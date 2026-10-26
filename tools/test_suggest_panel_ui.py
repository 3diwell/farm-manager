# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Панель «Подсказки» = отправки и очереди (Alpha 2.948, заказ владельца 05.09.2026).
#
# ЧТО ИЗМЕНИЛОСЬ. Прежний сценарий «нажми на тип принтера — подсветятся подходящие файлы»
# удалён целиком. Плавающее окно «Отправки» в углу экрана и баннер очереди под списком
# принтеров тоже убраны: их содержимое живёт теперь в панели «Подсказки» под принтерами.
# В свёрнутом виде заголовок панели носит счётчик активных дел и мигающую точку.
#
# ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ — в настоящем браузере, на настоящей странице с подставными
# ответами сервера (принтерам ничего не отправляется):
#   1. остатков прежнего сценария нет ни в коде, ни в разметке, ни в стилях, ни в реестре;
#   2. отправки видны внутри панели: строки со стадиями, прогресс, крестик у завершённых;
#   3. очередь на запуск и очередь ожидания видны там же, с кнопками;
#   4. плавающего окна и баннера под принтерами больше нет;
#   5. свёрнутая панель показывает счётчик и точку активности;
#   6. панель видна, даже если её выключили в настройках, пока дела идут;
#   7. на четырёх размерах окна ничего не вылезает, ошибок в консоли нет.
#
# Запуск:  python tools/test_suggest_panel_ui.py      (0 = всё в порядке)
# ============================================================================
import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage                              # noqa: E402

HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
CSS = io.open(os.path.join(REPO, "web", "app.css"), encoding="utf-8").read()
SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
REG = io.open(os.path.join(REPO, "app", "route_policy_registry.py"), encoding="utf-8").read()
CELL = io.open(os.path.join(REPO, "web", "components", "projects", "ProjectCell.js"), encoding="utf-8").read()

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


print("--- 1. Прежний сценарий вырезан без остатка ---")
for name, hay, needles in (
        ("app.js", APPJS, ("typeHl", "printerTypeList", "clickType", "isJobHl", "hlProjectIds", "hlPrinterIds",
                           "plateMatchesHint", "pendingProjectJobs", "loadPendingPrintable", "pending-printable",
                           "sendPanelCollapsed")),
        ("index.html", HTML, ("pt-type", "isJobHl", "plateMatchesHint", "typeHl", "hlProjectIds", "fm-send-panel",
                              "pq-banner", "sendPanelCollapsed")),
        ("app.css", CSS, (".pt-type", ".job-hl{", ".fm-send-panel{", ".fm-send-head{")),
        ("server.py", SRV, ('@app.get("/api/projects2/pending-printable")', "def g_projects2_pending_printable")),
        ("реестр маршрутов", REG, ("pending-printable",)),
        ("ProjectCell.js", CELL, ("highlighted", "job-hl"))):
    left = [n for n in needles if n in hay]
    check("1. %s: следов нет" % name, not left, left)

print("--- 2. Разметка панели ---")
#  2.974 (заказ владельца): выключателя панели в настройках больше нет — в ней сообщения
#  программы, отправки и очередь, то есть то, без чего оператор не видит, что происходит.
#  Свернуть панель по-прежнему можно, выключить — уже нет.
check("2. панель показывается всегда, выключателя в настройках нет",
      'v-if="!isMobile && edHas(\'suggestions\')" data-tour="suggest"' in HTML
      and "set-suggestions-toggle" not in HTML
      and "showSuggestions ||" not in HTML)
check("3. в заголовке — точка активности и счётчик",
      'class="sg-dot"' in HTML and 'class="sg-count" data-help="suggest-count"' in HTML)
check("4. внутри — отправки, очередь на запуск, очередь ожидания",
      'data-help="suggest-sends"' in HTML and 'data-help="suggest-queue"' in HTML and 'data-help="suggest-wait"' in HTML)
#  2.958: к слагаемым добавились сообщения — они тоже ждут внимания владельца.
check("5. счётчик складывает сообщения, отправки, очередь запуска, текущую отправку и очередь ожидания",
      "const suggestActiveCount = computed(() => (toasts.value || []).length + (sendActiveCount.value || 0) + ((printQueue.value || []).length)" in APPJS
      and "+ (printSendingNow.value ? 1 : 0) + ((queueWait.value || []).length));" in APPJS)
check("6. очередь ожидания опрашивается и в обычном интерфейсе",
      "if ((_ppTick++ % 4) === 0) loadQueueWait();" in APPJS)
#  R-132: из списка скрываемого ушёл и раздел безопасности, поэтому проверяется сам смысл —
#  ни один режим интерфейса не прячет 'suggestions', — а не прежняя строка списка целиком.
_ed = re.search(r"const _editionRemoved = (\{[^}]*\});", APPJS)
check("7. панель доступна в любом режиме интерфейса (basic больше не прячет её)",
      _ed is not None and "basic: [" in _ed.group(1) and "'projects'" in _ed.group(1)
      and "suggestions" not in _ed.group(1))

# ── Настоящий браузер ────────────────────────────────────────────────────────────────────
SEND_JOBS = [
    {"job_id": "j1", "printer_id": "b0", "printer_name": "X1 Carbon #1", "file_name": "Куб.gcode.3mf",
     "source": "quick", "state": "uploading", "progress": 42, "bytes_sent": 42, "bytes_total": 100, "error": None, "created_at": 1},
    {"job_id": "j2", "printer_id": "b1", "printer_name": "X1 Carbon #2", "file_name": "Кронштейн.gcode.3mf",
     "source": "quick", "state": "queued", "progress": None, "bytes_sent": None, "bytes_total": None, "error": None, "created_at": 2},
    {"job_id": "j3", "printer_id": "b2", "printer_name": "K2 Plus", "file_name": "Шестерня.gcode",
     "source": "quick", "state": "failed", "progress": None, "bytes_sent": None, "bytes_total": None, "error": "start_not_confirmed", "created_at": 3},
]
PRINTERS = [{"id": "b%d" % i, "name": "X1 Carbon #%d" % (i + 1), "type": "bambu", "model": "Bambu Lab X1 Carbon",
             "ip": "10.0.0.%d" % (40 + i), "port": 8883, "serial": "FIXTURE_B%d" % i, "access_code": ""} for i in range(3)]
API = {
    "/api/printers": PRINTERS,
    "/api/send-jobs": {"jobs": SEND_JOBS, "reserved_printer_ids": ["b0", "b1"]},
    "/api/print-queue": {"queue": [{"id": "q1", "printer_id": "b2", "printer_name": "K2 Plus", "eta": 45}],
                         "sending": {"printer_name": "X1 Carbon #3"}},
    "/api/queue-wait": {"ok": True, "allowed": ["b0"], "items": [
        {"id": "w1", "gcode_file": "Корпус.gcode", "material": "PETG", "match_printer_id": "b0",
         "match_printer_name": "X1 Carbon #1", "match_reason": "ready", "match_feed": "external",
         "match_finished": True},
        {"id": "w2", "gcode_file": "Крышка.gcode", "material": "", "match_printer_id": "",
         "match_printer_name": "", "match_reason": "material_unknown", "file_why": "gcode_not_declared"}]},
}
JS = r"""
return new Promise(function(res){
  setTimeout(function(){
    var l = byText('button', ['Позже', 'Later']); if (l) click(l);
    setTimeout(function(){
      var out = {};
      var pane = document.querySelector('.suggest-pane');
      out.pane = !!pane;
      out.floating = !!document.querySelector('.fm-send-panel');
      out.banner = !!document.querySelector('.pq-banner');
      out.typeButtons = document.querySelectorAll('.pt-type').length;
      out.sendRows = pane ? pane.querySelectorAll('.fm-send-row').length : -1;
      out.stages = pane ? [].slice.call(pane.querySelectorAll('.fm-send-stage')).map(function(e){ return e.textContent.trim(); }) : [];
      out.detBar = pane ? pane.querySelectorAll('.fm-send-bar.det').length : -1;
      out.dismiss = pane ? pane.querySelectorAll('.fm-send-x').length : -1;
      out.err = pane ? [].slice.call(pane.querySelectorAll('.fm-send-err')).map(function(e){ return e.textContent.trim(); }) : [];
      out.queueRows = pane ? pane.querySelectorAll('.pq-item').length : -1;
      out.sendingNow = pane ? [].slice.call(pane.querySelectorAll('.sg-row')).some(function(e){ return /Отправка на|Sending to/.test(e.textContent); }) : false;
      out.waitRows = pane ? pane.querySelectorAll('[data-help="suggest-wait"] .sg-row').length : -1;
      out.startBtns = pane ? pane.querySelectorAll('[data-help="suggest-wait"] .sg-btn').length : -1;
      out.whyLines = pane ? [].slice.call(pane.querySelectorAll('[data-help="suggest-wait"] .sg-why i')).map(function(e){ return e.textContent.trim(); }) : [];
      out.count = pane ? (pane.querySelector('.sg-count[data-help="suggest-count"]') || {}).textContent : null;
      out.dot = pane ? !!pane.querySelector('.sg-dot') : false;
      //  свернём: заголовок должен сохранить точку и счётчик, список — спрятаться
      var head = pane ? pane.querySelector('[data-help="suggest-fold"]') : null;
      if (head) click(head);
      setTimeout(function(){
        out.collapsedRows = pane ? pane.querySelectorAll('.fm-send-row').length : -1;
        out.collapsedDot = pane ? !!pane.querySelector('.sg-dot') : false;
        out.collapsedCount = pane ? (pane.querySelector('.sg-count[data-help="suggest-count"]') || {}).textContent : null;
        var r = pane ? pane.getBoundingClientRect() : null;
        out.collapsedH = r ? Math.round(r.height) : -1;
        if (head) click(head);   // вернём, чтобы состояние в localStorage не залипло
        setTimeout(function(){
          var W = document.documentElement.clientWidth;
          var kids = pane ? [].slice.call(pane.querySelectorAll('*')) : [];
          var pr = pane ? pane.getBoundingClientRect() : {left:0,right:W};
          //  Бегунок неопределённого прогресса живёт внутри полосы с overflow:hidden и по замерам
          //  «вылезает» за её край — это не дефект, полоса его обрезает. Такие элементы не считаем.
          var over = kids.filter(function(e){ var b = e.getBoundingClientRect();
            if (e.closest('.fm-send-bar')) return false;
            return b.width > 0 && (b.right > pr.right + 1 || b.left < pr.left - 1); });
          out.overflow = over.length;
          out.overflowCls = over.slice(0, 3).map(function(e){ return String(e.className || e.tagName).slice(0, 40); });
          out.clipped = kids.filter(function(e){ return e.scrollWidth > e.clientWidth + 2 && !e.classList.contains('fm-send-pn') && !e.classList.contains('fm-send-fn') && !e.classList.contains('sg-file') && !e.classList.contains('sg-sub') && !e.classList.contains('pq-name'); }).length;
          out.docScroll = document.documentElement.scrollWidth - document.documentElement.clientWidth;
          res(dump(out));
        }, 500);
      }, 500);
    }, 1800);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("8. браузерный движок доступен", False, str(stage.last_diag())[:200])
else:
    stage.set_api(API)
    stage.set_live({"b0": {"status": "IDLE", "nozzle_temp": 30, "bed_temp": 25, "percent": 0, "remaining_time": 0, "nozzle_count": 1},
                    "b1": {"status": "IDLE", "nozzle_temp": 30, "bed_temp": 25, "percent": 0, "remaining_time": 0, "nozzle_count": 1},
                    "b2": {"status": "IDLE", "nozzle_temp": 30, "bed_temp": 25, "percent": 0, "remaining_time": 0, "nozzle_count": 1}})
    print("--- 3. Настоящий браузер ---")
    bad = []
    first = None
    for wnd in ((1920, 1080), (1600, 1000), (1366, 768), (1280, 800)):
        R = stage.run(JS, window_size=wnd, settle_ms=2800, path="/?ls=farm_show_suggest:0")
        d = (R or {}).get("__diag") or {}
        errs = (d.get("consoleErrors") or []) + (d.get("pageErrors") or [])
        ok = bool(R) and R.get("pane") and R.get("overflow") == 0 and R.get("clipped") == 0 and R.get("docScroll", 1) <= 0 and not errs
        if not ok:
            bad.append("%dx%d: pane=%s overflow=%s %s clipped=%s docScroll=%s errs=%s" % (
                wnd[0], wnd[1], (R or {}).get("pane"), (R or {}).get("overflow"), (R or {}).get("overflowCls"), (R or {}).get("clipped"),
                (R or {}).get("docScroll"), [str(e)[:120] for e in errs][:2]))
        if first is None:
            first = R
    F = first or {}
    check("8. панель подсказок на месте на всех четырёх размерах, без выхода за края и ошибок консоли",
          not bad, "; ".join(bad)[:500])
    check("9. панель показана, хотя в настройках она выключена (дела идут — прятать нельзя)", F.get("pane") is True, F)
    check("10. плавающего окна отправок и баннера под принтерами нет",
          F.get("floating") is False and F.get("banner") is False, (F.get("floating"), F.get("banner")))
    check("11. кнопок типов принтеров нет", F.get("typeButtons") == 0, F.get("typeButtons"))
    #  Язык интерфейса в сцене — браузерный (обычно английский), поэтому стадии сверяются на обоих.
    check("12. отправки внутри панели: три строки, стадии словами",
          F.get("sendRows") == 3
          and any(("Отправка" in s or "Загрузка" in s or "Sending" in s or "Upload" in s) and "42%" in s for s in F.get("stages", []))
          and any("Ожидает" in s or "Waiting" in s for s in F.get("stages", [])), F.get("stages"))
    check("13. определённый прогресс 42 % — полоса есть; крестик только у завершённой/неудачной",
          F.get("detBar") == 1 and F.get("dismiss") == 1, (F.get("detBar"), F.get("dismiss")))
    check("14. текст неудачи виден в строке словами",
          F.get("err") and ("подтвердить" in F["err"][0] or "confirm" in F["err"][0]), F.get("err"))
    check("15. очередь на запуск: строка принтера и текущая отправка",
          F.get("queueRows") == 1 and F.get("sendingNow") is True, (F.get("queueRows"), F.get("sendingNow")))
    check("16. очередь ожидания: две строки, кнопка «Запустить» только у найденного принтера",
          F.get("waitRows") == 2 and F.get("startBtns") == 1, (F.get("waitRows"), F.get("startBtns")))
    _wl = F.get("whyLines") or []
    #  Стенд этого набора открывается на английском — проверяем смысл на любом из двух языков.
    check("16b. под строками очереди — пояснения словами: внешняя катушка, проверить стол, чего не хватает в файле",
          len(_wl) == 3 and any(s in _wl[0] for s in ("внешней катушки", "external spool"))
          and any(s in _wl[1] for s in ("стол", "bed")) and any(s in _wl[2] for s in ("ячейки", "slot")), _wl)
    check("17. счётчик в заголовке = 2 активные отправки + 1 в очереди + 1 отправляется + 2 ожидают = 6",
          F.get("count") == "6" and F.get("dot") is True, (F.get("count"), F.get("dot")))
    check("18. свёрнутая панель: список спрятан, точка и счётчик остались, высота — одна строка",
          F.get("collapsedRows") == 0 and F.get("collapsedDot") is True and F.get("collapsedCount") == "6"
          and 0 < (F.get("collapsedH") or 0) < 70, (F.get("collapsedRows"), F.get("collapsedDot"), F.get("collapsedCount"), F.get("collapsedH")))
    stage.set_api(None)

print("")
print("=" * 78)
print("МЕТКА: SUGGEST_PANEL_SENTINEL_2_948")
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for n in _fail:
    print("  провалено: %s" % n)
sys.exit(1 if _fail else 0)
