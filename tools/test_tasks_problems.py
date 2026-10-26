# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.895 — «Задачи: заметнее показывать проблемы».

ЗАМЫСЕЛ ПРОВЕРКИ. Сервер и раньше считал два признака беды — файла нет на диске и файл не
подходит ни одному принтеру фермы, — но интерфейс их не показывал: сломанная задача выглядела
как исправная. Здесь проверяется НАСТОЯЩИЙ код приложения: функция разбора проблем достаётся
из web/app.js и исполняется в Node, а разметка проверяется на месте — значок стоит в строке
задачи и не добавляет таблице колонку.

Отдельно проверяется честность: незнакомую причину «состав плиты не распознан» интерфейс
показывает КАК ЕСТЬ, сырым ключом, а не выдумывает текст.

БЕЗОПАСНОСТЬ: только чтение файлов и исполнение чистых функций в Node. Ни сети, ни принтеров,
ни базы.

Запуск:  python tools/test_tasks_problems.py
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
SENTINEL = "TASKS_PROBLEMS_SENTINEL_2_895"
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8", errors="replace").read()
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
HINTS = io.open(os.path.join(ROOT, "web", "composables", "helpHints.js"), encoding="utf-8").read()
NODE = r"C:\Program Files\nodejs\node.exe"
_node = NODE if os.path.exists(NODE) else "node"
Q = chr(39)
DQ = chr(34)
NL = chr(10)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def _extract(name):
    """Кусок исходника приложения от `const <name> = ` до закрывающей строки `    };`."""
    i = APPJS.find("    const %s = " % name)
    if i < 0:
        return ""
    j = APPJS.find(NL + "    };", i)
    return APPJS[i:j + len(NL + "    };")] if j > 0 else ""


print("--- сервер отдаёт наверх то, что знает ---")
check("1. причина и точность разбора читаются из базы",
      "SELECT filename, status, total, parts_json, reason, confidence FROM staging_part_counts" in SRV)
check("2. схема таблицы НЕ менялась",
      "CREATE TABLE IF NOT EXISTS staging_part_counts (filename TEXT PRIMARY KEY, status TEXT, "
      "total INTEGER, parts_json TEXT, source TEXT, confidence TEXT, reason TEXT, parser_version TEXT)" in SRV)
check("3. причина уходит в список задач полем part_reason",
      SRV.count('r["part_reason"]') == 2)
check("4. признаки беды сервер считал и раньше — их не трогали",
      'r["missing"] = (fp is None)' in SRV and 'r["compatible_pids"]' in SRV)

print("--- разбор проблем: настоящая функция приложения в Node ---")
_FN = _extract("stagingProblems")
_REASON = _extract("stagingPartReason")
_TABLE = _extract("PART_REASON_TEXT")
check("5. функция проблем найдена в приложении", bool(_FN.strip()))
check("6. таблица причин и её разбор найдены", bool(_REASON.strip()) and bool(_TABLE.strip()))

#  Случаи: [файл задачи, есть ли принтеры на ферме] -> какие метки ждём.
CASES = [
    ({"missing": True, "is_printable": True, "compatible_pids": ["p1"]}, 1, ["missing"]),
    ({"missing": True, "is_printable": True, "compatible_pids": []}, 1, ["missing"]),
    ({"missing": False, "is_printable": True, "compatible_pids": []}, 1, ["nofit"]),
    ({"missing": False, "is_printable": True, "compatible_pids": []}, 0, []),
    ({"missing": False, "is_printable": False, "compatible_pids": []}, 1, []),
    ({"missing": False, "is_printable": True, "compatible_pids": ["p1", "p2"]}, 1, []),
    ({"missing": False, "is_printable": True}, 1, []),
    (None, 1, []),
]
REASON_CASES = [
    ({"part_reason": "object_names_missing"}, "the file has no object names"),
    ({"part_reason": "time_limit_exceeded"}, "parsing took too long and was stopped"),
    ({"part_reason": "brand_new_reason_from_future"}, "brand_new_reason_from_future"),
    ({"part_reason": ""}, ""),
    ({}, ""),
]
_h = NL.join([
    "const tr = (s) => s;",
    "let FLEET = 1;",
    "const printers = { get value() { return FLEET ? [{id:'p1'}] : []; } };",
    _TABLE.replace("    const PART_REASON_TEXT", "const PART_REASON_TEXT"),
    _REASON.replace("    const stagingPartReason", "const stagingPartReason"),
    _FN.replace("    const stagingProblems", "const stagingProblems"),
    "const keys = [], levels = [];",
    "for (const c of " + json.dumps([[c[0], c[1]] for c in CASES]) + ") {",
    "  FLEET = c[1];",
    "  const r = stagingProblems(c[0]);",
    "  keys.push(r.map(x => x.key));",
    "  levels.push(r.map(x => x.level));",
    "}",
    "FLEET = 1;",
    "const reasons = " + json.dumps([c[0] for c in REASON_CASES]) + ".map(f => stagingPartReason(f));",
    "const tips = stagingProblems({missing:true}).map(x => String(x.tip || ''));",
    "console.log('@@' + JSON.stringify({ keys, levels, reasons, tips }) + '@@');",
]) + NL
_td = tempfile.mkdtemp(prefix="fm895_")
_hp = os.path.join(_td, "h.mjs")
io.open(_hp, "w", encoding="utf-8", newline=NL).write(_h)
res = None
try:
    r = subprocess.run([_node, _hp], capture_output=True, timeout=120)
    m = re.search(r"@@(.*)@@", (r.stdout or b"").decode("utf-8", "replace"), re.S)
    res = json.loads(m.group(1)) if m else None
    if res is None:
        check("7. функции исполнились в Node", False,
              ((r.stderr or b"").decode("utf-8", "replace"))[-300:])
except Exception as e:
    check("7. функции исполнились в Node", False, str(e))
finally:
    try:
        os.remove(_hp)
        os.rmdir(_td)
    except Exception:
        pass

if res:
    check("7. функции исполнились в Node", True)
    check("8. исчезнувший файл всегда виден как беда",
          res["keys"][0] == ["missing"] and res["levels"][0] == ["bad"], res["keys"][0])
    check("9. у сломанного файла показывается ОДНА главная беда, а не две сразу",
          res["keys"][1] == ["missing"], res["keys"][1])
    check("10. файл не для одной модели фермы отмечен предупреждением",
          res["keys"][2] == ["nofit"] and res["levels"][2] == ["warn"], res["keys"][2])
    check("11. на ферме без принтеров это не беда задачи",
          res["keys"][3] == [], res["keys"][3])
    check("12. файл, который сначала надо нарезать, не считается сломанным",
          res["keys"][4] == [], res["keys"][4])
    check("13. исправная задача меток не получает",
          res["keys"][5] == [] and res["keys"][6] == [], res["keys"][5:7])
    check("14. пустая задача не роняет экран", res["keys"][7] == [], res["keys"][7])
    check("15. у каждой метки есть человеческое пояснение",
          bool(res["tips"]) and all(len(t) > 30 for t in res["tips"]), res["tips"])
    check("16. известная причина переводится в человеческий текст",
          res["reasons"][0] == REASON_CASES[0][1] and res["reasons"][1] == REASON_CASES[1][1],
          res["reasons"][:2])
    check("17. НЕЗНАКОМАЯ причина показывается как есть, а не выдумывается",
          res["reasons"][2] == "brand_new_reason_from_future", res["reasons"][2])
    check("18. без причины ничего не показывается",
          res["reasons"][3] == "" and res["reasons"][4] == "", res["reasons"][3:])

print("--- разметка ---")


def _task_row():
    i = IDX.find('class="pvrow qtpvrow pvpart"')
    return IDX[i:i + 6000] if i >= 0 else ""


_row = _task_row()
check("19. метки стоят в строке задачи, под именем файла",
      0 < _row.find('class="pvnamecol"') < _row.find('class="qtprob"'), bool(_row))
#  Колонок ровно шесть, и колонки количества шире 64 px. Ширина здесь не украшение:
#  ИЗМЕРЕНО в браузере — при 64 px кнопки «−»/«+» сжимали поле так, что «100» обрезалось.
check("20. колонок в таблице шесть, и в поле количества помещается число из трёх-четырёх знаков",
      IDX.count('class="pvc ctr" data-help="qt-printing"') == 2
      and ".pvrow.qtpvrow{grid-template-columns:64px minmax(0,1fr) 84px 84px 104px 104px;}" in CSS
      and ".qtqty .qtpv-qty{flex:1 1 auto;" in CSS)
check("21. метка красная или жёлтая — по тяжести",
      ":class=" + DQ + Q + "qtprob-" + Q + " + pb.level" + DQ in IDX
      and ".qtprob-bad{" in CSS and ".qtprob-warn{" in CSS)
check("22. пояснение видно при наведении", ':title="pb.tip"' in _row)
#  Alpha 2.900: кнопка появляется при проблемах И НЕ ИСЧЕЗАЕТ, пока отбор включён — иначе
#  владелец остаётся с пустым списком и без единого подсвеченного отбора. Повторное нажатие
#  возвращает «Все».
check("23. кнопка «Проблемы» появляется при проблемах и не исчезает, пока отбор включён",
      'v-if="stagingProblemCount || stStatus===' + Q + "problem" + Q + '"' in IDX
      and "stStatus = (stStatus===" + Q + "problem" + Q + " ? " + Q + "all" + Q + " : "
          + Q + "problem" + Q + ")" in IDX)
check("24. отбор «с проблемами» работает в самом списке",
      "if (stStatus.value === " + Q + "problem" + Q + ") return base.filter(f => stagingProblems(f).length > 0);" in APPJS)
check("25. причина «состав не распознан» показана в раскрытии задачи",
      "stagingPartReason(f)" in IDX and 'class="pvsub qtpv-why"' in IDX)
check("26. стили меток описаны",
      ".qtprob{" in CSS and ".qtprob-b{" in CSS and ".qtprob-filter{" in CSS and ".qtpv-why{" in CSS)
check("27. функции отданы в шаблон",
      "stagingProblems, stagingProblemCount, stagingPartReason," in APPJS)
check("28. подписи переведены на русский",
      '"file is gone": "файла нет"' in APPJS
      and '"no printer fits": "нет подходящего принтера"' in APPJS
      and '"Problems": "Проблемы"' in APPJS
      and '"the file has no object names": "в файле нет имён объектов"' in APPJS)
check("29. подсказка объясняет обе метки",
      '"qt-problem"' in HINTS and "файла нет" in HINTS and "нет подходящего принтера" in HINTS)
#  2.961: меток пять — в 2.0 чип у имени и кнопка отбора, в 3.0 значок беды на кнопке принтера
#  у задачи и у детали проекта. Ключ подсказки у всех один.
check("30. у меток и кнопки есть подсказка", IDX.count('data-help="qt-problem"') == 5)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
