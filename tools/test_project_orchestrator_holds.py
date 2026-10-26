# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Generic-удержание принтера в send-менеджере — core Alpha 2.741 (этап 5A1).
# ЗАЧЕМ. Reservation живёт ТОЛЬКО на время отправки: она снимается по подтверждению старта
# (note_printer_running -> _terminate_locked), то есть на всю печать и на всё время «детали ещё на
# столе» принтер для менеджера снова свободен, а НИ ОДИН стартовый вход не проверяет состояние
# принтера. Hold закрывает именно это окно. Здесь доказываем: удержание непреодолимо для всех
# обычных стартов (в т.ч. под конкуренцией потоков), владелец его не теряет и проходит сам,
# RUNNING его не снимает, оно переживает рестарт и НЕ снимается отменой плана.
# Класс _PrintSendManager берётся ДОСЛОВНО из server.py (exec блока) — тест падает, если он уедет.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_orchestrator_holds.py   (0 = пройдено)
import importlib.util, os, re, sqlite3, tempfile, threading, time, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()

fail = 0
BOOM = []          # сюда падает ЛЮБАЯ попытка транспорта/печати — в конце обязан быть пуст


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def bomb(tag):
    def _b(*a, **k):
        BOOM.append(tag)
        raise AssertionError('ЗАПРЕЩЕНО в 5A1: ' + tag)
    return _b


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


def _block(start, end):
    i = _SRV.index(start)
    return _SRV[i:_SRV.index(end, i)]


# ── песочница: настоящий _PrintSendManager из ядра ─────────────────────────────────────────────
NS = {'threading': threading, 'time': time, 'os': os, 're': re, 'uuid': uuid,
      'log': type('L', (), {'debug': staticmethod(lambda *a, **k: None),
                            'info': staticmethod(lambda *a, **k: None),
                            'warning': staticmethod(lambda *a, **k: None),
                            'error': staticmethod(lambda *a, **k: None)})(),
      '_uid': lambda p: p + uuid.uuid4().hex[:10],
      'p_states': {}, 'last_seen': {}, 'STALE_FAIL_S': 60,
      '_send_file_to_printer': bomb('_send_file_to_printer'),   # ловушка: менеджер не смеет её звать
      '_exc_brief': lambda: 'x'}
exec('from concurrent.futures import ThreadPoolExecutor as _SendPool\nfrom collections import deque as _send_deque', NS)
for _c in ('_SEND_STATES', '_SEND_TERMINAL', '_SEND_MAX_WORKERS', '_SEND_HISTORY', '_SEND_DONE_TTL', '_SEND_CONFIRM_GRACE',
           '_SEND_QUEUE_ORPHAN_GRACE'):   # Alpha 2.771: grace watchdog'а брошенных queue-reservation (значение по умолчанию аргумента sweep_queue_orphans)
    exec(re.search(r'^%s = .*$' % _c, _SRV, re.M).group(0), NS)
exec(_block('def _send_sanitize_err(', 'def _hold_public('), NS)
exec(_block('def _hold_public(', 'def _hold_block('), NS)
exec(_block('def _send_printer_status(', '# ── БЕЗОПАСНОЕ СОСТОЯНИЕ'), NS)
exec(_block('class _PrintSendManager:', '_send_mgr = _PrintSendManager()'), NS)
Mgr = NS['_PrintSendManager']
OT, OID = 'project_run', 'prun_1'

# ── 1. Базовый API ─────────────────────────────────────────────────────────────────────────────
m = Mgr()
check('H1. изначально удержаний нет', m.holds_snapshot() == {} and m.get_hold('pr1') is None)
ok, h = m.set_hold('pr1', OT, OID, 'detали на столе')
check('H2. set_hold ставит удержание и возвращает его', ok and h['owner_type'] == OT and h['owner_id'] == OID)
check('H3. get_hold отдаёт КОПИЮ (мутация ответа не портит реестр)',
      (m.get_hold('pr1').update({'owner_id': 'HACKED'}), m.get_hold('pr1')['owner_id'])[1] == OID)
check('H4. holds_snapshot — глубокая копия',
      (m.holds_snapshot()['pr1'].update({'reason': 'HACKED'}), m.get_hold('pr1')['reason'])[1] == 'detали на столе')
_c0 = m.get_hold('pr1')['created_at']
time.sleep(0.01)
ok2, h2 = m.set_hold('pr1', OT, OID, 'обновлённая причина')
check('H5. повтор set_hold тем же владельцем идемпотентен: created_at не сдвигается',
      ok2 and h2['created_at'] == _c0 and m.get_hold('pr1')['reason'] == 'обновлённая причина')
check('H6. set_hold без владельца отвергается',
      m.set_hold('pr1', '', '', 'x') == (False, None) and m.set_hold('', OT, OID, 'x') == (False, None))

# ── 2. Owner-match ─────────────────────────────────────────────────────────────────────────────
check('H7. ЧУЖОЙ владелец не перехватывает удержание', m.set_hold('pr1', OT, 'prun_OTHER', 'x')[0] is False)
check('H8. и реестр при этом не изменился', m.get_hold('pr1')['owner_id'] == OID)
check('H9. ЧУЖОЙ владелец не снимает удержание', m.clear_hold('pr1', OT, 'prun_OTHER') is False)
check('H10. чужой owner_type не снимает', m.clear_hold('pr1', 'queue', OID) is False)
check('H11. удержание на месте после чужих попыток', m.get_hold('pr1') is not None)
check('H12. СВОЙ владелец снимает', m.clear_hold('pr1', OT, OID) is True)
check('H13. повторное снятие -> False (идемпотентно, без исключений)', m.clear_hold('pr1', OT, OID) is False)
check('H14. снятие несуществующего -> False', m.clear_hold('nope', OT, OID) is False)

# ── 3. Отказ обычных стартов ───────────────────────────────────────────────────────────────────
m = Mgr()
m.set_hold('pr1', OT, OID, 'waiting_plate_clear')
check('H15. reserve БЕЗ владельца -> printer_held', m.reserve('pr1', 'X1C', 'f.3mf', 'task') == (False, None, 'printer_held'))
check('H16. begin_direct без владельца -> printer_held',
      m.begin_direct('pr1', 'X1C', 'f.3mf', 'task', bomb('send_callable')) == (False, None, 'printer_held'))
_r, _j = m.begin_or_adopt_tracked('pr1', 'X1C', 'f.3mf', 'queue', bomb('send_callable'))
check('H17. begin_or_adopt_tracked без владельца -> printer_held + hold в ответе',
      _r['reason'] == 'printer_held' and _j is None and _r['hold']['owner_id'] == OID)
check('H18. ОТКАЗ до побочных эффектов: job не создан, reservation нет, send_callable не звался',
      m.snapshot()['jobs'] == [] and m.snapshot()['reserved_printer_ids'] == [] and BOOM == [])
check('H19. чужой владелец reserve тоже не проходит',
      m.reserve('pr1', 'X1C', 'f.3mf', 'task', hold_owner_type=OT, hold_owner_id='prun_OTHER')
      == (False, None, 'printer_held'))
check('H20. неудерживаемый принтер по-прежнему свободен (удержание точечное)',
      m.reserve('pr2', 'X1C', 'f.3mf', 'task')[0] is True)

# ── 4. Owner-bypass (это понадобится scheduler'у 5A2; здесь только механика) ───────────────────
m = Mgr()
m.set_hold('pr1', OT, OID, 'waiting_plate_clear')
_ok, _jid, _rs = m.reserve('pr1', 'X1C', 'f.3mf', 'project_run', hold_owner_type=OT, hold_owner_id=OID)
check('H21. ВЛАДЕЛЕЦ удержания резервирует свой принтер', _ok and _jid and _rs == '')
check('H22. reservation и hold СОСУЩЕСТВУЮТ (hold не снят захватом)',
      m.get_hold('pr1') is not None and m.snapshot()['reserved_printer_ids'] == ['pr1'])
check('H23. пока владелец держит reservation, чужой старт получает busy/held, но НЕ проходит',
      m.reserve('pr1', 'X1C', 'g.3mf', 'task')[0] is False)
check('H24. второй reserve того же владельца -> busy (reservation одна, дублей нет)',
      m.reserve('pr1', 'X1C', 'g.3mf', 'project_run', hold_owner_type=OT, hold_owner_id=OID)[2] == 'busy')

# ── 5. RUNNING не снимает удержание ────────────────────────────────────────────────────────────
_j = m._jobs[_jid]
_j['_command_sent'] = True
m.note_printer_running('pr1')
check('H25. телеметрия RUNNING снимает RESERVATION (прежнее поведение не тронуто)',
      m.snapshot()['reserved_printer_ids'] == [] and _j['state'] == 'completed')
check('H26. ГЛАВНОЕ: RUNNING НЕ снимает HOLD — принтер остаётся за владельцем', m.get_hold('pr1') is not None)
check('H27. и после снятия reservation чужой старт всё ещё получает printer_held',
      m.reserve('pr1', 'X1C', 'g.3mf', 'task') == (False, None, 'printer_held'))
m.tick(now=time.time() + 10_000)     # watchdog-тик TTL/подтверждений
check('H28. watchdog-тик удержание не трогает', m.get_hold('pr1') is not None)

# ── 6. Гонка: 10 потоков ручного старта против удержания ───────────────────────────────────────
m = Mgr()
m.set_hold('pr1', OT, OID, 'waiting_plate_clear')
_res, _lk = [], threading.Lock()


def _manual(i):
    r = m.reserve('pr1', 'X1C', 'f%d.3mf' % i, 'task')     # владельца НЕ передаём — обычный старт
    with _lk:
        _res.append(r[0])


_ths = [threading.Thread(target=_manual, args=(i,)) for i in range(10)]
[t.start() for t in _ths]
[t.join() for t in _ths]
check('H29. 10 потоков ручного reserve на удержанный принтер -> 0 успехов', _res == [False] * 10)
check('H30. и ни одного job/reservation не создано', m.snapshot()['jobs'] == [] and m.snapshot()['reserved_printer_ids'] == [])

# ── 7. Гонка: 10 потоков ВЛАДЕЛЬЦА -> ровно одна reservation ───────────────────────────────────
_res2 = []


def _owner(i):
    r = m.reserve('pr1', 'X1C', 'f%d.3mf' % i, 'project_run', hold_owner_type=OT, hold_owner_id=OID)
    with _lk:
        _res2.append(r[0])


_ths = [threading.Thread(target=_owner, args=(i,)) for i in range(10)]
[t.start() for t in _ths]
[t.join() for t in _ths]
check('H31. 10 потоков владельца -> РОВНО одна reservation (остальные busy)', _res2.count(True) == 1)
check('H32. в реестре ровно один job и одна reservation',
      len(m.snapshot()['jobs']) == 1 and m.snapshot()['reserved_printer_ids'] == ['pr1'])

# ── 8. Гонка владельца против чужого ───────────────────────────────────────────────────────────
m = Mgr()
m.set_hold('pr1', OT, OID, 'x')
_mixed = []


def _mix(i):
    if i % 2:
        r = m.reserve('pr1', 'X1C', 'f.3mf', 'task')                                  # чужой
    else:
        r = m.reserve('pr1', 'X1C', 'f.3mf', 'project_run', hold_owner_type=OT, hold_owner_id=OID)
    with _lk:
        _mixed.append((i % 2 == 0, r[0], r[2]))


_ths = [threading.Thread(target=_mix, args=(i,)) for i in range(10)]
[t.start() for t in _ths]
[t.join() for t in _ths]
check('H33. под смешанной гонкой успех — РОВНО один и только у владельца',
      [x for x in _mixed if x[1]] and len([x for x in _mixed if x[1]]) == 1 and [x for x in _mixed if x[1]][0][0] is True)
check('H34. все чужие получили именно printer_held (не busy — отказ по владению)',
      all(x[2] == 'printer_held' for x in _mixed if not x[0]))

# ── 9. Секретов в снимке нет ───────────────────────────────────────────────────────────────────
m = Mgr()
m.set_hold('pr1', OT, OID, 'project_run_item:waiting_plate_clear')
_snap = repr(m.holds_snapshot())
check('H35. снимок удержаний без токенов/паролей/ip/путей',
      not re.search(r'(?i)token|password|access|bblp|\d+\.\d+\.\d+\.\d+|[A-Za-z]:\\\\', _snap))
check('H36. в снимке только ожидаемые поля',
      set(m.holds_snapshot()['pr1'].keys()) == {'printer_id', 'owner_type', 'owner_id', 'reason', 'created_at'})
_ok, _h = m.set_hold('pr2', OT, OID, 'A' * 500)
check('H37. длинные строки обрезаются (реестр не раздувается)', len(_h['reason']) <= 120)

# ── 10. Rebuild после рестарта (реальный оркестратор + реальный _orch_rebuild_holds) ───────────
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
c.commit()
po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: ("IDLE", True), printers_fn=lambda: [], send_reserved_fn=lambda: set(),
        file_ok_fn=lambda f: True)
po.init_db()
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_1','prj','running','exact','boot_A',1.0,1.0)")


def mk_item(iid, state, printer):
    c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
              "assigned_printer_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
              (iid, 'prun_1', 'prj', 'F1', 1, state, printer, 1.0, 1.0))
    c.commit()


# По одному item'у на КАЖДОЕ состояние — на своём принтере (partial UNIQUE не даёт двух на одном).
for _i, _st in enumerate(('leased', 'sending', 'waiting_start_confirmation', 'printing', 'waiting_plate_clear')):
    mk_item('it_%d' % _i, _st, 'own%d' % _i)
mk_item('it_amb', 'ambiguous_after_dispatch', 'own_amb')
for _i, _st in enumerate(('pending', 'eligible', 'blocked', 'completed', 'cancelled',
                          'failed_before_dispatch', 'superseded_by_external_progress')):
    mk_item('it_free_%d' % _i, _st, 'free%d' % _i)

_holds = po.active_holds()
check('H38. удерживают ровно владеющие состояния (+ambiguous), и НИ ОДНО свободное',
      set(_holds) == {'own0', 'own1', 'own2', 'own3', 'own4', 'own_amb'})
check('H39. pending/eligible/blocked/completed/cancelled/failed_before_dispatch/superseded НЕ удерживают',
      not any(k.startswith('free') for k in _holds))
check('H40. владелец удержания — run, причина содержит состояние item',
      _holds['own3']['owner_type'] == 'project_run' and _holds['own3']['owner_id'] == 'prun_1'
      and 'printing' in _holds['own3']['reason'])
check('H41. holds_to_rebuild == active_holds', po.holds_to_rebuild() == _holds)
check('H42. active_holds — чистое чтение (БД не изменилась)',
      po.active_holds() == _holds
      # 5 владеющих + ambiguous + 7 свободных состояний = 13 item'ов, ни один не создан/не удалён чтением
      and c.execute("SELECT COUNT(*) n FROM project_run_items").fetchone()["n"] == 13)

# Реальный _orch_rebuild_holds из server.py: БД -> реестр (после «рестарта» реестр пуст).
m2 = Mgr()
RB = {'_orch': po, '_send_mgr': m2}
exec(_block('def _orch_rebuild_holds(', 'if not _IS_POOL_WORKER:'), RB)
_set, _cleared = RB['_orch_rebuild_holds']()
check('H43. rebuild после рестарта восстановил удержания из БД', _set == 6 and set(m2.holds_snapshot()) == set(_holds))
check('H44. восстановленное удержание сразу блокирует ручной старт',
      m2.reserve('own4', 'X1C', 'f.3mf', 'task') == (False, None, 'printer_held'))
check('H45. rebuild идемпотентен', RB['_orch_rebuild_holds']() == (6, 0) and set(m2.holds_snapshot()) == set(_holds))
# Осиротевшее удержание прошлого снимка снимается — но ТОЛЬКО по owner-match.
m2.set_hold('gone', 'project_run', 'prun_1', 'осиротевшее')
m2.set_hold('alien', 'other_owner', 'x1', 'чужое, не наше дело')
_s2, _c2 = RB['_orch_rebuild_holds']()
check('H46. осиротевшее удержание СВОЕГО типа снимается', _c2 == 1 and m2.get_hold('gone') is None)
check('H47. удержание ЧУЖОГО владельца rebuild не трогает', m2.get_hold('alien') is not None)

# ── 11. Cancel run НЕ снимает удержание ────────────────────────────────────────────────────────
_cr = po.cancel_run('prun_1')
check('H48. cancel_run отработал', _cr['status'] == 'ok')
check('H49. КРИТИЧНО: cancel run НЕ отменил печатающие/ждущие стол item\'ы',
      c.execute("SELECT COUNT(*) n FROM project_run_items WHERE state IN "
                "('sending','printing','waiting_plate_clear','leased','waiting_start_confirmation')").fetchone()["n"] == 5)
_holds_after = po.active_holds()
check('H50. КРИТИЧНО: после cancel run принтеры ВСЁ ЕЩЁ удержаны (детали на столе возможны)',
      set(_holds_after) == {'own0', 'own1', 'own2', 'own3', 'own4', 'own_amb'})
RB['_orch_rebuild_holds']()
check('H51. и ручной старт по-прежнему получает printer_held на waiting_plate_clear после cancel',
      m2.reserve('own4', 'X1C', 'f.3mf', 'task') == (False, None, 'printer_held'))
check('H52. отменённые pending-item\'ы удержания не создают', 'free0' not in _holds_after)

# Владение заканчивается только безопасным переходом item'а в терминальное состояние.
c.execute("UPDATE project_run_items SET state='completed' WHERE id='it_4'")
c.commit()
_s3, _c3 = RB['_orch_rebuild_holds']()
check('H53. item завершён явным безопасным переходом -> удержание снято', m2.get_hold('own4') is None)
check('H54. остальные удержания при этом целы', m2.get_hold('own3') is not None)

# ── 11a. Alpha 2.761: план, УДЕРЖИВАЮЩИЙ принтер, обязан быть ВИДЕН оператору ──────────────────
# Ловушка, пойманная на живой ферме: оператор отменил план, у которого деталь осталась
# ambiguous_after_dispatch (связь с принтером пропала во время печати). Такой план держит принтер,
# но в list_active_runs НЕ попадал (state='cancelled') -> в интерфейсе его нет -> разрешить
# неоднозначность НЕГДЕ -> принтер заблокирован навсегда, и ни один новый проект не стартует.
_listed = {r['run_id'] for r in po.list_active_runs()}
check('H54h. КРИТИЧНО: ОТМЕНЁННЫЙ план, который ещё удерживает принтер, ВИДЕН в списке',
      'prun_1' in _listed)
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_hist','prj','cancelled','exact','boot_A',9.0,9.0)")
c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
          "assigned_printer_id, created_at, updated_at) VALUES ('it_hist','prun_hist','prj','F1',1,"
          "'cancelled','pr_hist',9.0,9.0)")
c.commit()
_listed2 = {r['run_id'] for r in po.list_active_runs()}
check('H54i. а обычная ИСТОРИЯ (терминальный план БЕЗ удержаний) в списке НЕ появляется',
      'prun_hist' not in _listed2 and 'prun_1' in _listed2)

# ── 11b. Alpha 2.758: разрешение/отмена ОСВОБОЖДАЮТ осиротевшее удержание (роут зовёт сверку) ──
# Баг до 2.758: resolve/cancel НЕ звали сверку — удержание ambiguous-детали, разрешённой оператором
# «не начиналось», висело мёртвым в реестре и блокировало новый старт с printer_held до рестарта.
# Роут теперь после УСПЕШНОЙ операции зовёт _orch_resync_holds_safe -> _orch_rebuild_holds.
# Проверяем и ПОВЕДЕНИЕ (сверка снимает осиротевшее), и ФАКТ вызова из роутов.
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_2','prj','running','exact','boot_A',1.0,1.0)")
c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
          "assigned_printer_id, created_at, updated_at) VALUES ('it_amb2','prun_2','prj','F1',1,"
          "'ambiguous_after_dispatch','pr_amb2',1.0,1.0)")
c.commit()
RB['_orch_rebuild_holds']()
check('H54a. ambiguous-деталь удерживает свой принтер', m2.get_hold('pr_amb2') is not None)
_rr = po.resolve_item('prun_2', 'it_amb2', 'not_started')
# Alpha 2.766: у АКТИВНОГО run «не начиналась» возвращает деталь в очередь (pending) — прежний
# failed_before_dispatch был тупиком без пути повтора. Для удержаний это то же самое: pending
# принтер НЕ удерживает (H39), поэтому H54c/H54d ниже не меняются.
check('H54b. resolve_item(not_started) у активного run -> деталь возвращена в очередь (pending)',
      _rr.get('status') == 'ok' and _rr.get('state') == 'pending')
# как это делает роут whole_print_resolve_item в 2.758: после успеха — сверка удержаний
RB['_orch_rebuild_holds']()
check('H54c. КРИТИЧНО: после «не начиналось» удержание СНЯТО (а не printer_held навечно)',
      m2.get_hold('pr_amb2') is None)
check('H54d. и новый ручной старт на этом принтере теперь ПРОХОДИТ',
      m2.reserve('pr_amb2', 'X1C', 'f.3mf', 'task')[0] is True)
# Alpha 2.766: у ОТМЕНЁННОГО run «не начиналась» по-прежнему хоронит деталь (историю не воскрешаем):
# prun_1 отменён в секции 11, его it_amb до сих пор ambiguous — разрешаем и проверяем.
check('H54d2. у ОТМЕНЁННОГО run «не начиналась» -> failed_before_dispatch (в очередь НЕ возвращается)',
      po.resolve_item('prun_1', 'it_amb', 'not_started').get('state') == 'failed_before_dispatch')
# ФАКТ вызова сверки из роутов (H54e-g) проверяется ниже — после определения _fn_src.

# ── 11c. Alpha 2.762: планы УДАЛЁННЫХ проектов вычищаются (иначе держат принтер навсегда) ──────
# Ловушка с живой фермы: оператор удалил проект, а его план остался в БД и продолжал УДЕРЖИВАТЬ
# принтер. Показать такой план НЕГДЕ — блок плана рисуется внутри карточки проекта, а карточки уже
# нет; значит подтвердить исход печати нельзя, удержание не снять, и НИ ОДИН новый проект не
# стартует. Чистка обязана убирать ТОЛЬКО планы без проекта и не трогать живые.
PG = {'lock_p': threading.Lock(), 'conn_p': c, 'log': NS['log'], '_exc_brief': lambda: 'x'}
exec(_block('def _orch_purge_orphan_runs(', 'def _orch_resync_holds_safe('), PG)
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_orph','proj_GONE','cancelled','exact','boot_A',5.0,5.0)")
c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
          "assigned_printer_id, created_at, updated_at) VALUES ('it_orph','prun_orph','proj_GONE','F1',1,"
          "'ambiguous_after_dispatch','pr_orph',5.0,5.0)")
c.commit()
check('H54l. предусловие: осиротевший план (проект удалён) удерживает принтер', 'pr_orph' in po.active_holds())
_npurged = PG['_orch_purge_orphan_runs']()
check('H54m. КРИТИЧНО: планы УДАЛЁННЫХ проектов вычищены -> удержание принтера СНЯТО',
      _npurged >= 1 and 'pr_orph' not in po.active_holds()
      and c.execute("SELECT COUNT(*) n FROM project_runs WHERE id='prun_orph'").fetchone()["n"] == 0
      and c.execute("SELECT COUNT(*) n FROM project_run_items WHERE run_id='prun_orph'").fetchone()["n"] == 0)
check('H54n. КРИТИЧНО: планы ЖИВОГО проекта чистка НЕ трогает',
      c.execute("SELECT COUNT(*) n FROM project_runs WHERE id='prun_1'").fetchone()["n"] == 1
      and c.execute("SELECT COUNT(*) n FROM project_run_items WHERE run_id='prun_1'").fetchone()["n"] > 0)
check('H54o. повторная чистка идемпотентна (чистить больше нечего)', PG['_orch_purge_orphan_runs']() == 0)

# ── 12. Покрытие ВСЕХ стартовых входов + фактический ответ 409 ────────────────────────────────
# Инвентарь входов зафиксирован аудитом этапа 5: все байты идут через _mk_file_send, и КАЖДЫЙ старт
# проходит через reserve/begin_direct/begin_or_adopt_tracked. Там проверка атомарна и непреодолима.
# Дополнительно там, где ДО reserve выполняются compat/хуки/сеть (part_print, project, C1), обязан
# стоять ранний _hold_block — чтобы не платить побочными эффектами за заведомый отказ.
def _fn_src(name):
    """Исходник функции ядра ДОСЛОВНО (def или async def) — до следующего определения верхнего уровня."""
    m0 = re.search(r'^(?:async )?def %s\(' % re.escape(name), _SRV, re.M)
    if not m0:
        raise AssertionError('в server.py не найден вход: ' + name)
    i = m0.start()
    m = re.search(r'\n(?=(?:async )?def |class |@app\.)', _SRV[i:])
    return _SRV[i:i + (m.start() if m else len(_SRV))]


_LOWLEVEL = ('_send_mgr.reserve(', '_send_mgr.begin_direct(', '_send_mgr.begin_or_adopt_tracked(')
for _name, _early in (('u_print', False), ('u_print_path', True), ('part_print', True),
                      ('_do_project2_file_print', True), ('p_cmd', True),
                      ('api_print_queue_enqueue', False), ('api_print_queue_recovery_continue', False)):
    _src = _fn_src(_name)
    check('H55.%s вход «%s» проходит через низкоуровневую (атомарную) проверку удержания' % (_name, _name),
          any(x in _src for x in _LOWLEVEL))
    if _early:
        check('H56.%s вход «%s» отказывает РАНО — до compat/хуков/сети' % (_name, _name), '_hold_block(' in _src)

# R-019 (29.09.2026): «Загрузить» (print_path) спрашивает склад, а хук склада пишет в базу.
# Ранний отказ обязан стоять ДО хуков, иначе удержанный принтер стоил бы правки учёта.
_upp = _fn_src('u_print_path')
_i_hk = _upp.find('_run_pre_print_hooks(')
check('H56b. print_path: ранний отказ по удержанию и занятости стоит ДО хуков склада',
      0 <= _upp.find('_hold_block(') < _i_hk and 0 <= _upp.find('_send_mgr.reserved_ids()') < _i_hk)

_rsv = _block('def reserve(', 'def begin_or_adopt_tracked(')          # методы класса: берём блоком
_boat = _block('def begin_or_adopt_tracked(', 'def run(')
check('H57. reserve проверяет удержание ПЕРВЫМ делом — до создания job и reservation',
      _rsv.index('_hold_blocks_locked') < _rsv.index('self._resv.get(pid)')
      and _rsv.index('_hold_blocks_locked') < _rsv.index('_new_job_locked'))
check('H58. begin_or_adopt_tracked проверяет удержание до адопта и до отправки',
      # якорь именно на ЛОГИКУ адопта: 'adopt_job_id' встречается раньше в сигнатуре
      _boat.index('_hold_blocks_locked') < _boat.index('if adopt_job_id:')
      and _boat.index('_hold_blocks_locked') < _boat.index('self.run_tracked('))
check('H59. существующие вызывающие owner НЕ передают -> удержание для них непреодолимо',
      'begin_direct(pid, p["name"], fname, "upload_print"' in _SRV
      and 'hold_owner' not in _fn_src('u_print') and 'hold_owner' not in _fn_src('part_print'))
check('H60. очередь: удержанный принтер не встаёт в очередь, причина видна в ответе (held)',
      '_rreason == "printer_held"' in _fn_src('api_print_queue_enqueue')
      and '"held": _held' in _fn_src('api_print_queue_enqueue'))
check('H61. recovery: удержанный принтер уходит «на внимание», а не крутится в очереди',
      '_rrreason == "printer_held"' in _fn_src('api_print_queue_recovery_continue'))

# Alpha 2.758: роуты отмены/разрешения ДЕЙСТВИТЕЛЬНО зовут сверку удержаний (иначе фикс мёртв —
# осиротевшее удержание осталось бы висеть до рестарта, как и было в баге).
_cancel_src = _fn_src('whole_print_cancel')
_resolve_src = _fn_src('whole_print_resolve_item')
check('H54e. КРИТИЧНО: whole_print_cancel зовёт сверку удержаний только при status==ok',
      '_orch_resync_holds_safe(' in _cancel_src and 'if r.get("status") == "ok"' in _cancel_src)
check('H54f. КРИТИЧНО: whole_print_resolve_item зовёт сверку удержаний только при status==ok',
      '_orch_resync_holds_safe(' in _resolve_src and 'if r.get("status") == "ok"' in _resolve_src)
check('H54g. _orch_resync_holds_safe — обёртка над _orch_rebuild_holds (та же сверка БД->реестр, fail-open)',
      '_orch_rebuild_holds()' in _fn_src('_orch_resync_holds_safe')
      and 'except Exception' in _fn_src('_orch_resync_holds_safe'))
# Alpha 2.762: удаление проекта обязано уносить и его планы печати — иначе они остаются осиротевшими
# и держат принтер, а показать/разрешить их негде (карточки проекта уже нет).
_dp = _fn_src('delete_project')
check('H54j. КРИТИЧНО: delete_project уносит планы печати проекта (runs + items)',
      'DELETE FROM project_runs WHERE project_id=?' in _dp
      and 'DELETE FROM project_run_items WHERE project_id=?' in _dp)
check('H54k. и после удаления проекта удержания принтеров пересверяются с БД',
      '_orch_resync_holds_safe(' in _dp)
check('H54p. чистка осиротевших вызывается на загрузке ДО пересборки удержаний (иначе удержание вернётся)',
      _SRV.index('_orch_purge_orphan_runs()') < _SRV.index('_hs, _hc = _orch_rebuild_holds()'))

# Фактическая форма ответа 409 (JSONResponse подменяем, чтобы не поднимать приложение).
_RESP = {}


class _FakeJSON:
    def __init__(self, content, status_code=200):
        _RESP.clear()
        _RESP.update({'content': content, 'status': status_code})


m3 = Mgr()
m3.set_hold('pr1', OT, OID, 'detали на столе')
RS = dict(NS)
RS.update({'JSONResponse': _FakeJSON, '_send_mgr': m3})
exec(_block('def _hold_block(', 'def _send_printer_status('), RS)
exec(_block('def _send_accept_response(', 'def _orch_clearance_watchdog('), RS)
RS['_send_accept_response'](False, None, 'printer_held', 'pr1')
check('H62. фактический ответ конфликта — HTTP 409', _RESP['status'] == 409)
check('H63. тело ответа: status/reason/hold(owner_type, owner_id, reason)',
      _RESP['content']['status'] == 'error' and _RESP['content']['reason'] == 'printer_held'
      and _RESP['content']['hold'] == {'owner_type': OT, 'owner_id': OID, 'reason': 'detали на столе'})
check('H64. прежний успешный ответ не изменился',
      RS['_send_accept_response'](True, 'send_1', '', 'pr1') == {'status': 'ok', 'accepted': True, 'job_id': 'send_1'})
check('H65. прежний 409 printer_send_busy сохранён (не подменён held)',
      (RS['_send_accept_response'](False, 'send_9', 'busy', 'pr2'),
       _RESP['status'] == 409 and _RESP['content']['error'] == 'printer_send_busy')[1])
_hb = RS['_hold_block']('pr1')
check('H66. ранний _hold_block отдаёт то же тело и то же владение',
      _hb['reason'] == 'printer_held' and _hb['hold']['owner_id'] == OID)
check('H67. ранний _hold_block пропускает владельца', RS['_hold_block']('pr1', OT, OID) is None)
check('H68. ранний _hold_block на свободном принтере не мешает', RS['_hold_block']('pr_free') is None)

# ── 13. Ни одного вызова печати ────────────────────────────────────────────────────────────────
check('H69. предохранитель dispatch по-прежнему выключен', po.DISPATCH_ENABLED is False)
check('H70. НИ ОДНОГО вызова транспорта/печати за весь тест: BOOM=%r' % (BOOM,), BOOM == [])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: удержание принтера непреодолимо для всех обычных стартов (в т.ч. под гонкой 10 потоков), '
              'снимается только своим владельцем, сосуществует с reservation и НЕ снимается ни телеметрией '
              'RUNNING, ни watchdog\'ом, ни отменой плана; переживает рестарт через rebuild из БД '
              '(идемпотентно, чужие удержания не трогает) и не сделал ни одного вызова печати'))
raise SystemExit(1 if fail else 0)
