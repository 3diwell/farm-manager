# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — политика прямых команд принтеру (Alpha 2.782).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, веб-фреймворк,
СУБД и транспорты принтеров, не обращается к сети, ничего не отправляет и не журналирует
пользовательские значения — чтобы его можно было проверять офлайн-тестами без запуска
приложения, без рабочих данных и без единой команды реальному принтеру.

ЗАЧЕМ. Маршрут прямой команды принимал `val` строкой и подставлял её в G-code как есть:
    param = f"M104 S{val}\\n"
Значение `100\\nM112` превращало ОДИН разрешённый запрос в ДВЕ команды, вторая из которых —
аварийная остановка. Фильтрацией одного символа это не лечится: клиент всё равно смог бы
прислать опасную команду первой и единственной. Поэтому здесь другой подход — клиент
называет ЛОГИЧЕСКОЕ ДЕЙСТВИЕ из закрытого списка, значение разбирается по своему типу и
диапазону, а сама строка команды собирается сервером заново из нормализованных данных.
Ни один фрагмент запроса не попадает в G-code в исходном виде.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Это не «чёрный список опасных команд»: запрещено всё, что не описано
явно. Новое действие невозможно добавить со стороны клиента — только правкой ACTION_SPECS.
"""

import re

# ── Пределы значений ───────────────────────────────────────────────────────────
# ОТКУДА ЧИСЛА. Интерфейс никаких ограничений не задаёт (поля температур — обычный ввод
# без min/max), поэтому границы взяты по фактическим пределам поддерживаемых проектом
# моделей (AGENTS.md §1): самый горячий хотэнд среди них — Bambu H2D (350 °C), самый
# горячий стол — 120 °C. Ноль разрешён: это штатное «выключить нагрев».
# Значения намеренно НЕ подрезаются молча — выход за диапазон это ошибка, о которой
# пользователь должен узнать, а не тихо получить другую температуру.
NOZZLE_MIN_C, NOZZLE_MAX_C = 0, 350
BED_MIN_C, BED_MAX_C = 0, 120
#  R-104 (2.983): термокамера. Самая горячая камера среди поддерживаемых моделей — Bambu H2D/H2S
#  (65 °C по характеристикам производителя); у X1E и Creality K2 Plus/Pro предел 60 °C, и его
#  держит сама прошивка. Ноль — «выключить нагрев камеры».
CHAMBER_MIN_C, CHAMBER_MAX_C = 0, 65

# Потолок длины итоговой строки команды. Реальные команды здесь — единицы символов;
# ограничение существует, чтобы никакая ошибка форматирования не породила длинную строку.
MAX_COMMAND_LEN = 64

# Типы принтеров проекта.
T_KLIPPER, T_FLASHFORGE, T_BAMBU = "klipper", "flashforge", "bambu"
#  2.970: "demo" — виртуальный принтер для проверок. Он принимает ТЕ ЖЕ действия из того же
#  закрытого списка и проходит тот же разбор значений: иначе проверка на нём проверяла бы не
#  тот путь, которым идут настоящие принтеры. Сети у него нет, команда никуда не уходит.
T_DEMO = "demo"
#  12.10.2026: Creality на заводской прошивке (родная служба :9999). Пауза, продолжение, стоп и
#  температуры сопла и стола — команды самой службы (app/creality_native.py), не G-code.
T_CREALITY = "creality"
ALL_TYPES = (T_KLIPPER, T_FLASHFORGE, T_BAMBU, T_DEMO, T_CREALITY)

# Разделители строк и управляющие символы, которых в команде быть не может НИКОГДА.
# Помимо CR/LF учтены вертикальная табуляция, form feed и юникодные разделители строк:
# часть парсеров и транспортов трактует их как конец строки.
_FORBIDDEN_CHARS = frozenset(
    [chr(c) for c in range(0x20)]        # весь блок C0: \x00, \n, \r, \x0b, \x0c и прочие
    + ["\x7f"]                           # DEL
    + ["\u0085", "\u2028", "\u2029"]      # NEL, LINE SEPARATOR, PARAGRAPH SEPARATOR
)

# Строгий разбор целого: только необязательный минус и цифры. Этим одним правилом
# отсекаются NaN, Infinity, экспоненциальная запись, запятая как разделитель, единицы
# измерения внутри строки и любые лишние токены.
_INT_RE = re.compile(r"\A-?\d+\Z")

# Коды причин. Пользовательское значение в них НЕ попадает.
R_UNKNOWN_ACTION = "unknown_action"
R_BAD_VALUE = "bad_value"
R_OUT_OF_RANGE = "value_out_of_range"
R_UNSUPPORTED = "unsupported_command"
R_BAD_COMMAND = "malformed_command"

# ── Закрытый список действий ───────────────────────────────────────────────────
# ЧТО ЗДЕСЬ ЕСТЬ. Ровно то, что вызывает текущий интерфейс, и ничего сверх того.
# param=None — действие без параметра; тогда значение из запроса игнорируется целиком.
# Опасных действий (аварийная остановка, прошивка, сброс, произвольное перемещение,
# запись EEPROM, выполнение макросов) в списке НЕТ и быть не должно: интерфейс их не
# вызывает, а значит и маршрут не обязан их пропускать.
ACTION_SPECS = {
    "pause":    {"param": None, "types": ALL_TYPES},
    "resume":   {"param": None, "types": ALL_TYPES},
    "stop":     {"param": None, "types": ALL_TYPES},
    "nozzle":   {"param": "temp_c", "min": NOZZLE_MIN_C, "max": NOZZLE_MAX_C, "types": ALL_TYPES},
    "nozzle_l": {"param": "temp_c", "min": NOZZLE_MIN_C, "max": NOZZLE_MAX_C, "types": (T_BAMBU,)},
    "nozzle_r": {"param": "temp_c", "min": NOZZLE_MIN_C, "max": NOZZLE_MAX_C, "types": (T_BAMBU,)},
    "bed":      {"param": "temp_c", "min": BED_MIN_C, "max": BED_MAX_C, "types": ALL_TYPES},
    #  R-104 (2.983): термокамера — только у тех типов, где есть подтверждённый контракт:
    #  Bambu (команда set_ctt, см. server.py), Klipper (макрос M141 у Creality K2 Plus/Pro) и
    #  виртуальный принтер. У FlashForge поддерживаемых моделей с нагревом камеры нет.
    "chamber":  {"param": "temp_c", "min": CHAMBER_MIN_C, "max": CHAMBER_MAX_C, "types": (T_KLIPPER, T_BAMBU, T_DEMO)},
}

# Печать файла (start_print) политикой НЕ обслуживается: это файловая печать со своим
# контрактом, очередью, reservation и восстановлением, а не ручная команда. Маршрут
# обрабатывает её отдельной веткой до обращения сюда.
FILE_PRINT_ACTION = "start_print"


def is_known_action(action):
    """Входит ли действие в закрытый список. Сравнение точное: ни startswith, ни подстрок."""
    return isinstance(action, str) and action in ACTION_SPECS


def parse_int_strict(raw):
    """Целое из значения запроса или None.

    Отдельно исключён bool: в Python он подтип int, и True тихо превратился бы в 1.
    Строка разбирается только по явному шаблону, поэтому '1e2', '21,5', '210 C', ' 210 '
    с внутренними пробелами и прочие вольности не проходят. Обрезаются лишь пробелы по
    краям — ровно то, что может добавить поле ввода.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return int(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip(" ")
    if not _INT_RE.match(s):
        return None
    try:
        return int(s)
    except Exception:
        return None


def is_safe_command_line(line):
    """Пригодна ли ГОТОВАЯ строка к отправке: одна строка, без управляющих символов,
    в пределах длины. Последняя проверка перед транспортом — на случай ошибки форматтера."""
    if not isinstance(line, str) or not line:
        return False
    if len(line) > MAX_COMMAND_LEN:
        return False
    return not any(ch in _FORBIDDEN_CHARS for ch in line)


def parse_command(action, value, printer_type):
    """Разобрать запрос в нормализованное действие.

    -> (ok, normalized, reason)
    normalized: {"action": str, "temp_c": int|None} — только типизированные данные.
    Исходная строка запроса дальше НЕ передаётся никуда.
    """
    if not is_known_action(action):
        return (False, None, R_UNKNOWN_ACTION)
    spec = ACTION_SPECS[action]
    if printer_type not in spec["types"]:
        return (False, None, R_UNSUPPORTED)
    if spec["param"] is None:
        return (True, {"action": action, "temp_c": None}, "")
    n = parse_int_strict(value)
    if n is None:
        return (False, None, R_BAD_VALUE)
    if n < spec["min"] or n > spec["max"]:
        return (False, None, R_OUT_OF_RANGE)
    return (True, {"action": action, "temp_c": n}, "")


#  16.10.2026 (R-145): двухсопельные Bambu (H2D). Температуру сопла Bambu Studio задаёт НЕ G-code,
#  а командой протокола set_nozzle_temp с номером сопла (DeviceManager.cpp, command_set_nozzle_new:
#  {"print": {"command": "set_nozzle_temp", "extruder_index": N, "target_temp": T}}, QoS 1).
#  Номера — как у прошивки: DevDefs.h MAIN_EXTRUDER_ID 0, DEPUTY_EXTRUDER_ID 1; основное сопло —
#  правое (Bambu Studio StatusPanel), так же читает ha-bambulab (right = nozzle_temps[0],
#  left = nozzle_temps[1]). До этой правки «Сопло L» грело правое: T0 и есть сопло 0.
BAMBU_EXTRUDER_RIGHT, BAMBU_EXTRUDER_LEFT = 0, 1
_BAMBU_NOZZLE_INDEXES = {"nozzle_l": (BAMBU_EXTRUDER_LEFT,), "nozzle_r": (BAMBU_EXTRUDER_RIGHT,),
                         "nozzle": (BAMBU_EXTRUDER_RIGHT, BAMBU_EXTRUDER_LEFT)}


def bambu_nozzle_commands(normalized, nozzle_count=1):
    """Команды протокола Bambu для температуры сопла ДВУХСОПЕЛЬНОЙ модели. Принимает только
    нормализованные данные (результат parse_command). «nozzle» на двух соплах — обе команды.
    -> (ok, [команда], reason). Однососпельной модели — отказ R_UNSUPPORTED: ей идёт G-code."""
    if not isinstance(normalized, dict):
        return (False, [], R_BAD_COMMAND)
    action = normalized.get("action")
    t = normalized.get("temp_c")
    if not isinstance(nozzle_count, int) or isinstance(nozzle_count, bool) or nozzle_count < 2:
        return (False, [], R_UNSUPPORTED)
    if action not in _BAMBU_NOZZLE_INDEXES:
        return (False, [], R_UNSUPPORTED)
    if isinstance(t, bool) or not isinstance(t, int) or t < NOZZLE_MIN_C or t > NOZZLE_MAX_C:
        return (False, [], R_BAD_COMMAND)
    return (True, [{"print": {"sequence_id": "0", "command": "set_nozzle_temp",
                              "extruder_index": i, "target_temp": t}}
                   for i in _BAMBU_NOZZLE_INDEXES[action]], "")


def gcode_lines(normalized, nozzle_count=1):
    """Канонические строки G-code для действия. Принимает ТОЛЬКО нормализованные данные
    (результат parse_command), а не словарь запроса.

    Возвращает список строк БЕЗ завершающего разделителя: терминатор добавляет доверенный
    адаптер протокола, и он не зависит от пользовательских данных. Список длиннее одной
    строки бывает лишь там, где этого требует само железо (двухсопельная модель), и его
    длина определяется состоянием принтера, а не запросом.
    -> (ok, lines, reason)
    """
    if not isinstance(normalized, dict):
        return (False, [], R_BAD_COMMAND)
    action = normalized.get("action")
    t = normalized.get("temp_c")
    if action in ("pause", "resume", "stop"):
        return (False, [], R_UNSUPPORTED)      # управляются командой протокола, не G-code
    if not isinstance(t, bool) and isinstance(t, int):
        if action == "nozzle":
            lines = ([f"M104 S{t} T0", f"M104 S{t} T1"] if nozzle_count >= 2 else [f"M104 S{t}"])
        elif action == "nozzle_l":
            lines = [f"M104 S{t} T0"]
        elif action == "nozzle_r":
            lines = [f"M104 S{t} T1"]
        elif action == "bed":
            lines = [f"M140 S{t}"]
        elif action == "chamber":
            #  Marlin-совместимая команда камеры; у Creality K2 Plus/Pro это штатный макрос
            #  прошивки (SET_HEATER_TEMPERATURE HEATER=chamber_heater). Bambu G-code для камеры
            #  не использует — сервер шлёт ему команду протокола (см. p_cmd).
            lines = [f"M141 S{t}"]
        else:
            return (False, [], R_UNSUPPORTED)
        if not all(is_safe_command_line(x) for x in lines):
            return (False, [], R_BAD_COMMAND)
        return (True, lines, "")
    return (False, [], R_BAD_COMMAND)
