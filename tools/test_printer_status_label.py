# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.897 — подпись состояния на карточке принтера помещается целиком.

ЗАЧЕМ. Подпись стояла в жёстких 45 точках с обрезанием: и русское «ОФЛАЙН», и английское
OFFLINE в них не влезали, и владелец видел «ОФЛ…». Нашлось измерением, чинится измерением:
страница поднимается в настоящем браузере, и проверяется ФАКТ — слово видно целиком, строка
карточки при этом не разъезжается.

Длинные состояния («СВОБОДЕН», «ОЖИДАНИЕ», OPERATIONAL) стенд сам показать не может: состояния
приходят по вебсокету живого сервера. Поэтому текст подставляется прямо в элемент — разметка,
стили и раскладка при этом настоящие, подменяется только слово.

БЕЗОПАСНОСТЬ: синтетические ответы стенда, рабочая база и принтеры не затрагиваются.

Запуск:  python tools/test_printer_status_label.py
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import _fm_ui_stage as stage  # noqa: E402

SENTINEL = "PRINTER_STATUS_LABEL_SENTINEL_2_897"
CSS = io.open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8", errors="replace").read()
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


check("1. правило ширины подписи описано в стилях",
      "body .fm-style-migrated.fm-printers-font-bold-10{width:auto;min-width:45px;max-width:88px}" in CSS)

PRINTERS = [
    {"id": "p1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
     "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_0001", "access_code": ""},
    {"id": "p2", "name": "K2-02", "type": "klipper", "model": "Creality K2 Plus",
     "ip": "10.0.0.12", "port": 7125, "serial": "FIXTURE_SN_0002", "access_code": ""},
]

JS = r"""
return new Promise(function(res){
  setTimeout(function(){
    var later = byText('button', ['Позже', 'Later']);
    if (later) click(later);
    setUiLang('ru');
    setTimeout(function(){
      var out = { cases: [] };
      var els = [].slice.call(document.querySelectorAll('.fm-printers-font-bold-10'));
      out.found = els.length;
      var words = ['ОФЛАЙН', 'ПЕЧАТЬ', 'СВОБОДЕН', 'ОЖИДАНИЕ', 'OPERATIONAL'];
      for (var w = 0; w < words.length; w++) {
        var el = els[0];
        if (!el) break;
        el.textContent = words[w];
        var row = el.parentElement;
        var r = el.getBoundingClientRect(), rr = row.getBoundingClientRect();
        out.cases.push({
          word: words[w],
          clip: el.scrollWidth - el.clientWidth,
          w: el.offsetWidth,
          inRow: (r.left >= rr.left - 0.6 && r.right <= rr.right + 0.6),
          rowClip: row.scrollWidth - row.clientWidth
        });
      }
      //  Вернуть исходное слово, чтобы дальнейшие измерения шли по настоящему состоянию.
      if (els[0]) els[0].textContent = 'ОФЛАЙН';
      var el2 = els[0], row2 = el2 ? el2.parentElement : null;
      out.card = row2 ? { clip: row2.scrollWidth - row2.clientWidth,
                          h: Math.round(row2.getBoundingClientRect().height) } : null;
      out.docScroll = document.documentElement.scrollWidth - document.documentElement.clientWidth;
      res(dump(out));
    }, 600);
  }, 1200);
});
"""

if not stage.engine_ready():
    check("2. браузерный движок доступен (без него измерить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    check("2. браузерный движок доступен", True)
    stage.set_api({"/api/printers": PRINTERS})
    for scale in (100, 150):
        R = stage.run(JS, window_size=(1600, 1000), settle_ms=2500,
                      extra_args=("--force-device-scale-factor=%.2f" % (scale / 100.0),))
        if not R:
            check("3. карточка принтера построилась на %d %%" % scale, False, str(stage.last_diag())[:200])
            continue
        check("3. карточка принтера построилась на %d %%" % scale, (R.get("found") or 0) >= 1, R.get("found"))
        cases = R.get("cases") or []
        bad = [c for c in cases if c.get("clip", 0) > 1]
        check("4. слово состояния видно целиком на %d %% (включая «ОФЛАЙН» и «СВОБОДЕН»)"
              % scale, not bad, bad[:3])
        check("5. подпись не вылезает из строки карточки на %d %%" % scale,
              all(c.get("inRow") for c in cases), [c for c in cases if not c.get("inRow")][:2])
        check("6. строка карточки не разъезжается от длинного слова на %d %%" % scale,
              all((c.get("rowClip") or 0) <= 1 for c in cases),
              [(c["word"], c.get("rowClip")) for c in cases])
        #  Ширина меряется в собственных точках страницы: у приложения свой зум, и экранные
        #  точки от него зависят. Нижняя граница — что уговор про минимум соблюдён, верхняя —
        #  что подпись не съедает строку.
        check("7. подпись не уже 45 и не шире 88 точек на %d %%" % scale,
              all(45 <= (c.get("w") or 0) <= 88 for c in cases),
              [(c["word"], c.get("w")) for c in cases])
        check("8. лишней горизонтальной прокрутки страницы нет на %d %%" % scale,
              (R.get("docScroll") or 0) <= 0, R.get("docScroll"))
        _d = R.get("__diag") or {}
        check("9. консоль браузера чистая на %d %%" % scale,
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              json.dumps(_d, ensure_ascii=False)[:200])
    stage.set_api(None)
    stage.stop()

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
