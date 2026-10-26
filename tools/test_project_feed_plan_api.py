# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# API плана подачи (кандидаты / выбор / согласие / отзыв) — core Alpha 2.744 (этап 5A3a).
# ЗАЧЕМ. Это первый API, которым человек говорит «печатай ЭТИМ». Поэтому доказываем не «отвечает
# 200», а что он не может навредить: read-only остаётся read-only (побайтовый снимок БД), телу
# запроса не верят (материал/цвет/статус пересчитываются сервером), согласие покрывает ВЕСЬ перечень
# требований, устаревший отпечаток отклоняется, активный item не переписывается, и ни один вызов
# печати/резервации/планировщика не происходит.
# Проверяется СЕРВИСНЫЙ слой (он несёт http-коды) + статически доказывается, что роуты в server.py
# ведут именно в него. Приложение не поднимается: импорт server.py тронул бы боевую DATA_DIR.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_feed_plan_api.py   (0 = пройдено)
import importlib.util, json, os, re, sqlite3, tempfile, threading, uuid

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
        raise AssertionError('ЗАПРЕЩЕНО в 5A3a: ' + tag)
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
c.execute("INSERT INTO projects (id, name) VALUES ('prj2','P2')")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F2','prj2','other.3mf','h2',1)")
c.commit()

LOCK = threading.Lock()
FLEET = [{"id": "pr1", "name": "X1C", "type": "bambu", "order_idx": 0}]
TRANSPORT = {"pr1": "bambu"}
COMPAT = {"pr1"}
SNAP = {}          # printer_id -> generic snapshot склада
REPORTED = {}      # printer_id -> отчётная телеметрия
REQ = {"status": "ok", "reason": "", "filament_count": 1, "file_hash": "h1", "plate": "1", "nozzle": "0.4",
       "source": "3mf:project_settings",
       "filaments": [{"file_index": 0, "material": "PETG", "color_hex": "#161616"}]}
_bombs = {'scheduler': bomb('_scheduler_tick_core'), 'reserve': bomb('_send_mgr.reserve'),
          'run': bomb('_send_mgr.run'), 'do_print': bomb('_do_project2_file_print'),
          'send_file': bomb('_send_file_to_printer'), 'pjob': bomb('create_project_print_job'),
          'mqtt': bomb('mqtt.publish'), 'ftp': bomb('ftp.storbinary'), 'http': bomb('http_transport'),
          'after': bomb('after_dispatch'), 'ledger': bomb('inv_ledger')}


def SAFETY(pid):
    return {"printer_id": pid, "transport": TRANSPORT.get(pid, "bambu"), "status": "IDLE",
            "status_raw": "IDLE", "fresh": True, "user_stopped_pending": False,
            "printing_active": False, "safe_idle": True, "unsafe_reason": ""}


po.init(c, LOCK, lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: ("IDLE", True), safety_fn=SAFETY,
        printers_fn=lambda: list(FLEET), send_reserved_fn=lambda: set(), file_ok_fn=lambda f: True,
        file_requirements_fn=lambda fr: dict(REQ),
        filament_snapshot_fn=lambda pid: dict(SNAP.get(pid) or {}),
        reported_filament_fn=lambda pid: dict(REPORTED.get(pid) or {}))
po.init_db()
COMPAT_FN = lambda frow: set(COMPAT)


def spool(sid, mat, color):
    return {"id": sid, "material": mat, "color_hex": color, "vendor_name": "V", "color_name": "n"}


def inv_row(index, external, sid, mat, color, bound=True):
    r = {"index": index, "unit": None, "tray": None, "external": external, "offline": False,
         "spool": spool(sid, mat, color)}
    if bound:
        r.update({"inventory_bound": True, "source": "inventory"})
    return r


def rep_pos(index, external, mat, color, present=True):
    return {"index": index, "unit": None, "tray": None, "external": external, "present": present,
            "reported_material": mat, "reported_color": color}


def reported(positions, fresh=True, avail=True):
    return {"telemetry_available": avail, "telemetry_fresh": fresh, "positions": positions}


def reset(state='pending', run='prun_1', proj='prj', fid='F1'):
    c.execute("DELETE FROM project_runs"); c.execute("DELETE FROM project_run_items")
    c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
              "VALUES (?,?,'running','exact','boot_A',1.0,1.0)", (run, proj))
    c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, created_at, updated_at) "
              "VALUES ('it_1',?,?,?,1,?,1.0,1.0)", (run, proj, fid, state))
    c.commit()
    SNAP.clear(); REPORTED.clear()


def db_snap():
    out = {}
    for t in [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        out[t] = [tuple(repr(v) for v in r) for r in c.execute("SELECT * FROM %s" % t).fetchall()]
    return out


def cands(run='prun_1', item='it_1'):
    return po.feed_candidates(run, item, COMPAT_FN)


def istate(iid='it_1'):
    return c.execute("SELECT state FROM project_run_items WHERE id=?", (iid,)).fetchone()["state"]


def stored(iid='it_1'):
    return c.execute("SELECT feed_plan_json FROM project_run_items WHERE id=?", (iid,)).fetchone()[0]


# ══ A. Кандидаты (read-only) ══════════════════════════════════════════════════════════════════
for _slot, _ext, _label in ((-1, True, 'external -1'), (0, False, 'AMS0'), (5, False, 'multi-AMS5'),
                            (512, False, 'AMS HT512')):
    reset()
    SNAP['pr1'] = {"has_ams": not _ext, "slots": [inv_row(_slot, _ext, "sp_%d" % _slot, "PETG", "#161616")]}
    REPORTED['pr1'] = reported([rep_pos(None if _ext else _slot, _ext, "PETG", "#161616")])
    r = cands()
    #  16.09.2026. У внешней подачи Bambu материал — это ВЫБОР НА ЭКРАНЕ принтера, а не показание
    #  датчика: датчика наличия там нет, и выбранный тип остаётся, когда катушка кончилась или её
    #  сняли. Поэтому внешний кандидат больше не ready, а approval_required с причиной
    #  inventory_declared — подтверждает человек. У позиции AMS подтверждение датчиком есть, там
    #  по-прежнему ready. Отчётная телеметрия помечает это полем presence (sensor|setting).
    _want = 'approval_required' if _ext else 'ready'
    check('A.%s exact -> ровно один кандидат, %s, слот сохранён точно' % (_label, _want),
          r['status'] == 'ok' and len(r['candidates']) == 1
          and r['candidates'][0]['status'] == _want and r['candidates'][0]['ams_slot'] == _slot
          and r['candidates'][0]['mode'] == ('external' if _ext else 'ams'))
    check('A.%s selected — этот же кандидат, сводка верна' % _label,
          r['selected'] and r['selected']['ams_slot'] == _slot and r['summary'][_want] == 1)
    if _ext:
        check('A.%s причина названа словами: заявлено складом, нужно согласие человека' % _label,
              r['candidates'][0]['reason'] == 'inventory_declared'
              and r['candidates'][0]['required_approval_reasons'] == ['inventory_declared']
              and r['candidates'][0]['verification'] == 'inventory_declared')
    check('A.%s кандидат несёт отпечаток и имя принтера' % _label,
          r['candidates'][0]['fingerprint'] and r['candidates'][0]['printer_name'] == 'X1C')

# A4b. НЕ ВАКУУМ к предыдущему: та же внешняя позиция, но подтверждённая ДАТЧИКОМ
# (presence='sensor'), снова даёт ready. Значит правило смотрит на доказательство, а не на слово
# «внешняя», и проверка меряет разницу, а не саму себя.
reset()
SNAP['pr1'] = {"has_ams": False, "slots": [inv_row(-1, True, "sp_sensor", "PETG", "#161616")]}
_rp_sensor = rep_pos(None, True, "PETG", "#161616")
_rp_sensor["presence"] = "sensor"
REPORTED['pr1'] = reported([_rp_sensor])
r = cands()
check('A.external -1 с датчиком -> ready (правило смотрит на доказательство, а не на слово «внешняя»)',
      len(r['candidates']) == 1 and r['candidates'][0]['status'] == 'ready'
      and r['candidates'][0]['verification'] == 'telemetry_confirmed'
      and r['summary']['ready'] == 1)

# A5. Стабильный порядок нескольких принтеров/слотов
FLEET = [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0},
         {"id": "pr2", "name": "B", "type": "bambu", "order_idx": 1}]
TRANSPORT.update({"pr2": "bambu"}); COMPAT = {"pr1", "pr2"}
reset()
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(5, False, "sp_5", "PETG", "#191919"),      # close
                                          inv_row(0, False, "sp_0", "PETG", "#161616")]}     # exact
SNAP['pr2'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_p2", "PETG", "#161616"),     # exact
                                          inv_row(3, False, "sp_bad", "PLA", "#161616")]}    # blocked
REPORTED['pr1'] = reported([rep_pos(0, False, "PETG", "#161616"), rep_pos(5, False, "PETG", "#191919")])
REPORTED['pr2'] = reported([rep_pos(0, False, "PETG", "#161616"), rep_pos(3, False, "PLA", "#161616")])
r = cands()
_ord = [(x['printer_id'], x['ams_slot'], x['status']) for x in r['candidates']]
check('A5a. порядок: ready -> approval -> blocked; внутри ready — по order_idx принтера',
      _ord == [('pr1', 0, 'ready'), ('pr2', 0, 'ready'), ('pr1', 5, 'approval_required'),
               ('pr2', 3, 'blocked')])
check('A5b. selected — первый пригодный (pr1/AMS0)', r['selected']['printer_id'] == 'pr1'
      and r['selected']['ams_slot'] == 0)
check('A5c. сводка по статусам верна',
      r['summary'] == {'ready': 2, 'approval_required': 1, 'attention_required': 0, 'blocked': 1})
_r2 = cands()
check('A5d. повторный вызов даёт БАЙТ-В-БАЙТ тот же ответ (детерминизм)',
      json.dumps(r, sort_keys=True, ensure_ascii=False) == json.dumps(_r2, sort_keys=True, ensure_ascii=False))
FLEET = [{"id": "pr1", "name": "X1C", "type": "bambu", "order_idx": 0}]
COMPAT = {"pr1"}

# A6. READ-ONLY
reset()
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#161616")]}
REPORTED['pr1'] = reported([rep_pos(0, False, "PETG", "#161616")])
_before = db_snap()
cands(); cands(); cands()
check('A6a. КРИТИЧНО: GET кандидатов — полностью read-only (БД байт-в-байт)', db_snap() == _before)
check('A6b. план НЕ сохраняется автоматически', stored() == '{}')
check('A6c. согласие не создаётся', po.read_feed_plan('it_1') is None)

# A7-A10
reset()
SNAP['pr1'] = {"has_ams": True, "slots": []}
r = cands()
check('A7. нет складского источника -> кандидат attention/inventory_source_unavailable',
      r['candidates'] and r['candidates'][0]['status'] == 'attention_required'
      and r['candidates'][0]['reason'] == 'inventory_source_unavailable' and r['selected'] is None)
reset()
SNAP['pr1'] = {"has_ams": True, "slots": [{"index": 0, "external": False,
                                           "spool": spool("sp_x", "PETG", "#161616")}]}   # без inventory_bound
check('A8. telemetry-only строка кандидатом НЕ является',
      cands()['candidates'][0]['reason'] == 'inventory_source_unavailable')
reset()
_save = dict(REQ)
REQ = {"status": "error", "reason": "file_missing", "filament_count": 0, "filaments": []}
r = cands()
check('A9a. файл пропал -> кандидатов нет, причина названа',
      r['candidates'] == [] and r['reason'] == 'file_missing' and r['selected'] is None)
REQ = {"status": "error", "reason": "file_hash_changed", "filament_count": 0, "filaments": []}
check('A9b. хеш изменился -> кандидатов нет', cands()['reason'] == 'file_hash_changed')
REQ = dict(_save, filament_count=2, filaments=[{"file_index": 0, "material": "PETG", "color_hex": "#161616"},
                                               {"file_index": 1, "material": "PLA", "color_hex": "#FFFFFF"}])
r = cands()
check('A10. multi-filament -> кандидатов нет, blocked/multi_filament_not_supported',
      r['candidates'] == [] and r['reason'] == 'multi_filament_not_supported')
REQ = dict(_save)

# ══ S. Выбор кандидата ════════════════════════════════════════════════════════════════════════
def setup_ready():
    reset()
    SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#161616")]}
    REPORTED['pr1'] = reported([rep_pos(0, False, "PETG", "#161616")])
    return cands()['candidates'][0]


cd = setup_ready()
r = po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', cd['fingerprint'], COMPAT_FN)
check('S1a. exact ready -> план сохранён', r['status'] == 'ok' and r['feed_plan']['ams_slot'] == 0)
check('S1b. сохранён именно он и effective ready',
      json.loads(stored())['spool_id'] == 'sp_0' and po.read_feed_plan('it_1')['effective_status'] == 'ready')
check('S1c. item остался pending; ни резервации, ни разрешения, ни удержания не появилось',
      istate() == 'pending' and c.execute("SELECT COUNT(*) n FROM plate_clearances").fetchone()['n'] == 0)
_pre = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
r2 = po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', cd['fingerprint'], COMPAT_FN)
check('S9. повторный идентичный select идемпотентен (updated_at не дёргается)',
      r2['status'] == 'ok' and r2['idempotent'] is True
      and dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone()) == _pre)

cd = setup_ready()
r = po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', None, COMPAT_FN)
check('S2a. телу запроса не верят: материал/цвет пересчитаны сервером',
      r['status'] == 'ok' and r['feed_plan']['required_material'] == 'PETG'
      and r['feed_plan']['inventory_color'] == '#161616')
_sel_src = _MOD[_MOD.index('def api_feed_select'):_MOD.index('def api_feed_approve')]
check('S2b. статика: сервис не принимает material/color/status из тела вообще',
      not re.search(r'material|color|status\s*=', _sel_src.split('"""')[2]))
cd = setup_ready()
_r = po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', 'ЧУЖОЙ_ОТПЕЧАТОК', COMPAT_FN)
check('S3. устаревший отпечаток -> 409 feed_plan_stale + фактический отпечаток в ответе',
      _r['status'] == 'error' and _r['reason'] == 'feed_plan_stale' and _r['http'] == 409
      and _r['fingerprint'] == cd['fingerprint'])
check('S3b. при устаревшем отпечатке план НЕ сохранён', stored() == '{}')

reset()
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#191919")]}   # close
REPORTED['pr1'] = reported([rep_pos(0, False, "PETG", "#191919")])
cd = cands()['candidates'][0]
r = po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', cd['fingerprint'], COMPAT_FN)
check('S4. approval_required -> 409 feed_plan_approval_required + перечень причин',
      r['reason'] == 'feed_plan_approval_required' and r['http'] == 409
      and r['required_approval_reasons'] == ['close_color'])
check('S4b. план при отказе НЕ сохранён', stored() == '{}')

reset()
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PLA", "#161616")]}   # material mismatch
REPORTED['pr1'] = reported([rep_pos(0, False, "PLA", "#161616")])
cd = cands()['candidates'][0]
r = po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', cd['fingerprint'], COMPAT_FN)
check('S5. blocked -> 409 с точной канонической причиной',
      r['http'] == 409 and r['reason'] == 'material_mismatch' and stored() == '{}')

setup_ready()
check('S6a. неизвестный run -> 404', po.api_feed_select('НЕТ', 'it_1', 'pr1', 0, 'sp_0', None, COMPAT_FN)
      == {'status': 'error', 'reason': 'run_not_found', 'http': 404})
check('S6b. неизвестный item -> 404', po.api_feed_select('prun_1', 'НЕТ', 'pr1', 0, 'sp_0', None, COMPAT_FN)
      == {'status': 'error', 'reason': 'item_not_found', 'http': 404})
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_2','prj2','running','exact','boot_A',2.0,1.0)")
c.commit()
check('S7. item ЧУЖОГО run -> отказ 404 item_not_in_run',
      po.api_feed_select('prun_2', 'it_1', 'pr1', 0, 'sp_0', None, COMPAT_FN)['reason'] == 'item_not_in_run')
check('S7b. несовместимый принтер -> 409',
      po.api_feed_select('prun_1', 'it_1', 'pr_ЧУЖОЙ', 0, 'sp_0', None, COMPAT_FN)['reason'] == 'printer_incompatible')
check('S7c. несуществующая пара слот/катушка -> 409 candidate_not_found',
      po.api_feed_select('prun_1', 'it_1', 'pr1', 7, 'sp_НЕТ', None, COMPAT_FN)['reason'] == 'candidate_not_found')

for _st in ('leased', 'sending', 'waiting_start_confirmation', 'printing', 'waiting_plate_clear'):
    setup_ready()
    c.execute("UPDATE project_run_items SET state=? WHERE id='it_1'", (_st,)); c.commit()
    r = po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', None, COMPAT_FN)
    check('S8.%s активный item (%s) -> 409 item_already_active, план не тронут' % (_st, _st),
          r['reason'] == 'item_already_active' and r['http'] == 409 and stored() == '{}')

# ══ P. Согласие ═══════════════════════════════════════════════════════════════════════════════
def setup_close(transport='bambu'):
    """Близкий цвет. bambu -> причина одна; klipper -> ДВЕ (нет датчика)."""
    reset()
    TRANSPORT['pr1'] = transport
    SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#191919")]}
    REPORTED['pr1'] = (reported([rep_pos(0, False, "PETG", "#191919")]) if transport == 'bambu'
                       else reported([], fresh=False, avail=False))
    return cands()['candidates'][0]


cd = setup_close('bambu')
check('P1a. близкий цвет требует РОВНО одну причину', cd['required_approval_reasons'] == ['close_color'])
r = po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=True,
                        approved_by='оператор', expected_fingerprint=cd['fingerprint'], compat_fn=COMPAT_FN)
check('P1b. согласие принято -> effective_status=ready', r['status'] == 'ok'
      and r['feed_plan']['effective_status'] == 'ready')
check('P1c. ИСХОДНЫЕ факты сохранены (почему было спорно — видно)',
      r['feed_plan']['status'] == 'approval_required' and r['feed_plan']['color_relation'] == 'close'
      and r['feed_plan']['requires_approval'] is True)
check('P1d. approval_valid=True и причины записаны',
      r['feed_plan']['approval_valid'] is True and r['feed_plan']['approved_reasons'] == ['close_color'])
check('P1e. план сохранён в БД', json.loads(stored())['approval']['approved_by'] == 'оператор')

reset()
TRANSPORT['pr1'] = 'klipper'
SNAP['pr1'] = {"has_ams": False, "slots": [inv_row(-1, True, "sp_k", "PETG", "#161616")]}   # exact цвет
REPORTED['pr1'] = reported([], fresh=False, avail=False)
cd = cands()['candidates'][0]
check('P2a. Klipper exact цвет -> ровно одна причина inventory_declared',
      cd['required_approval_reasons'] == ['inventory_declared'])
r = po.api_feed_approve('prun_1', 'it_1', 'pr1', -1, 'sp_k', ['inventory_declared'], confirmed=True,
                        expected_fingerprint=cd['fingerprint'], compat_fn=COMPAT_FN)
check('P2b. согласие принято -> ready, слот -1 сохранён',
      r['status'] == 'ok' and r['feed_plan']['effective_status'] == 'ready' and r['feed_plan']['ams_slot'] == -1)

# P3-P5: ДВЕ причины одновременно — главный сценарий этого этапа
cd = setup_close('klipper')
check('P3a. КРИТИЧНО: близкий цвет + отсутствие датчика -> ОБЕ причины (раньше терялась вторая)',
      cd['required_approval_reasons'] == ['close_color', 'inventory_declared'])
r = po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color', 'inventory_declared'],
                        confirmed=True, expected_fingerprint=cd['fingerprint'], compat_fn=COMPAT_FN)
check('P3b. согласие на ОБЕ причины -> ready',
      r['status'] == 'ok' and r['feed_plan']['effective_status'] == 'ready'
      and r['feed_plan']['approved_reasons'] == ['close_color', 'inventory_declared'])
cd = setup_close('klipper')
for _one in (['close_color'], ['inventory_declared']):
    r = po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', _one, confirmed=True,
                            expected_fingerprint=cd['fingerprint'], compat_fn=COMPAT_FN)
    check('P4.%s КРИТИЧНО: согласие только на %r -> approval_incomplete, план НЕ сохранён'
          % (_one[0], _one),
          r['reason'] == 'approval_incomplete' and r['http'] == 409
          and r['required_approval_reasons'] == ['close_color', 'inventory_declared'] and stored() == '{}')
check('P5a. неизвестная причина -> 400',
      po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color', 'потому_что_хочу'],
                          confirmed=True, compat_fn=COMPAT_FN)
      == {'status': 'error', 'reason': 'unknown_approval_reason', 'http': 400, 'unknown': ['потому_что_хочу']})
cd = setup_close('bambu')
check('P5b. ЛИШНЯЯ (не требуемая) причина -> отказ, а не «и так сойдёт»',
      po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color', 'inventory_declared'],
                          confirmed=True, expected_fingerprint=cd['fingerprint'],
                          compat_fn=COMPAT_FN)['reason'] == 'approval_incomplete')
for _cf in (False, None, 'true', 1):
    check('P6.%r confirmed=%r -> 400 confirmation_required' % (_cf, _cf),
          po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=_cf,
                              compat_fn=COMPAT_FN) == {'status': 'error', 'reason': 'confirmation_required',
                                                       'http': 400})

# P7-P9: чего согласием НЕ починить
reset()
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#FF0000")]}   # ΔE > 5
REPORTED['pr1'] = reported([rep_pos(0, False, "PETG", "#FF0000")])
TRANSPORT['pr1'] = 'bambu'
cd = cands()['candidates'][0]
check('P7. ΔE00 > 5 нельзя approve (не approvable, план не сохранён)',
      po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=True,
                          expected_fingerprint=cd['fingerprint'], compat_fn=COMPAT_FN)['reason'] == 'not_approvable'
      and stored() == '{}')
reset()
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PLA", "#161616")]}
REPORTED['pr1'] = reported([rep_pos(0, False, "PLA", "#161616")])
cd = cands()['candidates'][0]
check('P8. несовпадение материала нельзя approve',
      po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color', 'inventory_declared'],
                          confirmed=True, compat_fn=COMPAT_FN)['reason'] in ('not_approvable', 'approval_incomplete')
      and stored() == '{}')
reset()
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#161616")]}
REPORTED['pr1'] = reported([rep_pos(0, False, "PETG", "#161616")], fresh=False)
cd = cands()['candidates'][0]
check('P9. устаревшая телеметрия Bambu нельзя approve',
      cd['status'] == 'attention_required' and cd['reason'] == 'telemetry_stale'
      and po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['inventory_declared'], confirmed=True,
                              compat_fn=COMPAT_FN)['reason'] in ('not_approvable', 'approval_incomplete'))
reset()
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#161616")]}
REPORTED['pr1'] = reported([rep_pos(0, False, None, None, present=False)])
check('P9b. пустой слот нельзя approve',
      po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['inventory_declared'], confirmed=True,
                          compat_fn=COMPAT_FN)['reason'] in ('not_approvable', 'approval_incomplete'))
_save2 = dict(REQ)
REQ = {"status": "error", "reason": "file_hash_changed", "filament_count": 0, "filaments": []}
check('P9c. изменившийся файл нельзя approve',
      po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=True,
                          compat_fn=COMPAT_FN)['reason'] == 'file_hash_changed')
REQ = dict(_save2, filament_count=2, filaments=[{"file_index": 0, "material": "PETG", "color_hex": "#161616"},
                                                {"file_index": 1, "material": "PLA", "color_hex": "#FFF"}])
check('P9d. multi-filament нельзя approve',
      po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=True,
                          compat_fn=COMPAT_FN)['reason'] == 'multi_filament_not_supported')
REQ = dict(_save2)

cd = setup_close('bambu')
check('P10. отпечаток изменился -> 409 feed_plan_stale',
      po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=True,
                          expected_fingerprint='ЧУЖОЙ', compat_fn=COMPAT_FN)['reason'] == 'feed_plan_stale')
cd = setup_close('bambu')
r1 = po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=True,
                         approved_by='оператор', expected_fingerprint=cd['fingerprint'],
                         compat_fn=COMPAT_FN, now=100.0)
_pre = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
r2 = po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=True,
                         approved_by='оператор', expected_fingerprint=cd['fingerprint'],
                         compat_fn=COMPAT_FN, now=999.0)
check('P11. повторное идентичное согласие идемпотентно (время не переписывается, строка не тронута)',
      r2['status'] == 'ok' and r2['idempotent'] is True
      and json.loads(stored())['approval']['approved_at'] == 100.0
      and dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone()) == _pre)

# P12: смена фактов обесценивает согласие
_ap_plan = json.loads(stored())
for _fld, _val in (('spool_id', 'sp_ДРУГАЯ'), ('ams_slot', 7), ('inventory_color', '#00FF00'),
                   ('inventory_material', 'PLA'), ('reported_color', '#00FF00'), ('file_hash', 'h9')):
    _t = dict(_ap_plan)
    _t[_fld] = _val
    check('P12.%s согласие НЕдействительно после смены «%s»' % (_fld, _fld),
          po.feed_plan_effective_status(_t) == 'approval_required')
SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#1D1D1D")]}   # цвет катушки сменили
REPORTED['pr1'] = reported([rep_pos(0, False, "PETG", "#1D1D1D")])
check('P12z. КРИТИЧНО: реально сменили катушку -> сохранённое согласие больше не ready',
      po.feed_plan_effective_status(po.build_feed_plan('prun_1', 'it_1', 'pr1')) == 'approval_required'
      and cands()['candidates'][0]['effective_status'] == 'approval_required')

check('P13. approved_by из ТЕЛА запроса не принимается: роут берёт identity сессии',
      "_feed_approved_by(req)" in _SRV and "НЕ из тела запроса" in _SRV
      and not re.search(r'approved_by\s*=\s*(?:str\()?d\.get\("approved_by"', _SRV))
_api_src = _MOD[_MOD.index('# 6c-bis.'):_MOD.index('# 6d. АТОМАРНЫЙ LEASE')]
_api_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _api_src))
check('P14. API не пишет ни в ledger/Inventory/Quality/Cost, ни в чужие таблицы',
      not re.search(r'inv_ledger|farm_inventory|inv_spools|quality|cost', _api_code)
      and set(re.findall(r'(?:INSERT INTO|UPDATE)\s+(\w+)', _api_code)) <= {'project_run_items'})

# ══ C. Отзыв плана ════════════════════════════════════════════════════════════════════════════
cd = setup_ready()
po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', cd['fingerprint'], COMPAT_FN)
check('C1a. план сохранён перед отзывом', stored() != '{}')
_pre = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
_before_all = db_snap()
r = po.api_feed_clear('prun_1', 'it_1', confirmed=True)
check('C1b. отзыв выполнен -> план пуст, ответ безопасный',
      r['status'] == 'ok' and r['cleared'] is True and r['feed_plan'] is None and stored() == '{}')
_post = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
check('C4. КРИТИЧНО: изменились РОВНО feed_plan_json и updated_at',
      {k for k in _pre if _pre[k] != _post[k]} == {'feed_plan_json', 'updated_at'})
_after_all = db_snap()
check('C5. КРИТИЧНО: разрешения/удержания/резервации/run не тронуты — чужие таблицы байт-в-байт',
      all(_before_all[t] == _after_all[t] for t in _before_all if t != 'project_run_items'))
_p2 = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
r = po.api_feed_clear('prun_1', 'it_1', confirmed=True)
check('C2. повторный отзыв идемпотентен (строка не тронута вовсе)',
      r['status'] == 'ok' and r['idempotent'] is True
      and dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone()) == _p2)
check('C2b. без confirmed отзыв не выполняется',
      po.api_feed_clear('prun_1', 'it_1', confirmed=False) == {'status': 'error',
                                                               'reason': 'confirmation_required', 'http': 400})
for _st in ('sending', 'printing', 'waiting_plate_clear'):
    setup_ready()
    po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', None, COMPAT_FN)
    _saved = stored()
    c.execute("UPDATE project_run_items SET state=? WHERE id='it_1'", (_st,)); c.commit()
    r = po.api_feed_clear('prun_1', 'it_1', confirmed=True)
    check('C3.%s активный item (%s) отозвать нельзя -> 409, план цел' % (_st, _st),
          r['reason'] == 'item_already_active' and r['http'] == 409 and stored() == _saved)
check('C_name. отзыв плана и отзыв «Стол очищен» — РАЗНЫЕ вещи и разные маршруты',
      'feed-plan/clear' in _SRV and 'plate-clear/revoke' in _SRV
      and 'НЕ отзыв подтверждения «Стол очищен»' in _MOD)

# ══ X. Безопасность и гонки ═══════════════════════════════════════════════════════════════════
cd = setup_ready()
po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', cd['fingerprint'], COMPAT_FN)
_raw = stored()
check('X1a. в сохранённом JSON нет секретов/путей/nonce',
      not re.search(r'(?i)token|password|access|bblp|nonce|\d+\.\d+\.\d+\.\d+|[A-Za-z]:\\\\|/mnt/|ftp|mqtt', _raw))
_cand_json = json.dumps(cands(), ensure_ascii=False)
check('X1b. в ответе кандидатов нет секретов/путей/state_snapshot',
      not re.search(r'(?i)token|password|access|bblp|nonce|state_snapshot|\d+\.\d+\.\d+\.\d+|[A-Za-z]:\\\\',
                    _cand_json))
check('X1c. кандидат отдаёт только whitelist-поля',
      all(set(x) <= set(po._CAND_PUBLIC) for x in cands()['candidates']))

# X2: два разных согласия одновременно
cd = setup_close('bambu')
_res, _lk = [], threading.Lock()
_bar = threading.Barrier(2)


def _appr(slot_spool):
    _bar.wait()
    r = po.api_feed_approve('prun_1', 'it_1', 'pr1', slot_spool[0], slot_spool[1], ['close_color'],
                            confirmed=True, expected_fingerprint=cd['fingerprint'], compat_fn=COMPAT_FN)
    with _lk:
        _res.append(r.get('status'))


SNAP['pr1'] = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#191919"),
                                          inv_row(5, False, "sp_5", "PETG", "#191919")]}
REPORTED['pr1'] = reported([rep_pos(0, False, "PETG", "#191919"), rep_pos(5, False, "PETG", "#191919")])
_t1 = threading.Thread(target=_appr, args=((0, 'sp_0'),))
_t2 = threading.Thread(target=_appr, args=((5, 'sp_5'),))
_t1.start(); _t2.start(); _t1.join(); _t2.join()
_final = json.loads(stored()) if stored() != '{}' else None
check('X2. два РАЗНЫХ согласия одновременно -> сохранён ровно один целостный план (без смеси)',
      _final is not None and _final['spool_id'] in ('sp_0', 'sp_5')
      and _final['ams_slot'] == (0 if _final['spool_id'] == 'sp_0' else 5)
      and _final['approval']['fingerprint'] == po.feed_fingerprint(_final))

# X3: согласие против начавшегося lease
cd = setup_ready()
c.execute("UPDATE project_run_items SET state='leased', assigned_printer_id='pr1' WHERE id='it_1'")
c.commit()
r = po.api_feed_approve('prun_1', 'it_1', 'pr1', 0, 'sp_0', ['close_color'], confirmed=True,
                        compat_fn=COMPAT_FN)
check('X3. КРИТИЧНО: согласие против начавшегося lease -> 409 item_already_active, план не тронут',
      r['reason'] == 'item_already_active' and r['http'] == 409 and stored() == '{}')

# X5: битый сохранённый JSON
setup_ready()
c.execute("UPDATE project_run_items SET feed_plan_json='{это не json' WHERE id='it_1'"); c.commit()
check('X5a. битый JSON: get_run не падает, честно feed_plan_corrupt',
      po.get_run('prun_1')['items'][0]['feed_plan']['reason'] == 'feed_plan_corrupt')
check('X5b. битый JSON: кандидаты считаются заново и не падают', cands()['status'] == 'ok')
_cd = cands()['candidates'][0]
check('X5c. битый JSON: select пересчитывает и перезаписывает план',
      po.api_feed_select('prun_1', 'it_1', 'pr1', 0, 'sp_0', _cd['fingerprint'], COMPAT_FN)['status'] == 'ok'
      and json.loads(stored())['spool_id'] == 'sp_0')
check('X5d. сырое содержимое наружу не отдаётся', 'это не json' not in json.dumps(cands(), ensure_ascii=False))

# ══ Роуты и no-dispatch ═══════════════════════════════════════════════════════════════════════
for _p, _fn in (('/feed-candidates', 'feed_candidates'), ('/feed-plan/select', 'api_feed_select'),
                ('/feed-plan/approve', 'api_feed_approve'), ('/feed-plan/clear', 'api_feed_clear')):
    check('R.%s роут объявлен и ведёт в сервис оркестратора' % _p,
          ('"/api/project-runs/{run_id}/items/{item_id}%s"' % _p) in _SRV and ('_orch.%s(' % _fn) in _SRV)
check('R5. GET кандидатов объявлен именно как GET',
      '@app.get("/api/project-runs/{run_id}/items/{item_id}/feed-candidates")' in _SRV)
check('X4a. статика: сервисы API не зовут планировщик/резервацию/lease/hold/clearance',
      not re.search(r'_scheduler_tick_core|scheduler_tick|reserve|cancel_reserved|set_hold|clear_hold'
                    r'|consume_clearance|_lease_item_tx|_send_mgr', _api_code))
check('X4b. статика: сервисы API не зовут транспорт/печать/создание задания',
      not re.search(r'_do_project2_file_print|_send_file_to_printer|create_project_print_job'
                    r'|\bafter_dispatch\b|\bmqtt|ftplib', _api_code))
check('Z1. предохранитель выключен', po.DISPATCH_ENABLED is False)
check('Z2. /start по-прежнему 409',
      po.start_run('prun_1') == {"status": "error", "reason": "project_orchestrator_dispatch_disabled"})
check('Z3. production scheduler по-прежнему ничего не делает',
      po.scheduler_tick() == {"status": "disabled", "reason": "project_orchestrator_dispatch_disabled",
                              "leased": 0, "dispatched": 0})
check('Z4. настоящих project_print_job не создано',
      c.execute("SELECT COUNT(*) n FROM project_print_jobs").fetchone()['n'] == 0)
check('Z5. НИ ОДНОГО вызова печати/резервации/планировщика за весь тест: BOOM=%r' % (BOOM,), BOOM == [])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: кандидаты read-only и детерминированы (БД байт-в-байт), выбор пересчитывается '
              'сервером и телу запроса не верит, согласие обязано покрыть ВЕСЬ перечень требований '
              '(близкий цвет + отсутствие датчика = две причины, раньше вторая терялась), устаревший '
              'отпечаток и активный item отклоняются, отзыв меняет только свою колонку; ни печати, '
              'ни резервации, ни планировщика'))
raise SystemExit(1 if fail else 0)
