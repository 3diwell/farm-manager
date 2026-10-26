# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Файловый менеджер принтеров (Alpha 2.823) — реестр провайдеров.

Выбор адаптера СТРОГО по типу принтера из конфигурации; НИКАКОГО угадывания
протокола и сканирования устройства случайными портами. Неизвестный тип честно
получает supported=False (unsupported), а не пустой список файлов.
"""
from app.printer_files import models as M
from app.printer_files.base import PrinterFileProvider


class _UnsupportedProvider(PrinterFileProvider):
    adapter = "unknown"

    def probe_capabilities(self, printer):
        return M.PrinterFileCapabilities(supported=False, reason=M.REASON_UNSUPPORTED,
                                         adapter=str((printer or {}).get("type") or "unknown"))


class ProviderRegistry:
    """providers: dict адаптеров по типу принтера ('bambu'/'klipper'/'flashforge').
    server.py создаёт реестр один раз с внедрёнными реальными транспортами."""

    def __init__(self, providers):
        self._providers = dict(providers or {})
        self._unsupported = _UnsupportedProvider()

    def provider_for(self, printer):
        """-> провайдер для принтера. Неизвестный/пустой тип -> честный unsupported."""
        ptype = str((printer or {}).get("type") or "").strip().lower()
        return self._providers.get(ptype, self._unsupported)

    def capabilities(self, printer):
        return self.provider_for(printer).probe_capabilities(printer)
