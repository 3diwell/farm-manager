# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Payload-тест опций запуска Bambu (Alpha 2.723). БЕЗ принтера/БД/сервера: из server.py в рантайме
# ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ исходники (_bambu_tray2 / _bambu_resolve_ams / _apply_bambu_print_opts) и
# конструктор _base (вырезан из _send_file_to_printer), исполняются со стабом p_states. Проверяем
# ТОЧНЫЕ снапшоты полей против ПЕРЕХВАЧЕННЫХ команд Bambu Studio (инструмент 2.722):
#   P1  External + опции OFF: use_ams=false, ams_mapping=[-1], ams_mapping2=[{255,0}],
#       timelapse=false, flow_cali=false, extrude_cali_flag=0, extrude_cali_manual_mode=0
#       (ПОСТОЯННОЕ поле — есть и в OFF-перехвате Studio), bed OFF → bed_leveling=false + auto_bed_leveling=0;
#   P2  External + опции ON: timelapse=true, flow_cali=true, extrude_cali_flag=1,
#       extrude_cali_manual_mode=0, bed_leveling=true, auto_bed_leveling=1;
#   P3  AMS slot 0: use_ams=true, ams_mapping=[0], ams_mapping2=[{ams_id:0, slot_id:0}];
#   P4  AMS slot 1: ams_mapping=[1], ams_mapping2=[{ams_id:0, slot_id:1}];
#   P5  synthetic multi-AMS/AMS HT: index 512 (unit 128, tray 0) → в команде [128] + [{128,0}]
#       (16.10.2026, R-006: номер блока HT, как у Bambu Studio и Bambuddy; внутри программы 512);
#   P6  fallback без tray-отчёта: слот 5 → деривация {1,1};
#   P7  «Авто (как в файле)» мультифиламент: карта НЕ сведена к одному слоту ([0,1] + mapping2 по трею);
#   P8  legacy-ключей flow_cal / vibration_cal НЕТ в финальном JSON; vibration_cali=false; противоречий нет;
#   P9  дефолтный payload (print_opts=None — очередь/пакет/старые элементы) = штатные дефолты
#       (timelapse OFF, flow OFF, bed ON) и ключи согласованы;
#   P10 очередь: print_opts+ams_slot переживают JSON-роундтрип durable payload; элемент БЕЗ print_opts → None;
#   P11 _start_queued_print пробрасывает print_opts в оба потока (проверка кода, не текстов комментариев);
#   P12 non-Bambu не изменён: ветки klipper/flashforge не читают print_opts; whitelist не трогает протокол;
#   P13 guard одиночного слота: мультифиламентный файл + слот n>=0 → принудительное «Авто» (печать не обрезаем);
#   P14 guard внешней катушки (Alpha 2.734, 16.10.2026 — R-137): НАСТОЯЩАЯ отправка файла; External(-1) и
#       плита печатает несколько материалов → error БЕЗ загрузки/команды/хуков; один материал плиты — печать;
#   P15 (16.10.2026, R-137) внешняя катушка H2D по соплу в файле: левая {254,0}, правая {255,0}, массивы по
#       числу филаментов проекта, односопельный принтер без изменений, сторона не известна → отказ;
#   P16 (R-137) НАСТОЯЩАЯ _send_file_to_printer и _launch_feed_plan: отказ ДО загрузки, хукам склада — [-2]
#       для левой катушки, учёт назначений — ext_slot=-2, план подачи {"slots": [-2], "ext": 254}.
# Запуск: python tools/test_bambu_print_payload.py   (0 = все проверки пройдены)
import os, sys, json, re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

fail = 0
def check(name, cond, detail=""):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name + (("  :: " + str(detail)[:400]) if (detail != "" and not cond) else ""))
    if not cond:
        fail += 1

def _slice(src, a, b):
    i = src.index(a); j = src.index(b, i)
    return src[i:j]

# ── ДОСЛОВНЫЕ исходники из server.py ──
helpers = _slice(SRC, "def _bambu_tray2(", "\ndef _apply_bambu_print_opts(")
applyfn = _slice(SRC, "def _apply_bambu_print_opts(", "\ndef _send_file_to_printer(")
base_line = re.search(r'_base = \{"sequence_id": "0", "command": "project_file".*?\}\n', SRC, re.S).group(0)
check("извлечены дословные исходники (tray2/resolve/apply) и конструктор _base",
      "_bambu_resolve_ams" in helpers and "extrude_cali_manual_mode" in applyfn and '"ams_mapping2": _ams_map2' in base_line)

class _Log:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass

p_states = {}
def _bambu_ams_mapping(fdata):   # стаб авто-маппинга из 3mf: управляется тестом
    return _AUTO[0]
_AUTO = [(False, [])]
import ast, io as _io, zipfile, textwrap
import xml.etree.ElementTree as ET
_TREE = ast.parse(SRC)
def _ast_src(names):
    """Дословные исходники функций и констант модуля server.py по именам (AST, а не поиск текста)."""
    out = []
    for node in _TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            out.append(ast.get_source_segment(SRC, node))
        elif isinstance(node, ast.Assign):
            tg = set()
            for t in node.targets:
                if isinstance(t, ast.Name):
                    tg.add(t.id)
            if tg & set(names):
                out.append(ast.get_source_segment(SRC, node))
    return "\n\n".join(out)
#  16.10.2026 (R-137): внешняя катушка решается по файлу (_bambu_ext_choice) — плита и сопла читаются
#  НАСТОЯЩИМИ помощниками; _bambu_ams_mapping в старых пунктах по-прежнему управляется тестом.
READERS = _ast_src(("_3mf_plate_used", "_3mf_side_values", "_3mf_filament_sides",
                    "_REQ_PROJECT_SETTINGS", "_REQ_SLICE_INFO", "_QW_PLATE_RE"))
ns = {"p_states": p_states, "log": _Log(), "_exc_brief": (lambda: ""), "_bambu_ams_mapping": _bambu_ams_mapping, "json": json,
      "re": re, "io": _io, "zipfile": zipfile, "ET": ET}
exec(READERS, ns)
exec(helpers, ns)
exec(applyfn, ns)
resolve = ns["_bambu_resolve_ams"]; applyopts = ns["_apply_bambu_print_opts"]; tray2 = ns["_bambu_tray2"]

def build(pid, ams_slot, fdata, print_opts):
    """Собирает payload РОВНО как _send_file_to_printer: resolve → дословный _base → apply."""
    _use_ams, _ams_map, _ams_map2 = resolve(pid, ams_slot, fdata)
    env = {"plate_param": "Metadata/plate_1.gcode", "os": os, "fname": "part.gcode.3mf", "_up_name": "part.gcode.3mf",
           "_ams_map": _ams_map, "_ams_map2": _ams_map2, "_use_ams": _use_ams,
           "_bambu_wire_mapping": ns.get("_bambu_wire_mapping", list)}
    exec(base_line, env)
    base = env["_base"]
    applyopts(base, print_opts)
    return base

ON = {"timelapse": True, "bed_leveling": True, "flow_cal": True}
OFF_ALL = {"timelapse": False, "bed_leveling": False, "flow_cal": False}

# ═══ P1: External + все опции OFF — точный снапшот против перехвата Studio ═══
b = build("pX", -1, None, OFF_ALL)
check("P1. External OFF: use_ams=False, ams_mapping=[-1], ams_mapping2=[{ams_id:255,slot_id:0}], timelapse=F, flow_cali=F, extrude_cali_flag=0, extrude_cali_manual_mode=0 (постоянное), bed_leveling=F, auto_bed_leveling=0",
      b["use_ams"] is False and b["ams_mapping"] == [-1]
      and b["ams_mapping2"] == [{"ams_id": 255, "slot_id": 0}]
      and b["timelapse"] is False and b["flow_cali"] is False and b["extrude_cali_flag"] == 0
      and b["bed_leveling"] is False and b["auto_bed_leveling"] == 0
      and b["extrude_cali_manual_mode"] == 0)

# ═══ P2: External + все опции ON ═══
b = build("pX", -1, None, ON)
check("P2. External ON: timelapse=T, flow_cali=T, extrude_cali_flag=1, extrude_cali_manual_mode=0, bed_leveling=T, auto_bed_leveling=1; источник тот же external",
      b["use_ams"] is False and b["ams_mapping"] == [-1] and b["ams_mapping2"] == [{"ams_id": 255, "slot_id": 0}]
      and b["timelapse"] is True and b["flow_cali"] is True and b["extrude_cali_flag"] == 1
      and b["extrude_cali_manual_mode"] == 0 and b["bed_leveling"] is True and b["auto_bed_leveling"] == 1)

# ═══ P3/P4: реальные слоты AMS unit 0 (лотки из живого отчёта) ═══
p_states["pA"] = {"ams_trays": [
    {"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color": "#c00"},
    {"index": 1, "unit": 0, "tray": 1, "type": "PETG", "color": "#0c0"},
    {"index": 5, "unit": 1, "tray": 1, "type": "ABS", "color": "#00c"},
]}
b = build("pA", 0, None, None)
check("P3. AMS slot 0: use_ams=True, ams_mapping=[0], ams_mapping2=[{ams_id:0,slot_id:0}] (как в перехвате)",
      b["use_ams"] is True and b["ams_mapping"] == [0] and b["ams_mapping2"] == [{"ams_id": 0, "slot_id": 0}])
b = build("pA", 1, None, None)
check("P4. AMS slot 1: ams_mapping=[1], ams_mapping2=[{ams_id:0,slot_id:1}] (как в перехвате)",
      b["use_ams"] is True and b["ams_mapping"] == [1] and b["ams_mapping2"] == [{"ams_id": 0, "slot_id": 1}])
b = build("pA", 5, None, None)
check("P4b. мульти-AMS: глобальный слот 5 (unit 1, tray 1 из ЖИВОГО отчёта) → [5] + [{ams_id:1,slot_id:1}]",
      b["ams_mapping"] == [5] and b["ams_mapping2"] == [{"ams_id": 1, "slot_id": 1}])

# ═══ P5: synthetic AMS HT / нестандартный unit — НЕ предполагаем unit 0..3 ═══
p_states["pHT"] = {"ams_trays": [{"index": 512, "unit": 128, "tray": 0, "type": "PA-CF", "color": "#333"}]}
b = build("pHT", 512, None, None)
#  16.10.2026 (R-006): в КОМАНДЕ принтеру слот AMS HT — номер блока (128), как у Bambu Studio
#  (GetTrayIndexMap: у N3S tray_index = ams_id) и Bambuddy; прежде уходило 512. Внутренний номер 512
#  остаётся у программы (склад, интерфейс) — его отдаёт _bambu_resolve_ams.
check("P5. AMS HT synthetic: index 512 (unit 128, tray 0) → в команде ams_mapping=[128], ams_mapping2=[{ams_id:128,slot_id:0}]",
      b["use_ams"] is True and b["ams_mapping"] == [128] and b["ams_mapping2"] == [{"ams_id": 128, "slot_id": 0}])
check("P5b. внутренний номер слота HT для склада прежний: _bambu_resolve_ams отдаёт 512",
      resolve("pHT", 512, None)[1] == [512])
p_states["pHT2"] = {"ams_trays": [{"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color": "#fff"},
                                  {"index": 516, "unit": 129, "tray": 0, "type": "PETG", "color": "#000"}]}
_AUTO[0] = (True, [0, 1])
_rs = ns.get("_bambu_auto_mapping")
ns["_bambu_auto_mapping"] = (lambda pid, fdata, fmap, why: [1, 516])     # подбор дал слот AMS и второй HT
b = build("pHT2", None, b"fake3mf", None)
ns["_bambu_auto_mapping"] = _rs
_AUTO[0] = (False, [])
check("P5c. смешанная карта: слот AMS 1 уходит как есть, второй HT (516) — номером блока 129; mapping2 по отчёту",
      b["ams_mapping"] == [1, 129] and b["ams_mapping2"] == [{"ams_id": 0, "slot_id": 1}, {"ams_id": 129, "slot_id": 0}],
      )

# ═══ P6: fallback без tray-отчёта (принтер оффлайн) — деривация из конструкции индекса ═══
b = build("pOffline", 5, None, None)
check("P6. слот 5 без живого отчёта → деривация {ams_id:1, slot_id:1} (index = unit*4 + tray)",
      b["ams_mapping"] == [5] and b["ams_mapping2"] == [{"ams_id": 1, "slot_id": 1}])

# ═══ P7: «Авто (как в файле)» мультифиламент — карта НЕ сведена к одному слоту ═══
_AUTO[0] = (True, [0, 1])
b = build("pA", None, b"fake3mf", None)
check("P7. авто мультифиламент: ams_mapping=[0,1] (identity, НЕ один слот), ams_mapping2 по живым лоткам [{0,0},{0,1}]",
      b["use_ams"] is True and b["ams_mapping"] == [0, 1]
      and b["ams_mapping2"] == [{"ams_id": 0, "slot_id": 0}, {"ams_id": 0, "slot_id": 1}])
_AUTO[0] = (False, [])
b = build("pA", None, b"fake3mf", None)
check("P7b. авто, но файл без филамент-инфо → честный external-формат ([-1] + 255), как печать с флешки",
      b["use_ams"] is False and b["ams_mapping"] == [-1] and b["ams_mapping2"] == [{"ams_id": 255, "slot_id": 0}])

# ═══ P8: никаких legacy/противоречий в финальном JSON ═══
for sc, (slot, po) in {"ext-on": (-1, ON), "slot0": (0, None), "auto": (None, None)}.items():
    b = build("pA", slot, b"x", po)
    s = json.dumps(b)
    if ("flow_cal\"" in s) or ("vibration_cal\"" in s):
        check("P8. legacy flow_cal/vibration_cal отсутствуют (сценарий %s)" % sc, False); break
else:
    check("P8. legacy flow_cal/vibration_cal ОТСУТСТВУЮТ во всех сценариях; vibration_cali=false; flow_cali/extrude_cali_flag согласованы",
          True)
b = build("pA", 0, None, ON)
check("P8b. согласованность производных: flow_cali=T ↔ extrude_cali_flag=1; bed=T ↔ auto_bed_leveling=1; extrude_cali_manual_mode=0 всегда; vibration_cali=False (до подтверждения)",
      b["vibration_cali"] is False and b["extrude_cali_flag"] == int(b["flow_cali"]) and b["auto_bed_leveling"] == int(b["bed_leveling"])
      and b["extrude_cali_manual_mode"] == 0)
b = build("pA", 0, None, OFF_ALL)
check("P8c. extrude_cali_manual_mode=0 присутствует и при Flow OFF (точное соответствие OFF-перехвату Studio)",
      b["flow_cali"] is False and b["extrude_cali_flag"] == 0 and b["extrude_cali_manual_mode"] == 0)

# ═══ P13: guard мультифиламентного файла — одиночный запомненный слот НЕ обрезает мульти-печать ═══
_AUTO[0] = (True, [0, 1])
b = build("pA", 5, b"multi3mf", None)   # пользователь/память дали одиночный слот 5, файл 2-филаментный
check("P13a. мультифиламентный файл + одиночный слот 5 → принудительное «Авто»: ams_mapping=[0,1] (identity), mapping2 по живым лоткам; [5] НЕ отправлен",
      b["use_ams"] is True and b["ams_mapping"] == [0, 1]
      and b["ams_mapping2"] == [{"ams_id": 0, "slot_id": 0}, {"ams_id": 0, "slot_id": 1}])
_AUTO[0] = (True, [0])
b = build("pA", 5, b"single3mf", None)   # однофиламентный файл — выбранный слот УВАЖАЕТСЯ
check("P13b. однофиламентный файл + слот 5 → слот сохраняется: [5] + [{ams_id:1,slot_id:1}]",
      b["use_ams"] is True and b["ams_mapping"] == [5] and b["ams_mapping2"] == [{"ams_id": 1, "slot_id": 1}])
_AUTO[0] = (False, [])
b = build("pA", 5, None, None)   # fdata недоступен (путь start_print) — guard не применим, слот сохраняется
check("P13c. без fdata (печать файла с принтера) guard не применим — слот 5 сохраняется как раньше",
      b["use_ams"] is True and b["ams_mapping"] == [5])

# ═══ P9: дефолтный payload (очередь/пакет/старые элементы, print_opts=None) ═══
b = build("pX", -1, None, None)
check("P9. print_opts=None → штатные дефолты: timelapse=F, flow_cali=F+flag 0+manual_mode 0 (постоянное), bed_leveling=T+auto 1, vibration_cali=F, bed_type=auto, md5/param как раньше",
      b["timelapse"] is False and b["flow_cali"] is False and b["extrude_cali_flag"] == 0
      and b["extrude_cali_manual_mode"] == 0
      and b["bed_leveling"] is True and b["auto_bed_leveling"] == 1 and b["vibration_cali"] is False
      and b["bed_type"] == "auto" and b["md5"] == "" and b["param"] == "Metadata/plate_1.gcode")

# ═══ P10: очередь — durable JSON-роундтрип сохраняет print_opts и источник ═══
qitem_src = _slice(SRC, '_qitem = {', '}\n')
check("P10a. элемент очереди содержит print_opts (dict-guard) и ams_slot", '"print_opts"' in qitem_src and '"ams_slot"' in qitem_src)
qitem = {"id": "1", "durable_id": "plq_x", "printer_id": "p1", "flow": "quick", "due_ts": 1.0,
         "gcode_file": "a.3mf", "source": "quick", "part_name": "", "project_id": None, "file_id": None,
         "ams_slot": -1, "print_opts": {"timelapse": True, "bed_leveling": False, "flow_cal": True}}
rt = json.loads(json.dumps(qitem, ensure_ascii=False))   # durable payload-колонка → recovery reconstruct
b = build("pX", rt.get("ams_slot"), None, rt.get("print_opts"))
check("P10b. роундтрип payload-JSON: print_opts+ams_slot пережили сериализацию; итоговый payload = External + ON-набор (bed OFF)",
      rt["print_opts"] == qitem["print_opts"] and rt["ams_slot"] == -1
      and b["use_ams"] is False and b["ams_mapping"] == [-1] and b["timelapse"] is True
      and b["flow_cali"] is True and b["extrude_cali_flag"] == 1 and b["extrude_cali_manual_mode"] == 0
      and b["bed_leveling"] is False and b["auto_bed_leveling"] == 0)
old_item = {"printer_id": "p1", "flow": "quick", "gcode_file": "a.3mf", "ams_slot": None}   # элемент ДО 2.723
b = build("pX", old_item.get("ams_slot"), None, old_item.get("print_opts"))
check("P10c. СТАРЫЙ элемент очереди без print_opts: .get() → None → дефолтный payload (P9), ничего не падает",
      old_item.get("print_opts") is None and b["timelapse"] is False and b["bed_leveling"] is True and b["auto_bed_leveling"] == 1)

# ═══ P11: _start_queued_print пробрасывает print_opts в ОБА потока ═══
sq = _slice(SRC, "async def _start_queued_print", "def _plq_set_status")
check("P11. _start_queued_print: project-поток и quick-поток передают print_opts=q.get(\"print_opts\")",
      sq.count('q.get("print_opts")') >= 2 and 'print_opts=q.get("print_opts")' in sq and '"print_opts": q.get("print_opts")' in sq)

# ═══ P12: non-Bambu не изменён; whitelist не трогает протокольные ключи ═══
sendfn = _slice(SRC, "def _send_file_to_printer(", "\nfrom concurrent.futures import ThreadPoolExecutor as _SendPool")   # Alpha 2.728: менеджер вставлен после _send_file_to_printer — режем ровно до него
klipper_branch = _slice(sendfn, 'if ptype == "klipper":', 'elif ptype == "bambu":')
ff_branch = sendfn[sendfn.index('elif ptype == "flashforge":'):]
b0 = build("pA", 0, None, {"timelapse": True, "command": "hack", "use_ams": False, "ams_mapping": [9], "url": "ftp://x", "token": "T"})
# Alpha 2.833: klipper-ветка читает РОВНО ОДИН allowlist-ключ print_opts.klipper_prestart (список
# option ID для предстартовых операций); Bambu-ключи (timelapse/bed_leveling/…) и произвольные
# ключи клиента в klipper по-прежнему НЕ читаются и протокол НЕ переопределяют. FlashForge — не читает вовсе.
check("P12. flashforge не читает print_opts; klipper читает ТОЛЬКО klipper_prestart (2.833); чужие ключи НЕ переопределяют протокол (command/use_ams/ams_mapping/url нетронуты)",
      "print_opts" not in ff_branch
      and klipper_branch.count('(print_opts or {}).get("klipper_prestart")') == 1   # единственный КОДОВЫЙ доступ
      and klipper_branch.count("print_opts.get") == 0 and klipper_branch.count("print_opts[") == 0
      and "timelapse" not in klipper_branch and "bed_leveling" not in klipper_branch
      and b0["command"] == "project_file" and b0["use_ams"] is True and b0["ams_mapping"] == [0] and "url" not in b0 and "token" not in b0)

# ═══ P14–P16 (16.10.2026, R-137): НАСТОЯЩИЕ функции и файлы в формате Bambu Studio ═══
#  Образцы собраны по устройству настоящего файла Bambu Studio (slice_info: <plate> с metadata index,
#  nozzle_diameters, filament_maps и <filament id tray_info_idx type color used_m used_g>; model_settings:
#  plater_id, filament_map_mode, filament_maps; project_settings: filament_map, nozzle_diameter,
#  physical_extruder_map) — это устройство снято с файла H2S владельца, его модель сюда не попадает.
def mk3mf(types, plate_ids, si_maps=None, ms_maps=None, ps_map=None, nozzles=1, model="Bambu Lab H2D",
          slice_info=True):
    b = _io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        ps = {"filament_type": list(types), "filament_colour": ["#FFFFFF"] * len(types),
              "filament_ids": ["GFL99"] * len(types), "printer_model": model,
              "nozzle_diameter": ["0.4"] * nozzles, "physical_extruder_map": [str(i) for i in range(nozzles)]}
        if ps_map is not None:
            ps["filament_map"] = list(ps_map)
        z.writestr("Metadata/project_settings.config", json.dumps(ps))
        if slice_info:
            x = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>", "  <plate>",
                 '    <metadata key="index" value="1"/>', '    <metadata key="printer_model_id" value="O1D"/>',
                 '    <metadata key="nozzle_diameters" value="0.4"/>']
            if si_maps is not None:
                x.append('    <metadata key="filament_maps" value="%s"/>' % si_maps)
            for fid in plate_ids:
                x.append('    <filament id="%d" tray_info_idx="GFL99" type="%s" color="#FFFFFF" used_m="1.00" used_g="3.00" />'
                         % (fid, types[fid - 1]))
            x += ["  </plate>", "</config>"]
            z.writestr("Metadata/slice_info.config", "\n".join(x))
        if ms_maps is not None:
            z.writestr("Metadata/model_settings.config",
                       '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <plate>\n'
                       '    <metadata key="plater_id" value="1"/>\n'
                       '    <metadata key="filament_map_mode" value="Manual"/>\n'
                       '    <metadata key="filament_maps" value="%s"/>\n  </plate>\n</config>' % ms_maps)
        z.writestr("Metadata/plate_1.gcode", "; HEADER_BLOCK_START\nG28\n")
    return b.getvalue()

R = {"p_states": {}, "log": _Log(), "_exc_brief": (lambda: ""), "json": json, "re": re, "io": _io,
     "zipfile": zipfile, "ET": ET, "os": os}
exec(_ast_src(("_bambu_ams_mapping",)), R)
exec(READERS, R)
exec(helpers, R)
exec(applyfn, R)
R["_bambu_auto_mapping"] = lambda pid, fdata, fmap, why: list(fmap)
H2D = {"nozzle_count": 2, "ams_trays": [], "ext_trays": {"254": {"tray_type": "PLA"}, "255": {"tray_type": "PETG"}}}
P1S = {"nozzle_count": 1, "ams_trays": []}
R["p_states"].update({"h2d": dict(H2D), "p1s": dict(P1S)})
rs, ch = R["_bambu_resolve_ams"], R["_bambu_ext_choice"]

LEFT1 = mk3mf(["PLA"], [1], si_maps="1", nozzles=2)
RIGHT1 = mk3mf(["PETG"], [1], si_maps="2", nozzles=2)
LEFT_OF3 = mk3mf(["PETG", "PLA", "ABS"], [2], si_maps="2 1 2", nozzles=2)
NOSIDE = mk3mf(["PLA"], [1], nozzles=2)
ONE_P1S = mk3mf(["PLA"], [1], si_maps="1", nozzles=1, model="Bambu Lab P1S")
OF3_P1S = mk3mf(["PETG", "PLA", "ABS"], [2], si_maps="1 1 1", nozzles=1, model="Bambu Lab P1S")
TWO_P1S = mk3mf(["PETG", "PLA", "ABS"], [1, 2], si_maps="1 1 1", nozzles=1, model="Bambu Lab P1S")

print("--- P15. внешняя катушка: сторона по соплу в файле (R-137) ---")
check("P15a. H2D, файл под ЛЕВОЕ сопло, «Внешняя катушка» → use_ams=false, [-1], [{ams_id:254, slot_id:0}]",
      rs("h2d", -1, LEFT1) == (False, [-1], [{"ams_id": 254, "slot_id": 0}]), rs("h2d", -1, LEFT1))
check("P15b. H2D, файл под ПРАВОЕ сопло → [-1], [{255, 0}]",
      rs("h2d", -1, RIGHT1) == (False, [-1], [{"ams_id": 255, "slot_id": 0}]), rs("h2d", -1, RIGHT1))
check("P15c. проект на 3 филамента, плита печатает №2 на левом сопле → по записи на филамент: [-1,-1,-1] и "
      "[{255,255},{254,0},{255,255}] (как get_ams_mapping_result у Studio)",
      rs("h2d", -1, LEFT_OF3) == (False, [-1, -1, -1], [{"ams_id": 255, "slot_id": 255}, {"ams_id": 254, "slot_id": 0},
                                                       {"ams_id": 255, "slot_id": 255}]), rs("h2d", -1, LEFT_OF3))
check("P15d. «Авто» у H2D без AMS — тот же выбор по соплу: левый файл → {254, 0}",
      rs("h2d", None, LEFT1) == (False, [-1], [{"ams_id": 254, "slot_id": 0}]), rs("h2d", None, LEFT1))
check("P15e. односопельный P1S, однофиламентный файл → РОВНО прежние [-1] и [{255, 0}] (P1/P7b)",
      rs("p1s", -1, ONE_P1S) == (False, [-1], [{"ams_id": 255, "slot_id": 0}])
      and rs("p1s", None, ONE_P1S) == (False, [-1], [{"ams_id": 255, "slot_id": 0}]), rs("p1s", -1, ONE_P1S))
check("P15f. P1S: проект на 3 филамента, плита печатает №2 → [-1,-1,-1] и [{255,255},{255,0},{255,255}] "
      "(раньше такой файл с внешней катушки не принимался вовсе)",
      rs("p1s", -1, OF3_P1S) == (False, [-1, -1, -1], [{"ams_id": 255, "slot_id": 255}, {"ams_id": 255, "slot_id": 0},
                                                      {"ams_id": 255, "slot_id": 255}]), rs("p1s", -1, OF3_P1S))
_c = ch("h2d", NOSIDE, explicit=True)
check("P15g. H2D, в файле нет сопла → отказ с понятной причиной, НИКАКОГО «по умолчанию 255»; resolve → (False, None, None)",
      _c["ok"] is False and "соплом" in (_c["why"] or "") and rs("h2d", -1, NOSIDE) == (False, None, None), _c)
_ms = mk3mf(["PLA"], [1], ms_maps="1", nozzles=2)
_ps = mk3mf(["PLA"], [1], ps_map=["2"], nozzles=2)
_ps_nosi = mk3mf(["PLA"], [1], ps_map=["1"], nozzles=2, slice_info=False)
check("P15h. запасные источники стороны: model_settings «1» → левая; project_settings filament_map ['2'] → правая; "
      "без slice_info — project_settings",
      ch("h2d", _ms)["ext"] == 254 and ch("h2d", _ps)["ext"] == 255 and ch("h2d", _ps_nosi)["ext"] == 254,
      (ch("h2d", _ms), ch("h2d", _ps)))
_bad = [ch("h2d", mk3mf(["PLA"], [1], si_maps=v, nozzles=2))["ok"] for v in ("0", "3", "")]
check("P15i. значения стороны не 1/2 ('0', '3', '') — сторона не известна, отказ (не подрезаются до 1)",
      _bad == [False, False, False], _bad)
_sf = ch("h2d", ONE_P1S, explicit=True)
check("P15j. на H2D файл, нарезанный для односопельного (nozzle_diameter один) → отказ «нарежьте под этот принтер»",
      _sf["ok"] is False and "односопельного" in (_sf["why"] or ""), _sf)
_l2 = ch("h2d", LEFT1, explicit=True, want=-2)
_r2 = ch("h2d", RIGHT1, explicit=True, want=-2)
check("P15k. явная «левая» (-2): файл под левое сопло → {254, 0}; под правое → отказ",
      _l2["ok"] and _l2["v1"] == [{"ams_id": 254, "slot_id": 0}] and _r2["ok"] is False, (_l2, _r2))
_m = ch("p1s", TWO_P1S, explicit=True)
check("P15l. P1S, плита печатает ДВА материала, явная внешняя катушка → отказ «плита печатает 2»",
      _m["ok"] is False and "печатает 2" in (_m["why"] or ""), _m)
check("P15m. P1S «Авто» без AMS при двух материалах плиты — прежняя команда [-1]/[{255,0}] (поведение не менялось)",
      rs("p1s", None, TWO_P1S) == (False, [-1], [{"ams_id": 255, "slot_id": 0}]), rs("p1s", None, TWO_P1S))
_n1, _n2 = ch("h2d", None), ch("p1s", None)
check("P15n. байтов файла нет (файл на принтере не прочитан): H2D — отказ; P1S — прежние [-1]/[{255,0}]",
      _n1["ok"] is False and _n2["ok"] and _n2["v1"] == [{"ams_id": 255, "slot_id": 0}], (_n1, _n2))

print("--- P14/P16. настоящая отправка файла и план подачи (R-137) ---")
UPL, CMDS, HOOKS, STASH = [], [], [], []
SF = dict(R)
SF.update({"time": __import__("time"), "server_print": {}, "_server_print_ts": {}, "_user_stopped": {},
           "print_run_events": type("_E", (), {"stash_dispatch": staticmethod(lambda *a, **k: None)})(),
           "bambu_serials": {"h2d": "SER", "p1s": "SER"}, "_bambu_ok_scheme": {}, "_bambu_last_refusal": {},
           "BAMBU_SLOW_MBPS": 0.5, "_bambu_refusal_reason": (lambda pid: ""),
           "_run_after_dispatch_hooks": (lambda pid, m, fd, fn: HOOKS.append(list(m))),
           "_stash_run_assignments": (lambda *a, **k: STASH.append((list(a[1]), a[3], k.get("ext_slot", -1))))})
SF["_bambu_ftp_upload"] = lambda pip, tok, name, fdata, attempts=3, timing=None, progress_cb=None: (UPL.append(name) or (True, "ok"))
SF["_bambu_send_project"] = lambda pid, serial, base, name: (CMDS.append(dict(base)) or True)
exec(_ast_src(("_bambu_safe_upload_name", "_send_file_to_printer", "_launch_feed_plan")), SF)
_send = SF["_send_file_to_printer"]

def _clear():
    UPL[:] = []; CMDS[:] = []; HOOKS[:] = []; STASH[:] = []

_clear()
r = _send("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "h2d", "left.gcode.3mf", LEFT1, ams_slot=-1)
check("P16a. H2D, левый файл: загрузка и команда {254, 0}; хукам склада — позиция -2; учёт назначений — ext_slot=-2",
      r == {"status": "ok"} and len(UPL) == 1 and CMDS and CMDS[0]["ams_mapping2"] == [{"ams_id": 254, "slot_id": 0}]
      and CMDS[0]["ams_mapping"] == [-1] and CMDS[0]["use_ams"] is False
      and HOOKS == [[-2]] and STASH == [([], True, -2)], (r, CMDS[:1], HOOKS, STASH))
_clear()
r = _send("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "h2d", "noside.gcode.3mf", NOSIDE, ams_slot=-1)
check("P14a. H2D, сопло в файле не указано → error ДО загрузки: ни файла на принтере, ни команды, ни хуков",
      isinstance(r, dict) and r.get("status") == "error" and "соплом" in r.get("reason", "")
      and not UPL and not CMDS and not HOOKS and not STASH, (r, UPL, CMDS, HOOKS))
_clear()
r = _send("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "h2d", "noside.gcode.3mf", NOSIDE, ams_slot=None)
check("P14b. то же для «Авто» у H2D без AMS — тоже отказ до загрузки (раньше уходило 255)",
      isinstance(r, dict) and r.get("status") == "error" and not UPL and not CMDS, (r, UPL, CMDS))
_clear()
r = _send("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "p1s", "two.gcode.3mf", TWO_P1S, ams_slot=-1)
check("P14c. P1S, явная внешняя катушка, плита печатает два материала → error до загрузки (печать не обрезается)",
      isinstance(r, dict) and r.get("status") == "error" and not UPL and not CMDS and not HOOKS, (r, UPL))
_clear()
r = _send("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "p1s", "of3.gcode.3mf", OF3_P1S, ams_slot=-1)
check("P14d. P1S, проект на 3 филамента, плита печатает один → печать идёт; хукам — [-1]; назначение — основная катушка (ext_slot=-1)",
      r == {"status": "ok"} and CMDS and CMDS[0]["ams_mapping2"][1] == {"ams_id": 255, "slot_id": 0}
      and HOOKS == [[-1]] and STASH == [([], True, -1)], (r, HOOKS, STASH))
_clear()
r = _send("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "p1s", "one.gcode.3mf", ONE_P1S, ams_slot=-1)
check("P14e. P1S, однофиламентный файл → команда прежняя [-1]/[{255,0}]",
      r == {"status": "ok"} and CMDS and CMDS[0]["ams_mapping"] == [-1]
      and CMDS[0]["ams_mapping2"] == [{"ams_id": 255, "slot_id": 0}], CMDS[:1])
_clear()
r = _send("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "h2d", "left.gcode.3mf", LEFT1, ams_slot=None)
check("P16b. «Авто» у H2D без AMS, левый файл → {254, 0} и хукам [-2]",
      r == {"status": "ok"} and CMDS and CMDS[0]["ams_mapping2"] == [{"ams_id": 254, "slot_id": 0}] and HOOKS == [[-2]],
      (r, CMDS[:1], HOOKS))
_plan = SF["_launch_feed_plan"]
_pl, _pr, _pp, _pu = (_plan("h2d", "bambu", -1, LEFT1), _plan("h2d", "bambu", -1, RIGHT1),
                      _plan("p1s", "bambu", -1, ONE_P1S), _plan("h2d", "bambu", -1, NOSIDE))
check("P16c. план подачи для проверки склада: левая H2D — slots [-2], ext 254; правая — [-1], ext 255; "
      "P1S — [-1] без поля ext (как раньше); сторона не известна — слотов нет",
      _pl.get("slots") == [-2] and _pl.get("ext") == 254 and _pl.get("external") is True
      and _pr.get("slots") == [-1] and _pr.get("ext") == 255
      and _pp.get("slots") == [-1] and "ext" not in _pp and _pu.get("slots") == [], (_pl, _pr, _pp, _pu))

print("--- P17. H2D: филамент не уходит в AMS чужого сопла (16.10.2026, проверка пакета R-006) ---")
#  Bambu Studio (SelectMachine.cpp do_ams_mapping) филамент левого сопла кладёт только в левый AMS или 254,
#  правого — только в правый AMS или 255; перекрёстная карта кончается остановкой принтера (Bambuddy #318).
#  H2D как в отчёте ha-bambulab H2D.json: AMS 0 на ЛЕВОМ сопле, AMS HT 128 на ПРАВОМ. Файл: ABS и PLA, оба под
#  ПРАВОЕ сопло. НАСТОЯЩИЙ подбор: ABS -> HT (512), а PLA справа нет — подбор оставляет слот файла 1 (левый AMS).
sys.path.insert(0, REPO)                             # модули программы (app/...) — из этого репозитория
from app import project_orchestrator as _orch_m, bambu_slot_match as _bslot_m, bambu_ams_state as _bams_m  # noqa: E402
XF = dict(SF)
XF.update({"_orch": _orch_m, "_bslot": _bslot_m, "_bams": _bams_m, "p_states": {}})
exec(_ast_src(("_3mf_filament_requirements", "_3mf_req_from_project_settings", "_3mf_req_from_slice_info",
                "_norm_hex_color")), XF)
exec(helpers, XF)                                    # настоящий авто-подбор (в R он заменён тождественным)
exec(_ast_src(("_bambu_safe_upload_name", "_send_file_to_printer")), XF)
_xsend = XF["_send_file_to_printer"]
_XW = "FFFFFFFF"
_XN = [{"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color_raw": _XW, "color": "#FFFFFF", "extruder": 1, "present": True},
       {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color_raw": _XW, "color": "#FFFFFF", "extruder": 1, "present": True},
       {"index": 512, "unit": 128, "tray": 0, "type": "ABS", "color_raw": _XW, "color": "#FFFFFF", "extruder": 0, "present": True}]
XN_FILE = mk3mf(["ABS", "PLA"], [1, 2], si_maps="2 2", nozzles=2)
XF["p_states"]["h2d"] = {"nozzle_count": 2, "ams_trays": [dict(t) for t in _XN]}
_xmap = XF["_bambu_auto_slot_map"]("h2d", XN_FILE, [0, 1])
_clear()
r = _xsend("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "h2d", "xn.gcode.3mf", XN_FILE, ams_slot=None)
check("P17a. «Авто»: подбор дал перекрёстную карту %s (PLA правого сопла — в AMS левого) — отказ ДО загрузки: ни "
      "файла на принтере, ни команды, ни хуков склада; причина по-русски называет филамент и сопла" % _xmap,
      _xmap == [512, 1] and isinstance(r, dict) and r.get("status") == "error"
      and "филамент №2 нарезан под правое сопло" in r.get("reason", "") and "левому соплу" in r.get("reason", "")
      and not UPL and not CMDS and not HOOKS and not STASH, (_xmap, r, UPL, CMDS, HOOKS))
_xc = XF["_bambu_cross_nozzle"]("h2d", XN_FILE, [512, 1])
check("P17b. проверка сопла называет филамент, сторону, слот и сопло блока",
      _xc and (_xc["i"], _xc["side"], _xc["slot"], _xc["extruder"]) == (1, 2, 1, 1), _xc)
XN_ONE = mk3mf(["PLA"], [1], si_maps="2", nozzles=2)
_clear()
r = _xsend("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "h2d", "one.gcode.3mf", XN_ONE, ams_slot=1)
check("P17c. слот выбран вручную (AMS левого сопла), файл под правое сопло — тоже отказ до загрузки",
      isinstance(r, dict) and r.get("status") == "error" and "правое сопло" in r.get("reason", "") and not UPL and not CMDS,
      (r, UPL, CMDS))
XF["p_states"]["h2d"]["ams_trays"].append({"index": 4, "unit": 1, "tray": 0, "type": "PLA", "color_raw": _XW,
                                           "color": "#FFFFFF", "extruder": 0, "present": True})
_clear()
r = _xsend("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "h2d", "xn.gcode.3mf", XN_FILE, ams_slot=None)
check("P17d. НЕ ВАКУУМ: PLA есть и в AMS правого сопла — печать уходит, карта [HT 128, слот 4], use_ams true",
      r == {"status": "ok"} and len(UPL) == 1 and CMDS and CMDS[0]["ams_mapping"] == [128, 4]
      and CMDS[0]["use_ams"] is True, (r, CMDS[:1]))
XF["p_states"]["p1s"] = {"nozzle_count": 1, "ams_trays": [dict(t) for t in _XN]}
check("P17e. односопельный принтер не проверяется (сопло блока к нему не относится)",
      XF["_bambu_cross_nozzle"]("p1s", XN_FILE, [512, 1]) is None
      and XF["_bambu_cross_nozzle"]("h2d", mk3mf(["ABS", "PLA"], [1, 2], nozzles=2), [512, 1]) is None)

print("--- P18. внешняя катушка: номер филамента плиты за пределами счёта проекта (16.10.2026) ---")
_b18 = _io.BytesIO()
with zipfile.ZipFile(_b18, "w") as _z:
    _z.writestr("Metadata/project_settings.config", json.dumps({"filament_type": ["PLA", "PETG"],
                                                               "nozzle_diameter": ["0.4"], "printer_model": "Bambu Lab P1S"}))
    _z.writestr("Metadata/slice_info.config", '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <plate>\n'
                '    <metadata key="index" value="1"/>\n'
                '    <filament id="2" tray_info_idx="GFG99" type="PETG" color="#FFFFFF" used_m="1.00" used_g="3.00" />\n'
                '  </plate>\n</config>')
    _z.writestr("Metadata/plate_1.gcode", "; HEADER_BLOCK_START\nG28\n")
P18 = _b18.getvalue()
_c18 = ch("p1s", P18, explicit=True)
check("P18. P1S, явная внешняя катушка, filament_colour в проекте нет, плита печатает филамент №2 — НЕ отказ "
      "(прежде «плита печатает 1»): [-1,-1] и [{255,255},{255,0}]",
      _c18["ok"] is True and _c18["v0"] == [-1, -1]
      and _c18["v1"] == [{"ams_id": 255, "slot_id": 255}, {"ams_id": 255, "slot_id": 0}]
      and rs("p1s", -1, P18) == (False, [-1, -1], [{"ams_id": 255, "slot_id": 255}, {"ams_id": 255, "slot_id": 0}]), _c18)

print("\n" + ("FAIL: %d проверок провалено" % fail if fail else
             "PASS: payload опций запуска Bambu — точное соответствие перехваченным командам Studio (external/слоты/HT/авто, ON/OFF, очередь/recovery, guard external+multi, без legacy-ключей)"))
sys.exit(1 if fail else 0)
