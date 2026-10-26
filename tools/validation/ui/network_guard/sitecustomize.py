# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 3B — сторож исходящих соединений ТОЛЬКО для E2E-подпроцесса.

ЗАЧЕМ. Журнал сети в браузере доказывает лишь то, что никуда не ходила СТРАНИЦА. Он ничего
не говорит про сам Python-backend: опрос принтеров, MQTT, FTPS и обнаружение живут в
серверном процессе. Официальные выключатели FM_E2E_* обещают их выключить — но обещание не
доказательство. Этот модуль превращает обещание в проверяемый факт: любое соединение за
пределы петли блокируется ДО выполнения и попадает в журнал.

КАК ВКЛЮЧАЕТСЯ. Python сам импортирует `sitecustomize` при старте, если находит его на
`sys.path`. Каталог подкладывается только запускаемому E2E-серверу через `PYTHONPATH`.
Никакой глобальный Python не изменяется, обычный Farm Manager этот файл не видит.

ПРЕДОХРАНИТЕЛЬ. Без переменных `FM_UI_GUARD_LOG` и `FM_UI_GUARD_SENTINEL` модуль не делает
НИЧЕГО. Даже если каталог случайно окажется в PYTHONPATH рабочей программы, она продолжит
работать как обычно: подменить сеть работающей ферме подкладыванием пути нельзя.

ЧТО ПИШЕТ. Только время, PID, имя хоста, порт, решение и причину. Ни байта передаваемых
данных, ни учётных записей, ни ключей.
"""
import json
import os
import socket
import sys
import threading
import time

_LOG = os.environ.get("FM_UI_GUARD_LOG") or ""
_SENTINEL = os.environ.get("FM_UI_GUARD_SENTINEL") or ""

# Петля — и только она. Имя `localhost` разрешено потому, что резолвится в петлю; всё
# остальное считается внешним, включая адреса локальной сети фермы.
_ALLOWED_HOSTS = frozenset(("127.0.0.1", "::1", "localhost", "ip6-localhost",
                            "0.0.0.0", "::"))
_LOCK = threading.Lock()


def _is_loopback(host):
    h = str(host or "").strip().strip("[]").lower()
    if h in _ALLOWED_HOSTS:
        return True
    if h.startswith("127."):                       # вся сеть 127.0.0.0/8
        parts = h.split(".")
        if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            return True
    if h.startswith("::ffff:127."):                # IPv4-mapped петля
        return True
    return False


def _write(entry):
    if not _LOG:
        return
    try:
        with _LOCK:
            with open(_LOG, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass                                        # журнал не имеет права ронять сервер


def _record(kind, host, port, allowed, reason):
    _write({"ts": round(time.time(), 3), "pid": os.getpid(), "kind": kind,
            "host": str(host)[:120], "port": port, "allowed": bool(allowed),
            "reason": reason})


def _classify(addr, kind):
    """(разрешено, host, port, причина). Неразобранный адрес безопасным НЕ считается."""
    if isinstance(addr, tuple) and addr:
        host, port = addr[0], (addr[1] if len(addr) > 1 else None)
        if _is_loopback(host):
            return True, host, port, "loopback"
        return False, host, port, "не петля: соединение за пределы 127.0.0.1 запрещено"
    return False, repr(addr)[:80], None, "адрес не разобран — недоказанное считается внешним"


def _install():
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto
    real_getaddrinfo = socket.getaddrinfo

    def connect(self, addr, *a, **kw):
        ok, host, port, why = _classify(addr, "connect")
        _record("connect", host, port, ok, why)
        if not ok:
            raise OSError("FM_UI_GUARD: исходящее соединение запрещено (%s:%s)" % (host, port))
        return real_connect(self, addr, *a, **kw)

    def connect_ex(self, addr, *a, **kw):
        ok, host, port, why = _classify(addr, "connect_ex")
        _record("connect_ex", host, port, ok, why)
        if not ok:
            return 10013                            # WSAEACCES: отказано в доступе
        return real_connect_ex(self, addr, *a, **kw)

    def sendto(self, data, *a, **kw):
        addr = a[-1] if a else kw.get("address")
        ok, host, port, why = _classify(addr, "sendto")
        if not ok:
            _record("sendto", host, port, False, why)
            raise OSError("FM_UI_GUARD: датаграмма наружу запрещена (%s:%s)" % (host, port))
        return real_sendto(self, data, *a, **kw)

    def getaddrinfo(host, port, *a, **kw):
        # Резолвинг сам по себе соединением не является, но чужое имя здесь — уже намерение.
        # Не блокируем (это сломало бы разбор адресов), а фиксируем: connect всё равно не пройдёт.
        if not _is_loopback(host):
            _record("getaddrinfo", host, port, True, "разрешение имени; соединение всё равно "
                                                     "будет заблокировано на connect")
        return real_getaddrinfo(host, port, *a, **kw)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto
    socket.getaddrinfo = getaddrinfo


if _LOG and _SENTINEL:
    try:
        _install()
        payload = {"pid": os.getpid(), "ts": round(time.time(), 3),
                   "python": sys.version.split()[0],
                   "guard": "fm-ui-network-guard-v1",
                   "allowed": sorted(_ALLOWED_HOSTS)}
        # Первый процесс создаёт удостоверение, остальные дописывают свои PID отдельной строкой.
        if not os.path.exists(_SENTINEL):
            with open(_SENTINEL, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(payload, fh, ensure_ascii=False)
        _record("guard_loaded", "-", None, True, "сторож установлен в процессе %d" % os.getpid())
    except Exception as e:                          # сторож не имеет права ронять запуск
        _write({"ts": round(time.time(), 3), "pid": os.getpid(), "kind": "guard_error",
                "host": "-", "port": None, "allowed": False, "reason": str(e)[:200]})
