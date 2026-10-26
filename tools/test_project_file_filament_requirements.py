# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Требования файла к филаменту (материал/цвет ИЗ САМОГО ФАЙЛА) — core Alpha 2.742 (этап 5A2a).
# ЗАЧЕМ. Существующий _bambu_ams_mapping читает из 3mf ТОЛЬКО ЧИСЛО филаментов: filament_colour
# берётся ради len(), сами цвета выбрасываются. Чтобы доказать источник подачи, нужны САМИ значения.
# Здесь проверяются РЕАЛЬНЫЕ helper'ы ядра (_3mf_filament_requirements/_file_filament_requirements)
# на НАСТОЯЩИХ zip/3mf-архивах, собранных в тесте. Главное, что доказываем: ничего не угадывается —
# ни по имени файла, ни по имени профиля; нет значения -> None.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_file_filament_requirements.py  (0 = пройдено)
import hashlib, io, json, os, re, sys, tempfile, zipfile

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
        raise AssertionError('ЗАПРЕЩЕНО в 5A2a: ' + tag)
    return _b


def _block(start, end):
    i = _SRV.index(start)
    return _SRV[i:_SRV.index(end, i)]


# ── песочница ядра: только парсер требований + его зависимости (ДОСЛОВНО из server.py) ─────────
NS = {'json': json, 'io': io, 'zipfile': zipfile, 're': re, 'os': os, 'hashlib': hashlib,
      'log': type('L', (), {'debug': staticmethod(lambda *a, **k: None),
                            'warning': staticmethod(lambda *a, **k: None),
                            'info': staticmethod(lambda *a, **k: None)})(),
      '_exc_brief': lambda: 'x',
      # ловушки: парсер требований не смеет ничего отправлять
      '_send_file_to_printer': bomb('_send_file_to_printer'),
      '_do_project2_file_print': bomb('_do_project2_file_print'),
      '_send_mgr': type('B', (), {'reserve': bomb('_send_mgr.reserve'), 'run': bomb('_send_mgr.run')})(),
      'create_project_print_job': bomb('create_project_print_job')}
exec('import xml.etree.ElementTree as ET', NS)
exec(_block('_REPORT_EMPTY_MAT', 'def _printer_reported_filament('), NS)   # _reported_material_norm + _norm_hex_color
exec(_block('_REQ_PROJECT_SETTINGS =', '# _normalize_model вынесена'), NS)
exec(_block('def _file_hash(', 'def analyze_project_plate('), NS)   # тот же sha256, что у остального ядра
req_bytes = NS['_3mf_filament_requirements']
req_file = NS['_file_filament_requirements']

TMP = tempfile.mkdtemp()


def mk3mf(name, project_settings=None, slice_info=None, extra=None, raw=None):
    """Настоящий 3mf (zip). project_settings — dict (JSON), slice_info — строка XML."""
    p = os.path.join(TMP, name)
    if raw is not None:
        with open(p, 'wb') as f:
            f.write(raw)
        return p
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('3D/3dmodel.model', '<model/>')
        if project_settings is not None:
            z.writestr('Metadata/project_settings.config', json.dumps(project_settings, ensure_ascii=False))
        if slice_info is not None:
            z.writestr('Metadata/slice_info.config', slice_info)
        z.writestr('Metadata/plate_1.gcode', '; gcode\n')
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    with open(p, 'wb') as f:
        f.write(buf.getvalue())
    return p


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


def row(path, hsh=None, fid='F1'):
    return {"id": fid, "filename": os.path.basename(path), "stored_path": path, "src_path": "",
            "content_hash": (sha(path) if hsh is None else hsh)}


SLICE_ONE = ('<config><plate><metadata key="index" value="1"/>'
             '<metadata key="nozzle_diameters" value="0.4"/>'
             '<filament id="1" tray_info_idx="GFA00" type="PLA" color="#161616" used_g="3.4"/>'
             '</plate></config>')

# ── 1. Одинарный филамент: project_settings ────────────────────────────────────────────────────
p = mk3mf('one.3mf', project_settings={"filament_type": ["PETG"], "filament_colour": ["#161616"],
                                       "filament_settings_id": ["Bambu PETG Basic @BBL X1C"],
                                       "nozzle_diameter": ["0.4"]})
r = req_file(row(p))
check('R1. single-filament 3mf: status=ok', r['status'] == 'ok' and r['reason'] == '')
check('R2. число филаментов = 1', r['filament_count'] == 1)
check('R3. материал извлечён ИЗ ФАЙЛА как есть', r['filaments'][0]['material'] == 'PETG')
check('R4. цвет извлечён и нормализован в #RRGGBB', r['filaments'][0]['color_hex'] == '#161616')
check('R5. file_index = 0', r['filaments'][0]['file_index'] == 0)
check('R6. nozzle сохранён, если доступен', r['nozzle'] == '0.4')
check('R7. источник назван честно', r['source'] == '3mf:project_settings')
check('R8. file_hash = реальный sha256 файла', r['file_hash'] == sha(p))

# ── 2. slice_info как источник ─────────────────────────────────────────────────────────────────
p = mk3mf('slice.3mf', slice_info=SLICE_ONE)
r = req_file(row(p))
check('R9. slice_info.config: материал/цвет извлечены (id 1-based -> file_index 0)',
      r['filaments'][0]['material'] == 'PLA' and r['filaments'][0]['color_hex'] == '#161616'
      and r['filaments'][0]['file_index'] == 0)
check('R10. plate/nozzle из slice_info сохранены', r['plate'] == '1' and r['nozzle'] == '0.4')
check('R11. источник — slice_info', r['source'] == '3mf:slice_info')

# ── 3. Приоритет и дополнение ──────────────────────────────────────────────────────────────────
p = mk3mf('both.3mf', project_settings={"filament_type": ["PETG"], "filament_colour": ["#FF0000"]},
          slice_info=SLICE_ONE)
r = req_file(row(p))
check('R12. project_settings имеет приоритет над slice_info (как у существующего helper\'а)',
      r['filaments'][0]['material'] == 'PETG' and r['filaments'][0]['color_hex'] == '#FF0000')
check('R13. оба источника названы', r['source'] == '3mf:project_settings+slice_info')
p = mk3mf('fill.3mf', project_settings={"filament_type": ["PETG"], "filament_colour": [None]},
          slice_info=SLICE_ONE)
r = req_file(row(p))
check('R14. недостающее поле ДОПОЛНЯЕТСЯ вторым источником (цвет из slice_info)',
      r['filaments'][0]['material'] == 'PETG' and r['filaments'][0]['color_hex'] == '#161616')

# ── 4. Имя файла НЕ источник ───────────────────────────────────────────────────────────────────
p = mk3mf('PETG_RED_#FF0000_plate.3mf', project_settings={"filament_settings_id": ["Generic PETG @BBL"]})
r = req_file(row(p))
check('R15. КРИТИЧНО: имя файла НЕ используется как материал (счёт есть, материала нет)',
      r['status'] == 'ok' and r['filament_count'] == 1 and r['filaments'][0]['material'] is None)
check('R16. КРИТИЧНО: имя файла НЕ используется как цвет', r['filaments'][0]['color_hex'] is None)
check('R17. КРИТИЧНО: имя ПРОФИЛЯ не сокращается до материала (Generic PETG -> не PETG)',
      r['filaments'][0]['material'] is None)
_src = _block('def _3mf_filament_requirements(', 'def _file_filament_requirements(')
check('R18. статика: в парсере требований нет ни filename, ни basename',
      'filename' not in _src and 'basename' not in _src)

# ── 5. Отсутствующие значения ──────────────────────────────────────────────────────────────────
p = mk3mf('nomat.3mf', project_settings={"filament_colour": ["#161616"]})
r = req_file(row(p))
check('R19. нет материала -> material=None (не угадываем)',
      r['filament_count'] == 1 and r['filaments'][0]['material'] is None
      and r['filaments'][0]['color_hex'] == '#161616')
p = mk3mf('nocol.3mf', project_settings={"filament_type": ["PLA"]})
r = req_file(row(p))
check('R20. нет цвета -> color_hex=None', r['filaments'][0]['color_hex'] is None
      and r['filaments'][0]['material'] == 'PLA')
p = mk3mf('badcol.3mf', project_settings={"filament_type": ["PLA"], "filament_colour": ["не-цвет"]})
check('R21. невалидный HEX -> None (мусор цветом не считается)',
      req_file(row(p))['filaments'][0]['color_hex'] is None)
p = mk3mf('alpha.3mf', project_settings={"filament_type": ["PLA"], "filament_colour": ["161616FF"]})
check('R22. RRGGBBAA принимается, alpha отбрасывается',
      req_file(row(p))['filaments'][0]['color_hex'] == '#161616')

# ── 6. Число филаментов ────────────────────────────────────────────────────────────────────────
p = mk3mf('zero.3mf', project_settings={"some_other_key": 1})
r = req_file(row(p))
check('R23. конфиг без филаментов -> count=0 (вызывающий скажет filament_count_unknown)',
      r['status'] == 'ok' and r['filament_count'] == 0 and r['filaments'] == [])
p = mk3mf('nocfg.3mf')
check('R24. 3mf вообще без конфигов -> count=0', req_file(row(p))['filament_count'] == 0)
p = mk3mf('multi.3mf', project_settings={"filament_type": ["PLA", "PETG"],
                                         "filament_colour": ["#000000", "#FFFFFF"]})
r = req_file(row(p))
check('R25. multi-filament: count=2 и ОБА филамента извлечены (blocked решает план, не парсер)',
      r['filament_count'] == 2 and [f['material'] for f in r['filaments']] == ['PLA', 'PETG']
      and [f['color_hex'] for f in r['filaments']] == ['#000000', '#FFFFFF'])
p = mk3mf('ragged.3mf', project_settings={"filament_type": ["PLA", "PETG"], "filament_colour": ["#000000"]})
r = req_file(row(p))
check('R26. рваные списки: count по длинному, недостающее -> None (не выдумываем)',
      r['filament_count'] == 2 and r['filaments'][1]['color_hex'] is None)

# ── 7. Unicode и составные расширения ──────────────────────────────────────────────────────────
p = mk3mf('Деталь Ф-1.gcode.3mf', project_settings={"filament_type": ["PLA Матовый"],
                                                    "filament_colour": ["#00A0E3"]})
r = req_file(row(p))
check('R27. Unicode-имя файла и Unicode-материал не ломают разбор',
      r['status'] == 'ok' and r['filaments'][0]['material'] == 'PLA Матовый'
      and r['filaments'][0]['color_hex'] == '#00A0E3')
check('R28. составное расширение .gcode.3mf разбирается штатно', r['filament_count'] == 1)
p = mk3mf('ws.3mf', project_settings={"filament_type": ["  PETG  "], "filament_colour": ["  #161616 "]})
check('R29. пробелы по краям обрезаются, исходный регистр материала сохраняется',
      req_file(row(p))['filaments'][0]['material'] == 'PETG')

# ── 8. Файл/хеш ────────────────────────────────────────────────────────────────────────────────
r = req_file({"id": "F1", "filename": "нет.3mf", "stored_path": os.path.join(TMP, 'нет.3mf'),
              "src_path": "", "content_hash": "abc"})
check('R30. файла нет на диске -> file_missing', r['status'] == 'error' and r['reason'] == 'file_missing')
r = req_file({"id": "F1", "filename": "x.3mf", "stored_path": "", "src_path": "", "content_hash": ""})
check('R31. пустой путь -> file_missing', r['reason'] == 'file_missing')
p = mk3mf('hash.3mf', project_settings={"filament_type": ["PLA"], "filament_colour": ["#000000"]})
r = req_file(row(p, hsh='устаревший_хеш'))
check('R32. КРИТИЧНО: хеш изменился -> file_hash_changed (требованиям верить нельзя)',
      r['status'] == 'error' and r['reason'] == 'file_hash_changed')
check('R33. отдаётся и фактический, и ожидавшийся хеш',
      r['file_hash'] == sha(p) and r['expected_hash'] == 'устаревший_хеш')
r = req_file(row(p, hsh=''))
check('R34. пустой content_hash сверку не проваливает (старые строки), хеш вычисляется',
      r['status'] == 'ok' and r['file_hash'] == sha(p))

# ── 9. Битый архив — fail-open ─────────────────────────────────────────────────────────────────
p = mk3mf('broken.3mf', raw='это вообще не zip'.encode('utf-8'))
r = req_file(row(p))
check('R35. битый архив: НЕ исключение, а честный count=0', r['status'] == 'ok' and r['filament_count'] == 0)
p = mk3mf('badjson.3mf', extra={'Metadata/project_settings.config': '{это не json'})
check('R36. невалидный JSON конфига -> count=0, без исключения', req_file(row(p))['filament_count'] == 0)
p = mk3mf('badxml.3mf', slice_info='<config><plate><filament id="1" ')
check('R37. невалидный XML конфига -> count=0, без исключения', req_file(row(p))['filament_count'] == 0)
p = mk3mf('truncated.3mf', raw=b'PK\x03\x04' + b'\x00' * 40)
check('R38. обрезанный zip -> count=0, без исключения', req_file(row(p))['filament_count'] == 0)
check('R39. парсер байтов терпит мусор на входе',
      req_bytes(b'') ['filament_count'] == 0 and req_bytes(None)['filament_count'] == 0)

# ── 10. Ни одного вызова печати ────────────────────────────────────────────────────────────────
check('R40. извлечение требований — чистое чтение: НИ ОДНОГО вызова печати (BOOM=%r)' % (BOOM,), BOOM == [])
_all = _block('_REQ_PROJECT_SETTINGS =', '# _normalize_model вынесена')
check('R41. в блоке требований нет транспорта/отправки/создания задания',
      not re.search(r'_send_mgr|_send_file_to_printer|_do_project2_file_print|mqtt|ftplib|storbinary'
                    r'|create_project_print_job|after_dispatch', _all))
check('R42. существующий _bambu_ams_mapping НЕ тронут (он на печатном пути)',
      'def _bambu_ams_mapping(data3mf):' in _SRV
      and 'Возвращает (use_ams: bool, ams_mapping: list)' in _SRV)

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: материал и цвет берутся ИЗ САМОГО ФАЙЛА (project_settings + дополнение из '
              'slice_info), имя файла и имя профиля источником НЕ являются; отсутствующее значение '
              'честно None, битый архив/JSON/XML и обрезанный zip дают count=0 без исключения, '
              'пропавший файл и изменившийся хеш названы точными причинами; печать не тронута'))
raise SystemExit(1 if fail else 0)
