# -*- coding: utf-8 -*-
"""Alpha 2.828 — ГЕНЕРАТОР замороженных v2-фикстур (запускается ОДИН раз).

ВНИМАНИЕ: passwordless_v2.3diwell-backup и protected_v2.3diwell-backup — ПОСТОЯННЫЙ публичный
контракт. После первой генерации и коммита их НЕЛЬЗЯ перегенерировать или менять НИКОГДА
(test_config_backup_compatibility_forever обязан вечно их восстанавливать). Данные синтетические:
никаких реальных токенов/адресов; credential помечен FIXTURE_ и НЕ совпадает с sentinel.
Соль/nonce protected-фикстуры случайны -> повторный запуск даст ДРУГИЕ байты -> ЗАПРЕЩЕНО.

Запуск (только если файлов ещё нет):  python tools/fixtures/config_backup/v2/make_v2_fixtures.py
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))

from app.config_backup import serializer, schemas
from app.config_backup.repository import DictGateway

PROTECTED_PASSPHRASE = "3diwell-frozen-v2-protected-fixture-passphrase"
CREATED_AT = "2026-07-24 00:00:00 UTC"
CREATED_BY = "3DIWELL Farm Manager Alpha 2.828 (frozen v2 fixtures)"

# Синтетическое хранилище: 1 Bambu + 1 FlashForge + 1 Moonraker + настройки ядра.
GATEWAY = DictGateway(
    config={"lan_access_enabled": True, "project_print_enabled": True, "modules_disabled": ["quality"],
            "data_dir": "D:\\FrozenV2\\data", "server_port": 8000,
            "pending_server_port": 9099, "migrate_from": "C:\\old\\data"},
    app_settings={"net_monitor": "1", "security_enabled": "1", "slicer_callback_enabled": "1",
                  "printer_files_read_enabled": "1", "printer_files_delete_enabled": "1",
                  "archive_dir": "E:\\FrozenV2\\archive", "slicer_path": "C:\\Program Files\\Orca\\orca-slicer.exe",
                  "slicer_callback_token_hash": "0000frozenv2hash0000", "slicer_callback_token_created_at": "2026-01-01 00:00:00"},
    printers=[
        {"id": "fixture-v2-bambu", "name": "Bambu X1C (v2 fixture)", "type": "bambu",
         "ip": "192.168.60.11", "port": 8883, "token": "FIXTURE_V2_BAMBU_ACCESS_CODE",
         "last_parts": "{}", "order_idx": 0, "gen": "auto", "serial": "FIXTURE-V2-BAMBU", "model": "X1C"},
        {"id": "fixture-v2-ff", "name": "FlashForge AD5M (v2 fixture)", "type": "flashforge",
         "ip": "192.168.60.12", "port": 8898, "token": "FIXTURE_V2_FF_CHECKCODE",
         "last_parts": "{}", "order_idx": 1, "gen": "auto", "serial": "FIXTURE-V2-FF", "model": "Adventurer 5M"},
        {"id": "fixture-v2-voron", "name": "Voron 2.4 (v2 fixture)", "type": "klipper",
         "ip": "192.168.60.13", "port": 7125, "token": "FIXTURE_V2_MOONRAKER_APIKEY",
         "last_parts": "{}", "order_idx": 2, "gen": "auto", "serial": "FIXTURE-V2-VORON", "model": "Voron 2.4"},
    ],
    modules={},
)


def _expected(blob, passphrase):
    payload = serializer.decode_payload(blob, passphrase)
    return {
        "container_format_version": 2,
        "payload_schema_version": 1,
        "printer_ids": [p.stable_id for p in payload.printers],
        "printer_adapters": {p.stable_id: p.adapter for p in payload.printers},
        "printer_tokens": {p.stable_id: p.credentials.get("token") for p in payload.printers},
        "core_values": payload.core.values,
        "core_machine_bound": payload.core.machine_bound,
    }


def _emit(name, blob, passphrase, protection_mode):
    path = os.path.join(HERE, name + ".3diwell-backup")
    if os.path.exists(path):
        raise SystemExit("ОТКАЗ: %s уже существует — перегенерация запрещена (контракт заморожен)." % path)
    open(path, "wb").write(blob)
    sha = hashlib.sha256(blob).hexdigest()
    open(os.path.join(HERE, name + ".sha256"), "w", encoding="utf-8").write(sha + "\n")
    return {"file": name + ".3diwell-backup", "protection_mode": protection_mode,
            "requires_password": protection_mode == schemas.PROTECTION_MODE_PASSWORD,
            "passphrase": passphrase, "sha256": sha, "byte_length": len(blob),
            "expected": _expected(blob, passphrase)}


def main():
    entries = []
    # passwordless (none) — основной сценарий Alpha 2.828
    b_none = serializer.export_backup_v2(GATEWAY, protection_mode=schemas.PROTECTION_MODE_NONE,
                                         created_by=CREATED_BY, created_at=CREATED_AT, backup_id="v2none0001")
    entries.append(_emit("passwordless_v2", b_none, None, schemas.PROTECTION_MODE_NONE))
    # protected (password_aes256gcm) — дополнительный режим
    b_pw = serializer.export_backup_v2(GATEWAY, protection_mode=schemas.PROTECTION_MODE_PASSWORD,
                                       passphrase=PROTECTED_PASSPHRASE, created_by=CREATED_BY,
                                       created_at=CREATED_AT, backup_id="v2pw000001")
    entries.append(_emit("protected_v2", b_pw, PROTECTED_PASSPHRASE, schemas.PROTECTION_MODE_PASSWORD))

    manifest = {"note": "FROZEN v2 fixtures — NEVER regenerate or modify. Permanent restore contract.",
                "container_format_version": 2, "fixtures": entries}
    open(os.path.join(HERE, "fixture_manifest.json"), "w", encoding="utf-8").write(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    for e in entries:
        print("СОЗДАНА:", e["file"], "mode=%s sha=%s bytes=%d" % (e["protection_mode"], e["sha256"][:16], e["byte_length"]))
    print("manifest: fixture_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
