# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.09.2026 — АВТОЗАПУСК очереди ожидания: печать уходит сама только по подтверждению «Стол очищен».

ЗАЧЕМ. Владелец попросил, чтобы при совпадении условий печать из очереди запускалась без нажатия.
Но программа не может знать, лежит ли на столе готовая деталь: датчика занятости стола нет ни
у одной поддерживаемой марки (проверено по источникам 16.09.2026 — ни Bambu, ни Klipper, ни
FlashForge такого поля не сообщают, и показать своё окно на экране принтера тоже нечем у Bambu
и FlashForge). Поэтому доказательством остаётся ОДНО: человек нажал «Стол очищен». Подтверждение —
тот же одноразовый жетон, что и у «Печатать весь проект» (plate_clearances), второго механизма
разрешения в программе нет.

ГЛАВНОЕ ПРАВИЛО, проверенное здесь (и пропущенное первой редакцией этого набора — нашла
состязательная проверка): жетон нужен ВСЕГДА, а не только когда программа видела завершение
печати. На столе может лежать что угодно, чего программа своей печатью не видела: деталь,
напечатанная с флешки при выключенном сервере, калибровочный отпечаток, оснастка. Принтер при
этом просто «в покое» — и раньше печать уходила поверх без слова человека.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ:
  · по умолчанию автозапуск ВЫКЛЮЧЕН, и выключенный не делает ничего;
  · разрешение двойное: выключатель фермы + список принтеров + отметка queue_allowed;
  · принтер В ПОКОЕ без подтверждения НЕ запускается, с подтверждением — запускается;
  · принтер, ТОЛЬКО ЧТО ЗАКОНЧИВШИЙ печать, без живого жетона НЕ запускается;
  · жетон ТРАТИТСЯ: вторая печать на тот же стол не уйдёт;
  · строки «требует внимания» автомат не трогает — их исход неясен, решает человек;
  · пока не разобраны запуски, прерванные перезапуском (recovery_hold), автомат молчит целиком;
  · принтер с незакрытой строкой долговременной очереди считается занятым;
  · за один проход уходит НЕ БОЛЬШЕ одного запуска;
  · ИСКЛЮЧЕНИЕ внутри запуска возвращает строку владельцу, а не оставляет её занятой навсегда;
  · причина неудачи хранится КОДОМ (её показывают на двух языках), а не русской фразой;
  · НЕ ВАКУУМ: те же данные при выключенном выключателе дают ноль запусков.
16.10.2026 (R-118, R-008, R-141, R-115):
  · автомат выбирает ТОЛЬКО среди принтеров с подтверждённым столом (а не первый свободный);
  · только доказанная подача (слот AMS по датчику, ячейка CFS) и точный цвет; внешняя катушка, другой
    цвет, слот без датчика, FlashForge — строка ждёт человека с причиной кодом;
  · склад спрашивается ДО траты жетона: «не хватает» — жетон цел, строка ждёт с пометкой;
  · «Стол очищен» после отмены Bambu держится, а после «Стоп» в FM принимается, когда отмена
    закончилась, — на НАСТОЯЩИХ снимке безопасности и стороже жетонов.

КАК. Ни сервер, ни принтеры не поднимаются: из server.py в рантайме ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ исходники
подбора и автозапуска и исполняются со стабами на временных базах SQLite. Модуль жетонов берётся
НАСТОЯЩИЙ (app/project_orchestrator) со своей временной базой: правила подтверждения обязаны
проверяться на настоящем коде, а не на его пересказе. Настройки фермы читаются из НАСТОЯЩЕЙ
таблицы app_settings временной базы — автозапуск читает свой выключатель прямо оттуда.
Ни одна команда никуда не отправляется: очередь запусков подменена и только записывает.

Запуск:  python tools/test_queue_auto_start.py      (0 = правила соблюдаются)
"""
import ast
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SRC = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
SENTINEL = "QUEUE_AUTO_START_SENTINEL_1609"

from app import project_orchestrator as _orch          # noqa: E402
from app import bambu_start_policy as _bstart          # noqa: E402
from app import gcode_tool_slot as _gts                # noqa: E402
from app.model_compat import detect_target, _models_compatible, _BAMBU_CODES   # noqa: E402
from app.utils import _normalize_model                 # noqa: E402
from app.part_counter import is_3mf_printable          # noqa: E402

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, ("  :: " + str(detail)[:300]) if detail else ""))


# ── ДОСЛОВНЫЕ исходники из server.py ────────────────────────────────────────────────────────
_tree = ast.parse(SRC)
FUNCS = ("_reported_material_norm", "_norm_hex_color", "_apply_vt_tray", "_bambu_ext_slots",
         "_3mf_req_from_project_settings", "_3mf_req_from_slice_info", "_3mf_filament_requirements",
         "_bambu_ams_mapping", "_tray_remain", "_ams_low_pct", "_bambu_auto_slot_map",
         #  16.10.2026 (R-006): сопла филаментов H2D из файла — помощник плиты, его зовут подбор
         #  запуска и сведения очереди о файле; без него обе падали бы в песочнице NameError.
         "_3mf_filament_sides", "_3mf_side_values",
         #  16.10.2026 (R-138): занятость по стадии — одно правило с запуском. Без этих функций
         #  _send_working_stage в песочнице падал бы NameError и молча отвечал «не занят».
         "_bambu_stage_busy", "_bambu_stage_base_of",
         #  16.10.2026 (R-138, проверка пакета): строка очереди называет, чем занят Bambu, словами запуска.
         "_qw_busy_words", "_bambu_busy_reason", "_bambu_stage_text",
         "_send_working_stage", "_send_printer_status", "_file_type_class", "_compatible_pids_for",
         "_qw_printer_name", "_qw_row", "_qw_blank_info", "_3mf_plate_used", "_qw_3mf_info",
         "_qw_gcode_info", "_qw_file_info", "_qw_mats", "_qw_ctx", "_qw_busy_verdict",
         "_qw_printer_feed", "_qw_feed", "_qw_auto_slot_mirror", "_qw_bambu_ams_proof",
         "_qw_bambu_verdict", "_qw_klipper_verdict", "_qw_material_verdict", "_qw_compatible",
         "_qw_match", "_qw_public", "_qw_finish", "_qw_launch_outcome",
         #  собственно автозапуск и общий путь запуска
         "_qw_launch_claimed", "_qw_auto_enabled", "_qw_auto_mark", "_qw_auto_bump", "_qw_auto_ok",
         "_qw_auto_gap", "_qw_auto_tick",
         #  16.10.2026 (R-016, R-118, R-141, R-008): подробность подачи по слотам, правило «автомат или
         #  человек», FlashForge, элемент очереди и проверка склада ДО траты жетона — НАСТОЯЩАЯ
         #  _enqueue_preflight (хуки модулей подменены ниже).
         "_qw_ams_label", "_qw_slot_detail", "_qw_flashforge_verdict", "_qw_auto_needs_human",
         "_qw_item", "_qw_auto_note", "_qw_auto_stock", "_enqueue_preflight", "_enqueue_item_bytes",
         #  R-118: снимок безопасности и сторож жетонов — настоящие, для проверок отмены и «Стоп».
         "_printer_transport", "_user_stop_active", "_get_printer_safety_snapshot", "_orch_clearance_watchdog",
         #  чтение списка принтеров автозапуска — настоящее, из таблицы настроек
         "_farm_auto_start_validate", "_farm_auto_start_read")
CONSTS = {"_REPORT_EMPTY_MAT", "_BAMBU_EXT_MAIN", "_REQ_PROJECT_SETTINGS", "_REQ_SLICE_INFO",
          "_ACTIVE_RAW", "_QW_FILE_CACHE_MAX", "_QW_GCODE_HEAD", "_QW_GCODE_TAIL", "_QW_CAND_MAX",
          "_QW_PLATE_RE", "_qw_file_cache", "_qw_file_lock", "_QW_MISMATCH", "_QW_UNFIT", "_QW_VERDICT_ORDER",
          "_QW_BED_RAW", "_QW_SENT_NOT_STARTED", "_QW_AUTO_TICK", "_QW_AUTO_FAILS_MAX",
          "_qw_auto_fails", "_qw_auto_inflight", "_qw_auto_last", "_FARM_AUTO_START_KEY", "_AUTO_START_MAX", "_AUTO_START_ID_MAX",
          "_bambu_stage_base", "_BAMBU_STAGE_BASE_TTL", "_BAMBU_ACTIVE_RAW",
          "_QW_AUTO_STOCK_RETRY_S", "_qw_auto_stock_low", "_SAFE_RAW_IDLE", "_USER_STOP_GRACE_S"}
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
check("1. исходники подбора и автозапуска извлечены из server.py",
      all(n in _fn_src for n in FUNCS), sorted(set(FUNCS) - set(_fn_src)))

# ── временные базы и стабы ──────────────────────────────────────────────────────────────────
_tmp = tempfile.mkdtemp(prefix="qwauto1609_")
conn = sqlite3.connect(os.path.join(_tmp, "printers.db"), check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("CREATE TABLE printers (id TEXT PRIMARY KEY, name TEXT, type TEXT, model TEXT, "
             "ip TEXT DEFAULT '10.0.0.99', token TEXT DEFAULT 'FIXTURE_TOKEN', "
             "queue_allowed INTEGER DEFAULT 0)")
#  ВАЖНО: колонка printer_id здесь обязана быть — по ней автозапуск считает принтер занятым,
#  если у него осталась неразобранная строка запуска. Без колонки правило молча не проверялось бы.
conn.execute("CREATE TABLE print_launch_queue (id TEXT PRIMARY KEY, printer_id TEXT DEFAULT '', "
             "status TEXT DEFAULT 'pending', payload TEXT DEFAULT '{}', updated_at REAL DEFAULT 0, "
             "last_error TEXT DEFAULT '')")
conn.execute("CREATE TABLE queue_wait (id TEXT PRIMARY KEY, gcode_file TEXT NOT NULL, "
             "source TEXT DEFAULT 'quick', part_name TEXT DEFAULT '', material TEXT DEFAULT '', "
             "state TEXT DEFAULT 'waiting', note TEXT DEFAULT '', created_at REAL DEFAULT 0, "
             "updated_at REAL DEFAULT 0)")
conn.commit()

#  Настройки фермы — НАСТОЯЩАЯ таблица: выключатель автозапуска читается прямо из неё.
conn_p = sqlite3.connect(os.path.join(_tmp, "parts.db"), check_same_thread=False)
conn_p.row_factory = sqlite3.Row
conn_p.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT DEFAULT '')")
conn_p.commit()

#  Настоящий модуль жетонов на своей временной базе: правила подтверждения проверяем на настоящем
#  коде. Снимок безопасности отдаём свой — им пользуется create_clearance.
_orch_conn = sqlite3.connect(os.path.join(_tmp, "orch.db"), check_same_thread=False)
_orch_conn.row_factory = sqlite3.Row
SAFE = {}


def _safety(pid):
    st = SAFE.get(pid) or {}
    return {"printer_id": pid, "transport": "bambu", "status": st.get("status", "IDLE"),
            "status_raw": st.get("status_raw", st.get("status", "IDLE")),
            "fresh": st.get("fresh", True), "user_stopped_pending": False,
            "printing_active": st.get("printing_active", False),
            "safe_idle": st.get("safe_idle", True), "unsafe_reason": ""}


_orch.init(_orch_conn, threading.RLock(), lambda p: p + uuid.uuid4().hex[:8], "boot_auto",
           printer_status_fn=lambda pid: (SAFE.get(pid, {}).get("status", "IDLE"), True),
           safety_fn=_safety, printers_fn=lambda: [], send_reserved_fn=lambda: set(),
           file_ok_fn=lambda f: True, file_requirements_fn=lambda fr: {},
           filament_snapshot_fn=lambda pid: {}, reported_filament_fn=lambda pid: {})
_orch.init_db()


class _Log:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _SendMgr:
    def __init__(self):
        self.reserved, self.holds = set(), {}

    def reserved_ids(self):
        return set(self.reserved)

    def get_hold(self, pid):
        return self.holds.get(pid)

    def cancel_reserved(self, sjid, why=""):
        self.reserved.discard(sjid)
        return True


FILES, ENQ = {}, []
ENQ_OK = [True]
_seq = [0]


def _uid(prefix):
    _seq[0] += 1
    return "%s%d" % (prefix, _seq[0])


def _pf_printer_row(pid):
    return conn.execute("SELECT * FROM printers WHERE id=?", (pid,)).fetchone()


def _enqueue(data):
    """Подменённая очередь запусков: НИЧЕГО не отправляет, только записывает и отвечает."""
    items = list((data or {}).get("items") or [])
    if not ENQ_OK[0]:
        return {"status": "ok", "queued": [], "held": [it["printer_id"] for it in items],
                "blocked": [], "notes": ["printer_held"]}
    ENQ.extend(items)
    return {"status": "ok", "queued": [it["printer_id"] for it in items], "held": [],
            "blocked": [], "notes": []}


#  16.10.2026 (R-008): хук склада подменён — НАСТОЯЩАЯ _enqueue_preflight зовёт его так же, как при
#  постановке в очередь. STOCK_BLOCK[0] — ответ склада (None — пропускает), HOOK_CALLS — кого спросили.
STOCK_BLOCK = [None]
STOCK_BLOCK_BY = {}          # принтер -> свой ответ склада (разбор пакета: склад против только на одном)
HOOK_CALLS = []


def _hooks_stub(pid, fdata, ams_slot, fname, advice_out=None, plan=None):
    HOOK_CALLS.append((pid, fname))
    return STOCK_BLOCK_BY.get(pid, STOCK_BLOCK[0])


USER_STOPPED = {}
from app import printer_state_policy as _state_policy   # noqa: E402 — причины небезопасного состояния
STALE_FAIL_S = 60.0
NS = {"log": _Log(), "conn_pr": conn, "lock_pr": threading.RLock(),
      "_run_pre_print_hooks": _hooks_stub, "_launch_feed_plan": lambda *a, **k: {},
      "_user_stopped": USER_STOPPED, "_state_policy": _state_policy,
      "conn_p": conn_p, "lock_p": threading.RLock(),
      "print_queue": [], "print_queue_lock": threading.RLock(), "p_states": {},
      "_send_mgr": _SendMgr(), "_exc_brief": lambda: "test", "last_seen": {},
      "STALE_FAIL_S": STALE_FAIL_S, "time": time, "os": os, "io": io, "re": re, "json": json,
      "zipfile": zipfile, "ET": ET, "threading": threading, "Dict": Dict, "Any": Any,
      "_orch": _orch, "_bstart": _bstart, "_gts": _gts, "detect_target": detect_target,
      "_bslot": __import__("app.bambu_slot_match", fromlist=["x"]),      # 16.10.2026: одна раскладка
      "_bams": __import__("app.bambu_ams_state", fromlist=["x"]),        # 16.10.2026: состояние AMS
      "_models_compatible": _models_compatible, "_BAMBU_CODES": _BAMBU_CODES,
      "_normalize_model": _normalize_model, "_is_3mf_printable": is_3mf_printable,
      #  Порог остатка — единственное, что берётся из общего чтения настроек.
      "_farm_settings_read": lambda: {"low_pct": 15}, "_printer_model_code": lambda pid: None,
      "_staging_path": lambda fname, part=None: FILES.get(os.path.basename(fname or "")),
      "_uid": _uid, "_pf_printer_row": _pf_printer_row, "api_print_queue_enqueue": _enqueue,
      "_plq_set_status": lambda *a, **k: None, "_print_queue_public": lambda: [],
      "_jsonmod": json}
for s in _const_src:
    exec(s, NS)                          # noqa: S102 — свой же исходник в песочнице
for n in FUNCS:
    if n in _fn_src:
        exec(_fn_src[n], NS)             # noqa: S102
M = NS


def _farm_set(on, pids, stagger=None):
    """Выключатель, список и интервал — в НАСТОЯЩУЮ таблицу настроек, как их пишет сервер.
    stagger=None — интервал поэтапного запуска ВЫКЛЮЧЕН (и это сбрасывается между сценариями)."""
    with NS["lock_p"]:
        conn_p.execute("INSERT INTO app_settings (key, value) VALUES ('farm_queue_auto_start', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("1" if on else "0",))
        conn_p.execute("INSERT INTO app_settings (key, value) VALUES ('farm_auto_start_printers', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (json.dumps(list(pids)),))
        conn_p.execute("INSERT INTO app_settings (key, value) VALUES ('farm_stagger_on', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ("1" if stagger else "0",))
        conn_p.execute("INSERT INTO app_settings (key, value) VALUES ('farm_stagger_sec', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (str(int(stagger or 0)),))
        conn_p.commit()


def _reset(auto_on=True, auto_pids=("p1",)):
    conn.execute("DELETE FROM printers")
    conn.execute("DELETE FROM queue_wait")
    conn.execute("DELETE FROM print_launch_queue")
    conn.commit()
    _orch_conn.execute("DELETE FROM plate_clearances")
    _orch_conn.commit()
    NS["p_states"].clear()
    NS["last_seen"].clear()
    NS["print_queue"][:] = []
    NS["_qw_file_cache"].clear()
    NS["_qw_auto_fails"].clear()
    NS["_qw_auto_inflight"].clear()
    NS["_qw_auto_last"][0] = 0.0
    NS["_qw_auto_stock_low"].clear()
    SAFE.clear()
    ENQ[:] = []
    ENQ_OK[0] = True
    STOCK_BLOCK[0] = None
    STOCK_BLOCK_BY.clear()
    HOOK_CALLS[:] = []
    USER_STOPPED.clear()
    _farm_set(auto_on, auto_pids)


def printer(pid, name="X1C-01", allowed=True, status="IDLE", ams=("PLA",), raw=None):
    """16.10.2026: лоток AMS подтверждён датчиком подачи (present=True) — так, как его разбирает
    app/bambu_ams_state по tray_exist_bits настоящего отчёта; автозапуск без датчика не идёт (R-118)."""
    conn.execute("INSERT OR REPLACE INTO printers (id, name, type, model, queue_allowed) "
                 "VALUES (?,?,?,?,?)", (pid, name, "bambu", "P1S", 1 if allowed else 0))
    conn.commit()
    st = {"status": status, "status_raw": status if raw is None else raw,
          "ams_trays": [{"index": i, "type": m, "color": "#FFFFFF", "color_raw": "FFFFFFFF",
                         "remain": -1, "present": True} for i, m in enumerate(ams)]}
    NS["p_states"][pid] = st
    NS["last_seen"][pid] = time.time()
    SAFE[pid] = {"status": status, "status_raw": status if raw is None else raw,
                 "printing_active": status in ("RUNNING", "PREPARE"),
                 "safe_idle": status == "IDLE"}


def mk3mf(name, types, plates):
    path = os.path.join(_tmp, name)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps({
            "filament_type": types, "filament_colour": ["#FFFFFF"] * len(types),
            "filament_settings_id": ["fixture"] * len(types), "printer_model": "Bambu Lab P1S",
            "nozzle_diameter": ["0.4"]}))
        x = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
        for no, fl in plates.items():
            x.append("  <plate>")
            x.append('    <metadata key="index" value="%d"/>' % no)
            for fid, ftype in fl:
                x.append('    <filament id="%d" type="%s" color="#FFFFFF" used_m="1.00" '
                         'used_g="3.00"/>' % (fid, ftype))
            x.append("  </plate>")
        x.append("</config>")
        z.writestr("Metadata/slice_info.config", "\n".join(x))
        z.writestr("Metadata/plate_1.gcode", "; HEADER_BLOCK_START\nG28\n")
        z.writestr("3D/3dmodel.model", "<model/>")
    FILES[name] = path
    return path


def add_row(rid, fname="pla.gcode.3mf", state="waiting"):
    conn.execute("INSERT INTO queue_wait (id, gcode_file, source, part_name, material, state, "
                 "note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (rid, fname, "quick", "", "PLA", state, "", time.time(), time.time()))
    conn.commit()


def row_state(rid):
    r = conn.execute("SELECT state, note FROM queue_wait WHERE id=?", (rid,)).fetchone()
    return (r["state"], r["note"]) if r else (None, None)


def give_clearance(pid, finished=False):
    """Человек нажал «Стол очищен» — через НАСТОЯЩИЙ код ядра, тем же видом подтверждения,
    который выбрал бы маршрут: закончил печать -> постпечатный, в покое -> первичный."""
    return _orch.create_clearance(pid, confirmed=True, confirmed_by="tester", post_print=finished,
                                  finished_raw=NS["_QW_BED_RAW"].get("bambu", ()))


mk3mf("pla.gcode.3mf", ["PLA"], {1: [(1, "PLA")]})

# ══ 1. Выключено по умолчанию ═══════════════════════════════════════════════════════════════
print("--- 1. пока владелец не разрешил, автомат не делает ничего ---")
_reset(auto_on=False)
printer("p1")
give_clearance("p1")
add_row("r1")
M["_qw_auto_tick"]()
check("2. выключатель фермы выключен — ни одного запуска, строка не тронута",
      ENQ == [] and row_state("r1")[0] == "waiting", (ENQ, row_state("r1")))

_reset(auto_on=True, auto_pids=())
printer("p1")
give_clearance("p1")
add_row("r1")
M["_qw_auto_tick"]()
check("3. включён, но список принтеров пуст — «никому», запусков нет",
      ENQ == [] and row_state("r1")[0] == "waiting", (ENQ, row_state("r1")))

_reset(auto_on=True, auto_pids=("p1",))
printer("p1", allowed=False)
give_clearance("p1")
add_row("r1")
M["_qw_auto_tick"]()
check("4. разрешение двойное: без отметки «запуск из очереди» автомат принтер не берёт",
      ENQ == [] and row_state("r1")[0] == "waiting", (ENQ, row_state("r1")))

# ══ 2. Стол: подтверждение нужно ВСЕГДА ═════════════════════════════════════════════════════
print("--- 2. пустой стол доказывает только человек ---")
_reset()
printer("p1")                      # принтер В ПОКОЕ, программа печати на нём не видела
add_row("r1")
M["_qw_auto_tick"]()
check("5. КОРЕНЬ ЗАДАЧИ: принтер в ПОКОЕ без подтверждения НЕ запускается "
      "(на столе может лежать деталь, которую программа не печатала)",
      ENQ == [] and row_state("r1")[0] == "waiting", (ENQ, row_state("r1")))

_reset()
printer("p1")
add_row("r1")
_c1 = give_clearance("p1")
check("6. принтер в покое подтверждается ПЕРВИЧНЫМ видом (safe_idle)", _c1.get("status") == "ok", _c1)
M["_qw_auto_tick"]()
check("7. с подтверждением запуск ушёл РОВНО один раз",
      len(ENQ) == 1 and ENQ[0]["printer_id"] == "p1" and ENQ[0].get("qw_id") == "r1", ENQ)
check("8. строка помечена «запускается», а не исчезла",
      row_state("r1")[0] == "launching", row_state("r1"))
check("9. подтверждение ПОТРАЧЕНО: живого жетона у принтера больше нет",
      _orch.active_clearance("p1") is None, _orch.active_clearance("p1"))

_reset()
printer("p1", status="FINISH")
add_row("r1")
M["_qw_auto_tick"]()
check("10. закончивший печать принтер без подтверждения тоже НЕ запускается",
      ENQ == [] and row_state("r1")[0] == "waiting", (ENQ, row_state("r1")))

_reset()
printer("p1", status="FINISH")
add_row("r1")
_c2 = give_clearance("p1", finished=True)
check("11. у закончившего принтера подтверждение принимается без safe_idle",
      _c2.get("status") == "ok", _c2)
M["_qw_auto_tick"]()
check("12. и запуск уходит", len(ENQ) == 1 and ENQ[0]["printer_id"] == "p1", ENQ)

add_row("r2")
conn.execute("UPDATE queue_wait SET state='waiting' WHERE id='r1'")
conn.commit()
NS["print_queue"][:] = []
M["_qw_auto_tick"]()
check("13. вторая печать на тот же стол без нового подтверждения НЕ уходит", len(ENQ) == 1, ENQ)

_reset()
printer("p1", status="RUNNING")
_bad = give_clearance("p1", finished=True)
check("14. на ПЕЧАТАЮЩЕМ принтере подтверждение не принимается вовсе",
      _bad.get("status") == "error" and _bad.get("reason") == "printer_busy", _bad)

_reset()
printer("p1", status="IDLE")
SAFE["p1"] = {"status": "IDLE", "status_raw": "IDLE", "printing_active": False, "safe_idle": False}
_bad2 = give_clearance("p1", finished=True)
check("15. «после печати» — не лазейка: принтер не в покое и не закончил -> отказ с причиной",
      _bad2.get("status") == "error" and _bad2.get("reason") == "printer_not_finished", _bad2)

# ══ 3. Границы автомата ═════════════════════════════════════════════════════════════════════
print("--- 3. чего автомат не трогает ---")
_reset()
printer("p1")
give_clearance("p1")
add_row("r1", state="attention")
M["_qw_auto_tick"]()
check("16. строку «требует внимания» автомат не берёт — её исход решает человек",
      ENQ == [] and row_state("r1")[0] == "attention", (ENQ, row_state("r1")))

_reset()
printer("p1")
give_clearance("p1")
add_row("r1")
conn.execute("INSERT INTO print_launch_queue (id, printer_id, status) VALUES ('d1','p9','recovery_hold')")
conn.commit()
M["_qw_auto_tick"]()
check("17. пока не разобраны прерванные перезапуском запуски — автомат молчит ЦЕЛИКОМ",
      ENQ == [], ENQ)

_reset()
printer("p1")
give_clearance("p1")
add_row("r1")
conn.execute("INSERT INTO print_launch_queue (id, printer_id, status) VALUES ('d2','p1','pending')")
conn.commit()
M["_qw_auto_tick"]()
check("18. принтер с незакрытой строкой запуска считается занятым",
      ENQ == [] and row_state("r1")[0] == "waiting", (ENQ, row_state("r1")))

_reset()
printer("p1")
printer("p2", name="X1C-02")
_farm_set(True, ["p1", "p2"])
give_clearance("p1")
give_clearance("p2")
add_row("r1")
add_row("r2")
M["_qw_auto_tick"]()
check("19. за один проход уходит НЕ БОЛЬШЕ одного запуска", len(ENQ) == 1, ENQ)

# ══ 4. Строка не застревает ═════════════════════════════════════════════════════════════════
print("--- 4. что бы ни случилось, строка возвращается владельцу ---")
_reset()
printer("p1")
give_clearance("p1")
add_row("r1")
_real_launch = M["_qw_launch_claimed"]


def _boom(*a, **k):
    raise RuntimeError("сбой базы посреди запуска")


M["_qw_launch_claimed"] = _boom
M["_qw_auto_tick"]()
M["_qw_launch_claimed"] = _real_launch
check("20. исключение внутри запуска возвращает строку в ожидание, а не оставляет её занятой",
      row_state("r1")[0] == "waiting" and ENQ == [], (row_state("r1"), ENQ))

# ══ 5. Неудачи подряд ═══════════════════════════════════════════════════════════════════════
print("--- 5. когда запуск раз за разом не удаётся ---")
_reset()
printer("p1")
add_row("r1")
ENQ_OK[0] = False
for _ in range(3):
    conn.execute("UPDATE queue_wait SET state='waiting' WHERE id='r1'")
    conn.commit()
    _orch_conn.execute("DELETE FROM plate_clearances")
    _orch_conn.commit()
    give_clearance("p1")
    M["_qw_auto_tick"]()
_st, _note = row_state("r1")
check("21. три неудачи подряд — строка «требует внимания», а не молчаливая долбёжка",
      _st == "attention", (_st, _note))
check("22. причина хранится КОДОМ (её показывают на двух языках), а не русской фразой",
      str(_note or "").startswith("auto_failed:"), _note)
check("23. и ни одной печати при этом не ушло", ENQ == [], ENQ)

# ══ 6. НЕ ВАКУУМ ════════════════════════════════════════════════════════════════════════════
print("--- 6. проверка меряет разницу, а не саму себя ---")
_reset(auto_on=False)
printer("p1", status="FINISH")
add_row("r1")
give_clearance("p1", finished=True)
M["_qw_auto_tick"]()
_off = list(ENQ)
_reset()
printer("p1", status="FINISH")
add_row("r1")
give_clearance("p1", finished=True)
M["_qw_auto_tick"]()
check("24. НЕ ВАКУУМ: те же данные при выключенном выключателе дают 0 запусков, при включённом — 1",
      _off == [] and len(ENQ) == 1, (_off, ENQ))

# ══ 7. Интервал поэтапного запуска ══════════════════════════════════════════════════════════
print("--- 7. автозапуск выдерживает интервал, заданный владельцем ---")
_reset()
_farm_set(True, ["p1"], stagger=90)
printer("p1")
give_clearance("p1")
add_row("r1")
M["_qw_auto_tick"]()
check("25. первый запуск уходит", len(ENQ) == 1, ENQ)
add_row("r2")
give_clearance("p1")                      # стол подтвердили снова
M["_qw_auto_tick"]()
check("26. второй запуск В ПРЕДЕЛАХ интервала не уходит", len(ENQ) == 1, ENQ)
NS["_qw_auto_last"][0] = time.time() - 120
M["_qw_auto_tick"]()
check("27. когда интервал прошёл — запуск уходит", len(ENQ) == 2, ENQ)

_reset()
printer("p1")
give_clearance("p1")
add_row("r1")
M["_qw_auto_tick"]()
_clr_row = _orch_conn.execute("SELECT consumed_by_item_id AS v FROM plate_clearances "
                              "WHERE consumed_at IS NOT NULL").fetchone()
check("28. потраченный жетон помечен как расход ОЧЕРЕДИ, а не проектной детали",
      _clr_row is not None and str(_clr_row["v"] or "").startswith("qw:"),
      dict(_clr_row) if _clr_row else None)

# ══ 8. Двухсопельный без сопел в файле — только ручной запуск (16.10.2026, R-115) ════════════
print("--- 8. двухсопельный принтер, а в файле не видно сопла: автомат не запускает ---")
def _mk_h2d(name, maps):
    """Файл под H2D (два сопла) по устройству Bambu Studio; maps — filament_maps плиты или None."""
    path = os.path.join(_tmp, name)
    si = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>", "  <plate>", '    <metadata key="index" value="1"/>']
    if maps:
        si.append('    <metadata key="filament_maps" value="%s"/>' % maps)
    si += ['    <filament id="1" type="PLA" color="#FFFFFF" used_m="1.00" used_g="3.00"/>', "  </plate>", "</config>"]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps({
            "filament_type": ["PLA"], "filament_colour": ["#FFFFFF"], "filament_settings_id": ["fixture"],
            "printer_model": "Bambu Lab H2D", "nozzle_diameter": ["0.4", "0.4"]}))
        z.writestr("Metadata/slice_info.config", "\n".join(si))
        z.writestr("Metadata/plate_1.gcode", "; HEADER_BLOCK_START\nG28\n")
        z.writestr("3D/3dmodel.model", "<model/>")
    FILES[name] = path


_mk_h2d("pla_h2d_noside.gcode.3mf", None)
_mk_h2d("pla_h2d_right.gcode.3mf", "2")
_reset()
printer("p1")
conn.execute("UPDATE printers SET model='H2D' WHERE id='p1'")
conn.commit()
NS["p_states"]["p1"]["nozzle_count"] = 2
give_clearance("p1")
add_row("r_h2d", fname="pla_h2d_noside.gcode.3mf")
M["_qw_auto_tick"]()
check("29. H2D, PLA в AMS, сопла в файле нет — автозапуск НЕ уходит, строка ждёт человека, жетон не потрачен",
      ENQ == [] and row_state("r_h2d")[0] == "waiting" and _orch.active_clearance("p1"), (ENQ, row_state("r_h2d")))
conn.execute("DELETE FROM queue_wait")
conn.commit()
add_row("r_h2d2", fname="pla_h2d_right.gcode.3mf")
M["_qw_auto_tick"]()
check("30. НЕ ВАКУУМ: тот же H2D и файл, где сопло указано, — автозапуск уходит", len(ENQ) == 1, (ENQ, row_state("r_h2d2")))

#  R-138: после отмены прошивка держит стадию (FAILED, 54, print_type idle) — автомат не считает принтер занятым.
_reset()
printer("p1", status="IDLE", raw="FAILED")
NS["p_states"]["p1"].update({"stage": 54, "print_type": "idle"})
SAFE["p1"]["status_raw"] = "FAILED"
give_clearance("p1", finished=True)
add_row("r_canc")
M["_qw_auto_tick"]()
check("31. (R-138) после отмены (FAILED, стадия 54, print_type idle) и подтверждения стола автозапуск уходит",
      len(ENQ) == 1, (ENQ, row_state("r_canc")))

#  16.10.2026 (проверка пакета R-138): оператор грузит филамент с экрана — сырой IDLE, стадия 24, print_type idle.
#  Это работа (ha-bambulab PR #2168 такие стадии не трогает). Прежняя редакция считала принтер свободным, и
#  автомат слал команду, на которую принтер отвечает 0500-4004.
_reset()
printer("p1", status="IDLE", raw="IDLE")
NS["p_states"]["p1"].update({"stage": 24, "print_type": "idle"})
give_clearance("p1", finished=False)
add_row("r_load")
M["_qw_auto_tick"]()
check("32а. загрузка филамента с экрана (IDLE, стадия 24, print_type idle) — автозапуск НЕ уходит, строка ждёт",
      ENQ == [] and row_state("r_load")[0] == "waiting", (ENQ, row_state("r_load")))

# ══ 9. Выбор только среди подтверждённых (16.10.2026, R-118) ════════════════════════════════
print("--- 9. автомат выбирает только среди принтеров с подтверждённым столом ---")
_reset()
_farm_set(True, ["p1", "p2"])
printer("p1", name="X1C-01")                      # свободен, разрешён, но стол НЕ подтверждён
printer("p2", name="X1C-02")
give_clearance("p2")
add_row("r1")
M["_qw_auto_tick"]()
check("32. (R-118) p1 свободен без подтверждения, p2 подтверждён — печать уходит на p2 (раньше не уходила никуда)",
      len(ENQ) == 1 and ENQ[0]["printer_id"] == "p2" and _orch.active_clearance("p2") is None, ENQ)
_reset()
_farm_set(True, ["p1"])
printer("p1")
printer("p2", name="X1C-02")                       # подтверждён, но автозапуск ему не разрешён
give_clearance("p2")
add_row("r1")
_real_match = M["_qw_match"]
_calls = []
M["_qw_match"] = lambda *a, **k: (_calls.append(1), _real_match(*a, **k))[1]
M["_qw_auto_tick"]()
M["_qw_match"] = _real_match
check("33. (R-118) подтверждённых среди разрешённых автомату нет — проход заканчивается, не читая файлов",
      ENQ == [] and _calls == [], (ENQ, _calls))

# ══ 10. Только доказанная подача и точный цвет (R-118, R-115, R-141) ═════════════════════════
print("--- 10. автомат берёт только доказанную подачу и точный цвет; иначе строка ждёт человека ---")
_reset()
printer("p1")
NS["p_states"]["p1"]["ams_trays"][0]["color_raw"] = "FF0000FF"     # в слоте красный, в файле белый
give_clearance("p1")
add_row("r1")
M["_qw_auto_tick"]()
check("34. (R-118) цвет в слоте не тот — автозапуска нет, жетон цел, в строке причина кодом",
      ENQ == [] and _orch.active_clearance("p1") is not None
      and row_state("r1") == ("waiting", "auto_needs_human:color_mismatch"), (ENQ, row_state("r1")))
_reset()
printer("p1", ams=())
NS["p_states"]["p1"]["ext_trays"] = {"255": {"tray_id": "255", "tray_type": "PLA", "tray_color": "FFFFFFFF"}}
give_clearance("p1")
add_row("r1")
M["_qw_auto_tick"]()
check("35. (R-118) PLA только на внешней катушке (материал «по настройке») — ждёт ручного запуска",
      ENQ == [] and row_state("r1") == ("waiting", "auto_needs_human:external"), (ENQ, row_state("r1")))
_reset()
printer("p1")
NS["p_states"]["p1"]["ams_trays"][0].pop("present", None)          # датчик подачи лотка не сообщал
give_clearance("p1")
add_row("r1")
M["_qw_auto_tick"]()
check("36. (R-118) слот не подтверждён датчиком подачи — автомат не берёт",
      ENQ == [] and row_state("r1") == ("waiting", "auto_needs_human:no_sensor"), (ENQ, row_state("r1")))
_reset()
conn.execute("INSERT INTO printers (id, name, type, model, queue_allowed) VALUES ('ff','AD5M-02','flashforge','',1)")
conn.commit()
NS["p_states"]["ff"] = {"status": "IDLE", "status_raw": "ready"}
NS["last_seen"]["ff"] = time.time()
SAFE["ff"] = {"status": "IDLE", "status_raw": "ready", "safe_idle": True}
_farm_set(True, ["ff"])
give_clearance("ff")
mk3mf("pla_any.gcode.3mf", ["PLA"], {1: [(1, "PLA")]})
with zipfile.ZipFile(FILES["pla_any.gcode.3mf"]) as _zr:
    _parts = {n: _zr.read(n) for n in _zr.namelist()}
_ps = json.loads(_parts["Metadata/project_settings.config"].decode("utf-8"))
_ps["printer_model"] = ""
_parts["Metadata/project_settings.config"] = json.dumps(_ps).encode("utf-8")
with zipfile.ZipFile(FILES["pla_any.gcode.3mf"], "w") as _zw:
    for _n, _d in _parts.items():
        _zw.writestr(_n, _d)
add_row("r1", fname="pla_any.gcode.3mf")
M["_qw_auto_tick"]()
check("37. (R-141) FlashForge: материал проверяет человек — автозапуск его не берёт никогда",
      ENQ == [] and row_state("r1") == ("waiting", "auto_needs_human:owner_check"), (ENQ, row_state("r1")))
_reset()
_farm_set(True, ["p1", "p2"])
printer("p1", name="X1C-01")
NS["p_states"]["p1"]["ams_trays"][0]["color_raw"] = "FF0000FF"     # подходит по материалу, цвет не тот
printer("p2", name="X1C-02", status="FINISH")                      # цвет точный, но стоит в списке позже
give_clearance("p1")
give_clearance("p2", finished=True)
add_row("r1")
M["_qw_auto_tick"]()
check("38. (R-118) первый подтверждённый не годится автомату по цвету — печать уходит на второй, где цвет точный",
      len(ENQ) == 1 and ENQ[0]["printer_id"] == "p2" and _orch.active_clearance("p1") is not None, ENQ)

# ══ 11. Склад — до траты жетона (16.10.2026, R-008) ════════════════════════════════════════
print("--- 11. склад не пропускает — жетон «Стол очищен» не тратится ---")
_reset()
printer("p1")
give_clearance("p1")
add_row("r1")
STOCK_BLOCK[0] = {"status": "low_filament", "shortfall": [{"material": "PLA", "needed": 40, "available": 5}]}
M["_qw_auto_tick"]()
check("39. (R-008) склад сказал «не хватает» — запуска нет, жетон ЖИВ, строка ждёт с пометкой auto_low_filament",
      ENQ == [] and _orch.active_clearance("p1") is not None
      and row_state("r1") == ("waiting", "auto_low_filament") and len(HOOK_CALLS) == 1, (ENQ, row_state("r1"), HOOK_CALLS))
M["_qw_auto_tick"]()
check("40. повторный проход сразу же склад не дёргает (пауза между вопросами), жетон по-прежнему цел",
      len(HOOK_CALLS) == 1 and ENQ == [] and _orch.active_clearance("p1") is not None, HOOK_CALLS)
STOCK_BLOCK[0] = None
NS["_qw_auto_stock_low"].clear()                   # пауза прошла, катушку поставили
M["_qw_auto_tick"]()
check("41. склад пропускает — запуск уходит и тратит жетон",
      len(ENQ) == 1 and _orch.active_clearance("p1") is None, (ENQ, row_state("r1")))

#  Разбор пакета 16.10.2026: склад был спрошен только у ВЫБРАННОГО принтера. Подбор детерминирован —
#  p1 выигрывал каждый проход, и подтверждённый p2 с полной катушкой печать не получал никогда.
_reset()
_farm_set(True, ["p1", "p2"])
printer("p1", name="X1C-01")
printer("p2", name="X1C-02")
give_clearance("p1")
give_clearance("p2")
add_row("r1")
STOCK_BLOCK_BY["p1"] = {"status": "low_filament", "shortfall": [{"material": "PLA", "needed": 40, "available": 5}]}
for _ in range(3):
    M["_qw_auto_tick"]()
check("41b. (R-008) два подтверждённых принтера, склад против только на первом — печать уходит на второй, "
      "жетон первого цел",
      len(ENQ) == 1 and ENQ[0]["printer_id"] == "p2" and _orch.active_clearance("p1") is not None
      and _orch.active_clearance("p2") is None and ("p2", "pla.gcode.3mf") in HOOK_CALLS,
      (ENQ, row_state("r1"), HOOK_CALLS))
#  Разбор пакета: в паузе между вопросами к складу — та же причина, что дал склад, а не «не хватает».
_reset()
printer("p1")
give_clearance("p1")
add_row("r1")
STOCK_BLOCK[0] = {"status": "spool_unbound"}
M["_qw_auto_tick"]()
_n1 = row_state("r1")
M["_qw_auto_tick"]()
_n2 = row_state("r1")
check("41c. склад отказал не нехваткой — пометка «нужно ваше решение (склад)» и на первом, и на втором проходе "
      "(в паузе не превращается в «не хватает материала»)",
      _n1 == ("waiting", "auto_needs_human:stock") and _n2 == ("waiting", "auto_needs_human:stock")
      and len(HOOK_CALLS) == 1 and ENQ == [], (_n1, _n2, HOOK_CALLS))

# ══ 12. Подтверждение после отмены и после «Стоп» — НАСТОЯЩИЕ снимок и сторож (R-118) ═══════
print("--- 12. «Стол очищен» после отмены и после «Стоп»: настоящий снимок безопасности и сторож ---")
_orch_conn2 = sqlite3.connect(os.path.join(_tmp, "orch2.db"), check_same_thread=False)
_orch_conn2.row_factory = sqlite3.Row
_orch.init(_orch_conn2, threading.RLock(), lambda p: p + uuid.uuid4().hex[:8], "boot_auto2",
           printer_status_fn=lambda pid: (str((NS["p_states"].get(pid) or {}).get("status") or ""), True),
           safety_fn=NS["_get_printer_safety_snapshot"], printers_fn=lambda: [], send_reserved_fn=lambda: set(),
           file_ok_fn=lambda f: True, file_requirements_fn=lambda fr: {},
           filament_snapshot_fn=lambda pid: {}, reported_filament_fn=lambda pid: {})
_orch.init_db()


def _route_clear(pid):
    """Как маршрут «Стол очищен»: вид подтверждения по сырому статусу (закончил — после печати)."""
    _raw = NS["_QW_BED_RAW"].get("bambu", ())
    _st = NS["p_states"].get(pid) or {}
    _fin = str(_st.get("status") or "").upper() == "FINISH" or str(_st.get("status_raw") or "") in _raw
    return _orch.create_clearance(pid, confirmed=True, confirmed_by="tester", post_print=_fin, finished_raw=_raw)


_reset()
printer("b1", status="IDLE", raw="FAILED")         # отмена Bambu: карточка IDLE (маска), прошивка FAILED
NS["p_states"]["b1"].update({"stage": 255, "print_type": "idle"})
_c = _route_clear("b1")
for _ in range(3):
    NS["_orch_clearance_watchdog"]()
check("42. (R-118) Bambu после отмены: подтверждение принято и ДЕРЖИТСЯ после трёх проходов сторожа",
      _c.get("status") == "ok" and _orch.active_clearance("b1") is not None, (_c, _orch.active_clearance("b1")))
_reset()
printer("b2", status="IDLE", raw="IDLE")           # подтверждён в чистом покое…
_c2 = _route_clear("b2")
NS["p_states"]["b2"]["status_raw"] = "FAILED"      # …и ПОТОМ сломался
NS["_orch_clearance_watchdog"]()
check("43. НЕ ВАКУУМ: принтер стал FAILED уже после подтверждения — сторож жетон гасит",
      _c2.get("status") == "ok" and _orch.active_clearance("b2") is None, _c2)
_reset()
printer("b3", status="IDLE", raw="FAILED")
NS["p_states"]["b3"].update({"stage": 255, "print_type": "idle"})
USER_STOPPED["b3"] = time.monotonic() - 600        # «Стоп» в FM десять минут назад, отмена закончилась
_c3 = _route_clear("b3")
check("44. (R-118) после «Стоп» в FM и законченной отмены «Стол очищен» принимается (раньше — «принтер печатает»)",
      _c3.get("status") == "ok", _c3)
_reset()
printer("b4", status="IDLE", raw="RUNNING")        # маска IDLE, а прошивка ещё отрабатывает отмену
USER_STOPPED["b4"] = time.monotonic() - 600
_c4 = _route_clear("b4")
check("45. отмена ещё идёт (сырой RUNNING) — подтверждение по-прежнему отклоняется: «принтер занят»",
      _c4.get("status") == "error" and _c4.get("reason") == "printer_busy", _c4)
_reset()
printer("b5", status="IDLE", raw="FAILED")
NS["p_states"]["b5"].update({"stage": 255, "print_type": "idle"})
USER_STOPPED["b5"] = time.monotonic() - 5          # «Стоп» нажат только что: отчёт об отмене мог не прийти
_c5 = _route_clear("b5")
check("46. «Стоп» нажат несколько секунд назад — подтверждение пока отклоняется (запас на кадр отчёта)",
      _c5.get("status") == "error" and _c5.get("reason") == "printer_busy", _c5)

print()
print("=" * 94)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    for f in _fail:
        print("  ПРОВАЛ: %s" % f)
    sys.exit(1)
print()
print("PASS: автозапуск уходит сам только при разрешении владельца и только на принтер, чей стол "
      "подтверждён человеком — ВСЕГДА, а не только после печати; подтверждение одноразовое, "
      "«требует внимания» и неразобранные запуски автомат не трогает, исключение возвращает строку, "
      "причина неудачи хранится кодом, за проход уходит не больше одного запуска")
sys.exit(0)
