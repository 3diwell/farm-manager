# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""WhatsApp Business Cloud API.

КОНТРАКТ (developers.facebook.com/docs/whatsapp/cloud-api, Messages; снят 10.09.2026):
  POST https://graph.facebook.com/<версия>/<PHONE_NUMBER_ID>/messages
  Authorization: Bearer <ACCESS_TOKEN>, Content-Type: application/json
  Свободный текст: {"messaging_product":"whatsapp","recipient_type":"individual","to":"<номер>",
                    "type":"text","text":{"preview_url":false,"body":"<текст до 4096>"}}
  Шаблон: {"messaging_product":"whatsapp","to":"<номер>","type":"template",
           "template":{"name":"<имя>","language":{"code":"<язык>"},
                       "components":[{"type":"body","parameters":[{"type":"text","text":"…"}]}]}}
  Успех: {"messages":[{"id":"wamid…"}]}; ошибка: {"error":{"message","code","error_data":{"details"},…}}
  Живой ответ без ключа (10.09.2026): code 100; версии v22.0–v25.0 принимаются.
  Коды: 190 ключ истёк/неверен, 131047 больше 24 часов с последнего ответа получателя —
  нужен шаблон, 131026 получатель недоступен, 133010 номер не зарегистрирован, 130429 часто.

ПОЧЕМУ БЕЗ МАСТЕРА И ПОЧЕМУ БИЗНЕС-АККАУНТ. У WhatsApp НЕТ API для обычного личного
аккаунта — ни платного, ни бесплатного (developers.facebook.com, Cloud API «Get started»,
сверено 11.09.2026: требуется бизнес-портфель Meta и номер, зарегистрированный как
бизнес-номер). Отправлять с личного номера умеют только неофициальные библиотеки, которые
эмулируют WhatsApp Web: это нарушение правил площадки и прямой путь к блокировке номера —
в программу такое не ставим. Отсюда и бизнес-аккаунт: он бесплатный, но завести его нужно.
Свободный текст доходит только сутки после того, как получатель сам написал бизнес-номеру,
дальше — одобренный шаблон. Кнопками это не сократить, поэтому мастера здесь нет.
"""
import json
import re

from . import models as M
from .base import MessengerProvider

GRAPH_VERSION = "v23.0"
PARAM_LIMIT = 1000
_DIGITS = re.compile(r"\D+")


def flatten_for_template(text):
    """Текст -> одна строка для параметра шаблона: площадка запрещает переводы строк,
    табуляцию и длинные пробелы в параметрах."""
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = " | ".join(p.strip() for p in t.split("\n") if p.strip())
    t = t.replace("\t", " ")
    t = re.sub(r" {2,}", " ", t)
    if len(t) > PARAM_LIMIT:
        t = t[:PARAM_LIMIT - 1] + "…"
    return t


class WhatsAppProvider(MessengerProvider):
    kind = "whatsapp"
    title = "WhatsApp"
    docs_url = "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started"
    DEFAULT_API_BASE = "https://graph.facebook.com"
    text_limit = 4096
    has_wizard = False
    note = {
        "ru": ("Для продвинутых. С обычного личного аккаунта WhatsApp отправлять нельзя: такого способа "
               "у WhatsApp просто нет. Работает только WhatsApp Business Platform (Cloud API) — бизнес-аккаунт "
               "Meta бесплатный, но завести его и отдельный номер для него нужно. Ещё одно правило площадки: "
               "свободный текст доходит только сутки после того, как получатель сам написал бизнес-номеру, "
               "дальше нужен заранее одобренный шаблон с одним параметром. Если это сложно — Telegram и VK "
               "делают то же самое за несколько нажатий."),
        "en": ("Advanced. A normal personal WhatsApp account cannot send messages — WhatsApp simply has no "
               "such option. Only the WhatsApp Business Platform (Cloud API) works: a Meta business account is "
               "free, but you have to create it and a separate number for it. One more platform rule: free-form "
               "text is delivered only within 24 hours after the recipient last wrote to the business number, "
               "after that an approved template with one body parameter is required. If that is too much — "
               "Telegram and VK take a few clicks."),
    }
    fields = (
        M.FieldSpec("access_token", {"ru": "Ключ доступа (access token)", "en": "Access token"},
                    {"ru": "Постоянный ключ системного пользователя Meta Business.",
                     "en": "Permanent system-user token from Meta Business."},
                    secret=True, placeholder="EAAG…", max_len=1024),
        M.FieldSpec("phone_number_id", {"ru": "Phone number ID", "en": "Phone number ID"},
                    {"ru": "Число из панели WhatsApp Business (не сам номер телефона).",
                     "en": "The numeric ID from the WhatsApp Business panel (not the phone number)."},
                    placeholder="123456789012345"),
        M.FieldSpec("to", {"ru": "Номер получателя", "en": "Recipient number"},
                    {"ru": "Международный формат без «+» и пробелов: 79001234567.",
                     "en": "International format without «+» or spaces: 79001234567."},
                    placeholder="79001234567"),
        M.FieldSpec("template_name", {"ru": "Имя шаблона (не обязательно)", "en": "Template name (optional)"},
                    {"ru": "Одобренный шаблон с одним параметром в теле. Пусто — свободный текст.",
                     "en": "An approved template with one body parameter. Empty — free-form text."},
                    required=False, placeholder="farm_notice"),
        M.FieldSpec("template_lang", {"ru": "Язык шаблона", "en": "Template language"},
                    {"ru": "Код языка шаблона, как в панели Meta: ru, en_US.",
                     "en": "Template language code as in the Meta panel: ru, en_US."},
                    required=False, placeholder="ru"),
    )

    @staticmethod
    def _digits(v):
        return _DIGITS.sub("", str(v or ""))

    def connected_label(self, cfg):
        to = self._digits((cfg or {}).get("to"))
        return ("+" + to) if to else ""

    def validate(self, cfg):
        r = MessengerProvider.validate(self, cfg)
        if r:
            return r
        cfg = cfg or {}
        if not re.match(r"^\d{5,20}$", self._digits(cfg.get("phone_number_id"))):
            return (M.REASON_BAD_REQUEST, "phone_number_id must be a number")
        if not re.match(r"^\d{7,15}$", self._digits(cfg.get("to"))):
            return (M.REASON_BAD_REQUEST, "recipient number must be 7–15 digits")
        return None

    def build_request(self, cfg, text, nonce=0):
        cfg = cfg or {}
        token = str(cfg.get("access_token") or "").strip()
        pnid = self._digits(cfg.get("phone_number_id"))
        to = self._digits(cfg.get("to"))
        tpl = str(cfg.get("template_name") or "").strip()
        if tpl:
            body = {"messaging_product": "whatsapp", "to": to, "type": "template",
                    "template": {"name": tpl,
                                 "language": {"code": str(cfg.get("template_lang") or "ru").strip() or "ru"},
                                 "components": [{"type": "body",
                                                 "parameters": [{"type": "text",
                                                                 "text": flatten_for_template(text)}]}]}}
        else:
            body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                    "type": "text", "text": {"preview_url": False, "body": self.prepare_text(text)}}
        return M.HttpRequest("POST", "%s/%s/%s/messages" % (self.api_base, GRAPH_VERSION, pnid),
                             headers={"Content-Type": "application/json",
                                      "Authorization": "Bearer " + token},
                             body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                             secrets=(token,))

    def parse_response(self, status, body):
        j = self._json(body)
        if j is None:
            if status == 401:
                return M.SendResult(False, M.REASON_BAD_TOKEN, "HTTP 401", status)
            return M.SendResult(False, M.REASON_BAD_RESPONSE, "HTTP %s, not JSON" % status, status)
        msgs = j.get("messages")
        if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict) and msgs[0].get("id"):
            return M.SendResult(True, M.REASON_OK, "", status, msgs[0].get("id"))
        err = j.get("error") if isinstance(j.get("error"), dict) else None
        if not err:
            return M.SendResult(False, M.REASON_BAD_RESPONSE, "no messages[] and no error{}", status)
        code = err.get("code")
        msg = str(err.get("message") or "")
        ed = err.get("error_data") if isinstance(err.get("error_data"), dict) else {}
        details = str(ed.get("details") or "")
        if code in (190, 104, 102):
            reason = M.REASON_BAD_TOKEN
        elif code in (131047, 131030):
            reason = M.REASON_RECIPIENT_NOT_ALLOWED
        elif code == 131026:
            reason = M.REASON_BAD_RECIPIENT
        elif code == 133010:
            reason = M.REASON_NOT_CONFIGURED
        elif code in (130429, 131056, 131048, 80007, 4):
            reason = M.REASON_RATE_LIMITED
        elif code in (100, 132000, 132001, 132005, 132007, 132012, 132015, 132016, 131008, 131009):
            reason = M.REASON_BAD_REQUEST
        elif code in (10, 200, 3):
            reason = M.REASON_NO_PERMISSION
        else:
            reason = M.REASON_PLATFORM_ERROR
        return M.SendResult(False, reason, "%s: %s" % (code, details or msg), status)
