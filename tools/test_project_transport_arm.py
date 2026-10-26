# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Одноразовое вооружение на один запуск (one-shot arm) — core Alpha 2.748, этап 5B2a.
# ЗАЧЕМ. Реальная печать — физическое действие. Право на неё даётся ОДИН раз, осознанно, из
# командной строки, на ОДНУ пару run/item/printer, максимум на 15 минут, и расходуется ровно один
# раз. Здесь доказываем, что иначе его получить нельзя: ни HTTP, ни окружением, ни перезапуском,
# ни повтором после отказа. Транспорт заменён bomb — реальная сеть не открывается.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_transport_arm.py   (0 = пройдено)
import importlib.util, json, os, re, sqlite3, tempfile, threading, uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
_MOD = open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

fail = 0
BOOM = []
CALLS = []


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def bomb(tag):
    def _b(*a, **k):
        BOOM.append(tag)
        raise AssertionError('ЗАПРЕЩЕНО в 5B2a: ' + tag)
    return _b


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


# ══ Песочница: НАСТОЯЩИЙ код вооружения из server.py ══════════════════════════════════════════
MONO = [1000.0]                       # управляемое монотонное время
NS = {'threading': threading, 'sys': type('S', (), {'argv': ['server.py']})(), 'time': type('T', (), {})(),
      'log': type('L', (), {'error': staticmethod(lambda *a, **k: None),
                            'warning': staticmethod(lambda *a, **k: None),
                            'info': staticmethod(lambda *a, **k: None),
                            'debug': staticmethod(lambda *a, **k: None)})(),
      '_BOOT': 'boot_A', '_orch': po, '_exc_brief': lambda: 'x',
      'app': type('A', (), {'get': staticmethod(lambda *a, **k: (lambda f: f))})(),
      'print': lambda *a, **k: None,
      # Alpha 2.757: _one_shot_public теперь читает флаг «печать из приложения» — здесь он выключен
      # (этот тест про CLI-вооружение). Персистентную настройку/роут-переключатель этот стенд не execит.
      '_project_print_enabled': lambda: False}
NS['time'].monotonic = lambda: MONO[0]


def _blk(a, b):
    i = _SRV.index(a)
    return _SRV[i:_SRV.index(b, i)]


# Границу блока сдвинули на начало блока «печать из приложения» (2.757): его @app.post роут этот
# стенд не execит (fake app без .post), а нужные one-shot-функции идут выше.
exec(_blk('_ONE_SHOT_PHRASE = ', '# ══════════════════════════════════════════════════════════════════════════════════════════════\n# ПЕЧАТЬ ПРОЕКТОВ ИЗ ПРИЛОЖЕНИЯ'), NS)
exec(_blk('def orch_transport_status(', '# Вооружение разбираем ЗДЕСЬ'), NS)
exec(_blk('def _strip_one_shot_args(', 'def _restart_self('), NS)
PHRASE = NS['_ONE_SHOT_PHRASE']
arm_boot, arm_check, arm_consume, arm_pub = (NS['_one_shot_boot_arm'], NS['_one_shot_arm_check'],
                                             NS['_one_shot_arm_consume'], NS['_one_shot_public'])


def unarm():
    NS['_ONE_SHOT_ARM'] = None
    NS['_ONE_SHOT_ERROR'] = ''
    po.DISPATCH_ENABLED = False
    po.TRANSPORT_ENABLED = False
    po.ALLOWED_PRINTER_IDS = frozenset()


def cli(run='prun_1', item='it_1', printer='pr1', phrase=None):
    return ['server.py', '--project-one-shot-run', run, '--project-one-shot-item', item,
            '--project-one-shot-printer', printer, '--project-one-shot-confirm',
            PHRASE if phrase is None else phrase]


# ══ A. Обычный запуск ═════════════════════════════════════════════════════════════════════════
unarm()
check('A1. обычный запуск (без флагов) -> НЕ вооружён, ошибки нет', arm_boot(['server.py'], now=MONO[0]) is False
      and arm_pub(MONO[0])['armed'] is False and arm_pub(MONO[0])['error'] == '')
check('A2. КРИТИЧНО: транспорт недостижим — все три предохранителя в безопасном состоянии',
      po.DISPATCH_ENABLED is False and po.TRANSPORT_ENABLED is False and po.ALLOWED_PRINTER_IDS == frozenset()
      and po.transport_allowed('pr1')[0] is False)
check('A3. проверка вооружения отказывает', arm_check('prun_1', 'it_1', 'pr1', MONO[0]) == (False, 'one_shot_not_armed'))

# ══ B-C. Fail-closed ══════════════════════════════════════════════════════════════════════════
for _lbl, _argv in (('нет printer', cli()[:6] + cli()[7:]),
                    ('только run', ['server.py', '--project-one-shot-run', 'prun_1']),
                    ('нет фразы', cli()[:-2]),
                    ('флаг без значения в конце', ['server.py', '--project-one-shot-run'])):
    unarm()
    r = arm_boot(_argv, now=MONO[0])
    check('B.%s частичный набор -> НЕ вооружён + заметная ошибка + транспорт недостижим' % _lbl,
          r is False and arm_pub(MONO[0])['armed'] is False and arm_pub(MONO[0])['error']
          and po.DISPATCH_ENABLED is False and po.ALLOWED_PRINTER_IDS == frozenset())
for _lbl, _ph in (('почти правильная', 'I_UNDERSTAND_THIS_SENDS_A_REAL_PRIN'),
                  ('другой регистр', PHRASE.lower()), ('пустая', ''), ('с пробелом', PHRASE + ' ')):
    unarm()
    r = arm_boot(cli(phrase=_ph), now=MONO[0])
    check('C.%s неверная фраза -> НЕ вооружён' % _lbl,
          r is False and arm_pub(MONO[0])['armed'] is False and po.DISPATCH_ENABLED is False)

# ══ D. Полный точный набор ════════════════════════════════════════════════════════════════════
unarm()
check('D1. полный точный набор -> вооружён', arm_boot(cli(), now=MONO[0]) is True)
p = arm_pub(MONO[0])
check('D2. область РОВНО одна: run/item/printer',
      p['armed'] is True and p['consumed'] is False
      and p['scope'] == {'run_id': 'prun_1', 'item_id': 'it_1', 'printer_id': 'pr1'})
check('D3. срок не больше 15 минут', 0 < p['expires_in_s'] <= 900)
check('D4. рантайм-конфиг включён РОВНО на один принтер (в файле по-прежнему False/пусто)',
      po.DISPATCH_ENABLED is True and po.TRANSPORT_ENABLED is True
      and po.ALLOWED_PRINTER_IDS == frozenset({'pr1'})
      and re.search(r'^DISPATCH_ENABLED = False$', _MOD, re.M)
      and re.search(r'^TRANSPORT_ENABLED = False$', _MOD, re.M)
      and re.search(r'^ALLOWED_PRINTER_IDS = frozenset\(\)$', _MOD, re.M))
check('D5. проверка своей цели проходит', arm_check('prun_1', 'it_1', 'pr1', MONO[0]) == (True, ''))

# ══ E. HTTP не может создать/изменить/продлить вооружение ═════════════════════════════════════
# 2.757: включение печати из приложения приходит из ЯВНОГО переключателя (d.get("enabled") ->
# персистентная настройка), а НЕ из тела /start и НЕ из вооружения. Проверяем именно это.
_start_route = _blk('async def whole_print_start(', 'async def whole_print_plate_clear(')
check('E1. КРИТИЧНО: вооружение и /start не читают предохранители/arm из тела',
      not re.search(r'd\.get\(["\'](?:armed|arm|one_shot|confirm_phrase|phrase|enabled|'
                    r'transport_enabled|allowed_printer_ids)["\']', _start_route)
      and not re.search(r'd\.get\(["\'](?:armed|arm|one_shot|phrase|transport_enabled)["\']', _SRV)
      and not re.search(r'_ONE_SHOT_ARM\s*=', _blk('@app.get("/api/project-orchestrator/transport-status")',
                                                   '# Вооружение разбираем ЗДЕСЬ')))
_armblk = _blk('_ONE_SHOT_PHRASE = ', '# ПЕЧАТЬ ПРОЕКТОВ ИЗ ПРИЛОЖЕНИЯ')
_armcode = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _armblk))
check('E2. КРИТИЧНО: вооружение не читается из окружения и не пишется в БД/файл',
      not re.search(r'os\.environ|getenv|open\(|conn_p|conn_pr|INSERT|UPDATE', _armcode))
check('E3. вооружение приходит ТОЛЬКО из аргументов процесса', 'sys.argv' in _armblk)
check('E4. один @app.get статуса; единственный POST рядом — явный переключатель печати (не вооружение)',
      _SRV.count('@app.get("/api/project-orchestrator/transport-status")') == 1
      and re.findall(r'@app\.(?:post|put|patch|delete)\(["\'](/api/project-orchestrator[^"\']*)', _SRV)
          == ['/api/project-orchestrator/print-enabled'])

# ══ F. Статус — read-only и стабилен ══════════════════════════════════════════════════════════
unarm(); arm_boot(cli(), now=MONO[0])
a_before = dict(NS['_ONE_SHOT_ARM'])
p1 = arm_pub(MONO[0]); p2 = arm_pub(MONO[0]); p3 = arm_pub(MONO[0])
check('F1. КРИТИЧНО: повторный GET при замороженном времени байт-в-байт стабилен',
      json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True) == json.dumps(p3, sort_keys=True))
check('F2. GET не создаёт, не продлевает и не расходует вооружение', NS['_ONE_SHOT_ARM'] == a_before)
check('F3. GET не сдвигает срок', p1['expires_in_s'] == arm_pub(MONO[0])['expires_in_s'])

# ══ S. Секретов в статусе нет ═════════════════════════════════════════════════════════════════
_j = json.dumps(arm_pub(MONO[0]), ensure_ascii=False)
check('S1. КРИТИЧНО: в статусе нет подтверждающей фразы', PHRASE not in _j)
check('S2. в статусе нет токенов/паролей/путей/nonce',
      not re.search(r'(?i)token|password|access|bblp|nonce|[A-Za-z]:\\\\|/mnt/|\d+\.\d+\.\d+\.\d+', _j))
check('S3. статус отдаёт только разрешённые поля',
      set(arm_pub(MONO[0])) == {'status', 'dispatch_enabled', 'transport_enabled', 'print_enabled',
                                'armed', 'consumed', 'expires_in_s', 'scope', 'error'})

# ══ G. Чужая цель ═════════════════════════════════════════════════════════════════════════════
unarm(); arm_boot(cli(), now=MONO[0])
for _lbl, _t in (('другой run', ('prun_2', 'it_1', 'pr1')), ('другой item', ('prun_1', 'it_9', 'pr1')),
                 ('другой printer', ('prun_1', 'it_1', 'pr2'))):
    check('G.%s -> отказ, вооружение НЕ израсходовано' % _lbl,
          arm_check(*_t, now=MONO[0]) == (False, 'one_shot_scope_mismatch')
          and NS['_ONE_SHOT_ARM']['consumed'] is False)
check('G4. чужой принтер вдобавок не в allowlist', po.transport_allowed('pr2')[0] is False)

# ══ H. Истечение срока ════════════════════════════════════════════════════════════════════════
unarm(); arm_boot(cli(), now=MONO[0])
MONO[0] = 1000.0 + 899.0
check('H1. до истечения — вооружён', arm_check('prun_1', 'it_1', 'pr1', MONO[0])[0] is True)
MONO[0] = 1000.0 + 900.0
check('H2. КРИТИЧНО: по истечении срока — отказ (срок по монотонному времени)',
      arm_check('prun_1', 'it_1', 'pr1', MONO[0]) == (False, 'one_shot_expired')
      and arm_pub(MONO[0])['armed'] is False and arm_pub(MONO[0])['expires_in_s'] == 0)
check('H3. израсходовать истёкшее нельзя',
      arm_consume('prun_1', 'it_1', 'pr1', MONO[0]) == (False, 'one_shot_expired'))
MONO[0] = 1000.0

# ══ K. Один расход ════════════════════════════════════════════════════════════════════════════
unarm(); arm_boot(cli(), now=MONO[0])
check('K1. первый расход проходит', arm_consume('prun_1', 'it_1', 'pr1', MONO[0]) == (True, ''))
check('K2. КРИТИЧНО: вооружение израсходовано', NS['_ONE_SHOT_ARM']['consumed'] is True
      and arm_pub(MONO[0]) ['armed'] is False and arm_pub(MONO[0])['consumed'] is True)
check('K3. КРИТИЧНО: второй расход невозможен',
      arm_consume('prun_1', 'it_1', 'pr1', MONO[0]) == (False, 'one_shot_already_used'))
check('K4. и проверка тоже отказывает', arm_check('prun_1', 'it_1', 'pr1', MONO[0])[0] is False)
check('K5. КРИТИЧНО: автоматически не восстанавливается (даже со временем)',
      (MONO.__setitem__(0, 1000.0 + 10), arm_check('prun_1', 'it_1', 'pr1', MONO[0])[0])[1] is False)
MONO[0] = 1000.0

# ══ L. Десять потоков ═════════════════════════════════════════════════════════════════════════
unarm(); arm_boot(cli(), now=MONO[0])
_res, _lk = [], threading.Lock()
_bar = threading.Barrier(10)


def _race():
    _bar.wait()
    ok, _w = arm_consume('prun_1', 'it_1', 'pr1', MONO[0])
    with _lk:
        _res.append(ok)


_th = [threading.Thread(target=_race) for _ in range(10)]
[t.start() for t in _th]
[t.join() for t in _th]
check('L1. КРИТИЧНО: 10 потоков -> вооружение израсходовано РОВНО один раз', _res.count(True) == 1)
check('L2. остальные девять получили честный отказ', _res.count(False) == 9)

# ══ P. Рестарт без CLI ════════════════════════════════════════════════════════════════════════
unarm()
check('P1. КРИТИЧНО: рестарт без флагов -> НЕ вооружён', arm_boot(['server.py'], now=MONO[0]) is False
      and arm_pub(MONO[0])['armed'] is False and po.transport_allowed('pr1')[0] is False)
check('P2. КРИТИЧНО: кнопка «Перезапустить» СНИМАЕТ вооружение (иначе была бы вторая печать даром)',
      NS['_strip_one_shot_args'](cli()) == ['server.py']
      and NS['_strip_one_shot_args'](['s.py', '--project-one-shot-run=prun_1',
                                      '--project-one-shot-confirm=' + PHRASE]) == ['s.py'])
check('P3. посторонние аргументы перезапуска сохраняются',
      NS['_strip_one_shot_args'](['s.py', '--verbose'] + cli()[1:]) == ['s.py', '--verbose'])
check('P4. статика: _restart_self реально чистит флаги',
      '_strip_one_shot_args(args)' in _SRV
      and _SRV.index('args = _strip_one_shot_args(args)') < _SRV.index('subprocess.Popen(args'))

# ══ R. Вооружение не пишет в БД ═══════════════════════════════════════════════════════════════
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


def snap():
    out = {}
    for t in [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        out[t] = [tuple(repr(v) for v in r) for r in c.execute("SELECT * FROM %s" % t).fetchall()]
    return out


unarm()
_b = snap()
arm_boot(cli(), now=MONO[0]); arm_pub(MONO[0]); arm_check('prun_1', 'it_1', 'pr1', MONO[0])
arm_consume('prun_1', 'it_1', 'pr1', MONO[0]); arm_pub(MONO[0])
check('R1. КРИТИЧНО: весь жизненный цикл вооружения НЕ трогает БД ни на байт', snap() == _b)

# ══ I-J, M-O, Q. Расход только на границе адаптера ════════════════════════════════════════════
_pd = _blk('def _orch_prod_dispatch(', 'def _orch_prod_adapters(')
_pd_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _pd))
check('I1. КРИТИЧНО: расход стоит ВНУТРИ адаптера — ранние отказы права на запуск не сжигают',
      '_one_shot_arm_consume(' in _pd_code)
check('I2. и до расхода в адаптере нет ни одного вызова печати',
      _pd_code.index('_one_shot_arm_consume(') < _pd_code.index('_do_project2_file_print('))
check('J1. ранняя проверка — отдельная ЧИТАЮЩАЯ функция; в adapters arm_check = _one_shot_arm_check '
      '(2.757: подключается, когда печать из приложения выключена)',
      'a["arm_check"] = _one_shot_arm_check' in _SRV)
_sic = _MOD[_MOD.index('def start_item_controlled'):_MOD.index('def _apply_dispatch_result')]
check('J2. КРИТИЧНО: ранняя проверка стоит ДО reservation',
      _sic.index('arm_check') < _sic.index('reserve_printer'))
check('J3. КРИТИЧНО: оркестратор вооружение НЕ расходует (это делает только адаптер на границе)',
      'arm_consume' not in _sic)
_cons = re.findall(r'_one_shot_arm_consume\(', _SRV)
check('M1. КРИТИЧНО: точка расхода в коде РОВНО одна', len(_cons) == 2)   # def + один вызов
check('N1. вооружение — только в памяти процесса: ни один модуль его не сохраняет',
      not re.search(r'_ONE_SHOT_ARM[^\n]*(?:json|dump|write|INSERT|UPDATE)', _SRV))
check('O1. после расхода повтор невозможен ЛЮБЫМ путём (адаптер получит отказ)',
      arm_check('prun_1', 'it_1', 'pr1', MONO[0])[0] is False)
check('Q1. recovery не трогает вооружение и не повторяет отправку',
      'one_shot' not in re.sub(r'#.*', '', _MOD[_MOD.index('def recover_on_start'):_MOD.index('def _classify_recovered')]))

# ══ T. Итоговые границы ═══════════════════════════════════════════════════════════════════════
unarm()
check('T1. КРИТИЧНО: значения по умолчанию — выключено и пусто', po.DISPATCH_ENABLED is False
      and po.TRANSPORT_ENABLED is False and po.ALLOWED_PRINTER_IDS == frozenset())
check('T2. и в ФАЙЛЕ они тоже False/пусто (а не только в рантайме)',
      re.search(r'^DISPATCH_ENABLED = False$', _MOD, re.M) and re.search(r'^TRANSPORT_ENABLED = False$', _MOD, re.M)
      and re.search(r'^ALLOWED_PRINTER_IDS = frozenset\(\)$', _MOD, re.M))
check('T3. фраза подтверждения — точная константа', _ONE := PHRASE == 'I_UNDERSTAND_THIS_SENDS_A_REAL_PRINT')
check('T4. срок жизни вооружения не больше 15 минут', re.search(r'^_ONE_SHOT_TTL_S = 900\.0', _SRV, re.M))
check('T5. воркеры пула не вооружаются', re.search(r'if not _IS_POOL_WORKER:\s*\n\s*try:\s*\n\s*_one_shot_boot_arm\(\)', _SRV))
check('T6. НИ ОДНОГО вызова печати/сети за весь тест: BOOM=%r' % (BOOM,), BOOM == [])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: вооружение приходит ТОЛЬКО из командной строки (не HTTP, не окружение, не БД, не '
              'файл), требует полного точного набора и точной фразы, действует на одну пару '
              'run/item/printer максимум 15 минут по монотонному времени и расходуется РОВНО один раз '
              '(10 потоков -> один); ранние отказы его не сжигают, расход стоит на границе адаптера; '
              'перезапуск — в том числе кнопкой — вооружение снимает; статус read-only и без секретов'))
raise SystemExit(1 if fail else 0)
