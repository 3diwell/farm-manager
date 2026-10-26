# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Библиотека модуля «Уведомления в мессенджеры» (модуль messengers 0.1.0).

Живёт ВНУТРИ папки модуля и ставится вместе с ним из ZIP; ядро программы о ней не знает.
backend.py модуля добавляет свою папку в sys.path и импортирует этот пакет.

  models.py    общие типы: результат отправки, описание поля, коды причин, события
  base.py      интерфейс площадки-провайдера
  telegram.py  Telegram Bot API            (контракт: core.telegram.org/bots/api)
  whatsapp.py  WhatsApp Business Cloud API (контракт: developers.facebook.com, Graph API)
  vk.py        VK API 5.199                (контракт: dev.vk.com, схема VKCOM/vk-api-schema)
  registry.py  список площадок и каталог для окна модуля
  settings.py  нормализация настроек, слияние правок, показ без секретов
  store.py     хранение в БД модуля: настройки отдельно, ключи отдельно
  transport.py HTTP через urllib с вычисткой секретов из текста ошибок
  service.py   диспетчер: очередь, рабочий поток, события фермы, тексты, защита от повторов
  pairing.py   мастер подключения: проверка ключа, ссылка «нажмите Start», авто-привязка чата

ЖЕЛЕЗНОЕ ПРАВИЛО. Ничто здесь не влияет на печать: все входы fail-open, сеть — только в
своих потоках, сбой площадки — строка статуса в окне модуля, а не ошибка сервера.
"""
