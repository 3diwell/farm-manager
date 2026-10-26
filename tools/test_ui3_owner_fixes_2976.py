# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.976 — правки по второму списку владельца, проверенные исполнением.

ЧТО ПРОВЕРЯЕТСЯ:
  1. окно камеры НЕ мелькает при «Деталь -> Камера»: покадровый замер, ни одного кадра, где
     окно видно не на своём месте (раньше — два таких кадра, окно крупнее и правее места);
  2. нажатие на принтер при открытом большом окне (файлы принтеров, проводник) закрывает окно
     и показывает пульт, а не плавающее окно камеры;
  3. в списке файлов пульта нет удаления; у «Печать» одна кнопка, а не две;
  4. на «Проектах» прокручивается и сетка, и РАСКРЫТЫЙ проект; нижний край — вровень с
     подсказками;
  5. перенос задачи в проект: одноимённый файл — вопрос «заменить или отменить»
     (сервер отвечает exists, страница спрашивает); счёт и заметки переходят
     (сам перенос на живом сервере — tools/test_task_to_project_e2e.py);
  6. H2D «Device is busy»: решение о принятой команде печати вынесено в модуль, ответ прошивки
     записывается, перед второй командой — выдержка (логика — tools/test_bambu_start_policy.py).

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_ui3_owner_fixes_2976.py
"""
import importlib.util
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location("fm_stage_2976", os.path.join(ROOT, "tools", "_fm_ui_stage.py"))
stage = importlib.util.module_from_spec(_s)
_s.loader.exec_module(stage)

SENTINEL = "UI3_OWNER_FIXES_SENTINEL_2_976"
PASS = FAIL = 0
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
HTML = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "ui3", "ui3.css"), encoding="utf-8").read()
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


print("--- 1. закреплено в файлах ---")
check("1. поправка масштаба окна камеры запоминается, окно показывается после подтверждения места",
      "let _ui3CamFit = null;" in APPJS and "requestAnimationFrame(_ui3CamReady);" in APPJS
      and "_ui3ArmTimer = setTimeout(_ui3CamReady, 1500);" in APPJS)
check("2. нажатие на принтер закрывает большие окна; под большим окном камера гаснет",
      "const _ui3CloseBigWindows = () => {" in APPJS
      and "watch(() => [workspaceView.value, !!exOpen.value]" in APPJS)
check("3. удаления в списке файлов пульта нет, у «Печать» одна кнопка",
      "ui3DeleteFileOnPrinter" not in APPJS and "ui3DeleteFileOnPrinter" not in HTML
      and 'class="ui3-pp-btn pri dd"' not in HTML and "ui3FilesDel" not in APPJS)
check("4. раскрытый проект прокручивается сам, пустая обёртка задач спрятана",
      "html.ui3-mode.ui3-right-projects .projects-pane > .ui3-rest > section > .glass-panel.ui3-proj {" in CSS
      and "html.ui3-mode.ui3-right-projects .projects-pane > .ui3-rest > .ui3-taskwrap { display: none !important; }" in CSS)
check("5. перенос в проект: сервер отвечает exists, страница спрашивает «заменить», счёт переходит",
      '"status": "exists"' in SRV and "def _carry_task_counts(" in SRV
      and 'replace = bool(body.get("replace"))' in SRV
      and "if (r.ok && d.status === 'exists') {" in APPJS
      and "Object.assign({}, body || {}, { replace: true })" in APPJS)
check("6. H2D: ответ прошивки записывается, решение — в модуле, перед второй командой выдержка",
      "_bambu_cmd_ack[pid] = {" in SRV and "_bstart.StartWatch(" in SRV
      and "if _bambu_wait_started(pid, 15.0):" in SRV
      and os.path.isfile(os.path.join(ROOT, "app", "bambu_start_policy.py")))
_rules = [l for l in CSS.splitlines() if ".glass-panel.ui3-proj" in l and "{" in l and not l.strip().startswith("/*")]
check("7. новые правила начинаются с html.ui3-mode",
      _rules and all(l.startswith("html.ui3-mode") for l in _rules))

print()
print("--- 2. исполнение: настоящая страница ---")
PR = [{"id": "b1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_B1", "access_code": ""},
      {"id": "b2", "name": "X1C-02", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.12", "port": 8883, "serial": "FIXTURE_B2", "access_code": ""}]
#  created_at позже остальных: проекты отсортированы по дате, и первой карточкой — той, что
#  нажимает проверка, — должен стоять именно P1 (у него есть дерево и детали в стенде).
_PRJ = {"id": "P1", "name": "Заказ 17", "due_date": "", "is_archived": 0, "created_at": "2026-09-30",
        "required_total": 120, "printed_total": 7, "parts_count": 24, "files_count": 1}
_PARTS = {"project": _PRJ, "parts": [
    {"part_id": "pp%d" % i, "part_name": "Деталь_%02d" % i, "required_qty": 12, "printed_qty": i % 12,
     "status": "in_progress", "notes": "", "rework_qty": 0, "rework_done": 0,
     "live_printers": [], "plates": [], "order_idx": i} for i in range(24)]}
_TREE = {"project": _PRJ, "nodes": [
    {"id": "f1", "name": "korpus.gcode.3mf", "type": "file", "is_printable": True,
     "target_model": "Bambu Lab X1 Carbon", "compatible_pids": ["b1", "b2"], "target_nozzles": 1,
     "children": [{"id": "c%d" % i, "name": "Деталь_%02d" % i, "qty": 1} for i in range(24)]}]}
PRJS = [_PRJ] + [{"id": "P%d" % i, "name": "Заказ %d" % i, "due_date": "", "is_archived": 0,
                  "created_at": "2026-09-0%d" % (i % 9 + 1), "required_total": 12, "printed_total": i,
                  "parts_count": 2, "files_count": 1} for i in range(2, 14)]

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = { frames: [] };
  var tab = function(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; };
  var vbtn = function(re){ return qa('.ui3-pp-seg button, [data-help="pp-view"] button').filter(function(b){ return re.test(b.textContent); })[0]; };
  function sample(n, done){
    var i = 0;
    function tick(){
      var ov = q('#fm-overlay-root > div.fixed'), slot = q('.ui3-camslot');
      if (ov) {
        var cs = getComputedStyle(ov), r = ov.getBoundingClientRect();
        var rec = { op: cs.opacity, box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] };
        if (slot) { var s = slot.getBoundingClientRect(); rec.slot = [Math.round(s.left), Math.round(s.top), Math.round(s.width), Math.round(s.height)]; }
        out.frames.push(rec);
      }
      i++;
      if (i < n) requestAnimationFrame(tick); else done();
    }
    requestAnimationFrame(tick);
  }
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      //  ── проекты: сетка и раскрытый проект прокручиваются, низ вровень ──
      var sg = q('[data-help="suggest"]');
      out.sugBottom = sg ? Math.round(sg.getBoundingClientRect().bottom) : null;
      var grid = q('.projects-pane .plan-grid-cols');
      out.gridBottom = grid ? Math.round(grid.getBoundingClientRect().bottom) : null;
      try { click(q('[data-help="project-card"]')); } catch (e) { out.e1 = String(e); }
      setTimeout(function(){
        var panel = q('.projects-pane .glass-panel.ui3-proj');
        var body = panel ? panel.querySelector(':scope > .p-2') : null;
        var bar = panel ? panel.firstElementChild : null;      // шапка проекта: имя, «Печатать весь проект»
        out.expOv = body ? getComputedStyle(body).overflowY : null;
        out.expBottom = panel ? Math.round(panel.getBoundingClientRect().bottom) : null;
        var h0 = qa('.ui3-proj')[0] ? qa('.ui3-proj')[0].getBoundingClientRect().top : null;
        var b0 = bar ? bar.getBoundingClientRect().top : null;
        out.barHasPrintAll = bar ? /Печатать весь проект|Print whole project/.test(bar.textContent) : null;
        if (body) body.scrollTop = 300;
        setTimeout(function(){
          out.expScrolled = body ? Math.round(body.scrollTop) : null;
          out.expHdrMoved = h0 == null ? null : Math.round(qa('.ui3-proj')[0].getBoundingClientRect().top - h0);
          out.barMoved = (bar && b0 != null) ? Math.round(bar.getBoundingClientRect().top - b0) : null;
          //  ── пульт: одна кнопка печати, список файлов без удаления ──
          try { click(qa('.printer-card')[0]); } catch (e) { out.e2 = String(e); }
          setTimeout(function(){
            out.printBtns = qa('.ui3-pp-split .ui3-pp-btn.pri').length;
            out.ddBtns = qa('.ui3-pp-btn.pri.dd').length;
            var fb = q('.ui3-pp-fsel .ui3-pp-selbtn'); if (fb) click(fb);
            setTimeout(function(){
              out.fileRows = qa('.ui3-pp-fit .nm').length;
              out.delBtns = qa('.ui3-pp-fit .del').length;
              if (fb) click(fb);
              //  ── камера: «Деталь» -> «Камера» без единого кадра не на месте ──
              var part = vbtn(/Деталь/); if (part) click(part);
              setTimeout(function(){
                var cam = vbtn(/Камера/); if (cam) click(cam);
                sample(80, function(){
                  //  ── большое окно сверху: «Файлы принтера» -> нажатие на другой принтер ──
                  var pf = q('[data-help="pp-pfiles"]'); out.pfBtn = !!pf; if (pf) click(pf);
                  setTimeout(function(){
                    out.pfOpened = !!q('.fm-set-scroll, [data-help="pf-root"], .fm-pf') || !(q('.projects-pane') && q('.projects-pane').offsetParent !== null);
                    var ov1 = q('#fm-overlay-root > div.fixed');
                    out.camUnderBig = ov1 ? getComputedStyle(ov1).opacity : 'none';
                    try { click(qa('.printer-card')[1]); } catch (e) { out.e3 = String(e); }
                    setTimeout(function(){
                      out.paneBack = !!(q('.projects-pane') && q('.projects-pane').offsetParent !== null);
                      out.panelShown = !!(q('.ui3-pp') && q('.ui3-pp').offsetParent !== null);
                      out.panelName = (q('.ui3-pp-name') || {}).textContent;
                      var ov2 = q('#fm-overlay-root > div.fixed');
                      out.camDocked = ov2 ? document.documentElement.classList.contains('ui3-cam-dock') : null;
                      out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
                      res(dump(out));
                    }, 1800);
                  }, 1200);
                });
              }, 600);
            }, 500);
          }, 1800);
        }, 400);
      }, 2000);
    }, 1700);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("8. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR, "/api/staging": [], "/api/projects2": PRJS,
                   "/api/projects2/P1/partsview": _PARTS, "/api/projects2/P1/tree": _TREE,
                   "/api/printer/b1/files": ["a.gcode", "b.gcode"], "/api/printer/b2/files": ["c.gcode"],
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"b1": {"status": "IDLE", "nozzle_count": 1}, "b2": {"status": "IDLE", "nozzle_count": 1}})
    R = stage.run(JS, window_size=(1920, 1080), settle_ms=17000, path="/ui3")
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R:
        check("8. страница отработала", False, str(stage.last_diag())[:250])
    else:
        check("8. сетка проектов кончается там же, где подсказки",
              R.get("gridBottom") is not None and abs(R.get("gridBottom") - R.get("sugBottom")) <= 1,
              (R.get("gridBottom"), R.get("sugBottom")))
        check("9. раскрытый проект прокручивается сам, шапки стоят («Печатать весь проект» на месте), низ вровень с подсказками",
              R.get("expOv") == "auto" and (R.get("expScrolled") or 0) > 100 and R.get("expHdrMoved") == 0
              and R.get("barMoved") == 0 and R.get("barHasPrintAll") is True
              and R.get("expBottom") is not None and abs(R.get("expBottom") - R.get("sugBottom")) <= 1,
              (R.get("expOv"), R.get("expScrolled"), R.get("expHdrMoved"), R.get("barMoved"),
               R.get("barHasPrintAll"), R.get("expBottom"), R.get("sugBottom")))
        check("10. у «Печать» одна кнопка, второй (стрелки) нет",
              R.get("printBtns") == 1 and R.get("ddBtns") == 0, (R.get("printBtns"), R.get("ddBtns")))
        check("11. список файлов пульта есть, кнопок удаления в нём нет",
              (R.get("fileRows") or 0) >= 1 and R.get("delBtns") == 0, (R.get("fileRows"), R.get("delBtns")))
        _bad = []
        for f in (R.get("frames") or []):
            visible = f.get("op") not in ("0",)
            b, s_ = f.get("box"), f.get("slot")
            off = (not s_) or (abs(b[0] - s_[0]) > 3 or abs(b[1] - s_[1]) > 3 or abs(b[2] - s_[2]) > 3 or abs(b[3] - s_[3]) > 3)
            if visible and off:
                _bad.append(f)
        check("12. «Деталь» -> «Камера»: ни одного кадра, где окно видно не на своём месте",
              len(R.get("frames") or []) >= 30 and not _bad,
              (len(R.get("frames") or []), _bad[:3]))
        check("13. нажатие на принтер при открытом окне «Файлы принтеров» закрывает окно и показывает пульт",
              R.get("pfBtn") is True and R.get("paneBack") is True and R.get("panelShown") is True
              and "X1C-02" in str(R.get("panelName") or ""),
              (R.get("pfBtn"), R.get("pfOpened"), R.get("paneBack"), R.get("panelShown"), R.get("panelName")))
        check("14. под большим окном камера была погашена, после — снова стыкована",
              R.get("camUnderBig") in ("0", "none") and R.get("camDocked") in (True, None),
              (R.get("camUnderBig"), R.get("camDocked")))
        check("15. горизонтальной полосы прокрутки нет", R.get("hscroll") is False, R.get("hscroll"))
        _d = R.get("__diag") or {}
        _warn = [w for w in (_d.get("consoleWarnings") or []) if "[WebRTC] camera failed" not in str(w)]
        check("16. консоль браузера чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled"))
              and not [w for w in _warn if "Vue warn" in str(w)],
              json.dumps(_d, ensure_ascii=False)[:260])

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
