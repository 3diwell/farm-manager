# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — атрибуты cookie сессии (Alpha 2.790).

ЧИСТЫЙ модуль: только стандартная библиотека, без фреймворка, БД, сети и журнала. Ничего
не устанавливает сам — возвращает НАБОР АТРИБУТОВ, который вызывающий передаёт в
set_cookie/delete_cookie. Смысл в том, чтобы атрибуты задавались в проекте В ОДНОМ месте:
до 2.790 они дублировались в трёх обработчиках, и рассинхронизация установки с удалением
означала бы, что cookie при выходе не удаляется, а остаётся в браузере.

ПОЧЕМУ Secure НЕ ВКЛЮЧЁН ЖЁСТКО. Программа работает по http://localhost. Атрибут Secure
запрещает браузеру отправлять cookie по обычному HTTP — включив его безусловно, мы просто
сломали бы вход. Поэтому Secure выставляется ТОЛЬКО когда соединение действительно
защищённое, и признак берётся из схемы ASGI, а не из заголовка X-Forwarded-Proto:
заголовок подделывается клиентом, и доверие к нему означало бы, что чужой запрос может
заставить нас пометить cookie как защищённую там, где защиты нет. Отсутствие HTTPS — это
ограничение развёртывания, а не дефект, который чинится этим флагом.

SameSite=Lax, а не None и не Strict. None потребовал бы Secure и открыл бы cookie
межсайтовым POST. Strict ломает переходы по ссылке в уже открытую программу. Lax —
существующее поведение проекта, оно и сохраняется.
"""

# Имя cookie не меняется: смена имени разлогинила бы все активные браузеры разом.
COOKIE_NAME = "fm_session"

SAMESITE = "lax"
PATH = "/"
# Domain намеренно НЕ задаётся: без него cookie привязана к конкретному хосту. Указание
# домена расширило бы её на поддомены — это ослабление, а не настройка.
DOMAIN = None

SECURE_SCHEMES = frozenset(("https", "wss"))


def is_secure_scheme(scheme):
    """Действительно ли соединение защищённое. На вход — схема из транспорта ASGI."""
    return str(scheme or "").strip().lower() in SECURE_SCHEMES


def set_attrs(scheme, max_age=None):
    """Атрибуты для установки cookie сессии.

    max_age=None -> cookie сеанса браузера; число -> срок жизни в секундах. Значение
    согласуется вызывающим с серверным сроком простоя сессии: cookie, живущая дольше
    серверной записи, создаёт ложное впечатление входа.
    """
    attrs = {
        "httponly": True,          # JavaScript не должен читать токен сессии
        "samesite": SAMESITE,
        "path": PATH,
        "secure": is_secure_scheme(scheme),
    }
    if DOMAIN is not None:
        attrs["domain"] = DOMAIN
    if max_age is not None:
        attrs["max_age"] = int(max_age)
    return attrs


def delete_attrs(scheme):
    """Атрибуты для удаления cookie.

    Браузер удалит cookie только если path, domain и (для части браузеров) samesite/secure
    совпадают с теми, с которыми она была установлена. Поэтому набор строится тем же
    модулем, а не повторяется руками в обработчике выхода.
    """
    attrs = {
        "path": PATH,
        "httponly": True,
        "samesite": SAMESITE,
        "secure": is_secure_scheme(scheme),
    }
    if DOMAIN is not None:
        attrs["domain"] = DOMAIN
    return attrs
