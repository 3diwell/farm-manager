# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# C1 confirm-flow (Alpha 2.728, корректировка без повышения версии).
# Проверяет ВОССТАНОВЛЕННЫЙ прежний confirm для C1 (печать файла уже на принтере, /api/printer/{pid}/cmd
# start_print): совместимость Bambu-файла проверяется СИНХРОННО ДО reservation/job; несовместимый файл без
# force → прежний confirm-required ответ (job=0, reservation=0, НИ одной команды принтеру); отмена → ничего;
# подтверждение (force) → ровно один job + одна reservation + одна MQTT-команда, compat пропущен; двойное
# подтверждение / захват другой вкладкой → второй запрос 409; after_dispatch для C1 не вызывается.
#
# БЕЗ сервера/принтера/сети/БД: из server.py ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ исходники (_PrintSendManager-блок,
# _c1_load_plate_compat, _bambu_start_print, _cmd_start_print_send) и исполняются со стабами; решение p_cmd
# start_print воспроизводится 1:1 (precheck → begin_direct → _send_accept_response). MQTT-публикация,
# FTP-загрузка и проверка совместимости — управляемые заглушки с счётчиками.
# Запуск: python tools/test_c1_confirm_flow.py   (0 = все проверки пройдены)
# ============================================================================
import os, sys, re, io, time, json, zipfile, threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)   # модули программы (app/...) берутся из репозитория
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

fail = 0
def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1
def _slice(a, b):
    i = SRC.index(a); return SRC[i:SRC.index(b, i)]

# ── ДОСЛОВНЫЕ исходники из server.py ──
MGR = SRC[SRC.index("from concurrent.futures import ThreadPoolExecutor as _SendPool"):SRC.index("\ndef _send_watchdog_loop")]
C1LOAD = _slice("def _c1_load_plate_compat(", "\ndef _bambu_start_print(")
#  2.988: перед первой командой печати сервер спрашивает свежий отчёт и проверяет, не занят
#  ли принтер. Берём эти функции ДОСЛОВНО — заглушка спрятала бы поведение.
BUSYPRE = _slice("def _bambu_print_started(", "\ndef _bambu_wait_started(")
BSTART = _slice("def _bambu_start_print(", "\ndef _creality_ws_send(")
C1AD = _slice("def _c1_after_dispatch(", "\ndef _cmd_start_print_send(")
#  16.10.2026 (R-006): плоский ams_mapping команды строит _bambu_wire_mapping (AMS HT — номер блока);
#  берётся ДОСЛОВНО, как и остальное: без неё старт C1 падал бы в песочнице NameError.
WIRE = _slice("def _bambu_wire_mapping(", "\ndef _tray_remain(")
CMDSEND = _slice("def _cmd_start_print_send(", "\n@app.post(\"/api/printer/{pid}/cmd\")")
#  16.10.2026 (R-137): внешняя катушка на пути «файл уже на принтере» решается по самому файлу
#  (_bambu_ext_choice внутри WIRE) — плита и сопла читаются НАСТОЯЩИМИ помощниками (AST).
import ast  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402
_TREE = ast.parse(SRC)
def _ast_src(names):
    out = []
    for node in _TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            out.append(ast.get_source_segment(SRC, node))
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            out.append(ast.get_source_segment(SRC, node))
    return "\n\n".join(out)
READERS = _ast_src(("_3mf_plate_used", "_3mf_side_values", "_3mf_filament_sides", "_bambu_ams_mapping",
                    "_bambu_refusal_reason", "_REQ_PROJECT_SETTINGS", "_REQ_SLICE_INFO", "_QW_PLATE_RE"))
check("извлечены дословные исходники (менеджер + _c1_load_plate_compat + _bambu_start_print + _cmd_start_print_send)",
      "class _PrintSendManager" in MGR and "def _c1_load_plate_compat" in C1LOAD
      and "_preload=None" in BSTART and "_preload=None" in CMDSEND)

# ── реальный 3mf-zip в памяти (плита + md5) ──
_zb = io.BytesIO()
with zipfile.ZipFile(_zb, "w") as _z:
    _z.writestr("Metadata/plate_1.gcode", "; g\nG28\n")
    _z.writestr("Metadata/plate_1.gcode.md5", "deadbeef")
FAKE_3MF = _zb.getvalue()
CUR_3MF = [FAKE_3MF]       # что «лежит на принтере» (отдаёт FTP-заглушка)

def mk_h2d(maps, nozzles=2):
    """Файл под H2D по устройству Bambu Studio: slice_info <plate> с filament_maps (сопло: 1 левое, 2 правое)."""
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("Metadata/project_settings.config", json.dumps({
            "filament_type": ["PLA"], "filament_colour": ["#FFFFFF"], "printer_model": "Bambu Lab H2D",
            "nozzle_diameter": ["0.4"] * nozzles}))
        si = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>", "  <plate>", '    <metadata key="index" value="1"/>']
        if maps:
            si.append('    <metadata key="filament_maps" value="%s"/>' % maps)
        si += ['    <filament id="1" tray_info_idx="GFL99" type="PLA" color="#FFFFFF" used_m="1.00" used_g="3.00" />',
               "  </plate>", "</config>"]
        z.writestr("Metadata/slice_info.config", "\n".join(si))
        z.writestr("Metadata/plate_1.gcode", "; g\nG28\n")
    return b.getvalue()
PUBS = []                  # что ушло принтеру (MQTT-кадры)
AD_MAPS = []               # с какой картой позвали after_dispatch

# ── управляемые счётчики/флаги ──
publishes = [0]        # число _bambu_publish (MQTT-команд); scheme=ftp → 1 кадр на старт
compat_calls = [0]     # число вызовов _check_file_compatible
compat_ok = [True]     # что вернёт _check_file_compatible
compat_reason = ["sliced for another printer"]
ad_calls = [0]         # after_dispatch (для C1 должен оставаться 0)

class _Log:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass

class _FakeFTP:
    def connect(self, *a, **k): pass
    def login(self, *a, **k): pass
    def prot_p(self): pass
    def set_pasv(self, *a, **k): pass
    def retrbinary(self, cmd, cb): cb(CUR_3MF[0])   # отдаём валидный 3mf
    def quit(self): pass

class _AllConn:
    def get(self, k, d=None): return object()       # mqtt_cls: соединение есть всегда

def _check_file_compatible(fdata, pid, val):
    compat_calls[0] += 1
    return (bool(compat_ok[0]), "" if compat_ok[0] else compat_reason[0])

def _bambu_resolve_ams(pid, slot, fdata):
    return (False, [-1], [{"ams_id": 255, "slot_id": 0}])

def _bambu_scheme_order(pid):
    return ["ftp"]                                   # одиночный кандидат → ровно 1 publish на старт

def _bambu_publish(pid, topic, payload):
    #  2.986: настоящая _bambu_publish возвращает True при успешной отправке, и с 2.978
    #  server.py на этот ответ смотрит: без связи по MQTT печать больше не считается
    #  начатой. Заглушка обязана держать тот же договор, иначе задание «падает».
    publishes[0] += 1
    try:
        PUBS.append(json.loads(payload))
    except Exception:
        pass
    return True

_uidc = [0]
def _uid(prefix=""):
    _uidc[0] += 1
    return str(prefix) + format(_uidc[0], "06d")

class _JSONResponse:                                 # стаб FastAPI JSONResponse (нужен status_code)
    def __init__(self, content, status_code=200):
        self.content = content; self.status_code = status_code

ns = {
    "threading": threading, "time": time, "os": os, "re": re, "io": io, "zipfile": zipfile, "json": json,
    "_uid": _uid, "p_states": {}, "last_seen": {}, "STALE_FAIL_S": 60,
    #  2.988: предполётная проверка занятости — настоящий модуль политики.
    "_bstart": __import__("app.bambu_start_policy", fromlist=["x"]), "_bambu_cmd_ack": {},
    "log": _Log(), "_exc_brief": (lambda: ""),
    "TEMP_FILES_DIR": os.path.join(REPO, "__no_such_dir_for_c1_test__"),   # нет локальной копии → путь FTP
    "_ftp_lock": (lambda ip: threading.Lock()), "ImplicitFTP_TLS": _FakeFTP,
    "_check_file_compatible": _check_file_compatible, "_bambu_resolve_ams": _bambu_resolve_ams,
    "_bambu_scheme_order": _bambu_scheme_order, "_bambu_publish": _bambu_publish,
    "_sniff_sanitize": (lambda x: x), "bambu_serials": {},
    "mqtt_cls": _AllConn(), "JSONResponse": _JSONResponse,
    "urllib": None, "_flashforge_print": (lambda *a, **k: None),
    "_run_after_dispatch_hooks": (lambda *a, **k: (AD_MAPS.append(list(a[1])), ad_calls.__setitem__(0, ad_calls[0] + 1))),
    #  16.10.2026 (R-114, R-138): причина отказа «занят» уходит в панель; память отказов — на запуск.
    "_bambu_last_refusal": {}, "ET": ET,
    "_health": __import__("app.printer_health_policy", fromlist=["x"]),
    #  2.977 (R-095): путь «файл уже на принтере» зовёт _c1_after_dispatch — списание
    #  филамента и запись в складской журнал. Кладём в песочницу то, на чём она держится,
    #  иначе задание падает NameError вместо проверки поведения.
    "_stash_run_assignments": (lambda *a, **k: None),
    "_moonraker_weight_stub": (lambda *a, **k: b""),
    "_klipper_dispatch_slots": (lambda pid, ch: ([0], True)),
    "_demo": type("_D", (), {"file_data": staticmethod(lambda *a, **k: b"")})(),
}
exec(MGR, ns)
exec(READERS, ns)
exec(C1LOAD, ns)
exec(BUSYPRE, ns)
exec(BSTART, ns)
exec(C1AD, ns)
exec(WIRE, ns)
exec(CMDSEND, ns)
Mgr = ns["_PrintSendManager"]
_c1_load_plate_compat = ns["_c1_load_plate_compat"]
_cmd_start_print_send = ns["_cmd_start_print_send"]
_send_accept_response = ns["_send_accept_response"]

class Data:
    """Заглушка PCmd (только поля, читаемые путём start_print)."""
    def __init__(self, val, force=False, ams_slot=None):
        self.val = val; self.force = force; self.ams_slot = ams_slot

def p_cmd_start(mgr, pid, p, data):
    """ДОСЛОВНАЯ копия решения p_cmd start_print (Alpha 2.728 C1 confirm restore):
    для Bambu — синхронный compat-precheck ДО reservation; блок → прежний incompatible-ответ (без job/reservation/команд);
    иначе preload + begin_direct через _cmd_start_print_send → _send_accept_response (accepted / 409)."""
    _fname = os.path.basename(str(data.val or ""))
    _preload = None
    if p["type"] == "bambu":
        _d3, _pp, _blk = _c1_load_plate_compat(pid, p, data)
        if _blk:
            return _blk
        #  16.10.2026 (R-137): как в p_cmd — внешняя катушка двухсопельного решается по файлу сразу.
        if data.ams_slot is None or int(data.ams_slot) < 0:
            _xc1 = ns["_bambu_ext_choice"](pid, _d3, explicit=False)
            if not _xc1.get("ok"):
                return {"status": "error", "reason": _xc1.get("why")}
        _preload = (_d3, _pp)
    _ok, _job_id, _reason = mgr.begin_direct(pid, p["name"], _fname, "printer_file", _cmd_start_print_send(p, pid, data, _preload))
    return _send_accept_response(_ok, _job_id, _reason, pid)

P = {"type": "bambu", "name": "Bambu", "ip": "10.0.0.9", "port": 8883, "token": "sekret"}

def _wait_jobs(mgr, n, dl=1.5):
    t = time.time() + dl
    while time.time() < t and len(mgr.snapshot()["jobs"]) < n:
        time.sleep(0.01)

# ═══ C1a: совместимый файл → accepted job (общий фоновый механизм), 1 MQTT-команда ═══
publishes[0] = 0; compat_calls[0] = 0; compat_ok[0] = True
m = Mgr()
resp = p_cmd_start(m, "P1", P, Data("model.gcode.3mf", force=False))
_wait_jobs(m, 1); time.sleep(0.25)
snap = m.snapshot()
check("C1a. совместимый C1 → accepted; ровно 1 job + 1 reservation; compat проверен синхронно (1 раз); ровно 1 MQTT-команда",
      isinstance(resp, dict) and resp.get("accepted") is True and resp.get("job_id")
      and len(snap["jobs"]) == 1 and "P1" in snap["reserved_printer_ids"]
      and compat_calls[0] == 1 and publishes[0] == 1)

# ═══ C1b: несовместимый файл без force → прежний confirm-required; job=0, reservation=0, MQTT=0 ═══
publishes[0] = 0; compat_calls[0] = 0; compat_ok[0] = False; compat_reason[0] = "sliced for X1C, printer is A1"
m = Mgr()
resp = p_cmd_start(m, "P2", P, Data("model.gcode.3mf", force=False))
snap = m.snapshot()
check("C1b. несовместимый C1 (без force) → confirm-required {status:incompatible, reason}; НИ job, НИ reservation, НИ MQTT-команды",
      isinstance(resp, dict) and resp.get("status") == "incompatible" and "X1C" in (resp.get("reason") or "")
      and len(snap["jobs"]) == 0 and len(snap["reserved_printer_ids"]) == 0
      and publishes[0] == 0 and compat_calls[0] == 1)

# ═══ C1c: отмена пользователем (повторный запрос НЕ отправлен) → ничего не создано/не выполнено ═══
snap = m.snapshot()
check("C1c. отмена подтверждения (нет force-повтора) → job=0, reservation=0, MQTT=0 — ничего не запущено",
      len(snap["jobs"]) == 0 and len(snap["reserved_printer_ids"]) == 0 and publishes[0] == 0)

# ═══ C1d: подтверждение (force=true) → ровно один job + одна reservation + одна MQTT-команда; compat пропущен ═══
publishes[0] = 0; compat_calls[0] = 0; compat_ok[0] = False   # файл всё ещё «несовместим», но force его пропускает
m = Mgr()
resp = p_cmd_start(m, "P3", P, Data("model.gcode.3mf", force=True))
_wait_jobs(m, 1); time.sleep(0.25)
snap = m.snapshot()
check("C1d. подтверждение (force=true) → ровно 1 job + 1 reservation + ровно 1 MQTT-команда; _check_file_compatible НЕ вызывается",
      isinstance(resp, dict) and resp.get("accepted") is True
      and len(snap["jobs"]) == 1 and "P3" in snap["reserved_printer_ids"]
      and publishes[0] == 1 and compat_calls[0] == 0)

# ═══ C1e: двойное подтверждение / другая вкладка заняла принтер за время диалога → второй запрос 409 ═══
publishes[0] = 0; compat_calls[0] = 0; compat_ok[0] = True
m = Mgr()
respA = p_cmd_start(m, "P4", P, Data("model.gcode.3mf", force=True))
_wait_jobs(m, 1); time.sleep(0.2)                 # первый accepted → waiting_confirmation, reservation ДЕРЖИТСЯ
respB = p_cmd_start(m, "P4", P, Data("model.gcode.3mf", force=True))   # 2-е подтверждение / другая вкладка
snap = m.snapshot()
jobsP4 = [j for j in snap["jobs"] if j["printer_id"] == "P4"]
check("C1e. двойное подтверждение / захват другой вкладкой → второй запрос 409 (printer_send_busy); ровно 1 job + 1 reservation; 1 MQTT-команда",
      isinstance(respA, dict) and respA.get("accepted") is True
      and getattr(respB, "status_code", None) == 409
      and isinstance(getattr(respB, "content", None), dict) and respB.content.get("error") == "printer_send_busy"
      and len(jobsP4) == 1 and "P4" in snap["reserved_printer_ids"] and publishes[0] == 1)

# ═══ C1f: after_dispatch для C1 вызывается ровно один раз (2.977, R-095: филамент по файлу,
#          уже лежащему на принтере, списывается — до этого не списывался вовсе) ═══
ad_calls[0] = 0; publishes[0] = 0; compat_ok[0] = True
m = Mgr()
p_cmd_start(m, "P5", P, Data("model.gcode.3mf", force=True))
_wait_jobs(m, 1); time.sleep(0.25)
check("C1f. C1: after_dispatch вызывается ровно один раз (2.977 R-095: филамент списывается); MQTT-команда ушла",
      ad_calls[0] == 1 and publishes[0] == 1)

# ═══ C1g–C1j (16.10.2026, R-137): внешняя катушка H2D — по соплу в самом файле, как FROM_SDCARD_VIEW у Studio ═══
def _run_c1(pid, data3mf, nozzles):
    publishes[0] = 0; ad_calls[0] = 0; compat_ok[0] = True; PUBS[:] = []; AD_MAPS[:] = []
    CUR_3MF[0] = data3mf
    ns["p_states"][pid] = {"nozzle_count": nozzles}
    m = Mgr()
    r = p_cmd_start(m, pid, P, Data("model.gcode.3mf", force=True))
    _wait_jobs(m, 1); time.sleep(0.25)
    return r, m.snapshot()

r, snap = _run_c1("H2D_L", mk_h2d("1"), 2)
_pl = [x["print"] for x in PUBS if (x.get("print") or {}).get("command") == "project_file"]
check("C1g. H2D, файл на принтере нарезан под ЛЕВОЕ сопло → команда use_ams=false, [-1], [{254, 0}]; "
      "складу — позиция -2 (левая)",
      isinstance(r, dict) and r.get("accepted") is True and len(_pl) == 1
      and _pl[0]["ams_mapping2"] == [{"ams_id": 254, "slot_id": 0}] and _pl[0]["ams_mapping"] == [-1]
      and _pl[0]["use_ams"] is False and AD_MAPS == [[-2]])
r, snap = _run_c1("H2D_R", mk_h2d("2"), 2)
_pl = [x["print"] for x in PUBS if (x.get("print") or {}).get("command") == "project_file"]
check("C1h. H2D, файл под ПРАВОЕ сопло → [{255, 0}], складу -1",
      len(_pl) == 1 and _pl[0]["ams_mapping2"] == [{"ams_id": 255, "slot_id": 0}] and AD_MAPS == [[-1]])
r, snap = _run_c1("H2D_U", mk_h2d(None), 2)
check("C1i. H2D, в файле нет сопла → отказ СРАЗУ (с причиной): ни задания, ни резерва, ни команды, ни списания",
      isinstance(r, dict) and r.get("status") == "error" and "соплом" in (r.get("reason") or "")
      and len(snap["jobs"]) == 0 and publishes[0] == 0 and ad_calls[0] == 0)
r, snap = _run_c1("P1S_1", FAKE_3MF, 1)
_pl = [x["print"] for x in PUBS if (x.get("print") or {}).get("command") == "project_file"]
check("C1j. односопельный, однофиламентный файл — команда прежняя [-1]/[{255, 0}]",
      len(_pl) == 1 and _pl[0]["ams_mapping"] == [-1] and _pl[0]["ams_mapping2"] == [{"ams_id": 255, "slot_id": 0}])
#  Фоновый запуск перепроверяет сам: даже если окно его пропустило, правая катушка «по умолчанию» не уйдёт.
publishes[0] = 0; PUBS[:] = []
ns["p_states"]["H2D_X"] = {"nozzle_count": 2}
_rx = ns["_bambu_start_print"](object(), "H2D_X", P, Data("model.gcode.3mf", force=True), (mk_h2d(None), "Metadata/plate_1.gcode"))
check("C1k. фоновый запуск тоже отказывает без команды, если сопло не известно",
      isinstance(_rx, dict) and _rx.get("status") == "error" and publishes[0] == 0, )
CUR_3MF[0] = FAKE_3MF

print()
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if fail == 0 else ("ПРОВАЛЕНО ПРОВЕРОК: " + str(fail)))
sys.exit(1 if fail else 0)
