# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — провайдер Inventory: полный срез склада, связи, привязки, round trip (dict+sqlite)."""
import copy
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import module_providers as mp
from app.config_backup.sqlite_store import SqliteModuleStore
from app.config_backup.errors import BackupError

_n = {"pass": 0, "fail": 0}


def check(label, cond, extra=""):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label + ("" if ok or extra == "" else "  :: %s" % (extra,)))
    _n["pass" if ok else "fail"] += 1
    return ok


INV = mp.get_provider("inventory")


def store():
    return mp.DictModuleStore(tables={
        "inv_vendors": [{"id": "v1", "name": "VendorX", "notes": "", "order_idx": 0, "is_deleted": 0,
                         "created_at": "t", "updated_at": "t"}],
        "inv_filaments": [{"id": "f1", "vendor_id": "v1", "material": "PETG", "color_name": "Red",
                           "color_hex": "#f00", "diameter": 1.75, "density": 1.24, "temp_min": 220,
                           "temp_max": 260, "spool_weight_g": 200, "price_per_kg": 1500, "notes": "",
                           "order_idx": 0, "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
        "inv_locations": [{"id": "L1", "name": "Полка", "parent_id": "", "notes": "", "order_idx": 0,
                           "is_deleted": 0, "created_at": "t"}],
        "inv_items": [{"id": "i1", "name": "Сопло", "category": "parts", "unit": "шт", "qty": 5,
                       "min_qty": 1, "max_qty": 10, "location_id": "L1", "price": 100,
                       "printer_brand": "", "printer_model": "", "notes": "", "order_idx": 0,
                       "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
        "inv_spools": [{"id": "s1", "filament_id": "f1", "label": "S-1", "weight_total_g": 1200,
                        "weight_remaining_g": 800, "location_id": "L1", "price": 1800, "lot": "LOT1",
                        "purchased_at": "2026-01-01", "opened_at": "", "status": "in_stock",
                        "nfc_uid": "", "ams_printer_id": "p-1", "ams_slot": 0, "notes": "",
                        "order_idx": 0, "is_deleted": 0, "created_at": "t", "updated_at": "t"}],
        "inv_ledger": [{"id": "lg1", "ts": "t", "kind": "adjust", "ref_type": "spool", "ref_id": "s1",
                        "qty": -50, "reason": "печать", "job_id": "", "username": "u", "note": ""}],
        "inv_pending_prints": [{"id": "RT"}],
    }, settings={"currency": "RUB"})


MOBILE = ("inv_mobile_codes", "inv_mobile_nfc", "inv_mobile_label_batches", "inv_mobile_labels")

print("--- export scope ---")
snap = INV.export_snapshot(store(), installed_version="1.7.24")
t = snap["domain_data"]["tables"]
check("15. все доказанные inventory-таблицы экспортируются (v2: + мобильная приёмка)",
      set(t) == {"inv_vendors", "inv_filaments", "inv_locations", "inv_items", "inv_spools", "inv_ledger"}
      | set(MOBILE))
check("16. stable IDs сохранены", t["inv_spools"][0]["id"] == "s1" and t["inv_filaments"][0]["id"] == "f1")
check("17. связи сохранены (spool->filament->vendor, spool->location)",
      t["inv_spools"][0]["filament_id"] == "f1" and t["inv_filaments"][0]["vendor_id"] == "v1"
      and t["inv_spools"][0]["location_id"] == "L1")
check("18. вес катушки сохранён (total+remaining)",
      t["inv_spools"][0]["weight_total_g"] == 1200 and t["inv_spools"][0]["weight_remaining_g"] == 800)
check("19. локации сохранены", t["inv_locations"][0]["name"] == "Полка")
check("20. vendor/material/color сохранены",
      t["inv_vendors"][0]["name"] == "VendorX" and t["inv_filaments"][0]["material"] == "PETG"
      and t["inv_filaments"][0]["color_hex"] == "#f00")
check("21. lot сохранён", t["inv_spools"][0]["lot"] == "LOT1")
check("22. привязка к stable printer ID сохранена (ams_printer_id+slot)",
      t["inv_spools"][0]["ams_printer_id"] == "p-1" and t["inv_spools"][0]["ams_slot"] == 0)
check("25. runtime-кэш (inv_pending_prints) исключён", "inv_pending_prints" not in t)
check("ledger (складская книга) сохранён", t["inv_ledger"][0]["qty"] == -50)
check("настройки модуля сохранены", snap["settings"] == {"currency": "RUB"})

print("--- restore semantics ---")
tgt = mp.DictModuleStore(tables={"inv_spools": [
    {"id": "cur-only", "filament_id": "", "label": "keep", "weight_total_g": 1,
     "weight_remaining_g": 1, "location_id": "", "price": 0, "lot": "", "purchased_at": "",
     "opened_at": "", "status": "in_stock", "nfc_uid": "", "ams_printer_id": "", "ams_slot": -1,
     "notes": "", "order_idx": 0, "is_deleted": 0, "created_at": "t", "updated_at": "t"}]})
plan = INV.build_restore_plan(tgt, snap, known_printer_ids=set())
check("23. отсутствующий принтер НЕ удаляет катушку: только warning missing_printer_ref",
      any(w["code"] == "missing_printer_ref" and w["printer_id"] == "p-1" for w in plan["warnings"]))
INV.apply_restore(tgt, snap)
ids = {r["id"] for r in tgt.read_table("inv_spools")}
check("upsert: записи копии добавлены, current-only катушка сохранена", ids == {"s1", "cur-only"})
check("привязка восстановлена как есть (не «переназначена по имени»)",
      [r for r in tgt.read_table("inv_spools") if r["id"] == "s1"][0]["ams_printer_id"] == "p-1")
check("26. verify: canonical-эквивалент после restore", INV.verify_restore(tgt, snap))

# Alpha 2.830 (root cause реальной копии 2.829): несопоставленная ВНУТРЕННЯЯ ссылка (цель
# удалена — напр. удалённая локация/филамент) — ЛЕГИТИМНОЕ состояние живой БД, НЕ повреждение.
# validate_snapshot её НЕ отклоняет; запись сохраняется как есть; план даёт warning-счётчик.
bad = copy.deepcopy(snap)
bad["domain_data"]["tables"]["inv_spools"][0]["filament_id"] = "no-such-filament"
try:
    INV.validate_snapshot(bad); r = None
except BackupError as e:
    r = e.reason
check("24. висячая внутренняя ссылка НЕ фатальна (запись сохраняется, не validation_failed)",
      r is None)
ur = INV.unresolved_internal_refs(bad)
check("24b. висячая ссылка попадает в план как dangling_internal_ref (счётчик, без значений)",
      any(u["table"] == "inv_spools" and u["column"] == "filament_id" and u["count"] == 1 for u in ur))
bad_tgt = mp.DictModuleStore()
INV.apply_restore(bad_tgt, bad)
check("24c. restore висячей ссылки сохраняет запись и значение (не обнуляет filament_id)",
      [r for r in bad_tgt.read_table("inv_spools") if r["id"] == "s1"][0]["filament_id"] == "no-such-filament")
# Структурное повреждение (дубликат ключа) ОСТАЁТСЯ фатальным.
dup = copy.deepcopy(snap)
dup["domain_data"]["tables"]["inv_spools"].append(dict(dup["domain_data"]["tables"]["inv_spools"][0]))
try:
    INV.validate_snapshot(dup); r = None
except BackupError as e:
    r = e.reason
check("duplicate ID отклоняется (структурное повреждение остаётся фатальным)", r == "validation_failed")

print("--- sqlite round trip (реальные CREATE TABLE, синтетическая БД) ---")
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "inv.db")
c = sqlite3.connect(db)
c.execute("CREATE TABLE inv_vendors (id TEXT PRIMARY KEY, name TEXT NOT NULL, notes TEXT DEFAULT '', order_idx INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)")
c.execute("CREATE TABLE inv_filaments (id TEXT PRIMARY KEY, vendor_id TEXT DEFAULT '', material TEXT DEFAULT '', color_name TEXT DEFAULT '', color_hex TEXT DEFAULT '', diameter REAL, density REAL, temp_min INTEGER, temp_max INTEGER, spool_weight_g REAL, price_per_kg REAL, notes TEXT DEFAULT '', order_idx INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)")
c.execute("CREATE TABLE inv_locations (id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT DEFAULT '', notes TEXT DEFAULT '', order_idx INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0, created_at TEXT)")
c.execute("CREATE TABLE inv_items (id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT DEFAULT '', unit TEXT DEFAULT 'шт', qty REAL, min_qty REAL, max_qty REAL, location_id TEXT DEFAULT '', price REAL, printer_brand TEXT DEFAULT '', printer_model TEXT DEFAULT '', notes TEXT DEFAULT '', order_idx INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)")
c.execute("CREATE TABLE inv_spools (id TEXT PRIMARY KEY, filament_id TEXT DEFAULT '', label TEXT DEFAULT '', weight_total_g REAL, weight_remaining_g REAL, location_id TEXT DEFAULT '', price REAL, lot TEXT DEFAULT '', purchased_at TEXT DEFAULT '', opened_at TEXT DEFAULT '', status TEXT DEFAULT 'in_stock', nfc_uid TEXT DEFAULT '', ams_printer_id TEXT DEFAULT '', ams_slot INTEGER DEFAULT -1, notes TEXT DEFAULT '', order_idx INTEGER DEFAULT 0, is_deleted INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)")
c.execute("CREATE TABLE inv_ledger (id TEXT PRIMARY KEY, ts TEXT, kind TEXT DEFAULT '', ref_type TEXT DEFAULT '', ref_id TEXT DEFAULT '', qty REAL, reason TEXT DEFAULT '', job_id TEXT DEFAULT '', username TEXT DEFAULT '', note TEXT DEFAULT '')")
c.execute("CREATE TABLE inv_settings (key TEXT PRIMARY KEY, value TEXT DEFAULT '')")
c.execute("CREATE TABLE inv_pending_prints (id TEXT PRIMARY KEY, note TEXT)")
c.execute("INSERT INTO inv_pending_prints (id, note) VALUES ('RUNTIME_KEEP', 'не трогать')")
c.commit(); c.close()

sq = SqliteModuleStore(db, INV.table_specs, "inv_settings", ("key", "value"))
INV.apply_restore(sq, snap)
check("sqlite: restore применён + verify canonical", INV.verify_restore(sq, snap))
re_snap = INV.export_snapshot(sq, installed_version="1.7.24")
check("sqlite: re-export == исходный canonical (round trip)",
      re_snap["domain_data"] == snap["domain_data"] and re_snap["settings"] == snap["settings"])
c = sqlite3.connect(db)
check("sqlite: runtime-таблица не тронута restore-ом",
      c.execute("SELECT COUNT(*) FROM inv_pending_prints").fetchone()[0] == 1)
c.close()
pre = sq.full_snapshot()
sq.upsert_rows("inv_spools", [{**snap["domain_data"]["tables"]["inv_spools"][0], "id": "junk"}], "id")
sq.restore_full(pre)
check("sqlite: rollback pre-image возвращает состояние байт-в-байт (canonical)",
      sq.full_snapshot() == pre)

# ═══════════════════════════════════════════════════════════════════════════════
# R-125 (data-safety-07), backup v2: мобильная приёмка склада — коды QR/штрихкодов, метки NFC,
# подготовленные наклейки. Раньше в копию не входили, а mobile_server_id (он в настройках) —
# входил: после восстановления телефон не узнавал уже принятые коды.
# ═══════════════════════════════════════════════════════════════════════════════
print("--- v2: мобильная приёмка (настоящий DDL модуля) ---")
import ast
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _inventory_ddl():
    """DDL модуля без его импорта: _INIT_SQL из backend.py + CREATE TABLE из mobile_api.init()."""
    out = []
    src = open(os.path.join(ROOT, "modules", "inventory", "backend.py"), encoding="utf-8").read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == "_INIT_SQL" for x in node.targets):
            out += list(ast.literal_eval(node.value))
    msrc = open(os.path.join(ROOT, "modules", "inventory", "mobile_api.py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(msrc)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.lstrip().startswith("CREATE TABLE"):
            out.append(node.value)
    return out


DDL = _inventory_ddl()


def ddl_db(name):
    p = os.path.join(tmp, name)
    cc = sqlite3.connect(p)
    for sql in DDL:
        cc.execute(sql)
    cc.commit(); cc.close()
    return p


def sq_store(path):
    return SqliteModuleStore(path, INV.table_specs, "inv_settings", ("key", "value"))


def rows(path, sql):
    cc = sqlite3.connect(path); cc.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in cc.execute(sql).fetchall()]
    finally:
        cc.close()


schema = ddl_db("schema.db")
in_ddl = {r["name"] for r in rows(schema, "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'inv_%'")}
spec_names = {s.name for s in INV.table_specs}
check("v2-1. таблицы провайдера = таблицы модуля без служебных (pending_prints, mobile_ops) и настроек",
      spec_names == in_ddl - {"inv_pending_prints", "inv_mobile_ops", "inv_settings"}
      and set(MOBILE) <= spec_names, sorted(in_ddl ^ spec_names))
bad = {}
for spec in INV.table_specs:
    cols = {r["name"] for r in rows(schema, 'PRAGMA table_info("%s")' % spec.name)}
    if cols != set(spec.columns):
        bad[spec.name] = sorted(cols ^ set(spec.columns))
check("v2-2. колонки каждой таблицы провайдера совпадают со схемой модуля", not bad)
check("v2-3. backup v2 с миграцией v1->v2; номер наклейки в партии объявлен уникальным",
      INV.backup_schema_version == 2 and set(INV.MIGRATIONS) == {1}
      and ("batch_id", "ordinal") in [s for s in INV.table_specs if s.name == "inv_mobile_labels"][0].unique)

src_db = ddl_db("mobile_src.db")
cc = sqlite3.connect(src_db)
for name, rws in store().full_snapshot()["tables"].items():
    if name == "inv_pending_prints":
        continue
    for r in rws:
        cc.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (name, ",".join(r), ",".join("?" for _ in r)), tuple(r.values()))
cc.execute("INSERT OR REPLACE INTO inv_settings(key,value) VALUES('mobile_server_id','srv-SOURCE')")
cc.execute("INSERT INTO inv_mobile_codes VALUES('4601234567890','product','f1','')")
cc.execute("INSERT INTO inv_mobile_codes VALUES('nfc:bambu:A1B2C3D4','unique','f1','s1')")
cc.execute("INSERT INTO inv_mobile_nfc(uid,spool_id,created_at) VALUES('A1B2C3D4','s1','2026-09-20 10:00:00')")
cc.execute("INSERT INTO inv_mobile_label_batches(id,name,filament_id,caption,weight_total_g,label,created_at) "
           "VALUES('labels_1','Партия','f1','VendorX PETG · Red',1000,'PETG','2026-09-20 10:00:00')")
cc.execute("INSERT INTO inv_mobile_labels(id,batch_id,ordinal,status) VALUES('spool_L1','labels_1',1,'prepared')")
cc.execute("INSERT INTO inv_mobile_labels(id,batch_id,ordinal,status,location_id,received_at) "
           "VALUES('spool_L2','labels_1',2,'received','L1','2026-09-21 09:00:00')")
cc.execute("INSERT INTO inv_mobile_ops VALUES('req_0000000000000001','h','{}')")
cc.commit(); cc.close()

v2 = INV.export_snapshot(sq_store(src_db), installed_version="1.7.30")
mt = v2["domain_data"]["tables"]
check("v2-4. коды QR/штрихкодов (включая nfc:bambu) экспортируются",
      [r["code"] for r in mt["inv_mobile_codes"]] == ["4601234567890", "nfc:bambu:A1B2C3D4"])
check("v2-5. метки NFC экспортируются", mt["inv_mobile_nfc"] == [{"uid": "A1B2C3D4", "spool_id": "s1",
                                                                  "created_at": "2026-09-20 10:00:00"}])
check("v2-6. подготовленные наклейки (партия и номера со статусами) экспортируются",
      len(mt["inv_mobile_label_batches"]) == 1
      and [(r["id"], r["ordinal"], r["status"]) for r in mt["inv_mobile_labels"]]
      == [("spool_L1", 1, "prepared"), ("spool_L2", 2, "received")])
check("v2-7. квитанции повторов (inv_mobile_ops) не входят; номер сервера — в настройках",
      "inv_mobile_ops" not in mt and v2["settings"].get("mobile_server_id") == "srv-SOURCE")

dst_db = ddl_db("mobile_dst.db")
INV.apply_restore(sq_store(dst_db), v2)
check("v2-8. восстановление на чистую базу: verify проходит", INV.verify_restore(sq_store(dst_db), v2))
check("v2-9. повторный экспорт совпадает с копией (round trip)",
      INV.export_snapshot(sq_store(dst_db), installed_version="1.7.30")["domain_data"] == v2["domain_data"])
check("v2-10. после восстановления телефон узнаёт код и метку (строки на месте)",
      rows(dst_db, "SELECT code FROM inv_mobile_codes ORDER BY code")[1]["code"] == "nfc:bambu:A1B2C3D4"
      and rows(dst_db, "SELECT spool_id FROM inv_mobile_nfc")[0]["spool_id"] == "s1")

print("--- v2: старая копия v1 (без мобильных таблиц) ---")
old = copy.deepcopy(v2)
old["backup_schema_version"] = 1
for name in MOBILE:
    old["domain_data"]["tables"].pop(name, None)
mig = INV.migrate_snapshot(old)
check("v2-11. миграция v1->v2 добавляет мобильные таблицы ПУСТЫМИ, остальное без изменений",
      mig["backup_schema_version"] == 2 and all(mig["domain_data"]["tables"][n] == [] for n in MOBILE)
      and mig["domain_data"]["tables"]["inv_spools"] == v2["domain_data"]["tables"]["inv_spools"])
INV.validate_snapshot(mig)
before_codes = rows(dst_db, "SELECT * FROM inv_mobile_codes ORDER BY code")
INV.apply_restore(sq_store(dst_db), mig)
check("v2-12. старая копия не трогает коды и метки, уже лежащие на цели",
      rows(dst_db, "SELECT * FROM inv_mobile_codes ORDER BY code") == before_codes
      and INV.verify_restore(sq_store(dst_db), mig))

print("--- v2: номер наклейки в партии занят другой наклейкой ---")
conf_db = ddl_db("mobile_conflict.db")
cc = sqlite3.connect(conf_db)
cc.execute("INSERT INTO inv_mobile_labels(id,batch_id,ordinal,status) VALUES('spool_OTHER','labels_1',1,'prepared')")
cc.commit(); cc.close()
conf = INV.restore_conflicts(sq_store(conf_db), v2)
check("v2-13. конфликт (партия, номер) найден заранее — без значений",
      conf == [{"code": "module_restore_conflict", "table": "inv_mobile_labels", "column": "batch_id,ordinal",
                "count": 1, "field_path": "inv_mobile_labels.batch_id"}], conf)
check("v2-14. та же наклейка (тот же id) конфликтом не считается",
      INV.restore_conflicts(sq_store(dst_db), v2) == [])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print("\n" + "=" * 60)
print("ИТОГО: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
