# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.992 — сообщения принтера (HMS) видны в программе.

ЗАЧЕМ. Владелец 10.09.2026: «нужно, чтобы сообщения, которые выскакивают на экранах
принтера, отображались в интерфейсе; в развёрнутой ячейке — само сообщение, в свёрнутой —
индикатор, что уведомление есть». Приложено фото H2D: «Micro Lidar lens seems to be dirty.
Please clean the lens. [0c00-0100-0001-0004]».

КОНТРАКТ (не догадки). Запись HMS несёт два 32-битных числа, attr и code. Печатный код —
четыре группы по четыре HEX: attr>>16, attr&0xFFFF, code>>16, code&0xFFFF. Важность берётся
из code>>16 (1 фатально, 2 серьёзно, 3 обычно, 4 сведения), узел — из attr>>24 (0x03 плата
движения, 0x05 материнская плата, 0x07 AMS, 0x08 голова, 0x0C камера и лидар). Разбор снят с
открытой реализации ha-bambulab (pybambu) и СВЕРЕН С ДВУМЯ реальными снимками владельца.

ЧТО ДОКАЗЫВАЕТСЯ:
  · оба кода с фотографий владельца разбираются в точности так, как показал принтер;
  · битые и пустые записи не роняют разбор и не превращаются в ложные уведомления;
  · delta-семантика та же, что у кодов: нет поля — прежнее не трогаем, [] — очистка;
  · прежний разбор кодов (на нём держится классификация отмены) НЕ изменён;
  · интерфейс показывает список в пульте и значок на свёрнутой ячейке, в сетке и в дашборде;
  · программа не выдумывает расшифровок: без таблицы производителя незнакомый код показан
    кодом, узлом и важностью;
  · 16.09.2026: с загруженной таблицей служебные коды прошивки (их нет ни в таблице, ни на
    экране принтера) человеку не показываются вовсе — ровно так поступает и Bambu Studio.

Безопасность прогона: server.py не импортируется целиком (разбор берётся дословным куском),
сеть и принтеры не используются.

Запуск: python tools/test_printer_hms_messages.py   (0 = все проверки пройдены)
"""
import io
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import printer_health_policy as H   # noqa: E402

SENTINEL = "PRINTER_HMS_MESSAGES_SENTINEL_2_992"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


print("=== Alpha 2.992: сообщения принтера в программе ===")

# ── 1. Разбор: сверка с фотографиями владельца ────────────────────────────────────────────
print("\n--- 1. Разбор кода: сверка с экраном принтера ---")
lidar = H.hms_record(0x0C000100, 0x00010004)
check("1. ФОТО ВЛАДЕЛЬЦА: код совпал с показанным на экране (0C00-0100-0001-0004)",
      lidar and lidar["code"] == "0C00-0100-0001-0004", lidar)
check("2. узел определён как камера и лидар — сообщение действительно про микро-лидар",
      lidar and lidar["module"] == "xcam", lidar)
check("3. важность взята из кода: принтер показал это красной рамкой",
      lidar and lidar["severity"] == "fatal", lidar)

ams = H.hms_record(0x07002000, 0x00030002)
check("4. ВТОРОЕ ФОТО: код подмены катушки AMS (0700-2000-0003-0002)",
      ams and ams["code"] == "0700-2000-0003-0002", ams)
check("5. узел AMS, важность «обычное» — это уведомление, а не сбой",
      ams and ams["module"] == "ams" and ams["severity"] == "common", ams)

check("6. числа приходят и строкой (у разных прошивок формат отчёта различается)",
      H.hms_record("201326848", "65540") == lidar)
check("7. и шестнадцатеричной строкой", H.hms_record("0x0C000100", "0x00010004") == lidar)

# ── 2. Разбор не выдумывает и не падает ───────────────────────────────────────────────────
print("\n--- 2. Битое и пустое ---")
for label, args in (("нет attr", (None, 1)), ("нет code", (1, None)), ("оба нуля", (0, 0)),
                    ("пустые строки", ("", "")), ("не число", ("мусор", "мусор")),
                    ("отрицательное", (-1, 5)), ("больше 32 бит", (0x1FFFFFFFF, 5))):
    check("8. %s -> уведомления нет (не выдумываем)" % label, H.hms_record(*args) is None,
          H.hms_record(*args))

check("9. неизвестная важность и узел честно названы неизвестными",
      (H.hms_record(0xAA000000, 0x00090001) or {}).get("severity") == "unknown"
      and (H.hms_record(0xAA000000, 0x00090001) or {}).get("module") == "unknown",
      H.hms_record(0xAA000000, 0x00090001))

lst = H.hms_records([{"attr": 0x0C000100, "code": 0x00010004},
                     {"attr": 0x0C000100, "code": 0x00010004},
                     "не словарь", {"attr": None, "code": None},
                     {"attr": 0x07002000, "code": 0x00030002}])
check("10. список: повторы убраны, мусор пропущен, порядок принтера сохранён",
      [x["code"] for x in lst] == ["0C00-0100-0001-0004", "0700-2000-0003-0002"], lst)
check("11. одна битая запись не прячет остальные", len(lst) == 2, lst)

# ── 3. Сервер: delta-семантика и прежний разбор не тронут ─────────────────────────────────
print("\n--- 3. Сервер ---")
SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_ns = {"_health": H}
_i = SRC.index("def _bambu_hms_list(")
exec(compile(SRC[_i:SRC.index("def _bambu_hms_codes(")], "<hms>", "exec"), _ns)
_hms = _ns["_bambu_hms_list"]
PREV = [{"code": "0700-2000-0003-0002", "severity": "common", "module": "ams"}]
check("12. поля hms нет в отчёте — прежние уведомления не трогаем (частичный отчёт)",
      _hms({"gcode_state": "RUNNING"}, PREV) == PREV)
check("13. hms=null — тоже прежние", _hms({"hms": None}, PREV) == PREV)
check("14. hms=[] — принтер снял уведомления, список очищается", _hms({"hms": []}, PREV) == [])
check("15. мусор вместо списка — прежние (воркер не роняем)", _hms({"hms": "мусор"}, PREV) == PREV)
check("16. записи разбираются",
      [x["code"] for x in _hms({"hms": [{"attr": 0x0C000100, "code": 0x00010004}]}, [])]
      == ["0C00-0100-0001-0004"])

check("17. прежний разбор кодов (на нём классификация отмены) НЕ изменён",
      "def _bambu_hms_codes(d, prev_codes):" in SRC and "'XXXX-XXXX'" in SRC)
check("18. уведомления попадают в состояние принтера и уходят в браузер обычной рассылкой",
      '"hms": _hms_list,' in SRC)

# ── 4. Интерфейс ──────────────────────────────────────────────────────────────────────────
print("\n--- 4. Интерфейс ---")
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
CSS = io.open(os.path.join(REPO, "web", "app.css"), encoding="utf-8").read()
UI3 = io.open(os.path.join(REPO, "web", "ui3", "ui3.css"), encoding="utf-8").read()

check("19. РАЗВЁРНУТАЯ ЯЧЕЙКА: в пульте есть блок сообщений принтера",
      'class="ui3-pp-hms"' in HTML and 'data-help="pp-hms"' in HTML and "hmsFor(ui3Printer)" in HTML)
check("20. СВЁРНУТАЯ ЯЧЕЙКА: значок с числом уведомлений",
      'class="pc-hms"' in HTML and "hmsCount(p.id)" in HTML and 'class="pc-hms-n"' in HTML)
check("21. значок есть и в виде «Сетка», и на карточке дашборда",
      'class="pc-hms-dot"' in HTML and 'class="pcd-hms"' in HTML)
check("22. цвет значка — по важности, объявленной принтером",
      ".pc-hms.sev-fatal" in CSS and ".pc-hms.sev-common" in CSS and ".pc-hms.sev-info" in CSS
      and ".pc-hms.sev-unknown" in CSS)
check("23. список в пульте не выдавливает пульт (своя прокрутка)",
      ".ui3-pp-hms {" in UI3 and "overflow-y: auto" in UI3.split(".ui3-pp-hms {")[1][:260])
check("24. известные коды переведены, и оба — с подтверждённым источником",
      "'0C00-0100-0001-0004':" in APPJS and "'0700-2000-0003-0002':" in APPJS
      and "wiki.bambulab.com" in APPJS)
check("25. КЛЮЧЕВОЕ: незнакомый код НЕ выдумывается — показан код, узел и важность",
      "hmsText(h)" in HTML and "hmsModuleText(h.module)" in HTML and "hmsSevText(h.severity)" in HTML
      and "h.code" in HTML)
check("26. оператору сказано, где прочитать полный текст — один раз под списком, а не в каждой строке",
      'class="ui3-pp-hms-f"' in HTML and "на экране принтера" in HTML
      and "hmsFor(ui3Printer).some(h => !hmsText(h))" in HTML)
check("27. подписи важности и узлов переведены на оба языка",
      "const hmsSevText" in APPJS and "const hmsModuleText" in APPJS
      and "камера и лидар" in APPJS and "camera and lidar" in APPJS)
check("28. значок и список доступны шаблону (экспорт из setup)",
      "hmsFor, hmsCount, hmsTopSeverity, hmsText, hmsSevText, hmsModuleText, hmsTip," in APPJS)

# ── 5. Только настоящие сообщения (жалоба владельца 16.09.2026) ───────────────────────────
print()
print("--- 5. Только настоящие сообщения: служебные коды прошивки не показываются ---")
#  ЖАЛОБА. В ячейках H2D и P2S программа показывала «Уведомление принтера» с кодами
#  0500-0200-0003-000A и 0500-0600-0002-0070, которых на экранах самих принтеров не было.
#  КОНТРАКТ (не догадка): обоих кодов нет в официальной таблице Bambu (1978 уведомлений,
#  e.bambulab.com/query.php), а Bambu Studio показывает уведомление только при непустом тексте
#  (src/slic3r/GUI/HMSPanel.cpp: if (!msg.empty()) { ... new HMSNotifyItem ... }).
OWNER_H2D = {"attr": 0x05000200, "code": 0x0003000A}
OWNER_P2S = {"attr": 0x05000600, "code": 0x00020070}
LIDAR_E = {"attr": 0x0C000100, "code": 0x00010004}
_old_lookup, _old_ready = H.HMS_TEXT_LOOKUP, H.HMS_TABLE_READY
H.HMS_TEXT_LOOKUP = lambda code: ({"ru": "Линза микро-лидара, возможно, загрязнена.",
                                   "en": "Micro Lidar lens seems to be dirty."}
                                  if code == "0C00-0100-0001-0004" else None)
H.HMS_TABLE_READY = lambda: True
ALL3 = H.hms_with_texts(H.hms_records([OWNER_H2D, LIDAR_E, OWNER_P2S]))
vis = H.hms_user_visible(ALL3)
check("29. ФОТО ВЛАДЕЛЬЦА: служебные коды H2D и P2S человеку НЕ показываются",
      [x["code"] for x in vis] == ["0C00-0100-0001-0004"], [x["code"] for x in vis])
check("30. настоящее сообщение (текст есть в таблице производителя) остаётся",
      len(vis) == 1 and vis[0].get("text", {}).get("ru", "").startswith("Линза"), vis)
check("31. разбор записей не тронут — прячется только показ человеку",
      [x["code"] for x in ALL3] == ["0500-0200-0003-000A", "0C00-0100-0001-0004", "0500-0600-0002-0070"],
      [x["code"] for x in ALL3])
H.HMS_TABLE_READY = lambda: False
check("32. БЕЗ таблицы производителя (установка без интернета) не прячем НИЧЕГО",
      len(H.hms_user_visible(ALL3)) == 3)


def _ready_boom():
    raise RuntimeError("таблицы нет")


H.HMS_TABLE_READY = _ready_boom
check("33. сломанный признак таблицы ничего не прячет (fail-open)", len(H.hms_user_visible(ALL3)) == 3)
H.HMS_TABLE_READY = None
check("34. признак не задан — поведение прежнее", len(H.hms_user_visible(ALL3)) == 3)
check("35. явный ответ в проверке сильнее хука",
      len(H.hms_user_visible(ALL3, table_ready=True)) == 1
      and len(H.hms_user_visible(ALL3, table_ready=False)) == 3)
check("36. мусор в списке фильтр не роняет",
      H.hms_user_visible(["мусор", None, {"code": "X", "text": {"ru": "т"}}], table_ready=True)
      == [{"code": "X", "text": {"ru": "т"}}])
H.HMS_TABLE_READY = lambda: True
_out = _hms({"hms": [OWNER_H2D, LIDAR_E, OWNER_P2S]}, [])
check("37. НАСТОЯЩИЙ разбор отчёта принтера: в состояние уходит только сообщение для человека",
      [x["code"] for x in _out] == ["0C00-0100-0001-0004"], _out)
check("38. сервер подключает признак таблицы рядом с самой таблицей и зовёт фильтр",
      "_health.HMS_TABLE_READY = _hms_table_ready" in SRC and "def _hms_table_ready():" in SRC
      and "_health.hms_user_visible(" in SRC)
check("39. журнал «Что нового» объясняет владельцу, что показываются только настоящие сообщения",
      "только настоящие сообщения для человека" in SRC and "служебные коды прошивки" in SRC)
H.HMS_TEXT_LOOKUP, H.HMS_TABLE_READY = _old_lookup, _old_ready

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
