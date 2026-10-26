# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Файловый менеджер принтеров (Alpha 2.823) — чистые модели данных.

ТОЛЬКО stdlib. Не импортирует server.py, веб-фреймворк, сеть, БД и DATA_DIR.
Единый словарь безопасных reason-кодов: наружу уходят ТОЛЬКО они (никаких raw-ответов
протокола, IP, путей, credentials, traceback).
"""
from dataclasses import dataclass
from typing import Optional, Tuple

# ── Безопасные reason-коды (единственный словарь ошибок наружу) ────────────────
REASON_UNSUPPORTED = "unsupported"
REASON_NO_CREDENTIALS = "no_credentials"
REASON_STORAGE_OFFLINE = "storage_offline"
REASON_READ_ONLY = "read_only"
REASON_FILE_BUSY = "file_busy"
REASON_ACTIVE_PRINT_FILE = "active_print_file"
REASON_STALE_REFERENCE = "stale_reference"
REASON_NOT_FOUND = "not_found"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_DELETE_DISABLED = "delete_disabled"
REASON_TIMEOUT = "timeout"
REASON_CONNECTION_LOST = "connection_lost"
REASON_DELETE_UNCONFIRMED = "delete_unconfirmed"
REASON_PARTIAL_FAILURE = "partial_failure"
REASON_SYSTEM_FILE = "system_file"
REASON_DIRECTORY = "directory"
REASON_PRINTING_UNVERIFIED = "printing_delete_unverified"
REASON_MALFORMED = "malformed_response"
REASON_BAD_REQUEST = "bad_request"
REASON_READ_DISABLED = "read_disabled"
# ── Alpha 2.825: печать существующего файла (select-for-print / print) ─────────
REASON_FILE_NOT_PRINTABLE = "file_not_printable"
REASON_PRINTER_OFFLINE = "printer_offline"
REASON_PRINTER_BUSY = "printer_busy"
REASON_PRINT_STORAGE_UNSUPPORTED = "print_from_storage_unsupported"
REASON_PREFLIGHT_FAILED = "preflight_failed"

# ── Alpha 2.989: предпросмотр файла принтера ─────────────────────────────────
#  Файл слишком велик, чтобы тянуть его ради картинки, или картинки внутри нет.
REASON_TOO_LARGE = "too_large"
REASON_NO_PREVIEW = "no_preview"

SAFE_REASONS = frozenset((
    REASON_UNSUPPORTED, REASON_NO_CREDENTIALS, REASON_STORAGE_OFFLINE, REASON_READ_ONLY,
    REASON_FILE_BUSY, REASON_ACTIVE_PRINT_FILE, REASON_STALE_REFERENCE, REASON_NOT_FOUND,
    REASON_PERMISSION_DENIED, REASON_DELETE_DISABLED, REASON_TIMEOUT, REASON_CONNECTION_LOST,
    REASON_DELETE_UNCONFIRMED, REASON_PARTIAL_FAILURE, REASON_SYSTEM_FILE, REASON_DIRECTORY,
    REASON_PRINTING_UNVERIFIED, REASON_MALFORMED, REASON_BAD_REQUEST, REASON_READ_DISABLED,
    REASON_FILE_NOT_PRINTABLE, REASON_PRINTER_OFFLINE, REASON_PRINTER_BUSY,
    REASON_TOO_LARGE, REASON_NO_PREVIEW,
    REASON_PRINT_STORAGE_UNSUPPORTED, REASON_PREFLIGHT_FAILED,
))

# ── Категории файлов (централизованно; см. security.categorize) ───────────────
CAT_PROGRAM = "program"
CAT_VIDEO = "video"
CAT_IMAGE = "image"
CAT_LOG = "log"
CAT_OTHER = "other"

STORAGE_INTERNAL = "internal"
STORAGE_USB = "usb"
STORAGE_SD = "sd"
STORAGE_OTHER = "other"


@dataclass(frozen=True)
class PrinterFileCapabilities:
    """Возможности файлового доступа конкретного принтера. НИЧЕГО не придумывается:
    каждый True обязан опираться на доказанный API (см. forensic-таблицу 2.823)."""
    supported: bool
    list_files: bool = False
    browse_directories: bool = False
    delete_files: bool = False
    # Alpha 2.825: печать УЖЕ существующего файла принтера через доказанный старый
    # C1-flow (/api/printer/{pid}/cmd start_print). НЕЗАВИСИМА от delete_files.
    print_existing_files: bool = False
    read_sizes: bool = False
    read_mtime: bool = False
    read_storage_usage: bool = False
    read_previews: bool = False
    storage_types: Tuple[str, ...] = ()
    reason: str = ""                      # безопасный reason-код при supported=False
    adapter: str = ""                     # имя адаптера для UI ("bambu"/"klipper"/"flashforge")

    def as_dict(self):
        return {
            "supported": bool(self.supported),
            "list_files": bool(self.list_files),
            "browse_directories": bool(self.browse_directories),
            "delete_files": bool(self.delete_files),
            "print_existing_files": bool(self.print_existing_files),
            "read_sizes": bool(self.read_sizes),
            "read_mtime": bool(self.read_mtime),
            "read_storage_usage": bool(self.read_storage_usage),
            "read_previews": bool(self.read_previews),
            "storage_types": list(self.storage_types),
            "reason": self.reason or "",
            "adapter": self.adapter or "",
        }


@dataclass(frozen=True)
class PrinterStorage:
    """Накопитель принтера. storage_id — НЕПРОЗРАЧНЫЙ короткий токен ([a-z0-9_-]),
    не абсолютный путь устройства."""
    storage_id: str
    display_name: str
    type: str = STORAGE_OTHER            # internal | usb | sd | other
    writable: bool = False
    total_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    online: bool = True

    def as_dict(self):
        return {
            "storage_id": self.storage_id, "display_name": self.display_name,
            "type": self.type, "writable": bool(self.writable),
            "total_bytes": self.total_bytes, "free_bytes": self.free_bytes,
            "online": bool(self.online),
        }


@dataclass
class PrinterFileEntry:
    """Один элемент листинга. Наружу уходят ТОЛЬКО эти поля; file_ref/parent_ref —
    непрозрачные токены (см. security.RefRegistry), реального пути в них нет."""
    file_ref: str
    name: str
    is_directory: bool = False
    category: str = CAT_OTHER
    timelapse: bool = False               # видео из ДОКАЗАННОЙ timelapse-папки
    extension: str = ""
    size_bytes: Optional[int] = None
    modified_at: Optional[int] = None     # epoch seconds; None = «Дата неизвестна»
    storage_id: str = ""
    deletable: bool = False
    protected_reason: str = ""            # безопасный reason-код, почему deletable=False
    # Alpha 2.825: printable НЕЗАВИСИМ от deletable (три разные возможности:
    # selectable — производное UI-свойство, printable/deletable — авторитетны на backend).
    printable: bool = False
    print_blocked_reason: str = ""        # безопасный reason-код, почему printable=False
    active_print: bool = False
    preview_ref: str = ""                 # зарезервировано; в 2.823 всегда ""

    def as_dict(self):
        return {
            "file_ref": self.file_ref, "name": self.name, "is_directory": bool(self.is_directory),
            "category": self.category, "timelapse": bool(self.timelapse),
            "extension": self.extension, "size_bytes": self.size_bytes,
            "modified_at": self.modified_at, "storage_id": self.storage_id,
            "deletable": bool(self.deletable), "protected_reason": self.protected_reason or "",
            "printable": bool(self.printable), "print_blocked_reason": self.print_blocked_reason or "",
            "active_print": bool(self.active_print), "preview_ref": self.preview_ref or "",
        }


@dataclass
class DeleteResult:
    """Результат удаления ОДНОГО файла (bulk-ответ агрегируется из таких строк)."""
    file_ref: str
    name: str = ""
    ok: bool = False
    reason: str = ""                      # безопасный reason-код при ok=False

    def as_dict(self):
        return {"file_ref": self.file_ref, "name": self.name, "ok": bool(self.ok),
                "reason": self.reason or ""}
