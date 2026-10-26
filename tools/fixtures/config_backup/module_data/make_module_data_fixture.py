# -*- coding: utf-8 -*-
"""Alpha 2.829 — ГЕНЕРАТОР замороженной фикстуры payload v2 С ДАННЫМИ МОДУЛЕЙ (один запуск).

После коммита фикстура НЕИЗМЕНЯЕМА (SHA-256; перегенерация запрещена). Синтетика: без
production-имён/секретов; credential помечен FIXTURE_ и НЕ совпадает с sentinel. Контейнер —
опубликованный v2 (passwordless) БЕЗ изменений формата; новое — только payload schema v2 +
module_data (inventory полный срез, cost настройки+расчёт, quality — маркер отсутствия данных).
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))

from app.config_backup import serializer, schemas
from app.config_backup import module_providers as mp
from app.config_backup.repository import DictGateway

CREATED_AT = "2026-07-25 00:00:00 UTC"
CREATED_BY = "3DIWELL Farm Manager Alpha 2.829 (frozen module-data fixture)"

GATEWAY = DictGateway(
    config={"lan_access_enabled": True, "project_print_enabled": True, "modules_disabled": [],
            "data_dir": "D:\\FrozenMD\\data", "server_port": 8000},
    app_settings={"net_monitor": "1", "security_enabled": "0", "printer_files_delete_enabled": "0"},
    printers=[
        {"id": "fixture-md-bambu", "name": "Bambu X1C (md fixture)", "type": "bambu",
         "ip": "192.168.70.11", "port": 8883, "token": "FIXTURE_MD_BAMBU_CODE",
         "last_parts": "{}", "order_idx": 0, "gen": "auto", "serial": "FIXTURE-MD-B", "model": "X1C"},
        {"id": "fixture-md-ff", "name": "FlashForge AD5M (md fixture)", "type": "flashforge",
         "ip": "192.168.70.12", "port": 8898, "token": "FIXTURE_MD_FF_CHECK",
         "last_parts": "{}", "order_idx": 1, "gen": "auto", "serial": "FIXTURE-MD-F", "model": "Adventurer 5M"},
    ])

INV_STORE = mp.DictModuleStore(tables={
    "inv_vendors": [{"id": "fx-vnd", "name": "Fixture Vendor", "notes": "", "order_idx": 0,
                     "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
    "inv_filaments": [{"id": "fx-fil", "vendor_id": "fx-vnd", "material": "PLA",
                       "color_name": "Blue", "color_hex": "#00f", "diameter": 1.75, "density": 1.24,
                       "temp_min": 190, "temp_max": 220, "spool_weight_g": 180, "price_per_kg": 1200,
                       "notes": "", "order_idx": 0, "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
    "inv_locations": [{"id": "fx-loc", "name": "Fixture Shelf", "parent_id": "", "notes": "",
                       "order_idx": 0, "is_deleted": 0, "created_at": "t"}],
    "inv_items": [{"id": "fx-item", "name": "Fixture Nozzle", "category": "parts", "unit": "шт",
                   "qty": 3, "min_qty": 1, "max_qty": 5, "location_id": "fx-loc", "price": 50,
                   "printer_brand": "", "printer_model": "", "notes": "", "order_idx": 0,
                   "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
    "inv_spools": [{"id": "fx-spool", "filament_id": "fx-fil", "label": "FX-1",
                    "weight_total_g": 1180, "weight_remaining_g": 640, "location_id": "fx-loc",
                    "price": 1400, "lot": "FXLOT", "purchased_at": "2026-01-01", "opened_at": "",
                    "status": "in_stock", "nfc_uid": "", "ams_printer_id": "fixture-md-bambu",
                    "ams_slot": 1, "notes": "", "order_idx": 0, "is_deleted": 0,
                    "created_at": "t", "updated_at": "t"}],
    "inv_ledger": [{"id": "fx-lg", "ts": "t", "kind": "adjust", "ref_type": "spool",
                    "ref_id": "fx-spool", "qty": -40, "reason": "fixture", "job_id": "",
                    "username": "fixture", "note": ""}],
}, settings={"currency": "RUB"})

COST_STORE = mp.DictModuleStore(tables={
    "cost_printer_settings": [{"printer_id": "fixture-md-bambu",
                               "settings_json": "{\"power_w\": 250}", "updated_at": "t"}],
    "cost_calculations": [{"calc_id": "fx-calc", "run_id": None, "parent_calc_id": None,
                           "revision": 1, "printer_id": "fixture-md-bambu", "printer_name": "Bambu X1C (md fixture)",
                           "printer_model": "X1C", "mode": "estimated", "basis": "estimated",
                           "source": "manual", "outcome": None, "label": "fixture calc",
                           "currency": "RUB", "quantity": 1, "duration_s": 1800,
                           "material_cost": 5, "depreciation_cost": 1, "electricity_cost": 1,
                           "operator_cost": 0, "extra_cost": 0, "total_run": 7, "total_per_part": 7,
                           "formula_version": "cost_v2", "breakdown_json": "{}",
                           "schema_version": 1, "created_at": "t"}],
}, settings={"formula_branch": "default"})


def main():
    path = os.path.join(HERE, "moduledata_v2.3diwell-backup")
    if os.path.exists(path):
        print("ОТКАЗ: фикстура уже существует — перегенерация запрещена (контракт заморожен).")
        return 2
    exports = [
        mp.get_provider("inventory").export_snapshot(INV_STORE, installed_version="1.7.24"),
        mp.get_provider("cost").export_snapshot(COST_STORE, installed_version="0.1.3"),
        mp.get_provider("quality").export_snapshot(mp.DictModuleStore(), installed_version="0.2.2"),
    ]
    blob = serializer.export_backup_v2(GATEWAY, protection_mode=schemas.PROTECTION_MODE_NONE,
                                       created_by=CREATED_BY, created_at=CREATED_AT,
                                       backup_id="mdfx000001", module_exports=exports)
    open(path, "wb").write(blob)
    sha = hashlib.sha256(blob).hexdigest()
    payload = serializer.decode_payload(blob)
    md = payload.module_data
    inv = [m for m in md["modules"] if m["module_id"] == "inventory"][0]
    manifest = {
        "note": "FROZEN module-data fixture (payload v2) — NEVER regenerate or modify.",
        "fixtures": [{
            "file": "moduledata_v2.3diwell-backup", "protection_mode": "none",
            "requires_password": False, "passphrase": None, "sha256": sha, "byte_length": len(blob),
            "expected": {
                "container_format_version": 2,
                "payload_schema_version": schemas.PAYLOAD_SCHEMA_VERSION,
                "printer_ids": [p.stable_id for p in payload.printers],
                "printer_tokens": {p.stable_id: p.credentials.get("token") for p in payload.printers},
                "core_values": payload.core.values,
                "core_machine_bound": payload.core.machine_bound,
                "module_ids": [m["module_id"] for m in md["modules"]],
                "inventory_spool_ids": [r["id"] for r in inv["domain_data"]["tables"]["inv_spools"]],
                "inventory_settings": inv["settings"],
                "quality_data_class": [m for m in md["modules"] if m["module_id"] == "quality"][0]["data_class"],
            },
        }],
    }
    open(os.path.join(HERE, "fixture_manifest.json"), "w", encoding="utf-8").write(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    open(os.path.join(HERE, "moduledata_v2.sha256"), "w", encoding="utf-8").write(sha + "\n")
    print("СОЗДАНА:", path)
    print("  SHA256:", sha, " bytes:", len(blob))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
