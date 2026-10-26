# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — журнал восстановления (crash-safe машина состояний) + восстановление на старте.

Живёт в DATA_DIR — НИКОГДА не покидает машину (тот же уровень доверия, что рабочая БД, где
токены принтеров и так лежат в открытом виде). Поэтому pre-image (для отката) хранить здесь
допустимо; но после COMPLETE pre-image ЗАТИРАЕТСЯ (секреты не задерживаются на диске).

Состояния: prepared -> applying -> committed_pending_verify -> complete
           (в любой точке при сбое) -> rollback_required -> complete
Запись атомарна (temp + fsync + os.replace): половинчатого журнала не бывает.
"""
import json
import os

JOURNAL_VERSION = 1

STATE_PREPARED = "prepared"
STATE_APPLYING = "applying"
STATE_COMMITTED_PENDING_VERIFY = "committed_pending_verify"
STATE_ROLLBACK_REQUIRED = "rollback_required"
STATE_COMPLETE = "complete"

_PENDING_STATES = (STATE_PREPARED, STATE_APPLYING,
                   STATE_COMMITTED_PENDING_VERIFY, STATE_ROLLBACK_REQUIRED)


def _default_atomic_write_bytes(path, data):
    """temp в той же папке + fsync + os.replace. Исходный файл цел при любой ошибке."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    tmp = os.path.join(d, ".%s.tmp" % os.path.basename(path))
    f = open(tmp, "wb")
    try:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    finally:
        f.close()
    os.replace(tmp, path)


class RecoveryJournal(object):
    def __init__(self, path, atomic_write_bytes=None):
        self.path = path
        self._aw = atomic_write_bytes or _default_atomic_write_bytes

    def _write(self, obj):
        self._aw(self.path, json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def read(self):
        try:
            if not os.path.isfile(self.path):
                return None
            with open(self.path, "rb") as f:
                return json.loads(f.read().decode("utf-8"))
        except Exception:
            return None

    def set_prepared(self, pre_image, meta=None):
        self._write({"journal_version": JOURNAL_VERSION, "state": STATE_PREPARED,
                     "pre_image": pre_image, "meta": dict(meta or {})})

    def _transition(self, new_state, extra=None):
        cur = self.read() or {}
        cur["state"] = new_state
        cur["journal_version"] = JOURNAL_VERSION
        if extra:
            cur.update(extra)
        self._write(cur)

    def set_applying(self):
        self._transition(STATE_APPLYING)

    def set_committed_pending_verify(self):
        self._transition(STATE_COMMITTED_PENDING_VERIFY)

    def set_state(self, state, extra=None):
        """Alpha 2.829: durable-переход в произвольное состояние multi-store машины
        (staging_modules / applying_module:<id> / verifying_module:<id> / rolling_back_*)."""
        self._transition(str(state), extra)

    def set_rollback_required(self, reason=""):
        self._transition(STATE_ROLLBACK_REQUIRED, {"reason": str(reason or "")})

    def complete(self):
        """Финал: state=complete + ЗАТИРАНИЕ pre-image (секреты не остаются на диске)."""
        self._write({"journal_version": JOURNAL_VERSION, "state": STATE_COMPLETE,
                     "pre_image": None, "meta": (self.read() or {}).get("meta", {})})

    def is_pending(self):
        # Alpha 2.829: pending = ЛЮБОЕ незавершённое состояние (включая multi-store
        # applying_module:<id> и т.п.), а не только исторический whitelist 2.827.
        j = self.read()
        st = (j or {}).get("state")
        return bool(j and isinstance(st, str) and st and st != STATE_COMPLETE)


def recover_on_startup(journal, gateway, verify_fn=None):
    """Незавершённый restore после падения: докатить или откатить к pre-image.
    verify_fn(gateway)->bool применяется только в состоянии committed_pending_verify."""
    j = journal.read()
    if not j or j.get("state") not in _PENDING_STATES:
        return {"recovered": False}
    state = j.get("state")
    pre = j.get("pre_image")
    if pre is None:
        # pre-image недоступен (не должно случаться до complete) — безопаснее не трогать данные
        journal.complete()
        return {"recovered": True, "action": "no_pre_image", "state": state}
    if state == STATE_COMMITTED_PENDING_VERIFY and verify_fn is not None:
        try:
            ok = bool(verify_fn(gateway))
        except Exception:
            ok = False
        if ok:
            journal.complete()
            return {"recovered": True, "action": "verified", "state": state}
    # prepared / applying / rollback_required / verify-fail -> откат
    gateway.restore_full(pre)
    journal.complete()
    return {"recovered": True, "action": "rolled_back", "state": state}
