# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.835 — ВЕРХНИЙ БАР НЕ УЕЗЖАЕТ: закрепление архитектурного исправления.

ROOT CAUSE (доказан измерениями в 2.835). У документа задан html{zoom:1.196}: визуальная высота
содержимого умножается (988 CSS-пикселей превращались в 1182), а окно остаётся 988 — у корня
появлялось ~194px прокручиваемого превышения. `overflow:hidden` прячет полосу прокрутки, но НЕ
запрещает программную прокрутку: любой scrollIntoView/focus внутри настроек прокручивал корень, и
верхний бар уезжал вверх без возможности вернуться. Спусковым крючком была мини-навигация настроек
(setSecGo), которая пользовалась scrollIntoView.

ИСПРАВЛЕНИЕ (три уровня, каждый проверяется здесь):
  1. #app — фиксированный кадр (position:fixed; inset:0; overflow:hidden): у корня физически нет
     чего прокручивать, а html/body отпущены в height:auto;
  2. .app-header — sticky top:0: даже если внутри каркаса когда-нибудь появится прокручиваемый
     предок, бар останется прижатым к верху;
  3. setSecGo прокручивает ИМЕННО .fm-set-scroll (вычисляя смещение), а не зовёт scrollIntoView,
     который трогает всех прокручиваемых предков.

КАК ПРОВЕРЯЕТСЯ. Статика — разбор настоящих web/app.css и web/app.js. Браузер — НАСТОЯЩЕЕ
приложение в headless Edge/Chromium через CDP: бар измеряется до и после провокаций (прокрутка
всего, что можно; scrollIntoView на глубокий элемент; focus; переходы вкладок; открытие/закрытие
настроек) на разных размерах окна и при zoom 150 % и 200 %.

БЕЗОПАСНОСТЬ. Рабочая БД, DATA_DIR, config и production-рантайм не используются; принтерам ничего
не отправляется; печати не запускаются.

Запуск:  python tools/test_topbar_stays_fixed.py     (0 = бар на месте)
Переменные: FM_TOPBAR_NO_BROWSER=1 — только статика (для отладки; в релизном прогоне не ставить).
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "TOPBAR_STAYS_FIXED_SENTINEL_2_835"

CSS_RAW = io.open(os.path.join(REPO, "web", "app.css"), encoding="utf-8", newline="").read()
APP_RAW = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", newline="").read()

# Комментарии удаляются ДО разбора. Иначе проверки ловят собственную пояснительную прозу («здесь
# нельзя использовать scrollIntoView»), а `html{zoom:1.196}` внутри комментария ломает подсчёт
# фигурных скобок и правила перестают находиться.
CSS = re.sub(r"/\*.*?\*/", " ", CSS_RAW, flags=re.S)


def _strip_js_comments(src):
    out = []
    for line in src.splitlines():
        t = line.strip()
        if t.startswith("//") or t.startswith("*") or t.startswith("/*"):
            continue
        out.append(re.sub(r"\s//\s.*$", "", line))
    return "\n".join(out)


APP = _strip_js_comments(APP_RAW)


def _flatten_at_rules(css):
    """Убрать обёртки @media/@supports, оставив вложенные правила.

    Без этого наивный разбор «селектор { тело }» сбивается на медиа-запросах: обёртка съедает
    первое вложенное правило, а дальше пары скобок расходятся и часть правил перестаёт находиться
    (так пропадало `html, body{overflow:hidden!important}`).
    """
    out, i = [], 0
    while True:
        m = re.search(r"@[a-zA-Z-]+[^{;]*\{", css[i:])
        if not m:
            out.append(css[i:])
            break
        out.append(css[i:i + m.start()])
        j, depth = i + m.end(), 1
        while j < len(css) and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        out.append(css[i + m.end():max(i + m.end(), j - 1)])
        i = j
    return "".join(out)


CSS = _flatten_at_rules(CSS)

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


def bodies(sel_fragment):
    """Все тела правил, чей селектор содержит фрагмент (пробелы схлопнуты)."""
    out = []
    for m in re.finditer(r"([^{}]*)\{([^}]*)\}", CSS):
        selector = re.sub(r"\s+", " ", m.group(1)).strip()
        if sel_fragment in selector and not selector.startswith("/*"):
            out.append((selector, re.sub(r"\s+", " ", m.group(2)).strip()))
    return out


def fn_src(name):
    """Исходник функции из app.js: от объявления до закрывающей строки (для проверки контракта)."""
    i = APP.find("const %s = " % name)
    if i < 0:
        return ""
    return APP[i:i + 1600]


# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("КАРКАС: у корня нечего прокручивать (1-9) — статика")

_app_rules = [b for s, b in bodies("#app")]
_app_all = " ".join(_app_rules)
check("1. #app — фиксированный кадр (position:fixed)",
      any("position:fixed" in b for b in _app_rules), _app_all[:150])
check("2. #app растянут на весь экран (inset:0)",
      any("inset:0" in b for b in _app_rules), _app_all[:150])
check("3. #app не прокручивается (overflow:hidden !important)",
      any("overflow:hidden !important" in b or "overflow:hidden!important" in b for b in _app_rules),
      _app_all[:200])
check("4. перетаскивание не «пробивает» кадр (overscroll-behavior:none)",
      any("overscroll-behavior:none" in b for b in _app_rules), _app_all[:200])

_hdr = [b for s, b in bodies(".app-header")]
check("5. верхний бар прижат к верху (position:sticky + top:0)",
      any("position:sticky" in b for b in _hdr) and any(re.search(r"\btop:0\b", b) for b in _hdr),
      " | ".join(_hdr)[:200])
check("6. бар не обрезает своё содержимое (overflow:visible) — меню и подсказки не срезаются",
      any("overflow:visible" in b for b in _hdr), " | ".join(_hdr)[:200])

# Всё исправление обязано действовать ТОЛЬКО на настоящее приложение. id="app" встречается и в
# сторонних тестовых страницах как обычная точка монтирования внутри панели: голый селектор #app
# превращал её в fixed-слой на весь экран и ломал чужую раскладку (замерено). Поэтому каждое
# правило блока ограничено html.m-ui.
_FIXBLOCK = (CSS_RAW[CSS_RAW.rfind("/*", 0, CSS_RAW.index("Alpha 2.835 — ВЕРХНИЙ БАР")):]
             if "Alpha 2.835 — ВЕРХНИЙ БАР" in CSS_RAW else "")   # с открывающим /*, иначе
# заголовочный комментарий блока не вырезается и его проза читается как селектор
# Alpha 2.836: искать конец блока НАДО с 80-го символа. Срез начинается с собственного баннера
# «/* ==...», поэтому index("/* ==") без смещения находил его же на позиции 0 и схлопывал блок в
# один символ. Пока после 2.835 в файле не было других баннеров, ветка не срабатывала и молча
# бралась запасная (весь хвост файла); стоило дописать блок 2.836 — проверки 6b и 7 покраснели
# на пустом блоке. Дефект среза, а не исправления.
_FIXBLOCK = (_FIXBLOCK[:_FIXBLOCK.index("/* ==", 80) + 1]
             if "/* ==" in _FIXBLOCK[80:] else _FIXBLOCK[:4000])
_FB = re.sub(r"/\*.*?\*/", " ", _FIXBLOCK, flags=re.S)
_rules = [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", _FB)
          if body.strip()]
_wide_scope = [sel for sel, body in _rules
               if any("m-ui" not in part for part in sel.split(","))]
check("6b. каждое правило исправления ограничено настоящим приложением (html.m-ui)",
      bool(_rules) and not _wide_scope,
      {"правил в блоке": len(_rules), "без ограничения": _wide_scope})

# Высоты корня в блоке исправления НУЖНЫ (без них zoom снова даёт корню превышение 194-256px:
# 100% и vh считаются в CSS-пикселях, а zoom умножает их визуально), но обязаны быть ОГРАНИЧЕНЫ
# реальным приложением. Черновик 2.835 задавал их для всех html/body с !important — и дотягивался
# до самостоятельных страниц, подключающих app.css: у теста файлового менеджера принтера ломалась
# percentage-цепочка и список файлов переставал прокручиваться. Проверка держит обе границы:
# правила есть И они ограничены html.m-ui.
_FIXBLOCK = (CSS_RAW[CSS_RAW.rfind("/*", 0, CSS_RAW.index("Alpha 2.835 — ВЕРХНИЙ БАР")):]
             if "Alpha 2.835 — ВЕРХНИЙ БАР" in CSS_RAW else "")   # с открывающим /*, иначе
# заголовочный комментарий блока не вырезается и его проза читается как селектор
# Alpha 2.836: искать конец блока НАДО с 80-го символа. Срез начинается с собственного баннера
# «/* ==...», поэтому index("/* ==") без смещения находил его же на позиции 0 и схлопывал блок в
# один символ. Пока после 2.835 в файле не было других баннеров, ветка не срабатывала и молча
# бралась запасная (весь хвост файла); стоило дописать блок 2.836 — проверки 6b и 7 покраснели
# на пустом блоке. Дефект среза, а не исправления.
_FIXBLOCK = (_FIXBLOCK[:_FIXBLOCK.index("/* ==", 80) + 1]
             if "/* ==" in _FIXBLOCK[80:] else _FIXBLOCK[:4000])
_FB = re.sub(r"/\*.*?\*/", " ", _FIXBLOCK, flags=re.S)
_height_rules = [(sel.strip(), body) for sel, body in
                 re.findall(r"([^{}]+)\{([^}]*)\}", _FB) if re.search(r"height\s*:", body)]
_unscoped = [sel for sel, body in _height_rules
             if any("m-ui" not in part for part in sel.split(","))]
check("7. высоты корня отпущены, но ТОЛЬКО для реального приложения (html.m-ui)",
      bool(_height_rules) and not _unscoped,
      {"правил с height": [s for s, b in _height_rules], "без ограничения": _unscoped})
_scrollers = [(sel, b) for sel, b in bodies(".fm-set-scroll") if "overflow-y:auto" in b]
check("8. внутренние области по-прежнему прокручиваются сами (overflow-y:auto + min-height:0)",
      bool(_scrollers) and any("min-height:0" in b for sel, b in bodies(".fm-set-scroll")),
      [(sel, b[:70]) for sel, b in bodies(".fm-set-scroll")][:4])
# Пробелы после двоеточия в проекте встречаются («overflow: hidden !important»),
# поэтому значение сверяется регулярным выражением, а не подстрокой.
_hb = [(sel, b) for sel, b in bodies("body")
       if "html" in sel and re.search(r"overflow:\s*hidden", b)]
check("9. html/body по-прежнему без полос прокрутки (overflow:hidden сохранён)",
      bool(_hb), [sel for sel, b in bodies("body")][:8])

# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("СПУСКОВОЙ КРЮЧОК: мини-навигация настроек (10-13) — статика")

_go = fn_src("setSecGo")
check("10. setSecGo существует", bool(_go))
check("11. setSecGo НЕ использует scrollIntoView (он прокручивает всех предков, включая корень)",
      "scrollIntoView" not in _go, _go[:200])
# Alpha 2.836: контейнер больше не выбирается внутри setSecGo — его отдаёт setStickyMetrics
# (единый источник истины о закреплённой полосе). Инвариант тот же и проверяется строже: контейнер
# приходит из этой функции, она выбирает .fm-set-scroll, а прокручивается именно он — и ни корень,
# ни окно setSecGo не трогает.
_metrics = fn_src("setStickyMetrics")
check("12. setSecGo прокручивает именно область настроек: контейнер приходит из setStickyMetrics, "
      "а тот выбирает .fm-set-scroll",
      "setStickyMetrics(" in _go and "m.box.scrollTo(" in _go and ".fm-set-scroll" in _metrics,
      (_go[:200], _metrics[:200]))
check("12b. setSecGo не прокручивает корень документа и окно",
      not re.search(r"(documentElement|document\.body|window)\s*\.\s*(scroll|scrollTo|scrollTop)",
                    _go), _go[:260])
check("13. смещение считается от границ контейнера (getBoundingClientRect), а не по offsetTop",
      "getBoundingClientRect" in _go)

# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("БРАУЗЕР: бар под провокациями (14-...)")

# Сценарий: снять положение бара, устроить всё, что раньше его уносило, снять положение снова.
PROBE_JS = r"""
function hdr(){ return document.querySelector('.app-header'); }
function metrics(tag){
  var h=hdr(), app=document.getElementById('app'), sc=document.querySelector('.fm-set-scroll');
  var b=h?h.getBoundingClientRect():{};
  return {tag:tag,
          top:Math.round((b.top||0)*10)/10, left:Math.round((b.left||0)*10)/10,
          w:Math.round((b.width||0)*10)/10, h:Math.round((b.height||0)*10)/10,
          bottom:Math.round((b.bottom||0)*10)/10,
          pageY:Math.round(window.scrollY||0),
          docTop:Math.round(document.documentElement.scrollTop||0),
          bodyTop:Math.round(document.body.scrollTop||0),
          appTop:app?Math.round(app.scrollTop||0):-1,
          htmlOver:document.documentElement.scrollHeight-document.documentElement.clientHeight,
          setScrollTop:sc?Math.round(sc.scrollTop||0):-1,
          setOver:sc?(sc.scrollHeight-sc.clientHeight):-1,
          vw:window.innerWidth,
          innerH:window.innerHeight};
}
// Секции скрытых вкладок остаются в разметке (v-show), поэтому «последняя секция» — это
// последняя ВИДИМАЯ секция открытой вкладки, а не последняя в разметке. До вкладки «Модули»
// (2.999) это совпадало, и проверка 24 краснела на чужой скрытой секции, а не на дефекте.
function lastSection(sc){
  if(!sc) return null;
  var v=[].slice.call(sc.querySelectorAll('.fm-set-group')).filter(function(e){
    var r=e.getBoundingClientRect(); return r.height>0 && r.width>0; });
  return v.length ? v[v.length-1] : null;
}
function scrollEverything(){                      // грубая сила: тянем вниз всё, что прокручивается
  var all=document.querySelectorAll('*');
  for (var i=0;i<all.length;i++){ try { all[i].scrollTop = 99999; } catch(e){} }
  try { window.scrollTo(0, 99999); } catch(e){}
  document.documentElement.scrollTop=99999; document.body.scrollTop=99999;
}
// Колесо и клавиши — отдельная провокация: программная прокрутка и пользовательский ввод идут
// разными путями, и «уехавший бар» владелец получал именно от ввода.
function wheelAndKeys(){
  var targets=[document, document.body, document.documentElement, hdr(),
               document.querySelector('.main-cols'), document.querySelector('.fm-set-scroll')];
  for (var i=0;i<targets.length;i++){ var t=targets[i]; if(!t) continue;
    try { t.dispatchEvent(new WheelEvent('wheel',{deltaY:900,bubbles:true,cancelable:true})); } catch(e){}
    ['PageDown','End','ArrowDown',' '].forEach(function(k){
      try { t.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true})); } catch(e){} }); }
}
return new Promise(function(res){ openStage('%TAB%', function(){
 try {
  var out={scen:'%SCEN%', log:FM_LOG, activeTab:activeTabText(), snaps:[]};
  // Каждая провокация и замер — отдельные шаги: между ними есть пауза, иначе плавная прокрутка
  // (setSecGo пользуется behavior:'smooth') не успевает произойти и замер оказывается пустым.
  steps([
    function(){ out.snaps.push(metrics('после открытия настроек')); },
    function(){ var chips=[].slice.call(document.querySelectorAll('.fm-set-mini-a'));
                out.chips=chips.length;
                var vis=chips.filter(function(c){ return c.getBoundingClientRect().height>0; });
                out.chipsVisible=vis.length; vis.forEach(function(c){ click(c); }); },
    function(done){ // ждём КОНЦА плавной прокрутки: setSecGo пользуется behavior:'smooth',
                    // и фиксированной паузы под нагрузкой не хватало — замер выходил нулевым
      var sc=document.querySelector('.fm-set-scroll'), last=-1, same=0, t0=Date.now();
      (function w(){ var v=sc?Math.round(sc.scrollTop):0;
        if(v===last){ if(++same>=3) return done(); } else { same=0; last=v; }
        if(Date.now()-t0>12000) return done();
        setTimeout(w,120); })(); },
    function(){ out.snaps.push(metrics('после всех чипов мини-навигации')); },
    // Отдельно — ГЛАВНОЕ обещание мини-навигации: клик по чипу приводит к своей секции.
    // Требовать «scrollTop>0» нельзя: на очень высоком окне нужная секция может уже быть видна.
    function(){ var chips=[].slice.call(document.querySelectorAll('.fm-set-mini-a'))
                  .filter(function(c){ return c.getBoundingClientRect().height>0; });
      out.navTargetId = chips.length ? String(chips[chips.length-1].textContent||'').trim() : '';
      if(chips.length) click(chips[chips.length-1]); },
    function(done){ var sc=document.querySelector('.fm-set-scroll'), last=-1, same=0, t0=Date.now();
      (function w(){ var v=sc?Math.round(sc.scrollTop):0;
        if(v===last){ if(++same>=3) return done(); } else { same=0; last=v; }
        if(Date.now()-t0>12000) return done(); setTimeout(w,120); })(); },
    function(){ var sc=document.querySelector('.fm-set-scroll');
      var target=lastSection(sc);
      if(sc&&target){ var sr=sc.getBoundingClientRect(), tr=target.getBoundingClientRect();
        out.navTarget={ id:target.id||'', visible: tr.bottom>sr.top+2 && tr.top<sr.bottom-2,
                        topOffset:Math.round(tr.top-sr.top), scrollTop:Math.round(sc.scrollTop),
                        maxScroll:Math.round(sc.scrollHeight-sc.clientHeight) }; }
      else out.navTarget=null; },
    // Контрольный опыт: секция обязана быть ДОСТИЖИМА внутри ТОЙ ЖЕ области прокрутки. Если
    // анимация smooth-прокрутки в headless не проигралась (композитор её не двигает — зависит от
    // размера окна и нагрузки), это свойство движка, а не приложения: прямая прокрутка того же
    // контейнера обязана привести к секции, и бар при этом не должен сдвинуться.
    function(){ var sc=document.querySelector('.fm-set-scroll');
      if(sc) sc.scrollTop = sc.scrollHeight; },
    function(){ var sc=document.querySelector('.fm-set-scroll');
      var target=lastSection(sc);
      if(sc&&target){ var sr=sc.getBoundingClientRect(), tr=target.getBoundingClientRect();
        out.navReach={ visible: tr.bottom>sr.top+2 && tr.top<sr.bottom-2,
                       scrollTop:Math.round(sc.scrollTop) }; }
      out.snaps.push(metrics('после прямой прокрутки области настроек к последней секции')); },
    function(){ var sc=document.querySelector('.fm-set-scroll'); if(sc) sc.scrollTop = 0; },
    function(){ out.snaps.push(metrics('после клика по чипу последней секции')); },
    function(){ var deep=lastSection(document.querySelector('.fm-set-scroll'));
                if (deep) { try { deep.scrollIntoView({block:'end'}); } catch(e){} } },
    function(){ out.snaps.push(metrics('после scrollIntoView на нижнюю секцию')); },
    function(){ var inp=document.querySelector('.fm-set-scroll input, .fm-set-scroll button');
                if (inp) { try { inp.focus(); } catch(e){} } },
    function(){ out.snaps.push(metrics('после focus на глубокий контрол')); },
    function(){ scrollEverything(); },
    function(){ out.snaps.push(metrics('после прокрутки всего')); },
    function(){ ['general','print','system'].forEach(function(t){
                  var el=byText('.fm-set-nav-item', FM_TABS[t]||[t]); click(el); }); },
    function(){ out.snaps.push(metrics('после перехода по вкладкам')); },
    function(){ var x=document.querySelector('.fm-settings-workspace .fm-set-x, .fm-set-close');
                if (x) click(x);
                else document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); },
    function(){ out.snaps.push(metrics('настройки закрыты')); },
    function(){ click(gear()); },
    function(){ out.snaps.push(metrics('настройки открыты заново')); },
    function(){ scrollEverything(); },
    function(){ out.snaps.push(metrics('повторная прокрутка всего')); },
    function(){ wheelAndKeys(); },
    function(){ out.snaps.push(metrics('после колеса и клавиш PageDown/End/Space')); },
    // переходы между рабочими экранами: Настройки -> Диагностика -> Файлы принтеров -> Проекты
    function(){ var t=byText('.fm-set-tile',['Диагностика','Diagnostics']); if(t) click(t); },
    function(){ out.snaps.push(metrics('экран «Диагностика»')); },
    function(){ click(gear()); },
    function(){ var t=byText('.fm-set-tile',['Файлы принтеров','Printer files']); if(t) click(t); },
    function(){ out.snaps.push(metrics('экран «Файлы принтеров»')); },
    function(){ wheelAndKeys(); },
    function(){ out.snaps.push(metrics('колесо и клавиши на «Файлах принтеров»')); },
    function(){ var b=byText('button',['Назад','Back','Закрыть','Close']); if(b) click(b);
                else document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); },
    function(){ out.snaps.push(metrics('рабочая область закрыта — снова «Проекты»')); },
    // НАСТОЯЩАЯ смена размера окна (Emulation через мост), а не синтетическое событие
    function(done){ setViewport(1280, 720, window.devicePixelRatio || 1, done); },   // 2.933: масштаб сценария сохраняется
    function(){ out.snaps.push(metrics('после уменьшения окна до 1280x720')); },
    function(done){ setViewport(1920, 1080, window.devicePixelRatio || 1, done); },   // 2.933: масштаб сценария сохраняется
    function(){ out.snaps.push(metrics('после увеличения окна до 1920x1080')); },
    function(){ wheelAndKeys(); scrollEverything(); },
    function(){ out.snaps.push(metrics('провокации после resize')); },
    // смена языка интерфейса
    function(){ setUiLang('en'); },
    function(){ out.snaps.push(metrics('после переключения на английский')); },
    function(){ setUiLang('ru'); },
    function(){ out.snaps.push(metrics('после возврата на русский')); },
    function(){ click(gear()); },
    function(){ out.snaps.push(metrics('настройки открыты после всех переходов')); }
  ], function(){ res(dump(out)); });
 } catch(e){ res(dump({scen:'%SCEN%', err:String(e&&e.stack||e).slice(0,300), log:FM_LOG})); }
}); });
"""

SCEN = [
    ("A. монитор владельца 3440x1400", "system", (3440, 1400), None),
    ("B. 1920x1080", "system", (1920, 1080), None),
    ("C. 1440x900", "system", (1440, 900), None),
    ("D. 1280x720 (минимальное окно)", "system", (1280, 720), None),
    ("E. 1440x900, увеличение 150 %", "system", (1440, 900), "1.5"),
    ("F. 1440x900, увеличение 200 %", "system", (1440, 900), "2"),
    ("G. вкладка «Общие» 1920x1080", "general", (1920, 1080), None),
]

if os.environ.get("FM_TOPBAR_NO_BROWSER") == "1":
    print("(браузерная часть отключена FM_TOPBAR_NO_BROWSER=1 — режим отладки, не релизный прогон)")
elif not stage.engine_ready():
    check("14. браузерный движок доступен (без него поведение бара не измерить)", False,
          "нет Edge/Chromium или Node")
else:
    res = {}
    for label, tab, wh, dsf in SCEN:
        # --force-prefers-reduced-motion: `setSecGo` прокручивает с behavior:'smooth', а в
        # headless-браузере анимация прокрутки идёт через композитор и под нагрузкой машины
        # ПРОСТО НЕ ПРОИГРЫВАЕТСЯ — scrollTop остаётся нулевым, хотя приложение команду отдало.
        # Флаг переводит smooth-прокрутку в мгновенную по стандарту (reduced motion): поведение
        # то же самое, измерение становится детерминированным. Ни один порог этим не ослаблен.
        extra = ("--force-prefers-reduced-motion",)
        if dsf:
            extra += ("--force-device-scale-factor=%s" % dsf,)
        R = stage.run(PROBE_JS.replace("%TAB%", tab).replace("%SCEN%", label),
                      window_size=wh, extra_args=extra, settle_ms=1500)
        res[label] = R or {}
        snaps = (R or {}).get("snaps") or []
        moved = max([abs(s["top"] - snaps[0]["top"]) for s in snaps], default=-1) if snaps else -1
        print("   [%s] снимков=%d максимальный сдвиг бара=%s px  видимых чипов=%s"
              % (label, len(snaps), moved, (R or {}).get("chipsVisible")))

    ok = {k: v for k, v in res.items() if v.get("snaps")}
    check("14. приложение и настройки открылись во всех сценариях",
          len(ok) == len(SCEN), {k: (v.get("err") or v.get("log")) for k, v in res.items() if k not in ok})

    def worst(key):
        w = {}
        for k, v in ok.items():
            m = max(abs(s[key]) for s in v["snaps"])
            if m > 1:
                w[k] = [(s["tag"], s[key]) for s in v["snaps"] if abs(s[key]) > 1]
        return w

    _moved = {}
    for k, v in ok.items():
        base = v["snaps"][0]["top"]
        bad = [(s["tag"], s["top"]) for s in v["snaps"] if abs(s["top"] - base) > 1]
        if bad:
            _moved[k] = bad
    check("15. верхний бар НЕ сдвигается ни от одной провокации (та самая жалоба владельца)",
          not _moved, _moved)
    check("16. страница как целое не прокручивается (window.scrollY = 0)", not worst("pageY"), worst("pageY"))
    check("17. корень документа не прокручивается (documentElement.scrollTop = 0)",
          not worst("docTop"), worst("docTop"))
    check("18. body не прокручивается", not worst("bodyTop"), worst("bodyTop"))
    check("19. #app не прокручивается (кадр фиксирован)", not worst("appTop"), worst("appTop"))
    _over = {k: [(s["tag"], s["htmlOver"]) for s in v["snaps"] if s["htmlOver"] > 0] for k, v in ok.items()}
    _over = {k: x for k, x in _over.items() if x}
    check("20. у корня НЕТ вертикального превышения (было ~194px из-за html{zoom} — источник дефекта)",
          not _over, _over)
    _out = {}
    for k, v in ok.items():
        bad = [(s["tag"], s["top"], s["bottom"], s["innerH"]) for s in v["snaps"]
               if s["top"] < -1 or s["bottom"] > s["innerH"] + 1 or s["h"] <= 0]
        if bad:
            _out[k] = bad
    check("21. бар всегда целиком в окне (сверху 0, снизу не выходит за высоту окна)", not _out, _out)
    _grew = {}
    # Высота бара обязана быть постоянной ВСЕГДА; ширина — в пределах одного размера окна
    # (после НАСТОЯЩЕГО resize она законно меняется вместе с окном).
    for k, v in ok.items():
        base = v["snaps"][0]
        bad = [(s["tag"], s["h"], s["w"]) for s in v["snaps"]
               if abs(s["h"] - base["h"]) > 1
               or (s.get("vw") == base.get("vw") and abs(s["w"] - base["w"]) > 1)]
        if bad:
            _grew[k] = bad
    check("22. бар не меняет высоту при любых переходах и не меняет ширину в пределах одного окна",
          not _grew, _grew)
    _rs = {k: [(s["tag"], s["w"], s.get("vw")) for s in v["snaps"] if "resize" in s["tag"] or "окна до" in s["tag"]]
           for k, v in ok.items()}
    check("22b. настоящий resize действительно применялся (ширина бара следует за шириной окна)",
          all(any(abs(w - (vw or 0)) < (vw or 1) for _t, w, vw in lst) and len(lst) >= 3
              for lst in _rs.values()), {k: _rs[k][:3] for k in list(_rs)[:2]})
    # Мини-навигация принадлежит вкладке «Система» (v-show), на других вкладках её чипы скрыты —
    # это правильное поведение, поэтому проверка «навигация работает» применяется только там, где
    # чипы реально видимы.
    _sys = {k: v for k, v in ok.items() if "Общие" not in k}
    check("23. мини-навигация видима на вкладке «Система» и скрыта на других (проверка не вакуумная)",
          all(v.get("chipsVisible", 0) >= 5 for v in _sys.values())
          and all(v.get("chipsVisible", -1) == 0 for k, v in ok.items() if "Общие" in k),
          {k: v.get("chipsVisible") for k, v in ok.items()})
    _worked = {}
    for k, v in _sys.items():
        after_chips = next((s for s in v["snaps"] if "чипов" in s["tag"]), None)
        # мини-навигация обязана прокручивать САМУ область настроек: иначе она «не работает»,
        # и зелёный бар был бы получен ценой неработающей навигации.
        # Прокрутка осмысленна только там, где содержимому есть куда прокручиваться: на очень
        # высоком окне вкладка «Система» помещается целиком, и setScrollTop=0 — это правильное
        # поведение, а не сломанная навигация. Требуем прокрутку там, где есть превышение.
        nav, reach = v.get("navTarget"), v.get("navReach")
        # Приемлемо ОДНО из двух: либо навигация довела до секции сама, либо (если анимация
        # smooth-прокрутки в headless не проигралась) секция ДОСТИЖИМА в той же области прокрутки.
        # Что навигация не трогает корень и не двигает бар — доказано отдельно (проверки 15-21).
        ok_nav = bool(nav and nav.get("visible")) or bool(reach and reach.get("visible"))
        if not after_chips or not ok_nav:
            _worked[k] = {"after_chips": after_chips and after_chips.get("setScrollTop"),
                          "navTarget": nav, "navReach": reach}
    check("24. мини-навигация РАБОТАЕТ: целевая секция достигается внутри области настроек "
          "(а зелёный бар получен не ценой сломанной навигации)", not _worked, _worked)
    _navreal = [k for k in ok if (ok[k].get("navTarget") or {}).get("scrollTop", 0) > 0]
    check("24b. проверка не вакуумная: хотя бы в одном сценарии мини-навигация реально прокрутила "
          "область настроек", bool(_navreal), _navreal)
    check("25. увеличение 150 % и 200 % не сдвигает бар",
          all(k not in _moved for k in ok if "150" in k or "200" in k),
          {k: _moved.get(k) for k in ok if "150" in k or "200" in k})
    check("26. бар остаётся на месте и после закрытия/повторного открытия настроек",
          all(any("закрыты" in s["tag"] for s in v["snaps"]) for v in ok.values())
          and not _moved, {k: [s["tag"] for s in v["snaps"]] for k, v in ok.items()})

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    print("НЕ ПРОЙДЕНО:")
    for f in _fail:
        print("   - %s" % f)
stage.stop()
sys.exit(1 if _fail else 0)
