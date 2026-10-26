# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Одноразовые подтверждения «Стол очищен» — core Alpha 2.740 (этапы 1-4, dry-run).
# Главный инвариант фермы: FINISH/IDLE/RUNNING НИКОГДА не означают, что деталь сняли со стола.
# Токен создаёт ТОЛЬКО человек, он одноразовый, привязан к ОДНОМУ принтеру и не переживает рестарт.
# Запуск: python tools/test_project_clearance_tokens.py   (0 = пройдено)
import importlib.util, os, sys, sqlite3, tempfile, threading, uuid, re, json

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

def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)

TEL = {"pr1": ("IDLE", True), "pr2": ("IDLE", True), "pr_off": ("OFFLINE", False),
       "pr_run": ("RUNNING", True), "pr_prep": ("PREPARE", True), "pr_stale": ("IDLE", False)}
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

def SAFETY(pid):
    """Alpha 2.741: безопасностный снимок из той же тестовой телеметрии TEL (стенды — Bambu).
    printing_active — только доказанно идущее задание; FINISH сюда НЕ входит (после него оператор
    и подтверждает «Стол очищен»). safe_idle — только доказанный IDLE."""
    st, fr = TEL.get(pid, ("OFFLINE", False))
    st = str(st or "").upper()
    active = st in ("RUNNING", "PREPARE", "PAUSE", "PAUSED", "SLICING")
    safe = bool(fr) and st == "IDLE"
    return {"printer_id": pid, "transport": "bambu", "status": st, "status_raw": st,
            "fresh": bool(fr), "user_stopped_pending": False, "printing_active": active,
            "safe_idle": safe,
            "unsafe_reason": "" if safe else ("offline_or_stale" if not fr else "not_idle_raw:" + st)}


def boot(b):
    po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], b,
            printer_status_fn=lambda pid: TEL.get(pid, ("OFFLINE", False)),
            safety_fn=SAFETY,
            printers_fn=lambda: [{"id": k, "name": k, "type": "bambu"} for k in TEL],
            send_reserved_fn=lambda: set(), file_ok_fn=lambda f: True)

boot('boot_A')
po.init_db()
# F1 совместим только с pr1 -> pr2 этому run не нужен
COMPAT = lambda f: ['pr1']
run = po.create_run('prj', False, {}, 'op', None, COMPAT)
RID = run['run_id']

def rows_clr():
    return c.execute("SELECT COUNT(*) n FROM plate_clearances").fetchone()["n"]

# ── создание требует ЯВНОГО человека и здоровой телеметрии ──
check('C1. без confirmed:true токен не создаётся (телеметрия сама его НЕ создаёт)',
      po.create_clearance('pr1', confirmed=False, run_id=RID, compat_fn=COMPAT)['reason'] == 'confirmation_required'
      and rows_clr() == 0)
check('C2. offline -> отказ telemetry_stale',
      po.create_clearance('pr_off', confirmed=True, run_id=RID, compat_fn=COMPAT)['reason'] == 'telemetry_stale')
check('C3. stale (несвежая телеметрия при IDLE) -> отказ',
      po.create_clearance('pr_stale', confirmed=True, run_id=RID, compat_fn=COMPAT)['reason'] == 'telemetry_stale')
check('C4. RUNNING -> отказ printer_busy',
      po.create_clearance('pr_run', confirmed=True, run_id=RID, compat_fn=COMPAT)['reason'] == 'printer_busy')
check('C5. PREPARE -> отказ printer_busy',
      po.create_clearance('pr_prep', confirmed=True, run_id=RID, compat_fn=COMPAT)['reason'] == 'printer_busy')
check('C6. после всех отказов в БД НЕТ ни одного токена', rows_clr() == 0)

# ── принадлежность run ──
check('C7. принтер, не подходящий НИ ОДНОМУ pending item этого run -> отказ printer_not_used_by_run',
      po.create_clearance('pr2', confirmed=True, run_id=RID, compat_fn=COMPAT)['reason'] == 'printer_not_used_by_run')
check('C8. чужой finished_job_id (не принадлежит этому run) -> отказ job_not_in_run',
      po.create_clearance('pr1', confirmed=True, finished_job_id='pjob_чужой', run_id=RID,
                          compat_fn=COMPAT)['reason'] == 'job_not_in_run')

# ── штатное создание ──
r = po.create_clearance('pr1', confirmed=True, confirmed_by='Оператор', run_id=RID, compat_fn=COMPAT)
check('C9. initial clearance создан: finished_job_id="" и is_initial=true',
      r['status'] == 'ok' and r['clearance']['finished_job_id'] == '' and r['clearance']['is_initial'] is True)
# Точный whitelist публичной поверхности токена (НЕ подмножество): любое новое поле обязано быть
# осознанно внесено сюда. status/invalid_reason/consumed_at/invalidated_at — метаданные жизненного
# цикла, секретами не являются; nonce и state_snapshot_json наружу по-прежнему не выходят.
check('C10. метаданные токена без секретов (нет nonce/token/ip/пути/credentials)',
      set(r['clearance'].keys()) == {'clearance_id', 'printer_id', 'finished_job_id', 'confirmed_by',
                                     'confirmed_at', 'boot_id', 'is_initial',
                                     'status', 'invalid_reason', 'consumed_at', 'invalidated_at'})
check('C10b. только что созданный токен — действующее разрешение: status="active" и пустая причина',
      r['clearance']['status'] == 'active' and r['clearance']['invalid_reason'] == ''
      and r['clearance']['consumed_at'] is None and r['clearance']['invalidated_at'] is None)
CID = r['clearance']['clearance_id']
check('C11. один активный токен на принтер: повторное создание -> clearance_exists',
      po.create_clearance('pr1', confirmed=True, run_id=RID, compat_fn=COMPAT)['reason'] == 'clearance_exists'
      and rows_clr() == 1)

# ── consume ровно один раз ──
check('C12. consume выполняется РОВНО один раз (conditional UPDATE + rowcount)',
      po.consume_clearance(CID, 'pitem_x') is True)
before = [repr(tuple(x)) for x in c.execute("SELECT * FROM plate_clearances ORDER BY rowid")]
check('C13. ПОВТОРНЫЙ consume отказывает и НЕ меняет БД',
      po.consume_clearance(CID, 'pitem_y') is False
      and [repr(tuple(x)) for x in c.execute("SELECT * FROM plate_clearances ORDER BY rowid")] == before)
check('C14. израсходованный токен больше не активен', po.active_clearance('pr1') is None)
check('C15. токен НЕ является разрешением на будущие задания: после расхода нужен новый',
      po.create_clearance('pr1', confirmed=True, run_id=RID, compat_fn=COMPAT)['status'] == 'ok')

# ── revoke ──
check('C16. revoke гасит активный токен', po.revoke_clearance('pr1')['status'] == 'ok')
before = [repr(tuple(x)) for x in c.execute("SELECT * FROM plate_clearances ORDER BY rowid")]
check('C17. повторный revoke идемпотентен: отказ без изменения БД',
      po.revoke_clearance('pr1')['reason'] == 'no_active_clearance'
      and [repr(tuple(x)) for x in c.execute("SELECT * FROM plate_clearances ORDER BY rowid")] == before)
check('C18. после revoke новый токен создаётся штатно (старый не блокирует)',
      po.create_clearance('pr1', confirmed=True, run_id=RID, compat_fn=COMPAT)['status'] == 'ok')
check('C19. отозванный токен нельзя израсходовать',
      po.consume_clearance(CID, 'pitem_z') is False)

# ── чужой boot_id ──
OLD = po.active_clearance('pr1')['id']
boot('boot_B')                                   # перезапуск сервера
n = po.invalidate_stale_boot_clearances()
check('C20. при рестарте токены прошлого запуска атомарно инвалидируются',
      n == 1 and po.active_clearance('pr1') is None
      and c.execute("SELECT invalid_reason FROM plate_clearances WHERE id=?", (OLD,)).fetchone()["invalid_reason"] == 'server_restart')
check('C21. токен чужого boot_id нельзя израсходовать даже по прямому id',
      po.consume_clearance(OLD, 'pitem_q') is False)
check('C22. после инвалидирования старый токен НЕ блокирует создание нового',
      po.create_clearance('pr1', confirmed=True, run_id=RID, compat_fn=COMPAT)['status'] == 'ok')
check('C23. повторная инвалидация идемпотентна (нечего гасить -> 0)',
      po.invalidate_stale_boot_clearances() == 0)

# ── токен принадлежит одному принтеру и одному расходованию ──
NEW = po.active_clearance('pr1')['id']
check('C24. токен привязан к ОДНОМУ принтеру: у другого принтера его нет',
      po.active_clearance('pr2') is None
      and c.execute("SELECT printer_id FROM plate_clearances WHERE id=?", (NEW,)).fetchone()["printer_id"] == 'pr1')
po.consume_clearance(NEW, 'pitem_1')
check('C25. израсходованный одним item\'ом токен нельзя применить к другому',
      po.consume_clearance(NEW, 'pitem_2') is False
      and c.execute("SELECT consumed_by_item_id FROM plate_clearances WHERE id=?", (NEW,)).fetchone()["consumed_by_item_id"] == 'pitem_1')

# ── событийная инвалидация ──
po.create_clearance('pr1', confirmed=True, run_id=RID, compat_fn=COMPAT)
po.invalidate_clearance_on_event('pr1', 'external_print_started')
check('C26. любая новая печать/смена состояния гасит токен (событийная инвалидация)',
      po.active_clearance('pr1') is None)
po.invalidate_clearance_on_event('pr1', 'external_print_started')
check('C27. событийная инвалидация идемпотентна и безопасна при отсутствии токена', True)

# ── статическая гарантия: телеметрия не создаёт токен ──
code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()))
ins = code[code.index('def create_clearance'):code.index('def revoke_clearance')]
# Alpha 2.746: проверка confirmed стала СТРОЖЕ — `confirmed is not True` вместо `not confirmed`
# (truthy-мусор вроде "yes"/1 больше не считается подтверждением; так же сделано в API 5A3a).
# INSERT токена по-прежнему РОВНО один на все пути: и первичный, и после печати.
check('C28. единственный путь создания токена требует confirmed=True (автосоздания по телеметрии нет)',
      'if confirmed is not True:' in ins and 'confirmation_required' in ins
      and code.count('INSERT INTO plate_clearances') == 1)

# ══════════════════════════════════════════════════════════════════════════════════════════════
# last_clearance — история токена для оператора. Проверяется через РЕАЛЬНЫЙ public-снимок run,
# то есть ровно то, что увидит UI, а не через прямые SELECT'ы.
# Главное: `clearance` остаётся ТОЛЬКО действующим разрешением; история живёт отдельным полем и
# разрешением не является ни при каком статусе.
# ══════════════════════════════════════════════════════════════════════════════════════════════
COMPAT2 = lambda f: ['pr1', 'pr2']          # pr2 нужен run'у -> для него можно создавать токены
def SNAP(pid='pr2'):
    """Ровно то, что отдаёт UI: printers[] из публичного снимка run."""
    return [p for p in po.get_run(RID)['printers'] if p['printer_id'] == pid][0]
mk2 = lambda: po.create_clearance('pr2', confirmed=True, run_id=RID, compat_fn=COMPAT2)

# ── A. токена никогда не было ──
s = SNAP()
check('L1. A: токена никогда не было -> clearance=null И last_clearance=null',
      s['clearance'] is None and s['last_clearance'] is None)

# ── B. active ──
check('L2. B: активный токен создан', mk2()['status'] == 'ok')
s = SNAP()
check('L3. B: active виден ОДНОВРЕМЕННО в clearance и last_clearance, это ОДИН и тот же токен',
      s['clearance'] and s['last_clearance']
      and s['clearance']['clearance_id'] == s['last_clearance']['clearance_id']
      and s['clearance']['status'] == 'active' and s['last_clearance']['status'] == 'active')

# ── C. consumed ──
CID_B = s['clearance']['clearance_id']
po.consume_clearance(CID_B, 'pitem_L')
s = SNAP()
check('L4. C: consumed -> clearance=null (израсходованный токен НЕ является разрешением)',
      s['clearance'] is None)
check('L5. C: last_clearance.status="consumed", consumed_at заполнен, invalidated_at=null',
      s['last_clearance']['status'] == 'consumed' and s['last_clearance']['clearance_id'] == CID_B
      and s['last_clearance']['consumed_at'] is not None and s['last_clearance']['invalidated_at'] is None)
check('L6. C: исторический consumed НЕ блокирует создание нового токена', mk2()['status'] == 'ok')

# ── D. revoked ──
CID_D = SNAP()['clearance']['clearance_id']
check('L7. D: revoke отработал', po.revoke_clearance('pr2')['status'] == 'ok')
s = SNAP()
_sig = re.search(r'def revoke_clearance\(printer_id, reason="([a-z_]+)"\)',
                 open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()).group(1)
check('L8. D: revoked -> clearance=null; last_clearance.status="revoked", invalidated_at заполнен',
      s['clearance'] is None and s['last_clearance']['status'] == 'revoked'
      and s['last_clearance']['clearance_id'] == CID_D and s['last_clearance']['invalidated_at'] is not None)
check('L9. D: invalid_reason — ФАКТИЧЕСКОЕ canonical значение revoke, а не выдуманное '
      '(сверено с дефолтом revoke_clearance и с БД: "%s")' % _sig,
      s['last_clearance']['invalid_reason'] == _sig == po.CLR_REASON_USER_REVOKE
      and c.execute("SELECT invalid_reason FROM plate_clearances WHERE id=?",
                    (CID_D,)).fetchone()['invalid_reason'] == _sig)
check('L10. D: revoked history НЕ блокирует создание нового токена', mk2()['status'] == 'ok')

# ── E. перезапуск сервера ──
CID_E = SNAP()['clearance']['clearance_id']
boot('boot_C')                                    # ══ ПЕРЕЗАПУСК ══
po.invalidate_stale_boot_clearances()
s = SNAP()
check('L11. E: после рестарта clearance=null (старое подтверждение разрешением не является)',
      s['clearance'] is None)
check('L12. E: last_clearance.status="invalidated", invalid_reason="server_restart" — оператор '
      'видит ПРИЧИНУ, а не молчаливое исчезновение подтверждения',
      s['last_clearance']['clearance_id'] == CID_E and s['last_clearance']['status'] == 'invalidated'
      and s['last_clearance']['invalid_reason'] == 'server_restart')
check('L13. E: новый boot может создать новый active токен', mk2()['status'] == 'ok')
s = SNAP()
check('L14. E: после нового токена last_clearance указывает на НОВЫЙ active, а не на старый invalidated',
      s['last_clearance']['clearance_id'] != CID_E and s['last_clearance']['status'] == 'active'
      and s['last_clearance']['clearance_id'] == s['clearance']['clearance_id']
      and s['last_clearance']['boot_id'] == 'boot_C')

# ── F. стабильный детерминированный выбор ──
_ids = sorted(r['id'] for r in c.execute("SELECT id FROM plate_clearances WHERE printer_id='pr2'"))
check('F-фикстура: у pr2 накоплена история из нескольких токенов', len(_ids) >= 4)
c.execute("UPDATE plate_clearances SET confirmed_at=5000.0 WHERE printer_id='pr2'")   # искусственная ничья
c.commit()
check('L15. F: при ОДИНАКОВОМ confirmed_at выбор детерминирован сортировкой id DESC',
      SNAP()['last_clearance']['clearance_id'] == _ids[-1])
check('L16. F: повторный снимок даёт побайтово идентичный JSON (нет случайности/времени в выдаче)',
      json.dumps(po.get_run(RID)['printers'], sort_keys=True) ==
      json.dumps(po.get_run(RID)['printers'], sort_keys=True))

# ── G. security ──
_dump = json.dumps(SNAP(), ensure_ascii=False)
_nonce = c.execute("SELECT nonce FROM plate_clearances WHERE id=?", (_ids[-1],)).fetchone()['nonce']
check('L17. G: nonce НЕ выходит наружу (ни ключом, ни значением)',
      'nonce' not in _dump and _nonce not in _dump and len(_nonce) > 0)
check('L18. G: наружу не выходят credentials, абсолютные пути и содержимое файлов',
      not re.search(r'password|token_secret|[A-Za-z]:\\\\|state_snapshot|/home/|C:/', _dump)
      and set(SNAP()['last_clearance']) == {'clearance_id', 'printer_id', 'finished_job_id', 'confirmed_by',
                                            'confirmed_at', 'boot_id', 'is_initial', 'status', 'invalid_reason',
                                            'consumed_at', 'invalidated_at'})

# ── H. business gates: исторический объект НИКОГДА не принимается как действующее разрешение ──
check('L19. H: consume исторического (израсходованного) токена по прямому id -> отказ',
      po.consume_clearance(CID_B, 'pitem_hist') is False)
check('L20. H: consume исторического (отозванного) токена по прямому id -> отказ',
      po.consume_clearance(CID_D, 'pitem_hist') is False)
check('L21. H: consume исторического (invalidated рестартом) токена по прямому id -> отказ',
      po.consume_clearance(CID_E, 'pitem_hist') is False)
po.revoke_clearance('pr2')                       # гасим единственный active
s = SNAP()
check('L22. H: при наличии ТОЛЬКО исторических токенов revoke -> no_active_clearance, '
      'хотя last_clearance по-прежнему заполнен',
      po.revoke_clearance('pr2')['reason'] == 'no_active_clearance'
      and s['clearance'] is None and s['last_clearance'] is not None)

# ── статические гарантии разделения ролей ──
_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', open(
    os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()))
_fns = re.split(r'\ndef ', _code)
_users = sorted(f.split('(')[0] for f in _fns if 'last_clearance(' in f and not f.startswith('last_clearance('))
check('L23. last_clearance вызывается ТОЛЬКО из публичного снимка (printer_availability) и ни в '
      'одном gate: найдено %r' % (_users,), _users == ['printer_availability'])
check('L24. gate\'ы по-прежнему спрашивают active_clearance (не заменён историей)',
      'if active_clearance(printer_id):' in _code
      and 'consumed_at IS NULL AND invalidated_at IS NULL' in _code)
_body_last = _code[_code.index('def last_clearance'):_code.index('def clearance_status')]
check('L25. last_clearance — чистое чтение: ни UPDATE/INSERT/DELETE, ни BEGIN/commit внутри',
      not re.search(r'UPDATE|INSERT|DELETE|BEGIN|commit', _body_last) and 'SELECT' in _body_last
      and 'ORDER BY confirmed_at DESC, id DESC LIMIT 1' in _body_last)
_raw = open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()
# Alpha 2.741: владелец разрешил ОДНУ аддитивную колонку СВОЕЙ таблицы (project_run_items.
# feed_plan_json) — прежний тотальный запрет ADD COLUMN заменён на точную проверку намерения:
# таблиц по-прежнему ровно 3, ALTER — только ADD COLUMN и только по своим таблицам, и ни одна
# колонка plate_clearances при этом не появилась/не исчезла (жизненный цикл токена не тронут).
check('L26. схема — те же 3 таблицы; ALTER — только ADD COLUMN по своим таблицам; токен не тронут',
      _raw.count('CREATE TABLE') == 3
      and len([x for x in po._SCHEMA if 'CREATE TABLE' in x]) == 3
      and all(re.match(r'^ALTER TABLE %s ADD COLUMN', a) for a in re.findall(r'"(ALTER[^"]*)"', _raw))
      and {t for t, _c, _d in po._MIGRATIONS} <= {'project_runs', 'project_run_items', 'plate_clearances'}
      and not [m for m in po._MIGRATIONS if m[0] == 'plate_clearances'])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: токен создаёт только человек при свежей телеметрии и не в RUNNING/PREPARE; он один на '
              'принтер, одноразовый, не переживает рестарт, не переносится на другой item/принтер и не является '
              'разрешением на будущие задания; повторные consume/revoke безопасны и БД не меняют. '
              'clearance остался ТОЛЬКО действующим разрешением (active), история вынесена в отдельное '
              'read-only last_clearance и ни одним gate\'ом за разрешение не принимается'))
sys.exit(1 if fail else 0)
