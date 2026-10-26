# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.920 — очередь ожидания и подбор принтера (заказ владельца 28.08.2026).

ЗАЧЕМ. Эта часть решает, НА ЧЁМ печатать, и потому ошибается дорого: не тот принтер — это
испорченная печать и потраченный пластик без человека рядом. Владелец разрешил хранение в базе
и выбрал первый этап «сервер находит принтер, запускает владелец». Проверяется ИСПОЛНЕНИЕМ
самое опасное:
  1. подбор НЕ выбирает принтер, которому запуск из очереди не разрешён;
  2. подбор НЕ выбирает занятый принтер (в том числе уже стоящий в очереди запусков);
  3. подбор НЕ выбирает принтер без нужного материала;
  4. материал файла неизвестен -> НИКТО не выбирается, строка ждёт владельца;
  5. причина отказа называется точно, а не «не получилось».

15.09.2026 — ПОДБОР ПЕРЕПИСАН после слова владельца: склада на ферме нет, материал задан на самом
принтере и совпадает с файлом, а очередь пишет «у свободных принтеров нет нужного материала».
Здесь же закреплено исполнением то, что нашла проверка:
  6. внешняя катушка Bambu участвует в подборе, и запуск идёт именно с неё (ams_slot=-1);
  7. от файла требуются материалы нарезанной плиты, а не всего проекта;
  8. «программа не видит материал» — отдельная причина, а не «нет материала»;
  9. файл не уходит на принтер, под который не нарезан; занятый отменой принтер не свободен;
 10. K2 по g-code: нужный материал обязан лежать в той ячейке, что указана в файле;
 11. материалы файла читаются живыми, запуск уходит ровно на подтверждённый принтер;
 12. зеркало раскладки по AMS в опросе совпадает с настоящим подбором запуска.
16.10.2026 (R-141, R-016, R-115, R-008, R-117), разделы 13-14:
 13. FlashForge — подбор «по слову человека» только на ручной запуск, автомат его не берёт;
 14. строка и окно запуска называют, куда пойдёт филамент, и «цвет отличается» / «другой вариант»;
 15. «Печатать всё равно» из очереди ({skip_filament: true}) и то же окно «Материал закончился»;
 16. причина возврата в ожидание — кодом в базе и словами на экране; «принял, но не начал» —
     «требует внимания».

БЕЗОПАСНОСТЬ — ЧИТАТЬ ПЕРЕД ПРАВКОЙ. Рабочая база НЕ открывается: сервер целиком не
импортируется. Берётся ИСХОДНЫЙ ТЕКСТ нужных функций из server.py и исполняется в отдельном
пространстве имён поверх ВРЕМЕННОЙ базы и временных файлов. Так проверяется настоящий код, но ни
одна строка владельца не может быть затронута — первая версия этого теста импортировала server и
стёрла бы принтеры из рабочей базы; так делать нельзя. Файлы-образцы собраны здесь по правилам
записи Bambu Studio (bbs_3mf.cpp) и по устройству файлов Creality Print, а не взяты у владельца.

Запуск:  python tools/test_queue_wait.py
"""
import ast
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SENTINEL = "QUEUE_WAIT_SENTINEL_2_920"
PASS = FAIL = 0

from app import project_orchestrator as _orch          # noqa: E402 — чистые модули, без сервера
from app import bambu_start_policy as _bstart          # noqa: E402
from app import gcode_tool_slot as _gts                # noqa: E402
from app import bambu_slot_match as _bslot             # noqa: E402 — 16.10.2026: одна раскладка по слотам
from app import bambu_ams_state as _bams               # noqa: E402 — 16.10.2026: состояние AMS
from app.model_compat import detect_target, _models_compatible, _BAMBU_CODES   # noqa: E402
from app.utils import _normalize_model                 # noqa: E402
from app.part_counter import is_3mf_printable          # noqa: E402


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


SRC = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
REG = io.open(os.path.join(ROOT, "app", "route_policy_registry.py"), encoding="utf-8").read()

print("--- 1. устройство закреплено в исходнике ---")
check("1. таблица очереди ожидания создаётся неразрушающе",
      "CREATE TABLE IF NOT EXISTS queue_wait" in SRC)
check("2. флаг разрешения у принтера по умолчанию ВЫКЛЮЧЕН",
      "queue_allowed INTEGER DEFAULT 0" in SRC)
check("3. очередь ожидания НЕ заводит своего запуска печати, а зовёт существующую очередь",
      "api_print_queue_enqueue({" in SRC and "def api_queue_wait_start" in SRC)
check("4. все пять маршрутов объявлены в реестре прав",
      all(p in REG for p in ("'/api/queue-wait'", "'/api/queue-wait/add'",
                             "'/api/queue-wait/remove'", "'/api/queue-wait/start'",
                             "'/api/printer/queue-allowed'")))
check("5. изменения очереди требуют того же права, что и постановка в очередь запусков",
      REG.count("'/api/queue-wait/add', 'api_queue_wait_add', 'print', 'browser', 'OPERATIONAL', "
                "('DATABASE', 'QUEUE'), 'NONE', 'project'") == 1)

print("--- 2. подбор принтера: НАСТОЯЩИЙ код на временной базе ---")
_tree = ast.parse(SRC)
FUNCS = ("_reported_material_norm", "_norm_hex_color", "_apply_vt_tray", "_bambu_ext_slots",
         "_3mf_req_from_project_settings", "_3mf_req_from_slice_info", "_3mf_filament_requirements",
         "_bambu_ams_mapping", "_tray_remain", "_ams_low_pct", "_bambu_auto_slot_map",
         #  16.10.2026 (R-006): сопла филаментов H2D из файла — помощник плиты, его зовут подбор
         #  запуска и сведения очереди о файле; без него обе падали бы в песочнице NameError.
         "_3mf_filament_sides", "_3mf_side_values",
         #  16.10.2026 (R-138): занятость по стадии — одно правило с запуском (_bambu_stage_busy);
         #  _bambu_busy_now — то, чем запуск решает «слать ли команду», для сверки правил.
         "_bambu_stage_busy", "_bambu_stage_base_of", "_bambu_busy_now", "_bambu_print_started",
         #  16.10.2026 (R-138, проверка пакета): чем занят принтер — словами запуска (строка очереди).
         "_qw_busy_words", "_bambu_busy_reason", "_bambu_stage_text",
         #  16.10.2026 (R-137): выбор внешней катушки запуском — для сверки с вердиктом очереди.
         "_bambu_ext_choice", "_bambu_dual_nozzle", "_bambu_ext_why",
         "_send_working_stage", "_send_printer_status", "_file_type_class", "_compatible_pids_for",
         "_qw_printer_name", "_qw_row", "_qw_blank_info", "_3mf_plate_used", "_qw_3mf_info",
         "_qw_gcode_info", "_qw_file_info", "_qw_mats", "_qw_ctx", "_qw_busy_verdict",
         "_qw_printer_feed", "_qw_feed", "_qw_auto_slot_mirror", "_qw_bambu_ams_proof", "_qw_bambu_verdict",
         "_qw_klipper_verdict", "_qw_material_verdict", "_qw_compatible", "_qw_match", "_qw_public",
         "_qw_finish", "_qw_launch_outcome", "_qw_recover_launching", "api_print_queue_cancel",
         "api_print_queue_recovery_cancel", "api_queue_wait_remove",
         "api_queue_wait_get", "api_queue_wait_add", "api_queue_wait_start",
         #  16.09.2026: путь запуска ПОСЛЕ захвата строки вынесен в общую функцию — ею пользуются
         #  и запуск по кнопке, и автозапуск. Без неё в песочнице api_queue_wait_start падает
         #  NameError, а проверки запуска молча перестают что-либо мерить.
         "_qw_launch_claimed",
         #  16.09.2026: разбор исхода считает неудачи автозапуска (_qw_auto_bump/_qw_auto_ok).
         #  Без них _qw_launch_outcome падает в песочнице NameError.
         "_qw_auto_bump", "_qw_auto_ok", "_qw_auto_mark",
         #  16.10.2026 (R-016, R-115, R-118, R-141, R-117): подробность подачи по слотам, FlashForge,
         #  правило «автомат или человек», элемент очереди запусков и слушатель неподтверждённого старта.
         "_qw_ams_label", "_qw_slot_detail", "_qw_flashforge_verdict", "_qw_auto_needs_human",
         "_qw_item", "_qw_start_unconfirmed")
CONSTS = {"_REPORT_EMPTY_MAT", "_BAMBU_EXT_MAIN", "_REQ_PROJECT_SETTINGS", "_REQ_SLICE_INFO",
          "_ACTIVE_RAW", "_QW_FILE_CACHE_MAX", "_QW_GCODE_HEAD", "_QW_GCODE_TAIL", "_QW_CAND_MAX",
          "_QW_PLATE_RE", "_qw_file_cache", "_qw_file_lock", "_QW_MISMATCH", "_QW_UNFIT", "_QW_VERDICT_ORDER",
          "_QW_BED_RAW", "_QW_SENT_NOT_STARTED", "_qw_auto_fails", "_QW_AUTO_FAILS_MAX", "_qw_auto_inflight",
          "_bambu_stage_base", "_BAMBU_STAGE_BASE_TTL", "_BAMBU_ACTIVE_RAW", "_BAMBU_EXT_WHY"}
_fn_src, _const_src = {}, []
for node in _tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in FUNCS:
        _fn_src[node.name] = ast.get_source_segment(SRC, node)
    elif isinstance(node, ast.Assign):
        names = set()
        for t in node.targets:
            if isinstance(t, ast.Name):
                names.add(t.id)
            elif isinstance(t, ast.Tuple):
                names.update(e.id for e in t.elts if isinstance(e, ast.Name))
        if names & CONSTS:
            _const_src.append(ast.get_source_segment(SRC, node))
check("6. исходники функций подбора найдены в server.py",
      all(n in _fn_src for n in FUNCS), sorted(set(FUNCS) - set(_fn_src)))

_tmp = tempfile.mkdtemp(prefix="qw920_")
_db = os.path.join(_tmp, "printers.db")
conn = sqlite3.connect(_db, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("CREATE TABLE printers (id TEXT PRIMARY KEY, name TEXT, type TEXT, model TEXT, "
             "ip TEXT DEFAULT '10.0.0.99', token TEXT DEFAULT 'FIXTURE_TOKEN', "
             "queue_allowed INTEGER DEFAULT 0)")
conn.execute("CREATE TABLE print_launch_queue (id TEXT PRIMARY KEY, status TEXT DEFAULT 'pending', "
             "payload TEXT DEFAULT '{}', updated_at REAL DEFAULT 0, last_error TEXT DEFAULT '')")
conn.execute("CREATE TABLE queue_wait (id TEXT PRIMARY KEY, gcode_file TEXT NOT NULL, "
             "source TEXT DEFAULT 'quick', part_name TEXT DEFAULT '', material TEXT DEFAULT '', "
             "state TEXT DEFAULT 'waiting', note TEXT DEFAULT '', created_at REAL DEFAULT 0, "
             "updated_at REAL DEFAULT 0)")
conn.commit()


class _Log:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _SendMgr:
    """Заглушка менеджера отправок: свободен всегда, если не сказано иное."""
    def __init__(self):
        self.reserved = set()
        self.holds = {}

    def reserved_ids(self):
        return set(self.reserved)

    def get_hold(self, pid):
        return self.holds.get(pid)

    def cancel_reserved(self, sjid, why=""):
        self.reserved.discard(sjid)
        return True


FILES = {}
ENQ = []
_seq = [0]


def _uid(prefix):
    _seq[0] += 1
    return "%s%d" % (prefix, _seq[0])


def _pf_printer_row(pid):
    return conn.execute("SELECT * FROM printers WHERE id=?", (pid,)).fetchone()


def _enqueue(data):
    items = list((data or {}).get("items") or [])
    ENQ.extend(items)
    return {"status": "ok", "queued": [it["printer_id"] for it in items], "held": [],
            "blocked": [], "notes": []}


STALE_FAIL_S = 60.0        # как в app/diagnostics.py
NS = {"log": _Log(), "conn_pr": conn, "lock_pr": threading.RLock(), "lock_p": threading.RLock(),
      "print_queue": [], "print_queue_lock": threading.RLock(), "p_states": {},
      "_send_mgr": _SendMgr(), "_exc_brief": lambda: "test", "last_seen": {},
      "STALE_FAIL_S": STALE_FAIL_S, "time": time, "os": os, "io": io, "re": re, "json": json,
      "zipfile": zipfile, "ET": ET, "threading": threading, "Dict": Dict, "Any": Any,
      "_orch": _orch, "_bstart": _bstart, "_gts": _gts, "detect_target": detect_target,
      "_bslot": _bslot, "_bams": _bams,
      "_models_compatible": _models_compatible, "_BAMBU_CODES": _BAMBU_CODES,
      "_normalize_model": _normalize_model, "_is_3mf_printable": is_3mf_printable,
      "_farm_settings_read": lambda: {"low_pct": 15}, "_printer_model_code": lambda pid: None,
      "_staging_path": lambda fname, part=None: FILES.get(os.path.basename(fname or "")),
      "_uid": _uid, "_pf_printer_row": _pf_printer_row, "api_print_queue_enqueue": _enqueue,
      "_plq_set_status": lambda *a, **k: None, "_print_queue_public": lambda: [],
      "_jsonmod": json}
for s in _const_src:
    exec(s, NS)                          # noqa: S102 — исполняем СВОЙ же исходник в песочнице
for n in FUNCS:
    if n in _fn_src:
        exec(_fn_src[n], NS)             # noqa: S102
M = NS


def _reset():
    conn.execute("DELETE FROM printers")
    conn.execute("DELETE FROM queue_wait")
    conn.commit()
    NS["p_states"].clear()
    NS["last_seen"].clear()
    NS["print_queue"][:] = []
    NS["_send_mgr"].reserved.clear()
    NS["_send_mgr"].holds.clear()
    NS["_qw_file_cache"].clear()
    ENQ[:] = []


def printer(pid, name, allowed=True, status="IDLE", ptype="bambu", model="P1S", ams=None,
            ext=None, ext_left=None, cfs=None, raw=None, stage=None, noz=None, print_type=None):
    conn.execute("INSERT OR REPLACE INTO printers (id, name, type, model, queue_allowed) "
                 "VALUES (?,?,?,?,?)", (pid, name, ptype, model, 1 if allowed else 0))
    conn.commit()
    st = {"status": status, "status_raw": status if raw is None else raw}
    if noz is not None:
        st["nozzle_count"] = noz
    if ams is not None:
        st["ams_trays"] = [({"index": i, "type": m, "color": "#FFFFFF", "color_raw": "FFFFFFFF",
                             "remain": -1} if isinstance(m, str) else dict(m, index=i))
                           for i, m in enumerate(ams)]
    ext_trays = {}
    if ext is not None:
        ext_trays["255"] = {"tray_id": "255", "tray_type": ext, "tray_color": ""}
    if ext_left is not None:
        ext_trays["254"] = {"tray_id": "254", "tray_type": ext_left, "tray_color": ""}
    if ext_trays:
        st["ext_trays"] = ext_trays
    if cfs is not None:
        trays = []
        for i, (mat, named) in enumerate(cfs):
            if not mat:
                trays.append({"index": i, "type": "Empty", "code": "", "label": _gts.slot_label(i)})
            else:
                trays.append({"index": i, "type": mat if named else "000003",
                              "code": "000003", "label": _gts.slot_label(i)})
        st["cfs_trays"] = trays
    if stage is not None:
        st["stage"] = stage
    if print_type is not None:
        st["print_type"] = print_type
    NS["p_states"][pid] = st
    NS["last_seen"][pid] = time.time()      # свежая телеметрия, если не сказано иное


def mk3mf(name, project_types, plates, model="Bambu Lab P1S", slice_info=True, nozzles=1,
          sliced=True, colours=None, extra_ps=None, plate_meta=None, used_g=None):
    """.gcode.3mf по правилам записи Bambu Studio: project_settings — все филаменты проекта,
    slice_info — по <plate> только филаменты, ушедшие в печать; plates = {номер: [(id, тип)]}.
    16.10.2026: colours — цвета филаментов проекта; extra_ps — прочие ключи project_settings
    (filament_is_support, filament_ids, filament_map); plate_meta — metadata плиты в slice_info
    (filament_maps); used_g — {id: граммы} вместо «3.00» (R-016: 0 — плита филамент не расходует)."""
    path = os.path.join(_tmp, name)
    with zipfile.ZipFile(path, "w") as z:
        _ps = {"filament_type": project_types,
               "filament_colour": list(colours) if colours else ["#FFFFFF"] * len(project_types),
               "filament_settings_id": ["fixture"] * len(project_types), "printer_model": model,
               "nozzle_diameter": ["0.4"] * nozzles}
        _ps.update(extra_ps or {})
        z.writestr("Metadata/project_settings.config", json.dumps(_ps))
        if slice_info:
            x = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
            for no, fl in plates.items():
                x.append("  <plate>")
                x.append('    <metadata key="index" value="%d"/>' % no)
                for _k, _v in (plate_meta or {}).items():
                    x.append('    <metadata key="%s" value="%s"/>' % (_k, _v))
                for fid, ftype in fl:
                    x.append('    <filament id="%d" type="%s" color="#FFFFFF" used_m="1.00" '
                             'used_g="%s"/>' % (fid, ftype, (used_g or {}).get(fid, "3.00")))
                x.append("  </plate>")
            x.append("</config>")
            z.writestr("Metadata/slice_info.config", "\n".join(x))
        if sliced:
            for no in plates:
                z.writestr("Metadata/plate_%d.gcode" % no, "; HEADER_BLOCK_START\nG28\n")
        z.writestr("3D/3dmodel.model", "<model/>")
    FILES[name] = path
    return path


def mkgcode(name, types, used_g, tools, model="Creality K2 Plus", pad=40, colours=None):
    """Плоский g-code в устройстве Creality Print: T<n> в начале, блок настроек в конце.
    16.10.2026: colours — строка «; filament_colour = #RRGGBB;…» блока настроек (R-016, R-118)."""
    lines = ["; generated by Creality Print", "START_PRINT EXTRUDER_TEMP=250 BED_TEMP=70"]
    lines += ["T%d" % t for t in tools]
    lines += ["G1 X10 Y10 E0.5"] * pad
    if used_g is not None:
        lines.append("; filament used [g] = " + ", ".join(used_g))
    lines.append("; printer_model = " + model)
    if types is not None:
        lines.append("; filament_type = " + ";".join(types))
    if colours is not None:
        lines.append("; filament_colour = " + ";".join(colours))
    path = os.path.join(_tmp, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    FILES[name] = path
    return path


def info_of(name):
    return M["_qw_file_info"](name, "", True)


def match(name, prefer=""):
    info, fdata = info_of(name)
    return M["_qw_match"](info, fdata, None, prefer)


def verdict_of(m, pid):
    return next((c["verdict"] for c in m["candidates"] if c["id"] == pid), None)


mk3mf("pla.gcode.3mf", ["PLA"], {1: [(1, "PLA")]})
mk3mf("pla_abs.gcode.3mf", ["PLA", "ABS"], {1: [(1, "PLA"), (2, "ABS")]})
mkgcode("nocfg.gcode", None, None, [], model="Creality K2 Plus")

_reset()
printer("p1", "X1C-01", allowed=False, ams=["PLA"])
m = match("pla.gcode.3mf")
check("7. без разрешения принтер НЕ выбирается, причина названа",
      m["pid"] == "" and m["reason"] == "not_allowed", m)

_reset()
printer("p1", "X1C-01", status="RUNNING", ams=["PLA"])
m = match("pla.gcode.3mf")
check("8. занятый печатью принтер НЕ выбирается, причина «занят»",
      m["pid"] == "" and m["reason"] == "busy", (m["pid"], m["reason"]))

_reset()
printer("p1", "X1C-01", ams=["PETG"])
m = match("pla.gcode.3mf")
check("9. принтер без нужного материала НЕ выбирается, причина «нет материала»",
      m["pid"] == "" and m["reason"] == "no_material", (m["pid"], m["reason"]))

_reset()
printer("p1", "K2-01", ptype="klipper", model="Creality K2 Plus", cfs=[("PLA", True)])
m = match("nocfg.gcode")
check("10. неизвестный материал файла — ждём владельца, никто не выбирается",
      m["pid"] == "" and m["reason"] == "material_unknown", (m["pid"], m["reason"]))

_reset()
printer("p1", "X1C-01", ams=["PLA", "PETG"])
m = match("pla.gcode.3mf")
check("11. подходящий принтер найден и назван",
      m["pid"] == "p1" and m["reason"] == "ready" and m["name"] == "X1C-01", m)

_reset()
printer("p1", "БЕЗ-РАЗРЕШЕНИЯ", allowed=False, ams=["PLA"])
printer("p2", "ЗАНЯТ", status="RUNNING", ams=["PLA"])
printer("p3", "ГОДНЫЙ", ams=["PLA"])
m = match("pla.gcode.3mf")
check("12. из трёх машин выбрана единственная годная", m["pid"] == "p3", (m["pid"], m["reason"]))

_reset()
printer("p1", "ОДИН", ams=["PLA"])
printer("p2", "ОБА", ams=["PLA", "ABS"])
m = match("pla_abs.gcode.3mf")
check("13. при двух материалах выбран принтер, где есть оба", m["pid"] == "p2", (m["pid"], m["reason"]))

_reset()
printer("p1", "В-ОЧЕРЕДИ", ams=["PLA"])
NS["print_queue"].append({"id": "q1", "printer_id": "p1", "due_ts": time.time() + 60})
m = match("pla.gcode.3mf")
check("14. принтер, уже стоящий в очереди запусков, не назначается второй раз",
      m["pid"] == "" and m["reason"] == "busy" and verdict_of(m, "p1") == "in_queue", m)

_reset()
printer("p1", "ОТПРАВКА", ams=["PLA"])
NS["_send_mgr"].reserved.add("p1")
m = match("pla.gcode.3mf")
check("15. принтер, занятый отправкой, не назначается",
      m["pid"] == "" and m["reason"] == "busy", (m["pid"], m["reason"]))

_reset()
printer("p1", "УДЕРЖАН", ams=["PLA"])
NS["_send_mgr"].holds["p1"] = {"owner_type": "test"}
m = match("pla.gcode.3mf")
check("16. удержанный принтер не назначается", m["pid"] == "" and m["reason"] == "busy", m["reason"])

_reset()
printer("p1", "ОФЛАЙН", status="OFFLINE", ams=["PLA"])
m = match("pla.gcode.3mf")
check("17. принтер не на связи не назначается",
      m["pid"] == "" and m["reason"] == "busy" and verdict_of(m, "p1") == "offline", m)

_reset()
printer("p1", "ЗАКОНЧИЛ", status="FINISH", ams=["PLA"])
m = match("pla.gcode.3mf")
check("18. принтер, закончивший печать, считается свободным (с пометкой «проверьте стол»)",
      m["pid"] == "p1" and m["finished"] is True, (m["pid"], m["finished"]))

_reset()
printer("p1", "РЕГИСТР", ams=["pla"])
m = match("pla.gcode.3mf")
check("19. материал сверяется без учёта регистра", m["pid"] == "p1", (m["pid"], m["reason"]))

#  2.978. Принтер, выключенный или выпавший из сети, оставляет на карточке последний отчёт
#  («IDLE»), и подбор считал его свободным — запуск уходил в никуда.
_reset()
printer("p1", "МОЛЧУН", ams=["PLA"])
NS["last_seen"]["p1"] = time.time() - (STALE_FAIL_S + 30)
m = match("pla.gcode.3mf")
check("20. принтер с несвежей телеметрией не выбирается", m["pid"] == "" and m["reason"] == "busy", m["reason"])

_reset()
printer("p1", "ПРОПАЛ", ams=["PLA"])
NS["last_seen"].pop("p1", None)
m = match("pla.gcode.3mf")
check("21. принтер, о котором не было ни одного отчёта, не выбирается", m["pid"] == "", m["reason"])

_reset()
printer("p1", "OFFLINE", ams=["PLA"])
NS["p_states"]["p1"]["status"] = "OFFLINE"
m = match("pla.gcode.3mf")
check("22. принтер со статусом «не на связи» не выбирается", m["pid"] == "", m["reason"])

_reset()
printer("p1", "ЖИВОЙ", ams=["PLA"])
m = match("pla.gcode.3mf")
check("23. свежий свободный принтер по-прежнему выбирается", m["pid"] == "p1", m["reason"])

print("--- 3. честность закреплена в тексте ---")
check("24. в исходнике сказано, что запуск идёт через существующую очередь, а не свой путь",
      "второй очереди запуска не заводится" in SRC or "Своего пути" in SRC)
check("25. решения владельца записаны рядом с кодом",
      "С ПОДТВЕРЖДЕНИЕМ" in SRC and "ЖДЁТ владельца" in SRC)

print("--- 4. строка запускается ровно один раз (2.978) ---")
#  Две вкладки на разных компьютерах нажимали «Запустить» почти одновременно, и один файл
#  уходил на два принтера. Строка занимается атомарно: UPDATE ... WHERE state='waiting'.
_START = SRC[SRC.index("def api_queue_wait_start"):SRC.index("def api_printer_queue_allowed")]
check("26. строка занимается условным UPDATE, а не просто читается",
      "UPDATE queue_wait SET state='starting'" in _START
      and "AND state IN ('waiting','attention')" in _START)
check("27. занять смогла только одна попытка — иначе отказ",
      "rowcount != 1" in _START and "already_started" in _START)
#  16.10.2026 (R-117): возврат в ожидание теперь пишет и причину (_qw_release(<код>)) — само
#  поведение проверяется исполнением ниже (раздел 13); здесь — что возвратов по-прежнему несколько.
check("28. при неудачном подборе или отказе постановки строка возвращается в ожидание",
      _START.count("_qw_release(") >= 3 and "state='waiting'" in _START)
check("29. застрявшая строка возвращается в ожидание при запуске программы",
      "UPDATE queue_wait SET state='waiting' WHERE state='starting'" in SRC)

print("--- 5. сценарий владельца: материал задан на самом принтере (внешняя катушка Bambu) ---")
#  Настоящая форма отчёта P1P без AMS (ha-bambulab MOCK-P1PNOAMS): vt_tray на уровне print, ams.ams=[].
mk3mf("petg.gcode.3mf", ["PETG"], {1: [(1, "PETG")]})
_p1p = {"ams": {"ams": [], "tray_now": "254"},
        "vt_tray": {"id": "254", "tray_info_idx": "GFG99", "tray_type": "PETG", "tray_color": "FFFFFFFF"}}
_reset()
printer("p1s", "P1S-01")
NS["p_states"]["p1s"]["ext_trays"] = M["_bambu_ext_slots"]({}, _p1p)
m = match("petg.gcode.3mf")
check("30. P1S без AMS и без склада: PETG на внешней катушке (как в отчёте принтера) — принтер найден",
      m["pid"] == "p1s" and m["reason"] == "ready" and (m["feed"] or {}).get("kind") == "external", m)

_reset()
printer("p1s", "P1S-01", ext="PETG")
_add = M["api_queue_wait_add"]({"gcode_file": "petg.gcode.3mf"})
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p1s"})
check("31. запуск такой строки ставит в очередь печать ИМЕННО с внешней катушки (ams_slot=-1)",
      _st.get("ok") is True and len(ENQ) == 1 and ENQ[0].get("ams_slot") == -1
      and ENQ[0].get("printer_id") == "p1s" and _st.get("feed") == "external", (_st, ENQ))

_reset()
printer("p1", "AMS-ПУСТ", ams=["Empty", "Empty", "Empty", "Empty"], ext="PLA")
m = match("pla.gcode.3mf")
check("32. все слоты AMS пусты, PLA на внешней — печать с внешней катушки",
      m["pid"] == "p1" and (m["feed"] or {}).get("kind") == "external", m)

_reset()
printer("p1", "AMS-PETG", ams=["PETG"], ext="PLA")
m = match("pla.gcode.3mf")
check("33. в AMS только PETG, PLA на внешней — печать с внешней катушки, а не из AMS",
      m["pid"] == "p1" and (m["feed"] or {}).get("kind") == "external", m)

_reset()
printer("p1", "AMS-PLA", ams=["PLA"], ext="PLA")
_add = M["api_queue_wait_add"]({"gcode_file": "pla.gcode.3mf"})
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p1"})
check("34. PLA есть в AMS — запуск как раньше, «Авто» из AMS, без принудительной внешней катушки",
      _st.get("ok") is True and ENQ and "ams_slot" not in ENQ[0] and _st.get("feed") == "ams", (_st, ENQ))

mk3mf("pla_petg.gcode.3mf", ["PLA", "PETG"], {1: [(1, "PLA"), (2, "PETG")]})
_reset()
printer("p1", "AMS-PLA+ВНЕШ-PETG", ams=["PLA"], ext="PETG")
m = match("pla_petg.gcode.3mf")
check("35. двухматериальный файл не собирается из AMS и внешней катушки — не подходит",
      m["pid"] == "" and m["reason"] == "no_material", (m["pid"], m["reason"], m["candidates"]))

_reset()
printer("p1", "X1C-БЕЗ-КАТУШКИ", model="X1C", ext="")
mk3mf("pla_x1.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, model="Bambu Lab X1 Carbon")
m = match("pla_x1.gcode.3mf")
check("36. внешняя катушка без материала — «на принтере не задан материал», а не угадывание",
      m["pid"] == "" and verdict_of(m, "p1") == "printer_empty" and m["reason"] == "no_material", m)

mk3mf("pla_h2d.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, model="Bambu Lab H2D", nozzles=2)
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ext_left="PLA")
m = match("pla_h2d.gcode.3mf")
#  16.10.2026 (R-137): вердикта «left_spool» больше нет — с левой катушки очередь запускает, когда файл нарезан
#  под левое сопло. В этом файле сопла не видно (filament_maps нет) — и об этом сказано прямо.
check("37. H2D: PLA на левой внешней катушке, а в файле не видно, каким соплом печатать — не запускается, причина названа",
      m["pid"] == "" and verdict_of(m, "h2d") == "ext_side_unknown", m)

mk3mf("petg_p2s.gcode.3mf", ["PETG"], {1: [(1, "PETG")]}, model="Bambu Lab P2S")
_reset()
printer("p2s", "P2S-01", model="P2S")
NS["p_states"]["p2s"]["ext_trays"] = M["_bambu_ext_slots"]({}, {"vir_slot": [
    {"id": "255", "tray_type": "PETG", "tray_color": "000000FF"}]})
m = match("petg_p2s.gcode.3mf")
check("38. P2S: внешняя катушка из vir_slot (255) видна подбору", m["pid"] == "p2s", m)

mk3mf("proj2_plate_petg.gcode.3mf", ["PLA", "PETG"], {1: [(2, "PETG")]})
_reset()
printer("p1", "P1S-ВНЕШ-PETG", ext="PETG")
m = match("proj2_plate_petg.gcode.3mf")
#  16.10.2026 (R-137): внешняя катушка разрешена, когда ПЛИТА печатает один материал (а не проект объявляет
#  один) — запуск дополняет команду записью «не назначен» для остальных филаментов проекта, как Bambu Studio.
check("39. проект объявляет два филамента, плита печатает один PETG, катушка внешняя — принтер найден, печать с внешней",
      m["pid"] == "p1" and verdict_of(m, "p1") == "ready" and (m["feed"] or {}).get("kind") == "external", m)
mk3mf("proj2_plate_both.gcode.3mf", ["PETG", "PETG"], {1: [(1, "PETG"), (2, "PETG")]})
m = match("proj2_plate_both.gcode.3mf")
check("39b. плита печатает два филамента (оба PETG) — с одной внешней катушки нельзя, причина названа",
      m["pid"] == "" and verdict_of(m, "p1") == "ext_multi" and m["reason"] == "no_material", m)

_reset()
printer("a1", "БЕЗ-PLA", ams=["PETG"])
#  16.10.2026 (R-141): FlashForge теперь получает свои вердикты (раздел 13). Принтер, который материал
#  не сообщает вовсе, — Bambu без AMS, от которого не пришло ни одной катушки.
printer("nb", "P1S-БЕЗ-ДАННЫХ")
mk3mf("pla_nomodel.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, model="")
m = match("pla_nomodel.gcode.3mf")
check("40. принтер, не сообщающий материал, — «программа не видит материал», а не «нет материала»",
      m["pid"] == "" and m["reason"] == "printer_material_unknown"
      and verdict_of(m, "nb") == "material_unknown_on_printer" and verdict_of(m, "a1") == "material_mismatch", m)

print("--- 6. материалы — по нарезанной плите, а не по всему проекту ---")
mk3mf("proj4.gcode.3mf", ["PLA", "PETG", "PLA", "ABS"], {1: [(2, "PETG")]})
_reset()
printer("p1", "AMS-PETG", ams=["Empty", "PETG", "Empty", "Empty"])
_i, _ = info_of("proj4.gcode.3mf")
m = M["_qw_match"](_i)
check("41. проект на 4 материала (синхронизация с AMS), плита печатает PETG — требуется только PETG, принтер найден",
      M["_qw_mats"](_i) == ["PETG"] and _i["source"] == "plate" and m["pid"] == "p1", (M["_qw_mats"](_i), m))
#  Тот же файл, но PETG лежит в слоте 1, а не 2. До 16.10.2026 подбор слотов запуска отдавал слот 1
#  неиспользуемому PLA проекта (его слот по файлу), PETG уехал бы в пустой слот, и очередь такой запуск
#  не предлагала. R-136: слоты раздаются только филаментам плиты (как у Bambu Studio), остальным -1.
_reset()
printer("p1", "AMS-PETG-В-1", ams=["PETG", "Empty", "Empty", "Empty"])
m = M["_qw_match"](_i)
check("41b. (R-136) PETG плиты лежит в слоте 1 — лишний PLA проекта его больше не занимает, запуск предлагается",
      m["pid"] == "p1" and verdict_of(m, "p1") == "ready", m)
_i41, _fd41 = info_of("proj4.gcode.3mf")
_map41 = M["_bambu_auto_slot_map"]("p1", _fd41, _i41["file_map"])
check("41c. (R-136) запуск: PETG плиты — в слот 1 (индекс 0), три филамента проекта вне плиты — «не назначен» (-1)",
      _map41 == [-1, 0, -1, -1], _map41)

mk3mf("all_plates.gcode.3mf", ["PLA", "PETG"], {1: [(1, "PLA")], 2: [(2, "PETG")]})
_i, _ = info_of("all_plates.gcode.3mf")
check("42. файл со всеми плитами: запуск печатает плиту 1 — требуется её PLA",
      M["_qw_mats"](_i) == ["PLA"], M["_qw_mats"](_i))

mk3mf("plates_2_10.gcode.3mf", ["PLA", "PETG"], {2: [(1, "PLA")], 10: [(2, "PETG")]})
_i, _ = info_of("plates_2_10.gcode.3mf")
check("43. плиты 2 и 10 без первой: запуск отправит plate_10 (первую по сортировке имён) — сверяется её PETG",
      M["_qw_mats"](_i) == ["PETG"] and _i["source"] == "plate", (M["_qw_mats"](_i), _i["why"]))

mk3mf("no_slice_info.gcode.3mf", ["PLA", "PETG"], {1: []}, slice_info=False)
_i, _ = info_of("no_slice_info.gcode.3mf")
check("44. нет описания плиты — берутся все материалы проекта с пометкой «по всему проекту»",
      M["_qw_mats"](_i) == ["PLA", "PETG"] and _i["source"] == "project", (M["_qw_mats"](_i), _i["source"]))

mk3mf("project_only.3mf", ["PETG"], {1: [(1, "PETG")]}, sliced=False)
_reset()
printer("p1", "P1S", ams=["PETG"])
_add = M["api_queue_wait_add"]({"gcode_file": "project_only.3mf"})
check("45. не нарезанный проект .3mf в очередь не ставится (печатать его нечем)",
      _add.get("ok") is False and _add.get("error") == "not_printable", _add)

mk3mf("support.gcode.3mf", ["PETG", "PLA"], {1: [(1, "PETG"), (2, "PLA-S")]})
_i, _ = info_of("support.gcode.3mf")
check("46. материал филамента берётся из того же списка, что у подбора слотов запуска (PLA, а не PLA-S из описания плиты)",
      M["_qw_mats"](_i) == ["PETG", "PLA"], M["_qw_mats"](_i))

print("--- 7. файл не уходит на принтер, под который не нарезан ---")
_reset()
printer("a_p1s", "P1S-01", model="P1S", noz=1, ams=["PLA"])
printer("b_h2d", "H2D-01", model="H2D", noz=2, ams=["PLA"])
m = match("pla_h2d.gcode.3mf")
check("47. файл под H2D при свободных P1S и H2D с PLA — выбран H2D, P1S назван неподходящим",
      m["pid"] == "b_h2d" and verdict_of(m, "a_p1s") == "incompatible", m)

_reset()
printer("k2", "K2-01", ptype="klipper", model="Creality K2 Plus", cfs=[("PLA", True)])
m = match("pla.gcode.3mf")
check("48. .gcode.3mf Bambu при свободном только K2 — «не подходит к файлу», не отправляется",
      m["pid"] == "" and m["reason"] == "incompatible", (m["pid"], m["reason"]))

mkgcode("k2_t0_petg.gcode", ["PETG", "PETG"], ["3.66", "0.00"], [0])
_reset()
printer("x1", "X1C-01", model="X1C", ams=["PETG"])
m = match("k2_t0_petg.gcode")
check("49. g-code под K2 при свободном только X1C — «не подходит к файлу»",
      m["pid"] == "" and m["reason"] == "incompatible", (m["pid"], m["reason"]))

_reset()
printer("demo", "Виртуальный", ptype="demo", model="", raw="idle")
m = match("pla_h2d.gcode.3mf")
check("50. виртуальный принтер подходит под любой файл и материал (печатает по часам)",
      m["pid"] == "demo" and (m["feed"] or {}).get("kind") == "demo", m)

_reset()
printer("p1", "P1S", ams=["PLA"])
m = match("pla_nomodel.gcode.3mf")
check("51. модель в файле не указана — принтеры по модели не отсекаются", m["pid"] == "p1", m)

print("--- 8. «свободен» — на самом деле, а не по картинке ---")
_reset()
printer("p1", "ОТМЕНА-ИДЁТ", status="IDLE", raw="RUNNING", ams=["PLA"])
m = match("pla.gcode.3mf")
check("52. после «Стоп» карточка рисует свободным, а принтер ещё отрабатывает отмену — не выбирается",
      m["pid"] == "" and verdict_of(m, "p1") == "printing", m)

_reset()
printer("p1", "ПАРКУЕТСЯ", status="IDLE", raw="IDLE", stage=13, ams=["PLA"])
m = match("pla.gcode.3mf")
check("53. статус ещё IDLE, но принтер уже паркует голову (stg_cur 13) — не выбирается, стадия названа",
      m["pid"] == "" and verdict_of(m, "p1") == "working_stage"
      and next(c for c in m["candidates"] if c["id"] == "p1")["stage"] == 13, m)

_reset()
printer("p1", "СТАДИЯ-0", status="IDLE", raw="IDLE", stage=0, ams=["PLA"])
m = match("pla.gcode.3mf")
_BUSY = SRC[SRC.index("def _qw_busy_verdict"):SRC.index("def _qw_printer_feed")]
_NOW = SRC[SRC.index("def _bambu_busy_now"):SRC.index("def _bambu_wait_started")]
#  16.10.2026 (R-138): сверяется ИСПОЛНЕНИЕМ — на одних и тех же отчётах очередь называет принтер занятым
#  стадией ровно тогда, когда запуск (_bambu_busy_now) не стал бы слать команду.
_agree = []
for _kw in ({"stage": 0}, {"stage": 13}, {"stage": 0, "print_type": "idle"}, {"stage": 54, "print_type": "idle", "raw": "FAILED"},
            {"stage": 13, "print_type": "local"}, {"stage": 255}, {"stage": 29, "print_type": "local", "raw": "FINISH"}):
    _reset()
    printer("pz", "СВЕРКА", status="IDLE", ams=["PLA"], **_kw)
    _q = M["_qw_busy_verdict"]("pz", "bambu", M["_qw_ctx"]()) == "working_stage"
    _agree.append((_kw, _q, bool(M["_bambu_busy_now"]("pz"))))
check("53b. занятость по стадии у очереди та же, что у запуска Bambu: принтер, которому запуск не пошлёт "
      "команду (стадия 0), очередь не предлагает — иначе строка ушла бы, а печать не началась",
      m["pid"] == "" and verdict_of(m, "p1") == "working_stage" and all(q == b for _k, q, b in _agree), (m, _agree))

#  09.10.2026 (R-138, ферма оператора P1P/P1S): после включения прошивка Bambu шлёт stg_cur = 0 у
#  принтера в покое; pybambu (ha-bambulab) поправляет это при print_type == "idle". Запуск теперь
#  такому принтеру команду шлёт — значит, и очередь обязана его предлагать (правило одно).
_reset()
printer("p1", "ПОСЛЕ-ВКЛЮЧЕНИЯ", status="IDLE", raw="IDLE", stage=0, print_type="idle", ams=["PLA"])
m = match("pla.gcode.3mf")
check("53c. стадия 0 при print_type=idle — принтер в покое: очередь его предлагает, как и запуск",
      m["pid"] == "p1" and verdict_of(m, "p1") != "working_stage", m)

_reset()
printer("p1", "ОТМЕНА-ЗАКОНЧЕНА", status="IDLE", raw="FAILED", stage=255, ams=["PLA"])
m = match("pla.gcode.3mf")
check("54. отмена закончилась (липкий FAILED, стадия покоя) — принтер снова свободен, с пометкой «проверьте стол»",
      m["pid"] == "p1" and m["finished"] is True, m)

_reset()
printer("p1", "ОТМЕНИЛИ", status="IDLE", raw="FAILED", stage=255, ams=["PLA"])
printer("p2", "ЧИСТЫЙ", status="IDLE", raw="IDLE", ams=["PLA"])
m = match("pla.gcode.3mf")
check("54b. после отмены на столе может остаться деталь: выбран принтер в чистом покое, а не отменивший",
      m["pid"] == "p2" and m["finished"] is False, m)

_reset()
printer("p1", "ЗАКОНЧИЛ", status="FINISH", ams=["PLA"])
printer("p2", "СВОБОДЕН", status="IDLE", ams=["PLA"])
m = match("pla.gcode.3mf")
check("55. из закончившего печать и свободного выбран свободный (на столе первого может лежать деталь)",
      m["pid"] == "p2" and m["finished"] is False, m)

print("--- 9. Creality K2: материал в той ячейке CFS, что указана в файле ---")
_i, _ = info_of("k2_t0_petg.gcode")
check("56. g-code Creality Print: материал и ячейка — по строкам расхода и filament_type (T1A, PETG)",
      [(n["idx"], n["material"]) for n in _i["need"]] == [(0, "PETG")] and _i["source"] == "gcode", _i["need"])

mkgcode("k2_t1_petg.gcode", ["PETG", "PETG"], ["0.00", "3.66"], [1])
_reset()
printer("k2", "K2-01", ptype="klipper", model="Creality K2 Plus", cfs=[("PLA", True), ("PETG", True)])
m0 = match("k2_t0_petg.gcode")
m1 = match("k2_t1_petg.gcode")
check("57. PETG лежит в T1B: файл на T1A не запускается («в ячейке другой материал»), файл на T1B — запускается",
      m0["pid"] == "" and verdict_of(m0, "k2") == "slot_mismatch"
      and m1["pid"] == "k2" and (m1["feed"] or {}).get("kind") == "cfs", (m0, m1))

_reset()
printer("k2", "K2-01", ptype="klipper", model="Creality K2 Plus", cfs=[("PETG", False)])
m = match("k2_t0_petg.gcode")
check("58. принтер назвал материал кодом, а не именем — «программа не видит материал»",
      m["pid"] == "" and m["reason"] == "printer_material_unknown", m)

mkgcode("orca_two.gcode", ["PLA", "PETG"], None, [0, 1])
_i, _ = info_of("orca_two.gcode")
check("59. два материала без строк расхода — что печатает файл, не угадывается",
      _i["need"] == [] and M["_qw_match"](_i)["reason"] == "material_unknown", _i)

mkgcode("conflict.gcode", ["PETG", "PETG"], ["3.66", "0.00"], [1])
_i, _ = info_of("conflict.gcode")
check("60. расход говорит «T1A», а строка выбора — «T1B»: противоречие, материал не угадывается",
      _i["need"] == [] and _i["why"] == "tool_conflict", _i)

mkgcode("no_tline.gcode", ["PETG"], ["3.66"], [])
_i, _ = info_of("no_tline.gcode")
check("60b. в g-code нет строки T<n>: принтер возьмёт заправленную ячейку — материал «по номеру ячейки» не засчитывается",
      _i["need"] == [] and _i["why"] == "no_tool_line", _i)

print("--- 10. живые материалы и запуск на подтверждённый принтер ---")
_reset()
printer("p1", "P1S-PLA", ams=["PLA"])
_live = mk3mf("live.gcode.3mf", ["PLA"], {1: [(1, "PLA")]})
_add = M["api_queue_wait_add"]({"gcode_file": "live.gcode.3mf"})
mk3mf("live.gcode.3mf", ["PETG"], {1: [(1, "PETG")]})
_t = time.time() + 30
os.utime(_live, (_t, _t))
_g = M["api_queue_wait_get"]()
_row = (_g.get("items") or [{}])[0]
check("61. файл перенарезали под PETG — очередь показывает PETG без повторного добавления",
      _row.get("material") == "PETG" and _row.get("match_reason") == "no_material", _row)
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p1"})
_state = conn.execute("SELECT state FROM queue_wait WHERE id=?", (_add.get("id"),)).fetchone()["state"]
check("62. запуск перечитывает файл: на принтер с PLA не уходит, строка возвращается в ожидание",
      _st.get("ok") is False and _st.get("error") == "no_material" and not ENQ and _state == "waiting", (_st, _state))

_reset()
printer("p1", "P1S-PLA", ams=["PLA"])
FILES.pop("later.gcode.3mf", None)
_add = M["api_queue_wait_add"]({"gcode_file": "later.gcode.3mf"})
_r1 = (M["api_queue_wait_get"]().get("items") or [{}])[0]
mk3mf("later.gcode.3mf", ["PLA"], {1: [(1, "PLA")]})
_r2 = (M["api_queue_wait_get"]().get("items") or [{}])[0]
check("63. файла не было при добавлении — «файл не найден»; появился — подбор находит принтер",
      _add.get("ok") is True and _r1.get("match_reason") == "file_missing"
      and _r2.get("match_printer_id") == "p1", (_add, _r1.get("match_reason"), _r2.get("match_reason")))

_locked = mk3mf("locked.gcode.3mf", ["PLA"], {1: [(1, "PLA")]})
_real_open = open


def _open_locked(path, *a, **k):
    if os.path.normcase(str(path)) == os.path.normcase(_locked):
        raise PermissionError("locked by another program")
    return _real_open(path, *a, **k)


NS["open"] = _open_locked
_i, _ = info_of("locked.gcode.3mf")
NS.pop("open", None)
check("63b. файл есть, но не читается (занят другой программой) — так и сказано, а не «файл не найден»",
      M["_qw_match"](_i)["reason"] == "file_unreadable", (_i["state"], M["_qw_match"](_i)["reason"]))

_reset()
printer("p1", "ПОДТВЕРЖДЁН", ams=["PLA"])
printer("p2", "ДРУГОЙ", ams=["PLA"])
_add = M["api_queue_wait_add"]({"gcode_file": "pla.gcode.3mf"})
NS["p_states"]["p1"]["status"] = "RUNNING"
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p1"})
_state = conn.execute("SELECT state FROM queue_wait WHERE id=?", (_add.get("id"),)).fetchone()["state"]
check("64. подтверждённый принтер занялся — на другой без подтверждения не отправляется",
      _st.get("ok") is False and _st.get("error") == "printer_changed" and not ENQ and _state == "waiting", (_st, ENQ))
NS["p_states"]["p1"]["status"] = "IDLE"
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p2"})
check("64b. пока подтверждённый принтер подходит, выбирается он, даже если другой стоит раньше по списку",
      _st.get("ok") is True and ENQ and ENQ[0]["printer_id"] == "p2", (_st, ENQ))

_reset()
for k in range(8):
    printer("m%d" % k, "P1S-%02d" % k, ams=["PETG"])
M["api_queue_wait_add"]({"gcode_file": "pla.gcode.3mf"})
_g = M["api_queue_wait_get"]()
_row = (_g.get("items") or [{}])[0]
_keys = set()
for c in _row.get("candidates") or []:
    _keys |= set(c.keys())
_dump = json.dumps(_g, ensure_ascii=False)
check("65. в ответе очереди нет адресов и кодов доступа принтеров — только имена и материалы",
      _keys <= {"id", "name", "verdict", "finished", "status", "stage", "have", "dual", "ext_side", "ptype"}
      and "10.0.0.99" not in _dump and "FIXTURE_TOKEN" not in _dump, (_keys,))
check("66. принтеров под строкой — не больше шести, остальные сосчитаны",
      len(_row.get("candidates") or []) == 6 and _row.get("candidates_more") == 2,
      (len(_row.get("candidates") or []), _row.get("candidates_more")))
_GET = SRC[SRC.index("def api_queue_wait_get"):SRC.index("def api_queue_wait_add")]
check("67. опрос очереди только читает: ни UPDATE, ни INSERT, ни команд принтерам",
      "UPDATE" not in _GET and "INSERT" not in _GET and "publish" not in _GET)

print("--- 11. зеркало раскладки по AMS совпадает с настоящим подбором запуска ---")
_mir = M["_qw_auto_slot_mirror"]
_real = M["_bambu_auto_slot_map"]
_cases = [
    ("petg_pla.gcode.3mf", ["PETG", "PLA"], ["PLA", "PETG"]),
    ("petg2.gcode.3mf", ["PETG", "PETG"], ["PETG"]),
    ("pla1.gcode.3mf", ["PLA"], [{"type": "PLA", "remain": 5, "color_raw": "FFFFFFFF"},
                                 {"type": "PLA", "remain": 90, "color_raw": "FFFFFFFF"}]),
    ("pla_empty.gcode.3mf", ["PLA"], ["Empty", "Empty"]),
    ("petg_pla_dup.gcode.3mf", ["PETG", "PLA"], ["ABS", "PETG"]),
]
_same = []
for fname, types, trays in _cases:
    mk3mf(fname, types, {1: [(i + 1, t) for i, t in enumerate(types)]})
    _reset()
    printer("p1", "P", ams=trays)
    _i, _fd = info_of(fname)
    _a = _real("p1", _fd, _i["file_map"]) or list(_i["file_map"])
    _b = _mir(NS["p_states"]["p1"]["ams_trays"], _i["fils"], _i["file_map"], 15)
    _same.append((fname, _a, _b))
check("68. на пяти раскладках (обмен слотов, повтор материала, почти пустая катушка, пустой AMS, спорный подбор) "
      "зеркало даёт ту же карту, что подбор запуска",
      all(a == b for _f, a, b in _same), _same)
_same2 = []
for fname, types, plate, trays in [
        ("p4a.gcode.3mf", ["PLA", "PETG", "PLA", "ABS"], [(2, "PETG")], ["PETG", "Empty", "Empty", "Empty"]),
        ("p4b.gcode.3mf", ["PLA", "PLA", "PETG"], [(2, "PLA"), (3, "PETG")], ["PLA", "PETG", "PLA", "Empty"]),
        ("p4c.gcode.3mf", ["PETG", "PLA"], [(2, "PLA")], ["ABS", "Empty"])]:
    mk3mf(fname, types, {1: plate})
    _reset()
    printer("p1", "P", ams=trays)
    _i, _fd = info_of(fname)
    _a = _real("p1", _fd, _i["file_map"]) or list(_i["file_map"])
    _b = _mir(NS["p_states"]["p1"]["ams_trays"], _i["fils"], _i["file_map"], 15, None,
              [n["idx"] for n in _i["need"]] if _i.get("source") == "plate" else None)
    _same2.append((fname, _a, _b))
check("68b. (R-136) плита печатает часть материалов проекта — зеркало очереди и подбор запуска снова совпадают",
      all(a == b for _f, a, b in _same2) and _same2[0][1] == [-1, 0, -1, -1], _same2)

#  16.10.2026 (R-006, R-139): новые правила раскладки — одна функция и для запуска, и для зеркала.
#  Каждый случай: (файл, типы, цвета, project_settings, metadata плиты, сопел, слоты AMS, ожидаемая карта).
_W, _G, _R, _DR = "FFFFFFFF", "808080FF", "FF0000FF", "8B0000FF"
_same3 = []
for fname, types, cols, extra, meta, noz, trays, want in [
        ("r6_dist.gcode.3mf", ["PLA"], ["#FF0000"], None, None, 1,
         [{"index": 0, "type": "PLA", "color_raw": _W}, {"index": 1, "type": "PLA", "color_raw": _DR}], [1]),
        ("r6_pair.gcode.3mf", ["PLA", "PLA"], ["#000000", "#FFFFFF"], None, None, 1,
         [{"index": 0, "type": "PLA", "color_raw": _W}, {"index": 1, "type": "PLA", "color_raw": _G}], [1, 0]),
        ("r6_present.gcode.3mf", ["PLA"], None, None, None, 1,
         [{"index": 0, "type": "PLA", "color_raw": _W, "present": False},
          {"index": 1, "type": "PLA", "color_raw": _W, "present": True}], [1]),
        ("r6_support.gcode.3mf", ["PLA"], None, {"filament_is_support": ["1"]}, None, 1,
         [{"index": 0, "type": "PLA", "color_raw": _W}, {"index": 1, "type": "Sup.PLA", "color_raw": _W}], [1]),
        ("r6_fid.gcode.3mf", ["PLA"], None, {"filament_ids": ["GFA00"]}, None, 1,
         [{"index": 0, "type": "PLA", "color_raw": _W, "tray_info_idx": "GFA01"},
          {"index": 1, "type": "PLA", "color_raw": _W, "tray_info_idx": "GFA00"}], [1]),
        ("r6_h2d.gcode.3mf", ["PLA"], None, None, {"filament_maps": "2"}, 2,
         [{"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color_raw": _W, "extruder": 1},
          {"index": 512, "unit": 128, "tray": 0, "type": "PLA", "color_raw": _W, "extruder": 0}], [512]),
        ("r6_h2d_left.gcode.3mf", ["PLA"], None, None, {"filament_maps": "1"}, 2,
         [{"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color_raw": _W, "extruder": 1},
          {"index": 512, "unit": 128, "tray": 0, "type": "PLA", "color_raw": _W, "extruder": 0}], [0])]:
    mk3mf(fname, types, {1: [(i + 1, t) for i, t in enumerate(types)]}, colours=cols, extra_ps=extra,
          plate_meta=meta, nozzles=noz, model=("Bambu Lab H2D" if noz == 2 else "Bambu Lab P1S"))
    _reset()
    printer("p1", "P", ams=[])
    NS["p_states"]["p1"]["ams_trays"] = [dict(t) for t in trays]
    _i, _fd = info_of(fname)
    _a = _real("p1", _fd, _i["file_map"]) or list(_i["file_map"])
    _rc = {}
    _b = _mir(NS["p_states"]["p1"]["ams_trays"], _i["fils"], _i["file_map"], 15, _rc,
              [n["idx"] for n in _i["need"]] if _i.get("source") == "plate" else None)
    _b2 = _mir(NS["p_states"]["p1"]["ams_trays"], _i["fils"], _i["file_map"], 15, _rc,
               [n["idx"] for n in _i["need"]] if _i.get("source") == "plate" else None)
    _same3.append((fname, _a, _b, _b2, want))
check("68c. (R-006) расстояние цвета, самая близкая пара, датчик подачи, опорный PLA, filament_id, сопло H2D: "
      "зеркало очереди (и с кешем цветов) == подбор запуска == ожидаемая карта",
      all(a == b == b2 == w for _f, a, b, b2, w in _same3), _same3)

#  R-139: PLA в слоте только по типу от прошлой катушки, а датчик подачи лотка не видит —
#  очередь такой принтер готовым не называет (прежде называла: слот файла «с PLA»).
_reset()
printer("p1", "P1S-пустой", ams=[{"type": "PLA", "color_raw": _W, "present": False}])
m = match("pla.gcode.3mf")
check("68d. (R-139) слот с типом PLA, но без лотка по датчику — принтер не готов, причина «пусто»",
      m["pid"] == "" and verdict_of(m, "p1") == "printer_empty", m)
_reset()
printer("p1", "P1S-есть", ams=[{"type": "PLA", "color_raw": _W, "present": True}])
m = match("pla.gcode.3mf")
check("68e. тот же слот с лотком по датчику — принтер готов", m["pid"] == "p1" and verdict_of(m, "p1") == "ready", m)

#  R-016: филамент плиты с used_g=0 Bambu Studio описал, но плита его не расходует.
mk3mf("r16_used0.gcode.3mf", ["PLA", "PETG"], {1: [(1, "PLA"), (2, "PETG")]}, used_g={2: "0.00"})
_i, _ = info_of("r16_used0.gcode.3mf")
_reset()
printer("p1", "Только-PLA", ams=["PLA"])
m = M["_qw_match"](_i)
check("68f. (R-016) PETG плиты с used_g=0 не требуется: нужен только PLA, принтер с PLA найден",
      M["_qw_mats"](_i) == ["PLA"] and m["pid"] == "p1", (M["_qw_mats"](_i), m))
_pu = M["_3mf_plate_used"](io.open(FILES["r16_used0.gcode.3mf"], "rb").read())
check("68g. граммы плиты по номеру филамента отдаются (used_g), без нулевого",
      _pu.get("used_g") == {0: 3.0} and _pu.get("idx") == [0], _pu)

#  16.10.2026 (R-006): к какому соплу плита привязала филамент — по файлу Bambu Studio
#  (bbs_3mf.cpp: <plate> metadata filament_maps через пробел; model_settings — plater_id;
#  project_settings — filament_map). 1 — левое сопло, 2 — правое.
_sides = M["_3mf_filament_sides"]


def _rd(name):
    return io.open(FILES[name], "rb").read()


mk3mf("sd_si.gcode.3mf", ["PLA", "PETG"], {1: [(1, "PLA"), (2, "PETG")]}, nozzles=2,
      plate_meta={"filament_maps": "1 2"}, extra_ps={"filament_map": ["2", "2"]}, model="Bambu Lab H2D")
_s = _sides(_rd("sd_si.gcode.3mf"))
check("68h. сопла из slice_info плиты (главнее project_settings): [1, 2], два сопла",
      _s.get("ok") and _s.get("maps") == [1, 2] and _s.get("extruders") == 2 and _s.get("source") == "slice_info", _s)
mk3mf("sd_ps.gcode.3mf", ["PLA", "PETG"], {1: [(1, "PLA"), (2, "PETG")]}, nozzles=2,
      extra_ps={"filament_map": ["2", "1"]}, model="Bambu Lab H2D")
_s = _sides(_rd("sd_ps.gcode.3mf"))
check("68i. в плите нет — берётся project_settings filament_map", _s.get("maps") == [2, 1]
      and _s.get("source") == "project_settings", _s)
_buf = io.BytesIO()
with zipfile.ZipFile(_buf, "w") as _z:
    _z.writestr("Metadata/project_settings.config", json.dumps({"filament_type": ["PLA"], "nozzle_diameter": ["0.4", "0.4"],
                                                               "filament_map": ["1"]}))
    _z.writestr("Metadata/model_settings.config",
                '<config><plate><metadata key="plater_id" value="1"/><metadata key="filament_maps" value="2"/>'
                '</plate></config>')
    _z.writestr("Metadata/plate_1.gcode", "; HEADER\n")
_s = _sides(_buf.getvalue())
check("68j. model_settings той же плиты (plater_id) главнее project_settings", _s.get("maps") == [2]
      and _s.get("source") == "model_settings", _s)
mk3mf("sd_p10.gcode.3mf", ["PLA"], {2: [(1, "PLA")], 10: [(1, "PLA")]}, nozzles=2, model="Bambu Lab H2D")
_buf = io.BytesIO()
with zipfile.ZipFile(FILES["sd_p10.gcode.3mf"]) as _zr, zipfile.ZipFile(_buf, "w") as _zw:
    for _n in _zr.namelist():
        _d = _zr.read(_n)
        if _n == "Metadata/slice_info.config":
            _d = _d.decode("utf-8").replace('<metadata key="index" value="2"/>',
                                            '<metadata key="index" value="2"/><metadata key="filament_maps" value="1"/>')
            _d = _d.replace('<metadata key="index" value="10"/>',
                            '<metadata key="index" value="10"/><metadata key="filament_maps" value="2"/>').encode("utf-8")
        _zw.writestr(_n, _d)
_s = _sides(_buf.getvalue())
check("68k. плиты 2 и 10: сопла берутся у plate_10 — той, что уйдёт в печать (первая по sorted)",
      _s.get("maps") == [2], _s)
mk3mf("sd_bad.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, nozzles=2, plate_meta={"filament_maps": "0"},
      model="Bambu Lab H2D")
_s = _sides(_rd("sd_bad.gcode.3mf"))
check("68l. значения не 1/2 — сопло неизвестно, подбор по соплу не ограничивает", _s.get("ok") is False, _s)
mk3mf("sd_one.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, nozzles=1, plate_meta={"filament_maps": "1"})
_s = _sides(_rd("sd_one.gcode.3mf"))
_ws = _bslot.with_sides([{"material": "PLA"}], _s)
check("68m. файл на одно сопло: filament_maps прочитан, но сопло филаменту не назначается",
      _s.get("extruders") == 1 and _ws[0]["side"] is None, (_s, _ws))
#  Требования файла: опорный ли филамент и его filament_id (R-006, R-115) — новые поля, прежние не тронуты.
mk3mf("req_sup.gcode.3mf", ["PLA", "PLA"], {1: [(1, "PLA"), (2, "PLA")]},
      extra_ps={"filament_is_support": ["0", "1"], "filament_ids": ["GFA00", "GFS00"]})
_rq = M["_3mf_filament_requirements"](_rd("req_sup.gcode.3mf"))["filaments"]
check("68n. требования: is_support и filament_id из project_settings, прежние поля на месте",
      [(f["material"], f["is_support"], f["filament_id"]) for f in _rq] == [("PLA", False, "GFA00"), ("PLA", True, "GFS00")]
      and all(set(f) >= {"file_index", "material", "color_hex"} for f in _rq), _rq)
_buf = io.BytesIO()
with zipfile.ZipFile(_buf, "w") as _z:
    _z.writestr("Metadata/slice_info.config", '<config><plate><metadata key="index" value="1"/>'
                '<filament id="1" tray_info_idx="GFA01" type="PLA" color="#FFFFFF" used_g="2.0"/></plate></config>')
    _z.writestr("Metadata/plate_1.gcode", "; HEADER\n")
_rq = M["_3mf_filament_requirements"](_buf.getvalue())["filaments"]
check("68o. filament_id из slice_info (tray_info_idx), опорным не считается без признака",
      _rq and _rq[0]["filament_id"] == "GFA01" and _rq[0]["is_support"] is False, _rq)

print("--- 11b. H2D: внешняя катушка по соплу в файле, двухсопельный без сопел (16.10.2026, R-137/R-115) ---")
mk3mf("pla_h2d_left.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, model="Bambu Lab H2D", nozzles=2,
      plate_meta={"filament_maps": "1"})
mk3mf("pla_h2d_right.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, model="Bambu Lab H2D", nozzles=2,
      plate_meta={"filament_maps": "2"})
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ext_left="PLA", ext="PETG")
m = match("pla_h2d_left.gcode.3mf")
_il, _fl = info_of("pla_h2d_left.gcode.3mf")
_chl = M["_bambu_ext_choice"]("h2d", _fl, explicit=True)
check("82. файл под левое сопло, PLA на левой катушке — принтер найден, печать с ЛЕВОЙ (254); запуск выберет ту же",
      m["pid"] == "h2d" and {k: (m["feed"] or {}).get(k) for k in ("kind", "ext")} == {"kind": "external", "ext": 254}
      and _chl.get("ext") == 254, (m, _chl))
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ext="PLA")
m = match("pla_h2d_left.gcode.3mf")
check("83. файл под левое сопло, PLA только на правой — НЕ запускается («другое сопло»); раньше уходило 255 — это и был дефект",
      m["pid"] == "" and verdict_of(m, "h2d") == "ext_wrong_side"
      and next(c for c in m["candidates"] if c["id"] == "h2d").get("ext_side") == "right", m)
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ext_left="PLA")
m = match("pla_h2d_right.gcode.3mf")
check("84. файл под правое сопло, PLA только на левой — не запускается, сторона названа",
      m["pid"] == "" and verdict_of(m, "h2d") == "ext_wrong_side"
      and next(c for c in m["candidates"] if c["id"] == "h2d").get("ext_side") == "left", m)
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ext="PLA", ext_left="PETG")
m = match("pla_h2d_right.gcode.3mf")
check("85. файл под правое сопло, PLA на правой — печать с правой (255)",
      m["pid"] == "h2d" and {k: (m["feed"] or {}).get(k) for k in ("kind", "ext")} == {"kind": "external", "ext": 255}, m)
_reset()
printer("p1", "P1S-БЕЗ-КАТУШКИ", ext_left="PLA", noz=1)
m = match("pla.gcode.3mf")
check("86. односопельный принтер: «254» в отчёте второй катушкой не считается — не показывается и не подбирается",
      m["pid"] == "" and not any(h["where"] == "ext_left" for c in m["candidates"] for h in c["have"]), m)

_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ext_left="PLA", ext="PETG")
_add = M["api_queue_wait_add"]({"gcode_file": "pla_h2d_left.gcode.3mf"})
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "h2d"})
_sn = conn.execute("SELECT note FROM queue_wait WHERE id=?", (_add.get("id"),)).fetchone()["note"]
check("87. запуск из очереди с левой катушки: ams_slot=-1 (сторону запуск перечитает из файла), в строке — «левая внешняя»",
      _st.get("ok") is True and ENQ and ENQ[0].get("ams_slot") == -1 and "левая внешняя" in (_sn or ""), (_st, ENQ, _sn))

#  R-115: двухсопельный, материал в AMS, а в файле не видно, каким соплом печатает плита.
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ams=["PLA"])
m = match("pla_h2d.gcode.3mf")
_row = M["_qw_public"]({"id": "x", "gcode_file": "pla_h2d.gcode.3mf"}, info_of("pla_h2d.gcode.3mf")[0], m)
check("88. (R-115) H2D, PLA в AMS, сопла в файле нет — «только ручной запуск»: подбор есть, но помечен непроверенным",
      verdict_of(m, "h2d") == "dual_nozzle_unverified" and m["pid"] == "h2d" and m.get("unverified") is True
      and _row.get("match_unverified") is True, (m, _row.get("match_unverified")))
_add = M["api_queue_wait_add"]({"gcode_file": "pla_h2d.gcode.3mf"})
_r = conn.execute("SELECT * FROM queue_wait WHERE id=?", (_add.get("id"),)).fetchone()
conn.execute("UPDATE queue_wait SET state='starting' WHERE id=?", (_add.get("id"),))
conn.commit()
_ra = M["_qw_launch_claimed"](_add.get("id"), _r, "h2d", auto=True)
_sa = conn.execute("SELECT state FROM queue_wait WHERE id=?", (_add.get("id"),)).fetchone()["state"]
check("89. автомат такую строку НЕ запускает и возвращает в ожидание",
      _ra.get("ok") is False and _ra.get("error") == "dual_nozzle_unverified" and _sa == "waiting" and not ENQ, (_ra, _sa))
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "h2d"})
_sn = conn.execute("SELECT note FROM queue_wait WHERE id=?", (_add.get("id"),)).fetchone()["note"]
check("90. человек запускает её сам (кнопкой, после предупреждения) — уходит, пометка «сопло не проверено»",
      _st.get("ok") is True and len(ENQ) == 1 and "сопло не проверено" in (_sn or ""), (_st, _sn))
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ams=["PLA"])
m = match("pla_h2d_left.gcode.3mf")
check("91. тот же H2D и файл, где сопло указано, — обычный «подходит», без пометки",
      verdict_of(m, "h2d") == "ready" and m["pid"] == "h2d" and not m.get("unverified"), m)

print("--- 11c. занятость после отмены и смена филамента (16.10.2026, R-138) ---")
_reset()
printer("p1", "P1S-ОТМЕНИЛИ", status="IDLE", raw="FAILED", stage=54, print_type="idle", ams=["PLA"])
m = match("pla.gcode.3mf")
check("92. ha-bambulab #2161: после отмены FAILED + стадия 54 + print_type idle — очередь предлагает принтер "
      "(с пометкой «проверьте стол»), а не «выполняет подготовку»",
      m["pid"] == "p1" and verdict_of(m, "p1") == "ready" and m["finished"] is True, m)
_reset()
printer("p1", "P1S-ГОТОВО", status="FINISH", raw="FINISH", stage=29, print_type="local", ams=["PLA"])
m = match("pla.gcode.3mf")
#  16.10.2026 (после проверки пакета): FINISH со стадией — как до 16.10 (ha-bambulab PR #2168 FINISH не
#  трогает: стадия после печати бывает настоящей); правило одно с запуском (проверка 53b).
check("93. FINISH + стадия 29 (охлаждение после печати) — занят, как и у запуска; причина названа по-русски",
      m["pid"] == "" and verdict_of(m, "p1") == "working_stage"
      and next(c for c in m["candidates"] if c["id"] == "p1").get("busy_ru") == "выполняет подготовку: стадия 29 "
                                                                                "(охлаждение камеры)", m)
_reset()
printer("p1", "P1S-СМЕНА", status="IDLE", raw="IDLE", ams=["PLA"])
NS["p_states"]["p1"]["ams_status"] = 0x0100
m = match("pla.gcode.3mf")
check("94. AMS меняет филамент (ams_status 0x0100) — занят, как в Bambu Studio",
      m["pid"] == "" and verdict_of(m, "p1") == "working_stage", m)
NS["p_states"]["p1"]["ams_status"] = 768
m = match("pla.gcode.3mf")
check("95. ams_status 768 (принтер в покое) — свободен", m["pid"] == "p1", m)
NS["p_states"]["p1"]["ams_status"] = 0x0100
m = match("pla.gcode.3mf")
_c96 = next(c for c in m["candidates"] if c["id"] == "p1")
check("96. (проверка пакета) строка очереди называет настоящую причину: «меняет филамент в AMS», а не «выполняет "
      "подготовку (стадия …)»",
      _c96.get("verdict") == "working_stage" and _c96.get("busy_ru") == "меняет филамент в AMS"
      and _c96.get("busy_en") == "is changing filament in the AMS", _c96)

print("--- 11d. калибровка или загрузка филамента с экрана; сопло слота у H2D (16.10.2026, проверка пакета) ---")
#  Сырой IDLE, print_type «idle», стадия 24 — оператор грузит филамент с экрана. ha-bambulab PR #2168
#  такие стадии намеренно не трогает. Прежняя редакция 16.10 считала принтер свободным: очередь предлагала
#  его, а автозапуск слал команду, на которую принтер отвечает 0500-4004.
for _sg, _nm in ((24, "загрузка филамента"), (8, "калибровка экструзии"), (13, "парковка головы")):
    _reset()
    printer("p1", "P1S-ЭКРАН", status="IDLE", raw="IDLE", stage=_sg, print_type="idle", ams=["PLA"])
    m = match("pla.gcode.3mf")
    _c97 = next(c for c in m["candidates"] if c["id"] == "p1")
    check("97. сырой IDLE + стадия %d + print_type idle — занят, очередь его не предлагает; причина «%s»" % (_sg, _nm),
          m["pid"] == "" and _c97.get("verdict") == "working_stage"
          and _c97.get("busy_ru") == "выполняет подготовку: стадия %d (%s)" % (_sg, _nm), (m["pid"], _c97))

#  H2D: AMS 0 на ЛЕВОМ сопле (PETG, PLA), AMS HT 128 на ПРАВОМ (ABS). Файл: ABS и PLA, оба под ПРАВОЕ сопло.
#  Подбор: ABS -> HT (правое), а PLA на правом нет — подбор оставляет слот файла 1, это AMS ЛЕВОГО сопла.
#  Материал «совпал», и прежде строка была «подходит» — автозапуск отправлял перекрёстную карту.
_W = "FFFFFFFF"
mk3mf("xn_h2d.gcode.3mf", ["ABS", "PLA"], {1: [(1, "ABS"), (2, "PLA")]}, nozzles=2,
      plate_meta={"filament_maps": "2 2"}, model="Bambu Lab H2D")
_XN = [{"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color_raw": _W, "extruder": 1, "present": True},
       {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color_raw": _W, "extruder": 1, "present": True},
       {"index": 512, "unit": 128, "tray": 0, "type": "ABS", "color_raw": _W, "extruder": 0, "present": True}]
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ams=[])
NS["p_states"]["h2d"]["ams_trays"] = [dict(t) for t in _XN]
_ix, _fx = info_of("xn_h2d.gcode.3mf")
_mx = M["_bambu_auto_slot_map"]("h2d", _fx, _ix["file_map"])
m = match("xn_h2d.gcode.3mf")
check("98. H2D: филамент правого сопла получил бы слот AMS левого сопла (карта %s) — строка НЕ «подходит», а «материал "
      "есть в AMS, но не в тех слотах»; автозапуск её не возьмёт; перепроверка запуска с байтами файла — тоже нет" % _mx,
      _mx == [512, 1] and m["pid"] == "" and verdict_of(m, "h2d") == "ams_unmapped"
      and M["_qw_bambu_ams_proof"]("h2d", _ix, _fx, 15) is False, (_mx, m))
_reset()
printer("h2d", "H2D-01", model="H2D", noz=2, ams=[])
NS["p_states"]["h2d"]["ams_trays"] = [dict(t) for t in _XN] + [
    {"index": 4, "unit": 1, "tray": 0, "type": "PLA", "color_raw": _W, "extruder": 0, "present": True}]
m = match("xn_h2d.gcode.3mf")
check("99. НЕ ВАКУУМ: PLA есть и в AMS правого сопла — подбор берёт его, строка «подходит»",
      M["_bambu_auto_slot_map"]("h2d", _fx, _ix["file_map"]) == [512, 4] and m["pid"] == "h2d"
      and verdict_of(m, "h2d") == "ready", m)

print("--- 12. строка живёт до ответа очереди запусков (16.09.2026) ---")


def _state_note(rid):
    r = conn.execute("SELECT state, note FROM queue_wait WHERE id=?", (rid,)).fetchone()
    return (r["state"], r["note"]) if r else (None, None)


_reset()
printer("p1", "P1S-01", ams=["PLA"])
_add = M["api_queue_wait_add"]({"gcode_file": "pla.gcode.3mf"})
_rid = _add.get("id")
_st = M["api_queue_wait_start"]({"id": _rid, "printer_id": "p1"})
_s, _n = _state_note(_rid)
check("69. после постановки в очередь запусков строка НЕ закрыта, а «запускается», и несёт свой номер",
      _st.get("ok") is True and _s == "launching" and "запускается" in (_n or "")
      and ENQ and ENQ[0].get("qw_id") == _rid, (_st, _s, _n, ENQ))

_Q = {"qw_id": _rid, "printer_name": "P1S-01"}
M["_qw_launch_outcome"](_Q, True, "", "ok")
check("70. отправка принята — строка закрывается", _state_note(_rid)[0] == "done", _state_note(_rid))


def _relaunch():
    conn.execute("UPDATE queue_wait SET state='launching' WHERE id=?", (_rid,))
    conn.commit()


_cases = [("printer_held", "error", "waiting", "принтер удержан другим запуском"),
          ("не хватает филамента", "low_filament", "waiting", "склад заблокировал запуск"),
          ("файл нарезан под другую модель", "incompatible", "waiting", "файл не подошёл принтеру"),
          ("FTP оборвался на середине", "error", "attention", "исход неясен")]
for _i, (_err, _status, _want, _label) in enumerate(_cases):
    _relaunch()
    M["_qw_launch_outcome"](_Q, False, _err, _status)
    _s, _n = _state_note(_rid)
    check("71%s. исход «%s» -> строка %s, причина в строке" % ("abcd"[_i], _label, _want),
          _s == _want and (_err in (_n or "")), (_s, _n))

_relaunch()
M["_qw_recover_launching"]()
_s, _n = _state_note(_rid)
check("72. перезапуск программы: незавершённая строка помечена «требует внимания», а не возвращена молча",
      _s == "attention" and "перезапуск" in (_n or ""), (_s, _n))

ENQ[:] = []
_st2 = M["api_queue_wait_start"]({"id": _rid, "printer_id": "p1"})
check("73. строку «требует внимания» владелец может запустить снова",
      _st2.get("ok") is True and _state_note(_rid)[0] == "launching" and len(ENQ) == 1, (_st2, _state_note(_rid)))

#  Отмена элемента в очереди запусков: до старта — доказанно не отправляли, строка возвращается.
NS["print_queue"][:] = [{"id": "1", "printer_id": "p1", "printer_name": "P1S-01",
                         "due_ts": time.time() + 60, "qw_id": _rid, "durable_id": "", "send_job_id": ""}]
M["api_print_queue_cancel"]({"ids": ["1"]})
_s, _n = _state_note(_rid)
check("74. запуск отменён в очереди запусков — строка вернулась в ожидание с причиной",
      _s == "waiting" and "отмен" in (_n or ""), (_s, _n))

#  Восстановление запуска: строку, которую очередь запусков ещё намерена выполнить, перезапуск
#  НЕ гасит — иначе её настоящий исход некуда было бы записать, и владелец запустил бы вторую печать.
_reset()
printer("p1", "P1S-01", ams=["PLA"])
_add3 = M["api_queue_wait_add"]({"gcode_file": "pla.gcode.3mf"})
_rid3 = _add3.get("id")
M["api_queue_wait_start"]({"id": _rid3, "printer_id": "p1"})
conn.execute("INSERT INTO print_launch_queue (id, status, payload, updated_at) VALUES (?,?,?,?)",
             ("plq_1", "recovery_hold", json.dumps({"qw_id": _rid3, "printer_id": "p1"}), time.time()))
conn.commit()
M["_qw_recover_launching"]()
check("77. запуск ждёт подтверждения после перезапуска — строка остаётся «запускается», а не гаснет",
      _state_note(_rid3)[0] == "launching", _state_note(_rid3))
M["_qw_launch_outcome"]({"qw_id": _rid3, "printer_name": "P1S-01"}, True, "", "ok")
check("78. продолженный запуск закрывает строку", _state_note(_rid3)[0] == "done", _state_note(_rid3))

conn.execute("UPDATE queue_wait SET state='launching' WHERE id=?", (_rid3,))
conn.execute("UPDATE print_launch_queue SET status='recovery_hold' WHERE id='plq_1'")
conn.commit()
M["api_print_queue_recovery_cancel"]()
check("79. восстановление отменено — строка вернулась в ожидание, а не осталась висеть",
      _state_note(_rid3)[0] == "waiting" and "отмен" in (_state_note(_rid3)[1] or ""), _state_note(_rid3))

conn.execute("UPDATE queue_wait SET state='launching' WHERE id=?", (_rid3,))
conn.commit()
_rm = M["api_queue_wait_remove"]({"id": _rid3})
check("80. строку, которая запускается, убрать нельзя: запуск от этого не отменился бы",
      _rm.get("ok") is False and _rm.get("error") == "launching"
      and conn.execute("SELECT COUNT(*) c FROM queue_wait WHERE id=?", (_rid3,)).fetchone()["c"] == 1, _rm)
conn.execute("UPDATE queue_wait SET state='waiting' WHERE id=?", (_rid3,))
conn.commit()
check("81. а из ожидания — убирается как прежде",
      M["api_queue_wait_remove"]({"id": _rid3}).get("ok") is True)

_LIFE = SRC[SRC.index("def _qw_launch_outcome"):SRC.index("def _qw_recover_launching")]
check("75. исход пишется только строке, которая ещё ждёт ответа (чужое состояние не перетираем)",
      "WHERE id=? AND state IN ('launching','attention')" in SRC and "_QW_SENT_NOT_STARTED" in _LIFE)
check("76. воркер очереди проставляет исход там же, где узнаёт его",
      "_qw_launch_outcome(q, _ok, _err, _st)" in SRC and "_qw_recover_launching()" in SRC)

print("--- 13. 16.10.2026: FlashForge, куда пойдёт филамент и цвет, вариант материала, причина возврата ---")
#  R-141: FlashForge (без станции материалов) материал по сети не сообщает — однофиламентный файл
#  предлагается только на ручной запуск с просьбой проверить катушку.
_reset()
printer("ff", "AD5M-02", ptype="flashforge", model="Flashforge Adventurer 5M", raw="ready")
m = match("pla_nomodel.gcode.3mf")
_row = M["_qw_public"]({"id": "x", "gcode_file": "pla_nomodel.gcode.3mf"}, info_of("pla_nomodel.gcode.3mf")[0], m)
check("96. (R-141) FlashForge 5M в покое, файл на PLA: подбор есть, но «проверяет человек» (owner_check, ручной запуск)",
      m["pid"] == "ff" and verdict_of(m, "ff") == "owner_check" and m.get("unverified") is True
      and _row.get("match_feed") == "unverified" and _row.get("match_unverified") is True, (m, _row.get("match_feed")))
check("97. (R-141) правило автомата: такую строку автозапуск не берёт («owner_check»)",
      M["_qw_auto_needs_human"](m) == "owner_check", M["_qw_auto_needs_human"](m))
printer("bb", "P1S-PLA", ams=["PLA"])
m = match("pla_nomodel.gcode.3mf")
check("98. (R-141) есть готовый принтер с PLA — выбирается он, FlashForge остаётся запасным",
      m["pid"] == "bb" and not m.get("unverified") and verdict_of(m, "ff") == "owner_check", m)
m = match("pla_nomodel.gcode.3mf", prefer="ff")
check("99. (R-141) владелец сам выбрал FlashForge в окне — запуск идёт на него, а не на готовый P1S",
      m["pid"] == "ff" and m.get("unverified") is True, m)
mk3mf("pla_abs_nomodel.gcode.3mf", ["PLA", "ABS"], {1: [(1, "PLA"), (2, "ABS")]}, model="")
m = match("pla_abs_nomodel.gcode.3mf")
check("100. (R-141) файл на два материала FlashForge 5M не предлагается: своим вердиктом «одно сопло, а "
      "филаментов несколько», а не «материал на внешней катушке»",
      verdict_of(m, "ff") == "single_nozzle_multi", m)
NS["p_states"]["ff"]["matl_station"] = True
m = match("pla_nomodel.gcode.3mf", prefer="ff")
check("101. (R-141) AD5X со станцией материалов — своим вердиктом «станция не поддерживается», а не «материал "
      "не виден» (станция свои ячейки сообщает); выбирается готовый P1S",
      verdict_of(m, "ff") == "ff_station" and m["pid"] == "bb", m)
_reset()
printer("ff", "AD5M-02", ptype="flashforge", model="Flashforge Adventurer 5M", raw="ready")
m = match("pla_abs_nomodel.gcode.3mf")
_reset()
printer("ff", "AD5X-01", ptype="flashforge", model="Flashforge AD5X", raw="ready")
NS["p_states"]["ff"]["matl_station"] = True
m2 = match("pla_nomodel.gcode.3mf")
check("101b. (разбор пакета) FlashForge, которому файл не подходит, — итог строки «принтеры не подходят к файлу», "
      "а не «нет нужного материала» и не «программа не видит материал»",
      m["pid"] == "" and m["reason"] == "incompatible" and m2["pid"] == "" and m2["reason"] == "incompatible",
      (m["reason"], m2["reason"]))
_reset()
printer("ff", "AD5M-02", ptype="flashforge", model="Flashforge Adventurer 5M", raw="ready")
_add = M["api_queue_wait_add"]({"gcode_file": "pla_nomodel.gcode.3mf"})
_st0 = M["api_queue_wait_start"]({"id": _add.get("id")})
_s0 = conn.execute("SELECT state, note FROM queue_wait WHERE id=?", (_add.get("id"),)).fetchone()
check("102. (R-141) запуск без выбранного владельцем принтера на FlashForge не уходит — строка ждёт",
      _st0.get("ok") is False and not ENQ and _s0["state"] == "waiting", (_st0, dict(_s0)))
_st1 = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "ff"})
check("103. (R-141) владелец подтвердил этот FlashForge — запуск поставлен в очередь запусков",
      _st1.get("ok") is True and len(ENQ) == 1 and ENQ[0]["printer_id"] == "ff", (_st1, ENQ))
_s1 = conn.execute("SELECT state, note FROM queue_wait WHERE id=?", (_add.get("id"),)).fetchone()
check("103b. (разбор пакета) пометка запуска FlashForge — «материал проверил человек», а не «двухсопельный: "
      "сопло не проверено» (у него одно сопло)",
      _s1["state"] == "launching" and _s1["note"] == "запускается на AD5M-02 (материал проверил человек)", dict(_s1))

#  R-016: куда пойдёт каждый филамент и совпадает ли цвет.
mk3mf("pla_white.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, colours=["#FFFFFF"])
_reset()
printer("p1", "P1S-КРАСНЫЙ", ams=[{"type": "PLA", "color_raw": "FF0000FF", "present": True}])
m = match("pla_white.gcode.3mf")
_row = M["_qw_public"]({"id": "x", "gcode_file": "pla_white.gcode.3mf"}, info_of("pla_white.gcode.3mf")[0], m)
_sl = (_row.get("match_slots") or [{}])[0]
check("104. (R-016) в файле белый PLA, в слоте красный: принтер подходит (решает человек), а в строке видно — "
      "AMS 1·1, цвет файла и слота, «цвет отличается»",
      m["pid"] == "p1" and _sl.get("label") == "AMS 1·1" and _sl.get("where") == "ams"
      and _sl.get("file_color") == "#FFFFFF" and _sl.get("slot_color") == "#FF0000" and _sl.get("rel") == "mismatch",
      _row.get("match_slots"))
check("105. (R-118) автомат такую строку не берёт: «цвет отличается»",
      M["_qw_auto_needs_human"](m) == "color_mismatch", M["_qw_auto_needs_human"](m))
_reset()
printer("p1", "P1S-БЕЛЫЙ", ams=[{"type": "PLA", "color_raw": "FFFFFFFF", "present": True}])
m = match("pla_white.gcode.3mf")
check("106. НЕ ВАКУУМ: тот же файл и белый слот (по датчику) — цвет точный, автомат может",
      ((m["feed"] or {}).get("slots") or [{}])[0].get("rel") == "exact" and M["_qw_auto_needs_human"](m) == "", m)
_reset()
printer("p1", "P1S-БЕЗ-ДАТЧИКА", ams=[{"type": "PLA", "color_raw": "FFFFFFFF"}])
m = match("pla_white.gcode.3mf")
check("107. (R-118) слот без подтверждения датчиком подачи — ручной запуск можно, автомат нет («no_sensor»)",
      m["pid"] == "p1" and M["_qw_auto_needs_human"](m) == "no_sensor", m)
_reset()
printer("p1", "P1S-ВНЕШ", ext="PLA")
NS["p_states"]["p1"]["ext_trays"]["255"]["tray_color"] = "0000FFFF"
m = match("pla_white.gcode.3mf")
_row = M["_qw_public"]({"id": "x", "gcode_file": "pla_white.gcode.3mf"}, info_of("pla_white.gcode.3mf")[0], m)
_sl = (_row.get("match_slots") or [{}])[0]
check("108. (R-016) внешняя катушка: в строке — «внешняя», синий на катушке против белого в файле",
      _sl.get("where") == "ext" and _sl.get("slot_color") == "#0000FF" and _sl.get("rel") == "mismatch"
      and M["_qw_auto_needs_human"](m) == "external", (_row.get("match_slots"), M["_qw_auto_needs_human"](m)))
#  K2: цвет файла — из «; filament_colour», цвет ячейки — из отчёта CFS.
mkgcode("k2_t0_petg_col.gcode", ["PETG", "PETG"], ["3.66", "0.00"], [0], colours=["#00FF00", "#000000"])
_reset()
printer("k2", "K2-01", ptype="klipper", model="Creality K2 Plus", cfs=[("PETG", True)])
NS["p_states"]["k2"]["cfs_trays"][0]["color"] = "#00FF00"
m = match("k2_t0_petg_col.gcode")
_sl = (((m["feed"] or {}).get("slots")) or [{}])[0]
check("109. (R-016) K2: цвет файла из filament_colour совпал с ячейкой T1A — «точный», автомат может",
      m["pid"] == "k2" and _sl.get("label") == "CFS T1A" and _sl.get("rel") == "exact"
      and M["_qw_auto_needs_human"](m) == "", m)
NS["p_states"]["k2"]["cfs_trays"][0]["color"] = "#00F000"
m = match("k2_t0_petg_col.gcode")
check("110. (R-016) ячейка почти того же цвета — «близкий»: ручной запуск можно, автомат нет",
      m["pid"] == "k2" and M["_qw_auto_needs_human"](m) == "color_close", m)

#  R-115: вариант материала — номер филамента известен у файла и у слота и различается.
mk3mf("pla_matte.gcode.3mf", ["PLA"], {1: [(1, "PLA")]}, colours=["#FFFFFF"], extra_ps={"filament_ids": ["GFA01"]})
_reset()
printer("p1", "P1S-BASIC", ams=[{"type": "PLA", "color_raw": "FFFFFFFF", "present": True, "tray_info_idx": "GFA00"}])
m = match("pla_matte.gcode.3mf")
_row = M["_qw_public"]({"id": "x", "gcode_file": "pla_matte.gcode.3mf"}, info_of("pla_matte.gcode.3mf")[0], m)
_sl = (_row.get("match_slots") or [{}])[0]
check("111. (R-115) в файле PLA Matte (GFA01), в слоте Basic (GFA00): ручной запуск можно, в строке «другой вариант», "
      "автомат нет",
      m["pid"] == "p1" and _sl.get("variant") is True and _sl.get("file_fid") == "GFA01" and _sl.get("slot_fid") == "GFA00"
      and M["_qw_auto_needs_human"](m) == "variant", (_row.get("match_slots"), M["_qw_auto_needs_human"](m)))
NS["p_states"]["p1"]["ams_trays"][0]["tray_info_idx"] = ""
m = match("pla_matte.gcode.3mf")
check("112. номер филамента у слота не известен — вариант не придумывается, сравнение как раньше",
      ((m["feed"] or {}).get("slots") or [{}])[0].get("variant") is False and M["_qw_auto_needs_human"](m) == "", m)

#  R-008: «Печатать всё равно» из очереди — {skip_filament: true} едет с элементом.
_reset()
printer("p1", "P1S-01", ams=["PLA"])
_add = M["api_queue_wait_add"]({"gcode_file": "pla.gcode.3mf"})
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p1", "skip_filament": True})
check("113. (R-008) запуск с решением владельца: элемент очереди запусков несёт skip_filament=True",
      _st.get("ok") is True and len(ENQ) == 1 and ENQ[0].get("skip_filament") is True, (_st, ENQ))
_reset()
printer("p1", "P1S-01", ams=["PLA"])
_add = M["api_queue_wait_add"]({"gcode_file": "pla.gcode.3mf"})
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p1", "skip_filament": "yes"})
check("114. без явного true склад не обходится (строка «yes» — не решение владельца)",
      _st.get("ok") is True and ENQ and "skip_filament" not in ENQ[0], ENQ)

#  R-117: возврат в ожидание пишет причину КОДОМ, а не оставляет «запускается на X».
_reset()
printer("p1", "P1S-01", ams=["PLA"])
_add = M["api_queue_wait_add"]({"gcode_file": "pla.gcode.3mf"})
conn.execute("UPDATE queue_wait SET note='запускается на P1S-01' WHERE id=?", (_add.get("id"),))
conn.commit()
_real_enq = NS["api_print_queue_enqueue"]
NS["api_print_queue_enqueue"] = lambda data: {"status": "ok", "queued": [], "held": [], "notes": [],
                                              "blocked": [{"status": "low_filament", "printer_id": "p1",
                                                           "shortfall": [{"material": "PLA"}]}]}
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p1"})
NS["api_print_queue_enqueue"] = _real_enq
_s, _n = _state_note(_add.get("id"))
check("115. (R-117) склад отказал при постановке — строка в ожидании с причиной «not_started:low_filament», "
      "ответ несёт список нехватки для окна решения",
      _st.get("error") == "enqueue_rejected" and _s == "waiting" and _n == "not_started:low_filament"
      and ((_st.get("enqueue") or {}).get("blocked") or [{}])[0].get("status") == "low_filament", (_st, _s, _n))
NS["p_states"]["p1"]["status"] = "RUNNING"
_st = M["api_queue_wait_start"]({"id": _add.get("id"), "printer_id": "p1"})
_s, _n = _state_note(_add.get("id"))
check("116. (R-117) принтер занялся — в строке «not_started:busy», а не прежнее «запускается на …»",
      _st.get("ok") is False and _s == "waiting" and _n == "not_started:busy", (_st, _s, _n))
_relaunch_id = _add.get("id")
conn.execute("UPDATE queue_wait SET state='launching' WHERE id=?", (_relaunch_id,))
conn.commit()
M["_qw_launch_outcome"]({"qw_id": _relaunch_id, "printer_name": "P1S-01"}, False,
                        "No connection to the printer to upload the file.", "not_sent")
_s, _n = _state_note(_relaunch_id)
check("117. (R-117) отправка сказала «ничего не ушло» (sent=False) — строка в ожидании, хотя текст причины незнакомый",
      _s == "waiting" and _n.startswith("not_started:") and "No connection" in _n, (_s, _n))
conn.execute("UPDATE queue_wait SET state='launching' WHERE id=?", (_relaunch_id,))
conn.commit()
M["_qw_launch_outcome"]({"qw_id": _relaunch_id, "printer_name": "P1S-01"}, False, "already running", "error")
check("118. (R-117) «already running» не доказывает «не отправлено» — строка «требует внимания», причина КОДОМ "
      "(«interrupted:…»), интерфейс покажет её словами",
      _state_note(_relaunch_id) == ("attention", "interrupted:already running"), _state_note(_relaunch_id))
conn.execute("UPDATE queue_wait SET state='done', note='запущено на P1S-01' WHERE id=?", (_relaunch_id,))
conn.commit()
_cb = M["_qw_start_unconfirmed"](_relaunch_id)
_cb({"status": "error", "reason": "upload failed"})
check("119. (R-117) немедленная ошибка отправки закрытую строку не трогает (её исход записал воркер)",
      _state_note(_relaunch_id)[0] == "done", _state_note(_relaunch_id))
_cb({"status": "error", "reason": "start_not_confirmed"})
check("120. (R-117) принтер принял файл, а печать не началась — строка «требует внимания» с причиной кодом",
      _state_note(_relaunch_id) == ("attention", "start_not_confirmed"), _state_note(_relaunch_id))

print("--- 14. интерфейс очереди: причины словами, подача и цвет, окно «Материал закончился» (Node) ---")
#  16.10.2026 (R-117, R-016, R-141, R-008): НАСТОЯЩИЕ функции очереди и окна решения вырезаются из
#  web/app.js и исполняются в Node со стабами сети и окон. Сеть подменена записью запросов.
import subprocess  # noqa: E402

_APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
_NODE = (r"C:\Program Files\nodejs\node.exe" if os.path.isfile(r"C:\Program Files\nodejs\node.exe")
         else (shutil.which("node") or "node"))


def _cut(start, what):
    i = _APPJS.find(start)
    if i < 0:
        return None
    j = _APPJS.find("\n    };\n", _APPJS.find(what, i))
    return _APPJS[i:j + len("\n    };\n")] if j > 0 else None


_blk_q = _cut("    const queueReasonText = (r) => {", "const queueStart = async (row) => {")
_blk_dec = _cut("    const filDecision = ref(", "const filForceStart = async")
_blk_rr = _cut("    const READINESS_REASON_RU = {", "const readinessReasonText")
#  16.10.2026 (разбор пакета): НАСТОЯЩИЕ словарь интерфейса и tr — фраза принтера в строке очереди
#  обязана переводиться тем же словарём, что у прямого запуска.
_ln_ru = next((l for l in _APPJS.splitlines() if l.startswith("    const RU = {")), None)
_ln_tr = next((l for l in _APPJS.splitlines() if l.startswith("    const tr = (s) =>")), None)
check("121. функции очереди, окна решения, тексты причин и словарь интерфейса найдены в app.js",
      bool(_blk_q) and bool(_blk_dec) and bool(_blk_rr) and bool(_ln_ru) and bool(_ln_tr))
_HARNESS = r"""
'use strict';
const ref = (v) => ({ value: v });
const computed = (fn) => ({ get value() { return fn(); } });
const lang = ref('ru');
/*I18N*/
const _L = (ru, en) => (lang.value === 'ru' ? ru : en);
const toasts = [], calls = [], asks = [];
const pushToast = (t, k) => toasts.push([String(t), k]);
const installedModules = ref([]);
const fetchPrintQueue = () => {}, fetchSendJobs = () => {}, loadQueueWait = () => {};
const setTimeout = () => {};
const queueAutoOn = ref(true);
const queueBusy = ref('');
let askAnswer = true;
const askConfirm = async (o) => { asks.push(o); return askAnswer; };
let answer = () => ({ ok: true, printer_name: 'P1S-01' });
const fetch = async (url, opt) => {
    const body = opt && opt.body ? JSON.parse(opt.body) : null;
    calls.push({ url, body });
    const r = answer(url, body);
    return { json: async () => r };
};
/*CODE*/
const out = {};
(async () => {
    const W = (row) => queueWhyLines(Object.assign({ match_printer_id: '', candidates: [] }, row), 4);
    // А. Причины у строк, вернувшихся в ожидание (R-117) — словами, без сырых кодов.
    out.a_busy = W({ state: 'waiting', note: 'not_started:printer_busy' });
    out.a_low = W({ state: 'waiting', note: 'not_started:low_filament' });
    out.a_text = W({ state: 'waiting', note: 'not_started:No connection to the printer to upload the file. Make sure the printer is powered on and online.' });
    out.a_intr = W({ state: 'attention', note: 'interrupted:already running' });
    lang.value = 'en';
    out.a_text_en = W({ state: 'waiting', note: 'not_started:No connection to the printer to upload the file. Make sure the printer is powered on and online.' });
    lang.value = 'ru';
    out.a_snc = W({ state: 'attention', note: 'start_not_confirmed' });
    out.a_stale = W({ state: 'waiting', note: 'запускается на P1S-01' });
    out.a_legacy = W({ state: 'waiting', note: 'запуск не состоялся: printer_held' });
    out.a_auto = W({ state: 'waiting', note: 'auto_needs_human:color_mismatch' });
    out.a_autolow = W({ state: 'waiting', note: 'auto_low_filament' });
    queueAutoOn.value = false;
    out.a_auto_off = W({ state: 'waiting', note: 'auto_needs_human:color_mismatch' });
    queueAutoOn.value = true;
    // Б. Куда пойдёт филамент и «цвет отличается» (R-016).
    const RED = { id: 'r1', gcode_file: 'kubik.gcode.3mf', state: 'waiting', note: '', material: 'PLA',
                  match_printer_id: 'p1', match_printer_name: 'P1S-01', match_feed: 'ams',
                  match_slots: [{ material: 'PLA', where: 'ams', label: 'AMS 1·1', file_color: '#FFFFFF', slot_color: '#FF0000',
                                  rel: 'mismatch', variant: false, file_fid: '', slot_fid: '' }] };
    out.b_lines = W(RED);
    const VAR = Object.assign({}, RED, { match_slots: [Object.assign({}, RED.match_slots[0], { slot_color: '#FFFFFF', rel: 'exact',
                                                                                              variant: true, file_fid: 'GFA01', slot_fid: 'GFA00' })] });
    out.b_var = W(VAR);
    const VAR2 = Object.assign({}, VAR, { match_slots: [Object.assign({}, VAR.match_slots[0], { file_fid: 'GFL99', slot_fid: 'GFZZ7' })] });
    out.b_var2 = W(VAR2);
    // В. FlashForge (R-141): строка, кандидат и окно подтверждения.
    const FF = { id: 'r2', gcode_file: 'kubik.gcode', state: 'waiting', note: '', material: 'PLA', match_printer_id: 'ff',
                 match_printer_name: 'AD5M-02', match_feed: 'unverified', match_unverified: true,
                 match_slots: [{ material: 'PLA', where: 'ext', label: '', file_color: '', slot_color: '', rel: 'unknown' }] };
    out.c_lines = W(FF);
    out.c_cand = queueVerdictText({ verdict: 'ff_station' });
    out.c_cand_multi = queueVerdictText({ verdict: 'single_nozzle_multi' });
    out.c_cand_unk = queueVerdictText({ verdict: 'material_unknown_on_printer' });
    out.c_cand_ok = queueVerdictText({ verdict: 'owner_check' });
    askAnswer = false;
    await queueStart(FF);
    out.c_ask = asks[0] ? { text: asks[0].text, list: asks[0].list } : null;
    await queueStart(RED);
    out.b_ask = asks[1] ? { text: asks[1].text, list: asks[1].list } : null;
    out.c_calls = calls.length;
    // Г. Склад против при «Запустить» из очереди (R-008): то же окно, все нехватки, порядок «принято — потом списание».
    askAnswer = true; asks.length = 0; calls.length = 0; toasts.length = 0;
    const LOW2 = { ok: false, error: 'enqueue_rejected', enqueue: { queued: [], held: [], notes: [], blocked: [
        { status: 'low_filament', printer_id: 'p1', printer_name: 'P1S-01', shortfall: [
            { material: 'PLA', color_name: 'Белый', needed: 120, available: 30, slot: 0, external: false, resolve_steps: [],
              override_steps: [{ url: '/api/mod/x/spool/S1/adjust', method: 'POST', body: { delta_g: -30 } }] },
            { material: 'PETG', color_name: 'Чёрный', needed: 80, available: 10, slot: 1, external: false, resolve_steps: [],
              override_steps: [{ url: '/api/mod/x/spool/S2/adjust', method: 'POST', body: { delta_g: -10 } }] }] }] } };
    answer = () => LOW2;
    await queueStart(RED);
    out.d_open = filDecision.value.open === true && filDecision.value.direct === true;
    const row = filDecision.value.rows[0] || {};
    out.d_row = { shorts: (row.shorts || []).map(s => s.material + ':' + s.needed + '/' + s.available), ovr: (row.override_steps || []).length };
    out.d_first_body = calls[0] && calls[0].body;
    calls.length = 0;
    answer = (url) => url.indexOf('/adjust') > 0 ? { ok: true } : { ok: true, printer_name: 'P1S-01', enqueue: { notes: [] } };
    await filForceStart(row);
    out.d_after_first = calls.length;
    await filForceStart(row);
    out.d_calls = calls.map(c => [c.url, c.body]);
    out.d_state = row.state;
    // Д. «Поставил новую катушку», а склад снова против — окно остаётся открытым с новой нехваткой (R-019).
    closeFilamentDecision(); calls.length = 0; toasts.length = 0;
    const LOW1 = JSON.parse(JSON.stringify(LOW2));
    LOW1.enqueue.blocked[0].shortfall = [Object.assign({}, LOW2.enqueue.blocked[0].shortfall[0],
        { resolve_steps: [{ url: '/api/mod/x/spool', method: 'POST', body: { a: 1 } }] })];
    const LOW_PETG = JSON.parse(JSON.stringify(LOW2));
    LOW_PETG.enqueue.blocked[0].shortfall = [LOW2.enqueue.blocked[0].shortfall[1]];
    answer = () => LOW1;
    await queueStart(RED);
    const row2 = filDecision.value.rows[0] || {};
    answer = (url) => url.indexOf('/api/mod/') === 0 ? { ok: true } : LOW_PETG;
    await filReceiveAndStart(row2);
    out.e_open = filDecision.value.open;
    out.e_state = row2.state;
    out.e_mat = (row2.shorts || []).map(s => s.material);
    out.e_calls = calls.map(c => c.url);
    out.e_toasts = toasts.map(t => t[0]);
    console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
"""
_res = {}
if _blk_q and _blk_dec and _blk_rr:
    _td = tempfile.mkdtemp(prefix="qw_js_")
    _hp = os.path.join(_td, "harness.js")
    io.open(_hp, "w", encoding="utf-8").write(_HARNESS.replace("/*I18N*/", (_ln_ru or "") + "\n" + (_ln_tr or ""))
                                              .replace("/*CODE*/", _blk_rr + _blk_dec + _blk_q))
    try:
        _pr = subprocess.run([_NODE, _hp], capture_output=True, text=True, encoding="utf-8", timeout=60)
        _last = (_pr.stdout or "").strip().splitlines()[-1:] or ["{}"]
        _res = json.loads(_last[0])
        if not _res and _pr.stderr:
            _res = {"error": _pr.stderr[-400:]}
    except Exception as _ex:
        _res = {"error": "node: %s" % _ex}
    shutil.rmtree(_td, ignore_errors=True)
check("122. сценарий интерфейса исполнился без ошибок", "error" not in _res, _res.get("error"))


def _has(lines, *parts):
    return any(all(p in (l or "") for p in parts) for l in (lines or []))


def _no_code(lines):
    return not any(c in (l or "") for l in (lines or []) for c in
                   ("printer_busy", "low_filament", "start_not_confirmed", "auto_needs_human", "not_started", "printer_held"))


check("123. (R-117) строка вернулась в ожидание — причина словами: «запуск не состоялся: принтер занят печатью…»",
      _has(_res.get("a_busy"), "запуск не состоялся", "принтер занят печатью") and _has(_res.get("a_low"), "не хватает материала")
      and _no_code(_res.get("a_busy")) and _no_code(_res.get("a_low")), (_res.get("a_busy"), _res.get("a_low")))
check("124. (R-117) причина от принтера фразой — через словарь интерфейса: по-русски в русском, как есть в английском; "
      "старые записи «запуск не состоялся: printer_held» — тоже словами",
      _has(_res.get("a_text"), "запуск не состоялся", "Нет связи с принтером для загрузки файла")
      and not _has(_res.get("a_text"), "No connection")
      and _has(_res.get("a_text_en"), "the launch did not happen", "No connection to the printer to upload the file")
      and _has(_res.get("a_legacy"), "принтер удержан")
      and _no_code(_res.get("a_legacy")), (_res.get("a_text"), _res.get("a_text_en"), _res.get("a_legacy")))
check("124b. (R-117, разбор пакета) «требует внимания» с причиной «already running» — словами, без сырого текста",
      _has(_res.get("a_intr"), "запуск прерван", "этот запуск уже выполнялся", "проверьте принтер")
      and not _has(_res.get("a_intr"), "already running") and not _has(_res.get("a_intr"), "interrupted"),
      _res.get("a_intr"))
check("125. (R-117) «принтер принял файл, но печать не началась — посмотрите экран принтера» у строки «требует внимания»",
      _has(_res.get("a_snc"), "принтер принял файл, но печать не началась", "экран принтера") and _no_code(_res.get("a_snc")),
      _res.get("a_snc"))
check("126. устаревшая пометка «запускается на …» у ожидающей строки не показывается",
      not _has(_res.get("a_stale"), "запускается"), _res.get("a_stale"))
check("127. (R-118) пометки автозапуска — словами, пока он включён; выключен — не показываются",
      _has(_res.get("a_auto"), "автозапуск ждёт вас", "цвет катушки отличается") and _has(_res.get("a_autolow"), "не хватает материала")
      and not _has(_res.get("a_auto_off"), "автозапуск") and _no_code(_res.get("a_auto")), (_res.get("a_auto"), _res.get("a_auto_off")))
check("128. (R-016) строка очереди: подача «PLA — AMS 1·1» и «цвет отличается: … в файле белый (#FFFFFF), на катушке красный (#FF0000)»",
      _has(_res.get("b_lines"), "подача: PLA — AMS 1·1")
      and _has(_res.get("b_lines"), "цвет отличается", "белый (#FFFFFF)", "красный (#FF0000)"), _res.get("b_lines"))
check("129. (R-115) другой вариант материала назван в строке СЛОВАМИ (по профилям Bambu Studio), без кодов",
      _has(_res.get("b_var"), "другой вариант материала", "в файле Bambu PLA Matte", "в слоте Bambu PLA Basic")
      and not _has(_res.get("b_var"), "GFA0"), _res.get("b_var"))
check("129b. незнакомый код варианта — «профиль <код>», знакомый Generic — названием",
      _has(_res.get("b_var2"), "в файле Generic PLA", "в слоте профиль GFZZ7"), _res.get("b_var2"))
_ba = _res.get("b_ask") or {}
check("130. (R-016) окно «Запустить печать?»: куда пойдёт филамент и что цвет отличается — решает человек",
      "PLA → AMS 1·1 — цвет отличается" in (_ba.get("list") or "") and "Цвет отличается" in (_ba.get("list") or ""), _ba)
_ca = _res.get("c_ask") or {}
check("131. (R-141) FlashForge: в окне — «FlashForge не сообщает по сети, какой материал заправлен. Проверьте на принтере, что стоит PLA.»",
      "FlashForge не сообщает по сети, какой материал заправлен. Проверьте на принтере, что стоит PLA." in (_ca.get("text") or "")
      and "двухсопельный" not in (_ca.get("text") or ""), _ca)
check("132. (R-141) строка FlashForge и кандидаты: «проверьте на принтере»; станция материалов и файл на несколько "
      "филаментов — своими словами; «материал не виден» — прежний общий текст",
      _has(_res.get("c_lines"), "FlashForge не сообщает", "PLA")
      and _res.get("c_cand") == "у принтера станция материалов — запуск из очереди с неё пока не поддерживается"
      and _res.get("c_cand_multi") == "у принтера одно сопло без станции материалов, а в файле несколько филаментов"
      and _res.get("c_cand_unk") == "материал этого принтера программе не виден"
      and "только ручной запуск" in (_res.get("c_cand_ok") or ""),
      (_res.get("c_lines"), _res.get("c_cand"), _res.get("c_cand_multi"), _res.get("c_cand_unk"), _res.get("c_cand_ok")))
check("133. отказ в окне подтверждения ничего не отправляет", _res.get("c_calls") == 0, _res.get("c_calls"))
check("134. (R-008) склад против при «Запустить» из очереди — открыто окно «Материал закончился» (одиночный запуск)",
      _res.get("d_open") is True and (_res.get("d_first_body") or {}).get("skip_filament") is None, (_res.get("d_open"), _res.get("d_first_body")))
check("135. (R-008) в окне — ОБЕ нехватки, «Печатать всё равно» спишет обе катушки",
      (_res.get("d_row") or {}).get("shorts") == ["PLA:120/30", "PETG:80/10"] and (_res.get("d_row") or {}).get("ovr") == 2,
      _res.get("d_row"))
_dc = _res.get("d_calls") or []
check("136. (R-008) «Печатать всё равно»: первое нажатие взводит; второе — СНАЧАЛА очередь принимает запуск с решением "
      "владельца, ПОТОМ списываются обе катушки",
      _res.get("d_after_first") == 0 and [c[0] for c in _dc] == ["/api/queue-wait/start", "/api/mod/x/spool/S1/adjust",
                                                                 "/api/mod/x/spool/S2/adjust"]
      and (_dc[0][1] or {}).get("skip_filament") is True and _res.get("d_state") == "queued", (_res.get("d_after_first"), _dc))
check("137. (R-019) «Поставил новую катушку», а склад снова против — окно открыто, в строке новая нехватка (PETG), а не «не удалось»",
      _res.get("e_open") is True and _res.get("e_state") == "" and _res.get("e_mat") == ["PETG"]
      and _res.get("e_calls") == ["/api/queue-wait/start", "/api/mod/x/spool", "/api/queue-wait/start"]
      and any("снова сообщает нехватку" in t for t in (_res.get("e_toasts") or [])), _res)

try:
    conn.close()
    shutil.rmtree(_tmp, ignore_errors=True)
except Exception:
    pass

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
