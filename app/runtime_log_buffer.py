# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — журнал в памяти для встроенного просмотра (Alpha 2.813).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, БД, сеть и принтерные
подсистемы. Ничего не открывает и не пишет на диск: это кольцевой буфер в памяти плюс
централизованное вычищение секретов.

ЗАЧЕМ. До 2.813 единственным «просмотрщиком логов» для пользователя было окно CMD, к которому
привязан сам процесс сервера: крестик у этого окна завершал Farm Manager вместе с печатями.
Теперь журнал показывается внутри программы, а данные для него готовит этот модуль.

ДВА ПРАВИЛА, РАДИ КОТОРЫХ ОН ОТДЕЛЬНЫЙ.
  1. Один источник. Буфер наполняется из ТОЙ ЖЕ точки логирования, что и файл журнала, поэтому
     во встроенном журнале не может «не хватать половины событий».
  2. Секреты вычищаются ЗДЕСЬ, до выдачи наружу. Просмотр, копирование и сохранение в файл
     работают с одним и тем же безопасным текстом — забыть про один из путей нельзя.

ЧТО СЮДА НЕ ПОПАДАЕТ НИКОГДА: объекты исключений, сырые пакеты протоколов, G-code, пароли,
токены, коды доступа принтеров, cookies и абсолютные пути к данным программы.
"""

import re
import threading
import time

# Сколько записей держим в памяти. Хватает, чтобы увидеть картину сбоя целиком, и при этом
# память ограничена жёстко: буфер не растёт вместе с временем работы фермы.
DEFAULT_CAPACITY = 2000

LEVELS = ("debug", "info", "warning", "error")
_LEVEL_ORDER = {name: i for i, name in enumerate(LEVELS)}

# Приведение имён уровней к нашим четырём (logging даёт свои названия).
_LEVEL_ALIASES = {
    "debug": "debug", "info": "info", "warn": "warning", "warning": "warning",
    "error": "error", "critical": "error", "fatal": "error", "exception": "error",
    "notset": "debug",
}

REDACTED = "[REDACTED]"

# ── Правила вычищения секретов ────────────────────────────────────────────────────────────────
# Порядок важен: сначала самые конкретные (пары «ключ: значение»), затем общие формы.
# Каждое правило заменяет ТОЛЬКО значение, оставляя человеку понятным, что именно скрыто.
_RULES = (
    # Заголовки: значение съедается ДО КОНЦА СТРОКИ. Одного «слова» мало — у Authorization это
    # схема («Bearer»), а сам токен идёт следующим словом; у Cookie значений вообще несколько.
    (re.compile(r"(?i)\b(authorization)\s*[:=][^\r\n]+"), r"\1: " + REDACTED),
    (re.compile(r"(?i)\b(cookie|set-cookie)\s*[:=][^\r\n]+"), r"\1: " + REDACTED),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"), "Bearer " + REDACTED),
    (re.compile(r"(?i)\b(session|sid|session_id|csrf|xsrf)\s*[:=]\s*\S+"), r"\1=" + REDACTED),
    (re.compile(r"(?i)\b(token|access_token|refresh_token|recovery_token|api_key|apikey|secret)"
                r"\s*[:=]\s*\S+"), r"\1=" + REDACTED),
    # Учётные данные и коды доступа принтеров
    (re.compile(r"(?i)\b(password|passwd|pwd|pass)\s*[:=]\s*\S+"), r"\1=" + REDACTED),
    (re.compile(r"(?i)\b(access[_ -]?code|lan[_ -]?code|pin)\s*[:=]\s*\S+"), r"\1=" + REDACTED),
    (re.compile(r"(?i)\b(serial|sn)\s*[:=]\s*[A-Za-z0-9]{6,}"), r"\1=" + REDACTED),
    # Учётные данные в адресе (scheme://user:pass@host)
    (re.compile(r"://[^\s/:@]+:[^\s/@]+@"), "://" + REDACTED + "@"),
    # Секреты в query/fragment
    (re.compile(r"(?i)([?&#](?:token|code|key|secret|password|grant)=)[^\s&#]+"), r"\1" + REDACTED),
)

# Абсолютные пути Windows и POSIX: наружу не отдаём вовсе — пользователю они ничего не объясняют,
# а расположение рабочих данных выдают.
_WIN_PATH = re.compile(r"\b[A-Za-z]:\\[^\s\"'<>|]+")
_UNC_PATH = re.compile(r"\\\\[^\s\"'<>|]+")
_POSIX_PATH = re.compile(r"(?<![\w.])/(?:home|Users|var|etc|opt)/[^\s\"'<>|]+")

# Признаки G-code: даже одна строка команды в журнале — это уже содержимое печати.
_GCODE = re.compile(r"(?im)^\s*(?:;.*|(?:G0|G1|G2|G3|G28|G29|G90|G91|G92|M104|M105|M106|M109|"
                    r"M140|M190|M204|M220|M221|T\d)\b.*)$")

_MAX_MESSAGE = 2000       # длинная строка в журнале — почти всегда сырой дамп; обрезаем безопасно


def redact(text):
    """Единственная точка вычищения секретов. -> безопасная строка.

    Применяется ДО попадания записи в буфер, поэтому просмотр, копирование и сохранение в файл
    физически не могут получить неочищенный текст."""
    s = "" if text is None else str(text)
    if not s:
        return ""
    for rx, repl in _RULES:
        s = rx.sub(repl, s)
    s = _GCODE.sub(REDACTED, s)
    s = _WIN_PATH.sub(REDACTED, s)
    s = _UNC_PATH.sub(REDACTED, s)
    s = _POSIX_PATH.sub(REDACTED, s)
    if len(s) > _MAX_MESSAGE:
        s = s[:_MAX_MESSAGE] + "… " + REDACTED
    return s


def normalize_level(level):
    """Имя уровня -> одно из наших четырёх."""
    return _LEVEL_ALIASES.get(str(level or "").strip().lower(), "info")


_SOURCE_RE = re.compile(r"^\s*\[([A-Za-z0-9_.\- ]{1,24})\]")


def extract_source(message):
    """Категория записи. В этом проекте сообщения начинаются с метки вида «[PORT] …» —
    её и показываем отдельной колонкой. Нет метки — источник «general»."""
    m = _SOURCE_RE.match(str(message or ""))
    if not m:
        return "general"
    return m.group(1).strip().lower()[:24] or "general"


class LogBuffer(object):
    """Потокобезопасный кольцевой буфер записей журнала.

    Пишут в него потоки воркеров принтеров и обработчики HTTP одновременно, поэтому все операции
    под одним замком. Номер записи (seq) монотонный и НЕ переиспользуется: просмотрщик просит
    «всё, что новее seq», и не может получить дубли или пропуски."""

    def __init__(self, capacity=DEFAULT_CAPACITY, clock=time.time):
        self._cap = max(1, int(capacity))
        self._clock = clock
        self._lock = threading.Lock()
        self._items = []
        self._seq = 0
        self._dropped = 0
        self._started_at = float(clock())

    # -- запись
    def append(self, level, message, source=None, code=None, ts=None):
        """Добавить запись. Текст вычищается ЗДЕСЬ. -> номер записи."""
        safe_msg = redact(message)
        lvl = normalize_level(level)
        src = str(source).strip().lower()[:24] if source else extract_source(message)
        rec_ts = float(ts if ts is not None else self._clock())
        with self._lock:
            self._seq += 1
            rec = {"seq": self._seq, "ts": rec_ts, "level": lvl,
                   "source": src or "general", "message": safe_msg}
            if code:
                rec["code"] = str(code)[:40]
            self._items.append(rec)
            if len(self._items) > self._cap:
                # Вытесняем самые старые: буфер ограничен, но пользователь должен ЗНАТЬ,
                # что часть истории уже не показывается (dropped).
                extra = len(self._items) - self._cap
                del self._items[:extra]
                self._dropped += extra
            return self._seq

    # -- чтение
    def snapshot(self, after_seq=0, limit=250, min_level=None, source=None):
        """Записи новее after_seq. -> (список, latest_seq, has_more).

        Ограничение количества обязательно: один ответ не должен вырастать вместе с буфером."""
        try:
            after = int(after_seq or 0)
        except (TypeError, ValueError):
            after = 0
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            lim = 250
        lim = max(1, min(lim, 1000))
        floor = _LEVEL_ORDER.get(normalize_level(min_level), 0) if min_level else 0
        want_src = str(source).strip().lower()[:24] if source else ""
        with self._lock:
            latest = self._seq
            picked = []
            for rec in self._items:
                if rec["seq"] <= after:
                    continue
                if _LEVEL_ORDER.get(rec["level"], 0) < floor:
                    continue
                if want_src and rec["source"] != want_src:
                    continue
                picked.append(dict(rec))
                if len(picked) > lim:
                    break
        has_more = len(picked) > lim
        return picked[:lim], latest, has_more

    def stats(self):
        with self._lock:
            return {"count": len(self._items), "capacity": self._cap,
                    "latest_seq": self._seq, "dropped_count": self._dropped,
                    "started_at": self._started_at}

    def clear(self):
        """Очистить буфер в памяти. Файл журнала при этом НЕ трогается."""
        with self._lock:
            self._items = []
