# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Mocked scheduler + атомарный lease — core Alpha 2.743 (этап 5A2b).
# ЗАЧЕМ. Это первый код, который САМ решает «печатать вот это вот здесь». Поэтому доказываем не
# «работает», а «не может навредить»: production-вход при выключенном предохранителе не делает
# НИЧЕГО; ядро выполняется только с явно переданными fake-адаптерами (настоящего transport-адаптера
# не существует); разрешение расходуется ровно один раз; принтер удерживается; ни один реальный
# вызов печати не происходит.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_orchestrator_scheduler.py  (0 = пройдено)
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
        raise AssertionError('ЗАПРЕЩЕНО в 5A2b: ' + tag)
    return _b


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


# ══ Стенд ══════════════════════════════════════════════════════════════════════════════════════
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','plate.3mf','h1',1)")
c.commit()

# LOCK — настоящий lock ядра. Через него доказываем, что adapter вызывается БЕЗ удержанного лока.
LOCK = threading.Lock()

FLEET = [{"id": "pr1", "name": "X1C", "type": "bambu", "order_idx": 0}]
SAFE = {"pr1": True}
COMPAT = {"pr1"}
FEED = {}          # printer_id -> план (или callable)
HOLDS = {}
RESV = {}
CALLS = []         # журнал вызовов адаптеров: (имя, lock_держится?)
DISPATCH_RESULT = [{"status": "accepted", "project_print_job_id": "pjob_1", "command_sent": False}]
_seq = [0]


def _lock_held():
    """True, если lock_p кем-то удерживается (в однопоточном тесте — нами)."""
    if LOCK.acquire(blocking=False):
        LOCK.release()
        return False
    return True


def SAFETY(pid):
    ok = bool(SAFE.get(pid))
    return {"printer_id": pid, "transport": "bambu", "status": "IDLE" if ok else "RUNNING",
            "status_raw": "IDLE" if ok else "RUNNING", "fresh": True, "user_stopped_pending": False,
            "printing_active": not ok, "safe_idle": ok, "unsafe_reason": "" if ok else "not_idle_raw:RUNNING"}


def wire(boot='boot_A'):
    po.init(c, LOCK, lambda p: p + uuid.uuid4().hex[:10], boot,
            printer_status_fn=lambda pid: ("IDLE", True), safety_fn=SAFETY,
            printers_fn=lambda: FLEET, send_reserved_fn=lambda: set(RESV), file_ok_fn=lambda f: True,
            file_requirements_fn=bomb('file_requirements (builder подменён fake-адаптером)'),
            filament_snapshot_fn=lambda pid: {}, reported_filament_fn=lambda pid: {})


wire()
po.init_db()


def mk_plan(pid, status='ready', slot=0, count=1, spool='sp_0', approval=None):
    return {"version": 1, "status": status, "reason": '' if status == 'ready' else 'close_color',
            "project_id": "prj", "run_id": "prun_1", "item_id": "it_1", "file_id": "F1",
            "file_hash": "h1", "printer_id": pid, "transport": "bambu", "filament_count": count,
            "ams_slot": slot, "mode": "external" if slot == -1 else "ams", "spool_id": spool,
            "inventory_bound": True, "required_material": "PETG", "inventory_material": "PETG",
            "reported_material": "PETG", "required_color": "#161616", "inventory_color": "#161616",
            "reported_color": "#161616", "color_distance": 0.0, "color_relation": "exact",
            "verification": "telemetry_confirmed", "requires_approval": status != 'ready',
            "approval": approval, "built_at": 1.0}


# ── Адаптеры: ТОЛЬКО fake. Настоящего transport-адаптера в 5A2b не существует ──────────────────
def A_build_feed_plan(run_id, item_id, printer_id):
    CALLS.append(('build_feed_plan', _lock_held()))
    v = FEED.get(printer_id)
    if callable(v):
        v = v(run_id, item_id, printer_id)
    return dict(v or mk_plan(printer_id), run_id=run_id, item_id=item_id, printer_id=printer_id)


def A_persist(item_id, run_id, plan):
    CALLS.append(('persist_feed_plan', _lock_held()))
    return po.persist_feed_plan(item_id, run_id, plan)


def A_reserve(pid, owner_type, owner_id):
    CALLS.append(('reserve_printer', _lock_held()))
    h = HOLDS.get(pid)
    if h and (h['owner_type'], h['owner_id']) != (owner_type, owner_id):
        return (False, None, 'printer_held')
    if pid in RESV:
        return (False, None, 'busy')
    _seq[0] += 1
    jid = 'send_%d' % _seq[0]
    RESV[pid] = jid
    return (True, jid, '')


def A_cancel(sjid):
    CALLS.append(('cancel_reserved', _lock_held()))
    for k, v in list(RESV.items()):
        if v == sjid:
            del RESV[k]
            return True
    return False


def A_set_hold(pid, ot, oid, reason):
    CALLS.append(('set_hold', _lock_held()))
    h = HOLDS.get(pid)
    if h and (h['owner_type'], h['owner_id']) != (ot, oid):
        return (False, dict(h))
    HOLDS[pid] = {"printer_id": pid, "owner_type": ot, "owner_id": oid, "reason": reason}
    return (True, dict(HOLDS[pid]))


def A_clear_hold(pid, ot, oid):
    CALLS.append(('clear_hold', _lock_held()))
    h = HOLDS.get(pid)
    if not h or (h['owner_type'], h['owner_id']) != (ot, oid):
        return False
    del HOLDS[pid]
    return True


def A_dispatch(payload):
    CALLS.append(('mock_dispatch', _lock_held()))
    r = DISPATCH_RESULT[0]
    if isinstance(r, Exception):
        raise r
    if callable(r):
        return r(payload)
    return dict(r)


ADAPTERS = {"list_printers": lambda: list(FLEET), "safety_snapshot": SAFETY,
            "compatibility_check": lambda frow: set(COMPAT), "build_feed_plan": A_build_feed_plan,
            "persist_feed_plan": A_persist, "reserve_printer": A_reserve, "cancel_reserved": A_cancel,
            "set_hold": A_set_hold, "clear_hold": A_clear_hold, "mock_dispatch": A_dispatch}


def reset(item_state='pending', run_state='running', items=(('it_1', 1, 'F1'),), printers=('pr1',)):
    c.execute("DELETE FROM project_runs"); c.execute("DELETE FROM project_run_items")
    c.execute("DELETE FROM plate_clearances")
    c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
              "VALUES ('prun_1','prj',?,'exact',?,1.0,1.0)", (run_state, po._ctx['boot']))
    for iid, seq, fid in items:
        c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, created_at, updated_at) "
                  "VALUES (?,'prun_1','prj',?,?,?,1.0,1.0)", (iid, fid, seq, item_state))
    c.commit()
    HOLDS.clear(); RESV.clear(); CALLS.clear()
    FEED.clear()
    for pid in printers:
        FEED[pid] = mk_plan(pid)
        SAFE[pid] = True


def clearance(pid='pr1'):
    cid = 'clr_' + uuid.uuid4().hex[:8]
    c.execute("INSERT INTO plate_clearances (id, printer_id, confirmed_at, nonce, boot_id) VALUES (?,?,?,?,?)",
              (cid, pid, 1.0, 'n', po._ctx['boot']))
    c.commit()
    return cid


def tick():
    return po._scheduler_tick_core({}, ADAPTERS)


def istate(iid='it_1'):
    return c.execute("SELECT state FROM project_run_items WHERE id=?", (iid,)).fetchone()["state"]


def rstate():
    return c.execute("SELECT state FROM project_runs WHERE id='prun_1'").fetchone()["state"]


def clr_row(cid):
    return dict(c.execute("SELECT * FROM plate_clearances WHERE id=?", (cid,)).fetchone())


def db_snap():
    out = {}
    for t in [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        out[t] = [tuple(repr(v) for v in r) for r in c.execute("SELECT * FROM %s" % t).fetchall()]
    return out


# ══ S1. PRODUCTION-вход при выключенном предохранителе ═════════════════════════════════════════
reset(); clearance()
_before = db_snap()
r = po.scheduler_tick()
check('S1a. production scheduler_tick -> disabled, 0 leased, 0 dispatched',
      r == {"status": "disabled", "reason": "project_orchestrator_dispatch_disabled", "leased": 0, "dispatched": 0})
check('S1b. КРИТИЧНО: ни одной reservation/hold/вызова адаптера', RESV == {} and HOLDS == {} and CALLS == [])
check('S1c. КРИТИЧНО: БД не изменилась ни на байт', db_snap() == _before)
check('S1d. и разрешение не потрачено', istate() == 'pending')
check('S1e. предохранитель на месте', po.DISPATCH_ENABLED is False)
check('S1f. /start по-прежнему 409',
      po.start_run('prun_1') == {"status": "error", "reason": "project_orchestrator_dispatch_disabled"})

# ══ S2. Штатный путь: один run/item/printer ═══════════════════════════════════════════════════
reset(); cid = clearance()
DISPATCH_RESULT[0] = {"status": "accepted", "project_print_job_id": "pjob_1", "command_sent": False}
r = tick()
check('S2a. ровно один lease и один dispatch', r['leased'] == 1 and r['dispatched'] == 1)
check('S2b. разрешение потреблено РОВНО один раз и именно этим item\'ом',
      clr_row(cid)['consumed_at'] is not None and clr_row(cid)['consumed_by_item_id'] == 'it_1')
check('S2c. принтер удержан этим run', HOLDS.get('pr1', {}).get('owner_id') == 'prun_1')
check('S2d. adapter вызван ровно один раз', [x[0] for x in CALLS].count('mock_dispatch') == 1)
_it = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
check('S2e. lease записан полностью: принтер/nonce/boot/срок/clearance/send_job/attempt',
      _it['assigned_printer_id'] == 'pr1' and _it['lease_nonce'] and _it['lease_boot_id'] == po._ctx['boot']
      and _it['lease_acquired_at'] and _it['lease_expires_at'] > _it['lease_acquired_at']
      and _it['clearance_id'] == cid and _it['send_job_id'] == RESV.get('pr1') and _it['attempt'] == 1)
check('S2f. item -> waiting_start_confirmation, pjob привязан',
      _it['state'] == 'waiting_start_confirmation' and _it['project_print_job_id'] == 'pjob_1')
check('S2g. command_sent=0 (команда ещё не подтверждена)', _it['command_sent'] == 0)
check('S2h. scheduler НЕ создаёт project_print_job сам',
      c.execute("SELECT COUNT(*) n FROM project_print_jobs").fetchone()['n'] == 0)

# ══ S3-S5, S7, S8. Отказы до lease ════════════════════════════════════════════════════════════
reset()                       # разрешения НЕТ
r = tick()
check('S3. нет разрешения -> 0 lease, 0 reservation (IDLE пустой стол не доказывает)',
      r['leased'] == 0 and RESV == {} and istate() == 'pending'
      and any(d['reason'] == 'no_active_clearance' for d in r['decisions']))

reset(); clearance(); SAFE['pr1'] = False
r = tick()
check('S4. принтер небезопасен -> 0 lease, 0 reservation',
      r['leased'] == 0 and RESV == {} and any(d['reason'] == 'printer_unsafe' for d in r['decisions']))

reset(); cid = clearance()
FEED['pr1'] = mk_plan('pr1', status='approval_required')
r = tick()
check('S5a. approval_required БЕЗ согласия -> 0 lease', r['leased'] == 0 and RESV == {})
check('S5b. разрешение НЕ потрачено', clr_row(cid)['consumed_at'] is None)
check('S5c. причина названа', any(d['reason'] == 'feed_plan_not_ready' for d in r['decisions']))
check('S5d. план всё равно сохранён — оператору есть что увидеть',
      po.read_feed_plan('it_1')['status'] == 'approval_required')

reset(); clearance()
FEED['pr1'] = mk_plan('pr1', count=2)
r = tick()
check('S7. multi-filament -> 0 lease', r['leased'] == 0 and RESV == {})

reset(); clearance()
FEED['pr1'] = mk_plan('pr1', status='attention_required')
r = tick()
check('S8. нет складского источника (attention) -> 0 lease', r['leased'] == 0 and RESV == {})

reset(); clearance()
FEED['pr1'] = mk_plan('pr1', slot=None)
r = tick()
check('S8b. Auto/None (ams_slot=None) -> 0 lease НИКОГДА', r['leased'] == 0 and RESV == {})

# ══ S6. Валидное согласие -> dispatch ═════════════════════════════════════════════════════════
reset(); cid = clearance()
_p = mk_plan('pr1', status='approval_required')
_ap = po.approve_feed_plan(_p, approved_by='оператор', now=5.0)
check('S6a. согласие принято и делает план ready', _ap['status'] == 'ok'
      and po.feed_plan_effective_status(_ap['plan']) == 'ready')
po.persist_feed_plan('it_1', 'prun_1', _ap['plan'])       # согласие живёт в сохранённом плане
FEED['pr1'] = mk_plan('pr1', status='approval_required')   # builder пересчитывает БЕЗ согласия
DISPATCH_RESULT[0] = {"status": "accepted", "project_print_job_id": "pjob_6", "command_sent": False}
r = tick()
check('S6b. КРИТИЧНО: согласие перенесено на пересчитанный план -> lease состоялся',
      r['leased'] == 1 and r['dispatched'] == 1 and istate() == 'waiting_start_confirmation')
check('S6c. исходный статус плана НЕ переписан (почему было спорно — видно)',
      po.read_feed_plan('it_1')['status'] == 'approval_required'
      and po.read_feed_plan('it_1')['effective_status'] == 'ready')

reset(); cid = clearance()
_p2 = dict(_ap['plan'], spool_id='sp_ДРУГАЯ')            # факты изменились
po.persist_feed_plan('it_1', 'prun_1', _p2)
FEED['pr1'] = mk_plan('pr1', status='approval_required', spool='sp_ДРУГАЯ')
r = tick()
check('S6d. согласие с ЧУЖИМ отпечатком не действует -> 0 lease',
      r['leased'] == 0 and clr_row(cid)['consumed_at'] is None)

# ══ S9, S10. Слоты сохраняются точно ══════════════════════════════════════════════════════════
for _slot, _label in ((-1, 'external -1'), (0, 'AMS0'), (5, 'multi-AMS5'), (512, 'AMS HT512')):
    reset(); clearance()
    FEED['pr1'] = mk_plan('pr1', slot=_slot)
    _got = {}
    DISPATCH_RESULT[0] = lambda pl, _g=_got: (_g.update(pl), {"status": "accepted",
                                                              "project_print_job_id": "pjob_s",
                                                              "command_sent": False})[1]
    r = tick()
    check('S9-S10.%s слот доходит до adapter БЕЗ искажения (%s)' % (_label, _slot),
          r['dispatched'] == 1 and _got.get('ams_slot') == _slot
          and _got.get('mode') == ('external' if _slot == -1 else 'ams'))

# ══ S11. paused/cancelled run ═════════════════════════════════════════════════════════════════
for _rs in ('paused', 'cancelled', 'attention_required', 'draft'):
    reset(run_state=_rs); cid = clearance()
    _b = db_snap()
    r = tick()
    check('S11.%s run в состоянии «%s» -> 0 lease, 0 reservation, БД не тронута' % (_rs, _rs),
          r['leased'] == 0 and RESV == {} and db_snap() == _b)

# ══ S12, S13. Удержания ═══════════════════════════════════════════════════════════════════════
reset(); cid = clearance()
HOLDS['pr1'] = {"printer_id": "pr1", "owner_type": "project_run", "owner_id": "prun_ЧУЖОЙ", "reason": "x"}
r = tick()
check('S12a. ЧУЖОЙ hold -> reservation отказана, 0 lease', r['leased'] == 0 and RESV == {})
check('S12b. разрешение не потрачено', clr_row(cid)['consumed_at'] is None)
check('S12c. чужой hold не тронут', HOLDS['pr1']['owner_id'] == 'prun_ЧУЖОЙ')

reset(); cid = clearance()
HOLDS['pr1'] = {"printer_id": "pr1", "owner_type": "project_run", "owner_id": "prun_1", "reason": "свой"}
DISPATCH_RESULT[0] = {"status": "accepted", "project_print_job_id": "pjob_13", "command_sent": False}
r = tick()
check('S13a. hold СВОЕГО run -> owner-bypass, lease состоялся', r['leased'] == 1 and r['dispatched'] == 1)
check('S13b. hold при этом НЕ снят и остался за тем же run',
      HOLDS.get('pr1', {}).get('owner_id') == 'prun_1')

# ══ S14, S15. Изменение мира между precheck и lease ═══════════════════════════════════════════
reset(); cid = clearance()
_flip = {'n': 0}


def _safety_flip(pid):
    """Первый вызов (precheck) — безопасно; после reservation — уже нет."""
    _flip['n'] += 1
    ok = _flip['n'] <= 1
    return {"printer_id": pid, "transport": "bambu", "status": "IDLE", "status_raw": "IDLE" if ok else "RUNNING",
            "fresh": True, "user_stopped_pending": False, "printing_active": not ok,
            "safe_idle": ok, "unsafe_reason": "" if ok else "not_idle_raw:RUNNING"}


ADAPTERS['safety_snapshot'] = _safety_flip
r = tick()
check('S14a. КРИТИЧНО: safety изменился ПОСЛЕ reservation -> lease не взят', r['leased'] == 0)
check('S14b. reservation отдана (cancel_reserved вызван)',
      RESV == {} and 'cancel_reserved' in [x[0] for x in CALLS])
check('S14c. КРИТИЧНО: разрешение НЕ потрачено', clr_row(cid)['consumed_at'] is None)
check('S14d. item остался pending', istate() == 'pending')
ADAPTERS['safety_snapshot'] = SAFETY

reset(); cid = clearance()
_fp = {'n': 0}


def _feed_flip(run_id, item_id, printer_id):
    """Второй вызов (после reservation) даёт ДРУГУЮ катушку — отпечаток разъехался."""
    _fp['n'] += 1
    return mk_plan(printer_id, spool='sp_0' if _fp['n'] <= 1 else 'sp_ДРУГАЯ')


FEED['pr1'] = _feed_flip
r = tick()
check('S15a. КРИТИЧНО: отпечаток плана изменился после reservation -> lease не взят', r['leased'] == 0)
check('S15b. reservation отдана', RESV == {})
check('S15c. разрешение НЕ потрачено', clr_row(cid)['consumed_at'] is None)
check('S15d. причина названа', any(d['reason'] == 'changed_after_reservation' for d in r['decisions']))

# ══ S16, S17. Гонки на уровне БД ══════════════════════════════════════════════════════════════
reset(); cid = clearance()
c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
          "assigned_printer_id, created_at, updated_at) "
          "VALUES ('it_other','prun_1','prj','F1',9,'printing','pr1',1.0,1.0)")
c.commit()
r = tick()
check('S16a. на принтере уже активный item -> lease не взят', r['leased'] == 0)
check('S16b. reservation отдана, разрешение цело', RESV == {} and clr_row(cid)['consumed_at'] is None)

reset(); cid = clearance()
c.execute("UPDATE plate_clearances SET consumed_at=1.0 WHERE id=?", (cid,))   # уже потрачено
c.commit()
r = tick()
check('S17a. разрешение уже потреблено -> lease не взят (rowcount=0 -> rollback)', r['leased'] == 0)
check('S17b. reservation отдана', RESV == {})
check('S17c. item остался pending, lease не записан',
      istate() == 'pending' and not c.execute("SELECT assigned_printer_id FROM project_run_items "
                                              "WHERE id='it_1'").fetchone()[0])

# ══ S18. set_hold не удался ═══════════════════════════════════════════════════════════════════
reset(); cid = clearance()
ADAPTERS['set_hold'] = lambda pid, ot, oid, reason: (False, None)
r = tick()
check('S18a. КРИТИЧНО: не удержали принтер -> adapter НЕ вызывается (отправлять нельзя)',
      'mock_dispatch' not in [x[0] for x in CALLS])
# 2.769: доказанный отказ -> деталь в очередь, run без тупика (см. reconcile_run_state)
check('S18b. item ВОЗВРАЩЁН В ОЧЕРЕДЬ (pending), run НЕ заклинен в attention',
      istate() == 'pending' and rstate() != 'attention_required')
check('S18c. reservation отдана', RESV == {})
check('S18d. разрешение ОСТАЁТСЯ потреблённым (доказательства пустого стола больше нет)',
      clr_row(cid)['consumed_at'] is not None)
check('S18e. автоповтора нет: повторный тик item не трогает', tick()['leased'] == 0)
ADAPTERS['set_hold'] = A_set_hold

# ══ S19-S22. Результаты mock-адаптера ═════════════════════════════════════════════════════════
reset(); cid = clearance()
DISPATCH_RESULT[0] = {"status": "accepted", "send_job_id": "s1", "project_print_job_id": "pjob_19",
                      "command_sent": False}
r = tick()
_it = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
check('S19. accepted/queued -> waiting_start_confirmation, pjob сохранён, command_sent=0, hold остаётся',
      _it['state'] == 'waiting_start_confirmation' and _it['project_print_job_id'] == 'pjob_19'
      and _it['command_sent'] == 0 and 'pr1' in HOLDS)

reset(); cid = clearance()
DISPATCH_RESULT[0] = {"status": "accepted", "project_print_job_id": "pjob_20", "command_sent": True}
r = tick()
_it = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
check('S20a. accepted/command_sent -> waiting_start_confirmation, command_sent=1, hold остаётся',
      _it['state'] == 'waiting_start_confirmation' and _it['command_sent'] == 1 and 'pr1' in HOLDS)
check('S20b. КРИТИЧНО: в printing переводит ТОЛЬКО телеметрия, не scheduler', _it['state'] != 'printing')
po.on_printer_started('pr1', 'plate.3mf', 'pjob_20')
check('S20c. телеметрия перевела в printing', istate() == 'printing')

reset(); cid = clearance()
DISPATCH_RESULT[0] = {"status": "failed", "command_sent": False, "reason": "ftp_upload_failed"}
r = tick()
# 2.769: сбой ДО команды доказан -> деталь в очередь, run без тупика
check('S21a. сбой ДО команды -> деталь ВОЗВРАЩЕНА В ОЧЕРЕДЬ (pending), run НЕ заклинен',
      r['dispatched'] == 0 and istate() == 'pending' and rstate() != 'attention_required')
check('S21b. reservation отдана', RESV == {})
check('S21c. КРИТИЧНО: hold СНЯТ (доказано, что печать начаться не могла)', 'pr1' not in HOLDS)
check('S21d. разрешение остаётся потреблённым', clr_row(cid)['consumed_at'] is not None)
check('S21e. причина сохранена', c.execute("SELECT last_error FROM project_run_items WHERE id='it_1'"
                                           ).fetchone()[0] == 'ftp_upload_failed')
check('S21f. автоповтора нет', tick()['leased'] == 0)

for _res, _label in ((RuntimeError('adapter упал'), 'исключение в adapter'),
                     ({"status": "failed", "command_sent": True, "reason": "x"}, 'сбой ПОСЛЕ команды'),
                     ({"status": "accepted", "project_print_job_id": "p", "command_sent": None}, 'command_sent неизвестен'),
                     ("не dict", 'неизвестный результат')):
    reset(); cid = clearance()
    DISPATCH_RESULT[0] = _res
    r = tick()
    check('S22.%s -> ambiguous_after_dispatch, run attention, hold ОСТАЁТСЯ' % _label,
          istate() == 'ambiguous_after_dispatch' and rstate() == 'attention_required' and 'pr1' in HOLDS)
    check('S22.%s: разрешение потреблено, автоповтора нет' % _label,
          clr_row(cid)['consumed_at'] is not None and tick()['leased'] == 0)
check('S22e. выход из ambiguous — только человеком',
      po.resolve_item('prun_1', 'it_1', 'not_started')['status'] == 'ok')

# ══ S23. Дубль project_print_job ══════════════════════════════════════════════════════════════
reset(); cid = clearance()
c.execute("UPDATE project_run_items SET project_print_job_id='pjob_ЧУЖОЙ' WHERE id='it_1'")
c.commit()
DISPATCH_RESULT[0] = {"status": "accepted", "project_print_job_id": "pjob_НОВЫЙ", "command_sent": False}
r = tick()
check('S23a. КРИТИЧНО: чужой pjob НЕ перезаписан -> ambiguous',
      istate() == 'ambiguous_after_dispatch'
      and c.execute("SELECT project_print_job_id FROM project_run_items WHERE id='it_1'").fetchone()[0] == 'pjob_ЧУЖОЙ')
check('S23b. hold остаётся (могла начаться печать)', 'pr1' in HOLDS)

# ══ S24, S25. Несколько принтеров и детерминизм ═══════════════════════════════════════════════
FLEET = [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0},
         {"id": "pr2", "name": "B", "type": "bambu", "order_idx": 1}]
COMPAT = {"pr1", "pr2"}
reset(items=(('it_1', 1, 'F1'), ('it_2', 2, 'F1')), printers=('pr1', 'pr2'))
clearance('pr1'); clearance('pr2')
DISPATCH_RESULT[0] = {"status": "accepted", "project_print_job_id": "", "command_sent": False}
_pj = {'n': 0}
DISPATCH_RESULT[0] = lambda pl: (_pj.__setitem__('n', _pj['n'] + 1),
                                 {"status": "accepted", "project_print_job_id": "pjob_%d" % _pj['n'],
                                  "command_sent": False})[1]
r = tick()
check('S24a. два принтера + два item -> ДВА lease за один тик', r['leased'] == 2 and r['dispatched'] == 2)
_a = c.execute("SELECT id, assigned_printer_id FROM project_run_items ORDER BY seq").fetchall()
check('S24b. item\'ы разъехались по РАЗНЫМ принтерам',
      {r0['assigned_printer_id'] for r0 in _a} == {'pr1', 'pr2'})
check('S24c. один принтер не получил два item', len({r0['assigned_printer_id'] for r0 in _a}) == 2)
check('S25a. порядок детерминирован: seq 1 -> pr1 (order_idx 0), seq 2 -> pr2',
      _a[0]['assigned_printer_id'] == 'pr1' and _a[1]['assigned_printer_id'] == 'pr2')

reset(items=(('it_1', 1, 'F1'), ('it_2', 2, 'F1')), printers=('pr1', 'pr2'))
clearance('pr1'); clearance('pr2')
FLEET = list(reversed(FLEET))                    # обратный порядок парка
_pj['n'] = 0
r2 = tick()
_a2 = c.execute("SELECT id, assigned_printer_id FROM project_run_items ORDER BY seq").fetchall()
check('S25b. обратный порядок парка даёт ТОТ ЖЕ результат (сортировка, а не «повезло»)',
      _a2[0]['assigned_printer_id'] == 'pr1' and _a2[1]['assigned_printer_id'] == 'pr2')
FLEET = [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}]
COMPAT = {"pr1"}

# ══ S26. Один item за тик; повторный тик не шлёт второй раз ═══════════════════════════════════
reset(); clearance()
DISPATCH_RESULT[0] = {"status": "accepted", "project_print_job_id": "pjob_26", "command_sent": False}
tick()
_n1 = [x[0] for x in CALLS].count('mock_dispatch')
CALLS.clear()
r = tick()
check('S26. повторный тик после accepted НЕ вызывает второй dispatch',
      _n1 == 1 and r['dispatched'] == 0 and 'mock_dispatch' not in [x[0] for x in CALLS])

# ══ 14. Инструментирование локов ══════════════════════════════════════════════════════════════
reset(); clearance()
DISPATCH_RESULT[0] = {"status": "accepted", "project_print_job_id": "pjob_lk", "command_sent": False}
tick()
_names = [x[0] for x in CALLS]
_held = {n: h for n, h in CALLS}
check('L1. КРИТИЧНО: adapter вызывается БЕЗ удержанного lock_p', _held.get('mock_dispatch') is False)
check('L2. КРИТИЧНО: reserve_printer вызывается БЕЗ удержанного lock_p (send-manager под DB-локом — нет)',
      _held.get('reserve_printer') is False)
check('L3. set_hold вызывается БЕЗ удержанного lock_p', _held.get('set_hold') is False)
check('L4. порядок: reserve -> set_hold -> adapter',
      _names.index('reserve_printer') < _names.index('set_hold') < _names.index('mock_dispatch'))
_src = _MOD[_MOD.index('def _lease_item_tx'):_MOD.index('def _attach_pjob')]
check('L5. статика: внутри транзакции lease нет ни одного вызова адаптера/send-manager',
      not re.search(r'cancel_reserved|reserve_printer|set_hold|clear_hold|mock_dispatch|_send', _src))
_core = _MOD[_MOD.index('def _scheduler_tick_core'):_MOD.index('def _apply_dispatch_result')]
_core_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _core))
# \b перед scheduler_tick обязателен: иначе проверка ловит собственное имя _scheduler_tick_core.
check('L6. статика: в ядре тика нет sleep/потока/таймера и оно не планирует следующий тик',
      not re.search(r'sleep|Thread|Timer|asyncio|while True|\bscheduler_tick\(', _core_code))
# _orch_lock упоминается в КОММЕНТАРИИ («не вводится и почему») — проверяем исполняемый код.
_mod_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _MOD))
check('L7. глобальный _orch_lock не введён (в коде его нет; в комментарии объяснено почему)',
      '_orch_lock' not in _mod_code and '_orch_lock' in _MOD)

reset(); cid = clearance()
ADAPTERS['set_hold'] = lambda pid, ot, oid, reason: (False, None)
CALLS.clear()
tick()
check('L8. cancel_reserved вызывается ПОСЛЕ выхода из lock_p (лок не удерживается)',
      dict(CALLS).get('cancel_reserved') is False)
ADAPTERS['set_hold'] = A_set_hold

# ══ 15. Ни одного реального вызова печати ═════════════════════════════════════════════════════
_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _MOD))
check('Z1. в модуле нет реального transport/печати/создания задания',
      not re.search(r'_send_mgr|paho|\bmqtt|ftplib|requests|socket|_do_project2_file_print'
                    r'|_send_file_to_printer|create_project_print_job|\bafter_dispatch\b|inv_ledger', _code))
check('Z2. production-вход выходит по предохранителю ДО любых побочных эффектов',
      re.search(r'def scheduler_tick\(\):[\s\S]{0,600}?if not DISPATCH_ENABLED:\s*\n\s*return', _MOD) is not None)
check('Z3. mocked-ядро НЕ зарегистрировано как роут и не запускается server.py',
      '_scheduler_tick_core' not in _SRV and 'scheduler_tick' not in _SRV)
check('Z4. обхода предохранителя флагом/окружением/HTTP нет',
      not re.search(r'os\.environ|getenv|TEST_MODE|_FORCE|allow_dispatch', _code))
check('Z5. НИ ОДНОГО вызова реальной печати за весь тест: BOOM=%r' % (BOOM,), BOOM == [])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: production-вход при выключенном предохранителе не делает НИЧЕГО (0 reservation/'
              'lease/consume/hold, БД байт-в-байт); ядро выполняется только с явно переданными fake-'
              'адаптерами; lease атомарен, разрешение расходуется ровно один раз, изменение мира или '
              'отпечатка после reservation отменяет захват без трат; hold ставится после COMMIT, '
              'снимается только при доказанной невозможности печати, при неоднозначности остаётся; '
              'reserve/set_hold/adapter вызываются без DB-лока; ни одного реального вызова печати'))
raise SystemExit(1 if fail else 0)
