# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — логические DTO резервной копии (НЕ ORM-строки, НЕ pickle, НЕ SQL-дамп).

Serializer работает ТОЛЬКО с этими DTO; физические имена таблиц/файлов известны лишь
repository-адаптеру. Каждая секция несёт свою schema_version и namespaced extensions
(неизвестные optional-поля сохраняются, известные — валидируются).
"""
from app.config_backup import schemas


def _ext(d):
    """Только namespaced ('x-...') расширения; прочее отбрасывается (не исполняется)."""
    out = {}
    for k, v in (d or {}).items():
        if isinstance(k, str) and k.startswith(schemas.EXTENSION_NAMESPACE_PREFIX):
            out[k] = v
    return out


class CoreSettingsSnapshot(object):
    def __init__(self, schema_version, values=None, machine_bound=None, extensions=None):
        self.schema_version = int(schema_version)
        self.values = dict(values or {})              # portable core settings
        self.machine_bound = dict(machine_bound or {})  # значения machine-bound (применяются с подтверждением)
        self.extensions = _ext(extensions)

    def as_dict(self):
        return {"schema_version": self.schema_version, "values": self.values,
                "machine_bound": self.machine_bound, "extensions": self.extensions}

    @staticmethod
    def from_dict(d):
        d = d or {}
        return CoreSettingsSnapshot(d.get("schema_version", schemas.CORE_SETTINGS_SCHEMA),
                                    d.get("values"), d.get("machine_bound"), d.get("extensions"))


class PrinterSnapshot(object):
    def __init__(self, stable_id, adapter, adapter_schema_version, display_name, model,
                 enabled, connection=None, options=None, credentials=None, extensions=None):
        self.stable_id = str(stable_id)
        self.adapter = str(adapter)
        self.adapter_schema_version = int(adapter_schema_version)
        self.display_name = str(display_name or "")
        self.model = str(model or "")
        self.enabled = bool(enabled)
        self.connection = dict(connection or {})       # ip/port/gen/serial (НЕ секрет доступа)
        self.options = dict(options or {})             # adapter-specific опции + order_idx
        self.credentials = dict(credentials or {})     # СЕКРЕТ (token/checkcode) — только внутри шифра
        self.extensions = _ext(extensions)

    def as_dict(self):
        return {"stable_id": self.stable_id, "adapter": self.adapter,
                "adapter_schema_version": self.adapter_schema_version,
                "display_name": self.display_name, "model": self.model, "enabled": self.enabled,
                "connection": self.connection, "options": self.options,
                "credentials": self.credentials, "extensions": self.extensions}

    @staticmethod
    def from_dict(d):
        d = d or {}
        return PrinterSnapshot(d.get("stable_id"), d.get("adapter"),
                               d.get("adapter_schema_version", 1), d.get("display_name"),
                               d.get("model"), d.get("enabled", True), d.get("connection"),
                               d.get("options"), d.get("credentials"), d.get("extensions"))


class ModuleSettingsSnapshot(object):
    def __init__(self, module_id, schema_version, enabled, values=None, extensions=None):
        self.module_id = str(module_id)
        self.schema_version = int(schema_version)
        self.enabled = bool(enabled)
        self.values = dict(values or {})
        self.extensions = _ext(extensions)

    def as_dict(self):
        return {"module_id": self.module_id, "schema_version": self.schema_version,
                "enabled": self.enabled, "values": self.values, "extensions": self.extensions}

    @staticmethod
    def from_dict(d):
        d = d or {}
        return ModuleSettingsSnapshot(d.get("module_id"), d.get("schema_version", schemas.MODULE_SETTINGS_SCHEMA),
                                      d.get("enabled", True), d.get("values"), d.get("extensions"))


class BackupPayload(object):
    """Корневой логический payload (внутри payload.enc / payload.bin).

    module_data (Alpha 2.829, payload schema v2): None = секция ОТСУТСТВУЕТ (старая копия
    v1 — данные модулей на цели НЕ трогаются); dict = {"section_schema_version": int,
    "modules": [snapshot провайдера, ...]} — см. module_providers. None ≠ пустой список!
    """

    def __init__(self, payload_schema_version, created_by, core, printers, modules,
                 include_secrets=True, extensions=None, module_data=None):
        self.payload_schema_version = int(payload_schema_version)
        self.created_by = str(created_by or "")
        self.include_secrets = bool(include_secrets)
        self.core = core                               # CoreSettingsSnapshot
        self.printers = list(printers or [])           # [PrinterSnapshot]
        self.modules = list(modules or [])             # [ModuleSettingsSnapshot] (legacy-секция v1)
        self.module_data = module_data                 # None (absent) | dict (см. докстринг)
        self.extensions = _ext(extensions)

    def as_dict(self):
        return {
            "manifest": {"payload_schema_version": self.payload_schema_version,
                         "created_by": self.created_by, "include_secrets": self.include_secrets,
                         "sections": ["core", "printers", "modules"]},
            "core": self.core.as_dict(),
            "printers": [p.as_dict() for p in self.printers],
            "modules": [m.as_dict() for m in self.modules],
            "module_data": self.module_data,           # None сохраняется как null (absent-маркер)
            "extensions": self.extensions,
        }

    @staticmethod
    def from_dict(d):
        d = d or {}
        man = d.get("manifest") or {}
        return BackupPayload(
            man.get("payload_schema_version", schemas.PAYLOAD_SCHEMA_VERSION),
            man.get("created_by"),
            CoreSettingsSnapshot.from_dict(d.get("core")),
            [PrinterSnapshot.from_dict(x) for x in (d.get("printers") or [])],
            [ModuleSettingsSnapshot.from_dict(x) for x in (d.get("modules") or [])],
            bool(man.get("include_secrets", True)),
            d.get("extensions"),
            d.get("module_data"),                      # отсутствие ключа == None == absent
        )
