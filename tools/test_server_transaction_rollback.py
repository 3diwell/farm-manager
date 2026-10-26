# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Тесты атомарного отката незавершённых транзакций SQLite (Alpha 2.772, дефект A-4).
#
# БЕЗ сервера/принтеров/сети/рабочей БД: production-функции ИЗВЛЕКАЮТСЯ ИЗ server.py через AST
# (ast.get_source_segment — дословный исходник, без декораторов) и исполняются со стабами.
# БД — sqlite3 ':memory:'; отказы вносятся оборачивающим соединением (fault injection),
# поэтому сохраняется НАСТОЯЩАЯ транзакционная семантика sqlite (in_transaction и т.п.).
#
# CHARACTERIZATION: до Alpha 2.772 обработчик ошибки не вызывал rollback(), поэтому первая
# запись оставалась в НЕЗАВЕРШЁННОЙ транзакции общего соединения — и её фиксировал следующий
# посторонний commit() любого другого кода на том же соединении.
#
# Запуск: python tools/test_server_transaction_rollback.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import json as _jsonmod
import os
import sqlite3
import sys
import threading
import time
from typing import Any, Dict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


def grab(fn_name):
    """Дословный исходник production-функции по имени (без декораторов)."""
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name:
            return ast.get_source_segment(SRC, n)
    raise AssertionError("функция не найдена: " + fn_name)


# ── инструментированный lock: фиксирует, удерживался ли он в момент rollback ──
class TrackLock(object):
    def __init__(self):
        self._l = threading.Lock()
        self.held = False
        self.depth = 0

    def __enter__(self):
        self._l.acquire()
        self.held = True
        self.depth += 1
        return self

    def __exit__(self, *a):
        self.depth -= 1
        self.held = False
        self._l.release()
        return False

    def locked(self):
        return self._l.locked()


# ── соединение с внесением отказов: настоящая sqlite под капотом ──
class FaultConn(object):
    def __init__(self, real, lock=None, fail_on_write=None, fail_commit=False, fail_rollback=False):
        self._real = real
        self._lock = lock
        self.fail_on_write = fail_on_write     # номер execute-записи (1-based), на котором падаем
        self.fail_commit = fail_commit
        self.fail_rollback = fail_rollback
        self.writes = 0
        self.commits = 0
        self.rollbacks = 0
        self.rollback_under_lock = []          # держался ли lock в момент каждого rollback

    def execute(self, sql, *a, **k):
        s = str(sql).lstrip().upper()
        if s.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            self.writes += 1
            if self.fail_on_write == self.writes:
                raise sqlite3.OperationalError("injected write failure #%d" % self.writes)
        return self._real.execute(sql, *a, **k)

    def commit(self):
        if self.fail_commit:
            raise sqlite3.OperationalError("injected commit failure")
        self.commits += 1
        return self._real.commit()

    def rollback(self):
        self.rollbacks += 1
        self.rollback_under_lock.append(bool(self._lock and self._lock.held))
        if self.fail_rollback:
            raise sqlite3.OperationalError("injected rollback failure")
        return self._real.rollback()

    @property
    def in_transaction(self):
        return self._real.in_transaction

    def __getattr__(self, item):
        return getattr(self._real, item)


class _Log(object):
    def __init__(self):
        self.lines = []

    def _rec(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(str(a))

    debug = info = warning = error = exception = _rec


class _SendMgrStub(object):
    def reserve(self, pid, *a, **k):
        return (True, "send_" + str(pid), "")

    def cancel_reserved(self, *a, **k):
        return True

    def get_hold(self, pid):
        return None


DDL = ("CREATE TABLE print_launch_queue (id TEXT PRIMARY KEY, batch_id TEXT DEFAULT '', "
       "printer_id TEXT, printer_name TEXT DEFAULT '', flow TEXT DEFAULT 'quick', "
       "job_ref TEXT DEFAULT '', due_ts REAL, status TEXT DEFAULT 'pending', "
       "attempts INTEGER DEFAULT 0, last_error TEXT DEFAULT '', payload TEXT DEFAULT '', "
       "created_at REAL, updated_at REAL, recovery_eligible INTEGER DEFAULT 1)")


def make_ns(fail_on_write=None, fail_commit=False, fail_rollback=False, rows=()):
    """Окружение с извлечёнными production-функциями и in-memory БД."""
    real = sqlite3.connect(":memory:", check_same_thread=False)
    real.row_factory = sqlite3.Row
    real.execute(DDL)
    real.commit()
    lock = TrackLock()
    conn = FaultConn(real, lock, fail_on_write, fail_commit, fail_rollback)
    for r in rows:
        real.execute("INSERT INTO print_launch_queue (id, printer_id, due_ts, status, created_at, updated_at, "
                     "recovery_eligible, payload) VALUES (?,?,?,?,?,?,?,?)",
                     (r["id"], r.get("printer_id", "P"), r.get("due_ts", time.time()), r["status"],
                      time.time(), time.time(), r.get("eligible", 1), r.get("payload", "{}")))
    real.commit()
    log = _Log()
    ns = {
        "time": time, "threading": threading, "os": os,
        "conn_pr": conn, "lock_pr": lock, "log": log, "_exc_brief": (lambda: "injected"),
        "print_queue": [], "print_queue_lock": threading.Lock(), "_print_queue_seq": 0,
        "_send_mgr": _SendMgrStub(), "_jsonmod": _jsonmod, "_PLQ_RECOVERY_GRACE": 25.0,
        "_uid": (lambda p="": p + "x"), "_hold_public": (lambda h: h),
        "_print_queue_public": (lambda: []), "_print_queue_recovered": False,
        "Dict": Dict, "Any": Any,
    }
    for _f in ("_print_queue_recover", "api_print_queue_durable_cancel", "api_print_queue_recovery_continue"):
        exec(grab(_f), ns)
    return ns, conn, lock, log, real


def rows_by_status(real):
    return {r["id"]: r["status"] for r in real.execute("SELECT id, status FROM print_launch_queue")}


print("=== A-4: атомарный откат многошаговых операций SQLite ===")

check("A0. production-функции извлечены дословно из server.py",
      "def _print_queue_recover" in grab("_print_queue_recover")
      and "durable-cancel update failed" in grab("api_print_queue_durable_cancel"))

# ═══ 1. Успешный путь: обе записи сохраняются, один commit, rollback НЕ вызывается ═══
ns, conn, lock, log, real = make_ns(rows=[{"id": "r1", "status": "launching"}, {"id": "r2", "status": "pending"}])
ns["_print_queue_recover"]()
st = rows_by_status(real)
check("1a. успешный путь: обе записи сохранены (launching→attention, pending→hold)",
      st["r1"] == "recovery_attention" and st["r2"] == "recovery_hold")
check("1b. успешный путь: ровно один commit и НИ ОДНОГО rollback",
      conn.commits == 1 and conn.rollbacks == 0)
check("1c. соединение чистое (транзакция закрыта)", conn.in_transaction is False)

# ═══ 2. Ошибка на ПЕРВОЙ записи: ничего не сохранено, соединение чистое ═══
ns, conn, lock, log, real = make_ns(fail_on_write=1, rows=[{"id": "r1", "status": "launching"},
                                                           {"id": "r2", "status": "pending"}])
ns["_print_queue_recover"]()
st = rows_by_status(real)
check("2a. ошибка на 1-й записи: данные не изменились",
      st["r1"] == "launching" and st["r2"] == "pending")
check("2b. соединение чистое (in_transaction == False)", conn.in_transaction is False)

# ═══ 3. Ошибка на ВТОРОЙ записи: первая ОТКАТЫВАЕТСЯ; чужой commit её не фиксирует ═══
ns, conn, lock, log, real = make_ns(fail_on_write=2, rows=[{"id": "r1", "status": "launching"},
                                                           {"id": "r2", "status": "pending"}])
ns["_print_queue_recover"]()
check("3a. [ХАРАКТЕРИЗАЦИЯ A-4] первая запись ОТКАЧЕНА (r1 остался launching)",
      rows_by_status(real)["r1"] == "launching")
check("3b. соединение чистое после сбоя", conn.in_transaction is False)
# посторонний последующий commit другого кода на ТОМ ЖЕ соединении
with lock:
    conn.execute("UPDATE print_launch_queue SET status='sent' WHERE id='r2'")
    conn.commit()
st = rows_by_status(real)
check("3c. [ХАРАКТЕРИЗАЦИЯ A-4] чужой commit НЕ зафиксировал остаток неудачной операции",
      st["r1"] == "launching" and st["r2"] == "sent")

# ═══ 4. Ошибка самого commit: выполняется rollback, соединение пригодно дальше ═══
ns, conn, lock, log, real = make_ns(fail_commit=True, rows=[{"id": "r1", "status": "launching"},
                                                            {"id": "r2", "status": "pending"}])
ns["_print_queue_recover"]()
check("4a. сбой commit: записи откачены", rows_by_status(real)["r1"] == "launching")
check("4b. сбой commit: rollback выполнен", conn.rollbacks >= 1)
check("4c. соединение пригодно для следующей операции", conn.in_transaction is False)
conn.fail_commit = False
with lock:
    conn.execute("UPDATE print_launch_queue SET status='canceled' WHERE id='r1'")
    conn.commit()
check("4d. следующая операция на том же соединении успешна",
      rows_by_status(real)["r1"] == "canceled")

# ═══ 5. Ошибка САМОГО rollback: исходная ошибка не теряется, ложного успеха нет ═══
ns, conn, lock, log, real = make_ns(fail_on_write=2, fail_rollback=True,
                                    rows=[{"id": "r1", "status": "launching"}, {"id": "r2", "status": "pending"}])
_raised = None
try:
    ns["_print_queue_recover"]()
except Exception as e:
    _raised = e
check("5a. сбой rollback не выбрасывает исключение наружу (политика ошибки прежняя)", _raised is None)
check("5b. исходная ошибка залогирована", any("recovery hold failed" in s for s in log.lines))
check("5c. сбой самого rollback залогирован отдельно и безопасно",
      any("rollback" in s.lower() for s in log.lines))
check("5d. попытка rollback была", conn.rollbacks >= 1)

# ═══ 6/8/9. rollback под тем же lock; lock освобождён после исключения ═══
ns, conn, lock, log, real = make_ns(fail_on_write=2, rows=[{"id": "r1", "status": "launching"},
                                                           {"id": "r2", "status": "pending"}])
ns["_print_queue_recover"]()
check("8. rollback выполнен ПОД ТЕМ ЖЕ lock, что и SQL-записи",
      conn.rollbacks >= 1 and all(conn.rollback_under_lock))
check("9. после исключения lock освобождён", not lock.locked() and lock.depth == 0)

# ═══ 10. Два последовательных вызова: первый падает, второй проходит ═══
ns, conn, lock, log, real = make_ns(fail_on_write=2, rows=[{"id": "r1", "status": "launching"},
                                                           {"id": "r2", "status": "pending"}])
ns["_print_queue_recover"]()
check("10a. первый вызов не оставил данных", rows_by_status(real)["r1"] == "launching")
conn.fail_on_write = None
ns["_print_queue_recovered"] = False          # повторный прогон в том же процессе
ns["_print_queue_recover"]()
st = rows_by_status(real)
check("10b. второй вызов успешен и его данные на месте",
      st["r1"] == "recovery_attention" and st["r2"] == "recovery_hold")
check("10c. соединение чистое", conn.in_transaction is False)

# ═══ 11. durable-cancel: тот же шаблон, тот же контракт ответа ═══
ns, conn, lock, log, real = make_ns(rows=[{"id": "d1", "status": "pending"}])
r = ns["api_print_queue_durable_cancel"]({"id": "d1"})
check("11a. durable-cancel успешный путь: контракт ответа не изменён",
      r.get("ok") is True and r.get("canceled") == 1 and rows_by_status(real)["d1"] == "canceled")

ns, conn, lock, log, real = make_ns(fail_on_write=1, rows=[{"id": "d1", "status": "pending"}])
r = ns["api_print_queue_durable_cancel"]({"id": "d1"})
check("11b. durable-cancel при сбое: прежний контракт ошибки сохранён",
      r.get("ok") is False and r.get("error") == "update failed" and r.get("canceled") == 0)
check("11c. durable-cancel при сбое: соединение чистое, данные не изменились",
      conn.in_transaction is False and rows_by_status(real)["d1"] == "pending")

# durable-cancel выполняет за вызов ОДНУ запись (ветки if/else), поэтому «частичного состояния
# между записями» там не бывает. Реальный риск ровно один — сбой самого commit: запись осталась бы
# в незавершённой транзакции, пользователю вернулось бы «отмена не удалась», а следующий чужой
# commit молча зафиксировал бы отмену.
ns, conn, lock, log, real = make_ns(fail_commit=True, rows=[{"id": "d1", "status": "pending"}])
r = ns["api_print_queue_durable_cancel"]({"id": "d1"})
check("11d. durable-cancel: сбой commit → откат, ответ прежний", r.get("ok") is False and conn.rollbacks >= 1)
conn.fail_commit = False
with lock:
    conn.execute("UPDATE print_launch_queue SET status='sent' WHERE id='d1'")
    conn.commit()
check("11e. [ХАРАКТЕРИЗАЦИЯ] чужой commit не зафиксировал отменённую отмену",
      rows_by_status(real)["d1"] == "sent")

# ═══ 12. recovery-continue: сбой в середине цикла записей ═══
_payload = _jsonmod.dumps({"printer_id": "P1", "printer_name": "P1", "gcode_file": "a.gcode"})
ns, conn, lock, log, real = make_ns(fail_on_write=2,
                                    rows=[{"id": "c1", "status": "recovery_hold", "printer_id": "P1", "payload": _payload},
                                          {"id": "c2", "status": "recovery_hold", "printer_id": "P2", "payload": _payload}])
r = ns["api_print_queue_recovery_continue"]()
st = rows_by_status(real)
check("12a. recovery-continue: сбой в цикле откатил ВСЕ записи операции",
      st["c1"] == "recovery_hold" and st["c2"] == "recovery_hold")
check("12b. recovery-continue: соединение чистое", conn.in_transaction is False)
check("12c. recovery-continue: rollback под тем же lock", all(conn.rollback_under_lock))

# ═══ 13. Статические проверки production-кода ═══
print("--- статические проверки ---")


def code_only(text):
    """Код без комментариев и докстрок — иначе пояснения о rollback ломают проверку."""
    import io
    import tokenize
    try:
        tree = ast.parse(text)
    except Exception:
        return text
    blank = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                blank.add(ln)
    rows_ = ["\n" if (i + 1) in blank else r for i, r in enumerate(text.splitlines(True))]
    txt = "".join(rows_)
    try:
        cuts = {}
        for tok in tokenize.generate_tokens(io.StringIO(txt).readline):
            if tok.type == tokenize.COMMENT:
                cuts.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))
        rr = txt.splitlines(True)
        for row, spans in cuts.items():
            s = rr[row - 1]
            for a, b in sorted(spans, reverse=True):
                s = s[:a] + s[b:]
            rr[row - 1] = s
        return "".join(rr)
    except Exception:
        return txt


for _fn in ("_print_queue_recover", "api_print_queue_durable_cancel", "api_print_queue_recovery_continue"):
    body = code_only(grab(_fn))
    has_rb = "conn_pr.rollback()" in body
    # rollback обязан стоять ВНУТРИ `with lock_pr:` — то есть с отступом глубже строки with
    ok_pos = False
    if has_rb:
        lines = body.splitlines()
        wi = [i for i, l in enumerate(lines) if l.strip().startswith("with lock_pr")]
        ri = [i for i, l in enumerate(lines) if "conn_pr.rollback()" in l]
        ok_pos = bool(wi) and all(
            any(w < r and (len(l) - len(l.lstrip())) > (len(lines[w]) - len(lines[w].lstrip()))
                for w in wi for l in [lines[r]])
            for r in ri)
    check("S. %s: rollback есть и стоит ВНУТРИ with lock_pr" % _fn, has_rb and ok_pos)

check("S4. успешный путь не получил лишнего commit (по одному на операцию)",
      code_only(grab("_print_queue_recover")).count("conn_pr.commit()") == 1
      and code_only(grab("api_print_queue_durable_cancel")).count("conn_pr.commit()") == 1
      and code_only(grab("api_print_queue_recovery_continue")).count("conn_pr.commit()") == 1)
check("S5. голых except и новых `except Exception: pass` не добавлено",
      "except:" not in "".join(code_only(grab(f)) for f in
                               ("_print_queue_recover", "api_print_queue_durable_cancel",
                                "api_print_queue_recovery_continue")))

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
