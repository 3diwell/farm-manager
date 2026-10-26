# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.975 — пять просьб владельца после работы на ферме, проверенные исполнением.

ЧТО ПРОВЕРЯЕТСЯ:
  1. окно камеры не мелькает ни при уходе на «Деталь», ни при возврате на камеру;
  2. сортировка «по статусу» выстроена лестницей по срочности — и у принтеров, и у задач
     (задачи раньше сортировались по внутреннему английскому слову, а не по видимому статусу);
  3. на вкладках «Задачи» и «Проекты» прокручивается только список, шапка стоит; нижний край
     правой половины совпадает с нижним краем «Подсказок»;
  4. «Файлы принтера» вернулись кнопкой в пульт — рядом с отправкой файла с компьютера;
  5. файлы принтера выбираются своим списком, у каждого есть удаление (когда принтер и права
     это позволяют), и Escape закрывает сначала меню, потом пульт.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.
Удаление НЕ выполняется: проверяется, что кнопка есть и ведёт в проверенный путь проводника.

Запуск:  python tools/test_ui3_owner_fixes_2975.py
"""
import importlib.util
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location("fm_stage_2975", os.path.join(ROOT, "tools", "_fm_ui_stage.py"))
stage = importlib.util.module_from_spec(_s)
_s.loader.exec_module(stage)

SENTINEL = "UI3_OWNER_FIXES_SENTINEL_2_975"
PASS = FAIL = 0
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
HTML = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "ui3", "ui3.css"), encoding="utf-8").read()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


print("--- 1. закреплено в файлах ---")
check("1. уход на «Деталь» и закрытие пульта гасят окно камеры",
      APPJS.count("_ui3CamArm();") >= 4
      and "_ui3CamArm();\n            closeCamera();" in APPJS)
check("2. лестница статусов принтера задана явно",
      "const _PRINTER_STATUS_ORDER = {" in APPJS
      and "FAILED: 0, ERROR: 0, ATTENTION: 0," in APPJS
      and "OFFLINE: 6," in APPJS)
check("3. задачи сортируются по ВИДИМОМУ статусу, а не по полю из базы",
      #  15.09.2026: между «в процессе» и «ожиданием» встала «отправка» (файл запущен, принтер ещё
      #  не подтвердил) — tools/test_task_sending_status.py.
      "const _TASK_STATUS_ORDER = { printing: 0, preparing: 1, paused: 2, in_progress: 3, sending: 4, pending: 5, done: 6 }" in APPJS
      and "const ra = _TASK_STATUS_ORDER[stagingStatusKey(a)];" in APPJS
      and "String(a.status || '').localeCompare(String(b.status || ''))" not in APPJS)
check("4. детали проекта сортируются тем же порядком",
      "const statusRank = _TASK_STATUS_ORDER;" in APPJS)
#  2.976: удаление из списка пульта владелец отменил — файлы удаляются в проводнике «Файлы
#  принтеров». Свой список остался: он выглядит частью пульта.
check("5. свой список файлов принтера — без удаления (2.976)",
      'class="ui3-pp-sel ui3-pp-fsel"' in HTML and "ui3DeleteFileOnPrinter" not in HTML
      and "ui3DeleteFileOnPrinter" not in APPJS and "ui3FilesDel" not in APPJS)
check("6. кнопка «Файлы принтера» стоит в пульте рядом с отправкой файла",
      'data-help="pp-pfiles"' in HTML and "openPrinterFiles(ui3Printer)" in HTML
      and HTML.find('data-help="pp-upload"') < HTML.rfind('data-help="pp-pfiles"'))
check("7. Escape закрывает меню пульта, режим отметки и сам пульт",
      "if (ui3FilesOpen.value) { ui3FilesOpen.value = false; return; }" in APPJS
      and "if (ui3AmsOpen.value) { ui3AmsOpen.value = false; return; }" in APPJS
      and "if (queuePickMode.value) { toggleQueuePick(); return; }" in APPJS
      and "if (ui3Mode && ui3Printer.value) { ui3SelectPrinter({ id: ui3Printer.value }); return; }" in APPJS)
check("8. щелчок мимо закрывает меню пульта",
      "if (ui3FilesOpen.value && !e.target.closest('.ui3-pp-fsel')) ui3FilesOpen.value = false;" in APPJS)
check("9. прокрутка «Проектов» отдана списку карточек",
      "html.ui3-mode.ui3-right-projects .projects-pane {" in CSS
      and "html.ui3-mode.ui3-right-projects .projects-pane > .ui3-rest > section > .plan-grid-cols {" in CSS)
check("10. высота правой половины считается по нижнему краю подсказок",
      "const rightColH = ref(null);" in APPJS
      and "rightColH.value = h + 'px';" in APPJS
      and '"{ height: (rightColH || leftColH)' in HTML.replace("'", '"'))
_rules = [l for l in CSS.splitlines() if (".ui3-pp-fsel" in l or ".ui3-pp-fit" in l or ".ui3-right-projects" in l)
          and "{" in l and not l.strip().startswith("/*")]
check("11. каждое новое правило начинается с html.ui3-mode",
      _rules and all(l.startswith("html.ui3-mode") for l in _rules),
      [l[:60] for l in _rules if not l.startswith("html.ui3-mode")])

print()
print("--- 2. исполнение: настоящая страница ---")
#  Принтеры на все ступени лестницы: беда, пауза, закончил, печатает, готовится, свободен, офлайн.
PR = [{"id": "p_idle", "name": "Свободный", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_1", "access_code": ""},
      {"id": "p_off", "name": "Офлайн", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.12", "port": 8883, "serial": "FIXTURE_2", "access_code": ""},
      {"id": "p_run", "name": "Печатает", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.13", "port": 8883, "serial": "FIXTURE_3", "access_code": ""},
      {"id": "p_bad", "name": "Беда", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.14", "port": 8883, "serial": "FIXTURE_4", "access_code": ""},
      {"id": "p_pause", "name": "Пауза", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.15", "port": 8883, "serial": "FIXTURE_5", "access_code": ""},
      {"id": "p_fin", "name": "Закончил", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.16", "port": 8883, "serial": "FIXTURE_6", "access_code": ""}]
LIVE = {"p_idle": {"status": "IDLE", "nozzle_count": 1},
        "p_off": {"status": "OFFLINE", "nozzle_count": 1},
        "p_run": {"status": "RUNNING", "percent": 30, "remaining_time": 40, "file_name": "деталь", "nozzle_count": 1},
        "p_bad": {"status": "FAILED", "nozzle_count": 1},
        "p_pause": {"status": "PAUSED", "percent": 20, "file_name": "деталь", "nozzle_count": 1},
        "p_fin": {"status": "FINISH", "nozzle_count": 1}}
#  Задачи на все ступени: печатается сейчас, в работе, ожидание, готово.
ST = [{"filename": "готово.gcode", "status": "ready", "printer_id": "", "required_qty": 2, "printed_qty": 2,
       "target_nozzles": 0.4, "target_model": "", "is_printable": True, "notes": "", "src_path": "",
       "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
       "compatible_pids": [], "parts": [], "part_total": 0},
      {"filename": "ожидание.gcode", "status": "ready", "printer_id": "", "required_qty": 5, "printed_qty": 0,
       "target_nozzles": 0.4, "target_model": "", "is_printable": True, "notes": "", "src_path": "",
       "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
       "compatible_pids": [], "parts": [], "part_total": 0},
      {"filename": "деталь.gcode", "status": "printing", "printer_id": "p_run", "required_qty": 9, "printed_qty": 1,
       "target_nozzles": 0.4, "target_model": "", "is_printable": True, "notes": "", "src_path": "",
       "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
       "compatible_pids": [], "parts": [], "part_total": 0},
      {"filename": "в_работе.gcode", "status": "printing", "printer_id": "", "required_qty": 4, "printed_qty": 1,
       "target_nozzles": 0.4, "target_model": "", "is_printable": True, "notes": "", "src_path": "",
       "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
       "compatible_pids": [], "parts": [], "part_total": 0}]
PRJ = [{"id": "P%d" % i, "name": "Заказ %d" % i, "due_date": "", "is_archived": 0,
        "created_at": "2026-09-0%d" % (i % 9 + 1), "required_total": 12, "printed_total": i,
        "parts_count": 2, "files_count": 1} for i in range(12)]

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = {};
  var esc = function(){ document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); };
  var tab = function(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; };
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      //  ── порядок принтеров по статусу ──
      out.printerOrder = qa('.printer-card .pc-name, .printer-card .pc-row-name, .printer-card h3')
        .map(function(e){ return e.textContent.trim(); });
      if (!out.printerOrder.length) out.printerOrder = qa('.printer-card').map(function(c){ return (c.textContent || '').trim().slice(0, 12); });
      //  ── задачи: сортировка по столбцу «Статус» ──
      try { click(tab(/Задачи/)); } catch (e) { out.e1 = String(e); }
      setTimeout(function(){
        var head = q('[data-help="qt-status"]');
        out.statusHead = !!head;
        if (head) click(head);
        setTimeout(function(){
          out.taskOrder = qa('.qt-panel .pvrow:not(.pvhead) .fn, .qt-panel .pvrow:not(.pvhead) [data-help="qt-name"]')
            .map(function(e){ return e.textContent.trim(); });
          if (!out.taskOrder.length) {
            out.taskOrder = qa('.qt-panel .pvrow:not(.pvhead)').map(function(r){ return (r.textContent || '').trim().slice(0, 22); });
          }
          //  ── края: задачи и подсказки ──
          var sg = q('[data-help="suggest"]'), pane = q('.projects-pane');
          out.taskBottom = pane ? Math.round(pane.getBoundingClientRect().bottom) : null;
          out.sugBottom = sg ? Math.round(sg.getBoundingClientRect().bottom) : null;
          //  ── проекты: прокрутка только в списке ──
          try { click(tab(/Проекты/)); } catch (e) { out.e2 = String(e); }
          setTimeout(function(){
            var pane2 = q('.projects-pane'), grid = q('.projects-pane .plan-grid-cols');
            out.projPaneOv = pane2 ? getComputedStyle(pane2).overflowY : null;
            out.projGridOv = grid ? getComputedStyle(grid).overflowY : null;
            var t0 = q('.ui3-rtabs').getBoundingClientRect().top;
            var h0 = qa('.ui3-proj')[0] ? qa('.ui3-proj')[0].getBoundingClientRect().top : null;
            if (grid) grid.scrollTop = 250;
            setTimeout(function(){
              out.projScrolled = grid ? Math.round(grid.scrollTop) : null;
              out.projTabsMoved = Math.round(q('.ui3-rtabs').getBoundingClientRect().top - t0);
              out.projHdrMoved = h0 == null ? null : Math.round(qa('.ui3-proj')[0].getBoundingClientRect().top - h0);
              out.projBottom = pane2 ? Math.round(pane2.getBoundingClientRect().bottom) : null;
              //  ── пульт: список файлов, кнопка, камера, Escape ──
              try { click(qa('.printer-card')[0]); } catch (e) { out.e3 = String(e); }
              setTimeout(function(){
                out.pfBtn = qa('[data-help="pp-pfiles"]').length;
                //  переключение вида: уход на «Деталь» обязан гасить окно камеры
                var part = qa('[data-help="pp-view"] button, .ui3-pp-view button').filter(function(b){ return /Деталь|Part/.test(b.textContent); })[0];
                if (part) { click(part); out.armOnPart = document.documentElement.classList.contains('ui3-cam-arm'); }
                var cam = qa('[data-help="pp-view"] button, .ui3-pp-view button').filter(function(b){ return /Камера|Camera/.test(b.textContent); })[0];
                if (cam) { click(cam); out.armOnCam = document.documentElement.classList.contains('ui3-cam-arm'); }
                setTimeout(function(){
                  out.armLater = document.documentElement.classList.contains('ui3-cam-arm');
                  var sel = q('.ui3-pp-fsel .ui3-pp-selbtn');
                  out.selBtn = !!sel;
                  if (sel) click(sel);
                  setTimeout(function(){
                    out.menuOpen = !!q('.ui3-pp-menu.files');
                    out.fileRows = qa('.ui3-pp-fit .nm').map(function(b){ return b.textContent.trim(); });
                    out.delBtns = qa('.ui3-pp-fit .del').length;
                    var r = q('.ui3-pp-menu.files') ? q('.ui3-pp-menu.files').getBoundingClientRect() : null;
                    var pr = q('.ui3-pp') ? q('.ui3-pp').getBoundingClientRect() : null;
                    out.menuInside = (r && pr) ? (r.left >= pr.left - 1 && r.right <= pr.right + 1) : null;
                    esc();
                    setTimeout(function(){
                      out.menuAfterEsc = !!q('.ui3-pp-menu.files');
                      out.panelAfterEsc1 = !!q('.ui3-pp');
                      esc();
                      setTimeout(function(){
                        out.panelAfterEsc2 = !!q('.ui3-pp');
                        out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
                        res(dump(out));
                      }, 700);
                    }, 500);
                  }, 900);
                }, 900);
              }, 1500);
            }, 600);
          }, 1300);
        }, 700);
      }, 1300);
    }, 1700);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("12. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR, "/api/staging": ST, "/api/projects2": PRJ,
                   #  Первым в списке стоит принтер с бедой — сортировка по статусу; именно его
                   #  и открывает проверка, поэтому файлы объявляем для него.
                   "/api/printer/p_bad/files": ["Куб_A.gcode", "Куб_B.gcode", "старый_тест.gcode"],
                   "/api/printer-files/capabilities": {"status": "ok", "read_enabled": True,
                                                       "delete_enabled": True, "delete_ui_allowed": True,
                                                       "capabilities": {"supported": True, "delete_files": True,
                                                                        "list_files": True}}})
    stage.set_live(LIVE)
    R = stage.run(JS, window_size=(1600, 950), settle_ms=16000, path="/ui3")
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R:
        check("12. страница отработала", False, str(stage.last_diag())[:250])
    else:
        _po = [x for x in (R.get("printerOrder") or [])]
        _want = ["Беда", "Пауза", "Закончил", "Печатает", "Свободный", "Офлайн"]
        check("12. принтеры по статусу: беда, пауза, закончил, печатает, свободен, офлайн",
              len(_po) >= 6 and all(_po[i].startswith(_want[i]) for i in range(6)),
              [x[:14] for x in _po])
        _to = [x for x in (R.get("taskOrder") or [])]
        check("13. задачи по статусу: печатается, в работе, ожидание, готово",
              R.get("statusHead") is True and len(_to) == 4
              and _to[0].startswith("деталь") and _to[-1].startswith("готово"), _to)
        check("14. нижний край задач совпал с нижним краем подсказок",
              R.get("taskBottom") is not None and abs(R.get("taskBottom") - R.get("sugBottom")) <= 1,
              (R.get("taskBottom"), R.get("sugBottom")))
        check("15. на «Проектах» прокручивается список карточек, а не вся половина",
              R.get("projPaneOv") == "hidden" and R.get("projGridOv") == "auto"
              and (R.get("projScrolled") or 0) > 40,
              (R.get("projPaneOv"), R.get("projGridOv"), R.get("projScrolled")))
        check("16. на «Проектах» шапка и строка кнопок стоят на месте",
              R.get("projTabsMoved") == 0 and R.get("projHdrMoved") == 0,
              (R.get("projTabsMoved"), R.get("projHdrMoved")))
        check("17. нижний край «Проектов» тоже совпал с подсказками",
              R.get("projBottom") is not None and abs(R.get("projBottom") - R.get("sugBottom")) <= 1,
              (R.get("projBottom"), R.get("sugBottom")))
        check("18. кнопка «Файлы принтера» есть в пульте", R.get("pfBtn") == 1, R.get("pfBtn"))
        check("19. окно камеры гаснет и при уходе на «Деталь», и при возврате на камеру",
              R.get("armOnPart") is True and R.get("armOnCam") is True and R.get("armLater") is False,
              (R.get("armOnPart"), R.get("armOnCam"), R.get("armLater")))
        check("20. список файлов принтера открывается своим меню внутри пульта",
              R.get("selBtn") is True and R.get("menuOpen") is True
              and len(R.get("fileRows") or []) == 3 and R.get("menuInside") is True,
              (R.get("selBtn"), R.get("menuOpen"), R.get("fileRows"), R.get("menuInside")))
        #  2.976: кнопок удаления в списке пульта нет — владелец отменил просьбу.
        check("21. кнопок удаления в списке файлов пульта нет (2.976)",
              R.get("delBtns") == 0, R.get("delBtns"))
        check("22. Escape закрывает сначала меню, потом пульт",
              R.get("menuAfterEsc") is False and R.get("panelAfterEsc1") is True
              and R.get("panelAfterEsc2") is False,
              (R.get("menuAfterEsc"), R.get("panelAfterEsc1"), R.get("panelAfterEsc2")))
        check("23. горизонтальной полосы прокрутки нет", R.get("hscroll") is False, R.get("hscroll"))
        _d = R.get("__diag") or {}
        _warn = [w for w in (_d.get("consoleWarnings") or []) if "[WebRTC] camera failed" not in str(w)]
        check("24. консоль браузера чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled"))
              and not [w for w in _warn if "Vue warn" in str(w)],
              json.dumps(_d, ensure_ascii=False)[:260])

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
