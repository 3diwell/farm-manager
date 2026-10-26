# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Файловый менеджер принтеров (Alpha 2.823) — контракт провайдера.

PrinterFileProvider — единый интерфейс файлового доступа. Каждый адаптер реализует
ТОЛЬКО доказанные возможности своего протокола; неподдержанное честно возвращает
supported=False/reason, а не пустой список. ТОЛЬКО stdlib; транспорт (FTPS/HTTP)
ВНЕДРЯЕТСЯ снаружи (server.py передаёт реальные клиенты, тесты — фейки) — сам пакет
в сеть не ходит и команд принтерам не шлёт.
"""
from app.printer_files import models as M


class PrinterFileError(Exception):
    """Единственный класс ошибок наружу: несёт БЕЗОПАСНЫЙ reason-код из models.SAFE_REASONS
    (никаких raw-ответов протокола/IP/путей/credentials)."""

    def __init__(self, reason):
        r = str(reason or M.REASON_CONNECTION_LOST)
        self.reason = r if r in M.SAFE_REASONS else M.REASON_CONNECTION_LOST
        super().__init__(self.reason)


class PrinterFileProvider(object):
    """Базовый провайдер. printer — безопасный dict {id, type, model, gen, has_credentials}
    (IP/token адаптеру передаёт server.py отдельно через внедрённый транспорт)."""

    adapter = "unknown"

    def probe_capabilities(self, printer):
        """-> PrinterFileCapabilities. СТАТИЧЕСКОЕ определение по адаптеру и конфигурации,
        БЕЗ обращения к устройству (сетевые операции начинаются только по действию
        пользователя: list_storages/list_directory)."""
        return M.PrinterFileCapabilities(supported=False, reason=M.REASON_UNSUPPORTED,
                                         adapter=self.adapter)

    def list_storages(self, printer):
        """-> list[PrinterStorage]. Может ходить в сеть через внедрённый транспорт."""
        raise PrinterFileError(M.REASON_UNSUPPORTED)

    def list_directory(self, printer, storage_id, rel_path):
        """-> list[dict] сырых элементов {name, is_dir, size|None, mtime|None}.
        rel_path — УЖЕ нормализованный security.normalize_rel_path."""
        raise PrinterFileError(M.REASON_UNSUPPORTED)

    def delete_file(self, printer, storage_id, rel_path):
        """Удалить ОДИН файл (не каталог). -> True при подтверждённом успехе.
        Таймаут/неизвестный результат — PrinterFileError(timeout): отсутствие ответа
        НЕ считается подтверждением удаления, автоматических повторов НЕТ."""
        raise PrinterFileError(M.REASON_UNSUPPORTED)

    # Необязательные операции (2.823 не реализует preview).
    def get_file_metadata(self, printer, storage_id, rel_path):
        raise PrinterFileError(M.REASON_UNSUPPORTED)

    def get_preview(self, printer, storage_id, rel_path):
        raise PrinterFileError(M.REASON_UNSUPPORTED)

    def storage_writable(self, printer, storage_id):
        """Чистая (без сети) проверка: разрешает ли ПОЛИТИКА адаптера удаление в этом
        накопителе. False по умолчанию (fail-closed)."""
        return False

    # Безопасность работы при печати (ЭТАП 14): можно ли удалять ДРУГИЕ файлы,
    # пока принтер печатает. Неизвестно -> False (delete блокируется весь).
    delete_safe_during_print = False
    # Доказанные timelapse-каталоги адаптера (для категоризации).
    timelapse_dirs = ()
    # Alpha 2.825: расширения, печать которых ДОКАЗАНА существующим C1-flow адаптера
    # (start_print файла, уже лежащего на принтере). Пусто = печать существующих
    # файлов не заявляется (fail-closed); printable считается ТОЛЬКО по этому списку.
    printable_extensions = ()
    # Накопители, из которых существующий start-flow адаптера УМЕЕТ запускать печать
    # (None = любой storage адаптера). Например, Klipper печатает только из root gcodes.
    printable_storages = None
