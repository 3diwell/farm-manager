# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Решение «приняла ли прошивка Bambu команду печати» — чистая логика без сети и без сервера.

ЗАЧЕМ ОТДЕЛЬНЫМ МОДУЛЕМ. Раньше решение жило внутри server.py и опиралось только на телеметрию:
«статус стал PREPARE/RUNNING — принято; принтер остался в покое и выдал ошибку — отвергнуто».
На H2D это давало ложный отказ: принтер уже выполнял команду (на экране «Homing toolhead»),
а отчёт со статусом запаздывал, и в список HMS в момент старта добавлялись записи. Программа
считала команду отвергнутой и слала следующий вариант пути к файлу — принтер отвечал
«Device is busy and cannot start new task [0500-4004]» (фото владельца, 07.09.2026).

ЧТО ЗДЕСЬ. Три источника правды, в порядке надёжности:
  1. ОТВЕТ прошивки на саму команду. Bambu отвечает на project_file тем же словарём с полями
     result/reason (по описанию протокола OpenBambuAPI, раздел MQTT — ответы на команды несут
     "result": "success"/"fail" и "reason"). Пришёл ответ — он и решает.
  2. Код 0500-4004 «устройство занято». Он появляется ТОЛЬКО если печать уже идёт — значит,
     первую команду приняли, и слать вторую нельзя. Число снято с экрана H2D владельца:
     0x05004004 = 83902468 в поле print_error.
  3. Телеметрия: статус SLICING/PREPARE/RUNNING — печать пошла.
Отказ — только если ни одного признака старта нет, а принтер при этом выдал НОВУЮ ошибку и
остался в покое до конца окна ожидания. Молчание — не отказ (медленный старт), как и раньше.

Сервер зовёт note() на каждом такте опроса и verdict() по истечении окна.
"""

STARTED_STATES = ("SLICING", "PREPARE", "RUNNING")
BUSY_CODE = 0x05004004          # «Device is busy and cannot start new task» — снято с экрана H2D
ACK_OK = ("success", "ok", "succeed", "succeeded")
ACK_FAIL = ("fail", "failed", "error", "err")

#  2.988: ЧЕТВЁРТЫЙ источник правды — поле stg_cur («чем принтер занят прямо сейчас»).
#  Зачем понадобился. Первые три источника читают gcode_state, ответ прошивки и код 0500-4004.
#  У H2D в начале печати gcode_state ещё IDLE (отчёт запаздывает), ответа может не быть, а на
#  экране уже «Homing toolhead» — то самое, что снял владелец 09.09.2026. Это состояние ВИДНО
#  в stg_cur: 13 = homing_toolhead, 2 = heatbed_preheating, 1 = auto_bed_leveling, 0 = печать.
#  Покой — только -1 (X1/H2D) и 255 (P1); значения снял из карты стадий pybambu (ha-bambulab,
#  custom_components/bambu_lab/pybambu/const.py, CURRENT_STAGE_IDS — 78 стадий).
#  ВАЖНО про ноль: 0 — это РАБОТА («printing»), поэтому отсутствие поля нельзя приводить к нулю.
#  Нет поля — «не знаю», а не «печатает»: иначе принтер без stg_cur всегда считался бы занятым.
IDLE_STAGES = (-1, 255)

#  16.10.2026 (R-138). После завершения или отмены печати стадия ничего не говорит о занятости:
#  P1S на прошивке 01.10.00.00 после отмены держит последнюю стадию (например 54 «ждёт температуру
#  стола») при gcode_state FAILED и print_type «idle» — до следующей печати (ha-bambulab #2161, правка
#  там же — PR #2168). Bambu Studio стадию для «занят» не читает вовсе: печать запрещена только при
#  gcode_state RUNNING/PAUSE/SLICING/PREPARE (DeviceManager.cpp is_in_printing_status) и при смене
#  филамента в AMS (SelectMachine.cpp). FINISHED_RAW — «печать этой отправки закончилась» (база стадии
#  в server._bambu_stage_base_of); для занятости стадия не в счёт только при CANCELLED_RAW (ниже).
FINISHED_RAW = ("FINISH", "FAILED")

#  16.10.2026 (R-138, проверка пакета): стадия не в счёт ТОЛЬКО при сыром FAILED — ровно как в
#  ha-bambulab PR #2168 (правка #2161): там намеренно ключ gcode_state FAILED, а не print_type «idle», —
#  чтобы не задеть стадии калибровки и загрузки филамента, запущенных с экрана принтера; FINISH там
#  оставлен, потому что часть принтеров законно сообщает стадию после печати (охлаждение). Прежнее
#  правило «print_type idle — покой при любой стадии» пропускало команду принтеру, который грузит
#  филамент или калибруется по кнопке с экрана: он отвечал 0500-4004, а программа считала печать начатой.
CANCELLED_RAW = ("FAILED",)

#  16.10.2026 (R-138): главный байт ams_status, при котором Bambu Studio не даёт отправить печать
#  (SelectMachine.cpp, проверка перед отправкой): 0x01 — смена филамента, 0x07 — холодная протяжка.
#  Главный байт = (ams_status & 0xFF00) >> 8 (DeviceManager.cpp _parse_ams_status, перечисление в
#  DeviceCore/DevDefs.h). Отчёт принтера в покое даёт 768 (0x03 — ASSIST), это не занятость.
AMS_MAIN_FILAMENT_CHANGE = 0x01
AMS_MAIN_COLD_PULL = 0x07
AMS_BUSY_MAIN = (AMS_MAIN_FILAMENT_CHANGE, AMS_MAIN_COLD_PULL)

#  16.10.2026 (R-138): названия стадий stg_cur — дословно из таблицы pybambu (ha-bambulab,
#  custom_components/bambu_lab/pybambu/const.py, CURRENT_STAGE_IDS). Только для показа причины
#  «принтер занят» человеку: решения по названию не принимаются.
STAGE_NAMES = {
    0: "printing", 1: "auto_bed_leveling", 2: "heatbed_preheating", 3: "sweeping_xy_mech_mode",
    4: "changing_filament", 5: "m400_pause", 6: "paused_filament_runout", 7: "heating_hotend",
    8: "calibrating_extrusion", 9: "scanning_bed_surface", 10: "inspecting_first_layer",
    11: "identifying_build_plate_type", 12: "calibrating_micro_lidar", 13: "homing_toolhead",
    14: "cleaning_nozzle_tip", 15: "checking_extruder_temperature", 16: "paused_user",
    17: "paused_front_cover_falling", 18: "calibrating_micro_lidar", 19: "calibrating_extrusion_flow",
    20: "paused_nozzle_temperature_malfunction", 21: "paused_heat_bed_temperature_malfunction",
    22: "filament_unloading", 23: "paused_skipped_step", 24: "filament_loading",
    25: "calibrating_motor_noise", 26: "paused_ams_lost", 27: "paused_low_fan_speed_heat_break",
    28: "paused_chamber_temperature_control_error", 29: "cooling_chamber", 30: "paused_user_gcode",
    31: "motor_noise_showoff", 32: "paused_nozzle_filament_covered_detected", 33: "paused_cutter_error",
    34: "paused_first_layer_error", 35: "paused_nozzle_clog",
    36: "check_absolute_accuracy_before_calibration", 37: "absolute_accuracy_calibration",
    38: "check_absolute_accuracy_after_calibration", 39: "calibrate_nozzle_offset",
    40: "bed_level_high_temperature", 41: "check_quick_release", 42: "check_door_and_cover",
    43: "laser_calibration", 44: "check_plaform", 45: "check_birdeye_camera_position",
    46: "calibrate_birdeye_camera", 47: "bed_level_phase_1", 48: "bed_level_phase_2",
    49: "heating_chamber", 50: "heated_bedcooling", 51: "print_calibration_lines", 52: "check_material",
    53: "calibrating_live_view_camera", 54: "waiting_for_heatbed_temperature",
    55: "check_material_position", 56: "calibrating_cutter_model_offset", 57: "measuring_surface",
    58: "thermal_preconditioning", 59: "homing_blade_holder", 60: "calibrating_camera_offset",
    61: "calibrating_blade_holder_position", 62: "hotend_pick_place_test",
    63: "waiting_chamber_temperature_equalize", 64: "preparing_hotend",
    65: "calibrating_detection_nozzle_clumping", 66: "purifying_chamber_air",
    67: "measuring_rotary_attachment", 68: "moving_toolhead_above_purge_chute", 69: "cooling_nozzle",
    70: "moving_toolhead_to_center_of_heatbed", 71: "active_arc_fitting", 72: "hotend_type_detection",
    73: "build_plate_alignment_detection", 74: "heatbed_surface_foreign_object_detection",
    75: "heatbed_underside_foreign_object_detection", 76: "pre_extrusion_before_printing",
    77: "preparing_ams", -1: "idle", 255: "idle",
}

#  16.10.2026 (R-138, проверка пакета): короткие русские названия стадий, которые бывают до печати и
#  в подготовке, — для причины «принтер занят» в панели отправок и в очереди: владелец читает её
#  по-русски. Английский текст и журнал называют стадию по таблице pybambu. Стадия без перевода —
#  только номером. Решения по названию не принимаются.
STAGE_NAMES_RU = {
    0: "печать", 1: "выравнивание стола", 2: "прогрев стола", 4: "смена филамента", 7: "нагрев сопла",
    8: "калибровка экструзии", 9: "сканирование стола", 13: "парковка головы", 14: "очистка сопла",
    22: "выгрузка филамента", 24: "загрузка филамента", 25: "калибровка шума моторов",
    29: "охлаждение камеры", 49: "нагрев камеры", 54: "ожидание температуры стола", 77: "подготовка AMS",
}

#  16.10.2026 (R-138): «стадии до команды нет» — отличается от None (принтер стадию не сообщал).
NO_BASE = object()


def _int(v, default=0):
    try:
        return int(v or 0)
    except Exception:
        return default


def _int_or_none(v):
    """Целое или None. Отдельно от _int: тот приводит None и '' к нулю, а ноль здесь значим."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        return None


def is_working_stage(stg_cur, print_type=None, gcode_state=None):
    """Принтер ЧТО-ТО выполняет прямо сейчас (парковка, прогрев стола, калибровка, печать).

    Годится ровно для одного решения: слать ли принтеру ВТОРУЮ команду печати. Не годится
    для ответа «наша ли это печать» — стадия не различает, кто её затеял. Но для нашего
    решения это и не нужно: занятому принтеру вторая команда даст «Device is busy» независимо
    от того, чем он занят.

    08.10.2026 (ферма оператора: P1P и P1S, файл на принтере, а печать «не запущена — the printer
    is busy: it is running a preparation step»; с экрана тот же файл запускается). Прошивка Bambu
    после включения сообщает stg_cur = 0 («печатает») у принтера в ПОКОЕ — и держит так до первой
    печати. Источник — pybambu (ha-bambulab), StageAction.print_update, дословно: «On boot the
    printer reports stg_cur == 0 incorrectly instead of 255. Attempt to correct for this.», поправка
    там же: print_type == "idle" и стадия 0 → 255. Без неё программа отказывала простаивающему
    принтеру до команды, а очередь показывала его «выполняет подготовку (стадия 0)». print_type
    нет в отчёте — поправка не применяется (ноль остаётся работой, как раньше).

    16.10.2026 (R-138, тот же отказ после ОТМЕНЕННОЙ печати). P1S после отмены держит последнюю
    стадию (54 «ждёт температуру стола») с gcode_state FAILED и print_type «idle» до следующей печати
    (ha-bambulab #2161; PR #2168 там же: при FAILED стадия = покой). Поэтому сырой gcode_state FAILED —
    стадия не в счёт. Только FAILED и только стадия 0 при print_type «idle» — как в источниках:
    калибровка или загрузка филамента, запущенные с экрана (сырой IDLE или FINISH, стадия 8/13/22/24/25,
    print_type «idle»), — это работа, и команду печати такому принтеру слать нельзя (проверка пакета
    16.10.2026: при «idle — покой при любой стадии» команда уходила, принтер отвечал 0500-4004).
    gcode_state — СЫРОЕ состояние прошивки (status_raw): показанное в карточке после «Стоп»
    подменяется на IDLE. Нет аргумента — проверка по нему не делается (как раньше)."""
    v = _int_or_none(stg_cur)
    if v is None or v in IDLE_STAGES:
        return False
    if str(gcode_state or "").strip().upper() in CANCELLED_RAW:
        return False
    if v == 0 and str(print_type or "").strip().lower() == "idle":
        return False
    return True


def stage_started(stage, base_stage):
    """После НАШЕЙ команды: стадия — признак начавшейся печати, только если она сменилась.

    16.10.2026 (R-138). base_stage — стадия, снятая перед первой командой этой отправки. Застрявшая
    стадия (54 после отмены, 0 после включения) с ней совпадает и стартом не считается; парковка
    головы H2D после команды (13 при прежних -1/255) — считается, даже пока gcode_state ещё IDLE
    (2.988). Покой (-1, 255) и отсутствие поля — не старт."""
    v = _int_or_none(stage)
    if v is None or v in IDLE_STAGES:
        return False
    return v != _int_or_none(base_stage)


def stage_name(stg_cur):
    """Название стадии по таблице pybambu или '' (для показа причины человеку)."""
    v = _int_or_none(stg_cur)
    return STAGE_NAMES.get(v, "") if v is not None else ""


def stage_name_ru(stg_cur):
    """Русское название стадии (STAGE_NAMES_RU) или '' — тогда стадию называют только номером."""
    v = _int_or_none(stg_cur)
    return STAGE_NAMES_RU.get(v, "") if v is not None else ""


def ams_busy(ams_status):
    """Главный байт ams_status — смена филамента (0x01) или холодная протяжка (0x07)? -> 0x01/0x07 или 0.

    Правило Bambu Studio (SelectMachine.cpp): с таким состоянием AMS окно отправки печать не пускает."""
    v = _int_or_none(ams_status)
    if v is None or v < 0:
        return 0
    main = (v >> 8) & 0xFF
    return main if main in AMS_BUSY_MAIN else 0


def is_busy_code(print_error):
    """Код «устройство занято» в поле print_error (число или строка)."""
    return _int(print_error) == BUSY_CODE


def ack_kind(ack, since):
    """Ответ прошивки на команду печати: 'ok' | 'fail' | None (нет ответа или он старый)."""
    if not isinstance(ack, dict):
        return None
    if ack.get("command") not in ("project_file", "gcode_file"):
        return None
    try:
        if float(ack.get("ts") or 0) < float(since or 0):
            return None                 # ответ на ПРОШЛУЮ команду — не в счёт
    except Exception:
        return None
    r = str(ack.get("result") or "").strip().lower()
    if r in ACK_OK:
        return "ok"
    if r in ACK_FAIL:
        return "fail"
    return None


class StartWatch:
    """Наблюдение за ОДНОЙ командой печати. base_* — признаки ошибок ДО команды: новым считается
    только то, чего до команды не было.

    first (16.10.2026, R-138, проверка пакета) — это ПЕРВАЯ команда печати этой отправки. Тогда
    код 0500-4004, которого до команды не было, — ответ принтера на НАШУ команду: он занят своим
    заданием (Bambuddy #2598: команда печати занятому принтеру получает 0500-4004), и наша печать
    не началась. Вердикт — 'busy', а не 'ok'. После второй и следующих команд 0500-4004 по-прежнему
    значит «первую приняли» (снимок H2D владельца, 07.09.2026)."""

    def __init__(self, base_pe=0, base_mce="0", base_hms=0, since=0.0, base_stage=NO_BASE, first=False):
        self.base_pe = _int(base_pe)
        self.base_mce = str(base_mce or "0")
        self.base_hms = _int(base_hms)
        self.since = since
        #  16.10.2026 (R-138): стадия перед первой командой этой отправки (NO_BASE — не снята).
        self.base_stage = base_stage
        self.first = bool(first)
        self.err_seen = False
        self.ack_reason = ""

    def stage_evidence(self, st):
        """Говорит ли стадия, что печать пошла. Стадия до команды известна — только её смена
        (stage_started); не известна — стадия работы по прежнему правилу с поправками R-138."""
        if self.base_stage is not NO_BASE:
            return stage_started(st.get("stage"), self.base_stage)
        return is_working_stage(st.get("stage"), st.get("print_type"),
                                st.get("status_raw") or st.get("status"))

    def note(self, state, ack=None):
        """Один такт. -> 'ok' | 'fail' | 'wait' | 'busy' (только при first)."""
        st = state or {}
        pe = _int(st.get("print_error"))
        if self.first and pe == BUSY_CODE and self.base_pe != BUSY_CODE:
            return "busy"               # 16.10.2026: принтер занят своим заданием — наша печать не началась
        status = str(st.get("status") or "").upper()
        if status in STARTED_STATES:
            return "ok"
        if pe == BUSY_CODE:
            return "ok"                 # печать уже идёт: первую команду приняли
        if self.stage_evidence(st):
            return "ok"                 # 2.988: принтер уже выполняет стадию (парковка/прогрев)
        k = ack_kind(ack, self.since)
        if k == "ok":
            return "ok"
        if k == "fail":
            self.ack_reason = str((ack or {}).get("reason") or "")
            return "fail"
        mce = str(st.get("mc_err") or "0")
        hms = _int(st.get("hms_n"))
        if (pe != 0 and pe != self.base_pe) or (mce not in ("0", "") and mce != self.base_mce) or (hms > self.base_hms):
            self.err_seen = True
        return "wait"

    def verdict(self):
        """Окно ожидания истекло без явного сигнала."""
        return "fail" if self.err_seen else "timeout"
