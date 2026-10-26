# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Завершение item/run по ручному подтверждению «Стол очищен» — core Alpha 2.746 (этап 5A4).
# ЗАЧЕМ. До 2.746 цепочка обрывалась: FINISH переводил item в waiting_plate_clear, оператор жал
# «Стол очищен» — и НИЧЕГО не происходило. item навсегда оставался waiting_plate_clear, run не
# завершался, принтер оставался удержан планом НАВСЕГДА (ручной старт получал printer_held), а у
# ПОСЛЕДНЕГО item подтвердить стол было вообще нельзя: printer_suits_run требовал наличия
# pending/eligible item'ов, которых у последнего уже нет.
# ИНВАРИАНТ, который здесь защищается: FINISH сам по себе НЕ освобождает принтер — освобождает
# только человек, и только после того, как подтвердил, что снял детали.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_clearance_completion.py   (0 = пройдено)
import importlib.util, os, re, sqlite3, tempfile, threading, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
_MOD = open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

fail = 0
BOOM = []


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def bomb(tag):
    def _b(*a, **k):
        BOOM.append(tag)
        raise AssertionError('ЗАПРЕЩЕНО в 5A4: ' + tag)
    return _b


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


# ══ Стенд ══════════════════════════════════════════════════════════════════════════════════════
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
CORE = ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs')
for t in CORE:
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
c.execute("INSERT INTO projects (id, name) VALUES ('prj2','P2')")
c.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
          "VALUES ('pa','prj','A','a',5,2)")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','plate.3mf','h1',1)")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F2','prj2','other.3mf','h2',1)")
c.commit()

LOCK = threading.Lock()
HOLDS = {}
SAFE = {'pr1': ('IDLE', 'IDLE', False), 'pr2': ('IDLE', 'IDLE', False)}   # (status, status_raw, printing_active)
_bombs = {'sched': bomb('_scheduler_tick_core'), 'tick': bomb('scheduler_tick'),
          'reserve': bomb('_send_mgr.reserve'), 'run': bomb('_send_mgr.run'),
          'do_print': bomb('_do_project2_file_print'), 'send_file': bomb('_send_file_to_printer'),
          'mkjob': bomb('create_project_print_job'), 'finjob': bomb('finish_project_print_job (повторно)'),
          'mqtt': bomb('mqtt.publish'), 'ftp': bomb('ftp.storbinary'), 'http': bomb('http_transport'),
          'after': bomb('after_dispatch'), 'ledger': bomb('inv_ledger')}


def SAFETY(pid):
    st, raw, active = SAFE.get(pid, ('OFFLINE', '', True))
    fresh = st != 'OFFLINE'
    return {"printer_id": pid, "transport": "bambu", "status": st, "status_raw": raw, "fresh": fresh,
            "user_stopped_pending": False, "printing_active": active,
            "safe_idle": fresh and raw == 'IDLE' and not active,
            "unsafe_reason": '' if (fresh and raw == 'IDLE') else 'x'}


def A_set_hold(pid, ot, oid, reason):
    h = HOLDS.get(pid)
    if h and (h['owner_type'], h['owner_id']) != (ot, oid):
        return (False, dict(h))
    HOLDS[pid] = {"printer_id": pid, "owner_type": ot, "owner_id": oid, "reason": reason}
    return (True, dict(HOLDS[pid]))


def A_clear_hold(pid, ot, oid):
    h = HOLDS.get(pid)
    if not h or (h['owner_type'], h['owner_id']) != (ot, oid):
        return False                       # чужое удержание не снимаем никогда
    del HOLDS[pid]
    return True


def wire(boot='boot_A'):
    po.init(c, LOCK, lambda p: p + uuid.uuid4().hex[:10], boot,
            printer_status_fn=lambda pid: (SAFE.get(pid, ('OFFLINE',))[0], SAFE.get(pid, ('OFFLINE',))[0] != 'OFFLINE'),
            safety_fn=SAFETY,
            printers_fn=lambda: [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0},
                                 {"id": "pr2", "name": "B", "type": "bambu", "order_idx": 1}],
            send_reserved_fn=lambda: set(), file_ok_fn=lambda f: True,
            holds_fn=lambda: dict(HOLDS), set_hold_fn=A_set_hold, clear_hold_fn=A_clear_hold,
            file_requirements_fn=lambda fr: {"status": "ok", "filament_count": 1, "file_hash": "h1",
                                             "filaments": [{"file_index": 0, "material": "PETG", "color_hex": "#161616"}]},
            filament_snapshot_fn=lambda pid: {}, reported_filament_fn=lambda pid: {})


wire()
po.init_db()
COMPAT = lambda f: ['pr1', 'pr2']


def mk(run_state='running', items=(), jobs=(), proj='prj', run_id='prun_1'):
    """items: (item_id, seq, state, printer, pjob). jobs: (job_id, printer, counted, status)."""
    with LOCK:
        c.execute("DELETE FROM project_runs"); c.execute("DELETE FROM project_run_items")
        c.execute("DELETE FROM plate_clearances"); c.execute("DELETE FROM project_print_jobs")
        c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
                  "VALUES (?,?,?,'exact',?,1.0,1.0)", (run_id, proj, run_state, po._ctx['boot']))
        for jid, pid, counted, st in jobs:
            c.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, "
                      "file_norm, snapshot_json, status, counted_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (jid, proj, 'F1' if proj == 'prj' else 'F2', pid, 'plate.3mf', 'plate3mf', '[]', st,
                       ('2024-01-01 10:00:00' if counted else '')))
        for iid, seq, st, pid, pjob in items:
            c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
                      "assigned_printer_id, project_print_job_id, created_at, updated_at) "
                      "VALUES (?,?,?,?,?,?,?,?,1.0,1.0)",
                      (iid, run_id, proj, 'F1' if proj == 'prj' else 'F2', seq, st, pid, pjob))
        c.commit()
    HOLDS.clear()
    for _i, _s, _st, _p, _j in items:
        if _p and _st in po.HOLD_ITEM_STATES:
            HOLDS[_p] = {"printer_id": _p, "owner_type": "project_run", "owner_id": run_id,
                         "reason": "project_run_item:" + _st}


def istate(iid):
    with LOCK:
        r = c.execute("SELECT state FROM project_run_items WHERE id=?", (iid,)).fetchone()
    return r["state"] if r else None


def ifin(iid):
    with LOCK:
        r = c.execute("SELECT finished_at FROM project_run_items WHERE id=?", (iid,)).fetchone()
    return r["finished_at"] if r else None


def rstate(rid='prun_1'):
    with LOCK:
        r = c.execute("SELECT state, finished_at FROM project_runs WHERE id=?", (rid,)).fetchone()
    return (r["state"], r["finished_at"]) if r else (None, None)


def nclr():
    with LOCK:
        return c.execute("SELECT COUNT(*) n FROM plate_clearances").fetchone()["n"]


def confirm(pid='pr1', job='pjob_1', run='prun_1', by='op'):
    return po.create_clearance(pid, confirmed=True, finished_job_id=job, confirmed_by=by,
                               run_id=run, compat_fn=COMPAT)


def snap_all():
    out = {}
    with LOCK:
        for t in [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            out[t] = [tuple(repr(v) for v in r) for r in c.execute("SELECT * FROM %s" % t).fetchall()]
    return out


ONE = (('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1'),)
JOB1 = (('pjob_1', 'pr1', True, 'finished'),)

# ══ §2. ДЫРА: воспроизводим ДО правки ═════════════════════════════════════════════════════════
# Эти четыре проверки — дискриминирующие: на коде 2.745 они ОБЯЗАНЫ падать.
mk(items=ONE, jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)          # печать кончилась, детали на столе
check('D0. исходно: item ждёт очистки, задание учтено, принтер удержан планом',
      istate('it_1') == 'waiting_plate_clear' and HOLDS.get('pr1', {}).get('owner_id') == 'prun_1')
r = confirm()
check('D1. ДЫРА-1: подтверждение «Стол очищен» у ПОСЛЕДНЕГО item вообще принимается',
      r.get('status') == 'ok')
check('D2. ДЫРА-2: после подтверждения item становится completed', istate('it_1') == 'completed')
check('D3. ДЫРА-3: последний item -> run завершён', rstate()[0] == 'completed')
check('D4. ДЫРА-4: у завершённого run принтер ОСВОБОЖДЁН (иначе он занят планом навсегда)',
      'pr1' not in HOLDS)

# ══ A. Один item: полный успешный цикл ════════════════════════════════════════════════════════
mk(items=ONE, jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
_before = snap_all()
r = confirm()
check('A1. подтверждение принято', r.get('status') == 'ok')
check('A2. item -> completed и у него проставлен finished_at',
      istate('it_1') == 'completed' and ifin('it_1') is not None)
check('A3. run -> completed и у него проставлен finished_at',
      rstate()[0] == 'completed' and rstate()[1] is not None)
check('A4. создана РОВНО одна строка разрешения (аудит)', nclr() == 1)
_cl = dict(c.execute("SELECT * FROM plate_clearances").fetchone())
check('A5. КРИТИЧНО: у завершённого run разрешение НЕ остаётся действующим (сразу consumed)',
      _cl['consumed_at'] is not None and _cl['consumed_by_item_id'] == 'it_1')
check('A6. active_clearance = null, last_clearance.status = consumed',
      po.active_clearance('pr1') is None
      and po.clearance_public(po.last_clearance('pr1'))['status'] == 'consumed')
check('A7. разрешение помнит, какое задание завершено (аудит)', _cl['finished_job_id'] == 'pjob_1')
check('A8. КРИТИЧНО: удержание снято — принтер снова доступен ручному старту', 'pr1' not in HOLDS)
check('A9. ответ отдаёт честный снимок: item/run/clearance',
      r.get('item', {}).get('state') == 'completed' and r.get('run', {}).get('state') == 'completed'
      and r['clearance']['status'] == 'consumed')

# ══ §11 + O. Учёт деталей 5A4 НЕ трогает ══════════════════════════════════════════════════════
_after = snap_all()
check('O1. КРИТИЧНО: количества деталей проекта НЕ изменены (учёт сделал FINISH, ровно один раз)',
      _before['project_parts'] == _after['project_parts'])
check('O2. project_print_jobs не изменены: второго задания/учёта не создано',
      _before['project_print_jobs'] == _after['project_print_jobs'])
check('O3. изменились ТОЛЬКО таблицы оркестратора и аудит разрешений',
      {t for t in _before if _before[t] != _after[t]} <= {'project_runs', 'project_run_items', 'plate_clearances'})
check('O4. project_files/projects/связи не тронуты',
      all(_before[t] == _after[t] for t in ('projects', 'project_files', 'project_file_parts')))

# ══ B. Два item'а: следующий ждёт, но НЕ запускается ══════════════════════════════════════════
mk(items=(('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1'), ('it_2', 2, 'pending', '', '')), jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
r = confirm()
check('B1. первый item -> completed', r.get('status') == 'ok' and istate('it_1') == 'completed')
check('B2. второй item остался pending — автозапуска нет', istate('it_2') == 'pending')
check('B3. КРИТИЧНО: разрешение ОСТАЁТСЯ действующим для следующего item того же run',
      po.active_clearance('pr1') is not None)
check('B4. КРИТИЧНО: удержание остаётся — ручной старт по-прежнему заблокирован',
      HOLDS.get('pr1', {}).get('owner_id') == 'prun_1')
check('B5. run НЕ завершён, переведён в рабочее состояние ожидания принтера',
      rstate()[0] == 'waiting_for_printer' and rstate()[1] is None)
check('B6. разрешение помнит завершённое задание', po.active_clearance('pr1')['finished_job_id'] == 'pjob_1')
check('B7. токен НЕ потреблён — его потратит следующий lease', po.active_clearance('pr1')['consumed_at'] is None)

# ══ C. Paused run ═════════════════════════════════════════════════════════════════════════════
mk(run_state='paused', items=(('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1'),
                              ('it_2', 2, 'pending', '', '')), jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
r = confirm()
check('C1. paused: item -> completed', r.get('status') == 'ok' and istate('it_1') == 'completed')
check('C2. КРИТИЧНО: run ОСТАЁТСЯ paused (подтверждение стола планом не управляет)', rstate()[0] == 'paused')
check('C3. разрешение активно, удержание остаётся',
      po.active_clearance('pr1') is not None and 'pr1' in HOLDS)
check('C4. автозапуска нет', istate('it_2') == 'pending')

# ══ D. Cancelled run, но печать фактически завершилась ════════════════════════════════════════
mk(run_state='cancelled', items=ONE, jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
r = confirm()
check('D5. cancelled: подтверждение очистки ВСЁ РАВНО обязательно и принимается', r.get('status') == 'ok')
check('D6. item отражает фактический FINISH -> completed', istate('it_1') == 'completed')
check('D7. run остаётся cancelled (не воскрешаем)', rstate()[0] == 'cancelled')
check('D8. КРИТИЧНО: действующего разрешения не остаётся — только аудит consumed',
      po.active_clearance('pr1') is None
      and po.clearance_public(po.last_clearance('pr1'))['status'] == 'consumed')
check('D9. КРИТИЧНО: удержание снято — принтер возвращён ферме', 'pr1' not in HOLDS)

# ══ E. Остаток из blocked/attention ═══════════════════════════════════════════════════════════
mk(items=(('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1'),
          ('it_2', 2, 'blocked', '', '')), jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
r = confirm()
check('E1. item -> completed', r.get('status') == 'ok' and istate('it_1') == 'completed')
check('E2. КРИТИЧНО: run НЕ считается завершённым — остались нерешённые item\'ы',
      rstate()[0] == 'attention_required' and rstate()[1] is None)
check('E3. МОДЕЛЬ: продолжение невозможно без человека -> действующего разрешения НЕ оставляем',
      po.active_clearance('pr1') is None)
check('E4. МОДЕЛЬ: но принтер ОСТАЁТСЯ удержан до явного решения владельца '
      '(сам себя план не отпускает)', HOLDS.get('pr1', {}).get('owner_id') == 'prun_1')

mk(items=(('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1'),
          ('it_2', 2, 'ambiguous_after_dispatch', 'pr2', 'pjob_2')),
   jobs=(('pjob_1', 'pr1', True, 'finished'), ('pjob_2', 'pr2', False, 'dispatched')))
SAFE['pr1'] = ('FINISH', 'FINISH', False)
r = confirm()
check('E5. ambiguous на ДРУГОМ принтере не мешает подтвердить этот стол', r.get('status') == 'ok')
check('E6. run -> attention_required, удержание чужого принтера не тронуто',
      rstate()[0] == 'attention_required' and HOLDS.get('pr2', {}).get('owner_id') == 'prun_1')

# ══ F-I. Неверные подтверждения: ни одно НЕ снимает удержание ═════════════════════════════════
def rejects(name, kw, want):
    mk(items=(('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1'),), jobs=JOB1)
    SAFE['pr1'] = ('FINISH', 'FINISH', False)
    _b = snap_all()
    r = po.create_clearance(kw.get('pid', 'pr1'), confirmed=kw.get('confirmed', True),
                            finished_job_id=kw.get('job', 'pjob_1'), confirmed_by='op',
                            run_id=kw.get('run', 'prun_1'), compat_fn=COMPAT)
    ok = r.get('status') == 'error' and (want is None or r.get('reason') == want)
    check(name, ok and snap_all() == _b and istate('it_1') == 'waiting_plate_clear'
          and HOLDS.get('pr1', {}).get('owner_id') == 'prun_1')


rejects('F1. чужой finished_job_id -> отказ, БД и удержание не тронуты', {'job': 'pjob_ЧУЖОЙ'}, 'job_not_in_run')
rejects('F2. задание другого run -> отказ', {'run': 'prun_ДРУГОЙ'}, None)
rejects('F3. подтверждение не того принтера -> отказ', {'pid': 'pr2'}, None)
rejects('F4. confirmed != true -> отказ', {'confirmed': False}, 'confirmation_required')

mk(items=(('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1'),),
   jobs=(('pjob_1', 'pr1', False, 'dispatched'),))     # НЕ учтено
SAFE['pr1'] = ('FINISH', 'FINISH', False)
_b = snap_all()
r = confirm()
check('G1. задание ещё НЕ учтено (FINISH не подтверждён) -> отказ',
      r.get('status') == 'error' and snap_all() == _b and 'pr1' in HOLDS)

mk(items=(('it_1', 1, 'ambiguous_after_dispatch', 'pr1', 'pjob_1'),), jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
_b = snap_all()
r = confirm()
check('H1. item в неоднозначности -> подтверждение стола его НЕ завершает',
      r.get('status') == 'error' and istate('it_1') == 'ambiguous_after_dispatch' and 'pr1' in HOLDS)

mk(items=ONE, jobs=JOB1)
SAFE['pr1'] = ('RUNNING', 'RUNNING', True)             # принтер физически печатает
_b = snap_all()
r = confirm()
check('I1. принтер печатает -> отказ printer_busy, ничего не изменилось',
      r.get('status') == 'error' and r.get('reason') == 'printer_busy' and snap_all() == _b)
SAFE['pr1'] = ('IDLE', 'IDLE', False)
mk(items=ONE, jobs=JOB1)
SAFE['pr1'] = ('OFFLINE', '', True)
r = confirm()
check('I2. телеметрия offline/stale -> отказ telemetry_stale', r.get('reason') == 'telemetry_stale')
SAFE['pr1'] = ('IDLE', 'IDLE', False)

# ══ J. Повторное подтверждение ════════════════════════════════════════════════════════════════
mk(items=ONE, jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
r1 = confirm()
_after1 = snap_all()
r2 = confirm()
check('J1. первое подтверждение завершило item/run', r1.get('status') == 'ok' and istate('it_1') == 'completed')
check('J2. второе подтверждение безопасно: либо идемпотентный snapshot, либо контролируемый отказ',
      r2.get('status') in ('ok', 'error'))
check('J3. КРИТИЧНО: вторая строка разрешения НЕ создана', nclr() == 1)
check('J4. КРИТИЧНО: item не завершён дважды, run.finished_at стабилен', snap_all() == _after1)
check('J5. удержание снято максимум один раз (повтор не роняет)', 'pr1' not in HOLDS)

# ══ K. Десять одновременных подтверждений ═════════════════════════════════════════════════════
mk(items=ONE, jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
_res, _lk = [], threading.Lock()
_bar = threading.Barrier(10)


def _race():
    _bar.wait()
    try:
        r = confirm()
    except Exception as e:
        r = {'status': 'exception', 'reason': str(e)}
    with _lk:
        _res.append(r.get('status'))


_th = [threading.Thread(target=_race) for _ in range(10)]
[t.start() for t in _th]
[t.join() for t in _th]
check('K1. ни один поток не упал с исключением', 'exception' not in _res)
check('K2. КРИТИЧНО: 10 одновременных подтверждений -> РОВНО одна строка разрешения', nclr() == 1)
check('K3. КРИТИЧНО: успех ровно у одного, остальные получили контролируемый отказ',
      _res.count('ok') == 1 and _res.count('error') == 9)
check('K4. item завершён один раз, run завершён один раз',
      istate('it_1') == 'completed' and rstate()[0] == 'completed')
check('K5. удержание снято', 'pr1' not in HOLDS)

# ══ L. Рестарт и повтор ═══════════════════════════════════════════════════════════════════════
mk(items=ONE, jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
confirm()
_a = snap_all()
wire('boot_B')                                        # ══ ПЕРЕЗАПУСК ══
po.recover_on_start()
check('L1. рестарт не воскрешает завершённый run и не трогает завершённый item',
      rstate()[0] == 'completed' and istate('it_1') == 'completed')
check('L2. повторное подтверждение после рестарта безопасно',
      confirm().get('status') in ('ok', 'error') and nclr() == 1)
check('L3. удержания завершённого run после rebuild не появляется', 'pr1' not in po.active_holds())
wire('boot_A')

# ══ M-N. Телеметрия ═══════════════════════════════════════════════════════════════════════════
mk(items=ONE, jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
confirm()
_a = snap_all()
po.on_printer_finished('pr1', 'plate.3mf', 'pjob_1')
po.on_printer_finished('pr1', 'plate.3mf', 'pjob_1')
check('M1. повторные FINISH после завершения ничего не меняют', snap_all() == _a)
mk(items=(('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1'), ('it_2', 2, 'pending', '', '')), jobs=JOB1)
SAFE['pr1'] = ('FINISH', 'FINISH', False)
_a = snap_all()
po.on_printer_finished('pr1', 'чужое.3mf', '')        # внешняя печать без нашего задания
check('N1. внешний/ручной FINISH чужого файла НЕ завершает наш item', snap_all() == _a)
check('N2. и не создаёт разрешение (телеметрия токен не создаёт НИКОГДА)', po.active_clearance('pr1') is None)

# ══ Ни одного вызова печати ═══════════════════════════════════════════════════════════════════
_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _MOD))
check('Z1. предохранитель выключен', po.DISPATCH_ENABLED is False)
check('Z2. /start по-прежнему 409',
      po.start_run('prun_1') == {"status": "error", "reason": "project_orchestrator_dispatch_disabled"})
check('Z3. production scheduler по-прежнему ничего не делает',
      po.scheduler_tick() == {"status": "disabled", "reason": "project_orchestrator_dispatch_disabled",
                              "leased": 0, "dispatched": 0})
_cc = _MOD[_MOD.index('def create_clearance'):_MOD.index('def revoke_clearance')]
_cc_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _cc))
check('Z4. подтверждение не зовёт планировщик/резервацию/транспорт',
      not re.search(r'_scheduler_tick_core|scheduler_tick|reserve|_lease_item_tx|_send|mqtt|ftp'
                    r'|_do_project2_file_print|create_project_print_job|finish_project_print_job', _cc_code))
check('Z5. КРИТИЧНО: удержание снимается ТОЛЬКО после COMMIT и только по owner-match',
      'clear_hold' in _cc_code and _cc_code.index('commit()') < _cc_code.index('clear_hold'))
check('Z6. в модуле по-прежнему нет транспорта',
      not re.search(r'_send_mgr|paho|\bmqtt|ftplib|requests|socket|_do_project2_file_print'
                    r'|_send_file_to_printer|create_project_print_job|\bafter_dispatch\b|inv_ledger', _code))
check('Z7. НИ ОДНОГО вызова печати за весь тест: BOOM=%r' % (BOOM,), BOOM == [])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: подтверждение «Стол очищен» завершает item и — если он был последним — весь run, '
              'снимая удержание по owner-match; при остатке item\'ов разрешение остаётся действующим, '
              'удержание сохраняется, а следующий item НЕ запускается; paused/cancelled/attention '
              'обрабатываются по своим правилам; повторы и 10 одновременных подтверждений дают ровно '
              'одну строку и одно завершение; количества деталей 5A4 не трогает вовсе'))
raise SystemExit(1 if fail else 0)
