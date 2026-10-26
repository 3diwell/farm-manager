# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Аддитивная миграция feed_plan_json — core Alpha 2.741 (этап 5A1).
# Доказывает на ВРЕМЕННЫХ БД, что колонка project_run_items.feed_plan_json:
#   • есть сразу на чистой БД;
#   • ДОБАВЛЯЕТСЯ к БД Alpha 2.740, где её не было, без потери строк;
#   • миграция идемпотентна (повторный init ничего не меняет);
#   • существующие строки получают DEFAULT '{}' (не NULL);
#   • чужие таблицы/строки/DDL остаются байт-в-байт прежними;
#   • колонка заполняется РОВНО из одного места (persist_feed_plan) и dispatch не появился.
# Смысл плана подачи (builder/approval/CIEDE2000) проверяет tools/test_project_feed_plan.py.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_feed_plan_schema.py   (0 = пройдено)
import importlib.util, os, re, sqlite3, tempfile, threading, uuid

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
    """DDL ядра берём ДОСЛОВНО из server.py — тест обязан падать, если схема ядра уедет."""
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


CORE_TABLES = ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs')
COL = 'feed_plan_json'


def _mkdb():
    db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
    c = sqlite3.connect(db, check_same_thread=False)
    c.row_factory = sqlite3.Row
    for t in CORE_TABLES:
        c.execute(_ddl(t))
    c.execute("INSERT INTO projects (id, name) VALUES ('prj','Мой проект')")
    c.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
              "VALUES ('pa','prj','Деталь A','деталь a',5,2)")
    c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
              "VALUES ('F1','prj','plate.3mf','hash1',1)")
    c.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, file_norm, "
              "snapshot_json) VALUES ('pjob_1','prj','F1','pr1','plate.3mf','plate.3mf','[]')")
    c.commit()
    return c


def _wire(c, boot='boot_A'):
    po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], boot,
            printer_status_fn=lambda pid: ("IDLE", True),
            printers_fn=lambda: [{"id": "pr1", "name": "X1C", "type": "bambu"}],
            send_reserved_fn=lambda: set(), file_ok_fn=lambda f: True)


def cols(c, t):
    return [r[1] for r in c.execute("PRAGMA table_info(%s)" % t).fetchall()]


def snap_foreign(c):
    """Побайтовый снимок ЧУЖИХ таблиц: DDL + все строки."""
    out = {}
    for t in CORE_TABLES:
        ddl = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
        rows = [tuple(repr(v) for v in r) for r in c.execute("SELECT * FROM %s" % t).fetchall()]
        out[t] = (ddl["sql"] if ddl else None, rows)
    return out


# ── A. ЧИСТАЯ БД: колонка есть сразу ───────────────────────────────────────────────────────────
c1 = _mkdb()
_wire(c1)
po.init_db()
check('A1. чистая БД: project_run_items.%s существует сразу' % COL, COL in cols(c1, 'project_run_items'))
_ci = [r for r in c1.execute("PRAGMA table_info(project_run_items)").fetchall() if r[1] == COL][0]
check('A2. тип TEXT, NOT NULL, DEFAULT \'{}\'',
      _ci[2].upper() == 'TEXT' and _ci[3] == 1 and _ci[4] == "'{}'")
check('A3. миграций ровно одна и она про свою таблицу',
      po._MIGRATIONS == [('project_run_items', 'feed_plan_json', "TEXT NOT NULL DEFAULT '{}'")])

# ── B. БД Alpha 2.740 БЕЗ колонки -> миграция ──────────────────────────────────────────────────
c2 = _mkdb()
# Воссоздаём ТОЧНО прежнюю таблицу: берём актуальный DDL и вычёркиваем ровно строку новой колонки —
# так «версия 2.740» не разъедется с реальностью, если схема ещё изменится.
_ddl_now = [q for q in po._SCHEMA if 'CREATE TABLE IF NOT EXISTS project_run_items' in q][0]
_ddl_740 = re.sub(r'\n\s*feed_plan_json TEXT NOT NULL DEFAULT \'\{\}\',', '', _ddl_now)
check('B1. эмуляция 2.740: DDL действительно без колонки и в остальном идентичен',
      COL not in _ddl_740 and len(_ddl_740) < len(_ddl_now))
c2.execute(_ddl_740)
c2.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, created_at, updated_at) "
           "VALUES ('pitem_old','prun_old','prj','F1',1,'pending',1000.0,1000.0)")
c2.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, created_at, updated_at) "
           "VALUES ('pitem_old2','prun_old','prj','F1',2,'completed',1000.0,1000.0)")
c2.commit()
check('B2. до миграции колонки нет', COL not in cols(c2, 'project_run_items'))
_before = snap_foreign(c2)
_wire(c2)
po.init_db()
check('B3. после init колонка добавлена', COL in cols(c2, 'project_run_items'))
check('B4. существующие строки НЕ потеряны (2 шт, id и состояния целы)',
      [(r["id"], r["state"]) for r in c2.execute("SELECT id, state FROM project_run_items ORDER BY seq").fetchall()]
      == [('pitem_old', 'pending'), ('pitem_old2', 'completed')])
check('B5. существующие строки получили DEFAULT \'{}\' (не NULL)',
      [r[COL] for r in c2.execute("SELECT %s FROM project_run_items ORDER BY seq" % COL).fetchall()] == ['{}', '{}'])
check('B6. чужие таблицы/DDL/строки байт-в-байт прежние', snap_foreign(c2) == _before)

# ── C. Идемпотентность ─────────────────────────────────────────────────────────────────────────
_added2 = po._migrate()
check('C1. повторная миграция НИЧЕГО не добавляет', _added2 == [])
po.init_db()
po.init_db()
check('C2. повторный init_db не ломает и не плодит колонку',
      [x for x in cols(c2, 'project_run_items')].count(COL) == 1)
check('C3. после повторных init строки по-прежнему целы и чужие таблицы не тронуты',
      c2.execute("SELECT COUNT(*) n FROM project_run_items").fetchone()["n"] == 2 and snap_foreign(c2) == _before)
_dbl = po._migrate()
check('C4. миграция сообщает пустой список, когда добавлять нечего', _dbl == [])

# ── D. Новые строки и запись ───────────────────────────────────────────────────────────────────
c2.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, created_at, updated_at) "
           "VALUES ('pitem_new','prun_old','prj','F1',3,'pending',1001.0,1001.0)")
c2.commit()
check('D1. новая строка без явного значения получает \'{}\'',
      c2.execute("SELECT %s v FROM project_run_items WHERE id='pitem_new'" % COL).fetchone()["v"] == '{}')
check('D2. колонка принимает JSON и читается обратно (для будущего 5A2)',
      (c2.execute("UPDATE project_run_items SET %s='{\"ams_slot\": 2}' WHERE id='pitem_new'" % COL),
       c2.commit(),
       c2.execute("SELECT %s v FROM project_run_items WHERE id='pitem_new'" % COL).fetchone()["v"])[2]
      == '{"ams_slot": 2}')

# ── E. Никакого dispatch и никакого использования feed_plan ────────────────────────────────────
_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _MOD))
check('E1. предохранитель по-прежнему выключен', po.DISPATCH_ENABLED is False)
# Alpha 2.742 (5A2a): колонку теперь ЗАПОЛНЯЕТ builder — прежний инвариант «нигде не читается»
# устарел по замыслу и заменён на актуальный и более ценный: писать в неё можно РОВНО из одного
# места (persist_feed_plan), чтобы план не мог появиться мимо проверок и транзакции.
_writes = [l.strip() for l in _code.splitlines() if re.search(r'(UPDATE|INSERT).*feed_plan_json', l)]
check('E2. feed_plan_json пишется РОВНО из одного места — persist_feed_plan (мимо него плана не будет)',
      len(_writes) == 1
      and _MOD.index('UPDATE project_run_items SET feed_plan_json=?') > _MOD.index('def persist_feed_plan')
      and _MOD.index('UPDATE project_run_items SET feed_plan_json=?') < _MOD.index('def read_feed_plan'))
check('E2b. запись идёт под BEGIN IMMEDIATE и проверяет принадлежность run и состояние item',
      all(x in _MOD[_MOD.index('def persist_feed_plan'):_MOD.index('def read_feed_plan')]
          for x in ('BEGIN IMMEDIATE', 'item_not_in_run', 'item_state_locked', 'rowcount')))
check('E3. в модуле по-прежнему нет транспорта/печати',
      not re.search(r'_send_mgr|paho|mqtt|ftplib|requests|socket|_do_project2_file_print|_send_file_to_printer', _code))
check('E4. ALTER — только ADD COLUMN и только по своим таблицам',
      all(re.match(r'^ALTER TABLE %s ADD COLUMN', a) for a in re.findall(r'"(ALTER[^"]*)"', _MOD))
      and 'DROP ' not in _code)

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: feed_plan_json есть на чистой БД и аддитивно доезжает до БД 2.740 без потери строк; '
              'миграция идемпотентна, старые строки получают \'{}\', чужие таблицы байт-в-байт целы; '
              'колонка заполняется ровно из одного места (persist_feed_plan) под транзакцией, '
              'dispatch не появился'))
raise SystemExit(1 if fail else 0)
