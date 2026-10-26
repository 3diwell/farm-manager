# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.830 — совместимость уже созданных копий Alpha 2.829 (regression).

Замороженная sanitized-фикстура воспроизводит ТОЧНУЮ форму дефекта 2.829 (висячая внутренняя
ссылка на удалённую локацию). 2.830 обязан: прочитать, провалидировать, построить план,
восстановить БЕЗ ПОТЕРЬ (запись сохраняется, значение не обнуляется), дать нормализованный
ре-экспорт. Ни одной записи не теряется. Container v1/v2 и старые frozen-фикстуры не меняются.
"""
import copy
import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, validator, migrations, multistore, recovery
from app.config_backup import module_providers as mp
from app.config_backup.repository import DictGateway
from app.config_backup.errors import BackupError

FIX_DIR = os.path.join(ROOT, "tools", "fixtures", "config_backup", "regressions",
                       "alpha_2_829_validation_failed")
_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


man = json.load(open(os.path.join(FIX_DIR, "fixture_manifest.json"), encoding="utf-8"))
blob = open(os.path.join(FIX_DIR, man["file"]), "rb").read()

print("--- фикстура заморожена ---")
check("39. SHA-256 regression-фикстуры не изменился", hashlib.sha256(blob).hexdigest() == man["sha256"])
check("размер совпадает с манифестом", len(blob) == man["byte_length"])
check("это обычный контейнер v2 (payload schema 2), НЕ новый формат",
      man["container_format_version"] == 2 and man["payload_schema_version"] == 2)

print("--- фикстура воспроизводит форму дефекта 2.829 ---")
payload = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob, None).as_dict()))
inv_entry = [m for m in payload.module_data["modules"] if m["module_id"] == "inventory"][0]
prov = mp.get_provider("inventory")
snap = prov.migrate_snapshot(inv_entry)
ur = prov.unresolved_internal_refs(snap)
check("7/8. фикстура содержит висячую ссылку inv_items.location_id -> inv_locations",
      any(u["table"] == "inv_items" and u["column"] == "location_id" and u["target"] == "inv_locations" for u in ur))
check("8b. и висячую inv_spools.location_id (точные field_path из манифеста)",
      any(u["table"] == "inv_spools" and u["column"] == "location_id" for u in ur))

print("--- старый strict-валидатор отверг бы это (симуляция root cause) ---")
def _old_strict(snap):
    tables = snap["domain_data"]["tables"]
    keys = {sp.name: {str(r.get(sp.key) or "") for r in tables.get(sp.name) or []} for sp in prov.table_specs}
    for sp in prov.table_specs:
        for col, target in sp.refs.items():
            for row in tables.get(sp.name) or []:
                ref = str(row.get(col) or "")
                if ref and ref not in keys.get(target, set()):
                    raise BackupError("validation_failed", "broken ref %s.%s" % (sp.name, col))
r = None
try:
    _old_strict(snap)
except BackupError as e:
    r = e.reason
check("root cause подтверждён: строгая проверка 2.829 давала validation_failed", r == "validation_failed")

print("--- 2.830 читает/валидирует/планирует ---")
prov.validate_snapshot(snap)   # НЕ бросает
check("9. 2.830 validate_snapshot принимает форму (висячая ссылка не фатальна)", True)
gw = DictGateway(config={}, app_settings={}, printers=[])
installed = {"inventory": "1.7.24", "cost": "0.1.3", "quality": "0.2.2"}
plan = multistore.build_full_plan(gw, payload, ["core", "printers", "modules"],
                                  module_stores={"inventory": mp.DictModuleStore(), "cost": mp.DictModuleStore()},
                                  installed_modules=installed, known_printer_ids=set())
check("9b. план строится и содержит dangling_internal_ref (счётчик, без значений)",
      any(w.get("code") == "dangling_internal_ref" for w in plan["module_data"]["warnings"]))

print("--- restore без потерь ---")
inv_store = mp.DictModuleStore(); cost_store = mp.DictModuleStore()
jr = recovery.RecoveryJournal(os.path.join(os.environ.get("TEMP", "."), "cfgbackup_regfx.json"))
res = multistore.apply_restore_multistore(gw, payload, ["core", "printers", "modules"], jr,
                                          module_stores={"inventory": inv_store, "cost": cost_store},
                                          installed_modules=installed)
check("10. restore применяется атомарно", res["status"] == "ok")
spools = inv_store.read_table("inv_spools"); items = inv_store.read_table("inv_items")
snap_spools = snap["domain_data"]["tables"]["inv_spools"]
check("10b. НИ ОДНА запись не потеряна (все spools/items восстановлены)",
      len(spools) == len(snap_spools) and len(items) == 1)
dangling = [r for r in spools if r["id"] == "spool-2"][0]
check("10c. висячая location_id СОХРАНЕНА как есть (не обнулена, не заменена default)",
      dangling["location_id"] == "loc-DELETED")
check("12. verify canonical после restore проходит", prov.verify_restore(inv_store, snap))

print("--- нормализованный (стабильный) ре-экспорт ---")
re_snap = prov.export_snapshot(inv_store, "1.7.24")
check("11. canonical ре-экспорт стабилен (та же логическая форма, детерминированный порядок)",
      re_snap["domain_data"] == snap["domain_data"])

print("--- старая копия БЕЗ module_data по-прежнему не очищает данные (регрессия 2.829) ---")
old = copy.deepcopy(payload.as_dict()); old["manifest"]["payload_schema_version"] = 1
old.pop("module_data", None)
mig = migrations.migrate_to_current(old)
check("12b. миграция v1: module_data отсутствует (None), не пусто", mig["module_data"] is None)
filled = mp.DictModuleStore(tables={"inv_spools": [{"id": "KEEP"}]}, settings={"currency": "USD"})
before = filled.full_snapshot()
multistore.apply_restore_multistore(DictGateway(config={}, app_settings={}, printers=[]),
                                    validator.validate_payload(mig), ["core", "printers", "modules"],
                                    recovery.RecoveryJournal(os.path.join(os.environ.get("TEMP", "."), "regfx2.json")),
                                    module_stores={"inventory": filled}, installed_modules={"inventory": "1.7.24"})
check("12c. старая копия НЕ очищает данные модуля", filled.full_snapshot() == before)

print("--- старые frozen-фикстуры не тронуты (SHA) ---")
froz = {
    "v1/sample.3diwell-backup": "bc778172",
    "v2/passwordless_v2.3diwell-backup": "2868302e",
    "v2/protected_v2.3diwell-backup": "b1169c6b",
    "module_data/moduledata_v2.3diwell-backup": "b1d09e8e",
}
base = os.path.join(ROOT, "tools", "fixtures", "config_backup")
for rel, pref in froz.items():
    b = open(os.path.join(base, rel), "rb").read()
    check("37/38. frozen не изменён: %s" % rel, hashlib.sha256(b).hexdigest().startswith(pref))

print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
