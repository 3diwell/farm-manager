# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""План подачи перед стартом печати (16.09.2026, слово владельца «делаем»).

ЗАЧЕМ. Проверка склада «хватит ли филамента» шла по слоту из запроса. При запуске из очереди и
пачкой слот не задан вовсе — сверялась катушка в слоте 0, пока печать шла с внешней катушки Bambu
или из ячейки CFS у Creality. Теперь ядро считает план подачи ТЕМИ ЖЕ функциями, которые решают
слот при отправке, и передаёт его хуку модуля. Проверяется исполнением самое опасное:

  1. план совпадает с тем, что решит транспорт (внешняя катушка, слот AMS, авто-раскладка, CFS);
  2. пустой список слотов — это «подача не определена», а НЕ слот 0;
  3. старый хук с четырьмя аргументами продолжает работать и продолжает блокировать печать:
     пятый позиционный аргумент дал бы TypeError, fail-open ветка проглотила бы его, и блокировка
     склада исчезла бы молча — это худшее, что могло случиться с этой правкой;
  4. распознаватель сигнатуры не роняет обход хуков сам (иначе хук пропустится целиком);
  5. план — только чтение: ни отправки, ни записи в базу.

БЕЗОПАСНОСТЬ — как в tools/test_queue_wait.py: сервер целиком НЕ импортируется, рабочая база не
открывается. Из server.py берутся ИСХОДНЫЕ ТЕКСТЫ нужных функций и модульных констант и
исполняются в отдельном пространстве имён со стабами. Файлы-образцы собираются здесь по правилам
записи Bambu Studio.

Запуск:  python tools/test_pre_print_slot_plan.py
"""
import ast
import io
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SENTINEL = "PRE_PRINT_SLOT_PLAN_3_0"
PASS = FAIL = 0

from app import project_orchestrator as _orch          # noqa: E402 — чистые модули, без сервера
from app import gcode_tool_slot as _gts                # noqa: E402


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


SRC = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
_tree = ast.parse(SRC)
FUNCS = ("_norm_hex_color", "_reported_material_norm", "_tray_remain", "_ams_low_pct",
         "_3mf_req_from_project_settings", "_3mf_req_from_slice_info", "_3mf_filament_requirements", "_3mf_plate_used",
         #  16.10.2026 (R-006): сопла филаментов H2D из файла — помощник плиты, его зовут подбор
         #  запуска и сведения очереди о файле; без него обе падали бы в песочнице NameError.
         "_3mf_filament_sides", "_3mf_side_values",
         "_bambu_ams_mapping", "_bambu_tray2", "_bambu_auto_slot_map", "_bambu_feed_report",
         "_bambu_auto_mapping", "_bambu_resolve_ams", "_cfs_tray_of", "_klipper_dispatch_slots",
         "_launch_feed_plan", "_hook_wants_plan", "_register_print_hook", "_run_pre_print_hooks",
         #  16.10.2026 (R-151): вызов хука со сроком и правило левой внешней катушки H2D
         "_call_hook", "_hook_accepts", "_hook_module_name", "_plan_has_ext_left",
         #  16.10.2026 (R-137): какая внешняя катушка (у H2D — по соплу в файле) — то же правило, что у отправки.
         "_bambu_ext_choice", "_bambu_goes_external", "_bambu_dual_nozzle", "_bambu_ext_why")
CONSTS = {"_REPORT_EMPTY_MAT", "_REQ_PROJECT_SETTINGS", "_REQ_SLICE_INFO", "_hook_plan_arg", "_QW_PLATE_RE",
          "HOOK_DEADLINE_S", "_hook_call_lock", "_hooks_lock", "_hook_busy", "_hook_owner", "HOOK_LATE_CAP",
          "_BAMBU_EXT_WHY"}
_src, _const_src, _const_seen = {}, [], set()
for node in _tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in FUNCS:
        _src[node.name] = ast.get_source_segment(SRC, node)
    elif isinstance(node, ast.Assign):
        names = set()
        for t in node.targets:
            if isinstance(t, ast.Name):
                names.add(t.id)
            elif isinstance(t, ast.Tuple):
                names.update(e.id for e in t.elts if isinstance(e, ast.Name))
        if names & CONSTS:
            _const_src.append(ast.get_source_segment(SRC, node))
            _const_seen |= (names & CONSTS)
check("1. исходники плана подачи, хуков и их констант найдены в server.py",
      all(n in _src for n in FUNCS) and _const_seen == CONSTS,
      (sorted(set(FUNCS) - set(_src)), sorted(CONSTS - _const_seen)))


class _Log:
    def __init__(self):
        self.lines = []

    def _rec(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(str(a))

    debug = info = warning = error = _rec


LOG = _Log()
NS = {"log": LOG, "_exc_brief": lambda: "test", "p_states": {}, "time": __import__("time"),
      "threading": __import__("threading"), "_loaded_modules": {},
      "io": io, "json": json, "re": re, "zipfile": zipfile, "os": os, "ET": ET,
      "_orch": _orch, "_gts": _gts, "_farm_settings_read": lambda: {"low_pct": 15},
      "_bslot": __import__("app.bambu_slot_match", fromlist=["x"]),      # 16.10.2026: одна раскладка
      "_bams": __import__("app.bambu_ams_state", fromlist=["x"]),        # 16.10.2026: состояние AMS
      "_print_hooks": {"pre_print_check": [], "after_dispatch": []}}
for s in _const_src:
    exec(s, NS)                    # noqa: S102 — исполняем СВОЙ же исходник в песочнице
for n in FUNCS:
    if n in _src:
        exec(_src[n], NS)          # noqa: S102
plan_of = NS["_launch_feed_plan"]


def mk3mf(types, plate_types=None):
    """.gcode.3mf: project_settings — филаменты проекта, slice_info — филаменты плиты."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps({
            "filament_type": types, "filament_colour": ["#FFFFFF"] * len(types),
            "filament_settings_id": ["fixture"] * len(types), "printer_model": "Bambu Lab P1S",
            "nozzle_diameter": ["0.4"]}))
        x = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>", "  <plate>",
             '    <metadata key="index" value="1"/>']
        for i, t in enumerate(plate_types if plate_types is not None else types):
            x.append('    <filament id="%d" type="%s" color="#FFFFFF" used_g="3.00"/>' % (i + 1, t))
        x += ["  </plate>", "</config>"]
        z.writestr("Metadata/slice_info.config", "\n".join(x))
        z.writestr("Metadata/plate_1.gcode", "; HEADER\nG28\n")
    return buf.getvalue()


def ams(pid, mats):
    NS["p_states"][pid] = {"status": "IDLE", "ams_trays": [
        {"index": i, "type": m, "color": "#FFFFFF", "color_raw": "FFFFFFFF", "remain": -1}
        for i, m in enumerate(mats)]}


def cfs(pid, cells, now=-1):
    NS["p_states"][pid] = {"status": "IDLE", "cfs_trays": [
        {"index": i, "type": (m or "Empty"), "label": _gts.slot_label(i), "code": ""}
        for i, m in enumerate(cells)], "cfs_now": now}


print("--- 1. план совпадает с тем, что решит транспорт ---")
F1 = mk3mf(["PLA"])
check("2. образец файла разобран (иначе все сверки ниже были бы вакуумными)",
      (NS["_3mf_filament_requirements"](F1) or {}).get("filament_count") == 1,
      NS["_3mf_filament_requirements"](F1))

NS["p_states"].clear()
NS["p_states"]["p1"] = {"status": "IDLE"}          # Bambu без AMS
p = plan_of("p1", "bambu", None, F1, None)
_use, _map, _m2 = NS["_bambu_resolve_ams"]("p1", None, F1)
check("3. Bambu без AMS: печать с внешней катушки — план [-1], external, как и решает запуск",
      p["slots"] == [-1] and p["external"] is True and _use is False, (p, _use, _map))

ams("p2", ["PETG", "PLA"])
p = plan_of("p2", "bambu", None, F1, None)
_use, _map, _m2 = NS["_bambu_resolve_ams"]("p2", None, F1)
check("4. Bambu с AMS: план равен карте слотов запуска (PLA лежит в слоте 1)",
      p["slots"] == list(_map) and p["slots"] == [1] and p["external"] is False, (p, _map))

p = plan_of("p2", "bambu", 0, F1, None)
check("5. выбран слот вручную — в плане ровно он", p["slots"] == [0] and p["source"] == "bambu_slot", p)

p = plan_of("p2", "bambu", -1, F1, None)
check("6. выбрана внешняя катушка — план [-1] и external", p["slots"] == [-1] and p["external"] is True, p)

F2 = mk3mf(["PLA", "PETG"])
ams("p3", ["PETG", "PLA"])
p = plan_of("p3", "bambu", None, F2, None)
_use, _map, _m2 = NS["_bambu_resolve_ams"]("p3", None, F2)
check("7. многоцветный файл: в плане слот для КАЖДОГО филамента, как в карте запуска",
      p["slots"] == list(_map) and len(p["slots"]) == 2, (p, _map))

cfs("k1", ["PETG", "PLA"], now=1)
p = plan_of("k1", "klipper", None, None, None)
_slots, _ext = NS["_klipper_dispatch_slots"]("k1", None)
check("8. Creality с CFS: план равен слоту, который сочтёт заправленным запуск",
      p["slots"] == list(_slots) and p["slots"] == [1] and p["external"] is False, (p, _slots))

p = plan_of("k1", "klipper", None, None, {"cfs_slot": 0})
check("9. выбрана ячейка в окне запуска — в плане ровно она",
      p["slots"] == [0] and p["source"] == "cfs_chosen", p)

cfs("k2", ["PETG", "PETG"], now=-1)      # два одинаковых материала: какой заправлен — неизвестно
p = plan_of("k2", "klipper", None, None, None)
_slots, _ext = NS["_klipper_dispatch_slots"]("k2", None)
check("10. CFS есть, а заправленную ячейку определить нельзя — пустой список, НЕ слот 0",
      p["slots"] == [] and list(_slots) == [] and p["source"] == "cfs_unknown", (p, _slots))

NS["p_states"]["ff"] = {"status": "IDLE"}
p = plan_of("ff", "flashforge", None, None, None)
check("11. FlashForge: одна подача — слот 0, как и уходит в списание после старта",
      p["slots"] == [0] and p["external"] is True, p)

p = plan_of("zz", "неизвестный", None, None, None)
check("12. незнакомый транспорт — плана нет (None), вызывающий ведёт себя как раньше",
      p["slots"] is None and p["confidence"] == "unknown", p)

p = plan_of("p2", "bambu", "мусор", F1, None)
check("13. мусор вместо слота не роняет план", isinstance(p, dict) and "slots" in p, p)


def mk_h2d(maps):
    """Файл под H2D: slice_info <plate> с filament_maps (1 — левое сопло, 2 — правое), два сопла."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps({
            "filament_type": ["PLA"], "filament_colour": ["#FFFFFF"], "printer_model": "Bambu Lab H2D",
            "nozzle_diameter": ["0.4", "0.4"]}))
        x = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>", "  <plate>", '    <metadata key="index" value="1"/>']
        if maps:
            x.append('    <metadata key="filament_maps" value="%s"/>' % maps)
        x += ['    <filament id="1" type="PLA" color="#FFFFFF" used_g="3.00"/>', "  </plate>", "</config>"]
        z.writestr("Metadata/slice_info.config", "\n".join(x))
        z.writestr("Metadata/plate_1.gcode", "; HEADER\nG28\n")
    return buf.getvalue()


#  16.10.2026 (R-137): левая внешняя катушка H2D — позиция -2 (Bambu 254). Хуки, не объявившие ext_left,
#  этот план видят пустым (см. обход хуков), поэтому старый склад правую катушку по ней не сверит.
NS["p_states"]["h2d"] = {"status": "IDLE", "nozzle_count": 2}
p = plan_of("h2d", "bambu", -1, mk_h2d("1"), None)
check("13b. H2D, файл под левое сопло: план {slots [-2], external, ext 254}",
      p["slots"] == [-2] and p["external"] is True and p.get("ext") == 254, p)
p = plan_of("h2d", "bambu", None, mk_h2d("2"), None)
check("13c. H2D без AMS, «Авто», файл под правое сопло: план [-1], ext 255", p["slots"] == [-1] and p.get("ext") == 255, p)
p = plan_of("h2d", "bambu", -1, mk_h2d(None), None)
check("13d. H2D, сопла в файле нет — запуск откажет; подача не определена: слотов нет (не «правая по умолчанию»)",
      p["slots"] == [] and p["confidence"] == "unknown", p)

print("--- 2. старый хук продолжает работать и продолжает блокировать ---")
calls = {"old": 0, "new": 0, "kw": 0}


def hook_old(printer_id, fdata, ams_slot, fname):
    calls["old"] += 1
    return {"status": "low_filament", "shortfall": [{"slot": ams_slot}]}


def hook_plan(printer_id, fdata, ams_slot, fname, plan=None):
    calls["new"] += 1
    calls["plan"] = plan
    return None


def hook_kwargs(printer_id, fdata, ams_slot, fname, **kw):
    calls["kw"] += 1
    calls["kwplan"] = kw.get("plan")
    return None


def hook_boom(printer_id, fdata, ams_slot, fname):
    raise TypeError("это исключение самого хука, а не несовпадение аргументов")


check("14. четырёхаргументный хук распознан как НЕ принимающий план",
      NS["_hook_wants_plan"](hook_old) is False)
check("15. хук с plan и хук с **kwargs распознаны как принимающие",
      NS["_hook_wants_plan"](hook_plan) is True and NS["_hook_wants_plan"](hook_kwargs) is True)
check("16. распознаватель не бросает даже на том, у чего нет сигнатуры",
      NS["_hook_wants_plan"](print) in (True, False) and NS["_hook_wants_plan"](None) is False)

NS["_print_hooks"]["pre_print_check"] = [hook_old]
r = NS["_run_pre_print_hooks"]("p1", b"", None, "f.3mf", plan={"slots": [1], "source": "bambu_auto"})
check("17. хук с ЧЕТЫРЬМЯ аргументами вызван и его блокировка дошла (план ему не передан)",
      calls["old"] == 1 and isinstance(r, dict) and r.get("status") == "low_filament", (calls, r))

NS["_print_hooks"]["pre_print_check"] = [hook_plan]
r = NS["_run_pre_print_hooks"]("p1", b"", None, "f.3mf", plan={"slots": [1], "source": "bambu_auto"})
check("18. хук, объявивший plan, получает план целиком",
      calls["new"] == 1 and (calls.get("plan") or {}).get("slots") == [1] and r is None, calls)

NS["_print_hooks"]["pre_print_check"] = [hook_kwargs]
NS["_run_pre_print_hooks"]("p1", b"", None, "f.3mf", plan={"slots": [0]})
check("19. хук с **kwargs тоже получает план", (calls.get("kwplan") or {}).get("slots") == [0], calls)

NS["_print_hooks"]["pre_print_check"] = [hook_boom, hook_old]
calls["old"] = 0
r = NS["_run_pre_print_hooks"]("p1", b"", None, "f.3mf", plan={"slots": [2]})
check("20. упавший хук пропускается, следующий работает и блокирует",
      calls["old"] == 1 and isinstance(r, dict) and r.get("status") == "low_filament", (calls, r))

NS["_print_hooks"]["pre_print_check"] = [hook_old]
calls["old"] = 0
r = NS["_run_pre_print_hooks"]("p1", b"", None, "f.3mf")
check("21. без плана всё как раньше: тот же вызов, та же блокировка",
      calls["old"] == 1 and isinstance(r, dict) and r.get("status") == "low_filament", (calls, r))

print("--- 3. план ничего не отправляет и не пишет ---")
_PLAN_SRC = _src["_launch_feed_plan"]
check("22. в плане подачи нет ни команд принтеру, ни записи в базу",
      all(bad not in _PLAN_SRC for bad in ("publish(", "urlopen", "conn_pr", "conn_p.", "INSERT",
                                           "UPDATE", "_send_mgr", "requests.")))
check("23. план зовёт РЕШАЮЩИЕ функции запуска, а не свою копию правил",
      "_bambu_resolve_ams(" in _PLAN_SRC and "_klipper_dispatch_slots(" in _PLAN_SRC)
#  16.10.2026: проверки 24-25 — по поведению и по дереву разбора, а не по тексту вызова (вызов
#  уехал в asyncio.to_thread, R-148).
NS["_print_hooks"]["pre_print_check"] = [hook_old, hook_plan]
calls["old"] = calls["new"] = 0
_adv24 = []
r = NS["_run_pre_print_hooks"]("p1", b"", None, "f.3mf", advice_out=_adv24, plan={"slots": [3]})
check("24. пятый аргумент уходит только тем, кто его объявил: четырёхаргументный хук не упал на лишнем "
      "аргументе (иначе было бы уведомление «проверка не выполнена»), хук с plan получил план",
      calls["old"] == 1 and calls["new"] == 0 and isinstance(r, dict) and not _adv24, (calls, r, _adv24))
NS["_print_hooks"]["pre_print_check"] = [hook_plan]
NS["_run_pre_print_hooks"]("p1", b"", None, "f.3mf", advice_out=_adv24, plan={"slots": [3]})
check("24b. … и хук с plan получает его целиком", (calls.get("plan") or {}).get("slots") == [3] and not _adv24, calls)
_fn_nodes = {n.name: n for n in _tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
_uses_plan = sorted(fn for fn in ("u_print_path", "_do_project2_file_print", "part_print", "_enqueue_preflight")
                    if fn in _fn_nodes and any(isinstance(x, ast.Name) and x.id == "_launch_feed_plan"
                                               for x in ast.walk(_fn_nodes[fn])))
check("25. ядро зовёт план на всех трёх путях запуска (одиночный, проектный, очередь/пачка)",
      _uses_plan == ["_do_project2_file_print", "_enqueue_preflight", "part_print", "u_print_path"], _uses_plan)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
