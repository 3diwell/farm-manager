# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — ДОБАВЛЯЕМЫЕ (append-only) миграции payload между версиями схемы.

ЖЕЛЕЗНОЕ ПРАВИЛО (docs/BACKUP_COMPATIBILITY_CONTRACT.md):
  • миграции ТОЛЬКО дописываются: v1->v2, v2->v3, ...;
  • опубликованную миграцию НЕЛЬЗЯ переписывать или удалять НИКОГДА;
  • каждая миграция — ЧИСТАЯ и ДЕТЕРМИНИРОВАННАЯ функция dict->dict (без времени/сети/случайности);
  • новые ключи получают дефолты; смысл старых ключей не меняется.

Так копия, снятая годы назад, восстанавливается на будущей мажорной версии: цепочка
v1->...->current приводит её к текущей структуре БЕЗ участия старого кода.
"""
from app.config_backup import schemas
from app.config_backup.errors import (BackupError, BACKUP_FROM_NEWER_VERSION,
                                       MIGRATION_MISSING, BACKUP_INVALID)


def _payload_version(raw):
    man = (raw or {}).get("manifest") or {}
    v = man.get("payload_schema_version")
    if not isinstance(v, int) or v < 1:
        raise BackupError(BACKUP_INVALID, "bad payload_schema_version")
    return v


# ─────────────────────────────────────────────────────────────────────────────
# Реестр миграций payload: {from_version: fn(raw_dict)->raw_dict(from_version+1)}.
# ДОБАВЛЯТЬ сюда, НИЧЕГО не удаляя и не переписывая опубликованное.
# ─────────────────────────────────────────────────────────────────────────────

def _m_v1_to_v2(raw):
    """Alpha 2.829: payload v1 (2.827-2.828) -> v2. КРИТИЧЕСКАЯ СЕМАНТИКА: в v1 секции
    module_data НЕ БЫЛО, поэтому она помечается ОТСУТСТВУЮЩЕЙ (None), а НЕ пустой.
    Импорт старой копии обязан НЕ трогать данные модулей на цели («replace with empty»
    ЗАПРЕЩЁН). Чистая, детерминированная, append-only — не переписывать никогда."""
    raw = dict(raw)
    raw["module_data"] = None                       # absent, НЕ пустой список
    man = dict(raw.get("manifest") or {})
    man["payload_schema_version"] = 2
    raw["manifest"] = man
    return raw


PAYLOAD_MIGRATIONS = {1: _m_v1_to_v2}


def migrate_to_current(raw):
    """Привести payload-dict к PAYLOAD_SCHEMA_VERSION. Копию из БУДУЩЕЙ версии — отклонить
    (её структуру этот код знать не может). Пропуск миграции в цепочке -> явная ошибка."""
    if not isinstance(raw, dict):
        raise BackupError(BACKUP_INVALID, "payload not object")
    v = _payload_version(raw)
    target = schemas.PAYLOAD_SCHEMA_VERSION
    if v > target:
        raise BackupError(BACKUP_FROM_NEWER_VERSION, "payload from newer app version")
    steps = 0
    while v < target:
        fn = PAYLOAD_MIGRATIONS.get(v)
        if fn is None:
            raise BackupError(MIGRATION_MISSING, "missing migration for payload v%d" % v)
        raw = fn(raw)
        nv = _payload_version(raw)
        if nv != v + 1:
            raise BackupError(MIGRATION_MISSING, "migration v%d did not yield v%d" % (v, v + 1))
        v = nv
        steps += 1
        if steps > 10000:
            raise BackupError(MIGRATION_MISSING, "migration loop guard")
    return raw


def migration_path_len(from_version):
    """Число шагов миграции от from_version до текущей (для тестов совместимости)."""
    v, n = int(from_version), 0
    while v < schemas.PAYLOAD_SCHEMA_VERSION:
        if v not in PAYLOAD_MIGRATIONS:
            raise BackupError(MIGRATION_MISSING, "missing migration for v%d" % v)
        v += 1
        n += 1
    return n
