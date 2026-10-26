# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Backend-тесты системы активных предупреждений принтеров — Alpha 2.731.
# Извлекаем ДОСЛОВНО из server.py нормализаторы (_norm_bambu_error_code / _bambu_hms_codes) и
# исполняем их со стабами; delta/clear-логику парсера воспроизводим функцией step() — ТОЧНЫМ зеркалом
# строк on_msg (error-поля + сброс на RUNNING/FINISH). Проверяем подтверждённые на железе значения,
# нормализацию signed/str/zero/malformed, hms delta и явный [], очистку на RUNNING/FINISH, sticky-partial.
# Запуск: python tools/test_printer_alerts_backend.py   (0 = все проверки пройдены)
import re, sys, io
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

fail = 0
def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond: fail += 1

SRC = open("server.py", encoding="utf-8", errors="surrogateescape").read()

def grab(name):
    i = SRC.index("def " + name + "(")
    j = SRC.index("\ndef ", i + 1)
    return SRC[i:j]

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app.printer_health_policy as _health   # Alpha 2.819: _norm_bambu_error_code делегирует единому нормализатору
ns = {"_health": _health}
exec(grab("_norm_bambu_error_code"), ns)
exec(grab("_bambu_hms_codes"), ns)
ne = ns["_norm_bambu_error_code"]
hc = ns["_bambu_hms_codes"]

# ── step(): ДОСЛОВНОЕ зеркало on_msg (server.py) для error-полей + сброс на RUNNING/FINISH ──
def step(prev, d):
    st = d.get("gcode_state", prev.get("status", "IDLE"))
    try: _pe = int(d.get("print_error", prev.get("print_error", 0)) or 0)
    except Exception: _pe = prev.get("print_error", 0)
    _mce = str(d.get("mc_print_error_code", prev.get("mc_err", "0")) or "0")
    _hms = d.get("hms")
    _hmsn = len(_hms) if isinstance(_hms, list) else prev.get("hms_n", 0)
    _ecode = ne(_pe)
    _hms_codes = hc(d, prev.get("hms_codes", []) or [])
    if st in ("RUNNING", "FINISH"):
        _pe = 0; _mce = "0"; _ecode = None; _hms_codes = []; _hmsn = 0
    return {"status": st, "print_error": _pe, "mc_err": _mce, "error_code": _ecode, "hms_codes": _hms_codes, "hms_n": _hmsn}

# ═══ извлечение реальных функций ═══
check("S1. извлечены реальные _norm_bambu_error_code / _bambu_hms_codes из server.py", callable(ne) and callable(hc))

# ═══ подтверждённые НА ЖЕЛЕЗЕ значения ═══
check("A1. print_error=134184977 → '07FF-8011' (закончился филамент)", ne(134184977) == "07FF-8011")
check("A2. print_error=134184967 → '07FF-8007' (проверьте подачу)", ne(134184967) == "07FF-8007")
r = step({}, {"gcode_state": "PAUSE", "print_error": 134184977, "mc_print_error_code": 32785})
check("A3. PAUSE + 134184977/mc32785 → error_code 07FF-8011, print_error/mc сохранены", r["error_code"] == "07FF-8011" and r["print_error"] == 134184977 and r["mc_err"] == "32785")

# ═══ штатная отмена печати (0300-400C) — backend НОРМАЛИЗУЕТ и СОХРАНЯЕТ сырое для диагностики (Alpha 2.732) ═══
# Классификация отмены как «не сбой» — на ФРОНТЕ (движок alert), backend только фиксирует факт (diagnostics not hidden).
check("C1. print_error=50348044 (0x0300400C) → '0300-400C'", ne(50348044) == "0300-400C")
rc = step({}, {"gcode_state": "FAILED", "print_error": 50348044, "mc_print_error_code": 16396})
check("C2. FAILED + отмена 50348044/mc16396 → error_code '0300-400C', сырое print_error/mc СОХРАНЕНЫ (диагностика не скрыта, FAILED не чистит)",
      rc["error_code"] == "0300-400C" and rc["print_error"] == 50348044 and rc["mc_err"] == "16396" and rc["status"] == "FAILED")
rc2 = step(rc, {"gcode_state": "RUNNING"})   # новая печать — только RUNNING/FINISH чистит коды
check("C3. RUNNING после отмены очищает код отмены (0300-400C не «липнет» в новую печать)",
      rc2["error_code"] is None and rc2["print_error"] == 0 and rc2["mc_err"] == "0")

# ═══ второй benign-код отмены P2S 0002-0070 — тоже НОРМАЛИЗУЕТСЯ и СОХРАНЯЕТСЯ (подавление на фронте, Alpha 2.735) ═══
check("C4. print_error=131184 (0x00020070) → '0002-0070'", ne(131184) == "0002-0070")
rc0070 = step({}, {"gcode_state": "FAILED", "print_error": 131184})
check("C5. FAILED + 0002-0070 → error_code '0002-0070', сырое print_error СОХРАНЕНО (диагностика не скрыта, FAILED не чистит)",
      rc0070["error_code"] == "0002-0070" and rc0070["print_error"] == 131184 and rc0070["status"] == "FAILED")
rc0070h = step({}, {"gcode_state": "FAILED", "hms": [{"code": 0x00020070}]})
check("C6. 0002-0070 как HMS-код → hms_codes=['0002-0070'] СОХРАНЁН (backend не выбрасывает; подавление — на фронте)",
      rc0070h["hms_codes"] == ["0002-0070"])

# ═══ нормализация: int/str/hex/zero/signed/malformed ═══
check("N1. строка-десятичная '134184977' → 07FF-8011", ne("134184977") == "07FF-8011")
check("N2. строка-hex '0x07FF8011' → 07FF-8011", ne("0x07FF8011") == "07FF-8011")
check("N3. mc-подобное 32785 (0x8011) → '0000-8011' (ровно 8 HEX)", ne(32785) == "0000-8011")
check("N4. 0 → None", ne(0) is None and ne("0") is None)
check("N5. signed -1 → 'FFFF-FFFF' (& 0xFFFFFFFF)", ne(-1) == "FFFF-FFFF")
check("N6. malformed 'zzz'/None/'' → None", ne("zzz") is None and ne(None) is None and ne("") is None)
check("N7. bool не считается кодом", ne(True) is None and ne(False) is None)
check("N8. формат всегда ровно 8 HEX с дефисом", re.match(r"^[0-9A-F]{4}-[0-9A-F]{4}$", ne(134184967)) is not None)

# ═══ hms delta / явный [] / нормализация записей ═══
check("H1. hms — список записей: code=0x12FF8011 → ['12FF-8011']", hc({"hms": [{"attr": 1, "code": 0x12FF8011}]}, []) == ["12FF-8011"])
check("H2. hms НЕТ в отчёте → prev не трогаем", hc({"print": 1}, ["07FF-8011"]) == ["07FF-8011"])
check("H3. hms == null → prev не трогаем (не очистка)", hc({"hms": None}, ["07FF-8011"]) == ["07FF-8011"])
check("H4. hms == [] (явно) → очистка []", hc({"hms": []}, ["07FF-8011"]) == [])
check("H5. malformed hms (не список) → prev не трогаем (fail-open)", hc({"hms": "x"}, ["07FF-8011"]) == ["07FF-8011"])
check("H6. дедуп и пропуск нулевых записей внутри hms", hc({"hms": [{"code": 0x12FF8011}, {"code": 0x12FF8011}, {"code": 0}]}, []) == ["12FF-8011"])
check("H7. malformed запись (не dict) не роняет и пропускается", hc({"hms": [42, {"code": 0x07FF8007}]}, []) == ["07FF-8007"])

# ═══ delta / clear через step() ═══
prev = step({}, {"gcode_state": "PAUSE", "print_error": 134184977, "mc_print_error_code": 32785, "hms": [{"code": 0x12FF8011}]})
check("D1. старт: активны error_code/hms_codes/print_error/mc", prev["error_code"] == "07FF-8011" and prev["hms_codes"] == ["12FF-8011"] and prev["hms_n"] == 1)
p2 = step(prev, {"gcode_state": "PAUSE"})   # частичный отчёт без error-полей
check("D2. partial без error-полей НИЧЕГО не очищает (sticky)", p2["error_code"] == "07FF-8011" and p2["print_error"] == 134184977 and p2["mc_err"] == "32785" and p2["hms_codes"] == ["12FF-8011"] and p2["hms_n"] == 1)
p3 = step(p2, {"gcode_state": "PAUSE", "print_error": 134184967, "mc_print_error_code": 32775})   # новый код
check("D3. новый print_error заменяет код (07FF-8007), hms по правилу delta сохраняется", p3["error_code"] == "07FF-8007" and p3["print_error"] == 134184967)
p4 = step(p3, {"gcode_state": "RUNNING"})   # возобновление
check("D4. RUNNING очищает ВСЁ: print_error=0, mc='0', error_code=None, hms_codes=[], hms_n=0", p4["print_error"] == 0 and p4["mc_err"] == "0" and p4["error_code"] is None and p4["hms_codes"] == [] and p4["hms_n"] == 0)
p5 = step(prev, {"gcode_state": "FINISH"})
check("D5. FINISH так же очищает все error-поля", p5["error_code"] is None and p5["hms_codes"] == [] and p5["print_error"] == 0 and p5["mc_err"] == "0" and p5["hms_n"] == 0)

# ═══ ручная пауза без кода / явный сброс hms ═══
mp = step({}, {"gcode_state": "PAUSE"})
check("D6. ручная PAUSE без кодов → error_code None, hms_codes [] (alert не будет)", mp["error_code"] is None and mp["hms_codes"] == [] and mp["print_error"] == 0)
pe = step(prev, {"gcode_state": "PAUSE", "hms": []})   # явный пустой hms при активном print_error
check("D7. явный hms:[] очищает hms_codes, но print_error/error_code (из sticky) остаются", pe["hms_codes"] == [] and pe["error_code"] == "07FF-8011")

# ═══ malformed report не роняет step (worker fail-open) ═══
ok_crash = True
try:
    step({}, {"gcode_state": "PAUSE", "print_error": "not-a-number", "hms": [{"weird": 1}, None, "x"]})
except Exception:
    ok_crash = False
check("D8. malformed report (плохой print_error/hms) не роняет обработку (fail-open)", ok_crash)

print("\n" + ("FAIL: %d проверок провалено" % fail if fail else "PASS: backend активных предупреждений — нормализация 07FF-8011/07FF-8007, delta/clear, hms [], sticky-partial, fail-open (реальные функции server.py)"))
sys.exit(1 if fail else 0)
