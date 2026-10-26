# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Модуль «Расчёт заказа» (id cost, 0.2.0) — выпуск 3.0, 12.09.2026.

ЗАЧЕМ. Владелец удалил модуль «Себестоимость печати» и поставил на его место «Расчёт заказа»
(исходники владельца). Модуль сохранил id `cost`, имена, пути и методы маршрутов, но ведёт себя
иначе: хранит заказы и копии их файлов, разбирает файлы печати, берёт задачи и проекты у самой
программы и создаёт по заказу проект. Прежний набор проверял удалённый модуль и заменён этим.

ЧТО ДОКАЗЫВАЕТСЯ (исполнением, во временной папке; рабочая DATA_DIR не открывается, сети нет —
обращения модуля к программе подменены заглушкой, которая записывает каждый запрос):
  A. манифест, сборка zip и карта прав ядра согласованы;
  B. загрузка: таблицы созданы, прежняя база farm_cost.db один раз сохранена копией, старые
     таблицы «Себестоимости» не тронуты, к печати модуль не подключается;
  C. настройки нормализуются, мусор не записывается;
  D. расчёт: каждое слагаемое сверено с независимой арифметикой;
  E. разбор файла печати: G-code и 3MF, отказ на пустом, чужом формате и опасном архиве;
  F. заказы: номера по порядку, повтор номера отклоняется, список, чтение, сводка;
  G. файлы заказа хранятся в папке модуля, удаление заказа убирает ТОЛЬКО свои копии; после
     переноса папки данных (0.2.2) файлы находятся на новом месте без переписывания базы;
  H. импорт задачи из программы, сохранение с копией файла, создание проекта: запросы уходят
     только на 127.0.0.1 и только с заголовками сеанса; подменённый Host их не уводит;
  I. эффекты маршрутов в карте прав равны факту графа вызовов; расчёт, открытый роли
     «только просмотр», пишет только кэш моделей принтеров;
  J. резервная копия: провайдер ядра читает базу нового модуля без ошибок.

Запуск: python tools/test_cost_module.py   (0 = все проверки пройдены)
"""
import ast
import asyncio
import glob
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-консоль cp1252
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)            # разбор файла модуль пробует начать с парсеров ядра (fail-open)
SENTINEL = "COST_ORDER_MODULE_SENTINEL_3_0"
MOD_DIR = os.path.join(REPO, "modules", "cost")
BACKEND = os.path.join(MOD_DIR, "backend.py")

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:400]) if detail else ""))


def section(t):
    print("\n--- %s ---" % t)


def rd(path):
    return io.open(path, encoding="utf-8").read()


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def money(a, b):
    return abs(float(a) - float(b)) <= 0.011


TMP = tempfile.mkdtemp(prefix="fm_cost_order_test_")
TMP2 = tempfile.mkdtemp(prefix="fm_cost_order_fresh_")
YEAR = datetime.now().year

# ════════════════════════════════════════════════════════════════════════════
section("A. манифест, сборка и карта прав")

MJ = json.load(open(os.path.join(MOD_DIR, "module.json"), encoding="utf-8"))
SRC = rd(BACKEND)
PANEL = rd(os.path.join(MOD_DIR, "web", "CostPanel.js"))
#  13.10.2026: номер выпуска сверяется с каталогом программы (app/module_catalog.py), а не с числом в
#  тексте проверки — иначе каждый подъём номера красил набор без дефекта.
_CAT = __import__("app.module_catalog", fromlist=["KNOWN_MODULE_RELEASES"]).KNOWN_MODULE_RELEASES
check("A1. манифест: id cost, «Расчёт заказа», выпуск как в каталоге программы при контракте с ядром 0.2.0, окно модуля на месте",
      MJ.get("id") == "cost" and MJ.get("ru") == "Расчёт заказа" and MJ.get("version") == _CAT.get("cost")
      and MJ.get("core_contract") == "0.2.0"
      and MJ.get("entry") == "web/CostPanel.js" and os.path.isfile(os.path.join(MOD_DIR, "web", "CostPanel.js")), MJ)
check("A2. старый модуль ушёл: к печати модуль не подключается (у «Себестоимости» были хуки печати)",
      "add_hook" not in SRC and "print_run_started" not in SRC and "print_run_finished" not in SRC)

from app import route_policy_registry as reg   # noqa: E402

COSTP = [p for p in reg.ALL_POLICIES if getattr(p, "module_id", None) == "cost"]
BY_ID = {p.policy_id: p for p in COSTP}
#  23.09.2026: с картой прав сверяется КОНТРАКТ модуля (core_contract), а не номер выпуска.
check("A3. в карте прав ровно 10 маршрутов модуля, у всех — контракт из манифеста",
      len(COSTP) == 10 and all(p.module_version == MJ.get("core_contract", MJ["version"]) for p in COSTP),
      sorted({p.module_version for p in COSTP}))

_bspec = importlib.util.spec_from_file_location("fm_build_cost_zip_test", os.path.join(REPO, "tools", "build_cost_zip.py"))
_bmod = importlib.util.module_from_spec(_bspec)
_bspec.loader.exec_module(_bmod)
_bmod.OUT = os.path.join(TMP2, "order.zip")                    # сборка — во временную папку, не в modules/
_buf = io.StringIO()
_old_stdout, sys.stdout = sys.stdout, _buf
try:
    _bmod.main()
    _built = True
except BaseException as _e:   # noqa: BLE001 — SystemExit/AssertionError сборщика — это провал проверки
    _built = repr(_e)
finally:
    sys.stdout = _old_stdout
_names = zipfile.ZipFile(_bmod.OUT).namelist() if _built is True else []
_want = ["cost/module.json", "cost/backend.py", "cost/order_calculator.py", "cost/order_parser.py", "cost/web/CostPanel.js"]
check("A4. сборщик кладёт в архив бэкенд, оба его соседних файла, окно и манифест — и ничего больше",
      _built is True and sorted(_names) == sorted(_want), (_built, _names))
check("A5. содержимое архива побайтно равно исходникам",
      _built is True and all(zipfile.ZipFile(_bmod.OUT).read(n) == open(os.path.join(MOD_DIR, *n.split("/")[1:]), "rb").read()
                             for n in _want))
check("A6. архив называется по имени модуля, а не «cost» (владелец ищет модуль по названию)",
      os.path.basename(rd(os.path.join(REPO, "tools", "build_cost_zip.py")) and _bmod.OUT) == "order.zip"
      and '"3diwell-module-order-calculation.zip"' in rd(os.path.join(REPO, "tools", "build_cost_zip.py"))
      and "3diwell-module-order-calculation.zip" in rd(os.path.join(REPO, "tools", "build_release.py"))
      and "3diwell-module-cost.zip" not in rd(os.path.join(REPO, "tools", "build_release.py")))

# ════════════════════════════════════════════════════════════════════════════
section("B. загрузка модуля во временной папке")

#  Прежняя база «Себестоимости»: её таблицы (схема резервной копии v1, заморожена) и немного
#  данных. Новый модуль обязан их не тронуть. R-125: провайдер копии с backup v2 описывает таблицы
#  «Расчёта заказа», поэтому прежние столбцы перечислены здесь явно, а не берутся из провайдера.
from app.config_backup import module_providers as MP   # noqa: E402

_LEGACY_COST_V1 = {
    "cost_printer_settings": ("printer_id", "settings_json", "updated_at"),
    "cost_calculations": ("calc_id", "run_id", "parent_calc_id", "revision", "printer_id", "printer_name",
                          "printer_model", "mode", "basis", "source", "outcome", "label", "currency",
                          "quantity", "duration_s", "material_cost", "depreciation_cost",
                          "electricity_cost", "operator_cost", "extra_cost", "total_run",
                          "total_per_part", "formula_version", "breakdown_json", "schema_version",
                          "created_at"),
}
_old = sqlite3.connect(os.path.join(TMP, "farm_cost.db"))
_old.execute("CREATE TABLE cost_config (key TEXT PRIMARY KEY, value TEXT)")
_old.execute("INSERT INTO cost_config VALUES ('tariff', '5.5')")
for _name, _cols in _LEGACY_COST_V1.items():
    _old.execute('CREATE TABLE "%s" (%s)' % (_name, ", ".join('"%s"' % c for c in _cols)))
_old.execute("INSERT INTO cost_calculations (calc_id, total_run) VALUES ('c1', 13.0)")
_old.commit()
_old.close()

PRINTERS = [{"id": "p1", "name": "X1", "type": "bambu", "model": "Bambu Lab X1 Carbon"},
            {"id": "p2", "name": "K2", "type": "klipper", "model": "Creality K2 Plus"}]


class FakeCore(object):
    """Имитация ModuleCore: своя БД во временной папке, учёт маршрутов и хуков, список принтеров."""

    def __init__(self, root):
        self.root = root
        self.routes = []
        self.hooks = []
        self.module_id = "cost"
        self.module_version = MJ["version"]

    def resolve_db(self, name):
        return os.path.join(self.root, name)

    def add_route(self, rel, handler, methods, policy_id=None):
        self.routes.append({"rel": rel, "handler": handler, "methods": list(methods), "policy_id": policy_id})

    def add_hook(self, name, fn):
        self.hooks.append(name)

    def printers(self):
        return [dict(p) for p in PRINTERS]


def load_backend(tag):
    spec = importlib.util.spec_from_file_location("fm_module_cost_" + tag, BACKEND)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cb = load_backend("a")
core = FakeCore(TMP)
cb.register(core)

_decl = {(r["rel"], r["methods"][0], r["handler"].__name__, r["policy_id"]) for r in core.routes}
_reg = {(p.module_route, p.method, p.handler, p.policy_id) for p in COSTP}
check("B1. маршруты, объявленные модулем, совпадают с картой прав ядра (путь, метод, обработчик, право)",
      len(core.routes) == 10 and _decl == _reg, sorted(_decl ^ _reg))
_c = sqlite3.connect(os.path.join(TMP, "farm_cost.db"))
_tables = {r[0] for r in _c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
_ddl = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", " ".join(cb.DDL)))
check("B2. все таблицы модуля созданы: %s" % ", ".join(sorted(_ddl)), _ddl and _ddl <= _tables, _ddl - _tables)
check("B3. таблицы прежней «Себестоимости» и их данные не тронуты",
      _c.execute("SELECT value FROM cost_config WHERE key='tariff'").fetchone() == ("5.5",)
      and _c.execute("SELECT COUNT(*) FROM cost_calculations").fetchone() == (1,))
_c.close()
_copies = glob.glob(os.path.join(TMP, "farm_cost_before_order_module_*.db"))
check("B4. перед первой загрузкой прежняя база сохранена копией (с её данными)",
      len(_copies) == 1 and sqlite3.connect(_copies[0]).execute("SELECT value FROM cost_config").fetchone() == ("5.5",),
      _copies)
cb_again = load_backend("b")
cb_again.register(FakeCore(TMP))
check("B5. повторная загрузка копию не повторяет",
      len(glob.glob(os.path.join(TMP, "farm_cost_before_order_module_*.db"))) == 1)
try:
    cb_again.conn_c.close()
except Exception:
    pass
check("B6. к хукам печати модуль не подписан: печать от него не зависит", core.hooks == [])
check("B7. файлы заказов живут в папке данных модуля", os.path.isdir(cb.FILES_DIR)
      and os.path.dirname(cb.FILES_DIR) == TMP and os.path.basename(cb.FILES_DIR) == "cost_order_files")

# ════════════════════════════════════════════════════════════════════════════
section("C. настройки")

_g = cb.api_settings_get()
check("C1. умолчания: рубли, шаг округления 1, номер заказа «год-порядковый»",
      _g["global"]["currency"] == "RUB" and _g["global"]["currency_symbol"] == "₽"
      and _g["global"]["rounding_step"] == 1.0 and _g["global"]["order_number_template"] == "{year}-{seq:04d}"
      and _g["formula_version"] == "order_quote_v1", _g.get("global"))
_s = cb._set_settings({"currency": "USD", "tax_mode": "bogus", "rounding_step": 0, "order_number_template": "no-placeholders",
                       "electricity_price_per_kwh": "7.5", "unknown_key": "x"})
check("C2. мусор нормализуется: символ валюты по коду, режим налога, шаг округления, шаблон номера; чужие ключи отброшены",
      _s["currency_symbol"] == "$" and _s["tax_mode"] == "on_top" and _s["rounding_step"] == 1.0
      and _s["order_number_template"] == "{year}-{seq:04d}" and _s["electricity_price_per_kwh"] == 7.5
      and "unknown_key" not in _s, _s)
check("C3. настройки записаны в базу модуля", cb._get_settings()["currency"] == "USD")
cb._set_settings({"currency": "RUB", "electricity_price_per_kwh": 8, "operator_hourly_rate": 600,
                  "engineer_hourly_rate": 1200, "default_markup_percent": 50, "default_waste_percent": 5,
                  "tax_percent": 20, "tax_mode": "on_top", "rounding_step": 10, "default_packaging_cost": 100,
                  "default_consumables_cost": 30, "minimum_order_price": 0, "default_post_processing_cost": 0})

# ════════════════════════════════════════════════════════════════════════════
section("D. расчёт заказа")

SETTINGS = {"electricity_price_per_kwh": 8.0, "operator_hourly_rate": 600.0, "engineer_hourly_rate": 1200.0,
            "default_post_processing_cost": 0.0, "default_packaging_cost": 100.0, "default_consumables_cost": 30.0,
            "default_markup_percent": 50.0, "default_waste_percent": 5.0, "minimum_order_price": 0.0,
            "tax_percent": 20.0, "tax_mode": "on_top", "rounding_step": 10.0, "currency": "RUB", "currency_symbol": "₽"}
RATES = {"p1": {"power_w": 300, "amortization_per_hour": 20, "service_per_hour": 5}}
ITEM1 = {"name": "Кронштейн", "printer_id": "p1", "duration_s": 7200,
         "parts": [{"name": "A", "required_qty": 10, "on_plate_qty": 4}],
         "materials": [{"material_name": "PETG", "weight_g": 50, "price_per_kg": 1500}],
         "operator_minutes": 30, "engineer_minutes": 15, "post_processing_cost": 5, "post_processing_mode": "per_item"}
ITEM2 = {"name": "Заглушка", "duration_s": 3600, "required_qty": 2, "on_plate_qty": 1,
         "weight_g": 20, "material_price_per_kg": 2000, "post_processing_cost": 15, "post_processing_mode": "fixed"}

#  Независимая арифметика (не функции модуля).
_runs1 = math.ceil(10 / 4)
_h1 = 7200 * _runs1 / 3600.0
_i1 = {"material": 50 / 1000.0 * 1500 * _runs1, "electricity": _h1 * 300 / 1000.0 * 8, "amortization": _h1 * 20,
       "service": _h1 * 5, "operator": 30 / 60.0 * 600, "engineer": 15 / 60.0 * 1200, "post": 5 * 10}
_h2 = 3600 * 2 / 3600.0
_i2 = {"material": 20 / 1000.0 * 2000 * 2, "electricity": 0.0, "amortization": 0.0, "service": 0.0,
       "operator": 0.0, "engineer": 0.0, "post": 15.0}
_base = sum(_i1.values()) + sum(_i2.values()) + 100 + 30
_full = _base * 1.05
_before_tax = _full * 1.5
_step = 10.0
_customer = math.floor(_before_tax * 1.2 / _step + 0.5) * _step
_tax = _customer * 20 / 120.0
_profit = _customer - _full - _tax

R = cb.calculate_order({"items": [ITEM1, ITEM2]}, SETTINGS, RATES)
check("D1. первая позиция: 3 запуска, материал, свет, амортизация, обслуживание, работа, постобработка — как по формуле",
      R["items"][0]["runs"] == 3 and money(R["items"][0]["material_cost"], _i1["material"])
      and money(R["items"][0]["electricity_cost"], _i1["electricity"]) and money(R["items"][0]["amortization_cost"], _i1["amortization"])
      and money(R["items"][0]["service_cost"], _i1["service"]) and money(R["items"][0]["operator_cost"], _i1["operator"])
      and money(R["items"][0]["engineer_cost"], _i1["engineer"]) and money(R["items"][0]["post_processing_cost"], _i1["post"]),
      R["items"][0])
check("D2. вторая позиция: старые поля веса и цены понимаются, принтер без ставок даёт ноль за время",
      R["items"][1]["runs"] == 2 and money(R["items"][1]["material_cost"], _i2["material"])
      and money(R["items"][1]["electricity_cost"], 0) and money(R["items"][1]["cost"], sum(_i2.values())), R["items"][1])
check("D3. итог: основа, отходы 5 %%, наценка 50 %%, налог сверху 20 %%, округление до 10: %.2f"
      % _customer,
      money(R["base_cost"], _base) and money(R["full_cost"], _full) and money(R["price_before_tax"], _before_tax)
      and money(R["customer_price"], _customer) and money(R["tax_amount"], _tax) and money(R["profit"], _profit)
      and R["total_runs"] == 5 and R["total_required_qty"] == 12 and R["total_duration_s"] == 7200 * 3 + 3600 * 2,
      {k: R[k] for k in ("base_cost", "full_cost", "price_before_tax", "customer_price", "tax_amount", "profit")})
_rmin = cb.calculate_order({"items": [ITEM1, ITEM2], "minimum_order_price": 5000}, SETTINGS, RATES)
check("D4. минимальная цена заказа применяется и отмечается", _rmin["minimum_applied"] is True
      and money(_rmin["price_before_tax"], 5000) and money(_rmin["customer_price"], 6000), _rmin["customer_price"])
_rinc = cb.calculate_order({"items": [ITEM1, ITEM2], "tax_mode": "included"}, SETTINGS, RATES)
_cinc = math.floor(_before_tax / _step + 0.5) * _step
check("D5. налог «включён в цену»: цена не растёт, налог выделяется из неё",
      _rinc["tax_mode"] == "included" and money(_rinc["customer_price"], _cinc)
      and money(_rinc["tax_amount"], _cinc * 20 / 120.0), (_rinc["customer_price"], _rinc["tax_amount"]))
_rman = cb.calculate_order({"items": [ITEM1, ITEM2], "manual_price": 2500}, SETTINGS, RATES)
check("D6. цена менеджера становится ценой для клиента, расчётная остаётся видна",
      money(_rman["customer_price"], 2500) and money(_rman["manual_price"], 2500) and money(_rman["calculated_price"], _customer))
_rbad = cb.calculate_order({"items": [{"duration_s": -5, "required_qty": "abc", "weight_g": -10, "material_price_per_kg": "x"}]},
                           SETTINGS, RATES)
check("D7. отрицательные и нечисловые значения не дают отрицательной цены",
      _rbad["items"][0]["required_qty"] == 1 and money(_rbad["items"][0]["material_cost"], 0)
      and _rbad["customer_price"] >= 0, _rbad["items"][0])

# ════════════════════════════════════════════════════════════════════════════
section("E. разбор файла печати")

SRCDIR = os.path.join(TMP, "src")
os.makedirs(SRCDIR)
GCODE = ("; HEADER_BLOCK_START\n; generated by OrcaSlicer 2.3.0 on 2026-09-12 at 10:00:00\n"
         "; model printing time: 1h 2m 3s; total estimated time: 1h 5m 0s\n; HEADER_BLOCK_END\n"
         "G28\nG1 X10 Y10 E1\nG1 X20 Y20 E2\n"
         "; filament used [g] = 12.50, 3.25\n; filament_type = PETG;PLA\n; filament_colour = #FF0000;#00FF00\n"
         "; printer_model = Bambu Lab X1 Carbon\n; nozzle_diameter = 0.4\n; layer_height = 0.2\n")
G_PATH = os.path.join(SRCDIR, "bracket.gcode")
io.open(G_PATH, "w", encoding="utf-8", newline="\n").write(GCODE)
A = cb.analyze_print_file(G_PATH, "bracket.gcode")
check("E1. G-code: слайсер, время, два материала с цветами и весами, общий вес, отпечаток файла",
      A["slicer"] == "OrcaSlicer" and A["estimated_s"] == 3900 and len(A["materials"]) == 2
      and A["materials"][0]["material"] == "PETG" and A["materials"][1]["color"] == "#00FF00"
      and money(A["materials"][0]["weight_g"], 12.5) and money(A["weight_g"], 15.75)
      and A["sha256"] == sha(G_PATH) and A["parts_total"] >= 1 and A["is_container"] is False,
      {k: A.get(k) for k in ("slicer", "estimated_s", "materials", "weight_g", "parts_total", "warnings")})
M_PATH = os.path.join(SRCDIR, "bracket.gcode.3mf")
with zipfile.ZipFile(M_PATH, "w", zipfile.ZIP_DEFLATED) as _z:
    _z.writestr("Metadata/plate_1.gcode", GCODE)
    _z.writestr("3D/3dmodel.model", "<model/>")
A3 = cb.analyze_print_file(M_PATH, "bracket.gcode.3mf")
#  16.10.2026 (R-136): Bambu Studio пишет в «total filament weight» только ИСПОЛЬЗОВАННЫЕ филаменты.
#  Проект PLA, PETG, PLA, ABS; плита печатает только PETG (12,40 г) — в строке G-code одно число.
#  Граммы по номеру филамента есть только в Metadata/slice_info.config.
BS_GCODE = ("; HEADER_BLOCK_START\n; generated by BambuStudio 01.09.07.52 on 2026-10-16 at 10:00:00\n"
            "; model printing time: 0h 40m 0s; total estimated time: 0h 45m 0s\n"
            "; total filament weight [g] : 12.40\n; HEADER_BLOCK_END\n"
            "; filament_type = PLA;PETG;PLA;ABS\n; filament_colour = #FFFFFF;#00AE42;#000000;#FF0000\n"
            "; printer_model = Bambu Lab X1 Carbon\nG28\n")
BS_SLICE = ('<?xml version="1.0" encoding="UTF-8"?><config><plate>'
            '<metadata key="index" value="1"/>'
            '<filament id="2" tray_info_idx="GFG99" type="PETG" color="#00AE42" used_m="4.06" used_g="12.40"/>'
            '</plate><plate><metadata key="index" value="2"/>'
            '<filament id="1" type="PLA" color="#FFFFFF" used_m="9.9" used_g="30.00"/></plate></config>')
BS_PATH = os.path.join(SRCDIR, "four_colors.gcode.3mf")
with zipfile.ZipFile(BS_PATH, "w", zipfile.ZIP_DEFLATED) as _z:
    _z.writestr("Metadata/plate_1.gcode", BS_GCODE)
    _z.writestr("Metadata/slice_info.config", BS_SLICE)
    _z.writestr("3D/3dmodel.model", "<model/>")
ABS_ = cb.analyze_print_file(BS_PATH, "four_colors.gcode.3mf")
_mw = [(m["material"], m["weight_g"]) for m in ABS_.get("materials") or []]
check("E2b. КРИТИЧНО (R-136): 3MF Bambu Studio — граммы плиты по номеру филамента из slice_info: "
      "12,4 г у PETG (второй), у первого PLA — ноль; плита 2 не подмешана",
      _mw == [("PLA", 0.0), ("PETG", 12.4), ("PLA", 0.0), ("ABS", 0.0)] and money(ABS_["weight_g"], 12.4), _mw)
_BS_G = os.path.join(SRCDIR, "four_colors.gcode")
io.open(_BS_G, "w", encoding="utf-8", newline="\n").write(BS_GCODE)
_mwg = [(m["material"], m["weight_g"]) for m in cb.analyze_print_file(_BS_G, "four_colors.gcode").get("materials") or []]
check("E2c. голый G-code без slice_info разбирается как раньше (по порядку строки)",
      _mwg[0] == ("PLA", 12.4), _mwg)
check("E2. 3MF: печатный G-code плиты найден внутри архива и разобран",
      A3["is_container"] is True and A3["inner_gcode"] == "Metadata/plate_1.gcode" and money(A3["weight_g"], 15.75),
      {k: A3.get(k) for k in ("inner_gcode", "weight_g")})


def analysis_error(path, name):
    try:
        cb.analyze_print_file(path, name)
        return None
    except cb.AnalysisError as e:
        return str(e)


_evil = os.path.join(SRCDIR, "evil.gcode.3mf")
with zipfile.ZipFile(_evil, "w") as _z:
    _z.writestr("../evil.gcode", GCODE)
_empty = os.path.join(SRCDIR, "empty.gcode")
open(_empty, "wb").close()
_nog = os.path.join(SRCDIR, "nogcode.3mf")
with zipfile.ZipFile(_nog, "w") as _z:
    _z.writestr("3D/3dmodel.model", "<model/>")
_stl = os.path.join(SRCDIR, "part.stl")
open(_stl, "wb").write(b"solid x\nendsolid x\n")
check("E3. опасный архив (путь с «..») отклоняется до чтения", analysis_error(_evil, "evil.gcode.3mf") == "archive_limit_exceeded")
check("E4. пустой файл, архив без G-code, чужой формат, отсутствующий файл — понятные отказы",
      analysis_error(_empty, "empty.gcode") == "file_empty" and analysis_error(_nog, "nogcode.3mf") == "printable_gcode_missing"
      and analysis_error(_stl, "part.stl") == "unsupported_format"
      and analysis_error(os.path.join(SRCDIR, "nope.gcode"), "nope.gcode") == "file_missing")

# ════════════════════════════════════════════════════════════════════════════
section("F. заказы")

r1 = cb._save_order_record({"title": "Кронштейны", "items": [ITEM1]})
r2 = cb._save_order_record({"title": "Второй", "items": [ITEM2]})
r3 = cb._save_order_record({"title": "Дубль", "order_number": r1.get("order_number"), "items": []})
check("F1. номера заказов по порядку года: %s, %s" % (r1.get("order_number"), r2.get("order_number")),
      r1.get("ok") and r2.get("ok") and r1["order_number"] == "%d-0001" % YEAR and r2["order_number"] == "%d-0002" % YEAR)
check("F2. повтор номера отклоняется с указанием поля", r3 == {"ok": False, "error": "order_number_exists", "field": "order_number"}, r3)
_lst = cb.api_calc_list()
_found = cb.api_calc_list(search="Кронш")
check("F3. список заказов и поиск по названию", len(_lst["orders"]) == 2 and len(_found["orders"]) == 1
      and _found["orders"][0]["internal_id"] == r1["internal_id"])
_one = cb.api_calc_one(r1["internal_id"])
check("F4. заказ читается целиком: состав, расчёт, файлы",
      _one["payload"]["title"] == "Кронштейны" and _one["calculation"]["customer_price"] > 0 and _one["files"] == [])
_upd = cb._save_order_record({"title": "Кронштейны v2", "items": [ITEM1]}, r1["internal_id"])
check("F5. правка заказа сохраняет его номер и не плодит записи",
      _upd["order_number"] == r1["order_number"] and len(cb.api_calc_list()["orders"]) == 2)
check("F6. сводка модуля", cb.api_summary()["total"] == 2 and cb.api_summary()["active"] is True)

# ════════════════════════════════════════════════════════════════════════════
section("G. файлы заказа")


class FakeUpload(object):
    def __init__(self, path, filename):
        self.filename = filename
        self._f = open(path, "rb")

    async def read(self, n=-1):
        data = self._f.read(n)
        if not data:
            self._f.close()
        return data


_stored = asyncio.run(cb._store_order_files(r2["internal_id"], [("file:tok1", FakeUpload(G_PATH, "bracket.gcode"))]))
_rows = cb._order_files(r2["internal_id"], include_path=True)
check("G1. файл заказа сохранён копией в папке модуля, отпечаток совпадает с исходником",
      len(_stored) == 1 and len(_rows) == 1 and cb._is_managed_file(_rows[0]["stored_path"])
      and os.path.isfile(_rows[0]["stored_path"]) and sha(_rows[0]["stored_path"]) == sha(G_PATH)
      and os.path.isfile(G_PATH), _rows)


def store_error(order_id, name):
    try:
        asyncio.run(cb._store_order_files(order_id, [("file:bad", FakeUpload(G_PATH, name))]))
        return None
    except cb.AnalysisError as e:
        return str(e)


_evil_name = "..\\..\\evil:stream.gcode"
check("G2. имя файла с путём и потоком NTFS не выводит запись из папки заказа и не оставляет обрывков",
      store_error(r2["internal_id"], _evil_name) == "unsupported_format"
      and not [f for f in os.listdir(os.path.dirname(_rows[0]["stored_path"])) if ".uploading-" in f]
      and not os.path.exists(os.path.join(TMP, "evil")))
_outside = os.path.join(TMP, "outside_keep.gcode")
shutil.copy2(G_PATH, _outside)
with cb.lock_c:
    cb.conn_c.execute("INSERT INTO order_files(file_id,order_id,file_token,filename,stored_path,size_bytes,sha256,analysis_json,created_at) "
                      "VALUES('ordf_outside',?, 'tok_out','outside_keep.gcode',?,1,'','{}','t')", (r2["internal_id"], _outside))
    cb.conn_c.commit()
_managed_path = _rows[0]["stored_path"]
_del = cb._delete_orders([r2["internal_id"]])
check("G3. удаление заказа убирает запись и СВОЮ копию файла, чужой файл по записанному пути остаётся",
      [d["internal_id"] for d in _del["deleted"]] == [r2["internal_id"]] and not os.path.exists(_managed_path)
      and os.path.isfile(_outside) and cb._order_files(r2["internal_id"]) == []
      and cb.api_calc_one(r2["internal_id"]).get("error") == "not_found", _del)

#  0.2.2 (29.09.2026): перенос папки данных программы (Настройки → Хранение данных). Файлы заказов
#  уезжают в новую cost_order_files, а в базе остаются абсолютные пути в прежнюю папку. Модуль
#  обязан находить файлы на новом месте, не переписывая базу, и удалять только файлы ТЕКУЩЕЙ папки.
r4 = cb._save_order_record({"title": "До переноса", "items": [dict(ITEM2, file_token="tokmv")]})
asyncio.run(cb._store_order_files(r4["internal_id"], [("file:tokmv", FakeUpload(G_PATH, "moved.gcode"))]))
_old_path = cb._order_files(r4["internal_id"], include_path=True)[0]["stored_path"]
TMP3 = tempfile.mkdtemp(prefix="fm_cost_order_moved_")
_bk = sqlite3.connect(os.path.join(TMP3, "farm_cost.db"))
with cb.lock_c:
    cb.conn_c.commit()
    cb.conn_c.backup(_bk)
_bk.close()
shutil.copytree(cb.FILES_DIR, os.path.join(TMP3, "cost_order_files"))
_away = cb.FILES_DIR + "_moved_away"
os.rename(cb.FILES_DIR, _away)            # прежней папки файлов больше нет — как после переноса
cm = load_backend("moved")
cm.register(FakeCore(TMP3))
_mv_rows = cm._order_files(r4["internal_id"], include_path=True)
_db_path = sqlite3.connect(os.path.join(TMP3, "farm_cost.db")).execute(
    "SELECT stored_path FROM order_files WHERE order_id=?", (r4["internal_id"],)).fetchone()
check("G4. после переноса папки данных файл заказа находится в НОВОЙ папке; запись в базе не переписана",
      len(_mv_rows) == 1 and os.path.dirname(os.path.dirname(_mv_rows[0]["stored_path"])) == cm.FILES_DIR
      and os.path.isfile(_mv_rows[0]["stored_path"]) and sha(_mv_rows[0]["stored_path"]) == sha(G_PATH)
      and _db_path == (_old_path,) and not os.path.exists(_old_path), (_mv_rows, _db_path))
_up_mv = []


def _fake_mp_moved(base, path, field, filename, file_path, headers, content_type="application/octet-stream"):
    _up_mv.append((path, filename, sha(file_path) if os.path.isfile(file_path) else None))
    if not os.path.isfile(file_path):
        raise OSError("file_missing")          # настоящая функция падает на open() так же
    return 200, {"status": "ok"}


cm._http_multipart_file = _fake_mp_moved
_link = asyncio.run(cm._complete_project_link(r4["internal_id"], "Проект после переноса", {"id": "prj_mv"},
                                              "http://127.0.0.1:1", {}))
check("G5. проект по заказу после переноса получает файл заказа (раньше — «upload_failed»: файл искали в старой папке)",
      _link.get("ok") and _link.get("uploaded") == ["moved.gcode"] and not _link.get("file_failures")
      and len(_up_mv) == 1 and _up_mv[0][2] == sha(G_PATH), (_link, _up_mv))
r5 = cm._save_order_record({"title": "Копия после переноса", "items": [dict(ITEM2, file_token="tokmv")]})
_cp = cm._copy_order_files(r4["internal_id"], r5["internal_id"], ["tokmv"])
check("G6. «Создать копию» после переноса копирует файл заказа, а не отказывает «source_file_missing»",
      len(_cp["copied"]) == 1 and not _cp["failures"]
      and cm._is_managed_file(cm._order_files(r5["internal_id"], include_path=True)[0]["stored_path"]), _cp)
os.makedirs(os.path.dirname(_old_path), exist_ok=True)
shutil.copy2(G_PATH, _old_path)             # по старому пути снова лежит файл — для новой папки он чужой
_new_path = _mv_rows[0]["stored_path"]
_d4 = cm._delete_orders([r4["internal_id"]])
check("G7. удаление заказа после переноса убирает файл в НОВОЙ папке и не трогает файл по старому пути",
      [d["internal_id"] for d in _d4["deleted"]] == [r4["internal_id"]] and not os.path.exists(_new_path)
      and os.path.isfile(_old_path) and _d4.get("file_delete_failures") == [], _d4)
_foreign = os.path.join(TMP3, "elsewhere", "x.gcode")
_dotted = os.path.join(TMP, "cost_order_files", "..", "..", "evil.gcode")
check("G8. путь без «cost_order_files» (чужой файл) и путь с «..» после него остаются как есть",
      cm._stored_file(_foreign) == _foreign and cm._stored_file(_dotted) == _dotted and cm._stored_file("") == "")
try:
    cm.conn_c.close()
except Exception:
    pass
shutil.rmtree(cb.FILES_DIR, ignore_errors=True)   # только что созданная папка с одним файлом теста
os.rename(_away, cb.FILES_DIR)
shutil.rmtree(TMP3, ignore_errors=True)

# ════════════════════════════════════════════════════════════════════════════
section("H. импорт из программы и создание проекта (обращения к программе подменены)")

CALLS, IMPORTED, UPLOADED, PROJECTS = [], [], [], []
TASKS_DIR = os.path.join(TMP, "fm_tasks")
os.makedirs(TASKS_DIR)
STAGING_SRC = os.path.join(TASKS_DIR, "bracket_v3.gcode")
shutil.copy2(G_PATH, STAGING_SRC)
STAGING = [{"filename": "bracket_v3.gcode", "src_path": STAGING_SRC, "is_printable": True, "missing": False,
            "target_model": "Bambu Lab X1 Carbon", "compatible_pids": ["p1"], "mtime": 1}]


def fake_http_json(base, path, method="GET", payload=None, headers=None):
    CALLS.append({"kind": "json", "base": base, "path": path, "method": method, "headers": dict(headers or {})})
    if path == "/api/printers":
        return 200, {"printers": [{"id": "p1", "model": "Bambu Lab X1 Carbon", "model_key": "bambu lab x1 carbon"}]}
    if path == "/api/staging":
        return 200, {"files": [dict(r) for r in STAGING]}
    if path == "/api/projects2":
        return 200, [dict(p) for p in PROJECTS]
    return 404, {"error": "not_found"}


def fake_multipart(base, path, field, filename, file_path, headers, content_type="application/octet-stream"):
    CALLS.append({"kind": "multipart", "base": base, "path": path, "method": "POST", "headers": dict(headers or {})})
    if path == "/api/projects/import":
        data = json.load(io.open(file_path, encoding="utf-8"))
        IMPORTED.append(data)
        for p in data.get("projects") or []:
            PROJECTS.append({"id": "prj_%d" % (len(PROJECTS) + 1), "name": p["name"]})
        return 200, {"status": "ok"}
    if re.match(r"^/api/projects2/[^/]+/files/upload$", path):
        UPLOADED.append({"path": path, "filename": filename, "sha": sha(file_path)})
        return 200, {"status": "ok"}
    return 404, {}


cb._http_json = fake_http_json
cb._http_multipart_file = fake_multipart


class FakeURL(object):
    scheme = "http"


class FakeReq(object):
    def __init__(self, body=None, headers=None, port=8123):
        self._body = body or {}
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.headers.setdefault("content-type", "application/json")
        self.scope = {"server": ("0.0.0.0", port)}
        self.url = FakeURL()

    async def json(self):
        return self._body


#  16.10.2026 (R-150): в Cookie браузера — и кука ЧУЖОЙ программы на 127.0.0.1 (куки не разделяются по
#  портам); дальше обязана уйти только fm_session.
HDR = {"Cookie": "other_app=s3cr3t; fm_session=abc", "Authorization": "Bearer t0k", "X-CSRF-Token": "csrf1",
       "Host": "evil.example:80", "X-Forwarded-For": "203.0.113.9", "Origin": "http://evil.example"}

_src = asyncio.run(cb.api_calculate(FakeReq({"action": "fm_sources"}, HDR)))
check("H1. список источников: задача программы видна, путь к файлу в браузер не уходит",
      _src.get("ok") and len(_src.get("files") or []) == 1 and _src["files"][0]["filename"] == "bracket_v3.gcode"
      and STAGING_SRC not in json.dumps(_src, ensure_ascii=False) and "src_path" not in json.dumps(_src), _src)
SID = (_src.get("files") or [{}])[0].get("source_id")
_imp = asyncio.run(cb.api_calculate(FakeReq({"action": "fm_import_staging", "source_id": SID}, HDR)))
_item = ((_imp.get("draft") or {}).get("items") or [{}])[0]
check("H2. импорт задачи даёт черновик: файл разобран, принтер подобран, время и материалы из файла",
      _imp.get("ok") and _item.get("filename") == "bracket_v3.gcode" and _item.get("printer_id") == "p1"
      and _item.get("duration_s") == 3900 and len(_item.get("materials") or []) == 2
      and (_item.get("fm_source") or {}).get("source_sha256") == sha(STAGING_SRC), _imp)
_cache = sqlite3.connect(os.path.join(TMP, "farm_cost.db")).execute(
    "SELECT printer_id, model_name, source FROM order_printer_models").fetchall()
check("H3. при импорте модуль обновил кэш моделей принтеров из списка программы (единственная запись расчёта)",
      _cache == [("p1", "Bambu Lab X1 Carbon", "public_api")], _cache)

_draft = dict(_imp.get("draft") or {})
_draft["title"] = "Заказ из задачи"
_saved = asyncio.run(cb.api_calc_save(FakeReq({"order": _draft}, HDR)))
_sf = cb._order_files(_saved.get("internal_id", ""), include_path=True)
check("H4. сохранение: файл задачи скопирован в папку заказа, исходник программы не тронут",
      _saved.get("ok") and len(_sf) == 1 and cb._is_managed_file(_sf[0]["stored_path"])
      and sha(_sf[0]["stored_path"]) == sha(STAGING_SRC) and os.path.isfile(STAGING_SRC), (_saved.get("error"), _sf))

_before = len(cb.api_calc_list()["orders"])
io.open(STAGING_SRC, "a", encoding="utf-8").write("; changed after import\n")
_again = dict(_imp.get("draft") or {})
_again["title"] = "Устаревший черновик"
_stale = asyncio.run(cb.api_calc_save(FakeReq({"order": _again}, HDR)))
check("H5. файл задачи изменился после импорта — сохранение отказывает, полузаписанный заказ не остаётся",
      _stale == {"ok": False, "error": "source_changed"} and len(cb.api_calc_list()["orders"]) == _before, _stale)

OID = _saved.get("internal_id", "")
_proj = asyncio.run(cb.api_calc_recalc(OID, FakeReq({"action": "create_project"}, HDR)))
_exp_name = "%s — %s" % (_saved.get("order_number"), "Заказ из задачи")
check("H6. по заказу создан проект: имя «номер — название», детали из черновика, файл заказа загружен в проект",
      _proj.get("ok") and _proj.get("project_id") == "prj_1" and len(IMPORTED) == 1
      and IMPORTED[0]["projects"][0]["name"] == _exp_name and IMPORTED[0]["projects"][0]["parts"]
      and len(UPLOADED) == 1 and UPLOADED[0]["path"] == "/api/projects2/prj_1/files/upload"
      and UPLOADED[0]["sha"] == sha(_sf[0]["stored_path"]) if _sf else False, (_proj, IMPORTED[:1], UPLOADED))
check("H7. статус заказа «проект создан», повторное нажатие не создаёт второй проект",
      cb.api_calc_one(OID)["status"] == "project_created"
      and asyncio.run(cb.api_calc_recalc(OID, FakeReq({"action": "create_project"}, HDR))).get("already_created") is True
      and len(IMPORTED) == 1)
check("H8. каждый запрос модуля ушёл на 127.0.0.1 того же порта, подменённый Host не сработал",
      CALLS and all(c["base"] == "http://127.0.0.1:8123" for c in CALLS), sorted({c["base"] for c in CALLS}))
_allowed_hdr = {"Cookie", "User-Agent"}
check("H9. дальше уходит только кука сеанса fm_session (и подпись модуля); Authorization, X-CSRF-Token, Host, "
      "Origin, X-Forwarded-For и чужие куки — нет",
      all(set(c["headers"]) <= _allowed_hdr and c["headers"].get("Cookie") == "fm_session=abc" for c in CALLS),
      [sorted(c["headers"]) for c in CALLS][:3])
_del2 = asyncio.run(cb.api_calc_recalc(OID, FakeReq({"action": "delete_order"}, HDR)))
check("H10. удаление заказа не трогает созданный проект: программе не ушло ни одного удаления",
      _del2.get("ok") and [x["project_id"] for x in _del2.get("linked_projects_kept") or []] == ["prj_1"]
      and not [c for c in CALLS if c["method"] not in ("GET", "POST")]
      and not [c for c in CALLS if c["kind"] == "multipart" and c["path"] not in ("/api/projects/import", "/api/projects2/prj_1/files/upload")])
#  Настоящее ядро путь файла задачи не отдаёт (staging_files.src_path пуст): файл лежит в
#  управляемой папке данных и ищется по имени. Именно так модуль и должен его находить.
_managed = os.path.join(TMP, "temp_files")
os.makedirs(_managed, exist_ok=True)
shutil.copy2(G_PATH, os.path.join(_managed, "task_managed.gcode"))
shutil.copy2(G_PATH, os.path.join(TMP, "outside.gcode"))
STAGING[:] = [{"filename": "task_managed.gcode", "src_path": "", "is_printable": True, "missing": False,
               "target_model": "", "compatible_pids": ["p1"], "mtime": 2},
              {"filename": "../outside.gcode", "src_path": "", "is_printable": True, "missing": False,
               "target_model": "", "compatible_pids": [], "mtime": 3},
              {"filename": "..\\outside.gcode", "src_path": "", "is_printable": True, "missing": False,
               "target_model": "", "compatible_pids": [], "mtime": 4}]
_src2 = asyncio.run(cb.api_calculate(FakeReq({"action": "fm_sources"}, HDR)))
check("H12. задача без записанного пути (так хранит ядро) находится по имени в папке данных; имя с «..» наружу не выводит; путь в браузер не уходит",
      _src2.get("ok") and [f["filename"] for f in _src2.get("files") or []] == ["task_managed.gcode"]
      and _managed not in json.dumps(_src2, ensure_ascii=False) and TMP not in json.dumps(_src2, ensure_ascii=False), _src2)
_imp2 = asyncio.run(cb.api_calculate(FakeReq({"action": "fm_import_staging",
                                              "source_id": ((_src2.get("files") or [{}])[0]).get("source_id")}, HDR)))
check("H13. такая задача импортируется в черновик: файл разобран, отпечаток — от файла в папке данных",
      _imp2.get("ok") and ((_imp2.get("draft") or {}).get("items") or [{}])[0].get("fm_source", {}).get("source_sha256")
      == sha(os.path.join(_managed, "task_managed.gcode")), _imp2)
check("H11. у модуля нет ни одного адреса вне 127.0.0.1: единственный шаблон адреса — «%s://127.0.0.1:%d»",
      [n.value for n in ast.walk(ast.parse(SRC)) if isinstance(n, ast.Constant) and isinstance(n.value, str) and "://" in n.value]
      == ["%s://127.0.0.1:%d"]
      and "ProxyHandler({})" in SRC)

# ════════════════════════════════════════════════════════════════════════════
#  16.10.2026 (R-150 e): порт — только из scope['server']; без него модуль ничего никуда не шлёт.
_n_calls = len(CALLS)


class FakeReqNoPort(FakeReq):
    def __init__(self, body=None, headers=None):
        FakeReq.__init__(self, body, headers)
        self.scope = {}


_src_np = asyncio.run(cb.api_calculate(FakeReqNoPort({"action": "fm_sources"}, HDR)))
_saved_np = cb._save_order_record({"title": "Без порта", "items": []})
_proj_np = asyncio.run(cb.api_calc_recalc(_saved_np.get("internal_id", ""), FakeReqNoPort({"action": "create_project"}, HDR)))
check("H8b. без адреса сервера в запросе (scope['server']) модуль не угадывает порт 8000: список задач и "
      "создание проекта отказывают, ни одного обращения наружу",
      not _src_np.get("files") and "fm_staging_unavailable" in (_src_np.get("warnings") or [])
      and _proj_np == {"ok": False, "error": "projects_api_unavailable"}
      and len(CALLS) == _n_calls, (_src_np, _proj_np, CALLS[_n_calls:]))
_h_only = cb._auth_headers(FakeReq({}, {"Cookie": "fm_session=bad value;x", "Authorization": "Bearer t"}))
_h_ok = cb._auth_headers(FakeReq({}, {"Cookie": "a=1; fm_session=fmd_AbC-12_x; b=2"}))
check("H9b. кука сеанса проверяется: мусор не пересылается вовсе, годная — ровно «fm_session=<значение>»",
      _h_only == {"User-Agent": "3DIWELL-Order-Module/1"}
      and _h_ok == {"Cookie": "fm_session=fmd_AbC-12_x", "User-Agent": "3DIWELL-Order-Module/1"}, (_h_only, _h_ok))

# ════════════════════════════════════════════════════════════════════════════
section("R-151. откат записи заказа не стирает чужое и новое")

with cb.lock_c:
    _ocols = {str(r[1]) for r in cb.conn_c.execute("PRAGMA table_info(orders)").fetchall()}
    if "extra_new_version" not in _ocols:
        cb.conn_c.execute("ALTER TABLE orders ADD COLUMN extra_new_version TEXT NOT NULL DEFAULT ''")
    cb.conn_c.commit()
_oa = cb._save_order_record({"title": "Заказ А", "items": []})
_ob = cb._save_order_record({"title": "Заказ Б", "items": []})
with cb.lock_c:
    cb.conn_c.execute("UPDATE orders SET extra_new_version='значение новой версии' WHERE internal_id=?",
                      (_oa["internal_id"],))
    cb.conn_c.commit()
    _snap_a = dict(cb.conn_c.execute("SELECT * FROM orders WHERE internal_id=?", (_oa["internal_id"],)).fetchone())
    cb.conn_c.execute("UPDATE orders SET title='испорчено', extra_new_version='' WHERE internal_id=?",
                      (_oa["internal_id"],))
    cb.conn_c.commit()
cb._restore_order_snapshot(_snap_a, _oa["internal_id"])
with cb.lock_c:
    _ra = dict(cb.conn_c.execute("SELECT * FROM orders WHERE internal_id=?", (_oa["internal_id"],)).fetchone())
check("R1. откат вернул запись целиком — и столбец, которого эта версия модуля не знает",
      _ra["title"] == "Заказ А" and _ra["extra_new_version"] == "значение новой версии", _ra)
_snap_clash = dict(_snap_a, order_number=_ob["order_number"])
with cb.lock_c:
    _n_before = cb.conn_c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
cb._restore_order_snapshot(_snap_clash, _oa["internal_id"])
with cb.lock_c:
    _n_after = cb.conn_c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    _rb = cb.conn_c.execute("SELECT title FROM orders WHERE internal_id=?", (_ob["internal_id"],)).fetchone()
    _ra2 = cb.conn_c.execute("SELECT order_number FROM orders WHERE internal_id=?", (_oa["internal_id"],)).fetchone()
check("R2. КРИТИЧНО: номер в снимке занят другим заказом — ни один заказ не удалён (REPLACE удалил бы "
      "заказ Б), запись А осталась прежней, база не в незакрытой транзакции",
      _n_after == _n_before and _rb is not None and _rb[0] == "Заказ Б" and _ra2[0] == _oa["order_number"]
      and not cb.conn_c.in_transaction, (_n_before, _n_after, _rb, _ra2))
check("R3. (R-150 f) испорченных комментариев «????» в модуле больше нет, файл целиком CRLF",
      "????" not in SRC and b"\r\n" in open(BACKEND, "rb").read()
      and b"\n" not in open(BACKEND, "rb").read().replace(b"\r\n", b""))

section("I. эффекты маршрутов и права")

SQL_W = re.compile(r"\b(INSERT\s+INTO|INSERT\s+OR\s+\w+\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|BEGIN\s+IMMEDIATE|ALTER\s+TABLE|CREATE\s+TABLE)\b", re.I)
SQL_T = re.compile(r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE(?!\s+SET\b)|DELETE\s+FROM)\s+(\w+)", re.I)   # «DO UPDATE SET» — не таблица
FS_CALLS = {"open", "os.remove", "os.rmdir", "os.makedirs", "os.replace", "os.rename", "os.unlink", "shutil.copy2",
            "shutil.copyfile", "shutil.move", "shutil.rmtree", "tempfile.mkstemp", "os.stat", "os.listdir",
            "os.path.getsize"}
NET_CALLS = {"build_opener", "UrlRequest", "conn_cls"}
#  Функции из соседних файлов модуля, до которых разбор backend.py не дотягивается: разбор файла
#  печати читает файл (FILESYSTEM), расчёт — чистая арифметика.
SIBLINGS = {"analyze_print_file": "FILESYSTEM", "_TrustedLocalUpload": "FILESYSTEM", "calculate_order": None}
_TREE = ast.parse(SRC)
_FNS = {}


class _Idx(ast.NodeVisitor):
    def visit_FunctionDef(self, n):
        _FNS.setdefault(n.name, []).append(n)
        self.generic_visit(n)
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, n):
        _FNS.setdefault(n.name, []).append(n)
        self.generic_visit(n)


_Idx().visit(_TREE)


def _dotted(f):
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
        return ".".join(reversed(parts))
    return "." + ".".join(reversed(parts))


def _facts(name, seen=None):
    """-> {категория: множество улик, 'tables': таблицы записи}. Функция, переданная аргументом
    (asyncio.to_thread(fn, ...)), считается вызванной — иначе запись в потоке была бы не видна."""
    seen = seen if seen is not None else set()
    out = {}
    if name in seen:
        return out
    seen.add(name)
    if SIBLINGS.get(name):
        out.setdefault(SIBLINGS[name], set()).add(name)
    for fn in _FNS.get(name, []):
        refs = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                if SQL_W.search(n.value):
                    out.setdefault("DATABASE", set()).add(SQL_W.search(n.value).group(0).upper())
                for t in SQL_T.findall(n.value):
                    out.setdefault("tables", set()).add(t)
            if isinstance(n, ast.Call):
                d = _dotted(n.func)
                if d.endswith(".commit"):
                    out.setdefault("DATABASE", set()).add("commit")
                if d in FS_CALLS:
                    out.setdefault("FILESYSTEM", set()).add(d)
                if d in NET_CALLS or d.endswith((".HTTPConnection", ".HTTPSConnection")):
                    out.setdefault("NETWORK", set()).add(d)
                refs.add(d.split(".")[-1])
                for a in list(n.args) + [k.value for k in n.keywords]:
                    if isinstance(a, ast.Name):
                        refs.add(a.id)
        for r in refs:
            if r in _FNS or r in SIBLINGS:
                for k, v in _facts(r, seen).items():
                    out.setdefault(k, set()).update(v)
    return out


_mismatch = []
for p in COSTP:
    f = _facts(p.handler)
    fact = sorted(k for k in f if k != "tables") or ["NONE"]
    declared = sorted(e.value for e in p.side_effects)
    if fact != declared:
        _mismatch.append((p.policy_id, "факт", fact, "в карте", declared))
check("I1. эффекты всех 10 маршрутов в карте прав равны факту графа вызовов обработчиков", not _mismatch, _mismatch)
check("I2. разбор не выродился: есть и запись, и файлы, и обращения к программе, и чистые чтения",
      {"DATABASE", "FILESYSTEM", "NETWORK"} <= {k for p in COSTP for k in _facts(p.handler)}
      and sum(1 for p in COSTP if not _facts(p.handler)) >= 4)
_calc_tables = _facts("api_calculate").get("tables", set())
check("I3. расчёт открыт роли «только просмотр» — и пишет только кэш моделей принтеров, не заказы и не настройки",
      BY_ID["cost.calculate"].required_capability == "view" and _calc_tables == {"order_printer_models"}, _calc_tables)
check("I4. POST расчёта больше не числится «только чтением»: он пишет кэш и временный файл",
      "cost.calculate" not in reg.READ_ONLY_DESPITE_METHOD and BY_ID["cost.calculate"].read_only is False)
_caps = {p.policy_id: p.required_capability for p in COSTP}
check("I5. права маршрутов прежние: чтение и расчёт — просмотр; сохранение и проект — проекты; тарифы — администратор",
      _caps == {"cost.settings.read": "view", "cost.printers.read": "view", "cost.calculate": "view",
                "cost.calculations.list": "view", "cost.calculations.read": "view", "cost.summary.read": "view",
                "cost.calculations.save": "project", "cost.calculations.recalc": "project",
                "cost.settings.write": "admin", "cost.printer_settings.write": "admin"}, _caps)
check("I6. окно модуля проверяет права тем же контрактом ядра, что и остальные окна",
      "CAP_CONTRACT_VERSION = 1" in PANEL and "a.contractVersion === CAP_CONTRACT_VERSION" in PANEL
      #  0.2.3: перед правами — «только просмотр» платной сборки без лицензии; сама проверка прав прежняя.
      and "const guard = (cap) => { if (licReadOnly.value) return false; if (can(cap)) return true; denyFlash(); return false; }" in PANEL
      and set(re.findall(r"(?:can|guard)\('([a-z_]+)'\)", PANEL)) <= {"view", "project", "admin"})

# ════════════════════════════════════════════════════════════════════════════
section("J. резервная копия")

from app.config_backup import module_providers as MP   # noqa: E402
from app.config_backup.sqlite_store import SqliteModuleStore   # noqa: E402

_fresh = load_backend("fresh")
_fresh.register(FakeCore(TMP2))
_prov = MP.get_provider("cost")
#  R-125: копия «Расчёта заказа» (backup v2) — по настоящим таблицам модуля; ядро открывает базу без
#  таблицы «ключ-значение» (_CFGBACKUP_MODULE_DB["cost"] = ("farm_cost.db", None, ...)).
try:
    _snap_empty = _prov.export_snapshot(SqliteModuleStore(os.path.join(TMP2, "farm_cost.db"), _prov.table_specs,
                                                          None, ("key", "value")), installed_version=MJ["version"])
    _err = None
except Exception as e:   # noqa: BLE001
    _snap_empty, _err = None, repr(e)
check("J1. копия с установленным «Расчётом заказа» на чистой базе собирается без ошибок (заказов ещё нет)",
      _err is None and all(not rows for rows in (_snap_empty.get("domain_data") or {}).get("tables", {}).values())
      and not _snap_empty.get("settings"), _err or _snap_empty)
_saved = _fresh._save_order_record({"title": "Заказ для копии", "items": []})
_snap_new = _prov.export_snapshot(SqliteModuleStore(os.path.join(TMP2, "farm_cost.db"), _prov.table_specs,
                                                    None, ("key", "value")), installed_version=MJ["version"])
_tabs_new = (_snap_new.get("domain_data") or {}).get("tables", {})
check("J1b. КРИТИЧНО: сохранённый заказ попадает в копию (раньше копия заказов была пустой)",
      _saved.get("ok") and [r.get("internal_id") for r in _tabs_new.get("orders") or []] == [_saved.get("internal_id")]
      and [r.get("order_number") for r in _tabs_new.get("orders") or []] == [_saved.get("order_number")]
      and "order_files" not in _tabs_new and _snap_new.get("backup_schema_version") == 2,
      (_saved, sorted(_tabs_new)))
_snap_old = _prov.export_snapshot(SqliteModuleStore(os.path.join(TMP, "farm_cost.db"), _prov.table_specs,
                                                    None, ("key", "value")), installed_version=MJ["version"])
_old_db = sqlite3.connect(os.path.join(TMP, "farm_cost.db"))
check("J2. таблицы прежней «Себестоимости» в копию 3.0 не входят (модуль их не использует), в базе они целы",
      not any(n.startswith("cost_") for n in (_snap_old.get("domain_data") or {}).get("tables", {}))
      and not _snap_old.get("settings")
      and _old_db.execute("SELECT COUNT(*) FROM cost_calculations").fetchone() == (1,),
      ((_snap_old.get("domain_data") or {}).get("tables"), _snap_old.get("settings")))
_old_db.close()
try:
    _fresh.conn_c.close()
except Exception:
    pass

# ════════════════════════════════════════════════════════════════════════════
section("метка-ловушка и уборка")

check("K1. метка-ловушка не попала в производственный код",
      not any(SENTINEL in rd(p) for p in (BACKEND, os.path.join(MOD_DIR, "order_parser.py"),
                                          os.path.join(MOD_DIR, "order_calculator.py"),
                                          os.path.join(MOD_DIR, "web", "CostPanel.js"),
                                          os.path.join(REPO, "app", "route_policy_registry.py"))))
try:
    cb.conn_c.close()
except Exception:
    pass
shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(TMP2, ignore_errors=True)
check("K2. временные папки теста убраны", not os.path.isdir(TMP) or not os.listdir(TMP))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
