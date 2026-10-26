# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  26.09.2026 — «Запомнить это устройство»: постоянное разрешение телефона.
#
#  ЗАЧЕМ. Владелец: телефон один раз входит логином и паролем, хранит зашифрованный токен
#  устройства (пароль не хранится) и дальше входит сам — бессрочно, пока разрешение не
#  отозвано выходом или через FM. До этой правки вход с телефона жил 8 часов простоя и
#  пропадал с перезапуском программы (таблица сессий только в памяти).
#
#  ЧТО ПРОВЕРЯЕТСЯ. Реальные функции server.py исполняются изолированно (разбор AST): выдача
#  токена устройства, проверка без предела простоя, переживание «перезапуска» (хранилище
#  читается заново из app_settings), все пути отзыва (выход, «Отозвать» в FM, смена пароля и
#  роли, отключение и удаление пользователя, выключение защиты, повторный вход), сбой записи
#  и чтения хранилища, обычная сессия осталась прежней (8 часов, в памяти), список устройств
#  для интерфейса, WebSocket, совместимость токена с приложением Android 0.13.0.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: server.py не импортируется, рабочие БД/DATA_DIR/config не
#  используются (sqlite в памяти), сокетов нет, токены и пароли в вывод не печатаются.
#
#  Запуск:  python tools/test_remembered_devices.py   (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import json
import os
import re
import sqlite3
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

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


SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
TREE = ast.parse(SRC)

from app import auth_rate_limit as RL               # noqa: E402
from app import session_cookie_policy as CP         # noqa: E402
from app import websocket_access_control as WSA     # noqa: E402


def fn_src(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    raise AssertionError("в server.py нет функции %s" % name)


def const_src(name):
    for n in TREE.body:
        if isinstance(n, ast.Assign) and any(
                (isinstance(t, ast.Name) and t.id == name)
                or (isinstance(t, ast.Tuple) and any(isinstance(e, ast.Name) and e.id == name for e in t.elts))
                for t in n.targets):
            return ast.unparse(n)
    raise AssertionError("в server.py нет константы %s" % name)


# ── изолированная база: users + app_settings, как в init_db ────────────────────
DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT DEFAULT '')")
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, pwd_hash TEXT NOT NULL DEFAULT '', "
           "role TEXT DEFAULT 'operator', is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
           "created_by TEXT DEFAULT '')")
DB.commit()

FAULT = {"write": False, "read": False, "users": False}
HOOK = {"user_read": None}   # 16.10.2026 (R-150): действие «между» чтениями проверки устройства


class _DB:
    """Обёртка соединения: позволяет изобразить сбой записи или чтения хранилища устройств."""
    def execute(self, sql, *a, **k):
        low = sql.lower()
        if FAULT["write"] and "insert into app_settings" in low:
            raise sqlite3.OperationalError("disk I/O error (изображён тестом)")
        if FAULT["read"] and "from app_settings" in low:
            raise sqlite3.OperationalError("database is locked (изображено тестом)")
        if FAULT["users"] and "update users set pwd_hash" in low:
            raise sqlite3.OperationalError("database is locked (изображено тестом)")
        if HOOK["user_read"] and "select username, role, is_active, pwd_hash from users" in low:
            _h, HOOK["user_read"] = HOOK["user_read"], None
            _h()
        return DB.execute(sql, *a, **k)

    def commit(self):
        return DB.commit()

    def rollback(self):
        return DB.rollback()

    @property
    def in_transaction(self):
        return DB.in_transaction


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


AUDIT = []
LOG = _Log()


class FakeResponse:
    def __init__(self): self.set, self.deleted = [], []
    def set_cookie(self, key, value, **kw): self.set.append((key, value, kw))
    def delete_cookie(self, key, **kw): self.deleted.append((key, kw))


class Headers(dict):
    def get(self, k, d=None):
        return dict.get(self, str(k).lower(), d)


class Req:
    def __init__(self, data=None, cookies=None, ua="", client="192.168.1.50", scheme="http"):
        self._data = data or {}
        self.cookies = cookies or {}
        self.headers = Headers({"user-agent": ua} if ua else {})
        self.client = type("C", (), {"host": client})()
        self.url = type("U", (), {"scheme": scheme})()


class _LanPolicy:
    class BindScope:
        NETWORK, LOOPBACK = "network", "loopback"
    @staticmethod
    def auth_disable_blocked(*a):
        return False


async def _json_body(req):
    return req._data


def _set_security_enabled(on):
    NS["_SECURITY_ENABLED"] = bool(on)


NS = {
    "_auth_rl": RL, "_cookie_policy": CP, "_ws_access": WSA, "_lan_policy": _LanPolicy,
    "secrets": __import__("secrets"), "hashlib": __import__("hashlib"), "time": time, "os": os,
    "json": json, "re": re, "threading": threading, "uuid": __import__("uuid"),
    "JSONResponse": _Resp, "log": LOG, "lock_p": _Lock(), "conn_p": _DB(),
    "_exc_brief": lambda: "ошибка (кратко)",
    "_audit": lambda *a, **k: AUDIT.append(a[:3]),
    "_json_body": _json_body, "_json_body_small": _json_body, "_read_config": lambda: {}, "_LAN_ACCESS_APPLIED": False,
    "_set_security_enabled": _set_security_enabled,
    "app": type("A", (), {"post": lambda *a, **k: (lambda f: f), "get": lambda *a, **k: (lambda f: f),
                          "patch": lambda *a, **k: (lambda f: f), "delete": lambda *a, **k: (lambda f: f)})(),
    "Request": object, "Response": object,
}
for _c in ("AUTH_ROLES", "_SESSION_COOKIE", "_SESSION_IDLE", "_sessions", "_sessions_lock", "_ROLE_PERMS",
           "_DEVICE_TOKEN_PREFIX", "_DEVICE_SETTINGS_KEY", "_DEVICE_COOKIE_MAX_AGE", "_DEVICE_MAX_PER_USER",
           "_DEVICE_SEEN_PERSIST_S", "_DEVICE_NAME_MAX", "_REMEMBER_DEVICE_PROTOCOL", "_devices",
           "_devices_dirty", "_devices_lock", "_devices_persist_lock", "_DUMMY_PWD_HASH", "_AUTH_LIMITER",
           "_DEVICE_USER_CHECK_S", "_DEVICE_RETRY_S", "_devices_retry_timer", "_DEVICE_OK", "_PWD_ITERS"):
    exec(compile(const_src(_c), "<server>", "exec"), NS)
for _n in ("_hash_pwd", "_verify_pwd", "_pwd_iters", "_pwd_needs_rehash", "_pwd_harden_runtime", "_pwd_rehash",
           "_devices_payload_locked", "_peer_of", "_dummy_pwd_hash", "_prune_sessions_if_needed",
           "_new_session", "_revoke_incoming_session", "_rate_limited_response", "_session_check",
           "_session_user", "_ws_auth_state", "_require_admin", "_active_admin_count", "_drop_user_sessions",
           "_device_token_hash", "_is_device_token", "_devices_ensure_loaded", "_devices_persist",
           "_device_name_for", "_device_register", "_device_lookup", "_device_remove", "_device_revoke_token",
           "_device_revoke_user", "_device_session_check", "_device_ws_view", "_devices_public",
           "_device_pw_mark", "_devices_schedule_retry", "_device_check", "_uid", "auth_setup",
           "auth_status", "auth_login", "auth_logout", "auth_disable", "auth_users_list", "auth_users_update",
           "auth_users_delete"):
    exec(compile(fn_src(_n), "<server>", "exec"), NS)

NS["_SECURITY_ENABLED"] = True
PWD_A, PWD_B = "Phone-pass-1", "Admin-pass-2"
DB.execute("INSERT INTO users (id, username, pwd_hash, role, is_active) VALUES (?,?,?,?,1)",
           ("usr_op", "ivan", NS["_hash_pwd"](PWD_A), "operator"))
DB.execute("INSERT INTO users (id, username, pwd_hash, role, is_active) VALUES (?,?,?,?,1)",
           ("usr_adm", "boss", NS["_hash_pwd"](PWD_B), "admin"))
DB.commit()

UA_PHONE = "Dalvik/2.1.0 (Linux; U; Android 14; SM-S918B Build/UP1A.231005.007)"


def login(user, pwd, remember=None, name=None, cookies=None, ua=UA_PHONE):
    body = {"username": user, "password": pwd}
    if remember is not None:
        body["remember_device"] = remember
    if name is not None:
        body["device_name"] = name
    NS["_AUTH_LIMITER"]._state.clear() if hasattr(NS["_AUTH_LIMITER"], "_state") else None
    resp = FakeResponse()
    r = asyncio.run(NS["auth_login"](Req(body, cookies=cookies, ua=ua), resp))
    tok = resp.set[-1][1] if resp.set else ""
    return r, resp, tok


def restart():
    """«Перезапуск программы»: память процесса пуста, база та же."""
    NS["_devices"] = None
    NS["_sessions"].clear()
    NS["_devices_dirty"][0] = False


def expire_user_cache():
    """Учётная запись перечитывается не чаще раза в _DEVICE_USER_CHECK_S — «прошло 5 секунд»."""
    for _r in (NS["_devices"] or {}).values():
        _r["_uchk"] = 0


def stored():
    row = DB.execute("SELECT value FROM app_settings WHERE key=?", (NS["_DEVICE_SETTINGS_KEY"],)).fetchone()
    return json.loads(row["value"]) if row and row["value"] else None


def status(tok):
    return NS["auth_status"](Req(cookies={"fm_session": tok} if tok else {}))


def admin_cookie():
    r, _resp, tok = login("boss", PWD_B)
    assert isinstance(r, dict) and r.get("ok"), r
    return {"fm_session": tok}


def patch_user(uid, body, cookies):
    return asyncio.run(NS["auth_users_update"](uid, Req(body, cookies=cookies)))


print("=== 26.09.2026: «Запомнить это устройство» ===")

# ════════════════════════════════════════════════════════════════════════════
section("1. обычный вход не изменился")
r, resp, tok = login("ivan", PWD_A)
check("1. без remember_device — обычная сессия: ответ прежний, без поля device",
      isinstance(r, dict) and r.get("ok") is True and "device" not in r and "remember_device_error" not in r)
check("2. обычный токен без префикса устройства, cookie на 8 часов",
      tok and not tok.startswith("fmd_") and resp.set[-1][2].get("max_age") == 8 * 3600)
check("3. обычная сессия — в памяти, хранилище устройств не создано", tok in NS["_sessions"] and stored() is None)
_s = NS["_sessions"][tok]
_s["last_seen"] -= 9 * 3600
check("4. обычная сессия по-прежнему истекает через 8 часов простоя", NS["_session_check"](tok) is None)
r, resp, tok = login("ivan", PWD_A)
restart()
check("5. обычная сессия по-прежнему пропадает с перезапуском", NS["_session_check"](tok) is None)
r, resp, tok = login("ivan", PWD_A, remember=False)
check("6. remember_device: false — тоже обычная сессия, без поля device",
      isinstance(r, dict) and r.get("ok") is True and not tok.startswith("fmd_") and "device" not in r)

# ════════════════════════════════════════════════════════════════════════════
section("2. выдача разрешения устройства")
restart()
r, resp, dtok = login("ivan", PWD_A, remember=True)
check("7. вход с remember_device: true — ok и device.persistent",
      isinstance(r, dict) and r.get("ok") is True and isinstance(r.get("device"), dict)
      and r["device"].get("persistent") is True and r["device"].get("id", "").startswith("dev_"))
check("8. токен устройства: префикс fmd_, алфавит и длина принимаются приложением Android 0.13.0",
      dtok.startswith("fmd_") and re.fullmatch(r"[A-Za-z0-9_-]{1,512}", dtok) is not None and len(dtok) >= 40)
_attrs = resp.set[-1][2]
check("9. cookie та же (fm_session), httponly, samesite lax, срок — годы, а не 8 часов",
      resp.set[-1][0] == "fm_session" and _attrs.get("httponly") is True and _attrs.get("samesite") == "lax"
      and _attrs.get("max_age", 0) >= 5 * 365 * 24 * 3600)
st = stored()
_raw = DB.execute("SELECT value FROM app_settings WHERE key=?", (NS["_DEVICE_SETTINGS_KEY"],)).fetchone()["value"]
check("10. разрешение записано в app_settings (схема базы не менялась)",
      isinstance(st, dict) and len(st.get("devices") or []) == 1)
check("11. в хранилище только отпечаток токена: самого токена и пароля там нет",
      dtok not in _raw and dtok[4:] not in _raw and PWD_A not in _raw
      and st["devices"][0]["h"] == __import__("hashlib").sha256(dtok.encode()).hexdigest())
check("12. имя устройства взято из User-Agent (модель телефона)", st["devices"][0]["name"] == "SM-S918B")
check("13. в журнал аудита записано запоминание устройства",
      any(a[1] == "device.remember" for a in AUDIT))
check("14. токен устройства не попал в журнал сервера", not any(dtok in l for l in LOG.lines))

# ════════════════════════════════════════════════════════════════════════════
section("3. разрешение бессрочное и переживает перезапуск")
u = NS["_session_check"](dtok)
check("15. токен устройства принимается: пользователь и роль из базы",
      u and u["username"] == "ivan" and u["role"] == "operator" and u.get("device_id"))
for _rec in NS["_devices"].values():
    _rec["seen"] -= 30 * 24 * 3600
check("16. месяц без входа — разрешение действует (предела простоя нет)", NS["_session_check"](dtok) is not None)
restart()
check("17. после «перезапуска» программы токен устройства по-прежнему принимается",
      (NS["_session_check"](dtok) or {}).get("username") == "ivan")
s1 = status(dtok)
check("18. /api/auth/status: authenticated, remember_device=1, device.persistent",
      s1.get("authenticated") is True and s1.get("remember_device") == 1
      and (s1.get("device") or {}).get("persistent") is True)
s0 = status("")
check("19. /api/auth/status без входа тоже сообщает remember_device=1 (приложение узнаёт поддержку до входа)",
      s0.get("authenticated") is False and s0.get("remember_device") == 1)
NS["_SECURITY_ENABLED"] = False
_soff = status("")
check("20. при выключенной защите status прежний и тоже с remember_device",
      _soff.get("enabled") is False and _soff.get("authenticated") is True and _soff.get("user") is None
      and _soff.get("remember_device") == 1)
NS["_SECURITY_ENABLED"] = True
check("20b. во всех трёх ответах status прежний список ролей",
      all(x.get("roles") == NS["AUTH_ROLES"] for x in (_soff, s0, s1)))
DB.execute("UPDATE users SET role='observer' WHERE id='usr_op'"); DB.commit()
check("21a. учётная запись не перечитывается чаще раза в 5 секунд (не держим базу на каждом запросе)",
      NS["_session_check"](dtok)["role"] == "operator")
expire_user_cache()
check("21. роль берётся текущая из базы, а не снимок входа", NS["_session_check"](dtok)["role"] == "observer")
DB.execute("UPDATE users SET role='operator' WHERE id='usr_op'"); DB.commit()

ws = NS["_ws_auth_state"](dtok)
check("22. WebSocket: токен устройства — действующая сессия, не истёкшая, пользователь включён",
      ws.session_present and ws.session_valid and not ws.session_expired and not ws.session_revoked
      and ws.user_enabled and ws.role == "operator")
check("23. WebSocket разрешает соединение", WSA.evaluate(ws, handshake=True).decision is WSA.WsDecision.ALLOW)

# ════════════════════════════════════════════════════════════════════════════
section("4. отзыв разрешения")
resp = FakeResponse()
NS["auth_logout"](Req(cookies={"fm_session": dtok}), resp)
check("24. выход с телефона снимает разрешение", NS["_session_check"](dtok) is None and not stored()["devices"])
restart()
check("25. после выхода и перезапуска разрешение не «воскресает»", NS["_session_check"](dtok) is None)
check("26. выход записан в аудит как отзыв устройства", any(a[1] == "device.revoke" for a in AUDIT))
wsr = NS["_ws_auth_state"](dtok)
check("27. WebSocket со снятым токеном — отозванная сессия", wsr.session_revoked)

r, _x, d1 = login("ivan", PWD_A, remember=True, name="Рабочий телефон")
check("28. имя устройства от приложения принимается", NS["_devices_public"]()[0]["name"] == "Рабочий телефон")
r2, _x, d2 = login("ivan", PWD_A, remember=True, cookies={"fm_session": d1})
check("29. повторный вход с того же телефона заменяет прежнее разрешение, а не копит их",
      NS["_session_check"](d1) is None and NS["_session_check"](d2) is not None and len(stored()["devices"]) == 1)

adm = admin_cookie()
lst = NS["auth_users_list"](Req(cookies=adm))
devs = lst.get("devices") or []
check("30. список пользователей для администратора содержит запомненные устройства",
      len(devs) == 1 and devs[0]["username"] == "ivan" and devs[0]["user_id"] == "usr_op")
check("31. в списке нет ни токена, ни его отпечатка", all("h" not in d and "token" not in d for d in devs)
      and d2 not in json.dumps(lst, ensure_ascii=False))
rr = patch_user("usr_adm", {"revoke_device": devs[0]["id"]}, adm)
check("32. «Отозвать» с чужим пользователем в адресе — 404, устройство живо",
      getattr(rr, "status_code", 200) == 404 and NS["_session_check"](d2) is not None)
rr = patch_user("usr_op", {"revoke_device": devs[0]["id"]}, adm)
check("33. «Отозвать» в FM снимает разрешение сразу и насовсем",
      isinstance(rr, dict) and rr.get("ok") is True and NS["_session_check"](d2) is None)
restart()
check("34. отзыв из FM переживает перезапуск", NS["_session_check"](d2) is None)
check("35. роль и пароль пользователя при отзыве не менялись",
      DB.execute("SELECT role FROM users WHERE id='usr_op'").fetchone()["role"] == "operator"
      and NS["_verify_pwd"](PWD_A, DB.execute("SELECT pwd_hash FROM users WHERE id='usr_op'").fetchone()["pwd_hash"]))
rr = patch_user("usr_op", {"revoke_device": "dev_nope"}, admin_cookie())
check("36. отзыв несуществующего устройства — 404", getattr(rr, "status_code", 200) == 404)
_opc = {"fm_session": login("ivan", PWD_A)[2]}
rr = patch_user("usr_op", {"revoke_device": "dev_x"}, _opc)
check("37. отзывать устройства может только администратор", getattr(rr, "status_code", 200) == 403)

_, _x, d3 = login("ivan", PWD_A, remember=True)
patch_user("usr_op", {"password": "New-pass-3"}, admin_cookie())
check("38. смена пароля пользователя снимает его разрешения устройств", NS["_session_check"](d3) is None)
_, _x, d4 = login("ivan", "New-pass-3", remember=True)
patch_user("usr_op", {"role": "observer"}, admin_cookie())
check("39. смена роли снимает разрешения устройств (как и обычные сессии)", NS["_session_check"](d4) is None)
patch_user("usr_op", {"role": "operator"}, admin_cookie())
_, _x, d5 = login("ivan", "New-pass-3", remember=True)
DB.execute("UPDATE users SET is_active=0 WHERE id='usr_op'"); DB.commit()
expire_user_cache()
check("40. отключённый пользователь не входит по токену, и его устройство снимается",
      NS["_session_check"](d5) is None and not [d for d in stored()["devices"] if d["uid"] == "usr_op"])
DB.execute("UPDATE users SET is_active=1 WHERE id='usr_op'"); DB.commit()
_, _x, d6 = login("ivan", "New-pass-3", remember=True)
_rd = asyncio.run(NS["auth_disable"](Req({"password": PWD_B}, cookies=admin_cookie()), FakeResponse()))
check("41. выключение защиты снимает все запомненные устройства",
      isinstance(_rd, dict) and _rd.get("ok") is True and NS["_SECURITY_ENABLED"] is False
      and NS["_session_check"](d6) is None and not stored()["devices"])
_set_security_enabled(True)

# ════════════════════════════════════════════════════════════════════════════
section("5. сбои хранилища")
restart()
FAULT["write"] = True
r, resp, t7 = login("ivan", "New-pass-3", remember=True)
FAULT["write"] = False
check("42. не удалось записать разрешение — выдаётся обычная сессия, и ответ об этом говорит",
      isinstance(r, dict) and r.get("ok") is True and r.get("device") is None
      and r.get("remember_device_error") == "store_failed" and not t7.startswith("fmd_")
      and resp.set[-1][2].get("max_age") == 8 * 3600)
check("43. несохранённое разрешение не осталось в памяти", not NS["_devices_public"]())

_, _x, d8 = login("ivan", "New-pass-3", remember=True)
restart()
FAULT["read"] = True
check("44. сбой чтения хранилища — вход по токену не принимается (отказ, а не разрешение)",
      NS["_session_check"](d8) is None)
_, _x, t9 = login("ivan", "New-pass-3", remember=True)
FAULT["read"] = False
check("45. при сбое чтения хранилище не перезаписано пустым: прежнее разрешение цело",
      len(stored()["devices"]) == 1 and NS["_session_check"](d8) is not None)

restart()
DB.execute("UPDATE app_settings SET value='{испорчено' WHERE key=?", (NS["_DEVICE_SETTINGS_KEY"],)); DB.commit()
check("46. испорченное хранилище не роняет программу: вход по токену просто не принимается",
      NS["_session_check"](d8) is None)
_, _x, d10 = login("ivan", "New-pass-3", remember=True)
check("47. после испорченного хранилища новое разрешение записывается и работает",
      NS["_session_check"](d10) is not None and len(stored()["devices"]) == 1)

# ── запись на диск не чаще раза в 10 минут ──
restart()
_before = stored()["devices"][0]["seen"]
NS["_session_check"](d10)
check("48. каждый запрос с телефона не пишет в базу (отметка времени — не чаще раза в 10 минут)",
      stored()["devices"][0]["seen"] == _before)
for _rec in NS["_devices"].values():
    _rec["_pseen"] -= 700
NS["_session_check"](d10)
check("49. через 10 минут отметка «был в сети» доходит до базы", stored()["devices"][0]["seen"] >= _before)

# ── предел устройств на пользователя ──
restart()
toks = [login("ivan", "New-pass-3", remember=True, name="Телефон %d" % i)[2] for i in range(22)]
mine = [d for d in NS["_devices_public"]() if d["user_id"] == "usr_op"]
check("50. не больше 20 устройств на пользователя: вытесняется давно не заходившее",
      len(mine) == 20 and NS["_session_check"](toks[0]) is None and NS["_session_check"](toks[-1]) is not None)

# ── удаление пользователя ──
_, _x, d11 = login("ivan", "New-pass-3", remember=True)
DB.execute("INSERT INTO users (id, username, pwd_hash, role, is_active) VALUES (?,?,?,?,1)",
           ("usr_tmp", "temp", NS["_hash_pwd"]("Temp-pass-9"), "operator")); DB.commit()
_, _x, d12 = login("temp", "Temp-pass-9", remember=True)
NS["auth_users_delete"]("usr_tmp", Req(cookies=admin_cookie()))
check("51. удаление пользователя снимает его устройства, чужие не трогает",
      NS["_session_check"](d12) is None and NS["_session_check"](d11) is not None)

# ════════════════════════════════════════════════════════════════════════════
section("5b. защита от ошибок, найденных проверкой 26.09.2026")
restart()
_, _x, p1 = login("ivan", "New-pass-3", remember=True)
DB.execute("UPDATE users SET pwd_hash=? WHERE id='usr_op'", (NS["_hash_pwd"]("Other-pass-7"),)); DB.commit()
expire_user_cache()
check("R1. разрешение привязано к паролю: сменили пароль в базе мимо программы — телефон не входит",
      NS["_session_check"](p1) is None
      and not [d for d in stored()["devices"] if d["h"] == NS["_device_token_hash"](p1)])
check("R1b. в хранилище лежит отпечаток хеша пароля, а не сам хеш и не пароль",
      all(len(d.get("pw", "")) == 32 for d in stored()["devices"])
      and "Other-pass-7" not in json.dumps(stored(), ensure_ascii=False))

_, _x, p2 = login("ivan", "Other-pass-7", remember=True)
_dev_id = next(d["id"] for d in NS["_devices_public"](current_tok=p2) if d["current"])
NS["_DEVICE_RETRY_S"] = 0.3
_pending = NS["_devices_retry_timer"][0]
if _pending is not None:
    _pending.cancel()   # повтор с прошлых шагов стоит на 30 с — для проверки ставим свой, короткий
NS["_devices_retry_timer"][0] = None
FAULT["write"] = True
rr = patch_user("usr_op", {"revoke_device": _dev_id}, admin_cookie())
check("R2. отзыв при сбое записи: доступ закрыт сразу, ответ честно говорит, что на диск не легло",
      isinstance(rr, dict) and rr.get("ok") is True and rr.get("persisted") is False
      and NS["_session_check"](p2) is None)
FAULT["write"] = False
time.sleep(1.2)
check("R3. запись отзыва повторяется в фоне сама, без запросов телефонов",
      NS["_devices_dirty"][0] is False and not [d for d in stored()["devices"] if d["id"] == _dev_id])
restart()
check("R4. после повтора и перезапуска отозванный телефон не входит", NS["_session_check"](p2) is None)
NS["_DEVICE_RETRY_S"] = 30

_, _x, p3 = login("ivan", "Other-pass-7", remember=True)
NS["_SECURITY_ENABLED"] = False
check("R5. защита выключена (например, восстановлением копии) — токен устройства не принимается",
      NS["_session_check"](p3) is None)
r5, _resp5, t5 = login("ivan", "Other-pass-7", remember=True)
check("R6. при выключенной защите устройство не запоминается", not t5.startswith("fmd_") and not r5.get("device"))
_setup = asyncio.run(NS["auth_setup"](Req({"username": "boss2", "password": "Setup-pass-8"}), FakeResponse()))
check("R7. повторное включение защиты снимает все прежние разрешения устройств",
      isinstance(_setup, dict) and _setup.get("ok") is True and NS["_SECURITY_ENABLED"] is True
      and NS["_session_check"](p3) is None and not stored()["devices"])

_, _x, p4 = login("ivan", "Other-pass-7", remember=True)
restart()
FAULT["read"] = True
_st = NS["auth_status"](Req(cookies={"fm_session": p4}))
FAULT["read"] = False
check("R8. временный сбой базы — /api/auth/status отвечает 503, а не «не вошёл» (телефон не стирает вход)",
      getattr(_st, "status_code", 200) == 503)
check("R9. после сбоя разрешение цело", NS["_session_check"](p4) is not None)

_, _x, p5 = login("ivan", "Other-pass-7", remember=True)
_raw = json.loads(DB.execute("SELECT value FROM app_settings WHERE key=?", (NS["_DEVICE_SETTINGS_KEY"],)).fetchone()["value"])
_raw["devices"].append({"id": "dev_broken", "h": "x" * 64, "uid": "usr_op", "created": "n/a", "seen": "n/a"})
DB.execute("UPDATE app_settings SET value=? WHERE key=?", (json.dumps(_raw), NS["_DEVICE_SETTINGS_KEY"])); DB.commit()
restart()
check("R10. одна испорченная запись не сбрасывает остальные телефоны", NS["_session_check"](p5) is not None)

_orig_tu = NS["secrets"].token_urlsafe
_seq = iter(["fmd_" + "A" * 39, "fmd_" + "B" * 39])
NS["secrets"] = type("S", (), {"token_urlsafe": staticmethod(lambda n=32: next(_seq, None) or _orig_tu(n)),
                               "token_hex": staticmethod(__import__("secrets").token_hex),
                               "compare_digest": staticmethod(__import__("secrets").compare_digest)})
_tok = NS["_new_session"]("usr_op", "ivan", "operator")
NS["secrets"] = __import__("secrets")
check("R11. обычная сессия никогда не получает префикс устройства (иначе её приняли бы за устройство)",
      _tok and not _tok.startswith("fmd_") and NS["_session_check"](_tok) is not None)
_gw = fn_src("_all_app_settings") if False else ""
check("R12. откат копии настроек не трогает хранилище устройств (отозванные не возвращаются)",
      re.search(r"def _all_app_settings\(self\):.*?if r\[\"key\"\] == _DEVICE_SETTINGS_KEY:\s*continue", SRC, re.S) is not None)

# ════════════════════════════════════════════════════════════════════════════
section("5c. пересчёт хеша пароля без потери телефонов (R-150, 16.10.2026)")
import hashlib as _hl
PWD_O = "Olga-pass-4"
OLD_ITERS = 200000          # число итераций прежних версий программы
UA_PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def _db_hash(uid):
    return DB.execute("SELECT pwd_hash FROM users WHERE id=?", (uid,)).fetchone()["pwd_hash"]


def _iters_of(h):
    return int(h.split("$")[1])


def _old_user(uid, name):
    """Пользователь, заведённый прежней версией программы: хеш на 200 000 итераций,
    без запомненных устройств."""
    NS["_device_revoke_user"](uid)
    DB.execute("DELETE FROM users WHERE id=?", (uid,))
    DB.execute("INSERT INTO users (id, username, pwd_hash, role, is_active) VALUES (?,?,?,?,1)",
               (uid, name, NS["_hash_pwd"](PWD_O, iters=OLD_ITERS), "operator"))
    DB.commit()
    return _db_hash(uid)


def _old_phone(uid, name, h):
    """Телефон, запомненный прежней версией: отметка старого хеша."""
    tok, _rec = NS["_device_register"](uid, name, "Старый телефон", "192.168.1.60", h)
    assert tok, "устройство не выдано"
    return tok


def _alive(tok):
    expire_user_cache()
    return NS["_session_check"](tok) is not None


restart()
_h600 = NS["_hash_pwd"](PWD_O)
check("RH1. новый хеш пароля — 600 000 итераций PBKDF2-SHA256 (норма OWASP) в прежней форме строки",
      NS["_PWD_ITERS"] >= 600000 and _h600.startswith("pbkdf2_sha256$%d$" % NS["_PWD_ITERS"])
      and NS["_verify_pwd"](PWD_O, _h600) and not NS["_verify_pwd"]("Wrong-pass-0", _h600))

_h_old = _old_user("usr_olga", "olga")
_ph_old = _old_phone("usr_olga", "olga", _h_old)
r, _resp, _pc = login("olga", PWD_O, ua=UA_PC)
_h_new = _db_hash("usr_olga")
check("RH2. вход со старым хешем проходит, в базе хеш пересчитан на 600 000, пароль подходит",
      isinstance(r, dict) and r.get("ok") is True and _iters_of(_h_old) == OLD_ITERS
      and _iters_of(_h_new) == NS["_PWD_ITERS"] and NS["_verify_pwd"](PWD_O, _h_new))
_a1 = _alive(_ph_old)
restart()
_a2 = _alive(_ph_old)
check("RH3. телефон, запомненный до пересчёта, остаётся в системе — сразу и после перезапуска",
      _a1 and _a2 and [d["pw"] for d in stored()["devices"] if d["uid"] == "usr_olga"]
      == [NS["_device_pw_mark"](_h_new)])
r, _resp, _pc2 = login("olga", PWD_O, ua=UA_PC)
check("RH3b. следующий вход с новым хешем ничего не пересчитывает",
      r.get("ok") is True and _db_hash("usr_olga") == _h_new and _alive(_ph_old))
patch_user("usr_olga", {"password": "Olga-pass-5"}, admin_cookie())
check("RH4. смена пароля после пересчёта по-прежнему снимает телефон", not _alive(_ph_old))

_h_old = _old_user("usr_olga", "olga")
r, _resp, _ph5 = login("olga", PWD_O, remember=True)
_h5 = _db_hash("usr_olga")
_a1 = _alive(_ph5)
restart()
_a2 = _alive(_ph5)
check("RH5. вход с «Запомнить устройство» на старом хеше: хеш пересчитан, новый телефон принят "
      "сразу и после перезапуска (отметка нового хеша, а не старого)",
      r.get("ok") is True and _ph5.startswith("fmd_") and _iters_of(_h5) == NS["_PWD_ITERS"] and _a1 and _a2)

for _fk, _fname in (("write", "записи хранилища устройств"), ("users", "замены хеша в базе")):
    restart()
    _h_old = _old_user("usr_olga", "olga")
    _ph6 = _old_phone("usr_olga", "olga", _h_old)
    FAULT[_fk] = True
    try:
        r, _resp, _t6 = login("olga", PWD_O, ua=UA_PC)
    finally:
        FAULT[_fk] = False
    _marks = [d["pw"] for d in NS["_devices"].values() if d["uid"] == "usr_olga"]
    check("RH6-%s. сбой %s при пересчёте: вход проходит, хеш прежний, транзакция откачена, "
          "отметки в памяти возвращены, телефон в системе" % (_fk, _fname),
          isinstance(r, dict) and r.get("ok") is True and _db_hash("usr_olga") == _h_old
          and not DB.in_transaction and _marks == [NS["_device_pw_mark"](_h_old)] and _alive(_ph6)
          and NS["_devices_dirty"][0] is False)
    restart()
    check("RH6-%sb. после перезапуска телефон тоже в системе" % _fk, _alive(_ph6))


class _CountHash:
    """hashlib, который считает итерации pbkdf2 (время проверки пароля пропорционально им)."""
    def __init__(self):
        self.iters = []

    def pbkdf2_hmac(self, name, pwd, salt, n, *a):
        self.iters.append(int(n))
        return _hl.pbkdf2_hmac(name, pwd, salt, n, *a)

    def __getattr__(self, k):
        return getattr(_hl, k)


_h_old = _old_user("usr_olga", "olga")
NS["_dummy_pwd_hash"]()   # эталон для неизвестного имени считается один раз заранее
_ch = _CountHash()
NS["hashlib"] = _ch
try:
    r7, _resp, _ = login("olga", "Wrong-pass-0", ua=UA_PC)
    _it_old = sum(_ch.iters)
    _ch.iters.clear()
    r7u, _resp, _ = login("nobody_here", "Wrong-pass-0", ua=UA_PC)
    _it_unknown = sum(_ch.iters)
    _ch.iters.clear()
    r7n, _resp, _ = login("boss", "Wrong-pass-0", ua=UA_PC)
    _it_new = sum(_ch.iters)
finally:
    NS["hashlib"] = _hl
check("RH7. неверный пароль к старому хешу: отказ, хеш не пересчитан, а итераций pbkdf2 столько же, "
      "сколько у неизвестного имени и у нового хеша (время ответа не выдаёт давно не входивших)",
      getattr(r7, "status_code", 200) == 401 and getattr(r7u, "status_code", 200) == 401
      and getattr(r7n, "status_code", 200) == 401 and _db_hash("usr_olga") == _h_old
      and _it_old == _it_unknown == _it_new == NS["_PWD_ITERS"])

restart()
_h_old = _old_user("usr_olga", "olga")
_ph8 = _old_phone("usr_olga", "olga", _h_old)
_cur8 = [_h_old]


def _rehash_now():
    _cur8[0] = NS["_pwd_rehash"]("usr_olga", _cur8[0], PWD_O) or _cur8[0]


HOOK["user_read"] = _rehash_now   # пересчёт ровно между поиском записи и чтением учётной записи
_ok8 = _alive(_ph8)
HOOK["user_read"] = None
check("RH8. пересчёт хеша посреди проверки телефона не снимает телефон (сверяется живая отметка)",
      _cur8[0] != _h_old and _ok8 and _alive(_ph8))

_lock_saved, _iters_saved = NS["lock_p"], NS["_PWD_ITERS"]
NS["lock_p"] = threading.Lock()   # настоящий замок, как в server.py
restart()
_h_old = _old_user("usr_olga", "olga")
_ph9 = _old_phone("usr_olga", "olga", _h_old)
NS["_PWD_ITERS"] = 1000           # быстрый счёт: проверяется порядок замков, а не стойкость
_stop, _bad, _nchk = [False], [], [0]


def _checker():
    while not _stop[0]:
        for _r in list((NS["_devices"] or {}).values()):
            _r["_uchk"] = 0
        _st, _u = NS["_device_check"](_ph9)
        _nchk[0] += 1
        if _st != NS["_DEVICE_OK"]:
            _bad.append(_st)
            break


_n_ok = 0
try:
    _t = threading.Thread(target=_checker, daemon=True)
    _t.start()
    _cur = _h_old
    for _i in range(30):
        _nh = NS["_pwd_rehash"]("usr_olga", _cur, PWD_O)
        if _nh:
            _cur, _n_ok = _nh, _n_ok + 1
        time.sleep(0.003)
    _stop[0] = True
    _t.join(5)
finally:
    NS["lock_p"], NS["_PWD_ITERS"] = _lock_saved, _iters_saved
check("RH8b. 30 пересчётов хеша наперегонки с проверками телефона: все прошли, телефон не снят ни разу",
      _n_ok == 30 and not _bad and _nchk[0] >= 30 and _alive(_ph9))

# ════════════════════════════════════════════════════════════════════════════
section("6. интерфейс и договорённость с приложением")
HTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
JS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
DOC = open(os.path.join(REPO, "docs", "ANDROID_REMEMBER_DEVICE.md"), encoding="utf-8").read()
check("52. окно «Пользователи» показывает блок «Запомненные устройства» с кнопкой «Отозвать»",
      "Запомненные устройства" in HTML and "revokeDevice(d)" in HTML and "devicesList" in HTML)
check("53. кнопка шлёт PATCH пользователя с revoke_device и перечитывает список",
      "revoke_device: d.id" in JS and "devicesList.value = Array.isArray(j.devices)" in JS)
check("54. новые имена отданы шаблону", "devicesList, deviceBusy, revokeDevice" in JS)
check("55. описание для приложения Android лежит в docs и называет протокол 1",
      "remember_device" in DOC and "fmd_" in DOC and "Версия договорённости: **1**" in DOC)
check("56. ни одного нового маршрута: устройства живут в прежних /api/auth/users",
      not re.search(r'@app\.(get|post|patch|delete)\("/api/auth/devices', SRC))

print("\n" + "=" * 76)
if FAILED:
    print("FAIL: провалено %d из %d" % (len(FAILED), len(FAILED) + PASSED[0]))
    for f in FAILED:
        print("   - %s" % f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % PASSED[0])
sys.exit(0)
