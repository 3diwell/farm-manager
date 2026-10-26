# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""26.09.2026 — тёмный язычок шапки подстраивается под надпись «Брокер данных • <статус>».

ЧТО ЗАЩИЩАЕТ. Замечание владельца: при увеличенном «Размере текста» надпись вылезала за правый край
тёмного выреза в шапке, «и это смотрится поломано». Вырез был нарисован внутри картинки фиксированной
ширины. Теперь левый блок шапки (.fm-header-left-v270) — одна фигура по прежнему контуру, у которой
тянется только ровное дно выреза; ширину задаёт невидимый «призрак» надписи со ВСЕМИ статусами
синхронизации (.fm-header-tongue-ghost-v300), поэтому язычок не прыгает при смене статуса.

В НАСТОЯЩЕМ браузере на изолированном стенде (настоящие web/index.html, app.css, app.js):
  1. надпись целиком внутри выреза — до правого скоса остаётся прежний зазор — при 90/100/130 %,
     по-русски и по-английски, во всех статусах, шрифтами Wide J (по умолчанию), Wide P и Arial;
  2. ширина язычка одна во всех статусах (не прыгает) и не меньше прежней; когда надпись влезает
     в прежний вырез (английский, 100 %), язычок ровно прежний; по-русски при 100 % вырез шире на
     «Сохранение...», которое в прежний не помещалось;
  3. призрак совпадает с настоящей надписью по ширине (иначе язычок разойдётся с ней);
  4. надпись шапки растёт ровно во столько раз, сколько выбрано в «Размере текста», и при шрифте
     Windows (у шапки свой шрифт — ей своя поправка);
  5. то же в интерфейсе 3.0 и в светлой теме; с модулем «Оформление и темы» (его картинка фона с
     !important не подменяет однотонную фигуру); на телефоне (узкое окно) призрака нет;
  6. ошибок консоли, исключений и предупреждений Vue нет.

Координаты — CSS-точки шапки; u = высота шапки / 3868 — единица исходной картинки выреза.
Запуск:  python tools/test_header_tongue.py      (0 = всё в порядке)
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

_pass, _fail = [0], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:500]) if detail else ""))


#  Геометрия исходной картинки выреза (единицы её viewBox 18866 x 3868): прежняя ширина левого блока
#  и зазор от конца надписи «Свободен» (100 %) до правого края выреза.
ORIG_W_U = 18866.0
GAP_U = 987.4

JS = r"""
var LANG = __LANG__, SIZES = __SIZES__, MODULE = __MODULE__, STATES = ['idle', 'saving', 'saved'];
//  Модуль «Оформление и темы» (modules/appearance/web/compatibility.js) при включённой теме подменяет фон
//  левого блока картинкой с !important — здесь его правила воспроизведены в той же форме и силе.
function moduleOn(){
  var svg = encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#2f5fa8"/></svg>');
  var st = document.createElement('style'); st.id = '__fm_appearance_sim';
  st.textContent = ['dark', 'light'].map(function(t){ return ':root[data-theme="' + t + '"][data-fm-appearance-active="1"] .fm-header-left-v270'
    + '{background-image:url("data:image/svg+xml,' + svg + '")!important;background-repeat:no-repeat!important;background-size:100% 100%!important;}'; }).join('');
  document.head.appendChild(st); document.documentElement.setAttribute('data-fm-appearance-active', '1'); }
var R = {rows: [], log: FM_LOG};
function vm(){ var a = document.getElementById('app'); return a && a._vnode && a._vnode.component && a._vnode.component.proxy; }
function zt(){ var hz = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
  var w = document.querySelector('.zoom-wrap'); var wz = w ? (parseFloat(getComputedStyle(w).zoom) || 1) : 1; return hz * wz; }
function measure(size, status){
  var hdr = document.querySelector('header.app-header'); var o = hdr.getBoundingClientRect(); var z = zt();
  var L = document.querySelector('.fm-header-left-v270'), C = document.querySelector('.fm-header-center-v270');
  var B = document.querySelector('.fm-header-broker-v270'), G = document.querySelector('.fm-header-tongue-ghost-v300');
  var rg = document.createRange(); rg.selectNodeContents(B); var br = rg.getBoundingClientRect();
  var lbl = B.querySelector('.fm-header-broker-text-v270'); var lr = lbl ? lbl.getBoundingClientRect() : null;
  function x(v){ return +((v - o.left) / z).toFixed(3); }
  var row = {size: size, status: status, H: +(o.height / z).toFixed(3), brokerR: x(br.right), labelW: lr ? +(lr.width / z).toFixed(3) : 0};
  if (L) { var lb = L.getBoundingClientRect(); row.leftL = x(lb.left); row.leftR = x(lb.right); }
  if (C) { var cb = C.getBoundingClientRect(); row.centerL = x(cb.left); row.centerW = +(cb.width / z).toFixed(3); }
  if (G) { var rg2 = document.createRange(); rg2.selectNodeContents(G); row.ghostR = x(rg2.getBoundingClientRect().right); }
  row.bg = L ? getComputedStyle(L).backgroundImage.slice(0, 40) : '';
  row.hasGhost = !!G; row.rule = (document.getElementById('ui-text-size') || {}).textContent || '';
  return row;
}
return new Promise(function(RES){
  var fns = [ function(){ var b = byText('button', ['Позже', 'Later']); if (b) click(b); },
              function(){ setUiLang(LANG); if (MODULE) moduleOn(); },
              function(d){ (document.fonts ? document.fonts.ready : Promise.resolve()).then(function(){ setTimeout(d, 500); }); } ];
  SIZES.forEach(function(sz){
    fns.push(function(){ var p = vm(); if (p) p.setUiTextSize(sz); else FM_LOG.push('нет vm'); });
    fns.push(function(d){ setTimeout(d, 300); });
    STATES.forEach(function(s){
      fns.push(function(){ var p = vm(); if (p) p.syncStatus = s; });
      fns.push(function(){ R.rows.push(measure(sz, s)); });
    });
  });
  fns.push(function(){ var p = vm(); if (p) { p.setUiTextSize('100'); p.syncStatus = 'idle'; } });
  steps(fns, function(){ dump(R); RES(true); });
});
"""


def run(lang, font, sizes=("90", "100", "130"), path="/", theme=None, size=(1440, 900), module=False):
    q = "ls=ui_font:%s" % font
    if theme:
        q += "&ls=farm_theme:%s" % theme
    page = path + ("&" if "?" in path else "?") + q
    js = (JS.replace("__LANG__", '"%s"' % lang).replace("__SIZES__", "[%s]" % ",".join('"%s"' % s for s in sizes))
            .replace("__MODULE__", "true" if module else "false"))
    res = stage.run(js, window_size=size, settle_ms=2500, path=page) or {}
    return res


NEED = ("leftR", "centerL", "centerW", "ghostR")


def judge(tag, res, en100_same=False, module=False):
    rows = res.get("rows") or []
    ok = len(rows) >= 3 and all(all(k in r for k in NEED) and r.get("labelW", 0) > 0 for r in rows)
    check("%s: прогон состоялся — язычок, середина шапки, призрак и подпись найдены (замеров %d)" % (tag, len(rows)), ok,
          res.get("log") or (rows[:1] if rows else stage.last_diag()))
    if not ok:
        return
    u = rows[0]["H"] / 3868.0
    orig = ORIG_W_U * u
    bad_fit = [(r["size"], r["status"], round(r["leftR"] - GAP_U * u - r["brokerR"], 2)) for r in rows
               if r["brokerR"] > r["leftR"] - GAP_U * u + 0.3]
    check("%s: надпись целиком внутри выреза, до правого скоса прежний зазор" % tag, not bad_fit, bad_fit)
    by_size = {}
    for r in rows:
        by_size.setdefault(r["size"], []).append(r["leftR"])
    jump = {s: (round(min(v), 2), round(max(v), 2)) for s, v in by_size.items() if max(v) - min(v) > 0.1}
    check("%s: язычок одной ширины во всех статусах (не прыгает)" % tag, not jump, jump)
    narrow = [(r["size"], round(r["leftR"], 2)) for r in rows if r["leftR"] < orig - 0.1]
    check("%s: язычок не уже прежнего (%.2f)" % (tag, orig), not narrow, narrow)
    #  Текст призрака кончается там же, где настоящая надпись с самым длинным из показываемых статусов.
    ghost = {}
    for sz in by_size:
        rs = [r for r in rows if r["size"] == sz]
        d = round(rs[0]["ghostR"] - max(r["brokerR"] for r in rs), 2)
        if abs(d) > 0.3:
            ghost[sz] = d
    check("%s: невидимая копия надписи совпадает с настоящей (самый длинный статус)" % tag, not ghost, ghost)
    adj = [(r["size"], round(r["centerL"] - r["leftR"], 2)) for r in rows if abs(r["centerL"] - r["leftR"]) > 0.5
           or r["centerW"] < 100]
    check("%s: середина шапки сразу за язычком и не схлопнулась" % tag, not adj, adj)
    lw = {r["size"]: r["labelW"] for r in rows if r["status"] == "idle"}
    if "100" in lw and lw["100"] > 0:
        ratios = {s: round(w / lw["100"], 3) for s, w in lw.items()}
        exp = {"90": 0.9, "100": 1.0, "110": 1.1, "120": 1.2, "130": 1.3}
        off = {s: v for s, v in ratios.items() if abs(v - exp[s]) > 0.03}
        check("%s: надпись шапки растёт ровно в выбранное число раз" % tag, not off, ratios)
    if en100_same:
        r100 = [r for r in rows if r["size"] == "100"]
        check("%s: при 100 %%, когда надпись влезает, язычок ровно прежний" % tag,
              r100 and all(abs(r["leftR"] - orig) <= 0.1 for r in r100), [(round(r["leftR"], 2), round(orig, 2)) for r in r100])
    if module:
        bgs = sorted({r.get("bg", "") for r in rows})
        check("%s: фон язычка однотонный, картинка модуля его не подменяет" % tag,
              all(b.startswith("linear-gradient") for b in bgs), bgs)
    probs = stage.page_problems(res)
    check("%s: ошибок консоли нет" % tag, not probs, probs)


if not stage.engine_ready():
    check("0. браузерный движок доступен", False, stage.last_diag())
else:
    for font, fname in (("default", "Wide J"), ("wide-p", "Wide P"), ("arial", "Arial")):
        for lang in ("ru", "en"):
            tag = "%s, %s" % (fname, lang.upper())
            judge(tag, run(lang, font), en100_same=(lang == "en" and font == "default"))
    judge("интерфейс 3.0, Wide J, RU", run("ru", "default", sizes=("100", "130"), path="/ui3"))
    judge("светлая тема, Wide J, RU", run("ru", "default", sizes=("100", "130"), theme="light"))
    for th in ("dark", "light"):
        judge("модуль «Оформление и темы», %s тема, Wide J, EN" % ("тёмная" if th == "dark" else "светлая"),
              run("en", "default", sizes=("100", "130"), theme=th, module=True), en100_same=True, module=True)
    #  Узкое окно (телефон): слоя с вырезом нет, призрака тоже; надпись на месте, ошибок нет.
    RM = stage.run(r"""return new Promise(function(r){ setTimeout(function(){
        dump({ghost: !!document.querySelector('.fm-header-tongue-ghost-v300'), left: !!document.querySelector('.fm-header-left-v270'),
              broker: !!document.querySelector('.fm-header-broker-v270')}); r(true); }, 1500); });""",
                   window_size=(700, 900), settle_ms=2500, path="/?ls=ui_text_size:130") or {}
    check("мобильная шапка: выреза и призрака нет, надпись на месте",
          RM.get("broker") is True and RM.get("ghost") is False and RM.get("left") is False, RM)
    probs = stage.page_problems(RM) if RM else ["прогон не состоялся: %s" % stage.last_diag()]
    check("мобильная шапка: ошибок консоли нет", not probs, probs)
    stage.stop()

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    for f in _fail:
        print("   - " + f)
sys.exit(1 if _fail else 0)
