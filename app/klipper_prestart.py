# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.833 — capability-driven предстартовые операции для Klipper/Moonraker.

ЗАЧЕМ. У Bambu есть окно «Параметры запуска» (таймлапс, калибровка потока, автокалибровка стола,
источник филамента). Для Klipper копировать эти пункты НЕЛЬЗЯ — у Moonraker/Klipper другой набор
возможностей, и он РАЗНЫЙ у каждого принтера (зависит от printer.cfg и макросов). Этот модуль по
РЕАЛЬНЫМ read-only данным Moonraker (список objects, список G-code команд, секции конфигурации)
строит список ДОКАЗАННО поддерживаемых предстартовых операций и — что критично — является ЕДИНЫМ
источником правды об allowlist.

БЕЗОПАСНОСТЬ (backend — authority):
  • клиент НИКОГДА не передаёт сырой G-code или имя макроса — только заранее известные option ID;
  • операция попадает в план ТОЛЬКО если она в allowlist И доказана в конфигурации И явно выбрана
    И безопасна перед каждой печатью И не «управляется файлом»;
  • по умолчанию всё ВЫКЛ, единственный безопасный дефолт — «Как в файле» (file_controlled);
  • неизвестные/недоказанные/небезопасные option ID молча отбрасываются (fail-closed).

Модуль ЧИСТЫЙ (без сети): discover_* принимает уже полученные оффлайн/тестом словари. Никогда не бросает.
"""

# ── Реестр допустимых предстартовых операций (ALLOWLIST) ─────────────────────────────────────────
# Каждая операция доказывается ПРИСУТСТВИЕМ printer-object И/ИЛИ доступностью G-code команды.
#   need_object   — object из /printer/objects/list, доказывающий, что фича сконфигурирована;
#   need_command  — G-code команда из /printer/gcode/help (или config-макрос), которую реально шлём;
#   command       — ТА САМАЯ строка, которую backend отправит (никогда не из клиента);
#   safe_each_print — можно ли безопасно выполнять перед КАЖДОЙ печатью автоматически;
#   auto_execute  — разрешено ли backend'у выполнять её как pre-command (иначе — только информируем).
# NB: операции, чья ФАКТИЧЕСКАЯ завершённость по состоянию Klipper не доказана в этом релизе
# (screws_tilt — ручная калибровка винтов), помечены auto_execute=False и safe_each_print=False:
# показываем как справочные, но НЕ выполняем автоматически (ЭТАП 13).
#
# Alpha 2.838 — УРОВНИ ДОКАЗАТЕЛЬСТВА. Прежний булев `supported` отвечал на вопрос «команда
# существует?», а интерфейс трактовал ответ как «операция будет выполнена». Между этими двумя
# утверждениями и жил дефект приёмки: галочка обещала калибровку, которой не происходило.
# Теперь у каждой возможности есть ЯВНОЕ состояние:
#   unsupported          — не доказана вовсе, выбрать нельзя;
#   detected             — команда есть, но предпосылки не доказаны (нет объекта) — только справочно;
#   supported_manual     — доказана, но ГАРАНТИРОВАТЬ автоматическое выполнение нельзя
#                          (ручная операция либо vendor-макрос, переопределяющий встроенную команду);
#   supported_automatic  — доказаны команда, предпосылки, порядок и критерий завершения — и ТОЛЬКО
#                          такое состояние даёт активный флажок;
#   file_controlled      — операцию уже выполняет сам файл/стартовый макрос, второй раз не шлём.
STATE_UNSUPPORTED = "unsupported"
STATE_DETECTED = "detected"
STATE_MANUAL = "supported_manual"
STATE_AUTOMATIC = "supported_automatic"
STATE_FILE_CONTROLLED = "file_controlled"

# Откуда взялась возможность (для честной подписи в интерфейсе).
SRC_BUILTIN = "klipper_builtin"       # встроенная команда Klipper
SRC_PRINTER_MACRO = "printer_macro"   # gcode_macro в конфигурации принтера
SRC_FILE = "file"                     # операция задана самим G-code/стартовым макросом

# Причины, по которым состояние ниже автоматического (безопасные коды, без деталей конфигурации).
WHY_NO_OBJECT = "object_missing"
WHY_NO_COMMAND = "command_missing"
WHY_MANUAL_OP = "manual_operation"
WHY_VENDOR_OVERRIDE = "vendor_override"
WHY_FILE_MACRO = "file_start_macro"
WHY_FILE_EXPLICIT = "file_explicit_call"

PRESTART_OPS = (
    {
        "id": "bed_mesh_calibrate",
        "label_ru": "Калибровка стола (bed mesh)",
        "label_en": "Bed mesh calibration",
        "explain_ru": "Строит новую карту неровностей стола перед печатью.",
        "explain_en": "Builds a fresh bed-mesh before printing.",
        "need_object": "bed_mesh",
        "need_command": "BED_MESH_CALIBRATE",
        "command": "BED_MESH_CALIBRATE",
        "safe_each_print": True,
        "auto_execute": True,
        "builtin": True,     # штатная команда Klipper; одноимённый gcode_macro = vendor-переопределение
        "need_homed": True,  # без запаркованных осей Klipper откажет; сами G28 НЕ шлём (не доказано)
    },
    {
        "id": "quad_gantry_level",
        "label_ru": "Выравнивание портала (QGL)",
        "label_en": "Quad gantry level",
        "explain_ru": "Выравнивает портал по четырём точкам (только принтеры с QGL).",
        "explain_en": "Levels the gantry at four points (QGL printers only).",
        "need_object": "quad_gantry_level",
        "need_command": "QUAD_GANTRY_LEVEL",
        "command": "QUAD_GANTRY_LEVEL",
        "safe_each_print": True,
        "auto_execute": True,
        "builtin": True,
        "need_homed": True,
    },
    {
        "id": "z_tilt_adjust",
        "label_ru": "Выравнивание оси Z (Z-tilt)",
        "label_en": "Z tilt adjust",
        "explain_ru": "Компенсирует перекос по нескольким Z-моторам.",
        "explain_en": "Compensates skew across multiple Z motors.",
        "need_object": "z_tilt",
        "need_command": "Z_TILT_ADJUST",
        "command": "Z_TILT_ADJUST",
        "safe_each_print": True,
        "auto_execute": True,
        "builtin": True,
        "need_homed": True,
    },
    {
        "id": "clean_nozzle",
        "label_ru": "Очистка сопла",
        "label_en": "Clean nozzle",
        "explain_ru": "Выполняет пользовательский макрос очистки сопла (если задан).",
        "explain_en": "Runs the printer's nozzle-cleaning macro (if defined).",
        "need_object": None,
        "need_command": "CLEAN_NOZZLE",
        "command": "CLEAN_NOZZLE",
        "safe_each_print": True,
        "auto_execute": True,
        "builtin": False,    # это ВСЕГДА пользовательский макрос — переопределять нечего
        "need_homed": False,
    },
    {
        "id": "screws_tilt",
        "label_ru": "Проверка винтов стола (справочно)",
        "label_en": "Bed screws check (informational)",
        "explain_ru": "Ручная калибровка винтов — результат нужно смотреть вручную, автоматически не запускается.",
        "explain_en": "Manual screw calibration — results are read by hand; never auto-run.",
        "need_object": "screws_tilt_adjust",
        "need_command": "SCREWS_TILT_CALCULATE",
        "command": "SCREWS_TILT_CALCULATE",
        "safe_each_print": False,
        "auto_execute": False,
        "builtin": True,
        "need_homed": True,
    },
)

# Быстрый доступ по id.
_OPS_BY_ID = {op["id"]: op for op in PRESTART_OPS}

# Единственный безопасный дефолтный режим: печать «как в файле» (никаких доп. операций).
FILE_CONTROLLED = "file_controlled"

# Известные имена стартовых макросов (справочно для UI: «обнаружен стартовый макрос»).
_START_MACROS = ("START_PRINT", "PRINT_START")


def _upper_set(items):
    """Множество имён в верхнем регистре без пустых. Никогда не бросает (не-итерируемое -> пусто)."""
    out = set()
    try:
        for x in (items or []):
            s = str(x or "").strip()
            if s:
                out.add(s.upper())
    except TypeError:
        return set()
    return out


def _lower_set(items):
    out = set()
    try:
        for x in (items or []):
            s = str(x or "").strip()
            if s:
                out.add(s.lower())
    except TypeError:
        return set()
    return out


def discover_capabilities(objects=None, gcode_commands=None, config_macros=None,
                          moonraker_version="", klipper_version=""):
    """По read-only данным Moonraker собрать capability sheet. Никогда не бросает.

    objects        — имена из /printer/objects/list (напр. 'bed_mesh', 'quad_gantry_level');
    gcode_commands — доступные G-code команды из /printer/gcode/help (ключи), в т.ч. макросы;
    config_macros  — имена секций 'gcode_macro X' из configfile (для обнаружения стартового макроса).

    → dict: {capabilities:[...], start_macro: str|'', moonraker_version, klipper_version}.
    Каждая capability: id/label_ru/label_en/explain_*/evidence/supported/safe_each_print/auto_execute/
    file_controlled(False пока)/default(False). Поле macro/command наружу НЕ отдаём в клиентском
    контракте отдельно — оно есть в записи, но backend НЕ принимает его обратно от клиента.
    """
    obj = _lower_set(objects)
    cmds = _upper_set(gcode_commands)
    macros = _upper_set(config_macros)
    caps = []
    for op in PRESTART_OPS:
        need_obj = op["need_object"]
        need_cmd = op["need_command"]
        has_obj = (need_obj is None) or (str(need_obj).lower() in obj)
        in_help = (need_cmd is not None) and (str(need_cmd).upper() in cmds)
        in_macro = (need_cmd is not None) and (str(need_cmd).upper() in macros)
        has_cmd = (need_cmd is None) or in_help or in_macro
        supported = bool(has_obj and has_cmd)
        if need_obj is not None and need_cmd is not None:
            evidence = "object:%s + command:%s" % (need_obj, need_cmd)
        elif need_cmd is not None:
            evidence = "command:%s" % need_cmd
        else:
            evidence = "object:%s" % need_obj
        # ── Alpha 2.838: уровень доказательства, а не булев «команда нашлась» ────────────────
        # vendor_override — имя ВСТРОЕННОЙ команды перекрыто gcode_macro в конфигурации принтера.
        # Что делает такой макрос, из read-only данных доказать НЕЛЬЗЯ: он может быть обёрткой,
        # заглушкой или выполнять совсем другое. Поэтому автоматическим он не становится никогда —
        # ровно этот случай и породил приёмочный дефект «галочка есть, калибровки нет».
        overridden = bool(op.get("builtin")) and in_macro
        source = SRC_PRINTER_MACRO if in_macro else (SRC_BUILTIN if in_help else "")
        if not has_cmd:
            state, why = STATE_UNSUPPORTED, WHY_NO_COMMAND
        elif not has_obj:
            state, why = STATE_DETECTED, WHY_NO_OBJECT
        elif not op["auto_execute"] or not op["safe_each_print"]:
            state, why = STATE_MANUAL, WHY_MANUAL_OP
        elif overridden:
            state, why = STATE_MANUAL, WHY_VENDOR_OVERRIDE
        else:
            state, why = STATE_AUTOMATIC, ""
        caps.append({
            "id": op["id"],
            "label_ru": op["label_ru"], "label_en": op["label_en"],
            "explain_ru": op["explain_ru"], "explain_en": op["explain_en"],
            "evidence": evidence if supported else "",
            "supported": supported,
            "safe_each_print": bool(op["safe_each_print"]),
            "auto_execute": bool(op["auto_execute"]),
            "file_controlled": False,
            "default": False,                 # по умолчанию ВСЁ выкл (кроме file_controlled-режима)
            # Новая модель (Alpha 2.838). Прежние поля выше СОХРАНЕНЫ — старый контракт не сломан.
            "state": state,
            "state_reason": why,
            "source": source,
            "vendor_override": overridden,
        })
    # Обнаруженный стартовый макрос (справочно).
    start_macro = ""
    for m in _START_MACROS:
        if m in cmds or m in macros:
            start_macro = m
            break
    return {
        "capabilities": caps,
        "start_macro": start_macro,
        "moonraker_version": str(moonraker_version or ""),
        "klipper_version": str(klipper_version or ""),
    }


# ── Анализ G-code файла: что уже делает сам файл (не запускаем второй раз) ─────────────────────────
# Ищем в НАЧАЛЬНЫХ строках файла вызовы, доказывающие, что операция уже выполняется слайсером/макросом.
_FILE_MARKERS = {
    "bed_mesh_calibrate": ("BED_MESH_CALIBRATE",),
    "quad_gantry_level": ("QUAD_GANTRY_LEVEL",),
    "z_tilt_adjust": ("Z_TILT_ADJUST",),
    "clean_nozzle": ("CLEAN_NOZZLE",),
}


def _gcode_command_lines(sample_text):
    """Реальные КОМАНДНЫЕ строки начала файла: комментарии убраны, регистр верхний.

    Alpha 2.838: прежняя проверка искала подстроку по всему тексту, включая комментарии и
    base64-миниатюру слайсера. Строка вида «; START_PRINT задаётся в printer.cfg» или случайное
    совпадение внутри миниатюры ОБЪЯВЛЯЛИ операцию «управляемой файлом» — и выбранная
    пользователем калибровка молча исчезала из плана. Теперь смотрим только на команды.
    """
    out = []
    for raw in str(sample_text or "").split("\n"):
        line = raw.split(";", 1)[0].strip()          # всё после ';' — комментарий
        if line:
            out.append(line.upper())
    return out


def analyze_gcode_start(sample_text):
    """По НАЧАЛУ g-code вернуть МНОЖЕСТВО op-id, которые файл выполняет сам. Никогда не бросает.

    Совпадением считается ВЫЗОВ команды в начале командной строки, а не подстрока где угодно.
    START_PRINT/PRINT_START по-прежнему считается «управляется файлом» для калибровки стола:
    что именно делает стартовый макрос, из файла доказать нельзя, а запускать калибровку вторым
    заходом поверх макроса — небезопасно. Подробную причину даёт file_control_reasons().
    """
    return set(file_control_reasons(sample_text).keys())


def file_control_reasons(sample_text):
    """{op_id: причина} — ПОЧЕМУ операция считается управляемой файлом. Никогда не бросает.

    WHY_FILE_EXPLICIT — файл сам вызывает эту команду. Это ЕДИНСТВЕННОЕ основание: команда
    стоит в файле, её видно, доказывать нечего.

    ── Alpha 2.841. ROOT CAUSE реальной приёмки ────────────────────────────────────────────
    Здесь была ещё одна ветка: если файл вызывает стартовый макрос (START_PRINT/PRINT_START),
    калибровка объявлялась «управляемой файлом» с причиной WHY_FILE_MACRO. Основанием служило
    ОДНО ИМЯ, а комментарий рядом честно признавал: «внутри которого калибровка не проверяема».
    То есть из НЕДОКАЗУЕМОСТИ делался вывод в пользу бездействия — fail-open ровно там, где
    весь остальной модуль fail-closed.

    Последствие на реальном Creality K2 Plus: START_PRINT стоит в шапке ЛЮБОГО файла из
    Creality Print, поэтому Farm Manager не отправлял калибровку НИКОГДА — ни в первую печать,
    ни во вторую, молча и с успешным результатом. Карту снимал сам принтер внутри своего
    BOX_START_PRINT, а тот делает замер, только когда активной сетки нет: после включения —
    делал, второй раз подряд — уже нет. Пользователь видел «галочка стоит, замера нет».

    Диагностический отчёт того же принтера при этом ПРЯМО говорит обратное:
    start_macro_analysis.performs_bed_mesh=false. Доказательство у нас было, а решение
    принималось по совпадению имени.

    Теперь стартовый макрос разбирается там, где для этого есть данные, — в
    klipper_contract_probe.resolve_bed_mesh_plan по ГРАФУ ВЫЗОВОВ с телами макросов: доказано,
    что он калибрует → MODE_FILE (наша калибровка была бы второй); доказано, что чистит или
    подменяет сетку → автоматический путь закрыт; недоказуемо → калибруем сами ДО запуска
    файла. Имя стартового макроса больше не решает ничего.
    """
    reasons = {}
    lines = _gcode_command_lines(sample_text)
    if not lines:
        return reasons

    def _calls(name):
        for ln in lines:
            if ln == name or ln.startswith(name + " ") or ln.startswith(name + "="):
                return True
        return False

    for op_id, markers in _FILE_MARKERS.items():
        for mk in markers:
            if _calls(mk):
                reasons[op_id] = WHY_FILE_EXPLICIT
                break
    return reasons


def merge_file_controlled(sheet, file_controlled_ids):
    """Проставить file_controlled=True для операций, которые уже делает файл (их нельзя выбирать).

    Принимает как множество id, так и {id: причина} из file_control_reasons(). Состояние
    возможности переводится в file_controlled — интерфейс обязан показать это ЯВНО, а не
    молча потерять выбор пользователя (дефект приёмки Alpha 2.837).
    """
    fc = file_controlled_ids or {}
    reasons = fc if isinstance(fc, dict) else {k: WHY_FILE_EXPLICIT for k in fc}
    for cap in (sheet.get("capabilities") or []):
        if cap["id"] in reasons:
            cap["file_controlled"] = True
            cap["state"] = STATE_FILE_CONTROLLED
            cap["state_reason"] = reasons[cap["id"]]
            cap["source"] = SRC_FILE
    return sheet


# ── Валидация выбора клиента и построение плана (backend authority) ───────────────────────────────
def validate_selection(sheet, selected_ids):
    """Отфильтровать клиентский выбор до ДОПУСТИМЫХ операций. → (accepted_ids, rejected_ids).

    Принимаем ТОЛЬКО известный allowlist-id, который: supported, safe_each_print, auto_execute и НЕ
    file_controlled. Всё прочее (неизвестный id, сырой G-code, имя макроса, недоказанная/небезопасная/
    управляемая файлом операция) отбрасывается в rejected. Fail-closed."""
    by_id = {c["id"]: c for c in (sheet.get("capabilities") or [])}
    accepted, rejected = [], []
    for raw in (selected_ids or []):
        oid = str(raw or "").strip()
        cap = by_id.get(oid)
        # Alpha 2.838: единственный пропуск — ДОКАЗАННО автоматическая операция. Прежний набор
        # условий (supported+safe+auto+not file_controlled) сохранён внутри state и дополнен
        # запретом vendor-переопределений, выполнение которых гарантировать нельзя.
        if (cap and oid in _OPS_BY_ID and cap.get("state") == STATE_AUTOMATIC
                and cap.get("supported") and cap.get("safe_each_print")
                and cap.get("auto_execute") and not cap.get("file_controlled")):
            if oid not in accepted:
                accepted.append(oid)
        else:
            rejected.append(oid)
    return accepted, rejected


def plan_dispositions(sheet, selected_ids):
    """Судьба КАЖДОЙ выбранной пользователем операции. → [{id, disposition, state, reason}].

    Нужна, чтобы выбор НИКОГДА не исчезал молча: и журнал, и интерфейс обязаны показать, что
    именно произошло с галочкой. disposition: 'planned' | 'skipped'.
    """
    by_id = {c["id"]: c for c in (sheet.get("capabilities") or [])}
    accepted, _rej = validate_selection(sheet, selected_ids)
    acc = set(accepted)
    out = []
    for raw in (selected_ids or []):
        oid = str(raw or "").strip()
        cap = by_id.get(oid) or {}
        out.append({
            "id": oid,
            "disposition": "planned" if oid in acc else "skipped",
            "state": str(cap.get("state") or (STATE_UNSUPPORTED if oid not in _OPS_BY_ID else "")),
            "reason": str(cap.get("state_reason") or ("unknown_option" if oid not in _OPS_BY_ID else "")),
        })
    return out


def build_prestart_plan(sheet, selected_ids):
    """Построить список G-code команд предстартовой подготовки ИЗ ALLOWLIST по валидному выбору.
    Клиентский текст сюда не попадает НИКОГДА — команды берутся из PRESTART_OPS по id. Порядок —
    как в PRESTART_OPS (сначала грубое выравнивание, затем bed mesh, затем очистка — детерминирован).
    → list[str]."""
    accepted, _ = validate_selection(sheet, selected_ids)
    acc = set(accepted)
    plan = []
    for op in PRESTART_OPS:                   # детерминированный порядок реестра
        if op["id"] in acc:
            plan.append(op["command"])
    return plan


def requires_homed(selected_ids):
    """Требует ли ХОТЯ БЫ ОДНА из операций запаркованных осей. → bool.

    Alpha 2.838. Farm Manager НИКОГДА не отправляет G28 сам: контракт «макрос паркует сам»
    для конкретного принтера не доказан, а лишняя парковка — это движение железа без спроса.
    Вместо этого предусловие ПРОВЕРЯЕТСЯ по toolhead.homed_axes, и при невыполнении печать не
    начинается с понятным объяснением.
"""
    for raw in (selected_ids or []):
        op = _OPS_BY_ID.get(str(raw or "").strip())
        if op and op.get("need_homed"):
            return True
    return False


def sanitize_preferences(sheet, prefs):
    """Очистить сохранённые per-printer предпочтения: оставить только известные допустимые id со
    значением True. Неизвестные/недоказанные/небезопасные/управляемые файлом — выкидываем. → dict.
    Так «старые» предпочтения после смены конфигурации/макросов безопасно игнорируются."""
    out = {}
    by_id = {c["id"]: c for c in (sheet.get("capabilities") or [])}
    if isinstance(prefs, dict):
        for k, v in prefs.items():
            oid = str(k or "").strip()
            cap = by_id.get(oid)
            if (cap and oid in _OPS_BY_ID and cap.get("supported") and cap.get("safe_each_print")
                    and cap.get("auto_execute") and not cap.get("file_controlled")):
                out[oid] = bool(v)
    return out
