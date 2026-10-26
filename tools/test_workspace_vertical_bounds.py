# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""
Alpha 2.817 — единая вертикальная граница рабочих экранов (Настройки/Диагностика/Проекты).

Требование пользователя (два эталонных скриншота 2.816): нижний край статичных рабочих экранов
«Настройки» и «Диагностика/Журнал» уходил ниже видимой рабочей области — ниже нижней границы левой
колонки принтеров (внешнего контура блока «Подсказки»). Нужно: нижняя граница Settings, Diagnostics и
обычной области Projects/Tasks совпадает с нижней границей левой колонки, содержимое настроек и журнала
прокручивается ТОЛЬКО внутри своих панелей, страница целиком не прокручивается.

Root cause (категория F). Левая колонка (`.left-col`) и `<main class="projects-pane">` получают ЯВНУЮ
высоту `leftColH` (JS `recalcLeftCol`: замер визуального верха колонки → доступная высота → делёж на
совокупный zoom из-за двойного zoom `.zoom-wrap`×html, введён Alpha 2.631). Статичные экраны 2.816
`.fm-settings-workspace`/`.fm-diagnostics-workspace` в этот контракт НЕ были включены и держались на
CSS `height:100%` от zoom-раздутого `.main-cols`, поэтому рендерились ниже видимой области. Внутренний
CSS-контракт 2.816 (`min-height:0`, `overflow:hidden`, `box-sizing:border-box`, тело — `overflow:auto`)
был корректен — не хватало только общей высоты. Фикс 2.817: оба экрана привязаны к тому же `leftColH`,
что и колонка принтеров и Проекты (одна вертикальная строка, одна высота).

Тест полностью офлайновый: разбор шаблона/CSS/JS-исходников + геометрический замер в РЕАЛЬНОМ движке
(headless Edge/Chromium — тот же безопасный стенд, что у inventory-layout тестов) на факовых viewport/DPI
с ВОСПРОИЗВЕДЕНИЕМ двойного zoom и НАСТОЯЩЕЙ формулы recalcLeftCol. Рабочая БД, DATA_DIR, config, сеть и
принтеры не используются; GUI не открывается; временное — в TemporaryDirectory, он удаляется.
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _edge_dom   # Alpha 2.834: DOM через CDP + проверка живости движка

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(PROJ, "web")

# Метка живёт ТОЛЬКО в этой оснастке и во временных файлах. В продукт, БД, DATA_DIR, config, логи,
# модули, ZIP, профиль WebView, _incoming/ и команды принтерам не попадает.
SENTINEL = "WORKSPACE_VERTICAL_BOUNDS_SENTINEL_2_817"

NODE = r"C:\Program Files\nodejs\node.exe"
_EDGE_CANDIDATES = [
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
# FM_VB_NO_ENGINE=1 отключает геометрический замер в headless-движке (используется быстрым
# mutation-proof стендом — статические проверки ловят все мутации детерминированно). В обычном
# прогоне переменная не установлена → геометрия выполняется полностью, без пропусков.
EDGE = None if os.environ.get("FM_VB_NO_ENGINE") else next(
    (p for p in _EDGE_CANDIDATES if p and os.path.isfile(p)), None)

# Alpha 2.835: наличие бинарника не значит работоспособность, НО неработоспособность движка
# больше НЕ повод пропускать браузерные проверки — это КРАСНЫЙ тест с точной причиной. Прежний
# SKIP был слепой зоной: именно он однажды спрятал реальный дефект интерфейса.
_ENGINE_WHY = ""
if not EDGE:
    _ENGINE_WHY = "движок рендера (Edge/Chrome) не найден"
elif not _edge_dom.engine_usable(EDGE):
    _ENGINE_WHY = "движок найден (%s), но не отдаёт документ по CDP" % EDGE
    EDGE = None

_fail = 0
_pass = 0
_skip = 0


def check(name, cond, detail=""):
    global _fail, _pass
    if cond:
        _pass += 1
        print("ok   %s" % name)
    else:
        _fail += 1
        print("FAIL — %s%s" % (name, (" | " + detail) if detail else ""))


def skip(name, why):
    global _skip
    _skip += 1
    print("SKIP — %s [%s]" % (name, why))


def rd(p):
    return io.open(p, encoding="utf-8", newline="").read()


HTML = rd(os.path.join(WEB, "index.html"))
CSS = rd(os.path.join(WEB, "app.css"))
APP = rd(os.path.join(WEB, "app.js"))
SRV = rd(os.path.join(PROJ, "server.py"))
ORCH = rd(os.path.join(PROJ, "app", "project_orchestrator.py"))
CSS_NS = CSS.replace(" ", "")


def open_tag(anchor):
    """Открывающий тег элемента, найденного по подстроке anchor (обычно class="...)."""
    i = HTML.find(anchor)
    if i < 0:
        return ""
    s = HTML.rfind("<", 0, i)
    e = HTML.find(">", i)
    return HTML[s:e + 1] if s >= 0 and e > 0 else ""


def style_of(tag):
    m = re.search(r':style="([^"]*)"', tag)
    return m.group(1) if m else ""


def height_expr(style):
    """Значение ключа height из объектного литерала :style (до запятой/})."""
    m = re.search(r"height\s*:\s*([^,}]+)", style)
    return m.group(1).strip() if m else ""


def binds_leftcolh(tag):
    return re.search(r"height\s*:\s*leftColH\b", style_of(tag)) is not None


def css_el_rule(cls):
    """Тело всех правил, стилизующих САМ элемент cls (включая групповые `.a,.b{}`), но не детей."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        for one in m.group(1).split(","):
            one = one.strip()
            if one and one.split()[-1] == cls:
                out.append(m.group(2))
                break
    return " ".join(out)


# Открывающие теги ключевых узлов вертикальной цепочки
T_SET = open_tag('class="fm-settings-workspace"')
T_DIAG = open_tag('class="fm-diagnostics-workspace"')
T_LEFT = open_tag('class="left-col')
T_PROJ = open_tag('class="projects-pane')
CLS_ZOOM = (re.search(r'class="([^"]*)"', open_tag('class="zoom-wrap')) or [None, ""])[1]
CLS_HEADER = (re.search(r'class="([^"]*)"', open_tag('class="app-header')) or [None, ""])[1]
CLS_MAINCOLS = (re.search(r'class="([^"]*)"', open_tag('class="main-cols')) or [None, ""])[1]
CLS_SUGGEST = (re.search(r'class="([^"]*)"', open_tag('class="suggest-pane')) or [None, ""])[1]
# Обёртка ряда — родитель main-cols
_mc = HTML.find('class="main-cols')
_wrap_open = HTML.rfind("<div", 0, HTML.rfind("<div", 0, _mc))
CLS_ROWWRAP = (re.search(r'class="([^"]*)"', HTML[_wrap_open:HTML.find(">", _wrap_open) + 1]) or [None, ""])[1]

SET_STYLE = style_of(T_SET)
DIAG_STYLE = style_of(T_DIAG)

print("=== A. Корневая цепочка высоты (html → main-cols) ===")
# 1–5 корневой каркас: колонка-flex, шапка не растягивается, ряд занимает остаток с min-height:0
check("1. корневой каркас Farm Manager — колонка на всю высоту (zoom-wrap: h-full flex flex-col)",
      "h-full" in CLS_ZOOM and "flex" in CLS_ZOOM and "flex-col" in CLS_ZOOM)
check("2. верхняя панель не растягивается (app-header shrink-0 = flex:0 0 auto)",
      "shrink-0" in CLS_HEADER)
check("3. основной ряд занимает остаток высоты (обёртка ряда flex-1)",
      "flex-1" in CLS_ROWWRAP)
check("4. обёртка ряда имеет min-height:0 и клип (flex-дети не раздувают высоту)",
      "min-h-0" in CLS_ROWWRAP and "overflow-hidden" in CLS_ROWWRAP)
check("5. main-cols имеет min-height:0 (замкнутая flex-цепочка, без min-height:auto)",
      "min-h-0" in CLS_MAINCOLS and "h-full" in CLS_MAINCOLS)
# 6–8 sidebar и workspace: min-height:0 у обоих
check("6. левая колонка имеет min-height:0",
      "min-h-0" in (re.search(r'class="([^"]*)"', T_LEFT) or [None, ""])[1])
_setcss = css_el_rule(".fm-settings-workspace").replace(" ", "")
_diagcss = css_el_rule(".fm-diagnostics-workspace").replace(" ", "")
check("7. рабочий экран настроек имеет min-height:0",
      "min-height:0" in _setcss)
check("8. рабочий экран диагностики имеет min-height:0",
      "min-height:0" in _diagcss)
# 9, 10 — глобальная блокировка прокрутки страницы (2.631) на месте
check("9. html/body не прокручиваются глобально (overflow:hidden !important, 2.631)",
      re.search(r"html,\s*body\s*\{[^}]*overflow:\s*hidden\s*!important", CSS) is not None)
check("10. main-cols не имеет собственного вертикального overflow (ряд не скроллит)",
      "overflow-y" not in CLS_MAINCOLS and "overflow-auto" not in CLS_MAINCOLS
      and "overflow:auto" not in css_el_rule(".main-cols").replace(" ", ""))

print("=== B. Единый вертикальный контракт: все три экрана держатся на leftColH ===")
# 11–14 — sidebar, Projects, Settings, Diagnostics привязаны к ОДНОЙ высоте leftColH
check("11. левая колонка привязана к leftColH", binds_leftcolh(T_LEFT))
#  2.975: правая половина кончается там же, где подсказки — у неё своя высота rightColH
#  с откатом к leftColH. Проверяем ровно это выражение: своих чисел по-прежнему нет.
check("12. Projects (projects-pane) привязан к общей высоте (rightColH || leftColH)",
      binds_leftcolh(T_PROJ) or "(rightColH || leftColH)" in T_PROJ, T_PROJ[:120])
check("13. Settings workspace привязан к leftColH (фикс 2.817)", binds_leftcolh(T_SET),
      "style=" + SET_STYLE)
check("14. Diagnostics workspace привязан к leftColH (фикс 2.817)", binds_leftcolh(T_DIAG),
      "style=" + DIAG_STYLE)
# 15 — ВСЕ используют ровно одно и то же выражение leftColH (без своего числа/оффсета на монитор)
_heights = [height_expr(style_of(t)) for t in (T_LEFT, T_PROJ, T_SET, T_DIAG)]
check("15. высота всех экранов — общая переменная (leftColH; у правой половины — rightColH "
      "с откатом), без своих чисел и оффсетов",
      all(h in ("leftColH", "(rightColH || leftColH)") for h in _heights), str(_heights))
# 16 — нет хардкода taskbar/пикселей и нет calc(100vh-…) в стилях экранов
check("16. нет хардкода высоты taskbar и произвольных px-оффсетов в стилях экранов",
      not re.search(r"calc\(\s*100vh", SET_STYLE + DIAG_STYLE)
      and not re.search(r"leftColH\s*[-+]\s*\d", SET_STYLE + DIAG_STYLE)
      and "taskbar" not in (SET_STYLE + DIAG_STYLE).lower())
# 17 — нет 100vh в CSS-правилах экранов (высота не завязана на viewport в обход main-row)
check("17. в CSS рабочих экранов нет 100vh (высота идёт от родителя, не от viewport)",
      "100vh" not in _setcss and "100vh" not in _diagcss)
# 18 — leftColH это ОДИН источник: тот же ref в setup-возврате app.js
check("18. leftColH — единый источник высоты (общий ref в app.js)",
      "const leftColH = ref(null)" in APP and re.search(r"\bleftColH\b", APP.split("return {")[-1]) is not None)

print("=== C. Механизм leftColH: замер по колонке, делёж на zoom, без якоря по «Подсказкам» ===")
_recalc = APP[APP.find("const recalcLeftCol ="):APP.find("const recalcLeftCol =") + 800]
check("19. recalcLeftCol замеряет верх ИМЕННО левой колонки, а не блока «Подсказки»",
      "querySelector('.left-col')" in _recalc and "suggest" not in _recalc)
check("20. высота считается от доступной высоты окна (window.innerHeight), без хардкода taskbar",
      "window.innerHeight" in _recalc and not re.search(r"innerHeight\s*-\s*\d{2,}\s*-\s*\d", _recalc))
# Alpha 2.869: раньше проверка искала константу _WRAP_ZOOM. В коде она давно заменена ЖИВЫМ замером
# _wrapZoom() (константа _WRAP_BASE_ZOOM осталась только проектным значением), и проверка краснела
# на исправном коде минимум с 2.863. Смысл прежний: делим на СОВОКУПНЫЙ zoom — html и .zoom-wrap.
#  2.975: совокупный масштаб считается заранее в _k, деление идёт на него.
check("21. визуальные px переводятся в css делением на совокупный zoom (двойной zoom учтён)",
      "_wrapZoom()" in _recalc and "getComputedStyle(document.documentElement).zoom" in _recalc
      and ("avail / (" in _recalc or "avail / _k" in _recalc))
check("22. высота пересчитывается на resize и при старте (общая граница движется вместе)",
      "window.addEventListener('resize', _onResize)" in APP
      and "nextTick(recalcLeftCol)" in APP.replace("nextTick(() => { recalcLeftCol();", "nextTick(recalcLeftCol)")
      and "recalcLeftCol()" in APP)
check("23. защита от абсурдных значений — на маленькой высоте leftColH сбрасывается (fallback CSS)",
      "avail < 200" in _recalc and "leftColH.value = null" in _recalc)

print("=== D. Settings: внешние границы и ВНУТРЕННЯЯ прокрутка ===")
check("24. рамка Settings видима (граница на самом экране)",
      "border:1px" in _setcss and "border-radius" in _setcss)
check("25. Settings не выпускает содержимое за рамку (overflow:hidden, box-sizing:border-box)",
      "overflow:hidden" in _setcss and "box-sizing:border-box" in _setcss)
check("26. заголовок Settings фиксирован (flex:0 0 auto у .fm-set-title)",
      "flex:0 0 auto" in css_el_rule(".fm-set-title"))
check("27. layout настроек имеет min-height:0 (замкнутая цепочка до скролла)",
      "min-height:0" in css_el_rule(".fm-set-layout").replace(" ", "")
      and "flex:1" in css_el_rule(".fm-set-layout").replace(" ", ""))
check("28. содержимое настроек прокручивается ВНУТРИ (.fm-set-scroll overflow-y:auto + min-height:0)",
      "overflow-y:auto" in css_el_rule(".fm-set-scroll").replace(" ", "")
      and "min-height:0" in css_el_rule(".fm-set-scroll").replace(" ", ""))

print("=== E. Diagnostics: внешние границы и ВНУТРЕННЯЯ прокрутка ===")
check("29. рамка Diagnostics видима",
      "border:1px" in _diagcss and "border-radius" in _diagcss)
check("30. Diagnostics не выпускает содержимое за рамку (overflow:hidden, box-sizing:border-box)",
      "overflow:hidden" in _diagcss and "box-sizing:border-box" in _diagcss)
check("31. toolbar диагностики зафиксирован сверху (.diag-head flex-shrink:0)",
      "flex-shrink:0" in css_el_rule(".diag-head").replace(" ", ""))
check("32. журнал прокручивается ВНУТРИ (.diag-body overflow-y:auto + min-height:0)",
      "overflow-y:auto" in css_el_rule(".diag-body").replace(" ", "")
      and "min-height:0" in css_el_rule(".diag-body").replace(" ", ""))
check("33. длинная запись не расширяет контейнер по вертикали (тело скроллит, а не растёт)",
      "flex:1" in css_el_rule(".diag-body").replace(" ", ""))

print("=== F. Projects использует тот же host и сохраняет состояние ===")
check("34. Projects рендерится в том же ряду main-cols",
      HTML.find('class="projects-pane') > HTML.find('class="main-cols'))
check("35. Projects прокручивается внутри себя (overflow-y-auto), не тянет страницу",
      "overflow-y-auto" in (re.search(r'class="([^"]*)"', T_PROJ) or [None, ""])[1])
check("36. переключение экранов не пересоздаёт DOM Проектов (v-show, а не v-if)",
      "v-show=" in T_PROJ and "v-if=" not in T_PROJ)
check("37. Projects/Settings/Diagnostics — соседи одного host (один переключаемый слот)",
      HTML.find('class="fm-settings-workspace"') > HTML.find('class="main-cols')
      and HTML.find('class="fm-diagnostics-workspace"') > HTML.find('class="main-cols'))

print("=== G. Регрессия и границы ===")
check("38. рабочая область 2.816 сохранена (экраны в потоке, без position:fixed)",
      "position:fixed" not in _setcss and "position:fixed" not in _diagcss)
check("39. стек вложенных модалей 2.815 сохранён",
      "fmModalStack" in APP and "v-modal-layer" in HTML and "id=\"fm-overlay-root\"" in HTML)
check("40. служба смены порта 2.814 сохранена",
      "_prepare_port_change" in SRV and "showPortDialog" in APP)
check("41. встроенный журнал 2.813 сохранён",
      "diagSearch" in APP and "toggleDiagPause" in APP)
check("42. резолвер активного порта 2.812 сохранён",
      "find_running_local" in rd(os.path.join(PROJ, "app", "desktop_shell.py")))
check("43. packaged restart E2E 2.811 сохранён",
      os.path.isfile(os.path.join(PROJ, "tools", "test_packaged_restart_end_to_end.py")))
check("44. управление модулями сохранено", "/api/modules/" in APP and "disableModule" in APP)
check("45. интеграция со слайсером сохранена", "'Интеграция со слайсером'" in HTML)
check("46. жизненный цикл внешней печати сохранён",
      os.path.isfile(os.path.join(PROJ, "tools", "test_external_reprint_sync.py")))
check("47. схема БД не менялась этой правкой",
      not re.search(r"(ALTER TABLE|DROP TABLE|CREATE TABLE)", HTML + CSS))
check("48. маршруты не добавлялись (фронтовая правка)",
      "@app.get" not in HTML and "@app.post" not in HTML)
check("49. файлы модулей и ZIP не трогались правкой",
      not re.search(r"modules[/\\][A-Za-z_]+\.zip", HTML + CSS))
check("50. автоматическая отправка выключена", "\nDISPATCH_ENABLED = False" in ORCH)
check("51. транспорт выключен", "\nTRANSPORT_ENABLED = False" in ORCH)
check("52. правка не отправляет команд принтерам",
      not re.search(r"(gcode_line|/api/print/start)", CSS)
      and "fm-settings-workspace" not in SRV and "leftColH" not in SRV)
check("53. каталог _incoming/ не используется", "_incoming" not in (HTML + CSS + APP))
check("54. правка минимальна: CSS-контракт 2.816 сохранён (height:100% fallback у экранов, app.css не переписана)",
      "height:100%" in _setcss and "height:100%" in _diagcss)

print("=== H. Геометрия в РЕАЛЬНОМ движке (headless Edge): нижние границы совпадают ===")
# Воспроизводим двойной zoom (html 1.196 × zoom-wrap 1.0971662034375) и НАСТОЯЩУЮ формулу recalcLeftCol.
# applyToWs отражает ФАКТИЧЕСКУЮ привязку продукта: если экран привязан к leftColH — в макете он тоже её
# получает и обязан совпасть с колонкой; если привязку убрать (мутация) — макет оставит height:100% и
# нижняя граница разойдётся, проверка «совпадает» станет красной.
_WRAP_ZOOM = "1.0971662034375"


def _page(win_h, apply_ws, kind):
    inner_scroll_id = "scr"
    if kind == "settings":
        body_inner = ('<div class="fm-set-title">T</div><div class="fm-set-layout">'
                      '<div class="fm-set-scroll" id="scr">' + ("<p>l</p>" * 240) + "</div></div>")
        ws_cls = "fm-settings-workspace"
    else:
        body_inner = ('<div class="diag-head">H</div><div class="diag-body" id="scr">'
                      + ("<div>row</div>" * 240) + "</div>")
        ws_cls = "fm-diagnostics-workspace"
    apply_js = "true" if apply_ws else "false"
    return (
        '<!doctype html><html style="zoom:1.196"><head><meta charset="utf-8"><style>'
        ":root{--fm-border-strong:#666;--fm-surface-base:#1c1c1e;--fm-border-soft:#333;--fm-border:#444;"
        "--fm-blue-06:#123;--fm-text-bright:#fff;--fm-surface-control:#222}"
        "*{box-sizing:border-box}"
        "html,body{margin:0;height:100%;overflow:hidden;background:#141416;font:13px system-ui;color:#ddd}"
        "#__res{position:fixed;left:-9999px;top:0}"
        "#app{height:100%;width:100%;position:relative}"
        ".zoom-wrap{height:100%;display:flex;flex-direction:column;zoom:" + _WRAP_ZOOM + ";padding:8px 16px 0}"
        ".app-header{flex:0 0 auto;height:48px;background:#222}"
        ".rowwrap{flex:1 1 auto;overflow:hidden;width:100%;min-height:0}"
        ".main-cols{display:flex;gap:8px;align-items:flex-start;width:100%;position:relative;height:100%;min-height:0}"
        ".left-col{width:360px;flex:0 0 auto;height:100%;min-height:0;display:flex;flex-direction:column;gap:8px}"
        ".pc-list{flex:1 1 auto;min-height:0;overflow:auto;background:#1a1a1c;border:1px solid #333;border-radius:12px}"
        ".suggest-pane{flex:0 0 auto;background:#202024;border:1px solid #333;border-radius:16px;padding:10px;height:120px}"
        ".fm-settings-workspace,.fm-diagnostics-workspace{flex:1 1 auto;display:flex;flex-direction:column;"
        "width:100%;height:100%;min-width:0;min-height:0;box-sizing:border-box;overflow:hidden;"
        "border:1px solid var(--fm-border-strong);border-radius:14px;background:var(--fm-surface-base)}"
        ".fm-set-title{padding:13px 16px;border-bottom:1px solid var(--fm-border-soft);flex:0 0 auto}"
        ".fm-set-layout{display:flex;flex:1 1 auto;min-height:0;flex-direction:column}"
        ".fm-set-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;padding:16px 20px 18px}"
        ".diag-head{padding:14px 18px;border-bottom:1px solid var(--fm-border);flex-shrink:0}"
        ".diag-body{flex:1;overflow-y:auto;min-height:0;padding:10px 18px}"
        "</style></head><body><div id=\"app\"><div class=\"zoom-wrap\">"
        "<header class=\"app-header\">H</header>"
        "<div class=\"rowwrap\"><div class=\"main-cols\">"
        "<div class=\"left-col\" id=\"left\"><div class=\"pc-list\">p</div><div class=\"suggest-pane\" id=\"sug\">S</div></div>"
        "<section class=\"" + ws_cls + "\" id=\"ws\">" + body_inner + "</section>"
        "</div></div></div></div><pre id=\"__res\"></pre><script>"
        "var _WZ=" + _WRAP_ZOOM + ";"
        "function recalc(){var el=document.querySelector('.left-col');var top=el.getBoundingClientRect().top;"
        "var avail=window.innerHeight-top-12;var hz=parseFloat(getComputedStyle(document.documentElement).zoom)||1.04;"
        "return avail<200?null:Math.round(avail/(hz*_WZ))+'px';}"
        "var R={winH:" + str(win_h) + ",innerH:window.innerHeight,htmlZoom:getComputedStyle(document.documentElement).zoom};"
        "var L=document.getElementById('left'),W=document.getElementById('ws'),SC=document.getElementById('" + inner_scroll_id + "');"
        "R.leftTop=Math.round(L.getBoundingClientRect().top*10)/10;R.wsTop=Math.round(W.getBoundingClientRect().top*10)/10;"
        "var h=recalc();R.leftColH=h;"
        "if(h){L.style.height=h; if(" + apply_js + ") W.style.height=h;}"
        "R.leftBottom=Math.round(L.getBoundingClientRect().bottom*10)/10;"
        "R.wsBottom=Math.round(W.getBoundingClientRect().bottom*10)/10;"
        "R.wsHeight=Math.round(W.getBoundingClientRect().height*10)/10;"
        "R.scrollable=SC.scrollHeight-SC.clientHeight;"
        "SC.scrollTop=SC.scrollHeight;R.reachedBottom=(SC.scrollHeight-SC.clientHeight-SC.scrollTop)<2;"
        "R.wsHeightAfterScroll=Math.round(W.getBoundingClientRect().height*10)/10;"
        "R.bodyScroll=document.body.scrollHeight-document.body.clientHeight;"
        "R.docScroll=document.documentElement.scrollHeight-document.documentElement.clientHeight;"
        "document.getElementById('__res').textContent='@@RES@@'+JSON.stringify(R)+'@@END@@';"
        "</script></body></html>")


def _run(td, win_w, win_h, dpi, apply_ws, kind, idx):
    pg = os.path.join(td, "vb_%s_%d_%s_%d.html" % (kind, win_h, apply_ws, idx))
    io.open(pg, "w", encoding="utf-8", newline="\n").write(_page(win_h, apply_ws, kind))
    prof = os.path.join(td, "prof_%d" % idx)
    # Alpha 2.834: Edge 150 перестал печатать документ по --dump-dom (rc=0, stdout пуст) — DOM
    # берём из ТОГО ЖЕ headless-Edge через CDP (tools/_edge_dom.py). Проверки ниже не изменены.
    dom = _edge_dom.dump_dom_compatible(EDGE, "file:///" + pg.replace("\\", "/"), prof,
                                        window_size=(win_w, win_h), budget_ms=5000,
                                        extra_args=("--force-device-scale-factor=%s" % dpi,))
    m = re.search(r"@@RES@@(\{.*?\})@@END@@", dom, re.S)
    return json.loads(m.group(1)) if m else None


if not EDGE:
    for lbl in ["desktop 1440x900", "short 1440x768", "large 1920x1080", "1366x768",
                "DPI 125%", "DPI 150%", "diag 1440x900", "diag 1920x1080", "bug-repro"]:
        check("H. геометрия (%s)" % lbl, False, _ENGINE_WHY)
    _tmp_gone = True
else:
    ws_set_binds = binds_leftcolh(T_SET)
    ws_diag_binds = binds_leftcolh(T_DIAG)
    TOL = 2.0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_vb_" + SENTINEL[-8:] + "_") as td:
        idx = 0
        # H1–H6: Settings-экран, разные viewport и DPI — нижняя граница совпадает с колонкой
        matrix = [("desktop 1440x900", 1440, 900, "1"), ("короткий 1440x768", 1440, 768, "1"),
                  ("большой 1920x1080", 1920, 1080, "1"), ("1366x768", 1366, 768, "1"),
                  ("DPI 125%", 1440, 900, "1.25"), ("DPI 150%", 1440, 900, "1.5")]
        for lbl, w, hh, dpi in matrix:
            idx += 1
            r = _run(td, w, hh, dpi, ws_set_binds, "settings", idx)
            if not r or not r.get("leftColH"):
                check("H. Settings %s" % lbl, False, "браузер не вернул результат измерения")
                continue
            d = abs(r["wsBottom"] - r["leftBottom"])
            aligned = d <= TOL
            same_top = abs(r["wsTop"] - r["leftTop"]) <= TOL
            in_view = r["wsBottom"] <= r["innerH"] + 1
            scrolls = r["scrollable"] > 0 and r["reachedBottom"]
            bounded = abs(r["wsHeight"] - r["wsHeightAfterScroll"]) <= TOL
            page_still = r["bodyScroll"] <= 2 and r["docScroll"] <= 2
            ok = aligned and same_top and in_view and scrolls and bounded and page_still
            check("H. Settings %s — низ совпал с колонкой (Δ%.1fpx), внутр.скролл, страница без скролла"
                  % (lbl, d), ok,
                  "wsBottom=%s leftBottom=%s innerH=%s scrollable=%s reached=%s bodyScroll=%s"
                  % (r["wsBottom"], r["leftBottom"], r["innerH"], r["scrollable"], r["reachedBottom"], r["bodyScroll"]))
        # H7, H8: Diagnostics-экран — низ совпадает, журнал скроллит внутри
        for lbl, w, hh in [("1440x900", 1440, 900), ("1920x1080", 1920, 1080)]:
            idx += 1
            r = _run(td, w, hh, "1", ws_diag_binds, "diag", idx)
            if not r or not r.get("leftColH"):
                check("H. Diagnostics %s" % lbl, False, "браузер не вернул результат измерения")
                continue
            d = abs(r["wsBottom"] - r["leftBottom"])
            ok = d <= TOL and r["wsBottom"] <= r["innerH"] + 1 and r["scrollable"] > 0 \
                and r["reachedBottom"] and r["bodyScroll"] <= 2
            check("H. Diagnostics %s — низ совпал с колонкой (Δ%.1fpx), журнал скроллит внутри" % (lbl, d),
                  ok, "wsBottom=%s leftBottom=%s scrollable=%s reached=%s"
                  % (r["wsBottom"], r["leftBottom"], r["scrollable"], r["reachedBottom"]))
        # H9: доказательство, что фикс несущий — БЕЗ привязки (height:100%) низ расходится с колонкой
        idx += 1
        rb = _run(td, 1440, 900, "1", False, "settings", idx)
        if not rb or not rb.get("leftColH"):
            check("H. bug-repro (без leftColH)", False, "браузер не вернул результат измерения")
        else:
            div = rb["wsBottom"] - rb["leftBottom"]
            check("H. КОНТРОЛЬ: без привязки к leftColH низ экрана уходит ниже колонки (Δ%.1fpx>2)" % div,
                  div > TOL, "wsBottom=%s leftBottom=%s" % (rb["wsBottom"], rb["leftBottom"]))
    _tmp_gone = not os.path.isdir(td)

print("=== I. Метка и следы ===")
_prod = [os.path.join(WEB, "index.html"), os.path.join(WEB, "app.css"), os.path.join(WEB, "app.js"),
         os.path.join(PROJ, "server.py")]
_leak = [p for p in _prod if SENTINEL in rd(p)]
check("55. метка не попала в продуктовые файлы", not _leak, str(_leak))
check("56. тестовых артефактов в проекте нет (_e2e_payload.json)",
      not os.path.exists(os.path.join(PROJ, "tools", "_e2e_payload.json")))
check("57. временный каталог удалён", _tmp_gone)

print()
print("Итого: %d проверок пройдено, %d провалено, %d пропущено" % (_pass, _fail, _skip))
if _fail:
    print("FAIL: %d проверок провалено" % _fail)
sys.exit(1 if _fail else 0)
