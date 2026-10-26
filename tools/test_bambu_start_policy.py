# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.976 — приняла ли прошивка Bambu команду печати: чистая логика без сервера.

ЗАЧЕМ. Владелец прислал фото экрана H2D: «Device is busy and cannot start new task [0500-4004]»
при запуске печати из задач — печать при этом шла («Homing toolhead»). Значит, программа послала
ВТОРУЮ команду печати уже печатающему принтеру. Причина — решение по одной телеметрии, которая
у H2D запаздывает. Здесь проверяется новое решение (app/bambu_start_policy.py) на снимках
состояний: ни один из путей не должен вести ко второй команде, когда первая уже выполняется.

БЕЗОПАСНОСТЬ: ни сети, ни принтеров, ни сервера — только функции модуля.

Запуск:  python tools/test_bambu_start_policy.py
"""
import importlib.util
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location("bambu_start_policy", os.path.join(ROOT, "app", "bambu_start_policy.py"))
pol = importlib.util.module_from_spec(_s)
_s.loader.exec_module(pol)

SENTINEL = "BAMBU_START_POLICY_SENTINEL_2_976"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


IDLE = {"status": "IDLE", "print_error": 0, "mc_err": "0", "hms_n": 0}

print("--- 1. код «занято» ---")
check("1. 0500-4004 с экрана H2D = 0x05004004 в print_error", pol.BUSY_CODE == 0x05004004 == 83902468)
check("2. код узнаётся и числом, и строкой", pol.is_busy_code(83902468) and pol.is_busy_code("83902468") and not pol.is_busy_code(0))

print("--- 2. ответ прошивки на команду ---")
check("3. success/fail читаются без учёта регистра",
      pol.ack_kind({"command": "project_file", "result": "SUCCESS", "ts": 10}, 5) == "ok"
      and pol.ack_kind({"command": "project_file", "result": "fail", "reason": "x", "ts": 10}, 5) == "fail")
check("4. ответ на прошлую команду (старше отправки) не в счёт",
      pol.ack_kind({"command": "project_file", "result": "success", "ts": 3}, 5) is None)
check("5. ответ на другую команду не в счёт",
      pol.ack_kind({"command": "gcode_line", "result": "success", "ts": 10}, 5) is None)
check("6. незнакомый result — не решение", pol.ack_kind({"command": "project_file", "result": "??", "ts": 10}, 5) is None)

print("--- 3. случай владельца: H2D уже печатает, отчёт запаздывает ---")
w = pol.StartWatch(0, "0", 0, since=100.0)
#  Первые такты: покой, но в HMS появилась запись (так у Bambu бывает в момент старта).
check("7. рост HMS при покое — ещё не отказ, а ожидание",
      w.note({"status": "IDLE", "print_error": 0, "mc_err": "0", "hms_n": 1}) == "wait")
#  Затем прошивка ответила, что команду приняла — решение 'ok', даже при покое в телеметрии.
check("8. ответ прошивки «принято» решает раньше телеметрии",
      w.note({"status": "IDLE", "print_error": 0, "mc_err": "0", "hms_n": 1},
             {"command": "project_file", "result": "success", "ts": 101.0}) == "ok")

w2 = pol.StartWatch(0, "0", 0, since=100.0)
check("9. код «занято» = печать уже идёт: 'ok', вторая команда не нужна",
      w2.note({"status": "IDLE", "print_error": 83902468, "mc_err": "0", "hms_n": 0}) == "ok")

w3 = pol.StartWatch(0, "0", 0, since=100.0)
w3.note({"status": "IDLE", "print_error": 0, "mc_err": "0", "hms_n": 2})
check("10. молчание с ростом HMS — по истечении окна 'fail' (как и прежде), а не раньше",
      w3.verdict() == "fail")
w4 = pol.StartWatch(0, "0", 0, since=100.0)
w4.note(IDLE)
check("11. полное молчание без ошибок — 'timeout' (медленный старт, повтор запрещён)", w4.verdict() == "timeout")

print("--- 4. настоящий отказ ---")
w5 = pol.StartWatch(0, "0", 0, since=100.0)
check("12. прошивка ответила отказом — 'fail' с причиной",
      w5.note(IDLE, {"command": "project_file", "result": "fail", "reason": "file not found", "ts": 100.5}) == "fail"
      and w5.ack_reason == "file not found")
w6 = pol.StartWatch(0, "0", 0, since=100.0)
check("13. статус PREPARE — 'ok' сразу", w6.note({"status": "PREPARE"}) == "ok")
w7 = pol.StartWatch(5, "0", 0, since=100.0)
w7.note({"status": "IDLE", "print_error": 5, "mc_err": "0", "hms_n": 0})
check("14. ошибка, бывшая ДО команды, новой не считается", w7.verdict() == "timeout")

print()
print("%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
