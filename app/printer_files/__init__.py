# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Файловый менеджер принтеров (Alpha 2.823) — чистый слой без сети и server.py.

Состав: models (данные и reason-коды), security (пути/refs/категории/защита),
base (контракт провайдера), bambu/moonraker/flashforge (адаптеры с внедряемым
транспортом), registry (выбор адаптера по типу принтера).
"""
