# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Точечный запуск ОДНОГО item на ОДИН принтер через настоящий печатный путь — Alpha 2.747 (5B1).
# ЗАЧЕМ. Это первая выдача, где оркестратор ФАКТИЧЕСКИ дотягивается до production transport.
# Поэтому доказываем не «работает», а «по умолчанию недостижимо и не может навредить»:
#   • три независимых серверных предохранителя, все выключены/пусты по умолчанию;
#   • их нельзя включить телом запроса/query/cookie — только серверной конфигурацией;
#   • один HTTP-запрос = максимум один item на одном принтере, без таймеров и автоповтора;
#   • adopt-путь зовётся РОВНО один раз, с точным ams_slot из feed_plan_json;
#   • сеть (MQTT/FTP/HTTP) заменена bomb: доказываем ПАРАМЕТРЫ вызова, а не факт отправки.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_controlled_transport.py   (0 = пройдено)
import importlib.util, json, os, re, sqlite3, tempfile, threading, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
_MOD = open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

fail = 0
BOOM = []          # любой запрещённый вызов (реальная сеть/транспорт/второе задание)
CALLS = []         # вызовы adopt-пути: полные kwargs


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def bomb(tag):
    def _b(*a, **k):
        BOOM.append(tag)
        raise AssertionError('ЗАПРЕЩЕНО в 5B1: ' + tag)
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

LOCK = threading.Lock()
HOLDS, RESV = {}, {}
MGR = threading.Lock()
SAFE = {'pr1': True, 'pr2': True}
_seq = [0]
DISPATCH_RESULT = [None]     # что «вернёт» adopt-путь (мокаем его границу)


def SAFETY(pid):
    ok = bool(SAFE.get(pid))
    return {"printer_id": pid, "transport": "bambu", "status": "IDLE" if ok else "RUNNING",
            "status_raw": "IDLE" if ok else "RUNNING", "fresh": True, "user_stopped_pending": False,
            "printing_active": not ok, "safe_idle": ok, "unsafe_reason": "" if ok else "not_idle_raw:RUNNING"}


def A_reserve(pid, ot, oid):
    with MGR:
        h = HOLDS.get(pid)
        if h and (h['owner_type'], h['owner_id']) != (ot, oid):
            return (False, None, 'printer_held')
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
        h = HOLDS.get(pid)
        if h and (h['owner_type'], h['owner_id']) != (ot, oid):
            return (False, dict(h))
        HOLDS[pid] = {"printer_id": pid, "owner_type": ot, "owner_id": oid, "reason": reason}
        return (True, dict(HOLDS[pid]))


def A_clear_hold(pid, ot, oid):
    with MGR:
        h = HOLDS.get(pid)
        if not h or (h['owner_type'], h['owner_id']) != (ot, oid):
            return False
        del HOLDS[pid]
        return True


PLAN = {}


def A_build(run_id, item_id, printer_id):
    p = dict(PLAN.get(printer_id) or {})
    p.update({"run_id": run_id, "item_id": item_id, "printer_id": printer_id})
    return p


# ── ТОЧНАЯ ГРАНИЦА: production-адаптер ядра, но _do_project2_file_print замокан ────────────────
NS = {'asyncio': None, 'lock_p': LOCK, 'conn_p': c, '_jsonmod': json, 'main_loop': None,
      '_orch': po, '_send_mgr': None,
      '_do_project2_file_print': bomb('_do_project2_file_print (должен зваться через мок границы)')}


def _exec_block(start, end, ns):
    i = _SRV.index(start)
    exec(_SRV[i:_SRV.index(end, i)], ns)


_exec_block('def _orch_run_print_opts(', 'def _orch_prod_dispatch(', NS)
# _orch_prod_dispatch зовёт корутину через run_coroutine_threadsafe — в тесте подменяем ровно этот
# мост, чтобы поймать ФАКТИЧЕСКИЕ kwargs, с которыми ядро идёт в существующий печатный путь.
_DISPATCH_SRC = _SRV[_SRV.index('def _orch_prod_dispatch('):_SRV.index('def _orch_prod_adapters(')]


class _FakeFut:
    def __init__(self, v):
        self._v = v

    def result(self):
        if isinstance(self._v, Exception):
            raise self._v
        return self._v


def _fake_print(*a, **k):
    CALLS.append({"args": a, "kwargs": k})
    return DISPATCH_RESULT[0]


NS2 = dict(NS)
NS2['_do_project2_file_print'] = _fake_print
# Alpha 2.748: адаптер расходует одноразовое вооружение на своей границе. Этот тест — про семантику
# 5B1, поэтому вооружение здесь всегда «есть» (его собственные правила проверяет
# tools/test_project_transport_arm.py). Возвращаем canonical (ok, reason).
ARM_OK = [True]
NS2['_one_shot_arm_consume'] = lambda r, i, p: ((True, '') if ARM_OK[0] else (False, 'one_shot_already_used'))
# Alpha 2.757: _orch_prod_dispatch расходует вооружение ТОЛЬКО когда печать из приложения выключена.
# Этот тест — про CLI-путь (5B1), поэтому «печать из приложения» здесь выключена -> идёт расход arm.
NS2['_project_print_enabled'] = lambda: False
NS2['asyncio'] = type('A', (), {'run_coroutine_threadsafe': staticmethod(lambda coro, loop: _FakeFut(coro))})()
exec(_DISPATCH_SRC, NS2)
PROD_DISPATCH = NS2['_orch_prod_dispatch']


def wire(boot='boot_A'):
    po.init(c, LOCK, lambda p: p + uuid.uuid4().hex[:10], boot,
            printer_status_fn=lambda pid: ("IDLE", True), safety_fn=SAFETY,
            printers_fn=lambda: [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0},
                                 {"id": "pr2", "name": "B", "type": "bambu", "order_idx": 1}],
            send_reserved_fn=lambda: set(RESV), file_ok_fn=lambda f: True,
            holds_fn=lambda: dict(HOLDS), set_hold_fn=A_set_hold, clear_hold_fn=A_clear_hold,
            file_requirements_fn=lambda fr: {"status": "ok", "filament_count": 1, "file_hash": "h1",
                                             "filaments": [{"file_index": 0, "material": "PETG", "color_hex": "#161616"}]},
            filament_snapshot_fn=lambda pid: {}, reported_filament_fn=lambda pid: {})


wire()
po.init_db()
ADAPTERS = {"list_printers": lambda: [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}],
            "safety_snapshot": SAFETY, "compatibility_check": lambda fr: ['pr1', 'pr2'],
            "build_feed_plan": A_build, "persist_feed_plan": po.persist_feed_plan,
            "reserve_printer": A_reserve, "cancel_reserved": A_cancel,
            "set_hold": A_set_hold, "clear_hold": A_clear_hold, "dispatch": PROD_DISPATCH}


def mk_plan(pid='pr1', slot=0, spool='sp_0'):
    return {"version": 1, "status": "ready", "reason": "", "project_id": "prj", "run_id": "prun_1",
            "item_id": "it_1", "file_id": "F1", "file_hash": "h1", "printer_id": pid, "transport": "bambu",
            "filament_count": 1, "ams_slot": slot, "mode": "external" if slot == -1 else "ams",
            "spool_id": spool, "inventory_bound": True, "required_material": "PETG",
            "inventory_material": "PETG", "reported_material": "PETG", "required_color": "#161616",
            "inventory_color": "#161616", "reported_color": "#161616", "color_distance": 0.0,
            "color_relation": "exact", "verification": "telemetry_confirmed",
            "required_approval_reasons": [], "requires_approval": False, "approval": None, "built_at": 1.0}


def reset(slot=0, items=(('it_1', 1, 'pending'),), run_state='running', clr=True, printer='pr1', plan=None):
    with LOCK:
        c.execute("DELETE FROM project_runs"); c.execute("DELETE FROM project_run_items")
        c.execute("DELETE FROM plate_clearances"); c.execute("DELETE FROM project_print_jobs")
        c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, print_opts_json, "
                  "created_at, updated_at) VALUES ('prun_1','prj',?,'exact',?,'{}',1.0,1.0)",
                  (run_state, po._ctx['boot']))
        for iid, seq, st in items:
            c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
                      "created_at, updated_at) VALUES (?,'prun_1','prj','F1',?,?,1.0,1.0)", (iid, seq, st))
        c.commit()
    HOLDS.clear(); RESV.clear(); CALLS.clear(); PLAN.clear()
    SAFE['pr1'] = SAFE['pr2'] = True
    PLAN[printer] = plan if plan is not None else mk_plan(printer, slot)
    for iid, _s, _st in items:
        po.persist_feed_plan(iid, 'prun_1', PLAN[printer])
    if clr:
        with LOCK:
            c.execute("INSERT INTO plate_clearances (id, printer_id, confirmed_at, nonce, boot_id) "
                      "VALUES (?,?,1.0,'n',?)", ('clr_' + uuid.uuid4().hex[:6], printer, po._ctx['boot']))
            c.commit()
    DISPATCH_RESULT[0] = {"status": "ok", "pjob_id": "pjob_1"}


def start(item='it_1', confirmed=True, **kw):
    """Alpha 2.749: expected_* стали ОБЯЗАТЕЛЬНЫМИ (fail-closed). По умолчанию подставляем СВЕЖИЕ
    canonical-значения — ровно те, что UI берёт из detail-снимка. Так все проверки ниже не только
    продолжают работать, но и проходят через настоящий optimistic-lock, а не мимо него.
    Сценарии про устаревший экран передают своё значение явно (kw перекрывает)."""
    with LOCK:
        r = c.execute("SELECT updated_at FROM project_runs WHERE id='prun_1'").fetchone()
        i = c.execute("SELECT updated_at FROM project_run_items WHERE id=?", (item,)).fetchone()
    saved = po.read_feed_plan(item)
    fresh = {"expected_run_updated_at": r["updated_at"] if r else 0.0,
             "expected_item_updated_at": i["updated_at"] if i else 0.0,
             "expected_feed_fingerprint": (saved or {}).get("fingerprint") or "x"}
    fresh.update(kw)
    return po.start_item_controlled('prun_1', item, confirmed=confirmed, adapters=ADAPTERS, **fresh)


def istate(iid='it_1'):
    with LOCK:
        r = c.execute("SELECT state FROM project_run_items WHERE id=?", (iid,)).fetchone()
    return r["state"] if r else None


def db_snap():
    out = {}
    with LOCK:
        for t in [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            out[t] = [tuple(repr(v) for v in r) for r in c.execute("SELECT * FROM %s" % t).fetchall()]
    return out


def clr_consumed():
    with LOCK:
        r = c.execute("SELECT consumed_at FROM plate_clearances").fetchone()
    return r and r["consumed_at"] is not None


def enable(printers=('pr1',)):
    po.DISPATCH_ENABLED = True
    po.TRANSPORT_ENABLED = True
    po.ALLOWED_PRINTER_IDS = frozenset(printers)


def disable():
    po.DISPATCH_ENABLED = False
    po.TRANSPORT_ENABLED = False
    po.ALLOWED_PRINTER_IDS = frozenset()


# ══ A-D. Предохранители по умолчанию ══════════════════════════════════════════════════════════
disable(); reset()
_before = db_snap()
r = start()
check('A1. по умолчанию /start-сервис отказывает предохранителем dispatch',
      r['status'] == 'error' and r['reason'] == 'project_orchestrator_dispatch_disabled' and r['http'] == 409)
check('A2. КРИТИЧНО: 0 reservation, 0 hold, 0 вызовов печатного пути',
      RESV == {} and HOLDS == {} and CALLS == [])
check('A3. КРИТИЧНО: БД не изменилась ни на байт', db_snap() == _before)
check('A4. разрешение не потрачено', not clr_consumed())

po.DISPATCH_ENABLED = True; po.TRANSPORT_ENABLED = False; po.ALLOWED_PRINTER_IDS = frozenset()
reset(); _before = db_snap()
r = start()
check('B1. dispatch включён, но transport выключен -> отказ', r['reason'] == 'project_orchestrator_transport_disabled')
check('B2. 0 побочных эффектов', RESV == {} and HOLDS == {} and CALLS == [] and db_snap() == _before)

po.TRANSPORT_ENABLED = True; po.ALLOWED_PRINTER_IDS = frozenset()
reset(); _before = db_snap()
r = start()
check('B3. оба флага включены, но allowlist ПУСТ -> отказ', r['reason'] == 'printer_not_allowlisted')
check('B4. 0 побочных эффектов', RESV == {} and HOLDS == {} and CALLS == [] and db_snap() == _before)

po.ALLOWED_PRINTER_IDS = frozenset({'pr2'})
reset(); _before = db_snap()
r = start()
check('C1. принтер плана НЕ в allowlist -> отказ', r['reason'] == 'printer_not_allowlisted')
check('C2. 0 побочных эффектов', RESV == {} and HOLDS == {} and CALLS == [] and db_snap() == _before)

enable()
for _cf in (False, None, 1, "yes", "true", 0):
    reset(); _b = db_snap()
    r = start(confirmed=_cf)
    check('D.%r confirmed=%r -> отказ confirmation_required, 0 эффектов' % (_cf, _cf),
          r['reason'] == 'confirmation_required' and r['http'] == 400
          and CALLS == [] and RESV == {} and db_snap() == _b)

# ══ E. Устаревшие ожидания ════════════════════════════════════════════════════════════════════
enable(); reset(); _b = db_snap()
r = start(expected_run_updated_at=999.0)
check('E1. устаревший run_updated_at -> отказ ДО reservation/транспорта',
      r['reason'] == 'run_stale' and CALLS == [] and RESV == {} and db_snap() == _b)
reset(); _b = db_snap()
r = start(expected_item_updated_at=999.0)
check('E2. устаревший item_updated_at -> отказ', r['reason'] == 'item_stale' and CALLS == [] and db_snap() == _b)
reset(); _b = db_snap()
r = start(expected_feed_fingerprint='ЧУЖОЙ')
check('E3. устаревший отпечаток плана -> отказ',
      r['reason'] == 'feed_plan_stale' and CALLS == [] and RESV == {} and db_snap() == _b)
reset(run_state='paused'); _b = db_snap()
check('E4. run не running -> отказ', start()['reason'] == 'run_not_running' and CALLS == [])
reset(items=(('it_1', 1, 'printing'),)); _b = db_snap()
check('E5. item уже активен -> отказ', start()['reason'] == 'item_not_leasable' and CALLS == [])

# ══ F-H. Полный fresh gate ════════════════════════════════════════════════════════════════════
reset(); SAFE['pr1'] = False; _b = db_snap()
r = start()
check('F1. принтер небезопасен (raw не IDLE) -> отказ до транспорта',
      r['reason'] == 'printer_unsafe' and CALLS == [] and RESV == {} and db_snap() == _b)
reset(clr=False); _b = db_snap()
r = start()
check('G1. нет действующего подтверждения «Стол очищен» -> отказ',
      r['reason'] == 'no_active_clearance' and CALLS == [] and db_snap() == _b)
for _bad, _lbl in ((dict(status='attention_required', reason='inventory_source_unavailable'), 'attention'),
                   (dict(status='blocked', reason='material_mismatch'), 'blocked'),
                   (dict(status='approval_required', reason='close_color',
                         required_approval_reasons=['close_color'], requires_approval=True), 'approval_required'),
                   (dict(ams_slot=None), 'Auto/None'),
                   (dict(filament_count=2), 'multi-filament')):
    reset(plan=dict(mk_plan(), **_bad))
    _b = db_snap()
    r = start()
    check('H.%s план «%s» -> отказ, 0 вызовов транспорта' % (_lbl, _lbl),
          r['status'] == 'error' and CALLS == [] and RESV == {} and not clr_consumed())

# ══ I-J. Слот доходит до печатного пути БЕЗ искажения ═════════════════════════════════════════
for _slot, _lbl in ((-1, 'external -1'), (0, 'AMS0'), (5, 'multi-AMS5'), (512, 'AMS HT512')):
    reset(slot=_slot)
    r = start()
    check('I-J.%s запуск принят' % _lbl, r['status'] == 'ok' and r['accepted'] is True)
    check('I-J.%s КРИТИЧНО: adopt-путь получил РОВНО %s' % (_lbl, _slot),
          len(CALLS) == 1 and CALLS[0]['kwargs']['ams_slot'] == _slot
          and isinstance(CALLS[0]['kwargs']['ams_slot'], int))

# ══ K-L. Ровно один job / один send-job / один adopt ══════════════════════════════════════════
reset()
r = start()
k = CALLS[0]['kwargs']
check('K1. КРИТИЧНО: adopt-путь вызван РОВНО один раз', len(CALLS) == 1)
check('K2. КРИТИЧНО: _from_queue=True — задание создаёт САМ путь (второго нет) и reserve не вложен',
      k['_from_queue'] is True)
check('K3. КРИТИЧНО: адоптируется НАША reservation (вложенного reserve нет)',
      k['_send_job_id'] == 'send_%d' % _seq[0] and k['_send_job_id'] in RESV.values())
check('K4. owner-bypass передан: план проходит СВОЙ hold',
      k['hold_owner_type'] == 'project_run' and k['hold_owner_id'] == 'prun_1')
check('K5. project_print_job СВОИМ кодом не создаётся — id приходит из adopt-пути',
      c.execute("SELECT COUNT(*) n FROM project_print_jobs").fetchone()['n'] == 0
      and c.execute("SELECT project_print_job_id FROM project_run_items WHERE id='it_1'").fetchone()[0] == 'pjob_1')
check('K6. позиционные аргументы — project/file/printer из БД, а не из запроса',
      CALLS[0]['args'] == ('prj', 'F1', 'pr1'))
check('L1. print_opts — только из canonical серверного источника (project_runs.print_opts_json)',
      k['print_opts'] == {})
check('L2. force/skip_filament НЕ передаются: compat и хуки склада работают штатно (один after_dispatch)',
      'force' not in k and 'skip_filament' not in k)
_pd = _SRV[_SRV.index('def _orch_prod_dispatch('):_SRV.index('def _orch_prod_adapters(')]
# Комментарии снимаем ОБЯЗАТЕЛЬНО: в них _send_file_to_printer и FTP упомянуты намеренно (объясняют
# цепочку), и без этого проверка падает на собственном объяснении.
_pd_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _pd))
check('L3. статика: адаптер не трогает MQTT/FTP/HTTP и не создаёт задание сам',
      not re.search(r'mqtt|ftplib|storbinary|urllib|requests|create_project_print_job|_send_file_to_printer', _pd_code)
      and '_do_project2_file_print(' in _pd_code)   # зовёт РОВНО существующий adopt-путь
check('L4. статика: оркестратор по-прежнему без транспорта',
      not re.search(r'_send_mgr|paho|\bmqtt|ftplib|_do_project2_file_print|_send_file_to_printer'
                    r'|create_project_print_job', re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _MOD))))

# ══ O. accepted НЕ означает «печать пошла» ════════════════════════════════════════════════════
reset()
r = start()
check('O1. КРИТИЧНО: после accepted item = waiting_start_confirmation, а НЕ printing',
      istate() == 'waiting_start_confirmation')
check('O2. ответ не утверждает, что печать началась',
      r['result'] == 'accepted_awaiting_start_confirmation' and 'started' not in json.dumps(r).lower())
check('O3. hold остаётся, разрешение потреблено', 'pr1' in HOLDS and clr_consumed())
po.on_printer_started('pr1', 'plate.3mf', 'pjob_1')
check('O4. в printing переводит ТОЛЬКО телеметрия', istate() == 'printing')

# ══ P-Q. Классификация результата ═════════════════════════════════════════════════════════════
reset()
DISPATCH_RESULT[0] = {"status": "error", "reason": "printer_send_busy", "pjob_id": ""}
r = start()
# Alpha 2.769 (аудит): доказанный отказ больше НЕ хоронит деталь — она возвращается в ОЧЕРЕДЬ
# (pending), а run не заклинивает в attention_required (прежний тупик: retry не существовало,
# оператор отменял весь план). Повтор — только явной кнопкой (P2 ниже это и доказывает).
check('P1. ДОКАЗАННЫЙ отказ до отправки -> деталь ВОЗВРАЩЕНА В ОЧЕРЕДЬ (pending), hold снят',
      istate() == 'pending' and 'pr1' not in HOLDS and RESV == {}
      and c.execute("SELECT state FROM project_runs WHERE id='prun_1'").fetchone()[0] != 'attention_required')
check('P2. автоповтора нет: повторный запуск того же item не идёт в транспорт',
      (len(CALLS) == 1) and (start()['status'] == 'error') and len(CALLS) == 1)

for _res, _lbl in (({"status": "error", "reason": "Error starting print: boom"}, 'сбой на полпути'),
                   (RuntimeError('таймаут'), 'исключение/таймаут'),
                   ("не dict", 'неизвестный ответ')):
    reset()
    DISPATCH_RESULT[0] = _res
    r = start()
    check('Q.%s -> ambiguous, run attention, hold ОСТАЁТСЯ' % _lbl,
          istate() == 'ambiguous_after_dispatch' and 'pr1' in HOLDS
          and c.execute("SELECT state FROM project_runs WHERE id='prun_1'").fetchone()[0] == 'attention_required')
    check('Q.%s: разрешение потреблено, автоповтора нет' % _lbl,
          clr_consumed() and start()['status'] == 'error')

# ══ R. Повтор после accepted/ambiguous ════════════════════════════════════════════════════════
reset()
start()
_n = len(CALLS)
r2 = start()
check('R1. КРИТИЧНО: повтор после accepted -> 0 новых вызовов транспорта',
      len(CALLS) == _n and r2['status'] == 'error' and r2['reason'] == 'item_not_leasable')

# ══ M. Десять одновременных запусков ══════════════════════════════════════════════════════════
reset()
_res, _lk = [], threading.Lock()
_bar = threading.Barrier(10)


def _race():
    _bar.wait()
    try:
        r = start()
    except Exception as e:
        r = {'status': 'exception', 'reason': str(e)}
    with _lk:
        _res.append(r.get('status'))


_th = [threading.Thread(target=_race) for _ in range(10)]
[t.start() for t in _th]
[t.join() for t in _th]
check('M1. ни один поток не упал', 'exception' not in _res)
check('M2. КРИТИЧНО: 10 одновременных запусков -> РОВНО один вызов печатного пути', len(CALLS) == 1)
check('M3. КРИТИЧНО: ровно один успех, остальные — контролируемый отказ', _res.count('ok') == 1)
check('M4. разрешение потреблено ровно один раз, item в единственном валидном состоянии',
      clr_consumed() and istate() == 'waiting_start_confirmation')
check('M5. на принтере ровно один активный item',
      c.execute("SELECT COUNT(*) n FROM project_run_items WHERE assigned_printer_id='pr1' AND state IN "
                "('leased','sending','waiting_start_confirmation','printing','waiting_plate_clear')").fetchone()['n'] == 1)

# ══ N. Ручной старт против точечного ══════════════════════════════════════════════════════════
_mw, _sw = 0, 0
for _i in range(8):
    reset()
    _out, _lk2 = [], threading.Lock()
    _b2 = threading.Barrier(2)

    def _manual():
        _b2.wait()
        with MGR:                                  # ручной старт — БЕЗ owner, как upload_print/part_print
            if 'pr1' in HOLDS or 'pr1' in RESV:
                r = False
            else:
                RESV['pr1'] = 'manual'; r = True
        with _lk2:
            _out.append(('manual', r))

    def _ctl():
        _b2.wait()
        r = start()
        with _lk2:
            _out.append(('ctl', r.get('status') == 'ok'))

    t1, t2 = threading.Thread(target=_manual), threading.Thread(target=_ctl)
    t1.start(); t2.start(); t1.join(); t2.join()
    won = [x[0] for x in _out if x[1]]
    if won == ['manual']:
        _mw += 1
        check('N.%d ручной победил -> точечный запуск БД не изменил и в транспорт не пошёл' % _i,
              istate() == 'pending' and not clr_consumed() and CALLS == [])
    elif won == ['ctl']:
        _sw += 1
        check('N.%d точечный победил -> ручной получил отказ' % _i,
              istate() == 'waiting_start_confirmation' and len(CALLS) == 1)
    else:
        check('N.%d КРИТИЧНО: победил РОВНО один (%r)' % (_i, _out), False)
check('N9. за 8 раундов всегда побеждал ровно один (ручной=%d, точечный=%d)' % (_mw, _sw), _mw + _sw == 8)

# ══ U. Обратный порядок парка не меняет targeted-результат ════════════════════════════════════
reset()
ADAPTERS['list_printers'] = lambda: [{"id": "pr2", "name": "B", "type": "bambu", "order_idx": 1},
                                     {"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}]
r = start()
check('U1. цель задана явно: обратный порядок парка на результат не влияет',
      r['status'] == 'ok' and CALLS[0]['args'][2] == 'pr1' and len(CALLS) == 1)
ADAPTERS['list_printers'] = lambda: [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}]

# ══ S. FINISH не освобождает принтер; «Стол очищен» применяет 5A4 ═════════════════════════════
reset()
start()
po.on_printer_started('pr1', 'plate.3mf', 'pjob_1')
with LOCK:
    c.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, file_norm, "
              "snapshot_json, status, counted_at) VALUES ('pjob_1','prj','F1','pr1','plate.3mf','plate3mf',"
              "'[]','finished','2024-01-01 10:00:00')")
    c.commit()
po.on_printer_finished('pr1', 'plate.3mf', 'pjob_1')
check('S1. FINISH -> waiting_plate_clear, принтер НЕ освобождён', istate() == 'waiting_plate_clear' and 'pr1' in HOLDS)
SAFE['pr1'] = True
r = po.create_clearance('pr1', confirmed=True, finished_job_id='pjob_1', confirmed_by='op',
                        run_id='prun_1', compat_fn=lambda f: ['pr1'])
check('S2. подтверждение «Стол очищен» завершает item и run по логике 5A4 и освобождает принтер',
      r['status'] == 'ok' and istate() == 'completed' and 'pr1' not in HOLDS
      and c.execute("SELECT state FROM project_runs WHERE id='prun_1'").fetchone()[0] == 'completed')

# ══ T. Рестарт не повторяет отправку ══════════════════════════════════════════════════════════
reset()
start()
_n = len(CALLS)
wire('boot_B')
rec = po.recover_on_start()
check('T1. КРИТИЧНО: рестарт НЕ повторяет отправку', len(CALLS) == _n)
check('T2. незавершённая отправка после рестарта -> ambiguous (решает человек)',
      istate() == 'ambiguous_after_dispatch')
wire('boot_A')

# ══ V. Секретов наружу нет ════════════════════════════════════════════════════════════════════
reset()
r = start()
_j = json.dumps(r, ensure_ascii=False, default=str)
check('V1. ответ без токенов/паролей/ip/абсолютных путей/содержимого файла',
      not re.search(r'(?i)token|password|access|bblp|\d+\.\d+\.\d+\.\d+|[A-Za-z]:\\\\|/mnt/|stored_path|PK\x03', _j))

# ══ Z. Итоговые границы ═══════════════════════════════════════════════════════════════════════
disable()
check('Z1. КРИТИЧНО: предохранители возвращены в безопасное состояние',
      po.DISPATCH_ENABLED is False and po.TRANSPORT_ENABLED is False and po.ALLOWED_PRINTER_IDS == frozenset())
reset(); _b = db_snap()
check('Z2. и /start снова недостижим: 409 + БД не тронута',
      start()['reason'] == 'project_orchestrator_dispatch_disabled' and db_snap() == _b and CALLS == [])
check('Z3. значения ПО УМОЛЧАНИЮ в файле — выключено и пусто (а не только в рантайме)',
      re.search(r'^TRANSPORT_ENABLED = False$', _MOD, re.M)
      and re.search(r'^ALLOWED_PRINTER_IDS = frozenset\(\)$', _MOD, re.M)
      and re.search(r'^DISPATCH_ENABLED = False$', _MOD, re.M))
# Имена полей — ТОЧНЫЕ: подстрока «allow» ловила легитимный d.get("allow_overproduction")
# (согласие на перепроизводство), к предохранителям отношения не имеющий.
# Alpha 2.748/2.757: рантайм-включение приходит из ДВУХ функций — CLI-вооружение (_one_shot_boot_arm)
# и явный персистентный переключатель владельца (_apply_project_print_fuses, из настройки). Вне этих
# двух функций server.py предохранителей не присваивает, и тело /start их не трогает.
_arm_fn = _SRV[_SRV.index('def _one_shot_boot_arm('):_SRV.index('def _one_shot_expired(')]
_fuse_fn = _SRV[_SRV.index('def _apply_project_print_fuses('):_SRV.index('@app.post("/api/project-orchestrator/print-enabled")')]
_srv_wo_arm = _SRV.replace(_arm_fn, '').replace(_fuse_fn, '')
_start_route = _SRV[_SRV.index('async def whole_print_start('):_SRV.index('async def whole_print_plate_clear(')]
check('Z4. КРИТИЧНО: флаги включаются лишь в двух функциях; тело /start (и query/cookie) их не включает',
      not re.search(r'_orch\.(?:TRANSPORT_ENABLED|DISPATCH_ENABLED|ALLOWED_PRINTER_IDS)\s*=', _srv_wo_arm)
      and not re.search(r'os\.environ|getenv', _arm_fn)      # и не из окружения
      and not re.search(r'd\.get\(["\'](?:enabled|transport_enabled|dispatch_enabled|'
                        r'allowed_printer_ids|allowlist|printer_ids|armed|arm|phrase)["\']', _start_route)
      and not re.search(r'(?:query_params|cookies)\.get\(["\'](?:enabled|transport|dispatch|allow)', _SRV))
check('Z5. роут не принимает printer_id/ams_slot/spool_id как авторитетные',
      not re.search(r'_orch\.start_item_controlled\([^)]*printer_id\s*=\s*str\(d\.get', _SRV)
      and 'printer_id/ams_slot/spool_id берутся из сохранённого feed_plan_json' in _SRV)
check('Z6. точечный запуск не создаёт таймеров/воркеров',
      not re.search(r'Thread|Timer|setInterval|while True',
                    _MOD[_MOD.index('def start_item_controlled'):_MOD.index('def _apply_dispatch_result')]))
# ── Alpha 2.759: САМОБЛОКИРОВКА ЦИКЛА СОБЫТИЙ (баг, из-за которого печать не стартовала НИКОГДА) ──
# start_item_controlled СИНХРОННАЯ, и внутри неё _orch_prod_dispatch ставит корутину отправки в event
# loop через run_coroutine_threadsafe и БЛОКИРУЮЩЕ ждёт fut.result(). Если звать её прямо из async-роута
# (то есть в самом цикле), корутина отправки попадает в тот же цикл, который её и заблокировал: она не
# выполнится никогда -> команда на принтер не уходит, а сервер виснет намертво (0% CPU, ни HTTP, ни
# опроса принтеров). Поймано на живой ферме трассировкой стеков. Блокирующая работа обязана уходить
# из цикла в поток — иначе баг возвращается молча.
check('Z6b. КРИТИЧНО: блокирующий start_item_controlled НЕ вызывается прямо в event loop (уносится в поток)',
      re.search(r'await\s+asyncio\.to_thread\(\s*_orch\.start_item_controlled', _start_route)
      and not re.search(r'^\s*r\s*=\s*_orch\.start_item_controlled\(', _start_route, re.M))
_dispatch_fn = _SRV[_SRV.index('def _orch_prod_dispatch('):]
_dispatch_fn = _dispatch_fn[:_dispatch_fn.index('\ndef ', 1)]
check('Z6c. при этом dispatch по-прежнему ждёт РЕАЛЬНЫЙ результат отправки (не «выстрелил и забыл»)',
      'fut.result()' in _dispatch_fn and 'run_coroutine_threadsafe' in _dispatch_fn)

check('Z7. НИ ОДНОГО запрещённого вызова за весь тест: BOOM=%r' % (BOOM,), BOOM == [])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: по умолчанию реальный транспорт НЕДОСТИЖИМ (три серверных предохранителя, БД '
              'байт-в-байт), включить их из запроса нельзя; один запрос = максимум один item на одном '
              'принтере; adopt-путь зовётся ровно один раз с точным ams_slot и canonical print_opts, '
              'без вложенного reserve и без второго задания; accepted не означает «печать пошла»; '
              'сомнение -> ambiguous с сохранением hold; 10 одновременных запусков дают один вызов'))
raise SystemExit(1 if fail else 0)
