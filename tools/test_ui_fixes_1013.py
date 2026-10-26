# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Окно: исправления проверки интерфейса 13.10.2026 — на настоящих web/index.html и app.js (стенд).

  U1. отказ принтера на «Пауза»/«Стоп»/«Продолжить» раньше пропадал молча — теперь сообщение;
  U2. пульт UI3: после «Изменить принтер → Отмена» кнопки пульта молча переставали работать;
  U3. кнопка «Печать» в карточке была доступна у принтера на паузе (сервер теперь и сам отказывает);
  U6. вызывалась несуществующая toast() — подтверждения не появлялись (проверка по исходнику);
  U5. вызывалась несуществующая fetchPrinters() после «Адрес обновлён».

Стенд статический: сервер, база и принтеры не участвуют, ответы /api синтетические.
Запуск: python tools/test_ui_fixes_1013.py   (0 = пройдено)
"""
import os
import re
import sys

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as st  # noqa: E402

fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""), flush=True)
    if not ok:
        fails.append(name)


APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
print("--- исходник ---")
check("U6. вызовов несуществующей toast() нет (подтверждения идут через pushToast)",
      not re.search(r"(?<![A-Za-z_.])toast\(", APPJS) and "const pushToast" in APPJS)
check("U5. несуществующая fetchPrinters() не вызывается (после «Адрес обновлён» — fetchStateMatrix)",
      "fetchPrinters(" not in APPJS and "const fetchStateMatrix" in APPJS)

PRINTERS = [
    #  FlashForge без модели и без камеры: значок «модель не задана» открывает «Изменить принтер»,
    #  а камера на синтетическом стенде не мешает чистоте консоли.
    {"id": "k1", "name": "Klipper 01", "type": "flashforge", "model": "", "ip": "10.0.0.41", "port": 8898},
    {"id": "k2", "name": "Klipper 02", "type": "klipper", "model": "Voron 2.4 300", "ip": "10.0.0.42", "port": 7125},
]
LIVE = {
    "k1": {"status": "PAUSED", "status_raw": "paused", "percent": 40, "file_name": "part", "nozzle_count": 1,
           "nozzle_temp": 200, "bed_temp": 60, "hms": []},
    "k2": {"status": "IDLE", "status_raw": "standby", "percent": 0, "nozzle_count": 1, "nozzle_temp": 25, "bed_temp": 25, "hms": []},
}

if not st.engine_ready():
    print("SKIP — нет браузерного движка или Node")
    sys.exit(0)
st.set_live(LIVE)
st.set_api({"/api/printers": PRINTERS, "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
            "/api/printer/k1/cmd": {"status": "error", "reason": "command_not_confirmed"}})

print("--- карточки 2.0 ---")
JS20 = r"""
return new Promise(function(res){ setTimeout(function(){
  function btn(name){ return [...document.querySelectorAll('[data-tour-mark="ctl-print"]')].find(function(b){
      var c = b.closest('.printer-card'); return c && (c.innerText||'').indexOf(name) >= 0; }); }
  var a = btn('Klipper 01'), b = btn('Klipper 02');
  dump({found: !!a && !!b, pausedDisabled: a ? !!a.disabled : null, idleDisabled: b ? !!b.disabled : null});
  res(true);
}, 3500); });
"""
r = st.run(JS20, window_size=(1440, 900), settle_ms=1500, path="/?ui=2&ls=farm_lang:ru")
if r is None:
    check("U3. стенд 2.0 поднялся", False, st.last_diag())
else:
    check("U3. принтер на паузе — «Печать» в карточке недоступна; свободный — доступна",
          r.get("found") and r.get("pausedDisabled") is True and r.get("idleDisabled") is False, r)
    check("U3а. консоль чистая (2.0)", not st.page_problems(r), st.page_problems(r)[:2])

print("--- пульт UI3 ---")
JS3 = r"""
return new Promise(function(res){
  window.__calls = [];
  var of = window.fetch;
  window.fetch = function(u, o){ try { window.__calls.push([String(u), (o && o.method) || 'GET']); } catch (e) {} return of.apply(this, arguments); };
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function card(name){ return [...document.querySelectorAll('.printer-card')].find(function(e){
      return (e.innerText||'').indexOf(name) >= 0; }); }
  (async function(){
    await sleep(3000);
    var out = {};
    var c = card('Klipper 01'); if (c) c.click(); await sleep(1200);
    out.pauseBefore = !!document.querySelector('[data-help="pp-resume"], [data-help="pp-pause"]');
    var warn = c && c.querySelector('.pc-nomodel, .pc-row-warn');
    out.warnFound = !!warn;
    if (warn) { warn.click(); await sleep(1200); }
    var cancel = [...document.querySelectorAll('button')].find(function(b){ return b.offsetParent && /^(Отмена|Cancel)$/.test((b.innerText||'').trim()); });
    out.cancelFound = !!cancel;
    if (cancel) { cancel.click(); await sleep(900); }
    var btn = document.querySelector('[data-help="pp-resume"]') || document.querySelector('[data-help="pp-pause"]');
    out.panelBtn = btn ? btn.getAttribute('data-help') : '';
    window.__calls = [];
    if (btn) { btn.click(); await sleep(1500); }
    out.calls = window.__calls.filter(function(x){ return x[0].indexOf('/cmd') >= 0; });
    //  2.0 показывает всплывающее сообщение, UI3 — строку в панели сообщений: ищем по всей странице.
    var _all = (document.body.innerText || '').replace(/\s+/g, ' ');
    var _k = _all.indexOf('не выполнено');
    out.toast = _k >= 0 ? _all.slice(Math.max(0, _k - 40), _k + 160) : '';
    dump(out); res(true);
  })();
});
"""
r = st.run(JS3, window_size=(1440, 900), settle_ms=1500, path="/ui3?ls=farm_lang:ru")
if r is None:
    check("U2. стенд UI3 поднялся", False, st.last_diag())
else:
    check("U2. пульт UI3: после «Изменить принтер → Отмена» кнопка пульта по-прежнему шлёт команду своему принтеру",
          r.get("warnFound") and r.get("cancelFound") and r.get("panelBtn")
          and any(c[0].endswith("/api/printer/k1/cmd") and c[1] == "POST" for c in (r.get("calls") or [])), r)
    check("U1. принтер не подтвердил команду — владелец видит сообщение «не выполнено», а не тишину",
          "не выполнено" in (r.get("toast") or "") and "не подтвердил" in (r.get("toast") or ""), r.get("toast"))
    check("U1а. консоль чистая (UI3)", not st.page_problems(r), st.page_problems(r)[:2])

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (len(names) - len(fails), len(fails)))
for f in fails:
    print("  FAIL:", f)
sys.exit(1 if fails else 0)
