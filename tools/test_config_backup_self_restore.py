# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.830 — ПОСТОЯННЫЙ инвариант само-восстановления:

  export_success => same-version inspect/validate/plan_success

Farm Manager не имеет права выдать файл копии, который сам же не прочитает и не спланирует.
Тест бьёт по РЕАЛЬНОЙ форме дефекта 2.829 (висячая внутренняя ссылка) через синтетические
хранилища + real production self_check. Никаких production DB / сети / принтеров.
"""
import copy
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, self_check, migrations, validator, multistore
from app.config_backup import module_providers as mp
from app.config_backup.repository import DictGateway
from app.config_backup.errors import BackupError

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


def _spool(sid, loc):
    return {"id": sid, "filament_id": "fil-1", "label": sid, "weight_total_g": 1000,
            "weight_remaining_g": 500, "location_id": loc, "price": 10, "lot": "L", "purchased_at": "",
            "opened_at": "", "status": "in_stock", "nfc_uid": "", "ams_printer_id": "", "ams_slot": -1,
            "notes": "", "order_idx": 0, "is_deleted": 0, "created_at": "t", "updated_at": "t"}


def _stores(with_dangling):
    inv = mp.DictModuleStore(tables={
        "inv_filaments": [{"id": "fil-1", "vendor_id": "", "material": "PLA", "color_name": "",
                           "color_hex": "", "diameter": 1.75, "density": 1.2, "temp_min": 190,
                           "temp_max": 220, "spool_weight_g": 180, "price_per_kg": 1000, "notes": "",
                           "order_idx": 0, "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
        "inv_locations": [{"id": "loc-1", "name": "Shelf", "parent_id": "", "notes": "",
                           "order_idx": 0, "is_deleted": 0, "created_at": "t"}],
        "inv_spools": [_spool("s1", "loc-1"),
                       _spool("s2", "loc-DELETED" if with_dangling else "loc-1")],
    }, settings={"currency": "RUB"})
    return {"inventory": inv, "cost": mp.DictModuleStore()}


GW = DictGateway(config={"lan_access_enabled": True}, app_settings={"net_monitor": "1"}, printers=[])
INSTALLED = {"inventory": "1.7.24", "cost": "0.1.3", "quality": "0.2.2"}


def _export(stores):
    exports = [mp.get_provider("inventory").export_snapshot(stores["inventory"], "1.7.24"),
               mp.get_provider("cost").export_snapshot(stores["cost"], "0.1.3"),
               mp.get_provider("quality").export_snapshot(mp.DictModuleStore(), "0.2.2")]
    return serializer.export_backup_v2(GW, created_by="t", created_at="t", module_exports=exports)


print("--- РЕАЛЬНЫЙ ИНВАРИАНТ (даже с висячей ссылкой) ---")
stores = _stores(with_dangling=True)     # текущее состояние С висячей ссылкой (как у пользователя)
blob = _export(stores)
check("1. экспорт синтетического текущего состояния успешен (файл-байты получены)", bool(blob) and len(blob) > 0)

info = serializer.inspect_container(blob)
check("2. экспортированные байты успешно inspect", info.get("container_format_version") == 2
      and not info.get("requires_password"))

payload = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob, None).as_dict()))
plan = multistore.build_full_plan(GW, payload, ["core", "printers", "modules"],
                                  module_stores=_stores(True), installed_modules=INSTALLED,
                                  known_printer_ids=set())
check("3. экспортированные байты успешно строят план (не validation_failed)", plan is not None)

res = self_check.verify_exported_blob(blob, GW, _stores(True), INSTALLED, None)
check("4. export success => plan success (self_check проходит на висячей ссылке)",
      res["ok"] and "dangling_internal_ref" in res["warning_codes"])
check("4b. self_check покрывает все установленные модули", set(res["modules"]) >= {"inventory", "cost"})

print("--- ЭКСПОРТ НЕ ВЫДАЁТ ФАЙЛ ПРИ СБОЕ ПРОВЕРКИ ---")
# Структурно повреждённые байты (дубликат ключа) — self_check ОБЯЗАН упасть => файла не будет.
from app.config_backup import container_v1, container_v2, schemas
bad_dict = serializer.decode_payload(blob, None).as_dict()
inv_entry = [m for m in bad_dict["module_data"]["modules"] if m["module_id"] == "inventory"][0]
inv_entry["domain_data"]["tables"]["inv_spools"].append(
    dict(inv_entry["domain_data"]["tables"]["inv_spools"][0]))    # duplicate key = структурное повреждение
bad_bytes = container_v1.canonical_json_bytes(bad_dict)
bad_blob = container_v2.write_container_v2(
    {"backup_id": "bad0000001", "created_by_app": "t", "created_at": "t",
     "sections": ["core", "printers", "modules"], "printer_count": 0, "module_count": 0},
    bad_bytes, schemas.PROTECTION_MODE_NONE, None)
r = None
try:
    self_check.verify_exported_blob(bad_blob, GW, _stores(True), INSTALLED, None)
except BackupError as e:
    r = e.reason
check("5. self_check падает на структурно повреждённой копии (=> файл не создаётся)",
      r == "validation_failed")

print("--- ROUTE-ПРОВОДКА: self-validation ДО audit ok и ДО выдачи файла ---")
src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
exp_route = src[src.index("async def cfgbackup_export"):src.index("async def cfgbackup_inspect")]
i_self = exp_route.find("verify_exported_blob")
i_ok = exp_route.find('result="ok"')
i_file = exp_route.find("Content-Disposition")
check("6. self-validation вызывается в маршруте экспорта", i_self > 0)
check("6b. self-validation стоит ДО audit result=ok", 0 < i_self < i_ok)
check("6c. self-validation стоит ДО выдачи файла", 0 < i_self < i_file)
check("6d. при сбое self-check audit пишет НЕ ok (validation_failed)",
      'result="validation_failed"' in exp_route or "result=_cfgbackup_safe_reason(e.reason)" in exp_route)

print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
