# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""26.09.2026 — свободные шрифты интерфейса «3DIWELL Wide J» (шрифт по умолчанию) и «3DIWELL Wide P».

ЧТО ЗАЩИЩАЕТ. Прежний фирменный Sony Sketch распространять было нельзя; по решению владельца он
удалён из программы, сборки и репозитория 26.09.2026, по умолчанию стоит Wide J. Замены — изменённые
Jura и Play под SIL Open Font License 1.1 (web/design/fonts/). Интерфейс выверен под размеры прежнего
шрифта: его буквы занимали ~49 % кегля. Замена обязана занимать то же место — иначе подписи вылезут
за кнопки. Эталон — замеры прежнего шрифта, записанные ниже константами (SONY_REF), пока файл был.

  1. Файлы шрифтов и тексты их лицензий на месте; лицензии совпадают с закреплёнными в
     tools/build_ui_fonts.py.
  2. fonts.css объявляет оба семейства по существующим файлам с метриками строки 74.5/25.5/0 %
     (рисунок букв по центру строки); шрифт по умолчанию — Wide J; следов Sony Sketch нет.
  3. Настройка «Шрифт»: первый пункт — шрифт по умолчанию «3DIWELL Wide J», второй — Wide P; у обоих
     увеличение html{zoom:1.196} и шрифт на весь экран, включая шапку; сохранённый выбор 'wide-j'
     (отдельный пункт до 26.09.2026) переносится на шрифт по умолчанию.
  4. В НАСТОЯЩЕМ браузере оба шрифта загружаются, а строки текста занимают то же место, что у
     прежнего шрифта (Wide J — ровно в J_SIZE раз больше): не шире 3 % и не уже 8 %, высота заглавной
     ±1 px на 100 px, пробел ±3 %, высота строки — ровно кегль.
  5. Выбор в настройках действительно меняет шрифт страницы (переключение как у пользователя), а
     запуск с сохранённым 'wide-j' открывается шрифтом по умолчанию.
  6. При fontTools: имя «Play» (зарезервировано автором) не стало именем изменённого шрифта,
     уведомления авторов сохранены, пробел как у прежнего шрифта, буквы раздвинуты, пересборка даёт те
     же байты (для неё нужен ещё ttfautohint-py); у обычного и жирного одна запись высоты строчных.

  26.09.2026, вторая редакция (замечания владельца «Jura размытый», «буквы слишком близко»): в каждом
  файле обязана быть подгонка под пиксели (таблицы fpgm, prep, gasp) — без неё на Windows штрихи
  мылятся; пробел между словами — как у прежнего шрифта.

Запуск:  python tools/test_ui_fonts.py      (0 = всё в порядке)
"""
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import struct
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
FONTS = os.path.join(REPO, "web", "design", "fonts")
WOFF = ["3diwell-wide-j.woff2", "3diwell-wide-j-bold.woff2", "3diwell-wide-p-regular.woff2", "3diwell-wide-p-bold.woff2"]

_pass, _fail, _skip = [0], [], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:400]) if detail else ""))


def skip(name, why):
    _skip.append(name)
    print("SKIP — %s: %s" % (name, why))


def read(*p):
    return io.open(os.path.join(REPO, *p), encoding="utf-8").read()


spec = importlib.util.spec_from_file_location("fm_build_ui_fonts", os.path.join(REPO, "tools", "build_ui_fonts.py"))
BUF = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BUF)
#  Во сколько раз шрифт задуман крупнее Sony Sketch (Wide J 1.200 — на 7 %), по файлу обычного начертания.
SIZE = {f["family"]: f.get("size", 1.0) for f in BUF.FACES if f["style"] == "Regular"}
K = {"j": SIZE["3DIWELL Wide J"], "p": SIZE["3DIWELL Wide P"]}

print("=" * 78)
print("1. Файлы шрифтов и лицензии")
print("=" * 78)
for n in WOFF:
    p = os.path.join(FONTS, n)
    head = open(p, "rb").read(4) if os.path.isfile(p) else b""
    check("1.%s на месте и это WOFF2" % n, head == b"wOF2", head)
for n, src in (("OFL-Jura.txt", "Jura-OFL.txt"), ("OFL-Play.txt", "Play-OFL.txt")):
    p = os.path.join(FONTS, n)
    got = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else ""
    check("1.%s — текст лицензии авторов без изменений" % n, got == BUF.SOURCES[src][2], got)
check("1.README с происхождением и изменениями", os.path.isfile(os.path.join(FONTS, "README.md")))

#  Список таблиц WOFF2 читается без распаковки: он лежит в начале файла, до сжатых данных.
_WOFF2_KNOWN = ["cmap", "head", "hhea", "hmtx", "maxp", "name", "OS/2", "post", "cvt ", "fpgm", "glyf", "loca", "prep",
                "CFF ", "VORG", "EBDT", "EBLC", "gasp", "hdmx", "kern", "LTSH", "PCLT", "VDMX", "vhea", "vmtx", "BASE",
                "GDEF", "GPOS", "GSUB", "EBSC", "JSTF", "MATH", "CBDT", "CBLC", "COLR", "CPAL", "SVG ", "sbix", "acnt",
                "avar", "bdat", "bloc", "bsln", "cvar", "fdsc", "feat", "fmtx", "fvar", "gvar", "hsty", "just", "lcar",
                "mort", "morx", "opbd", "prop", "trak", "Zapf", "Silf", "Glat", "Gloc", "Feat", "Sill"]


def woff2_tables(path):
    data = open(path, "rb").read()
    num = struct.unpack(">H", data[12:14])[0]
    off, tags = [48], []

    def b128():
        v = 0
        for _ in range(5):
            b = data[off[0]]
            off[0] += 1
            v = (v << 7) | (b & 0x7F)
            if not b & 0x80:
                return v
        return v
    for _ in range(num):
        flags = data[off[0]]
        off[0] += 1
        if flags & 0x3F == 63:
            tag = data[off[0]:off[0] + 4].decode("latin-1")
            off[0] += 4
        else:
            tag = _WOFF2_KNOWN[flags & 0x3F]
        b128()
        xf = (flags >> 6) & 3
        if (tag in ("glyf", "loca") and xf == 0) or (tag not in ("glyf", "loca") and xf != 0):
            b128()
        tags.append(tag)
    return tags


for n in WOFF:
    p = os.path.join(FONTS, n)
    tags = woff2_tables(p) if os.path.isfile(p) else []
    check("1.%s: есть подгонка под пиксели (fpgm, prep, gasp)" % n, {"fpgm", "prep", "gasp"} <= set(tags), tags)

print("\n" + "=" * 78)
print("2. fonts.css")
print("=" * 78)
CSS = read("web", "design", "fonts.css")
SRV = read("server.py")
#  Метрики строки, под которые выверен интерфейс (были у прежнего шрифта в server.py): рисунок букв
#  стоит в середине строки. Теперь они — у каждого начертания Wide J и Wide P в fonts.css.
LINE_METRICS = ("74.5%", "25.5%", "0%")
faces = re.findall(r"@font-face\s*\{(.*?)\}", CSS, re.S)
decl = []
for f in faces:
    fam = re.search(r"font-family:\s*'([^']+)'", f)
    url = re.search(r"url\('/design/fonts/([^']+)'\)", f)
    mt = tuple(re.search(r"%s:\s*([\d.]+%%)" % k, f).group(1) if re.search(r"%s:\s*([\d.]+%%)" % k, f) else None
               for k in ("ascent-override", "descent-override", "line-gap-override"))
    decl.append((fam and fam.group(1), url and url.group(1), mt))
check("2.1 объявлены оба семейства по всем четырём файлам",
      sorted(d[1] for d in decl) == sorted(WOFF)
      and {d[0] for d in decl} == {"3DIWELL Wide J", "3DIWELL Wide P"}, decl)
check("2.2 метрики строки у всех начертаний — 74.5/25.5/0 % (буквы по центру строки)",
      all(d[2] == LINE_METRICS for d in decl), decl)
check("2.3 шрифт по умолчанию — 3DIWELL Wide J",
      re.search(r"--fm-font:\s*'3DIWELL Wide J'\s*;", CSS) is not None
      and "*{ font-family: var(--fm-font, '3DIWELL Wide J'), sans-serif !important; }" in CSS)
#  Прежний шрифт удалён целиком: ни файла, ни встраивания сервером, ни упоминаний в коде интерфейса
#  и в описании сборки (иначе он вернулся бы в программу или в выданный установщик).
_web_hits = []
for _root, _dirs, _files in os.walk(os.path.join(REPO, "web")):
    if os.sep + "vendor" in _root:
        continue
    for _n in _files:
        if _n.endswith((".html", ".js", ".css", ".json", ".svg")):
            try:
                if "sony" in io.open(os.path.join(_root, _n), encoding="utf-8").read().lower():
                    _web_hits.append(os.path.relpath(os.path.join(_root, _n), REPO))
            except UnicodeDecodeError:
                pass
check("2.4 прежнего шрифта Sony Sketch нет: ни файла, ни встраивания сервером, ни упоминаний в web/ и сборке",
      not os.path.isfile(os.path.join(REPO, "Sony_Sketch.ttf"))
      and not any(x in SRV for x in ("Sony Sketch", "Sony_Sketch", "FONT_PATH", "font_css", "{{ CSS }}"))
      and "{{ CSS }}" not in read("web", "app.css")
      and "sony" not in read("3diwell.spec").lower()
      and not _web_hits, _web_hits)

print("\n" + "=" * 78)
print("3. Настройка «Шрифт»")
print("=" * 78)
APP = read("web", "app.js")
ui = APP[APP.index("const uiFonts = ["):]
ui = ui[:ui.index("];")]
brand = re.findall(r"key:\s*'([^']+)'[^\n]*stack:\s*\"'([^']+)', sans-serif\", brand: true", ui)
check("3.1 Wide P в списке и помечен как свободная замена (с тем же увеличением, что у шрифта по умолчанию)",
      brand == [("wide-p", "3DIWELL Wide P")], brand)
check("3.1b первый пункт — шрифт по умолчанию «3DIWELL Wide J», отдельного пункта 'wide-j' нет",
      re.search(r"\{ key: 'default',\s*en: '3DIWELL Wide J',\s*ru: '3DIWELL Wide J',\s*stack: '' \}", ui) is not None
      and "'wide-j'" not in ui and ui.index("key: 'default'") < ui.index("key: 'wide-p'"), ui[:600])
ap = APP[APP.index("const applyUiFont = "):]
ap = ap[:ap.index("\n")]
check("3.2 у них то же увеличение html{zoom:1.196}, что у шрифта по умолчанию",
      "const isDefaultFont = !(f && f.stack) || !!(f && f.brand);" in ap)
check("3.3 шрифт ставится на весь экран, включая шапку",
      "(f && f.brand) ? ('* { font-family: ' + f.stack + ' !important; }')" in ap)
check("3.4 при системном шрифте шапка идёт шрифтом по умолчанию Wide J",
      "header.app-header, header.app-header * { font-family: '3DIWELL Wide J', sans-serif !important; }" in ap)
check("3.5 сохранённый выбор 'wide-j' переносится на шрифт по умолчанию",
      "if (_f === 'wide-j') { _f = 'default'; try { localStorage.setItem('ui_font', _f); } catch(e){} }" in APP)

print("\n" + "=" * 78)
print("4-5. Настоящий браузер")
print("=" * 78)
import _fm_ui_stage as stage  # noqa: E402

#  Эталон — замер прежнего шрифта Sony Sketch EF 2.0.5 (SHA-256 12257e91…2781) 26.09.2026, пока файл был,
#  тем же браузерным движком (Edge 153) и так же, как ниже меряются Wide J/P: canvas.measureText на 100 px.
#  Ширины canvas берутся из единиц шрифта и не зависят ни от html{zoom}, ни от подгонки под пиксели.
#  rows — строки SAMPLES (последняя — жирная, у прежнего шрифта жирный был синтетическим), cap — высота
#  заглавной H, space — ширина пробела между словами. Файл удалён — пересчитать эталон нельзя.
SONY_REF = {"rows": [1618.3105, 2087.4023, 3235.7422, 839.7461], "cap": 49.0, "space": 29.4922}
JS = r"""
var SAMPLES = ['Принтеры Очередь Склад Настройки', 'Печать идёт: 42% · осталось 1:37 · PLA 1.75 мм',
               'ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789', 'Остановить печать'];
function box(fam, text, weight, lh){
  var s = document.createElement('span');
  s.style.cssText = 'position:absolute;left:0;top:0;white-space:nowrap;font-size:40px;line-height:' + (lh || 'normal') + ';'
    + 'font-weight:' + (weight||400) + ';font-family:' + fam + ' !important';
  s.textContent = text; document.body.appendChild(s);
  var r = s.getBoundingClientRect(); s.remove(); return {w: r.width, h: r.height};
}
function cw(fam, text, weight){
  var c = document.createElement('canvas').getContext('2d'); c.font = (weight||400) + ' 100px ' + fam;
  return c.measureText(text).width;
}
function capH(fam){
  var c = document.createElement('canvas').getContext('2d'); c.font = '400 100px ' + fam;
  return c.measureText('H').actualBoundingBoxAscent;
}
return new Promise(function(resolve){
  var later = byText('button',['Позже','Later']); if (later) click(later);
  var jobs = [document.fonts.load('40px "3DIWELL Wide J"', 'Прив'), document.fonts.load('700 40px "3DIWELL Wide J"', 'Прив'),
              document.fonts.load('40px "3DIWELL Wide P"', 'Прив'), document.fonts.load('700 40px "3DIWELL Wide P"', 'Прив')];
  Promise.all(jobs).then(function(){
    var out = {loaded: {}, rows: {}, lh: {}, cap: {}, space: {}, zoom: {}, applied: {}};
    ['"3DIWELL Wide J"', '"3DIWELL Wide P"'].forEach(function(f){
      out.loaded[f] = document.fonts.check('40px ' + f, 'Прив') && document.fonts.check('700 40px ' + f, 'Прив'); });
    var fams = {j: '"3DIWELL Wide J"', p: '"3DIWELL Wide P"'};
    Object.keys(fams).forEach(function(k){
      out.rows[k] = SAMPLES.map(function(t, i){ return cw(fams[k], t, i === 3 ? 700 : 400); });
      //  высота строки при line-height:normal против ровно одного кегля (line-height:1)
      out.lh[k] = SAMPLES.map(function(t, i){ return [box(fams[k], t, i === 3 ? 700 : 400).h, box(fams[k], t, i === 3 ? 700 : 400, '1').h]; });
      out.cap[k] = capH(fams[k]);
      out.space[k] = cw(fams[k], 'а а') - cw(fams[k], 'аа');
    });
    // Настоящий шрифт не зависит от запасного: с моноширинным и с засечками запасным ширина одна.
    out.own = {};
    ['"3DIWELL Wide J"', '"3DIWELL Wide P"'].forEach(function(f){
      var a = box(f + ', monospace', SAMPLES[0]).w, b = box(f + ', serif', SAMPLES[0]).w;
      out.own[f] = Math.abs(a - b) / Math.max(a, b); });
    // 5. Переключение как у пользователя: открыть настройки, выбрать шрифт в списке.
    openStage('general', function(){
      var sel = document.querySelector('select[data-help="set-font"]');
      out.hasSelect = !!sel;
      out.options = sel ? [].slice.call(sel.options).map(function(o){ return o.value; }) : [];
      out.labels = sel ? [].slice.call(sel.options).map(function(o){ return (o.textContent || '').trim(); }) : [];
      var keys = ['wide-p', 'arial', 'default'], i = 0;
      (function next(){
        if (i >= keys.length) { out.saved = localStorage.getItem('ui_font'); out.problems = FM_LOG; dump(out); return resolve(true); }
        var k = keys[i++];
        if (sel) { sel.value = k; sel.dispatchEvent(new Event('change', {bubbles: true})); }
        setTimeout(function(){
          var probe = document.querySelector('.fm-set-lbl') || document.body;
          var head = document.querySelector('header.app-header *') || document.querySelector('header.app-header');
          out.applied[k] = {body: getComputedStyle(probe).fontFamily, header: head ? getComputedStyle(head).fontFamily : null,
                            zoom: document.documentElement.style.zoom, dpr: window.devicePixelRatio};
          next();
        }, 350);
      })();
    }, 'ru');
  }).catch(function(e){ dump({error: String(e && e.message || e)}); resolve(true); });
});
"""

#  Запуск с выбором, сохранённым до 26.09.2026 (отдельный пункт 'wide-j'): открывается шрифтом по умолчанию.
JS_SAVED = r"""
return new Promise(function(resolve){ setTimeout(function(){
  var probe = document.querySelector('.main-cols') || document.body;
  var head = document.querySelector('header.app-header *') || document.querySelector('header.app-header');
  dump({saved: localStorage.getItem('ui_font'), body: getComputedStyle(probe).fontFamily,
        header: head ? getComputedStyle(head).fontFamily : null, zoom: document.documentElement.style.zoom,
        dpr: window.devicePixelRatio, override: (document.getElementById('ui-font-override') || {}).textContent || ''});
  resolve(true); }, 1500); });
"""

if not stage.engine_ready():
    check("4.0 браузерный движок доступен", False, stage.last_diag())
else:
    R = stage.run(JS, window_size=(1440, 900), settle_ms=2200) or {}
    check("4.0 прогон состоялся", bool(R.get("rows")), R.get("error") or stage.last_diag())
    if R.get("rows"):
        check("4.1 оба шрифта и их жирные начертания загружаются браузером",
              R["loaded"] and all(R["loaded"].values()), R["loaded"])
        rows = R["rows"]
        own = R.get("own") or {}
        check("4.2 текст действительно рисуется новым шрифтом, а не запасным (ширина не зависит от запасного)",
              own and all(v < 0.002 for v in own.values()), own)
        for k, name in (("j", "Wide J"), ("p", "Wide P")):
            kk = K[k]
            dw = [round((a - s * kk) / (s * kk), 4) for a, s in zip(rows[k], SONY_REF["rows"])]
            #  Вылезти за кнопку может только более широкий текст — поэтому шире не больше 3 %;
            #  уже допускается до 8 % (строки с цифрами у прежнего шрифта были особенно широкими).
            check("4.3 %s: строки (к прежнему шрифту ×%.2f) не шире больше чем на 3 %% и не уже чем на 8 %%" % (name, kk),
                  all(-0.08 <= x <= 0.03 for x in dw[:3]), dw)
            check("4.4 %s: жирная строка (к прежнему шрифту ×%.2f) не шире больше чем на 6 %%" % (name, kk), dw[3] <= 0.06, dw)
            lh = R.get("lh", {}).get(k) or []
            check("4.5 %s: высота строки — ровно кегль, как была у прежнего шрифта" % name,
                  lh and all(abs(a - b) <= 0.5 for a, b in lh), lh)
            #  браузер отдаёт высоту заглавной целыми точками — одно округление даёт до 1 точки
            check("4.6 %s: высота заглавной — как у прежнего шрифта ×%.2f (±1 px на 100 px)" % (name, kk),
                  abs(R["cap"][k] - SONY_REF["cap"] * kk) <= 1.0, (R["cap"][k], SONY_REF["cap"] * kk))
            check("4.7 %s: пробел между словами — как у прежнего шрифта ×%.2f (±3 %%)" % (name, kk),
                  abs(R["space"][k] - SONY_REF["space"] * kk) <= 0.03 * SONY_REF["space"] * kk,
                  (R["space"][k], SONY_REF["space"] * kk))
        ap_ = R.get("applied") or {}
        opts = R.get("options", [])
        check("5.1 в настройках выбор шрифта: первым — шрифт по умолчанию «3DIWELL Wide J», затем Wide P; 'wide-j' отдельно нет",
              R.get("hasSelect") and opts[:2] == ["default", "wide-p"] and "wide-j" not in opts
              and (R.get("labels") or [""])[0] == "3DIWELL Wide J", (opts, R.get("labels")))
        whole = all(abs(v.get("dpr", 1) - round(v.get("dpr", 1))) <= 0.001 for v in ap_.values()) if ap_ else True
        for k, fam in (("default", "3DIWELL Wide J"), ("wide-p", "3DIWELL Wide P")):
            a = ap_.get(k) or {}
            check("5.2 выбор «%s» ставит шрифт на страницу и в шапку" % fam,
                  fam in (a.get("body") or "") and fam in (a.get("header") or ""), a)
            check("5.3 у «%s» увеличение html{zoom:1.196}" % fam,
                  (a.get("zoom") == "1.196") if whole else (a.get("zoom") == ""), a)
        a = ap_.get("arial") or {}
        check("5.4 системный шрифт — без увеличения, как раньше, шапка — шрифтом по умолчанию",
              "Arial" in (a.get("body") or "") and a.get("zoom") == "" and "3DIWELL Wide J" in (a.get("header") or ""), a)
        check("5.5 последний выбор («3DIWELL Wide J») сохранён как шрифт по умолчанию", R.get("saved") == "default", R.get("saved"))
        probs = stage.page_problems(R)
        check("5.6 ошибок консоли, исключений и предупреждений Vue нет", not probs, probs)
    RS = stage.run(JS_SAVED, window_size=(1440, 900), settle_ms=2200, path="/?ls=ui_font:wide-j") or {}
    whole = abs((RS.get("dpr") or 1) - round(RS.get("dpr") or 1)) <= 0.001
    check("5.7 запуск с сохранённым 'wide-j' — шрифт по умолчанию Wide J, выбор переписан на 'default'",
          RS.get("saved") == "default" and "3DIWELL Wide J" in (RS.get("body") or "")
          and "3DIWELL Wide J" in (RS.get("header") or "") and RS.get("override") == ""
          and ((RS.get("zoom") == "1.196") if whole else True), {k: v for k, v in RS.items() if k != "__diag"})
    probs = stage.page_problems(RS) if RS else ["прогон не состоялся: %s" % stage.last_diag()]
    check("5.8 консоль чистая при запуске с сохранённым выбором", not probs, probs)
    stage.stop()

print("\n" + "=" * 78)
print("6. Имена, уведомления, повторяемость сборки (нужен fontTools)")
print("=" * 78)
try:
    from fontTools.ttLib import TTFont  # noqa: F401
    import brotli  # noqa: F401
    HAVE_FT = True
except Exception:
    HAVE_FT = False
try:
    import ttfautohint  # noqa: F401
    HAVE_TA = True
except Exception:
    HAVE_TA = False
#  Отпечатки файлов, прошедших 6.1–6.6 и пересборку 6.3 целиком (29.09.2026: fontTools, brotli,
#  ttfautohint-py 0.6.1, закреплённые исходники). Где этих библиотек или исходников нет, набор сверяет
#  файлы с отпечатками: те же байты — те же имена, уведомления, раздвижка и повторяемость сборки.
#  Пересобрал шрифты — прогони набор с fontTools и FM_FONT_SRC и обнови отпечатки.
VERIFIED_SHA256 = {
    "3diwell-wide-j.woff2": "6c6e412498deeadaf86ce0d2d1239a5a746212bf623c4d673eeaae419ea74377",
    "3diwell-wide-j-bold.woff2": "672c9564b3b4847aaf83d2abe4f08c174b6b9cecae9959fa7b5475eb036477a9",
    "3diwell-wide-p-regular.woff2": "dc4dde71fbcaae4068bec174d2aebf0d48b96ef00ff7b3723e5a52807355f09b",
    "3diwell-wide-p-bold.woff2": "da7baf1fc377f5f2111fa928b7d3fccf4308cc4cbda7373211501fc0646e42d0",
}
PIN_DIFF = [n for n in WOFF if BUF.sha256(os.path.join(FONTS, n)) != VERIFIED_SHA256.get(n)]
PIN_HINT = "шрифты изменены после проверки: прогоните набор с fontTools, brotli и FM_FONT_SRC и обновите отпечатки"
if not HAVE_FT:
    check("6.1-6.6 (по отпечаткам, fontTools нет) файлы шрифтов те же, что прошли полную проверку",
          not PIN_DIFF, {"изменены": PIN_DIFF, "что делать": PIN_HINT} if PIN_DIFF else None)
else:
    from fontTools.ttLib import TTFont
    for n in WOFF:
        nm = TTFont(os.path.join(FONTS, n))["name"]
        names = [nm.getDebugName(i) or "" for i in (1, 4, 6, 16)]
        check("6.1 %s: имя «Play» не стало именем изменённого шрифта" % n,
              not any(re.search(r"\bPlay(type)?\b", x) for x in names), names)
        cp = nm.getDebugName(0) or ""
        check("6.2 %s: уведомление авторов сохранено" % n,
              ("Jura Project Authors" in cp) if "wide-j" in n else ("Jonas Hecksher" in cp and "Reserved Font Name" in cp), cp)
        f = TTFont(os.path.join(FONTS, n))
        upem = f["head"].unitsPerEm
        cm = f.getBestCmap()
        sp = f["hmtx"][cm[0x20]][0] / upem
        size = next(x.get("size", 1.0) for x in BUF.FACES if x["dst"] == n)
        check("6.4 %s: пробел между словами %.4f — как у Sony Sketch ×%.2f (%.4f)" % (n, sp, size, BUF.SONY_SPACE * size),
              abs(sp - BUF.SONY_SPACE * size) <= 0.002, sp)
        from fontTools.pens.boundsPen import BoundsPen
        gs = f.getGlyphSet()
        gaps = []
        for ch in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяabcdefghijklmnopqrstuvwxyz":
            pen = BoundsPen(gs)
            gs[cm[ord(ch)]].draw(pen)
            gaps.append((f["hmtx"][cm[ord(ch)]][0] - (pen.bounds[2] - pen.bounds[0])) / upem)
        rel = sum(gaps) / len(gaps) / (BUF.SONY_CAP * size)
        low = 0.18 if "bold" in n else 0.22          # до раздвижки было 0.156 (жирный) и 0.199–0.213
        check("6.5 %s: буквы раздвинуты — средний промежуток %.3f высоты заглавной (не меньше %.2f)" % (n, rel, low),
              rel >= low, rel)
    #  «Размер текста» пересчитывает кегль по записи высоты строчных (OS/2 sxHeight): если у жирного
    #  она другая, жирный текст растёт не в то число раз (26.09.2026: у Wide J было на 3 % больше).
    xh = {}
    for n in WOFF:
        f = TTFont(os.path.join(FONTS, n))
        fam = next(x["family"] for x in BUF.FACES if x["dst"] == n)
        xh.setdefault(fam, set()).add(round(f["OS/2"].sxHeight / f["head"].unitsPerEm, 4))
    check("6.6 у начертаний одной семьи одна запись высоты строчных", all(len(v) == 1 for v in xh.values()), xh)
src = os.environ.get("FM_FONT_SRC", "")
if HAVE_FT and HAVE_TA and src and not BUF.check_sources(src):
    with tempfile.TemporaryDirectory() as td:
        BUF.build(src, td)
        same = [n for n in WOFF if open(os.path.join(td, n), "rb").read() == open(os.path.join(FONTS, n), "rb").read()]
    check("6.3 пересборка из закреплённых исходников даёт те же байты", len(same) == len(WOFF), same)
else:
    check("6.3 (по отпечаткам, пересборки здесь нет) файлы совпадают с проверенной пересборкой",
          not PIN_DIFF, {"изменены": PIN_DIFF, "что делать": PIN_HINT} if PIN_DIFF else None)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d SKIP=%d" % (_pass[0], len(_fail), len(_skip)))
if _fail:
    for f in _fail:
        print("   - " + f)
sys.exit(1 if _fail else 0)
