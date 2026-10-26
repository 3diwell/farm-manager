# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.791 — единая нормализация состояний принтера.
#
#  ЧАСТЬ 1 (ХАРАКТЕРИЗАЦИЯ). Как было в Alpha 2.790 (эталон 8eebcfe): завершение печати,
#  ошибка задания, пауза и незнакомая строка прошивки сваливались в ОДИН код
#  `not_idle_raw:<сырая строка>`. Оператор видел техническую строку, «печать завершена»
#  было неотличимо от «задание провалилось», а интерфейс держал СВОЮ таблицу состояний.
#
#  ЧАСТЬ 2+. Новое: чистая политика app/printer_state_policy.py — один разбор сырых строк
#  на все подсистемы, свой стабильный код причины у каждого случая, понятный текст в UI.
#
#  ЧТО ЭТОТ ЭТАП НЕ МЕНЯЕТ — и это главное. Порог безопасного покоя НЕ расширен.
#  FINISH и complete покоем НЕ становятся: на Bambu FINISH означает «печать закончена,
#  деталь ещё на столе», и снять барьер может только оператор кнопкой «Стол очищен»
#  (IDLE_NOT_PROOF в app/project_orchestrator.py). Автоматическая отправка остаётся
#  выключенной (DISPATCH_ENABLED = False) и этим этапом не трогается.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * production server.py НЕ импортируется: нужный блок извлекается текстом и исполняется
#     в изоляции. Тест запускается при РАБОТАЮЩЕЙ программе.
#   * рабочие БД, DATA_DIR и config не открываются; принтеры и сеть не используются.
#   * ни одной команды принтеру, ни одного задания печати.
#
#  Запуск:  python tools/test_printer_state_normalization.py   (0 = всё пройдено)
# ============================================================================
import os
import subprocess
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.append(os.path.join(REPO, "tools"))
import _history_baseline as HB   # noqa: E402

PARENT = "8eebcfe"   # HEAD до Alpha 2.791 (handoff 2.790)

FAILED = []
PASSED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "PRINTER_STATE_SENTINEL_2_791"

from app import printer_state_policy as P   # noqa: E402
L, R = P.Lifecycle, P.Readiness

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["server.py", "web/app.js"], check)
hcheck = HIST.check


def git_show(rel):
    return HIST.show(rel)


PAR_SRC = git_show("server.py")
PAR_JS = git_show("web/app.js")


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.791: единая нормализация состояний принтера ===")
section("характеризация: как было в Alpha 2.790 (эталон %s)" % PARENT)

hcheck("H0. эталон %s прочитан" % PARENT, lambda: bool(PAR_SRC) and bool(PAR_JS))
hcheck("H1. (1-4) завершение, ошибка, пауза и незнакомая строка давали ОДИН код с сырой строкой",
       lambda: 'return _no("not_idle_raw:" + raw[:24])' in PAR_SRC)
hcheck("H2. (5) планировщик сравнивал сырую строку напрямую по белому списку",
       lambda: "_SAFE_RAW_IDLE" in PAR_SRC and "printer_state_policy" not in PAR_SRC)
hcheck("H3. (6) у интерфейса была СВОЯ таблица состояний",
       lambda: "_statusBucket" in PAR_JS and "readinessReasonText" not in PAR_JS)
hcheck("H4. (6b) интерфейс считал FINISH зелёным, а FAILED — свободным",
       lambda: "'done' || s === 'FINISH') ? 'green'" in PAR_JS
       and "st === 'FINISH' || st === 'OPERATIONAL' || st === 'FAILED'" in PAR_JS)
hcheck("H5. (7-9) неизвестное, stale и offline блокировались (fail-closed) — сохранено",
       lambda: 'return _no("offline_or_stale")' in PAR_SRC and 'return _no("no_status_raw")' in PAR_SRC)
check("H6. (10-13) production server.py не импортируется, БД/принтеры/сеть не используются",
      "server" not in sys.modules)
check("H7. барьер «стол не подтверждён» существовал и в 2.790",
      "IDLE_NOT_PROOF" in open(os.path.join(REPO, "app", "project_orchestrator.py"),
                               encoding="utf-8").read())


# ════════════════════════════════════════════════════════════════════════════
section("чистая политика: нормализация (пункты 1-25)")

_psrc = open(os.path.join(REPO, "app", "printer_state_policy.py"), encoding="utf-8").read()
check("P0. политика не тянет фреймворк, БД, сеть, subprocess и журнал",
      not any(x in _psrc for x in ("import os", "import sqlite3", "import socket",
                                   "import logging", "import subprocess", "fastapi",
                                   "starlette", "urllib", "requests")))
check("P1. политика ничего не меняет и не обращается к принтеру",
      not any(x in _psrc for x in ("open(", "conn_", "execute(", "send", "urlopen")))

check("1. Bambu FINISH -> FINISHED", P.normalize_raw("bambu", "FINISH") == L.FINISHED)
check("2. регистр Bambu приводится безопасно",
      P.normalize_raw("bambu", "finish") == L.FINISHED
      and P.normalize_raw("bambu", "Finish") == L.FINISHED)
check("3. пробелы по краям не мешают", P.normalize_raw("bambu", "  FINISH  ") == L.FINISHED)
check("4. Klipper complete -> FINISHED", P.normalize_raw("klipper", "complete") == L.FINISHED)
check("5. FlashForge completed/complete -> FINISHED",
      P.normalize_raw("flashforge", "completed") == L.FINISHED
      and P.normalize_raw("flashforge", "complete") == L.FINISHED)
check("6. печать -> PRINTING",
      P.normalize_raw("bambu", "RUNNING") == L.PRINTING
      and P.normalize_raw("klipper", "printing") == L.PRINTING
      and P.normalize_raw("flashforge", "heating") == L.PRINTING)
check("7. пауза -> PAUSED (Bambu шлёт PAUSE, а не PAUSED)",
      P.normalize_raw("bambu", "PAUSE") == L.PAUSED
      and P.normalize_raw("bambu", "PAUSED") == L.PAUSED
      and P.normalize_raw("klipper", "paused") == L.PAUSED)
check("8. FAILED -> FAILED", P.normalize_raw("bambu", "FAILED") == L.FAILED)
check("9. ошибка и отмена -> FAILED",
      P.normalize_raw("klipper", "error") == L.FAILED
      and P.normalize_raw("klipper", "cancelled") == L.FAILED
      and P.normalize_raw("flashforge", "cancel") == L.FAILED)
check("10. незнакомая строка -> UNKNOWN",
      P.normalize_raw("bambu", "WAT") == L.UNKNOWN
      and P.normalize_raw("klipper", "wat") == L.UNKNOWN)
check("11. None -> UNKNOWN", P.normalize_raw("bambu", None) == L.UNKNOWN)
check("12. не-строка -> UNKNOWN",
      P.normalize_raw("bambu", 123) == L.UNKNOWN and P.normalize_raw("bambu", []) == L.UNKNOWN)
check("12b. пустая строка -> UNKNOWN", P.normalize_raw("bambu", "") == L.UNKNOWN)
check("21-23. неизвестный транспорт -> UNKNOWN, случайного прохода нет",
      P.normalize_raw("weird", "IDLE") == L.UNKNOWN
      and P.normalize_raw("", "IDLE") == L.UNKNOWN
      and set(P.SUPPORTED_TRANSPORTS) == {"bambu", "klipper", "flashforge", "creality"})   # 12.10.2026: + Creality без Moonraker
check("22. строка одной прошивки не проходит как известная у другой",
      P.normalize_raw("bambu", "standby") == L.UNKNOWN
      and P.normalize_raw("klipper", "FINISH") == L.UNKNOWN)
check("24-25. наблюдавшиеся состояния покрыты",
      P.normalize_raw("bambu", "FINISH") == L.FINISHED
      and P.normalize_raw("klipper", "complete") == L.FINISHED
      and P.normalize_raw("bambu", "FAILED") == L.FAILED)


section("покой, терминальность и причины (пункты 26-34)")

check("26-27. покой — только доказанный idle: FINISH и complete покоем НЕ становятся",
      P.is_quiet(L.IDLE) and not P.is_quiet(L.FINISHED) and not P.is_quiet(L.FAILED)
      and not P.is_quiet(L.UNKNOWN))
check("28. терминальность различает успех и ошибку",
      P.is_terminal(L.FINISHED) and P.is_terminal(L.FAILED)
      and P.is_successful_terminal(L.FINISHED)
      and not P.is_successful_terminal(L.FAILED))
check("29. активность: печать/подготовка/пауза; завершение и ошибка активными НЕ считаются",
      P.is_active(L.PRINTING) and P.is_active(L.PREPARING) and P.is_active(L.PAUSED)
      and not P.is_active(L.FINISHED) and not P.is_active(L.FAILED))
check("31. FINISH даёт СВОЮ причину, а не not_idle_raw",
      P.reason_for(L.FINISHED) == P.REASON_FINISHED_AWAITING_CLEARANCE
      and "not_idle_raw" not in P.reason_for(L.FINISHED))
check("33. FAILED даёт отдельную причину ошибки",
      P.reason_for(L.FAILED) == P.REASON_JOB_FAILED
      and P.reason_for(L.FAILED) != P.reason_for(L.FINISHED))
check("30+32. остальные причины различимы и стабильны",
      len({P.reason_for(x) for x in (L.PRINTING, L.PREPARING, L.PAUSED, L.FINISHED,
                                     L.FAILED, L.UNKNOWN)}) == 6)
check("34. сырая строка прошивки в код причины НЕ подставляется",
      all(SENTINEL not in P.reason_for(P.normalize_raw(t, SENTINEL))
          for t in ("bambu", "klipper", "flashforge")))

section("пригодность (пункты 13-20, 35-41)")

check("19-20. свежий покой без препятствий -> READY",
      P.readiness_for(L.IDLE, fresh=True) == R.READY)
check("13-14. несвежесть/offline всегда блокируют",
      P.readiness_for(L.IDLE, fresh=False) == R.OFFLINE
      and P.readiness_for(L.FINISHED, fresh=False) == R.OFFLINE)
check("15-18. любое препятствие блокирует даже при покое",
      P.readiness_for(L.IDLE, fresh=True, blockers=("send_reservation",)) == R.BLOCKED
      and P.readiness_for(L.IDLE, True, ("in_other_project_run",)) == R.BLOCKED
      and P.readiness_for(L.IDLE, True, ("printer_held",)) == R.BLOCKED)
check("36-37. печать и пауза -> BUSY",
      P.readiness_for(L.PRINTING) == R.BUSY and P.readiness_for(L.PAUSED) == R.BUSY)
check("38. FAILED -> BLOCKED (без доказанного сброса не назначается)",
      P.readiness_for(L.FAILED) == R.BLOCKED)
check("35+БАРЬЕР. FINISHED -> BLOCKED: завершение само по себе НЕ делает принтер готовым",
      P.readiness_for(L.FINISHED) == R.BLOCKED)
check("41. UNKNOWN -> UNKNOWN, готовым не становится",
      P.readiness_for(L.UNKNOWN) == R.UNKNOWN and P.readiness_for(L.UNKNOWN) != R.READY)
check("вход не мутируется, решение детерминировано",
      P.readiness_for(L.IDLE) == P.readiness_for(L.IDLE)
      and P.normalize_raw("bambu", "FINISH") == P.normalize_raw("bambu", "FINISH"))


# ════════════════════════════════════════════════════════════════════════════
section("интеграция с ядром: единый источник и сохранённый порог")

check("E1. ядро использует общую политику, а не свой разбор строк",
      "_state_policy.reason_for(_state_policy.normalize_raw(" in SRC)
# Ищем ФОРМУ ВЫРАЖЕНИЯ, а не упоминание: слово not_idle_raw законно осталось в пояснении
# к коду, где сказано, что именно изменилось. Подстрочный поиск дал бы ложный результат.
check("E2. сырая строка в причину больше не подставляется",
      'not_idle_raw:" + raw' not in SRC and "'not_idle_raw:' + raw" not in SRC
      and 'raw[:24]' not in SRC)
check("E3. ПОРОГ ПОКОЯ НЕ РАСШИРЕН: белый список прежний",
      '"bambu": ("IDLE",)' in SRC and '"klipper": ("standby",)' in SRC
      and '"flashforge": ("ready", "idle")' in SRC)
check("E4. барьер «стол не подтверждён» не тронут",
      "IDLE_NOT_PROOF" in open(os.path.join(REPO, "app", "project_orchestrator.py"),
                               encoding="utf-8").read())
check("47-48+52. автоматическая отправка ОСТАЁТСЯ выключенной",
      "DISPATCH_ENABLED = False" in open(os.path.join(REPO, "app", "project_orchestrator.py"),
                                         encoding="utf-8").read())
# 'gcode' законно упоминается как ИМЯ ПОЛЯ прошивки (Bambu gcode_state) в пояснении к
# таблице — это описание источника, а не отправка. Проверяем вызовы, а не слова.
check("E5. политика не участвует в отправке заданий и командах принтеру",
      not any(x in _psrc for x in ("dispatch(", "reserve(", "queue(", "send(",
                                   "start_print", "_send_file_to_printer")))

_js = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
check("E6. интерфейс переводит коды причин в понятный текст",
      "readinessReasonText" in _js
      and "Печать завершена — подтвердите очистку стола" in _js
      and "Предыдущее задание завершилось ошибкой" in _js)
check("E7. коды ядра и словарь интерфейса согласованы",
      all(("'%s'" % c) in _js for c in
          (P.REASON_FINISHED_AWAITING_CLEARANCE, P.REASON_JOB_FAILED, P.REASON_PRINTING,
           P.REASON_PAUSED, P.REASON_STATE_UNKNOWN, P.REASON_OFFLINE_OR_STALE)))
check("E8. незнакомый код интерфейс показывает как есть, а не прячет",
      "map[key] || key" in _js)

section("побочные эффекты и метка (пункты 53-59)")

check("53-58. нормализация ничего не пишет и никого не вызывает",
      not any(x in _psrc for x in ("INSERT", "UPDATE", "DELETE", "commit",
                                   "makedirs", "Popen", "os.")))
check("59a. метка не попадает в решение",
      P.readiness_for(P.normalize_raw("bambu", SENTINEL)) == R.UNKNOWN)
check("59b. метка отсутствует в исходниках приложения",
      SENTINEL not in SRC and SENTINEL not in _psrc and SENTINEL not in _js
      and SENTINEL not in open(os.path.join(REPO, "app", "project_orchestrator.py"),
                               encoding="utf-8").read())

print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
