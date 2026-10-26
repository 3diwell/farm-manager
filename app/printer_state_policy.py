# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — единая нормализация состояний принтера (Alpha 2.791).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, веб-фреймворк, СУБД
и принтерные подсистемы, не обращается к сети и к принтерам, ничего не пишет в журнал и не
меняет состояние. Только классификация — вход неизменяем, выход детерминирован.

ЗАЧЕМ. Одна и та же строка прошивки разбиралась в трёх местах по разным правилам: ядро
держало белый список безопасного покоя, интерфейс — свою таблицу цветов, а причина отказа
собиралась как `not_idle_raw:<сырая строка>`. В результате карточка красила завершившуюся
печать зелёным «Готово», планировщик тот же принтер отклонял, а оператор видел техническую
строку вместо объяснения. Здесь эти правила сведены в одно место.

ЧТО ЭТОТ МОДУЛЬ НЕ МЕНЯЕТ — и это принципиально. Он НЕ расширяет допуск к печати. Порог
безопасного покоя остаётся прежним: покой — это доказанный канонический idle КОНКРЕТНОГО
транспорта, и только он. FINISH и complete покоем НЕ становятся: на Bambu FINISH означает
«печать закончена, деталь ещё на столе», и снять этот барьер может ТОЛЬКО оператор кнопкой
«Стол очищен» (см. IDLE_NOT_PROOF в app/project_orchestrator.py). Модуль меняет ровно две
вещи: даёт завершению и ошибке СВОИ причины вместо общего not_idle_raw и позволяет
интерфейсу и планировщику опираться на один и тот же разбор.

ПОЧЕМУ ТАБЛИЦЫ РАЗДЕЛЬНЫЕ ПО ТРАНСПОРТАМ. Строки не совпадают между прошивками: Bambu шлёт
'PAUSE' (не 'PAUSED') и 'FINISH'; Klipper — 'complete' и 'standby'; FlashForge — 'ready' и
'completed'. Общая таблица на все транспорты означала бы, что неизвестная строка одной
прошивки случайно совпадёт с известной строкой другой.
"""


class Lifecycle(object):
    """Этап жизненного цикла задания, выведенный из сырого состояния прошивки."""
    UNKNOWN = "UNKNOWN"
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    PRINTING = "PRINTING"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"
    FAILED = "FAILED"


class Readiness(object):
    """Пригодность принтера к СЛЕДУЮЩЕМУ заданию."""
    READY = "READY"
    BUSY = "BUSY"
    BLOCKED = "BLOCKED"
    OFFLINE = "OFFLINE"
    UNKNOWN = "UNKNOWN"


# ── Причины. Стабильные машинные коды; человекочитаемый текст подбирает интерфейс.
#    Ни один код не содержит сырой строки прошивки — она остаётся отдельным
#    диагностическим полем и в принятии решения не участвует.
REASON_READY = "ready"
REASON_OFFLINE_OR_STALE = "offline_or_stale"
REASON_NO_STATUS_RAW = "no_status_raw"
REASON_USER_STOP_PENDING = "user_stop_pending"
REASON_UNKNOWN_TRANSPORT = "unknown_transport"
REASON_PRINTING = "printing"
REASON_PREPARING = "preparing"
REASON_PAUSED = "paused"
REASON_FINISHED_AWAITING_CLEARANCE = "finished_awaiting_clearance"
REASON_JOB_FAILED = "job_failed"
REASON_STATE_UNKNOWN = "state_unknown"
REASON_STATUS_NOT_IDLE = "status_not_idle"

# ── Сырые состояния по транспортам. Источники: Bambu gcode_state, Klipper
#    print_stats.state, FlashForge detail.status — ровно те строки, которые разбирают
#    адаптеры в server.py. Выдуманных вариантов здесь нет намеренно.
_RAW_MAP = {
    "bambu": {
        "IDLE": Lifecycle.IDLE,
        "RUNNING": Lifecycle.PRINTING,
        "PREPARE": Lifecycle.PREPARING,
        "SLICING": Lifecycle.PREPARING,
        "PAUSE": Lifecycle.PAUSED,      # Bambu шлёт PAUSE, а не PAUSED
        "PAUSED": Lifecycle.PAUSED,
        "FINISH": Lifecycle.FINISHED,
        "FAILED": Lifecycle.FAILED,
    },
    "klipper": {
        "standby": Lifecycle.IDLE,
        "printing": Lifecycle.PRINTING,
        "paused": Lifecycle.PAUSED,
        "complete": Lifecycle.FINISHED,
        "error": Lifecycle.FAILED,
        "cancelled": Lifecycle.FAILED,
    },
    "flashforge": {
        "ready": Lifecycle.IDLE,
        "idle": Lifecycle.IDLE,
        "printing": Lifecycle.PRINTING,
        "heating": Lifecycle.PRINTING,
        "busy": Lifecycle.PRINTING,
        "paused": Lifecycle.PAUSED,
        "pausing": Lifecycle.PAUSED,
        "pause": Lifecycle.PAUSED,      # 12.10.2026: так пишет паузу часть прошивок FlashForge
        "completed": Lifecycle.FINISHED,
        "complete": Lifecycle.FINISHED,
        "error": Lifecycle.FAILED,
        "cancel": Lifecycle.FAILED,
        "cancelled": Lifecycle.FAILED,
    },
    #  12.10.2026: Creality на заводской прошивке (родная служба, порт 9999). Прошивка шлёт число
    #  состояния; адаптер (app/creality_native.py) сам сводит его к этим словам — незнакомое число
    #  остаётся незнакомым (fail-closed), покоем не становится.
    "creality": {
        "idle": Lifecycle.IDLE,
        "printing": Lifecycle.PRINTING,
        "paused": Lifecycle.PAUSED,
        "complete": Lifecycle.FINISHED,
        "error": Lifecycle.FAILED,
        "cancelled": Lifecycle.FAILED,
    },
}

# Регистр сырых строк у транспортов разный и значимый: Bambu отдаёт ЗАГЛАВНЫМИ, Klipper и
# FlashForge — строчными. Приводим к тому регистру, в котором прошивка их присылает, а не к
# общему: иначе неизвестная строка одной прошивки совпала бы с известной строкой другой.
_RAW_CASE = {"bambu": "upper", "klipper": "lower", "flashforge": "lower", "creality": "lower"}

SUPPORTED_TRANSPORTS = frozenset(_RAW_MAP)

# Покой, доказывающий, что можно готовить следующее задание. Ровно прежний белый список:
# этап 2.791 его НЕ расширяет.
_QUIET = frozenset((Lifecycle.IDLE,))

# Состояния, доказывающие, что задание физически идёт (движение/нагрев/пауза посреди печати).
# Используется НЕ для допуска к печати, а для запрета подтверждать «Стол очищен».
_ACTIVE = frozenset((Lifecycle.PRINTING, Lifecycle.PREPARING, Lifecycle.PAUSED))

_LIFECYCLE_REASON = {
    Lifecycle.PRINTING: REASON_PRINTING,
    Lifecycle.PREPARING: REASON_PREPARING,
    Lifecycle.PAUSED: REASON_PAUSED,
    Lifecycle.FINISHED: REASON_FINISHED_AWAITING_CLEARANCE,
    Lifecycle.FAILED: REASON_JOB_FAILED,
    Lifecycle.UNKNOWN: REASON_STATE_UNKNOWN,
}

_TERMINAL = frozenset((Lifecycle.FINISHED, Lifecycle.FAILED))
_SUCCESSFUL_TERMINAL = frozenset((Lifecycle.FINISHED,))


def normalize_raw(transport, raw):
    """Сырая строка прошивки -> этап жизненного цикла.

    Не-строка, пустое значение, неизвестный транспорт и незнакомая строка дают UNKNOWN:
    неизвестное никогда не становится покоем (fail-closed).
    """
    t = str(transport or "").strip().lower()
    table = _RAW_MAP.get(t)
    if table is None:
        return Lifecycle.UNKNOWN
    if not isinstance(raw, str):
        return Lifecycle.UNKNOWN
    s = raw.strip()
    if not s:
        return Lifecycle.UNKNOWN
    s = s.upper() if _RAW_CASE.get(t) == "upper" else s.lower()
    return table.get(s, Lifecycle.UNKNOWN)


def is_quiet(lifecycle):
    """Доказанный покой (можно готовить следующее задание при прочих условиях)."""
    return lifecycle in _QUIET


def is_active(lifecycle):
    """Задание физически идёт или стоит на паузе посреди печати."""
    return lifecycle in _ACTIVE


def is_terminal(lifecycle):
    return lifecycle in _TERMINAL


def is_successful_terminal(lifecycle):
    return lifecycle in _SUCCESSFUL_TERMINAL


def reason_for(lifecycle):
    """Причина отказа, соответствующая этапу. Для покоя причины нет."""
    if is_quiet(lifecycle):
        return REASON_READY
    return _LIFECYCLE_REASON.get(lifecycle, REASON_STATE_UNKNOWN)


def readiness_for(lifecycle, fresh=True, blockers=()):
    """Пригодность к следующему заданию.

    blockers — уже установленные вызывающим препятствия (резервирование отправки, чужой
    запуск, удержание принтера и т. п.). Модуль их не вычисляет: он не знает ни очереди, ни
    восстановления, ни базы. Любое препятствие делает результат BLOCKED.
    """
    if not fresh:
        return Readiness.OFFLINE
    if blockers:
        return Readiness.BLOCKED
    if lifecycle == Lifecycle.UNKNOWN:
        return Readiness.UNKNOWN
    if is_quiet(lifecycle):
        return Readiness.READY
    if is_active(lifecycle):
        return Readiness.BUSY
    return Readiness.BLOCKED   # FINISHED (стол не подтверждён) и FAILED
