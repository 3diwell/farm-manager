# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Разбор состояния CFS (система подачи катушек) у принтеров Creality K2 — чистые функции.

КОНТРАКТ ВЗЯТ С ЖИВОГО ПРИНТЕРА, А НЕ ПРИДУМАН. Основание — диагностический отчёт с
Creality K2 Plus (Klipper 09faed31-dirty), снятый 26.08.2026 штатной кнопкой Farm Manager.
В отчёте лежит ответ Moonraker на /printer/objects/query?box&filament_rack. Форма этой прошивки:

    box:
      state            — "connect", когда система на связи
      T1 … T4          — короба (до четырёх), у каждого:
          state            — "connect" либо "None", если короба нет
          temperature      — температура внутри короба, строкой
          dry_and_humidity — влажность внутри короба, строкой
          vender[4]        — производитель по слотам A…D
          material_type[4] — КОД материала по слотам ("000003"), "-1" = слот пуст
          color_value[4]   — цвет по слотам, шестнадцатеричный без решётки ("09ea7ae")
          remain_len[4]    — остаток по слотам ("100"); "0" = филамента в слоте НЕТ, даже
                             если material_type и color_value в нём заполнены (метка остаётся
                             от прежней катушки — наблюдение владельца, отчёты 26.08 и 02.09.2026)
      same_material    — записи вида [код, цвет, …, "PETG"]: отсюда берутся ИМЕНА материалов
      map              — T1A…T4D, подтверждает разметку «короб + слот A…D»
    filament_rack:
      remain_material_type / remain_material_color — что заправлено в голову СЕЙЧАС

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО. Своей таблицы кодов материалов: код «000003» означает PETG только
потому, что так сказал сам принтер в same_material. Не назвал — показываем код как есть, а не
догадку.

Вторая понимаемая форма — та, что отдают открытые интеграции к другим прошивкам Creality
(boxsInfo -> materialBoxs -> materials). Она оставлена: разбору не мешает, а на другой прошивке
может пригодиться. Всё неопознанное честно даёт shape="unknown".
"""

SLOTS_PER_BOX = 4
SLOT_LETTERS = ("A", "B", "C", "D")
EMPTY_COLOR = "#3f3f46"                 # тот же цвет пустого слота, что у AMS — вид карточки един
_ABSENT = ("-1", "none", "null", "")    # чем прошивка обозначает «ничего нет»


def _absent(v):
    return str(v if v is not None else "").strip().lower() in _ABSENT


def _color_of(raw):
    """Цвет слота в вид '#RRGGBB'.

    Прошивка отдаёт цвет шестнадцатеричным числом без выравнивания: '09ea7ae' — семь знаков,
    значащие последние шесть (9ea7ae — серо-голубой). Поэтому берём ПОСЛЕДНИЕ шесть, а не
    первые: для обычного '0000ff' это ничего не меняет.
    """
    s = str(raw or "").strip().lstrip("#")
    s = "".join(ch for ch in s if ch in "0123456789abcdefABCDEF")
    if len(s) < 6:
        return EMPTY_COLOR
    return "#" + s[-6:].upper()


def _material_names(box):
    """Сопоставление КОД материала -> человеческое имя, взятое у самого принтера."""
    out = {}
    same = box.get("same_material") if isinstance(box, dict) else None
    for row in (same if isinstance(same, list) else []):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        code = str(row[0] or "").strip()
        name = ""
        for cell in reversed(list(row[1:])):
            if isinstance(cell, str) and cell.strip() and not _absent(cell):
                cand = cell.strip()
                #  Имя материала — это буквы (PETG, PLA), а не код и не цвет.
                if any(ch.isalpha() for ch in cand) and not cand.isdigit():
                    name = cand
                    break
        if code and name and not _absent(code):
            out[code] = name
    return out


def _parse_units(box):
    """Форма живого K2: короба T1…T4 с параллельными списками по слотам A…D."""
    names = _material_names(box)
    trays, units = [], []
    for n in range(1, 5):
        u = box.get("T%d" % n)
        if not isinstance(u, dict) or _absent(u.get("state")):
            continue                     # короба нет — не выдумываем ему слоты
        unit = n - 1
        units.append({"unit": unit,
                      "temp": None if _absent(u.get("temperature")) else u.get("temperature"),
                      "humidity": (None if _absent(u.get("dry_and_humidity"))
                                   else u.get("dry_and_humidity")),
                      "state": u.get("state")})
        mats = u.get("material_type") if isinstance(u.get("material_type"), list) else []
        cols = u.get("color_value") if isinstance(u.get("color_value"), list) else []
        rems = u.get("remain_len") if isinstance(u.get("remain_len"), list) else []
        vends = u.get("vender") if isinstance(u.get("vender"), list) else []
        for i in range(SLOTS_PER_BOX):
            code = str(mats[i]).strip() if i < len(mats) and mats[i] is not None else "-1"
            col = cols[i] if i < len(cols) else ""
            rem = rems[i] if i < len(rems) else None
            ven = vends[i] if i < len(vends) else ""
            percent = None
            try:
                if rem is not None and not _absent(rem):
                    val = float(str(rem).strip())
                    #  Наблюдение с живого принтера: у заправленного слота здесь 100, у пустых 0.
                    #  Считаем это процентами ТОЛЬКО в диапазоне 0…100; всё, что больше, —
                    #  не проценты, и выдумывать единицу измерения мы не будем.
                    percent = int(val) if 0 <= val <= 100 else None
            except Exception:
                percent = None
            #  🔒 Alpha 2.942, ПО НАБЛЮДЕНИЮ ВЛАДЕЛЬЦА НА ЖИВОЙ ФЕРМЕ: «есть слоты, в которых
            #  показывает, что есть филамент, а по факту там пусто». Так и есть, и это видно в
            #  отчёте с его K2 Plus от 02.09.2026: в T1A и T1C стоит material_type 000003 и
            #  цвет 09ea7ae, а remain_len у них "0" — катушка кончилась или вынута, а МЕТКА
            #  осталась. В отчёте от 26.08.2026 у тех же слотов материала не было вовсе —
            #  значит метки появляются и остаются.
            #  Прежнее правило смотрело ТОЛЬКО на материал и цвет, поэтому такой слот рисовался
            #  полным, а заодно попадал в кандидаты на «заправленный»: три одинаковых кандидата
            #  вместо одного — и списание филамента молчало вовсе.
            #  ПРАВИЛО: остаток ИЗВЕСТЕН и равен нулю — филамента в слоте нет.
            #  Остаток НЕИЗВЕСТЕН (поля нет, "-1", не число) — слот считается заполненным как
            #  раньше: отсутствие данных не доказывает пустоту, и выдумывать её нельзя.
            declared = not (_absent(code) and _absent(col))
            spent = bool(declared and percent is not None and percent <= 0)
            empty = (not declared) or spent
            trays.append({
                "index": unit * SLOTS_PER_BOX + i,
                "unit": unit,
                "tray": i,
                "label": "T%d%s" % (n, SLOT_LETTERS[i]),
                "type": ("Empty" if empty else (names.get(code) or code)),
                "code": "" if (empty or _absent(code)) else code,
                "color": EMPTY_COLOR if empty else _color_of(col),
                "percent": percent,
                "vendor": "" if _absent(ven) else str(ven),
                #  Что принтер ПОМНИТ про опустевший слот — чтобы подсказка объяснила человеку,
                #  почему он видел здесь материал, а не молчала загадочным «пусто».
                "spent": spent,
                "declared": ((names.get(code) or code) if (spent and not _absent(code)) else ""),
            })
    return trays, units


def _parse_material_boxes(box):
    """Вторая известная форма (открытые интеграции к другим прошивкам Creality)."""
    info = box.get("boxsInfo")
    boxes = None
    if isinstance(info, dict) and isinstance(info.get("materialBoxs"), list):
        boxes = info["materialBoxs"]
    elif isinstance(box.get("materialBoxs"), list):
        boxes = box["materialBoxs"]
    if boxes is None:
        return None, None
    trays, units = [], []
    for pos, b in enumerate(boxes):
        if not isinstance(b, dict) or b.get("type") not in (0, None):
            continue
        try:
            unit = int(b.get("id", pos))
        except Exception:
            unit = pos
        units.append({"unit": unit, "temp": b.get("temp"), "humidity": b.get("humidity"),
                      "state": b.get("state")})
        for mpos, m in enumerate(b.get("materials") or []):
            if not isinstance(m, dict):
                continue
            try:
                slot = int(m.get("id", mpos))
            except Exception:
                slot = mpos
            if slot < 0 or slot >= SLOTS_PER_BOX:
                continue
            mat = str(m.get("type") or "").strip()
            pct = m.get("percent")
            #  То же правило, что и для формы коробов (см. ниже): известный нулевой остаток
            #  означает, что филамента нет, даже если материал слотом заявлен.
            spent = bool(mat and isinstance(pct, (int, float)) and not isinstance(pct, bool)
                         and pct <= 0)
            trays.append({
                "index": unit * SLOTS_PER_BOX + slot,
                "unit": unit,
                "tray": slot,
                "label": "T%d%s" % (unit + 1, SLOT_LETTERS[slot]),
                "type": ("Empty" if (not mat or spent) else mat),
                "code": "",
                "color": (_color_of(m.get("color")) if (mat and not spent) else EMPTY_COLOR),
                "percent": pct,
                "vendor": str(m.get("vendor") or ""),
                "spent": spent,
                "declared": (mat if spent else ""),
            })
    return trays, units


def _loaded_candidates(trays, rack):
    """Слоты, которые ПОДХОДЯТ под то, что заправлено в голову. -> список индексов.

    Прямого признака у этой прошивки нет: filament_rack сообщает только код материала и цвет
    заправленного, но НЕ номер слота (проверено на двух отчётах с живого принтера). Поэтому
    сопоставляем по коду и цвету — и возвращаем ВСЕХ подходящих, а не первого попавшегося.
    """
    if not isinstance(rack, dict):
        return []
    code = str(rack.get("remain_material_type") or rack.get("material_type") or "").strip()
    color = _color_of(rack.get("remain_material_color") or rack.get("color_value"))
    if _absent(code) and color == EMPTY_COLOR:
        return []
    out = []
    for t in trays:
        if t["type"] == "Empty":
            continue
        if not _absent(code) and t.get("code") == code:
            out.append(t["index"])
            continue
        if color != EMPTY_COLOR and t["color"] == color:
            out.append(t["index"])
    return out


def _loaded_index(trays, rack):
    """Какой слот заправлен в голову сейчас, если это можно утверждать. -> индекс или -1.

    ПРАВИЛО ЧЕСТНОСТИ (Alpha 2.902). Раньше возвращался ПЕРВЫЙ подходящий слот. На отчёте с
    живого принтера 27.08.2026 в одном коробе оказались два слота с ОДНИМ И ТЕМ ЖЕ материалом
    одного цвета (T1B и T1C, PETG 09ea7ae) — отличить их по данным принтера нечем, и программа
    показывала T1B как заправленный, хотя с тем же успехом печатать мог T1C. С этого выпуска:
    подходит ровно один слот — он и есть; подходит несколько — честное «не знаю» (-1).
    Списание филамента опирается на это же значение, поэтому цена ошибки — неверный учёт.
    """
    cands = _loaded_candidates(trays, rack)
    return cands[0] if len(cands) == 1 else -1


def parse(box_obj, rack_obj=None):
    """Разобрать состояние CFS. -> {trays, now, units, shape, boxes}.

    trays — слоты в том же виде, в каком карточка рисует слоты AMS, плюс поля CFS
    (label «T1B», code, percent, vendor). now — заправленный слот, если его можно утверждать,
    иначе -1; now_candidates — все слоты, подходящие под заправленный материал (их может быть
    несколько, и тогда выбрать один нельзя). Чистая функция: ни сети, ни времени, ни состояния.
    """
    if not isinstance(box_obj, dict):
        return {"trays": [], "now": -1, "now_candidates": [], "units": [], "shape": "unknown", "boxes": 0}
    trays, units = _parse_material_boxes(box_obj)
    shape = "materialBoxs"
    if trays is None:
        trays, units = _parse_units(box_obj)
        shape = "units" if trays else "unknown"
    if not trays:
        return {"trays": [], "now": -1, "now_candidates": [], "units": units or [],
                "shape": shape if units else "unknown", "boxes": len(units or [])}
    trays.sort(key=lambda t: t["index"])
    #  now_candidates отдаётся наружу, чтобы интерфейс мог честно объяснить: «заправлен один из
    #  этих, точно не знаем», вместо того чтобы молча ничего не подсвечивать.
    cands = _loaded_candidates(trays, rack_obj)
    return {"trays": trays, "now": (cands[0] if len(cands) == 1 else -1),
            "now_candidates": cands, "units": units, "shape": shape, "boxes": len(units)}


def raw_keys(box_obj, limit=40):
    """Имена ключей ответа — для диагностики, когда структура не опознана."""
    if not isinstance(box_obj, dict):
        return []
    out = []
    for k in list(box_obj.keys())[:limit]:
        v = box_obj.get(k)
        kind = type(v).__name__
        if isinstance(v, dict):
            kind = "dict(%s)" % ",".join(list(v.keys())[:6])
        elif isinstance(v, list):
            kind = "list[%d]" % len(v)
        out.append("%s: %s" % (k, kind))
    return out
