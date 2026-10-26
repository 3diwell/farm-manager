# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Схема оркестратора «Печатать весь проект» — core Alpha 2.740 (этапы 1-4, dry-run).
# Доказывает на ВРЕМЕННОЙ farm_parts.db со схемой ЯДРА (DDL берётся дословно из server.py):
#   • init создаёт ТОЛЬКО три новые таблицы и заявленные индексы;
#   • повторный init идемпотентен;
#   • ПОБАЙТОВЫЙ снимок всех существующих таблиц и строк до/после не отличается;
#   • в исходнике модуля нет ALTER/DROP/DELETE чужих данных;
#   • partial UNIQUE индексы физически запрещают: второй активный run проекта, два активных item'а
#     одного принтера, два item'а с одним project_print_job_id, второй активный clearance принтера.
# Запуск: python tools/test_project_orchestrator_schema.py   (0 = пройдено)
import importlib.util, os, sys, sqlite3, tempfile, threading, uuid, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
_MOD = open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()

fail = 0
def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


CORE_TABLES = ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs',
               'parts_catalog', 'staging_files', 'app_settings')
NEW_TABLES = {'project_runs', 'project_run_items', 'plate_clearances'}

db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in CORE_TABLES:
    c.execute(_ddl(t))
# наполняем ПОЛЬЗОВАТЕЛЬСКИМИ данными — они обязаны пережить init байт-в-байт
c.execute("INSERT INTO projects (id, name) VALUES ('prj','Мой проект')")
c.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty, "
          "rework_qty, rework_done) VALUES ('pa','prj','Деталь A','деталь a',5,2,1,0)")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','plate.3mf','hash1',1)")
c.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) "
          "VALUES ('l1','prj','F1','pa',2)")
c.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, file_norm, "
          "snapshot_json) VALUES ('pjob_1','prj','F1','pr1','plate.3mf','plate.3mf','[]')")
c.execute("INSERT INTO parts_catalog (part_name, required_qty, printed_qty) VALUES ('Старая деталь',3,1)")
c.execute("INSERT INTO staging_files (filename) VALUES ('quick.gcode')")
c.execute("INSERT INTO app_settings (key, value) VALUES ('theme','dark')")
c.commit()


def snapshot_all():
    """Побайтовый снимок КАЖДОЙ существующей таблицы: DDL + все строки (repr всех колонок)."""
    snap = {}
    for t in CORE_TABLES:
        ddl = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        rows = c.execute("SELECT * FROM %s ORDER BY rowid" % t).fetchall()
        snap[t] = (ddl["sql"] if ddl else None, [repr(tuple(r)) for r in rows])
    return snap


def tables():
    return {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def indexes():
    return {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}


before_tables, before_indexes, before_snap = tables(), indexes(), snapshot_all()

po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: ("IDLE", True),
        printers_fn=lambda: [{"id": "pr1", "name": "X1C", "type": "bambu"}],
        send_reserved_fn=lambda: set(), file_ok_fn=lambda f: True)
po.init_db()
after1_tables, after1_indexes, after1_snap = tables(), indexes(), snapshot_all()
po.init_db()   # ПОВТОРНЫЙ init
after2_tables, after2_indexes, after2_snap = tables(), indexes(), snapshot_all()

check('S1. init создал РОВНО три новые таблицы (project_runs, project_run_items, plate_clearances)',
      after1_tables - before_tables == NEW_TABLES)
check('S2. ни одна существующая таблица не исчезла', before_tables <= after1_tables)
check('S3. появились только заявленные индексы оркестратора',
      after1_indexes - before_indexes == {'idx_pruns_project', 'idx_pruns_active', 'idx_pri_run',
                                          'idx_pri_project', 'idx_pri_printer', 'idx_pri_pjob',
                                          'idx_pri_active_printer', 'idx_clr_printer', 'idx_clr_active'})
check('S4. ПОБАЙТОВЫЙ снимок существующих таблиц и строк ПОСЛЕ init идентичен снимку ДО',
      before_snap == after1_snap)
check('S5. повторный init полностью идемпотентен: ни таблиц, ни индексов, ни строк не изменилось',
      (after1_tables, after1_indexes, after1_snap) == (after2_tables, after2_indexes, after2_snap))
check('S6. DDL существующих таблиц не переписан (никаких ALTER)',
      all(before_snap[t][0] == after2_snap[t][0] for t in CORE_TABLES))
check('S7. пользовательские строки целы: project_parts/project_files/project_print_jobs байт-в-байт',
      all(before_snap[t][1] == after2_snap[t][1] for t in
          ('project_parts', 'project_files', 'project_print_jobs', 'parts_catalog', 'staging_files', 'app_settings')))

code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _MOD))
# Alpha 2.741: аддитивная миграция СВОИХ таблиц (feed_plan_json) legalизует ровно один вид ALTER —
# «ALTER TABLE <своя> ADD COLUMN». Прежний тотальный запрет 'ALTER ' заменён на ТОЧНУЮ проверку
# исходного намерения: чужие таблицы не ALTER'ятся, DROP/RENAME/переписывания нет вообще.
check('S8. нет DROP; DELETE/UPDATE чужих таблиц нет; ALTER — только ADD COLUMN по СВОИМ таблицам',
      'DROP ' not in code
      and all(re.match(r'^ALTER TABLE %s ADD COLUMN', a) for a in re.findall(r'"(ALTER[^"]*)"', code))
      and {t for t, _c, _d in po._MIGRATIONS} <= NEW_TABLES
      and not re.search(r'(DELETE|UPDATE)\s+(FROM\s+)?(project_parts|project_files|project_file_parts|'
                        r'project_print_jobs|projects|parts_catalog|staging_files)\b', code))
check('S9. модуль пишет ТОЛЬКО в свои три таблицы',
      set(re.findall(r'(?:INSERT INTO|UPDATE)\s+(\w+)', code)) <= NEW_TABLES)

# ── partial UNIQUE индексы: структурные запреты уровня БД ──
now = 1000.0
def mk_run(rid, state):
    c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
              "VALUES (?,?,?,?,?,?,?)", (rid, 'prj', state, 'exact', 'boot_A', now, now))
    c.commit()

mk_run('prun_1', 'draft')
try:
    mk_run('prun_2', 'running')
    ok = False
except sqlite3.IntegrityError:
    ok = True
check('S10. partial UNIQUE: ВТОРОЙ активный run того же проекта невозможен (уровень БД)', ok)
c.execute("UPDATE project_runs SET state='completed' WHERE id='prun_1'"); c.commit()
mk_run('prun_2', 'running')
check('S11. после завершения первого run новый активный создаётся штатно',
      c.execute("SELECT COUNT(*) n FROM project_runs").fetchone()["n"] == 2)

def mk_item(iid, state, printer='', pjob=''):
    c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
              "assigned_printer_id, project_print_job_id, planned_parts_json, planned_overproduction_json, "
              "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,'{}','{}',?,?)",
              (iid, 'prun_2', 'prj', 'F1', 1, state, printer, pjob, now, now))
    c.commit()

mk_item('pitem_1', 'printing', printer='pr1')
try:
    mk_item('pitem_2', 'leased', printer='pr1')
    ok = False
except sqlite3.IntegrityError:
    ok = True
check('S12. partial UNIQUE: ДВА активных item\'а на одном принтере невозможны (уровень БД)', ok)
mk_item('pitem_3', 'pending', printer='pr1')
check('S13. неактивные (pending) item\'ы на том же принтере ограничением НЕ задеты',
      c.execute("SELECT COUNT(*) n FROM project_run_items WHERE assigned_printer_id='pr1'").fetchone()["n"] == 2)

c.execute("UPDATE project_run_items SET project_print_job_id='pjob_1' WHERE id='pitem_1'"); c.commit()
try:
    c.execute("UPDATE project_run_items SET project_print_job_id='pjob_1' WHERE id='pitem_3'"); c.commit()
    ok = False
except sqlite3.IntegrityError:
    c.rollback()
    ok = True
check('S14. UNIQUE: два item\'а с ОДНИМ project_print_job_id невозможны', ok)
check('S15. пустой project_print_job_id ограничением не задет (partial index)',
      c.execute("SELECT COUNT(*) n FROM project_run_items WHERE project_print_job_id=''").fetchone()["n"] >= 1)

def mk_clr(cid, printer='pr1'):
    c.execute("INSERT INTO plate_clearances (id, printer_id, confirmed_at, nonce, boot_id) VALUES (?,?,?,?,?)",
              (cid, printer, now, uuid.uuid4().hex, 'boot_A'))
    c.commit()

mk_clr('clr_1')
try:
    mk_clr('clr_2')
    ok = False
except sqlite3.IntegrityError:
    ok = True
check('S16. partial UNIQUE: ВТОРОЙ активный clearance того же принтера невозможен (двойной клик отбит БД)', ok)
c.execute("UPDATE plate_clearances SET consumed_at=? WHERE id='clr_1'", (now,)); c.commit()
mk_clr('clr_2')
check('S17. после расходования токена новый создаётся штатно',
      c.execute("SELECT COUNT(*) n FROM plate_clearances").fetchone()["n"] == 2)

check('S18. существующие таблицы не пострадали и после всех вставок в НОВЫЕ таблицы',
      all(before_snap[t][1] == snapshot_all()[t][1] for t in CORE_TABLES))

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: init создаёт только три новые таблицы и заявленные индексы, идемпотентен; существующие '
              'таблицы, DDL и пользовательские строки остаются байт-в-байт прежними; partial UNIQUE индексы '
              'физически запрещают второй активный run, два item\'а на принтер, дубль project_print_job_id и '
              'второй активный clearance'))
sys.exit(1 if fail else 0)
