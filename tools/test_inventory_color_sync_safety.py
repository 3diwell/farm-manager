# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# DATA-SAFETY синхронизации цвета — inventory 1.7.22.
# Доказывает, что «взять цвет с принтера» меняет РОВНО ОДНО поле каталога и НИЧЕГО больше.
# Исправление неточного HEX — это НЕ движение материала: строка в inv_ledger исказила бы историю
# физической катушки (её читает api_inv_spool_ledger по ref_type='spool'), отчёт стоимости
# (inv_ledger LEFT JOIN inv_spools/inv_filaments) и прогноз расхода. Поэтому в ledger не пишем ничего.
#
# Метод: снимаем ПОБАЙТОВЫЙ снимок каждой строки каждой таблицы БД (repr всех колонок) ДО и ПОСЛЕ sync
# и требуем, чтобы дифф состоял РОВНО из одного изменения: inv_filaments.color_hex (+ служебный
# updated_at той же строки). Любая новая/изменённая/удалённая строка где угодно — провал.
# Запуск: python tools/test_inventory_color_sync_safety.py   (0 = пройдено)
import importlib.util, os, sys, tempfile, logging

logging.disable(logging.CRITICAL)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(tempfile.mkdtemp(), 'farm_inventory.db')
spec = importlib.util.spec_from_file_location('inv_backend', os.path.join(REPO, 'modules', 'inventory', 'backend.py'))
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)

PRINTERS = [{"id": "pr1", "name": "X1C-01", "type": "bambu", "ip": "1", "port": 1, "order_idx": 0}]
STATES = {"pr1": {"ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color": "FF0000"}]}}
REPORTED = {}
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
c.execute("INSERT INTO inv_vendors (id,name) VALUES ('v','Bambu Lab')")
c.execute("INSERT INTO inv_filaments (id,vendor_id,material,color_name,color_hex,price_per_kg,spool_weight_g) "
          "VALUES ('f1','v','PLA','Красный','FF0000',1500,250)")
# s0 привязана к AMS0; s_spare — та же позиция каталога, лежит на складе (правка цвета видна и у неё)
for sid in ('s0', 's_spare'):
    c.execute("INSERT INTO inv_spools (id,filament_id,label,weight_total_g,weight_remaining_g,price,lot,"
              "purchased_at,opened_at,status,nfc_uid,notes) VALUES (?,?,?,1000,418.5,1200,'LOT-7','2026-01-05',"
              "'2026-02-01','in_stock','NFC-1','заметка')", (sid, 'f1', sid))
# реальная история движения материала у катушки — она обязана остаться нетронутой
c.execute("INSERT INTO inv_ledger (id,kind,ref_type,ref_id,qty,reason) VALUES ('led_seed_in','in','spool','s0',1000,'приход')")
c.execute("INSERT INTO inv_ledger (id,kind,ref_type,ref_id,qty,reason) VALUES ('led_seed_out','out','spool','s0',-581.5,'печать (авто)')")
# незавершённая печать (pending) — тоже не должна пострадать
c.execute("INSERT INTO inv_pending_prints (id,printer_id,fname,started_ts,deductions,status) "
          "VALUES ('pp1','pr1','job.3mf',1000,'[]','active')")
c.commit()
inv.inv_bind_spool('s0', 'pr1', 0)

TABLES = ['inv_vendors', 'inv_filaments', 'inv_spools', 'inv_items', 'inv_locations',
          'inv_ledger', 'inv_pending_prints', 'inv_settings']


def snapshot():
    """Побайтовый снимок ВСЕЙ БД модуля: таблица -> [repr всех колонок каждой строки], порядок по rowid."""
    snap = {}
    with inv.lock_inv:
        for t in TABLES:
            rows = inv.conn_inv.execute("SELECT * FROM %s ORDER BY rowid" % t).fetchall()
            snap[t] = [repr(tuple(r)) for r in rows]
    return snap


def diff(a, b):
    out = []
    for t in TABLES:
        if a[t] != b[t]:
            out.append((t, a[t], b[t]))
    return out


fail = 0
def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [{"index": 0, "present": True, "reported_material": "PLA", "reported_color": "C12E1F"}]}

before = snapshot()
spool_before = dict(inv.conn_inv.execute("SELECT * FROM inv_spools WHERE id='s0'").fetchone())
fil_before = dict(inv.conn_inv.execute("SELECT * FROM inv_filaments WHERE id='f1'").fetchone())
res = inv.inv_sync_spool_color('s0')
after = snapshot()
spool_after = dict(inv.conn_inv.execute("SELECT * FROM inv_spools WHERE id='s0'").fetchone())
fil_after = dict(inv.conn_inv.execute("SELECT * FROM inv_filaments WHERE id='f1'").fetchone())

check('S1. синхронизация выполнена (цвет каталога взят с принтера)',
      res.get('ok') is True and res.get('from') == '#FF0000' and res.get('to') == '#C12E1F')

d = diff(before, after)
check('S2. во ВСЕЙ БД изменилась РОВНО ОДНА таблица — inv_filaments',
      [t for t, _, _ in d] == ['inv_filaments'])
check('S3. inv_ledger байт-в-байт прежний: ни прихода, ни расхода, ни «adjust» — движения материала нет',
      before['inv_ledger'] == after['inv_ledger'] and len(after['inv_ledger']) == 2)
check('S4. история КАТУШКИ (api_inv_spool_ledger, ref_type=spool) не получила новых строк',
      inv.conn_inv.execute("SELECT COUNT(*) AS n FROM inv_ledger WHERE ref_type='spool' AND ref_id='s0'").fetchone()['n'] == 2)
check('S5. inv_spools байт-в-байт прежние (обе катушки филамента)',
      before['inv_spools'] == after['inv_spools'])
check('S6. вес катушки не тронут (weight_remaining_g / weight_total_g)',
      spool_before['weight_remaining_g'] == spool_after['weight_remaining_g'] == 418.5
      and spool_before['weight_total_g'] == spool_after['weight_total_g'] == 1000)
check('S7. привязка/статус/цена/лот/nfc/updated_at катушки не тронуты (ВСЕ поля spool идентичны)',
      spool_before == spool_after)
check('S8. незавершённая печать (inv_pending_prints) не тронута', before['inv_pending_prints'] == after['inv_pending_prints'])
check('S9. остальные таблицы (vendors/items/locations/settings) не тронуты',
      all(before[t] == after[t] for t in ('inv_vendors', 'inv_items', 'inv_locations', 'inv_settings')))

changed = [k for k in fil_before if fil_before[k] != fil_after[k]]
check('S10. в inv_filaments изменился ТОЛЬКО color_hex (+ служебный updated_at), больше ничего',
      set(changed) <= {'color_hex', 'updated_at'} and 'color_hex' in changed
      and fil_after['color_hex'] == '#C12E1F')
check('S11. материал/цена/плотность/вес катушки/имя цвета филамента не тронуты',
      fil_before['material'] == fil_after['material'] and fil_before['price_per_kg'] == fil_after['price_per_kg']
      and fil_before['density'] == fil_after['density'] and fil_before['spool_weight_g'] == fil_after['spool_weight_g']
      and fil_before['color_name'] == fil_after['color_name'])
check('S12. число строк не выросло НИ В ОДНОЙ таблице (audit/ledger-записи не создавались)',
      all(len(before[t]) == len(after[t]) for t in TABLES))
check('S13. в исходниках модуля нет записи в inv_ledger из пути синхронизации цвета',
      'INSERT INTO inv_ledger' not in
      open(os.path.join(REPO, 'modules', 'inventory', 'backend.py'), encoding='utf-8').read()
      .split('def inv_sync_spool_color')[1].split('\ndef ')[0])

# идемпотентный повтор тоже ничего не пишет
again = snapshot()
inv.inv_sync_spool_color('s0')
check('S14. повторная синхронизация (цвет уже совпал) не пишет в БД вообще', again == snapshot())
# отказ при чужом материале — тоже без записей
REPORTED = {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [{"index": 0, "present": True, "reported_material": "PETG", "reported_color": "00FF00"}]}
before2 = snapshot()
r2 = inv.inv_sync_spool_color('s0')
check('S15. отказ (чужой материал) не оставляет следов в БД', r2.get('ok') is False and before2 == snapshot())

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: синхронизация цвета меняет РОВНО inv_filaments.color_hex; inv_ledger, история катушки, '
              'inv_spools (вес/цена/привязка/статус/pending) и все прочие таблицы остаются байт-в-байт прежними; '
              'записей движения материала и audit-строк в БД не создаётся (событие только в лог приложения)'))
sys.exit(1 if fail else 0)
