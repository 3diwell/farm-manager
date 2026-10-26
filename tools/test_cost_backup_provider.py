# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Провайдер модуля cost — «Расчёт заказа», backup v2 (R-125: modules-05 / data-safety-06).

До v2 провайдер описывал таблицы прежней «Себестоимости печати»: заказы «Расчёта заказа» в копию
не попадали (экспорт давал пустые таблицы), а старая копия 2.x на чистой 3.0 откатывала ВСЁ
восстановление (таблиц cost_* нет — UPSERT молча пропускался, проверка падала).

Здесь без сервера и без данных фермы (временные SQLite-базы):
  1. состав v2 сверяется с НАСТОЯЩИМ DDL модуля (modules/cost/backend.py) — таблицы и колонки;
  2. экспорт и круговое восстановление на настоящей SQLite; order_files в копию не входит;
  3. старая копия v1 (замороженная фикстура 2.829) мигрирует: данные «Себестоимости» уходят в
     extensions, не применяются, план о них говорит, восстановление проходит без отката;
  4. номер заказа, занятый на цели ДРУГИМ заказом, — отказ ДО изменений, а не откат посреди;
  5. счётчик номеров применяется как MAX(текущее, из копии).
"""
import ast
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.config_backup import module_providers as mp  # noqa: E402
from app.config_backup import multistore, recovery, serializer, validator, migrations  # noqa: E402
from app.config_backup.sqlite_store import SqliteModuleStore  # noqa: E402
from app.config_backup.repository import DictGateway  # noqa: E402
from app.config_backup.errors import BackupError  # noqa: E402

_n = {"pass": 0, "fail": 0}


def check(label, cond, extra=""):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label + ("" if ok or extra == "" else "  :: %s" % (extra,)))
    _n["pass" if ok else "fail"] += 1
    return ok


COST = mp.get_provider("cost")
TMP = tempfile.mkdtemp(prefix="fm_cost_backup_")


def _module_ddl():
    """DDL модуля — список строк DDL из modules/cost/backend.py (без импорта модуля)."""
    src = open(os.path.join(ROOT, "modules", "cost", "backend.py"), encoding="utf-8").read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DDL" for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit("DDL не найден в modules/cost/backend.py")


DDL = _module_ddl()


def new_db(name):
    p = os.path.join(TMP, name)
    c = sqlite3.connect(p)
    for sql in DDL:
        c.execute(sql)
    c.commit()
    c.close()
    return p


def store(path):
    # Так же, как ядро: _CFGBACKUP_MODULE_DB["cost"] = ("farm_cost.db", None, ...) — без таблицы
    # «ключ-значение»: настройки модуля — строка order_config.
    return SqliteModuleStore(path, COST.table_specs, None, ("key", "value"))


def db_rows(path, sql, args=()):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def db_exec(path, sql, args=()):
    c = sqlite3.connect(path)
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def order(iid, number, title="Заказ", updated="2026-09-20 10:00:00"):
    return (iid, number, title, "calculated", "2026-09-20", "", "", "", "", "not_connected", "RUB", "₽",
            1234.5, 2000.0, json.dumps({"title": title, "items": [{"file_token": "file_x"}]}, ensure_ascii=False),
            json.dumps({"full_cost": 1234.5}), "2026-09-20 10:00:00", updated)


ORDER_SQL = ("INSERT INTO orders(internal_id,order_number,title,status,created_date,due_date,project_id,"
             "project_name,external_crm_id,crm_sync_status,currency,currency_symbol,full_cost,customer_price,"
             "payload_json,calculation_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")


def fill_source(path):
    db_exec(path, "INSERT INTO order_config(key,value,updated_at) VALUES('global',?,?)",
            (json.dumps({"currency": "RUB", "tax_percent": 20.0}), "2026-09-20 10:00:00"))
    db_exec(path, "INSERT INTO order_model_rates(model_key,model_name,power_w,amortization_per_hour,"
                  "service_per_hour,updated_at) VALUES('x1c','X1C',350,12.5,3,'t')")
    db_exec(path, "INSERT INTO order_printer_rates(printer_id,printer_model,amortization_per_hour,"
                  "service_per_hour,power_override_w,amortization_override_enabled,service_override_enabled,"
                  "updated_at) VALUES('p1','X1C',15,4,NULL,1,0,'t')")
    db_exec(path, "INSERT INTO order_printer_models(printer_id,model_name,model_key,source,updated_at) "
                  "VALUES('p1','X1C','x1c','printer','t')")
    db_exec(path, "INSERT INTO order_sequence(year,last_seq) VALUES(2026,5)")
    db_exec(path, ORDER_SQL, order("ord_A", "2026-0004", "Кронштейны"))
    db_exec(path, ORDER_SQL, order("ord_B", "2026-0005", "Корпуса"))
    db_exec(path, "INSERT INTO order_files(file_id,order_id,file_token,filename,stored_path,size_bytes,sha256,"
                  "analysis_json,created_at) VALUES('f1','ord_A','file_x','part.3mf','C:/old/cost_order_files/ord_A/part.3mf',"
                  "10,'','{}','t')")


def payload_with(snaps):
    blob = serializer.export_backup_v2(DictGateway(config={}, app_settings={}, printers=[]),
                                       created_by="t", created_at="t", module_exports=snaps)
    return validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob).as_dict()))


def jr(name):
    return recovery.RecoveryJournal(os.path.join(TMP, name + ".json"))


try:
    print("--- 1. состав v2 = настоящая схема модуля (DDL modules/cost/backend.py) ---")
    ddl_tables = {s.split("CREATE TABLE IF NOT EXISTS ", 1)[1].split(" ", 1)[0].split("(", 1)[0]
                  for s in DDL if s.startswith("CREATE TABLE")}
    spec_names = {s.name for s in COST.table_specs}
    check("1. таблицы провайдера = таблицы модуля без order_files (файлы моделей в копию не входят)",
          spec_names == ddl_tables - {"order_files"} and "order_files" in ddl_tables, (spec_names, ddl_tables))
    schema_db = new_db("schema.db")
    bad_cols = {}
    for spec in COST.table_specs:
        cols = {r["name"] for r in db_rows(schema_db, 'PRAGMA table_info("%s")' % spec.name)}
        if cols != set(spec.columns):
            bad_cols[spec.name] = (sorted(cols ^ set(spec.columns)))
    check("2. колонки каждой таблицы провайдера совпадают со схемой модуля", not bad_cols, bad_cols)
    check("3. backup v2, миграция v1->v2 объявлена (append-only), таблицы «ключ-значение» нет",
          COST.backup_schema_version == 2 and set(COST.MIGRATIONS) == {1} and COST.settings_source is None)
    srv = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    _i = srv.index("_CFGBACKUP_MODULE_DB = {")
    _node = ast.parse(srv[_i:srv.index("\n}\n", _i) + 3]).body[0].value
    check("4. ядро открывает базу cost без таблицы настроек (farm_cost.db, None)",
          ast.literal_eval(_node).get("cost", ("", "x"))[:2] == ("farm_cost.db", None))
    ospec = [s for s in COST.table_specs if s.name == "orders"][0]
    check("5. номер заказа объявлен уникальным (как UNIQUE в схеме модуля)", ("order_number",) in ospec.unique)

    print("--- 2. экспорт с настоящей базы ---")
    src_db = new_db("source.db")
    fill_source(src_db)
    snap = COST.export_snapshot(store(src_db), installed_version="0.2.1")
    t = snap["domain_data"]["tables"]
    check("6. заказы экспортируются целиком (2 заказа, номера и расчёт на месте)",
          [r["order_number"] for r in t["orders"]] == ["2026-0004", "2026-0005"]
          and json.loads(t["orders"][0]["payload_json"])["title"] == "Кронштейны")
    check("7. настройки, ставки, модели принтеров и счётчик номеров экспортируются",
          len(t["order_config"]) == 1 and len(t["order_model_rates"]) == 1 and len(t["order_printer_rates"]) == 1
          and len(t["order_printer_models"]) == 1 and t["order_sequence"][0]["last_seq"] == 5)
    check("8. файлы моделей (order_files, абсолютные пути) в копию не входят", "order_files" not in t
          and "cost_order_files" not in json.dumps(snap, ensure_ascii=False))
    check("9. отдельных настроек «ключ-значение» нет (settings пусто), класс — данные с провайдером",
          snap["settings"] == {} and snap["data_class"] == mp.DATA_CLASS_PROVIDER
          and snap["backup_schema_version"] == 2)

    print("--- 3. круговое восстановление на чистую базу 3.0 ---")
    dst_db = new_db("clean.db")
    plan = COST.build_restore_plan(store(dst_db), snap, known_printer_ids={"p1"})
    check("10. план: всё добавляется, предупреждений нет",
          plan["counts"]["added"] == 7 and plan["counts"]["updated"] == 0 and plan["warnings"] == [], plan)
    COST.apply_restore(store(dst_db), snap)
    check("11. verify после восстановления проходит", COST.verify_restore(store(dst_db), snap))
    re_snap = COST.export_snapshot(store(dst_db), installed_version="0.2.1")
    check("12. повторный экспорт совпадает с копией (canonical round trip)",
          re_snap["domain_data"] == snap["domain_data"])
    plan_np = COST.build_restore_plan(store(new_db("np.db")), snap, known_printer_ids=set())
    check("13. принтера нет на цели — предупреждение, запись не удаляется",
          any(w["code"] == "missing_printer_ref" and w["printer_id"] == "p1" for w in plan_np["warnings"]))

    print("--- 4. старая копия v1 («Себестоимость печати», замороженная фикстура 2.829) ---")
    fx_dir = os.path.join(ROOT, "tools", "fixtures", "config_backup", "module_data")
    fx_man = json.load(open(os.path.join(fx_dir, "fixture_manifest.json"), encoding="utf-8"))["fixtures"][0]
    fx_blob = open(os.path.join(fx_dir, fx_man["file"]), "rb").read()
    check("14. фикстура заморожена (SHA-256 не изменился)", hashlib.sha256(fx_blob).hexdigest() == fx_man["sha256"])
    fx_payload = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(fx_blob).as_dict()))
    old = [m for m in fx_payload.module_data["modules"] if m["module_id"] == "cost"][0]
    check("15. в фикстуре — копия cost v1 с расчётом «Себестоимости»",
          old["backup_schema_version"] == 1 and "cost_calculations" in old["domain_data"]["tables"])
    mig = COST.migrate_snapshot(old)
    legacy = (mig.get("extensions") or {}).get(mp.LEGACY_COST_EXT) or {}
    check("16. миграция v1->v2: данные «Себестоимости» сохранены в extensions как есть",
          mig["backup_schema_version"] == 2
          and legacy.get("tables", {}).get("cost_calculations", [{}])[0].get("calc_id") == "fx-calc"
          and legacy.get("settings") == {"formula_branch": "default"})
    check("17. ... и не применяются: таблиц и настроек v2 в такой копии нет",
          mig["domain_data"] == {"tables": {}} and mig["settings"] == {})
    COST.validate_snapshot(mig)
    tgt_db = new_db("target_with_order.db")
    db_exec(tgt_db, ORDER_SQL, order("ord_T", "2026-0001", "Заказ на цели"))
    lp = COST.build_restore_plan(store(tgt_db), mig, known_printer_ids=set())
    check("18. план честно говорит: данные прежней «Себестоимости» не восстанавливаются (счётчик)",
          any(w["code"] == "legacy_cost_not_restored" and w["count"] == 2 for w in lp["warnings"]), lp["warnings"])
    gw = DictGateway(config={}, app_settings={}, printers=[])
    res = multistore.apply_restore_multistore(
        gw, fx_payload, ["core", "printers", "modules"], jr("legacy"),
        module_stores={"inventory": mp.DictModuleStore(), "cost": store(tgt_db)},
        installed_modules={"inventory": "1.7.30", "cost": "0.2.1", "quality": "0.2.3"})
    check("19. КРИТИЧНО: восстановление старой копии на 3.0 проходит без отката (раньше — rollback всего)",
          res.get("status") == "ok" and "cost" in res.get("modules_applied", []), res)
    check("20. заказ на цели не тронут, чужих таблиц cost_* не появилось",
          [r["internal_id"] for r in db_rows(tgt_db, "SELECT internal_id FROM orders")] == ["ord_T"]
          and not db_rows(tgt_db, "SELECT name FROM sqlite_master WHERE name LIKE 'cost_%'"))

    print("--- 5. номер заказа занят ДРУГИМ заказом на цели ---")
    conf_db = new_db("conflict.db")
    db_exec(conf_db, ORDER_SQL, order("ord_OTHER", "2026-0004", "Другой заказ"))
    conf = COST.restore_conflicts(store(conf_db), snap)
    check("21. конфликт найден заранее (таблица, колонка, счётчик — без значений)",
          conf == [{"code": "module_restore_conflict", "table": "orders", "column": "order_number",
                    "count": 1, "field_path": "orders.order_number"}], conf)
    check("22. тот же заказ (тот же internal_id) конфликтом не считается",
          COST.restore_conflicts(store(dst_db), snap) == [])
    pay = payload_with([snap])
    before = hashlib.sha256(open(conf_db, "rb").read()).hexdigest()
    fp = multistore.build_full_plan(DictGateway(config={}, app_settings={}, printers=[]), pay, ["modules"],
                                    module_stores={"cost": store(conf_db)}, installed_modules={"cost": "0.2.1"},
                                    known_printer_ids={"p1"})
    check("23. план: модуль заблокирован, причина — module_restore_conflict",
          fp["module_data"]["blocked"] and any(w.get("code") == "module_restore_conflict" and w.get("module_id") == "cost"
                                               for w in fp["module_data"]["warnings"]))
    err = None
    try:
        multistore.apply_restore_multistore(DictGateway(config={}, app_settings={}, printers=[]), pay,
                                            ["core", "printers", "modules"], jr("conflict"),
                                            module_stores={"cost": store(conf_db)}, installed_modules={"cost": "0.2.1"})
    except BackupError as e:
        err = e
    check("24. КРИТИЧНО: применение отказывает ДО изменений (manual_resolution, cost, orders.order_number)",
          err is not None and err.reason == "manual_resolution_required" and err.module_id == "cost"
          and err.field_path == "orders.order_number", getattr(err, "detail", err))
    check("25. база цели не изменилась ни на байт, журнал не открывался",
          hashlib.sha256(open(conf_db, "rb").read()).hexdigest() == before and not jr("conflict").is_pending())

    print("--- 6. счётчик номеров: MAX(текущее, из копии) ---")
    hi_db = new_db("seq_hi.db")
    db_exec(hi_db, "INSERT INTO order_sequence(year,last_seq) VALUES(2026,10)")
    COST.apply_restore(store(hi_db), snap)
    check("26. на цели номер уже дальше (10 > 5) — счётчик не откатывается назад",
          db_rows(hi_db, "SELECT last_seq FROM order_sequence WHERE year=2026")[0]["last_seq"] == 10)
    check("27. verify принимает «не меньше, чем в копии»", COST.verify_restore(store(hi_db), snap))
    lo_db = new_db("seq_lo.db")
    db_exec(lo_db, "INSERT INTO order_sequence(year,last_seq) VALUES(2026,2)")
    COST.apply_restore(store(lo_db), snap)
    check("28. на цели номер меньше (2 < 5) — берётся значение копии",
          db_rows(lo_db, "SELECT last_seq FROM order_sequence WHERE year=2026")[0]["last_seq"] == 5)
    db_exec(lo_db, "UPDATE order_sequence SET last_seq=1 WHERE year=2026")
    check("29. verify ловит счётчик меньше копии", not COST.verify_restore(store(lo_db), snap))

    print("--- 7. in-memory хранилище (тесты ядра) ---")
    dm = mp.DictModuleStore(tables={k: list(v) for k, v in t.items()})
    dsnap = COST.export_snapshot(dm, installed_version="0.2.1")
    tgt = mp.DictModuleStore()
    COST.apply_restore(tgt, dsnap)
    check("30. round trip на DictModuleStore", COST.verify_restore(tgt, dsnap)
          and COST.export_snapshot(tgt, installed_version="0.2.1")["domain_data"] == dsnap["domain_data"])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 60)
print("ИТОГО: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
