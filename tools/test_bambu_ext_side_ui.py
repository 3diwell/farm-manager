# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.10.2026 (R-137, R-115) — окно запуска и очередь: внешняя катушка двухсопельного Bambu (H2D).

ЗАЧЕМ. У H2D две внешние катушки: левая (Bambu 254) подаёт только в левое сопло, правая (255) — только
в правое. Какую взять, решает файл — под какое сопло он нарезан (Bambu Studio, SelectMachine.cpp), —
а не оператор. Окно запуска обязано это сказать и показать материал обеих катушек; очередь — назвать
новые причины («файл нарезан под другое сопло», «в файле не видно сопла», «только ручной запуск»)
словами, а не кодами.

КАК ПРОВЕРЯЕТСЯ. Целиком окно запуска на синтетическом стенде не открыть: Vue в web/vendor —
производственная сборка и setupState наружу не отдаёт. Поэтому из НАСТОЯЩЕГО web/index.html берётся
блок «Источник филамента» окна запуска, а из НАСТОЯЩЕГО web/app.js — функции его подписей и подписи
очереди; блок монтируется настоящим Vue внутри приложения на стенде (tools/_fm_ui_stage.py) шириной
окна запуска (440 px минус поля) на четырёх размерах окна. Сверяется: тексты, ничего не вылезает и не
обрезано (в том числе подпись выбранного пункта списка), консоль чистая.

Запуск: python tools/test_bambu_ext_side_ui.py   (0 = все проверки пройдены)
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (str(detail)[:2500],)) if detail else ""))


def js_const(name):
    """Исходник `const name = …;` из app.js — до следующего объявления того же уровня."""
    m = re.search(r"\n    const " + re.escape(name) + r" = ", APPJS)
    if not m:
        return ""
    i = m.start() + 1
    j = re.search(r"\n    (?:const |let |function |//|return \{)", APPJS[m.end():])
    return APPJS[i:m.end() + (j.start() if j else 0)]


def html_block(start):
    """Элемент разметки целиком, начиная с подстроки start (по балансу <div>)."""
    i = HTML.find(start)
    if i < 0:
        return ""
    depth, j = 0, i
    while j < len(HTML):
        if HTML.startswith("<div", j):
            depth += 1
        elif HTML.startswith("</div>", j):
            depth -= 1
            if depth == 0:
                return HTML[i:j + len("</div>")]
        j += 1
    return ""


FNS = ["_extTrayMat", "printExtLabel", "printExtNote", "feedSlotLabel", "queueVerdictText", "queueHaveText",
       "queueReasonText", "queueExtSide", "queueUnverifiedText"]
SRCS = {n: js_const(n) for n in FNS}
check("1. функции подписей найдены в настоящем web/app.js", all(SRCS.values()),
      [n for n, v in SRCS.items() if not v])
check("2. окно запуска отдаёт в разметку обе функции подписей внешней катушки",
      re.search(r"printStart, printExtLabel, printExtNote,", APPJS) is not None)
BLOCK = html_block('<div v-if="printStart.caps && printStart.caps.bambu"')
check("3. блок «Источник филамента» окна запуска найден в настоящем web/index.html",
      "printExtLabel(printStart)" in BLOCK and "printExtNote(printStart)" in BLOCK, BLOCK[:200])

#  Состояние окна: как его собирает openPrintStart (srcOptions — настоящим _printSrcOptions).
SRC_OPTS = js_const("_printSrcOptions")
LIVE = {"h2d": {"nozzle_count": 2, "ext_trays": {"254": {"tray_type": "PLA"}, "255": {"tray_type": "PETG-CF"}},
                "ams_trays": [{"index": 0, "unit": 0, "tray": 0, "type": "PLA"}]},
        "p1s": {"nozzle_count": 1, "ext_trays": {"255": {"tray_type": "PETG"}}, "ams_trays": []}}

_JS = r"""
return new Promise(function(res){
  (async function(){
    var out = {cases: []};
    try {
      var V = await import('/vendor/vue.esm-browser.js');
      var lang = V.ref('ru');
      var wsData = V.ref(__LIVE__);
      __FNS__
      __SRCOPTS__
      function mkState(pid, hasAms, dual, src){
        var trays = (wsData.value[pid] || {}).ams_trays || [];
        return { open: true, printerId: pid, printerName: 'H2D-01', ptype: 'bambu', model: '', label: 'part.gcode.3mf',
                 caps: {bambu: true, klipper: false, fields: ['timelapse', 'bed_leveling', 'flow_cal']},
                 opts: {timelapse: false, bed_leveling: true, flow_cal: false}, src: src, hasAms: hasAms, dual: dual,
                 srcOptions: hasAms ? _printSrcOptions(trays, dual) : [], c1: false, cfsTrays: [], cfsSlot: 'file' };
      }
      var cases = [['h2d', false, true, 'external'], ['h2d', true, true, -1], ['p1s', false, false, 'external'],
                   ['p1s', true, false, -1]];
      for (var k = 0; k < cases.length; k++) {
        var c = cases[k];
        var host = document.createElement('div');
        host.style.cssText = 'position:fixed;left:20px;top:20px;width:400px;z-index:99999;background:var(--fm-surface-card)';
        document.body.appendChild(host);
        var app = V.createApp({ data: function(){ return { lang: lang.value, printStart: mkState(c[0], c[1], c[2], c[3]) }; },
                                methods: { printExtLabel: printExtLabel, printExtNote: printExtNote },
                                template: __TPL__ });
        app.mount(host);
        await new Promise(function(r){ setTimeout(r, 250); });
        var box = host.getBoundingClientRect(), kids = [].slice.call(host.querySelectorAll('*'));
        var sel = host.querySelector('[data-help="pso-src"]');
        var selText = '', selFits = true;
        if (sel) {
          var o = sel.options[sel.selectedIndex]; selText = o ? o.textContent.trim() : '';
          var cs = getComputedStyle(sel), cv = document.createElement('canvas').getContext('2d');
          cv.font = cs.fontWeight + ' ' + cs.fontSize + ' ' + cs.fontFamily;
          var need = cv.measureText(selText).width + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + 18;
          selFits = need <= sel.getBoundingClientRect().width + 0.5;
        }
        var fixed = host.querySelector('[data-help="pso-ext"]'), note = host.querySelector('[data-help="pso-ext-note"]');
        //  подпись «Источник филамента» и значение справа — в одну строку (перенос в узком окне — дефект вида)
        var row = (fixed || sel) ? (fixed || sel).parentElement : null, lab = row ? row.firstElementChild : null;
        function lines(el){ if (!el) return 0; var r = document.createRange(); r.selectNodeContents(el);
          var tops = {}; [].slice.call(r.getClientRects()).forEach(function(x){ if (x.width > 0) tops[Math.round(x.top)] = 1; });
          return Object.keys(tops).length; }
        var oneLine = lines(lab) === 1 && (!fixed || lines(fixed) === 1);
        //  где значение относительно подписи: в той же строке или под ней (у двухсопельного — под ней)
        var val = fixed || sel, lr = lab ? lab.getBoundingClientRect() : null, vr = val ? val.getBoundingClientRect() : null;
        var below = !!(lr && vr && vr.top >= lr.bottom - 1), sameRow = !!(lr && vr && vr.top < lr.bottom && vr.bottom > lr.top);
        out.cases.push({ pid: c[0], hasAms: c[1],
          fixed: fixed ? fixed.textContent.trim() : null, note: note ? note.textContent.trim() : null,
          sel: selText, selFits: selFits, oneLine: oneLine, below: below, sameRow: sameRow,
          options: sel ? [].slice.call(sel.options).map(function(x){ return x.textContent.trim(); }) : [],
          overflow: kids.filter(function(e){ var r = e.getBoundingClientRect();
              return r.width > 0 && (r.right > box.right + 1 || r.left < box.left - 1); }).length,
          clipped: kids.filter(function(e){ return e.tagName !== 'SELECT' && e.scrollWidth > e.clientWidth + 2; }).length,
          hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 });
        app.unmount(); host.remove();
      }
      out.labels = { m2: feedSlotLabel(-2), m1dual: feedSlotLabel(-1, 'h2d'), m1single: feedSlotLabel(-1, 'p1s'),
                     m1none: feedSlotLabel(-1), s0: feedSlotLabel(0) };
      out.verdicts = { wl: queueVerdictText({verdict: 'ext_wrong_side', ext_side: 'left'}),
                       wr: queueVerdictText({verdict: 'ext_wrong_side', ext_side: 'right'}),
                       su: queueVerdictText({verdict: 'ext_side_unknown'}),
                       du: queueVerdictText({verdict: 'dual_nozzle_unverified'}),
                       ls: queueVerdictText({verdict: 'left_spool'}),
                       have2: queueHaveText({dual: true, have: [{where: 'ext', material: 'PETG'}, {where: 'ext_left', material: 'PLA'}]}),
                       have1: queueHaveText({dual: false, have: [{where: 'ext', material: 'PETG'}]}),
                       reason: queueReasonText('dual_nozzle_unverified'),
                       side254: queueExtSide({match_ext: 254}, true), side255: queueExtSide({match_ext: 255}, true),
                       sideNone: queueExtSide({}, true), unv: queueUnverifiedText(),
                       wsAms: queueVerdictText({verdict: 'working_stage', stage: 255, busy_ru: 'меняет филамент в AMS',
                                                busy_en: 'is changing filament in the AMS'}),
                       ws255: queueVerdictText({verdict: 'working_stage', stage: 255}),
                       wsM1: queueVerdictText({verdict: 'working_stage', stage: -1}),
                       wsNull: queueVerdictText({verdict: 'working_stage', stage: null}),
                       ws13: queueVerdictText({verdict: 'working_stage', stage: 13}) };
      lang.value = 'en';
      out.en = { label: printExtLabel({dual: true}), m2: feedSlotLabel(-2),
                 wl: queueVerdictText({verdict: 'ext_wrong_side', ext_side: 'left'}),
                 note: printExtNote({dual: true, printerId: 'h2d'}),
                 wsAms: queueVerdictText({verdict: 'working_stage', stage: 255, busy_ru: 'меняет филамент в AMS',
                                          busy_en: 'is changing filament in the AMS'}),
                 ws255: queueVerdictText({verdict: 'working_stage', stage: 255}) };
    } catch (e) { out.error = String(e && e.stack || e); }
    res(dump(out));
  })();
});
"""
_JS = (_JS.replace("__LIVE__", json.dumps(LIVE, ensure_ascii=False))
          .replace("__FNS__", "\n".join(SRCS[n] for n in FNS))
          .replace("__SRCOPTS__", SRC_OPTS)
          .replace("__TPL__", json.dumps(BLOCK, ensure_ascii=False)))

if not (all(SRCS.values()) and BLOCK and SRC_OPTS):
    check("4. стенд: исходники собраны", False, "нет исходников для монтирования")
elif not stage.engine_ready():
    check("4. браузерный движок доступен", False, str(stage.last_diag())[:200])
else:
    bad = []
    first = None
    for w, h in ((1600, 1000), (1280, 800), (1024, 640), (853, 533)):
        U = stage.run(_JS, window_size=(w, h), settle_ms=2200)
        probs = stage.page_problems(U)
        cs = (U or {}).get("cases") or []
        lay = [c for c in cs if c.get("overflow") or c.get("clipped") or not c.get("selFits") or c.get("hscroll")
               or not c.get("oneLine")]
        if not U or U.get("error") or probs or lay or len(cs) != 4:
            bad.append((w, h, (U or {}).get("error"), probs, lay))
        if first is None and U and not U.get("error"):
            first = U
    check("4. на четырёх размерах окна (1600×1000, 1280×800, 1024×640, 853×533): ничего не вылезает, "
          "не обрезано (в том числе выбранный пункт списка), горизонтальной прокрутки нет, консоль чистая",
          not bad, bad)
    U = first or {}
    cs = {(c["pid"], c["hasAms"]): c for c in (U.get("cases") or [])}
    h_fixed, h_sel = cs.get(("h2d", False)) or {}, cs.get(("h2d", True)) or {}
    p_fixed, p_sel = cs.get(("p1s", False)) or {}, cs.get(("p1s", True)) or {}
    check("5. H2D без AMS: источник «Внешняя катушка (сторона — по соплу в файле)», под ним — правило (сторона — по "
          "соплу, под которое нарезан файл) и материалы обеих катушек (левая PLA, правая PETG-CF)",
          h_fixed.get("fixed") == "Внешняя катушка (сторона — по соплу в файле)"
          and "под чьё сопло нарезан файл" in (h_fixed.get("note") or "")
          and "левая: PLA" in (h_fixed.get("note") or "") and "правая: PETG-CF" in (h_fixed.get("note") or ""), h_fixed)
    check("6. H2D с AMS, выбран пункт внешней катушки: «Внешняя катушка (сторона — по соплу в файле)» целиком (поле "
          "выбора не обрезает его — проверка 4), под списком — правило и материалы обеих катушек",
          "Внешняя катушка (сторона — по соплу в файле)" in (h_sel.get("options") or [])
          and h_sel.get("sel") == "Внешняя катушка (сторона — по соплу в файле)"
          and "под чьё сопло нарезан файл" in (h_sel.get("note") or "")
          and "левая: PLA" in (h_sel.get("note") or ""), h_sel)
    check("7. односопельный P1S — без изменений: «Внешняя катушка», без строки о сторонах; при AMS — "
          "пояснение «только если плита печатает один материал»",
          p_fixed.get("fixed") == "Внешняя катушка" and p_fixed.get("note") is None
          and "Внешняя катушка" in (p_sel.get("options") or []) and "один материал" in (p_sel.get("note") or ""),
          (p_fixed, p_sel))
    check("7b. раскладка строки: у H2D длинное значение стоит ПОД подписью «Источник филамента» (не обрезано и не "
          "ломает подпись); у P1S значение, как прежде, в одной строке с подписью",
          h_fixed.get("below") and h_sel.get("below") and p_fixed.get("sameRow") and p_sel.get("sameRow"),
          [(c.get("pid"), c.get("hasAms"), c.get("below"), c.get("sameRow")) for c in (U.get("cases") or [])])
    L, Q, E = U.get("labels") or {}, U.get("verdicts") or {}, U.get("en") or {}
    check("8. подписи позиции: -2 — «Левая внешняя катушка»; у H2D -1 — «Правая внешняя катушка»; у P1S и без "
          "принтера -1 — «Внешняя катушка»; слоты AMS прежние",
          L.get("m2") == "Левая внешняя катушка" and L.get("m1dual") == "Правая внешняя катушка"
          and L.get("m1single") == "Внешняя катушка" and L.get("m1none") == "Внешняя катушка" and L.get("s0") == "AMS 1·1", L)
    check("9. очередь называет причины словами: другое сопло (с названной стороной), сопла в файле нет, "
          "только ручной запуск; прежний текст «left_spool» сохранён на один выпуск",
          "левой внешней катушке" in (Q.get("wl") or "") and "правое сопло" in (Q.get("wl") or "")
          and "правой внешней катушке" in (Q.get("wr") or "") and "левое сопло" in (Q.get("wr") or "")
          and "не видно, каким соплом" in (Q.get("su") or "") and "ручной запуск" in (Q.get("du") or "")
          and "левой внешней" in (Q.get("ls") or "")
          and not any(k in json.dumps(Q, ensure_ascii=False) for k in ("ext_wrong_side", "dual_nozzle_unverified",
                                                                       "ext_side_unknown")), Q)
    check("10. что лежит на принтере: у H2D внешняя 255 — «правая внешняя», 254 — «левая внешняя»; у P1S — «внешняя»",
          Q.get("have2") == "правая внешняя PETG, левая внешняя PLA" and Q.get("have1") == "внешняя PETG", Q)
    check("11. строка очереди: сторона внешней катушки в пояснении; предупреждение для ручного запуска двухсопельного",
          Q.get("side254") == "левой " and Q.get("side255") == "правой " and Q.get("sideNone") == ""
          and "автозапуск" in (Q.get("unv") or "") and "вручную" in (Q.get("reason") or ""), Q)
    check("12. английский интерфейс — те же смыслы по-английски",
          (E.get("label") or "") == "External spool (side by the nozzle in the file)" and E.get("m2") == "Left external spool"
          and "left external spool" in (E.get("wl") or "") and "left: PLA" in (E.get("note") or ""), E)

    #  16.10.2026 (проверка пакета R-138): «выполняет подготовку (стадия 255)» при смене филамента в AMS называл
    #  не ту причину. Теперь строка берёт причину у сервера (busy_ru/busy_en), а номер стадии покоя не пишет.
    check("13. очередь, принтер занят: причина словами сервера («меняет филамент в AMS»); без неё — «выполняет "
          "подготовку» без «(стадия 255)»/«(стадия -1)»; настоящая стадия — с номером; по-английски так же",
          Q.get("wsAms") == "меняет филамент в AMS" and Q.get("ws255") == "выполняет подготовку"
          and Q.get("wsM1") == "выполняет подготовку" and Q.get("wsNull") == "выполняет подготовку"
          and Q.get("ws13") == "выполняет подготовку (стадия 13)"
          and E.get("wsAms") == "is changing filament in the AMS" and E.get("ws255") == "is running a preparation step",
          (Q, E))

print()
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
