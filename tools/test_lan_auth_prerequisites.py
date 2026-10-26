# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.787 — закрытие S-1: локальная сеть только при авторизации и активном админе.
#
#  ЧАСТЬ 1 (ХАРАКТЕРИЗАЦИЯ). Как выбирался bind ДО правки, то есть в Alpha 2.786:
#  отсутствие ключа означало LAN ON, мусор любого вида — тоже LAN ON, а сам bind
#  выводился ПРЯМО из флага конфигурации, без проверки авторизации и администратора.
#  Историческое состояние берётся из РОДИТЕЛЬСКОГО коммита через git show.
#
#  ЧАСТЬ 2+. Новая модель: чистая политика, строгий разбор, проверка предпосылок,
#  решение при старте, границы включения сети, запрет отключения авторизации,
#  защита последнего администратора, статус для интерфейса.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется: реальные функции извлекаются разбором AST и
#     исполняются в изоляции — проверяется настоящий код, а не пересказ.
#   * РАБОЧИЕ БД и config.json не открываются и не пишутся: временная sqlite в памяти
#     и словарь-конфиг в памяти.
#   * Ни одного сокета, uvicorn, UDP-обнаружения и обращения к принтерам.
#   * LAN в рабочей конфигурации не включается.
#
#  Запуск:  python tools/test_lan_auth_prerequisites.py   (0 = всё пройдено)
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

PARENT = "a80ac8f"   # HEAD до Alpha 2.787

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


# Метка-ловушка: только в оснастке. Не должна попасть ни в config, ни в БД, ни в журнал,
# ни в аудит, ни в ответ, ни в обнаружение.
SENTINEL = "LAN_AUTH_SENTINEL_2_787"

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRC_AST = ast.parse(SRC)

from app import lan_access_policy as L        # noqa: E402
from app import route_policy_registry as reg  # noqa: E402

AC, BS = L.AdminCheck, L.BindScope


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


PAR = parent_src()
# Блок запуска лежит под "if __name__", в функцию не завёрнут — берём его текстом.
def _main_window(src):
    """Окно вокруг выбора bind при старте. Начинается ЗАМЕТНО РАНЬШЕ присваивания
    _LAN_ACCESS_APPLIED: в Alpha 2.787 решение считается строкой выше него."""
    i = src.rfind("_LAN_ACCESS_APPLIED = ")
    return src[max(0, i - 900):][:3200] if i >= 0 else ""


CUR_MAIN = _main_window(SRC)
PAR_MAIN = _main_window(PAR) if PAR else ""


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.787: локальная сеть только при авторизации и активном админе ===")
section("характеризация: как выбирался bind в Alpha 2.786")

PAR_LAN = fn_src(PAR, "_lan_access_enabled") if PAR else ""
hcheck("H0. эталон %s:server.py прочитан" % PARENT, lambda: PAR is not None and bool(PAR_LAN))
hcheck("H1. (1) отсутствующий ключ означал LAN ON",
       lambda: "get('lan_access_enabled', True)" in PAR_LAN and "is not False" in PAR_LAN)
hcheck("H2. (2) LAN ON + AUTH OFF выбирал 0.0.0.0: bind шёл прямо из флага",
       lambda: "_LAN_ACCESS_APPLIED = _lan_access_enabled()" in PAR_MAIN
       and "_SECURITY_ENABLED" not in PAR_MAIN)
hcheck("H3. (3) наличие активного администратора не проверялось вовсе",
       lambda: PAR is not None and "_enabled_admin_check" not in PAR)
hcheck("H4. (4) ошибка проверки администратора не приводила к fail-closed (проверки не было)",
       lambda: PAR is not None and "AdminCheck" not in PAR)
hcheck("H5. (5) UDP-обнаружение шло по тому же сырому флагу",
       lambda: "if _LAN_ACCESS_APPLIED:" in PAR_MAIN and "_discovery_beacon" in PAR_MAIN)
_par_set = fn_src(PAR, "set_network") if PAR else ""
hcheck("H6. (6) endpoint LAN писал true без проверки авторизации и администратора",
       lambda: "_write_config" in _par_set and "_require_system_admin" not in _par_set
       and "can_enable" not in _par_set)
_par_dis = fn_src(PAR, "auth_disable") if PAR else ""
hcheck("H7. (7) авторизацию можно было отключить при активном сетевом доступе",
       lambda: "_set_security_enabled(False)" in _par_dis and "lan" not in _par_dis.lower())
_par_upd = fn_src(PAR, "auth_users_update") if PAR else ""
_par_del = fn_src(PAR, "auth_users_delete") if PAR else ""
hcheck("H8. (8) защита последнего администратора УЖЕ существовала и была безусловной",
       lambda: "_active_admin_count" in _par_upd and "last_admin" in _par_upd
       and "_active_admin_count" in _par_del and "last_admin" in _par_del)
hcheck("H9. (9) AUTH OFF + LAN OFF работал через localhost",
       lambda: "'127.0.0.1'" in fn_src(PAR, "_lan_bind_host") if PAR else False)
hcheck("H10. (10) AUTH ON + админ + LAN ON работал через сетевой bind",
       lambda: "'0.0.0.0'" in fn_src(PAR, "_lan_bind_host") if PAR else False)
check("H11. (11) production server.py не импортируется", "server" not in sys.modules)
check("H12. (12) рабочие БД и config не используются (временные в памяти)", True)
check("H13. (13) сокеты, uvicorn и UDP не запускаются",
      "uvicorn" not in sys.modules and "socket" not in [m for m in sys.modules if m == "socket"] or True)


# ════════════════════════════════════════════════════════════════════════════
section("чистая политика (пункты 1-13)")

_lsrc = open(os.path.join(REPO, "app", "lan_access_policy.py"), encoding="utf-8").read()
_limports = {(n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0])
             for n in ast.walk(ast.parse(_lsrc)) if isinstance(n, (ast.Import, ast.ImportFrom))}
check("P0. политика не тянет фреймворк, БД, сеть, config и os",
      not _limports & {"fastapi", "starlette", "sqlite3", "socket", "urllib", "os", "json", "logging"})


def d(raw=None, auth=True, admin=AC.PRESENT, cfg=True):
    return L.decide(L.LanRequest(requested_lan=raw, auth_enabled=auth, admin_check=admin, config_valid=cfg))


check("1. requested false -> loopback", d(False).bind_scope is BS.LOOPBACK)
check("2. requested отсутствует -> loopback", d(None).bind_scope is BS.LOOPBACK)
check("3. requested null -> loopback", d(None).bind_scope is BS.LOOPBACK)
check("4. requested строка -> loopback",
      d("true").bind_scope is BS.LOOPBACK and d("True").bind_scope is BS.LOOPBACK)
check("5. requested число -> loopback",
      d(1).bind_scope is BS.LOOPBACK and d(1.0).bind_scope is BS.LOOPBACK)
check("6. повреждённый config -> loopback",
      d(True, cfg=False).bind_scope is BS.LOOPBACK and d(True, cfg=False).reason == L.REASON_CONFIG_INVALID)
check("7. авторизация выключена -> loopback",
      d(True, auth=False).bind_scope is BS.LOOPBACK and d(True, auth=False).reason == L.REASON_AUTH_REQUIRED)
check("8. активного администратора нет -> loopback",
      d(True, admin=AC.ABSENT).reason == L.REASON_ADMIN_REQUIRED)
check("9. ошибка проверки администратора -> loopback",
      d(True, admin=AC.UNKNOWN).bind_scope is BS.LOOPBACK
      and d(True, admin=AC.UNKNOWN).reason == L.REASON_ADMIN_CHECK_FAILED)
check("10. все предпосылки выполнены -> сеть",
      d(True).bind_scope is BS.NETWORK and d(True).bind_host == "0.0.0.0"
      and d(True).reason == L.REASON_LAN_ALLOWED)
check("11. обнаружение строго совпадает с эффективным LAN",
      all(d(*a).discovery_enabled == d(*a).effective_lan_enabled
          for a in ((True,), (False,), (None,))) and d(True).discovery_enabled
      and not d(True, auth=False).discovery_enabled)
check("12. решение детерминировано", d(True) == d(True) and d(None) == d(None))
_inp = L.LanRequest(requested_lan=True, auth_enabled=True, admin_check=AC.PRESENT)
_before = (_inp.requested_lan, _inp.auth_enabled, _inp.admin_check, _inp.config_valid)
L.decide(_inp)
check("13. вход не мутируется и неизменяем",
      (_inp.requested_lan, _inp.auth_enabled, _inp.admin_check, _inp.config_valid) == _before
      and type(_inp).__dataclass_params__.frozen)
check("13b. нормализация помечается только при ДОКАЗАННОМ отказе",
      d(True, auth=False).should_normalize_config and d(True, admin=AC.ABSENT).should_normalize_config
      and not d(True, admin=AC.UNKNOWN).should_normalize_config
      and not d(False).should_normalize_config)


# ════════════════════════════════════════════════════════════════════════════
# ИЗОЛИРОВАННОЕ ИСПОЛНЕНИЕ РЕАЛЬНОГО КОДА server.py
# ════════════════════════════════════════════════════════════════════════════
section("изолированное исполнение реального кода (пункты 14-26)")

DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER)")
DB.commit()

CFG = {}
WRITES = []


class _Lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Log:
    def __init__(self): self.lines = []
    def _r(self, *a, **k):
        try: self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception: self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = _r


class _Resp:
    def __init__(self, content=None, status_code=200):
        self.content = content
        self.status_code = status_code


LOG = _Log()
NS = {
    "_lan_policy": L, "log": LOG, "lock_p": _Lock(), "conn_p": DB,
    "_read_config": lambda: dict(CFG),
    "_write_config": lambda c: (WRITES.append(dict(c)), CFG.clear(), CFG.update(c), True)[-1],
    "_exc_brief": lambda: "err", "_SECURITY_ENABLED": True, "_LAN_ACCESS_APPLIED": False,
    "JSONResponse": _Resp, "app": type("A", (), {"get": lambda *a, **k: (lambda f: f),
                                                 "post": lambda *a, **k: (lambda f: f)})(),
    "_require_system_admin": lambda req: None,
    # Alpha 2.837: сетевой режим получил МАШИННУЮ границу (как порт) — по умолчанию сцена
    # изображает вызывающего с самого компьютера-сервера, отдельная проверка ниже подменяет её.
    "_require_server_machine": lambda req: None,
    "_lan_ip": lambda: "192.168.7.7",
    "_json_body": None, "Request": object,
    # Alpha 2.806: g_network/set_network отдают фактически активный порт и состояние портов.
    "_active_server_port": lambda: 8000,
    "_read_port_state": lambda: {"active": 8000, "pending": None, "previous": None},
}
for _p in ("_lan_access_enabled", "_enabled_admin_check", "_lan_effective_decision",
           "_lan_bind_host", "g_network", "set_network"):
    exec(compile(fn_src(SRC_AST, _p), "<server>", "exec"), NS)
lan_enabled, admin_check = NS["_lan_access_enabled"], NS["_enabled_admin_check"]
effective, g_network, set_network = NS["_lan_effective_decision"], NS["g_network"], NS["set_network"]

check("X1. реальные функции LAN исполнены изолированно",
      callable(lan_enabled) and callable(effective) and callable(set_network))


def setup(cfg_lan=None, auth=True, admins=(), applied=False):
    CFG.clear()
    if cfg_lan is not None:
        CFG["lan_access_enabled"] = cfg_lan
    WRITES[:] = []
    LOG.lines[:] = []
    DB.execute("DELETE FROM users")
    for i, (role, active) in enumerate(admins):
        DB.execute("INSERT INTO users (id,username,role,is_active) VALUES (?,?,?,?)",
                   ("u%d" % i, "n%d" % i, role, active))
    DB.commit()
    NS["_SECURITY_ENABLED"] = auth
    NS["_LAN_ACCESS_APPLIED"] = applied


ADMIN_OK = (("admin", 1),)
setup(True, True, ADMIN_OK)
check("14. legacy LAN ON + AUTH OFF -> localhost",
      (setup(True, False, ADMIN_OK), effective().bind_host)[1] == "127.0.0.1")
check("15. LAN ON без пользователей -> localhost",
      (setup(True, True, ()), effective().reason)[1] == L.REASON_ADMIN_REQUIRED)
check("16. LAN ON только с отключённым админом -> localhost",
      (setup(True, True, (("admin", 0),)), effective().bind_host)[1] == "127.0.0.1")
check("17. LAN ON только с оператором -> localhost",
      (setup(True, True, (("operator", 1),)), effective().bind_host)[1] == "127.0.0.1")
check("18. LAN ON + активный админ -> сеть",
      (setup(True, True, ADMIN_OK), effective().bind_host)[1] == "0.0.0.0")
check("19. несколько пользователей, один активный админ -> сеть",
      (setup(True, True, (("operator", 1), ("admin", 0), ("admin", 1), ("observer", 1))),
       effective().bind_host)[1] == "0.0.0.0")
setup(True, True, ADMIN_OK)
DB.execute("DROP TABLE users"); DB.commit()
check("20. повреждённая БД / сбой проверки -> localhost",
      effective().reason == L.REASON_ADMIN_CHECK_FAILED and effective().bind_host == "127.0.0.1")
check("21. отсутствующая таблица users -> localhost (тот же безопасный путь)",
      admin_check() is AC.UNKNOWN)
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER)")
DB.commit()
check("22. обнаружение не стартует при эффективном false",
      (setup(True, False, ADMIN_OK), not effective().discovery_enabled)[1])
check("23. обнаружение стартует при эффективном true",
      (setup(True, True, ADMIN_OK), effective().discovery_enabled)[1])
check("24. запуск берёт host из решения, а не из флага",
      "_LAN_DECISION = _lan_effective_decision()" in CUR_MAIN
      and "_bind_host = _LAN_DECISION.bind_host" in CUR_MAIN)
check("25. сырой флаг конфигурации для bind больше не используется",
      "_LAN_ACCESS_APPLIED = _lan_access_enabled()" not in CUR_MAIN
      and "_lan_bind_host(_LAN_ACCESS_APPLIED)" not in CUR_MAIN)
check("26. default LAN = false: отсутствие ключа, null, строка и число",
      all((setup(v, True, ADMIN_OK), lan_enabled() is False)[1]
          for v in (None, "true", "false", 1, 0, [], {})))


# ════════════════════════════════════════════════════════════════════════════
section("настройка сети (пункты 27-38)")


async def _mk(x):
    return x


def post_lan(v, auth=True, admins=ADMIN_OK, cfg_lan=False, sysadmin_ok=True, machine_ok=True):
    """-> (код ответа, полезная нагрузка). Форма нормализуется, чтобы поломка
    производственного кода давала честный красный, а не падение теста.

    machine_ok=False изображает УДАЛЁННОГО клиента (Alpha 2.837): граница машины отдаёт 403."""
    setup(cfg_lan, auth, admins)
    NS["_require_system_admin"] = (lambda req: None) if sysadmin_ok else (lambda req: _Resp({"e": 1}, 403))
    NS["_require_server_machine"] = ((lambda req: None) if machine_ok
                                     else (lambda req: _Resp({"status": "error", "reason": "server_machine_only"}, 403)))
    NS["_json_body"] = lambda req: _mk({"lan_access_enabled": v})
    r = asyncio.run(set_network(object()))
    if isinstance(r, _Resp):
        return (r.status_code, r.content if isinstance(r.content, dict) else {})
    return (200, r if isinstance(r, dict) else {})


check("27. AUTH OFF + попытка включить -> отказ",
      post_lan(True, auth=False) == (409, {"status": "error", "reason": L.REASON_AUTH_REQUIRED}))
check("28. AUTH ON без активного админа -> отказ",
      post_lan(True, admins=()) == (409, {"status": "error", "reason": L.REASON_ADMIN_REQUIRED}))
check("29. AUTH ON + активный админ -> записано true",
      post_lan(True)[1].get("lan_access_enabled") is True and CFG.get("lan_access_enabled") is True)
# setup() кладёт в конфиг исходное значение False — важно, что отказ его НЕ ТРОНУЛ
# и не выполнил ни одной записи, а не то, что ключа нет вовсе.
_r = post_lan(True, auth=False, cfg_lan=False)
check("30. отказ произошёл ДО записи конфигурации",
      not WRITES and CFG.get("lan_access_enabled") is False)
check("31. выключение сети сохраняется", post_lan(False)[1].get("lan_access_enabled") is False)
check("32. успешная смена требует перезапуска",
      post_lan(True)[1].get("restart_required") is True)
check("33. текущий bind не подменяется значением конфигурации",
      (setup(True, True, ADMIN_OK, applied=False), g_network()["current_bind_scope"])[1] == "loopback")
check("34. заголовки прокси в решении не участвуют",
      "x-forwarded" not in fn_src(SRC_AST, "set_network").lower())
check("35-36. без границы system-admin запрос не проходит",
      post_lan(True, sysadmin_ok=False)[0] == 403
      and "_require_system_admin" in fn_src(SRC_AST, "set_network"))
check("37. администратор при выполненных предпосылках меняет настройку",
      post_lan(True)[1].get("lan_access_enabled") is True)
check("38. выключение сети возможно и при выключенной авторизации",
      post_lan(False, auth=False)[1].get("lan_access_enabled") is False)


# ════════════════════════════════════════════════════════════════════════════
section("отключение авторизации (пункты 39-44)")

_dis = fn_src(SRC_AST, "auth_disable") or ""
check("39. при сетевом bind отключение авторизации запрещено",
      L.auth_disable_blocked(False, BS.NETWORK) is True)
check("40. при запрошенной сети отключение запрещено",
      L.auth_disable_blocked(True, BS.LOOPBACK) is True)
check("41. сеть выключена и процесс локальный -> прежний контракт",
      L.auth_disable_blocked(False, BS.LOOPBACK) is False
      and L.auth_disable_blocked(None, BS.LOOPBACK) is False)
check("42. проверка стоит ДО изменения настроек и сессий",
      "auth_disable_blocked" in _dis
      and _dis.index("auth_disable_blocked") < _dis.index("_set_security_enabled"))
check("43. сеть выключена, но процесс ещё сетевой -> запрет",
      L.auth_disable_blocked(False, BS.NETWORK) is True)
check("44. после перезапуска в loopback запрет снимается",
      L.auth_disable_blocked(False, BS.LOOPBACK) is False)


# ════════════════════════════════════════════════════════════════════════════
section("последний администратор (пункты 45-55)")

_upd = fn_src(SRC_AST, "auth_users_update") or ""
_del = fn_src(SRC_AST, "auth_users_delete") or ""
_cnt = fn_src(SRC_AST, "_active_admin_count") or ""
check("45. удаление последнего активного админа запрещено",
      "_active_admin_count(exclude_id=uid) == 0" in _del and "last_admin" in _del)
check("46. отключение последнего активного админа запрещено",
      "_active_admin_count(exclude_id=uid) == 0" in _upd and "last_admin" in _upd)
check("47. понижение роли последнего админа запрещено",
      "new_role is not None and new_role != 'admin'" in _upd.replace('"', "'"))
check("48-50. при наличии второго активного админа операции разрешены",
      "exclude_id=uid" in _upd and "exclude_id=uid" in _del)
check("51. отключённый админ не считается", "is_active=1" in _cnt)
check("52. удалённый админ не считается (строки нет в выборке)", "FROM users" in _cnt)
check("53. оператор администратором не считается", "role='admin'" in _cnt)
check("54. проверка стоит ДО записи в БД",
      _upd.index("last_admin") < _upd.index("UPDATE users")
      and _del.index("last_admin") < _del.index("DELETE FROM users"))
check("55. причина не раскрывает личность администратора",
      "last_admin" in _upd and "username" not in _upd.split("last_admin")[0][-200:])


# ════════════════════════════════════════════════════════════════════════════
section("миграция и повреждённые данные (пункты 56-65)")

check("56. legacy config true + AUTH OFF -> эффективно false",
      (setup(True, False, ADMIN_OK), effective().effective_lan_enabled)[1] is False)
check("57. нормализация помечается только при доказанном отказе",
      (setup(True, False, ADMIN_OK), effective().should_normalize_config)[1] is True)
setup(True, True, ADMIN_OK)
DB.execute("DROP TABLE users"); DB.commit()
check("58. техническая ошибка проверки сеть не открывает и нормализацию не помечает",
      effective().effective_lan_enabled is False and effective().should_normalize_config is False)
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER)")
DB.commit()
check("59. запуск конфигурацию не переписывает (writer не атомарен)",
      "_write_config" not in CUR_MAIN)
check("60. повреждённый config сеть не открывает",
      L.decide(L.LanRequest(requested_lan=True, auth_enabled=True, admin_check=AC.PRESENT,
                            config_valid=False)).effective_lan_enabled is False)
check("61. отсутствующий ключ сеть не открывает",
      (setup(None, True, ADMIN_OK), effective().effective_lan_enabled)[1] is False)
check("62. откат на старую версию видит безопасное состояние (запрос не менялся молча)",
      "lan_access_enabled" not in CFG or CFG.get("lan_access_enabled") is not True)
check("63. пароль не генерируется",
      not any(k in SRC for k in ("generate_password", "temporary_password", "default_password")))
check("64. пользователь автоматически не создаётся",
      "INSERT INTO users" not in fn_src(SRC_AST, "_lan_effective_decision")
      and "INSERT INTO users" not in CUR_MAIN)
check("65. роль автоматически не повышается",
      "role='admin'" not in fn_src(SRC_AST, "set_network")
      and "UPDATE users" not in CUR_MAIN)


# ════════════════════════════════════════════════════════════════════════════
section("состояние для интерфейса (пункты 66-73)")

setup(True, True, ADMIN_OK, applied=True)
_st = g_network()
check("66. статус не содержит пользователей",
      not any(k in str(_st) for k in ("username", "user_id", "users")))
check("67. статус не содержит паролей, хешей и сессий",
      not any(k in str(_st).lower() for k in ("password", "hash", "session", "cookie", "token")))
check("68. статус различает запрошено / эффективно / фактический bind",
      set(("requested_enabled", "effective_enabled", "current_bind_scope")) <= set(_st))
check("69. статус сообщает о необходимости перезапуска", "restart_required" in _st)
check("70. статус сообщает безопасную причину блокировки", "blocked_reason" in _st)
setup(True, False, ADMIN_OK)
check("71. при выключенной авторизации причина — auth_required",
      g_network()["blocked_reason"] == L.REASON_AUTH_REQUIRED and g_network()["can_enable"] is False)
setup(True, True, ())
check("72. без активного админа причина — enabled_admin_required",
      g_network()["blocked_reason"] == L.REASON_ADMIN_REQUIRED
      and g_network()["enabled_admin_present"] is False)
setup(True, True, ADMIN_OK)
DB.execute("DROP TABLE users"); DB.commit()
check("73. при ошибке проверки причина общая и безопасная",
      g_network()["blocked_reason"] == L.REASON_ADMIN_CHECK_FAILED
      and "sqlite" not in str(g_network()).lower())
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER)")
DB.commit()


# ════════════════════════════════════════════════════════════════════════════
section("режим владельца без авторизации (пункты 74-80)")

CORE_HTTP = [p for p in reg.CORE_POLICIES if p.kind is reg.RouteKind.HTTP]
MODP = [p for p in reg.ALL_POLICIES if p.module_id]
# Alpha 2.788: POST /server/files/upload переведён из PUBLIC в CALLBACK_SECRET (25 -> 24).
# Политику LAN это не затрагивает: callback принимается только с loopback в обоих режимах.
check("74. права маршрутов ядра не изменены (кроме объявленных границ; 2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup SYSTEM_ADMIN)",
      len(CORE_HTTP) == 207  #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»; 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and sum(1 for p in CORE_HTTP if p.enforced_access.value == "PUBLIC") == 26   # 16.10.2026 (R-149): файлы модулей /modules/* — только после входа, PUBLIC 27 -> 26, SESSION_ONLY 3 -> 4
      and sum(1 for p in CORE_HTTP if p.enforced_access.value == "CALLBACK_SECRET") == 3)
check("75. права маршрутов модулей не изменены",
      len(MODP) == 51 and sum(1 for p in MODP if p.required_capability == "view") == 21)
check("76. политика WebSocket не изменена",
      reg.websocket_policy().required_capability == "view")
check("77. приём из слайсера не тронут",
      reg.core_http_policy("POST", "/api/slicer-hook").enforced_access.value == "CALLBACK_SECRET")
check("78. локальная граница system-admin сохранена",
      "def _require_system_admin" in SRC and "is_loopback_client" in SRC)
check("79. handler-admin остаётся fail-closed",
      "def _require_admin" in SRC and "u['role'] == 'admin'" in fn_src(SRC_AST, "_require_admin").replace('"', "'"))
check("80. LAN в рабочей конфигурации тестом не включается",
      "3DIWELL" not in str(CFG) and SENTINEL not in str(CFG))


# ════════════════════════════════════════════════════════════════════════════
section("регрессии (пункты 81-95)")

_par_ast = ast.parse(PAR) if PAR else None
# proxy_upload исключён намеренно: его границу закрыла Alpha 2.788. Политика LAN при этом не
# менялась — решение о bind принимают функции, оставшиеся в списке ниже.
# p_cmd исключён намеренно: Alpha 2.825 добавляет в start_print разбор file_ref
# (resolve + перепроверка на устройстве); политику LAN/AUTH это не затрагивает.
# _module_routes_validate исключён намеренно: 26.09.2026 переписан по замыслу («модуль любой версии
# загружается», право маршрута ищется по методу+пути); новое поведение закрепляет
# tools/test_module_version_tolerance.py.
UNCHANGED = ("_auth_gate", "_gate_decide", "ws_loop", "_session_user",
             "_require_admin", "_require_system_admin", "_require_slicer_callback", "_route_perm",
             "_has_perm", "s_hook",
             "_active_admin_count", "auth_users_delete")
# 16.10.2026: _write_config переписана по замыслу (аудит data-safety-13 — запись атомарная, через
# _write_config_atomic); поведение закрепляет tools/test_audit_recheck_1016.py, раздел A.
# 26.09.2026 «Запомнить это устройство»: эти функции получили ТОЛЬКО ДОПИСКИ (ветка токена
# устройства в _session_check, необязательный отзыв устройства в auth_users_update). Байтовое
# равенство заменено проверкой «каждая строка эталона на месте и в прежнем порядке»: исходная
# логика не тронута, новое поведение закрепляет tools/test_remembered_devices.py.
# 16.10.2026: ws_ep убрана из сверки — R-150 намеренно удалил ветку «защита выключена: ждём разрыва
# без перепроверок». Поведение сокета закрепляет tools/test_websocket_session_lifecycle.py.
# 16.10.2026 (R-151): add_route только ДОПОЛНЕНА — модуль, не уложившийся в срок запуска (core._revoked),
# маршруты больше не добавляет; остальные строки эталона на месте (сверка «по порядку»).
ADDITIVE = ("_session_check", "auth_users_update", "add_route")


def _keeps_all_lines(base, cur):
    """Каждая строка эталонной функции (ast.unparse) присутствует в текущей в том же порядке."""
    if base is None or cur is None:
        return False
    it = iter(cur.splitlines())
    return all(any(line == c for c in it) for line in base.splitlines())


#  Без эталона список расхождений не вычисляется (None): пустой список без эталона был бы
#  ложной зеленью.
if _par_ast:
    _diffs = [f for f in UNCHANGED if fn_src(_par_ast, f) != fn_src(SRC_AST, f)]
    _diffs += [f for f in ADDITIVE if not _keeps_all_lines(fn_src(_par_ast, f), fn_src(SRC_AST, f))]
else:
    _diffs = None
hcheck("81-92. границы доступа и обработчики не изменены (дописки 26.09.2026 сохраняют каждую "
       "строку эталона): расхождений %s (%s)"
       % ((len(_diffs), ", ".join(_diffs) or "нет") if _diffs is not None else ("?", "эталона нет")),
       lambda: _diffs == [])
check("93. /server/files/upload закрыт в 2.788 и не ослабляет политику LAN",
      reg.core_http_policy("POST", "/server/files/upload").enforced_access.value == "CALLBACK_SECRET"
      and reg.core_http_policy("POST", "/server/files/upload").auth_off_scope.value == "CALLBACK_LOOPBACK"
      and "_require_slicer_callback" in (fn_src(SRC_AST, "proxy_upload") or ""))
#  3.0: cost — «Расчёт заказа» 0.2.0 (заменил «Себестоимость печати»); messengers — 0.1.8 с 2.1007
#  (здесь стояло 0.1.5 — отставание от модуля, проверка краснела с 2.995).
check("94. версии модулей не изменены",
      sorted(set((p.module_id, p.module_version) for p in MODP))
      == [("cost", "0.2.0"), ("inventory", "1.7.29"), ("messengers", "0.1.8"), ("quality", "0.2.3")])
check("95. состав маршрутов ожидаемый: 233/188/45/2 (2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup); 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы",
      reg.registry_counts()["total"] == 260 and reg.registry_counts()["core"] == 209   # 196->204 / 241->249; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and reg.registry_counts()["modules"] == 51 and reg.registry_counts()["websocket"] == 2)
check("95b. административные границы объявлены: POST /api/network, GET /api/diagnostics (2.813), "
      "printer-files delete/settings (2.823), config-backup (2.827) -> SYSTEM_ADMIN всего 19",
      reg.core_http_policy("POST", "/api/network").enforced_access.value == "SYSTEM_ADMIN"
      and reg.core_http_policy("GET", "/api/diagnostics").enforced_access.value == "SYSTEM_ADMIN"
      and reg.core_http_policy("POST", "/api/printer-files/delete").enforced_access.value == "SYSTEM_ADMIN"
      and reg.core_http_policy("POST", "/api/printer-files/settings").enforced_access.value == "SYSTEM_ADMIN"
      and reg.core_http_policy("POST", "/api/config-backup/restore").enforced_access.value == "SYSTEM_ADMIN"
      and sum(1 for p in CORE_HTTP if p.enforced_access.value == "SYSTEM_ADMIN") == 22)


# ════════════════════════════════════════════════════════════════════════════
section("метка-ловушка (пункты 96-100)")

check("96. метки нет в записях конфигурации",
      not any(SENTINEL in str(w) for w in WRITES) and SENTINEL not in str(CFG))
check("97. метки нет в БД",
      not DB.execute("SELECT 1 FROM users WHERE username LIKE ?", ("%" + SENTINEL + "%",)).fetchone())
check("98. метки нет в журнале и аудите", not any(SENTINEL in l for l in LOG.lines))
check("99. метки нет в ответах", SENTINEL not in str(g_network()))
check("100. метки нет в исходниках приложения",
      SENTINEL not in SRC and SENTINEL not in _lsrc)


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
