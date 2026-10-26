# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.792 — понятные статусы и причины в анализе плана.
#
#  ЧАСТЬ 1 (ХАРАКТЕРИЗАЦИЯ). Как было в Alpha 2.791 (эталон 792e5e7): бейдж варианта
#  печатал КОД backend как есть (`{{ c.effective_status }}`), поэтому оператор видел
#  attention_required и blocked; верхняя сводка при этом имела СВОИ рукописные подписи —
#  две несогласованные таблицы представления одного и того же набора статусов.
#
#  ЧАСТЬ 2+. Новое: одна таблица FEED_STATUS_VIEW во фронтенде, из которой берут подпись и
#  бейдж, и сводка; незнакомый код получает понятную подпись, а сам код уходит в title.
#
#  ЧЕГО ЭТОТ ЭТАП НЕ МЕНЯЕТ. Коды backend (ready / approval_required / attention_required /
#  blocked) остаются прежними — это машинный контракт. Решения планировщика, порог покоя
#  Alpha 2.791, барьер очистки стола и выключенная автоматическая отправка не трогаются.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * production server.py НЕ импортируется; рабочие БД, DATA_DIR и config не открываются.
#   * принтеры и сеть не используются, команды и задания печати не отправляются.
#
#  Запуск:  python tools/test_plan_analysis_status_presentation.py   (0 = всё пройдено)
# ============================================================================
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.append(os.path.join(REPO, "tools"))
import _history_baseline as HB   # noqa: E402

PARENT = "792e5e7"   # HEAD до Alpha 2.792

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


SENTINEL = "PLAN_STATUS_PRESENTATION_SENTINEL_2_792"

JS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
HTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["web/index.html", "web/app.js"], check)
hcheck = HIST.check


def git_show(rel):
    return HIST.show(rel)


PAR_HTML = git_show("web/index.html")
PAR_JS = git_show("web/app.js")

# Ровно те коды, что объявляет backend. Список не выдуман — он сверяется с исходником ниже.
CODES = ("ready", "approval_required", "attention_required", "blocked")

# Предохранитель проверяем ПО САМОЙ КОНСТАНТЕ (строка целиком), а не по упоминанию: слова
# «DISPATCH_ENABLED = False» есть и в докстроке модуля, и подстрочный поиск остался бы
# истинным даже после того, как предохранитель фактически сняли.
_DISPATCH_OFF = bool(re.search(r"(?m)^DISPATCH_ENABLED\s*=\s*False\s*$", ORCH))


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.792: понятные статусы анализа плана ===")
section("характеризация: как было в Alpha 2.791 (эталон %s)" % PARENT)

hcheck("H0. эталон %s прочитан" % PARENT, lambda: bool(PAR_HTML) and bool(PAR_JS))
hcheck("H1. (1-2) бейдж печатал КОД backend как есть",
       lambda: "{{ c.effective_status }}" in PAR_HTML)
hcheck("H3. (3) сводка имела свои рукописные подписи",
       lambda: "'внимание' : 'attention'" in PAR_HTML and "'нельзя' : 'blocked'" in PAR_HTML)
hcheck("H4. (4) общей таблицы представления не существовало",
       lambda: PAR_JS is not None and "FEED_STATUS_VIEW" not in PAR_JS and "feedStatusLabel" not in PAR_JS)
hcheck("H5. (5-6) причины уже переводились — дефект был только в статусе",
       lambda: "feedReasonText" in PAR_JS)
check("H7. (7) предохранитель автоотправки был выключен и остаётся",
      _DISPATCH_OFF)
check("H8. (8-11) production server.py не импортируется, БД/принтеры/сеть не используются",
      "server" not in sys.modules)


# ════════════════════════════════════════════════════════════════════════════
section("единая таблица представления (пункты 1-15)")

check("B0. коды backend не менялись",
      'FEED_READY, FEED_APPROVAL = "ready", "approval_required"' in ORCH
      and 'FEED_ATTENTION, FEED_BLOCKED = "attention_required", "blocked"' in ORCH)
check("15. таблица представления одна",
      JS.count("const FEED_STATUS_VIEW") == 1)

_view = JS[JS.index("const FEED_STATUS_VIEW"):]
_view = _view[:_view.index("};") + 2]

for code, ru, en in (("ready", "Готов", "Ready"),
                     ("approval_required", "Нужно подтверждение", "Confirmation required"),
                     ("attention_required", "Требуется настройка", "Setup required"),
                     ("blocked", "Недоступен", "Unavailable")):
    check("%s -> RU «%s» / EN «%s»" % (code, ru, en),
          re.search(r"%s:\s*\{[^}]*ru:\s*'%s'[^}]*en:\s*'%s'" % (code, ru, en), _view) is not None)

check("10-11. RU и EN покрыты для всех %d кодов" % len(CODES),
      all(re.search(r"\b%s:\s*\{[^}]*ru:[^}]*en:" % c, _view) for c in CODES))
check("12-13. у каждой записи есть CSS-класс severity",
      all(re.search(r"\b%s:\s*\{[^}]*cls:\s*'(ok|warn|bad)'" % c, _view) for c in CODES))
check("39. готов / настройка / недоступен различаются классами",
      re.search(r"ready:\s*\{[^}]*cls:\s*'ok'", _view)
      and re.search(r"attention_required:\s*\{[^}]*cls:\s*'warn'", _view)
      and re.search(r"blocked:\s*\{[^}]*cls:\s*'bad'", _view))
check("14. дублирующих записей нет",
      all(_view.count("%s:" % c) == 1 for c in CODES))
check("у сводки подписи из ТОЙ ЖЕ таблицы",
      all(re.search(r"\b%s:\s*\{[^}]*sum_ru:[^}]*sum_en:" % c, _view) for c in CODES))


section("бейдж, сводка и запасной вариант (пункты 8-9, 16-25)")

check("8. сырой код в бейдже больше не печатается",
      "{{ c.effective_status }}" not in HTML)
check("16-19. бейдж берёт подпись из общей таблицы",
      "feedStatusLabel(c.effective_status)" in HTML
      and "feedStatusClass(c.effective_status)" in HTML)
check("9. код остался только диагностикой в title",
      ':title="c.effective_status"' in HTML)
check("15b. сводка использует тот же реестр, а не свои подписи",
      HTML.count("feedSummaryLabel(") == 4
      and "'внимание' : 'attention'" not in HTML and "'нельзя' : 'blocked'" not in HTML)
check("25. сводка не показывает сырые коды",
      not re.search(r"\{\{\s*lang==='ru'\s*\?\s*'готовы'", HTML))
check("7. незнакомый код -> понятная подпись, а не snake_case",
      "'Неизвестное состояние'" in JS and "'Unknown state'" in JS)
check("37. запасной вариант не показывает сырой snake_case основным текстом",
      re.search(r"if \(!v\) return \{ label: ru \? 'Неизвестное состояние'", JS) is not None)
check("36. у сводки тоже есть безопасный запасной вариант",
      re.search(r"if \(!v\) return ru \? 'прочие' : 'other'", JS) is not None)
check("6-7b. helper не решает вопрос выбираемости и не трогает payload",
      "selectable" not in _view and "readiness" not in _view)
check("40. бейдж содержит текст, а не только цвет",
      "feedStatusLabel(" in HTML)
check("41. причина выводится отдельной строкой и не дублирует бейдж",
      "feedReasonText(c.reason)" in HTML)


section("сценарии со скриншота (пункты 16-24)")

check("16-17. X7/X10 (нет источника) -> «Требуется настройка»",
      re.search(r"attention_required:\s*\{[^}]*ru:\s*'Требуется настройка'", _view) is not None)
check("18-19. X8/X11 (материал не совпал) -> «Недоступен»",
      re.search(r"blocked:\s*\{[^}]*ru:\s*'Недоступен'", _view) is not None)
check("21. причина несовпадения материала уже понятна и не менялась",
      "'Материал катушки не совпадает с материалом файла.'" in JS)
check("23-24. сводка считает настройку и недоступность РАЗНЫМИ категориями",
      "feedSummaryLabel('attention_required')" in HTML
      and "feedSummaryLabel('blocked')" in HTML
      and "feedSummary.attention_required" in HTML and "feedSummary.blocked" in HTML)
check("22. выбираемость варианта решает backend, представление её не меняет",
      "feedStatusLabel" not in ORCH and "FEED_STATUS_VIEW" not in ORCH)


section("защитные границы не тронуты (пункты 26-32, 47-54)")

check("30. предохранитель автоотправки остаётся выключенным",
      _DISPATCH_OFF)
check("26-29+31. решения планировщика и порог покоя не менялись",
      '"bambu": ("IDLE",)' in open(os.path.join(REPO, "server.py"),
                                   encoding="utf-8", errors="surrogateescape").read()
      and "IDLE_NOT_PROOF" in ORCH)
check("32. представление не меняет число готовых вариантов",
      "feedSummary.ready" in HTML and "FEED_STATUS_VIEW" not in ORCH)
check("47-53. таблица представления не имеет побочных эффектов",
      not any(x in _view for x in ("fetch(", "localStorage", "sessionStorage", "await",
                                   "dispatch", "reserve", "queue")))
check("54a. метка не попадает в производственный код",
      SENTINEL not in JS and SENTINEL not in HTML and SENTINEL not in ORCH)
check("54b. незнакомый код (в т.ч. метка) не выводится сырым",
      "map[key] || key" in JS or "'Неизвестное состояние'" in JS)

section("текст про автоматическую отправку")

check("новый текст разделяет сохранение плана и реальную отправку",
      "Выбор источника только сохраняет план. Автоматическая отправка на принтер пока отключена." in HTML
      and "Choosing a source only saves the plan." in HTML)
check("агрессивное «НЕ» заглавными убрано",
      "Выбор источника НЕ запускает печать" not in HTML)
check("кнопок запуска не добавлено",
      HTML.count("feedStatusLabel(") == 1)

print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
