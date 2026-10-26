# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.10.2026 (R-139, R-116, R-006) — состояние AMS Bambu: снятый AMS, наличие лотка, сопло блока.

ЗАЧЕМ. Аудит 08.10.2026 (R-139) нашёл по коду: ПУСТОЙ список print.ams.ams — то, чем прошивка
сообщает, что AMS сняли, — разбор пропускал, и слоты снятого AMS жили в программе до перезапуска.
Запуск слал use_ams=true с картой слотов принтеру без AMS (ответ прошивки — «Failed to get AMS
mapping table», печать встаёт на паузу), а склад видел «заправленные» слоты. Наличие лотка по
датчику подачи (tray_exist_bits) не читалось: пустой слот с типом от прошлой катушки считался
заправленным (R-116), а короткий словарь лотка {id, state} затирал материал на «Empty».

КОНТРАКТ — исходники Bambu Studio (DevFilaSystem.cpp ParseV1_0, ParseAmsInfo) и открытые
интеграции: ha-bambulab (PR #2113 — первый отчёт после подключения бывает с пустым списком при
живом AMS; issue #2164 — пустой слот голым {"id"}; tests/pybambu/H2D.json — настоящий отчёт H2D:
ams_exist_bits «11», tray_exist_bits «1000f», info AMS 0 «1101», HT 128 «2004»), printforce-link
PR #21 (маска бывает целым числом; «a missing bitmask is not an unload»). Отчёты здесь собраны по
этим описаниям; серийники и коды доступа — выдуманные.

КАК. Сервер не импортируется: из server.py ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ исходники — сам обработчик отчёта
on_msg (вложен в run_bambu), _printer_reported_filament, _qw_printer_feed и блок подбора слотов с
_bambu_resolve_ams — и исполняются в песочнице с настоящими чистыми модулями. Так проверяется весь
путь «отчёт принтера -> состояние -> что видят запуск и склад». Ни сети, ни базы, ни принтеров.

Запуск:  python tools/test_bambu_ams_presence.py      (0 = все проверки пройдены)
"""
import ast
import io
import json
import os
import re
import sys
import textwrap
import time as _real_time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
SENTINEL = "BAMBU_AMS_PRESENCE_SENTINEL_R139"

from app import project_orchestrator as _orch          # noqa: E402
from app import bambu_start_policy as _bstart          # noqa: E402
from app import printer_health_policy as _health       # noqa: E402
from app import bambu_slot_match as _bslot             # noqa: E402
from app import bambu_ams_state as _bams               # noqa: E402

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:400]) if detail else ""))


def _slice(a, b):
    i = SRC.index(a)
    return SRC[i:SRC.index(b, i)]


class _Log:
    def __init__(self):
        self.lines = []

    def _w(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(str(a))

    info = debug = warning = error = _w


class _Clock:
    """Подменное время: on_msg берёт монотонные секунды для выдержки снятия блока."""
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def time(self):
        return _real_time.time()

    def sleep(self, s):
        self.t += s


CLOCK = _Clock()
LOG = _Log()
HANDLED = []

# ── Песочница: ДОСЛОВНЫЕ исходники из server.py ─────────────────────────────────────────────
NS = {"log": LOG, "_exc_brief": (lambda: "test"), "time": CLOCK, "os": os, "re": re, "json": json,
      "p_states": {}, "last_seen": {}, "STALE_FAIL_S": 60.0, "bambu_serials": {}, "_bambu_cmd_ack": {},
      "_bambu_print_path": {}, "_last_active_ts": {}, "_user_stopped": {}, "_cancel_latch": {},
      "_CANCEL_RECENT_ACTIVE_S": 300.0, "_bstart": _bstart, "_health": _health, "_bams": _bams,
      "_bslot": _bslot, "_orch": _orch,
      "handle_state": (lambda pid, st, fn: HANDLED.append((pid, st, fn)))}
exec("_PLATE_RE = re.compile(r\"(?i)^plate[_\\s-]?\\d+$\")", NS)
exec(_slice("def _best_bambu_name(", "\n_pjob_log_seen"), NS)
#  _reported_material_norm, _norm_hex_color, _apply_vt_tray, _bambu_ext_slots, коды HMS,
#  _printer_reported_filament — одним блоком, как в tools/test_material_check.py.
exec(_slice("_REPORT_EMPTY_MAT = (", "\ndef run_bambu("), NS)

_tree = ast.parse(SRC)
_run = next(n for n in _tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_bambu")
_onmsg = next(n for n in ast.walk(_run) if isinstance(n, ast.FunctionDef) and n.name == "on_msg")
_onmsg_src = textwrap.dedent(ast.get_source_segment(SRC, _onmsg, padded=True))
exec("def _make_on_msg(pid):\n" + textwrap.indent(_onmsg_src, "    ") + "\n    return on_msg\n", NS)

#  Подбор слотов и выбор источника подачи запуска — блок _bambu_tray2 … _bambu_resolve_ams.
exec(_slice("def _bambu_tray2(", "\ndef _apply_bambu_print_opts("), NS)
REQ = {"fils": [], "map": [0]}
NS["_3mf_filament_requirements"] = lambda fdata: {"filament_count": len(REQ["fils"]), "filaments": list(REQ["fils"])}
NS["_bambu_ams_mapping"] = lambda fdata: (True, list(REQ["map"]))
NS["_3mf_plate_used"] = lambda fdata: {"ok": False}
NS["_3mf_filament_sides"] = lambda fdata: dict(REQ.get("sides") or {"ok": False})
#  Позиции подачи для очереди.
_feed_src = next(ast.get_source_segment(SRC, n) for n in _tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == "_qw_printer_feed")
exec(_feed_src, NS)
check("0. извлечены дословные исходники: on_msg из run_bambu, телеметрия склада, подбор слотов, подача очереди",
      callable(NS.get("_make_on_msg")) and callable(NS.get("_printer_reported_filament"))
      and callable(NS.get("_bambu_resolve_ams")) and callable(NS.get("_qw_printer_feed")))

PID = "node_fixture"


class _Msg:
    def __init__(self, printd):
        self.topic = "device/FIXTURE_SERIAL/report"
        self.payload = json.dumps({"print": printd}).encode("utf-8")


def feed(printd, pid=PID):
    NS["_make_on_msg"](pid)(None, None, _Msg(printd))
    return NS["p_states"].get(pid) or {}


def reset(pid=PID):
    NS["p_states"].pop(pid, None)
    NS["last_seen"].pop(pid, None)


def tray_d(tid, ttype, color="FFFFFFFF", remain=80, fid="GFA00"):
    return {"id": str(tid), "tray_type": ttype, "tray_color": color, "remain": remain,
            "tray_info_idx": fid, "state": 11}


def by_index(st):
    return {t["index"]: t for t in (st.get("ams_trays") or [])}


P1P_AMS = {"ams": [{"id": "0", "humidity": "4", "temp": "0.0",
                    "tray": [tray_d(0, "PLA", "FF0000FF"), tray_d(1, "PETG", "00FF00FF", fid="GFG00"),
                             tray_d(2, "PLA", "0000FFFF", remain=-1), tray_d(3, "ABS", "000000FF", fid="GFB00")]}],
           "ams_exist_bits": "1", "tray_exist_bits": "f", "tray_now": "255", "tray_tar": "255", "version": 4}

print("--- 1. полный отчёт: четыре слота, поля прежние ---")
reset()
st = feed({"gcode_state": "IDLE", "ams": P1P_AMS, "hw_switch_state": 1,
           "vt_tray": {"id": "254", "tray_type": "PETG", "tray_color": "FFFFFFFF", "tray_info_idx": "GFG99"}})
bi = by_index(st)
check("1e. (R-115) filament_id внешней катушки сохраняется рядом с её материалом",
      ((st.get("ext_trays") or {}).get("255") or {}).get("tray_info_idx") == "GFG99"
      and (st.get("ext_tray") or {}).get("tray_type") == "PETG", st.get("ext_trays"))
check("1. полный отчёт P1P: четыре слота с прежними номерами 0..3", sorted(bi) == [0, 1, 2, 3], sorted(bi))
check("1b. поля слота прежние (тип, цвет, сырой цвет, остаток; -1 -> «не знаю»)",
      bi[0]["type"] == "PLA" and bi[0]["color"] == "#FF0000" and bi[0]["color_raw"] == "FF0000FF"
      and bi[0]["remain"] == 80 and bi[2]["remain"] is None and bi[1]["unit"] == 0 and bi[1]["tray"] == 1, bi.get(0))
check("1c. новое: лоток на месте по датчику подачи, filament_id слота, маски у принтера",
      all(t.get("present") is True for t in bi.values()) and bi[1].get("tray_info_idx") == "GFG00"
      and st.get("ams_exist_bits") == 1 and st.get("tray_exist_bits") == 15, (bi.get(1), st.get("tray_exist_bits")))
check("1d. tray_now 255 (внешняя) -> ams_now -1, как и раньше", st.get("ams_now") == -1, st.get("ams_now"))

print("--- 2. AMS сняли: пустой список и сброшенные биты дважды, с выдержкой ---")
REQ.update({"fils": [{"material": "PLA", "color_hex": "#FF0000"}], "map": [0]})
CLOCK.t = 2000.0
st = feed({"ams": {"ams": [], "ams_exist_bits": "0", "tray_exist_bits": "0"}})
check("2. ОДИН отчёт с пустым списком слоты не снимает (ha-bambulab PR #2113)",
      sorted(by_index(st)) == [0, 1, 2, 3], sorted(by_index(st)))
check("2a. но датчик подачи уже сказал «лотков нет»: ни один слот не present",
      all(t.get("present") is False for t in st["ams_trays"]), [t.get("present") for t in st["ams_trays"]])
use, mp, mp2 = NS["_bambu_resolve_ams"](PID, None, b"fake3mf")
check("2b. пока снятие не подтверждено, подбор не отправляет печать в слот без лотка (остаётся карта файла)",
      use is True and mp == [0], (use, mp))
CLOCK.t = 2004.0
st = feed({"ams": {"ams": [], "ams_exist_bits": "0", "tray_exist_bits": "0"}})
check("2c. второй такой отчёт раньше 10 секунд — ещё не снятие", len(st["ams_trays"]) == 4, len(st["ams_trays"]))
CLOCK.t = 2012.0
st = feed({"ams": {"ams": [], "ams_exist_bits": "0", "tray_exist_bits": "0"}})
check("2d. подтверждено через 12 с — слотов снятого AMS больше нет", st.get("ams_trays") == [], st.get("ams_trays"))
use, mp, mp2 = NS["_bambu_resolve_ams"](PID, None, b"fake3mf")
check("2e. КОРЕНЬ R-139: запуск уходит с внешней катушки — (False, [-1], [{255, 0}]), а не с картой AMS",
      (use, mp, mp2) == (False, [-1], [{"ams_id": 255, "slot_id": 0}]), (use, mp, mp2))
rep = NS["_printer_reported_filament"](PID)
#  16.10.2026 (после проверки пакета): слоты снятого AMS склад видит ПУСТЫМИ позициями с пометкой removed —
#  не «заправлены» и не исчезли бесследно. Иначе склад решал «AMS у принтера нет вовсе» и включал старое
#  правило «внешняя катушка = слот 0»: печать с внешней катушки списывалась с катушки слота 0 снятого AMS.
_ext = [p for p in rep["positions"] if p["external"]]
_gone = [p for p in rep["positions"] if not p["external"]]
check("2f. склад: внешняя подача — как раньше; слоты снятого AMS — пустыми позициями с пометкой removed",
      len(_ext) == 1 and sorted(p["index"] for p in _gone) == [0, 1, 2, 3]
      and all(p.get("removed") is True and p["present"] is False and p["reported_material"] is None
              and p["presence"] == "sensor" for p in _gone), rep["positions"])
#  Настоящее правило склада (modules/inventory/backend.py) — дословно, на ядре из этой песочницы.
_INV = io.open(os.path.join(REPO, "modules", "inventory", "backend.py"), encoding="utf-8").read()
_inv_tree = ast.parse(_INV)
_no_ams_src = next(ast.get_source_segment(_INV, n) for n in _inv_tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "_printer_confirmed_no_ams")


class _Core:
    def printer_states(self):
        return NS["p_states"]

    def get_printer_reported_filament(self, pid):
        return json.loads(json.dumps(NS["_printer_reported_filament"](pid)))


INV_NS = {"core": _Core()}
exec(_no_ams_src, INV_NS)
check("2h. КОРЕНЬ (проверка пакета R-139): после снятия AMS склад НЕ получает «у принтера AMS нет» "
      "(_printer_confirmed_no_ams False) — правило «внешняя = слот 0» не включается, с катушки слота 0 не списывает",
      rep.get("telemetry_fresh") is True and INV_NS["_printer_confirmed_no_ams"](PID) is False,
      (rep.get("telemetry_fresh"), rep["positions"]))
feed({"ams": {"ams": [], "ams_exist_bits": "0", "tray_exist_bits": "0"}, "vt_tray": {"id": "254", "tray_type": "PLA"}},
     pid="node_noams")
check("2i. НЕ ВАКУУМ: принтер, у которого AMS не было никогда, склад по-прежнему видит «без AMS»",
      INV_NS["_printer_confirmed_no_ams"]("node_noams") is True
      and not [p for p in NS["_printer_reported_filament"]("node_noams")["positions"] if not p["external"]],
      NS["_printer_reported_filament"]("node_noams"))
st = feed({"ams": P1P_AMS})
check("2g. AMS вернули — слоты вернулись", sorted(by_index(st)) == [0, 1, 2, 3], sorted(by_index(st)))
_back = [p for p in NS["_printer_reported_filament"](PID)["positions"] if not p["external"]]
check("2j. AMS вернули — пометок removed нет, слоты снова заправлены по датчику",
      st.get("ams_removed") == [] and len(_back) == 4 and not any(p.get("removed") for p in _back)
      and all(p["present"] for p in _back), _back)

print("--- 3. пустой список при живом AMS (первый отчёт после подключения) ---")
reset()
feed({"ams": P1P_AMS})
CLOCK.t = 3000.0
feed({"ams": {"ams": [], "ams_exist_bits": "3", "tray_exist_bits": "ff"}})
CLOCK.t = 3030.0
st = feed({"ams": {"ams": [], "ams_exist_bits": "3", "tray_exist_bits": "ff"}})
check("3. пустой список, но биты блоков стоят ('3'/'ff') — слоты остаются и через 30 с",
      sorted(by_index(st)) == [0, 1, 2, 3] and all(t.get("present") for t in st["ams_trays"]), sorted(by_index(st)))

print("--- 4. маски нет вовсе — ничего не снимается ---")
reset()
feed({"ams": {"ams": P1P_AMS["ams"]}})
CLOCK.t = 4000.0
feed({"ams": {"ams": []}})
CLOCK.t = 4060.0
st = feed({"ams": {"ams": []}})
check("4. пустые списки без масок дважды через минуту — слоты на месте («a missing bitmask is not an unload»)",
      sorted(by_index(st)) == [0, 1, 2, 3], sorted(by_index(st)))
check("4b. без маски наличие неизвестно (None), а не «пусто»",
      all(t.get("present") is None for t in st["ams_trays"]), [t.get("present") for t in st["ams_trays"]])
CLOCK.t = 4070.0
feed({"ams": {"ams": [], "ams_exist_bits": "0"}})
CLOCK.t = 4075.0
feed({"gcode_state": "IDLE"})                      # отчёт без print.ams — выдержку не сбрасывает
CLOCK.t = 4085.0
st = feed({"ams": {"ams": [], "ams_exist_bits": "0"}})
check("4c. отчёт без блока ams между двумя пустыми не мешает подтверждению снятия",
      st.get("ams_trays") == [], st.get("ams_trays"))
reset()
feed({"ams": P1P_AMS})
CLOCK.t = 4100.0
feed({"ams": {"ams": [], "ams_exist_bits": "0"}})
CLOCK.t = 4105.0
feed({"ams": {"ams": P1P_AMS["ams"], "ams_exist_bits": "1"}})       # блок снова в списке
CLOCK.t = 4120.0
st = feed({"ams": {"ams": [], "ams_exist_bits": "0"}})
check("4d. блок вернулся в список между пустыми — выдержка начинается заново, слоты на месте",
      len(st["ams_trays"]) == 4, len(st["ams_trays"]))

print("--- 5. служебное обновление лотка не затирает материал ---")
reset()
feed({"ams": P1P_AMS})
st = feed({"ams": {"ams": [{"id": "0", "tray": [{"id": "1", "state": 11}]}], "tray_exist_bits": "f"}})
check("5. словарь {id, state} без tray_type — материал слота 1 прежний (PETG), остальные слоты на месте",
      by_index(st)[1]["type"] == "PETG" and by_index(st)[1]["color_raw"] == "00FF00FF"
      and len(st["ams_trays"]) == 4, by_index(st).get(1))
st = feed({"ams": {"ams": [{"id": "0", "tray": [{"id": "1"}]}], "tray_exist_bits": "d"}})
check("5b. голый {id} при бите 0 (ha-bambulab #2164) — слот 1 пуст: материал снят, лотка нет",
      by_index(st)[1]["type"] == "Empty" and by_index(st)[1].get("present") is False, by_index(st).get(1))

print("--- 6. датчик подачи главнее типа в слоте (R-116) ---")
reset()
st = feed({"ams": dict(P1P_AMS, tray_exist_bits="e")})
bi = by_index(st)
check("6. tray_exist_bits 'e': слот 0 не present, хотя тип PLA остался от прошлой катушки",
      bi[0].get("present") is False and bi[0]["type"] == "PLA" and bi[1].get("present") is True, bi.get(0))
rep = NS["_printer_reported_filament"](PID)
pos = {p["index"]: p for p in rep["positions"] if not p["external"]}
check("6b. склад: слот 0 — пуст и материалом не подтверждён (present False, reported_material None)",
      pos[0].get("present") is False and pos[0]["reported_material"] is None and pos[0]["presence"] == "sensor", pos.get(0))
check("6c. склад: слот 1 с лотком — как раньше (present True, PETG)",
      pos[1].get("present") is True and pos[1]["reported_material"] == "PETG", pos.get(1))
REQ.update({"fils": [{"material": "PLA", "color_hex": "#FF0000"}], "map": [0]})
use, mp, mp2 = NS["_bambu_resolve_ams"](PID, None, b"fake3mf")
check("6d. подбор запуска: PLA файла уходит в слот 2 с лотком, а не в пустой слот 0", mp == [2], mp)
have = NS["_qw_printer_feed"](PID, "bambu")[1]
check("6e. очередь: в позициях подачи нет слота без лотка",
      0 not in [h["slot"] for h in have if h["where"] == "ams"] and 1 in [h["slot"] for h in have], have)
reset()
st = feed({"ams": {k: v for k, v in P1P_AMS.items() if k != "tray_exist_bits"}})
rep = NS["_printer_reported_filament"](PID)
check("6f. отчёт без tray_exist_bits — склад видит слоты как раньше (по типу)",
      all(p.get("present") for p in rep["positions"] if not p["external"]), rep["positions"])

print("--- 7. H2D: AMS на левом сопле, AMS HT на правом (отчёт ha-bambulab H2D.json) ---")
reset()
H2D_AMS = {"ams": [{"id": "0", "info": "1101", "tray": [tray_d(0, "PLA", fid="GFA01"), tray_d(1, "PLA"),
                                                     tray_d(2, "PLA", fid="GFA01"), tray_d(3, "PETG", fid="GFG02")]},
                   {"id": "128", "info": "2004", "tray": [tray_d(0, "PA-GF", "000000FF", fid="GFN08")]}],
           "ams_exist_bits": "11", "tray_exist_bits": "1000f", "tray_now": "0", "tray_tar": "0"}
st = feed({"ams": H2D_AMS, "hw_switch_state": 1})
bi = by_index(st)
check("7. H2D: слоты 0..3 и HT под внутренним номером 512, все на месте по маске '1000f'",
      sorted(bi) == [0, 1, 2, 3, 512] and all(t.get("present") is True for t in bi.values()), sorted(bi))
check("7b. сопло блока из info: AMS 0 — левое (1), HT 128 — правое (0)",
      bi[0].get("extruder") == 1 and bi[512].get("extruder") == 0
      and (st.get("ams_units") or {}).get("0", {}).get("extruder") == 1
      and (st.get("ams_units") or {}).get("128", {}).get("extruder") == 0, st.get("ams_units"))
check("7c. tray_now 0 читается (активный слот 0)", st.get("ams_now") == 0, st.get("ams_now"))
REQ.update({"fils": [{"material": "PA-GF", "color_hex": "#000000"}], "map": [0],
            "sides": {"ok": True, "maps": [2], "extruders": 2, "source": "slice_info"}})
use, mp, mp2 = NS["_bambu_resolve_ams"](PID, None, b"fake3mf")
check("7d. подбор: PA-GF правого сопла — слот HT; в mapping2 блок 128", mp == [512] and mp2 == [{"ams_id": 128, "slot_id": 0}],
      (mp, mp2))
check("7e. в команду принтеру HT уходит номером блока 128", NS.get("_bambu_wire_mapping", list)(mp) == [128],
      NS.get("_bambu_wire_mapping", list)(mp))
REQ.pop("sides", None)
st = feed({"ams": {"ams": [], "ams_exist_bits": "1", "tray_exist_bits": "f"}})
CLOCK.t += 15
st = feed({"ams": {"ams": [], "ams_exist_bits": "1", "tray_exist_bits": "f"}})
check("7f. сняли только HT (бит 4 сброшен, бит AMS 0 стоит) — уходит только HT",
      sorted(by_index(st)) == [0, 1, 2, 3], sorted(by_index(st)))
_rm = [p for p in NS["_printer_reported_filament"](PID)["positions"] if p.get("removed")]
check("7g. след снятого HT для склада — позиция 512 (блок 128, слот 0), пустая",
      [(p["index"], p["unit"], p["tray"], p["present"]) for p in _rm] == [(512, 128, 0, False)], _rm)

print("--- 8. маска целым числом (P1) ---")
reset()
st = feed({"ams": dict(P1P_AMS, ams_exist_bits=1, tray_exist_bits=14)})
check("8. tray_exist_bits=14 целым числом принимается: слот 0 пуст, 1..3 на месте",
      [by_index(st)[i].get("present") for i in range(4)] == [False, True, True, True],
      [by_index(st)[i].get("present") for i in range(4)])
check("8b. маска мусором не ломает состояние (прежнее значение)",
      _bams.parse_bits("zz") is None and feed({"ams": {"tray_exist_bits": "zz"}}).get("tray_exist_bits") == 14)

print("--- 9. текущий слот и датчик экструдера (R-116) ---")
reset()
st = feed({"ams": {"ams": [], "tray_now": "254"}, "vt_tray": {"id": "254", "tray_type": "PETG"}})
check("9. P1P без AMS: tray_now 254 (внешняя) -> ams_now -1, а не 254", st.get("ams_now") == -1, st.get("ams_now"))
st = feed({"hw_switch_state": 0})
rep = NS["_printer_reported_filament"](PID)
ext = [p for p in rep["positions"] if p["external"]]
check("9b. внешняя позиция: extruder_has_filament=False по hw_switch_state=0, presence по-прежнему «setting»",
      ext and ext[0].get("extruder_has_filament") is False and ext[0]["presence"] == "setting", ext)
st = feed({"gcode_state": "IDLE"})
rep = NS["_printer_reported_filament"](PID)
check("9c. отчёт без hw_switch_state держит прежнее значение (P1 шлёт частями)",
      [p for p in rep["positions"] if p["external"]][0].get("extruder_has_filament") is False)
st = feed({"hw_switch_state": 1})
rep = NS["_printer_reported_filament"](PID)
check("9d. hw_switch_state=1 -> extruder_has_filament=True",
      [p for p in rep["positions"] if p["external"]][0].get("extruder_has_filament") is True)

print("--- 10. биты наличия по правилам Bambu Studio ---")
check("10. AMS: бит блока = id, бит лотка = id*4+slot",
      _bams.unit_bit(1, 1) == 1 and _bams.tray_bit(1, 2, 1) == 6)
check("10b. AMS HT: бит блока 4+(id-128), бит лотка 16+(id-128)+slot",
      _bams.unit_bit(129, 4) == 5 and _bams.tray_bit(129, 0, 4) == 17 and _bams.unit_bit(128, None) == 4)
check("10c. AMS Lite смешанный: бит блока 12, бит лотка 24+slot",
      _bams.unit_bit(0, 5) == 12 and _bams.tray_bit(0, 3, 5) == 27)
check("10d. сопло: 0x1101 -> 1 (левое), 0x2004 -> 0 (правое), 0x0E01 (переключатель) -> не знаем",
      _bams.unit_extruder(0x1101) == 1 and _bams.unit_extruder(0x2004) == 0 and _bams.unit_extruder(0x0E01) is None)

print("--- 11. занятость: ams_status и новый формат стадии (16.10.2026, R-138) ---")
reset()
st = feed({"gcode_state": "IDLE", "ams_status": 256, "stg_cur": 255})
check("11. ams_status из отчёта попадает в состояние принтера (0x0100 — смена филамента у Bambu Studio)",
      st.get("ams_status") == 256, st.get("ams_status"))
st = feed({"gcode_state": "IDLE"})
check("11b. отчёт без ams_status держит прежнее значение (P1 шлёт частями)", st.get("ams_status") == 256,
      st.get("ams_status"))
st = feed({"gcode_state": "IDLE", "stage": {"_id": 13}})
check("11c. новый формат стадии (print.stage._id) читается, когда stg_cur нет", st.get("stage") == 13, st.get("stage"))
st = feed({"gcode_state": "IDLE", "stg_cur": 255, "stage": {"_id": 13}})
check("11d. stg_cur есть — он главнее", st.get("stage") == 255, st.get("stage"))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
