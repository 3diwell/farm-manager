# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-128 (arch-auth-07): восстановление копии не запирает вход.

ДЕФЕКТ. Копия с включённой защитой входом, восстановленная на компьютер без администратора,
писала security_enabled=1 молча: процесс работал дальше без защиты (флаг читается только при
запуске), а после ЛЮБОГО перезапуска вход закрывался навсегда — пользователей в копии нет,
первичная настройка отвечает «уже включено», восстановление из трея не находит администратора,
повторное восстановление копии требует входа администратора.

ТЕПЕРЬ. Одно правило для плана и применения (restore_plan.security_hold_keys): копия включает
защиту, а хранилище не подтверждает активного администратора (ABSENT или UNKNOWN) — ключ не
пишется, план предупреждает (security_held_no_admin). Смена флага защиты в любую сторону требует
перезапуска и в плане, и в результате применения. Хранилище без enabled_admin_state (тестовое)
ведёт себя как раньше.

Без сервера и без данных фермы: DictGateway в памяти + разбор исходника server.py.
"""
import ast
import copy
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.config_backup import serializer, validator, migrations, multistore, recovery, restore_plan  # noqa: E402
from app.config_backup.repository import DictGateway  # noqa: E402

_n = {"pass": 0, "fail": 0}


def check(label, cond, extra=""):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label + ("" if ok or extra == "" else "  :: %s" % (extra,)))
    _n["pass" if ok else "fail"] += 1
    return ok


class _Enum(object):
    """Как _lan_policy.AdminCheck: у значения есть .value."""
    def __init__(self, v):
        self.value = v


class AdminGW(DictGateway):
    """Хранилище, которое умеет сказать, есть ли администратор (как ServerStorageGateway)."""
    def __init__(self, state, **kw):
        super().__init__(**kw)
        self._state = state

    def enabled_admin_state(self):
        if self._state == "RAISE":
            raise RuntimeError("users table unavailable")
        return self._state


CFG = {"lan_access_enabled": False, "project_print_enabled": True}


def payload(security_on):
    src = DictGateway(config=dict(CFG), app_settings={"net_monitor": "1", "security_enabled": "1" if security_on else "0"},
                      printers=[])
    blob = serializer.export_backup_v2(src, created_by="t", created_at="t", module_exports=[])
    return validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob).as_dict()))


def target(state, security_on=False, cls=AdminGW):
    kw = dict(config=dict(CFG), app_settings={"net_monitor": "1", "security_enabled": "1" if security_on else "0"},
              printers=[])
    return cls(state, **kw) if cls is AdminGW else cls(**kw)


def item(plan, key="security_enabled"):
    return [i for i in plan["sections"]["core"]["items"] if i["key"] == key][0]


def journal():
    return recovery.RecoveryJournal(os.path.join(tempfile.mkdtemp(prefix="fm_sechold_"), "j.json"))


P_ON, P_OFF = payload(True), payload(False)

print("--- 1. нет администратора: защита НЕ включается ---")
tgt = target("ABSENT")
plan = restore_plan.build_plan(tgt, P_ON, ["core", "printers"])
codes = {w["code"] for w in plan["warnings"]}
check("1. план помечает security_enabled как held (не update)", item(plan)["action"] == "held", item(plan))
check("2. план предупреждает security_held_no_admin с понятным текстом (RU и EN)",
      "security_held_no_admin" in codes
      and any("нет администратора" in (w.get("text") or "") and "administrator" in (w.get("text_en") or "")
              for w in plan["warnings"]))
check("3. held не считается изменением и не требует перезапуска",
      plan["counts"]["core_changed"] == 0 and plan["restart_required"] is False, plan["counts"])
check("4. прежнее общее «Меняется настройка безопасности» не показывается вместо нового",
      "security_change" not in codes)
res = multistore.apply_restore_multistore(tgt, P_ON, ["core", "printers"], journal())
check("5. КРИТИЧНО: после применения защита выключена (security_enabled остаётся '0')",
      tgt.get_app_setting("security_enabled") == "0", tgt.get_app_setting("security_enabled"))
check("6. результат называет удержанный ключ и не пишет его", res.get("held_keys") == ["security_enabled"]
      and "security_enabled" not in res.get("app_changed", []), res)
check("7. остальное восстановление применено (net_monitor и прочее — как в копии)",
      res.get("status") in ("ok", "noop") and tgt.get_app_setting("net_monitor") == "1")

print("--- 2. проверка администратора не удалась: тоже «нельзя» ---")
for st, label in (("UNKNOWN", "UNKNOWN"), ("RAISE", "исключение в проверке"), ("", "пустой ответ"),
                  (_Enum("UNKNOWN"), "UNKNOWN как enum")):
    t2 = target(st)
    check("8. %s -> held" % label,
          restore_plan.security_hold_keys(t2, P_ON, ["core"]) == ("security_enabled",)
          and item(restore_plan.build_plan(t2, P_ON, ["core"]))["action"] == "held")
t3 = target("UNKNOWN")
multistore.apply_restore_multistore(t3, P_ON, ["core"], journal())
check("9. UNKNOWN: применение тоже не включает защиту", t3.get_app_setting("security_enabled") == "0")

print("--- 3. администратор есть: защита включается, нужен перезапуск ---")
for st, label in (("PRESENT", "строка"), (_Enum("PRESENT"), "enum AdminCheck")):
    t4 = target(st)
    p4 = restore_plan.build_plan(t4, P_ON, ["core", "printers"])
    check("10. PRESENT (%s): план — update, перезапуск требуется" % label,
          item(p4)["action"] == "update" and p4["restart_required"] is True
          and "security_held_no_admin" not in {w["code"] for w in p4["warnings"]})
t5 = target("PRESENT")
r5 = multistore.apply_restore_multistore(t5, P_ON, ["core", "printers"], journal())
check("11. PRESENT: применение включает защиту и требует перезапуска (не молча при следующем запуске)",
      t5.get_app_setting("security_enabled") == "1" and r5.get("restart_required") is True
      and r5.get("held_keys") == [], r5)


def only(p, keep=("security_enabled", "net_monitor")):
    """Копия без прочих ключей, требующих перезапуска (lan_access_enabled и т. п.): так видно,
    что перезапуск требует именно смена защиты, а не что-то другое."""
    q = copy.deepcopy(p)
    q.core.values = {k: v for k, v in (q.core.values or {}).items() if k in keep}
    return q


r5b = multistore.apply_restore_multistore(target("PRESENT"), only(P_ON), ["core"], journal())
r5c = multistore.apply_restore_multistore(target("PRESENT"), only(P_OFF), ["core"], journal())
check("11b. перезапуск требует именно смена флага защиты (без неё — не требуется)",
      r5b.get("restart_required") is True and r5c.get("restart_required") is False, (r5b, r5c))

print("--- 4. выключение защиты копией: применяется, но тоже с перезапуском ---")
t6 = target("PRESENT", security_on=True)
p6 = restore_plan.build_plan(t6, P_OFF, ["core"])
r6 = multistore.apply_restore_multistore(t6, P_OFF, ["core"], journal())
check("12. копия с выключенной защитой: update, план и результат требуют перезапуска",
      item(p6)["action"] == "update" and p6["restart_required"] is True
      and t6.get_app_setting("security_enabled") == "0" and r6.get("restart_required") is True)
t7 = target("ABSENT", security_on=True)
check("13. защита уже включена и копия её не меняет — удерживать нечего",
      restore_plan.security_hold_keys(t7, P_ON, ["core"]) == ()
      and item(restore_plan.build_plan(t7, P_ON, ["core"]))["action"] == "unchanged")
t8 = target("ABSENT")
r8 = multistore.apply_restore_multistore(t8, P_OFF, ["core"], journal())
check("14. флаг не меняется (0 -> 0) — перезапуск из-за него не нужен",
      restore_plan.restart_on_change(target("ABSENT"), serializer.payload_to_mutation(P_OFF, ["core"])) is False)

print("--- 5. хранилище без проверки администратора — поведение прежнее ---")
t9 = target(None, cls=DictGateway)
p9 = restore_plan.build_plan(t9, P_ON, ["core"])
check("15. DictGateway: ключ не удерживается, план — update + security_change",
      restore_plan.security_hold_keys(t9, P_ON, ["core"]) == () and item(p9)["action"] == "update"
      and "security_change" in {w["code"] for w in p9["warnings"]})
multistore.apply_restore_multistore(t9, P_ON, ["core"], journal())
check("16. DictGateway: значение копии применяется как раньше", t9.get_app_setting("security_enabled") == "1")
check("17. без секции core удерживать нечего", restore_plan.security_hold_keys(target("ABSENT"), P_ON, ["printers"]) == ())

print("--- 6. план и применение не расходятся ---")
mut = serializer.payload_to_mutation(P_ON, ["core"], hold_keys=("security_enabled",))
check("18. payload_to_mutation(hold_keys) не пишет удержанный ключ, остальные — пишет",
      "security_enabled" not in mut.app_set and "net_monitor" in mut.app_set)
t10 = target("ABSENT")
p10 = multistore.build_full_plan(t10, P_ON, ["core", "printers", "modules"], module_stores={}, installed_modules={})
check("19. полный план (multistore) несёт то же предупреждение и тот же held",
      item(p10)["action"] == "held" and any(w.get("code") == "security_held_no_admin" for w in p10["warnings"]))
t11 = target("PRESENT")
p11 = multistore.build_full_plan(t11, P_ON, ["core"], module_stores={}, installed_modules={},
                                 hold_keys=("security_enabled",))
check("20. переданный сервером hold_keys главнее собственного расчёта (одно решение на запрос)",
      item(p11)["action"] == "held")

print("--- 7. проводка в server.py ---")
SRC = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
tree = ast.parse(SRC)
gw = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ServerStorageGateway"][0]
meth = [n for n in gw.body if isinstance(n, ast.FunctionDef) and n.name == "enabled_admin_state"]
check("21. ServerStorageGateway.enabled_admin_state() отдаёт _enabled_admin_check() (три состояния)",
      len(meth) == 1 and "_enabled_admin_check()" in ast.get_source_segment(SRC, meth[0]))
fn = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "cfgbackup_restore"][0]
body = ast.get_source_segment(SRC, fn)
i_plan = body.find("build_full_plan(")
i_lock = body.find("_CFGBACKUP_RESTORE_LOCK.acquire(blocking=False)")
i_apply = body.find("apply_restore_multistore(")
holds = [i for i in range(len(body)) if body.startswith("security_hold_keys(", i)]
check("22. маршрут считает правило перед планом и заново перед применением (под замком)",
      len(holds) == 2 and holds[0] < i_plan and i_lock < holds[1] < i_apply, holds)
check("23. и передаёт его в план и в применение (hold_keys=_hold)",
      body.count("hold_keys=_hold") == 2)

print("\n" + "=" * 60)
print("ИТОГО: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
