# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.977 — раздел карты «Исправления на 07.09.2026» (R-095…R-101), проверенный исполнением.

ЧТО ПРОВЕРЯЕТСЯ:
  R-095  запуск файла, уже лежащего на принтере, зовёт списание филамента (живой сервер —
         tools/test_print_from_printer_deduct_e2e.py; здесь — устройство в файлах);
  R-096  при открытом окне «Файлы принтеров» половина с пультом спрятана целиком (между колонкой
         принтеров и окном ничего не просвечивает), окно начинается вровень с областью «Принтеры»
         и кончается вровень с «Подсказками»;
  R-097  «Открыть расположение файла» — кнопка у имени задачи и у имени детали, а не пункт меню;
  R-098  детали проекта сортируются по видимому статусу тем же порядком, что и задачи;
  R-099  бар вкладок одной длины на всех четырёх вкладках;
  R-100  окно «О программе» при открытом пульте такое же, как без него (логотип не растянут);
  R-101  элемент видеопотока пересоздаётся при смене принтера — прошлый кадр не остаётся;
  плюс   кнопка «Показать камеру» не мелькает в первом кадре после открытия пульта.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_roadmap_fixes_0709_2977.py
"""
import importlib.util
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location("fm_stage_2977", os.path.join(ROOT, "tools", "_fm_ui_stage.py"))
stage = importlib.util.module_from_spec(_s)
_s.loader.exec_module(stage)

SENTINEL = "ROADMAP_FIXES_0709_SENTINEL_2_977"
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
check("1. R-095: путь «файл уже на принтере» зовёт списание, у виртуального принтера есть данные о весе",
      "def _c1_after_dispatch(pid, p, data, fdata):" in SRV and SRV.count("_c1_after_dispatch(pid, p, data,") >= 4
      and "_demo.remember(pid, fname, fdata)" in SRV)
check("2. R-096: половина не перебивает v-show; большие окна равняются по высоте колонки",
      "display: flex !important; flex-direction: column; overflow: hidden !important; }" not in CSS
      and "html.ui3-mode .fm-printer-files-workspace, html.ui3-mode .fm-settings-workspace," in CSS
      and "setProperty('--u3-right-h'" in APPJS)
#  2.978: путь к файлу больше НЕ живёт в дереве проекта (его читает и наблюдатель) —
#  кнопка спрашивает его отдельным маршрутом .../locate по явному действию.
check("3. R-097: кнопки у задачи и детали, пункт меню убран, путь спрашивается отдельно",
      'data-help="qt-reveal"' in HTML and 'data-help="pr-reveal"' in HTML
      and "label: tr('Open file location')" not in APPJS
      and "def locate_project2_file(" in SRV
      and "/files/' + encodeURIComponent(fileId) + '/locate'" in APPJS
      and '"stored_path": f["stored_path"] or ""' not in SRV)
#  15.09.2026 («Отправка» до подтверждения принтером): у детали появился СВОЙ видимый статус —
#  пока по любой её плите идёт отправка, в строке стоит «отправка». Сортировка берёт теперь его
#  (p2PartOwnKey), а не сырое поле status. Смысл проверки прежний и даже строже: порядок идёт
#  от того, что ВИДНО в строке, и из общей таблицы статусов задач.
check("4. R-098: детали — по видимому статусу, порядок тот же, что у задач",
      "va = statusRank[liveStatusKey(a.live_printers, p2PartOwnKey(a))] ?? 9;" in APPJS
      and "vb = statusRank[liveStatusKey(b.live_printers, p2PartOwnKey(b))] ?? 9;" in APPJS
      and "const statusRank = _TASK_STATUS_ORDER;" in APPJS
      and "const p2PartOwnKey = (pp) => {" in APPJS)
check("5. R-099: бар вкладок на всю ширину", "html.ui3-mode .ui3-rtabs { display: flex; width: 100%;" in CSS)
check("6. R-100: правила стыковки камеры относятся только к окну камеры",
      not [l for l in CSS.splitlines() if "#fm-overlay-root" in l and "fm-cam-ov" not in l and not l.strip().startswith("/*")]
      and 'class="fm-cam-ov fixed inset-0' in HTML)
check("7. R-101: элементы потока пересоздаются при смене принтера",
      ":key=\"'cami-' + cameraPrinterId\"" in HTML and ":key=\"'camv-' + cameraPrinterId\"" in HTML
      and ":key=\"'camf-' + cameraPrinterId\"" in HTML)
check("8. кнопка «Показать камеру» не рисуется, пока камера открывается",
      'v-if="!cameraPrinterId && !ui3CamPending"' in HTML and "const ui3CamPending = ref(false);" in APPJS)

print()
print("--- 2. исполнение: настоящая страница ---")
PR = [{"id": "k1", "name": "K2_Plus_01", "type": "klipper", "model": "Creality K2 Plus",
       "ip": "10.0.0.71", "port": 7125, "serial": "FIXTURE_K1", "access_code": ""},
      {"id": "b1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_B1", "access_code": ""}]
_PRJ = {"id": "P1", "name": "Заказ 17", "due_date": "", "is_archived": 0, "created_at": "2026-09-30",
        "required_total": 36, "printed_total": 7, "parts_count": 3, "files_count": 1}
#  Три детали: «в работе», «печатается сейчас» (живой принтер) и «готово» — порядок должен быть:
#  печатается, в работе, готово.
_PARTS = {"project": _PRJ, "parts": [
    {"part_id": "ppA", "part_name": "А_в_работе", "required_qty": 12, "printed_qty": 3, "status": "in_progress",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": [], "plates": [{"filename": "korpus.gcode.3mf", "on_plate_qty": 1}], "order_idx": 0},
    {"part_id": "ppB", "part_name": "Б_готово", "required_qty": 2, "printed_qty": 2, "status": "done",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": [], "plates": [{"filename": "korpus.gcode.3mf", "on_plate_qty": 1}], "order_idx": 1},
    {"part_id": "ppC", "part_name": "В_печатается", "required_qty": 12, "printed_qty": 1, "status": "in_progress",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": ["b1"], "plates": [{"filename": "korpus.gcode.3mf", "on_plate_qty": 1}], "order_idx": 2}]}
_TREE = {"project": _PRJ, "nodes": [{"id": "f1", "name": "korpus.gcode.3mf", "type": "file", "is_printable": True, "compatible_pids": ["b1"],
                                     "target_model": "Bambu Lab X1 Carbon", "filename": "korpus.gcode.3mf", "stored_path": "C:/tmp/korpus.gcode.3mf",
                                     "children": [{"id": "c%d" % i, "name": n, "qty": 1} for i, n in enumerate(["А_в_работе", "Б_готово", "В_печатается"])]}]}
ST = [{"filename": "Куб_01.gcode", "status": "ready", "printer_id": "", "required_qty": 10, "printed_qty": 1,
       "target_nozzles": 0.4, "target_model": "", "is_printable": True, "notes": "", "src_path": "C:/tmp/Куб_01.gcode",
       "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
       "compatible_pids": ["k1"], "parts": [], "part_total": 0}]
LIVE = {"k1": {"status": "IDLE", "nozzle_count": 1},
        "b1": {"status": "RUNNING", "percent": 40, "remaining_time": 60, "nozzle_count": 1, "file_name": "korpus"}}

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function R(el){ var r = el.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]; }
  var tab = function(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; };
  var out = { firstFrame: null };
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      //  R-099: ширина бара на четырёх вкладках
      var widths = [];
      (function step(i){
        var names = [/Проекты/, /Задачи/, /Очередь/, /Филамент/];
        if (i >= names.length) { out.barWidths = widths; afterBars(); return; }
        click(tab(names[i]));
        setTimeout(function(){ widths.push(q('.ui3-rtabs') ? R(q('.ui3-rtabs'))[2] : null); step(i + 1); }, 400);
      })(0);
      function afterBars(){
        //  R-097 у задачи
        click(tab(/Задачи/));
        setTimeout(function(){
          out.taskReveal = !!q('[data-help="qt-reveal"]');
          //  R-098: сортировка деталей по статусу
          click(tab(/Проекты/));
          setTimeout(function(){
            click(q('[data-help="project-card"]'));
            setTimeout(function(){
              out.partReveal = !!q('[data-help="pr-reveal"]');
              var head = qa('.pvtbl.ui3-pv .pvhead .pvc').filter(function(c){ return /Статус|Status/.test(c.textContent); })[0];
              out.statusHead = !!head;
              if (head) click(head);
              setTimeout(function(){
                out.partOrder = qa('.pvtbl.ui3-pv .pvrow.pvpart .pvpname').map(function(e){ return e.textContent.trim(); });
                //  пульт: первый кадр без кнопки «Показать камеру»
                var card = qa('.printer-card').filter(function(c){ return /X1C-01/.test(c.textContent); })[0];
                click(card);
                requestAnimationFrame(function(){
                  out.firstFrame = { camOnBtn: !!q('[data-help="pp-cam-on"]'), panel: !!q('.ui3-pp'), pending: document.documentElement.classList.contains('ui3-cam-arm') };
                  setTimeout(function(){
                    out.camLater = !!q('#fm-overlay-root > .fm-cam-ov');
                    //  R-101: смена принтера пересоздаёт элемент потока
                    var img0 = q('#fm-overlay-root > .fm-cam-ov img, #fm-overlay-root > .fm-cam-ov video');
                    var other = qa('.printer-card').filter(function(c){ return /K2_Plus_01/.test(c.textContent); })[0];
                    out.img0 = !!img0;
                    //  R-096: окно файлов принтеров
                    var pf = q('[data-help="pp-pfiles"]'); if (pf) click(pf);
                    setTimeout(function(){
                      var ws = q('.fm-printer-files-workspace'), pane = q('.printers-pane'), sg = q('[data-help="suggest"]');
                      out.ws = ws ? R(ws) : null; out.pane = pane ? R(pane) : null; out.sug = sg ? R(sg) : null;
                      out.ppHidden = !(q('.ui3-pp') && q('.ui3-pp').offsetParent !== null);
                      var left = pane ? pane.getBoundingClientRect().right : 0, right = ws ? ws.getBoundingClientRect().left : left + 40;
                      var strip = 0;
                      qa('.ui3-pp *').forEach(function(el){ var r = el.getBoundingClientRect(); if (r.width > 3 && r.height > 3 && r.left >= left - 1 && r.right <= right + 1 && el.offsetParent !== null) strip++; });
                      out.strip = strip;
                      //  R-100: «О программе» при открытом пульте
                      try { click(qa('.fm-set-x')[0]); } catch (e) {}
                      setTimeout(function(){
                        var gear = q('[data-tour="settings"]') || q('[data-help="settings"]'); if (gear) click(gear);
                        setTimeout(function(){
                          var ab = qa('button, .fm-set-line').filter(function(b){ return /О программе|About/.test(b.textContent); })[0]; if (ab) click(ab);
                          setTimeout(function(){
                            var lg = q('.fm-about-logo');
                            out.logo = lg ? R(lg) : null;
                            out.logoRatio = lg ? (lg.getBoundingClientRect().width / Math.max(1, lg.getBoundingClientRect().height)) : null;
                            out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
                            res(dump(out));
                          }, 900);
                        }, 900);
                      }, 700);
                    }, 1500);
                  }, 1500);
                });
              }, 500);
            }, 1800);
          }, 700);
        }, 700);
      }
    }, 1700);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("9. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR, "/api/staging": ST, "/api/projects2": [_PRJ],
                   "/api/projects2/P1/partsview": _PARTS, "/api/projects2/P1/tree": _TREE,
                   "/api/printer/b1/files": ["a.gcode"], "/api/printer/k1/files": ["c.gcode"],
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
                   "/api/printer-files/capabilities": {"status": "ok", "read_enabled": True, "delete_enabled": False, "delete_ui_allowed": False,
                                                       "capabilities": {"supported": True, "list_files": True, "delete_files": False}},
                   "/api/printer-files/storages": {"status": "ok", "storages": [{"storage_id": "gcodes", "name": "Память", "read_only": True}]},
                   "/api/printer-files/list": {"status": "ok", "entries": [], "next_cursor": None}})
    stage.set_live(LIVE)
    R = stage.run(JS, window_size=(1600, 900), settle_ms=17000, path="/ui3")
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R:
        check("9. страница отработала", False, str(stage.last_diag())[:250])
    else:
        bw = R.get("barWidths") or []
        check("9. R-099: бар вкладок одной длины на всех четырёх вкладках",
              len(bw) == 4 and all(w and abs(w - bw[0]) <= 1 for w in bw), bw)
        check("10. R-097: кнопка «где лежит файл» есть у задачи и у детали",
              R.get("taskReveal") is True and R.get("partReveal") is True, (R.get("taskReveal"), R.get("partReveal")))
        po = R.get("partOrder") or []
        check("11. R-098: детали по статусу — печатается, в работе, готово (как в задачах)",
              R.get("statusHead") is True and po[:3] == ["В_печатается", "А_в_работе", "Б_готово"], po)
        ff = R.get("firstFrame") or {}
        check("12. в первом кадре после открытия пульта нет кнопки «Показать камеру»",
              ff.get("panel") is True and ff.get("camOnBtn") is False, ff)
        check("13. камера потом открылась", R.get("camLater") is True and R.get("img0") is True, (R.get("camLater"), R.get("img0")))
        ws, pane, sg = R.get("ws"), R.get("pane"), R.get("sug")
        check("14. R-096: окно «Файлы принтеров» начинается вровень с областью «Принтеры»",
              ws and pane and abs(ws[1] - pane[1]) <= 1, (ws, pane))
        check("15. R-096: и кончается вровень с «Подсказками»",
              ws and sg and abs((ws[1] + ws[3]) - (sg[1] + sg[3])) <= 1, (ws, sg))
        check("16. R-096: пульт под окном спрятан целиком, в полосе между колонкой и окном ничего нет",
              R.get("ppHidden") is True and R.get("strip") == 0, (R.get("ppHidden"), R.get("strip")))
        check("17. R-100: логотип в «О программе» при открытом пульте не растянут (шире высоты примерно в 7 раз)",
              R.get("logoRatio") is not None and 5.5 <= R.get("logoRatio") <= 8.5, (R.get("logo"), R.get("logoRatio")))
        check("18. горизонтальной полосы нет", R.get("hscroll") is False, R.get("hscroll"))
        _d = R.get("__diag") or {}
        _warn = [w for w in (_d.get("consoleWarnings") or []) if "[WebRTC] camera failed" not in str(w)]
        check("19. консоль браузера чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled"))
              and not [w for w in _warn if "Vue warn" in str(w)],
              json.dumps(_d, ensure_ascii=False)[:260])

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
