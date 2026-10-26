# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.784 — явная карта прав маршрутов ядра.
#
#  ЧТО ДОКАЗЫВАЕТ ЭТОТ ФАЙЛ
#   Часть 1. ХАРАКТЕРИЗАЦИЯ. Как система решала доступ ДО правки (Alpha 2.783):
#            любой GET получал право None, неизвестное изменяющее — 'project',
#            весь префикс /api/auth/ обходил гейт одной строкой условия. Легаси-модель
#            реконструирована и СВЕРЕНА с исходником родительского коммита, поэтому
#            эти проверки остаются зелёными навсегда: они описывают историю.
#   Часть 2+. Новая модель: движок, резолвер маршрута, полнота карты, матрица ролей,
#            особые решения, поведение при выключенной авторизации, порядок побочных
#            эффектов, краевые случаи сопоставления и регрессии.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется: только чтение исходника и разбор AST.
#   * Работающая программа не трогается: ни запуска, ни остановки, ни запросов к ней.
#   * Ни одной реальной БД, DATA_DIR, config.json, сети, слайсера и принтера.
#   * Приложение для проверок — своё, изолированное, с обработчиками-заглушками.
#
#  Запуск:  python tools/test_core_route_permissions.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import asyncio
import json
import os
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

PARENT = "8fe9e70"   # HEAD до Alpha 2.784: эталон прежнего поведения

FAILED = []
PASSED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)


def section(title):
    print("\n--- %s ---" % title)


# Метка-ловушка. Если она хоть раз окажется в обработчике, БД, файловой системе,
# адаптере принтера, очереди, подпроцессе, журнале, аудите или в теле ответа при
# отказе — значит отказ случился ПОЗЖЕ побочного эффекта. Живёт только в тесте.
SENTINEL = "CORE_PERMISSION_SENTINEL_2_784"

SRC_PATH = os.path.join(REPO, "server.py")
SRC = open(SRC_PATH, encoding="utf-8", errors="surrogateescape").read()
SRC_AST = ast.parse(SRC)

from app import route_access_control as rac          # noqa: E402
from app import route_matching as rm                 # noqa: E402
from app import route_policy_registry as reg         # noqa: E402

EA, ES, AD = rac.EnforcedAccess, rac.EnforcementStage, rac.AccessDecision


def fn_src(tree_or_src, name):
    tree = tree_or_src if isinstance(tree_or_src, ast.AST) else ast.parse(tree_or_src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return None


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["server.py"], check)
hcheck = HIST.check


def parent_src():
    return HIST.show("server.py")


def literal_from_src(name):
    for n in ast.walk(SRC_AST):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    return None


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.784: явная карта прав маршрутов ядра ===")
section("характеризация: как решался доступ в Alpha 2.783")

# Модель ролей и исключения гейта берём ИЗ ИСХОДНИКА, а не из памяти.
ROLE_PERMS = literal_from_src("_ROLE_PERMS")
GATE_EXCLUDE = literal_from_src("_GATE_EXCLUDE")
check("H0. модель ролей и _GATE_EXCLUDE прочитаны из server.py",
      isinstance(ROLE_PERMS, dict) and len(ROLE_PERMS) == 4 and len(GATE_EXCLUDE) == 5)

# Легаси _route_perm исполняем В ИЗОЛЯЦИИ: это настоящий код из server.py, но server.py
# при этом не импортируется (в нём named mutex, БД и запуск сервера).
_legacy_ns = {"re": __import__("re")}
exec(compile(fn_src(SRC_AST, "_route_perm"), "<_route_perm>", "exec"), _legacy_ns)
legacy_route_perm = _legacy_ns["_route_perm"]

PAR = parent_src()
hcheck("H1. эталон %s:server.py прочитан" % PARENT, lambda: PAR is not None)
par_gate = fn_src(PAR, "_auth_gate") if PAR else ""

# Реконструкция гейта 2.783. Достоверность доказывается тем, что ровно это условие
# присутствует в тексте родительского коммита (H2), а в текущем его больше нет (A11).
LEGACY_GATE_COND = "path.startswith('/api/') and (not path.startswith('/api/auth/')) and (path not in _GATE_EXCLUDE)"
hcheck("H2. условие гейта 2.783 дословно найдено в %s" % PARENT,
       lambda: bool(par_gate) and LEGACY_GATE_COND in par_gate)


def legacy_gate(method, path, role, security_enabled=True, has_session=True):
    """Точная реконструкция общего гейта Alpha 2.783."""
    if not security_enabled:
        return "ALLOW"
    if not (path.startswith("/api/") and not path.startswith("/api/auth/")
            and path not in GATE_EXCLUDE):
        return "ALLOW"                       # мимо гейта: статика, /api/auth/*, _GATE_EXCLUDE
    if not has_session:
        return "401"
    perm = legacy_route_perm(method, path)
    if perm and perm not in ROLE_PERMS.get(role, set()):
        return "403"
    return "ALLOW"


CORE_HTTP = [p for p in reg.CORE_POLICIES if p.kind is reg.RouteKind.HTTP]
CORE_WS = [p for p in reg.CORE_POLICIES if p.kind is reg.RouteKind.WEBSOCKET]
MOD = [p for p in reg.ALL_POLICIES if p.module_id is not None]

# 1. Любой GET ядра получал право None.
check("H3. (характеризация 1) любой GET ядра получал право None: проверено %d"
      % sum(1 for p in CORE_HTTP if p.method == "GET"),
      all(legacy_route_perm("GET", p.path) is None for p in CORE_HTTP if p.method == "GET"))

# 2. Observer получал почти все GET.
obs_gets = [p for p in CORE_HTTP if p.method == "GET"
            and legacy_gate("GET", p.path, "observer") == "ALLOW"]
check("H4. (характеризация 2) observer получал все %d GET ядра" % len(obs_gets),
      len(obs_gets) == sum(1 for p in CORE_HTTP if p.method == "GET"))

# 3. Изменяющие маршруты с perm=None: их прежний слой прав пропускал наблюдателя.
#    2.980 (R-092): +2 — запуск и остановка сырой записи сетевых объявлений. Они живут по
#    правилам диагностики, а доступ к ним закрыт правом администратора отдельной записью.
mut_none = [p for p in CORE_HTTP if p.method in reg.MUTATING_METHODS
            and legacy_route_perm(p.method, p.path) is None]
check("H5. (характеризация 3) изменяющие с perm=None были доступны observer: %d"
      % len(mut_none),
      len(mut_none) == 9 and all(legacy_gate(p.method, p.path, "observer") == "ALLOW"
                                 for p in mut_none))

# 4. Остальные неизвестные изменяющие получали 'project'.
check("H6. (характеризация 4) неизвестный изменяющий получал 'project'",
      legacy_route_perm("POST", "/api/completely-unknown-route-2784") == "project"
      and legacy_route_perm("DELETE", "/api/another/unknown/{x}") == "project")

# 5. /api/auth/* обходили гейт по префиксу.
auth_routes = [p for p in CORE_HTTP if p.path.startswith("/api/auth/")]
check("H7. (характеризация 5) все %d /api/auth/* обходили гейт по префиксу" % len(auth_routes),
      len(auth_routes) == 12
      and all(legacy_gate(p.method, p.path, "observer", has_session=False) == "ALLOW"
              for p in auth_routes))

# 6. Новый /api/auth/... автоматически обошёл бы гейт.
check("H8. (характеризация 6) НОВЫЙ /api/auth/... обошёл бы гейт автоматически",
      legacy_gate("POST", "/api/auth/brand-new-danger", "observer", has_session=False) == "ALLOW")

# 7-8. Новый GET получил бы None, новый POST — 'project'.
check("H9. (характеризация 7) новый GET получил бы право None",
      legacy_route_perm("GET", "/api/brand-new-2784") is None)
check("H10. (характеризация 8) новый POST получил бы право 'project'",
      legacy_route_perm("POST", "/api/brand-new-2784") == "project")

# 9. /api/logs/download был доступен observer.
check("H11. (характеризация 9) GET /api/logs/download был доступен observer",
      legacy_gate("GET", "/api/logs/download", "observer") == "ALLOW")

# 10. Изменяющая диагностика была доступна observer.
diag_mut = ["/api/diagnostics/bambu-sniff/start", "/api/diagnostics/bambu-sniff/stop",
            "/api/diagnostics/verbose", "/api/diagnostics/monitor",
            "/api/diagnostics/clear", "/api/diagnostics/client"]
check("H12. (характеризация 10) вся изменяющая диагностика была доступна observer",
      all(legacy_gate("POST", p, "observer") == "ALLOW" for p in diag_mut))

# 11. Маршруты модулей работали по общему fallback.
check("H13. (характеризация 11) все %d маршрутов модулей шли по общему fallback" % len(MOD),
      len(MOD) == 51
      and all(p.current_permission == legacy_route_perm(p.method, p.path) for p in MOD))

# 12. WebSocket картой прав не пользовался.
# Alpha 2.879: сокетов стало два (телеметрия /ws и камера). Смысл проверки прежний: картой
# прав HTTP они не пользуются ни один, ни другой.
check("H14. (характеризация 12) WebSocket не использовал карту прав",
      len(CORE_WS) == 2 and all(p.current_permission is None for p in CORE_WS)
      and "_route_perm" not in (fn_src(SRC_AST, "ws_ep") or "")
      and "_route_perm" not in (fn_src(SRC_AST, "printer_camera_ws") or ""))


# 16.10.2026 (R-150, аудит arch-auth-17): _route_perm — только исторический эталон для наборов
# характеристики; гейт решает по реестру. Вызов в коде программы или модулей вернул бы вторую,
# расходящуюся карту прав. Ищем настоящие вызовы по AST (комментарии и строки не считаются).
def _route_perm_calls():
    hits = []
    files = [os.path.join(REPO, "server.py")]
    for _top in ("app", "modules"):
        for _b, _ds, _fs in os.walk(os.path.join(REPO, _top)):
            _ds[:] = [d for d in _ds if d not in ("__pycache__", "node_modules", "vendor")]
            files += [os.path.join(_b, f) for f in _fs if f.endswith(".py")]
    for _f in files:
        try:
            _t = ast.parse(open(_f, encoding="utf-8", errors="surrogateescape").read())
        except SyntaxError:
            continue
        for _n in ast.walk(_t):
            if isinstance(_n, ast.Call):
                _fn = _n.func
                _nm = _fn.id if isinstance(_fn, ast.Name) else (_fn.attr if isinstance(_fn, ast.Attribute) else "")
                if _nm == "_route_perm":
                    hits.append("%s:%d" % (os.path.relpath(_f, REPO), _n.lineno))
    return hits


_rp_hits = _route_perm_calls()
check("RP1. _route_perm нигде не вызывается — ни в server.py, ни в app/, ни в модулях (право — только в реестре)",
      _rp_hits == [] and fn_src(SRC_AST, "_route_perm") is not None)
if _rp_hits:
    print("   вызовы _route_perm: %s" % ", ".join(_rp_hits))

# 13. Guard обработчиков работали отдельно от гейта.
guarded = [p for p in CORE_HTTP if p.handler_guard is not reg.HandlerGuard.NONE]
# Alpha 2.787 добавила двадцатую границу: POST /api/network (открытие фермы в сеть).
# Alpha 2.788 добавила двадцать первую: POST /server/files/upload (Moonraker-приём файла).
# Alpha 2.798 добавила двадцать вторую: POST /api/auth/local-recovery/complete (local-recovery guard).
check("H15. (характеризация 13) guard обработчиков были независимой границей: %d" % len(guarded),
      len(guarded) == 32)   # Alpha 2.813: +GET /api/diagnostics; 2.823: +pf_delete/pf_settings_set; 2.827: +4 config-backup (SYSTEM_ADMIN); 26.09.2026 +3 лицензии модулей (SYSTEM_ADMIN)

# 14. При выключенной авторизации гейт не выполнял проверок.
check("H16. (характеризация 14) при AUTH OFF гейт пропускал всё",
      all(legacy_gate(p.method, p.path, None, security_enabled=False) == "ALLOW"
          for p in CORE_HTTP))

# 15. Характеризация не вызывает обработчиков и не создаёт побочных эффектов.
check("H17. (характеризация 15) характеризация не вызвала ни одного обработчика",
      "server" not in sys.modules)


# ════════════════════════════════════════════════════════════════════════════
section("движок решений (чистый, без фреймворка и БД)")

check("E1. движок не тянет фреймворк, БД, сеть и config",
      not {"fastapi", "starlette", "sqlite3", "socket", "urllib", "requests", "os"}
      & {(n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0])
         for n in ast.walk(ast.parse(open(os.path.join(REPO, "app", "route_access_control.py"),
                                          encoding="utf-8").read()))
         if isinstance(n, (ast.Import, ast.ImportFrom))})


def ctx(role=None, session=True, enabled=True, security=True):
    caps = ROLE_PERMS.get(role)
    return rac.SecurityContext(
        security_enabled=security, has_session=session and role is not None,
        user_enabled=enabled, role=role,
        capabilities=(frozenset(caps) if caps is not None else None))


def pol(method, path):
    return reg.core_http_policy(method, path)


def outcome(method, path, role=None, **kw):
    return rac.decide(pol(method, path), ctx(role, **kw)).outcome


check("E2. отсутствие политики = отказ, а не разрешение",
      rac.decide(None, ctx("admin")).outcome is AD.POLICY_MISSING)
check("E3. решение детерминировано (два одинаковых входа — один выход)",
      rac.decide(pol("GET", "/api/printers"), ctx("observer"))
      == rac.decide(pol("GET", "/api/printers"), ctx("observer")))
check("E4. вход неизменяем (frozen dataclass)",
      type(ctx("admin")).__dataclass_params__.frozen
      and type(rac.decide(None, ctx())).__dataclass_params__.frozen)
check("E5. коды причин не содержат URL, параметров и тела запроса",
      all(("/" not in v and "?" not in v)
          for k, v in vars(rac).items()
          if k.startswith("REASON_") and isinstance(v, str)))
check("E6. needs_session_state честен: для PUBLIC решение от сессии не зависит",
      all(rac.decide(p, ctx(r)).outcome is rac.decide(p, ctx(None, session=False)).outcome
          for p in reg.CORE_POLICIES if p.enforced_access is EA.PUBLIC
          for r in ("admin", "observer", None)))


# ════════════════════════════════════════════════════════════════════════════
section("резолвер: фактически совпавший маршрут")

from fastapi import FastAPI, Request                                    # noqa: E402
from fastapi.responses import JSONResponse, PlainTextResponse           # noqa: E402

SPY = {"handler": [], "db": [], "fs": [], "printer": [], "queue": [],
       "subprocess": [], "log": [], "audit": [], "body": []}


def reset_spy():
    for v in SPY.values():
        del v[:]


def build_app():
    """Изолированное приложение: настоящие пути из реестра, обработчики-заглушки.

    Каждый обработчик отмечается в SPY и имитирует побочные эффекты. Если гейт
    отказал правильно, ни одна из этих отметок появиться не может.
    """
    a = FastAPI(lifespan=None)

    def mk(name):
        async def h(request: Request):
            SPY["handler"].append(name)
            SPY["db"].append(name)          # обработчики ядра ходят в БД/ФС/очередь
            SPY["fs"].append(name)
            SPY["queue"].append(name)
            body = await request.body()     # реальное чтение тела — только тут
            SPY["body"].append(body[:64])
            return {"ok": True, "route": name}
        h.__name__ = name
        return h

    routes = [
        ("GET", "/api/printers", "g_printers"),
        ("POST", "/api/printers/save", "s_printers"),
        ("POST", "/api/printer/{pid}/cmd", "p_cmd"),
        ("POST", "/api/printer/{pid}/webrtc", "printer_webrtc"),
        ("GET", "/api/logs/download", "download_logs"),
        ("POST", "/api/diagnostics/client", "diagnostics_client"),
        ("POST", "/api/diagnostics/verbose", "diagnostics_verbose"),
        ("POST", "/api/diagnostics/bambu-sniff/start", "api_bambu_sniff_start"),
        ("POST", "/api/diagnostics/bambu-sniff/stop", "api_bambu_sniff_stop"),
        ("POST", "/api/diagnostics/monitor", "api_diag_monitor_set"),
        ("POST", "/api/diagnostics/clear", "diagnostics_clear"),
        ("PATCH", "/api/projects2/{project_id}/parts/{part_id}", "u_project2_part"),
        ("POST", "/api/projects2/{project_id}/parts/{part_id}/rework", "request_part_rework"),
        ("POST", "/api/part/print", "part_print"),
        ("POST", "/api/auth/login", "auth_login"),
        ("GET", "/api/auth/status", "auth_status"),
        ("POST", "/api/auth/logout", "auth_logout"),
        ("GET", "/api/auth/users", "auth_users_list"),
        ("POST", "/api/restart", "restart_app"),
        ("POST", "/api/slicer-hook", "s_hook"),
        ("GET", "/api/version", "octo_version"),
        ("GET", "/version", "version"),
        ("POST", "/server/files/upload", "proxy_upload"),
        ("GET", "/assets/{module_path:path}", "_serve_ui_module"),
        # 16.10.2026 (R-149): файлы интерфейса модулей — только после входа.
        ("GET", "/modules/{module_id}/{asset_path:path}", "_serve_module_asset"),
        ("GET", "/api/mod/inventory/items", "api_inv_items"),
        ("POST", "/api/mod/inventory/item", "api_inv_item_create"),
        # Маршрут ядра, которого НЕТ в реестре: обязан быть закрыт fail-closed.
        ("GET", "/api/unregistered-route-2784", "unregistered_handler"),
    ]
    for m, p, n in routes:
        a.add_api_route(p, mk(n), methods=[m])
    return a


APP = build_app()
SESSIONS = {}   # токен -> роль (поддельные сессии, настоящих здесь быть не может)


def gate_reference(scope, cookie_role, security_enabled):
    """Референс-реализация гейта из тех же модулей, что использует server.py.

    Тест не импортирует server.py, поэтому композиция собирается здесь, а её
    совпадение с продуктовой доказывается разбором AST в разделе регрессий (R*).
    -> (ответ-отказ | None)
    """
    if not security_enabled:
        return None
    matched = rm.resolve_matched_route(scope["app"].routes, scope)
    if matched is None:
        return None
    if matched.is_module_route:
        if cookie_role is None:
            return ("401", {"error": "unauthorized"})
        perm = legacy_route_perm(scope["method"].upper(), scope["path"])
        if perm and perm not in ROLE_PERMS.get(cookie_role, set()):
            return ("403", {"error": "forbidden", "perm": perm})
        return None
    policy = reg.core_http_policy(matched.method, matched.path_template)
    u = cookie_role if rac.needs_session_state(policy) else None
    d = rac.decide(policy, ctx(u, session=u is not None, security=True))
    if d.outcome is AD.POLICY_MISSING:
        SPY["log"].append(matched.endpoint_name)
        return ("500", {"error": "server_error", "reason": rac.REASON_POLICY_MISSING})
    if d.outcome is AD.REQUIRE_SESSION:
        return ("401", {"error": "unauthorized"})
    if d.outcome is AD.FORBIDDEN:
        b = {"error": "forbidden"}
        if d.required_capability:
            b["perm"] = d.required_capability
        return ("403", b)
    return None


def install_gate(a):
    @a.middleware("http")
    async def _gate(request, call_next):
        role = request.headers.get("x-test-role") or None
        sec = request.headers.get("x-test-security", "1") == "1"
        deny = gate_reference(request.scope, role, sec)
        if deny is not None:
            return JSONResponse(deny[1], status_code=int(deny[0]))
        return await call_next(request)
    return a


install_gate(APP)


def call(method, path, role=None, security=True, body=b"", headers=None):
    """Один HTTP-запрос через ASGI напрямую: httpx в окружении нет, ставить нельзя."""
    hdrs = {"x-test-security": "1" if security else "0"}
    if role:
        hdrs["x-test-role"] = role
    hdrs.update(headers or {})
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method.upper(), "scheme": "http",
        "path": path, "raw_path": path.encode("utf-8", "surrogateescape"),
        "root_path": "", "query_string": b"",
        "headers": [(k.lower().encode(), str(v).encode()) for k, v in hdrs.items()],
        "client": ("127.0.0.1", 51234), "server": ("127.0.0.1", 8000),
    }
    out = {"status": None, "body": b""}
    state = {"sent": False}

    async def receive():
        if state["sent"]:
            return {"type": "http.disconnect"}
        state["sent"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"") or b""

    asyncio.run(APP(scope, receive, send))
    return out


def status(method, path, role=None, **kw):
    reset_spy()
    return call(method, path, role, **kw)["status"]


check("M1. параметр пути разбирается как шаблон, а не как строка",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "POST",
                                            "path": "/api/printer/AB-99/cmd",
                                            "path_params": {}}).path_template
      == "/api/printer/{pid}/cmd")
check("M2. несовпадение метода не считается совпадением (останется 405)",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "DELETE",
                                            "path": "/api/printers", "path_params": {}}) is None)
check("M3. неизвестный URL не совпадает ни с чем (останется 404)",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "GET",
                                            "path": "/api/no-such-thing", "path_params": {}}) is None)
# HEAD у двух классов маршрутов ведёт себя ПО-РАЗНОМУ — доказываем оба случая.
check("M4a. HEAD на маршруте ядра (APIRoute) не совпадает: остаётся штатный 405",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "HEAD",
                                            "path": "/api/printers", "path_params": {}}) is None)
check("M4b. HEAD на маршруте фреймворка (Route) совпадает и НАСЛЕДУЕТ политику GET",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "HEAD",
                                            "path": "/openapi.json",
                                            "path_params": {}}).method == "GET")
check("M5. OPTIONS собственной бизнес-политики не требует (совпадения нет)",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "OPTIONS",
                                            "path": "/api/printers", "path_params": {}}) is None)
check("M6. маршрут модуля распознан как модульный",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "GET",
                                            "path": "/api/mod/inventory/items",
                                            "path_params": {}}).is_module_route is True)
check("M7. маршрут ядра модульным не считается",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "GET",
                                            "path": "/api/printers",
                                            "path_params": {}}).is_module_route is False)
check("M8. path-конвертер (:path) сопоставляется корректно",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "GET",
                                            "path": "/assets/inventory/Panel.js",
                                            "path_params": {}}).path_template
      == "/assets/{module_path:path}")
check("M9. двойной слэш не выдаёт себя за существующий маршрут",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "GET",
                                            "path": "//api/printers", "path_params": {}}) is None)
check("M10. имя обработчика извлекается верно",
      rm.resolve_matched_route(APP.routes, {"type": "http", "method": "GET",
                                            "path": "/api/printers",
                                            "path_params": {}}).endpoint_name == "g_printers")


# ════════════════════════════════════════════════════════════════════════════
section("полнота карты прав (пункты 1-10)")

check("1. все %d HTTP-маршрута ядра имеют этап CORE_2_784" % len(CORE_HTTP),
      len(CORE_HTTP) == 207   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»; 2.980: +7 поиск принтеров в сети и запись сетевых объявлений; 2.978: +1 «где лежит файл проекта»; 2.903: +3 UI 3.0 (вторая страница); Alpha 2.823: +5 printer-files; 2.825: +select-for-print; 2.827: +4 config-backup; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.870: +камера без перекодирования; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and all(p.enforcement_stage is ES.CORE_2_784 for p in CORE_HTTP))
check("2. ни один маршрут ядра не остался DEFERRED",
      not [p for p in CORE_HTTP if p.enforced_access is EA.DEFERRED])
# Alpha 2.785 перевела маршруты модулей на собственный активный этап. Для ЯДРА важно
# другое: они по-прежнему не относятся к CORE_2_784 и решаются отдельной картой.
check("3. все 51 маршрутов модулей вынесены за пределы карты ядра (этап MODULE_2_785)",
      len(MOD) == 51 and all(p.enforcement_stage is ES.MODULE_2_785 for p in MOD)
      and not any(p.enforcement_stage is ES.CORE_2_784 for p in MOD))
# Alpha 2.786 включила собственный этап WebSocket. Для КАРТЫ ЯДРА важно другое: /ws в неё
# не входит и решается отдельным движком, а HTTP-гейт его не видит вовсе.
check("4. оба сокета вынесены из карты ядра в собственный этап WebSocket",
      len(CORE_WS) == 2
      and all(p.enforcement_stage is ES.WEBSOCKET_2_786 for p in CORE_WS)
      and not any(p.enforcement_stage is ES.CORE_2_784 for p in CORE_WS))
check("5. новый маршрут ядра без политики валит проверку (fail closed)",
      reg.core_http_policy("GET", "/api/unregistered-route-2784") is None
      and status("GET", "/api/unregistered-route-2784", "admin") == 500)
check("6. устаревшая политика без маршрута обнаруживается",
      reg.core_http_policy("GET", "/api/removed-in-the-future-2784") is None)
check("7. расхождение метода/пути/обработчика обнаруживается",
      reg.core_http_policy("POST", "/api/printers") is None
      and reg.core_http_policy("GET", "/api/printers").handler == "g_printers")
check("8. HEAD/OPTIONS не получили фиктивных бизнес-записей",
      not any(p.method in ("HEAD", "OPTIONS") for p in reg.ALL_POLICIES)
      and not any(p.method in ("HEAD", "OPTIONS") for p in reg.FRAMEWORK_POLICIES))
check("9. неизвестный URL сохраняет 404, чужой метод — 405",
      status("GET", "/api/no-such-thing", "observer") == 404
      and status("DELETE", "/api/printers", "observer") == 405)
check("10. найденный маршрут без политики закрыт до обработчика",
      status("GET", "/api/unregistered-route-2784", "admin") == 500
      and not SPY["handler"])


# ════════════════════════════════════════════════════════════════════════════
section("пространство /api/auth/* (пункты 11-18)")

cur_gate = fn_src(SRC_AST, "_auth_gate") or ""
check("11. общего обхода startswith('/api/auth/') в гейте больше нет",
      "startswith('/api/auth/')" not in cur_gate and '"/api/auth/"' not in cur_gate)
check("12. все 12 маршрутов авторизации имеют точную политику",
      len(auth_routes) == 12
      and all(p.enforced_access is not EA.DEFERRED for p in auth_routes))
check("13. НОВЫЙ /api/auth/... не становится публичным автоматически",
      reg.core_http_policy("POST", "/api/auth/brand-new-danger") is None
      and rac.decide(None, ctx("observer")).outcome is AD.POLICY_MISSING)
check("14. вход доступен анонимно",
      pol("POST", "/api/auth/login").enforced_access is EA.PUBLIC
      and status("POST", "/api/auth/login") == 200)
check("15. первичная настройка сохраняет контракт",
      pol("POST", "/api/auth/setup").enforced_access is EA.PUBLIC)
check("16. статус защиты сохраняет контракт (доступен до входа)",
      pol("GET", "/api/auth/status").enforced_access is EA.PUBLIC
      and status("GET", "/api/auth/status") == 200)
check("17. выход и отключение защиты требуют сессии",
      pol("POST", "/api/auth/logout").enforced_access is EA.SESSION_ONLY
      and pol("POST", "/api/auth/disable").enforced_access is EA.SESSION_ONLY
      and status("POST", "/api/auth/logout") == 401
      and status("POST", "/api/auth/logout", "observer") == 200)
check("18. пользователи и аудит остаются за _require_admin",
      all(pol(m, p).enforced_access is EA.HANDLER_ADMIN for m, p in (
          ("GET", "/api/auth/users"), ("POST", "/api/auth/users"),
          ("PATCH", "/api/auth/users/{uid}"), ("DELETE", "/api/auth/users/{uid}"),
          ("GET", "/api/auth/audit"), ("GET", "/api/auth/audit/export"))))


# ════════════════════════════════════════════════════════════════════════════
section("устранение неявных правил (пункты 19-23)")

check("19. ни один GET ядра не разрешён неявным None",
      all(p.enforced_access is not EA.DEFERRED and
          (p.enforced_access is not EA.CAPABILITY or p.required_capability)
          for p in CORE_HTTP if p.method == "GET"))
check("20. ни один изменяющий маршрут ядра не получает право общим fallback",
      all(p.enforced_access is not EA.DEFERRED for p in CORE_HTTP
          if p.method in reg.MUTATING_METHODS))
check("21. маршруты модулей продолжают идти по прежнему fallback",
      status("POST", "/api/mod/inventory/item", "observer") == 403
      and status("POST", "/api/mod/inventory/item", "operator") == 200
      and status("GET", "/api/mod/inventory/items", "observer") == 200)
check("22. _route_perm НЕ участвует в решении по маршруту ядра",
      "_route_perm(" not in (fn_src(SRC_AST, "_gate_decide") or "x"))
# С Alpha 2.785 _route_perm не участвует в авторизации вовсе: маршруты модулей получили
# собственную явную карту. Функция сохранена как исторический помощник и как источник
# характеризации — вызовов в рантайме у неё больше нет.
check("23. _route_perm сохранён в коде, но в рантайме не вызывается",
      fn_src(SRC_AST, "_route_perm") is not None and SRC.count("_route_perm(") == 1)


# ════════════════════════════════════════════════════════════════════════════
section("матрица ролей (пункты 24-39)")

VIEW_GET = [p for p in CORE_HTTP if p.enforced_access is EA.CAPABILITY
            and p.required_capability == "view"]
MUT_CAP = [p for p in CORE_HTTP if p.enforced_access is EA.CAPABILITY
           and p.method in reg.MUTATING_METHODS]

check("24. observer получает явное право view на всех %d маршрутах чтения" % len(VIEW_GET),
      all(rac.decide(p, ctx("observer")).outcome is AD.ALLOW for p in VIEW_GET))
check("25. observer не получает ни одного изменяющего маршрута ядра",
      all(rac.decide(p, ctx("observer")).outcome is AD.FORBIDDEN for p in MUT_CAP
          if p.required_capability != "view"))
check("26. observer не получает системный журнал",
      status("GET", "/api/logs/download", "observer") == 403)
check("27. observer не получает изменяющую диагностику",
      status("POST", "/api/diagnostics/verbose", "observer") == 403)
check("28. observer не получает прямую команду принтеру",
      status("POST", "/api/printer/P1/cmd", "observer") == 403)
check("29. observer получает WebRTC (просмотр камеры)",
      status("POST", "/api/printer/P1/webrtc", "observer") == 200)
check("30. assembler получает только view/rework, но не count и не project",
      rac.decide(pol("POST", "/api/projects2/{project_id}/parts/{part_id}/rework"),
                 ctx("assembler")).outcome is AD.ALLOW
      and rac.decide(pol("PATCH", "/api/projects2/{project_id}/parts/{part_id}"),
                     ctx("assembler")).outcome is AD.FORBIDDEN
      and rac.decide(pol("POST", "/api/printers/save"), ctx("assembler")).outcome is AD.FORBIDDEN)
check("31. operator получает operate и project согласно модели ролей",
      status("POST", "/api/part/print", "operator") == 200
      and status("POST", "/api/printer/P1/cmd", "operator") == 200
      and status("POST", "/api/printers/save", "operator") == 200)
check("32. operator не получает admin-маршрутов",
      status("GET", "/api/logs/download", "operator") == 403
      and status("POST", "/api/diagnostics/verbose", "operator") == 403)
check("33. operator не проходит handler-admin (решает _require_admin)",
      rac.decide(pol("GET", "/api/auth/users"), ctx("operator")).outcome is AD.DEFER_TO_HANDLER)
check("34. operator не проходит system-admin (решает _require_system_admin)",
      rac.decide(pol("POST", "/api/restart"), ctx("operator")).outcome is AD.DEFER_TO_HANDLER)
check("35. admin получает обычный функционал",
      status("GET", "/api/printers", "admin") == 200
      and status("POST", "/api/part/print", "admin") == 200
      and status("GET", "/api/logs/download", "admin") == 200)
check("36. admin без ключа интеграции не открывает callback",
      rac.decide(pol("POST", "/api/slicer-hook"), ctx("admin")).outcome is AD.DEFER_TO_HANDLER)
check("37. неизвестная роль получает отказ",
      rac.decide(pol("GET", "/api/printers"), ctx("wizard")).outcome is AD.FORBIDDEN
      and status("GET", "/api/printers", "wizard") == 403)
check("38. отключённый пользователь получает отказ",
      rac.decide(pol("GET", "/api/printers"),
                 rac.SecurityContext(security_enabled=True, has_session=True,
                                     user_enabled=False, role="admin",
                                     capabilities=frozenset(ROLE_PERMS["admin"]))
                 ).outcome is AD.REQUIRE_SESSION)
check("39. недействительная сессия получает отказ",
      rac.decide(pol("GET", "/api/printers"), ctx(None, session=False)).outcome
      is AD.REQUIRE_SESSION and status("GET", "/api/printers") == 401)


# ════════════════════════════════════════════════════════════════════════════
section("особые решения (пункты 40-48)")

SPECIALS = (
    ("40. системный журнал только администратору", "GET", "/api/logs/download", "admin"),
    ("41. запуск bambu-sniff только администратору", "POST", "/api/diagnostics/bambu-sniff/start", "admin"),
    ("42. остановка bambu-sniff только администратору", "POST", "/api/diagnostics/bambu-sniff/stop", "admin"),
    ("43. подробный режим только администратору", "POST", "/api/diagnostics/verbose", "admin"),
    ("44. переключение мониторинга только администратору", "POST", "/api/diagnostics/monitor", "admin"),
    ("45. очистка буфера диагностики только администратору", "POST", "/api/diagnostics/clear", "admin"),
)
for _name, _m, _p, _cap in SPECIALS:
    _pl = pol(_m, _p)
    check(_name, _pl.enforced_access is EA.CAPABILITY and _pl.required_capability == _cap)

check("46. приёмник ошибок интерфейса доступен любой действующей сессии",
      pol("POST", "/api/diagnostics/client").enforced_access is EA.SESSION_ONLY
      and all(status("POST", "/api/diagnostics/client", r) == 200
              for r in ("observer", "assembler", "operator", "admin"))
      and status("POST", "/api/diagnostics/client") == 401)
# 16.10.2026 (R-149, аудит arch-auth-19/paid-boundary-14): файлы интерфейса модулей отдаются
# только вошедшему. Проверяется настоящим гейтом на изолированном приложении: без входа — 401
# и обработчик не вызван; любая роль — 200; защита выключена — 200, как раньше.
_ma_path = "/modules/inventory/InventoryPanel.js"
_ma_anon = status("GET", _ma_path)
_ma_anon_handler = list(SPY["handler"])
check("46b. файлы модулей (/modules/*) — только после входа: без входа 401 и обработчик не вызван, "
      "любая роль — 200, при выключенной защите — 200",
      pol("GET", "/modules/{module_id}/{asset_path:path}").enforced_access is EA.SESSION_ONLY
      and _ma_anon == 401 and not _ma_anon_handler
      and all(status("GET", _ma_path, r) == 200 for r in ("observer", "assembler", "operator", "admin"))
      and status("GET", _ma_path, None, security=False) == 200
      and status("GET", "/assets/app.js") == 200)
check("47. WebRTC требует права view",
      pol("POST", "/api/printer/{pid}/webrtc").required_capability == "view")
# Все восемь особых маршрутов были доступны observer до правки. Ни один из них не стал
# доступнее: шесть сузились до admin, один до любой сессии, один до явного права view.
SPECIAL_KEYS = (("POST", "/api/diagnostics/bambu-sniff/start"),
                ("POST", "/api/diagnostics/bambu-sniff/stop"),
                ("POST", "/api/diagnostics/verbose"), ("POST", "/api/diagnostics/monitor"),
                ("POST", "/api/diagnostics/clear"), ("POST", "/api/diagnostics/client"),
                ("POST", "/api/printer/{pid}/webrtc"), ("GET", "/api/logs/download"))
ADMIN_ONLY_DIAG = ["/api/diagnostics/bambu-sniff/start", "/api/diagnostics/bambu-sniff/stop",
                   "/api/diagnostics/verbose", "/api/diagnostics/monitor",
                   "/api/diagnostics/clear"]
check("48. ни одно особое решение не расширяет доступ (все 8 были доступны observer)",
      all(legacy_gate(m, p, "observer") == "ALLOW" for m, p in SPECIAL_KEYS)
      and all(pol(m, p).enforced_access is not EA.PUBLIC for m, p in SPECIAL_KEYS)
      and all(status("POST", p, "observer") == 403 for p in ADMIN_ONLY_DIAG)
      and all(status("POST", p, "admin") == 200 for p in ADMIN_ONLY_DIAG))


# ════════════════════════════════════════════════════════════════════════════
section("выключенная авторизация (пункты 49-55)")

check("49. обычный рабочий процесс при AUTH OFF прежний",
      all(status(m, p, None, security=False) == 200 for m, p in (
          ("GET", "/api/printers"), ("POST", "/api/part/print"),
          ("POST", "/api/printers/save"), ("GET", "/api/logs/download"))))
check("50. system-admin при AUTH OFF по-прежнему решает сам (loopback)",
      rac.decide(pol("POST", "/api/restart"), ctx(None, session=False, security=False)).outcome
      is AD.DEFER_TO_HANDLER)
check("51. callback при AUTH OFF по-прежнему требует ключ и loopback",
      rac.decide(pol("POST", "/api/slicer-hook"), ctx(None, session=False, security=False)).outcome
      is AD.DEFER_TO_HANDLER)
check("52. _require_admin при AUTH OFF сохраняет прежний отказ",
      rac.decide(pol("GET", "/api/auth/users"), ctx(None, session=False, security=False)).outcome
      is AD.DEFER_TO_HANDLER)
check("53. маршруты модулей при AUTH OFF работают как раньше",
      status("POST", "/api/mod/inventory/item", None, security=False) == 200)
check("54. WebSocket HTTP-гейтом не обслуживается (решает собственный движок)",
      reg.core_http_policy("GET", "/ws") is None
      and rac.decide(CORE_WS[0], ctx(None, session=False, security=False)).outcome
      is AD.DEFER_TO_WEBSOCKET)
check("55. LAN/bind/config этой правкой не меняются",
      "lan_access_enabled" not in cur_gate and "_read_config" not in cur_gate
      and "_write_config" not in cur_gate)


# ════════════════════════════════════════════════════════════════════════════
section("порядок побочных эффектов (пункты 56-64)")

reset_spy()
r_deny = call("POST", "/api/printer/P1/cmd", "observer",
              body=json.dumps({"payload": SENTINEL}).encode())
check("56. отказ произошёл до обработчика", r_deny["status"] == 403 and not SPY["handler"])
check("57. отказ произошёл до чтения тела", not SPY["body"])
check("58. отказ произошёл до разбора multipart", not SPY["body"])
check("59. отказ произошёл до обращения к БД", not SPY["db"])
check("60. отказ произошёл до обращения к файловой системе", not SPY["fs"])
check("61. отказ произошёл до адаптера принтера", not SPY["printer"])
check("62. отказ произошёл до очереди и recovery", not SPY["queue"])
check("63. отказ произошёл до подпроцессов", not SPY["subprocess"])
check("64. ответ об ошибке не отражает тело запроса",
      SENTINEL.encode() not in r_deny["body"])


# ════════════════════════════════════════════════════════════════════════════
section("краевые случаи сопоставления (пункты 65-74)")

check("65. параметры пути: доступ решается по шаблону, а не по значению",
      status("POST", "/api/printer/ANY-ID-42/cmd", "observer") == 403
      and status("POST", "/api/printer/ANY-ID-42/cmd", "operator") == 200)
check("66. несовпадение метода даёт 405, а не ошибку доступа",
      status("DELETE", "/api/printers", "observer") == 405)
check("67. закодированный путь не обходит проверку",
      status("POST", "/api/printer/%2E%2E%2Fadmin/cmd", "observer") == 403)
check("68. хвостовой слэш не обходит проверку (редирект на канонический путь)",
      status("GET", "/api/printers/", "observer") in (200, 307)
      and status("POST", "/api/printer/P1/cmd/", "observer") in (307, 403, 404, 405))
check("69. двойной слэш не обходит проверку",
      status("GET", "//api/printers", "observer") in (307, 404))
check("70. регистр пути значим: /API/PRINTERS не совпадает",
      status("GET", "/API/PRINTERS", "observer") == 404)
check("71. статический маршрут остаётся публичным",
      status("GET", "/assets/inventory/Panel.js") == 200
      and status("GET", "/version") == 200)
check("72. HEAD не открывает маршрут: на APIRoute штатный 405, на маршруте фреймворка "
      "наследует политику GET",
      status("HEAD", "/api/logs/download", "observer") == 405
      and status("HEAD", "/api/logs/download", "admin") == 405
      and status("HEAD", "/openapi.json") == 401
      and status("HEAD", "/openapi.json", "observer") != 401)
check("73. OPTIONS сохраняет штатное поведение фреймворка",
      status("OPTIONS", "/api/printers", "observer") == 405)
check("74. неизвестный URL остаётся 404 и при отсутствии сессии",
      status("GET", "/api/no-such-thing") == 404)


# ════════════════════════════════════════════════════════════════════════════
section("регрессии (пункты 75-86)")

check("75. реестр: baseline 233/188/45/2 (2.798 +local-recovery; 2.823 +5 printer-files; 2.825 +select-for-print; 2.827 +4 config-backup; 2.831 +2 printer-sort-mode; 2.833 +2 klipper-prestart; 2.870 +камера без перекодирования; 2.879 +камера по WebSocket); 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы",
      reg.registry_counts()["total"] == 260 and reg.registry_counts()["core"] == 209   #; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and reg.registry_counts()["modules"] == 51 and reg.registry_counts()["websocket"] == 2)

_par_ast = ast.parse(PAR) if PAR else None
# add_route исключён намеренно: Alpha 2.785 переводит регистрацию маршрутов модулей на
# обязательный policy_id и атомарную проверку. Границы доступа ЯДРА при этом не тронуты.
# ws_ep исключена намеренно: Alpha 2.786 переводит WebSocket на явную авторизацию и
# периодическую перепроверку доступа. Границы HTTP при этом не тронуты.
# proxy_upload исключён намеренно: Alpha 2.788 ставит ему ту же границу callback, что у
# OctoPrint-близнеца /api/files/local (2.781). Сам движок границы (_require_slicer_callback)
# при этом НЕ менялся — он остаётся в списке ниже и продолжает сверяться с эталоном.
# p_cmd исключён намеренно: Alpha 2.825 добавляет в ветку start_print РАЗБОР непрозрачной
# ссылки file_ref (resolve + перепроверка файла на устройстве, val подменяется сервером);
# граница operate и весь прежний путь без file_ref не тронуты — см. 76c ниже.
UNCHANGED = ("_route_perm", "_has_perm", "_require_admin", "_require_system_admin",
             "_require_slicer_callback", "_session_user", "_req_role",
             "s_hook")
#  Без эталона список расхождений не вычисляется (None): пустой список без эталона был бы
#  ложной зеленью.
_diffs = ([f for f in UNCHANGED if fn_src(_par_ast, f) != fn_src(SRC_AST, f)]
          if _par_ast else None)
hcheck("76-82. функции границ и обработчиков не изменены: расхождений %s (%s)"
       % ((len(_diffs), ", ".join(_diffs) or "нет") if _diffs is not None else ("?", "эталона нет")),
       lambda: _diffs == [])
_pc_par = (fn_src(_par_ast, "p_cmd") if _par_ast else "") or ""
_pc_cur = fn_src(SRC_AST, "p_cmd") or ""
hcheck("76c. p_cmd изменён НАМЕРЕННО (2.825): +resolve file_ref в start_print; прежний путь сохранён",
       lambda: bool(_pc_par) and _pc_cur != _pc_par
       and "_pf_resolve_print_target" not in _pc_par
       and _pc_cur.count("_pf_resolve_print_target") == 1
       and "file_ref" not in _pc_par
       and all(t in _pc_cur for t in ("_hold_block(pid)", "_c1_load_plate_compat",
                                     "_send_mgr.begin_direct", "_printer_cmd_policy.parse_command")))
_pu_par = (fn_src(_par_ast, "proxy_upload") if _par_ast else "") or ""
_pu_cur = fn_src(SRC_AST, "proxy_upload") or ""
# Сигнатуру берём первой строкой def, а не поиском по телу: слова "File(...)" законно
# встречаются в пояснении к коду, и подстрочный поиск дал бы ложный результат.
def _sig(src):
    for ln in src.splitlines():
        if ln.lstrip().startswith(("def ", "async def ")):
            return ln.strip()
    return ""
hcheck("76b. proxy_upload изменён НАМЕРЕННО: появилась граница callback, разбор формы стал ручным",
       lambda: bool(_pu_par) and _pu_cur != _pu_par
       and "_require_slicer_callback" not in _pu_par
       and "_require_slicer_callback" in _pu_cur
       and "File(...)" in _sig(_pu_par) and "File(...)" not in _sig(_pu_cur)
       and "request: Request" in _sig(_pu_cur))
hcheck("83. _auth_gate изменена НАМЕРЕННО и только она",
       lambda: bool(PAR) and fn_src(_par_ast, "_auth_gate") != cur_gate)
check("84. декораторы маршрутов не получили dependencies",
      "dependencies=" not in SRC)
check("85. модули не тронуты: состав и версии прежние",
      sorted(set(p.module_id for p in MOD)) == ["cost", "inventory", "messengers", "quality"]
      and len(MOD) == 51)
check("86. исторические поля current_* сохранены",
      all(p.current_permission == legacy_route_perm(
          "GET" if p.method == "WS" else p.method, p.path) for p in reg.ALL_POLICIES))

check("S1. метка-ловушка не попала ни в обработчик, ни в журнал, ни в аудит",
      not any(SENTINEL in str(v) for v in SPY.values()))
check("S2. server.py в тесте не импортировался", "server" not in sys.modules)


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
