# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — секция module_data: payload v2, absent-семантика старых копий, missing module,
fail-closed экспорт (server.py как текст), sentinel MODULE_BACKUP_AND_RESTART_SENTINEL_2_829."""
import copy
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, validator, migrations, multistore, recovery, schemas
from app.config_backup import module_providers as mp
from app.config_backup import container_v2
from app.config_backup.repository import DictGateway
from app.config_backup.errors import BackupError

SENTINEL = "MODULE_BACKUP_AND_RESTART_SENTINEL_2_829"
_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


def _reason(fn):
    try:
        fn(); return None
    except BackupError as e:
        return e.reason


GW = DictGateway(config={"lan_access_enabled": True, "modules_disabled": []},
                 app_settings={"net_monitor": "1"},
                 printers=[{"id": "p1", "name": "X1", "type": "bambu", "ip": "1.2.3.4", "port": 8883,
                            "token": "SECTOK", "last_parts": "{}", "order_idx": 0, "gen": "auto",
                            "serial": "S", "model": "X1C"}])
INV_SNAP = mp.get_provider("inventory").export_snapshot(mp.DictModuleStore(tables={
    "inv_spools": [{"id": "sp1", "filament_id": "", "label": "L", "weight_total_g": 1,
                    "weight_remaining_g": 1, "location_id": "", "price": 0, "lot": "",
                    "purchased_at": "", "opened_at": "", "status": "in_stock", "nfc_uid": "",
                    "ams_printer_id": "", "ams_slot": -1, "notes": "SECRETNOTE", "order_idx": 0,
                    "is_deleted": 0, "created_at": "t", "updated_at": "t"}]},
    settings={"currency": "RUB"}), installed_version="1.7.24")
Q_SNAP = mp.get_provider("quality").export_snapshot(mp.DictModuleStore(), installed_version="0.2.2")

print("--- payload v2 + module_data ---")
blob = serializer.export_backup_v2(GW, created_by="t", created_at="t",
                                   module_exports=[INV_SNAP, Q_SNAP])
payload = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob).as_dict()))
check("1. новый экспорт содержит module_data (payload v2)",
      payload.module_data is not None and payload.payload_schema_version == schemas.PAYLOAD_SCHEMA_VERSION)
check("2. секция несёт независимые версии (section + module backup_schema_version)",
      payload.module_data["section_schema_version"] == schemas.MODULE_DATA_SECTION_SCHEMA
      and all(isinstance(m["backup_schema_version"], int) for m in payload.module_data["modules"]))
check("3. APP_VERSION не используется как schema (все версии int)",
      not any(isinstance(m.get("backup_schema_version"), str) for m in payload.module_data["modules"]))
hb, hdr = container_v2.peek_header(blob)
check("4. header НЕ содержит данных модулей (SECRETNOTE только в payload)",
      b"SECRETNOTE" not in hb and b"SECRETNOTE" in blob)

print("--- absent-семантика старых копий ---")
old = copy.deepcopy(payload.as_dict())
old["manifest"]["payload_schema_version"] = 1
old.pop("module_data", None)
mig = migrations.migrate_to_current(old)
check("5. миграция v1->v2: module_data=None (ОТСУТСТВУЕТ, не пусто)", mig["module_data"] is None)
pay_old = validator.validate_payload(mig)
filled = mp.DictModuleStore(tables={"inv_spools": [{"id": "KEEP"}]}, settings={"currency": "USD"})
before = filled.full_snapshot()
jr = recovery.RecoveryJournal(os.path.join(tempfile.mkdtemp(), "j.json"))
multistore.apply_restore_multistore(DictGateway(config={}, app_settings={}, printers=[]),
                                    pay_old, ["core", "printers", "modules"], jr,
                                    {"inventory": filled}, {"inventory": "1.7.24"})
check("6. импорт СТАРОЙ копии НЕ очищает и НЕ заменяет данные модулей",
      filled.full_snapshot() == before)
plan = multistore.build_full_plan(DictGateway(config={}, app_settings={}, printers=[]), pay_old,
                                  ["modules"], {"inventory": filled}, {"inventory": "1.7.24"})
check("7. план старой копии: явный текст об отсутствии module data",
      plan["module_data"]["absent"]
      and any("отсутствуют" in (w.get("text") or "") for w in plan["module_data"]["warnings"]))
check("8. миграция НЕ создаёт «replace with empty» (в migrations нет пустого списка)",
      "module_data\"] = None" in open(os.path.join(ROOT, "app", "config_backup", "migrations",
                                                   "__init__.py"), encoding="utf-8").read().replace("'", '"'))

print("--- missing module ---")
tgt = DictGateway(config={}, app_settings={}, printers=[])
plan2 = multistore.build_full_plan(tgt, payload, ["modules"], {}, {})
check("9. модуль не установлен -> warning с именем + blocked",
      plan2["module_data"]["blocked"]
      and any(w.get("code") == "missing_module" and w.get("module_id") == "inventory"
              for w in plan2["module_data"]["warnings"]))
check("10. полный restore при missing module -> manual_resolution_required",
      _reason(lambda: multistore.apply_restore_multistore(
          tgt, payload, ["modules"], recovery.RecoveryJournal(os.path.join(tempfile.mkdtemp(), "j2.json")),
          {}, {})) == "manual_resolution_required")
jr3 = recovery.RecoveryJournal(os.path.join(tempfile.mkdtemp(), "j3.json"))
res = multistore.apply_restore_multistore(tgt, payload, ["modules"], jr3, {}, {},
                                          exclude_modules=("inventory",))
check("11. пользователь может ЯВНО снять module section -> restore проходит без неё",
      res["status"] in ("ok", "noop") and res.get("modules_applied", []) == [])

print("--- fail-closed экспорт в server.py (текст) + sentinel ---")
src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
check("12. экспорт вызывает require_export_completeness (fail-closed)",
      "require_export_completeness" in src and "_cfgbackup_module_exports" in src)
check("13. отказ экспорта отдаёт точные имена модулей (modules в ответе 409)",
      '"modules": [m for m in names.split(",") if m]' in src)
leaks = []
targets = [os.path.join(ROOT, "server.py")]
for base in ("app/config_backup", "web", "docs", "tools/fixtures/config_backup", "modules"):
    for r, _d, fs in os.walk(os.path.join(ROOT, base)):
        for fn in fs:
            if fn.endswith((".py", ".js", ".html", ".md", ".json", ".3diwell-backup")):
                targets.append(os.path.join(r, fn))
for t in targets:
    try:
        if SENTINEL.encode() in open(t, "rb").read():
            leaks.append(os.path.relpath(t, ROOT))
    except Exception:
        pass
check("14. sentinel НЕ в production/fixtures/modules (только этот тест): %s" % (leaks or "нигде"),
      not leaks)
check("15. активная печать блокирует restore (guard в маршруте, точный вызов)",
      "if _cfgbackup_any_active_print():" in src and '"reason": "active_prints"' in src)

print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
