# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.900 — новые элементы читаются в ОБЕИХ темах, а не только в тёмной.

ЗАЧЕМ. Выпуски 2.893-2.898 добавили в «Задачи» и «Отчёты» полтора десятка новых элементов, и
часть цветов была взята жёсткими значениями вместо переменных темы. На тёмной теме всё выглядело
правильно, а на светлой заголовок группы задач становился почти белым на белом (контраст 1.2:1) —
то есть имя заказа, ради которого сделана вся группировка, пропадало с экрана. Глазами это никто
не поймал: проверяли на тёмной.

Здесь контраст ИЗМЕРЯЕТСЯ в настоящем браузере по формуле WCAG: берётся вычисленный цвет текста и
ДЕЙСТВИТЕЛЬНЫЙ цвет подложки (поднимаясь по предкам, пока не встретится непрозрачный фон).
Порог 3.0 — это «видно»; найденный дефект давал 1.2.

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами, рабочая база и принтеры не затрагиваются.

Запуск:  python tools/test_light_theme_contrast.py
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

SENTINEL = "LIGHT_THEME_CONTRAST_SENTINEL_2_900"
CSS = io.open(os.path.join(ROOT, "web", "app.css"), encoding="utf-8", errors="replace").read()
BS = chr(92)
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


print("--- цвета берутся из переменных темы, а не зашиты ---")
#  Эти токены объявлены ОДИН раз и от темы не зависят: в новых элементах им не место.
#  Комментарии вырезаем — в них эти имена упоминаются как раз с объяснением, почему их убрали.
FIXED_TOKENS = ("--fm-neutral-90b", "--fm-neutral-15", "--fm-neutral-65")
CSS_NC = re.sub(r"/\*.*?\*/", " ", CSS, flags=re.S)
NEW_BLOCK = CSS_NC[CSS_NC.find(".qtprog{"):]
_bad = [t for t in FIXED_TOKENS if t in NEW_BLOCK]
check("1. в новых правилах нет цветов, не зависящих от темы", not _bad, _bad)
check("2. подложки новых блоков взяты из темы",
      ".qtgrp{" in CSS and "background:var(--fm-surface-raised)" in CSS
      and "rgba(255,255,255,0.03)}" not in CSS.split(".qtgrp{")[-1][:400])

PRINTERS = [{"id": "p1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
             "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_SN_0001", "access_code": ""}]
STAGING = [
    {"filename": "korpus_verhniy.gcode.3mf", "project_id": "p1", "project_name": "Заказ Иванов",
     "src_path": "", "required_qty": 100, "printed_qty": 37, "missing": True,
     "part_reason": "object_names_missing"},
    {"filename": "kryshka.gcode.3mf", "project_id": "p1", "project_name": "Заказ Иванов",
     "src_path": "", "required_qty": 8, "printed_qty": 8, "missing": False, "part_reason": ""},
    {"filename": "chuzhaya.gcode", "project_id": "", "project_name": "", "src_path": "",
     "required_qty": 2, "printed_qty": 0, "missing": False, "part_reason": ""},
]
for f in STAGING:
    f.update({"status": "pending", "printer_id": "", "target_nozzles": 0.4,
              "target_model": "Bambu Lab X1 Carbon", "is_printable": True, "notes": "",
              "linked": False, "mtime": 0, "cb": "0-x", "parts": [], "part_total": None,
              "part_status": ("ignored" if f["part_reason"] else None), "part_confidence": "",
              "compatible_pids": ([] if f["filename"] == "chuzhaya.gcode" else ["p1"])})
MODULES = {"modules": [{"id": "quality", "ru": "Качество печати", "en": "Print quality",
                        "version": "0.2.2", "icon": "activity", "enabled": True,
                        "state": "loaded", "launchers": []}]}
RUNS = {"runs": [
    {"run_id": "run_%d" % i, "printer_id": "p1", "printer_name": "X1C-01",
     "filename": "korpus_verhniy.gcode.3mf", "started_at": "2026-08-2%d 10:00:00" % (i % 7),
     "elapsed_s": 1800 + i * 60, "outcome_raw": ["finished", "failed", "cancelled", "unknown"][i % 4],
     "terminal_reason": ""} for i in range(12)]}

#  Что меряем: элемент, порог контраста и человеческое имя. Порог 3.0 — «видно»;
#  для рамок берём отдельный, более мягкий порог: рамка не обязана быть контрастной, но обязана
#  отличаться от фона.
TEXT_TARGETS = [
    (".qtgrp-t", 3.0, "имя группы задач"),
    (".qtgrp-n", 2.5, "число задач в группе"),
    (".qtgrp-sum", 2.5, "итог по группе"),
    (".qtprog-txt", 2.5, "подпись прогресса задачи"),
    (".qtprob-b", 2.5, "метка проблемы задачи"),
    (".qtprob-filter", 2.5, "кнопка отбора «Проблемы»"),
    (".rep-cv", 3.0, "число в сводке отчёта"),
    (".rep-cl", 2.5, "подпись числа в отчёте"),
    (".rep-sec-h", 3.0, "заголовок раздела отчёта"),
    (".rep-name", 3.0, "имя принтера в таблице отчёта"),
    (".rep-th", 2.5, "шапка таблицы отчёта"),
    (".rep-foot", 2.5, "честные оговорки внизу отчёта"),
    (".rep-day-n", 2.5, "число над столбиком дня"),
]
BORDER_TARGETS = [
    (".qtqty-btn", 1.25, "рамка кнопок «−»/«+»"),
    (".qtgrp", 1.15, "рамка заголовка группы"),
    (".rep-card", 1.15, "рамка карточки отчёта"),
]

JS = r"""
return new Promise(function(res){
  function lum(c){
    var m = (c || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    var p = m[1].split(',').map(function(x){ return parseFloat(x); });
    if (p.length > 3 && p[3] === 0) return null;
    var f = p.slice(0, 3).map(function(v){ v = v / 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
  }
  function bgOf(el){
    var n = el;
    while (n && n.nodeType === 1) {
      var c = getComputedStyle(n).backgroundColor;
      var l = lum(c);
      if (l !== null) return c;
      n = n.parentElement;
    }
    return 'rgb(255,255,255)';
  }
  function ratio(a, b){
    var la = lum(a), lb = lum(b);
    if (la === null || lb === null) return null;
    var hi = Math.max(la, lb), lo = Math.min(la, lb);
    return Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100;
  }
  function measure(sel){
    var el = document.querySelector(sel);
    if (!el) return { sel: sel, found: false };
    var cs = getComputedStyle(el);
    var bg = bgOf(el.parentElement || el);
    return { sel: sel, found: true, text: ratio(cs.color, bg),
             border: ratio(cs.borderTopColor, bg), color: cs.color, bg: bg,
             visible: el.getBoundingClientRect().width > 0 };
  }
  function snap(theme){
    document.documentElement.setAttribute('data-theme', theme);
    var out = { theme: theme, items: [] };
    var sels = SELECTORS;
    for (var i = 0; i < sels.length; i++) out.items.push(measure(sels[i]));
    return out;
  }
  setTimeout(function(){
    var later = byText('button', ['Позже', 'Later']); if (later) click(later);
    setUiLang('ru');
    setTimeout(function(){
      //  Включаем группировку по проекту — иначе заголовка группы на экране нет.
      var gb = [].slice.call(document.querySelectorAll('.qtgrp-pick button'));
      for (var i = 0; i < gb.length; i++) {
        var t = (gb[i].textContent || '').trim();
        if (t === 'по проекту' || t === 'By project') { click(gb[i]); break; }
      }
      setTimeout(function(){
        var tasks = { light: snap('light'), dark: snap('dark') };
        //  Теперь тот же замер на экране отчётов.
        click(gear());
        setTimeout(function(){
          var tile = byText('.fm-set-tile', ['Отчёты', 'Reports']);
          if (tile) click(tile);
          setTimeout(function(){
            var reports = { light: snap('light'), dark: snap('dark') };
            document.documentElement.setAttribute('data-theme', 'dark');
            res(dump({ tasks: tasks, reports: reports }));
          }, 1100);
        }, 700);
      }, 600);
    }, 500);
  }, 1200);
});
"""

if not stage.engine_ready():
    check("3. браузерный движок доступен (без него контраст измерить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    check("3. браузерный движок доступен", True)
    stage.set_api({"/api/printers": PRINTERS, "/api/staging": STAGING,
                   "/api/modules": MODULES, "/api/mod/quality/print-runs": RUNS})
    sels = [t[0] for t in TEXT_TARGETS] + [t[0] for t in BORDER_TARGETS]
    js = "const SELECTORS = " + json.dumps(sels) + ";\n" + JS
    R = stage.run(js, window_size=(1600, 1000), settle_ms=2500,
                  extra_args=("--force-device-scale-factor=1.0",))
    stage.set_api(None)
    stage.stop()
    if not R:
        check("4. страницы построились и измерены", False, str(stage.last_diag())[:220])
    else:
        check("4. страницы построились и измерены", True)
        by = {}
        for screen in ("tasks", "reports"):
            for theme in ("light", "dark"):
                for it in ((R.get(screen) or {}).get(theme) or {}).get("items", []):
                    if it.get("found"):
                        by[(it["sel"], theme)] = it
        #  Каждый элемент обязан найтись хотя бы на одном из двух экранов.
        missing = [s for s in sels if (s, "light") not in by]
        check("5. все проверяемые элементы найдены на экране", not missing, missing)

        for sel, thr, human in TEXT_TARGETS:
            for theme, tname in (("light", "светлая"), ("dark", "тёмная")):
                it = by.get((sel, theme))
                if not it:
                    continue
                val = it.get("text")
                check("6.%s %s — %s тема: контраст текста %s (нужно >= %s)"
                      % (sel, human, tname, val, thr),
                      val is not None and val >= thr,
                      "цвет %s на фоне %s" % (it.get("color"), it.get("bg")))
        for sel, thr, human in BORDER_TARGETS:
            for theme, tname in (("light", "светлая"), ("dark", "тёмная")):
                it = by.get((sel, theme))
                if not it:
                    continue
                val = it.get("border")
                check("7.%s %s — %s тема: рамка отличается от фона (%s, нужно >= %s)"
                      % (sel, human, tname, val, thr),
                      val is not None and val >= thr,
                      "рамка на фоне %s" % (it.get("bg"),))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
