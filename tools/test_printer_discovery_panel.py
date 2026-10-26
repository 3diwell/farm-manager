# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.10.2026 (R-092) — панель «Найти в сети»: почему ничего не нашлось и FlashForge без лишнего ввода.

ЗАЧЕМ. Сервер давно присылал в снимке поиска занятые порты и предупреждения, но панель их не
показывала: «найдено 0» приходило без причины, хотя частая причина на ферме — порт 2021 занят
Bambu Studio или OrcaSlicer на этом же компьютере. И у FlashForge код доступа — «серийник:код
проверки», а серийник принтер объявляет сам: владелец вписывал его руками.

ЧТО ПРОВЕРЯЕТСЯ (настоящие index.html и app.js в браузере, ответы сервера подставлены стендом):
  1. занятые порты — понятные строки под шапкой панели; строки внутри формы, текст не обрезан,
     страница не уезжает вбок — на четырёх размерах окна (UI 3.0) и на двух (UI 2.0);
  2. «Заполнить форму» у найденного FlashForge: тип FlashForge, адрес, серийник уже в поле кода
     с двоеточием — остаётся дописать код проверки;
  3. «найдено 0», а устройства в сети на вопросы отвечали — об этом сказано; свои же вопросы,
     вернувшиеся на слушатели портов, ответами не считаются;
  4. консоль браузера чистая.

Сеть не трогается: стенд на 127.0.0.1, поиск не запускается (ответы сервера подставлены).
Запуск: python tools/test_printer_discovery_panel.py   (0 = пройдено)
Снимки для осмотра: FM_DISC_SHOTS=<папка> python tools/test_printer_discovery_panel.py
"""
import importlib.util
import json
import os
import sys

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location("fm_stage_discpanel", os.path.join(ROOT, "tools", "_fm_ui_stage.py"))
stage = importlib.util.module_from_spec(_s)
_s.loader.exec_module(stage)

SENTINEL = "PRINTER_DISCOVERY_PANEL_SENTINEL_R092"
fails = []


def check(name, ok, extra=""):
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:600] if (not ok and extra != "") else ""))
    if not ok:
        fails.append(name)


def snap(ports_closed=(), devices=(), received=None, warnings=()):
    return {"status": "ok", "active": False, "phase": "done", "seconds": 25, "elapsed_s": 25.0,
            "remaining_s": 0, "asked": [],
            "ports": [{"port": p, "open": p not in ports_closed, "joined": p not in ports_closed,
                       "error": ("OSError: [WinError 10048] адрес уже используется" if p in ports_closed else "")}
                      for p in (2021, 1990, 5353, 1900)],
            "warnings": list(warnings) or [{"code": "port_busy", "text": "порт %d занять не удалось" % p}
                                           for p in ports_closed],
            "received": dict(received or {}), "devices": list(devices), "found": len(devices)}


FF_DEV = {"key": "id:serial:SNFF0001", "family": "flashforge", "adapter": "flashforge", "ip": "192.0.2.60",
          "port": 8899, "name": "Adventurer 5M Pro у стены", "model": "", "model_code": "",
          "serial": "SNFF0001", "state": "new", "sources": ["flashforge"]}

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = {};
  setTimeout(function(){
    var later = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (later) later.click();
    try { setUiLang('ru'); } catch(e) {}
    setTimeout(function(){
      var add = q('[data-help="add-printer"]'); out.addBtn = !!add;
      if (add) add.click();
      setTimeout(function(){
        var find = q('[data-help="pf-find"]'); out.findBtn = !!find;
        if (find) find.click();
        setTimeout(function(){
          var sheet = q('.fm-addp-sheet'), panel = q('.pd-panel');
          out.panel = !!panel;
          var pr = panel ? panel.getBoundingClientRect() : null, sr = sheet ? sheet.getBoundingClientRect() : null;
          out.notes = qa('.pd-panel .pd-note[role="status"]').map(function(n){
            var r = n.getBoundingClientRect();
            return {text: (n.textContent || '').trim(),
                    inside: !!pr && r.left >= pr.left - 0.5 && r.right <= pr.right + 0.5 && (!sr || r.right <= sr.right + 0.5),
                    clipped: n.scrollWidth > n.clientWidth + 1, visible: r.width > 0 && r.height > 0,
                    color: getComputedStyle(n).color};
          });
          out.empty = !!q('.pd-panel .pd-empty');
          out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
          out.sheetHscroll = !!sheet && sheet.scrollWidth > sheet.clientWidth + 1;
          var use = qa('.pd-panel .pd-btn').filter(function(b){ return /Заполнить форму|Fill the form/.test(b.textContent); })[0];
          out.useBtn = !!use;
          if (!use) { res(dump(out)); return; }
          use.click();
          setTimeout(function(){
            var tok = q('[data-help="pf-token"]'), ip = q('[data-help="pf-ip"]');
            out.token = tok ? tok.value : null;
            out.ip = ip ? ip.value : null;
            out.panelClosed = !q('.pd-panel');
            out.toast = /Серийный номер уже вписан/.test(document.body.innerText || '');
            res(dump(out));
          }, 600);
        }, 1400);
      }, 700);
    }, 900);
  }, 1200);
});
"""

JS_EMPTY = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = {};
  setTimeout(function(){
    var later = qa('button').filter(function(b){ return /Позже|Later/.test(b.textContent); })[0];
    if (later) later.click();
    try { setUiLang('ru'); } catch(e) {}
    setTimeout(function(){
      var add = q('[data-help="add-printer"]'); if (add) add.click();
      setTimeout(function(){
        var find = q('[data-help="pf-find"]'); if (find) find.click();
        setTimeout(function(){
          out.panel = !!q('.pd-panel');
          out.notes = qa('.pd-panel .pd-note[role="status"]').map(function(n){ return (n.textContent || '').trim(); });
          out.empty = !!q('.pd-panel .pd-empty');
          res(dump(out));
        }, 1400);
      }, 700);
    }, 900);
  }, 1200);
});
"""

SHOTS = os.environ.get("FM_DISC_SHOTS") or ""
RUNS = (("/ui3", "UI 3.0", ((1600, 1000), (1280, 800), (1024, 640), (853, 533))),
        ("/", "UI 2.0", ((1600, 1000), (853, 533))))


def diag_problems(R):
    d = (R or {}).get("__diag") or {}
    return [x for x in (list(d.get("consoleErrors") or []) + list(d.get("pageErrors") or [])
                        + list(d.get("unhandled") or [])
                        + [w for w in (d.get("consoleWarnings") or []) if "Vue warn" in str(w)])]


if not stage.engine_ready():
    check("0. браузерный движок доступен (без него вид проверить нечем)", False, str(stage.last_diag())[:200])
else:
    try:
        #  1-2. Порты 2021 и 5353 заняты, найден FlashForge.
        S1 = snap(ports_closed=(2021, 5353), devices=[FF_DEV], received={"порт 1990": 2, "ответ flashforge-19000": 1})
        stage.set_api({"/api/printers": [], "/api/printer-discovery/start": S1, "/api/printer-discovery": S1})
        for path, label, sizes in RUNS:
            for (w, h) in sizes:
                tag = "%s %dx%d" % (label, w, h)
                shot = os.path.join(SHOTS, "disc_%s_%dx%d.png" % ("ui3" if "ui3" in path else "ui2", w, h)) if SHOTS else None
                R = stage.run(JS, window_size=(w, h), path=path, settle_ms=2200, shot_path=shot)
                if not R:
                    check("1. %s: сценарий выполнился" % tag, False, str(stage.last_diag())[:300])
                    continue
                notes = R.get("notes") or []
                texts = [n.get("text") or "" for n in notes]
                check("1. %s: форма открыта, поиск показал панель" % tag,
                      R.get("addBtn") and R.get("findBtn") and R.get("panel"), R)
                check("2. %s: занятые порты сказаны словами — 2021 (слайсер Bambu) и 5353 (Klipper/Creality)" % tag,
                      len(texts) == 2 and texts[0].startswith("Порт 2021 занят другой программой")
                      and "(обычно Bambu Studio или OrcaSlicer)" in texts[0] and texts[1].startswith("Порт 5353 занят"), texts)
                check("3. %s: строки внутри панели, текст не обрезан, страница и форма не уезжают вбок" % tag,
                      bool(notes) and all(n.get("inside") and n.get("visible") and not n.get("clipped") for n in notes)
                      and not R.get("hscroll") and not R.get("sheetHscroll"), (notes, R.get("hscroll"), R.get("sheetHscroll")))
                check("4. %s: найденный FlashForge — серийник уже в поле кода с двоеточием, адрес вписан" % tag,
                      R.get("useBtn") and R.get("token") == "SNFF0001:" and R.get("ip") == "192.0.2.60"
                      and R.get("panelClosed") and R.get("toast"), {k: R.get(k) for k in ("useBtn", "token", "ip", "panelClosed", "toast")})
                probs = diag_problems(R)
                check("5. %s: консоль браузера чистая" % tag, not probs, probs[:3])

        #  3. Ничего не найдено, но устройства на вопросы отвечали.
        S2 = snap(received={"порт 5353": 3, "ответ ssdp-msearch": 2})
        stage.set_api({"/api/printers": [], "/api/printer-discovery/start": S2, "/api/printer-discovery": S2})
        R2 = stage.run(JS_EMPTY, window_size=(1280, 800), path="/ui3", settle_ms=2200)
        check("6. найдено 0, а устройства отвечали (2) — об этом сказано, и общее «ни один не объявился» на месте",
              bool(R2) and R2.get("notes") == ["Устройства в сети отвечали (2), но ни одно не похоже на принтер."]
              and R2.get("empty"), R2)
        #  Свои вопросы, вернувшиеся на слушатели портов, — не ответы сети.
        S3 = snap(received={"порт 5353": 5, "порт 2021": 3})
        stage.set_api({"/api/printers": [], "/api/printer-discovery/start": S3, "/api/printer-discovery": S3})
        R3 = stage.run(JS_EMPTY, window_size=(1280, 800), path="/ui3", settle_ms=2200)
        check("7. пакеты только на слушатели портов (это могут быть наши же вопросы) — строки «отвечали» нет",
              bool(R3) and R3.get("notes") == [] and R3.get("empty"), R3)
        check("8. консоль браузера чистая (пустой поиск)", not diag_problems(R2) and not diag_problems(R3),
              (diag_problems(R2) + diag_problems(R3))[:3])
    finally:
        stage.set_api(None)

print()
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: FAIL=%d" % len(fails))
sys.exit(1 if fails else 0)
