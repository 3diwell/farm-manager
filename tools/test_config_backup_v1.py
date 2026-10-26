# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — формат v1: замороженные константы, валидатор, миграции (append-only)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import schemas, serializer, validator, migrations
from app.config_backup.errors import BackupError
from app.config_backup.repository import DictGateway

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


def _payload():
    gw = DictGateway(
        config={"lan_access_enabled": True, "project_print_enabled": True, "modules_disabled": [],
                "data_dir": "D:\\d", "server_port": 8000},
        app_settings={"net_monitor": "1"},
        printers=[{"id": "a", "name": "A", "type": "bambu", "ip": "1.2.3.4", "port": 8883,
                   "token": "T", "last_parts": "{}", "order_idx": 0, "gen": "auto",
                   "serial": "S", "model": "X1C"}])
    blob = serializer.export_backup(gw, "pw", created_by="t", created_at="t")
    return serializer.decode_payload(blob, "pw").as_dict()


def sec_constants():
    print("--- замороженные константы формата v1 ---")
    check("1. FORMAT_ID постоянен",
          schemas.FORMAT_ID == "com.3diwell.farm-manager.configuration-backup")
    check("2. расширение .3diwell-backup", schemas.BACKUP_EXTENSION == ".3diwell-backup")
    # Заморожен КОНТЕЙНЕР v1; payload schema эволюционирует append-only миграциями
    # (Alpha 2.829: v2 добавила секцию module_data — это ШТАТНЫЙ механизм, не правка v1).
    check("3. контейнер v1 заморожен; payload/секции растут только миграциями",
          schemas.CONTAINER_FORMAT_VERSION == 1 and schemas.PAYLOAD_SCHEMA_VERSION >= 1
          and schemas.CORE_SETTINGS_SCHEMA == 1 and schemas.PRINTERS_SCHEMA == 1
          and schemas.MODULE_SETTINGS_SCHEMA == 1
          and migrations.migration_path_len(1) == schemas.PAYLOAD_SCHEMA_VERSION - 1)
    check("4. схемы адаптеров объявлены (bambu/flashforge/moonraker/klipper)",
          set(schemas.ADAPTER_SCHEMAS) >= {"bambu", "flashforge", "moonraker", "klipper"})
    check("5. базовая крипто-возможность известна ридеру",
          "aes256gcm-scrypt-v1" in schemas.KNOWN_READER_CAPABILITIES)
    check("6. пространство расширений namespaced 'x-'",
          schemas.EXTENSION_NAMESPACE_PREFIX == "x-")


def sec_validator():
    print("--- валидатор (данные, не команды) ---")
    ok_payload = validator.validate_payload(_payload())
    check("7. валидный payload проходит", len(ok_payload.printers) == 1)
    # future payload version
    fut = _payload(); fut["manifest"]["payload_schema_version"] = 99
    check("8. payload из будущей версии -> backup_from_newer_version",
          _reason(lambda: validator.validate_payload(fut)) == "backup_from_newer_version")
    # future core section schema
    fc = _payload(); fc["core"]["schema_version"] = 5
    check("9. секция core из будущей версии отклонена",
          _reason(lambda: validator.validate_payload(fc)) == "backup_from_newer_version")
    # future adapter schema (known adapter)
    fa = _payload(); fa["printers"][0]["adapter_schema_version"] = 9
    check("10. известный адаптер из будущей схемы отклонён",
          _reason(lambda: validator.validate_payload(fa)) == "backup_from_newer_version")
    # duplicate printer id
    du = _payload(); du["printers"].append(dict(du["printers"][0]))
    check("11. дубликат stable_id принтера отклонён",
          _reason(lambda: validator.validate_payload(du)) == "validation_failed")
    # empty stable id
    em = _payload(); em["printers"][0]["stable_id"] = ""
    check("12. пустой stable_id отклонён",
          _reason(lambda: validator.validate_payload(em)) == "validation_failed")
    # unknown non-namespaced core value dropped; namespaced ext kept
    ux = _payload(); ux["core"]["values"]["totally_unknown_key"] = 7
    ux["core"]["extensions"] = {"x-vendor": 1, "bogus": 2}
    v = validator.validate_payload(ux)
    check("13. неизвестный не-namespaced ключ отброшен",
          "totally_unknown_key" not in v.core.values)
    check("14. namespaced 'x-' расширение сохранено, прочее отброшено",
          v.core.extensions.get("x-vendor") == 1 and "bogus" not in v.core.extensions)
    # unknown adapter type preserved (forward-friendly)
    na = _payload(); na["printers"][0]["adapter"] = "future-brand"; na["printers"][0]["adapter_schema_version"] = 1
    v2 = validator.validate_payload(na)
    check("15. неизвестный тип адаптера сохранён как есть (forward-friendly)",
          v2.printers[0].adapter == "future-brand")


def sec_migrations():
    print("--- миграции (append-only) ---")
    check("16. цепочка миграций от v1 полная (без пропусков)",
          migrations.migration_path_len(1) == migrations.schemas.PAYLOAD_SCHEMA_VERSION - 1)
    # РЕАЛЬНЫЙ payload v1 (как в копиях 2.827-2.828): без module_data, manifest=1.
    raw = _payload()
    raw["manifest"]["payload_schema_version"] = 1
    raw.pop("module_data", None)
    core_before = raw["core"]
    mig = migrations.migrate_to_current(raw)
    check("17. v1 -> current: module_data=None (ОТСУТСТВУЕТ, не пусто); core/printers не тронуты",
          mig["manifest"]["payload_schema_version"] == migrations.schemas.PAYLOAD_SCHEMA_VERSION
          and mig.get("module_data") is None and mig["core"] == core_before)
    fut = _payload(); fut["manifest"]["payload_schema_version"] = 99
    check("18. миграция из будущего -> backup_from_newer_version",
          _reason(lambda: migrations.migrate_to_current(fut)) == "backup_from_newer_version")
    check("19. реестр миграций — ровно append-only цепочка 1..current-1",
          set(migrations.PAYLOAD_MIGRATIONS.keys())
          == set(range(1, migrations.schemas.PAYLOAD_SCHEMA_VERSION)))
    # AAD-привязка: подмена header ломает расшифровку
    from app.config_backup import container_v1
    gw = DictGateway(config={"lan_access_enabled": True}, app_settings={"net_monitor": "1"}, printers=[])
    blob = serializer.export_backup(gw, "pw", created_by="t", created_at="t")
    hb, hdr, ct = container_v1.read_container(blob)
    tampered = dict(hdr); tampered["created_by_app"] = "attacker"
    try:
        container_v1.decrypt_payload(container_v1.canonical_json_bytes(tampered), tampered, ct, "pw")
        ok = False
    except BackupError as e:
        ok = e.reason == "backup_corrupted_or_wrong_password"
    check("20. header является AAD: его подмена ломает расшифровку (единый код)", ok)


def _reason(fn):
    try:
        fn(); return None
    except BackupError as e:
        return e.reason


if __name__ == "__main__":
    sec_constants()
    sec_validator()
    sec_migrations()
    print("\n" + "=" * 60)
    print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
    sys.exit(1 if _n["fail"] else 0)
