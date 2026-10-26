# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.838 — предстартовая калибровка: выбор пользователя обязан ДОЙТИ до
#  выполнения либо быть ЧЕСТНО объяснён.
#
#  ЧТО ЗАКРЫВАЕТ. Приёмка владельца на Creality K2 Plus: «галочка bed mesh стоит,
#  печать идёт, калибровки нет». Доказанный по коду корень (категория M — две
#  причины сразу):
#    1) диалог получает лист возможностей БЕЗ файла, поэтому file_controlled там
#       всегда false и флажок активен ВСЕГДА;
#    2) при запуске операция могла быть отброшена (file_controlled / недоказанность),
#       после чего _klipper_execute_prestart возвращал (True, "") МОЛЧА — ни строки
#       в журнале, ни слова пользователю, печать продолжалась.
#  Плюс третья, отдельно доказанная слабость: наличие команды в gcode/help считалось
#  достаточным доказательством выполнимости, хотя одноимённый gcode_macro принтера
#  может делать что угодно.
#
#  ЧЕСТНО О ГРАНИЦАХ. Живая read-only разведка реального K2 Plus в этой выдаче НЕ
#  выполнялась (принтер на другом компьютере и в другой сети). Поэтому здесь НЕ
#  проверяется, какой именно макрос у K2 Plus: проверяется КОНТРАКТ — что при
#  недоказанной операции Farm Manager не обещает её выполнить и не начинает печать
#  молча. Снятие реального контракта — tools/klipper_probe.py на рабочем ПК.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется: функции берутся разбором AST и исполняются изолированно;
#   * ни одного реального сетевого сокета: urllib подменён fake-Moonraker'ом;
#   * ловушка запрещает любой адрес, кроме синтетического;
#   * реальному принтеру не отправляется НИ ОДНОЙ команды (счётчик проверяется);
#   * рабочие БД/config/DATA_DIR не открываются; печати не запускаются.
#
#  Запуск:  python tools/test_k2_plus_bed_mesh_prestart.py    (0 = всё пройдено)
# ============================================================================
import ast
import io
import json
import os
import re
import sys
import types
import urllib.error as _urlerr
import urllib.parse as _urlparse
import urllib.request as _urlreq

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "K2_BED_MESH_PRESTART_SENTINEL_2_838"   # ТОЛЬКО в этой оснастке
FAKE_HOST = "127.0.0.1"                            # синтетический адрес fake-Moonraker

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" | " + str(extra)[:200]) if extra else ""))
    return ok


def section(t):
    print("\n--- %s ---" % t)


SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
ORCH = io.open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
FIX = json.load(io.open(os.path.join(REPO, "tools", "fixtures", "klipper",
                                     "k2_plus_prestart_contract.json"), encoding="utf-8"))


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


from app import klipper_prestart as P  # noqa: E402

print("=== Alpha 2.838: предстартовая калибровка Klipper — контракт доказательства ===")
print("МЕТКА ОСНАСТКИ: %s" % SENTINEL)

# ════════════════════════════════════════════════════════════════════════════
section("A. Уровни доказательства (ЭТАП 6)")

check("A1. пять уровней объявлены и различимы",
      len({P.STATE_UNSUPPORTED, P.STATE_DETECTED, P.STATE_MANUAL,
           P.STATE_AUTOMATIC, P.STATE_FILE_CONTROLLED}) == 5)

_scen = {s["name"]: s for s in FIX["scenarios"]}


def sheet_of(name):
    s = _scen[name]
    return P.discover_capabilities(s["objects"], s["gcode_commands"], s["config_macros"])


_bm = lambda sh: {c["id"]: c for c in sh["capabilities"]}["bed_mesh_calibrate"]   # noqa: E731

check("A2. штатный Klipper: встроенная команда + объект -> supported_automatic",
      _bm(sheet_of("stock_klipper"))["state"] == P.STATE_AUTOMATIC
      and _bm(sheet_of("stock_klipper"))["source"] == P.SRC_BUILTIN)
check("A3. vendor-переопределение: тот же набор команд -> supported_manual, НЕ автомат",
      _bm(sheet_of("vendor_override"))["state"] == P.STATE_MANUAL
      and _bm(sheet_of("vendor_override"))["state_reason"] == P.WHY_VENDOR_OVERRIDE
      and _bm(sheet_of("vendor_override"))["vendor_override"] is True)
check("A4. недоказанная команда не становится автоматической",
      _bm(sheet_of("unsupported"))["state"] == P.STATE_UNSUPPORTED)
check("A5. команда есть, объекта нет -> detected (справочно, не автомат)",
      _bm(P.discover_capabilities([], ["BED_MESH_CALIBRATE"], []))["state"] == P.STATE_DETECTED)
check("A6. ручная операция остаётся supported_manual даже при полных доказательствах",
      {c["id"]: c for c in P.discover_capabilities(
          ["screws_tilt_adjust"], ["SCREWS_TILT_CALCULATE"], [])["capabilities"]
       }["screws_tilt"]["state"] == P.STATE_MANUAL)
check("A7. прежние поля контракта СОХРАНЕНЫ (supported/auto_execute/safe_each_print/file_controlled)",
      all(k in _bm(sheet_of("stock_klipper"))
          for k in ("supported", "auto_execute", "safe_each_print", "file_controlled", "default")))

# ════════════════════════════════════════════════════════════════════════════
section("B. Разбор начала файла: комментарий больше не «управляет» операцией")

# ── Alpha 2.841. ROOT CAUSE реальной приёмки ─────────────────────────────────────────────
# Прежде здесь проверялось обратное: вызов START_PRINT объявлял калибровку «управляемой файлом».
# Основанием служило ОДНО ИМЯ. На реальном K2 Plus START_PRINT стоит в шапке любого файла из
# Creality Print, поэтому Farm Manager не отправлял калибровку НИ РАЗУ — ни в первую печать, ни
# во вторую, молча и с успешным результатом. Карту снимал сам принтер внутри BOX_START_PRINT, а
# тот делает замер, только когда активной сетки нет: после включения — делал, вторую печать
# подряд — уже нет. Что делает стартовый макрос, теперь решается по графу вызовов (раздел «риск»).
check("B1(2.841). один лишь вызов START_PRINT НЕ объявляет калибровку управляемой файлом",
      P.file_control_reasons("START_PRINT BED_TEMP=60\n") == {},
      P.file_control_reasons("START_PRINT BED_TEMP=60\n"))
check("B2. КОММЕНТАРИЙ со словом START_PRINT больше не управляет (корень ложного пропуска)",
      P.file_control_reasons("; START_PRINT задаётся в printer.cfg\nG1 X0\n") == {})
check("B3. base64-миниатюра слайсера не считается вызовом",
      P.file_control_reasons("; thumbnail begin\n; iVBORSTART_PRINTw0KGgo=\n; thumbnail end\n") == {})
check("B4. явный вызов BED_MESH_CALIBRATE распознан как file_explicit_call",
      P.file_control_reasons("G28\nBED_MESH_CALIBRATE\n") == {"bed_mesh_calibrate": P.WHY_FILE_EXPLICIT})
check("B5. analyze_gcode_start сохраняет ПРЕЖНИЙ контракт (множество id)",
      P.analyze_gcode_start("BED_MESH_CALIBRATE\n") == {"bed_mesh_calibrate"}
      and P.analyze_gcode_start("START_PRINT\n") == set()
      and P.analyze_gcode_start("") == set())
check("B7. имя команды как АРГУМЕНТ строки не считается её вызовом",
      P.file_control_reasons("SET_GCODE_VARIABLE MACRO=BED_MESH_CALIBRATE VARIABLE=x VALUE=1\n") == {}
      and P.file_control_reasons("M117 BED_MESH_CALIBRATE next\n") == {}
      and P.file_control_reasons("BED_MESH_CALIBRATE\n") == {"bed_mesh_calibrate": P.WHY_FILE_EXPLICIT})
check("B6. merge_file_controlled переводит состояние в file_controlled с причиной",
      (lambda sh: (_bm(sh)["state"] == P.STATE_FILE_CONTROLLED
                   and _bm(sh)["state_reason"] == P.WHY_FILE_EXPLICIT
                   and _bm(sh)["source"] == P.SRC_FILE))(
          P.merge_file_controlled(sheet_of("file_controlled"),
                                  P.file_control_reasons(_scen["file_controlled"]["gcode_head"]))))

# ════════════════════════════════════════════════════════════════════════════
section("C. Судьба галочки видна всегда (ЭТАП 8)")

for name in ("stock_klipper", "vendor_override", "unsupported"):
    sh = sheet_of(name)
    exp = _scen[name]["expected_plan"]
    got_plan = P.build_prestart_plan(sh, exp["selected"])
    got_disp = P.plan_dispositions(sh, exp["selected"])
    check("C[%s]. план и судьба выбора совпадают с фикстурой" % name,
          got_plan == exp["commands"]
          and [(d["id"], d["disposition"], d["state"], d["reason"]) for d in got_disp]
          == [(d["id"], d["disposition"], d["state"], d["reason"]) for d in exp["dispositions"]],
          (got_plan, got_disp))

_fc = P.merge_file_controlled(sheet_of("file_controlled"),
                              P.file_control_reasons(_scen["file_controlled"]["gcode_head"]))
check("C[file_controlled]. план пуст, судьба — skipped/file_controlled",
      P.build_prestart_plan(_fc, ["bed_mesh_calibrate"]) == []
      and P.plan_dispositions(_fc, ["bed_mesh_calibrate"])[0]["state"] == P.STATE_FILE_CONTROLLED)
check("C-EXTRA. неизвестный id виден как skipped/unknown_option (а не исчезает)",
      P.plan_dispositions(sheet_of("stock_klipper"), ["G28 ; raw"])[0]["reason"] == "unknown_option")
check("C-HOMED. предусловие парковки объявлено ровно для операций, которым оно нужно",
      P.requires_homed(["bed_mesh_calibrate"]) and P.requires_homed(["z_tilt_adjust"])
      and not P.requires_homed(["clean_nozzle"]) and not P.requires_homed([]))

# ════════════════════════════════════════════════════════════════════════════
section("D. FAKE-MOONRAKER E2E: команда одна, upload только после завершения (ЭТАП 14)")

# Alpha 2.840: калибровка стола подтверждается ещё и состоянием bed_mesh — сцена его отдаёт
# и «измеряет» сетку при выполнении команды.
SC = {"state": "standby", "wh": "ready", "homed": "xyz", "reachable": True,
      "cmd_fail": None, "post_state": None, "objects": [], "cmds": [], "macros": [],
      "sent": [], "gets": [], "uploads": [], "idle": "Ready",
      "mesh": {"profile_name": "default", "probed_matrix": [[0.0, 0.1], [0.2, 0.3]]}}


class _FR(object):
    def __init__(self, b): self._b = b
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _fake_urlopen(req, timeout=None):
    url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
    host = _urlparse.urlparse(url).hostname or ""
    if host != FAKE_HOST:                      # ловушка: наружу — никогда
        raise AssertionError("тест попытался обратиться к постороннему адресу: %s" % host)
    if "/server/files/upload" in url:
        SC["uploads"].append(url)
        return _FR(b'{"result": {"print_started": true}}')
    if not SC["reachable"]:
        raise _urlerr.URLError("unreachable")
    if "/printer/gcode/script" in url:
        _s = _urlparse.unquote(url.split("script=")[-1])
        SC["sent"].append(_s)
        if "BED_MESH_CALIBRATE" in _s:          # «измерили» стол: сетка изменилась
            SC["mesh"] = {"profile_name": "default", "probed_matrix": [[9.0, 9.1], [9.2, 9.3]]}
        if _s.upper().startswith("G28"):
            SC["homed"] = "xyz"
        if SC["cmd_fail"] == "http":
            raise _urlerr.HTTPError(url, 400, "err", {}, io.BytesIO(b"{}"))
        if SC["cmd_fail"] == "timeout":
            raise TimeoutError("timed out")
        if SC["post_state"] is not None:      # "" — тоже сценарий: «данных о состоянии нет»
            SC["state"] = SC["post_state"]
        return _FR(b'{"result": "ok"}')
    SC["gets"].append(url)
    if "/printer/objects/list" in url:
        return _FR(json.dumps({"result": {"objects": SC["objects"]}}).encode())
    if "/printer/gcode/help" in url:
        return _FR(json.dumps({"result": {c: "" for c in SC["cmds"]}}).encode())
    if "configfile" in url:
        return _FR(json.dumps({"result": {"status": {"configfile": {"settings": {
            ("gcode_macro " + m.lower()): {} for m in SC["macros"]}}}}}).encode())
    if "/printer/info" in url:
        return _FR(json.dumps({"result": {"software_version": "v0.12.0"}}).encode())
    if "/server/info" in url:
        return _FR(json.dumps({"result": {"moonraker_version": "v0.9.3"}}).encode())
    if "bed_mesh" in url:
        return _FR(json.dumps({"result": {"status": {"bed_mesh": SC["mesh"]}}}).encode())
    if "idle_timeout" in url:
        return _FR(json.dumps({"result": {"status": {"idle_timeout": {"state": SC["idle"]}}}}).encode())
    if "toolhead" in url:
        return _FR(json.dumps({"result": {"status": {"toolhead": {"homed_axes": SC["homed"]}}}}).encode())
    if "print_stats" in url:
        return _FR(json.dumps({"result": {"status": {"print_stats": {"state": SC["state"]},
                                                     "webhooks": {"state": SC["wh"]}}}}).encode())
    return _FR(b"{}")


_fake_urllib = types.SimpleNamespace(
    request=types.SimpleNamespace(Request=_urlreq.Request, urlopen=_fake_urlopen),
    error=_urlerr, parse=_urlparse)


class _Log(object):
    def __init__(self): self.lines = []
    def _r(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = exception = _r


LOG = _Log()
from app import klipper_contract_probe as KCP   # noqa: E402  (чистое ядро, без сети)
NS = {"urllib": _fake_urllib, "json": json, "log": LOG, "_klprestart": P, "_kcprobe": KCP,
      "time": __import__("time"), "_exc_brief": (lambda: "err"),
      "_KLIPPER_IDLE_STATES": const_src("_KLIPPER_IDLE_STATES")}
for _f in ("_klipper_get_json", "_klipper_discover", "_klipper_config_macros",
           "_klipper_bed_mesh_attempt", "_klipper_execute_prestart"):
    _s = fn_src(_f)
    if not _s:
        print("FAIL — функция %s не найдена в server.py" % _f)
        sys.exit(1)
    exec(compile(_s, "<server>", "exec"), NS)
run_pre = NS["_klipper_execute_prestart"]

STAGES = []


def _pcb(**kw):
    STAGES.append(kw.get("stage"))


def scen(name, **kw):
    s = _scen[name]
    SC.update({"state": "standby", "wh": "ready", "homed": "xyz", "reachable": True,
               "cmd_fail": None, "post_state": None, "sent": [], "gets": [], "uploads": [],
               "idle": "Ready",
               "mesh": {"profile_name": "default", "probed_matrix": [[0.0, 0.1], [0.2, 0.3]]},
               "objects": list(s["objects"]), "cmds": list(s["gcode_commands"]),
               "macros": list(s["config_macros"])})
    SC.update(kw)
    STAGES[:] = []
    LOG.lines[:] = []


# 1. Штатный Klipper: ровно одна команда, стадии показаны, потом можно печатать.
scen("stock_klipper")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "part.gcode",
                  b"G1 X0\n", progress_cb=_pcb)
check("D1. калибровка выполнена ДО печати и печать разрешена", ok and why == "")
check("D2. отправлена РОВНО ОДНА команда, и это команда из реестра",
      SC["sent"] == ["BED_MESH_CALIBRATE"], SC["sent"])
check("D3. загрузка файла НЕ начиналась внутри подготовки", SC["uploads"] == [])
# Alpha 2.840: стадии стали точнее — разбор контракта, калибровка и проверка результата.
check("D4. пользователю показаны стадии разбора, калибровки и проверки",
      "resolving" in STAGES and "calibrating" in STAGES and "verifying" in STAGES, STAGES)
check("D5. журнал содержит resolve/plan/calibration begin/calibration complete",
      any("[KLIPPER PRESTART] resolve" in x for x in LOG.lines)
      and any("[KLIPPER PRESTART] plan" in x for x in LOG.lines)
      and any("[KLIPPER PRESTART] calibration begin" in x for x in LOG.lines)
      and any("[KLIPPER PRESTART] calibration complete" in x for x in LOG.lines), LOG.lines[:4])
check("D6. в журнале нет адреса принтера и нет метки оснастки",
      not any(FAKE_HOST in x for x in LOG.lines) and not any(SENTINEL in x for x in LOG.lines))

# 2. HTTP-ответ есть, но принтер не вернулся в покой → печать НЕ начинается.
scen("stock_klipper", post_state="printing")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "part.gcode", b"", progress_cb=_pcb)
check("D7. HTTP-ответ НЕ считается завершением: принтер не в готовности -> печать блокирована",
      (not ok) and "не начата" in why and SC["uploads"] == [])

# 2b. Пустое состояние больше не проходит как доказательство покоя.
scen("stock_klipper", post_state="")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "part.gcode", b"", progress_cb=_pcb)
check("D8. отсутствие данных о состоянии НЕ считается доказательством завершения", not ok)

# 3. Ошибка калибровки → печать не начинается.
scen("stock_klipper", cmd_fail="http")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "part.gcode", b"", progress_cb=_pcb)
check("D9. ошибка калибровки блокирует печать", (not ok) and SC["uploads"] == []
      and any("[KLIPPER PRESTART] calibration failed" in x for x in LOG.lines))

# 4. Timeout → uncertain: не повторяем и не печатаем.
scen("stock_klipper", cmd_fail="timeout")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "part.gcode", b"", progress_cb=_pcb)
check("D10. timeout -> печать не начата, макрос НЕ повторён, состояние uncertain",
      (not ok) and len(SC["sent"]) == 1 and "повторно НЕ отправлялась" in why
      and any("[KLIPPER PRESTART] calibration uncertain" in x for x in LOG.lines), why[:120])

# 5. Занятый принтер / не готов / офлайн — команд нет вовсе.
scen("stock_klipper", state="printing")
ok, _ = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "f.gcode", b"", progress_cb=_pcb)
check("D11. активная печать не получает калибровку", (not ok) and SC["sent"] == [])
scen("stock_klipper", wh="shutdown")
ok, _ = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "f.gcode", b"", progress_cb=_pcb)
check("D12. Klipper не готов -> команд нет", (not ok) and SC["sent"] == [])
scen("stock_klipper", reachable=False)
ok, _ = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "f.gcode", b"", progress_cb=_pcb)
check("D13. принтер офлайн -> команд нет и печать блокирована", (not ok) and SC["sent"] == [])

# 6. Незапаркованные оси: проверяем предусловие, но G28 НЕ шлём.
# Alpha 2.840: незапаркованные оси больше не тупик. Доказанный контракт (встроенная
# BED_MESH_CALIBRATE, G28 не переопределён) разрешает РОВНО ОДНУ полную парковку —
# и только после её подтверждения идёт калибровка.
scen("stock_klipper", homed="")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "f.gcode", b"", progress_cb=_pcb)
check("D14. оси не запаркованы -> РОВНО один G28, затем калибровка, печать разрешена",
      ok and SC["sent"] == ["G28", "BED_MESH_CALIBRATE"]
      and any("[KLIPPER PRESTART] home complete" in x for x in LOG.lines), SC["sent"])
scen("stock_klipper", homed="xy")
ok, _ = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "f.gcode", b"", progress_cb=_pcb)
check("D15. частичная парковка достраивается одним полным G28 (а не считается парковкой)",
      ok and SC["sent"] == ["G28", "BED_MESH_CALIBRATE"], SC["sent"])
scen("stock_klipper")            # уже запаркован
ok, _ = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "f.gcode", b"", progress_cb=_pcb)
check("D15b. при запаркованных осях G28 НЕ отправляется",
      ok and SC["sent"] == ["BED_MESH_CALIBRATE"], SC["sent"])
scen("stock_klipper", homed="")
ok, _ = run_pre(FAKE_HOST, 7125, "pK2fixture", ["clean_nozzle"], "f.gcode", b"", progress_cb=_pcb)
check("D16. операции, которой парковка не нужна, отсутствие парковки не мешает",
      ok and SC["sent"] == ["CLEAN_NOZZLE"])

# 7. vendor-переопределение: печать не начинается, команда не уходит.
scen("vendor_override")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "f.gcode", b"", progress_cb=_pcb)
# Alpha 2.840: объяснение стало точнее — resolver называет ПРИЧИНУ (команда переопределена),
# а не общую формулу. Инвариант прежний: команда не уходит, печать не начинается.
check("D17. переопределённая макросом команда НЕ выполняется автоматически и печать блокирована",
      (not ok) and SC["sent"] == []
      and ("переопределена" in why or "не может быть выполнена автоматически" in why)
      and "не начата" in why)

# 8. Файл управляет операцией: команды нет, печать идёт, событие в журнале.
scen("file_controlled")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["bed_mesh_calibrate"], "f.gcode",
                  _scen["file_controlled"]["gcode_head"].encode(), progress_cb=_pcb)
check("D18. операция файла не дублируется: команд 0, печать разрешена, событие записано",
      ok and SC["sent"] == []
      and any("mode=file_controlled" in x for x in LOG.lines), LOG.lines[:3])

# 9. Сырой G-code и произвольный макрос от клиента.
scen("stock_klipper")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", ["BED_MESH_CALIBRATE", "G28", "EVIL_MACRO"],
                  "f.gcode", b"", progress_cb=_pcb)
check("D19. сырой G-code/имя макроса от клиента: команд 0 и печать блокирована",
      (not ok) and SC["sent"] == [])

# 10. Пустой выбор — прежний путь байт-в-байт.
scen("stock_klipper")
ok, why = run_pre(FAKE_HOST, 7125, "pK2fixture", [], "f.gcode", b"", progress_cb=_pcb)
check("D20. пустой выбор ничего не меняет (совместимость со всеми прежними вызовами)",
      ok and SC["sent"] == [] and why == "")

# ════════════════════════════════════════════════════════════════════════════
section("E. Границы: backend — authority, клиент не диктует команды")

_ex = fn_src("_klipper_execute_prestart")
check("E1. текст клиента в команду не превращается: строка берётся из реестра",
      "build_prestart_plan" in _ex and "selected_ids" in _ex
      and not re.search(r"script['\"]?\s*:\s*[^)]*selected", _ex))
check("E2. молчаливый успех при отброшенном выборе невозможен",
      "plan_dispositions" in _ex and "_skipped_other" in _ex)
check("E3. Farm Manager не отправляет G28 сам ни при каких условиях",
      '"G28"' not in _ex and "'G28'" not in _ex)
check("E4. подготовка идёт ДО загрузки файла",
      (lambda s: s.find("_klipper_execute_prestart") < s.find("/server/files/upload"))(
          fn_src("_send_file_to_printer")))
check("E5. discovery остаётся read-only (в нём нет gcode/script)",
      "gcode/script" not in fn_src("_klipper_discover"))
check("E6. сбой подготовки возвращает ошибку ДО загрузки файла (печать не начинается)",
      (lambda s: "if not _ok_pre:" in s
       and s.find("if not _ok_pre:") < s.find("/server/files/upload"))(fn_src("_send_file_to_printer")))
check("E7. предпочтения читаются СТРОГО по id принтера (чужие не применяются)",
      "_klipper_prefs_all().get(str(pid)) or {}" in fn_src("get_klipper_prestart"))

# ════════════════════════════════════════════════════════════════════════════
section("F. Интерфейс: активная галочка только при полном контракте (ЭТАП 9)")

check("F1. флажок неактивен для всего, кроме supported_automatic",
      ':disabled="c.state !== \'supported_automatic\'"' in HTML)
check("F2. в запрос уходят ТОЛЬКО операции уровня supported_automatic",
      "c && c.state === 'supported_automatic' && c.supported && !c.file_controlled" in APPJS
      and "klipper_prestart: ids" in APPJS)
check("F3. причина неактивности показана пользователю (klCapNote)",
      "{{ klCapNote(c) }}" in HTML and "const klCapNote" in APPJS
      and "klCapNote," in APPJS)
# Alpha 2.840: формулировки подписи ИЗМЕНЕНЫ намеренно — теперь она называет источник
# автоматического пути, а всё недоказанное подписано единым «путь не подтверждён».
check("F4. RU: названы все четыре источника автоматического пути",
      all(s in APPJS for s in ("Управляется стартовым макросом или файлом",
                               "Автоматический путь не подтверждён: ",
                               "команда переопределена макросом принтера и выполняется только вручную",
                               "Встроенная команда Klipper — выполнится до отправки файла",
                               "Макрос принтера — выполнится до отправки файла")))
check("F5. EN: те же состояния переведены",
      all(s in APPJS for s in ("Controlled by the start macro or the file",
                               "The automatic path is not confirmed: ",
                               "the command is overridden by a printer macro and can only be run manually",
                               "Klipper built-in — runs before the file is sent",
                               "Printer macro — runs before the file is sent")))
check("F6. стадии подготовки видны в панели отправок (RU и EN)",
      "Калибровка стола…" in APPJS and "Bed mesh calibration…" in APPJS
      and "Ожидание завершения калибровки…" in APPJS
      and "Waiting for calibration to finish…" in APPJS)
check("F7. пояснение про неактивную галочку есть на обоих языках",
      "Неактивная галочка означает" in HTML and "A greyed-out checkbox means" in HTML)
check("F8. «Отмена» диалога не запускает печать и не шлёт команд",
      "const closePrintStart = () => { if (printStart.value.open) printStart.value = "
      "Object.assign({}, printStart.value, { open: false, onConfirm: null }); };" in APPJS)
check("F9. окно закрывается ДО вызова onConfirm (двойное подтверждение невозможно)",
      (lambda s: s.find("{ open: false, onConfirm: null }") < s.find("if (cb) cb(opts, srcSlot)"))(
          APPJS[APPJS.index("const confirmPrintStart"):APPJS.index("const printStartTypeLabel")]))
check("F10. c1 (файл уже на принтере) предстартовые операции не применяет",
      "if (caps.klipper && !ctx.c1)" in APPJS)

# ════════════════════════════════════════════════════════════════════════════
section("G. Регрессии и предохранители")

check("G1. подтверждение запуска Klipper 2.833 сохранено",
      "pending_confirmation" in SRV and "waiting_confirmation" in SRV
      and os.path.exists(os.path.join(REPO, "app", "klipper_start.py")))
check("G2. Bambu-опции запуска сохранены (whitelist)",
      "_apply_bambu_print_opts" in SRV and "extrude_cali_flag" in SRV)
check("G3. FlashForge-запуск сохранён", "/uploadGcode" in SRV and "gcodeFile" in SRV)
check("G4. «Сеть и доступ» 2.837 сохранена",
      "enable_blocked_reason" in SRV and "change_allowed" in SRV)
check("G5. DISPATCH_ENABLED = False", re.search(r"^DISPATCH_ENABLED = False$", ORCH, re.M) is not None)
check("G6. TRANSPORT_ENABLED = False", re.search(r"^TRANSPORT_ENABLED = False$", ORCH, re.M) is not None)
check("G7. удаление файлов принтера остаётся выключенным",
      "PRINTER_FILE_DELETE_ENABLED_DEFAULT = False" in
      io.open(os.path.join(REPO, "app", "printer_files", "security.py"), encoding="utf-8").read())
#  Alpha 2.891: складской модуль поднят до 1.7.28 (слоты CFS у Creality K2).
#  Смысл проверки прежний: ЭТА подсистема модули не трогает.
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
check("G8. модули не тронуты этой подсистемой (версии закреплены)",
      all((lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(io.open(os.path.join(REPO, "modules", m, "module.json"), encoding="utf-8"))) == v
          for m, v in (("inventory", "1.7.29"), ("cost", "0.2.0"), ("quality", "0.2.3"))))   # 3.0: cost — «Расчёт заказа»
check("G9. `_incoming/` продуктовым кодом не используется",
      not any(t in SRV for t in ('"_incoming"', "'_incoming'", "_incoming/")))
check("G10. метка оснастки НЕ попала в продуктовые файлы",
      SENTINEL not in SRV and SENTINEL not in APPJS and SENTINEL not in HTML
      and SENTINEL not in io.open(os.path.join(REPO, "app", "klipper_prestart.py"),
                                  encoding="utf-8").read())
check("G11. фикстура обезличена: ни адресов, ни токенов, ни реального G-code",
      not re.search(r"(?i)(token|api[_-]?key|serial|password)", json.dumps(FIX, ensure_ascii=False))
      and not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", json.dumps(FIX)))
check("G12. фикстура ЧЕСТНО помечена как неподтверждённая живой разведкой",
      all(s.get("confirmed") is False for s in FIX["scenarios"])
      and bool(FIX.get("open_questions_for_real_printer")))
_PROBE_P = os.path.join(REPO, "tools", "klipper_probe.py")
_PROBE = io.open(_PROBE_P, encoding="utf-8").read() if os.path.exists(_PROBE_P) else ""
_PROBE_AST = ast.parse(_PROBE) if _PROBE else None
# Доказательство «инструмент только читает» строим по КОДУ, а не по тексту: единственный
# запрос собирается с method="GET", тело никогда не передаётся, а список путей закрыт и
# не содержит исполняющих эндпоинтов.
# Alpha 2.839: CLI стал ТОНКОЙ ОБЁРТКОЙ — allowlist переехал в production-ядро
# app/klipper_contract_probe.py, и берётся он оттуда же. Список читаем из ядра.
_CORE_P = os.path.join(REPO, "app", "klipper_contract_probe.py")
_CORE_AST = ast.parse(io.open(_CORE_P, encoding="utf-8").read()) if os.path.exists(_CORE_P) else None
_probe_paths = []
if _CORE_AST:
    for n in ast.walk(_CORE_AST):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ALLOWED_PATHS" for t in n.targets):
            _probe_paths = [e.value for e in getattr(n.value, "elts", []) if isinstance(e, ast.Constant)]
_probe_calls = [n for n in ast.walk(_PROBE_AST or ast.parse(""))
                if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("Request")]
check("G13. read-only разведчик существует и по построению не умеет отправлять команды",
      bool(_PROBE) and bool(_probe_paths) and "klipper_contract_probe" in _PROBE
      and all("script" not in p for p in _probe_paths)
      and all(any(k.arg == "method" and getattr(k.value, "value", "") == "GET" for k in c.keywords)
              for c in _probe_calls)
      and all(not any(k.arg == "data" for k in c.keywords) for c in _probe_calls),
      (_probe_paths[:2], len(_probe_calls)))
check("G14. реальному принтеру за весь прогон не отправлено ни одной команды",
      all(_urlparse.urlparse(u).hostname in (FAKE_HOST, None) for u in SC["gets"]))
check("G15. артефакт _e2e_payload.json не создан",
      not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
