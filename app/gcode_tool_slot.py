# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.945 — выбор ячейки CFS в файле печати. Чистые функции, без сети и файловой системы.

ЗАЧЕМ. Владелец: «при запуске на печать нет выбора ячейки материала». У Bambu слот уезжает
вместе с командой запуска, у Creality K2 — НЕТ: при обычной загрузке файла по протоколу
Moonraker сопоставление филамента не работает, слот задаётся В САМОМ ФАЙЛЕ.

КОНТРАКТ СНЯТ С НАСТОЯЩИХ ФАЙЛОВ, А НЕ ПРИДУМАН. 04.09.2026 владелец прислал ДВЕ ПАРЫ файлов
Creality Print V6.3.1.3548 для его K2 Plus. Первая пара оказалась нарезана на один и тот же
слот (различались только время и внутренний номер) — она показала лишь механизм. Вторая пара
нарезана по-настоящему на разные слоты, и она показала ВЕСЬ набор различий:

    START_PRINT EXTRUDER_TEMP=250 BED_TEMP=70
    T0                     ← слот 1 короба          T1        ← слот 2 короба
    M104 S250                                       M104 S250

    ; filament used [mm] = 1197.41, 0.00            ; filament used [mm] = 0.00, 1197.41
    ; filament used [cm3] = 2.88, 0.00              ; filament used [cm3] = 0.00, 2.88
    ; filament used [g] = 3.66, 0.00                ; filament used [g] = 0.00, 3.66
    ; filament cost = 0.05, 0.00                    ; filament cost = 0.00, 0.05
    ; default_filament_colour = #9ea7ae;            ; default_filament_colour = ;#BEEB61
    ; default_filament_type = PETG;                 ; default_filament_type = ;PETG

То есть слот задаётся строкой `T<n>`, а вдобавок слайсер ПЕРЕСТАВЛЯЕТ по номеру слота
служебные строки: сколько филамента ушло и какой это филамент. Значения перечислены по одному
на каждый филамент проекта, и занят ровно тот номер, что стоит в строке `T<n>`. Здесь делается
то же самое — иначе в файле остаётся написано, что печать идёт из первой ячейки, хотя команда
уводит её во вторую.

Нумерация подтверждена дважды: таблицей `box.map` самого принтера (T1A, T1B, T1C, T1D, T2A…)
и вторым файлом владельца — он нарезал его на вторую ячейку и получил `T1`. Значит T0 = T1A,
T1 = T1B и далее; тот же порядок у нас в `cfs_trays` (unit*4 + slot).

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Слайсер меняет ещё три вещи, которые повторять не нужно и нельзя:
  * оценку времени (`M73`, `;TIME_ELAPSED`, «estimated printing time») — печать из другой
    ячейки дольше на время заправки, но это только показания прогресса, а честно пересчитать
    их нельзя: время заправки знает принтер, а не мы;
  * картинку предпросмотра — она нарисована цветом филамента и заново не рисуется;
  * повторную команду нагрева `M104` в начале — она дублирует уже стоящую в файле с той же
    температурой, а дописывать строки в чужой файл здесь запрещено.

ПРАВИЛА БЕЗОПАСНОСТИ, заложенные здесь:
  * НИЧЕГО НЕ ДОПИСЫВАЕМ. Меняются только строки, которые слайсер сам положил в файл. Нет
    строки выбора — значит выбора в этом файле нет, и мы честно об этом говорим.
  * Строк `T<n>` НЕСКОЛЬКО — файл многоцветный: не трогаем вовсе. Подмена одного номера в
    многоцветной печати сломала бы её.
  * Байты вне изменённых строк не меняются: переносы строк, комментарии в конце строки и
    кодировка остаются как были.
"""
import re

#  Строка выбора инструмента: T и число, дальше только пробелы и, возможно, комментарий.
#  Осознанно строго: `T0 X10` — это уже не выбор инструмента, и трогать такое нельзя.
_TOOL_RE = re.compile(rb"^T(\d+)[ \t]*(;[^\r\n]*)?$")

STATUS_CHANGED = "changed"            # номер заменён
STATUS_SAME = "same"                  # в файле уже нужный слот — файл не тронут
STATUS_NO_TOOL_LINE = "no_tool_line"  # строки выбора нет вовсе
STATUS_MULTIPLE = "multiple"          # многоцветный файл — не трогаем

#  Расход филамента: по одному числу на филамент проекта, через запятую.
_USED_KEYS = (b"; filament used [mm] = ", b"; filament used [cm3] = ",
              b"; filament used [g] = ", b"; filament cost = ")
#  Какой филамент пошёл в дело: список через точку с запятой, заполнен один номер.
#  Рядом — полный список проекта, откуда берётся значение для нового номера.
_DEFAULT_KEYS = ((b"; default_filament_colour = ", b"; filament_colour = "),
                 (b"; default_filament_type = ", b"; filament_type = "))


#  16.10.2026 (R-148): поиск нужных строк регулярным выражением прямо по байтам файла. Прежде
#  каждый вызов резал на строки ВЕСЬ файл: на G-code K2 в 30 МБ это 5 с и 200 МБ памяти, а запуск
#  печати зовёт разбор трижды, причём из обработчиков веб-запросов, — интерфейс всей фермы
#  замирал. Здесь ищется только «перевод строки + начало нужной строки»: такой поиск
#  идёт по образцу с постоянным началом и укладывается в сотые доли секунды. Правила те же, что у
#  построчного разбора: строка — до «\n», один «\r» перед ним не входит в строку.
_TOOL_BODY = rb"(T(\d+)[ \t]*(?:;[^\r\n]*)?)\r?(?=\n|\Z)"
_TOOL_FIRST = re.compile(_TOOL_BODY)                  # строка выбора в самом начале файла
_TOOL_NEXT = re.compile(rb"\n" + _TOOL_BODY)          # и после каждого перевода строки


def _as_bytes(data):
    """Байты файла или None (тогда совпадений нет). bytes возвращается тем же объектом, без копии."""
    if not isinstance(data, (bytes, bytearray)):
        return None
    return bytes(data)


def find_tool_lines(data):
    """Все строки выбора инструмента. -> [{line, start, end, index, text}]

    data — байты файла. Границы строки точные, чтобы не трогать всё прочее.
    Никогда не бросает: неразбираемый файл просто не даёт совпадений."""
    out = []
    data = _as_bytes(data)
    if data is None:
        return out
    found = []
    m = _TOOL_FIRST.match(data)
    if m:
        found.append(m)
    found.extend(_TOOL_NEXT.finditer(data))
    line, pos = 1, 0
    for m in found:
        start, end = m.start(1), m.end(1)
        line += data.count(b"\n", pos, start)         # номер строки — по числу переводов до неё
        pos = start
        core = data[start:end]
        out.append({"line": line, "start": start, "end": end,
                    "index": int(m.group(2)),
                    "text": core.decode("ascii", "replace")})
    return out


#  Служебные строки о филаментах (расход и списки проекта) — тем же быстрым поиском.
_META_KEYS = _USED_KEYS + tuple(k for pair in _DEFAULT_KEYS for k in pair)
_META_BODY = rb"(?:" + rb"|".join(re.escape(k) for k in _META_KEYS) + rb")[^\n]*"
_META_FIRST = re.compile(_META_BODY)
_META_NEXT = re.compile(rb"\n(" + _META_BODY + rb")")


def _meta_lines(data):
    """Строки, которые начинаются с одного из ключей _META_KEYS, по порядку в файле.
    -> [(start, end, core)]: end — конец строки без перевода строки, core — сама строка без
    завершающего «\\r». Так строку можно заменить по месту, не трогая ни байта вокруг."""
    out = []
    data = _as_bytes(data)
    if data is None:
        return out
    spans = []
    m = _META_FIRST.match(data)
    if m:
        spans.append((m.start(), m.end()))
    spans.extend((x.start(1), x.end(1)) for x in _META_NEXT.finditer(data))
    for start, end in spans:
        core = data[start:end]
        if core.endswith(b"\r"):
            core, end = core[:-1], end - 1
        out.append((start, end, core))
    return out


def _split_semi(value):
    """`#9ea7ae;#BEEB61` -> ['#9ea7ae', '#BEEB61']. Пустые значения сохраняются."""
    return [x.strip() for x in value.decode("utf-8", "replace").split(";")]


def read_meta(data):
    """Что файл говорит о филаментах, ничего не меняя. -> dict

    Возвращает списки проекта (`types`, `colours`), пометки «этот филамент пошёл в дело»
    (`default_types`, `default_colours`), расход по номерам (`used`) и номер из строки `T<n>`.
    Всё — как есть в файле; отсутствующие строки просто не попадают в ответ."""
    res = {"tool": None, "types": [], "colours": [],
           "default_types": [], "default_colours": [], "used": {}}
    tools = find_tool_lines(data)
    if len(tools) == 1:
        res["tool"] = tools[0]["index"]
    for _s, _e, core in _meta_lines(data):
        if not core.startswith(b"; "):
            continue
        for key in _USED_KEYS:
            if core.startswith(key):
                res["used"][key.decode("ascii")] = [
                    x.strip() for x in core[len(key):].decode("ascii", "replace").split(",")]
        if core.startswith(b"; filament_type = "):
            res["types"] = _split_semi(core[len(b"; filament_type = "):])
        elif core.startswith(b"; filament_colour = "):
            res["colours"] = _split_semi(core[len(b"; filament_colour = "):])
        elif core.startswith(b"; default_filament_type = "):
            res["default_types"] = _split_semi(core[len(b"; default_filament_type = "):])
        elif core.startswith(b"; default_filament_colour = "):
            res["default_colours"] = _split_semi(core[len(b"; default_filament_colour = "):])
    return res


def sliced_material(data):
    """Каким филаментом нарезан файл. -> строка вроде 'PETG' (или '' — не сказано).

    Нужно перед подменой ячейки: температуры в файле уже прошиты (`START_PRINT
    EXTRUDER_TEMP=250`, `M104 S250`), и печатать PLA по программе для PETG — это сгоревший
    пруток и забитое сопло. Сравнение с тем, что лежит в выбранной ячейке, делает вызывающий."""
    meta = read_meta(data)
    tool = meta.get("tool")
    types = meta.get("types") or []
    if isinstance(tool, int) and 0 <= tool < len(types) and types[tool]:
        return types[tool]
    for v in (meta.get("default_types") or []):
        if v:
            return v
    for v in types:
        if v:
            return v
    return ""


def same_material(a, b):
    """Один ли это материал. 'PETG' и ' petg ' — да; 'PETG' и 'PLA' — нет.

    Сравнение мягкое (регистр и незначащие знаки не считаются), потому что имя материала
    приходит из двух разных мест: из файла слайсера и из короба принтера."""
    def norm(x):
        return re.sub(r"[^a-z0-9]+", "", str(x or "").lower())
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return True                      # нечего сравнивать — запрещать не за что
    return na == nb


def _zero_like(sample):
    """Ноль в том же виде, что и соседние числа: `1197.41` -> `0.00`, `12` -> `0`."""
    s = sample.decode("ascii", "replace") if isinstance(sample, (bytes, bytearray)) else str(sample)
    if "." in s:
        return ("0." + "0" * len(s.split(".", 1)[1])).encode("ascii")
    return b"0"


def _retarget_used(value, frm, to):
    """Расход филамента переставить с номера frm на номер to. -> новые байты или None.

    Список дополняется нулями, если выбран номер, которого в проекте не было: слайсер
    перечисляет только филаменты проекта, а короб у принтера шире."""
    parts = [x.strip() for x in value.split(b",")]
    if not parts:
        return None
    src = parts[frm] if 0 <= frm < len(parts) else b""
    if not src or set(src.decode("ascii", "replace")) <= set("0."):
        #  На месте старого номера пусто или ноль — берём единственное непустое значение.
        nz = [p for p in parts if p and set(p.decode("ascii", "replace")) > set("0.")]
        if len(nz) != 1:
            return None                  # непонятно, что переставлять — лучше не трогать
        src = nz[0]
    zero = _zero_like(src)
    out = [zero] * max(len(parts), to + 1)
    out[to] = src
    return b", ".join(out)


def _retarget_default(value, full, to, fallback=None):
    """Пометку «этот филамент в деле» перенести на номер to. -> новые байты или None.

    Значение берётся из полного списка проекта; если выбранного номера в проекте не было —
    из fallback (что принтер сообщает о самой ячейке), иначе остаётся пустым."""
    parts = value.split(b";")
    full_parts = full.split(b";") if full is not None else []
    if 0 <= to < len(full_parts) and full_parts[to].strip():
        val = full_parts[to].strip()
    elif fallback:
        val = str(fallback).strip().encode("utf-8", "replace")
    else:
        val = b""
    out = [b""] * max(len(parts), len(full_parts), to + 1)
    out[to] = val
    return b";".join(out)


def describe(data):
    """Что можно сказать о выборе слота в этом файле, ничего не меняя. -> dict."""
    lines = find_tool_lines(data)
    if not lines:
        return {"status": STATUS_NO_TOOL_LINE, "count": 0, "current": None, "lines": []}
    if len(lines) > 1:
        return {"status": STATUS_MULTIPLE, "count": len(lines),
                "current": lines[0]["index"], "lines": [x["line"] for x in lines[:8]]}
    return {"status": STATUS_SAME, "count": 1, "current": lines[0]["index"],
            "lines": [lines[0]["line"]]}


def _apply_meta(data, frm, to, material=None, colour=None):
    """Служебные строки привести к выбранному номеру. -> (новые байты, [какие строки])

    Правится только то, что слайсер сам меняет при выборе другого слота; ни одной новой
    строки не появляется. Не нашлась строка — просто пропускаем её."""
    data = bytes(data)
    full = {}
    meta = _meta_lines(data)                          # R-148: один быстрый поиск на оба прохода
    for _s, _e, core in meta:
        for _dkey, fkey in _DEFAULT_KEYS:
            if core.startswith(fkey):
                full[fkey] = core[len(fkey):]
    edits, touched = [], []
    for start, end, core in meta:
        new = None
        for key in _USED_KEYS:
            if core.startswith(key):
                new = _retarget_used(core[len(key):], frm, to)
                if new is not None:
                    new = key + new
                break
        if new is None:
            for dkey, fkey in _DEFAULT_KEYS:
                if core.startswith(dkey):
                    new = _retarget_default(core[len(dkey):], full.get(fkey), to,
                                            colour if b"colour" in dkey else material)
                    if new is not None:
                        new = dkey + new
                    break
        if new is not None and new != core:
            edits.append((start, end, new))
            touched.append(core.split(b" = ", 1)[0].decode("ascii", "replace").lstrip("; "))
    if not edits:
        return data, []
    out, pos = [], 0
    for start, end, new in edits:
        out.append(data[pos:start])
        out.append(new)
        pos = end
    out.append(data[pos:])
    return b"".join(out), touched


def set_tool_slot(data, slot, material=None, colour=None):
    """Поставить в файл выбор ячейки. -> (новые байты, отчёт).

    slot — индекс слота, как в cfs_trays (0 = T1A, 1 = T1B, …). Файл не подходит для замены —
    возвращаются ИСХОДНЫЕ байты и отчёт с причиной: решение, печатать или нет, принимает
    вызывающий, а молча печатать не из того слота нельзя.

    material и colour — что принтер сообщает о выбранной ячейке. Нужны только для случая,
    когда выбран слот, которого в проекте слайсера не было: тогда служебную пометку заполнить
    больше нечем. Не переданы — пометка останется пустой, печать от этого не изменится."""
    try:
        slot = int(slot)
    except Exception:
        return data, {"status": STATUS_NO_TOOL_LINE, "count": 0, "current": None,
                      "error": "slot_not_a_number"}
    if slot < 0:
        return data, {"status": STATUS_NO_TOOL_LINE, "count": 0, "current": None,
                      "error": "slot_negative"}
    lines = find_tool_lines(data)
    if not lines:
        return data, {"status": STATUS_NO_TOOL_LINE, "count": 0, "current": None, "to": slot}
    if len(lines) > 1:
        return data, {"status": STATUS_MULTIPLE, "count": len(lines),
                      "current": lines[0]["index"], "to": slot,
                      "lines": [x["line"] for x in lines[:8]]}
    one = lines[0]
    if one["index"] == slot:
        #  Файл уже нарезан на эту ячейку — не трогаем ни байта: он уйдёт таким, как есть.
        return data, {"status": STATUS_SAME, "count": 1, "current": slot, "to": slot,
                      "line": one["line"], "meta": []}
    core = bytes(data)[one["start"]:one["end"]]
    m = _TOOL_RE.match(core)
    tail = core[1 + len(m.group(1)):]                 # пробелы и комментарий — как были
    new_core = b"T" + str(slot).encode("ascii") + tail
    out = bytes(data)[:one["start"]] + new_core + bytes(data)[one["end"]:]
    out, touched = _apply_meta(out, one["index"], slot, material=material, colour=colour)
    return out, {"status": STATUS_CHANGED, "count": 1, "current": one["index"], "to": slot,
                 "line": one["line"], "was": one["text"],
                 "now": new_core.decode("ascii", "replace"), "meta": touched}


def slot_label(index, per_box=4):
    """Индекс слота -> подпись принтера (0 -> T1A). Отражает порядок box.map."""
    try:
        i = int(index)
    except Exception:
        return ""
    if i < 0:
        return ""
    letters = "ABCD"
    box, pos = divmod(i, per_box)
    if pos >= len(letters):
        return ""
    return "T%d%s" % (box + 1, letters[pos])
