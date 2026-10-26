# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.10.2026 (R-152, R-110) — у каждой подсказки при наведении есть текст на русском и английском.

ЗАЧЕМ. Подсказка показывается, только если для ключа data-help есть запись в реестре
web/composables/helpHints.js: обработчик наведения (web/app.js, _onHelpOver) молча пропускает
неизвестный ключ. До 16.10.2026 у 63 элементов оформления 3.0 (почти весь пульт принтера, окно
запуска печати, добавление принтера, филамент, настройки модулей) ключ в разметке был, а записи
не было — новичок наводил курсор и не видел ничего. Обучение в 3.0 держится на этих подсказках
(тур 2.0 выключен, R-110), поэтому полнота проверяется исполнением, а не на глаз.

Что проверяется:
  A. Каждый ключ data-help из web/index.html (обычный и :data-help со строкой) и из
     web/components/**/*.js проходит через НАСТОЯЩИЙ _helpEntry программы (node) и даёт
     непустые заголовок и текст: в русском окне — русские, в английском — английские (без
     английского варианта _helpEntry показал бы русский текст, это тоже дефект).
  B. Непустота: выдуманный ключ без записи и запись без английского варианта набор ловит.
  C. Стенд (настоящая страница, синтетические ответы): с включёнными подсказками наведение на
     раздел пульта показывает рамку с текстом из реестра на русском и на английском, рамка целиком
     в окне; консоль чистая.
  D. Предложение при первом запуске (R-110): в панели «Подсказки» карточка «Включить подсказки» /
     «Не нужно»; первая кнопка включает подсказки, обе снимают карточку и запоминают ответ
     (farm_help_offer_v1); при уже включённых подсказках или данном ответе карточки нет; карточка
     не шире панели, горизонтальной прокрутки нет.
  Записи реестра, которых нет в разметке, печатаются для сведения и проверку не краснят.

БЕЗОПАСНОСТЬ: только чтение файлов проекта и стенд на 127.0.0.1; ни принтеров, ни рабочих данных.

Запуск:  python tools/test_help_hints_coverage.py      (0 = всё в порядке)
"""
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.dont_write_bytecode = True

PASS, FAILS = [0], []


def check(name, cond, detail=""):
    if cond:
        PASS[0] += 1
        print("PASS — %s" % name)
    else:
        FAILS.append(name)
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,))[:700] if detail != "" else ""))


def read(*p):
    return io.open(os.path.join(ROOT, *p), encoding="utf-8").read()


CYR = re.compile(u"[\u0400-\u04FF]")


def markup_keys():
    """-> ({ключ: [где]}, [нарушения]) — все ключи data-help разметки ядра."""
    srcs = [("web/index.html", read("web", "index.html"))]
    for f in sorted(glob.glob(os.path.join(ROOT, "web", "components", "**", "*.js"), recursive=True)):
        srcs.append((os.path.relpath(f, ROOT).replace("\\", "/"), io.open(f, encoding="utf-8").read()))
    keys, bad = {}, []
    for name, src in srcs:
        for m in re.finditer(r'(?<![:\w-])data-help="([^"]*)"', src):
            k = m.group(1).strip()
            if not k or "{{" in k:
                bad.append("%s: пустой или вычисляемый data-help «%s»" % (name, k))
                continue
            keys.setdefault(k, []).append(name)
        #  :data-help — выражение; ключи в нём — строковые литералы (у тернарного — оба).
        for m in re.finditer(r'(?:v-bind)?:data-help="([^"]*)"', src):
            lits = re.findall(r"'([^']+)'", m.group(1))
            if not lits:
                bad.append("%s: :data-help без строкового ключа: %s" % (name, m.group(1)))
            for k in lits:
                keys.setdefault(k, []).append(name + " (:data-help)")
    return keys, bad


def resolve(keys, probes=True):
    """Прогнать ключи через настоящий _helpEntry программы. -> (dict, stderr)."""
    app_js = read("web", "app.js")
    m = re.search(r"const _helpEntry = \(key\) => \{[\s\S]*?\n    \};", app_js)
    if not m:
        return None, "в web/app.js не найден _helpEntry"
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    if not os.path.isfile(node) and not shutil.which("node"):
        return None, "node не найден"
    hints = read("web", "composables", "helpHints.js")
    hints = re.sub(r"\bexport\s+(const|default)\b", lambda x: "const" if x.group(1) == "const" else "", hints)
    probe_js = ""
    if probes:
        #  Непустота: запись без английского варианта (в реестр стенда, не в файл).
        probe_js = ("HELP_HINTS['__fm_probe_no_en__'] = { title: 'Проба', "
                    "text: 'Только русский текст подсказки для проверки набора.' };\n")
    js = (hints + "\nconst lang = {value: 'ru'};\n" + m.group(0).strip() + "\n" + probe_js
          + "const KEYS = " + json.dumps(sorted(keys)) + ";\n"
          + "const out = {};\n"
          + "for (const k of KEYS) { lang.value = 'ru'; const ru = _helpEntry(k); "
            "lang.value = 'en'; const en = _helpEntry(k); out[k] = {ru: ru, en: en}; }\n"
          + "out.__registry = Object.keys(HELP_HINTS).filter(k => k.indexOf('__fm_probe') !== 0);\n"
          + "console.log(JSON.stringify(out));\n")
    td = tempfile.mkdtemp(prefix="fm_hints_")
    try:
        jf = os.path.join(td, "hints_check.js")
        io.open(jf, "w", encoding="utf-8").write(js)
        p = subprocess.run([node, jf], capture_output=True, text=True, encoding="utf-8", timeout=60)
        try:
            return json.loads(p.stdout.strip().splitlines()[-1]), p.stderr[-400:]
        except Exception:
            return None, (p.stdout[-200:] + p.stderr[-400:])
    finally:
        shutil.rmtree(td, ignore_errors=True)


def entry_problems(key, r):
    """Нарушения одного ключа: пусто — подсказка есть на обоих языках."""
    out = []
    ru, en = (r or {}).get("ru"), (r or {}).get("en")
    if not ru:
        return ["нет записи в реестре"]
    if not (ru.get("title") or "").strip() or not (ru.get("text") or "").strip():
        out.append("пустой русский заголовок или текст")
    elif not CYR.search(ru["text"]):
        out.append("русский текст без русских букв")
    if not en or not (en.get("title") or "").strip() or not (en.get("text") or "").strip():
        out.append("пустой английский заголовок или текст")
    elif CYR.search(en["title"] + en["text"]) or en.get("text") == ru.get("text"):
        out.append("нет английского варианта (в английском окне показан русский текст)")
    return out


print("--- A. каждый ключ разметки даёт текст на обоих языках ---")
KEYS, BAD_MARKUP = markup_keys()
check("A1. разметка без пустых и вычисляемых ключей data-help", not BAD_MARKUP, BAD_MARKUP[:5])
#  Сборщик ключей должен видеть все виды записи: обычный атрибут, :data-help и компоненты.
check("A2. сборщик видит обычные ключи, :data-help и разметку компонентов (%d ключей)" % len(KEYS),
      len(KEYS) >= 150 and "pp-stop" in KEYS and "settings" in KEYS and "set-mod-cfg" in KEYS
      and "due-chip" in KEYS and any("components" in w for w in KEYS.get("due-chip", [])),
      sorted(KEYS)[:5])
RES, ERR = resolve(list(KEYS) + ["__fm_probe_missing__", "__fm_probe_no_en__"])
check("A3. реестр и _helpEntry исполнились в node", isinstance(RES, dict), ERR)
RES = RES or {}
missing = {k: entry_problems(k, RES.get(k)) for k in sorted(KEYS)}
missing = {k: v for k, v in missing.items() if v}
check("A4. у каждого из %d ключей разметки есть заголовок и текст на русском и английском" % len(KEYS),
      not missing, ["%s: %s (%s)" % (k, "; ".join(v), KEYS[k][0]) for k, v in list(missing.items())[:12]])
reg = RES.get("__registry") or []
orph = sorted(k for k in reg if k not in KEYS)
print("      сведения: записей в реестре %d, ключей в разметке %d; записи без элемента в разметке: %s"
      % (len(reg), len(KEYS), ", ".join(orph) or "нет"))

print("--- B. непустота: дыры в реестре набор ловит ---")
check("B1. ключ без записи признаётся дефектом",
      entry_problems("__fm_probe_missing__", RES.get("__fm_probe_missing__")) == ["нет записи в реестре"],
      RES.get("__fm_probe_missing__"))
check("B2. запись без английского варианта признаётся дефектом (в английском окне был бы русский текст)",
      any("английск" in x for x in entry_problems("__fm_probe_no_en__", RES.get("__fm_probe_no_en__"))),
      RES.get("__fm_probe_no_en__"))

# ─────────────────────────────────────────────────────────────────────────────────────────────
#  C/D. Стенд: настоящая страница интерфейса 3.0.
import _fm_ui_stage as stage  # noqa: E402

PR = [{"id": "c1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_C1", "access_code": ""}]
RUN = {"status": "RUNNING", "percent": 42, "remaining_time": 73, "file_name": "korpus_v3",
       "nozzle_temp": 231.2, "bed_temp": 70.1, "nozzle_target": 235, "bed_target": 70,
       "total_time": 9480, "elapsed": 5100, "nozzle_count": 1,
       "ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "#1f2937"}],
       "ams_now": 0, "parts": [{"name": "korpus", "qty": 2}]}

JS_HOVER = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function tip(){ var t = q('#helpTipEl'); if (!t) return null; var b = t.getBoundingClientRect();
    return {title: (q('#helpTipEl .help-tip-title')||{}).textContent || '', text: (q('#helpTipEl .help-tip-text')||{}).textContent || '',
            r: [b.left, b.top, b.right, b.bottom], vw: innerWidth, vh: innerHeight, op: getComputedStyle(t).opacity}; }
  function hover(key, cb){
    var el = q('.ui3-pp [data-help="' + key + '"]');
    if (!el) { cb({missing: key}); return; }
    document.body.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));   // сбросить прежнюю
    el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true, view: window}));
    setTimeout(function(){ cb(tip()); }, 900);
  }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('X1C-01') >= 0; })[0];
      if (card) card.click();
      setTimeout(function(){
        var o = {panel: !!q('.ui3-pp')};
        hover('pp-temps', function(t1){
          o.ru = t1;
          setUiLang('en');
          setTimeout(function(){
            hover('pp-stop', function(t2){ o.en = t2; res(dump(o)); });
          }, 700);
        });
      }, 1800);
    }, 900);
  }, 1900);
});
"""

JS_OFFER = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function ls(k){ try { return localStorage.getItem(k); } catch (e) { return 'ERR'; } }
  var ANSWER = %(answer)s;
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('%(lang)s');
    setTimeout(function(){
      var o = {}; var c = q('.fm-help-offer'), pane = q('.suggest-pane');
      o.card = !!c;
      if (c) {
        var cb = c.getBoundingClientRect(), pb = pane ? pane.getBoundingClientRect() : null;
        o.cardR = [cb.left, cb.top, cb.right, cb.bottom]; o.paneR = pb ? [pb.left, pb.top, pb.right, pb.bottom] : null;
        o.text = (c.textContent || '').replace(/\s+/g, ' ').trim();
        o.btns = qa('.fm-help-offer button').map(function(b){ var r = b.getBoundingClientRect();
          return {t: (b.textContent || '').trim(), r: [r.left, r.top, r.right, r.bottom], sw: b.scrollWidth, cw: b.clientWidth}; });
        o.cardOver = c.scrollWidth > c.clientWidth + 1;
      }
      o.hScroll = [document.documentElement.scrollWidth, document.documentElement.clientWidth];
      o.before = {hints: ls('farm_help_hints'), offer: ls('farm_help_offer_v1')};
      if (!c || ANSWER === null) { res(dump(o)); return; }
      var b = q(ANSWER ? '.fm-help-offer-yes' : '.fm-help-offer-no');
      if (b) b.click();
      setTimeout(function(){
        o.after = {card: !!q('.fm-help-offer'), hints: ls('farm_help_hints'), offer: ls('farm_help_offer_v1')};
        //  Подсказки действительно работают после «Включить»: наведение на шестерёнку настроек.
        var g = q('[data-help="settings"]');
        if (g) g.dispatchEvent(new MouseEvent('mouseover', {bubbles: true, view: window}));
        setTimeout(function(){ var t = q('#helpTipEl'); o.after.tip = t ? (t.textContent || '').trim().slice(0, 80) : '';
          res(dump(o)); }, 900);
      }, 600);
    }, 1400);
  }, 1900);
});
"""


def run_stage(js, size, path):
    r = stage.run(js, window_size=size, settle_ms=2600, path=path, extra_args=("--force-device-scale-factor=1.0",))
    if not r:
        r = stage.run(js, window_size=size, settle_ms=2600, path=path, extra_args=("--force-device-scale-factor=1.0",))
    return r


def tip_ok(t, want_title, want_text):
    if not t or t.get("missing"):
        return ["нет рамки подсказки: %s" % (t,)]
    bad = []
    if t.get("title") != want_title or (t.get("text") or "").strip() != want_text:
        bad.append("текст не из реестра: %r / %r" % (t.get("title"), (t.get("text") or "")[:60]))
    r = t.get("r") or [0, 0, 0, 0]
    if r[0] < -0.5 or r[1] < -0.5 or r[2] > t.get("vw", 0) + 0.5 or r[3] > t.get("vh", 0) + 0.5:
        bad.append("рамка выходит за окно: %s при окне %sx%s" % (r, t.get("vw"), t.get("vh")))
    if str(t.get("op")) != "1":
        bad.append("рамка не видна (opacity %s)" % t.get("op"))
    return bad


if not stage.engine_ready():
    check("браузер стенда доступен", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR, "/api/printer/c1/files": ["a.gcode"],
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live({"c1": RUN})
    want = RES or {}
    print("--- C. стенд: наведение показывает текст реестра на обоих языках ---")
    for size in ((1600, 1000), (853, 533)):
        r = run_stage(JS_HOVER, size, "/ui3?ls=farm_help_hints:1&ls=farm_help_offer_v1:1")
        ru_w = (want.get("pp-temps") or {}).get("ru") or {}
        en_w = (want.get("pp-stop") or {}).get("en") or {}
        b1 = ["пульт не открылся"] if not (r and r.get("panel")) else tip_ok(r.get("ru"), ru_w.get("title"), ru_w.get("text"))
        check("C1. %dx%d: наведение на «Температуры» пульта — русская подсказка из реестра, целиком в окне" % size,
              not b1, b1)
        b2 = ["пульт не открылся"] if not (r and r.get("panel")) else tip_ok(r.get("en"), en_w.get("title"), en_w.get("text"))
        check("C2. %dx%d: в английском окне наведение на «Стоп» — английская подсказка из реестра" % size,
              not b2, b2)
        probs = stage.page_problems(r)
        check("C3. %dx%d: консоль чистая" % size, not probs, probs[:3])

    print("--- D. предложение включить подсказки при первом запуске (R-110) ---")
    stage.set_live({})
    stage.set_api({"/api/printers": PR})
    #  1390×797 — окно владельца 1366×768 на стенде (рамка 24×92): здесь кнопки карточки уходили
    #  за край панели, пока она была ограничена 26 %.
    for size in ((1390, 797), (853, 533)):
        r = run_stage(JS_OFFER % {"answer": "true", "lang": "ru"}, size, "/ui3")
        bad = []
        if not (r and r.get("card")):
            bad.append("карточки нет при первом запуске: %s" % (r and {k: r.get(k) for k in ("card", "before")}))
        else:
            if "Включить подсказки" not in (r.get("text") or "") or "Не нужно" not in (r.get("text") or ""):
                bad.append("текст карточки: %s" % r.get("text"))
            cr, pr = r.get("cardR"), r.get("paneR")
            if not pr or cr[0] < pr[0] - 0.5 or cr[2] > pr[2] + 0.5:
                bad.append("карточка шире панели: %s в %s" % (cr, pr))
            #  Карточка целиком видна без прокрутки: панель в 3.0 ограничена 26 % колонки, и на
            #  окне 1366×768 кнопки уходили за её нижний край.
            if pr and cr[3] > pr[3] + 0.5:
                bad.append("карточка обрезана низом панели: %s в %s" % (cr, pr))
            for bt in r.get("btns") or []:
                if bt["r"][0] < cr[0] - 0.5 or bt["r"][2] > cr[2] + 0.5 or bt["sw"] > bt["cw"] + 1:
                    bad.append("кнопка «%s» вылезает: %s" % (bt["t"], bt["r"]))
                if pr and bt["r"][3] > pr[3] + 0.5:
                    bad.append("кнопка «%s» ниже края панели: %s" % (bt["t"], bt["r"]))
            if r.get("cardOver"):
                bad.append("у карточки горизонтальная прокрутка")
            hs = r.get("hScroll") or [0, 0]
            if hs[0] > hs[1] + 1:
                bad.append("горизонтальная прокрутка страницы %s" % hs)
            a = r.get("after") or {}
            if a.get("card") or a.get("hints") != "1" or a.get("offer") != "1":
                bad.append("после «Включить подсказки»: %s" % a)
            if not a.get("tip"):
                bad.append("после включения наведение не показало подсказку")
        check("D1. %dx%d: карточка в панели «Подсказки» целиком (не шире, кнопки не за краем); «Включить подсказки» включает их, "
              "карточка уходит, ответ запомнен" % size, not bad, bad)
        probs = stage.page_problems(r)
        check("D2. %dx%d: консоль чистая" % size, not probs, probs[:3])

    r = run_stage(JS_OFFER % {"answer": "false", "lang": "en"}, (1280, 800), "/ui3")
    a = (r or {}).get("after") or {}
    check("D3. английское окно: «No, thanks» — подсказки не включаются, карточка уходит, ответ запомнен",
          bool(r and r.get("card")) and "Turn on hints" in (r.get("text") or "")
          and not a.get("card") and a.get("hints") != "1" and a.get("offer") == "1" and not a.get("tip"),
          r and {"card": r.get("card"), "text": r.get("text"), "after": a})
    for qs, why in (("ls=farm_help_offer_v1:1", "ответ уже дан"), ("ls=farm_help_hints:1", "подсказки уже включены")):
        r = run_stage(JS_OFFER % {"answer": "null", "lang": "ru"}, (1280, 800), "/ui3?" + qs)
        check("D4. %s — карточки нет" % why, bool(r) and r.get("card") is False, r and r.get("card"))
        probs = stage.page_problems(r)
        check("D5. %s: консоль чистая" % why, not probs, probs[:3])
    stage.set_api({})
    stage.set_live({})

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS[0], len(FAILS)))
for f in FAILS:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILS else 0)
