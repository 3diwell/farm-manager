# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.971 — «сколько попросил, столько и завелось»: поле количества виртуальных принтеров.

ЗАЧЕМ. Владелец просил заводить виртуальные принтеры В ЛЮБОМ КОЛИЧЕСТВЕ, а прежние
нарисованные плитки «Демо 30» убрать: их нельзя было ни открыть, ни удалить, и при любом
сохранении списка они попадали в базу принтеров.

ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ. Настоящая страница в настоящем браузере: поле рядом с кнопкой, границы
1..50, и ГЛАВНОЕ — что уходит на сохранение. Запрос перехватывается на выходе из страницы,
поэтому видно ровно то, что получит сервер: столько принтеров, сколько попросили, все типа
demo, без служебных полей и без подделок.

Что печать на таком принтере действительно идёт и поднимает счёт в задачах — проверяется
отдельно, на живом сервере: tools/test_demo_printer_e2e.py.

Запуск:  python tools/test_virtual_printer_add.py
"""
import importlib.util
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location(
    "fm_stage_vprinter", os.path.join(ROOT, "tools", "_fm_ui_stage.py"))
stage = importlib.util.module_from_spec(_s)
_s.loader.exec_module(stage)

SENTINEL = "VIRTUAL_PRINTER_ADD_SENTINEL_2_971"
PASS = FAIL = 0
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
HTML = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


print("--- 1. устройство закреплено в файлах ---")
check("1. поле количества стоит рядом с кнопкой в форме добавления принтера",
      'data-help="pf-demo-n"' in HTML and 'data-help="pf-demo"' in HTML)
check("2. границы количества заданы и в разметке, и в коде: от 1 до 50",
      'min="1" max="50"' in HTML and "Math.min(50," in APPJS)
check("3. подделок «Демо 30» в коде не осталось",
      "ui3ApplyDemo" not in APPJS and "ui3DemoToggle" not in APPJS and "ui3DemoN" not in APPJS)
check("4. на запись списка принтеров ведёт один собранный путь",
      APPJS.count("executePostMatrix('/api/printers/save'") == 3
      and APPJS.count("executePostMatrix('/api/printers/save', _printersPayload(") == 3)

print("--- 2. настоящий браузер: вид строки и что уходит на сохранение ---")
stage.set_api({"/api/printers": []})

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var sent = [];
  var realFetch = window.fetch;
  window.fetch = function(u, o){
    try {
      if (String(u).indexOf('/api/printers/save') >= 0 && o && o.body) sent.push(JSON.parse(o.body));
    } catch (e) { sent.push('NEPARSED'); }
    return realFetch.apply(window, arguments);
  };
  setTimeout(function(){
    var later = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (later) later.click();
    try { setUiLang('ru'); } catch(e) {}
    setTimeout(function(){
      var add = q('[data-help="add-printer"]');
      if (add) add.click();
      setTimeout(function(){
        var inp = q('[data-help="pf-demo-n"]'), btn = q('[data-help="pf-demo"]');
        var out = { found: !!inp && !!btn, value0: inp ? inp.value : null };
        if (!inp || !btn) { res(dump(out)); return; }
        var ri = inp.getBoundingClientRect(), rb = btn.getBoundingClientRect();
        var rr = inp.parentElement.getBoundingClientRect();
        out.oneRow = Math.abs((ri.top + ri.height / 2) - (rb.top + rb.height / 2)) <= 2;
        out.inRow = rb.left + rb.width <= rr.left + rr.width + 1 && ri.left >= rr.left - 1;
        out.textFits = btn.scrollWidth <= btn.clientWidth + 1 && btn.scrollHeight <= btn.clientHeight + 1;
        out.noOverlap = ri.left + ri.width <= rb.left + 0.5;
        out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
        function set(v){ inp.value = String(v); inp.dispatchEvent(new Event('change', {bubbles:true})); }
        set(0);
        setTimeout(function(){
          out.low = q('[data-help="pf-demo-n"]').value;
          set(999);
          setTimeout(function(){
            out.high = q('[data-help="pf-demo-n"]').value;
            set(3);
            setTimeout(function(){
              out.set3 = q('[data-help="pf-demo-n"]').value;
              q('[data-help="pf-demo"]').click();
              setTimeout(function(){
                out.sent = sent;
                res(dump(out));
              }, 700);
            }, 120);
          }, 120);
        }, 120);
      }, 600);
    }, 900);
  }, 1200);
});
"""

R = stage.run(JS, window_size=(1600, 1500), settle_ms=5200, path="/ui3") if stage.engine_ready() else None
if not R:
    print("SKIP — браузера нет, исполняемые проверки пропущены")
else:
    check("5. поле и кнопка найдены, по умолчанию заводится один принтер",
          R.get("found") is True and R.get("value0") == "1", (R.get("found"), R.get("value0")))
    check("6. поле и кнопка в одной строке, не налезают друг на друга и не вылезают из формы",
          R.get("oneRow") is True and R.get("inRow") is True and R.get("noOverlap") is True,
          (R.get("oneRow"), R.get("inRow"), R.get("noOverlap")))
    check("7. подпись кнопки помещается целиком, горизонтальной полосы нет",
          R.get("textFits") is True and R.get("hscroll") is False,
          (R.get("textFits"), R.get("hscroll")))
    check("8. меньше одного и больше пятидесяти ввести нельзя: 0 -> 1, 999 -> 50",
          R.get("low") == "1" and R.get("high") == "50", (R.get("low"), R.get("high")))
    _sent = R.get("sent") or []
    _last = _sent[-1] if _sent else None
    check("9. нажатие отправило список на сохранение ровно один раз",
          len(_sent) == 1 and isinstance(_last, list), len(_sent))
    check("10. заведено столько принтеров, сколько попросили: три",
          isinstance(_last, list) and len(_last) == 3,
          _last if not isinstance(_last, list) else len(_last))
    check("11. все три — виртуальные, без адреса и кода доступа",
          isinstance(_last, list) and all(x.get("type") == "demo" and not x.get("ip")
                                          and "token" not in x and "access_code" not in x
                                          for x in _last),
          json.dumps(_last, ensure_ascii=False)[:200])
    check("12. имена не повторяются, и у каждого принтера свой номер",
          isinstance(_last, list)
          and len({x.get("name") for x in _last}) == 3
          and len({x.get("id") for x in _last}) == 3,
          [x.get("name") for x in (_last or [])])
    check("13. в списке нет ни одной подделки и нет служебных полей",
          isinstance(_last, list)
          and not [x for x in _last if x.get("__demo") or x.get("__ui3demo")]
          and all(set(x) <= {"id", "name", "type", "ip", "port", "gen", "serial", "model", "token"}
                  for x in _last),
          json.dumps(_last, ensure_ascii=False)[:200])
    _diag = R.get("__diag") or {}
    check("14. консоль браузера чистая",
          not (_diag.get("consoleErrors") or _diag.get("pageErrors") or _diag.get("unhandled"))
          and not [w for w in (_diag.get("consoleWarnings") or []) if "Vue warn" in str(w)],
          json.dumps(_diag, ensure_ascii=False)[:220])

print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
