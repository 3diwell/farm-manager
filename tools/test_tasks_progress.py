# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.893 — «Задачи: показ прогресса задачи».

ЗАМЫСЕЛ ПРОВЕРКИ. Прогресс считается в интерфейсе из двух чисел задачи («нужно», «напечатано»)
и живой телеметрии («печатается сейчас»). Здесь проверяется САМА АРИФМЕТИКА на настоящем коде
приложения — функция достаётся из web/app.js и исполняется в Node, — плюс то, что полоса
вставлена в свободное место строки и не добавляет колонку в таблицу.

БЕЗОПАСНОСТЬ: только чтение файлов и исполнение чистой функции в Node. Ни сети, ни принтеров.

Запуск:  python tools/test_tasks_progress.py
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = "TASKS_PROGRESS_SENTINEL_2_893"
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8", errors="replace").read()
NODE = r"C:\Program Files\nodejs\node.exe"
_node = NODE if os.path.exists(NODE) else "node"

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


# ── арифметика прогресса: НАСТОЯЩАЯ функция из app.js, исполненная в Node ──
def _extract(name):
    i = APPJS.find("    const %s = (" % name)
    if i < 0:
        return ""
    j = APPJS.find("\n    };", i)
    return APPJS[i:j + len("\n    };")] if j > 0 else ""


SRC = _extract("stagingProgress")
check("1. функция прогресса найдена в приложении", bool(SRC.strip()))

CASES = [
    ({"required_qty": 10, "printed_qty": 3}, 0, {"pct": 30, "livePct": 0, "left": 7, "complete": False}),
    ({"required_qty": 10, "printed_qty": 3}, 2, {"pct": 30, "livePct": 20, "left": 7, "complete": False}),
    ({"required_qty": 10, "printed_qty": 10}, 0, {"pct": 100, "livePct": 0, "left": 0, "complete": True}),
    ({"required_qty": 10, "printed_qty": 12}, 0, {"pct": 100, "livePct": 0, "left": 0, "complete": True}),
    ({"required_qty": 0, "printed_qty": 0}, 0, {"pct": 0, "livePct": 0, "left": 0, "complete": False}),
    ({"required_qty": 3, "printed_qty": 1}, 99, {"pct": 33, "livePct": 67, "left": 2, "complete": False}),
    ({"required_qty": 10, "printed_qty": -5}, 0, {"pct": 0, "livePct": 0, "left": 10, "complete": False}),
]
harness = ("const tr = (s) => s;\n"
           "let LIVE = 0;\n"
           "const liveStagingPrintingQty = () => LIVE;\n"
           + SRC.replace("    const stagingProgress", "const stagingProgress") + "\n"
           "const out = [];\n"
           "for (const c of " + json.dumps([[c[0], c[1]] for c in CASES]) + ") {\n"
           "  LIVE = c[1];\n"
           "  out.push(stagingProgress(c[0]));\n"
           "}\n"
           "console.log('@@' + JSON.stringify(out) + '@@');\n")
res = None
_td = tempfile.mkdtemp(prefix="fm893_")
_hp = os.path.join(_td, "h.mjs")
io.open(_hp, "w", encoding="utf-8", newline="\n").write(harness)
try:
    r = subprocess.run([_node, _hp], capture_output=True, timeout=120)
    m = re.search(r"@@(.*)@@", (r.stdout or b"").decode("utf-8", "replace"), re.S)
    res = json.loads(m.group(1)) if m else None
    if res is None:
        check("2. функция исполнилась в Node", False,
              ((r.stderr or b"").decode("utf-8", "replace"))[-200:])
except Exception as e:
    check("2. функция исполнилась в Node", False, str(e))
finally:
    try:
        os.remove(_hp)
        os.rmdir(_td)
    except Exception:
        pass

if res:
    check("2. функция исполнилась в Node", True)
    ok = True
    bad = []
    for (inp, live, want), got in zip(CASES, res):
        for k, v in want.items():
            if got.get(k) != v:
                ok = False
                bad.append((inp, live, k, v, got.get(k)))
    check("3. арифметика прогресса верна во всех случаях (в т.ч. ноль, перебор и живая печать)",
          ok, bad[:3])
    check("4. «печатается сейчас» никогда не выходит за 100 % вместе с напечатанным",
          all((g["pct"] + g["livePct"]) <= 100 for g in res), res)


def _in_task_row(idx):
    """Полоса обязана стоять В СТРОКЕ задачи, между именем файла и полем «нужно».

    Заголовок таблицы использует те же метки data-help, поэтому ищем именно строку данных:
    её начало — `class="pvrow qtpvrow pvpart"`.
    """
    i = idx.find('class="pvrow qtpvrow pvpart"')
    if i < 0:
        return False
    row = idx[i:i + 12000]   # 2.951: строка выросла — в ней ветки 2.0 и 3.0
    return 0 < row.find('class="pvnamecol"') < row.find('class="qtprog"') < row.find('data-help="qt-req"')


print("--- разметка и стиль ---")
#  Колонок в таблице должно остаться столько же: заголовок и ячейка «Печатается» — это две
#  строки одной и той же колонки, третьей быть не должно.
check("5. полоса живёт под именем файла, а не отдельной колонкой",
      'class="qtprog"' in IDX
      and IDX.count('class="pvc ctr" data-help="qt-printing"') == 2
      and _in_task_row(IDX))
check("6. заполненная и живая части — разные элементы",
      'class="qtprog-done"' in IDX and 'class="qtprog-live"' in IDX)
#  2.974: в оформлении 3.0 у строки задачи своя полоса, поэтому условие показа
#  дополнено «!ui3Mode». Сам гейт «нет плана — нет полосы» на месте.
check("7. полоса скрыта у задачи без плана (нужно 0)",
      'stagingProgress(f).req"' in IDX and 'v-if="!ui3Mode && stagingProgress(f).req"' in IDX)
check("8. подпись доступна и текстом, и подсказкой",
      'stagingProgressText(f)' in IDX and ':title="stagingProgressText(f)"' in IDX)
check("9. стили полосы описаны", ".qtprog-bar{" in CSS and ".qtprog-done{" in CSS
      and ".qtprog-live{" in CSS)
check("10. в шапке раздела показан общий процент",
      "stagingTotals.pct" in IDX and "pct: req ?" in APPJS.replace("const pct = req ?", "pct: req ?"))
check("11. подпись переведена на русский",
      '"printing now": "печатается"' in APPJS and '"of": "из"' in APPJS)
check("12. функции отданы в шаблон",
      "stagingProgress, stagingProgressText," in APPJS)

print("--- быстрая правка количества (Alpha 2.894) ---")
_STEP = _extract("stepStagingQty")
check("13. функция шага количества есть в приложении", bool(_STEP.strip()))

#  У каждой задачи СВОЁ имя файла: задержка сохранения хранится по имени, и разные задачи не
#  должны глушить сохранения друг друга.
_STEP_CASES = [
    ({"filename": "a.gcode", "required_qty": 3, "printed_qty": 1}, "required_qty", 1, 4),
    ({"filename": "b.gcode", "required_qty": 3, "printed_qty": 1}, "required_qty", -1, 2),
    ({"filename": "c.gcode", "required_qty": 0, "printed_qty": 0}, "required_qty", -1, 0),   # ниже нуля не уходим
    ({"filename": "d.gcode", "required_qty": 5, "printed_qty": 0}, "printed_qty", 1, 1),
    ({"filename": "e.gcode", "required_qty": 5, "printed_qty": 0}, "printed_qty", -1, 0),
]
_NL = chr(10)
_h = _NL.join([
    "let CAN = true;",
    "let saved = 0;",
    "const savedNames = [];",
    "const can = () => CAN;",
    "const markStagingDirty = () => {};",
    "const saveStaging = (f) => { saved += 1; savedNames.push(String(f && f.filename || '')); };",
    "const sleep = (ms) => new Promise(r => setTimeout(r, ms));",
    "const _stepTimers = {};",   # хранилище отложенных сохранений — объявлено в app.js рядом с функцией
    _STEP.replace("    const stepStagingQty", "const stepStagingQty"),
    "const out = [];",
    "for (const c of " + json.dumps([[c[0], c[1], c[2]] for c in _STEP_CASES]) + ") {",
    "  const f = Object.assign({}, c[0]);",
    "  stepStagingQty(f, c[1], c[2]);",
    "  out.push(f[c[1]]);",
    "}",
    "CAN = false;",
    "const noRight = { required_qty: 3 };",
    "stepStagingQty(noRight, 'required_qty', 1);",
    "CAN = true;",
    "const bogus = { required_qty: 3 };",
    "stepStagingQty(bogus, 'notes', 1);",
    "//  Alpha 2.900: сохранение уходит С ЗАДЕРЖКОЙ — ждём её, иначе считали бы нули.",
    "await sleep(600);",
    "const savedAfterCases = saved;",
    "const savedNamesAfterCases = savedNames.slice();",
    "//  Серия из ПЯТИ быстрых нажатий по ОДНОЙ задаче обязана уйти ОДНИМ сохранением с итогом.",
    "saved = 0;",
    "const burst = { filename: 'burst.gcode', required_qty: 0, printed_qty: 0 };",
    "for (let i = 0; i < 5; i++) stepStagingQty(burst, 'printed_qty', 1);",
    "const burstSavedImmediately = saved;",
    "await sleep(600);",
    "const burstSaves = saved;",
    "console.log('@@' + JSON.stringify({ out, noRight: noRight.required_qty, bogus,",
    "  saved: savedAfterCases, savedNames: savedNamesAfterCases, burstSavedImmediately, burstSaves,",
    "  burstValue: burst.printed_qty }) + '@@');",
]) + _NL
_td2 = tempfile.mkdtemp(prefix="fm894_")
_hp2 = os.path.join(_td2, "h.mjs")
io.open(_hp2, "w", encoding="utf-8", newline=chr(10)).write(_h)
_res2 = None
try:
    _r2 = subprocess.run([_node, _hp2], capture_output=True, timeout=120)
    _m2 = re.search(r"@@(.*)@@", (_r2.stdout or b"").decode("utf-8", "replace"), re.S)
    _res2 = json.loads(_m2.group(1)) if _m2 else None
    if _res2 is None:
        check("14. шаг исполнился в Node", False,
              ((_r2.stderr or b"").decode("utf-8", "replace"))[-200:])
except Exception as _e2:
    check("14. шаг исполнился в Node", False, str(_e2))
finally:
    try:
        os.remove(_hp2)
        os.rmdir(_td2)
    except Exception:
        pass

if _res2:
    check("14. шаг исполнился в Node", True)
    check("15. плюс и минус меняют ровно на одну штуку",
          _res2["out"] == [c[3] for c in _STEP_CASES], _res2["out"])
    check("16. ниже нуля значение не уходит", _res2["out"][2] == 0 and _res2["out"][4] == 0)
    check("17. без права на правку значение не меняется", _res2["noRight"] == 3, _res2["noRight"])
    check("18. чужое поле не трогается", _res2["bogus"] == {"required_qty": 3}, _res2["bogus"])
    #  Из пяти шагов два ничего не меняют (0 − 1 остаётся 0). Такие шаги НЕ должны
    #  дёргать сервер: лишний запрос на каждый бесполезный клик — это шум и нагрузка.
    check("19. сохраняются только настоящие изменения, пустые шаги сервер не дёргают",
          _res2["saved"] == 3, _res2["saved"])
    check("19a. каждая задача сохраняется отдельно, соседние не глушат друг друга",
          sorted(_res2.get("savedNames") or []) == ["a.gcode", "b.gcode", "d.gcode"],
          _res2.get("savedNames"))
    #  Alpha 2.900: пять быстрых нажатий = ОДИН запрос с итоговым числом. Раньше уходило пять
    #  одновременных запросов с абсолютным значением, и последним мог записаться не последний.
    check("19b. серия быстрых нажатий уходит одним сохранением, а не пятью",
          _res2.get("burstSavedImmediately") == 0 and _res2.get("burstSaves") == 1
          and _res2.get("burstValue") == 5,
          (_res2.get("burstSavedImmediately"), _res2.get("burstSaves"), _res2.get("burstValue")))

#  2.951: в 3.0 «Итог из План» — своя ячейка с теми же кнопками (2.0 + 3.0).
#  2.961: такие же кнопки появились у деталей проекта — в обычном виде и в правке.
#  У «Итога» право «счёт», у «Плана» — «проект», поэтому вторых меньше.
check("20. кнопки стоят у обоих полей и только при праве на правку",
      IDX.count("qtqty-btn") == 16 and IDX.count("stepStagingQty(f, 'required_qty'") == 4
      and IDX.count("stepStagingQty(f, 'printed_qty'") == 4
      and IDX.count("stepPartQty(pr.id, pp, 'required_qty'") == 4
      and IDX.count("stepPartQty(pr.id, pp, 'printed_qty'") == 4
      and IDX.count(chr(34) + 'can(' + chr(39) + 'project' + chr(39) + ')' + chr(34)
                    + ' class=' + chr(34) + 'qtqty-btn') == 12)
check("21. кнопки не открывают строку задачи по клику", IDX.count('@click.stop="stepStagingQty') == 8)
check("22. стиль кнопок описан и не расширяет колонку", ".qtqty-btn{" in CSS and ".qtqty{" in CSS)
check("23. подписи кнопок переведены",
      '"Minus one": "Убавить на одну"' in APPJS and '"Plus one": "Прибавить на одну"' in APPJS)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
