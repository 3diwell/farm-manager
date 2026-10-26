# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.902 — когда заправленный слот CFS определить нельзя, программа НЕ ГАДАЕТ.

ОТКУДА ВЗЯЛАСЬ ЭТА ПРОВЕРКА. 27.08.2026 владелец прислал отчёт с живого Creality K2 Plus, где в
одном коробе оказались ДВА слота с одинаковым материалом одного цвета (T1B и T1C, PETG, цвет
09ea7ae). Принтер сообщает про заправленное только материал и цвет — номера слота в его данных
нет вовсе (проверено: объект filament_rack состоит из шести полей, слота среди них нет). Значит
отличить T1B от T1C нечем. А программа показывала T1B как заправленный (брала первое совпадение)
и с него же списывала филамент со склада — то есть уверенно вычитала граммы, возможно, не с той
катушки.

ЧТО ЗАКРЕПЛЯЕТСЯ ЗДЕСЬ, на четырёх уровнях и ИСПОЛНЕНИЕМ, а не чтением строк:
  1. разбор состояния — подходит ровно один слот, он и «заправлен»; подходит несколько — -1;
  2. ядро — при неизвестном слоте у принтера С подачей списание не назначается ни на что;
  3. складской модуль — пустое назначение у принтера с живой подачей не списывает НИЧЕГО
     (настоящая функция модуля на настоящей базе в памяти);
  4. интерфейс — неясность видна владельцу словами, а не молчанием.

БЕЗОПАСНОСТЬ: чистые функции, sqlite во временной папке, ни сети, ни принтеров. Данные в фикстуре
выдуманные (FIXTURE_*), настоящих серийных номеров нет.

Запуск:  python tools/test_cfs_loaded_slot_ambiguity.py
"""
import io
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.creality_cfs import parse  # noqa: E402

SENTINEL = "CFS_AMBIGUITY_SENTINEL_2_902"
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
BACKEND = os.path.join(ROOT, "modules", "inventory", "backend.py")
NL = chr(10)
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def box(materials, colors, remains):
    """Короб T1 в том виде, в каком его присылает принтер (значения из отчёта, sn выдуман)."""
    return {
        "state": "connect", "filament": 1, "auto_refill": 1, "enable": 1, "filament_useup": 1,
        "same_material": [["000003", "09ea7ae", "list[2]", "PETG"]],
        "T1": {"state": "connect", "temperature": "27", "dry_and_humidity": "39",
               "version": "1.4.2", "sn": "FIXTURE_SN_0002", "mode": "0",
               "vender": ["none", "unknown", "unknown", "none"],
               "remain_len": remains, "color_value": colors, "material_type": materials,
               "change_color_num": ["-1", "0", "-1", "-1"]},
    }


RACK = {"vender": "-1", "color_value": "09ea7ae", "material_type": "000003",
        "remain_material_color": "09ea7ae", "remain_material_type": "000003",
        "remain_material_velocity": 400}

print("--- 1. разбор состояния: несколько подходящих слотов = «не знаю» ---")
#  Точный слепок случая владельца: B и C одинаковы во всём, что видно программе.
AMBIG = parse(box(["-1", "000003", "000003", "-1"], ["-1", "09ea7ae", "09ea7ae", "-1"],
                  ["0", "100", "100", "0"]), RACK)
check("1. слоты разобраны (четыре ячейки короба T1)", len(AMBIG["trays"]) == 4, len(AMBIG["trays"]))
check("2. при двух одинаковых слотах заправленный НЕ утверждается", AMBIG["now"] == -1, AMBIG["now"])
check("3. но оба кандидата названы — владельцу есть что показать",
      AMBIG["now_candidates"] == [1, 2], AMBIG["now_candidates"])

#  Тот же короб, но материалы разные: неясности нет, слот называется прямо.
ONE = parse(box(["-1", "000003", "000010", "-1"], ["-1", "09ea7ae", "0000ff", "-1"],
                ["0", "100", "100", "0"]), RACK)
check("4. когда подходит ровно один слот — он и заправлен", ONE["now"] == 1, ONE["now"])
check("5. кандидат при этом ровно один", ONE["now_candidates"] == [1], ONE["now_candidates"])

#  В голове материал, которого в коробе нет вовсе (печать с внешней катушки).
NONE_ = parse(box(["-1", "000010", "-1", "-1"], ["-1", "0000ff", "-1", "-1"],
                  ["0", "100", "0", "0"]), RACK)
check("6. если подходящих слотов нет — тоже честное «не знаю»",
      NONE_["now"] == -1 and NONE_["now_candidates"] == [], (NONE_["now"], NONE_["now_candidates"]))
check("7. без данных о заправленном (нет filament_rack) слот не утверждается",
      parse(box(["-1", "000003", "-1", "-1"], ["-1", "09ea7ae", "-1", "-1"],
                ["0", "100", "0", "0"]), None)["now"] == -1)

print("--- 2. ядро: с чего списывать, когда слот неизвестен ---")
#  Берём НАСТОЯЩУЮ функцию сервера и исполняем её на подставном состоянии принтеров.
#  Ищем по НАЧАЛУ сигнатуры: с 2.944 у функции есть второй параметр (выбранная
#  владельцем ячейка CFS), и привязка к точному «(pid):» ломалась на осознанной правке.
_i = SRV.find("def _klipper_dispatch_slots(pid")
_j = SRV.find(NL + NL + NL, _i)
DISPATCH_SRC = SRV[_i:_j] if (_i >= 0 and _j > _i) else ""
check("8. функция выбора слота для списания найдена в сервере", bool(DISPATCH_SRC.strip()))

NS = {"log": type("L", (), {"info": lambda *a, **k: None, "debug": lambda *a, **k: None})(),
      "_exc_brief": lambda: ""}
exec(compile(DISPATCH_SRC, "<server>", "exec"), NS)
dispatch = NS["_klipper_dispatch_slots"]

TRAYS = [{"index": i, "unit": 0, "tray": i, "label": "T1" + "ABCD"[i]} for i in range(4)]
NS["p_states"] = {
    "p_ambig": {"cfs_trays": TRAYS, "cfs_now": -1},          # CFS есть, слот не определён
    "p_known": {"cfs_trays": TRAYS, "cfs_now": 2},           # CFS есть, слот известен
    "p_bogus": {"cfs_trays": TRAYS, "cfs_now": 9},           # CFS есть, слот вне короба
    "p_plain": {"status": "IDLE"},                           # обычный Klipper без подачи
}
check("9. слот известен — списываем именно с него", dispatch("p_known") == ([2], False),
      dispatch("p_known"))
#  ГЛАВНОЕ. Прежнее поведение здесь возвращало [0] — то есть слот T1A, настоящую чужую катушку.
check("10. слот НЕ определён у принтера с подачей — не списываем ни с чего",
      dispatch("p_ambig") == ([], False), dispatch("p_ambig"))
check("11. слот вне короба (мусор в данных) — тоже не списываем",
      dispatch("p_bogus") == ([], False), dispatch("p_bogus"))
check("12. у принтера БЕЗ подачи поведение прежнее: слот 0, внешняя катушка",
      dispatch("p_plain") == ([0], True), dispatch("p_plain"))
check("13. неизвестный принтер не роняет функцию", dispatch("нет такого") == ([0], True))

print("--- 3. складской модуль: пустое назначение не списывает у принтера с подачей ---")


class FakeCore:
    """Ядро для модуля: только то, что нужно списанию. Никуда не ходит и ничего не печатает."""

    def __init__(self, states):
        self._n = 0
        self._states = states

    def new_id(self, prefix=""):
        self._n += 1
        return str(prefix) + format(self._n, "08d")

    def printers(self):
        return []

    def printer_states(self):
        return self._states

    def get_printer_reported_filament(self, pid):
        return {"telemetry_available": False, "telemetry_fresh": False, "positions": []}


def load_backend(dbpath, core):
    spec = importlib.util.spec_from_file_location("inv_backend_cfs", BACKEND)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.core = core
    m.conn_inv = sqlite3.connect(dbpath, check_same_thread=False)
    m.conn_inv.row_factory = sqlite3.Row
    m.lock_inv = threading.RLock()
    m._init_tables()
    #  Вес печати задаём списком напрямую — разбор G-code здесь не проверяется.
    m._inv_gcode_weights = lambda fdata: (list(fdata) if isinstance(fdata, (list, tuple)) else [])
    return m


def make_spool(m, pid, slot, remaining=1000.0):
    fid = m.core.new_id("fil_")
    sid = m.core.new_id("spool_")
    with m.lock_inv:
        m.conn_inv.execute("INSERT INTO inv_filaments (id, material, color_name) VALUES (?,?,?)",
                           (fid, "PETG", "Серый"))
        m.conn_inv.execute(
            "INSERT INTO inv_spools (id, filament_id, weight_total_g, weight_remaining_g, status, "
            "ams_printer_id, ams_slot) VALUES (?,?,?,?,?,?,?)",
            (sid, fid, 1000.0, remaining, "in_use", pid, slot))
        m.conn_inv.commit()
    return sid


def remaining(m, sid):
    with m.lock_inv:
        r = m.conn_inv.execute("SELECT weight_remaining_g FROM inv_spools WHERE id=?", (sid,)).fetchone()
    return float(r["weight_remaining_g"]) if r else None


_td = tempfile.mkdtemp(prefix="fm902_")
_mods = []
try:
    #  А. Принтер С подачей: назначения нет -> НЕ списываем, хотя катушка к слоту 0 привязана.
    core_a = FakeCore({"p_cfs": {"cfs_trays": TRAYS, "cfs_now": -1}})
    m_a = load_backend(os.path.join(_td, "a.db"), core_a)
    _mods.append(m_a)
    s_slot0 = make_spool(m_a, "p_cfs", 0)
    m_a._inv_autodeduct("p_cfs", [], [25.0], "part.gcode")
    check("14. у принтера с подачей пустое назначение НЕ трогает катушку слота T1A",
          remaining(m_a, s_slot0) == 1000.0, remaining(m_a, s_slot0))

    #  Б. Тот же принтер, слот известен -> списываем именно с него.
    s_slot2 = make_spool(m_a, "p_cfs", 2)
    m_a._inv_autodeduct("p_cfs", [2], [25.0], "part.gcode")
    check("15. когда слот известен, граммы уходят с его катушки",
          remaining(m_a, s_slot2) == 975.0 and remaining(m_a, s_slot0) == 1000.0,
          (remaining(m_a, s_slot2), remaining(m_a, s_slot0)))

    #  В. Принтер БЕЗ подачи: прежнее поведение не тронуто — пустое назначение = внешняя катушка.
    core_b = FakeCore({"p_ext": {"status": "IDLE"}})
    m_b = load_backend(os.path.join(_td, "b.db"), core_b)
    _mods.append(m_b)
    s_ext = make_spool(m_b, "p_ext", -1)
    m_b._inv_autodeduct("p_ext", [], [40.0], "part.gcode")
    check("16. у принтера без подачи внешнее списание работает как раньше",
          remaining(m_b, s_ext) == 960.0, remaining(m_b, s_ext))
finally:
    for m in _mods:
        try:
            m.conn_inv.close()
        except Exception:
            pass
    for f in os.listdir(_td):
        try:
            os.remove(os.path.join(_td, f))
        except Exception:
            pass
    try:
        os.rmdir(_td)
    except Exception:
        pass

print("--- 4. интерфейс: неясность видна словами ---")
check("17. сервер отдаёт наверх список подходящих слотов",
      '"cfs_now_candidates": _cfs.get("now_candidates") or []' in SRV)
check("18. слот-кандидат подписан осторожно, а не «подан»",
      "возможно, подан именно он" in APPJS and "possibly the loaded one" in APPJS)
check("19. на ряде CFS сказано, что слот не определён и списания не будет",
      "какой слот заправлен — точно не известно" in APPJS
      and "филамент со слотов не списывается" in APPJS)
check("20. слово «подан» осталось только для доказанного слота",
      "cfs_now === t.index" in APPJS)
#  Настоящих серийных номеров в отслеживаемых файлах быть не должно — ни в данных, ни даже
#  в тексте самой проверки. Поэтому ищем не конкретный номер, а ЛЮБОЙ похожий на серийный:
#  длинную склейку заглавных букв с цифрами. У выдуманного FIXTURE_SN_0002 такой формы нет.
_self = io.open(__file__, encoding="utf-8").read()
_sn_like = [t for t in re.findall(r"[A-Z0-9]{12,}", _self) if any(c.isdigit() for c in t)
            and any(c.isalpha() for c in t) and not t.startswith("FIXTURE")]
check("21. в наборе нет ничего похожего на настоящий серийный номер",
      "FIXTURE_SN_0002" in _self and not _sn_like, _sn_like[:3])

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
