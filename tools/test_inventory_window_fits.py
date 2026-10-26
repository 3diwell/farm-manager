# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Окно «Складского учёта» целиком помещается на экране (склад 1.7.32).
#
# ДЕФЕКТ. Окно склада ставит сам модуль (инлайн position:fixed + left/top/width/height). Программа
# увеличивает всю страницу через html{zoom} — 1.196 при шрифте по умолчанию, 1.04 при остальных.
# Модуль сравнивал своё положение с window.innerWidth/innerHeight — это ВИДИМЫЕ точки, а его
# left/width — ЛОГИЧЕСКИЕ (браузер умножает их на zoom). Итог — окно по умолчанию уходило за
# правый и нижний край: на 1600×1000 кнопка «Закрыть» стояла на 1542–1630 при ширине экрана 1576,
# поле поиска и стрелки групп — за краем; на 1280 и 1920 то же самое.
#
# ПОЧИНКА (modules/inventory/web/InventoryPanel.js). Край экрана считается в логических точках
# (вьюпорт ÷ живой zoom — как exWinClampIntoView у окна проводника в ядре), окно держится целиком
# в экране с отступом 12, минимум 620×460 уступает маленькому экрану; сохранённое положение
# возвращается в видимую область; смена zoom без события resize (смена шрифта) ловится по размеру
# подложки .fm-inv-root. Перетаскивание и растяжение работают как раньше, только не уводят окно
# за край.
#
# ЧТО ДОКАЗЫВАЕТСЯ — замерами в НАСТОЯЩЕМ браузере (настоящий модуль, настоящая страница с её
# html{zoom}, данные синтетические):
#   1. на окнах 1600×1000, 1280×800, 1024×640, 853×533, 1920×1080, в интерфейсах «/» и «/ui3»:
#      окно, кнопка «Закрыть», поле поиска и заголовки групп целиком в видимой области, окно
#      по центру и не крошечное, горизонтальной прокрутки нет, консоль чистая;
#   2. то же при «Размере текста» 90 % и 130 % и в светлой теме;
#   3. сохранённое положение за краем экрана (и слишком большое) возвращается в видимую область;
#   4. окно браузера уменьшили и увеличили при открытом складе — окно в экране;
#   5. zoom страницы вырос без события resize (так меняет его выбор шрифта) — окно в экране;
#   6. перетаскивание сдвигает окно ровно на сдвиг мыши, растяжение растит ровно на сдвиг,
#      а утащить или растянуть окно за край нельзя; минимум 620×460 соблюдается, где помещается.
#   НЕ ВАКУУМ: с прежним модулем (1.7.31) проверки 1 краснеют — проверено откатом правки.
#
# БЕЗОПАСНОСТЬ: стенд tools/_fm_ui_stage.py — статический сервер с синтетическими ответами.
# Рабочая база, папка данных, принтеры и печать не затрагиваются.
#
# Запуск:  python tools/test_inventory_window_fits.py      (0 = всё в порядке)
# ============================================================================
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage                              # noqa: E402

SENTINEL = "INVENTORY_WINDOW_FITS_1732"
SIZES = ((1600, 1000), (1280, 800), (1024, 640), (853, 533), (1920, 1080))
TOL = 0.6          # доля точки на округление координат браузером
PAD = 12           # отступ окна от края экрана в логических точках (как у окна проводника ядра)
MINW, MINH = 620, 460

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:500]) if detail else ""))


SPOOLS = [{"id": 100 + i, "material": m, "color_hex": c, "color_name": cn, "vendor_name": v,
           "weight_total_g": 1000, "weight_remaining_g": w, "status": "in_stock", "ams_printer_id": None,
           "ams_slot": None, "created_at": "2026-09-%02d 10:00:00" % (1 + i)}
          for i, (m, c, cn, w, v) in enumerate([
              ("PETG", "#9ea7ae", "серый", 900, "Generic"), ("PLA", "#e5484d", "красный", 420, "Bambu"),
              ("PLA", "#222222", "чёрный", 80, "Bambu"), ("ABS", "#f5f5f5", "белый", 1000, "eSun"),
              ("PLA", "#f5a524", "оранжевый", 60, "Polymaker")])]
INV = {
    "/api/modules": {"modules": []},
    "/api/mod/inventory/ams": {"printers": [
        {"printer_id": "AD5M", "printer_name": "FlashForge AD5M", "has_ams": False, "feed": "",
         "slots": [{"index": -1, "unit": None, "tray": None, "type": "", "color": "", "external": True,
                    "spool": None}]}]},
    "/api/mod/inventory/filament": {"vendors": [{"id": 1, "name": "Generic"}], "filaments": [], "spools": SPOOLS},
    "/api/mod/inventory/items": {"items": []},
    "/api/mod/inventory/cost": {"by_material": [], "by_file": [], "spent": 0, "filament_value": 0,
                                "parts_value": 0, "total_value": 0},
    "/api/mod/inventory/settings": {"currency": "RUB", "low_filament_g": 100},
    "/api/mod/inventory/forecast": {"spools": []},
    "/api/mod/inventory/locations": {"locations": []},
}

#  __WIN__ — сохранённая геометрия окна (null — нет сохранённой); __STEPS__ — действия после открытия.
#  Каждое действие заканчивается замером: где окно, «Закрыть», поиск, заголовки групп, есть ли прокрутка.
JS = r"""
return new Promise(function(res){ (async function(){
  var out = {errs: [], m: []};
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function R(el){ if (!el) return null; var b = el.getBoundingClientRect();
    return {l: b.left, t: b.top, r: b.right, b: b.bottom, w: b.width, h: b.height}; }
  function shown(sel){ return [].slice.call(document.querySelectorAll(sel)).filter(function(e){
    var b = e.getBoundingClientRect(); return e.offsetParent !== null && b.width > 0 && b.height > 0; }); }
  function measure(tag){
    var p = document.querySelector('.fm-inv-panel'), de = document.documentElement;
    var s = shown('.fm-inv-panel .fm-inv-search')[0] || null;
    var inl = p ? (p.getAttribute('style') || '') : '';
    function px(k){ var m = inl.match(new RegExp('(^|;)\\s*' + k + ':\\s*([-\\d.]+)px')); return m ? parseFloat(m[2]) : null; }
    return {tag: tag, iw: window.innerWidth, ih: window.innerHeight, z: getComputedStyle(de).zoom,
      panel: R(p), close: R(document.querySelector('.fm-inv-close')), head: R(document.querySelector('.fm-inv-head')),
      search: R(s), groups: shown('.fm-inv-panel .fm-inv-mhead').map(R),
      hscroll: de.scrollWidth - de.clientWidth, g: {x: px('left'), y: px('top'), w: px('width'), h: px('height')}};
  }
  function pe(type, x, y){ return new PointerEvent(type, {clientX: x, clientY: y, bubbles: true, cancelable: true,
    pointerId: 1, pointerType: 'mouse', isPrimary: true, button: 0, buttons: type === 'pointerup' ? 0 : 1}); }
  async function gesture(el, dx, dy){   // нажать, провести мышью на (dx, dy) видимых точек, отпустить
    var b = el.getBoundingClientRect(), x = b.left + Math.min(40, b.width / 2), y = b.top + b.height / 2;
    el.dispatchEvent(pe('pointerdown', x, y)); await sleep(30);
    window.dispatchEvent(pe('pointermove', x + dx / 2, y + dy / 2)); await sleep(30);
    window.dispatchEvent(pe('pointermove', x + dx, y + dy)); await sleep(30);
    window.dispatchEvent(pe('pointerup', x + dx, y + dy)); await sleep(250);
  }
  try {
    await sleep(1200);
    var later = byText('button', ['Позже', 'Later']); if (later) click(later);
    var WIN = __WIN__;
    try { if (WIN) localStorage.setItem('inv_win', JSON.stringify(WIN)); else localStorage.removeItem('inv_win'); } catch (e) {}
    var V = await import('/vendor/vue.esm-browser.js');
    var M = await import('/modules/inventory/InventoryPanel.js');
    var host = document.createElement('div'); document.body.appendChild(host);
    var inv = V.ref(null);
    var app = V.createApp({ setup: function(){ return function(){ return V.h(M.default, { ref: inv, open: true,
      lang: 'ru', startTab: 'filament', access: { contractVersion: 1, can: function(){ return true; } } }); }; } });
    app.component('svg-icon', { props: ['name'], template: '<i></i>' });
    app.config.errorHandler = function(e){ out.errs.push(String((e && e.message) || e)); };
    app.mount(host);
    await sleep(900);
    var vm = inv.value;
    vm.tab = 'warehouse'; vm.wmode = 'stock';
    await sleep(400);
    var g = vm.warehouseGroups, pla = g.filter(function(x){ return x.material === 'PLA'; })[0];
    if (pla) { vm.toggleMat(pla); await sleep(250); }
    out.m.push(measure('open'));
    var STEPS = __STEPS__;
    for (var i = 0; i < STEPS.length; i++) {
      var st = STEPS[i];
      if (st[0] === 'drag') await gesture(document.querySelector('.fm-inv-head'), st[1], st[2]);
      else if (st[0] === 'resize') await gesture(document.querySelector('.fm-inv-rz-' + st[3]), st[1], st[2]);
      else if (st[0] === 'viewport') await new Promise(function(r){ setViewport(st[1], st[2], 1, r); });
      else if (st[0] === 'zoom') { document.documentElement.style.zoom = st[1]; await sleep(500); }
      await sleep(200);
      out.m.push(measure(st.join(' ')));
    }
  } catch (e) { out.fatal = String((e && e.stack) || e); }
  res(dump(out));
})(); });
"""


def run(path, size, win=None, steps=()):
    stage.set_api(INV)
    js = JS.replace("__WIN__", json.dumps(win)).replace("__STEPS__", json.dumps([list(s) for s in steps]))
    return stage.run(js, window_size=size, settle_ms=2500, path=path)


def _inside(r, iw, ih):
    return bool(r) and r["l"] >= -TOL and r["t"] >= -TOL and r["r"] <= iw + TOL and r["b"] <= ih + TOL


def _within(a, b):
    return bool(a) and bool(b) and a["l"] >= b["l"] - TOL and a["t"] >= b["t"] - TOL \
        and a["r"] <= b["r"] + TOL and a["b"] <= b["b"] + TOL


def _z(m):
    try:
        return float(m.get("z") or 1)
    except Exception:
        return 1.0


def fits(tag, m):
    """Окно и всё нужное в нём — целиком на экране; окно не выродилось в крошечное."""
    iw, ih, p = m["iw"], m["ih"], m["panel"]
    check("окно целиком в видимой области (%s)" % tag, _inside(p, iw, ih), (p, iw, ih))
    c = m["close"]
    check("кнопка «Закрыть» на экране и внутри окна (%s)" % tag, _inside(c, iw, ih) and _within(c, p), (c, p))
    s = m["search"]
    check("поле поиска на экране и внутри окна (%s)" % tag, _inside(s, iw, ih) and _within(s, p), (s, p))
    gs = m.get("groups") or []
    #  По горизонтали: заголовок группы (справа у него стрелка) не выходит ни за экран, ни за окно.
    #  По вертикали группы прокручиваются внутри окна — нижние законно уходят под его край.
    check("заголовки групп склада (со стрелками) по ширине внутри окна и экрана (%s)" % tag,
          bool(gs) and bool(p) and all(x["l"] >= max(0, p["l"]) - TOL and x["r"] <= min(iw, p["r"]) + TOL for x in gs),
          ([(round(x["l"]), round(x["r"])) for x in gs][:4], p and (round(p["l"]), round(p["r"])), iw))
    check("горизонтальной прокрутки страницы нет (%s)" % tag, (m.get("hscroll") or 0) <= 0, m.get("hscroll"))
    z = _z(m)
    need_w = min(MINW, iw / z - 2 * PAD) * z
    need_h = min(MINH, ih / z - 2 * PAD) * z
    check("окно не крошечное: не меньше 620×460 или всего экрана за вычетом отступов (%s)" % tag,
          p and p["w"] >= need_w - 1 and p["h"] >= need_h - 1, (p and (round(p["w"]), round(p["h"])), round(need_w), round(need_h)))


def console_clean(tag, R):
    probs = stage.page_problems(R) + ["ошибка Vue: %s" % e for e in (R.get("errs") or [])]
    check("консоль браузера чистая (%s)" % tag, not probs, probs[:3])


def opened(tag, R):
    ok = bool(R) and not R.get("fatal") and bool(R.get("m")) and bool((R["m"][0] or {}).get("panel"))
    check("склад открылся (%s)" % tag, ok, (R or {}).get("fatal") or stage.last_diag())
    return ok


if not stage.engine_ready():
    check("браузерный движок доступен (без него окно проверить нечем)", False, str(stage.last_diag())[:250])
else:
    print("--- 1. окно по умолчанию: пять экранов, интерфейсы 3.0 и 2.0 ---")
    for path in ("/ui3", "/"):
        for size in SIZES:
            tag = "%s %dx%d" % (path, size[0], size[1])
            R = run(path, size)
            if not opened(tag, R):
                continue
            m = R["m"][0]
            fits(tag, m)
            p = m["panel"]
            check("окно по центру экрана (%s)" % tag,
                  abs(p["l"] - (m["iw"] - p["r"])) <= 2.5 and abs(p["t"] - (m["ih"] - p["b"])) <= 2.5,
                  (round(p["l"]), round(m["iw"] - p["r"]), round(p["t"]), round(m["ih"] - p["b"])))
            console_clean(tag, R)

    print("--- 2. «Размер текста» 90 % и 130 %, светлая тема ---")
    for path, size, q in (("/ui3", (853, 533), "ls=ui_text_size:130"), ("/", (853, 533), "ls=ui_text_size:130"),
                          ("/ui3", (1280, 800), "ls=ui_text_size:130"), ("/", (1600, 1000), "ls=ui_text_size:130"),
                          ("/ui3", (1920, 1080), "ls=ui_text_size:90"), ("/", (1024, 640), "ls=ui_text_size:90"),
                          ("/ui3", (1280, 800), "ls=farm_theme:light"), ("/", (1920, 1080), "ls=farm_theme:light")):
        tag = "%s %dx%d %s" % (path, size[0], size[1], q.split("=", 1)[1])
        R = run(path + "?" + q, size)
        if not opened(tag, R):
            continue
        fits(tag, R["m"][0])
        m = R["m"][0]
        check("«Закрыть» не вытеснена из шапки текстом заголовка (%s)" % tag, _within(m["close"], m["head"]),
              (m["close"], m["head"]))
        console_clean(tag, R)

    print("--- 3. сохранённое положение за краем экрана возвращается в видимую область ---")
    for path, size, win in (("/ui3", (1280, 800), {"x": 1500, "y": 900, "w": 1500, "h": 1000}),
                            ("/", (1024, 640), {"x": -400, "y": -300, "w": 700, "h": 500}),
                            ("/ui3", (1920, 1080), {"x": 700, "y": 400, "w": 1180, "h": 900})):
        tag = "%s %dx%d, сохранено %s" % (path, size[0], size[1], win)
        R = run(path, size, win=win)
        if not opened(tag, R):
            continue
        fits(tag, R["m"][0])
        console_clean(tag, R)

    print("--- 4. окно браузера уменьшили и увеличили при открытом складе ---")
    for path in ("/ui3", "/"):
        tag = "%s 1920x1080 → 853x533 → 1600x1000" % path
        R = run(path, (1920, 1080), steps=(("viewport", 853, 533), ("viewport", 1600, 1000)))
        if not opened(tag, R):
            continue
        ms = R["m"]
        check("вьюпорт действительно менялся (%s)" % tag,
              len(ms) == 3 and ms[1]["iw"] < ms[0]["iw"] and ms[2]["iw"] > ms[1]["iw"], [x["iw"] for x in ms])
        for m in ms:
            fits("%s, шаг «%s», экран %sx%s" % (path, m["tag"], m["iw"], m["ih"]), m)
        console_clean(tag, R)

    print("--- 5. zoom страницы вырос без события resize (так его меняет выбор шрифта) ---")
    tag = "/ui3 1280x800, шрифт Segoe UI (zoom 1.04) → 1.196"
    R = run("/ui3?ls=ui_font:segoe", (1280, 800), win={"x": 30, "y": 20, "w": 1180, "h": 900},
            steps=(("zoom", "1.196"),))
    if opened(tag, R):
        ms = R["m"]
        check("zoom страницы действительно сменился 1.04 → 1.196 (%s)" % tag,
              len(ms) == 2 and abs(_z(ms[0]) - 1.04) < 0.01 and abs(_z(ms[1]) - 1.196) < 0.01, [x.get("z") for x in ms])
        for m in ms:
            fits("%s, zoom %s" % (tag, m.get("z")), m)
        console_clean(tag, R)

    print("--- 6. перетаскивание и растяжение — как раньше, но не за край ---")
    for path, size in (("/ui3", (1600, 1000)), ("/", (853, 533))):
        tag = "%s %dx%d" % (path, size[0], size[1])
        R = run(path, size, steps=(("drag", -40, 25), ("drag", 5000, 5000), ("drag", -9000, -9000),
                                   ("resize", 30, 20, "se"), ("resize", 6000, 6000, "se"),
                                   ("resize", -6000, -6000, "se")))
        if not opened(tag, R):
            continue
        ms = R["m"]
        if len(ms) != 7:
            check("все шаги жестов выполнены (%s)" % tag, False, [x["tag"] for x in ms])
            continue
        o, d1, dfar, dback, r1, rfar, rmin = ms
        for m in ms[1:]:
            fits("%s, после «%s»" % (tag, m["tag"]), m)
        #  Сдвиг мыши (−40, +25); на маленьком экране места может не хватить — тогда окно доходит
        #  ровно до отступа от края и не дальше.
        ex = max(-40.0, -(o["panel"]["l"] - PAD * _z(o)))
        ey = min(25.0, o["ih"] - PAD * _z(o) - o["panel"]["b"])
        check("перетаскивание сдвигает окно ровно на сдвиг мыши (−40, +25), пока есть место (%s)" % tag,
              abs((d1["panel"]["l"] - o["panel"]["l"]) - ex) <= 1.5 and abs((d1["panel"]["t"] - o["panel"]["t"]) - ey) <= 1.5
              and abs(d1["panel"]["w"] - o["panel"]["w"]) <= 0.6,
              (round(d1["panel"]["l"] - o["panel"]["l"], 1), round(d1["panel"]["t"] - o["panel"]["t"], 1),
               "ожидалось", round(ex, 1), round(ey, 1)))
        if size == (1600, 1000):
            check("на просторном экране сдвиг полный — проверка перетаскивания не вырождена (%s)" % tag,
                  ex == -40.0 and ey == 25.0, (ex, ey))
        check("утащенное вправо-вниз окно упирается в край с отступом, а не уходит за экран (%s)" % tag,
              dfar["panel"]["r"] <= dfar["iw"] - 5 and dfar["panel"]["b"] <= dfar["ih"] - 5
              and dfar["panel"]["r"] >= dfar["iw"] - 25 and dfar["panel"]["b"] >= dfar["ih"] - 25,
              (dfar["panel"], dfar["iw"], dfar["ih"]))
        check("утащенное влево-вверх окно упирается в край с отступом (%s)" % tag,
              5 <= dback["panel"]["l"] <= 25 and 5 <= dback["panel"]["t"] <= 25, dback["panel"])
        grew_w, grew_h = r1["panel"]["w"] - dback["panel"]["w"], r1["panel"]["h"] - dback["panel"]["h"]
        room_w = dback["iw"] - dback["panel"]["r"] - PAD * _z(dback)
        room_h = dback["ih"] - dback["panel"]["b"] - PAD * _z(dback)
        check("растяжение за угол растит окно ровно на сдвиг мыши (+30, +20), если есть место (%s)" % tag,
              (abs(grew_w - 30) <= 1.5 if room_w >= 31 else grew_w >= -0.6)
              and (abs(grew_h - 20) <= 1.5 if room_h >= 21 else grew_h >= -0.6),
              (round(grew_w, 1), round(grew_h, 1), round(room_w), round(room_h)))
        z = _z(rmin)
        want_w = min(MINW, int(rmin["iw"] / z - 2 * PAD)) * z
        want_h = min(MINH, int(rmin["ih"] / z - 2 * PAD)) * z
        check("растянуть окно за край нельзя (%s)" % tag,
              rfar["panel"]["r"] <= rfar["iw"] - 5 and rfar["panel"]["b"] <= rfar["ih"] - 5, (rfar["panel"], rfar["iw"], rfar["ih"]))
        check("сжать меньше 620×460 нельзя, а на маленьком экране минимум уступает экрану (%s)" % tag,
              abs(rmin["panel"]["w"] - want_w) <= 1.5 and abs(rmin["panel"]["h"] - want_h) <= 1.5,
              ((round(rmin["panel"]["w"]), round(rmin["panel"]["h"])), (round(want_w), round(want_h))))
        console_clean(tag, R)
    stage.set_api(None)
    stage.stop()

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
sys.exit(1 if _fail else 0)
