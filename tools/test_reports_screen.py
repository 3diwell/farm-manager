# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.898 — экран «Отчёты и статистика».

ЗАМЫСЕЛ ПРОВЕРКИ. Отчёт — это счёт, и врать он не имеет права. Главное здесь не разметка, а
АРИФМЕТИКА и ЧЕСТНОСТЬ:

  * у печати четыре исхода, и «исход не ясен» (печать сменил новый файл) нельзя валить ни в
    успех, ни в брак — доля успеха считается без него;
  * время печати суммируется ТОЛЬКО по завершённым;
  * «модуль не установлен» и «печатей не было» — разные ответы, и показываться должны по-разному.

Всё это проверяется исполнением: функции достаются из web/app.js и считают в Node, а экран
поднимается в настоящем браузере — с журналом и без модуля.

БЕЗОПАСНОСТЬ: чтение файлов, чистые функции в Node и стенд с синтетическими ответами. Рабочая
база, принтеры и печать не затрагиваются.

Запуск:  python tools/test_reports_screen.py
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "REPORTS_SCREEN_SENTINEL_2_898"
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8", errors="replace").read()
HINTS = io.open(os.path.join(ROOT, "web", "composables", "helpHints.js"), encoding="utf-8").read()
NODE = r"C:\Program Files\nodejs\node.exe"
_node = NODE if os.path.exists(NODE) else "node"
NL = chr(10)
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


print("--- 1. счёт: настоящие функции приложения в Node ---")
_i = APPJS.find("    const showReports = ref(false);")
_j = APPJS.find(NL + "    };", APPJS.find("    const repDayHeight = (d) => {"))
BLOCK = APPJS[_i:_j + len(NL + "    };")] if (_i >= 0 and _j > _i) else ""
check("1. блок отчётов найден в приложении", bool(BLOCK.strip()) and "repStats" in BLOCK)

#  Журнал печатей: два принтера, все четыре исхода плюс одна идущая печать.
RUNS = [
    {"printer_id": "p1", "printer_name": "X1C-01", "filename": "korpus.gcode",
     "started_at": "2026-08-20 10:00:00", "elapsed_s": 3600, "outcome_raw": "finished"},
    {"printer_id": "p1", "printer_name": "X1C-01", "filename": "korpus.gcode",
     "started_at": "2026-08-20 12:00:00", "elapsed_s": 1800, "outcome_raw": "finished"},
    {"printer_id": "p1", "printer_name": "X1C-01", "filename": "korpus.gcode",
     "started_at": "2026-08-21 09:00:00", "elapsed_s": 300, "outcome_raw": "failed"},
    {"printer_id": "p2", "printer_name": "K2-02", "filename": "kryshka.gcode",
     "started_at": "2026-08-21 11:00:00", "elapsed_s": 120, "outcome_raw": "cancelled"},
    {"printer_id": "p2", "printer_name": "K2-02", "filename": "kryshka.gcode",
     "started_at": "2026-08-21 13:00:00", "elapsed_s": None, "outcome_raw": "unknown",
     "terminal_reason": "superseded_by_new_job"},
    {"printer_id": "p2", "printer_name": "K2-02", "filename": "novaya.gcode",
     "started_at": "2026-08-22 08:00:00", "elapsed_s": None, "outcome_raw": "running"},
    #  Незнакомый исход из будущей версии модуля обязан попасть в «не ясен», а не потеряться.
    {"printer_id": "p2", "printer_name": "K2-02", "filename": "novaya.gcode",
     "started_at": "2026-08-22 09:00:00", "elapsed_s": 60, "outcome_raw": "teleported"},
]
_h = NL.join([
    "const localStorage = { getItem: () => null, setItem: () => {} };",
    "const ref = (v) => ({ value: v });",
    "const computed = (fn) => ({ get value() { return fn(); } });",
    "const lang = ref('ru');",
    "const installedModules = ref([{ id: 'quality', state: 'loaded' }]);",
    "const modulesLoadState = ref('ready');",
    "const moduleIsLoaded = (m) => !m.disabled && (!m.state || m.state === 'loaded');",
    "const loadInstalledModules = async () => {};",
    "const showSettings = ref(false), showDiag = ref(false), showPrinterFiles = ref(false);",
    "const closeSettings = () => {}, closeDiagnostics = () => {}, closePrinterFiles = () => {};",
    "let fetch = async () => ({ ok: true, status: 200, json: async () => ({ runs: [] }) });",
    BLOCK.replace("    const ", "const ").replace(NL + "    ", NL),
    "const RUNS_MAIN = " + json.dumps(RUNS) + ";",
    "repRuns.value = RUNS_MAIN;",
    "const S = repStats.value;",
    "const out = {",
    "  total: S.total, finished: S.finished, failed: S.failed, cancelled: S.cancelled,",
    "  unknown: S.unknown, running: S.running, judged: S.judged, rate: S.rate, seconds: S.seconds,",
    "  printers: S.printers.map(p => ({ name: p.name, total: p.total, finished: p.finished,",
    "    failed: p.failed, cancelled: p.cancelled, unknown: p.unknown, rate: p.rate, seconds: p.seconds })),",
    "  files: S.files.map(f => ({ name: f.name, total: f.total, finished: f.finished, failed: f.failed })),",
    "  days: S.days.map(d => ({ day: d.day, total: d.total, finished: d.finished })),",
    "  dayMax: S.dayMax,",
    "  bars: S.days.map(d => repDayHeight(d)),",
    "  dur: [59, 60, 3600, 5100, 50400].map(s => repDuration(s)),",
    "  durZero: repDuration(0),",
    "  dayLabel: repDayLabel('2026-08-27'),",
    "  since7: _repSince(7), since90: _repSince(90),",
    "  nightDay: (function(){ repRuns.value = [{ printer_id: 'p1', printer_name: 'X1C-01',",
    "     filename: 'n.gcode', started_at: '2026-08-21 23:30:00', elapsed_s: 60,",
    "     outcome_raw: 'finished' }]; const d = repStats.value.days[0].day;",
    "     repRuns.value = RUNS_MAIN; return d; })(),",
    "  nightLocal: (function(){ const t = new Date(Date.parse('2026-08-21T23:30:00Z'));",
    "     const p = (n) => String(n).padStart(2, '0');",
    "     return t.getFullYear() + '-' + p(t.getMonth() + 1) + '-' + p(t.getDate()); })(),",
    "  periods: repPeriods.slice(),",
    "};",
    "setRepDays(7); out.after7 = repDays.value;",
    "setRepDays(555); out.afterJunk = repDays.value;",
    "repRuns.value = []; out.emptyRate = repStats.value.rate; out.emptyBars = repStats.value.dayMax;",
    "//  четыре состояния модуля качества",
    "out.stReady = repModuleState.value;",
    "installedModules.value = [{ id: 'quality', state: 'error' }]; out.stOff = repModuleState.value;",
    "installedModules.value = [{ id: 'quality', disabled: true }]; out.stDisabled = repModuleState.value;",
    "installedModules.value = []; modulesLoadState.value = 'unavailable'; out.stNoList = repModuleState.value;",
    "modulesLoadState.value = 'ready'; out.stNoModule = repModuleState.value;",
    "installedModules.value = [{ id: 'quality', state: 'loaded' }];",
    "//  ГОНКА: две загрузки подряд, ответ у первой приходит ПОЗЖЕ и с ошибкой.",
    "let FETCHN = 0;",
    "const sleep = (ms) => new Promise(r => setTimeout(r, ms));",
    "fetch = async (url) => {",
    "  const n = ++FETCHN;",
    "  if (n === 1) { await sleep(120); return { ok: false, status: 500, json: async () => ({}) }; }",
    "  await sleep(10);",
    "  return { ok: true, status: 200, json: async () => ({ runs: RUNS_MAIN }) };",
    "};",
    "const p1 = loadReports();",
    "const p2 = loadReports();",
    "await Promise.all([p1, p2]);",
    "await sleep(200);",
    "out.raceState = repState.value;",
    "out.raceRuns = repRuns.value.length;",
    "out.raceBusy = repBusy.value;",
    "console.log('@@' + JSON.stringify(out) + '@@');",
]) + NL
_td = tempfile.mkdtemp(prefix="fm898_")
_hp = os.path.join(_td, "h.mjs")
io.open(_hp, "w", encoding="utf-8", newline=NL).write(_h)
G = None
try:
    r = subprocess.run([_node, _hp], capture_output=True, timeout=120)
    m = re.search(r"@@(.*)@@", (r.stdout or b"").decode("utf-8", "replace"), re.S)
    G = json.loads(m.group(1)) if m else None
    if G is None:
        check("2. счёт исполнился в Node", False, ((r.stderr or b"").decode("utf-8", "replace"))[-300:])
except Exception as e:
    check("2. счёт исполнился в Node", False, str(e))
finally:
    try:
        os.remove(_hp)
        os.rmdir(_td)
    except Exception:
        pass

if G:
    check("2. счёт исполнился в Node", True)
    check("3. исходы разложены верно",
          (G["total"], G["finished"], G["failed"], G["cancelled"], G["unknown"], G["running"])
          == (7, 2, 1, 1, 2, 1),
          (G["total"], G["finished"], G["failed"], G["cancelled"], G["unknown"], G["running"]))
    check("4. незнакомый исход попадает в «не ясен», а не теряется",
          G["total"] == G["finished"] + G["failed"] + G["cancelled"] + G["unknown"] + G["running"])
    check("5. доля успеха считается БЕЗ «не ясен» и без идущих печатей",
          G["judged"] == 4 and G["rate"] == 50, (G["judged"], G["rate"]))
    check("6. время печати суммируется только по завершённым",
          G["seconds"] == 5400, G["seconds"])
    _p1 = [p for p in G["printers"] if p["name"] == "X1C-01"][0]
    _p2 = [p for p in G["printers"] if p["name"] == "K2-02"][0]
    check("7. разбивка по принтерам верна",
          (_p1["total"], _p1["finished"], _p1["failed"], _p1["seconds"], _p1["rate"]) == (3, 2, 1, 5400, 67)
          and (_p2["total"], _p2["cancelled"], _p2["unknown"], _p2["seconds"]) == (4, 1, 2, 0),
          (_p1, _p2))
    check("8. принтеры идут от самого загруженного",
          [p["name"] for p in G["printers"]] == ["K2-02", "X1C-01"], [p["name"] for p in G["printers"]])
    check("9. файлы сведены и отсортированы по числу запусков",
          [f["name"] for f in G["files"]] == ["korpus.gcode", "kryshka.gcode", "novaya.gcode"]
          and G["files"][0]["total"] == 3 and G["files"][0]["finished"] == 2,
          G["files"])
    #  Состав дней проверяется ПОИМЁННО: «их не меньше трёх» прошло бы и на сломанном коде.
    check("10. дни разложены поимённо и по возрастанию",
          [d["day"] for d in G["days"]] == ["2026-08-20", "2026-08-21", "2026-08-22"]
          and G["dayMax"] == 3, G["days"])
    #  Печать, начатая по Гринвичу в 23:30, у владельца восточнее Гринвича приходится уже на
    #  СЛЕДУЮЩИЙ день. Если местное время из кода убрать, эта проверка покраснеет.
    check("10a. день считается по местному времени владельца, а не по Гринвичу",
          G.get("nightDay") == G.get("nightLocal"), (G.get("nightDay"), G.get("nightLocal")))
    check("11. столбик самого высокого дня — самый высокий, и ни один не нулевой",
          max(G["bars"]) == 84 and min(G["bars"]) >= 4, G["bars"])
    check("12. время печати пишется словами",
          G["dur"] == ["меньше минуты", "1 мин", "1 ч 00 мин", "1 ч 25 мин", "14 ч 00 мин"],
          G["dur"])
    #  Ноль — это «завершённых печатей не было», а не «печатали меньше минуты». Разные вещи.
    check("12a. при нуле стоит прочерк, а не «меньше минуты»", G["durZero"] == "—", G["durZero"])
    check("13. подпись дня — день и месяц", G["dayLabel"] == "27.08", G["dayLabel"])
    check("14. граница периода строится в том же виде, в каком время лежит в журнале",
          bool(re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$", G["since7"] or ""))
          and G["since90"] < G["since7"], (G["since7"], G["since90"]))
    check("15. срок выбирается только из предложенных",
          G["periods"] == [7, 30, 90] and G["after7"] == 7 and G["afterJunk"] == 7,
          (G["periods"], G["after7"], G["afterJunk"]))
    check("16. пустой журнал не даёт деления на ноль",
          G["emptyRate"] == 0 and G["emptyBars"] == 0, (G["emptyRate"], G["emptyBars"]))
    check("16a. «модуль работает», «выключен», «сломан», «списка нет» и «модуля нет» — разные ответы",
          (G.get("stReady"), G.get("stOff"), G.get("stDisabled"), G.get("stNoList"), G.get("stNoModule"))
          == ("ready", "moduleoff", "moduleoff", "nolist", "nomodule"),
          (G.get("stReady"), G.get("stOff"), G.get("stDisabled"), G.get("stNoList"), G.get("stNoModule")))
    #  Поздняя ошибка отменённой загрузки НЕ имеет права стереть верные числа свежей.
    check("16b. при двух загрузках подряд применяется только последняя",
          G.get("raceState") == "" and G.get("raceRuns") == 7 and G.get("raceBusy") is False,
          (G.get("raceState"), G.get("raceRuns"), G.get("raceBusy")))

print("--- 2. разметка и честные оговорки ---")
check("17. экран отчётов есть и занимает тот же слот, что «Диагностика»",
      'v-if="showReports" class="fm-reports-workspace"' in IDX
      and ".fm-reports-workspace{" in CSS)
check("18. экран открывается плиткой в настройках",
      'openReports()' in IDX and 'Отчёты и статистика' in IDX)
check("19. «модуля нет», «модуль выключен», «список не пришёл» и «печатей не было» — четыре разных ответа",
      "repState==='nomodule'" in IDX and "repState==='moduleoff'" in IDX
      and "repState==='nolist'" in IDX and "!repStats.total" in IDX
      and "Модуль не установлен — считать не из чего" in IDX
      and "установлен, но не работает" in IDX
      and "Не удалось получить список модулей" in IDX
      and "За выбранный срок печатей не было" in IDX)
check("19a. кнопки срока не нажимаются во время загрузки",
      ':disabled="repBusy" @click="setRepDays(d)"' in IDX)
check("19b. доля успеха не заявляет 0 %, когда судить не по чему",
      "repStats.judged ? (repStats.rate + '%') : '—'" in IDX)
check("19c. строка про записи без исхода названа честно",
      "Записей без отметки о завершении" in IDX and "закончившаяся при выключенной программе" in IDX)
check("20. отдельно сказано, что «отменено» включает уход принтера в покой",
      "уход принтера в покой без доказанного завершения" in IDX)
check("21. отдельно сказано, что «исход не ясен» в долю успеха не входит",
      "В долю успеха такие не входят вовсе" in IDX)
check("22. формула доли успеха написана прямо на экране",
      "завершено ÷ (завершено + сбой + отменено)" in IDX)
check("23. сказано, что глубина ограничена днём установки модуля",
      "Глубина отчёта ограничена днём установки модуля" in IDX)
check("24. предупреждение о пределе в 2000 запусков есть",
      "repCapped" in IDX and "2000" in IDX)
#  Журнал спрашивается ровно в одном месте и только у модуля; своего маршрута отчётов
#  на сервере не заведено — иначе пришлось бы трогать права и реестр маршрутов.
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
check("25. журнал спрашивается у модуля качества и нигде больше",
      APPJS.count("fetch('/api/mod/quality/print-runs") == 1
      and "/api/reports" not in SRV)
check("26. стили экрана описаны",
      ".rep-cards{" in CSS and ".rep-tbl{" in CSS and ".rep-days{" in CSS and ".rep-foot{" in CSS)
check("27. функции отданы в шаблон",
      "showReports, openReports, closeReports," in APPJS and "repStats, repDuration," in APPJS)
check("28. подсказка объясняет, откуда берутся числа",
      '"reports"' in HINTS and "Качество печати" in HINTS)
check("29. экран закрывается клавишей Esc",
      "if (showReports.value) { closeReports(); return; }" in APPJS)

print("--- 3. вид: экран открывается в настоящем браузере ---")
MODULES = {"modules": [{"id": "quality", "ru": "Качество печати", "en": "Print quality",
                        "version": "0.2.2", "icon": "activity", "enabled": True, "state": "loaded",
                        "launchers": []}]}
STAGE_RUNS = {"runs": [dict(r, run_id="run_%d" % i) for i, r in enumerate(RUNS)]}

JS = r"""
return new Promise(function(res){
  setTimeout(function(){
    var later = byText('button', ['Позже', 'Later']);
    if (later) click(later);
    setUiLang('ru');
    setTimeout(function(){
      click(gear());
      setTimeout(function(){
        var t = byText('.fm-set-tile', ['Отчёты', 'Reports']);
        if (t) click(t);
        setTimeout(function(){
          var root = document.querySelector('.fm-reports-workspace');
          var cards = [].slice.call(document.querySelectorAll('.rep-card')).map(function(c){
            return { v: (c.querySelector('.rep-cv') || {}).textContent || '',
                     l: (c.querySelector('.rep-cl') || {}).textContent || '' }; });
          var rows = [].slice.call(document.querySelectorAll('.rep-tbl .rep-tr:not(.rep-th)'));
          var bars = [].slice.call(document.querySelectorAll('.rep-day-bar')).map(function(b){
            return Math.round(b.getBoundingClientRect().height); });
          var over = [].slice.call(document.querySelectorAll('.rep-tr>span')).filter(function(s){
            return s.scrollWidth - s.clientWidth > 1 && !s.classList.contains('rep-name'); });
          //  R-051: вычисленный вид — им сверяются оформления 2.0 и 3.0.
          function cs(el){ return el ? getComputedStyle(el) : null; }
          var pb = cs(document.querySelector('.rep-pbtn.is-on')), per = cs(document.querySelector('.rep-period'));
          var rc = cs(root), card = cs(document.querySelector('.rep-card'));
          var probe = document.createElement('i'); document.body.appendChild(probe);
          probe.style.color = 'var(--fm-surface-card)'; var cardTok = getComputedStyle(probe).color;
          probe.style.color = 'var(--fm-accent)'; var accTok = getComputedStyle(probe).color; probe.remove();
          var look = { ui3: document.documentElement.classList.contains('ui3-mode'),
            wsBr: rc ? rc.borderTopLeftRadius : '', wsSh: rc ? rc.boxShadow : '',
            onBg: pb ? pb.backgroundColor : '', onC: pb ? pb.color : '', onBr: pb ? pb.borderTopLeftRadius : '',
            perBr: per ? per.borderTopLeftRadius : '', cardBr: card ? card.borderTopLeftRadius : '',
            cardTok: cardTok, accTok: accTok };
          //  Контраст по WCAG с ДЕЙСТВИТЕЛЬНОЙ подложкой: полупрозрачные слои (color-mix в 3.0)
          //  складываются по предкам до первого непрозрачного фона (test_light_theme_contrast
          //  меряет только 2.0 и полупрозрачные слои пропускает).
          function col(s){
            s = s || ''; var n = (s.match(/-?[\d.]+/g) || []).map(parseFloat);
            if (/^color\(/.test(s)) return [n[0] * 255, n[1] * 255, n[2] * 255, n.length > 3 ? n[3] : 1];
            return n.length >= 3 ? [n[0], n[1], n[2], n.length > 3 ? n[3] : 1] : null; }
          function ovl(fg, bg){ var a = fg[3]; return [0, 1, 2].map(function(i){ return fg[i] * a + bg[i] * (1 - a); }).concat([1]); }
          function effBg(el){
            var layers = [], n = el;
            while (n && n.nodeType === 1) { var c = col(getComputedStyle(n).backgroundColor);
              if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } n = n.parentElement; }
            var bg = [255, 255, 255, 1];
            for (var i = layers.length - 1; i >= 0; i--) bg = ovl(layers[i], bg);
            return bg; }
          function lum(c){ var f = c.slice(0, 3).map(function(v){ v = v / 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
            return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]; }
          look.contrast = ['.rep-title', '.rep-cv', '.rep-cl', '.rep-sec-h', '.rep-name', '.rep-th', '.rep-dur',
                           '.rep-foot', '.rep-day-n', '.rep-day-l', '.rep-pbtn:not(.is-on)', '.rep-pbtn.is-on', '.rep-btn']
            .map(function(sel){ var el = document.querySelector(sel); if (!el) return { sel: sel, k: null };
              var bg = effBg(el), fg = ovl(col(getComputedStyle(el).color), bg), a = lum(fg), b = lum(bg);
              return { sel: sel, k: Math.round((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) * 100) / 100 }; });
          res(dump({
            look: look,
            open: !!root,
            empty: root ? !!root.querySelector('.rep-empty') : null,
            emptyText: root && root.querySelector('.rep-empty') ? (root.querySelector('.rep-empty').textContent || '').trim().slice(0, 60) : '',
            cards: cards, rows: rows.length, bars: bars, overflowCells: over.length,
            hscroll: root ? (root.scrollWidth - root.clientWidth) : -1,
            docScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            foot: document.querySelectorAll('.rep-foot > div').length
          }));
        }, 900);
      }, 700);
    }, 500);
  }, 1200);
});
"""

if not stage.engine_ready():
    check("30. браузерный движок доступен (без него экран проверить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    check("30. браузерный движок доступен", True)
    stage.set_api({"/api/modules": MODULES, "/api/mod/quality/print-runs": STAGE_RUNS})
    R = stage.run(JS, window_size=(1600, 1000), settle_ms=2500,
                  extra_args=("--force-device-scale-factor=1.25",))
    if not R:
        check("31. экран отчётов открылся", False, str(stage.last_diag())[:200])
    else:
        check("31. экран отчётов открылся", bool(R.get("open")), R.get("open"))
        check("32. сводка показана карточками", len(R.get("cards") or []) == 7,
              [c.get("l") for c in (R.get("cards") or [])])
        check("33. в сводке видно и число запусков, и долю успеха",
              any((c.get("v") or "").strip() == "7" for c in (R.get("cards") or []))
              and any("%" in (c.get("v") or "") for c in (R.get("cards") or [])),
              [c.get("v") for c in (R.get("cards") or [])])
        check("34. таблицы заполнены (принтеры и файлы)", (R.get("rows") or 0) >= 5, R.get("rows"))
        check("35. столбики по дням нарисованы", len(R.get("bars") or []) >= 3
              and min(R.get("bars") or [0]) > 0, R.get("bars"))
        check("36. числа в таблицах не обрезаны", (R.get("overflowCells") or 0) == 0,
              R.get("overflowCells"))
        check("37. лишней горизонтальной прокрутки нет",
              (R.get("hscroll") or 0) <= 0 and (R.get("docScroll") or 0) <= 0,
              (R.get("hscroll"), R.get("docScroll")))
        check("38. честные оговорки показаны на экране", (R.get("foot") or 0) >= 6, R.get("foot"))
        _d = R.get("__diag") or {}
        check("39. консоль браузера чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled"))
              and not [w for w in (_d.get("consoleWarnings") or []) if "Vue warn" in str(w)],
              json.dumps(_d, ensure_ascii=False)[:220])
        _l2 = R.get("look") or {}
        check("39a. на «/» (интерфейс 2.0) вид отчётов прежний: окно 12 px, срок — обведённые кнопки",
              _l2.get("ui3") is False and _l2.get("wsBr") == "12px" and _l2.get("onBr") == "8px"
              and _l2.get("onC") == _l2.get("accTok"), _l2)

    #  Второй прогон: модуля качества НЕТ. Экран обязан сказать это словами, а не показать нули.
    stage.set_api({"/api/modules": {"modules": []}})
    R2 = stage.run(JS, window_size=(1600, 1000), settle_ms=2500,
                   extra_args=("--force-device-scale-factor=1.0",))
    if not R2:
        check("40. без модуля экран всё равно открывается", False, str(stage.last_diag())[:200])
    else:
        check("40. без модуля экран всё равно открывается", bool(R2.get("open")), R2.get("open"))
        check("41. без модуля сказано ПРО МОДУЛЬ, а не «печатей не было»",
              bool(R2.get("empty")) and "модул" in (R2.get("emptyText") or "").lower(),
              R2.get("emptyText"))
        check("42. без модуля не показывается ни одной цифры сводки",
              not (R2.get("cards") or []) and not (R2.get("rows") or 0),
              (len(R2.get("cards") or []), R2.get("rows")))
    #  ── УЗКОЕ ОКНО. Приложение держит раскладку на 960 своих точек: на ноутбуке 1366 при
    #  125 % и на 1920 при 150 % слот под таблицу оказывается уже суммы её колонок. Раньше имя
    #  принтера схлопывалось в ноль, а последний столбец срезался — и прокрутки не было.
    NARROW_JS = r"""
return new Promise(function(res){
  setTimeout(function(){
    var later = byText('button', ['Позже', 'Later']); if (later) click(later);
    setUiLang('ru');
    setTimeout(function(){
      click(gear());
      setTimeout(function(){
        var t = byText('.fm-set-tile', ['Отчёты', 'Reports']);
        if (t) click(t);
        setTimeout(function(){
          var names = [].slice.call(document.querySelectorAll('.rep-name')).map(function(n){
            var r = n.getBoundingClientRect();
            return { w: Math.round(r.width), clip: n.scrollWidth - n.clientWidth,
                     text: (n.textContent || '').trim().slice(0, 20) };
          });
          var scrolls = [].slice.call(document.querySelectorAll('.rep-scroll')).map(function(sc){
            var tbl = sc.querySelector('.rep-tbl');
            var tr = sc.querySelector('.rep-tr');
            var last = tr ? tr.lastElementChild : null;
            var lr = last ? last.getBoundingClientRect() : null;
            var br = tbl ? tbl.getBoundingClientRect() : null;
            return { canScroll: sc.scrollWidth > sc.clientWidth,
                     tblW: tbl ? Math.round(tbl.getBoundingClientRect().width) : 0,
                     lastInside: (lr && br) ? (lr.right <= br.right + 0.6) : false };
          });
          var root = document.querySelector('.fm-reports-workspace');
          res(dump({ names: names, scrolls: scrolls,
                     rootClip: root ? (root.scrollWidth - root.clientWidth) : -1,
                     docScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth }));
        }, 1100);
      }, 700);
    }, 500);
  }, 1200);
});
"""
    stage.set_api({"/api/modules": MODULES, "/api/mod/quality/print-runs": STAGE_RUNS})
    for wnd, scale in (((1280, 800), 100), ((1366, 768), 125)):
        tag = "окно %d, масштаб %d %%" % (wnd[0], scale)
        R3 = stage.run(NARROW_JS, window_size=wnd, settle_ms=2500,
                       extra_args=("--force-device-scale-factor=%.2f" % (scale / 100.0),))
        if not R3:
            check("43. экран отчётов построился на узком окне (%s)" % tag, False,
                  str(stage.last_diag())[:200])
            continue
        check("43. экран отчётов построился на узком окне (%s)" % tag, True)
        _names = R3.get("names") or []
        check("44. имя принтера видно, а не схлопнуто в ноль (%s)" % tag,
              bool(_names) and all((n.get("w") or 0) >= 40 for n in _names),
              [(n.get("text"), n.get("w")) for n in _names][:4])
        check("45. имя принтера не обрезано многоточием без нужды (%s)" % tag,
              all((n.get("clip") or 0) <= 1 for n in _names[:3]),
              [(n.get("text"), n.get("clip")) for n in _names][:3])
        _sc = R3.get("scrolls") or []
        check("46. последний столбец таблицы не срезан (%s)" % tag,
              bool(_sc) and all(x.get("lastInside") for x in _sc),
              [(x.get("tblW"), x.get("lastInside")) for x in _sc])
        check("47. лишнее уезжает прокруткой ВНУТРИ блока, а не двигает страницу (%s)" % tag,
              (R3.get("docScroll") or 0) <= 0 and (R3.get("rootClip") or 0) <= 0,
              (R3.get("docScroll"), R3.get("rootClip")))

    #  ── R-051: тот же экран в интерфейсе 3.0 (/ui3), тёмная и светлая темы. Вид — как у
    #  остальных экранов 3.0: скругление панели 18 px, срок — сегментный переключатель с
    #  выбранной светлой капсулой (не акцентной обводкой). Счёт, таблицы и отсутствие лишней
    #  прокрутки — те же требования, что на «/».
    for _path, _tag in (("/ui3", "3.0, тёмная"), ("/ui3?ls=farm_theme:light", "3.0, светлая")):
        stage.set_api({"/api/modules": MODULES, "/api/mod/quality/print-runs": STAGE_RUNS})
        R4 = stage.run(JS, window_size=(1600, 1000), settle_ms=2500, path=_path)
        if not R4:
            check("48. экран отчётов открылся (%s)" % _tag, False, str(stage.last_diag())[:200])
            continue
        _l = R4.get("look") or {}
        check("48. экран отчётов открылся (%s)" % _tag, bool(R4.get("open")) and _l.get("ui3") is True,
              (R4.get("open"), _l.get("ui3")))
        check("49. окно отчётов скруглено как панели 3.0 (18 px) и с тенью (%s)" % _tag,
              _l.get("wsBr") == "18px" and "inset" in (_l.get("wsSh") or ""), (_l.get("wsBr"), _l.get("wsSh")))
        check("50. срок — сегментный переключатель: капсула-дорожка и светлая выбранная часть (%s)" % _tag,
              _l.get("perBr") == "999px" and _l.get("onBr") == "999px" and _l.get("onBg") == _l.get("cardTok")
              and _l.get("onC") != _l.get("accTok"), _l)
        check("51. карточки-числа скруглены как карточки 3.0 (14 px) (%s)" % _tag, _l.get("cardBr") == "14px",
              _l.get("cardBr"))
        check("52. сводка, таблицы и столбики на месте (%s)" % _tag,
              len(R4.get("cards") or []) == 7 and (R4.get("rows") or 0) >= 5 and len(R4.get("bars") or []) >= 3,
              (len(R4.get("cards") or []), R4.get("rows"), R4.get("bars")))
        check("53. числа не обрезаны и лишней прокрутки нет (%s)" % _tag,
              (R4.get("overflowCells") or 0) == 0 and (R4.get("hscroll") or 0) <= 0 and (R4.get("docScroll") or 0) <= 0,
              (R4.get("overflowCells"), R4.get("hscroll"), R4.get("docScroll")))
        #  Порог как в test_light_theme_contrast: 3.0 — «видно» для главного, 2.5 — для подписей.
        _main = (".rep-title", ".rep-cv", ".rep-sec-h", ".rep-name", ".rep-pbtn.is-on")
        _k = _l.get("contrast") or []
        _low = [(c["sel"], c["k"]) for c in _k
                if c.get("k") is None or c["k"] < (3.0 if c["sel"] in _main else 2.5)]
        check("53a. тексты отчёта читаются на своей подложке, контраст ≥ 3 / ≥ 2,5 (%s)" % _tag,
              len(_k) == 13 and not _low, _low or _k)
        print("      (контраст: %s)" % ", ".join("%s %s" % (c["sel"], c["k"]) for c in _k))
        _p4 = stage.page_problems(R4)
        check("54. консоль браузера чистая (%s)" % _tag, not _p4, _p4[:3])
    stage.set_api(None)
    stage.stop()

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
