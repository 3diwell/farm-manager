# -*- coding: utf-8 -*-
"""Alpha 2.830 — ГЕНЕРАТОР sanitized regression-фикстуры (один запуск).

Воспроизводит ТОЛЬКО ФОРМУ дефекта Alpha 2.829 (validation_failed): внутренняя ссылка на
УДАЛЁННУЮ запись — inv_items.location_id и inv_spools.location_id указывают на локацию, которой
нет в inv_locations (пользователь удалил локацию, товар/катушка сохранили старый id). Это
compatibility regression fixture, НЕ новый формат контейнера (обычный v2, payload schema 2).

СИНТЕТИКА: выдуманные id/имена/креды (FIXTURE_*), НЕ реальные записи, НЕ реальный SHA копии
пользователя, без sentinel. После коммита — неизменяема (SHA-256).
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "..")))

from app.config_backup import serializer, schemas
from app.config_backup import module_providers as mp
from app.config_backup.repository import DictGateway

CREATED_AT = "2026-07-25 02:00:00 UTC"
CREATED_BY = "3DIWELL Farm Manager Alpha 2.829 (regression fixture: dangling internal ref)"

GATEWAY = DictGateway(
    config={"lan_access_enabled": True, "modules_disabled": [], "server_port": 8000},
    app_settings={"net_monitor": "1"},
    printers=[{"id": "fixture-reg-bambu", "name": "Bambu (reg fixture)", "type": "bambu",
               "ip": "192.168.99.10", "port": 8883, "token": "FIXTURE_REG_CODE",
               "last_parts": "{}", "order_idx": 0, "gen": "auto", "serial": "FIXTURE-REG",
               "model": "X1C"}])

# Инвентарь с ВИСЯЧИМИ внутренними ссылками на удалённую локацию "loc-DELETED":
INV = mp.DictModuleStore(tables={
    "inv_vendors": [{"id": "vnd-1", "name": "FIXTURE Vendor", "notes": "", "order_idx": 0,
                     "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
    "inv_filaments": [{"id": "fil-1", "vendor_id": "vnd-1", "material": "PLA", "color_name": "X",
                       "color_hex": "#111", "diameter": 1.75, "density": 1.24, "temp_min": 190,
                       "temp_max": 220, "spool_weight_g": 180, "price_per_kg": 1000, "notes": "",
                       "order_idx": 0, "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
    "inv_locations": [{"id": "loc-1", "name": "FIXTURE Shelf", "parent_id": "", "notes": "",
                       "order_idx": 0, "is_deleted": 0, "created_at": "t"}],
    # item ссылается на loc-DELETED (нет в inv_locations) — ТОЧНАЯ форма дефекта:
    "inv_items": [{"id": "item-1", "name": "FIXTURE Nozzle", "category": "parts", "unit": "шт",
                   "qty": 2, "min_qty": 0, "max_qty": 5, "location_id": "loc-DELETED", "price": 10,
                   "printer_brand": "", "printer_model": "", "notes": "", "order_idx": 0,
                   "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
    "inv_spools": [
        # spool-1: валидная локация; spool-2: висячая location_id; spool-3: пустая (нет ссылки)
        {"id": "spool-1", "filament_id": "fil-1", "label": "A", "weight_total_g": 1000,
         "weight_remaining_g": 500, "location_id": "loc-1", "price": 1000, "lot": "L1",
         "purchased_at": "2026-01-01", "opened_at": "", "status": "in_stock", "nfc_uid": "",
         "ams_printer_id": "fixture-reg-bambu", "ams_slot": 0, "notes": "", "order_idx": 0,
         "is_deleted": 0, "created_at": "t", "updated_at": "t"},
        {"id": "spool-2", "filament_id": "fil-1", "label": "B", "weight_total_g": 1000,
         "weight_remaining_g": 800, "location_id": "loc-DELETED", "price": 1000, "lot": "L2",
         "purchased_at": "2026-01-02", "opened_at": "", "status": "in_stock", "nfc_uid": "",
         "ams_printer_id": "", "ams_slot": -1, "notes": "", "order_idx": 1,
         "is_deleted": 0, "created_at": "t", "updated_at": "t"},
        {"id": "spool-3", "filament_id": "fil-1", "label": "C", "weight_total_g": 1000,
         "weight_remaining_g": 900, "location_id": "", "price": 1000, "lot": "L3",
         "purchased_at": "2026-01-03", "opened_at": "", "status": "in_stock", "nfc_uid": "",
         "ams_printer_id": "", "ams_slot": -1, "notes": "", "order_idx": 2,
         "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
    "inv_ledger": [{"id": "lg-1", "ts": "t", "kind": "adjust", "ref_type": "spool",
                    "ref_id": "spool-1", "qty": -10, "reason": "fixture", "job_id": "",
                    "username": "fixture", "note": ""}],
}, settings={"currency": "RUB"})


def main():
    path = os.path.join(HERE, "dangling_ref_v2.3diwell-backup")
    if os.path.exists(path):
        print("ОТКАЗ: фикстура уже существует — перегенерация запрещена (заморожена).")
        return 2
    exports = [
        mp.get_provider("inventory").export_snapshot(INV, installed_version="1.7.24"),
        mp.get_provider("cost").export_snapshot(mp.DictModuleStore(), installed_version="0.1.3"),
        mp.get_provider("quality").export_snapshot(mp.DictModuleStore(), installed_version="0.2.2"),
    ]
    blob = serializer.export_backup_v2(GATEWAY, protection_mode=schemas.PROTECTION_MODE_NONE,
                                       created_by=CREATED_BY, created_at=CREATED_AT,
                                       backup_id="regfx00001", module_exports=exports)
    open(path, "wb").write(blob)
    sha = hashlib.sha256(blob).hexdigest()
    manifest = {
        "note": "SANITIZED regression fixture (Alpha 2.830). Reproduces the SHAPE of the Alpha "
                "2.829 validation_failed defect: internal reference to a DELETED entity "
                "(inv_items.location_id / inv_spools.location_id -> missing inv_locations row). "
                "Synthetic IDs/names/credentials only. Compatibility regression fixture, NOT a new "
                "container format. NEVER regenerate or modify.",
        "file": "dangling_ref_v2.3diwell-backup",
        "container_format_version": 2,
        "payload_schema_version": schemas.PAYLOAD_SCHEMA_VERSION,
        "protection_mode": "none",
        "requires_password": False,
        "sha256": sha,
        "byte_length": len(blob),
        "defect_shape": {
            "reason_old": "validation_failed",
            "field_paths": ["module_data.inventory.domain_data.tables.inv_items[].location_id",
                            "module_data.inventory.domain_data.tables.inv_spools[].location_id"],
            "unresolved_target": "inv_locations",
            "expected_new_behavior": "tolerated + dangling_internal_ref warning + record preserved",
        },
    }
    open(os.path.join(HERE, "fixture_manifest.json"), "w", encoding="utf-8").write(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    open(os.path.join(HERE, "dangling_ref_v2.sha256"), "w", encoding="utf-8").write(sha + "\n")
    print("СОЗДАНА:", os.path.basename(path))
    print("  SHA256:", sha, " bytes:", len(blob))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
