# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — валидация и санитизация УЖЕ мигрированного payload (данные, не команды).

Строго: типы, границы, уникальность идентичности принтера, версии секций/адаптеров.
Секция/адаптер из БУДУЩЕЙ версии -> безопасный отказ (структуру знать нельзя). Неизвестные
НЕ-namespaced ключи отбрасываются (не применяются); namespaced 'x-...' расширения сохраняются.
Ничего из payload не исполняется.
"""
from app.config_backup import schemas
from app.config_backup import settings_registry as reg
from app.config_backup.models import (BackupPayload, CoreSettingsSnapshot,
                                       PrinterSnapshot, ModuleSettingsSnapshot)
from app.config_backup.errors import (BackupError, VALIDATION_FAILED,
                                       BACKUP_FROM_NEWER_VERSION)

MAX_PRINTERS = 512
MAX_MODULES = 128
MAX_STR = 8192
MAX_LIST = 4096


def _need(cond, detail):
    if not cond:
        raise BackupError(VALIDATION_FAILED, detail)


def _clip_str(v):
    s = "" if v is None else str(v)
    if len(s) > MAX_STR:
        raise BackupError(VALIDATION_FAILED, "string too long")
    return s


def _sanitize_core(raw_core):
    _need(isinstance(raw_core, dict), "core not object")
    sv = raw_core.get("schema_version", schemas.CORE_SETTINGS_SCHEMA)
    _need(isinstance(sv, int) and sv >= 1, "bad core schema_version")
    if sv > schemas.CORE_SETTINGS_SCHEMA:
        raise BackupError(BACKUP_FROM_NEWER_VERSION, "core section from newer version")
    raw_values = raw_core.get("values") or {}
    raw_mb = raw_core.get("machine_bound") or {}
    _need(isinstance(raw_values, dict) and isinstance(raw_mb, dict), "core values/machine_bound not object")

    values, machine_bound = {}, {}
    for e in reg.portable_settings():
        if e.key in raw_values:
            values[e.key] = reg.coerce_out(e, raw_values[e.key])   # только зарегистрированные ключи
    for e in reg.machine_bound_settings():
        if e.key in raw_mb:
            machine_bound[e.key] = reg.coerce_out(e, raw_mb[e.key])
    # неизвестные не-namespaced ключи молча отброшены (не применяются)
    ext = {k: v for k, v in (raw_core.get("extensions") or {}).items()
           if isinstance(k, str) and k.startswith(schemas.EXTENSION_NAMESPACE_PREFIX)}
    return CoreSettingsSnapshot(schemas.CORE_SETTINGS_SCHEMA, values=values,
                                machine_bound=machine_bound, extensions=ext)


def _sanitize_printer(raw):
    _need(isinstance(raw, dict), "printer not object")
    sid = _clip_str(raw.get("stable_id"))
    _need(sid != "", "printer stable_id empty")
    adapter = _clip_str(raw.get("adapter")).strip().lower()
    _need(adapter != "", "printer adapter empty")
    asv = raw.get("adapter_schema_version", 1)
    _need(isinstance(asv, int) and asv >= 1, "bad adapter_schema_version")
    # известный адаптер из будущей версии схемы -> отказ; неизвестный адаптер сохраняем как есть
    known = schemas.ADAPTER_SCHEMAS.get(adapter)
    if known is not None and asv > known:
        raise BackupError(BACKUP_FROM_NEWER_VERSION, "adapter '%s' from newer schema" % adapter)
    conn = raw.get("connection") or {}
    opts = raw.get("options") or {}
    creds = raw.get("credentials") or {}
    _need(isinstance(conn, dict) and isinstance(opts, dict) and isinstance(creds, dict),
          "printer sub-objects not object")
    port = conn.get("port")
    if port not in (None, ""):
        try:
            port = int(port)
        except Exception:
            raise BackupError(VALIDATION_FAILED, "printer port not int")
        _need(0 < port <= 65535, "printer port out of range")
    else:
        port = None
    try:
        order_idx = int(opts.get("order_idx") or 0)
    except Exception:
        raise BackupError(VALIDATION_FAILED, "printer order_idx not int")
    return PrinterSnapshot(
        stable_id=sid, adapter=adapter, adapter_schema_version=asv,
        display_name=_clip_str(raw.get("display_name")), model=_clip_str(raw.get("model")),
        enabled=bool(raw.get("enabled", True)),
        connection={"ip": _clip_str(conn.get("ip")), "port": port,
                    "gen": _clip_str(conn.get("gen") or "auto"), "serial": _clip_str(conn.get("serial"))},
        options={"order_idx": order_idx},
        credentials={"token": _clip_str(creds.get("token"))},
        extensions={k: v for k, v in (raw.get("extensions") or {}).items()
                    if isinstance(k, str) and k.startswith(schemas.EXTENSION_NAMESPACE_PREFIX)})


def _sanitize_module(raw):
    _need(isinstance(raw, dict), "module not object")
    mid = _clip_str(raw.get("module_id"))
    _need(mid != "", "module_id empty")
    sv = raw.get("schema_version", schemas.MODULE_SETTINGS_SCHEMA)
    _need(isinstance(sv, int) and sv >= 1, "bad module schema_version")
    if sv > schemas.MODULE_SETTINGS_SCHEMA:
        raise BackupError(BACKUP_FROM_NEWER_VERSION, "module '%s' from newer version" % mid)
    vals = raw.get("values") or {}
    _need(isinstance(vals, dict), "module values not object")
    if len(vals) > MAX_LIST:
        raise BackupError(VALIDATION_FAILED, "module values too large")
    return ModuleSettingsSnapshot(module_id=mid, schema_version=schemas.MODULE_SETTINGS_SCHEMA,
                                  enabled=bool(raw.get("enabled", True)), values=dict(vals))


def validate_payload(raw):
    """Провалидировать и санитизировать payload-dict (после migrate_to_current) -> BackupPayload.
    Любая структурная проблема -> VALIDATION_FAILED; будущая версия секции -> BACKUP_FROM_NEWER_VERSION."""
    _need(isinstance(raw, dict), "payload not object")
    man = raw.get("manifest") or {}
    psv = man.get("payload_schema_version")
    _need(isinstance(psv, int), "bad payload_schema_version")
    if psv > schemas.PAYLOAD_SCHEMA_VERSION:
        raise BackupError(BACKUP_FROM_NEWER_VERSION, "payload from newer version")
    _need(psv == schemas.PAYLOAD_SCHEMA_VERSION, "payload not migrated to current")

    core = _sanitize_core(raw.get("core") or {})

    raw_printers = raw.get("printers") or []
    _need(isinstance(raw_printers, list), "printers not list")
    _need(len(raw_printers) <= MAX_PRINTERS, "too many printers")
    printers, seen = [], set()
    for rp in raw_printers:
        snap = _sanitize_printer(rp)
        if snap.stable_id in seen:
            raise BackupError(VALIDATION_FAILED, "duplicate printer stable_id")
        seen.add(snap.stable_id)
        printers.append(snap)

    raw_modules = raw.get("modules") or []
    _need(isinstance(raw_modules, list), "modules not list")
    _need(len(raw_modules) <= MAX_MODULES, "too many modules")
    modules, seen_m = [], set()
    for rm in raw_modules:
        snap = _sanitize_module(rm)
        if snap.module_id in seen_m:
            raise BackupError(VALIDATION_FAILED, "duplicate module_id")
        seen_m.add(snap.module_id)
        modules.append(snap)

    module_data = _sanitize_module_data(raw.get("module_data"))

    return BackupPayload(schemas.PAYLOAD_SCHEMA_VERSION, man.get("created_by", ""),
                         core, printers, modules, include_secrets=True,
                         extensions={k: v for k, v in (raw.get("extensions") or {}).items()
                                     if isinstance(k, str) and k.startswith(schemas.EXTENSION_NAMESPACE_PREFIX)},
                         module_data=module_data)


def _sanitize_module_data(raw_md):
    """Alpha 2.829: секция module_data. None = ОТСУТСТВУЕТ (старая копия; данные модулей на цели
    не трогаются) — None ≠ пустой список. dict -> структурная проверка; содержимое снапшота
    каждого модуля дополнительно валидирует его provider (module_providers) на этапе плана."""
    if raw_md is None:
        return None
    _need(isinstance(raw_md, dict), "module_data not object")
    sv = raw_md.get("section_schema_version")
    _need(isinstance(sv, int) and sv >= 1, "bad module_data section_schema_version")
    if sv > schemas.MODULE_DATA_SECTION_SCHEMA:
        raise BackupError(BACKUP_FROM_NEWER_VERSION, "module_data section from newer version")
    mods = raw_md.get("modules")
    _need(isinstance(mods, list), "module_data.modules not list")
    _need(len(mods) <= MAX_MODULES, "too many module_data entries")
    from app.config_backup import module_providers as _mp
    seen = set()
    out = []
    for m in mods:
        _need(isinstance(m, dict), "module_data entry not object")
        mid = _clip_str(m.get("module_id"))
        _need(mid != "", "module_data module_id empty")
        if mid in seen:
            raise BackupError(VALIDATION_FAILED, "duplicate module_id in module_data")
        seen.add(mid)
        bsv = m.get("backup_schema_version")
        _need(isinstance(bsv, int) and bsv >= 1, "bad module backup_schema_version")
        dc = m.get("data_class")
        _need(dc in _mp.DATA_CLASSES, "unknown module data_class")
        dd = m.get("domain_data")
        _need(dd is None or isinstance(dd, dict), "module domain_data not object/null")
        st = m.get("settings")
        _need(st is None or isinstance(st, dict), "module settings not object/null")
        out.append({"module_id": mid, "backup_schema_version": bsv, "data_class": dc,
                    "installed_module_version_at_export": _clip_str(m.get("installed_module_version_at_export")),
                    "enabled": bool(m.get("enabled", True)),
                    "settings": dict(st or {}), "domain_data": dd,
                    "attachments_manifest": list(m.get("attachments_manifest") or []),
                    "extensions": {k: v for k, v in (m.get("extensions") or {}).items()
                                   if isinstance(k, str) and k.startswith(schemas.EXTENSION_NAMESPACE_PREFIX)}})
    return {"section_schema_version": schemas.MODULE_DATA_SECTION_SCHEMA, "modules": out}
