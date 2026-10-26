# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — ключ интеграции для нативных callback слайсера (Alpha 2.781).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, веб-фреймворк,
СУБД и принтерные подсистемы, не обращается к сети и не пишет в журнал — чтобы его можно
было проверять офлайн-тестами без запуска приложения и без рабочих данных.

ЗАЧЕМ. Маршруты OctoPrint-приёма обходят обычный session-гейт: у нативного слайсера нет
сессии приложения. Значит нужен отдельный признак «этот запрос сделала настроенная
интеграция», не совпадающий ни с паролем пользователя, ни с сессией, ни с учётными данными
принтера, ни с админ-правами.

ПОЧЕМУ ИМЕННО X-Api-Key. Реальный отправитель — встроенный OctoPrint-клиент слайсера
(OrcaSlicer / PrusaSlicer / Bambu Studio, тип хоста OctoPrint). Он передаёт ключ в
заголовке X-Api-Key — это протокол, и произвольное имя заголовка такой клиент отправить не
может. Ключ при этом не попадает в адрес запроса: клиент строит адрес как http://хост/путь.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Это не сетевая авторизация и не замена входа в программу: ключ лишь
доказывает, что запрос сделала настроенная интеграция. Ограничение по адресу отправителя
(только этот компьютер) остаётся отдельным условием на стороне вызывающего.

ЧТО ХРАНИТСЯ. На сервере — ТОЛЬКО sha256 ключа. Сам ключ показывается администратору один
раз при создании и нигде не сохраняется: потерян — значит нужна замена, восстановить нельзя.
"""

import hashlib
import hmac
import re
import secrets

# Единственный принимаемый заголовок. Второго имени нет намеренно: чем меньше способов
# передать ключ, тем меньше шансов, что он утечёт не тем каналом.
HEADER_NAME = "X-Api-Key"

# 32 случайных байта -> 256 бит энтропии, представление token_urlsafe (43 символа).
TOKEN_BYTES = 32

# Потолок длины принимаемого значения. Проверяется ДО хеширования, чтобы огромное значение
# не заставляло сервер считать sha256 по мегабайтам.
MAX_TOKEN_LEN = 128
MIN_TOKEN_LEN = 32

# Формат задан явно, поэтому обрезка краёв не нужна и не делается: значение с пробелом
# внутри или по краям — это НЕ наш ключ, и «починить» его подгонкой было бы неверно.
_TOKEN_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z")

# Единственная причина отказа. Отсутствующий, неверный, отозванный и просроченный ключ
# обязаны выглядеть для вызывающего ОДИНАКОВО: разница подсказывала бы, что именно угадано.
REASON_DENIED = "callback_not_authorized"


def generate_token():
    """Новый ключ интеграции. Источник — secrets (CSPRNG), без привязки к имени машины,
    учётной записи, адресу или текущему моменту: предсказать значение нельзя."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw):
    """sha256-hex от ключа. Хранится только это; обратного преобразования нет."""
    return hashlib.sha256(str(raw or "").encode("utf-8")).hexdigest()


def _acceptable(value):
    """Похоже ли значение на наш ключ по формату. Дешёвая отбраковка ДО хеширования."""
    if not isinstance(value, str):
        return False
    if len(value) < MIN_TOKEN_LEN or len(value) > MAX_TOKEN_LEN:
        return False
    return bool(_TOKEN_RE.match(value))


def verify_token(value, stored_hash):
    """Совпадает ли предъявленный ключ с сохранённым отпечатком.

    Сравнение — hmac.compare_digest, за постоянное время: наивная проверка на равенство
    завершалась бы на первом несовпавшем символе и по времени ответа выдавала бы префикс.
    """
    stored = str(stored_hash or "")
    if not stored or not _acceptable(value):
        return False
    return hmac.compare_digest(hash_token(value), stored)


def _single_value(headers, name):
    """Ровно одно значение заголовка или None.

    Несколько значений (в том числе склеенных запятой, как их объединяет HTTP) считаются
    отказом: неоднозначность на границе доверия недопустима, и «выберем первое подходящее»
    превратило бы перебор в рабочую тактику.
    """
    if not headers:
        return None
    lowered = str(name).lower()
    found = None
    try:
        items = headers.items()
    except Exception:
        return None
    for k, v in items:
        if str(k).lower() != lowered:
            continue
        if found is not None:
            return None
        found = v
    if found is None:
        return None
    found = str(found)
    if "," in found:
        return None
    return found


def check_header(headers, stored_hash, enabled=True):
    """Решение для нативного callback по одному заголовку.

    -> (ok, reason). При отказе reason ВСЕГДА REASON_DENIED — вызывающему не сообщается,
    отсутствовал ключ, был неверным или отозван. Значение ключа не возвращается и не
    попадает в reason.
    """
    if not enabled:
        return (False, REASON_DENIED)
    value = _single_value(headers, HEADER_NAME)
    if value is None:
        return (False, REASON_DENIED)
    if not verify_token(value, stored_hash):
        return (False, REASON_DENIED)
    return (True, "")


def is_configured(stored_hash):
    """Настроена ли интеграция (есть сохранённый отпечаток ключа)."""
    return bool(str(stored_hash or "").strip())
