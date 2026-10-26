# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""26.09.2026 — настройка «Размер текста» (Настройки → Общие → Оформление).

ЧТО ЗАЩИЩАЕТ. Заказ владельца: «увеличение и уменьшение шрифта, чтобы были варианты». Размеры шрифта
в программе заданы сотнями правил в точках, и --text-scale меняет лишь часть из них, поэтому размер
меняется свойством font-size-adjust на всех элементах сразу.

  1. Варианты 90–130 %, по умолчанию 100 %; при 100 % правила нет вовсе — вид ровно прежний.
  2. Выбор в настройках действительно меняет ВСЕ надписи в заданное число раз и сохраняется.
  3. Сохранённый выбор действует сразу при запуске (в том числе в интерфейсе 3.0).
  4. После смены шрифта размер пересчитывается под новый шрифт, а не остаётся от прежнего.
  5. Самые тесные подписи программы — кнопки раскрытой ячейки принтера — при 130 % помещаются, а
     на главном экране нет вылезающего текста и горизонтальной прокрутки.
  6. При 130 % поля выбора в настройках остаются в одну строку со всеми шрифтами (26.09.2026:
     длинная подпись «3DIWELL Wide J (из Jura)» переносилась в поле на вторую строку).

Запуск:  python tools/test_ui_text_size.py      (0 = всё в порядке)
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

_pass, _fail = [0], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:400]) if detail else ""))


def read(*p):
    return io.open(os.path.join(REPO, *p), encoding="utf-8").read()


print("=" * 78)
print("1. Код и разметка")
print("=" * 78)
APP = read("web", "app.js")
IDX = read("web", "index.html")
HINTS = read("web", "composables", "helpHints.js")
sizes = APP[APP.index("const uiTextSizes = ["):]
sizes = sizes[:sizes.index("];")]
opts = re.findall(r"key:\s*'(\d+)',\s*v:\s*([\d.]+)", sizes)
check("1.1 варианты 90, 100, 110, 120, 130 % с множителями 0.9 … 1.3",
      opts == [("90", "0.9"), ("100", "1"), ("110", "1.1"), ("120", "1.2"), ("130", "1.3")], opts)
check("1.2 по умолчанию 100 %, выбор хранится на этом компьютере",
      "const uiTextSize = ref('100');" in APP and "localStorage.setItem('ui_text_size', k)" in APP)
ap = APP[APP.index("const applyUiTextSize = "):APP.index("const setUiTextSize = ")]
check("1.3 при 100 % правила нет, иначе — font-size-adjust на всех элементах",
      "if (m === 1) return;" in ap and "'*{font-size-adjust:'" in ap and "!important}'" in ap, ap[:300])
check("1.4 смена шрифта пересчитывает размер текста",
      re.search(r"const setUiFont = \(k\) => \{[^\n]*applyUiTextSize\(\);", APP) is not None)
check("1.5 в настройках есть выбор размера текста",
      'data-help="set-text-size" @change="setUiTextSize($event.target.value)"' in IDX
      and 'v-for="t in uiTextSizes"' in IDX)
check("1.6 у выбора есть подсказка", '"set-text-size": {' in HINTS)
#  26.09.2026: шапка при шрифте Windows идёт своим шрифтом — ей своя поправка, иначе надпись брокера
#  росла в 1,4-1,7 раза и вылезала из язычка (проверяется в браузере набором test_header_tongue.py).
check("1.7 у шапки своя поправка размера текста, замеренная её шрифтом",
      "_uiFontAspect(hdr)" in ap and "'header.app-header,header.app-header *{font-size-adjust:'" in ap, ap[-700:])
_uf = APP[APP.index("const uiFonts = ["):]
N_APP_FONTS = len(re.findall(r"key:\s*'[^']+'", _uf[:_uf.index("];")]))

print("\n" + "=" * 78)
print("2-5. Настоящий браузер")
print("=" * 78)
import _fm_ui_stage as stage  # noqa: E402

PRINTERS = [{"id": "b1", "name": "H2D_01", "type": "bambu", "model": "Bambu Lab H2D", "ip": "127.0.0.1", "port": 8883},
            {"id": "f1", "name": "AD5M-01", "type": "flashforge", "model": "FlashForge Adventurer 5M", "ip": "127.0.0.1", "port": 8898}]

COMMON = r"""
function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
function labelW(){ var l=[].slice.call(document.querySelectorAll('.fm-set-lbl')).filter(function(e){ return /Размер текста|Text size/.test(e.textContent); })[0];
  if(!l) return 0; var r=document.createRange(); r.selectNodeContents(l); return r.getBoundingClientRect().width; }
function pick(sel, v){ var s=document.querySelector(sel); if(!s) return false; s.value=v; s.dispatchEvent(new Event('change',{bubbles:true})); return true; }
function rule(){ var e=document.getElementById('ui-text-size'); return e ? e.textContent : null; }
function selH(){ return [].slice.call(document.querySelectorAll('.fm-set-ctl .fm-set-select')).filter(function(x){
  return x.getBoundingClientRect().width > 2; }).map(function(x){ return Math.round(x.getBoundingClientRect().height); }); }
function vis(m){ return [].slice.call(document.querySelectorAll('[data-tour-mark="'+m+'"]')).filter(function(b){ return b.getBoundingClientRect().width>2; })[0]; }
function cells(){ return ['ctl-start','ctl-stop','ctl-pause','ctl-print'].map(function(m){ var b=vis(m); if(!b) return null;
  var box=b.getBoundingClientRect(), n=null; for(var i=0;i<b.childNodes.length;i++){ if(b.childNodes[i].nodeType===3 && b.childNodes[i].textContent.trim()){ n=b.childNodes[i]; break; } }
  if(!n) return {mark:m, noText:true}; var rg=document.createRange(); rg.selectNodeContents(n); var t=rg.getBoundingClientRect();
  return {mark:m, word:n.textContent.trim(), slack:Math.min(t.left-box.left, box.right-t.right), vslack:Math.min(t.top-box.top, box.bottom-t.bottom)}; }); }
function audit(){ var de=document.documentElement, bad=[];
  [].slice.call(document.querySelectorAll('button, a, label, th, td, li, [role=button]')).forEach(function(el){
    var r0=el.getBoundingClientRect(); if(r0.width<2||r0.height<2||el.classList.contains('fm-send-x')) return;
    var cs=getComputedStyle(el); if(cs.display==='none'||cs.visibility==='hidden') return;
    for(var i=0;i<el.childNodes.length;i++){ var nd=el.childNodes[i]; if(nd.nodeType!==3||!nd.textContent.trim()) continue;
      var rg=document.createRange(); rg.selectNodeContents(nd); var r=rg.getBoundingClientRect(); if(r.width<1) continue;
      var out=Math.max(r0.left-r.left, r.right-r0.right); if(out>1.5){ bad.push((el.className||el.tagName).toString().slice(0,40)+' «'+nd.textContent.trim().slice(0,20)+'» '+Math.round(out)); break; } } });
  return {hscroll: de.scrollWidth>de.clientWidth+1, outside: bad}; }
"""

JS_MAIN = COMMON + r"""
return new Promise(function(resolve){
  var out = {log: []};
  openStage('general', async function(){
    try {
      out.ruleDefault = rule();
      out.options = [].slice.call((document.querySelector('select[data-help="set-text-size"]')||{options:[]}).options).map(function(o){ return o.value; });
      var w100 = labelW();
      out.picked = pick('select[data-help="set-text-size"]', '130'); await sleep(300);
      out.ratio130 = labelW() / w100; out.saved = localStorage.getItem('ui_text_size'); out.rule130 = rule();
      pick('select[data-help="set-text-size"]', '90'); await sleep(300); out.ratio90 = labelW() / w100;
      // шрифт меняется при 130 %: размер обязан пересчитаться под новый шрифт
      pick('select[data-help="set-font"]', 'arial'); await sleep(200);
      pick('select[data-help="set-text-size"]', '100'); await sleep(250); var a100 = labelW();
      pick('select[data-help="set-text-size"]', '130'); await sleep(250); out.ratioArial = labelW() / a100;
      // 6. поля выбора в одну строку при 130 % со всеми шрифтами
      out.selH = {};
      var fonts = [].slice.call(document.querySelector('select[data-help="set-font"]').options).map(function(o){ return o.value; });
      for (var fi = 0; fi < fonts.length; fi++) {
        pick('select[data-help="set-font"]', fonts[fi]); await sleep(220);
        out.selH[fonts[fi]] = selH();
      }
      pick('select[data-help="set-font"]', 'default'); await sleep(250);
      pick('select[data-help="set-text-size"]', '100'); await sleep(250);
      out.ruleBack = rule(); out.savedBack = localStorage.getItem('ui_text_size');
    } catch(e) { out.log.push(String(e && e.message || e)); }
    out.problems = FM_LOG; dump(out); resolve(true);
  }, 'ru');
});
"""

JS_CELLS = COMMON + r"""
return new Promise(function(resolve){
  var out = {log: []};
  (async function(){
    try {
      var later = byText('button',['Позже','Later']); if (later) click(later);
      setUiLang('ru'); await sleep(900);
      out.rule = rule();
      var card = document.querySelector('.printer-card'); if (card) click(card); else out.log.push('нет карточки');
      await sleep(900);
      out.cells = cells(); out.audit = audit();
    } catch(e) { out.log.push(String(e && e.message || e)); }
    out.problems = FM_LOG; dump(out); resolve(true);
  })();
});
"""

if not stage.engine_ready():
    check("2.0 браузерный движок доступен", False, stage.last_diag())
else:
    stage.set_api({"/api/printers": PRINTERS, "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    R = stage.run(JS_MAIN, window_size=(1280, 800), settle_ms=2200) or {}
    check("2.0 прогон состоялся", "ratio130" in R, R.get("log") or stage.last_diag())
    if "ratio130" in R:
        check("2.1 при 100 % правила нет — вид ровно прежний", R.get("ruleDefault") == "", R.get("ruleDefault"))
        check("2.2 в списке пять вариантов", R.get("options") == ["90", "100", "110", "120", "130"], R.get("options"))
        check("2.3 130 % — надписи ровно в 1.3 раза крупнее", abs(R["ratio130"] - 1.3) <= 0.02, R["ratio130"])
        check("2.4 90 % — надписи мельче в 0.9 раза", abs(R.get("ratio90", 0) - 0.9) <= 0.02, R.get("ratio90"))
        check("2.5 выбор сохраняется на этом компьютере", R.get("saved") == "130", R.get("saved"))
        check("4.1 после смены шрифта 130 % пересчитаны под новый шрифт", abs(R.get("ratioArial", 0) - 1.3) <= 0.03,
              R.get("ratioArial"))
        check("2.6 возврат к 100 % убирает правило", R.get("ruleBack") == "" and R.get("savedBack") == "100",
              (R.get("ruleBack"), R.get("savedBack")))
        sh = R.get("selH") or {}
        bad = {k: v for k, v in sh.items() if v and max(v) - min(v) > 2}
        check("6.1 при 130 %% поля выбора в настройках в одну строку со всеми %d шрифтами" % len(sh),
              len(sh) >= N_APP_FONTS >= 14 and not bad, bad or sh)
        probs = stage.page_problems(R)
        check("2.7 ошибок консоли, исключений и предупреждений Vue нет", not probs, probs)

    #  3. Сохранённый выбор — при запуске, интерфейс 3.0 (ключ кладётся в хранилище до загрузки страницы)
    R3 = stage.run(COMMON + "return new Promise(function(r){ setTimeout(function(){ dump({rule: rule(), saved: "
                   "localStorage.getItem('ui_text_size')}); r(true); }, 1500); });",
                   window_size=(1280, 800), settle_ms=2200, path="/ui3?ls=ui_text_size:120") or {}
    check("3.1 сохранённые 120 % действуют сразу при запуске (интерфейс 3.0)",
          R3.get("saved") == "120" and "font-size-adjust" in (R3.get("rule") or ""), R3)

    #  5. Тесные места при 130 %
    for path, tag in (("/?ls=ui_text_size:130", "интерфейс 2.0"),):
        RC = stage.run(JS_CELLS, window_size=(1440, 900), settle_ms=2200, path=path) or {}
        cs = [c for c in (RC.get("cells") or []) if c]
        check("5.1 %s: при 130 %% кнопки раскрытой ячейки принтера найдены" % tag, len(cs) == 4, RC.get("cells") or RC.get("log"))
        if cs:
            worst = min(c.get("slack", -99) for c in cs)
            check("5.2 %s: при 130 %% подписи кнопок помещаются (запас не меньше 1 точки)" % tag, worst >= 1.0,
                  [(c.get("word"), round(c.get("slack", 0), 1)) for c in cs])
        au = RC.get("audit") or {}
        check("5.3 %s: при 130 %% нет вылезающего текста и горизонтальной прокрутки" % tag,
              au and not au.get("hscroll") and not au.get("outside"), au)
        probs = stage.page_problems(RC)
        check("5.4 %s: ошибок консоли нет" % tag, not probs, probs)
    stage.stop()

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    for f in _fail:
        print("   - " + f)
sys.exit(1 if _fail else 0)
