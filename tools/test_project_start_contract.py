# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Контракт optimistic-lock запуска плана — Alpha 2.749.
# ЗАЧЕМ. POST /api/project-runs/{run_id}/start сверяет ТРИ значения: run.updated_at,
# item.updated_at и feed_plan.fingerprint. Пока у item.updated_at не было production JSON path,
# UI слал undefined -> JSON.stringify выбрасывал ключ -> сервер видел None -> сравнение молча
# ПРОПУСКАЛОСЬ (fail-open). Харнесс этого не ловил, потому что его фикстура ДОРИСОВЫВАЛА поле,
# которого настоящий сериализатор не отдаёт. Тест закрывает оба конца:
#   • форма реального detail/list JSON снимается с НАСТОЯЩЕЙ сериализации оркестратора;
#   • обязательные frontend-поля сверяются с этой формой, а фикстуры — с ней же;
#   • stale-снимок обязан отбиваться ДО reservation, не тратя arm и не трогая БД.
# server.py НЕ импортируется (это подняло бы боевой DATA_DIR) — DDL выскабливается из текста.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_start_contract.py   (0 = пройдено)
import importlib.util, json, os, re, sqlite3, tempfile, threading, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
_APPJS = open(os.path.join(REPO, 'web', 'app.js'), encoding='utf-8').read()
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
        raise AssertionError('ЗАПРЕЩЕНО: ' + tag)
    return _b


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


# ══ Стенд: временная БД, боевой DATA_DIR не трогаем ═══════════════════════════════════════════
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','Проект')")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','plate.3mf','h1',1)")
c.commit()

LOCK = threading.Lock()
HOLDS, RESV = {}, {}
MGR = threading.Lock()
_seq = [0]
DISPATCHES = []          # каждый вход в адаптер = попытка реальной отправки
ARM_CHECKS = []
ARM_CONSUMED = [0]


def SAFETY(pid):
    return {"printer_id": pid, "transport": "bambu", "status": "IDLE", "status_raw": "IDLE",
            "fresh": True, "user_stopped_pending": False, "printing_active": False,
            "safe_idle": True, "unsafe_reason": ""}


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


def A_dispatch(payload):
    # Граница реальной отправки. Вооружение тратится ИМЕННО здесь (как в _orch_prod_dispatch),
    # поэтому «сюда не дошли» == «arm не израсходован и ничего не улетело».
    DISPATCHES.append(dict(payload))
    ARM_CONSUMED[0] += 1
    return {"status": "ok", "pjob_id": "pjob_1", "command_sent": True}


def A_arm_check(run_id, item_id, printer_id):
    ARM_CHECKS.append((run_id, item_id, printer_id))
    return (True, '')


PLAN = {}


def A_build(run_id, item_id, printer_id):
    p = dict(PLAN.get(printer_id) or {})
    p.update({"run_id": run_id, "item_id": item_id, "printer_id": printer_id})
    return p


po.init(c, LOCK, lambda p: p + uuid.uuid4().hex[:10], 'boot_A',
        printer_status_fn=lambda pid: ("IDLE", True), safety_fn=SAFETY,
        printers_fn=lambda: [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}],
        send_reserved_fn=lambda: set(RESV), file_ok_fn=lambda f: True,
        holds_fn=lambda: dict(HOLDS), set_hold_fn=A_set_hold, clear_hold_fn=A_clear_hold,
        file_requirements_fn=lambda fr: {"status": "ok", "filament_count": 1, "file_hash": "h1",
                                         "filaments": [{"file_index": 0, "material": "PETG",
                                                        "color_hex": "#161616"}]},
        filament_snapshot_fn=lambda pid: {}, reported_filament_fn=lambda pid: {})
po.init_db()

ADAPTERS = {"list_printers": lambda: [{"id": "pr1", "name": "A", "type": "bambu", "order_idx": 0}],
            "safety_snapshot": SAFETY, "compatibility_check": lambda fr: ['pr1'],
            "build_feed_plan": A_build, "persist_feed_plan": po.persist_feed_plan,
            "reserve_printer": A_reserve, "cancel_reserved": A_cancel,
            "set_hold": A_set_hold, "clear_hold": A_clear_hold,
            "dispatch": A_dispatch, "arm_check": A_arm_check}

# Предохранители поднимаем ТОЛЬКО на своём импортированном объекте модуля внутри тест-процесса —
# тем же штатным приёмом, что и tools/test_project_controlled_transport.py. В репозитории файл
# остаётся False/пустым (это отдельно доказывает test_project_orchestrator_no_dispatch.py).
# Без этого первый предохранитель отбивал бы запуск раньше optimistic-lock, и весь блок проверок
# ниже был бы зелёным НИ ЗА ЧТО: отказ приходил бы с reason=project_orchestrator_dispatch_disabled.
po.DISPATCH_ENABLED = True
po.TRANSPORT_ENABLED = True
po.ALLOWED_PRINTER_IDS = frozenset({'pr1'})


def mk_plan(pid='pr1', slot=0):
    return {"version": 1, "status": "ready", "reason": "", "project_id": "prj", "run_id": "prun_1",
            "item_id": "it_1", "file_id": "F1", "file_hash": "h1", "printer_id": pid,
            "transport": "bambu", "filament_count": 1, "ams_slot": slot, "mode": "ams",
            "spool_id": "sp_0", "inventory_bound": True, "required_material": "PETG",
            "inventory_material": "PETG", "reported_material": "PETG", "required_color": "#161616",
            "inventory_color": "#161616", "reported_color": "#161616", "color_distance": 0.0,
            "color_relation": "exact", "verification": "telemetry_confirmed",
            "required_approval_reasons": [], "requires_approval": False, "approval": None,
            "built_at": 1.0}


def reset(items=(('it_1', 1, 'pending'),), run_state='running', clr=True):
    with LOCK:
        for t in ('project_runs', 'project_run_items', 'plate_clearances', 'project_print_jobs'):
            c.execute("DELETE FROM " + t)
        c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, "
                  "print_opts_json, created_at, updated_at) VALUES "
                  "('prun_1','prj',?,'exact',?,'{}',1.0,111.5)", (run_state, po._ctx['boot']))
        for iid, seq, st in items:
            # created_at и updated_at РАЗНЫЕ: иначе тест не отличит canonical updated_at от created_at.
            c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
                      "created_at, updated_at) VALUES (?,'prun_1','prj','F1',?,?,1.0,222.25)",
                      (iid, seq, st))
        c.commit()
    HOLDS.clear(); RESV.clear(); PLAN.clear(); DISPATCHES.clear(); ARM_CHECKS.clear()
    ARM_CONSUMED[0] = 0
    PLAN['pr1'] = mk_plan()
    for iid, _s, _st in items:
        po.persist_feed_plan(iid, 'prun_1', PLAN['pr1'])
    if clr:
        with LOCK:
            c.execute("INSERT INTO plate_clearances (id, printer_id, confirmed_at, nonce, boot_id) "
                      "VALUES ('clr_1','pr1',1.0,'nonce_secret_zzz',?)", (po._ctx['boot'],))
            c.commit()


def snap():
    """Полный снимок побочных эффектов: БД + удержания + резервации."""
    with LOCK:
        rows = {t: [dict(r) for r in c.execute("SELECT * FROM " + t + " ORDER BY id").fetchall()]
                for t in ('project_runs', 'project_run_items', 'plate_clearances', 'project_print_jobs')}
    return json.dumps({"db": rows, "holds": HOLDS, "resv": RESV}, sort_keys=True, default=str)


# ══ A. Detail JSON: canonical item.updated_at ═════════════════════════════════════════════════
reset()
detail = po.get_run('prun_1')
it0 = detail['items'][0]
with LOCK:
    db_item = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
    db_run = dict(c.execute("SELECT * FROM project_runs WHERE id='prun_1'").fetchone())

check('A1. КРИТИЧНО: detail-JSON отдаёт item.updated_at (без него UI не соберёт optimistic-lock)',
      'updated_at' in it0)
# Сверяем с ФАКТИЧЕСКОЙ колонкой, а не с числом из INSERT: persist_feed_plan законно двигает
# updated_at, и хардкод 222.25 проверял бы выдуманный инвариант вместо canonical-источника.
check('A2. КРИТИЧНО: item.updated_at — РЕАЛЬНОЕ значение колонки, а не created_at/run.updated_at/0/None',
      it0.get('updated_at') == db_item['updated_at']
      and it0.get('updated_at') not in (0, None)
      and it0.get('updated_at') != db_item['created_at']
      and it0.get('updated_at') != db_run['updated_at']
      and it0.get('updated_at') != (it0.get('feed_plan') or {}).get('built_at'))
check('A3. item.updated_at — число (float), пригодное для сравнения без парсинга строк',
      isinstance(it0.get('updated_at'), float))
check('A4. run.updated_at идёт из canonical project_runs.updated_at',
      detail.get('updated_at') == db_run['updated_at'] == 111.5)
check('A5. fingerprint идёт из СОХРАНЁННОГО feed_plan_json, а не считается на лету из чужого плана',
      (it0.get('feed_plan') or {}).get('fingerprint')
      == po.feed_fingerprint(json.loads(db_item['feed_plan_json'])))
check('A6. КРИТИЧНО: три значения optimistic-lock достижимы из ОДНОГО detail-снимка',
      isinstance(detail.get('updated_at'), float) and isinstance(it0.get('updated_at'), float)
      and bool((it0.get('feed_plan') or {}).get('fingerprint')))
check('A7. item.updated_at меняется при смене состояния item (значение живое, а не константа)',
      (lambda before: (po._set_item_state('it_1', 'eligible', only_if=('pending',)),
                       po.get_run('prun_1')['items'][0].get('updated_at') != before)[1])(it0.get('updated_at')))

# ══ B. Форма list: не притворяется detail ═════════════════════════════════════════════════════
reset()
lst = po.list_active_runs()
LIST_KEYS = {'run_id', 'project_id', 'state', 'allow_overproduction', 'plan_quality', 'blocked',
             'created_at', 'updated_at', 'boot_id', 'note', 'dispatch_enabled', 'project_name'}
check('B1. list отдаёт РОВНО заявленную модель run + project_name', len(lst) == 1
      and set(lst[0].keys()) == LIST_KEYS)
check('B2. КРИТИЧНО: list НЕ содержит items/printers/feed_plan — за ними только detail',
      all(k not in lst[0] for k in ('items', 'printers', 'feed_plan', 'counts')))
check('B3. run_id и run.updated_at в list есть (шаг 1 двухшагового получения)',
      lst[0]['run_id'] == 'prun_1' and lst[0]['updated_at'] == 111.5)
DETAIL_KEYS = LIST_KEYS - {'project_name'} | {'items', 'counts', 'printers', 'part_names'}  # part_names — 2.754
check('B4. detail = модель run + items + counts + printers (второй несовместимой модели нет)',
      set(po.get_run('prun_1').keys()) == DETAIL_KEYS)
check('B5. detail отдаёт printers/clearance по прежней модели',
      isinstance(detail.get('printers'), list) and detail['printers']
      and {'printer_id', 'clearance', 'last_clearance', 'hold', 'available',
           'unavailable_reasons', 'safe_idle'} <= set(detail['printers'][0].keys()))

# ══ C-D-E-F-G. Frontend строит POST из НАСТОЯЩЕГО detail JSON ═════════════════════════════════
# Тело POST читаем из web/app.js дословно и вычисляем ПО РЕАЛЬНОМУ detail-JSON: так «поле есть в
# UI-коде» и «поле есть в ответе backend» проверяются одной проверкой, а не двумя независимыми.
# С 2.757 тело POST собирает общий помощник _sendControlledStart (его же зовут и «четыре галочки»,
# и одно-кнопочный запуск из приложения) — оба пути шлют РОВНО одно и то же тело, поэтому источник один.
_SEND = _APPJS[_APPJS.index('const _sendControlledStart = async (r, it) => {'):]
_SEND = _SEND[:_SEND.index('\n    const confirmControlledStart')]
BODY_SRC = re.search(r'const body = \{(.*?)\};', _SEND, re.S).group(1)
PAIRS = dict(re.findall(r'(\w+):\s*([^,\n]+?)(?:,|\s*\};|\s*$)', BODY_SRC.replace('\n', ' ')))


# Тело собирается из ver = startVersions(r, it). Разворачиваем ver обратно в поля detail-снимка,
# но НЕ на глазок: источники вытаскиваются из самого текста startVersions в web/app.js. Если UI
# начнёт брать версию откуда-то ещё (Date.now/created_at/built_at), карта разойдётся и тест упадёт,
# а не молча подставит «правильное» значение.
_SV = _APPJS[_APPJS.index('const startVersions = (r, it) => {'):]
_SV = _SV[:_SV.index('\n    };') + 6]
_VER_RET = re.search(r'return \{ run: ([^,]+), item: ([^,]+), fp: ([^}]+) \};', _SV)
assert _VER_RET, 'не разобрал возврат startVersions() — карта ver.* устарела'
VER_SRC = {'run': _VER_RET.group(1).strip(), 'item': _VER_RET.group(2).strip(),
           'fp': _VER_RET.group(3).strip()}
assert VER_SRC == {'run': 'r.updated_at', 'item': 'it.updated_at', 'fp': 'p.fingerprint'}, \
    'startVersions берёт версию НЕ из canonical-полей: ' + repr(VER_SRC)


def js_path(expr, run, item):
    """Вычисляем JS-выражение тела POST по реальному detail-снимку. Неизвестное выражение — ошибка,
    а не None: молча «догадаться» здесь означало бы проверять выдумку вместо production."""
    e = expr.strip()
    if e == 'true':
        return True
    if e == 'it.item_id':
        return item.get('item_id')
    if e in ('r.updated_at', 'ver.run'):
        return run.get('updated_at')
    if e in ('it.updated_at', 'ver.item'):
        return item.get('updated_at')
    if e in ("(it.feed_plan && it.feed_plan.fingerprint) || ''", 'ver.fp'):
        return (item.get('feed_plan') or {}).get('fingerprint') or ''
    raise AssertionError('неизвестное выражение в теле POST: ' + e)


reset()
d2 = po.get_run('prun_1')
body = {k: js_path(v, d2, d2['items'][0]) for k, v in PAIRS.items()}
check('C1. КРИТИЧНО: тело POST собирается из detail-снимка без единого undefined',
      set(PAIRS) == {'confirmed', 'item_id', 'expected_run_updated_at', 'expected_item_updated_at',
                     'expected_feed_fingerprint'}
      and all(v is not None and v != '' for v in body.values()))
with LOCK:
    _di = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
    _dr = dict(c.execute("SELECT * FROM project_runs WHERE id='prun_1'").fetchone())
check('D1. КРИТИЧНО: значения тела ТОЧНО равны canonical-колонкам БД (run.updated_at, '
      'item.updated_at, отпечаток сохранённого feed_plan_json)',
      body['confirmed'] is True and body['item_id'] == 'it_1'
      and body['expected_run_updated_at'] == _dr['updated_at'] == 111.5
      and body['expected_item_updated_at'] == _di['updated_at']
      and body['expected_feed_fingerprint'] == po.feed_fingerprint(json.loads(_di['feed_plan_json'])))
# E/F/G: пропажа любого из трёх обязана ронять запуск, а не «проскакивать» как None.
# Причина сверяется ТОЧНО: иначе проверка прошла бы за счёт постороннего отказа (так и было —
# зелено давал предохранитель project_orchestrator_dispatch_disabled, а не контракт).
# Подставляем ровно те литералы, которыми оборачивается «значения нет»: None (undefined в JSON),
# "", строка, NaN, bool. Каждый обязан быть отвергнут ДО адаптера.
# Для меток времени мусором считается ВСЁ, что не настоящее число (включая строку "222.25" и bool:
# в Python True == 1, и без явной проверки он прошёл бы как метка). Для отпечатка «пропажа» — это
# только пустое значение; непустой мусор («nan», «True») — это НЕВЕРНЫЙ отпечаток, и он обязан
# отбиваться как feed_stale. Требовать от обоих одну причину было бы подгонкой теста под код.
TS_JUNK = (None, '', 'null', '222.25', float('nan'), float('inf'), True, [], {})
FP_EMPTY = (None, '', [], {})
for lbl, drop, junks in [('E1. item.updated_at', 'expected_item_updated_at', TS_JUNK),
                         ('F1. run.updated_at', 'expected_run_updated_at', TS_JUNK),
                         ('G1. feed_plan.fingerprint', 'expected_feed_fingerprint', FP_EMPTY)]:
    for junk in junks:
        r = po.start_item_controlled('prun_1', 'it_1', confirmed=True, adapters=ADAPTERS,
                                     **{k: (junk if k == drop else body[k]) for k in
                                        ('expected_run_updated_at', 'expected_item_updated_at',
                                         'expected_feed_fingerprint')})
        check(lbl + ' = ' + repr(junk) + ' -> отказ expected_version_required, ничего не улетело',
              r.get('status') == 'error' and r.get('reason') == 'expected_version_required'
              and int(r.get('http') or 0) == 400 and DISPATCHES == [] and ARM_CONSUMED[0] == 0
              and not RESV and not HOLDS)
    reset()
    d2 = po.get_run('prun_1')
    body = {k: js_path(v, d2, d2['items'][0]) for k, v in PAIRS.items()}
# Непустой мусорный отпечаток — не «пропажа», а несовпадение: тоже fail-closed, но своей причиной.
for junk in ('nan', 'True', 'fp_чужой'):
    r = po.start_item_controlled('prun_1', 'it_1', confirmed=True, adapters=ADAPTERS,
                                 expected_run_updated_at=body['expected_run_updated_at'],
                                 expected_item_updated_at=body['expected_item_updated_at'],
                                 expected_feed_fingerprint=junk)
    check('G2. неверный отпечаток ' + repr(junk) + ' -> feed_plan_stale, ничего не улетело',
          r.get('status') == 'error' and r.get('reason') == 'feed_plan_stale'
          and DISPATCHES == [] and ARM_CONSUMED[0] == 0 and not RESV and not HOLDS)

# ══ H-I-J-K-L-M. Stale-снимок отбивается ДО reservation ═══════════════════════════════════════
def start_with(**over):
    reset()
    d = po.get_run('prun_1')
    b = {k: js_path(v, d, d['items'][0]) for k, v in PAIRS.items()}
    b.update(over.pop('body', {}))
    for mut in over.pop('mutate', []):
        mut()
    before = snap()
    r = po.start_item_controlled('prun_1', 'it_1', confirmed=True, adapters=ADAPTERS,
                                 expected_run_updated_at=b['expected_run_updated_at'],
                                 expected_item_updated_at=b['expected_item_updated_at'],
                                 expected_feed_fingerprint=b['expected_feed_fingerprint'])
    return r, before, snap()


def touch_item():
    with LOCK:
        c.execute("UPDATE project_run_items SET updated_at=999.75 WHERE id='it_1'")
        c.commit()


def touch_run():
    with LOCK:
        c.execute("UPDATE project_runs SET updated_at=999.75 WHERE id='prun_1'")
        c.commit()


def touch_feed():
    p = dict(mk_plan())
    p['ams_slot'] = 3                      # другой слот -> другой отпечаток
    po.persist_feed_plan('it_1', 'prun_1', p)


for lbl, mut in [('I1. изменился ТОЛЬКО item', touch_item),
                 ('J1. изменился ТОЛЬКО run', touch_run),
                 ('K1. изменился ТОЛЬКО feed plan', touch_feed)]:
    r, before, after = start_with(mutate=[mut])
    check(lbl + ' -> 409 stale', r.get('status') == 'error' and int(r.get('http') or 0) == 409)
    check(lbl + ' -> H1. отказ ДО reservation: ни резерваций, ни удержаний, ни заданий',
          not RESV and not HOLDS and DISPATCHES == [])
    check(lbl + ' -> L1. вооружение НЕ израсходовано (до адаптера не дошли)',
          ARM_CONSUMED[0] == 0)
    check(lbl + ' -> M1. БД не изменилась: clearance не consume, задание не создано',
          before == after)

# Свежий снимок обязан проходить — иначе всё выше зелено вакуумно.
r, before, after = start_with()
check('H2. КРИТИЧНО: СВЕЖИЙ снимок проходит (проверки выше не вакуумны)',
      r.get('status') == 'ok' and len(DISPATCHES) == 1 and ARM_CONSUMED[0] == 1)

# ══ N. Фикстуры харнессов не выдумывают полей ═════════════════════════════════════════════════
PROD_ITEM_KEYS = set(po.get_run('prun_1')['items'][0].keys())
PROD_RUN_KEYS = set(po.get_run('prun_1').keys())


def fixture_keys(path, fn):
    """Ключи верхнего уровня фикстуры. Вложенные объекты схлопываем, чтобы их поля не считались
    полями item/run (иначе feed_plan.* дал бы гору ложных «лишних»)."""
    src = open(os.path.join(REPO, 'tools', path), encoding='utf-8').read()
    i = src.index('const ' + fn + ' = ')
    # Терминатор зависит от формы фикстуры: Object.assign({...}, o) против стрелки => ({...}).
    # Берём ближайший — иначе захватим соседние фикстуры и получим гору ложных «лишних».
    ends = [src.index(e, i) for e in ('}, o);', '});') if e in src[i:i + 4000]]
    j = min(ends)
    body = src[i:j]
    for _ in range(6):
        body = re.sub(r'\{[^{}]*\}', 'X', body)
        body = re.sub(r'\[[^\[\]]*\]', 'X', body)
    return set(re.findall(r'(\w+):', body))


PROD_LIST_KEYS = set(po.list_active_runs()[0].keys())
# Каждая фикстура сверяется с ТОЙ формой, которую подделывает: item() и run() — с detail,
# mkRun() — со СПИСКОМ. Иначе list-фикстура тихо притворяется detail (объявляет items/counts),
# и харнесс перестаёт воспроизводить production.
for h, fn, prod, what in [('e2e_feed_plan_harness.js', 'item', PROD_ITEM_KEYS, 'item из detail'),
                          ('e2e_whole_print_harness.js', 'mkRun', PROD_LIST_KEYS, 'run из list')]:
    try:
        extra = (fixture_keys(h, fn) - {'o'}) - prod
        check('N1. КРИТИЧНО: фикстура ' + fn + '() в ' + h + ' не выдумывает полей сверх '
              'production (' + what + ')' + (' — лишние: ' + ', '.join(sorted(extra)) if extra else ''),
              not extra)
    except ValueError:
        check('N1. фикстура ' + fn + '() найдена в ' + h, False)
# Обратная сторона дрейфа: N1 ловит «фикстура выдумала поле», но не ловит «фикстура забыла поле,
# которое production отдаёт, а UI из него читает» — а именно так и рождается ложнозелёный харнесс.
FEED_ITEM_FIX = fixture_keys('e2e_feed_plan_harness.js', 'item') - {'o'}
check('N1b. КРИТИЧНО: фикстура item() даёт все поля, которые UI берёт из item для запуска'
      + (' (нет: ' + ', '.join(sorted({'item_id', 'state', 'updated_at', 'feed_plan'} - FEED_ITEM_FIX)) + ')'
         if {'item_id', 'state', 'updated_at', 'feed_plan'} - FEED_ITEM_FIX else ''),
      {'item_id', 'state', 'updated_at', 'feed_plan'} <= FEED_ITEM_FIX)
# Обратная сторона: фикстура обязана давать ВСЁ, что UI берёт из item для запуска.
UI_ITEM_FIELDS = {'item_id', 'state', 'updated_at', 'feed_plan'}
check('N2. КРИТИЧНО: production-сериализатор отдаёт все поля item, которые UI берёт для запуска'
      + (' (нет: ' + ', '.join(sorted(UI_ITEM_FIELDS - PROD_ITEM_KEYS)) + ')' if UI_ITEM_FIELDS - PROD_ITEM_KEYS else ''),
      UI_ITEM_FIELDS <= PROD_ITEM_KEYS)
check('N3. КРИТИЧНО: production-сериализатор отдаёт run.updated_at, который UI берёт для запуска',
      'updated_at' in PROD_RUN_KEYS)

# ══ O. В JSON нет секретов ════════════════════════════════════════════════════════════════════
blob = json.dumps(po.get_run('prun_1'), default=str) + json.dumps(po.list_active_runs(), default=str)
check('O1. КРИТИЧНО: detail/list не раскрывают nonce подтверждения стола',
      'nonce_secret_zzz' not in blob and '"nonce"' not in blob)
# 2.754: ГОЛОЕ имя файла (items[].filename) — законное human-имя для UI; запрещены токены и ПУТИ.
check('O2. detail/list не раскрывают токены/пароли/пути файловой системы',
      not re.search(r'token|password|secret|[A-Za-z]:\\\\|/home/|access_code', blob, re.I))

print('\nПРОВАЛЕНО: ' + str(fail) if fail else
      '\nВСЁ ЗЕЛЁНОЕ: у item.updated_at есть canonical production-путь; тело POST собирается из '
      'ОДНОГО detail-снимка без undefined; пропажа любого из трёх значений отбивается fail-closed; '
      'stale ловится ДО reservation, не тратя вооружение и не трогая БД; фикстуры харнессов не '
      'выдумывают полей сверх настоящего сериализатора.')
raise SystemExit(1 if fail else 0)
