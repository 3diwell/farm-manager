# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.915 — UI 3.0 как СЛОЙ ОФОРМЛЕНИЯ рабочего интерфейса.

ЗАЧЕМ. Владелец вернул исходную точку: раскладка ровно как в UI 2.0, разница только в виде.
Страница /ui3 отдаёт тот же web/index.html и подключает лист web/ui3/ui3.css. Здесь легко
ошибиться дважды, и обе ошибки молчаливые: (1) слой заденет рабочую страницу — а она в
продакшене; (2) слой «оформит» так, что поверхности сольются и категории перестанут
различаться, ради чего всё и делалось. И то и другое проверяется ИСПОЛНЕНИЕМ: реальные
вычисленные цвета в браузере, а не намерения в тексте.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_ui3_overlay.py
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

SENTINEL = "UI3_OVERLAY_SENTINEL_2_915"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def rgb(s):
    """'rgb(20, 20, 24)' -> (20,20,24). Нужен, чтобы сравнивать светлоту поверхностей."""
    m = re.findall(r"[\d.]+", str(s or ""))
    return tuple(round(float(x)) for x in m[:3]) if len(m) >= 3 else None


def lum(c):
    """Грубая светлота: для сравнения уровней поверхностей этого достаточно."""
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) if c else None


print("--- 1. устройство закреплено в файлах ---")
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "ui3", "ui3.css"), encoding="utf-8").read()
#  Тот же лист, но без комментариев: проверки «селектора нет в листе» обязаны смотреть
#  на ПРАВИЛА, а не на пояснения — иначе ловят собственную прозу.
CSS_RULES = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
check("1. /ui3 отдаёт рабочую страницу с флагом, вставленным в начало <head>",
      #  2.982 (R-106): страницу 3.0 собирает одна функция _ui3_page_html — её отдают и «/»,
      #  и «/ui3»; проверяем саму функцию и то, что /ui3 ею пользуется.
      "_ui3_page_html()" in SRV.split("def home_ui3()", 1)[1][:1600]
      and '_read_web_text("index.html")' in SRV.split("def _ui3_page_html()", 1)[1][:900]
      and 'content.replace(marker, marker + inject, 1)' in SRV.split("def _ui3_page_html()", 1)[1][:1200]
      and "window.__UI3_MODE__=true" in SRV)
check("2. скрипт выбора интерфейса не зацикливает /ui3",
      "!window.__UI3_MODE__&&!location.hash" in IDX)
check("3. слой включается одним классом на странице",
      "classList.add('ui3-mode')" in APPJS)
check("4. в разметке НЕТ следов отменённой раскладки по окнам "
      "(кнопки разделов в шапке и их логика удалены)",
      "fm-ui3-tabs" not in IDX and "setUi3Section" not in APPJS
      and "ui3-sect-printers" not in CSS)
#  Слой обязан быть ТОЛЬКО оформлением: сами КОЛОНКИ он не прячет. Правила внутри
#  колонки (скрыть раздел проектов или задач) законны — на них держится разделение.
#  Исключение (R-107, 2.985): дашборд без выбранного принтера намеренно прячет правую
#  половину — класс ui3-dash-full ставит app.js по состоянию страницы; выбор принтера
#  или другой вид возвращают колонку. Это состояние, а не оформление, и сторож его знает.
_col_hides = [l for l in CSS.split("\n")
              if "display" in l
              and ".ui3-dash-full" not in l
              and (l.split("{")[0].strip().endswith(".left-col")
                   or l.split("{")[0].strip().endswith(".projects-pane"))]
check("5. лист оформления не прячет сами колонки", not _col_hides, _col_hides[:3])
#  Каждое правило должно начинаться с html.ui3-mode — иначе оно утечёт на рабочую страницу
#  (лист туда не подключается, но правило без области — мина на будущее). Комментарии
#  вырезаем: строка пояснения, кончающаяся запятой, — не селектор.
_nc = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
_selectors = [l.strip() for l in _nc.split("\n")
              if l.strip().endswith("{")
              or (l.strip().endswith(",") and ":" not in l)]
#  08.10.2026: @container (раздел 37 — колонки пульта по ширине самого пульта) — обёртка, как @media;
#  правила внутри неё сами начинаются с html.ui3-mode и проверяются этой же строкой.
_bad_sel = [l for l in _selectors
            if not l.startswith(("html.ui3-mode", "@media", "@container", "@keyframes", "/*"))]
check("6. каждое правило слоя ограничено режимом UI 3.0", not _bad_sel, _bad_sel[:4])

#  2.971: путь записи списка принтеров в базу должен быть ОДИН. Раньше их было три, и одно
#  из них отправляло массив как есть — вместе с нарисованными подделками. Так они и попали
#  в базу владельца.
check("15a. в базу принтеров уходит ОДИН собранный список, и он пропускает только настоящее",
      "const _printersPayload = (" in APPJS
      and "!x.__demo && !x.__ui3demo" in APPJS
      and APPJS.count("executePostMatrix('/api/printers/save'") == 3
      and APPJS.count("executePostMatrix('/api/printers/save', _printersPayload(") == 3,
      APPJS.count("executePostMatrix('/api/printers/save'"))

print("--- 2. вид: уровни поверхностей и цвета в настоящем браузере ---")
PR = [
    {"id": "p%d" % i, "name": "X1C-%02d" % i, "type": "bambu", "model": "Bambu Lab X1 Carbon",
     "ip": "10.0.0.%d" % (10 + i), "port": 8883, "serial": "FIXTURE_SN_%04d" % i,
     "access_code": ""} for i in range(1, 4)
]

JS_UI3 = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function bg(el){ return el ? getComputedStyle(el).backgroundColor : null; }
  setTimeout(function(){
    var later = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (later) later.click();
    setUiLang('ru');
    setTimeout(function(){
      var out = {};
      out.mode = document.documentElement.classList.contains('ui3-mode');
      out.left = !!q('.left-col') && q('.left-col').offsetParent !== null;
      out.right = !!q('.projects-pane') && q('.projects-pane').offsetParent !== null;
      out.demoBtn = q('.fm-ui3-demo') ? 'есть' : null;   // 2.971: кнопки подделок больше нет
      out.before = qa('.printer-card').length;
      setTimeout(function(){
        out.after = qa('.printer-card').length;
        var card = q('.printer-card'), panel = q('.printers-pane');
        out.panelBg = bg(panel);
        out.cardBg = bg(card);
        out.cardRadius = card ? getComputedStyle(card).borderTopLeftRadius : null;
        out.panelRadius = panel ? getComputedStyle(panel).borderTopLeftRadius : null;
        var h2 = q('.printers-pane h2') || q('h2');
        out.h2 = h2 ? { size: getComputedStyle(h2).fontSize,
                        spacing: getComputedStyle(h2).letterSpacing,
                        transform: getComputedStyle(h2).textTransform } : null;
        var dot = card ? card.querySelector('.rounded-full') : null;
        out.dotShadow = dot ? getComputedStyle(dot).boxShadow : null;
        res(dump(out));
      }, 700);
    }, 900);
  }, 1900);
});
"""

R = None
if not stage.engine_ready():
    check("7. браузерный движок доступен (без него оформление проверить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    check("7. браузерный движок доступен", True)
    stage.set_api({"/api/printers": PR})
    R = stage.run(JS_UI3, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                  extra_args=("--force-device-scale-factor=1.0",))
    if not R:
        check("8. страница /ui3 открылась", False, str(stage.last_diag())[:220])
    else:
        check("8. страница /ui3 открылась в режиме оформления", bool(R.get("mode")))
        check("9. раскладка осталась как в UI 2.0: обе колонки на месте",
              R.get("left") is True and R.get("right") is True,
              (R.get("left"), R.get("right")))
        _panel, _card = rgb(R.get("panelBg")), rgb(R.get("cardBg"))
        check("10. уровни поверхности РАЗЛИЧИМЫ: карточка светлее панели",
              _panel and _card and (lum(_card) - lum(_panel)) >= 3,
              (R.get("panelBg"), R.get("cardBg")))
        check("11. но различие СДЕРЖАННОЕ, а не контрастные заплаты",
              _panel and _card and (lum(_card) - lum(_panel)) <= 40,
              (lum(_panel), lum(_card)))
        check("12. форма мягкая: у панели радиус больше, чем у карточки",
              R.get("panelRadius") and R.get("cardRadius")
              and float(str(R["panelRadius"]).replace("px", ""))
              > float(str(R["cardRadius"]).replace("px", "")),
              (R.get("panelRadius"), R.get("cardRadius")))
        _h2 = R.get("h2") or {}
        check("13. заголовки разделов — мелкие, разряжённые, прописные",
              _h2.get("transform") == "uppercase"
              and float(str(_h2.get("size", "0")).replace("px", "")) <= 14
              and float(str(_h2.get("spacing", "0")).replace("px", "")) >= 0.8, _h2)
        check("14. неоновый ореол точки состояния погашен, осталось тихое кольцо",
              R.get("dotShadow") and "6px 0px" not in str(R.get("dotShadow")),
              R.get("dotShadow"))
        #  2.971: подделки «Демо 30» убраны. Они рисовали плитки, похожие на принтеры, но
        #  принтерами не были — и при сохранении списка попадали в базу владельца. Их место
        #  занял настоящий виртуальный принтер, который живёт в базе и слушается кнопок.
        check("15. подделок «Демо 30» больше нет: кнопки нет и лишние плитки не появляются",
              R.get("demoBtn") is None and (R.get("after") or 0) == (R.get("before") or 0)
              and "ui3DemoToggle" not in APPJS and "ui3ApplyDemo" not in APPJS
              and ".fm-ui3-demo" not in CSS,
              (R.get("demoBtn"), R.get("before"), R.get("after")))
        _diag = R.get("__diag") or {}
        check("16. консоль браузера чистая на /ui3",
              not (_diag.get("consoleErrors") or _diag.get("pageErrors") or _diag.get("unhandled"))
              and not [w for w in (_diag.get("consoleWarnings") or []) if "Vue warn" in str(w)],
              json.dumps(_diag, ensure_ascii=False)[:220])

    print("--- 3. рабочая страница «/» не изменилась ---")
    JS_20 = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var later = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (later) later.click();
    setTimeout(function(){
      var card = q('.printer-card');
      res(dump({
        mode: document.documentElement.classList.contains('ui3-mode'),
        skinLink: !!q('link[href*="/ui3/ui3.css"]'),
        demoBtn: qa('.fm-ui3-demo').length,
        left: !!q('.left-col') && q('.left-col').offsetParent !== null,
        right: !!q('.projects-pane') && q('.projects-pane').offsetParent !== null,
        cardBg: card ? getComputedStyle(card).backgroundColor : null
      }));
    }, 900);
  }, 1900);
});
"""
    R2 = stage.run(JS_20, window_size=(1900, 1000), settle_ms=2600, path="/",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R2:
        check("17. рабочая страница открылась", False, str(stage.last_diag())[:220])
    else:
        check("17. на «/» слоя оформления НЕТ: ни класса, ни листа, ни кнопки демо",
              R2.get("mode") is False and R2.get("skinLink") is False
              and R2.get("demoBtn") == 0,
              (R2.get("mode"), R2.get("skinLink"), R2.get("demoBtn")))
        check("18. обе колонки рабочей страницы на месте, как раньше",
              R2.get("left") is True and R2.get("right") is True,
              (R2.get("left"), R2.get("right")))
        check("19. карточка принтера на «/» осталась СВОЕГО цвета — слой её не перекрасил",
              rgb(R2.get("cardBg")) != rgb((R or {}).get("cardBg")),
              (R2.get("cardBg"), (R or {}).get("cardBg")))
        _d2 = R2.get("__diag") or {}
        check("20. консоль браузера чистая на «/»",
              not (_d2.get("consoleErrors") or _d2.get("pageErrors") or _d2.get("unhandled"))
              and not [w for w in (_d2.get("consoleWarnings") or []) if "Vue warn" in str(w)],
              json.dumps(_d2, ensure_ascii=False)[:220])

print("--- 4. нажатие на принтер: пульт и камера вместо проектов ---")
JS_PP = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  function byName(n){ return qa('[data-pid]').filter(function(c){ return c.textContent.indexOf(n) >= 0; })[0]; }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var out = { restBefore: vis(q('.ui3-rtabs')) };
      var cam = byName('X1C-01'); if (cam) cam.click();
      setTimeout(function(){
        out.panel = vis(q('.ui3-pp'));
        out.name = (q('.ui3-pp-name') || {}).textContent;
        out.restHidden = !vis(q('.ui3-rtabs'));
        out.cardExpanded = !!q('.printer-card.card-active');
        out.camSlot = vis(q('.ui3-camslot'));
        out.dock = document.documentElement.classList.contains('ui3-cam-dock');
        //  2.917: выбранная карточка выделена; значки в плитках; файлы принтера
        out.selCards = qa('.printer-card.ui3-sel').length;
        out.selIsCam = !!(q('.printer-card.ui3-sel') || {}).textContent
          && q('.printer-card.ui3-sel').textContent.indexOf('X1C-01') >= 0;
        out.icons = qa('.ui3-pp-ic').length;
        var ov = q('#fm-overlay-root div.fixed'), slot = q('.ui3-camslot');
        out.camOverlays = qa('#fm-overlay-root video, #fm-overlay-root img').length;
        if (ov && slot) {
          var a = slot.getBoundingClientRect(), b = ov.getBoundingClientRect();
          out.delta = [Math.abs(b.left-a.left), Math.abs(b.top-a.top),
                       Math.abs(b.width-a.width), Math.abs(b.height-a.height)];
        }
        //  2.975: свой список файлов вместо системного поля. Открываем его здесь, а строки
        //  считаем следующим шагом: страница успевает нарисовать список.
        var _fb = q('.ui3-pp-fsel .ui3-pp-selbtn'); if (_fb) _fb.click();
        setTimeout(function(){
        out.files = qa('.ui3-pp-fit .nm').length;
        var _f1 = qa('.ui3-pp-fit .nm').filter(function(b){ return /korpus_verh_v3/.test(b.textContent); })[0];
        if (_f1) _f1.click();
        setTimeout(function(){
        //  Подпись поля обновляется следующим кадром — читаем её после него.
        out.fileSel = (q('.ui3-pp-fsel .ui3-pp-selbtn .t') || {}).textContent &&
                      /korpus_verh_v3/.test(q('.ui3-pp-fsel .ui3-pp-selbtn .t').textContent) ? 1 : 0;
        var ff = byName('FF-01'); if (ff) ff.click();
        setTimeout(function(){
          out.name2 = (q('.ui3-pp-name') || {}).textContent;
          out.noCam = vis(q('.ui3-camnone'));
          out.dock2 = document.documentElement.classList.contains('ui3-cam-dock');
          if (ff) ff.click();
          setTimeout(function(){
            out.restBack = vis(q('.ui3-rtabs'));
            out.panelGone = !vis(q('.ui3-pp'));
            res(dump(out));
          }, 500);
        }, 800);
        }, 300);
        }, 400);
      }, 1200);
    }, 900);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [
        {"id": "c1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_C1", "access_code": ""},
        {"id": "c2", "name": "FF-01", "type": "flashforge", "model": "FlashForge Adventurer 5M",
         "ip": "10.0.0.12", "port": 8899, "serial": "FIXTURE_SN_C2", "access_code": ""}],
        "/api/printer/c1/files": ["korpus_verh_v3.gcode.3mf", "kryshka.gcode",
                                  "detal_bolshaya.gcode.3mf"]})
    R3 = stage.run(JS_PP, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R3:
        check("23. нажатие на карточку проверено", False, str(stage.last_diag())[:200])
    else:
        check("23. нажатие открывает пульт ИМЕННО выбранного принтера",
              R3.get("panel") is True and R3.get("name") == "X1C-01",
              (R3.get("panel"), R3.get("name")))
        check("24. проекты и задачи при этом пропадают",
              R3.get("restBefore") is True and R3.get("restHidden") is True,
              (R3.get("restBefore"), R3.get("restHidden")))
        check("25. сама карточка НЕ раскрывается, как раньше",
              R3.get("cardExpanded") is False, R3.get("cardExpanded"))
        check("26. у принтера с камерой камера появляется тут же",
              R3.get("camSlot") is True and R3.get("dock") is True, 
              (R3.get("camSlot"), R3.get("dock")))
        check("27. камера ОДНА — это блок программы, а не вторая реализация",
              (R3.get("camOverlays") or 0) == 1, R3.get("camOverlays"))
        _dl = R3.get("delta") or [99, 99, 99, 99]
        check("28. камера встаёт ровно в отведённое место (расхождение до 2 точек)",
              max(_dl) <= 2, _dl)
        check("29. у принтера без камеры честно сказано, что её нет",
              R3.get("name2") == "FF-01" and R3.get("noCam") is True
              and R3.get("dock2") is False,
              (R3.get("name2"), R3.get("noCam"), R3.get("dock2")))
        check("29a. выбранный принтер выделен — видно, какой открыт",
              R3.get("selCards") == 1 and R3.get("selIsCam") is True,
              (R3.get("selCards"), R3.get("selIsCam")))
        check("29b. в плитках пульта есть значки (сопло, стол, печать, задание, файлы)",
              (R3.get("icons") or 0) >= 5, R3.get("icons"))
        check("29c. файлы принтера в своём списке и выбираются (2.975)",
              (R3.get("files") or 0) == 3 and R3.get("fileSel") == 1,
              (R3.get("files"), R3.get("fileSel")))
        check("30. повторное нажатие возвращает проекты и задачи",
              R3.get("restBack") is True and R3.get("panelGone") is True,
              (R3.get("restBack"), R3.get("panelGone")))
        _d3 = R3.get("__diag") or {}
        check("31. консоль чистая при работе с пультом",
              not (_d3.get("consoleErrors") or _d3.get("pageErrors") or _d3.get("unhandled")),
              json.dumps(_d3, ensure_ascii=False)[:200])

print("--- 5. правая половина: проекты ИЛИ задачи, края вровень с баром ---")
JS_SPLIT = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  function edge(el){ if(!el) return null; var b=el.getBoundingClientRect();
    return [Math.round(b.left), Math.round(b.right)]; }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var out = {};
      out.tabs = qa('.ui3-rtabs button').map(function(b){ return b.textContent.trim(); });
      out.state1 = { proj: vis(q('.ui3-proj')), tasks: vis(q('.qt-panel')) };
      out.header = edge(q('.fm-header-desktop-v270') || q('header'));
      out.printers = edge(q('.printers-pane'));
      var t = qa('.ui3-rtabs button');
      if (t[1]) t[1].click();
      setTimeout(function(){
        out.state2 = { proj: vis(q('.ui3-proj')), tasks: vis(q('.qt-panel')) };
        out.qt = edge(q('.qt-panel'));
        if (t[0]) t[0].click();
        setTimeout(function(){
          out.state3 = { proj: vis(q('.ui3-proj')), tasks: vis(q('.qt-panel')) };
          res(dump(out));
        }, 450);
      }, 450);
    }, 900);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [
        {"id": "s1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_S1", "access_code": ""}]})
    R4 = stage.run(JS_SPLIT, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R4:
        check("34. разделение проектов и задач проверено", False, str(stage.last_diag())[:200])
    else:
        _tb = R4.get("tabs") or []
        #  2.965: к трём разделам добавился четвёртый — «Филамент».
        check("34. переключатель правой половины: «Проекты | Задачи | Очередь | Филамент»",
              len(_tb) == 4 and _tb[0] == "Проекты" and _tb[1] == "Задачи"
              and _tb[2].startswith("Очередь") and _tb[3].startswith("Филамент"), _tb)
        _s1, _s2, _s3 = R4.get("state1") or {}, R4.get("state2") or {}, R4.get("state3") or {}
        check("35. в состоянии «Проекты» задач на экране нет",
              _s1.get("proj") is True and _s1.get("tasks") is False, _s1)
        check("36. в состоянии «Задачи» проектов на экране нет",
              _s2.get("proj") is False and _s2.get("tasks") is True, _s2)
        check("37. переключение работает в обе стороны",
              _s3.get("proj") is True and _s3.get("tasks") is False, _s3)
        _h, _p, _q = R4.get("header") or [0, 0], R4.get("printers") or [0, 0], R4.get("qt") or [0, 0]
        check("38. левый край панели принтеров вровень с верхним баром (до 2 точек)",
              abs(_p[0] - _h[0]) <= 2, (_h, _p))
        check("39. правый край панели задач вровень с верхним баром (до 2 точек)",
              abs(_q[1] - _h[1]) <= 2, (_h, _q))
        _d4 = R4.get("__diag") or {}
        check("40. консоль чистая при переключении",
              not (_d4.get("consoleErrors") or _d4.get("pageErrors") or _d4.get("unhandled")),
              json.dumps(_d4, ensure_ascii=False)[:200])

print("--- 6. зона задач и карточки проектов ---")
JS_CELLS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function box(el){ if(!el) return null; var b=el.getBoundingClientRect();
    return [Math.round(b.width), Math.round(b.height)]; }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var out = {};
      //  карточки проектов
      var cell = q('.plan-cell');
      out.cell = box(cell);
      out.cellAlign = cell ? getComputedStyle(cell).textAlign : null;
      var ring = cell ? cell.querySelector('.plan-ring rect') : null;
      out.ringRx = ring ? getComputedStyle(ring).rx : null;
      out.ringShadow = ring ? getComputedStyle(ring).filter : null;
      //  зона задач
      var t = qa('.ui3-rtabs button');
      if (t[1]) t[1].click();
      setTimeout(function(){
        out.open = box(q('.qt-open'));
        out.drop = box(q('[data-tour="qtdrop"]'));
        res(dump(out));
      }, 600);
    }, 1300);
  }, 1900);
});
"""
if stage.engine_ready():
    _PROJ = [{"id": "p%d" % i, "name": n, "parts_count": pc, "done_count": dc,
              "printing_count": 0, "files_count": 2, "required_total": pc, "printed_total": dc,
              "rework_pending": 0, "needs_rework": False, "part_thumbs": [],
              "due_date": dd, "created_at": "2026-08-20"}
             for i, (n, pc, dc, dd) in enumerate([
                 ("Заказ №218 — корпуса", 80, 46, "2026-09-02"),
                 ("Заказ №221 — крепёж", 200, 64, "2026-09-05"),
                 ("Свои изделия", 16, 12, "")], 1)]
    stage.set_api({"/api/printers": [
        {"id": "z1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_Z1", "access_code": ""}],
        "/api/projects2": _PROJ})
    R5 = stage.run(JS_CELLS, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R5:
        check("43. зона задач и карточки проверены", False, str(stage.last_diag())[:200])
    else:
        _open, _drop = R5.get("open") or [0, 0], R5.get("drop") or [1, 1]
        #  Было: кнопка 1022x152 во всю ширину зоны. Стало: обычная кнопка у правого края.
        check("43. кнопка «Открыть» компактная, а не во всю ширину",
              _open[0] <= 260 and _open[1] <= 60 and _open[0] < _drop[0] * 0.35,
              (_open, _drop))
        check("44. сама зона задач стала полосой, а не большим прямоугольником",
              _drop[1] <= 110, _drop)
        _cell = R5.get("cell") or [0, 0]
        check("45. карточка проекта — вытянутая карточка, а не крупный квадрат",
              _cell[0] > _cell[1] and _cell[1] <= 220, _cell)
        check("46. текст в карточке выровнен по левому краю, а не по центру",
              R5.get("cellAlign") == "left", R5.get("cellAlign"))
        check("47. кольцо выполнения повторяет скругление карточки и без неонового ореола",
              str(R5.get("ringRx")).startswith("13") and R5.get("ringShadow") == "none",
              (R5.get("ringRx"), R5.get("ringShadow")))
        _d5 = R5.get("__diag") or {}
        check("48. консоль чистая на проектах и задачах",
              not (_d5.get("consoleErrors") or _d5.get("pageErrors") or _d5.get("unhandled")),
              json.dumps(_d5, ensure_ascii=False)[:200])

print("--- 7. очередь: третье состояние правой половины ---")
check("51. в правом меню файла есть пункт «Добавить в очередь»",
      "Добавить в очередь" in APPJS)
#  2.959: спрашивает по-прежнему, но своим окном, а не окном браузера.
check("52. запуск из очереди спрашивает подтверждение своим окном и называет принтер",
      "title: _L('Запустить печать?', 'Start printing?')" in APPJS and "на принтере " in APPJS
      and "window.confirm" not in APPJS)

JS_QUEUE = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var out = {}, t = qa('.ui3-rtabs button');
      if (t[2]) t[2].click();
      setTimeout(function(){
        var tabs = q('.ui3-rtabs'), sec = q('.ui3-q');
        out.screen = vis(sec);
        out.order = !!(tabs && sec)
          && tabs.getBoundingClientRect().top < sec.getBoundingClientRect().top;
        out.rows = qa('.ui3-q-row').length;
        out.go = qa('.ui3-q-go').length;
        out.states = qa('.ui3-q-state').map(function(x){
          return x.textContent.replace(/\s+/g, ' ').trim(); });
        out.why = qa('.ui3-q-row').map(function(r){
          var w = r.querySelector('.ui3-q-why');
          return w ? w.textContent.replace(/\s+/g, ' ').trim() : ''; });
        out.whyOver = qa('.ui3-q-why').filter(function(w){
          var p = w.closest('.ui3-q-row').getBoundingClientRect(), b = w.getBoundingClientRect();
          return b.right > p.right + 1 || w.scrollWidth > w.clientWidth + 2; }).length;
        var an = q('.ui3-q-allow-n b');
        out.allowN = an ? an.textContent.trim() : null;
        out.allowGo = !!q('.ui3-q-allow-go');
        out.projHidden = !vis(q('.ui3-proj'));
        out.tasksHidden = !vis(q('.qt-panel'));
        var w = document.documentElement;
        out.hscroll = w.scrollWidth - w.clientWidth;
        res(dump(out));
      }, 900);
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    #  Три положения сразу: принтер найден, материал файла неизвестен, материала нет ни у кого.
    stage.set_api({
        "/api/printers": [
            {"id": "q1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
             "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_Q1", "access_code": ""},
            {"id": "q2", "name": "K2-02", "type": "klipper", "model": "Creality K2 Plus",
             "ip": "10.0.0.12", "port": 7125, "serial": "FIXTURE_SN_Q2", "access_code": ""}],
        "/api/queue-wait": {"ok": True, "allowed": ["q1"], "items": [
            {"id": "w1", "gcode_file": "korpus.gcode.3mf", "material": "PLA", "state": "waiting",
             "note": "", "created_at": 0, "source": "quick", "part_name": "",
             "match_printer_id": "q1", "match_printer_name": "X1C-01", "match_reason": "ready",
             "match_feed": "external", "match_finished": False, "material_source": "plate"},
            {"id": "w2", "gcode_file": "kryshka.gcode", "material": "", "state": "waiting",
             "note": "", "created_at": 0, "source": "quick", "part_name": "",
             "match_printer_id": "", "match_printer_name": "", "match_reason": "material_unknown"},
            {"id": "w3", "gcode_file": "detal.gcode.3mf", "material": "ABS", "state": "waiting",
             "note": "", "created_at": 0, "source": "quick", "part_name": "",
             "match_printer_id": "", "match_printer_name": "", "match_reason": "no_material",
             "candidates": [
                 {"id": "q1", "name": "X1C-01 с очень длинным именем принтера на дальнем стеллаже фермы",
                  "verdict": "material_mismatch", "finished": False, "status": "IDLE",
                  "have": [{"where": "ams", "label": "", "material": "PLA"},
                           {"where": "ams", "label": "", "material": "PETG-HF Translucent Olive"},
                           {"where": "ext", "label": "", "material": "TPU 95A"}]}],
             "candidates_more": 0}]}})
    R5 = stage.run(JS_QUEUE, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R5:
        check("53. экран очереди проверен", False, str(stage.last_diag())[:200])
    else:
        check("53. экран очереди открывается и идёт ПОД переключателем, а не внутри настроек",
              R5.get("screen") is True and R5.get("order") is True,
              (R5.get("screen"), R5.get("order")))
        check("54. в состоянии «Очередь» проектов и задач на экране нет",
              R5.get("projHidden") is True and R5.get("tasksHidden") is True,
              (R5.get("projHidden"), R5.get("tasksHidden")))
        check("55. показаны все строки очереди", R5.get("rows") == 3, R5.get("rows"))
        #  Главное свойство безопасности: запустить можно только то, чему нашёлся принтер.
        check("56. кнопка «Запустить» есть только у строки с найденным принтером",
              R5.get("go") == 1, R5.get("go"))
        _st = R5.get("states") or []
        check("57. по каждой строке названо имя принтера или точная причина",
              len(_st) == 3 and "X1C-01" in _st[0]
              and "материал" in _st[1] and "материал" in _st[2], _st)
        _why = R5.get("why") or []
        check("57b. под строками пояснение: у найденного — «с внешней катушки», у ненайденного — принтер с причиной и материалами",
              len(_why) == 3 and "внешней катушки" in _why[0] and _why[1] == ""
              and "X1C-01" in _why[2] and "нет нужного материала" in _why[2] and "TPU 95A" in _why[2], _why)
        check("57c. длинное пояснение переносится внутри строки, а не вылезает за неё",
              R5.get("whyOver") == 0, R5.get("whyOver"))
        check("58. на экране очереди виден счётчик разрешённых принтеров и путь их отметить",
              R5.get("allowN") == "1" and R5.get("allowGo") is True,
              (R5.get("allowN"), R5.get("allowGo")))
        check("59. на экране очереди нет горизонтальной прокрутки",
              (R5.get("hscroll") or 0) <= 1, R5.get("hscroll"))
        _d5 = R5.get("__diag") or {}
        check("60. консоль чистая на экране очереди",
              not (_d5.get("consoleErrors") or _d5.get("pageErrors") or _d5.get("unhandled")),
              json.dumps(_d5, ensure_ascii=False)[:200])

print("--- 8. отметка принтеров для очереди в их же панели ---")
JS_PICK = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  function card(id){ return q('[data-pid="' + id + '"]'); }
  function top(el){ return el ? Math.round(el.getBoundingClientRect().top) : null; }
  //  Заглушка стенда отвечает одинаково, поэтому «поставилось ли разрешение» проверяем
  //  по ОТПРАВЛЕННОМУ запросу, а не по тому, что вернул стенд.
  var sent = [];
  var _f = window.fetch;
  window.fetch = function(u, o){
    try {
      if (String(u).indexOf('/api/printer/queue-allowed') >= 0 && o && o.body)
        sent.push(JSON.parse(o.body));
    } catch (e) { /* тело не наше */ }
    return _f.apply(this, arguments);
  };
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var out = {}, btn = q('.ui3-qpick');
      out.btn = vis(btn);
      //  Кнопка обязана стоять в одной строке с «список/сетка» и «Добавить».
      var sw = q('[data-tour="pview"]'), add = q('[data-tour="add-printer"]');
      out.row = (btn && sw && add)
        ? (Math.abs(top(btn) - top(sw)) <= 6 && Math.abs(top(btn) - top(add)) <= 6) : null;
      //  2.1002 (заказ владельца): кнопки шапки стоят СЛЕВА, подпись «Принтеры» — справа.
      //  Меряем не порядок в разметке, а расстояния до краёв панели: при широкой сетке
      //  принтеров панель растягивается, и кнопки раньше уезжали вслед за правым краем.
      var h2 = q('[data-tour="psort"]'), pane = q('.printers-pane');
      var pr = pane ? pane.getBoundingClientRect() : null;
      out.hdrBtnsLeft = (sw && h2) ? (sw.getBoundingClientRect().left < h2.getBoundingClientRect().left) : null;
      out.hdrLeftGap = (pr && sw) ? Math.round(sw.getBoundingClientRect().left - pr.left) : null;
      out.hdrRightGap = (pr && h2) ? Math.round(pr.right - h2.getBoundingClientRect().right) : null;
      //  z1 разрешён с самого начала, z2 — нет: метка обязана стоять ровно на одном.
      out.marks = qa('.ui3-qa').length;
      //  Опечатка в имени переменной оформления (var(--fm-acc) вместо --fm-accent) не видна
      //  ни в разборе файла, ни глазами на снимке — только в вычисленном цвете. Меряем.
      var _m = q('.ui3-qa');
      //  Настоящий акцент слоя: несуществующая переменная даёт пустое значение, свойство
      //  становится недействительным и цвет молча НАСЛЕДУЕТСЯ — на снимке это не видно.
      //  2.936: имя токена сменилось с --u3-accent на --fm-accent. Слой 3.0 больше не держит
      //  своей палитры: он переопределяет токены дизайн-системы, и модуль «Оформление и темы»
      //  меняет именно их. Проверка НЕ ослаблена — она по-прежнему краснеет и на опечатке в
      //  имени, и на любом цвете, кроме акцента слоя.
      var _pr = document.createElement('span');
      _pr.style.color = 'var(--fm-accent)';
      document.body.appendChild(_pr);
      var _acc = getComputedStyle(_pr).color;
      _pr.remove();
      //  Браузер отдаёт цвет двумя способами: rgb(59, 130, 246) и color(srgb 0.23 0.51 0.96),
      //  а после color-mix — почти всегда вторым. Приводим оба к одному виду.
      function rgb3(v){
        var t = String(v);
        var m = t.match(/-?[\d.]+/g);
        if (!m) return null;
        var a = m.slice(t.indexOf('color(') === 0 ? 0 : 0, 3).map(Number);
        if (t.indexOf('color(') === 0) a = a.map(function(x){ return Math.round(x * 255); });
        return a.map(function(x){ return Math.round(x); }).join(',');
      }
      out.accent = rgb3(_acc);
      out.markCss = _m ? (function(c){ return {
        fg: rgb3(c.color), bg: rgb3(c.backgroundColor), br: rgb3(c.borderTopColor),
        bgA: c.backgroundColor }; })(getComputedStyle(_m)) : null;
      out.markOnZ1 = !!(card('z1') && card('z1').querySelector('.ui3-qa'));
      out.markOnZ2 = !!(card('z2') && card('z2').querySelector('.ui3-qa'));
      if (btn) btn.click();
      setTimeout(function(){
        out.modeOn = !!(btn && btn.classList.contains('is-on'));
        out.dashed = qa('.printer-card.ui3-qpick-t').length;
        if (card('z2')) card('z2').click();          // разрешить второму
        setTimeout(function(){
          out.panelAfter = !!q('.ui3-pp');           // пульт открываться НЕ должен
          if (card('z1')) card('z1').click();        // снять с первого
          setTimeout(function(){
            out.sent = sent;
            if (btn) btn.click();                    // выходим из режима
            setTimeout(function(){
              out.modeOff = !!(btn && !btn.classList.contains('is-on'));
              out.dashedOff = qa('.printer-card.ui3-qpick-t').length;
              if (card('z1')) card('z1').click();
              setTimeout(function(){
                out.panelBack = !!q('.ui3-pp');      // обычное нажатие снова открывает пульт
                res(dump(out));
              }, 500);
            }, 350);
          }, 700);
        }, 700);
      }, 450);
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [
        {"id": "z1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_Z1", "access_code": ""},
        {"id": "z2", "name": "K2-02", "type": "klipper", "model": "Creality K2 Plus",
         "ip": "10.0.0.12", "port": 7125, "serial": "FIXTURE_SN_Z2", "access_code": ""}],
        "/api/queue-wait": {"ok": True, "allowed": ["z1"], "items": []},
        "/api/printer/queue-allowed": {"ok": True}})
    R7 = stage.run(JS_PICK, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R7:
        check("61. режим отметки принтеров проверен", False, str(stage.last_diag())[:200])
    else:
        check("61. кнопка режима есть и стоит в одной строке с «список/сетка» и «Добавить»",
              R7.get("btn") is True and R7.get("row") is True, (R7.get("btn"), R7.get("row")))
        check("61б. кнопки шапки «Принтеры» прижаты ВЛЕВО, подпись — вправо (заказ 11.09.2026)",
              R7.get("hdrBtnsLeft") is True
              and isinstance(R7.get("hdrLeftGap"), int) and R7["hdrLeftGap"] <= 40
              and isinstance(R7.get("hdrRightGap"), int) and R7["hdrRightGap"] <= 40,
              {k: R7.get(k) for k in ("hdrBtnsLeft", "hdrLeftGap", "hdrRightGap")})
        check("62. метка стоит ровно на разрешённом принтере и видна без всякого режима",
              R7.get("marks") == 1 and R7.get("markOnZ1") is True and R7.get("markOnZ2") is False,
              (R7.get("marks"), R7.get("markOnZ1"), R7.get("markOnZ2")))
        _mc = R7.get("markCss") or {}
        #  Прозрачный фон или рамка = правило оформления не сработало (чаще всего — опечатка
        #  в имени переменной: несуществующая переменная молча даёт пустое значение).
        _acc = R7.get("accent")
        check("63. метка нарисована ИМЕННО акцентом слоя — знак, фон и рамка",
              bool(_acc) and _mc.get("fg") == _acc and _mc.get("bg") == _acc
              and _mc.get("br") == _acc
              and "rgba(0, 0, 0, 0)" not in str(_mc.get("bgA")), (_acc, _mc))
        check("64. включённый режим виден: кнопка нажата, карточки стали переключателями",
              R7.get("modeOn") is True and (R7.get("dashed") or 0) >= 2,
              (R7.get("modeOn"), R7.get("dashed")))
        #  Главное: в этом режиме нажатие на принтер НЕ открывает пульт, а меняет разрешение.
        check("65. нажатие на принтер в режиме отметки не открывает пульт",
              R7.get("panelAfter") is False, R7.get("panelAfter"))
        _sent = R7.get("sent") or []
        check("66. нажатие ставит разрешение неотмеченному и СНИМАЕТ у отмеченного",
              len(_sent) == 2
              and _sent[0].get("printer_id") == "z2" and _sent[0].get("allowed") is True
              and _sent[1].get("printer_id") == "z1" and _sent[1].get("allowed") is False, _sent)
        check("67. выход из режима возвращает обычное поведение — открывается пульт",
              R7.get("modeOff") is True and (R7.get("dashedOff") or 0) == 0
              and R7.get("panelBack") is True,
              (R7.get("modeOff"), R7.get("dashedOff"), R7.get("panelBack")))
        _d7 = R7.get("__diag") or {}
        check("68. консоль чистая в режиме отметки",
              not (_d7.get("consoleErrors") or _d7.get("pageErrors") or _d7.get("unhandled")),
              json.dumps(_d7, ensure_ascii=False)[:200])

print("--- 9. страница открывается на сохранённой вкладке ---")
#  Поломка 2.920: очередь запрашивалась раньше, чем объявлена, и страница, открытая на вкладке
#  «Очередь», падала при запуске. Проверяем именно ЗАПУСК с сохранённым выбором.
JS_REOPEN = r"""
return new Promise(function(res){
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var out = {};
    //  2.936: вкладки — штатный компонент дизайн-системы .fm-seg/.fm-seg-b, и активное
    //  состояние у него называется .active (раньше здесь был свой класс .is-on).
    out.tab = qa('.ui3-rtabs button.active').map(function(b){
      return b.textContent.replace(/\s+/g, ' ').trim(); })[0] || null;
    out.screen = !!document.querySelector('.ui3-q');
    out.mounted = !document.body.innerHTML.includes('{{');
    res(dump(out));
  }, 2200);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [], "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R8 = stage.run(JS_REOPEN, window_size=(1600, 900), settle_ms=2600,
                   path="/ui3?ls=ui3_right_tab:queue",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R8:
        check("69. открытие страницы на вкладке «Очередь» проверено", False,
              str(stage.last_diag())[:200])
    else:
        check("69. страница, открытая на вкладке «Очередь», запускается и рисует экран",
              R8.get("mounted") is True and R8.get("screen") is True
              and str(R8.get("tab") or "").split()[0] in ("Очередь", "Queue"),
              (R8.get("mounted"), R8.get("screen"), R8.get("tab")))
        _d8 = R8.get("__diag") or {}
        check("70. при таком запуске в консоли нет ошибок",
              not (_d8.get("consoleErrors") or _d8.get("pageErrors") or _d8.get("unhandled")),
              json.dumps(_d8, ensure_ascii=False)[:250])

print("--- 10. светлая тема и движение ---")
check("71. у слоя есть отдельная палитра светлой темы",
      'html.ui3-mode[data-theme="light"]' in CSS and CSS.count('[data-theme="light"]') >= 5)
check("72. движение уважает системную настройку «меньше движения»",
      "prefers-reduced-motion" in CSS)

print("--- 11. три вида принтеров и настоящий «Список» (2.922) ---")
check("73. в оформлении 3.0 видов три, в рабочем 2.0 — прежние два",
      "ui3Mode ? [" in APPJS and "{ id: 'rows', title: 'List view', icon: 'view-list' }" in APPJS
      and APPJS.count("{ id: 'grid', title: 'Grid view', icon: 'view-grid' }") == 2)
check("74. у вида «Ячейки» своя иконка в наборе значков",
      "'view-cells'" in io.open(os.path.join(ROOT, "web", "design", "icons.js"),
                                encoding="utf-8").read())

JS_ROWS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var out = {}, sw = q('[data-tour="pview"]');
      out.cellH = (q('.printer-card') || {offsetHeight: 0}).offsetHeight;
      if (sw) sw.click();                                     // Ячейки -> Список
      setTimeout(function(){
        out.rows = qa('.pc-row').length;
        out.rowH = (q('.pc-row') || {offsetHeight: 0}).offsetHeight;
        var pane = q('.printers-pane'), pr = pane ? pane.getBoundingClientRect() : null;
        //  Ни одна строка не должна вылезать за панель — раньше время печати обрезалось краем.
        out.overflow = qa('.pc-row').filter(function(r){
          var b = r.getBoundingClientRect();
          return pr && (b.right > pr.right + 1 || b.left < pr.left - 1); }).length;
        //  Значения совпадают с «Ячейками»: печатающий принтер показывает всё.
        var run = qa('.pc-row').filter(function(r){ return /печать/i.test(r.textContent); })[0];
        out.runText = run ? run.textContent.replace(/\s+/g, ' ').trim() : '';
        var first = q('.printer-card');
        if (first) first.click();                             // клик по строке = пульт
        setTimeout(function(){
          out.panel = !!q('.ui3-pp');
          var back = q('.ui3-pp-back');
          if (back) back.click();
          setTimeout(function(){
            if (sw) sw.click();                               // Список -> Сетка
            setTimeout(function(){
              out.gridOn = !!q('.pc-grid-cols');
              if (sw) sw.click();                             // Сетка -> Ячейки
              setTimeout(function(){
                out.cellsBack = qa('.pc-row').length === 0 && !q('.pc-grid-cols');
                res(dump(out));
              }, 500);
            }, 500);
          }, 500);
        }, 800);
      }, 600);
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    _RUN = {"status": "RUNNING", "nozzle_temp": 214.3, "bed_temp": 60.1, "percent": 47,
            "remaining_time": 96, "nozzle_count": 1}
    stage.set_api({"/api/printers": [
        {"id": "v1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.41", "port": 8883, "serial": "FIXTURE_SN_V1", "access_code": ""},
        {"id": "v2", "name": "K2-02", "type": "klipper", "model": "Creality K2 Plus",
         "ip": "10.0.0.42", "port": 7125, "serial": "FIXTURE_SN_V2", "access_code": ""}],
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"v1": _RUN})
    R9 = stage.run(JS_ROWS, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_live(None)
    stage.set_api(None)
    stage.stop()
    if not R9:
        check("75. вид «Список» проверен", False, str(stage.last_diag())[:200])
    else:
        check("75. кнопка вида циклит: Ячейки -> Список -> Сетка -> Ячейки",
              R9.get("rows") == 2 and R9.get("gridOn") is True and R9.get("cellsBack") is True,
              (R9.get("rows"), R9.get("gridOn"), R9.get("cellsBack")))
        check("76. строка списка заметно ниже ячейки — это настоящий список, а не те же карточки",
              0 < (R9.get("rowH") or 0) <= 40 and (R9.get("rowH") or 99) * 2 < (R9.get("cellH") or 0),
              (R9.get("rowH"), R9.get("cellH")))
        check("77. ни одна строка не вылезает за панель",
              R9.get("overflow") == 0, R9.get("overflow"))
        _rt = R9.get("runText") or ""
        check("78. печатающий принтер в строке показывает температуры, процент и время",
              "214°" in _rt and "60°" in _rt and "47%" in _rt and "1h 36m" in _rt, _rt)
        check("79. нажатие на строку открывает пульт принтера — как и в других видах",
              R9.get("panel") is True, R9.get("panel"))
        _d9 = R9.get("__diag") or {}
        check("80. консоль чистая в виде «Список»",
              not (_d9.get("consoleErrors") or _d9.get("pageErrors") or _d9.get("unhandled")),
              json.dumps(_d9, ensure_ascii=False)[:200])

print("--- 12. шапка: на /ui3 она ТА ЖЕ, что в рабочем интерфейсе 2.0 (2.937) ---")
#  Заказ владельца 2.937: «бар сверху должен быть точно таким же, как в UI 2.0; там только
#  добавляются кнопки посередине». До этого (2.922) слой переодевал шапку: прятал фигурный
#  SVG с шестерёнкой и языками и рисовал вместо него свои кнопки. Теперь сторожим обратное.
JS_HDR = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var out = {};
      //  Фигура 2.0 с шестерёнкой и языками обязана быть НА МЕСТЕ и внутри бара.
      var svg = q('.fm-header-lang-svg-v270'), hdr = q('header');
      out.svgShown = !!svg && getComputedStyle(svg).display !== 'none'
        && svg.getBoundingClientRect().width > 40;
      out.svgInBar = !!(svg && hdr)
        && svg.getBoundingClientRect().top >= hdr.getBoundingClientRect().top - 1
        && svg.getBoundingClientRect().bottom <= hdr.getBoundingClientRect().bottom + 1;
      //  Фоновая картинка левого выступа тоже на месте.
      var left = q('.fm-header-left-v270');
      out.leftImg = !!left && getComputedStyle(left).backgroundImage !== 'none';
      //  Центральная плашка красится ШТАТНЫМ цветом шапки, а не цветом слоя. Сравниваем
      //  вычисленные цвета: пробный элемент красим токеном и смотрим, что получилось.
      var center = q('.fm-header-center-v270');
      var _pr = document.createElement('span');
      _pr.style.backgroundColor = 'var(--fm-header-surface)';
      document.body.appendChild(_pr);
      var wantBg = getComputedStyle(_pr).backgroundColor;
      _pr.remove();
      out.centerBg = center ? getComputedStyle(center).backgroundColor : null;
      out.wantBg = wantBg;
      out.centerOk = !!center && out.centerBg === wantBg
        && wantBg !== 'rgba(0, 0, 0, 0)';
      //  Своих кнопок шапки в слое больше нет вовсе.
      out.ownBtns = qa('.ui3-hbt').length + qa('.ui3-hdr-acts').length;
      //  Кнопки, которые владелец просил добавить, стоят в середине и внутри бара.
      var sw = q('.fm-ui-switch'), demo = q('.fm-ui3-demo');
      out.switchIn = !!(sw && hdr)
        && sw.getBoundingClientRect().top >= hdr.getBoundingClientRect().top - 1
        && sw.getBoundingClientRect().bottom <= hdr.getBoundingClientRect().bottom + 1;
      out.demoIn = !!(demo && hdr)
        && demo.getBoundingClientRect().top >= hdr.getBoundingClientRect().top - 1
        && demo.getBoundingClientRect().bottom <= hdr.getBoundingClientRect().bottom + 1;
      //  Кнопка демо одета как соседний переключатель, а не как кнопка операционной системы.
      var dcs = demo ? getComputedStyle(demo) : null;
      out.demoDressed = dcs ? (dcs.borderRadius === '7px'
        && dcs.borderTopWidth !== '0px' && dcs.fontWeight === '700') : null;
      //  Языки и шестерёнка 2.0 работают: переключаем язык прямо в фигуре.
      var en = q('.fm-header-lang-en-v270');
      if (en) en.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
      setTimeout(function(){
        var t = qa('.ui3-rtabs button').map(function(b){ return b.textContent.trim(); });
        out.enWorks = t.some(function(x){ return x.indexOf('Tasks') === 0; });
        var ru = q('.fm-header-lang-ru-v270');
        if (ru) ru.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        setTimeout(function(){
          var gear = q('.fm-header-settings-v270');
          if (gear) gear.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
          setTimeout(function(){
            var wsp = document.querySelector('.fm-settings-workspace');
            out.settings = !!wsp && wsp.offsetParent !== null;
            res(dump(out));
          }, 900);
        }, 700);
      }, 900);
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [], "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R10 = stage.run(JS_HDR, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R10:
        check("81. шапка проверена", False, str(stage.last_diag())[:200])
    else:
        check("81. фигура шапки 2.0 (шестерёнка и языки) на месте и внутри бара",
              R10.get("svgShown") is True and R10.get("svgInBar") is True
              and R10.get("leftImg") is True,
              (R10.get("svgShown"), R10.get("svgInBar"), R10.get("leftImg")))
        #  Цвет центральной плашки берётся из штатного токена шапки — как на «/».
        check("82. центральная плашка бара красится штатным --fm-header-surface",
              R10.get("centerOk") is True, (R10.get("centerBg"), R10.get("wantBg")))
        check("83. своих кнопок шапки у слоя не осталось",
              R10.get("ownBtns") == 0, R10.get("ownBtns"))
        #  2.971: кнопка подделок убрана, в середине бара остался переключатель интерфейсов.
        #  2.982 (R-106): переключатель СКРЫТ по решению владельца — 3.0 стал основным, 2.0
        #  открывается адресом /?ui=2. Проверяем, что его в баре нет.
        check("84. переключатель 2.0/3.0 в баре скрыт (R-106)",
              R10.get("switchIn") is False, R10.get("switchIn"))
        check("85. языки и шестерёнка фигуры 2.0 работают на /ui3",
              R10.get("enWorks") is True and R10.get("settings") is True,
              (R10.get("enWorks"), R10.get("settings")))
        _dA = R10.get("__diag") or {}
        check("86. консоль чистая в шапке",
              not (_dA.get("consoleErrors") or _dA.get("pageErrors") or _dA.get("unhandled")),
              json.dumps(_dA, ensure_ascii=False)[:200])

print("--- 13. рабочая страница «/»: шапка и виды не тронуты ---")
JS_UI2 = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  setTimeout(function(){
    var svg = q('.fm-header-lang-svg-v270');
    res(dump({
      svgShown: !!svg && getComputedStyle(svg).display !== 'none',
      noActs: !q('.ui3-hdr-acts'),
      noRows: !q('.pc-row'),
    }));
  }, 2600);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": []})
    R11 = stage.run(JS_UI2, window_size=(1900, 1000), settle_ms=2600, path="/",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R11:
        check("87. страница «/» проверена", False, str(stage.last_diag())[:200])
    else:
        check("87. в рабочем интерфейсе фигурная шапка на месте, новых кнопок и строк нет",
              R11.get("svgShown") is True and R11.get("noActs") is True
              and R11.get("noRows") is True,
              (R11.get("svgShown"), R11.get("noActs"), R11.get("noRows")))

print("--- 14. четыре масштаба владельца: «Список» без дефектов ---")
JS_SCALE = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var sw = q('[data-tour="pview"]');
      if (sw) sw.click();
      setTimeout(function(){
        var pane = q('.printers-pane'), pr = pane ? pane.getBoundingClientRect() : null;
        var w = document.documentElement;
        res(dump({
          rows: qa('.pc-row').length,
          overflow: qa('.pc-row').filter(function(r){
            var b = r.getBoundingClientRect();
            return pr && (b.right > pr.right + 1 || b.left < pr.left - 1); }).length,
          hscroll: w.scrollWidth - w.clientWidth,
          btns: q('.fm-header-lang-svg-v270') ? 1 : 0,
          btnCut: qa('.fm-header-lang-svg-v270, .fm-ui-switch').filter(function(b){
            var r = b.getBoundingClientRect();
            return r.right > w.clientWidth + 1 || r.left < -1; }).length,
        }));
      }, 700);
    }, 1000);
  }, 1900);
});
"""
_SCALES = ((1600, 1000, "80 %"), (1280, 800, "100 %"), (1024, 640, "125 %"), (853, 533, "150 %"))
_n = 88
for _w, _h, _lbl in _SCALES:
    if not stage.engine_ready():
        break
    stage.set_api({"/api/printers": [
        {"id": "s1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.51", "port": 8883, "serial": "FIXTURE_SN_S1", "access_code": ""},
        {"id": "s2", "name": "K2-02", "type": "klipper", "model": "Creality K2 Plus",
         "ip": "10.0.0.52", "port": 7125, "serial": "FIXTURE_SN_S2", "access_code": ""}],
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"s1": {"status": "RUNNING", "nozzle_temp": 214.3, "bed_temp": 60.1,
                           "percent": 47, "remaining_time": 96, "nozzle_count": 1}})
    _R = stage.run(JS_SCALE, window_size=(_w, _h), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_live(None)
    stage.set_api(None)
    stage.stop()
    if not _R:
        check("%d. масштаб %s проверен" % (_n, _lbl), False, str(stage.last_diag())[:160])
    else:
        _dS = _R.get("__diag") or {}
        check("%d. масштаб %s: строки в панели, фигура шапки и кнопки середины в баре, прокрутки и ошибок нет"
              % (_n, _lbl),
              _R.get("rows") == 2 and _R.get("overflow") == 0
              and (_R.get("hscroll") or 0) <= 1 and _R.get("btns") == 1
              and _R.get("btnCut") == 0
              and not (_dS.get("consoleErrors") or _dS.get("pageErrors") or _dS.get("unhandled")),
              (_R.get("rows"), _R.get("overflow"), _R.get("hscroll"), _R.get("btns"),
               _R.get("btnCut"), json.dumps(_dS, ensure_ascii=False)[:120]))
    _n += 1

print("--- 15. вкладка «Задачи»: группы-карточки (2.923) ---")
JS_TASKS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var t = qa('.ui3-rtabs button'); if (t[1]) t[1].click();
      setTimeout(function(){
        var pick = qa('.qtgrp-pick button').filter(function(b){
          return /проект/i.test(b.textContent); })[0];
        if (pick) pick.click();
        setTimeout(function(){
          var out = {};
          var inp = q('.ui3-task > input');
          out.lupa = inp ? getComputedStyle(inp).backgroundImage.indexOf('svg') > 0 : null;
          var fb = qa('.qtfilters button')[0];
          var cf = fb ? getComputedStyle(fb) : null;
          out.filterPill = cf ? cf.borderRadius === '999px' : null;
          var row = q('.pvrow.pvpart'), grp = q('.qtgrp');
          var cr = row ? getComputedStyle(row) : null;
          var cg = grp ? getComputedStyle(grp) : null;
          out.rowCard = cr ? cr.borderRadius : null;
          //  Суть жалобы «всё сливается»: у строки и у заголовка группы теперь РАЗНЫЕ тела.
          out.distinct = (cr && cg) ? (cr.backgroundColor !== cg.backgroundColor
            && cg.backgroundColor !== 'rgba(0, 0, 0, 0)'
            && cr.backgroundColor !== 'rgba(0, 0, 0, 0)') : null;
          var btn = q('.qtqty-btn');
          out.qtyHidden = btn ? getComputedStyle(btn).opacity === '0' : null;
          var badge = q('.qtpv .status-badge');
          out.chip = badge ? getComputedStyle(badge).borderRadius === '999px' : null;
          if (row) row.click();
          setTimeout(function(){
            //  2.924: раскрытия вниз больше нет — панель не появляется ни от какого клика.
            var pan = q('.qtpv-panel');
            out.noPanel = !pan || getComputedStyle(pan).display === 'none';
            out.chevHidden = !q('.qtpv .pvchev')
              || getComputedStyle(q('.qtpv .pvchev')).display === 'none';
            out.partsChip = (q('.ui3-qtparts') || {textContent: ''}).textContent.trim();
            out.goBtn = qa('button.ui3-qtrail').length;   // 2.951: рельса-кнопка
            out.noteField = !!q('.ui3-qtnote');
            var rows2 = qa('.pvrow.pvpart');
            var zrow = rows2[1] || rows2[0];
            var prev = zrow.querySelector('.pvprev');
            if (prev) prev.dispatchEvent(new MouseEvent('mouseenter', {bubbles: false}));
            setTimeout(function(){
              var pop = document.querySelector('body > .thumb-pop-clone');
              var zr = zrow.getBoundingClientRect();
              var pz = pop ? pop.getBoundingClientRect() : null;
              out.zoom = pop ? { w: pop.offsetWidth, img: !!pop.querySelector('img'),
                                 vis: getComputedStyle(pop).visibility === 'visible',
                                 dl: pz ? Math.round(pz.left - zr.left) : null,
                                 db: pz ? Math.round(pz.bottom - zr.top) : null } : null;
              var ic = q('.ui3-qtrail svg');
              out.iconKids = ic ? ic.childElementCount : 0;
              if (prev) prev.dispatchEvent(new MouseEvent('mouseleave', {bubbles: false}));
              setTimeout(function(){
                out.zoomGone = !document.querySelector('body > .thumb-pop-clone');
                var w = document.documentElement;
                out.hscroll = w.scrollWidth - w.clientWidth;
                res(dump(out));
              }, 400);
            }, 500);
          }, 700);
        }, 700);
      }, 900);
    }, 1000);
  }, 1900);
});
"""
_ST_FILES = [
    {"filename": "korpus.gcode.3mf", "status": "new", "required_qty": 12, "printed_qty": 7,
     "notes": "PLA", "cb": 0, "mtime": 0, "src_path": "", "project_id": "p1",
     "project_name": "Дрон", "is_printable": True,
     "parts": [{"name": "korpus", "qty": 1}, {"name": "luchi", "qty": 4}]},
    {"filename": "vint.gcode.3mf", "status": "new", "required_qty": 60, "printed_qty": 44,
     "notes": "", "cb": 0, "mtime": 0, "src_path": "", "project_id": "p2",
     "project_name": "Кофемолка", "is_printable": True, "parts": []},
    {"filename": "test.gcode", "status": "new", "required_qty": 1, "printed_qty": 0,
     "notes": "", "cb": 0, "mtime": 0, "src_path": "", "project_id": "",
     "project_name": "", "parts": []}]
if stage.engine_ready():
    stage.set_api({"/api/printers": [], "/api/staging": _ST_FILES,
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R12 = stage.run(JS_TASKS, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R12:
        check("92. вкладка «Задачи» проверена", False, str(stage.last_diag())[:200])
    else:
        check("92. поиск — поле с лупой", R12.get("lupa") is True, R12.get("lupa"))
        check("93. фильтры — капсулы", R12.get("filterPill") is True, R12.get("filterPill"))
        check("94. каждая задача — карточка со скруглением",
              R12.get("rowCard") == "12px", R12.get("rowCard"))
        #  Ответ на жалобу «всё сливается»: тела строки и заголовка группы РАЗНЫЕ и непрозрачные.
        check("95. заголовок группы отличим от строк: у обоих своё тело, и они разные",
              R12.get("distinct") is True, R12.get("distinct"))
        check("96. кнопки «−/+» спрятаны до наведения — в покое на экране данные",
              R12.get("qtyHidden") is True, R12.get("qtyHidden"))
        check("97. статус — мягкий чип-капсула", R12.get("chip") is True, R12.get("chip"))
        check("98. нажатие на строку НЕ раскрывает панель вниз (2.924), стрелки-обещания нет",
              R12.get("noPanel") is True and R12.get("chevHidden") is True,
              (R12.get("noPanel"), R12.get("chevHidden")))
        check("98a. дополнительное — в строке: чип деталей, чип заметки, рельса-кнопка печати",
              "дет." in str(R12.get("partsChip")) and R12.get("noteField") is True
              and R12.get("goBtn") == 2,
              (R12.get("partsChip"), R12.get("noteField"), R12.get("goBtn")))
        _z = R12.get("zoom") or {}
        check("98b. наведение на миниатюру показывает большой предпросмотр и он исчезает",
              _z.get("w") == 232 and _z.get("img") is True and _z.get("vis") is True
              and R12.get("zoomGone") is True, (_z, R12.get("zoomGone")))
        #  2.925: предпросмотр стыкуется углом со строкой — нижний левый угол попапа лежит
        #  на верхнем левом углу задачи, данные строки не перекрываются.
        _dl = _z.get("dl") if _z.get("dl") is not None else 99
        _db = _z.get("db") if _z.get("db") is not None else 99
        check("98d. предпросмотр стыкуется углом со строкой (расхождение до 1 точки)",
              abs(_dl) <= 1 and abs(_db) <= 1, (_dl, _db))
        check("98e. иконка на рельсе — рисунок принтера с концепта (три фигуры), не пустота",
              (R12.get("iconKids") or 0) >= 3, R12.get("iconKids"))
        #  2.977 (R-097, заказ владельца): «Открыть расположение файла» — кнопкой-папкой у имени
        #  файла (и у имени детали в проекте), а не пунктом правого меню.
        check("98c. «Открыть расположение файла» — кнопка у имени, а не пункт правого меню (2.977)",
              'data-help="qt-reveal"' in IDX and 'data-help="pr-reveal"' in IDX
              and "revealStaging(f.filename)" in IDX and "revealPart(pr, pp)" in IDX
              and "label: tr('Open file location')" not in APPJS)
        check("99. горизонтальной прокрутки нет", (R12.get("hscroll") or 0) <= 1,
              R12.get("hscroll"))
        _dT = R12.get("__diag") or {}
        check("100. консоль чистая на «Задачах»",
              not (_dT.get("consoleErrors") or _dT.get("pageErrors") or _dT.get("unhandled")),
              json.dumps(_dT, ensure_ascii=False)[:200])

print("--- 16. «Задачи» на четырёх масштабах владельца ---")
JS_TSCALE = r"""
return new Promise(function(res){
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var t = qa('.ui3-rtabs button'); if (t[1]) t[1].click();
      setTimeout(function(){
        var w = document.documentElement;
        var pane = document.querySelector('.projects-pane');
        var pr = pane ? pane.getBoundingClientRect() : null;
        res(dump({
          rows: qa('.pvrow.pvpart').length,
          cut: qa('.pvrow.pvpart').filter(function(r){
            var b = r.getBoundingClientRect();
            return pr && (b.right > pr.right + 1 || b.left < pr.left - 1); }).length,
          hscroll: w.scrollWidth - w.clientWidth,
        }));
      }, 900);
    }, 1000);
  }, 1900);
});
"""
_n2 = 101
for _w, _h, _lbl in ((1600, 1000, "80 %"), (1280, 800, "100 %"),
                     (1024, 640, "125 %"), (853, 533, "150 %")):
    if not stage.engine_ready():
        break
    stage.set_api({"/api/printers": [], "/api/staging": _ST_FILES,
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    _R2 = stage.run(JS_TSCALE, window_size=(_w, _h), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not _R2:
        check("%d. задачи на %s проверены" % (_n2, _lbl), False, str(stage.last_diag())[:160])
    else:
        _dU = _R2.get("__diag") or {}
        check("%d. масштаб %s: строки в панели, прокрутки и ошибок нет" % (_n2, _lbl),
              _R2.get("rows") == 3 and _R2.get("cut") == 0
              and (_R2.get("hscroll") or 0) <= 1
              and not (_dU.get("consoleErrors") or _dU.get("pageErrors") or _dU.get("unhandled")),
              (_R2.get("rows"), _R2.get("cut"), _R2.get("hscroll"),
               json.dumps(_dU, ensure_ascii=False)[:120]))
    _n2 += 1

print("--- 17. первый отклик нажатия без задержки (2.926) ---")
check("105. тяжёлая подготовка пульта отложена ЗА первый кадр (двойной rAF), выделение — сразу",
      "requestAnimationFrame(() => requestAnimationFrame(() => {" in APPJS
      and APPJS.index("ui3Printer.value = p.id;")
          < APPJS.index("requestAnimationFrame(() => requestAnimationFrame(() => {"))
check("106. нажатие отвечает стилем без скриптов (:active), и «меньше движения» его гасит",
      ".printer-card:active" in CSS and CSS.count(".printer-card:active") >= 2)

JS_FAST = r"""
return new Promise(function(res){
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = qa('.printer-card')[0];
      var t0 = performance.now();
      card.click();
      //  Выделение обязано стоять уже в первом-втором кадре после нажатия.
      requestAnimationFrame(function(){ requestAnimationFrame(function(){
        res(dump({ selMs: Math.round(performance.now() - t0),
                   sel: card.classList.contains('ui3-sel') }));
      }); });
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [
        {"id": "f1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.91", "port": 8883, "serial": "FIXTURE_SN_F1", "access_code": ""}],
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R13 = stage.run(JS_FAST, window_size=(1600, 900), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R13:
        check("107. мгновенность отклика проверена", False, str(stage.last_diag())[:200])
    else:
        check("107. выделение принтера стоит в первых кадрах после нажатия",
              R13.get("sel") is True and (R13.get("selMs") or 999) < 250,
              (R13.get("sel"), R13.get("selMs")))
        _dF = R13.get("__diag") or {}
        check("108. консоль чистая при быстром нажатии",
              not (_dF.get("consoleErrors") or _dF.get("pageErrors") or _dF.get("unhandled")),
              json.dumps(_dF, ensure_ascii=False)[:200])

print("--- 18. настройки фермы на сервере; пометок фермы и обучения нет (12.09.2026) ---")
check("109. интервал поэтапного запуска читается с сервера и пишется на сервер",
      "_farmSettingsPull" in APPJS and "fetch('/api/farm-settings')" in APPJS
      and APPJS.count("_farmSettingsPush();") >= 2)
#  12.09.2026, решение владельца: пометки «сопло / материал / группа» удалены из пульта вместе с
#  записью на сервер и разовым переносом из браузера; обучение выключено флагом (код тура цел).
check("109a. в разметке и коде страницы пометок нет: ни блока, ни записи, ни переноса из браузера",
      "ui3-pp-marks" not in IDX and "saveMark" not in IDX and "saveMark" not in APPJS
      and "_migrateOldMarks" not in APPJS and "/api/printer/marks" not in APPJS)

JS_MARKS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  var sent = [];
  var _f = window.fetch;
  window.fetch = function(u, o){
    try { if (String(u).indexOf('/api/printer/marks') >= 0) sent.push(String(u)); } catch (e) {}
    return _f.apply(this, arguments);
  };
  //  Старые пометки концепта 2.910 в браузере. Раньше их разово переносила на сервер миграция
  //  (таймер 4 с от загрузки); её больше нет — запросов записи пометок быть не должно.
  try {
    localStorage.removeItem('ui3_marks_migrated');
    localStorage.setItem('ui3_farm_groups', JSON.stringify({ v: 1,
      groups: [{ id: 'g1', name: 'Цех Б' }], assign: { w1: 'g1' },
      props: { w1: { noz: '0.8', mat: 'ABS' } } }));
  } catch (e) {}
  setTimeout(function(){
    var out = {};
    //  Профиль стенда — как у нового пользователя: раньше окно выбора обучения открывалось
    //  само через 0.9 с после загрузки. Теперь его быть не должно.
    out.tourDialog = !!q('.fm-tour-start-panel');
    out.tourCard = !!document.getElementById('tourCardEl');
    setUiLang('ru');
    setTimeout(function(){
      var card = q('.printer-card');
      if (card) card.click();
      setTimeout(function(){
        var view = q('.ui3-pp-view');
        var pult = q('section[class^="ui3-pp"]') || (view && view.closest('section'));
        out.pult = !!pult;
        out.block = !!q('.ui3-pp-marks');
        out.fields = document.querySelectorAll('.ui3-mark').length;
        out.marksText = pult ? /Пометки фермы|Farm marks/.test(pult.innerText || '') : null;
        setTimeout(function(){
          out.sent = sent.length;
          out.tourDialogLater = !!q('.fm-tour-start-panel');
          res(dump(out));
        }, 2800);
      }, 900);
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [
        {"id": "w1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.95", "port": 8883, "serial": "FIXTURE_SN_W1", "access_code": ""}],
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
        "/api/farm-settings": {"ok": True, "settings": {}}})
    R14 = stage.run(JS_MARKS, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R14:
        check("110. пульт без пометок и запуск без обучения проверены", False, str(stage.last_diag())[:200])
    else:
        check("110. пульт открылся, а блока «Пометки фермы» и его полей в нём нет",
              R14.get("pult") is True and R14.get("block") is False and R14.get("fields") == 0
              and R14.get("marksText") is False,
              (R14.get("pult"), R14.get("block"), R14.get("fields"), R14.get("marksText")))
        check("111. старые пометки из браузера на сервер больше не отправляются",
              R14.get("sent") == 0, R14.get("sent"))
        check("112. окно выбора обучения при запуске не появляется, тур не стартует",
              R14.get("tourDialog") is False and R14.get("tourCard") is False
              and R14.get("tourDialogLater") is False,
              (R14.get("tourDialog"), R14.get("tourCard"), R14.get("tourDialogLater")))
        _dM = R14.get("__diag") or {}
        check("113. консоль чистая: пульт без пометок и запуск без обучения",
              not (_dM.get("consoleErrors") or _dM.get("pageErrors") or _dM.get("unhandled")),
              json.dumps(_dM, ensure_ascii=False)[:200])

print("--- 19. пульт открывается из «Очереди» (2.929) ---")
JS_QP = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var t = qa('.ui3-rtabs button');
      if (t[2]) t[2].click();
      setTimeout(function(){
        var out = { queueShown: vis(q('.ui3-q')) };
        var card = q('.printer-card');
        if (card) card.click();
        setTimeout(function(){
          out.panelShown = vis(q('.ui3-pp-head'));
          out.queueHidden = !vis(q('.ui3-q'));
          var back = q('.ui3-pp-back');
          if (back) back.click();
          setTimeout(function(){
            out.queueBack = vis(q('.ui3-q'));
            res(dump(out));
          }, 600);
        }, 900);
      }, 900);
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [
        {"id": "e1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
         "ip": "10.0.0.97", "port": 8883, "serial": "FIXTURE_SN_E1", "access_code": ""}],
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R15 = stage.run(JS_QP, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R15:
        check("114. пульт из очереди проверен", False, str(stage.last_diag())[:200])
    else:
        #  Жалоба владельца: из «Очереди» нажатие на принтер давало чёрное поле —
        #  правило состояния прятало тело пульта, оставался тёмный слот камеры.
        check("114. нажатие на принтер из «Очереди» открывает ПУЛЬТ, а не чёрное поле",
              R15.get("queueShown") is True and R15.get("panelShown") is True
              and R15.get("queueHidden") is True,
              (R15.get("queueShown"), R15.get("panelShown"), R15.get("queueHidden")))
        check("115. возврат из пульта возвращает очередь на экран",
              R15.get("queueBack") is True, R15.get("queueBack"))
        _dQ = R15.get("__diag") or {}
        check("116. консоль чистая при пульте из очереди",
              not (_dQ.get("consoleErrors") or _dQ.get("pageErrors") or _dQ.get("unhandled")),
              json.dumps(_dQ, ensure_ascii=False)[:200])

print("--- 20. снимки владельца 30.08: скрим, колонки, бейдж, бар (2.930) ---")
#  05.09.2026: сценарий «тип принтера -> подсветка подходящих файлов» удалён по заказу владельца.
#  Проверка теперь охраняет его ОТСУТСТВИЕ: ни кода, ни разметки, ни стилей, ни маршрута.
_HTML20 = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
_CSS20 = io.open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8").read()
check("117. сценарий подсветки по типам принтеров удалён без остатка",
      "typeHl" not in APPJS and "printerTypeList" not in APPJS and "plateMatchesHint" not in APPJS
      and "pending-printable" not in APPJS and "pt-type" not in _HTML20 and "isJobHl" not in _HTML20
      and ".pt-type" not in _CSS20 and ".job-hl{" not in _CSS20)
check("118. колонки «Списка» заданы в символах шрифта, разрастание запрещено",
      "flex: 0 0 9ch" in CSS and "flex: 0 0 calc(4ch + 18px)" in CSS
      and "flex: 0 0 8.5ch" in CSS)
check("119. имени принтера гарантирован минимум — оно не схлопывается в ноль",
      "html.ui3-mode .pc-row-name { flex: 1 1 60px; min-width: 40px;" in CSS)
#  2.967, заказ владельца: номер переехал на ПРАВЫЙ край и стал прямоугольником; на
#  температуры он не ложится, потому что лежит в потоке строки последним элементом.
check("120. номер выбора принтера в «Списке» стоит на правом крае, а не на температурах",
      "html.ui3-mode .pc-rows .pc-pick-num { display: none !important; }" in CSS
      and "html.ui3-mode .pc-row-pick {" in CSS and "margin-right: -20px" in CSS
      and 'class="pc-row-pick"' in IDX)
#  2.937, заказ владельца: бар на /ui3 обязан быть ТЕМ ЖЕ, что в 2.0. Значит слой не
#  вправе трогать ни фигуру шапки, ни логотип с брокером, ни переключатель интерфейсов.
check("121. слой не переодевает шапку: правил на .fm-header-* и .fm-ui-switch нет",
      ".fm-header-" not in CSS_RULES and ".fm-ui-switch" not in CSS_RULES,
      [l.strip()[:70] for l in CSS_RULES.split("\n")
       if ".fm-header-" in l or ".fm-ui-switch" in l][:4])
check("122. настройки оформлены слоем: карточки-группы, капсула активного раздела",
      ".fm-settings-workspace .fm-set-group" in CSS
      and ".fm-set-nav-item.active" in CSS and ".fm-set-line + .fm-set-line" in CSS)

JS_SCRIM = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var _f0 = window.fetch;
  window.fetch = function(u, o){
    if (String(u).indexOf('/api/staging') >= 0 && String(u).indexOf('/save') < 0 && window.__EMPTY) {
      return Promise.resolve(new Response('[]', { headers: { 'Content-Type': 'application/json' } }));
    }
    return _f0(u, o);
  };
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var sw = q('[data-tour="pview"]'); if (sw) sw.click();
      setTimeout(function(){
        var out = {};
        function spread(sel){
          var xs = qa('.pc-row').filter(function(r){ return /печать/i.test(r.textContent); })
            .map(function(r){ var e = r.querySelector(sel);
                              return e ? Math.round(e.getBoundingClientRect().right) : null; })
            .filter(function(x){ return x !== null; });
          return xs.length >= 2 ? Math.max.apply(0, xs) - Math.min.apply(0, xs) : 99;
        }
        out.stSpread = spread('.pc-row-st');
        out.etaSpread = spread('.pc-row-eta');
        out.nameMin = Math.min.apply(0, qa('.pc-row-name').map(function(n){
          return Math.round(n.getBoundingClientRect().width); }));
        var t = qa('.pt-type');
        out.typeButtons = t.length;
        if (t[0]) t[0].click();
        setTimeout(function(){
          out.scrimOn = !!q('.fm-spotlight-overlay');
          window.__EMPTY = true;
          setTimeout(function(){
            out.scrimAuto = !q('.fm-spotlight-overlay');
            res(dump(out));
          }, 5600);
        }, 700);
      }, 800);
    }, 1400);
  }, 1900);
});
"""
if stage.engine_ready():
    _PB = [{"id": "b%d" % i, "name": "X%d" % i, "type": "bambu",
            "model": "Bambu Lab X1 Carbon", "ip": "10.0.0.%d" % (40 + i), "port": 8883,
            "serial": "FIXTURE_B%d" % i, "access_code": ""} for i in range(4)]
    stage.set_api({"/api/printers": _PB, 
        "/api/staging": [{"filename": "a.gcode.3mf", "status": "new", "required_qty": 2,
                          "printed_qty": 0, "notes": "", "cb": 0, "mtime": 0, "src_path": "",
                          "is_printable": True, "project_id": "", "project_name": "",
                          "parts": [], "compatible_pids": ["b3"]}],
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"b0": {"status": "RUNNING", "nozzle_temp": 247, "bed_temp": 70,
                            "percent": 1, "remaining_time": 526, "nozzle_count": 1},
                    "b1": {"status": "RUNNING", "nozzle_temp": 84, "bed_temp": 69,
                            "percent": 0, "remaining_time": 379, "nozzle_count": 1},
                    "b2": {"status": "RUNNING", "nozzle_temp": 148, "bed_temp": 70,
                            "percent": 3, "remaining_time": 171, "nozzle_count": 1},
                    "b3": {"status": "IDLE", "nozzle_temp": 25, "bed_temp": 24,
                            "nozzle_count": 1}})
    R16 = stage.run(JS_SCRIM, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R16:
        check("123. сценарии снимков проверены", False, str(stage.last_diag())[:200])
    else:
        _sp1 = R16.get("stSpread") if R16.get("stSpread") is not None else 99
        _sp2 = R16.get("etaSpread") if R16.get("etaSpread") is not None else 99
        check("123. колонки печатающих строк стоят ровно (правые края до 1 точки)",
              _sp1 <= 1 and _sp2 <= 1, (_sp1, _sp2))
        check("124. имя видно в каждой строке (ширина не ноль)",
              (R16.get("nameMin") or 0) >= 30, R16.get("nameMin"))
        #  Суть снимка «пустые строки»: слой висел вечно. Теперь: включился — и сам погас,
        #  когда подсвечивать стало некого.
        #  05.09.2026: типов в подсказках больше нет — нажимать нечего, слой не появляется вовсе.
        check("125. подсказок по типам нет, и затемняющий слой не появляется",
              R16.get("typeButtons") == 0 and R16.get("scrimOn") is False,
              (R16.get("typeButtons"), R16.get("scrimOn")))
        _dS2 = R16.get("__diag") or {}
        check("126. консоль чистая в сценариях снимков",
              not (_dS2.get("consoleErrors") or _dS2.get("pageErrors") or _dS2.get("unhandled")),
              json.dumps(_dS2, ensure_ascii=False)[:200])

print("--- 21. настройки: карточки и капсула на живом экране ---")
JS_SET = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      //  2.937: шестерёнка снова в фигуре шапки 2.0, своей кнопки у слоя нет.
      var gear = q('.fm-header-settings-v270');
      if (gear) gear.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
      setTimeout(function(){
        var out = {};
        var wsp = q('.fm-settings-workspace');
        out.open = !!wsp && wsp.offsetParent !== null;
        var nav = q('.fm-set-nav-item.active');
        out.pill = nav ? getComputedStyle(nav).borderRadius === '10px' : null;
        var grp = q('.fm-settings-workspace .fm-set-group');
        var cg = grp ? getComputedStyle(grp) : null;
        out.card = cg ? (cg.borderRadius === '14px'
          && cg.backgroundColor !== 'rgba(0, 0, 0, 0)') : null;
        var w = document.documentElement;
        out.hscroll = w.scrollWidth - w.clientWidth;
        res(dump(out));
      }, 1100);
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [], 
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R17 = stage.run(JS_SET, window_size=(1280, 800), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R17:
        check("127. настройки проверены", False, str(stage.last_diag())[:200])
    else:
        check("127. настройки: активный раздел — капсула, группы — карточки, прокрутки нет",
              R17.get("open") is True and R17.get("pill") is True and R17.get("card") is True
              and (R17.get("hscroll") or 0) <= 1,
              (R17.get("open"), R17.get("pill"), R17.get("card"), R17.get("hscroll")))
        _dS3 = R17.get("__diag") or {}
        check("128. консоль чистая в настройках",
              not (_dS3.get("consoleErrors") or _dS3.get("pageErrors") or _dS3.get("unhandled")),
              json.dumps(_dS3, ensure_ascii=False)[:200])

print("--- 22. шрифт по центру строк и детали проекта карточками (2.931) ---")
_FCSS = io.open(os.path.join(ROOT, "web", "design", "fonts.css"), encoding="utf-8").read()
#  Рисунок букв шрифта интерфейса занимает ~49% знакоместа и сидел внизу строк по всей
#  программе (снимки владельца). Метрики переопределены в объявлении шрифта — с 26.09.2026 у
#  шрифта по умолчанию «3DIWELL Wide J» в web/design/fonts.css (оба начертания).
_WJ = [f for f in re.findall(r"@font-face\s*\{(.*?)\}", _FCSS, re.S) if "'3DIWELL Wide J'" in f]
check("129. метрики шрифта по умолчанию переопределены: буквы по центру строки",
      len(_WJ) == 2 and all("ascent-override: 74.5%" in f and "descent-override: 25.5%" in f
                            and "line-gap-override: 0%" in f for f in _WJ), _WJ)
check("130. карточки строк — общие для ОБЕИХ таблиц (задачи и детали проекта)",
      "html.ui3-mode .pvtbl .pvrow.pvpart {" in CSS
      and "html.ui3-mode .pvtbl .pvhead {" in CSS
      and "html.ui3-mode .pvtbl .status-badge {" in CSS
      and ".qtpv .pvrow.pvpart {" not in CSS)
check("131. раскрытая деталь проекта прирастает к строке; чип переработки — тихий круг",
      "html.ui3-mode .pvtbl .pvrow.pvpart:has(+ .pvpanel)" in CSS
      and "html.ui3-mode .pvtbl .pvpanel {" in CSS
      and "html.ui3-mode .rw-chip {" in CSS)

print("--- 23. пульт: камера справа, плитки слева, живое колесо (2.932) ---")
#  2.1004: минимум переехал на ПЕРВУЮ колонку. Раньше камера всегда забирала свой максимум,
#  и в виде «дашборд» колонке управления оставалось 214 точек — надписи вылезали за кнопки.
check("132. правила пульта: две колонки при камере, у управления свой минимум, слот без обрезки высоты",
      "html.ui3-mode .ui3-pp-body { display: grid; grid-template-columns: minmax(300px, 1fr) minmax(0, 384px);" in CSS
      and "max-height: 34vh" not in CSS)
#  2.977: окно камеры узнаётся по своему классу .fm-cam-ov, а не по «любому fixed inset-0» —
#  иначе правила стыковки цепляли и чужие окна в #fm-overlay-root (логотип в «О программе»).
check("133. указатель проходит сквозь задокированную камеру, органы управления живые",
      "pointer-events: none !important;" in CSS
      and ".fm-cam-ov button," in CSS)

JS_PANEL2 = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = q('.printer-card');
      if (card) card.click();
      setTimeout(function(){
        var out = {};
        var main = q('.ui3-pp-body');
        var slot = q('.ui3-camslot');
        var grid = q('.ui3-pp-ctl');
        out.twoCols = !!(main && main.classList.contains('has-cam'));
        if (slot && grid) {
          var sb = slot.getBoundingClientRect(), gb = grid.getBoundingClientRect();
          out.camRight = sb.left > gb.right - 4;
          out.tall = sb.height >= 216;
        }
        var ov = document.querySelector('#fm-overlay-root > div.fixed');
        out.docked = !!ov;
        if (ov && slot) {
          var s2 = slot.getBoundingClientRect();
          var hit = document.elementFromPoint(s2.left + s2.width/2, s2.top + s2.height/2);
          out.wheelThrough = !!hit && !ov.contains(hit);
          var btn = ov.querySelector('button');
          if (btn) {
            var bb = btn.getBoundingClientRect();
            var hb = document.elementFromPoint(bb.left + bb.width/2, bb.top + bb.height/2);
            out.btnAlive = !!hb && (hb === btn || btn.contains(hb));
          }
        }
        res(dump(out));
      }, 1400);
    }, 1000);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [
        {"id": "k1", "name": "K2-01", "type": "klipper", "model": "Creality K2 Plus",
         "ip": "10.0.0.71", "port": 7125, "serial": "FIXTURE_K1", "access_code": ""}],
        
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"k1": {"status": "RUNNING", "nozzle_temp": 220, "bed_temp": 60,
                            "percent": 45, "remaining_time": 90, "nozzle_count": 1,
                            "file_name": "x.gcode"}})
    R18 = stage.run(JS_PANEL2, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R18:
        check("134. пульт двумя колонками проверен", False, str(stage.last_diag())[:200])
    else:
        check("134. камера СПРАВА от управления, окно растянуто по высоте колонки (2.963)",
              R18.get("twoCols") is True and R18.get("camRight") is True
              and R18.get("tall") is True,
              (R18.get("twoCols"), R18.get("camRight"), R18.get("tall")))
        #  Суть жалобы «колесо не крутит»: оверлей глотал события. Теперь указатель над
        #  камерой попадает в панель ПОД ней, а кнопки камеры остаются живыми.
        check("135. колесо над камерой уходит панели, органы камеры кликаются",
              R18.get("docked") is True and R18.get("wheelThrough") is True
              and R18.get("btnAlive") is True,
              (R18.get("docked"), R18.get("wheelThrough"), R18.get("btnAlive")))

print("--- 24. дробный масштаб браузера: шрифт не гаснет (2.933) ---")
check("136. буст шрифта включается только при целом масштабе экрана (код)",
      "const _whole = Math.abs(_d - Math.round(_d)) <= 0.001;" in APPJS
      and "isDefaultFont && !isMobile.value && _whole" in APPJS)
check("137. видео камеры заперто в карточке (обрезка), слои ограничены",
      "overflow: hidden !important;" in CSS
      and ".fm-cam-ov > div * {" in CSS)

JS_DPR = r"""
return new Promise(function(res){
  setTimeout(function(){
    res(dump({ dpr: window.devicePixelRatio,
               htmlZoom: getComputedStyle(document.documentElement).zoom }));
  }, 2600);
});
"""
if stage.engine_ready():
    #  На целом масштабе буст стоит, на дробном — снят: это и держит шрифт живым.
    stage.set_api({"/api/printers": []})
    _Ra = stage.run(JS_DPR, window_size=(1200, 700), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    stage.set_api({"/api/printers": []})
    _Rb = stage.run(JS_DPR, window_size=(1200, 700), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.1",))
    stage.set_api(None)
    stage.stop()
    if not _Ra or not _Rb:
        check("138. поведение на масштабах проверено", False, str(stage.last_diag())[:200])
    else:
        check("138. целый масштаб: буст шрифта работает как прежде (html zoom 1.196)",
              str(_Ra.get("htmlZoom")) == "1.196", (_Ra.get("dpr"), _Ra.get("htmlZoom")))
        #  Остаётся базовый html-zoom 1.04 из таблицы стилей — он мягкий и шрифт не
        #  гасит (промерено снимками); гаснул именно буст 1.196 поверх дробного масштаба.
        check("139. дробный масштаб (110%): буст 1.196 снят — остался только базовый 1.04",
              str(_Rb.get("htmlZoom")) == "1.04", (_Rb.get("dpr"), _Rb.get("htmlZoom")))

print("--- 25. правка деталей проекта: список не прыгает (2.934) ---")
check("140. правка использует ту же сетку, что и обычный список (.pvtbl), а не свою таблицу",
      'class="pvtbl p2edit"' in IDX
      and "project2Mode[pr.id] === 'edit'\" class=\"mb-3 rounded-xl" not in IDX)
#  «Printing» встречается ещё и в мобильной вёрстке — считаем не вхождения в файле,
#  а подписи ВНУТРИ самой таблицы правки.
_p2blk = IDX[IDX.index('class="pvtbl p2edit"'):]
_p2blk = _p2blk[:_p2blk.index("</template>")]
check("141. шапка правки повторяет шапку обычного вида (те же подписи)",
      all(x in _p2blk for x in ("{{ tr('Part name') }}", "{{ tr('Req') }}",
                                "{{ tr('Prnt') }}", "{{ lang==='ru'?'Брак':'Defect' }}",
                                "{{ tr('Status') }}", "{{ tr('Printing') }}")))
check("142. якоря правки сохранены: миниатюра, имя, удаление детали",
      IDX.count('class="p2ed-thumb"') == 2
      and 'data-help="edit-part-name"' in IDX
      and "deleteProject2Part(pr.id, pp.part_id)" in IDX)
check("143. место под стрелку и под заметку зарезервировано — высота строк не скачет",
      ".p2ed-chevgap { visibility: hidden; }" in CSS
      and "html.ui3-mode .pvtbl .pvnamecol { min-height: 38px;" in CSS)

JS_P2 = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function cols(root){
    var r = root.querySelector('.pvrow.pvpart');
    if (!r) return null;
    return [].slice.call(r.children).map(function(e){
      var b = e.getBoundingClientRect();
      return [Math.round(b.left), Math.round(b.width)]; });
  }
  function heads(root){
    var h = root.querySelector('.pvrow.pvhead');
    return h ? [].slice.call(h.children).map(function(e){
      return Math.round(e.getBoundingClientRect().left); }) : null;
  }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = qa('.plan-cell')[0];
      if (card) card.click();
      setTimeout(function(){
        var out = {};
        var view = q('.pvtbl:not(.p2edit)');
        out.viewCols = view ? cols(view) : null;
        out.viewHead = view ? heads(view) : null;
        var pen = qa('[data-help="proj-edit"]')[0];
        if (pen) pen.click();
        setTimeout(function(){
          var ed = q('.pvtbl.p2edit');
          out.editCols = ed ? cols(ed) : null;
          out.editHead = ed ? heads(ed) : null;
          //  2.961: в 3.0 числа правки живут в общей капсуле «Итог из План» (.qtpv-qty),
          //  в 2.0 остаются прежними полями (.p2qty). Проверяем, что органы правки есть в любом виде.
          out.hasFields = !!(ed && ed.querySelector('input.p2ed-note')
                             && (ed.querySelector('.p2qty') || ed.querySelector('.qtpv-qty'))
                             && ed.querySelector('.p2ed-del'));
          //  Поле заметки в покое без рамки — оно должно выглядеть подписью.
          var nt = ed ? ed.querySelector('input.p2ed-note') : null;
          out.noteQuiet = nt ? (getComputedStyle(nt).borderTopColor === 'rgba(0, 0, 0, 0)'
                                || getComputedStyle(nt).borderTopStyle === 'none') : null;
          res(dump(out));
        }, 1100);
      }, 1100);
    }, 1200);
  }, 1900);
});
"""
_PARTS = {"parts": [
    {"part_id": "pp1", "part_name": "Корпус", "required_qty": 12, "printed_qty": 7,
     "status": "printing", "notes": "", "rework_qty": 0, "rework_done": 0,
     "live_printers": [], "plates": [], "order_idx": 0},
    {"part_id": "pp2", "part_name": "Крышка", "required_qty": 4, "printed_qty": 4,
     "status": "done", "notes": "", "rework_qty": 0, "rework_done": 0,
     "live_printers": [], "plates": [], "order_idx": 1}]}
_TREE = {"project": {"id": "pr1", "name": "Дрон FPV-7"}, "nodes": [
    {"id": "f1", "name": "korpus.gcode.3mf", "type": "file", "is_printable": True,
     "target_model": "Bambu Lab X1 Carbon",
     "children": [{"id": "c1", "name": "Корпус", "qty": 1}]}]}
if stage.engine_ready():
    stage.set_api({
        "/api/printers": [], 
        "/api/projects2": [{"id": "pr1", "name": "Дрон FPV-7", "parts_count": 2,
                            "done_count": 1, "printing_count": 1, "files_count": 1,
                            "required_total": 16, "printed_total": 11, "rework_pending": 0,
                            "needs_rework": False, "part_thumbs": [], "due_date": "",
                            "created_at": "2026-08-01"}],
        "/api/projects2/pr1/partsview": _PARTS,
        "/api/projects2/pr1/tree": _TREE,
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R19 = stage.run(JS_P2, window_size=(1700, 950), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R19:
        check("144. правка проекта проверена", False, str(stage.last_diag())[:200])
    else:
        #  Суть жалобы: при входе в правку всё съезжало. Меряем сами колонки.
        check("144. колонки строк совпадают в обоих режимах (до 1 точки)",
              bool(R19.get("viewCols")) and R19.get("viewCols") == R19.get("editCols"),
              (R19.get("viewCols"), R19.get("editCols")))
        check("145. подписи шапки стоят на тех же местах в обоих режимах",
              bool(R19.get("viewHead")) and R19.get("viewHead") == R19.get("editHead"),
              (R19.get("viewHead"), R19.get("editHead")))
        check("146. органы правки на месте: заметка, количества, удаление",
              R19.get("hasFields") is True, R19.get("hasFields"))
        check("147. поле заметки в покое выглядит подписью, а не коробкой",
              R19.get("noteQuiet") is True, R19.get("noteQuiet"))
        _dP = R19.get("__diag") or {}
        check("148. консоль чистая при входе в правку",
              not (_dP.get("consoleErrors") or _dP.get("pageErrors") or _dP.get("unhandled")),
              json.dumps(_dP, ensure_ascii=False)[:200])

#  ── 2.951: строка задачи 3.0 по выбранному концепту (С3 + цвет рельсы по статусу из С5) ───────
#  Жалоба владельца: кнопка некрасивая, элементы налезают, строка растёт по вертикали.
#  Проверяем ИСПОЛНЕНИЕМ на плотных данных: проект с синхронизацией, заметка, предупреждение,
#  прогресс, печать на принтере, файл без нарезки — на узком (1280) и широком (1920) экране.
JS_ROW = r"""
return new Promise(function(res){
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function R(el){ var b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var t = qa('.ui3-rtabs button'); if (t[1]) t[1].click();
      setTimeout(function(){
        var out = {rows: []};
        var z = parseFloat(getComputedStyle(document.querySelector('.zoom-wrap') || document.body).zoom) || 1;
        var bz = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
        out.k = z * bz;
        qa('.pvrow.qtpvrow.pvpart').forEach(function(r){
          var rr = R(r), o = {};
          o.h = rr[3] / out.k;
          var rail = r.querySelector('.ui3-qtrail'); o.railH = rail ? R(rail)[3] / out.k : null;
          o.railW = rail ? R(rail)[2] / out.k : null;
          //  2.957 (Д3): синхронизация — полоса у ПРАВОГО края строки, зеркальная рельсе.
          var syncC = r.querySelector('.ui3-qtsync');
          o.syncLast = syncC ? (syncC === r.children[r.children.length - 1]) : null;
          o.syncRightGap = syncC ? Math.round((rr[0] + rr[2] - (R(syncC)[0] + R(syncC)[2])) / out.k) : null;
          var sb = syncC ? syncC.querySelector('.qtsync') : null;
          o.syncW = sb ? Math.round(R(sb)[2] / out.k) : null;
          o.syncH = sb ? Math.round(R(sb)[3] / out.k) : null;
          o.syncOn = sb ? /(^|\s)on(\s|$)/.test(sb.className) : null;
          o.railCls = rail ? rail.className : '';
          var nm = r.querySelector('.pvc.pvname'); o.nameW = nm ? R(nm)[2] / out.k : 0;   // ширина КОЛОНКИ имени
          var meta = r.querySelector('.ui3-qtmeta'); var mr = meta ? R(meta) : null;
          //  Чип либо целиком внутри блока и строки (виден), либо целиком ниже строки (спрятан переносом).
          o.chips = meta ? [].slice.call(meta.children).map(function(c){ var b = R(c);
            var shown = b[1] < rr[1] + rr[3];
            if (b[2] < 1) return { cls: c.className.split(' ')[0], shown: false, ok: true };   // распорка нулевой ширины
            return { cls: c.className.split(' ')[0], shown: shown, ok: !shown || (b[0] >= mr[0] - 0.6 && b[0] + b[2] <= mr[0] + mr[2] + 0.6 && b[1] >= rr[1] - 0.6 && b[1] + b[3] <= rr[1] + rr[3] + 0.6) }; }) : [];
          o.top = rr[1] / out.k; o.bot = (rr[1] + rr[3]) / out.k;
          var nm2 = r.querySelector('.pvpname'), nt2 = r.querySelector('.ui3-qtnoteline');
          o.nameNoteGap = (nm2 && nt2) ? Math.round((R(nt2)[1] - (R(nm2)[1] + R(nm2)[3])) / out.k) : null;
          //  Скрытые ячейки (display:none) в счёт не идут: у них нулевая коробка в начале координат.
          var cs = [].slice.call(r.children).map(R).filter(function(b){ return b[2] > 0.5; }); var ov = 0;
          for (var i = 1; i < cs.length; i++) if (cs[i][0] < cs[i-1][0] + cs[i-1][2] - 1) ov++;
          o.overlaps = ov;
          o.tall = [].slice.call(r.querySelectorAll('*')).filter(function(e){ return e.getBoundingClientRect().height > rr[3] + 1; }).length;
          var bd = r.querySelector('.status-badge'); o.badge = bd ? bd.textContent.trim() : '';
          o.badgeN = bd && bd.querySelector('.sb-n') ? bd.querySelector('.sb-n').textContent.trim() : '';
          var pg = r.querySelector('.qtprog'); o.progBottom = pg ? Math.round((R(pg)[1] + R(pg)[3]) - (rr[1] + rr[3])) : null;
          o.pairInputs = r.querySelectorAll('.ui3-qtpair input').length;
          var last = r.children[r.children.length - 1];
          o.lastIn = R(last)[0] + R(last)[2] <= rr[0] + rr[2] + 0.6;
          var bdE = r.querySelector('.status-badge');
          o.badgeIn = bdE ? (R(bdE)[0] + R(bdE)[2] <= rr[0] + rr[2] + 0.6 && R(bdE)[0] >= rr[0] - 0.6) : null;
          var pair = r.querySelector('.ui3-qtpair'); var pc = pair ? pair.parentElement : null;
          o.qtyClip = [].slice.call(r.querySelectorAll('.ui3-qtpair input')).filter(function(i){ return i.scrollWidth > i.clientWidth + 0.5; }).length;
          o.pairIn = pair ? (R(pair)[0] >= R(pc)[0] - 0.6 && R(pair)[0] + R(pair)[2] <= R(pc)[0] + R(pc)[2] + 0.6) : null;
          o.qtyVals = [].slice.call(r.querySelectorAll('.ui3-qtpair input')).map(function(i){ return i.value; });
          out.rows.push(o);
        });
        out.headCells = (document.querySelector('.pvrow.qtpvrow.pvhead') || {children: []}).children.length;
        //  2.953: столбцы по одной вертикали — левые края ячеек значков, чисел и статуса одинаковы во всех строках.
        var cols = {};
        ['.ui3-qtmeta', '.ui3-qtpair', '.status-badge'].forEach(function(sel){
          cols[sel] = qa('.pvrow.qtpvrow.pvpart ' + sel).map(function(e){ return Math.round(R(e.closest('.pvc') || e)[0]); }); });
        out.colsAligned = Object.keys(cols).every(function(k){ return cols[k].length && cols[k].every(function(x){ return Math.abs(x - cols[k][0]) <= 1; }); });
        out.cols = cols;
        //  2.954: подписи «Итог» и «План» стоят над центрами своих полей, «из» — над «из».
        var hd = qa('.pvrow.qtpvrow.pvhead .ui3-qtpair-h > *'), pq = qa('.pvrow.qtpvrow.pvpart')[0].querySelectorAll('.ui3-qtpair > *');
        var cx = function(e){ var b = R(e); return b[0] + b[2] / 2; };
        out.hdOff = (hd.length === 3 && pq.length === 3) ? [0, 1, 2].map(function(i){ return Math.round(cx(hd[i]) - cx(pq[i])); }) : null;
        var inp = qa('.pvrow.qtpvrow.pvpart')[0].querySelector('.ui3-qtpair input'); out.inH = inp ? Math.round(R(inp)[3] / out.k) : null; out.inW = inp ? Math.round(R(inp)[2] / out.k) : null;
        //  Заметка: видна текстом под именем; клик — поле на том же месте; Esc возвращает текст.
        var rows0 = qa('.pvrow.qtpvrow.pvpart');
        var sp = rows0[0].querySelector('span.ui3-qtnote'); var spR = sp ? R(sp) : null;
        out.noteText = sp ? sp.textContent.trim() : '';
        out.noteInRow = sp ? (spR[1] >= R(rows0[0])[1] && spR[1] + spR[3] <= R(rows0[0])[1] + R(rows0[0])[3] + 0.6) : false;
        var nm = rows0[0].querySelector('.pvpname'); out.noteBelowName = (sp && nm) ? (spR[1] >= R(nm)[1] + R(nm)[3] - 0.6) : false;
        var ph = rows0[2].querySelector('span.ui3-qtnote'); out.phQuiet = ph ? getComputedStyle(ph).opacity === '0' : null;
        if (sp) sp.click();
        setTimeout(function(){
          var inp = rows0[0].querySelector('input.ui3-qtnote');
          var ir = inp ? R(inp) : null;
          out.edit = inp ? { val: inp.value, focused: document.activeElement === inp, samePlace: Math.abs(ir[1] - spR[1]) <= 1 && Math.abs(ir[0] - spR[0]) <= 1,
                             h: rows0[0].getBoundingClientRect().height / out.k } : null;
          if (inp) { inp.value = 'испорчено'; inp.dispatchEvent(new Event('input', {bubbles: true})); inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); }
          setTimeout(function(){
            var sp2 = rows0[0].querySelector('span.ui3-qtnote');
            out.afterEsc = sp2 ? sp2.textContent.trim() : null;
            var w = document.documentElement; out.hscroll = w.scrollWidth - w.clientWidth;
            res(dump(out));
          }, 250);
        }, 400);
      }, 1100);
    }, 1000);
  }, 1900);
});
"""
_ROW_ST = [
    {"filename": "Корпус_редуктора_v3_PETG_0.4n_0.2mm_3h12m_очень_длинное_имя_файла.gcode.3mf", "status": "printing",
     "printer_id": "", "required_qty": 12, "printed_qty": 5, "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon",
     "is_printable": True, "notes": "Печатать только на чёрном PETG", "src_path": "", "linked": False, "missing": False,
     "project_id": "PRJ1", "project_name": "Заказ 17", "project_sync": True, "compatible_pids": ["b0"],
     "parts": [{"name": "Корпус", "count": 4}], "part_total": 4},
    {"filename": "Крышка_ABS.gcode.3mf", "status": "done", "printer_id": "", "required_qty": 3, "printed_qty": 3,
     "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon", "is_printable": True, "notes": "", "src_path": "",
     "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
     "compatible_pids": ["b0"], "parts": [{"name": "Крышка", "count": 4}], "part_total": 4},
    {"filename": "Модель_без_нарезки.stl", "status": "ready", "printer_id": "", "required_qty": 1, "printed_qty": 0,
     "target_nozzles": 0.4, "target_model": "", "is_printable": False, "notes": "", "src_path": "", "linked": False,
     "missing": False, "project_id": "", "project_name": "", "project_sync": False, "compatible_pids": [], "parts": [], "part_total": 0},
    {"filename": "Кронштейн_K2.gcode", "status": "ready", "printer_id": "", "required_qty": 8, "printed_qty": 0,
     "target_nozzles": 0.4, "target_model": "Creality K2 Plus", "is_printable": True, "notes": "срочно", "src_path": "",
     "linked": False, "missing": True, "project_id": "", "project_name": "", "project_sync": False,
     "compatible_pids": ["b0"], "parts": [{"name": "Кронштейн", "count": 4}], "part_total": 4},
    #  2.952: девять знаков в обоих полях — снимок владельца, цифры не помещались.
    {"filename": "Миллионы.gcode.3mf", "status": "ready", "printer_id": "", "required_qty": 987654321, "printed_qty": 123456789,
     "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon", "is_printable": True, "notes": "", "src_path": "",
     "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
     "compatible_pids": ["b0"], "parts": [], "part_total": 0}]
_ROW_PB = [{"id": "b0", "name": "X1 Carbon #1", "type": "bambu", "model": "Bambu Lab X1 Carbon", "ip": "10.0.0.40",
            "port": 8883, "serial": "FIXTURE_B0", "access_code": ""}]
if stage.engine_ready():
    stage.set_api({"/api/printers": _ROW_PB, "/api/staging": _ROW_ST,
                   "/api/projects2": [{"id": "PRJ1", "name": "Заказ 17", "due_date": "", "is_archived": 0,
                                       "created_at": "2026-09-01", "required_total": 12, "printed_total": 5,
                                       "parts_count": 1, "files_count": 1}],
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"b0": {"status": "RUNNING", "file_name": "Корпус_редуктора_v3_PETG_0.4n_0.2mm_3h12m_очень_длинное_имя_файла",
                           "nozzle_temp": 230, "bed_temp": 70, "percent": 42, "remaining_time": 3600, "nozzle_count": 1}})
    _n = 154
    for _w in (1280, 1920):
        R21 = stage.run(JS_ROW, window_size=(_w, 900), settle_ms=2600, path="/ui3",
                        extra_args=("--force-device-scale-factor=1.0",))
        _tag = " на %d" % _w
        if not R21:
            check("%d. строка задачи 3.0 проверена%s" % (_n, _tag), False, str(stage.last_diag())[:200]); _n += 8; continue
        _rows = R21.get("rows") or []
        check("%d. пять задач, у всех высота строки 50 px — заметка, предупреждение и прогресс её не растят%s" % (_n, _tag),
              len(_rows) == 5 and all(abs(r["h"] - 50) <= 1.5 for r in _rows), [round(r["h"], 1) for r in _rows])
        _gaps = [round(_rows[i + 1]["top"] - _rows[i]["bot"]) for i in range(len(_rows) - 1)]
        check("%d. между именем и заметкой 5 px, между строками 8 px%s" % (_n, _tag),
              all(r["nameNoteGap"] == 5 for r in _rows) and all(abs(g - 8) <= 1 for g in _gaps),
              ([r["nameNoteGap"] for r in _rows], _gaps))
        check("%d. рельса-кнопка 52 px во всю высоту строки, цвет по статусу: run / done / wait%s" % (_n + 1, _tag),
              all(r["railH"] is not None and abs(r["railH"] - r["h"]) <= 2.5 and abs((r["railW"] or 0) - 52) <= 1 for r in _rows)
              and "st-run" in _rows[0]["railCls"] and "st-done" in _rows[1]["railCls"]
              and "st-wait" in _rows[2]["railCls"] and "slicer" in _rows[2]["railCls"],
              [(r["railH"], r["railCls"]) for r in _rows])
        check("%d. ячейки не налезают друг на друга, ничего не выше строки, бейдж статуса целиком внутри%s" % (_n + 2, _tag),
              all(r["overlaps"] == 0 and r["tall"] == 0 and r["lastIn"] and r["badgeIn"] for r in _rows),
              [(r["overlaps"], r["tall"], r["lastIn"], r["badgeIn"]) for r in _rows])
        check("%d. значки после имени видны целиком или не видны вовсе, имя не уже 96 px%s" % (_n + 3, _tag),
              all(all(c["ok"] for c in r["chips"]) for r in _rows)
              and all(r["nameW"] >= 95 for r in _rows),
              [(round(r["nameW"]), [c for c in r["chips"] if not c["ok"]]) for r in _rows])
        check("%d. число печатающихся — внутри бейджа статуса, колонки «В печати» нет (6 ячеек в шапке)%s" % (_n + 4, _tag),
              _rows[0]["badgeN"] == "1" and _rows[1]["badgeN"] == "" and R21.get("headCells") == 7,
              (_rows[0]["badge"], _rows[0]["badgeN"], R21.get("headCells")))
        #  2.974 (заказ владельца): линия выполнения плана из строки убрана — в оформлении 3.0
        #  её нет ни в задачах, ни в проектах. Числа «Итог из План» остались на месте.
        check("%d. «Итог из План» — два поля в одной ячейке, линии прогресса нет; девять знаков видны целиком%s" % (_n + 5, _tag),
              all(r["pairInputs"] == 2 for r in _rows) and all(r["progBottom"] is None for r in _rows)
              and all(r["qtyClip"] == 0 and r["pairIn"] is True for r in _rows) and _rows[4]["qtyVals"] == ["123456789", "987654321"],
              [(r["pairInputs"], r["progBottom"], r["qtyClip"], r["pairIn"], r["qtyVals"]) for r in _rows])
        _e = R21.get("edit") or {}
        check("%d. заметка видна строкой под именем, пустая — тихая; клик даёт поле на том же месте, Esc возвращает текст%s" % (_n + 6, _tag),
              R21.get("noteText", "").startswith("Печатать") and R21.get("noteInRow") is True and R21.get("noteBelowName") is True
              and R21.get("phQuiet") is True and _e.get("focused") is True and _e.get("samePlace") is True
              and abs((_e.get("h") or 0) - 50) <= 1.5 and R21.get("afterEsc", "").startswith("Печатать"),
              (R21.get("noteText"), R21.get("noteInRow"), R21.get("noteBelowName"), R21.get("phQuiet"), _e, R21.get("afterEsc")))
        check("%d. столбцы значков, чисел и статуса стоят по одной вертикали во всех строках%s" % (_n + 8, _tag),
              R21.get("colsAligned") is True, R21.get("cols"))
        check("%d. синхронизация — полоса 52 px во всю высоту у правого края; у задачи без проекта её нет%s" % (_n + 10, _tag),
              all(r["syncLast"] is True and (r["syncRightGap"] or 0) <= 1 for r in _rows)   # 1 px — рамка строки
              and _rows[0]["syncW"] == 52 and abs((_rows[0]["syncH"] or 0) - _rows[0]["h"]) <= 2.5
              and _rows[0]["syncOn"] is True and _rows[2]["syncW"] is None,
              [(r["syncLast"], r["syncRightGap"], r["syncW"], r["syncH"], r["syncOn"]) for r in _rows])
        _wantW = 46 if _w <= 1300 else 56
        check("%d. «Итог», «из», «План» в шапке — над центрами своих столбцов (до 2 px); поле %d × 22%s" % (_n + 9, _wantW, _tag),
              R21.get("hdOff") is not None and all(abs(x) <= 2 for x in R21["hdOff"]) and R21.get("inH") == 22
              and R21.get("inW") == _wantW,
              (R21.get("hdOff"), R21.get("inW"), R21.get("inH")))
        _dR = R21.get("__diag") or {}
        check("%d. консоль чистая, горизонтальной прокрутки нет%s" % (_n + 7, _tag),
              not (_dR.get("consoleErrors") or _dR.get("pageErrors") or _dR.get("unhandled")) and (R21.get("hscroll") or 0) <= 1,
              (json.dumps(_dR, ensure_ascii=False)[:160], R21.get("hscroll")))
        _n += 11
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()

#  ── 2.950: вкладка «Задачи» при раскрытом проекте ─────────────────────────────────────
#  Жалоба владельца (05.09.2026): в 3.0 открыл проект, переключился на «Задачи» — пусто,
#  задачи появлялись только после щелчка по пустому месту (он сворачивал проект). Причина:
#  раздел задач стоял под правилом 2.0 «раскрытый проект прячет задачи», а в 3.0 вкладки
#  разделены классами html.ui3-right-*. Проверяем ИСПОЛНЕНИЕМ весь порядок переключений.
check("149. раздел задач в 3.0 не зависит от раскрытого проекта (условие в шаблоне)",
      'v-if="!project2Expanded || ui3Mode" data-tour="qtsection"' in IDX)
JS_TT = r"""
return new Promise(function(res){
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.getBoundingClientRect().width > 0; }
  function tab(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; }
  function rows(){ return qa('.pvrow.qtpvrow.pvpart').filter(vis).length; }
  function expanded(){ return vis(document.querySelector('.ui3-proj.glass-panel')); }
  var out = {};
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      try { tab(/Проекты/).click(); } catch (e) {}
      setTimeout(function(){
        try { document.querySelector('[data-help="project-card"]').click(); } catch (e) { out.err = String(e); }
        setTimeout(function(){
          out.expanded = expanded(); out.tasksOnProjects = rows();
          try { tab(/Задачи/).click(); } catch (e) {}
          setTimeout(function(){
            out.tasksOnTasks = rows(); out.projectOnTasks = expanded();
            try { tab(/Проекты/).click(); } catch (e) {}
            setTimeout(function(){
              out.expandedBack = expanded(); out.tasksBack = rows();
              res(dump(out));
            }, 600);
          }, 900);
        }, 1200);
      }, 900);
    }, 1200);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({
        "/api/printers": [],
        "/api/staging": [{"filename": "kub.gcode.3mf", "status": "ready", "printer_id": "",
                          "required_qty": 2, "printed_qty": 0, "target_nozzles": 0.4,
                          "target_model": "", "is_printable": True, "notes": "", "src_path": "",
                          "linked": False, "missing": False, "project_id": "", "project_name": "",
                          "project_sync": False, "compatible_pids": [],
                          "parts": [{"name": "Cube", "count": 2}], "part_total": 2}],
        "/api/projects2": [{"id": "pr1", "name": "Дрон FPV-7", "parts_count": 2,
                            "done_count": 1, "printing_count": 1, "files_count": 1,
                            "required_total": 16, "printed_total": 11, "rework_pending": 0,
                            "needs_rework": False, "part_thumbs": [], "due_date": "",
                            "created_at": "2026-08-01"}],
        "/api/projects2/pr1/partsview": _PARTS,
        "/api/projects2/pr1/tree": _TREE,
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R20 = stage.run(JS_TT, window_size=(1600, 1000), settle_ms=2600, path="/ui3")
    stage.set_api(None)
    stage.stop()
    if not R20:
        check("150. вкладка «Задачи» при раскрытом проекте проверена", False, str(stage.last_diag())[:200])
    else:
        check("150. проект раскрыт, на вкладке «Проекты» задач нет",
              R20.get("expanded") is True and R20.get("tasksOnProjects") == 0,
              (R20.get("expanded"), R20.get("tasksOnProjects"), R20.get("err")))
        check("151. переключились на «Задачи» — задачи видны, проект не торчит среди них",
              R20.get("tasksOnTasks") == 1 and R20.get("projectOnTasks") is False,
              (R20.get("tasksOnTasks"), R20.get("projectOnTasks")))
        check("152. вернулись в «Проекты» — проект по-прежнему раскрыт, задачи спрятаны",
              R20.get("expandedBack") is True and R20.get("tasksBack") == 0,
              (R20.get("expandedBack"), R20.get("tasksBack")))
        _dT = R20.get("__diag") or {}
        check("153. консоль чистая на всём пути переключений",
              not (_dT.get("consoleErrors") or _dT.get("pageErrors") or _dT.get("unhandled")),
              json.dumps(_dT, ensure_ascii=False)[:200])

# ══════════════════════════════════════════════════════════════════════════════════════════
#  2.1004 — ДЕФЕКТЫ СО СНИМКОВ ВЛАДЕЛЬЦА 11.09.2026 (вид «дашборд», окно не во весь экран)
#  1. В раскрытой ячейке надпись «Отправить файл с компьютера» вылезала за кнопку на соседнюю.
#     Корень: колонка с камерой всегда забирала свой максимум, колонке управления оставалось
#     214 точек. Числа температур при этом схлопывались в ноль.
#  2. Форма добавления принтера объявлена во всю ширину колонки, а в «дашборде» колонка — весь
#     экран: поля растягивались на два метра, и у формы не было предела по высоте
#     (класс max-h-[80vh] в наборе Tailwind проекта отсутствует). С 2.1005 форма —
#     панель у левого края во всю высоту экрана; проверки 165/166 меряют это.
#  Проверяем замером на размере окна владельца.
JS_DASH = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = {};
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click();
    setUiLang('ru');
    setTimeout(function(){
      var sw = q('[data-tour="pview"]');
      (function toDash(n){
        if (q('.pc-dash-cols') || n > 6) {
          out.dash = !!q('.pc-dash-cols');
          var card = qa('.printer-card')[0];
          if (card) card.click();
          setTimeout(function(){
            var pp = q('.ui3-pp');
            out.panel = !!pp;
            if (pp) {
              var pr = pp.getBoundingClientRect();
              out.ctlW = (function(e){ return e ? Math.round(e.getBoundingClientRect().width) : 0; })(q('.ui3-pp-ctl'));
              out.btnOver = qa('.ui3-pp-btn').filter(function(e){ return e.scrollWidth > e.clientWidth + 1; }).length;
              out.tempOver = qa('.ui3-pp-temp .cur, .ui3-pp-temp .lb').filter(function(e){
                return e.scrollWidth > e.clientWidth + 1; }).length;
              out.outOfPanel = qa('.ui3-pp *').filter(function(e){
                var b = e.getBoundingClientRect();
                return b.width > 0 && (b.right > pr.right + 1 || b.left < pr.left - 1); }).length;
              var ov = 0;
              qa('.ui3-pp-row').forEach(function(row){
                var bs = [].slice.call(row.querySelectorAll('.ui3-pp-btn'));
                for (var i = 0; i + 1 < bs.length; i++) {
                  var a = bs[i].getBoundingClientRect(), b = bs[i+1].getBoundingClientRect();
                  if (Math.abs(a.top - b.top) < 4 && a.right > b.left + 1) ov++;
                }
              });
              out.btnOverlap = ov;
            }
            var x = q('.ui3-pp-head button');
            if (x) x.click();
            setTimeout(function(){
              var add = q('[data-tour="add-printer"]');
              if (add) add.click();
              setTimeout(function(){
                //  2.1005: форма — панель у ЛЕВОГО края во всю высоту экрана (заказ владельца 12.09.2026).
                var form = q('.fm-addp-sheet');
                var pane = q('.printers-pane');
                out.formClass = !!form;
                if (form && pane) {
                  var fr = form.getBoundingClientRect(), pn = pane.getBoundingClientRect();
                  out.formW = Math.round(fr.width);
                  out.paneW = Math.round(pn.width);
                  out.formLeft = Math.round(fr.left);
                  out.formTop = Math.round(fr.top);
                  out.formBottomGap = Math.round(window.innerHeight - fr.bottom);
                  var foot = q('.fm-addp-foot'), pri = q('.fm-addp-pri');
                  out.footVisible = !!foot && Math.round(foot.getBoundingClientRect().bottom) <= Math.round(fr.bottom) + 1;
                  out.priVisible = !!pri && pri.getBoundingClientRect().bottom <= window.innerHeight + 1;
                  out.formOver = [].slice.call(form.querySelectorAll('*')).filter(function(e){
                    var b = e.getBoundingClientRect();
                    return b.width > 0 && (b.right > fr.right + 1 || b.left < fr.left - 1); }).length;
                }
                res(dump(out));
              }, 1100);
            }, 700);
          }, 1400);
          return;
        }
        if (sw) sw.click();
        setTimeout(function(){ toDash(n + 1); }, 700);
      })(0);
    }, 1200);
  }, 1900);
});
"""
if stage.engine_ready():
    stage.set_api({"/api/printers": [
        {"id": "d1", "name": "Виртуальный 1", "type": "virtual", "model": "Виртуальный принтер",
         "ip": "127.0.0.1", "port": 0},
        {"id": "d2", "name": "Виртуальный 3", "type": "virtual", "model": "Виртуальный принтер",
         "ip": "127.0.0.1", "port": 0}],
        "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
        "/api/printer/files": {"ok": True, "files": []}})
    #  Размер окна — тот самый, на котором владелец снял оба экрана.
    R21 = stage.run(JS_DASH, window_size=(1715, 1312), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R21:
        check("161. вид «дашборд» проверен браузером", False, str(stage.last_diag())[:200])
    else:
        check("161. раскрытая ячейка открылась в виде «дашборд»",
              R21.get("dash") is True and R21.get("panel") is True,
              (R21.get("dash"), R21.get("panel")))
        check("162. колонке управления оставлено не меньше 300 точек (было 214 — всё ужималось)",
              (R21.get("ctlW") or 0) >= 340, R21.get("ctlW"))
        check("163. НАДПИСИ НЕ ВЫЛЕЗАЮТ за кнопки и кнопки не налезают друг на друга",
              R21.get("btnOver") == 0 and R21.get("btnOverlap") == 0,
              (R21.get("btnOver"), R21.get("btnOverlap")))
        check("164. числа температур не обрезаны, ничего не вылезает за панель",
              R21.get("tempOver") == 0 and R21.get("outOfPanel") == 0,
              (R21.get("tempOver"), R21.get("outOfPanel")))
        #  2.1005: форма — панель у левого края во всю высоту, а не карточка по центру колонки.
        check("165. форма добавления — панель ПОСТОЯННОЙ ширины у ЛЕВОГО края, а не во всю колонку",
              R21.get("formClass") is True and (R21.get("formW") or 9999) <= 600
              and isinstance(R21.get("formLeft"), int) and abs(R21["formLeft"]) <= 1
              and (R21.get("paneW") or 0) > 1000,
              (R21.get("formW"), R21.get("formLeft"), R21.get("paneW")))
        check("166. панель занимает экран СВЕРХУ ДОНИЗУ, кнопки внизу видны, ничего не вылезает",
              isinstance(R21.get("formTop"), int) and abs(R21["formTop"]) <= 1
              and isinstance(R21.get("formBottomGap"), int) and abs(R21["formBottomGap"]) <= 1
              and R21.get("footVisible") is True and R21.get("priVisible") is True
              and R21.get("formOver") == 0,
              (R21.get("formTop"), R21.get("formBottomGap"), R21.get("footVisible"), R21.get("priVisible"),
               R21.get("formOver")))
        _dD = R21.get("__diag") or {}
        check("167. консоль чистая на этом пути",
              not (_dD.get("consoleErrors") or _dD.get("pageErrors") or _dD.get("unhandled")),
              json.dumps(_dD, ensure_ascii=False)[:200])


print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
