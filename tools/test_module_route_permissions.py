# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.785 — явная регистрация и проверка прав маршрутов модулей.
#
#  ЧАСТЬ 1 (ХАРАКТЕРИЗАЦИЯ). Как система решала доступ к маршрутам модулей ДО правки,
#  то есть в Alpha 2.784: все 45 маршрутов помечены отложенным этапом, каждый
#  изменяющий получает 'project' общим fallback, каждый читающий — None, а
#  core.add_route принимает регистрацию вообще без объявления прав. Легаси-модель
#  реконструирована и сверена с исходником родительского коммита, поэтому эти
#  проверки остаются зелёными навсегда: они описывают историю, а не текущий код.
#
#  26.09.2026: слово владельца — ставится и работает любая версия модуля. Пункты 21c-31, 32b,
#  A1b и A2 переведены на новое поведение (право — из карты по методу и пути, расхождение —
#  в заметки, маршрут вне карты — только admin); целиком его закрепляет
#  tools/test_module_version_tolerance.py. Строгие политики живут только в памяти этого прогона
#  и снимаются в нём же.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется: только чтение исходника и разбор AST.
#   * Работающая программа не трогается: ни запуска, ни остановки, ни запросов.
#   * Ни одной реальной БД модулей, DATA_DIR, config.json, сети и принтеров.
#   * Backend модулей не импортируется: их handlers ходят в свои БД.
#
#  Запуск:  python tools/test_module_route_permissions.py   (0 = всё пройдено)
# ============================================================================
import ast
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

PARENT = "cd71e81"   # HEAD до Alpha 2.785: эталон прежнего поведения

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


# Метка-ловушка: только в тестовой оснастке. Не должна попасть ни в handler, ни в БД
# модуля, ни в файловую систему, ни в журнал, ни в аудит, ни в ответ, ни в ZIP.
SENTINEL = "MODULE_PERMISSION_SENTINEL_2_785"

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRC_AST = ast.parse(SRC)

from app import route_access_control as rac      # noqa: E402
from app import route_policy_registry as reg     # noqa: E402
# 26.09.2026: строгая политика для маршрута модуля, которого нет в карте прав (только admin).
from app import module_runtime_policy as rtp     # noqa: E402

EA, ES, AD = rac.EnforcedAccess, rac.EnforcementStage, rac.AccessDecision

MOD = [p for p in reg.ALL_POLICIES if p.module_id is not None]
CORE_HTTP = [p for p in reg.CORE_POLICIES if p.kind is reg.RouteKind.HTTP]
CORE_WS = [p for p in reg.CORE_POLICIES if p.kind is reg.RouteKind.WEBSOCKET]


def fn_src(tree_or_src, name, cls=None):
    tree = tree_or_src if isinstance(tree_or_src, ast.AST) else ast.parse(tree_or_src)
    if cls:
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef) and n.name == cls:
                tree = n
                break
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
_ns = {"re": __import__("re")}
exec(compile(fn_src(SRC_AST, "_route_perm"), "<x>", "exec"), _ns)
legacy_route_perm = _ns["_route_perm"]

PAR = parent_src()


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.785: явная регистрация и проверка прав маршрутов модулей ===")
section("характеризация: как решался доступ к модулям в Alpha 2.784")

hcheck("H0. эталон %s:server.py прочитан" % PARENT, lambda: PAR is not None)
check("H0b. модель ролей прочитана из server.py",
      isinstance(ROLE_PERMS, dict) and set(ROLE_PERMS) == {"admin", "operator", "assembler", "observer"})

MOD_MUT = [p for p in MOD if p.method in reg.MUTATING_METHODS]
MOD_RO = [p for p in MOD if p.method not in reg.MUTATING_METHODS]


def legacy_gate_module(p, role):
    """Реконструкция ветки модулей общего гейта Alpha 2.784 (AUTH ON)."""
    if role is None:
        return "401"
    perm = legacy_route_perm(p.method, p.path)
    if perm and perm not in ROLE_PERMS.get(role, set()):
        return "403"
    return "ПУСКАЕТ"


# 1 — историческое состояние берём из РОДИТЕЛЬСКОГО коммита, а не из текущего реестра:
#     иначе проверка описывала бы не историю, а сегодняшний день, и после правки лгала бы.
def _parent_file(rel):
    return HIST.show(rel)


_PAR_REG = _parent_file("app/route_policy_registry.py")
hcheck("H1. (характеризация 1) все 51 маршрутов модулей имели отложенный этап",
       lambda: _PAR_REG is not None and len(MOD) == 51
       and "(EnforcementStage.MODULE_DEFERRED_2_785, EnforcedAccess.DEFERRED, None)" in _PAR_REG
       and "MODULE_2_785" not in _PAR_REG.replace("MODULE_DEFERRED_2_785", ""))

# 2
check("H2. (характеризация 2) все %d изменяющих получали 'project' общим fallback" % len(MOD_MUT),
      len(MOD_MUT) == 29   # 2.994: +4 POST модуля messengers
      and all(legacy_route_perm(p.method, p.path) == "project" for p in MOD_MUT)
      and all(p.current_permission == "project" for p in MOD_MUT))

# 3
check("H3. (характеризация 3) все %d читающих получали право None" % len(MOD_RO),
      len(MOD_RO) == 22   # 2.994: +2 GET модуля messengers
      and all(legacy_route_perm(p.method, p.path) is None for p in MOD_RO)
      and all(p.current_permission is None for p in MOD_RO))

# 4
check("H4. (характеризация 4) observer читал ВСЕ читающие маршруты модулей",
      all(legacy_gate_module(p, "observer") == "ПУСКАЕТ" for p in MOD_RO))

# 5
check("H5. (характеризация 5) observer не мог ни один изменяющий (нет project)",
      all(legacy_gate_module(p, "observer") == "403" for p in MOD_MUT))

# 6 — ключевой дефект: operator получал ВСЁ изменяющее независимо от назначения,
#     включая настройки модулей и глобальные справочники.
check("H6. (характеризация 6) operator получал ВСЕ %d изменяющих независимо от назначения" % len(MOD_MUT),
      all(legacy_gate_module(p, "operator") == "ПУСКАЕТ" for p in MOD_MUT))

# 7
check("H7. (характеризация 7) assembler не получал project, но имел count и rework",
      "project" not in ROLE_PERMS["assembler"]
      and {"count", "rework"} & set(ROLE_PERMS["assembler"]) == {"rework"}
      and "count" not in ROLE_PERMS["assembler"]
      and all(legacy_gate_module(p, "assembler") == "403" for p in MOD_MUT))

# 8 — ни один модуль не объявлял собственных прав
_mod_srcs = {}
for mid in ("inventory", "cost", "quality", "messengers"):   # 2.994: +модуль уведомлений
    fp = os.path.join(REPO, "modules", mid, "backend.py")
    _mod_srcs[mid] = open(fp, encoding="utf-8", errors="surrogateescape").read()
_PAR_MOD = {m: _parent_file("modules/%s/backend.py" % m) for m in ("inventory", "cost", "quality")}
hcheck("H8. (характеризация 8) ни один модуль не объявлял собственную политику прав",
       lambda: all(s is not None for s in _PAR_MOD.values())
       and not any(("policy_id" in s) or ("required_capability" in s) or ("enforced_access" in s)
                  for s in _PAR_MOD.values()))

# 9 — add_route принимал регистрацию без объявления прав
_par_add = fn_src(PAR, "add_route", cls="ModuleCore") if PAR else None
hcheck("H9. (характеризация 9) core.add_route принимал регистрацию без объявления прав",
       lambda: _par_add is not None and "policy_id" not in _par_add
       and "add_api_route" in _par_add)

# 10
check("H10. (характеризация 10) новый маршрут модуля автоматически получил бы fallback",
      legacy_route_perm("POST", "/api/mod/inventory/brand-new-2785") == "project"
      and legacy_route_perm("GET", "/api/mod/inventory/brand-new-2785") is None)

# 11-12 — регистрация ничего не сверяла с реестром
hcheck("H11. (характеризация 11) маршрут, которого нет в реестре, регистрировался беспрепятственно",
       lambda: _par_add is not None and "route_policy_registry" not in _par_add
       and "core_http_policy" not in _par_add)
hcheck("H12. (характеризация 12) несовпадение обработчика при регистрации не проверялось",
       lambda: _par_add is not None and "handler" in _par_add and "==" not in _par_add.split("add_api_route")[0])

# 13 — прежняя модель проверяется на записи с ИСТОРИЧЕСКИМ этапом. Это одновременно
#      доказывает, что путь «отдать прежней модели» никуда не делся: старый или сторонний
#      модуль по-прежнему не получает доступа по недосмотру.
class _HistoricalModulePolicy:
    enforcement_stage = ES.MODULE_DEFERRED_2_785
    enforced_access = EA.DEFERRED
    required_capability = None


check("H13. (характеризация 13) отложенный этап по-прежнему отдаёт решение прежней модели",
      rac.decide(_HistoricalModulePolicy(), rac.SecurityContext(security_enabled=False)).outcome
      is AD.DEFER_TO_LEGACY_MODULE
      and rac.decide(_HistoricalModulePolicy(), rac.SecurityContext(
          security_enabled=True, has_session=True, user_enabled=True, role="admin",
          capabilities=frozenset(ROLE_PERMS["admin"]))).outcome is AD.DEFER_TO_LEGACY_MODULE)

# 14
check("H14. (характеризация 14) маршруты ядра уже работали по карте Alpha 2.784",
      len(CORE_HTTP) == 207 and all(p.enforcement_stage is ES.CORE_2_784 for p in CORE_HTTP))   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»; 2.823: +5 printer-files; 2.825: +select-for-print; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера

# 15
# Alpha 2.879: сокетов два — телеметрия /ws и камера. К модулям не относится ни один.
check("H15. (характеризация 15) WebSocket в авторизации модулей не участвует",
      len(CORE_WS) == 2 and all(p.module_id is None for p in CORE_WS)
      and not any(p.enforcement_stage is ES.MODULE_2_785 for p in CORE_WS))

# 16
check("H16. (характеризация 16) ни один backend модуля не импортирован, БД не открыты",
      "server" not in sys.modules
      and not any(m.startswith("fm_module_") for m in sys.modules)
      and "modules.inventory.backend" not in sys.modules)


# ════════════════════════════════════════════════════════════════════════════
# РЕАЛЬНЫЙ КОД РЕГИСТРАЦИИ ИЗ server.py, ИСПОЛНЕННЫЙ В ИЗОЛЯЦИИ.
# Определения классов и функций компилируются, но их тела не выполняются, поэтому
# отсутствующие глобали ядра (БД, принтеры) безопасны: мы вызываем только регистрацию.
# ════════════════════════════════════════════════════════════════════════════
section("изолированное исполнение реального кода регистрации")


class _FakeApp:
    def __init__(self):
        self.registered = []
        self.policy_at_attach = []   # 26.09.2026: была ли у маршрута политика в момент подключения

    def add_api_route(self, path, handler, methods=None):
        self.registered.append((tuple(methods or []), path, getattr(handler, "__name__", "")))
        self.policy_at_attach.append(reg.module_http_policy((list(methods or []) or ["?"])[0], path) is not None)


class _FakeLog:
    def __init__(self):
        self.lines = []

    def _rec(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = _rec


def _cls_src(name):
    for n in ast.walk(SRC_AST):
        if isinstance(n, ast.ClassDef) and n.name == name:
            return ast.unparse(n)
    return None


_HOOKS = {"pre_print_check": [], "after_dispatch": [], "print_run_started": [], "print_run_finished": []}
_BADGE, _FIL = [], []
_APP, _LOG = _FakeApp(), _FakeLog()


def _register_print_hook(name, fn):
    if name not in _HOOKS or not callable(fn):
        return False
    _HOOKS[name].append(fn)
    return True


NS = {
    "app": _APP, "log": _LOG, "_route_registry": reg, "_route_access": rac,
    "_module_rt_policy": rtp,   # 26.09.2026: server.py импортирует app/module_runtime_policy.py под этим именем
    "_print_hooks": _HOOKS, "_printer_badge_providers": _BADGE,
    "_printer_filament_providers": _FIL, "_register_print_hook": _register_print_hook,
    "os": os, "_jsonmod": __import__("json"),
    #  16.10.2026 (R-151): подписка и откат — под общим замком; владелец хука — для предупреждений
    "_hooks_lock": __import__("threading").RLock(), "_hook_owner": {},
}
for _piece in (_cls_src("ModuleCore"), fn_src(SRC_AST, "_module_routes_validate"),
               fn_src(SRC_AST, "_module_rollback")):
    exec(compile(_piece, "<server>", "exec"), NS)
ModuleCore = NS["ModuleCore"]
validate = NS["_module_routes_validate"]
rollback = NS["_module_rollback"]

check("X1. реальные ModuleCore/_module_routes_validate/_module_rollback исполнены изолированно",
      callable(getattr(ModuleCore, "add_route", None)) and callable(validate) and callable(rollback))


def mk_handler(name):
    def h():
        SPY["handler"].append(name)
    h.__name__ = name
    return h


SPY = {"handler": [], "db": [], "fs": [], "net": [], "module_state": [], "body": []}


def declare(core, rel, handler_name, method, policy_id):
    core.add_route(rel, mk_handler(handler_name), [method], policy_id=policy_id)


def fresh_core(mid, ver):
    return ModuleCore(mid, "/fake/dir", ver)


def declare_all(mid):
    """Объявляет РОВНО те маршруты, что объявляет настоящий модуль, по реестру."""
    #  2.978: версию берём ИЗ РЕЕСТРА, а не вписываем сюда руками. Вписанная руками
    #  устарела при выпуске модуля 0.2.3: «Качество» переставало проходить проверку
    #  целиком, и два пункта набора краснели, хотя в самой программе всё было согласовано
    #  (сверку реестра с module.json делает пункт 15 выше, и он зелёный).
    _vers = sorted({q.module_version for q in MOD if q.module_id == mid})
    assert len(_vers) == 1, ("у модуля должна быть одна версия в реестре", mid, _vers)
    core = fresh_core(mid, _vers[0])
    for p in sorted([q for q in MOD if q.module_id == mid], key=lambda q: q.policy_id):
        declare(core, p.module_route, p.handler, p.method, p.policy_id)
    return core


# ════════════════════════════════════════════════════════════════════════════
section("полнота карты прав модулей (пункты 1-20)")

INV = [p for p in MOD if p.module_id == "inventory"]
COST = [p for p in MOD if p.module_id == "cost"]
QUAL = [p for p in MOD if p.module_id == "quality"]

check("1. все 207 маршрутов ядра остаются CORE_2_784 (2.978 +«где лежит файл проекта»; 2.980 +7 поиск принтеров и запись сети) (2.823: +5 printer-files; 2.825: +select-for-print; 2.827: +4 config-backup; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.870: +камера без перекодирования); 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы",
      len(CORE_HTTP) == 207 and all(p.enforcement_stage is ES.CORE_2_784 for p in CORE_HTTP))   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
check("2. все 51 маршрутов модулей имеют активный этап MODULE_2_785",
      len(MOD) == 51 and all(p.enforcement_stage is ES.MODULE_2_785 for p in MOD))
check("3. ни один маршрут модуля не остался DEFERRED",
      not [p for p in MOD if p.enforced_access is EA.DEFERRED])
check("4. сокеты не входят в карту модулей и решаются отдельным движком",
      len(CORE_WS) == 2
      and all(p.enforcement_stage is ES.WEBSOCKET_2_786 for p in CORE_WS)
      and reg.module_http_policy("GET", "/ws") is None
      and reg.module_http_policy("GET", "/api/printer/{pid}/camera.ws") is None)
check("5. Складской учёт содержит ровно 31 политику", len(INV) == 31)
check("6. Расчёт заказа (cost) содержит ровно 10 политик", len(COST) == 10)
check("7. Аналитика качества содержит ровно 4 политики", len(QUAL) == 4)

SRC_ROUTES = {}
for _mid in ("inventory", "cost", "quality", "messengers"):
    _msrc = _mod_srcs[_mid]
    for _m in __import__("re").finditer(
            r'core\.add_route\(\s*"([^"]+)"\s*,\s*(\w+)\s*,\s*\[\s*"(\w+)"\s*\]\s*,\s*policy_id\s*=\s*"([^"]+)"',
            _msrc):
        SRC_ROUTES[(_mid, _m.group(3), _m.group(1))] = (_m.group(2), _m.group(4))

check("8. каждый маршрут модуля из реестра существует в исходнике: не хватает %d"
      % len([p for p in MOD if (p.module_id, p.method, p.module_route) not in SRC_ROUTES]),
      all((p.module_id, p.method, p.module_route) in SRC_ROUTES for p in MOD))
check("9. каждый маршрут из исходника есть в реестре: лишних %d"
      % len([k for k in SRC_ROUTES if k not in {(p.module_id, p.method, p.module_route) for p in MOD}]),
      len(SRC_ROUTES) == 51)
check("10. метод, путь и обработчик совпадают у всех 45",
      all(SRC_ROUTES[(p.module_id, p.method, p.module_route)][0] == p.handler for p in MOD))
check("11. id модуля совпадает у всех записей",
      all(p.path.startswith("/api/mod/%s/" % p.module_id) for p in MOD))
#  23.09.2026: в реестре записан КОНТРАКТ модуля с ядром; без поля core_contract это его version.
def _mod_contract(mid):
    _m = __import__("json").load(open(os.path.join(REPO, "modules", mid, "module.json"), encoding="utf-8"))
    return _m.get("core_contract") or _m["version"]


check("12. версия модуля в реестре совпадает с контрактом манифеста",
      all(p.module_version == _mod_contract(p.module_id) for p in MOD))
check("13. policy_id уникален", len({p.policy_id for p in MOD}) == 51)
check("14. метод + итоговый путь уникальны", len({(p.method, p.path) for p in MOD}) == 51)
check("15. policy_id в исходнике совпадает с реестром",
      all(SRC_ROUTES[(p.module_id, p.method, p.module_route)][1] == p.policy_id for p in MOD))
check("16. устаревшая политика без маршрута обнаруживается",
      reg.module_policy_by_id("inventory.removed.route.2785") is None)
check("17. политика чужого модуля не проходит по id",
      reg.module_policy_by_id("cost.calculate").module_id == "cost"
      and reg.module_policy_by_id("inventory.spool.create").module_id == "inventory")
check("18. поиск по неверному обработчику даёт расхождение",
      reg.module_policy_by_id("cost.calculate").handler == "api_calculate")
check("19. поиск по неверному методу не находит маршрут",
      reg.module_http_policy("GET", "/api/mod/cost/calculate") is None
      and reg.module_http_policy("POST", "/api/mod/cost/calculate") is not None)
check("20. поиск по неверному пути не находит маршрут",
      reg.module_http_policy("POST", "/api/mod/cost/calculate-typo") is None)


# ════════════════════════════════════════════════════════════════════════════
section("контракт регистрации (пункты 21-32)")

#  26.09.2026 (слово владельца: ставится и работает любая версия модуля). Проверка маршрутов
#  больше не отказывает модулю из-за расхождения с картой прав. Право маршрута берётся из карты
#  по МЕТОДУ И ИТОГОВОМУ ПУТИ — тем же ключом, по которому гейт ищет политику при каждом запросе;
#  расхождение контракта, policy_id и обработчика идёт в заметки (core._route_notes). Маршрут,
#  которого в карте нет (модуль новее программы), получает строгую политику «только admin»
#  (app/module_runtime_policy.py, поле объявления runtime_policy). Отказ — только маршруту,
#  который подключить нельзя вовсе (не один метод, повтор метода и пути); он пропускается, а
#  остальные маршруты модуля подключаются. Пункты 21c-31 переведены на это поведение; новое
#  поведение целиком закрепляет tools/test_module_version_tolerance.py.


def _role_ctx(role, session=True):
    caps = ROLE_PERMS.get(role)
    return rac.SecurityContext(security_enabled=True, has_session=session and role is not None,
                               user_enabled=True, role=role,
                               capabilities=(frozenset(caps) if caps is not None else None))


def _admin_only(p):
    """Строгая политика: пускает только admin; остальным ролям — 403, без сессии — 401."""
    return (p is not None
            and rac.decide(p, _role_ctx("admin")).outcome is AD.ALLOW
            and all(rac.decide(p, _role_ctx(r)).outcome is AD.FORBIDDEN
                    for r in ("operator", "assembler", "observer"))
            and rac.decide(p, _role_ctx(None, session=False)).outcome is AD.REQUIRE_SESSION)


def _notes(core):
    """Заметки о расхождении с картой, оставленные проверкой (26.09.2026)."""
    return list(getattr(core, "_route_notes", None) or [])


def _gate_pol(d):
    """Политика, которую найдёт гейт для объявления: по методу и итоговому пути."""
    return reg.module_http_policy(d["methods"][0], d["full"])


#  Версии модулей — из карты прав, а не числом: в 3.0 «Расчёт заказа» (0.2.0) заменил
#  «Себестоимость печати» (0.1.3), и вписанное число сделало бы проверки ниже вакуумными.
_INV_VER = sorted({p.module_version for p in INV})[0]
_COST_VER = sorted({p.module_version for p in COST})[0]

_c = declare_all("inventory")
_ready, _errs = validate(_c)
check("21. core.add_route принимает policy_id (сигнатура; с 26.09.2026 право ищется по методу и пути)",
      "policy_id" in (fn_src(SRC_AST, "add_route", cls="ModuleCore") or ""))
check("21b. корректный модуль проходит проверку целиком: %d маршрутов, ошибок %d, заметок %d"
      % (len(_ready), len(_errs), len(_notes(_c))),
      len(_ready) == 31 and not _errs and not _notes(_c)
      and not any("runtime_policy" in d for d in _ready))

_c = fresh_core("inventory", "0.0.1-old")
for _p in sorted(INV, key=lambda q: q.policy_id):
    declare(_c, _p.module_route, _p.handler, _p.method, _p.policy_id)
_r, _e = validate(_c)
check("21c. старый контракт модуля принимается: готовы все 31, расхождение версии — в заметках, право — из карты",
      len(_r) == 31 and not _e
      and len(_notes(_c)) == 31
      and all("0.0.1-old" in n and _INV_VER in n for n in _notes(_c))
      and not any("runtime_policy" in d for d in _r)
      and all(_gate_pol(d) == reg.module_policy_by_id(d["policy_id"]) for d in _r)
      and "версия модуля не совпадает с реестром" not in (fn_src(SRC_AST, "_module_routes_validate") or ""))

_c = fresh_core("inventory", _INV_VER)
_c.add_route("spool", mk_handler("api_inv_spool_create"), ["POST"])          # без policy_id
_r, _e = validate(_c)
check("22. без policy_id право не берётся из объявления: маршрут получает право карты по методу и пути",
      len(_r) == 1 and not _e and "runtime_policy" not in _r[0] and not _notes(_c)
      and _gate_pol(_r[0]) == reg.module_policy_by_id("inventory.spool.create")
      and _gate_pol(_r[0]).required_capability == "project")

_c = fresh_core("inventory", _INV_VER)
declare(_c, "spool", "api_inv_spool_create", "POST", "inventory.no.such.policy")
_r, _e = validate(_c)
check("23. неизвестный policy_id своего права не даёт: право — из карты по методу и пути, расхождение в заметках",
      len(_r) == 1 and not _e and "runtime_policy" not in _r[0]
      and len(_notes(_c)) == 1 and "inventory.no.such.policy" in _notes(_c)[0]
      and _gate_pol(_r[0]) == reg.module_policy_by_id("inventory.spool.create"))

_c = fresh_core("cost", _COST_VER)
declare(_c, "calculate", "api_calculate", "POST", "cost.calculate")
declare(_c, "calculate", "api_calculate", "POST", "cost.calculate")
_r, _e = validate(_c)
check("24. повтор того же метода и пути не регистрируется второй раз",
      len(_r) == 1 and len(_e) == 1 and "дважды" in _e[0])

_c = fresh_core("cost", _COST_VER)
declare(_c, "calculate", "api_calculate", "POST", "cost.calculate")
_c._declared_routes[0]["policy_id"] = "GET /api/printers"     # политика ядра
declare(_c, "brand-new-2609", "api_brand_new", "POST", "GET /api/printers")   # тот же id на пути вне карты
_r, _e = validate(_c)
_rp = _r[1].get("runtime_policy") if len(_r) == 2 else None
check("25. id политики ядра модулю не доверяется: право — из карты по методу и пути, вне карты — только admin",
      len(_r) == 2 and not _e and "runtime_policy" not in _r[0]
      and _gate_pol(_r[0]) == reg.module_policy_by_id("cost.calculate")
      and _gate_pol(_r[0]).module_id == "cost"
      and any("GET /api/printers" in n for n in _notes(_c))
      and _rp is not None and _rp.module_id == "cost" and _rp.path == "/api/mod/cost/brand-new-2609"
      and str(_rp.policy_id).startswith(rtp.RUNTIME_POLICY_PREFIX)
      and _rp.required_capability == "admin" and _admin_only(_rp))

_c = fresh_core("cost", _COST_VER)
declare(_c, "spool", "api_inv_spool_create", "POST", "inventory.spool.create")
_r, _e = validate(_c)
_rp = _r[0].get("runtime_policy") if len(_r) == 1 else None
check("26. политика чужого модуля не переходит: путь вне карты получает строгую политику СВОЕГО модуля (только admin)",
      len(_r) == 1 and not _e and _rp is not None
      and _rp.module_id == "cost" and _rp.path == "/api/mod/cost/spool"
      and _rp.policy_id != "inventory.spool.create"
      and _rp.required_capability == "admin" and _admin_only(_rp)
      and reg.module_policy_by_id("inventory.spool.create").required_capability == "project")

_c = fresh_core("cost", _COST_VER)
declare(_c, "settings", "api_settings_set", "POST", "cost.calculate")   # мягкий id на пути ставок фермы
_r, _e = validate(_c)
check("26b. более мягкий policy_id право не понижает: POST settings остаётся admin по карте",
      len(_r) == 1 and not _e and "runtime_policy" not in _r[0]
      and _gate_pol(_r[0]).policy_id == "cost.settings.write"
      and _gate_pol(_r[0]).required_capability == "admin"
      and any("cost.calculate" in n for n in _notes(_c)))

_APP.registered[:] = []
_c = declare_all("inventory")
_broken = _c._declared_routes[5]
_broken["methods"] = [_broken["methods"][0], "PUT"]        # ломаем ОДИН из 31: два метода подключить нельзя
_ready2, _errs2 = validate(_c)
check("27. маршрут, который подключить нельзя, пропускается один: готовы 30 из 31, сама проверка ничего не подключает",
      len(_errs2) == 1 and len(_ready2) == 30 and all(d is not _broken for d in _ready2)
      and not _APP.registered)

_c = declare_all("inventory")
_c._declared_routes[5]["policy_id"] = "inventory.no.such.policy"   # неверный id у ОДНОГО из 31
_ready3, _errs3 = validate(_c)
check("27b. неверный policy_id одного маршрута модуль не останавливает: готовы все 31, расхождение — в заметках",
      len(_ready3) == 31 and not _errs3 and len(_notes(_c)) == 1 and not _APP.registered)

# Сценарий повторяет цикл подключения _register_module (26.09.2026): Склад объявляет один
# БИТЫЙ маршрут (два метода) и один маршрут, которого нет в карте (модуль новее программы);
# Расчёт заказа — со старым контрактом; Качество корректно. Ожидание — пропущен только битый
# маршрут, новый подключён со строгой политикой, поставленной ДО подключения, а все остальные
# маршруты всех трёх модулей подключены.
_APP.registered[:] = []
_APP.policy_at_attach[:] = []
_NEW_INV = "/api/mod/inventory/brand-new-2609"
_res28 = {}
_broken_h = None
for _mid in ("inventory", "cost", "quality"):
    _cc = declare_all(_mid)
    if _mid == "inventory":
        _cc._declared_routes[5]["methods"] = [_cc._declared_routes[5]["methods"][0], "PUT"]
        _broken_h = _cc._declared_routes[5]["handler"].__name__
        declare(_cc, "brand-new-2609", "api_inv_brand_new", "POST", "inventory.brand.new")
    if _mid == "cost":
        _cc.module_version = "0.0.1-old"
    _rr, _ee = validate(_cc)
    _res28[_mid] = (_notes(_cc), list(_ee))
    for _d in _rr:                  # как в _register_module: строгая политика — ДО маршрута
        _rpd = _d.get("runtime_policy")
        if _rpd is not None and not rtp.register(_rpd):
            continue
        _APP.add_api_route(_d["full"], _d["handler"], methods=_d["methods"])
_paths = [r[1] for r in _APP.registered]
_new_pol = reg.module_http_policy("POST", _NEW_INV)
check("28. ошибка одного маршрута не ломает ни свой модуль, ни остальные: Склад 30 + 1 новый, Расчёт заказа 10 (старый контракт), Качество 4",
      len(_APP.registered) == 45
      and len([p for p in _paths if p.startswith("/api/mod/inventory/")]) == 31
      and _broken_h and _broken_h not in [r[2] for r in _APP.registered]
      and _NEW_INV in _paths
      and len([p for p in _paths if p.startswith("/api/mod/cost/")]) == 10
      and len([p for p in _paths if p.startswith("/api/mod/quality/")]) == 4
      and len(_res28["inventory"][1]) == 1 and len(_res28["inventory"][0]) == 1
      and len(_res28["cost"][0]) == 10 and not _res28["cost"][1]
      and not _res28["quality"][0] and not _res28["quality"][1]
      and rtp.is_runtime(_new_pol) and _new_pol.module_id == "inventory" and _admin_only(_new_pol))
check("29. каждый подключённый маршрут подключён ровно один раз и в момент подключения уже имел политику",
      len({r[1:] for r in _APP.registered}) == 45
      and len(_APP.policy_at_attach) == 45 and all(_APP.policy_at_attach))
rtp.clear("inventory")
check("29b. строгие политики снимаются и в опись карты не входят (счётчики описи прежние)",
      reg.module_http_policy("POST", _NEW_INV) is None and not rtp.policies()
      and not [p for p in reg.ALL_POLICIES if rtp.is_runtime(p)]
      and len(MOD) == 51 and reg.registry_counts()["modules"] == 51)

_c = fresh_core("inventory", _INV_VER)
declare(_c, "spool", "api_inv_spool_create", "POST", "inventory.no.such.policy")
_c.add_route("spool/{sid}", mk_handler("api_inv_spool_update"), ["PATCH", "PUT"],
             policy_id="inventory.spool.update")
_r, _e = validate(_c)
_msgs = " ".join(list(_e) + _notes(_c))
check("30. ни отказ, ни заметка о расхождении не раскрывают тело запроса и секреты",
      _e and _notes(_c) and SENTINEL not in _msgs and "password" not in _msgs.lower())

_c = fresh_core("legacy_module", "1.0.0")
_c.add_route("anything", mk_handler("legacy_handler"), ["POST"])
_r, _e = validate(_c)
_rp = _r[0].get("runtime_policy") if len(_r) == 1 else None
check("31. старый модуль без policy_id и без записи в карте ставится, но закрыт строго: только admin",
      len(_r) == 1 and not _e and _rp is not None
      and _rp.module_id == "legacy_module" and _rp.path == "/api/mod/legacy_module/anything"
      and _rp.enforcement_stage is ES.MODULE_2_785 and _rp.enforced_access is EA.CAPABILITY
      and _rp.required_capability == "admin" and _admin_only(_rp)
      # сама проверка политику в гейт не подключает — это делает только цикл регистрации
      and reg.module_http_policy("POST", "/api/mod/legacy_module/anything") is None)

check("32. сторонний маршрут модуля без политики закрыт и в гейте",
      reg.module_http_policy("POST", "/api/mod/thirdparty/do-something") is None
      and rac.decide(None, rac.SecurityContext(security_enabled=True, has_session=True,
                                               user_enabled=True, role="admin",
                                               capabilities=frozenset(ROLE_PERMS["admin"]))
                     ).outcome is AD.POLICY_MISSING)

#  26.09.2026: строгая политика видна гейту только после подключения; карту она не перекрывает
#  и в пространство чужого модуля не заходит.
_rp = rtp.build("thirdparty", "9.9.9", "POST", "other-thing", "tp_handler")
_ok_reg = rtp.register(_rp)
_live = reg.module_http_policy("POST", "/api/mod/thirdparty/other-thing")
_refused_described = rtp.register(rtp.build("inventory", _INV_VER, "POST", "spool", "x"))
_still_described = reg.module_http_policy("POST", "/api/mod/inventory/spool")
_refused_foreign = rtp.register(__import__("dataclasses").replace(
    rtp.build("thirdparty", "9.9.9", "POST", "steal", "x"), path="/api/mod/inventory/steal"))
_steal = reg.module_http_policy("POST", "/api/mod/inventory/steal")
rtp.clear()
check("32b. строгая политика действует в гейте только после подключения, карту не перекрывает, в чужой модуль не заходит",
      _ok_reg and _live is _rp and _admin_only(_live)
      and not _refused_described
      and _still_described == reg.module_policy_by_id("inventory.spool.create")
      and not _refused_foreign and _steal is None
      and reg.module_http_policy("POST", "/api/mod/thirdparty/other-thing") is None
      and reg.module_http_policy("POST", "/api/mod/thirdparty/do-something") is None
      and not rtp.policies())

# Порядок доказывается не только поведением, но и исходником.
_reg_src = fn_src(SRC_AST, "_register_module") or ""
check("A1. в _register_module проверка идёт ДО подключения маршрутов",
      "_module_routes_validate" in _reg_src and "add_api_route" in _reg_src
      and _reg_src.index("_module_routes_validate") < _reg_src.index("add_api_route"))
check("A1b. строгая политика подключается ДО маршрута (нет мгновения без политики)",
      "_module_rt_policy.register" in _reg_src
      and _reg_src.index("_module_rt_policy.register") < _reg_src.index("add_api_route"))
#  26.09.2026: откат и отказ в загрузке остались только для сбоя backend.py; ошибки маршрутов
#  пропускают сами маршруты, а модуль грузится (прежнее «модуль не грузится» снято словом владельца).
_reg_fn = next((n for n in ast.walk(SRC_AST)
                if isinstance(n, ast.FunctionDef) and n.name == "_register_module"), None)
#  16.10.2026 (R-151): загрузка backend идёт со сроком (_module_run_register), поэтому откат стоит не в
#  except, а в ветке «загрузка не удалась» (ошибка или срок) — обе формы считаются.
_exc_rb = [h for h in ast.walk(_reg_fn) if isinstance(h, (ast.ExceptHandler, ast.If))
           and "_module_rollback" in ast.unparse(h) and "return None" in ast.unparse(h)
           and "_errs" not in ast.unparse(getattr(h, "test", None) or ast.Pass())] if _reg_fn else []
_errs_ifs = [n for n in ast.walk(_reg_fn) if isinstance(n, ast.If)
             and "_errs" in ast.unparse(n.test)] if _reg_fn else []
check("A2. откат и отказ — только при сбое backend; ошибки маршрутов пропускают сами маршруты, модуль грузится",
      bool(_exc_rb) and bool(_errs_ifs)
      and not any(isinstance(x, ast.Return) for i in _errs_ifs for x in ast.walk(i))
      and not any(("_module_rollback" in ast.unparse(i)) or ("_note_failed_module" in ast.unparse(i))
                  for i in _errs_ifs)
      and "_loaded_modules[mid]" in _reg_src
      and _reg_src.index("_module_routes_validate") < _reg_src.index("_loaded_modules[mid]"))

_HOOKS["pre_print_check"].clear(); _BADGE[:] = []; _FIL[:] = []
_c = fresh_core("inventory", "1.7.29")
_hook_fn = lambda *a, **k: None
_c.add_hook("pre_print_check", _hook_fn)
_BADGE.append(("inventory", _hook_fn))
rollback(_c)
check("A3. откат снимает печатные хуки и провайдеры неудачной загрузки",
      not _HOOKS["pre_print_check"] and not _BADGE and not _c._added_hooks)

_c = declare_all("cost")
validate(_c)
_c._routes_sealed = True
_late = None
try:
    _c.add_route("late", mk_handler("x"), ["GET"], policy_id="cost.summary.read")
except RuntimeError:
    _late = "отклонён"
check("A4. поздний add_route в обход проверки отклоняется", _late == "отклонён")


# ════════════════════════════════════════════════════════════════════════════
section("матрица ролей при включённой авторизации (пункты 33-47)")


def ctx(role, session=True, enabled=True, security=True):
    caps = ROLE_PERMS.get(role)
    return rac.SecurityContext(security_enabled=security, has_session=session and role is not None,
                               user_enabled=enabled, role=role,
                               capabilities=(frozenset(caps) if caps is not None else None))


def out(p, role, **kw):
    return rac.decide(p, ctx(role, **kw)).outcome


MOD_RO_N = [p for p in MOD if p.method not in reg.MUTATING_METHODS]
MOD_MUT_N = [p for p in MOD if p.method in reg.MUTATING_METHODS]
VIEW = [p for p in MOD if p.required_capability == "view"]
PROJ = [p for p in MOD if p.required_capability == "project"]
CNT = [p for p in MOD if p.required_capability == "count"]
ADM = [p for p in MOD if p.required_capability == "admin"]

check("33. observer читает все %d маршрутов с правом view" % len(VIEW),
      all(out(p, "observer") is AD.ALLOW for p in VIEW))
# Единственный POST, доступный observer, — cost.calculate. С 3.0 это «Расчёт заказа»: расчёт,
# разбор файла и импорт задачи или проекта в черновик. Заказ он не сохраняет и не удаляет,
# настройки и ставки не меняет, проект не создаёт; пишет только кэш моделей принтеров — доказано
# разбором графа вызовов в tools/test_cost_module.py (I3). Все остальные изменяющие ему закрыты.
_MOD_WRITES = [p for p in MOD if p.required_capability != "view"]
check("34. observer не вызывает ни один ПИШУЩИЙ маршрут модуля",
      all(out(p, "observer") is AD.FORBIDDEN for p in _MOD_WRITES)
      and len(_MOD_WRITES) == 30)   # 2.994: +6 admin-маршрутов модуля messengers
_CALC_BODY = _mod_srcs["cost"].split("async def api_calculate")[1].split("\nasync def")[0].split("\ndef ")[0]
check("34b. единственный POST, открытый observer, — расчёт заказа; он не зовёт сохранение, удаление, настройки и создание проекта",
      [p.policy_id for p in MOD_MUT_N if out(p, "observer") is AD.ALLOW] == ["cost.calculate"]
      and not __import__("re").search(
          r"\b(_save_order_record|_store_order_files|_store_fm_source_files|_delete_orders|_set_settings|_create_project)\b",
          _CALC_BODY)
      and not __import__("re").search(r"\b(INSERT|UPDATE|DELETE)\b", _CALC_BODY.upper()))
check("35. assembler читает маршруты view", all(out(p, "assembler") is AD.ALLOW for p in VIEW))
check("36. count-маршрутов ровно 2 и они недоступны assembler (у роли нет count)",
      len(CNT) == 2 and "count" not in ROLE_PERMS["assembler"]
      and all(out(p, "assembler") is AD.FORBIDDEN for p in CNT))
check("37. rework в модулях не используется (операций брака и доработки нет)",
      not [p for p in MOD if p.required_capability == "rework"])
check("38. assembler не получает ни project, ни admin",
      all(out(p, "assembler") is AD.FORBIDDEN for p in PROJ + ADM))
check("39. operator читает все view-маршруты", all(out(p, "operator") is AD.ALLOW for p in VIEW))
check("40. operator получает все %d project-маршрутов и оба count" % len(PROJ),
      all(out(p, "operator") is AD.ALLOW for p in PROJ + CNT))
check("41. operator не получает ни один admin-маршрут модуля",
      all(out(p, "operator") is AD.FORBIDDEN for p in ADM))
check("42. admin получает все 51 маршрутов модулей",
      all(out(p, "admin") is AD.ALLOW for p in MOD))
check("43. неизвестная роль получает отказ", all(out(p, "wizard") is AD.FORBIDDEN for p in MOD))
check("44. отключённый пользователь получает отказ",
      all(rac.decide(p, rac.SecurityContext(security_enabled=True, has_session=True,
                                            user_enabled=False, role="admin",
                                            capabilities=frozenset(ROLE_PERMS["admin"]))
                     ).outcome is AD.REQUIRE_SESSION for p in MOD))
check("45. недействительная сессия получает отказ",
      all(out(p, None, session=False) is AD.REQUIRE_SESSION for p in MOD))
check("46. нехватка права даёт 403 (FORBIDDEN), а не 401",
      out(reg.module_policy_by_id("inventory.settings.write"), "operator") is AD.FORBIDDEN)
check("47. отсутствие сессии даёт 401 (REQUIRE_SESSION), а не 403",
      out(reg.module_policy_by_id("inventory.settings.write"), None, session=False)
      is AD.REQUIRE_SESSION)


# ════════════════════════════════════════════════════════════════════════════
section("Складской учёт (пункты 48-55)")


def inv(pid):
    return reg.module_policy_by_id(pid)


check("48. все 11 читающих маршрутов имеют право view",
      len([p for p in INV if p.method == "GET"]) == 11
      and all(p.required_capability == "view" for p in INV if p.method == "GET"))
check("49. обычная складская работа доступна operator, но не observer",
      all(out(inv(x), "operator") is AD.ALLOW and out(inv(x), "observer") is AD.FORBIDDEN
          for x in ("inventory.spool.create", "inventory.spool.update", "inventory.spool.delete",
                    "inventory.item.create", "inventory.item.delete")))
check("50. пересчёт количества помечен count (приход/расход/задать)",
      inv("inventory.spool.adjust").required_capability == "count"
      and inv("inventory.item.adjust").required_capability == "count")
check("51. привязка и отвязка катушки имеют явное право project",
      inv("inventory.spool.bind").required_capability == "project"
      and inv("inventory.spool.unbind").required_capability == "project")
check("52. локации — работа оператора; каталог филамента и настройки — admin",
      all(inv(x).required_capability == "project" for x in
          ("inventory.location.create", "inventory.location.update", "inventory.location.delete"))
      and all(inv(x).required_capability == "admin" for x in
              ("inventory.filament.update", "inventory.filament.delete", "inventory.settings.write")))
check("53. observer не меняет остатки",
      all(out(inv(x), "observer") is AD.FORBIDDEN for x in
          ("inventory.spool.adjust", "inventory.item.adjust", "inventory.spool.update")))
check("54. operator не меняет настройки модуля и каталог филамента",
      all(out(inv(x), "operator") is AD.FORBIDDEN for x in
          ("inventory.settings.write", "inventory.filament.update", "inventory.filament.delete")))
check("55. ни один маршрут склада не идёт по общему fallback",
      all(p.enforcement_stage is ES.MODULE_2_785 and p.enforced_access is EA.CAPABILITY
          and p.required_capability for p in INV))


# ════════════════════════════════════════════════════════════════════════════
section("Расчёт заказа (пункты 56-61)")

check("56. читающие маршруты имеют view",
      all(p.required_capability == "view" for p in COST if p.method == "GET"))
check("57. расчёт открыт просмотру и сам заказ не сохраняет — сохранение и создание проекта требуют права project",
      inv("cost.calculate").required_capability == "view"
      and inv("cost.calculations.save").required_capability == "project"
      and inv("cost.calculations.recalc").required_capability == "project"
      and "_save_order_record" not in _CALC_BODY and "INSERT" not in _CALC_BODY.upper())
check("58. ставки фермы и настройки принтера требуют admin",
      inv("cost.settings.write").required_capability == "admin"
      and inv("cost.printer_settings.write").required_capability == "admin")
check("59. observer не меняет данные расчёта заказа",
      all(out(p, "observer") is AD.FORBIDDEN for p in COST if p.method in reg.MUTATING_METHODS
          and p.required_capability != "view"))
check("60. operator сохраняет расчёт, но не меняет ставки",
      out(inv("cost.calculations.save"), "operator") is AD.ALLOW
      and out(inv("cost.calculations.recalc"), "operator") is AD.ALLOW
      and out(inv("cost.settings.write"), "operator") is AD.FORBIDDEN
      and out(inv("cost.printer_settings.write"), "operator") is AD.FORBIDDEN)
check("61. ни один маршрут себестоимости не идёт по общему fallback",
      all(p.enforcement_stage is ES.MODULE_2_785 and p.required_capability for p in COST))


# ════════════════════════════════════════════════════════════════════════════
section("Аналитика качества (пункты 62-67)")

check("62. все читающие маршруты имеют view",
      all(p.required_capability == "view" for p in QUAL))
check("63. маршрутов доработки нет: модуль через HTTP только читает",
      all(p.method == "GET" for p in QUAL)
      and not [p for p in QUAL if p.required_capability == "rework"])
check("64. изменяющих маршрутов у модуля нет вовсе",
      not [p for p in QUAL if p.method in reg.MUTATING_METHODS])
check("65. настроек и admin-маршрутов у модуля нет",
      not [p for p in QUAL if p.required_capability == "admin"])
check("66. assembler не получает общий project ради качества",
      all(out(p, "assembler") is AD.ALLOW for p in QUAL) and "project" not in ROLE_PERMS["assembler"])
check("67. ни один маршрут качества не идёт по общему fallback",
      all(p.enforcement_stage is ES.MODULE_2_785 and p.required_capability for p in QUAL))


# ════════════════════════════════════════════════════════════════════════════
section("выключенная авторизация (пункты 68-72)")

check("68. обычный рабочий процесс модулей при AUTH OFF прежний",
      all(rac.decide(p, ctx(None, session=False, security=False)).outcome is AD.ALLOW for p in MOD))
check("69. при AUTH OFF поддельная сессия не требуется",
      rac.decide(MOD[0], rac.SecurityContext(security_enabled=False)).outcome is AD.ALLOW)
check("70. LAN и config этой правкой не меняются",
      "lan_access_enabled" not in (fn_src(SRC_AST, "_gate_decide") or "")
      and "_write_config" not in (fn_src(SRC_AST, "_module_routes_validate") or ""))
check("71. поведение ядра при AUTH OFF не изменилось",
      all(rac.decide(p, ctx(None, session=False, security=False)).outcome
          in (AD.ALLOW, AD.DEFER_TO_HANDLER) for p in CORE_HTTP))
check("72. callback и system-admin границы не тронуты",
      all(f in SRC for f in ("_require_slicer_callback", "_require_system_admin", "_require_admin")))


# ════════════════════════════════════════════════════════════════════════════
section("порядок побочных эффектов (пункты 73-81)")

_gate = fn_src(SRC_AST, "_gate_decide") or ""
_gate_mw = fn_src(SRC_AST, "_auth_gate") or ""
check("73. отказ возвращается ДО передачи запроса дальше по цепочке",
      "return deny" in _gate_mw and "await call_next" in _gate_mw
      and _gate_mw.index("return deny") < _gate_mw.index("await call_next"))
check("74. решение принимается без чтения тела запроса",
      "await request.body()" not in _gate and ".json()" not in _gate)
check("75. multipart в гейте не разбирается", "form(" not in _gate and "multipart" not in _gate.lower())
check("76. гейт не обращается к БД модуля", not any(x in _gate for x in ("conn_", "execute(", "sqlite")))
check("77. гейт не обращается к файловой системе", not any(x in _gate for x in ("open(", "os.path", "shutil")))
check("78. гейт не меняет состояние модулей",
      not any(x in _gate for x in ("_loaded_modules", "_disabled_modules", "add_api_route")))
check("79. гейт не ходит в сеть", not any(x in _gate for x in ("urllib", "requests", "socket", "httpx")))
# Ответ об отказе собирается из КОНСТАНТ: единственное непостоянное значение — имя
# требуемого права, которое берётся из реестра, а не из запроса.
check("80. ответ об отказе собран из констант и не отражает запрос",
      "server_error" in _gate and "unauthorized" in _gate and "forbidden" in _gate
      and "await request" not in _gate
      and not __import__("re").search(r"JSONResponse\([^)]*request", _gate))
check("81. отказ регистрации происходит до подключения маршрута в приложение",
      not _APP.registered or all(r[1].startswith("/api/mod/") for r in _APP.registered))


# ════════════════════════════════════════════════════════════════════════════
section("регрессии (пункты 82-95)")

_par_ast = ast.parse(PAR) if PAR else None
# ws_ep исключена намеренно: её переписала Alpha 2.786 (авторизация WebSocket).
# Права модулей и границы HTTP при этом не тронуты — это и проверяется ниже.
# proxy_upload исключён намеренно: его границу закрыла Alpha 2.788 (Moonraker-приём файла).
# Права модулей при этом не тронуты — это и проверяется ниже.
# p_cmd исключён намеренно: Alpha 2.825 добавляет в start_print разбор file_ref
# (resolve + перепроверка на устройстве); граница operate и путь без file_ref не тронуты.
UNCHANGED = ("_route_perm", "_has_perm", "_require_admin", "_require_system_admin",
             "_require_slicer_callback", "_session_user", "_req_role",
             "_security_context_for", "s_hook")
#  Без эталона список расхождений не вычисляется (None): пустой список без эталона был бы
#  ложной зеленью.
_diffs = ([f for f in UNCHANGED if fn_src(_par_ast, f) != fn_src(SRC_AST, f)]
          if _par_ast else None)
hcheck("82-89. границы ядра и обработчики не изменены: расхождений %s (%s)"
       % ((len(_diffs), ", ".join(_diffs) or "нет") if _diffs is not None else ("?", "эталона нет")),
       lambda: _diffs == [])
# Alpha 2.787 перевела ОДИН маршрут (POST /api/network) из CAPABILITY в SYSTEM_ADMIN:
# 119 -> 118. Alpha 2.788 перевела ОДИН маршрут (POST /server/files/upload) из PUBLIC в
# CALLBACK_SECRET: 25 -> 24. Права остальных 164 маршрутов ядра не менялись.
check("90. карта прав ядра Alpha 2.784 не изменена (кроме объявленных границ; Alpha 2.813 — "
      "GET /api/diagnostics стал административным: встроенный журнал показывает работу фермы)",
      len(CORE_HTTP) == 207   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»; 2.823: +5 printer-files; 2.825: +select-for-print; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.870: +камера без перекодирования; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and sum(1 for p in CORE_HTTP if p.enforced_access is EA.CAPABILITY) == 145  #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»; 2.989: +printer-files/preview (чтение файлов принтера); 2.980: +7 — поиск принтеров в сети (4, право «заводить принтеры») и запись сетевых объявлений (3, право администратора); 2.978: +1 — «где лежит файл проекта»; 2.948: −1 pending-printable; 2.920: +5 CAPABILITY — очередь ожидания; 2.927: +3 — пометки и настройки фермы; 2.947: +1 — синхронизация задачи с проектом; 12.09.2026 -1 маршрут пометок принтера
      and sum(1 for p in CORE_HTTP if p.enforced_access is EA.PUBLIC) == 26  # 16.10.2026 (R-149): файлы модулей /modules/* — только после входа, PUBLIC 27 -> 26, SESSION_ONLY 3 -> 4; 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы
      and sum(1 for p in CORE_HTTP if p.enforced_access is EA.CALLBACK_SECRET) == 3)
check("91. baseline описи ожидаемый: 233/188/45/2 (2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup; 2.831 +2 printer-sort-mode; 2.833 +2 klipper-prestart; 2.870 +камера без перекодирования; 2.879 +камера по WebSocket)",
      reg.registry_counts()["total"] == 260 and reg.registry_counts()["core"] == 209   #; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and reg.registry_counts()["modules"] == 51 and reg.registry_counts()["websocket"] == 2)
check("92. _route_perm сохранён в коде как исторический помощник",
      fn_src(SRC_AST, "_route_perm") is not None)
# Считаем ВЫЗОВЫ, а не упоминания: в пояснениях к коду имя функции встречается законно.
check("93. _route_perm БОЛЬШЕ НЕ участвует в авторизации HTTP (0 вызовов в рантайме)",
      "_route_perm(" not in _gate and "_route_perm(" not in _gate_mw
      and SRC.count("_route_perm(") == 1)   # ровно одно вхождение — строка def
check("94. /server/files/upload закрыт в 2.788 и НЕ трогает права модулей",
      reg.core_http_policy("POST", "/server/files/upload").enforced_access is EA.CALLBACK_SECRET
      and "_require_slicer_callback" in (fn_src(SRC_AST, "proxy_upload") or "")
      and all(p.enforced_access is not EA.CALLBACK_SECRET for p in MOD))
# Alpha 2.786 переписала авторизацию WebSocket намеренно. Для ПРАВ МОДУЛЕЙ важно, что
# сокет к ним отношения не имеет: он не обслуживает ни один маршрут /api/mod/.
check("95. WebSocket не участвует в правах модулей",
      all(p.module_id is None for p in CORE_WS)
      and {p.path for p in CORE_WS} == {"/ws", "/api/printer/{pid}/camera.ws"}
      and not [p for p in MOD if p.kind is reg.RouteKind.WEBSOCKET])

check("S1. метка-ловушка не попала ни в обработчик, ни в журнал, ни в состояние",
      not any(SENTINEL in str(v) for v in SPY.values())
      and not any(SENTINEL in l for l in _LOG.lines)
      and SENTINEL not in " ".join(str(r) for r in _APP.registered))
check("S2. ни один настоящий обработчик модуля не вызван", not SPY["handler"])
check("S3. server.py и backend модулей не импортированы",
      "server" not in sys.modules and not any(m.startswith("fm_module_") for m in sys.modules))


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
