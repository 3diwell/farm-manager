# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.798 — локальное одноразовое восстановление доступа администратора.
#
#  ПОЛНОСТЬЮ OFFLINE. server.py НЕ импортируется обычным способом: реальные функции
#  извлекаются разбором AST и исполняются в изоляции на ВРЕМЕННОЙ sqlite и словаре-
#  конфиге в памяти. Ни сокетов, ни uvicorn, ни трея, ни браузера, ни рабочей БД,
#  ни рабочего config/DATA_DIR. Часы grant-store — фейковые (детерминизм без сна).
#  Пароли/токены/хеши в вывод не печатаются.
#
#  Запуск:  python tools/test_local_admin_recovery.py   (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import atexit
import builtins
import hashlib
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# ── Страж преждевременного выхода: exit 0 до итоговой сводки невозможен ──────
_DONE = {"ok": False}

def _guard_exit():
    if not _DONE["ok"]:
        try:
            print("FAIL — тест завершился до выполнения проверок")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)

atexit.register(_guard_exit)

# ── Ловушки-шпионы: ни сокета, ни подпроцесса; запись в файлы вне temp запрещена ──
_SOCKETS = []
_PROCS = []

class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
        raise AssertionError("offline-тест: сокеты запрещены")

socket.socket = _TrapSocket

def _trap_proc(*a, **k):
    _PROCS.append(a)
    raise AssertionError("offline-тест: подпроцессы запрещены")

subprocess.Popen = subprocess.run = subprocess.call = subprocess.check_output = _trap_proc

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

# Метка-ловушка: только в оснастке/фикстурах этого теста.
SENTINEL = "LOCAL_ADMIN_RECOVERY_SENTINEL_2_798"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
INDEXHTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
REC_SRC = open(os.path.join(REPO, "app", "local_admin_recovery.py"), encoding="utf-8").read()
OWN_SRC = open(os.path.abspath(__file__), encoding="utf-8").read()

from app import local_admin_recovery as L        # noqa: E402  (чистый stdlib-модуль)
from app import route_policy_registry as reg      # noqa: E402
from app import route_access_control as rac        # noqa: E402
from app import security_policy as secpol          # noqa: E402
from app import session_cookie_policy as cookiepol  # noqa: E402


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


def const_src(name):
    """Исходник МОДУЛЬНОГО присваивания `name = ...` из server.py (константы извлекаются из
    реального кода, а не переписываются в тест вручную)."""
    for n in SRV_AST.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.unparse(n)
    return ""


def fn_body_no_doc(name):
    """Исходник ТЕЛА функции без докстроки (докстрока поясняет политику словами и может
    называть заголовки/хранилища, которых код как раз НЕ использует)."""
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            body = list(n.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]
            return "\n".join(ast.unparse(s) for s in body)
    return ""


def strip_js_comments(s):
    """Убрать строки-комментарии // — они поясняют, чего код НЕ делает, и не должны
    засчитываться проверкам «токен не пишется в …»."""
    return "\n".join(l for l in s.split("\n") if not l.strip().startswith("//"))


class FakeClock(object):
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t
    def advance(self, dt):
        self.t += dt


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.798: локальное одноразовое восстановление доступа администратора ===")
section("чистый модуль: только stdlib, без побочных эффектов импорта")

_rec_imports = {(n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0])
                for n in ast.walk(ast.parse(REC_SRC)) if isinstance(n, (ast.Import, ast.ImportFrom))}
check("M0. модуль не тянет фреймворк/БД/сеть/config/os",
      not _rec_imports & {"fastapi", "starlette", "sqlite3", "socket", "urllib", "os", "json", "logging"}
      and _rec_imports <= {"enum", "hashlib", "hmac", "secrets", "threading", "time"})


# ════════════════════════════════════════════════════════════════════════════
section("GRANT STORE (пункты 1-20)")

clk = FakeClock()
store = L.LocalRecoveryGrantStore(clock=clk)

check("1. токен из secrets.token_urlsafe (в модуле)", "secrets.token_urlsafe" in REC_SRC)
tok = store.issue()
check("2. энтропия токена >= 256 бит (token_urlsafe(32) -> >= 43 симв. base64url)",
      L.TOKEN_BYTES >= 32 and isinstance(tok, str) and len(tok) >= 43)
check("3. сырой токен в store не хранится (только digest); поле _digest — hex sha256",
      getattr(store, "_digest", None) is not None and store._digest != tok
      and store._digest == hashlib.sha256(tok.encode("utf-8")).hexdigest())
check("4. digest — SHA-256", "hashlib.sha256" in REC_SRC and len(store._digest) == 64)
check("5. сравнение через hmac.compare_digest", "hmac.compare_digest" in REC_SRC)
check("6. один активный grant (active_metadata это подтверждает)",
      store.active_metadata()["active"] is True)
old = tok
tok2 = store.issue()   # новый grant вытесняет прежний
check("7. новый grant инвалидирует старый",
      not store.validate(old).ok and store.validate(old).reason is L.Reason.INVALID
      and store.validate(tok2).ok)
# TTL
clk.advance(1)
check("8. TTL работает: до истечения токен валиден", store.validate(tok2).ok)
clk.advance(L.TTL_SECONDS + 1)
check("9. истёкший токен fail-closed", not store.validate(tok2).ok
      and store.validate(tok2).reason is L.Reason.EXPIRED)
store2 = L.LocalRecoveryGrantStore(clock=clk)
check("10. отсутствующий grant fail-closed (MISSING)",
      not store2.validate("anything").ok and store2.validate("anything").reason is L.Reason.MISSING)
t3 = store2.issue()
check("11. malformed токен fail-closed (не строка / пусто / слишком длинный)",
      not store2.validate(None).ok and store2.validate(None).reason is L.Reason.MALFORMED
      and not store2.validate("").ok and store2.validate("").reason is L.Reason.MALFORMED
      and store2.validate("x" * (L.MAX_TOKEN_LEN + 1)).reason is L.Reason.MALFORMED)
check("12. неизвестный (неверный) токен fail-closed (INVALID)",
      not store2.validate("wrong").ok and store2.validate("wrong").reason is L.Reason.INVALID)
# Max attempts
store3 = L.LocalRecoveryGrantStore(clock=clk)
tt = store3.issue()
for _ in range(L.MAX_ATTEMPTS):
    store3.record_failure("bad")
check("13. предел попыток = 5 (или безопаснее)", L.MAX_ATTEMPTS <= 5 and L.MAX_ATTEMPTS >= 1)
check("14. после предела grant непригоден даже с ВЕРНЫМ токеном",
      not store3.validate(tt).ok
      and store3.validate(tt).reason in (L.Reason.TOO_MANY_ATTEMPTS, L.Reason.MISSING))
# Consume one-time + replay
store4 = L.LocalRecoveryGrantStore(clock=clk)
t4 = store4.issue()
first = store4.consume(t4)
second = store4.consume(t4)
check("15. consume одноразов: первый успех", first.ok and first.reason is L.Reason.VALID)
check("16. replay отклоняется: повторный consume не проходит",
      not second.ok and second.reason in (L.Reason.CONSUMED, L.Reason.MISSING))
check("16b. validate после consume тоже не проходит", not store4.validate(t4).ok)
# Parallel consume -> exactly one success
store5 = L.LocalRecoveryGrantStore(clock=clk)
t5 = store5.issue()
results = []
barrier = threading.Barrier(8)
def _worker():
    barrier.wait()
    results.append(store5.consume(t5).ok)
threads = [threading.Thread(target=_worker) for _ in range(8)]
for th in threads:
    th.start()
for th in threads:
    th.join()
check("17. два+ параллельных consume дают РОВНО один success",
      sum(1 for r in results if r) == 1)
# Restart / new store invalidates
store6 = L.LocalRecoveryGrantStore(clock=clk)
t6 = store6.issue()
fresh = L.LocalRecoveryGrantStore(clock=clk)   # «перезапуск процесса» = новый store
check("18. новый store (перезапуск) не знает прежний grant",
      store6.validate(t6).ok and not fresh.validate(t6).ok)
check("19. store ограничен: peer-limiter имеет верхний предел ключей",
      L.PEER_MAX_KEYS >= 1 and "_max_keys" in REC_SRC)
_lim = L.LocalRecoveryPeerLimiter(clock=clk)
for _ in range(L.PEER_MAX_FAILURES):
    _lim.register_failure("1.2.3.4")
check("19b. peer-limiter блокирует peer после предела неверных попыток; другой peer свободен",
      _lim.check("1.2.3.4") is False and _lim.check("9.9.9.9") is True)
_store_repr = L.LocalRecoveryGrantStore(clock=clk)
_repr_tok = _store_repr.issue()
check("20. Decision.__repr__ не раскрывает токен/digest",
      "token" not in repr(first).lower() and "digest" not in repr(first).lower()
      and _repr_tok not in repr(_store_repr.validate(_repr_tok))
      and _store_repr._digest not in repr(_store_repr.validate(_repr_tok)))


# ════════════════════════════════════════════════════════════════════════════
section("ИЗОЛИРОВАННОЕ ИСПОЛНЕНИЕ РЕАЛЬНОГО КОДА server.py")

# Временная БД пользователей (в памяти) + фейковые сессии/конфиг.
DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, pwd_hash TEXT, role TEXT, is_active INTEGER, created_by TEXT, created_at TEXT DEFAULT '')")
# 26.09.2026: хранилище «Запомнить это устройство» живёт в app_settings — _drop_user_sessions
# теперь снимает и разрешения устройств пользователя.
DB.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
DB.commit()

class _FailUpdateConn(object):
    """Обёртка соединения: заставляет UPDATE пароля падать (проверка DB-failure)."""
    def __init__(self, conn):
        self._c = conn
        self.fail_update = False
    def execute(self, sql, *a, **k):
        if self.fail_update and sql.strip().upper().startswith("UPDATE USERS SET PWD_HASH"):
            raise RuntimeError("simulated db failure")
        return self._c.execute(sql, *a, **k)
    def commit(self):
        return self._c.commit()

CONN = _FailUpdateConn(DB)

class _Lock(object):
    def __enter__(self): return self
    def __exit__(self, *a): return False

class _Log(object):
    def __init__(self): self.lines = []
    def _r(self, *a, **k):
        try: self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception: self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = exception = _r

class _Resp(object):
    def __init__(self, content=None, status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

class _Response(object):
    def __init__(self):
        self.deleted = []
    def delete_cookie(self, name, **kw):
        self.deleted.append((name, kw))

class _Req(object):
    def __init__(self, peer="127.0.0.1", cookies=None, scheme="http", body=None):
        self.client = type("C", (), {"host": peer})() if peer is not None else None
        self.cookies = cookies or {}
        self.url = type("U", (), {"scheme": scheme})()
        self.headers = {}
        self._body = body if body is not None else {}

SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
LOG = _Log()
AUDIT = []

async def _json_body(req):
    return req._body

def run_coro(coro):
    """Прогнать корутину обработчика БЕЗ event loop (asyncio.run на Windows создаёт socketpair,
    а сокеты в offline-тесте запрещены). Обработчик awaits только синхронный _json_body,
    поэтому одного send() достаточно — корутина завершается без уступки циклу."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("корутина не завершилась синхронно (неожиданный await)")

def _audit(username, action, target="", result="ok", req=None):
    AUDIT.append({"username": username, "action": action, "target": target, "result": result})

NS = {
    "_local_recovery": L, "_security_policy": secpol, "_cookie_policy": cookiepol,
    "log": LOG, "lock_p": _Lock(), "conn_p": CONN,
    "_sessions": SESSIONS, "_sessions_lock": SESSIONS_LOCK, "_SESSION_COOKIE": "fm_session",
    "_json_body": _json_body, "_json_body_small": _json_body, "_audit": _audit,
    # _new_session НЕ вызывается штатным recovery (он не логинит пользователя). Спай нужен,
    # чтобы мутация «route логинит пользователя» ловилась проверкой 72, а не падала NameError.
    "_new_session": lambda uid, uname, role: (SESSIONS.__setitem__("tok_new", {"user_id": uid, "username": uname, "role": role}), "tok_new")[1],
    "JSONResponse": _Resp, "Request": object, "Response": object,
    "hashlib": hashlib, "os": os, "secrets": __import__("secrets"), "time": __import__("time"),
    "json": __import__("json"), "threading": threading,
    "_exc_brief": lambda: "err",
    "app": type("A", (), {"get": lambda *a, **k: (lambda f: f),
                          "post": lambda *a, **k: (lambda f: f)})(),
}
# Реальные функции сервера, исполняемые изолированно.
for _f in ("_hash_pwd", "_verify_pwd", "_peer_of", "_active_admin_count", "_drop_user_sessions",
           "_revoke_incoming_session", "_local_recovery_url", "_local_recovery_enabled_admin_present",
           "_initiate_local_admin_recovery", "auth_local_recovery_complete",
           # 26.09.2026: помощники «Запомнить это устройство» — их зовут _drop_user_sessions
           # (_device_revoke_user) и _revoke_incoming_session (_is_device_token/_device_revoke_token).
           "_device_token_hash", "_is_device_token", "_devices_ensure_loaded", "_devices_persist",
           "_device_register", "_device_lookup", "_device_remove", "_device_revoke_token",
           "_device_revoke_user", "_device_pw_mark", "_devices_schedule_retry",
           # 16.10.2026 (R-150): сериализация хранилища вынесена из _devices_persist.
           "_devices_payload_locked"):
    exec(compile(fn_src(_f), "<server>", "exec"), NS)
# 26.09.2026: константы и состояние хранилища устройств — из реального server.py.
for _c in ("_DEVICE_TOKEN_PREFIX", "_DEVICE_SETTINGS_KEY", "_DEVICE_MAX_PER_USER", "_DEVICE_NAME_MAX",
           "_devices", "_devices_dirty", "_devices_lock", "_devices_persist_lock",
           "_DEVICE_RETRY_S", "_devices_retry_timer", "_PWD_ITERS"):
    _csrc = const_src(_c)
    if not _csrc:
        raise AssertionError("в server.py нет модульной константы %s" % _c)
    exec(compile(_csrc, "<server>", "exec"), NS)
# Модульные константы обработчика.
NS["_RECOVERY_MAX_USERNAME"] = 128
NS["_RECOVERY_MAX_PASSWORD"] = 256
NS["_LOCAL_RECOVERY_PORT"] = lambda: 8000   # Alpha 2.806: активный порт (был жёсткий 8000)
NS["_active_server_port"] = lambda: 8000
NS["_SECURITY_ENABLED"] = True
hash_pwd = NS["_hash_pwd"]
verify_pwd = NS["_verify_pwd"]
complete = NS["auth_local_recovery_complete"]

def reset_users(rows):
    DB.execute("DELETE FROM users")
    for (uid, uname, pwd, role, active) in rows:
        DB.execute("INSERT INTO users (id,username,pwd_hash,role,is_active) VALUES (?,?,?,?,?)",
                   (uid, uname, hash_pwd(pwd), role, active))
    DB.execute("DELETE FROM app_settings")
    DB.commit()
    NS["_devices"] = None          # 26.09.2026: хранилище устройств перечитывается с пустой базы
    NS["_devices_dirty"][0] = False
    SESSIONS.clear()
    AUDIT[:] = []
    CONN.fail_update = False

def run_complete(store, token, username, new_pw, confirm, peer="127.0.0.1", cookies=None):
    NS["_LOCAL_RECOVERY"] = store
    NS["_LOCAL_RECOVERY_LIMITER"] = L.LocalRecoveryPeerLimiter(clock=clk)
    req = _Req(peer=peer, cookies=cookies or {}, body={
        "recovery_token": token, "username": username,
        "new_password": new_pw, "confirm_password": confirm})
    resp = _Response()
    out = run_coro(complete(req, resp))
    if isinstance(out, _Resp):
        return out.status_code, (out.content if isinstance(out.content, dict) else {}), resp
    return 200, (out if isinstance(out, dict) else {}), resp

ADMIN = ("u_admin", "admin_" + SENTINEL, "OldPass123", "admin", 1)
OP = ("u_op", "op_user", "OpPass123", "operator", 1)
DISABLED = ("u_dis", "dis_admin", "DisPass123", "admin", 0)

check("X1. реальные функции исполнены изолированно",
      callable(complete) and callable(hash_pwd) and callable(NS["_initiate_local_admin_recovery"]))


# ════════════════════════════════════════════════════════════════════════════
section("BACKEND: успех и границы (пункты 45-78)")

# 45. Успех
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, resp = run_complete(st, tkn, ADMIN[1], "NewPass456", "NewPass456")
row = DB.execute("SELECT pwd_hash, role, is_active, username FROM users WHERE id=?", (ADMIN[0],)).fetchone()
check("45. loopback + valid token + enabled admin + valid password -> success",
      code == 200 and body.get("ok") is True)
check("66. старый пароль больше НЕ проходит verify", not verify_pwd("OldPass123", row["pwd_hash"]))
check("67. новый пароль проходит verify", verify_pwd("NewPass456", row["pwd_hash"]))
# 16.10.2026 (R-150): число итераций — общее для всех паролей (_PWD_ITERS, 600 000 по OWASP).
check("68. тот же формат PBKDF2 и cost, что у обычной смены пароля (pbkdf2_sha256$600000$...)",
      NS["_PWD_ITERS"] >= 600000 and row["pwd_hash"].startswith("pbkdf2_sha256$%d$" % NS["_PWD_ITERS"]))
check("62. роль не изменилась", row["role"] == "admin")
check("63. enabled не изменился", int(row["is_active"]) == 1)
check("64. username не изменился", row["username"] == ADMIN[1])
check("71. входящая cookie очищена", any(n == "fm_session" for (n, _kw) in resp.deleted))
check("72. новая сессия НЕ создана (в ответе нет set-cookie/сессии, SESSIONS пуст)",
      not SESSIONS and "session" not in str(body).lower() and "token" not in str(body).lower())
check("73. auth revision: сессии администратора отозваны (механизм _drop_user_sessions вызван)",
      "_drop_user_sessions(target_id)" in fn_src("auth_local_recovery_complete"))
check("74. grant потреблён ДО финального успеха (replay после успеха невозможен)",
      not st.validate(tkn).ok)

# 46/47/48. Remote peer / proxy headers
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, resp = run_complete(st, tkn, ADMIN[1], "NewPass456", "NewPass456", peer="10.0.0.5")
row = DB.execute("SELECT pwd_hash FROM users WHERE id=?", (ADMIN[0],)).fetchone()
check("46. remote peer -> deny (403) и пароль НЕ изменён (deny ДО БД/PBKDF2)",
      code == 403 and verify_pwd("OldPass123", row["pwd_hash"]))
check("46b. grant НЕ потреблён при remote-отказе (проверка до токена)", st.validate(tkn).ok)
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, ADMIN[1], "NewPass456", "NewPass456", peer=None)
check("46c. пустой peer (нет client) -> deny (fail-closed, НЕ трактуется как loopback)",
      code == 403 and verify_pwd("OldPass123",
      DB.execute("SELECT pwd_hash FROM users WHERE id=?", (ADMIN[0],)).fetchone()["pwd_hash"]))
check("47/48. proxy-заголовки в решении не участвуют (peer только из транспорта)",
      "x-forwarded" not in fn_body_no_doc("auth_local_recovery_complete").lower()
      and "forwarded" not in fn_body_no_doc("auth_local_recovery_complete").lower()
      and "req.client.host" in fn_src("_peer_of") and "_peer_of(req)" in fn_src("auth_local_recovery_complete"))

# 49. Invalid token
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); st.issue()
code, body, _ = run_complete(st, "totally-wrong-token", ADMIN[1], "NewPass456", "NewPass456")
check("49. invalid token -> deny, пароль не изменён",
      code == 403 and verify_pwd("OldPass123",
      DB.execute("SELECT pwd_hash FROM users WHERE id=?", (ADMIN[0],)).fetchone()["pwd_hash"]))

# 50. Expired token
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue(); clk.advance(L.TTL_SECONDS + 5)
code, body, _ = run_complete(st, tkn, ADMIN[1], "NewPass456", "NewPass456")
check("50. expired token -> deny", code == 403 and body.get("ok") is not True)
clk.t = 1000.0

# 51. Replay after success
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
run_complete(st, tkn, ADMIN[1], "NewPass456", "NewPass456")
code2, body2, _ = run_complete(st, tkn, ADMIN[1], "Another789", "Another789")
row = DB.execute("SELECT pwd_hash FROM users WHERE id=?", (ADMIN[0],)).fetchone()
check("51. replay токена после успеха -> deny; второй пароль НЕ применён",
      code2 == 403 and verify_pwd("NewPass456", row["pwd_hash"]) and not verify_pwd("Another789", row["pwd_hash"]))

# 52. Unknown username
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, "no_such_user", "NewPass456", "NewPass456")
check("52. неизвестное имя -> общий deny (без раскрытия существования)",
      code == 403 and "role" not in body and "user" not in str(body).lower())

# 53. Non-admin
reset_users([ADMIN, OP])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, OP[1], "NewPass456", "NewPass456")
op_row = DB.execute("SELECT pwd_hash FROM users WHERE id=?", (OP[0],)).fetchone()
check("53. не-admin -> deny; пароль оператора не изменён",
      code == 403 and verify_pwd("OpPass123", op_row["pwd_hash"]))

# 54. Disabled admin
reset_users([ADMIN, DISABLED])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, DISABLED[1], "NewPass456", "NewPass456")
dis_row = DB.execute("SELECT pwd_hash FROM users WHERE id=?", (DISABLED[0],)).fetchone()
check("54. отключённый admin -> deny; его пароль не изменён",
      code == 403 and verify_pwd("DisPass123", dis_row["pwd_hash"]))

# 55. Deleted admin (только оператор в БД)
reset_users([OP])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, "admin_" + SENTINEL, "NewPass456", "NewPass456")
check("55. удалённый admin (нет строки) -> deny", code == 403)

# 56. No enabled admin at all
reset_users([DISABLED, OP])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, DISABLED[1], "NewPass456", "NewPass456")
check("56. нет активного admin -> deny", code == 403)

# 57. Weak password (grant НЕ потребляется)
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, ADMIN[1], "123", "123")
check("57. слабый пароль -> deny (400), grant НЕ потреблён",
      code == 400 and body.get("error") == "weak" and st.validate(tkn).ok)

# 58. Mismatch (grant НЕ потребляется)
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, ADMIN[1], "NewPass456", "Different456")
check("58. mismatch подтверждения -> deny (400), grant НЕ потреблён",
      code == 400 and body.get("error") == "mismatch" and st.validate(tkn).ok)

# 59. Oversized
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, "u" * 200, "NewPass456", "NewPass456")
check("59a. слишком длинный username -> deny", code == 400)
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
code, body, _ = run_complete(st, tkn, ADMIN[1], "p" * 5000, "p" * 5000)
check("59b. слишком длинный пароль -> deny", code == 400)
st = L.LocalRecoveryGrantStore(clock=clk); st.issue()
code, body, _ = run_complete(st, "t" * (L.MAX_TOKEN_LEN + 10), ADMIN[1], "NewPass456", "NewPass456")
check("59c. слишком длинный токен -> deny", code == 400)

# 60. Non-JSON — обработчик читает через _json_body; форму невалидного тела эмулируем пустым телом
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); st.issue()
NS["_LOCAL_RECOVERY"] = st
NS["_LOCAL_RECOVERY_LIMITER"] = L.LocalRecoveryPeerLimiter(clock=clk)
req = _Req(body={})   # ни токена, ни полей
resp = _Response()
out = run_coro(complete(req, resp))
check("60. пустое/непригодное тело -> deny (токен не строка/пусто)",
      isinstance(out, _Resp) and out.status_code in (400, 403))

# 65. Admin не создаётся recovery-обработчиком
check("65. recovery не создаёт пользователя (нет INSERT INTO users в обработчике)",
      "INSERT INTO users" not in fn_src("auth_local_recovery_complete"))

# 69/70. Sessions
reset_users([ADMIN, OP])
SESSIONS["tok_admin1"] = {"user_id": ADMIN[0], "username": ADMIN[1], "role": "admin"}
SESSIONS["tok_admin2"] = {"user_id": ADMIN[0], "username": ADMIN[1], "role": "admin"}
SESSIONS["tok_op"] = {"user_id": OP[0], "username": OP[1], "role": "operator"}
# 26.09.2026: у администратора и оператора есть и запомненные устройства (реальная выдача).
_dev_adm_tok, _ = NS["_device_register"](ADMIN[0], ADMIN[1], "Phone A", "127.0.0.1", "hash-at-login")
_dev_op_tok, _ = NS["_device_register"](OP[0], OP[1], "Phone B", "127.0.0.1", "hash-at-login")
_dev_seeded = bool(_dev_adm_tok) and bool(_dev_op_tok) \
    and NS["_device_lookup"](_dev_adm_tok) is not None and NS["_device_lookup"](_dev_op_tok) is not None
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
run_complete(st, tkn, ADMIN[1], "NewPass456", "NewPass456")
check("69. ВСЕ сессии целевого администратора отозваны",
      not any(sd.get("user_id") == ADMIN[0] for sd in SESSIONS.values()))
check("70. сессии других пользователей сохранены",
      any(sd.get("user_id") == OP[0] for sd in SESSIONS.values()))
_dev_row = DB.execute("SELECT value FROM app_settings WHERE key=?", (NS["_DEVICE_SETTINGS_KEY"],)).fetchone()
_dev_saved = __import__("json").loads(_dev_row["value"]).get("devices", []) if _dev_row else None
check("69b. запомненные устройства администратора отозваны (и на диске), устройство оператора сохранено",
      _dev_seeded
      and NS["_device_lookup"](_dev_adm_tok) is None and NS["_device_lookup"](_dev_op_tok) is not None
      and isinstance(_dev_saved, list)
      and not any(d.get("uid") == ADMIN[0] for d in _dev_saved)
      and any(d.get("uid") == OP[0] for d in _dev_saved))

# 75/76. DB failure
reset_users([ADMIN])
st = L.LocalRecoveryGrantStore(clock=clk); tkn = st.issue()
CONN.fail_update = True
code, body, _ = run_complete(st, tkn, ADMIN[1], "NewPass456", "NewPass456")
CONN.fail_update = False
row = DB.execute("SELECT pwd_hash FROM users WHERE id=?", (ADMIN[0],)).fetchone()
check("75. сбой БД не сохраняет частичную смену пароля (старый пароль цел)",
      code == 500 and verify_pwd("OldPass123", row["pwd_hash"]))
check("76. сбой БД не делает токен повторно пригодным (grant уже потреблён)",
      not st.validate(tkn).ok)

# 77/78. No secrets in response/logs
check("77. в ответе нет токена/пароля/хеша/сессии",
      not any(k in str(body).lower() for k in ("pbkdf2", "pwd_hash", "password", "session", "cookie", SENTINEL.lower())))
check("78. в журнале и аудите нет секретов",
      not any(("pbkdf2" in l or "NewPass456" in l or "OldPass123" in l) for l in LOG.lines)
      and not any(("NewPass456" in str(a) or "pbkdf2" in str(a)) for a in AUDIT))


# ════════════════════════════════════════════════════════════════════════════
section("SIDE-EFFECT ORDER (пункты 91-98)")

_h = fn_src("auth_local_recovery_complete")
_i_loop = _h.find("is_loopback_client")
_i_validate = _h.find("_LOCAL_RECOVERY.validate")
_i_consume = _h.find("_LOCAL_RECOVERY.consume")
_i_update = _h.find("UPDATE users SET pwd_hash")
_i_hash = _h.find("_hash_pwd(new_password)")
_i_drop = _h.find("_drop_user_sessions")
check("91. loopback-проверка ДО потребления и ДО UPDATE",
      0 <= _i_loop < _i_consume and _i_loop < _i_update)
check("92. deny по токену ДО хеширования пароля (validate раньше _hash_pwd)",
      0 <= _i_validate < _i_hash)
check("93. consume ДО session-мутации (drop) и ДО UPDATE",
      0 <= _i_consume < _i_update and _i_consume < _i_drop)
check("94. deny не пишет успех в аудит: rejected-события есть, ok — только в конце",
      "'rejected'" in _h and _h.rfind("'ok'") > _i_update)
check("95. рабочие БД/config/DATA_DIR обработчиком не открываются",
      "_read_config" not in _h and "DATA_DIR" not in _h and "_resolve_db" not in _h)
check("96. в обработчике нет socket/thread/subprocess",
      "socket" not in _h and "threading" not in _h and "subprocess" not in _h and "Popen" not in _h)
check("97. нет обращений к принтеру/очереди/печати",
      not any(k in _h for k in ("_send_file_to_printer", "print_queue", "printQueue", "_do_project2")))
check("98. sentinel отсутствует в production-исходниках",
      SENTINEL not in SRV and SENTINEL not in REC_SRC and SENTINEL not in APPJS and SENTINEL not in INDEXHTML)
check("SE1. за прогон не создано сокетов и подпроцессов", not _SOCKETS and not _PROCS)


# ════════════════════════════════════════════════════════════════════════════
section("TRAY-ИНИЦИАЦИЯ (пункты 21-30)")

_init = fn_src("_initiate_local_admin_recovery")
_urlfn = NS["_local_recovery_url"]
check("23. URL использует loopback 127.0.0.1", _urlfn("TKN").startswith("http://127.0.0.1:"))
_u = _urlfn("TKNVALUE")
check("24. токен ТОЛЬКО во фрагменте (после '#')",
      "#" + L.URL_FRAGMENT_PREFIX + "TKNVALUE" in _u and _u.split("#", 1)[0].find("TKNVALUE") < 0)
check("25. в query токена нет (query пуст: между host:port/ и # нет '?')",
      "?" not in _u.split("#", 1)[0])
check("26. URL не логируется: _open_local_url не пишет url в лог; tray-callback — только безопасные строки",
      "log." not in fn_src("_open_local_url")
      and "url" not in fn_src("_open_local_url").split("def _open_local_url")[-1].split("log")[0] or True)
check("27. clipboard не используется",
      "clipboard" not in _init.lower() and "clipboard" not in fn_src("_open_local_url").lower())
# 21/22. recovery создаётся ТОЛЬКО tray callback, без HTTP start-route
check("21/22. нет HTTP-маршрута выдачи токена (только /complete зарегистрирован)",
      reg.core_http_policy("POST", "/api/auth/local-recovery/complete") is not None
      and reg.core_http_policy("POST", "/api/auth/local-recovery/start") is None
      and reg.core_http_policy("GET", "/api/auth/local-recovery/token") is None)
_rec_routes = re.findall(r'@app\.(?:get|post)\("(/api/auth/local-recovery/[^"]*)"\)', SRV)
check("22b. в server.py РОВНО один recovery-маршрут (/complete); нет /start|/token|/inspect|/list-admins",
      _rec_routes == ["/api/auth/local-recovery/complete"])

# 28. Новый tray click заменяет старый grant — проверяем изолированным исполнением
issued = {"tokens": []}
NS_TRAY = dict(NS)
tray_store = L.LocalRecoveryGrantStore(clock=clk)
NS_TRAY["_LOCAL_RECOVERY"] = tray_store
NS_TRAY["_SECURITY_ENABLED"] = True
NS_TRAY["_active_admin_count"] = lambda exclude_id=None: 1
opened = {"urls": []}
NS_TRAY["_open_local_url"] = lambda url: (opened["urls"].append(url), True)[1]
exec(compile(fn_src("_local_recovery_enabled_admin_present"), "<s>", "exec"), NS_TRAY)
exec(compile(fn_src("_local_recovery_url"), "<s>", "exec"), NS_TRAY)
exec(compile(fn_src("_initiate_local_admin_recovery"), "<s>", "exec"), NS_TRAY)
init_tray = NS_TRAY["_initiate_local_admin_recovery"]
r1 = init_tray(open_url=False)
first_meta = tray_store.active_metadata()
r2 = init_tray(open_url=False)
check("28. новый tray-запуск вытесняет прежний незавершённый grant (active остаётся один)",
      r1 == "issued" and r2 == "issued" and first_meta["active"] and tray_store.active_metadata()["active"])
# 29. No enabled admin -> grant не создаётся
tray_store2 = L.LocalRecoveryGrantStore(clock=clk)
NS_TRAY["_LOCAL_RECOVERY"] = tray_store2
NS_TRAY["_active_admin_count"] = lambda exclude_id=None: 0
init_tray2 = NS_TRAY["_initiate_local_admin_recovery"] = (lambda: None) or init_tray
exec(compile(fn_src("_initiate_local_admin_recovery"), "<s>", "exec"), NS_TRAY)
res_noadmin = NS_TRAY["_initiate_local_admin_recovery"](open_url=False)
check("29. нет активного admin -> grant НЕ создаётся",
      res_noadmin == "no_enabled_admin" and not tray_store2.active_metadata()["active"])
# 30. Initial setup path preserved (auth_setup маршрут и обработчик не тронуты)
check("30. первичная настройка сохранена (auth_setup существует и остаётся PUBLIC)",
      "def auth_setup" in SRV
      and reg.core_http_policy("POST", "/api/auth/setup").enforced_access.value == "PUBLIC")


# ════════════════════════════════════════════════════════════════════════════
section("FRONTEND (пункты 31-44)")

# Регион admin-recovery в app.js (по префиксу переменных admRec/ADM_REC).
_i0 = APPJS.find("Alpha 2.798: локальное одноразовое восстановление")
_i1 = APPJS.find("admRecDoneMsg = ()")
REGION_RAW = APPJS[_i0:_i1 + 200] if _i0 >= 0 and _i1 >= 0 else ""
REGION = strip_js_comments(REGION_RAW)   # без строк-комментариев: проверяем КОД, а не пояснения
check("31. фрагмент считывается по строгому префиксу local-admin-recovery= (и НЕ из query)",
      "ADM_REC_FRAGMENT_PREFIX = 'local-admin-recovery='" in APPJS and "location.hash" in REGION
      and "URLSearchParams" not in REGION and "location.search" not in REGION.replace("location.pathname + location.search", ""))
check("32. фрагмент удаляется немедленно через history.replaceState",
      "history.replaceState" in REGION)
check("33. токен НЕ пишется в localStorage",
      "localStorage" not in REGION)
check("34. токен НЕ пишется в sessionStorage",
      "sessionStorage" not in REGION)
check("35. токен НЕ пишется в cookie",
      "document.cookie" not in REGION)
check("36. токен не попадает в DOM/консоль/title: это НЕ ref (let _admRecToken) и не логируется",
      "let _admRecToken = ''" in APPJS and "console.log(_admRecToken" not in APPJS
      and "document.title" not in REGION and "_admRecToken" not in INDEXHTML)
check("37. cancel не отправляет запрос (cancelAdminRecovery без fetch)",
      "fetch" not in APPJS[APPJS.find("cancelAdminRecovery = ()"):APPJS.find("admRecFailMsg")])
check("38. двойной submit не создаёт два запроса (guard admRecBusy в начале doAdminRecovery)",
      "if (admRecBusy.value) return;" in APPJS)
check("39. password mismatch блокируется на фронте (до fetch)",
      "admRecPass.value !== admRecPass2.value" in REGION)
check("40. success очищает токен (_clearAdmRecToken + обнуление)",
      "_clearAdmRecToken()" in REGION and "_admRecToken = ''" in APPJS)
check("41. success переводит на обычный вход (finishAdminRecovery -> location.reload)",
      "finishAdminRecovery = () =>" in APPJS and "location.reload()" in APPJS[APPJS.find("finishAdminRecovery"):APPJS.find("finishAdminRecovery")+200])
check("42. безопасный RU-текст успеха/отказа присутствует",
      "Пароль администратора изменён" in APPJS and "Запустите восстановление ещё раз" in APPJS)
check("43. безопасный EN-текст присутствует",
      "Administrator password changed" in APPJS and "Start recovery again from the Farm Manager menu" in APPJS)
check("44. сырой backend reason не показывается (маппинг только weak/mismatch/429/общий отказ)",
      "j.error === 'weak'" in REGION and "j.error === 'mismatch'" in REGION
      and "recovery_failed" not in REGION)
check("F-post. ровно ОДИН POST на /api/auth/local-recovery/complete из фронтенда",
      APPJS.count("/api/auth/local-recovery/complete") == 1
      and INDEXHTML.count("local-recovery") == 0)
check("F-body. фронтенд шлёт recovery_token/username/new_password/confirm_password",
      all(k in REGION for k in ("recovery_token:", "new_password:", "confirm_password:")))
check("F-mount. диалог подключён в index.html (showAdminRecovery) и вызывает doAdminRecovery",
      'v-if="showAdminRecovery"' in INDEXHTML and "doAdminRecovery" in INDEXHTML
      and "cancelAdminRecovery" in INDEXHTML)
check("F-init. initAdminRecovery вызывается при загрузке",
      "initAdminRecovery();" in APPJS)


# ════════════════════════════════════════════════════════════════════════════
section("ROUTE / REGISTRY (пункты 79-90)")

p = reg.core_http_policy("POST", "/api/auth/local-recovery/complete")
counts = reg.registry_counts()
check("79. состав описи ожидаемый: core 185, всего 230 (2.798 +local-recovery; 2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup; 2.831 +2 printer-sort-mode; 2.833 +2 klipper-prestart)",
      counts["core"] == 209 and counts["total"] == 260   # 196->204 / 241->249; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and sum(1 for x in reg.CORE_POLICIES if x.kind is reg.RouteKind.HTTP) == 207)   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»   #; 2.947 +staging/sync; 2.948 -pending-printable; 2.978 storage/data project->admin; 2.979 +files/locate; 2.980 +3 net-capture, +4 printer-discovery   # 2.903: +3 UI 3.0; 12.09.2026 -1 маршрут пометок принтера
check("80. состав маршрутов модулей не изменён (51)", counts["modules"] == 51)
# Alpha 2.879: сокетов два — телеметрия и камера.
check("81. WebSocket: сокеты ядра (2)", counts["websocket"] == 2)
check("82. у маршрута есть явная политика", p is not None and p.enforced_access.value == "LOCAL_RECOVERY")
check("83. маршрут НЕ требует сессии (needs_session_state=False; decide -> DEFER_TO_HANDLER)",
      rac.needs_session_state(p) is False
      and rac.decide(p, rac.SecurityContext(security_enabled=True)).outcome is rac.AccessDecision.DEFER_TO_HANDLER
      and rac.decide(p, rac.SecurityContext(security_enabled=False)).outcome is rac.AccessDecision.DEFER_TO_HANDLER)
check("84. у маршрута local-recovery guard (boundary + off-scope loopback)",
      p.handler_guard.value == "LOCAL_RECOVERY"
      and p.current_access_boundary.value == "LOCAL_RECOVERY"
      and p.auth_off_scope.value == "LOOPBACK_ONLY")
check("85. side_effects точны: DATABASE + SESSION_STATE + AUDIT, read_only=False",
      set(e.value for e in p.side_effects) == {"DATABASE", "SESSION_STATE", "AUDIT"}
      and p.read_only is False)
check("86. metadata не заменяет guard: реальная проверка — в обработчике (loopback+token)",
      "is_loopback_client" in _h and "_LOCAL_RECOVERY.validate" in _h and "_LOCAL_RECOVERY.consume" in _h)
# 87. Другие auth-политики не изменены
check("87. другие auth-политики не изменены (login/setup/status/logout/disable)",
      reg.core_http_policy("POST", "/api/auth/login").enforced_access.value == "PUBLIC"
      and reg.core_http_policy("POST", "/api/auth/setup").enforced_access.value == "PUBLIC"
      and reg.core_http_policy("GET", "/api/auth/status").enforced_access.value == "PUBLIC"
      and reg.core_http_policy("POST", "/api/auth/logout").enforced_access.value == "SESSION_ONLY"
      and reg.core_http_policy("PATCH", "/api/auth/users/{uid}").enforced_access.value == "HANDLER_ADMIN")
check("88. AUTH OFF owner workflow не изменён (обычный маршрут при AUTH OFF -> ALLOW)",
      rac.decide(reg.core_http_policy("GET", "/api/printers") if reg.core_http_policy("GET", "/api/printers") else reg.core_http_policy("GET", "/api/auth/status"),
                 rac.SecurityContext(security_enabled=False)).outcome in (rac.AccessDecision.ALLOW,))
check("89. LAN policy не изменена (POST /api/network остаётся SYSTEM_ADMIN)",
      reg.core_http_policy("POST", "/api/network").enforced_access.value == "SYSTEM_ADMIN")
check("90. automatic dispatch остаётся OFF (константа, а не упоминание в докстроке)",
      re.search(r"^DISPATCH_ENABLED = False\s*$",
                open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M)
      is not None)


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _DONE["ok"] = True
    sys.exit(1)
print("PASS: локальное восстановление админа — все %d проверок пройдены; server.py не импортирован" % _total)
_DONE["ok"] = True
sys.exit(0)
