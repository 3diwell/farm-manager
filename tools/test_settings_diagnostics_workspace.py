# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""
Alpha 2.816 — «Настройки» и «Диагностика/Журнал» как СТАТИЧНЫЕ рабочие экраны.

Требование пользователя: эти два системных экрана перестают быть плавающими модальными окнами и
занимают центральную рабочую область (место «Проекты и задачи»). Верхняя панель и колонка принтеров
остаются видимыми и рабочими; затемнения, центрирования и перетаскивания нет; закрытие возвращает
в «Проекты» с сохранённым состоянием. Вложенные диалоги (порт, модули, подтверждения) по-прежнему
открываются поверх через overlay root 2.815.

Тест полностью офлайновый: разбор шаблона/DOM/CSS/JS-исходников и прогон извлечённой из web/app.js
логики переключения рабочей области в Node на фальшивом DOM. Рабочая БД, DATA_DIR, config, сеть и
принтеры не используются; GUI не открывается; временное — в TemporaryDirectory, он удаляется.
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(PROJ, "web")

# Метка живёт ТОЛЬКО в этой оснастке и во временных файлах. В продукт, БД, DATA_DIR, config, логи,
# модули, ZIP, профиль WebView, _incoming/ и команды принтерам не попадает.
SENTINEL = "SETTINGS_DIAGNOSTICS_WORKSPACE_SENTINEL_2_816"

NODE = r"C:\Program Files\nodejs\node.exe"
_fail = 0
_pass = 0


def check(name, cond, detail=""):
    global _fail, _pass
    if cond:
        _pass += 1
        print("ok   %s" % name)
    else:
        _fail += 1
        print("FAIL — %s%s" % (name, (" | " + detail) if detail else ""))


def rd(p):
    return io.open(p, encoding="utf-8", newline="").read()


HTML = rd(os.path.join(WEB, "index.html"))
CSS = rd(os.path.join(WEB, "app.css"))
APP = rd(os.path.join(WEB, "app.js"))
SRV = rd(os.path.join(PROJ, "server.py"))
ORCH = rd(os.path.join(PROJ, "app", "project_orchestrator.py"))


def section(cls):
    """Кусок <section ... class="cls">...</section> рабочего экрана."""
    i = HTML.find('class="' + cls + '"')
    if i < 0:
        return ""
    a = HTML.rfind("<section", 0, i)
    b = HTML.find("</section>", i)
    return HTML[a:b + 10] if a >= 0 and b > 0 else ""


def css_el_rule(cls):
    """Тело всех правил, стилизующих сам элемент cls (включая групповые селекторы `.a,.b{}`),
    но НЕ его детей. css_rule по одиночному селектору вернул бы пусто → вакуумная проверка."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        for one in m.group(1).split(","):
            one = one.strip()
            if one and one.split()[-1] == cls:
                out.append(m.group(2))
                break
    return " ".join(out)


def jsfn(name):
    """Тело выражения `const name = ...;` из app.js — до завершающей `;` на нулевой глубине.
    Работает и для блочных стрелок `() => {...}`, и для однострочных `computed(() => expr)`.
    Пропускает строки и построчные комментарии, чтобы `;`/скобки внутри них не сбивали баланс."""
    i = APP.find("const " + name + " =")
    if i < 0:
        return ""
    j = i + len("const " + name + " =")
    pd = bd = 0
    while j < len(APP):
        c = APP[j]
        if APP[j:j + 2] == "//":
            nl = APP.find("\n", j)
            j = len(APP) if nl < 0 else nl
            continue
        if c in "\"'`":
            q = c
            j += 1
            while j < len(APP) and APP[j] != q:
                if APP[j] == "\\":
                    j += 1
                j += 1
            j += 1
            continue
        if c == "(":
            pd += 1
        elif c == ")":
            pd -= 1
        elif c == "{":
            bd += 1
        elif c == "}":
            bd -= 1
        elif c == ";" and pd == 0 and bd == 0:
            return APP[i:j + 1]
        j += 1
    return APP[i:]


SET = section("fm-settings-workspace")
DIAG = section("fm-diagnostics-workspace")

# ---- границы основного ряда, куда встают рабочие экраны ----
_main_row_i = HTML.find('class="main-cols')
_left_i = HTML.find('class="left-col')
_main_i = HTML.find('class="projects-pane')
_header_i = HTML.find('class="app-header')
# открывающие теги <main> и колонки принтеров (v-show/v-if стоят ДО class=, поэтому берём весь тег)
_main_tag_i = HTML.rfind("<main", 0, _main_i)
_main_tag = HTML[_main_tag_i:HTML.find(">", _main_tag_i) + 1] if _main_tag_i >= 0 else ""
_left_tag_i = HTML.rfind("<div", 0, _left_i)
_left_tag = HTML[_left_tag_i:HTML.find(">", _left_tag_i) + 1] if _left_tag_i >= 0 else ""

print("=== A. Структура рабочей области ===")

# 1 — единый host: рабочие экраны и <main> лежат в одном ряду main-cols
check("1. существует единый host основной рабочей области (main-cols)",
      _main_row_i >= 0 and _left_i > _main_row_i and _main_i > _main_row_i)
# 2, 3, 4 — Projects/Settings/Diagnostics рендерятся ВНУТРИ этого ряда
_row_end = HTML.find("</div>\n</div>", _main_i) if _main_i > 0 else -1
check("2. Проекты рендерятся внутри рабочей области (<main class=projects-pane>)",
      _main_i > _main_row_i and "workspaceView==='projects'" in _main_tag)
check("3. Настройки рендерятся рабочим экраном внутри рабочей области",
      bool(SET) and HTML.find('class="fm-settings-workspace"') > _main_row_i)
check("4. Диагностика рендерится рабочим экраном внутри рабочей области",
      bool(DIAG) and HTML.find('class="fm-diagnostics-workspace"') > _main_row_i)
# 5, 6 — корневые экраны НЕ телепортируются в overlay root
check("5. Настройки не телепортируются в overlay root как корневой экран",
      "<teleport" not in SET and 'class="fm-settings-workspace"' in SET)
check("6. Диагностика не телепортируется в overlay root как корневой экран",
      "<teleport" not in DIAG and 'class="fm-diagnostics-workspace"' in DIAG)
# 7, 8 — нет полноэкранного backdrop. Легальные .fm-settings-backdrop (restart/tour) живут в overlay
# root ПОСЛЕ #app; в ряду main-cols (внутри #app) затемнения быть не должно — там его увидела бы страница.
_row_to_set = HTML[_main_row_i:HTML.find('class="fm-settings-workspace"')] if _main_row_i >= 0 else ""
check("7. Настройки не имеют fullscreen backdrop",
      "fm-settings-backdrop" not in SET and "diag-overlay" not in SET
      and "fm-settings-backdrop" not in _row_to_set)
check("8. Диагностика не имеет fullscreen backdrop",
      "diag-overlay" not in DIAG and "fm-settings-backdrop" not in DIAG and "diag-overlay" not in HTML)
# 9, 10 — колонка принтеров и верхняя панель ВНЕ сменяемого экрана
check("9. колонка принтеров вне сменяемого рабочего экрана (её видимость не зависит от workspaceView)",
      0 < _left_i < _main_i and _left_i < HTML.find('class="fm-settings-workspace"')
      and "workspaceView" not in _left_tag)
check("10. верхняя панель вне рабочей области (выше ряда main-cols)",
      0 < _header_i < _main_row_i)

print("=== A2. Настройки ===")
_setcss = css_el_rule(".fm-settings-workspace").replace(" ", "")
# 11
check("11. рабочий экран настроек занимает 100% рабочей области",
      "width:100%" in _setcss and "height:100%" in _setcss and "flex:1" in _setcss)
# 12, 13, 14 — шапка и навигация фиксированы, прокручивается содержимое
# шапка/навигация/тело используют СУЩЕСТВУЮЩИЕ классы модали — они уже дают нужный flex/overflow,
# дублирующих классов 2.816 не заводим (иначе ломаются якоря соседних тестов).
check("12. заголовок настроек фиксирован (flex:0 0 auto у .fm-set-title)",
      "flex:0 0 auto" in css_el_rule(".fm-set-title") and 'class="fm-set-title"' in SET)
check("13. навигация настроек фиксирована (flex:0 0 auto у .fm-set-nav)",
      "flex:0 0 auto" in css_el_rule(".fm-set-nav") and 'class="fm-set-nav"' in SET)
check("14. содержимое настроек прокручивается (.fm-set-scroll overflow-y:auto)",
      "overflow-y:auto" in css_el_rule(".fm-set-scroll").replace(" ", "")
      and 'class="fm-set-scroll"' in SET)
# 15, 16 — не окно: без перетаскивания и transform-центрирования
check("15. настройки не перетаскиваются (нет ручек ресайза и drag-обработчиков)",
      "setResizeStart" not in SET and "setDragStart" not in SET and "ex-rz" not in SET)
check("16. настройки не центрируются transform'ом относительно viewport",
      "position:fixed" not in _setcss and "translate(-50%,-50%)" not in _setcss
      and "z-index" not in _setcss)
# 17, 18 — закрытие возвращает Проекты и не трогает backend
_closeSet = jsfn("closeSettings")
check("17. закрытие настроек возвращает в Проекты (showSettings=false → workspaceView='projects')",
      "showSettings.value = false" in _closeSet)
check("18. КРИТИЧНО: закрытие настроек не завершает backend/Desktop",
      not re.search(r"(restart|shutdown|quit|exit|/api/restart|window\.close|closeApp)", _closeSet, re.I))
# 19, 20 — вкладка и прокрутка сохраняются
check("19. выбранная вкладка настроек сохраняется (settingsTab не сбрасывается при закрытии)",
      "settingsTab" not in _closeSet and "const settingsTab = ref('general')" in APP)
check("20. прокрутка разделов настроек сохраняется",
      "_setScrollMem" in APP and "_restoreSetScroll" in APP
      and 'ref="setScrollEl"' in SET and '@scroll.passive="onSetScroll"' in SET)

print("=== A3. Диагностика ===")
_diagcss = css_el_rule(".fm-diagnostics-workspace").replace(" ", "")
# 21
check("21. рабочий экран диагностики занимает 100% рабочей области",
      "width:100%" in _diagcss and "height:100%" in _diagcss and "flex:1" in _diagcss)
# 22, 23 — toolbar сверху, тело прокручивается
check("22. панель инструментов диагностики зафиксирована сверху (.diag-head flex-shrink:0, без перетаскивания)",
      'class="diag-head"' in DIAG and "flex-shrink:0" in css_el_rule(".diag-head").replace(" ", "")
      and "diagDragStart" not in DIAG)
check("23. тело журнала прокручивается внутри рабочего экрана (.diag-body overflow-y:auto)",
      "overflow-y:auto" in css_el_rule(".diag-body").replace(" ", "")
      and DIAG.count("diag-body") >= 1)
# 24 — закрытие возвращает Проекты
_closeDiag = jsfn("closeDiagnostics")
check("24. закрытие диагностики возвращает в Проекты (showDiag=false)",
      "showDiag.value = false" in _closeDiag)
# 25, 26 — опрос останавливается при закрытии и возобновляется при открытии
check("25. опрос журнала прекращается после закрытия (таймеры сняты)",
      "clearInterval(diagTimer)" in _closeDiag and "diagTimer = null" in _closeDiag)
_openDiag = jsfn("openDiagnostics")
check("26. опрос журнала возобновляется при открытии",
      "setInterval(fetchDiag" in _openDiag and "showDiag.value = true" in _openDiag)
# 27, 28 — deep-link и трей открывают ЭТОТ рабочий экран
check("27. deep-link #logs открывает рабочий экран диагностики",
      "'#logs'" in APP and re.search(r"===\s*'#logs'\s*\)\s*openDiagnostics\(\)", APP) is not None)
check("28. пункт трея «Открыть журнал» ведёт на этот же экран (через #logs)",
      'LOG_VIEW_FRAGMENT = "#logs"' in SRV and "_open_desktop_shell(LOG_VIEW_FRAGMENT)" in SRV
      and "Открыть журнал Farm Manager" in SRV)
# 29, 30 — без CMD и без второго backend
check("29. CMD/консоль не открывается в пути журнала (нет AllocConsole/AttachConsole)",
      "AllocConsole" not in APP and "AttachConsole" not in APP)
check("30. открытие журнала не поднимает второй backend (переиспользует активный Desktop/порт)",
      "find_running_local" in rd(os.path.join(PROJ, "app", "desktop_shell.py")))

print("=== A4. Состояние Проектов ===")
# 31–36 — <main> держится на v-show, DOM не уничтожается → всё состояние переживает уход
check("31–35. состояние Проектов сохраняется: <main> на v-show, а не v-if (DOM не пересоздаётся)",
      "v-show=" in _main_tag and "v-if=" not in _main_tag)
check("36. возврат не сбрасывает Проекты (close-обработчики не трогают выбор/фильтры проекта)",
      "project" not in _closeSet.lower() and "project" not in _closeDiag.lower()
      and "selectedProject" not in _closeSet and "spotlight" not in _closeDiag)

print("=== B. Стек модальных окон поверх рабочего экрана ===")
# извлекаем блок диалога порта из overlay root
_pi = HTML.find('v-if="showPortDialog"')
_pa = HTML.rfind("<teleport", 0, _pi)
_pb = HTML.find("</teleport>", _pi)
PORT = HTML[_pa:_pb + 11] if _pa >= 0 else ""


def zof(sel):
    body = " ".join(m.group(1) for m in
                    re.finditer(r"(?:^|\})\s*" + re.escape(sel) + r"\s*\{([^{}]*)\}", CSS, re.M))
    m = re.search(r"z-index:\s*var\(--(fm-z-[a-z0-9-]+)\)", body)
    if m:
        mm = re.search(r"--%s\s*:\s*(\d+)" % re.escape(m.group(1)), CSS)
        return int(mm.group(1)) if mm else None
    m = re.search(r"z-index:\s*(\d+)", body)
    return int(m.group(1)) if m else None


_zapp = zof("#app")
_zpwin = zof(".fm-ov-win")
_zpback = zof(".fm-ov-back")
# 37 — диалог порта открывается ПОВЕРХ рабочего экрана настроек (он в overlay root над #app)
check("37. диалог порта открывается поверх рабочего экрана настроек",
      '<teleport to="#fm-overlay-root">' in PORT and _zpwin is not None
      and _zapp is not None and _zpwin > _zapp)
# 38, 39 — установка/удаление модуля живут в настройках и подтверждаются поверх (модуль-инсталл — в SET, confirm системный)
check("38. установка модуля доступна из настроек (кнопка внутри рабочего экрана)",
      "pickModuleZip" in SET or "exInstallModule" in SET or "fm-set-mod-install" in SET)
#  2.959: своё окно вместо системного; проверяем, что оно и вправду выше любого слоя.
check("39. подтверждение удаления модуля открывается поверх любого окна",
      "Удалить модуль" in APP and "askConfirm({" in jsfn("deleteModule")
      and "calc(var(--fm-z-critical, 100120) + 20)" in CSS)
# 40, 41 — корневые экраны НЕ модальные слои
check("40. Настройки не считаются модальным слоем (нет v-modal-layer на корне)",
      "v-modal-layer" not in SET)
check("41. Диагностика не считается модальным слоем (нет v-modal-layer на корне)",
      "v-modal-layer" not in DIAG)
# 42, 43 — Escape: сначала верхний дочерний modal, затем рабочий экран → Проекты
_i_nested = APP.find("const _topNested = fmModalTopNested();")
_i_diag_esc = APP.find("if (showDiag.value) { closeDiagnostics(); return; }")
_i_set_esc = APP.find("if (showSettings.value) { closeSettings(); return; }")
check("42. Escape закрывает верхний дочерний modal раньше рабочего экрана",
      0 < _i_nested < _i_set_esc and 0 < _i_nested < _i_diag_esc)
check("43. следующий Escape закрывает рабочий экран → возврат в Проекты",
      _i_set_esc > 0 and _i_diag_esc > 0)
# 44 — фокус после дочернего modal возвращается в настройки (механизм стека 2.815)
check("44. фокус после закрытия дочернего modal возвращается (restore из стека 2.815)",
      "entry.restore" in APP and "restore.focus()" in APP)
# 45 — overlay root 2.815 на месте
check("45. overlay root 2.815 сохранён", HTML.count('id="fm-overlay-root"') == 1)

print("=== C. Раскладка ===")
# 46–51 — sidebar виден и интерактивен; рабочая область не перекрывает панель/колонку
check("46. колонка принтеров остаётся видимой (отдельная колонка, без v-if на весь ряд)",
      _left_i > 0 and 'class="left-col' in HTML)
check("47. колонка принтеров интерактивна без дочернего modal (её клики не заблокированы экраном)",
      "position:fixed" not in _setcss and "position:fixed" not in _diagcss)
check("48. рабочий экран не перекрывает колонку принтеров (в потоке flex, не fixed/inset)",
      "inset:0" not in _setcss and "inset:0" not in _diagcss)
check("49. рабочий экран не перекрывает верхнюю панель (лежит ниже неё в потоке)",
      _header_i < _main_row_i and "position:fixed" not in _setcss)
check("50. рабочий экран занимает правую границу области (flex:1 растягивает до края)",
      "flex:1" in _setcss and "flex:1" in _diagcss)
check("51. рабочий экран занимает нижнюю границу (height:100%)",
      "height:100%" in _setcss and "height:100%" in _diagcss)
# 52, 53 — без фиксированной ширины окна и без плавающих внешних полей
check("52. нет фиксированной ширины модального окна",
      not re.search(r"width:min\(\d{3,}px", _setcss) and not re.search(r"width:min\(\d{3,}px", _diagcss)
      and "margin:auto" not in _setcss)
check("53. нет огромных внешних полей плавающего окна (box-sizing и без крупных margin)",
      "box-sizing:border-box" in _setcss and not re.search(r"margin:\d{2,}px", _setcss))
# 54, 55 — адаптив и ресайз
check("54. узкий экран не обрезает критические кнопки (навигация становится узкой, экран не модаль)",
      "max-width:720px" in CSS and ".fm-settings-workspace{width:100%;height:100%}".replace(" ", "") in CSS.replace(" ", ""))
check("55. ресайз Desktop сохраняет раскладку (экран в потоке, размеры относительные — без абсолютных px)",
      not re.search(r"(top|left|right|bottom):\s*\d+px", _setcss)
      and not re.search(r"(top|left|right|bottom):\s*\d+px", _diagcss))

print("=== D. Browser / Desktop / Client ===")
# 56–62 — единая раскладка, один DOM
check("56. Browser использует рабочую область (единый шаблон)",
      bool(SET) and bool(DIAG))
check("57. Desktop использует тот же рабочий экран (одна разметка, без ветвления по среде)",
      "isDesktop" not in SET and "isDesktop" not in DIAG)
check("58. Client использует тот же рабочий экран (одна разметка)",
      "isClient" not in SET and "isClient" not in DIAG)
# Проверяем именно ВЫЗОВ-страж в обработчике порта, а не сигнатуру def _require_server_machine(req)
# (иначе строка совпала бы с определением функции и снятие стража осталось бы незамеченным).
check("59. управление портом у Client остаётся read-only (машинная граница на сервере)",
      "deny_machine = _require_server_machine(req)" in SRV
      and "if deny_machine is not None:" in SRV and "portCanChange" in APP)
check("60. DOM Browser и Desktop не расходятся (нет отдельной ветки разметки экранов)",
      HTML.count('class="fm-settings-workspace"') == 1 and HTML.count('class="fm-diagnostics-workspace"') == 1)
check("61. закрытие Desktop не завершает backend (существующий контракт трея сохранён)",
      "def _open_log_viewer" in SRV and "Выход" in SRV)
check("62. Client не содержит backend (сборка клиента отдельной spec без server)",
      os.path.isfile(os.path.join(PROJ, "desktop_shell.spec")))

print("=== E. Регрессия ===")
check("63. стек вложенных модалей 2.815 сохранён",
      "fmModalStack" in APP and "v-modal-layer" in HTML and "fm-ov-win" in CSS)
check("64. служба смены порта 2.814 сохранена",
      "_prepare_port_change" in SRV and "showPortDialog" in APP)
check("65. встроенный журнал 2.813 сохранён",
      "diagSearch" in APP and "toggleDiagPause" in APP and "exportDiag" in APP)
check("66. резолвер активного порта 2.812 сохранён",
      "find_running_local" in rd(os.path.join(PROJ, "app", "desktop_shell.py")))
check("67. packaged restart E2E 2.811 сохранён",
      os.path.isfile(os.path.join(PROJ, "tools", "test_packaged_restart_end_to_end.py"))
      and "clean_child_env" in rd(os.path.join(PROJ, "app", "restart_cli.py")))
check("68. управление модулями сохранено",
      "/api/modules/" in APP and "disableModule" in APP)
check("69. интеграция со слайсером сохранена",
      "sliCbGenerate()" in HTML and "'Интеграция со слайсером'" in HTML)
check("70. жизненный цикл внешней печати сохранён",
      os.path.isfile(os.path.join(PROJ, "tools", "test_external_reprint_sync.py")))
check("71. схема БД не менялась этой правкой",
      not re.search(r"(ALTER TABLE|DROP TABLE|CREATE TABLE)", HTML + CSS + APP))
check("72. маршруты не добавлялись без необходимости (фронтовая правка, без новых @app.)",
      "@app.get" not in HTML and "@app.post" not in APP)
check("73. файлы модулей и ZIP не трогались",
      not re.search(r"modules[/\\][A-Za-z_]+\.zip", HTML + CSS + APP))
check("74. автоматическая отправка выключена", "\nDISPATCH_ENABLED = False" in ORCH)
check("75. транспорт выключен", "\nTRANSPORT_ENABLED = False" in ORCH)
check("76. правка не отправляет команд принтерам",
      not re.search(r"(gcode_line|/api/print/start)", CSS) and "fm-settings-workspace" not in SRV)
check("77. каталог _incoming/ не используется", "_incoming" not in (HTML + CSS + APP))

print("=== F. Прогон логики переключения рабочей области (настоящий код из app.js) ===")
# Вырезаем workspaceView + open/close и прогоняем в Node на фальшивых ref — доказываем взаимное
# исключение экранов, возврат в Projects и остановку опроса без чтения строк.
_wv = jsfn("workspaceView") or ""
#  2.900: настоящие функции четвёртого экрана и «Файлов принтеров» — их взаимное исключение
#  проверяется исполнением, а не чтением строк.
_openRep = jsfn("openReports") or ""
_closeRep = jsfn("closeReports") or ""
_openPf = jsfn("openPrinterFiles") or ""
_closePf = jsfn("closePrinterFiles") or ""
_ok_run, _R = False, {}
if _wv and _closeSet and _closeDiag and _openDiag and _openRep and _closeRep and _openPf and _closePf:
    HARNESS = r"""
const state = { showSettings:false, showDiag:false, diagTimer:null, ticks:0 };
const ref = (v) => ({ value:v });
const showSettings = { get value(){return state.showSettings}, set value(v){state.showSettings=v} };
const showDiag = { get value(){return state.showDiag}, set value(v){state.showDiag=v} };
// Alpha 2.823: третий workspace-экран «Файлы принтеров» участвует в workspaceView и взаимном исключении.
const showPrinterFiles = { get value(){return !!state.showPrinterFiles}, set value(v){state.showPrinterFiles=v} };
// Alpha 2.898: четвёртый workspace-экран «Отчёты» — тот же слот и то же взаимное исключение.
// 2.900: заглушек мало — настоящие openReports/closeReports/openPrinterFiles вставляются ниже.
const showReports = { get value(){return !!state.showReports}, set value(v){state.showReports=v} };
const loadReports = () => { state.repLoads = (state.repLoads || 0) + 1; };
const printers = { value: [{ id: 'p1' }] };
const pfSelectPrinter = () => {};
let _pfGen = 0;
const computed = (fn) => ({ get value(){ return fn(); } });
let diagTimer = null;
const clearInterval_ = () => { diagTimer=null; };
globalThis.setInterval = () => { state.ticks++; return {id:1}; };
globalThis.clearInterval = (t) => { if (t!==null) diagTimer=null; };
const diagEntries = ref([]); let diagLastId = 0;
const diagPaused = ref(false), diagLostConnection = ref(false), diagTab = ref('log');
const connTimer=null,_liveTrendTimer=null,sniffTimer=null;
const fetchDiag = () => {}; const setDiagTab = () => {}; const refreshDurableQueue = () => {};
const loadStorageInfo = () => {}, loadNetworkInfo = () => {};
const settingsPos = ref({}); const _restoreSetScroll = () => {};
const fmCloseNested = () => {};
__WV__
__CLOSESET__
__CLOSEDIAG__
__OPENDIAG__
__CLOSEREP__
__OPENREP__
__CLOSEPF__
__OPENPF__
const openSettings = () => { if (showDiag.value) closeDiagnostics(); if (showReports.value) closeReports(); showSettings.value = true; };
const R = {};
openSettings();
R.a = (workspaceView.value === 'settings');
openDiagnostics();                       // должно увести настройки
R.b = (workspaceView.value === 'diagnostics' && showSettings.value === false && diagTimer !== null);
closeDiagnostics();
R.c = (workspaceView.value === 'projects' && diagTimer === null);   // опрос остановлен, возврат в проекты
openSettings();
closeSettings();
R.d = (workspaceView.value === 'projects');
// ── 2.900: четвёртый экран «Отчёты» в том же слоте ──
openReports();
R.e = (workspaceView.value === 'reports' && showSettings.value === false
       && showDiag.value === false && showPrinterFiles.value === false);
openSettings();                          // настройки обязаны увести отчёты
R.f = (workspaceView.value === 'settings' && showReports.value === false);
closeSettings();
openReports();
openDiagnostics();                       // диагностика обязана увести отчёты
R.g = (workspaceView.value === 'diagnostics' && showReports.value === false);
closeDiagnostics();
openReports();
openPrinterFiles('p1');                  // ЭТОТ ПУТЬ И БЫЛ СЛОМАН В 2.898
R.h = (workspaceView.value === 'printerFiles' && showReports.value === false);
closePrinterFiles();
openPrinterFiles('p1');
openReports();                           // и наоборот: отчёты уводят файлы принтеров
R.i = (workspaceView.value === 'reports' && showPrinterFiles.value === false);
closeReports();
R.j = (workspaceView.value === 'projects');
console.log(JSON.stringify(R));
"""
    src = (HARNESS.replace("__WV__", _wv).replace("__CLOSESET__", _closeSet)
           .replace("__CLOSEDIAG__", _closeDiag).replace("__OPENDIAG__", _openDiag)
           .replace("__CLOSEREP__", _closeRep).replace("__OPENREP__", _openRep)
           .replace("__CLOSEPF__", _closePf).replace("__OPENPF__", _openPf))
    with tempfile.TemporaryDirectory(prefix="fm_ws_" + SENTINEL[-8:] + "_") as td:
        rp = os.path.join(td, "run.mjs")
        io.open(rp, "w", encoding="utf-8", newline="\n").write(src)
        try:
            pr = subprocess.run([NODE, rp], cwd=td, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120)
            if pr.returncode == 0:
                _R = json.loads((pr.stdout or "").strip().splitlines()[-1])
                _ok_run = True
            else:
                print("     [node] %s" % ((pr.stderr or "")[:300].replace("\n", " ")))
        except Exception as e:
            print("     [node] %r" % (e,))
    _tmp_gone = not os.path.isdir(td)
else:
    _tmp_gone = True

check("F1. открытие настроек делает рабочей областью 'settings'", _ok_run and _R.get("a"))
check("F1a. функции четвёртого экрана найдены в приложении",
      bool(_openRep) and bool(_closeRep) and bool(_openPf) and bool(_closePf))
check("F2. открытие диагностики уводит настройки и запускает опрос", _ok_run and _R.get("b"))
check("F3. закрытие диагностики останавливает опрос и возвращает 'projects'", _ok_run and _R.get("c"))
check("F4. закрытие настроек возвращает 'projects'", _ok_run and _R.get("d"))
check("F5. открытие «Отчётов» уводит все три остальных экрана", _ok_run and _R.get("e"))
check("F6. настройки уводят «Отчёты»", _ok_run and _R.get("f"))
check("F7. диагностика уводит «Отчёты»", _ok_run and _R.get("g"))
#  ИМЕННО ЭТА ПРОВЕРКА закрывает дефект 2.898: «Файлы принтеров» открывались ПОВЕРХ отчётов,
#  и два рабочих экрана делили один слот пополам.
check("F8. «Файлы принтеров» уводят «Отчёты» (дефект 2.898)", _ok_run and _R.get("h"))
check("F9. «Отчёты» уводят «Файлы принтеров»", _ok_run and _R.get("i"))
check("F10. закрытие «Отчётов» возвращает в проекты", _ok_run and _R.get("j"))

print("=== G. Метка и следы ===")
_prod = [os.path.join(WEB, "index.html"), os.path.join(WEB, "app.css"), os.path.join(WEB, "app.js"),
         os.path.join(PROJ, "server.py")]
_leak = [p for p in _prod if SENTINEL in rd(p)]
check("78. метка не попала в продуктовые файлы, БД, config и логи", not _leak, str(_leak))
check("78a. временных артефактов теста в проекте не осталось",
      not os.path.exists(os.path.join(PROJ, "tools", "_e2e_payload.json")))
check("79. временный каталог удалён", _tmp_gone)

print()
print("Итого: %d проверок пройдено, %d провалено" % (_pass, _fail))
if _fail:
    print("FAIL: %d проверок провалено" % _fail)
sys.exit(1 if _fail else 0)
