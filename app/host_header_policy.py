# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — политика заголовка Host при выключенном входе (R-124, Alpha 3.0).

ЧИСТЫЙ модуль: только стандартная библиотека. НЕ импортирует server.py, FastAPI,
SQLite и сеть — его проверяют офлайн-тестами без запуска программы. Имена компьютера
сюда ПЕРЕДАЮТСЯ, а не собираются: разрешать имена через DNS здесь нельзя.

ОТ ЧЕГО ЗАЩИЩАЕТ. Подмена DNS (DNS rebinding): чужой сайт evil.example отдаёт браузеру
адрес 127.0.0.1. Страница evil.example тогда обращается к программе на этом компьютере,
а браузер присылает Origin=http://evil.example:8000 и Host=evil.example:8000 — они
совпадают, и проверка Origin (app/security_policy.py) считает страницу «своей». При
выключенном входе больше ничего её не останавливает.

ПОЧЕМУ ТОЛЬКО ПРИ ВЫКЛЮЧЕННОМ ВХОДЕ. Без входа программа слушает только этот компьютер
(app/lan_access_policy.decide), и законно к ней обращаются лишь по его адресам:
localhost (трей, восстановление, слайсер), 127.0.0.1 (окно программы). При включённом
входе у подменённого имени нет cookie сессии, а другие компьютеры фермы и телефон
ходят по IP или по имени из своей сети — их эта проверка не касается.

ЧТО ПРОПУСКАЕТСЯ при выключенном входе:
  * любой IP-адрес (IPv4 и IPv6, в том числе 0.0.0.0 и адреса сети): подменить DNS
    для адреса нельзя, а проброс порта по IP продолжает работать;
  * 'localhost' и '*.localhost' (RFC 6761: браузер разрешает их сам, внешний DNS не
    участвует, зарегистрировать такое имя нельзя);
  * точные имена этого компьютера из переданного списка (и они же с '.local');
  * отсутствующий или пустой Host: браузер без Host запрос не отправит.
Всё остальное — отказ с машинным кодом причины. Подстановок вида '<имя>.*' нет.
"""

import ipaddress

from app import security_policy as _sp

# Коды решения (машинные, без имён и адресов — их нельзя возвращать в ответ).
OK_AUTH_ENABLED = "auth_enabled"
OK_NO_HOST = "no_host"
OK_IP = "ip_address"
OK_LOCALHOST = "localhost"
OK_LOCAL_NAME = "local_name"
DENY_MALFORMED = "host_malformed"
DENY_NAME = "host_not_local"

# Символы, которых в настоящем Host не бывает: userinfo, путь, запрос, фрагмент.
_FORBIDDEN_CHARS = frozenset("@/\\?#")


def _norm_name(name):
    """Имя в нижнем регистре, без завершающей точки. Пустое -> ''."""
    s = str(name or "").strip().lower()
    while s.endswith("."):
        s = s[:-1]
    return s


def _punycode(name):
    """ASCII-форма имени для сравнения с тем, что пришлёт браузер. Ошибка -> None."""
    try:
        return name.encode("idna").decode("ascii").lower()
    except Exception:
        return None


def local_machine_names(raw_names):
    """Множество имён этого компьютера для сравнения с Host.

    На вход — сырые имена (socket.gethostname(), COMPUTERNAME). Для каждого берётся
    нижний регистр без завершающей точки, его punycode (кириллическое имя браузер
    присылает в виде xn--...) и оба варианта с суффиксом '.local'. Пустые, с пробелами
    и похожие на IP-адрес строки пропускаются: адреса и так проходят своим правилом.
    """
    out = set()
    for raw in raw_names or ():
        n = _norm_name(raw)
        if not n or any(ch.isspace() for ch in n) or any(ch in _FORBIDDEN_CHARS for ch in n):
            continue
        variants = {n}
        p = _punycode(n)
        if p:
            variants.add(p)
        for v in list(variants):
            if v.endswith(".local"):
                continue
            variants.add(v + ".local")
        out.update(variants)
    return frozenset(out)


def _is_ip(host):
    h = host
    if "%" in h:
        h = h.split("%", 1)[0]          # fe80::1%eth0 — индекс зоны
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def host_allowed(host_header, scheme, *, auth_enabled, local_names=()):
    """Решение: пропускать ли запрос с таким Host. Возвращает (bool, код_причины).

    auth_enabled читается вызывающим на КАЖДЫЙ запрос: вход могут включить и выключить
    на ходу, и решение обязано меняться со следующего же запроса.
    """
    if auth_enabled:
        return True, OK_AUTH_ENABLED
    if host_header is None:
        return True, OK_NO_HOST
    raw = str(host_header)
    if raw.strip() == "":
        return True, OK_NO_HOST
    s = raw.strip()
    if any(ch.isspace() for ch in s) or any(ch in _FORBIDDEN_CHARS for ch in s):
        return False, DENY_MALFORMED
    parsed = _sp.parse_host_header(s, scheme or "http")
    if not parsed:
        return False, DENY_MALFORMED
    host = _norm_name(parsed[1])
    if not host:
        return False, DENY_MALFORMED
    if _is_ip(host):
        return True, OK_IP
    if host == "localhost" or host.endswith(".localhost"):
        return True, OK_LOCALHOST
    names = local_names if isinstance(local_names, (set, frozenset)) else local_machine_names(local_names)
    if host in names:
        return True, OK_LOCAL_NAME
    if not host.isascii():
        p = _punycode(host)
        if p and p in names:
            return True, OK_LOCAL_NAME
    return False, DENY_NAME


def refusal_text(port):
    """Текст отказа для человека: по-русски и по-английски. Host запроса в текст НЕ
    подставляется — иначе чужой сайт управлял бы содержимым нашего ответа."""
    try:
        p = int(port)
    except Exception:
        p = 8000
    url = "http://localhost:%d" % p
    return (
        "Адрес не разрешён. Защита входа выключена, поэтому программа открывается только "
        "по адресу этого компьютера. Откройте %s или включите «Доступ и аудит» "
        "в настройках программы.\n\n"
        "This address is not allowed. Sign-in protection is off, so the program opens only "
        "at this computer's address. Open %s or turn on Access and audit in the "
        "program settings.\n" % (url, url)
    )
