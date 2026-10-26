# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.830 — обязательная само-проверка экспорта (ПОСТОЯННЫЙ контракт).

ИНВАРИАНТ: export_success => same-version inspect/validate/plan_success.

Farm Manager НЕ ДОЛЖЕН выдавать файл резервной копии, который сам же (той же версией) не может
прочитать, провалидировать и подготовить план восстановления. До появления файла экспорт
выполняет ПОЛНЫЙ обратный проход по реальным байтам копии тем же кодом, что и restore:
  1) decode payload из готовых байтов (round-trip, а не отдельная модель в памяти);
  2) migrate -> validate payload той же production-схемой;
  3) build_full_plan против ТЕКУЩЕГО состояния (read-only);
  4) план не должен требовать manual_resolution для собственного состояния.
Любой сбой -> BackupError (файл не создаётся; audit result=validation_failed; НЕ result=ok).

Этот модуль НИЧЕГО не мутирует и не обращается к принтерам/сети. Значения наружу не отдаёт.
"""
from app.config_backup import serializer, migrations, validator, multistore
from app.config_backup.errors import BackupError, VALIDATION_FAILED, MANUAL_RESOLUTION_REQUIRED

_SECTIONS = ["core", "printers", "modules"]


def verify_exported_blob(blob, gateway, module_stores, installed_modules, passphrase=None):
    """Полный обратный проход по фактическим байтам копии. Бросает BackupError при любом сбое.
    Возвращает безопасную сводку (счётчики секций/предупреждений) при успехе — без значений."""
    # 1-2. Round-trip decode + migrate + validate теми же production-функциями, что и restore.
    try:
        raw = serializer.decode_payload(blob, passphrase).as_dict()
        migrated = migrations.migrate_to_current(raw)
        payload = validator.validate_payload(migrated)
    except BackupError as e:
        if e.stage is None:
            e.stage = "self_validation"
        raise
    except Exception as e:
        raise BackupError(VALIDATION_FAILED, "self-check decode/validate: %s" % type(e).__name__,
                          stage="self_validation")
    # 3. Dry-план против ТЕКУЩЕГО состояния (read-only) — тот же путь, что использует restore.
    try:
        known = {str(p.get("id")) for p in gateway.list_printers()}
        plan = multistore.build_full_plan(
            gateway, payload, _SECTIONS, module_stores=module_stores,
            installed_modules=installed_modules, known_printer_ids=known)
    except BackupError as e:
        if e.stage is None:
            e.stage = "self_validation"
        raise
    except Exception as e:
        raise BackupError(VALIDATION_FAILED, "self-check plan: %s" % type(e).__name__,
                          stage="self_validation", section="modules")
    # 4. Собственное состояние не должно требовать ручного разрешения (все модули установлены).
    md = plan.get("module_data") or {}
    if md.get("blocked"):
        raise BackupError(MANUAL_RESOLUTION_REQUIRED, "self-check plan blocked",
                          stage="self_validation", section="modules")
    warn_codes = sorted({str(w.get("code")) for w in (plan.get("warnings") or []) if w.get("code")})
    mod_ids = sorted({str(m.get("module_id")) for m in (md.get("modules") or []) if m.get("module_id")})
    return {"ok": True, "sections": list(_SECTIONS), "modules": mod_ids, "warning_codes": warn_codes}
