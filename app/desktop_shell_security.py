# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — политика безопасности desktop-оболочки (Alpha 2.805).

ТОЛЬКО стандартная библиотека. Чистые функции без ввода-вывода: валидация адреса
сервера, канонический origin, решение по навигации WebView, распознавание ответа
Farm Manager, разбор discovery-ответа. Всё тестируется offline.

ГЛАВНОЕ. Оболочка НЕ является границей безопасности: auth/origin/capabilities/
permissions проверяет backend. Здесь решается только, какие НАВИГАЦИИ разрешены
внутри окна (свой origin), какие уходят в системный браузер (внешние http/https,
mailto) и какие блокируются (file:, javascript:, data:, vbscript:, UNC и прочее).
"""

import ipaddress
import json
import re
from urllib.parse import urlsplit

# Разрешённые схемы ВНУТРИ окна. Всё прочее (file, javascript, data, vbscript, about,
# blob-вне-origin, ms-appx, произвольные кастомные схемы) в top-level не разрешается.
_INTERNAL_SCHEMES = ("http", "https")

# Схемы, которые открываются ВНЕШНИМ приложением (не в WebView).
_EXTERNAL_APP_SCHEMES = ("mailto",)

#  25.10.2026: программа перешла с «Alpha 3.0» на «Beta 3.71». Ответ /version узнаётся по паре
#  чисел с любым из двух префиксов выпуска: окно и клиент Beta узнают сервер Alpha, и наоборот
#  с этой правки. Клиенты Alpha 3.0, уже стоящие у пользователей, принимали только «Alpha».
VERSION_RE = re.compile(r"^(?:Alpha|Beta) \d+\.\d+$")

DISCOVERY_MAGIC = b"3DIWELL_DISCOVER_v1"      # существующий протокол server.py (не менять)
DISCOVERY_REPLY = b"3DIWELL_SERVER_v1"
DISCOVERY_PORT = 8021

# Фиктивный командный host страниц оболочки (zero-bridge вместо privileged js-моста).
# .invalid — зарезервированная RFC 2606 зона: в сеть такой запрос уйти не может, а
# NavigationStarting отменяет его ещё раньше. Команды принимаются ТОЛЬКО со страниц
# самой оболочки (пока origin сервера не выбран) — это решает вызывающая сторона.
SHELL_CMD_HOST = "fmshell.invalid"
SHELL_CMD_ORIGIN = "http://" + SHELL_CMD_HOST
SHELL_CMD_ACTIONS = ("retry", "browser", "close", "change-server", "discover",
                     "open-browser", "connect", "toggle-fullscreen")
# Действия, разрешённые С ЛЮБОЙ страницы (включая страницы сервера): только безвредные
# оконные операции. Всё остальное — только со страниц самой оболочки.
SHELL_CMD_ANY_PAGE = frozenset({"toggle-fullscreen"})


def parse_shell_command(url):
    """Командный URL оболочки -> (action, params) либо None. Неизвестное действие — None
    (команда не исполняется). Параметры — только строки из query."""
    try:
        u = urlsplit(str(url or ""))
    except Exception:
        return None
    if u.scheme not in _INTERNAL_SCHEMES or (u.hostname or "").lower() != SHELL_CMD_HOST:
        return None
    action = (u.path or "").strip("/")
    if action not in SHELL_CMD_ACTIONS:
        return None
    from urllib.parse import parse_qsl
    params = {k: v for k, v in parse_qsl(u.query, keep_blank_values=True)}
    return (action, params)


# ── адрес сервера ─────────────────────────────────────────────────────────────

def normalize_server_url(raw, default_scheme="http"):
    """Пользовательский ввод -> канонический origin `scheme://host[:port]`.
    -> (origin, "") либо ("", код ошибки). Правила:
      * схемы только http/https (по умолчанию http);
      * credentials в URL запрещены;
      * query/fragment запрещены (fragment не является адресом сервера);
      * путь допускается только пустой или '/';
      * host: IPv4, IPv6 (в скобках), hostname; UNC/файловые пути запрещены;
      * порт явный 1..65535 либо дефолт схемы (в origin не дописывается)."""
    s = str(raw or "").strip()
    if not s:
        return ("", "empty")
    if "\\" in s:
        return ("", "invalid_url")                      # UNC/файловый путь адресом не является
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", s):
        scheme = s.split("://", 1)[0].lower()
        if scheme not in _INTERNAL_SCHEMES:
            return ("", "bad_scheme")                   # javascript:/file:/data: и т.п.
    else:
        s = "%s://%s" % (default_scheme, s)
    try:
        u = urlsplit(s)
    except Exception:
        return ("", "invalid_url")
    if u.scheme not in _INTERNAL_SCHEMES:
        return ("", "bad_scheme")
    if u.username is not None or u.password is not None:
        return ("", "credentials_in_url")
    if u.query:
        return ("", "query_not_allowed")
    if u.fragment:
        return ("", "fragment_not_allowed")
    if u.path not in ("", "/"):
        return ("", "path_not_allowed")
    host = (u.hostname or "").strip()
    if not host:
        return ("", "no_host")
    try:
        port = u.port                                    # ValueError на мусорном порте
    except ValueError:
        return ("", "bad_port")
    if port is not None and not (1 <= int(port) <= 65535):
        return ("", "bad_port")
    # host: IPv6 -> в скобках; IPv4/hostname -> как есть (lowercase)
    try:
        ip = ipaddress.ip_address(host)
        host_out = ("[%s]" % ip.compressed) if ip.version == 6 else ip.compressed
    except ValueError:
        if not re.match(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$", host):
            return ("", "bad_host")
        host_out = host.lower()
    origin = "%s://%s" % (u.scheme, host_out)
    if port is not None and port != (80 if u.scheme == "http" else 443):
        origin += ":%d" % int(port)
    return (origin, "")


def origin_of(url):
    """Канонический origin URL для сравнения «свой/чужой»: (scheme, host, effective_port).
    Дефолтные порты нормализуются, host — lowercase. None — не http(s) или мусор."""
    try:
        u = urlsplit(str(url or ""))
    except Exception:
        return None
    if u.scheme not in _INTERNAL_SCHEMES or not u.hostname:
        return None
    try:
        port = u.port
    except ValueError:
        return None
    if port is None:
        port = 80 if u.scheme == "http" else 443
    return (u.scheme, u.hostname.lower(), int(port))


def origin_port(url):
    """Порт адреса (для человекочитаемых сообщений «проверены порты: …»). 0 — не разобрали.

    Alpha 2.812: наружу пользователю показываем ТОЛЬКО номера портов — ни путей, ни команд,
    ни адреса файла настроек."""
    o = origin_of(url)
    return int(o[2]) if o else 0


def same_origin(url, allowed_origin):
    """URL принадлежит разрешённому origin (точное сравнение scheme+host+port).
    `localhost` и `127.0.0.1` — РАЗНЫЕ origin (не считаем другим доверенным сервером
    без явной нормализации адреса при подключении)."""
    a, b = origin_of(url), origin_of(allowed_origin)
    return a is not None and b is not None and a == b


def navigation_decision(url, allowed_origin):
    """Решение по top-level навигации внутри WebView.
    -> ("allow" | "external" | "external_app" | "block", причина)."""
    s = str(url or "").strip()
    if not s:
        return ("block", "empty_url")
    low = s.lower()
    if low.startswith("about:blank"):
        return ("allow", "about_blank")               # служебная пустая страница WebView2
    if low.startswith("data:text/html") and allowed_origin == "":
        # локальные страницы самой оболочки (запуск/подключение) до выбора сервера
        return ("allow", "shell_page")
    scheme = low.split(":", 1)[0] if ":" in low else ""
    if s.startswith("\\\\") or re.match(r"^[a-z]:[\\/]", low):
        return ("block", "filesystem_path")           # UNC/локальный путь
    if scheme in _EXTERNAL_APP_SCHEMES:
        return ("external_app", "mailto")
    if scheme not in _INTERNAL_SCHEMES:
        return ("block", "scheme_" + (scheme or "none"))   # file/javascript/data/vbscript/…
    if parse_shell_command(s) is not None or SHELL_CMD_HOST in low.split("/", 3)[2:3]:
        return ("block", "shell_command_host")        # командный host НЕ уходит ни в окно, ни в браузер
    if allowed_origin and same_origin(s, allowed_origin):
        return ("allow", "same_origin")
    return ("external", "foreign_http")               # чужой http(s) -> системный браузер


# ── распознавание Farm Manager ────────────────────────────────────────────────

def is_farm_manager_version_payload(text):
    """Тело GET /version действительно от Farm Manager: JSON {"version": "Alpha N.NNN"} или
    {"version": "Beta N.NNN"}."""
    try:
        data = json.loads(str(text or ""))
    except Exception:
        return False
    return isinstance(data, dict) and bool(VERSION_RE.match(str(data.get("version") or "")))


def classify_probe(status, body_text):
    """Классификация ответа /version: открытый порт ещё не значит Farm Manager.
    -> "ready" (наш сервер, доступ открыт) | "auth" (наш сервер, требуется вход) |
       "foreign" (посторонний HTTP-сервер)."""
    if status == 200 and is_farm_manager_version_payload(body_text):
        return "ready"
    if status in (401, 403):
        try:
            data = json.loads(str(body_text or ""))
        except Exception:
            return "foreign"
        # формат отказа гейта Farm Manager: {"error": "unauthorized"/"forbidden"}
        if isinstance(data, dict) and data.get("error") in ("unauthorized", "forbidden"):
            return "auth"
    return "foreign"


def parse_discovery_reply(data, addr_ip):
    """Разбор UDP-ответа `3DIWELL_SERVER_v1|<port>|<имя>` от существующего маяка server.py.
    -> {"ip","port","name"} либо None. Имя обрезается и чистится (в UI попадает только
    безопасный короткий текст)."""
    try:
        raw = bytes(data or b"")
        if not raw.startswith(DISCOVERY_REPLY + b"|"):
            return None
        parts = raw.decode("utf-8", "replace").split("|")
        port = int(parts[1])
        if not (1 <= port <= 65535):
            return None
        name = re.sub(r"[\x00-\x1f<>\"']", "", parts[2] if len(parts) > 2 else "").strip()[:48]
        ipaddress.ip_address(str(addr_ip))
        return {"ip": str(addr_ip), "port": port, "name": name or "3DIWELL Farm"}
    except Exception:
        return None
