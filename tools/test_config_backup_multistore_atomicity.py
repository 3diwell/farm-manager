# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — multi-store атомарность: pre-images, порядок, каскадные откаты, crash-журнал,
verification, cleanup, конкурентность, sqlite fail-safe. Только синтетика (TemporaryDirectory)."""
import copy
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, validator, migrations, multistore, recovery
from app.config_backup import module_providers as mp
from app.config_backup.sqlite_store import SqliteModuleStore
from app.config_backup.repository import DictGateway
from app.config_backup.errors import BackupError

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


def _inv_rows():
    return [{"id": "s1", "filament_id": "", "label": "L", "weight_total_g": 1,
             "weight_remaining_g": 1, "location_id": "", "price": 0, "lot": "", "purchased_at": "",
             "opened_at": "", "status": "in_stock", "nfc_uid": "", "ams_printer_id": "",
             "ams_slot": -1, "notes": "", "order_idx": 0, "is_deleted": 0,
             "created_at": "t", "updated_at": "t"}]


GW_SRC = DictGateway(config={"lan_access_enabled": True, "modules_disabled": []},
                     app_settings={"net_monitor": "1"}, printers=[])
INV = mp.get_provider("inventory")
COST = mp.get_provider("cost")
SNAP_INV = INV.export_snapshot(mp.DictModuleStore(tables={"inv_spools": _inv_rows()},
                                                  settings={"currency": "RUB"}), "1.7.24")
# R-125: cost — «Расчёт заказа» (backup v2): данные модуля — заказы (таблица orders).
SNAP_COST = COST.export_snapshot(mp.DictModuleStore(tables={"orders": [
    {"internal_id": "ord_1", "order_number": "2026-0001", "title": "", "status": "draft",
     "created_date": "2026-09-20", "due_date": "", "project_id": "", "project_name": "",
     "external_crm_id": "", "crm_sync_status": "not_connected", "currency": "RUB",
     "currency_symbol": "₽", "full_cost": 0, "customer_price": 0, "payload_json": "{}",
     "calculation_json": "{}", "created_at": "t", "updated_at": "t"}]}, settings={}), "0.2.1")
BLOB = serializer.export_backup_v2(GW_SRC, created_by="t", created_at="t",
                                   module_exports=[SNAP_INV, SNAP_COST])
PAYLOAD = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(BLOB).as_dict()))
INSTALLED = {"inventory": "1.7.24", "cost": "0.2.1"}


def fresh():
    return (DictGateway(config={"lan_access_enabled": False}, app_settings={"net_monitor": "0"}, printers=[]),
            {"inventory": mp.DictModuleStore(), "cost": mp.DictModuleStore()})


def jr():
    return recovery.RecoveryJournal(os.path.join(tempfile.mkdtemp(), "j.json"))


print("--- pre-images и порядок ---")
gw, stores = fresh()
j = jr()
res = multistore.apply_restore_multistore(gw, PAYLOAD, ["core", "printers", "modules"], j,
                                          stores, INSTALLED)
meta = (j.read() or {}).get("meta") or {}
check("43. pre-image КАЖДОГО store создаётся (order+hashes в meta журнала)",
      meta.get("order") == ["core", "cost", "inventory"]
      and set(meta.get("hashes") or {}) == {"core", "module:cost", "module:inventory"})
check("44. порядок применения детерминирован (core -> модули по module_id)",
      res["modules_applied"] == ["cost", "inventory"])
check("52. успех удаляет все pre-images (complete + затирание)",
      (j.read() or {}).get("state") == "complete" and (j.read() or {}).get("pre_image") is None)

print("--- каскадные откаты ---")
class Boom(mp.DictModuleStore):
    def __init__(self, fail_table):
        super().__init__(); self.fail_table = fail_table
    def upsert_rows(self, name, rows, key):
        super().upsert_rows(name, rows, key)
        if name == self.fail_table:
            raise RuntimeError("boom")

gw, _ = fresh()
core0 = gw.full_snapshot()
st = {"inventory": Boom("inv_spools"), "cost": mp.DictModuleStore()}
cost0 = st["cost"].full_snapshot()
check("45. сбой Inventory откатывает core (и применённый до него cost)",
      _reason(lambda: multistore.apply_restore_multistore(gw, PAYLOAD, ["core", "printers", "modules"],
              jr(), st, INSTALLED)) == "rollback_completed"
      and gw.full_snapshot() == core0 and st["cost"].full_snapshot() == cost0)

gw, _ = fresh()
core0 = gw.full_snapshot()
st = {"inventory": mp.DictModuleStore(), "cost": Boom("orders")}
inv0 = st["inventory"].full_snapshot()
check("46. сбой Cost (первый по порядку) откатывает core; inventory ещё не применялся и цел",
      _reason(lambda: multistore.apply_restore_multistore(gw, PAYLOAD, ["core", "printers", "modules"],
              jr(), st, INSTALLED)) == "rollback_completed"
      and gw.full_snapshot() == core0 and st["inventory"].full_snapshot() == inv0)

class BadVerify(mp.DictModuleStore):
    def read_table(self, name):
        rows = super().read_table(name)
        return [] if name == "inv_spools" and rows else rows   # «после» apply читается пусто

gw, _ = fresh()
core0 = gw.full_snapshot()
st = {"inventory": BadVerify(), "cost": mp.DictModuleStore()}
check("47-48. verification failure модуля откатывает ВСЁ (core+cost+inventory)",
      _reason(lambda: multistore.apply_restore_multistore(gw, PAYLOAD, ["core", "printers", "modules"],
              jr(), st, INSTALLED)) == "rollback_completed" and gw.full_snapshot() == core0)

print("--- rollback: обратный порядок + верификация ---")
seq = []
class TracerGW(DictGateway):
    def restore_full(self, snap):
        seq.append("core"); super().restore_full(snap)

gw = TracerGW(config={}, app_settings={}, printers=[])
st = {"inventory": Boom("inv_spools"), "cost": mp.DictModuleStore()}
_orig_inv_restore = st["inventory"].restore_full
st["inventory"].restore_full = lambda s: (seq.append("inventory"), _orig_inv_restore(s))[-1]
_orig_cost_restore = st["cost"].restore_full
st["cost"].restore_full = lambda s: (seq.append("cost"), _orig_cost_restore(s))[-1]
_reason(lambda: multistore.apply_restore_multistore(gw, PAYLOAD, ["core", "printers", "modules"],
        jr(), st, INSTALLED))
check("50. rollback идёт в ОБРАТНОМ порядке (inventory -> cost -> core), включая упавший mid-apply store",
      seq == ["inventory", "cost", "core"])

class RollbackLiar(mp.DictModuleStore):
    def restore_full(self, snap):
        pass                                          # «откат», который ничего не вернул
gw, _ = fresh()
st = {"inventory": Boom("inv_spools"), "cost": RollbackLiar()}
st["cost"].upsert_rows("orders", [{"internal_id": "junk"}], "internal_id")
r = _reason(lambda: multistore.apply_restore_multistore(gw, PAYLOAD, ["core", "printers", "modules"],
            jr(), st, INSTALLED))
check("51. rollback сам ПРОВЕРЯЕТСЯ (лживый откат -> rollback_failed, не тихий успех)",
      r == "rollback_failed")

print("--- crash-журнал ---")
gw, stores = fresh()
pre = {"__multi__": True, "core": gw.full_snapshot(),
       "modules": {"inventory": stores["inventory"].full_snapshot(),
                   "cost": stores["cost"].full_snapshot()}}
j = jr()
j.set_prepared(pre, meta={"order": ["core", "cost", "inventory"]})
j.set_state("applying_module:cost")
gw.apply_mutation(serializer.payload_to_mutation(PAYLOAD, ["core"]))
stores["cost"].upsert_rows("orders", [{"internal_id": "half"}], "internal_id")
check("журнал pending на applying_module", j.is_pending())
rec = multistore.recover_on_startup_multi(j, gw, stores)
check("49. crash recovery восстанавливает ВСЕ stores из pre-images",
      rec["action"] == "rolled_back_multi"
      and gw.full_snapshot() == pre["core"]
      and stores["cost"].full_snapshot() == pre["modules"]["cost"]
      and not j.is_pending())

print("--- fail-safe: sqlite locked / конкурентность ---")
tmp = tempfile.mkdtemp()
db = os.path.join(tmp, "m.db")
c = sqlite3.connect(db)
c.execute("CREATE TABLE inv_spools (id TEXT PRIMARY KEY, filament_id TEXT, label TEXT, weight_total_g REAL, weight_remaining_g REAL, location_id TEXT, price REAL, lot TEXT, purchased_at TEXT, opened_at TEXT, status TEXT, nfc_uid TEXT, ams_printer_id TEXT, ams_slot INTEGER, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT, updated_at TEXT)")
c.execute("CREATE TABLE inv_vendors (id TEXT PRIMARY KEY, name TEXT, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT, updated_at TEXT)")
c.execute("CREATE TABLE inv_filaments (id TEXT PRIMARY KEY, vendor_id TEXT, material TEXT, color_name TEXT, color_hex TEXT, diameter REAL, density REAL, temp_min INTEGER, temp_max INTEGER, spool_weight_g REAL, price_per_kg REAL, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT, updated_at TEXT)")
c.execute("CREATE TABLE inv_locations (id TEXT PRIMARY KEY, name TEXT, parent_id TEXT, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT)")
c.execute("CREATE TABLE inv_items (id TEXT PRIMARY KEY, name TEXT, category TEXT, unit TEXT, qty REAL, min_qty REAL, max_qty REAL, location_id TEXT, price REAL, printer_brand TEXT, printer_model TEXT, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT, updated_at TEXT)")
c.execute("CREATE TABLE inv_ledger (id TEXT PRIMARY KEY, ts TEXT, kind TEXT, ref_type TEXT, ref_id TEXT, qty REAL, reason TEXT, job_id TEXT, username TEXT, note TEXT)")
c.execute("CREATE TABLE inv_settings (key TEXT PRIMARY KEY, value TEXT)")
c.commit()
c.execute("BEGIN EXCLUSIVE")                          # запертая БД
gw, _ = fresh()
core0 = gw.full_snapshot()
sq = SqliteModuleStore(db, INV.table_specs, "inv_settings", ("key", "value"))
r = _reason(lambda: multistore.apply_restore_multistore(gw, PAYLOAD, ["core", "printers", "modules"],
            jr(), {"inventory": sq, "cost": mp.DictModuleStore()}, INSTALLED))
c.rollback(); c.close()
check("54. запертая module-БД -> fail-safe (database_busy ДО мутаций либо полный откат)",
      r in ("database_busy", "rollback_completed", "rollback_failed"))
check("53. диск/БД сбой не оставляет half-state core",
      gw.full_snapshot() == core0 or r == "rollback_failed")

check("55. concurrent restore blocked: серверный маршрут держит _CFGBACKUP_RESTORE_LOCK",
      "_CFGBACKUP_RESTORE_LOCK.acquire(blocking=False)" in
      open(os.path.join(os.path.dirname(__file__), "..", "server.py"), encoding="utf-8").read())

print("--- журнал от прежней сборки (другой состав таблиц) ---")
# R-125 (замечание проверки): сбой посреди восстановления на сборке ДО правки оставил журнал, где
# pre-image cost — старые таблицы cost_*, а у склада нет inv_mobile_*. Новая сборка при старте
# откатывает по этому журналу уже с НОВЫМИ спеками: таблицы, которых нет в pre-image, трогать
# нельзя — иначе заказы, order_config и коды QR/NFC стёрлись бы (вставлять-то нечего).
def _mk_db(path, specs, settings_table=None):
    cc = sqlite3.connect(path)
    for sp in specs:
        cols = ", ".join('"%s"%s' % (col, " PRIMARY KEY" if col == sp.key else "") for col in sp.columns)
        cc.execute('CREATE TABLE "%s" (%s)' % (sp.name, cols))
    if settings_table:
        cc.execute('CREATE TABLE "%s" (key TEXT PRIMARY KEY, value TEXT)' % settings_table)
    cc.commit(); cc.close()


cost_db, inv_db = os.path.join(tmp, "farm_cost.db"), os.path.join(tmp, "farm_inventory.db")
_mk_db(cost_db, COST.table_specs)
_mk_db(inv_db, INV.table_specs, "inv_settings")
sq_cost = SqliteModuleStore(cost_db, COST.table_specs, None)
sq_inv = SqliteModuleStore(inv_db, INV.table_specs, "inv_settings", ("key", "value"))
sq_cost.upsert_rows("orders", [dict(SNAP_COST["domain_data"]["tables"]["orders"][0])], "internal_id")
_cfg_spec = [sp for sp in COST.table_specs if sp.name == "order_config"][0]
sq_cost.upsert_rows("order_config", [{c: ("1" if c == _cfg_spec.key else "x") for c in _cfg_spec.columns}],
                    _cfg_spec.key)
sq_inv.upsert_rows("inv_mobile_codes", [{"code": "4601234567890", "kind": "product",
                                         "filament_id": "f1", "spool_id": ""}], "code")
sq_inv.upsert_rows("inv_spools", _inv_rows(), "id")
sq_inv.write_settings({"currency": "RUB"})
cost_before, inv_before = sq_cost.full_snapshot(), sq_inv.full_snapshot()
gw, _ = fresh()
old_pre = {"__multi__": True, "core": gw.full_snapshot(),
           "modules": {"cost": {"tables": {"cost_printer_settings": [], "cost_calculations": []},
                                "settings": {"currency": "RUB"}},
                       "inventory": {"tables": {s.name: sq_inv.read_table(s.name) for s in INV.table_specs
                                                if not s.name.startswith("inv_mobile_")},
                                     "settings": {"currency": "EUR"}}}}
j = jr()
j.set_prepared(old_pre, meta={"order": ["core", "cost", "inventory"]})
j.set_state("applying_module:cost")
rec = multistore.recover_on_startup_multi(j, gw, {"cost": sq_cost, "inventory": sq_inv})
cost_after, inv_after = sq_cost.full_snapshot(), sq_inv.full_snapshot()
check("56. КРИТИЧНО: откат по журналу прежней сборки не стирает заказы и order_config",
      rec["action"] == "rolled_back_multi" and len(cost_after["tables"]["orders"]) == 1
      and len(cost_after["tables"]["order_config"]) == 1 and cost_after["tables"] == cost_before["tables"])
check("57. КРИТИЧНО: и коды QR/NFC склада (inv_mobile_*), которых нет в старом pre-image, целы",
      len(inv_after["tables"]["inv_mobile_codes"]) == 1
      and inv_after["tables"]["inv_mobile_codes"] == inv_before["tables"]["inv_mobile_codes"])
check("58. таблицы и настройки, которые в старом pre-image есть, откатываются как раньше",
      inv_after["tables"]["inv_spools"] == inv_before["tables"]["inv_spools"]
      and inv_after["settings"] == {"currency": "EUR"})
sq_cost.restore_full({"tables": {"orders": []}})
check("59. таблица, которая в pre-image есть (пустая), очищается — свой откат не ослаблен",
      sq_cost.read_table("orders") == [] and len(sq_cost.read_table("order_config")) == 1)
sq_inv.restore_full({"tables": {"inv_spools": []}})
check("60. pre-image без настроек настройки модуля не стирает",
      sq_inv.read_settings() == {"currency": "EUR"} and sq_inv.read_table("inv_spools") == []
      and len(sq_inv.read_table("inv_mobile_codes")) == 1)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
