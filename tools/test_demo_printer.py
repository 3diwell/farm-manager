# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.970 — виртуальный принтер (тип "demo"): часовой автомат и его проводка.

ЗАЧЕМ. Владелец просил принтер, на котором можно ПО-НАСТОЯЩЕМУ запускать файлы и смотреть,
что делает программа. Ценность такой проверки держится на одном условии: виртуальный принтер
должен проходить ТЕ ЖЕ механизмы, что и настоящий, а не подменять их. Если он начнёт считать
количество сам или обходить очередь и склад — проверка на нём будет проверять его самого.

Здесь проверяется:
  * сроки, заданные владельцем: 10 секунд стол, 10 сопло, 20 печать, потом готово;
  * цели нагрева берутся из файла, потом с пульта, и только потом по умолчанию;
  * пауза останавливает часы задания, остановка заканчивает его без печати;
  * состояние отдаётся в том же виде, что у настоящих адаптеров (те же поля и единицы);
  * ядро НЕ переписано: количество считает handle_state на FINISH, как у всех;
  * сети у принтера нет — модуль не умеет её открывать.

БЕЗОПАСНОСТЬ: production server.py не импортируется (правило проекта). Проверяется чистый
модуль app/demo_printer.py и текст проводки в server.py.

Запуск:  python tools/test_demo_printer.py
"""
import importlib.util
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("fm_demo_printer_test",
                                              os.path.join(ROOT, "app", "demo_printer.py"))
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)

SENTINEL = "DEMO_PRINTER_SENTINEL_2_970"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
POL = io.open(os.path.join(ROOT, "app", "printer_command_policy.py"), encoding="utf-8").read()
MOD = io.open(os.path.join(ROOT, "app", "demo_printer.py"), encoding="utf-8").read()
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()

print("--- 1. сроки, заданные владельцем ---")
check("1. 10 секунд стол, 10 сопло, 20 печать — всего 40",
      (dp.BED_S, dp.NOZZLE_S, dp.PRINT_S, dp.TOTAL_S) == (10.0, 10.0, 20.0, 40.0),
      (dp.BED_S, dp.NOZZLE_S, dp.PRINT_S, dp.TOTAL_S))

dp.forget("p1")
dp.start("p1", "korpus.gcode", None, 1000.0)


def at(t, pid="p1"):
    return dp.state(pid, 1000.0 + t)


phases = [(0.0, "PREPARE", "heating_bed"), (5.0, "PREPARE", "heating_bed"),
          (9.9, "PREPARE", "heating_bed"), (10.1, "PREPARE", "heating_nozzle"),
          (19.9, "PREPARE", "heating_nozzle"), (20.1, "RUNNING", "printing"),
          (39.9, "RUNNING", "printing"), (40.1, "FINISH", "finish"), (300.0, "FINISH", "finish")]
check("2. состояния идут по срокам: стол, сопло, печать, готово",
      all(at(t)["status"] == st and at(t)["status_raw"] == raw for t, st, raw in phases),
      [(t, at(t)["status"], at(t)["status_raw"]) for t, st, raw in phases if at(t)["status"] != st])
check("3. стол греется первым, сопло стоит холодным и наоборот",
      at(5.0)["bed_temp"] > dp.AMBIENT_C and at(5.0)["nozzle_temp"] == dp.AMBIENT_C
      and at(15.0)["bed_temp"] == dp.BED_DEFAULT_C and at(15.0)["nozzle_temp"] > dp.AMBIENT_C,
      (at(5.0)["bed_temp"], at(5.0)["nozzle_temp"], at(15.0)["bed_temp"], at(15.0)["nozzle_temp"]))
check("4. проценты идут от нуля к сотне и раньше конца сотни не показывают",
      at(20.1)["percent"] == 0 and 45 <= at(30.0)["percent"] <= 55
      and at(39.9)["percent"] == 99 and at(40.1)["percent"] == 100,
      [at(t)["percent"] for t in (20.1, 30.0, 39.9, 40.1)])
check("5. пока идёт печать, остаток времени не показывает ноль",
      all(at(t)["remaining_time"] >= 1 for t in (0.1, 10.5, 25.0, 39.5))
      and at(40.1)["remaining_time"] == 0,
      [at(t)["remaining_time"] for t in (0.1, 10.5, 25.0, 39.5, 40.1)])
check("6. после готовности принтер остывает, а не остаётся горячим навсегда",
      at(41.0)["bed_temp"] > at(55.0)["bed_temp"] > dp.AMBIENT_C
      and at(300.0)["bed_temp"] == dp.AMBIENT_C and at(300.0)["nozzle_temp"] == dp.AMBIENT_C,
      (at(41.0)["bed_temp"], at(55.0)["bed_temp"], at(300.0)["bed_temp"]))

print("--- 2. откуда берутся цели нагрева ---")
GCODE = b"; sliced\nM140 S70\nM190 S70\nM104 S245\nM109 S245\nG28\nG1 X0 Y0\n"
check("7. из обычного g-code читаются настоящие цели",
      dp.temps_from_file(GCODE) == (70, 245), dp.temps_from_file(GCODE))
check("8. упакованный .3mf не разбирается — значения не выдумываются",
      dp.temps_from_file(b"PK\x03\x04" + GCODE) == (None, None))
check("9. мусорные значения из файла отбрасываются",
      dp.temps_from_file(b"M140 S999\nM104 S888\n") == (None, None))
dp.forget("p2")
_b, _n, _src = dp.start("p2", "a.gcode", GCODE, 0.0)
check("10. цели из файла идут первыми", (_b, _n, _src) == (70, 245, "файл"), (_b, _n, _src))
dp.forget("p3")
dp.set_target("p3", "bed", 55)
dp.set_target("p3", "nozzle", 210)
_b, _n, _src = dp.start("p3", "a.3mf", b"PK\x03\x04", 0.0)
check("11. если в файле целей нет — берутся заданные на пульте",
      (_b, _n, _src) == (55, 210, "пульт"), (_b, _n, _src))
dp.forget("p4")
_b, _n, _src = dp.start("p4", "a.3mf", b"PK\x03\x04", 0.0)
check("12. если нет и там — значения по умолчанию, и это названо честно",
      (_b, _n, _src) == (dp.BED_DEFAULT_C, dp.NOZZLE_DEFAULT_C, "по умолчанию"), (_b, _n, _src))

print("--- 3. пауза и остановка ---")
dp.forget("p5")
dp.start("p5", "a.gcode", None, 0.0)
dp.pause("p5", True, 25.0)                      # встали на пятой секунде печати
s_at_60 = dp.state("p5", 60.0)
check("13. на паузе часы задания стоят: состояние и проценты не меняются",
      s_at_60["status"] == "PAUSED" and s_at_60["status_raw"] == "paused"
      and s_at_60["percent"] == dp.state("p5", 25.0)["percent"],
      (s_at_60["status"], s_at_60["percent"]))
_pct_paused = s_at_60["percent"]                # запоминаем ДО снятия: после него часы сместятся
dp.pause("p5", False, 60.0)                     # сняли паузу через 35 секунд
check("14. после снятия паузы печать продолжается с того же места, а не с конца",
      dp.state("p5", 60.1)["status"] == "RUNNING"
      and abs(dp.state("p5", 60.1)["percent"] - _pct_paused) <= 1
      and dp.state("p5", 75.1)["status"] == "FINISH",
      (dp.state("p5", 60.1)["percent"], _pct_paused, dp.state("p5", 75.1)["status"]))
dp.forget("p6")
dp.start("p6", "a.gcode", None, 0.0)
dp.stop("p6", 25.0)
check("15. остановка заканчивает задание без печати: принтер свободен и остывает",
      dp.state("p6", 26.0)["status"] == "IDLE"
      and dp.state("p6", 26.0)["status_raw"] == "cancelled"
      and dp.state("p6", 26.0)["file_name"] == ""
      and dp.state("p6", 200.0)["bed_temp"] == dp.AMBIENT_C,
      dp.state("p6", 26.0))
check("16. остановленное задание не «дозревает» до FINISH и не засчитается",
      all(dp.state("p6", t)["status"] == "IDLE" for t in (30.0, 45.0, 500.0)))

print("--- 4. состояние в том же виде, что у настоящих принтеров ---")
st = dp.state("p1", 1030.0)
check("17. те же поля, что присылают адаптеры Bambu, Klipper и FlashForge",
      set(("status", "status_raw", "percent", "remaining_time", "file_name",
           "nozzle_temp", "bed_temp", "nozzle_target", "bed_target",
           "total_time", "nozzle_count")) <= set(st), sorted(st))
check("18. остаток в минутах, полное время в секундах — как во всей программе",
      st["remaining_time"] <= 1 and st["total_time"] == 40, (st["remaining_time"], st["total_time"]))
check("19. неизвестный принтер — просто свободен, без выдуманного задания",
      dp.state("нет-такого", 0.0)["status"] == "IDLE"
      and dp.state("нет-такого", 0.0)["file_name"] == "")
check("20. файлы «на принтере» помнятся и не задваиваются",
      (dp.add_file("p7", "a.gcode"), dp.add_file("p7", "a.gcode"), dp.add_file("p7", "b.gcode"),
       dp.files("p7"))[3] == ["a.gcode", "b.gcode"], dp.files("p7"))

print("--- 5. механизмы не подменены ---")
check("21. модуль не умеет открывать сеть: ни сокетов, ни запросов",
      not re.search(r"\b(import\s+(socket|urllib|http|requests|ftplib)|urlopen|connect\()", MOD))
check("22. модуль ничего не считает сам: ни задач, ни проектов, ни склада",
      not re.search(r"staging|project|inventory|printed_qty|handle_state", MOD, re.I))
check("23. количество засчитывает ядро на FINISH — тем же кодом, что у настоящих принтеров",
      'elif state == "FINISH" and prev != "FINISH":' in SRV
      and "handle_state(pid, st[\"status\"], st.get(\"file_name\") or \"\")" in SRV)
check("24. воркер виртуального принтера — такой же житель restart_workers, как остальные",
      'elif p["type"] == "demo" and main_loop:' in SRV and "run_demo" in SRV)
check("25. команды проходят ту же политику: свой список действий не заведён",
      'T_DEMO = "demo"' in POL and "ALL_TYPES = (T_KLIPPER, T_FLASHFORGE, T_BAMBU, T_DEMO, T_CREALITY)" in POL
      and "_printer_cmd_policy.parse_command(data.cmd, data.val, p[\"type\"])" in SRV)
#  2.986: виртуальный принтер называет стадии теми же словами, что и настоящие —
#  uploading/starting_file из _SEND_STATES. Раньше он слал upload/starting, у которых
#  нет подписи в интерфейсе.
check("26. отправка файла идёт тем же менеджером и показывает те же стадии",
      'if ptype == "demo":' in SRV and '_pcb(stage="uploading"' in SRV.split('if ptype == "demo":', 1)[1][:600]
      and '_pcb(stage="starting_file")' in SRV.split('if ptype == "demo":', 1)[1][:900])
check("27. покой и занятость виртуального принтера описаны в общих таблицах состояний",
      '"demo": ("idle",),' in SRV
      and '"demo": ("heating_bed", "heating_nozzle", "printing", "paused"),' in SRV)
check("28. принтер заводится одной кнопкой, без адреса и кода доступа",
      "const addDemoPrinter = async () => {" in APPJS and "type: 'demo'" in APPJS
      and "ip: ''," in APPJS and 'data-help="pf-demo"' in IDX)
check("29. в разметке не заведено ни одной отдельной ветки «если демо» для печати",
      "'demo'" not in IDX.split('data-help="pf-demo"')[0][-4000:].replace("addDemoPrinter", ""))

print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
