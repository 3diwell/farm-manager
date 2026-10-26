# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.820 — РЕГРЕССИЯ ЧЕРЕЗ ФАКТИЧЕСКИЙ ПРОДАКШЕН-ПУТЬ (внешняя остановка Bambu с экрана).

ЗАЧЕМ ИМЕННО ТАК. Приёмка 2.818 и 2.819 проваливалась, хотя unit-тест policy проходил: тесты звали
classify_bambu НАПРЯМУЮ с рукотворным снимком БЕЗ hms_codes и потому не воспроизводили реальную
телеметрию. На живом железе H2D при остановке С ЭКРАНА принтер шлёт ОДНОВРЕМЕННО:
    print_error = 50348044 (0x0300400C → '0300-400C', семейство отмены),
    mc_print_error_code = '16396' (0x400C, семейство отмены),
    hms = [{'code': 196618}]  → '0003-000A'  (HMS-уведомление об отмене).
Старый _bambu_real_code брал ПЕРВЫЙ «реальный» HMS (0003-000A) и короткозамыкал контекст-гейт:
device_error='0003-000A', is_cancellation=False → красная карточка + счётчик.

ЧТО ПРОВЕРЯЕТ ТЕСТ. НЕ зовёт policy как главный сценарий. Он ИСПОЛНЯЕТ ФАКТИЧЕСКИЙ КОД server.py:
реальные _norm_bambu_error_code / _bambu_hms_codes (AST-вырезка) и реальный блок on_message
(парсинг print_error/mc/hms → _ecode/_hms_codes → classify_bambu → защёлка → маскировка статуса →
p_states) — текстовая вырезка по якорям. Прогоняет ПОСЛЕДОВАТЕЛЬНОСТЬ кадров (idle → running →
failed → failed+коды) и проверяет ИТОГ в p_states: device_error и status. Если server.py снова начнёт
терять контекст (или блок изменят несовместимо) — тест станет красным ДО сборки, а не на ферме.

Файл самодостаточен: печатает 'OK'/'FAIL k/n' и код возврата. Кириллица в stdout требует PYTHONUTF8=1.
"""
import ast
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app.printer_health_policy as _health  # РЕАЛЬНЫЙ единый классификатор (тот же, что в server.py)

SERVER = os.path.join(ROOT, "server.py")
SRC = open(SERVER, encoding="utf-8").read()
SRC_LINES = SRC.splitlines()


# ── 1. Реальные помощники server.py (модульные функции) — вырезаем через AST, исполняем как есть.
def _extract_func(name):
    tree = ast.parse(SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SRC, node)
    raise AssertionError("не найдена функция %r в server.py" % name)


# ── 2. Реальный блок on_message: от парсинга print_error до маскировки статуса. Якоря — стабильные
#       строки кода; если их нет, значит блок несовместимо изменён — тест обязан упасть, а не молчать.
def _extract_block():
    start = end = None
    for i, ln in enumerate(SRC_LINES):
        if start is None and '_pe = int(d.get("print_error"' in ln:
            start = i
        if start is not None and "if (pid in _user_stopped or pid in _cancel_latch) and st in" in ln:
            # маскировка статуса — следующая строка (st = "IDLE"); включаем её
            end = i + 1
            break
    assert start is not None, "не найден старт блока on_message (парсинг print_error)"
    assert end is not None and end + 1 <= len(SRC_LINES), "не найден конец блока on_message (маска статуса)"
    assert 'st = "IDLE"' in SRC_LINES[end], "конец блока не там, где ожидалось: %r" % SRC_LINES[end]
    block = SRC_LINES[start:end + 1]
    # снять единый отступ вложенной функции, чтобы блок исполнялся на верхнем уровне
    import textwrap
    return textwrap.dedent("\n".join(block))


def _extract_const_float(name):
    for ln in SRC_LINES:
        s = ln.strip()
        if s.startswith(name + " ") and "=" in s:
            val = s.split("=", 1)[1].split("#", 1)[0].strip()
            return float(val)
    raise AssertionError("не найдена константа %r" % name)


# Пространство имён «как в server.py» для исполнения вырезанного блока.
NS = {}
exec(_extract_func("_norm_bambu_error_code"), NS)
exec(_extract_func("_bambu_hms_codes"), NS)
#  2.992: блок разбора отчёта считает ещё и список уведомлений принтера целиком
#  (код, важность, узел). Берём функцию ДОСЛОВНО — заглушка спрятала бы поведение.
exec(_extract_func("_bambu_hms_list"), NS)
NS["_health"] = _health
NS["time"] = __import__("time")
NS["log"] = types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None,
                                  warning=lambda *a, **k: None)
NS["_CANCEL_RECENT_ACTIVE_S"] = _extract_const_float("_CANCEL_RECENT_ACTIVE_S")
BLOCK = compile(_extract_block(), "<on_message-block>", "exec")

# состояние процесса (как модульные словари server.py) — общее на всю сессию принтера
NS["_user_stopped"] = {}
NS["_cancel_latch"] = {}
NS["_last_active_ts"] = {}

PID = "node_test_h2"
_pstates = {}   # локальный аналог p_states


def feed(report):
    """Прогнать ОДИН сырой отчёт через фактический код server.py и записать p_states[PID]."""
    prev = _pstates.get(PID, {})
    st = report.get("gcode_state", prev.get("status", "IDLE"))
    NS.update({"d": report, "prev": prev, "st": st, "pid": PID})
    exec(BLOCK, NS)   # ← ФАКТИЧЕСКИЙ блок on_message: _pe/_mce/_ecode/_hms_codes → classify → latch → mask
    _pstates[PID] = {
        "status": NS["st"], "status_raw": NS["_st_raw"],
        "device_error": NS["_dev_err"], "error_code": NS["_ecode"],
        "hms_codes": NS["_hms_codes"], "mc_err": NS["_mce"], "print_error": NS["_pe"],
    }
    return _pstates[PID]


# ── Проверки ────────────────────────────────────────────────────────────────────────────────────
checks = []


def ck(cond, label):
    checks.append((bool(cond), label))


def reset():
    NS["_user_stopped"].clear(); NS["_cancel_latch"].clear(); NS["_last_active_ts"].clear()
    _pstates.clear()


# Кадры реального железа: код отмены как ДЕСЯТИЧНЫЙ int (Bambu так и шлёт print_error).
PE_CANCEL = 50348044                 # 0x0300400C → '0300-400C'
HMS_CANCEL_RAW = int("0003000A", 16)  # 196618 → '0003-000A'
RUN = {"gcode_state": "RUNNING"}
# «липкий» FAILED со всеми тремя признаками отмены сразу (полный отчёт после стопа с экрана):
STOP = {"gcode_state": "FAILED", "print_error": PE_CANCEL, "mc_print_error_code": "16396",
        "hms": [{"code": HMS_CANCEL_RAW}]}

# 1) ГЛАВНЫЙ СЦЕНАРИЙ: печать шла (RUNNING), затем остановлена с экрана (FAILED + коды + HMS 0003-000A).
reset()
feed({"gcode_state": "IDLE"})
feed(RUN)                    # принтер печатает → _last_active_ts проставлен
s = feed(STOP)               # остановка с экрана: те самые три признака
ck(s["hms_codes"] == ["0003-000A"], "1a снимок реально содержит HMS 0003-000A (иначе тест бесполезен)")
ck(s["error_code"] == "0300-400C", "1b print_error нормализован в '0300-400C'")
ck(s["device_error"] is None, "1c device_error ПУСТ → красной карточки НЕТ (корень 2.820)")
ck(s["status"] == "IDLE", "1d статус замаскирован в IDLE → нет 'print failure' в диагностике")
ck(PID in NS["_cancel_latch"], "1e отмена защёлкнута (job_cancelled залогирован)")

# 1D) РЕАЛИСТИЧНАЯ ХРОНОЛОГИЯ (как в forensic: FAILED в 13:39:03, код отмены в 13:39:09 — на 6 с позже).
#     Кадр FAILED БЕЗ кода идёт ПЕРВЫМ → prev становится FAILED → prev_active=False на кадре с кодом.
#     Спасает ТОЛЬКО recently_active (окно 2.819); именно этот путь ловит мутации _last_active_ts.
reset()
feed(RUN)                                   # печатал → отметка активности
feed({"gcode_state": "FAILED"})             # ушёл в FAILED БЕЗ кода (prev станет FAILED)
sD = feed(STOP)                             # код отмены + HMS пришли на СЛЕДУЮЩЕМ кадре
ck(sD["device_error"] is None, "1D-a код на кадр ПОЗЖЕ FAILED: device_error пуст (recently_active спас)")
ck(sD["status"] == "IDLE", "1D-b статус замаскирован в IDLE (нет 'print failure')")
ck(PID in NS["_cancel_latch"], "1D-c отмена защёлкнута несмотря на prev_active=False")

# 2) Защёлка держит «липкий» FAILED до новой печати (повторные кадры отчёта не растят ошибку).
s2 = feed(STOP)
ck(s2["device_error"] is None and s2["status"] == "IDLE", "2 повторный липкий FAILED так же чист")

# 3) РЕАЛЬНАЯ АППАРАТНАЯ ошибка во время остановки НЕ скрывается (fail-safe: известный HMS клога).
reset()
feed(RUN)
s3 = feed({"gcode_state": "FAILED", "print_error": PE_CANCEL, "mc_print_error_code": "16396",
           "hms": [{"code": int("07FF8011", 16)}, {"code": HMS_CANCEL_RAW}]})
ck(s3["device_error"] == "07FF-8011", "3a реальный HMS клога ПОКАЗАН, отмена его не прячет")
ck(PID not in NS["_cancel_latch"], "3b при реальной ошибке отмена НЕ защёлкивается")

# 4) HMS 0003-000A БЕЗ недавней печати (stale, принтер не печатал) — НЕ гасится (fail-safe окна).
reset()
s4 = feed({"gcode_state": "FAILED", "print_error": PE_CANCEL, "mc_print_error_code": "16396",
           "hms": [{"code": HMS_CANCEL_RAW}]})
ck(s4["device_error"] == "0300-400C", "4 stale-код отмены без активности ПОКАЗАН (не залипание)")

# 5) Чистая отмена по одному print_error (без HMS) после печати — по-прежнему гасится (регресс 2.819).
reset()
feed(RUN)
s5 = feed({"gcode_state": "FAILED", "print_error": PE_CANCEL, "mc_print_error_code": "16396"})
ck(s5["device_error"] is None and s5["status"] == "IDLE", "5 отмена без HMS так же чиста (2.819)")

# 6) Возобновление печати снимает защёлку и любой прежний код (новая физическая сессия).
reset()
feed(RUN); feed(STOP)
s6 = feed(RUN)
ck(PID not in NS["_cancel_latch"], "6a новая печать сняла защёлку отмены")
ck(s6["device_error"] is None and s6["status"] == "RUNNING", "6b идёт печать — канал чист")

# 7) Настоящий сбой печати (не семейство отмены) ПОКАЗАН даже сразу после активности.
reset()
feed(RUN)
s7 = feed({"gcode_state": "FAILED", "print_error": int("05004002", 16)})  # 0500-4002 — не отмена
ck(s7["device_error"] == "0500-4002", "7 настоящий сбой '0500-4002' показан (не замаскирован)")

# 8) 24.10.2026 (журнал фермы, P2S_07): новая печать, а в ПЕРВОМ кадре подготовки принтер ещё несёт
#    уведомление об отмене 0003-000A. Раньше «недавняя активность» от самого PREPARE делала его «отменой»
#    новой печати: защёлка → «Свободен» на всю печать, старт не подтверждён, конец не учтён.
PREP_STALE_HMS = {"gcode_state": "PREPARE", "hms": [{"code": HMS_CANCEL_RAW}]}
reset()
feed({"gcode_state": "FINISH"})                # прошлая печать закончилась
s8 = feed(PREP_STALE_HMS)
ck(s8["hms_codes"] == ["0003-000A"], "8a кадр подготовки реально несёт HMS отмены (иначе тест бесполезен)")
ck(PID not in NS["_cancel_latch"], "8b подготовка новой печати НЕ защёлкивает отмену")
ck(s8["status"] == "PREPARE" and s8["device_error"] is None, "8c статус — «готовится», красной ошибки нет")
s8r = feed(RUN)
ck(s8r["status"] == "RUNNING" and PID not in NS["_cancel_latch"], "8d дальше печать видна как печать")
s8f = feed({"gcode_state": "FINISH"})
ck(s8f["status"] == "FINISH", "8e конец печати виден как конец (попадёт в учёт)")

# 9) Код прежней ОТМЕНЁННОЙ печати «залип» (FM держит его до нового кадра), а следующая печать
#    стартует: первый кадр PREPARE без новых кодов — тоже не отмена новой печати.
reset()
feed(RUN); feed(STOP)                          # прошлую печать действительно отменили
ck(PID in NS["_cancel_latch"], "9a прошлая отмена защёлкнута, как и раньше")
s9 = feed({"gcode_state": "PREPARE"})          # новая печать: коды в кадре не пришли — остались прежние
ck(PID not in NS["_cancel_latch"] and s9["status"] == "PREPARE", "9b новая печать: защёлка снята, статус «готовится»")
s9r = feed(RUN)
ck(s9r["status"] == "RUNNING", "9c и печатает как печать")

# 10) Настоящая отмена ВО ВРЕМЯ подготовки (с экрана): PREPARE → FAILED с кодами — защёлкнута, как прежде.
reset()
feed({"gcode_state": "IDLE"})
feed({"gcode_state": "PREPARE"})
s10 = feed(STOP)
ck(PID in NS["_cancel_latch"] and s10["status"] == "IDLE" and s10["device_error"] is None,
   "10 отмена во время подготовки по-прежнему распознаётся (FAILED с кодами → защёлка, без красной ошибки)")

# ── Итог ──────────────────────────────────────────────────────────────────────────────────────
passed = sum(1 for ok, _ in checks if ok)
total = len(checks)
for ok, label in checks:
    if not ok:
        print("FAIL:", label)
if passed == total:
    print("OK (%d/%d) — внешняя остановка Bambu (HMS 0003-000A) через фактический путь server.py" % (passed, total))
    sys.exit(0)
else:
    print("FAIL %d/%d" % (passed, total))
    sys.exit(1)
