# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.896 — «Задачи: группировка по проекту».

ЗАМЫСЕЛ ПРОВЕРКИ. У задач нет и не заводится своей связи с проектом (это меняло бы схему базы).
Связь выводится ТОЧНЫМ совпадением файла: тот же путь на диске либо то же имя. Проверяется это
на трёх уровнях, и каждый — исполнением, а не чтением глазами:

  1. Запрос к базе. Из server.py достаются НАСТОЯЩИЕ CREATE TABLE и НАСТОЯЩИЙ SELECT, поднимается
     sqlite в памяти, кладутся выдуманные проекты и файлы — и проверяется, что связь находится,
     удалённый проект не участвует, а спорное совпадение (одно имя в двух проектах) не даёт связи.
  2. Разбор на группы. Функция группировки достаётся из web/app.js и исполняется в Node.
  3. Вид. Страница поднимается в браузере, кнопки группировки нажимаются по-настоящему.

БЕЗОПАСНОСТЬ: sqlite только в памяти, рабочая база не открывается; браузерный стенд отвечает
синтетическими данными; ни сети наружу, ни принтеров.

Запуск:  python tools/test_tasks_grouping.py
"""
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "TASKS_GROUPING_SENTINEL_2_896"
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8", errors="replace").read()
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
HINTS = io.open(os.path.join(ROOT, "web", "composables", "helpHints.js"), encoding="utf-8").read()
NODE = r"C:\Program Files\nodejs\node.exe"
_node = NODE if os.path.exists(NODE) else "node"
BS = chr(92)
NL = chr(10)
Q = chr(39)

PASS = FAIL = 0


DQ = chr(34)


def _between(text, start, end):
    """Кусок исходника от строки start (включительно) до строки end (не включая)."""
    i = text.find(start)
    j = text.find(end, i + len(start)) if i >= 0 else -1
    return text[i:j] if (i >= 0 and j > i) else ""


def _func_src(text, name):
    """Исходник функции верхнего уровня целиком (до трёх пустых строк подряд не бывает —
    берём до следующей строки, начинающейся без отступа)."""
    i = text.find("def %s(" % name)
    if i < 0:
        return ""
    out = []
    for line in text[i:].split(NL):
        if out and line and not line[0].isspace() and not line.startswith("def %s(" % name):
            break
        out.append(line)
    return NL.join(out)


def _dedent(src):
    """Снять общий отступ, чтобы кусок кода из функции можно было исполнить отдельно."""
    lines = src.split(NL)
    pads = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    p = min(pads) if pads else 0
    return NL.join((l[p:] if len(l) >= p else l) for l in lines)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


print("--- 1. запрос к базе исполняется по-настоящему ---")


def _create_of(table):
    m = re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % table, SRV, re.S)
    return m.group(1) if m else ""


_c_projects = _create_of("projects")
_c_files = _create_of("project_files")
check("1. описания таблиц найдены в сервере", bool(_c_projects) and bool(_c_files))

#  Запрос собран из нескольких строк-литералов подряд — склеиваем их ровно так же, как это
#  делает сам Python при чтении исходника.
_blk = re.search(r"_pfiles = conn_p\.execute\(\s*((?:\"[^\"]*\"\s*)+)\)\.fetchall\(\)", SRV, re.S)
_sql = "".join(re.findall(r'"([^"]*)"', _blk.group(1))) if _blk else ""
check("2. запрос связи задач с проектами найден в сервере", "SELECT pf.filename" in _sql, _sql[:80])

if _sql:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(_c_projects)
    con.execute(_c_files)
    con.execute("INSERT INTO projects (id, name, is_deleted) VALUES ('p1', 'Заказ Иванов', 0)")
    con.execute("INSERT INTO projects (id, name, is_deleted) VALUES ('p2', 'Аврал', 0)")
    con.execute("INSERT INTO projects (id, name, is_deleted) VALUES ('p3', 'Удалённый', 1)")
    con.execute("INSERT INTO projects (id, name, is_deleted, is_archived) VALUES ('p4', 'Архивный', 0, 1)")
    con.execute("INSERT INTO project_files (id, project_id, filename, src_path) VALUES "
                "('f1', 'p1', 'korpus.gcode', 'C:" + BS + "Zakazy" + BS + "Ivanov" + BS + "korpus.gcode')")
    con.execute("INSERT INTO project_files (id, project_id, filename, src_path) VALUES "
                "('f2', 'p2', 'kryshka.gcode', '')")
    con.execute("INSERT INTO project_files (id, project_id, filename, src_path) VALUES "
                "('f3', 'p3', 'staroe.gcode', '')")
    con.execute("INSERT INTO project_files (id, project_id, filename, src_path) VALUES "
                "('f6', 'p4', 'arhivnoe.gcode', '')")
    #  Спорное совпадение: одно и то же имя лежит в ДВУХ живых проектах.
    con.execute("INSERT INTO project_files (id, project_id, filename, src_path) VALUES "
                "('f4', 'p1', 'obshee.gcode', '')")
    con.execute("INSERT INTO project_files (id, project_id, filename, src_path) VALUES "
                "('f5', 'p2', 'obshee.gcode', '')")
    rows = [dict(r) for r in con.execute(_sql).fetchall()]
    con.close()
    names = sorted((r["fn"], r["pname"]) for r in rows)
    check("3. запрос отдаёт файлы живых проектов", ("korpus.gcode", "Заказ Иванов") in names
          and ("kryshka.gcode", "Аврал") in names, names)
    check("4. файлы УДАЛЁННОГО проекта в связь не попадают",
          all(r["pname"] != "Удалённый" for r in rows), [r["pname"] for r in rows])
    #  Архивный проект не виден на экране «Проекты». Подписать задачу его именем — значит
    #  сослаться на то, чего владелец не найдёт.
    check("4a. файлы АРХИВНОГО проекта в связь не попадают",
          all(r["pname"] != "Архивный" for r in rows), [r["pname"] for r in rows])
    #  ГЛАВНОЕ ОТЛИЧИЕ ОТ ПРЕЖНЕЙ ВЕРСИИ НАБОРА (2.900). Раньше правило связи было переписано
    #  здесь копией — проверка оставалась зелёной, даже если правило в server.py сломать насмерть.
    #  Теперь из server.py берётся НАСТОЯЩИЙ код: и построение карт, и сама подстановка.
    _map_src = _between(SRV, "    _by_name, _by_path = {}, {}", "    for r in rows:")
    _lookup_src = _between(SRV, "        _pr = _by_path.get(",
                           "        r[" + DQ + "project_id" + DQ + "], r[" + DQ + "project_name" + DQ + "] = ")
    _key_src = _func_src(SRV, "_staging_path_key")
    check("5a. код связи взят из сервера, а не переписан в тесте",
          bool(_map_src.strip()) and bool(_lookup_src.strip()) and bool(_key_src.strip()),
          (len(_map_src), len(_lookup_src), len(_key_src)))

    #  Хвост — сама строка подстановки: от её начала до конца строки.
    _mark = "        r[" + DQ + "project_id" + DQ + "], r[" + DQ + "project_name" + DQ + "] = "
    _ti = SRV.find(_mark)
    _tail = SRV[_ti:SRV.find(NL, _ti) + 1] if _ti >= 0 else ""
    NS = {"os": os}
    exec(compile(_key_src, "<server>", "exec"), NS)
    NS["_pfiles"] = rows
    exec(compile(_dedent(_map_src), "<server>", "exec"), NS)
    _LOOKUP = _dedent(_lookup_src + _tail)

    def _link(filename, src_path=""):
        """Настоящая подстановка сервера для одной задачи."""
        loc = dict(NS)
        loc["r"] = {"filename": filename, "src_path": src_path}
        loc["sp"] = src_path
        exec(compile(_LOOKUP, "<server>", "exec"), loc)
        return (loc["r"].get("project_id"), loc["r"].get("project_name"))

    check("5. одно имя в двух проектах связи НЕ даёт (наугад не выбираем)",
          _link("obshee.gcode") == ("", ""), _link("obshee.gcode"))
    check("6. однозначное имя связь даёт",
          _link("korpus.gcode") == ("p1", "Заказ Иванов"), _link("korpus.gcode"))
    check("6a. файл удалённого проекта связи не даёт", _link("staroe.gcode") == ("", ""),
          _link("staroe.gcode"))
    check("6b. файл архивного проекта связи не даёт", _link("arhivnoe.gcode") == ("", ""),
          _link("arhivnoe.gcode"))
    check("6c. незнакомый файл связи не даёт", _link("nikomu_ne_izvestnyi.gcode") == ("", ""),
          _link("nikomu_ne_izvestnyi.gcode"))
    check("6d. регистр имени значения не имеет", _link("KORPUS.GCODE") == ("p1", "Заказ Иванов"),
          _link("KORPUS.GCODE"))
    #  Путь сильнее имени: если он совпал, берём проект по пути.
    _by_path_case = _link("obshee.gcode", "C:" + BS + "Zakazy" + BS + "Ivanov" + BS + "korpus.gcode")
    check("6e. совпадение пути перевешивает спорное совпадение имени",
          _by_path_case == ("p1", "Заказ Иванов"), _by_path_case)

check("7. сервер кладёт проект в каждую задачу",
      'r["project_id"], r["project_name"]' in SRV and "_staging_path_key" in SRV)
check("8. схема БД не менялась ради этого",
      "ALTER TABLE staging_files ADD COLUMN project" not in SRV
      and SRV.count('"CREATE TABLE IF NOT EXISTS staging_files (filename TEXT PRIMARY KEY, status TEXT '
                    "DEFAULT 'ready', printer_id TEXT DEFAULT '', order_idx INTEGER DEFAULT 0, "
                    "required_qty INTEGER DEFAULT 1, printed_qty INTEGER DEFAULT 0, notes TEXT DEFAULT '')\"") == 1)

print("--- 2. разбор на группы: настоящая функция приложения в Node ---")
_i = APPJS.find("    const ST_GROUPS = ")
_j = APPJS.find(NL + "    });", APPJS.find("    const stagingViewGroups = computed("))
BLOCK = APPJS[_i:_j + len(NL + "    });")] if (_i >= 0 and _j > _i) else ""
check("9. блок группировки найден в приложении", bool(BLOCK.strip()))

FILES = [
    {"filename": "korpus.gcode", "project_id": "p1", "project_name": "Заказ Иванов",
     "src_path": "C:" + BS + "Zakazy" + BS + "Ivanov" + BS + "korpus.gcode",
     "required_qty": 5, "printed_qty": 1},
    {"filename": "kryshka.gcode", "project_id": "p1", "project_name": "Заказ Иванов",
     "src_path": "C:" + BS + "Zakazy" + BS + "Ivanov" + BS + "kryshka.gcode",
     "required_qty": 3, "printed_qty": 3},
    {"filename": "srochno.gcode", "project_id": "p2", "project_name": "Аврал",
     "src_path": "D:/Srochnoe/srochno.gcode", "required_qty": 2, "printed_qty": 0},
    {"filename": "sam_po_sebe.gcode", "project_id": "", "project_name": "",
     "src_path": "", "required_qty": 1, "printed_qty": 0},
]
_h = NL.join([
    "const localStorage = { getItem: () => null, setItem: () => {} };",
    "const ref = (v) => ({ value: v });",
    "const computed = (fn) => ({ get value() { return fn(); } });",
    "const tr = (s) => s;",
    "const sortStaging = (a) => a;",
    "const filterStagingView = (a) => a;",
    "const stagingFiles = ref(" + json.dumps(FILES) + ");",
    "const lang = ref('ru');",
    BLOCK.replace("    const ", "const ").replace("    try {", "try {").replace(NL + "    ", NL),
    "const out = {};",
    "for (const mode of ['none', 'project', 'folder']) {",
    "  stGroup.value = mode;",
    "  out[mode] = stagingViewGroups.value.map(g => ({ key: g.key, title: g.title, sub: g.sub,",
    "     n: g.files.length, req: g.req, prnt: g.prnt, pct: g.pct, closed: g.closed }));",
    "}",
    "stGroup.value = 'project';",
    "toggleStGroup('p1');",
    "out.closedAfterClick = stagingViewGroups.value.map(g => [g.key, g.closed]);",
    "setStGroup('musor-kotorogo-net');",
    "out.badMode = stGroup.value;",
    "setStGroup('folder');",
    "out.goodMode = stGroup.value;",
    "out.plural = [1, 2, 5, 11, 21, 22, 25, 101, 104].map(n => tasksWord(n));",
    "lang.value = 'en';",
    "out.pluralEn = [1, 2].map(n => tasksWord(n));",
    "lang.value = 'ru';",
    "console.log('@@' + JSON.stringify(out) + '@@');",
]) + NL
_td = tempfile.mkdtemp(prefix="fm896_")
_hp = os.path.join(_td, "h.mjs")
io.open(_hp, "w", encoding="utf-8", newline=NL).write(_h)
G = None
try:
    r = subprocess.run([_node, _hp], capture_output=True, timeout=120)
    m = re.search(r"@@(.*)@@", (r.stdout or b"").decode("utf-8", "replace"), re.S)
    G = json.loads(m.group(1)) if m else None
    if G is None:
        check("10. группировка исполнилась в Node", False,
              ((r.stderr or b"").decode("utf-8", "replace"))[-300:])
except Exception as e:
    check("10. группировка исполнилась в Node", False, str(e))
finally:
    try:
        os.remove(_hp)
        os.rmdir(_td)
    except Exception:
        pass

if G:
    check("10. группировка исполнилась в Node", True)
    check("11. без группировки список остаётся ОДНИМ куском и без заголовка",
          len(G["none"]) == 1 and G["none"][0]["title"] == "" and G["none"][0]["n"] == 4, G["none"])
    _p = G["project"]
    check("12. по проекту получается три группы", len(_p) == 3, [g["title"] for g in _p])
    check("13. группы идут по алфавиту, «Вне проектов» — последней",
          [g["title"] for g in _p] == ["Аврал", "Заказ Иванов", "Outside projects"],
          [g["title"] for g in _p])
    _iv = [g for g in _p if g["title"] == "Заказ Иванов"][0]
    check("14. в группе считается свой итог", _iv["n"] == 2 and _iv["req"] == 8
          and _iv["prnt"] == 4 and _iv["pct"] == 50, _iv)
    _f = G["folder"]
    check("15. по папке группы названы по последней папке пути",
          sorted(g["title"] for g in _f) == sorted(["Ivanov", "Srochnoe", "No folder"]),
          [g["title"] for g in _f])
    check("16. у группы-папки виден полный путь",
          any(g["sub"].endswith("Ivanov") for g in _f), [g["sub"] for g in _f])
    check("17. задача без пути уходит в «Без папки», и она последняя",
          _f[-1]["title"] == "No folder" and _f[-1]["n"] == 1, _f[-1])
    check("18. клик по заголовку сворачивает ИМЕННО эту группу",
          dict(G["closedAfterClick"]).get("p1") is True
          and all(v is False for k, v in G["closedAfterClick"] if k != "p1"),
          G["closedAfterClick"])
    check("19. неизвестный способ группировки не принимается",
          G["badMode"] == "project" and G["goodMode"] == "folder",
          (G["badMode"], G["goodMode"]))

if G:
    #  «1 задач» вместо «1 задача» — такой же дефект, как обрезанный текст: владелец читает
    #  это каждый день. Формы проверяются на числах, где русский язык меняет окончание.
    check("19a. слово «задача» склоняется по числу",
          G.get("plural") == ["задача", "задачи", "задач", "задач", "задача", "задачи",
                              "задач", "задача", "задачи"], G.get("plural"))
    check("19b. в английском две формы", G.get("pluralEn") == ["task", "tasks"], G.get("pluralEn"))

print("--- 3. разметка ---")
check("20. переключатель группировки стоит рядом с отборами",
      "qtgrp-pick" in IDX and "setStGroup(m[0])" in IDX
      and "[['none','No grouping'],['project','By project'],['folder','By folder']]" in IDX)
check("21. заголовок группы показывается только при группировке",
      'v-if="g.title" class="qtgrp"' in IDX and 'v-for="g in stagingViewGroups"' in IDX)
check("22. задачи стоят ВНУТРИ своей группы",
      IDX.find('v-for="g in stagingViewGroups"') < IDX.find('v-for="(f, fi) in g.files"')
      < IDX.find('class="pvrow qtpvrow pvpart"'))
check("23. свёрнутая группа не рисует свои задачи", 'v-if="!g.closed"' in IDX)
check("24. в заголовке видно количество и итог",
      "tasksWord(g.files.length)" in IDX and "g.pct" in IDX)
check("25. колонок в таблице не прибавилось",
      IDX.count('class="pvc ctr" data-help="qt-printing"') == 2
      and ".pvrow.qtpvrow{grid-template-columns:64px minmax(0,1fr) 84px 84px 104px 104px;}" in CSS)
check("26. стили групп описаны",
      ".qtgrp{" in CSS and ".qtgrp-pick{" in CSS and ".qtfilters{flex-wrap:wrap" in CSS)
check("27. подписи переведены",
      '"By project": "по проекту"' in APPJS and '"Outside projects": "Вне проектов"' in APPJS
      and '"No folder": "Без папки"' in APPJS)
check("28. подсказка объясняет, откуда берётся связь и что она НЕ доказательство",
      '"qt-group"' in HINTS and "ТАКИМ ЖЕ именем" in HINTS
      and "не доказательство" in HINTS and "не влияет" in HINTS)
#  ИЗМЕРЕНО: сервер кладёт задачам src_path='' намеренно (файл копируется в папку программы),
#  поэтому сегодня группировать по папке НЕ ПО ЧЕМУ. Способ обязан скрываться, а не показывать
#  единственную группу «Без папки» и выдавать её за работу.
check("29a. способ «по папке» показывается ТОЛЬКО когда путь у задач есть",
      "stagingFolderKnown" in APPJS
      and "m[0] !== " + Q + "folder" + Q + " || stagingFolderKnown" in IDX
      and "if (v === " + Q + "folder" + Q + " && !stagingFolderKnown.value) return;" in APPJS)
check("29b. переключатель группировки не показывается на телефоне",
      'v-if="!isMobile" class="qtgrp-pick"' in IDX)
check("29c. у «остатка» свой ключ в каждом способе — свёрнутость не перетекает",
      "key = " + Q + "__none:" + Q + " + stGroup.value" in APPJS)
check("29. функции отданы в шаблон",
      "stGroup, setStGroup, stGroupClosed, toggleStGroup, stagingViewGroups, stagingFolder," in APPJS)

print("--- 4. вид: кнопки нажимаются в настоящем браузере ---")
PRINTERS = [{"id": "p1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
             "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_0001", "access_code": ""}]
STAGING = []
for i, (fn, pid, pname, folder) in enumerate((
        ("korpus.gcode", "p1", "Заказ Иванов", "C:" + BS + "Zakazy" + BS + "Ivanov"),
        ("kryshka.gcode", "p1", "Заказ Иванов", "C:" + BS + "Zakazy" + BS + "Ivanov"),
        ("srochno.gcode", "p2", "Аврал", "D:" + BS + "Srochnoe"),
        ("sam_po_sebe.gcode", "", "", ""))):
    STAGING.append({
        "filename": fn, "status": "pending", "printer_id": "", "required_qty": 5 - i,
        "printed_qty": i, "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon",
        "is_printable": True, "notes": "", "src_path": (folder + BS + fn) if folder else "",
        "linked": bool(folder), "missing": False, "compatible_pids": ["p1"], "mtime": 0,
        "cb": "0-x", "parts": [], "part_status": None, "part_total": None,
        "part_reason": "", "part_confidence": "", "project_id": pid, "project_name": pname})

JS = r"""
return new Promise(function(res){
  var out = { steps: [] };
  function snap(tag){
    var heads = [].slice.call(document.querySelectorAll('.qtgrp')).map(function(h){
      var r = h.getBoundingClientRect();
      return { t: (h.querySelector('.qtgrp-t') || {}).textContent || '',
               n: (h.querySelector('.qtgrp-n') || {}).textContent || '',
               closed: h.classList.contains('closed'),
               w: Math.round(r.width), inView: r.left >= -1 };
    });
    var tbl = document.querySelector('.pvtbl.qtpv');
    out.steps.push({ tag: tag, heads: heads,
                     rows: document.querySelectorAll('.pvrow.qtpvrow.pvpart').length,
                     hscroll: tbl ? (tbl.scrollWidth - tbl.clientWidth) : -1,
                     docScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth });
  }
  function byText(sel, texts){
    var all = [].slice.call(document.querySelectorAll(sel));
    for (var i = 0; i < all.length; i++) {
      var t = (all[i].textContent || '').trim();
      for (var k = 0; k < texts.length; k++) if (t === texts[k]) return all[i];
    }
    return null;
  }
  setTimeout(function(){
    snap('без группировки');
    var b = byText('.qtgrp-pick button', ['по проекту', 'By project']);
    if (b) b.click();
    setTimeout(function(){
      snap('по проекту');
      var h = document.querySelector('.qtgrp');
      if (h) h.click();
      setTimeout(function(){
        snap('первая группа свёрнута');
        var f = byText('.qtgrp-pick button', ['по папке', 'By folder']);
        if (f) f.click();
        setTimeout(function(){ snap('по папке'); res(dump(out)); }, 350);
      }, 350);
    }, 350);
  }, 900);
});
"""

if not stage.engine_ready():
    check("30. браузерный движок доступен (без него вид проверить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    check("30. браузерный движок доступен", True)
    stage.set_api({"/api/printers": PRINTERS, "/api/staging": STAGING})
    R = stage.run(JS, window_size=(1600, 1000), settle_ms=2500,
                  extra_args=("--force-device-scale-factor=1.25",))
    stage.set_api(None)
    stage.stop()
    if not R:
        check("31. страница «Задач» построилась", False, str(stage.last_diag())[:200])
    else:
        check("31. страница «Задач» построилась", True)
        st = {x["tag"]: x for x in (R.get("steps") or [])}
        check("32. без группировки заголовков нет",
              st.get("без группировки", {}).get("heads") == []
              and st.get("без группировки", {}).get("rows") == 4,
              st.get("без группировки"))
        _pg = st.get("по проекту", {})
        check("33. кнопка «по проекту» раскладывает задачи по трём группам",
              len(_pg.get("heads") or []) == 3 and _pg.get("rows") == 4,
              [h.get("t") for h in (_pg.get("heads") or [])])
        _cl = st.get("первая группа свёрнута", {})
        check("34. клик по заголовку прячет задачи этой группы",
              len(_cl.get("heads") or []) == 3 and (_cl.get("rows") or 0) < 4
              and any(h.get("closed") for h in (_cl.get("heads") or [])),
              (_cl.get("rows"), [h.get("closed") for h in (_cl.get("heads") or [])]))
        _fg = st.get("по папке", {})
        check("35. кнопка «по папке» тоже работает",
              len(_fg.get("heads") or []) == 3, [h.get("t") for h in (_fg.get("heads") or [])])
        check("36. заголовки не вылезают за край и не рождают полосу прокрутки",
              all((s.get("hscroll") or 0) <= 0 and (s.get("docScroll") or 0) <= 0
                  and all(h.get("inView") for h in (s.get("heads") or []))
                  for s in (R.get("steps") or [])),
              [(s["tag"], s.get("hscroll"), s.get("docScroll")) for s in (R.get("steps") or [])])
        _diag = R.get("__diag") or {}
        check("37. консоль браузера чистая",
              not (_diag.get("consoleErrors") or _diag.get("pageErrors") or _diag.get("unhandled"))
              and not [w for w in (_diag.get("consoleWarnings") or []) if "Vue warn" in str(w)],
              json.dumps(_diag, ensure_ascii=False)[:220])

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
