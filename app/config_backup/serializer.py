# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — сборка логического payload из хранилища и обратно (канонично, детерминированно).

Экспорт: gateway (реальное хранилище) -> BackupPayload -> канонический JSON -> зашифрованный
контейнер .3diwell-backup. Restore-применение — в restore_engine (использует payload_to_mutation).
Секреты (token принтера) попадают ТОЛЬКО внутрь шифра; header несекретен.
"""
from app.config_backup import schemas
from app.config_backup import settings_registry as reg
from app.config_backup import container_v1, container_v2
from app.config_backup.models import (BackupPayload, CoreSettingsSnapshot,
                                       ModuleSettingsSnapshot)
from app.config_backup.repository import printer_row_to_snapshot, snapshot_to_printer_row, Mutation
from app.config_backup.errors import (BackupError, BACKUP_INVALID,
                                      BACKUP_FROM_NEWER_VERSION)


def _read_effective(gateway, entry, cfg):
    if entry.store == reg.STORE_CONFIG_JSON:
        return reg.coerce_out(entry, cfg.get(entry.key))
    return reg.coerce_out(entry, gateway.get_app_setting(entry.key))


def build_payload(gateway, created_by="", module_exports=None):
    """Собрать BackupPayload из реального хранилища (только чтение). Детерминированный порядок.

    module_exports (Alpha 2.829): список УЖЕ собранных снапшотов провайдеров модулей
    (module_providers.ModuleBackupProvider.export_snapshot). Секция module_data у НОВОГО
    экспорта присутствует всегда (пустой список = «модулей нет»), в отличие от старых
    копий v1, где секция ОТСУТСТВУЕТ (None)."""
    cfg = gateway.get_config_json() or {}

    values, machine_bound = {}, {}
    for entry in reg.portable_settings():
        values[entry.key] = _read_effective(gateway, entry, cfg)
    for entry in reg.machine_bound_settings():
        machine_bound[entry.key] = _read_effective(gateway, entry, cfg)
    # excluded_settings() (operational/secret_derived) намеренно НЕ читаем.

    core = CoreSettingsSnapshot(schemas.CORE_SETTINGS_SCHEMA, values=values, machine_bound=machine_bound)

    printers = [printer_row_to_snapshot(r) for r in (gateway.list_printers() or [])]
    printers.sort(key=lambda p: (p.options.get("order_idx", 0), p.stable_id))

    modules = []
    for mid, mdata in sorted((gateway.get_module_settings() or {}).items()):
        mdata = mdata or {}
        modules.append(ModuleSettingsSnapshot(
            module_id=str(mid), schema_version=schemas.MODULE_SETTINGS_SCHEMA,
            enabled=bool(mdata.get("enabled", True)), values=dict(mdata.get("values") or {})))

    module_data = {"section_schema_version": schemas.MODULE_DATA_SECTION_SCHEMA,
                   "modules": sorted([dict(m) for m in (module_exports or [])],
                                     key=lambda m: str(m.get("module_id")))}
    return BackupPayload(schemas.PAYLOAD_SCHEMA_VERSION, created_by, core, printers, modules,
                         include_secrets=True, module_data=module_data)


def payload_canonical_bytes(payload):
    return container_v1.canonical_json_bytes(payload.as_dict())


def export_backup(gateway, passphrase, created_by="", created_at="", extra_meta=None, module_exports=None):
    """Полный экспорт -> bytes контейнера .3diwell-backup. created_at передаётся снаружи
    (в этой среде нет доступа к системным часам в тестах; server.py даёт time.strftime)."""
    payload = build_payload(gateway, created_by=created_by, module_exports=module_exports)
    payload_bytes = payload_canonical_bytes(payload)
    meta = {
        "created_by_app": str(created_by or ""),
        "created_at": str(created_at or ""),
        "payload_schema_version": schemas.PAYLOAD_SCHEMA_VERSION,
        "sections": ["core", "printers", "modules"],
        "printer_count": len(payload.printers),
        "module_count": len(payload.modules),
        "required_reader_capabilities": ["aes256gcm-scrypt-v1"],
    }
    if extra_meta:
        for k, v in extra_meta.items():
            if isinstance(k, str) and k.startswith(schemas.EXTENSION_NAMESPACE_PREFIX):
                meta[k] = v
    return container_v1.write_container(meta, payload_bytes, passphrase)


def export_backup_v2(gateway, protection_mode=schemas.DEFAULT_PROTECTION_MODE, passphrase=None,
                     created_by="", created_at="", backup_id="", extra_meta=None, module_exports=None):
    """Alpha 2.828 — экспорт в контейнер v2. protection_mode=none (по умолчанию, без пароля) или
    password_aes256gcm. Тот же build_payload/canonical payload, что и v1 — логическая модель одна."""
    payload = build_payload(gateway, created_by=created_by, module_exports=module_exports)
    payload_bytes = payload_canonical_bytes(payload)
    meta = {
        "backup_id": str(backup_id or ""),
        "created_by_app": str(created_by or ""),
        "created_at": str(created_at or ""),
        "sections": ["core", "printers", "modules"],
        "printer_count": len(payload.printers),
        "module_count": len(payload.modules),
    }
    if extra_meta:
        for k, v in extra_meta.items():
            if isinstance(k, str) and k.startswith(schemas.EXTENSION_NAMESPACE_PREFIX):
                meta[k] = v
    return container_v2.write_container_v2(meta, payload_bytes, protection_mode, passphrase)


def _peek_version(container_bytes):
    """Определить версию контейнера по header (безопасно). -> (container_version, header)."""
    _hb, header = container_v2.peek_header(container_bytes)
    cfv = header.get("container_format_version")
    if not isinstance(cfv, int) or cfv < 1:
        raise BackupError(BACKUP_INVALID, "bad container_format_version")
    if cfv > schemas.MAX_CONTAINER_FORMAT_VERSION:
        raise BackupError(BACKUP_FROM_NEWER_VERSION, "container from newer version")
    return cfv, header


def inspect_container(container_bytes):
    """НЕСЕКРЕТНЫЕ metadata (без пароля) для v1 И v2. Отдаёт версию контейнера, режим защиты и
    requires_password, чтобы UI знал, показывать поле пароля или нет. Ничего не расшифровывает."""
    cfv, header = _peek_version(container_bytes)
    if cfv == schemas.CONTAINER_FORMAT_VERSION:                       # v1 — всегда зашифрован
        header_bytes, header, _ct = container_v1.read_container(container_bytes)
        enc = header.get("encryption") or {}
        return {
            "format_id": header.get("format_id"),
            "container_format_version": 1,
            "protection_mode": schemas.PROTECTION_MODE_PASSWORD,
            "requires_password": True,
            "payload_schema_version": header.get("payload_schema_version"),
            "created_by_app": header.get("created_by_app", ""),
            "created_at": header.get("created_at", ""),
            "printer_count": header.get("printer_count"),
            "module_count": header.get("module_count"),
            "kdf": enc.get("kdf"), "cipher": enc.get("cipher"),
        }
    # v2 — строгий разбор + режим защиты из header
    header_bytes, header, _body = container_v2.read_container_v2(container_bytes)
    mode = header.get("protection_mode")
    enc = header.get("encryption") or {}
    return {
        "format_id": header.get("format_id"),
        "container_format_version": 2,
        "protection_mode": mode,
        "requires_password": container_v2.requires_password(header),
        "payload_schema_version": header.get("payload_schema_version"),
        "created_by_app": header.get("created_by_app", ""),
        "created_at": header.get("created_at", ""),
        "backup_id": header.get("backup_id", ""),
        "printer_count": header.get("printer_count"),
        "module_count": header.get("module_count"),
        "kdf": enc.get("kdf") if mode == schemas.PROTECTION_MODE_PASSWORD else None,
        "cipher": enc.get("cipher") if mode == schemas.PROTECTION_MODE_PASSWORD else None,
    }


def decode_payload(container_bytes, passphrase=None):
    """Прочитать контейнер (v1 ИЛИ v2) -> BackupPayload. Версия определяется по header, а НЕ по
    расширению/наличию текста. Неверный пароль/повреждение шифра -> единый безопасный код."""
    cfv, _header = _peek_version(container_bytes)
    if cfv == schemas.CONTAINER_FORMAT_VERSION:                       # v1
        header_bytes, header, ciphertext = container_v1.read_container(container_bytes)
        plaintext = container_v1.decrypt_payload(header_bytes, header, ciphertext, passphrase)
    else:                                                            # v2 (none/password)
        header_bytes, header, body = container_v2.read_container_v2(container_bytes)
        plaintext = container_v2.load_payload_v2(header_bytes, header, body, passphrase)
    import json
    try:
        obj = json.loads(plaintext.decode("utf-8"))
    except Exception:
        raise BackupError(BACKUP_INVALID, "payload not valid json")
    if not isinstance(obj, dict):
        raise BackupError(BACKUP_INVALID, "payload not object")
    return BackupPayload.from_dict(obj)


def payload_to_mutation(payload, selected_sections, apply_machine_bound=False, hold_keys=()):
    """Преобразовать (уже провалидированный/мигрированный) payload в Mutation по выбранным секциям.
    Учитывает restore_behavior реестра: import_as_off форсирует OFF, current_only/exclude пропускаются,
    machine_bound применяется ТОЛЬКО при явном apply_machine_bound.
    hold_keys (R-128): ключи core, которые не пишутся вовсе (restore_plan.security_hold_keys)."""
    mut = Mutation()
    sel = set(selected_sections or ())
    held = set(hold_keys or ())

    if "core" in sel:
        vals = (payload.core.values or {})
        for entry in reg.portable_settings():
            if entry.key not in vals:
                continue
            if entry.key in held:
                continue   # R-128: значение копии не применяется, текущее остаётся как есть
            rb = entry.restore_behavior
            if rb == reg.RB_EXCLUDE or rb == reg.RB_CURRENT_ONLY:
                continue
            value = vals[entry.key]
            if rb == reg.RB_IMPORT_AS_OFF:
                value = False   # деструктивная/сетевая функция импортируется выключенной
            stored = reg.coerce_store(entry, value)
            if entry.store == reg.STORE_CONFIG_JSON:
                mut.config_set[entry.key] = stored
            else:
                mut.app_set[entry.key] = stored
        if apply_machine_bound:
            mb = (payload.core.machine_bound or {})
            for entry in reg.machine_bound_settings():
                if entry.key not in mb:
                    continue
                stored = reg.coerce_store(entry, mb[entry.key])
                if entry.store == reg.STORE_CONFIG_JSON:
                    mut.config_set[entry.key] = stored
                else:
                    mut.app_set[entry.key] = stored

    if "printers" in sel:
        for snap in payload.printers:
            if not snap.stable_id:
                continue
            mut.printers_upsert.append(snapshot_to_printer_row(snap))

    # modules — секция v1 хранится, но применение модульных настроек делегируется их владельцам
    # в отдельной итерации (см. restore_plan); ядро v1 применяет core+printers.
    return mut
