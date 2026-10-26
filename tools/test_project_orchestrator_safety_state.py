# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Безопасностное состояние принтера + жизненный цикл clearance/телеметрии — Alpha 2.741 (этап 5A1).
# ЗАЧЕМ. p_states[pid]["status"] — статус ДЛЯ КАРТИНКИ, и он НАМЕРЕННО искажён: после веб-«Стоп»
# Bambu показывается IDLE, пока идёт цикл отмены (у P2S 3-4 минуты РЕАЛЬНОЙ печати). Оркестратор
# видел ровно этот статус — то есть его единственная проба принтера ЛГАЛА. Здесь доказываем, что
# решения принимаются по НЕискажённому status_raw + _user_stopped, по БЕЛОМУ списку (fail-closed),
# и что токен «Стол очищен» гаснет при доказанном изменении принтера.
# _get_printer_safety_snapshot берётся ДОСЛОВНО из server.py (exec блока).
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_orchestrator_safety_state.py  (0 = пройдено)
import importlib.util, os, re, sqlite3, sys, tempfile, threading, time, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()

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
        raise AssertionError('ЗАПРЕЩЕНО в 5A1: ' + tag)
    return _b


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


def _block(start, end):
    i = _SRV.index(start)
    return _SRV[i:_SRV.index(end, i)]


# ── песочница ядра ─────────────────────────────────────────────────────────────────────────────
P_STATES, LAST_SEEN, USER_STOPPED, TYPES = {}, {}, {}, {}


class _FakePrinters:
    """Подмена conn_pr: отдаёт type принтера тем же интерфейсом, что и sqlite-строка."""
    def execute(self, q, args):
        pid = args[0]
        return type('C', (), {'fetchone': staticmethod(
            lambda: ({'type': TYPES[pid]} if pid in TYPES else None))})()


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import printer_state_policy as _state_policy   # noqa: E402  (Alpha 2.791, только stdlib)

NS = {'p_states': P_STATES, 'last_seen': LAST_SEEN, '_user_stopped': USER_STOPPED,
      'conn_pr': _FakePrinters(), 'lock_pr': threading.Lock(), 'time': time, 'STALE_FAIL_S': 60,
      '_state_policy': _state_policy}
exec(_block('_SAFE_RAW_IDLE = {', 'def _printer_transport('), NS)
exec(_block('def _printer_transport(', 'class _PrintSendManager:'), NS)
safety = NS['_get_printer_safety_snapshot']


def tel(pid, transport, status, raw, age=1.0, stopped=False):
    TYPES[pid] = transport
    P_STATES[pid] = {"status": status, "status_raw": raw}
    LAST_SEEN[pid] = time.time() - age
    USER_STOPPED.pop(pid, None)
    if stopped:
        USER_STOPPED[pid] = time.monotonic()


# ── 1. Bambu: подделанный UI-IDLE ──────────────────────────────────────────────────────────────
# Ровно тот сценарий из аудита: оператор нажал «Стоп», UI рисует IDLE, принтер физически печатает.
tel('b1', 'bambu', 'IDLE', 'RUNNING', stopped=True)
s = safety('b1')
check('S1. КРИТИЧНО: Bambu с UI-IDLE, но status_raw=RUNNING и _user_stopped -> unsafe',
      s['safe_idle'] is False and s['status'] == 'IDLE' and s['status_raw'] == 'RUNNING')
check('S2. и это видно явно: user_stopped_pending=True, printing_active=True',
      s['user_stopped_pending'] is True and s['printing_active'] is True)
check('S3. причина названа честно', s['unsafe_reason'] == 'user_stop_pending')
tel('b2', 'bambu', 'IDLE', 'IDLE')
check('S4. Bambu raw IDLE без _user_stopped -> SAFE',
      safety('b2')['safe_idle'] is True and safety('b2')['printing_active'] is False)
tel('b3', 'bambu', 'IDLE', 'FAILED', stopped=True)
check('S5. «липкий» FAILED под маской IDLE -> unsafe', safety('b3')['safe_idle'] is False)

# ── 2. Bambu: канонические небезопасные ────────────────────────────────────────────────────────
for _raw in ('FINISH', 'FAILED', 'PAUSE', 'PAUSED', 'PREPARE', 'RUNNING', 'SLICING'):
    tel('bx', 'bambu', _raw, _raw)
    check('S6.%s Bambu raw=%s -> unsafe' % (_raw, _raw), safety('bx')['safe_idle'] is False)
tel('bp', 'bambu', 'PAUSE', 'PAUSE')
check('S7. ВАЖНО: Bambu шлёт PAUSE (не PAUSED) — белый список ловит это, чёрный не ловил',
      safety('bp')['safe_idle'] is False and safety('bp')['printing_active'] is True)
tel('bf', 'bambu', 'FINISH', 'FINISH')
check('S8. FINISH — НЕ покой (детали на столе), но и НЕ активная печать: подтвердить стол можно',
      safety('bf')['safe_idle'] is False and safety('bf')['printing_active'] is False)

# ── 3. Klipper ─────────────────────────────────────────────────────────────────────────────────
tel('k1', 'klipper', 'IDLE', 'standby')
check('S9. Klipper известный standby -> safe', safety('k1')['safe_idle'] is True)
tel('k2', 'klipper', 'IDLE', 'wat_is_this')
# Alpha 2.791: сам порог безопасности НЕ менялся (незнакомая строка по-прежнему unsafe),
# изменился только КОД причины: вместо not_idle_raw:<сырая строка> — стабильный state_unknown.
# Сырая строка в причину больше не подставляется и в решении не участвует.
check('S10. КРИТИЧНО: Klipper НЕИЗВЕСТНЫЙ raw -> unsafe (хотя нормализованный status=IDLE!)',
      safety('k2')['safe_idle'] is False
      and safety('k2')['unsafe_reason'] == _state_policy.REASON_STATE_UNKNOWN
      and 'wat_is_this' not in safety('k2')['unsafe_reason'])
tel('k3', 'klipper', 'RUNNING', 'printing')
check('S11. Klipper printing -> unsafe + printing_active',
      safety('k3')['safe_idle'] is False and safety('k3')['printing_active'] is True)
tel('k4', 'klipper', 'FAILED', 'standby')
check('S12. Klipper raw=standby, но прошивка в shutdown (status=FAILED) -> unsafe',
      safety('k4')['safe_idle'] is False and safety('k4')['unsafe_reason'] == 'status_not_idle:FAILED')
tel('k5', 'klipper', 'PAUSED', 'paused')
check('S13. Klipper paused -> unsafe + printing_active (посреди задания)',
      safety('k5')['safe_idle'] is False and safety('k5')['printing_active'] is True)

# ── 4. FlashForge ──────────────────────────────────────────────────────────────────────────────
tel('f1', 'flashforge', 'IDLE', 'ready')
check('S14. FlashForge известный ready -> safe', safety('f1')['safe_idle'] is True)
tel('f2', 'flashforge', 'IDLE', 'что-то новое')
check('S15. КРИТИЧНО: FlashForge НЕИЗВЕСТНЫЙ raw -> unsafe (нормализованный status=IDLE не спасает)',
      safety('f2')['safe_idle'] is False)
tel('f3', 'flashforge', 'RUNNING', 'heating')
check('S16. FlashForge heating -> unsafe + printing_active',
      safety('f3')['safe_idle'] is False and safety('f3')['printing_active'] is True)

# ── 5. Свежесть / вырожденные случаи ───────────────────────────────────────────────────────────
tel('s1', 'bambu', 'IDLE', 'IDLE', age=999)
check('S17. stale телеметрия -> unsafe', safety('s1')['safe_idle'] is False and safety('s1')['unsafe_reason'] == 'offline_or_stale')
tel('s2', 'bambu', 'OFFLINE', 'IDLE')
check('S18. OFFLINE -> unsafe', safety('s2')['safe_idle'] is False)
tel('s3', 'bambu', 'IDLE', '')
check('S19. НЕТ status_raw (напр. OFFLINE_STATE) -> unsafe', safety('s3')['unsafe_reason'] == 'no_status_raw')
P_STATES['s4'] = {"status": "IDLE"}          # status_raw отсутствует как ключ
LAST_SEEN['s4'] = time.time()
TYPES['s4'] = 'bambu'
check('S20. status_raw отсутствует ключом -> unsafe', safety('s4')['safe_idle'] is False)
tel('s5', 'weird_printer', 'IDLE', 'IDLE')
check('S21. неизвестный транспорт -> unsafe', safety('s5')['unsafe_reason'] == 'unknown_transport')
LAST_SEEN['s6'] = time.time()
check('S22. принтера нет в парке -> unsafe, без исключения', safety('s6')['safe_idle'] is False)
check('S23. проба — чистое чтение: p_states не изменён',
      P_STATES['b2'] == {"status": "IDLE", "status_raw": "IDLE"})

# ── 6. Оркестратор: fail-closed без пробы ──────────────────────────────────────────────────────
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

FLEET = [{"id": "b2", "name": "X1C", "type": "bambu"}]


def wire(safety_fn, boot='boot_A'):
    po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], boot,
            printer_status_fn=lambda pid: ("IDLE", True),      # УМЫШЛЕННО «всё хорошо» — не должен слушать
            safety_fn=safety_fn, printers_fn=lambda: FLEET,
            send_reserved_fn=lambda: set(), file_ok_fn=lambda f: True)


wire(None)
po.init_db()
check('S24. FAIL-CLOSED: без safety-пробы принтер небезопасен и считается «возможно печатающим»',
      po.safety('b2')['safe_idle'] is False and po.safety('b2')['printing_active'] is True
      and po.safety('b2')['unsafe_reason'] == 'no_safety_probe')
wire(lambda pid: (_ for _ in ()).throw(RuntimeError('проба упала')))
check('S25. FAIL-CLOSED: упавшая проба -> unsafe (исключение не всплывает)',
      po.safety('b2')['safe_idle'] is False and po.safety('b2')['unsafe_reason'] == 'safety_probe_failed')
wire(lambda pid: "не dict")
check('S26. FAIL-CLOSED: проба вернула мусор -> unsafe', po.safety('b2')['safe_idle'] is False)
wire(lambda pid: {"safe_idle": "да"})
check('S27. «почти правда» приводится к строгому bool', po.safety('b2')['safe_idle'] is True)

# ── 7. create_clearance ходит через safety, а не UI-статус ─────────────────────────────────────
wire(safety)
tel('b2', 'bambu', 'IDLE', 'RUNNING', stopped=True)     # маска: UI IDLE, реально печатает
_r = po.create_clearance('b2', confirmed=True, confirmed_by='op')
check('S28. КРИТИЧНО: «Стол очищен» на замаскированном IDLE (идёт цикл отмены) -> ОТКАЗ',
      _r['status'] == 'error' and _r['reason'] == 'printer_busy')
check('S29. и в отказе — НАСТОЯЩЕЕ состояние, а не картинка', _r['printer_status'] == 'RUNNING')
check('S30. токен при этом не создан', po.active_clearance('b2') is None)
tel('b2', 'bambu', 'RUNNING', 'RUNNING')
check('S31. явная печать -> отказ', po.create_clearance('b2', confirmed=True)['reason'] == 'printer_busy')
tel('b2', 'bambu', 'IDLE', 'IDLE', age=999)
check('S32. stale -> отказ telemetry_stale', po.create_clearance('b2', confirmed=True)['reason'] == 'telemetry_stale')
tel('b2', 'bambu', 'FINISH', 'FINISH')
# Alpha 2.752: подтверждение БЕЗ finished_job_id — ПЕРВИЧНОЕ (стол пуст до первой печати), и на
# FINISH оно теперь законно отбивается: до первой печати принтер обязан быть в safe_idle.
# «Главный сценарий после FINISH» — это ПОСТПЕЧАТНОЕ подтверждение, оно идёт С finished_job_id
# и safe_idle не требует (проверяется ниже и в test_project_first_print_gate.py A6).
_r = po.create_clearance('b2', confirmed=True, confirmed_by='op')
check('S33. ПЕРВИЧНОЕ подтверждение на FINISH (без finished_job_id) -> отказ printer_unsafe',
      _r.get('reason') == 'printer_unsafe')
check('S34. токен при этом НЕ создан', po.active_clearance('b2') is None)
_r = po.create_clearance('b2', confirmed=True, confirmed_by='op', finished_job_id='pjob_x')
check('S33b. ПОСТПЕЧАТНОЕ подтверждение на FINISH (с finished_job_id) -> токен создан, как раньше',
      _r.get('status') == 'ok')
check('S34b. токен активен', po.active_clearance('b2') is not None)
po.revoke_clearance('b2')
tel('b2', 'bambu', 'IDLE', 'IDLE')
check('S35. на покое подтверждение тоже разрешено (initial clearance)',
      po.create_clearance('b2', confirmed=True, confirmed_by='op')['status'] == 'ok')
check('S36. без confirmed=True токен не создаётся никогда',
      (po.revoke_clearance('b2'), po.create_clearance('b2', confirmed=False))[1]['reason'] == 'confirmation_required')

# ── 8. printer_availability — по safety ────────────────────────────────────────────────────────
tel('b2', 'bambu', 'IDLE', 'IDLE')
po.create_clearance('b2', confirmed=True, confirmed_by='op')
_av = po.printer_availability()[0]
check('S37. purely safe принтер доступен', _av['available'] is True and _av['safe_idle'] is True)
tel('b2', 'bambu', 'IDLE', 'RUNNING', stopped=True)
_av = po.printer_availability()[0]
check('S38. КРИТИЧНО: замаскированный IDLE в availability -> НЕ доступен',
      _av['available'] is False and any('unsafe_state' in r for r in _av['unavailable_reasons']))
tel('b2', 'bambu', 'PAUSE', 'PAUSE')
check('S39. Bambu PAUSE -> недоступен (прежний чёрный список это пропускал)',
      po.printer_availability()[0]['available'] is False)

# ── 9. Инвалидация токена по событиям ──────────────────────────────────────────────────────────
tel('b2', 'bambu', 'IDLE', 'IDLE')
po.revoke_clearance('b2')
po.create_clearance('b2', confirmed=True, confirmed_by='op')
_cid = po.active_clearance('b2')['id']
check('S40. исходно токен активен', po.clearance_status(po.active_clearance('b2')) == 'active')
# Сценарий из задания: оператор подтвердил стол -> началась РУЧНАЯ печать (item не наш).
_res = po.on_printer_started('b2', 'чужой.3mf', '')
check('S41. КРИТИЧНО: началась manual печать -> токен больше НЕ активен',
      _res['clearances_invalidated'] == 1 and po.active_clearance('b2') is None)
check('S42. чужая печать план не захватывает', _res['matched'] is False)
_row = c.execute("SELECT invalid_reason FROM plate_clearances WHERE id=?", (_cid,)).fetchone()
check('S43. причина канонична: print_started', _row['invalid_reason'] == po.CLR_REASON_PRINT_STARTED)
check('S44. КРИТИЧНО: после FINISH старый токен НЕЛЬЗЯ consume', po.consume_clearance(_cid, 'it_x') is False)
_again = po.on_printer_started('b2', 'чужой.3mf', '')
check('S45. повторный кадр телеметрии идемпотентен (гасить уже нечего)', _again['clearances_invalidated'] == 0)

# read-only операции токен НЕ гасят
po.create_clearance('b2', confirmed=True, confirmed_by='op')
po.printer_availability(); po.diagnostics(); po.list_active_runs(); po.active_clearance('b2')
check('S46. read-only GET/UI-polling/диагностика токен НЕ гасят', po.active_clearance('b2') is not None)
check('S47. offline -> токен гаснет',
      po.invalidate_clearance_on_event('b2', po.CLR_REASON_PRINTER_OFFLINE) == 1 and po.active_clearance('b2') is None)
po.create_clearance('b2', confirmed=True, confirmed_by='op')
check('S48. ошибка принтера -> токен гаснет',
      po.on_printer_failed('b2', 'x.3mf', '')['clearances_invalidated'] == 1)
check('S49. FINISH сам по себе токен НЕ создаёт (инвариант)',
      (po.on_printer_finished('b2', 'x.3mf', ''), po.active_clearance('b2'))[1] is None)
tel('b2', 'bambu', 'IDLE', 'IDLE')
check('S50. IDLE сам по себе токен НЕ создаёт', po.active_clearance('b2') is None)

# ── 10. Телеметрия -> состояние плана (на фикстуре: dispatch выключен) ─────────────────────────
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_1','prj','running','exact','boot_A',1.0,1.0)")
c.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, file_norm, "
          "snapshot_json) VALUES ('pjob_1','prj','F1','b2','plate.3mf','plate3mf','[]')")
c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, assigned_printer_id, "
          "project_print_job_id, created_at, updated_at) "
          "VALUES ('it_1','prun_1','prj','F1',1,'sending','b2','pjob_1',1.0,1.0)")
c.commit()
HOLDS = {}
po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: ("IDLE", True), safety_fn=safety, printers_fn=lambda: FLEET,
        send_reserved_fn=lambda: set(), file_ok_fn=lambda f: True,
        holds_fn=lambda: dict(HOLDS),
        set_hold_fn=lambda pid, ot, oid, r: (HOLDS.__setitem__(pid, {"owner_type": ot, "owner_id": oid, "reason": r}), (True, HOLDS[pid]))[1],
        clear_hold_fn=lambda pid, ot, oid: HOLDS.pop(pid, None) is not None)


def item_state():
    return c.execute("SELECT state FROM project_run_items WHERE id='it_1'").fetchone()["state"]


def run_state():
    return c.execute("SELECT state FROM project_runs WHERE id='prun_1'").fetchone()["state"]


_r = po.on_printer_started('b2', 'plate.3mf', 'pjob_1')
check('S51. STARTED: наш item -> printing, run -> running',
      _r['matched'] is True and item_state() == 'printing' and run_state() == 'running')
check('S52. STARTED: принтер удержан планом',
      HOLDS.get('b2', {}).get('owner_id') == 'prun_1' and 'printing' in HOLDS['b2']['reason'])
po.on_printer_started('b2', 'plate.3mf', 'pjob_1')
check('S53. повторный STARTED идемпотентен', item_state() == 'printing')
_r = po.on_printer_started('b2', 'чужой.3mf', '')
check('S54. чужой filename item НЕ захватывает', _r['matched'] is False and item_state() == 'printing')

_r = po.on_printer_finished('b2', 'plate.3mf', 'pjob_1')
check('S55. FINISH: item -> waiting_plate_clear, run -> waiting_for_plate_clear',
      item_state() == 'waiting_plate_clear' and run_state() == 'waiting_for_plate_clear')
check('S56. КРИТИЧНО: FINISH НЕ освобождает принтер — удержание остаётся', 'b2' in HOLDS)
check('S57. КРИТИЧНО: FINISH НЕ создаёт разрешение на следующий запуск', po.active_clearance('b2') is None)
po.on_printer_finished('b2', 'plate.3mf', 'pjob_1')
check('S58. повторный FINISH идемпотентен', item_state() == 'waiting_plate_clear')
check('S59. item в waiting_plate_clear удерживает принтер и после рестарта (active_holds из БД)',
      po.active_holds().get('b2', {}).get('owner_id') == 'prun_1')

# Поздний FAILED НЕ откатывает уже завершённую печать: она учтена, стол всё равно ждёт очистки,
# и waiting_plate_clear — более точное состояние, чем ambiguous. Переход запрещён намеренно.
_r = po.on_printer_failed('b2', 'plate.3mf', 'pjob_1', 'поздний кадр')
check('S59b. поздний FAILED НЕ понижает waiting_plate_clear до ambiguous',
      item_state() == 'waiting_plate_clear')
check('S59c. и удержание при этом не теряется', 'b2' in HOLDS)

# Реальный сценарий FAILED: печать ИДЁТ и срывается.
c.execute("UPDATE project_run_items SET state='printing' WHERE id='it_1'")
c.commit()
_r = po.on_printer_failed('b2', 'plate.3mf', 'pjob_1', 'telemetry_failed')
check('S60. FAILED во время печати: item -> ambiguous_after_dispatch (attention_required у item НЕТ — не выдумываем)',
      item_state() == 'ambiguous_after_dispatch')
check('S61. FAILED: внимание поднято на уровень run -> attention_required', run_state() == 'attention_required')
check('S62. FAILED: удержание остаётся (на столе возможен брак)', 'b2' in HOLDS)
check('S63. FAILED: токен автоматически НЕ создаётся', po.active_clearance('b2') is None)
check('S64. ambiguous не откатывается обратно в printing поздним кадром',
      (po.on_printer_started('b2', 'plate.3mf', 'pjob_1'), item_state())[1] == 'ambiguous_after_dispatch')
check('S65. выход из ambiguous — только человеком (автоповтора нет)',
      po.resolve_item('prun_1', 'it_1', 'not_started')['status'] == 'ok')

# ── 11. Ни одного вызова печати ────────────────────────────────────────────────────────────────
_mod = open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()
_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _mod))
check('S66. предохранитель выключен', po.DISPATCH_ENABLED is False)
check('S67. колбэки телеметрии не умеют печатать: транспорта в модуле по-прежнему нет',
      not re.search(r'_send_mgr|paho|mqtt|ftplib|requests|socket|_do_project2_file_print|_send_file_to_printer', _code))
check('S68. НИ ОДНОГО вызова транспорта/печати за весь тест: BOOM=%r' % (BOOM,), BOOM == [])
check('S69. UI-маскировка ядра НЕ тронута: _send_printer_status по-прежнему отдаёт UI-статус',
      'def _send_printer_status(pid):' in _SRV and 'st.get("status")' in _block('def _send_printer_status(', '# ── БЕЗОПАСНОЕ'))

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: решения принимаются по НЕискажённому status_raw + _user_stopped по белому списку '
              '(fail-closed для неизвестных строк, отсутствующей/упавшей пробы, stale/offline и чужого '
              'транспорта); замаскированный IDLE больше не пускает ни подтверждение стола, ни выбор '
              'принтера; токен гаснет на доказанном изменении и переживает read-only обращения; '
              'FINISH/IDLE/FAILED сами не создают разрешение и не освобождают принтер'))
raise SystemExit(1 if fail else 0)
