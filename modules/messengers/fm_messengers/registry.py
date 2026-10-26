# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Реестр площадок. Порядок списка — порядок карточек в окне модуля.

Новая площадка: файл с провайдером + одна строка в default_registry().
"""
from collections import OrderedDict

from .max import MaxProvider
from .telegram import TelegramProvider
from .vk import VkProvider
from .whatsapp import WhatsAppProvider


class MessengerRegistry(object):
    def __init__(self, providers):
        self._p = OrderedDict()
        for p in providers or ():
            if not p.kind or p.kind in self._p:
                raise ValueError("messenger kind must be unique and non-empty: %r" % (p.kind,))
            self._p[p.kind] = p

    def kinds(self):
        return list(self._p.keys())

    def get(self, kind):
        return self._p.get(str(kind or "").strip().lower())

    def providers(self):
        return list(self._p.values())

    def catalog(self, lang):
        return [p.describe(lang) for p in self._p.values()]

    def secret_keys(self):
        return {p.kind: p.secret_keys() for p in self._p.values()}


def default_registry(api_bases=None):
    """api_bases: {kind: base_url} — ТОЛЬКО для проверок с поддельным сервером."""
    ab = api_bases or {}
    return MessengerRegistry([
        TelegramProvider(ab.get("telegram")),
        VkProvider(ab.get("vk")),
        MaxProvider(ab.get("max")),
        WhatsAppProvider(ab.get("whatsapp")),
    ])
