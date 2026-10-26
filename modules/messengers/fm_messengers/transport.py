# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""HTTP-доставка запроса площадке. Единственное место модуля, где есть сеть.

Ошибка HTTP (4xx/5xx) — НЕ исключение: тело ответа возвращается провайдеру, он умеет его
читать. Исключение — только отсутствие ответа: нет связи, таймаут, DNS, TLS. Текст такой
ошибки вычищается от секретов запроса.
"""
import socket
import urllib.error
import urllib.request

from . import models as M

MAX_BODY = 256 * 1024
USER_AGENT = "3DIWELL-FarmManager-messengers"


class TransportError(Exception):
    def __init__(self, detail):
        Exception.__init__(self, detail)
        self.detail = detail


def http_send(req):
    """HttpRequest -> (status, body_bytes). Бросает TransportError, если ответа не было."""
    headers = dict(req.headers or {})
    headers.setdefault("User-Agent", USER_AGENT)
    r = urllib.request.Request(req.url, data=req.body, headers=headers, method=req.method)
    try:
        with urllib.request.urlopen(r, timeout=req.timeout) as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read(MAX_BODY)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_BODY)
        except Exception:
            body = b""
        return int(e.code), body
    except (urllib.error.URLError, socket.timeout, OSError, ValueError) as e:
        raise TransportError(M.clip_detail("%s: %s" % (type(e).__name__, e), req.secrets))
