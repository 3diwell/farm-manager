# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Файловый менеджер принтеров (Alpha 2.823) — политика безопасности.

ТОЛЬКО stdlib. Не импортирует server.py/сеть/БД. Здесь:
  * нормализация относительных путей (fail-closed: '..', абсолютные, UNC, схемы — отказ);
  * НЕПРОЗРАЧНЫЕ ссылки file_ref/directory_ref (bounded-реестр с TTL: UI никогда не
    передаёт и не получает реальный путь устройства);
  * централизованная категоризация файлов (программы/видео/таймлапс/изображения/журналы);
  * политика защищённых файлов (system/firmware/dotfiles/каталоги/активная печать);
  * предохранитель удаления: PRINTER_FILE_DELETE_ENABLED_DEFAULT = False — удаление
    ВЫКЛЮЧЕНО по умолчанию и включается только системным администратором в настройках.
    Этот флаг НЕ связан с DISPATCH/TRANSPORT и не включает отправку печати.
"""
import secrets
import threading
import time

from app.printer_files import models as M

# ── Предохранитель удаления (значение по умолчанию; рантайм читает настройку сервера) ──
PRINTER_FILE_DELETE_ENABLED_DEFAULT = False
PRINTER_FILE_READ_ENABLED_DEFAULT = True

# ── Нормализация путей (пути живут ТОЛЬКО на сервере; от UI приходят только refs) ─────
_FORBIDDEN_SCHEMES = ("file:", "javascript:", "http:", "https:", "ftp:", "data:", "vbscript:")


def normalize_rel_path(raw):
    """Безопасный ОТНОСИТЕЛЬНЫЙ путь внутри storage root -> str | None (None = отказ).

    Fail-closed: '..' в любом сегменте, абсолютные пути (/, \\, X:), UNC (//host),
    URL-схемы (file:, javascript:, ...), управляющие символы, пустые сегменты — отказ.
    Разделитель нормализуется к '/'; ведущие/хвостовые '/' снимаются."""
    s = str(raw if raw is not None else "")
    if len(s) > 1024:
        return None
    low = s.lower().lstrip()
    for sch in _FORBIDDEN_SCHEMES:
        if low.startswith(sch):
            return None
    s = s.replace("\\", "/")
    if s.startswith("//") or s.startswith("\\\\"):
        return None                     # UNC
    if len(s) >= 2 and s[1] == ":":
        return None                     # Windows-диск (C:)
    if any(ord(c) < 32 or c == "\x7f" for c in s):
        return None                     # управляющие символы
    if s.startswith("/"):
        return None                     # абсолютный путь — отказ (не «относителизуем» молча)
    s = s.strip("/")
    if s == "":
        return ""                       # корень storage — допустим для каталогов
    parts = []
    for seg in s.split("/"):
        seg = seg.strip()
        if seg in ("", ".",):
            return None                 # пустой сегмент/точка — не нормальный листинг
        if seg == ".." or seg.startswith(".."):
            return None                 # traversal
        parts.append(seg)
    if len(parts) > 12:
        return None                     # разумная глубина
    return "/".join(parts)


def storage_id_ok(sid):
    """storage_id — короткий непрозрачный токен [a-z0-9_-]{1,32} (не путь)."""
    s = str(sid or "")
    return bool(s) and len(s) <= 32 and all(c.isalnum() or c in "_-" for c in s) and s == s.lower()


# ── Категоризация (централизованно; ЭТАП 5) ───────────────────────────────────
_PROGRAM_EXTS = frozenset((".gcode", ".g", ".gx", ".gco", ".3mf"))
_VIDEO_EXTS = frozenset((".mp4", ".avi", ".mkv", ".mov"))
_IMAGE_EXTS = frozenset((".jpg", ".jpeg", ".png", ".webp", ".bmp"))
_LOG_EXTS = frozenset((".log",))
# Явно системные/прошивочные расширения — удалять нельзя никогда.
_SYSTEM_EXTS = frozenset((".bin", ".sig", ".fw", ".img", ".cfg", ".conf", ".json", ".db", ".ini", ".sh", ".py"))


def file_ext(name):
    n = str(name or "")
    # составное .gcode.3mf считаем .3mf (печатный контейнер)
    i = n.rfind(".")
    return n[i:].lower() if i > 0 else ""


def categorize(name, dir_hint="", timelapse_dirs=()):
    """-> (category, timelapse: bool). Таймлапсом видео считается ТОЛЬКО в доказанной
    timelapse-папке адаптера (произвольный MP4 таймлапсом не объявляется)."""
    ext = file_ext(name)
    if ext in _PROGRAM_EXTS:
        return (M.CAT_PROGRAM, False)
    if ext in _VIDEO_EXTS:
        d = str(dir_hint or "").strip("/").lower()
        tl = any(d == str(t).strip("/").lower() or d.startswith(str(t).strip("/").lower() + "/")
                 for t in (timelapse_dirs or ()))
        return (M.CAT_VIDEO, bool(tl))
    if ext in _IMAGE_EXTS:
        return (M.CAT_IMAGE, False)
    if ext in _LOG_EXTS:
        return (M.CAT_LOG, False)
    return (M.CAT_OTHER, False)


def protection_for(name, is_directory, category, storage_writable, active_names=()):
    """Политика защиты одного элемента -> (deletable: bool, reason: str).

    Нельзя удалять: каталоги; элементы read-only storage; dotfiles; системные/прошивочные
    расширения; журналы (system log по умолчанию protected); файл активной печати
    (сравнение нормализованных имён). Неизвестное «прочее» — protected fail-closed."""
    n = str(name or "")
    if is_directory:
        return (False, M.REASON_DIRECTORY)
    if not storage_writable:
        return (False, M.REASON_READ_ONLY)
    if not n or n.startswith("."):
        return (False, M.REASON_SYSTEM_FILE)
    ext = file_ext(n)
    if ext in _SYSTEM_EXTS or ext == "":
        return (False, M.REASON_SYSTEM_FILE)
    if category == M.CAT_LOG:
        return (False, M.REASON_SYSTEM_FILE)
    if category == M.CAT_OTHER:
        # не доказан обычный пользовательский тип — fail-closed
        return (False, M.REASON_SYSTEM_FILE)
    if _name_matches_active(n, active_names):
        return (False, M.REASON_ACTIVE_PRINT_FILE)
    return (True, "")


def printable_for(name, is_directory, category, storage_id, caps_print_existing,
                  printable_exts=(), printable_storages=None):
    """Alpha 2.825: политика печатаемости одного элемента -> (printable: bool, reason: str).

    НЕЗАВИСИМА от deletable. Fail-closed: печатается ТОЛЬКО обычная программа печати
    (category=program) с расширением из ДОКАЗАННОГО списка адаптера, из накопителя,
    откуда существующий C1-flow реально умеет стартовать. Каталоги, видео/таймлапсы,
    изображения, журналы и «прочее» — никогда не printable."""
    if is_directory:
        return (False, M.REASON_DIRECTORY)
    if not caps_print_existing:
        return (False, M.REASON_PRINT_STORAGE_UNSUPPORTED)
    if category != M.CAT_PROGRAM:
        return (False, M.REASON_FILE_NOT_PRINTABLE)
    ext = file_ext(name)
    if ext not in tuple(printable_exts or ()):
        return (False, M.REASON_FILE_NOT_PRINTABLE)
    if printable_storages is not None and str(storage_id) not in tuple(printable_storages):
        return (False, M.REASON_PRINT_STORAGE_UNSUPPORTED)
    return (True, "")


def _strip_print_ext(base):
    b = str(base or "").lower()
    for e in (".gcode.3mf", ".gcode.gz", ".gcode", ".3mf", ".gco", ".gx", ".g"):
        if b.endswith(e):
            return b[:-len(e)]
    return b


def _name_matches_active(name, active_names):
    """Совпадение с файлом активной печати: по basename без регистра И по стему без
    печатных расширений (принтер может сообщать имя без/с другим расширением)."""
    b = str(name or "").replace("\\", "/").split("/")[-1].strip().lower()
    if not b:
        return False
    stem = _strip_print_ext(b)
    for a in (active_names or ()):
        ab = str(a or "").replace("\\", "/").split("/")[-1].strip().lower()
        if not ab:
            continue
        if b == ab or (stem and stem == _strip_print_ext(ab)):
            return True
    return False


# ── Непрозрачные ссылки (ЭТАП 3): bounded-реестр с TTL ─────────────────────────
_REF_TTL_S = 30 * 60          # 30 минут; протухшая ссылка -> stale_reference
_REF_MAX = 20000              # потолок реестра; старейшие вытесняются


class RefRegistry:
    """Реестр непрозрачных ссылок. UI получает и возвращает ТОЛЬКО токены pfr_/pfd_;
    сервер резолвит их в (printer_id, storage_id, rel_path, is_dir) и ПЕРЕПРОВЕРЯЕТ
    принадлежность принтеру. Подмена printer_id/storage_id внутри ссылки невозможна:
    ссылка непрозрачна, а resolve() требует совпадения printer_id вызова."""

    def __init__(self, ttl_s=_REF_TTL_S, max_items=_REF_MAX, now=None):
        self._ttl = ttl_s
        self._max = max_items
        self._now = now or time.monotonic
        self._lock = threading.Lock()
        self._items = {}              # ref -> (printer_id, storage_id, rel_path, is_dir, born)

    def make(self, printer_id, storage_id, rel_path, is_dir):
        """-> непрозрачный токен. rel_path обязан быть УЖЕ нормализованным."""
        tok = ("pfd_" if is_dir else "pfr_") + secrets.token_hex(12)
        with self._lock:
            if len(self._items) >= self._max:
                # вытесняем ~10% старейших (bounded, без роста без ограничений)
                for k in sorted(self._items, key=lambda k: self._items[k][4])[:max(1, self._max // 10)]:
                    self._items.pop(k, None)
            self._items[tok] = (str(printer_id), str(storage_id), str(rel_path), bool(is_dir), self._now())
        return tok

    def resolve(self, ref, printer_id):
        """-> (storage_id, rel_path, is_dir) | None. None = stale/чужой принтер/мусор."""
        tok = str(ref or "")
        if not (tok.startswith("pfr_") or tok.startswith("pfd_")):
            return None
        with self._lock:
            row = self._items.get(tok)
        if not row:
            return None
        pid, sid, path, is_dir, born = row
        if pid != str(printer_id):
            return None                              # подмена принтера — отказ
        if (self._now() - born) > self._ttl:
            with self._lock:
                self._items.pop(tok, None)
            return None                              # TTL истёк -> stale_reference
        return (sid, path, is_dir)

    def drop_printer(self, printer_id):
        """Сбросить все ссылки принтера (смена принтера/обновление больших объёмов)."""
        with self._lock:
            for k in [k for k, v in self._items.items() if v[0] == str(printer_id)]:
                self._items.pop(k, None)
