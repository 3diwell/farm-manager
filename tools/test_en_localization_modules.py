# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""23.09.2026 — английский интерфейс модулей без русских подписей (обзор для английского видео).

ЖАЛОБА. При подготовке английского видеообзора в EN-интерфейсе остались русские подписи:
  · Расчёт заказа — «г» в сводке веса, «/кг» и «г» в списке филамента со склада;
  · Camera Wall — «без перекодирования» рядом с Core H.264;
  · Склад → новая позиция — стандартная единица «шт».
Широкий проход по тому же маршруту нашёл ещё одно место в той же строке заказа: время печати
писалось «2 ч 41 мин» при любом языке (и в строке заказа, и в «Общем времени»).

ПРАВИЛО ДЛЯ ЕДИНИЦ СКЛАДА. Стандартная единица ХРАНИТСЯ прежним словом («шт» — так она уже лежит
в базе у созданных позиций), а ПОКАЗЫВАЕТСЯ по языку: при EN — pcs. Выбранное в английском
интерфейсе pcs сохраняется как «шт», поэтому оба языка видят одну позицию. Свою единицу
пользователь пишет любую — она хранится и показывается как есть. Данные не переписываются.

ЧЕГО НЕ ДЕЛАЛИ. Не переводили и не переименовывали пользовательские названия (материалы,
производители, полки, запчасти, файлы, принтеры) и не делали глобальной замены «г»/«шт».
Системный выбор даты — поле браузера: его окно рисует браузер на языке Windows (см. проверку 17).

Безопасность: только чтение исходников и исполнение отдельных функций в Node. Баз, сети нет.
Запуск: python tools/test_en_localization_modules.py   (0 = все проверки пройдены)
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SENTINEL = "EN_LOCALIZATION_MODULES_SENTINEL_2309"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


def rd(*p):
    return io.open(os.path.join(REPO, *p), encoding="utf-8").read()


COST = rd("modules", "cost", "web", "CostPanel.js")
#  26.09.2026: «Видеостены» может не быть — в открытой выгрузке модуль придержан до решения
#  владельца об авторстве. Тогда её раздел пропускается с пометкой, остальное проверяется.
CAM_PRESENT = os.path.isfile(os.path.join(REPO, "modules", "camera_wall", "module.json"))
CAMP = rd("modules", "camera_wall", "web", "camera-providers.js") if CAM_PRESENT else ""
CAMW = rd("modules", "camera_wall", "web", "CameraWallPanel.js") if CAM_PRESENT else ""
INV = rd("modules", "inventory", "web", "InventoryPanel.js")

NODE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"


def node(js):
    """Исполнить кусок JS в Node и вернуть разобранный JSON с последней строки вывода."""
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    if r.returncode != 0:
        return {"__error__": (r.stderr or r.stdout)[-400:]}
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"__error__": "%s: %r" % (e, r.stdout[-200:])}


print("=== 23.09.2026: английский интерфейс модулей ===")
print()
print("--- 1. Расчёт заказа ---")
check("1. вес позиции заказа: единица через L('г','g'), русской «г» вне перевода нет",
      "{{materialWeight(it).toFixed(1)}} {{L('г','g')}}</div>" in COST
      and "{{materialWeight(it).toFixed(1)}} г</div>" not in COST)
check("2. филамент со склада: цена за килограмм и остаток переведены (/kg и g)",
      "{{L('/кг','/kg')}}" in COST and "+' '+L('г','g'):''" in COST and " /кг{{" not in COST
      and "+' г':''" not in COST)
m = re.search(r"function fmtTime\(sec,lang\)\{.*?\}\s*$", COST, re.M)
res = node("%s\nconsole.log(JSON.stringify([fmtTime(9660,'en'),fmtTime(9660,'ru'),fmtTime(1500,'en'),"
           "fmtTime(1500,'ru'),fmtTime(-5,'en')]));" % (m.group(0) if m else "function fmtTime(){}"))
check("3. время печати по языку: 2 h 41 min / 2 ч 41 мин, 25 min / 25 мин (исполнено в Node)",
      res == ["2 h 41 min", "2 ч 41 мин", "25 min", "25 мин", "0 min"], res)
calls = re.findall(r"fmtTime\(([^)]*)\)", COST)
check("4. КАЖДЫЙ вызов времени в шаблоне передаёт язык интерфейса",
      calls and all(c == "sec,lang" or "L('ru','en'" in c for c in calls), calls)

print()
print("--- 2. Camera Wall ---")
if not CAM_PRESENT:
    print("SKIP — 5-8. модуля «Видеостена» в этой копии нет (придержан вне открытой выгрузки)")
else:
  check("5. подпись способа потока — техническое английское название, как у остальных",
        "label: 'Core H.264 · no transcoding'" in CAMP and "без перекодирования'" not in CAMP)
  tt = re.search(r"const TRANSPORT_RU = .*?;\n\s*const transportText = .*?;", CAMW, re.S)
  res = node("const props={lang:'ru'};%s\nconst ru=transportText('Core H.264 · no transcoding');"
             "props.lang='en';const en=transportText('Core H.264 · no transcoding');"
             "const other=transportText('WebRTC · STUN');const empty=transportText('');"
             "console.log(JSON.stringify([ru,en,other,empty]));" % (tt.group(0) if tt else ""))
  check("6. RU показывает «Core H.264 · без перекодирования», EN — «no transcoding»; прочие не трогаются",
        res == ["Core H.264 · без перекодирования", "Core H.264 · no transcoding", "WebRTC · STUN", ""], res)
  check("7. плитка рисует подпись через перевод", "{{ transportText(tile.state.transport) }}" in CAMW
        and "{{ tile.state.transport }}" not in CAMW and "transportText," in CAMW)
  check("8. сам способ потока и его порядок не менялись (core-fmp4 первым, MJPEG запасным)",
        CAMP.find("key: 'core-fmp4'") < CAMP.find("key: 'core-mjpeg', label: 'Core MJPEG · FFmpeg'")
        and "new CoreFmp4Provider(`/api/printer/${pid}/camera.mp4`, env)" in CAMP)

print()
print("--- 3. Склад: единицы ---")
unit_block = re.search(r"const UNIT_EN = .*?\n    \};", INV, re.S)
harness = ("const props={lang:'en'};%s\n"
           "const out={};"
           "out.en_default=unitText('шт');out.en_all=['шт','компл','м','рулон','г','мл'].map(unitText);"
           "out.en_custom=unitText('мешок');out.en_empty=unitText('');"
           "out.canon_pcs=unitCanon('pcs');out.canon_PCS=unitCanon(' PCS ');out.canon_custom=unitCanon('bag');"
           "props.lang='ru';out.ru_default=unitText('шт');out.ru_canon=unitCanon('pcs');"
           "console.log(JSON.stringify(out));" % (unit_block.group(0) if unit_block else ""))
res = node(harness)
check("9. EN: стандартная «шт» показывается как pcs, весь стандартный список переведён",
      res.get("en_default") == "pcs" and res.get("en_all") == ["pcs", "set", "m", "roll", "g", "ml"], res)
check("10. своя единица пользователя показывается как есть (не переводится)", res.get("en_custom") == "мешок", res)
check("11. КЛЮЧЕВОЕ: выбранное в EN pcs сохраняется как прежнее «шт» — данные не расходятся",
      res.get("canon_pcs") == "шт" and res.get("canon_PCS") == "шт", res)
check("12. своя единица в EN сохраняется ровно как введена", res.get("canon_custom") == "bag", res)
check("13. RU: всё как было — «шт» показывается «шт», введённое сохраняется как есть",
      res.get("ru_default") == "шт" and res.get("ru_canon") == "pcs", res)
check("14. поле «Единица» в форме связано с переводом, а не с сырым значением",
      'v-model="itemUnitView"' in INV and 'v-model="itemDlg.form.unit"' not in INV
      and ':value="unitText(u)"' in INV)
check("15. единица показывается переводом в списке позиций и в окне прихода/расхода",
      '<span class="fm-inv-qty-u">{{ unitText(it.unit) }}</span>' in INV
      and INV.count("{{ unitText(itemAdj.unit) }}") == 2 and "{{ itemAdj.unit }}" not in INV)
check("16. хранимые значения прежние: новая позиция по умолчанию получает то же «шт»",
      "unit: 'шт', qty: 0" in INV and "const UNITS = ['шт', 'компл', 'м', 'рулон', 'г', 'мл'];" in INV)

print()
print("--- 4. Системный выбор даты ---")
dates = re.findall(r'<input type="date"[^>]*>', COST)
check("17. поля даты — обычные поля браузера без русских подписей от FM (их окно рисует браузер "
      "на языке Windows, FM на него не влияет)",
      len(dates) == 2 and all(not re.search(r"[А-Яа-яЁё]", d) for d in dates), dates)

print()
print("--- 5. Что не трогали ---")
check("18. склад по-прежнему хранит и показывает названия пользователя как есть (без перевода)",
      "{{ it.name }}" in INV or "it.name" in INV)
check("19. валюта не превращается в другую: расчёт заказа не подменяет знак валюты по языку",
      "currency" in COST and "L('₽'" not in COST and "L('руб" not in COST)

print()
print("--- 6. Склад 1.7.37: история движений ---")
#  09.10.2026. Записи истории хранятся по-русски, английское окно переводит их таблицей
#  InventoryI18n.js. Запись списания пустой катушки с телефона (1.7.35) в таблицу не попала и в
#  английском окне оставалась русской. Проверка берёт ВСЕ причины, которые телефонный клиент пишет
#  в историю (строки mobile_api.py с «катушк»/«приёмк»), — новая причина без перевода покраснеет здесь.
MOB = rd("modules", "inventory", "mobile_api.py")
reasons = sorted(set(re.findall(r'"([^"{}\n]*(?:катушк|приёмк)[^"{}\n]*)"', MOB)))
i18n_url = "file:///" + os.path.join(REPO, "modules", "inventory", "web", "InventoryI18n.js").replace("\\", "/")
res = node("import(%s).then(m => { const R = %s; console.log(JSON.stringify(R.map(r => [r, m.systemText(r, 'en'), m.systemText(r, 'ru')]))); })"
           % (json.dumps(i18n_url), json.dumps(reasons, ensure_ascii=False)))
check("20. найдены причины, которые пишет телефонный клиент (не меньше пяти)", len(reasons) >= 5, reasons)
check("21. КАЖДАЯ такая причина в английском окне переведена (без кириллицы), в русском — как есть",
      isinstance(res, list) and len(res) == len(reasons)
      and all(not re.search(r"[А-Яа-яЁё]", en) and ru == r for r, en, ru in res), res)
check("22. списание пустой катушки: «Empty spool written off · mobile client»",
      isinstance(res, list) and ["списание пустой катушки · мобильный клиент",
                                 "Empty spool written off · mobile client",
                                 "списание пустой катушки · мобильный клиент"] in res, res)
_hn = re.search(r"const histNote = (\(n\) => \{.*?\});\r?\n", INV)
hn = node("const f = %s; console.log(JSON.stringify([f('{\"printer_id\": \"P2S\", \"ams_slot\": 2}'), f('Benchy.gcode.3mf'), "
          "f('{не JSON: заметка}'), f(''), f(null), f('[1,2]')]));" % (_hn.group(1) if _hn else "null"))
check("23. служебная пометка телефона (JSON) в окне истории не показывается, обычная заметка — как есть",
      hn == ["", "Benchy.gcode.3mf", "{не JSON: заметка}", "", "", "[1,2]"], hn)
check("24. в окне истории пометка выводится через histNote, а не сырым e.note",
      '<template v-if="histNote(e.note)"> · {{ histNote(e.note) }}</template>' in INV and "{{ e.note }}" not in INV)
check("25. причина видна целиком: перенос строк вместо многоточия, дата не переносится",
      "'.fm-inv-hist .fm-inv-hist-r{white-space:normal;overflow:visible;text-overflow:clip;" in INV
      and "'.fm-inv-hist .fm-inv-hist-t{white-space:nowrap}'" in INV)
check("26. предел высоты диалога — от подложки (100%), а не от 100vh: под увеличением страницы 1.196 "
      "vh давал диалог выше экрана", "'.fm-inv-dlg-back > .fm-inv-dlg{max-height:calc(100% - 24px)}'" in INV)
check("27. в окне истории прокручивается только список: заголовок и «Закрыть» всегда на виду",
      'class="fm-inv-dlg sm fm-inv-dlg-hist"' in INV
      and "'.fm-inv-dlg-hist .fm-inv-hist{flex:1 1 auto;min-height:0}'" in INV)
check("28. подписи под цифрами склада не вылезают из ячейки: ячейка не уже слова, длинная подпись переносится",
      "'.fm-inv-mstat{display:flex;flex-direction:column;gap:1px;min-width:auto}'" in INV
      and re.search(r"'\.fm-inv-mstat-l\{[^']*white-space:normal;line-height:1\.15\}'", INV) is not None)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
