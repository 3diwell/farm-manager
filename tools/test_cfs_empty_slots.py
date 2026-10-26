# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Пустой слот CFS не выдаётся за заполненный (Alpha 2.942).
#
# ЗАЧЕМ ЭТОТ НАБОР ЕСТЬ. Владелец на живой ферме: «есть слоты, в которых показывает, что есть
# филамент, а по факту там пусто». Так и было. Отчёт с его Creality K2 Plus от 02.09.2026:
# в T1A и T1C стоит material_type "000003" и цвет "09ea7ae", а remain_len у них "0" — катушка
# кончилась или вынута, а МЕТКА осталась. В отчёте от 26.08.2026 у тех же слотов материала не
# было вовсе, значит метки появляются и остаются.
#
# Разбор смотрел ТОЛЬКО на материал и цвет, поэтому:
#   * карточка рисовала такой слот полным и цветным — то, что владелец и видел;
#   * слот попадал в кандидаты на «заправленный»: три одинаковых кандидата вместо одного,
#     заправленный слот не определялся, и филамент НЕ СПИСЫВАЛСЯ вовсе.
#
# ПРАВИЛО, которое здесь закрепляется: остаток ИЗВЕСТЕН и равен нулю — филамента нет.
# Остаток НЕИЗВЕСТЕН — слот считается заполненным, как раньше: отсутствие данных не
# доказывает пустоту. Второе так же важно, как первое, и проверяется отдельно.
#
# Ни сервера, ни сети, ни принтера: чистые функции разбора + настоящая diagnose.
#
# Запуск:  python tools/test_cfs_empty_slots.py      (0 = всё в порядке)
# ============================================================================
import copy
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from app.creality_cfs import parse                      # noqa: E402
from app.diagnostics import diagnose                    # noqa: E402
from app.klipper_contract_probe import (_cfs_section, _slot_selection_section,  # noqa: E402
                                        MACROS_OF_INTEREST)

SENTINEL = "CFS_EMPTY_SLOTS_SENTINEL_2_942"

#  ФИКСТУРА — СОСТОЯНИЕ ЖИВОГО ПРИНТЕРА ВЛАДЕЛЬЦА (отчёт K2 Plus 02.09.2026).
#  Серийный номер короба заменён на выдуманный: настоящих идентификаторов устройств в
#  отслеживаемых файлах быть не должно.
BOX = {
    "filament": 1, "state": "connect", "auto_refill": 1, "enable": 1, "filament_useup": 0,
    "same_material": [["000003", "09ea7ae", ["09ea7ae"], "PETG"]],
    "map": {"T1A": "T1A", "T1B": "T1B", "T1C": "T1C", "T1D": "T1D"},
    "T1": {"state": "connect", "filament": "None", "temperature": "30",
           "dry_and_humidity": "35", "filament_detected": "None", "version": "1.4.2",
           "sn": "FIXTURE_SN_0003", "mode": "0",
           "vender": ["none", "unknown", "none", "none"],
           "remain_len": ["0", "100", "0", "0"],
           "color_value": ["09ea7ae", "09ea7ae", "09ea7ae", "-1"],
           "material_type": ["000003", "000003", "000003", "-1"],
           "change_color_num": [-1, "0", -1, -1], "slot_rfid_scrap": "0"},
    "T2": {"state": "None"}, "T3": {"state": "None"}, "T4": {"state": "None"},
}
RACK = {"vender": "-1", "color_value": "09ea7ae", "material_type": "000003",
        "remain_material_color": "09ea7ae", "remain_material_type": "000003",
        "remain_material_velocity": 400}
PRINTER = {"id": "k2", "name": "K2 Plus", "type": "klipper", "model": "Creality K2 Plus",
           "ip": "192.0.2.10", "port": ""}
CTRL = {"control": {"reachable": True, "latency_ms": 11}, "file": None}

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def by_label(res, label):
    return next(t for t in res["trays"] if t["label"] == label)


print("--- 1. Состояние живого принтера владельца разбирается верно ---")
R = parse(BOX, RACK)
a, b, c, dd = (by_label(R, x) for x in ("T1A", "T1B", "T1C", "T1D"))
check("1. КОРЕНЬ ЖАЛОБЫ: слот с меткой, но без остатка — пустой (T1A)",
      a["type"] == "Empty" and a["color"] == "#3f3f46", (a["type"], a["color"]))
check("2. то же для T1C", c["type"] == "Empty" and c["color"] == "#3f3f46", (c["type"], c["color"]))
check("3. слот с филаментом остался заполненным (T1B)",
      b["type"] == "PETG" and b["percent"] == 100, (b["type"], b["percent"]))
check("4. у опустевшего слота помечено, что метка осталась",
      a["spent"] is True and a["declared"] == "PETG" and c["spent"] is True,
      (a.get("spent"), a.get("declared")))
check("5. просто пустой слот не помечается «метка осталась» (T1D)",
      dd["type"] == "Empty" and dd["spent"] is False, (dd["type"], dd.get("spent")))
check("6. у опустевшего слота не остаётся кода материала — по нему не сматчиться",
      a["code"] == "" and c["code"] == "", (a["code"], c["code"]))

print("--- 2. Заправленный слот теперь определяется, и списание оживает ---")
check("7. кандидат ровно один", R["now_candidates"] == [1], R["now_candidates"])
check("8. заправленным назван T1B", R["now"] == 1 and by_label(R, "T1B")["index"] == 1, R["now"])

print("--- 3. Отсутствие данных НЕ считается пустотой ---")
#  Тот же короб, но принтер не сообщил остаток вовсе. Пустоту выдумывать нельзя.
NO_REM = copy.deepcopy(BOX)
NO_REM["T1"]["remain_len"] = ["-1", "-1", "-1", "-1"]
R2 = parse(NO_REM, RACK)
check("9. без остатка слоты остаются заполненными",
      [t["type"] for t in R2["trays"]][:3] == ["PETG", "PETG", "PETG"],
      [t["type"] for t in R2["trays"]])
check("10. и тогда честное «не знаю» сохраняется (три кандидата)",
      R2["now"] == -1 and R2["now_candidates"] == [0, 1, 2], (R2["now"], R2["now_candidates"]))
MISSING = copy.deepcopy(BOX)
del MISSING["T1"]["remain_len"]
R3 = parse(MISSING, RACK)
check("11. поля остатка нет вовсе — тоже не пустота",
      by_label(R3, "T1A")["type"] == "PETG" and by_label(R3, "T1A")["spent"] is False)

print("--- 4. Прежнее правило честности не ослаблено ---")
#  Два слота с филаментом и одинаковым материалом — заправленный по-прежнему не утверждается.
TWO = copy.deepcopy(BOX)
TWO["T1"]["remain_len"] = ["0", "100", "100", "0"]
R4 = parse(TWO, RACK)
check("12. два полных одинаковых слота — по-прежнему «не знаю»",
      R4["now"] == -1 and R4["now_candidates"] == [1, 2], (R4["now"], R4["now_candidates"]))
check("13. и пустой слот с меткой в кандидаты не лезет", 0 not in R4["now_candidates"],
      R4["now_candidates"])

print("--- 5. Отчёт диагностики говорит это словами ---")
st = {"cfs_trays": R["trays"], "cfs_now": R["now"], "cfs_now_candidates": R["now_candidates"]}
rep = diagnose(PRINTER, st, 3, 0, None, CTRL, lang="ru")
cfs = next((x for x in rep["checks"] if x["key"] == "cfs"), None)
check("14. проверка CFS есть в отчёте", cfs is not None, [x["key"] for x in rep["checks"]])
check("15. она зелёная и называет заправленный слот",
      cfs and cfs["status"] == "ok" and "T1B" in cfs["value"], cfs)
check("16. и называет слоты с оставшейся меткой",
      cfs and "T1A" in cfs["value"] and "T1C" in cfs["value"], cfs and cfs["value"])
st2 = {"cfs_trays": R4["trays"], "cfs_now": R4["now"], "cfs_now_candidates": R4["now_candidates"]}
cfs2 = next(x for x in diagnose(PRINTER, st2, 3, 0, None, CTRL, lang="ru")["checks"]
            if x["key"] == "cfs")
check("17. при неоднозначности — внимание и объяснение, а не молчание",
      cfs2["status"] == "warn" and cfs2["advice"] and "не списывается" in cfs2["advice"], cfs2)
cfs_en = next(x for x in diagnose(PRINTER, st2, 3, 0, None, CTRL, lang="en")["checks"]
              if x["key"] == "cfs")
check("18. английский текст есть и говорит о том же",
      "deducted" in (cfs_en["advice"] or ""), cfs_en)
check("19. у принтера без короба проверки CFS нет вовсе",
      not [x for x in diagnose(PRINTER, {}, 3, 0, None, CTRL, lang="ru")["checks"]
           if x["key"] == "cfs"])

print("--- 6. Диагностический отчёт: разбор рядом с сырыми данными ---")
sec = _cfs_section({"status": {"box": BOX, "filament_rack": RACK}})
p = sec.get("parsed") or {}
check("20. в отчёт попал вывод самой программы", bool(p), sec.keys())
check("21. в нём назван заправленный слот", p.get("loaded_slot_label") == "T1B", p.get("loaded_slot_label"))
check("22. и отмечены слоты с оставшейся меткой",
      [s["label"] for s in p.get("slots", []) if s.get("spent_label_left")] == ["T1A", "T1C"],
      [s.get("label") for s in p.get("slots", []) if s.get("spent_label_left")])
#  Глубина описания: вложенный список внутри same_material больше не схлопывается в заглушку.
sm = ((sec.get("objects") or {}).get("box") or {}).get("same_material")
check("23. вложенные списки в отчёте больше не обрезаются заглушкой",
      isinstance(sm, list) and isinstance(sm[0], list) and isinstance(sm[0][2], list), sm)

print("--- 6б. Отчёт отвечает, ЧЕМ на этом принтере выбирается слот ---")
#  Владелец: «при запуске на печать нет выбора ячейки материала». Чтобы такой выбор стал
#  возможен, нужно знать команду. Публичного описания нет — прошивка K2 закрыта, поэтому
#  спрашиваем сам принтер. Слепок ниже — состав его конфигурации по отчёту 02.09.2026.
MACROS_OWNER = {"M8200": {}, "BOX_LOAD_MATERIAL_EXTRUDE_MATERIAL": {}, "BOX_INFO_REFRESH": {}}
BYNAME_OWNER = {
    "M8200": {"exists": True, "parameters": ["I"], "body": {"lines": [], "total_lines": 0}},
    "BOX_LOAD_MATERIAL_EXTRUDE_MATERIAL": {"exists": True, "parameters": ["TNN"],
                                           "body": {"lines": ["BOX_EXTRUDE_MATERIAL {get_tnn}"]}},
    "BOX_INFO_REFRESH": {"exists": True, "parameters": ["ADDR", "NUM"],
                         "body": {"lines": ["BOX_GET_RFID ADDR={params.ADDR}"]}},
}
SS = _slot_selection_section(MACROS_OWNER, {"M8200", "BOX_LOAD_MATERIAL"}, BYNAME_OWNER)
check("23а. раздел про выбор слота есть и разобран", SS.get("status") == "complete", SS.get("status"))
check("23б. ГЛАВНЫЙ ФАКТ: макросов смены инструмента у принтера нет",
      SS.get("tool_change_macros") == [] and SS.get("tool_change_macros_present") is False,
      SS.get("tool_change_macros"))
check("23в. фирменный M8200 найден и назван", SS.get("m8200_present") is True)
check("23г. макросы с параметром, похожим на слот, перечислены",
      [x["macro"] for x in SS.get("macros_with_slot_like_parameter", [])]
      == ["BOX_INFO_REFRESH", "BOX_LOAD_MATERIAL_EXTRUDE_MATERIAL", "M8200"],
      SS.get("macros_with_slot_like_parameter"))
check("23д. вердикт честный: выбирать слот пока нечем",
      SS.get("verdict") == "vendor_macro_only" and "не доказан" in (SS.get("verdict_ru") or ""),
      SS.get("verdict"))
#  А если бы макросы смены инструмента были — вердикт обязан стать другим.
SS2 = _slot_selection_section(dict(MACROS_OWNER, T0={}, T1={}), {"T0", "T1"}, dict(BYNAME_OWNER))
check("23е. с макросами T0/T1 вердикт меняется на «слот задаётся в файле»",
      SS2.get("verdict") == "tool_macros" and SS2.get("tool_change_macros") == ["T0", "T1"],
      (SS2.get("verdict"), SS2.get("tool_change_macros")))
check("23ж. пустая конфигурация не выдаётся за ответ",
      _slot_selection_section({}, set(), {}).get("verdict") == "none_found",
      _slot_selection_section({}, set(), {}).get("verdict"))
check("23з. M8200 и T0…T15 действительно вычитываются отчётом",
      all(n in MACROS_OF_INTEREST for n in ("M8200", "T0", "T15", "BOX_EXTRUDE_MATERIAL")),
      [n for n in ("M8200", "T0", "T15", "BOX_EXTRUDE_MATERIAL") if n not in MACROS_OF_INTEREST])

print("--- 7. НЕ ВАКУУМ: проверка ловит именно прежнее поведение ---")
#  Возвращаем прежнее правило (пустота только по материалу и цвету) и требуем красного.
import app.creality_cfs as cfs_mod                       # noqa: E402

_orig = cfs_mod._parse_units


def _old_rule(box):
    trays, units = _orig(box)
    for t in trays:
        if t.get("spent"):                # прежнее правило остаток не смотрело
            t["type"] = t.get("declared") or "PETG"
            t["code"] = "000003"
            t["color"] = "#9EA7AE"
            t["spent"] = False
    return trays, units


cfs_mod._parse_units = _old_rule
try:
    OLD = parse(BOX, RACK)
    check("24. на прежнем правиле слот T1A выглядел заполненным",
          by_label(OLD, "T1A")["type"] != "Empty", by_label(OLD, "T1A")["type"])
    check("25. и заправленный слот не определялся — списания не было",
          OLD["now"] == -1 and len(OLD["now_candidates"]) == 3,
          (OLD["now"], OLD["now_candidates"]))
finally:
    cfs_mod._parse_units = _orig
check("26. после восстановления разбор снова верный", parse(BOX, RACK)["now"] == 1)

print("--- 8. КАК ЭТО ВЫГЛЯДИТ: настоящая карточка в настоящем браузере ---")
#  Владелец жаловался на ВИД, поэтому вид и проверяется: стенд отдаёт настоящие index.html и
#  app.js, живое состояние приходит тем же путём, что и от сервера (вебсокет стенда).
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage                              # noqa: E402

JS = r"""
return new Promise(function(res){
  //  Ряд CFS показывается только у РАСКРЫТОЙ карточки, поэтому открываем её, как человек:
  //  иначе проверялись бы стили невидимого элемента, а владелец жаловался именно на вид.
  var l = byText('button', ['Позже', 'Later']); if (l) click(l);
  setTimeout(function(){
    var card = document.querySelector('.printer-card'); if (card) click(card);
    setTimeout(function(){
    var out = {};
    var row = document.querySelector('.fm-printers-flex-21');
    var rr = row ? row.getBoundingClientRect() : null;
    out.rowVisible = !!(rr && rr.width > 0 && rr.height > 0);
    //  У самого ряда тоже есть подсказка («CFS: система подачи…»), поэтому берём только
    //  квадраты слотов — их подсказка начинается с названия слота.
    var all = row ? [].slice.call(row.querySelectorAll('span[title]')) : [];
    var cells = all.filter(function(e){ var t = e.getAttribute('title') || '';
        return t.indexOf('Слот') === 0 || t.indexOf('Slot') === 0; });
    out.cells = cells.length;
    out.slots = cells.map(function(el){
      var cs = getComputedStyle(el), r = el.getBoundingClientRect();
      return { title: el.getAttribute('title') || '', opacity: cs.opacity,
               bg: cs.backgroundColor, shadow: cs.boxShadow,
               w: Math.round(r.width), h: Math.round(r.height) };
    });
    res(dump(out));
    }, 1200);
  }, 900);
});
"""

if not stage.engine_ready():
    check("27. браузерный движок доступен (без него вид проверить нечем)", False,
          "нет Edge/Chromium или Node: %s" % stage.last_diag())
else:
    check("27. браузерный движок доступен", True)
    PR = [{"id": "k2", "name": "K2 Plus", "type": "klipper", "model": "Creality K2 Plus",
           "ip": "192.0.2.10", "port": "", "serial": "FIXTURE_SN_0003", "access_code": ""}]
    stage.set_api({"/api/printers": PR})
    stage.set_live({"k2": {"cfs_trays": R["trays"], "cfs_now": R["now"],
                           "cfs_now_candidates": R["now_candidates"],
                           "online": True, "state": "idle"}})
    UI = stage.run(JS, window_size=(1600, 1000), settle_ms=2600)
    stage.set_api(None)
    stage.set_live(None)
    if not UI:
        check("28. карточка принтера с рядом CFS открылась", False, str(stage.last_diag())[:220])
    else:
        check("28. ряд CFS показан: четыре слота", UI.get("cells") == 4, UI.get("cells"))
        check("28а. ряд действительно ВИДЕН на экране, а не только есть в разметке",
              UI.get("rowVisible") is True and all(x.get("w", 0) > 0 and x.get("h", 0) > 0
                                                   for x in (UI.get("slots") or [])),
              (UI.get("rowVisible"), [(x.get("w"), x.get("h")) for x in (UI.get("slots") or [])]))
        sl = UI.get("slots") or []
        if len(sl) == 4:
            a_, b_, c_, d_ = sl
            #  Пустой слот рисуется приглушённым и нейтральным, полный — цветным и непрозрачным.
            check("29. КОРЕНЬ ЖАЛОБЫ: слот T1A нарисован пустым, а не заполненным",
                  a_["opacity"] != "1" and "158, 167, 174" not in a_["bg"], a_)
            check("30. то же для T1C", c_["opacity"] != "1" and "158, 167, 174" not in c_["bg"], c_)
            check("31. слот с филаментом остался цветным (T1B)",
                  b_["opacity"] == "1" and "158, 167, 174" in b_["bg"], b_)
            check("32. подсказка пустого слота объясняет оставшуюся метку",
                  ("PETG" in a_["title"]) and any(w in a_["title"]
                                                  for w in ("метка", "label")), a_["title"])
            check("33. подсказка полного слота называет материал и что он подан",
                  "PETG" in b_["title"] and any(w in b_["title"]
                                                for w in ("подан", "loaded")), b_["title"])
            check("34. пустой слот без метки ничего лишнего не обещает (T1D)",
                  "PETG" not in d_["title"], d_["title"])
            check("35. заправленный слот подсвечен", b_["shadow"] and b_["shadow"] != "none",
                  b_["shadow"])
        diag = UI.get("__diag") or {}
        check("36. ошибок в консоли браузера нет",
              not diag.get("consoleErrors") and not diag.get("pageErrors"),
              (diag.get("consoleErrors"), diag.get("pageErrors")))

print("")
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for n in _fail:
    print("  провалено: %s" % n)
sys.exit(1 if _fail else 0)
