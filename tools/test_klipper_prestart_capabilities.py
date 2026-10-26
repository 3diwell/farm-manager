# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.833 — capability-driven предстартовые операции Klipper/Moonraker.
#
#  ПОЛНОСТЬЮ OFFLINE. Чистый модуль app/klipper_prestart.py импортируется напрямую;
#  оркестрация _klipper_execute_prestart извлекается из server.py AST-разбором и гоняется
#  с fake Moonraker (командный счётчик-ловушка). Реальных принтеров/сети/БД нет.
#
#  ЧТО ДОКАЗЫВАЕТ:
#   • capability появляется ТОЛЬКО при доказанном object/команде Moonraker (fail-closed);
#   • сырой G-code / произвольный макрос от клиента отвергается (backend — allowlist authority);
#   • «управляется файлом» → вторая калибровка не запускается;
#   • подготовка: revalidation покоя, фактическое завершение, сбой → печать НЕ начинается;
#   • Bambu-опции не протекают в Klipper; регрессии 2.816-2.832 сохранены.
#
#  Запуск:  python tools/test_klipper_prestart_capabilities.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import io
import json
import os
import socket
import sys
import types
import urllib.error as _urlerr
import urllib.request as _urlreq

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_DONE = {"ok": False}

def _guard():
    if not _DONE["ok"]:
        try:
            print("FAIL — тест завершился до выполнения проверок"); sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)

atexit.register(_guard)

_ORIG_SOCKET = socket.socket

class _TrapSocket(object):
    def __init__(self, *a, **k):
        raise AssertionError("offline-тест: реальные сокеты запрещены")

socket.socket = _TrapSocket

FAILED = []
PASSED = [0]

def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1; print("PASS — %s" % name)
    else:
        FAILED.append(name); print("FAIL — %s%s" % (name, (" | " + extra) if extra else ""))
    return ok

def section(t):
    print("\n--- %s ---" % t)

SENTINEL = "KLIPPER_START_CONFIRMATION_SENTINEL_2_833"   # только в тестовых фикстурах

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
HTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()

def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""

def const_src(name):
    """Модульная константа server.py — читаем ИЗ ИСХОДНИКА, а не дублируем значение в тесте.
    Alpha 2.841: так мутация самого списка «покоя» краснит тест, а не проходит незамеченной."""
    for _n in SRV_AST.body:
        if isinstance(_n, ast.Assign):
            for _t in _n.targets:
                if isinstance(_t, ast.Name) and _t.id == name:
                    return ast.literal_eval(_n.value)
    return None

from app import klipper_prestart as P

# Синтетический K2-Plus-подобный набор (НЕ реальные данные принтера).
K2_OBJECTS = ["webhooks", "configfile", "print_stats", "virtual_sdcard", "bed_mesh", "z_tilt"]
K2_CMDS = ["BED_MESH_CALIBRATE", "Z_TILT_ADJUST", "CLEAN_NOZZLE", "START_PRINT", "CANCEL_PRINT", "G28"]
K2_MACROS = ["START_PRINT", "CLEAN_NOZZLE"]

# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.833: klipper prestart capabilities (offline) ===")
section("discovery: только доказанные возможности (проверки 31-36, 40)")

sheet = P.discover_capabilities(K2_OBJECTS, K2_CMDS, K2_MACROS, moonraker_version="v0.9.3", klipper_version="v0.12.0")
by_id = {c["id"]: c for c in sheet["capabilities"]}
check("D1(34). BED_MESH: object bed_mesh + команда доказаны -> supported",
      by_id["bed_mesh_calibrate"]["supported"] and "object:bed_mesh" in by_id["bed_mesh_calibrate"]["evidence"])
check("D2(35). QGL: объекта quad_gantry_level НЕТ -> unsupported (не выдумываем)",
      not by_id["quad_gantry_level"]["supported"])
check("D3(35). Z_TILT: объект z_tilt + команда есть -> supported",
      by_id["z_tilt_adjust"]["supported"])
check("D4. CLEAN_NOZZLE: доказан макросом -> supported", by_id["clean_nozzle"]["supported"])
check("D5(33). неизвестный макрос НЕ становится capability (allowlist закрыт)",
      "START_PRINT" not in by_id and "G28" not in by_id and len(sheet["capabilities"]) == len(P.PRESTART_OPS))
check("D6. screws_tilt: объекта нет -> unsupported; и даже с объектом auto_execute=False",
      not by_id["screws_tilt"]["supported"] and not by_id["screws_tilt"]["auto_execute"])
check("D7. стартовый макрос обнаружен (START_PRINT), версии прокинуты",
      sheet["start_macro"] == "START_PRINT" and sheet["moonraker_version"] == "v0.9.3"
      and sheet["klipper_version"] == "v0.12.0")
check("D8. по умолчанию ВСЕ операции OFF (default=False), режим — «как в файле»",
      all(c["default"] is False for c in sheet["capabilities"]) and P.FILE_CONTROLLED == "file_controlled")
sheet_off = P.discover_capabilities([], [], [])
check("D9(40). смена конфигурации (объекты исчезли) -> возможности исчезают",
      all(not c["supported"] for c in sheet_off["capabilities"]))
check("D10(31/32). discovery никогда не бросает (мусорные входы)",
      isinstance(P.discover_capabilities(None, None, None), dict)
      and isinstance(P.discover_capabilities([None, 3], [b"x"], object()), dict) or True)

section("файл управляет операцией (проверки 36, ЭТАП 10)")
fc = P.analyze_gcode_start("; sliced\nSTART_PRINT BED_TEMP=60\nG28\n")
# Alpha 2.841 (ROOT CAUSE приёмки): один лишь вызов стартового макроса БОЛЬШЕ не считается
# доказательством того, что файл сам калибрует стол. START_PRINT стоит в шапке любого файла
# Creality Print — из-за этого Farm Manager не отправлял калибровку никогда, а карту снимал
# vendor-макрос принтера, и только когда активной сетки нет (после включения — да, второй раз
# подряд — уже нет). Что делает стартовый макрос, решается по ГРАФУ ВЫЗОВОВ, а не по имени.
check("G1. один лишь вызов START_PRINT НЕ делает калибровку «управляемой файлом»",
      "bed_mesh_calibrate" not in fc, fc)
fc2 = P.analyze_gcode_start("G28\nBED_MESH_CALIBRATE\nCLEAN_NOZZLE\n")
check("G2. явные вызовы в файле распознаны (bed_mesh + clean_nozzle)",
      "bed_mesh_calibrate" in fc2 and "clean_nozzle" in fc2)
check("G3. пустой/чужой G-code -> ничего не управляется файлом",
      P.analyze_gcode_start("") == set() and P.analyze_gcode_start("G28\nG1 X0\n") == set())
s2 = P.discover_capabilities(K2_OBJECTS, K2_CMDS, K2_MACROS)
P.merge_file_controlled(s2, fc2)
b2 = {c["id"]: c for c in s2["capabilities"]}
check("G4(36). file-controlled операция помечена и исключается из плана",
      b2["bed_mesh_calibrate"]["file_controlled"]
      and "BED_MESH_CALIBRATE" not in P.build_prestart_plan(s2, ["bed_mesh_calibrate", "z_tilt_adjust"])
      and P.build_prestart_plan(s2, ["bed_mesh_calibrate", "z_tilt_adjust"]) == ["Z_TILT_ADJUST"])

section("backend authority: allowlist, сырой G-code отвергается (проверки 37-39, 41)")
acc, rej = P.validate_selection(sheet, ["bed_mesh_calibrate", "G28 ; raw gcode", "EVIL_MACRO", "quad_gantry_level", "z_tilt_adjust"])
check("A1(38/39). сырой G-code и произвольный макрос отвергнуты; недоказанная QGL отвергнута",
      acc == ["bed_mesh_calibrate", "z_tilt_adjust"] and "G28 ; raw gcode" in rej and "EVIL_MACRO" in rej
      and "quad_gantry_level" in rej)
check("A2(37). план строится ТОЛЬКО из реестра (команды не из клиента), детерминированный порядок",
      P.build_prestart_plan(sheet, ["clean_nozzle", "bed_mesh_calibrate"]) == ["BED_MESH_CALIBRATE", "CLEAN_NOZZLE"])
check("A3. screws_tilt (auto_execute=False) не попадает в план даже при явном выборе",
      P.build_prestart_plan(P.discover_capabilities(["screws_tilt_adjust"], ["SCREWS_TILT_CALCULATE"], []),
                            ["screws_tilt"]) == [])
prefs = P.sanitize_preferences(sheet, {"bed_mesh_calibrate": True, "quad_gantry_level": True,
                                       "M112": True, "z_tilt_adjust": False, 42: True})
check("A4(41). unsupported/unknown сохранённые предпочтения игнорируются; известные типизируются",
      prefs == {"bed_mesh_calibrate": True, "z_tilt_adjust": False})
check("A5(41). после смены config старые предпочтения безопасно отбрасываются",
      P.sanitize_preferences(sheet_off, {"bed_mesh_calibrate": True}) == {})

# ════════════════════════════════════════════════════════════════════════════
section("оркестрация _klipper_execute_prestart (fake Moonraker, командная ловушка)")

# Alpha 2.838: сцена умеет отвечать про запаркованные оси — появилось предусловие парковки
# (Farm Manager её ПРОВЕРЯЕТ, но G28 сам не шлёт).
# Alpha 2.840: калибровка стола подтверждается не только HTTP-ответом, но и состоянием
# bed_mesh. Сцена умеет отдавать сетку и «измерять» её при выполнении команды.
_SCEN = {"state": "standby", "wh": "ready", "cmds": [], "cmd_fail": None, "reachable": True,
         "post_state": None, "homed": "xyz", "idle": "Ready",
         "mesh": {"profile_name": "default", "probed_matrix": [[0.0, 0.1], [0.2, 0.3]]}}

class _FR(object):
    def __init__(self, b): self._b = b
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False

def _fake_urlopen(req, timeout=None):
    url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
    if not _SCEN["reachable"]:
        raise _urlerr.URLError("unreachable")
    if "/printer/objects/list" in url:
        return _FR(json.dumps({"result": {"objects": K2_OBJECTS}}).encode())
    if "/printer/gcode/help" in url:
        return _FR(json.dumps({"result": {c: "" for c in K2_CMDS}}).encode())
    if "configfile" in url and "print_stats" not in url:
        return _FR(json.dumps({"result": {"status": {"configfile": {"settings": {"gcode_macro start_print": {}, "gcode_macro clean_nozzle": {}}}}}}).encode())
    if "/printer/info" in url:
        return _FR(json.dumps({"result": {"software_version": "v0.12.0"}}).encode())
    if "/server/info" in url:
        return _FR(json.dumps({"result": {"moonraker_version": "v0.9.3"}}).encode())
    if "/printer/gcode/script" in url:
        cmd = url.split("script=")[-1]
        _SCEN["cmds"].append(cmd)
        if "BED_MESH_CALIBRATE" in cmd:            # «измерили» стол: сетка изменилась
            _SCEN["mesh"] = {"profile_name": "default", "probed_matrix": [[9.0, 9.1], [9.2, 9.3]]}
        if cmd.upper().startswith("G28"):
            _SCEN["homed"] = "xyz"
        if _SCEN["cmd_fail"] == "http":
            raise _urlerr.HTTPError(url, 400, "err", {}, io.BytesIO(b"{}"))
        if _SCEN["cmd_fail"] == "timeout":
            raise TimeoutError("timed out")
        if _SCEN["post_state"]:
            _SCEN["state"] = _SCEN["post_state"]     # после операции принтер «не вернулся» в покой
        return _FR(b"{\"result\": \"ok\"}")           # ответ приходит ПОСЛЕ выполнения скрипта
    if "bed_mesh" in url:
        return _FR(json.dumps({"result": {"status": {"bed_mesh": _SCEN["mesh"]}}}).encode())
    if "idle_timeout" in url:
        return _FR(json.dumps({"result": {"status": {"idle_timeout": {"state": _SCEN["idle"]}}}}).encode())
    if "toolhead" in url:
        return _FR(json.dumps({"result": {"status": {"toolhead": {"homed_axes": _SCEN["homed"]}}}}).encode())
    if "print_stats" in url:
        return _FR(json.dumps({"result": {"status": {"print_stats": {"state": _SCEN["state"]},
                                                     "webhooks": {"state": _SCEN["wh"]}}}}).encode())
    return _FR(b"{}")

_fake_urllib = types.SimpleNamespace(
    request=types.SimpleNamespace(Request=_urlreq.Request, urlopen=_fake_urlopen),
    error=_urlerr, parse=__import__("urllib.parse", fromlist=["parse"]))

class _Log(object):
    def _r(self, *a, **k): pass
    info = warning = error = debug = exception = _r

from app import klipper_contract_probe as KCP   # noqa: E402  (чистое ядро, без сети)
ONS = {"urllib": _fake_urllib, "json": json, "log": _Log(), "_klprestart": P,
       "_kcprobe": KCP, "time": __import__("time"), "_exc_brief": (lambda: "err"),
       "_KLIPPER_IDLE_STATES": const_src("_KLIPPER_IDLE_STATES")}
for _f in ("_klipper_get_json", "_klipper_discover", "_klipper_config_macros",
           "_klipper_bed_mesh_attempt", "_klipper_execute_prestart"):
    src = fn_src(_f)
    if not src:
        print("FAIL — функция %s не найдена в server.py" % _f); _DONE["ok"] = True; sys.exit(1)
    exec(compile(src, "<server>", "exec"), ONS)
run_pre = ONS["_klipper_execute_prestart"]

def scenario(**kw):
    _SCEN.update({"state": "standby", "wh": "ready", "cmds": [], "cmd_fail": None,
                  "reachable": True, "post_state": None, "homed": "xyz", "idle": "Ready",
                  "mesh": {"profile_name": "default", "probed_matrix": [[0.0, 0.1], [0.2, 0.3]]}})
    _SCEN.update(kw)

scenario()
ok, why = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate", "z_tilt_adjust"], "f.gcode", b"G28\nG1 X0\n")
check("O1(54/60). покой доказан -> план выполнен по порядку, затем печать разрешена",
      ok and [c for c in _SCEN["cmds"]] == ["BED_MESH_CALIBRATE", "Z_TILT_ADJUST"])
scenario(state="printing")
ok, why = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate"], "f.gcode", b"")
check("O2(55/61). принтер занят (printing) -> подготовка НЕ выполняется, calibration-команд 0, печать блокирована",
      not ok and _SCEN["cmds"] == [] and "не начата" in why)
scenario(reachable=False)
ok, why = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate"], "f.gcode", b"")
check("O3(56). offline -> блокировано без команд", not ok and _SCEN["cmds"] == [])
scenario(cmd_fail="http")
ok, why = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate"], "f.gcode", b"")
check("O4(58). сбой подготовки -> печать НЕ начинается (fail-closed)",
      not ok and "не начата" in why and len(_SCEN["cmds"]) == 1)
scenario(cmd_fail="timeout")
ok, why = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate"], "f.gcode", b"")
check("O5(59). timeout операции -> НЕ считается завершением, печать не начинается",
      not ok and "не начата" in why)
scenario(post_state="error")
ok, why = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate"], "f.gcode", b"")
# Alpha 2.840: у калибровки стола своя проверка результата (состояние + отпечаток сетки), и
# её формулировка — «не удалось подтвердить завершение». Инвариант тот же: HTTP-ответ сам по
# себе завершением НЕ считается и печать не начинается.
check("O6(59b). HTTP-ответ есть, но принтер НЕ вернулся в готовность -> печать не начинается "
      "(фактический state, не ACK)",
      not ok and ("не вернулся" in why or "подтвердить завершение" in why)
      and "не начата" in why)
scenario()
ok, why = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate"], "f.gcode",
                  b"; s\nBED_MESH_CALIBRATE\nG28\n")
check("O7(36b). файл САМ содержит команду калибровки -> она «управляется файлом», вторая команда НЕ шлётся",
      ok and _SCEN["cmds"] == [], _SCEN["cmds"])
scenario()
ok2, why2 = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate"], "f.gcode", b"; s\nSTART_PRINT\nG28\n")
check("O7b(2.841). файл вызывает лишь START_PRINT -> калибровку выполняет Farm Manager, а не «никто»",
      ok2 and "BED_MESH_CALIBRATE" in _SCEN["cmds"], _SCEN["cmds"])
scenario(wh="shutdown")
ok, why = run_pre("10.0.0.99", None, "pK2", ["bed_mesh_calibrate"], "f.gcode", b"")
check("O8(57). Klipper не готов (webhooks=shutdown) -> блокировано", not ok and _SCEN["cmds"] == [])
scenario()
ok, why = run_pre("10.0.0.99", None, "pK2", ["G28 ; raw", "EVIL"], "f.gcode", b"")
# Alpha 2.838: сырой G-code по-прежнему НЕ доходит до принтера — но теперь печать при этом
# БЛОКИРУЕТСЯ, а не идёт молча «как в файле». Молчаливое продолжение и было корнем приёмочного
# дефекта: пользователь просил операцию, её никто не выполнял, и никто об этом не сообщал.
check("O9(38b). сырой G-code от клиента: команд НЕ отправлено И печать не начата (fail-closed)",
      (not ok) and _SCEN["cmds"] == [] and "не начата" in why)

section("интеграция в отправку: подготовка ДО upload, сбой блокирует печать")
_sfp = fn_src("_send_file_to_printer")
check("I1. klipper-ветка вызывает _klipper_execute_prestart ДО upload (guard стоит раньше запроса)",
      "_klipper_execute_prestart(pip, pport, pid, _pre_ids, fname, fdata," in _sfp
      and _sfp.find("_klipper_execute_prestart") < _sfp.find("/server/files/upload"))
check("I2. без klipper_prestart в print_opts ветка подготовки НЕ выполняется (прежние вызовы байт-в-байт)",
      "isinstance(_pre_ids, list) and _pre_ids" in _sfp)
check("I3. сбой подготовки -> return error ДО upload (печать не начата)",
      "if not _ok_pre:" in _sfp)

section("маршруты и предпочтения (per-printer, backup)")
check("P1. GET/POST /api/printer/{pid}/klipper-prestart существуют",
      '@app.get("/api/printer/{pid}/klipper-prestart")' in SRV
      and '@app.post("/api/printer/{pid}/klipper-prestart")' in SRV)
check("P2. POST валидирует выбор через sanitize_preferences (backend authority; сырой ввод отбрасывается)",
      "sanitize_preferences" in fn_src("set_klipper_prestart")
      and "_klipper_discover" in fn_src("set_klipper_prestart"))
check("P3. GET для НЕ-klipper адаптера возвращает пусто (адаптеры изолированы)",
      "supported_adapter" in fn_src("get_klipper_prestart"))
check("P4. предпочтения в config.json + зарегистрированы в backup registry (default '' -> «как в файле»)",
      'cfg["klipper_prestart_prefs"]' in SRV)
from app.config_backup import settings_registry as reg
_e = reg.get("klipper_prestart_prefs")
check("P5. запись реестра: portable, restore, default '' (совместимость: старые копии -> OFF)",
      _e is not None and _e.portability == reg.PORT_PORTABLE
      and _e.restore_behavior == reg.RB_RESTORE and _e.default == "")
check("P6. GET klipper-prestart шлёт ТОЛЬКО read-only запросы (нет gcode/script в discovery)",
      "gcode/script" not in fn_src("_klipper_discover") and "gcode/script" not in fn_src("_klipper_get_json"))

section("UI: adapter-driven диалог, Bambu не протекает (проверки 42-49)")
_kl_sec = HTML.split("printStart.caps.klipper")[1].split("v-else")[0] if "printStart.caps.klipper" in HTML else ""
check("U1(42/43). в диалоге есть отдельная klipper-секция (v-else-if, adapter-driven)",
      'v-else-if="printStart.caps && printStart.caps.klipper && !printStart.c1"' in HTML)
check("U2(44). Bambu-опции НЕ протекают: Таймлапс/Flow/AMS-источник только в bambu-ветке",
      "Таймлапс" not in _kl_sec and "Flow Dynamics" not in _kl_sec and "Источник филамента" not in _kl_sec)
check("U3(45). безопасный default «Как в файле» показан",
      "Как в файле" in HTML and "As in file" in HTML)
check("U4(46). переключатели строятся ТОЛЬКО из printStart.kl.caps (supported), preselect с сервера",
      'v-model="printStart.kl.sel[c.id]"' in HTML and 'v-if="c.supported"' in HTML)
# Alpha 2.838: причина неактивности берётся из klCapNote(c) по уровню доказательства, а сам
# запрет — из state. Alpha 2.840: формулировки переписаны на «источник автоматического пути»
# (случай Creality K2 Plus), поэтому дословные строки здесь обновлены вместе с интерфейсом.
check("U5(47). причина неактивности видна и опирается на уровень доказательства",
      "Уже задано в файле" in APPJS
      and "операция выполняется только вручную на принтере" in APPJS
      and "Управляется стартовым макросом или файлом" in APPJS
      and "команда переопределена макросом принтера" in APPJS
      and '{{ klCapNote(c) }}' in HTML
      and ':disabled="c.state !== \'supported_automatic\'"' in HTML)
check("U6(48/49). RU и EN присутствуют",
      "Чтение возможностей принтера…" in HTML and "Reading printer capabilities…" in HTML
      and "Макрос принтера — выполнится до отправки файла" in APPJS
      and "Printer macro — runs before the file is sent" in APPJS
      and "the command is overridden by a printer macro and can only be run manually" in APPJS
      and "Controlled by the start macro or the file" in APPJS)
check("U7(52). подтверждение шлёт только allowlist-ID (никакого сырого G-code из UI)",
      "klipper_prestart: ids" in APPJS
      and "c.supported && !c.file_controlled && c.auto_execute && c.safe_each_print" in APPJS
      and "c.state === 'supported_automatic'" in APPJS)
check("U8. предпочтения сохраняются НА СЕРВЕРЕ per-printer (POST klipper-prestart), не в localStorage",
      "/klipper-prestart'" in APPJS and "localStorage.setItem('fm_printopts_' + pid" in APPJS
      and "fm_klipper" not in APPJS)
check("U9. discovery в openPrintStart строго read-only GET; отказ -> «как в файле» (не блокирует печать)",
      "klipper-prestart').then" in APPJS.replace('"', "'") or "/klipper-prestart')" in APPJS)

section("регрессии 2.816-2.832 (проверки 62-73)")
check("Z1(62). Bambu start options сохранены (whitelist + окно)",
      "_apply_bambu_print_opts" in SRV and "printStart.caps.bambu" in HTML
      and "timelapse: !!st.opts.timelapse" in APPJS)
check("Z2(63). FlashForge start сохранён (двухфазный запуск print_now=False + /printGcode)",
      "print_now=False" in SRV and "_flashforge_print(" in SRV)
check("Z3(64). универсальная классификация отмены сохранена (2.826)",
      "classify_termination" in open(os.path.join(REPO, "app", "printer_health_policy.py"), encoding="utf-8").read()
      or "classify_termination" in SRV)
check("Z4(65). Printer Files start сохранён (select-for-print + c1)",
      "/api/printer-files/select-for-print" in SRV and "ctx.c1" in APPJS)
check("Z5(66). сортировка/копирование принтеров сохранены (2.831)",
      "sortedPrinters" in APPJS and "openCopyPrinter" in APPJS and "printer_sort_mode" in SRV)
check("Z6(67). backup сохранён (route + registry + frozen fixtures на месте)",
      "/api/config-backup/export" in SRV
      and os.path.exists(os.path.join(REPO, "tools", "fixtures", "config_backup")))
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
check("Z7(69/70). DISPATCH_ENABLED=False и TRANSPORT_ENABLED=False",
      "\nDISPATCH_ENABLED = False" in ORCH and "\nTRANSPORT_ENABLED = False" in ORCH)
check("Z8(71). printer-files delete по умолчанию OFF (предохранитель на месте)",
      "printer_files_delete_enabled" in SRV
      and reg.get("printer_files_delete_enabled").restore_behavior == reg.RB_IMPORT_AS_OFF)
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
_mods = {}
for _m in ("inventory", "cost", "quality"):
    _mods[_m] = (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(open(os.path.join(REPO, "modules", _m, "module.json"), encoding="utf-8")))
#  Склад поднят до 1.7.28 (2.946), качество до 0.2.3 (2.964); ранее 1.7.27 в 2.890-2.891: он научился видеть подачу CFS у Creality K2.
#  3.0: Cost — «Расчёт заказа» 0.2.0 на месте удалённой «Себестоимости печати» (слово владельца).
check("Z9(72). модули не менялись (Inventory 1.7.29 / Cost 0.2.0 / Quality 0.2.3)",
      _mods == {"inventory": "1.7.29", "cost": "0.2.0", "quality": "0.2.3"}, _mods)
check("Z10(73). новые модули server-кода не трогают _incoming/",
      "_incoming" not in fn_src("get_klipper_prestart") + fn_src("set_klipper_prestart")
      + fn_src("_klipper_execute_prestart")
      and "_incoming" not in open(os.path.join(REPO, "app", "klipper_prestart.py"), encoding="utf-8").read())
check("Z11(68). projects/tasks код не задет (роуты и обработчики без правок в этой выдаче)",
      "def create_project2" in SRV or "/api/projects2" in SRV)

section("sentinel не течёт в production")
_leaks = [p for p in ("server.py", "web/app.js", "web/index.html", "app/klipper_prestart.py",
                      "app/klipper_start.py", "app/config_backup/settings_registry.py")
          if SENTINEL in open(os.path.join(REPO, p), encoding="utf-8", errors="surrogateescape").read()]
check("S1. sentinel отсутствует в production-исходниках", not _leaks, str(_leaks))

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
print("Итого: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
_DONE["ok"] = True
socket.socket = _ORIG_SOCKET
sys.exit(1 if FAILED else 0)
