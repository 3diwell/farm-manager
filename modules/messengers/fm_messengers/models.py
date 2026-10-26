# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Общие типы модуля уведомлений. Только стандартная библиотека."""
import re

# ── Причины результата: безопасный словарь, который можно отдавать в интерфейс ────────────
REASON_OK = "ok"
REASON_DISABLED = "disabled"
REASON_NOT_CONFIGURED = "not_configured"
REASON_BAD_REQUEST = "bad_request"
REASON_BAD_TOKEN = "bad_token"
REASON_NO_PERMISSION = "no_permission"
#  У сообщества ВКонтакте выключены сообщения (код 912). Отдельно от «нет прав»: чинится
#  не пересозданием ключа, а одной галочкой в настройках сообщества.
REASON_MESSAGES_OFF = "messages_off"
REASON_BAD_RECIPIENT = "bad_recipient"
REASON_RECIPIENT_NOT_ALLOWED = "recipient_not_allowed"
REASON_TOO_LONG = "too_long"
REASON_RATE_LIMITED = "rate_limited"
REASON_NETWORK = "network"
REASON_PLATFORM_ERROR = "platform_error"
REASON_BAD_RESPONSE = "bad_response"
REASON_UNKNOWN_KIND = "unknown_kind"
SAFE_REASONS = frozenset((
    REASON_OK, REASON_DISABLED, REASON_NOT_CONFIGURED, REASON_BAD_REQUEST, REASON_BAD_TOKEN,
    REASON_NO_PERMISSION, REASON_MESSAGES_OFF, REASON_BAD_RECIPIENT, REASON_RECIPIENT_NOT_ALLOWED,
    REASON_TOO_LONG,
    REASON_RATE_LIMITED, REASON_NETWORK, REASON_PLATFORM_ERROR, REASON_BAD_RESPONSE,
    REASON_UNKNOWN_KIND,
))

# ── События фермы ─────────────────────────────────────────────────────────────────────────
EVENT_PRINT_FINISHED = "print_finished"
EVENT_PRINT_FAILED = "print_failed"
EVENT_PRINT_CANCELLED = "print_cancelled"
EVENT_PRINTER_ERROR = "printer_error"
EVENT_PRINTER_NOTICE = "printer_notice"
EVENT_PRINTER_OFFLINE = "printer_offline"
EVENT_TEST = "test"
EVENT_KEYS = (EVENT_PRINT_FINISHED, EVENT_PRINT_FAILED, EVENT_PRINT_CANCELLED,
              EVENT_PRINTER_ERROR, EVENT_PRINTER_NOTICE, EVENT_PRINTER_OFFLINE)
EVENT_DEFAULTS = {
    EVENT_PRINT_FINISHED: True, EVENT_PRINT_FAILED: True, EVENT_PRINT_CANCELLED: False,
    EVENT_PRINTER_ERROR: True, EVENT_PRINTER_NOTICE: True, EVENT_PRINTER_OFFLINE: False,
}

DETAIL_LIMIT = 200
#  «Нет связи» шлём, только если связи нет столько секунд подряд (сервис и шаблоны).
OFFLINE_AFTER_S = 180
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")


def clip_detail(text, secrets=(), limit=DETAIL_LIMIT):
    """Короткая безопасная строка: без управляющих символов и секретов, не длиннее limit.
    Секреты вычищаются ДО обрезки — обрезанный ключ всё равно ключ."""
    t = str(text or "")
    for s in secrets or ():
        s = str(s or "")
        if len(s) >= 4:
            t = t.replace(s, "***")
    t = _CTRL.sub(" ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if len(t) > limit:
        t = t[:limit - 1] + "…"
    return t


class SendResult(object):
    __slots__ = ("ok", "reason", "detail", "http_status", "message_id")

    def __init__(self, ok, reason, detail="", http_status=None, message_id=None):
        self.ok = bool(ok)
        self.reason = reason if reason in SAFE_REASONS else REASON_PLATFORM_ERROR
        self.detail = clip_detail(detail)
        self.http_status = http_status
        self.message_id = message_id

    def as_dict(self):
        return {"ok": self.ok, "reason": self.reason, "detail": self.detail,
                "http_status": self.http_status, "message_id": self.message_id}

    def __repr__(self):
        return "SendResult(ok=%r, reason=%r, detail=%r)" % (self.ok, self.reason, self.detail)


class HttpRequest(object):
    """Готовый запрос. secrets — что вычищать из текста любой ошибки (у Telegram ключ стоит
    прямо в адресе, и упасть он может вместе с адресом)."""
    __slots__ = ("method", "url", "headers", "body", "timeout", "secrets")

    def __init__(self, method, url, headers=None, body=None, timeout=15.0, secrets=()):
        self.method = method
        self.url = url
        self.headers = dict(headers or {})
        self.body = body
        self.timeout = float(timeout)
        self.secrets = tuple(secrets or ())


class FieldSpec(object):
    """Поле настроек площадки. secret — ключ (не показывается), info — служебное значение,
    которое заполняет мастер подключения (имя бота, название чата), а не человек."""
    __slots__ = ("key", "secret", "required", "label", "hint", "placeholder", "max_len", "info")

    def __init__(self, key, label=None, hint=None, secret=False, required=True, placeholder="",
                 max_len=512, info=False):
        self.key = key
        self.label = dict(label or {})
        self.hint = dict(hint or {})
        self.secret = bool(secret)
        self.required = bool(required)
        self.placeholder = placeholder
        self.max_len = int(max_len)
        self.info = bool(info)

    def as_dict(self, lang):
        L = "ru" if lang != "en" else "en"
        return {"key": self.key, "secret": self.secret, "required": self.required, "info": self.info,
                "label": self.label.get(L) or self.label.get("en") or self.key,
                "hint": self.hint.get(L) or self.hint.get("en") or "",
                "placeholder": self.placeholder, "max_len": self.max_len}
