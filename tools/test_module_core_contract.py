# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""23.09.2026 — номер выпуска модуля отделён от его контракта с ядром.

ЖАЛОБА. Доработанному складу присвоили 1.7.30, а ядро ждало строго 1.7.29: модуль не загрузился
(«Установлено 1.7.30, требуется 1.7.29»), хотя его маршруты не менялись. Пришлось вернуть 1.7.29 и
записывать доработки отдельными полями — разные по возможностям сборки жили под одним номером.

КАК ТЕПЕРЬ. Модуль может объявить в module.json поле `core_contract` — номер ВЕРСИИ СВОИХ
МАРШРУТОВ в карте прав ядра. С картой прав сверяется он, а `version` — номер выпуска — меняется
свободно. Поля нет — сверяется `version`, как раньше. Поле есть, но пустое или не строка —
_module_core_contract по-прежнему говорит «манифест негоден».

26.09.2026 — ЛЮБАЯ ВЕРСИЯ МОДУЛЯ ЗАГРУЖАЕТСЯ (слово владельца). Несовпадение контракта с картой
прав, чужой policy_id, другое имя обработчика — больше не отказ, а заметка (core._route_notes).
Испорченное поле core_contract — не отказ: загрузчик сверяет номер выпуска. Новое поведение
целиком закреплено набором tools/test_module_version_tolerance.py; здесь прежние проверки
переведены на него.

ЧТО НЕ ОСЛАБЛЕНО (и это здесь доказывается на НАСТОЯЩЕЙ карте прав и НАСТОЯЩИХ маршрутах модулей):
право маршрута берётся из карты прав по методу и итоговому пути — тем же ключом, по которому гейт
ищет политику при каждом запросе; объявление модуля (policy_id, обработчик, контракт) право не
выбирает. Маршрут, которого карта не знает (чужой метод, лишний маршрут, подменённый путь, чужая
политика), подключается только администратору. Два метода в одном объявлении и повтор метода
и пути по-прежнему не подключаются.

Безопасность прогона: server.py не импортируется (функции берутся дословно разбором исходника),
backend модулей не выполняется (объявления маршрутов читаются разбором), баз и сети нет. Строгая
политика подключается только в память этого процесса и снимается сразу после проверки.

Запуск: python tools/test_module_core_contract.py   (0 = все проверки пройдены)
"""
import ast
import io
import json
import os
import sys
from types import SimpleNamespace as NS

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import route_access_control as RA    # noqa: E402
from app import route_policy_registry as R    # noqa: E402
from app import module_runtime_policy as MRP  # noqa: E402  26.09.2026: строгая политика маршрута, которого нет в карте

SENTINEL = "MODULE_CORE_CONTRACT_SENTINEL_2309"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_TREE = ast.parse(SRV)
_WANT = {"_module_core_contract", "_module_routes_validate", "_module_failure_state"}
_FN = [n for n in _TREE.body if isinstance(n, ast.FunctionDef) and n.name in _WANT]
#  26.09.2026: проверка маршрутов обращается к app/module_runtime_policy.py — server.py импортирует
#  его под именем _module_rt_policy; подставляем тот же настоящий модуль.
ENV = {"_route_registry": R, "_route_access": RA, "_module_rt_policy": MRP,
       "MODULE_STATE_VERSION_MISMATCH": "version_mismatch", "MODULE_STATE_ROUTE_MISMATCH": "route_mismatch"}
exec(compile(ast.Module(body=_FN, type_ignores=[]), "server_module_loader", "exec"), ENV)
contract_of = ENV["_module_core_contract"]
validate = ENV["_module_routes_validate"]
failure_state = ENV["_module_failure_state"]
_FNODE = {n.name: n for n in _TREE.body if isinstance(n, ast.FunctionDef)}
#  Права ролей — дословно из server.py (литерал), чтобы решение гейта считалось на настоящей модели.
_ROLE_PERMS = next(ast.literal_eval(n.value) for n in _TREE.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "_ROLE_PERMS" for t in n.targets))


def declarations(module_id):
    """Маршруты, которые модуль объявляет в register(): разбор вызовов core.add_route."""
    src = io.open(os.path.join(REPO, "modules", module_id, "backend.py"), encoding="utf-8").read()
    reg = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "register")
    out = []
    for n in ast.walk(reg):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_route"):
            continue
        rel = ast.literal_eval(n.args[0])
        methods = ast.literal_eval(n.args[2]) if len(n.args) > 2 else \
            ast.literal_eval(next(k.value for k in n.keywords if k.arg == "methods"))
        pid = next(ast.literal_eval(k.value) for k in n.keywords if k.arg == "policy_id")
        handler = n.args[1].id if isinstance(n.args[1], ast.Name) else getattr(n.args[1], "attr", "")
        out.append({"rel": rel, "full": "/api/mod/%s/%s" % (module_id, rel), "methods": list(methods),
                    "policy_id": pid, "handler": NS(__name__=handler)})
    return out


def manifest(module_id):
    return json.loads(io.open(os.path.join(REPO, "modules", module_id, "module.json"), encoding="utf-8").read())


def run(module_id, contract, routes=None):
    """-> (готовые объявления, отказы, заметки). 26.09.2026: заметки — расхождения с картой прав,
    которые загрузку больше не отменяют (core._route_notes)."""
    core = NS(module_id=module_id, module_version=contract,
              _declared_routes=routes if routes is not None else declarations(module_id))
    ready, errs = validate(core)
    return ready, errs, list(getattr(core, "_route_notes", None) or [])


def rt(d):
    """Строгая политика, которую проверка приложила к объявлению (None — право из карты прав)."""
    return d.get("runtime_policy")


def admin_only(p, module_id, method, full):
    """Строгая политика «только администратор» для ИМЕННО этого метода и пути."""
    return (p is not None and MRP.is_runtime(p) and p.required_capability == "admin"
            and p.enforced_access is RA.EnforcedAccess.CAPABILITY
            and p.enforcement_stage is RA.EnforcementStage.MODULE_2_785
            and p.module_id == module_id and p.method == method and p.path == full
            and p not in R.ALL_POLICIES)


def ctx(role):
    return RA.SecurityContext(security_enabled=True, has_session=True, user_enabled=True, role=role,
                              capabilities=frozenset(_ROLE_PERMS[role]))


print("=== 23.09.2026: контракт модуля с ядром ===")
print()
print("--- 1. Какой номер сверяется ---")
check("1. поле core_contract задано — сверяется оно", contract_of({"version": "1.7.30", "core_contract": "1.7.29"})
      == ("1.7.29", True))
check("2. поля нет — сверяется version, как раньше (прежние модули не меняют поведения)",
      contract_of({"version": "0.1.8"}) == ("0.1.8", True))
for bad in ("", "   ", 17, None, ["1.7.29"]):
    check("3. core_contract пустой или не строка (%r) — поле признано негодным (загрузчик с 26.09.2026 сверяет тогда version, см. проверку 18)" % (bad,),
          contract_of({"version": "1.7.30", "core_contract": bad}) == ("", False))

print()
print("--- 2. Склад: выпуск 1.7.39 при прежних маршрутах ---")
inv = manifest("inventory")
inv_routes = declarations("inventory")
#  29.09.2026: склад 1.7.31 (возврат филамента только при подтверждённой остановке) — маршруты те же,
#  контракт прежний 1.7.29. Склад 1.7.32 (окно целиком помещается на экране) — тоже без новых маршрутов.
#  Склад 1.7.33 (08.10.2026: окно решения при любой нехватке, без допуска 30 г) — маршруты те же.
#  Склад 1.7.36 (09.10.2026: доработки второго разработчика 1.7.35 — английский язык, списание и замена
#  со списанием с телефона — поверх 1.7.33). Мобильное списание идёт прежним маршрутом пакетного
#  удаления с конвертом mobile — новых маршрутов нет. Склад 1.7.37 (09.10.2026: перевод записи
#  списания, окно истории целиком, подписи под цифрами) — только интерфейс, маршруты те же. Склад 1.7.38
#  (10.10.2026: телефон снимает и списывает катушку и после отменённой печати, FAILED) — маршруты те же.
#  Склад 1.7.39 (11.10.2026: самопроверка лицензии в платной сборке; у обычного модуля её нет) — маршруты те же.
#  13.10.2026: номер выпуска — из каталога программы (app/module_catalog.py), а не числом в проверке.
_INV_REL = __import__("app.module_catalog", fromlist=["x"]).KNOWN_MODULE_RELEASES.get("inventory")
check("4. в module.json склада выпуск как в каталоге (%s) и контракт 1.7.29 (доработки не прячутся за одним номером)" % _INV_REL,
      inv.get("version") == _INV_REL and inv.get("core_contract") == "1.7.29", inv)
check("5. маршрутов склада в карте прав достаточно, чтобы проверка что-то значила", len(inv_routes) >= 30,
      len(inv_routes))
ready, errs, notes = run("inventory", contract_of(inv)[0])
check("6. КЛЮЧЕВОЕ: склад 1.7.39 с контрактом 1.7.29 проходит проверку ядра целиком — модуль загрузится, "
      "без заметок и без строгих политик",
      not errs and len(ready) == len(inv_routes) and not notes and not any(rt(d) for d in ready),
      (errs[:3], notes[:3]))
map_ver = next(p.module_version for p in R.ALL_POLICIES if getattr(p, "module_id", None) == "inventory")
ready, errs, notes = run("inventory", inv["version"])
#  26.09.2026: раньше здесь был отказ «версия модуля не совпадает с реестром» — так было у пользователя.
check("7. ТОТ ЖЕ склад без поля core_contract теперь загружается: все маршруты подключаются с правом из карты, "
      "отказов нет",
      not errs and len(ready) == len(inv_routes) and not any(rt(d) for d in ready), (errs[:2], len(ready)))
check("7. расхождение не теряется — по заметке на каждый маршрут: «контракт модуля %s, карта прав знает %s»"
      % (inv["version"], map_ver),
      len(notes) == len(inv_routes)
      and all(("контракт модуля %s, карта прав знает %s" % (inv["version"], map_ver)) in n for n in notes), notes[:2])
check("8. подсказка в настройках по-прежнему назвала бы старый отказ несовпадением версии (функция не менялась)",
      failure_state(["inventory.summary.read: версия модуля не совпадает с реестром"]) == "version_mismatch"
      and failure_state(["summary: объявлено методов 2, нужен ровно один"]) == "route_mismatch"
      and failure_state([]) == "route_mismatch")
check("8. но проверка маршрутов такой причины больше не выдаёт — ни в отказах, ни в заметках, ни в исходнике",
      not any("версия модуля не совпадает" in s for s in list(errs) + notes)
      and "версия модуля не совпадает с реестром" not in SRV, (errs[:1], notes[:1]))
for other in ("1.7.28", "1.7.99"):
    ready, errs, notes = run("inventory", other)
    check("9. контракт %s (не тот, что в карте прав) — модуль загружается, право каждого маршрута из карты, "
          "расхождение в заметках" % other,
          not errs and len(ready) == len(inv_routes) and not any(rt(d) for d in ready)
          and len(notes) == len(inv_routes) and all(other in n and map_ver in n for n in notes),
          (errs[:1], notes[:1]))

print()
print("--- 3. Право маршрута решают метод и итоговый путь, а не объявление модуля ---")
good = contract_of(inv)[0]
d0 = inv_routes[0]
m0 = d0["methods"][0]
pol0 = R.module_http_policy(m0, d0["full"])
check("10. (основа) первый маршрут склада есть в карте прав, и его право ниже администратора — проверки ниже "
      "что-то доказывают", pol0 is not None and pol0.module_id == "inventory"
      and pol0.required_capability not in (None, "admin"), pol0)
r1 = [dict(d) for d in inv_routes]
r1[0] = dict(r1[0], handler=NS(__name__="чужой_обработчик"))
ready, errs, notes = run("inventory", good, r1)
check("10. верный контракт, но подменён обработчик — маршрут подключается с правом из карты (метод и путь те же), "
      "подмена видна в заметке",
      not errs and len(ready) == len(r1) and rt(r1[0]) is None
      and R.module_http_policy(m0, d0["full"]) is pol0
      and any(("обработчик в карте прав — %s" % pol0.handler) in n for n in notes), (errs[:1], notes[:2]))
m_foreign = next(m for m in ("DELETE", "PUT", "PATCH", "POST", "GET")
                 if m != m0 and R.module_http_policy(m, d0["full"]) is None)
r2 = [dict(d) for d in inv_routes]
r2[0] = dict(r2[0], methods=[m_foreign])
ready, errs, notes = run("inventory", good, r2)
check("11. верный контракт, но чужой метод (%s) — право соседней записи (%s) не наследуется: только администратору"
      % (m_foreign, pol0.required_capability),
      not errs and len(ready) == len(r2) and admin_only(rt(r2[0]), "inventory", m_foreign, d0["full"])
      and rt(r2[0]).policy_id != pol0.policy_id and not any(rt(d) for d in r2[1:])
      and any(("%s %s: нет в карте прав" % (m_foreign, d0["rel"])) in n for n in notes), (errs[:1], rt(r2[0])))
r2b = [dict(d) for d in inv_routes]
r2b[0] = dict(r2b[0], methods=[m0, m_foreign])
r2b.append(dict(inv_routes[1]))
ready, errs, notes = run("inventory", good, r2b)
check("11. два метода в одном объявлении или повтор того же метода и пути — такой маршрут не подключается, "
      "остальные подключаются",
      len(errs) == 2 and any("нужен ровно один" in e for e in errs) and any("объявлен дважды" in e for e in errs)
      and len(ready) == len(inv_routes) - 1 and r2b[0] not in ready, errs)
r3 = [dict(d) for d in inv_routes] + [{"rel": "backdoor", "full": "/api/mod/inventory/backdoor", "methods": ["POST"],
                                       "policy_id": "inventory.backdoor", "handler": NS(__name__="x")}]
ready, errs, notes = run("inventory", good, r3)
bd = rt(r3[-1])
check("12. верный контракт, но маршрут, которого нет в карте прав, — модуль загружается, остальные маршруты "
      "с правом из карты",
      not errs and len(ready) == len(r3) and not any(rt(d) for d in r3[:-1])
      and any("POST backdoor: нет в карте прав" in n for n in notes), (errs[:1], notes[-1:]))
check("12. такой маршрут получает строгую политику: право admin, доступ по праву, этап MODULE_2_785, "
      "в опись карты прав не входит",
      admin_only(bd, "inventory", "POST", "/api/mod/inventory/backdoor")
      and R.module_http_policy("POST", "/api/mod/inventory/backdoor") is None, bd)
_gate_ok = False
try:
    _put = MRP.register(bd)
    _seen = R.module_http_policy("POST", "/api/mod/inventory/backdoor")
    _op = RA.decide(_seen, ctx("operator"))
    _adm = RA.decide(_seen, ctx("admin"))
    _gate_ok = (_put and _seen is bd and _op.outcome is RA.AccessDecision.FORBIDDEN
                and _op.required_capability == "admin" and _adm.outcome is RA.AccessDecision.ALLOW)
    _gate_extra = (_put, _op, _adm)
finally:
    MRP.clear("inventory")
check("12. гейт по методу и пути находит именно её: оператору — 403 с правом admin, администратору — пропуск",
      _gate_ok and R.module_http_policy("POST", "/api/mod/inventory/backdoor") is None,
      locals().get("_gate_extra", ""))
r4 = [dict(d) for d in inv_routes]
r4[0] = dict(r4[0], full="/api/mod/inventory/other")
ready, errs, notes = run("inventory", good, r4)
check("13. верный контракт, но подменён итоговый путь (не совпадает с именем маршрута) — такой маршрут "
      "не подключается вовсе, остальные маршруты модуля готовы, никаких прав он не получает",
      len(errs) == 1 and "вне пространства модуля" in errs[0] and len(ready) == len(r4) - 1
      and r4[0] not in ready and not any(rt(d) for d in ready), (errs[:1], len(ready)))
r5 = [dict(d0)]
ready, errs, notes = run("cost", "0.2.0", r5)
check("14. чужая политика (маршрут склада, объявленный модулем cost) не присваивается: маршрут не "
      "подключается, права склада модуль cost не получает",
      len(errs) == 1 and "вне пространства модуля" in errs[0] and not ready, (errs[:1], len(ready)))
cost_routes = declarations("cost")
c0 = next(d for d in cost_routes
          if (R.module_http_policy(d["methods"][0], d["full"]) or NS(required_capability=None)).required_capability)
cpol = R.module_http_policy(c0["methods"][0], c0["full"])
borrowed = next(p for p in R.ALL_POLICIES if getattr(p, "module_id", None) == "inventory"
                and p.required_capability != cpol.required_capability)
for fake_pid in (borrowed.policy_id, "admin.everything"):
    r6 = [dict(d) for d in cost_routes]
    i6 = cost_routes.index(c0)
    r6[i6] = dict(r6[i6], policy_id=fake_pid)
    ready, errs, notes = run("cost", contract_of(manifest("cost"))[0], r6)
    check("14. чужой или выдуманный policy_id (%s) права не выбирает: у %s %s остаётся право карты (%s), "
          "подмена в заметке" % (fake_pid, c0["methods"][0], c0["rel"], cpol.required_capability),
          not errs and len(ready) == len(r6) and rt(r6[i6]) is None
          and R.module_http_policy(c0["methods"][0], c0["full"]) is cpol
          and any(("%s: policy_id в карте прав — %s" % (fake_pid, cpol.policy_id)) in n for n in notes),
          (errs[:1], notes[:2]))
_val = _FNODE["_module_routes_validate"]
_ifs = [n for n in ast.walk(_val) if isinstance(n, ast.If)
        and ast.unparse(n.test) == "core.module_version and pol.module_version != core.module_version"]
check("15. сравнение контракта с картой прав в ядре осталось, но ведёт в заметку, а не в отказ",
      "if core.module_version and pol.module_version != core.module_version:" in SRV and len(_ifs) == 1
      and not _ifs[0].orelse and len(_ifs[0].body) == 1
      and ast.unparse(_ifs[0].body[0]).startswith("notes.append("), [ast.unparse(b) for b in _ifs[0].body] if _ifs else "")
check("15. право ищется тем же ключом, что у гейта при каждом запросе: метод + итоговый путь",
      "_module_rt_policy.described_policy(method, d['full'])" in ast.unparse(_val)
      and "_route_registry.module_http_policy(matched.method, matched.path_template)" in ast.unparse(_FNODE["_gate_decide"])
      and all(MRP.described_policy(d["methods"][0], d["full"]) is R.module_http_policy(d["methods"][0], d["full"])
              for d in inv_routes))

print()
print("--- 4. Остальные модули с маршрутами работают как раньше ---")
for mid in ("cost", "messengers", "quality"):
    m = manifest(mid)
    ready, errs, notes = run(mid, contract_of(m)[0])
    check("16. модуль %s %s (сверяется %s) проходит проверку целиком: без отказов, без заметок, всё с правом из карты"
          % (mid, m.get("version"), contract_of(m)[0]),
          not errs and ready and not notes and not any(rt(d) for d in ready), (errs[:2], notes[:2]))

print()
print("--- 5. Ядро и интерфейс ---")
reg = SRV[SRV.find("def _register_module(mdir, source):"):SRV.find("def _load_modules():")]
check("17. загрузчик передаёт в ядро модуля КОНТРАКТ, а не номер выпуска",
      "core = ModuleCore(mid, mdir, _contract)" in reg and 'ModuleCore(mid, mdir, m.get("version", ""))' not in reg)
#  26.09.2026: раньше недействительный контракт означал «модуль не загружается, недействительный манифест».
_bad = [n for n in ast.walk(_FNODE["_register_module"]) if isinstance(n, ast.If)
        and ast.unparse(n.test) == "not _contract_ok"]
check("18. недействительный контракт больше не отменяет загрузку: в этой ветке нет ни выхода, ни пометки "
      "«недействительный манифест»",
      len(_bad) == 1 and not any(isinstance(n, ast.Return) for n in ast.walk(_bad[0]))
      and "MODULE_STATE_INVALID_MANIFEST" not in ast.unparse(_bad[0])
      and "_note_failed_module" not in ast.unparse(_bad[0]), ast.unparse(_bad[0])[:300] if _bad else "")
_c18 = {}
if len(_bad) == 1 and not any(isinstance(n, ast.Return) for n in ast.walk(_bad[0])):   # с выходом ветку не исполнить
    _m18 = dict(inv, core_contract="")
    _c18 = {"m": _m18, "mid": "inventory", "log": NS(warning=lambda *a, **k: None)}
    _c18["_contract"], _c18["_contract_ok"] = contract_of(_m18)
    exec(compile(ast.Module(body=_bad[0].body, type_ignores=[]), "server_register_contract", "exec"), _c18)
ready, errs, notes = run("inventory", _c18.get("_contract", ""))
check("18. склад с испорченным core_contract загружается и сверяется по номеру выпуска %s: все маршруты "
      "подключаются, расхождение в заметках" % inv["version"],
      _c18.get("_contract_ok") is False and _c18.get("_contract") == inv["version"]
      and not errs and len(ready) == len(inv_routes) and not any(rt(d) for d in ready)
      and len(notes) == len(inv_routes), (_c18.get("_contract"), errs[:1]))
check("19. /api/modules отдаёт контракт — и у загруженных, и у незагрузившихся",
      SRV.count('"installed_contract":') >= 2 and '"installed_contract": _module_core_contract(m)[0],' in SRV)
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
hint = APPJS[APPJS.find("const moduleVersionHint"):APPJS.find("const moduleVersionHint") + 1400]
check("20. подсказка в настройках сравнивает контракт: «контракт X, требуется Y», а не номер выпуска",
      "m.installed_contract" in hint and "'контракт '" in hint and "'contract '" in hint)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
