# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# FlashForge: извлечение чистого g-code из 3mf-контейнера перед отправкой — core Alpha 2.764.
# ПРИЧИНА (поймана на живой ферме, 3 из 3 отправок). Слайсеры Orca/Bambu отдают .gcode.3mf —
# ZIP-контейнер; настоящий g-code лежит внутри (Metadata/plate_1.gcode). До 2.764 принтеру уходил
# ВЕСЬ контейнер с printNow=true: прошивка Adventurer 5M 3.1.5 пыталась исполнить zip как g-code,
# сообщала «print failure» и зависала НАМЕРТВО (лечится только выключением питания принтера).
# Здесь доказываем: (1) извлечение отдаёт байты g-code БЕЗ изменений (md5 сверяется), (2) любая
# неоднозначность — отказ ДО отправки, (3) ветка отправки шлёт принтеру извлечённый g-code, а хуки
# склада и учёт продолжают жить с ИСХОДНЫМ контейнером (там метаданные филамента).
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_flashforge_3mf_extract.py   (0 = пройдено)
import hashlib, io, os, re, zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()

fail = 0


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def _fn_src(name):
    m = re.search(r'^def %s\(' % re.escape(name), _SRV, re.M)
    assert m, 'в server.py не найдено: ' + name
    i = m.start()
    j = re.search(r'\n(?=(?:async )?def |class |@app\.)', _SRV[i:])
    return _SRV[i:i + (j.start() if j else len(_SRV))]


# ── настоящая функция из server.py ─────────────────────────────────────────────────────────────
NS = {'zipfile': zipfile, 'io': io, 'hashlib': hashlib}
exec(_fn_src('_ff_extract_gcode_from_3mf'), NS)
X = NS['_ff_extract_gcode_from_3mf']


def mk3mf(entries):
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, 'w')
    for n, data in entries.items():
        z.writestr(n, data)
    z.close()
    return buf.getvalue()


GC = '; HEADER_BLOCK_START\nG28 ; home\nG1 X10 Y10\n'
GOOD = mk3mf({'[Content_Types].xml': '<xml/>', '3D/3dmodel.model': '<model/>',
              'Metadata/plate_1.gcode': GC,
              'Metadata/plate_1.gcode.md5': hashlib.md5(GC.encode()).hexdigest(),
              'Metadata/project_settings.config': '{}'})

# ── 1. Извлечение: байты НЕ меняются, имя правильное ───────────────────────────────────────────
ok, name, data, why = X('Part_PETG_1h.gcode.3mf', GOOD)
check('E1. КРИТИЧНО: из контейнера извлечён РОВНО plate_1.gcode (байт-в-байт)',
      ok and data == GC.encode() and why == '')
check('E2. имя загрузки: .gcode.3mf -> .gcode (принтеру уходит имя без контейнерного суффикса)',
      name == 'Part_PETG_1h.gcode')
check('E3. .3mf без двойного суффикса -> имя дополняется .gcode',
      X('Part.3mf', GOOD)[1] == 'Part.gcode')

# ── 2. Fail-closed: неоднозначность = отказ ДО принтера ────────────────────────────────────────
check('E4. КРИТИЧНО: контейнер без g-code -> отказ no_gcode_in_3mf',
      X('a.gcode.3mf', mk3mf({'Metadata/x.txt': 'hi'})) == (False, '', b'', 'no_gcode_in_3mf'))
check('E5. КРИТИЧНО: два g-code без plate_1 -> отказ (не гадаем, какой печатать)',
      X('a.gcode.3mf', mk3mf({'Metadata/a.gcode': GC, 'Metadata/b.gcode': GC}))[3] == 'ambiguous_gcode_in_3mf')
check('E6. один g-code с нестандартным именем -> извлекается однозначно',
      X('a.gcode.3mf', mk3mf({'weird/path.gcode': GC}))[0] is True)
check('E7. КРИТИЧНО: битая контрольная сумма -> отказ gcode_md5_mismatch (обрезанный файл не печатаем)',
      X('a.gcode.3mf', mk3mf({'Metadata/plate_1.gcode': GC,
                              'Metadata/plate_1.gcode.md5': 'deadbeef' * 4}))[3] == 'gcode_md5_mismatch')
check('E8. не-zip мусор -> отказ bad_3mf_container (не исключение)',
      X('a.gcode.3mf', b'\x00\x01garbage')[0] is False
      and X('a.gcode.3mf', b'\x00\x01garbage')[3].startswith('bad_3mf_container'))

# ── 3. Ветка отправки: извлечение стоит НА ПРОВОДЕ, а учёт живёт исходным файлом ───────────────
_send = _fn_src('_send_file_to_printer')
_ffb = _send[_send.index('elif ptype == "flashforge":'):]
check('F1. КРИТИЧНО: контейнер распознаётся по magic PK и извлекается ДО _flashforge_upload_print',
      re.search(r'if fdata\[:2\] == b"PK":', _ffb)
      and _ffb.index('_ff_extract_gcode_from_3mf(') < _ffb.index('_flashforge_upload_print('))
check('F2. КРИТИЧНО: принтеру уходит ИЗВЛЕЧЁННОЕ (_ff_fname/_ff_fdata), а не контейнер',
      '_flashforge_upload_print(pip, pport, ptoken, _ff_fname, _ff_fdata, print_now=False)' in _ffb
      and '_flashforge_upload_print(pip, pport, ptoken, fname, fdata)' not in _ffb)
# ── Alpha 2.768: ДВУХФАЗНЫЙ запуск (совмещённый printNow=true вешал прошивку даже на чистом файле) ──
check('F2b. КРИТИЧНО: загрузка идёт БЕЗ старта (print_now=False) — сбой любого шага = печати точно нет',
      'print_now=False' in _ffb)
check('F2c. КРИТИЧНО: между загрузкой и стартом — пауза и ПРОВЕРКА файла через gcodeList',
      _ffb.index('_flashforge_upload_print(') < _ffb.index('time.sleep(')
      < _ffb.index('_flashforge_files(pip, pport, ptoken)')
      < _ffb.index('_flashforge_print(pip, pport, ptoken, _target)'))
check('F2d. КРИТИЧНО: файла нет в списке -> отказ ДО команды старта, канонический definite-код',
      re.search(r'if _target is None:[\s\S]{0,400}"reason": "file not found"', _ffb)
      and _ffb.index('"reason": "file not found"') < _ffb.index('_flashforge_print(pip, pport, ptoken, _target)'))
check('F2e. старт — ОТДЕЛЬНОЙ командой /printGcode по имени, которое ВЕРНУЛ принтер (_target)',
      '_flashforge_print(pip, pport, ptoken, _target)' in _ffb)
check('F3. КРИТИЧНО: отказ извлечения -> return error ДО загрузки (принтер не тронут)',
      _ffb.index('return {"status": "error", "reason": "The 3mf container has no usable g-code')
      < _ffb.index('_flashforge_upload_print('))
check('F4. КРИТИЧНО: хуки склада и привязки получают ИСХОДНЫЙ контейнер (метаданные филамента в 3mf)',
      '_run_after_dispatch_hooks(pid, [0], fdata, fname)' in _ffb
      and '_stash_run_assignments(pid, [0], fdata, True)' in _ffb)
check('F5. server_print запоминает ИСХОДНОЕ имя ДО ветки (корреляция задания не ломается)',
      _send.index('server_print[pid] = fname') < _send.index('elif ptype == "flashforge":'))
check('F6. чистый .gcode (не PK) отправляется как раньше — извлечение его не трогает',
      '_ff_fname, _ff_fdata = fname, fdata' in _ffb)

# ── 4. Alpha 2.767: санитайзер — klipper-расширения Orca валят прошивку A5M ────────────────────
# На ферме 6 из 6 отправок вешали принтер НАМЕРТВО; решающий эксперимент (2.765, полная тишина в
# эфире 10 c после старта) исключил конкурентные запросы. В файле: EXCLUDE_OBJECT_DEFINE ОДНОЙ
# строкой на 3.6 КБ — ПЕРВАЯ команда файла + 87 SET_VELOCITY_LIMIT. Убираем только их и усекаем
# комментарии-простыни; траектории (G0/G1/E) не меняются ни байтом.
exec(_fn_src('_ff_sanitize_gcode'), NS)
S = NS['_ff_sanitize_gcode']
GSRC = (b'; header\n'
        b'EXCLUDE_OBJECT_DEFINE NAME=x POLYGON=' + b'[' * 3000 + b'\n'
        b'M73 P0 R2\n'
        b'SET_VELOCITY_LIMIT VELOCITY=500\n'
        b'G1 X10 Y10 E5\n'
        b'EXCLUDE_OBJECT_START NAME=x\n'
        b'G1 X20 Y20 E10\n'
        b'EXCLUDE_OBJECT_END NAME=x\n'
        b'; ' + b'c' * 900 + b'\n'
        b'G1 X30 Y30 E15\n')
G2, NREM = S(GSRC)
check('S1. КРИТИЧНО: EXCLUDE_OBJECT_*/SET_VELOCITY_LIMIT вычищены, счётчик честный (4 + 1 комментарий)',
      NREM == 5 and b'EXCLUDE_OBJECT' not in G2 and b'SET_VELOCITY_LIMIT' not in G2)
check('S2. КРИТИЧНО: траектории целы — все G1/M73 на месте и в прежнем порядке',
      G2.count(b'G1 ') == 3 and b'M73 P0 R2' in G2
      and G2.index(b'M73') < G2.index(b'G1 X10') < G2.index(b'G1 X20') < G2.index(b'G1 X30'))
check('S3. КРИТИЧНО: комментарий-простыня усечён (буфер парсера конечен), обычный комментарий цел',
      max(len(l) for l in G2.split(b'\n')) <= 512 and b'; header' in G2)
check('S4. КРИТИЧНО: длинная НЕ-комментарий строка (кроме BAD) НЕ трогается — чужие команды не режем',
      S(b'G1 X1 ' + b'E' * 600 + b'\nG28\n')[1] == 0)
check('S5. no-op: чистый g-code возвращается БАЙТ-В-БАЙТ (removed=0)',
      S(b'G28\nG1 X10 E5\nM104 S200\n') == (b'G28\nG1 X10 E5\nM104 S200\n', 0))
check('S6. идемпотентность: повторный проход ничего не находит', S(G2) == (G2, 0))
_ffb2 = _fn_src('_send_file_to_printer')
_ffb2 = _ffb2[_ffb2.index('elif ptype == "flashforge":'):]
check('S7. КРИТИЧНО: ветка отправки зовёт санитайзер ПОСЛЕ извлечения и ДО загрузки',
      _ffb2.index('_ff_extract_gcode_from_3mf(') < _ffb2.index('_ff_sanitize_gcode(')
      < _ffb2.index('_flashforge_upload_print('))

# ── 5. Alpha 2.767: осиротевшие dispatched-задания чистятся на загрузке ────────────────────────
# Зависший принтер оставлял pjob со status='dispatched' навсегда: _pjob_candidates выдавал их все,
# корреляция следующей печати давала ambiguous_multi («учёт не ведём») и шквал строк в логе.
import sqlite3, threading
_c = sqlite3.connect(':memory:', check_same_thread=False)
_c.row_factory = sqlite3.Row
_c.execute("CREATE TABLE project_print_jobs (id TEXT PRIMARY KEY, status TEXT, counted_at TEXT DEFAULT '', finished_at TEXT DEFAULT '')")
_c.execute("CREATE TABLE project_run_items (id TEXT PRIMARY KEY, project_print_job_id TEXT, state TEXT)")
_c.executemany("INSERT INTO project_print_jobs (id, status) VALUES (?,?)",
               [('pj_orphan', 'dispatched'), ('pj_live', 'dispatched'),
                ('pj_pending', 'dispatched'), ('pj_done', 'finished'),
                ('pj_observed', 'dispatched')])
_c.executemany("INSERT INTO project_run_items (id, project_print_job_id, state) VALUES (?,?,?)",
               [('i1', 'pj_live', 'ambiguous_after_dispatch'), ('i2', 'pj_pending', 'pending')])
# _fn_src захватывает и boot-блок после функции — глушим его: _IS_POOL_WORKER=True пропускает
# запуск чистки при exec (сам вызов проверяем явно ниже), log/_exc_brief — простые заглушки.
# Alpha 2.807: чистка дополнительно спрашивает, какие задания принадлежат ЖИВЫМ наблюдаемым
# запускам — здесь это подставной список (сам движок проверяется test_external_reprint_sync).
PJ = {'lock_p': threading.Lock(), 'conn_p': _c, '_IS_POOL_WORKER': True,
      'log': type('L', (), {'warning': staticmethod(lambda *a, **k: None)})(),
      '_exc_brief': lambda: 'x',
      '_pjl_live_job_ids': lambda: {'pj_observed'}}
exec(_fn_src('fail_project_print_job'), PJ)
exec(_fn_src('_pjob_recover_stale'), PJ)
_n = PJ['_pjob_recover_stale']()
st = {r['id']: r['status'] for r in _c.execute("SELECT id, status FROM project_print_jobs")}
check('S8. КРИТИЧНО: осиротевшие dispatched (без item ИЛИ item уже pending) помечены failed',
      _n == 2 and st['pj_orphan'] == 'failed' and st['pj_pending'] == 'failed')
check('S9. КРИТИЧНО: ЖИВОЕ задание (item ambiguous — нужно resolve(started)) НЕ тронуто',
      st['pj_live'] == 'dispatched')
check('S10. завершённые задания не тронуты; повторная чистка идемпотентна',
      st['pj_done'] == 'finished' and PJ['_pjob_recover_stale']() == 0)
check('S11. чистка вызывается на загрузке (boot-блок _IS_POOL_WORKER)',
      '_npj = _pjob_recover_stale()' in _SRV)
# Alpha 2.807 — РЕГРЕССИЯ УЧЁТА ВНЕШНЕЙ ПЕЧАТИ. У печати с экрана принтера и у обычной ручной
# отправки строки-владельца в project_run_items нет и быть не может (на рабочей ферме таблица
# пуста вовсе), поэтому прежнее условие гасило ВСЕ задания, включая задание идущей печати.
check('S12. КРИТИЧНО (2.807): задание ЖИВОГО наблюдаемого запуска НЕ гасится, хотя item отсутствует',
      st['pj_observed'] == 'dispatched')
_PJ_FAILSAFE = dict(PJ)
_PJ_FAILSAFE['_pjl_live_job_ids'] = lambda: (_ for _ in ()).throw(RuntimeError('unavailable'))
_c.execute("UPDATE project_print_jobs SET status='dispatched', counted_at='' WHERE id='pj_orphan'")
exec(_fn_src('_pjob_recover_stale'), _PJ_FAILSAFE)
check('S13. КРИТИЧНО (2.807): список живых запусков недоступен -> уборка ПРОПУСКАЕТСЯ, вслепую не гасим',
      _PJ_FAILSAFE['_pjob_recover_stale']() == 0
      and _c.execute("SELECT status FROM project_print_jobs WHERE id='pj_orphan'").fetchone()['status'] == 'dispatched')

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: FlashForge получает ЧИСТЫЙ g-code (извлечение из 3mf + вычистка klipper-расширений '
              'Orca, валящих прошивку A5M); траектории не меняются ни байтом; любая неоднозначность — '
              'отказ ДО принтера; осиротевшие dispatched-задания чистятся на загрузке, живые — нет'))
raise SystemExit(1 if fail else 0)
