# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Файловый менеджер принтеров (Alpha 2.823) — адаптер FlashForge AD5M.

Доказанная база: ТОЛЬКО `POST /gcodeList` (server.py _flashforge_files) — плоский
список ИМЁН программ печати, без размеров, дат, папок и накопителей. Удаление
файлов этим HTTP-API проектом НЕ подтверждено -> delete_files=False честно:
кнопки удаления для FlashForge отключены с причиной unsupported, экспериментальные
destructive-запросы реальному принтеру не выполняются.

Транспорт ВНЕДРЯЕТСЯ: list_names(printer_id) -> list[str] (server.py передаёт
обёртку над _flashforge_files; тест — фейк). Сам модуль в сеть не ходит.
"""
from app.printer_files import models as M
from app.printer_files.base import PrinterFileProvider, PrinterFileError


class FlashforgeFileProvider(PrinterFileProvider):
    adapter = "flashforge"
    delete_safe_during_print = False
    timelapse_dirs = ()
    # Alpha 2.825: печать существующего файла доказана ТОЛЬКО для чистого g-code
    # (/printGcode, C1 2.728). .3mf НЕ printable: прошивка A5M исполняет только чистый
    # g-code — контейнер целиком ВЕШАЕТ принтер (доказано 2.764), печать существующего
    # .3mf старым flow не поддерживается.
    printable_extensions = (".gcode", ".gx", ".g", ".gco")

    def __init__(self, list_names):
        self._list_names = list_names

    def probe_capabilities(self, printer):
        if not (printer or {}).get("has_credentials"):
            return M.PrinterFileCapabilities(
                supported=False, reason=M.REASON_NO_CREDENTIALS, adapter=self.adapter)
        return M.PrinterFileCapabilities(
            supported=True, list_files=True, browse_directories=False,
            delete_files=False,            # доказанного delete-API нет — не притворяемся
            # Печать существующего файла ДОКАЗАНА историческим путём /printGcode
            # (C1 start_print 2.728; см. 2.768 — это и есть штатный старый flow).
            print_existing_files=True,
            read_sizes=False, read_mtime=False, read_storage_usage=False,
            read_previews=False, storage_types=(M.STORAGE_INTERNAL,), adapter=self.adapter)

    def list_storages(self, printer):
        if not (printer or {}).get("has_credentials"):
            raise PrinterFileError(M.REASON_NO_CREDENTIALS)
        return [M.PrinterStorage(storage_id="internal", display_name="Память принтера",
                                 type=M.STORAGE_INTERNAL, writable=False,
                                 total_bytes=None, free_bytes=None, online=True)]

    def list_directory(self, printer, storage_id, rel_path):
        if str(storage_id) != "internal" or rel_path:
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        try:
            names = self._list_names(str((printer or {}).get("id") or ""))
        except PrinterFileError:
            raise
        except (TimeoutError,):
            raise PrinterFileError(M.REASON_TIMEOUT)
        except Exception:
            raise PrinterFileError(M.REASON_CONNECTION_LOST)
        if names is None or not isinstance(names, (list, tuple)):
            raise PrinterFileError(M.REASON_MALFORMED)
        out = []
        for n in names:
            nm = str(n or "").replace("\\", "/").split("/")[-1].strip()
            if nm:
                out.append({"name": nm, "is_dir": False, "size": None, "mtime": None})
        return out

    def delete_file(self, printer, storage_id, rel_path):
        raise PrinterFileError(M.REASON_UNSUPPORTED)   # доказанного API нет
