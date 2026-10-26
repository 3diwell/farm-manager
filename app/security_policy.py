# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — политика браузерного Origin (Alpha 2.775).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, FastAPI,
SQLite и принтерные подсистемы — чтобы его можно было проверять офлайн-тестами без
запуска приложения и без рабочих данных.

ЗАЧЕМ. SPA обслуживается тем же FastAPI-приложением, то есть работает same-origin, и
wildcard CORS ей не нужен. Но CORS сам по себе НЕ мешает браузеру ОТПРАВИТЬ изменяющий
запрос — он лишь ограничивает чтение ответа. Поэтому чужую страницу, открытую в браузере
оператора, останавливает только серверная проверка Origin.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Это защита от браузерного drive-by, а НЕ замена авторизации.
Нативный клиент (слайсер, скрипт, curl) Origin не присылает и проверку проходит —
его должна ограничивать авторизация, а не эта политика.

ЗАГОЛОВКИ ПРОКСИ (X-Forwarded-For, X-Real-IP, Forwarded) здесь намеренно НЕ участвуют:
без явно настроенного доверенного reverse proxy они подделываются клиентом и источником
истины быть не могут.
"""

import ipaddress
from urllib.parse import urlsplit

# Методы, меняющие состояние. Для них Origin обязателен к проверке.
_MUTATING = frozenset(("POST", "PUT", "PATCH", "DELETE"))

# Порты по умолчанию: сравниваем ЭФФЕКТИВНЫЕ порты, иначе http://x и http://x:80
# считались бы разными источниками.
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def is_loopback_client(addr):
    """Alpha 2.778: действительно ли клиент пришёл с этого же компьютера.

    На вход подаётся ТОЛЬКО адрес из транспорта (request.client.host). Заголовки
    X-Forwarded-For, X-Real-IP, Forwarded и Host сюда не передаются и передаваться не
    должны: без явно настроенного доверенного reverse proxy они подделываются клиентом,
    и удалённый запрос притворился бы локальным.

    Разбор через ipaddress, без startswith и без DNS. Всё, что не разбирается как
    IP-адрес (имя хоста, строка 'localhost', мусор, None), считается НЕ локальным.
    Учитывается IPv4-mapped IPv6 (::ffff:127.0.0.1) — сам по себе он is_loopback=False.
    """
    s = str(addr or "").strip()
    if not s:
        return False
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]              # [::1] -> ::1
    if "%" in s:
        s = s.split("%", 1)[0]   # fe80::1%eth0 -> fe80::1 (zone index)
    try:
        ip = ipaddress.ip_address(s)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    try:
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            return bool(mapped.is_loopback)
    except Exception:
        pass
    return False


def is_mutating_method(method):
    """Меняет ли метод состояние (POST/PUT/PATCH/DELETE). Регистр не важен."""
    return str(method or "").strip().upper() in _MUTATING


def _effective_port(scheme, port):
    """Порт с подстановкой значения по умолчанию для схемы. None — схема неизвестна."""
    if port:
        try:
            return int(port)
        except Exception:
            return None
    return _DEFAULT_PORTS.get(str(scheme or "").lower())


def parse_origin(origin):
    """Разобрать заголовок Origin в (scheme, hostname, effective_port) или None.

    None означает «это не пригодный к сравнению источник»: пусто, 'null', мусор,
    несколько значений через пробел, userinfo (user:pass@host — классическая обманка),
    а также наличие пути/запроса/фрагмента (у настоящего Origin их не бывает).
    Разбор — стандартным urlsplit, никакого startswith по строкам.
    """
    s = str(origin or "").strip()
    if not s or s.lower() == "null":
        return None
    if any(ch.isspace() for ch in s):      # несколько Origin в одном заголовке
        return None
    try:
        u = urlsplit(s)
    except Exception:
        return None
    if u.scheme.lower() not in _DEFAULT_PORTS:
        return None
    if u.path or u.query or u.fragment:    # Origin — это строго scheme://host[:port]
        return None
    if u.username or u.password:           # http://127.0.0.1:8000@evil.example
        return None
    try:
        host = u.hostname                  # urlsplit сам снимает скобки IPv6 и приводит к нижнему регистру
        port = _effective_port(u.scheme, u.port)
    except Exception:
        return None
    if not host or port is None:
        return None
    return (u.scheme.lower(), host, port)


def parse_host_header(host_header, scheme):
    """Разобрать заголовок Host ('127.0.0.1:8000', '[::1]:8000', 'example.com')
    в (scheme, hostname, effective_port) или None. Схему берём из фактического запроса."""
    s = str(host_header or "").strip()
    if not s or any(ch.isspace() for ch in s):
        return None
    try:
        u = urlsplit("//" + s)             # '//' даёт urlsplit разобрать это как authority
        host = u.hostname
        port = _effective_port(scheme, u.port)
    except Exception:
        return None
    if not host or port is None:
        return None
    return (str(scheme or "").lower(), host, port)


def is_same_origin(origin, host_header, scheme):
    """Совпадает ли Origin с источником самого запроса по (scheme, hostname, port).

    Hostname сравнивается без учёта регистра (urlsplit уже привёл его к нижнему),
    порт — эффективный. Никакого префиксного/суффиксного сравнения строк:
    'localhost.evil.example' и 'localhost' — разные hostname, и точка.
    """
    o = parse_origin(origin)
    h = parse_host_header(host_header, scheme)
    if not o or not h:
        return False
    return o == h


def origin_allowed(origin, host_header, scheme, method):
    """Решение HTTP-гарда: пропускать ли запрос.

    1. Неизменяющий метод (GET/HEAD/OPTIONS) — пропускаем: ломать навигацию и статику
       нельзя, а прочитать ответ чужая страница всё равно не сможет (wildcard CORS снят).
    2. Origin отсутствует — пропускаем: так ходят слайсеры, нативные клиенты и
       внутренние интеграции. Их ограничивает авторизация, а не эта политика.
    3. Origin совпадает с источником запроса — пропускаем.
    4. Иначе (чужой источник, 'null', мусор) — отклоняем.
    """
    if not is_mutating_method(method):
        return True
    if origin is None or str(origin).strip() == "":
        return True
    return is_same_origin(origin, host_header, scheme)


# Alpha 2.779: транспортная схема сокета -> её HTTP-эквивалент.
# ЗАЧЕМ. ASGI-скоуп WebSocket даёт scheme "ws"/"wss" (именно это server.py передаёт как
# ws.url.scheme), а браузер в заголовке Origin присылает ВСЕГДА "http"/"https" — схемы
# "ws://" в Origin не бывает. Прямое сравнение ws != http отклоняло собственный интерфейс
# ещё до accept(), и SPA оставалась вообще без телеметрии (регрессия 2.775).
# Соответствие строгое и однозначное: ws — только с http, wss — только с https;
# понижение/повышение транспорта не допускается. Порты по умолчанию у пар совпадают
# (ws:80 / http:80, wss:443 / https:443), поэтому эффективный порт от нормализации
# не меняется и сравнение портов остаётся прежним.
_WS_TO_HTTP_SCHEME = {"ws": "http", "wss": "https"}


def _origin_scheme_for_transport(scheme):
    """HTTP-эквивалент транспортной схемы для сравнения с Origin.

    Не-WebSocket схемы возвращаются как есть, поэтому вызов с "http"/"https" ведёт
    себя в точности как раньше. Сопоставление — по точному ключу словаря, без
    startswith/суффиксов.
    """
    s = str(scheme or "").strip().lower()
    return _WS_TO_HTTP_SCHEME.get(s, s)


def ws_origin_allowed(origin, host_header, scheme):
    """Решение для WebSocket-рукопожатия. Обычный CORS его не защищает вовсе.

    Отсутствующий Origin допускается (нативные клиенты — как и для HTTP);
    любой присутствующий обязан точно совпасть с источником запроса.

    Alpha 2.779: транспортная схема приводится к HTTP-эквиваленту ДО сравнения —
    иначе собственный браузерный Origin не совпадал бы никогда. Сам разбор и строгое
    сравнение остаются ОБЩИМИ с HTTP-политикой (is_same_origin): hostname, эффективный
    порт и отказ для null/мусора/userinfo/пути не меняются. HTTP-гард не затронут.
    """
    if origin is None or str(origin).strip() == "":
        return True
    return is_same_origin(origin, host_header, _origin_scheme_for_transport(scheme))
