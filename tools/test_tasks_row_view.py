# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.895 — строка «Задач» ИЗМЕРЯЕТСЯ в настоящем браузере, а не проверяется на словах.

ЗАЧЕМ ЭТА ПРОВЕРКА СУЩЕСТВУЕТ. В 2.894 рядом с полями количества появились кнопки «−» и «+».
Разметка и стили выглядели правильно, все текстовые проверки были зелёными — а в браузере поле
сжалось до 15 px, и «100» в нём обрезалось. Дефект нашёлся только измерением. Здесь он и
закрывается: страница поднимается в headless-браузере на подменённых данных, и проверяется
ФАКТ — число из четырёх знаков видно целиком, метки проблем не вылезают из своей колонки,
горизонтальной полосы прокрутки нет, консоль чистая.

Данные синтетические (стенд tools/_fm_ui_stage.py): рабочая база, настоящие принтеры и печать
не затрагиваются. Ни сети наружу, ни отправки файлов.

Запуск:  python tools/test_tasks_row_view.py
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "TASKS_ROW_VIEW_SENTINEL_2_895"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


PRINTERS = [
    {"id": "p1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
     "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_0001", "access_code": ""},
]
#  Три задачи нарочно разные: сломанная (файла нет), чужая (нет подходящего принтера) и
#  исправная. Числа взяты предельные для фермы — четыре знака.
STAGING = [
    {"filename": "korpus_verhniy_v3.gcode.3mf", "status": "pending", "printer_id": "",
     "required_qty": 9999, "printed_qty": 100, "target_nozzles": 0.4,
     "target_model": "Bambu Lab X1 Carbon", "is_printable": True, "notes": "",
     "src_path": "", "linked": True, "missing": True, "compatible_pids": ["p1"],
     "mtime": 0, "cb": "0-x", "parts": [], "part_status": "ignored", "part_total": None,
     "part_reason": "object_names_missing", "part_confidence": ""},
    {"filename": "ochen_dlinnoe_imya_detali_dlya_proverki_granic_kolonki_02.gcode",
     "status": "pending", "printer_id": "", "required_qty": 4, "printed_qty": 0,
     "target_nozzles": 0.6, "target_model": "Voron 2.4", "is_printable": True,
     "notes": "заметка владельца", "src_path": "", "linked": True, "missing": False,
     "compatible_pids": [], "mtime": 0, "cb": "0-x", "parts": [], "part_status": "ignored",
     "part_total": None, "part_reason": "brand_new_reason_from_future", "part_confidence": ""},
    {"filename": "kryshka_ok.gcode.3mf", "status": "done", "printer_id": "", "required_qty": 2,
     "printed_qty": 2, "target_nozzles": 0.4, "target_model": "Bambu Lab X1 Carbon",
     "is_printable": True, "notes": "", "src_path": "", "linked": True, "missing": False,
     "compatible_pids": ["p1"], "mtime": 0, "cb": "0-x",
     "parts": [{"name": "kryshka", "count": 2}], "part_status": "counted", "part_total": 2,
     "part_reason": "", "part_confidence": "exact"},
]

JS = r"""
return new Promise(function(res){
  setTimeout(function(){
    var qty = [].slice.call(document.querySelectorAll('.qtpv-qty')).map(function(i){
      var r = i.getBoundingClientRect(), cell = i.closest('.qtqty');
      var cr = cell ? cell.getBoundingClientRect() : null;
      return { val: i.value, clip: i.scrollWidth - i.clientWidth,
               inCell: cr ? (r.left >= cr.left - 0.6 && r.right <= cr.right + 0.6) : false };
    });
    var btns = [].slice.call(document.querySelectorAll('.qtqty-btn')).map(function(b){
      var r = b.getBoundingClientRect(), cell = b.closest('.qtqty');
      var cr = cell ? cell.getBoundingClientRect() : null;
      return { w: Math.round(r.width), h: Math.round(r.height),
               inCell: cr ? (r.left >= cr.left - 0.6 && r.right <= cr.right + 0.6) : false };
    });
    //  Меряем САМУ дорожку полосы (.qtprog-bar), а не её обёртку: обёртка сжимается всегда,
    //  а вылезала за колонку именно дорожка с жёсткой шириной. Плюс собственное переполнение
    //  колонки имени: если внутри что-то шире неё, scrollWidth это покажет даже при overflow:hidden.
    var bars = [].slice.call(document.querySelectorAll('.qtprog-bar')).map(function(p){
      var r = p.getBoundingClientRect(), col = p.closest('.pvnamecol');
      var cr = col ? col.getBoundingClientRect() : null;
      var qty = p.closest('.pvrow') ? p.closest('.pvrow').querySelector('.qtqty') : null;
      var qr = qty ? qty.getBoundingClientRect() : null;
      return { w: Math.round(r.width),
               inCol: cr ? (r.left >= cr.left - 0.6 && r.right <= cr.right + 0.6) : false,
               colClip: col ? (col.scrollWidth - col.clientWidth) : 0,
               overQty: qr ? (r.right > qr.left + 0.6) : false };
    });
    var marks = [].slice.call(document.querySelectorAll('.qtprob-b')).map(function(b){
      var r = b.getBoundingClientRect(), host = b.closest('.pvnamecol');
      var hr = host ? host.getBoundingClientRect() : null;
      return { text: (b.textContent || '').trim(), cls: b.className,
               tip: (b.getAttribute('title') || '').length,
               inCol: hr ? (r.right <= hr.right + 1 && r.left >= hr.left - 1) : false };
    });
    var head = [].slice.call(document.querySelectorAll('.pvrow.qtpvrow.pvhead .pvc'));
    var row0 = document.querySelector('.pvrow.qtpvrow.pvpart');
    var cells0 = row0 ? [].slice.call(row0.querySelectorAll(':scope > .pvc')) : [];
    var tbl = document.querySelector('.pvtbl.qtpv');
    var filt = document.querySelector('.qtprob-filter');
    res(dump({
      qty: qty, btns: btns, marks: marks, bars: bars,
      headCells: head.length, rowCells: cells0.length,
      rows: document.querySelectorAll('.pvrow.qtpvrow.pvpart').length,
      hscroll: tbl ? (tbl.scrollWidth - tbl.clientWidth) : -1,
      docScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      filter: filt ? (filt.textContent || '').trim() : ''
    }));
  }, 900);
});
"""

if not stage.engine_ready():
    check("1. браузерный движок доступен (без него измерить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    check("1. браузерный движок доступен", True)
    stage.set_api({"/api/printers": PRINTERS, "/api/staging": STAGING})
    #  Широкое окно и УЗКОЕ. Узкое здесь главное: приложение держит раскладку на 960 своих точек,
    #  и на ноутбуке 1366 при 125-150 % колонке имени остаётся совсем мало места. Именно там
    #  полоса прогресса выходила за свою колонку.
    for (wnd, scale) in (((1600, 1000), 100), ((1600, 1000), 150), ((1280, 800), 100), ((1280, 800), 125)):
        scale_name = "%d %% при окне %d" % (scale, wnd[0])
        R = stage.run(JS, window_size=wnd, settle_ms=2500,
                      extra_args=("--force-device-scale-factor=%.2f" % (scale / 100.0),))
        if not R:
            check("2. страница «Задач» построилась на %s" % scale_name, False, str(stage.last_diag())[:200])
            continue
        diag = R.get("__diag") or {}
        check("2. страница «Задач» построилась на %s" % scale_name, True)
        check("3. все три задачи показаны на %s" % scale_name, R.get("rows") == 3, R.get("rows"))
        check("4. колонок шесть — ни одной лишней на %s" % scale_name,
              R.get("headCells") == 6 and R.get("rowCells") == 6,
              (R.get("headCells"), R.get("rowCells")))
        qty = R.get("qty") or []
        check("5. полей количества шесть на %s" % scale_name, len(qty) == 6, len(qty))
        clipped = [q for q in qty if q.get("clip", 0) > 1]
        check("6. число в поле видно ЦЕЛИКОМ, включая 9999, на %s" % scale_name,
              not clipped, clipped[:3])
        check("7. поля не вылезают из своей клетки на %s" % scale_name,
              all(q.get("inCell") for q in qty), [q for q in qty if not q.get("inCell")][:2])
        btns = R.get("btns") or []
        check("8. кнопки «−» и «+» есть у каждого поля и стоят внутри клетки на %s" % scale_name,
              len(btns) == 12 and all(b.get("inCell") for b in btns), len(btns))
        check("9. кнопки не выродились в точку на %s" % scale_name,
              all(b.get("w", 0) >= 9 and b.get("h", 0) >= 14 for b in btns), btns[:2])
        marks = R.get("marks") or []
        check("10. обе метки проблем показаны на %s" % scale_name, len(marks) == 2, marks)
        check("11. метки разной тяжести: беда и предупреждение на %s" % scale_name,
              any("qtprob-bad" in m.get("cls", "") for m in marks)
              and any("qtprob-warn" in m.get("cls", "") for m in marks), [m.get("cls") for m in marks])
        check("12. метки не вылезают из колонки имени на %s" % scale_name,
              all(m.get("inCol") for m in marks), [m for m in marks if not m.get("inCol")])
        check("13. у метки есть пояснение при наведении на %s" % scale_name,
              all(m.get("tip", 0) > 30 for m in marks), [m.get("tip") for m in marks])
        check("14. кнопка отбора «с проблемами» показана на %s" % scale_name,
              bool(R.get("filter")), R.get("filter"))
        _bars = R.get("bars") or []
        check("14a. полоса прогресса не вылезает из колонки имени на %s" % scale_name,
              bool(_bars) and all(b.get("inCol") for b in _bars),
              [b for b in _bars if not b.get("inCol")][:2])
        check("14b. полоса прогресса не налезает на поле количества на %s" % scale_name,
              not [b for b in _bars if b.get("overQty")],
              [b for b in _bars if b.get("overQty")][:2])
        check("14c. колонке имени нечего прятать: внутри неё ничего шире её самой на %s" % scale_name,
              not [b for b in _bars if (b.get("colClip") or 0) > 1],
              [(b.get("w"), b.get("colClip")) for b in _bars if (b.get("colClip") or 0) > 1][:3])
        check("15. лишней горизонтальной прокрутки нет на %s" % scale_name,
              (R.get("hscroll") or 0) <= 0 and (R.get("docScroll") or 0) <= 0,
              (R.get("hscroll"), R.get("docScroll")))
        check("16. консоль браузера чистая на %s" % scale_name,
              not (diag.get("consoleErrors") or diag.get("pageErrors") or diag.get("unhandled"))
              and not [w for w in (diag.get("consoleWarnings") or []) if "Vue warn" in str(w)],
              json.dumps(diag, ensure_ascii=False)[:200])
    stage.set_api(None)
    stage.stop()

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
