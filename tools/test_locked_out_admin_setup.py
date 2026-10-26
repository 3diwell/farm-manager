# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  R-128, шаг 2 (Alpha 3.0) — выход для ЗАПЕРТОЙ фермы.
#
#  ЗАЧЕМ. Защита входом включена, а включённых администраторов ноль (например, копию настроек
#  восстановила старая версия программы: флаг защиты приехал, таблица пользователей — нет).
#  Раньше /api/auth/setup отвечал already_enabled, восстановление из трея требовало
#  администратора, повторное восстановление копии — его сессию: тупик. Теперь на ЭТОМ
#  компьютере (адрес из транспорта, только loopback) можно создать администратора; во всех
#  остальных случаях ответ прежний.
#
#  ЧТО ПРОВЕРЯЕТСЯ.
#   U* — настоящие функции server.py (_locked_out_setup_allowed, _enabled_admin_check,
#        auth_setup, auth_status) исполняются изолированно (разбор AST, sqlite в памяти):
#        адрес не из loopback, подложный X-Forwarded-For, «localhost» строкой, нет адреса,
#        сбой базы (UNKNOWN), отключённый администратор, занятый логин, гонка двух запросов,
#        подмена DNS (DNS rebinding): 127.0.0.1 с Host/Origin чужого сайта — отказ (U19-U23).
#   E* — НАСТОЯЩИЙ процесс программы в изолированном режиме app/e2e_isolation (своя временная
#        папка данных, config, порт, замок; без трея, браузера, обнаружения и принтеров):
#        запертое состояние (security_enabled=1, пользователей нет) -> с 127.0.0.1 создание
#        проходит, повторное — отказ, событие в журнале аудита; администратор есть — отказ.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: рабочие DATA_DIR/config/БД/порт/замок не используются, рабочая
#  программа не останавливается, принтерам ничего не отправляется; временная папка удаляется.
#
#  Запуск:  PYTHONIOENCODING=utf-8 python tools/test_locked_out_admin_setup.py   (0 = пройдено)
# ============================================================================
import ast
import asyncio
import glob
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from app import auth_rate_limit as RL               # noqa: E402
from app import session_cookie_policy as CP         # noqa: E402
from app import lan_access_policy as LANP           # noqa: E402
from app import security_policy as SECP             # noqa: E402
from app import e2e_isolation as ISO                # noqa: E402
from app import host_header_policy as HOSTP         # noqa: E402

FAILED = []
NAMES = []


def check(name, ok, extra=""):
    NAMES.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,)) if (not ok and extra != "") else ""), flush=True)
    if not ok:
        FAILED.append(name)


def section(t):
    print("\n--- %s ---" % t, flush=True)


SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
TREE = ast.parse(SRC)
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)


def fn_src(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    raise AssertionError("в server.py нет функции %s" % name)


def const_src(name):
    for n in TREE.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.unparse(n)
    raise AssertionError("в server.py нет константы %s" % name)


# ════════════════════════════════════════════════════════════════════════════
section("исходники: выход подключён в обработчике, окне входа и журнале")
SETUP_SRC = fn_src("auth_setup")
STATUS_SRC = fn_src("auth_status")
HTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
JS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
check("S1. auth_setup при включённой защите спрашивает _locked_out_setup_allowed",
      "_locked_out_setup_allowed(req)" in SETUP_SRC and "already_enabled" in SETUP_SRC)
check("S2. auth_status отдаёт признак setup_available только через ту же проверку",
      "setup_available" in STATUS_SRC and "_locked_out_setup_allowed(req)" in STATUS_SRC)
_login = re.search(r'<div v-if="authEnabled && !authUser" class="fm-login-overlay">.*?</teleport>', HTML, re.S)
check("S3. окно входа показывает «Создать администратора» по признаку сервера и открывает окно настройки",
      bool(_login) and 'v-if="authSetupAvailable"' in _login.group(0) and 'openSecuritySetup' in _login.group(0)
      and 'Создать администратора' in _login.group(0) and 'Create administrator' in _login.group(0))
_ALLOWED_SRC = fn_src("_locked_out_setup_allowed")
_HDR_SRC = fn_src("_local_page_headers_ok")
check("S5. выход проверяет Host и Origin по правилу R-124 до обращения к базе",
      "_local_page_headers_ok(req)" in _ALLOWED_SRC
      and _ALLOWED_SRC.index("_local_page_headers_ok(req)") < _ALLOWED_SRC.index("_enabled_admin_check()")
      and _HDR_SRC.count("auth_enabled=False") == 2 and "parse_origin" in _HDR_SRC)
check("S4. интерфейс читает setup_available и знает событие журнала",
      "j.setup_available" in JS and "'security.local_admin_setup'" in JS and "authSetupAvailable," in JS)

# ════════════════════════════════════════════════════════════════════════════
section("функции server.py изолированно")
DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, pwd_hash TEXT NOT NULL DEFAULT '', "
           "role TEXT DEFAULT 'operator', is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
           "created_by TEXT DEFAULT '')")
DB.commit()
STATE = {"fault": False, "queries": 0}


class _DB:
    def execute(self, sql, *a, **k):
        STATE["queries"] += 1
        if STATE["fault"]:
            raise sqlite3.OperationalError("database is locked (изображено тестом)")
        return DB.execute(sql, *a, **k)

    def commit(self):
        return DB.commit()

    def rollback(self):
        return DB.rollback()


class _Lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Resp:
    def __init__(self, content=None, status_code=200, headers=None):
        self.content, self.status_code, self.headers = content, status_code, headers or {}


class _Log:
    def __init__(self): self.lines = []
    def _r(self, *a, **k): self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = _r


class _Limiter:
    def check(self, *a): return type("D", (), {"allow": True, "reason": "", "retry_after": 0})()
    def register_failure(self, *a): pass


class FakeResponse:
    def __init__(self): self.set = []
    def set_cookie(self, key, value, **kw): self.set.append((key, value))


class Headers(dict):
    def get(self, k, d=None):
        return dict.get(self, str(k).lower(), d)


class Req:
    def __init__(self, data=None, client="127.0.0.1", headers=None):
        self._data = data or {}
        self.cookies = {}
        self.headers = Headers({str(k).lower(): v for k, v in (headers or {}).items()})
        self.client = None if client is None else type("C", (), {"host": client})()
        self.url = type("U", (), {"scheme": "http"})()


async def _json_body(req):
    return req._data


AUDIT, LOG = [], _Log()


def _set_security_enabled(on):
    NS["_SECURITY_ENABLED"] = bool(on)


NS = {
    "_auth_rl": RL, "_cookie_policy": CP, "_lan_policy": LANP, "_security_policy": SECP, "sqlite3": sqlite3,
    "secrets": secrets, "hashlib": __import__("hashlib"), "os": os, "time": time, "uuid": __import__("uuid"),
    "JSONResponse": _Resp, "log": LOG, "lock_p": _Lock(), "conn_p": _DB(), "_AUTH_LIMITER": _Limiter(),
    "_exc_brief": lambda: "ошибка (кратко)", "_audit": lambda *a, **k: AUDIT.append(a[:4]),
    "_json_body": _json_body, "_json_body_small": _json_body, "_set_security_enabled": _set_security_enabled,
    "_device_remove": lambda *a, **k: 0, "_revoke_incoming_session": lambda *a, **k: None,
    "_new_session": lambda *a, **k: "tok_" + secrets.token_hex(8), "_is_device_token": lambda t: False,
    "_session_user": lambda r: None, "_device_check": lambda t: (None, None), "_DEVICE_UNAVAILABLE": "unavailable",
    "app": type("A", (), {"post": lambda *a, **k: (lambda f: f), "get": lambda *a, **k: (lambda f: f)})(),
    "Request": object, "Response": object,
    "_host_policy": HOSTP, "_HOST_LOCAL_NAMES": HOSTP.local_machine_names(["FARM-PC"]),
}
for _c in ("AUTH_ROLES", "_SESSION_COOKIE", "_SESSION_IDLE", "_REMEMBER_DEVICE_PROTOCOL", "_PWD_ITERS"):
    exec(compile(const_src(_c), "<server>", "exec"), NS)
for _n in ("_hash_pwd", "_peer_of", "_uid", "_enabled_admin_check", "_local_page_headers_ok",
           "_locked_out_setup_allowed",
           "auth_setup", "auth_status"):
    exec(compile(fn_src(_n), "<server>", "exec"), NS)

ALLOWED = NS["_locked_out_setup_allowed"]


def setup(user, pwd="Admin-pass-9", **kw):
    r = asyncio.run(NS["auth_setup"](Req({"username": user, "password": pwd}, **kw), FakeResponse()))
    if isinstance(r, _Resp):
        return r.status_code, (r.content or {})
    return 200, r


def users():
    return [dict(r) for r in DB.execute("SELECT username, role, is_active, created_by FROM users ORDER BY rowid")]


# ── U: защита выключена — прежний путь первичной настройки ──
NS["_SECURITY_ENABLED"] = False
check("U1. защита выключена: выход не срабатывает (признак False)", ALLOWED(Req()) is False)
st, js = setup("first")
check("U2. защита выключена: обычная первичная настройка как раньше (security.enable, created_by=setup)",
      st == 200 and js.get("ok") and NS["_SECURITY_ENABLED"] is True and AUDIT[-1][1] == "security.enable"
      and users()[-1]["created_by"] == "setup", (st, js, AUDIT[-1:]))
st, js = setup("second")
check("U3. защита включена и администратор есть: с этого компьютера прежний отказ already_enabled",
      st == 400 and js.get("error") == "already_enabled" and len(users()) == 1, (st, js))
st, js = setup("third", client="192.168.1.50")
check("U4. администратор есть, запрос из сети: прежний отказ", st == 400 and js.get("error") == "already_enabled")

# ── запертое состояние: администратор отключён, есть оператор ──
DB.execute("UPDATE users SET is_active=0")
DB.execute("INSERT INTO users (id, username, pwd_hash, role, is_active) VALUES ('usr_op','ivan','x','operator',1)")
DB.commit()
check("U5. проверка администраторов: отключённый администратор = ABSENT",
      NS["_enabled_admin_check"]() is LANP.AdminCheck.ABSENT)
STATE["queries"] = 0
st, js = setup("netadm", client="192.168.1.50")
check("U6. заперто, запрос из сети: отказ already_enabled, база не тронута (ни одного запроса)",
      st == 400 and js.get("error") == "already_enabled" and STATE["queries"] == 0
      and not [u for u in users() if u["username"] == "netadm"], (st, js, STATE["queries"]))
st, js = setup("xffadm", client="10.0.0.7", headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1",
                                                     "Host": "127.0.0.1"})
check("U7. заперто, подложные X-Forwarded-For/X-Real-IP/Host = 127.0.0.1 из сети: отказ",
      st == 400 and js.get("error") == "already_enabled" and len(users()) == 2, (st, js))
check("U8. «localhost» строкой, пустой адрес и отсутствующий client не считаются этим компьютером",
      ALLOWED(Req(client="localhost")) is False and ALLOWED(Req(client="")) is False
      and ALLOWED(Req(client=None)) is False)
check("U9. loopback в любой записи (127.0.0.1, 127.0.0.2, ::1, ::ffff:127.0.0.1) — этот компьютер",
      all(ALLOWED(Req(client=a)) for a in ("127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1")))
st_net = NS["auth_status"](Req(client="192.168.1.50"))
st_loc = NS["auth_status"](Req(client="127.0.0.1"))
check("U10. окно входа: признак setup_available отдаётся только этому компьютеру",
      st_loc.get("setup_available") is True and "setup_available" not in st_net
      and st_loc.get("authenticated") is False, (st_loc, st_net))
# ── подмена DNS (DNS rebinding): чужая страница в браузере этого компьютера, адрес 127.0.0.1 ──
EVIL = {"Host": "evil.example:8000", "Origin": "http://evil.example:8000"}
_n0 = len(users())
STATE["queries"] = 0
st, js = setup("evil", headers=EVIL)
check("U19. подмена DNS: с 127.0.0.1, Host и Origin = evil.example — отказ already_enabled, база не тронута",
      ALLOWED(Req(headers=EVIL)) is False and st == 400 and js.get("error") == "already_enabled"
      and len(users()) == _n0 and STATE["queries"] == 0, (st, js, STATE["queries"]))
check("U20. подмена DNS: окно входа такой странице признак setup_available не отдаёт",
      "setup_available" not in NS["auth_status"](Req(headers=EVIL)))
check("U21. Host этого компьютера, но чужой, 'null' или битый Origin — отказ",
      ALLOWED(Req()) is True and
      all(ALLOWED(Req(headers={"Host": "127.0.0.1:8000", "Origin": o})) is False
          for o in ("http://evil.example:8000", "null", "http://127.0.0.1:8000@evil.example", "garbage")))
check("U22. похожие на свои, но чужие имена в Host — отказ",
      ALLOWED(Req()) is True and
      all(ALLOWED(Req(headers={"Host": h})) is False
          for h in ("localhost.evil.example:8000", "127.0.0.1.nip.io:8000", "farm-pc.evil.example", "evil.example")))
_good = [
    {},                                                                   # трей и утилиты без Host
    {"Host": "127.0.0.1:8000"},
    {"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"},
    {"Host": "localhost:8000", "Origin": "http://localhost:8000"},
    {"Host": "[::1]:8000", "Origin": "http://[::1]:8000"},
    {"Host": "FARM-PC:8000", "Origin": "http://farm-pc:8000"},
    {"Host": "farm-pc.local:8000"},
]
check("U23. законные адреса этого компьютера (IP, localhost, [::1], имя компьютера) пропускаются",
      all(ALLOWED(Req(headers=h)) is True for h in _good),
      [h for h in _good if ALLOWED(Req(headers=h)) is not True])
STATE["fault"] = True
check("U11. сбой чтения базы (UNKNOWN) — отказ, а не разрешение", ALLOWED(Req()) is False)
st, js = setup("faultadm")
STATE["fault"] = False
check("U12. при сбое базы создание не проходит (already_enabled)", st == 400 and js.get("error") == "already_enabled")
st, js = setup("ivan")
check("U13. занятый логин: понятный отказ username_taken, пользователей не прибавилось",
      st == 400 and js.get("error") == "username_taken" and len(users()) == 2, (st, js))
AUDIT.clear()
st, js = setup("boss")
new = [u for u in users() if u["username"] == "boss"]
check("U14. заперто, с этого компьютера: администратор создан, защита осталась включённой",
      st == 200 and js.get("ok") and js.get("user", {}).get("role") == "admin" and NS["_SECURITY_ENABLED"] is True
      and new and new[0]["role"] == "admin" and new[0]["is_active"] == 1 and new[0]["created_by"] == "local_setup",
      (st, js, new))
check("U15. событие записано в журнал аудита и в журнал программы",
      AUDIT and AUDIT[-1][:2] == ("boss", "security.local_admin_setup") and AUDIT[-1][3] == "ok"
      and any("R-128" in l for l in LOG.lines), (AUDIT, LOG.lines[-2:]))
st, js = setup("boss2")
check("U16. повторное создание (администратор уже есть) — прежний отказ", st == 400 and js.get("error") == "already_enabled")
check("U17. после создания признак setup_available больше не отдаётся",
      "setup_available" not in NS["auth_status"](Req(client="127.0.0.1")))

# ── гонка: проверка прошла, а администратор появился до записи ──
DB.execute("UPDATE users SET is_active=0 WHERE role='admin'")
DB.commit()
_real = NS["_locked_out_setup_allowed"]
NS["_locked_out_setup_allowed"] = lambda req: True    # «проверка уже прошла»
DB.execute("UPDATE users SET is_active=1 WHERE username='boss'")
DB.commit()
_n = len(users())
st, js = setup("racer")
NS["_locked_out_setup_allowed"] = _real
check("U18. гонка двух запросов: запись под замком проверяет администратора ещё раз, второго не создаёт",
      st == 400 and js.get("error") == "already_enabled" and len(users()) == _n, (st, js))


# ════════════════════════════════════════════════════════════════════════════
section("настоящий процесс программы (изолированный режим)")
PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def listening(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=0x08000000).stdout
    return any(len(l.split()) >= 5 and l.split()[3] == "LISTENING" and l.split()[1] == "127.0.0.1:%d" % port for l in out.splitlines())


def wait(fn, t):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return None


def call(port, method, path, body=None, cookie="", headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else (b"" if method != "GET" else None)
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)          # urllib не подставляет свой Host, если он задан явно
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", "fm_session=" + cookie)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}"), r.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}"), e.headers.get_all("Set-Cookie") or []
        except Exception:
            return e.code, {}, []
    except Exception as e:
        return 0, {"exc": str(e)}, []


def cookie_of(setcookies):
    for c in setcookies:
        m = re.match(r"fm_session=([^;]*)", c)
        if m:
            return m.group(1)
    return ""


root = tempfile.mkdtemp(prefix="fm_e2e_lock_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD)), "временная папка внутри рабочей!"
port = free_port()
token = "LOCK_E2E_" + secrets.token_hex(8)
with open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
    json.dump({"token": token, "sentinel": "LOCK_E2E_0929"}, f)
cfgp = os.path.join(root, "config.json")
with open(cfgp, "w", encoding="utf-8") as f:
    json.dump({"server_port": port}, f)
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_LOCK_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "1",
            ISO.ENV_NO_MODULES: "1"})
proc = None


def start():
    p = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                         cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=(0x00000008 | 0x00000200))
    ok = wait(lambda: call(port, "GET", "/version")[1].get("version") == APP_VERSION if listening(port) else None, 150)
    return p, bool(ok)


def stop():
    with open(os.path.join(root, "stop.request"), "w", encoding="utf-8") as f:
        f.write(token)
    gone = wait(lambda: not listening(port), 60)
    if not gone and proc is not None and proc.poll() is None:
        proc.terminate()   # только СВОЙ процесс; рабочую программу не трогаем
        gone = wait(lambda: not listening(port), 20)
    if proc is not None:
        try:
            proc.wait(timeout=20)
        except Exception:
            pass
    try:
        os.unlink(os.path.join(root, "stop.request"))
    except Exception:
        pass
    return bool(gone)


def settings_db():
    """База с app_settings и users во ВРЕМЕННОЙ папке (у рабочей программы — своя)."""
    for p in sorted(glob.glob(os.path.join(root, "*.db"))):
        c = sqlite3.connect(p)
        try:
            names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            c.close()
        if {"app_settings", "users"} <= names:
            return p
    return None


def lock_farm():
    """Запертое состояние, как после восстановления копии старой версией: защита включена,
    пользователей нет."""
    p = settings_db()
    assert p and os.path.normcase(p).startswith(os.path.normcase(root)), p
    c = sqlite3.connect(p)
    try:
        c.execute("DELETE FROM users")
        c.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES ('security_enabled', '1')")
        c.commit()
    finally:
        c.close()
    return p


print("изолированный экземпляр: порт %d, папка %s" % (port, root), flush=True)
try:
    proc, ok = start()
    check("E1. изолированный экземпляр поднялся (своя папка, порт, замок)", ok)
    check("E2. штатная остановка перед подготовкой запертого состояния", stop())
    dbp = lock_farm()
    proc, ok = start()
    check("E3. процесс поднят в запертом состоянии", ok)
    st, js, _ = call(port, "GET", "/api/auth/status")
    check("E4. статус с 127.0.0.1: вход включён, не вошли, setup_available=true",
          js.get("enabled") is True and js.get("authenticated") is False and js.get("setup_available") is True, js)
    st, js, _ = call(port, "GET", "/api/printers")
    check("E5. без входа данные фермы закрыты (защита действительно включена)", st == 401, (st, js))
    st, js, _ = call(port, "POST", "/api/auth/setup", {"username": "ab", "password": "x"})
    check("E6. слабые данные — отказ weak, администратор не создан", st == 400 and js.get("error") == "weak", (st, js))
    _evil = {"Host": "evil.example:%d" % port, "Origin": "http://evil.example:%d" % port}
    st, js, _ = call(port, "GET", "/api/auth/status", headers=_evil)
    check("E6a. подмена DNS: статус для страницы evil.example не отдаёт setup_available",
          js.get("enabled") is True and js.get("authenticated") is False and "setup_available" not in js, (st, js))
    st, js, sc = call(port, "POST", "/api/auth/setup", {"username": "evil", "password": "Evil-pass-1"}, headers=_evil)
    _c = sqlite3.connect(dbp)
    try:
        _rows = _c.execute("SELECT username FROM users").fetchall()
    finally:
        _c.close()
    check("E6b. подмена DNS: POST /api/auth/setup с 127.0.0.1 и Host/Origin evil.example — отказ, "
          "сессия не выдана, пользователей нет",
          st == 400 and js.get("error") == "already_enabled" and not cookie_of(sc) and _rows == [], (st, js, _rows))
    st, js, sc = call(port, "POST", "/api/auth/setup", {"username": "rescue", "password": "Rescue-pass-1"})
    adm = cookie_of(sc)
    check("E7. ГЛАВНОЕ: с этого компьютера администратор создан, выдана сессия",
          st == 200 and js.get("ok") is True and (js.get("user") or {}).get("role") == "admin" and adm, (st, js))
    st, js, _ = call(port, "GET", "/api/auth/status", cookie=adm)
    check("E8. новый администратор вошёл; защита осталась включённой",
          js.get("enabled") is True and js.get("authenticated") is True and (js.get("user") or {}).get("role") == "admin", js)
    st, js, _ = call(port, "POST", "/api/auth/setup", {"username": "rescue2", "password": "Rescue-pass-2"})
    check("E9. повторное создание — прежний отказ already_enabled", st == 400 and js.get("error") == "already_enabled", (st, js))
    st, js, _ = call(port, "GET", "/api/auth/status")
    check("E10. после создания признак setup_available больше не отдаётся",
          js.get("enabled") is True and "setup_available" not in js, js)
    st, js, _ = call(port, "GET", "/api/auth/audit?limit=50", cookie=adm)
    acts = [(e.get("username"), e.get("action"), e.get("result"), e.get("ip")) for e in (js.get("entries") or [])]
    check("E11. в журнале аудита событие «администратор создан на этом компьютере» с адресом 127.0.0.1",
          ("rescue", "security.local_admin_setup", "ok", "127.0.0.1") in acts, acts[:5])
    st, js, sc = call(port, "POST", "/api/auth/login", {"username": "rescue", "password": "Rescue-pass-1"})
    check("E12. новый администратор входит паролем", st == 200 and js.get("ok") is True and cookie_of(sc), (st, js))
    c = sqlite3.connect(dbp)
    try:
        rows = c.execute("SELECT username, role, is_active FROM users").fetchall()
        sec = c.execute("SELECT value FROM app_settings WHERE key='security_enabled'").fetchone()
    finally:
        c.close()
    check("E13. в базе ровно один администратор, флаг защиты = 1",
          rows == [("rescue", "admin", 1)] and sec and sec[0] == "1", (rows, sec))
finally:
    stop()
    shutil.rmtree(root, ignore_errors=True)

print("\nИТОГО: проверок %d, провалено %d" % (len(NAMES), len(FAILED)))
sys.exit(1 if FAILED else 0)
