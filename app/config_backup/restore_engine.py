# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — атомарное применение восстановления с проверкой и откатом.

Поток: READ→DECRYPT→VALIDATE→MIGRATE выполнены выше (serializer/validator/migrations).
Здесь: PLAN→PRE-SNAPSHOT(journal)→APPLY(atomic mutation)→VERIFY→COMMIT | ROLLBACK.
Любой сбой на APPLY/VERIFY -> компенсирующий откат к pre-image; данные не остаются половинчатыми.
"""
from app.config_backup import serializer
from app.config_backup import settings_registry as reg
from app.config_backup.errors import BackupError, ROLLBACK_COMPLETED, ROLLBACK_FAILED


def _verify(gateway, mutation):
    """Перечитать хранилище и убедиться, что мутация применилась (целевые значения на месте)."""
    cfg = gateway.get_config_json() or {}
    for k, v in mutation.config_set.items():
        if cfg.get(k) != v:
            return False
    for k, v in mutation.app_set.items():
        if gateway.get_app_setting(k) != v:
            return False
    if mutation.printers_upsert:
        by_id = {str(p.get("id")): p for p in (gateway.list_printers() or [])}
        for row in mutation.printers_upsert:
            cur = by_id.get(str(row.get("id")))
            if cur is None:
                return False
            for col in ("name", "type", "ip", "token", "model", "serial", "gen"):
                if str(cur.get(col) or "") != str(row.get(col) or ""):
                    return False
    return True


def apply_restore(gateway, payload, selected_sections, journal,
                  apply_machine_bound=False):
    """Атомарно применить payload к хранилищу через journal. -> dict-результат.
    payload ДОЛЖЕН быть уже провалидирован (validator.validate_payload)."""
    mutation = serializer.payload_to_mutation(payload, selected_sections,
                                              apply_machine_bound=apply_machine_bound)
    if mutation.is_empty():
        return {"status": "noop", "changed": False}

    # PRE-SNAPSHOT: полный pre-image в журнал (для отката при падении процесса).
    pre = gateway.full_snapshot()
    journal.set_prepared(pre, meta={"sections": sorted(set(selected_sections or ()))})

    journal.set_applying()
    try:
        gateway.apply_mutation(mutation)
    except Exception as e:
        # APPLY упал: компенсирующий откат немедленно.
        try:
            gateway.restore_full(pre)
        except Exception:
            journal.set_rollback_required("apply+rollback failed")
            raise BackupError(ROLLBACK_FAILED, "apply failed AND rollback failed")
        journal.complete()
        raise BackupError(ROLLBACK_COMPLETED, "apply failed, rolled back: %s" % type(e).__name__)

    journal.set_committed_pending_verify()
    ok = False
    try:
        ok = _verify(gateway, mutation)
    except Exception:
        ok = False
    if not ok:
        try:
            gateway.restore_full(pre)
        except Exception:
            journal.set_rollback_required("verify failed; rollback failed")
            raise BackupError(ROLLBACK_FAILED, "verify failed AND rollback failed")
        journal.complete()
        raise BackupError(ROLLBACK_COMPLETED, "verify failed, rolled back")

    journal.complete()
    restart = _restart_required(mutation)
    return {"status": "ok", "changed": True,
            "config_changed": sorted(mutation.config_set.keys()),
            "app_changed": sorted(mutation.app_set.keys()),
            "printers_written": [r.get("id") for r in mutation.printers_upsert],
            "restart_required": restart}


def _restart_required(mutation):
    for k in list(mutation.config_set.keys()) + list(mutation.app_set.keys()):
        e = reg.get(k)
        if e and e.restart_required:
            return True
    return False


def make_verify_fn(payload, selected_sections, apply_machine_bound=False):
    """Замыкание verify для recover_on_startup (сверяет ожидаемую мутацию)."""
    mutation = serializer.payload_to_mutation(payload, selected_sections,
                                              apply_machine_bound=apply_machine_bound)

    def _fn(gateway):
        return _verify(gateway, mutation)

    return _fn
