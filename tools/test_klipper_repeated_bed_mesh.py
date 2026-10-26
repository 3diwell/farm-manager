# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — ПОВТОРНАЯ КАЛИБРОВКА СТОЛА: выбранная галочка означает НОВЫЙ
#  замер перед КАЖДОЙ отдельной печатью, а не «когда-нибудь после включения».
#
#  ЧТО ЗАКРЫВАЕТ. Реальная приёмка на Creality K2 Plus: первая печать после
#  включения принтера физически снимала карту стола, вторая — уже нет, хотя
#  галочка «Калибровка стола» оставалась отмеченной, принтер не выключался, а
#  с собственного экрана K2 повторный замер выполнялся штатно.
#
#  ROOT CAUSE (доказан прогоном двух lifecycle через настоящий код server.py):
#  калибровку не отправлял НИКТО. file_control_reasons объявляла операцию
#  «управляемой файлом», если в шапке G-code встречался вызов стартового
#  макроса. START_PRINT стоит в шапке ЛЮБОГО файла из Creality Print, поэтому
#  резолвер уходил в MODE_FILE с commands=0 — молча, с успешным результатом и
#  без строки в журнале. Карту снимал сам принтер внутри BOX_START_PRINT, а тот
#  делает замер, только когда активной сетки нет: после включения — делал,
#  вторую печать подряд — уже нет.
#
#  ВТОРОЙ ДЕФЕКТ, найденный тем же прогоном: предстартовый гейт требовал
#  print_stats.state == "standby", а Klipper после завершённой печати держит
#  "complete". Вторая печать подряд с выбранной подготовкой отказывала целиком.
#
#  ЧЕСТНО О ГРАНИЦАХ. Живой K2 Plus здесь НЕ опрашивается (другой ПК, другая
#  сеть). Проверяется КОНТРАКТ на синтетической модели, воспроизводящей форму
#  ситуации из клиентского отчёта: bed_mesh есть, BED_MESH_CALIBRATE —
#  настоящий builtin, START_PRINT паркует оси и вызывает vendor-макрос, тело
#  которого недоступно. Сам клиентский отчёт в репозиторий не копировался.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * ни одного сетевого сокета: urllib подменён целиком (см. socket trap);
#   * server.py НЕ импортируется — функции извлекаются из AST и исполняются
#     в изолированном пространстве имён;
#   * реальному принтеру не отправляется НИ ОДНОЙ команды;
#   * файлы репозитория не изменяются.
#
#  Запуск:  python tools/test_klipper_repeated_bed_mesh.py    (0 = всё пройдено)
# ============================================================================
import ast
import io
import json
import os
import socket
import sys
import types

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" | " + str(extra)[:220]) if extra else ""))
    return ok


def section(t):
    print("\n--- %s ---" % t)


# ── Ловушка сокетов: ни один тест не имеет права выйти в сеть ────────────────
class _SocketTrap(socket.socket):
    def __init__(self, *a, **k):
        raise AssertionError("СЕТЕВОЙ ДОСТУП ЗАПРЕЩЁН: тест пытался открыть сокет")


_REAL_SOCKET = socket.socket
socket.socket = _SocketTrap

SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8",
              errors="surrogateescape").read()
SRV_AST = ast.parse(SRC)


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


def const_src(name):
    """Модульная константа server.py — читаем ИЗ ИСХОДНИКА, а не дублируем значение здесь:
    так мутация самого значения краснит тест, а не проходит незамеченной."""
    for n in SRV_AST.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.literal_eval(n.value)
    return None


# ════════════════════════════════════════════════════════════════════════════
#  Модель принтера: Creality K2 Plus по ФОРМЕ клиентского отчёта
# ════════════════════════════════════════════════════════════════════════════
BOX_UNKNOWN = object()          # тело vendor-макроса недоступно (как в отчёте v1)


class FakeK2(object):
    """Состояние принтера между запусками. Команды МЕНЯЮТ его, как на живом принтере."""

    def __init__(self, box_body=BOX_UNKNOWN, start_body=None):
        self.print_state = "standby"
        self.webhooks = "ready"
        self.homed = ""
        self.mesh = {}
        self.sent = []
        self.uploads = []
        self.timeout_on = set()          # скрипты, которые «зависнут» на чтении ответа
        self.box_body = box_body
        self.start_body = start_body if start_body is not None else (
            "BOX_START_PRINT\nG90\nG28\nSET_GCODE_OFFSET Z=0\n")

    # ── конфигурация ────────────────────────────────────────────────────────
    def macros(self):
        m = {"START_PRINT": self.start_body, "CANCEL_PRINT": "TURN_OFF_HEATERS\n"}
        if self.box_body is not BOX_UNKNOWN and self.box_body is not None:
            m["BOX_START_PRINT"] = self.box_body
        return m

    def builtins(self):
        # BOX_START_PRINT здесь НЕТ намеренно: на реальном K2 Plus это vendor gcode_macro, тело
        # которого клиентский отчёт не выгружал. Если внести его в /printer/gcode/help, он станет
        # ИЗВЕСТНЫМ листом графа, риск посчитается none — и проверка «недоказуемости» окажется
        # вакуумной, проходя по совсем другой ветке резолвера.
        return ["BED_MESH_CALIBRATE", "G28", "BED_MESH_PROFILE", "Z_TILT_ADJUST",
                "START_PRINT", "CANCEL_PRINT", "G90",
                "SET_GCODE_OFFSET", "M117", "TURN_OFF_HEATERS", "BED_MESH_CLEAR"]

    # ── жизненный цикл печати ───────────────────────────────────────────────
    def finish_print(self, post_state="complete"):
        """Печать закончилась. Принтер НЕ выключался: оси запаркованы, сетка активна."""
        self.print_state = post_state
        self.homed = "xyz"

    def calibrations(self):
        return [s for s in self.sent if "BED_MESH_CALIBRATE" in s.upper()]

    def homings(self):
        return [s for s in self.sent if s.strip().upper().startswith("G28")]


PR = [FakeK2()]                 # текущий принтер (список — чтобы менять из замыканий)


def _query(url):
    p = PR[0]
    if "/printer/objects/list" in url:
        return {"result": {"objects": ["configfile", "toolhead", "bed_mesh", "print_stats",
                                       "webhooks", "idle_timeout", "virtual_sdcard", "z_tilt"]}}
    if "/printer/gcode/help" in url:
        return {"result": {k: "desc" for k in p.builtins()}}
    if "configfile" in url:
        st = {"settings": {}}
        for k, v in p.macros().items():
            st["settings"]["gcode_macro " + k] = {"gcode": v}
        return {"result": {"status": {"configfile": st}}}
    if "/printer/info" in url:
        return {"result": {"software_version": "v0.12.0-synthetic"}}
    if "bed_mesh" in url:
        return {"result": {"status": {"bed_mesh": p.mesh}}}
    if "toolhead" in url:
        return {"result": {"status": {"toolhead": {"homed_axes": p.homed}}}}
    if "idle_timeout" in url:
        return {"result": {"status": {"idle_timeout": {"state": "Ready"}}}}
    if "print_stats" in url or "webhooks" in url:
        return {"result": {"status": {"print_stats": {"state": p.print_state},
                                      "webhooks": {"state": p.webhooks}}}}
    return {}


class _Resp(object):
    def __init__(self, b):
        self._b = b

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Request(object):
    def __init__(self, url, data=None, headers=None):
        self.full_url = url
        self.data = data


def _urlopen(req, timeout=None):
    import urllib.parse as up
    p = PR[0]
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if "/printer/gcode/script" in url:
        script = up.parse_qs(url.split("?", 1)[1]).get("script", [""])[0]
        p.sent.append(script)
        if script in p.timeout_on:
            raise TimeoutError("read timed out")     # ответ не пришёл: исход неизвестен
        if script.strip().upper().startswith("G28"):
            p.homed = "xyz"
        if "BED_MESH_CALIBRATE" in script.upper():
            n = len(p.calibrations())
            p.mesh = {"profile_name": "default", "mesh_min": [10, 10], "mesh_max": [200, 200],
                      "probed_matrix": [[0.01 * n, 0.02], [0.03, 0.04]]}
        return _Resp(b"{}")
    if "/server/files/upload" in url:
        p.uploads.append(len(req.data or b""))
        return _Resp(b'{"result": {"print_started": true}}')
    return _Resp(json.dumps(_query(url)).encode())


_fake_urllib = types.ModuleType("urllib")
_fake_urllib.request = types.SimpleNamespace(Request=_Request, urlopen=_urlopen)
import urllib.parse as _up                                            # noqa: E402
_fake_urllib.parse = _up
_fake_urllib.error = types.SimpleNamespace(HTTPError=Exception, URLError=Exception)


class _Log(object):
    def __init__(self):
        self.lines = []

    def _add(self, fmt, *a):
        try:
            self.lines.append(str(fmt) % a if a else str(fmt))
        except Exception:
            self.lines.append(str(fmt))

    info = warning = debug = error = _add


LOG = _Log()

from app import klipper_prestart as P                                 # noqa: E402
from app import klipper_contract_probe as KCP                         # noqa: E402
import time as _time                                                  # noqa: E402

NS = {"urllib": _fake_urllib, "json": json, "log": LOG, "_klprestart": P, "_kcprobe": KCP,
      "time": _time, "_exc_brief": (lambda: "err"),
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
    if kw.get("stage"):
        STAGES.append(kw["stage"])


# Шапка файла из Creality Print: START_PRINT есть ВСЕГДА. Именно она и ломала калибровку.
SLICER_HEAD = (b"; generated by Creality Print\n; printer_model = K2 Plus\n"
               b"START_PRINT BED_TEMP=60 EXTRUDER_TEMP=220\nG1 X0 Y0 F3000\n")
PLAIN_HEAD = b"; plain\nG1 X0 Y0 F3000\nG1 Z0.2\n"
EXPLICIT_HEAD = b"; explicit\nG28\nBED_MESH_CALIBRATE\nG1 X0 Y0\n"


def new_printer(**kw):
    PR[0] = FakeK2(**kw)
    LOG.lines[:] = []
    del STAGES[:]
    return PR[0]


def launch(fdata=SLICER_HEAD, sel=("bed_mesh_calibrate",), fname="part.gcode"):
    """Один явный запуск печати пользователем. → (ok, reason, отправленные за этот запуск)."""
    n0 = len(PR[0].sent)
    ok, why = run_pre("10.0.0.7", 7125, "pK2synthetic", list(sel), fname, fdata, progress_cb=_pcb)
    return ok, why, PR[0].sent[n0:]


# ════════════════════════════════════════════════════════════════════════════
section("A. Две печати подряд без выключения принтера — сценарий приёмки")

p = new_printer()
ok1, why1, cmd1 = launch()
check("A1. первая печать после включения разрешена", ok1 and why1 == "", why1[:120])
check("A2. первая печать: парковка и калибровка, ровно по одной",
      cmd1 == ["G28", "BED_MESH_CALIBRATE"], cmd1)
p.finish_print(post_state="complete")           # печать закончилась, принтер НЕ выключался
ok2, why2, cmd2 = launch()
check("A3. вторая печать разрешена, хотя принтер не перезапускался", ok2 and why2 == "",
      why2[:160])
check("A4. вторая печать ВЫПОЛНЯЕТ новую калибровку", cmd2 == ["BED_MESH_CALIBRATE"], cmd2)
check("A5. оси остались запаркованы -> второй G28 НЕ отправлялся", p.homings() == ["G28"],
      p.homings())
check("A6. ИТОГО за две печати: калибровок 2", len(p.calibrations()) == 2, p.calibrations())
check("A7. активная сетка от первой печати НЕ отменила вторую калибровку",
      bool(p.mesh) and len(p.calibrations()) == 2)
check("A8. состояние 'complete' после первой печати не считается занятостью",
      "не в покое" not in why2)

section("B. Тот же файл, другой файл, те же опции")

p = new_printer()
launch(fname="a.gcode"); p.finish_print()
launch(fname="a.gcode")
check("B1. ОДИН И ТОТ ЖЕ файл дважды -> калибровок 2 (запуск не считается повтором)",
      len(p.calibrations()) == 2, p.calibrations())

p = new_printer()
launch(fname="a.gcode"); p.finish_print()
launch(fname="b.gcode")
check("B2. разные файлы -> калибровок 2", len(p.calibrations()) == 2, p.calibrations())

p = new_printer()
launch(); p.finish_print(); launch(); p.finish_print(); launch()
check("B3. три печати подряд -> калибровок 3, парковка одна",
      len(p.calibrations()) == 3 and len(p.homings()) == 1,
      (p.calibrations(), p.homings()))

section("C. Одинаковый отпечаток сетки не отменяет факт калибровки")

p = new_printer()
launch()
_fp1 = KCP.mesh_fingerprint(p.mesh)["sha256"]
p.finish_print()
_frozen = dict(p.mesh)


def _freeze_urlopen(req, timeout=None):
    """Калибровка выполняется, но карта получается физически ТА ЖЕ (так бывает)."""
    r = _urlopen(req, timeout=timeout)
    PR[0].mesh = dict(_frozen)
    return r


_fake_urllib.request.urlopen = _freeze_urlopen
ok3, why3, cmd3 = launch()
_fake_urllib.request.urlopen = _urlopen
check("C1. отпечаток не изменился, но команда РЕАЛЬНО отправлена",
      "BED_MESH_CALIBRATE" in cmd3, cmd3)
check("C2. совпадение отпечатков не объявляется провалом калибровки", ok3, why3[:160])
check("C3. ИТОГО калибровок 2 при одинаковом отпечатке", len(p.calibrations()) == 2)

section("D. Кто выполняет калибровку — решается по доказательству, не по имени")

p = new_printer()
ok, why, cmd = launch(fdata=EXPLICIT_HEAD)
check("D1. файл САМ содержит BED_MESH_CALIBRATE -> вторую не шлём, печать разрешена",
      ok and cmd == [], (cmd, why[:120]))
check("D2. событие видно в журнале как file_controlled, а не молча",
      any("mode=file_controlled" in x for x in LOG.lines), LOG.lines[:3])

p = new_printer(box_body="M117 hi\n", start_body="BOX_START_PRINT\nG28\nBED_MESH_CALIBRATE\n")
ok, why, cmd = launch(fdata=SLICER_HEAD)
check("D3. ДОКАЗАНО, что стартовый макрос сам калибрует -> команд 0, печать разрешена",
      ok and cmd == [], (cmd, why[:120]))

p = new_printer(box_body="BED_MESH_CLEAR\n")
ok, why, cmd = launch(fdata=SLICER_HEAD)
check("D4. ДОКАЗАНО, что стартовый макрос очистит сетку -> печать НЕ начата, команд 0",
      (not ok) and cmd == [] and len(why) > 40, (cmd, why[:120]))

p = new_printer()                                   # BOX_START_PRINT недоступен
ok, why, cmd = launch(fdata=SLICER_HEAD)
check("D5. НЕДОКАЗУЕМО -> калибруем сами (иначе не калибрует никто)",
      ok and cmd == ["G28", "BED_MESH_CALIBRATE"], (cmd, why[:120]))
check("D6. причина названа в журнале явно",
      any("start_macro_unproven_self_calibrate" in x for x in LOG.lines), LOG.lines[:3])

section("E. Разбор шапки файла: имя стартового макроса ничего не решает")

check("E1. один лишь START_PRINT НЕ объявляет калибровку управляемой файлом",
      P.file_control_reasons(SLICER_HEAD.decode()) == {},
      P.file_control_reasons(SLICER_HEAD.decode()))
check("E2. явная команда в файле — по-прежнему основание",
      P.file_control_reasons(EXPLICIT_HEAD.decode()) == {"bed_mesh_calibrate": P.WHY_FILE_EXPLICIT})
check("E3. комментарий со словом START_PRINT ничего не меняет",
      P.file_control_reasons("; START_PRINT в printer.cfg\nG1 X0\n") == {})
check("E4. PRINT_START (второе распространённое имя) тоже не является доказательством",
      P.file_control_reasons("PRINT_START BED=60\n") == {})

section("F. Покой принтера: завершённая печать не считается занятостью")

_IDLE = const_src("_KLIPPER_IDLE_STATES")
check("F1. список покоя прочитан из server.py", isinstance(_IDLE, (list, tuple)) and _IDLE, _IDLE)
check("F2. 'complete' и 'cancelled' считаются покоем", "complete" in _IDLE and "cancelled" in _IDLE,
      _IDLE)
check("F3. 'printing' и 'paused' покоем НЕ считаются",
      "printing" not in _IDLE and "paused" not in _IDLE, _IDLE)
check("F4. пустая строка (нет данных) покоем НЕ считается", "" not in _IDLE, _IDLE)

for _st in ("standby", "complete", "cancelled"):
    p = new_printer()
    launch()
    p.finish_print(post_state=_st)
    ok, why, cmd = launch()
    check("F5[%s]. после печати в состоянии %r вторая калибровка выполняется" % (_st, _st),
          ok and cmd == ["BED_MESH_CALIBRATE"], (cmd, why[:120]))

p = new_printer()
p.print_state = "printing"
ok, why, cmd = launch()
check("F6. идущая печать не получает НИ ОДНОЙ команды", (not ok) and cmd == [], (cmd, why[:110]))
p = new_printer()
p.print_state = "paused"
ok, why, cmd = launch()
check("F7. приостановленная печать не получает НИ ОДНОЙ команды", (not ok) and cmd == [], cmd)

section("G. Неудача и неопределённость не переносятся на следующую печать")

p = new_printer()
p.timeout_on.add("BED_MESH_CALIBRATE")
ok, why, cmd = launch()
check("G1. таймаут калибровки -> печать НЕ начата", not ok, why[:120])
check("G2. загрузка файла не начиналась", p.uploads == [], p.uploads)
check("G3. команда повторно НЕ отправлялась (автоповтора нет)",
      len(p.calibrations()) == 1, p.calibrations())
check("G4. пользователю сказано проверить принтер перед повторной попыткой",
      "Проверьте принтер" in why and "НЕ отправлялась" in why, why[:200])
p.timeout_on.clear()
ok2, why2, cmd2 = launch()
check("G5. НОВЫЙ явный запуск после неопределённости выполняет калибровку заново",
      ok2 and cmd2 == ["BED_MESH_CALIBRATE"], (cmd2, why2[:120]))
check("G6. прошлая неудача не блокирует следующий запуск навсегда", ok2)

section("G2. Обычная операция плана тоже переживает вторую печать подряд")

# Калибровку исполняет отдельная ветка (_klipper_bed_mesh_attempt), а остальные выбранные
# операции — общий цикл плана со СВОЕЙ проверкой готовности после команды. Alpha 2.841 расширила
# понятие покоя в обоих местах; без этой сцены вторая проверка осталась бы недоказанной.
p = new_printer()
p.homed = "xyz"                      # общий план требует уже запаркованных осей: он их не паркует
ok, why, cmd = launch(sel=("z_tilt_adjust",))
check("G2a. первая печать выполняет обычную операцию плана",
      ok and cmd == ["Z_TILT_ADJUST"], (cmd, why[:120]))
p.finish_print(post_state="complete")
ok, why, cmd = launch(sel=("z_tilt_adjust",))
check("G2b. ВТОРАЯ печать подряд тоже её выполняет (состояние 'complete' не мешает)",
      ok and cmd == ["Z_TILT_ADJUST"], (cmd, why[:160]))

section("H. Стадии подготовки видны пользователю в КАЖДОМ запуске")

p = new_printer()
launch()
_first = list(STAGES)
p.finish_print()
del STAGES[:]
launch()
_second = list(STAGES)
check("H1. первая печать показывает стадии состояния/разбора/калибровки/проверки",
      all(s in _first for s in ("checking_state", "resolving", "calibrating", "verifying")),
      _first)
check("H2. вторая печать показывает стадии ЗАНОВО, а не остаётся в прошлой",
      all(s in _second for s in ("checking_state", "resolving", "calibrating", "verifying")),
      _second)
check("H3. во второй печати стадия парковки пропущена (оси уже запаркованы)",
      "homing" not in _second, _second)
check("H4. стадия «калибровка завершена» показана в обеих печатях",
      "calibration_done" in _first and "calibration_done" in _second)

section("I. Журнал: две печати — две отдельные цепочки")

_chains = [x for x in LOG.lines if "[KLIPPER PRESTART]" in x]
check("I1. вторая печать пишет собственный resolve",
      any("resolve" in x for x in _chains), _chains[:2])
check("I2. вторая печать пишет calibration begin и complete",
      any("calibration begin" in x for x in _chains)
      and any("calibration complete" in x for x in _chains), _chains[:4])
check("I3. в журнале нет ни адреса принтера, ни значений сетки",
      not any("10.0.0.7" in x for x in LOG.lines)
      and not any("probed_matrix" in x for x in LOG.lines))

section("J. Регрессия: предохранители и границы не сдвинулись")

_orch = io.open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
check("J1. DISPATCH_ENABLED остаётся False", "\nDISPATCH_ENABLED = False" in _orch)
check("J2. TRANSPORT_ENABLED остаётся False", "\nTRANSPORT_ENABLED = False" in _orch)
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
check("J3. модули не тронуты (Inventory/Cost/Quality)",
      all((lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(io.open(os.path.join(REPO, "modules", m, "module.json"),
                            encoding="utf-8"))) == v
          for m, v in (("inventory", "1.7.29"), ("cost", "0.2.0"), ("quality", "0.2.3"))))   # 3.0: cost — «Расчёт заказа»
_send_src = fn_src("_send_file_to_printer")
check("J4. загрузка файла происходит ПОСЛЕ подготовки, а не до",
      _send_src
      and "_klipper_execute_prestart" in _send_src
      and _send_src.index("_klipper_execute_prestart")
      < _send_src.index("/server/files/upload"))
# «retry» как СЛОВО встречается в тексте для пользователя («before retrying»), поэтому ищем не
# слово, а структуру: калибровочная команда отправляется ровно из ОДНОГО места, без цикла.
_att_ast = [n for n in ast.walk(SRV_AST)
            if isinstance(n, ast.FunctionDef) and n.name == "_klipper_bed_mesh_attempt"][0]
_sends = [n for n in ast.walk(_att_ast)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_send"]
_loops = [n for n in ast.walk(_att_ast) if isinstance(n, (ast.For, ast.While))]
check("J5. в попытке калибровки нет цикла и ровно две отправки (парковка + калибровка)",
      len(_sends) == 2 and _loops == [], (len(_sends), len(_loops)))
check("J6. ловушка сокетов не сработала (сети не было)", socket.socket is _SocketTrap)

socket.socket = _REAL_SOCKET

print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  RED: %s" % f)
sys.exit(1 if FAILED else 0)
