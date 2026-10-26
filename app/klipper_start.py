# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.833 — формальный контракт результата запуска печати для Klipper/Moonraker.

ПРОБЛЕМА, которую этот модуль формализует. Klipper-запуск в server.py — это ОДИН HTTP-запрос
`/server/files/upload?print=true` (файл + команда печати вместе). Если Moonraker уже принял запрос
и начал печать, но HTTP-ОТВЕТ не успел вернуться до client read-timeout, старый код подписывал это
как «Ошибка запуска печати: timed out» и создавал ложный провал — хотя через секунду телеметрия
того же принтера показывала печать того же файла.

Модуль — ЧИСТЫЙ (без сети, без импортов server.py): его гоняют оффлайн-тесты. Никогда не бросает.

ЧЕСТНО ПРО ОБЛАСТЬ ПРИМЕНЕНИЯ (уточнено 26.08.2026 разбором): в продукте server.py разбирает
исход ВНУТРИ СЕБЯ — по типу исключения urllib (HTTPError -> отказ, TimeoutError -> ожидание
подтверждения, URLError -> команда не ушла), а отсюда берёт только текст сообщения
(`user_message`). То есть этот модуль — формальный контракт и площадка для оффлайн-проверок,
а НЕ единственное место, где живёт классификация. Меняешь правила исхода — правь ОБА места:
здесь и в server.py (ветки `except` вокруг upload/print). Раньше в этом абзаце было написано
«единственный источник правды», и это вводило в заблуждение.

КЛЮЧЕВОЙ ПРИНЦИП. read-timeout ПОСЛЕ отправки запроса ≠ доказанный отказ. Команда МОГЛА быть
принята устройством. Поэтому:
  • такой исход = PENDING_CONFIRMATION (ждём подтверждения по телеметрии), НЕ провал;
  • команду НИКОГДА не повторяем автоматически (upload+print не идемпотентны — второй старт-пар);
  • подтверждение — по факту телеметрии ТОГО ЖЕ принтера и ТОГО ЖЕ файла (см. evaluate_confirmation).
"""

# ── Состояния решения о запуске ────────────────────────────────────────────────────────────────
CONFIRMED = "confirmed"                     # телеметрия/ответ доказали старт
PENDING_CONFIRMATION = "pending_confirmation"  # команда могла быть принята, ответа нет → ждём
REJECTED = "rejected"                        # устройство однозначно отказало (HTTP-ошибка / print_started=false)
FAILED_BEFORE_SEND = "failed_before_send"    # сбой ДО отправки (connect/DNS/файл не готов)
UNCERTAIN = "uncertain"                      # дедлайн истёк, доказать отказ невозможно → ручная проверка

DECISION_STATES = (CONFIRMED, PENDING_CONFIRMATION, REJECTED, FAILED_BEFORE_SEND, UNCERTAIN)

# Разрешён ли повтор (ТОЛЬКО ручной, после исправления причины и свежей ревалидации).
# PENDING/UNCERTAIN/CONFIRMED → авто-повтор ЗАПРЕЩЁН (команда могла дойти).
_RETRY_ALLOWED = {
    FAILED_BEFORE_SEND: True,               # до отправки — ничего не начато, повтор безопасен
    REJECTED: True,                         # доказанный отказ — повтор после исправления причины
    PENDING_CONFIRMATION: False,
    UNCERTAIN: False,
    CONFIRMED: False,
}

# Пользовательские сообщения (RU · EN). Красную ошибку показываем ТОЛЬКО для доказанного отказа.
USER_MESSAGES = {
    PENDING_CONFIRMATION: "Команда отправлена. Ожидание подтверждения запуска… · Command sent. Waiting for start confirmation…",
    CONFIRMED: "Печать началась. · Print started.",
    UNCERTAIN: "Не удалось подтвердить запуск. Проверьте состояние принтера перед повторной отправкой. · Could not confirm the start. Check the printer before sending again.",
    REJECTED: "Принтер отклонил запуск печати. · The printer rejected the print start.",
    FAILED_BEFORE_SEND: "Не удалось отправить команду печати. · Failed to send the print command.",
}

# Виды транспортных исходов Klipper-отправки (server.py передаёт ровно один из них).
KIND_TIMEOUT_AFTER_SEND = "timeout_after_send"  # bare socket.timeout при чтении ОТВЕТА (запрос ушёл)
KIND_CONNECT_ERROR = "connect_error"            # соединение не установлено / оборвано ДО отправки
KIND_DNS_ERROR = "dns_error"                     # имя не разрешилось (запрос не мог уйти)
KIND_HTTP_ERROR = "http_error"                   # Moonraker ответил 4xx/5xx
KIND_PRINT_STARTED_FALSE = "print_started_false"  # файл принят, но print_started=false
KIND_UNKNOWN = "unknown"


def classify_transport_failure(kind):
    """Транспортный исход отправки → состояние решения. Никогда не бросает.

    timeout_after_send — ЕДИНСТВЕННЫЙ неоднозначный случай: запрос доставлен, ответ не получен →
    PENDING (не провал, не повтор). Всё, что доказуемо произошло ДО отправки, — FAILED_BEFORE_SEND.
    Явный отказ Moonraker (HTTP / print_started=false) — REJECTED.
    """
    if kind == KIND_TIMEOUT_AFTER_SEND:
        return PENDING_CONFIRMATION
    if kind in (KIND_CONNECT_ERROR, KIND_DNS_ERROR):
        return FAILED_BEFORE_SEND
    if kind in (KIND_HTTP_ERROR, KIND_PRINT_STARTED_FALSE):
        return REJECTED
    # Неизвестный/непредвиденный сбой — консервативно как провал ДО отправки НЕ считаем: команда
    # могла уйти. Возвращаем PENDING, чтобы НЕ создать ложный красный провал и НЕ повторить команду.
    return PENDING_CONFIRMATION


def retry_allowed(decision):
    """Разрешён ли (ручной) повтор для данного решения. Авто-повтор запрещён везде."""
    return bool(_RETRY_ALLOWED.get(decision, False))


def user_message(decision):
    """RU · EN сообщение для UI по состоянию решения."""
    return USER_MESSAGES.get(decision, "")


# ── Идентичность имени файла Moonraker ───────────────────────────────────────────────────────────
# print_stats.filename Moonraker — путь ОТНОСИТЕЛЬНО корня gcodes (может быть с подпапкой:
# "M Frame_4h19m.gcode" или "job/part.gcode"). Для сопоставления с запрошенным файлом сравниваем
# basename без учёта регистра и разделителей путей. Пустое имя телеметрии сопоставить НЕЛЬЗЯ.
def normalize_filename(name):
    """basename без каталогов, casefold. '' → '' (сопоставлять нечем)."""
    s = str(name or "").strip().replace("\\", "/")
    if not s:
        return ""
    s = s.rsplit("/", 1)[-1]                 # отбрасываем каталоги (gcodes/subdir/x → x)
    return s.strip().casefold()


def filenames_match(requested, observed):
    """Совпадает ли печатаемый принтером файл с запрошенным. Пустое наблюдение → False."""
    a = normalize_filename(requested)
    b = normalize_filename(observed)
    if not a or not b:
        return False
    return a == b


# ── Attempt / Decision ───────────────────────────────────────────────────────────────────────────
# Состояния Klipper print_stats, доказывающие, что задание ФИЗИЧЕСКИ идёт (движение/пауза посреди
# печати). standby/complete/error/cancelled — НЕ доказывают запуск НАШЕГО attempt.
_RUNNING_STATES = ("printing", "paused")
# Свежие «покойные» состояния: если принтер устойчиво в них после дедлайна — старт НЕ подтверждён.
_IDLE_STATES = ("standby", "ready", "idle", "operational")


class PrintStartAttempt:
    """Неизменяемая (по смыслу) запись одной попытки запуска. started_at/deadline — монотонные
    секунды, передаются извне (модуль не читает часы, чтобы не мешать resume/тестам)."""

    __slots__ = ("printer_id", "adapter", "attempt_id", "requested_file", "started_at",
                 "confirmation_deadline", "command_sent", "reservation_id", "lifecycle_session_id")

    def __init__(self, printer_id, requested_file, started_at, confirmation_window,
                 adapter="klipper", attempt_id="", command_sent=True,
                 reservation_id="", lifecycle_session_id=""):
        self.printer_id = str(printer_id or "")
        self.adapter = str(adapter or "klipper")
        self.attempt_id = str(attempt_id or "")
        self.requested_file = str(requested_file or "")
        self.started_at = float(started_at)
        self.confirmation_deadline = float(started_at) + float(confirmation_window)
        self.command_sent = bool(command_sent)
        self.reservation_id = str(reservation_id or "")
        self.lifecycle_session_id = str(lifecycle_session_id or "")

    def normalized_file(self):
        return normalize_filename(self.requested_file)


def evaluate_confirmation(attempt, printer_id, state, filename, now,
                          session_start=None, fresh=True):
    """Сопоставить телеметрию с ожидающей попыткой → одно из DECISION_STATES.

    printer_id/state/filename — наблюдение телеметрии. now — монотонное время. session_start —
    момент начала наблюдаемой физической сессии печати (если известен), fresh — свежа ли телеметрия.

    Правила (fail-closed — подтверждаем ТОЛЬКО при доказательстве):
      • другой принтер                                   → PENDING (не наш) ;
      • state printing/paused И имя файла совпадает И
        (session_start неизвестен ИЛИ ≥ started_at−slack) → CONFIRMED ;
      • state printing/paused, но ФАЙЛ иной                → PENDING (это не наш attempt) ;
      • state printing/paused, но session_start ЯВНО старше → PENDING (это прошлая сессия) ;
      • свежий idle/standby и now > deadline               → UNCERTAIN, если телеметрия свежая, но
        мы не можем доказать отказ; вызывающий решает про failed по своей политике grace ;
      • телеметрия НЕсвежая                                → PENDING (ждём, без ложного вывода) ;
      • дедлайн истёк без доказательств                    → UNCERTAIN.
    """
    st = str(state or "").strip().lower()
    # Наблюдение по ЧУЖОМУ принтеру наш attempt не подтверждает и не опровергает.
    if str(printer_id or "") != attempt.printer_id:
        return PENDING_CONFIRMATION
    if st in _RUNNING_STATES:
        if not filenames_match(attempt.requested_file, filename):
            return PENDING_CONFIRMATION      # печатается ДРУГОЙ файл — это не наш запуск
        if session_start is not None:
            # slack 2 c: телеметрия могла отставать; сессия СТАРШЕ attempt (с запасом) — не наша.
            if float(session_start) < attempt.started_at - 2.0:
                return PENDING_CONFIRMATION
        return CONFIRMED
    if not fresh:
        return PENDING_CONFIRMATION          # нечего утверждать по устаревшей телеметрии
    if now > attempt.confirmation_deadline:
        return UNCERTAIN                      # дедлайн истёк, отказ доказать невозможно
    return PENDING_CONFIRMATION
