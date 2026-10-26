# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Интерфейс площадки-провайдера.

Провайдер — ЧИСТЫЙ объект: получает настройки канала и текст, отдаёт HttpRequest; получает
код и тело ответа, отдаёт SendResult. Сети и потоков у него нет, поэтому каждую площадку
можно проверить исполнением без интернета и без ключей.

Площадка, у которой есть мастер подключения (Telegram, VK), дополнительно умеет собирать
произвольный вызов своего API (api_request) и разбирать его ответ (parse_api) — этим
пользуется pairing.py, чтобы проверить ключ и дождаться первого сообщения от человека.

Чтобы добавить площадку: файл fm_messengers/<kind>.py с наследником, поля в fields,
build_request и parse_response по ОФИЦИАЛЬНОЙ документации, одна строка в registry.py.
"""
import json

from . import models as M


class MessengerProvider(object):
    kind = ""
    title = ""
    docs_url = ""
    note = {"ru": "", "en": ""}
    fields = ()
    text_limit = 4096
    DEFAULT_API_BASE = ""
    has_wizard = False              # есть ли мастер подключения (кнопки вместо полей)
    wizard = {"ru": [], "en": []}   # шаги мастера для окна модуля (текст и кнопки)

    def __init__(self, api_base=None):
        self.api_base = str(api_base or self.DEFAULT_API_BASE).rstrip("/")

    # ── настройки ─────────────────────────────────────────────────────────────────────────
    def missing(self, cfg):
        cfg = cfg or {}
        return [f.key for f in self.fields if f.required and not str(cfg.get(f.key) or "").strip()]

    def validate(self, cfg):
        """-> None, если слать можно; иначе (reason, detail)."""
        miss = self.missing(cfg)
        if miss:
            return (M.REASON_NOT_CONFIGURED, "missing: " + ", ".join(miss))
        return None

    def field_dicts(self, lang):
        return [f.as_dict(lang) for f in self.fields]

    def secret_keys(self):
        return [f.key for f in self.fields if f.secret]

    def connected_label(self, cfg):
        """Короткая подпись «куда подключено» для окна модуля (без секретов)."""
        return ""

    # ── текст ─────────────────────────────────────────────────────────────────────────────
    def prepare_text(self, text):
        t = str(text or "")
        if len(t) > self.text_limit:
            t = t[:self.text_limit - 1] + "…"
        return t

    # ── контракт площадки ─────────────────────────────────────────────────────────────────
    def build_request(self, cfg, text, nonce=0):
        raise NotImplementedError

    def parse_response(self, status, body):
        raise NotImplementedError

    def extract_token(self, text):
        """Ключ из того, что человек вставил. Площадка с мастером умеет найти его внутри
        целого сообщения (люди копируют сообщение целиком чаще, чем ровно одну строку)."""
        return str(text or "").strip()

    def api_request(self, cfg, method, params=None):
        """Произвольный вызов API площадки (для мастера подключения). Нет — None."""
        return None

    def parse_api(self, status, body):
        """(HTTP-код, тело) -> (ok, данные | {"reason","detail"})."""
        return (False, {"reason": M.REASON_BAD_RESPONSE, "detail": "no api"})

    # ── помощники ─────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _json(body):
        try:
            if isinstance(body, (bytes, bytearray)):
                body = body.decode("utf-8", "replace")
            j = json.loads(body or "")
            return j if isinstance(j, dict) else None
        except Exception:
            return None

    def describe(self, lang):
        L = "ru" if lang != "en" else "en"
        return {"kind": self.kind, "title": self.title, "docs_url": self.docs_url,
                "note": self.note.get(L) or self.note.get("en") or "",
                "fields": self.field_dicts(lang), "text_limit": self.text_limit,
                "has_wizard": self.has_wizard,
                "wizard": list(self.wizard.get(L) or self.wizard.get("en") or [])}
