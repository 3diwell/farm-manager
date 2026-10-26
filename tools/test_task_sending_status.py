# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""15.09.2026 (заказ владельца) — статус «Отправка» у файла сразу после запуска печати.

ЗАЧЕМ. Раньше строка файла в «Задачах» и «Проектах» менялась только когда принтер подтверждал
старт: файл ушёл, идёт загрузка на принтер, ожидание подтверждения — а строка всё ещё «ОЖИДАНИЕ».
При запуске десяти файлов подряд не видно, какие уже пошли, и тот же файл легко запустить ещё раз.
Теперь строка показывает «ОТПРАВКА» с момента, когда запуск принят (та же панель отправок:
job на сервере + оптимистичная строка), рельса/кнопка запуска говорят «Отправка…».

ЧТО ПРОВЕРЯЕТСЯ.
  A. устройство закреплено в исходниках (клиент, стили, сервер, «Что нового»);
  B. НАСТОЯЩИЙ код имени файла проекта для очереди — на временной базе, сервер не поднимается;
  C. в браузере (стенд tools/_fm_ui_stage.py, UI 3.0): задача с идущей отправкой — «ОТПРАВКА» синим,
     рельса st-send; ошибка отправки — снова «ОЖИДАНИЕ»; завершённый job ещё держит «ОТПРАВКА»;
     «отправка» сильнее «ГОТОВО»; деталь проекта с отправляемой плитой — «отправка», а «в процессе»
     сильнее «отправки». Консоль чистая.

БЕЗОПАСНОСТЬ. Рабочая база, DATA_DIR и принтеры не участвуют: стенд отдаёт web/ и выдуманные
ответы; функция сервера исполняется из исходного текста поверх временной базы.

Запуск:  python tools/test_task_sending_status.py
"""
import ast
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.chdir(ROOT)
import _fm_ui_stage as stage  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (str(detail)[:300],)) if detail else ""))


def _read(*parts):
    return io.open(os.path.join(ROOT, *parts), encoding="utf-8").read()


APPJS = _read("web", "app.js")
IDX = _read("web", "index.html")
CSS3 = _read("web", "ui3", "ui3.css")
CSS = _read("web", "app.css")
SRV = _read("server.py")

print("--- A. устройство закреплено в исходниках ---")
check("A1. источник статуса «отправка» — панель отправок (job'ы сервера + оптимистичная строка)",
      "const fileSendState = (filename) => {" in APPJS
      and "for (const j of (sendJobsView.value || [])) {" in APPJS
      and "if (j.state !== 'completed') return j.state || 'queued';" in APPJS)
check("A2. статус задачи: «отправка» сильнее «ожидания» и «готово», слабее «в процессе»",
      "if (f.status === 'printing') return 'in_progress'; if (fileSendState(f && f.filename)) return 'sending';" in APPJS
      and "k === 'sending' ? tr('SENDING')" in APPJS)
check("A3. порядок сортировки: «отправка» между «в процессе» и «ожиданием»",
      "const _TASK_STATUS_ORDER = { printing: 0, preparing: 1, paused: 2, in_progress: 3, sending: 4, pending: 5, done: 6 };" in APPJS)
check("A4. цвет — синий, как у всего, что уже идёт",
      "|| s === 'in_progress' || s === 'sending' || s === 'RUNNING'" in APPJS)
check("A5. подписи на двух языках",
      '"SENDING": "ОТПРАВКА"' in APPJS and '"sending": "отправка"' in APPJS and '"Sending…": "Отправка…"' in APPJS)
check("A6. задачи 3.0: подсказка бейджа — стадия отправки, рельса — st-send и значок отправки, кнопка — «Отправка…»",
      ':title="stagingStatusTitle(f)"' in IDX
      and "if (k === 'sending') return 'st-send';" in APPJS
      and """(stagingStatusKey(f) === 'sending' ? 'upload' : 'printer-flat')""" in IDX
      and """:title="printBtnLabel('st:'+f.filename, f.filename)\"""" in IDX
      and "(filename && fileSendState(filename)) ? tr('Sending…')" in APPJS)
check("A7. задачи 2.0 и плиты проекта: кнопка запуска подсвечена и подписана «Отправка…»",
      IDX.count("""(fileSendState(f.filename) ? 'pvbtn-send' : '')">{{ printBtnLabel('st:'+f.filename, f.filename) }}""") == 2
      and """(fileSendState(pl.filename) ? 'pvbtn-send' : '')">{{ printBtnLabel('p2:'+pl.file_id, pl.filename) }}""" in IDX)
check("A8. деталь проекта: бейдж, точка и рельса берут «отправку» по своим плитам; «в процессе» сильнее",
      IDX.count("liveStatusKey(pp.live_printers, p2PartOwnKey(pp))") >= 4
      and IDX.count("liveStatusLabel(pp.live_printers, p2PartOwnLabel(pp))") == 2
      and "liveStatusKey(pp.live_printers, pp.status)" not in IDX
      and "return (s !== 'in_progress' && p2PartSending(pp)) ? 'sending' : s;" in APPJS
      and "p2PartOwnKey(a)" in APPJS and "p2PartOwnKey(b)" in APPJS)
check("A9. стили: рельса st-send «дышит» синим, кнопка pvbtn-send пульсирует",
      "html.ui3-mode .ui3-qtrail.st-send {" in CSS3 and "@keyframes ui3-qtrail-send" in CSS3
      and ".pvbtn-send{" in CSS and "@keyframes fmSendPulse" in CSS
      and CSS3.count("{") == CSS3.count("}") and CSS.count("{") == CSS.count("}"))
check("A10. после постановки в очередь панель отправок подтягивается сразу (три места)",
      APPJS.count("fetchSendJobs();") >= 4 and "fetchPrintQueue();\n            fetchSendJobs();" in APPJS)
check("A11. оптимистичная строка проектной печати несёт имя файла (обе ветки запуска)",
      "file_name: (ctx.flow === 'project' ? _p2FileNameOf(ctx.pid, ctx.fileId) : (ctx.filename || ''))" in APPJS
      and "file_name: _p2FileNameOf(pid, fileId), source: 'project' };" in APPJS
      and "const _p2FileNameOf = (pid, fileId) => {" in APPJS)
check("A12. сервер: у reservation очереди проектного файла есть имя; читается ДО замка очереди",
      "def _project_file_name(project_id, file_id):" in SRV
      and '_send_mgr.reserve(pid, str(it.get("printer_name") or pid), _resv_name(it), "queue")' in SRV
      and SRV.index("_pf_names[_k] = _project_file_name(*_k)") < SRV.index('batch_id = _uid("batch_")')
      and SRV.index('batch_id = _uid("batch_")') < SRV.index("    with print_queue_lock:\n        queued_pids = {q[\"printer_id\"] for q in print_queue}"))
check("A13. «Что нового» говорит о статусе «Отправка» словами пользователя",
      "сразу после запуска показывает «Отправка»" in SRV)
check("A14. шаблон отдаёт всё, что использует", all(
      n in APPJS.split("stagingStatusKey, stagingStatusLabel, stagingStatusTitle,", 1)[1][:200]
      for n in ("fileSendState,", "p2PartSending,", "p2PartOwnKey,", "p2PartOwnLabel,")))

print("--- B. имя файла проекта для очереди — НАСТОЯЩИЙ код на временной базе ---")
_tree = ast.parse(SRV)
_src = None
for node in _tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == "_project_file_name":
        _src = ast.get_source_segment(SRV, node)
check("B1. исходник функции найден", bool(_src))
_tmp = tempfile.mkdtemp(prefix="sendname_")
conn_p = sqlite3.connect(os.path.join(_tmp, "parts.db"), check_same_thread=False)
conn_p.row_factory = sqlite3.Row
conn_p.execute("CREATE TABLE project_files (id TEXT PRIMARY KEY, project_id TEXT, filename TEXT)")
conn_p.execute("INSERT INTO project_files VALUES ('f1', 'P1', 'korpus.gcode.3mf')")
conn_p.commit()
NS = {"conn_p": conn_p, "lock_p": threading.RLock(),
      "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None)})(), "_exc_brief": lambda: "?"}
exec(_src, NS)   # noqa: S102 — свой исходник в песочнице
_pfn = NS["_project_file_name"]
check("B2. имя читается по паре (проект, файл)", _pfn("P1", "f1") == "korpus.gcode.3mf")
check("B3. чужой проект / нет файла / пустые id — пустая строка, без исключений",
      _pfn("P2", "f1") == "" and _pfn("P1", "nope") == "" and _pfn("", "f1") == "" and _pfn("P1", None) == "")
conn_p.close()
NS["conn_p"] = None
check("B4. сломанная база — тоже пустая строка (fail-open: очередь от подписи не зависит)", _pfn("P1", "f1") == "")
shutil.rmtree(_tmp, ignore_errors=True)

print("--- C. в браузере (стенд UI 3.0) ---")
PR = [{"id": "b1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_B1", "access_code": ""}]


def task(name, req, printed):
    return {"filename": name, "status": "ready", "printer_id": "", "required_qty": req, "printed_qty": printed,
            "target_nozzles": 0, "target_model": "", "is_printable": True, "notes": "", "src_path": "",
            "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
            "compatible_pids": ["b1"], "parts": [], "part_total": 0}


ST = [task("plate_A.gcode", 3, 0), task("plate_B.gcode", 3, 0), task("plate_C.gcode", 2, 2)]


def job(i, fname, state, source="task", err=None):
    return {"job_id": "send_%d" % i, "printer_id": "b1", "printer_name": "X1C-01", "file_name": fname,
            "source": source, "state": state, "progress": (42 if state == "uploading" else None),
            "bytes_sent": None, "bytes_total": None, "error": err, "created_at": 1000 + i, "queue_id": None}


_PRJ = {"id": "P1", "name": "Заказ 17", "due_date": "", "is_archived": 0, "created_at": "2026-09-15",
        "required_total": 6, "printed_total": 1, "parts_count": 2, "files_count": 2}


def plate(fid, name):
    return {"file_id": fid, "filename": name, "target_model": "Bambu Lab X1 Carbon", "on_plate_qty": 1,
            "total_parts": 1, "is_printable": True, "compatible_pids": ["b1"], "content_hash": "", "src_path": "",
            "file_part_id": fid + "_l"}


_PARTS = {"project": _PRJ, "parts": [
    {"part_id": "ppA", "part_name": "Корпус", "required_qty": 4, "printed_qty": 0, "status": "pending",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": [], "plates": [plate("f1", "korpus.gcode.3mf")]},
    {"part_id": "ppB", "part_name": "Крышка", "required_qty": 2, "printed_qty": 1, "status": "in_progress",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": [], "plates": [plate("f2", "kryshka.gcode.3mf")]}]}
_TREE = {"project": _PRJ, "nodes": [
    {"id": "f1", "name": "korpus.gcode.3mf", "type": "file", "is_printable": True, "compatible_pids": ["b1"],
     "target_model": "Bambu Lab X1 Carbon", "filename": "korpus.gcode.3mf", "file_id": "f1", "children": [{"id": "c1", "name": "Корпус", "qty": 1}]},
    {"id": "f2", "name": "kryshka.gcode.3mf", "type": "file", "is_printable": True, "compatible_pids": ["b1"],
     "target_model": "Bambu Lab X1 Carbon", "filename": "kryshka.gcode.3mf", "file_id": "f2", "children": [{"id": "c2", "name": "Крышка", "qty": 1}]}]}

JS_TASKS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var tab = function(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; };
  var out = {};
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); } catch (e) {}
    setUiLang('ru');
    setTimeout(function(){
      var t = tab(/Задачи/); if (t) click(t);
      setTimeout(function(){
        out.rows = qa('[data-help="qt-row"]').map(function(r){
          var n = r.querySelector('.pvpname[data-help="qt-name"]');
          var b = r.querySelector('[data-help="qt-status"] .status-badge');
          var rail = r.querySelector('.ui3-qtrail');
          var svg = rail ? rail.querySelector('svg') : null;
          return { name: n ? n.textContent.trim() : '', label: b ? b.textContent.trim() : null,
                   title: b ? (b.getAttribute('title') || '') : null, badgeCls: b ? b.className : '',
                   railCls: rail ? rail.className : '', railTitle: rail ? (rail.getAttribute('title') || '') : '',
                   railIcon: svg ? svg.innerHTML.replace(/\s+/g, '') : '' };
        });
        out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
        res(dump(out));
      }, 1200);
    }, 800);
  }, 1500);
});
"""

JS_PROJECT = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var tab = function(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; };
  var out = {};
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); } catch (e) {}
    setUiLang('ru');
    setTimeout(function(){
      var t = tab(/Проекты/); if (t) click(t);
      setTimeout(function(){
        var card = q('[data-help="project-card"]'); if (card) click(card);
        setTimeout(function(){
          out.rows = qa('[data-help="part-row"]').map(function(r){
            var n = r.querySelector('.pvpname[data-help="col-name"]');
            var b = r.querySelector('[data-help="col-status"] .status-badge');
            var rail = r.querySelector('.ui3-qtrail');
            return { name: n ? n.textContent.trim() : '', label: b ? b.textContent.trim() : null,
                     badgeCls: b ? b.className : '', railCls: rail ? rail.className : '',
                     railTitle: rail ? (rail.getAttribute('title') || '') : '' };
          });
          out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
          res(dump(out));
        }, 1500);
      }, 1200);
    }, 800);
  }, 1500);
});
"""


def by_name(r, name):
    for x in (r or {}).get("rows") or []:
        if x.get("name") == name:
            return x
    return {}


def errs_of(r):
    d = (r or {}).get("__diag") or {}
    return (d.get("consoleErrors") or []) + (d.get("pageErrors") or []) + (d.get("unhandled") or [])


if not stage.engine_ready():
    check("C0. браузерный движок доступен (без него бейдж проверить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    def run_tasks(jobs):
        stage.set_api({"/api/printers": PR, "/api/staging": ST, "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
                       "/api/farm-settings": {"ok": True, "settings": {}}, "/api/modules": {"modules": [], "restart_needed": False},
                       "/api/send-jobs": {"jobs": jobs, "reserved_printer_ids": ["b1"] if jobs else []}})
        return stage.run(JS_TASKS, window_size=(1600, 900), settle_ms=2000, path="/ui3")

    # 1) идёт отправка A (загрузка на принтер), C стоит в очереди и уже «готово» по счётчику
    R1 = run_tasks([job(1, "plate_A.gcode", "uploading"), job(2, "plate_C.gcode", "queued", "queue")])
    a, b, c = by_name(R1, "plate_A.gcode"), by_name(R1, "plate_B.gcode"), by_name(R1, "plate_C.gcode")
    check("C1. три строки задач на экране", R1 is not None and len((R1 or {}).get("rows") or []) == 3,
          (R1 or {}).get("rows") if R1 else stage.last_diag())
    check("C2. файл с идущей отправкой — «ОТПРАВКА» синим, подсказка — стадия отправки",
          a.get("label") == "ОТПРАВКА" and "text-blue-400" in a.get("badgeCls", "") and a.get("title") == "Отправка на принтер…",
          (a.get("label"), a.get("badgeCls"), a.get("title")))
    check("C3. рельса этого файла — st-send, подпись «Отправка…», значок другой, чем у ждущей строки",
          "st-send" in a.get("railCls", "") and a.get("railTitle") == "Отправка…"
          and a.get("railIcon") and a.get("railIcon") != b.get("railIcon"),
          (a.get("railCls"), a.get("railTitle")))
    check("C4. файл без отправки — по-прежнему «ОЖИДАНИЕ» жёлтым, рельса st-wait, подпись «Выбрать принтер»",
          b.get("label") == "ОЖИДАНИЕ" and "text-yellow-500" in b.get("badgeCls", "")
          and "st-wait" in b.get("railCls", "") and b.get("railTitle") == "Выбрать принтер",
          (b.get("label"), b.get("badgeCls"), b.get("railCls"), b.get("railTitle")))
    check("C5. «отправка» сильнее «готово»: повторный запуск готовой задачи виден (в очереди — тоже «ОТПРАВКА»)",
          c.get("label") == "ОТПРАВКА" and c.get("title") == "Ожидает отправки", (c.get("label"), c.get("title")))
    check("C6. консоль чистая, горизонтальной прокрутки нет",
          R1 is not None and not errs_of(R1) and not R1.get("hscroll"), errs_of(R1)[:2] if R1 else "")

    # 2) отправка A провалилась — строка честно возвращается в «ожидание»; C без отправки — «готово»
    R2 = run_tasks([job(1, "plate_A.gcode", "failed", "task", "no connection")])
    a2, c2 = by_name(R2, "plate_A.gcode"), by_name(R2, "plate_C.gcode")
    check("C7. ошибка отправки — снова «ОЖИДАНИЕ» и рельса st-wait (причина остаётся в панели отправок)",
          a2.get("label") == "ОЖИДАНИЕ" and "st-wait" in a2.get("railCls", "") and a2.get("railTitle") == "Выбрать принтер",
          (a2.get("label"), a2.get("railCls"), a2.get("railTitle")))
    check("C8. без отправки готовая задача — «ГОТОВО»", c2.get("label") == "ГОТОВО", c2.get("label"))

    # 3) отправка завершена (принтер подтвердил), а статус задачи ещё не догнал — держим «ОТПРАВКА»
    R3 = run_tasks([job(1, "plate_A.gcode", "completed")])
    a3 = by_name(R3, "plate_A.gcode")
    check("C9. завершённая отправка держит «ОТПРАВКА», пока статус задачи не догонит",
          a3.get("label") == "ОТПРАВКА", a3.get("label"))
    check("C10. консоль чистая во втором и третьем прогоне",
          R2 is not None and R3 is not None and not errs_of(R2) and not errs_of(R3),
          (errs_of(R2) + errs_of(R3))[:2] if (R2 and R3) else "")

    # 4) проект: плита детали «Корпус» отправляется — деталь «отправка»; «Крышка» уже в процессе — так и остаётся
    stage.set_api({"/api/printers": PR, "/api/staging": [], "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
                   "/api/farm-settings": {"ok": True, "settings": {}}, "/api/modules": {"modules": [], "restart_needed": False},
                   "/api/projects2": [_PRJ], "/api/projects2/P1/partsview": _PARTS, "/api/projects2/P1/tree": _TREE,
                   "/api/send-jobs": {"jobs": [job(3, "korpus.gcode.3mf", "starting_file", "project"),
                                               job(4, "kryshka.gcode.3mf", "uploading", "project")],
                                      "reserved_printer_ids": ["b1"]}})
    R4 = stage.run(JS_PROJECT, window_size=(1600, 900), settle_ms=2000, path="/ui3")
    k, kr = by_name(R4, "Корпус"), by_name(R4, "Крышка")
    check("C11. детали проекта на экране", R4 is not None and len((R4 or {}).get("rows") or []) == 2,
          (R4 or {}).get("rows") if R4 else stage.last_diag())
    check("C12. деталь с отправляемой плитой — «отправка» синим, рельса st-send с подписью «Отправка…»",
          k.get("label") == "отправка" and "text-blue-400" in k.get("badgeCls", "")
          and "st-send" in k.get("railCls", "") and k.get("railTitle") == "Отправка…",
          (k.get("label"), k.get("badgeCls"), k.get("railCls"), k.get("railTitle")))
    check("C13. деталь «в процессе» остаётся «в процессе» — подтверждённая печать сильнее отправки",
          kr.get("label") == "в процессе" and "st-send" not in kr.get("railCls", ""), (kr.get("label"), kr.get("railCls")))
    check("C14. консоль чистая в проекте, горизонтальной прокрутки нет",
          R4 is not None and not errs_of(R4) and not R4.get("hscroll"), errs_of(R4)[:2] if R4 else "")
    stage.set_api(None)
    stage.stop()

print()
print("=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
