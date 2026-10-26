# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — ВЕРСИИ формата резервного копирования (НЕИЗМЕНЯЕМЫЙ контракт).

РАЗНЫЕ независимые версии (НИКОГДА не APP_VERSION — та только metadata):
  container_format_version  — внешний ZIP / header.json / шифрование;
  payload_schema_version    — общая логическая структура payload;
  *_settings_schema         — секции core/printers/module;
  <adapter>_schema          — схема настроек конкретного адаптера.

ПРАВИЛО (docs/BACKUP_COMPATIBILITY_CONTRACT.md): опубликованные значения версий и смысл
байтов при них — навсегда. Несовместимая структура -> увеличить версию и ДОБАВИТЬ миграцию;
переписывать старые миграции/смысл нельзя.
"""

# Идентификатор формата — константа навсегда.
FORMAT_ID = "com.3diwell.farm-manager.configuration-backup"
BACKUP_EXTENSION = ".3diwell-backup"

# Внешний контейнер (ZIP+header). container v1 = ЗАШИФРОВАННЫЙ (payload.enc, всегда пароль).
# ВЕРСИЯ 1 ЗАМОРОЖЕНА НАВСЕГДА и НЕ меняется — это опубликованный контракт.
CONTAINER_FORMAT_VERSION = 1            # v1 (заморожен): всегда AES-256-GCM + пароль

# Alpha 2.828: container v2 — упаковка + режим защиты. Логическая модель payload та же.
# v2 читает payload.bin и поддерживает protection_mode: none (без пароля) / password_aes256gcm.
CONTAINER_FORMAT_VERSION_2 = 2
MAX_CONTAINER_FORMAT_VERSION = 2        # максимально поддерживаемая версия контейнера (для отказа будущим)

# Имена записей ZIP. v1 -> payload.enc (не менять); v2 -> payload.bin.
HEADER_NAME = "header.json"
PAYLOAD_NAME_V1 = "payload.enc"
PAYLOAD_NAME_V2 = "payload.bin"

# Режимы защиты v2. none — по умолчанию (без пароля, полный payload открытым текстом внутри
# ZIP + SHA-256/CRC от СЛУЧАЙНОГО повреждения, НЕ от намеренной подмены). password_aes256gcm —
# тот же проверенный стек v1 (scrypt + AES-256-GCM + AAD=header). Пустой пароль как ключ ЗАПРЕЩЁН.
PROTECTION_MODE_NONE = "none"
PROTECTION_MODE_PASSWORD = "password_aes256gcm"
PROTECTION_MODES = frozenset((PROTECTION_MODE_NONE, PROTECTION_MODE_PASSWORD))
DEFAULT_PROTECTION_MODE = PROTECTION_MODE_NONE     # Alpha 2.828: без пароля — основной сценарий

# Кодировка payload (обе версии контейнера): канонический UTF-8 JSON логической модели.
PAYLOAD_ENCODING_CANONICAL_JSON = "canonical-json-utf8"

# Логическая структура payload. Alpha 2.829: выпуск 2 — добавлена секция module_data
# (настройки и пользовательские данные модулей). Контейнеры v1/v2 при этом НЕ меняются:
# payload-версия живёт в манифесте payload и мигрируется append-only цепочкой.
# КРИТИЧНО: в payload v1 (Alpha 2.827-2.828) секция module_data ОТСУТСТВУЕТ (None), а не пуста —
# импорт старой копии НЕ очищает и НЕ заменяет данные модулей.
PAYLOAD_SCHEMA_VERSION = 2

# Схема секции module_data (растёт независимо; identity модуля = stable module_id).
MODULE_DATA_SECTION_SCHEMA = 1

# Версии секций (растут независимо; каждая правка -> миграция).
CORE_SETTINGS_SCHEMA = 1
PRINTERS_SCHEMA = 1
MODULE_SETTINGS_SCHEMA = 1

# Версии схем адаптеров (настройки, специфичные для типа принтера).
ADAPTER_SCHEMAS = {
    "bambu": 1,
    "flashforge": 1,
    "moonraker": 1,
    "klipper": 1,           # синоним moonraker-транспорта в проекте
}

# Возможности ридера, которые может потребовать header (required_reader_capabilities).
# Незнакомая ОБЯЗАТЕЛЬНАЯ возможность -> безопасный отказ (unknown нельзя трактовать как known).
KNOWN_READER_CAPABILITIES = frozenset((
    "aes256gcm-scrypt-v1",     # базовый крипто-контракт v1 (и password-режим v2)
    "cleartext-json-v2",       # Alpha 2.828: незашифрованный payload.bin (v2 protection_mode=none)
))

# Пространство имён для расширений (unknown optional namespaced ext сохраняются).
EXTENSION_NAMESPACE_PREFIX = "x-"
