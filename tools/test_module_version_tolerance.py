# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  26.09.2026 — любая версия модуля ставится и работает; «есть новее» — только предупреждение.
#
#  ЗАЧЕМ. Слово владельца: «Нужно, чтобы устанавливалась любая версия модуля, независимо от её
#  версии. Если программа знает, что есть более новая версия, она просто предупреждает. И даже
#  если модуль новее, чем знает программа, он всё-таки должен установиться.» До этой правки:
#    * модуль ДРУГОЙ версии, чем записана в карте прав ядра, не загружался вовсе («Требуется
#      обновление») — и старый, и новее программы (так было со складом 1.7.30 при карте 1.7.29);
#    * маршрут, которого нет в карте прав, отменял загрузку ВСЕГО модуля.
#
#  ЧТО ПРОВЕРЯЕТСЯ. Настоящие функции server.py (разбор AST) и настоящая карта прав:
#    1) таблица известных выпусков совпадает с module.json модулей проекта — страж рассинхрона;
#    2) сравнение номеров выпусков;
#    3) проверка маршрутов: старая, новая и «новее программы» версии проходят; право маршрута
#       берётся из карты по методу и пути (тем же ключом, что у гейта при каждом запросе);
#    4) маршрут, которого карта не знает, — только администратору при включённой защите;
#    5) полная загрузка модуля из папки (_register_module): старый, новый, с испорченным
#       core_contract; модуль с падающим backend.py по-прежнему не загружается;
#    6) установка из zip: версия не проверяется, ответ сообщает прежнюю версию и «есть новее»;
#    7) интерфейс показывает пометки, а не отказ.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: server.py не импортируется и не запускается; модули ставятся только во
#  временную папку; рабочие DATA_DIR/БД/config не трогаются; сети нет.
#
#  Запуск:  python tools/test_module_version_tolerance.py   (0 = всё пройдено)
# ============================================================================
import ast
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import types
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from app import route_policy_registry as R          # noqa: E402
from app import route_access_control as RA          # noqa: E402
from app import module_catalog as MC                # noqa: E402
from app import module_runtime_policy as MRP        # noqa: E402
#  26.09.2026: проверка подписанного пакета и служба лицензий — настоящие модули проекта; ключей
#  у службы нет, поэтому все модули набора — «без подписи», как и раньше.
from app.licensing import package as LPKG            # noqa: E402
from app.licensing import service as LSVC            # noqa: E402

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" :: %s" % (extra,)) if extra != "" else ""))


def section(t):
    print("\n--- %s ---" % t)


SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRV)


def fn_node(name):
    for n in TREE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            return n
    raise AssertionError("в server.py нет %s" % name)


def assign_node(name):
    for n in TREE.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return n
    raise AssertionError("в server.py нет %s" % name)


class _Log:
    def __init__(self): self.lines = []
    def _r(self, *a, **k): self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = _r


class _App:
    def __init__(self): self.routes = []
    def add_api_route(self, path, handler, methods=None):
        self.routes.append((tuple(methods or ()), path, getattr(handler, "__name__", "")))
    def get(self, *a, **k): return lambda f: f
    post = get


LOG = _Log()
APP = _App()
NS = {"re": re, "os": os, "_jsonmod": json, "_ilu": importlib.util, "_zipfile": zipfile, "_iomod": io, "_shutil": shutil,
      "log": LOG, "app": APP, "_route_registry": R, "_route_access": RA, "_module_catalog": MC,
      "_module_rt_policy": MRP, "_exc_brief": lambda: "ошибка (кратко)",
      "_loaded_modules": {}, "_failed_modules": {}, "_disabled_modules": {}, "_registered_backends": set(),
      "_print_hooks": {"pre_print_check": [], "after_dispatch": [], "print_run_started": [], "print_run_finished": []},
      "_printer_badge_providers": [], "_printer_filament_providers": [], "_modules_restart_needed": False,
      "_lic_pkg": LPKG, "_LICENSES": LSVC.LicenseService(tempfile.mkdtemp(prefix="fm_modver_lic_"), trusted={}),
      "secrets": __import__("secrets"), "time": __import__("time"),
      #  16.10.2026 (R-151): загрузка модуля со сроком и общий замок подписок
      "threading": __import__("threading"), "_hooks_lock": __import__("threading").RLock(), "_hook_owner": {}}
_nodes = [assign_node(n) for n in ("MODULE_STATE_LOADED", "MODULE_STATE_DISABLED", "MODULE_STATE_VERSION_MISMATCH",
                                   "MODULE_STATE_ROUTE_MISMATCH", "MODULE_STATE_INVALID_MANIFEST",
                                   "MODULE_STATE_LOAD_ERROR", "MODULE_STATE_PENDING_RESTART",
                                   "MODULE_STATE_INTEGRITY_FAILED", "MODULE_STATE_PACKAGE_UNTRUSTED", "MODULE_STATES",
                                   "MODULE_REGISTER_DEADLINE_S", "MODULE_REGISTER_WARN_S")]
_nodes += [fn_node(n) for n in ("_module_id_ok", "_read_manifest", "ModuleCore", "_load_modules",
                                "_modules_disabled_ids", "_module_routes_validate", "_module_rollback",
                                "_module_failure_state", "_module_expected_version", "_note_failed_module",
                                "_module_core_contract", "_register_module", "api_modules_list",
                                "_modules_install_bytes", "_module_licensing_view", "_module_feature_gate",
                                "_fs_retry", "_rm_dir_or_link", "_module_swap_recover", "_module_run_register")]
_mod = ast.Module(body=_nodes, type_ignores=[])
exec(compile(ast.fix_missing_locations(_mod), "server_modules", "exec"), NS)
validate = NS["_module_routes_validate"]

print("=== 26.09.2026: любая версия модуля ===")

# ════════════════════════════════════════════════════════════════════════════
section("1. программа знает те же выпуски, что лежат в проекте (страж рассинхрона)")
repo_versions = {}
for mid in sorted(os.listdir(os.path.join(REPO, "modules"))):
    mj = os.path.join(REPO, "modules", mid, "module.json")
    if os.path.isfile(mj):
        repo_versions[json.loads(io.open(mj, encoding="utf-8").read())["id"]] = \
            json.loads(io.open(mj, encoding="utf-8").read())["version"]
#  26.09.2026: в открытой выгрузке части модулей нет (придержаны до решения владельца) — там
#  сверяются только те, что есть; в закрытом репозитории списки обязаны совпасть целиком.
_PUBLIC = os.path.isfile(os.path.join(REPO, "packaging", "PUBLIC_TREE.md"))
_known = {k: v for k, v in MC.KNOWN_MODULE_RELEASES.items() if (k in repo_versions or not _PUBLIC)}
check("1. для каждого модуля проекта программа знает его выпуск, и номера совпадают "
      "(поднял версию модуля — впиши её в app/module_catalog.py)",
      repo_versions == _known and set(repo_versions) <= set(MC.KNOWN_MODULE_RELEASES),
      {"проект": repo_versions, "программа": MC.KNOWN_MODULE_RELEASES})

section("2. сравнение номеров")
check("2. 1.7.30 новее 1.7.4 (числа, а не строки)", MC.compare_versions("1.7.30", "1.7.4") == 1)
check("3. 1.7 и 1.7.0 — одно и то же", MC.compare_versions("1.7", "1.7.0") == 0)
check("4. 0.2.1 старее 0.10.0", MC.compare_versions("0.2.1", "0.10.0") == -1)
for _a, _b, _e in (("1.10", "1.9", 1), ("1.8.0", "1.8.0-beta", 1), ("1.8.0-rc1", "1.8.0", -1),
                   ("2.0.0", "v1.0.0", 1), ("v1.2", "1.2", 0), ("1.7.30", "1.7.30+build5", 0),
                   ("1.8.0-beta.2", "1.8.0-beta.10", -1), ("", "0.0.1", -1)):
    check("4b. %s против %s: %+d" % (_a, _b, _e), MC.compare_versions(_a, _b) == _e)
check("4c. нестандартные цифры в номере не роняют список модулей", MC.version_key("0.2.³") is not None)
check("5. предупреждение «есть новее» — только когда программа знает выпуск новее установленного",
      MC.newer_known("inventory", "1.7.20") == MC.KNOWN_MODULE_RELEASES["inventory"]
      and MC.newer_known("inventory", MC.KNOWN_MODULE_RELEASES["inventory"]) == ""
      and MC.newer_known("inventory", "9.0.0") == "" and MC.newer_known("unknown_mod", "0.1") == ""
      and MC.newer_known("inventory", "") == ""
      and MC.newer_known("inventory", "1.7.30-rc1") == MC.KNOWN_MODULE_RELEASES["inventory"])

# ════════════════════════════════════════════════════════════════════════════
section("3. проверка маршрутов модуля по карте прав")


def declarations(module_id):
    src = io.open(os.path.join(REPO, "modules", module_id, "backend.py"), encoding="utf-8").read()
    reg = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "register")
    out = []
    for n in ast.walk(reg):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_route"):
            continue
        rel = ast.literal_eval(n.args[0])
        methods = ast.literal_eval(n.args[2]) if len(n.args) > 2 else ["GET"]
        pid = next((ast.literal_eval(k.value) for k in n.keywords if k.arg == "policy_id"), None)
        handler = n.args[1].id if isinstance(n.args[1], ast.Name) else getattr(n.args[1], "attr", "")
        out.append({"rel": rel, "full": "/api/mod/%s/%s" % (module_id, rel), "methods": [str(m).upper() for m in methods],
                    "policy_id": pid, "handler": types.SimpleNamespace(__name__=handler)})
    return out


def run(module_id, contract, routes=None):
    core = types.SimpleNamespace(module_id=module_id, module_version=contract,
                                 _declared_routes=routes if routes is not None else declarations(module_id))
    ready, errors = validate(core)
    return ready, errors, list(getattr(core, "_route_notes", []))


INV = declarations("inventory")
_reg_contract = next(p.module_version for p in R.MODULE_POLICIES if p.module_id == "inventory")
ready, errs, notes = run("inventory", _reg_contract)
check("6. склад с контрактом из карты: все маршруты готовы, без заметок и без строгих политик",
      len(ready) == len(INV) >= 30 and not errs and not notes and not any("runtime_policy" in d for d in ready))
ready, errs, notes = run("inventory", "1.7.20")
check("7. СТАРЫЙ склад (контракт 1.7.20) больше не отвергается: все маршруты готовы",
      len(ready) == len(INV) and not errs, errs[:3])
check("8. расхождение номера записано в заметки, а не в отказ", any("1.7.20" in n for n in notes))
ready, errs, notes = run("inventory", "1.9.0")
check("9. склад НОВЕЕ программы (контракт 1.9.0): все маршруты готовы", len(ready) == len(INV) and not errs)
check("10. известные карте маршруты новее программы получают право ИЗ КАРТЫ, а не строгое",
      not any("runtime_policy" in d for d in ready))

_extra = [dict(d) for d in declarations("inventory")] + [
    {"rel": "brand-new-report", "full": "/api/mod/inventory/brand-new-report", "methods": ["GET"],
     "policy_id": "inventory.brand_new.read", "handler": types.SimpleNamespace(__name__="api_brand_new")}]
ready, errs, notes = run("inventory", "1.9.0", _extra)
_new = [d for d in ready if d["rel"] == "brand-new-report"]
check("11. маршрут, которого карта не знает, НЕ отменяет загрузку модуля: он тоже готов",
      len(ready) == len(INV) + 1 and not errs and len(_new) == 1)
_rp = _new[0].get("runtime_policy") if _new else None
check("12. и получает строгую политику: право admin, этап модулей, доступ по праву",
      _rp is not None and _rp.required_capability == "admin" and _rp.enforced_access is RA.EnforcedAccess.CAPABILITY
      and _rp.enforcement_stage is RA.EnforcementStage.MODULE_2_785 and MRP.is_runtime(_rp))
check("13. заметка об этом маршруте называет его «только администратору»",
      any("brand-new-report" in n and "администратор" in n for n in notes))

_dup = declarations("inventory")
_dup.append(dict(_dup[0]))
ready, errs, _n = run("inventory", _reg_contract, _dup)
check("14. повтор того же метода и пути пропускается, остальные маршруты готовы",
      len(ready) == len(INV) and len(errs) == 1)
_multi = declarations("inventory")
_multi[0] = dict(_multi[0], methods=["GET", "POST"])
ready, errs, _n = run("inventory", _reg_contract, _multi)
check("15. маршрут с двумя методами пропускается (подключить его по карте нельзя), остальные готовы",
      len(ready) == len(INV) - 1 and len(errs) == 1)
_ren = declarations("inventory")
_ren[0] = dict(_ren[0], handler=types.SimpleNamespace(__name__="renamed_handler"))
ready, errs, notes = run("inventory", _reg_contract, _ren)
check("16. другое имя обработчика — заметка, а не отказ (право ищется по пути, как у гейта)",
      len(ready) == len(INV) and not errs and any("обработчик" in n for n in notes))
_weak = next(p for p in R.MODULE_POLICIES if p.module_id == "cost" and p.required_capability == "view")
_borrow = [{"rel": "brand-new-thing", "full": "/api/mod/cost/brand-new-thing", "methods": ["POST"],
            "policy_id": _weak.policy_id, "handler": types.SimpleNamespace(__name__=_weak.handler)}]
ready, errs, notes = run("cost", "0.2.0", _borrow)
check("16a. неизвестный маршрут со ЧУЖИМ слабым policy_id своего модуля не получает его право ('view'): только admin",
      len(ready) == 1 and ready[0].get("runtime_policy") is not None
      and ready[0]["runtime_policy"].required_capability == "admin", [d.get("runtime_policy") for d in ready])
_outside = declarations("inventory")
_outside[0] = dict(_outside[0], full="/api/mod/cost/summary")
ready, errs, notes = run("inventory", _reg_contract, _outside)
check("16b. маршрут с адресом вне пространства своего модуля не подключается (права чужого модуля не берутся)",
      len(errs) == 1 and "вне пространства" in errs[0] and len(ready) == len(INV) - 1)


class _DeferredMRP:
    """Карта, где запись маршрута есть, но права у неё нет (DEFERRED): такой маршрут пропускается."""
    def __getattr__(self, k):
        return getattr(MRP, k)

    def described_policy(self, method, path):
        p = MRP.described_policy(method, path)
        return p.__class__(**{**p.__dict__, "enforced_access": RA.EnforcedAccess.DEFERRED}) if p else None


NS["_module_rt_policy"] = _DeferredMRP()
try:
    ready, errs, notes = run("quality", "0.2.3")
finally:
    NS["_module_rt_policy"] = MRP
check("16c. запись карты без действующего права (DEFERRED) — маршрут пропускается, а не открывается",
      not ready and len(errs) == len(declarations("quality")) and all("действующего права" in e for e in errs))
for _mid in ("cost", "quality", "messengers"):
    ready, errs, notes = run(_mid, "0.0.1")
    check("17. %s старой версии (0.0.1) проходит проверку целиком" % _mid,
          ready and not errs and len(ready) == len(declarations(_mid)))

# ════════════════════════════════════════════════════════════════════════════
section("4. строгая политика для неизвестного маршрута")
MRP.clear()
pol = MRP.build("inventory", "1.9.0", "POST", "brand-new/action", "api_x")
check("18. строгая политика подключается и находится гейтом по методу и пути",
      MRP.register(pol) and R.module_http_policy("POST", "/api/mod/inventory/brand-new/action") is pol)


def ctx(role):
    if role is None:
        return RA.SecurityContext(security_enabled=True)
    caps = {"admin": {"view", "operate", "project", "admin"}, "operator": {"view", "operate", "project"},
            "observer": {"view"}}[role]
    return RA.SecurityContext(security_enabled=True, has_session=True, user_enabled=True, role=role,
                              capabilities=frozenset(caps))


D = RA.AccessDecision
check("19. защита включена: оператору — отказ", RA.decide(pol, ctx("operator")).outcome is D.FORBIDDEN)
check("20. наблюдателю — отказ", RA.decide(pol, ctx("observer")).outcome is D.FORBIDDEN)
check("21. без входа — требуется вход", RA.decide(pol, ctx(None)).outcome is D.REQUIRE_SESSION)
check("22. администратору — разрешено", RA.decide(pol, ctx("admin")).outcome is D.ALLOW)
check("23. защита выключена — как у любого маршрута модуля (разрешено)",
      RA.decide(pol, RA.SecurityContext(security_enabled=False)).outcome is D.ALLOW)
_known = next(p for p in R.MODULE_POLICIES if p.module_id == "inventory" and p.method == "GET")
_shadow = MRP.build("inventory", "9", "GET", _known.module_route, "x")
check("24. строгая политика НЕ перекрывает запись карты для того же метода и пути",
      MRP.register(_shadow) is False and R.module_http_policy("GET", _known.path) is _known)
_alien = MRP.build("inventory", "9", "GET", "x", "x")
_alien = _alien.__class__(**{**_alien.__dict__, "path": "/api/printers"})
check("25. путь вне пространства своего модуля строгой политикой не подключается", MRP.register(_alien) is False)
_before = R.registry_counts()
check("26. опись и её счётчики строгие политики не меняют",
      R.registry_counts() == _before and all(not MRP.is_runtime(p) for p in R.ALL_POLICIES))
MRP.clear()
check("27. снятие строгих политик", R.module_http_policy("POST", "/api/mod/inventory/brand-new/action") is None)

# ════════════════════════════════════════════════════════════════════════════
section("5. загрузка модуля из папки целиком")
TMP = tempfile.mkdtemp(prefix="fm_modver_")


def make_module(mid, version, routes, core_contract=None, crash=False):
    d = os.path.join(TMP, "%s_%s" % (mid, version.replace(".", "_")))
    os.makedirs(d, exist_ok=True)
    man = {"id": mid, "ru": "Тест", "en": "Test", "version": version}
    if core_contract is not None:
        man["core_contract"] = core_contract
    io.open(os.path.join(d, "module.json"), "w", encoding="utf-8").write(json.dumps(man, ensure_ascii=False))
    lines = ["def register(core):"]
    if crash:
        lines.append("    raise RuntimeError('backend упал (изображено тестом)')")
    for rel, meth, hname, pid in routes:
        lines.append("    def %s():\n        return {'ok': True}" % hname)
        lines.append("    core.add_route(%r, %s, [%r], policy_id=%r)" % (rel, hname, meth, pid))
    if len(lines) == 1:
        lines.append("    pass")
    io.open(os.path.join(d, "backend.py"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return d


def reset_loader():
    for k in ("_loaded_modules", "_failed_modules", "_disabled_modules"):
        NS[k].clear()
    NS["_registered_backends"].clear()
    APP.routes.clear()
    MRP.clear()


_q = [p for p in R.MODULE_POLICIES if p.module_id == "quality"]
_qroutes = [(p.module_route, p.method, p.handler, p.policy_id) for p in _q]
reset_loader()
mid = NS["_register_module"](make_module("quality", "0.1.0", _qroutes), "user")
_info = NS["_loaded_modules"].get("quality") or {}
check("28. СТАРЫЙ модуль качества 0.1.0 (без core_contract) загружается", mid == "quality" and _info)
check("29. все его маршруты подключены, строгих политик нет",
      len(APP.routes) == len(_q) and _info.get("admin_only_routes") == 0 and not MRP.policies())
_lst = NS["api_modules_list"]()
_row = next(m for m in _lst["modules"] if m["id"] == "quality")
check("30. список модулей: состояние loaded и пометка «есть новее» с известным выпуском",
      _row["state"] == "loaded" and _row["newer_version"] == MC.KNOWN_MODULE_RELEASES["quality"]
      and _row["admin_only_routes"] == 0)

reset_loader()
mid = NS["_register_module"](make_module("quality", "0.9.0", _qroutes + [("brand-new", "GET", "api_q_new", "quality.brand_new")]), "user")
_info = NS["_loaded_modules"].get("quality") or {}
check("31. модуль НОВЕЕ программы с новым маршрутом загружается (раньше — отказ всему модулю)",
      mid == "quality" and _info.get("admin_only_routes") == 1 and len(APP.routes) == len(_q) + 1)
check("32. строгая политика встала ДО подключения нового маршрута и только для него",
      [p.path for p in MRP.policies()] == ["/api/mod/quality/brand-new"])
_row = next(m for m in NS["api_modules_list"]()["modules"] if m["id"] == "quality")
check("33. список модулей: loaded, без «есть новее», с числом функций «только администратору»",
      _row["state"] == "loaded" and _row["newer_version"] == "" and _row["admin_only_routes"] == 1)
check("33a. и признак «новее программы» — контракт модуля новее карты прав", _row.get("newer_than_app") is True)
reset_loader()
mid = NS["_register_module"](make_module("quality", "0.1.0", _qroutes + [("dropped-old", "GET", "api_q_old", "quality.old")]), "user")
_row = next(m for m in NS["api_modules_list"]()["modules"] if m["id"] == "quality")
check("33b. у СТАРОГО модуля с маршрутом, которого карта уже не знает, нет ложного «новее программы»",
      _row["admin_only_routes"] == 1 and _row.get("newer_than_app") is False
      and _row["newer_version"] == MC.KNOWN_MODULE_RELEASES["quality"])

reset_loader()
mid = NS["_register_module"](make_module("quality", "0.2.3", _qroutes, core_contract=""), "user")
check("34. испорченное поле core_contract больше не отменяет загрузку",
      mid == "quality" and "quality" in NS["_loaded_modules"])

reset_loader()
mid = NS["_register_module"](make_module("quality", "0.2.5", _qroutes + [_qroutes[0]]), "user")
_info = NS["_loaded_modules"].get("quality") or {}
check("34a. маршрут, объявленный дважды, пропускается, а модуль всё равно загружается целиком",
      mid == "quality" and _info.get("skipped_routes") == 1 and len(APP.routes) == len(_q))

reset_loader()
_bd = make_module("quality", "0.2.3", [])
_man = json.loads(io.open(os.path.join(_bd, "module.json"), encoding="utf-8").read())
_man["id"] = "{x}"
io.open(os.path.join(_bd, "module.json"), "w", encoding="utf-8").write(json.dumps(_man))
check("34b. id модуля с недопустимыми символами («{x}») не загружается — такой адрес перехватил бы чужие маршруты",
      NS["_register_module"](_bd, "user") is None and not APP.routes)

# две папки одного модуля: загружается одна, и первой — та, чьё имя совпадает с id
DUPROOT = os.path.join(TMP, "dup_modules")
os.makedirs(DUPROOT, exist_ok=True)
for _fold, _ver in (("quality", "0.2.3"), ("quality - Копия", "0.2.0")):
    _src = make_module("quality", _ver, _qroutes)
    shutil.copytree(_src, os.path.join(DUPROOT, _fold))
reset_loader()
NS["_modules_scan_dirs"] = lambda: [(DUPROOT, "user")]
NS["_read_config"] = lambda: {}
NS["_load_modules"]()
_info = NS["_loaded_modules"].get("quality") or {}
check("34c. две папки одного модуля: загружается одна (папка с именем модуля), маршруты — один раз",
      os.path.basename(_info.get("dir", "")) == "quality" and len(APP.routes) == len(_q)
      and _info.get("manifest", {}).get("version") == "0.2.3")

reset_loader()
mid = NS["_register_module"](make_module("quality", "0.2.4", _qroutes, crash=True), "user")
check("35. модуль, чей backend.py падает при запуске, по-прежнему не загружается (load_error)",
      mid is None and NS["_failed_modules"].get("quality", {}).get("state") == "load_error" and not APP.routes)

# ════════════════════════════════════════════════════════════════════════════
section("6. установка из zip: версия не проверяется")
MODDIR = os.path.join(TMP, "user_modules")
NS["MODULES_USER_DIR"] = MODDIR
#  26.09.2026: установка распаковывает в отдельную папку и сохраняет прежнюю версию рядом.
NS["MODULES_STAGING_DIR"] = os.path.join(TMP, "modules_staging")
NS["MODULES_PREVIOUS_DIR"] = os.path.join(TMP, "modules_previous")


def make_zip(mid, version):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("%s/module.json" % mid, json.dumps({"id": mid, "ru": "Качество", "version": version}))
        z.writestr("%s/backend.py" % mid, "def register(core):\n    pass\n")
    return buf.getvalue()


r1 = NS["_modules_install_bytes"](make_zip("quality", "0.2.3"))
check("36. установка текущей версии: ok, прежней нет, предупреждений нет",
      r1.get("status") == "ok" and r1.get("replaced_version") == "" and not r1.get("older_than_replaced")
      and r1.get("newer_version") == "")
r2 = NS["_modules_install_bytes"](make_zip("quality", "0.1.5"))
check("37. установка СТАРОЙ версии поверх новой разрешена: ok",
      r2.get("status") == "ok" and json.loads(io.open(os.path.join(MODDIR, "quality", "module.json"),
                                                      encoding="utf-8").read())["version"] == "0.1.5")
check("38. ответ говорит, что версия старее прежней, и что есть новее",
      r2.get("replaced_version") == "0.2.3" and r2.get("older_than_replaced") is True
      and r2.get("newer_version") == MC.KNOWN_MODULE_RELEASES["quality"])
rb = NS["_modules_install_bytes"](make_zip("{x}", "1.0.0"))
check("39a. zip с недопустимым id не ставится", rb.get("status") == "error" and rb.get("reason") == "bad module id")
r3 = NS["_modules_install_bytes"](make_zip("quality", "5.0.0"))
check("39. установка версии новее, чем знает программа, — ok и без ложных предупреждений",
      r3.get("status") == "ok" and not r3.get("older_than_replaced") and r3.get("newer_version") == "")

# ════════════════════════════════════════════════════════════════════════════
section("7. интерфейс и журнал")
HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
JS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
HINTS = io.open(os.path.join(REPO, "web", "composables", "helpHints.js"), encoding="utf-8").read()
check("40. строка модуля показывает пометку «есть новее» и «новее программы»",
      "есть новее: v" in HTML and "новее программы" in HTML and "l.first && l.newer" in HTML
      and "l.first && l.adminOnly" in HTML)
check("41. данные пометок приходят из /api/modules", "newer: m.newer_version" in JS and "adminOnly: Number(m.admin_only_routes)" in JS
      and "newerThanApp: !!m.newer_than_app" in JS and "skipped: Number(m.skipped_routes)" in JS)
check("41a. пропущенные функции модуля видны в строке («часть функций не подключена»), а «новее программы» — только когда это правда",
      "часть функций не подключена" in HTML and "l.first && l.skipped" in HTML and "l.newerThanApp?" in HTML
      and "часть функций — у администратора" in HTML)
check("42. сообщение после установки говорит о старой версии и о более новой",
      "j.older_than_replaced" in JS and "j.newer_version" in JS)
check("43. подсказка «Установка и обновление» больше не обещает «только новее»",
      "любой версии" in HINTS and "Обновление — тот же файл новее" not in HINTS)
check("44. журнал «Что нового» говорит пользователю о новом правиле",
      "ставится и запускается любая версия модуля" in SRV)
check("45. в журнал сервера расхождение с картой пишется, но без путей и секретов",
      any("карт" in l for l in LOG.lines)
      and not any(TMP in l for l in LOG.lines if "карт" in l or "маршрут" in l))

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 76)
if FAILED:
    print("FAIL: провалено %d из %d" % (len(FAILED), len(FAILED) + PASSED[0]))
    for f in FAILED:
        print("   - %s" % f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % PASSED[0])
sys.exit(0)
