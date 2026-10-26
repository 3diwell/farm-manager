# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.839 — ЯДРО безопасного сбора контракта подготовки печати Klipper/Moonraker.

ЗАЧЕМ. Alpha 2.838 доказала: включать автоматическую калибровку можно только когда известны
точная команда, предпосылки, порядок и критерий завершения. Снять эти факты умеет только сам
принтер. В 2.838 для этого был CLI (`tools/klipper_probe.py`), но у владельца принтера —
клиента — нет ни Python, ни терминала, ни адреса принтера. Поэтому ядро вынесено СЮДА, в
production-модуль: им пользуются и встроенная кнопка в Farm Manager, и прежний CLI, и тесты.
Двух реализаций протокола в проекте нет и быть не должно.

ГРАНИЦЫ БЕЗОПАСНОСТИ (проверяемые построением, см. tools/test_klipper_contract_report.py):
  * модуль НЕ открывает сокеты сам: HTTP-доступ передаётся колбэком `get_json(path)`;
  * перед КАЖДЫМ обращением путь сверяется с неизменяемым allowlist ниже — произвольный
    путь, `/printer/gcode/script`, upload, restart и запись конфигурации невозможны;
  * ни один вызов не несёт тела запроса: контракт колбэка — только чтение (GET);
  * клиент (frontend) НИКОГДА не задаёт адрес, токен, endpoint и команду;
  * отчёт проходит рекурсивную редакцию и финальную самопроверку: при малейшем следе
    адреса, токена, серийника или пути отчёт НЕ выдаётся.

Модуль никогда не бросает: любая беда превращается в секцию со статусом `unavailable`.
"""

import re

REPORT_SCHEMA = "3diwell-klipper-contract-report-v1"

# ── Статусы секций отчёта ───────────────────────────────────────────────────────────────────
ST_COMPLETE = "complete"
ST_UNAVAILABLE = "unavailable"
ST_UNSUPPORTED = "unsupported"
ST_REDACTED = "redacted"

# ── НЕИЗМЕНЯЕМЫЙ ALLOWLIST read-only эндпоинтов Moonraker ───────────────────────────────────
# Только то, что нужно для контракта подготовки. Каждый путь доказанно ничего не меняет.
# Расширять список можно ТОЛЬКО правкой этого файла: снаружи он не настраивается.
ALLOWED_PATHS = (
    "/server/info",
    "/printer/info",
    "/printer/objects/list",
    "/printer/gcode/help",
    "/printer/objects/query?configfile",
    "/printer/objects/query?toolhead&print_stats&webhooks&idle_timeout",
    "/printer/objects/query?bed_mesh",
    #  Alpha 2.887: состояние CFS (система подачи катушек K2). Объект называется `box` —
    #  подтверждено списком ожидаемых объектов K2 в открытом проекте HelixScreen. Запрос
    #  read-only и безопасен для принтеров без CFS: по документации Moonraker несуществующий
    #  объект просто отсутствует в ответе, ошибки не возникает.
    "/printer/objects/query?box&filament_rack",
)

# Явно запрещённые фрагменты — вторая линия защиты на случай ошибки в allowlist.
FORBIDDEN_FRAGMENTS = (
    "gcode/script", "/server/files/upload", "/printer/restart", "/printer/firmware_restart",
    "/printer/emergency_stop", "/machine/reboot", "/machine/shutdown", "/machine/services",
    "/server/database", "/access/", "/server/files/delete", "/printer/print/",
)


def describe_structure(value, depth=0, max_depth=4, budget=None):
    """Состав значения без домыслов: имена полей, типы, длины и простые величины.

    Alpha 2.888. Нужна, чтобы дописать разбор чужого протокола ПО ФАКТУ, а не по догадке:
    в отчёт попадает форма ответа принтера, а не наши предположения о ней. Строки режутся,
    объём ограничен — отчёт остаётся читаемым и не превращается в дамп памяти.
    """
    if budget is None:
        budget = [400]
    if budget[0] <= 0:
        return "…"
    budget[0] -= 1
    if isinstance(value, dict):
        if depth >= max_depth:
            return "dict(%d полей)" % len(value)
        return dict((str(k), describe_structure(v, depth + 1, max_depth, budget))
                    for k, v in list(value.items())[:40])
    if isinstance(value, (list, tuple)):
        if depth >= max_depth:
            return "list[%d]" % len(value)
        return [describe_structure(v, depth + 1, max_depth, budget) for v in list(value)[:16]]
    if isinstance(value, str):
        return value[:80]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return type(value).__name__


#  ── Чем на ЭТОМ принтере можно выбрать слот CFS ────────────────────────────────────────────
#  Alpha 2.943. Раздел отвечает ровно на один вопрос и ничего не выдумывает: какие способы
#  адресовать слот ФАКТИЧЕСКИ есть в конфигурации этого принтера. Ни одной команды не шлёт.
TOOL_MACRO_NAMES = tuple("T%d" % i for i in range(16))
#  Имена параметров, которыми в известных нам макросах передаётся слот или адрес короба.
#  Список — наблюдение по отчёту живого K2 Plus, а не догадка: BOX_LOAD_MATERIAL_EXTRUDE_MATERIAL
#  принимает TNN, BOX_INFO_REFRESH — ADDR и NUM.
SLOT_PARAM_HINTS = ("TNN", "ADDR", "NUM", "SLOT", "INDEX", "I", "T", "N")


def _slot_selection_section(macros, cmd_set, by_name):
    """-> раздел «выбор слота CFS»: что есть, чего нет, и что из этого следует.

    macros  — {ИМЯ: {...}} из configfile; cmd_set — команды из /printer/gcode/help;
    by_name — уже разобранные макросы (тела, параметры). Никогда не бросает."""
    try:
        tools = sorted((n for n in TOOL_MACRO_NAMES if n in macros or n in cmd_set),
                       key=lambda x: int(x[1:]))
        m8200 = by_name.get("M8200") or {}
        with_param = []
        for name, m in sorted(by_name.items()):
            ps = [p for p in (m.get("parameters") or []) if str(p).upper() in SLOT_PARAM_HINTS]
            if ps:
                with_param.append({"macro": name, "parameters": ps,
                                   "body_available": bool(((m.get("body") or {}).get("lines")))})
        if tools:
            verdict, why = "tool_macros", (
                "У принтера есть макросы смены инструмента (%s). По ним слайсер и адресует слот: "
                "номер инструмента ставится в файле печати." % ", ".join(tools))
        elif m8200.get("exists"):
            verdict, why = "vendor_macro_only", (
                "Макросов смены инструмента (T0…T15) у принтера НЕТ. Есть фирменный M8200 — "
                "по нему и идёт смена, но его параметры публично не описаны (прошивка закрыта). "
                "Пока значение параметров не доказано, выбор слота из программы делать нельзя: "
                "это нож, продувка и движение головы на живом принтере.")
        elif with_param:
            verdict, why = "feed_macro_param", (
                "Ни макросов смены инструмента, ни M8200 нет. Есть макросы подачи с параметрами, "
                "похожими на номер слота (%s) — что именно они означают, не доказано."
                % ", ".join(x["macro"] for x in with_param[:4]))
        else:
            verdict, why = "none_found", (
                "Способов адресовать слот в конфигурации принтера не найдено.")
        return {
            "status": ST_COMPLETE if (macros or cmd_set) else ST_UNAVAILABLE,
            "tool_change_macros": tools,
            "tool_change_macros_present": bool(tools),
            "m8200_present": bool(m8200.get("exists")),
            "m8200_parameters": m8200.get("parameters") or [],
            "m8200_body": (m8200.get("body") or {}),
            "macros_with_slot_like_parameter": with_param,
            "verdict": verdict,
            "verdict_ru": why,
        }
    except Exception as e:
        return {"status": ST_UNAVAILABLE, "error": "%s: %s" % (type(e).__name__, e)}


#  ── Раздел CFS отчёта: без обрезаний и с готовым разбором ──────────────────────────────────
#  Alpha 2.942. Прежний раздел звал describe_structure с настройками по умолчанию (глубина 4),
#  и вложенные списки схлопывались в заглушку: в отчёте с K2 Plus от 02.09.2026 поле
#  same_material[0][2] превратилось в строку "list[2]" — а это, судя по всему, СПИСОК СЛОТОВ с
#  тем же материалом, то есть ровно та подсказка, которой не хватало, чтобы понять, какой слот
#  заправлен. Догадку за факт выдавать нельзя, поэтому теперь раздел CFS описывается на полную
#  глубину: следующий отчёт покажет содержимое, а не заглушку.
#
#  Заодно рядом с сырым составом кладётся ВЫВОД САМОЙ ПРОГРАММЫ (app/creality_cfs.parse):
#  какие слоты она увидела, какой считает заправленным и почему. Без этого владелец присылал
#  отчёт, а разбор приходилось прогонять отдельно руками.
CFS_DEPTH = 12          # глубина описания: вложенных структур в этом ответе заведомо меньше
CFS_BUDGET = 4000       # узлов на весь раздел; ответ принтера в разы меньше


def _cfs_section(cfs_res, st_fn=None):
    """-> раздел cfs_state отчёта. Никогда не бросает: диагностика не должна падать.

    st_fn — та же оценка доступности пути, что и у остальных разделов; она живёт внутри
    сборки отчёта, поэтому передаётся сюда, а не берётся из модуля."""
    status = (cfs_res.get("status") or {}) if isinstance(cfs_res, dict) else {}
    out = {
        "status": (st_fn("/printer/objects/query?box&filament_rack", bool(status))
                   if st_fn else (ST_COMPLETE if status else ST_UNAVAILABLE)),
        #  Ровно то, что прислал принтер, но в виде состава: поля, типы, длины и простые
        #  величины — теперь на полную глубину, без заглушек вида "list[2]".
        "objects": describe_structure(status, max_depth=CFS_DEPTH, budget=[CFS_BUDGET]),
        "present": sorted(status.keys()),
    }
    try:
        from app.creality_cfs import parse as _parse
        r = _parse(status.get("box"), status.get("filament_rack"))
        out["parsed"] = {
            "shape": r.get("shape"),
            "boxes": r.get("boxes"),
            "loaded_slot_index": r.get("now"),
            "loaded_slot_label": next((t.get("label") for t in (r.get("trays") or [])
                                       if t.get("index") == r.get("now")), ""),
            "candidates": r.get("now_candidates") or [],
            "slots": [{"label": t.get("label"), "index": t.get("index"),
                       "type": t.get("type"), "percent": t.get("percent"),
                       "spent_label_left": bool(t.get("spent")),
                       "declared_when_spent": t.get("declared") or "",
                       "vendor": t.get("vendor") or ""}
                      for t in (r.get("trays") or [])],
            "units": r.get("units") or [],
        }
        #  Почему заправленный слот не определён — словами, чтобы это читалось без кода.
        if r.get("now", -1) < 0:
            cands = r.get("now_candidates") or []
            out["parsed"]["why_unknown"] = (
                "подходящих слотов нет: материал в голове не совпал ни с одним слотом"
                if not cands else
                "подходящих слотов несколько (%s) — принтер не сообщает номер заправленного"
                % ", ".join(str(c) for c in cands))
    except Exception as e:
        out["parsed_error"] = "%s: %s" % (type(e).__name__, e)
    return out


def is_allowed(path):
    """Разрешён ли путь. Всё, чего нет в allowlist, запрещено (fail-closed)."""
    p = str(path or "")
    if not p.startswith("/"):
        return False
    for bad in FORBIDDEN_FRAGMENTS:
        if bad in p:
            return False
    return p in ALLOWED_PATHS


# ── Что нас интересует в конфигурации принтера ──────────────────────────────────────────────
START_MACRO_NAMES = ("START_PRINT", "PRINT_START")
CALIBRATION_NAMES = ("BED_MESH_CALIBRATE", "Z_TILT_ADJUST", "QUAD_GANTRY_LEVEL",
                     "SCREWS_TILT_CALCULATE", "BED_MESH_PROFILE", "CLEAN_NOZZLE")
HOMING_NAMES = ("G28",)
#  Alpha 2.892: макросы смены материала CFS (Creality K2). Нужны, чтобы узнать, КАК просить
#  принтер поставить нужный слот и ЧЕМ он сообщает о завершении смены. Имена взяты из отчёта
#  живого K2 Plus — это его собственные gcode_macro. Встроенные BOX_START_PRINT,
#  BOX_NOZZLE_CLEAN, BOX_GO_TO_EXTRUDE_POS сюда не входят: у них нет тела (скомпилированный код).
FEED_MACRO_NAMES = (
    "BOX_LOAD_MATERIAL", "BOX_LOAD_MATERIAL_HEATING", "BOX_LOAD_MATERIAL_CUT_MATERIAL",
    "BOX_LOAD_MATERIAL_EXTRUDE_MATERIAL", "BOX_LOAD_MATERIAL_MATERIAL_FLUSH",
    "BOX_LOAD_MATERIAL_RETRUDE_MATERIAL", "BOX_LOAD_MATERIAL_END",
    "BOX_QUIT_MATERIAL", "BOX_QUIT_MATERIAL_HEATING", "BOX_QUIT_MATERIAL_CUT_MATERIAL",
    "BOX_QUIT_MATERIAL_RETRUDE_MATERIAL", "BOX_QUIT_MATERIAL_END",
    "BOX_INFO_REFRESH",
    #  Те же операции без приставки BOX — у прошивки они тоже есть; какая из пар принимает
    #  слот, покажет отчёт, гадать не будем.
    "LOAD_MATERIAL", "LOAD_MATERIAL_HEATING", "LOAD_MATERIAL_MATERIAL_FLUSH",
    "LOAD_MATERIAL_CLOSE_FAN2", "LOAD_MATERIAL_RESTORE_FAN2", "LOAD_MATERIAL_END",
    "QUIT_MATERIAL", "QUIT_MATERIAL_HEATING", "QUIT_MATERIAL_CUT_MATERIAL",
    "QUIT_MATERIAL_RETRUDE_MATERIAL", "QUIT_MATERIAL_END",
    #  Alpha 2.943. Владелец: «при запуске на печать нет выбора ячейки материала». Чтобы этот
    #  выбор вообще стал возможен, надо знать, ЧЕМ принтеру говорят номер слота. Публичного
    #  описания нет: прошивка K2 закрыта, Creality выложила двоичные файлы, а не исходники.
    #  Значит спрашиваем сам принтер — читаем тела ровно тех макросов, которые к этому причастны.
    #  M8200 — фирменный макрос смены инструмента (есть на K2 Plus владельца, отчёт 02.09.2026).
    "M8200",
    #  Листья цепочки смены материала: их тела скомпилированы, но отчёт хотя бы зафиксирует,
    #  что они есть и какие параметры принимают.
    "BOX_EXTRUDE_MATERIAL", "BOX_RETRUDE_MATERIAL", "BOX_CUT_MATERIAL", "BOX_MODE_WAIT",
    "BOX_SET_TEMP", "BOX_SET_PRE_LOADING", "BOX_GET_RFID", "BOX_GET_REMAIN_LEN",
    "BOX_MATERIAL_CHANGE_FLUSH", "BOX_START_PRINT", "BOX_GO_TO_EXTRUDE_POS",
    "BOX_NOZZLE_CLEAN", "BOX_MOVE_TO_SAFE_POS", "BOX_MOVE_TO_CUT", "BOX_SAVE_FAN",
    "BOX_RESTORE_FAN", "FILAMENT_RACK_SET_TEMP", "FILAMENT_RACK_FLUSH",
) + tuple("T%d" % i for i in range(16))
#  T0…T15 — смена инструмента. По обсуждениям OrcaSlicer именно ими слайсер помечает смену
#  филамента для K2, а на стороне принтера они заведены макросами. У K2 Plus владельца их НЕТ
#  (проверено по 143 объектам отчёта 02.09.2026) — и это ровно тот факт, который надо
#  зафиксировать отчётом, а не додумывать.
MACROS_OF_INTEREST = (START_MACRO_NAMES + CALIBRATION_NAMES + HOMING_NAMES
                      + ("CANCEL_PRINT",) + FEED_MACRO_NAMES)

# Сколько строк тела макроса разрешено включить в отчёт (очищенных). Тело нужно, чтобы
# понять ПОРЯДОК команд; всё остальное из него вырезается.
MAX_BODY_LINES = 40
MAX_BODY_LINE_LEN = 120


# ════════════════════════════════════════════════════════════════════════════════════════════
#  РЕДАКЦИЯ
# ════════════════════════════════════════════════════════════════════════════════════════════
_RE_IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_RE_IPV6 = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}\b")
_RE_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_RE_WINPATH = re.compile(r"\b[A-Za-z]:[\\/][^\s\"']*")
_RE_UNIXPATH = re.compile(r"(?:/home/|/Users/|/root/|/var/|/etc/|/opt/|/mnt/|/media/)[^\s\"']*")
_RE_URL = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"']+")
_RE_LONGHEX = re.compile(r"\b[0-9A-Fa-f]{16,}\b")
_RE_KEYVAL = re.compile(r"(?i)\b(api[_-]?key|token|access[_-]?code|password|passwd|secret|serial)\b"
                        r"\s*[:=]\s*\S+")

REDACTED = "<redacted>"

# Порядок значим: сначала самые длинные конструкции (URL/пути), затем адреса и ключи.
_PATTERNS = (_RE_URL, _RE_WINPATH, _RE_UNIXPATH, _RE_KEYVAL, _RE_MAC, _RE_IPV6, _RE_IPV4, _RE_LONGHEX)


def redact_text(s, secrets=()):
    """Очистить строку: явные секреты + шаблоны адресов/путей/URL/ключей. Никогда не бросает."""
    out = str(s if s is not None else "")
    for sec in (secrets or ()):
        v = str(sec or "").strip()
        if len(v) >= 3 and v.lower() not in ("none", "null", "0"):
            out = out.replace(v, REDACTED)
    for rx in _PATTERNS:
        out = rx.sub(REDACTED, out)
    return out


def redact(obj, secrets=()):
    """РЕКУРСИВНАЯ редакция произвольной структуры (dict/list/str/примитивы).

    Ключи словарей тоже чистятся: имя ключа может само оказаться путём или адресом.
    """
    if isinstance(obj, dict):
        return {redact_text(k, secrets): redact(v, secrets) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v, secrets) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj, secrets)
    return obj


def find_leaks(serialized, secrets=()):
    """Что осталось в готовом отчёте вопреки редакции. → список безопасных КОДОВ (не значений).

    Наружу отдаются только названия категорий: логировать сами утёкшие значения запрещено.
    """
    txt = str(serialized or "")
    bad = []
    for sec in (secrets or ()):
        v = str(sec or "").strip()
        if len(v) >= 3 and v.lower() not in ("none", "null", "0") and v in txt:
            bad.append("known_secret")
            break
    for name, rx in (("ipv4", _RE_IPV4), ("ipv6", _RE_IPV6), ("mac", _RE_MAC),
                     ("windows_path", _RE_WINPATH), ("unix_path", _RE_UNIXPATH),
                     ("url", _RE_URL), ("long_hex", _RE_LONGHEX), ("key_value", _RE_KEYVAL)):
        if rx.search(txt):
            bad.append(name)
    return sorted(set(bad))


# ════════════════════════════════════════════════════════════════════════════════════════════
#  РАЗБОР МАКРОСОВ
# ════════════════════════════════════════════════════════════════════════════════════════════
def _body_lines(body):
    """Командные строки тела макроса: без комментариев (# и ;), без пустых. Верхний регистр."""
    out = []
    for raw in str(body or "").split("\n"):
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if line:
            out.append(line)
    return out


def macro_params(body):
    """Имена параметров, которые макрос читает: params.NAME / params.get('NAME') / params['NAME']."""
    txt = str(body or "")
    names = set(re.findall(r"params\.([A-Za-z_][A-Za-z_0-9]*)", txt))
    names |= set(re.findall(r"params\.get\(\s*['\"]([^'\"]+)", txt))
    names |= set(re.findall(r"params\[\s*['\"]([^'\"]+)", txt))
    return sorted(n.upper() for n in names if n)


def macro_calls(body, wanted=MACROS_OF_INTEREST):
    """Какие интересные команды ВЫЗЫВАЕТ макрос (по началу командной строки)."""
    out = []
    for line in _body_lines(body):
        u = line.upper()
        for w in wanted:
            if u == w or u.startswith(w + " ") or u.startswith(w + "="):
                if w not in out:
                    out.append(w)
    return out


def macro_objects_read(body):
    """Какие printer-объекты читает макрос: printer.<obj> / printer['obj']."""
    txt = str(body or "")
    names = set(re.findall(r"printer\.([A-Za-z_][A-Za-z_0-9]*)", txt))
    names |= set(re.findall(r"printer\[\s*['\"]([^'\"]+)", txt))
    return sorted(n.lower() for n in names if n)


def sanitized_body(body, secrets=()):
    """Очищенное и ОГРАНИЧЕННОЕ представление тела макроса.

    Нужно только для восстановления ПОРЯДКА команд. Комментарии удалены, пути/адреса/ключи
    вычищены, длина ограничена. Всегда помечается redacted=True — это не исходный текст.
    """
    lines = _body_lines(body)
    cut = lines[:MAX_BODY_LINES]
    out = []
    for ln in cut:
        s = redact_text(ln, secrets)
        if len(s) > MAX_BODY_LINE_LEN:
            s = s[:MAX_BODY_LINE_LEN] + "…"
        out.append(s)
    return {"redacted": True, "lines": out,
            "truncated": len(lines) > MAX_BODY_LINES, "total_lines": len(lines)}


def analyze_macro(name, body, in_help, in_config, secrets=()):
    """Полный безопасный разбор одного макроса/команды."""
    calls = macro_calls(body) if in_config else []
    return {
        "name": name,
        "exists": bool(in_help or in_config),
        "source": ("gcode_macro" if in_config else ("klipper_builtin" if in_help else "")),
        "overrides_builtin": bool(in_config and name in (CALIBRATION_NAMES + HOMING_NAMES)),
        "parameters": macro_params(body) if in_config else [],
        "calls": calls,
        "calls_homing": any(c in HOMING_NAMES for c in calls),
        "calls_bed_mesh_calibrate": "BED_MESH_CALIBRATE" in calls,
        "calls_z_tilt": "Z_TILT_ADJUST" in calls,
        "calls_quad_gantry_level": "QUAD_GANTRY_LEVEL" in calls,
        "loads_mesh_profile": "BED_MESH_PROFILE" in calls,
        "objects_read": macro_objects_read(body) if in_config else [],
        "body": sanitized_body(body, secrets) if in_config else {"redacted": True, "lines": [],
                                                                 "truncated": False, "total_lines": 0},
    }


# ════════════════════════════════════════════════════════════════════════════════════════════
#  СБОР
# ════════════════════════════════════════════════════════════════════════════════════════════
def collect(get_json):
    """Прочитать всё, что разрешено. get_json(path) -> (объект|None, код_ошибки).

    Обращения идут ТОЛЬКО по allowlist: путь, которого в нём нет, не запрашивается вовсе.
    Никогда не бросает. → {path: {"ok": bool, "data": dict, "error": str}}
    """
    raw = {}
    for path in ALLOWED_PATHS:
        if not is_allowed(path):                     # страховка от правки списка «на месте»
            raw[path] = {"ok": False, "data": {}, "error": "not_allowed"}
            continue
        try:
            obj, err = get_json(path)
        except Exception:
            obj, err = None, "exception"
        if isinstance(obj, dict):
            raw[path] = {"ok": True, "data": obj, "error": ""}
        else:
            raw[path] = {"ok": False, "data": {}, "error": str(err or "no_data")}
    return raw


def _result(raw, path):
    d = (raw.get(path) or {}).get("data") or {}
    r = d.get("result")
    return r if isinstance(r, dict) else {}


def build_report(raw, app_version="", model_label="", adapter="klipper",
                 generated_at="", secrets=(), gcode_head=""):
    """Собрать ОБЕЗЛИЧЕННЫЙ отчёт по собранным данным. Никогда не бросает."""
    warnings = []
    unresolved = []

    srv = _result(raw, "/server/info")
    pinfo = _result(raw, "/printer/info")
    objs_res = _result(raw, "/printer/objects/list")
    help_res = _result(raw, "/printer/gcode/help")
    cfg_res = _result(raw, "/printer/objects/query?configfile")
    state_res = _result(raw, "/printer/objects/query?toolhead&print_stats&webhooks&idle_timeout")
    mesh_res = _result(raw, "/printer/objects/query?bed_mesh")
    #  Alpha 2.888: состояние системы подачи катушек (CFS у Creality K2).
    cfs_res = _result(raw, "/printer/objects/query?box&filament_rack")

    def _st(path, value_ok):
        if not (raw.get(path) or {}).get("ok"):
            return ST_UNAVAILABLE
        return ST_COMPLETE if value_ok else ST_UNSUPPORTED

    objects = [str(o) for o in (objs_res.get("objects") or []) if o]
    commands = sorted(set(str(c).upper() for c in (help_res.keys() if isinstance(help_res, dict) else [])))
    settings = ((cfg_res.get("status") or {}).get("configfile") or {}).get("settings")
    settings = settings if isinstance(settings, dict) else {}
    macros = {}
    for k, v in settings.items():
        ks = str(k or "")
        if ks.lower().startswith("gcode_macro "):
            macros[ks.split(" ", 1)[1].strip().upper()] = v if isinstance(v, dict) else {}

    if not (raw.get("/printer/objects/query?configfile") or {}).get("ok"):
        warnings.append("configfile_unavailable")
        unresolved.append("Конфигурация принтера недоступна — состав и тела макросов не прочитаны.")

    # ── Релевантные макросы ────────────────────────────────────────────────────────────────
    relevant = []
    cmd_set = set(commands)
    for name in MACROS_OF_INTEREST:
        in_cfg = name in macros
        in_help = name in cmd_set
        if not (in_cfg or in_help):
            continue
        relevant.append(analyze_macro(name, (macros.get(name) or {}).get("gcode"),
                                      in_help, in_cfg, secrets))

    by_name = {m["name"]: m for m in relevant}

    # ── Стартовый макрос ───────────────────────────────────────────────────────────────────
    start_name = next((n for n in START_MACRO_NAMES if n in by_name), "")
    start = by_name.get(start_name) or {}
    start_analysis = {
        "status": ST_COMPLETE if start_name else (
            ST_UNAVAILABLE if warnings else ST_UNSUPPORTED),
        "name": start_name,
        "exists": bool(start_name),
        "parameters": start.get("parameters", []),
        "calls": start.get("calls", []),
        "performs_bed_mesh": bool(start.get("calls_bed_mesh_calibrate")),
        "performs_homing": bool(start.get("calls_homing")),
        "loads_mesh_profile": bool(start.get("loads_mesh_profile")),
        "body": start.get("body", {"redacted": True, "lines": [], "truncated": False, "total_lines": 0}),
    }
    if start_name and not start.get("body", {}).get("lines"):
        unresolved.append("Стартовый макрос найден, но его тело не прочитано — порядок команд неизвестен.")

    # ── Калибровка стола ───────────────────────────────────────────────────────────────────
    bmc = by_name.get("BED_MESH_CALIBRATE") or {}
    bed_mesh_state = (mesh_res.get("status") or {}).get("bed_mesh") or {}
    bed_mesh_analysis = {
        "status": _st("/printer/objects/query?bed_mesh", True),
        "object_present": ("bed_mesh" in [o.lower() for o in objects]),
        "command_exists": bool(bmc.get("exists")),
        "overridden_by_macro": bool(bmc.get("overrides_builtin")),
        "source": bmc.get("source", ""),
        "parameters": bmc.get("parameters", []),
        "calls": bmc.get("calls", []),
        "profiles": sorted((bed_mesh_state.get("profiles") or {}).keys())
        if isinstance(bed_mesh_state.get("profiles"), dict) else [],
        "active_profile": str(bed_mesh_state.get("profile_name") or ""),
        "body": bmc.get("body", {"redacted": True, "lines": [], "truncated": False, "total_lines": 0}),
    }
    if bed_mesh_analysis["overridden_by_macro"]:
        unresolved.append("BED_MESH_CALIBRATE переопределена макросом принтера — что она делает "
                          "фактически, из read-only данных не доказать.")

    # ── Парковка ───────────────────────────────────────────────────────────────────────────
    toolhead = (state_res.get("status") or {}).get("toolhead") or {}
    g28 = by_name.get("G28") or {}
    homing_analysis = {
        "status": _st("/printer/objects/query?toolhead&print_stats&webhooks&idle_timeout", True),
        "homed_axes_now": str(toolhead.get("homed_axes") or ""),
        "g28_overridden_by_macro": bool(g28.get("overrides_builtin")),
        "start_macro_homes": bool(start.get("calls_homing")),
        "calibration_macro_homes": bool(bmc.get("calls_homing")),
    }

    # ── Кандидаты в критерии завершения ────────────────────────────────────────────────────
    print_stats = (state_res.get("status") or {}).get("print_stats") or {}
    webhooks = (state_res.get("status") or {}).get("webhooks") or {}
    idle = (state_res.get("status") or {}).get("idle_timeout") or {}
    completion = {
        "status": _st("/printer/objects/query?toolhead&print_stats&webhooks&idle_timeout", True),
        "candidates": [
            {"evidence": "gcode_script_response",
             "describe": "Ответ на чтение скрипта Moonraker приходит после его выполнения",
             "observable": True},
            {"evidence": "print_stats.state",
             "describe": "Переход в standby после операции", "observable": bool(print_stats)},
            {"evidence": "webhooks.state",
             "describe": "ready без shutdown/error", "observable": bool(webhooks)},
            {"evidence": "idle_timeout.state",
             "describe": "Printing -> Ready после завершения макроса", "observable": bool(idle)},
            {"evidence": "bed_mesh.profile_name",
             "describe": "Появление/смена активного профиля сетки",
             "observable": bool(bed_mesh_state)},
        ],
    }

    current_state = {
        "status": _st("/printer/objects/query?toolhead&print_stats&webhooks&idle_timeout", True),
        "print_stats_state": str(print_stats.get("state") or ""),
        "webhooks_state": str(webhooks.get("state") or ""),
        "idle_timeout_state": str(idle.get("state") or ""),
        "homed_axes": str(toolhead.get("homed_axes") or ""),
    }

    # ── Что делает сам файл (если передан начальный фрагмент) ───────────────────────────────
    file_analysis = {"status": ST_UNSUPPORTED, "controls": {}}
    if gcode_head:
        try:
            from app import klipper_prestart as _kp
            file_analysis = {"status": ST_COMPLETE, "controls": _kp.file_control_reasons(gcode_head)}
        except Exception:
            file_analysis = {"status": ST_UNAVAILABLE, "controls": {}}

    # ── Честные открытые вопросы ───────────────────────────────────────────────────────────
    if not start_name:
        unresolved.append("Стартовый макрос (START_PRINT/PRINT_START) не найден — неизвестно, "
                          "что выполняется перед печатью.")
    if not bmc.get("exists"):
        unresolved.append("Команда калибровки стола не обнаружена.")
    if not completion["candidates"][1]["observable"]:
        unresolved.append("Состояние печати недоступно — подтвердить завершение операции нечем.")

    # ── Alpha 2.840: рекурсивный контракт (АДДИТИВНО к v1) ─────────────────────────────────
    # Разделы только ДОБАВЛЯЮТСЯ: report_schema_version не меняется, ни одно поле v1 не
    # переименовано и не удалено, поэтому читатель v1 продолжает работать без правок.
    # Тела макросов сюда не попадают — только имена вызовов, флаги и признаки недосказанности.
    _bodies = {}
    for _n, _m in macros.items():
        _bodies[_n] = (_m or {}).get("gcode") or ""
    _sg = build_call_graph(start_name, _bodies, cmd_set) if start_name else {}
    _risk, _risk_ev = analyze_mesh_risk(_sg) if start_name else (RISK_UNKNOWN, ["start_macro_unknown"])
    _plan = resolve_bed_mesh_plan(objects, commands, _bodies,
                                  file_controls=(file_analysis.get("controls") or {}),
                                  start_macro=start_name)
    _cands = []
    for _c in VENDOR_CALIBRATION_CANDIDATES:
        if _c not in _bodies:
            _cands.append({"name": _c, "present": False, "proven": False, "reason": "absent"})
            continue
        _ok, _why, _cg = _vendor_is_safe(_c, _bodies, cmd_set)
        _cands.append({"name": _c, "present": True, "proven": bool(_ok), "reason": _why,
                       "graph_nodes": len(_cg.get("nodes") or {}),
                       "unknown": list(_cg.get("unknown") or [])})
    _cal_root = (_plan.get("commands") or [""])[0]
    _cal_graph = build_call_graph(_cal_root, _bodies, cmd_set) if _cal_root else {}
    _limits = bool(_sg.get("truncated")) or bool(_cal_graph.get("truncated"))
    _unresolved_nodes = sorted(set(list(_sg.get("unknown") or []) + list(_cal_graph.get("unknown") or [])))
    if _risk == RISK_UNKNOWN:
        unresolved.append("Судьба сетки стола после стартового макроса НЕ доказана — "
                          "автоматическая калибровка закрыта (fail-closed).")
    if _unresolved_nodes:
        unresolved.append("Часть вызовов стартового макроса не прочитана — их тела недоступны.")

    sections_v2 = {
        "vendor_calibration_candidates": {
            "status": ST_COMPLETE if _bodies else ST_UNAVAILABLE, "candidates": _cands},
        "recursive_start_call_graph": {
            "status": ST_COMPLETE if _sg.get("nodes") else ST_UNAVAILABLE, "graph": _sg},
        "recursive_calibration_call_graph": {
            "status": ST_COMPLETE if _cal_graph.get("nodes") else ST_UNSUPPORTED,
            "root": _cal_root, "graph": _cal_graph},
        "mesh_clear_or_replace_analysis": {
            "status": ST_COMPLETE if start_name else ST_UNAVAILABLE,
            "post_start_mesh_risk": _risk, "evidence": list(_risk_ev)},
        "resolved_bed_mesh_plan": {
            "status": ST_COMPLETE,
            "mode": _plan["mode"], "reason_code": _plan["reason_code"],
            "commands": _plan["commands"], "command_classes": _plan["command_classes"],
            "requires_homing": _plan["requires_homing"],
            "completion_evidence": _plan["completion_evidence"],
            "source": _plan["source"], "post_start_mesh_risk": _plan["post_start_mesh_risk"],
            "explanation_ru": _plan["explanation_ru"], "explanation_en": _plan["explanation_en"]},
    }

    report = {
        "report_schema_version": REPORT_SCHEMA,
        "generated_at": str(generated_at or ""),
        "farm_manager_version": str(app_version or ""),
        "adapter": str(adapter or ""),
        "printer_model": str(model_label or ""),
        "klipper_version": str(pinfo.get("software_version") or ""),
        "moonraker_version": str(srv.get("moonraker_version") or ""),
        "sections": {
            "objects_present": {"status": _st("/printer/objects/list", bool(objects)),
                                "objects": sorted(objects)},
            "relevant_commands": {"status": _st("/printer/gcode/help", bool(commands)),
                                  "commands": sorted(n for n in MACROS_OF_INTEREST if n in cmd_set),
                                  "total_commands": len(commands)},
            "relevant_macros": {"status": ST_COMPLETE if relevant else ST_UNAVAILABLE,
                                "macros": relevant},
            "start_macro_analysis": start_analysis,
            "cfs_state": _cfs_section(cfs_res, _st),
            "cfs_slot_selection": _slot_selection_section(macros, cmd_set, by_name),
            "bed_mesh_analysis": bed_mesh_analysis,
            "homing_analysis": homing_analysis,
            "completion_evidence_candidates": completion,
            "current_safe_state": current_state,
            "file_controlled_analysis": file_analysis,
        },
        "probe_warnings": sorted(set(warnings)),
        "unresolved_questions": list(dict.fromkeys(unresolved)),
        "endpoints_read": [p for p in ALLOWED_PATHS if (raw.get(p) or {}).get("ok")],
        "endpoints_failed": [p for p in ALLOWED_PATHS if not (raw.get(p) or {}).get("ok")],
        # Alpha 2.840 — новые ВЕРХНЕУРОВНЕВЫЕ поля (добавление, не замена):
        "post_start_mesh_risk": _risk,
        "unresolved_graph_nodes": _unresolved_nodes,
        "graph_limits_reached": _limits,
        "graph_limits": {"max_depth": GRAPH_MAX_DEPTH, "max_nodes": GRAPH_MAX_NODES,
                         "max_body_chars": BODY_MAX_CHARS},
    }
    report["sections"].update(sections_v2)
    return redact(report, secrets)


# ════════════════════════════════════════════════════════════════════════════════════════════
#  Alpha 2.840 — ОГРАНИЧЕННЫЙ РЕКУРСИВНЫЙ ГРАФ ВЫЗОВОВ
#
#  ЗАЧЕМ. Отчёт v1 разбирал только заранее выбранные имена, поэтому про START_PRINT было видно
#  лишь «вызывает G28». На реальном K2 Plus он вызывает ещё и vendor-макросы (BOX_START_PRINT,
#  PRINT_PREPARE_CLEAR, BOX_NOZZLE_CLEAN, NEXT_HOMEZ_NACCU), тела которых v1 не читал. Что они
#  делают с сеткой стола — было НЕИЗВЕСТНО, а значит и «померить сетку заранее» было небезопасно:
#  стартовый макрос мог её очистить, заменить или измерить заново.
#
#  Теперь граф строится по ФАКТИЧЕСКОЙ конфигурации принтера, с жёсткими предохранителями:
#  ограничение глубины и числа узлов, обнаружение циклов, лимит длины тела. Любое «не дочитали»
#  превращается в unknown — и это ЗАКРЫВАЕТ автоматический путь, а не открывает его.
# ════════════════════════════════════════════════════════════════════════════════════════════
# Откуда взялся исполняемый контракт (те же значения, что и в app/klipper_prestart.py —
# интерфейс показывает их одинаково независимо от того, кто посчитал).
SRC_BUILTIN = "klipper_builtin"
SRC_PRINTER_MACRO = "printer_macro"
SRC_FILE = "file"

GRAPH_MAX_DEPTH = 6
GRAPH_MAX_NODES = 120
BODY_MAX_CHARS = 24000        # тело длиннее — считаем обрезанным (доказать содержимое нельзя)

# Команды, меняющие судьбу сетки стола.
MESH_CLEAR_TOKENS = ("BED_MESH_CLEAR", "BED_MESH_SET_DISABLE")
MESH_PROFILE_TOKENS = ("BED_MESH_PROFILE",)
MESH_CALIBRATE_TOKENS = ("BED_MESH_CALIBRATE", "G29")
# Команды, после которых говорить о доказанном состоянии нельзя вовсе.
DANGEROUS_TOKENS = ("SAVE_CONFIG", "RESTART", "FIRMWARE_RESTART", "M112",
                    "EMERGENCY_STOP", "SDCARD_RESET_FILE")

RISK_NONE = "none"
RISK_CLEARS = "clears"
RISK_REPLACES = "replaces"
RISK_RECALIBRATES = "recalibrates"
RISK_UNKNOWN = "unknown"


def macro_tokens(body):
    """Первые токены командных строк тела — имена вызываемых команд/макросов.

    Строки шаблонизатора Jinja ({% ... %}, {{ ... }}) и присваивания переменных командами не
    являются. Значения параметров не извлекаются вовсе.
    """
    out = []
    for line in _body_lines(body):
        s = line.strip()
        if not s or s.startswith("{") or s.startswith("#"):
            continue
        tok = re.split(r"[\s=]", s, maxsplit=1)[0].upper()
        if tok and re.fullmatch(r"[A-Z_][A-Z_0-9.]*", tok):
            out.append(tok)
    return out


def node_flags(calls):
    """Признаки узла по его прямым вызовам. Значения параметров не участвуют."""
    c = set(calls or [])
    return {
        "calls_homing": bool(c & {"G28"}),
        "calls_bed_mesh_calibrate": bool(c & {"BED_MESH_CALIBRATE"}),
        "calls_bed_mesh_clear": bool(c & set(MESH_CLEAR_TOKENS)),
        "loads_mesh_profile": bool(c & set(MESH_PROFILE_TOKENS)),
        "calls_g29": bool(c & {"G29"}),
        "calls_z_tilt": bool(c & {"Z_TILT_ADJUST"}),
        "calls_qgl": bool(c & {"QUAD_GANTRY_LEVEL"}),
        "calls_save_config": bool(c & {"SAVE_CONFIG"}),
        "calls_restart": bool(c & {"RESTART", "FIRMWARE_RESTART"}),
        "calls_shutdown": bool(c & {"M112", "EMERGENCY_STOP"}),
    }


def build_call_graph(root, macros, builtins=()):
    """Ограниченный обход вызовов от `root`. Никогда не бросает. → dict.

    macros   — {ИМЯ: тело} из configfile (gcode_macro);
    builtins — имена из /printer/gcode/help (тела нет и не нужно: семантику встроенных
               команд, важных для сетки, мы знаем поимённо).

    Узел бывает трёх видов:
      macro   — тело известно, обходим дальше;
      builtin — встроенная команда Klipper: тела нет, но и рекурсии нет;
      unknown — имя не найдено НИГДЕ. Это и есть «не дочитали» → небезопасно.
    """
    mac = {str(k).upper(): v for k, v in (macros or {}).items()}
    blt = set(str(b).upper() for b in (builtins or ()))
    nodes, order, cycles, unknown, truncated = {}, [], [], [], False
    root = str(root or "").upper()
    if not root:
        return {"root": "", "nodes": {}, "order": [], "cycles": [], "unknown": [],
                "truncated": True, "depth_reached": 0}

    stack = [(root, 0, (root,))]
    seen = set()
    while stack:
        name, depth, path = stack.pop(0)
        if len(nodes) >= GRAPH_MAX_NODES or depth > GRAPH_MAX_DEPTH:
            truncated = True
            continue
        if name in seen:
            continue
        seen.add(name)
        order.append(name)
        if name in mac:
            body = str(mac.get(name) or "")
            body_trunc = len(body) > BODY_MAX_CHARS
            calls = macro_tokens(body[:BODY_MAX_CHARS])
            nodes[name] = dict({"kind": "macro", "source": SRC_PRINTER_MACRO, "calls": calls,
                                "parameters": macro_params(body[:BODY_MAX_CHARS]),
                                "body_available": True, "truncated": body_trunc, "depth": depth},
                               **node_flags(calls))
            if body_trunc:
                truncated = True
            for c in calls:
                if c in path:                       # цикл: дальше не идём
                    if c not in cycles:
                        cycles.append(c)
                    continue
                stack.append((c, depth + 1, path + (c,)))
        elif name in blt:
            nodes[name] = dict({"kind": "builtin", "source": SRC_BUILTIN, "calls": [],
                                "parameters": [], "body_available": False,
                                "truncated": False, "depth": depth}, **node_flags([]))
        else:
            nodes[name] = dict({"kind": "unknown", "source": "", "calls": [],
                                "parameters": [], "body_available": False,
                                "truncated": False, "depth": depth}, **node_flags([]))
            if name not in unknown:
                unknown.append(name)
    return {"root": root, "nodes": nodes, "order": order, "cycles": cycles,
            "unknown": sorted(unknown), "truncated": bool(truncated),
            "depth_reached": max([n["depth"] for n in nodes.values()] or [0])}


def analyze_mesh_risk(graph):
    """Что граф делает с сеткой стола ПОСЛЕ нашей предстартовой калибровки. → (risk, evidence).

    Приоритет: unknown > clears > replaces > recalibrates > none. Любая недосказанность
    (обрезанное тело, неизвестное имя, упёрлись в лимит) даёт unknown — fail-closed.
    """
    ev = []
    g = graph or {}
    nodes = g.get("nodes") or {}
    if not nodes:
        return (RISK_UNKNOWN, ["graph_empty"])
    if g.get("truncated"):
        ev.append("graph_truncated")
    for u in (g.get("unknown") or []):
        ev.append("unknown_macro:%s" % u)
    hit = {"clear": [], "profile": [], "cal": [], "danger": []}
    for name, n in nodes.items():
        for c in n.get("calls") or []:
            if c in MESH_CLEAR_TOKENS:
                hit["clear"].append(c)
            elif c in MESH_PROFILE_TOKENS:
                hit["profile"].append(c)
            elif c in MESH_CALIBRATE_TOKENS:
                hit["cal"].append(c)
            elif c in DANGEROUS_TOKENS:
                hit["danger"].append(c)
    for k, tag in (("clear", "mesh_clear"), ("profile", "mesh_profile_load"),
                   ("cal", "mesh_recalibrate"), ("danger", "state_changing")):
        for c in sorted(set(hit[k])):
            ev.append("%s:%s" % (tag, c))
    if ev and (g.get("truncated") or g.get("unknown") or hit["danger"]):
        return (RISK_UNKNOWN, sorted(set(ev)))
    if hit["clear"]:
        return (RISK_CLEARS, sorted(set(ev)))
    if hit["profile"]:
        return (RISK_REPLACES, sorted(set(ev)))
    if hit["cal"]:
        return (RISK_RECALIBRATES, sorted(set(ev)))
    return (RISK_NONE, [])


# ════════════════════════════════════════════════════════════════════════════════════════════
#  Alpha 2.840 — ВЫБОР ИСПОЛНЯЕМОГО КОНТРАКТА КАЛИБРОВКИ СТОЛА
# ════════════════════════════════════════════════════════════════════════════════════════════
MODE_VENDOR = "vendor_macro"
MODE_STANDARD = "standard_builtin"
MODE_FILE = "file_controlled"
MODE_UNSUPPORTED = "unsupported"
MODE_UNSAFE = "unsafe"

# Имена, которые ВООБЩЕ рассматриваются как кандидаты в vendor-калибровку. Имя само по себе
# доказательством не является — тело всё равно обязано пройти проверку ниже.
VENDOR_CALIBRATION_CANDIDATES = ("BED_MESH_CALIBRATE_START_PRINT", "PRINT_CALIBRATION",
                                 "CALIBRATE_BED_MESH", "AUTO_BED_LEVEL")

CMD_HOME_ALL = "home_all"
CMD_BED_MESH_BUILTIN = "bed_mesh_builtin"
CMD_VENDOR_CALIBRATION = "vendor_calibration_macro"


def _upper_set(items):
    """Имена в верхнем регистре. Никогда не бросает (не-итерируемое → пусто)."""
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


def _vendor_is_safe(name, macros, builtins):
    """Доказан ли vendor-макрос как безопасная калибровка. → (ok, reason, graph)."""
    g = build_call_graph(name, macros, builtins)
    nodes = g.get("nodes") or {}
    if g.get("truncated") or g.get("unknown"):
        return (False, "vendor_graph_incomplete", g)
    calls = set()
    for n in nodes.values():
        calls.update(n.get("calls") or [])
    if calls & set(DANGEROUS_TOKENS):
        return (False, "vendor_state_changing", g)
    if not (calls & set(MESH_CALIBRATE_TOKENS)):
        return (False, "vendor_does_not_calibrate", g)
    if calls & set(MESH_CLEAR_TOKENS):
        return (False, "vendor_clears_mesh", g)
    return (True, "vendor_proven", g)


def resolve_bed_mesh_plan(objects=None, gcode_commands=None, config_macros=None,
                          file_controls=(), start_macro=""):
    """ЕДИНСТВЕННОЕ место, где решается, как именно калибровать стол. Никогда не бросает.

    config_macros здесь — СЛОВАРЬ {ИМЯ: тело} (в отличие от discover_capabilities, которому
    достаточно имён): без тел доказать контракт невозможно.

    → {mode, commands, requires_homing, completion_evidence, post_start_mesh_risk,
       reason_code, explanation_ru, explanation_en, source, command_classes, graph}
    """
    obj = _lower_set(objects)
    blt = _upper_set(gcode_commands)
    # Обещание «никогда не бросает» должно держаться и на мусоре: единственный вызывающий —
    # предстартовый путь, и исключение здесь означало бы падение ПЕРЕД печатью, а не отказ.
    macros = {}
    if isinstance(config_macros, dict):
        macros = {str(k).upper(): v for k, v in config_macros.items()}
    try:
        fc = set(file_controls or ())
    except TypeError:
        fc = set()

    def _out(mode, code, ru, en, commands=(), classes=(), homing=False, risk=RISK_UNKNOWN,
             source="", graph=None, evidence=()):
        return {"mode": mode, "commands": list(commands), "command_classes": list(classes),
                "requires_homing": bool(homing), "completion_evidence": list(evidence),
                "post_start_mesh_risk": risk, "reason_code": code,
                "explanation_ru": ru, "explanation_en": en, "source": source,
                "graph": graph or {}}

    # ── C. Операцию уже выполняет сам файл ─────────────────────────────────────────────────
    if "bed_mesh_calibrate" in fc:
        return _out(MODE_FILE, "file_controls_mesh",
                    "Калибровка выполняется стартовым макросом файла — повторно она не запускается.",
                    "Calibration is performed by the file's start macro — it will not be run again.",
                    risk=RISK_NONE, source=SRC_FILE)

    # ── Предпосылки вообще ─────────────────────────────────────────────────────────────────
    if "bed_mesh" not in obj:
        return _out(MODE_UNSUPPORTED, "bed_mesh_object_missing",
                    "У принтера не настроена сетка стола.",
                    "The printer has no bed mesh configured.", risk=RISK_NONE)
    if "BED_MESH_CALIBRATE" not in blt and "BED_MESH_CALIBRATE" not in macros:
        return _out(MODE_UNSUPPORTED, "bed_mesh_command_missing",
                    "Команда калибровки стола на принтере не найдена.",
                    "The bed mesh calibration command was not found on the printer.", risk=RISK_NONE)

    # Риск от последующего стартового макроса считаем ОДИН раз: он нужен обоим путям.
    sm = str(start_macro or "").upper()
    sm_graph = build_call_graph(sm, macros, blt) if sm else {}
    risk, risk_ev = analyze_mesh_risk(sm_graph) if sm else (RISK_UNKNOWN, ["start_macro_unknown"])
    # Стартовый макрос сам калибрует → наша калибровка была бы второй и лишней.
    if risk == RISK_RECALIBRATES:
        return _out(MODE_FILE, "start_macro_recalibrates",
                    "Калибровка выполняется стартовым макросом принтера — повторно она не запускается.",
                    "Calibration is performed by the printer's start macro — it will not be run again.",
                    risk=risk, source=SRC_PRINTER_MACRO, graph=sm_graph, evidence=risk_ev)

    # ── A. Доказанный vendor-контракт (имя само по себе НЕ доказательство) ─────────────────
    for cand in VENDOR_CALIBRATION_CANDIDATES:
        if cand not in macros:
            continue
        ok, why, g = _vendor_is_safe(cand, macros, blt)
        if ok and risk == RISK_NONE:
            _vcalls = set()
            for _n in (g.get("nodes") or {}).values():
                _vcalls.update(_n.get("calls") or [])
            return _out(MODE_VENDOR, "vendor_proven",
                        "Используется проверенный калибровочный макрос принтера.",
                        "Using the printer's proven calibration macro.",
                        commands=[cand], classes=[CMD_VENDOR_CALIBRATION],
                        homing=("G28" not in _vcalls),   # макрос паркует сам → нам не нужно
                        risk=risk, source=SRC_PRINTER_MACRO, graph=g,
                        evidence=["gcode_script_response", "webhooks_ready", "print_stats_standby",
                                  "bed_mesh_fingerprint"])
        # Кандидат есть, но не доказан — молча его не берём и идём дальше к стандартному пути.

    # ── B. Стандартный встроенный путь ─────────────────────────────────────────────────────
    bmc_overridden = "BED_MESH_CALIBRATE" in macros
    if bmc_overridden:
        return _out(MODE_UNSAFE, "bed_mesh_overridden",
                    "Команда калибровки переопределена макросом принтера — что она делает "
                    "на самом деле, доказать нельзя.",
                    "The calibration command is overridden by a printer macro — what it actually "
                    "does cannot be proven.", risk=risk, source=SRC_PRINTER_MACRO, graph=sm_graph)
    if "G28" in macros:
        return _out(MODE_UNSAFE, "homing_overridden",
                    "Парковка осей переопределена макросом принтера — автоматический путь закрыт.",
                    "Homing is overridden by a printer macro — the automatic path is closed.",
                    risk=risk, source=SRC_PRINTER_MACRO, graph=sm_graph)
    # ── ДОКАЗАННЫЙ вред: наша калибровка была бы выброшена стартовым макросом ───────────────
    # Здесь недосказанности нет: граф прочитан целиком и в нём ВИДНО очистку сетки или загрузку
    # другого профиля. Замер стола в таком порядке — потерянное время и ложное обещание
    # пользователю, поэтому автоматический путь остаётся закрытым.
    if risk in (RISK_CLEARS, RISK_REPLACES):
        _ru = {RISK_CLEARS: "стартовый макрос принтера очищает сетку после калибровки",
               RISK_REPLACES: "стартовый макрос принтера загружает другую сетку"}
        _en = {RISK_CLEARS: "the printer's start macro clears the mesh afterwards",
               RISK_REPLACES: "the printer's start macro loads a different mesh"}
        return _out(MODE_UNSAFE, "post_start_mesh_risk_%s" % risk,
                    "Автоматическая калибровка закрыта: %s." % _ru.get(risk, risk),
                    "Automatic calibration is closed: %s." % _en.get(risk, risk),
                    risk=risk, source=SRC_PRINTER_MACRO, graph=sm_graph, evidence=risk_ev)
    # ── Alpha 2.841: НЕДОКАЗУЕМОСТЬ больше не отдаёт калибровку принтеру ────────────────────
    # Тело vendor-макроса может быть недоступно (на реальном K2 Plus это BOX_START_PRINT), и
    # доказать, что он оставит сетку в покое, нельзя. Раньше такой случай закрывал автомат —
    # а на практике это означало, что калибровку не делал НИКТО: файл её не содержит, мы её не
    # шлём, а vendor-макрос снимает карту только когда сетки нет (после включения — да, вторую
    # печать подряд — уже нет). Выбранная пользователем галочка обязана означать новый замер,
    # поэтому недоказуемость теперь переводит калибровку на нас: снимаем карту САМИ и только
    # потом запускаем файл. Худшее, что может случиться дальше, — vendor-макрос снимет её ещё
    # раз: это дольше, но безопасно и видно пользователю. Молчаливое бездействие — не вариант.
    if risk == RISK_UNKNOWN:
        return _out(MODE_STANDARD, "start_macro_unproven_self_calibrate",
                    "Что делает стартовый макрос принтера с сеткой, доказать нельзя, поэтому "
                    "Farm Manager измерит стол сам перед запуском файла.",
                    "What the printer's start macro does to the mesh cannot be proven, so Farm "
                    "Manager will measure the bed itself before starting the file.",
                    commands=["BED_MESH_CALIBRATE"], classes=[CMD_BED_MESH_BUILTIN],
                    homing=True, risk=risk, source=SRC_BUILTIN, graph=sm_graph,
                    evidence=["gcode_script_response", "webhooks_ready", "print_stats_standby",
                              "idle_timeout_ready", "bed_mesh_fingerprint"])
    return _out(MODE_STANDARD, "standard_builtin_proven",
                "Farm Manager выполнит парковку осей при необходимости, измерит сетку стола "
                "и только затем запустит файл.",
                "Farm Manager will home the axes if needed, measure the bed mesh and only then "
                "start the file.",
                commands=["BED_MESH_CALIBRATE"], classes=[CMD_BED_MESH_BUILTIN],
                homing=True, risk=risk, source=SRC_BUILTIN, graph=sm_graph,
                evidence=["gcode_script_response", "webhooks_ready", "print_stats_standby",
                          "idle_timeout_ready", "bed_mesh_fingerprint"])


def mesh_fingerprint(bed_mesh_state):
    """Безопасный отпечаток сетки: профиль, размеры и SHA-256 канонической матрицы.

    САМИ ЗНАЧЕНИЯ наружу не отдаются и не логируются — только форма и хеш.
    """
    import hashlib
    st = bed_mesh_state if isinstance(bed_mesh_state, dict) else {}
    mx = st.get("probed_matrix")
    if not isinstance(mx, list) or not mx:
        mx = st.get("mesh_matrix")
    rows = len(mx) if isinstance(mx, list) else 0
    cols = len(mx[0]) if (rows and isinstance(mx[0], list)) else 0
    canon = ""
    if rows and cols:
        try:
            canon = ";".join(",".join("%.6f" % float(v) for v in row) for row in mx)
        except Exception:
            canon = ""
    return {"profile_name": str(st.get("profile_name") or ""),
            "rows": rows, "cols": cols,
            "sha256": (hashlib.sha256(canon.encode("utf-8")).hexdigest() if canon else ""),
            "present": bool(rows and cols)}


def report_filename(model_label="", date_str=""):
    """Имя файла отчёта: только безопасные символы, без адресов и путей."""
    m = re.sub(r"[^A-Za-z0-9._-]+", "-", str(model_label or "klipper")).strip("-") or "klipper"
    d = re.sub(r"[^0-9-]+", "", str(date_str or "")) or "0000-00-00"
    return "3diwell-klipper-report-%s-%s.json" % (m[:48], d)


def summarize(report):
    """Короткая человеческая сводка для интерфейса. Ни адресов, ни тел макросов."""
    s = (report or {}).get("sections") or {}
    st = s.get("start_macro_analysis") or {}
    bm = s.get("bed_mesh_analysis") or {}
    return {
        "klipper_version": (report or {}).get("klipper_version", ""),
        "moonraker_version": (report or {}).get("moonraker_version", ""),
        "start_macro": st.get("name", ""),
        "start_macro_params": st.get("parameters", []),
        "start_macro_does_bed_mesh": bool(st.get("performs_bed_mesh")),
        "start_macro_homes": bool(st.get("performs_homing")),
        "bed_mesh_command_exists": bool(bm.get("command_exists")),
        "bed_mesh_overridden": bool(bm.get("overridden_by_macro")),
        # Alpha 2.840: главный вывод отчёта — можно ли вообще калибровать автоматически.
        "post_start_mesh_risk": (report or {}).get("post_start_mesh_risk", RISK_UNKNOWN),
        "bed_mesh_plan_mode": ((s.get("resolved_bed_mesh_plan") or {}).get("mode") or ""),
        "bed_mesh_plan_reason": ((s.get("resolved_bed_mesh_plan") or {}).get("reason_code") or ""),
        "unresolved_graph_nodes": list((report or {}).get("unresolved_graph_nodes") or []),
        "sections_complete": sorted(k for k, v in s.items()
                                    if isinstance(v, dict) and v.get("status") == ST_COMPLETE),
        "sections_unavailable": sorted(k for k, v in s.items()
                                       if isinstance(v, dict) and v.get("status") == ST_UNAVAILABLE),
        "unresolved_count": len((report or {}).get("unresolved_questions") or []),
    }
