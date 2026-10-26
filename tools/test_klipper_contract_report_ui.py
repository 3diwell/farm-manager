# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.839 — клиентский интерфейс сбора отчёта: одна кнопка и честные состояния.
#
#  ЗАЧЕМ. Владелец принтера не программист: у него нет Python, терминала и адреса
#  принтера. Весь его сценарий — открыть принтер, нажать кнопку, дождаться, сохранить
#  файл. Этот тест доказывает, что так оно и есть и что ни одно состояние не врёт.
#
#  ЧЕМ ПРОВЕРЯЕТСЯ
#   * статические инварианты разметки и app.js;
#   * ИСПОЛНЕНИЕ логики состояний НАСТОЯЩИМ вендорным Vue в Node (fetch замокан);
#   * реальный браузер (Edge/CDP): приложение с новой разметкой поднимается без
#     единой ошибки консоли и без предупреждений Vue.
#
#  БЕЗОПАСНОСТЬ: сети нет, принтеров нет, server.py не импортируется, рабочие данные
#  не открываются. Ни одного обращения к настоящему принтеру.
#
#  Запуск:  python tools/test_klipper_contract_report_ui.py    (0 = всё пройдено)
# ============================================================================
import io
import json
import os
import re
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

SENTINEL = "KLIPPER_CONTRACT_REPORT_SENTINEL_2_839"

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" | " + str(extra)[:240]) if extra else ""))
    return ok


def section(t):
    print("\n--- %s ---" % t)


APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()

# Alpha 2.867: блок диагностики ПЕРЕЕХАЛ из окна запуска печати в собственное окно, которое
# открывается значком на ячейке принтера. Режем разметку этого окна.
_KI = HTML.find('v-if="klDiag.open"')
_KL = HTML[_KI:_KI + 14000] if _KI > 0 else ""
# Разметка компактной плитки сетки: значка диагностики там быть не должно.
_GSI = HTML.find('class="grid-summary')
# Разметка окна запуска печати — чтобы доказать, что блока там больше НЕТ.
_PSI = HTML.find('v-if="printStart.open"')
_PSE = HTML.find('</div></transition></teleport>', _PSI) if _PSI > 0 else 0
_PS = HTML[_PSI:_PSE] if _PSE > _PSI > 0 else ""

print("=== Alpha 2.839: клиентский интерфейс отчёта Klipper ===")
print("МЕТКА ОСНАСТКИ: %s" % SENTINEL)

# ════════════════════════════════════════════════════════════════════════════
section("A. Кнопка и тексты (RU/EN), видимость по адаптеру")

check("A1. блок диагностики живёт в окне диагностики принтера", 'data-help="kl-report"' in _KL)
check("A2. заголовок блока RU/EN",
      "'Диагностика подготовки печати':'Print preparation diagnostics'" in _KL)
check("A3. описание обещает ТОЛЬКО чтение (RU)",
      "Команды движения, калибровки и печати отправлены не будут." in _KL)
check("A4. описание обещает ТОЛЬКО чтение (EN)",
      "No movement, calibration or printing commands will be sent." in _KL)
check("A5. кнопка сбора RU/EN",
      "'Собрать диагностический отчёт':'Collect diagnostic report'" in _KL)
check("A6. кнопка сохранения RU/EN", "'Сохранить отчёт':'Save report'" in _KL)
check("A7. кнопка копирования RU/EN", "'Копировать сводку':'Copy summary'" in _KL)
check("A8. инструкция «передайте файл разработчику» RU/EN",
      "Передайте сохранённый JSON-файл разработчику Farm Manager." in _KL
      and "Send the saved JSON file to the Farm Manager developer." in _KL)
check("A9. кнопка «Повторить» есть у всех отказов", "'Повторить':'Retry'" in _KL)
check("A10. блок ушёл из окна запуска печати и существует ровно один раз",
      HTML.count('data-help="kl-report"') == 1
      and _PS and 'data-help="kl-report"' not in _PS
      and 'klRep' not in _PS)
check("A10b. значок диагностики есть в раскрытой карточке принтера и только у Klipper",
      HTML.count('@click.stop="openKlipperDiag(p)"') == 1
      and HTML.count('v-if="printerCapabilities(p).klipper" class="pc-diag') == 1)
# Плитка кончается там, где начинается teleport с раскрытой карточкой.
check("A10c. в компактной плитке сетки значка НЕТ: он уводил имя принтера на вторую строку",
      _GSI > 0 and 'pc-diag' not in HTML[_GSI:HTML.find('<teleport', _GSI)])
check("A11. повторное нажатие заблокировано во время сбора",
      ':disabled="klRepBusy"' in _KL and _KL.count(':disabled="klRepBusy"') == 2)
check("A12. клиенту не показывают ни адрес, ни токен, ни тело конфигурации",
      not re.search(r"(?i)(\bIP\b|\btoken\b|api[_-]?key|printer\.cfg|адрес принтера|"
                    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", _KL))

for phase, ru, en in (("idle", "Готов к проверке", "Ready to check"),
                      ("reading", "Чтение конфигурации принтера…", "Reading printer configuration…"),
                      ("analyzing", "Анализ макросов…", "Analysing macros…"),
                      ("checking", "Проверка безопасности отчёта…", "Checking report safety…"),
                      ("ready", "Отчёт готов", "Report ready"),
                      ("partial", "Отчёт готов частично", "Report ready (partial)"),
                      ("unreachable", "Принтер недоступен", "Printer unreachable"),
                      ("config_failed", "Не удалось прочитать конфигурацию",
                       "Could not read the configuration"),
                      ("blocked", "Отчёт заблокирован проверкой безопасности",
                       "Report blocked by the safety check")):
    check("A13. состояние «%s» названо на RU и EN" % phase, ru in APPJS and en in APPJS)

check("A14. имена состояний экспортированы в шаблон",
      all(n in APPJS for n in ("klRep,", "klRepPhaseText,", "klRepBusy,", "klRepDone,",
                               "klRepSummaryLines,", "collectKlipperReport,",
                               "saveKlipperReport,", "copyKlipperSummary,")))
check("A15. интерфейс не передаёт серверу ни адрес, ни endpoint — только printer_id в пути",
      "'/api/printer/' + encodeURIComponent(pid) + '/klipper-contract-report'" in APPJS
      and ("'/klipper-contract-report',\n                { method: 'POST', headers: "
           "{ 'Content-Type': 'application/json' }, body: '{}' });") in APPJS)
check("A16. сохранение идёт без обращения к серверу (файл на сервере не создаётся)",
      "new Blob([JSON.stringify(st.report" in APPJS and "a.download = st.filename" in APPJS)
check("A18. окно диагностики открывается только для Klipper (проверка в коде, не только в разметке)",
      "if (!p || !printerCapabilities(p).klipper) return;" in APPJS)
check("A19. принтер для отчёта берётся из окна диагностики, а не из окна запуска печати",
      "const pid = klDiag.value.printerId;" in APPJS and "printStart.value.printerId;" not in
      APPJS[APPJS.find("const collectKlipperReport"):APPJS.find("const saveKlipperReport")])
check("A20. имена окна диагностики экспортированы в шаблон",
      all(n in APPJS for n in ("klDiag,", "openKlipperDiag,", "closeKlipperDiag,")))
check("A17. неизвестная схема отчёта не выдаётся за годную",
      "'3diwell-klipper-contract-report-v1'" in APPJS and "bad_schema" in APPJS)

# ════════════════════════════════════════════════════════════════════════════
section("B. ИСПОЛНЕНИЕ состояний настоящим Vue (Node, fetch замокан)")

_i = APPJS.find("const klRep = ref(")
_j = APPJS.find("const copyKlipperSummary")
_j = APPJS.find("};", _j) + 2
BLOCK = APPJS[_i:_j] if (_i > 0 and _j > _i) else ""
check("B0. блок логики отчёта извлечён из app.js дословно", len(BLOCK) > 1500, len(BLOCK))

HARNESS = r"""
import { pathToFileURL } from 'url';
const Vue = await import(pathToFileURL(process.argv[2]).href);
const { ref, computed } = Vue;
const lang = ref('ru');
const printerCapabilities = (p) => ({ klipper: String((p && p.type) || '').toLowerCase() === 'klipper' });
const toasts = [];
const toast = (t) => toasts.push(String(t));
const pushToast = (t) => toasts.push(String(t));   // 13.10.2026: окно зовёт pushToast (toast в app.js не было)
const saved = [];
globalThis.document = {
  createElement: () => ({ href: '', download: '', click() { saved.push(this.download); }, remove() {} }),
  body: { appendChild() {}, removeChild() {} },
};
globalThis.Blob = class { constructor(p) { this.parts = p; } };
globalThis.URL = { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} };
// В Node 24 globalThis.navigator доступен ТОЛЬКО на чтение — присваивание падает.
Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true,
  value: { clipboard: { writeText: async (t) => { globalThis.__copied = t; } } } });
let MODE = 'ok', CALLS = [];
const OKREP = { report_schema_version: '3diwell-klipper-contract-report-v1', sections: {} };
globalThis.fetch = async (u, o) => {
  CALLS.push({ url: String(u), method: (o && o.method) || 'GET', body: (o && o.body) || null });
  if (MODE === 'net') throw new Error('network down');
  const mk = (st, j) => ({ ok: st === 200, status: st, json: async () => j });
  if (MODE === 'unreachable') return mk(503, { status: 'error', reason: 'unreachable' });
  if (MODE === 'blocked') return mk(500, { status: 'error', reason: 'report_redaction_failed' });
  if (MODE === 'badschema') return mk(200, { status: 'ok', report: { report_schema_version: 'x' }, summary: {}, filename: 'a.json' });
  if (MODE === 'partial') return mk(200, { status: 'ok', report: OKREP, summary: { unresolved_count: 2 }, filename: 'p.json', partial: true });
  return mk(200, { status: 'ok', report: OKREP, summary: { klipper_version: 'v0.12.0', bed_mesh_overridden: true, start_macro: 'START_PRINT', start_macro_params: ['BED_TEMP'], unresolved_count: 1 }, filename: 'r.json', partial: false });
};
__BLOCK__
// Принтер задаётся ровно так, как это делает карточка: через openKlipperDiag.
openKlipperDiag({ id: 'pK2', name: 'K2 Plus', model: 'Creality K2 Plus', type: 'klipper' });
const openedFor = klDiag.value.printerId;
openKlipperDiag({ id: 'pB1', name: 'X1C', model: 'Bambu Lab X1 Carbon', type: 'bambu' });
const afterBambu = klDiag.value.printerId;
const out = { phases: {}, calls: {}, saved: [], copied: '', summary: '', openedFor, afterBambu };
async function run(mode, key) { MODE = mode; CALLS = []; await collectKlipperReport(); out.phases[key] = klRep.value.phase; out.calls[key] = CALLS.length; }
await run('ok', 'ok');
out.summary = klRepSummaryLines.value;
saveKlipperReport(); out.saved = saved.slice();
await copyKlipperSummary(); out.copied = String(globalThis.__copied || '');
out.postBody = null;
await run('partial', 'partial');
await run('unreachable', 'unreachable');
await run('blocked', 'blocked');
await run('badschema', 'badschema');
await run('net', 'net');
MODE = 'ok'; CALLS = [];
const p1 = collectKlipperReport(); const p2 = collectKlipperReport();
await p1; await p2; out.doubleClickCalls = CALLS.length;
lang.value = 'en'; MODE = 'ok'; await collectKlipperReport();
out.enSummary = klRepSummaryLines.value; out.enPhase = klRepPhaseText();
lang.value = 'ru'; out.ruPhase = klRepPhaseText();
MODE = 'ok'; CALLS = []; await collectKlipperReport();
out.lastCall = CALLS[0] || null;
console.log('@@RES@@' + JSON.stringify(out) + '@@END@@');
"""

NODE = r"C:\Program Files\nodejs\node.exe"
res = None
if BLOCK:
    td = tempfile.mkdtemp(prefix="fm839_")
    hp = os.path.join(td, "h.mjs")
    io.open(hp, "w", encoding="utf-8", newline="\n").write(HARNESS.replace("__BLOCK__", BLOCK))
    node = NODE if os.path.exists(NODE) else "node"
    try:
        r = subprocess.run([node, hp, os.path.join(REPO, "web", "vendor", "vue.esm-browser.js")],
                           cwd=REPO, capture_output=True, timeout=180)
        out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
        m = re.search(r"@@RES@@(\{.*\})@@END@@", out, re.S)
        res = json.loads(m.group(1)) if m else None
        if res is None:
            check("B1. сценарий состояний выполнен настоящим Vue", False, out[-300:])
    except Exception as e:
        check("B1. сценарий состояний выполнен настоящим Vue", False, str(e))
    finally:
        try:
            os.remove(hp)
            os.rmdir(td)
        except Exception:
            pass

if res:
    check("B1. сценарий состояний выполнен настоящим Vue", True)
    check("B1b. окно диагностики запомнило принтер с ячейки", res.get("openedFor") == "pK2", res.get("openedFor"))
    check("B1c. Bambu окно диагностики не открывает — принтер не подменяется",
          res.get("afterBambu") == "pK2", res.get("afterBambu"))
    check("B2. успех -> состояние «Отчёт готов»", res["phases"].get("ok") == "ready", res["phases"])
    check("B3. частичный отчёт -> отдельное состояние", res["phases"].get("partial") == "partial")
    check("B4. недоступный принтер -> unreachable", res["phases"].get("unreachable") == "unreachable")
    check("B5. блокировка самопроверкой -> blocked", res["phases"].get("blocked") == "blocked")
    check("B6. чужая схема отчёта -> config_failed", res["phases"].get("badschema") == "config_failed")
    check("B7. обрыв сети -> unreachable без исключения", res["phases"].get("net") == "unreachable")
    check("B8. каждое нажатие = РОВНО один запрос",
          all(v == 1 for v in res["calls"].values()), res["calls"])
    check("B9. двойное нажатие не создаёт второй запрос", res.get("doubleClickCalls") == 1,
          res.get("doubleClickCalls"))
    check("B10. сохранение даёт файл с именем от сервера", res["saved"] == ["r.json"], res["saved"])
    check("B11. сводка копируется в буфер и не пуста", len(res.get("copied") or "") > 20)
    check("B12. RU-сводка на русском", "Стартовый макрос" in (res.get("summary") or ""))
    check("B13. EN-сводка на английском", "Start macro" in (res.get("enSummary") or ""))
    check("B14. подпись состояния переводится", res.get("enPhase") == "Report ready"
          and res.get("ruPhase") == "Отчёт готов")
    _c = res.get("lastCall") or {}
    check("B15. запрос идёт POST на маршрут отчёта по printer_id",
          _c.get("method") == "POST" and _c.get("url", "").endswith("/pK2/klipper-contract-report"), _c)
    check("B16. тело запроса пустое: ни адреса, ни токена, ни endpoint от клиента",
          str(_c.get("body") or "{}") == "{}", _c.get("body"))

# ════════════════════════════════════════════════════════════════════════════
section("C. Шаблон и реальный браузер")

try:
    node = NODE if os.path.exists(NODE) else "node"
    _js = (
        "const fs=require('fs');const html=fs.readFileSync('web/index.html','utf8');"
        "(async()=>{globalThis.document={createElement:()=>({style:{}}),querySelector:()=>null,head:{}};"
        "let s=html.indexOf('id=\"app\"');s=html.lastIndexOf('<div',s);"
        "const oe=html.indexOf('>',s)+1;const re=/<div\\b|<\\/div>/g;re.lastIndex=oe;"
        "let m,d=1,c=-1;while((m=re.exec(html))){d+=(m[0]==='</div>')?-1:1;if(d===0){c=m.index;break;}}"
        "const V=await import('./web/vendor/vue.esm-browser.js');const cp=V.compile||V.default.compile;"
        "const r=cp(html.slice(oe,c),{decodeEntities:x=>x});console.log(typeof r);})()"
        ".catch(e=>{console.error('ERR '+e.message);process.exit(1)});")
    r = subprocess.run([node, "-e", _js], cwd=REPO, capture_output=True, timeout=180)
    check("C1. шаблон #app компилируется реальным Vue после добавления блока",
          r.returncode == 0 and b"function" in (r.stdout or b""),
          (r.stdout or b"")[-200:] + (r.stderr or b"")[-200:])
except Exception as e:
    check("C1. шаблон #app компилируется реальным Vue после добавления блока", False, str(e))

import _fm_ui_stage as stage  # noqa: E402

if not stage.engine_ready():
    check("C2. движок браузера доступен (пропуск ЗАПРЕЩЁН — это красный)", False, "Edge/Node не найдены")
else:
    JS = r"""
return new Promise(function(res){ openStage('system', function(){
  setTimeout(function(){ dump({ ok:true, app: !!document.querySelector('#app') }); res(true); }, 400);
}, 'ru'); });
"""
    r = stage.run(JS, window_size=(1440, 900), settle_ms=1500, timeout=420.0)
    if r is None:
        check("C2. приложение поднялось в реальном браузере", False, str(stage.last_diag())[:200])
    else:
        check("C2. приложение поднялось в реальном браузере", bool(r.get("app")))
        probs = stage.page_problems(r)
        check("C3. 0 ошибок консоли и 0 предупреждений Vue после добавления блока",
              not probs, "; ".join(probs[:2]))
    stage.stop()

check("C4. метка оснастки не попала в продуктовые файлы",
      SENTINEL not in APPJS and SENTINEL not in HTML)

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
