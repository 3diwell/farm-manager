# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# «Складской учёт» в оформлении интерфейса 3.0 (R-051).
#
# ЧТО СДЕЛАНО. Окно склада (модуль inventory) на странице 3.0 получило вид остальных экранов
# 3.0: поверхность и скругление панели, вкладки — сегментный переключатель, тихие кнопки,
# карточки-группы, цвета состояний из токенов темы. Сделано ТОЛЬКО листом web/ui3/ui3.css
# (раздел 34): модуль не менялся, интерфейс 2.0 этот лист не подключает.
#
# ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ — вычисленным видом в НАСТОЯЩЕМ браузере (настоящий модуль из
# modules/inventory монтируется настоящим Vue, данные синтетические):
#   1. на /ui3 окно имеет скругление и тень 3.0, фон — поверхность панели 3.0;
#   2. активная вкладка — светлая капсула, а не акцентная «папка»;
#   3. ни одна подпись не вылезает из своей кнопки, вкладки, чипа; дорожка вкладок
#      не выходит за окно и ни одна вкладка не срезана её краем — на четырёх ширинах экрана,
#      в самом маленьком окне склада 620×460 и там же при «Размере текста» 130 % (вкладки
#      переносятся на вторую строку, как в 2.0);
#   3a. значок «мало» у слота, приход/расход в истории катушки и контекстное меню катушки —
#      цветами и видом 3.0; выбранная строка при наведении остаётся акцентной;
#   4. липкая шапка «В работе» того же цвета, что и окно (иначе под ней видна полоса);
#   5. в светлой теме «мало» у склада окрашено светлым токеном предупреждения (#b26a00),
#      а не прежним жёстким #f5a524, и читается на карточке;
#   6. перетаскивание не сломано: положение и размер окна по-прежнему пишет модуль;
#   7. консоль браузера чистая;
#   8. НЕ ВАКУУМ: тот же замер на «/» (интерфейс 2.0) даёт прежний вид — скругление 16 px,
#      тень «0 24px 60px», вкладка-папка. Значит, проверки различают оформления, а слой
#      не утекает в 2.0.
#
# БЕЗОПАСНОСТЬ: стенд tools/_fm_ui_stage.py — статический сервер с синтетическими ответами.
# Рабочая база, папка данных, принтеры и печать не затрагиваются.
#
# Запуск:  python tools/test_inventory_ui3_look.py      (0 = всё в порядке)
# ============================================================================
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage                              # noqa: E402

SENTINEL = "INVENTORY_UI3_LOOK_R051"
CSS = io.open(os.path.join(REPO, "web", "ui3", "ui3.css"), encoding="utf-8").read()

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:400]) if detail else ""))


# ── 1. Лист: раздел склада есть и соблюдает правила слоя ────────────────────────────────────
print("--- 1. лист оформления ---")
_m = re.search(r"/\*\s*── 34\. Складской учёт.*?(?=/\*\s*── 35\.|\Z)", CSS, re.S)
SEC = _m.group(0) if _m else ""
_rules = re.sub(r"/\*.*?\*/", "", SEC, flags=re.S)
check("1. в листе 3.0 есть раздел «Складской учёт»", bool(SEC) and ".fm-inv-panel" in SEC)
check("2. в разделе нет жёстких цветов — только токены темы",
      not re.findall(r"#[0-9a-fA-F]{3,8}\b", _rules), re.findall(r"#[0-9a-fA-F]{3,8}\b", _rules)[:5])
_panel = " ".join(re.findall(r"\.fm-inv-panel\s*\{([^}]*)\}", _rules))
check("3. положение и размер окна слой не задаёт (их пишет модуль — на этом держится перетаскивание)",
      bool(_panel) and not re.search(r"(^|[;\s])(position|left|top|right|bottom|width|height|max-width|max-height)\s*:",
                                     _panel), _panel[:200])
_pads = re.findall(r"\.fm-inv-(?:body|tabpane)\s*\{([^}]*)\}", _rules)
check("4. отступы тела окна не трогаются (на них держится липкая шапка «В работе»)",
      not [p for p in _pads if "padding" in p], _pads)
check("5. пределы высоты не завязаны на vh (html{zoom} делает их выше экрана)",
      not re.search(r"\d+(\.\d+)?vh", _rules))
#  Наведение на выбранную строку: правило «выбранная + наведение» обязано стоять ПОСЛЕ общего
#  наведения того же веса, иначе выбранная строка при наведении гаснет в серый.
_hov = _rules.find(".fm-inv-srow:hover")
_selhov = _rules.find(".fm-inv-srow.selsel:hover")
check("5a. выбранная строка при наведении остаётся акцентной (правило ниже общего наведения)",
      _hov >= 0 and _selhov > _hov and "--fm-accent" in _rules[_selhov:_rules.find("}", _selhov)],
      (_hov, _selhov))
check("5b. дорожка вкладок переносит вкладки, а не прячет их за краем",
      bool(re.search(r"\.fm-inv-tabs\s*\{[^}]*flex-wrap\s*:\s*wrap", _rules)))

# ── 2. Вид в настоящем браузере ─────────────────────────────────────────────────────────────


def _slots(n, feed, labels=None, sp=None):
    return [{"index": i, "unit": 0, "tray": i, "type": "PLA", "color": "", "label": (labels[i] if labels else ""),
             "feed": feed, "spool": (sp if (sp and i == 0) else None)} for i in range(n)]


def _ext():
    return {"index": -1, "unit": None, "tray": None, "type": "", "color": "", "external": True, "spool": None}


SPOOLS = [{"id": 100 + i, "material": m, "color_hex": c, "color_name": cn, "vendor_name": v,
           "weight_total_g": 1000, "weight_remaining_g": w, "status": "in_stock", "ams_printer_id": None,
           "ams_slot": None, "created_at": "2026-09-%02d 10:00:00" % (1 + i)}
          for i, (m, c, cn, w, v) in enumerate([
              ("PETG", "#9ea7ae", "серый", 900, "Generic"), ("PLA", "#e5484d", "красный", 420, "Bambu"),
              ("PLA", "#222222", "чёрный", 80, "Bambu"), ("ABS", "#f5f5f5", "белый", 1000, "eSun"),
              ("PLA", "#f5a524", "оранжевый", 60, "Polymaker")])]
BOUND = dict(SPOOLS[1], id=200, status="loaded", ams_printer_id="P2S", ams_slot=0)
INV = {
    "/api/modules": {"modules": []},
    "/api/mod/inventory/ams": {"printers": [
        {"printer_id": "AD5M", "printer_name": "FlashForge AD5M", "has_ams": False, "feed": "", "slots": [_ext()]},
        {"printer_id": "P2S", "printer_name": "Bambu P2S", "has_ams": True, "feed": "ams",
         "slots": [_ext()] + _slots(4, "ams", sp=BOUND)},
        {"printer_id": "K2P", "printer_name": "Creality K2 Plus", "has_ams": True, "feed": "cfs",
         "slots": [_ext()] + _slots(4, "cfs", ["T1A", "T1B", "T1C", "T1D"])}]},
    "/api/mod/inventory/filament": {"vendors": [{"id": 1, "name": "Generic"}], "filaments": [],
                                    "spools": SPOOLS + [BOUND]},
    "/api/mod/inventory/items": {"items": []},
    "/api/mod/inventory/cost": {"by_material": [], "by_file": [], "spent": 0, "filament_value": 0,
                                "parts_value": 0, "total_value": 0},
    "/api/mod/inventory/settings": {"currency": "RUB", "low_filament_g": 100},
    "/api/mod/inventory/forecast": {"spools": []},
    "/api/mod/inventory/locations": {"locations": []},
}

#  __WIN__ — сохранённая геометрия окна (null — по умолчанию модуля); __LANG__ — язык подписей.
JS = r"""
return new Promise(function(res){ (async function(){
  var out = {errs: []};
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function cs(el){ return el ? getComputedStyle(el) : null; }
  function over(sel, root){ return [].slice.call((root || document).querySelectorAll(sel)).filter(function(e){
      return e.offsetParent !== null && e.scrollWidth - e.clientWidth > 1; })
    .map(function(e){ return (e.className || '') + ': ' + (e.textContent || '').trim().slice(0, 30); }); }
  try {
    await sleep(1200);
    var later = byText('button', ['Позже', 'Later']); if (later) click(later);
    var WIN = __WIN__;
    try { if (WIN) localStorage.setItem('inv_win', JSON.stringify(WIN)); else localStorage.removeItem('inv_win'); } catch (e) {}
    var V = await import('/vendor/vue.esm-browser.js');
    var M = await import('/modules/inventory/InventoryPanel.js');
    var host = document.createElement('div'); document.body.appendChild(host);
    var app = V.createApp(M.default, { open: true, lang: __LANG__, startTab: 'filament',
      access: { contractVersion: 1, can: function(){ return true; } } });
    app.component('svg-icon', { props: ['name'], template: '<i></i>' });
    app.config.errorHandler = function(e){ out.errs.push(String((e && e.message) || e)); };
    var vm = app.mount(host);
    await sleep(900);
    vm.tab = 'warehouse'; vm.wmode = 'work';
    await sleep(500);
    var root = getComputedStyle(document.documentElement);
    out.tok = { base: root.getPropertyValue('--fm-surface-base').trim(), card: root.getPropertyValue('--fm-surface-card').trim(),
                warn: root.getPropertyValue('--fm-warn').trim() };
    var probe = document.createElement('i'); document.body.appendChild(probe);
    probe.style.color = 'var(--fm-surface-base)'; out.tok.baseRgb = getComputedStyle(probe).color;
    probe.style.color = 'var(--fm-surface-card)'; out.tok.cardRgb = getComputedStyle(probe).color;
    probe.style.color = 'var(--fm-warn)'; out.tok.warnRgb = getComputedStyle(probe).color;
    probe.style.color = 'var(--fm-accent)'; out.tok.accentRgb = getComputedStyle(probe).color;
    probe.style.color = 'var(--fm-success)'; out.tok.successRgb = getComputedStyle(probe).color;
    probe.style.color = 'var(--fm-danger)'; out.tok.dangerRgb = getComputedStyle(probe).color;
    probe.remove();
    //  Значок «мало» у слота и приход/расход в истории: те же классы, что в шаблоне модуля,
    //  на пробных элементах — действует весь каскад (app.css модуля + лист 3.0).
    out.marks = {};
    [['slotLow', 'fm-inv-slot-low'], ['histIn', 'fm-inv-hist-k k-in'], ['histOut', 'fm-inv-hist-k k-out']].forEach(function(m){
      var s = document.createElement('span'); s.className = m[1]; s.textContent = '1'; document.body.appendChild(s);
      out.marks[m[0]] = getComputedStyle(s).color; s.remove(); });
    var p = document.querySelector('.fm-inv-panel'), pc = cs(p);
    out.ui3 = document.documentElement.classList.contains('ui3-mode');
    out.panel = pc ? { bg: pc.backgroundColor, br: pc.borderTopLeftRadius, sh: pc.boxShadow,
                       inline: p.getAttribute('style') || '' } : null;
    var pr = p ? p.getBoundingClientRect() : null;
    out.panelRect = pr ? { l: Math.round(pr.left), r: Math.round(pr.right), w: Math.round(pr.width), vw: window.innerWidth } : null;
    var t = document.querySelector('.fm-inv-tab.active'), tc = cs(t);
    out.tab = tc ? { bg: tc.backgroundColor, br: tc.borderTopLeftRadius + ' ' + tc.borderBottomLeftRadius, c: tc.color } : null;
    var tabs = document.querySelector('.fm-inv-tabs'), tr = tabs ? tabs.getBoundingClientRect() : null;
    var tabR = 0; [].slice.call(document.querySelectorAll('.fm-inv-tab')).forEach(function(b){
      tabR = Math.max(tabR, b.getBoundingClientRect().right); });
    out.tabsFit = tabs ? { sw: tabs.scrollWidth, cw: tabs.clientWidth, right: Math.round(tr.right),
                           panelRight: pr ? Math.round(pr.right) : 0, tabR: Math.round(tabR),
                           h: Math.round(tr.height) } : null;
    var hdr = document.querySelector('.fm-inv-prow-h');
    out.stickyBg = hdr ? cs(hdr).backgroundColor : null;
    out.overWork = over('.fm-inv-tab, .fm-inv-kpi, .fm-inv-close, .fm-inv-sum-i, .fm-inv-pfree, .fm-inv-pslot, .fm-inv-psec-h');
    vm.wmode = 'stock';
    await sleep(400);
    var g = vm.warehouseGroups, pla = g.filter(function(x){ return x.material === 'PLA'; })[0];
    if (pla) { vm.toggleMat(pla); await sleep(250); }
    var low = document.querySelector('.fm-inv-schip.low:not(.zero)');
    out.low = low ? { c: cs(low).color, bg: cs(low).backgroundColor } : null;
    var card = low ? low.closest('.fm-inv-mcard') : null;
    out.cardBg = card ? cs(card).backgroundColor : null;
    out.overStock = over('.fm-inv-btn, .fm-inv-schip, .fm-inv-sort button, .fm-inv-fsel, .fm-inv-freset');
    //  Справка: числа группы в самом узком окне режет раскладка самого модуля (так и в 2.0).
    out.overStats = over('.fm-inv-mstat-v, .fm-inv-msum');
    //  Контекстное меню катушки (правый щелчок) — настоящее меню модуля.
    vm.spoolMenu({ clientX: 300, clientY: 200 }, vm.spools[0]);
    await sleep(250);
    var cm = document.querySelector('.fm-inv-ctx'), cmc = cs(cm);
    var dz = cm ? cm.querySelector('.ctx-item.danger') : null;
    out.ctx = cmc ? { bg: cmc.backgroundColor, br: cmc.borderTopLeftRadius, sh: cmc.boxShadow,
                      itBr: cm.querySelector('.ctx-item') ? cs(cm.querySelector('.ctx-item')).borderTopLeftRadius : '',
                      danger: dz ? cs(dz).color : '' } : null;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await sleep(150);
    out.hscroll = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    out.lang = __LANG__;
  } catch (e) { out.fatal = String((e && e.stack) || e); }
  res(dump(out));
})(); });
"""


def _rgb(s):
    """rgb()/rgba() или color(srgb r g b / a) — так браузер пишет результат color-mix()."""
    s = s or ""
    m = re.findall(r"[\d.]+", s.replace("srgb", ""))
    if len(m) < 3:
        return None
    v = [float(x) for x in m[:4]]
    if s.strip().startswith("color("):
        v = [x * 255.0 for x in v[:3]] + v[3:]
    return tuple(v)


def _lum(c):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _over(fg, bg):
    """Цвет с прозрачностью поверх непрозрачной подложки."""
    a = fg[3] if len(fg) > 3 else 1.0
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3))


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def run(path, size, win=None, lang="ru"):
    stage.set_api(INV)
    js = JS.replace("__WIN__", json.dumps(win)).replace("__LANG__", json.dumps(lang))
    return stage.run(js, window_size=size, settle_ms=2500, path=path)


def ui3_checks(tag, R):
    if not R or R.get("fatal"):
        check("6. склад открылся на /ui3 (%s)" % tag, False, (R or {}).get("fatal") or stage.last_diag())
        return
    check("6. склад открылся на /ui3 (%s)" % tag, bool(R.get("panel")) and R.get("ui3"), R.get("panel"))
    pnl, tok = R.get("panel") or {}, R.get("tok") or {}
    check("7. окно скруглено как панели 3.0 (18 px) (%s)" % tag, pnl.get("br") == "18px", pnl.get("br"))
    check("8. тень окна — 3.0 с внутренним светом, не прежняя «0 24px 60px» (%s)" % tag,
          "inset" in (pnl.get("sh") or "") and "24px 60px" not in (pnl.get("sh") or ""), pnl.get("sh"))
    check("9. фон окна — поверхность панели 3.0 (%s)" % tag, pnl.get("bg") == tok.get("baseRgb"),
          (pnl.get("bg"), tok.get("baseRgb")))
    tab = R.get("tab") or {}
    check("10. активная вкладка — светлая капсула, без акцентной заливки и «папки» (%s)" % tag,
          tab.get("bg") == tok.get("cardRgb") and tab.get("br", "").split(" ")[0] == tab.get("br", "").split(" ")[-1]
          and tab.get("c") != tok.get("accentRgb"), tab)
    tf = R.get("tabsFit") or {}
    check("11. дорожка вкладок целиком внутри окна, ни одна вкладка не срезана её краем (%s)" % tag,
          bool(tf) and tf.get("sw", 1) <= tf.get("cw", 0) + 1 and tf.get("right", 1) <= tf.get("panelRight", 0) + 1
          and tf.get("tabR", 1) <= tf.get("right", 0) + 1, tf)
    check("12. подписи не вылезают из кнопок, вкладок и чипов (%s)" % tag,
          not (R.get("overWork") or []) and not (R.get("overStock") or []),
          (R.get("overWork") or []) + (R.get("overStock") or []))
    if R.get("overStats"):
        print("      (справка, модуль: числа группы обрезаны раскладкой модуля и в 2.0: %s)"
              % "; ".join(R["overStats"][:3]))
    check("13. липкая шапка «В работе» того же цвета, что окно (%s)" % tag,
          R.get("stickyBg") == pnl.get("bg"), (R.get("stickyBg"), pnl.get("bg")))
    check("14. окно по-прежнему ставит и растягивает модуль (инлайн-геометрия на месте) (%s)" % tag,
          "left:" in (pnl.get("inline") or "").replace(" ", "") and "width:" in (pnl.get("inline") or "").replace(" ", ""),
          pnl.get("inline"))
    check("15. «мало» окрашено токеном предупреждения темы (%s)" % tag,
          bool(R.get("low")) and (R.get("low") or {}).get("c") == tok.get("warnRgb"), (R.get("low"), tok.get("warnRgb")))
    mk = R.get("marks") or {}
    check("15a. значок «мало» у слота и приход/расход истории — цветами темы (%s)" % tag,
          mk.get("slotLow") == tok.get("warnRgb") and mk.get("histIn") == tok.get("successRgb")
          and mk.get("histOut") == tok.get("dangerRgb"),
          (mk, tok.get("warnRgb"), tok.get("successRgb"), tok.get("dangerRgb")))
    cx = R.get("ctx") or {}
    check("15b. контекстное меню катушки — меню 3.0: поверхность карточки, 12 px, тень 3.0 (%s)" % tag,
          cx.get("bg") == tok.get("cardRgb") and cx.get("br") == "12px" and cx.get("itBr") == "8px"
          and "12px 40px" not in (cx.get("sh") or "") and cx.get("danger") == tok.get("dangerRgb"), cx)
    check("16. горизонтальной прокрутки страницы нет (%s)" % tag, (R.get("hscroll") or 0) <= 0, R.get("hscroll"))
    probs = stage.page_problems(R) + ["ошибка Vue: %s" % e for e in (R.get("errs") or [])]
    check("17. консоль браузера чистая (%s)" % tag, not probs, probs[:3])
    return R


if not stage.engine_ready():
    check("5a. браузерный движок доступен (без него вид проверить нечем)", False, str(stage.last_diag())[:250])
else:
    print("--- 2. вид на /ui3: тёмная тема, четыре ширины экрана ---")
    for size in ((1280, 800), (1440, 900), (1600, 1000), (1920, 1080)):
        R = ui3_checks("%dx%d" % size, run("/ui3", size))
        if R and R.get("panelRect"):
            pr = R["panelRect"]
            #  Справка, не проверка: положение окна ставит модуль. До склада 1.7.32 окно под
            #  html{zoom} уходило за правый край; что оно целиком на экране, доказывает
            #  tools/test_inventory_window_fits.py.
            print("      (окно: левый край %s, правый %s, ширина экрана %s)" % (pr["l"], pr["r"], pr["vw"]))
    print("--- 3. самое маленькое окно склада 620×460 и английские подписи ---")
    ui3_checks("окно 620×460, en", run("/ui3", (1280, 800), win={"x": 20, "y": 20, "w": 620, "h": 460}, lang="en"))
    ui3_checks("окно 620×460, ru", run("/ui3", (1280, 800), win={"x": 20, "y": 20, "w": 620, "h": 460}))
    print("--- 3a. «Размер текста» 130 % в самом маленьком окне: вкладки переносятся, а не срезаются ---")
    for _lg in ("ru", "en"):
        R13 = ui3_checks("окно 620×460, 130 %%, %s" % _lg,
                         run("/ui3?ls=ui_text_size:130", (1280, 800), win={"x": 20, "y": 20, "w": 620, "h": 460}, lang=_lg))
        if R13 and R13.get("tabsFit"):
            print("      (дорожка вкладок: высота %s, ширина %s/%s)"
                  % (R13["tabsFit"].get("h"), R13["tabsFit"].get("sw"), R13["tabsFit"].get("cw")))
    print("--- 4. светлая тема 3.0 ---")
    RL = ui3_checks("светлая", run("/ui3?ls=farm_theme:light", (1440, 900)))
    if RL and RL.get("low") and RL.get("cardBg"):
        _bg = _rgb(RL["cardBg"])
        _fg = _over(_rgb(RL["low"]["c"]), _bg)
        _chip = _over(_rgb(RL["low"]["bg"]), _bg)
        _k = _contrast(_fg, _chip)
        check("18. в светлой теме «мало» — светлый янтарный #b26a00, а не прежний #f5a524",
              RL["low"]["c"] == "rgb(178, 106, 0)", RL["low"])
        check("19. «мало» читается на своём чипе в светлой теме (контраст ≥ 3)", _k >= 3.0, round(_k, 2))
    else:
        check("18. в светлой теме «мало» — светлый янтарный", False, (RL or {}).get("low"))
    print("--- 5. не вакуум: интерфейс 2.0 («/») остаётся прежним ---")
    R2 = run("/", (1440, 900))
    if not R2 or R2.get("fatal"):
        check("20. склад открылся на «/»", False, (R2 or {}).get("fatal") or stage.last_diag())
    else:
        p2, t2 = R2.get("panel") or {}, R2.get("tab") or {}
        check("20. на «/» слой 3.0 не подключён", R2.get("ui3") is False, R2.get("ui3"))
        check("21. на «/» окно прежнее: скругление 16 px и тень «0 24px 60px»",
              p2.get("br") == "16px" and "24px 60px" in (p2.get("sh") or ""), p2)
        check("22. на «/» вкладка прежняя — «папка» со скруглением только сверху",
              t2.get("br") == "9px 0px", t2)
        check("23. те же замеры различают оформления (2.0 ≠ 3.0) — проверки выше не пустые",
              p2.get("br") != "18px" and "inset" not in (p2.get("sh") or ""), p2)
        m2 = R2.get("marks") or {}
        check("23a. на «/» цвета модуля прежние (#2ea043 / #e5484d) — слой 3.0 в 2.0 не утекает",
              m2.get("histIn") == "rgb(46, 160, 67)" and m2.get("histOut") == "rgb(229, 72, 77)", m2)
        c2 = R2.get("ctx") or {}
        check("23b. на «/» контекстное меню прежнее (скругление .6rem, тень «0 12px 40px»)",
              c2.get("br") != "12px" and "12px 40px" in (c2.get("sh") or ""), c2)
        probs = stage.page_problems(R2)
        check("24. консоль браузера чистая на «/»", not probs, probs[:3])
    stage.set_api(None)
    stage.stop()

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
sys.exit(1 if _fail else 0)
