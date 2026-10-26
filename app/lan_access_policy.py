# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — чистая политика сетевого доступа (Alpha 2.787).

ЧТО ЭТО. Единственное место, где решается, слушать ли сервер сеть. Решение выводится не из
одного флага конфигурации, а из ПРОВЕРЕННОГО набора предпосылок:

    сеть = запрошено И авторизация включена И есть активный администратор И конфиг цел

Любое «нет», «неизвестно» или «не удалось проверить» означает loopback. Это и есть закрытие
S-1: раньше при выключенной авторизации общий гейт не выполнял проверок, а сервер при этом
мог слушать 0.0.0.0 — то есть подавляющее большинство маршрутов было доступно любому
устройству сети без какой-либо идентификации.

ПОЧЕМУ ИМЕННО ТАК. Выключенная авторизация означает ЛОКАЛЬНЫЙ режим владельца, а не
«открытый сервер без паролей». Поэтому сеть открывается только там, где есть кому
предъявить права: включённая авторизация плюс существующий действующий администратор.
Автоматически включать авторизацию, создавать администратора или генерировать пароль
запрещено — это молча превратило бы обновление в смену модели доступа.

LOOPBACK ДОСТУПЕН ВСЕГДА. Что бы ни решила эта политика, локальный доступ не отключается:
иначе неверная настройка или сбой БД заперли бы владельца снаружи собственной программы.

ЧИСТЫЙ МОДУЛЬ: только стандартная библиотека. Не импортирует server.py и веб-фреймворк,
не открывает БД и DATA_DIR, не читает и не пишет config, не обращается к сети, не запускает
обнаружение и не логирует пользователей, логины и пароли. Импорт без побочных эффектов.
"""

import enum
from dataclasses import dataclass
from typing import Any


class BindScope(enum.Enum):
    """На каком интерфейсе слушает HTTP-сервер."""
    LOOPBACK = "LOOPBACK"   # только этот компьютер
    NETWORK = "NETWORK"     # локальная сеть


class AdminCheck(enum.Enum):
    """Результат проверки «есть ли хотя бы один ВКЛЮЧЁННЫЙ администратор».

    UNKNOWN — проверку выполнить не удалось (БД недоступна, нет таблицы, ошибка запроса).
    Это НЕ то же самое, что ABSENT: техническая ошибка не должна ни открывать сеть, ни
    приводить к необратимой нормализации конфигурации.
    """
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


# Безопасные коды причин. Ни имён, ни логинов, ни путей, ни деталей ошибок БД.
REASON_LAN_DISABLED = "lan_disabled"
REASON_AUTH_REQUIRED = "auth_required"
REASON_ADMIN_REQUIRED = "enabled_admin_required"
REASON_CONFIG_INVALID = "config_invalid"
REASON_ADMIN_CHECK_FAILED = "admin_check_failed"
REASON_LAN_ALLOWED = "lan_allowed"

LOOPBACK_HOST = "127.0.0.1"   # НЕ 'localhost': он неоднозначно резолвится в IPv4/IPv6
NETWORK_HOST = "0.0.0.0"


@dataclass(frozen=True)
class LanRequest:
    """Вход политики. Неизменяем; собирается вызывающим из штатных источников.

    requested_lan — СЫРОЕ значение из конфигурации, любого типа. Разбор строгий:
    сетью считается только настоящее True. Отсутствие ключа, null, строка "true",
    число 1 и любой другой мусор означают «не запрошено».
    """
    requested_lan: Any = None
    auth_enabled: bool = False
    admin_check: AdminCheck = AdminCheck.UNKNOWN
    config_valid: bool = True


@dataclass(frozen=True)
class LanDecision:
    """Решение политики. Неизменяемо и детерминировано."""
    effective_lan_enabled: bool
    bind_scope: BindScope
    discovery_enabled: bool
    reason: str
    should_normalize_config: bool = False

    @property
    def bind_host(self):
        return NETWORK_HOST if self.bind_scope is BindScope.NETWORK else LOOPBACK_HOST


def parse_requested_lan(raw):
    """Строгий разбор запрошенного значения. -> True | False | None (не задано/мусор).

    Никаких truthy-преобразований: "false" не станет True, 1 не станет True, null не
    станет True. Ровно это и было дырой прежнего контракта, где отсутствие ключа
    означало включённую сеть.
    """
    return raw if isinstance(raw, bool) else None


def _blocked(reason, normalize=False):
    return LanDecision(effective_lan_enabled=False, bind_scope=BindScope.LOOPBACK,
                       discovery_enabled=False, reason=reason,
                       should_normalize_config=normalize)


def decide(request):
    """Решение о сетевом доступе. Порядок ветвей значим.

    should_normalize_config=True выставляется ТОЛЬКО когда отказ окончателен и проверен:
    авторизация выключена либо активного администратора заведомо нет. При технической
    ошибке проверки флаг не выставляется — иначе временный сбой БД безвозвратно затёр бы
    настройку пользователя. Само решение о записи принимает вызывающий; политика ничего
    не пишет.
    """
    if not isinstance(request, LanRequest):
        return _blocked(REASON_CONFIG_INVALID)
    if not request.config_valid:
        return _blocked(REASON_CONFIG_INVALID)

    requested = parse_requested_lan(request.requested_lan)
    if requested is not True:
        return _blocked(REASON_LAN_DISABLED)

    # Сеть запрошена — дальше проверяем, есть ли кому предъявить права.
    if not request.auth_enabled:
        return _blocked(REASON_AUTH_REQUIRED, normalize=True)
    if request.admin_check is AdminCheck.ABSENT:
        return _blocked(REASON_ADMIN_REQUIRED, normalize=True)
    if request.admin_check is not AdminCheck.PRESENT:
        return _blocked(REASON_ADMIN_CHECK_FAILED)

    return LanDecision(effective_lan_enabled=True, bind_scope=BindScope.NETWORK,
                       discovery_enabled=True, reason=REASON_LAN_ALLOWED,
                       should_normalize_config=False)


def can_enable(auth_enabled, admin_check):
    """Можно ли ПРЯМО СЕЙЧАС разрешить включение сети. -> (можно, причина).

    Та же логика, что и в decide, но без учёта текущего запрошенного значения: нужна
    обработчику настроек, чтобы отказать ДО записи конфигурации, и интерфейсу, чтобы
    объяснить, чего не хватает.
    """
    if not auth_enabled:
        return (False, REASON_AUTH_REQUIRED)
    if admin_check is AdminCheck.ABSENT:
        return (False, REASON_ADMIN_REQUIRED)
    if admin_check is not AdminCheck.PRESENT:
        return (False, REASON_ADMIN_CHECK_FAILED)
    return (True, REASON_LAN_ALLOWED)


def auth_disable_blocked(requested_lan, current_bind_scope):
    """Можно ли отключать авторизацию. -> True, если отключать НЕЛЬЗЯ.

    Запрещено в двух случаях:
      * процесс СЕЙЧАС слушает сеть — иначе выключение авторизации мгновенно открыло бы
        ферму всей локальной сети без единой проверки;
      * сеть запрошена в конфигурации, пусть текущий процесс и локальный, — иначе
        следующий запуск оказался бы в том же небезопасном сочетании.
    """
    if current_bind_scope is BindScope.NETWORK:
        return True
    return parse_requested_lan(requested_lan) is True
