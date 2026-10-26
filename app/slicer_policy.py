# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — политика пути к исполняемому файлу слайсера (Alpha 2.780).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, FastAPI, SQLite и
принтерные подсистемы — чтобы его можно было проверять офлайн-тестами без запуска
приложения и без рабочих данных.

ЗАЧЕМ. Сохранённый путь к слайсеру позже подставляется как argv[0] в subprocess.Popen,
то есть это выбор ИСПОЛНЯЕМОГО КОДА. Административную границу (кто вправе его менять)
держит _require_system_admin в server.py; здесь — вторая линия: что именно вообще
допустимо принять в качестве такого пути.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Это не проверка подлинности программы: содержимое файла не читается,
подпись не проверяется, хеш не считается. Задача скромнее и честнее — не дать записать в
настройку то, что заведомо не является локальной установленной программой (URL, устройство,
именованный канал, каталог, скрипт-обёртка, сетевой путь).

ФАЙЛ НЕ ЗАПУСКАЕТСЯ при проверке. Единственные обращения к диску — канонизация пути и
вопросы «существует ли» и «обычный ли это файл».
"""

import os
import re
from pathlib import Path

# Расширения, допустимые для исполняемого файла слайсера. Windows-установка любого из
# поддерживаемых слайсеров (Bambu Studio, OrcaSlicer, PrusaSlicer, FlashPrint, Cura) — это
# всегда .exe; ни один реальный сценарий проекта не требует иного. Скрипт-обёртки
# (.bat/.cmd/.ps1/.vbs/.js/.py) и ярлыки (.lnk) НЕ допускаются намеренно: они превращают
# выбор слайсера в выполнение произвольной команды, а пользы для рабочего процесса не дают.
DEFAULT_ALLOWED_EXT = (".exe",)

# Схема URL в начале строки: http://, file://, ftp://, ws:// и любые другие.
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")

# Префиксы пространств имён устройств Windows: \\.\PhysicalDrive0, \\.\pipe\x,
# \\?\GLOBALROOT\Device\..., \\?\ вообще. Проверяются ПОСЛЕ приведения / к \.
_DEVICE_PREFIXES = ("\\\\.\\", "\\\\?\\")


def _to_backslash(s):
    """Единая форма для проверки префиксов: прямые слэши Windows принимает наравне с обратными."""
    return s.replace("/", "\\")


def _is_unc(s):
    """Сетевой путь \\\\server\\share — но НЕ device-пространство \\\\.\\ и \\\\?\\."""
    t = _to_backslash(s)
    if t.startswith(_DEVICE_PREFIXES):
        return False
    return t.startswith("\\\\")


def validate_slicer_executable(path, allowed_ext=DEFAULT_ALLOWED_EXT, allow_unc=False):
    """Проверить и канонизировать путь к исполняемому файлу слайсера.

    -> (ok, normalized_absolute_path, reason)
    ok=True  — путь принят, normalized содержит канонический абсолютный путь.
    ok=False — normalized пустой, reason — КОРОТКИЙ код причины.

    reason намеренно не содержит самого пути: ответ об ошибке уходит в браузер, и полный
    абсолютный путь в нём раскрывал бы структуру диска сервера тому, кому отказано.
    """
    if not isinstance(path, str):
        return (False, "", "not_a_string")

    s = path.strip().strip('"')
    if not s:
        return (False, "", "empty")
    if "\x00" in s:
        return (False, "", "null_byte")
    if _URL_RE.match(s):
        return (False, "", "url_not_allowed")

    t = _to_backslash(s)
    if t.startswith(_DEVICE_PREFIXES):
        return (False, "", "device_path_not_allowed")
    if _is_unc(s) and not allow_unc:
        return (False, "", "network_path_not_allowed")

    # Канонизация: снимает ".." и "." , разрешает симлинки/junction'ы и приводит к
    # абсолютному виду. strict=True — несуществующий путь считается ошибкой сразу.
    try:
        p = Path(s).resolve(strict=True)
    except Exception:
        return (False, "", "not_found")

    # Канонизация могла привести к сетевому пути (например, через подключённый диск).
    if _is_unc(str(p)) and not allow_unc:
        return (False, "", "network_path_not_allowed")

    try:
        if not p.is_file():
            return (False, "", "not_a_file")
    except Exception:
        return (False, "", "not_a_file")

    if p.suffix.lower() not in tuple(e.lower() for e in allowed_ext):
        return (False, "", "bad_extension")

    return (True, str(p), "")


def same_executable(a, b):
    """Один ли это исполняемый файл. Сравнение канонических путей без учёта регистра
    (Windows-пути регистронезависимы); содержимое файлов не читается."""
    try:
        na = os.path.normcase(os.path.abspath(str(a or "")))
        nb = os.path.normcase(os.path.abspath(str(b or "")))
    except Exception:
        return False
    return bool(na) and na == nb
