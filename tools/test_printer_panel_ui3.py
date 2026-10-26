# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.963 — пульт принтера в оформлении 3.0 по утверждённому макету владельца.

ЗАЧЕМ. Владелец отверг три круга набросков и утвердил один полный макет: слева управление
(печать, температуры, материал, служебное, пометки), справа вверху камера на всё свободное
место, под ней задание. Здесь легко ошибиться молча: нарисовать кнопку, за которой нет
команды; показать катушку, которую принтер не подсвечивает; поставить вторую камеру рядом
с общей. Поэтому проверяется ИСПОЛНЕНИЕМ: настоящий браузер, стенд с живым состоянием по
вебсокету, перехват отправленных принтеру команд.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_printer_panel_ui3.py
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "PRINTER_PANEL_UI3_SENTINEL_2_963"
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
ICONS = io.open(os.path.join(ROOT, "web", "design", "icons.js"), encoding="utf-8").read()

print("--- 1. устройство закреплено в файлах ---")
_a = IDX.find('<section v-if="ui3Mode && ui3Printer && ui3PpP" class="ui3-pp')
SEC = IDX[_a:IDX.find("</section>", _a)] if _a >= 0 else ""
check("1. пульт 3.0 — одна секция с разделами: печать, температуры, материал, служебное, вид, задание",
      bool(SEC) and all(('data-help="%s"' % k) in SEC for k in
                        ("pp-print", "pp-temps", "pp-material", "pp-tools", "pp-view", "pp-job", "pp-go", "pp-ams-menu", "pp-close", "pp-alert")))
#  2.973: кнопка правки принтера из пульта убрана — правка живёт в меню карточки (правый клик).
check("1a. кнопки правки принтера в пульте больше нет",
      'data-help="pp-edit"' not in IDX and "openEditPrinter(p)" in APPJS)
check("2. старые плитки, список файлов и кнопки «Задать» из разметки ушли",
      "ui3-pp-files" not in IDX and "ui3-pp-grid" not in IDX and "ui3-pp-cmds" not in IDX and "ui3-pp-set" not in IDX)
check("3. команды принтеру — те же, что у карточки 2.0: pause/resume/stop/nozzle/bed/start_print",
      "sendCmd('resume')" in SEC and "sendCmd('pause')" in SEC and "confirmStop()" in SEC
      and "sendCmd('nozzle', tempNozzle)" in SEC and "sendCmd('bed', tempBed)" in SEC
      and "sendCmd('start_print', printFileName.value);" in APPJS.split("const ui3PpPrint = ", 1)[1][:600])
check("4. выбор катушки перед печатью идёт через то же поле printAmsSlot, что и в 2.0",
      "printAmsSlot.value = (slot == null) ? null : slot;" in APPJS
      and "if (ui3PpAmsChoices.value.length && !ui3AmsPicked.value) { ui3AmsOpen.value = true; return; }" in APPJS)
check("5. камера одна: пульт стыкует общий блок, своего <video> в секции нет",
      "<video" not in SEC and "openCamera(p); nextTick(() => setTimeout(_ui3DockCam, 60));" in APPJS
      and 'class="ui3-camslot"' in SEC)
#  12.09.2026, решение владельца: пометки фермы «сопло / материал / группа» из пульта удалены
#  вместе с записью на сервер.
check("6. пометок фермы в пульте больше нет — ни блока, ни полей, ни функции записи",
      'data-help="pp-marks"' not in IDX and "ui3-pp-marks" not in IDX and "saveMark" not in IDX
      and "saveMark" not in APPJS and "/api/printer/marks" not in APPJS and "ui3-pp-marks" not in CSS)
_exp = APPJS[APPJS.find("goToUi2, uiSwitchVisible, ui3Mode, ui3Printer"):][:900]
check("7. функции пульта отданы шаблону",
      all(n in _exp for n in ("ui3PpP,", "ui3PpS,", "ui3PpBusy,", "ui3TempStep,", "ui3TempPreset,", "ui3PpTrays,",
                              "ui3PpAmsChoices,", "ui3PpPrint,", "ui3PpPrintWith,", "ui3PpSetView,", "ui3PpCamFull,")))
_names = re.findall(r"^\s*'(pp-[a-z]+)':", ICONS, re.M)
check("8. набор иконок пульта — 25 штук одним стилем, три кнопки печати залиты",
      len(_names) == 25 and "'pp-play'" in ICONS and "'pp-pause'" in ICONS and "'pp-stop'" in ICONS
      and ICONS.count("fill=\"currentColor\" stroke=\"none\"") >= 4
      and all(("name=\"%s\"" % n) not in SEC or n in _names for n in _names),
      _names)
_used = set(re.findall(r'<svg-icon name="(pp-[a-z]+)"', SEC))
check("9. каждая иконка в разметке есть в наборе", _used <= set(_names), sorted(_used - set(_names)))
_rules = [l for l in re.sub(r"/\*.*?\*/", "", CSS, flags=re.S).splitlines() if ".ui3-pp-" in l or ".ui3-camslot" in l]
#  08.10.2026: правила пульта бывают и внутри @container, вложенного в @media (раздел 37) —
#  отступ любой, важно лишь, что правило начинается с html.ui3-mode и не задевает интерфейс 2.0.
check("10. каждое правило пульта в ui3.css начинается с html.ui3-mode (или лежит внутри @media/@container)",
      _rules and all(l.lstrip().startswith("html.ui3-mode") for l in _rules),
      [l[:60] for l in _rules if not l.lstrip().startswith("html.ui3-mode")][:3])
#  2.1004: пределы колонок переставлены — левая не уже 300px, правая сжимается: раскрытая ячейка
#  не ломается в широком виде. Проверка ждала прежнее правило и краснела с 2.1004.
check("11. раскладка: две колонки, узкий экран — одна колонка с камерой сверху",
      "html.ui3-mode .ui3-pp-body { display: grid; grid-template-columns: minmax(300px, 1fr) minmax(0, 384px);" in CSS
      and "html.ui3-mode .ui3-pp-view { order: -1; }" in CSS
      and "html.ui3-mode .ui3-camslot { position: relative; flex: 1 1 auto; min-height: 216px;" in CSS)
#  2.974: пересчёт места вызывается следующим кадром, а не прямо из наблюдателя, — иначе
#  браузер сообщает о круге «пересчёт меняет размер, размер зовёт пересчёт».
check("12. стыковка камеры следит за размером места и уступает режиму «во весь экран»",
      "_ui3Ro = new ResizeObserver(() => {" in APPJS
      and "_ui3RoRaf = requestAnimationFrame(() => { _ui3RoRaf = 0; _ui3DockCam(); });" in APPJS
      and "if (ui3CamFull.value) { _ui3CamReady(); return; }" in APPJS)

print("--- 2. исполнение: печатающий Bambu с AMS ---")
JS_RUN = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  function rc(el){ if(!el) return null; var b = el.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; }
  var sent = []; var _f = window.fetch;
  window.fetch = function(u, o){ try { if (String(u).indexOf('/cmd') >= 0 && o && o.body) sent.push(JSON.parse(o.body)); } catch(e){} return _f.apply(this, arguments); };
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('X1C-01') >= 0; })[0];
      if (card) card.click();
      setTimeout(function(){
        var out = {};
        var pp = q('.ui3-pp');
        out.panel = vis(pp);
        out.state = (q('.ui3-pp-state') || {}).textContent;
        out.ctl = rc(q('.ui3-pp-ctl')); out.view = rc(q('.ui3-pp-view')); out.slot = rc(q('.ui3-camslot')); out.job = rc(q('.ui3-pp-job'));
        out.dock = document.documentElement.classList.contains('ui3-cam-dock');
        out.ov = rc(q('#fm-overlay-root > div.fixed'));
        out.camOverlays = qa('#fm-overlay-root video, #fm-overlay-root img').length;
        out.btns = qa('.ui3-pp-sec[data-help="pp-print"] .ui3-pp-btn').map(function(b){ return b.textContent.trim(); });
        out.noSelect = !q('.ui3-pp-sel');
        out.temps = qa('.ui3-pp-temp .cur').map(function(b){ return b.textContent.trim(); });
        out.hot = qa('.ui3-pp-temp.hot').length;
        out.presets = qa('.ui3-pp-presets button:not(.edit)').length;
        out.slots = qa('.ui3-pp-slot').map(function(s){ return s.className.replace('ui3-pp-slot','').trim() + ':' + s.textContent.trim(); });
        out.now = (q('.ui3-pp-t .mini') || {}).textContent;
        out.rem = (q('.ui3-pp-tline') || {}).textContent;
        out.tsub = (q('.ui3-pp-tsub') || {}).textContent;
        out.parts = qa('.ui3-pp-parts span').map(function(s){ return s.textContent.trim(); });
        out.hasScrollX = pp ? pp.scrollWidth > pp.clientWidth + 1 : null;
        var over = [];
        if (pp) { var pr = pp.getBoundingClientRect(); qa('.ui3-pp *').forEach(function(e){ var b = e.getBoundingClientRect(); if (b.width > 0 && b.right > pr.right + 1) over.push(e.className || e.tagName); }); }
        out.over = over.slice(0, 8);
        var plus = q('.ui3-pp-temp[data-help="pp-nozzle"] .ui3-pp-step button:last-child');
        if (plus) { plus.click(); plus.click(); }
        setTimeout(function(){
          out.sentStep = sent.slice();
          out.nozzleInput = (q('.ui3-pp-temp[data-help="pp-nozzle"] input') || {}).value;
          var pre = qa('.ui3-pp-presets button:not(.edit)')[1]; if (pre) pre.click();
          setTimeout(function(){ out.sentPreset = sent.slice(out.sentStep.length); res(dump(out)); }, 300);
        }, 1100);
      }, 1500);
    }, 900);
  }, 1900);
});
"""
PR = [{"id": "c1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_C1", "access_code": ""},
      {"id": "c2", "name": "FF-01", "type": "flashforge", "model": "FlashForge Adventurer 5M",
       "ip": "10.0.0.12", "port": 8899, "serial": "FIXTURE_SN_C2", "access_code": ""}]
FILES = ["korpus_verh_v3.gcode.3mf", "kryshka.gcode", "detal_bolshaya.gcode.3mf"]
RUN = {"status": "RUNNING", "percent": 42, "remaining_time": 73, "file_name": "korpus_v3",
       "nozzle_temp": 231.2, "bed_temp": 70.1, "nozzle_target": 235, "bed_target": 70,
       "total_time": 9480, "elapsed": 5100, "nozzle_count": 1,
       "ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "#1f2937"},
                     {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color": "#ef4444"},
                     {"index": 2, "unit": 0, "tray": 2, "type": "Empty", "color": ""}],
       "ams_now": 0, "parts": [{"name": "korpus", "qty": 2}, {"name": "kryshka", "qty": 1}]}
IDLE = dict(RUN, status="IDLE", percent=0, remaining_time=0, file_name="", elapsed=0, total_time=0,
            nozzle_temp=24, bed_temp=23, nozzle_target=0, bed_target=0, parts=[], ams_now=-1)


def _near(a, b, tol):
    return a is not None and b is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


if stage.engine_ready():
    stage.set_api({"/api/printers": PR, "/api/printer/c1/files": FILES})
    stage.set_live({"c1": RUN})
    R = stage.run(JS_RUN, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                  extra_args=("--force-device-scale-factor=1.0",))
    if not R:
        check("13. печатающий принтер проверен", False, str(stage.last_diag())[:200])
    else:
        check("13. пульт открыт, состояние по-русски", R.get("panel") is True and R.get("state") == "Печатает", R.get("state"))
        check("14. при печати: Пауза и Стоп, файлы и отправка видны, но погашены; списка файлов нет",
              #  2.977 (R-096): «Файлы принтера» есть и у печатающего принтера — проводник только читает.
              R.get("btns") == ["Пауза", "Стоп", "Файлы на принтере · 3", "Отправить файл", "Файлы принтера"] and R.get("noSelect") is True,
              (R.get("btns"), R.get("noSelect")))
        check("15. температуры: текущая → цель, горячие нагреватели отмечены, четыре готовых значения",
              R.get("temps") == ["231°→235°", "70°→70°"] and R.get("hot") == 2 and R.get("presets") == 4,
              (R.get("temps"), R.get("hot"), R.get("presets")))
        check("16. материал: слоты AMS, активный отмечен, пустой погашен, внешняя катушка последней",
              R.get("slots") == ["on:PETG", ":PLA", "empty:пусто", "ext:внешн."] and "AMS 1" in (R.get("now") or ""),
              (R.get("slots"), R.get("now")))
        check("17. задание: детали на столе, проценты, остаток словами, к какому часу, прошло и всего",
              R.get("parts") == ["korpus ×2", "kryshka ×1"] and "42 %" in (R.get("rem") or "")
              and "осталось 1 ч 13 мин" in (R.get("rem") or "") and "готово к" in (R.get("rem") or "")
              and "прошло 1 ч 25 мин" in (R.get("tsub") or "") and "всего 2 ч 38 мин" in (R.get("tsub") or "")
              and "начата" in (R.get("tsub") or ""),
              (R.get("parts"), R.get("rem"), R.get("tsub")))
        _c, _s, _j, _v = R.get("ctl"), R.get("slot"), R.get("job"), R.get("view")
        check("18. широкий экран: камера справа от управления, окно растянуто, задание прижато к низу колонки",
              bool(_c and _s and _j) and _s[0] > _c[0] + _c[2] - 4 and _s[3] >= 216
              and abs((_j[1] + _j[3]) - (_c[1] + _c[3])) <= 6,
              (_c, _s, _j))
        check("19. камера одна и стоит ровно в отведённом месте",
              R.get("dock") is True and R.get("camOverlays") == 1 and _near(R.get("ov"), R.get("slot"), 2),
              (R.get("dock"), R.get("camOverlays"), R.get("ov"), R.get("slot")))
        check("20. два нажатия «+» на сопле — ОДНА команда принтеру с итогом 245",
              R.get("sentStep") == [{"cmd": "nozzle", "val": "245"}] and R.get("nozzleInput") == "245",
              (R.get("sentStep"), R.get("nozzleInput")))
        check("21. готовое значение PETG задаёт сопло 235 и стол 70 двумя командами",
              R.get("sentPreset") == [{"cmd": "nozzle", "val": "235"}, {"cmd": "bed", "val": "70"}], R.get("sentPreset"))
        check("22. ничего не вылезает за край пульта, горизонтальной прокрутки нет",
              R.get("hasScrollX") is False and not R.get("over"), (R.get("hasScrollX"), R.get("over")))
        _d = R.get("__diag") or {}
        check("23. консоль чистая", not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:200])

    print("--- 3. исполнение: узкий экран 1280 ---")
    R2 = stage.run(JS_RUN, window_size=(1280, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    if not R2:
        check("24. узкий экран проверен", False, str(stage.last_diag())[:200])
    else:
        _c, _v = R2.get("ctl"), R2.get("view")
        check("24. на 1280 одна колонка: камера с заданием сверху, управление под ними, ничего не вылезает",
              bool(_c and _v) and _v[1] < _c[1] and R2.get("hasScrollX") is False and not R2.get("over"),
              (_c, _v, R2.get("hasScrollX"), R2.get("over")))
        _d = R2.get("__diag") or {}
        check("25. консоль чистая на 1280", not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:200])

    print("--- 4. исполнение: свободный принтер, запуск печати, вид «Деталь», принтер без камеры ---")
    JS_IDLE = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  var sent = []; var _f = window.fetch;
  window.fetch = function(u, o){ try { if (String(u).indexOf('/cmd') >= 0 && o && o.body) sent.push(JSON.parse(o.body)); } catch(e){} return _f.apply(this, arguments); };
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('X1C-01') >= 0; })[0];
      if (card) card.click();
      setTimeout(function(){
        var out = {};
        out.state = (q('.ui3-pp-state') || {}).textContent;
        out.idle = (q('.ui3-pp-job .ui3-pp-tsub') || {}).textContent;
        //  2.975: файлы принтера выбираются своим списком — в системное поле нельзя было
        //  поставить кнопку удаления. Открываем список, а строки считаем следующим шагом:
        //  страница успевает его нарисовать.
        var selBtn = q('.ui3-pp-fsel .ui3-pp-selbtn');
        if (selBtn) selBtn.click();
        out.goDisabled = (q('.ui3-pp-split .ui3-pp-btn.pri') || {}).disabled;
        out.upload = !!q('[data-help="pp-upload"]');
        setTimeout(function(){
        out.files = qa('.ui3-pp-fit .nm').length;
        var first = qa('.ui3-pp-fit .nm')[0]; if (first) first.click();
        setTimeout(function(){
          out.goDisabled2 = (q('.ui3-pp-split .ui3-pp-btn.pri') || {}).disabled;
          var go = q('.ui3-pp-split .ui3-pp-btn.pri'); if (go) go.click();
          setTimeout(function(){
            out.sentBeforePick = sent.length;
            out.menu = vis(q('.ui3-pp-menu'));
            out.menuItems = qa('.ui3-pp-menu-it').map(function(b){ return b.textContent.trim(); });
            var it = qa('.ui3-pp-menu-it')[1]; if (it) it.click();
            setTimeout(function(){
              out.sent = sent.slice(); out.menuAfter = vis(q('.ui3-pp-menu'));
              var seg = qa('.ui3-pp-seg button'); if (seg[1]) seg[1].click();
              setTimeout(function(){
                out.partShown = vis(q('.ui3-pp-part')); out.slotGone = !q('.ui3-camslot');
                out.dockOff = !document.documentElement.classList.contains('ui3-cam-dock');
                out.camClosed = !q('#fm-overlay-root > div.fixed');
                if (seg[0]) seg[0].click();
                setTimeout(function(){
                  out.slotBack = vis(q('.ui3-camslot'));
                  out.dockBack = document.documentElement.classList.contains('ui3-cam-dock');
                  var x = q('.ui3-pp-back'); if (x) x.click();
                  setTimeout(function(){
                    out.closed = !q('.ui3-pp'); out.restBack = vis(q('.ui3-rtabs'));
                    var ff = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('FF-01') >= 0; })[0];
                    if (ff) ff.click();
                    setTimeout(function(){
                      out.ffState = (q('.ui3-pp-state') || {}).textContent;
                      out.ffNoCam = vis(q('.ui3-camnone')); out.ffPart = vis(q('.ui3-pp-part'));
                      out.ffSeg = !q('.ui3-pp-seg'); out.ffDock = document.documentElement.classList.contains('ui3-cam-dock');
                      res(dump(out));
                    }, 1200);
                  }, 500);
                }, 700);
              }, 500);
            }, 600);
          }, 400);
        }, 300);
        }, 400);
      }, 1500);
    }, 900);
  }, 1900);
});
"""
    stage.set_live({"c1": IDLE})
    R3 = stage.run(JS_IDLE, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R3:
        check("26. свободный принтер проверен", False, str(stage.last_diag())[:200])
    else:
        check("26. свободный принтер: состояние, список из трёх файлов, отправка с компьютера",
              R3.get("state") == "Свободен" and R3.get("files") == 3 and R3.get("upload") is True
              and "свободен" in (R3.get("idle") or ""), (R3.get("state"), R3.get("files"), R3.get("upload"), R3.get("idle")))
        check("27. «Печатать» заперта без файла и оживает после выбора",
              R3.get("goDisabled") is True and R3.get("goDisabled2") is False, (R3.get("goDisabled"), R3.get("goDisabled2")))
        check("28. первое нажатие при AMS не печатает, а спрашивает катушку: внешняя и два заряженных слота",
              R3.get("sentBeforePick") == 0 and R3.get("menu") is True
              and R3.get("menuItems") == ["Внешняя катушка", "AMS 1·1 · PETG", "AMS 1·2 · PLA"],
              (R3.get("sentBeforePick"), R3.get("menu"), R3.get("menuItems")))
        check("29. выбор слота отправляет start_print с этим слотом и закрывает меню",
              R3.get("sent") == [{"cmd": "start_print", "val": FILES[0], "ams_slot": 0}] and R3.get("menuAfter") is False,
              (R3.get("sent"), R3.get("menuAfter")))
        check("30. «Деталь» убирает камеру (и её стыковку), «Камера» возвращает",
              R3.get("partShown") is True and R3.get("slotGone") is True and R3.get("dockOff") is True
              and R3.get("camClosed") is True and R3.get("slotBack") is True and R3.get("dockBack") is True,
              {k: R3.get(k) for k in ("partShown", "slotGone", "dockOff", "camClosed", "slotBack", "dockBack")})
        check("31. крестик закрывает пульт и возвращает проекты и задачи",
              R3.get("closed") is True and R3.get("restBack") is True, (R3.get("closed"), R3.get("restBack")))
        check("32. принтер без камеры: честно сказано, предпросмотр на месте окна, переключателя нет",
              R3.get("ffNoCam") is True and R3.get("ffPart") is True and R3.get("ffSeg") is True and R3.get("ffDock") is False
              and R3.get("ffState") == "Нет данных",
              {k: R3.get(k) for k in ("ffNoCam", "ffPart", "ffSeg", "ffDock", "ffState")})
        _d = R3.get("__diag") or {}
        check("33. консоль чистая", not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:200])
else:
    print("SKIP — браузер стенда недоступен: исполнение не проверено")

print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
