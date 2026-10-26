# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""
Alpha 2.819 — КАНОНИЧЕСКАЯ идентичность кода ошибки Bambu (raw → 'XXXX-XXXX'), без догадок про endian.

Причина. Приёмка 2.818 показала на карточке H2 «Код 0003-000A», хотя ЖИВОЙ лог зафиксировал реальный
raw `print_error = 50348044 = 0x0300400C → 0300-400C` (штатный код отмены, уже известный с 2.732).
Значения `0003-000A` и `0300-000A` в телеметрии НЕ встречаются вовсе — это НЕВЕРНО ПРОЧИТАННЫЙ скриншот.
Настоящий дефект 2.818 был не в чтении кода, а в контексте внешней остановки (см.
test_user_cancelled_print_classification.py). Но чтобы «неверно прочитанный код» больше НИКОГДА не увёл
классификацию, решение теперь принимается по КАНОНИЧЕСКОМУ числовому значению из ЕДИНОГО нормализатора
app.printer_health_policy.norm_error_code, а не по строке интерфейса. Этот тест доказывает ЧИСЛОМ, что
нормализация детерминирована и без byte/word-swap, и что server.py использует тот же нормализатор.

Тест полностью offline: только чистый модуль + статический разбор server.py. Ни сети, ни БД, ни принтеров.
"""
import io
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

SENTINEL = "BAMBU_ERROR_CODE_CANONICAL_SENTINEL_2_819"

import app.printer_health_policy as H

_fail = 0
_pass = 0


def check(name, cond, detail=""):
    global _fail, _pass
    if cond:
        _pass += 1
        print("ok   %s" % name)
    else:
        _fail += 1
        print("FAIL — %s%s" % (name, (" | " + detail) if detail else ""))


SRV = io.open(os.path.join(PROJ, "server.py"), encoding="utf-8", errors="replace").read()
n = H.norm_error_code

print("=== A. Реальный код H2 из живого лога ===")
# raw print_error 50348044 == 0x0300400C — тремя путями входа даёт ОДНО каноническое значение.
check("1. raw int 50348044 → '0300-400C'", n(50348044) == "0300-400C")
check("2. raw hex 0x0300400C → '0300-400C'", n(0x0300400C) == "0300-400C")
check("3. dec-строка '50348044' → '0300-400C'", n("50348044") == "0300-400C")
check("4. hex-строка '0x0300400C' → '0300-400C'", n("0x0300400C") == "0300-400C")
check("5. 50348044 == 0x0300400C (одно и то же число)", 50348044 == 0x0300400C)

print("=== B. Скриншотные коды — ДРУГИЕ raw-значения (misread), в телеметрии их нет ===")
check("6. '0003-000A' был бы raw 0x0003000A = 196618 — ДРУГОЕ число, не равно 0x0300400C",
      n(0x0003000A) == "0003-000A" and 0x0003000A == 196618 and 0x0003000A != 0x0300400C)
check("7. '0300-000A' (из задачи 2.818) был бы raw 0x0300000A = 50331658 — тоже ДРУГОЕ число",
      n(0x0300000A) == "0300-000A" and 0x0300000A != 0x0300400C and 0x0300000A != 0x0003000A)
check("8. три строки — три РАЗНЫХ raw: 0300-400C / 0003-000A / 0300-000A не совпадают",
      len({0x0300400C, 0x0003000A, 0x0300000A}) == 3)

print("=== C. Нет byte/word-swap и прочих перестановок (доказано числом) ===")
# Порядок групп фиксирован: старшие 16 бит — группа, младшие — код. Проверяем, что norm НЕ делает swap.
check("9. НЕ word-swap: 0x0300400C ≠ '400C-0300' (иначе перепутаны старшие/младшие 16 бит)",
      n(0x0300400C) != "400C-0300")
check("10. НЕ byte-swap: 0x0300400C ≠ '0C40-0003'", n(0x0300400C) != "0C40-0003")
check("11. группа = старшие 16 бит, код = младшие: '0300' и '400C' на своих местах",
      n(0x0300400C)[:4] == "%04X" % ((0x0300400C >> 16) & 0xFFFF)
      and n(0x0300400C)[5:] == "%04X" % (0x0300400C & 0xFFFF))
check("12. известный HMS 0x07FF8011 → '07FF-8011' (тот же порядок групп)", n(0x07FF8011) == "07FF-8011")

print("=== D. Форма, ведущие нули, знак, мусор ===")
check("13. всегда ровно 8 HEX с дефисом посередине (XXXX-XXXX)",
      len(n(0x0300400C)) == 9 and n(0x0300400C)[4] == "-")
check("14. ведущие нули сохраняются: 0x0000000A → '0000-000A'", n(0x0000000A) == "0000-000A")
check("15. верхний регистр HEX: 0x0300400C → '0300-400C' (C заглавная)", n(0x0300400C) == n(0x0300400C).upper())
check("16. signed → & 0xFFFFFFFF: -1 → 'FFFF-FFFF'", n(-1) == "FFFF-FFFF")
check("17. ноль/пусто/мусор/bool → None",
      n(0) is None and n("") is None and n(None) is None and n("zzz") is None and n(True) is None)
check("18. большое число обрезается до 32 бит (& 0xFFFFFFFF)", n(0x1_0300400C) == "0300-400C")

print("=== E. Единый источник: server.py делегирует норму этому модулю ===")
check("19. server.py: _norm_bambu_error_code делегирует _health.norm_error_code (один canonical)",
      "return _health.norm_error_code(v)" in SRV and "from app import printer_health_policy as _health" in SRV)
check("20. классификатор сравнивает семейство отмены в каноническом виде (не по display-строке интерфейса)",
      H.is_bambu_cancel_code("0300-400C") and not H.is_bambu_cancel_code("0003-000A")
      and not H.is_bambu_cancel_code("400C-0300"))

print("=== F. Метка ===")
_leak = [p for p in [os.path.join(PROJ, "server.py"), os.path.join(PROJ, "app", "printer_health_policy.py")]
         if SENTINEL in io.open(p, encoding="utf-8", errors="replace").read()]
check("21. метка не попала в продуктовые файлы", not _leak, str(_leak))
check("22. тестовых артефактов нет (_e2e_payload.json)",
      not os.path.exists(os.path.join(PROJ, "tools", "_e2e_payload.json")))

print()
print("Итого: %d проверок пройдено, %d провалено" % (_pass, _fail))
if _fail:
    print("FAIL: %d проверок провалено" % _fail)
sys.exit(1 if _fail else 0)
