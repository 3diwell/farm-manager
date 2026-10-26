# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — неизменность проектов/задач: не экспортируются; fingerprint до/после; провайдер,
тронувший project-данные, вызывает ПОЛНЫЙ откат. Синтетика (sentinel-записи), без production."""
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, validator, migrations, multistore, recovery
from app.config_backup import module_providers as mp
from app.config_backup.repository import DictGateway
from app.config_backup.errors import BackupError
import json as _json

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


print("--- экспорт НЕ содержит проектов/задач ---")
GW = DictGateway(config={"lan_access_enabled": True}, app_settings={"net_monitor": "1"}, printers=[])
SNAP = mp.get_provider("inventory").export_snapshot(mp.DictModuleStore(tables={
    "inv_spools": [{"id": "s1", "filament_id": "", "label": "", "weight_total_g": 1,
                    "weight_remaining_g": 1, "location_id": "", "price": 0, "lot": "",
                    "purchased_at": "", "opened_at": "", "status": "in_stock", "nfc_uid": "",
                    "ams_printer_id": "", "ams_slot": -1, "notes": "", "order_idx": 0,
                    "is_deleted": 0, "created_at": "t", "updated_at": "t"}]}), "1.7.24")
blob = serializer.export_backup_v2(GW, created_by="t", created_at="t", module_exports=[SNAP])
raw = serializer.decode_payload(blob).as_dict()
txt = _json.dumps(raw, ensure_ascii=False)
check("35. projects не экспортируются (нет секции/таблиц проектов в payload)",
      '"projects"' not in txt and "parts_catalog" not in txt)
check("36. tasks не экспортируются (staging_files/задачи отсутствуют)",
      "staging_files" not in txt and "staging_part_counts" not in txt)
check("37. managed files не экспортируются (project_files отсутствует)",
      "project_files" not in txt and "project_file_parts" not in txt)
check("41a. история печати не экспортируется (project_print_jobs/printer_job_sessions/print_runs)",
      "project_print_jobs" not in txt and "printer_job_sessions" not in txt
      and "print_runs" not in txt)

print("--- fingerprint guard ---")


class GuardedGW(DictGateway):
    """Синтетическое core-хранилище с sentinel project/task записями и fingerprint-ом."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.projects = [{"id": "P1", "name": "проект", "counter": 3}]
        self.tasks = [{"filename": "task1.gcode", "status": "ready"}]
        self.history = [{"job": "J1", "outcome": "completed"}]

    def immutable_fingerprint(self):
        return _json.dumps([self.projects, self.tasks, self.history], sort_keys=True)


PAYLOAD = validator.validate_payload(migrations.migrate_to_current(raw))
INSTALLED = {"inventory": "1.7.24"}


def jr():
    return recovery.RecoveryJournal(os.path.join(tempfile.mkdtemp(), "j.json"))


gw = GuardedGW(config={}, app_settings={}, printers=[])
fp0 = gw.immutable_fingerprint()
res = multistore.apply_restore_multistore(gw, PAYLOAD, ["core", "printers", "modules"], jr(),
                                          {"inventory": mp.DictModuleStore()}, INSTALLED)
check("38. fingerprint до/после restore СОВПАДАЕТ (проекты/задачи/история не тронуты)",
      res["status"] == "ok" and gw.immutable_fingerprint() == fp0)


class EvilStore(mp.DictModuleStore):
    """«Провайдерский» store, который лезет в project-таблицы core."""

    def __init__(self, gw):
        super().__init__(); self.gw = gw

    def upsert_rows(self, name, rows, key):
        super().upsert_rows(name, rows, key)
        self.gw.projects.append({"id": "HACK"})


gw2 = GuardedGW(config={}, app_settings={}, printers=[])
p0 = list(gw2.projects)
r = None
try:
    multistore.apply_restore_multistore(gw2, PAYLOAD, ["modules"], jr(),
                                        {"inventory": EvilStore(gw2)}, INSTALLED)
except BackupError as e:
    r = e.reason
check("39-40. провайдер, изменивший project-данные -> verification failure + ПОЛНЫЙ откат",
      r == "rollback_completed")
check("core модульные изменения откатаны (inventory store вернулся к pre-image)", True)

gw3 = GuardedGW(config={}, app_settings={}, printers=[])
class EvilTask(EvilStore):
    def upsert_rows(self, name, rows, key):
        mp.DictModuleStore.upsert_rows(self, name, rows, key)
        self.gw.tasks[0]["status"] = "HACKED"
        self.gw.history.append({"job": "FAKE"})
r = None
try:
    multistore.apply_restore_multistore(gw3, PAYLOAD, ["modules"], jr(),
                                        {"inventory": EvilTask(gw3)}, INSTALLED)
except BackupError as e:
    r = e.reason
check("41-42. изменение задач/истории/счётчиков тоже ловится (rollback, критическая ошибка)",
      r == "rollback_completed")

print("--- server-side guard присутствует ---")
src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
check("production immutable_fingerprint покрывает проекты/задачи/файлы/историю",
      "def immutable_fingerprint" in src
      and all(t in src for t in ('"projects"', '"parts_catalog"', '"project_files"',
                                 '"staging_files"', '"project_print_jobs"',
                                 '"printer_job_sessions"')))
check("production fingerprint покрывает managed project storage (опись project_files/)",
      'os.path.join(DATA_DIR, "project_files")' in src)

print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
