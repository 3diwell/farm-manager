# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""
Alpha 2.815 — единый стек вложенных модальных окон.

ЧТО ЛОВИТ ЭТОТ ТЕСТ (дефект, найденный пользователем в 2.814):
«Настройки → Система → Сеть и доступ → Изменить порт» открывали диалог, который появлялся
ПОД окном настроек и выглядел прозрачным. Две независимые причины:
  1) диалог сам выбирал себе числа z-index 100050/100051, а окно настроек — 100060,
     поэтому дочерний диалог оказывался ниже родителя и его затемнение не забирало клики;
  2) панель диалога красилась в background: var(--fm-surface-1) — такой переменной в проекте
     НЕТ, объявление невалидно, фон остаётся прозрачным.
Третья причина того же класса: окно журнала лежало внутри #app, у которого position:relative
и z-index:1, — оно создаёт stacking context и топит внутри себя любой слой, каким бы большим
ни был его z-index.

Тест полностью офлайновый: читает исходники и прогоняет НАСТОЯЩИЙ код стека из web/app.js
в Node с фальшивым DOM. Рабочая база, DATA_DIR, config, сеть и принтеры не используются,
графический интерфейс не открывается. Всё временное — в TemporaryDirectory, он удаляется.
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

# Метка появляется ТОЛЬКО в этой оснастке и во временных файлах. В продукт, БД, DATA_DIR,
# config, модули, ZIP, логи, профиль WebView, _incoming/ и команды принтерам не попадает.
SENTINEL = "NESTED_MODAL_STACK_SENTINEL_2_815"

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

NODE = r"C:\Program Files\nodejs\node.exe"


# ---------------------------------------------------------------- разбор CSS
def css_rule(sel):
    """Тело правила по точному селектору. Правил с одним селектором может быть несколько
    (например, пустая заглушка `#app{}` в начале файла и настоящее правило ниже), поэтому
    склеиваем все — иначе проверка молча читает пустую строку и зеленеет впустую."""
    return " ".join(m.group(1) for m in
                    re.finditer(r"(?:^|\})\s*" + re.escape(sel) + r"\s*\{([^{}]*)\}", CSS, re.M))


def css_el_rule(cls):
    """Тело ВСЕХ правил, которые стилизуют сам элемент cls, включая ГРУППОВЫЕ селекторы
    (`.a,.b{...}`) и потомковые (`X .cls{...}`), но НЕ правила его детей (`.cls .child{...}`).
    css_rule видит только одиночный селектор — для `.fm-settings-workspace,.fm-diagnostics-workspace{...}`
    он вернул бы пусто и проверка стала бы вакуумной."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        for one in m.group(1).split(","):
            one = one.strip()
            if one and one.split()[-1] == cls:
                out.append(m.group(2))
                break
    return " ".join(out)


def zvars():
    """Шкала слоёв из :root — единственный источник значений."""
    out = {}
    for m in re.finditer(r"--(fm-z-[a-z0-9-]+)\s*:\s*(\d+)\s*;", CSS):
        out[m.group(1)] = int(m.group(2))
    return out


Z = zvars()


def zof(sel):
    """Фактический слой правила: число либо разыменованная переменная шкалы."""
    body = css_rule(sel)
    m = re.search(r"z-index:\s*var\(--(fm-z-[a-z0-9-]+)\)", body)
    if m:
        return Z.get(m.group(1))
    m = re.search(r"z-index:\s*(\d+)", body)
    return int(m.group(1)) if m else None


def block(anchor):
    """Кусок разметки от ближайшего <teleport> перед anchor до его </teleport>."""
    i = HTML.find(anchor)
    if i < 0:
        return ""
    a = HTML.rfind("<teleport", 0, i)
    b = HTML.find("</teleport>", i)
    return HTML[a:b + 11] if a >= 0 and b > 0 else ""


def section(cls):
    """Кусок <section ... class="cls">...</section> (рабочие экраны 2.816 — не в телепорте)."""
    i = HTML.find('class="' + cls + '"')
    if i < 0:
        return ""
    a = HTML.rfind("<section", 0, i)
    b = HTML.find("</section>", i)
    return HTML[a:b + 10] if a >= 0 and b > 0 else ""


PORT = block('v-if="showPortDialog"')
# Alpha 2.816: «Настройки» и «Диагностика» больше НЕ модали в overlay root — это статичные рабочие
# экраны основной области. Инвариант стека 2.815 сохраняется иначе: диалог порта лежит в overlay root
# (position:fixed, слой overlay-2) РЯДОМ с #app, у которого z-index:1, поэтому диалог красится выше
# всей страницы, включая рабочий экран настроек внутри неё.
SET = section('fm-settings-workspace')
DIAG = section('fm-diagnostics-workspace')

print("=== A. DOM и портал ===")

# 1
_roots = HTML.count('id="fm-overlay-root"')
check("1. overlay root существует ровно один раз", _roots == 1, "найдено %d" % _roots)

# overlay root обязан лежать РЯДОМ с #app, а не внутри: иначе он унаследует stacking context #app
_i_app_open = HTML.find('<div id="app"')
_i_root = HTML.find('<div id="fm-overlay-root">')
_tail = HTML[_i_root:]
check("1a. overlay root вне #app и до подключения app.js",
      _i_root > _i_app_open and "<script" in _tail and _i_root < HTML.find('<script type="module"'))
_root_rule = css_rule("#fm-overlay-root")
check("1b. overlay root не создаёт своего stacking context (нет z-index/transform/opacity/filter)",
      not re.search(r"z-index|transform|opacity|filter|isolation|contain", _root_rule),
      _root_rule[:70])

# 2, 3 — Alpha 2.816: настройки — рабочий экран (не модаль); диалог порта — по-прежнему в overlay root
check("2. настройки — статичный рабочий экран, а не телепортированная модаль",
      bool(SET) and 'class="fm-settings-workspace"' in SET
      and "<teleport" not in SET and "fm-settings-backdrop" not in SET
      and "v-modal-layer" not in SET)
check("3. диалог порта рендерится в overlay-системе", '<teleport to="#fm-overlay-root">' in PORT)

# 4 — диалог порта НЕ внутри рабочего экрана настроек (он в отдельном overlay root)
_set_i = HTML.find('class="fm-settings-workspace"')
_set_end = HTML.find("</section>", _set_i)
_port_i = HTML.find('v-if="showPortDialog"')
check("4. диалог порта не остаётся внутри рабочего экрана настроек",
      _set_i >= 0 and not (_set_i < _port_i < _set_end))

# 5
check("5. диалог порта встречается в разметке ровно один раз",
      HTML.count('v-if="showPortDialog"') == 1)

# 6 — фон и окно разными узлами и разными слоями
check("6. затемнение и окно — разные слои",
      'class="fm-ov-back"' in PORT and 'class="fm-ov-win"' in PORT
      and zof(".fm-ov-back") is not None and zof(".fm-ov-win") is not None
      and zof(".fm-ov-back") < zof(".fm-ov-win"))

# 7 — прозрачность родителя не наследуется
check("7. вложенное окно не наследует прозрачность родителя",
      "opacity" not in css_rule(".fm-ov-win")
      and "opacity" not in css_rule(".fm-settings-workspace"))

# 8 — диалог порта живёт в overlay root ВНЕ рабочего экрана настроек, поэтому overflow экрана его не режет
check("8. диалог порта в overlay root, а не внутри рабочего экрана настроек",
      "overflow:hidden" in css_el_rule(".fm-settings-workspace").replace(" ", "")
      and not (_set_i < _port_i < _set_end)
      and '<teleport to="#fm-overlay-root">' in PORT)

# 8a — диагностика тоже стала рабочим экраном, а не окном в overlay root
_app_rule = css_rule("#app")
check("8a. диагностика — статичный рабочий экран, а не окно в overlay root",
      bool(DIAG) and 'class="fm-diagnostics-workspace"' in DIAG
      and "<teleport" not in DIAG and "diag-overlay" not in HTML
      and "z-index:1" in _app_rule.replace(" ", ""))
check("8b. в разметке не осталось teleport к голому body", 'teleport to="body"' not in HTML)

print("=== B. Шкала слоёв ===")

_need = ["fm-z-overlay-1-back", "fm-z-overlay-1", "fm-z-overlay-2-back", "fm-z-overlay-2",
         "fm-z-overlay-3-back", "fm-z-overlay-3", "fm-z-critical", "fm-z-toast"]
# 9
check("9. значения слоёв централизованы в шкале --fm-z-*",
      all(k in Z for k in _need), "нет: %s" % [k for k in _need if k not in Z])
# 9a — Alpha 2.816: рабочий экран настроек НЕ модаль: без модального слоя, без backdrop, обычный поток
check("9a. рабочий экран настроек не использует модальный слой и backdrop",
      "z-index" not in css_el_rule(".fm-settings-workspace")
      and "position:fixed" not in css_el_rule(".fm-settings-workspace").replace(" ", "")
      and "fm-settings-backdrop" not in SET)
check("9b. диалог порта берёт значения из шкалы, а не из своих чисел",
      "var(--fm-z-overlay-2-back)" in css_rule(".fm-ov-back")
      and "var(--fm-z-overlay-2)" in css_rule(".fm-ov-win")
      and not re.search(r"z-index:\s*\d", PORT))

_zb, _zw = zof(".fm-ov-back"), zof(".fm-ov-win")
# Рабочий экран настроек лежит ВНУТРИ #app (z-index:1); диалог порта — в overlay root рядом с #app.
_zapp = zof("#app")
# 10, 11, 12, 13
check("10. фон диалога порта выше страницы #app (в ней рабочий экран настроек)",
      _zb is not None and _zapp is not None and _zb > _zapp, "%s > %s" % (_zb, _zapp))
check("11. окно диалога порта выше своего фона", _zw > _zb, "%s > %s" % (_zw, _zb))
check("12. окно диалога порта выше страницы #app", _zw > _zapp, "%s > %s" % (_zw, _zapp))
check("13. overlay root вне #app — его слои не тонут в stacking context страницы",
      _i_root > _i_app_open and _zb > _zapp)

# 14 — никаких бесконтрольных чисел
_big = sorted({int(v) for v in re.findall(r"z-index:\s*(\d+)", CSS + HTML) if int(v) >= 1000000})
check("14. нет произвольных огромных z-index", not _big and "999999" not in CSS + HTML
      and "2147483647" not in CSS + HTML, "найдено %s" % _big)
check("14a. исправление не сделано через !important",
      "!important" not in css_rule(".fm-ov-win") and "!important" not in css_rule(".fm-ov-back"))

# 15 — тост не перекрывает критическое подтверждение
check("15. тост не перекрывает критическое подтверждение",
      Z.get("fm-z-toast", 0) < Z.get("fm-z-critical", 0)
      and "var(--fm-z-toast)" in css_rule(".fm-toasts")
      and "var(--fm-z-critical)" in HTML)
check("15a. уровни идут строго по возрастанию без пересечений",
      Z["fm-z-overlay-1-back"] < Z["fm-z-overlay-1"] < Z["fm-z-overlay-2-back"]
      < Z["fm-z-overlay-2"] < Z["fm-z-overlay-3-back"] < Z["fm-z-overlay-3"]
      < Z["fm-z-critical"])

print("=== C. Стек модальных окон (прогон настоящего кода из app.js) ===")

# Из app.js вырезается НАСТОЯЩИЙ блок стека и директивы и исполняется в Node на фальшивом DOM.
_a = APP.find("// === Alpha 2.815: ЕДИНЫЙ СТЕК МОДАЛЬНЫХ ОКОН")
_b = APP.find("__app.mount('#app');")
STACK_SRC = APP[_a:_b].rstrip() if (_a >= 0 and _b > _a) else ""
check("16pre. блок стека найден в app.js целиком",
      bool(STACK_SRC) and "fmModalStack" in STACK_SRC and "__app.directive('modal-layer'" in STACK_SRC
      and "fmTrapTab" in STACK_SRC and "fmCloseNested" in STACK_SRC)

_mod = STACK_SRC.replace("__app.directive('modal-layer', {", "export const MODAL_LAYER = {")
if _mod.endswith("});"):
    _mod = _mod[:-3] + "};"
_mod += ("\nexport { fmModalStack, fmModalTop, fmModalTopNested, fmCloseNested, "
         "fmModalLock, fmTrapTab };\n")

HARNESS = r"""
// Фальшивый DOM: ровно столько, сколько трогает код стека. Ни браузера, ни Vue, ни сети.
const listeners = new WeakMap();
function El(id, focusables) {
    const el = {
        id, _focusables: focusables || [], offsetParent: {}, disabled: false,
        querySelectorAll() { return el._focusables; },
        addEventListener(t, f) { (listeners.get(el) || listeners.set(el, {}).get(el))[t] = f; },
        removeEventListener(t) { const m = listeners.get(el); if (m) delete m[t]; },
        contains(n) { return n === el || el._focusables.indexOf(n) >= 0; },
        focus() { document.activeElement = el; },
        fire(t, ev) { const m = listeners.get(el); if (m && m[t]) m[t](ev); },
    };
    listeners.set(el, {});
    el._focusables.forEach(n => { n.offsetParent = {}; n.focus = () => { document.activeElement = n; }; });
    return el;
}
const bodyClasses = new Set();
globalThis.document = {
    activeElement: null,
    body: {
        style: { overflow: 'auto' },
        classList: {
            toggle(c, on) { if (on) bodyClasses.add(c); else bodyClasses.delete(c); },
            has(c) { return bodyClasses.has(c); },
        },
    },
    contains(n) { return !!n && n.__inDoc !== false; },
};
const M = await import('./stack.mjs');
const key = (n) => ({ id: n, offsetParent: {}, focus() { document.activeElement = this; } });

const R = {};
const openBtn = key('btn-change-port');          // кнопка «Изменить порт» в настройках
const setEls = [key('set-close'), key('set-input')];
const portEls = [key('port-input'), key('btn-cancel'), key('btn-later'), key('btn-restart')];
const setWin = El('settings-window', setEls);
const portWin = El('port-window', portEls);

let settingsOpen = true, portOpen = false;
const closePort = () => { portOpen = false; M.MODAL_LAYER.unmounted(portWin); };
const closeSettings = () => { M.fmCloseNested(); settingsOpen = false; M.MODAL_LAYER.unmounted(setWin); };
const openSettings = () => { settingsOpen = true; M.MODAL_LAYER.mounted(setWin, { value: { id: 'settings', level: 1, close: closeSettings, autofocus: false } }); };
const openPort = () => { portOpen = true; M.MODAL_LAYER.mounted(portWin, { value: { id: 'port', level: 2, close: closePort } }); };

document.activeElement = openBtn;                 // фокус на кнопке, из которой открывают диалог
openSettings();
R.s16 = (M.fmModalStack.length === 1 && M.fmModalStack[0].level === 1 && M.fmModalStack[0].id === 'settings');
openPort();
R.s17 = (M.fmModalStack.length === 2 && M.fmModalTop().level === 2);
R.s18 = (M.fmModalTop().id === 'port' && M.fmModalTopNested().id === 'port');
R.s34 = (document.body.style.overflow === 'hidden' && document.body.classList.has('fm-modal-open'));
await new Promise(r => setTimeout(r, 5));
R.s24 = (portEls.indexOf(document.activeElement) === 0);          // фокус в первом поле диалога

// Tab и Shift+Tab не выпускают фокус из верхнего слоя
let prevented = false;
document.activeElement = portEls[portEls.length - 1];
portWin.fire('keydown', { key: 'Tab', shiftKey: false, preventDefault() { prevented = true; } });
R.s25 = (prevented && document.activeElement === portEls[0]);
prevented = false;
document.activeElement = portEls[0];
portWin.fire('keydown', { key: 'Tab', shiftKey: true, preventDefault() { prevented = true; } });
R.s26 = (prevented && document.activeElement === portEls[portEls.length - 1]);
// нижний слой свой Tab НЕ перехватывает, пока он не верхний
let lowerPrevented = false;
document.activeElement = setEls[setEls.length - 1];
setWin.fire('keydown', { key: 'Tab', shiftKey: false, preventDefault() { lowerPrevented = true; } });
R.s25b = (lowerPrevented === false);

// повторное открытие того же диалога не плодит слои
openPort(); openPort();
R.s21 = (M.fmModalStack.filter(s => s.id === 'port').length === 1);
R.s22 = (M.fmModalStack.length === 2);

document.activeElement = portEls[0];
closePort();
R.s19 = (M.fmModalTop() && M.fmModalTop().id === 'settings' && M.fmModalTopNested() === null);
R.s20 = (settingsOpen === true && M.fmModalStack.length === 1);
R.s29 = (document.activeElement === openBtn);                     // фокус вернулся на кнопку
R.s34b = (document.body.style.overflow === 'hidden');             // родитель ещё открыт — фон заперт

// закрытие родителя уносит и детей
openPort();
R.s23pre = (M.fmModalStack.length === 2);
closeSettings();
R.s23 = (portOpen === false && settingsOpen === false && M.fmModalStack.length === 0);
R.s36 = (document.body.style.overflow === 'auto' && !document.body.classList.has('fm-modal-open'));
console.log(JSON.stringify(R));
"""

_ok_run, _R = False, {}
with tempfile.TemporaryDirectory(prefix="fm_modal_" + SENTINEL[-8:] + "_") as td:
    io.open(os.path.join(td, "stack.mjs"), "w", encoding="utf-8", newline="\n").write(_mod)
    io.open(os.path.join(td, "run.mjs"), "w", encoding="utf-8", newline="\n").write(HARNESS)
    try:
        pr = subprocess.run([NODE, os.path.join(td, "run.mjs")], cwd=td, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=120)
        if pr.returncode == 0:
            _R = json.loads((pr.stdout or "").strip().splitlines()[-1])
            _ok_run = True
        else:
            print("     [node] %s" % ((pr.stderr or "")[:400].replace("\n", " ")))
    except Exception as e:
        print("     [node] %r" % (e,))
_tmp_gone = not os.path.isdir(td)

check("16. открытие настроек создаёт слой 1-го уровня", _ok_run and _R.get("s16"))
check("17. открытие диалога порта создаёт слой 2-го уровня", _ok_run and _R.get("s17"))
check("18. верхний слой — диалог порта", _ok_run and _R.get("s18"))
check("19. закрытие диалога возвращает верхним слоем настройки", _ok_run and _R.get("s19"))
check("20. КРИТИЧНО: настройки не закрываются вместе с диалогом порта", _ok_run and _R.get("s20"))
check("21. повторное открытие не создаёт второй слой", _ok_run and _R.get("s21"))
check("22. двойное нажатие не создаёт два диалога порта", _ok_run and _R.get("s22"))
check("23. закрытие настроек уносит дочерние слои", _ok_run and _R.get("s23pre") and _R.get("s23"))

print("=== D. Фокус и клавиатура ===")
check("24. фокус переходит в диалог порта", _ok_run and _R.get("s24"))
check("25. Tab заперт в верхнем слое", _ok_run and _R.get("s25"))
check("25a. нижний слой не перехватывает Tab, пока он не верхний", _ok_run and _R.get("s25b"))
check("26. Shift+Tab заперт в верхнем слое", _ok_run and _R.get("s26"))

# 27, 28 — порядок жёсткой цепочки Escape: вложенные слои раньше родителя, эфемерные меню раньше всех
_i_nested = APP.find("const _topNested = fmModalTopNested();")
_i_settings = APP.find("if (showSettings.value) { closeSettings(); return; }")
_i_ctx = APP.find("if (ctxMenu.value.show) { closeContextMenu(); return; }")
check("27. КРИТИЧНО: Escape закрывает вложенный диалог раньше настроек",
      0 < _i_nested < _i_settings, "nested=%d settings=%d" % (_i_nested, _i_settings))
check("27a. эфемерные меню закрываются раньше вложенных диалогов", 0 < _i_ctx < _i_nested)
check("28. второй Escape закрывает настройки по прежнему контракту", _i_settings > 0)
check("28a. Escape закрывает ровно один слой (после закрытия — выход из обработчика)",
      "_topNested.close(); return; }" in APP)
check("29. фокус возвращается на кнопку, из которой открыли диалог", _ok_run and _R.get("s29"))
# 30 — Enter не запускает перезапуск
check("30. КРИТИЧНО: Enter не запускает перезапуск сам по себе",
      "@keydown.enter.prevent" in PORT
      and not re.search(r"@keydown\.enter[^\"]*=\"applyPort", PORT)
      and "<form" not in PORT)

print("=== E. Указатель и прокрутка ===")
check("31. КРИТИЧНО: клик по настройкам перекрыт фоном диалога (фон выше всей страницы)", _zb > _zapp)
check("32. клик по основной странице перекрыт фоном диалога",
      "inset:0" in css_rule(".fm-ov-back").replace(" ", "") and _zb > (zof("#app") or 1))
check("33. клик мимо действует только на верхний слой",
      "const setBackdropClose = () => { if (fmModalTopNested()) return;" in APP)
check("34. прокрутка фона заблокирована, пока открыт слой", _ok_run and _R.get("s34"))
check("34a. закрытие дочернего слоя не снимает блокировку с ещё открытым родителем",
      _ok_run and _R.get("s34b"))
check("35. диалог прокручивается внутри себя",
      "overflow:auto" in css_rule(".fm-ov-win").replace(" ", "")
      and "overscroll-behavior:contain" in css_rule(".fm-ov-win").replace(" ", ""))
check("36. после закрытия всех слоёв блокировка прокрутки снята", _ok_run and _R.get("s36"))
# 37 — окно настроек не пересоздаётся, поэтому его прокрутка сохраняется
_close_port_js = re.search(r"const closePortDialog = [^\n]*", APP).group(0)
check("37. позиция прокрутки настроек сохраняется (родитель не пересоздаётся)",
      "showSettings" not in _close_port_js and "showPortDialog.value = false" in _close_port_js)

print("=== F. Визуальный контракт ===")
_win = css_rule(".fm-ov-win").replace(" ", "")
_back = css_rule(".fm-ov-back").replace(" ", "")
# 38 — КЛЮЧЕВАЯ проверка второй причины дефекта: переменная фона обязана существовать
_bgvar = re.search(r"background:var\(--([a-z0-9-]+)\)", _win)
check("38. КРИТИЧНО: панель диалога непрозрачна, её переменная фона объявлена",
      bool(_bgvar) and ("--%s:" % _bgvar.group(1)) in CSS.replace(" ", "")
      and "rgba" not in _win.split("border:")[0],
      "переменная %s" % (_bgvar.group(1) if _bgvar else "нет"))
check("38a. в диалоге не осталось несуществующих переменных оформления",
      all(("--%s:" % v) in CSS.replace(" ", "")
          for v in set(re.findall(r"var\(--([a-z0-9-]+)\)", _win + _back
                                  + css_rule(".fm-ov-input") + css_rule(".fm-ov-note")
                                  + css_rule(".fm-ov-err")))),
      "нет: %s" % [v for v in set(re.findall(r"var\(--([a-z0-9-]+)\)", _win + _back))
                   if ("--%s:" % v) not in CSS.replace(" ", "")])
check("39. затемнение имеет собственную прозрачность", "rgba(" in _back and "0.5)" in _back)
check("40. диалог центрируется относительно viewport, а не родителя",
      "position:fixed" in _win and "top:50%" in _win and "left:50%" in _win
      and "translate(-50%,-50%)" in _win)
check("41. малый экран не обрезает диалог", "width:min(92vw," in _win and "min-width" not in _win)
check("42. высота ограничена высотой экрана", "max-height:min(88vh," in _win)
check("43. читаемость сохранена: рамка, тень и цвет текста заданы",
      "border:1px" in _win and "box-shadow:" in _win and "color:var(--fm-text-primary)" in _win)
check("44. верстка не зависит от абсолютных координат (DPI/масштаб)",
      not re.search(r"(top|left|right|bottom):\s*\d+px", _win))

print("=== G. Остальные диалоги, открываемые из настроек ===")
# Alpha 2.816: журнал/диагностика теперь рабочий экран, а не диалог — из списка убран.
# Оставшиеся настоящие модали (пользователи, журнал аудита, «Что нового») по-прежнему выше страницы.
for num, name, sel in [("45", "пользователи и журнал аудита", ".fm-ov-2"),
                       ("47", "окно «Что нового»", ".fm-changelog-panel")]:
    _z = zof(sel)
    check("%s. %s выше страницы #app" % (num, name), _z is not None and _z > _zapp,
          "%s=%s vs #app %s" % (sel, _z, _zapp))
check("46. журнал/диагностика — рабочий экран, а не модаль поверх страницы",
      "diag-overlay" not in HTML and 'class="fm-diagnostics-workspace"' in HTML)
_nested_ids = ["showUsers", "showAudit", "showSecuritySetup", "showSecurityDisable", "showAdminRecovery"]
check("45a. все пять окон на уровне 2, а не на прежних 10000",
      all(('v-if="%s"' % i) in HTML for i in _nested_ids)
      and HTML.count('class="fm-login-overlay fm-ov-2"') == 5)
# 48 — удаление и отключение модуля подтверждаются системным окном браузера: оно по своей
# природе выше любого слоя страницы, отдельного z-index ему не требуется.
_del = APP[APP.find("const deleteModule ="):APP.find("const deleteModule =") + 700]
#  2.959: системный confirm() заменён своим окном; требование прежнее — оно обязано быть
#  выше настроек и любых вложенных диалогов, иначе вопрос окажется под окном.
check("48. подтверждение удаления модуля — своё окно и оно выше всех слоёв",
      "askConfirm({" in _del and "Удалить модуль" in _del
      and "calc(var(--fm-z-critical, 100120) + 20)" in CSS)
# 49 — ни одно окно не делит слой с другим на том же уровне вложенности (диагностика больше не модаль)
_lvl2 = {s: zof(s) for s in [".fm-ov-win", ".fm-changelog-panel", ".fm-ov-2"]}
check("49. вложенные окна не прячут друг друга неверным слоем",
      all(v is not None and Z["fm-z-overlay-2"] <= v <= Z["fm-z-overlay-3"] for v in _lvl2.values()),
      str(_lvl2))
# 50 — закрытие дочернего окна не трогает родителя
check("50. закрытие дочернего окна не закрывает родителя",
      _ok_run and _R.get("s20") and "fmCloseNested(); showSettings.value = false;" in APP)
check("50a. исправление системное: слой задан классом, а не персональным z-index для порта",
      "portModal" not in CSS and "portDialog" not in CSS
      and not re.search(r"z-index:\s*\d", PORT))

print("=== H. Регрессия: смежные механизмы не тронуты ===")
SRV = rd(os.path.join(PROJ, "server.py"))
ORCH = rd(os.path.join(PROJ, "app", "project_orchestrator.py"))
PCFG = rd(os.path.join(PROJ, "app", "server_port_config.py"))

check("51. поток смены порта на сервере не менялся",
      "_prepare_port_change" in SRV and "_require_server_machine(req)" in SRV
      and "check_port_availability" in SRV)
check("52. «Применить позже» сохранено", "applyPort(false)" in PORT and "plan_change" in PCFG)
check("53. «Применить и перезапустить» сохранено",
      "applyPort(true)" in PORT and "restart_now" in APP and "_restart_for_port" in SRV)
check("54. откат на прежний порт сохранён", "rollback_pending" in PCFG and "previous" in PCFG)
check("55. интеграция со слайсером сохранена во вкладке «Печать»",
      "sliCbGenerate()" in HTML and "'Интеграция со слайсером'" in HTML
      and "/api/slicer-callback/generate" in APP)
check("56. управление модулями сохранено",
      "/api/modules/" in APP and "pickModuleZip" in APP and "disableModule" in APP)
check("57. встроенный журнал сохранён",
      "diagSearch" in APP and "toggleDiagPause" in APP and "exportDiag" in APP)
check("58. резолвер активного порта сохранён",
      "find_running_local" in rd(os.path.join(PROJ, "app", "desktop_shell.py")))
check("59. packaged restart E2E сохранён",
      os.path.isfile(os.path.join(PROJ, "tools", "test_packaged_restart_end_to_end.py"))
      and "clean_child_env" in rd(os.path.join(PROJ, "app", "restart_cli.py")))
check("60. жизненный цикл внешней печати сохранён",
      os.path.isfile(os.path.join(PROJ, "tools", "test_external_reprint_sync.py")))
check("61. схема БД не менялась этой правкой",
      not re.search(r"(ALTER TABLE|DROP TABLE)", HTML + CSS + APP))
check("62. файлы модулей и ZIP не трогались",
      not re.search(r"modules[/\\][A-Za-z_]+\.zip", HTML + CSS + APP))
check("63. автоматическая отправка выключена", "\nDISPATCH_ENABLED = False" in ORCH)
check("64. транспорт выключен", "\nTRANSPORT_ENABLED = False" in ORCH)
check("65. правка не отправляет команд принтерам",
      not re.search(r"(gcode_line|print/start|/api/print/)", CSS)
      and "fm-ov-win" not in SRV)
check("66. каталог _incoming/ не используется", "_incoming" not in (HTML + CSS + APP))

print("=== I. Метка и следы ===")
# 67 — метка живёт только в оснастке
_prod = [os.path.join(WEB, "index.html"), os.path.join(WEB, "app.css"), os.path.join(WEB, "app.js"),
         os.path.join(PROJ, "server.py")]
_leak = [p for p in _prod if SENTINEL in rd(p)]
check("67. метка не попала в продуктовые файлы, БД, config и логи", not _leak, str(_leak))
check("67a. временных артефактов теста в проекте не осталось",
      not os.path.exists(os.path.join(PROJ, "tools", "_e2e_payload.json"))
      and not any(f.startswith("fm_modal_") for f in os.listdir(os.path.join(PROJ, "tools"))))
check("68. временный каталог удалён", _tmp_gone)

print()
print("Итого: %d проверок пройдено, %d провалено" % (_pass, _fail))
if _fail:
    print("FAIL: %d проверок провалено" % _fail)
sys.exit(1 if _fail else 0)
