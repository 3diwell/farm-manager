# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.847 — кнопки управления в раскрытой ячейке принтера: подпись помещается и стоит по центру.

ЧТО ЗАЩИЩАЕТ. Два дефекта, найденных владельцем и исправленных в Alpha 2.844-2.846.

  1. ЗНАЧОК СЪЕДАЛ ЦЕНТРОВКУ. Подпись была одной строкой «▶ Старт», и по центру вставала строка
     ВМЕСТЕ со значком: формально идеально (отклонение строки 0.00 px), а само слово уезжало
     вправо на 9.3 px («Старт», «Стоп») и 10.4 px («Пауза»), потому что значок занимает слева
     12-16 px. Глаз читает слово, поэтому кнопка выглядела перекошенной. Лечение: значок вынесен
     в отдельный элемент `.pc-ctl-ic` и позиционируется слева, в потоке остаётся только слово.

  2. ПОДПИСЬ «ПЕЧАТЬ» НЕ ПОМЕЩАЛАСЬ. Ширина кнопки задана жёстко, и на Georgia текст выходил за
     край на 1.4 px, на Verdana на 0.7 px. Лечение: размер подписи уменьшен (через --text-scale,
     чтобы регулятор размера текста продолжал действовать), ширина кнопки НЕ менялась.

ПОЧЕМУ ИЗМЕРЕНИЕМ, А НЕ ГЛАЗАМИ. Оба дефекта прожили в программе долго именно потому, что их
никто не измерял: «вроде нормально» их не ловит. Проверка меряет фактическую геометрию — центр
слова относительно центра кнопки и зазор от текста до края — на ВСЕХ шрифтах из настроек,
потому что дефект проявлялся только на части из них.

ЯЗЫК. Меряются РУССКИЕ подписи: английские («PRINT») короче и дефект по ширине не показывают.
Язык переключается настоящим кликом по шапке, как это делает владелец.

ПРОВЕРКА НЕ ВАКУУМНАЯ. Отдельным прогоном воспроизводятся оба прежних дефекта — значок
возвращается в поток (`position:static`) и подписи возвращается прежний размер, — и проверка
ОБЯЗАНА на них покраснеть. Если не краснеет, значит она ничего не меряет, и это тоже провал.

БЕЗОПАСНОСТЬ. Рабочая БД, DATA_DIR, config и production-рантайм не используются; принтеры
синтетические; ничего никуда не отправляется и не сохраняется.

Запуск:  python tools/test_printer_cell_buttons.py      (0 = кнопки в порядке)
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "PRINTER_CELL_BUTTONS_SENTINEL_2_847"

# Допуски. Центровка: 1 px — это половина «полупикселя» на каждую сторону, глазом неразличимо,
# а прежний дефект был 9-10 px, то есть на порядок больше. Зазор: 1 px — минимум, при котором
# текст не касается рамки; на момент написания худший шрифт (Georgia) даёт 3.5 px.
MAX_WORD_OFFSET_PX = 1.0
MIN_SLACK_PX = 1.0

PRINTERS = [
    {"id": "p1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
     "ip": "127.0.0.1", "port": 8883, "serial": "S1", "access_code": ""},
]

# Стеки — те же, что в uiFonts (web/app.js); совпадение сверяет проверка 4a. Дефект проявлялся
# не на всех шрифтах, поэтому проверяются все. Шрифт по умолчанию — 3DIWELL Wide J (с 26.09.2026,
# fonts.css); brand — Wide P: у него, как у шрифта по умолчанию, работает увеличение html{zoom:1.196}.
FONTS_JS = """[
 {key:'default',     stack:''},
 {key:'wide-p',      stack:"'3DIWELL Wide P', sans-serif", brand:true},
 {key:'segoe',       stack:"'Segoe UI', system-ui, sans-serif"},
 {key:'tahoma',      stack:"Tahoma, Geneva, sans-serif"},
 {key:'calibri',     stack:"Calibri, 'Segoe UI', sans-serif"},
 {key:'arial',       stack:"Arial, Helvetica, sans-serif"},
 {key:'verdana',     stack:"Verdana, Geneva, sans-serif"},
 {key:'trebuchet',   stack:"'Trebuchet MS', Tahoma, sans-serif"},
 {key:'bahnschrift', stack:"Bahnschrift, 'Segoe UI', sans-serif"},
 {key:'georgia',     stack:"Georgia, 'Times New Roman', serif"},
 {key:'cambria',     stack:"Cambria, Georgia, serif"},
 {key:'times',       stack:"'Times New Roman', Times, serif"},
 {key:'mono',        stack:"Consolas, 'Cascadia Mono', ui-monospace, monospace"},
 {key:'courier',     stack:"'Courier New', Courier, monospace"}
]"""

JS = r"""
var FONTS = %(fonts)s;
var MARKS = ['ctl-start','ctl-stop','ctl-pause','ctl-print'];
var LOG = [];

// Шрифт применяется ровно так же, как это делает applyUiFont в app.js: подменой стиля
// #ui-font-override и зума <html> (1.196 у стандартного шрифта, из CSS у выбранного).
function applyFont(f){
  var el = document.getElementById('ui-font-override');
  if (!el) { el = document.createElement('style'); el.id = 'ui-font-override'; document.head.appendChild(el); }
  document.documentElement.style.zoom = (f.stack && !f.brand) ? '' : '1.196';
  el.textContent = f.stack ? ('* { font-family: ' + f.stack + " !important; }") : '';
  void document.body.offsetHeight;
}

function btn(m){ return document.querySelector('[data-tour-mark="' + m + '"]'); }

// Текстовый узел кнопки — это САМА подпись без значка: значок лежит в отдельном span.
function measure(m){
  var b = btn(m); if (!b) return null;
  var box = b.getBoundingClientRect(), node = null;
  for (var i = 0; i < b.childNodes.length; i++) {
    var n = b.childNodes[i];
    if (n.nodeType === 3 && n.textContent.trim()) { node = n; break; }
  }
  if (!node) return {mark: m, noText: true};
  var rg = document.createRange(); rg.selectNodeContents(node);
  var t = rg.getBoundingClientRect();
  var ic = b.querySelector('.pc-ctl-ic');
  var ir = ic ? ic.getBoundingClientRect() : null;
  return {
    mark: m, word: node.textContent.trim(),
    off: ((t.left + t.right) / 2) - ((box.left + box.right) / 2),
    slack: Math.min(t.left - box.left, box.right - t.right),
    hasIcon: !!ic,
    iconInside: ir ? (ir.left >= box.left - 0.5 && ir.right <= box.right + 0.5) : null,
    iconLeftOfWord: ir ? (ir.right <= t.left + 0.5) : null
  };
}

function sweep(){
  var res = {};
  for (var i = 0; i < FONTS.length; i++) {
    applyFont(FONTS[i]);
    var arr = [];
    for (var j = 0; j < MARKS.length; j++) { var r = measure(MARKS[j]); if (r) arr.push(r); }
    res[FONTS[i].key] = arr;
  }
  applyFont(FONTS[0]);
  return res;
}

// Мост снимает DOM сразу после вычисления выражения и отложенных вызовов НЕ ждёт — поэтому
// возвращаем Promise: он и есть разрешённый способ сделать здесь что-то асинхронное.
return new Promise(function(resolve){
  var later = document.querySelector('.fm-tour-start-later');
  if (later) click(later);

  setUiLang('ru');                       // настоящий клик по переключателю в шапке
  setTimeout(function(){
    var card = document.querySelector('.printer-card');
    if (card) click(card); else LOG.push('карточка принтера не найдена');
    setTimeout(function(){
      var out = {expanded: !!btn('ctl-print'), log: LOG};
      out.normal = sweep();

      // Воспроизведение прежних дефектов: значок обратно в поток, подписи — прежний размер.
      var bad = document.createElement('style');
      bad.textContent = '.pc-ctl-ic{position:static !important;}'
        + 'button[data-tour-mark="ctl-print"]{font-size:calc(10px*var(--text-scale)*var(--ts-mult)) !important;}';
      document.head.appendChild(bad);
      void document.body.offsetHeight;
      out.mutated = sweep();
      bad.remove();

      out.problems = (typeof FM_LOG !== 'undefined') ? FM_LOG : [];
      dump(out);
      resolve(true);
    }, 900);
  }, 900);
});
""" % {"fonts": FONTS_JS}

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def worst(sweep_res, field, pick):
    """Худшее значение поля по всем шрифтам и кнопкам: (значение, шрифт, кнопка)."""
    best = None
    for font, arr in (sweep_res or {}).items():
        for r in arr:
            if r.get(field) is None:
                continue
            v = abs(r[field]) if field == "off" else r[field]
            if best is None or pick(v, best[0]):
                best = (v, font, r.get("mark"))
    return best


print("=" * 78)
print("КНОПКИ УПРАВЛЕНИЯ В РАСКРЫТОЙ ЯЧЕЙКЕ ПРИНТЕРА")
print("=" * 78)

#  Список шрифтов теста обязан совпадать с настройками программы: иначе новый шрифт
#  останется непроверенным, а проверка — зелёной.
import io as _io  # noqa: E402
import re as _re  # noqa: E402
_APP = _io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
_ui = _APP[_APP.index("const uiFonts = ["):]
_ui = _ui[:_ui.index("];")]
APP_FONTS = [(m.group(1), m.group(2), bool(m.group(3)))
             for m in _re.finditer(r"key:\s*'([^']+)'.*?stack:\s*(\"[^\"]*\"|'[^']*')\s*(,\s*brand:\s*true)?", _ui)]
APP_FONTS = [(k, st[1:-1], b) for k, st, b in APP_FONTS]
TEST_FONTS = [(m.group(1), m.group(2)[1:-1], bool(m.group(3)))
              for m in _re.finditer(r"key:'([^']+)',\s*stack:(\"[^\"]*\"|'[^']*')(,\s*brand:true)?", FONTS_JS)]
N_FONTS = len(TEST_FONTS)
check("4a. шрифты теста — ровно шрифты настроек программы (ключ, набор, увеличение)",
      APP_FONTS == TEST_FONTS and N_FONTS >= 14, {"программа": APP_FONTS, "тест": TEST_FONTS})

if not stage.engine_ready():
    check("1. браузерный движок доступен (без него геометрию мерить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    stage.set_api({"/api/printers": PRINTERS})
    R = stage.run(JS, window_size=(1440, 900), settle_ms=2200) or {}

    check("1. прогон состоялся", bool(R.get("normal")), stage.last_diag() if not R else "")

    if R.get("normal"):
        # Язык подтверждается САМОЙ подписью, а не косвенным признаком: измеряется ровно то,
        # что видит владелец. Английские «Start»/«PRINT» короче и дефект по ширине прячут.
        _words = sorted({r.get("word") for arr in R["normal"].values() for r in arr if r.get("word")})
        check("2. меряются русские подписи (английские короче и дефект прячут)",
              "Старт" in _words and any(w.lower() == "печать" for w in _words), _words)
        check("3. ячейка принтера раскрыта и кнопки управления найдены",
              bool(R.get("expanded")), R.get("log"))

        normal = R["normal"]
        n_fonts = len(normal)
        n_btns = sum(len(v) for v in normal.values())
        check("4. измерены все %d шрифтов и все 4 кнопки на каждом" % N_FONTS,
              n_fonts == N_FONTS and n_btns == 4 * N_FONTS, {"шрифтов": n_fonts, "измерений": n_btns})

        no_text = [(f, r["mark"]) for f, arr in normal.items() for r in arr if r.get("noText")]
        check("5. у каждой кнопки есть текстовая подпись (значок не поглотил её)", not no_text, no_text)

        w_off = worst(normal, "off", lambda v, b: v > b)
        check("6. слово стоит по центру кнопки на всех шрифтах (допуск %.1f px)" % MAX_WORD_OFFSET_PX,
              w_off is not None and w_off[0] <= MAX_WORD_OFFSET_PX,
              "худшее: %.2f px, шрифт %s, кнопка %s" % w_off if w_off else "нет данных")

        w_slack = worst(normal, "slack", lambda v, b: v < b)
        check("7. подпись помещается в кнопку на всех шрифтах (зазор не меньше %.1f px)" % MIN_SLACK_PX,
              w_slack is not None and w_slack[0] >= MIN_SLACK_PX,
              "худшее: %.2f px, шрифт %s, кнопка %s" % w_slack if w_slack else "нет данных")

        icons = [(f, r["mark"]) for f, arr in normal.items() for r in arr
                 if r.get("hasIcon") and not (r.get("iconInside") and r.get("iconLeftOfWord"))]
        check("8. значок внутри кнопки и слева от слова (не налезает на подпись)", not icons, icons)

        with_icon = [r for arr in normal.values() for r in arr if r.get("hasIcon")]
        check("9. значки вообще есть — проверка 8 не пустая", len(with_icon) >= 3 * N_FONTS,
              {"кнопок со значком": len(with_icon)})

        # --- проверка не вакуумная: прежние дефекты обязаны краснеть ---
        mut = R.get("mutated") or {}
        m_off = worst(mut, "off", lambda v, b: v > b)
        check("10. НЕ ВАКУУМ: возвращённый в поток значок снова сбивает слово с центра",
              m_off is not None and m_off[0] > MAX_WORD_OFFSET_PX,
              "худшее при дефекте: %.2f px (ожидалось больше %.1f)" % (m_off[0], MAX_WORD_OFFSET_PX)
              if m_off else "нет данных")

        m_slack = worst(mut, "slack", lambda v, b: v < b)
        check("11. НЕ ВАКУУМ: прежний размер подписи снова не помещается в кнопку",
              m_slack is not None and m_slack[0] < MIN_SLACK_PX,
              "худшее при дефекте: %.2f px (ожидалось меньше %.1f)" % (m_slack[0], MIN_SLACK_PX)
              if m_slack else "нет данных")

        probs = stage.page_problems(R)
        check("12. ошибок консоли, исключений и предупреждений Vue нет", not probs, probs)

        print("\n   Худшее по норме:  центр %s   зазор %s" % (
            ("%.2f px (%s, %s)" % w_off) if w_off else "-",
            ("%.2f px (%s, %s)" % w_slack) if w_slack else "-"))
        print("   Худшее при дефекте: центр %s   зазор %s" % (
            ("%.2f px (%s, %s)" % m_off) if m_off else "-",
            ("%.2f px (%s, %s)" % m_slack) if m_slack else "-"))

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    print("НЕ ПРОЙДЕНО:")
    for f in _fail:
        print("   - %s" % f)
stage.stop()
sys.exit(1 if _fail else 0)
