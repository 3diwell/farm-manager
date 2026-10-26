# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Telegram Bot API.

КОНТРАКТ (core.telegram.org/bots/api; снят 10.09.2026):
  Все методы: POST https://api.telegram.org/bot<token>/<метод>, тело JSON.
  sendMessage: chat_id (число или строка), text (до 4096), link_preview_options.
  getMe: сведения о боте — id, username, first_name.
  getUpdates: offset, timeout (долгий опрос), allowed_updates; ответ result — список
    обновлений {update_id, message:{message_id, date, chat:{id,type,title,first_name,
    last_name,username}, from:{…}, text}}. Обновление считается принятым, когда следующий
    вызов передаёт offset = update_id + 1. При включённом webhook getUpdates отвечает 409 —
    тогда deleteWebhook.
  Ссылка «нажмите Start»: https://t.me/<username>?start=<код> — бот получает текст
    «/start <код>» (код до 64 знаков A-Za-z0-9_-).
  Ответ: {"ok": true, "result": …} либо {"ok": false, "error_code": N, "description": "…"}.
  Живой ответ на заведомо неверный ключ: {"ok":false,"error_code":401,"description":"Unauthorized"}.

МАСТЕР ПОДКЛЮЧЕНИЯ. Бота создаёт только человек у @BotFather (программного способа нет):
три сообщения — /newbot, имя, адрес. Дальше всё делает модуль: проверяет ключ (getMe),
даёт ссылку с кодом, ждёт нажатия Start (getUpdates), сам запоминает chat_id и шлёт пробное.
"""
import json
import re

from . import models as M
from .base import MessengerProvider

_CHAT_RX = re.compile(r"^(-?\d{1,20}|@[A-Za-z0-9_]{5,64})$")
#  Ключ бота в тексте: <id бота>:<секрет>. Нужен, чтобы принять ВСЁ сообщение BotFather
#  целиком — человек копирует его целиком гораздо чаще, чем ровно одну строку.
_TOKEN_RX = re.compile(r"(\d{5,12}:[A-Za-z0-9_-]{30,})")
_NUM_RX = re.compile(r"^-?\d+$")


class TelegramProvider(MessengerProvider):
    kind = "telegram"
    title = "Telegram"
    docs_url = "https://t.me/BotFather"
    DEFAULT_API_BASE = "https://api.telegram.org"
    text_limit = 4096
    has_wizard = True
    note = {
        "ru": "Сообщения приходят в ваш Telegram — на телефон и на компьютер сразу.",
        "en": "Messages arrive in your Telegram — on the phone and on the computer at once.",
    }
    #  Ссылка с предзаполненной командой: t.me/<username>?text=<текст> (core.telegram.org/api/links).
    #  Проверено живым запросом 11.09.2026: t.me отдаёт tg://resolve?domain=BotFather&text=%2Fnewbot,
    #  то есть чат открывается с уже впечатанным /newbot — человеку остаётся нажать «отправить».
    NEWBOT_LINK = "https://t.me/BotFather?text=%2Fnewbot"
    BOTFATHER_LINK = "https://t.me/BotFather"
    wizard = {
        "ru": [
            {"n": 1, "title": "Создайте бота у @BotFather",
             "text": "Бота создаёт человек — у Telegram нет способа сделать это программой. Это три "
                     "сообщения и одна минута.\n"
                     "Нажмите кнопку: откроется чат с @BotFather, команда /newbot уже будет впечатана — "
                     "просто отправьте её.\n"
                     "Он спросит НАЗВАНИЕ бота: напишите любое, например «Моя ферма».\n"
                     "Потом спросит АДРЕС: он должен быть латиницей и заканчиваться на bot — скопируйте "
                     "готовый ниже и отправьте.\n"
                     "В ответ придёт сообщение с длинной строкой — это ключ, он нужен на следующем шаге.",
             "button": "Открыть @BotFather", "url": "https://t.me/BotFather?text=%2Fnewbot",
             "suggest_label": "Готовый адрес для бота — скопируйте и отправьте его BotFather:",
             "suggest": "bot_username", "next": "Бот создан, дальше"},
            {"n": 2, "title": "Вставьте ключ из BotFather",
             "text": "Ключ — это то, что BotFather прислал последним сообщением: строка после слов "
                     "«Use this token to access the HTTP API», вида 8123456789:AAHdq…\n"
                     "Нажмите на неё прямо в Telegram — она скопируется. Можно вставить сюда и всё "
                     "сообщение целиком: программа сама найдёт в нём ключ.",
             "input": "token", "placeholder": "8123456789:AA…", "button": "Далее",
             "link_button": "Открыть @BotFather ещё раз", "link_url": "https://t.me/BotFather"},
            {"n": 3, "title": "Нажмите Start в чате с ботом",
             "text": "Откроется чат с вашим ботом. Нажмите кнопку Start внизу — этим вы разрешаете ему "
                     "писать вам. Больше ничего вводить не нужно: программа сама узнает ваш чат, включит "
                     "канал и пришлёт пробное сообщение.\n"
                     "Можно нажать Start на компьютере или на телефоне — сообщения приходят на все ваши "
                     "устройства сразу.",
             "button": "Открыть бота", "wait": "Жду нажатия Start…"},
        ],
        "en": [
            {"n": 1, "title": "Create a bot with @BotFather",
             "text": "A human has to create the bot — Telegram has no way to do it from a program. "
                     "It is three messages and one minute.\n"
                     "Press the button: a chat with @BotFather opens with the /newbot command already "
                     "typed in — just send it.\n"
                     "He asks for the bot NAME: anything, e.g. “My farm”.\n"
                     "Then for the ADDRESS: Latin letters, must end with bot — copy the ready one below.\n"
                     "He replies with a message containing a long string — that is the token for step 2.",
             "button": "Open @BotFather", "url": "https://t.me/BotFather?text=%2Fnewbot",
             "suggest_label": "A ready address for the bot — copy it and send it to BotFather:",
             "suggest": "bot_username", "next": "Bot created, next"},
            {"n": 2, "title": "Paste the token from BotFather",
             "text": "The token is what BotFather sent last: the line after “Use this token to access "
                     "the HTTP API”, like 8123456789:AAHdq…\n"
                     "Tap it in Telegram — it gets copied. You can also paste the whole message here: "
                     "the program will find the token in it.",
             "input": "token", "placeholder": "8123456789:AA…", "button": "Next",
             "link_button": "Open @BotFather again", "link_url": "https://t.me/BotFather"},
            {"n": 3, "title": "Press Start in the chat with your bot",
             "text": "A chat with your bot opens. Press Start at the bottom — that allows it to message "
                     "you. Nothing else to type: the program finds your chat, enables the channel and "
                     "sends a test message.\n"
                     "Press Start on the computer or on the phone — messages reach all your devices.",
             "button": "Open the bot", "wait": "Waiting for Start…"},
        ],
    }
    fields = (
        M.FieldSpec("bot_token", {"ru": "Ключ бота", "en": "Bot token"},
                    {"ru": "Выдаёт @BotFather.", "en": "Issued by @BotFather."},
                    secret=True, placeholder="123456789:AA…"),
        M.FieldSpec("chat_id", {"ru": "Chat ID", "en": "Chat ID"},
                    {"ru": "Заполняется мастером автоматически.", "en": "Filled in by the wizard."},
                    placeholder="123456789"),
        M.FieldSpec("bot_username", info=True, required=False),
        M.FieldSpec("chat_title", info=True, required=False),
    )

    def extract_token(self, text):
        m = _TOKEN_RX.search(str(text or ""))
        return m.group(1) if m else str(text or "").strip()

    def connected_label(self, cfg):
        cfg = cfg or {}
        bot = str(cfg.get("bot_username") or "").strip()
        who = str(cfg.get("chat_title") or "").strip()
        parts = [("@" + bot) if bot else "", who]
        return " → ".join(p for p in parts if p)

    def validate(self, cfg):
        r = MessengerProvider.validate(self, cfg)
        if r:
            return r
        chat = str((cfg or {}).get("chat_id") or "").strip()
        if not _CHAT_RX.match(chat):
            return (M.REASON_BAD_REQUEST, "chat_id must be a number (or @channel)")
        return None

    # ── произвольный вызов API (мастер подключения) ───────────────────────────────────────
    def api_request(self, cfg, method, params=None):
        token = str((cfg or {}).get("bot_token") or "").strip()
        timeout = 15.0
        if method == "getUpdates":
            timeout = float((params or {}).get("timeout") or 0) + 10.0
        return M.HttpRequest("POST", "%s/bot%s/%s" % (self.api_base, token, method),
                             headers={"Content-Type": "application/json"},
                             body=json.dumps(params or {}, ensure_ascii=False).encode("utf-8"),
                             timeout=timeout, secrets=(token,))

    def parse_api(self, status, body):
        j = self._json(body)
        if j is None:
            reason = M.REASON_BAD_TOKEN if status in (401, 404) else M.REASON_BAD_RESPONSE
            return (False, {"reason": reason, "detail": "HTTP %s" % status, "code": status})
        if j.get("ok") is True:
            return (True, j.get("result"))
        code = j.get("error_code")
        desc = str(j.get("description") or "")
        reason = M.REASON_BAD_TOKEN if code in (401, 404) else (
            M.REASON_RATE_LIMITED if code == 429 else M.REASON_PLATFORM_ERROR)
        return (False, {"reason": reason, "detail": "%s: %s" % (code, desc), "code": code})

    # ── отправка ──────────────────────────────────────────────────────────────────────────
    def build_request(self, cfg, text, nonce=0):
        token = str((cfg or {}).get("bot_token") or "").strip()
        chat = str((cfg or {}).get("chat_id") or "").strip()
        chat_v = int(chat) if _NUM_RX.match(chat) else chat
        body = {"chat_id": chat_v, "text": self.prepare_text(text),
                "link_preview_options": {"is_disabled": True}}
        return M.HttpRequest("POST", "%s/bot%s/sendMessage" % (self.api_base, token),
                             headers={"Content-Type": "application/json"},
                             body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                             secrets=(token,))

    def parse_response(self, status, body):
        j = self._json(body)
        if j is None:
            if status == 401:
                return M.SendResult(False, M.REASON_BAD_TOKEN, "HTTP 401", status)
            return M.SendResult(False, M.REASON_BAD_RESPONSE, "HTTP %s, not JSON" % status, status)
        if j.get("ok") is True:
            res = j.get("result") if isinstance(j.get("result"), dict) else {}
            return M.SendResult(True, M.REASON_OK, "", status, res.get("message_id"))
        code = j.get("error_code")
        desc = str(j.get("description") or "")
        low = desc.lower()
        if code in (401, 404):
            reason = M.REASON_BAD_TOKEN
        elif code == 403:
            reason = M.REASON_RECIPIENT_NOT_ALLOWED
        elif code == 429:
            reason = M.REASON_RATE_LIMITED
        elif "chat not found" in low or "user not found" in low:
            reason = M.REASON_BAD_RECIPIENT
        elif "too long" in low:
            reason = M.REASON_TOO_LONG
        elif "chat_id is empty" in low:
            reason = M.REASON_NOT_CONFIGURED
        elif code == 400:
            reason = M.REASON_BAD_REQUEST
        else:
            reason = M.REASON_PLATFORM_ERROR
        return M.SendResult(False, reason, ("%s: %s" % (code, desc)) if code else desc, status)
