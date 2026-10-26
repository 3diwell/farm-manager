# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.961 — строка детали в проектах повторяет строку задачи (оформление 3.0).

ЗАЧЕМ. Владелец попросил: «отображение и поведение ячейки должно быть точно таким же, как
и в задачах», плюс столбец «Брак». Плюс беда (нет подходящего принтера, файла нет на диске)
показывается прямо на кнопке выбора принтера, а не чипом справа от имени.

Здесь проверяется ИСПОЛНЕНИЕМ: раскрытый проект в 3.0 — из чего состоит строка детали, что
кнопка синхронизации приходит от связанной ЗАДАЧИ и включает ту же связь, что беда рисуется
на рельсе, и что вход в правку (карандаш) не сдвигает столбцы.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_project_row_ui3.py
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "PROJECT_ROW_UI3_SENTINEL_2_961"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "ui3", "ui3.css"), encoding="utf-8").read()

#  Куски разметки вынесены в переменные: кавычки внутри мешают писать их в самой проверке.
_CLICK_SELF = chr(64) + chr(99) + "lick.self=" + chr(34) + "project2Expanded = " + chr(39) * 2 + chr(34)
_ESC_PROJ = "if (project2Expanded.value) { project2Expanded.value = " + chr(39) * 2 + "; return; }"
_HEAD_CLICK = chr(60) + "div " + chr(64) + "click=" + chr(34) + "project2Expanded = " + chr(39) * 2 + chr(34)

print("--- 1. устройство закреплено в файлах ---")
check("1. беда рисуется на кнопке принтера, а не чипом справа",
      'class="ui3-qtflag"' in IDX and "ui3-qtprob" not in IDX)
check("2. значок беды — сплошной треугольник без круга",
      "'alert-solid'" in io.open(os.path.join(ROOT, "web", "design", "icons.js"), encoding="utf-8").read()
      and "html.ui3-mode .ui3-qtflag { position: absolute; top: 2px; right: 2px; width: 14px" in CSS)
check("3. таблица деталей в 3.0 получает свой класс слоя",
      """class="pvtbl" :class="ui3Mode ? 'ui3-pv' : ''\"""" in IDX)
check("4. у строки детали те же столбцы, что у задачи, плюс «Брак»",
      "html.ui3-mode .pvtbl.ui3-pv .pvrow { grid-template-columns: 52px 56px minmax(96px,1fr) minmax(0,96px) 184px 72px 124px 52px; }" in CSS)
check("5. правка проекта стоит в ТОЙ ЖЕ сетке — вход в неё ничего не сдвигает",
      "html.ui3-mode .pvtbl.p2edit .pvrow { grid-template-columns: 52px 56px minmax(96px,1fr) minmax(0,96px) 184px 72px 124px 52px; }" in CSS)
check("6. связь детали с задачей ищется по проекту и имени детали",
      "const _partTaskIndex = computed(() => {" in APPJS and "const ui3PartTask = (pid, pp) =>" in APPJS)
check("7. кнопка синхронизации у детали переключает связь ТОЙ ЖЕ задачи",
      'toggleStagingSync(ui3PartTask(pr.id, pp))' in IDX
      and ':class="{on: ui3PartTask(pr.id, pp).project_sync}"' in IDX)
check("8. числа детали правятся кнопками «−/+» с тем же сохранением по полю",
      "const stepPartQty = (pid, pp, field, d) => {" in APPJS
      and "stepPartQty(pr.id, pp, 'printed_qty', 1)" in IDX
      and "stepPartQty(pr.id, pp, 'required_qty', -1)" in IDX)
check("9. заметка детали правится на месте, ключ — «pt:<id>»",
      """ui3NoteStart(pp, 'pt:' + pp.part_id)""" in IDX and "ui3NoteEditFor === ('pt:' + pp.part_id)" in IDX)
#  2.962: поведение строки стало как в задачах — щелчок не раскрывает панель, рельса печатает.
check("10a. щелчок по строке детали раскрывает панель только в 2.0",
      '@click="!ui3Mode && pvTogglePart(pp.part_id)"' in IDX
      and "html.ui3-mode .pvtbl.ui3-pv .pvpanel { display: none !important; }" in CSS)
check("10b. рельса детали — настоящая кнопка выбора принтера по первой плите",
      "onPrintBtn({flow:'project', pid:pr.id, fileId:pvFirstFid(pp), rowKey:'pt:' + pp.part_id}, pp.plates[0], $event)" in IDX
      and "printBtnActive('pt:' + pp.part_id) ? 'go' : ''" in IDX)
check("10c. наведение на предпросмотр детали даёт большой предпросмотр",
      IDX.count('class="thumb-big ui3-qtzoom hidden"') == 2)
check("10d. пустое место в проекте больше его не сворачивает; остаются заголовок и Escape",
      _CLICK_SELF not in IDX and _ESC_PROJ in APPJS and _HEAD_CLICK in IDX)
check("10. в 2.0 строка детали не изменилась: прежние колонки под своим условием",
      IDX.count("""<div v-if="!ui3Mode" class="pvc ctr pv-num" data-help="col-req">""") == 1
      and IDX.count("""<div v-if="!ui3Mode" class="pvc ctr pv-num" data-help="col-printing">""") == 1)

print()
print("--- 2. раскрытый проект в браузере ---")
_PRJ = {"id": "P1", "name": "Заказ 17", "due_date": ""}
_PARTS = {"project": _PRJ, "parts": [
    {"part_id": "pp1", "part_name": "Корпус_редуктора", "required_qty": 12, "printed_qty": 7, "status": "in_progress",
     "notes": "Печатать только на чёрном PETG", "rework_qty": 3, "rework_done": 1, "live_printers": ["b0"],
     #  Плита нужна, чтобы сосчиталось «сколько печатается сейчас»: счёт идёт по плитам детали.
     "plates": [{"filename": "korpus.gcode.3mf", "on_plate_qty": 1}], "order_idx": 0},
    {"part_id": "pp2", "part_name": "Крышка", "required_qty": 4, "printed_qty": 4, "status": "done", "notes": "",
     "rework_qty": 2, "rework_done": 2, "live_printers": [], "plates": [], "order_idx": 1},
    {"part_id": "pp3", "part_name": "Кронштейн_левый", "required_qty": 6, "printed_qty": 0, "status": "pending",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": [], "plates": [], "order_idx": 2}]}
_TREE = {"project": _PRJ, "nodes": [{"id": "f1", "name": "korpus.gcode.3mf", "type": "file", "is_printable": True,
                                     "target_model": "Bambu Lab X1 Carbon",
                                     "children": [{"id": "c1", "name": "Корпус_редуктора", "qty": 1}]}]}
#  У «Корпус_редуктора» есть задача, и у неё беда: файла нет на диске. У «Крышки» задача есть,
#  синхронизация выключена. У «Кронштейн_левый» задачи нет вовсе — полосы быть не должно.
_ST = [{"filename": "korpus.gcode.3mf", "status": "ready", "printer_id": "", "required_qty": 12, "printed_qty": 7,
        "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon", "is_printable": True, "notes": "", "src_path": "",
        "linked": False, "missing": True, "project_id": "P1", "project_name": "Заказ 17", "project_sync": True,
        "compatible_pids": [], "parts": [{"name": "Корпус_редуктора", "count": 1}], "part_total": 1},
       {"filename": "kryshka.gcode.3mf", "status": "ready", "printer_id": "", "required_qty": 4, "printed_qty": 4,
        "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon", "is_printable": True, "notes": "", "src_path": "",
        "linked": False, "missing": False, "project_id": "P1", "project_name": "Заказ 17", "project_sync": False,
        "compatible_pids": ["b0"], "parts": [{"name": "Крышка", "count": 1}], "part_total": 1}]

JS = r"""
return new Promise(function(res){
  var out = {};
  var done = function(){ try { res(dump(out)); } catch (e) { res(dump({fatal: String(e)})); } };
  var tab = function(re){ return [].slice.call(document.querySelectorAll('.ui3-rtabs .fm-seg-b')).filter(function(b){ return re.test(b.textContent); })[0]; };
  var K = function(){ return (parseFloat(getComputedStyle(document.querySelector('.zoom-wrap')||document.body).zoom)||1) * (parseFloat(getComputedStyle(document.documentElement).zoom)||1); };
  var cols = function(sel){ var r = document.querySelector(sel + ' .pvrow.pvpart'); if (!r) return null;
    return [].slice.call(r.children).map(function(c){ var b = c.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.width)]; }); };
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      try { click(tab(/Проекты/)); } catch (e) { out.e1 = String(e); }
      setTimeout(function(){
        try { click(document.querySelector('[data-help="project-card"]')); } catch (e) { out.e2 = String(e); }
        setTimeout(function(){
          try {
            var tbl = document.querySelector('.pvtbl.ui3-pv');
            out.hasTable = !!tbl;
            var k = K();
            var rows = tbl ? [].slice.call(tbl.querySelectorAll('.pvrow.pvpart')) : [];
            out.rows = rows.map(function(r){
              var b = r.getBoundingClientRect();
              var cs = [].slice.call(r.children).map(function(c){ var x = c.getBoundingClientRect(); return [x.left, x.width]; }).filter(function(x){ return x[1] > 0.5; });
              var ov = 0; for (var i = 1; i < cs.length; i++) if (cs[i][0] < cs[i-1][0] + cs[i-1][1] - 1) ov++;
              var tall = [].slice.call(r.querySelectorAll('*')).filter(function(e){ return e.getBoundingClientRect().height > b.height + 1; }).length;
              var sb = r.querySelector('.ui3-qtsync .qtsync');
              return { h: b.height / k, overlaps: ov, tall: tall,
                       rail: !!r.querySelector('.ui3-qtrail'),
                       flag: (r.querySelector('.ui3-qtflag') || {}).className || '',
                       pairInputs: r.querySelectorAll('.ui3-qtpair input').length,
                       sync: !!sb, syncOn: sb ? /(^|\s)on(\s|$)/.test(sb.className) : null,
                       note: ((r.querySelector('.ui3-qtnote')||{}).textContent||'').trim(),
                       rw: ((r.querySelector('.rw-chip')||{}).textContent||'').trim(),
                       badgeN: ((r.querySelector('.status-badge .sb-n')||{}).textContent||'').trim(),
                       prog: !!r.querySelector('.qtprog') };
            });
            out.headCells = tbl ? tbl.querySelector('.pvrow.pvhead').children.length : 0;
            out.viewCols = cols('.pvtbl.ui3-pv');
          } catch (e) { out.e3 = String(e); }
          //  Кнопка синхронизации у детали обязана менять связь ЗАДАЧИ: следим за обращением к серверу.
          try {
            window.__calls = [];
            var _f = window.fetch;
            window.fetch = function(u){ try { window.__calls.push(String((u && u.url) || u)); } catch (e) {} return _f.apply(this, arguments); };
            var sb2 = document.querySelector('.pvtbl.ui3-pv .pvrow.pvpart .ui3-qtsync .qtsync');
            if (sb2) click(sb2);
          } catch (e) { out.e4 = String(e); }
          setTimeout(function(){
            try { out.syncCalled = (window.__calls || []).some(function(u){ return /staging\/sync/.test(u); }); } catch (e) {}
            //  Вход в правку (карандаш) не должен сдвигать столбцы.
            try { var pen = document.querySelectorAll('[data-help="proj-edit"]')[0]; out.hasPen = !!pen; if (pen) click(pen); } catch (e) { out.e5 = String(e); }
            setTimeout(function(){
              try { out.editCols = cols('.pvtbl.p2edit'); } catch (e) { out.e6 = String(e); }
              done();
            }, 1100);
          }, 700);
        }, 1500);
      }, 1000);
    }, 2300);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("11. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    check("11. браузерный движок доступен", True)
    stage.set_api({"/api/printers": [{"id": "b0", "name": "X1", "type": "bambu", "model": "Bambu Lab X1 Carbon",
                                      "ip": "10.0.0.40", "port": 8883, "serial": "FIXTURE", "access_code": ""}],
                   "/api/staging": _ST,
                   "/api/projects2": [{"id": "P1", "name": "Заказ 17", "due_date": "", "is_archived": 0,
                                       "created_at": "2026-09-01", "required_total": 22, "printed_total": 11,
                                       "parts_count": 3, "files_count": 1}],
                   "/api/projects2/P1/partsview": _PARTS, "/api/projects2/P1/tree": _TREE,
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"b0": {"status": "RUNNING", "file_name": "korpus", "nozzle_temp": 230, "bed_temp": 70,
                           "percent": 40, "remaining_time": 600, "nozzle_count": 1}})
    R = stage.run(JS, window_size=(1700, 1000), settle_ms=2600, path="/ui3",
                  extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R:
        check("12. строка детали проверена", False, str(stage.last_diag())[:250])
    else:
        _r = R.get("rows") or []
        check("12. три детали, у всех высота 50 и восемь ячеек в шапке",
              R.get("hasTable") is True and len(_r) == 3
              and all(abs(x["h"] - 50) <= 1.5 for x in _r) and R.get("headCells") == 8,
              ([round(x["h"], 1) for x in _r], R.get("headCells")))
        check("13. ничего не налезает и ничего не выше строки",
              all(x["overlaps"] == 0 and x["tall"] == 0 for x in _r),
              [(x["overlaps"], x["tall"]) for x in _r])
        #  2.974 (заказ владельца): линия выполнения плана убрана из проектов и задач.
        #  Рельса запуска слева осталась — по ней владелец и запускает деталь в печать.
        check("14. у каждой детали рельса слева, линии хода печати больше нет",
              all(x["rail"] for x in _r) and not any(x["prog"] for x in _r),
              [(x["rail"], x["prog"]) for x in _r])
        check("15. беда связанной задачи показана на рельсе первой детали и только у неё",
              "lvl-bad" in (_r[0]["flag"] or "") and not _r[1]["flag"] and not _r[2]["flag"],
              [x["flag"] for x in _r])
        check("16. «Итог из План» — два поля в капсуле у каждой детали",
              all(x["pairInputs"] == 2 for x in _r), [x["pairInputs"] for x in _r])
        check("17. синхронизация есть там, где есть задача: включена, выключена, отсутствует",
              _r[0]["sync"] is True and _r[0]["syncOn"] is True
              and _r[1]["sync"] is True and _r[1]["syncOn"] is False
              and _r[2]["sync"] is False,
              [(x["sync"], x["syncOn"]) for x in _r])
        check("18. нажатие на неё уходит на сервер тем же запросом, что и в задачах",
              R.get("syncCalled") is True, R.get("syncCalled"))
        check("19. заметка видна строкой, «Брак» показан, число печатающихся — в бейдже",
              _r[0]["note"].startswith("Печатать") and _r[0]["rw"] == "1/3" and _r[1]["rw"] == "2/2"
              and _r[0]["badgeN"] == "1",
              (_r[0]["note"][:24], _r[0]["rw"], _r[1]["rw"], _r[0]["badgeN"]))
        check("20. вход в правку не сдвигает столбцы (до 1 точки)",
              R.get("hasPen") is True and R.get("viewCols") and R.get("viewCols") == R.get("editCols"),
              (R.get("hasPen"), R.get("viewCols"), R.get("editCols")))
        _d = R.get("__diag") or {}
        check("21. консоль чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:220])

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
