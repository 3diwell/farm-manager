# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""13.10.2026 — какой адрес показывать как «Адрес для других компьютеров».

ЗАЧЕМ. Владелец на приёмке 12.10.2026: в настройках доступа из сети программа показала адрес
виртуального адаптера VPN («happ-xray») вместо адреса Ethernet. Адрес брался «по маршруту в
интернет» (UDP-сокет к 8.8.8.8 и getsockname), а VPN в режиме TUN переводит этот маршрут на свой
адаптер. С других компьютеров фермы такой адрес не открывается.

КАК ТЕПЕРЬ. Адрес «по маршруту» остаётся, если он принадлежит ФИЗИЧЕСКОЙ сетевой карте (кабель,
Wi-Fi) — так у всех без VPN поведение прежнее. Иначе берётся адрес физической карты, у которой есть
шлюз, затем любой адрес физической карты. Физические карты Windows отдаёт командой
`Get-NetAdapter -Physical` — виртуальные (VPN-TUN, Hyper-V, WSL) в неё не попадают. Ничего не
удалось узнать — прежний адрес «по маршруту».

Выбор (choose) — чистая функция и проверяется без сети; опрос карт кэшируется на две минуты.
"""
import json
import subprocess
import sys
import threading
import time

_CACHE = {"at": 0.0, "adapters": None}
_LOCK = threading.Lock()
CACHE_S = 120.0

_PS = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$gw=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Select-Object -ExpandProperty InterfaceIndex);"
    "$o=@(foreach($a in (Get-NetAdapter -Physical | Where-Object Status -eq 'Up')){"
    "Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 | ForEach-Object {"
    "[pscustomobject]@{ip=$_.IPAddress;name=$a.Name;gw=($gw -contains $a.ifIndex)}}});"
    "ConvertTo-Json -InputObject $o -Compress"
)


def _usable(ip):
    ip = str(ip or "")
    return bool(ip) and not ip.startswith("127.") and not ip.startswith("169.254.") and ip != "0.0.0.0"


def choose(route_ip, adapters):
    """route_ip — адрес «по маршруту»; adapters — [{ip, name, gw}] физических карт или None
    (узнать не удалось). -> адрес для показа."""
    if not adapters:
        return route_ip
    phys = [a for a in adapters if isinstance(a, dict) and _usable(a.get("ip"))]
    if not phys:
        return route_ip
    if any(a.get("ip") == route_ip for a in phys):
        return route_ip
    with_gw = [a for a in phys if a.get("gw")]
    return (with_gw or phys)[0]["ip"]


def physical_adapters(timeout=6.0):
    """[{ip, name, gw}] физических карт в состоянии «подключено». Не Windows или ошибка -> None."""
    if not sys.platform.startswith("win"):
        return None
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=0x08000000)
        data = json.loads((r.stdout or "").strip() or "[]")
    except Exception:
        return None
    if isinstance(data, dict):
        data = [data]
    out = []
    for a in data if isinstance(data, list) else []:
        if isinstance(a, dict) and a.get("ip"):
            out.append({"ip": str(a.get("ip")), "name": str(a.get("name") or ""), "gw": bool(a.get("gw"))})
    return out


def _refresh():
    adapters = physical_adapters() or []
    with _LOCK:
        _CACHE["adapters"] = adapters
        _CACHE["at"] = time.monotonic()
        _CACHE["busy"] = False


def best(route_ip):
    """Адрес для показа. Опрос карт (около 2 с у PowerShell) идёт в фоне и не задерживает ни запуск,
    ни ответ: пока его нет, показывается адрес «по маршруту», как прежде."""
    now = time.monotonic()
    with _LOCK:
        stale = _CACHE["adapters"] is None or now - _CACHE["at"] > CACHE_S
        if stale and not _CACHE.get("busy"):
            _CACHE["busy"] = True
            threading.Thread(target=_refresh, name="lan-address", daemon=True).start()
        adapters = list(_CACHE["adapters"] or [])
    return choose(route_ip, adapters)
