# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.835 — СИСТЕМА КОМПОНОВКИ экрана настроек: порядок, спокойная сетка, единый ритм.

ЧТО ЗАЩИЩАЕТ. Владелец видел «блоки расставлены хаотично, глаза разбегаются». Измерения на его
реальном мониторе 3440x1440 показали две причины:
  (1) сетка auto-fit без ограничения меры разворачивала секции в ЧЕТЫРЕ колонки узких карточек,
      а «широкие» секции шли полосой на 2585px;
  (2) у .fm-chk стояло flex:1 1 240px — запись для строки, но флажки лежат в flex-КОЛОНКЕ, где
      240px становятся базовой ВЫСОТОЙ: каждая строка-флажок раздувалась до 315-519px и внутри
      карточек появлялись огромные пустоты.
Тест закрепляет исправленное состояние: колонок никогда больше двух, мера страницы ограничена,
ряды ровные, отступы одинаковые, строки-флажки нормальной высоты, порядок секций логический.

КАК ПРОВЕРЯЕТСЯ. Статика — разбор настоящих web/app.css и web/index.html. Браузер — НАСТОЯЩЕЕ
приложение в headless Edge/Chromium через CDP (tools/_fm_ui_stage.py) на пяти размерах окна,
включая 3440x1400; редакция принудительно pro, иначе секция «Доступ и аудит» не рендерится.

БЕЗОПАСНОСТЬ. Рабочая БД, DATA_DIR, config и production-рантайм не используются; принтерам ничего
не отправляется; печати не запускаются.

Запуск:  python tools/test_settings_layout_system.py      (0 = раскладка в порядке)
Переменные: FM_LAYOUT_NO_BROWSER=1 — только статика (для отладки; в релизном прогоне не ставить).
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "SETTINGS_LAYOUT_SYSTEM_SENTINEL_2_835"

CSS = io.open(os.path.join(REPO, "web", "app.css"), encoding="utf-8", newline="").read()
HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8", newline="").read()

_i = HTML.index('<div class="fm-set-title">')
SET = HTML[_i:HTML.index("</section>", _i)]

_pass, _fail = [0], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:240]) if detail else ""))


def sec(t):
    print("\n--- %s ---" % t)


def rule(sel):
    """Тело правила по ТОЧНОМУ селектору (первое вхождение).

    Пробелы внутри тела СХЛОПЫВАЮТСЯ до одного, а не удаляются: иначе `flex:0 0 auto`
    превратился бы в `flex:00auto` и проверка стала бы ложно-красной.
    """
    pat = re.escape(sel).replace(r"\ ", r"\s*")
    m = re.search(pat + r"\s*\{([^}]*)\}", CSS)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


# Логический порядок секций вкладки «Система»: сначала инструменты (действия), затем доступ к
# принтерам и сети, затем данные и права, в конце — обслуживание (резервная копия) и расширения.
#  2.999: модули уехали на свою вкладку — в «Системе» их больше нет.
SYSTEM_ORDER = ["fm-sec-tools", "fm-sec-pf", "fm-sec-net", "fm-sec-storage",
                "fm-sec-acc", "fm-sec-backup"]
#  Вкладка «Модули»: список (во всю ширину), выбор кнопок для бара и установка.
#  3.000: между списком и выбором кнопок ядро рисует ЯЧЕЙКИ ВСТРОЕННЫХ НАСТРОЕК модулей —
#  по одной на модуль, объявивший settings_entry. Их id вида fm-sec-modcfg-<id> здесь не
#  перечисляются: состав зависит от того, что установлено, и проверяется отдельным набором.
MODULES_ORDER = ["fm-sec-modules", "fm-sec-modbar", "fm-sec-modinstall"]
TAB_ORDER = {"system": SYSTEM_ORDER, "modules": MODULES_ORDER}
# Полосой на всю ширину идут только крупные секции, у которых внутри своя сетка/таблица.
WIDE_EXPECTED = {"fm-sec-tools", "fm-sec-backup", "fm-sec-modules"}   # 2.999: список модулей остаётся полосой

# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("МЕРА СТРАНИЦЫ И СЕТКА (1-12) — статика")

MEASURE_SEL = ".fm-set-scroll > .fm-set-grid"
_measure_rule = rule(MEASURE_SEL)
_m = re.search(r"--fm-set-measure:\s*(\d+)px", CSS)
check("1. мера страницы задана переменной --fm-set-measure",
      bool(_m) and 700 <= int(_m.group(1)) <= 1400, _m.group(0) if _m else "нет переменной")
check("2. мера применена к сетке (max-width), иначе на ultrawide карточки растягиваются полосой",
      "max-width:var(--fm-set-measure)" in _measure_rule, _measure_rule[:120])
_head_mini = re.search(r"\.fm-set-scroll\s*>\s*\.fm-set-head,\s*\.fm-set-scroll\s*>\s*\.fm-set-mini,", CSS)
check("3. заголовок раздела и мини-навигация ограничены той же мерой (одна вертикаль)",
      bool(_head_mini))
check("4. в правиле меры есть width:100% (без него flex-колонка мерит по содержимому и даёт h-scroll)",
      "width:100%" in _measure_rule, _measure_rule[:120])
check("5. в правиле меры есть box-sizing:border-box (глобального border-box в проекте нет)",
      "box-sizing:border-box" in _measure_rule, _measure_rule[:140])
check("6. мера центрирована (margin-left/right:auto)",
      "margin-left:auto" in _measure_rule and "margin-right:auto" in _measure_rule)

_grid = rule(".fm-set-grid")
check("7. колонки задаются auto-fit с min() — порог 1<->2 не зависит от ширины ОКНА",
      "repeat(auto-fit,minmax(min(" in _grid, _grid[:140])
_mm = re.search(r"minmax\(min\((\d+)px,100%\),1fr\)", _grid)
check("8. минимальная ширина колонки такова, что колонок не больше двух при заданной мере",
      bool(_mm) and _m is not None
      and (int(_m.group(1)) + 12) // (int(_mm.group(1)) + 12) == 2,
      "мера=%s min=%s" % (_m.group(1) if _m else "?", _mm.group(1) if _mm else "?"))
check("9. ряды выровнены по высоте (align-items:stretch) — без «ступенек»",
      "align-items:stretch" in _grid, _grid[:140])
check("10. карточка растягивается на всю высоту ряда (height:100%)",
      "height:100%" in rule(".fm-set-grid > .fm-set-group"))
check("11. широкая секция занимает всю строку сетки (grid-column:1/-1)",
      "grid-column:1/-1" in rule(".fm-set-sec-wide"))
_chk = rule(".fm-chk")
check("12. строка-флажок НЕ имеет базовой высоты (flex:0 0 auto) — иначе пустоты в карточках",
      "flex:0 0 auto" in _chk and "240px" not in _chk, _chk[:140])

# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("ПОРЯДОК И ГРУППИРОВКА СЕКЦИЙ (13-18) — статика")

_ids = re.findall(r'<div [^>]*class="fm-set-group[^"]*"[^>]*id="(fm-sec-[a-z]+)"', SET)
_ids_any = re.findall(r'id="(fm-sec-[a-z]+)"', SET)
check("13. у каждой секции вкладок «Система» и «Модули» есть свой id (нужен мини-навигации)",
      sorted(set(_ids_any)) == sorted(SYSTEM_ORDER + MODULES_ORDER), sorted(set(_ids_any)))
check("14. порядок секций в разметке — логический (инструменты -> доступ -> данные -> обслуживание)",
      [i for i in _ids_any if i in SYSTEM_ORDER] == SYSTEM_ORDER, _ids_any)
check("14б. 2.999: на вкладке «Модули» сначала список, потом установка",
      [i for i in _ids_any if i in MODULES_ORDER] == MODULES_ORDER, _ids_any)

_wide_ids = set()
for m in re.finditer(r'<div ([^>]*class="fm-set-group[^"]*"[^>]*)>', SET):
    a = m.group(1)
    idm = re.search(r'id="(fm-sec-[a-z]+)"', a)
    if idm and "fm-set-sec-wide" in a:
        _wide_ids.add(idm.group(1))
check("15. полосой на всю ширину помечены только крупные секции",
      _wide_ids == WIDE_EXPECTED, sorted(_wide_ids))
_nav_targets = re.findall(r"setSecGo\('(fm-sec-[a-z]+)'\)", SET)
check("16. мини-навигация ведёт ровно к секциям «Системы» и в том же порядке",
      _nav_targets == SYSTEM_ORDER, _nav_targets)
check("17. секции-пары стоят рядом по смыслу (файлы принтеров + сеть, хранение + доступ)",
      SYSTEM_ORDER.index("fm-sec-pf") + 1 == SYSTEM_ORDER.index("fm-sec-net")
      and SYSTEM_ORDER.index("fm-sec-storage") + 1 == SYSTEM_ORDER.index("fm-sec-acc"))
check("18. каждая вкладка имеет заголовок с описанием (заголовок -> описание -> секции)",
      SET.count('class="fm-set-head-t"') >= 3 and SET.count('class="fm-set-head-d"') >= 3,
      "t=%d d=%d" % (SET.count('class="fm-set-head-t"'), SET.count('class="fm-set-head-d"')))

# ══════════════════════════════════════════════════════════════════════════════════════════════
sec("БРАУЗЕР: реальные измерения раскладки (19-...)")

MEASURE_JS = r"""
return new Promise(function(res){ openStage('%TAB%', function(){
  var __lang = %LANG%;
 try {
  var out={tab:'%TAB%', log:FM_LOG, activeTab:activeTabText(), uiLang:uiLang(), wantLang:__lang, errs:[]};
  var grid=[].slice.call(document.querySelectorAll('.fm-set-grid')).filter(function(g){
    return g.getBoundingClientRect().width>10; })[0];
  var scroll=document.querySelector('.fm-set-scroll');
  if(!grid||!scroll){ out.errs.push('нет сетки или области прокрутки'); return res(dump(out)); }
  var gb=grid.getBoundingClientRect();
  out.gridW=Math.round(gb.width*10)/10;
  out.gridCssW=Math.round(parseFloat(getComputedStyle(grid).width)*10)/10;
  out.cols=getComputedStyle(grid).gridTemplateColumns.split(' ').filter(function(x){
    return parseFloat(x)>1; }).length;
  out.hScroll={scroll:scroll.scrollWidth-scroll.clientWidth,
               app:(function(a){return a?a.scrollWidth-a.clientWidth:-1;})(document.getElementById('app')),
               doc:document.documentElement.scrollWidth-document.documentElement.clientWidth};
  var secs=[].slice.call(grid.querySelectorAll(':scope > .fm-set-group')).filter(function(e){
    var b=e.getBoundingClientRect(); return b.height>10 && b.width>10; });
  out.items=secs.map(function(e){ var b=e.getBoundingClientRect();
    return {id:e.id||'', left:Math.round(b.left), top:Math.round(b.top),
            w:Math.round(b.width), h:Math.round(b.height),
            wide:e.classList.contains('fm-set-sec-wide'),
            over:e.scrollWidth-e.clientWidth}; });
  out.n=out.items.length;
  out.domOrder=secs.map(function(e){ return e.id||''; });
  // визуальный порядок: сверху вниз, внутри ряда слева направо
  out.visOrder=out.items.slice().sort(function(a,b){
    return (a.top-b.top) || (a.left-b.left); }).map(function(i){ return i.id; });
  // ряды по top (допуск 6px): ровные ли и одинаковы ли отступы
  var rows=[]; out.items.forEach(function(it){
    var r=rows.find(function(x){ return Math.abs(x.top-it.top)<=6; });
    if(r) r.items.push(it); else rows.push({top:it.top, items:[it]}); });
  rows.sort(function(a,b){ return a.top-b.top; });
  out.rows=rows.map(function(r){ var hs=r.items.map(function(i){return i.h;});
    return {top:r.top, n:r.items.length,
            maxDiff:Math.max.apply(null,hs)-Math.min.apply(null,hs),
            ids:r.items.map(function(i){return i.id;})}; });
  out.ragged=out.rows.filter(function(r){ return r.n>1 && r.maxDiff>2; }).length;
  var gaps=[]; for (var i=1;i<rows.length;i++){
    var pb=Math.max.apply(null, rows[i-1].items.map(function(x){return x.top+x.h;}));
    gaps.push(Math.round(rows[i].top-pb)); }
  out.gaps=gaps;
  out.gapSpread=gaps.length?(Math.max.apply(null,gaps)-Math.min.apply(null,gaps)):0;
  // перекрытия секций
  out.overlaps=0;
  for (var a=0;a<out.items.length;a++) for (var b2=a+1;b2<out.items.length;b2++){
    var A=out.items[a], B=out.items[b2];
    if (A.left < B.left+B.w-1 && B.left < A.left+A.w-1 &&
        A.top  < B.top +B.h-1 && B.top  < A.top +A.h-1) out.overlaps++; }
  // строки-флажки: высота должна быть «строчной», а не блочной
  var chks=[].slice.call(document.querySelectorAll('.fm-set-scroll .fm-chk')).filter(function(e){
    return e.getBoundingClientRect().height>0; });
  out.chkMax=chks.length?Math.max.apply(null, chks.map(function(e){
    return Math.round(e.getBoundingClientRect().height); })):0;
  out.chkN=chks.length;
  // текст внутри карточек не выходит за их границы
  out.textOver=0;
  secs.forEach(function(s){ var sb=s.getBoundingClientRect();
    [].slice.call(s.querySelectorAll('.fm-set-lbl,.fm-set-sec-t,.fm-bdg,.fm-set-hint')).forEach(function(t){
      var tb=t.getBoundingClientRect();
      if (tb.width>0 && (tb.right>sb.right+1 || tb.left<sb.left-1)) out.textOver++; }); });
  res(dump(out));
 } catch(e){ res(dump({tab:'%TAB%', errs:[String(e&&e.stack||e).slice(0,300)], log:FM_LOG})); }
}, %LANGARG%); });
"""

# Отдельный сценарий: главный экран без настроек — нужен, чтобы отделить переполнение каркаса
# приложения от переполнения раскладки настроек.
MAIN_JS = r"""
return new Promise(function(res){ setTimeout(function(){
  var b=byText('button',['Позже','Later']); if(b) click(b);
  setTimeout(function(){ var app=document.getElementById('app');
    res(dump({settingsOpen: !!document.querySelector('.fm-set-scroll'),
              appDx: app?app.scrollWidth-app.clientWidth:-1,
              docDx: document.documentElement.scrollWidth-document.documentElement.clientWidth}));
  }, 480); }, 300); });
"""

# (tab, окно, масштаб «увеличения», язык, подпись). Масштаб задаётся --force-device-scale-factor:
# это то же, что увеличение страницы у владельца, и именно оно меняет масштаб CSS-пикселя.
SCEN = [
    ("system", (3440, 1400), 1.0, None, "монитор владельца 3440x1400"),
    ("system", (3440, 1440), 1.0, None, "монитор владельца 3440x1440"),
    ("system", (2560, 1080), 1.0, None, "широкий 2560"),
    ("system", (1920, 1080), 1.0, None, "обычный 1920"),
    ("system", (1440, 900), 1.0, None, "узкий 1440"),
    ("system", (1280, 720), 1.0, None, "минимальный 1280"),
    ("general", (3440, 1400), 1.0, None, "«Общие» на ultrawide"),
    ("print", (1920, 1080), 1.0, None, "«Печать» на 1920"),
    #  2.999: новая вкладка «Модули» — те же инварианты раскладки, что и у остальных.
    ("modules", (1920, 1080), 1.0, None, "«Модули» на 1920"),
    ("modules", (1280, 720), 1.0, None, "«Модули» на 1280"),
    # увеличение 125/150/175/200 % — раскладка настроек обязана оставаться спокойной
    ("system", (1920, 1080), 1.25, None, "увеличение 125 %"),
    ("system", (1920, 1080), 1.5, None, "увеличение 150 %"),
    ("system", (1920, 1080), 1.75, None, "увеличение 175 %"),
    ("system", (1920, 1080), 2.0, None, "увеличение 200 %"),
    # английский интерфейс: длина подписей другая, раскладка не должна разъезжаться
    ("system", (1920, 1080), 1.0, "en", "EN «Система» 1920"),
    ("system", (3440, 1440), 1.0, "en", "EN «Система» 3440"),
    ("general", (1920, 1080), 1.0, "en", "EN «Общие» 1920"),
    ("print", (1920, 1080), 1.0, "en", "EN «Печать» 1920"),
    ("modules", (1920, 1080), 1.0, "en", "EN «Модули» 1920"),
    # русский интерфейс выбран явно (а не «как повезёт в свежем профиле»)
    ("system", (1920, 1080), 1.0, "ru", "RU «Система» 1920 (язык выбран явно)"),
]
MEASURE_MAX = int(_m.group(1)) if _m else 1040


def _key(tab, wh, dsf, lang):
    return "%s@%dx%d z%g %s" % (tab, wh[0], wh[1], dsf, lang or "auto")


def _dsf_args(dsf):
    return ("--force-device-scale-factor=%g" % dsf,) if abs(dsf - 1.0) > 1e-9 else ()


if os.environ.get("FM_LAYOUT_NO_BROWSER") == "1":
    print("(браузерная часть отключена FM_LAYOUT_NO_BROWSER=1 — режим отладки, не релизный прогон)")
elif not stage.engine_ready():
    check("19. браузерный движок доступен (без него раскладку измерить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    results, meta, problems = {}, {}, {}
    for tab, wh, dsf, lang, label in SCEN:
        js = (MEASURE_JS.replace("%TAB%", tab)
              .replace("%LANG%", "'%s'" % lang if lang else "''")
              .replace("%LANGARG%", "'%s'" % lang if lang else "undefined"))
        R = stage.run(js, window_size=wh, settle_ms=1500, extra_args=_dsf_args(dsf))
        k = _key(tab, wh, dsf, lang)
        results[k] = R or {}
        meta[k] = {"tab": tab, "w": wh[0], "h": wh[1], "dsf": dsf, "lang": lang, "label": label}
        problems[k] = stage.page_problems(R) if R else ["мост не вернул результат: %s" % stage.last_diag()]
        print("   [%s] %s: секций=%s колонок=%s рваных=%s разброс=%s h-scroll=%s флажок_max=%s язык=%s"
              % (label, tab, (R or {}).get("n"), (R or {}).get("cols"), (R or {}).get("ragged"),
                 (R or {}).get("gapSpread"), (R or {}).get("hScroll"), (R or {}).get("chkMax"),
                 (R or {}).get("uiLang")))

    ok = {k: v for k, v in results.items() if v and v.get("n")}
    check("19. приложение и настройки открылись во всех сценариях",
          len(ok) == len(SCEN), {k: (v.get("errs") or v.get("log")) for k, v in results.items() if k not in ok})
    check("20. каждый сценарий измерен на ЗАПРОШЕННОЙ вкладке",
          all(v.get("activeTab") for v in ok.values()),
          {k: v.get("activeTab") for k, v in ok.items()})
    check("21. вкладка «Система» показывает все 6 секций (редакция pro, «Доступ и аудит» на месте; 2.999: модули уехали)",
          all(v.get("n") == 6 for k, v in ok.items() if k.startswith("system")),
          {k: v.get("n") for k, v in ok.items() if k.startswith("system")})
    check("22. колонок НИКОГДА не больше двух — даже на 3440 (иначе «глаза разбегаются»)",
          all(1 <= v.get("cols", 0) <= 2 for v in ok.values()),
          {k: v.get("cols") for k, v in ok.items()})
    _ultra = [k for k in ok if meta[k]["w"] == 3440 and meta[k]["dsf"] == 1.0]
    check("23. на ultrawide колонок ровно две (страница не разъезжается и не сужается в одну)",
          bool(_ultra) and all(ok[k].get("cols") == 2 for k in _ultra),
          {k: ok[k].get("cols") for k in _ultra})
    check("24. мера страницы соблюдена: сетка не шире --fm-set-measure",
          all(v.get("gridCssW", 0) <= MEASURE_MAX + 2 for v in ok.values()),
          {k: v.get("gridCssW") for k, v in ok.items()})
    # Область настроек и документ обязаны быть без горизонтальной прокрутки ВСЕГДА. У #app на окне
    # уже 1280px есть свой запас 3px: каркас приложения имеет .zoom-wrap{min-width:960px}, а при
    # zoom 1.09717 это 1053px против 1050px рабочей ширины. Это свойство КАРКАСА, оно есть и на
    # главном экране при закрытых настройках (проверка 25b), скрыто overflow:hidden и к раскладке
    # настроек не относится — поэтому допуск задан осознанно и только для #app.
    _hoff = {k: v["hScroll"] for k, v in ok.items()
             if v["hScroll"]["scroll"] > 0 or v["hScroll"]["doc"] > 0 or v["hScroll"]["app"] > 4}
    check("25. горизонтальной прокрутки нет: область настроек и документ строго 0",
          not _hoff, _hoff)
    # Остаточное превышение у #app принадлежит КАРКАСУ (.zoom-wrap{min-width:960px}), а не раскладке
    # настроек: замеряем тот же размер окна и то же увеличение при ЗАКРЫТЫХ настройках и требуем,
    # чтобы настройки НЕ добавляли ни пикселя. Замер делается для каждого размера/увеличения.
    _frame_cache = {}

    def _frame_dx(w, h, dsf):
        kk = (w, h, dsf)
        if kk not in _frame_cache:
            # одна повторная попытка: замер каркаса — вспомогательный, и разовый сбой сцены не
            # должен выглядеть как регрессия раскладки
            R = stage.run(MAIN_JS, window_size=(w, h), settle_ms=1200, extra_args=_dsf_args(dsf))
            if not R:
                R = stage.run(MAIN_JS, window_size=(w, h), settle_ms=1800, extra_args=_dsf_args(dsf))
            _frame_cache[kk] = R or {}
        return _frame_cache[kk]

    _added = {}
    for k, v in ok.items():
        mm = meta[k]
        base = _frame_dx(mm["w"], mm["h"], mm["dsf"])
        if base.get("settingsOpen") is not False or v["hScroll"]["app"] > (base.get("appDx") or 0):
            _added[k] = {"каркас": base.get("appDx"), "с настройками": v["hScroll"]["app"],
                         "настройки закрыты на замере каркаса": base.get("settingsOpen")}
    check("25b. настройки НЕ добавляют горизонтального превышения к каркасу (все окна и увеличения)",
          not _added, _added)
    check("26. рядов-«ступенек» нет: парные карточки одной высоты",
          all(v.get("ragged") == 0 for v in ok.values()), {k: v.get("rows") for k, v in ok.items()})
    check("27. отступы между рядами одинаковые (разброс <= 2px) — единый ритм",
          all(v.get("gapSpread", 99) <= 2 for v in ok.values()),
          {k: v.get("gaps") for k, v in ok.items()})
    check("28. секции не перекрываются",
          all(v.get("overlaps") == 0 for v in ok.values()),
          {k: v.get("overlaps") for k, v in ok.items()})
    check("29. визуальный порядок секций совпадает с порядком в разметке (читается сверху вниз)",
          all(v.get("visOrder") == v.get("domOrder") for v in ok.values()),
          {k: (v.get("domOrder"), v.get("visOrder")) for k, v in ok.items()
           if v.get("visOrder") != v.get("domOrder")})
    check("30. на вкладке «Система» порядок именно логический",
          all([i for i in ok[k]["visOrder"] if i] == SYSTEM_ORDER for k in ok if k.startswith("system")),
          {k: ok[k]["visOrder"] for k in ok if k.startswith("system")})
    _mod_keys = [k for k in ok if k.startswith("modules")]
    check("30б. вкладка «Модули» измерена и показывает свои постоянные секции по порядку",
          bool(_mod_keys) and all([i for i in ok[k]["visOrder"] if i in MODULES_ORDER] == MODULES_ORDER
                                  for k in _mod_keys),
          {k: ok[k]["visOrder"] for k in _mod_keys})
    #  2.1003 (заказ владельца): ячейки настроек модулей — в САМОМ НИЗУ вкладки. У них нет
    #  своего id (состав зависит от того, что установлено), поэтому в порядке они идут пустыми
    #  строками: все пустые обязаны стоять ПОСЛЕ последней постоянной секции.
    _cfg_tail = {}
    for k in _mod_keys:
        vo = ok[k]["visOrder"]
        last_fixed = max([i for i, x in enumerate(vo) if x in MODULES_ORDER] or [-1])
        _cfg_tail[k] = [i for i, x in enumerate(vo) if not x and i < last_fixed]
    check("30в. ячейки настроек модулей стоят ниже всех постоянных секций вкладки",
          bool(_mod_keys) and all(not v for v in _cfg_tail.values()),
          {k: ok[k]["visOrder"] for k, v in _cfg_tail.items() if v})
    #  И у самой ячейки нет своей полосы прокрутки: лист настроек выше — прокручивается он.
    check("30г. у ячейки настроек модуля нет собственной прокрутки",
          ".fm-mod-cfg{overflow:visible}" in CSS and "max-height:620px" not in CSS,
          [l for l in CSS.splitlines() if "fm-mod-cfg" in l])
    # Порог 200px: дефект flex-basis давал строки 315-519px, а честный перенос длинной подписи на
    # узком окне доходит до ~120px. Между этими величинами есть запас, и проверка остаётся строгой.
    #  2.999: на вкладке «Модули» флажков НЕТ по замыслу — это список модулей и кнопка
    #  установки. Требование «в каждом сценарии есть флажок» сужено до вкладок, где они есть;
    #  вакуумной проверка не стала: таких сценариев большинство, и высота там меряется та же.
    _chk = {k: v for k, v in ok.items() if meta[k]["tab"] != "modules"}
    check("31. строка-флажок нормальной высоты (<=200px): нет раздутых блоков и пустот",
          all(0 < v.get("chkMax", 0) <= 200 for v in _chk.values()),
          {k: v.get("chkMax") for k, v in _chk.items()})
    check("32. флажки реально присутствуют там, где они есть (проверка не вакуумная)",
          len(_chk) >= 10 and all(v.get("chkN", 0) >= 1 for v in _chk.values()),
          {k: v.get("chkN") for k, v in _chk.items()})
    check("32б. 2.999: на вкладке «Модули» флажков нет — там список и установка",
          all(v.get("chkN", 0) == 0 for k, v in ok.items() if meta[k]["tab"] == "modules"),
          {k: v.get("chkN") for k, v in ok.items() if meta[k]["tab"] == "modules"})
    check("33. ни одна карточка не переполнена по ширине",
          all(all(it["over"] <= 0 for it in v["items"]) for v in ok.values()),
          {k: [it for it in v["items"] if it["over"] > 0] for k, v in ok.items()})
    check("34. подписи, бейджи и подсказки не выходят за границы своих карточек",
          all(v.get("textOver") == 0 for v in ok.values()),
          {k: v.get("textOver") for k, v in ok.items()})
    _narrow = [k for k in ok if meta[k]["w"] == 1280 and meta[k]["dsf"] == 1.0]
    check("35. на узком окне раскладка честно сворачивается в одну колонку",
          bool(_narrow) and all(ok[k].get("cols") == 1 for k in _narrow),
          {k: ok[k].get("cols") for k in _narrow})
    check("36. широкие секции занимают всю ширину сетки, обычные — колонку",
          all(all((it["w"] > v["gridW"] * 0.9) if it["wide"] else True for it in v["items"])
              for v in ok.values()),
          {k: [(it["id"], it["w"], v["gridW"]) for it in v["items"] if it["wide"]]
           for k, v in ok.items()})

    # ── увеличение 100-200 %, RU/EN, реальный монитор владельца (37-43) ──
    _zooms = {meta[k]["dsf"] for k in ok if meta[k]["dsf"] != 1.0}
    check("37. измерены все уровни увеличения 125/150/175/200 % (а не только 100 %)",
          _zooms == {1.25, 1.5, 1.75, 2.0}, sorted(_zooms))
    _zk = [k for k in ok if meta[k]["dsf"] != 1.0]
    check("38. при любом увеличении колонок не больше двух и сетка не шире меры страницы",
          all(1 <= ok[k].get("cols", 0) <= 2 and ok[k].get("gridCssW", 0) <= MEASURE_MAX + 2 for k in _zk),
          {k: (ok[k].get("cols"), ok[k].get("gridCssW")) for k in _zk})
    check("39. при любом увеличении область настроек и документ без горизонтальной прокрутки",
          all(ok[k]["hScroll"]["scroll"] == 0 and ok[k]["hScroll"]["doc"] == 0 for k in _zk),
          {k: ok[k]["hScroll"] for k in _zk})
    check("40. при любом увеличении строки-флажки нормальной высоты и карточки не рваные",
          all(0 < ok[k].get("chkMax", 0) <= 200 and ok[k].get("ragged") == 0 for k in _zk),
          {k: (ok[k].get("chkMax"), ok[k].get("ragged")) for k in _zk})
    _en = [k for k in ok if meta[k]["lang"] == "en"]
    _ru = [k for k in ok if meta[k]["lang"] == "ru"]
    check("41. язык интерфейса реально переключился в запрошенный (RU и EN сценарии)",
          bool(_en) and bool(_ru)
          and all(ok[k].get("uiLang") == "en" for k in _en)
          and all(ok[k].get("uiLang") == "ru" for k in _ru),
          {k: ok[k].get("uiLang") for k in _en + _ru})
    check("42. на английском вкладка «Система» показывает те же 6 секций в том же порядке",
          all([i for i in ok[k]["visOrder"] if i] == SYSTEM_ORDER
              for k in _en if meta[k]["tab"] == "system"),
          {k: ok[k]["visOrder"] for k in _en if meta[k]["tab"] == "system"})
    check("43. на английском раскладка так же спокойна: <=2 колонок, ряды ровные, h-scroll 0",
          all(1 <= ok[k].get("cols", 0) <= 2 and ok[k].get("ragged") == 0
              and ok[k]["hScroll"]["scroll"] == 0 and ok[k]["hScroll"]["doc"] == 0 for k in _en),
          {k: (ok[k].get("cols"), ok[k].get("ragged"), ok[k]["hScroll"]) for k in _en})
    _bad = {k: v for k, v in problems.items() if v}
    check("44. ни один сценарий не дал ошибок консоли, исключений и предупреждений Vue",
          not _bad, _bad)

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    print("НЕ ПРОЙДЕНО:")
    for f in _fail:
        print("   - %s" % f)
stage.stop()
sys.exit(1 if _fail else 0)
