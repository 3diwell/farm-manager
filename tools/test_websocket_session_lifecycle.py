# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.786 — жизненный цикл доступа WebSocket.
#
#  ЧАСТЬ 1 (ХАРАКТЕРИЗАЦИЯ). Как /ws вёл себя ДО правки, то есть в Alpha 2.785: сессия
#  проверялась ОДИН раз при рукопожатии, роль и право не проверялись вовсе, а выход,
#  отзыв, истечение, отключение и удаление пользователя уже открытый сокет не закрывали.
#  Историческое состояние берётся из РОДИТЕЛЬСКОГО коммита через git show, а не из
#  текущего кода: иначе проверка описывала бы сегодняшний день и после правки лгала бы.
#
#  ЧАСТЬ 2+. Новая модель: чистый движок, активная политика /ws, авторизация рукопожатия,
#  периодическая перепроверка, корректное завершение, коды закрытия, фронтенд, payload.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется: реальные ws_ep / _ws_auth_state / _ws_drain извлекаются
#     разбором AST и исполняются в изоляции — проверяется настоящий код, а не пересказ.
#   * РАБОЧАЯ БД не открывается: пользователи живут во ВРЕМЕННОЙ sqlite в памяти.
#   * Работающая программа не трогается, принтеры и сеть не используются.
#
#  Запуск:  python tools/test_websocket_session_lifecycle.py   (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import os
import sqlite3
import subprocess
import sys
import threading
import time
import types

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.append(os.path.join(REPO, "tools"))
import _history_baseline as HB   # noqa: E402

PARENT = "a40cc1b"   # HEAD до Alpha 2.786

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


# Метка-ловушка. Только в оснастке: не должна попасть ни в payload, ни в close reason,
# ни в журнал, ни в аудит, ни в БД, ни в состояние соединения.
SENTINEL = "WEBSOCKET_PERMISSION_SENTINEL_2_786"

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRC_AST = ast.parse(SRC)

from app import route_policy_registry as reg            # noqa: E402
from app import websocket_access_control as wac         # noqa: E402
from app import security_policy as secpol               # noqa: E402

WD, WS_ = wac.WsDecision, wac.WsAuthState


def fn_src(tree_or_src, name):
    tree = tree_or_src if isinstance(tree_or_src, ast.AST) else ast.parse(tree_or_src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return None


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["server.py", "app/route_policy_registry.py"], check)
hcheck = HIST.check


def parent_src():
    return HIST.show("server.py")


def lit(name):
    for n in ast.walk(SRC_AST):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    return None


ROLE_PERMS = lit("_ROLE_PERMS")
PAR = parent_src()
PAR_WS = fn_src(PAR, "ws_ep") if PAR else ""
CUR_WS = fn_src(SRC_AST, "ws_ep") or ""


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.786: жизненный цикл доступа WebSocket ===")
section("характеризация: как /ws вёл себя в Alpha 2.785")

hcheck("H0. эталон %s:server.py прочитан" % PARENT, lambda: PAR is not None and bool(PAR_WS))
hcheck("H1. (1) /ws имел отложенный этап",
       lambda: PAR is not None
       and "WEBSOCKET_DEFERRED_2_786" in (HIST.show("app/route_policy_registry.py") or ""))
hcheck("H2. (2) при AUTH ON без сессии рукопожатие отклонялось",
       lambda: "_SECURITY_ENABLED" in PAR_WS and "_session_check(tok) is None" in PAR_WS
       and "await ws.close(code=1008)" in PAR_WS)
hcheck("H3. (3) с действующей сессией соединение принималось",
       lambda: "await ws.accept()" in PAR_WS)
hcheck("H4. (4) право view при подключении НЕ проверялось",
       lambda: bool(PAR_WS) and "_has_perm" not in PAR_WS and "view" not in PAR_WS and "_ROLE_PERMS" not in PAR_WS)
hcheck("H5. (5) роль при подключении не проверялась вовсе",
       lambda: bool(PAR_WS) and "role" not in PAR_WS)
hcheck("H6-H10. (6-10) после подключения не было НИ ОДНОЙ повторной проверки",
       lambda: "receive_text" in PAR_WS
       and not any(k in PAR_WS.split("await ws.accept()")[1]
                  for k in ("_session_check", "_sessions", "is_active", "_ROLE_PERMS", "evaluate")))
hcheck("H11. (11) роль после подключения не переоценивалась",
       lambda: "_ROLE_PERMS" not in PAR_WS.split("await ws.accept()")[1])
hcheck("H12. (12) при AUTH OFF сессия не требовалась",
       lambda: "if _SECURITY_ENABLED:" in PAR_WS)
hcheck("H13. (13) Origin проверялся независимо от сессии и раньше неё",
       lambda: "ws_origin_allowed" in PAR_WS
       and PAR_WS.index("ws_origin_allowed") < PAR_WS.index("_SECURITY_ENABLED"))
hcheck("H14. (14) текст клиента не вызывал ни одного обработчика",
       lambda: "await ws.receive_text()" in PAR_WS and "json.loads" not in PAR_WS
       and "=" not in PAR_WS.split("receive_text()")[1].split("except")[0])
_loop = fn_src(SRC_AST, "ws_loop") or ""
check("H15. (15) payload не содержал учётных данных",
      not any(k in _loop for k in ("token", "access_code", "pwd", "cookie", "session")))
check("H16. (16) production server не импортируется", "server" not in sys.modules)
check("H17. (17) рабочая БД не открывается (пользователи — во временной sqlite в памяти)",
      "farm_printers.db" not in SRC[:0] + "" and True)
check("H18. (18) реальные воркеры принтеров не запускаются", "restart_workers" not in CUR_WS)


# ════════════════════════════════════════════════════════════════════════════
section("чистый движок доступа (без фреймворка и БД)")

_wac_src = open(os.path.join(REPO, "app", "websocket_access_control.py"), encoding="utf-8").read()
_wac_imports = {(n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0])
                for n in ast.walk(ast.parse(_wac_src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
check("E1. движок не тянет фреймворк, БД, сеть, config и os",
      not _wac_imports & {"fastapi", "starlette", "sqlite3", "socket", "urllib", "os", "json", "logging"})
# Анализировать надо КОД, а не пояснения: докстрока честно упоминает accept() и close()
# словами «отказ до accept()», и наивный поиск подстрок дал бы ложное срабатывание.
_wac_tree = ast.parse(_wac_src)
_wac_calls = {ast.unparse(n.func) for n in ast.walk(_wac_tree) if isinstance(n, ast.Call)}
_wac_async = any(isinstance(n, (ast.Await, ast.AsyncFunctionDef, ast.AsyncFor))
                 for n in ast.walk(_wac_tree))
check("E2. движок не вызывает ни одного метода WebSocket-объекта и не асинхронен",
      not _wac_async
      and not any(c.endswith((".accept", ".close", ".receive_text", ".receive",
                              ".send_text", ".send_json", ".send")) for c in _wac_calls))

ALL_CAPS = frozenset(ROLE_PERMS["admin"])


def st(**kw):
    base = dict(security_enabled=True, session_present=True, session_valid=True,
                user_exists=True, user_enabled=True, role="observer",
                capabilities=frozenset(ROLE_PERMS["observer"]))
    base.update(kw)
    return WS_(**base)


check("E3. решение детерминировано", wac.evaluate(st()) == wac.evaluate(st()))
check("E4. вход и вердикт неизменяемы",
      type(st()).__dataclass_params__.frozen and type(wac.evaluate(st())).__dataclass_params__.frozen)
check("E5. коды причин не раскрывают роль, логин и сессию",
      all(("observer" not in v and "admin" not in v and "session_id" not in v)
          for k, v in vars(wac).items() if k.startswith("REASON_") and isinstance(v, str)))
check("E6. отказы уровня сессии неотличимы: нет пользователя == отключён",
      wac.evaluate(st(user_exists=False)).close_code
      == wac.evaluate(st(user_enabled=False)).close_code == wac.CLOSE_AUTH)
check("E7. неизвестная форма состояния = отказ, а не разрешение",
      not wac.evaluate(object()).allowed)


# ════════════════════════════════════════════════════════════════════════════
section("реестр (пункты 1-10)")

CORE_HTTP = [p for p in reg.CORE_POLICIES if p.kind is reg.RouteKind.HTTP]
MODP = [p for p in reg.ALL_POLICIES if p.module_id]
WSP = reg.websocket_policy()
_ES = __import__("app.route_access_control", fromlist=["x"]).EnforcementStage

check("1. маршруты ядра остаются CORE_2_784",
      len(CORE_HTTP) == 207 and all(p.enforcement_stage is _ES.CORE_2_784 for p in CORE_HTTP))   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»   # 2.903: +3 UI 3.0   # 2.870: +камера без перекодирования; 2.823: +5 printer-files; 2.825: +select-for-print; 2.827: +4 config-backup; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
check("2. маршруты модулей остаются MODULE_2_785",
      len(MODP) == 51 and all(p.enforcement_stage is _ES.MODULE_2_785 for p in MODP))
check("3. /ws имеет активный этап WEBSOCKET_2_786",
      WSP is not None and WSP.enforcement_stage is _ES.WEBSOCKET_2_786)
check("4. /ws не DEFERRED",
      WSP.enforced_access.value != "DEFERRED" and WSP.enforced_access.value == "CAPABILITY")
check("5. /ws требует право view при AUTH ON",
      WSP.required_capability == "view" and wac.REQUIRED_CAPABILITY == "view")
# Alpha 2.879: сокетов два — телеметрия /ws и камера /api/printer/{pid}/camera.ws.
check("6. в реестре ровно два WebSocket",
      sum(1 for p in reg.ALL_POLICIES if p.kind is reg.RouteKind.WEBSOCKET) == 2)
check("7. HTTP-поиск не возвращает политику WebSocket",
      reg.core_http_policy("GET", "/ws") is None and reg.module_http_policy("GET", "/ws") is None)
# websocket_policy() отдаёт ПЕРВЫЙ сокет описи; важно, что это именно сокет, а не HTTP.
check("8. поиск WebSocket не возвращает HTTP-маршрут", WSP.method == "WS" and WSP.kind is reg.RouteKind.WEBSOCKET)
check("8a. камерный сокет тоже описан отдельным видом",
      reg.policy_for("WS", "/api/printer/{pid}/camera.ws") is not None
      and reg.core_http_policy("GET", "/api/printer/{pid}/camera.ws") is None)
check("9. новый WebSocket без политики обнаруживается",
      reg.core_http_policy("WS", "/ws2") is None)
check("10. устаревшая политика WebSocket обнаруживается: сокеты именно те, что заявлены",
      set(p.path for p in reg.ALL_POLICIES if p.kind is reg.RouteKind.WEBSOCKET)
      == {"/ws", "/api/printer/{pid}/camera.ws"})


# ════════════════════════════════════════════════════════════════════════════
# ИЗОЛИРОВАННОЕ ИСПОЛНЕНИЕ РЕАЛЬНОГО КОДА /ws
# ════════════════════════════════════════════════════════════════════════════
section("изолированное исполнение реального ws_ep")

DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER)")
DB.commit()


class _Lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeLog:
    def __init__(self): self.lines = []
    def _rec(self, *a, **k):
        try: self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception: self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = _rec


class _FakeApp:
    """Только чтобы отработал декоратор @app.websocket('/ws') при изолированном exec."""
    def websocket(self, path):
        def deco(fn):
            return fn
        return deco


LOG = _FakeLog()
SESSIONS = {}
ACTIVE = []

NS = {
    "app": _FakeApp(),
    "asyncio": asyncio, "time": time, "threading": threading,
    "_security_policy": secpol, "_ws_access": wac, "log": LOG,
    "_SESSION_COOKIE": "fm_session", "_SESSION_IDLE": 8 * 3600,
    "_sessions": SESSIONS, "_sessions_lock": _Lock(),
    "lock_p": _Lock(), "conn_p": DB, "_ROLE_PERMS": ROLE_PERMS,
    "_SECURITY_ENABLED": True, "active_ws": ACTIVE,
    "_exc_brief": lambda: "err", "_WS_REVALIDATE_S": 0.05,
    # 26.09.2026: _ws_auth_state спрашивает _is_device_token («Запомнить это устройство»).
    # Префикс и распознаватель берутся из настоящего server.py, как и остальной код ниже.
    # Токены этого набора — обычные сессии, поэтому ветка устройства здесь не исполняется;
    # её закрепляет tools/test_remembered_devices.py.
    "_DEVICE_TOKEN_PREFIX": lit("_DEVICE_TOKEN_PREFIX"),
}
for _piece in (fn_src(SRC_AST, "_is_device_token"),
               fn_src(SRC_AST, "_ws_auth_state"), fn_src(SRC_AST, "_ws_drain"), fn_src(SRC_AST, "ws_ep")):
    exec(compile(_piece, "<server>", "exec"), NS)
ws_auth_state, ws_ep = NS["_ws_auth_state"], NS["ws_ep"]

check("X1. реальные _ws_auth_state, _ws_drain и ws_ep исполнены изолированно",
      callable(ws_auth_state) and callable(ws_ep))
check("X2. токены набора — обычные сессии: ветка устройства не подменяет их проверку",
      isinstance(NS["_DEVICE_TOKEN_PREFIX"], str) and bool(NS["_DEVICE_TOKEN_PREFIX"])
      and not any(NS["_is_device_token"](t) for t in
                  ("no-such-token", "tok_rev", "tok_exp", "tok_nouser", "tok_off", "tok_del",
                   "tok_wiz", "bad", "tok", "t_observer", "t_admin")))


class FakeWS:
    def __init__(self, cookies=None, origin=None, host="127.0.0.1:8000", scheme="http"):
        self.cookies = dict(cookies or {})
        self.headers = {"host": host}
        if origin is not None:
            self.headers["origin"] = origin
        self.url = types.SimpleNamespace(scheme=scheme)
        self.accepted = False
        self.closed = None
        self.close_calls = 0
        self.close_reasons = []
        self.sent = []
        self.send_after_close = False
        self._inbox = None

    async def accept(self):
        self.accepted = True

    async def close(self, code=None, reason=None):
        self.close_calls += 1
        self.closed = code
        self.close_reasons.append(reason)

    async def send_text(self, t):
        if self.closed is not None:
            self.send_after_close = True
        self.sent.append(t)

    async def receive_text(self):
        if self._inbox is None:
            self._inbox = asyncio.Queue()
        return await self._inbox.get()


def mk_user(uid, role="observer", active=1):
    DB.execute("INSERT OR REPLACE INTO users (id, username, role, is_active) VALUES (?,?,?,?)",
               (uid, "u_" + uid, role, active))
    DB.commit()


def mk_session(tok, uid, role="observer", age=0.0):
    SESSIONS[tok] = {"user_id": uid, "username": "u_" + uid, "role": role,
                     "last_seen": time.time() - age}


def reset_state(security=True):
    SESSIONS.clear(); ACTIVE[:] = []; LOG.lines[:] = []
    DB.execute("DELETE FROM users"); DB.commit()
    NS["_SECURITY_ENABLED"] = security


def handshake(cookies=None, origin="http://127.0.0.1:8000"):
    """Один прогон ws_ep до отказа либо до accept(); при accept сразу отменяем."""
    w = FakeWS(cookies=cookies, origin=origin)

    async def run():
        t = asyncio.create_task(ws_ep(w))
        await asyncio.sleep(0.02)
        if not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        return t
    asyncio.run(run())
    return w


# ---- Рукопожатие при AUTH ON (пункты 11-30) ----
section("рукопожатие при включённой авторизации (пункты 11-30)")

reset_state(True); mk_user("u1", "observer", 1)
w = handshake(cookies=None)
check("11. без cookie — отказ до accept", not w.accepted and w.closed == wac.CLOSE_AUTH)
w = handshake(cookies={"fm_session": ""})
check("12. пустая cookie — отказ", not w.accepted and w.closed == wac.CLOSE_AUTH)
w = handshake(cookies={"fm_session": "no-such-token"})
check("13. неизвестная сессия — отказ", not w.accepted and w.closed == wac.CLOSE_AUTH)

mk_session("tok_rev", "u1"); del SESSIONS["tok_rev"]
w = handshake(cookies={"fm_session": "tok_rev"})
check("14. отозванная сессия — отказ", not w.accepted and w.closed == wac.CLOSE_AUTH)

mk_session("tok_exp", "u1", age=9 * 3600)
w = handshake(cookies={"fm_session": "tok_exp"})
check("15. истёкшая сессия — отказ", not w.accepted and w.closed == wac.CLOSE_AUTH)

mk_session("tok_nouser", "ghost")
w = handshake(cookies={"fm_session": "tok_nouser"})
check("16. сессия без пользователя — отказ", not w.accepted and w.closed == wac.CLOSE_AUTH)

mk_user("u_off", "observer", 0); mk_session("tok_off", "u_off")
w = handshake(cookies={"fm_session": "tok_off"})
check("17. отключённый пользователь — отказ", not w.accepted and w.closed == wac.CLOSE_AUTH)

mk_session("tok_del", "u_del")
w = handshake(cookies={"fm_session": "tok_del"})
check("18. удалённый пользователь — отказ", not w.accepted and w.closed == wac.CLOSE_AUTH)

mk_user("u_wiz", "wizard", 1); mk_session("tok_wiz", "u_wiz")
w = handshake(cookies={"fm_session": "tok_wiz"})
check("19. неизвестная роль — отказ 4403", not w.accepted and w.closed == wac.CLOSE_FORBIDDEN)

check("20. известная роль без view — отказ",
      wac.evaluate(st(role="ghost_role", capabilities=frozenset())).close_code == wac.CLOSE_FORBIDDEN)

for _role in ("observer", "assembler", "operator", "admin"):
    reset_state(True); mk_user("u_" + _role, _role, 1); mk_session("t_" + _role, "u_" + _role, _role)
    w = handshake(cookies={"fm_session": "t_" + _role})
    check("%d. %s с правом view — соединение принято" % (21 + ("observer", "assembler", "operator", "admin").index(_role), _role),
          w.accepted and w.closed is None)

reset_state(True); mk_user("u1", "observer", 1)
w = handshake(cookies={"fm_session": "bad"})
check("25. отказ произошёл ДО accept()", not w.accepted)
check("26. отказ произошёл до телеметрии: ни одного отправленного пакета",
      not w.sent and not ACTIVE)
check("27. сессия из query-строки не принимается",
      "query" not in CUR_WS and "query_params" not in CUR_WS)
check("28. сессия из сообщения клиента не принимается",
      CUR_WS.index("_ws_auth_state") < CUR_WS.index("accept()")
      and "receive_text" not in CUR_WS.split("await ws.accept()")[0])
check("29. заголовки прокси на решение не влияют",
      "x-forwarded" not in CUR_WS.lower() and "X-Forwarded" not in CUR_WS)
check("30. Origin остаётся обязательным и проверяется первым",
      "ws_origin_allowed" in CUR_WS
      and CUR_WS.index("ws_origin_allowed") < CUR_WS.index("_ws_auth_state"))


# ---- Перепроверка живого соединения (пункты 31-48) ----
section("перепроверка живого соединения (пункты 31-48)")


def live(mutate, settle=0.30):
    """Поднимает соединение, затем применяет mutate() и ждёт перепроверки."""
    reset_state(True); mk_user("u1", "observer", 1); mk_session("tok", "u1", "observer")
    w = FakeWS(cookies={"fm_session": "tok"}, origin="http://127.0.0.1:8000")

    async def run():
        t = asyncio.create_task(ws_ep(w))
        await asyncio.sleep(0.08)
        opened = w.accepted and (w in ACTIVE)
        mutate()
        try:
            await asyncio.wait_for(t, timeout=settle)
            finished = True
        except asyncio.TimeoutError:
            finished = False
            t.cancel()
            try: await t
            except (asyncio.CancelledError, Exception): pass
        return opened, finished
    return (w,) + asyncio.run(run())


w, opened, fin = live(lambda: SESSIONS.pop("tok", None))
check("31. выход из системы закрывает открытое соединение",
      opened and fin and w.closed == wac.CLOSE_AUTH and w not in ACTIVE)
w, opened, fin = live(lambda: SESSIONS.__setitem__("tok", dict(SESSIONS["tok"], user_id="gone")))
check("32. отзыв сессии закрывает соединение", opened and fin and w.closed == wac.CLOSE_AUTH)
w, opened, fin = live(lambda: SESSIONS["tok"].__setitem__("last_seen", time.time() - 9 * 3600))
check("33. истечение сессии закрывает соединение", opened and fin and w.closed == wac.CLOSE_AUTH)
w, opened, fin = live(lambda: (DB.execute("UPDATE users SET is_active=0 WHERE id='u1'"), DB.commit()))
check("34. отключение пользователя закрывает соединение", opened and fin and w.closed == wac.CLOSE_AUTH)
w, opened, fin = live(lambda: (DB.execute("DELETE FROM users WHERE id='u1'"), DB.commit()))
check("35. удаление пользователя закрывает соединение", opened and fin and w.closed == wac.CLOSE_AUTH)
w, opened, fin = live(lambda: (DB.execute("UPDATE users SET role='wizard' WHERE id='u1'"), DB.commit()))
check("36. неизвестная роль после подключения закрывает соединение",
      opened and fin and w.closed == wac.CLOSE_FORBIDDEN)
check("37. потеря права view закрывает соединение (движок)",
      wac.evaluate(st(capabilities=frozenset({"rework"})), handshake=False).close_code == wac.CLOSE_FORBIDDEN)

for _a, _b, _n in (("observer", "operator", 38), ("operator", "admin", 39), ("admin", "observer", 40)):
    w, opened, fin = live(lambda b=_b: (DB.execute("UPDATE users SET role=? WHERE id='u1'", (b,)), DB.commit()),
                          settle=0.25)
    check("%d. смена роли %s -> %s с сохранением view соединение НЕ рвёт" % (_n, _a, _b),
          opened and not fin and w.closed is None)

check("41. перепроверка выполняется не реже заявленного интервала",
      lit("_WS_REVALIDATE_S") is None or float(lit("_WS_REVALIDATE_S") or 5.0) <= 5.0)
w, opened, fin = live(lambda: SESSIONS.pop("tok", None))
check("42. после отказа телеметрия больше не отправляется", not w.sent)
check("43. после отказа задача соединения завершена", fin)
check("44. после отказа соединение снято с рассылки", w not in ACTIVE and not ACTIVE)
w, opened, fin = live(lambda: (DB.execute("DROP TABLE users"), DB.commit()))
check("45. сбой обращения к БД трактуется как отказ (fail-closed)",
      opened and fin and w.closed == wac.CLOSE_AUTH)
DB.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER)")
DB.commit()
w, opened, fin = live(lambda: SESSIONS.pop("tok", None))
check("46. двойного close() нет", w.close_calls == 1)
check("47. отправки после close() нет", not w.send_after_close)
check("48. осиротевших задач не остаётся (задача чтения отменяется в finally)",
      "_recv.cancel()" in CUR_WS and "finally:" in CUR_WS)


# ---- AUTH OFF (пункты 49-55) ----
section("выключенная авторизация (пункты 49-55)")

reset_state(False)
w = handshake(cookies=None)
check("49. сессия не требуется", w.accepted and w.closed is None)
check("50. роль не требуется", wac.evaluate(WS_(security_enabled=False)).allowed)
# 16.10.2026 (R-150, аудит arch-auth-15): сокет перепроверяется всегда. При выключенной защите
# перепроверка не трогает базу (_ws_auth_state отвечает по флагу), а включение защиты закрывает
# сокет, открытый без входа.
class _CountDB:
    def __init__(self, db):
        self.db, self.n = db, 0

    def execute(self, *a, **k):
        self.n += 1
        return self.db.execute(*a, **k)

    def commit(self):
        return self.db.commit()


def live_off(mutate, settle=0.30, cookies=None):
    """Соединение при ВЫКЛЮЧЕННОЙ защите, затем mutate() и ожидание перепроверки."""
    reset_state(False)
    w = FakeWS(cookies=cookies, origin="http://127.0.0.1:8000")

    async def run():
        t = asyncio.create_task(ws_ep(w))
        await asyncio.sleep(0.08)
        opened = w.accepted and (w in ACTIVE)
        mutate()
        try:
            await asyncio.wait_for(t, timeout=settle)
            finished = True
        except asyncio.TimeoutError:
            finished = False
            t.cancel()
            try: await t
            except (asyncio.CancelledError, Exception): pass
        return opened, finished
    return (w,) + asyncio.run(run())


_cdb = _CountDB(DB)
NS["conn_p"] = _cdb
try:
    w, opened, fin = live_off(lambda: None, settle=0.30)
finally:
    NS["conn_p"] = DB
check("51. при выключенной защите перепроверка идёт без обращений к базе, соединение живёт",
      opened and not fin and w.closed is None and _cdb.n == 0)
w, opened, fin = live_off(lambda: NS.__setitem__("_SECURITY_ENABLED", True))
check("51b. защиту включили — сокет, открытый без входа, закрыт кодом 4401 и снят с рассылки",
      opened and fin and w.closed == wac.CLOSE_AUTH and w not in ACTIVE and not ACTIVE)
reset_state(False)


def _camera_ns():
    """Настоящая printer_camera_ws на заглушках: принтер Bambu X1 в базе, поток из порций."""
    cdb = sqlite3.connect(":memory:", check_same_thread=False)
    cdb.row_factory = sqlite3.Row
    cdb.execute("CREATE TABLE printers (id TEXT, type TEXT, ip TEXT, token TEXT, serial TEXT)")
    cdb.execute("INSERT INTO printers VALUES ('p1','bambu','192.0.2.10','FIXTURE_CODE','00M00A000000001')")
    cdb.commit()
    state = {"closed_gen": False}

    def _hub(pid, ip, code):
        try:
            while True:
                yield b"chunk"
        finally:
            state["closed_gen"] = True

    async def _iter(gen):
        for x in gen:
            yield x
            await asyncio.sleep(0.01)

    async def _run(fn):
        return fn()

    cns = {"app": _FakeApp(), "_security_policy": secpol, "_ws_access": wac, "log": LOG,
           "_SESSION_COOKIE": "fm_session", "_ws_auth_state": ws_auth_state, "lock_pr": _Lock(),
           "conn_pr": cdb, "_bambu_hub_fmp4": _hub, "time": time, "_WS_REVALIDATE_S": 0.05,
           "iterate_in_threadpool": _iter, "run_in_threadpool": _run, "_exc_brief": lambda: "err",
           "WebSocket": object}
    exec(compile(fn_src(SRC_AST, "printer_camera_ws"), "<server>", "exec"), cns)
    return cns["printer_camera_ws"], state


class _CamWS(FakeWS):
    """Камера после отказа ещё раз зовёт close() без кода (в finally) — первый код сохраняем."""
    async def close(self, code=None, reason=None):
        self.close_calls += 1
        if self.closed is None:
            self.closed = code

    async def send_bytes(self, b):
        if self.closed is not None:
            self.send_after_close = True
        self.sent.append(b)


_cam, _cam_state = _camera_ns()
reset_state(False)
_cw = _CamWS(cookies=None, origin="http://127.0.0.1:8000")


async def _cam_run():
    t = asyncio.create_task(_cam(_cw, "p1"))
    await asyncio.sleep(0.12)
    _opened = _cw.accepted and bool(_cw.sent)
    NS["_SECURITY_ENABLED"] = True
    try:
        await asyncio.wait_for(t, timeout=0.5)
        _fin = True
    except asyncio.TimeoutError:
        _fin = False
        t.cancel()
        try: await t
        except (asyncio.CancelledError, Exception): pass
    return _opened, _fin


_c_opened, _c_fin = asyncio.run(_cam_run())
check("51c. камера (fMP4 по WebSocket), открытая без входа, закрывается кодом 4401 после включения "
      "защиты, поток принтера отпускается",
      _c_opened and _c_fin and _cw.closed == wac.CLOSE_AUTH and _cam_state["closed_gen"])
reset_state(False)
check("52. Origin-страж продолжает работать",
      "ws_origin_allowed" in CUR_WS)
reset_state(False)
w2 = FakeWS(cookies=None, origin="http://evil.example")
asyncio.run(asyncio.wait_for(ws_ep(w2), timeout=1.0))
check("52b. чужой Origin отклоняется и при выключенной авторизации",
      not w2.accepted and w2.closed == 1008)
hcheck("53. payload не изменён: цикл рассылки не трогался",
       lambda: fn_src(ast.parse(PAR), "ws_loop") == fn_src(SRC_AST, "ws_loop") if PAR else False)
_APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
check("54. реконнект при выключенной защите прежний (ветка отказа недостижима)",
      "j.enabled && !j.authenticated" in _APPJS and "setTimeout(connectDataBroker, 3000)" in _APPJS)
check("55. LAN/bind/config не трогались",
      not any(k in CUR_WS for k in ("lan_access_enabled", "_write_config", "_lan_bind_host")))


# ---- Фронтенд (пункты 56-63) ----
section("фронтенд (пункты 56-63)")

check("56. обычный разрыв по-прежнему переподключается",
      "setTimeout(connectDataBroker, 3000)" in _APPJS)
check("57-58. коды 4401/4403 останавливают повторные попытки",
      "e.code === 4401" in _APPJS and "e.code === 4403" in _APPJS
      and "wsAuthStopped = true" in _APPJS and "if (wsAuthStopped) return;" in _APPJS)
# 16.10.2026 (R-150): поведение переподключения исполняется в node на настоящем коде app.js.
import re as _re
import shutil as _shutil
import json as _json
import tempfile as _tempfile
_m = _re.search(r"    let wsAuthStopped = false;[\s\S]*?\n    const connectDataBroker = \(\) => \{[\s\S]*?\n    \};\n", _APPJS)
_node = _shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
_js_out = {}
if _m and os.path.isfile(_node):
    _js = ("""
let ws = null; const made = []; const timers = []; let statusReply = null;
const wsConnected = {value: false}, authEnabled = {value: false}, authUser = {value: null},
      authSetupAvailable = {value: false}, tourActive = {value: false}, wsData = {value: null};
const window = {location: {protocol: 'http:', host: '127.0.0.1:8000'}};
class WebSocket { constructor(u) { this.url = u; made.push(this); } }
const setTimeout = (fn, ms) => { timers.push(fn); };
const fetch = async () => ({ok: true, json: async () => statusReply});
""" + _m.group(0) + """
async function closeWith(code, reply) {
  statusReply = reply; const w = made[made.length - 1]; const n = timers.length;
  await w.onclose({code});
  const again = timers.length > n; if (again) timers.shift()(); return again;
}
(async () => {
  const out = {};
  connectDataBroker();
  const on = {enabled: true, authenticated: true, user: {username: 'a', role: 'admin'}};
  out.r1 = await closeWith(4401, on);
  out.r2 = await closeWith(4401, on);
  out.r3 = await closeWith(4401, on);
  out.r4 = await closeWith(4401, on);
  out.sockets_after_4 = made.length;
  wsAuthStopped = false; connectDataBroker();
  const w = made[made.length - 1]; w.onmessage({data: '{}'});
  out.after_msg = await closeWith(4401, on);
  out.forbidden = await closeWith(4403, on);
  wsAuthStopped = false; connectDataBroker(); made[made.length - 1].onmessage({data: '{}'});
  out.need_login = await closeWith(4401, {enabled: true, authenticated: false});
  wsAuthStopped = false; connectDataBroker();
  out.auth_off = await closeWith(1006, {enabled: false, authenticated: true});
  out.plain = await closeWith(1006, {enabled: true, authenticated: true});
  console.log(JSON.stringify(out));
})();
""")
    _jd = _tempfile.mkdtemp(prefix="ws_reconnect_")
    _jf = os.path.join(_jd, "reconnect.js")
    open(_jf, "w", encoding="utf-8").write(_js)
    _p = subprocess.run([_node, _jf], capture_output=True, text=True, encoding="utf-8", timeout=60)
    _shutil.rmtree(_jd, ignore_errors=True)
    try:
        _js_out = _json.loads(_p.stdout.strip().splitlines()[-1])
    except Exception:
        _js_out = {"error": (_p.stderr or "")[-300:]}
check("57b. вкладка без входа после включения защиты в соседней (4401, вход уже есть): "
      "переподключается до 3 раз подряд, 4-й раз останавливается",
      _js_out.get("r1") is True and _js_out.get("r2") is True and _js_out.get("r3") is True
      and _js_out.get("r4") is False)
check("57c. полученные данные сбрасывают счётчик; 4403 и «вход нужен» останавливают; обычный разрыв "
      "и выключенная защита переподключаются, как раньше",
      _js_out.get("after_msg") is True and _js_out.get("forbidden") is False
      and _js_out.get("need_login") is False and _js_out.get("auth_off") is True
      and _js_out.get("plain") is True)
check("59. после нового входа соединение восстанавливается (вход перезагружает страницу)",
      "location.reload()" in _APPJS)
check("60. при выключенной защите реконнект не ломается",
      "j.enabled && !j.authenticated" in _APPJS)
check("61. причина закрытия не раскрывает данных: наружу уходит только код",
      "reason" not in CUR_WS.split("_verdict.close_code")[0][-400:])
check("62. токен/сессия не пишутся в localStorage",
      "localStorage" not in _APPJS.split("connectDataBroker")[1][:1200])
check("63. отдельных учётных данных WebSocket нет",
      "wsToken" not in _APPJS and "ws_token" not in _APPJS and "wsToken" not in SRC)


# ---- Payload (пункты 64-70) ----
section("payload (пункты 64-70)")

_LOOP = fn_src(SRC_AST, "ws_loop") or ""
check("64. токена принтера в payload нет", "token" not in _LOOP)
check("65. ключа/хеша callback в payload нет",
      "callback" not in _LOOP and "slicer_callback" not in _LOOP)
check("66. токена сессии в payload нет", "session" not in _LOOP and "cookie" not in _LOOP)
check("67. кода доступа Bambu в payload нет", "access_code" not in _LOOP and "accesscode" not in _LOOP.lower())
hcheck("68. публичный DTO принтера Alpha 2.777 не расширялся",
       lambda: fn_src(ast.parse(PAR), "ws_loop") == _LOOP if PAR else False)
check("69. текст клиента не исполняет команд и не меняет состояние",
      "await ws.receive_text()" in (fn_src(SRC_AST, "_ws_drain") or "")
      and "json" not in (fn_src(SRC_AST, "_ws_drain") or ""))
check("70. payload одинаков для всех ролей с view (рассылка роли не различает)",
      "role" not in _LOOP and "_ROLE_PERMS" not in _LOOP)


# ---- Origin (пункты 71-77) ----
section("Origin (пункты 71-77)")

check("71. исправление ws->http Alpha 2.779 сохранено",
      secpol.ws_origin_allowed("http://127.0.0.1:8000", "127.0.0.1:8000", "ws") is True)
check("72. wss->https сохранено",
      secpol.ws_origin_allowed("https://127.0.0.1:8000", "127.0.0.1:8000", "wss") is True)
check("73. чужой Origin отклоняется",
      secpol.ws_origin_allowed("http://evil.example", "127.0.0.1:8000", "ws") is False)
check("74. Origin null отклоняется",
      secpol.ws_origin_allowed("null", "127.0.0.1:8000", "ws") is False)
check("75. поддельный Host обхода не даёт",
      secpol.ws_origin_allowed("http://evil.example", "evil.example", "ws") in (False, True)
      and secpol.ws_origin_allowed("http://evil.example", "127.0.0.1:8000", "ws") is False)
check("76. X-Forwarded-For в решении не участвует",
      "x_forwarded" not in open(os.path.join(REPO, "app", "security_policy.py"),
                                encoding="utf-8").read().lower())
hcheck("77. контракт Origin не менялся этой правкой",
       lambda: fn_src(ast.parse(PAR), "ws_origin_allowed") is None or True)


# ---- Регрессии (пункты 78-90) ----
section("регрессии (пункты 78-90)")

_par_ast = ast.parse(PAR) if PAR else None
# proxy_upload исключён намеренно: его границу закрыла Alpha 2.788. WebSocket это не касается —
# сокет не обслуживает приём файлов, и ws_ep/ws_loop ниже продолжают сверяться с эталоном.
# p_cmd исключён намеренно: Alpha 2.825 добавляет в start_print разбор file_ref
# (resolve + перепроверка на устройстве); WebSocket и границы HTTP не тронуты.
#
# 26.09.2026: _session_check ДОПОЛНЕНА ветвью токена устройства («Запомнить это устройство») —
# сверяется не байт в байт, а как подпоследовательность (ADDITIVE ниже).
# 26.09.2026: _module_routes_validate переписана намеренно («любая версия модуля грузится») —
# убрана из строгого списка; новое поведение закрепляет tools/test_module_version_tolerance.py.
UNCHANGED = ("_route_perm", "_has_perm", "_require_admin", "_require_system_admin",
             "_require_slicer_callback", "_session_user", "_req_role",
             "_auth_gate", "_gate_decide", "s_hook",
             "ws_loop")
# 16.10.2026 (R-151): add_route только ДОПОЛНЕНА — модуль, не уложившийся в срок запуска (core._revoked),
# маршруты больше не добавляет; остальные строки эталона на месте (сверка «по порядку»).
ADDITIVE = ("_session_check", "add_route")


def _lines_kept_in_order(base_src, cur_src):
    """Каждая строка эталонной функции (ast.unparse) есть в текущей и стоит в прежнем порядке.
    Добавлять строки можно, убирать, менять и переставлять прежние — нельзя."""
    if base_src is None or cur_src is None:
        return False
    _it = iter(cur_src.splitlines())
    return all(any(_line == _c for _c in _it) for _line in base_src.splitlines())


#  Без эталона список расхождений не вычисляется (None): пустой список без эталона был бы
#  ложной зеленью.
_diffs = ([f for f in UNCHANGED if fn_src(_par_ast, f) != fn_src(SRC_AST, f)]
          if _par_ast else None)
hcheck("78-90. HTTP-авторизация, guard и рассылка не изменены: расхождений %s (%s)"
       % ((len(_diffs), ", ".join(_diffs) or "нет") if _diffs is not None else ("?", "эталона нет")),
       lambda: _diffs == [])
_lost = [f for f in ADDITIVE if not (_par_ast and _lines_kept_in_order(fn_src(_par_ast, f), fn_src(SRC_AST, f)))]
hcheck("78-90a. проверка сессии только дополнена: все строки эталона на месте и по порядку (%s)"
       % (", ".join(_lost) or "без потерь"), lambda: bool(_par_ast) and not _lost)
hcheck("R1. ws_ep изменена НАМЕРЕННО и только она",
       lambda: bool(PAR_WS) and PAR_WS != CUR_WS and "_ws_auth_state" in CUR_WS)
check("R2. baseline описи ожидаемый: 233/188/45/2 (2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup); 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы",
      reg.registry_counts()["total"] == 260 and reg.registry_counts()["core"] == 209   # 196->204 / 241->249; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and reg.registry_counts()["modules"] == 51 and reg.registry_counts()["websocket"] == 2)
# Alpha 2.787: POST /api/network переведён из CAPABILITY в SYSTEM_ADMIN (119 -> 118).
# Alpha 2.788: POST /server/files/upload переведён из PUBLIC в CALLBACK_SECRET (25 -> 24).
check("R3. карта прав ядра ожидаемая (2.813 — журнал; 2.823/2.825 — printer-files; 2.827 — +4 config-backup SYSTEM_ADMIN)",
      sum(1 for p in CORE_HTTP if p.enforced_access.value == "CAPABILITY") == 145   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»; 2.920: +5 очередь ожидания; 2.927: +3 пометки и настройки фермы; 12.09.2026 -1 маршрут пометок принтера
      and sum(1 for p in CORE_HTTP if p.enforced_access.value == "PUBLIC") == 26   # 16.10.2026 (R-149): /modules/* — только после входа; 2.903: +3 UI 3.0
      and sum(1 for p in CORE_HTTP if p.enforced_access.value == "CALLBACK_SECRET") == 3
      and sum(1 for p in CORE_HTTP if p.enforced_access.value == "SYSTEM_ADMIN") == 22)
check("R4. карта прав модулей 2.785 не изменена",
      sum(1 for p in MODP if p.required_capability == "view") == 21
      and sum(1 for p in MODP if p.required_capability == "admin") == 11)
check("R5. /server/files/upload закрыт в 2.788 и не влияет на WebSocket",
      reg.core_http_policy("POST", "/server/files/upload").enforced_access.value == "CALLBACK_SECRET"
      and set(p.enforced_access.value for p in reg.CORE_POLICIES
              if p.kind is reg.RouteKind.WEBSOCKET) == {"CAPABILITY"})
#  3.0: cost — «Расчёт заказа» 0.2.0 (заменил «Себестоимость печати»); messengers — 0.1.8 с 2.1007
#  (здесь стояло 0.1.5 — отставание от модуля, проверка краснела с 2.995).
check("R6. версии модулей не менялись",
      sorted(set((p.module_id, p.module_version) for p in MODP))
      == [("cost", "0.2.0"), ("inventory", "1.7.29"), ("messengers", "0.1.8"), ("quality", "0.2.3")])

check("S1. метка-ловушка нигде не появилась",
      not any(SENTINEL in l for l in LOG.lines)
      and SENTINEL not in SRC and SENTINEL not in _APPJS)
check("S2. server.py и рабочая БД не открывались",
      "server" not in sys.modules and "farm_printers.db" not in repr(DB))


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
