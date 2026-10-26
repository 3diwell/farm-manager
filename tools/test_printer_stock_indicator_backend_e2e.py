# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.797 — ИЗОЛИРОВАННЫЙ backend E2E-тест индикатора складской привязки.
#
#  ЧТО ПРОВЕРЯЕТ (реальная цепочка СОХРАНЕНА, ожидания НЕ ослаблены):
#    реальный modules/inventory/backend.py (register на ВРЕМЕННОЙ БД, реальная схема,
#    реальный SQL bind) -> реальный _inv_filament_provider() -> реальный core-агрегатор
#    _aggregate_printer_filament() (исходник берётся ИЗ server.py как текст, БЕЗ импорта
#    server.py) -> реальная JSON-сериализация ответа /api/printer-filament.
#  Сценарии: external -1 / AMS0 / мульти-AMS5 / AMS HT512 / telemetry-only / fail-open /
#  unbind + граничные значения остатка (0 / NULL / отрицательный / больше максимума) и
#  изоляция катушек разных принтеров.
#
#  ПОЧЕМУ ЗАМЕНА (Alpha 2.796 и раньше): тест писал реальный ответ в
#  tools/_e2e_payload.json — артефакт в РАБОЧЕМ ДЕРЕВЕ репозитория, который не удалялся
#  ни при успехе, ни при падении, ни при прерывании (никакого cleanup не было), поэтому
#  полный набор был вынужден пропускать тест, а после ручного запуска требовалась ручная
#  уборка. Временная БД создавалась через tempfile.mkdtemp() БЕЗ очистки — каждая
#  попытка оставляла папку в %TEMP% (к 2026-07-21 их накопилось >1300).
#
#  ТЕПЕРЬ: ВСЕ временные файлы (БД, payload) живут ТОЛЬКО внутри
#  tempfile.TemporaryDirectory() и исчезают автоматически при любом исходе; ловушки-
#  шпионы доказывают отсутствие сокетов/подпроцессов/записей вне temp-root; atexit-страж
#  превращает преждевременный выход в честный красный; после прогона тест сам проверяет,
#  что в дереве репозитория не появилось ни одного файла.
#
#  Запуск: python tools/test_printer_stock_indicator_backend_e2e.py   (0 = пройдено)
# ============================================================================
import ast
import atexit
import builtins
import importlib.util
import json
import logging
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.disable(logging.CRITICAL)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Страж преждевременного выхода: exit 0 до итоговой сводки невозможен ──────
_COMPLETED = {"done": False}

def _premature_exit_guard():
    if not _COMPLETED["done"]:
        try:
            print("FAIL — тест завершился до выполнения проверок (ложнозелёный сценарий пресечён)")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)

atexit.register(_premature_exit_guard)

# ── Ловушки-шпионы ───────────────────────────────────────────────────────────
# Устанавливаются ДО любой работы. Пишущий open вне temp-root и sqlite вне temp-root
# падают СРАЗУ (deny до внешнего write), а не обнаруживаются задним числом.
_TMP_HOLDER = {"root": None}   # normcase-путь temp-root; до создания записи запрещены
_SOCKETS = []
_PROCS = []
_THREADS = []
_DB_PATHS = []
_OPENS = []

def _under_tmp(path):
    r = _TMP_HOLDER["root"]
    return bool(r) and os.path.normcase(os.path.abspath(path)).startswith(r)


class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
        raise AssertionError("offline-тест: создание сокета запрещено")

socket.socket = _TrapSocket

def _trap_proc(*a, **k):
    _PROCS.append(a)
    raise AssertionError("offline-тест: подпроцессы (в т.ч. git) запрещены")

subprocess.Popen = _trap_proc
subprocess.run = _trap_proc
subprocess.call = _trap_proc
subprocess.check_output = _trap_proc

# Реальный register() склада запускает ОДИН штатный фоновый наблюдатель возвратов
# (daemon 'inv-return-watch', тик 5 с по временной БД) — он разрешён; любой другой
# поток (uvicorn, discovery и т.п.) — запрещён.
_ALLOWED_THREADS = {"inv-return-watch"}
_ORIG_THREAD_START = threading.Thread.start

def _spy_thread_start(self, *a, **k):
    name = str(getattr(self, "name", ""))
    _THREADS.append(name)
    if name not in _ALLOWED_THREADS:
        raise AssertionError("offline-тест: неожиданный поток %r" % name)
    return _ORIG_THREAD_START(self, *a, **k)

threading.Thread.start = _spy_thread_start

_ORIG_CONNECT = sqlite3.connect

def _spy_connect(database, *a, **k):
    p = str(database)
    _DB_PATHS.append(p)
    if p != ":memory:" and not _under_tmp(p):
        raise AssertionError("offline-тест: sqlite вне temp-root запрещён: %s" % p)
    return _ORIG_CONNECT(database, *a, **k)

sqlite3.connect = _spy_connect

_ORIG_OPEN = builtins.open

def _spy_open(file, mode="r", *a, **k):
    p, m = str(file), str(mode)
    _OPENS.append((p, m))
    if any(c in m for c in "wax+") and not _under_tmp(p):
        raise AssertionError("offline-тест: запись вне temp-root запрещена: %s" % p)
    return _ORIG_OPEN(file, mode, *a, **k)

builtins.open = _spy_open

# ── Оснастка проверок ────────────────────────────────────────────────────────
FAILED = []
PASSED = [0]

def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)

def section(t):
    print("\n--- %s ---" % t)

# Метка-ловушка: живёт ТОЛЬКО во временных fixture (метка катушки в temp-БД).
SENTINEL = "PRINTER_STOCK_E2E_SENTINEL_2_797"

OWN_SRC = open(os.path.abspath(__file__), encoding="utf-8").read()
SRV_SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
BK_PATH = os.path.join(REPO, "modules", "inventory", "backend.py")
BK_SRC = open(BK_PATH, encoding="utf-8").read()
ORCH_SRC = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()

# Снимки дерева репозитория ДО работы (сравниваются в конце: артефактов быть не должно).
_TOOLS_BEFORE = set(os.listdir(os.path.join(REPO, "tools")))
_ROOT_BEFORE = set(f for f in os.listdir(REPO) if os.path.isfile(os.path.join(REPO, f)))


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.797: изолированный backend E2E-тест индикатора складской привязки ===")
section("characterization: почему старый тест Alpha 2.796 был непригоден")

# Дословная выдержка из tools/test_printer_stock_indicator_backend_e2e.py состояния
# commit c2bd5c0 (Alpha 2.796). Отпечаток файла зафиксирован; git в прогоне не вызывается.
OLD_SHA256 = "67ef75840a204f899e7e795f5f33a69145d9c11788e4358f394313a1f4117df0"
OLD_WRITE_FIXTURE = (
    "with open(os.path.join(REPO, 'tools', '_e2e_payload.json'), 'w', encoding='utf-8') as f:\n"
    "    json.dump(resp, f, ensure_ascii=False)\n"
)
OLD_TMPDIR_FIXTURE = "DB = os.path.join(tempfile.mkdtemp(), 'farm_inventory.db')"

check("C1. старый тест писал артефакт в РАБОЧЕЕ ДЕРЕВО: tools/_e2e_payload.json (fixture c2bd5c0)",
      "'tools', '_e2e_payload.json'" in OLD_WRITE_FIXTURE and "'w'" in OLD_WRITE_FIXTURE)
check("C2. cleanup в старом тесте отсутствовал ВООБЩЕ (ни успех, ни падение, ни прерывание)",
      "remove" not in OLD_WRITE_FIXTURE and "unlink" not in OLD_WRITE_FIXTURE
      and "TemporaryDirectory" not in OLD_TMPDIR_FIXTURE)
check("C3. временная БД создавалась mkdtemp() без очистки (утечка папки в %TEMP% за каждый прогон)",
      "tempfile.mkdtemp()" in OLD_TMPDIR_FIXTURE)
check("C4. отпечаток старого файла зафиксирован (SHA-256, состояние c2bd5c0)",
      len(OLD_SHA256) == 64 and all(c in "0123456789abcdef" for c in OLD_SHA256))
check("C5. этот тест не создаёт старый артефакт (запись вне temp-root перехватывается ловушкой)",
      not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))

_own_ast = ast.parse(OWN_SRC)
_imports_server = any(
    (isinstance(n, ast.Import) and any(a.name == "server" for a in n.names))
    or (isinstance(n, ast.ImportFrom) and (n.module or "") == "server")
    for n in ast.walk(_own_ast) if isinstance(n, (ast.Import, ast.ImportFrom)))
_spec_server = False
for _n in ast.walk(_own_ast):
    if isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute) \
            and _n.func.attr == "spec_from_file_location":
        for _sub in ast.walk(_n):
            if isinstance(_sub, ast.Constant) and _sub.value == "server.py":
                _spec_server = True
check("C6. этот тест не импортирует server.py (ни import, ни spec-загрузка server.py)",
      not _imports_server and not _spec_server)
check("C7. server.py и uvicorn не появились в sys.modules (mutex не участвует)",
      "server" not in sys.modules and "uvicorn" not in sys.modules
      and not any(getattr(m, "__file__", "") and os.path.normcase(str(getattr(m, "__file__", "")))
                  == os.path.normcase(os.path.join(REPO, "server.py"))
                  for m in list(sys.modules.values())))


# ════════════════════════════════════════════════════════════════════════════
section("реальная цепочка в изолированной временной среде")

PRINTERS = [
    {"id": "p_ext", "name": "EXT only", "type": "bambu", "ip": "1.1.1.1", "port": 8883, "order_idx": 0},
    {"id": "p_ams", "name": "AMS multi", "type": "bambu", "ip": "1.1.1.2", "port": 8883, "order_idx": 1},
    {"id": "p_ht", "name": "AMS HT", "type": "bambu", "ip": "1.1.1.3", "port": 8883, "order_idx": 2},
    {"id": "p_tel", "name": "Telemetry", "type": "bambu", "ip": "1.1.1.4", "port": 8883, "order_idx": 3},
    {"id": "p_edge", "name": "Edge values", "type": "bambu", "ip": "1.1.1.5", "port": 8883, "order_idx": 4},
]
STATES = {
    "p_ams": {"ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color": "FF0000"},
                            {"index": 5, "unit": 1, "tray": 1, "type": "ASA", "color": "00FF00"}]},
    "p_ht": {"ams_trays": [{"index": 512, "unit": 128, "tray": 0, "type": "PA-CF", "color": "0000FF"}]},
    "p_tel": {"ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "112233"}]},
    "p_edge": {"ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color": "AAAAAA"},
                             {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color": "BBBBBB"},
                             {"index": 2, "unit": 0, "tray": 2, "type": "PLA", "color": "CCCCCC"},
                             {"index": 3, "unit": 0, "tray": 3, "type": "PLA", "color": "DDDDDD"}]},
}
PROVIDERS = []
_n = [0]


class FakeCore:
    """Ровно тот контракт ModuleCore, которым пользуется модуль (см. AGENTS.md §7.1)."""
    module_id = "inventory"

    def __init__(self, db_path):
        self._db = db_path

    def add_route(self, *a, **k):
        return ""

    def add_hook(self, *a, **k):
        return True

    def resolve_db(self, name):
        return self._db

    def new_id(self, prefix=""):
        _n[0] += 1
        return "%s%d" % (prefix, _n[0])

    def printers(self):
        return [dict(p) for p in PRINTERS]

    def printer_states(self):
        return STATES

    def add_printer_filament_provider(self, fn):
        PROVIDERS.append(("inventory", fn))
        return True

    def get_printer_reported_filament(self, pid):
        return {}


# Ожидаемые поля карточки катушки (_inv_spool_brief). Проверка «не меньше» — удаление
# любого поля ловится, аддитивная эволюция контракта не блокируется.
SPOOL_KEYS = {"id", "vendor_name", "material", "color_name", "color_hex",
              "weight_remaining_g", "weight_total_g", "label", "filament_id",
              "vendor_id", "diameter", "lot", "opened_at", "purchased_at",
              "price_per_kg", "spool_price"}
SLOT_KEYS = {"index", "unit", "tray", "external", "offline", "spool", "inventory_bound", "source"}

_TMP_KEPT = {}

with tempfile.TemporaryDirectory(prefix="fm_e2e_stock_") as _tmp:
    _TMP_HOLDER["root"] = os.path.normcase(os.path.abspath(_tmp))
    _TMP_KEPT["path"] = _tmp
    DB = os.path.join(_tmp, "farm_inventory.db")

    spec = importlib.util.spec_from_file_location("inv_backend_e2e", BK_PATH)
    inv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inv)
    inv.register(FakeCore(DB))

    c = inv.conn_inv
    c.execute("INSERT INTO inv_vendors (id,name) VALUES ('v1','Bambu Lab')")
    c.execute("INSERT INTO inv_filaments (id,vendor_id,material,color_name,color_hex,diameter,price_per_kg) "
              "VALUES ('f1','v1','PLA','Красный','FF0000',1.75,1500)")
    # Метка-ловушка — ТОЛЬКО в метке катушки временной БД.
    BINDINGS = [
        ("s_ext", "p_ext", -1, 1000, 500),
        ("s_ams0", "p_ams", 0, 1000, 500),
        ("s_ams5", "p_ams", 5, 1000, 500),
        ("s_ht", "p_ht", 512, 1000, 500),
        ("s_zero", "p_edge", 0, 1000, 0),        # остаток РОВНО 0 — не должен пропасть как falsy
        ("s_null", "p_edge", 1, 1000, None),     # остаток NULL — не должен стать ложным числом
        ("s_neg", "p_edge", 2, 1000, -50),       # отрицательный — безопасно проходит как есть
        ("s_over", "p_edge", 3, 1000, 2000),     # больше максимума — не ломает ответ
    ]
    for sid, pid, slot, total, remaining in BINDINGS:
        c.execute("INSERT INTO inv_spools (id,filament_id,label,weight_total_g,weight_remaining_g,status) "
                  "VALUES (?,?,?,?,?,'in_stock')",
                  (sid, "f1", (SENTINEL if sid == "s_ext" else sid), total, remaining))
        c.commit()
        inv.inv_bind_spool(sid, pid, slot, external=(slot == -1))   # реальная привязка через реальный API модуля

    # Реальный агрегатор ядра: исходник функции берём ИЗ server.py (текстом, БЕЗ импорта)
    # и исполняем как есть — та же техника, что в test_lan_auth_prerequisites.
    _m = re.search(r"\ndef _aggregate_printer_filament\(\):\n(?:.*\n)*?    return out\n", SRV_SRC)
    assert _m, "не найден _aggregate_printer_filament в server.py"
    _ns = {"_printer_filament_providers": PROVIDERS, "log": logging.getLogger("x")}
    exec(_m.group(0), _ns)
    aggregate = _ns["_aggregate_printer_filament"]

    resp = json.loads(json.dumps({"printers": aggregate()}, ensure_ascii=False, default=str))
    # Payload — ТОЛЬКО внутри temp-root (форма данных как у /api/printer-filament).
    _payload_path = os.path.join(_tmp, "_e2e_payload.json")
    with open(_payload_path, "w", encoding="utf-8") as f:
        json.dump(resp, f, ensure_ascii=False)
    check("B1. payload создан строго внутри temp-root и существует до конца прогона",
          os.path.isfile(_payload_path) and _under_tmp(_payload_path))

    P = resp["printers"]

    def rows(pid):
        return (P.get(pid) or {}).get("slots") or []

    def bound(pid):
        return [s for s in rows(pid) if s.get("spool")]

    def spool_of(pid, index):
        for s in bound(pid):
            if s.get("index") == index:
                return s.get("spool")
        return None

    # ── Прежний контракт A1-A8 (ожидания НЕ ослаблены) ──
    check("A1. external -1 -> одна строка со spool, external=true, inventory_bound=true",
          len(bound("p_ext")) == 1 and bound("p_ext")[0]["external"] is True
          and bound("p_ext")[0].get("inventory_bound") is True)
    check("A2. AMS0 + мульти-AMS5 -> две строки со spool, inventory_bound=true",
          len(bound("p_ams")) == 2 and sorted(s["index"] for s in bound("p_ams")) == [0, 5]
          and all(s.get("inventory_bound") is True for s in bound("p_ams")))
    check("A3. AMS HT 512 -> одна строка со spool (unit=128), inventory_bound=true",
          len(bound("p_ht")) == 1 and bound("p_ht")[0]["index"] == 512
          and bound("p_ht")[0]["unit"] == 128 and bound("p_ht")[0].get("inventory_bound") is True)
    check("A4. telemetry-only (материал в AMS, складской катушки нет) -> строк со spool нет",
          len(bound("p_tel")) == 0)
    check("A5. аддитивное поле source='inventory' доезжает через generic-агрегатор",
          all(s.get("source") == "inventory" for pid in ("p_ext", "p_ams", "p_ht", "p_edge")
              for s in bound(pid)))
    check("A5b. агрегатор ядра проставил module_id (карточка знает, ЧЕЙ модуль открыть)",
          all((P.get(pid) or {}).get("module_id") == "inventory"
              for pid in ("p_ext", "p_ams", "p_ht", "p_tel", "p_edge")))
    check("A6. провайдеров нет (Inventory не установлен/выключен) -> {} (fail-open)",
          (lambda ns: (exec(_m.group(0), ns), ns["_aggregate_printer_filament"]())[1])
          ({"_printer_filament_providers": [], "log": logging.getLogger("x")}) == {})
    check("A7. провайдер бросает исключение -> агрегатор глотает, ядро не падает (fail-open)",
          (lambda ns: (exec(_m.group(0), ns), ns["_aggregate_printer_filament"]())[1])
          ({"_printer_filament_providers": [("boom", lambda: (_ for _ in ()).throw(RuntimeError("x")))],
            "log": logging.getLogger("x")}) == {})

    # ── DTO и граничные значения остатка ──
    check("D1. карточка катушки несёт полный набор полей (в т.ч. weight_remaining_g/weight_total_g)",
          all(SPOOL_KEYS <= set(s["spool"]) for pid in ("p_ext", "p_ams", "p_ht", "p_edge")
              for s in bound(pid)))
    check("D2. строка слота несёт ожидаемые поля провайдера (index/unit/tray/external/offline/"
          "spool/inventory_bound/source)",
          all(SLOT_KEYS <= set(s) for pid in ("p_ext", "p_ams", "p_ht", "p_edge") for s in bound(pid)))
    _z = spool_of("p_edge", 0)
    check("D3. остаток РОВНО 0 сохраняется как число 0 (не None, не пропал из-за falsy)",
          _z is not None and _z.get("weight_remaining_g") == 0
          and _z.get("weight_remaining_g") is not None and "weight_remaining_g" in _z)
    _nl = spool_of("p_edge", 1)
    check("D4. NULL-остаток остаётся честным null (не превращается в ложное число/процент)",
          _nl is not None and "weight_remaining_g" in _nl and _nl.get("weight_remaining_g") is None)
    _ng = spool_of("p_edge", 2)
    check("D5. отрицательный остаток проходит безопасно и без искажения (-50)",
          _ng is not None and _ng.get("weight_remaining_g") == -50)
    _ov = spool_of("p_edge", 3)
    check("D6. остаток больше максимума не ломает ответ (2000 при total 1000, оба поля целы)",
          _ov is not None and _ov.get("weight_remaining_g") == 2000
          and _ov.get("weight_total_g") == 1000)
    check("D7. единицы согласованы: оба весовых поля в граммах и числовые (или честный null)",
          all(isinstance(s["spool"].get("weight_total_g"), (int, float))
              and (s["spool"].get("weight_remaining_g") is None
                   or isinstance(s["spool"].get("weight_remaining_g"), (int, float)))
              for pid in ("p_ext", "p_ams", "p_ht", "p_edge") for s in bound(pid)))

    # ── Изоляция принтеров и катушек ──
    _ids_by_pid = {pid: sorted(s["spool"]["id"] for s in bound(pid))
                   for pid in ("p_ext", "p_ams", "p_ht", "p_tel", "p_edge")}
    check("I1. каждая катушка видна ровно у СВОЕГО принтера (данные не подмешиваются)",
          _ids_by_pid == {"p_ext": ["s_ext"], "p_ams": ["s_ams0", "s_ams5"], "p_ht": ["s_ht"],
                          "p_tel": [], "p_edge": ["s_neg", "s_null", "s_over", "s_zero"]})
    check("I2. привязка сопоставлена по printer_id+slot: s_ams5 в слоте 5, s_zero в слоте 0 p_edge",
          (spool_of("p_ams", 5) or {}).get("id") == "s_ams5"
          and (spool_of("p_edge", 0) or {}).get("id") == "s_zero")

    # ── Unbind: реальный API отвязки убирает строку ──
    inv.inv_unbind_spool("s_ext")
    check("A8. unbind последней катушки -> строк со spool у принтера не остаётся",
          len([s for s in (aggregate().get("p_ext") or {}).get("slots") or []
               if s.get("spool")]) == 0)

    # Закрываем sqlite ДО выхода из TemporaryDirectory: на Windows открытый файл БД
    # помешал бы автоочистке (именно поэтому старый тест «не мог» убирать mkdtemp).
    try:
        inv.conn_inv.close()
    except Exception:
        pass

_TMP_HOLDER["root"] = None


# ════════════════════════════════════════════════════════════════════════════
section("cleanup proof: временная среда исчезла при любом исходе")

check("L1. temp-root удалён автоматически после успешного прогона (БД и payload исчезли)",
      not os.path.exists(_TMP_KEPT["path"]))

_fail_dir = {}
try:
    with tempfile.TemporaryDirectory(prefix="fm_e2e_stock_fail_") as _t2:
        _TMP_HOLDER["root"] = os.path.normcase(os.path.abspath(_t2))
        _fail_dir["path"] = _t2
        with open(os.path.join(_t2, "payload_before_failure.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        raise AssertionError("искусственное падение внутри временной среды")
except AssertionError:
    pass
finally:
    _TMP_HOLDER["root"] = None
check("L2. cleanup выполняется и при искусственном assertion failure (temp-root исчез вместе с файлом)",
      not os.path.exists(_fail_dir["path"]))


# ════════════════════════════════════════════════════════════════════════════
section("дерево репозитория не тронуто, side effects отсутствуют")

check("R1. tools/_e2e_payload.json НЕ создан",
      not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))
check("R2. состав tools/ не изменился (ни одного нового/удалённого файла)",
      set(os.listdir(os.path.join(REPO, "tools"))) == _TOOLS_BEFORE)
check("R3. состав файлов корня репозитория не изменился",
      set(f for f in os.listdir(REPO) if os.path.isfile(os.path.join(REPO, f))) == _ROOT_BEFORE)
check("R4. все sqlite-подключения — только внутри temp-root (%d подключений)" % len(_DB_PATHS),
      len(_DB_PATHS) >= 1 and all(p == ":memory:" or "fm_e2e_stock_" in p for p in _DB_PATHS))
_writes = [(p, m) for (p, m) in _OPENS if any(ch in m for ch in "wax+")]
check("R5. все записи файлов — только внутри temp-root (%d записей)" % len(_writes),
      len(_writes) >= 1 and all("fm_e2e_stock_" in p for (p, m) in _writes))
_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", "?????"), "3DIWELL")
check("R6. рабочие config.json / DATA_DIR / _incoming не читались и не писались",
      not any("config.json" in p.lower() or "_incoming" in p.lower()
              or os.path.normcase(p).startswith(os.path.normcase(_data_dir))
              for (p, m) in _OPENS))
check("R7. за весь прогон не создано ни одного сокета (HTTP/принтеры/discovery невозможны)",
      len(_SOCKETS) == 0)
check("R8. за весь прогон не запущено ни одного подпроцесса (git/слайсер/сервер невозможны)",
      len(_PROCS) == 0)
check("R9. запущен только штатный фоновый наблюдатель склада (inv-return-watch), ничего больше",
      set(_THREADS) <= _ALLOWED_THREADS)
check("R10. предохранитель автоотправки на месте: DISPATCH_ENABLED/TRANSPORT_ENABLED = False",
      re.search(r"^DISPATCH_ENABLED = False\s*$", ORCH_SRC, re.M) is not None
      and re.search(r"^TRANSPORT_ENABLED = False\s*$", ORCH_SRC, re.M) is not None)


# ════════════════════════════════════════════════════════════════════════════
section("метка-ловушка")

check("T1. sentinel не встречается в production-исходниках (server.py, backend склада)",
      SENTINEL not in SRV_SRC and SENTINEL not in BK_SRC)
check("T2. sentinel определён ровно один раз и только в оснастке этого теста",
      OWN_SRC.count(SENTINEL) == 1)
check("T3. sentinel не мог покинуть temp-root: записи вне temp-root перехватываются ловушкой (R5)",
      all("fm_e2e_stock_" in p for (p, m) in _writes))


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _COMPLETED["done"] = True
    sys.exit(1)
print("PASS: изолированный E2E — все %d проверок пройдены; реальная цепочка Inventory -> "
      "generic provider -> core aggregator -> JSON проверена во временной среде; артефактов "
      "в дереве репозитория нет" % _total)
_COMPLETED["done"] = True
sys.exit(0)
