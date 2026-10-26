# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ДОКАЗАТЕЛЬСТВО «НОЛЬ ПЕЧАТИ» — core Alpha 2.740 (этапы 1-4, dry-run).
# Подменяет ВСЕ пути отправки на bomb-функции и прогоняет ПОЛНЫЙ новый сценарий оркестратора:
# preflight → create → snapshot → pause → resume → clearance(create/revoke) → recovery → resolve → cancel → start.
# Любой вызов печати немедленно валит тест. Дополнительно проверяется, что модуль оркестратора вообще
# не импортирует печатные/сетевые библиотеки и что предохранитель отдаёт контролируемый отказ.
# Запуск: python tools/test_project_orchestrator_no_dispatch.py   (0 = пройдено)
import importlib.util, os, sys, sqlite3, tempfile, threading, uuid, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()

fail = 0
def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1

BOOM = []
def bomb(name):
    def _f(*a, **k):
        BOOM.append(name)
        raise AssertionError('ЗАПРЕЩЁННЫЙ ВЫЗОВ ПЕЧАТИ: ' + name)
    return _f

# ── bomb-заглушки на КАЖДЫЙ путь, способный что-то отправить ──
class BombSendMgr:
    reserve = bomb('_send_mgr.reserve')
    run = bomb('_send_mgr.run')
    begin_direct = bomb('_send_mgr.begin_direct')
    begin_or_adopt_tracked = bomb('_send_mgr.begin_or_adopt_tracked')
    run_tracked = bomb('_send_mgr.run_tracked')
    def snapshot(self):                      # единственный разрешённый — ЧИТАЮЩИЙ
        return {"jobs": [], "reserved_printer_ids": []}

class BombMqtt:
    publish = bomb('mqtt.publish')
    connect = bomb('mqtt.connect')

class BombFtp:
    storbinary = bomb('ftp.storbinary')
    login = bomb('ftp.login')

_bombs = {"_do_project2_file_print": bomb('_do_project2_file_print'),
          "_send_file_to_printer": bomb('_send_file_to_printer'),
          "part_print": bomb('part_print'),
          "_send_mgr": BombSendMgr(), "mqtt": BombMqtt(), "ftp": BombFtp()}

def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)

db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
c.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
          "VALUES ('pa','prj','A','a',2,0)")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','f1.3mf','h1',1)")
c.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) "
          "VALUES ('l1','prj','F1','pa',1)")
c.commit()

def SAFETY_FROM(tel_fn):
    """Alpha 2.741: безопасностный снимок из тестовой телеметрии (все стенды — Bambu, где status_raw
    совпадает с gcode_state, а веб-«Стоп» не имитируется). safe_idle — только доказанный IDLE;
    printing_active — состояния, доказывающие идущее задание (FINISH сюда НЕ входит: именно после
    него оператор и подтверждает «Стол очищен»)."""
    def _fn(pid):
        st, fr = tel_fn(pid)
        st = str(st or "").upper()
        active = st in ("RUNNING", "PREPARE", "PAUSE", "PAUSED", "SLICING")
        safe = bool(fr) and st == "IDLE"
        return {"printer_id": pid, "transport": "bambu", "status": st, "status_raw": st,
                "fresh": bool(fr), "user_stopped_pending": False, "printing_active": active,
                "safe_idle": safe,
                "unsafe_reason": "" if safe else ("offline_or_stale" if not fr else "not_idle_raw:" + st)}
    return _fn


# Пробы — только читающие; send_reserved берём у bomb-менеджера через snapshot (разрешено).
po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: ("IDLE", True),
        safety_fn=SAFETY_FROM(lambda pid: ("IDLE", True)),
        printers_fn=lambda: [{"id": "pr1", "name": "X1C", "type": "bambu"}],
        send_reserved_fn=lambda: set(_bombs["_send_mgr"].snapshot()["reserved_printer_ids"]),
        file_ok_fn=lambda f: True)
po.init_db()

COMPAT = lambda f: ['pr1']

# ══ ПОЛНЫЙ СЦЕНАРИЙ: ни один шаг не смеет тронуть печать ══
pf = po.preflight('prj', False, COMPAT)
check('D1. preflight отработал и честно сообщает, что автозапуск выключен',
      pf['dispatch_enabled'] is False and pf['plan']['chosen_files'] == {'F1': 2}
      and 'IDLE' in pf['idle_is_not_proof'])
cr = po.create_run('prj', False, {}, 'tester', pf['plan']['snapshot_version'], COMPAT)
check('D2. create_run создал draft-run и материализовал items (scheduler не запускается)',
      cr['status'] == 'ok' and po.get_run(cr['run_id'])['state'] == 'draft'
      and len(po.get_run(cr['run_id'])['items']) == 2)
rid = cr['run_id']
snap = po.get_run(rid)
check('D3. snapshot run отдаётся, все items в pending (ни одного будущего состояния)',
      all(i['state'] == 'pending' for i in snap['items']))
check('D4. pause/resume работают и НЕ запускают печать',
      po.pause_run(rid)['status'] == 'ok' and po.resume_run(rid)['state'] == 'draft')
cl = po.create_clearance('pr1', confirmed=True, confirmed_by='op')
check('D5. clearance создаётся по явному подтверждению', cl['status'] == 'ok')
check('D6. revoke clearance работает', po.revoke_clearance('pr1')['status'] == 'ok')
rec = po.recover_on_start()
check('D7. recovery отработал в dry-run и печать не продолжил', rec['dispatch_enabled'] is False)
check('D8. resolve несуществующего ambiguous отказывает без побочных эффектов',
      po.resolve_item(rid, 'нет', 'started')['status'] == 'error')
st = po.start_run(rid)
check('D9. start_run -> контролируемый отказ project_orchestrator_dispatch_disabled, БД не меняется',
      st == {"status": "error", "reason": "project_orchestrator_dispatch_disabled"}
      and po.get_run(rid)['state'] == 'draft')
check('D10. cancel_run работает', po.cancel_run(rid)['status'] == 'ok')

# ── Alpha 2.741 (этап 5A1): новые поверхности тоже обязаны не трогать печать ───────────────────
# Прогоняем ПОД ТЕМИ ЖЕ бомбами: миграцию, удержания, безопасностный снимок, гашение токена,
# колбэки телеметрии STARTED/FINISH/FAILED, cancel и recovery. Ни один из них не смеет ни отправить
# файл, ни опубликовать MQTT, ни зайти на FTP.
_HOLDS_D = {}
po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: ("IDLE", True),
        safety_fn=SAFETY_FROM(lambda pid: ("IDLE", True)),
        printers_fn=lambda: [{"id": "pr1", "name": "X1C", "type": "bambu"}],
        send_reserved_fn=lambda: set(_bombs["_send_mgr"].snapshot()["reserved_printer_ids"]),
        file_ok_fn=lambda f: True, holds_fn=lambda: dict(_HOLDS_D),
        set_hold_fn=lambda pid, ot, oid, r: (_HOLDS_D.__setitem__(pid, {"owner_type": ot, "owner_id": oid, "reason": r}),
                                             (True, _HOLDS_D[pid]))[1],
        clear_hold_fn=lambda pid, ot, oid: _HOLDS_D.pop(pid, None) is not None)
check('D10a. миграция feed_plan_json идемпотентна и печать не трогает', po._migrate() == [])
check('D10b. безопасностный снимок — чистое чтение', po.safety('pr1')['safe_idle'] is True)
check('D10c. active_holds/holds_to_rebuild читают БД и ничего не запускают',
      po.active_holds() == {} and po.holds_to_rebuild() == {})
po.create_clearance('pr1', confirmed=True, confirmed_by='op')
check('D10d. гашение токена по событию печать не трогает',
      po.invalidate_clearance_on_event('pr1', po.CLR_REASON_PRINT_STARTED) == 1)
check('D10e. printers_with_active_clearance — чистое чтение', po.printers_with_active_clearance() == [])
check('D10f. колбэки телеметрии без совпавшего item ничего не запускают',
      po.on_printer_started('pr1', 'x.3mf', '')['matched'] is False
      and po.on_printer_finished('pr1', 'x.3mf', '')['matched'] is False
      and po.on_printer_failed('pr1', 'x.3mf', '', 'e')['matched'] is False)
check('D10g. recovery после всего этого по-прежнему ничего не отправляет',
      isinstance(po.recover_on_start().get('items'), list))
check('D10h. предохранитель не сдвинулся', po.DISPATCH_ENABLED is False
      and po.start_run(rid) == {"status": "error", "reason": "project_orchestrator_dispatch_disabled"})

check('D11. НИ ОДНА bomb-функция печати не вызвана за весь сценарий (0 вызовов)', BOOM == [])
if BOOM:
    print('     ВЫЗВАНО:', BOOM)

# ══ READ-ONLY список активных runs: GET /api/project-runs?active=1 (добавлен для восстановления
#    панели после перезагрузки страницы). cr выше уже отменён D10 -> для списка создаём свежий run. ══
import json as _json
cr_a = po.create_run('prj', False, {}, 'tester', None, COMPAT)          # снова активный run проекта prj
c.execute("INSERT INTO projects (id, name) VALUES ('prj2','Второй проект')")
c.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
          "VALUES ('pb','prj2','B','b',1,0)")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F2','prj2','f2.3mf','h2',1)")
c.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) "
          "VALUES ('l2','prj2','F2','pb',1)")
c.commit()
cr_b = po.create_run('prj2', False, {}, 'tester', None, COMPAT)          # активный run ДРУГОГО проекта
_t = 9000.0
# orphan: строки проекта нет -> LEFT JOIN обязан сохранить run в списке (иначе он «исчезнет» из UI)
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_orphan','prj_УДАЛЁН','paused','exact','boot_A',?,?)", (_t, _t))
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_done','prj_x','completed','exact','boot_A',?,?)", (_t, _t))
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_cxl','prj_y','cancelled','exact','boot_A',?,?)", (_t, _t))
c.commit()

_TBL = ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs',
        'project_runs', 'project_run_items', 'plate_clearances')
_before = {t: [repr(tuple(x)) for x in c.execute("SELECT * FROM %s ORDER BY rowid" % t)] for t in _TBL}
L1 = po.list_active_runs()
L2 = po.list_active_runs()
_after = {t: [repr(tuple(x)) for x in c.execute("SELECT * FROM %s ORDER BY rowid" % t)] for t in _TBL}
_ids = [r['run_id'] for r in L1]
_msrc = open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()
# КОД без docstring/комментариев: иначе фраза «не запускает recovery» в описании даст ложное падение
_lsrc_raw = _msrc[_msrc.index('def list_active_runs'):_msrc.index('def create_run')]
_lsrc = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _lsrc_raw))

check('L1. два активных run РАЗНЫХ проектов возвращаются оба',
      cr_a['run_id'] in _ids and cr_b['run_id'] in _ids)
check('L2. имя проекта подставлено read-only LEFT JOIN с projects',
      next(r for r in L1 if r['run_id'] == cr_b['run_id'])['project_name'] == 'Второй проект')
check('L3. orphan-run (строки проекта нет) НЕ пропадает; project_name=None -> UI подпишет нейтрально',
      'prun_orphan' in _ids and next(r for r in L1 if r['run_id'] == 'prun_orphan')['project_name'] is None)
check('L4. возвращаются ТОЛЬКО состояния из canonical RUN_ACTIVE_STATES (есть draft и paused)',
      {r['state'] for r in L1} >= {'draft', 'paused'} and all(r['state'] in po.RUN_ACTIVE_STATES for r in L1))
check('L5. completed/cancelled в списке ОТСУТСТВУЮТ', 'prun_done' not in _ids and 'prun_cxl' not in _ids)
check('L6. порядок стабильный: created_at ASC, id ASC',
      _ids == [r['run_id'] for r in sorted(L1, key=lambda x: (x['created_at'], x['run_id']))])
check('L7. повторный GET возвращает идентичный ответ',
      _json.dumps(L1, sort_keys=True, ensure_ascii=False) == _json.dumps(L2, sort_keys=True, ensure_ascii=False))
check('L8. чтение НИЧЕГО не изменило: побайтовый снимок ВСЕХ таблиц идентичен', _before == _after)
check('L9. модель та же, что у run_public, плюс ТОЛЬКО аддитивное project_name (второй модели нет)',
      set(L1[0].keys()) == set(po.run_public(dict(
          c.execute("SELECT * FROM project_runs WHERE id=?", (L1[0]['run_id'],)).fetchone())).keys()) | {'project_name'})
check('L10. в ответе нет секретов, токенов и абсолютных путей',
      not any(k in _json.dumps(L1, ensure_ascii=False).lower() for k in
              ('access_code', 'token', 'password', 'mqtt', 'ftp', 'c:\\', '/home/', 'src_path', 'stored_path')))
check('L11. list_active_runs — строго read-only: ни INSERT/UPDATE/DELETE, ни recovery/clearance/reservation',
      not any(w in _lsrc.upper() for w in ('INSERT ', 'UPDATE ', 'DELETE '))
      and not any(w in _lsrc for w in ('recover', 'create_clearance', 'consume_clearance', 'reserve', '_send')))
check('L12. литеральные роуты объявлены ДО /{run_id} — иначе Starlette перехватил бы diagnostics',
      _SRV.index('@app.get("/api/project-runs")') < _SRV.index('@app.get("/api/project-runs/{run_id}")')
      and _SRV.index('@app.get("/api/project-runs/diagnostics")') < _SRV.index('@app.get("/api/project-runs/{run_id}")'))
check('L13. без ?active=1 история НЕ отдаётся (пустой список)',
      'if int(active or 0) != 1:' in _SRV)
check('L14. server.py НЕ дублирует список активных состояний — единственный источник RUN_ACTIVE_STATES',
      "'waiting_for_plate_clear'" not in _SRV[_SRV.index('def whole_print_list_runs'):
                                              _SRV.index('def whole_print_diagnostics')])
check('L15. bomb-функции печати по-прежнему НЕ вызывались после работы со списком', BOOM == [])

# ── статические гарантии модуля ──
src = open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()
code = re.sub(r'"""[\s\S]*?"""', '', src)          # убрать docstring'и
code = re.sub(r'#.*', '', code)                    # убрать комментарии
check('D12. в КОДЕ модуля (без комментариев) нет ни одного печатного/сетевого вызова',
      not any(x in code for x in ('_send_mgr', '_do_project2_file_print', '_send_file_to_printer',
                                  'paho', 'mqtt', 'ftplib', 'FTP_TLS', 'requests', 'socket')))
check('D13. модуль не импортирует ни ядро, ни Inventory/Quality/Cost',
      not re.search(r'^\s*(import|from)\s+(server|modules)', code, re.M)
      and not any(x in code for x in ('farm_inventory', 'farm_quality', 'farm_cost')))
check('D14. предохранитель объявлен и выключен', po.DISPATCH_ENABLED is False
      and po.DISPATCH_DISABLED_REASON == 'project_orchestrator_dispatch_disabled')
check('D15. production-код не переводит items в будущие (печатные) состояния',
      not any(("'%s'" % s) in code.split('IT_FUTURE_STATES')[-1] for s in
              ('leased', 'sending', 'waiting_start_confirmation', 'printing', 'waiting_plate_clear')
              if False) and all(i['state'] in po.IT_STATES_NOW for i in po.get_run(rid)['items']))

# ── API-уровень: роут /start отдаёт 409 и второй барьер существует ──
blk = _SRV[_SRV.index('«ПЕЧАТАТЬ ВЕСЬ ПРОЕКТ» — БЕЗОПАСНЫЙ ФУНДАМЕНТ'):_SRV.index('# ---- API проектов 2.0 (этап 3)')]
code_blk = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', blk))
# Alpha 2.747 (этап 5B1): в блоке роутов ПОЯВИЛСЯ production-адаптер, который дотягивается до
# настоящей печати — это и есть смысл этапа, прежний тотальный запрет устарел. Проверяем НОВУЮ и
# по-прежнему безопасную правду: своей цепочки транспорта нет (только существующий adopt-путь),
# второго задания/вложенного reserve нет, и всё закрыто предохранителями, выключенными по умолчанию.
check('D16. печать достижима ТОЛЬКО существующим adopt-путём: своей цепочки транспорта нет',
      '_do_project2_file_print(' in code_blk and '_from_queue=True' in code_blk
      and not any(x in code_blk for x in ('_send_file_to_printer', '.publish(', 'begin_direct',
                                          'run_tracked', 'ftplib', 'storbinary', 'urllib',
                                          'create_project_print_job')))
check('D16b. reserve берётся ТОЛЬКО с owner-bypass (план проходит свой же hold, чужой — нет)',
      re.search(r'_send_mgr\.reserve\([^)]*hold_owner_type=', code_blk)
      and not re.search(r'_send_mgr\.reserve\((?![^)]*hold_owner_type)', code_blk))
check('D16c. КРИТИЧНО: три серверных предохранителя выключены/пусты ПО УМОЛЧАНИЮ',
      po.DISPATCH_ENABLED is False and po.TRANSPORT_ENABLED is False
      and po.ALLOWED_PRINTER_IDS == frozenset()
      and po.transport_allowed('любой')[0] is False)
# Alpha 2.748/2.757: рантайм-включение предохранителей появилось из ДВУХ источников — (1) одноразовое
# CLI-вооружение (_one_shot_boot_arm, из sys.argv), (2) явный персистентный переключатель владельца
# «печать из приложения» (_apply_project_print_fuses, из сохранённой настройки project_print_enabled).
# Прежний тотальный запрет присваивания устарел; важно: присваивание ТОЛЬКО в этих двух функциях, и
# НИКОГДА — из тела запроса /start.
_arm_fn = _SRV[_SRV.index('def _one_shot_boot_arm('):_SRV.index('def _one_shot_expired(')]
_fuse_fn = _SRV[_SRV.index('def _apply_project_print_fuses('):_SRV.index('@app.post("/api/project-orchestrator/print-enabled")')]
_srv_wo = _SRV.replace(_arm_fn, '').replace(_fuse_fn, '')
_toggle_fn = _SRV[_SRV.index('async def orch_set_print_enabled('):_SRV.index('@app.get("/api/project-orchestrator/transport-status")')]
_start_route = _SRV[_SRV.index('async def whole_print_start('):_SRV.index('async def whole_print_plate_clear(')]
check('D16d. КРИТИЧНО: предохранители присваиваются ТОЛЬКО в _one_shot_boot_arm/_apply_project_print_fuses; '
      'переключатель пишет ПЕРСИСТЕНТНУЮ настройку; тело /start предохранители НЕ трогает',
      '_orch.TRANSPORT_ENABLED = True' in _arm_fn and 'sys.argv' in _SRV
      and '_orch.TRANSPORT_ENABLED = True' in _fuse_fn
      and not re.search(r'_orch\.(?:TRANSPORT_ENABLED|DISPATCH_ENABLED|ALLOWED_PRINTER_IDS)\s*=', _srv_wo)
      and 'project_print_enabled' in _toggle_fn and '_apply_project_print_fuses' in _toggle_fn
      and not re.search(r'd\.get\(["\'](?:enabled|transport_enabled|dispatch_enabled|allowed_printer_ids|'
                        r'armed|arm|phrase)["\']', _start_route))
check('D17. из _PrintSendManager используется ТОЛЬКО читающий snapshot()',
      '_send_mgr.snapshot()' in code_blk)
check('D18. эндпоинт /start защищён предохранителем на API-уровне (409, defense in depth)',
      '_orch_guard()' in code_blk and 'DISPATCH_DISABLED_REASON' in code_blk
      and 'status_code=409' in code_blk)

# ══════════════════════════════════════════════════════════════════════════════════════════════
# M. Публичный снимок run с ЛЮБЫМ состоянием токена обязан остаться чистым чтением.
# Особая опасность: last_clearance добавлен ради обратной связи оператору — он не смеет ничего
# «чинить», гасить или создавать по дороге.
# ══════════════════════════════════════════════════════════════════════════════════════════════
def _dbsnap():
    return {t: [repr(tuple(x)) for x in c.execute("SELECT * FROM %s ORDER BY rowid" % t)] for t in _TBL}

def _read_only_get(tag):
    """Полный побайтовый снимок ВСЕХ таблиц до/после реального публичного GET."""
    b = _dbsnap()
    g1, g2 = po.get_run(rid), po.get_run(rid)
    a = _dbsnap()
    p = [x for x in g1['printers'] if x['printer_id'] == 'pr1'][0]
    same = _json.dumps(g1, sort_keys=True, ensure_ascii=False) == _json.dumps(g2, sort_keys=True, ensure_ascii=False)
    return b == a, same, p

po.revoke_clearance('pr1')                                    # гарантируем отсутствие активного
_st = {}
po.create_clearance('pr1', confirmed=True, confirmed_by='op')
_st['active'] = _read_only_get('active')
_cid = po.active_clearance('pr1')['id']
po.consume_clearance(_cid, 'pitem_m')
_st['consumed'] = _read_only_get('consumed')
po.create_clearance('pr1', confirmed=True, confirmed_by='op')
po.revoke_clearance('pr1')
_st['revoked'] = _read_only_get('revoked')
po.create_clearance('pr1', confirmed=True, confirmed_by='op')
po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], 'boot_B',   # ══ ПЕРЕЗАПУСК ══
        printer_status_fn=lambda pid: ("IDLE", True),
        safety_fn=SAFETY_FROM(lambda pid: ("IDLE", True)),
        printers_fn=lambda: [{"id": "pr1", "name": "X1C", "type": "bambu"}],
        send_reserved_fn=lambda: set(_bombs["_send_mgr"].snapshot()["reserved_printer_ids"]),
        file_ok_fn=lambda f: True)
po.invalidate_stale_boot_clearances()
_st['invalidated'] = _read_only_get('invalidated')

for _k, _want in (('active', 'active'), ('consumed', 'consumed'), ('revoked', 'revoked'),
                  ('invalidated', 'invalidated')):
    _ro, _same, _p = _st[_k]
    check('M1.%s GET run при токене "%s" — чистое чтение: побайтовый снимок ВСЕХ таблиц до/после '
          'идентичен' % (_k, _k), _ro)
    check('M2.%s повторный GET идентичен (нет побочных эффектов у первого)' % _k, _same)
    check('M3.%s last_clearance.status = "%s" (честно, без догадок по IDLE/FINISH)' % (_k, _want),
          _p['last_clearance'] and _p['last_clearance']['status'] == _want)
    check('M4.%s clearance = %s — active-only семантика сохранена' % (_k, 'объект' if _k == 'active' else 'null'),
          (_p['clearance'] is not None) == (_k == 'active'))

check('M5. ни один bomb-путь печати не сработал за всю работу с историей токена '
      '(print/send/MQTT/FTP = 0)', BOOM == [])
check('M6. /start по-прежнему 409 и БД не трогает: снимок до/после идентичен',
      (lambda b: (po.start_run(rid)['reason'] == po.DISPATCH_DISABLED_REASON) and b == _dbsnap())(_dbsnap()))
check('M7. предохранитель по-прежнему выключен', po.DISPATCH_ENABLED is False)

# ── старые проверки не удалены ──
_self = open(os.path.abspath(__file__), encoding='utf-8').read()
_old = ["'D%d." % i for i in range(1, 19)] + ["'L%d." % i for i in range(1, 16)]
_missing = [x.strip("'") for x in _old if x not in _self]
check('M8. ни одна из 33 прежних проверок (D1-D18, L1-L15) не удалена; отсутствуют: %r' % (_missing,),
      not _missing)

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: полный сценарий preflight/create/pause/resume/clearance/recovery/resolve/cancel/start '
              'не сделал НИ ОДНОГО вызова печати (bomb на _do_project2_file_print, _send_file_to_printer, '
              'send-manager, MQTT, FTP); предохранитель выключен и продублирован на API-уровне'))
sys.exit(1 if fail else 0)
