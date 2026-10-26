# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Тесты read-only проверки соответствия материала ПРИВЯЗАННОЙ катушки склада материалу, который РЕАЛЬНО
# сообщает Bambu-принтер (Alpha 2.725 / inventory 1.7.14). БЕЗ принтера / сервера / MQTT-соединения.
#
# ЧАСТЬ A — ЯДРО: из server.py ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ исходники (_reported_material_norm / _norm_hex_color /
#   _apply_vt_tray / _printer_reported_filament) и исполняются со стабами p_states/last_seen/STALE_FAIL_S.
#   Проверяется: vt_tray при ams=[]; AMS и vt_tray вместе; частичный отчёт без vt_tray сохраняет прошлое;
#   явный пустой/сброшенный vt_tray очищает; malformed vt_tray не роняет; отсутствующий цвет → null (НЕ
#   "#3f3f46"); external ≠ AMS index 0; offline/stale; reported-геттер НЕ вызывает провайдеры/снимок;
#   read-путь без MQTT publish; get_printer_filament_snapshot и quality/cost НЕ изменены (статически).
#
# ЧАСТЬ B — INVENTORY: backend.py грузится с FakeCore (РЕАЛЬНЫЙ core-getter поверх фикстуры p_states) на
#   ВРЕМЕННОЙ БД; создаются filament/spool + привязка; inv_ams_overview() отдаёт material_check. Правила
#   сравнения: match / material_mismatch / color_mismatch / slot_empty / unknown; регистр и пробелы;
#   «My PETG»≠«PETG» (без алиасов); RRGGBB↔RRGGBBAA; offline/stale → unknown; multi-AMS 1/5/512;
#   external без AMS; AMS slot 0 не спутан с external; non-Bambu без ложной проверки; форма overview цела.
#
# Запуск: python tools/test_material_check.py   (0 = все проверки пройдены)
# ============================================================================
import os, sys, time, importlib.util, sqlite3, tempfile, threading, copy, logging

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
logging.getLogger("fm.mod.inventory").setLevel(logging.CRITICAL)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

fail = 0
def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1

# ═══════════════════════════ ЧАСТЬ A — ЯДРО ═══════════════════════════
core_block = SRC[SRC.index("_REPORT_EMPTY_MAT = ("):SRC.index("\ndef run_bambu(")]
check("A0. извлечён дословный core-блок (нормализация/vt_tray/reported-геттер)",
      "_apply_vt_tray" in core_block and "_printer_reported_filament" in core_block and "_norm_hex_color" in core_block)
check("A0b. в блоке отчётной телеметрии НЕТ MQTT publish/subscribe (read-only)",
      ".publish(" not in core_block and ".subscribe(" not in core_block)

class _Boom:
    """Сентинел: любое обращение/вызов — провал (доказывает, что read-путь их не трогает)."""
    def __getattr__(self, k): raise AssertionError("provider path touched: " + k)
    def __call__(self, *a, **k): raise AssertionError("provider path called")
    def __iter__(self): raise AssertionError("providers iterated")

_pub = {"n": 0}
CNS = {
    "p_states": {}, "last_seen": {}, "STALE_FAIL_S": 60, "STALE_WARN_S": 20, "time": time,
    # если reported-путь вдруг тронет провайдеры/снимок — упадёт немедленно:
    "_aggregate_printer_filament": _Boom(), "_printer_filament_providers": _Boom(),
    "get_printer_filament_snapshot": _Boom(), "_printer_filament_providers_list": _Boom(),
    "log": type("L", (), {"warning": staticmethod(lambda *a, **k: None), "debug": staticmethod(lambda *a, **k: None)})(),
}
exec(core_block, CNS)
rmat = CNS["_reported_material_norm"]; nhex = CNS["_norm_hex_color"]; vt = CNS["_apply_vt_tray"]; rep = CNS["_printer_reported_filament"]

NOW = time.time()

# A1 — нормализация материала
check("A1. материал: 'Empty'/'?'/пусто/None → None; реальный сохраняется (trim)",
      rmat("PETG") == "PETG" and rmat("Empty") is None and rmat("") is None and rmat("?") is None
      and rmat(None) is None and rmat("  PLA ") == "PLA")

# A2 — нормализация цвета: отсутствующий → None, НЕ '#3f3f46'
check("A2. цвет: ''/None → None; 'aabbcc'→'#AABBCC'; RRGGBBAA→#RRGGBB; мусор→None",
      nhex("") is None and nhex(None) is None and nhex("aabbcc") == "#AABBCC"
      and nhex("11223344") == "#112233" and nhex("#00ff00") == "#00FF00" and nhex("zzz") is None)

# A3 — vt_tray разбирается НЕЗАВИСИМО от наличия ams.ams[] (ams=[] всё равно даёт external)
e3 = vt(None, {"ams": [], "vt_tray": {"id": "254", "tray_type": "PETG", "tray_color": "00FF00FF"}})
check("A3. vt_tray разбирается при пустом ams=[] (внешняя есть и без AMS)",
      isinstance(e3, dict) and e3.get("tray_type") == "PETG" and e3.get("tray_color") == "00FF00FF")

# A4 — частичный отчёт БЕЗ vt_tray сохраняет прошлое достоверное значение
prev4 = {"tray_id": "254", "tray_type": "ABS", "tray_color": "112233FF"}
check("A4. частичный отчёт без vt_tray сохраняет прошлое external",
      vt(prev4, {"ams": [{"id": 0, "tray": []}]}) == prev4 and vt(prev4, {}) == prev4 and vt(prev4, None) == prev4)

# A5 — явный пустой/сброшенный vt_tray очищает external
check("A5. явный сброшенный (None) / пустой ({}) vt_tray очищает external (материал → null)",
      vt(prev4, {"vt_tray": None}) == {} and (vt(prev4, {"vt_tray": {}}).get("tray_type") == "" ))

# A6 — malformed vt_tray fail-open (не исключение, мусор не стирает прошлое)
check("A6. malformed vt_tray fail-open: строка/число не роняют, прошлое не стирается",
      vt(prev4, {"vt_tray": "garbage"}) == prev4 and vt(prev4, {"vt_tray": 123}) == prev4 and vt("weird", 42) == "weird")

# A7 — offline: телеметрии нет, не свежо
CNS["p_states"] = {"P": {"status": "OFFLINE"}}; CNS["last_seen"] = {"P": NOW}
r7 = rep("P")
check("A7. offline → telemetry_available False, positions пусто, telemetry_fresh False",
      r7["telemetry_available"] is False and r7["positions"] == [] and r7["telemetry_fresh"] is False)

# A8 — stale (age ≥ STALE_FAIL_S): телеметрия есть, но не свежая
CNS["p_states"] = {"P": {"status": "IDLE", "ams_trays": [
    {"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "#00FF00", "color_raw": "00FF00FF"}]}}
CNS["last_seen"] = {"P": NOW - 120}
r8 = rep("P")
check("A8. stale → telemetry_fresh False при telemetry_available True",
      r8["telemetry_fresh"] is False and r8["telemetry_available"] is True)

# A9 — AMS и vt_tray ОДНОВРЕМЕННО; external НЕ путается с AMS index 0
CNS["p_states"] = {"P": {"status": "IDLE",
    "ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color": "#112233", "color_raw": "112233FF"}],
    "ext_tray": {"tray_type": "ABS", "tray_color": "445566"}}}
CNS["last_seen"] = {"P": NOW}
r9 = rep("P")
amsp = [p for p in r9["positions"] if not p["external"]]; extp = [p for p in r9["positions"] if p["external"]]
check("A9. AMS+vt_tray вместе: external index=None и AMS index=0 — РАЗНЫЕ позиции, не спутаны",
      len(amsp) == 1 and amsp[0]["index"] == 0 and amsp[0]["external"] is False and amsp[0]["reported_material"] == "PLA"
      and len(extp) == 1 and extp[0]["external"] is True and extp[0]["index"] is None and extp[0]["reported_material"] == "ABS")

# A10 — отсутствующий tray_color → reported_color None (НЕ '#3f3f46')
CNS["p_states"] = {"P": {"status": "IDLE", "ams_trays": [
    {"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "#3f3f46", "color_raw": ""}]}}
CNS["last_seen"] = {"P": NOW}
check("A10. отсутствующий цвет: reported_color None, НЕ UI-fallback '#3f3f46'",
      rep("P")["positions"][0]["reported_color"] is None)

# A11 — пустой физический слот (type 'Empty') → present False, material None
CNS["p_states"] = {"P": {"status": "IDLE", "ams_trays": [
    {"index": 1, "unit": 0, "tray": 1, "type": "Empty", "color": "#3f3f46", "color_raw": ""}]}}
CNS["last_seen"] = {"P": NOW}
r11 = rep("P")["positions"][0]
check("A11. пустой слот → present False, reported_material None",
      r11["present"] is False and r11["reported_material"] is None)

# A12 — multi-AMS индексы 1, 5, 512 (обычный / второй unit / AMS HT)
CNS["p_states"] = {"P": {"status": "IDLE", "ams_trays": [
    {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color": "", "color_raw": ""},
    {"index": 5, "unit": 1, "tray": 1, "type": "PETG", "color": "", "color_raw": ""},
    {"index": 512, "unit": 128, "tray": 0, "type": "ABS", "color": "", "color_raw": ""}]}}
CNS["last_seen"] = {"P": NOW}
byidx = {p["index"]: p for p in rep("P")["positions"]}
check("A12. multi-AMS: 1(unit0/tray1), 5(unit1/tray1), 512(unit128/tray0) — верные unit/tray/материал",
      byidx[1]["unit"] == 0 and byidx[1]["tray"] == 1 and byidx[5]["unit"] == 1 and byidx[5]["reported_material"] == "PETG"
      and byidx[512]["unit"] == 128 and byidx[512]["tray"] == 0 and byidx[512]["reported_material"] == "ABS")

# A13 — reported-геттер НЕ вызывает провайдеры/агрегатор/снимок (нет рекурсии): РАНТАЙМ (rep() выше отработал
# при _Boom-сентинелах в CNS для этих имён — обращение бросило бы AssertionError) + нет call-синтаксиса в теле.
repfn = core_block[core_block.index("def _printer_reported_filament("):]
check("A13. reported-геттер НЕ вызывает провайдеры/агрегатор/get_printer_filament_snapshot (рантайм _Boom не упал + нет call-синтаксиса)",
      "_aggregate_printer_filament(" not in repfn and "get_printer_filament_snapshot(" not in repfn
      and "_printer_filament_providers" not in repfn)

# A14 — read-путь без MQTT publish (у функций отчётной телеметрии нет publish-поверхности)
_ = rep("P"); _ = vt(None, {"vt_tray": {"tray_type": "PLA"}})
check("A14. runtime MQTT publish counter == 0 на всём read-пути отчётной телеметрии", _pub["n"] == 0)

# A15 — on_msg аддитивно: color_raw в ams_trays; внешние катушки с уровня print (vir_slot/vt_tray) в ext_trays,
# основная (255) — в ext_tray, который читает склад; оба поля в p_states.
#  16.10.2026 (R-139): разбор слотов AMS переехал в чистый модуль app/bambu_ams_state.py — color_raw
#  проверяется ИСПОЛНЕНИЕМ этого разбора (on_msg зовёт его же), внешние катушки — как прежде.
sys.path.insert(0, REPO)
from app import bambu_ams_state as _bams_mod   # noqa: E402
_ms = _bams_mod.merge({}, {"ams": [{"id": "0", "tray": [{"id": "1", "tray_type": "PLA", "tray_color": "FF8000FF"}]}]}, 0.0)
_t1 = next((t for t in _ms["ams_trays"] if t["index"] == 1), {})
check("A15. on_msg: color_raw в ams_trays (исполнением разбора); внешние катушки из print -> ext_trays; основная (255) -> ext_tray",
      _t1.get("color_raw") == "FF8000FF" and _t1.get("color") == "#FF8000"
      and "_bams.merge(" in SRC
      and '_bambu_ext_slots(ext_trays, d, dual=' in SRC
      and 'ext_tray = ext_trays[_BAMBU_EXT_MAIN]' in SRC
      and '"ext_tray": ext_tray, "ext_trays": ext_trays' in SRC)

# A15b-A15i — формы отчётов настоящих принтеров (BambuStudio DeviceManager.cpp: jj = j["print"], vir_slot
# главнее vt_tray; ha-bambulab mock_data). Серийники и коды не нужны — только блок катушек.
xs = CNS["_bambu_ext_slots"]
_p1p = {"ams": {"ams": [], "tray_now": "254"},
        "vt_tray": {"id": "254", "tray_info_idx": "GFG99", "tray_type": "PETG", "tray_color": "FFFFFFFF"}}
_s = xs({}, _p1p)
check("A15b. P1P без AMS: print.vt_tray PETG -> основная внешняя (255) PETG, хотя id в отчёте «254»",
      _s.get("255", {}).get("tray_type") == "PETG" and "254" not in _s)
_s = xs({}, {"vir_slot": [{"id": "255", "tray_type": "PETG", "tray_color": "00FF00FF"}]})
check("A15c. P2S: только print.vir_slot [255 PETG] -> основная внешняя PETG",
      _s.get("255", {}).get("tray_type") == "PETG")
_s = xs({}, {"vir_slot": [{"id": "254", "tray_type": "PLA"}, {"id": 255, "tray_type": "TPU"}],
             "vt_tray": {"id": "255", "tray_type": "ABS"}})
check("A15d. H2D: vir_slot 254 PLA + 255 TPU (id строкой и числом), vt_tray рядом не перебивает vir_slot",
      _s.get("254", {}).get("tray_type") == "PLA" and _s.get("255", {}).get("tray_type") == "TPU")
_s = xs({}, {"vt_tray": {"id": "255", "tray_type": "", "tray_color": ""}})
check("A15e. X1C без катушки: пустой tray_type -> материала нет (не угадывается)",
      _s.get("255", {}).get("tray_type") == "" and rmat(_s["255"]["tray_type"]) is None)
_prev = {"255": {"tray_type": "PLA"}, "254": {"tray_type": "PETG"}}
check("A15f. частичный отчёт без катушек сохраняет обе; vir_slot только с 255 не трогает 254",
      xs(_prev, {"mc_percent": 5}) == _prev
      and xs(_prev, {"vir_slot": [{"id": "255", "tray_type": "ABS"}]}).get("254", {}).get("tray_type") == "PETG")
check("A15g. явный None у vt_tray очищает основную; мусор и не-словарь отчёт не роняют и не стирают",
      xs(_prev, {"vt_tray": None}).get("255") == {} and xs(_prev, {"vir_slot": "garbage"}) == _prev
      and xs(_prev, None) == _prev and xs(_prev, {"vt_tray": 123}) == _prev)
check("A15h. прежняя форма (vt_tray внутри print.ams) понимается как запасная",
      xs({}, {"ams": {"vt_tray": {"tray_type": "ASA"}}}).get("255", {}).get("tray_type") == "ASA")
# A15k/A15l (16.10.2026, R-137) — двухсопельный: H2 шлёт в vt_tray АКТИВНУЮ катушку (наблюдение Bambuddy),
# и одиночный vt_tray больше не переписывает правую (255), когда левая (254) уже известна из vir_slot.
_h2 = {"254": {"tray_type": "PLA"}, "255": {"tray_type": "PETG"}}
check("A15k. H2D: одиночный vt_tray с id «254» обновляет ЛЕВУЮ катушку, правая не тронута; без id — пропускается",
      xs(_h2, {"vt_tray": {"id": "254", "tray_type": "ABS"}}, dual=True) == {"254": {"tray_id": "254", "tray_type": "ABS",
                                                                                  "tray_color": "", "tray_info_idx": ""},
                                                                         "255": {"tray_type": "PETG"}}
      and xs(_h2, {"vt_tray": {"tray_type": "ABS"}}, dual=True) == _h2)
check("A15l. односопельный (dual=False) — по-прежнему одиночный vt_tray = основная (255), как у Bambu Studio",
      xs(_h2, {"vt_tray": {"id": "254", "tray_type": "ABS"}}).get("255", {}).get("tray_type") == "ABS")
CNS["p_states"] = {"H": {"status": "IDLE", "nozzle_count": 2, "ams_trays": [],
                         "ext_tray": {"tray_type": "PETG", "tray_color": ""},
                         "ext_trays": {"254": {"tray_type": "PLA", "tray_color": "FF0000FF"},
                                       "255": {"tray_type": "PETG", "tray_color": ""}}},
                   "S": {"status": "IDLE", "nozzle_count": 1, "ams_trays": [],
                         "ext_tray": {"tray_type": "PETG", "tray_color": ""},
                         "ext_trays": {"254": {"tray_type": "PLA"}, "255": {"tray_type": "PETG"}}}}
CNS["last_seen"] = {"H": NOW, "S": NOW}
_rh, _rs = rep("H"), rep("S")
check("A15m. H2D: левая внешняя — отдельным ключом ext_left (PLA, «setting»), в positions по-прежнему одна внешняя (правая)",
      (_rh.get("ext_left") or {}).get("reported_material") == "PLA" and _rh["ext_left"]["presence"] == "setting"
      and _rh["ext_left"].get("ext_id") == 254
      and [x["reported_material"] for x in _rh["positions"] if x["external"]] == ["PETG"]
      and "ext_left" not in _rs)

# A15i/A15j — внешняя катушка P1P доходит до склада, но помечена как НАСТРОЙКА экрана, а не показание датчика:
# её тип выбирают на принтере, и он остаётся, когда катушка кончилась. Склад по такой пометке замену катушки
# не делает (tools/test_inventory_preflight_tiers.py, уровень 2) — поэтому заполнять ext_tray снова безопасно.
CNS["p_states"] = {"P": {"status": "IDLE", "ams_trays": [], "ext_tray": xs({}, _p1p)["255"]}}
CNS["last_seen"] = {"P": NOW}
_ex = [p for p in rep("P")["positions"] if p["external"]]
check("A15i. внешняя катушка P1P видна складу и помечена presence='setting' (выбор на экране, не датчик)",
      len(_ex) == 1 and _ex[0]["reported_material"] == "PETG" and _ex[0]["presence"] == "setting"
      and rep("P")["telemetry_available"] is True)

CNS["p_states"] = {"P": {"status": "IDLE",
    "ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color": "", "color_raw": ""}],
    "ext_tray": {"tray_type": "PETG", "tray_color": ""}}}
CNS["last_seen"] = {"P": NOW}
_byext = {bool(p["external"]): p for p in rep("P")["positions"]}
check("A15j. слот AMS помечен presence='sensor', внешняя — 'setting'; прежние поля не изменились",
      _byext[False]["presence"] == "sensor" and _byext[True]["presence"] == "setting"
      and _byext[False]["present"] is True and _byext[True]["present"] is True
      and _byext[False]["reported_material"] == "PLA" and _byext[True]["reported_material"] == "PETG")

# A16 — get_printer_filament_snapshot НЕ изменён (нет reported_* и нового геттера в теле)
snap_fn = SRC[SRC.index("def get_printer_filament_snapshot("):SRC.index("def get_printer_reported_filament(")]
check("A16. get_printer_filament_snapshot без изменений (только _aggregate; без reported_material/_printer_reported)",
      "_aggregate_printer_filament" in snap_fn and "reported_material" not in snap_fn and "_printer_reported_filament" not in snap_fn)

# A17 — quality НЕ тронут: использует старый снимок, не новый геттер. cost с 3.0 — «Расчёт заказа»:
# снимок ядра он не использует вовсе (цены материалов его окно берёт у склада) и геттер тоже не трогает.
qsrc = open(os.path.join(REPO, "modules", "quality", "backend.py"), encoding="utf-8").read()
csrc = open(os.path.join(REPO, "modules", "cost", "backend.py"), encoding="utf-8").read()
check("A17. quality использует get_printer_filament_snapshot; quality и cost НЕ трогают get_printer_reported_filament",
      "get_printer_filament_snapshot" in qsrc
      and "get_printer_reported_filament" not in qsrc and "get_printer_reported_filament" not in csrc)

# ═══════════════════════════ ЧАСТЬ B — INVENTORY ═══════════════════════════
BACKEND = os.path.join(REPO, "modules", "inventory", "backend.py")

class FakeCore:
    """core для модуля: реальный reported-геттер (extracted _printer_reported_filament) поверх фикстуры p_states."""
    def __init__(self):
        self._n = 0; self.printers_list = []; self.pstates = {}; self.lastseen = {}
    def new_id(self, prefix=""):
        self._n += 1; return str(prefix) + format(self._n, "08d")
    def printers(self):
        return [dict(p) for p in self.printers_list]
    def printer_states(self):
        return self.pstates
    def get_printer_reported_filament(self, pid):
        CNS["p_states"] = self.pstates; CNS["last_seen"] = self.lastseen
        return copy.deepcopy(rep(pid))

def load_backend(dbpath, fake):
    spec = importlib.util.spec_from_file_location("inv_backend_mck", BACKEND)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.core = fake
    m.conn_inv = sqlite3.connect(dbpath, check_same_thread=False)
    m.conn_inv.row_factory = sqlite3.Row
    m.lock_inv = threading.RLock()
    m._init_tables()
    return m

fake = FakeCore()
_tmp = tempfile.mkdtemp(prefix="mck_")
m = load_backend(os.path.join(_tmp, "inv.db"), fake)

def add_printer(pid, ptype="bambu"):
    fake.printers_list.append({"id": pid, "name": pid, "type": ptype})

def mkbind(mat, hexc, pid, slot):
    fid = m.inv_create_filament({"material": mat, "color_hex": hexc or ""})
    sid = m.inv_create_spool({"filament_id": fid, "weight_total_g": 1000, "weight_remaining_g": 800})["id"]
    m.inv_bind_spool(sid, pid, slot)
    return sid

def ams_tray(index, unit, tray, ttype, color_raw=""):
    return {"index": index, "unit": unit, "tray": tray, "type": ttype,
            "color": ("#" + color_raw[:6]) if color_raw else "#3f3f46", "color_raw": color_raw}

# ── принтеры и сценарии (каждый — свой принтер, чтобы проверки не мешали друг другу) ──
add_printer("MATCH");   mkbind("PETG", "00FF00", "MATCH", 0)
fake.pstates["MATCH"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "PETG", "00FF00FF")]}

add_printer("CASE");    mkbind("PETG", "", "CASE", 0)
fake.pstates["CASE"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "  petg ", "")]}

add_printer("MMAT");    mkbind("PETG", "", "MMAT", 0)
fake.pstates["MMAT"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "ABS", "")]}

add_printer("MYPETG");  mkbind("My PETG", "", "MYPETG", 0)
fake.pstates["MYPETG"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "PETG", "")]}

add_printer("COLOR");   mkbind("PETG", "00FF00", "COLOR", 0)
fake.pstates["COLOR"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "PETG", "FF0000FF")]}

add_printer("CALPHA");  mkbind("PETG", "00FF00", "CALPHA", 0)
fake.pstates["CALPHA"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "PETG", "00FF0080")]}

add_printer("NOCOLOR"); mkbind("PETG", "00FF00", "NOCOLOR", 0)
fake.pstates["NOCOLOR"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "PETG", "")]}

add_printer("EMPTY");   mkbind("PETG", "", "EMPTY", 0)
fake.pstates["EMPTY"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "Empty", "")]}

add_printer("STALE");   mkbind("PETG", "", "STALE", 0)
fake.pstates["STALE"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "PETG", "")]}

add_printer("OFFLN");   mkbind("PETG", "", "OFFLN", 0)
fake.pstates["OFFLN"] = {"status": "OFFLINE"}

# external без AMS (ext_tray, нет ams_trays) — inv_ams_overview создаёт синтетический external slot 0
add_printer("EXT");     mkbind("PETG", "00FF00", "EXT", 0)
fake.pstates["EXT"] = {"status": "IDLE", "ext_tray": {"tray_type": "PETG", "tray_color": "00FF00FF"}}

add_printer("EXTMM");   mkbind("PETG", "", "EXTMM", 0)
fake.pstates["EXTMM"] = {"status": "IDLE", "ext_tray": {"tray_type": "ABS", "tray_color": ""}}

# AMS slot 0 занят + ext_tray другого материала: слот 0 должен сравниваться с AMS (PETG), НЕ с external (ABS)
add_printer("AMS0");    mkbind("PETG", "", "AMS0", 0)
fake.pstates["AMS0"] = {"status": "IDLE", "ams_trays": [ams_tray(0, 0, 0, "PETG", "")],
                        "ext_tray": {"tray_type": "ABS", "tray_color": ""}}

# multi-AMS: слоты 1, 5, 512
add_printer("MULTI")
mkbind("PLA", "", "MULTI", 1); mkbind("PETG", "", "MULTI", 5); mkbind("ABS", "", "MULTI", 512)
fake.pstates["MULTI"] = {"status": "IDLE", "ams_trays": [
    ams_tray(1, 0, 1, "PLA", ""), ams_tray(5, 1, 1, "PETG", ""), ams_tray(512, 128, 0, "ABS", "")]}

# non-Bambu (klipper) — проверка НЕ выполняется
add_printer("KLIP", "klipper"); mkbind("PETG", "", "KLIP", 0)
fake.pstates["KLIP"] = {"status": "IDLE", "ext_tray": {"tray_type": "ABS", "tray_color": ""}}

for pid in fake.pstates:
    if pid != "OFFLN":
        fake.lastseen[pid] = NOW
fake.lastseen["STALE"] = NOW - 120
fake.lastseen["OFFLN"] = NOW

ov = m.inv_ams_overview()
def prow(pid):
    for p in ov["printers"]:
        if p["printer_id"] == pid:
            return p
    return None
def bound_slot(pid):
    p = prow(pid)
    for s in (p["slots"] if p else []):
        if s.get("spool"):
            return s
    return None
def mc(pid):
    s = bound_slot(pid)
    return (s or {}).get("material_check") or {}
def slot_by_index(pid, idx):
    for s in prow(pid)["slots"]:
        if s.get("index") == idx and s.get("spool"):
            return s
    return None

# B1 — базовый match
check("B1. PETG ↔ PETG (+совпавший цвет) → match", mc("MATCH")["status"] == "match")
# B2 — регистр и лишние пробелы не создают mismatch
check("B2. 'PETG' ↔ '  petg ' → match (регистр/пробелы нормализованы)", mc("CASE")["status"] == "match")
# B3 — разные материалы
check("B3. PETG ↔ ABS → material_mismatch (reported_material='ABS')",
      mc("MMAT")["status"] == "material_mismatch" and mc("MMAT")["reported_material"] == "ABS")
# B4 — без алиасов
check("B4. 'My PETG' ↔ 'PETG' → material_mismatch (базовый материал не угадываем)",
      mc("MYPETG")["status"] == "material_mismatch")
# B5 — тот же материал, разные валидные цвета
check("B5. PETG совпал, цвета #00FF00 vs #FF0000 → color_mismatch",
      mc("COLOR")["status"] == "color_mismatch")
# B6 — RRGGBB ↔ RRGGBBAA (тот же RGB) → match (alpha игнор)
check("B6. цвет RRGGBB ↔ RRGGBBAA (тот же RGB) → match (alpha принтера игнорируется)",
      mc("CALPHA")["status"] == "match")
# B7 — отсутствующий цвет не превращается в mismatch
check("B7. материал совпал, у принтера нет цвета → match (не color_mismatch)",
      mc("NOCOLOR")["status"] == "match" and mc("NOCOLOR")["reported_color"] is None)
# B8 — пустой физический слот
check("B8. принтер сообщает пустой слот, катушка привязана → slot_empty",
      mc("EMPTY")["status"] == "slot_empty")
# B9 — stale → unknown
check("B9. устаревшая телеметрия → unknown (ложный match/mismatch исключён)",
      mc("STALE")["status"] == "unknown")
# B10 — offline → unknown
check("B10. offline → unknown", mc("OFFLN")["status"] == "unknown")
# B11 — external без AMS: match
#  16.09.2026: материал внешней катушки — настройка экрана принтера, а не показание датчика:
#  сверка по нему ничего не утверждает (ни match, ни mismatch), иначе синхронизация цвета
#  переписала бы каталог филамента цветом снятой катушки.
check("B11. внешняя катушка без AMS (vt_tray): сверка честно молчит — это настройка экрана, не датчик",
      bound_slot("EXT").get("external") is True and mc("EXT")["status"] == "unknown"
      and mc("EXT")["reason"] == "printer_setting_only")
# B12 — по той же причине не утверждается и НЕСОВПАДЕНИЕ: экран помнит снятую катушку, а не
#       показывает заправленную. Материал при этом виден — просто выводов по нему не делаем.
check("B12. внешняя катушка PETG, принтер показывает ABS → вывод не делается (материал виден)",
      mc("EXTMM")["status"] == "unknown" and mc("EXTMM")["reason"] == "printer_setting_only"
      and mc("EXTMM")["reported_material"] == "ABS")
# B13 — AMS slot 0 не спутан с external
check("B13. AMS slot 0 (PETG) сравнивается с AMS, НЕ с external (ABS) → match",
      slot_by_index("AMS0", 0).get("external") is not True and mc("AMS0")["status"] == "match")
# B14 — multi-AMS 1/5/512
check("B14. multi-AMS: слоты 1(PLA), 5(PETG), 512(ABS) → все match по своим позициям",
      slot_by_index("MULTI", 1)["material_check"]["status"] == "match"
      and slot_by_index("MULTI", 5)["material_check"]["status"] == "match"
      and slot_by_index("MULTI", 512)["material_check"]["status"] == "match")
# B15 — non-Bambu без ложной проверки
check("B15. non-Bambu (klipper): material_check НЕ добавляется (существующий UI не меняется)",
      "material_check" not in (bound_slot("KLIP") or {}))
# B16 — форма overview обратно совместима (material_check аддитивен)
s16 = bound_slot("MATCH")
check("B16. форма overview цела: index/unit/tray/type/color/spool на месте, material_check аддитивен",
      all(k in s16 for k in ("index", "unit", "tray", "type", "color", "spool"))
      and set(mc("MATCH").keys()) == {"status", "reason", "expected_material", "reported_material",
                                       "expected_color", "reported_color", "checked_at",
                                       # 1.7.22: аддитивно, старые ключи не тронуты
                                       "color_distance", "color_relation"})
# B17 — expected/reported заполнены для tooltip
check("B17. material_check несёт expected/reported для tooltip",
      mc("MATCH")["expected_material"] == "PETG" and mc("MATCH")["reported_material"] == "PETG"
      and mc("MMAT")["expected_material"] == "PETG" and mc("MMAT")["reported_material"] == "ABS")

print()
print(("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if fail == 0 else ("ПРОВАЛЕНО ПРОВЕРОК: " + str(fail))))
sys.exit(1 if fail else 0)
