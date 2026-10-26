# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.835 — широкий фикс кадра `#app` НЕ ломает остальные экраны.

ЧТО ЗАЩИЩАЕТ. Верхний бар перестал уезжать благодаря фиксированному кадру:
`html.m-ui #app { position:fixed; inset:0; overflow:hidden; overscroll-behavior:none }`.
Такой фикс широкий по определению: он выводит корень интерфейса из потока и запрещает прокрутку
корня. Значит, обязана быть отдельная защита от побочных эффектов — каждый экран и каждый слой
должен остаться видимым, кликабельным и ПРОКРУЧИВАЕМЫМ ВНУТРИ СВОЕГО контейнера, а нижнее
содержимое — достижимым. Проверка «элемент есть в DOM» здесь недостаточна и намеренно не
используется: измеряется фактическая геометрия, попадание курсора и доступность низа.

КАК ПРОВЕРЯЕТСЯ. НАСТОЯЩЕЕ приложение (web/index.html + app.js + app.css + вендорный Vue) в
headless Edge через CDP (tools/_fm_ui_stage.py). Поверхности открываются РЕАЛЬНЫМИ действиями:
клик по шестерёнке, по плиткам, по заголовку списка принтеров, правый клик по карточке принтера,
клик по плитке модуля. Для каждой поверхности снимается:
  * прокрутка корня (documentElement/body) — обязана оставаться нулевой и невозможной;
  * положение верхнего бара до и после — обязано совпадать;
  * видимость и попадание курсора в центр поверхности (кадр её не перекрывает);
  * СВОЙ scroll-контейнер: если содержимое выше контейнера, прокрутка вниз обязана доводить до
    последнего элемента (нижнее содержимое реально доступно);
  * горизонтальное переполнение — 0;
  * ошибки консоли, исключения и предупреждения Vue — 0.

БЕЗОПАСНОСТЬ. Рабочая БД, DATA_DIR, config и production-рантайм не используются; данные сцены
синтетические; принтерам ничего не отправляется; печати не запускаются; ничего не сохраняется.

Запуск:  python tools/test_app_frame_surfaces.py      (0 = кадр никому не мешает)
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "APP_FRAME_SURFACES_SENTINEL_2_835"

CSS = io.open(os.path.join(REPO, "web", "app.css"), encoding="utf-8",
              errors="surrogateescape", newline="").read()

_pass, _fail = [0], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:260]) if detail else ""))


def sec(t):
    print("\n--- %s ---" % t)


# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("КАДР #app: статический контракт (1-5)")

_frame = re.search(r"html\.m-ui\s+#app\s*\{([^}]*)\}", CSS)
_frame_body = re.sub(r"\s+", "", _frame.group(1)) if _frame else ""
check("1. кадр объявлен именно для html.m-ui #app (а не для голого #app — иначе он перехватывает "
      "точки монтирования сторонних страниц)", bool(_frame), "правило не найдено")
check("2. кадр выведен из потока и не прокручивается: position:fixed + inset:0 + overflow:hidden",
      "position:fixed" in _frame_body and "inset:0" in _frame_body and "overflow:hidden" in _frame_body,
      _frame_body[:160])
_bare_app = [sel.strip() for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", CSS)
             for sel in sel.split(",")
             if sel.strip() == "#app" and "position:fixed" in re.sub(r"\s+", "", body)]
check("3. голого правила `#app{position:fixed}` в файле нет (область действия ограничена)",
      not _bare_app, _bare_app)
check("4. цепочка прокрутки не выходит наружу кадра (overscroll-behavior:none)",
      "overscroll-behavior:none" in _frame_body, _frame_body[:160])
# Инвариант 🔒 из AGENTS §6: списки не должны листать страницу позади.
_contain = [s for s in (".ex-list", ".ex-side", ".ex-prev", ".fm-users-list", ".fm-audit-list",
                        ".fm-set-scroll", ".diag-body", ".fm-changelog-scroll")
            if not re.search(re.escape(s) + r"[^{]*\{[^}]*overscroll-behavior:\s*contain", CSS)]
check("5. прежний инвариант списков (overscroll-behavior:contain) кадром не отменён", not _contain, _contain)

# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("БРАУЗЕР: поверхности приложения (6-...)")

PRINTERS = [
    {"id": "p1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
     "ip": "10.0.0.11", "port": 8883, "serial": "S1", "access_code": ""},
    {"id": "p2", "name": "K2-02", "type": "klipper", "model": "Creality K2 Plus",
     "ip": "10.0.0.12", "port": 7125, "serial": "S2", "access_code": ""},
]
SEND_JOBS = {"jobs": [
    {"job_id": i, "printer_id": "p1", "printer_name": "X1C-01", "file_name": "part_%d.3mf" % i,
     "source": "task", "state": ("failed" if i % 4 == 3 else "uploading"),
     "progress": (i * 7) % 100, "bytes_sent": None, "bytes_total": None,
     "error": ("no connection" if i % 4 == 3 else None), "created_at": i} for i in range(1, 13)],
    "reserved_printer_ids": []}
MODULES = {"modules": [{"id": "inventory", "ru": "Складской учёт", "en": "Inventory",
                        "version": "1.7.24", "icon": "archive", "entry": "web/InventoryPanel.js",
                        "enabled": True,
                        "launchers": [{"ru": "Складской учёт", "en": "Inventory",
                                       "icon": "archive", "props": {}}]}]}

# Общий пролог измерения: одна функция на все поверхности, чтобы пороги были одинаковыми.
PROBE = r"""
var HEADER0 = null;
function headTop(){ var h=document.querySelector('.app-header'); return h? Math.round(h.getBoundingClientRect().top*10)/10 : null; }
function rootScroll(){ var d=document.documentElement, b=document.body;
  return {docTop:d.scrollTop, bodyTop:b.scrollTop,
          docOver:d.scrollHeight-d.clientHeight, bodyOver:b.scrollHeight-b.clientHeight}; }
function visible(e){ if(!e) return false; var b=e.getBoundingClientRect(); var cs=getComputedStyle(e);
  return b.width>4 && b.height>4 && cs.display!=='none' && cs.visibility!=='hidden' && parseFloat(cs.opacity||'1')>0.05; }
// точки внутри элемента И внутри видимой области: элемент считается доступным курсору, если
// хотя бы в одной из них верхним оказывается он сам или его потомок (кадр его не перекрыл)
function hitPoints(e){ var b=e.getBoundingClientRect();
  // берём ВИДИМУЮ часть элемента: высокая секция может уходить за нижний край области прокрутки,
  // и это не «перекрытие кадром», а нормальное состояние длинного списка
  var l=Math.max(b.left,1), r=Math.min(b.right,innerWidth-1);
  var t=Math.max(b.top,1), bo=Math.min(b.bottom,innerHeight-1);
  if(r-l<2 || bo-t<2) return [];
  var pts=[];
  [(l+r)/2, l+3, r-3].forEach(function(x){ [(t+bo)/2, t+3, bo-3].forEach(function(y){
    pts.push([Math.round(x),Math.round(y)]); }); });
  return pts; }
// Достижимость курсором по СТЕКУ элементов в точке: поверхность достижима, если она (или её
// потомок) есть в стеке, а всё, что лежит НАД ней, — либо её предок, либо слой, сквозь который
// курсор проходит (pointer-events:none). Так служебные прозрачные слои не считаются помехой.
function reachAt(e,x,y){ var st=document.elementsFromPoint(x,y)||[];
  for (var i=0;i<st.length;i++){ var t=st[i];
    if (t===e || e.contains(t)) return {ok:true, blocker:''};
    if (t.contains(e)) continue;
    if (getComputedStyle(t).pointerEvents==='none') continue;
    return {ok:false, blocker:String(t.id||t.className||t.tagName).slice(0,60)}; }
  return {ok:false, blocker:'элемента нет в стеке точки'}; }
function hitOk(e){ if(!e) return false; var pts=hitPoints(e);
  if(!pts.length) return false;
  for (var i=0;i<pts.length;i++){ if(reachAt(e,pts[i][0],pts[i][1]).ok) return true; }
  return false; }
function hitBlocker(e){ var pts=hitPoints(e);
  if(!pts.length) return 'вне видимой области (rect ' + JSON.stringify(e.getBoundingClientRect()) + ')';
  for (var i=0;i<pts.length;i++){ var r=reachAt(e,pts[i][0],pts[i][1]); if(!r.ok) return r.blocker; }
  return ''; }
// ожидание: прокрутка к секции идёт не мгновенно, поэтому измеряем ПОСЛЕ того, как элемент
// действительно попал в видимую область (или по таймауту — тогда проверка честно краснеет)
function waitVisible(getEl, cb, ms){ var t0=Date.now();
  (function w(){ var e=getEl();
    if(e && hitPoints(e).length) return setTimeout(cb, 120);
    if(Date.now()-t0>(ms||3000)) return cb();
    setTimeout(w, 100); })(); }
// свой контейнер прокрутки: сам элемент или ближайший предок с реальной прокруткой
function scroller(e){ var n=e;
  while(n && n!==document.body){ var cs=getComputedStyle(n);
    if(/(auto|scroll)/.test(cs.overflowY) && n.scrollHeight-n.clientHeight>2) return n;
    n=n.parentElement; }
  return null; }
// доступно ли нижнее содержимое: прокручиваем контейнер до конца и смотрим, виден ли последний ребёнок
function bottomReachable(box){
  var sc=scroller(box);
  if(!sc){
    // прокрутки нет нигде в цепочке: это честно только если содержимое правда помещается в окно
    var over0=box.scrollHeight-box.clientHeight;
    if(over0>2) return {needed:true, ok:false, over:over0, why:'содержимое выше окна, а прокрутки нет'};
    return {needed:false, ok:true, why:'содержимое помещается целиком'}; }
  var before=sc.scrollTop;
  sc.scrollTop = sc.scrollHeight;
  var reached = sc.scrollTop >= sc.scrollHeight - sc.clientHeight - 2;
  var kids=[].slice.call(sc.children).filter(function(k){ return k.getBoundingClientRect().height>0; });
  var last=kids.length? kids[kids.length-1] : null;
  var lastVisible = last ? (last.getBoundingClientRect().bottom <= sc.getBoundingClientRect().bottom + 2
                            && last.getBoundingClientRect().bottom > sc.getBoundingClientRect().top) : true;
  sc.scrollTop = before;
  return {needed:true, ok: reached && lastVisible, scroller:String(sc.className||sc.id||sc.tagName).slice(0,40),
          over: sc.scrollHeight-sc.clientHeight, reached: reached, lastVisible: lastVisible};
}
function probe(name, box){
  var r = {name:name, found: !!box};
  if(!box) return r;
  var b=box.getBoundingClientRect();
  r.rect={top:Math.round(b.top), left:Math.round(b.left), w:Math.round(b.width), h:Math.round(b.height)};
  r.visible=visible(box); r.hit=hitOk(box); if(!r.hit) r.blocker=hitBlocker(box);
  r.hOver=box.scrollWidth-box.clientWidth;
  r.bottom=bottomReachable(box);
  r.root=rootScroll();
  r.headTop=headTop();
  r.headMoved = (HEADER0===null||r.headTop===null) ? null : Math.round(Math.abs(r.headTop-HEADER0)*10)/10;
  return r;
}
// провокация прокрутки корня: колесо и клавиши по всему подряд — бар обязан остаться на месте
function provoke(){
  var targets=[document, document.body, document.documentElement,
               document.querySelector('.app-header'), document.querySelector('.main-cols')];
  targets.forEach(function(t){ if(!t) return;
    try { t.dispatchEvent(new WheelEvent('wheel',{deltaY:600,bubbles:true,cancelable:true})); } catch(e){}
    try { t.dispatchEvent(new KeyboardEvent('keydown',{key:'PageDown',bubbles:true})); } catch(e){}
    try { t.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true})); } catch(e){} });
  try { window.scrollTo(0, 4000); } catch(e){}
  try { document.documentElement.scrollTop = 4000; document.body.scrollTop = 4000; } catch(e){}
}
"""

MAIN_JS = PROBE + r"""
return new Promise(function(res){
  var out={probes:[], log:FM_LOG};
  steps([
    function(){ var b=byText('button',['Позже','Later']); if(b) click(b); },
    function(){ HEADER0 = headTop(); out.header0 = HEADER0;
                out.frame = (function(){ var a=document.getElementById('app'); var cs=getComputedStyle(a);
                  return {pos:cs.position, ovf:cs.overflow, over:cs.overscrollBehavior}; })();
                out.probes.push(probe('workspace', document.querySelector('.main-cols'))); },
    // панель фоновых отправок — измеряем в чистом состоянии, до открытия меню
    function(){ out.probes.push(probe('панель подсказок', document.querySelector('.suggest-pane'))); },
    // подсказки-tooltip: контролы с title обязаны быть доступны курсору (кадр их не перекрывает)
    // Подписи ВНУТРИ панели отправок исключены осознанно: там текст намеренно перекрыт своими же
    // слоями строки (стадия/прогресс) — это внутреннее наложение панели, к кадру отношения не имеет,
    // а сама панель проверяется отдельной пробой выше.
    function(){ var withTitle=[].slice.call(document.querySelectorAll('[title]')).filter(function(e){
        var b=e.getBoundingClientRect();
        return b.width>6&&b.height>6 && hitPoints(e).length>0 && !e.closest('.suggest-pane'); });
      out.titled = withTitle.length;
      out.titledHit = withTitle.filter(function(e){ return hitOk(e); }).length;
      out.titledMiss = withTitle.filter(function(e){ return !hitOk(e); })
        .map(function(e){ return String(e.className||e.tagName).slice(0,40); }).slice(0,6); },
    function(){ provoke(); },
    function(){ out.probes.push(probe('workspace после провокаций', document.querySelector('.main-cols'))); },
    // выпадающее меню сортировки принтеров
    function(){ var h=document.querySelector('[data-tour="psort"]'); if(h) click(h); },
    function(){ out.probes.push(probe('dropdown сортировки', document.querySelector('#fm-overlay-root .fm-bg-raised'))); },
    function(){ document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); },
    // контекстное меню принтера
    function(){ var c=document.querySelector('.printer-card');
      if(c) c.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:120,clientY:160})); },
    function(){ out.probes.push(probe('контекстное меню', document.querySelector('.ctx-menu'))); },
    function(){ document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); },
    // аварийный экран: обязан показываться ПОВЕРХ фиксированного кадра
    function(){ var f=document.getElementById('fm-boot-fallback'); if(f) f.style.display='flex'; },
    function(){ var f=document.getElementById('fm-boot-fallback');
      out.probes.push(probe('аварийный экран (boot fallback)', f));
      if(f) f.style.display='none'; },
  ], function(){ out.diagTail=rootScroll(); res(dump(out)); });
});
"""

SET_JS = PROBE + r"""
return new Promise(function(res){
  var out={probes:[], log:FM_LOG};
  openStage('system', function(){
    HEADER0 = headTop(); out.header0 = HEADER0;
    steps([
      function(){ out.probes.push(probe('панель настроек', document.querySelector('.fm-set-scroll'))); },
      // мини-навигация: переход к последней секции полосы не должен двигать бар
      function(){ var chips=[].slice.call(document.querySelectorAll('.fm-set-mini-a'));
        out.chips = chips.length; if(chips.length) click(chips[chips.length-1]); },
      function(done){ waitVisible(function(){ return document.getElementById('fm-sec-modules') ||
        document.getElementById('fm-sec-backup'); }, done, 4000); },
      function(){ out.probes.push(probe('последняя секция «Системы» после чипа',
          document.getElementById('fm-sec-backup') || document.getElementById('fm-sec-modules'))); },
      //  2.999: модули живут на СВОЕЙ вкладке — переходим туда и там проверяем установку.
      function(){ var t=byText('.fm-set-nav-item',['Модули','Modules']); if(t) click(t);
        else FM_LOG.push('вкладка «Модули» не найдена'); },
      function(done){ waitVisible(function(){ return document.getElementById('fm-sec-modules'); }, done, 4000); },
      function(){ out.probes.push(probe('секция «Модули» на своей вкладке', document.getElementById('fm-sec-modules')));
        out.modInstall = (function(){ var b=document.querySelector('#fm-sec-modinstall .fm-set-act');
          if(!b) return {found:false};
          var cs=getComputedStyle(b);
          // вход в СИСТЕМНЫЙ выбор файла: контрол обязан жить внутри области прокрутки настроек
          // (то есть внутри кадра) и не быть выключенным из отрисовки
          return {found:true, display:cs.display, disabled:!!b.disabled,
                  inScroll: !!(document.querySelector('.fm-set-scroll') || {contains:function(){return false;}}).contains(b)}; })(); },
      function(){ var t=byText('.fm-set-nav-item',['Система','System']); if(t) click(t); },
      function(){ var chips=[].slice.call(document.querySelectorAll('.fm-set-mini-a'));
        var b=chips.filter(function(c){ return /Резерв|Backup/.test(c.textContent||''); })[0]; if(b) click(b); },
      function(done){ waitVisible(function(){ return document.getElementById('fm-sec-backup'); }, done, 4000); },
      function(){ out.probes.push(probe('секция «Резервная копия»', document.getElementById('fm-sec-backup'))); },
      function(){ provoke(); },
      function(){ out.probes.push(probe('панель настроек после провокаций', document.querySelector('.fm-set-scroll'))); },
      // окно смены порта — настоящая модалка поверх кадра
      function(){ var b=byText('button',['Изменить порт','Change port','Изменить','Change']); if(b) click(b); },
      function(){ out.probes.push(probe('модальное окно (смена порта)', document.querySelector('.fm-ov-win'))); },
      function(){ document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); },
      // рабочие экраны того же слота: диагностика и файлы принтеров
      function(){ var t=byText('.fm-set-tile',['Диагностика','Diagnostics']); if(t) click(t); },
      function(){ out.probes.push(probe('экран «Диагностика»', document.querySelector('.diag-body'))); },
      function(){ click(gear()); },
      function(){ var t=byText('.fm-set-tile',['Файлы принтеров','Printer files']); if(t) click(t); },
      function(){ out.probes.push(probe('экран «Файлы принтеров»',
          document.querySelector('.fm-printer-files-workspace'))); },
      // окно модуля открывается карточкой модуля в настройках — тот же путь, что у владельца
      function(){ click(gear()); },
      function(){ var t=byText('.fm-set-nav-item',['Модули','Modules']); if(t) click(t); },
      function(){ var card=document.querySelector('#fm-sec-modules .fm-set-act[role="button"]');
        if(card) click(card); else FM_LOG.push('карточка модуля не найдена'); },
      function(){ out.probes.push(probe('окно модуля (Складской учёт)',
          document.querySelector('.fm-inv-body') || document.querySelector('.fm-inv-root'))); },
    ], function(){ res(dump(out)); });
  });
});
"""


def _fmt(p):
    return "%-34s найден=%s видим=%s курсор=%s h-over=%s низ=%s бар=%s" % (
        p.get("name"), p.get("found"), p.get("visible"), p.get("hit"), p.get("hOver"),
        (p.get("bottom") or {}).get("ok"), p.get("headMoved"))


if not stage.engine_ready():
    check("6. браузерный движок доступен (без него кадр проверить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    stage.set_api({"/api/printers": PRINTERS, "/api/send-jobs": SEND_JOBS, "/api/modules": MODULES,
                   # пустые, но ПРАВИЛЬНОЙ ФОРМЫ ответы модуля: иначе панель склада падает на
                   # `.length` у undefined — это свойство стенда, а не дефект продукта
                   "/api/mod/inventory/filament": {"vendors": [], "filaments": [], "spools": []},
                   "/api/mod/inventory/ams": {"printers": []},
                   "/api/mod/inventory/forecast": {"spools": []},
                   "/api/mod/inventory/items": {"items": []},
                   "/api/mod/inventory/locations": {"locations": []},
                   "/api/mod/inventory/settings": {"settings": {}},
                   "/api/mod/inventory/cost": {"by_file": [], "by_material": [], "filament_value": 0,
                                              "parts_value": 0, "spent": [], "total_value": 0}})
    RUNS = {}
    for key, js, wh in (("main", MAIN_JS, (1600, 900)), ("settings", SET_JS, (1600, 900)),
                        ("main-узкое", MAIN_JS, (1280, 720)), ("settings-zoom150", SET_JS, (1440, 900))):
        extra = ("--force-device-scale-factor=1.5",) if key.endswith("zoom150") else ()
        R = stage.run(js, window_size=wh, settle_ms=2000, extra_args=extra)
        RUNS[key] = R or {}
        print("\n   [%s] %s  чипы=%s подсказки=%s/%s %s" % (
            key, "OK" if R else ("НЕТ РЕЗУЛЬТАТА: %s" % stage.last_diag()),
            (R or {}).get("chips"), (R or {}).get("titledHit"), (R or {}).get("titled"),
            (R or {}).get("titledMiss") or ""))
        for p in (R or {}).get("probes", []):
            print("      " + _fmt(p))

    allp = [(k, p) for k, R in RUNS.items() for p in (R.get("probes") or [])]
    check("6. все четыре прогона (главный экран, настройки, узкое окно, увеличение 150 %) выполнены",
          all(RUNS[k].get("probes") for k in RUNS), {k: bool(RUNS[k].get("probes")) for k in RUNS})
    check("7. кадр действительно фиксированный во время прогона (position:fixed, overflow:hidden)",
          all(RUNS[k]["frame"]["pos"] == "fixed" and RUNS[k]["frame"]["ovf"] == "hidden"
              for k in RUNS if RUNS[k].get("frame")),
          {k: RUNS[k].get("frame") for k in RUNS})
    _missing = [(k, p["name"]) for k, p in allp if not p.get("found")]
    check("8. каждая заявленная поверхность реально открылась (ни одна не «не найдена»)",
          not _missing, _missing)
    _invis = [(k, p["name"]) for k, p in allp if p.get("found") and not p.get("visible")]
    check("9. каждая поверхность видима (не нулевого размера, не скрыта)", not _invis, _invis)
    _nohit = [(k, p["name"], p.get("blocker")) for k, p in allp if p.get("found") and not p.get("hit")]
    check("10. кадр не перекрывает поверхности: курсор попадает в каждую из них",
          not _nohit, _nohit)
    _rootscr = [(k, p["name"], p["root"]) for k, p in allp
                if p.get("root") and (p["root"]["docTop"] or p["root"]["bodyTop"]
                                      or p["root"]["docOver"] > 0 or p["root"]["bodyOver"] > 0)]
    check("11. корень НИКОГДА не прокручен и не имеет чего прокручивать (в т.ч. после колеса, "
          "PageDown/End и программной прокрутки)", not _rootscr, _rootscr[:4])
    _moved = [(k, p["name"], p["headMoved"]) for k, p in allp
              if p.get("headMoved") not in (None, 0, 0.0)]
    check("12. верхний бар не сдвинулся ни на одной поверхности", not _moved, _moved)
    _bottom = [(k, p["name"], p["bottom"]) for k, p in allp
               if p.get("found") and not (p.get("bottom") or {}).get("ok")]
    check("13. нижнее содержимое достижимо: свой scroll-контейнер доводит до последнего элемента",
          not _bottom, _bottom[:4])
    _hover = [(k, p["name"], p["hOver"]) for k, p in allp if (p.get("hOver") or 0) > 0]
    check("14. горизонтального переполнения нет ни на одной поверхности", not _hover, _hover)
    _scrolled = [(k, p["name"], p["bottom"]) for k, p in allp
                 if (p.get("bottom") or {}).get("needed") and (p["bottom"].get("over") or 0) > 0]
    check("15. проверка не вакуумная: хотя бы одна поверхность реально прокручивалась внутри себя",
          bool(_scrolled), len(_scrolled))
    _titles = [(k, RUNS[k].get("titled"), RUNS[k].get("titledHit")) for k in RUNS if RUNS[k].get("titled")]
    check("16. элементы с подсказками (title) доступны курсору — всплывающая подсказка возможна",
          bool(_titles) and all(t[1] == t[2] for t in _titles), _titles)
    _mod = [RUNS[k].get("modInstall") for k in RUNS if RUNS[k].get("modInstall")]
    check("17. вход в системный выбор файла («Установить модуль») отрисован и живёт ВНУТРИ области "
          "прокрутки настроек — кадр его не вынес наружу и не отключил",
          bool(_mod) and all(m.get("found") and m.get("display") != "none" and not m.get("disabled")
                             and m.get("inScroll") for m in _mod), _mod)
    _probs = {k: stage.page_problems(RUNS[k]) for k in RUNS if stage.page_problems(RUNS[k])}
    check("18. ни один прогон не дал ошибок консоли, исключений и предупреждений Vue",
          not _probs, _probs)

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    print("НЕ ПРОЙДЕНО:")
    for f in _fail:
        print("   - %s" % f)
stage.stop()
sys.exit(1 if _fail else 0)
