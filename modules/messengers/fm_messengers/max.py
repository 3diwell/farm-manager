# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""MAX Bot API (мессенджер MAX, платформа VK).

КОНТРАКТ (dev.max.ru/docs-api и dev.max.ru/docs/chatbots; снят 12.09.2026; сверен со
структурами официального Go-клиента max-messenger/max-bot-api-client-go):
  Адрес: https://platform-api2.max.ru — документация прямо просит слать запросы на этот домен
    «вместо platform-api.max.ru». Ключ ТОЛЬКО в заголовке «Authorization: <token>»: передача
    через параметры адреса больше не поддерживается. Предел — 30 запросов в секунду, в один
    диалог — не чаще двух сообщений в секунду.
  GET /me: сведения о боте — user_id, first_name, username (никнейм), is_bot,
    last_activity_time. Неверный ключ — HTTP 401.
  POST /messages?user_id=<id> | ?chat_id=<id> [&disable_link_preview=true], тело JSON
    {"text": до 4000 знаков, "notify": true|false, "format": "markdown"|"html"|null}.
    Успех: {"message": {sender, recipient{chat_id, chat_type, user_id}, timestamp,
    body{mid, seq, text}}}. Ошибки: 400 неверный запрос, 401 ключ, 404 не найдено,
    429 слишком часто, 503 сервис недоступен; тело ошибки {"error", "code", "message"}.
  GET /updates?limit=&timeout=(0-90, по умолчанию 30)&marker=&types=a,b — долгий опрос.
    Ответ {"updates": [...], "marker": N}: marker из ответа передаётся в следующий вызов,
    без marker отдаются последние события. У каждого события update_type и timestamp
    (Unix-время в МИЛЛИСЕКУНДАХ). bot_started: chat_id, user{user_id, first_name, last_name,
    username, is_bot}, payload (то, что стояло в ссылке после ?start=), user_locale.
    message_created: message{sender{…}, recipient{chat_id, chat_type: dialog|chat|channel,
    user_id}, timestamp, body{mid, seq, text}}, user_locale.
  Ссылка на бота: https://max.ru/<никнейм>?start=<payload> (payload до 128 знаков) — при
    переходе бот получает bot_started с этим payload.

КАК ЗАВОДИТСЯ БОТ (dev.max.ru/docs/chatbots/bots-create/create, 12.09.2026). Программного
способа нет, и у MAX нет «BotFather»: бота создаёт человек на платформе MAX для бизнеса
(business.max.ru) с ПРОВЕРЕННЫМ профилем организации, ИП или самозанятого (требование платформы;
по её правилам — резидента РФ, в текстах для владельца страна не называется — его решение 2.998).
Раздел «Чат-боты» → «Создать» → карточка (логотип, название 1-59 знаков, описание до 200,
никнейм платформа выдаёт сама) → «Создать» → модерация до 48 рабочих часов → статус
«Опубликован» — и в карточке бота появляется ключ. Лимит: 5 ботов у организации и ИП,
2 у самозанятого. Дальше всё делает модуль: проверяет ключ (/me), даёт ссылку с кодом,
ждёт нажатия Start (/updates), сам запоминает чат и шлёт пробное.
"""
import json
import re
import urllib.parse

from . import models as M
from .base import MessengerProvider

_NUM_RX = re.compile(r"^-?\d{1,19}$")
#  Ключ бота MAX — длинная строка без пробелов из букв, цифр, дефисов и подчёркиваний.
#  Точный формат платформа не публикует; берём самый длинный такой кусок из вставленного
#  текста — человек может вставить строку из карточки бота вместе с подписью «Токен:».
_TOKEN_RX = re.compile(r"([A-Za-z0-9_\-]{20,})")


class MaxProvider(MessengerProvider):
    kind = "max"
    title = "MAX"
    docs_url = "https://dev.max.ru/docs/chatbots/bots-create/create"
    DEFAULT_API_BASE = "https://platform-api2.max.ru"
    text_limit = 4000
    has_wizard = True
    note = {
        "ru": "Сообщения приходят в ваш MAX от вашего же бота — на телефон и на компьютер сразу.",
        "en": "Messages arrive in your MAX from your own bot — on the phone and on the computer at once.",
    }
    BUSINESS_LINK = "https://business.max.ru/self"
    DOCS_LINK = "https://dev.max.ru/docs/chatbots/bots-create/create"
    wizard = {
        "ru": [
            {"n": 1, "title": "Создайте бота на платформе MAX для бизнеса",
             "text": "Бота создаёт человек — у MAX нет способа сделать это программой, и нет "
                     "«BotFather» как в Telegram: бот заводится на сайте платформы для бизнеса.\n"
                     "Нужен ПРОВЕРЕННЫЙ профиль организации, ИП или самозанятого — так требует платформа. "
                     "Если профиля ещё нет — нажмите кнопку, войдите и пройдите проверку в разделе "
                     "«Верификация»: от нескольких минут до двух рабочих дней.\n"
                     "Дальше: раздел «Чат-боты» → «Создать» → заполните карточку (название — любое, "
                     "например «Моя ферма»; логотип и описание — по желанию) → «Создать».\n"
                     "Бот уйдёт на модерацию — до 48 рабочих часов. Когда статус станет "
                     "«Опубликован», откройте карточку бота: там будет ключ (токен). Он нужен на "
                     "следующем шаге.",
             "button": "Открыть платформу MAX", "url": "https://business.max.ru/self",
             "link_button": "Инструкция MAX по созданию бота", "link_url": DOCS_LINK,
             "next": "Бот создан, дальше"},
            {"n": 2, "title": "Вставьте ключ из карточки бота",
             "text": "Ключ — длинная строка в карточке бота на платформе (появляется после "
                     "модерации, когда статус «Опубликован»). Скопируйте её и вставьте сюда. "
                     "Можно вставить и строку вместе с подписью — программа сама найдёт ключ.",
             "input": "token", "placeholder": "ключ бота из карточки на платформе", "button": "Далее",
             "link_button": "Открыть платформу MAX ещё раз", "link_url": "https://business.max.ru/self"},
            {"n": 3, "title": "Нажмите Start в чате с ботом",
             "text": "Откроется чат с вашим ботом в MAX. Нажмите Start внизу — этим вы разрешаете ему "
                     "писать вам. Больше ничего вводить не нужно: программа сама узнает ваш чат, "
                     "включит канал и пришлёт пробное сообщение.\n"
                     "Можно нажать Start на компьютере или на телефоне — сообщения приходят на все "
                     "ваши устройства сразу.",
             "button": "Открыть бота", "wait": "Жду нажатия Start…"},
        ],
        "en": [
            {"n": 1, "title": "Create a bot on the MAX business platform",
             "text": "A human has to create the bot — MAX has no way to do it from a program and no "
                     "“BotFather” like Telegram: bots are created on the business platform site.\n"
                     "You need a VERIFIED profile of a company, sole proprietor or self-employed "
                     "person — the platform requires it. No profile yet — press the button, sign in and pass "
                     "the check in the “Verification” section: minutes to two business days.\n"
                     "Then: “Chat-bots” → “Create” → fill in the card (any name, e.g. “My farm”; logo "
                     "and description optional) → “Create”.\n"
                     "The bot goes to moderation — up to 48 business hours. When the status becomes "
                     "“Published”, open the bot card: the token is there. It is needed on step 2.",
             "button": "Open the MAX platform", "url": "https://business.max.ru/self",
             "link_button": "MAX guide on creating a bot", "link_url": DOCS_LINK,
             "next": "Bot created, next"},
            {"n": 2, "title": "Paste the token from the bot card",
             "text": "The token is the long string in the bot card on the platform (it appears after "
                     "moderation, when the status is “Published”). Copy it and paste it here. Pasting "
                     "the line together with its caption is fine — the program finds the token.",
             "input": "token", "placeholder": "bot token from the card on the platform", "button": "Next",
             "link_button": "Open the MAX platform again", "link_url": "https://business.max.ru/self"},
            {"n": 3, "title": "Press Start in the chat with your bot",
             "text": "A chat with your bot opens in MAX. Press Start at the bottom — that allows it to "
                     "message you. Nothing else to type: the program finds your chat, enables the "
                     "channel and sends a test message.\n"
                     "Press Start on the computer or on the phone — messages reach all your devices.",
             "button": "Open the bot", "wait": "Waiting for Start…"},
        ],
    }
    fields = (
        M.FieldSpec("access_token", {"ru": "Ключ бота", "en": "Bot token"},
                    {"ru": "Из карточки бота на платформе MAX для бизнеса.",
                     "en": "From the bot card on the MAX business platform."},
                    secret=True, placeholder="ключ бота"),
        M.FieldSpec("chat_id", {"ru": "Chat ID", "en": "Chat ID"},
                    {"ru": "Заполняется мастером автоматически.", "en": "Filled in by the wizard."},
                    placeholder="123456789"),
        M.FieldSpec("user_id", info=True, required=False),
        M.FieldSpec("bot_username", info=True, required=False),
        M.FieldSpec("bot_name", info=True, required=False),
        M.FieldSpec("chat_title", info=True, required=False),
    )

    def extract_token(self, text):
        cands = _TOKEN_RX.findall(str(text or ""))
        if cands:
            return max(cands, key=len)
        return str(text or "").strip()

    def connected_label(self, cfg):
        cfg = cfg or {}
        bot = str(cfg.get("bot_username") or "").strip()
        who = str(cfg.get("chat_title") or "").strip()
        parts = [("@" + bot) if bot else str(cfg.get("bot_name") or "").strip(), who]
        return " → ".join(p for p in parts if p)

    def validate(self, cfg):
        r = MessengerProvider.validate(self, cfg)
        if r:
            return r
        chat = str((cfg or {}).get("chat_id") or "").strip()
        if not _NUM_RX.match(chat):
            return (M.REASON_BAD_REQUEST, "chat_id must be a number")
        return None

    # ── произвольный вызов API (мастер подключения) ───────────────────────────────────────
    def _headers(self, token, with_json=False):
        h = {"Authorization": token, "Accept": "application/json"}
        if with_json:
            h["Content-Type"] = "application/json"
        return h

    def api_request(self, cfg, method, params=None):
        token = str((cfg or {}).get("access_token") or "").strip()
        p = dict(params or {})
        if method == "me":
            return M.HttpRequest("GET", "%s/me" % self.api_base, headers=self._headers(token),
                                 timeout=15.0, secrets=(token,))
        if method == "updates":
            q = {}
            for k in ("limit", "timeout", "marker"):
                if p.get(k) is not None:
                    q[k] = str(p[k])
            if p.get("types"):
                q["types"] = ",".join(str(t) for t in p["types"])
            url = "%s/updates" % self.api_base
            if q:
                url += "?" + urllib.parse.urlencode(q)
            return M.HttpRequest("GET", url, headers=self._headers(token),
                                 timeout=float(p.get("timeout") or 0) + 10.0, secrets=(token,))
        if method == "messages":
            q = {}
            for k in ("chat_id", "user_id"):
                if p.get(k) is not None:
                    q[k] = str(p[k])
            body = {"text": self.prepare_text(p.get("text")), "notify": True}
            return M.HttpRequest("POST", "%s/messages?%s" % (self.api_base, urllib.parse.urlencode(q)),
                                 headers=self._headers(token, with_json=True),
                                 body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 timeout=15.0, secrets=(token,))
        return None

    @staticmethod
    def _error_text(j, status):
        j = j or {}
        parts = [str(j.get(k) or "") for k in ("code", "message", "error")]
        s = ": ".join(p for p in parts if p)
        return s or ("HTTP %s" % status)

    def parse_api(self, status, body):
        j = self._json(body)
        if 200 <= int(status) < 300:
            return (True, j if j is not None else {})
        if status == 401:
            reason = M.REASON_BAD_TOKEN
        elif status == 429:
            reason = M.REASON_RATE_LIMITED
        elif status == 400:
            reason = M.REASON_BAD_REQUEST
        elif j is None:
            reason = M.REASON_BAD_RESPONSE
        else:
            reason = M.REASON_PLATFORM_ERROR
        return (False, {"reason": reason, "detail": self._error_text(j, status), "code": status})

    # ── отправка ──────────────────────────────────────────────────────────────────────────
    def build_request(self, cfg, text, nonce=0):
        cfg = cfg or {}
        token = str(cfg.get("access_token") or "").strip()
        chat = str(cfg.get("chat_id") or "").strip()
        user = str(cfg.get("user_id") or "").strip()
        q = {"disable_link_preview": "true"}
        if chat:
            q["chat_id"] = chat
        elif user:
            q["user_id"] = user
        body = {"text": self.prepare_text(text), "notify": True}
        return M.HttpRequest("POST", "%s/messages?%s" % (self.api_base, urllib.parse.urlencode(q)),
                             headers=self._headers(token, with_json=True),
                             body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                             secrets=(token,))

    def parse_response(self, status, body):
        j = self._json(body)
        if 200 <= int(status) < 300:
            msg = (j or {}).get("message") if isinstance(j, dict) else None
            mid = None
            if isinstance(msg, dict) and isinstance(msg.get("body"), dict):
                mid = msg["body"].get("mid")
            return M.SendResult(True, M.REASON_OK, "", status, mid)
        detail = self._error_text(j, status)
        low = detail.lower()
        if status == 401:
            reason = M.REASON_BAD_TOKEN
        elif status == 404 or "chat.not.found" in low or "user.not.found" in low or "not found" in low:
            reason = M.REASON_BAD_RECIPIENT
        elif status == 403 or "access.denied" in low or "forbidden" in low:
            reason = M.REASON_RECIPIENT_NOT_ALLOWED
        elif status == 429:
            reason = M.REASON_RATE_LIMITED
        elif "too long" in low or "too.long" in low or "text.length" in low:
            reason = M.REASON_TOO_LONG
        elif status == 400:
            reason = M.REASON_BAD_REQUEST
        elif j is None:
            reason = M.REASON_BAD_RESPONSE
        else:
            reason = M.REASON_PLATFORM_ERROR
        return M.SendResult(False, reason, detail, status)
