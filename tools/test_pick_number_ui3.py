# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.967 — номер выбранного на печать принтера в виде «Список» (заказ владельца).

ЗАЧЕМ. Со снимка с фермы цифру в маленьком кружке было почти не разглядеть. Владелец выбрал
прямоугольник у ПРАВОГО края строки, обрезанный её краем, и потребовал, чтобы все значки были
ОДНОГО размера — по самому большому номеру. Здесь легко ошибиться молча: значок ляжет на
температуру, у разных строк разъедется ширина, или рядом останется старый номер в углу
карточки и число задвоится.

Проверяется ИСПОЛНЕНИЕМ в настоящем браузере на трёх размерах фермы: 3 принтера (один знак),
12 (два знака) и 100 (три знака).

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_pick_number_ui3.py
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

SENTINEL = "PICK_NUMBER_UI3_SENTINEL_2_967"
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
CSS = io.open(os.path.join(ROOT, "web", "ui3", "ui3.css"), encoding="utf-8").read()

print("--- 1. устройство закреплено в файлах ---")
check("1. значок лежит ВНУТРИ строки последним элементом — его обрезает сама строка",
      '<span v-if="ui3Mode && printSel.includes(p.id)" class="pc-row-pick"' in IDX
      and "height: 34px; padding: 0 10px; overflow: hidden; }" in CSS)
check("2. прежний номер в углу карточки в этом виде не показывается — числа не задваиваются",
      "html.ui3-mode .pc-rows .pc-pick-num { display: none !important; }" in CSS)
check("3. размер ОДИН И ТОТ ЖЕ всегда: посчитан по трёхзначному числу, от количества не зависит",
      "pn-w" not in IDX and "pn-w" not in CSS
      and "width: 48px; height: 24px;" in CSS and "width: 38px; height: 24px;" in CSS)
check("3a. в «Сетке» значок встроен в правый нижний угол: тот же оранжевый, внешний угол как у плитки",
      "html.ui3-mode .printer-card:not(.pc-grid) .pc-pick-num {" in CSS
      and "html.ui3-mode .printer-card.pc-grid .pc-pick-num {" in CSS
      and "top: auto; left: auto; right: 0; bottom: 0;" in CSS
      and "width: 36px; height: 16px;" in CSS and "border-radius: 8px 0 14px 0;" in CSS)
check("3b. содержимое плитки поднимается ровно на высоту значка и только пока она отмечена",
      "html.ui3-mode .printer-card.pc-grid.pc-pick-sel .grid-summary { padding-bottom: 16px; }" in CSS)
check("4. это прямоугольник со скруглением, а не круг",
      "border-radius: 7px;" in CSS.split("html.ui3-mode .pc-row-pick {", 1)[1].split("}", 1)[0])
_rules = [l for l in re.sub(r"/\*.*?\*/", "", CSS, flags=re.S).splitlines() if ".pc-row-pick" in l or ".pn-w" in l]
check("5. каждое правило значка в ui3.css начинается с html.ui3-mode",
      _rules and all(l.startswith("html.ui3-mode") for l in _rules),
      [l[:60] for l in _rules if not l.startswith("html.ui3-mode")][:3])

print("--- 2. исполнение: ферма из 3, 12 и 100 принтеров ---")
JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  setTimeout(function(){
    var l = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (l) l.click(); setUiLang('ru');
    setTimeout(function(){
      var sw = q('[data-tour="pview"] button') || q('[data-tour="pview"]');
      var tries = 0;
      (function toRows(){
        if (q('.pc-row') || tries > 4) return step2();
        tries++; if (sw) sw.click(); setTimeout(toRows, 350);
      })();
      function step2(){
        setTimeout(function(){
          var out = { rows: qa('.pc-row').length };
          var tt = qa('.ui3-rtabs button').filter(function(b){ return /Задачи/.test(b.textContent); })[0];
          if (tt) tt.click();
          var go = qa('button.ui3-qtrail').filter(function(b){ return /ыбрать принтер|elect printer/.test(b.title); })[0];
          out.goFound = !!go;
          if (go) go.click();
          setTimeout(function(){
            qa('[data-pid]').forEach(function(c){ c.click(); });
            setTimeout(function(){
              var picks = qa('.pc-row-pick');
              out.n = picks.length;
              out.nums = picks.map(function(b){ return b.textContent.trim(); });
              out.sizes = picks.map(function(b){ var r = b.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height); });
              out.oldShown = qa('.pc-pick-num').filter(function(b){ return b.offsetParent !== null; }).length;
              out.wclass = ((q('.pc-pick-sel') || {}).className || '').split(' ').filter(function(c){ return c.indexOf('pn-w') === 0; })[0] || '';
              var b0 = picks[0], row = b0 && b0.closest('.pc-row');
              if (b0 && row) {
                var br = b0.getBoundingClientRect(), rr = row.getBoundingClientRect();
                out.cut = Math.round(br.right - rr.right);          // насколько уходит за край строки
                out.font = getComputedStyle(b0).fontSize;
                var t = row.querySelectorAll('.pc-row-t');
                var last = t[t.length - 1];
                out.gapToTemp = last ? Math.round(br.left - last.getBoundingClientRect().right) : null;
                out.overlap = last ? (br.left < last.getBoundingClientRect().right - 1) : null;
                //  цифра не обрезана: правый край ТЕКСТА внутри видимой части значка
                var rg = document.createRange();
                rg.selectNodeContents(b0);
                var tr2 = rg.getBoundingClientRect();
                out.textRight = Math.round(tr2.right);
                out.rowRight = Math.round(rr.right);
                out.textFits = tr2.right <= rr.right - 1;   // цифры целиком внутри строки
              }
              res(dump(out));
            }, 900);
          }, 700);
        }, 500);
      }
    }, 1000);
  }, 1900);
});
"""


def farm(n):
    pr = [{"id": "p%d" % i, "name": "X%d" % i, "type": "bambu", "model": "Bambu Lab X1 Carbon",
           "ip": "10.0.0.%d" % (i % 250), "port": 8883, "serial": "FIXTURE_%d" % i, "access_code": ""}
          for i in range(1, n + 1)]
    live = {p["id"]: {"status": "FINISH", "nozzle_temp": 28, "bed_temp": 25, "nozzle_count": 1} for p in pr}
    return pr, live


STAGING = [{"filename": "korpus.gcode.3mf", "project_id": "", "project_name": "", "src_path": "",
            "required_qty": 5, "printed_qty": 0, "missing": False, "part_reason": "",
            "is_printable": True, "printer_type": "bambu"}]

if stage.engine_ready():
    _res = {}
    for n in (3, 12, 100):
        pr, live = farm(n)
        stage.set_api({"/api/printers": pr, "/api/staging": STAGING,
                       "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
        stage.set_live(live)
        _res[n] = stage.run(JS, window_size=(1600, 950), settle_ms=2600, path="/ui3",
                            extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()

    if not all(_res.values()):
        check("6. номер проверен исполнением", False, str(stage.last_diag())[:200])
    else:
        _all = set()
        for n in (3, 12, 100):
            R = _res[n]
            check("6.%d ферма из %d: номер у каждого отмеченного, счёт по порядку" % (n, n),
                  R.get("n") == n and R.get("nums")[:2] == ["1", "2"] and R.get("nums")[-1] == str(n),
                  (R.get("n"), (R.get("nums") or [])[-1:]))
            check("7.%d ферма из %d: все значки ОДНОГО размера, и он не зависит от количества" % (n, n),
                  len(set(R.get("sizes") or [])) == 1 and R.get("wclass") == "",
                  (set(R.get("sizes") or []), R.get("wclass")))
            check("8.%d ферма из %d: значок обрезан краем строки и не лежит на температуре" % (n, n),
                  (R.get("cut") or 0) > 4 and R.get("overlap") is False and (R.get("gapToTemp") or 0) > 4,
                  (R.get("cut"), R.get("overlap"), R.get("gapToTemp")))
            check("9.%d ферма из %d: цифра крупная и не срезана краем" % (n, n),
                  R.get("font") == "13.5px" and R.get("textFits") is True,
                  (R.get("font"), R.get("textRight"), R.get("rowRight")))
            check("10.%d ферма из %d: прежний номер в углу не показан — числа не задвоились" % (n, n),
                  R.get("oldShown") == 0, R.get("oldShown"))
            _all |= set(R.get("sizes") or [])
            _d = R.get("__diag") or {}
            check("11.%d ферма из %d: консоль чистая" % (n, n),
                  not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
                  json.dumps(_d, ensure_ascii=False)[:160])
        check("12. размер значка ОДИН на всех трёх фермах: 3, 12 и 100 принтеров",
              len(_all) == 1, _all)
else:
    print("SKIP — браузер стенда недоступен: исполнение не проверено")

print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
