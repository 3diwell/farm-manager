# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.821 — АДАПТИВНАЯ панель диагностики: тексты не выходят из кнопок, группы переносятся.

Проверяет ДВА уровня:
  СТАТИКА  — web/index.html (логические группы toolbar, сохранённые handler'ы) и web/app.css
             (flex-wrap на строках, nowrap+flex:0 0 на кнопках/подписях, гибкий поиск, без
             absolute/фиксированной высоты toolbar, без глобального horizontal scroll).
  LAYOUT   — реальный безопасный движок Edge/Chromium: страница ЛИНКует настоящий web/app.css и
             строит toolbar РЕАЛЬНЫМИ классами .diag-* с новыми группами и САМЫМИ ДЛИННЫМИ RU/EN
             подписями, рендерит при разных ширинах/зумах/DPI и меряет getBoundingClientRect:
             текст не переносится внутри кнопки, подписи/статус в одну строку, элементы не
             перекрываются, тело журнала начинается ниже toolbar и имеет положительную высоту,
             нет горизонтального scroll страницы.

Полностью offline: без рабочей БД/DATA_DIR/config, без printer commands, без production runtime,
fake-данные журнала, fake-локали RU/EN, fake zoom/viewport. Если Edge не найден — layout-проверки
помечаются SKIP (не RED), статика идёт всегда. Требует PYTHONUTF8=1 для кириллицы в stdout.

Sentinel (только тестовая оснастка): DIAGNOSTICS_TOOLBAR_RESPONSIVE_SENTINEL_2_821
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

SENTINEL = "DIAGNOSTICS_TOOLBAR_RESPONSIVE_SENTINEL_2_821"
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDX = os.path.join(PROJ, "web", "index.html")
CSS = os.path.join(PROJ, "web", "app.css")

_pass = _fail = _skip = 0


def check(label, cond, extra=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print("ok   " + label)
    else:
        _fail += 1
        print("FAIL " + label + ((" — " + extra) if extra else ""))


def skip(label, why):
    global _skip
    _skip += 1
    print("SKIP " + label + " — " + why)


def rd(p):
    return io.open(p, encoding="utf-8", errors="surrogateescape").read()


HTML = rd(IDX)
CSSTXT = rd(CSS)

# ── Изолируем реальный toolbar (.diag-bar лог-вкладки) и всю секцию diagnostics ────────────────
_bar_s = HTML.find('<div v-if="diagTab===\'log\'" class="diag-bar">')
_bar_e = HTML.find('<div v-if="diagTab===\'log\'" id="diagBody"')
BAR = HTML[_bar_s:_bar_e] if (_bar_s >= 0 and _bar_e > _bar_s) else ""
_sec_s = HTML.find('<section v-if="showDiag" class="fm-diagnostics-workspace"')
_sec_e = HTML.find("id=\"diagBody\"")
HEAD = HTML[_sec_s:_bar_s] if (_sec_s >= 0 and _bar_s > _sec_s) else ""

print("=== A. Структура toolbar (index.html): логические группы ===")
check("1. toolbar разбит на логические группы (view-options/live-status/actions)",
      'class="diag-view-options"' in BAR and 'class="diag-live-status"' in BAR
      and 'class="diag-actions-group"' in BAR)
check("2. вкладки в первой строке (.diag-tabs в .diag-head)", 'class="diag-tabs"' in HEAD)
check("3. фильтры — отдельная группа (.diag-filters)", 'class="diag-filters"' in HEAD)
check("4. view-options держит Подробную консоль, Автопрокрутку и Паузу вместе",
      re.search(r'diag-view-options"[\s\S]*Verbose console[\s\S]*Auto-scroll[\s\S]*toggleDiagPause[\s\S]*</div>', BAR) is not None)
check("5. поиск — собственный адаптивный элемент (flex:1 1 …)",
      'v-model="diagSearch"' in BAR and re.search(r'diag-search"[^>]*flex:1 1', BAR) is not None)
check("6. live-status цельный: счётчик + diagStateText в одной группе",
      re.search(r'diag-live-status"[\s\S]*diag-count[\s\S]*diagStateText[\s\S]*</div>', BAR) is not None)
check("7. actions — одна группа (Копировать/Сохранить/Очистить/Скачать)",
      re.search(r'diag-actions-group"[\s\S]*copyDiag\(\)[\s\S]*exportDiag\(\)[\s\S]*clearDiag[\s\S]*downloadLogs[\s\S]*</div>', BAR) is not None)
check("8. кнопка закрытия остаётся в шапке (.diag-x)", 'class="diag-x"' in HEAD)
check("8b. DOM-порядок бара = визуальный (view-options→search→live-status→actions) — tab order логичен",
      0 <= BAR.find('diag-view-options') < BAR.find('diag-search')
      < BAR.find('diag-live-status') < BAR.find('diag-actions-group'))
check("8c. вкладки идут ДО кнопки закрытия в шапке (close — последняя логичная)",
      0 <= HEAD.find('diag-tabs') < HEAD.find('diag-x'))

print("\n=== B. Сохранённые handler'ы (backend/логика НЕ тронуты) ===")
for hd, nm in [("toggleDiagPause()", "Pause/Resume"), ("v-model=\"diagSearch\"", "Search"),
               ("copyDiag()", "Copy"), ("exportDiag()", "Save .txt"),
               ("@click=\"clearDiag\"", "Clear"), ("@click=\"downloadLogs\"", "Download"),
               ("diagFilter=f.id", "Filters"), ("v-model=\"diagAutoscroll\"", "Auto-scroll"),
               ("@change=\"toggleDiagVerbose\"", "Verbose")]:
    check("9.%s handler сохранён" % nm, hd in HTML)

print("\n=== C. CSS-контракт (app.css, дописанный блок 2.821) ===")
def css_has(pat):
    return re.search(pat, CSSTXT) is not None
check("10. .diag-bar получает flex-wrap:wrap",
      css_has(r"\.fm-diagnostics-workspace\s+\.diag-bar\{[^}]*flex-wrap:wrap"))
check("11. .diag-head тоже переносится (высокий zoom)",
      css_has(r"\.fm-diagnostics-workspace\s+\.diag-head\{[^}]*flex-wrap:wrap"))
check("12. кнопки бара: white-space:nowrap",
      css_has(r"\.diag-bar\s+\.diag-fbtn[\s\S]{0,120}?white-space:nowrap"))
check("13. кнопки бара: flex:0 0 auto (не сжимаются ниже текста)",
      css_has(r"\.diag-bar\s+\.diag-fbtn[\s\S]{0,120}?flex:0 0 auto"))
check("14. кнопки бара: min-inline-size:max-content",
      css_has(r"\.diag-bar\s+\.diag-fbtn[\s\S]{0,140}?min-inline-size:max-content"))
check("15. подписи чекбоксов nowrap (Подробная консоль/Автопрокрутка)",
      css_has(r"\.diag-bar\s+\.diag-chk[\s\S]{0,120}?white-space:nowrap"))
check("16. группы — flex:0 0 auto",
      css_has(r"diag-actions-group\{[^}]*flex:0 0 auto"))
check("17. без absolute/fixed в новом контракте",
      not re.search(r"diag-(view-options|live-status|actions-group|bar|head)\{[^}]*position:(absolute|fixed)", CSSTXT))
check("18. без фиксированной высоты toolbar (.diag-bar/.diag-head без height:Npx)",
      not css_has(r"\.fm-diagnostics-workspace\s+\.diag-(bar|head)\{[^}]*height:\d"))
check("19. sentinel НЕ попал в продуктовые файлы", SENTINEL not in HTML and SENTINEL not in CSSTXT)

# ── LAYOUT (headless Edge) ─────────────────────────────────────────────────────────────────────
EDGE = next((p for p in [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"] if os.path.isfile(p)), None)

# Alpha 2.835: наличие бинарника не значит работоспособность, НО неработоспособность движка
# больше НЕ повод пропускать браузерные проверки — это КРАСНЫЙ тест с точной причиной. Прежний
# SKIP был слепой зоной: именно он однажды спрятал реальный дефект интерфейса.
_ENGINE_WHY = ""
if not EDGE:
    _ENGINE_WHY = "движок рендера (Edge/Chrome) не найден"
elif not _edge_dom.engine_usable(EDGE):
    _ENGINE_WHY = "движок найден (%s), но не отдаёт документ по CDP" % EDGE
    EDGE = None

# самые длинные подписи (RU шире EN): worst-case стресс
LOC = {
    "ru": {"log": "Журнал", "conn": "Связь", "queue": "Очередь запуска", "sniff": "Перехват Studio",
           "all": "Все", "info": "Важное", "warn": "Предупреждения", "err": "Ошибки",
           "verbose": "Подробная консоль", "auto": "Автопрокрутка", "pause": "Продолжить",
           "search": "Поиск по записям…", "status": "Соединение потеряно",
           "copy": "Копировать", "save": "Сохранить .txt", "clear": "Очистить", "dl": "⤓ Скачать логи"},
    "en": {"log": "Log", "conn": "Connection", "queue": "Launch queue", "sniff": "Studio capture",
           "all": "All", "info": "Info+", "warn": "Warnings", "err": "Errors",
           "verbose": "Verbose console", "auto": "Auto-scroll", "pause": "Resume",
           "search": "Search entries…", "status": "Connection lost",
           "copy": "Copy", "save": "Save .txt", "clear": "Clear", "dl": "⤓ Download logs"},
}
_WRAP_Z = "1.0971662034375"


def page(loc, count_txt, browser_zoom):
    L = LOC[loc]
    css_href = "file:///" + CSS.replace("\\", "/")
    rows = "".join(
        '<div class="diag-row"><span class="diag-ts">12:04:%02d</span>'
        '<span class="diag-lvl lvl-info">INFO</span>'
        '<span class="diag-msg">demo log line %d for layout measurement</span></div>' % (i % 60, i)
        for i in range(40))
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<link rel='stylesheet' href='" + css_href + "'>"
        "<style>"
        "html,body{margin:0;height:100%;overflow:hidden;background:#141416}"
        "#__res{position:fixed;left:-9999px;top:0}"
        "#bz{zoom:" + str(browser_zoom) + "}"
        "#app{height:100%}"
        ".zoom-wrap{height:100%;display:flex;flex-direction:column;zoom:" + _WRAP_Z + ";padding:8px 16px 0}"
        ".app-header{flex:0 0 auto;height:48px}"
        ".rowwrap{flex:1 1 auto;min-height:0;width:100%}"
        ".main-cols{display:flex;gap:8px;width:100%;height:100%;min-height:0}"
        ".left-col{width:360px;flex:0 0 auto}"
        "</style></head><body><div id='bz'><div id='app'><div class='zoom-wrap'>"
        "<header class='app-header'></header>"
        "<div class='rowwrap'><div class='main-cols'>"
        "<div class='left-col'></div>"
        "<section class='fm-diagnostics-workspace' id='ws'>"
        "<div class='diag-head' id='dhead'>"
        "<svg class='diag-ico'></svg>"
        "<div class='diag-tabs'>"
        "<button class='diag-tab on'>" + L["log"] + "</button>"
        "<button class='diag-tab'>" + L["conn"] + "</button>"
        "<button class='diag-tab'>" + L["queue"] + "</button>"
        "<button class='diag-tab'>" + L["sniff"] + "</button></div>"
        "<span class='diag-count'>" + count_txt + "</span>"
        "<div class='diag-filters'>"
        "<button class='diag-fbtn on'>" + L["all"] + "</button>"
        "<button class='diag-fbtn'>" + L["info"] + "</button>"
        "<button class='diag-fbtn'>" + L["warn"] + "</button>"
        "<button class='diag-fbtn'>" + L["err"] + "</button></div>"
        "<div class='diag-x'>✕</div></div>"
        "<div class='diag-bar' id='dbar'>"
        "<div class='diag-view-options'>"
        "<label class='diag-chk'><input type='checkbox'><span>" + L["verbose"] + "</span></label>"
        "<label class='diag-chk'><input type='checkbox' checked><span>" + L["auto"] + "</span></label>"
        "<button class='diag-fbtn'>" + L["pause"] + "</button></div>"
        "<input class='diag-search' type='search' placeholder='" + L["search"] + "' "
        "style='flex:1 1 200px;min-width:130px;padding:3px 8px;border-radius:6px;border:1px solid #555;font-size:12px'>"
        "<div class='diag-live-status'>"
        "<span class='diag-count'>" + count_txt + "</span>"
        "<span class='diag-chk' style='opacity:.85'>" + L["status"] + "</span></div>"
        "<div class='diag-actions-group'>"
        "<button class='diag-fbtn'>" + L["copy"] + "</button>"
        "<button class='diag-fbtn'>" + L["save"] + "</button>"
        "<button class='diag-clear'>" + L["clear"] + "</button>"
        "<button class='diag-dl'>" + L["dl"] + "</button></div></div>"
        "<div class='diag-body' id='dbody'>" + rows + "</div>"
        "</section></div></div></div></div></div>"
        "<pre id='__res'></pre><script>"
        "function measure(){"
        "var ws=document.getElementById('ws'),dhead=document.getElementById('dhead'),"
        "dbar=document.getElementById('dbar'),dbody=document.getElementById('dbody');"
        "var R={ok:true,fails:[]};"
        "function bad(m){R.ok=false;R.fails.push(m);}"
        # кнопки: текст не выходит за padding box (нет ни горизонтального, ни вертикального overflow)
        "var btns=[].slice.call(dbar.querySelectorAll('.diag-fbtn,.diag-clear,.diag-dl'))"
        ".concat([].slice.call(dhead.querySelectorAll('.diag-tab,.diag-fbtn')));"
        "btns.forEach(function(b,i){"
        "  if(b.scrollWidth>b.clientWidth+2) bad('btn#'+i+' hoverflow \"'+b.textContent.trim()+'\"');"
        "  if(b.scrollHeight>b.clientHeight+2) bad('btn#'+i+' voverflow \"'+b.textContent.trim()+'\"');});"
        # подписи/статус: ровно одна строка (getClientRects===1)
        "var spans=[].slice.call(dbar.querySelectorAll('.diag-chk span, .diag-live-status .diag-chk'));"
        "spans.forEach(function(s,i){ if(s.getClientRects().length>1) bad('span#'+i+' wrapped \"'+s.textContent.trim()+'\"');});"
        # геометрия: тело журнала ниже toolbar, положительная высота, toolbar в пределах workspace
        "var rH=dhead.getBoundingClientRect(),rB=dbar.getBoundingClientRect(),rBody=dbody.getBoundingClientRect(),rW=ws.getBoundingClientRect();"
        "R.headTop=Math.round(rH.top*10)/10;R.barBottom=Math.round(rB.bottom*10)/10;R.bodyTop=Math.round(rBody.top*10)/10;"
        "R.bodyH=Math.round(rBody.height*10)/10;R.wsBottom=Math.round(rW.bottom*10)/10;"
        "if(rBody.top < rB.bottom-2) bad('body overlaps toolbar');"
        "if(rBody.height <= 0) bad('body height<=0');"
        "if(rB.bottom > rW.bottom+2) bad('toolbar exceeds workspace bottom');"
        "if(rH.top < rW.top-2) bad('head above workspace');"
        # содержимое бара не выходит за его собственную высоту (ловит фиксированную высоту toolbar)
        "if(dbar.scrollHeight > dbar.clientHeight+2) bad('toolbar content overflows its height');"
        # нет горизонтального scroll страницы
        "var de=document.documentElement;"
        "if(de.scrollWidth > de.clientWidth+2) bad('page hscroll '+de.scrollWidth+'>'+de.clientWidth);"
        # перекрытие управляющих элементов (bar)
        "var ctl=[].slice.call(dbar.querySelectorAll('.diag-fbtn,.diag-clear,.diag-dl,.diag-chk,.diag-search'))"
        ".concat([].slice.call(dhead.querySelectorAll('.diag-tab,.diag-fbtn,.diag-x')));"
        "for(var a=0;a<ctl.length;a++)for(var c=a+1;c<ctl.length;c++){var x=ctl[a].getBoundingClientRect(),y=ctl[c].getBoundingClientRect();"
        "if(x.left<y.right-1&&y.left<x.right-1&&x.top<y.bottom-1&&y.top<x.bottom-1) bad('overlap '+a+'/'+c);}"
        # каждый элемент управления в горизонтальных границах workspace (иначе overflow:hidden его обрежет = недоступен)
        "ctl.forEach(function(e,i){var r=e.getBoundingClientRect();"
        "if(r.right>rW.right+2) bad('ctl#'+i+' clipped past ws right \"'+(e.textContent||'').trim()+'\"');"
        "if(r.left<rW.left-2) bad('ctl#'+i+' left of ws');});"
        "R.barRows=Math.round(rB.height/Math.max(1,rH.height)*10)/10;"
        "return R;}"
        "document.getElementById('__res').textContent='@@RES@@'+JSON.stringify(measure())+'@@END@@';"
        "</script></body></html>")


def run_case(td, loc, count_txt, win_w, win_h, dsf, bz, idx):
    pg = os.path.join(td, "diag_%s_%d_%d_%s_%s.html" % (loc, win_w, win_h, str(dsf), str(bz)))
    io.open(pg, "w", encoding="utf-8", newline="\n").write(page(loc, count_txt, bz))
    prof = os.path.join(td, "p%d" % idx)
    # Alpha 2.834: Edge 150 больше не печатает документ по --dump-dom (headless стал detached:
    # родитель выходит с 0, stdout пуст). DOM читаем из того же headless-Edge по CDP.
    dom = _edge_dom.dump_dom_compatible(EDGE, "file:///" + pg.replace("\\", "/"), prof,
                                        window_size=(win_w, win_h), budget_ms=5000,
                                        extra_args=("--force-device-scale-factor=%s" % dsf,))
    m = re.search(r"@@RES@@(\{.*?\})@@END@@", dom, re.S)
    return json.loads(m.group(1)) if m else None


print("\n=== D. Геометрия в реальном движке (Edge/Chromium) ===")
if not EDGE:
    for lbl in ["1920x1080", "1600x900", "1440x900", "1366x768", "1100x700", "zoom125", "zoom150",
                "zoom175", "zoom200", "DPI125", "DPI150", "EN-1366", "count-1", "count-999999"]:
        check("D.%s" % lbl, False, _ENGINE_WHY)
    _tmp_gone = True
else:
    # (label, loc, count, win_w, win_h, dsf, browser_zoom)
    CASES = [
        ("20. 1920x1080 100% RU", "ru", "347", 1920, 1080, 1, 1.0),
        ("21. 1600x900 100% RU", "ru", "347", 1600, 900, 1, 1.0),
        ("22. 1440x900 100% RU", "ru", "347", 1440, 900, 1, 1.0),
        ("23. 1366x768 100% RU", "ru", "347", 1366, 768, 1, 1.0),
        ("24. 1100x700 100% RU (группы переносятся)", "ru", "347", 1100, 700, 1, 1.0),
        ("25. 1440x900 zoom125% RU", "ru", "347", 1440, 900, 1, 1.25),
        ("26. 1440x900 zoom150% RU", "ru", "347", 1440, 900, 1, 1.5),
        ("27. 1440x900 zoom175% RU", "ru", "347", 1440, 900, 1, 1.75),
        ("28. 1440x900 zoom200% RU (все действия доступны)", "ru", "347", 1440, 900, 1, 2.0),
        ("29. 1440x900 DPI125% RU", "ru", "347", 1440, 900, 1.25, 1.0),
        ("30. 1440x900 DPI150% RU", "ru", "347", 1440, 900, 1.5, 1.0),
        ("31. 1366x768 100% EN", "en", "347", 1366, 768, 1, 1.0),
        ("32. счётчик 1 не ломает layout", "ru", "1", 1440, 900, 1, 1.0),
        ("33. счётчик 999999 не ломает layout", "ru", "999999", 1440, 900, 1, 1.0),
    ]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_diagtb_" + SENTINEL[-8:] + "_") as td:
        for i, (lbl, loc, cnt, w, h, dsf, bz) in enumerate(CASES):
            R = run_case(td, loc, cnt, w, h, dsf, bz, i)
            if R is None:
                # Alpha 2.835: молчание браузера — это КРАСНАЯ проверка, а не пропуск:
                # именно такой пропуск однажды спрятал реальный дефект интерфейса.
                check("D.%s" % lbl, False, "браузер не вернул результат измерения")
                continue
            ok = bool(R.get("ok"))
            check("D.%s (body=%.0f rows≈%.1f)" % (lbl, R.get("bodyH", 0), R.get("barRows", 0)),
                  ok, ("; ".join(R.get("fails", []))[:200]))
    _tmp_gone = True

print("\n=== E. Регрессия: сохранённые контракты (только чтение исходников, backend не тронут) ===")


def has(path, needle):
    try:
        return needle in rd(os.path.join(PROJ, path))
    except Exception:
        return False


check("44. Bambu-фикс Alpha 2.820 сохранён (BAMBU_CANCEL_HMS в policy)",
      has("app/printer_health_policy.py", "BAMBU_CANCEL_HMS"))
check("45. Diagnostics API не менялся: маршрут /api/diagnostics/summary в server.py",
      has("server.py", '"/api/diagnostics/summary")'))
check("46. Diagnostics API: /api/diagnostics/client (клиентские ошибки) в server.py",
      has("server.py", "/api/diagnostics/client"))
check("47. фронтенд зовёт ПРЕЖНИЙ endpoint сводки (pollDiagSummary → summary)",
      has("web/app.js", "/api/diagnostics/summary") and has("web/app.js", "pollDiagSummary"))
check("48. ring buffer + redaction модуль на месте (app/runtime_log_buffer.py)",
      os.path.exists(os.path.join(PROJ, "app", "runtime_log_buffer.py")))
check("49. высота workspace Alpha 2.817 (leftColH) НЕ тронута",
      has("web/index.html", "height: leftColH"))
check("50. DISPATCH_ENABLED = False (модульное присваивание orchestrator)",
      has("app/project_orchestrator.py", "\nDISPATCH_ENABLED = False"))
check("51. TRANSPORT_ENABLED = False (модульное присваивание orchestrator)",
      has("app/project_orchestrator.py", "\nTRANSPORT_ENABLED = False"))
check("52. правки только фронтенд-презентация: diag-фикс живёт в app.css (не в server.py)",
      "diag-actions-group" in CSSTXT and not has("server.py", "diag-actions-group"))

print()
print("Итого: %d проверок пройдено, %d провалено, %d пропущено" % (_pass, _fail, _skip))
if _fail:
    print("FAIL: %d проверок провалено" % _fail)
    sys.exit(1)
sys.exit(0)
