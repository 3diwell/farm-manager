#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Alpha 2.793 — единый capability contract окон модулей.
#
# Что доказывает тест:
#   * характеризацию Alpha 2.792 (эталон — коммит 1d04271, он неизменяем, поэтому проверки
#     остаются зелёными и после 2.793 и продолжают описывать именно старое состояние);
#   * состав и границы нового контракта ядра (поля, отсутствие секретов, строгая нормализация);
#   * что модули НЕ содержат своей таблицы прав и не ветвятся по названиям ролей;
#   * что имена прав в интерфейсе совпадают с правами маршрутов модулей Alpha 2.785;
#   * что backend-права модулей и состав маршрутов не изменены.
#
# Безопасность прогона:
#   * production server.py НЕ импортируется (работающая программа не мешает и не даёт ложный ноль);
#   * рабочие БД, DATA_DIR и config не открываются; сеть, принтеры и слайсер не используются;
#   * модульные backend-обработчики не выполняются: тест читает исходники и реестр политик.
#
# Запуск: python tools/test_module_window_capability_contract.py   (0 = все проверки пройдены)

import io
import os
import re
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

PARENT = "1d04271"   # HEAD до Alpha 2.793 (handoff 2.792)
SENTINEL = "MODULE_CAPABILITY_SENTINEL_2_793"

fail = 0
total = 0


def check(name, cond):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


def section(t):
    print("\n--- %s ---" % t)


def rd(rel):
    return io.open(os.path.join(REPO, rel), encoding="utf-8", errors="surrogateescape").read()


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["web/index.html", "web/app.js",
                                  "modules/inventory/web/InventoryPanel.js",
                                  "modules/cost/web/CostPanel.js",
                                  "modules/quality/web/QualityPanel.js",
                                  "app/route_policy_registry.py"], check)
hcheck = HIST.check


def git_show(rel):
    return HIST.show(rel)


APPJS = rd("web/app.js")
HTML = rd("web/index.html")
INV = rd("modules/inventory/web/InventoryPanel.js")
COST = rd("modules/cost/web/CostPanel.js")
QUAL = rd("modules/quality/web/QualityPanel.js")

from app import route_policy_registry as reg   # noqa: E402  (чистый модуль политик, без БД и сети)

MODP = [p for p in reg.MODULE_POLICIES] if hasattr(reg, "MODULE_POLICIES") else \
       [p for p in reg.ALL_POLICIES if getattr(p, "module_id", None)]

print("=== Alpha 2.793: единый capability contract окон модулей ===")

# ════════════════════════════════════════════════════════════════════════════
section("характеризация: как было в Alpha 2.792 (эталон %s)" % PARENT)

P_HTML = git_show("web/index.html")
P_APPJS = git_show("web/app.js")
P_INV = git_show("modules/inventory/web/InventoryPanel.js")
P_COST = git_show("modules/cost/web/CostPanel.js")
P_QUAL = git_show("modules/quality/web/QualityPanel.js")

hcheck("H0. эталон %s прочитан (иначе все проверки характеризации бессмысленны)" % PARENT,
       lambda: all(x for x in (P_HTML, P_APPJS, P_INV, P_COST, P_QUAL)))

_p_tag = ""
if P_HTML:
    m = re.search(r'<component v-if="activeModuleComp"[^>]*></component>', P_HTML)
    _p_tag = m.group(0) if m else ""

hcheck("H1. (1) окно модуля получало open", lambda: bool(_p_tag) and ':open="true"' in _p_tag)
hcheck("H2. (2) окно модуля получало lang", lambda: bool(_p_tag) and ':lang="lang"' in _p_tag)
hcheck("H3. (3) единого access contract окно НЕ получало",
       lambda: bool(_p_tag) and "access" not in _p_tag and "capab" not in _p_tag)
hcheck("H4. (3b) в ядре не существовало ни contract, ни его версии",
       lambda: bool(P_APPJS) and "moduleAccess" not in P_APPJS
       and "MODULE_ACCESS_CONTRACT_VERSION" not in P_APPJS)
hcheck("H5. (4) Inventory не мог вызвать core can() через props",
       lambda: bool(P_INV) and re.search(r'\bprops\.access\b', P_INV) is None
       and re.search(r'^\s*access:\s*\{', P_INV, re.M) is None)
hcheck("H6. (5) Cost не мог вызвать core can() через props",
       lambda: bool(P_COST) and re.search(r'\bprops\.access\b', P_COST) is None
       and "access:" not in P_COST)
hcheck("H7. (6) Quality не мог вызвать core can() через props",
       lambda: bool(P_QUAL) and re.search(r'\bprops\.access\b', P_QUAL) is None
       and "access:" not in P_QUAL)
hcheck("H8. (7) Inventory показывал admin-контролы, не зная о правах: валюта и порог склада",
       lambda: bool(P_INV) and '@change="setCurrency($event.target.value)"' in P_INV
       and '@change="setLowG($event.target.value)"' in P_INV
       and "can('admin')" not in P_INV)
hcheck("H9. (8) Cost показывал admin-контролы, не зная о правах: ставки и настройки принтера",
       lambda: bool(P_COST) and '@click="saveGlobal"' in P_COST
       and '@click="savePrinter(p)"' in P_COST
       and "can('admin')" not in P_COST)
hcheck("H10. (10) frontend до клика не знал о запрете: ни одной проверки права перед запросом",
       lambda: bool(P_INV) and bool(P_COST)
       and "guard(" not in P_INV and "guard(" not in P_COST)
hcheck("H11. (11) режим без авторизации существовал независимо от props окна модуля",
       lambda: bool(P_APPJS) and "if (!authEnabled.value) return true;" in P_APPJS)
check("H12. (12-15) тест не импортирует server.py и не трогает рабочие данные",
      "server" not in sys.modules
      and not any(str(getattr(m, "__file__", "") or "").endswith("server.py")
                  for m in sys.modules.values()))

# ════════════════════════════════════════════════════════════════════════════
section("контракт ядра: состав, версия, отсутствие секретов")

_ma = ""
if "const moduleAccess = computed(" in APPJS:
    _ma = APPJS[APPJS.index("const moduleAccess = computed("):]
    _ma = _ma[:_ma.index("\n    });") + 8]

check("1. контракт существует и он ровно один", APPJS.count("const moduleAccess = computed(") == 1)
check("2. contractVersion = 1",
      "MODULE_ACCESS_CONTRACT_VERSION = 1" in APPJS
      and "contractVersion: MODULE_ACCESS_CONTRACT_VERSION" in _ma)
check("3. контракт заморожен (модуль не может дописать себе право)",
      "Object.freeze({" in _ma and "capabilities: Object.freeze(caps)" in _ma)

_allowed_fields = {"contractVersion", "authEnabled", "capabilities", "revision", "can", "revalidate"}
_fields = set(re.findall(r'^\s*([A-Za-z_][A-Za-z0-9_]*):', _ma, re.M))
check("4. в контракте только разрешённые поля: %s" % (", ".join(sorted(_fields)) or "нет"),
      bool(_fields) and _fields <= _allowed_fields)

for bad, label in (("token", "session token"), ("cookie", "cookie"), ("password", "password"),
                   ("hash", "hash"), ("authUser", "запись пользователя"), ("role", "название роли")):
    check("5-10. в контракте нет поля/утечки «%s»" % label, bad.lower() not in _ma.lower())

check("11. contract не читает и не пишет браузерное хранилище",
      "localStorage" not in _ma and "sessionStorage" not in _ma)
check("12. can() контракта делегирует ЕДИНСТВЕННОМУ core-хелперу can()",
      "can: moduleCan" in _ma
      and re.search(r'const moduleCan = \(cap\) => \(\(typeof cap === .string. '
                    r'&& MODULE_CAPABILITIES\.indexOf\(cap\) >= 0\) \? !!can\(cap\) : false\)', APPJS) is not None)
check("13. своей таблицы прав у контракта НЕТ (единственная таблица ролей — прежняя core)",
      APPJS.count("_rolePerms") == 2 and _ma.count("_rolePerms") == 0)

_caps_line = re.search(r'const MODULE_CAPABILITIES = Object\.freeze\(\[([^\]]*)\]\)', APPJS)
_caps = set(re.findall(r"'([a-z_]+)'", _caps_line.group(1))) if _caps_line else set()
check("14. словарь имён прав = ровно семь имён контракта",
      _caps == {"view", "project", "operate", "printer_write", "count", "rework", "admin"})
check("15. printer_delete в словарь модулей НЕ входит (ни один маршрут модуля его не проверяет)",
      "printer_delete" not in _caps and "printer_delete" in APPJS)

check("16. реактивность: контракт зависит от ревизии доступа",
      "const accessRevision = ref(0)" in APPJS and "accessRevision.value" in _ma)
check("17. переоценка прав не даёт шквала запросов (дебаунс + флаг)",
      "_accessRevalidating" in APPJS and "< 3000" in APPJS)
check("18. переоценка перечитывает правду с сервера тем же путём, что и загрузка",
      re.search(r'const revalidateAccess = async \(\) => \{[^}]*await fetchAuthStatus\(\)',
                APPJS, re.S) is not None)
check("19. модуль не получает ссылку на изменяемое состояние авторизации",
      "authEnabled: !!authEnabled.value" in _ma and "authEnabled," not in _ma)

#  3.000: у модуля стало ДВЕ поверхности — окно и ВСТРОЕННАЯ ячейка настроек во вкладке
#  «Модули». Инвариант прежний и даже строже: обе получают ОДИН И ТОТ ЖЕ объект прав,
#  каждая — единственной точкой монтирования, без ветвления по имени модуля.
check("20. контракт передаётся каждой поверхности модуля одной точкой монтирования",
      HTML.count('<component v-if="activeModuleComp"') == 1
      and HTML.count('v-for="m in modulesWithSettings"') == 1
      and HTML.count(':access="moduleAccess"') == 2)
_cfg_cell = HTML[HTML.index('v-for="m in modulesWithSettings"'):]
_cfg_cell = _cfg_cell[:_cfg_cell.index("</component>") + len("</component>")]
check("20б. ячейка настроек получает ТОТ ЖЕ контракт и не ветвится по имени модуля",
      ':access="moduleAccess"' in _cfg_cell and ':is="m.comp"' in _cfg_cell
      and not any(mid in _cfg_cell for mid in ("inventory", "cost", "quality", "messengers")))
check("21. все окна модулей получают контракт одинаково (общая точка, без ветвлений по id)",
      re.search(r'<component v-if="activeModuleComp"[^>]*:access="moduleAccess"[^>]*>', HTML) is not None
      and "inventory" not in re.search(r'<component v-if="activeModuleComp"[^>]*>', HTML).group(0))
check("22. moduleAccess экспортирован из setup (иначе шаблон получил бы undefined)",
      re.search(r'\bmoduleAccess,', APPJS) is not None)

# ════════════════════════════════════════════════════════════════════════════
section("модули: одна проверка права, ноль своих таблиц прав и ролей")

for mid, src in (("inventory", INV), ("cost", COST)):
    check("23. %s: контракт объявлен как prop" % mid,
          re.search(r'access:\s*\{\s*type:\s*Object,\s*default:\s*null\s*\}', src) is not None)
    check("24. %s: версия контракта проверяется явно" % mid,
          "CAP_CONTRACT_VERSION = 1" in src
          and "a.contractVersion === CAP_CONTRACT_VERSION" in src)
    check("25. %s: отсутствующий/чужой контракт -> can() = false (fail-safe, НЕ режим owner)" % mid,
          re.search(r'const can = \(cap\) => \(capReady\.value \? '
                    r'!!props\.access\.can\(cap\) : false\)', src) is not None)
    check("26. %s: своей таблицы прав нет" % mid,
          "_rolePerms" not in src and "rolePerms" not in src)
    check("27. %s: нет ветвлений по названию роли" % mid,
          not re.search(r"role\s*===|===\s*'admin'|===\s*'operator'|"
                        r"===\s*'observer'|===\s*'assembler'", src))
    check("28. %s: контракт не пишется в браузерное хранилище" % mid,
          not re.search(r'(localStorage|sessionStorage)\.setItem\([^)]*(access|capab|contract)',
                        src, re.I))
    check("29. %s: право не отправляется backend как доказательство доступа" % mid,
          not re.search(r"headers[^}]*(X-Cap|X-Role|capabilit|X-Access)", src, re.I)
          and not re.search(r"JSON\.stringify\(\{[^}]*capabilit", src, re.I))

check("30. Quality остаётся только для чтения",
      QUAL.count("fetch(") == 1 and "'/api/mod/quality/summary'" in QUAL
      and "method:" not in QUAL)
hcheck("30h. окно Quality не менялось с эталона %s" % PARENT, lambda: QUAL == P_QUAL)
check("31. Quality не получил искусственных ограничений project/admin",
      "can('project')" not in QUAL and "can('admin')" not in QUAL and "guard(" not in QUAL)

# ════════════════════════════════════════════════════════════════════════════
section("submit-time recheck: скрытой кнопки недостаточно")

_INV_MUT = {
    "setLowG": "admin", "setCurrency": "admin",
    "replaceSpool": "project", "saveSpool": "project", "del": "project",
    "applyDuplicate": "project", "applyBind": "project", "unbind": "project",
    "confirmUnbind": "project", "recDoSync": "project", "openBulkDelete": "project",
    "confirmBulkDelete": "project", "saveItem": "project", "delItem": "project",
    "saveLoc": "project", "delLoc": "project",
    "applyAdj": "count", "applyItemAdj": "count",
}
#  3.0: «Расчёт заказа» добавил тариф на группу моделей (saveModelGroup) — это тоже право admin.
_COST_MUT = {"saveCalc": "project", "saveGlobal": "admin", "savePrinter": "admin",
             "clearOverride": "admin", "saveModelGroup": "admin"}


def fn_body(src, name):
    """Тело функции от объявления до следующего объявления const верхнего уровня."""
    m = re.search(r'const %s = (?:async )?\([^)]*\) => ' % re.escape(name), src)
    if not m:
        return None
    tail = src[m.end():]
    nxt = re.search(r'\n    const [A-Za-z_]', tail)
    return tail[:nxt.start()] if nxt else tail[:4000]


for name, cap in sorted(_INV_MUT.items()):
    body = fn_body(INV, name)
    ok = bool(body) and body.lstrip().startswith("{ if (!guard('%s')) return;" % cap) \
        or (bool(body) and re.match(r'\{\s*if \(!guard\(\'%s\'\)\) return;' % cap, body.strip()))
    check("32. inventory.%s: право «%s» проверяется ПЕРВОЙ строкой (до fetch и до локальных правок)"
          % (name, cap), ok)

for name, cap in sorted(_COST_MUT.items()):
    body = fn_body(COST, name)
    ok = bool(body) and re.match(r'\{\s*if \(!guard\(\'%s\'\)\) return;' % cap, body.strip()) is not None
    check("33. cost.%s: право «%s» проверяется ПЕРВОЙ строкой" % (name, cap), ok)

#  11.10.2026 (лицензии 043): платная сборка сначала проверяет «только просмотр» (licReadOnly) — тоже отказ
#  без запроса; сама проверка права после этого прежняя.
def _guard_line(src):
    m = re.search(r"const guard = \(cap\) => \{(.*?)\};\n", src)
    return m.group(1) if m else ""


def _guard_ok(src):
    g = _guard_line(src)
    rest = re.sub(r"^\s*if \(licReadOnly\.value\) (?:\{ licFlash\(\); return false; \}|return false;)", "", g)
    return (rest.strip() == "if (can(cap)) return true; denyFlash(); return false;"
            and "fetch" not in g and "api(" not in g)


check("34. inventory: guard() отказывает без запроса и без изменения данных",
      _guard_ok(INV) and "fetch" not in (fn_body(INV, "guard") or "fetch"))
check("35. cost: guard() отказывает без запроса и без изменения данных", _guard_ok(COST))
check("36. текст отказа человеческий и без внутреннего кода права",
      "Недостаточно прав для этого действия." in INV
      and "Недостаточно прав для этого действия." in COST
      and "You do not have permission for this action." in INV)

# ════════════════════════════════════════════════════════════════════════════
section("401/403: backend остаётся окончательной инстанцией")

_inv_denied = fn_body(INV, "accessDenied") or ""
check("37. inventory: 403/401 переоценивает доступ и не повторяет запрос",
      "r.status !== 403 && r.status !== 401" in INV
      and "a.revalidate()" in _inv_denied
      and "fetch(" not in _inv_denied)
check("38. cost: 403/401 переоценивает доступ в единой точке api()",
      "r.status === 403 || r.status === 401" in COST and "a.revalidate()" in COST)
check("39. inventory: отказ по правам не затирается общим сообщением об ошибке",
      "denyUntil" in INV and "if (k === 'err' && Date.now() < denyUntil) return;" in INV)

# ════════════════════════════════════════════════════════════════════════════
section("карта интерфейса сходится с правами маршрутов Alpha 2.785")

_reg_caps = {}
for p in MODP:
    _reg_caps.setdefault(p.module_id, set()).add(p.required_capability)

_ui_caps = {
    "inventory": set(re.findall(r"(?:can|guard)\('([a-z_]+)'\)", INV)),
    "cost": set(re.findall(r"(?:can|guard)\('([a-z_]+)'\)", COST)),
}
for mid in ("inventory", "cost"):
    check("40. %s: интерфейс не выдумывает имён прав — все они есть у маршрутов модуля" % mid,
          _ui_caps[mid] <= _reg_caps.get(mid, set()),)
    check("41. %s: интерфейс не использует имя права вне словаря контракта" % mid,
          _ui_caps[mid] <= _caps)

check("42. inventory: пересчёт остатка отнесён к count, а не к project",
      "guard('count')" in INV
      and ("inventory.spool.adjust", "count") in
          [(p.policy_id, p.required_capability) for p in MODP]
      and ("inventory.item.adjust", "count") in
          [(p.policy_id, p.required_capability) for p in MODP])
check("43. inventory: настройки склада отнесены к admin (валюта и порог)",
      ("inventory.settings.write", "admin") in
      [(p.policy_id, p.required_capability) for p in MODP]
      and "guard('admin')" in (fn_body(INV, "setCurrency") or "")
      and "guard('admin')" in (fn_body(INV, "setLowG") or ""))
check("44. inventory: обычная складская работа осталась project, а не admin",
      "guard('project')" in (fn_body(INV, "saveSpool") or "")
      and "guard('project')" in (fn_body(INV, "applyBind") or ""))
check("45. inventory: контролов цены и удаления филамента в окне НЕТ — запрос невозможен",
      not re.search(r"fetch\('/api/mod/inventory/filament/'", INV)
      and not re.search(r"'/api/mod/inventory/filament/' \+", INV)
      and ("inventory.filament.update", "admin") in
          [(p.policy_id, p.required_capability) for p in MODP])
check("46. cost: расчёт остаётся правом view — от наблюдателя его не прячут",
      ("cost.calculate", "view") in [(p.policy_id, p.required_capability) for p in MODP]
      and "guard(" not in (fn_body(COST, "recalc") or "guard(")
      and "can('project')" not in COST.split("const recalc")[1].split("const saveCalc")[0])
check("47. cost: сохранение расчёта — project, ставки и настройки принтера — admin",
      "guard('project')" in (fn_body(COST, "saveCalc") or "")
      and "guard('admin')" in (fn_body(COST, "saveGlobal") or "")
      and "guard('admin')" in (fn_body(COST, "savePrinter") or "")
      and "guard('admin')" in (fn_body(COST, "clearOverride") or ""))

# ════════════════════════════════════════════════════════════════════════════
section("backend-права модулей не ослаблены")

_counts = {}
for p in MODP:
    _counts[p.required_capability] = _counts.get(p.required_capability, 0) + 1
check("48. состав прав маршрутов модулей прежний: view 21 / project 17 / count 2 / admin 11 (2.994: +6 messengers)",
      _counts == {"view": 21, "project": 17, "count": 2, "admin": 11})
check("49. все 51 маршрутов модулей остаются на границе CAPABILITY",
      len(MODP) == 51 and all(p.enforced_access.value == "CAPABILITY" for p in MODP))
check("50. состав маршрутов ожидаемый: 233/188/45/2 (2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup; 2.870 +камера без перекодирования); 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы",
      reg.registry_counts()["total"] == 260 and reg.registry_counts()["core"] == 209   # 196->204 / 241->249; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and reg.registry_counts()["modules"] == 51 and reg.registry_counts()["websocket"] == 2)

# Инвариант Alpha 2.793: этап НЕ трогал права маршрутов модулей. Сверяем именно права с эталоном
# 1d04271 — это долговечная проверка, которая продолжает ловить любой их дрейф и после следующих
# этапов. Побайтовый дифф самого реестра принадлежит тесту того этапа, который его менял
# (Alpha 2.794 — tools/test_module_route_side_effect_metadata.py, проверка 23).
_par_reg = git_show("app/route_policy_registry.py")
_par_caps = dict(((m, meth, r), c) for m, meth, r, c in re.findall(
    r'\("[a-z_.]+",\s+"(inventory|cost|quality)",\s+"([A-Z]+)",\s+"([^"]+)",\s+"CAPABILITY",\s+"([a-z_]+)"\)',
    _par_reg or ""))
_now_caps = dict(((p.module_id, p.method, p.module_route), p.required_capability)
                 for p in MODP if p.module_id in ("inventory", "cost", "quality"))   # 2.994: messengers в эталоне 1d04271 нет
hcheck("51. права ВСЕХ маршрутов модулей побайтово совпадают с эталоном %s (%d записей)"
       % (PARENT, len(_par_caps)),
       lambda: len(_par_caps) == 45 and _par_caps == _now_caps)

check("52. предохранитель автоматической отправки остаётся выключенным",
      re.search(r'^DISPATCH_ENABLED = False\s*$', rd("app/project_orchestrator.py"), re.M) is not None
      and re.search(r'^TRANSPORT_ENABLED = False\s*$', rd("app/project_orchestrator.py"), re.M) is not None)

# ════════════════════════════════════════════════════════════════════════════
section("границы предыдущих этапов и метка-ловушка")

SRV = rd("server.py")
# Alpha 2.795: проверяем СИНХРОННОСТЬ ядра и установщика (реальный инвариант), а не конкретный
# номер — иначе проверка краснела бы после каждого бампа версии (та же хрупкость, что чинилась в
# 2.795 у UI-тестов). Версии модулей пинуются: в этом контракте они стабильны.
_core_ver = re.search(r'APP_VERSION = "(?:Alpha|Beta) (\d+\.\d+)"', SRV)
_iss_ver = re.search(r'#define AppVersion "(\d+\.\d+)"', rd("3diwell-setup.iss"))
check("53. версии синхронны: номер ядра == номер установщика; версии модулей на месте",
      bool(_core_ver) and bool(_iss_ver) and _core_ver.group(1) == _iss_ver.group(1)
      #  23.09.2026: стабилен КОНТРАКТ модуля с ядром, номер выпуска меняется свободно.
      and '"core_contract": "1.7.29"' in rd("modules/inventory/module.json")   # 1.7.28 с 2.946: привязка катушки снова открывается
      and '"core_contract": "0.2.0"' in rd("modules/cost/module.json")   # 3.0: «Расчёт заказа» заменил «Себестоимость печати»
      and '"version": "0.2.3"' in rd("modules/quality/module.json"))
check("54. границы 2.789-2.792 не тронуты",
      "filesystem_access_policy" in SRV and "auth_rate_limit" in SRV
      and "session_cookie_policy" in SRV and "printer_state_policy" in SRV
      and "FEED_STATUS_VIEW" in APPJS)
check("55. контракт не имеет побочных эффектов: ни печати, ни очереди, ни принтера",
      not any(x in _ma for x in ("fetch(", "dispatch", "reserve", "queue", "printer",
                                 "localStorage", "sessionStorage")))
check("56. метка-ловушка отсутствует в производственном коде",
      not any(SENTINEL in s for s in (APPJS, HTML, INV, COST, QUAL, SRV,
                                      rd("app/route_policy_registry.py"))))

print("\n" + "=" * 76)
sys.exit(HIST.summary(total - fail, fail))
