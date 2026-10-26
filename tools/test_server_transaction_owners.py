# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Транзакционные владельцы 15 многошаговых операций (Alpha 2.773, завершение A-4).
#
# БЕЗ сервера/принтеров/сети/рабочей БД: production-функции извлекаются из server.py через AST
# (ast.get_source_segment — дословный исходник) и исполняются со стабами; БД — sqlite3 ':memory:';
# отказы вносятся оборачивающим соединением, поэтому сохраняется НАСТОЯЩАЯ семантика sqlite.
#
# Проверяется: владелец откатывает всю связанную операцию; откат идёт ПОД ТЕМ ЖЕ локом; чужой
# последующий commit не фиксирует остаток; post-commit хуки НЕ откатывают подтверждённую
# транзакцию; общий lock-менеджер не получил глобального rollback.
#
# Запуск: python tools/test_server_transaction_owners.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import json
import os
import sqlite3
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

# Все 15 кандидатов A-4 (Alpha 2.772) — каждый обязан быть классифицирован и покрыт.
CANDIDATES = ["init_db", "delete_project", "_ensure_project_part", "delete_project_part",
              "_insert_parsed_file", "delete_project_file", "restore_project_file", "add_manual_part",
              "finish_project_print_job", "_import_projects2_archive", "staging_to_project",
              "request_part_rework", "staging_delete", "s_parts", "s_printers"]
# Транзакционные владельцы, появившиеся ПОСЛЕ Alpha 2.772. Каждый добавляется сюда ЯВНО (иначе S3
# краснеет) и проверяется наравне с историческими: блок обязан быть обёрнут владельцем отката.
#   _reconcile_owner_files — Alpha 2.802: обновление stored_path при согласовании папок проекта.
#   _rename_owner_dir_to_desired — Alpha 2.803: обновление stored_path при переименовании папки.
#   rename_project_atomic — Alpha 2.804: projects.name + все stored_path проекта ОДНОЙ транзакцией.
#   apply_mutation / restore_full — Alpha 2.827: применение/откат восстановления конфигурации
#     (config-backup) пишут app_settings и printers транзакционно с владельцем отката.
#   _carry_task_counts — Alpha 2.976: перенос счёта задачи в детали проекта; план,
#     напечатанное и заметки пишутся одной транзакцией.
LATER_OWNERS = ["_reconcile_owner_files", "_rename_owner_dir_to_desired", "rename_project_atomic",
                "apply_mutation", "restore_full", "_carry_task_counts"]
ALL_OWNERS = CANDIDATES + LATER_OWNERS

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


def grab(fn_name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name:
            return ast.get_source_segment(SRC, n)
    raise AssertionError("функция не найдена: " + fn_name)


class TrackLock(object):
    """Лок, который помнит, удерживался ли он в момент отката."""

    def __init__(self):
        self._l = threading.Lock()
        self.held = False

    def __enter__(self):
        self._l.acquire()
        self.held = True
        return self

    def __exit__(self, *a):
        self.held = False
        self._l.release()
        return False

    def locked(self):
        return self._l.locked()


class FaultConn(object):
    def __init__(self, real, lock=None, fail_on_write=None, fail_commit=False, fail_rollback=False):
        self._real = real
        self._lock = lock
        self.fail_on_write = fail_on_write
        self.fail_commit = fail_commit
        self.fail_rollback = fail_rollback
        self.writes = 0
        self.commits = 0
        self.rollbacks = 0
        self.rollback_under_lock = []

    def execute(self, sql, *a, **k):
        if str(sql).lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
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


DDL = [
    ("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT, is_deleted INTEGER DEFAULT 0)"),
    ("CREATE TABLE project_parts (id TEXT PRIMARY KEY, project_id TEXT, part_name TEXT, "
     "norm_name TEXT, required_qty INTEGER DEFAULT 0, printed_qty INTEGER DEFAULT 0, "
     "rework_qty INTEGER DEFAULT 0, rework_done INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0, "
     "order_idx INTEGER DEFAULT 0, updated_at TEXT)"),
    ("CREATE TABLE project_file_parts (id TEXT PRIMARY KEY, project_id TEXT, file_id TEXT, "
     "part_id TEXT, on_plate_qty INTEGER DEFAULT 1, updated_at TEXT)"),
    ("CREATE TABLE project_print_jobs (id TEXT PRIMARY KEY, snapshot_json TEXT, status TEXT, "
     "counted_at TEXT DEFAULT '', finished_at TEXT)"),
]


def make_env(fail_on_write=None, fail_commit=False, fail_rollback=False, hook_raises=False):
    real = sqlite3.connect(":memory:", check_same_thread=False)
    real.row_factory = sqlite3.Row
    for d in DDL:
        real.execute(d)
    real.commit()
    lock = TrackLock()
    conn = FaultConn(real, lock, fail_on_write, fail_commit, fail_rollback)
    log = _Log()
    hooks = {"calls": 0}

    def _recompute_project_part_status(pid):
        hooks["calls"] += 1
        if hook_raises:
            raise RuntimeError("hook failure (post-commit)")

    ns = {"time": time, "json": json, "threading": threading, "os": os,
          "conn_p": conn, "lock_p": lock, "log": log, "_exc_brief": (lambda: "injected"),
          "_recompute_project_part_status": _recompute_project_part_status,
          "_uid": (lambda p="": p + "x"), "contextmanager": __import__("contextlib").contextmanager}
    # Дословный production-helper. ast.get_source_segment отдаёт функцию БЕЗ декоратора,
    # поэтому навешиваем ровно тот же @contextmanager, что стоит на ней в server.py.
    exec(grab("_rollback_sqlite_on_error"), ns)
    ns["_rollback_sqlite_on_error"] = ns["contextmanager"](ns["_rollback_sqlite_on_error"])
    for f in ("delete_project_part", "finish_project_print_job"):
        exec(grab(f), ns)
    return ns, conn, lock, log, real, hooks


def seed(real):
    real.execute("INSERT INTO projects (id, name) VALUES ('pr1','P')")
    real.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
                 "VALUES ('pp1','pr1','A','a',5,0)")
    real.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id) VALUES ('fp1','pr1','f1','pp1')")
    real.commit()


print("=== A-4: транзакционные владельцы (Alpha 2.773) ===")

check("A0. helper и production-функции извлечены дословно",
      "def _rollback_sqlite_on_error" in grab("_rollback_sqlite_on_error")
      and "def finish_project_print_job" in grab("finish_project_print_job"))

# ═══ Шаблон 1: владелец с двумя последовательными DML ═══
ns, conn, lock, log, real, _h = make_env()
seed(real)
ns["delete_project_part"]("pr1", "pp1")
check("1a. успешный путь: обе записи удалены, один commit, без rollback",
      real.execute("SELECT COUNT(*) c FROM project_parts").fetchone()["c"] == 0
      and real.execute("SELECT COUNT(*) c FROM project_file_parts").fetchone()["c"] == 0
      and conn.commits == 1 and conn.rollbacks == 0)

ns, conn, lock, log, real, _h = make_env(fail_on_write=2)
seed(real)
try:
    ns["delete_project_part"]("pr1", "pp1")
except Exception:
    pass
check("1b. ошибка на 2-й DML: ПЕРВАЯ откачена (связь на месте)",
      real.execute("SELECT COUNT(*) c FROM project_file_parts").fetchone()["c"] == 1)
check("1c. соединение чистое", conn.in_transaction is False)
check("1d. откат выполнен ПОД ТЕМ ЖЕ локом", conn.rollbacks == 1 and all(conn.rollback_under_lock))
check("1e. лок освобождён после исключения", not lock.locked())
# чужой последующий commit не должен зафиксировать остаток
with lock:
    conn.execute("UPDATE projects SET name='X' WHERE id='pr1'")
    conn.commit()
check("1f. чужой commit НЕ зафиксировал остаток провалившейся операции",
      real.execute("SELECT COUNT(*) c FROM project_file_parts").fetchone()["c"] == 1
      and real.execute("SELECT name FROM projects WHERE id='pr1'").fetchone()["name"] == "X")

# ═══ Шаблон 2: цикл DML + один commit (finish_project_print_job) ═══
def seed_job(real, qty=3):
    real.execute("INSERT INTO project_print_jobs (id, snapshot_json, status, counted_at) "
                 "VALUES ('job1',?, 'dispatched','')", (json.dumps([{"part_id": "pp1", "qty": qty}]),))
    real.commit()


ns, conn, lock, log, real, hooks = make_env()
seed(real); seed_job(real)
r = ns["finish_project_print_job"]("job1")
row = real.execute("SELECT printed_qty FROM project_parts WHERE id='pp1'").fetchone()
check("2a. успешный путь: задание засчитано, деталь прибавлена, возврат True",
      r is True and row["printed_qty"] == 3 and conn.rollbacks == 0)
check("2b. post-commit хук вызван ПОСЛЕ фиксации (вне транзакции)", hooks["calls"] == 1)

ns, conn, lock, log, real, hooks = make_env(fail_on_write=2)
seed(real); seed_job(real)
try:
    ns["finish_project_print_job"]("job1")
except Exception:
    pass
job = real.execute("SELECT status, counted_at FROM project_print_jobs WHERE id='job1'").fetchone()
part = real.execute("SELECT printed_qty FROM project_parts WHERE id='pp1'").fetchone()
check("2c. [КРИТИЧНО] сбой в цикле: задание НЕ помечено засчитанным, деталь НЕ прибавлена",
      job["counted_at"] == "" and job["status"] == "dispatched" and part["printed_qty"] == 0)
check("2d. соединение чистое, откат под локом",
      conn.in_transaction is False and conn.rollbacks == 1 and all(conn.rollback_under_lock))
check("2e. post-commit хук НЕ вызывался при откате", hooks["calls"] == 0)

# ═══ Шаблон 3: сбой самого commit ═══
ns, conn, lock, log, real, hooks = make_env(fail_commit=True)
seed(real); seed_job(real)
try:
    ns["finish_project_print_job"]("job1")
except Exception:
    pass
check("3a. сбой commit: всё откачено",
      real.execute("SELECT printed_qty FROM project_parts WHERE id='pp1'").fetchone()["printed_qty"] == 0)
check("3b. соединение пригодно дальше", conn.in_transaction is False)
conn.fail_commit = False
with lock:
    conn.execute("UPDATE projects SET name='OK' WHERE id='pr1'")
    conn.commit()
check("3c. следующая операция сохраняется нормально",
      real.execute("SELECT name FROM projects WHERE id='pr1'").fetchone()["name"] == "OK")

# ═══ Шаблон 4: ошибка post-commit хука НЕ откатывает подтверждённую транзакцию ═══
ns, conn, lock, log, real, hooks = make_env(hook_raises=True)
seed(real); seed_job(real)
try:
    ns["finish_project_print_job"]("job1")
except Exception:
    pass
check("4. [КРИТИЧНО] сбой post-commit хука НЕ откатывает уже зафиксированный результат",
      real.execute("SELECT printed_qty FROM project_parts WHERE id='pp1'").fetchone()["printed_qty"] == 3
      and real.execute("SELECT counted_at FROM project_print_jobs WHERE id='job1'").fetchone()["counted_at"] != ""
      and conn.rollbacks == 0)

# ═══ Шаблон 5: сбой самого rollback не теряет исходную ошибку ═══
ns, conn, lock, log, real, hooks = make_env(fail_on_write=2, fail_rollback=True)
seed(real); seed_job(real)
_orig = None
try:
    ns["finish_project_print_job"]("job1")
except Exception as e:
    _orig = e
check("5a. исходное исключение доходит до вызывающего (не подменено ошибкой отката)",
      isinstance(_orig, sqlite3.OperationalError) and "injected write failure" in str(_orig))
check("5b. сбой отката записан в журнал отдельно и безопасно",
      any("rollback failed" in s.lower() for s in log.lines)
      and not any("INSERT" in s or "UPDATE" in s for s in log.lines))

# ═══ Шаблон 6: helper не трогает соединение без открытой транзакции ═══
ns, conn, lock, log, real, hooks = make_env()
try:
    with lock, ns["_rollback_sqlite_on_error"](conn, "noop"):
        raise RuntimeError("no db work at all")
except RuntimeError:
    pass
check("6. без открытой транзакции helper не вызывает rollback (in_transaction=False)",
      conn.rollbacks == 0)

# ═══ Статические проверки по всем 15 кандидатам ═══
print("--- статические проверки ---")


def code_only(text):
    import io
    import tokenize
    try:
        t = ast.parse(text)
    except Exception:
        return text
    blank = set()
    for node in ast.walk(t):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                blank.add(ln)
    rows = ["\n" if (i + 1) in blank else r for i, r in enumerate(text.splitlines(True))]
    txt = "".join(rows)
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


CODE = code_only(SRC)

# S1: каждый транзакционный lock-блок (DML + commit) во всех 15 обёрнут helper'ом
def txn_blocks(fn_name):
    """Блоки `with lock_*`, содержащие и DML, и commit: (обёрнут_ли, всего)."""
    fn = None
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name:
            fn = n
    wrapped = total = 0
    for w in ast.walk(fn):
        if not isinstance(w, ast.With):
            continue
        names = [it.context_expr.id for it in w.items
                 if isinstance(it.context_expr, ast.Name) and it.context_expr.id in ("lock_p", "lock_pr")]
        if not names:
            continue
        conn_name = "conn_p" if names[0] == "lock_p" else "conn_pr"
        has_dml = has_commit = False
        for n in ast.walk(w):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == conn_name:
                if n.func.attr in ("execute", "executemany") and n.args:
                    a = n.args[0]
                    s = (a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else "").strip().upper()
                    if s.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
                        has_dml = True
                elif n.func.attr == "commit":
                    has_commit = True
        if not (has_dml and has_commit):
            continue
        total += 1
        if any(isinstance(it.context_expr, ast.Call)
               and getattr(it.context_expr.func, "id", "") == "_rollback_sqlite_on_error" for it in w.items):
            wrapped += 1
    return wrapped, total


unclassified = []
for name in ALL_OWNERS:
    w, t = txn_blocks(name)
    if t == 0 or w != t:
        unclassified.append("%s (%d/%d)" % (name, w, t))
check("S1. все транзакционные блоки всех 15 кандидатов обёрнуты владельцем: %s"
      % ("да" if not unclassified else "НЕТ -> " + ", ".join(unclassified)), not unclassified)

check("S2. общий lock-менеджер НЕ получил глобального rollback "
      "(lock_p/lock_pr — обычные threading.Lock)",
      "lock_p, lock_pr = threading.Lock(), threading.Lock()" in CODE
      and "class _RollbackLock" not in CODE and "def lock_p" not in CODE)

# S3: helper применяется только к разрешённому белому списку функций
used_in = set()
for n in ast.walk(TREE):
    if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_rollback_sqlite_on_error":
        for a in ast.walk(TREE):
            if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and a.lineno <= n.lineno <= (a.end_lineno or a.lineno):
                used_in.add(a.name)
extra = used_in - set(ALL_OWNERS)
check("S3. helper используется только в белом списке 15 владельцев: %s"
      % ("да" if not extra else "ЛИШНИЕ -> " + ", ".join(sorted(extra))), not extra)

check("S4. helper не берёт lock и не делает commit",
      "lock_p" not in code_only(grab("_rollback_sqlite_on_error"))
      and "commit()" not in code_only(grab("_rollback_sqlite_on_error")))
check("S5. helper перевыбрасывает исходное исключение",
      "raise" in code_only(grab("_rollback_sqlite_on_error")))
check("S6. read-only lock-блок в delete_project_file НЕ обёрнут (helper не в read-only коде)",
      txn_blocks("delete_project_file") == (1, 1))
check("S7. VACUUM в init_db остаётся вне транзакции (isolation_level=None)",
      "isolation_level = None" in CODE and "VACUUM" in CODE)
check("S8. правки Alpha 2.772 на месте (три обработчика очереди сохранили rollback)",
      CODE.count("conn_pr.rollback()") >= 3)

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
