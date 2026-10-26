# -*- coding: utf-8 -*-
"""Alpha 2.827 — ГЕНЕРАТОР замороженной v1-фикстуры резервной копии (запускается ОДИН раз).

ВНИМАНИЕ: sample.3diwell-backup — ПОСТОЯННЫЙ публичный контракт. После первой генерации и
коммита его НЕЛЬЗЯ перегенерировать или менять НИКОГДА (тест test_config_backup_compatibility_forever
обязан вечно восстанавливать именно эти байты). Этот скрипт хранится лишь для провенанса:
он документирует, из каких синтетических данных получена фикстура. Данные синтетические —
никаких реальных токенов/адресов. Соль/nonce случайны -> повторный запуск даст ДРУГИЕ байты;
поэтому запускать повторно ЗАПРЕЩЕНО (перезапись сломает контракт).

Запуск (только если файла ещё нет):  python tools/fixtures/config_backup/v1/make_v1_fixture.py
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))

from app.config_backup import serializer
from app.config_backup.repository import DictGateway

# Зафиксированный тестовый пароль фикстуры (НЕ секрет — часть публичного теста).
FIXTURE_PASSPHRASE = "3diwell-frozen-v1-fixture-passphrase"
FIXTURE_CREATED_AT = "2026-07-24 00:00:00"
FIXTURE_CREATED_BY = "3DIWELL Farm Manager Alpha 2.827 (frozen v1 fixture)"

# Синтетическое хранилище: 1 Bambu + 1 FlashForge + 1 Moonraker(klipper) + все настройки ядра.
GATEWAY = DictGateway(
    config={
        "lan_access_enabled": True,
        "project_print_enabled": True,
        "modules_disabled": ["quality"],
        "data_dir": "D:\\FrozenFixture\\data",         # machine_bound -> current_only
        "server_port": 8000,                             # machine_bound -> current_only
        "pending_server_port": 9099,                     # operational -> ИСКЛЮЧЁН
        "migrate_from": "C:\\old\\data",                 # operational -> ИСКЛЮЧЁН
    },
    app_settings={
        "net_monitor": "1",
        "security_enabled": "1",
        "slicer_callback_enabled": "1",
        "printer_files_read_enabled": "1",
        "printer_files_delete_enabled": "1",             # destructive -> import_as_off при restore
        "archive_dir": "E:\\FrozenFixture\\archive",     # machine_bound
        "slicer_path": "C:\\Program Files\\Orca\\orca-slicer.exe",  # machine_bound
        "slicer_callback_token_hash": "0000frozenfixturehash0000",  # secret_derived -> ИСКЛЮЧЁН
        "slicer_callback_token_created_at": "2026-01-01 00:00:00",  # secret_derived -> ИСКЛЮЧЁН
    },
    printers=[
        {"id": "fixture-bambu-x1c", "name": "Bambu X1C (fixture)", "type": "bambu",
         "ip": "192.168.50.11", "port": 8883, "token": "FIXTURE_BAMBU_ACCESS_CODE",
         "last_parts": "{\"gear\": 3}", "order_idx": 0, "gen": "auto",
         "serial": "FIXTURE-BAMBU-0001", "model": "X1C"},
        {"id": "fixture-ff-ad5m", "name": "FlashForge AD5M (fixture)", "type": "flashforge",
         "ip": "192.168.50.12", "port": 8898, "token": "FIXTURE_FF_CHECKCODE",
         "last_parts": "{}", "order_idx": 1, "gen": "auto",
         "serial": "FIXTURE-FF-0001", "model": "Adventurer 5M"},
        {"id": "fixture-moonraker-v2", "name": "Voron 2.4 (fixture)", "type": "klipper",
         "ip": "192.168.50.13", "port": 7125, "token": "FIXTURE_MOONRAKER_APIKEY",
         "last_parts": "{}", "order_idx": 2, "gen": "auto",
         "serial": "FIXTURE-VORON-0001", "model": "Voron 2.4"},
    ],
    modules={},
)

BACKUP_PATH = os.path.join(HERE, "sample.3diwell-backup")
META_PATH = os.path.join(HERE, "sample.meta.json")


def main():
    if os.path.exists(BACKUP_PATH):
        print("ОТКАЗ: фикстура уже существует — перегенерация запрещена (контракт заморожен).")
        print("       ", BACKUP_PATH)
        return 2
    blob = serializer.export_backup(GATEWAY, FIXTURE_PASSPHRASE,
                                    created_by=FIXTURE_CREATED_BY, created_at=FIXTURE_CREATED_AT)
    with open(BACKUP_PATH, "wb") as f:
        f.write(blob)
    sha = hashlib.sha256(blob).hexdigest()
    # Ожидаемое расшифрованное содержимое (канонический payload) — для сверки в тесте.
    payload = serializer.decode_payload(blob, FIXTURE_PASSPHRASE)
    meta = {
        "note": "FROZEN v1 fixture — NEVER regenerate or modify. Permanent restore contract.",
        "passphrase": FIXTURE_PASSPHRASE,
        "created_at": FIXTURE_CREATED_AT,
        "sha256": sha,
        "byte_length": len(blob),
        "expected": {
            "container_format_version": 1,
            "payload_schema_version": 1,
            "printer_ids": [p.stable_id for p in payload.printers],
            "printer_adapters": {p.stable_id: p.adapter for p in payload.printers},
            "printer_tokens": {p.stable_id: p.credentials.get("token") for p in payload.printers},
            "core_values": payload.core.values,
            "core_machine_bound": payload.core.machine_bound,
        },
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("СОЗДАНА фикстура:", BACKUP_PATH)
    print("  SHA256:", sha, "  bytes:", len(blob))
    print("  META  :", META_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
