# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — безопасные reason-коды резервного копирования конфигурации.

Наружу (в API/лог/UI) уходят ТОЛЬКО эти коды — никогда не raw-исключение, не путь, не
секрет, не значение настройки. Неверный пароль и повреждение дают ОДИН и тот же код
(без oracle-деталей: нельзя по ошибке отличить «пароль неверный» от «файл повреждён»).
"""


class BackupError(Exception):
    """Единственный публичный тип ошибки. .reason — безопасный код из REASONS.

    Alpha 2.830: опциональные СТРУКТУРНЫЕ safe-поля (stage/section/module_id/field_path).
    Это ТОЛЬКО коды и schema-пути (имена секций/таблиц/колонок) — НИКОГДА значения,
    секреты, пути ФС или traceback. Используются для понятного UI без раскрытия данных."""

    def __init__(self, reason, detail="", stage=None, section=None, module_id=None, field_path=None):
        self.reason = str(reason)
        self.detail = str(detail)          # ТОЛЬКО для внутреннего лога, наружу не отдаётся
        self.stage = stage                 # safe: этап (parse/migrate/validate/plan/self_validation)
        self.section = section             # safe: core|printers|modules
        self.module_id = module_id         # safe: стабильный id модуля
        self.field_path = field_path       # safe: schema-путь (таблица.колонка), без значения
        super().__init__(self.reason)


# ── Безопасные reason-коды (единственный словарь) ─────────────────────────────
BACKUP_INVALID = "backup_invalid"
BACKUP_CORRUPTED_OR_WRONG_PASSWORD = "backup_corrupted_or_wrong_password"   # единый — без oracle
UNSUPPORTED_FORMAT = "unsupported_format"
BACKUP_FROM_NEWER_VERSION = "backup_from_newer_version"
MIGRATION_MISSING = "migration_missing"
VALIDATION_FAILED = "validation_failed"
MANUAL_RESOLUTION_REQUIRED = "manual_resolution_required"
ACTIVE_PRINTS = "active_prints"
RESTORE_LOCKED = "restore_locked"
DISK_FULL = "disk_full"
DATABASE_BUSY = "database_busy"
ROLLBACK_COMPLETED = "rollback_completed"
ROLLBACK_FAILED = "rollback_failed"
RESTART_REQUIRED = "restart_required"
LOCAL_ONLY = "local_only"
PERMISSION_DENIED = "permission_denied"
WEAK_ENCRYPTION_PARAMS = "weak_encryption_params"
EXCESSIVE_ENCRYPTION_PARAMS = "excessive_encryption_params"

SAFE_REASONS = frozenset((
    BACKUP_INVALID, BACKUP_CORRUPTED_OR_WRONG_PASSWORD, UNSUPPORTED_FORMAT,
    BACKUP_FROM_NEWER_VERSION, MIGRATION_MISSING, VALIDATION_FAILED,
    MANUAL_RESOLUTION_REQUIRED, ACTIVE_PRINTS, RESTORE_LOCKED, DISK_FULL,
    DATABASE_BUSY, ROLLBACK_COMPLETED, ROLLBACK_FAILED, RESTART_REQUIRED,
    LOCAL_ONLY, PERMISSION_DENIED, WEAK_ENCRYPTION_PARAMS, EXCESSIVE_ENCRYPTION_PARAMS,
))


def safe_reason(reason):
    """Свести любое к безопасному коду (незнакомое -> backup_invalid)."""
    r = str(reason or "")
    return r if r in SAFE_REASONS else BACKUP_INVALID


# Alpha 2.830: HTTP-коды по контракту (409 — состояние требует действия пользователя;
# 500 — только серверный откат/сбой; остальное 400).
_HTTP_409 = frozenset((MANUAL_RESOLUTION_REQUIRED, RESTORE_LOCKED, ACTIVE_PRINTS))
_HTTP_500 = frozenset((ROLLBACK_FAILED,))


def http_status_for(reason):
    r = safe_reason(reason)
    if r in _HTTP_409:
        return 409
    if r in _HTTP_500:
        return 500
    return 400


def safe_structured(err, stage=None):
    """Безопасный структурированный ответ об ошибке: ТОЛЬКО reason-код + schema-идентификаторы
    (stage/section/module_id/field_path). НИКОГДА значения, секреты, пути ФС, traceback, payload.
    Принимает BackupError или строку-reason."""
    reason = getattr(err, "reason", err)
    out = {"status": "error", "reason": safe_reason(reason)}
    st = stage or getattr(err, "stage", None)
    if st:
        out["stage"] = str(st)
    for k in ("section", "module_id", "field_path"):
        v = getattr(err, k, None)
        if v:
            out[k] = str(v)
    return out
