# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 3.0 (29.09.2026, R-111) — пульт принтера в интерфейсе 3.0 прокручивается сам.

ЗАЧЕМ. На окнах уже 1600 точек пульт встаёт в одну колонку (камера сверху) и становится выше
правой половины. На вкладках «Проекты» и «Задачи» половина — колонка без своей прокрутки,
поэтому низ пульта («Служебное», задание) обрезался, а колесо мыши ничего не делало. Замер
до правки на 1280×800: половина 574 точки, пульт 1406, прокрутки нет ни у кого.

ЛОВУШКА, из-за которой набор смотрит на overflowY, а не только на scrollTop: программная
прокрутка (scrollTop) срабатывает и у элемента с overflow:hidden — на ней дефект не виден.
Пользователь же крутит колесом и тянет полосу, а их у overflow:hidden нет.

Что проверяется исполнением (стенд, синтетический печатающий Bambu с AMS):
  * окна 1280×800, 1600×900, 1920×1080, 2560×1440 при «Размере текста» 100 и 130 %;
  * вкладки правой половины «Проекты», «Задачи», «Очередь» на узких окнах;
  * низ пульта не ниже низа половины; на узких окнах у пульта своя прокрутка и она нужна;
  * прокрутка до конца показывает «Служебное» и задание целиком; шапка пульта на месте;
  * окно камеры при прокрутке обрезается по видимой части: не ложится на шапку пульта и
    шапку программы, не перехватывает нажатия в шапке;
  * на широких окнах — две колонки, пульт своей высоты, прокрутки нет;
  * открытый список файлов при прокрутке уходит под шапку пульта, а не ложится на неё;
  * при открытой форме «Добавить принтер» шапка пульта уходит под затемнение вместе с пультом,
    её крестик сквозь затемнение не нажимается (с подменой isolation:auto набор это видит);
  * нет горизонтальной прокрутки, консоль чистая;
  * интерфейс 2.0 не задет: раскрытая ячейка по-прежнему прокручивается;
  * 08.10.2026 (обход фермы, снимок владельца с экрана 1366×768): колонки выбираются по ширине
    самого пульта — от 594 точек две колонки (управление видно сразу, камера 16:9 вверху своей
    колонки), уже — одна колонка, но камера не выше, чем оставляет место управлению; без этого
    правила (подмена container-type) на окне владельца управление начинается ниже края пульта;
  * 16.10.2026 (второй снимок обхода — вид «Дашборд»): на окне 1366×705 при тексте 100 и 130 %
    пульт в две колонки и управление сразу под шапкой; с прежней колонкой принтеров 46 % (подмена
    правила) — одна колонка и управление ниже края; окна ноутбуков 1536×864 (125 %) — две колонки,
    1280×720 (150 %) — договорённость узких окон;
  * НЕПУСТОТА: тот же сценарий с подменой правил (пульт без своей прокрутки, как до правки)
    обязан показать дефект — иначе набор ничего не ловит.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_printer_panel_scroll_ui3.py
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

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "ui3", "ui3.css"), encoding="utf-8").read()
CSS_NC = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)

print("--- 1. устройство закреплено в файлах ---")
check("1. при открытом пульте половина — колонка без своей прокрутки, на всех вкладках",
      re.search(r"html\.ui3-mode \.projects-pane:has\(> section\.ui3-pp\) \{\s*display: flex; flex-direction: column; "
                r"overflow: hidden !important;", CSS_NC) is not None)
check("2. прокручивается сам пульт: сжимается (min-height 0), не растягивается, своя прокрутка",
      re.search(r"html\.ui3-mode \.projects-pane > section\.ui3-pp \{\s*flex: 0 1 auto; min-height: 0; overflow-y: auto;",
                CSS_NC) is not None)
_hz = re.search(r"html\.ui3-mode \.ui3-pp > \.ui3-pp-head \{\s*position: sticky; top: 0; z-index: (\d+);", CSS_NC)
_mz = re.search(r"html\.ui3-mode \.ui3-pp-menu \{[^}]*z-index: (\d+);", CSS_NC)
check("3. шапка пульта закреплена сверху и лежит выше выпадающих списков пульта",
      bool(_hz and _mz) and int(_hz.group(1)) > int(_mz.group(1)), (_hz and _hz.group(1), _mz and _mz.group(1)))
check("4. окно камеры обрезается по видимой части пульта",
      "clip-path: inset(var(--u3-cam-clip-t, 0px) 0 var(--u3-cam-clip-b, 0px) 0);" in CSS_NC
      and "const _ui3SetCamClip = (d, slot, r, k) => {" in APPJS
      and "_ui3SetCamClip(d, slot, r, f.k);" in APPJS and "_ui3SetCamClip(d, slot, r, k);" in APPJS)
check("5. предел высоты пульта не от vh (html{zoom} ломает vh)",
      not re.search(r"\.ui3-pp[^{]*\{[^}]*\d+vh", CSS_NC))
check("5a. пульт — свой контекст наложения: z-index шапки не выходит за пульт (затемнение формы принтера)",
      re.search(r"html\.ui3-mode \.projects-pane > section\.ui3-pp \{[^}]*isolation: isolate;", CSS_NC) is not None)

# ---------------------------------------------------------------------------------------------
JS3 = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function R(el){ if(!el) return null; var b=el.getBoundingClientRect(); return [Math.round(b.top*10)/10, Math.round(b.bottom*10)/10, Math.round(b.height*10)/10, Math.round(b.left*10)/10, Math.round(b.right*10)/10]; }
  var MUT = %(mut)s, MUT2 = %(mut2)s, MUT3 = %(mut3)s;
  //  16.10.2026 (R-111): подмена правила вида «Дашборд» — колонка принтеров снова 46 %%, как до правки.
  if (MUT3) { var st4=document.createElement('style'); st4.textContent='html.ui3-mode.ui3-dash-pp .left-col{width:46%%!important;flex:0 0 46%%!important;min-width:400px!important}'; document.head.appendChild(st4); }
  if (MUT) { var st=document.createElement('style'); st.textContent='html.ui3-mode section.ui3-pp{overflow:visible!important;flex:none!important}'; document.head.appendChild(st); }
  if (MUT2) { var st3=document.createElement('style'); st3.textContent='html.ui3-mode .projects-pane > section.ui3-pp{container-type:normal!important}'; document.head.appendChild(st3); }
  function camInfo(){
    var ov = q('#fm-overlay-root > .fm-cam-ov'); if (!ov) return null;
    var b = ov.getBoundingClientRect(); var cs = getComputedStyle(ov);
    var w = parseFloat(cs.width) || 0; var k = w ? b.width / w : 1;
    var m = String(cs.clipPath || '').match(/inset\(([-\d.]+)px(?:\s+([-\d.]+)px)?(?:\s+([-\d.]+)px)?/);
    var ct = m ? parseFloat(m[1]) : 0, cb = m ? parseFloat(m[3] != null ? m[3] : m[1]) : 0;
    return {top: b.top, bottom: b.bottom, visTop: b.top + ct*k, visBot: b.bottom - cb*k, clip: cs.clipPath, k: k,
            dock: document.documentElement.classList.contains('ui3-cam-dock')};
  }
  function headHits(){
    //  Точки вдоль нижнего ряда шапки пульта: каждая обязана попадать в саму шапку, а не в
    //  окно камеры (у его кнопок pointer-events включены).
    var h = q('.ui3-pp-head'); if (!h) return ['нет шапки'];
    var b = h.getBoundingClientRect(), bad = [];
    for (var i = 1; i < 10; i++) {
      var x = b.left + b.width * i / 10, y = b.bottom - 3;
      var e = document.elementFromPoint(x, y);
      if (!e || !e.closest('.ui3-pp-head')) bad.push(Math.round(x) + ':' + (e ? (e.className || e.tagName) : 'null'));
    }
    return bad;
  }
  var TS = %(ts)s, tsMode = 'none';
  function textSize(){
    //  «Размер текста» ставит сама программа (?ls=ui_text_size:N → стиль #ui-text-size). Если в
    //  этой версии программы такой настройки нет, набор подставляет то же правило сам — тем же
    //  способом, что и программа (font-size-adjust по замеренной высоте строчной буквы).
    if (TS === 100) return;
    var el = document.getElementById('ui-text-size');
    if (el && el.textContent) { tsMode = 'app'; return; }
    var s = document.createElement('span'); s.textContent = 'xxxxxxxxxx';
    s.style.cssText = 'position:absolute;left:-9999px;top:0;visibility:hidden;white-space:nowrap;font-size:100px;letter-spacing:0';
    (document.getElementById('app') || document.body).appendChild(s);
    s.style.setProperty('font-size-adjust', 'none', 'important'); var w0 = s.getBoundingClientRect().width;
    s.style.setProperty('font-size-adjust', '1', 'important'); var w1 = s.getBoundingClientRect().width;
    s.remove();
    var a = (w0 > 0 && w1 > 0) ? w0 / w1 : 0;
    if (a > 0.05 && a < 2) {
      var st2 = document.createElement('style'); st2.id = 'ui-text-size-test';
      st2.textContent = '*{font-size-adjust:' + (a * TS / 100).toFixed(4) + ' !important}';
      document.head.appendChild(st2); tsMode = 'test';
    }
  }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    textSize();
    setTimeout(function(){
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('X1C-01') >= 0; })[0];
      if (card) card.click();
      setTimeout(function(){
        var o = {inner: [innerWidth, innerHeight], tsMode: tsMode};
        var pane = q('.projects-pane'), pp = q('.ui3-pp');
        o.tab = document.documentElement.className.split(' ').filter(function(c){ return /ui3-right-/.test(c); });
        o.dashPp = document.documentElement.classList.contains('ui3-dash-pp');
        o.panel = !!pp;
        if (!pp) { res(dump(o)); return; }
        var body = q('.ui3-pp-body');
        o.cols = getComputedStyle(body).gridTemplateColumns.split(' ').length;
        o.pane = R(pane); o.pp = R(pp);
        o.ppOv = getComputedStyle(pp).overflowY; o.paneOv = getComputedStyle(pane).overflowY;
        o.ppSH = pp.scrollHeight; o.ppCH = pp.clientHeight;
        var kids = [].slice.call(pp.children).filter(function(e){ return e.getBoundingClientRect().height > 0; });
        o.contentH = kids.length ? Math.round((kids[kids.length-1].getBoundingClientRect().bottom - kids[0].getBoundingClientRect().top)*10)/10 : 0;
        o.hScroll = [document.documentElement.scrollWidth, document.documentElement.clientWidth, pp.scrollWidth, pp.clientWidth];
        o.cam0 = camInfo();
        o.ctl0 = R(q('.ui3-pp-ctl')); o.slot0 = R(q('.ui3-camslot')); o.head0 = R(q('.ui3-pp-head'));
        //  Колесо мыши: доходит ли до пульта прокрутка (у overflow:hidden её нет).
        o.canWheel = o.ppOv === 'auto' || o.ppOv === 'scroll';
        //  Промежуточная прокрутка: камера наполовину под шапкой пульта.
        var slot = q('.ui3-camslot'), head = q('.ui3-pp-head');
        var mid = slot ? Math.max(0, (slot.getBoundingClientRect().top - pp.getBoundingClientRect().top) + slot.getBoundingClientRect().height/2 - head.getBoundingClientRect().height) : 200;
        pp.scrollTop = Math.round(mid / 1.2);
        setTimeout(function(){
          o.midTop = pp.scrollTop;
          o.headMid = R(head); o.camMid = camInfo(); o.slotMid = R(q('.ui3-camslot'));
          o.hitsMid = headHits();
          o.hdr = R(q('header') || q('.top-bar') || q('.fm-topbar'));
          pp.scrollTop = 100000;
          setTimeout(function(){
            o.endTop = pp.scrollTop;
            o.ppEnd = R(pp); o.headEnd = R(head);
            o.tools = R(q('.ui3-pp [data-help="pp-tools"]')); o.job = R(q('.ui3-pp [data-help="pp-job"]'));
            o.camEnd = camInfo(); o.hitsEnd = headHits();
            o.pane2 = R(pane);
            //  Каждый раздел должен быть ДОСТИЖИМ прокруткой: в одну колонку задание стоит
            //  под камерой (сверху), «Служебное» — внизу. Подводим раздел под шапку пульта и
            //  смотрим, что он целиком в видимой части. Масштаб «точки экрана на единицу
            //  scrollTop» меряется сдвигом, а не угадывается (html{zoom}).
            o.reach = {};
            ['pp-job', 'pp-tools'].forEach(function(k){
              var e = q('.ui3-pp [data-help="' + k + '"]'); if (!e) { o.reach[k] = null; return; }
              pp.scrollTop = 0; var t0 = e.getBoundingClientRect().top;
              pp.scrollTop = 100; var s1 = pp.scrollTop, t1 = e.getBoundingClientRect().top;
              var kk = s1 ? (t0 - t1) / s1 : 1;
              var hb = head.getBoundingClientRect().bottom;
              pp.scrollTop = Math.max(0, (t0 - hb - 2) / (kk || 1));
              var eb = e.getBoundingClientRect(), pb = pp.getBoundingClientRect();
              o.reach[k] = {sec: [Math.round(eb.top*10)/10, Math.round(eb.bottom*10)/10], vis: [Math.round(head.getBoundingClientRect().bottom*10)/10, Math.round(pb.bottom*10)/10]};
            });
            res(dump(o));
          }, 600);
        }, 600);
      }, 1800);
    }, 900);
  }, 1900);
});
"""

#  Выпадающий список файлов внутри прокручиваемого пульта: при прокрутке он обязан уходить
#  ПОД закреплённую шапку, а не ложиться на неё (у списков z-index 40).
JS_MENU = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('X1C-01') >= 0; })[0];
      if (card) card.click();
      setTimeout(function(){
        var o = {}; var pp = q('.ui3-pp'), head = q('.ui3-pp-head'), btn = q('.ui3-pp-fsel .ui3-pp-selbtn');
        o.found = !!(pp && head && btn);
        if (!o.found) { res(dump(o)); return; }
        pp.scrollTop = 0; var t0 = btn.getBoundingClientRect().top;
        pp.scrollTop = 100; var s1 = pp.scrollTop, t1 = btn.getBoundingClientRect().top;
        var kk = s1 ? (t0 - t1) / s1 : 1;
        pp.scrollTop = Math.max(0, (t0 - head.getBoundingClientRect().bottom - 10) / (kk || 1));
        btn.click();
        setTimeout(function(){
          var m = q('.ui3-pp-menu'); o.menu = !!m;
          if (m) {
            //  Сдвигаем так, чтобы верх списка ушёл под шапку.
            var d = (m.getBoundingClientRect().top - head.getBoundingClientRect().top + 20) / (kk || 1);
            pp.scrollTop = pp.scrollTop + d;
          }
          setTimeout(function(){
            var m2 = q('.ui3-pp-menu'); o.menuStill = !!m2;
            if (m2) { var mb = m2.getBoundingClientRect(); o.menuTop = mb.top; o.menuBottom = mb.bottom; }
            var b = head.getBoundingClientRect(); o.head = [b.top, b.bottom];
            o.bad = [];
            for (var i = 1; i < 10; i++) {
              var x = b.left + b.width * i / 10, y = b.top + b.height / 2;
              var e = document.elementFromPoint(x, y);
              if (!e || !e.closest('.ui3-pp-head')) o.bad.push(Math.round(x) + ':' + (e ? (e.className || e.tagName) : 'null'));
            }
            res(dump(o));
          }, 500);
        }, 500);
      }, 1800);
    }, 900);
  }, 1900);
});
"""

#  Форма «Добавить принтер» при открытом пульте: остальная страница уходит под размытое
#  затемнение (.fm-spotlight-overlay, z-index 40). Закреплённая шапка пульта (z-index 41)
#  обязана уйти под него вместе с пультом, а её крестик — не нажиматься сквозь затемнение.
JS_SCRIM = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var MUT = %(mut)s;
  if (MUT) { var st=document.createElement('style'); st.textContent='html.ui3-mode .projects-pane > section.ui3-pp{isolation:auto!important}'; document.head.appendChild(st); }
  function who(e){ if (!e) return 'null';
    if (e.closest('.fm-spotlight-overlay')) return 'SCRIM';
    if (e.closest('.ui3-pp-head')) return 'HEAD';
    return String(e.className && e.className.baseVal === undefined ? e.className : e.tagName).slice(0, 40); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('X1C-01') >= 0; })[0];
      if (card) card.click();
      setTimeout(function(){
        var o = {pp: !!q('.ui3-pp')};
        var h0 = q('.ui3-pp-head'); o.headBefore = [];
        if (h0) { var b0 = h0.getBoundingClientRect();
          for (var j = 1; j < 10; j++) o.headBefore.push(who(document.elementFromPoint(b0.left + b0.width*j/10, b0.top + b0.height/2))); }
        var add = q('[data-help="add-printer"]'); o.addBtn = !!add;
        if (add) add.click();
        setTimeout(function(){
          o.scrim = !!q('.fm-spotlight-overlay');
          var h = q('.ui3-pp-head'); o.hits = [];
          if (h) {
            var b = h.getBoundingClientRect();
            for (var i = 1; i < 10; i++) o.hits.push(who(document.elementFromPoint(b.left + b.width*i/10, b.top + b.height/2)));
            var bx = q('.ui3-pp-back');
            if (bx) { var r = bx.getBoundingClientRect(); o.closeHit = who(document.elementFromPoint(r.left + r.width/2, r.top + r.height/2)); }
          }
          res(dump(o));
        }, 1200);
      }, 1800);
    }, 900);
  }, 1900);
});
"""

JS2 = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = document.querySelector('.printer-card'); if (card) click(card);
      setTimeout(function(){
        var o = {inner: [innerWidth, innerHeight]};
        var pc = q('.pc-scroll');
        o.pc = !!pc; o.pcOv = pc && getComputedStyle(pc).overflowY; o.pcSH = pc && pc.scrollHeight; o.pcCH = pc && pc.clientHeight;
        o.hScroll = [document.documentElement.scrollWidth, document.documentElement.clientWidth];
        if (pc) { pc.scrollTop = 100000; o.pcTop = pc.scrollTop; }
        res(dump(o));
      }, 1500);
    }, 900);
  }, 1900);
});
"""

PR = [{"id": "c1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_C1", "access_code": ""},
      {"id": "c2", "name": "FF-01", "type": "flashforge", "model": "FlashForge Adventurer 5M",
       "ip": "10.0.0.12", "port": 8899, "serial": "FIXTURE_SN_C2", "access_code": ""}]
RUN = {"status": "RUNNING", "percent": 42, "remaining_time": 73, "file_name": "korpus_v3",
       "nozzle_temp": 231.2, "bed_temp": 70.1, "nozzle_target": 235, "bed_target": 70,
       "total_time": 9480, "elapsed": 5100, "nozzle_count": 1,
       "ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "#1f2937"},
                     {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color": "#ef4444"}],
       "ams_now": 0, "parts": [{"name": "korpus", "qty": 2}]}

NARROW = ((1280, 800), (1600, 900))
#  08.10.2026: колонки выбираются по ширине пульта. На 1280×800 пульт уже 594 точек — одна колонка,
#  на 1600×900 шире — две, как на широком экране. Прокрутка у пульта нужна на обоих.
NARROW_COLS = {(1280, 800): 1, (1600, 900): 2}
#  Окно владельца: экран 1366×768, окно на весь экран — рабочая область 1366×705; у стенда
#  рамка окна 24×92, поэтому окно стенда 1390×797.
OWNER = (1390, 797)
WIDE = ((1920, 1080), (2560, 1440))


def run3(w, h, ts=100, tab="", mut=False, mut2=False, view="", mut3=False):
    path = "/ui3?"
    qs = []
    if ts != 100:
        qs.append("ls=ui_text_size:%d" % ts)
    if tab:
        qs.append("ls=ui3_right_tab:%s" % tab)
    if view:
        qs.append("ls=farm_view:%s" % view)
    path += "&".join(qs)
    js = JS3 % {"mut": "true" if mut else "false", "mut2": "true" if mut2 else "false",
                "mut3": "true" if mut3 else "false", "ts": int(ts)}
    r = stage.run(js, window_size=(w, h), settle_ms=2600, path=path, extra_args=("--force-device-scale-factor=1.0",))
    if not r:
        #  Параллельные прогоны изредка роняют стенд (отказ соединения) — один повтор.
        r = stage.run(js, window_size=(w, h), settle_ms=2600, path=path, extra_args=("--force-device-scale-factor=1.0",))
    if r and ts != 100:
        print("      размер текста %d %%: %s" % (ts, {"app": "ставит программа", "test": "подставлен набором",
                                                    "none": "НЕ применён"}.get(r.get("tsMode"), r.get("tsMode"))))
        if r.get("tsMode") not in ("app", "test"):
            check("размер текста %d %% применён на %d×%d" % (ts, w, h), False, r.get("tsMode"))
    return r


def inside(a, top, bottom, tol=1.5):
    return bool(a) and a[0] >= top - tol and a[1] <= bottom + tol


def narrow_ok(r, cols=1):
    """Проверки узкого окна; возвращает список нарушений (пусто — всё хорошо)."""
    bad = []
    if not r or not r.get("panel"):
        return ["пульт не открылся"]
    pane, pp = r.get("pane"), r.get("pp")
    if r.get("cols") != cols:
        bad.append("колонок %s, ждали %s" % (r.get("cols"), cols))
    if not (pane and pp and pp[1] <= pane[1] + 1):
        bad.append("низ пульта %s ниже низа половины %s" % (pp and pp[1], pane and pane[1]))
    if not r.get("canWheel"):
        bad.append("у пульта нет своей прокрутки (overflowY=%s)" % r.get("ppOv"))
    if not ((r.get("ppSH") or 0) > (r.get("ppCH") or 0) + 20):
        bad.append("прокрутка не нужна? scrollHeight %s clientHeight %s" % (r.get("ppSH"), r.get("ppCH")))
    ppE, hE = r.get("ppEnd"), r.get("headEnd")
    if not (ppE and hE):
        bad.append("нет замеров после прокрутки")
    else:
        #  «Служебное» — внизу пульта: после прокрутки до конца оно целиком на виду.
        if not inside(r.get("tools"), hE[1], ppE[1]):
            bad.append("«Служебное» %s не целиком в видимой части пульта %s..%s после прокрутки до конца"
                       % (r.get("tools"), hE[1], ppE[1]))
        for k, v in sorted((r.get("reach") or {}).items()):
            if not v or not inside(v["sec"], v["vis"][0], v["vis"][1]):
                bad.append("раздел %s не достижим прокруткой: %s" % (k, v))
        if len(r.get("reach") or {}) != 2:
            bad.append("разделы задания и «Служебное» не найдены: %s" % r.get("reach"))
        if abs(hE[0] - ppE[0]) > 2:
            bad.append("шапка пульта уехала: %s при верхе пульта %s" % (hE[0], ppE[0]))
    if (r.get("endTop") or 0) <= 0:
        bad.append("прокрутка до конца не сдвинула пульт")
    if r.get("hitsMid") or r.get("hitsEnd"):
        bad.append("в шапке пульта нажатие ловит другое: %s %s" % (r.get("hitsMid"), r.get("hitsEnd")))
    for key, hk in (("camMid", "headMid"), ("camEnd", "headEnd")):
        c, hd = r.get(key), r.get(hk)
        if c and c.get("dock") and hd:
            if c["visBot"] > c["visTop"] + 0.5 and c["visTop"] < hd[1] - 1.5:
                bad.append("%s: видимая часть камеры %.1f выше низа шапки пульта %.1f" % (key, c["visTop"], hd[1]))
            if c["visBot"] > (ppE or pp)[1] + 1.5 and c["visBot"] > c["visTop"] + 0.5:
                bad.append("%s: камера ниже низа пульта" % key)
    hs = r.get("hScroll") or [0, 0, 0, 0]
    if hs[0] > hs[1] + 1 or hs[2] > hs[3] + 1:
        bad.append("горизонтальная прокрутка %s" % hs)
    return bad


if not stage.engine_ready():
    check("браузер стенда доступен", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR, "/api/printer/c1/files": ["a.gcode"],
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"c1": RUN})

    print("--- 2. узкие окна: пульт прокручивается сам ---")
    n = 5
    for ts in (100, 130):
        for (w, h) in NARROW:
            r = run3(w, h, ts)
            n += 1
            bad = narrow_ok(r, NARROW_COLS[(w, h)])
            check("%d. %d×%d, текст %d %%: низ пульта в половине, своя прокрутка, «Служебное» и задание "
                  "достижимы, шапка на месте, камера обрезана" % (n, w, h, ts), not bad,
                  bad or "")
            if r and r.get("camMid"):
                print("      камера на промежуточной прокрутке: clip=%s" % (r["camMid"].get("clip"),))
            probs = stage.page_problems(r)
            n += 1
            check("%d. %d×%d, текст %d %%: консоль чистая" % (n, w, h, ts), not probs, probs[:3])

    print("--- 3. вкладки правой половины (на «Очереди» раньше крутилась вся половина) ---")
    for tab in ("tasks", "queue"):
        for (w, h) in NARROW:
            r = run3(w, h, 100, tab)
            n += 1
            bad = narrow_ok(r, NARROW_COLS[(w, h)])
            if r and ("ui3-right-" + tab) not in (r.get("tab") or []):
                bad.append("вкладка не та: %s" % r.get("tab"))
            if r and r.get("paneOv") != "hidden":
                bad.append("половина прокручивается сама (overflowY=%s)" % r.get("paneOv"))
            check("%d. вкладка %s, %d×%d: пульт прокручивается сам, половина стоит" % (n, tab, w, h), not bad, bad or "")
            probs = stage.page_problems(r)
            n += 1
            check("%d. вкладка %s, %d×%d: консоль чистая" % (n, tab, w, h), not probs, probs[:3])

    print("--- 4. широкие окна: две колонки, пульт своей высоты, прокрутки нет ---")
    for ts in (100, 130):
        for (w, h) in WIDE:
            r = run3(w, h, ts)
            n += 1
            bad = []
            if not r or not r.get("panel"):
                bad = ["пульт не открылся"]
            else:
                pane, pp = r.get("pane"), r.get("pp")
                if r.get("cols") != 2:
                    bad.append("колонок %s" % r.get("cols"))
                if not (pane and pp and pp[1] <= pane[1] + 1):
                    bad.append("низ пульта ниже половины")
                if (r.get("ppSH") or 0) > (r.get("ppCH") or 0) + 1:
                    bad.append("появилась прокрутка %s/%s" % (r.get("ppSH"), r.get("ppCH")))
                #  Пульт не растянут до низа: его высота — высота содержимого (плюс рамка).
                if not (pp and abs(pp[2] - (r.get("contentH") or 0)) <= 4):
                    bad.append("высота пульта %s не равна содержимому %s" % (pp and pp[2], r.get("contentH")))
                if r.get("hitsMid"):
                    bad.append("нажатие в шапке ловит другое: %s" % r.get("hitsMid"))
                hs = r.get("hScroll") or [0, 0, 0, 0]
                if hs[0] > hs[1] + 1 or hs[2] > hs[3] + 1:
                    bad.append("горизонтальная прокрутка %s" % hs)
                c = r.get("cam0")
                if c and c.get("dock") and abs(c["visTop"] - c["top"]) > 1.5:
                    bad.append("камера обрезана без прокрутки: %s" % c.get("clip"))
            check("%d. %d×%d, текст %d %%: две колонки, высота пульта своя (%s), прокрутки нет"
                  % (n, w, h, ts, (r or {}).get("pp", [0, 0, 0])[2] if r and r.get("pp") else "?"), not bad, bad or "")
            probs = stage.page_problems(r)
            n += 1
            check("%d. %d×%d, текст %d %%: консоль чистая" % (n, w, h, ts), not probs, probs[:3])

    print("--- 4a. окно владельца 1366×768 (обход 08.10.2026): управление видно без прокрутки ---")

    def owner_ok(r):
        bad = []
        if not r or not r.get("panel"):
            return ["пульт не открылся"]
        pp, ctl, slot, head = r.get("pp"), r.get("ctl0"), r.get("slot0"), r.get("head0")
        if r.get("cols") != 2:
            bad.append("колонок %s, ждали 2" % r.get("cols"))
        if not (pp and ctl and head and ctl[0] <= head[1] + 40):
            bad.append("управление начинается не под шапкой пульта: %s, шапка %s" % (ctl, head))
        if not (pp and ctl and pp[1] - max(ctl[0], head[1]) >= 300):
            bad.append("из управления видно меньше 300 точек: пульт %s, управление %s" % (pp, ctl))
        if not (slot and slot[1] <= pp[1] + 1):
            bad.append("камера %s уходит за низ пульта %s" % (slot, pp))
        if slot:
            ratio = (slot[4] - slot[3]) / max(1.0, slot[2])
            if not (1.6 <= ratio <= 1.95):
                bad.append("место камеры не 16:9: %.2f (%s)" % (ratio, slot))
        hs = r.get("hScroll") or [0, 0, 0, 0]
        if hs[0] > hs[1] + 1 or hs[2] > hs[3] + 1:
            bad.append("горизонтальная прокрутка %s" % hs)
        return bad

    for ts in (100, 130):
        ro = run3(OWNER[0], OWNER[1], ts)
        n += 1
        bo = owner_ok(ro)
        check("%d. окно 1366×705, текст %d %%: две колонки, управление сразу под шапкой, камера 16:9 целиком в пульте"
              % (n, ts), not bo, bo or "")
        probs = stage.page_problems(ro)
        n += 1
        check("%d. окно 1366×705, текст %d %%: консоль чистая" % (n, ts), not probs, probs[:3])
    #  1280×800 — пульт уже 594 точек, одна колонка. Камера, задание и управление в ~440 точек
    #  высоты вместе не помещаются; правило 37 ограничивает камеру, и управление поднимается.
    #  Печатающий принтер: блок задания высокий, управление начинается у самого края пульта.
    r1 = run3(1280, 800, 100)
    r1m = run3(1280, 800, 100, "", mut2=True)
    n += 1
    ok1 = bool(r1 and r1m and r1.get("panel") and r1.get("cols") == 1 and r1.get("slot0") and r1m.get("slot0")
               and r1.get("ctl0") and r1m.get("ctl0") and r1.get("pp"))
    if ok1:
        s1, s1m = r1["slot0"], r1m["slot0"]
        ok1 = (s1[2] < (s1[4] - s1[3]) * 9 / 16 - 40          # место камеры ниже, чем 16:9 по ширине
               and r1m["ctl0"][0] - r1["ctl0"][0] >= 120     # управление поднялось
               and r1["ctl0"][0] <= r1["pp"][1] + 60)        # и начинается у края видимой части
    check("%d. 1280×800: одна колонка, камера ограничена по высоте, управление поднялось к видимой части" % n,
          ok1, r1 and r1m and {"cols": r1.get("cols"), "slot": r1.get("slot0"), "slot_без_правила": r1m.get("slot0"),
                               "ctl": r1.get("ctl0"), "ctl_без_правила": r1m.get("ctl0"), "pp": r1.get("pp")})
    #  Непустота: без правила 37 на окне владельца управление уходит ниже края пульта.
    rmo = run3(OWNER[0], OWNER[1], 100, "", mut2=True)
    n += 1
    check("%d. непустота: без правила 37 на окне 1366×705 одна колонка и управление ниже края пульта" % n,
          bool(rmo and rmo.get("panel")) and rmo.get("cols") == 1 and bool(rmo.get("ctl0") and rmo.get("pp"))
          and rmo["ctl0"][0] >= rmo["pp"][1] - 1, rmo and {k: rmo.get(k) for k in ("cols", "ctl0", "pp")})

    #  16.10.2026 (R-111): второй снимок обхода 08.10.2026 — вид «Дашборд». С открытым пультом колонка
    #  принтеров там была 46 %, пульту на 1366×768 оставалось 571 точка — одна колонка, и управление
    #  начиналось ниже края пульта (замер стенда: 0 точек управления без прокрутки). Плюс частые
    #  масштабы ноутбуков: 1920×1080 при 125 % (окно 1536×864) и при 150 % (1280×720).
    print("--- 4b. вид «Дашборд» и окна ноутбуков (R-111, 16.10.2026) ---")
    for ts in (100, 130):
        rd = run3(OWNER[0], OWNER[1], ts, view="dash")
        n += 1
        bd = owner_ok(rd)
        if rd and not rd.get("dashPp"):
            bd.append("вид «Дашборд» с пультом не включился (нет ui3-dash-pp)")
        check("%d. «Дашборд», окно 1366×705, текст %d %%: две колонки, управление сразу под шапкой, камера в пульте"
              % (n, ts), not bd, bd or "")
        probs = stage.page_problems(rd)
        n += 1
        check("%d. «Дашборд», окно 1366×705, текст %d %%: консоль чистая" % (n, ts), not probs, probs[:3])
    rdm = run3(OWNER[0], OWNER[1], 100, view="dash", mut3=True)
    n += 1
    check("%d. непустота: с прежней колонкой 46 %% на «Дашборде» пульт в одну колонку и управление ниже его края" % n,
          bool(rdm and rdm.get("panel") and rdm.get("dashPp")) and rdm.get("cols") == 1
          and bool(rdm.get("ctl0") and rdm.get("pp")) and rdm["ctl0"][0] >= rdm["pp"][1] - 1,
          rdm and {k: rdm.get(k) for k in ("cols", "ctl0", "pp", "dashPp")})
    for (w, h), view in (((1536, 864), ""), ((1536, 864), "dash")):
        rl = run3(w, h, 100, view=view)
        n += 1
        bl = owner_ok(rl)
        check("%d. %d×%d (ноутбук 1920×1080 при 125 %%)%s: две колонки, управление под шапкой, камера в пульте"
              % (n, w, h, ", «Дашборд»" if view else ""), not bl, bl or "")
        probs = stage.page_problems(rl)
        n += 1
        check("%d. %d×%d%s: консоль чистая" % (n, w, h, ", «Дашборд»" if view else ""), not probs, probs[:3])
    #  1280×720 (ноутбук при 150 %): пульт уже 594 точек — одна колонка в обоих видах. Действует
    #  договорённость узких окон: своя прокрутка, все разделы достижимы, камера ограничена, без
    #  горизонтальной прокрутки. Управление у печатающего принтера здесь начинается ниже видимой
    #  части (камера 160 точек + блок задания) — это печатается для сведения, решения ещё нет.
    for view in ("", "dash"):
        rs = run3(1280, 720, 100, view=view)
        n += 1
        bs = narrow_ok(rs, 1)
        check("%d. 1280×720 (ноутбук 1920×1080 при 150 %%)%s: одна колонка, своя прокрутка, разделы достижимы"
              % (n, ", «Дашборд»" if view else ""), not bs, bs or "")
        if rs and rs.get("ctl0") and rs.get("pp"):
            print("      сведения: управление начинается на %.0f точек ниже видимой части пульта"
                  % (rs["ctl0"][0] - rs["pp"][1]))
        probs = stage.page_problems(rs)
        n += 1
        check("%d. 1280×720%s: консоль чистая" % (n, ", «Дашборд»" if view else ""), not probs, probs[:3])

    print("--- 5. непустота: без новых правил дефект обязан быть виден ---")
    rm = run3(1280, 800, 100, "", mut=True)
    badm = narrow_ok(rm)
    n += 1
    check("%d. подмена правил (пульт без своей прокрутки) — набор видит обрезанный низ" % n,
          bool(rm and rm.get("panel")) and any("своей прокрутки" in b for b in badm)
          and any("ниже низа половины" in b for b in badm), badm)

    print("--- 6. открытый список файлов при прокрутке уходит под шапку пульта ---")
    stage.set_live({"c1": dict(RUN, status="IDLE", percent=0, remaining_time=0, file_name="", elapsed=0,
                               total_time=0, parts=[])})
    stage.set_api({"/api/printers": PR, "/api/printer/c1/files": ["a.gcode", "b.gcode", "c.gcode.3mf"],
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    rmn = stage.run(JS_MENU, window_size=(1280, 800), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    if not rmn:
        rmn = stage.run(JS_MENU, window_size=(1280, 800), settle_ms=2600, path="/ui3",
                        extra_args=("--force-device-scale-factor=1.0",))
    n += 1
    check("%d. 1280×800: список файлов открыт, его верх под шапкой, шапка остаётся сверху и ловит нажатия" % n,
          bool(rmn) and rmn.get("found") and rmn.get("menu") and rmn.get("menuStill")
          and (rmn.get("menuTop") or 0) < rmn["head"][1] and not rmn.get("bad"),
          rmn and {k: rmn.get(k) for k in ("found", "menu", "menuStill", "menuTop", "head", "bad")})
    probs = stage.page_problems(rmn)
    n += 1
    check("%d. список файлов: консоль чистая" % n, not probs, probs[:3])

    print("--- 6a. форма «Добавить принтер»: шапка пульта уходит под затемнение ---")
    stage.set_live({"c1": RUN})
    stage.set_api({"/api/printers": PR, "/api/printer/c1/files": ["a.gcode"],
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})

    def run_scrim(mut=False):
        js = JS_SCRIM % {"mut": "true" if mut else "false"}
        rr = stage.run(js, window_size=(1280, 800), settle_ms=2600, path="/ui3",
                       extra_args=("--force-device-scale-factor=1.0",))
        if not rr:
            rr = stage.run(js, window_size=(1280, 800), settle_ms=2600, path="/ui3",
                           extra_args=("--force-device-scale-factor=1.0",))
        return rr

    def scrim_ok(rr):
        return (bool(rr) and rr.get("pp") and rr.get("addBtn") and rr.get("scrim")
                and rr.get("headBefore") == ["HEAD"] * 9
                and rr.get("hits") == ["SCRIM"] * 9 and rr.get("closeHit") == "SCRIM")

    rs = run_scrim()
    n += 1
    check("%d. 1280×800: при открытой форме принтера шапка пульта и крестик под затемнением, "
          "сквозь него не нажимаются" % n, scrim_ok(rs),
          rs and {k: rs.get(k) for k in ("pp", "addBtn", "scrim", "headBefore", "hits", "closeHit")})
    probs = stage.page_problems(rs)
    n += 1
    check("%d. форма принтера: консоль чистая" % n, not probs, probs[:3])
    rsm = run_scrim(mut=True)
    n += 1
    check("%d. непустота: без isolation у пульта набор видит шапку поверх затемнения" % n,
          bool(rsm) and rsm.get("scrim") and not scrim_ok(rsm) and "HEAD" in (rsm.get("hits") or []),
          rsm and {k: rsm.get(k) for k in ("scrim", "hits", "closeHit")})

    print("--- 7. интерфейс 2.0 не задет ---")
    r2 = stage.run(JS2, window_size=(1280, 800), settle_ms=2600, path="/",
                   extra_args=("--force-device-scale-factor=1.0",))
    n += 1
    check("%d. 2.0, 1280×800: раскрытая ячейка прокручивается, как было" % n,
          bool(r2) and r2.get("pc") is True and r2.get("pcOv") == "auto"
          and (r2.get("pcSH") or 0) > (r2.get("pcCH") or 0) and (r2.get("pcTop") or 0) > 0
          and r2["hScroll"][0] <= r2["hScroll"][1] + 1,
          r2 and {k: r2.get(k) for k in ("pc", "pcOv", "pcSH", "pcCH", "pcTop", "hScroll")})
    probs = stage.page_problems(r2)
    n += 1
    check("%d. 2.0: консоль чистая" % n, not probs, probs[:3])

    stage.set_api(None)
    stage.set_live(None)
    stage.stop()

print("\nИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
