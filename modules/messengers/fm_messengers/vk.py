# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""VK API (версия 5.199).

КОНТРАКТ (dev.vk.com; машинная схема VKCOM/vk-api-schema; живой ответ api.vk.com 10.09.2026
подтвердил адрес, версию и форму ошибки):
  Все методы: POST https://api.vk.com/method/<метод>, тело application/x-www-form-urlencoded
  с access_token и v=5.199. Ошибка: {"error":{"error_code":N,"error_msg":"…"}}.
  messages.send: peer_id, message (до 9000; здесь 4096), random_id (уникальное число),
    dont_parse_links, disable_mentions. Успех: {"response": <id сообщения>}.
  groups.getTokenPermissions (ключ сообщества): {"mask": N, "permissions": [{"setting": N,
    "name": "messages"}, …]} — есть ли у ключа право «сообщения».
  groups.getById (ключи user/group/service, group_ids/group_id не обязательны): сведения о
    сообществе — id, name, screen_name; с ключом сообщества без параметров — о нём самом.
  messages.getConversations (ключи user/group): count, filter=all, extended=1,
    fields=first_name,last_name → items[].conversation.peer.{id,type}, items[].last_message
    .{from_id,text,date}, profiles[] — кто написал сообществу.
  Ссылка на диалог с сообществом: https://vk.me/club<id>.
  Коды: 5 ключ не принят, 7/15 нет права, 901 получатель не разрешил сообщения от сообщества,
  902 закрыт приватностью, 912 сообщения сообщества выключены, 914 длинно, 936 контакт не
  найден, 100 неверный параметр, 6/9/29 часто, 14 капча, 10 сбой сервера.

МАСТЕР ПОДКЛЮЧЕНИЯ. Сообщество и ключ создаёт человек на сайте (кнопки открывают нужные
страницы), дальше модуль проверяет ключ, даёт ссылку на диалог с сообществом и ждёт первого
сообщения — им получатель одновременно разрешает сообществу писать ему (иначе код 901).
"""
import re
import time
import urllib.parse

from . import models as M
from .base import MessengerProvider

API_VERSION = "5.199"
_NUM_RX = re.compile(r"^-?\d{1,19}$")
#  Ключ сообщества в тексте: новый формат vk1.a.<секрет> либо старый — 85 HEX-знаков.
_TOKEN_RX = re.compile(r"(vk1\.a\.[A-Za-z0-9_-]{20,}|\b[0-9a-f]{85}\b)")


class VkProvider(MessengerProvider):
    kind = "vk"
    title = "VK"
    docs_url = "https://vk.com/groups_create"
    DEFAULT_API_BASE = "https://api.vk.com"
    text_limit = 4096
    has_wizard = True
    note = {
        "ru": "Сообщения приходят в ваш VK от вашего же сообщества — в приложение и на сайт.",
        "en": "Messages arrive in your VK from your own community — in the app and on the site.",
    }
    COMMUNITY_LINK = "https://vk.com/groups_create"
    ADMIN_GROUPS_LINK = "https://vk.com/groups?tab=admin"
    #  Названия разделов сверены с dev.vk.com («Ключ доступа сообщества», 11.09.2026):
    #  Управление → Дополнительно → Работа с API → вкладка «Ключи доступа» → Создать ключ →
    #  выбрать права → Создать → подтвердить в приложении ВКонтакте или по СМС.
    #  2.997: добавлен переход ОТ ЛЕВОГО МЕНЮ к управлению — без него инструкция начиналась
    #  с середины пути, и человек, стоящий на ленте, не понимал, куда нажимать.
    wizard = {
        "ru": [
            {"n": 1, "title": "Откройте своё сообщество",
             "text": "Сообщения вам будет присылать ваше же сообщество — так устроен ВКонтакте: "
                     "у отправителя должна быть страница.\n"
                     "В ЛЕВОМ меню ВКонтакте нажмите «Сообщества» и откройте своё. Часто оно видно и в "
                     "самом низу левого меню — строкой с маленькой картинкой.\n"
                     "Если сообщества ещё нет — нажмите «Создать сообщество»: тип любой, название любое, "
                     "например «Моя ферма».\n"
                     "Вы должны быть его администратором: другим ВКонтакте ключ не выдаёт.",
             "button": "Создать сообщество", "url": "https://vk.com/groups_create",
             "link_button": "Мои сообщества", "link_url": "https://vk.com/groups?tab=admin",
             "next": "Сообщество открыто, дальше"},
            {"n": 2, "title": "Войдите в «Управление» и включите сообщения",
             "text": "Вы на странице своего сообщества. Смотрите в ПРАВЫЙ СТОЛБЕЦ — там блок ссылок: "
                     "«Управление», «Сообщения», «Статистика», «Монетизация», «Реклама сообщества», "
                     "«Страйки», «Комментарии», «События». «Управление» — самая первая строка в нём, "
                     "со значком шестерёнки. Нажмите её.\n"
                     "В меню «Ещё» вверху страницы «Управления» НЕТ — туда заходить не нужно.\n"
                     "Если такого блока в правом столбце вообще нет, значит вы не администратор "
                     "этого сообщества — откройте то, которое создали сами.\n"
                     "Откроется страница настроек со списком разделов: «Основная информация», "
                     "«Разделы», «Сообщения», «Дополнительно» и другие.\n"
                     "Найдите «Сообщения», включите «Сообщения сообщества» и нажмите «Сохранить».",
             "link_button": "Мои сообщества", "link_url": "https://vk.com/groups?tab=admin",
             "next": "Сообщения включил, дальше"},
            {"n": 3, "title": "Создайте ключ доступа",
             "text": "В ТОМ ЖЕ списке разделов справа (вы всё ещё в «Управлении»):\n"
                     "«Дополнительно» → «Работа с API» → вкладка «Ключи доступа» → кнопка "
                     "«Создать ключ».\n"
                     "Отметьте право «Сообщения сообщества» и нажмите «Создать». ВКонтакте попросит "
                     "подтвердить — в мобильном приложении или по СМС.\n"
                     "После подтверждения ключ появится на этой же вкладке: длинная строка vk1.a.… "
                     "Скопируйте её и вставьте сюда.",
             "input": "token", "placeholder": "vk1.a.…", "button": "Далее",
             "link_button": "Мои сообщества", "link_url": "https://vk.com/groups?tab=admin"},
            {"n": 4, "title": "Напишите своему сообществу",
             "text": "Откроется диалог с вашим сообществом. Отправьте туда любое сообщение, например "
                     "«Старт» — этим вы разрешаете ему писать вам (без этого ВКонтакте запрещает "
                     "сообществу писать первым).\n"
                     "Дальше программа всё сделает сама: найдёт диалог, включит канал и пришлёт пробное.",
             "button": "Открыть диалог", "wait": "Жду вашего сообщения…"},
        ],
        "en": [
            {"n": 1, "title": "Open your community",
             "text": "Your own community will message you — that is how VK works: the sender needs a page.\n"
                     "In the LEFT menu press “Communities” and open yours. It is often visible at the very "
                     "bottom of the left menu too.\n"
                     "No community yet — press “Create a community”: any type, any name.\n"
                     "You must be its administrator: VK issues the token to admins only.",
             "button": "Create a community", "url": "https://vk.com/groups_create",
             "link_button": "My communities", "link_url": "https://vk.com/groups?tab=admin",
             "next": "Community open, next"},
            {"n": 2, "title": "Enter “Manage” and enable messages",
             "text": "You are on your community page. Look at the RIGHT COLUMN — there is a block of "
                     "links: Manage, Messages, Statistics, Monetisation, Community promotion, "
                     "Strikes, Comments, Events. “Manage” is the very first line there, with a "
                     "gear icon. Press it.\n"
                     "The “…” menu at the top does NOT contain it — no need to go there.\n"
                     "If that block is missing entirely, you are not an administrator of this "
                     "community.\n"
                     "The settings page opens with a list of sections: General, Sections, Messages, "
                     "More and others.\n"
                     "Find “Messages”, enable community messages and press “Save”.",
             "link_button": "My communities", "link_url": "https://vk.com/groups?tab=admin",
             "next": "Messages enabled, next"},
            {"n": 3, "title": "Create an access token",
             "text": "In the SAME list of sections on the right (still inside “Manage”):\n"
                     "“More” → “API usage” → the “Access tokens” tab → “Create token”.\n"
                     "Tick the community messages permission and press “Create”. VK asks to confirm — in "
                     "the mobile app or by SMS.\n"
                     "After that the token appears on the same tab: a long vk1.a.… string. Copy it here.",
             "input": "token", "placeholder": "vk1.a.…", "button": "Next",
             "link_button": "My communities", "link_url": "https://vk.com/groups?tab=admin"},
            {"n": 4, "title": "Write to your community",
             "text": "A dialog with your community opens. Send any message there, e.g. “Start” — that "
                     "allows it to message you (VK forbids a community to write first otherwise).\n"
                     "The program does the rest: finds the dialog, enables the channel and sends a test.",
             "button": "Open the dialog", "wait": "Waiting for your message…"},
        ],
    }
    fields = (
        M.FieldSpec("access_token", {"ru": "Ключ доступа сообщества", "en": "Community access token"},
                    {"ru": "С правом «сообщения сообщества».", "en": "With the community messages permission."},
                    secret=True, placeholder="vk1.a.…", max_len=1024),
        M.FieldSpec("peer_id", {"ru": "ID получателя (peer_id)", "en": "Recipient ID (peer_id)"},
                    {"ru": "Заполняется мастером автоматически.", "en": "Filled in by the wizard."},
                    placeholder="123456789"),
        M.FieldSpec("group_id", info=True, required=False),
        M.FieldSpec("group_name", info=True, required=False),
        M.FieldSpec("peer_title", info=True, required=False),
    )

    def extract_token(self, text):
        m = _TOKEN_RX.search(str(text or ""))
        return m.group(1) if m else str(text or "").strip()

    def connected_label(self, cfg):
        cfg = cfg or {}
        parts = [str(cfg.get("group_name") or "").strip(), str(cfg.get("peer_title") or "").strip()]
        return " → ".join(p for p in parts if p)

    def validate(self, cfg):
        r = MessengerProvider.validate(self, cfg)
        if r:
            return r
        if not _NUM_RX.match(str((cfg or {}).get("peer_id") or "").strip()):
            return (M.REASON_BAD_REQUEST, "peer_id must be a number")
        return None

    # ── произвольный вызов API (мастер подключения) ───────────────────────────────────────
    def api_request(self, cfg, method, params=None):
        token = str((cfg or {}).get("access_token") or "").strip()
        items = [("access_token", token), ("v", API_VERSION)]
        for k, v in (params or {}).items():
            items.append((k, str(v)))
        return M.HttpRequest("POST", "%s/method/%s" % (self.api_base, method),
                             headers={"Content-Type": "application/x-www-form-urlencoded"},
                             body=urllib.parse.urlencode(items).encode("utf-8"),
                             timeout=15.0, secrets=(token,))

    def parse_api(self, status, body):
        j = self._json(body)
        if j is None:
            return (False, {"reason": M.REASON_BAD_RESPONSE, "detail": "HTTP %s" % status, "code": None})
        if "response" in j and "error" not in j:
            return (True, j.get("response"))
        err = j.get("error") if isinstance(j.get("error"), dict) else {}
        code = err.get("error_code")
        msg = str(err.get("error_msg") or "")
        if code == 5:
            reason = M.REASON_BAD_TOKEN
        elif code == 912:
            #  «This is a chat bot feature, change this status in settings» —
            #  у сообщества выключены сообщения. Отдельная причина: чинится не правами ключа.
            reason = M.REASON_MESSAGES_OFF
        elif code in (7, 15):
            reason = M.REASON_NO_PERMISSION
        elif code in (6, 9, 29):
            reason = M.REASON_RATE_LIMITED
        elif code == 100:
            reason = M.REASON_BAD_REQUEST
        else:
            reason = M.REASON_PLATFORM_ERROR
        return (False, {"reason": reason, "detail": "%s: %s" % (code, msg), "code": code})

    # ── отправка ──────────────────────────────────────────────────────────────────────────
    def build_request(self, cfg, text, nonce=0):
        cfg = cfg or {}
        token = str(cfg.get("access_token") or "").strip()
        peer = int(str(cfg.get("peer_id") or "0").strip())
        rid = int(nonce or 0) & 0x7FFFFFFF
        if rid == 0:
            rid = int(time.time() * 1000) & 0x7FFFFFFF
        params = [("access_token", token), ("v", API_VERSION), ("peer_id", str(peer)),
                  ("random_id", str(rid)), ("message", self.prepare_text(text)),
                  ("dont_parse_links", "1"), ("disable_mentions", "1")]
        return M.HttpRequest("POST", "%s/method/messages.send" % self.api_base,
                             headers={"Content-Type": "application/x-www-form-urlencoded"},
                             body=urllib.parse.urlencode(params).encode("utf-8"),
                             secrets=(token,))

    def parse_response(self, status, body):
        j = self._json(body)
        if j is None:
            return M.SendResult(False, M.REASON_BAD_RESPONSE, "HTTP %s, not JSON" % status, status)
        if "response" in j and "error" not in j:
            mid = j.get("response")
            return M.SendResult(True, M.REASON_OK, "", status, mid if isinstance(mid, int) else None)
        err = j.get("error") if isinstance(j.get("error"), dict) else None
        if not err:
            return M.SendResult(False, M.REASON_BAD_RESPONSE, "neither response nor error", status)
        code = err.get("error_code")
        msg = str(err.get("error_msg") or "")
        if code == 5:
            reason = M.REASON_BAD_TOKEN
        elif code == 912:
            reason = M.REASON_MESSAGES_OFF
        elif code in (7, 15):
            reason = M.REASON_NO_PERMISSION
        elif code in (901, 902):
            reason = M.REASON_RECIPIENT_NOT_ALLOWED
        elif code == 936:
            reason = M.REASON_BAD_RECIPIENT
        elif code == 914:
            reason = M.REASON_TOO_LONG
        elif code in (6, 9, 29):
            reason = M.REASON_RATE_LIMITED
        elif code == 100:
            reason = M.REASON_BAD_REQUEST
        else:
            reason = M.REASON_PLATFORM_ERROR
        return M.SendResult(False, reason, "%s: %s" % (code, msg), status)
