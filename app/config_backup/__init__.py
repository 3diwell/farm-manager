# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — постоянный контракт резервного копирования конфигурации.

ЧИСТЫЙ слой (кроме serializer/repository-адаптера): не импортирует server.py в модулях
формата/крипто/миграций. Правила совместимости — docs/BACKUP_COMPATIBILITY_CONTRACT.md;
спецификация первого формата — docs/BACKUP_FORMAT_V1.md. НИКОГДА не менять опубликованный
формат/миграцию/frozen-fixture — только добавлять новую версию.
"""
