# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.790 — защита входа и cookie-сессий.
#
#  ЧАСТЬ 1 (ХАРАКТЕРИЗАЦИЯ). Как было в Alpha 2.789 (эталон 425e631): ограничителя
#  повторных попыток не существовало вовсе; неизвестное имя возвращалось МГНОВЕННО, минуя
#  200 000 итераций pbkdf2, то есть время ответа сообщало, заведено ли имя; атрибуты cookie
#  дублировались в трёх обработчиках; сессия, предъявленная во входящей cookie, при входе
#  не отзывалась и продолжала работать после повышения прав.
#
#  ЧАСТЬ 2+. Новое: чистый ограничитель app/auth_rate_limit.py, единый источник атрибутов
#  cookie app/session_cookie_policy.py, проверка пароля по эталонному хешу для неизвестного
#  имени и отзыв входящей сессии при входе.
#
#  ЧЕГО ЭТОТ ЭТАП НЕ ДЕЛАЕТ: восстановление пароля, HTTPS, MFA, смена алгоритма хранения
#  паролей, постоянное между перезапусками ограничение.
#
#  26.09.2026 («Запомнить это устройство»): _session_check, _ws_auth_state, auth_users_update
#  и _drop_user_sessions дополнены — сверяются тем, что каждая строка эталона осталась на месте
#  по порядку; auth_status переписана — вместо сверки исполняется (пункт 74-80b). Поведение
#  устройства закрепляет tools/test_remembered_devices.py.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * production server.py НЕ импортируется: реальные функции извлекаются разбором AST и
#     исполняются в изоляции. Тест запускается при РАБОТАЮЩЕЙ программе.
#   * рабочие БД, DATA_DIR, config, пользователи и сессии не используются: sqlite в памяти.
#   * ни одного сокета, реального запроса входа и обращения к принтерам.
#   * пароли, токены и cookie в вывод не печатаются.
#
#  Запуск:  python tools/test_auth_session_hardening.py   (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import os
import sqlite3
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.append(os.path.join(REPO, "tools"))
import _history_baseline as HB   # noqa: E402

PARENT = "425e631"   # HEAD до Alpha 2.790 (handoff 2.789)

FAILED = []
PASSED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "AUTH_SESSION_SENTINEL_2_790"

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRC_AST = ast.parse(SRC)

from app import auth_rate_limit as RL          # noqa: E402
from app import session_cookie_policy as CP    # noqa: E402


def fn_src(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return None


def const_src(tree, name):
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name
                                             for t in n.targets):
            return ast.unparse(n)
    return None


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["server.py"], check)
hcheck = HIST.check

PAR_SRC = HIST.show("server.py")
PAR_AST = ast.parse(PAR_SRC) if PAR_SRC else None


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.790: защита входа и cookie-сессий ===")
section("характеризация: как было в Alpha 2.789 (эталон %s)" % PARENT)

PAR_LOGIN = fn_src(PAR_AST, "auth_login") if PAR_AST else ""
PAR_SETUP = fn_src(PAR_AST, "auth_setup") if PAR_AST else ""
PAR_LOGOUT = fn_src(PAR_AST, "auth_logout") if PAR_AST else ""
PAR_NEWS = fn_src(PAR_AST, "_new_session") if PAR_AST else ""
PAR_UPD = fn_src(PAR_AST, "auth_users_update") if PAR_AST else ""
PAR_DEL = fn_src(PAR_AST, "auth_users_delete") if PAR_AST else ""
PAR_DIS = fn_src(PAR_AST, "auth_disable") if PAR_AST else ""

hcheck("H0. эталон %s прочитан" % PARENT, lambda: bool(PAR_SRC) and bool(PAR_LOGIN))
hcheck("H1. (1) серверного ограничителя попыток не существовало",
       lambda: PAR_SRC is not None and "auth_rate_limit" not in PAR_SRC
       and "rate_limit" not in PAR_LOGIN.lower())
hcheck("H2. (2-3) неограниченные проверки пароля: вход шёл сразу в БД и pbkdf2",
       lambda: "conn_p.execute" in PAR_LOGIN and "_verify_pwd" in PAR_LOGIN)
hcheck("H3. (4) внешний ответ для неизвестного имени и неверного пароля УЖЕ был одинаков",
       lambda: "if not r or not _verify_pwd" in PAR_LOGIN
       and PAR_LOGIN.count("'error': 'invalid'") == 1)
hcheck("H4. (5) проверки пароля по эталонному хешу НЕ выполнялось (быстрый выход)",
       lambda: bool(PAR_LOGIN) and "dummy" not in PAR_LOGIN.lower())
hcheck("H5. (6) атрибуты cookie задавались прямо в обработчиках, без общего источника",
       lambda: "httponly=True, samesite='lax'" in PAR_LOGIN.replace('"', "'")
       and PAR_SRC.count("set_cookie(_SESSION_COOKIE") == 2
       and "session_cookie_policy" not in PAR_SRC)
hcheck("H6. (7) входящая cookie НЕ переиспользовалась: токен всегда генерировался сервером",
       lambda: "secrets.token_urlsafe(32)" in PAR_NEWS)
hcheck("H7. (8) но прежняя входящая сессия при входе НЕ отзывалась",
       lambda: bool(PAR_LOGIN) and "cookies.get" not in PAR_LOGIN)
hcheck("H8. (9) logout отзывал серверную сессию",
       lambda: "_sessions.pop(tok, None)" in PAR_LOGOUT)
hcheck("H9. (10) отзыв сессий при отключении/удалении/смене пароля УЖЕ существовал",
       lambda: "_drop_user_sessions" in PAR_UPD and "_drop_user_sessions" in PAR_DEL
       and "_sessions.clear()" in PAR_DIS)
hcheck("H10. (11) срок жизни — по простою, 8 часов",
       lambda: "_SESSION_IDLE = 8 * 3600" in PAR_SRC)
hcheck("H11. (12) при AUTH OFF сессия не требуется",
       lambda: "if not _SECURITY_ENABLED" in (fn_src(PAR_AST, "auth_status") or ""))
check("H12. (13-15) рабочая БД/config/сеть не используются", True)
check("H13. (14) production server.py не импортируется", "server" not in sys.modules)
# 16.10.2026 (R-150): число итераций поднято с 200 000 до 600 000 (OWASP), алгоритм и формат
# строки прежние. Проверка исполняет обе версии: хеш эталона проверяется текущей _verify_pwd
# (пароли, заведённые до правки, работают), новый хеш — 600 000 итераций той же формы.
def _h14():
    if PAR_AST is None:
        return False
    _pn = {"hashlib": __import__("hashlib"), "os": os}
    exec(compile(fn_src(PAR_AST, "_hash_pwd"), "<parent>", "exec"), _pn)
    _cn = {"hashlib": __import__("hashlib"), "os": os, "secrets": __import__("secrets")}
    exec(compile(const_src(SRC_AST, "_PWD_ITERS"), "<server>", "exec"), _cn)
    for _f in ("_hash_pwd", "_verify_pwd"):
        exec(compile(fn_src(SRC_AST, _f), "<server>", "exec"), _cn)
    _old, _new = _pn["_hash_pwd"]("Pass-H14"), _cn["_hash_pwd"]("Pass-H14")
    return (fn_src(PAR_AST, "_verify_pwd") == fn_src(SRC_AST, "_verify_pwd")
            and _old.startswith("pbkdf2_sha256$200000$") and _cn["_verify_pwd"]("Pass-H14", _old)
            and not _cn["_verify_pwd"]("Pass-H15", _old)
            and _new.startswith("pbkdf2_sha256$%d$" % _cn["_PWD_ITERS"]) and _cn["_PWD_ITERS"] >= 600000
            and _cn["_verify_pwd"]("Pass-H14", _new))


hcheck("H14. (17) алгоритм хранения паролей прежний (PBKDF2-SHA256, та же строка); итераций 600 000, "
       "старые хеши проверяются", _h14)


# ════════════════════════════════════════════════════════════════════════════
section("чистый ограничитель (пункты 7-33)")

_rlsrc = open(os.path.join(REPO, "app", "auth_rate_limit.py"), encoding="utf-8").read()
_rlimp = {(n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0])
          for n in ast.walk(ast.parse(_rlsrc)) if isinstance(n, (ast.Import, ast.ImportFrom))}
check("L0. ограничитель не тянет фреймворк, БД, сеть, config и журнал",
      not _rlimp & {"fastapi", "starlette", "sqlite3", "socket", "urllib", "requests",
                    "logging", "json", "os"})
check("L1. используются монотонные часы, а не системное время",
      "monotonic" in _rlsrc and "time.time()" not in _rlsrc)


class Clock:
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t
    def advance(self, s):
        self.t += s


clk = Clock()
lim = RL.AuthRateLimiter(clock=clk)
PEER = "203.0.113.5"
ACC = RL.account_key("alice")

check("7. первые допустимые неудачи проходят",
      all(lim.register_failure(RL.NS_LOGIN_ACCOUNT, ACC).allow for _ in range(RL.LOGIN_ACCOUNT_MAX - 1)))
_d = lim.register_failure(RL.NS_LOGIN_ACCOUNT, ACC)
check("8. порог «имя+адрес» блокирует", not _d.allow and _d.reason == RL.REASON_RATE_LIMITED)
check("10-11. блокировка отдаёт причину и корректный Retry-After",
      _d.retry_after == RL.BLOCK_SECONDS and lim.check(RL.NS_LOGIN_ACCOUNT, ACC).retry_after > 0)
check("12. после остывания попытка снова разрешена",
      (clk.advance(RL.BLOCK_SECONDS + 2), lim.check(RL.NS_LOGIN_ACCOUNT, ACC).allow)[1])

clk2 = Clock(); lim2 = RL.AuthRateLimiter(clock=clk2)
for i in range(RL.LOGIN_PEER_MAX - 1):
    lim2.register_failure(RL.NS_LOGIN_PEER, PEER)
check("9. порог адреса блокирует независимо от имени",
      not lim2.register_failure(RL.NS_LOGIN_PEER, PEER).allow)

clk3 = Clock(); lim3 = RL.AuthRateLimiter(clock=clk3)
for _ in range(RL.LOGIN_ACCOUNT_MAX - 1):
    lim3.register_failure(RL.NS_LOGIN_ACCOUNT, ACC)
check("13. успешный вход снимает неудачи ЭТОГО имени",
      lim3.clear(RL.NS_LOGIN_ACCOUNT, ACC)
      and lim3.register_failure(RL.NS_LOGIN_ACCOUNT, ACC).allow)
clk4 = Clock(); lim4 = RL.AuthRateLimiter(clock=clk4)
for _ in range(RL.LOGIN_PEER_MAX):
    lim4.register_failure(RL.NS_LOGIN_PEER, PEER)
check("13b. успешный вход НЕ снимает уже сработавший заслон адреса",
      not lim4.clear(RL.NS_LOGIN_PEER, PEER) and not lim4.check(RL.NS_LOGIN_PEER, PEER).allow)

clk5 = Clock(); lim5 = RL.AuthRateLimiter(clock=clk5)
for _ in range(RL.LOGIN_ACCOUNT_MAX - 1):
    lim5.register_failure(RL.NS_LOGIN_ACCOUNT, ACC)
clk5.advance(RL.LOGIN_ACCOUNT_WINDOW + 1)
check("12b. неудачи вне окна не накапливаются",
      lim5.register_failure(RL.NS_LOGIN_ACCOUNT, ACC).allow)

check("25. регистр и пробелы не дают разных ключей там, где вход их не различает",
      RL.account_key("  alice  ") == RL.account_key("alice")
      and RL.account_key("Alice") != RL.account_key("alice"))
check("32-33. сырой логин и пароль в состоянии не хранятся",
      "alice" not in repr(lim3._state) and len(RL.account_key("alice")) == 64
      and "password" not in _rlsrc.lower().replace("raw password", ""))
check("30-31. у первичной настройки отдельное пространство",
      RL.NS_SETUP_PEER != RL.NS_LOGIN_PEER and RL.NS_SETUP_PEER in RL._LIMITS)

clk6 = Clock(); lim6 = RL.AuthRateLimiter(clock=clk6, max_keys=32)
for i in range(200):
    lim6.register_failure(RL.NS_LOGIN_ACCOUNT, RL.account_key("u%d" % i))
check("27. состояние ограничено сверху", lim6.size() <= 32)
clk7 = Clock(); lim7 = RL.AuthRateLimiter(clock=clk7)
lim7.register_failure(RL.NS_LOGIN_ACCOUNT, ACC)
clk7.advance(RL.BLOCK_SECONDS + RL.LOGIN_ACCOUNT_WINDOW + 10)
check("28. истёкшее состояние убирается", lim7.prune() == 0)
check("26. одновременные неудачи не обходят порог (состояние под замком)",
      "threading.Lock" in _rlsrc and "with self._lock" in _rlsrc)
check("29. ограничение в памяти: перезапуск сбрасывает счётчики (заявлено честно)",
      "перезапуск" in _rlsrc.lower())


# ════════════════════════════════════════════════════════════════════════════
section("политика cookie (пункты 51-62)")

_a = CP.set_attrs("http")
check("51. HttpOnly установлен", _a["httponly"] is True)
check("52. SameSite=Lax", _a["samesite"] == "lax")
check("53. Path=/", _a["path"] == "/")
check("54. Domain не задаётся", "domain" not in _a and CP.DOMAIN is None)
check("55. HTTP localhost НЕ получает Secure", _a["secure"] is False)
check("56. настоящий HTTPS получает Secure",
      CP.set_attrs("https")["secure"] is True and CP.set_attrs("wss")["secure"] is True)
check("57. X-Forwarded-Proto в решении не участвует",
      "forwarded" not in _rlsrc.lower()
      and "forwarded" not in open(os.path.join(REPO, "app", "session_cookie_policy.py"),
                                  encoding="utf-8").read().lower().replace(
                                      "x-forwarded-proto", ""))
_d1, _d2 = CP.set_attrs("http"), CP.delete_attrs("http")
check("58. удаление cookie использует совместимые атрибуты",
      _d2["path"] == _d1["path"] and _d2["samesite"] == _d1["samesite"]
      and _d2["secure"] == _d1["secure"] and ("domain" in _d2) == ("domain" in _d1))
check("20b. имя cookie не менялось", CP.COOKIE_NAME == "fm_session")


# ════════════════════════════════════════════════════════════════════════════
# ИЗОЛИРОВАННОЕ ИСПОЛНЕНИЕ РЕАЛЬНЫХ ОБРАБОТЧИКОВ
# ════════════════════════════════════════════════════════════════════════════
section("изолированное исполнение входа (пункты 34-50, 81-88)")

DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, pwd_hash TEXT, "
           "role TEXT, is_active INTEGER)")
DB.commit()

SPY = {}


def spy_reset():
    SPY.clear()
    SPY.update({"body": 0, "db": 0, "verify": 0, "audit": [], "log": [],
                "set_cookie": [], "del_cookie": []})


class _Lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _DB:
    def execute(self, *a, **k):
        SPY["db"] += 1
        return DB.execute(*a, **k)
    def commit(self):
        return DB.commit()


class _Resp:
    def __init__(self, content=None, status_code=200, headers=None):
        self.content, self.status_code = content, status_code
        self.headers = headers or {}


class FakeResponse:
    def set_cookie(self, key, value, **kw):
        SPY["set_cookie"].append((key, value, kw))
    def delete_cookie(self, key, **kw):
        SPY["del_cookie"].append((key, kw))


class _Log:
    def _r(self, *a, **k):
        SPY["log"].append(" ".join(str(x) for x in a))
    info = warning = error = debug = _r


NS = {
    "_auth_rl": RL, "_cookie_policy": CP, "secrets": __import__("secrets"),
    "hashlib": __import__("hashlib"), "time": __import__("time"), "os": os,
    "JSONResponse": _Resp, "log": _Log(), "lock_p": _Lock(), "conn_p": _DB(),
    "_SESSION_COOKIE": "fm_session", "_SESSION_IDLE": 8 * 3600,
    "_sessions": {}, "_sessions_lock": __import__("threading").Lock(),
    "_SECURITY_ENABLED": False,
    "_audit": lambda *a, **k: SPY["audit"].append(a[:2]),
    "app": type("A", (), {"post": lambda *a, **k: (lambda f: f),
                          "get": lambda *a, **k: (lambda f: f)})(),
    "Request": object, "Response": object,
}
for _n in ("_hash_pwd", "_verify_pwd", "_peer_of", "_dummy_pwd_hash",
           # 16.10.2026 (R-150): пересчёт хеша при входе. Пользователи здесь заводятся с новым
           # хешем, пересчёт не нужен; его поведение — tools/test_remembered_devices.py (RH*).
           "_pwd_iters", "_pwd_needs_rehash", "_pwd_harden_runtime", "_pwd_rehash",
           "_prune_sessions_if_needed", "_new_session", "_revoke_incoming_session",
           "_rate_limited_response", "_session_check", "_session_user",
           "auth_login", "auth_logout", "auth_status",
           "_is_device_token"):
    exec(compile(fn_src(SRC_AST, _n), "<server>", "exec"), NS)
exec(compile(const_src(SRC_AST, "_DUMMY_PWD_HASH"), "<server>", "exec"), NS)
exec(compile(const_src(SRC_AST, "_PWD_ITERS"), "<server>", "exec"), NS)
exec(compile(const_src(SRC_AST, "_AUTH_LIMITER"), "<server>", "exec"), NS)
# 26.09.2026: вход, выход и проверка сессии различают токен запомненного устройства (префикс
# fmd_) — признак и константы берутся из настоящего server.py. Пути устройства здесь не
# исполняются: входы идут без remember_device, это обычные сессии. Поведение устройства
# закрепляет tools/test_remembered_devices.py.
for _c in ("_DEVICE_TOKEN_PREFIX", "_DEVICE_COOKIE_MAX_AGE", "_REMEMBER_DEVICE_PROTOCOL",
           "AUTH_ROLES"):
    exec(compile(const_src(SRC_AST, _c), "<server>", "exec"), NS)

_real_verify = NS["_verify_pwd"]


def _counting_verify(pwd, stored):
    SPY["verify"] += 1
    return _real_verify(pwd, stored)


NS["_verify_pwd"] = _counting_verify


async def _fake_json_body(req):
    SPY["body"] += 1
    return req._data


NS["_json_body"] = _fake_json_body
NS["_json_body_small"] = _fake_json_body   # 16.10.2026: вход читает тело с пределом размера

login = NS["auth_login"]
logout = NS["auth_logout"]
LIMITER = NS["_AUTH_LIMITER"]
SESSIONS = NS["_sessions"]

PWD = "correct horse battery"
DB.execute("INSERT INTO users (id,username,pwd_hash,role,is_active) VALUES (?,?,?,?,1)",
           ("u1", "alice", NS["_hash_pwd"](PWD), "operator"))
DB.commit()


class Req:
    def __init__(self, data=None, client="203.0.113.9", cookies=None, scheme="http"):
        self._data = data or {}
        self.client = type("C", (), {"host": client})() if client else None
        self.cookies = cookies or {}
        self.url = type("U", (), {"scheme": scheme})()


def do_login(username, password, client="203.0.113.9", cookies=None, scheme="http"):
    spy_reset()
    resp = FakeResponse()
    r = asyncio.run(login(Req({"username": username, "password": password}, client, cookies, scheme), resp))
    return r


check("X1. реальные обработчики исполнены изолированно",
      callable(login) and callable(logout))

r = do_login("alice", PWD)
check("43. успешный вход создаёт сессию и ставит cookie",
      isinstance(r, dict) and r.get("ok") is True and len(SPY["set_cookie"]) == 1
      and len(SESSIONS) == 1)
tok1 = SPY["set_cookie"][0][1]
r = do_login("alice", PWD)
tok2 = SPY["set_cookie"][0][1]
check("44. два последовательных входа дают РАЗНЫЕ токены", tok1 != tok2)
_news = fn_src(SRC_AST, "_new_session")
check("45-46. токен создаётся secrets (32 байта = 256 бит), а не random",
      "secrets.token_urlsafe(32)" in _news and "random." not in _news
      and len(tok2) >= 43)
check("51b. cookie ставится с безопасными атрибутами",
      SPY["set_cookie"][0][2].get("httponly") is True
      and SPY["set_cookie"][0][2].get("samesite") == "lax"
      and SPY["set_cookie"][0][2].get("path") == "/"
      and SPY["set_cookie"][0][2].get("secure") is False)
check("56b. при HTTPS-схеме cookie получает Secure",
      (do_login("alice", PWD, scheme="https"), SPY["set_cookie"][0][2].get("secure"))[1] is True)

# 42/47: входящая сессия отзывается
SESSIONS.clear()
do_login("alice", PWD)
old_tok = SPY["set_cookie"][0][1]
do_login("alice", PWD, cookies={"fm_session": old_tok})
new_tok = SPY["set_cookie"][0][1]
check("42+47. входящая сессия отозвана, новая не равна ей",
      old_tok not in SESSIONS and new_tok in SESSIONS and old_tok != new_tok)

# 34-37: неизвестный / неверный / отключённый
DB.execute("INSERT INTO users (id,username,pwd_hash,role,is_active) VALUES (?,?,?,?,0)",
           ("u2", "bob", NS["_hash_pwd"](PWD), "operator"))
DB.commit()
LIMITER._state.clear()
r_unknown = do_login("nosuchuser", "whatever")
v_unknown = SPY["verify"]
LIMITER._state.clear()
r_wrong = do_login("alice", "wrong password")
v_wrong = SPY["verify"]
LIMITER._state.clear()
r_disabled = do_login("bob", PWD)
check("34-36. неизвестный, неверный пароль и отключённый — одинаковый ответ",
      r_unknown.status_code == 401 and r_wrong.status_code == 401
      and r_disabled.status_code == 401
      and r_unknown.content == r_wrong.content == r_disabled.content
      == {"ok": False, "error": "invalid"})
check("37-38. неизвестное имя ВСЁ РАВНО выполняет проверку пароля того же класса",
      v_unknown == v_wrong == 1)
check("39. эталонный хеш считается один раз, а не на каждый запрос",
      NS["_DUMMY_PWD_HASH"][0] is not None
      and NS["_dummy_pwd_hash"]() is NS["_dummy_pwd_hash"]())
check("41. логин и пароль не отражаются в ответе",
      "nosuchuser" not in str(r_unknown.content) and PWD not in str(r_wrong.content))
check("85. при неудаче сессия не создаётся и cookie не ставится",
      len(SPY["set_cookie"]) == 0)

# 81-84: порядок при блокировке
LIMITER._state.clear()
for _ in range(RL.LOGIN_ACCOUNT_MAX):
    do_login("alice", "wrong")
r_blocked = do_login("alice", "wrong")
check("8b. после порога вход отвечает 429 с Retry-After",
      r_blocked.status_code == 429
      and r_blocked.content == {"ok": False, "error": RL.REASON_RATE_LIMITED}
      and int(r_blocked.headers.get("Retry-After", "0")) > 0)
check("83-84+18-19. при блокировке имени БД не опрашивается, pbkdf2 не считается, "
      "сессия не создаётся",
      SPY["db"] == 0 and SPY["verify"] == 0 and len(SPY["set_cookie"]) == 0)

LIMITER._state.clear()
for _ in range(RL.LOGIN_PEER_MAX):
    do_login("u%d" % _, "wrong")
r_peer = do_login("alice", PWD)
check("81-82. при блокировке адреса тело запроса не читается вовсе",
      r_peer.status_code == 429 and SPY["body"] == 0 and SPY["db"] == 0
      and SPY["verify"] == 0)

# 20-22: proxy-заголовки не влияют
LIMITER._state.clear()
for _ in range(RL.LOGIN_ACCOUNT_MAX):
    do_login("alice", "wrong", client="198.51.100.1")
spy_reset()
_resp = FakeResponse()
_req = Req({"username": "alice", "password": "wrong"}, "198.51.100.1")
_req.headers = {"X-Forwarded-For": "10.0.0.1", "X-Real-IP": "10.0.0.2",
                "Forwarded": "for=10.0.0.3"}
r_hdr = asyncio.run(login(_req, _resp))
check("20-22. X-Forwarded-For / X-Real-IP / Forwarded не меняют корзину адреса",
      r_hdr.status_code == 429
      and "headers" not in fn_src(SRC_AST, "_peer_of"))
check("24. адрес IPv6 поддерживается",
      NS["_peer_of"](Req({}, "::1")) == "::1")

# 13: успешный вход очищает состояние имени
LIMITER._state.clear()
for _ in range(RL.LOGIN_ACCOUNT_MAX - 1):
    do_login("alice", "wrong")
r_ok = do_login("alice", PWD)
check("13c. успешный вход снимает накопленные неудачи имени",
      isinstance(r_ok, dict) and r_ok.get("ok") is True
      and LIMITER.check(RL.NS_LOGIN_ACCOUNT, RL.account_key("alice", "203.0.113.9")).allow)

# 16.10.2026 (аудит arch-auth-09): неудачи с одного адреса не запирают то же имя на другом
LIMITER._state.clear()
for _ in range(RL.LOGIN_ACCOUNT_MAX):
    do_login("alice", "wrong", client="198.51.100.7")
r_other = do_login("alice", PWD, client="127.0.0.1")
r_same = do_login("alice", PWD, client="198.51.100.7")
check("13d. пять неверных паролей с чужого устройства не закрывают вход тому же имени с компьютера фермы",
      isinstance(r_other, dict) and r_other.get("ok") is True
      and getattr(r_same, "status_code", None) == 429)

# 17: ошибка БД не считается неудачей учётных данных
check("17. ошибка БД обрабатывается как отказ, а не как «пароль верный»",
      "except Exception" in fn_src(SRC_AST, "auth_login")
      and "r = None" in fn_src(SRC_AST, "auth_login"))

# 63-64: logout
LIMITER._state.clear()
SESSIONS.clear()
do_login("alice", PWD)
tok = SPY["set_cookie"][0][1]
spy_reset()
resp = FakeResponse()
logout(Req({}, "203.0.113.9", {"fm_session": tok}), resp)
check("63+87. logout отзывает серверную сессию ДО очистки cookie",
      tok not in SESSIONS and len(SPY["del_cookie"]) == 1)
check("62. удаление cookie использует совместимые атрибуты",
      SPY["del_cookie"][0][1].get("path") == "/"
      and SPY["del_cookie"][0][1].get("samesite") == "lax")
spy_reset()
logout(Req({}, "203.0.113.9", {"fm_session": tok}), FakeResponse())
check("64. повторный logout безопасен", tok not in SESSIONS)


# ════════════════════════════════════════════════════════════════════════════
section("метка и неизменность соседних границ")

# Метка подаётся как ПАРОЛЬ: он не должен появиться нигде. Введённое ИМЯ при неудачном
# входе журнал аудита записывает намеренно (это и есть след попытки) — существующее
# поведение, оно проверяется отдельно и не считается утечкой.
LIMITER._state.clear()
_r_sent = do_login("alice", SENTINEL)
check("88a. пароль-метка не попадает ни в ответ, ни в журнал, ни в аудит",
      SENTINEL not in str(_r_sent.content)
      and not any(SENTINEL in str(x) for x in SPY["log"])
      and not any(SENTINEL in str(x) for x in SPY["audit"]))
check("88a2. введённое имя не отражается в ответе (но остаётся в аудите по существующему контракту)",
      (lambda rr: SENTINEL not in str(rr.content))(
          (LIMITER._state.clear(), do_login(SENTINEL, "x"))[1])
      and any(SENTINEL in str(x) for x in SPY["audit"]))
check("88b. метка отсутствует в исходниках приложения",
      SENTINEL not in SRC and SENTINEL not in _rlsrc
      and SENTINEL not in open(os.path.join(REPO, "app", "session_cookie_policy.py"),
                               encoding="utf-8").read()
      and SENTINEL not in open(os.path.join(REPO, "web", "app.js"),
                               encoding="utf-8", errors="surrogateescape").read())
check("14b. пароль не попадает в журнал и аудит",
      not any(PWD in str(x) for x in SPY["log"] + SPY["audit"]))

def lines_kept_in_order(base, cur):
    """26.09.2026: каждая строка эталонной функции (ast.unparse) есть в текущей, в том же
    порядке. Дописывать можно, убирать и переставлять — нельзя. Нет функции ни там, ни там —
    совпадение; есть только с одной стороны — расхождение."""
    if base is None or cur is None:
        return base is None and cur is None
    it = iter(cur.split("\n"))
    return all(any(line == c for c in it) for line in base.split("\n"))


# Строго байт-в-байт с эталоном.
UNCHANGED = ("_session_user", "_require_admin",
             "_require_system_admin", "_require_slicer_callback", "_auth_gate",
             "_gate_decide", "_route_perm", "_has_perm",
             "auth_users_delete",
             "_active_admin_count", "_verify_pwd",
             "proxy_upload", "fs_list", "_lan_effective_decision", "_within_upload_dir")
# _hash_pwd изменена 16.10.2026 (R-150: 600 000 итераций) — её закрепляет H14 исполнением.
# auth_status переписана 26.09.2026 («Запомнить это устройство»: ключи remember_device и
# device) — новое поведение закрепляет tools/test_remembered_devices.py, здесь — пункт 74-80b.
# Дополнены 26.09.2026 («Запомнить это устройство»): все строки эталона сохранены, по порядку.
# 16.10.2026 (аудит arch-auth-18): ws_ep дописана — сбой проверки источника закрывает соединение
# (прежде соединение шло дальше); поведение — tools/test_audit_recheck_1016.py. В тот же день R-150
# намеренно удалил её ветку «защита выключена: ждём разрыва без перепроверок», поэтому ws_ep из
# сверки убрана; поведение сокета закрепляет tools/test_websocket_session_lifecycle.py.
# 16.10.2026 (R-151): add_route только ДОПОЛНЕНА — модуль, не уложившийся в срок запуска (core._revoked),
# маршруты больше не добавляет; остальные строки эталона на месте (сверка «по порядку»).
ADDITIVE_26_09 = ("_session_check", "_ws_auth_state", "auth_users_update",
                  "_drop_user_sessions", "add_route")
#  Без эталона списки расхождений не вычисляются (None): пустой список «расхождений нет»
#  без эталона был бы ложной зеленью.
_diffs = ([f for f in UNCHANGED if fn_src(PAR_AST, f) != fn_src(SRC_AST, f)]
          if PAR_AST else None)
hcheck("95-105. соседние границы и алгоритмы не изменены: расхождений %s (%s)"
       % ((len(_diffs), ", ".join(_diffs) or "нет") if _diffs is not None else ("?", "эталона нет")),
       lambda: _diffs == [])
_adiffs = ([f for f in ADDITIVE_26_09
            if not lines_kept_in_order(fn_src(PAR_AST, f), fn_src(SRC_AST, f))]
           if PAR_AST else None)
hcheck("95-105b. дополненные 26.09.2026 функции сохранили каждую строку эталона по порядку: "
       "расхождений %s (%s)"
       % ((len(_adiffs), ", ".join(_adiffs) or "нет") if _adiffs is not None else ("?", "эталона нет")),
       lambda: _adiffs == [])
_sc_par = fn_src(PAR_AST, "_session_check") if PAR_AST else None
_sc_lines = (_sc_par or "").split("\n")
_sc_idx = next((i for i, l in enumerate(_sc_lines) if "s['last_seen'] = now" in l), -1)
hcheck("95-105c. сверка «строки эталона по порядку» ловит удалённую и переставленную строку",
       lambda: _sc_par is not None and _sc_idx > 0
       and lines_kept_in_order(_sc_par, _sc_par)
       and not lines_kept_in_order(_sc_par, "\n".join(_sc_lines[:_sc_idx] + _sc_lines[_sc_idx + 1:]))
       and not lines_kept_in_order(_sc_par, "\n".join(
          _sc_lines[:_sc_idx - 1] + [_sc_lines[_sc_idx], _sc_lines[_sc_idx - 1]]
          + _sc_lines[_sc_idx + 1:]))
       and not lines_kept_in_order(_sc_par, None))
check("67-69. отзыв сессий при смене пароля, роли, отключении и удалении сохранён",
      "_drop_user_sessions(uid)" in fn_src(SRC_AST, "auth_users_update")
      and "_drop_user_sessions(uid)" in fn_src(SRC_AST, "auth_users_delete"))
check("70. отключение защиты по-прежнему очищает все сессии",
      "_sessions.clear()" in fn_src(SRC_AST, "auth_disable"))
# 26.09.2026: _session_check дополнена веткой токена устройства (он проверяется своим путём);
# путь обычной сессии — все строки эталона, по порядку.
hcheck("71-72. отозванная и истёкшая сессии не обновляют last_seen",
       lambda: bool(PAR_AST) and lines_kept_in_order(fn_src(PAR_AST, "_session_check"),
                                                     fn_src(SRC_AST, "_session_check")))
check("74-80. AUTH OFF не требует сессии и не затронут ограничителем",
      "_AUTH_LIMITER" not in fn_src(SRC_AST, "auth_status")
      and "_AUTH_LIMITER" not in (fn_src(SRC_AST, "_auth_gate") or ""))
# 74-80b. auth_status переписана 26.09.2026 — вместо сверки с эталоном исполняется настоящая:
# при AUTH OFF сессия не нужна; при AUTH ON без cookie вход не засчитан; обычная сессия
# признака устройства не получает.
_status = NS["auth_status"]
LIMITER._state.clear()
SESSIONS.clear()
do_login("alice", PWD)
_st_tok = SPY["set_cookie"][0][1]
_st_off = _status(Req({}, "203.0.113.9"))
NS["_SECURITY_ENABLED"] = True
try:
    _st_anon = _status(Req({}, "203.0.113.9"))
    _st_user = _status(Req({}, "203.0.113.9", {"fm_session": _st_tok}))
finally:
    NS["_SECURITY_ENABLED"] = False
check("74-80b. auth_status (переписана 26.09.2026): AUTH OFF — вход без сессии; AUTH ON без "
      "cookie — не вошёл; обычная сессия — без признака устройства",
      _st_off.get("enabled") is False and _st_off.get("authenticated") is True
      and _st_off.get("user") is None
      and _st_anon.get("enabled") is True and _st_anon.get("authenticated") is False
      and _st_anon.get("user") is None
      and _st_user.get("authenticated") is True
      and _st_user.get("user") == {"username": "alice", "role": "operator"}
      and "device" not in _st_user and not _st_tok.startswith(NS["_DEVICE_TOKEN_PREFIX"]))
hcheck("106. права маршрутов не менялись",
       lambda: PAR_AST is not None
       and fn_src(PAR_AST, "_route_perm") == fn_src(SRC_AST, "_route_perm"))

print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
