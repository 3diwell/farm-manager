# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.836 — КАРКАС ПРИЛОЖЕНИЯ И ВЕРХ НАСТРОЕК: геометрические инварианты.

ЧТО ЗАЩИЩАЕТ. Приёмка Alpha 2.835 провалилась по скриншоту владельца: колонка принтеров и окно
«Настройки» заходили под верхний бар, а в «Настройки → Система» верхушки карточек были обрезаны
и уезжали под закреплённую строку чипов. Замер в реальном Edge через CDP на геометрии того же
скриншота (1365x1024, RU) показал ТРИ причины:

  (1) КОРОБКА строки бара .app-header занимала 11.5-73.8, а РИСОВАЛ бар (абсолютный слой
      .fm-header-desktop-v270) 11.5-92.4 при контенте с 85.3 — наложение 7.1px на колонку и на
      любой рабочий экран. Причина: height:2.695rem у коробки против height:3.5rem у слоя;
      разницу раньше срезал overflow:hidden, а Alpha 2.835 срез сняла. Тесты 2.835 мерили
      КОРОБКУ (у неё зазор -11.5px) и потому дефект не видели — эта слепая зона здесь закрыта:
      измеряется именно то, что РИСУЕТСЯ.

  (2) Закреплённая .fm-set-mini не могла встать вплотную к верху области прокрутки: sticky не
      выходит за свой контейнер, а контейнер начинался на 16px ниже (padding-top у .fm-set-scroll).
      Между верхом области и полосой оставалась ПРОЗРАЧНАЯ щель 20.9px, сквозь которую были видны
      проезжающие карточки — это и есть «обрезанные верхушки» на скриншоте.

  (3) setSecGo вычитал ФИКСИРОВАННЫЕ 6px, игнорируя высоту полосы (56-97px: при узком окне чипы
      переносятся на две строки) — заголовок целевой секции уезжал ПОД навигацию.

КАК ПРОВЕРЯЕТСЯ. Статика — разбор настоящих web/app.css и web/app.js. Браузер — НАСТОЯЩЕЕ
приложение в headless Edge через CDP (tools/_fm_ui_stage.py) на шести размерах окна (включая
обязательный сценарий скриншота владельца 1365x1024 RU), пяти уровнях увеличения, RU и EN,
на четырёх рабочих экранах и по всем семи чипам. Недоступный движок, таймаут, ошибка консоли,
предупреждение Vue — КРАСНЫЙ тест с точной причиной, а не пропуск.

БЕЗОПАСНОСТЬ. Рабочая БД, DATA_DIR, config и production-рантайм не используются; принтерам ничего
не отправляется; печати не запускаются.

Запуск:  python tools/test_app_shell_and_settings_header.py     (0 = геометрия в порядке)
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "APP_SHELL_SETTINGS_HEADER_SENTINEL_2_836"

CSS = io.open(os.path.join(REPO, "web", "app.css"), encoding="utf-8",
              errors="surrogateescape", newline="").read()
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", newline="").read()

_pass, _fail = [0], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def sec(t):
    print("\n--- %s ---" % t)


def rule(sel):
    """Тело правила по ТОЧНОМУ селектору (последнее вхождение — append-only перекрывает раннее)."""
    pat = re.escape(sel).replace(r"\ ", r"\s*")
    ms = list(re.finditer(pat + r"\s*\{([^}]*)\}", CSS))
    return re.sub(r"\s+", " ", ms[-1].group(1)).strip() if ms else ""


# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("СТАТИКА: строка бара резервирует РОВНО то, что рисует (1-6)")

_shell = rule("body .fm-style-migrated.fm-header-shell-v270")
_paint = rule("body .fm-style-migrated.fm-header-desktop-v270")
check("1. высота строки бара берётся из переменной --fm-header-h",
      "var(--fm-header-h)" in _shell, _shell)
check("2. высота рисуемого слоя берётся из ТОЙ ЖЕ переменной (разойтись больше не могут)",
      "var(--fm-header-h)" in _paint, _paint)
_var = re.findall(r"--fm-header-h\s*:\s*([^;}]+)", CSS)
check("3. переменная --fm-header-h объявлена ровно один раз", len(_var) == 1, _var)
check("4. значение переменной равно прежней высоте рисуемого слоя (3.5rem) — вид бара не менялся",
      bool(_var) and _var[-1].strip() == "3.5rem", _var)
check("5. компенсирующих сдвигов у бара не появилось (нет transform/отрицательных margin)",
      "transform" not in _shell and "transform" not in _paint
      and not re.search(r"margin[^;]*:\s*-", _shell + _paint), _shell + " | " + _paint)
check("6. прежний кадр html.m-ui #app не тронут (fixed + inset:0 + overflow:hidden)",
      all(x in re.sub(r"\s+", "", rule("html.m-ui #app"))
          for x in ("position:fixed", "inset:0", "overflow:hidden")), rule("html.m-ui #app"))

sec("СТАТИКА: закреплённая навигация настроек (7-13)")

_scroll = rule(".fm-settings-workspace .fm-set-scroll")
_mini = rule(".fm-set-mini")
check("7. у области прокрутки настроек снят верхний отступ (иначе sticky не достаёт до верха)",
      "padding-top:0" in re.sub(r"\s+", "", _scroll), _scroll)
check("8. верхний отступ перенесён на заголовок раздела (вид не изменился)",
      "padding-top:16px" in re.sub(r"\s+", "",
                                   rule(".fm-settings-workspace .fm-set-scroll > .fm-set-head")),
      rule(".fm-settings-workspace .fm-set-scroll > .fm-set-head"))
check("9. отрицательный margin у навигации снят",
      not re.search(r"margin\s*:\s*-", _mini), _mini)
check("10. у навигации непрозрачный фон и явная нижняя граница",
      "background:var(--fm-surface-deep)" in re.sub(r"\s+", "", _mini)
      and "border-bottom" in _mini, _mini)
check("11. под навигацией есть тень-разделитель", "box-shadow" in _mini, _mini)
check("12. область прокрутки знает высоту закреплённой зоны (scroll-padding-top)",
      "scroll-padding-top:var(--fm-set-sticky-h" in re.sub(r"\s+", "", _scroll), _scroll)
check("13. у секций задан scroll-margin-top из ТОЙ ЖЕ величины",
      "scroll-margin-top:var(--fm-set-sticky-h" in re.sub(
          r"\s+", "", rule('.fm-settings-workspace .fm-set-scroll [id^="fm-sec-"]')),
      rule('.fm-settings-workspace .fm-set-scroll [id^="fm-sec-"]'))

sec("СТАТИКА: якорная прокрутка (14-17)")

_go = APPJS[APPJS.index("const setSecGo"):APPJS.index("const setSecGo") + 1400]
# Комментарии вырезаем: внутри setSecGo слово scrollIntoView стоит в ПРОЗЕ («здесь НЕЛЬЗЯ
# использовать scrollIntoView»), и проверка ловила бы собственный текст, а не вызов.
_go_code = re.sub(r"//[^\n]*", "", _go)
check("14. setSecGo не ВЫЗЫВАЕТ scrollIntoView (он прокручивает и внешние контейнеры)",
      "scrollIntoView(" not in _go_code, _go_code[:160])
check("15. setSecGo вычитает ЗАМЕРЕННУЮ высоту закреплённой полосы, а не константу 6px",
      "bandVis" in _go and "- 6," not in _go and "scrollTop + delta - 6" not in _go, _go[:200])
check("16. высоту полосы даёт единая функция-источник истины setStickyMetrics",
      "const setStickyMetrics" in APPJS and "--fm-set-sticky-h" in APPJS)
check("17. восстановление позиции раздела компенсирует закреплённую полосу",
      "_setScrollClampSticky" in APPJS and "_restoreSetScroll" in APPJS)

# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("БРАУЗЕР: реальные измерения")

if not stage.engine_ready():
    check("18. браузерный движок доступен (без него геометрию измерить нечем)", False,
          stage.last_diag())
    print("\n" + "=" * 78)
    print("МЕТКА: %s" % SENTINEL)
    print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
    raise SystemExit(1)

SHELL_JS = r"""
return new Promise(function(res){ openStage('system', function(){
 var __lang=%LANG%;
 try {
  var out={log:FM_LOG, lang:uiLang(), tab:activeTabText(), wantLang:__lang, errs:[]};
  function vis(sel){ return [].slice.call(document.querySelectorAll(sel)).filter(function(e){
      var b=e.getBoundingClientRect(); return b.width>1 && b.height>1; })[0]||null; }
  var H=document.documentElement, B=document.body;
  var hdr=document.querySelector('.app-header');
  var paint=vis('.fm-header-desktop-v270');
  var cols=document.querySelector('.main-cols');
  var left=vis('.left-col');
  var ws=vis('.fm-settings-workspace');
  var setTitle=vis('.fm-settings-workspace .fm-set-title');
  var sc=vis('.fm-set-scroll');
  var headT=vis('.fm-set-head-t'), headD=vis('.fm-set-head-d'), mini=vis('.fm-set-mini');
  var grid=vis('.fm-set-grid');
  if(!hdr||!paint||!cols||!left||!ws||!sc||!mini||!grid){
    out.errs.push('не найдены элементы каркаса/настроек'); return res(dump(out)); }

  out.r={hdr:rectOf(hdr), paint:rectOf(paint), cols:rectOf(cols), left:rectOf(left),
         ws:rectOf(ws), setTitle:rectOf(setTitle), sc:rectOf(sc), headT:rectOf(headT),
         headD:rectOf(headD), mini:rectOf(mini), grid:rectOf(grid)};
  out.miniBg=getComputedStyle(mini).backgroundColor;
  out.miniZ=getComputedStyle(mini).zIndex;
  out.bootFallback=(function(){ var f=document.getElementById('fm-boot-fallback');
      return !!(f && f.getBoundingClientRect().height>1); })();
  out.hScroll={sc:sc.scrollWidth-sc.clientWidth,
               app:(function(a){return a?a.scrollWidth-a.clientWidth:-1;})(document.getElementById('app')),
               doc:H.scrollWidth-H.clientWidth};

  // карточки первого ряда при положении «сверху»
  sc.scrollTop=0;
  var cards=[].slice.call(grid.querySelectorAll(':scope > .fm-set-group')).filter(function(e){
    var b=e.getBoundingClientRect(); return b.height>10&&b.width>10; });
  out.cardsN=cards.length;
  out.top0=(function(){ var mb=mini.getBoundingClientRect().bottom;
    var tops=cards.map(function(e){ return e.getBoundingClientRect().top; });
    return {miniBottom:Math.round(mb*10)/10, firstCardTop:Math.round(Math.min.apply(null,tops)*10)/10,
            gap:Math.round((Math.min.apply(null,tops)-mb)*10)/10}; })();

  // именные карточки владельца: их заголовки НЕ должны быть обрезаны
  // По ИДЕНТИФИКАТОРАМ, а не по подписям: подписи различаются в RU/EN («Сеть и доступ» /
  // «Network & access»), и фильтр по тексту молча давал бы пустой список на английском.
  out.named=cards.map(function(e){ var t=e.querySelector('.fm-set-sec-t');
      var tb=t?t.getBoundingClientRect():null; var b=e.getBoundingClientRect();
      return {id:e.id||'', title:t?(t.textContent||'').trim():'',
              top:Math.round(b.top*10)/10, titleTop:tb?Math.round(tb.top*10)/10:null}; })
    .filter(function(c){ return c.id==='fm-sec-pf' || c.id==='fm-sec-net'; });

  // ПРОКРУТКА: щель над закреплённой полосой обязана быть нулевой
  sc.scrollTop=Math.min(420, sc.scrollHeight-sc.clientHeight);
  setTimeout(function(){
   try {
    var scr=sc.getBoundingClientRect(), mr=mini.getBoundingClientRect();
    out.scrolled={setTop:Math.round(sc.scrollTop),
                  gapAboveMini:Math.round((mr.top-scr.top)*10)/10,
                  miniH:Math.round(mr.height*10)/10};
    // корень не двигается: колесо, клавиши, фокус
    out.root={before:{doc:Math.round(H.scrollTop), body:Math.round(B.scrollTop)}};
    try { H.scrollTop=99999; B.scrollTop=99999; window.scrollTo(0,99999); } catch(e){}
    var ev=new WheelEvent('wheel',{deltaY:1200,bubbles:true,cancelable:true});
    (document.querySelector('.fm-set-scroll')||document.body).dispatchEvent(ev);
    ['PageDown','End',' '].forEach(function(k){
      document.body.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true})); });
    var f=document.querySelector('.fm-set-mini-a'); if(f&&f.focus) f.focus();
    setTimeout(function(){
      out.root.after={doc:Math.round(H.scrollTop), body:Math.round(B.scrollTop),
                      headTop:Math.round(hdr.getBoundingClientRect().top*10)/10};
      out.headTopStart=Math.round(out.r.hdr.top*10)/10;
      out.diag=(window.__fmDiag||null);
      res(dump(out));
    }, 260);
   } catch(e){ out.errs.push(String(e&&e.stack||e).slice(0,300)); res(dump(out)); }
  }, 320);
 } catch(e){ res(dump({errs:[String(e&&e.stack||e).slice(0,300)], log:FM_LOG})); }
}, %LANGARG%); });
"""

CHIPS_JS = r"""
return new Promise(function(res){ openStage('system', function(){
 try {
  var out={log:FM_LOG, lang:uiLang(), chips:[], errs:[]};
  function vis(sel){ return [].slice.call(document.querySelectorAll(sel)).filter(function(e){
      var b=e.getBoundingClientRect(); return b.width>1 && b.height>1; })[0]||null; }
  var sc=vis('.fm-set-scroll'), mini=vis('.fm-set-mini'), H=document.documentElement;
  var hdr=document.querySelector('.app-header');
  if(!sc||!mini){ out.errs.push('нет области настроек'); return res(dump(out)); }
  var chips=[].slice.call(mini.querySelectorAll('.fm-set-mini-a'));
  out.chipN=chips.length;
  var hdrTop0=hdr.getBoundingClientRect().top;
  (function nx(i){
    if(i>=chips.length){ out.hdrTopEnd=Math.round(hdr.getBoundingClientRect().top*10)/10;
                         out.hdrTop0=Math.round(hdrTop0*10)/10; return res(dump(out)); }
    var label=(chips[i].textContent||'').trim();
    click(chips[i]);
    setTimeout(function(){
      try {
        var id=null;
        // активный чип задаёт целевую секцию
        var act=mini.querySelector('.fm-set-mini-a.active');
        var secs=[].slice.call(sc.querySelectorAll('[id^="fm-sec-"]'));
        var target=secs[i] || null;
        var scr=sc.getBoundingClientRect(), mr=mini.getBoundingClientRect();
        var tb=target?target.getBoundingClientRect():null;
        var tt=target?target.querySelector('.fm-set-sec-t'):null;
        var ttb=tt?tt.getBoundingClientRect():null;
        out.chips.push({i:i, label:label, id:target?target.id:'',
          miniBottom:Math.round(mr.bottom*10)/10,
          targetTop:tb?Math.round(tb.top*10)/10:null,
          titleTop:ttb?Math.round(ttb.top*10)/10:null,
          titleBottom:ttb?Math.round(ttb.bottom*10)/10:null,
          belowNav: !!(ttb && ttb.top >= mr.bottom-0.5),
          fullyVisible: !!(ttb && ttb.top>=scr.top-0.5 && ttb.bottom<=scr.bottom+0.5),
          gapAboveMini:Math.round((mr.top-scr.top)*10)/10,
          docTop:Math.round(H.scrollTop), setTop:Math.round(sc.scrollTop),
          activeLabel: act?(act.textContent||'').trim():''});
      } catch(e){ out.errs.push('чип'+i+': '+String(e&&e.message||e)); }
      nx(i+1);
    }, 700);
  })(0);
 } catch(e){ res(dump({errs:[String(e&&e.stack||e).slice(0,300)], log:FM_LOG})); }
}, 'ru'); });
"""

WORKSPACE_JS = r"""
return new Promise(function(res){ openStage('system', function(){
 try {
  var out={log:FM_LOG, surfaces:[], errs:[]};
  function vis(sel){ return [].slice.call(document.querySelectorAll(sel)).filter(function(e){
      var b=e.getBoundingClientRect(); return b.width>1 && b.height>1; })[0]||null; }
  var hdr=document.querySelector('.app-header');
  var paint=vis('.fm-header-desktop-v270');
  var H=document.documentElement, B=document.body;
  function probe(name, el){
    var p=paint.getBoundingClientRect();
    var left=vis('.left-col');
    var lb=left?left.getBoundingClientRect():null;
    var b=el?el.getBoundingClientRect():null;
    return {name:name, found:!!el,
            paintBottom:Math.round(p.bottom*10)/10,
            top:b?Math.round(b.top*10)/10:null,
            leftTop:lb?Math.round(lb.top*10)/10:null,
            overlap:b?Math.round((p.bottom-b.top)*10)/10:null,
            leftOverlap:lb?Math.round((p.bottom-lb.top)*10)/10:null,
            docTop:Math.round(H.scrollTop), bodyTop:Math.round(B.scrollTop),
            hdrTop:Math.round(hdr.getBoundingClientRect().top*10)/10}; }
  steps([
    function(){ out.surfaces.push(probe('Настройки', vis('.fm-settings-workspace'))); },
    function(){ var t=byText('.fm-set-tile',['Диагностика','Diagnostics']); if(t) click(t); },
    function(){ out.surfaces.push(probe('Диагностика', vis('.diag-body')||vis('.fm-diagnostics-workspace'))); },
    function(){ var c=byText('button',['Закрыть','Close']); if(c) click(c); },
    function(){ var g=gear(); if(g && !document.querySelector('.fm-set-scroll')) click(g); },
    function(){ var t=byText('.fm-set-tile',['Файлы принтеров','Printer files']); if(t) click(t); },
    function(){ out.surfaces.push(probe('Файлы принтеров', vis('.fm-printer-files-workspace'))); },
    function(){ var c=byText('button',['Закрыть','Close']); if(c) click(c); },
    // После закрытия рабочего экрана слот занимает та поверхность, что осталась видимой:
    // проверяем ИМЕННО её геометрию, а не гадаем, какая именно откроется.
    function(){ out.surfaces.push(probe('слот после закрытия экрана',
        vis('.projects-pane') || vis('.fm-settings-workspace') || vis('.fm-printer-files-workspace')
        || vis('.fm-diagnostics-workspace'))); }
  ], function(){ out.diag=(window.__fmDiag||null); res(dump(out)); });
 } catch(e){ res(dump({errs:[String(e&&e.stack||e).slice(0,300)], log:FM_LOG})); }
}, 'ru'); });
"""

# FM_SHELL_ONLY — какой блок выполнять. Пусто/all = ВСЁ (релизный прогон и полный набор).
# Значения shell|chips|ws нужны только mutation proof, чтобы каждая порча проверялась минимальным
# блоком и 20 порч укладывались в разумное время. Базовая линия каждого режима в mutation proof
# проверяется отдельно — режим не может быть тихой дырой.
_ONLY = (os.environ.get("FM_SHELL_ONLY") or "all").strip().lower()
_FAST = _ONLY != "all"

SCEN = [
    ((1365, 1024), 1.0, "ru", "СКРИНШОТ ВЛАДЕЛЬЦА 1365x1024 RU"),
    ((3440, 1440), 1.0, "ru", "3440x1440 RU"),
    ((1920, 1080), 1.0, "ru", "1920x1080 RU"),
    ((1280, 720), 1.0, "ru", "1280x720 RU"),
    ((3440, 1440), 1.0, "en", "3440x1440 EN"),
    ((1280, 720), 1.0, "en", "1280x720 EN"),
    ((1920, 1080), 1.25, "ru", "увеличение 125 %"),
    ((1920, 1080), 1.5, "ru", "увеличение 150 %"),
    ((1920, 1080), 1.75, "ru", "увеличение 175 %"),
    ((1920, 1080), 2.0, "ru", "увеличение 200 %"),
]

sec("ПОКРЫТИЕ: обязательные сценарии релиза (17b-17d)")
_labels = [s[3] for s in SCEN]
check("17b. обязательный сценарий скриншота владельца 1365x1024 RU есть в наборе",
      any(l.startswith("СКРИНШОТ ВЛАДЕЛЬЦА 1365x1024 RU") for l in _labels), _labels)
check("17c. увеличение 125/150/175/200 % есть в наборе",
      all(("увеличение %d %%" % p) in _labels for p in (125, 150, 175, 200)), _labels)
check("17d. в наборе есть и русские, и английские сценарии на разных размерах окна",
      len({s[2] for s in SCEN}) == 2 and len({s[0] for s in SCEN}) >= 4,
      [(s[0], s[2]) for s in SCEN])

if _FAST:
    # Минимальный, но НЕ ослабленный набор: окно скриншота владельца, узкое окно и увеличение.
    SCEN = [s for s in SCEN if s[3] in ("СКРИНШОТ ВЛАДЕЛЬЦА 1365x1024 RU", "1280x720 EN",
                                        "увеличение 200 %")]

_shots = os.environ.get("FM_SHELL_SHOTS") or ""
res = {}
for wh, dsf, lang, label in ([] if _ONLY not in ("all", "shell") else SCEN):
    js = SHELL_JS.replace("%LANG%", "'%s'" % lang).replace("%LANGARG%", "'%s'" % lang)
    extra = ("--force-device-scale-factor=%g" % dsf,) if abs(dsf - 1.0) > 1e-9 else ()
    shot = os.path.join(_shots, "after_%s.png" % re.sub(r"\W+", "_", label)) if _shots else None
    R = stage.run(js, window_size=wh, settle_ms=1700, extra_args=extra, shot_path=shot)
    res[label] = R or {}
    r = (R or {}).get("r") or {}
    print("   [%s] бар %s | контент %s | щель над nav %s | корень %s"
          % (label,
             ("%.1f-%.1f/%.1f-%.1f" % (r["hdr"]["top"], r["hdr"]["bottom"],
                                       r["paint"]["top"], r["paint"]["bottom"])) if r else "?",
             ("%.1f" % r["cols"]["top"]) if r else "?",
             ((R or {}).get("scrolled") or {}).get("gapAboveMini"),
             ((R or {}).get("root") or {}).get("after")))

ok = {k: v for k, v in res.items() if v and v.get("r") and not v.get("errs")}
if _ONLY in ("all", "shell"):
    check("18. все %d сценариев каркаса реально исполнены в браузере" % len(SCEN),
          len(ok) == len(SCEN),
          {k: (v.get("errs") or "мост не вернул результат") for k, v in res.items() if k not in ok})

if ok:
    sec("БРАУЗЕР: глобальный каркас (19-31)")
    check("19. верхний бар виден во всех сценариях",
          all(v["r"]["hdr"]["h"] > 10 for v in ok.values()),
          {k: v["r"]["hdr"]["h"] for k, v in ok.items()})
    check("20. колонка принтеров видна во всех сценариях",
          all(v["r"]["left"]["h"] > 50 for v in ok.values()),
          {k: v["r"]["left"]["h"] for k, v in ok.items()})
    check("21. рабочий экран виден во всех сценариях",
          all(v["r"]["ws"]["h"] > 50 for v in ok.values()),
          {k: v["r"]["ws"]["h"] for k, v in ok.items()})
    check("22. КОРОБКА бара равна тому, что бар РИСУЕТ (корень дефекта 2.835)",
          all(abs(v["r"]["hdr"]["bottom"] - v["r"]["paint"]["bottom"]) <= 0.6
              for v in ok.values()),
          {k: (v["r"]["hdr"]["bottom"], v["r"]["paint"]["bottom"]) for k, v in ok.items()})
    check("23. НАРИСОВАННЫЙ бар НЕ пересекается с колонкой принтеров",
          all(v["r"]["left"]["top"] > v["r"]["paint"]["bottom"] + 0.5 for v in ok.values()),
          {k: (v["r"]["paint"]["bottom"], v["r"]["left"]["top"]) for k, v in ok.items()})
    check("24. НАРИСОВАННЫЙ бар НЕ пересекается с рабочим экраном",
          all(v["r"]["ws"]["top"] > v["r"]["paint"]["bottom"] + 0.5 for v in ok.values()),
          {k: (v["r"]["paint"]["bottom"], v["r"]["ws"]["top"]) for k, v in ok.items()})
    check("25. колонка и рабочий экран стоят на ОДНОЙ верхней линии (общий слот, а не свой отступ "
          "у каждого экрана)",
          all(abs(v["r"]["left"]["top"] - v["r"]["ws"]["top"]) <= 1.0 for v in ok.values()),
          {k: (v["r"]["left"]["top"], v["r"]["ws"]["top"]) for k, v in ok.items()})
    _gaps = {k: round(v["r"]["cols"]["top"] - v["r"]["paint"]["bottom"], 1) for k, v in ok.items()}
    check("26. между баром и основной областью есть ОДИН контролируемый зазор (>0 и <40px)",
          all(0.5 < g < 40 for g in _gaps.values()), _gaps)
    #  2.933: при ДРОБНОМ увеличении буст шрифта html{zoom:1.196} отключается (иначе
    #  фирменный шрифт переставал отрисовываться — снимок владельца на 110%). Поэтому
    #  законных значения зазора ДВА: с бустом (целые масштабы) и без (дробные). Внутри
    #  каждой группы зазор по-прежнему единый — подгонки под конкретный экран нет.
    _frac = {k for k in _gaps if "125" in k or "150" in k or "175" in k}
    _g_int = [v for k, v in _gaps.items() if k not in _frac]
    _g_frac = [v for k, v in _gaps.items() if k in _frac]
    check("27. зазор единый внутри целых и внутри дробных масштабов (без подгонки под экран)",
          (not _g_int or max(_g_int) - min(_g_int) <= 1.0)
          and (not _g_frac or max(_g_frac) - min(_g_frac) <= 1.0), _gaps)
    check("28. прокрутка корня документа равна нулю",
          all(v["root"]["after"]["doc"] == 0 for v in ok.values()),
          {k: v["root"]["after"] for k, v in ok.items()})
    check("29. прокрутка body равна нулю",
          all(v["root"]["after"]["body"] == 0 for v in ok.values()),
          {k: v["root"]["after"] for k, v in ok.items()})
    check("30. колесо, клавиши (PageDown/End/Space) и перевод фокуса НЕ сдвигают бар",
          all(abs(v["root"]["after"]["headTop"] - v["headTopStart"]) <= 0.6 for v in ok.values()),
          {k: (v["headTopStart"], v["root"]["after"]["headTop"]) for k, v in ok.items()})
    check("31. горизонтальной прокрутки нет ни у документа, ни у области настроек",
          all(v["hScroll"]["doc"] <= 0 and v["hScroll"]["sc"] <= 0 for v in ok.values()),
          {k: v["hScroll"] for k, v in ok.items()})
    # У каркаса на окне 1280 есть ПРЕДСУЩЕСТВУЮЩИЕ 3px: они были и до этой правки — замерено в
    # прогоне Alpha 2.835 («минимальный 1280 ... h-scroll={'scroll': 0, 'app': 3, 'doc': 0}»).
    # Этой задачей они не введены; проверка держит порог, чтобы они не выросли.
    check("31b. каркас не получил НОВОЙ горизонтальной прокрутки (порог 3px — предсуществующий "
          "остаток на окне 1280, замерен до правки)",
          all(v["hScroll"]["app"] <= 3 for v in ok.values())
          and all(v["hScroll"]["app"] <= 0 for k, v in ok.items() if "1280" not in k),
          {k: v["hScroll"]["app"] for k, v in ok.items()})

    sec("БРАУЗЕР: верх настроек (32-40)")
    check("32. окно «Настройки» не пересекается с верхним баром",
          all(v["r"]["setTitle"] and v["r"]["setTitle"]["top"] > v["r"]["paint"]["bottom"] + 0.5
              for v in ok.values()),
          {k: (v["r"]["paint"]["bottom"], (v["r"]["setTitle"] or {}).get("top"))
           for k, v in ok.items()})
    check("33. заголовок окна «Настройки» виден целиком",
          all(v["r"]["setTitle"] and v["r"]["setTitle"]["h"] > 20 for v in ok.values()),
          {k: (v["r"]["setTitle"] or {}).get("h") for k, v in ok.items()})
    check("34. название вкладки («Система»/«System») видно",
          all(v["r"]["headT"] and v["r"]["headT"]["h"] > 8 for v in ok.values()),
          {k: (v["r"]["headT"] or {}).get("h") for k, v in ok.items()})
    check("35. короткое описание вкладки видно",
          all(v["r"]["headD"] and v["r"]["headD"]["h"] > 8 for v in ok.values()),
          {k: (v["r"]["headD"] or {}).get("h") for k, v in ok.items()})
    check("36. мини-навигация видна",
          all(v["r"]["mini"] and v["r"]["mini"]["h"] > 8 for v in ok.values()),
          {k: (v["r"]["mini"] or {}).get("h") for k, v in ok.items()})
    _alpha = {k: v["miniBg"] for k, v in ok.items()}
    check("37. фон мини-навигации НЕПРОЗРАЧНЫЙ (иначе сквозь неё видно карточки)",
          all(not re.search(r"rgba\([^)]*,\s*0(\.\d+)?\s*\)$", a.strip())
              and a.strip() not in ("transparent", "rgba(0, 0, 0, 0)")
              for a in _alpha.values()), _alpha)
    check("38. заголовок, описание, навигация и сетка идут ОДНОЙ вертикалью",
          all(abs(v["r"]["headT"]["left"] - v["r"]["mini"]["left"]) <= 1.0
              and abs(v["r"]["mini"]["left"] - v["r"]["grid"]["left"]) <= 1.0
              for v in ok.values()),
          {k: (v["r"]["headT"]["left"], v["r"]["mini"]["left"], v["r"]["grid"]["left"])
           for k, v in ok.items()})
    check("39. в положении «сверху» первый ряд карточек ПОЛНОСТЬЮ ниже навигации",
          all(v["top0"]["gap"] > 0 for v in ok.values()),
          {k: v["top0"] for k, v in ok.items()})
    check("40. между навигацией и сеткой нормальный зазор (>2px, <60px)",
          all(2 < v["top0"]["gap"] < 60 for v in ok.values()),
          {k: v["top0"]["gap"] for k, v in ok.items()})

    sec("БРАУЗЕР: ГЛАВНОЕ — щель над закреплённой навигацией (41-44)")
    _gap = {k: v["scrolled"]["gapAboveMini"] for k, v in ok.items()}
    check("41. при прокрутке над навигацией НЕТ прозрачной полосы (щель = 0) — именно она "
          "показывала обрезанные верхушки карточек на скриншоте владельца",
          all(abs(g) <= 0.6 for g in _gap.values()), _gap)
    check("42. проверка не вакуумная: область настроек реально прокручивалась",
          all(v["scrolled"]["setTop"] > 50 for v in ok.values()),
          {k: v["scrolled"]["setTop"] for k, v in ok.items()})
    check("43. карточки «Файлы принтеров» и «Сеть и доступ» найдены и их заголовки не обрезаны "
          "сверху областью прокрутки",
          all(len(v["named"]) >= 2
              and all(c["titleTop"] is not None and c["titleTop"] >= v["r"]["sc"]["top"] - 0.5
                      for c in v["named"])
              for v in ok.values()),
          {k: v["named"] for k, v in ok.items()}),
    check("44. аварийный экран загрузки не показан ни в одном сценарии",
          all(not v["bootFallback"] for v in ok.values()),
          {k: v["bootFallback"] for k, v in ok.items()})

    sec("БРАУЗЕР: без ошибок страницы (45-46)")
    _probs = {}
    for k, v in ok.items():
        p = stage.page_problems(v)
        if p:
            _probs[k] = p
    check("45. ошибок консоли, исключений и предупреждений Vue нет ни в одном сценарии",
          not _probs, _probs)
    check("46. язык интерфейса в каждом сценарии — тот, который запрашивали",
          all(v.get("lang") == v.get("wantLang") for v in ok.values()),
          {k: (v.get("wantLang"), v.get("lang")) for k, v in ok.items()})

# ── чипы ──────────────────────────────────────────────────────────────────────────────────────
if _ONLY in ("all", "chips"):
    sec("БРАУЗЕР: все семь чипов (47-52)")
    CH = stage.run(CHIPS_JS, window_size=(1365, 1024), settle_ms=1700) or {}
    _ch = CH.get("chips") or []
    check("47. все шесть чипов нажаты в реальном браузере (2.999: модули уехали на свою вкладку)",
          len(_ch) == 6 and CH.get("chipN") == 6,
          {"нажато": len(_ch), "чипов в DOM": CH.get("chipN"), "errs": CH.get("errs")})
    check("48. после КАЖДОГО чипа заголовок целевой секции ниже закреплённой навигации",
          bool(_ch) and all(c["belowNav"] for c in _ch),
          [{"чип": c["label"], "titleTop": c["titleTop"], "miniBottom": c["miniBottom"]}
           for c in _ch if not c["belowNav"]])
    check("49. после КАЖДОГО чипа заголовок целевой секции виден целиком",
          bool(_ch) and all(c["fullyVisible"] for c in _ch),
          [{"чип": c["label"], "titleTop": c["titleTop"]} for c in _ch if not c["fullyVisible"]])
    check("50. чипы прокручивают ТОЛЬКО область настроек: корень остаётся на нуле",
          bool(_ch) and all(c["docTop"] == 0 for c in _ch),
          [{"чип": c["label"], "docTop": c["docTop"]} for c in _ch if c["docTop"] != 0])
    check("51. верхний бар не сдвинулся за все семь переходов",
          CH.get("hdrTop0") is not None and CH.get("hdrTopEnd") is not None
          and abs(CH["hdrTopEnd"] - CH["hdrTop0"]) <= 0.6,
          (CH.get("hdrTop0"), CH.get("hdrTopEnd")))
    _chp = stage.page_problems(CH) if CH else ["мост не вернул результат"]
    check("52. переходы по чипам не дали ошибок консоли и предупреждений Vue", not _chp, _chp)

# ── рабочие экраны ────────────────────────────────────────────────────────────────────────────
if _ONLY in ("all", "ws"):
    sec("БРАУЗЕР: рабочие экраны (53-57)")
    WS = stage.run(WORKSPACE_JS, window_size=(1365, 1024), settle_ms=1700) or {}
    _sf = [s for s in (WS.get("surfaces") or []) if s.get("found")]
    check("53. открыты и измерены все четыре поверхности (Настройки, Диагностика, Файлы "
          "принтеров, слот после закрытия экрана)", len(_sf) == 4,
          {"найдено": [s["name"] for s in (WS.get("surfaces") or []) if s.get("found")],
           "не найдено": [s["name"] for s in (WS.get("surfaces") or []) if not s.get("found")],
           "errs": WS.get("errs")})
    check("54. ни одна поверхность не заходит под НАРИСОВАННЫЙ верхний бар",
          bool(_sf) and all(s["overlap"] < 0 for s in _sf),
          [{"экран": s["name"], "перекрытие": s["overlap"]} for s in _sf if s["overlap"] >= 0])
    check("55. на каждой поверхности колонка принтеров тоже ниже бара и корень не прокручен",
          bool(_sf) and all(s["leftOverlap"] < 0 and s["docTop"] == 0 and s["bodyTop"] == 0
                            for s in _sf),
          [{"экран": s["name"], "leftOverlap": s["leftOverlap"], "docTop": s["docTop"]}
           for s in _sf if not (s["leftOverlap"] < 0 and s["docTop"] == 0)])
    _hdrs = [s["hdrTop"] for s in _sf]
    check("56. открытие и закрытие рабочих экранов не сдвигает верхний бар",
          bool(_hdrs) and (max(_hdrs) - min(_hdrs)) <= 0.6, _hdrs)
    _wsp = stage.page_problems(WS) if WS else ["мост не вернул результат"]
    check("57. работа с экранами не дала ошибок консоли и предупреждений Vue", not _wsp, _wsp)

# Режим частичного прогона не имеет права стать тихой дырой: при FM_SHELL_ONLY печатаем, что
# именно выполнено, а полный релизный прогон обязан идти без этой переменной.
if _FAST:
    print("\n(режим FM_SHELL_ONLY=%s — выполнен только блок «%s»; релизный прогон идёт без "
          "этой переменной)" % (_ONLY, _ONLY))

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    for n in _fail:
        print("  RED: " + n)
raise SystemExit(1 if _fail else 0)
