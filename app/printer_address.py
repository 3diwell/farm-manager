# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.10.2026 (R-020) — проверка адреса принтера ДО того, как по нему пойдёт связь.

ЗАЧЕМ. У двух принтеров Klipper на ферме в карточках записано «198.68.104» и «198.68.109» —
без последней части. Windows такую строку не отвергает, а молча достраивает (замер на компьютере
разработки 16.10.2026, getaddrinfo с AI_NUMERICHOST): «198.68.104» становится 198.68.0.104 —
публичным адресом в интернете. Документация Python о socket.inet_aton говорит то же самое: «also
accepts strings with less than three dots; see the Unix manual page inet(3)». В итоге опрос
принтера раз в пару секунд стучался на чужой узел в интернете, а у Bambu туда же ушёл бы код
доступа принтера (MQTT, имя «bblp»).

ПРАВИЛО. Строка только из цифр и точек — это ВСЕГДА адрес IPv4, именем узла она быть не может
(RFC 3696 §2: имя верхнего уровня не бывает из одних цифр). Поэтому её требуем полной: ровно
четыре числа от 0 до 255 через точку, без ведущих нулей — так её понимает модуль ipaddress.
Ведущие нули отвергаются намеренно: «192.168.1.010» inet_aton читает как восьмеричное …1.8.
Имя узла (k2plus.local) и IPv6 допускаются: проверить их без обращения к сети нельзя, и
это не наша дыра. Адрес из интернета (не из локальной сети) — только предупреждение, а не отказ:
бывают фермы, подключённые через VPN.

ЧИСТЫЙ МОДУЛЬ: только стандартная библиотека, ни сокетов, ни файлов — проверяется офлайн.
"""
import ipaddress
import re

#  Вердикты. Отказ — только SHORT и BAD; GLOBAL — предупреждение; EMPTY — адреса нет вовсе
#  (у виртуального принтера его и не бывает).
OK = "ok"
GLOBAL = "global"
SHORT = "short"
BAD = "bad"
EMPTY = "empty"
BLOCKING = frozenset((SHORT, BAD))

_NUMERIC_RE = re.compile(r"^[0-9.]+$")
#  Метка имени узла. Правило мягче RFC 1123: подчёркивание и буквы не латиницей не отвергаются —
#  задача проверки поймать неполный адрес, а не отказать работающему имени из сети владельца.
_LABEL_RE = re.compile(r"^[\w-]{1,63}$")


def check_printer_address(value):
    """Адрес принтера -> (вердикт, нормализованное значение).

    Вердикты: OK, GLOBAL (адрес из интернета — предупредить), SHORT (меньше четырёх чисел),
    BAD (так адрес не записывается), EMPTY (адреса нет). Нормализация — только обрезка пробелов
    по краям; сама строка не переписывается."""
    s = str(value if value is not None else "").strip()
    if not s:
        return EMPTY, ""
    if _NUMERIC_RE.match(s):
        parts = s.split(".")
        if len([x for x in parts if x]) < 4:
            return SHORT, s
        if len(parts) != 4:
            return BAD, s
        try:
            addr = ipaddress.IPv4Address(s)
        except ValueError:
            return BAD, s
        return (GLOBAL if addr.is_global else OK), s
    if ":" in s:
        try:
            addr = ipaddress.IPv6Address(s)
        except ValueError:
            return BAD, s
        return (GLOBAL if addr.is_global else OK), s
    host = s[:-1] if s.endswith(".") else s
    if not host or len(host) > 253:
        return BAD, s
    labels = host.split(".")
    if not all(_LABEL_RE.match(x) for x in labels):
        return BAD, s
    if len(labels) > 1 and labels[-1].isdigit():
        return BAD, s            # RFC 3696 §2: последняя часть имени из одних цифр не бывает
    return OK, s


def is_blocking(verdict):
    """Принять такой адрес нельзя: связь по нему уйдёт не туда или не уйдёт вовсе."""
    return verdict in BLOCKING


def address_problem(ip, ptype=""):
    """Для карточки принтера: 'short' / 'bad' либо None. Виртуальному принтеру адрес не нужен."""
    if str(ptype or "").strip().lower() == "demo":
        return None
    verdict, _ = check_printer_address(ip)
    return verdict if verdict in BLOCKING else None


def describe(verdict, ip, lang="ru"):
    """Текст для владельца: что не так с адресом. Пусто — если всё в порядке."""
    shown = str(ip if ip is not None else "").strip()[:64]
    ru = (lang or "ru") == "ru"
    if verdict == SHORT:
        return ("Неполный адрес %s: нужно 4 числа через точку" % shown) if ru else \
               ("Incomplete address %s: four numbers separated by dots are needed" % shown)
    if verdict == BAD:
        return ("Неверный адрес %s: нужно 4 числа от 0 до 255 через точку или имя принтера в сети" % shown) if ru else \
               ("Invalid address %s: four numbers 0-255 separated by dots or the printer's network name are needed" % shown)
    if verdict == GLOBAL:
        return ("Адрес %s не из локальной сети" % shown) if ru else \
               ("Address %s is not on the local network" % shown)
    return ""
