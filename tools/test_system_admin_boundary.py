# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Административная граница для модулей и перезапуска (Alpha 2.778).
#
# БЕЗ сервера/сети/принтеров/рабочей БД/DATA_DIR: helper и обработчики извлекаются из
# server.py ДОСЛОВНО через AST и исполняются со стабами; БД пользователей — ':memory:'.
# Настоящий модуль не устанавливается, настоящий restart не выполняется — вместо файловых
# и процессных операций стоят шпионы, которые лишь фиксируют факт вызова.
#
# ЗАКРЫВАЕМАЯ ЦЕПОЧКА: установка ZIP кладёт на диск исполняемый backend.py -> перезапуск
# заставляет загрузчик его импортировать. Прежде оба шага требовали лишь права 'project'.
#
# Запуск: python tools/test_system_admin_boundary.py   (0 = все проверки пройдены)
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
sys.path.insert(0, REPO)
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

from app import security_policy as sp   # noqa: E402

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


print("=== Alpha 2.778: административная граница модулей и перезапуска ===")

# ═══ ЧАСТЬ 1. Чистое определение loopback ═══
LOOPBACK_YES = ["127.0.0.1", "127.1.2.3", "::1", "[::1]", " 127.0.0.1 ", "::ffff:127.0.0.1"]
LOOPBACK_NO = ["192.168.1.50", "10.0.0.7", "8.8.8.8", "0.0.0.0", "localhost", "LOCALHOST",
               "", None, "не-адрес", "127.0.0.1.evil.example", "::ffff:192.168.1.50",
               "fe80::1", "example.com"]
for a in LOOPBACK_YES:
    check("L. loopback  %-22r -> да" % a, sp.is_loopback_client(a) is True)
for a in LOOPBACK_NO:
    check("L. НЕ loopback %-20r -> нет" % a, sp.is_loopback_client(a) is False)

_POL = code_only(open(os.path.join(REPO, "app", "security_policy.py"), encoding="utf-8").read())
for h in ("X-Forwarded-For", "X-Real-IP", "Forwarded"):
    check("L. модуль политики не читает заголовок %s" % h, h not in _POL)
check("L. разбор через ipaddress, без startswith", "ipaddress.ip_address" in _POL)

# ═══ ЧАСТЬ 2. Поведение _require_system_admin ═══
DDL = "CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER DEFAULT 1)"


class Req(object):
    """Минимальная замена Request: адрес клиента и cookie сессии."""

    class _C(object):
        def __init__(self, host):
            self.host = host

    def __init__(self, client="127.0.0.1", cookie=None, no_client=False):
        self.client = None if no_client else Req._C(client)
        self.cookies = {"fm_session": cookie} if cookie else {}
        self.headers = {}


def make_env(security_on, users=(), sessions=None):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(DDL)
    for u in users:
        conn.execute("INSERT INTO users (id, username, role, is_active) VALUES (?,?,?,?)",
                     (u["id"], u.get("username", u["id"]), u["role"], u.get("is_active", 1)))
    conn.commit()
    sess = dict(sessions or {})

    def _session_user(req):
        tok = (getattr(req, "cookies", {}) or {}).get("fm_session", "")
        return dict(sess[tok]) if tok in sess else None

    ns = {"threading": threading, "os": os,
          "_SECURITY_ENABLED": security_on, "_session_user": _session_user,
          "conn_p": conn, "lock_p": threading.Lock(),
          "log": type("L", (), {"error": staticmethod(lambda *a, **k: None),
                                "info": staticmethod(lambda *a, **k: None),
                                "warning": staticmethod(lambda *a, **k: None),
                                "debug": staticmethod(lambda *a, **k: None)})(),
          "_exc_brief": (lambda: "x"), "_security_policy": sp,
          "JSONResponse": (lambda d, status_code=200: {"_json": d, "_code": status_code})}
    exec(grab("_require_system_admin"), ns)
    return ns["_require_system_admin"]


ADMIN_S = {"user_id": "u1", "username": "adm", "role": "admin"}
OPER_S = {"user_id": "u2", "username": "op", "role": "operator"}
OBS_S = {"user_id": "u3", "username": "ob", "role": "observer"}
USERS = [{"id": "u1", "role": "admin"}, {"id": "u2", "role": "operator"},
         {"id": "u3", "role": "observer"}, {"id": "u4", "role": "admin", "is_active": 0}]


def code_of(res):
    return None if res is None else res["_code"]


# ── AUTH ON ────────────────────────────────────────────────────────────────
g = make_env(True, USERS, {"tA": ADMIN_S, "tO": OPER_S, "tB": OBS_S,
                           "tD": {"user_id": "u4", "username": "old", "role": "admin"}})
check("1. AUTH ON, без сессии -> 401", code_of(g(Req(cookie=None))) == 401)
check("2. AUTH ON, недействительная сессия -> 401", code_of(g(Req(cookie="нет-такой"))) == 401)
check("3. AUTH ON, отключённая учётка (сессия выдана до отключения) -> 401",
      code_of(g(Req(cookie="tD"))) == 401)
check("4. AUTH ON, observer -> 403", code_of(g(Req(cookie="tB"))) == 403)
check("5. AUTH ON, operator -> 403", code_of(g(Req(cookie="tO"))) == 403)
check("6. AUTH ON, admin -> разрешено", g(Req(cookie="tA")) is None)
check("7. AUTH ON, admin даже с LAN-адреса -> разрешено (решает роль, не адрес)",
      g(Req(client="192.168.1.50", cookie="tA")) is None)
check("8. AUTH ON, loopback без сессии -> 401 (loopback НЕ заменяет вход)",
      code_of(g(Req(client="127.0.0.1", cookie=None))) == 401)

# ── AUTH OFF ───────────────────────────────────────────────────────────────
g2 = make_env(False, USERS)
check("9.  AUTH OFF, 127.0.0.1 -> разрешено (локальный владелец)", g2(Req(client="127.0.0.1")) is None)
check("10. AUTH OFF, ::1 -> разрешено", g2(Req(client="::1")) is None)
check("11. AUTH OFF, LAN IP -> 403", code_of(g2(Req(client="192.168.1.50"))) == 403)
check("12. AUTH OFF, публичный IP -> 403", code_of(g2(Req(client="8.8.8.8"))) == 403)
check("13. AUTH OFF, client отсутствует -> 403", code_of(g2(Req(no_client=True))) == 403)

r14 = Req(client="192.168.1.50"); r14.headers = {"x-forwarded-for": "127.0.0.1"}
check("14. AUTH OFF, подделка X-Forwarded-For при LAN-клиенте -> 403", code_of(g2(r14)) == 403)
r15 = Req(client="192.168.1.50"); r15.headers = {"host": "localhost:8000"}
check("15. AUTH OFF, подделка Host: localhost при LAN-клиенте -> 403", code_of(g2(r15)) == 403)
r16 = Req(client="192.168.1.50"); r16.headers = {"origin": "http://192.168.1.50:8000"}
check("16. AUTH OFF, корректный same-origin из сети -> всё равно 403 "
      "(Origin-политика не заменяет админ-границу)", code_of(g2(r16)) == 403)

# ═══ ЧАСТЬ 3. Покрытие маршрутов и ПОРЯДОК проверки ═══
print("--- покрытие маршрутов и порядок проверки ---")

# Обязательный whitelist: маршрут -> (метод, обработчик)
CRITICAL = [
    ("/api/modules/install", "post", "api_modules_install"),
    ("/api/modules/install-path", "post", "api_modules_install_path"),
    ("/api/modules/{module_id}", "delete", "api_modules_delete"),
    ("/api/modules/{module_id}/disable", "post", "api_modules_disable"),
    ("/api/modules/{module_id}/enable", "post", "api_modules_enable"),
    ("/api/restart", "post", "restart_app"),
]

FN = {}
for n in ast.walk(TREE):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FN.setdefault(n.name, n)


def guard_is_first(fn_name):
    """Стоит ли вызов _require_system_admin ПЕРВЫМ исполняемым оператором тела."""
    fn = FN.get(fn_name)
    if not fn:
        return False
    body = [s for s in fn.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str))]      # пропустить докстроку
    if not body:
        return False
    first = body[0]
    return isinstance(first, ast.Assign) and "_require_system_admin" in (ast.unparse(first.value) or "")


def route_of(fn_name):
    fn = FN.get(fn_name)
    out = []
    if fn:
        for d in fn.decorator_list:
            u = ast.unparse(d) or ""
            if u.startswith("app."):
                out.append(u)
    return out


for path, method, fname in CRITICAL:
    decs = route_of(fname)
    # ast.unparse нормализует строковые литералы в ОДИНАРНЫЕ кавычки — принимаем оба вида.
    check("R. %-38s декоратор на месте" % path,
          any(("app.%s(" % method) in d and (("'%s'" % path) in d or ('"%s"' % path) in d)
              for d in decs))
    check("R. %-38s guard стоит ПЕРВЫМ, до побочных эффектов" % path, guard_is_first(fname))

# Ни один критический обработчик не выполняет побочное действие раньше проверки
BODY_EFFECTS = {
    "api_modules_install": "await file.read()",
    "api_modules_install_path": "open(path",
    "api_modules_delete": "_shutil.rmtree",
    "api_modules_disable": "_modules_disabled_save",
    "api_modules_enable": "_register_module",
    "restart_app": "_restart_self",
}
for fname, effect in BODY_EFFECTS.items():
    body = code_only(grab(fname))
    gi = body.find("_require_system_admin")
    ei = body.find(effect)
    check("E. %-26s побочное действие %-22s ПОСЛЕ проверки" % (fname, effect),
          gi >= 0 and (ei < 0 or gi < ei))

# Регрессия: никто не понизил обратно до 'project' и не завёл новый незащищённый маршрут
CODE = code_only(SRC)
mod_routes = [d for d in
              [ast.unparse(dec) for n in ast.walk(TREE)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for dec in n.decorator_list]
              if isinstance(d, str) and "/api/modules" in d and "app.get" not in d]
check("R+. все mutating-маршруты /api/modules учтены в whitelist (%d)" % len(mod_routes),
      len(mod_routes) == 5)
check("R+. новых restart/shutdown/exit/quit-маршрутов нет",
      not any(k in CODE for k in ('"/api/shutdown"', '"/api/exit"', '"/api/quit"')))
check("R+. GET /api/modules намеренно НЕ стал admin-only (обычный список для UI)",
      not guard_is_first("api_modules_list") if "api_modules_list" in FN else True)

# Границы задачи: ролевая карта и прочее не тронуты
check("B1. общая ролевая карта _route_perm не менялась",
      'if method == "GET":' in CODE and "_ROLE_PERMS" in CODE)
check("B2. Origin-гард 2.775 на месте", "_origin_guard" in CODE and "ws_origin_allowed" in CODE)
check("B3. DTO принтеров 2.777 на месте", "printer_public_dto" in CODE)
check("B4. merge credentials 2.776 на месте", "_merge_printer_secret" in CODE)
check("B5. _require_admin для управления пользователями не ослаблен",
      "def _require_admin" in CODE and CODE.count("_require_admin(req)") >= 6)

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
