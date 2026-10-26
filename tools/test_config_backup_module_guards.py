# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-125: данные модулей в копии — какие модули входят и когда их нельзя применить.

1. Отключённые и не загрузившиеся модули тоже входят в копию (data-safety-01): раньше
   _cfgbackup_installed_modules читал только _loaded_modules, и их данные выпадали молча.
2. Базы модуля ещё нет (модуль ни разу не запускался) — экспорт и план читают её как пустую и
   НЕ создают файл.
3. В копии есть строки таблицы, которой у модуля на этом компьютере нет (модуль старее копии):
   раньше UPSERT молча пропускал таблицу, проверка падала и откатывала ВСЁ восстановление. Теперь
   план блокирует модуль с понятной причиной, а применение отказывает ДО любых изменений.
4. Интерфейс: причины показаны словами по-русски и по-английски, у «Видеостены» и уведомлений
   есть названия.

Без сервера и без данных фермы: временные SQLite-базы, DictGateway, разбор исходников.
"""
import ast
import hashlib
import os
import re
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


INV = mp.get_provider("inventory")
TMP = tempfile.mkdtemp(prefix="fm_module_guards_")
V1_TABLES = [
    "CREATE TABLE inv_vendors (id TEXT PRIMARY KEY, name TEXT, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT, updated_at TEXT)",
    "CREATE TABLE inv_filaments (id TEXT PRIMARY KEY, vendor_id TEXT, material TEXT, color_name TEXT, color_hex TEXT, diameter REAL, density REAL, temp_min INTEGER, temp_max INTEGER, spool_weight_g REAL, price_per_kg REAL, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT, updated_at TEXT)",
    "CREATE TABLE inv_locations (id TEXT PRIMARY KEY, name TEXT, parent_id TEXT, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT)",
    "CREATE TABLE inv_items (id TEXT PRIMARY KEY, name TEXT, category TEXT, unit TEXT, qty REAL, min_qty REAL, max_qty REAL, location_id TEXT, price REAL, printer_brand TEXT, printer_model TEXT, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT, updated_at TEXT)",
    "CREATE TABLE inv_spools (id TEXT PRIMARY KEY, filament_id TEXT, label TEXT, weight_total_g REAL, weight_remaining_g REAL, location_id TEXT, price REAL, lot TEXT, purchased_at TEXT, opened_at TEXT, status TEXT, nfc_uid TEXT, ams_printer_id TEXT, ams_slot INTEGER, notes TEXT, order_idx INTEGER, is_deleted INTEGER, created_at TEXT, updated_at TEXT)",
    "CREATE TABLE inv_ledger (id TEXT PRIMARY KEY, ts TEXT, kind TEXT, ref_type TEXT, ref_id TEXT, qty REAL, reason TEXT, job_id TEXT, username TEXT, note TEXT)",
    "CREATE TABLE inv_settings (key TEXT PRIMARY KEY, value TEXT)",
]


def old_module_db(name, with_settings=True):
    """База склада старой версии модуля: таблицы v1 без мобильной приёмки."""
    p = os.path.join(TMP, name)
    c = sqlite3.connect(p)
    for sql in V1_TABLES:
        if with_settings or "inv_settings" not in sql:
            c.execute(sql)
    c.commit()
    c.close()
    return p


def sq(path):
    return SqliteModuleStore(path, INV.table_specs, "inv_settings", ("key", "value"))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def payload_with(snaps):
    blob = serializer.export_backup_v2(DictGateway(config={"lan_access_enabled": False},
                                                   app_settings={"net_monitor": "1"}, printers=[]),
                                       created_by="t", created_at="t", module_exports=snaps)
    return validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(blob).as_dict()))


SNAP_MOBILE = INV.export_snapshot(mp.DictModuleStore(tables={
    "inv_mobile_codes": [{"code": "4601234567890", "kind": "product", "filament_id": "f1", "spool_id": ""}]},
    settings={"mobile_server_id": "srv-A"}), installed_version="1.7.30")
SNAP_EMPTY_MOBILE = INV.export_snapshot(mp.DictModuleStore(tables={
    "inv_locations": [{"id": "L1", "name": "Полка", "parent_id": "", "notes": "", "order_idx": 0,
                       "is_deleted": 0, "created_at": "t"}]}, settings={"currency": "RUB"}),
    installed_version="1.7.30")

try:
    print("--- 1. базы модуля ещё нет: читается пустой и не создаётся ---")
    ghost = os.path.join(TMP, "never_started", "farm_inventory.db")
    os.makedirs(os.path.dirname(ghost))
    gs = sq(ghost)
    snap_g = INV.export_snapshot(gs, installed_version="1.7.30", enabled=False)
    check("1. экспорт модуля без базы — пустой снимок, enabled=false",
          snap_g["enabled"] is False and snap_g["settings"] == {}
          and all(v == [] for v in snap_g["domain_data"]["tables"].values()))
    check("2. has_table/full_snapshot без базы — «пусто», без исключений",
          gs.has_table("inv_spools") is False and gs.full_snapshot() == {
              "tables": {s.name: [] for s in INV.table_specs}, "settings": {}})
    gs.upsert_rows("inv_spools", [{"id": "x"}], "id")
    gs.write_settings({"k": "v"})
    gs.restore_full({"tables": {"inv_spools": [{"id": "x"}]}, "settings": {"k": "v"}})
    check("3. КРИТИЧНО: ни чтение, ни запись, ни откат не создали файл базы", not os.path.exists(ghost))
    check("4. пустой снимок на модуль без базы — не блокируется (экспорт и само-проверка проходят)",
          multistore.module_block_reasons(INV, gs, snap_g) == [])
    blk = multistore.module_block_reasons(INV, gs, SNAP_MOBILE)
    check("5. данные в копии, а база модуля ни разу не создавалась — модуль блокируется",
          len(blk) == 1 and blk[0]["code"] == "module_not_initialized", blk)
    check("5b. причина — «ни разу не запускался: включите и перезапустите», а не «обновите модуль»",
          blk and "ни разу не запускался" in blk[0]["text"] and "Обновите" not in blk[0]["text"]
          and blk[0].get("field_path") == "inv_mobile_codes" and not os.path.exists(ghost), blk)

    print("--- 2. модуль на цели старее копии (нет мобильных таблиц) ---")
    old_db = old_module_db("old_module.db")
    reasons = multistore.module_block_reasons(INV, sq(old_db), SNAP_MOBILE)
    check("6. причина module_tables_missing называет недостающую таблицу (без значений)",
          reasons and reasons[0]["code"] == "module_tables_missing" and reasons[0]["tables"] == ["inv_mobile_codes"]
          and reasons[0]["field_path"] == "inv_mobile_codes" and "4601234567890" not in str(reasons), reasons)
    check("7. копия без строк в новых таблицах на старый модуль ложится (не блокируется)",
          multistore.module_block_reasons(INV, sq(old_db), SNAP_EMPTY_MOBILE) == [])
    no_st = old_module_db("old_no_settings.db", with_settings=False)
    r_st = multistore.module_block_reasons(INV, sq(no_st), SNAP_EMPTY_MOBILE)
    check("8. нет таблицы настроек, а в копии настройки есть — тоже блок (иначе молчаливый пропуск)",
          r_st and r_st[0]["tables"] == ["inv_settings"], r_st)
    check("9. тестовое хранилище в памяти таблицы не проверяет — поведение прежнее",
          multistore.module_block_reasons(INV, mp.DictModuleStore(), SNAP_MOBILE) == [])

    pay = payload_with([SNAP_MOBILE])
    gw = DictGateway(config={"lan_access_enabled": False}, app_settings={"net_monitor": "0"}, printers=[])
    plan = multistore.build_full_plan(gw, pay, ["core", "printers", "modules"],
                                      module_stores={"inventory": sq(old_db)},
                                      installed_modules={"inventory": "1.7.24"}, known_printer_ids=set())
    check("10. план: модуль заблокирован, предупреждение с module_id и кодом",
          plan["module_data"]["blocked"] is True
          and any(w.get("code") == "module_tables_missing" and w.get("module_id") == "inventory"
                  for w in plan["module_data"]["warnings"]))
    check("10b. план называет заблокированный модуль (blocked_modules) — выход для окна копии",
          plan["module_data"]["blocked_modules"] == ["inventory"] and plan["module_data"]["excluded"] == [])
    plan_x = multistore.build_full_plan(gw, pay, ["core", "printers", "modules"],
                                        module_stores={"inventory": sq(old_db)},
                                        installed_modules={"inventory": "1.7.24"}, known_printer_ids=set(),
                                        exclude_modules=("inventory", "not_in_backup"))
    check("10c. план с исключённым модулем не заблокирован; модуль назван исключённым, в счётчиках его нет",
          plan_x["module_data"]["blocked"] is False and plan_x["module_data"]["blocked_modules"] == []
          and plan_x["module_data"]["excluded"] == ["inventory"]
          and not any(m.get("module_id") == "inventory" for m in plan_x["module_data"]["modules"])
          and not any(w.get("module_id") == "inventory" for w in plan_x["warnings"]), plan_x["module_data"])
    pay_q = payload_with([SNAP_MOBILE, mp.get_provider("quality").export_snapshot(mp.DictModuleStore(),
                                                                                 installed_version="0.2.3")])
    kw = dict(module_stores={"inventory": sq(old_db)}, known_printer_ids=set(),
              installed_modules={"inventory": "1.7.24", "quality": "0.2.3"})
    ids_all = [m.get("module_id") for m in multistore.build_full_plan(
        gw, pay_q, ["core", "printers", "modules"], **kw)["module_data"]["modules"]]
    md_q = multistore.build_full_plan(gw, pay_q, ["core", "printers", "modules"],
                                      exclude_modules=("quality",), **kw)["module_data"]
    check("10d. исключённый модуль без данных тоже не значится в плане как восстанавливаемый",
          "quality" in ids_all and "quality" not in [m.get("module_id") for m in md_q["modules"]]
          and md_q["excluded"] == ["quality"], (ids_all, md_q))
    core0, db0 = gw.full_snapshot(), sha(old_db)
    jpath = os.path.join(TMP, "journal_old.json")
    err = None
    try:
        multistore.apply_restore_multistore(gw, pay, ["core", "printers", "modules"],
                                            recovery.RecoveryJournal(jpath),
                                            module_stores={"inventory": sq(old_db)},
                                            installed_modules={"inventory": "1.7.24"})
    except BackupError as e:
        err = e
    check("11. КРИТИЧНО: применение отказывает ДО изменений (manual_resolution, inventory, имя таблицы)",
          err is not None and err.reason == "manual_resolution_required" and err.module_id == "inventory"
          and err.section == "modules" and err.field_path == "inv_mobile_codes", getattr(err, "detail", err))
    check("12. ядро и база модуля не тронуты, журнал восстановления не открывался",
          gw.full_snapshot() == core0 and sha(old_db) == db0 and not os.path.exists(jpath))
    res = multistore.apply_restore_multistore(gw, pay, ["core", "printers", "modules"],
                                              recovery.RecoveryJournal(os.path.join(TMP, "j_excl.json")),
                                              module_stores={"inventory": sq(old_db)},
                                              installed_modules={"inventory": "1.7.24"},
                                              exclude_modules=("inventory",))
    check("13. явно исключённый модуль не мешает восстановить остальное", res.get("status") == "ok"
          and res.get("modules_applied") == [] and sha(old_db) == db0)

    print("--- 3. в копию входят отключённые и не загрузившиеся модули (server.py) ---")
    SRC = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    tree = ast.parse(SRC)
    fnode = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_cfgbackup_installed_modules"][0]
    ns = {
        "MODULE_STATE_INVALID_MANIFEST": "invalid_manifest",
        "_loaded_modules": {"inventory": {"manifest": {"id": "inventory", "version": "1.7.30"}},
                            "quality": {"manifest": {"id": "quality", "version": "0.2.3"}}},
        "_disabled_modules": {"cost": {"manifest": {"id": "cost", "version": "0.2.1"}}},
        "_failed_modules": {
            "messengers": {"manifest": {"id": "messengers", "version": "0.1.8"}, "state": "load_error",
                           "installed_version": "0.1.8"},
            "quality": {"manifest": {"id": "quality", "version": "0.2.2"}, "state": "load_error"},
            "junk_folder": {"manifest": {}, "state": "invalid_manifest"},
            "{bad}": {"manifest": {"id": "{bad}"}, "state": "invalid_manifest"},
        },
    }
    exec(compile(ast.Module(body=[fnode], type_ignores=[]), "server.py", "exec"), ns)
    got = ns["_cfgbackup_installed_modules"]()
    check("14. загруженные + ОТКЛЮЧЁННЫЕ + НЕ ЗАГРУЗИВШИЕСЯ модули входят в копию (версии верные)",
          got == {"inventory": "1.7.30", "quality": "0.2.3", "cost": "0.2.1", "messengers": "0.1.8"}, got)
    check("15. папка без годного манифеста модулем не считается (нет stable id)",
          "junk_folder" not in got and "{bad}" not in got)
    exp = ast.get_source_segment(SRC, [n for n in tree.body if isinstance(n, ast.FunctionDef)
                                       and n.name == "_cfgbackup_module_exports"][0])
    stores = ast.get_source_segment(SRC, [n for n in tree.body if isinstance(n, ast.FunctionDef)
                                          and n.name == "_cfgbackup_module_stores"][0])
    check("16. экспорт и хранилища берут тот же полный список; отключённый помечается enabled=false",
          "_cfgbackup_installed_modules()" in exp and "enabled=(mid not in disabled)" in exp
          and "_cfgbackup_installed_modules()" in stores)

    print("--- 4. интерфейс: причины словами, названия модулей ---")
    JS = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
    IDX = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    wt = JS[JS.find("const cbWarnText = (w) => {"):]
    wt = wt[:wt.find("\n    };") + 7]
    check("17. предупреждения плана с новыми кодами — по-русски и по-английски",
          all(c in wt for c in ("'security_held_no_admin'", "'module_tables_missing'", "'module_restore_conflict'",
                                "'legacy_cost_not_restored'"))
          and "старее копии" in wt and "older than the backup" in wt and "return w.text || ''" in wt)
    check("18. окно плана выводит предупреждения через cbWarnText (а не сырой текст сервера)",
          "{{ cbWarnText(w) }}" in IDX and "{{ w.text }}" not in IDX
          and re.search(r"cbModLabel, cbWarnText,", JS) is not None)
    lab = JS[JS.find("const cbModLabel = (mid) => {"):]
    lab = lab[:lab.find("};") + 2]
    check("19. у «Видеостены» и уведомлений в мессенджеры есть названия (RU/EN)",
          "camera_wall: ru ? 'Видеостена' : 'Camera Wall'" in lab
          and "messengers: ru ? 'Уведомления в мессенджеры' : 'Messenger notifications'" in lab)
    err_fn = JS[JS.find("const cbErrorText = (j) => {"):JS.find("const cbWarnText = (w) => {")]
    check("20. отказ применения с причиной (field_path) не выдаётся за «нужен модуль»",
          "j.field_path" in err_fn and err_fn.find("j.field_path") < err_fn.find("требуется модуль")
          and "нельзя применить на этом компьютере" in err_fn and "cannot be applied on this computer" in err_fn)
    check("21. «ни разу не запускался» — свой текст RU/EN, отличный от «обновите модуль»",
          "'module_not_initialized'" in wt and "ни разу не запускался" in wt and "has never run" in wt)
    ins = JS[JS.find("const cbInspect = async"):JS.find("const cbApply = async")]
    app_ = JS[JS.find("const cbApply = async"):JS.find("const cbRestartLater")]
    pick = JS[JS.find("const cbPickImport"):JS.find("const cbInspect = async")]
    check("22. план и применение уходят с ОДНИМ списком исключённых модулей; смена файла его сбрасывает",
          "req.exclude_modules = cbExclude.value.slice()" in ins
          and "req.exclude_modules = cbExclude.value.slice()" in app_
          and "cbExclude.value = [];" in pick)
    check("23. заблокированный план применить нельзя (кнопка и сама функция)",
          "cbPlanBlocked()) return;" in app_ and ':disabled="cbBusy || cbPlanBlocked()"' in IDX)
    check("24. у заблокированного модуля есть «Восстановить без модуля», у исключённого — «Вернуть» (RU/EN)",
          'v-for="mid in cbBlockedModules()"' in IDX and "cbSetExclude(mid, true)" in IDX
          and "Восстановить без модуля «" in IDX and "Restore without the" in IDX
          and 'v-for="mid in cbExcludedModules()"' in IDX and "cbSetExclude(mid, false)" in IDX
          and "Вернуть в восстановление" in IDX and "Include again" in IDX
          and "module_data.blocked_modules" in JS and "module_data.excluded" in JS)
    se = JS[JS.find("const cbSetExclude = async"):]
    se = se[:se.find("\n    };") + 7]
    check("25. исключение перестраивает план (cbInspect), а не применяет его",
          "await cbInspect()" in se and "cbApply" not in se)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 60)
print("ИТОГО: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
