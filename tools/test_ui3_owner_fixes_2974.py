# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.974 — десять просьб владельца по оформлению 3.0, проверенные исполнением.

ЗАЧЕМ ОДИН НАБОР НА ДЕСЯТЬ ПРАВОК. Все они пришли одним списком после работы на живой ферме
и все про одно: интерфейс не должен вести себя неожиданно. Держать их вместе полезно — видно,
что ни одна не потерялась.

ЧТО ПРОВЕРЯЕТСЯ:
  1. предупреждение о конце филамента не двоится;
  2. окно камеры не мелькает во весь экран, пока не встало на своё место;
  3-4. «Файлы принтера» убраны из меню карточки (и вместе с ними — открытие камеры следом);
  5. поле «Предупреждать ниже» и «Заметки» детали не откатываются во время правки;
  6. выключателя панели подсказок в настройках нет, сворачивание осталось;
  7. на вкладке «Задачи» прокручивается только список, шапка стоит;
  8. линии выполнения плана в задачах и проектах нет;
  9. отчёт об удаче и обычное сообщение живут три секунды;
 10. в настройках нет щели между баром и закреплённым рядом разделов — ни на одной вкладке.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_ui3_owner_fixes_2974.py
"""
import importlib.util
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location("fm_stage_2974", os.path.join(ROOT, "tools", "_fm_ui_stage.py"))
stage = importlib.util.module_from_spec(_s)
_s.loader.exec_module(stage)

SENTINEL = "UI3_OWNER_FIXES_SENTINEL_2_974"
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
check("1. ключ катушки не зависит от того, каким путём слот попал в таблицу",
      "spoolKey: sp ? (pid + '/' + (sp.id != null ? 'id' + sp.id" in APPJS
      and "':' + key + ':'" not in APPJS)
check("2. повтор того же сообщения не создаёт вторую строку",
      "const _same = toasts.value.find(x => x && x.msg === t.msg && x.type === t.type" in APPJS)
check("3. окно камеры гасится, пока не встало на место",
      #  2.977 (R-100): правила стыковки камеры относятся ТОЛЬКО к окну камеры (.fm-cam-ov),
      #  а не к любому окну слоя — прежний селектор div.fixed.inset-0 задевал «О программе».
      "html.ui3-mode.ui3-cam-arm #fm-overlay-root > .fm-cam-ov" in CSS
      and "const _ui3CamArm = () =>" in APPJS and "const _ui3CamReady = () =>" in APPJS
      and APPJS.count("_ui3CamArm(); openCamera(p)") == 2)
check("4. «Файлы принтера» убраны из меню карточки принтера",
      "openPrinterFiles(p.id)" not in APPJS and "tr('Printer files')" not in APPJS
      and "const openPrinterFiles" in APPJS)   # сам проводник остаётся — он в настройках
check("5. поле порога привязано двусторонне и лениво",
      'v-model.lazy="ui3FilLowInput"' in HTML and "const ui3FilLowInput = computed({" in APPJS)
check("6. поля детали проекта помечаются правящимися и не затираются обновлением",
      "const p2Dirty = ref({})" in APPJS
      and "const keys = Object.keys(p2Dirty.value || {});" in APPJS
      and "if (f in op) np[f] = op[f];" in APPJS)
check("7. выключателя панели подсказок в настройках нет, сворачивание осталось",
      "set-suggestions-toggle" not in HTML and "showSuggestions ||" not in HTML
      and 'data-help="suggest-fold"' in HTML and "toggleSuggestCollapsed" in APPJS)
check("8. прокрутка вкладки «Задачи» отдана списку",
      "html.ui3-mode.ui3-right-tasks .projects-pane {" in CSS
      and "html.ui3-mode.ui3-right-tasks .ui3-taskwrap > .qt-panel {" in CSS
      and "ui3-taskwrap" in HTML)
check("9. линия выполнения плана убрана из оформления 3.0",
      'v-if="ui3Mode && pp.required_qty" class="qtprog"' not in HTML
      and 'v-if="!ui3Mode && stagingProgress(f).req" class="qtprog"' in HTML)
check("10. срок обычного сообщения — три секунды",
      "const MSG_LIFE = { ok: 3000, info: 3000, warn: 1200000, bad: 0, work: 0 }" in APPJS)
check("11. в настройках верхний отступ снят с области прокрутки и отдан заголовку",
      "html.ui3-mode .fm-settings-workspace .fm-set-scroll { padding-top: 0 !important; }" in CSS
      and "html.ui3-mode .fm-settings-workspace .fm-set-scroll > .fm-set-head { padding-top: 18px !important; }" in CSS)
_rules = [l for l in CSS.splitlines() if (".ui3-taskwrap" in l or ".ui3-cam-arm" in l or ".fm-set-mini" in l)
          and "{" in l and not l.strip().startswith("/*")]
check("12. каждое новое правило начинается с html.ui3-mode",
      _rules and all(l.startswith("html.ui3-mode") for l in _rules),
      [l[:60] for l in _rules if not l.startswith("html.ui3-mode")])

print()
print("--- 2. исполнение: настоящая страница ---")
PR = [{"id": "b1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_B1", "access_code": ""},
      {"id": "k1", "name": "K2-01", "type": "klipper", "model": "Creality K2 Plus",
       "ip": "10.0.0.71", "port": 7125, "serial": "FIXTURE_K1", "access_code": ""}]
#  У обеих катушек остаток ниже порога — предупреждений должно быть ровно два, не четыре.
FIL = {"printers": {
    "b1": {"has_ams": True, "slots": [
        {"index": 0, "unit": 0, "tray": 0, "external": False, "offline": False,
         "spool": {"id": "s1", "vendor_name": "Bambu", "material": "PETG", "color_name": "чёрный",
                   "color_hex": "#1f2937", "weight_remaining_g": 90, "weight_total_g": 1000}}]},
    "k1": {"has_ams": True, "slots": [
        {"index": 0, "unit": 0, "tray": 0, "external": False, "offline": False,
         "spool": {"id": "s3", "vendor_name": "Creality", "material": "PLA", "color_name": "белый",
                   "color_hex": "#f5f5f5", "weight_remaining_g": 70, "weight_total_g": 1000}}]}}}
LIVE = {"b1": {"status": "IDLE", "nozzle_count": 1, "ams_now": 0,
               "ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "#1f2937"}]},
        "k1": {"status": "IDLE", "nozzle_count": 1, "cfs_now": -1,
               "cfs_trays": [{"index": 0, "type": "PLA", "color": "#f5f5f5"}]}}
ST = [{"filename": "Куб_%02d.gcode" % i, "status": "ready", "printer_id": "", "required_qty": 10,
       "printed_qty": i % 10, "target_nozzles": 0.4, "target_model": "", "is_printable": True,
       "notes": "", "src_path": "", "linked": False, "missing": False, "project_id": "",
       "project_name": "", "project_sync": False, "compatible_pids": [], "parts": [], "part_total": 0}
      for i in range(16)]

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = {};
  var tab = function(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; };
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      //  ── меню карточки принтера: «Файлы принтера» быть не должно ──
      try {
        var card = q('.printer-card');
        card.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, clientX: 120, clientY: 200}));
      } catch (e) { out.e1 = String(e); }
      setTimeout(function(){
        out.menu = qa('.ctx-menu button, .ctx-menu .ctx-item').map(function(b){ return b.textContent.trim(); });
        try { document.body.click(); } catch (e) {}
        //  ── камера: пока не встала на место, её не видно ──
        try { click(q('.printer-card')); } catch (e) { out.e2 = String(e); }
        out.armAtOnce = document.documentElement.classList.contains('ui3-cam-arm');
        var ov0 = q('#fm-overlay-root > div.fixed.inset-0');
        out.armedOpacity = ov0 ? getComputedStyle(ov0).opacity : null;
        setTimeout(function(){
          out.armLater = document.documentElement.classList.contains('ui3-cam-arm');
          out.docked = document.documentElement.classList.contains('ui3-cam-dock');
          //  ── вкладка «Задачи»: прокрутка только в списке, линии плана нет ──
          try { click(q('.ui3-pp-ib[data-help="pp-close"]') || q('.printer-card')); } catch (e) {}
          setTimeout(function(){
            try { click(tab(/Задачи/)); } catch (e) { out.e3 = String(e); }
            setTimeout(function(){
              var pane = q('.projects-pane'), panel = q('.ui3-taskwrap > .qt-panel');
              out.paneOv = pane ? getComputedStyle(pane).overflowY : null;
              out.listOv = panel ? getComputedStyle(panel).overflowY : null;
              out.listScrolls = panel ? (panel.scrollHeight > panel.clientHeight + 1) : null;
              var t0 = q('.ui3-rtabs').getBoundingClientRect().top;
              var f0 = q('.qtfilters') ? q('.qtfilters').getBoundingClientRect().top : null;
              if (panel) panel.scrollTop = 400;
              out.progress = qa('.qtprog').length;
              setTimeout(function(){
                out.scrolled = panel ? Math.round(panel.scrollTop) : null;
                out.tabsMoved = Math.round(q('.ui3-rtabs').getBoundingClientRect().top - t0);
                out.filtMoved = f0 == null ? null : Math.round(q('.qtfilters').getBoundingClientRect().top - f0);
                out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
                //  ── обычное сообщение живёт три секунды ──
                //  Кнопка-рельса запуска в строке задачи. У файлов в стенде нет ни одного
                //  подходящего принтера, поэтому программа обязана сказать об этом сообщением.
                var prn = q('.qt-panel .ui3-qtrail');
                out.railFound = !!prn;
                if (prn) click(prn);
                setTimeout(function(){
                  var noFree = function(){ return qa('.sg-msg .sg-msg-t')
                        .filter(function(m){ return /совместимых|compatible/i.test(m.textContent); }).length; };
                  out.msgAfterClick = noFree();
                  out.msgTexts = qa('.sg-msg .sg-msg-t').map(function(m){ return m.textContent.trim().slice(0, 40); });
                  setTimeout(function(){
                    out.msgAfter8s = noFree();
                    out.msgTexts8 = qa('.sg-msg .sg-msg-t').map(function(m){ return m.textContent.trim().slice(0, 40); });
                    //  ── вкладка «Филамент»: одно предупреждение на катушку, поле не откатывается ──
                    try { click(tab(/Филамент/)); } catch (e) { out.e4 = String(e); }
                    setTimeout(function(){
                      out.lowWarns = qa('.sg-msg .sg-msg-t').map(function(m){ return m.textContent.trim(); })
                                       .filter(function(t){ return /Скоро кончится|Running low/.test(t); }).length;
                      var inp = q('.ui3-fil input[type="number"]');
                      out.lowFound = !!inp;
                      if (inp) { inp.focus(); inp.value = '4'; inp.dispatchEvent(new Event('input', {bubbles: true})); }
                      setTimeout(function(){
                        out.lowTyped = q('.ui3-fil input[type="number"]').value;
                        out.lowWarns2 = qa('.sg-msg .sg-msg-t').map(function(m){ return m.textContent.trim(); })
                                          .filter(function(t){ return /Скоро кончится|Running low/.test(t); }).length;
                        //  ── настройки: щель под баром на каждой вкладке ──
                        var gear = q('[data-tour="settings"]') || q('[data-help="settings"]')
                                || qa('button').filter(function(b){ return /settings|gear/i.test(b.className + (b.getAttribute('title') || '')); })[0];
                        if (gear) click(gear);
                        setTimeout(function(){
                          out.gaps = [];
                          var navs = qa('.fm-set-nav-item');
                          var step = function(i){
                            if (i >= navs.length) { out.suggestToggle = qa('[data-help="set-suggestions-toggle"]').length; res(dump(out)); return; }
                            click(navs[i]);
                            setTimeout(function(){
                              var sc = q('.fm-set-scroll');
                              if (sc) sc.scrollTop = 420;
                              setTimeout(function(){
                                //  Ряд разделов есть только у «Системы»; на других вкладках верхним
                                //  элементом области стоит заголовок раздела. Скрытый ряд не в счёт.
                                var mini = q('.fm-set-mini');
                                if (mini && mini.offsetParent === null) mini = null;
                                //  Щель берётся из ДВУХ величин: верхнего отступа самой области
                                //  (именно он не давал закреплённому ряду встать вплотную) и,
                                //  где ряд есть, расстояния от верха области до него.
                                out.gaps.push([navs[i].textContent.trim().slice(0, 12),
                                               sc ? getComputedStyle(sc).paddingTop : null,
                                               (sc && mini) ? Math.round(mini.getBoundingClientRect().top - sc.getBoundingClientRect().top) : null]);
                                step(i + 1);
                              }, 500);
                            }, 500);
                          };
                          step(0);
                        }, 900);
                      }, 2200);
                    }, 1200);
                  }, 8000);
                }, 700);
              }, 700);
            }, 1300);
          }, 700);
        }, 1600);
      }, 700);
    }, 1700);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("13. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR, "/api/printer-filament": FIL, "/api/staging": ST,
                   "/api/projects2": [], "/api/farm-settings": {"ok": True, "settings": {"low_pct": "15"}}})
    stage.set_live(LIVE)
    R = stage.run(JS, window_size=(1600, 950), settle_ms=25000, path="/ui3")
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R:
        check("13. страница отработала", False, str(stage.last_diag())[:250])
    else:
        _menu = R.get("menu") or []
        check("13. в меню карточки принтера нет «Файлы принтера», остальное на месте",
              _menu and not [m for m in _menu if "Файлы принтера" in m or "Printer files" in m]
              and [m for m in _menu if "Изменить" in m or "Edit" in m], _menu)
        check("14. камера гасится в тот же миг, когда её открывают",
              R.get("armAtOnce") is True and (R.get("armedOpacity") in (None, "0")),
              (R.get("armAtOnce"), R.get("armedOpacity")))
        check("15. и показывается, когда встала на место: метка снята",
              R.get("armLater") is False, (R.get("armLater"), R.get("docked")))
        check("16. на вкладке «Задачи» прокручивается список, а не вся половина",
              R.get("paneOv") == "hidden" and R.get("listOv") == "auto"
              and R.get("listScrolls") is True and (R.get("scrolled") or 0) > 100,
              (R.get("paneOv"), R.get("listOv"), R.get("listScrolls"), R.get("scrolled")))
        check("17. шапка вкладки стоит на месте, пока список прокручивается",
              R.get("tabsMoved") == 0 and R.get("filtMoved") == 0,
              (R.get("tabsMoved"), R.get("filtMoved")))
        check("18. линии выполнения плана в списке нет, горизонтальной полосы тоже",
              R.get("progress") == 0 and R.get("hscroll") is False,
              (R.get("progress"), R.get("hscroll")))
        check("19. обычное сообщение появилось и через несколько секунд ушло само",
              R.get("railFound") is True and R.get("msgAfterClick") == 1 and R.get("msgAfter8s") == 0,
              (R.get("railFound"), R.get("msgAfterClick"), R.get("msgAfter8s"),
               R.get("msgTexts"), R.get("msgTexts8")))
        check("20. предупреждение о конце филамента — по одному на катушку, а не по два",
              R.get("lowWarns") == 2 and R.get("lowWarns2") == 2,
              (R.get("lowWarns"), R.get("lowWarns2")))
        check("21. поле «Предупреждать ниже» не откатывается во время правки",
              R.get("lowFound") is True and R.get("lowTyped") == "4",
              (R.get("lowFound"), R.get("lowTyped")))
        _gaps = R.get("gaps") or []
        check("22. в настройках щели нет ни на одной вкладке: отступа сверху нет, ряд стоит вплотную",
              len(_gaps) >= 3 and all(g[1] == "0px" for g in _gaps)
              and all(g[2] is None or abs(g[2]) <= 1 for g in _gaps)
              and [g for g in _gaps if g[2] is not None],   # хотя бы на одной вкладке ряд есть
              _gaps)
        check("23. выключателя панели подсказок в настройках нет",
              R.get("suggestToggle") == 0, R.get("suggestToggle"))
        _d = R.get("__diag") or {}
        #  Единственное ожидаемое предупреждение стенда: настоящей камеры здесь нет, поэтому
        #  WebRTC не отвечает и программа честно сообщает о переходе на MJPEG. Это её штатное
        #  поведение при недоступной камере, а не дефект страницы.
        _warn = [w for w in (_d.get("consoleWarnings") or []) if "[WebRTC] camera failed" not in str(w)]
        check("24. консоль браузера чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled"))
              and not [w for w in _warn if "Vue warn" in str(w)],
              json.dumps(_d, ensure_ascii=False)[:260])

print()
print("--- 3. «Заметки» детали проекта не откатываются под руками ---")
#  Список деталей раскрытого проекта перечитывается с сервера каждые три секунды (см.
#  pollInterval в app.js). Владелец набирал заметку — и она возвращалась к прежней. Здесь
#  проверяется именно это: набрали, подождали ДОЛЬШЕ круга обновления, посмотрели.
_PRJ = {"id": "P1", "name": "Заказ 17", "due_date": "", "is_archived": 0, "created_at": "2026-09-01",
        "required_total": 12, "printed_total": 7, "parts_count": 1, "files_count": 1}
_PARTS = {"project": _PRJ, "parts": [
    {"part_id": "pp1", "part_name": "Корпус_редуктора", "required_qty": 12, "printed_qty": 7,
     "status": "in_progress", "notes": "старая заметка", "rework_qty": 0, "rework_done": 0,
     "live_printers": [], "plates": [], "order_idx": 0}]}
_TREE = {"project": _PRJ, "nodes": [
    {"id": "f1", "name": "korpus.gcode.3mf", "type": "file", "is_printable": True,
     "target_model": "Bambu Lab X1 Carbon",
     "children": [{"id": "c1", "name": "Корпус_редуктора", "qty": 1}]}]}

JS_NOTES = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = {};
  //  В оформлении 3.0 заметка детали показана строкой под именем; поле появляется по щелчку
  //  по ней (см. ui3NoteEditFor в app.js).
  var note = function(){ return q('.ui3-qtnote.editing'); };
  var noteAny = function(){ return q('.ui3-qtnoteline'); };
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      try {
        var pt = qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return /Проекты/.test(b.textContent); })[0];
        if (pt) click(pt);
        click(q('[data-help="project-card"]'));
      } catch (e) { out.e1 = String(e); }
      setTimeout(function(){
        //  Заметка живёт в раскрытой строке детали: сперва раскрываем саму строку.
        try { click(qa('.pvtbl .pvrow.pvpart').filter(function(r){ return r.offsetParent !== null; })[0]); } catch (e) { out.e2 = String(e); }
        setTimeout(function(){
        try { if (!note() && noteAny()) click(noteAny().querySelector('span') || noteAny()); } catch (e) { out.e3 = String(e); }
        setTimeout(function(){
        out.noteFound = !!note();
        if (!note()) { out.cells = qa('.ui3-qtnoteline, .pvrow.pvpart').slice(0, 6).map(function(e){ return e.className.slice(0, 40) + '|' + e.textContent.trim().slice(0, 20); }); res(dump(out)); return; }
        var el = note();
        el.focus();
        el.value = 'новая заметка владельца';
        el.dispatchEvent(new Event('input', {bubbles: true}));
        out.typed = el.value;
        setTimeout(function(){
          out.after5s = note() ? note().value : (noteAny() ? ('текстом: ' + noteAny().textContent.trim()) : null);
          res(dump(out));
        }, 5200);
        }, 400);
        }, 900);
      }, 1800);
    }, 1700);
  }, 1500);
});
"""

if stage.engine_ready():
    stage.set_api({"/api/printers": [], "/api/staging": [], "/api/projects2": [_PRJ],
                   "/api/projects2/P1/partsview": _PARTS, "/api/projects2/P1/tree": _TREE,
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    RN = stage.run(JS_NOTES, window_size=(1700, 1000), settle_ms=12000, path="/ui3")
    stage.set_api(None)
    stage.stop()
    if not RN:
        check("25. «Заметки» проверены исполнением", False, str(stage.last_diag())[:250])
    else:
        check("25. поле «Заметки» детали найдено", RN.get("noteFound") is True, RN.get("cells"))
        check("26. набранная заметка на месте и после круга обновления списка",
              RN.get("typed") == "новая заметка владельца"
              and RN.get("after5s") == "новая заметка владельца",
              (RN.get("typed"), RN.get("after5s")))
else:
    check("25. браузерный движок доступен (без него проверить нечем)", False, "движка нет")

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
