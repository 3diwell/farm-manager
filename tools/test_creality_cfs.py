# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.887 — CFS принтера Creality K2 на карточке: разбор и проводка.

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ
  * разбор понимает документированную структуру Creality (boxsInfo -> materialBoxs -> materials)
    в обеих встреченных формах и раскладывает слоты так же, как это сделано для AMS;
  * незнакомая структура НЕ разбирается наугад: возвращается shape="unknown" и пустой список,
    а ключи ответа доступны для диагностики;
  * сервер спрашивает у Moonraker объект `box` и кладёт слоты в ОТДЕЛЬНОЕ поле cfs_trays,
    не трогая ams_trays: у Bambu это поле участвует в запуске печати со слота, а у Klipper
    печать со слота не поддержана и списание идёт прежним путём;
  * карточка рисует ряд CFS по наличию слотов, без условия по марке, и клик по слоту ничего
    не запускает.

ИСТОЧНИКИ КОНТРАКТА перечислены в app/creality_cfs.py (HelixScreen preset k2.json;
rathlinus/ha-creality-lan; документация Moonraker про отсутствующие объекты).

БЕЗОПАСНОСТЬ: только чтение файлов и чистые функции. Ни сети, ни принтеров, ни БД.

Запуск:  python tools/test_creality_cfs.py
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.creality_cfs import parse as cfs_parse, raw_keys as cfs_keys  # noqa: E402

SENTINEL = "CREALITY_CFS_SENTINEL_2_887"
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
IDX = io.open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
APPJS = io.open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


#  ФИКСТУРА — СНЯТА С ЖИВОГО ПРИНТЕРА (диагностический отчёт Creality K2 Plus, 26.08.2026),
#  но серийный номер короба заменён на выдуманный: настоящих идентификаторов устройств в
#  отслеживаемых файлах быть не должно.
BOX_REAL = {
    "filament": 1, "state": "connect", "auto_refill": 1, "enable": 1, "filament_useup": 1,
    "same_material": [["000003", "09ea7ae", ["09ea7ae"], "PETG"]],
    "map": {"T1A": "T1A", "T1B": "T1B", "T1C": "T1C", "T1D": "T1D"},
    "T1": {"state": "connect", "filament": "None", "temperature": "27",
           "dry_and_humidity": "40", "filament_detected": "None", "measuring_wheel": "None",
           "version": "1.4.2", "sn": "FIXTURE_SN_0001", "mode": "0",
           "vender": ["none", "unknown", "none", "none"],
           "remain_len": ["0", "100", "0", "0"],
           "color_value": ["-1", "09ea7ae", "-1", "-1"],
           "material_type": ["-1", "000003", "-1", "-1"],
           "change_color_num": ["-1", "0", "-1", "-1"], "slot_rfid_scrap": "0"},
    "T2": {"state": "None", "vender": ["-1", "-1", "-1", "-1"],
           "remain_len": ["-1", "-1", "-1", "-1"], "color_value": ["-1", "-1", "-1", "-1"],
           "material_type": ["-1", "-1", "-1", "-1"]},
    "T3": {"state": "None"}, "T4": {"state": "None"},
}
RACK_REAL = {"vender": "-1", "color_value": "09ea7ae", "material_type": "000003",
             "remain_material_color": "09ea7ae", "remain_material_type": "000003",
             "remain_material_velocity": 400}

print("--- 1. Настоящая структура прошивки K2 Plus разбирается ---")
r = cfs_parse(BOX_REAL, RACK_REAL)
check("1. опознана форма коробов T1…T4", r["shape"] == "units", r["shape"])
check("2. подключённый короб один — три остальных не выдуманы",
      r["boxes"] == 1 and len(r["trays"]) == 4, (r["boxes"], len(r["trays"])))
check("3. слоты пронумерованы сквозным номером и подписаны как у принтера",
      [t["index"] for t in r["trays"]] == [0, 1, 2, 3]
      and [t["label"] for t in r["trays"]] == ["T1A", "T1B", "T1C", "T1D"],
      [(t["index"], t["label"]) for t in r["trays"]])
check("4. занятый слот распознан: материал назван по ответу самого принтера",
      r["trays"][1]["type"] == "PETG" and r["trays"][1]["code"] == "000003", r["trays"][1])
check("5. цвет берётся ПОСЛЕДНИМИ шестью знаками: 09ea7ae -> #9EA7AE",
      r["trays"][1]["color"] == "#9EA7AE", r["trays"][1]["color"])
check("6. пустые слоты названы пустыми и получили цвет пустого слота",
      all(r["trays"][i]["type"] == "Empty" and r["trays"][i]["color"] == "#3f3f46"
          for i in (0, 2, 3)), [r["trays"][i] for i in (0, 2, 3)])
check("7. остаток слота прочитан", r["trays"][1]["percent"] == 100, r["trays"][1]["percent"])
check("8. температура и влажность короба сняты",
      r["units"] == [{"unit": 0, "temp": "27", "humidity": "40", "state": "connect"}], r["units"])
check("9. заправленный слот определён по filament_rack", r["now"] == 1, r["now"])
check("10. без filament_rack заправленный слот честно неизвестен",
      cfs_parse(BOX_REAL)["now"] == -1)

print("--- 2. Имена материалов НЕ выдумываются ---")
_no_names = dict(BOX_REAL)
_no_names["same_material"] = []
_r2 = cfs_parse(_no_names, RACK_REAL)
check("11. принтер не назвал материал — показываем его код, а не догадку",
      _r2["trays"][1]["type"] == "000003", _r2["trays"][1]["type"])

print("--- 3. Вторая известная форма и мусор ---")
_alt = {"materialBoxs": [{"id": 0, "type": 0, "temp": 28, "humidity": 17, "materials": [
    {"id": 0, "type": "PLA", "color": "FF0000", "percent": 80}]}]}
_r3 = cfs_parse(_alt)
check("12. форма materialBoxs (другие прошивки) тоже понимается",
      _r3["shape"] == "materialBoxs" and _r3["trays"][0]["type"] == "PLA", _r3["shape"])
check("13. незнакомая структура даёт unknown и пустой список",
      cfs_parse({"state": 1, "cur": 2})["shape"] == "unknown"
      and cfs_parse({"state": 1})["trays"] == [])
check("14. мусор вместо ответа не роняет разбор",
      cfs_parse(None)["shape"] == "unknown" and cfs_parse([1, 2])["shape"] == "unknown")
check("15. короб не на связи слотов не даёт",
      cfs_parse({"T1": {"state": "None", "material_type": ["000003", "-1", "-1", "-1"]}})["trays"] == [])

print("--- 4. Проводка в сервере ---")
check("16. объект box запрашивается у Moonraker вместе с остальными",
      "&webhooks&box" in SRV)
check("17. разбор подключён и вызывается на ответе принтера вместе с filament_rack",
      "from app.creality_cfs import parse as _cfs_parse" in SRV
      and '_cfs_parse(_box, st.get("filament_rack"))' in SRV)
check("18. слоты кладутся в ОТДЕЛЬНОЕ поле, ams_trays у Klipper не трогается",
      '"cfs_trays": _cfs.get("trays")' in SRV
      and '"ams_trays"' not in SRV[SRV.find("async def run_klipper"):SRV.find("async def run_flashforge")
                                    if SRV.find("async def run_flashforge") > 0 else len(SRV)])
#  Alpha 2.888: в журнал уходит СОСТАВ ответа — по нему разбор дописывается точно, а не по
#  одним именам полей верхнего уровня.
check("19. незнакомая структура попадает в журнал один раз на принтер, с составом ответа",
      "_cfs_unknown_logged" in SRV and "_cfs_describe(_box)" in SRV)

print("--- 5. Показ на карточке ---")
check("20. ряд CFS рисуется по наличию слотов, без условия по марке",
      'v-if="(wsData[p.id]?.cfs_trays || []).length"' in IDX)
check("21. поданный слот подсвечивается",
      "cfs_now === t.index" in IDX)
check("22. клик по слоту CFS ничего не запускает (у AMS он участвует в печати)",
      "cfs_trays" in IDX and IDX.count("onPrinterCardClick(p, $event)") == IDX.replace(
          'v-if="(wsData[p.id]?.cfs_trays || []).length"', "").count("onPrinterCardClick(p, $event)"))
check("23. подписи слота и короба отданы в шаблон (метка принтера T1B в подсказке)",
      "cfsTitle" in APPJS and "cfsSlotTitle" in APPJS
      and "cfsTitle, cfsSlotTitle," in APPJS)

print("--- 6. Диагностический отчёт показывает СОСТАВ ответа CFS ---")
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("kcp", os.path.join(ROOT, "app", "klipper_contract_probe.py"))
_kcp = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_kcp)
check("24. состояние CFS входит в разрешённые адреса отчёта",
      any("box" in p for p in _kcp.ALLOWED_PATHS), _kcp.ALLOWED_PATHS)
check("25. адрес остаётся read-only: исполняющих фрагментов в нём нет",
      all(not any(bad in p for bad in _kcp.FORBIDDEN_FRAGMENTS) for p in _kcp.ALLOWED_PATHS))
_desc = _kcp.describe_structure({"box": {"state": 1, "slots": [{"id": 0, "color": "FF0000"}],
                                         "deep": {"a": {"b": {"c": {"d": {"e": 1}}}}},
                                         "long": "x" * 200}})
check("26. состав показывает поля, типы и простые значения",
      _desc["box"]["state"] == 1 and isinstance(_desc["box"]["slots"], list)
      and _desc["box"]["slots"][0]["color"] == "FF0000", _desc)
check("27. длинные строки режутся, глубина ограничена",
      len(_desc["box"]["long"]) == 80 and isinstance(_desc["box"]["deep"], dict), _desc["box"]["long"][:20])
check("28. отчёт получил раздел состояния CFS",
      "cfs_state" in io.open(os.path.join(ROOT, "app", "klipper_contract_probe.py"),
                             encoding="utf-8").read())
check("29. журнал программы пишет СОСТАВ ответа, а не только имена полей",
      "_cfs_describe(_box)" in SRV)

print("--- 7. Списание идёт с той катушки, которая заправлена ---")

#  Alpha 2.890. До этого для Klipper в оба места списания жёстко передавался «слот 0,
#  внешняя катушка»: у Klipper-принтеров систем подачи не было. У K2 с CFS печать идёт
#  с одного из слотов короба, и списывать с внешней катушки — вести неверный учёт.
_disp = SRV[SRV.find("def _klipper_dispatch_slots"):SRV.find("def _run_after_dispatch_hooks")]
check("30. выбор слота для списания вынесен в отдельную функцию", bool(_disp.strip()))
check("31. слот берётся из состояния принтера, а не из догадки",
      'st.get("cfs_trays")' in _disp and 'st.get("cfs_now"' in _disp)
check("32. слот засчитывается, только если он есть среди слотов CFS",
      'any(int(t.get("index", -1)) == now for t in trays)' in _disp)
check("33. нет CFS или слот не определён — поведение прежнее (слот 0, внешняя катушка)",
      "return [0], True" in _disp)
check("34. при списании с CFS признак «внешняя катушка» снимается",
      "return [now], False" in _disp)
#  Три вхождения — это объявление функции и два места печати Klipper. С 2.944 у функции есть
#  второй параметр (выбранная владельцем ячейка CFS), поэтому считаем по НАЧАЛУ вызова, а не по
#  точному «(pid)»: проверяется по-прежнему то же самое — обе точки печати идут через эту функцию.
#  2.977 (R-095): к объявлению и двум точкам печати добавилась третья — запуск файла,
#  УЖЕ лежащего на принтере (_c1_after_dispatch). Он идёт через того же помощника,
#  поэтому вхождений стало четыре, а списаний по _kslots — по-прежнему два.
#  16.09.2026: пятое вхождение — план подачи перед стартом (_launch_feed_plan): склад обязан
#  сверять ТОТ слот, из которого пойдёт печать, и слот ему считает этот же помощник. Это ЧТЕНИЕ
#  перед запуском, а не новая точка печати: списаний по _kslots по-прежнему два.
check("35. все точки печати Klipper используют этот выбор",
      SRV.count("_klipper_dispatch_slots(pid") == 5
      and SRV.count("_run_after_dispatch_hooks(pid, _kslots") == 2
      and SRV.count("_stash_run_assignments(pid, _kslots") == 2)
#  2.979: то же самое место появилось у ВИРТУАЛЬНОГО принтера — у него тоже одна
#  внешняя катушка, слот 0. Смысл проверки прежний: у FlashForge ничего не поменялось.
#  12.10.2026: третья такая точка — Creality на заводской прошивке (_creality_send_print): одна катушка,
#  слот 0. Точек ровно три — виртуальный принтер, FlashForge и Creality без Moonraker.
check("36. FlashForge не тронут: у него по-прежнему слот 0",
      "_stash_run_assignments(pid, [0], fdata, True)       # FlashForge без AMS" in SRV
      and SRV.count("_stash_run_assignments(pid, [0], fdata, True)") == 3)

print("--- 8. Складской модуль видит слоты CFS ---")
_INV = io.open(os.path.join(ROOT, "modules", "inventory", "backend.py"), encoding="utf-8").read()
check("37. слоты подачи берутся общим помощником: сначала AMS, потом CFS",
      "def _printer_feed_trays" in _INV and 'st.get("ams_trays")' in _INV
      and 'st.get("cfs_trays")' in _INV)
check("38. обзор склада строит позиции через этот помощник",
      "_printer_feed_trays(p[" in _INV)
#  Сравниваем с ВЫЗОВОМ геттера, а не с упоминанием в пояснении к функции.
_conf = _INV[_INV.find("def _printer_confirmed_no_ams"):]
_conf = _conf[:_conf.find("def ", 10)]
check("39. у принтера с живым CFS «подачи нет» больше не подтверждается",
      0 <= _conf.find('get("cfs_trays")') < _conf.find("core.get_printer_reported_filament(pid)"),
      (_conf.find('get("cfs_trays")'), _conf.find("core.get_printer_reported_filament(pid)")))
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
check("40. версия складского модуля поднята — владельцу нужно его переустановить",
      (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(io.open(os.path.join(ROOT, "modules", "inventory", "module.json"),
                        encoding="utf-8"))) == "1.7.29")

print("--- 9. Подписи склада — под ту подачу, что у принтера на самом деле ---")
_PANEL = io.open(os.path.join(ROOT, "modules", "inventory", "web", "InventoryPanel.js"),
                 encoding="utf-8").read()
check("41. вид подачи и метка слота доходят до интерфейса",
      '"label": t.get("label", ""), "feed": _feed_kind' in _INV and '"feed": _feed_kind' in _INV)
check("42. короб подписан меткой принтера (T1), а не «AMS»",
      "feedOf" in _PANEL and "'T' + ((u.n || 0) + 1)" in _PANEL)
check("43. слот в ячейке показывает букву принтера (T1B -> B)",
      "if (sl.label) return String(sl.label).slice(-1);" in _PANEL)
check("44. в окне привязки слот назван как на принтере",
      "const bindSlotName" in _PANEL and "L('Слот ', 'Slot ') + sl.label" in _PANEL)
check("45. общие подписи больше не называют чужую систему",
      "Слоты подачи" in _PANEL and "Нет подачи" in _PANEL and "Системы подачи" in _PANEL
      and "AMS слоты" not in _PANEL)
check("46. для Bambu подписи прежние — ветка AMS сохранена",
      "'AMS HT'" in _PANEL and "'A' + u.n" in _PANEL)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
