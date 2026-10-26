# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Конкурентность mocked scheduler — core Alpha 2.743 (этап 5A2b).
# ЗАЧЕМ. Гонки — единственный класс ошибок, который на ферме проявляется как ДВЕ печати на одном
# принтере или печать на занятый стол. Тут доказываем под НАСТОЯЩИМИ потоками (а не рассуждением):
# 10 одновременных тиков дают ровно один lease, ровно один consume разрешения и ровно один вызов
# adapter'а; ручной старт и планировщик не могут выиграть оба; два run'а не делят принтер.
# Все адаптеры — fake. Настоящего transport-адаптера в 5A2b не существует.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_orchestrator_scheduler_concurrency.py
import importlib.util, os, re, sqlite3, tempfile, threading, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
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


# ══ Стенд: настоящая sqlite + настоящие потоки ════════════════════════════════════════════════
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','plate.3mf','h1',1)")
# Второй проект нужен для C4: активный run на проект может быть ТОЛЬКО один (idx_pruns_active),
# поэтому «два run'а за один принтер» — это по определению два РАЗНЫХ проекта.
c.execute("INSERT INTO projects (id, name) VALUES ('prj2','P2')")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F2','prj2','plate2.3mf','h1',1)")
c.commit()

class TrackedLock:
    """lock_p с УЧЁТОМ ВЛАДЕЛЬЦА. Обычный locked() под конкуренцией врёт: он True и когда лок держит
    ДРУГОЙ поток, поэтому «adapter вызван без лока» им не доказать. Здесь помним ident владельца и
    спрашиваем именно «держу ли ЕГО я, в этом потоке»."""
    def __init__(self):
        self._l = threading.Lock()
        self._owner = None

    def acquire(self, *a, **k):
        ok = self._l.acquire(*a, **k)
        if ok:
            self._owner = threading.get_ident()
        return ok

    def release(self):
        self._owner = None
        self._l.release()

    def locked(self):
        return self._l.locked()

    def held_by_me(self):
        return self._owner == threading.get_ident() and self._l.locked()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *a):
        self.release()
        return False


LOCK = TrackedLock()             # тот же lock_p, что и в ядре
MGR = threading.Lock()           # мьютекс send-менеджера (reservation/hold) — как в _PrintSendManager
FLEET = [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}]
COMPAT = {"pr1"}
HOLDS, RESV = {}, {}
DISPATCHED, DLOCK = [], threading.Lock()
_seq = [0]


def SAFETY(pid):
    return {"printer_id": pid, "transport": "bambu", "status": "IDLE", "status_raw": "IDLE",
            "fresh": True, "user_stopped_pending": False, "printing_active": False,
            "safe_idle": True, "unsafe_reason": ""}


po.init(c, LOCK, lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: ("IDLE", True), safety_fn=SAFETY,
        printers_fn=lambda: FLEET, send_reserved_fn=lambda: set(RESV), file_ok_fn=lambda f: True,
        file_requirements_fn=bomb('file_requirements'), filament_snapshot_fn=lambda pid: {},
        reported_filament_fn=lambda pid: {})
po.init_db()


def mk_plan(pid, slot=0, spool='sp_0'):
    return {"version": 1, "status": "ready", "reason": "", "project_id": "prj", "run_id": "prun_1",
            "item_id": "it_1", "file_id": "F1", "file_hash": "h1", "printer_id": pid,
            "transport": "bambu", "filament_count": 1, "ams_slot": slot,
            "mode": "external" if slot == -1 else "ams", "spool_id": spool, "inventory_bound": True,
            "required_material": "PETG", "inventory_material": "PETG", "reported_material": "PETG",
            "required_color": "#161616", "inventory_color": "#161616", "reported_color": "#161616",
            "color_distance": 0.0, "color_relation": "exact", "verification": "telemetry_confirmed",
            "requires_approval": False, "approval": None, "built_at": 1.0}


# ── Адаптеры: reservation/hold под СВОИМ мьютексом, ровно как настоящий _PrintSendManager ──────
def A_reserve(pid, owner_type, owner_id):
    with MGR:
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


DISPATCH_HOOK = [None]


def A_dispatch(payload):
    # Именно held_by_me: под конкуренцией lock_p законно держит другой поток, и глобальный
    # locked() дал бы ложное срабатывание.
    if LOCK.held_by_me():
        BOOM.append('adapter вызван под удержанным lock_p')
    if DISPATCH_HOOK[0]:
        DISPATCH_HOOK[0](payload)
    with DLOCK:
        DISPATCHED.append(payload)
        n = len(DISPATCHED)
    return {"status": "accepted", "project_print_job_id": "pjob_%d" % n, "command_sent": False}


ADAPTERS = {"list_printers": lambda: list(FLEET), "safety_snapshot": SAFETY,
            "compatibility_check": lambda frow: set(COMPAT), "build_feed_plan": lambda r, i, p: mk_plan(p),
            "persist_feed_plan": po.persist_feed_plan, "reserve_printer": A_reserve,
            "cancel_reserved": A_cancel, "set_hold": A_set_hold, "clear_hold": A_clear_hold,
            "mock_dispatch": A_dispatch}


def reset(items=(('it_1', 1),), printers=('pr1',), runs=(('prun_1', 1.0, 'prj'),)):
    """items: (item_id, seq[, run_id, project_id, file_id]); runs: (run_id, created_at, project_id)."""
    with LOCK:
        c.execute("DELETE FROM project_runs"); c.execute("DELETE FROM project_run_items")
        c.execute("DELETE FROM plate_clearances")
        for rid, created, prj in runs:
            c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
                      "VALUES (?,?,'running','exact','boot_A',?,1.0)", (rid, prj, created))
        for t in items:
            iid, seq = t[0], t[1]
            rid = t[2] if len(t) > 2 else 'prun_1'
            prj = t[3] if len(t) > 3 else 'prj'
            fid = t[4] if len(t) > 4 else 'F1'
            c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, created_at, updated_at) "
                      "VALUES (?,?,?,?,?,'pending',1.0,1.0)", (iid, rid, prj, fid, seq))
        c.commit()
    HOLDS.clear(); RESV.clear(); DISPATCHED.clear(); DISPATCH_HOOK[0] = None
    cids = []
    for pid in printers:
        cid = 'clr_' + uuid.uuid4().hex[:8]
        with LOCK:
            c.execute("INSERT INTO plate_clearances (id, printer_id, confirmed_at, nonce, boot_id) "
                      "VALUES (?,?,?,?,'boot_A')", (cid, pid, 1.0, 'n'))
            c.commit()
        cids.append(cid)
    return cids


def run_ticks(n, barrier_all=True):
    """n одновременных тиков. Барьер — чтобы они реально стартовали в одну точку, а не по очереди."""
    results, errs, lk = [], [], threading.Lock()
    bar = threading.Barrier(n) if barrier_all else None

    def _w():
        try:
            if bar:
                bar.wait()
            r = po._scheduler_tick_core({}, ADAPTERS)
            with lk:
                results.append(r)
        except Exception as e:
            with lk:
                errs.append(e)

    ths = [threading.Thread(target=_w) for _ in range(n)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    return results, errs


def consumed(cid):
    with LOCK:
        r = c.execute("SELECT consumed_at, consumed_by_item_id FROM plate_clearances WHERE id=?", (cid,)).fetchone()
    return (r["consumed_at"] is not None, r["consumed_by_item_id"])


def istate(iid='it_1'):
    with LOCK:
        return c.execute("SELECT state FROM project_run_items WHERE id=?", (iid,)).fetchone()["state"]


# ══ C1. 10 одновременных тиков, один item/printer/clearance ═══════════════════════════════════
cid = reset()[0]
res, errs = run_ticks(10)
check('C1a. ни один тик не упал', errs == [] or check('   ошибки: %r' % errs[:2], False) is None)
check('C1b. КРИТИЧНО: ровно ОДИН lease на 10 одновременных тиков',
      sum(r['leased'] for r in res) == 1)
check('C1c. КРИТИЧНО: ровно ОДИН вызов adapter (двух печатей быть не может)', len(DISPATCHED) == 1)
check('C1d. КРИТИЧНО: разрешение потреблено РОВНО один раз и одним item\'ом', consumed(cid) == (True, 'it_1'))
check('C1e. ровно один dispatched в сумме', sum(r['dispatched'] for r in res) == 1)
check('C1f. item в единственном валидном состоянии', istate() == 'waiting_start_confirmation')
check('C1g. проигравшие тики не оставили reservation', len(RESV) <= 1)
check('C1h. принтер удержан ровно один раз одним владельцем',
      len(HOLDS) == 1 and HOLDS['pr1']['owner_id'] == 'prun_1')
with LOCK:
    _n = c.execute("SELECT COUNT(*) n FROM project_run_items WHERE assigned_printer_id='pr1' "
                   "AND state IN ('leased','sending','waiting_start_confirmation','printing','waiting_plate_clear')"
                   ).fetchone()['n']
check('C1i. на принтере ровно ОДИН активный item (partial UNIQUE + lease)', _n == 1)

# ══ C2. 10 тиков, два принтера/два item ═══════════════════════════════════════════════════════
FLEET = [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0},
         {"id": "pr2", "name": "B", "type": "bambu", "order_idx": 1}]
COMPAT = {"pr1", "pr2"}
cids = reset(items=(('it_1', 1), ('it_2', 2)), printers=('pr1', 'pr2'))
res, errs = run_ticks(10)
check('C2a. ни один тик не упал', errs == [])
check('C2b. КРИТИЧНО: максимум ДВА dispatch (по одному на принтер), без дублей', len(DISPATCHED) == 2)
check('C2c. суммарно ровно два lease', sum(r['leased'] for r in res) == 2)
check('C2d. каждый item отправлен ровно один раз',
      sorted(d['item_id'] for d in DISPATCHED) == ['it_1', 'it_2'])
check('C2e. каждый принтер получил ровно один item',
      sorted(d['printer_id'] for d in DISPATCHED) == ['pr1', 'pr2'])
check('C2f. оба разрешения потреблены по одному разу',
      all(consumed(x)[0] for x in cids))
check('C2g. оба принтера удержаны', set(HOLDS) == {'pr1', 'pr2'})
FLEET = [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}]
COMPAT = {"pr1"}

# ══ C3. Ручной старт против планировщика ══════════════════════════════════════════════════════
_manual_wins, _sched_wins = 0, 0
for _i in range(12):
    cid = reset()[0]
    _mres, _lk2 = [], threading.Lock()
    _bar = threading.Barrier(2)

    def _manual():
        _bar.wait()
        # Ручной старт — БЕЗ owner: ровно так же, как это делают upload_print/part_print/очередь.
        with MGR:
            if 'pr1' in HOLDS or 'pr1' in RESV:
                r = (False, None, 'held_or_busy')
            else:
                RESV['pr1'] = 'manual_%d' % _i
                r = (True, 'manual_%d' % _i, '')
        with _lk2:
            _mres.append(r[0])

    def _sched():
        _bar.wait()
        r = po._scheduler_tick_core({}, ADAPTERS)
        with _lk2:
            _mres.append(('sched', r['leased']))

    t1, t2 = threading.Thread(target=_manual), threading.Thread(target=_sched)
    t1.start(); t2.start(); t1.join(); t2.join()
    _mw = [x for x in _mres if x is True]
    _sw = [x for x in _mres if isinstance(x, tuple) and x[1] == 1]
    if _mw and not _sw:
        _manual_wins += 1
        check('C3.%d ручной победил -> планировщик БД НЕ изменил (item pending, разрешение цело)' % _i,
              istate() == 'pending' and consumed(cid)[0] is False)
    elif _sw and not _mw:
        _sched_wins += 1
        check('C3.%d планировщик победил -> ручной получил отказ, lease состоялся' % _i,
              istate() == 'waiting_start_confirmation' and consumed(cid)[0] is True)
    else:
        check('C3.%d КРИТИЧНО: победил РОВНО один (manual=%r, sched=%r)' % (_i, _mw, _sw), False)
check('C3z. за 12 раундов побеждал ровно один участник (manual=%d, sched=%d, сумма=12)'
      % (_manual_wins, _sched_wins), _manual_wins + _sched_wins == 12)

# ══ C4. Два run'а (двух РАЗНЫХ проектов) за один принтер ══════════════════════════════════════
# Один активный run на проект запрещён индексом idx_pruns_active, поэтому конкурируют prj и prj2.
cid = reset(items=(('it_a', 1, 'prun_1', 'prj', 'F1'), ('it_b', 1, 'prun_2', 'prj2', 'F2')),
            runs=(('prun_1', 1.0, 'prj'), ('prun_2', 2.0, 'prj2')))[0]
res, errs = run_ticks(8)
check('C4a. ни один тик не упал (конфликт UNIQUE обработан, а не свалился)', errs == [])
check('C4b. КРИТИЧНО: ровно ОДИН item получил принтер', len(DISPATCHED) == 1)
check('C4c. победил СТАРШИЙ run (FIFO по created_at) — новый не обгоняет старый',
      DISPATCHED[0]['run_id'] == 'prun_1' and DISPATCHED[0]['item_id'] == 'it_a')
check('C4d. второй run принтер не получил и БД не испортил', istate('it_b') == 'pending')
check('C4e. разрешение потреблено один раз победителем', consumed(cid) == (True, 'it_a'))

# ══ C5. Двойной consume разрешения ════════════════════════════════════════════════════════════
cid = reset()[0]
_wins, _lk3 = [], threading.Lock()


def _consume_race():
    ok = po.consume_clearance(cid, 'it_' + uuid.uuid4().hex[:4])
    with _lk3:
        _wins.append(ok)


_ths = [threading.Thread(target=_consume_race) for _ in range(10)]
[t.start() for t in _ths]
[t.join() for t in _ths]
check('C5. КРИТИЧНО: 10 потоков consume одного разрешения -> ровно ОДИН успех', _wins.count(True) == 1)

# ══ C6. Adapter держится барьером: локи в это время свободны ══════════════════════════════════
cid = reset()[0]
_gate = threading.Event()
_probe = {"db_ok": None, "mgr_ok": None}


def _hold_in_adapter(payload):
    """Пока adapter «отправляет» (минуты в реальности), БД и send-менеджер обязаны быть свободны."""
    _probe["db_ok"] = LOCK.acquire(blocking=False)
    if _probe["db_ok"]:
        # читаем БД параллельно adapter'у — API не должен быть заблокирован
        _probe["read"] = c.execute("SELECT COUNT(*) n FROM project_run_items").fetchone()["n"]
        LOCK.release()
    _probe["mgr_ok"] = MGR.acquire(blocking=False)
    if _probe["mgr_ok"]:
        MGR.release()
    _gate.wait(timeout=2.0)


DISPATCH_HOOK[0] = _hold_in_adapter
_t = threading.Thread(target=lambda: po._scheduler_tick_core({}, ADAPTERS))
_t.start()
threading.Event().wait(0.15)          # даём тику дойти до adapter'а
check('C6a. КРИТИЧНО: во время adapter lock_p СВОБОДЕН (минутная отправка не блокирует БД)',
      _probe["db_ok"] is True)
check('C6b. и параллельное чтение БД во время adapter проходит', _probe.get("read") == 1)
check('C6c. КРИТИЧНО: во время adapter мьютекс send-менеджера тоже свободен', _probe["mgr_ok"] is True)
_gate.set()
_t.join(timeout=5.0)
check('C6d. тик завершился', not _t.is_alive() and istate() == 'waiting_start_confirmation')
DISPATCH_HOOK[0] = None

# ══ C7. Исключение на одном item не ЗАСОРЯЕТ другой принтер ══════════════════════════════════
# ВАЖНОЕ УТОЧНЕНИЕ СМЫСЛА. Ambiguous останавливает СВОЙ run намеренно (run -> attention_required,
# §11), а транзакция lease обязана перечитать run и убедиться, что он running (§7). Значит второй
# item ТОГО ЖЕ run после неоднозначности НЕ запускается — и это правильно: пока человек не знает,
# началась ли печать на pr1, подкладывать ему ещё запусков того же проекта нельзя.
# Проверяем то, что действительно требуется: сбой не оставляет мусора на pr2 и не мешает ДРУГОМУ run.
FLEET = [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0},
         {"id": "pr2", "name": "B", "type": "bambu", "order_idx": 1}]
COMPAT = {"pr1", "pr2"}
cids = reset(items=(('it_1', 1), ('it_2', 2)), printers=('pr1', 'pr2'))


def _boom_on_pr1(payload):
    if payload['printer_id'] == 'pr1':
        raise RuntimeError('adapter упал на pr1')


DISPATCH_HOOK[0] = _boom_on_pr1
r = po._scheduler_tick_core({}, ADAPTERS)
check('C7a. упавший item -> ambiguous (мог отправить), hold на СВОЁМ принтере остаётся',
      istate('it_1') == 'ambiguous_after_dispatch' and 'pr1' in HOLDS)
check('C7b. run своего проекта остановлен — человек ещё не знает, началась ли печать',
      c.execute("SELECT state FROM project_runs WHERE id='prun_1'").fetchone()['state'] == 'attention_required'
      and istate('it_2') == 'pending')
check('C7c. КРИТИЧНО: pr2 НЕ засорён — ни reservation, ни hold не утекли',
      'pr2' not in RESV and 'pr2' not in HOLDS)
check('C7d. КРИТИЧНО: разрешение pr2 НЕ потрачено на неудавшемся пути',
      consumed(cids[0])[0] is True and consumed(cids[1])[0] is False)

# А вот ДРУГОЙ run (другого проекта) обязан спокойно занять pr2 — сбой соседа ему не помеха.
with LOCK:
    c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
              "VALUES ('prun_2','prj2','running','exact','boot_A',5.0,1.0)")
    c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, created_at, updated_at) "
              "VALUES ('it_x','prun_2','prj2','F2',1,'pending',1.0,1.0)")
    c.commit()
DISPATCH_HOOK[0] = None
r = po._scheduler_tick_core({}, ADAPTERS)
check('C7e. КРИТИЧНО: ДРУГОЙ run штатно занял pr2 — сбой соседнего проекта его не блокирует',
      istate('it_x') == 'waiting_start_confirmation'
      and any(d['printer_id'] == 'pr2' and d['run_id'] == 'prun_2' for d in DISPATCHED))
check('C7f. и pr1 при этом остался за первым run (чужое удержание не перехвачено)',
      HOLDS['pr1']['owner_id'] == 'prun_1' and HOLDS['pr2']['owner_id'] == 'prun_2')
FLEET = [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}]
COMPAT = {"pr1"}

# ══ C8. Повторный тик после accepted ══════════════════════════════════════════════════════════
cid = reset()[0]
po._scheduler_tick_core({}, ADAPTERS)
_n = len(DISPATCHED)
res, errs = run_ticks(5)
check('C8. КРИТИЧНО: 5 повторных тиков после accepted не вызвали ни одного нового dispatch',
      len(DISPATCHED) == _n and sum(r['leased'] for r in res) == 0)

# ══ Ни одного реального вызова печати ═════════════════════════════════════════════════════════
check('Z1. предохранитель выключен и production-вход ничего не делает',
      po.DISPATCH_ENABLED is False
      and po.scheduler_tick() == {"status": "disabled", "reason": "project_orchestrator_dispatch_disabled",
                                  "leased": 0, "dispatched": 0})
check('Z2. настоящих project_print_job не создано (их отдаёт только fake-adapter)',
      c.execute("SELECT COUNT(*) n FROM project_print_jobs").fetchone()['n'] == 0)
check('Z3. НИ ОДНОГО реального вызова печати и ни одного adapter под локом: BOOM=%r' % (BOOM,), BOOM == [])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: под настоящими потоками 10 одновременных тиков дают ровно один lease, один '
              'consume разрешения и один вызов adapter; два принтера — ровно два, без дублей; ручной '
              'старт и планировщик никогда не выигрывают оба; два run\'а за один принтер разводит '
              'FIFO+UNIQUE; во время adapter БД и send-менеджер свободны; исключение на одном item '
              'не мешает другому принтеру; повторные тики второй отправки не делают'))
raise SystemExit(1 if fail else 0)
