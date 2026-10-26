# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# План подачи филамента (feed plan) — core Alpha 2.742 (этап 5A2a).
# ЗАЧЕМ. Главный инвариант функции: источник подачи должен быть ДОКАЗАН. До 2.742 доказывать было
# нечем — ams_slot нигде не вычислялся, Auto тихо уходил на внешнюю катушку при провале телеметрии,
# а проверка материала была чисто справочной. Здесь доказываем: нечем доказать -> НЕ ready; близкий
# цвет и «заявлено складом» сами по себе автозапуск не разрешают; Auto/None в план не попадает.
# Проверяются РЕАЛЬНЫЕ функции app/project_orchestrator.py на временной БД и generic-снимках ядра.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_feed_plan.py   (0 = пройдено)
import importlib.util, os, re, sqlite3, tempfile, threading, uuid

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
        raise AssertionError('ЗАПРЕЩЕНО в 5A2a: ' + tag)
    return _b


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


# ══ T. ЭТАЛОН CIEDE2000: Sharma/Wu/Dalal (2005), Table 1 — 34 пары, точность 1e-4 ══════════════
# Единственная защита от «тихо неправильной» формулы: CIEDE2000 легко реализовать ПОЧТИ верно.
SHARMA = [
    (50.0000, 2.6772, -79.7751, 50.0000, 0.0000, -82.7485, 2.0425),
    (50.0000, 3.1571, -77.2803, 50.0000, 0.0000, -82.7485, 2.8615),
    (50.0000, 2.8361, -74.0200, 50.0000, 0.0000, -82.7485, 3.4412),
    (50.0000, -1.3802, -84.2814, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -1.1848, -84.8006, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -0.9009, -85.5211, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, 0.0000, 0.0000, 50.0000, -1.0000, 2.0000, 2.3669),
    (50.0000, -1.0000, 2.0000, 50.0000, 0.0000, 0.0000, 2.3669),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0009, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0010, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0011, 7.2195),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0012, 7.2195),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0009, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0010, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0011, -2.4900, 4.7461),
    (50.0000, 2.5000, 0.0000, 50.0000, 0.0000, -2.5000, 4.3065),
    (50.0000, 2.5000, 0.0000, 73.0000, 25.0000, -18.0000, 27.1492),
    (50.0000, 2.5000, 0.0000, 61.0000, -5.0000, 29.0000, 22.8977),
    (50.0000, 2.5000, 0.0000, 56.0000, -27.0000, -3.0000, 31.9030),
    (50.0000, 2.5000, 0.0000, 58.0000, 24.0000, 15.0000, 19.4535),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.1736, 0.5854, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2972, 0.0000, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 1.8634, 0.5757, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2592, 0.3350, 1.0000),
    (60.2574, -34.0099, 36.2677, 60.4626, -34.1751, 39.4387, 1.2644),
    (63.0109, -31.0961, -5.8663, 62.8187, -29.7946, -4.0864, 1.2630),
    (61.2901, 3.7196, -5.3901, 61.4292, 2.2480, -4.9620, 1.8731),
    (35.0831, -44.1164, 3.7933, 35.0232, -40.0716, 1.5901, 1.8645),
    (22.7233, 20.0904, -46.6940, 23.0331, 14.9730, -42.5619, 2.0373),
    (36.4612, 47.8580, 18.3852, 36.2715, 50.5065, 21.2231, 1.4146),
    (90.8027, -2.0831, 1.4410, 91.1528, -1.6435, 0.0447, 1.4441),
    (90.9257, -0.5406, -0.9208, 88.6381, -0.8985, -0.7239, 1.5381),
    (6.7747, -0.2908, -2.4247, 5.8714, -0.0985, -2.2286, 0.6377),
    (2.0776, 0.0795, -1.1350, 0.9033, -0.0636, -0.5514, 0.9082),
]
worst = max(abs(po.ciede2000((a, b, c), (d, e, f)) - x) for a, b, c, d, e, f, x in SHARMA)
check('T1. ΔE00 совпал со ВСЕМИ %d эталонными парами Sharma (макс. отклонение %.7f)' % (len(SHARMA), worst),
      worst < 1e-4)
check('T2. ΔE00 симметричен',
      all(abs(po.ciede2000((a, b, c), (d, e, f)) - po.ciede2000((d, e, f), (a, b, c))) < 1e-9
          for a, b, c, d, e, f, _ in SHARMA))
check('T3. ΔE00 самого с собой = 0',
      all(po.ciede2000((a, b, c), (a, b, c)) < 1e-9 for a, b, c, _, _, _, _ in SHARMA))
_lab_w, _lab_k = po.hex_to_lab('#FFFFFF'), po.hex_to_lab('#000000')
# Допуск 1e-3, а не 1e-6: белая точка D65 задана стандартными ОКРУГЛЁННЫМИ значениями
# (0.95047/1.00000/1.08883), поэтому белый даёт L=100.000004. Это ~4e-6 при пороге ΔE00 = 5.0 —
# на решения не влияет никак; точность самой формулы стережёт эталон Sharma (T1, допуск 1e-4).
check('T4. sRGB->Lab: белый = L100/a0/b0, чёрный = L0',
      abs(_lab_w[0] - 100.0) < 1e-3 and abs(_lab_w[1]) < 1e-3 and abs(_lab_w[2]) < 1e-3 and abs(_lab_k[0]) < 1e-6)
check('T5. sRGB->Lab: красный ≈ L53.24 a80.09 b67.20 (опорная точка)',
      all(abs(g - w) < 0.01 for g, w in zip(po.hex_to_lab('#FF0000'), (53.2408, 80.0925, 67.2032))))
check('T6. регистр/формат HEX на сравнение не влияют',
      po.color_relation('#aabbcc', 'AABBCC') == ('exact', 0.0)
      and po.color_relation('#AABBCCFF', '#AABBCC') == ('exact', 0.0))
check('T7. невалидный HEX с любой стороны -> unknown (близким НЕ объявляем)',
      po.color_relation('мусор', '#000000') == ('unknown', None)
      and po.color_relation('#000000', None) == ('unknown', None))
check('T8. порог: ΔE00 <= 5 -> close, > 5 -> mismatch',
      po.color_relation('#000000', '#161616')[0] == 'close'
      and po.color_relation('#000000', '#FF0000')[0] == 'mismatch')

# ══ Нормализация материала: алиасы запрещены ══════════════════════════════════════════════════
check('T9. «My PETG» != «PETG»', po.norm_material('My PETG') != po.norm_material('PETG'))
check('T10. «PETG-CF» != «PETG»', po.norm_material('PETG-CF') != po.norm_material('PETG'))
check('T11. «Generic PETG» НЕ сокращается до «PETG»', po.norm_material('Generic PETG') != po.norm_material('PETG'))
check('T12. регистр/пробелы не мешают: «  petg  » == «PETG»', po.norm_material('  petg  ') == po.norm_material('PETG'))
check('T13. внутренние двойные пробелы схлопываются', po.norm_material('PLA  Matte') == po.norm_material('PLA Matte'))

# ══ Стенд: временная БД + управляемые generic-снимки ══════════════════════════════════════════
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','plate.3mf','h1',1)")
c.commit()

REQ = {"status": "ok", "reason": "", "filament_count": 1, "file_hash": "h1", "plate": "1", "nozzle": "0.4",
       "source": "3mf:project_settings",
       "filaments": [{"file_index": 0, "material": "PETG", "color_hex": "#161616"}]}
SNAP = {"has_ams": True, "slots": []}
REPORTED = {"printer_id": "pr1", "telemetry_available": True, "telemetry_fresh": True, "positions": []}
TRANSPORT = ['bambu']
_bombs = {'_do_project2_file_print': bomb('_do_project2_file_print'),
          '_send_file_to_printer': bomb('_send_file_to_printer'),
          'create_project_print_job': bomb('create_project_print_job'),
          'after_dispatch': bomb('after_dispatch'), 'inv_ledger': bomb('inv_ledger'),
          'mqtt_publish': bomb('mqtt_publish'), 'ftp_storbinary': bomb('ftp_storbinary'),
          'http_transport': bomb('http_transport'),
          'reserve': bomb('_send_mgr.reserve'), 'run': bomb('_send_mgr.run')}


def SAFETY(pid):
    return {"printer_id": pid, "transport": TRANSPORT[0], "status": "IDLE", "status_raw": "IDLE",
            "fresh": True, "user_stopped_pending": False, "printing_active": False,
            "safe_idle": True, "unsafe_reason": ""}


def wire(boot='boot_A'):
    po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], boot,
            printer_status_fn=lambda pid: ("IDLE", True), safety_fn=SAFETY,
            printers_fn=lambda: [{"id": "pr1", "name": "X1C", "type": TRANSPORT[0]}],
            send_reserved_fn=lambda: set(), file_ok_fn=lambda f: True,
            file_requirements_fn=lambda fr: dict(REQ),
            filament_snapshot_fn=lambda pid: dict(SNAP),
            reported_filament_fn=lambda pid: dict(REPORTED))


wire()
po.init_db()
c.execute("INSERT INTO project_runs (id, project_id, state, plan_quality, boot_id, created_at, updated_at) "
          "VALUES ('prun_1','prj','running','exact',?,1.0,1.0)", (po._ctx['boot'],))
c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, created_at, updated_at) "
          "VALUES ('it_1','prun_1','prj','F1',1,'pending',1.0,1.0)")
c.commit()


def spool(sid, mat, color):
    return {"id": sid, "material": mat, "color_hex": color, "vendor_name": "V", "color_name": "n"}


def inv_row(index, external, sid, mat, color, bound=True):
    r = {"index": index, "unit": None, "tray": None, "external": external, "offline": False,
         "spool": spool(sid, mat, color)}
    if bound:
        r.update({"inventory_bound": True, "source": "inventory"})
    return r


def rep_pos(index, external, mat, color, present=True, presence=None):
    #  16.09.2026: presence — ЧЕМ подтверждена позиция. У слота AMS принтер видит вставленный лоток
    #  («sensor»), у внешней катушки Bambu материал ВЫБРАН НА ЭКРАНЕ («setting») и остаётся после
    #  того, как катушка кончилась. Подтверждением датчика считается только первое.
    return {"index": index, "unit": None, "tray": None, "external": external, "present": present,
            "presence": (presence or ("setting" if external else "sensor")),
            "reported_material": mat, "reported_color": color}


def build():
    return po.build_feed_plan('prun_1', 'it_1', 'pr1', now=1000.0)


# ── A. Без Inventory provider ──────────────────────────────────────────────────────────────────
SNAP = {"has_ams": True, "slots": []}
p = build()
check('A1. складского провайдера нет -> attention_required/inventory_source_unavailable',
      p['status'] == 'attention_required' and p['reason'] == 'inventory_source_unavailable')
check('A2. подача НЕ назначена (ams_slot остаётся None — Auto не изобретаем)', p['ams_slot'] is None)

# ── B. Telemetry-only строка не катушка ────────────────────────────────────────────────────────
SNAP = {"has_ams": True, "slots": [{"index": 0, "external": False, "offline": False,
                                    "spool": spool("sp_x", "PETG", "#161616")}]}   # без inventory_bound/source
p = build()
check('B1. КРИТИЧНО: строка БЕЗ inventory_bound/source катушкой не считается',
      p['status'] == 'attention_required' and p['reason'] == 'inventory_source_unavailable')
SNAP = {"has_ams": True, "slots": [{"index": 0, "external": False, "inventory_bound": True,
                                    "source": "inventory", "spool": None}]}
check('B2. inventory_bound без настоящей катушки — не кандидат', build()['reason'] == 'inventory_source_unavailable')
SNAP = {"has_ams": True, "slots": [{"index": 0, "external": False, "inventory_bound": True,
                                    "source": "inventory", "spool": {"id": "", "material": "PETG"}}]}
check('B3. катушка без id — не кандидат', build()['reason'] == 'inventory_source_unavailable')

# ── C-F. Слоты: external −1 / AMS0 / multi-AMS5 / AMS HT512 ────────────────────────────────────
SNAP = {"has_ams": False, "slots": [inv_row(-1, True, "sp_ext", "PETG", "#161616")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [rep_pos(None, True, "PETG", "#161616")]}
p = build()
check('C1. Bambu внешняя катушка: материал с экрана принтера датчиком НЕ подтверждён -> approval_required',
      p['status'] == 'approval_required' and p['reason'] == 'inventory_declared')
check('C2. внешняя = ОТДЕЛЬНАЯ позиция -1 (это НЕ слот AMS 0), mode=external',
      p['ams_slot'] == -1 and p['mode'] == 'external')
check('C3. external сопоставлен с отчётом по ФЛАГУ, значение показано, но подтверждением не считается',
      p['verification'] == 'inventory_declared' and p['reported_material'] == 'PETG')
#  16.09.2026: пустая внешняя позиция («на экране материал не задан») запуск НЕ блокирует — датчика
#  наличия там нет, и «пусто» ничего не доказывает; решает человек.
REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [rep_pos(None, True, None, None, present=False)]}
p = build()
check('C4. внешняя без материала на экране -> approval_required (а не blocked/slot_empty)',
      p['status'] == 'approval_required' and p['reason'] == 'inventory_declared')
#  Если бы подтверждение пришло от ДАТЧИКА подачи, план был бы готов к запуску, как и раньше.
REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [rep_pos(None, True, "PETG", "#161616", presence="sensor")]}
p = build()
check('C5. подтверждение ДАТЧИКОМ подачи -> ready/telemetry_confirmed (прежнее поведение)',
      p['status'] == 'ready' and p['verification'] == 'telemetry_confirmed')
REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [rep_pos(None, True, "PETG", "#161616")]}

#  16.10.2026 (R-137): у H2D склад отдаёт вторую внешнюю строку — левую (ext_side 'left', позиция -2).
#  План подачи знает одну внешнюю позицию -1: левую катушку он сверял бы с ПРАВОЙ подачей принтера.
#  Поэтому левая кандидатом не становится, правая работает как раньше.
_L = dict(inv_row(-2, True, "sp_left", "PETG", "#161616"), ext_side="left")
_R = dict(inv_row(-1, True, "sp_right", "PETG", "#161616"), ext_side="right")
SNAP = {"has_ams": False, "slots": [_L, _R]}
p = build()
check('C6. H2D: левая внешняя катушка (-2) кандидатом не становится, план — на правой -1',
      [c['spool_id'] for c in p['candidates']] == ['sp_right'] and p['ams_slot'] == -1 and p['spool_id'] == 'sp_right')
SNAP = {"has_ams": False, "slots": [_L]}
p = build()
check('C7. H2D: привязана только левая — подача не назначается, решает человек',
      p['ams_slot'] is None and p['status'] == 'attention_required' and not p['candidates'])

for _idx, _label in ((0, 'AMS0'), (5, 'multi-AMS5'), (512, 'AMS HT512')):
    SNAP = {"has_ams": True, "slots": [inv_row(_idx, False, "sp_%d" % _idx, "PETG", "#161616")]}
    REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
                "positions": [rep_pos(_idx, False, "PETG", "#161616")]}
    p = build()
    check('D-F.%s exact -> ready, слот = РЕАЛЬНЫЙ индекс %d (в порядковый не превращаем)' % (_label, _idx),
          p['status'] == 'ready' and p['ams_slot'] == _idx and p['mode'] == 'ams')

# ── G-J. Материал и цвет ───────────────────────────────────────────────────────────────────────
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PLA", "#161616")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, "PLA", "#161616")]}
p = build()
check('G1. материал файла != материал катушки -> blocked/material_mismatch',
      p['status'] == 'blocked' and p['reason'] == 'material_mismatch')
check('G2. подача при blocked НЕ назначается', p['ams_slot'] is None)
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "Generic PETG", "#161616")]}
check('G3. КРИТИЧНО: «Generic PETG» не сокращается до «PETG» -> blocked', build()['reason'] == 'material_mismatch')
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG-CF", "#161616")]}
check('G4. КРИТИЧНО: «PETG-CF» != «PETG» -> blocked', build()['reason'] == 'material_mismatch')
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "", "#161616")]}
check('G5. материал катушки не заполнен -> attention/material_unknown',
      build()['status'] == 'attention_required' and build()['reason'] == 'material_unknown')

SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "  petg ", "#161616")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, "petg", "#161616")]}
check('H1. exact материал (регистр/пробелы) + exact цвет -> ready', build()['status'] == 'ready')

SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#191919")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, "PETG", "#191919")]}
p = build()
check('I1. ΔE00 <= 5 -> approval_required/close_color (автозапуск НЕ разрешается)',
      p['status'] == 'approval_required' and p['reason'] == 'close_color'
      and p['color_relation'] == 'close' and p['requires_approval'] is True)
check('I2. расстояние посчитано и сохранено', isinstance(p['color_distance'], float) and 0 < p['color_distance'] <= 5.0)

SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#FF0000")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, "PETG", "#FF0000")]}
p = build()
check('J1. ΔE00 > 5 -> blocked/color_mismatch', p['status'] == 'blocked' and p['reason'] == 'color_mismatch')
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "не-цвет")]}
check('J2. цвет катушки невалиден -> attention/color_unknown', build()['reason'] == 'color_unknown')

# ── K-L. Телеметрия Bambu ──────────────────────────────────────────────────────────────────────
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#161616")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": False, "positions": [rep_pos(0, False, "PETG", "#161616")]}
check('K1. телеметрия Bambu устарела -> attention/telemetry_stale',
      build()['status'] == 'attention_required' and build()['reason'] == 'telemetry_stale')
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": []}
check('K2. позиции нет в отчёте -> attention/telemetry_stale', build()['reason'] == 'telemetry_stale')
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, None, None, present=True)]}
check('K3. отчёт без материала -> attention/telemetry_stale', build()['reason'] == 'telemetry_stale')
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, "PLA", "#161616")]}
p = build()
check('K4. КРИТИЧНО: принтер сообщает НЕ ТО, что в складе -> blocked/reported_material_mismatch',
      p['status'] == 'blocked' and p['reason'] == 'reported_material_mismatch')
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, None, None, present=False)]}
check('L1. слот пуст по отчёту -> blocked/slot_empty', build()['reason'] == 'slot_empty')

# ── M. Klipper/FlashForge: заявление оператора, а не датчик ────────────────────────────────────
SNAP = {"has_ams": False, "slots": [inv_row(-1, True, "sp_k", "PETG", "#161616")]}
REPORTED = {"telemetry_available": False, "telemetry_fresh": False, "positions": []}
for _t in ('klipper', 'flashforge'):
    TRANSPORT[0] = _t
    p = build()
    check('M1.%s Inventory-declared -> approval_required (датчика нет, ready не бывает)' % _t,
          p['status'] == 'approval_required' and p['reason'] == 'inventory_declared'
          and p['verification'] == 'inventory_declared')
    check('M2.%s логическое назначение подачи: mode=external, ams_slot=-1' % _t,
          p['mode'] == 'external' and p['ams_slot'] == -1)
TRANSPORT[0] = 'bambu'
SNAP = {"has_ams": False, "slots": [inv_row(-1, True, "sp_ext", "PETG", "#161616")]}
REPORTED = {"telemetry_available": False, "telemetry_fresh": False, "positions": []}
p = build()
check('M3. Bambu external без vt_tray/отчёта -> approval_required/inventory_declared (не ready)',
      p['status'] == 'approval_required' and p['reason'] == 'inventory_declared')

# ── N. Детерминированный выбор ─────────────────────────────────────────────────────────────────
REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [rep_pos(0, False, "PETG", "#161616"), rep_pos(5, False, "PETG", "#191919"),
                          rep_pos(3, False, "PLA", "#161616")]}
SNAP = {"has_ams": True, "slots": [inv_row(5, False, "sp_5", "PETG", "#191919"),   # close -> approval
                                   inv_row(3, False, "sp_3", "PLA", "#161616"),    # mismatch -> blocked
                                   inv_row(0, False, "sp_0", "PETG", "#161616")]}  # exact -> ready
p = build()
check('N1. из смеси кандидатов выбран ready (а не первый по порядку словаря)',
      p['status'] == 'ready' and p['ams_slot'] == 0 and p['spool_id'] == 'sp_0')
check('N2. все кандидаты возвращены для UI, порядок — ready, approval, blocked',
      [x['status'] for x in p['candidates']] == ['ready', 'approval_required', 'blocked'])
SNAP = {"has_ams": True, "slots": list(reversed(SNAP['slots']))}
p2 = build()
check('N3. обратный порядок строк даёт ТОТ ЖЕ выбор (детерминизм, а не «повезло»)',
      p2['spool_id'] == 'sp_0' and [x['status'] for x in p2['candidates']] == [x['status'] for x in p['candidates']])
SNAP = {"has_ams": True, "slots": [inv_row(5, False, "sp_b", "PETG", "#161616"),
                                   inv_row(0, False, "sp_a", "PETG", "#161616")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [rep_pos(0, False, "PETG", "#161616"), rep_pos(5, False, "PETG", "#161616")]}
p = build()
check('N4. два ОДИНАКОВЫХ ready -> детерминированно меньший слот', p['ams_slot'] == 0 and p['spool_id'] == 'sp_a')
check('N5. повторный расчёт даёт тот же ответ', build()['spool_id'] == 'sp_a')
check('N6. blocked/attention кандидат selected не становится',
      all(x['status'] in ('ready', 'approval_required') for x in [p] if x['ams_slot'] is not None))

# ── Требования файла: блокировки ───────────────────────────────────────────────────────────────
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#161616")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, "PETG", "#161616")]}
_saved = dict(REQ)
REQ = dict(_saved, filament_count=2, filaments=[{"file_index": 0, "material": "PETG", "color_hex": "#161616"},
                                                {"file_index": 1, "material": "PLA", "color_hex": "#FFFFFF"}])
check('X1. multi-filament -> blocked/multi_filament_not_supported (пофиламентной карты нет)',
      build()['status'] == 'blocked' and build()['reason'] == 'multi_filament_not_supported')
REQ = dict(_saved, filament_count=0, filaments=[])
check('X2. число филаментов неизвестно -> blocked/filament_count_unknown', build()['reason'] == 'filament_count_unknown')
REQ = dict(_saved, filaments=[{"file_index": 0, "material": None, "color_hex": "#161616"}])
check('X3. материал файла неизвестен -> blocked/file_material_unknown', build()['reason'] == 'file_material_unknown')
REQ = dict(_saved, filaments=[{"file_index": 0, "material": "PETG", "color_hex": None}])
check('X4. цвет файла неизвестен -> blocked/file_color_unknown', build()['reason'] == 'file_color_unknown')
REQ = {"status": "error", "reason": "file_missing", "filament_count": 0, "filaments": []}
check('X5. файл пропал -> blocked/file_missing', build()['reason'] == 'file_missing')
REQ = {"status": "error", "reason": "file_hash_changed", "filament_count": 0, "filaments": []}
check('X6. хеш изменился -> blocked/file_hash_changed', build()['reason'] == 'file_hash_changed')
REQ = dict(_saved)

# ── O-Q. Согласие оператора ────────────────────────────────────────────────────────────────────
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#191919")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, "PETG", "#191919")]}
p = build()
check('O1. близкий цвет БЕЗ согласия -> effective_status остаётся approval_required',
      po.feed_plan_effective_status(p) == 'approval_required')
a = po.approve_feed_plan(p, approved_by='оператор', now=2000.0)
check('O2. согласие принято', a['status'] == 'ok' and a['idempotent'] is False)
ap = a['plan']
check('O3. КРИТИЧНО: после согласия effective_status = ready', po.feed_plan_effective_status(ap) == 'ready')
check('O4. ИСХОДНЫЕ факты не переписаны (почему было спорно — видно)',
      ap['status'] == 'approval_required' and ap['reason'] == 'close_color'
      and ap['color_relation'] == 'close' and ap['requires_approval'] is True)
check('O5. audit-метаданные сохранены',
      ap['approval']['approved_by'] == 'оператор' and ap['approval']['approved_at'] == 2000.0
      and ap['approval']['approved_reason'] == 'close_color')
a2 = po.approve_feed_plan(ap, approved_by='оператор', now=3000.0)
check('O6. повторное согласие идемпотентно (время не переписывается)',
      a2['idempotent'] is True and a2['plan']['approval']['approved_at'] == 2000.0)

for _fld, _val in (('spool_id', 'sp_ДРУГАЯ'), ('ams_slot', 7), ('file_hash', 'h2'),
                   ('printer_id', 'pr2'), ('inventory_color', '#00FF00'), ('inventory_material', 'PLA'),
                   ('required_material', 'PLA'), ('required_color', '#00FF00'), ('item_id', 'it_2')):
    _tampered = dict(ap)
    _tampered[_fld] = _val
    check('P1.%s согласие НЕдействительно после смены «%s»' % (_fld, _fld),
          po.feed_plan_effective_status(_tampered) == 'approval_required')
_restored = dict(ap)
check('P2. неизменённый план по-прежнему ready (отпечаток стабилен)', po.feed_plan_effective_status(_restored) == 'ready')

SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PLA", "#161616")]}
check('Q1. НЕЛЬЗЯ approve material_mismatch', po.approve_feed_plan(build())['reason'] == 'not_approvable')
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#FF0000")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, "PETG", "#FF0000")]}
check('Q2. НЕЛЬЗЯ approve цвет с ΔE00 > 5', po.approve_feed_plan(build())['reason'] == 'not_approvable')
SNAP = {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#161616")]}
REPORTED = {"telemetry_available": True, "telemetry_fresh": False, "positions": [rep_pos(0, False, "PETG", "#161616")]}
check('Q3. НЕЛЬЗЯ approve устаревшую телеметрию Bambu', po.approve_feed_plan(build())['reason'] == 'not_approvable')
REPORTED = {"telemetry_available": True, "telemetry_fresh": True, "positions": [rep_pos(0, False, None, None, present=False)]}
check('Q4. НЕЛЬЗЯ approve пустой слот', po.approve_feed_plan(build())['reason'] == 'not_approvable')
REQ = dict(_saved, filament_count=2, filaments=[{"file_index": 0, "material": "PETG", "color_hex": "#161616"},
                                                {"file_index": 1, "material": "PLA", "color_hex": "#FFF"}])
check('Q5. НЕЛЬЗЯ approve multi-filament', po.approve_feed_plan(build())['reason'] == 'not_approvable')
REQ = {"status": "error", "reason": "file_hash_changed", "filament_count": 0, "filaments": []}
check('Q6. НЕЛЬЗЯ approve изменившийся файл', po.approve_feed_plan(build())['reason'] == 'not_approvable')
REQ = dict(_saved)
check('Q7. ready approve не требует (и не является approvable)',
      (lambda: (globals().__setitem__('SNAP', {"has_ams": True, "slots": [inv_row(0, False, "sp_0", "PETG", "#161616")]}),
                globals().__setitem__('REPORTED', {"telemetry_available": True, "telemetry_fresh": True,
                                                   "positions": [rep_pos(0, False, "PETG", "#161616")]}),
                po.approve_feed_plan(build())['reason'])[2])() == 'not_approvable')
_forb = po._MOD_APPROVABLE if hasattr(po, '_MOD_APPROVABLE') else po.APPROVABLE_REASONS
# Alpha 2.751: к двум причинам добавлена manual_external (внешняя катушка FlashForge без склада).
# Перечень по-прежнему ЗАКРЫТЫЙ и назван явно — material_mismatch/ΔE>5/stale сюда не входят.
check('Q8. approvable причин РОВНО три и они названы явно',
      tuple(_forb) == ('close_color', 'inventory_declared', 'manual_external'))

# ── R. Запись в item ───────────────────────────────────────────────────────────────────────────
def snap_db():
    """Побайтовый снимок ВСЕХ таблиц: доказываем, что меняется только feed_plan_json + updated_at."""
    out = {}
    for t in [r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
        out[t] = [tuple(repr(v) for v in r) for r in c.execute("SELECT * FROM %s" % t).fetchall()]
    return out


p = build()
_before = snap_db()
_pre_row = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
r = po.persist_feed_plan('it_1', 'prun_1', p)
check('R1. запись принята', r['status'] == 'ok' and r['written'] is True)
_post_row = dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone())
_diff = {k for k in _pre_row if _pre_row[k] != _post_row[k]}
check('R2. КРИТИЧНО: изменились РОВНО feed_plan_json и updated_at, больше ничего',
      _diff == {'feed_plan_json', 'updated_at'})
_after = snap_db()
check('R3. КРИТИЧНО: чужие таблицы байт-в-байт прежние',
      all(_before[t] == _after[t] for t in _before if t != 'project_run_items'))
r2 = po.persist_feed_plan('it_1', 'prun_1', p)
check('R4. повторная запись ИДЕНТИЧНОГО плана идемпотентна (updated_at не дёргаем)',
      r2['status'] == 'ok' and r2['written'] is False and r2['idempotent'] is True
      and dict(c.execute("SELECT * FROM project_run_items WHERE id='it_1'").fetchone()) == _post_row)
check('R5. JSON canonical/sorted (тот же план -> та же строка)',
      po._feed_dump(p) == po._feed_dump(dict(p)) and po._feed_dump(p).index('"ams_slot"') < po._feed_dump(p).index('"status"'))
check('R6. чужой run записать нельзя', po.persist_feed_plan('it_1', 'prun_ЧУЖОЙ', p)['reason'] == 'item_not_in_run')
check('R7. несуществующий item -> item_not_found', po.persist_feed_plan('нет', 'prun_1', p)['reason'] == 'item_not_found')
for _st in ('sending', 'printing', 'waiting_plate_clear', 'leased', 'waiting_start_confirmation'):
    c.execute("UPDATE project_run_items SET state=? WHERE id='it_1'", (_st,))
    c.commit()
    _r = po.persist_feed_plan('it_1', 'prun_1', dict(p, reason='ПОПЫТКА ПЕРЕЗАПИСИ'))
    check('R8.%s КРИТИЧНО: активный item (%s) перезаписать НЕЛЬЗЯ' % (_st, _st),
          _r['status'] == 'error' and _r['reason'] == 'item_state_locked')
c.execute("UPDATE project_run_items SET state='pending' WHERE id='it_1'")
c.commit()

# ── S. Битый JSON не ломает API ────────────────────────────────────────────────────────────────
c.execute("UPDATE project_run_items SET feed_plan_json='{это не json' WHERE id='it_1'")
c.commit()
_fp = po.read_feed_plan('it_1')
check('S1. битый JSON -> attention_required/feed_plan_corrupt (а не «плана нет»)',
      _fp['status'] == 'attention_required' and _fp['reason'] == 'feed_plan_corrupt')
check('S2. get_run с битым планом НЕ падает', po.get_run('prun_1')['items'][0]['feed_plan']['reason'] == 'feed_plan_corrupt')
check('S3. сырое содержимое наружу не отдаётся', 'это не json' not in repr(_fp))
c.execute("UPDATE project_run_items SET feed_plan_json='[]' WHERE id='it_1'")
c.commit()
check('S4. чужой тип JSON (список) -> feed_plan_corrupt', po.read_feed_plan('it_1')['reason'] == 'feed_plan_corrupt')
c.execute("UPDATE project_run_items SET feed_plan_json='{}' WHERE id='it_1'")
c.commit()
check('S5. пустой план -> null (одна модель, пустого объекта не изобретаем)', po.read_feed_plan('it_1') is None)
check('S6. в public-снимке item поле feed_plan есть и равно null',
      po.get_run('prun_1')['items'][0]['feed_plan'] is None)

# ── U. Секретов/путей в JSON нет ───────────────────────────────────────────────────────────────
po.persist_feed_plan('it_1', 'prun_1', p)
_raw = c.execute("SELECT feed_plan_json FROM project_run_items WHERE id='it_1'").fetchone()[0]
check('U1. в сохранённом JSON нет токенов/паролей/ip/путей/nonce',
      not re.search(r'(?i)token|password|access|bblp|nonce|\d+\.\d+\.\d+\.\d+|[A-Za-z]:\\\\|/mnt/|ftp|mqtt', _raw))
check('U2. в JSON только поля модели (whitelist)',
      set(__import__('json').loads(_raw)) <= set(po._FEED_KEYS))
check('U3. байтов файла в JSON нет', len(_raw) < 4000 and 'PK' not in _raw)

# ── V. Рестарт читает тот же план ──────────────────────────────────────────────────────────────
_expect = po.read_feed_plan('it_1')
wire('boot_B')                      # ══ ПЕРЕЗАПУСК: другой boot_id, новый _ctx ══
po.recover_on_start()
check('V1. КРИТИЧНО: после рестарта читается ТОТ ЖЕ план (он в БД, а не в памяти)',
      po.read_feed_plan('it_1') == _expect)
check('V2. и он по-прежнему называет тот же слот/катушку',
      po.read_feed_plan('it_1')['ams_slot'] == p['ams_slot'] and po.read_feed_plan('it_1')['spool_id'] == p['spool_id'])

# ── Ни одного вызова печати ────────────────────────────────────────────────────────────────────
_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _MOD))
check('Z1. предохранитель по-прежнему выключен', po.DISPATCH_ENABLED is False)
check('Z2. /start по-прежнему отказывает',
      po.start_run('prun_1') == {"status": "error", "reason": "project_orchestrator_dispatch_disabled"})
# \b перед after_dispatch обязателен: иначе проверка ловит собственное ИМЯ СОСТОЯНИЯ
# «ambiguous_after_dispatch» и падает на пустом месте.
check('Z3. в модуле нет транспорта/печати/создания задания',
      not re.search(r'_send_mgr|paho|\bmqtt|ftplib|requests|socket|_do_project2_file_print'
                    r'|_send_file_to_printer|create_project_print_job|\bafter_dispatch\b|inv_ledger', _code))
check('Z4. builder не импортирует склад и не читает его БД',
      not re.search(r'import\s+.*inventory|farm_inventory|inv_spools', _code))
# Alpha 2.743 (5A2b): в модуле законно появился scheduler_tick (выключенный, без воркера), поэтому
# запрет слова «schedule» во ВСЁМ модуле устарел. Смысл проверки — про BUILDER: он обязан остаться
# чистым вычислением. Плюс отдельно фиксируем главное: фонового воркера/таймера нет НИГДЕ.
_feed_sec = _MOD[_MOD.index('# 6c. ПЛАН ПОДАЧИ'):_MOD.index('# 6d. АТОМАРНЫЙ LEASE')]
_feed_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _feed_sec))
check('Z5. в builder плана подачи нет scheduler/worker/timer',
      not re.search(r'Thread|Timer|asyncio|schedul', _feed_code))
check('Z5b. во ВСЁМ модуле нет фонового воркера/таймера/петли (тик — только по явному вызову)',
      not re.search(r'Thread|Timer|asyncio|while True', _code))
check('Z6. НИ ОДНОГО вызова печати за весь тест: BOOM=%r' % (BOOM,), BOOM == [])
_bs = _MOD[_MOD.index('def build_feed_plan'):_MOD.index('def feed_fingerprint')]
check('Z7. build_feed_plan — ЧИСТОЕ вычисление: не пишет в БД, не резервирует, не трогает clearance/hold',
      not re.search(r'UPDATE |INSERT |DELETE |BEGIN |commit\(|reserve\(|consume_clearance|set_hold', _bs))
_ps = _MOD[_MOD.index('def persist_feed_plan'):_MOD.index('def read_feed_plan')]
_ps_code = re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '', _ps))    # без докстринга: там слово UPDATE в тексте
check('Z8. persist_feed_plan пишет ТОЛЬКО в свою колонку и ничего не запускает',
      _ps_code.count('UPDATE project_run_items SET feed_plan_json=?') == 1
      and not re.search(r'reserve\(|consume_clearance|set_hold|clear_hold|_send', _ps_code)
      and len(re.findall(r'UPDATE |INSERT |DELETE ', _ps_code)) == 1)

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: источник подачи назначается только когда доказан — складская привязка обязательна '
              '(telemetry-only строка катушкой не считается), материал сверяется буквально без алиасов, '
              'цвет по CIEDE2000 (эталон Sharma 34/34), близкий цвет и «заявлено складом» требуют явного '
              'согласия и обесцениваются при смене отпечатка; external=-1 / AMS0 / multi-AMS5 / AMS HT512 '
              'сохраняют РЕАЛЬНЫЙ индекс, Auto/None не назначается никогда, multi-filament заблокирован; '
              'запись меняет только feed_plan_json+updated_at, битый JSON не роняет API, план переживает '
              'рестарт; печать не тронута'))
raise SystemExit(1 if fail else 0)
