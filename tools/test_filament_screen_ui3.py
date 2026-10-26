# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.965 — экран «Филамент» и предупреждение «скоро кончится» (R-047, R-018).

ЗАЧЕМ. Владелец просил одну таблицу на всю ферму: где какая катушка и что кончается. Здесь
легко ошибиться молча: показать граммы там, где катушка со складом не связана (тогда число
выдумано), потерять слот принтера, который сейчас офлайн, или завалить «Подсказки» одним и
тем же предупреждением каждые десять секунд опроса.

Проверяется ИСПОЛНЕНИЕМ: настоящий браузер, стенд отдаёт слоты по вебсокету и склад по
своему адресу, порог сохраняется на сервер.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_filament_screen_ui3.py
"""
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "FILAMENT_SCREEN_UI3_SENTINEL_2_965"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "ui3", "ui3.css"), encoding="utf-8").read()
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()

print("--- 1. устройство закреплено в файлах ---")
check("1. вкладка «Филамент» стоит рядом с «Проекты», «Задачи» и «Очередь»",
      "setUi3RightTab('filament')" in IDX and "'Филамент':'Filament'" in IDX
      and "k !== 'filament'" in APPJS and "ui3-right-filament" in APPJS)
check("2. экран НИЧЕГО не меняет: ни печати, ни склада, ни привязок",
      bool(re.search(r'<section v-if="ui3Mode && ui3RightTab === .filament.', IDX)))
_sec = IDX.split('class="ui3-fil w-full min-w-0"', 1)[1].split("</section>", 1)[0]
check("2a. в разделе нет ни одной команды печати и ни одной записи",
      not any(k in _sec for k in ("sendCmd", "start_print", "method: 'POST'", "queueAdd", "deleteStagingFile")))
check("3. новых обращений к принтерам нет: слоты из телеметрии, граммы из склада",
      "const _ui3FilSlots" in APPJS and "wsData.value && wsData.value[pid]" in APPJS
      and "printerFilament.value[pid]" in APPJS
      and "fetch('/api/printer-filament'" in io.open(os.path.join(ROOT, "web", "composables", "usePrinterFilament.js"), encoding="utf-8").read())
check("4. порог — общая настройка фермы, а не запись в браузере",
      '_FARM_SETTINGS_KEYS = ("stagger_on", "stagger_sec", "low_pct", "queue_auto_start", "update_check")' in SRV
      and "low_pct: String(ui3FilLowPct.value)" in APPJS
      and "if ('low_pct' in st) _ui3FilLowSet(st.low_pct, false);" in APPJS)
check("5. предупреждение уходит в «Подсказки» и повторяться не может",
      "_ui3FilWarned" in APPJS and "if (_ui3FilWarned.has(s.spoolKey)) continue;" in APPJS
      and "if (!s.low) { _ui3FilWarned.delete(s.spoolKey); continue; }" in APPJS
      and "pushToast(" in APPJS.split("const _ui3FilCheckLow", 1)[1][:1400])
_rules = [l for l in re.sub(r"/\*.*?\*/", "", CSS, flags=re.S).splitlines() if ".ui3-fil" in l]
check("6. каждое правило экрана в ui3.css начинается с html.ui3-mode",
      _rules and all(l.startswith("html.ui3-mode") or l.startswith("  html.ui3-mode") for l in _rules),
      [l[:60] for l in _rules if not (l.startswith("html.ui3-mode") or l.startswith("  html.ui3-mode"))][:3])

print("--- 2. исполнение: две марки, склад, порог, предупреждение ---")
PR = [{"id": "b1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_B1", "access_code": ""},
      {"id": "k1", "name": "K2-01", "type": "klipper", "model": "Creality K2 Plus",
       "ip": "10.0.0.71", "port": 7125, "serial": "FIXTURE_K1", "access_code": ""}]
FIL = {"printers": {
    "b1": {"has_ams": True, "slots": [
        {"index": 0, "unit": 0, "tray": 0, "external": False, "offline": False,
         "spool": {"id": "s1", "vendor_name": "Bambu", "material": "PETG", "color_name": "чёрный",
                   "color_hex": "#1f2937", "weight_remaining_g": 620, "weight_total_g": 1000}},
        {"index": 1, "unit": 0, "tray": 1, "external": False, "offline": False,
         "spool": {"id": "s2", "vendor_name": "eSUN", "material": "PLA", "color_name": "красный",
                   "color_hex": "#ef4444", "weight_remaining_g": 90, "weight_total_g": 1000}}]},
    "k1": {"has_ams": True, "slots": [
        {"index": 0, "unit": 0, "tray": 0, "external": False, "offline": False,
         "spool": {"id": "s3", "vendor_name": "Creality", "material": "PLA", "color_name": "белый",
                   "color_hex": "#f5f5f5", "weight_remaining_g": 300, "weight_total_g": 1000}}]}}}
LIVE = {"b1": {"status": "RUNNING", "percent": 40, "remaining_time": 60, "nozzle_count": 1,
               "file_name": "korpus", "ams_now": 0, "ams_trays": [
                   {"index": 0, "unit": 0, "tray": 0, "type": "PETG", "color": "#1f2937"},
                   {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color": "#ef4444"},
                   {"index": 2, "unit": 0, "tray": 2, "type": "Empty", "color": ""}]},
        "k1": {"status": "IDLE", "nozzle_count": 1, "cfs_now": -1, "cfs_trays": [
                   {"index": 0, "type": "PLA", "color": "#f5f5f5"},
                   {"index": 1, "type": "ABS", "color": "#3b82f6"}]}}

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  var sent = []; var _f = window.fetch;
  window.fetch = function(u, o){ try { if (String(u).indexOf('/api/farm-settings') >= 0 && o && o.body) sent.push(JSON.parse(o.body)); } catch(e){} return _f.apply(this, arguments); };
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var out = {};
      var ft = qa('.ui3-rtabs button').filter(function(b){ return /Филамент/.test(b.textContent); })[0];
      out.tabExists = !!ft;
      if (ft) ft.click();
      setTimeout(function(){
        out.shown = vis(q('.ui3-fil'));
        out.projHidden = !vis(q('.ui3-proj'));
        out.taskHidden = !vis(q('.ui3-task'));
        out.printers = qa('.ui3-fil-pr').length;
        out.rows = qa('.ui3-fil-row').map(function(r){
          return [r.className.replace('ui3-fil-row', '').trim(),
                  (r.querySelector('.sl') || {}).textContent,
                  (r.querySelector('.mt') || {}).textContent,
                  (r.querySelector('.rm') || {}).textContent.trim()];
        });
        out.sum = (q('.ui3-fil-sum') || {}).textContent;
        out.thr = (q('.ui3-fil-th input') || {}).value;
        out.badge = (q('.ui3-rtabs-n.warn') || {}).textContent;
        out.msgs = qa('.sg-msg .sg-msg-t').map(function(m){ return m.textContent.trim(); });
        var sec = q('.ui3-fil'), over = [];
        if (sec) { var b = sec.getBoundingClientRect();
          qa('.ui3-fil *').forEach(function(e){ var r2 = e.getBoundingClientRect(); if (r2.width > 0 && r2.right > b.right + 1) over.push(e.className); }); }
        out.over = over.slice(0, 6);
        out.trunc = qa('.ui3-fil-row .sl').filter(function(e){ return e.scrollWidth > e.clientWidth + 1; })
                      .map(function(e){ return e.textContent; });
        var pane = q('.projects-pane');
        out.scrollX = pane ? pane.scrollWidth > pane.clientWidth + 1 : null;
        //  Порог поднимаем: строк «скоро кончится» должно стать больше, и он уходит на сервер.
        var inp = q('.ui3-fil-th input');
        if (inp) { inp.value = '60'; inp.dispatchEvent(new Event('change', { bubbles: true })); }
        setTimeout(function(){
          out.lowAfter = qa('.ui3-fil-row.low').length;
          out.sent = sent.slice();
          out.msgs2 = qa('.sg-msg .sg-msg-t').map(function(m){ return m.textContent.trim(); });
          res(dump(out));
        }, 1400);
      }, 1400);
    }, 1200);
  }, 1900);
});
"""

if stage.engine_ready():
    stage.set_api({"/api/printers": PR, "/api/printer-filament": FIL,
                   "/api/farm-settings": {"ok": True, "settings": {}}})
    stage.set_live(LIVE)
    R = stage.run(JS, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                  extra_args=("--force-device-scale-factor=1.0",))
    if not R:
        check("7. экран проверен исполнением", False, str(stage.last_diag())[:200])
    else:
        check("7. вкладка открывается, остальные разделы уходят",
              R.get("tabExists") is True and R.get("shown") is True
              and R.get("projHidden") is True and R.get("taskHidden") is True,
              {k: R.get(k) for k in ("tabExists", "shown", "projHidden", "taskHidden")})
        check("8. слоты обеих марок в одной таблице: AMS у Bambu, CFS у Creality",
              R.get("printers") == 2
              and [r[1] for r in (R.get("rows") or [])] == ["AMS 1·1", "AMS 1·2", "AMS 1·3", "CFS 1", "CFS 2"],
              R.get("rows"))
        _rows = {r[1]: r for r in (R.get("rows") or [])}
        check("9. у привязанной катушки — граммы и проценты",
              _rows.get("AMS 1·1", [None] * 4)[3] == "620 г · 62 %"
              and _rows.get("CFS 1", [None] * 4)[3] == "300 г · 30 %", _rows)
        check("10. у слота без привязки граммы НЕ выдумываются",
              _rows.get("CFS 2", [None] * 4)[3] == "остаток неизвестен"
              and _rows.get("CFS 2", [None] * 4)[2] == "ABS", _rows.get("CFS 2"))
        check("11. пустой слот показан пустым, а не нулём граммов",
              _rows.get("AMS 1·3", [None] * 4)[0] == "empty"
              and _rows.get("AMS 1·3", [None] * 4)[3] == "—", _rows.get("AMS 1·3"))
        check("12. ниже порога строка подсвечена; по умолчанию порог 15 %",
              _rows.get("AMS 1·2", [None] * 4)[0] == "low" and R.get("thr") == "15"
              and R.get("badge") == "1", (_rows.get("AMS 1·2"), R.get("thr"), R.get("badge")))
        check("13. сводка считает принтеры, слоты, граммы и то, что кончается",
              all(x in (R.get("sum") or "") for x in ("2", "5", "1010", "скоро кончится")), R.get("sum"))
        check("14. предупреждение пришло в «Подсказки» и названо по имени принтера и слоту",
              len([m for m in (R.get("msgs") or []) if "X1C-01" in m and "AMS 1·2" in m]) == 1,
              R.get("msgs"))
        #  Порог 60 %: PETG 62 % остаётся спокойным, PLA 9 % и PLA 30 % — подсвечены.
        check("15. поднятый порог подсвечивает больше строк и сохраняется на сервер",
              R.get("lowAfter") == 2
              and any(x.get("low_pct") == "60" for x in (R.get("sent") or [])),
              (R.get("lowAfter"), R.get("sent")))
        check("16. второе предупреждение о той же катушке не приходит",
              len([m for m in (R.get("msgs2") or []) if "AMS 1·2" in m]) == 1, R.get("msgs2"))
        check("17. ничего не вылезает за край, горизонтальной прокрутки нет",
              not R.get("over") and R.get("scrollX") is False, (R.get("over"), R.get("scrollX")))
        _d = R.get("__diag") or {}
        check("18. консоль чистая", not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:200])

    print("--- 3. исполнение: узкий экран и ферма без склада ---")
    R2 = stage.run(JS, window_size=(1280, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    if not R2:
        check("19. узкий экран проверен", False, str(stage.last_diag())[:200])
    else:
        check("19. на 1280 таблица цела и ничего не вылезает",
              R2.get("printers") == 2 and not R2.get("over") and R2.get("scrollX") is False,
              (R2.get("printers"), R2.get("over"), R2.get("scrollX")))

    stage.set_api({"/api/printers": PR, "/api/printer-filament": {"printers": {}},
                   "/api/farm-settings": {"ok": True, "settings": {"low_pct": "25"}}})
    R3 = stage.run(JS, window_size=(1900, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    print("--- 4. исполнение: H2D, две внешние катушки (16.10.2026, R-137) ---")
    #  Склад отдаёт у H2D две внешние строки: левую (ext_side 'left', позиция -2) и правую (-1).
    #  Раньше вторая затирала первую: левая катушка пропадала из таблицы вместе со своим
    #  предупреждением «скоро кончится».
    PR_H2D = [{"id": "h2", "name": "H2D-01", "type": "bambu", "model": "Bambu Lab H2D",
               "ip": "10.0.0.12", "port": 8883, "serial": "FIXTURE_H2", "access_code": ""}]
    FIL_H2D = {"printers": {"h2": {"has_ams": False, "slots": [
        {"index": -2, "unit": None, "tray": None, "external": True, "ext_side": "left", "offline": False,
         "spool": {"id": "sl", "vendor_name": "Bambu", "material": "PETG", "color_name": "зелёный",
                   "color_hex": "#22c55e", "weight_remaining_g": 50, "weight_total_g": 1000}},
        {"index": -1, "unit": None, "tray": None, "external": True, "ext_side": "right", "offline": False,
         "spool": {"id": "sr", "vendor_name": "eSUN", "material": "PLA", "color_name": "красный",
                   "color_hex": "#ef4444", "weight_remaining_g": 700, "weight_total_g": 1000}}]}}}
    stage.set_api({"/api/printers": PR_H2D, "/api/printer-filament": FIL_H2D,
                   "/api/farm-settings": {"ok": True, "settings": {}}})
    stage.set_live({"h2": {"status": "IDLE", "nozzle_count": 2, "ams_trays": []}})
    for _w, _h in ((1600, 1000), (1280, 800), (1024, 640), (853, 533)):
        R4 = stage.run(JS, window_size=(_w, _h), settle_ms=2600, path="/ui3",
                       extra_args=("--force-device-scale-factor=1.0",))
        _tag = "%dx%d" % (_w, _h)
        if not R4:
            check("23.%s H2D проверен исполнением" % _tag, False, str(stage.last_diag())[:200])
            continue
        _r4 = {r[1]: r for r in (R4.get("rows") or [])}
        check("23.%s H2D: обе внешние катушки в таблице — левая и правая, у каждой свои граммы" % _tag,
              [r[1] for r in (R4.get("rows") or [])] == ["Лев. внеш.", "Прав. внеш."]
              and _r4.get("Лев. внеш.", [None] * 4)[3] == "50 г · 5 %"
              and _r4.get("Прав. внеш.", [None] * 4)[3] == "700 г · 70 %", R4.get("rows"))
        check("24.%s H2D: левая катушка подсвечена и о ней пришло предупреждение" % _tag,
              _r4.get("Лев. внеш.", [None] * 4)[0] == "low"
              and len([m for m in (R4.get("msgs") or [])
                       if "H2D-01" in m and ("Лев. внеш." in m or "Left ext." in m)]) == 1,
              (_r4.get("Лев. внеш."), R4.get("msgs")))
        check("25.%s H2D: подписи не обрезаны, ничего не вылезает, горизонтальной прокрутки нет" % _tag,
              not R4.get("trunc") and not R4.get("over") and R4.get("scrollX") is False,
              (R4.get("trunc"), R4.get("over"), R4.get("scrollX")))
        _d = R4.get("__diag") or {}
        check("26.%s консоль чистая" % _tag,
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:200])
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R3:
        check("20. ферма без склада проверена", False, str(stage.last_diag())[:200])
    else:
        _rows3 = {r[1]: r for r in (R3.get("rows") or [])}
        check("20. без модуля склада слоты видны, а граммы честно неизвестны",
              R3.get("printers") == 2 and len(R3.get("rows") or []) == 5
              and _rows3.get("AMS 1·1", [None] * 4)[3] == "остаток неизвестен"
              and not [m for m in (R3.get("msgs") or []) if "Скоро кончится" in m],
              (R3.get("printers"), _rows3.get("AMS 1·1"), R3.get("msgs")))
        check("21. порог приходит с сервера, а не берётся из браузера",
              R3.get("thr") == "25", R3.get("thr"))
        _d = R3.get("__diag") or {}
        check("22. консоль чистая", not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:200])
else:
    print("SKIP — браузер стенда недоступен: исполнение не проверено")

print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
