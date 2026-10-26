# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Первая печать плана — Alpha 2.752: первичное «Стол очищен» + controlled start из draft.
# ЗАЧЕМ. Репетиция 2.751 упёрлась в два дефекта, блокировавших ПЕРВУЮ реальную печать:
#   (1) кнопка «Стол очищен» существовала только для waiting_plate_clear + assigned_printer_id,
#       а перед первой печатью item ещё pending/eligible и принтер не присвоен -> подтвердить пустой
#       стол было НЕЧЕМ, и /start закономерно получал no_active_clearance;
#   (2) run после «Сохранить план» остаётся draft, а start_item_controlled требовал RUN_RUNNING —
#       отдельного корректного перехода draft->running не существовало.
# Здесь доказываются ОБА исправления и их границы: safe_idle авторитетен для первичного
# подтверждения (но НЕ для постпечатного), confirmed — только литеральный true, активация run
# атомарна с lease+consume clearance, фоновому scheduler активация ЗАПРЕЩЕНА.
# server.py НЕ импортируется (боевой DATA_DIR); DDL выскабливается из текста.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_first_print_gate.py   (0 = пройдено)
import importlib.util, json, os, re, sqlite3, tempfile, threading, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
_APPJS = open(os.path.join(REPO, 'web', 'app.js'), encoding='utf-8').read()
_INDEX = open(os.path.join(REPO, 'web', 'index.html'), encoding='utf-8').read()
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

fail = 0


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


# ══ Стенд: временная БД ═══════════════════════════════════════════════════════════════════════
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','plate.3mf','h1',1)")
c.commit()

LOCK = threading.Lock()
HOLDS, RESV = {}, {}
MGR = threading.Lock()
_seq = [0]
DISPATCHES = []
# Управляемый снимок безопасности: (status, status_raw, fresh, printing_active, safe_idle)
SAFE = {'pr1': ('IDLE', 'IDLE', True, False, True)}


def SAFETY(pid):
    st, raw, fresh, active, idle = SAFE.get(pid, ('OFFLINE', '', False, True, False))
    return {"printer_id": pid, "transport": "flashforge", "status": st, "status_raw": raw,
            "fresh": fresh, "user_stopped_pending": False, "printing_active": active,
            "safe_idle": idle, "unsafe_reason": '' if idle else ('not_idle_raw:' + (raw or 'OFFLINE'))}


def A_reserve(pid, ot, oid):
    with MGR:
        if pid in RESV:
            return (False, None, 'busy')
        _seq[0] += 1
        RESV[pid] = 'send_%d' % _seq[0]
        return (True, RESV[pid], '')


def A_cancel(sjid):
    with MGR:
        for k, v in list(RESV.items()):
            if v == sjid:
                del RESV[k]
                return True
        return False


def A_set_hold(pid, ot, oid, reason):
    with MGR:
        HOLDS[pid] = {"printer_id": pid, "owner_type": ot, "owner_id": oid, "reason": reason}
        return (True, dict(HOLDS[pid]))


def A_clear_hold(pid, ot, oid):
    with MGR:
        if pid in HOLDS:
            del HOLDS[pid]
            return True
        return False


def A_dispatch(payload):
    DISPATCHES.append(dict(payload))
    # РОВНО форма ответа production-адаптера: status='accepted' + command_sent + project_print_job_id.
    return {"status": "accepted", "command_sent": True, "project_print_job_id": "pjob_new"}


PLAN = {}


def A_build(run_id, item_id, printer_id):
    p = dict(PLAN.get(printer_id) or {})
    p.update({"run_id": run_id, "item_id": item_id, "printer_id": printer_id})
    return p


po.init(c, LOCK, lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: (SAFE.get(pid, ('OFFLINE',))[0], True), safety_fn=SAFETY,
        printers_fn=lambda: [{"id": "pr1", "name": "FF", "type": "flashforge", "order_idx": 0}],
        send_reserved_fn=lambda: set(RESV), file_ok_fn=lambda f: True,
        holds_fn=lambda: dict(HOLDS), set_hold_fn=A_set_hold, clear_hold_fn=A_clear_hold,
        file_requirements_fn=lambda fr: {"status": "ok", "filament_count": 1, "file_hash": "h1",
                                         "filaments": [{"file_index": 0, "material": "PETG",
                                                        "color_hex": "#161616"}]},
        filament_snapshot_fn=lambda pid: {}, reported_filament_fn=lambda pid: {})
po.init_db()
COMPAT = lambda f: ['pr1']

ADAPTERS = {"list_printers": lambda: [{"id": "pr1", "name": "FF", "type": "flashforge", "order_idx": 0}],
            "safety_snapshot": SAFETY, "compatibility_check": COMPAT,
            "build_feed_plan": A_build, "persist_feed_plan": po.persist_feed_plan,
            "reserve_printer": A_reserve, "cancel_reserved": A_cancel,
            "set_hold": A_set_hold, "clear_hold": A_clear_hold, "dispatch": A_dispatch}

# Предохранители — только на своём объекте модуля в тест-процессе (штатный приём всех 5B-тестов).
po.DISPATCH_ENABLED = True
po.TRANSPORT_ENABLED = True
po.ALLOWED_PRINTER_IDS = frozenset({'pr1'})


def mk_plan(pid='pr1'):
    return {"version": 1, "status": "ready", "reason": "", "project_id": "prj", "run_id": "prun_1",
            "item_id": "it_1", "file_id": "F1", "file_hash": "h1", "printer_id": pid,
            "transport": "flashforge", "filament_count": 1, "ams_slot": -1, "mode": "external",
            "spool_id": "", "inventory_bound": False, "required_material": "PETG",
            "inventory_material": None, "reported_material": None, "required_color": "#161616",
            "inventory_color": None, "reported_color": None, "color_distance": None,
            "color_relation": "unknown", "verification": "manual_external",
            "required_approval_reasons": ["manual_external"],
            "approval": {"by": "op", "at": 1.0, "fingerprint": "", "reasons": ["manual_external"]},
            "built_at": 1.0}


def reset(run_state='draft', item_state='pending', clr=False, items=None, jobs=()):
    with LOCK:
        for t in ('project_runs', 'project_run_items', 'plate_clearances', 'project_print_jobs'):
            c.execute("DELETE FROM " + t)
        c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, "
                  "print_opts_json, created_at, updated_at) VALUES "
                  "('prun_1','prj',?,'exact',?,'{}',1.0,111.5)", (run_state, po._ctx['boot']))
        for jid, pid, st in jobs:
            # counted_at обязателен: незасчитанный job не завершает item (_completion_context).
            c.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, "
                      "file_norm, snapshot_json, status, counted_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (jid, 'prj', 'F1', pid, 'plate.3mf', 'plate3mf', '[]', st, '2024-01-01 10:00:00'))
        for iid, seq, st, apid, pjob in (items or ((('it_1', 1, item_state, '', '')),)) if items else [('it_1', 1, item_state, '', '')]:
            c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
                      "assigned_printer_id, project_print_job_id, created_at, updated_at) "
                      "VALUES (?,?,?,?,?,?,?,?,1.0,222.25)", (iid, 'prun_1', 'prj', 'F1', seq, st, apid, pjob))
        c.commit()
    HOLDS.clear(); RESV.clear(); DISPATCHES.clear(); PLAN.clear()
    SAFE['pr1'] = ('IDLE', 'IDLE', True, False, True)
    PLAN['pr1'] = mk_plan()
    for row in (items or [('it_1',)]):
        if str(row[2] if len(row) > 2 else 'pending') in ('pending', 'eligible'):
            po.persist_feed_plan(row[0], 'prun_1', PLAN['pr1'])
    if clr:
        with LOCK:
            c.execute("INSERT INTO plate_clearances (id, printer_id, confirmed_at, nonce, boot_id) "
                      "VALUES ('clr_1','pr1',1.0,'n',?)", (po._ctx['boot'],))
            c.commit()


def rstate():
    with LOCK:
        return c.execute("SELECT state FROM project_runs WHERE id='prun_1'").fetchone()["state"]


def snap():
    with LOCK:
        rows = {t: [tuple(repr(v) for v in r) for r in c.execute("SELECT * FROM " + t).fetchall()]
                for t in ('project_runs', 'project_run_items', 'plate_clearances', 'project_print_jobs')}
    return json.dumps(rows, sort_keys=True)


def fresh_start(**kw):
    with LOCK:
        r = c.execute("SELECT updated_at FROM project_runs WHERE id='prun_1'").fetchone()
        i = c.execute("SELECT updated_at FROM project_run_items WHERE id='it_1'").fetchone()
    saved = po.read_feed_plan('it_1')
    args = {"expected_run_updated_at": r["updated_at"], "expected_item_updated_at": i["updated_at"],
            "expected_feed_fingerprint": (saved or {}).get("fingerprint") or "x"}
    args.update(kw)
    return po.start_item_controlled('prun_1', 'it_1', confirmed=True, adapters=ADAPTERS, **args)


# ══ A. Первичное «Стол очищен» (create_clearance без finished_job_id) ═════════════════════════
reset()
r = po.create_clearance('pr1', confirmed=True, run_id='prun_1', compat_fn=COMPAT)
check('A1. fresh + safe_idle -> первичное подтверждение СОЗДАЁТСЯ', r.get('status') == 'ok')

reset(); SAFE['pr1'] = ('IDLE', 'IDLE', False, False, False)
check('A2. устаревшая телеметрия -> первичное НЕ создаётся (telemetry_stale)',
      po.create_clearance('pr1', confirmed=True, run_id='prun_1', compat_fn=COMPAT)['reason'] == 'telemetry_stale')

reset(); SAFE['pr1'] = ('RUNNING', 'RUNNING', True, True, False)
check('A3. доказанно идущая печать -> первичное НЕ создаётся (printer_busy)',
      po.create_clearance('pr1', confirmed=True, run_id='prun_1', compat_fn=COMPAT)['reason'] == 'printer_busy')

reset(); SAFE['pr1'] = ('FINISH', 'FINISH', True, False, False)
r = po.create_clearance('pr1', confirmed=True, run_id='prun_1', compat_fn=COMPAT)
check('A4. КРИТИЧНО: не safe_idle (FINISH) -> ПЕРВИЧНОЕ подтверждение отбито авторитетно backend-ом',
      r.get('reason') == 'printer_unsafe' and 'not_idle_raw:FINISH' in (r.get('unsafe_reason') or ''))
with LOCK:
    _n = c.execute("SELECT COUNT(*) n FROM plate_clearances").fetchone()["n"]
check('A4b. и токен при этом НЕ записан в БД', _n == 0)

reset()
for junk in ("true", 1, "yes", [], {"x": 1}, "True"):
    rr = po.create_clearance('pr1', confirmed=junk, run_id='prun_1', compat_fn=COMPAT)
    check('A5. confirmed=' + repr(junk) + ' (truthy, но НЕ литеральный true) -> отказ',
          rr.get('reason') == 'confirmation_required')

# Постпечатное подтверждение (FINISH, finished_job_id) обязано РАБОТАТЬ без safe_idle — как раньше.
reset(run_state='running', items=[('it_1', 1, 'waiting_plate_clear', 'pr1', 'pjob_1')],
      jobs=[('pjob_1', 'pr1', 'finished')])
SAFE['pr1'] = ('FINISH', 'FINISH', True, False, False)
r = po.create_clearance('pr1', confirmed=True, finished_job_id='pjob_1', run_id='prun_1', compat_fn=COMPAT)
check('A6. КРИТИЧНО: постпечатное подтверждение на FINISH (НЕ safe_idle) по-прежнему создаётся',
      r.get('status') == 'ok')

# Статика server.py: роут принимает только литеральный true и телеметрия clearance не создаёт.
check('A7. КРИТИЧНО: роут plate-clear передаёт confirmed=(... is True), а не bool(...)',
      "confirmed=(d.get(\"confirmed\") is True)" in _SRV
      and "confirmed=bool(d.get(\"confirmed\"))" not in _SRV)
_srv_code = re.sub(r'#.*', '', _SRV)
#  16.09.2026: вызовов стало ДВА, и оба — явные действия человека: кнопка «Стол очищен» в
#  проектном запуске и она же в очереди ожидания (автозапуск печати без подтверждения не идёт).
#  Смысл проверки прежний и даже строже: считаем вызовы И убеждаемся, что оба стоят в обработчиках
#  маршрутов plate-clear. Телеметрия, воркеры и автозапуск жетонов по-прежнему не создают.
_clr_calls = len(re.findall(r'create_clearance\(', _srv_code))
_clr_routes = len(re.findall(r'_orch\.create_clearance\(', _srv_code))
check('A8. create_clearance зовётся из server.py РОВНО дважды — из двух роутов plate-clear '
      '(проектного и очереди); телеметрия, воркеры и автозапуск токенов не создают',
      _clr_calls == 2 and _clr_routes == 2
      and 'def whole_print_plate_clear(' in _SRV and 'def api_printer_plate_clear(' in _SRV
      and _SRV.count('post_print=') == 1)

# ══ B. Controlled start из draft ══════════════════════════════════════════════════════════════
reset(run_state='draft', clr=True)
r = fresh_start()
check('B1. КРИТИЧНО: draft + свежие версии + READY план + active clearance -> ровно один accepted',
      r.get('status') == 'ok' and len(DISPATCHES) == 1)
check('B1b. КРИТИЧНО: run стал running (активация в одной транзакции с lease)', rstate() == 'running')

reset(run_state='waiting_for_printer', clr=True)
r = fresh_start()
check('B2. waiting_for_printer стартует так же', r.get('status') == 'ok' and rstate() == 'running')

reset(run_state='draft', clr=False)
before = snap()
r = fresh_start()
check('B3. КРИТИЧНО: draft БЕЗ clearance -> отказ no_active_clearance, run ОСТАЛСЯ draft, БД не тронута',
      r.get('reason') == 'no_active_clearance' and rstate() == 'draft'
      and snap() == before and DISPATCHES == [] and not RESV and not HOLDS)

for st in ('paused', 'waiting_for_plate_clear', 'attention_required', 'completed', 'cancelled'):
    reset(run_state=st, clr=True)
    r = fresh_start()
    check('B4. run=' + st + ' -> controlled start ЗАКРЫТ (run_not_running), состояние не изменилось',
          r.get('reason') == 'run_not_running' and rstate() == st and DISPATCHES == [])

# Прямая атомарность: отказ ВНУТРИ транзакции (несуществующий clearance) откатывает и активацию.
reset(run_state='draft', clr=True)
lok, lreason, _n = po._lease_item_tx('prun_1', 'it_1', 'pr1', po.read_feed_plan('it_1'),
                                     'clr_НЕ_СУЩЕСТВУЕТ', 'send_x', activate_run=True)
check('B5. КРИТИЧНО: отказ внутри lease-транзакции (чужой clearance_id) -> run остался draft',
      lok is False and lreason == 'no_active_clearance' and rstate() == 'draft')

# Scheduler НЕ активирует draft: и напрямую (default activate_run=False), и целым тиком.
reset(run_state='draft', clr=True)
lok, lreason, _n = po._lease_item_tx('prun_1', 'it_1', 'pr1', po.read_feed_plan('it_1'),
                                     'clr_1', 'send_x')
check('B6. КРИТИЧНО: _lease_item_tx БЕЗ activate_run на draft -> run_not_running, run остался draft',
      lok is False and lreason == 'run_not_running' and rstate() == 'draft')
reset(run_state='draft', clr=True)
tick = po._scheduler_tick_core({"now": None}, dict(ADAPTERS, mock_dispatch=A_dispatch))
check('B7. КРИТИЧНО: целый scheduler-тик пропускает draft run (skipped run_not_running), lease=0',
      tick.get('leased') == 0 and rstate() == 'draft' and DISPATCHES == []
      and any(d.get('reason') == 'run_not_running' for d in tick.get('decisions') or []))

# Один и тот же вызов должен по-прежнему работать для УЖЕ running (регрессия 5B1-пути).
reset(run_state='running', clr=True)
r = fresh_start()
check('B8. running-путь не сломан: accepted, run остался running',
      r.get('status') == 'ok' and rstate() == 'running')

# ══ C. UI: первичная цель и её гейты (статика по НАСТОЯЩИМ web-файлам) ═══════════════════════
_targets = _APPJS[_APPJS.index('const projectRunClearanceTargets = (r) => {'):]
_targets = _targets[:_targets.index('\n    };') + 7]
check('C1. первичная цель строится из pending/eligible + СОХРАНЁННОГО ready-плана',
      "['pending', 'eligible'].includes(it.state)" in _targets
      and "fp.effective_status !== 'ready'" in _targets)
check('C2. КРИТИЧНО: используется именно feed_plan.printer_id (не догадка по совместимости)',
      'byId[fp.printer_id]' in _targets and 'initial: true' in _targets)
check('C3. КРИТИЧНО: не больше одной цели на принтер, постпечатная (waiting_plate_clear) добавляется ПЕРВОЙ',
      'used.has(p.printer_id)' in _targets
      and _targets.index("it.state !== 'waiting_plate_clear'") < _targets.index("['pending', 'eligible']"))
_can = _APPJS[_APPJS.index('const clearanceCanConfirm = (t) =>'):]
_can = _can[:_can.index(';') + 1]
check('C4. КРИТИЧНО: кнопка первичного подтверждения требует telemetry_fresh И safe_idle',
      'telemetry_fresh' in _can and "(!t.initial || !!t.printer.safe_idle)" in _can)
check('C5. при unsafe показывается ТОЧНАЯ причина (unsafe_reason), а не общее слово',
      't.initial && !t.printer.safe_idle' in _APPJS and 't.printer.unsafe_reason' in _APPJS)
check('C6. отдельный текст перед первой печатью присутствует в разметке (2.754: ветка need-initial)',
      'Перед первой печатью физически проверьте, что стол пуст. Только человек может это подтвердить.' in _INDEX
      and "kind==='need-initial'" in _INDEX)
check('C7. кнопка называется «Стол очищен» и шлёт confirmed:true + finished_job_id цели',
      'Стол очищен' in _INDEX
      and re.search(r"\{ confirmed: true, finished_job_id: t\.finished_job_id \}", _APPJS))
check('C8. постпечатная цель не изменилась: waiting_plate_clear + assigned_printer_id + project_print_job_id',
      "it.state !== 'waiting_plate_clear' || !it.assigned_printer_id" in _targets
      and "finished_job_id: it.project_print_job_id || ''" in _targets)

print('\nПРОВАЛЕНО: ' + str(fail) if fail else
      '\nВСЁ ЗЕЛЁНОЕ: первичное «Стол очищен» существует и требует fresh+safe_idle (авторитетно в '
      'backend), постпечатное на FINISH не сломано, confirmed — только литеральный true; controlled '
      'start начинает run из draft/waiting_for_printer атомарно с lease+consume, любой отказ '
      'оставляет draft и БД нетронутыми, фоновому scheduler активация запрещена.')
raise SystemExit(1 if fail else 0)
