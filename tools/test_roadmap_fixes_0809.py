# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Раздел карты «Исправления и доработка на 08.09.2026»: R-103 … R-107.

Набор растёт вместе с разделом: у каждого пункта своя часть — сначала то, что закреплено в
файлах (устройство кода), затем исполнение на настоящей странице в headless-браузере.

  R-103  пресеты прогрева правятся оператором и хранятся на сервере — одни на всю ферму;
  R-104  преднагрев термокамеры у принтеров, где она есть (Bambu X1E/H2-серия/X2D, Creality K2 Plus/Pro);
  R-105  кнопка-папка «Открыть расположение файла» стоит ПЕРЕД именем файла и детали;
  R-107  дашборд фермы: вид «Дашборд», адаптивная сетка на 25+ принтеров, порядок по важности,
         пульт справа только после выбора принтера;

БЕЗОПАСНОСТЬ: стенд с синтетическими ответами; ни сети, ни принтеров, ни рабочей базы.

Запуск:  python tools/test_roadmap_fixes_0809.py
"""
import importlib.util
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location("fm_stage_0809", os.path.join(ROOT, "tools", "_fm_ui_stage.py"))
stage = importlib.util.module_from_spec(_s)
_s.loader.exec_module(stage)

SENTINEL = "ROADMAP_FIXES_0809_SENTINEL"
PASS = FAIL = 0
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
HTML = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
CSS = io.open(os.path.join(ROOT, "web", "ui3", "ui3.css"), encoding="utf-8").read()
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


# ════════════════════════════════════════════════════════════════════════════
print("--- R-105: кнопка-папка перед именем (устройство кода) ---")
_btn_pr = 'class="ui3-reveal" data-help="pr-reveal"'
_name_pr = 'class="pvpname" data-help="col-name"'
_btn_qt = 'class="ui3-reveal" data-help="qt-reveal"'
_name_qt = 'class="pvpname" data-help="qt-name"'
check("1. в проектах кнопка стоит перед именем детали",
      _btn_pr in HTML and _name_pr in HTML and HTML.index(_btn_pr) < HTML.index(_name_pr))
check("2. в задачах кнопка стоит перед именем файла",
      _btn_qt in HTML and _name_qt in HTML and HTML.index(_btn_qt) < HTML.index(_name_qt))
check("3. отступ у кнопки теперь справа, а не слева",
      "margin-right: 6px" in CSS.split("html.ui3-mode .ui3-reveal {", 1)[1][:200]
      and "margin-left: 6px" not in CSS.split("html.ui3-mode .ui3-reveal {", 1)[1][:200])

# ════════════════════════════════════════════════════════════════════════════
print()
print("--- R-104: термокамера (устройство кода) ---")
POL = io.open(os.path.join(ROOT, "app", "printer_command_policy.py"), encoding="utf-8").read()
DEMO = io.open(os.path.join(ROOT, "app", "demo_printer.py"), encoding="utf-8").read()
check("8. действие «chamber» в закрытом списке политики, только bambu/klipper/demo",
      '"chamber":  {"param": "temp_c", "min": CHAMBER_MIN_C, "max": CHAMBER_MAX_C, "types": (T_KLIPPER, T_BAMBU, T_DEMO)}' in POL
      and "CHAMBER_MIN_C, CHAMBER_MAX_C = 0, 65" in POL)
check("9. Bambu получает команду протокола set_ctt (как шлёт слайсер), а не G-code",
      '"command": "set_ctt", "ctt_val": int(_tc)' in SRV)
check("10. Klipper получает M141 (макрос камеры K2 Plus/Pro)", 'lines = [f"M141 S{t}"]' in POL)
check("11. Bambu: разбор температуры камеры в обоих форматах отчёта",
      '_packed & 0xFFFF, (_packed >> 16) & 0xFFFF' in SRV and 'd.get("chamber_temper")' in SRV and 'd.get("ctt")' in SRV)
check("12. Klipper: нагреватель камеры запрашивается у Moonraker и попадает в состояние",
      "heater_generic%20chamber_heater" in SRV and 'st.get("heater_generic chamber_heater")' in SRV
      and '"chamber_heater": bool(isinstance(_chh, dict) and _chh)' in SRV)
check("13. признак нагрева камеры отдаётся в списке принтеров по модели",
      '"chamber_heater": _chamber_heater_by_model(r)' in SRV
      and all(k in SRV for k in ('"bambulabx1e"', '"bambulabh2d"', '"bambulabh2s"', '"crealityk2plus"')))
check("14. датчик без нагревателя (X1C, P1S, P2S) в перечень не входит",
      '"bambulabx1carbon"' not in SRV and '"bambulabp1s"' not in SRV and '"bambulabp2s"' not in SRV)
check("15. виртуальный принтер умеет камеру", '("bed", "nozzle", "chamber")' in DEMO and '"chamber_heater": True' in DEMO)
check("16. в пульте есть строка «Камера», показанная только при нагреве камеры",
      'v-if="ui3PpChamber" class="ui3-pp-temp"' in HTML and 'data-help="pp-chamber"' in HTML
      and "sendCmd('chamber', tempChamber)" in HTML)
check("17. «Остыть» гасит и камеру", "ui3TempPreset({ n: 0, b: 0, c: 0 })" in HTML)
check("18. пресет с камерой шлёт её только принтеру с нагревом камеры",
      "if (ui3PpChamber.value && pr.c !== undefined" in APPJS)

# ════════════════════════════════════════════════════════════════════════════
print()
print("--- R-103: пресеты прогрева (устройство кода) ---")
check("22. пресеты хранятся на сервере отдельным ключом настроек фермы с проверкой формы",
      '_FARM_PRESETS_KEY = "farm_preheat_presets"' in SRV and "def _farm_presets_validate(raw):" in SRV
      and 'out["preheat_presets"] = _presets' in SRV)
check("23. пределы пресета совпадают с политикой команд (сопло 350, стол 120, камера 65)",
      '_PRESET_LIMITS = {"n": (0, 350), "b": (0, 120), "c": (0, 65)}' in SRV)
check("24. интерфейс берёт пресеты с сервера вместе с настройками фермы",
      "if (Array.isArray(st.preheat_presets)) ui3PresetsFromServer(st.preheat_presets);" in APPJS)
check("25. редактор в пульте: карандаш, строки, добавить/убрать/встроенные/сохранить",
      'data-help="pp-presets-edit"' in HTML and 'data-help="pp-presets-editor"' in HTML
      and "ui3PresetAdd" in HTML and "ui3PresetRemove(i)" in HTML and "ui3PresetReset" in HTML and "ui3PresetSave" in HTML)
check("26. сохранение шлёт на сервер ТОЛЬКО пресеты (а не все настройки фермы)",
      "body: JSON.stringify({ preheat_presets: list })" in APPJS)
check("27. встроенные три остаются умолчанием", "_UI3_PRESETS_DEFAULT = [{ name: 'PLA', n: 220, b: 60, c: null }" in APPJS)

# ════════════════════════════════════════════════════════════════════════════
print()
print("--- исполнение: настоящая страница ---")
PR = [{"id": "k1", "name": "K2_Plus_01", "type": "klipper", "model": "Creality K2 Plus",
       "ip": "10.0.0.71", "port": 7125, "serial": "FIXTURE_K1", "access_code": "", "chamber_heater": True},
      {"id": "b1", "name": "X1C-01", "type": "bambu", "model": "Bambu Lab X1 Carbon",
       "ip": "10.0.0.11", "port": 8883, "serial": "FIXTURE_B1", "access_code": "", "chamber_heater": False}]
_PRJ = {"id": "P1", "name": "Заказ 17", "due_date": "", "is_archived": 0, "created_at": "2026-09-30",
        "required_total": 36, "printed_total": 7, "parts_count": 3, "files_count": 1}
_PARTS = {"project": _PRJ, "parts": [
    {"part_id": "ppA", "part_name": "А_в_работе", "required_qty": 12, "printed_qty": 3, "status": "in_progress",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": [], "plates": [{"filename": "korpus.gcode.3mf", "on_plate_qty": 1, "file_id": "f1"}], "order_idx": 0},
    {"part_id": "ppB", "part_name": "Б_готово", "required_qty": 2, "printed_qty": 2, "status": "done",
     "notes": "", "rework_qty": 0, "rework_done": 0, "live_printers": [], "plates": [{"filename": "korpus.gcode.3mf", "on_plate_qty": 1, "file_id": "f1"}], "order_idx": 1}]}
_TREE = {"project": _PRJ, "nodes": [{"id": "f1", "name": "korpus.gcode.3mf", "type": "file", "is_printable": True, "compatible_pids": ["b1"],
                                     "target_model": "Bambu Lab X1 Carbon", "filename": "korpus.gcode.3mf", "file_id": "f1",
                                     "children": [{"id": "c%d" % i, "name": n, "qty": 1} for i, n in enumerate(["А_в_работе", "Б_готово"])]}]}
ST = [{"filename": "Куб_01.gcode", "status": "ready", "printer_id": "", "required_qty": 10, "printed_qty": 1,
       "target_nozzles": 0.4, "target_model": "", "is_printable": True, "notes": "", "src_path": "C:/tmp/Куб_01.gcode",
       "linked": False, "missing": False, "project_id": "", "project_name": "", "project_sync": False,
       "compatible_pids": ["k1"], "parts": [], "part_total": 0}]
LIVE = {"k1": {"status": "IDLE", "nozzle_count": 1, "chamber_heater": True, "chamber_temp": 31, "chamber_target": 45},
        "b1": {"status": "RUNNING", "percent": 40, "remaining_time": 60, "nozzle_count": 1, "file_name": "korpus"}}

JS = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  function L(el){ return el ? Math.round(el.getBoundingClientRect().left) : null; }
  var tab = function(re){ return qa('.ui3-rtabs .fm-seg-b').filter(function(b){ return re.test(b.textContent); })[0]; };
  var out = {};
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      click(tab(/Задачи/));
      setTimeout(function(){
        //  Имя берём ИЗ СТРОКИ (.pvpname): такой же data-help стоит и у заголовка столбца.
        var n = q('.pvpname[data-help="qt-name"]'), b = n && n.parentElement ? n.parentElement.querySelector('[data-help="qt-reveal"]') : null;
        out.qtBtn = L(b); out.qtName = L(n);
        out.qtSameLine = (b && n) ? Math.abs(b.getBoundingClientRect().top - n.getBoundingClientRect().top) < 12 : null;
        click(tab(/Проекты/));
        setTimeout(function(){
          click(q('[data-help="project-card"]'));
          setTimeout(function(){
            var pn = q('.pvpname[data-help="col-name"]'), pb = pn && pn.parentElement ? pn.parentElement.querySelector('[data-help="pr-reveal"]') : null;
            out.prBtn = L(pb); out.prName = L(pn);
            out.prSameLine = (pb && pn) ? Math.abs(pb.getBoundingClientRect().top - pn.getBoundingClientRect().top) < 12 : null;
            out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
            //  R-104: пульт K2 Plus — строка «Камера» есть; пульт X1C — её нет.
            var k = qa('.printer-card').filter(function(c){ return /K2_Plus_01/.test(c.textContent); })[0];
            click(k);
            setTimeout(function(){
              var row = q('[data-help="pp-chamber"]');
              out.k2Chamber = !!row;
              out.k2ChamberTxt = row ? row.textContent.replace(/\s+/g, ' ').trim() : '';
              out.k2ChamberInput = !!(row && row.querySelector('input[type="number"]'));
              var rb = q('[data-help="pp-bed"]');
              out.k2ChamberBelowBed = !!(row && rb) && row.getBoundingClientRect().top > rb.getBoundingClientRect().top;
              //  R-103: пресеты с сервера в пульте K2 Plus (с камерой) — три, «Нейлон» с камерой 60
              var pb = qa('[data-help="pp-presets"] button').map(function(b){ return b.textContent.replace(/\s+/g, ' ').trim(); });
              out.presets = pb;
              var pen = q('[data-help="pp-presets-edit"]'); out.pen = !!pen;
              if (pen) click(pen);
              setTimeout(function(){
                var ed = q('[data-help="pp-presets-editor"]');
                out.editor = !!ed;
                out.editRows = ed ? ed.querySelectorAll('.ui3-pp-pedit-row:not(.head)').length : 0;
                var add = ed ? [].slice.call(ed.querySelectorAll('button')).filter(function(b){ return /Добавить|Add/.test(b.textContent); })[0] : null;
                if (add) click(add);
                setTimeout(function(){
                  out.editRowsAfterAdd = ed ? ed.querySelectorAll('.ui3-pp-pedit-row:not(.head)').length : 0;
                  var cancel = ed ? [].slice.call(ed.querySelectorAll('button')).filter(function(b){ return /Отмена|Cancel/.test(b.textContent); })[0] : null;
                  if (cancel) click(cancel);
                  setTimeout(function(){
                    out.editorClosed = !q('[data-help="pp-presets-editor"]');
                    out.presetsBack = qa('[data-help="pp-presets"] button').length;
                    var x = qa('.printer-card').filter(function(c){ return /X1C-01/.test(c.textContent); })[0];
                    click(x);
                    setTimeout(function(){
                      out.x1cChamber = !!q('[data-help="pp-chamber"]');
                      out.x1cBed = !!q('[data-help="pp-bed"]');
                      //  у X1C камеры нет — в подписи пресета «Нейлон» третьего числа быть не должно
                      out.x1cPresets = qa('[data-help="pp-presets"] button').map(function(b){ return b.textContent.replace(/\s+/g, ' ').trim(); });
                      res(dump(out));
                    }, 900);
                  }, 500);
                }, 500);
              }, 700);
            }, 900);
          }, 1800);
        }, 700);
      }, 700);
    }, 1700);
  }, 1500);
});
"""

if not stage.engine_ready():
    check("4. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR, "/api/staging": ST, "/api/projects2": [_PRJ],
                   "/api/projects2/P1/partsview": _PARTS, "/api/projects2/P1/tree": _TREE,
                   "/api/queue-wait": {"ok": True, "allowed": [], "items": []},
                   #  R-103: пресеты фермы приходят с сервера
                   "/api/farm-settings": {"ok": True, "settings": {"preheat_presets": [
                       {"name": "PLA", "n": 215, "b": 55, "c": None}, {"name": "ASA", "n": 255, "b": 95, "c": 55},
                       {"name": "Нейлон", "n": 270, "b": 90, "c": 60}]}}})
    stage.set_live(LIVE)
    R = stage.run(JS, window_size=(1600, 900), settle_ms=9000, path="/ui3")
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R:
        check("4. страница отработала", False, str(stage.last_diag())[:200])
    else:
        check("4. задачи: кнопка-папка стоит ЛЕВЕЕ имени файла и на одной строке с ним",
              R.get("qtBtn") is not None and R.get("qtName") is not None and R["qtBtn"] < R["qtName"]
              and R.get("qtSameLine") is True, (R.get("qtBtn"), R.get("qtName"), R.get("qtSameLine")))
        check("5. проекты: кнопка-папка стоит ЛЕВЕЕ имени детали и на одной строке с ним",
              R.get("prBtn") is not None and R.get("prName") is not None and R["prBtn"] < R["prName"]
              and R.get("prSameLine") is True, (R.get("prBtn"), R.get("prName"), R.get("prSameLine")))
        check("6. без горизонтальной прокрутки", R.get("hscroll") is False, R.get("hscroll"))
        check("19. R-104: у K2 Plus в пульте есть строка «Камера» с полем ввода, ниже стола",
              R.get("k2Chamber") is True and R.get("k2ChamberInput") is True and R.get("k2ChamberBelowBed") is True,
              (R.get("k2Chamber"), R.get("k2ChamberInput"), R.get("k2ChamberBelowBed")))
        check("20. R-104: строка показывает текущую и целевую температуру камеры (31° → 45°)",
              "31°" in (R.get("k2ChamberTxt") or "") and "45°" in (R.get("k2ChamberTxt") or ""), R.get("k2ChamberTxt"))
        _pr = R.get("presets") or []
        check("28. R-103: пульт показывает пресеты С СЕРВЕРА (не встроенные): PLA 215/55, ASA 255/95/55, Нейлон 270/90/60",
              any(p.startswith("PLA") and "215/55" in p for p in _pr) and any("ASA" in p and "255/95/55" in p for p in _pr)
              and any("Нейлон" in p and "270/90/60" in p for p in _pr) and not any("220/60" in p for p in _pr), _pr)
        check("29. R-103: карандаш открывает редактор с тремя строками, «Добавить» даёт четвёртую, «Отмена» закрывает",
              R.get("pen") is True and R.get("editor") is True and R.get("editRows") == 3
              and R.get("editRowsAfterAdd") == 4 and R.get("editorClosed") is True and (R.get("presetsBack") or 0) >= 5,
              (R.get("pen"), R.get("editor"), R.get("editRows"), R.get("editRowsAfterAdd"), R.get("editorClosed"), R.get("presetsBack")))
        _xp = R.get("x1cPresets") or []
        check("29б. R-103: у принтера без камеры третье число пресета не показывается",
              any("Нейлон" in p and "270/90" in p and "/60" not in p for p in _xp), _xp)
        check("21. R-104: у X1C (датчик без нагревателя) строки «Камера» нет, стол на месте",
              R.get("x1cChamber") is False and R.get("x1cBed") is True, (R.get("x1cChamber"), R.get("x1cBed")))
        _d = R.get("__diag") or {}
        check("7. консоль чистая",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled")),
              (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled") or [])[:2])

# ════════════════════════════════════════════════════════════════════════════
print()
print("--- R-107: дашборд фермы (устройство кода) ---")
ICONS = io.open(os.path.join(ROOT, "web", "design", "icons.js"), encoding="utf-8").read()
check("30. вид «Дашборд» есть в переключателе видов 3.0 со своим значком",
      "{ id: 'dash', title: 'Dashboard view', icon: 'view-dash' }" in APPJS and "'view-dash':" in ICONS)
check("31. сетка адаптивная: auto-fill без привязки к числу столбцов",
      "grid-template-columns: repeat(auto-fill, minmax(142px, 1fr))" in CSS)
check("32. пока принтер не выбран — правая половина скрыта и места не занимает",
      "html.ui3-mode.ui3-dash-full .projects-pane { display: none !important; }" in CSS
      and "html.ui3-mode.ui3-dash-full .left-col { width: auto !important; flex: 1 1 auto !important;" in CSS)
#  12.10.2026: «Занят» (калибровка, незнакомое состояние прошивки) — ступенью печатающих, не «Свободен».
check("33. порядок по умолчанию — по важности: ошибка, пауза, завершил, печатает/занят, свободен, не в сети",
      "const _DASH_RANK = { error: 0, paused: 1, done: 2, print: 3, busy: 3, idle: 4, offline: 5 };" in APPJS
      and "if (ra !== rb) return ra - rb;" in APPJS)
check("34. содержимое карточки зависит от состояния (печатает/завершил/ошибка-пауза/не в сети/свободен)",
      HTML.count("dashState(p.id)===") >= 5 and 'data-help="pc-dash"' in HTML)
check("35. строки дашборда — через общий словарь переводов",
      all(('"%s":' % k) in APPJS for k in ("Dashboard view", "Print finished", "Clear the plate", "Free", "Paused", "Offline", "Preparing")))

print()
print("--- R-107: исполнение — ферма из 26 принтеров ---")
DPR = [{"id": "p%02d" % i, "name": "P%02d" % i, "type": "bambu" if i % 3 else "klipper",
        "model": "Bambu Lab P1S" if i % 3 else "Creality K2 Plus", "ip": "10.0.0.%d" % (100 + i), "port": 8883,
        "serial": "FIXTURE_%02d" % i, "access_code": "", "chamber_heater": (i % 3 == 0)} for i in range(1, 27)]
DLIVE = {
    "p01": {"status": "FAILED", "percent": 30, "file_name": "bracket.gcode", "nozzle_count": 1, "nozzle_temp": 40, "bed_temp": 30},
    "p02": {"status": "PAUSED", "percent": 40, "remaining_time": 50, "file_name": "cover.gcode", "nozzle_count": 1, "nozzle_temp": 200, "bed_temp": 60},
    "p03": {"status": "FINISH", "percent": 100, "file_name": "lid.gcode", "nozzle_count": 1, "nozzle_temp": 90, "bed_temp": 40},
    "p04": {"status": "RUNNING", "percent": 20, "remaining_time": 12, "file_name": "base.gcode", "nozzle_count": 1, "nozzle_temp": 220, "bed_temp": 60, "nozzle_target": 220, "bed_target": 60},
    "p05": {"status": "RUNNING", "percent": 90, "remaining_time": 5, "file_name": "clip.gcode", "nozzle_count": 1, "nozzle_temp": 220, "bed_temp": 60, "nozzle_target": 220, "bed_target": 60},
    "p06": {"status": "RUNNING", "percent": 5, "remaining_time": 90, "file_name": "frame.gcode", "nozzle_count": 1, "nozzle_temp": 220, "bed_temp": 60, "nozzle_target": 220, "bed_target": 60,
            "chamber_heater": True, "chamber_temp": 44, "chamber_target": 50},
}
for i in range(7, 21):
    DLIVE["p%02d" % i] = {"status": "IDLE", "percent": 0, "nozzle_count": 1, "nozzle_temp": 25, "bed_temp": 25}
#  p21…p26 — без телеметрии: не в сети.

JSD = r"""
return new Promise(function(res){
  function q(s){ return document.querySelector(s); }
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var out = {};
  setTimeout(function(){
    try { var l = byText('button', ['Позже','Later']); if (l) click(l); setUiLang('ru'); } catch (e) { out.e0 = String(e); }
    setTimeout(function(){
      var de = document.documentElement, W = de.clientWidth;
      var cards = qa('.printer-card.pc-dashcard');
      out.cards = cards.length;
      out.dashClass = de.classList.contains('ui3-dash') && de.classList.contains('ui3-dash-full');
      var pp = q('.projects-pane'); out.rightHidden = !pp || pp.offsetParent === null;
      var lc = q('.left-col'); out.leftW = lc ? Math.round(lc.getBoundingClientRect().width) : 0; out.W = W;
      var tops = cards.map(function(c){ return Math.round(c.getBoundingClientRect().top); });
      var first = tops.length ? Math.min.apply(null, tops) : 0;
      out.cols = tops.filter(function(t){ return Math.abs(t - first) < 3; }).length;
      out.minW = cards.length ? Math.round(Math.min.apply(null, cards.map(function(c){ return c.getBoundingClientRect().width; }))) : 0;
      out.order = cards.map(function(c){ var n = c.querySelector('.pcd-name'); return n ? n.textContent.trim() : '?'; });
      out.states = cards.map(function(c){ var m = (c.className.match(/pcd-([a-z]+)/) || [])[1]; return m || '?'; });
      out.p06chamber = !!qa('.printer-card.pc-dashcard').filter(function(c){ return /P06/.test(c.textContent); })[0]
        && /44°/.test(qa('.printer-card.pc-dashcard').filter(function(c){ return /P06/.test(c.textContent); })[0].textContent);
      out.p03msg = (function(){ var c = qa('.printer-card.pc-dashcard').filter(function(c){ return /P03/.test(c.textContent); })[0]; return c ? c.textContent.replace(/\s+/g,' ') : ''; })();
      out.hscroll = de.scrollWidth > de.clientWidth + 1;
      var over = cards.filter(function(c){ var r = c.getBoundingClientRect(); return r.right > W + 1 || r.left < -1; }).length;
      out.overflow = over;
      //  выбор принтера: пульт справа, сетка ужимается; закрытие — снова полный обзор
      var target = cards.filter(function(c){ return /P05/.test(c.textContent); })[0];
      click(target);
      setTimeout(function(){
        out.ppShown = !!(q('.ui3-pp') && q('.ui3-pp').offsetParent !== null);
        out.leftWpp = lc ? Math.round(lc.getBoundingClientRect().width) : 0;
        out.cardsAlive = qa('.printer-card.pc-dashcard').length;
        var x = q('[data-help="pp-close"]'); if (x) click(x);
        setTimeout(function(){
          out.ppGone = !q('.ui3-pp') || q('.ui3-pp').offsetParent === null;
          out.leftWback = lc ? Math.round(lc.getBoundingClientRect().width) : 0;
          out.rightHiddenBack = !q('.projects-pane') || q('.projects-pane').offsetParent === null;
          res(dump(out));
        }, 900);
      }, 1200);
    }, 1800);
  }, 1500);
});
"""
EXPECT_ORDER = ["P01", "P02", "P03", "P05", "P04", "P06"] + ["P%02d" % i for i in range(7, 21)] + ["P%02d" % i for i in range(21, 27)]
if not stage.engine_ready():
    check("36. браузерный движок доступен", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": DPR, "/api/queue-wait": {"ok": True, "allowed": [], "items": []}})
    stage.set_live(DLIVE)
    for (w, h, want_cols) in ((1280, 800, 6), (1600, 900, 7), (1920, 1080, 9)):
        R2 = stage.run(JSD, window_size=(w, h), settle_ms=8000, path="/ui3?ls=farm_view:dash")
        if not R2:
            check("36. дашборд %dpx: страница отработала" % w, False, str(stage.last_diag())[:200])
            continue
        check("36. дашборд %dpx: 26 карточек, правая половина скрыта, колонка во всю ширину" % w,
              R2.get("cards") == 26 and R2.get("dashClass") is True and R2.get("rightHidden") is True
              and R2.get("leftW", 0) >= 0.9 * R2.get("W", 1), (R2.get("cards"), R2.get("dashClass"), R2.get("rightHidden"), R2.get("leftW"), R2.get("W")))
        check("37. дашборд %dpx: столбцов %d (ожидалось около %d), карточка не уже 170 экранных точек" % (w, R2.get("cols", 0), want_cols),
              abs((R2.get("cols") or 0) - want_cols) <= 1 and (R2.get("minW") or 0) >= 170, (R2.get("cols"), R2.get("minW")))
        check("38. дашборд %dpx: без горизонтальной прокрутки и карточек за краем" % w,
              R2.get("hscroll") is False and R2.get("overflow") == 0, (R2.get("hscroll"), R2.get("overflow")))
        if w == 1600:
            check("39. порядок по важности: ошибка, пауза, завершил, печатающие по ближайшему концу, свободные, не в сети",
                  R2.get("order") == EXPECT_ORDER, R2.get("order"))
            check("40. состояния карточек распознаны верно",
                  R2.get("states", [])[:6] == ["error", "paused", "done", "print", "print", "print"]
                  and set(R2.get("states", [])[6:20]) == {"idle"} and set(R2.get("states", [])[20:]) == {"offline"}, R2.get("states"))
            check("41. завершивший печать зовёт освободить стол", "Освободите стол" in (R2.get("p03msg") or ""), R2.get("p03msg"))
            check("42. у принтера с камерой на карточке видна температура камеры", R2.get("p06chamber") is True)
            check("43. выбор принтера открывает пульт справа, сетка ужимается, остальные карточки живы",
                  R2.get("ppShown") is True and (R2.get("leftWpp") or 0) < 0.6 * R2.get("W", 1) and R2.get("cardsAlive") == 26,
                  (R2.get("ppShown"), R2.get("leftWpp"), R2.get("W"), R2.get("cardsAlive")))
            check("44. закрытие пульта возвращает полный обзор",
                  R2.get("ppGone") is True and (R2.get("leftWback") or 0) >= 0.9 * R2.get("W", 1) and R2.get("rightHiddenBack") is True,
                  (R2.get("ppGone"), R2.get("leftWback"), R2.get("rightHiddenBack")))
        _d2 = R2.get("__diag") or {}
        check("45. дашборд %dpx: консоль чистая" % w,
              not (_d2.get("consoleErrors") or _d2.get("pageErrors") or _d2.get("unhandled")),
              (_d2.get("consoleErrors") or _d2.get("pageErrors") or _d2.get("unhandled") or [])[:2])
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
