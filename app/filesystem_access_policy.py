# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — политика клиентских файловых путей (Alpha 2.789).

ЧИСТЫЙ модуль: только стандартная библиотека, и притом ТОЛЬКО строковые операции
`os.path`. НЕ импортирует server.py, веб-фреймворк, СУБД и принтерные подсистемы, не
обращается к сети, НЕ ХОДИТ В ФАЙЛОВУЮ СИСТЕМУ и ничего не пишет в журнал — чтобы его
можно было проверять офлайн-тестами без запуска приложения и без рабочих данных.
Разрешение символических ссылок (realpath) выполняет ВЫЗЫВАЮЩИЙ и передаёт сюда уже
разрешённые пути: так единственное обращение к диску остаётся на стороне обработчика,
а решение остаётся детерминированным и воспроизводимым в тесте.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ — важно не перепутать. Это НЕ модель «разрешённых корней». Встроенный
файловый менеджер по замыслу даёт обзор всего диска (см. FILE_MANAGER_ENABLED в server.py),
а модели привязываются к заданиям ПО АБСОЛЮТНОМУ ПУТИ БЕЗ КОПИРОВАНИЯ. Ограничивать МЕСТО
обзора эта политика не пытается: такое ограничение сломало бы и выбор моделей из
произвольной папки, и уже привязанные файлы. Она решает две другие задачи:

  1) ФОРМА пути. Отсекаются написания, которые интерфейс никогда не присылает, а
     злонамеренный клиент прислать может: UNC-доступ к чужому компьютеру, extended- и
     device-пространства имён Windows, альтернативные потоки NTFS, drive-relative
     написание, зарезервированные имена устройств и управляющие символы. Это не
     «чёрный список траверсала», а сужение до обычного локального пути.

  2) ПРИНАДЛЕЖНОСТЬ служебному каталогу — там, где каталог задаёт СЕРВЕР (приём файлов
     от слайсера, кэш превью, папки данных). Сравнение идёт ПОКОМПОНЕНТНО через
     commonpath, а не `startswith`: иначе каталог-сосед с общим префиксом
     (``...\\Farm`` и ``...\\Farm-evil``) прошёл бы проверку.

ГРАНИЦЫ ЧЕСТНОСТИ. Проверка основана на путях, а не на дескрипторах, поэтому она не
устраняет гонку «проверили — подменили» (TOCTOU) полностью: между решением и операцией
каталог теоретически можно подменить. Вызывающий обязан перепроверять границу
непосредственно перед побочным эффектом; абсолютной handle-based защиты здесь нет и она
не заявляется.
"""

import os
import re

# ── Коды причин. Наружу клиенту они не отдаются: у обработчиков свой прежний контракт
#    ответа. Коды нужны тестам и журналу решений, поэтому они стабильны и безопасны —
#    ни один не содержит самого пути.
REASON_OK = ""
REASON_EMPTY = "path_empty"
REASON_NOT_STRING = "path_not_string"
REASON_TOO_LONG = "path_too_long"
REASON_CONTROL_CHARS = "path_control_chars"
REASON_ADS = "alternate_data_stream"
REASON_DRIVE_RELATIVE = "drive_relative_not_allowed"
REASON_UNC = "unc_not_allowed"
REASON_EXTENDED = "extended_path_not_allowed"
REASON_DEVICE = "device_path_not_allowed"
REASON_RESERVED_NAME = "reserved_name"
REASON_TRAILING_DOT_SPACE = "trailing_dot_or_space"
REASON_NOT_ABSOLUTE = "path_not_absolute"
REASON_OUTSIDE_BASE = "path_outside_base"

# Потолок длины. Проверяется ДО любых разборов, чтобы гигантское значение не заставляло
# сервер нормализовать мегабайты. Длиннее любого осмысленного пути Windows.
MAX_PATH_LEN = 4096

# Управляющие символы: NUL и весь блок C0. В пути они не встречаются никогда, а в
# отдельных API обрезают строку по NUL.
_CONTROL_RE = re.compile(r"[\x00-\x1f]")

# Имена устройств DOS. Открытие такого имени обращается к устройству, а не к файлу.
_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM%d" % i for i in range(1, 10)]
    + ["LPT%d" % i for i in range(1, 10)]
)

# Обычный локальный путь с буквой диска: X:\... или X:/...
_LOCAL_ABS_RE = re.compile(r"\A[A-Za-z]:[\\/]")
# Drive-relative: X:folder — «относительно ТЕКУЩЕГО каталога диска X», а не корня.
_DRIVE_RELATIVE_RE = re.compile(r"\A[A-Za-z]:(?![\\/])")


class PathDecision(object):
    """Неизменяемый результат проверки. allow -> путь можно передавать дальше."""

    __slots__ = ("allow", "reason", "path")

    def __init__(self, allow, reason=REASON_OK, path=""):
        self.allow = bool(allow)
        self.reason = reason
        self.path = path

    def __eq__(self, other):
        return (isinstance(other, PathDecision) and self.allow == other.allow
                and self.reason == other.reason and self.path == other.path)

    def __repr__(self):   # только для отладки теста; сам путь наружу не уходит
        return "PathDecision(allow=%r, reason=%r)" % (self.allow, self.reason)


def _deny(reason):
    return PathDecision(False, reason, "")


def _components(path):
    """Компоненты пути без разделителей и без пустых элементов."""
    return [c for c in re.split(r"[\\/]+", path) if c not in ("", ".")]


def has_reserved_name(path):
    """Есть ли среди компонентов зарезервированное имя устройства DOS.

    Сравнение без учёта регистра и по части ДО первой точки: 'con.txt' — тоже устройство.
    """
    for comp in _components(path):
        stem = comp.split(".", 1)[0].strip().upper()
        if stem in _RESERVED:
            return True
    return False


def has_trailing_dot_or_space(path):
    """Компонент, заканчивающийся точкой или пробелом.

    Windows такие окончания молча срезает, поэтому 'name.' и 'name' — один и тот же файл;
    это классический способ разойтись проверке и фактической операции.

    Компоненты '.' и '..' — законная навигация, а не имя с завершающей точкой: обзор диска
    намеренно не ограничен местом, и путь вида 'C:\\Models\\..\\Other' обязан работать.
    """
    for comp in _components(path):
        if comp in (".", ".."):
            continue
        if comp != comp.rstrip(". "):
            return True
    return False


def check_client_path(raw, require_absolute=True):
    """Проверка ФОРМЫ пути, пришедшего от клиента.

    Не проверяет существование и не обращается к диску. Не решает, «внутри» ли путь
    какого-либо каталога — обзор диска остаётся разрешённым по замыслу продукта.

    require_absolute=True (по умолчанию) — интерфейс присылает абсолютный локальный путь,
    полученный из нашего же файлового менеджера. Относительный путь означал бы
    зависимость от текущего каталога процесса и здесь не принимается.
    """
    if not isinstance(raw, str):
        return _deny(REASON_NOT_STRING)
    if not raw:
        return _deny(REASON_EMPTY)
    if len(raw) > MAX_PATH_LEN:
        return _deny(REASON_TOO_LONG)
    if _CONTROL_RE.search(raw):
        return _deny(REASON_CONTROL_CHARS)

    # Пространства имён Windows. Проверяются ДО нормализации: normpath их не устраняет,
    # а os.path.abspath способен превратить device-путь в «обычный» на вид.
    head = raw[:4].replace("/", "\\")
    if head.startswith("\\\\?\\"):
        return _deny(REASON_EXTENDED)
    if head.startswith("\\\\.\\"):
        return _deny(REASON_DEVICE)
    if raw[:2].replace("/", "\\") == "\\\\":
        return _deny(REASON_UNC)   # \\server\share — чужой компьютер, не этот

    if _DRIVE_RELATIVE_RE.match(raw):
        return _deny(REASON_DRIVE_RELATIVE)

    # Альтернативный поток NTFS: 'file.txt:stream'. Двоеточие законно только как
    # разделитель буквы диска во второй позиции.
    tail = raw[2:] if _LOCAL_ABS_RE.match(raw) else raw
    if ":" in tail:
        return _deny(REASON_ADS)

    if has_reserved_name(raw):
        return _deny(REASON_RESERVED_NAME)
    if has_trailing_dot_or_space(raw):
        return _deny(REASON_TRAILING_DOT_SPACE)

    if require_absolute and not _LOCAL_ABS_RE.match(raw):
        return _deny(REASON_NOT_ABSOLUTE)

    # normpath снимает '.', схлопывает повторяющиеся разделители и приводит их к
    # разделителю платформы. Он НЕ является проверкой безопасности и здесь ничего не
    # разрешает: все опасные формы уже отклонены выше.
    return PathDecision(True, REASON_OK, os.path.normpath(raw))


def is_within(base, target):
    """Лежит ли target внутри base (или совпадает с ним).

    ОБА пути должны быть уже разрешены вызывающим через os.path.realpath: именно это
    снимает символические ссылки и junction — иначе ссылка внутри каталога выводила бы
    наружу, а проверка этого не замечала.

    Сравнение покомпонентное через commonpath. Строковый префикс здесь неприменим:
    'C:\\Data\\Farm-evil'.startswith('C:\\Data\\Farm') истинно, хотя это разные каталоги.
    Регистр приводится normcase — на Windows пути регистронезависимы.
    """
    if not isinstance(base, str) or not isinstance(target, str) or not base or not target:
        return False
    b = os.path.normcase(os.path.normpath(base))
    t = os.path.normcase(os.path.normpath(target))
    if b == t:
        return True
    try:
        return os.path.commonpath([b, t]) == b
    except ValueError:
        # Разные диски, либо смесь абсолютного и относительного — принадлежности нет.
        return False


def check_within(base, target):
    """is_within в виде решения с кодом причины (для единообразия с check_client_path)."""
    if is_within(base, target):
        return PathDecision(True, REASON_OK, os.path.normpath(target))
    return _deny(REASON_OUTSIDE_BASE)
