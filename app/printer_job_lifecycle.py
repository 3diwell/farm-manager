# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — единая модель наблюдения за печатью (Alpha 2.807).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, веб-фреймворк, СУБД,
принтерные подсистемы; не ходит в сеть, не пишет журнал, не меняет глобальное состояние.
Все функции детерминированы: одинаковый вход -> одинаковый выход. Время и генерация
идентификаторов приходят СНАРУЖИ (параметрами), чтобы тесты были воспроизводимы.

ЗАЧЕМ (задача Alpha 2.807).
Печать, запущенная НЕ из Farm Manager, а прямо с экрана принтера (в том числе повторная печать
ранее отправленного файла), должна одинаково распознаваться на всех поддерживаемых принтерах:
получать статус «печатается» на конкретном принтере и ровно один раз увеличивать количество
готовых экземпляров после успешного завершения.

Прежний механизм жил в `handle_state` (server.py) и опирался ТОЛЬКО на оперативную память
процесса (`last_st`, `last_job`, `print_source`) плюс строку `project_print_jobs`. Физического
идентификатора запуска не было вовсе: единственной «личностью» задания было имя файла. Отсюда
три следствия, подтверждённые журналом фермы:
  * перезапуск программы во время печати терял состояние и порождал ВТОРУЮ строку задания
    на ту же физическую печать (дальше — `ambiguous_multi`, «учёт не ведём»);
  * стартовая уборка «осиротевших» заданий (Alpha 2.767) гасила задания экранной печати,
    потому что у них принципиально нет строки-владельца в плане оркестратора;
  * повторная печать того же файла не отличалась от «того же самого» задания.

Здесь эти решения собраны в одном месте и отделены от протоколов. Адаптер обязан только
превратить сырой отчёт в `PrinterJobObservation`; он НЕ создаёт и НЕ закрывает запуски,
НЕ трогает счётчики проекта и НЕ решает, какому проекту принадлежит печать.

ЧТО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ (принципиально).
  * Не обещает «никогда не сломается». Он даёт проверяемый контракт: одна модель жизненного
    цикла, тонкие адаптеры, fail-closed сопоставление и идемпотентный учёт.
  * Не расширяет допуск к печати и не отправляет команды принтерам.
  * Не считает завершением ни `offline`, ни `idle`: успех засчитывается ТОЛЬКО по доказанному
    терминальному состоянию прошивки (terminal evidence).
  * Не занимается нечётким сопоставлением имён: похожесть строк, «содержит», «начинается с»
    и совпадение одного лишь расширения не являются совпадением никогда.

ОТНОШЕНИЕ К app/printer_state_policy.py.
Таблицы сырых строк прошивок живут ТАМ и здесь НЕ дублируются: `normalize_state` вызывает
`printer_state_policy.normalize_raw`. Этот модуль добавляет ровно одно, чего той политике
не хватало для учёта: отделяет ОТМЕНУ от ОШИБКИ (обе там сведены в FAILED, потому что для
допуска к следующей печати разницы нет, а для счётчика готовых деталей — есть).
"""

import hashlib
import re
import unicodedata

from . import printer_state_policy as _policy


# ── Нормализованные состояния наблюдения (protocol-neutral) ────────────────────────────────────
STATE_UNKNOWN = "unknown"
STATE_OFFLINE = "offline"
STATE_IDLE = "idle"
STATE_PREPARING = "preparing"
STATE_PRINTING = "printing"
STATE_PAUSED = "paused"
STATE_COMPLETED = "completed"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"

NORMALIZED_STATES = frozenset((
    STATE_UNKNOWN, STATE_OFFLINE, STATE_IDLE, STATE_PREPARING,
    STATE_PRINTING, STATE_PAUSED, STATE_COMPLETED, STATE_CANCELLED, STATE_FAILED,
))

# Состояния, при которых печать физически идёт (в т.ч. пауза посреди печати).
ACTIVE_STATES = frozenset((STATE_PREPARING, STATE_PRINTING, STATE_PAUSED))
# Терминальные состояния, ДОКАЗАННЫЕ прошивкой. `idle` и `offline` сюда не входят намеренно.
TERMINAL_STATES = frozenset((STATE_COMPLETED, STATE_CANCELLED, STATE_FAILED))
# Единственное терминальное состояние, увеличивающее количество готовых экземпляров.
SUCCESS_STATES = frozenset((STATE_COMPLETED,))


# ── Состояния сессии наблюдаемого физического запуска ──────────────────────────────────────────
SESSION_UNSEEN = "unseen"
SESSION_ACTIVE_UNMATCHED = "observed_active_unmatched"
SESSION_ACTIVE_MATCHED = "observed_active_matched"
SESSION_PAUSED = "paused"
SESSION_TERMINAL_COMPLETED = "terminal_completed"
SESSION_TERMINAL_CANCELLED = "terminal_cancelled"
SESSION_TERMINAL_FAILED = "terminal_failed"
SESSION_TERMINAL_UNKNOWN = "terminal_unknown"
SESSION_ACCOUNTED = "accounted"

SESSION_ACTIVE_STATES = frozenset((SESSION_ACTIVE_UNMATCHED, SESSION_ACTIVE_MATCHED, SESSION_PAUSED))
SESSION_TERMINAL_STATES = frozenset((
    SESSION_TERMINAL_COMPLETED, SESSION_TERMINAL_CANCELLED,
    SESSION_TERMINAL_FAILED, SESSION_TERMINAL_UNKNOWN, SESSION_ACCOUNTED,
))

_TERMINAL_STATE_FOR = {
    STATE_COMPLETED: SESSION_TERMINAL_COMPLETED,
    STATE_CANCELLED: SESSION_TERMINAL_CANCELLED,
    STATE_FAILED: SESSION_TERMINAL_FAILED,
}


# ── Решения движка ────────────────────────────────────────────────────────────────────────────
ACTION_IGNORE = "ignore"                    # наблюдение не меняет состояние (дубль/устаревшее/покой)
ACTION_OPEN = "open_session"                # начался НОВЫЙ физический запуск
ACTION_CONTINUE = "continue_session"        # тот же запуск (прогресс/возобновление/reconnect)
ACTION_PAUSE = "pause_session"              # тот же запуск, встал на паузу
ACTION_TERMINAL = "close_terminal"          # доказанный терминал прошивки
ACTION_CLOSE_UNKNOWN = "close_unknown"      # активность пропала без доказательства исхода

# Причины (стабильные машинные коды; текст для пользователя подбирает интерфейс).
REASON_DUPLICATE_SNAPSHOT = "duplicate_snapshot"
REASON_STALE_SEQUENCE = "stale_sequence"
REASON_STALE_AFTER_TERMINAL = "stale_after_terminal"
REASON_DUPLICATE_TERMINAL = "duplicate_terminal"
REASON_NEW_AFTER_TERMINAL = "new_after_terminal"
REASON_NEW_NATIVE_JOB = "new_native_job"
REASON_NEW_FILE = "new_file"
REASON_FIRST_SEEN = "first_seen"
REASON_SAME_RUN = "same_run"
REASON_RESUMED = "resumed"
REASON_RECONNECTED = "reconnected"
REASON_OFFLINE_KEEP_ACTIVE = "offline_keep_active"
REASON_NO_TERMINAL_EVIDENCE = "no_terminal_evidence"
REASON_QUIET = "quiet"
REASON_UNKNOWN_STATE = "unknown_state"

# Итоги сопоставления с проектом.
MATCH_DISPATCH = "matched_dispatch_correlation"
MATCH_REMOTE_MAPPING = "matched_remote_mapping"
MATCH_UNIQUE_FILENAME = "matched_unique_filename"
MATCH_NONE = "unmatched"
MATCH_AMBIGUOUS = "ambiguous_match"
MATCH_NO_FILENAME = "unmatched_no_filename"


# ── Отделение ОТМЕНЫ от ОШИБКИ ────────────────────────────────────────────────────────────────
# printer_state_policy сводит и отмену, и ошибку в FAILED: для допуска к следующей печати
# разницы нет. Для счётчика готовых деталей разница есть, поэтому здесь — явный список сырых
# строк ОТМЕНЫ по транспортам. Списки намеренно узкие: незнакомая строка не становится отменой,
# она остаётся ошибкой (обе одинаково НЕ увеличивают количество готовых — fail-safe в обе стороны).
_CANCEL_RAW = {
    "bambu": frozenset(),                       # Bambu не различает отмену и сбой в gcode_state
    "klipper": frozenset(("cancelled",)),
    "flashforge": frozenset(("cancel", "cancelled")),
    "creality": frozenset(("cancelled",)),      # 12.10.2026: заводская прошивка Creality (app/creality_native.py)
}

_LIFECYCLE_TO_STATE = {
    _policy.Lifecycle.IDLE: STATE_IDLE,
    _policy.Lifecycle.PREPARING: STATE_PREPARING,
    _policy.Lifecycle.PRINTING: STATE_PRINTING,
    _policy.Lifecycle.PAUSED: STATE_PAUSED,
    _policy.Lifecycle.FINISHED: STATE_COMPLETED,
    _policy.Lifecycle.FAILED: STATE_FAILED,
    _policy.Lifecycle.UNKNOWN: STATE_UNKNOWN,
}

SUPPORTED_ADAPTERS = frozenset(_policy.SUPPORTED_TRANSPORTS)


def normalize_state(adapter_kind, raw_state, connected=True):
    """Сырая строка прошивки -> нормализованное состояние наблюдения.

    connected=False -> `offline` НЕЗАВИСИМО от строки: потеря связи завершением не является.
    Незнакомая строка и незнакомый транспорт -> `unknown` (fail-closed: неизвестное никогда
    не становится ни покоем, ни успехом).
    """
    if not connected:
        return STATE_OFFLINE
    kind = str(adapter_kind or "").strip().lower()
    if isinstance(raw_state, str) and raw_state.strip().upper() == "OFFLINE":
        return STATE_OFFLINE
    life = _policy.normalize_raw(kind, raw_state)
    state = _LIFECYCLE_TO_STATE.get(life, STATE_UNKNOWN)
    if state == STATE_FAILED:
        raw = raw_state.strip().lower() if isinstance(raw_state, str) else ""
        if raw in _CANCEL_RAW.get(kind, frozenset()):
            return STATE_CANCELLED
    return state


# ── Нормализация имени файла ──────────────────────────────────────────────────────────────────
# Порядок значим: длинные составные расширения ПЕРЕД короткими, иначе ".gcode.3mf" срежется
# как ".3mf" и оставит хвост ".gcode".
PRINT_EXTENSIONS = (".gcode.3mf", ".gcode.gz", ".gcode", ".3mf", ".gco", ".gx")

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
# Ярлык плиты без настоящего имени: Bambu при печати с SD часто присылает subtask_name='plate_1'.
_PLATE_LABEL_RE = re.compile(r"^plate[\s_-]?\d+$")


def file_basename(name):
    """Только имя файла, без каталогов. Разделители обоих семейств ОС + защита от traversal.

    Компоненты пути отбрасываются безопасно: '..' и абсолютные пути не могут «протечь» дальше,
    потому что наружу уходит исключительно последний непустой компонент.
    """
    s = str(name or "").strip().strip('"').strip("'")
    if not s:
        return ""
    s = s.replace("\\", "/")
    # Отбрасываем пустые компоненты и '.'/'..' — от них не остаётся ничего осмысленного.
    parts = [p for p in s.split("/") if p not in ("", ".", "..")]
    if not parts:
        return ""
    base = parts[-1]
    # Альтернативный поток NTFS (name:stream) отбрасываем: печатается сам файл, не поток.
    if ":" in base:
        head = base.split(":", 1)[0]
        if head:
            base = head
    return base.strip()


def strip_print_extension(name):
    """Имя без типичного расширения печати. Регистр расширения не важен, само имя не меняется."""
    b = file_basename(name)
    low = b.lower()
    for ext in PRINT_EXTENSIONS:
        if low.endswith(ext) and len(b) > len(ext):
            return b[:-len(ext)]
    return b


def normalize_filename(name):
    """Каноническое имя для СРАВНЕНИЯ: NFC -> basename -> снятие расширения печати -> casefold
    -> удаление всех не буквенно-цифровых символов.

    Даёт устойчивость к трём реальным расхождениям прошивок: другой (или отсутствующий)
    вариант расширения, другой регистр, другие разделители/пробелы в имени. Возвращает ''
    для пустого имени и для служебного ярлыка плиты ('plate_1') — такой «идентификатор»
    не принадлежит ни одному файлу проекта, и сопоставлять по нему нельзя.
    """
    raw = str(name or "")
    if not raw.strip():
        return ""
    nfc = unicodedata.normalize("NFC", raw)
    stem = strip_print_extension(nfc)
    if not stem:
        return ""
    folded = unicodedata.normalize("NFC", stem).casefold()
    if _PLATE_LABEL_RE.match(folded.strip()):
        return ""
    return _NON_ALNUM_RE.sub("", folded)


# ── Наблюдение ────────────────────────────────────────────────────────────────────────────────
class PrinterJobObservation(object):
    """Нормализованный снимок наблюдения за принтером — единственный вход движка.

    Адаптер обязан вернуть ЭТО и ничего больше: он не создаёт запуски, не закрывает их,
    не трогает счётчики проекта и не решает, какому проекту принадлежит печать.
    Не все поля обязаны быть заполнены — протоколы отличаются по объёму сведений.
    """

    __slots__ = (
        "printer_id", "adapter_kind", "observed_at", "connection_epoch",
        "raw_state", "normalized_state", "native_job_id", "native_task_id",
        "filename_raw", "filename_normalized", "remote_path", "progress",
        "elapsed_seconds", "total_seconds", "started_at", "finished_at", "result",
        "plate_index", "source_hint", "sequence", "payload_fingerprint",
        "terminal_evidence", "is_snapshot", "is_stale",
    )

    def __init__(self, printer_id, adapter_kind, observed_at=0.0, connection_epoch=0,
                 raw_state="", normalized_state=STATE_UNKNOWN, native_job_id="",
                 native_task_id="", filename_raw="", remote_path="", progress=None,
                 elapsed_seconds=None, total_seconds=None, started_at=None, finished_at=None,
                 result="", plate_index=None, source_hint="", sequence=0,
                 is_snapshot=False, is_stale=False):
        self.printer_id = str(printer_id or "")
        self.adapter_kind = str(adapter_kind or "").strip().lower()
        self.observed_at = float(observed_at or 0.0)
        self.connection_epoch = int(connection_epoch or 0)
        self.raw_state = "" if raw_state is None else str(raw_state)
        self.normalized_state = normalized_state if normalized_state in NORMALIZED_STATES else STATE_UNKNOWN
        self.native_job_id = str(native_job_id or "").strip()
        self.native_task_id = str(native_task_id or "").strip()
        self.filename_raw = str(filename_raw or "")
        self.filename_normalized = normalize_filename(self.filename_raw)
        self.remote_path = str(remote_path or "")
        self.progress = _clamp_progress(progress)
        self.elapsed_seconds = _non_negative_int(elapsed_seconds)
        self.total_seconds = _non_negative_int(total_seconds)
        self.started_at = started_at
        self.finished_at = finished_at
        self.result = str(result or "")
        self.plate_index = _plate_index(plate_index)
        self.source_hint = str(source_hint or "")
        self.sequence = int(sequence or 0)
        self.is_snapshot = bool(is_snapshot)
        self.is_stale = bool(is_stale)
        # Доказательство исхода: ТОЛЬКО явное терминальное состояние прошивки. Ни исчезновение
        # задания, ни переход в покой, ни потеря связи доказательством не являются.
        self.terminal_evidence = self.normalized_state in TERMINAL_STATES
        self.payload_fingerprint = self._fingerprint()

    def _fingerprint(self):
        """Отпечаток значимых полей. Одинаковый отпечаток = наблюдение ничего не добавляет.

        В отпечаток НЕ входят ни время наблюдения, ни номер в последовательности: иначе
        каждый повторный опрос выглядел бы новым и защита от дублей не работала бы.
        """
        parts = [
            self.printer_id, self.adapter_kind, self.normalized_state, self.raw_state,
            self.native_job_id, self.native_task_id, self.filename_normalized,
            "" if self.progress is None else str(self.progress),
            "" if self.elapsed_seconds is None else str(self.elapsed_seconds),
            "" if self.plate_index is None else str(self.plate_index),
        ]
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]

    @property
    def is_active(self):
        return self.normalized_state in ACTIVE_STATES

    @property
    def is_terminal(self):
        return self.normalized_state in TERMINAL_STATES

    @property
    def is_success(self):
        return self.normalized_state in SUCCESS_STATES

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self):   # только безопасные поля: имя файла в repr не попадает
        return "<PrinterJobObservation %s/%s %s seq=%s>" % (
            self.printer_id, self.adapter_kind, self.normalized_state, self.sequence)


def _clamp_progress(value):
    """Прогресс 0..100 или None. Мусор и выход за границы не роняют разбор."""
    if value is None:
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    if p != p:            # NaN
        return None
    if 0.0 < p <= 1.0 and not float(p).is_integer():
        p = p * 100.0     # доля 0..1 (virtual_sdcard.progress, printProgress)
    return int(max(0.0, min(100.0, p)))


def _non_negative_int(value):
    if value is None:
        return None
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _plate_index(value):
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def observe(printer_id, adapter_kind, raw_state, filename_raw="", connected=True,
            observed_at=0.0, connection_epoch=0, sequence=0, native_job_id="",
            native_task_id="", remote_path="", progress=None, elapsed_seconds=None,
            total_seconds=None, plate_index=None, source_hint="", is_snapshot=False,
            state_override=None):
    """Собрать `PrinterJobObservation` из уже разобранных адаптером полей.

    Единственная точка, где сырое состояние превращается в нормализованное. Ошибок не бросает:
    любой мусор во входе даёт `unknown`/None, но не исключение — телеметрия не должна ронять
    опрос принтера.

    state_override — исход, известный НЕ из протокола, а из действия оператора (нажата «Стоп»).
    Прошивка после отмены может ещё минуты рапортовать «печатает», но исход уже определён.
    Это НЕ лазейка для протокольной логики: успехом (`completed`) переопределить нельзя —
    успех доказывает только сама прошивка.
    """
    state = normalize_state(adapter_kind, raw_state, connected=connected)
    if state_override in NORMALIZED_STATES and state_override not in SUCCESS_STATES:
        state = state_override
    return PrinterJobObservation(
        printer_id=printer_id, adapter_kind=adapter_kind, observed_at=observed_at,
        connection_epoch=connection_epoch, raw_state=raw_state, normalized_state=state,
        native_job_id=native_job_id, native_task_id=native_task_id,
        filename_raw=filename_raw, remote_path=remote_path, progress=progress,
        elapsed_seconds=elapsed_seconds, total_seconds=total_seconds,
        plate_index=plate_index, source_hint=source_hint, sequence=sequence,
        is_snapshot=is_snapshot,
    )


# ── Решение движка ────────────────────────────────────────────────────────────────────────────
class Decision(object):
    """Что сделать с сессией по итогам одного наблюдения. Чистое значение, без побочных эффектов."""

    __slots__ = ("action", "reason", "session_state", "terminal_state", "counts_completion")

    def __init__(self, action, reason, session_state=None, terminal_state="", counts_completion=False):
        self.action = action
        self.reason = reason
        self.session_state = session_state
        self.terminal_state = terminal_state
        self.counts_completion = bool(counts_completion)

    def __repr__(self):
        return "<Decision %s (%s)>" % (self.action, self.reason)

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


def _session_get(session, key, default=None):
    if session is None:
        return default
    if isinstance(session, dict):
        return session.get(key, default)
    return getattr(session, key, default)


def decide(session, obs):
    """Ядро: (состояние сессии | None, наблюдение) -> `Decision`. Чистая функция.

    Сессия — снимок ПОСЛЕДНЕГО известного физического запуска этого принтера (из БД или из
    памяти), словарь с полями: lifecycle_state, filename_normalized, native_job_id,
    connection_epoch, sequence, last_fingerprint, completion_accounted.

    Ключевые инварианты, ради которых функция существует:
      * потеря связи НЕ завершает запуск;
      * покой без доказанного терминала НЕ считается успехом;
      * пауза и возобновление НЕ создают новый запуск;
      * повторный терминал НЕ учитывается второй раз;
      * повторная печать того же файла ПОСЛЕ терминала — это НОВЫЙ физический запуск.
    """
    state = obs.normalized_state
    prev_state = _session_get(session, "lifecycle_state") or SESSION_UNSEEN
    prev_active = prev_state in SESSION_ACTIVE_STATES
    prev_terminal = prev_state in SESSION_TERMINAL_STATES

    # 1. Устаревшее/переупорядоченное наблюдение. Проверяем ДО всего остального: пакет из
    #    прошлого не должен ни открывать, ни закрывать, ни воскрешать запуск.
    if session is not None and _is_stale(session, obs):
        return Decision(ACTION_IGNORE, REASON_STALE_SEQUENCE, prev_state)

    # 2. Терминальный замок: после доказанного исхода «печатается» принимается за НОВЫЙ запуск
    #    только при доказательстве старта. Без него это запоздавший или retained пакет прошлой
    #    печати, и принять его нельзя — см. _has_start_evidence.
    if prev_terminal and state in ACTIVE_STATES:
        if not _has_start_evidence(session, obs):
            return Decision(ACTION_IGNORE, REASON_STALE_AFTER_TERMINAL, prev_state)

    # 3. Повторный терминал того же запуска — учёт уже сделан (или сознательно не сделан).
    if prev_terminal and state in TERMINAL_STATES:
        return Decision(ACTION_IGNORE, REASON_DUPLICATE_TERMINAL, prev_state)

    # 4. Потеря связи: активный запуск сохраняем, не завершаем и не пересоздаём.
    if state == STATE_OFFLINE:
        if prev_active:
            return Decision(ACTION_IGNORE, REASON_OFFLINE_KEEP_ACTIVE, prev_state)
        return Decision(ACTION_IGNORE, REASON_QUIET, prev_state)

    # 5. Активное состояние.
    if state in ACTIVE_STATES:
        if not prev_active:
            # Из покоя/терминала/небытия в работу — начался новый физический запуск.
            reason = REASON_NEW_AFTER_TERMINAL if prev_terminal else (
                REASON_FIRST_SEEN if session is None else REASON_NEW_FILE)
            return Decision(ACTION_OPEN, reason, SESSION_ACTIVE_UNMATCHED)
        # Сессия активна — тот же это запуск или уже другой?
        new_run, why = _is_new_run(session, obs)
        if new_run:
            return Decision(ACTION_OPEN, why, SESSION_ACTIVE_UNMATCHED)
        if state == STATE_PAUSED:
            return Decision(ACTION_PAUSE, REASON_SAME_RUN, SESSION_PAUSED)
        if prev_state == SESSION_PAUSED:
            return Decision(ACTION_CONTINUE, REASON_RESUMED, _matched_or_unmatched(session))
        if _session_get(session, "connection_epoch") not in (None, obs.connection_epoch):
            return Decision(ACTION_CONTINUE, REASON_RECONNECTED, _matched_or_unmatched(session))
        if _session_get(session, "last_fingerprint") == obs.payload_fingerprint:
            return Decision(ACTION_IGNORE, REASON_DUPLICATE_SNAPSHOT, prev_state)
        return Decision(ACTION_CONTINUE, REASON_SAME_RUN, _matched_or_unmatched(session))

    # 6. Доказанный терминал прошивки.
    if state in TERMINAL_STATES:
        if not prev_active:
            # Терминал без известного активного запуска (например, принтер показывает FINISH
            # прошлой печати при первом подключении). Открывать задним числом нечего.
            return Decision(ACTION_IGNORE, REASON_NO_TERMINAL_EVIDENCE, prev_state)
        return Decision(ACTION_TERMINAL, REASON_SAME_RUN, _TERMINAL_STATE_FOR[state],
                        terminal_state=state, counts_completion=(state in SUCCESS_STATES))

    # 7. Покой. Доказательством успеха НЕ является никогда — активная сессия закрывается как
    #    «исход неизвестен», количество готовых деталей не меняется.
    if state == STATE_IDLE:
        if prev_active:
            return Decision(ACTION_CLOSE_UNKNOWN, REASON_NO_TERMINAL_EVIDENCE,
                            SESSION_TERMINAL_UNKNOWN, terminal_state=STATE_IDLE)
        return Decision(ACTION_IGNORE, REASON_QUIET, prev_state)

    # 8. Неизвестное состояние: ничего не предпринимаем — незнакомая строка прошивки не повод
    #    ни закрыть работающую печать, ни объявить её успешной.
    return Decision(ACTION_IGNORE, REASON_UNKNOWN_STATE, prev_state)


def _matched_or_unmatched(session):
    """Сохранить уже достигнутую связь с проектом при продолжении того же запуска."""
    return (SESSION_ACTIVE_MATCHED
            if _session_get(session, "lifecycle_state") == SESSION_ACTIVE_MATCHED
            or _session_get(session, "matched_file_id")
            else SESSION_ACTIVE_UNMATCHED)


def _is_stale(session, obs):
    """Наблюдение из прошлого: меньший номер в той же эпохе связи.

    Номера сравниваем ТОЛЬКО внутри одной эпохи: после переподключения счётчик начинается
    заново, и «меньший номер» там означает новое наблюдение, а не старое.
    """
    prev_seq = _session_get(session, "sequence")
    prev_epoch = _session_get(session, "connection_epoch")
    if prev_seq is None or not obs.sequence:
        return False
    if prev_epoch is not None and prev_epoch != obs.connection_epoch:
        return False
    return obs.sequence < int(prev_seq or 0)


def _same_identity(session, obs):
    """Совпадает ли личность задания: сначала native id, иначе нормализованное имя файла."""
    prev_native = (_session_get(session, "native_job_id") or "").strip()
    if prev_native and obs.native_job_id:
        return prev_native == obs.native_job_id
    prev_name = _session_get(session, "filename_normalized") or ""
    return bool(prev_name) and prev_name == obs.filename_normalized


# Порог «печать только началась». Ниже него активное состояние после терминала считается
# доказательством НОВОГО запуска, выше — запоздавшим пакетом прошлой печати.
NEW_RUN_MAX_PROGRESS = 50
NEW_RUN_MAX_ELAPSED_S = 300


def _has_start_evidence(session, obs):
    """Доказательство, что после терминала началась ИМЕННО НОВАЯ печать, а не пришёл запоздавший
    или retained пакет прошлой.

    ПОЧЕМУ БЕЗ ДОКАЗАТЕЛЬСТВА НЕЛЬЗЯ. У Bambu состояние FINISH «липкое»: оно держится до
    следующей печати. Если принять любой поздний «печатается» за новый запуск, то следующий же
    отчёт FINISH закрыл бы этот запуск как успешный и засчитал бы деталь ВТОРОЙ раз. Поэтому
    здесь fail-closed: нет доказательства старта — нового запуска нет.

    Доказательством считается любое из:
      * прошивка назвала ДРУГОЙ идентификатор задания (самый сильный признак);
      * печатается ДРУГОЙ файл;
      * принтер именно ГОТОВИТСЯ к печати (preparing) — так начинают Bambu и FlashForge;
      * прогресс известен и мал — печать пошла сначала (все три поддерживаемых протокола);
      * время печати известно и мало.

    ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ. Ни один из поддерживаемых протоколов не сообщает идентификатор
    задания, поэтому для протокола, который не даёт ни прогресса, ни времени, повтор того же
    файла сразу после завершения останется незамеченным. Это осознанный выбор в пользу
    недосчёта: лишняя деталь в плане искажает производство сильнее, чем недостающая.
    """
    prev_native = (_session_get(session, "native_job_id") or "").strip()
    if obs.native_job_id and prev_native and obs.native_job_id != prev_native:
        return True
    prev_name = _session_get(session, "filename_normalized") or ""
    if obs.filename_normalized and prev_name and obs.filename_normalized != prev_name:
        return True
    if obs.normalized_state == STATE_PREPARING:
        return True
    if obs.progress is not None and obs.progress <= NEW_RUN_MAX_PROGRESS:
        return True
    if obs.elapsed_seconds is not None and obs.elapsed_seconds <= NEW_RUN_MAX_ELAPSED_S:
        return True
    return False


def _is_new_run(session, obs):
    """Тот же физический запуск или уже другой? -> (bool, причина).

    Иерархия ровно та же, что и у идентичности запуска: сначала СИЛЬНЫЙ признак прошивки
    (native job id), затем имя файла. Имя файла НИКОГДА не является единственным признаком
    самого по себе: если прошивка дала native id, решает он.
    """
    prev_native = (_session_get(session, "native_job_id") or "").strip()
    if prev_native and obs.native_job_id:
        if prev_native != obs.native_job_id:
            return True, REASON_NEW_NATIVE_JOB
        return False, REASON_SAME_RUN          # тот же native id -> тот же запуск, имя не важно
    prev_name = _session_get(session, "filename_normalized") or ""
    if prev_name and obs.filename_normalized and prev_name != obs.filename_normalized:
        return True, REASON_NEW_FILE
    return False, REASON_SAME_RUN


# ── Сопоставление с файлом/деталью проекта ────────────────────────────────────────────────────
class MatchResult(object):
    """Итог сопоставления. Fail-closed: при любой неоднозначности проект НЕ меняется."""

    __slots__ = ("state", "project_id", "file_id", "reason", "candidates")

    def __init__(self, state, project_id=None, file_id=None, reason="", candidates=0):
        self.state = state
        self.project_id = project_id
        self.file_id = file_id
        self.reason = reason or state
        self.candidates = int(candidates or 0)

    @property
    def matched(self):
        return self.state in (MATCH_DISPATCH, MATCH_REMOTE_MAPPING, MATCH_UNIQUE_FILENAME)

    @property
    def ambiguous(self):
        return self.state == MATCH_AMBIGUOUS

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self):
        return "<MatchResult %s cands=%s>" % (self.state, self.candidates)


def match_observation(obs, candidates=(), remote_sends=(), dispatch_correlation=None):
    """Единый сопоставитель. Порядок — от самого сильного признака к слабому.

      1. Прямая корреляция с запуском Farm Manager (внутренний идентификатор отправки).
      2. Точная запись о ФАКТИЧЕСКОЙ отправке этого файла НА ЭТОТ принтер.
      3. Точное совпадение нормализованного имени — только если кандидат ровно один.
      4. Иначе — не сопоставлено либо неоднозначно; счётчики проекта не меняются.

    `candidates` — записи файлов проектов: {file_id, project_id, filename, is_deleted,
    is_archived, has_parts}. Отбор кандидатов делает вызывающий (он владеет БД); здесь —
    только правила. Нечёткого сопоставления нет ни на одном уровне: ни «содержит», ни
    «начинается с», ни похожесть строк, ни совпадение одного лишь расширения.
    """
    # Уровень 1 — доказанная корреляция с нашей же отправкой.
    if dispatch_correlation:
        fid = dispatch_correlation.get("file_id")
        pid = dispatch_correlation.get("project_id")
        if fid and pid:
            return MatchResult(MATCH_DISPATCH, pid, fid, MATCH_DISPATCH, 1)

    if not obs.filename_normalized:
        # Без имени файла привязывать не к чему. Догадка по «единственному живому проекту»
        # запрещена: именно так чужая печать засчитывала чужую деталь.
        return MatchResult(MATCH_NONE, reason=MATCH_NO_FILENAME)

    # Уровень 2 — точная запись об отправке ИМЕННО на этот принтер.
    sends = [s for s in (remote_sends or [])
             if str(s.get("printer_id") or "") == obs.printer_id
             and normalize_filename(s.get("remote_filename") or s.get("filename") or "") == obs.filename_normalized
             and s.get("file_id") and s.get("project_id")]
    if sends:
        uniq = {(s["project_id"], s["file_id"]) for s in sends}
        if len(uniq) == 1:
            s = sends[0]
            return MatchResult(MATCH_REMOTE_MAPPING, s["project_id"], s["file_id"],
                               MATCH_REMOTE_MAPPING, len(sends))
        # Одно и то же имя отправлялось на этот принтер из РАЗНЫХ файлов — не гадаем.
        return MatchResult(MATCH_AMBIGUOUS, reason=MATCH_AMBIGUOUS, candidates=len(uniq))

    # Уровень 3 — точное имя среди живых записей проекта.
    live = []
    for c in (candidates or []):
        if _truthy(c.get("is_deleted")) or _truthy(c.get("is_archived")):
            continue          # удалённый/архивный проект кандидатом не является
        if not c.get("file_id") or not c.get("project_id"):
            continue
        if not _truthy(c.get("has_parts")):
            continue          # файл без деталей засчитывать нечем
        if normalize_filename(c.get("filename") or "") != obs.filename_normalized:
            continue
        live.append(c)
    uniq_files = {(c["project_id"], c["file_id"]) for c in live}
    if len(uniq_files) == 1:
        c = live[0]
        return MatchResult(MATCH_UNIQUE_FILENAME, c["project_id"], c["file_id"],
                           MATCH_UNIQUE_FILENAME, 1)
    if len(uniq_files) > 1:
        # Одинаковое имя в нескольких проектах/файлах. НЕ выбираем ни «последний», ни первый
        # результат SQL, ни по имени проекта, ни по пути папки: неверная привязка испортила бы
        # план чужого проекта, а не привязать — всего лишь недосчитать.
        return MatchResult(MATCH_AMBIGUOUS, reason=MATCH_AMBIGUOUS, candidates=len(uniq_files))
    return MatchResult(MATCH_NONE, reason=MATCH_NONE)


def _truthy(v):
    if isinstance(v, str):
        return v.strip().lower() not in ("", "0", "false", "no")
    return bool(v)


# ── Восстановление после перезапуска ──────────────────────────────────────────────────────────
RECOVERY_REUSE = "recovery_reused_session"
RECOVERY_NEW_RUN = "recovery_new_run"
RECOVERY_KEEP_OPEN = "recovery_keep_open"
RECOVERY_ACCOUNT_PENDING = "recovery_account_pending"
RECOVERY_CLOSE_UNKNOWN = "recovery_close_unknown"


def plan_recovery(session, obs):
    """Что делать с НЕЗАКРЫТОЙ сессией при первом наблюдении после перезапуска. Чистая функция.

    Сценарии из задачи:
      A. Печать продолжается и личность совпала -> тот же запуск, второй не создаём.
      B. Терминал уже доказан, но учёт не выполнен -> учесть РОВНО один раз.
      B'. Принтер в покое, доказательства исхода нет -> успех НЕ выдумываем.
      C. Учёт уже выполнен -> повторно не считаем.
      D. Пока backend был выключен, начался новый запуск -> новый запуск только при
         ДОКАЗАТЕЛЬСТВЕ (иной native id либо явный терминал прошлого + активность).
    """
    if session is None:
        return RECOVERY_NEW_RUN if obs.is_active else RECOVERY_KEEP_OPEN
    if _session_get(session, "completion_accounted"):
        return RECOVERY_KEEP_OPEN
    prev_state = _session_get(session, "lifecycle_state") or SESSION_UNSEEN
    if prev_state == SESSION_TERMINAL_COMPLETED:
        # Доказательство исхода было получено ДО перезапуска — учитываем один раз.
        return RECOVERY_ACCOUNT_PENDING
    if prev_state in SESSION_TERMINAL_STATES:
        return RECOVERY_KEEP_OPEN
    if obs.is_active:
        if _same_identity(session, obs):
            return RECOVERY_REUSE
        return RECOVERY_NEW_RUN
    if obs.is_success:
        return RECOVERY_ACCOUNT_PENDING
    if obs.is_terminal:
        return RECOVERY_CLOSE_UNKNOWN if obs.normalized_state != STATE_COMPLETED else RECOVERY_ACCOUNT_PENDING
    # Принтер в покое/offline/unknown: доказательства успеха нет — не угадываем.
    return RECOVERY_CLOSE_UNKNOWN if obs.normalized_state == STATE_IDLE else RECOVERY_KEEP_OPEN


# ── Безопасное журналирование ─────────────────────────────────────────────────────────────────
SAFE_EVENTS = (
    "job_observed", "job_session_created", "job_matched", "job_unmatched", "job_ambiguous",
    "job_resumed", "job_completed", "job_cancelled", "job_failed", "completion_accounted",
    "duplicate_terminal_ignored", "stale_observation_ignored", "recovery_reused_session",
)


def short_id(value, length=8):
    """Укороченный необратимый идентификатор для журнала: сам идентификатор наружу не уходит."""
    s = str(value or "")
    if not s:
        return ""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:max(4, int(length))]


def safe_log_fields(obs, decision=None, match=None, observed_run_id=""):
    """Поля события для журнала. Секретов и пользовательских данных здесь нет НИКОГДА:
    ни адреса принтера, ни серийного номера, ни кода доступа, ни пароля, ни сырого отчёта,
    ни g-code, ни имени файла — только укороченные идентификаторы и машинные коды."""
    out = {
        "printer": short_id(obs.printer_id),
        "adapter": obs.adapter_kind,
        "state": obs.normalized_state,
        "epoch": obs.connection_epoch,
        "seq": obs.sequence,
        "obs": obs.payload_fingerprint[:12],
        "file": short_id(obs.filename_normalized) if obs.filename_normalized else "",
    }
    if observed_run_id:
        out["run"] = short_id(observed_run_id)
    if decision is not None:
        out["action"] = decision.action
        out["reason"] = decision.reason
    if match is not None:
        out["match"] = match.state
        out["cands"] = match.candidates
    return out
