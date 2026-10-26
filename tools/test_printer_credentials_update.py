# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Безопасное сохранение учётных данных принтеров (Alpha 2.776).
#
# БЕЗ сервера/сети/принтеров/рабочей БД/DATA_DIR: обработчик s_printers и helper merge
# извлекаются из server.py ДОСЛОВНО через AST и исполняются со стабами; БД — ':memory:'.
# Настоящих credentials здесь нет — только заведомо фиктивные тестовые строки.
#
# CHARACTERIZATION: до 2.776 UPSERT делал token=excluded.token и serial=excluded.serial
# БЕЗУСЛОВНО. Фронт отдаёт весь массив принтеров при любом сохранении, поэтому пустое
# или потерянное поле формы стирало учётные данные — и не только у редактируемого
# принтера, а у всех сразу. Ферма молча теряла связь со всем парком.
#
# Запуск: python tools/test_printer_credentials_update.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import os
import sqlite3
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)
#  16.10.2026 (R-020): s_printers проверяет адрес нового или изменённого принтера чистым модулем
#  app/printer_address.py — песочнице нужен тот же модуль, что и серверу.
sys.path.insert(0, REPO)
from app import printer_address as _paddr  # noqa: E402

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


class P(object):
    """Заменитель PrUpdate: ровно те атрибуты, что читает обработчик."""

    def __init__(self, pid, name="P", type="bambu", ip="10.0.0.1", port=None,
                 token=None, gen="auto", serial=None, model=""):
        self.id = pid; self.name = name; self.type = type; self.ip = ip
        self.port = port; self.token = token; self.gen = gen
        self.serial = serial; self.model = model


class _Log(object):
    def __init__(self):
        self.lines = []

    def _mk(self, lvl):
        def rec(*a, **k):
            try:
                self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
            except Exception:
                self.lines.append(str(a))
        return rec

    def __getattr__(self, item):
        return self._mk(item)


DDL = ("CREATE TABLE printers (id TEXT PRIMARY KEY, name TEXT, type TEXT DEFAULT 'bambu', "
       "ip TEXT, port INTEGER, token TEXT, last_parts TEXT DEFAULT '{}', order_idx INTEGER DEFAULT 0, "
       "gen TEXT DEFAULT 'auto', serial TEXT DEFAULT '', model TEXT DEFAULT '')")


def make_env(rows=(), fail_on_write=None):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(DDL)
    for r in rows:
        conn.execute("INSERT INTO printers (id, name, type, ip, port, token, serial, last_parts, order_idx) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (r["id"], r.get("name", "P"), r.get("type", "bambu"), r.get("ip", "10.0.0.1"),
                      r.get("port"), r.get("token", ""), r.get("serial", ""), "{}", r.get("order_idx", 0)))
    conn.commit()

    class Faulty(object):
        def __init__(self, real):
            self._real = real; self.writes = 0

        def execute(self, sql, *a, **k):
            s = str(sql).lstrip().upper()
            if s.startswith(("INSERT", "UPDATE", "DELETE")):
                self.writes += 1
                if fail_on_write == self.writes:
                    raise sqlite3.OperationalError("injected write failure")
            return self._real.execute(sql, *a, **k)

        @property
        def in_transaction(self):
            return self._real.in_transaction

        def __getattr__(self, i):
            return getattr(self._real, i)

    fconn = Faulty(conn)
    log = _Log()
    ns = {"threading": threading, "os": os, "log": log, "_exc_brief": (lambda: "injected"),
          "conn_pr": fconn, "lock_pr": threading.Lock(),
          "contextmanager": __import__("contextlib").contextmanager,
          "_req_role": (lambda req: None), "_has_perm": (lambda r, p: True),
          "restart_workers": (lambda: None), "_apply_project_print_fuses": (lambda: None),
          "JSONResponse": (lambda d, status_code=200: {"_json": d, "_code": status_code}),
          "List": list, "PrUpdate": P, "Request": object, "_paddr": _paddr}
    exec(grab("_rollback_sqlite_on_error"), ns)
    ns["_rollback_sqlite_on_error"] = ns["contextmanager"](ns["_rollback_sqlite_on_error"])
    if any(isinstance(n, ast.FunctionDef) and n.name == "_merge_printer_secret" for n in ast.walk(TREE)):
        exec(grab("_merge_printer_secret"), ns)
    exec(grab("s_printers"), ns)
    return ns, conn, fconn, log


def creds(conn):
    return {r["id"]: (r["token"], r["serial"])
            for r in conn.execute("SELECT id, token, serial FROM printers")}


TOK_A, TOK_B = "FAKE-TOKEN-AAA", "FAKE-TOKEN-BBB"
SER_A, SER_B = "FAKESERIALA", "FAKESERIALB"
TWO = [{"id": "p1", "token": TOK_A, "serial": SER_A},
       {"id": "p2", "token": TOK_B, "serial": SER_B}]

print("=== Alpha 2.776: сохранение учётных данных принтеров ===")

check("A0. обработчик s_printers извлечён дословно", "def s_printers" in grab("s_printers"))

# ═══ 1-4. Сохранение БЕЗ credential не стирает его ═══
for label, tok in (("ключ отсутствует (None)", None), ("пустая строка", ""), ("только пробелы", "   ")):
    ns, conn, _, _ = make_env(TWO)
    ns["s_printers"]([P("p1", name="Новое имя", token=tok, serial=tok), P("p2", token=tok, serial=tok)], None)
    c = creds(conn)
    check("1. [ХАРАКТЕРИЗАЦИЯ] %-24s -> token и serial СОХРАНЕНЫ у обоих" % label,
          c["p1"] == (TOK_A, SER_A) and c["p2"] == (TOK_B, SER_B))

# ═══ 5. Новое непустое значение заменяет ═══
ns, conn, _, _ = make_env(TWO)
ns["s_printers"]([P("p1", token="FAKE-NEW-AAA", serial="FAKENEWA"), P("p2")], None)
c = creds(conn)
check("5. новое непустое значение заменяет старое", c["p1"] == ("FAKE-NEW-AAA", "FAKENEWA"))
check("5b. и НЕ трогает второй принтер", c["p2"] == (TOK_B, SER_B))

# ═══ 6-7. Новый принтер ═══
ns, conn, _, _ = make_env(TWO)
ns["s_printers"]([P("p1"), P("p2"), P("p3", token="FAKE-NEW-CCC", serial="FAKENEWC")], None)
c = creds(conn)
check("6. новый принтер с непустым token — сохранён", c["p3"] == ("FAKE-NEW-CCC", "FAKENEWC"))
ns, conn, _, _ = make_env(TWO)
ns["s_printers"]([P("p1"), P("p2"), P("p4", token="", serial="")], None)
check("7. новый принтер с пустым token — создан без token (пустая строка)",
      creds(conn)["p4"] == ("", ""))

# ═══ 10. Изменение одного принтера не трогает остальные ═══
ns, conn, _, _ = make_env(TWO)
ns["s_printers"]([P("p1", name="Переименован", ip="10.0.0.99"), P("p2")], None)
c = creds(conn)
check("10. правка имени/адреса одного принтера не меняет credentials обоих",
      c["p1"] == (TOK_A, SER_A) and c["p2"] == (TOK_B, SER_B))

# ═══ 11. Удаление принтера не трогает credentials остальных ═══
ns, conn, _, _ = make_env(TWO + [{"id": "p3", "token": "FAKE-TOKEN-CCC", "serial": "FAKESERIALC"}])
ns["s_printers"]([P("p1"), P("p2")], None)
c = creds(conn)
check("11. удаление p3 (его нет в массиве) не тронуло credentials p1/p2",
      c == {"p1": (TOK_A, SER_A), "p2": (TOK_B, SER_B)})

# ═══ 12. Смешанный batch ═══
ns, conn, _, _ = make_env(TWO)
ns["s_printers"]([P("p1", token="FAKE-ROTATED"), P("p2", token=None)], None)
c = creds(conn)
check("12. смешанный batch: у одного новый token, у второго сохранён старый",
      c["p1"][0] == "FAKE-ROTATED" and c["p2"][0] == TOK_B)

# ═══ 13-14. Ошибка на N-м элементе: batch откатывается, соединение чистое ═══
ns, conn, fconn, _ = make_env(TWO, fail_on_write=3)   # 1=DELETE, 2=UPSERT p1, 3=UPSERT p2
_raised = None
try:
    ns["s_printers"]([P("p1", token="FAKE-X"), P("p2", token="FAKE-Y")], None)
except Exception as e:
    _raised = e
c = creds(conn)
check("13. сбой на 2-м принтере откатил ВЕСЬ batch (all-or-nothing сохранён)",
      c["p1"] == (TOK_A, SER_A) and c["p2"] == (TOK_B, SER_B))
check("14. соединение не осталось в открытой транзакции", fconn.in_transaction is False)

# ═══ 15. Устаревшая форма не стирает более новый credential ═══
ns, conn, _, _ = make_env(TWO)
# B: другой запрос сменил токен p1
ns["s_printers"]([P("p1", token="FAKE-ROTATED-BY-B"), P("p2")], None)
# A: форма была открыта ДО этого и сохраняет только имя, credential не передаёт
ns["s_printers"]([P("p1", name="Имя из старой формы"), P("p2")], None)
c = creds(conn)
check("15. [КЛЮЧЕВОЕ] устаревшая форма НЕ вернула старый токен и не стёрла новый",
      c["p1"][0] == "FAKE-ROTATED-BY-B")

# ═══ 16. Нельзя перенести credential между принтерами ═══
ns, conn, _, _ = make_env(TWO)
ns["s_printers"]([P("p1", name="p2-подделка"), P("p2")], None)
c = creds(conn)
check("16. credential не переносится между printer id (merge строго по своему id)",
      c["p1"][0] == TOK_A and c["p2"][0] == TOK_B)

# ═══ 17. Дублирующий id в массиве ═══
ns, conn, _, _ = make_env(TWO)
ns["s_printers"]([P("p1", name="раз"), P("p1", name="два"), P("p2")], None)
c = creds(conn)
check("17. дублирующий id не приводит к потере credential", c["p1"][0] == TOK_A)

# ═══ 12b. Пустой массив ═══
ns, conn, _, _ = make_env(TWO)
ns["s_printers"]([], None)
check("12b. пустой массив удаляет всех (контракт не изменён)", creds(conn) == {})

# ═══ 19. Секрет не попадает в журнал ═══
ns, conn, _, log = make_env(TWO)
ns["s_printers"]([P("p1", token="FAKE-SECRET-IN-LOG")], None)
check("19. значение credential не появилось в журнале",
      not any(("FAKE-SECRET-IN-LOG" in s) or (TOK_A in s) for s in log.lines))

# ═══ Статические проверки ═══
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


BODY = code_only(grab("s_printers"))
# Дефект был НЕ в самом выражении token=excluded.token: excluded.* ссылается на то, что мы
# подставили в параметры INSERT. Ломало именно то, что туда уходило СЫРОЕ значение формы.
# Поэтому верный инвариант — в параметры идут смерженные _tok/_ser, а не p.token/p.serial.
check("S1. в параметры INSERT идёт смерженный token, а не сырое поле формы",
      "_tok" in BODY and "p.token" not in BODY)
check("S2. в параметры INSERT идёт смерженный serial, а не сырое поле формы",
      "_ser" in BODY and "getattr(p, 'serial', '') or ''" not in BODY)
check("S3. текущие значения читаются ВНУТРИ той же транзакции (merge не по данным формы)",
      "SELECT id, token, serial" in BODY)   # 16.10.2026 (R-020): в ту же выборку добавлен ip
check("S4. merge выполняется явным helper'ом", "_merge_printer_secret" in BODY)
check("S5. блок остаётся transaction owner с откатом",
      "_rollback_sqlite_on_error(conn_pr" in BODY and BODY.count("conn_pr.commit()") == 1)
check("S6. GET /api/printers в этой версии НЕ изменён (временный контракт 2.776)",
      "SELECT * FROM printers ORDER BY order_idx ASC" in code_only(grab("g_printers")))
check("S7. ролевая модель и права не тронуты",
      "printer_delete" in BODY and "_route_perm" in SRC)


def decorated_with(fn_name, route):
    """Навешен ли декоратор маршрута ИМЕННО на эту функцию (а не на соседнюю)."""
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name:
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and route in (ast.unparse(d) or ""):
                    return True
    return False


# Ловушка, на которую я сам наступил: helper, вставленный МЕЖДУ декоратором и функцией,
# перехватывает маршрут на себя, и обработчик перестаёт быть роутом. Тесты, вызывающие
# функцию напрямую через AST, этого не видят — поэтому проверяем привязку явно.
check("S8. маршрут /api/printers/save навешен именно на s_printers",
      decorated_with("s_printers", "/api/printers/save"))
check("S9. helper _merge_printer_secret НЕ является маршрутом",
      not decorated_with("_merge_printer_secret", "/api/"))

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
