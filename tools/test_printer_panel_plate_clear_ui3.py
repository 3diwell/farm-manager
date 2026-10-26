# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.10.2026 (R-140, R-118) — «Стол очищен» в пульте принтера 3.0 и в списке автозапуска очереди.

ЗАЧЕМ. Кнопка «Стол очищен» в пульте принтера появлялась только для печати проекта. Подтверждение
для очереди жило в строке очереди и в «Подсказках»: стоя у принтера с открытым пультом, его было не
найти, а если строки под этот принтер не было (материал другой, очередь пуста) — кнопки не было нигде,
и автозапуск на этот принтер молча не шёл. Решение: одна кнопка на принтер, откуда бы ни шла печать.
  · печать проекта — главнее: кнопка ведёт в её собственное окно подтверждения;
  · иначе — подтверждение очереди (спрашивает и шлёт {confirmed: true});
  · вариант очереди — только когда принтер ждёт подтверждения (plate_wait) И есть ради чего: закончил
    печать, на нём ждёт строка очереди или ему разрешён автозапуск. Иначе у каждого свободного
    разрешённого принтера висела бы жёлтая кнопка, которая ничего не меняет.
R-118: в списке «Запускать из очереди самому» рядом с каждым принтером, который ждёт подтверждения,
— своя кнопка «Стол очищен».

ПРОВЕРЯЕТСЯ ИСПОЛНЕНИЕМ: настоящий index.html + app.js в браузере стенда, ответы /api синтетические,
запросы перехватываются. Осмотр — на четырёх размерах окна: ничего не вылезает, прокрутки вбок нет,
консоль чистая.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети фермы, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_printer_panel_plate_clear_ui3.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "PRINTER_PANEL_PLATE_CLEAR_UI3_SENTINEL_R140"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


PR = [{"id": "c1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_C1", "access_code": ""},
      {"id": "c2", "name": "P1S-02", "type": "bambu", "model": "Bambu Lab P1S",
       "ip": "10.0.0.12", "port": 8883, "serial": "FIXTURE_SN_C2", "access_code": ""}]
IDLE = {"status": "FINISH", "percent": 100, "remaining_time": 0, "file_name": "", "nozzle_temp": 30,
        "bed_temp": 28, "nozzle_target": 0, "bed_target": 0, "nozzle_count": 1, "ams_trays": [], "ams_now": -1}
ROW = {"id": "w1", "gcode_file": "korpus.gcode.3mf", "material": "PLA", "state": "waiting", "note": "",
       "created_at": 0, "source": "quick", "part_name": "", "match_printer_id": "c2",
       "match_printer_name": "P1S-02", "match_reason": "ready", "match_feed": "ams", "match_finished": False,
       "material_source": "plate", "match_slots": []}


def api(plate_wait, items=None, auto=("c1",), runs=None):
    a = {"/api/printers": PR,
         "/api/queue-wait": {"ok": True, "allowed": ["c1", "c2"], "items": list(items or []),
                             "plate_wait": plate_wait},
         "/api/farm-settings": {"ok": True, "settings": {"queue_auto_start": "1",
                                                         "auto_start_printers": list(auto)}}}
    if runs:
        a.update(runs)
    return a


#  Сценарий: вкладка «Очередь» — замер кнопки в списке автозапуска; затем пульт X1C-01 — замер
#  кнопки в «Служебном», нажатие, окно подтверждения, «Стол очищен» в окне, перехват запроса.
JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  //  окно подтверждения закреплено (position: fixed) — offsetParent у него всегда null; видимость — по размеру
  function shown(el){ if (!el) return false; var b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0; }
  function rc(el){ if(!el) return null; var b = el.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; }
  function overOf(rootSel){ var root = q(rootSel); if (!root) return ['нет ' + rootSel]; var pr = root.getBoundingClientRect(), o = [];
    qa(rootSel + ' *').forEach(function(e){ var b = e.getBoundingClientRect();
      if (b.width > 0 && (b.right > pr.right + 1 || b.left < pr.left - 1)) o.push((e.className && e.className.baseVal === undefined ? e.className : e.tagName) + ''); });
    return o.slice(0, 6); }
  function clipped(el){ return !!el && (el.scrollWidth > el.clientWidth + 1 || el.getBoundingClientRect().right > window.innerWidth + 1); }
  var sent = []; var _f = window.fetch;
  window.fetch = function(u, o){ try { if (o && o.method === 'POST') sent.push([String(u), o.body ? JSON.parse(o.body) : null]); } catch(e){} return _f.apply(this, arguments); };
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var out = {}, t = qa('.ui3-rtabs button');
      if (t[2]) t[2].click();
      setTimeout(function(){
        var ab = qa('.ui3-q-auto-list .ui3-q-clr');
        out.autoBtns = ab.map(function(b){ var lp = b.closest('.ui3-q-auto-p'), sp = lp ? lp.querySelector('span') : null;
          return sp ? sp.textContent.trim() : ''; });
        out.autoClip = ab.filter(clipped).length;
        out.autoOver = overOf('.ui3-q-auto');
        out.autoBtnRc = rc(ab[0]);
        var de = document.scrollingElement || document.documentElement;
        out.hscrollQ = de.scrollWidth - de.clientWidth;
        var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('X1C-01') >= 0; })[0];
        if (card) card.click();
        setTimeout(function(){
          var tools = q('[data-help="pp-tools"]');
          var btn = tools ? [].slice.call(tools.querySelectorAll('.ui3-pp-btn')).filter(function(b){ return /Стол очищен/.test(b.textContent); })[0] : null;
          out.ppBtn = !!btn && vis(btn);
          out.ppTitle = btn ? btn.getAttribute('title') : null;
          out.ppNote = !!(tools && tools.querySelector('.ui3-pp-note'));
          out.ppClip = clipped(btn);
          out.ppOver = overOf('.ui3-pp');
          out.ppRc = rc(btn);
          var de2 = document.scrollingElement || document.documentElement;
          out.hscrollP = de2.scrollWidth - de2.clientWidth;
          if (btn) btn.click();
          setTimeout(function(){
            var ask = q('.fm-ask-back');
            out.ask = shown(ask);
            out.askText = ask ? ask.textContent.replace(/\s+/g, ' ').trim() : '';
            out.sentBeforeOk = sent.length;
            var ok = q('.fm-ask-ok'); if (ok) ok.click();
            setTimeout(function(){
              out.sent = sent.slice();
              out.toasts = qa('[class*="toast"]').map(function(x){ return x.textContent.replace(/\s+/g, ' ').trim(); }).filter(Boolean).slice(0, 4);
              res(dump(out));
            }, 900);
          }, 700);
        }, 1600);
      }, 900);
    }, 1000);
  }, 1900);
});
"""

#  Короткий сценарий: открыть пульт X1C-01, посмотреть «Служебное» и нажать кнопку, если она есть.
JS_SHORT = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function vis(el){ return !!el && el.offsetParent !== null; }
  //  окно подтверждения закреплено (position: fixed) — offsetParent у него всегда null; видимость — по размеру
  function shown(el){ if (!el) return false; var b = el.getBoundingClientRect(); return b.width > 0 && b.height > 0; }
  var sent = []; var _f = window.fetch;
  window.fetch = function(u, o){ try { if (o && o.method === 'POST') sent.push([String(u), o.body ? JSON.parse(o.body) : null]); } catch(e){} return _f.apply(this, arguments); };
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var out = {};
      var card = qa('[data-pid]').filter(function(c){ return c.textContent.indexOf('X1C-01') >= 0; })[0];
      if (card) card.click();
      setTimeout(function(){
        var tools = q('[data-help="pp-tools"]');
        var btn = tools ? [].slice.call(tools.querySelectorAll('.ui3-pp-btn')).filter(function(b){ return /Стол очищен/.test(b.textContent); })[0] : null;
        out.ppBtn = !!btn && vis(btn);
        out.ppTitle = btn ? btn.getAttribute('title') : null;
        out.ppNote = !!(tools && tools.querySelector('.ui3-pp-note'));
        if (btn) btn.click();
        setTimeout(function(){
          out.ask = shown(q('.fm-ask-back'));
          out.sent = sent.filter(function(s){ return s[0].indexOf('plate-clear') >= 0; });
          res(dump(out));
        }, 800);
      }, 1600);
    }, 1000);
  }, 1900);
});
"""

SIZES = ((1600, 1000), (1280, 800), (1024, 640), (853, 533))


def run(js, **kw):
    """Прогон на стенде с одним повтором, если мост браузера не вернул результата (на занятой машине
    16.10.2026 такое бывало и без дефекта страницы: тот же сценарий отдельно проходил за секунды).
    Повтор — только при ПУСТОМ ответе моста; результат проверок не подменяется."""
    for _try in range(2):
        r = stage.run(js, timeout=240, **kw)
        if r:
            return r
        print("      (стенд не ответил, повтор: %s)" % str(stage.last_diag())[:160])
    return None
SHOTS = os.environ.get("FM_SHOT_DIR") or ""

if stage.engine_ready():
    print("--- 1. принтер закончил печать: кнопка в пульте и в списке автозапуска, на четырёх размерах ---")
    stage.set_live({"c1": IDLE, "c2": dict(IDLE, status="IDLE")})
    stage.set_api(api([{"id": "c1", "name": "X1C-01", "finished": True}]))
    for k, (w, h) in enumerate(SIZES):
        R = run(JS, window_size=(w, h), settle_ms=2600, path="/ui3",
                      extra_args=("--force-device-scale-factor=1.0",),
                      shot_path=(os.path.join(SHOTS, "plate_clear_%dx%d.png" % (w, h)) if SHOTS else None))
        tag = "%dx%d" % (w, h)
        if not R:
            check("%s. стенд проверен" % tag, False, str(stage.last_diag())[:200])
            continue
        if k == 0:
            check("1. (R-118) в списке автозапуска у X1C-01 (ждёт подтверждения) — кнопка «Стол очищен», у P1S-02 — нет",
                  R.get("autoBtns") == ["X1C-01"], R.get("autoBtns"))
            check("2. (R-140) в пульте X1C-01 «Служебное» показывает «Стол очищен» для очереди, без «служебных действий нет»",
                  R.get("ppBtn") is True and R.get("ppNote") is False
                  and "очередь сможет запустить следующую печать" in (R.get("ppTitle") or ""),
                  (R.get("ppBtn"), R.get("ppNote"), R.get("ppTitle")))
            check("3. нажатие спрашивает подтверждение и до ответа ничего не шлёт",
                  R.get("ask") is True and R.get("sentBeforeOk") == 0 and "X1C-01" in (R.get("askText") or ""),
                  (R.get("ask"), R.get("sentBeforeOk"), R.get("askText")))
            _pc = [s for s in (R.get("sent") or []) if "plate-clear" in s[0]]
            check("4. «Стол очищен» в окне — POST /api/printer/c1/plate-clear с {confirmed: true}",
                  _pc == [["/api/printer/c1/plate-clear", {"confirmed": True}]], R.get("sent"))
        check("5.%s ничего не вылезает: кнопка в пульте и в списке автозапуска целиком в своих блоках" % tag,
              not R.get("ppOver") and not R.get("autoOver") and not R.get("ppClip") and R.get("autoClip") == 0,
              (R.get("ppOver"), R.get("autoOver"), R.get("ppClip"), R.get("autoClip"), R.get("ppRc"), R.get("autoBtnRc")))
        check("6.%s прокрутки вбок нет ни на вкладке «Очередь», ни с открытым пультом" % tag,
              (R.get("hscrollQ") or 0) <= 1 and (R.get("hscrollP") or 0) <= 1, (R.get("hscrollQ"), R.get("hscrollP")))
        _probs = stage.page_problems(R)
        check("7.%s консоль чистая" % tag, not _probs, _probs[:3])

    print("--- 2. ждать нечего: кнопки нет, «служебных действий нет» на месте ---")
    stage.set_api(api([]))
    R2 = run(JS_SHORT, window_size=(1600, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    if not R2:
        check("8. стенд проверен", False, str(stage.last_diag())[:200])
    else:
        check("8. принтер не ждёт подтверждения — кнопки нет, показано «служебных действий сейчас нет»",
              R2.get("ppBtn") is False and R2.get("ppNote") is True, R2)

    print("--- 3. НЕ ВАКУУМ: принтер в plate_wait, но ради чего подтверждать нет ---")
    #  Не закончил печать, строки под него нет, автозапуск ему не разрешён — жёлтая кнопка ничего бы не меняла.
    stage.set_live({"c1": dict(IDLE, status="IDLE"), "c2": dict(IDLE, status="IDLE")})
    stage.set_api(api([{"id": "c1", "name": "X1C-01", "finished": False}], auto=()))
    R3 = run(JS_SHORT, window_size=(1600, 1000), settle_ms=2600, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    if not R3:
        check("9. стенд проверен", False, str(stage.last_diag())[:200])
    else:
        check("9. принтер свободен, без строки и без автозапуска — кнопки нет (иначе висела бы у всех)",
              R3.get("ppBtn") is False and R3.get("ppNote") is True, R3)
    stage.set_api(api([{"id": "c1", "name": "X1C-01", "finished": False}], items=[dict(ROW, match_printer_id="c1",
                                                                                      match_printer_name="X1C-01")], auto=()))
    R3b = run(JS_SHORT, window_size=(1600, 1000), settle_ms=2600, path="/ui3",
                    extra_args=("--force-device-scale-factor=1.0",))
    if not R3b:
        check("10. стенд проверен", False, str(stage.last_diag())[:200])
    else:
        check("10. тот же принтер, но на нём ждёт строка очереди — кнопка есть и шлёт подтверждение очереди",
              R3b.get("ppBtn") is True and R3b.get("ask") is True, R3b)

    print("--- 4. печать проекта ждёт стола — главнее очереди ---")
    _runs = {"/api/project-runs": {"runs": [{"run_id": "run1", "state": "running", "project_name": "Корпуса"}]},
             "/api/project-runs/run1": {"run_id": "run1", "state": "running", "project_name": "Корпуса",
                                        "items": [{"item_id": "i1", "state": "waiting_plate_clear",
                                                   "assigned_printer_id": "c1", "project_print_job_id": "pj1"}],
                                        "printers": [{"printer_id": "c1", "name": "X1C-01", "status": "FINISH",
                                                      "telemetry_fresh": True}],
                                        "counts": {}}}
    stage.set_live({"c1": IDLE, "c2": dict(IDLE, status="IDLE")})
    stage.set_api(api([{"id": "c1", "name": "X1C-01", "finished": True}], runs=_runs))
    R4 = run(JS_SHORT, window_size=(1600, 1000), settle_ms=3200, path="/ui3",
                   extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R4:
        check("11. стенд проверен", False, str(stage.last_diag())[:200])
    else:
        check("11. кнопка ведёт в подтверждение ПРОЕКТА: подпись проекта, окна очереди нет, запрос очереди не ушёл",
              R4.get("ppBtn") is True and "Программа ждёт подтверждения" in (R4.get("ppTitle") or "")
              and R4.get("ask") is False and R4.get("sent") == [], R4)
        _p4 = stage.page_problems(R4)
        check("12. консоль чистая и с планом проекта", not _p4, _p4[:3])
else:
    print("SKIP — браузер стенда недоступен: исполнение не проверено")

print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
