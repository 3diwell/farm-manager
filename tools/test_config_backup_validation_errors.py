# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.830 — безопасные ошибки проверки + контракт маршрутов.

BackupError НИКОГДА не уходит как unhandled 500; наружу — только структурированный безопасный
ответ (reason/stage/section/module_id/field_path), без значений/секретов/traceback/путей/SQL.
File-select ведёт к inspect/plan, НЕ apply; inspect/plan НЕ мутируют; retry = только проверка.
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import multistore, validator, migrations, serializer
from app.config_backup import module_providers as mp
from app.config_backup.repository import DictGateway
from app.config_backup.errors import (BackupError, safe_structured, http_status_for,
                                       safe_reason, VALIDATION_FAILED, MANUAL_RESOLUTION_REQUIRED,
                                       ACTIVE_PRINTS, RESTORE_LOCKED, ROLLBACK_FAILED)

# ТОЛЬКО для теста; не должен просочиться в прод/фикстуры/данные.
SENTINEL = "CONFIG_BACKUP_SELF_RESTORE_SENTINEL_2_830"
_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


print("--- safe_structured / http_status ---")
e = BackupError(VALIDATION_FAILED, "broken ref inv_items.location_id -> inv_locations",
                section="modules", module_id="inventory", field_path="inv_items.location_id")
resp = safe_structured(e, stage="plan")
check("26/27. структурированный ответ: reason+stage+section+module_id",
      resp["reason"] == "validation_failed" and resp["stage"] == "plan"
      and resp["section"] == "modules" and resp["module_id"] == "inventory")
txt = json.dumps(resp, ensure_ascii=False)
check("28. НЕТ значений/секретов/traceback/пути/SQL/detail в ответе",
      "broken ref" not in txt and "Traceback" not in txt and "->" not in txt
      and "C:\\\\" not in txt and "SELECT" not in txt)
check("28b. field_path — только schema-путь (таблица.колонка), допустим без значений",
      resp.get("field_path") == "inv_items.location_id")
check("http 400 для validation_failed", http_status_for(VALIDATION_FAILED) == 400)
check("http 409 для manual_resolution_required", http_status_for(MANUAL_RESOLUTION_REQUIRED) == 409)
check("http 409 для active_prints / restore_locked",
      http_status_for(ACTIVE_PRINTS) == 409 and http_status_for(RESTORE_LOCKED) == 409)
check("http 500 только для rollback_failed", http_status_for(ROLLBACK_FAILED) == 500)
check("незнакомый reason -> backup_invalid (не течёт)", safe_reason("weird internal detail") == "backup_invalid")

print("--- route: BackupError НЕ unhandled 500; plan обёрнут ---")
src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
restore_fn = src[src.index("async def cfgbackup_restore"):src.index("def _bambu_ams_mapping")]
# build_full_plan должен стоять внутри try, а следом except _CfgBackupError
i_plan = restore_fn.find("build_full_plan")
i_try = restore_fn.rfind("try:", 0, i_plan)
i_exc = restore_fn.find("except _CfgBackupError", i_plan)
check("21/26. build_full_plan обёрнут в try (не уйдёт как unhandled 500)",
      0 < i_try < i_plan < i_exc)
check("26b. plan-ошибка отдаёт safe_structured", "_cfgbackup_safe_structured(e, stage=\"plan\")" in restore_fn)
check("apply-ошибка отдаёт safe_structured", "_cfgbackup_safe_structured(e, stage=\"apply\")" in restore_fn)
check("22/23. mode=plan возвращается ДО apply (do_apply-гейт)",
      restore_fn.find("if not do_apply:") < restore_fn.find("if _cfgbackup_any_active_print():"))
check("24. apply требует mode=apply (do_apply) + отдельный active-prints/lock гейт",
      'do_apply = str((body or {}).get("mode") or "plan") == "apply"' in restore_fn
      and "_CFGBACKUP_RESTORE_LOCK.acquire(blocking=False)" in restore_fn)

print("--- inspect/plan НЕ мутируют ---")
class TrackStore(mp.DictModuleStore):
    def __init__(self, *a, **k):
        super().__init__(*a, **k); self.writes = 0
    def upsert_rows(self, *a, **k): self.writes += 1; return super().upsert_rows(*a, **k)
    def write_settings(self, *a, **k): self.writes += 1; return super().write_settings(*a, **k)

gw = DictGateway(config={"lan_access_enabled": True}, app_settings={}, printers=[])
snap = mp.get_provider("inventory").export_snapshot(mp.DictModuleStore(tables={
    "inv_spools": [{"id": "s1", "filament_id": "", "label": "", "weight_total_g": 1,
                    "weight_remaining_g": 1, "location_id": "gone", "price": 0, "lot": "",
                    "purchased_at": "", "opened_at": "", "status": "in_stock", "nfc_uid": "",
                    "ams_printer_id": "", "ams_slot": -1, "notes": "", "order_idx": 0,
                    "is_deleted": 0, "created_at": "t", "updated_at": "t"}]}), "1.7.24")
blob = serializer.export_backup_v2(gw, created_by="t", created_at="t", module_exports=[snap])
payload = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob, None).as_dict()))
ts = TrackStore()
plan = multistore.build_full_plan(gw, payload, ["core", "printers", "modules"],
                                  module_stores={"inventory": ts}, installed_modules={"inventory": "1.7.24"},
                                  known_printer_ids=set())
check("22/23. build_full_plan НИЧЕГО не пишет в store (0 мутаций)", ts.writes == 0)
check("план на висячей ссылке даёт dangling_internal_ref (не падает)",
      any(w.get("code") == "dangling_internal_ref" for w in plan["module_data"]["warnings"]))

# Реальная ошибка модуля (дубликат ключа) через build_full_plan обязана нести section+module_id.
dup_dict = serializer.decode_payload(blob, None).as_dict()
dup_inv = [m for m in dup_dict["module_data"]["modules"] if m["module_id"] == "inventory"][0]
dup_inv["domain_data"]["tables"]["inv_spools"].append(
    dict(dup_inv["domain_data"]["tables"]["inv_spools"][0]))
dup_payload = validator.validate_payload(migrations.migrate_to_current(dup_dict))
ee = None
try:
    multistore.build_full_plan(gw, dup_payload, ["core", "printers", "modules"],
                               module_stores={"inventory": mp.DictModuleStore()},
                               installed_modules={"inventory": "1.7.24"}, known_printer_ids=set())
except BackupError as _e:
    ee = _e
check("26c. ошибка модуля из плана несёт section='modules' и module_id",
      ee is not None and ee.section == "modules" and ee.module_id == "inventory")
check("26d. structured-ответ этой ошибки безопасен (reason+section+module_id, без detail)",
      safe_structured(ee, stage="plan").get("module_id") == "inventory"
      and "detail" not in safe_structured(ee, stage="plan"))

print("--- inspect route не расшифровывает/не меняет данные ---")
insp_fn = src[src.index("async def cfgbackup_inspect"):src.index("async def cfgbackup_restore")]
check("inspect: только метаданные, без decode_payload/apply",
      "inspect_container" in insp_fn and "apply_restore" not in insp_fn and "decode_payload" not in insp_fn)

print("--- frontend: retry=проверка, file-select=inspect/plan, RU/EN, единый текст убран ---")
js = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
check("29/46. retryRestartConnection и «Повторить проверку» -> cbInspect (не restore apply)",
      "@click=\"cbInspect()\"" in open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read())
check("21. cbInspect шлёт mode:'plan' (не apply)", "mode: 'plan'" in js and "cbInspect" in js)
check("cbApply — единственный путь mode:'apply'", js.count("mode: 'apply'") == 1)
check("43/44. cbErrorText даёт RU и EN сообщение модуля",
      "не прошла проверку данных модуля" in js and "failed data validation for module" in js)
check("45. «Не удалось выполнить операцию» больше НЕ единственный текст (есть cbErrorText+section)",
      "cbErrorText" in js and "j.section === 'modules'" in js)
check("43b. код ошибки показывается пользователю (module_id + _snapshot_invalid)",
      "_snapshot_invalid" in js)

print("--- SENTINEL не в проде/фикстурах/данных ---")
leaks = []
for base in ("server.py", "app/config_backup", "web", "docs", "modules",
             "tools/fixtures/config_backup"):
    p = os.path.join(ROOT, base)
    files = [p] if os.path.isfile(p) else []
    if os.path.isdir(p):
        for r, _d, fs in os.walk(p):
            for fn in fs:
                if fn.endswith((".py", ".js", ".html", ".md", ".json", ".3diwell-backup", ".txt")):
                    files.append(os.path.join(r, fn))
    for fp in files:
        try:
            if SENTINEL.encode() in open(fp, "rb").read():
                leaks.append(os.path.relpath(fp, ROOT))
        except Exception:
            pass
check("SENTINEL только в этом тесте (нет в проде/фикстурах/модулях): %s" % (leaks or "нигде"), not leaks)

print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
