# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.796 — БЕЗОПАСНЫЙ OFFLINE-ТЕСТ runtime-привязки LAN (замена теста Alpha 2.720).
#
#  ЧТО ПРОВЕРЯЕТ. Что server.py ДЕЙСТВИТЕЛЬНО подключён к чистой политике
#  app/lan_access_policy.py (Alpha 2.787): решение bind берётся из helper, 127.0.0.1 при
#  эффективном OFF, 0.0.0.0 только при эффективном ON, UDP discovery (порт 8021) стартует
#  только по discovery_enabled, HTTP-порт 8000, proxy-заголовки не влияют на startup bind,
#  порядок side effects (решение ДО bind, отказ ДО discovery), предпосылки API 2.787.
#  Методы: AST/разбор исходника + изолированное исполнение извлечённых функций
#  на конфиге-словаре и sqlite в памяти. server.py НЕ импортируется и НЕ запускается.
#
#  ПОЧЕМУ ЗАМЕНА. Старый тест (Alpha 2.720) импортировал production server.py через
#  exec_module (mutex одиночного экземпляра при работающем Farm Manager завершал процесс
#  через sys.exit(0) ДО первой проверки — ложнозелёный ноль, доказано 2026-07-21) и
#  ОТКРЫВАЛ НАСТОЯЩИЕ СОКЕТЫ: TCP-listener в том числе на 0.0.0.0 (эфемерный порт),
#  который на время прогона был достижим из локальной сети. Проверялась при этом только
#  legacy-ветка _lan_bind_host(явный аргумент) — решение 2.787 (AUTH/admin) не проверялось.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется; uvicorn не запускается; git не вызывается.
#   * Ни одного сокета, потока, подпроцесса — ловушки-шпионы это ДОКАЗЫВАЮТ.
#   * Рабочие config.json / БД / DATA_DIR не читаются и не пишутся (шпион open).
#   * Преждевременный выход (sys.exit(0) до проверок) превращается в exit 1 (atexit-страж).
#
#  Запуск:  python tools/test_lan_access_runtime.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import atexit
import builtins
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

# ── Страж преждевременного выхода (пресекает ложнозелёный exit 0 до проверок) ──
_COMPLETED = {"done": False}

def _premature_exit_guard():
    if not _COMPLETED["done"]:
        try:
            print("FAIL — тест завершился до выполнения проверок (ложнозелёный сценарий пресечён)")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)

atexit.register(_premature_exit_guard)

# ── Ловушки-шпионы побочных эффектов ────────────────────────────────────────
_SOCKETS = []
_THREADS = []
_PROCS = []
_OPENS = []

class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
        raise AssertionError("offline-тест: создание сокета запрещено")

socket.socket = _TrapSocket

def _trap_thread_start(self, *a, **k):
    _THREADS.append(getattr(self, "name", "?"))
    raise AssertionError("offline-тест: запуск потока запрещён")

threading.Thread.start = _trap_thread_start

def _trap_proc(*a, **k):
    _PROCS.append(a)
    raise AssertionError("offline-тест: подпроцессы (в т.ч. git) запрещены")

subprocess.Popen = _trap_proc
subprocess.run = _trap_proc
subprocess.call = _trap_proc
subprocess.check_output = _trap_proc

_ORIG_OPEN = builtins.open

def _spy_open(file, mode="r", *a, **k):
    _OPENS.append((str(file), str(mode)))
    return _ORIG_OPEN(file, mode, *a, **k)

builtins.open = _spy_open

# ── Оснастка проверок ────────────────────────────────────────────────────────
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

# Метка-ловушка: только в оснастке этого теста.
SENTINEL = "LAN_OFFLINE_TEST_SENTINEL_2_796"

from app import lan_access_policy as L   # noqa: E402  (чистый stdlib-модуль, НЕ server.py)

AC, BS = L.AdminCheck, L.BindScope
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
POL_SRC = open(os.path.join(REPO, "app", "lan_access_policy.py"), encoding="utf-8").read()
SI_SRC = open(os.path.join(REPO, "app", "single_instance.py"), encoding="utf-8").read()
ORCH_SRC = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
OWN_SRC = open(os.path.abspath(__file__), encoding="utf-8").read()
AST_T = ast.parse(SRC)


def fn_src(name):
    for n in ast.walk(AST_T):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


def fn_body_src(name):
    """Исходник ТЕЛА функции без докстроки (докстроки поясняют политику словами
    и могут упоминать адреса — телу функции литералы хостов запрещены)."""
    for n in ast.walk(AST_T):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            body = list(n.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body = body[1:]
            return "\n".join(ast.unparse(s) for s in body)
    return ""


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.796: offline-тест runtime-привязки LAN (без импорта server.py) ===")
section("characterization: почему старый runtime-тест Alpha 2.720 был непригоден")

# Дословные выдержки из tools/test_lan_access_runtime.py состояния commit 8e44db9.
OLD_RUNTIME_SHA256 = "35158a64a88e50f64dda8e47ca992b5aa87669d0cb18a35a4c3358bf72292152"
OLD_RT_IMPORT_FIXTURE = (
    'spec = importlib.util.spec_from_file_location("fm_server_lan_rt", os.path.join(REPO, "server.py"))\n'
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)   # используем НАСТОЯЩИЙ helper выбора host\n"
)
OLD_RT_SOCKET_FIXTURE = (
    "    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
    "    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "    srv.bind((host, port)); srv.listen(8); srv.settimeout(0.3)\n"
)
OLD_RT_IMPORT_LINE = 46      # строка exec_module в старом файле (8e44db9)
OLD_RT_FIRST_CHECK_LINE = 86  # первая проверка check(...) в старом файле (8e44db9)

check("C1. старый runtime-тест загружал production server.py на уровне модуля (fixture 8e44db9)",
      "server.py" in OLD_RT_IMPORT_FIXTURE and "exec_module" in OLD_RT_IMPORT_FIXTURE)
check("C2. импорт стоял ДО первой проверки: при занятом mutex exit 0 без единой проверки",
      OLD_RT_IMPORT_LINE < OLD_RT_FIRST_CHECK_LINE
      and "_si_code = 0" in SRC and "sys.exit(_si_code)" in SRC)
check("C3. старый тест открывал настоящие TCP-сокеты (bind/listen, в т.ч. на 0.0.0.0)",
      "srv.bind((host, port))" in OLD_RT_SOCKET_FIXTURE and "srv.listen(8)" in OLD_RT_SOCKET_FIXTURE)
check("C4. отпечаток старого файла зафиксирован (SHA-256, состояние 8e44db9)",
      len(OLD_RUNTIME_SHA256) == 64 and all(c in "0123456789abcdef" for c in OLD_RUNTIME_SHA256))

_own_ast = ast.parse(OWN_SRC)
_imports_server = any(
    (isinstance(n, ast.Import) and any(a.name == "server" for a in n.names))
    or (isinstance(n, ast.ImportFrom) and (n.module or "") == "server")
    for n in ast.walk(_own_ast) if isinstance(n, (ast.Import, ast.ImportFrom)))
_calls_exec_module = any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "exec_module"
    for n in ast.walk(_own_ast))
_calls_spec_load = any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "spec_from_file_location"
    for n in ast.walk(_own_ast))
check("C5. этот тест не импортирует server.py и не использует spec/exec_module-загрузку",
      not _imports_server and not _calls_exec_module and not _calls_spec_load)
check("C6. server.py и uvicorn не появились в sys.modules",
      "server" not in sys.modules and "uvicorn" not in sys.modules
      and not any(getattr(m, "__file__", "") and os.path.normcase(str(getattr(m, "__file__", "")))
                  == os.path.normcase(os.path.join(REPO, "server.py"))
                  for m in list(sys.modules.values())))


# ════════════════════════════════════════════════════════════════════════════
section("wiring: server.py использует чистый LAN-helper (AST)")

_imports_policy = any(
    isinstance(n, ast.ImportFrom) and (n.module or "") == "app"
    and any(a.name == "lan_access_policy" and a.asname == "_lan_policy" for a in n.names)
    for n in ast.walk(AST_T))
check("W1. server.py импортирует app.lan_access_policy как _lan_policy",
      _imports_policy)

_eff = fn_src("_lan_effective_decision")
check("W2. _lan_effective_decision строит LanRequest и вызывает _lan_policy.decide",
      "_lan_policy.decide" in _eff and "_lan_policy.LanRequest" in _eff
      and "auth_enabled=bool(_SECURITY_ENABLED)" in _eff
      and "admin_check=" in _eff and "config_valid=" in _eff)
check("W3. решение — единственный источник: _lan_bind_host без аргумента берёт bind из decide",
      "_lan_effective_decision().bind_host" in fn_src("_lan_bind_host"))
check("W4. _lan_bind_host не содержит собственной таблицы хостов (только константы политики)",
      "_lan_policy.NETWORK_HOST" in fn_body_src("_lan_bind_host")
      and "_lan_policy.LOOPBACK_HOST" in fn_body_src("_lan_bind_host")
      and "0.0.0.0" not in fn_body_src("_lan_bind_host")
      and "127.0.0.1" not in fn_body_src("_lan_bind_host"))
check("W5. во всём server.py нет ни одной строковой константы '0.0.0.0' (дублирующей таблицы нет)",
      not any(isinstance(n, ast.Constant) and n.value == "0.0.0.0" for n in ast.walk(AST_T)))
check("W6. строгое чтение настройки: _lan_access_enabled принимает только настоящий True, ошибка -> False",
      "is True" in fn_src("_lan_access_enabled") and "return False" in fn_src("_lan_access_enabled"))
check("W7. проверка админа отдаёт только факт PRESENT/ABSENT/UNKNOWN (fail-closed при ошибке)",
      "role='admin' AND is_active=1" in fn_src("_enabled_admin_check").replace('"', "'")
      and "_lan_policy.AdminCheck.UNKNOWN" in fn_src("_enabled_admin_check"))

# Стартовое окно: единственный блок if __name__ == "__main__".
_main_if = None
for _n in AST_T.body:
    if isinstance(_n, ast.If) and "__name__" in ast.dump(_n.test) and "__main__" in ast.dump(_n.test):
        _main_if = _n
MAIN_SEG = ast.get_source_segment(SRC, _main_if) or ""
check("W8. стартовый блок найден и решение считается чистым helper ДО выбора bind",
      _main_if is not None
      and "_LAN_DECISION = _lan_effective_decision()" in MAIN_SEG
      and "_LAN_ACCESS_APPLIED = _LAN_DECISION.effective_lan_enabled" in MAIN_SEG
      and "_bind_host = _LAN_DECISION.bind_host" in MAIN_SEG)
check("W9. сырой флаг конфигурации для bind больше не используется (нет обходной таблицы)",
      "_LAN_ACCESS_APPLIED = _lan_access_enabled()" not in MAIN_SEG
      and "_lan_bind_host(_LAN_ACCESS_APPLIED)" not in MAIN_SEG)

# UDP discovery: единственный запуск и только под гейтом решения.
_disc_gates = [n for n in ast.walk(AST_T)
               if isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
               and n.test.attr == "discovery_enabled"
               and isinstance(n.test.value, ast.Name) and n.test.value.id == "_LAN_DECISION"]

def _beacon_threads(tree):
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "Thread":
            for kw in n.keywords:
                if kw.arg == "target" and isinstance(kw.value, ast.Name) and kw.value.id == "_discovery_beacon":
                    out.append(n)
    return out

_all_beacons = _beacon_threads(AST_T)
_gated_beacons = []
for _g in _disc_gates:
    for _stmt in _g.body:
        _gated_beacons.extend(_beacon_threads(_stmt))
_beacon_port_ok = False
if _all_beacons:
    for _kw in _all_beacons[0].keywords:
        if _kw.arg == "args" and isinstance(_kw.value, ast.Tuple) and len(_kw.value.elts) == 1:
            _e = _kw.value.elts[0]
            # Alpha 2.806: beacon объявляет ФАКТИЧЕСКИ активный порт (_ACTIVE_PORT), не жёсткий 8000.
            _beacon_port_ok = isinstance(_e, ast.Name) and _e.id == "_ACTIVE_PORT"
check("W10. запуск discovery-beacon ровно один и он ВНУТРИ if _LAN_DECISION.discovery_enabled",
      len(_disc_gates) == 1 and len(_all_beacons) == 1 and len(_gated_beacons) == 1)
check("W11. beacon объявляет фактически активный порт (args=(_ACTIVE_PORT,))", _beacon_port_ok)

_dp = [n for n in AST_T.body if isinstance(n, ast.Assign)
       and any(isinstance(t, ast.Name) and t.id == "DISCOVERY_PORT" for t in n.targets)]
check("W12. порт UDP discovery остаётся 8021",
      len(_dp) == 1 and isinstance(_dp[0].value, ast.Constant) and _dp[0].value.value == 8021
      and 's.bind(("", DISCOVERY_PORT))' in fn_src("_discovery_beacon").replace("'", '"'))

# Alpha 2.806: uvicorn получает УЖЕ ПОДНЯТЫЙ нами сокет — uvicorn.Server(uvicorn.Config(...)).run(sockets=..).
# Ищем единственный uvicorn.Config(...) с host=_bind_host, port=_ACTIVE_PORT.
_uc = [n for n in ast.walk(AST_T) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
       and n.func.attr == "Config" and isinstance(n.func.value, ast.Name) and n.func.value.id == "uvicorn"]
_uc_ok = False
if len(_uc) == 1:
    _host = _port = None
    for _kw in _uc[0].keywords:
        if _kw.arg == "host":
            _host = _kw.value
        if _kw.arg == "port":
            _port = _kw.value
    _uc_ok = (isinstance(_host, ast.Name) and _host.id == "_bind_host"
              and isinstance(_port, ast.Name) and _port.id == "_ACTIVE_PORT")
# uvicorn.run(...) больше нет; вместо него Server(...).run(sockets=[_listen_sock]) на подготовленном сокете.
_no_plain_run = not any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
    and isinstance(n.func.value, ast.Name) and n.func.value.id == "uvicorn" for n in ast.walk(AST_T))
check("W13. единственный uvicorn.Config: host=_bind_host (из решения), port=_ACTIVE_PORT; "
      "сокет поднят нами (Server.run(sockets=...))",
      len(_uc) == 1 and _uc_ok and _no_plain_run
      and "_uv.run(sockets=[_listen_sock])" in MAIN_SEG)

check("W14. proxy-заголовки не участвуют в startup bind и в решении "
      "(нет forwarded/x-real-ip в стартовом блоке и LAN-функциях)",
      all("forward" not in blob.lower() and "x-real" not in blob.lower()
          for blob in (MAIN_SEG, _eff, fn_src("_lan_bind_host"),
                       fn_src("_lan_access_enabled"), fn_src("_enabled_admin_check"), POL_SRC)))

_eff_def = next(n for n in ast.walk(AST_T)
                if isinstance(n, ast.FunctionDef) and n.name == "_lan_effective_decision")
check("W15. _lan_effective_decision не принимает ни запроса, ни заголовков (0 параметров)",
      not _eff_def.args.args and not _eff_def.args.kwonlyargs
      and _eff_def.args.vararg is None and _eff_def.args.kwarg is None)


# ════════════════════════════════════════════════════════════════════════════
section("side-effect order: решение до bind, отказ до discovery, отказ ничего не пишет")

_i_decision = MAIN_SEG.find("_LAN_DECISION = _lan_effective_decision()")
_i_gate = MAIN_SEG.find("if _LAN_DECISION.discovery_enabled:")
_i_uvicorn = MAIN_SEG.find("_uv.run(sockets=[_listen_sock])")   # Alpha 2.806: bind поднятого сокета
check("O1. порядок старта: решение -> гейт discovery -> bind сервера",
      0 <= _i_decision < _i_gate < _i_uvicorn)
# Alpha 2.806: LAN-ОТКАЗ по-прежнему НЕ пишет config. Порт-блок пишет config АТОМАРНО (commit/rollback)
# — это отдельный легитимный контракт; убеждаемся, что запись только атомарная (_write_config_atomic),
# а неатомарного _write_config( в стартовом блоке нет, и ветка LAN-отказа config не трогает.
_lan_refuse = MAIN_SEG[MAIN_SEG.find("if not _LAN_ACCESS_APPLIED and _lan_access_enabled():"):_i_gate]
check("O2. LAN-отказ не пишет config; порт-запись только атомарная",
      "_write_config(" not in MAIN_SEG
      and "_write_config" not in _lan_refuse
      and "_write_config_atomic" in MAIN_SEG)
check("O3. отказ не создаёт пользователей и сессии (в стартовом блоке нет INSERT/UPDATE users)",
      "INSERT INTO" not in MAIN_SEG and "UPDATE users" not in MAIN_SEG
      and "_new_session" not in MAIN_SEG)
check("O4. firewall-правило добавляется только в разрешающей ветке гейта discovery",
      MAIN_SEG.count("_ensure_firewall_rule") == 1
      and _i_gate < MAIN_SEG.find("_ensure_firewall_rule") < _i_uvicorn)


# ════════════════════════════════════════════════════════════════════════════
section("предпосылки API Alpha 2.787 остаются подключены")

_set = fn_src("set_network")
_get = fn_src("g_network")
check("A1. POST /api/network за границей system-admin",
      "_require_system_admin" in _set and _set.find("_require_system_admin") < _set.find("_json_body"))
check("A2. включение проверяет can_enable ДО записи конфигурации (отказ 409 с причиной)",
      "can_enable" in _set and "_write_config" in _set
      and _set.find("can_enable") < _set.find("_write_config") and "409" in _set)
check("A3. настройка принимает строго boolean", "isinstance(v, bool)" in _set)
check("A4. статус различает запрошено/эффективно/фактический bind и отдаёт причину",
      all(k in _get for k in ("requested_enabled", "effective_enabled",
                              "current_bind_scope", "blocked_reason", "restart_required"))
      and "_lan_effective_decision" in _get)
check("A5. отключение авторизации заблокировано при сетевом bind (auth_disable_blocked подключён)",
      "auth_disable_blocked" in fn_src("auth_disable"))


# ════════════════════════════════════════════════════════════════════════════
section("изолированное исполнение реального кода выбора bind (без импорта server.py)")

DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
_USERS_DDL = "CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER)"
DB.execute(_USERS_DDL)
DB.commit()


class _Lock(object):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Log(object):
    def __init__(self):
        self.lines = []

    def _r(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = _r


CFG = {}
CFG_RAISE = {"on": False}
WRITES = []
LOG = _Log()


def _read_config_stub():
    if CFG_RAISE["on"]:
        raise RuntimeError("config unreadable")
    return dict(CFG)


NS = {"_lan_policy": L, "log": LOG, "lock_p": _Lock(), "conn_p": DB,
      "_read_config": _read_config_stub,
      "_write_config": lambda c: WRITES.append(dict(c)),
      "_exc_brief": lambda: "err", "_SECURITY_ENABLED": False}
for _fname in ("_lan_access_enabled", "_enabled_admin_check", "_lan_effective_decision", "_lan_bind_host"):
    exec(compile(fn_src(_fname), "<server-lan>", "exec"), NS)
lan_enabled = NS["_lan_access_enabled"]
admin_check = NS["_enabled_admin_check"]
effective = NS["_lan_effective_decision"]
bind_host = NS["_lan_bind_host"]

_ABSENT = object()


def setup(cfg_lan=_ABSENT, auth=True, admins=(), raise_cfg=False, extra=None):
    CFG.clear()
    if cfg_lan is not _ABSENT:
        CFG["lan_access_enabled"] = cfg_lan
    if extra:
        CFG.update(extra)
    CFG_RAISE["on"] = raise_cfg
    WRITES[:] = []
    LOG.lines[:] = []
    DB.execute("DELETE FROM users")
    for i, (role, active) in enumerate(admins):
        DB.execute("INSERT INTO users (id,username,role,is_active) VALUES (?,?,?,?)",
                   ("u%d" % i, "n%d" % i, role, active))
    DB.commit()
    NS["_SECURITY_ENABLED"] = auth


ADMIN_OK = (("admin", 1),)

setup(auth=False)
check("R1. ключа нет + AUTH OFF -> loopback без discovery (default OFF)",
      bind_host() == "127.0.0.1" and effective().discovery_enabled is False
      and effective().reason == L.REASON_LAN_DISABLED)
setup(True, auth=False)
check("R2. setting ON + AUTH OFF -> loopback, discovery OFF (reason auth_required)",
      bind_host() == "127.0.0.1" and effective().discovery_enabled is False
      and effective().reason == L.REASON_AUTH_REQUIRED)
setup(False, auth=True, admins=ADMIN_OK)
check("R3. setting OFF + AUTH ON + admin -> loopback (reason lan_disabled)",
      bind_host() == "127.0.0.1" and effective().reason == L.REASON_LAN_DISABLED)
setup(True, auth=True, admins=())
check("R4. setting ON + AUTH ON без админа -> loopback (reason enabled_admin_required)",
      bind_host() == "127.0.0.1" and effective().reason == L.REASON_ADMIN_REQUIRED
      and effective().discovery_enabled is False)
setup(True, auth=True, admins=ADMIN_OK)
check("R5. setting ON + AUTH ON + активный админ -> 0.0.0.0 и discovery ON (единственный allow)",
      bind_host() == "0.0.0.0" and effective().effective_lan_enabled is True
      and effective().discovery_enabled is True and effective().reason == L.REASON_LAN_ALLOWED)
setup(True, auth=True, admins=(("admin", 0),))
check("R6. отключённый админ не считается enabled admin -> loopback",
      bind_host() == "127.0.0.1" and effective().reason == L.REASON_ADMIN_REQUIRED)
setup(True, auth=True, admins=(("operator", 1), ("observer", 1)))
check("R7. без единого админа (только другие роли) -> loopback",
      bind_host() == "127.0.0.1" and effective().reason == L.REASON_ADMIN_REQUIRED)
setup(True, auth=True, admins=(("operator", 1), ("admin", 0), ("admin", 1)))
check("R8. один активный админ среди прочих -> сеть разрешена",
      bind_host() == "0.0.0.0")
setup(True, auth=True, admins=ADMIN_OK)
DB.execute("DROP TABLE users")
DB.commit()
check("R9. ошибка чтения БД (нет таблицы users) -> UNKNOWN -> loopback (admin_check_failed)",
      admin_check() is AC.UNKNOWN and bind_host() == "127.0.0.1"
      and effective().reason == L.REASON_ADMIN_CHECK_FAILED)
DB.execute(_USERS_DDL)
DB.commit()
setup(True, auth=True, admins=ADMIN_OK, raise_cfg=True)
check("R10. ошибка чтения config -> loopback (reason config_invalid), настройка False",
      bind_host() == "127.0.0.1" and effective().reason == L.REASON_CONFIG_INVALID
      and lan_enabled() is False)
_malformed_ok = True
for _v in ("true", "false", 1, 0, 1.0, None, [], {}):
    setup(_v, auth=True, admins=ADMIN_OK)
    if lan_enabled() is not False or bind_host() != "127.0.0.1":
        _malformed_ok = False
check("R11. malformed значения настройки ('true'/1/0/null/список/словарь) -> False и loopback",
      _malformed_ok)
setup(True, auth=True, admins=ADMIN_OK)
check("R12. legacy-ветка с явным аргументом сохранена: False->127.0.0.1, True->0.0.0.0",
      bind_host(False) == "127.0.0.1" and bind_host(True) == "0.0.0.0")
setup(SENTINEL, auth=True, admins=ADMIN_OK)
check("R13. sentinel как значение настройки -> fail-closed loopback, sentinel не утёк в reason/лог",
      bind_host() == "127.0.0.1" and SENTINEL not in effective().reason
      and not any(SENTINEL in ln for ln in LOG.lines))
setup(True, auth=False, extra={"X-Forwarded-Proto": "https", "X-Forwarded-For": "10.0.0.99",
                               "Forwarded": "for=10.0.0.99;proto=https"})
_d_proxy = effective()
setup(True, auth=False)
_d_plain = effective()
check("R14. proxy-подобные ключи конфигурации не влияют на решение (blocked в обоих случаях)",
      _d_proxy == _d_plain and _d_proxy.bind_scope is BS.LOOPBACK)
setup(True, auth=True, admins=ADMIN_OK)
_rows_before = [tuple(r) for r in DB.execute("SELECT id,username,role,is_active FROM users ORDER BY id")]
_dec = effective()
_rows_after = [tuple(r) for r in DB.execute("SELECT id,username,role,is_active FROM users ORDER BY id")]
check("R15. вычисление решения ничего не меняет: БД и конфиг нетронуты, записей нет",
      _rows_before == _rows_after and not WRITES and _dec.effective_lan_enabled is True)


# ════════════════════════════════════════════════════════════════════════════
section("защиты вокруг LAN не ослаблены")

check("G1. single-instance guard на месте: ранний захват mutex на уровне модуля",
      "_SINGLE_INSTANCE = _single_instance.acquire(" in SRC
      and "if not _SINGLE_INSTANCE.ok:" in SRC and "sys.exit(_si_code)" in SRC
      and SRC.index("_single_instance.acquire(") < SRC.index("def _lan_access_enabled"))
check("G2. имя mutex не менялось (иначе старая и новая сборки запустятся одновременно)",
      r"Local\3DIWELL_Farm_Manager_SingleInstance_v1" in SI_SRC)
check("G3. предохранитель автоотправки на месте: DISPATCH_ENABLED/TRANSPORT_ENABLED = False",
      re.search(r"^DISPATCH_ENABLED = False\s*$", ORCH_SRC, re.M) is not None
      and re.search(r"^TRANSPORT_ENABLED = False\s*$", ORCH_SRC, re.M) is not None)


# ════════════════════════════════════════════════════════════════════════════
section("метка-ловушка и отсутствие побочных эффектов")

check("T1. sentinel не встречается в production-исходниках",
      SENTINEL not in SRC and SENTINEL not in POL_SRC
      and SENTINEL not in SI_SRC and SENTINEL not in ORCH_SRC)
check("T2. sentinel определён ровно один раз и только в оснастке этого теста",
      OWN_SRC.count(SENTINEL) == 1)
check("T3. за весь прогон не создано ни одного сокета (bind 8000/8021 невозможен)",
      len(_SOCKETS) == 0)
check("T4. за весь прогон не запущено ни одного потока (UDP discovery не стартовал)",
      len(_THREADS) == 0)
check("T5. за весь прогон не запущено ни одного подпроцесса (git не вызывался)",
      len(_PROCS) == 0)
_writes_fs = [(p, m) for (p, m) in _OPENS if any(c in m for c in "wax+")]
check("T6. ни одной записи в файлы (config/DB/логи/_incoming нетронуты)", not _writes_fs)
_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", "?????"), "3DIWELL")
check("T7. рабочий config.json / DATA_DIR / _incoming не читались вовсе",
      not any("config.json" in p.lower() or "_incoming" in p.lower()
              or os.path.normcase(p).startswith(os.path.normcase(_data_dir))
              for (p, _m) in _OPENS))
_expected_reads = {os.path.normcase(os.path.join(REPO, "server.py")),
                   os.path.normcase(os.path.join(REPO, "app", "lan_access_policy.py")),
                   os.path.normcase(os.path.join(REPO, "app", "single_instance.py")),
                   os.path.normcase(os.path.join(REPO, "app", "project_orchestrator.py")),
                   os.path.normcase(os.path.abspath(__file__))}
check("T8. читались только объявленные исходники (server.py, политика, guard, orchestrator, сам тест)",
      set(os.path.normcase(p) for (p, _m) in _OPENS) <= _expected_reads)


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _COMPLETED["done"] = True
    sys.exit(1)
print("PASS: runtime-привязка LAN (offline) — все %d проверок пройдены, server.py не импортировался" % _total)
_COMPLETED["done"] = True
sys.exit(0)
