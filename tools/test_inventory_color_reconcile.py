# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Инструмент сверки цвета + явная синхронизация — inventory 1.7.22. РЕАЛЬНЫЙ backend на ВРЕМЕННОЙ БД:
# register() -> реальная схема -> реальный inv_bind_spool -> реальный inv_ams_overview/material_check
# -> реальные inv_reconcile / inv_sync_spool_color. Телеметрия подаётся через тот же generic-контракт
# ядра (core.get_printer_reported_filament), что и в бою.
# Проверяет: близкий оттенок = совпадение (match/color_close), далёкий = color_mismatch, приоритет
# материала, slot_empty/unknown не изменились; сверка видит external -1 / AMS0 / мульти-AMS / AMS HT512;
# синхронизация пишет ТОЛЬКО color_hex филамента (в inv_ledger/историю катушки — НИЧЕГО), отказывается без
# свежей телеметрии/при чужом материале, идемпотентна, и честно сообщает, скольких катушек коснётся.
# Запуск: python tools/test_inventory_color_reconcile.py   (0 = пройдено)
import importlib.util, os, sys, tempfile, logging

logging.disable(logging.CRITICAL)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(tempfile.mkdtemp(), 'farm_inventory.db')
spec = importlib.util.spec_from_file_location('inv_backend', os.path.join(REPO, 'modules', 'inventory', 'backend.py'))
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)

PRINTERS = [{"id": "pr1", "name": "X1C-01", "type": "bambu", "ip": "1.1.1.1", "port": 8883, "order_idx": 0}]
STATES = {"pr1": {"ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color": "FF0000"},
                               {"index": 5, "unit": 1, "tray": 1, "type": "PLA", "color": "00FF00"},
                               {"index": 512, "unit": 128, "tray": 0, "type": "PLA", "color": "0000FF"}]}}
REPORTED = {}          # подменяем в тестах: то, что «сообщает принтер»
_n = [0]


class FakeCore:
    module_id = 'inventory'
    def add_route(self, *a, **k): return ''
    def add_hook(self, *a, **k): return True
    def resolve_db(self, name): return DB
    def new_id(self, prefix=''):
        _n[0] += 1
        return '%s%d' % (prefix, _n[0])
    def printers(self): return [dict(p) for p in PRINTERS]
    def printer_states(self): return STATES
    def add_printer_filament_provider(self, fn): return True
    def get_printer_reported_filament(self, pid): return REPORTED


inv.register(FakeCore())
c = inv.conn_inv
c.execute("INSERT INTO inv_vendors (id,name) VALUES ('v1','Bambu Lab')")
# f_red — ДВЕ катушки (проверяем побочный эффект: цвет принадлежит филаменту)
c.execute("INSERT INTO inv_filaments (id,vendor_id,material,color_name,color_hex) VALUES ('f_red','v1','PLA','Красный','FF0000')")
c.execute("INSERT INTO inv_filaments (id,vendor_id,material,color_name,color_hex) VALUES ('f_grn','v1','PLA','Зелёный','00FF00')")
c.execute("INSERT INTO inv_filaments (id,vendor_id,material,color_name,color_hex) VALUES ('f_blu','v1','PETG','Синий','0000FF')")
for sid, fid in [('s_ext', 'f_red'), ('s_ams0', 'f_red'), ('s_ams5', 'f_grn'), ('s_ht', 'f_blu'), ('s_spare', 'f_red')]:
    c.execute("INSERT INTO inv_spools (id,filament_id,label,weight_total_g,weight_remaining_g,status) "
              "VALUES (?,?,?,1000,500,'in_stock')", (sid, fid, sid))
c.commit()
inv.inv_bind_spool('s_ext', 'pr1', -1, external=True)
inv.inv_bind_spool('s_ams0', 'pr1', 0)
inv.inv_bind_spool('s_ams5', 'pr1', 5)
inv.inv_bind_spool('s_ht', 'pr1', 512)
# s_spare остаётся непривязанной катушкой того же филамента f_red

fail = 0
def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1

def telemetry(positions, available=True, fresh=True):
    global REPORTED
    REPORTED = {"telemetry_available": available, "telemetry_fresh": fresh, "positions": positions}

def rows():
    return {(r.get('spool') or {}).get('id'): r for r in inv.inv_reconcile('pr1').get('rows', [])}

def mc(sid):
    return (rows().get(sid) or {}).get('material_check') or {}

# ── сверка видит ВСЕ реальные позиции ──
telemetry([{"external": True, "present": True, "presence": "sensor",
            "reported_material": "PLA", "reported_color": "FF0000"},
           {"index": 0, "present": True, "reported_material": "PLA", "reported_color": "FF0000"},
           {"index": 5, "present": True, "reported_material": "PLA", "reported_color": "00FF00"},
           {"index": 512, "present": True, "reported_material": "PETG", "reported_color": "0000FF"}])
R = rows()
check('T1. сверка видит все привязанные катушки: external -1, AMS0, мульти-AMS5, AMS HT512',
      set(R.keys()) == {'s_ext', 's_ams0', 's_ams5', 's_ht'}
      and R['s_ext']['external'] is True and R['s_ht']['index'] == 512 and R['s_ht']['unit'] == 128)
check('T2. точное совпадение (подтверждено датчиком подачи) -> match/ok, distance=0, relation=exact',
      mc('s_ext')['status'] == 'match' and mc('s_ext')['reason'] == 'ok'
      and mc('s_ext')['color_distance'] == 0.0 and mc('s_ext')['color_relation'] == 'exact')
#  16.09.2026: та же позиция, но материал взят с ЭКРАНА принтера (внешняя катушка Bambu) — сверка
#  ничего не утверждает, и синхронизация цвета по ней запрещена: экран помнит снятую катушку.
telemetry([{"external": True, "present": True, "presence": "setting",
            "reported_material": "PLA", "reported_color": "FF0000"}])
_before = inv.conn_inv.execute("SELECT color_hex FROM inv_filaments WHERE id='f_red'").fetchone()['color_hex']
_r_set = inv.inv_sync_spool_color('s_ext')
check('T2b. настройка экрана вместо датчика -> unknown/printer_setting_only, синхронизация цвета отказана',
      mc('s_ext')['status'] == 'unknown' and mc('s_ext')['reason'] == 'printer_setting_only'
      and _r_set['ok'] is False
      and inv.conn_inv.execute("SELECT color_hex FROM inv_filaments WHERE id='f_red'").fetchone()['color_hex'] == _before)
telemetry([{"external": True, "present": True, "presence": "sensor",
            "reported_material": "PLA", "reported_color": "FF0000"},
           {"index": 0, "present": True, "reported_material": "PLA", "reported_color": "FF0000"},
           {"index": 5, "present": True, "reported_material": "PLA", "reported_color": "00FF00"},
           {"index": 512, "present": True, "reported_material": "PETG", "reported_color": "0000FF"}])

# ── близкий оттенок = СОВПАДЕНИЕ (главное изменение 1.7.22) ──
telemetry([{"index": 0, "present": True, "reported_material": "PLA", "reported_color": "FE0101"}])
check('T3. близкий оттенок (ΔE00 <= 5) -> match/color_close, relation=close, есть числовая distance',
      mc('s_ams0')['status'] == 'match' and mc('s_ams0')['reason'] == 'color_close'
      and mc('s_ams0')['color_relation'] == 'close' and 0 < mc('s_ams0')['color_distance'] <= 5.0)
telemetry([{"index": 0, "present": True, "reported_material": "PLA", "reported_color": "C12E1F"}])
check('T4. далёкий оттенок (ΔE00 > 5) -> color_mismatch/color, relation=far',
      mc('s_ams0')['status'] == 'color_mismatch' and mc('s_ams0')['reason'] == 'color'
      and mc('s_ams0')['color_relation'] == 'far' and mc('s_ams0')['color_distance'] > 5.0)

# ── приоритет материала и неизменённые статусы ──
telemetry([{"index": 0, "present": True, "reported_material": "PETG", "reported_color": "C12E1F"}])
check('T5. материал важнее цвета -> material_mismatch, цвет НЕ сравнивается (distance=None)',
      mc('s_ams0')['status'] == 'material_mismatch' and mc('s_ams0')['color_distance'] is None
      and mc('s_ams0')['color_relation'] is None)
telemetry([{"index": 0, "present": False, "reported_material": None, "reported_color": None}])
check('T6. пустой слот принтера -> slot_empty (не изменён), цвет не сравнивается',
      mc('s_ams0')['status'] == 'slot_empty' and mc('s_ams0')['color_distance'] is None)
telemetry([{"index": 0, "present": True, "reported_material": "PLA", "reported_color": "FF0000"}], fresh=False)
check('T7. несвежая телеметрия -> unknown/stale (не изменён), цвет не сравнивается',
      mc('s_ams0')['status'] == 'unknown' and mc('s_ams0')['reason'] == 'stale'
      and mc('s_ams0')['color_distance'] is None)
telemetry([{"index": 0, "present": True, "reported_material": "PLA", "reported_color": "не-hex"}])
check('T8. невалидный HEX от принтера -> цвет не сравнивается, ложного mismatch нет (match)',
      mc('s_ams0')['status'] == 'match' and mc('s_ams0')['color_distance'] is None)

# ── синхронизация цвета ──
check('T9. цвет принадлежит филаменту: f_red -> 3 катушки (2 привязаны + 1 на складе)',
      inv._inv_filament_spool_count('f_red') == 3
      and rows()['s_ams0']['filament_spool_count'] == 3)
telemetry([{"index": 0, "present": True, "reported_material": "PLA", "reported_color": "C12E1F"}], fresh=False)
r = inv.inv_sync_spool_color('s_ams0')
check('T10. синхронизация ОТКАЗАНА при несвежей телеметрии (ничего не записано)',
      r['ok'] is False and inv.conn_inv.execute("SELECT color_hex FROM inv_filaments WHERE id='f_red'").fetchone()['color_hex'] == 'FF0000')
telemetry([{"index": 0, "present": True, "reported_material": "PETG", "reported_color": "C12E1F"}])
r = inv.inv_sync_spool_color('s_ams0')
check('T11. синхронизация ОТКАЗАНА при несовпадении материала (чужой цвет не пишем)',
      r['ok'] is False and r['reason'] == 'material_mismatch'
      and inv.conn_inv.execute("SELECT color_hex FROM inv_filaments WHERE id='f_red'").fetchone()['color_hex'] == 'FF0000')
telemetry([{"index": 0, "present": True, "reported_material": "PLA", "reported_color": "C12E1F"}])
r = inv.inv_sync_spool_color('s_ams0')
check('T12. синхронизация выполнена: цвет филамента <- цвет принтера, честно назван охват (3 катушки)',
      r['ok'] is True and r['from'] == '#FF0000' and r['to'] == '#C12E1F' and r['affected_spools'] == 3
      and inv.conn_inv.execute("SELECT color_hex FROM inv_filaments WHERE id='f_red'").fetchone()['color_hex'] == '#C12E1F')
check('T13. после синхронизации сверка показывает точное совпадение',
      mc('s_ams0')['status'] == 'match' and mc('s_ams0')['color_relation'] == 'exact')
check('T14. синхронизация идемпотентна (повтор -> ok/unchanged, лишней записи нет)',
      (lambda x: x['ok'] is True and x.get('unchanged') is True)(inv.inv_sync_spool_color('s_ams0')))
check('T15. затронут ТОЛЬКО цвет: материал/вес/привязка/цена катушки не изменились',
      (lambda s, f: s['weight_remaining_g'] == 500 and s['ams_printer_id'] == 'pr1' and s['ams_slot'] == 0
       and f['material'] == 'PLA' and f['color_name'] == 'Красный')(
          inv.conn_inv.execute("SELECT * FROM inv_spools WHERE id='s_ams0'").fetchone(),
          inv.conn_inv.execute("SELECT * FROM inv_filaments WHERE id='f_red'").fetchone()))
check('T16. соседние филаменты не тронуты (f_grn остался зелёным)',
      inv.conn_inv.execute("SELECT color_hex FROM inv_filaments WHERE id='f_grn'").fetchone()['color_hex'] == '00FF00')
check('T17. в inv_ledger НЕТ записи о правке цвета: это не приход и не расход, историю катушки '
      'и отчёт стоимости она бы исказила (побайтовая проверка — tools/test_inventory_color_sync_safety.py)',
      inv.conn_inv.execute("SELECT COUNT(*) AS n FROM inv_ledger").fetchone()['n'] == 0)
r = inv.inv_sync_spool_color('s_spare')
check('T18. непривязанная катушка -> синхронизация отказана (not_bound)', r['ok'] is False and r['reason'] == 'not_bound')
r = inv.inv_sync_spool_color('нет-такой')
check('T19. несуществующая катушка -> not_found, без падения', r['ok'] is False and r['reason'] == 'not_found')
check('T20. принтера нет / нет привязок -> пустые rows, без падения',
      inv.inv_reconcile('нет-такого')['rows'] == [])

#  13.10.2026: цвет сохраняется только кодом цвета (разметка в поле не попадёт в окно), вид записи прежний
def _hex_after(v):
    inv.inv_update_filament('f_red', {"color_hex": v})
    return inv.conn_inv.execute("SELECT color_hex FROM inv_filaments WHERE id='f_red'").fetchone()['color_hex']
_h = [_hex_after(v) for v in ('#c12e1f', 'C12E1F', '#abc', '"><img src=x onerror=alert(1)>', '#ZZZZZZ')]
print('   цвета:', _h)
check('T21. цвет: «#c12e1f» → «#C12E1F», «C12E1F» без изменений, «#abc» → «#AABBCC», разметка и мусор → пусто',
      _h == ['#C12E1F', 'C12E1F', '#AABBCC', '', ''])

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: сверка видит все реальные позиции (external -1 / AMS0 / мульти-AMS / AMS HT512); близкий '
              'оттенок = совпадение, далёкий = отличие; материал важнее цвета; slot_empty/unknown не изменены; '
              'синхронизация пишет только цвет филамента, отказывается без свежей телеметрии и при чужом '
              'материале, идемпотентна и честно называет охват'))
sys.exit(1 if fail else 0)
