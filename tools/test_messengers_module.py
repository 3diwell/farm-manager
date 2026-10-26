# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.994 — модуль «Уведомления в мессенджеры» (modules/messengers, v0.1.0).

ЗАЧЕМ. Владелец 10.09.2026: нужен МОДУЛЬ (отдельное дополнение, ставится из ZIP), который
шлёт сообщения фермы в Telegram, WhatsApp, VK; подключение — «несколько нажатий», без чтения
инструкций и без ручного ввода chat_id/peer_id.

КОНТРАКТЫ (не догадки; сняты 10.09.2026): Telegram Bot API (getMe, getUpdates, sendMessage,
ссылка ?start=<код>); VK API 5.199 (groups.getTokenPermissions, groups.getById,
messages.getConversations, messages.send; схема VKCOM/vk-api-schema); WhatsApp Cloud API
(Graph messages). Живые ответы серверов без ключа подтвердили адреса и форму ошибок.

ЧТО ДОКАЗЫВАЕТСЯ:
  · библиотека площадок собирает запросы ровно по контрактам и разбирает ответы;
  · МАСТЕР ПОДКЛЮЧЕНИЯ: ключ → getMe → ссылка с кодом → нажатие Start поймано → chat_id
    сохранён, канал включён, пробное ушло; неверный ключ, webhook (409), таймаут, отмена;
    VK: право «messages», сообщество, первое свежее сообщение → peer_id и имя;
  · ключи лежат отдельно от настроек и в резервную копию не попадают;
  · backend модуля регистрируется в поддельном ядре: 6 маршрутов с policy_id, хук, поток;
    объявленные маршруты проходят ТЕ ЖЕ проверки, что _module_routes_validate ядра;
  · провайдер копии модуля, карта БД модулей, манифест, сборка ZIP, окно модуля;
  · ядро чистое: встроенной версии 2.993 не осталось.

Безопасность прогона: server.py не импортируется (только текст), в интернет не ходим —
единственный HTTP-сервер поднимается на 127.0.0.1 внутри этого процесса.

Запуск: python tools/test_messengers_module.py   (0 = все проверки пройдены)
"""
import asyncio
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_DIR = os.path.join(REPO, "modules", "messengers")
sys.path.insert(0, REPO)
sys.path.insert(0, MOD_DIR)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fm_messengers import models as M          # noqa: E402
from fm_messengers import pairing as PR         # noqa: E402
from fm_messengers import registry as R        # noqa: E402
from fm_messengers import service as SV        # noqa: E402
from fm_messengers import settings as S        # noqa: E402
from fm_messengers import store as ST          # noqa: E402
from fm_messengers import transport as T       # noqa: E402
from fm_messengers.vk import API_VERSION        # noqa: E402
from fm_messengers.whatsapp import GRAPH_VERSION  # noqa: E402
from app import route_policy_registry as RPR   # noqa: E402
from app.config_backup import module_providers as MP  # noqa: E402

SENTINEL = "MESSENGERS_MODULE_SENTINEL_2_994"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


def rd(*parts):
    return io.open(os.path.join(REPO, *parts), encoding="utf-8").read()


PANEL_SRC = rd("modules", "messengers", "web", "MessengersPanel.js")

print("=== Alpha 2.996: модуль «Уведомления в мессенджеры» ===")
tmp = tempfile.mkdtemp(prefix="fm_msg_")
reg = R.default_registry()

# ── 1. Реестр и каталог ───────────────────────────────────────────────────────────────────
print("\n--- 1. Площадки и мастер ---")
check("1. четыре площадки: Telegram, VK и MAX первыми (у них мастер), WhatsApp — для продвинутых",
      reg.kinds() == ["telegram", "vk", "max", "whatsapp"], reg.kinds())
cat = reg.catalog("ru")
def step_with(w, key):
    """Шаг по роли: с ссылкой на сайт / с полем ключа / с ожиданием человека."""
    return next((x for x in w if x.get(key)), None)


check("2. у Telegram и VK мастер ведёт по шагам: открыть сайт → вставить ключ → дождаться человека",
      all(c["has_wizard"] and 3 <= len(c["wizard"]) <= 5 and step_with(c["wizard"], "url")
          and step_with(c["wizard"], "input") and step_with(c["wizard"], "wait")
          and c["wizard"][0].get("url") for c in cat if c["kind"] in ("telegram", "vk")))
_wa_note = [c for c in cat if c["kind"] == "whatsapp"][0]["note"]
check("3. у WhatsApp мастера нет — поля и честный ответ, ПОЧЕМУ нужен бизнес-аккаунт",
      not [c for c in cat if c["kind"] == "whatsapp"][0]["has_wizard"]
      and "личного аккаунта" in _wa_note and "Business Platform" in _wa_note
      and "бесплатн" in _wa_note, _wa_note[:140])
#  Указание владельца 11.09.2026: «по поводу блокировки его в России писать не нужно, здесь не
#  идёт речь о конкретной стране — программу могут использовать где угодно». Проверяем ВСЕ
#  тексты модуля, а не одну строку: подсказки площадок, шаги мастеров, поля.
_ALL_TEXT = " ".join([c["note"] for c in cat]
                     + [str(v) for c in cat for st in c["wizard"] for v in st.values()]
                     + [f["label"] + " " + f["hint"] for c in cat for f in c["fields"]]
                     + [c["note"] for c in reg.catalog("en")]
                     + [str(v) for c in reg.catalog("en") for st in c["wizard"] for v in st.values()])
_COUNTRIES = ("Росси", "Russia", "России", "РФ ", "Украин", "Беларус", "Казахстан")
check("3б. в текстах модуля НЕ названа ни одна страна и её ограничения",
      not [w for w in _COUNTRIES if w in _ALL_TEXT], [w for w in _COUNTRIES if w in _ALL_TEXT])
check("3в. и в самих исходниках площадок страновых оговорок не осталось",
      not any(w in rd("modules", "messengers", "fm_messengers", "%s.py" % k)
              for k in ("whatsapp", "telegram", "vk", "max") for w in ("Росси", "Russia")))
check("4. ровно один секрет на площадку; служебные поля (имя бота, чат) помечены info",
      [sum(1 for f in c["fields"] if f["secret"]) for c in cat] == [1] * len(cat) and len(cat) == 4
      and any(f["info"] for c in cat if c["kind"] == "telegram" for f in c["fields"]))
check("5. в каталоге нет значений, только описания", not any("value" in f for c in cat for f in c["fields"]))

# ── 1б. Понятность мастера (поправка владельца 11.09.2026) ────────────────────────────────
print("\n--- 1б. Мастер объясняет, что делать ---")
tg_w = [c for c in cat if c["kind"] == "telegram"][0]["wizard"]
vk_w = [c for c in cat if c["kind"] == "vk"][0]["wizard"]
tg_key, vk_key = step_with(tg_w, "input"), step_with(vk_w, "input")
tg_wait, vk_wait = step_with(tg_w, "wait"), step_with(vk_w, "wait")
check("5а. ГЛАВНОЕ: на шаге ввода ключа НАПИСАНО, откуда этот ключ берётся",
      "BotFather" in tg_key["text"] and "Use this token" in tg_key["text"]
      and "vk1.a" in vk_key["text"] and "Ключи доступа" in vk_key["text"], tg_key["text"][:120])
check("5б. на шаге ввода ключа есть вторая кнопка — вернуться к площадке за ключом",
      tg_key.get("link_url") and tg_key.get("link_button") and vk_key.get("link_url"))
check("5в. Telegram открывается ссылкой с УЖЕ ВПЕЧАТАННОЙ командой /newbot (t.me/<имя>?text=<текст>)",
      tg_w[0]["url"] == "https://t.me/BotFather?text=%2Fnewbot", tg_w[0]["url"])
check("5г. на первом шаге сказано, что бота создаёт человек и почему (не «просто сделайте»)",
      "нет способа сделать это программой" in tg_w[0]["text"])
check("5д. на первом шаге сказано, ЧТО ОТВЕЧАТЬ на оба вопроса BotFather",
      "НАЗВАНИЕ" in tg_w[0]["text"] and "АДРЕС" in tg_w[0]["text"] and "bot" in tg_w[0]["text"])
check("5е. готовый адрес бота предлагается программой — придумывать не нужно",
      tg_w[0].get("suggest") == "bot_username" and tg_w[0].get("suggest_label"))
check("5ж. у каждого шага есть номер, заголовок и текст; у последнего — ожидание",
      all(x.get("n") and x.get("title") and x.get("text") for x in tg_w + vk_w)
      and tg_wait and vk_wait)
check("5з. на последнем шаге сказано, что дальше всё делает программа",
      "программа сама узнает ваш чат" in tg_wait["text"] and "программа всё сделает сама" in vk_wait["text"])
check("5и. VK: путь расписан по пунктам меню — «Управление» и «Работа с API»",
      "Управлени" in (vk_w[1]["text"] + vk_key["text"]) and "Работа с API" in vk_key["text"])
check("5к. тексты шагов не пустые и не короче осмысленного (по-русски и по-английски)",
      all(len(x["text"]) > 120 for x in tg_w + vk_w)
      and all(len(x["text"]) > 100 for c in reg.catalog("en") if c["has_wizard"] for x in c["wizard"]))

#  Поправка владельца 11.09.2026: «по данной инструкции не могу найти, как его создать».
#  Официальный путь (dev.vk.com, «Ключ доступа сообщества», снят 11.09.2026):
#  Управление → Дополнительно → Работа с API → вкладка «Ключи доступа» → Создать ключ →
#  права → Создать → подтверждение в приложении или по СМС.
_vk_key = vk_key["text"]
check("5л. VK: путь до ключа совпадает с официальным — с «Дополнительно», вкладкой и подтверждением",
      "Дополнительно" in _vk_key and "Работа с API" in _vk_key and "Ключи доступа" in _vk_key
      and "Создать ключ" in _vk_key and ("СМС" in _vk_key or "приложении" in _vk_key), _vk_key[:160])
check("5м. VK: включение сообщений — ОТДЕЛЬНЫЙ шаг (раньше тонуло в одном абзаце с ключом)",
      len(vk_w) == 4 and "сообщения" in vk_w[1]["title"].lower() and not vk_w[1].get("input")
      and "Сохранить" in vk_w[1]["text"] and vk_key is vk_w[2], [x["title"] for x in vk_w])
#  Владелец 11.09.2026 (со скриншотом ленты): «того, что описано во втором пункте, просто нет
#  на скрине». Инструкция начиналась с середины пути — с «в своём сообществе», хотя человек
#  стоял на ленте. Проверяем, что переход описан целиком.
check("5м1. VK: путь начинается с ЛЕВОГО МЕНЮ — как на экране у человека, а не с середины",
      "ЛЕВОМ меню" in vk_w[0]["text"] and "Сообщества" in vk_w[0]["text"])
#  Снято с живого экрана владельца 11.09.2026: «Управление» — ПЕРВАЯ строка блока ссылок в
#  правом столбце (шестерёнка), над «Сообщения»/«Статистика»/«Страйки»; в меню «Ещё» его нет.
#  Прежний текст звал «справа под аватаркой» и в «…» — владелец кнопку не нашёл.
check("5м2. VK: «Управление» названо ПЕРВОЙ строкой правого столбца, а не «под аватаркой»",
      "ПРАВЫЙ СТОЛБЕЦ" in vk_w[1]["text"] and "первая строка" in vk_w[1]["text"]
      and "шестерёнк" in vk_w[1]["text"] and "аватарк" not in vk_w[1]["text"])
check("5м2б. VK: перечислены соседние ссылки блока — по ним человек узнаёт нужное место",
      all(w in vk_w[1]["text"] for w in ("Статистика", "Страйки", "Комментарии")))
check("5м3. VK: сказано, что в меню «Ещё» этого пункта НЕТ, и что значит его отсутствие",
      "«Ещё»" in vk_w[1]["text"] and "НЕТ" in vk_w[1]["text"]
      and "не администратор" in vk_w[1]["text"])
check("5м4. VK: шаг ключа ссылается на ТО ЖЕ меню, а не начинается заново",
      "ТОМ ЖЕ" in vk_key["text"] or "том же" in vk_key["text"])
check("5н. VK: сказано, что нужны права администратора (иначе ключ не выдаётся)",
      "администратор" in vk_w[0]["text"])
check("5о. VK: на шагах есть ссылка на свои сообщества — не искать вручную",
      all("vk.com/groups" in (x.get("link_url") or "") for x in vk_w[:3]))
check("5п. КЛЮЧЕВОЕ: «сообщения выключены» (912) — отдельная причина, а не общее «нет прав»",
      reg.get("vk").parse_response(200, b'{"error":{"error_code":912,"error_msg":"chat bot feature"}}').reason == M.REASON_MESSAGES_OFF
      and reg.get("vk").parse_response(200, b'{"error":{"error_code":7,"error_msg":"x"}}').reason == M.REASON_NO_PERMISSION
      and reg.get("vk").parse_api(200, b'{"error":{"error_code":912,"error_msg":"x"}}')[1]["reason"] == M.REASON_MESSAGES_OFF)
check("5р. обе причины переведены на человеческий и подсказывают, что чинить",
      "Управление → Сообщения" in PANEL_SRC and "Сообщения сообщества" in PANEL_SRC)

print("\n--- 1в. Ключ можно вставить как угодно ---")
BOTFATHER_MSG = ("Done! Congratulations on your new bot. You will find it at t.me/ferma_ab12c_bot.\n\n"
                 "Use this token to access the HTTP API:\n8123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw\n\n"
                 "Keep your token secure and store it safely.")
check("5л. КЛЮЧЕВОЕ: вставили ВСЁ сообщение BotFather — ключ найден сам",
      reg.get("telegram").extract_token(BOTFATHER_MSG) == "8123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
check("5м. обычная вставка одного ключа не портится (и лишние пробелы срезаются)",
      reg.get("telegram").extract_token("  8123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw \n")
      == "8123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw")
check("5н. VK: ключ найден и в новом формате vk1.a.…, и в старом (85 HEX)",
      reg.get("vk").extract_token("ключ: vk1.a.AbCdEf0123456789_-XyZqwertyuiop, никому не давайте")
      == "vk1.a.AbCdEf0123456789_-XyZqwertyuiop"
      and reg.get("vk").extract_token("token " + "a1b2c3d4e5" * 8 + "f1b2c" + " конец") == "a1b2c3d4e5" * 8 + "f1b2c")
check("5о. не ключ остаётся не ключом (не выдумываем)", reg.get("telegram").extract_token("привет") == "привет")

# ── 2. Контракты отправки ─────────────────────────────────────────────────────────────────
print("\n--- 2. Контракты отправки ---")
tg, vk, wa = reg.get("telegram"), reg.get("vk"), reg.get("whatsapp")
req = tg.build_request({"bot_token": "123456:ABC-DEF", "chat_id": "-1001234"}, "Привет\nмир")
body = json.loads(req.body)
check("6. Telegram: POST api.telegram.org/bot<token>/sendMessage, chat_id числом, без parse_mode",
      req.url == "https://api.telegram.org/bot123456:ABC-DEF/sendMessage" and body["chat_id"] == -1001234
      and body["text"] == "Привет\nмир" and "parse_mode" not in body and body["link_preview_options"] == {"is_disabled": True})
check("7. Telegram: живой ответ на неверный ключ (401) -> bad_token; chat not found -> bad_recipient",
      tg.parse_response(401, b'{"ok":false,"error_code":401,"description":"Unauthorized"}').reason == M.REASON_BAD_TOKEN
      and tg.parse_response(400, b'{"ok":false,"error_code":400,"description":"Bad Request: chat not found"}').reason == M.REASON_BAD_RECIPIENT)
req = vk.build_request({"access_token": "vk1.a.secret", "peer_id": "987"}, "Привет", nonce=12345)
params = dict(urllib.parse.parse_qsl(req.body.decode("utf-8")))
check("8. VK: POST api.vk.com/method/messages.send, форма с v=5.199, peer_id, random_id, ключ в теле",
      req.url == "https://api.vk.com/method/messages.send" and params["v"] == API_VERSION == "5.199"
      and params["peer_id"] == "987" and params["random_id"] == "12345" and "vk1.a.secret" not in req.url)
check("9. VK: живой ответ без ключа (15) -> no_permission; 901 -> recipient_not_allowed; 912 -> messages_off",
      vk.parse_response(200, b'{"error":{"error_code":15,"error_msg":"Access denied: token required"}}').reason == M.REASON_NO_PERMISSION
      and vk.parse_response(200, b'{"error":{"error_code":901,"error_msg":"x"}}').reason == M.REASON_RECIPIENT_NOT_ALLOWED
      and vk.parse_response(200, b'{"error":{"error_code":912,"error_msg":"x"}}').reason == M.REASON_MESSAGES_OFF)
req = wa.build_request({"access_token": "EAAGtoken", "phone_number_id": "1234567890", "to": "+7 (900) 123-45-67"}, "Привет")
body = json.loads(req.body)
check("10. WhatsApp: POST graph.facebook.com/<версия>/<phone_number_id>/messages, Bearer, тело по документации",
      req.url == "https://graph.facebook.com/%s/1234567890/messages" % GRAPH_VERSION
      and req.headers["Authorization"] == "Bearer EAAGtoken"
      and body == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "79001234567",
                   "type": "text", "text": {"preview_url": False, "body": "Привет"}})
check("11. WhatsApp: 131047 (окно 24 часов) -> recipient_not_allowed; 190 -> bad_token",
      wa.parse_response(400, b'{"error":{"message":"x","code":131047,"error_data":{"details":"More than 24 hours"}}}').reason == M.REASON_RECIPIENT_NOT_ALLOWED
      and wa.parse_response(401, b'{"error":{"message":"expired","code":190}}').reason == M.REASON_BAD_TOKEN)

# ── 3. Мастер подключения: Telegram ───────────────────────────────────────────────────────
print("\n--- 3. Мастер подключения: Telegram ---")


class FakeNet(object):
    """Поддельная сеть: ответ по хвосту адреса; журнал вызовов; программируемые сценарии."""

    def __init__(self):
        self.calls = []
        self.updates_calls = 0
        self.code = None
        self.mode = "ok"
        self.now = int(time.time())

    def __call__(self, req):
        tail = req.url.rsplit("/", 1)[-1]
        self.calls.append((tail, req.body))
        if tail == "getMe":
            if self.mode == "bad_token":
                return 401, b'{"ok":false,"error_code":401,"description":"Unauthorized"}'
            return 200, b'{"ok":true,"result":{"id":1,"is_bot":true,"first_name":"Farm","username":"farm_alerts_bot"}}'
        if tail == "deleteWebhook":
            self.mode = "ok"
            return 200, b'{"ok":true,"result":true}'
        if tail == "getUpdates":
            self.updates_calls += 1
            if self.mode == "webhook" and self.updates_calls == 1:
                return 409, b'{"ok":false,"error_code":409,"description":"Conflict: can\'t use getUpdates method while webhook is active"}'
            if self.mode == "silent":
                return 200, b'{"ok":true,"result":[]}'
            if self.updates_calls < 2:
                return 200, b'{"ok":true,"result":[]}'
            if self.mode == "other_text":
                msg = {"message_id": 1, "date": self.now + 1, "chat": {"id": 555, "type": "private", "first_name": "Алексей", "last_name": "С."}, "text": "привет"}
            elif self.mode == "old_group":
                msg = {"message_id": 1, "date": self.now - 3600, "chat": {"id": -100777, "type": "supergroup", "title": "Старая группа"}, "text": "давно"}
            else:
                msg = {"message_id": 1, "date": self.now + 1, "chat": {"id": 555, "type": "private", "first_name": "Алексей", "last_name": "С."}, "text": "/start " + str(self.code)}
            return 200, json.dumps({"ok": True, "result": [{"update_id": 10 + self.updates_calls, "message": msg}]}).encode("utf-8")
        if tail == "sendMessage":
            return 200, b'{"ok":true,"result":{"message_id":2}}'
        return 404, b"nope"


def mk_stack(net, clock=None):
    store = ST.SettingsStore(os.path.join(tmp, "db_%d.db" % len(os.listdir(tmp))), reg.secret_keys())
    svc = SV.MessengerService(reg, store.read_config, store.write_config, None, None, transport=net,
                              clock=clock)
    pm = PR.PairingManager(reg, svc, lambda kind, patch: svc.update_settings({"channels": {kind: patch}})["saved"],
                           None, transport=net, clock=clock)
    return store, svc, pm


def wait_state(pm, kind, states, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = pm.status(kind)
        if st.get("state") in states:
            return st
        time.sleep(0.05)
    return pm.status(kind)


net = FakeNet()
store, svc, pm = mk_stack(net)
st = pm.start("telegram", "123456:ABCDEFGH")
net.code = st["link"].split("start=")[1]
check("12. ключ проверен через getMe: состояние waiting, ссылка t.me/<бот>?start=<код>, имя бота",
      st["state"] == "waiting" and st["link"].startswith("https://t.me/farm_alerts_bot?start=") and st["bot_name"] == "@farm_alerts_bot", st)
st = wait_state(pm, "telegram", ("paired", "error", "timeout"))
check("13. нажатие Start (/start <код>) поймано -> paired, получатель назван", st["state"] == "paired" and st["target_name"] == "Алексей С.", st)
cfg = store.read_config()
ch = cfg["channels"]["telegram"]
check("14. chat_id и имя бота сохранены САМИ, канал включён", ch["chat_id"] == "555" and ch["bot_username"] == "farm_alerts_bot" and ch["enabled"] is True, ch)
check("15. пробное сообщение ушло в этот чат сразу после привязки",
      any(t == "sendMessage" and json.loads(b)["chat_id"] == 555 for t, b in net.calls))
check("16. ключ лежит отдельно от настроек: в таблице настроек его нет, в конфиге для отправки — есть",
      "ABCDEFGH" not in json.dumps(store.public_raw()) and ch["bot_token"] == "123456:ABCDEFGH")
check("17. порядок вызовов: getMe -> getUpdates… -> sendMessage", [t for t, _ in net.calls][:2] == ["getMe", "getUpdates"] and net.calls[-1][0] == "sendMessage")

net2 = FakeNet(); net2.mode = "other_text"
store2, svc2, pm2 = mk_stack(net2)
st = pm2.start("telegram", "123456:ABCDEFGH"); net2.code = st["link"].split("start=")[1]
st = wait_state(pm2, "telegram", ("paired", "error", "timeout"))
net_msg = FakeNet()
store_msg, _, pm_msg = mk_stack(net_msg)
st = pm_msg.start("telegram", BOTFATHER_MSG)
net_msg.code = st["link"].split("start=")[1] if st.get("link") else ""
st = wait_state(pm_msg, "telegram", ("paired", "error", "timeout"))
check("17б. мастер принял ЦЕЛОЕ сообщение BotFather: ключ вычленен, подключение прошло",
      st["state"] == "paired"
      and store_msg.read_config()["channels"]["telegram"]["bot_token"] == "8123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw", st)

check("18. человек написал боту что-то своё (не через ссылку) — свежее личное сообщение тоже подходит",
      st["state"] == "paired" and store2.read_config()["channels"]["telegram"]["chat_id"] == "555", st)

net3 = FakeNet(); net3.mode = "old_group"
store3, svc3, pm3 = mk_stack(net3, clock=lambda: 1000.0)
st = pm3.start("telegram", "123456:ABCDEFGH"); net3.code = st["link"].split("start=")[1]
time.sleep(0.6)
check("19. старое сообщение из чужой группы без кода НЕ привязывает (ждём дальше)",
      pm3.status("telegram")["state"] == "waiting" and not store3.read_config()["channels"]["telegram"].get("chat_id"))
pm3.stop("telegram")
check("20. отмена мастера -> stopped", wait_state(pm3, "telegram", ("stopped",))["state"] == "stopped")

net4 = FakeNet(); net4.mode = "bad_token"
_, _, pm4 = mk_stack(net4)
st = pm4.start("telegram", "wrong")
check("21. неверный ключ: сразу error/bad_token, поток не запускается, в сеть — только getMe",
      st["state"] == "error" and st["reason"] == M.REASON_BAD_TOKEN and [t for t, _ in net4.calls] == ["getMe"], st)

net5 = FakeNet(); net5.mode = "webhook"
store5, _, pm5 = mk_stack(net5)
st = pm5.start("telegram", "123456:ABCDEFGH"); net5.code = st["link"].split("start=")[1]
st = wait_state(pm5, "telegram", ("paired", "error", "timeout"))
check("22. у бота включён webhook (409): модуль сам делает deleteWebhook и продолжает -> paired",
      st["state"] == "paired" and "deleteWebhook" in [t for t, _ in net5.calls], st)

clk = {"t": 0.0}
net6 = FakeNet(); net6.mode = "silent"
_, _, pm6 = mk_stack(net6, clock=lambda: clk["t"])
pm6.start("telegram", "123456:ABCDEFGH")
clk["t"] = PR.PAIR_WINDOW_S + 1
check("23. никто не нажал Start за 10 минут -> timeout (поток завершился сам)",
      wait_state(pm6, "telegram", ("timeout",))["state"] == "timeout")
check("24. пустой ключ -> not_configured без сети", pm6.start("telegram", "  ")["reason"] == M.REASON_NOT_CONFIGURED)
check("25. у WhatsApp мастера нет -> unknown_kind", pm6.start("whatsapp", "x")["reason"] == M.REASON_UNKNOWN_KIND)

# ── 4. Мастер подключения: VK ─────────────────────────────────────────────────────────────
print("\n--- 4. Мастер подключения: VK ---")


class FakeVk(object):
    def __init__(self, perms=("messages",), old=False):
        self.calls = []
        self.perms = perms
        self.old = old
        self.n = 0
        self.now = int(time.time())

    def __call__(self, req):
        method = req.url.rsplit("/", 1)[-1]
        p = dict(urllib.parse.parse_qsl(req.body.decode("utf-8")))
        self.calls.append((method, p))
        if method == "groups.getTokenPermissions":
            return 200, json.dumps({"response": {"mask": 4096, "permissions": [{"setting": 4096, "name": n} for n in self.perms]}}).encode()
        if method == "groups.getById":
            return 200, json.dumps({"response": {"groups": [{"id": 123, "name": "Моя ферма", "screen_name": "club123"}]}}).encode()
        if method == "messages.getConversations":
            self.n += 1
            if self.n < 2:
                return 200, b'{"response":{"count":0,"items":[]}}'
            date = self.now - 3600 if self.old else self.now + 1
            return 200, json.dumps({"response": {"count": 1, "items": [
                {"conversation": {"peer": {"id": 42, "type": "user", "local_id": 42}},
                 "last_message": {"from_id": 42, "date": date, "text": "Старт"}}],
                "profiles": [{"id": 42, "first_name": "Иван", "last_name": "Петров"}]}}).encode()
        if method == "messages.send":
            return 200, b'{"response":777}'
        return 404, b"nope"


vnet = FakeVk()
vstore, vsvc, vpm = mk_stack(vnet)
st = vpm.start("vk", "vk1.a.secret")
check("26. ключ проверен: право «messages» есть, сообщество найдено, ссылка vk.me/club<id>",
      st["state"] == "waiting" and st["link"] == "https://vk.me/club123" and st["bot_name"] == "Моя ферма", st)
check("27. запросы по схеме 5.199: v и access_token в теле каждого вызова",
      all(p.get("v") == "5.199" and p.get("access_token") == "vk1.a.secret" for _, p in vnet.calls))
st = wait_state(vpm, "vk", ("paired", "error", "timeout"))
vch = vstore.read_config()["channels"]["vk"]
check("28. первое свежее сообщение человека -> paired: peer_id, имя из profiles, сообщество, канал включён",
      st["state"] == "paired" and vch["peer_id"] == "42" and vch["peer_title"] == "Иван Петров"
      and vch["group_id"] == "123" and vch["group_name"] == "Моя ферма" and vch["enabled"] is True, vch)
check("29. getConversations запрошен с extended=1 (иначе имени не узнать) и пробное ушло в peer 42",
      any(m == "messages.getConversations" and p.get("extended") == "1" for m, p in vnet.calls)
      and any(m == "messages.send" and p.get("peer_id") == "42" for m, p in vnet.calls))
check("30. ключ VK не попал в таблицу настроек", "vk1.a.secret" not in json.dumps(vstore.public_raw()))

vnet2 = FakeVk(perms=("photos",))
_, _, vpm2 = mk_stack(vnet2)
st = vpm2.start("vk", "vk1.a.secret")
check("31. ключ без права «сообщения сообщества» -> error/no_permission ещё до ожидания",
      st["state"] == "error" and st["reason"] == M.REASON_NO_PERMISSION, st)

vnet3 = FakeVk(old=True)
vstore3, _, vpm3 = mk_stack(vnet3, clock=lambda: 1000.0)
vpm3.start("vk", "vk1.a.secret")
time.sleep(PR.VK_POLL_INTERVAL_S + 0.8)
check("32. старый диалог (сообщение до начала подключения) не привязывает",
      vpm3.status("vk")["state"] == "waiting" and not vstore3.read_config()["channels"]["vk"].get("peer_id"))
vpm3.stop("vk")

# ── 5. Хранилище и настройки ──────────────────────────────────────────────────────────────
print("\n--- 5. Хранилище ---")
st5 = ST.SettingsStore(os.path.join(tmp, "s5.db"), reg.secret_keys())
cfg, _ = S.apply_patch(None, {"channels": {"telegram": {"enabled": True, "bot_token": "123456:ABCDEFGH", "chat_id": "5"},
                                            "vk": {"access_token": "vk1.a.X", "peer_id": "7"}}}, reg)
st5.write_config(cfg)
raw = st5.public_raw()
check("33. секреты в msg_settings не пишутся (обе площадки)", "ABCDEFGH" not in json.dumps(raw) and "vk1.a.X" not in json.dumps(raw))
back = st5.read_config()
check("34. чтение собирает конфиг обратно с ключами", back["channels"]["telegram"]["bot_token"] == "123456:ABCDEFGH" and back["channels"]["vk"]["access_token"] == "vk1.a.X")
cfg2, _ = S.apply_patch(back, {"channels": {"telegram": {"bot_token": None}}}, reg)
st5.write_config(cfg2)
check("35. стирание ключа удаляет строку из msg_secrets", not st5.read_config()["channels"]["telegram"].get("bot_token"))
view = S.public_view(back, reg)
check("36. показ без секретов: connected и подпись «куда подключено»",
      view["channels"]["telegram"]["bot_token"] == "" and view["channels"]["telegram"]["bot_token_set"] is True
      and view["channels"]["telegram"]["connected"] is True and "ABCDEFGH" not in json.dumps(view))
cfg3, ch3 = S.apply_patch(back, {"channels": {"telegram": {"bot_token": "", "chat_id": "5"}}}, reg)
check("37. пустой секрет из формы прежний ключ не стирает", cfg3["channels"]["telegram"]["bot_token"] == "123456:ABCDEFGH" and ch3 == [])

# ── 6. Диспетчер (коротко: остальное доказано мастером) ──────────────────────────────────
print("\n--- 6. Диспетчер ---")
sent = []


def fake_send(req):
    sent.append(req)
    return 200, b'{"ok":true,"result":{"message_id":1}}'


clock = {"t": 1000.0}
st6 = ST.SettingsStore(os.path.join(tmp, "s6.db"), reg.secret_keys())
st6.write_config(S.apply_patch(None, {"channels": {"telegram": {"enabled": True, "bot_token": "123456:ABCDEFGH", "chat_id": "5"}}}, reg)[0])
svc6 = SV.MessengerService(reg, st6.read_config, st6.write_config, lambda pid: "H2D_01", None, transport=fake_send, clock=lambda: clock["t"])
FIN = {"outcome_raw": "finished", "printer_id": "b1", "printer_name": "H2D_01", "filename": "bracket.3mf", "elapsed_s": 8100, "run_id": "r1"}
#  2.1007: текст идёт по шаблону — принтер сверху, файл отдельной строкой, статус последним.
check("38. хук print_run_finished -> сообщение «Печать завершена» с файлом и длительностью по новой раскладке",
      svc6.on_run_finished(FIN) and svc6.process_pending() == 1
      and json.loads(sent[-1].body)["text"].split("\n") == ["🖨 H2D_01", "📄 «bracket.3mf»", "✅ Печать завершена · 2 ч 15 мин"],
      json.loads(sent[-1].body)["text"] if sent else "")
check("39. повтор в окне 10 минут не шлётся; после — шлётся", svc6.on_run_finished(FIN) is False and (clock.__setitem__("t", 1700.0) or svc6.on_run_finished(FIN)))
svc6.process_pending()
n0 = len(sent)
svc6.observe({"b1": {"status": "RUNNING", "device_error": None, "hms": []}}, now=clock["t"])
svc6.observe({"b1": {"status": "FAILED", "device_error": "0300-8010", "hms": [{"code": "0C00-0100-0001-0004", "severity": "fatal", "module": "xcam"}]}}, now=clock["t"] + 2)
svc6.process_pending()
texts = [json.loads(r.body)["text"] for r in sent[n0:]]
check("40. наблюдатель: ошибка принтера и критичное уведомление -> два сообщения", len(texts) == 2 and any("0300-8010" in t for t in texts) and any("0C00-0100-0001-0004" in t for t in texts), texts)
svc7 = SV.MessengerService(reg, st6.read_config, st6.write_config, None, None, transport=fake_send, clock=lambda: clock["t"])
svc7.observe({"b2": {"status": "FAILED", "device_error": "0300-8010"}}, now=0)
svc7.process_pending()
check("41. первый снимок принтера — база: старые ошибки при старте не пересылаются", len(sent) == n0 + 2)

# ── 7. Backend модуля в поддельном ядре ──────────────────────────────────────────────────
print("\n--- 7. Backend модуля ---")


class FakeCore(object):
    def __init__(self):
        self.module_id = "messengers"
        self.module_dir = MOD_DIR
        self.module_version = "0.1.8"
        self.routes = []
        self.hooks = {}
        self._states = {}

    def resolve_db(self, name):
        return os.path.join(tmp, name)

    def add_route(self, path, fn, methods, policy_id=None):
        self.routes.append({"rel": path, "fn": fn, "methods": [str(m).upper() for m in methods], "policy_id": policy_id,
                            "full": "/api/mod/messengers/" + path})
        return "/api/mod/messengers/" + path

    def add_hook(self, name, fn):
        self.hooks[name] = fn
        return True

    def printers(self):
        return [{"id": "b1", "name": "H2D_01", "type": "bambu"}]

    def printer_states(self):
        return self._states


spec = importlib.util.spec_from_file_location("fm_module_messengers_test", os.path.join(MOD_DIR, "backend.py"))
BE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BE)
fc = FakeCore()
BE.register(fc)
check("42. register(core): 6 маршрутов, у каждого policy_id, ровно один метод",
      len(fc.routes) == 6 and all(r["policy_id"] and len(r["methods"]) == 1 for r in fc.routes), [(r["rel"], r["methods"]) for r in fc.routes])
check("43. подписка на print_run_finished и рабочие объекты созданы", "print_run_finished" in fc.hooks and BE._svc is not None and BE._pair is not None and BE._store is not None)
check("44. поток наблюдения запущен", any(t.name == "messengers-observe" and t.is_alive() for t in threading.enumerate()))

# те же проверки, что _module_routes_validate ядра (правила скопированы дословно)
errs = []
seen = set()
for d in fc.routes:
    pid = d["policy_id"]
    pol = RPR.module_policy_by_id(pid)
    if pol is None:
        errs.append("%s: политика не найдена" % pid); continue
    if pid in seen:
        errs.append("%s: дважды" % pid)
    seen.add(pid)
    if pol.module_id != "messengers":
        errs.append("%s: чужой модуль" % pid)
    if pol.module_version != "0.1.8":
        errs.append("%s: версия %s" % (pid, pol.module_version))
    if pol.method != d["methods"][0]:
        errs.append("%s: метод" % pid)
    if pol.module_route != d["rel"]:
        errs.append("%s: относительный путь" % pid)
    if pol.path != d["full"]:
        errs.append("%s: итоговый путь" % pid)
    if pol.handler != getattr(d["fn"], "__name__", ""):
        errs.append("%s: обработчик %s != %s" % (pid, pol.handler, getattr(d["fn"], "__name__", "")))
    if pol.enforcement_stage.value != "MODULE_2_785":
        errs.append("%s: этап %s" % (pid, pol.enforcement_stage))
    if pol.enforced_access.value != "CAPABILITY" or pol.required_capability != "admin":
        errs.append("%s: право %s/%s" % (pid, pol.enforced_access, pol.required_capability))
check("45. КЛЮЧЕВОЕ: все объявленные маршруты проходят проверки ядра по реестру прав (модуль загрузится целиком)", not errs, errs)
check("46. версия в манифесте совпадает с реестром (иначе ядро откажет модулю)",
      #  13.10.2026: сверяется КОНТРАКТ манифеста (core_contract) — выпуск 0.1.9 сменил поведение, а не
      #  маршруты; без core_contract контрактом служит номер выпуска.
      (json.loads(rd("modules", "messengers", "module.json")).get("core_contract")
       or json.loads(rd("modules", "messengers", "module.json"))["version"]) == "0.1.8"
      and all(p.module_version == "0.1.8" for p in RPR.MODULE_POLICIES if p.module_id == "messengers")
      and sum(1 for p in RPR.MODULE_POLICIES if p.module_id == "messengers") == 6)
check("47. все шесть маршрутов — только администратору (адреса получателей, ключи, сеть)",
      all(p.required_capability == "admin" for p in RPR.MODULE_POLICIES if p.module_id == "messengers"))


class FakeReq(object):
    def __init__(self, body=None, query=None):
        self._body = body
        self.query_params = dict(query or {})

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


run = asyncio.run
BE._svc._send = fake_send
BE._pair._send = FakeNet()
j = run(BE.api_msg_settings_get(FakeReq(query={"lang": "ru"})))
check("48. GET settings: конверт ok, настройки без секретов, каталог с мастером, состояние мастера",
      j["status"] == "ok" and "catalog" in j and "pairing" in j and j["settings"]["channels"]["telegram"]["bot_token"] == "")
j = run(BE.api_msg_settings_set(FakeReq({"events": {"print_cancelled": True}, "lang": "en"})))
check("49. POST settings: частичная правка сохраняется", j["status"] == "ok" and j["settings"]["events"]["print_cancelled"] is True and j["settings"]["lang"] == "en")
j = run(BE.api_msg_test(FakeReq({"kind": "telegram"})))
check("50. POST test без подключённого канала -> error/not_configured (сеть не трогается)", j["status"] == "error" and j["result"]["reason"] == M.REASON_NOT_CONFIGURED)
BE._pair._send.mode = "ok"
j = run(BE.api_msg_pair_start(FakeReq({"kind": "telegram", "token": "123456:ABCDEFGH"})))
BE._pair._send.code = j["pairing"]["link"].split("start=")[1]
check("51. POST pair/start: ok + waiting + ссылка", j["status"] == "ok" and j["pairing"]["state"] == "waiting" and "t.me/" in j["pairing"]["link"], j)
wait_state(BE._pair, "telegram", ("paired", "error", "timeout"))
j = run(BE.api_msg_pair_status(FakeReq(query={"kind": "telegram"})))
check("52. GET pair/status: paired, получатель назван", j["pairing"]["state"] == "paired" and j["pairing"]["target_name"], j)
j = run(BE.api_msg_settings_get(FakeReq(query={})))
check("53. после мастера канал Telegram подключён и включён, подпись «@бот → человек»",
      j["settings"]["channels"]["telegram"]["connected"] is True and j["settings"]["channels"]["telegram"]["enabled"] is True
      and "farm_alerts_bot" in j["settings"]["channels"]["telegram"]["connected_label"], j["settings"]["channels"]["telegram"])
j = run(BE.api_msg_test(FakeReq({"kind": "telegram"})))
check("54. POST test теперь доставляет", j["status"] == "ok" and j["result"]["ok"] is True)
j = run(BE.api_msg_pair_stop(FakeReq({"kind": "vk"})))
check("55. POST pair/stop на незапущенном мастере — безвредно", j["status"] == "ok")
j = run(BE.api_msg_settings_set(FakeReq(None)))
check("56. битое тело -> не падает, ничего не меняет", j["status"] == "ok" and j["changed"] == [])

# ── 8. Настоящий HTTP до поддельного сервера ─────────────────────────────────────────────
print("\n--- 8. Транспорт ---")


class _H(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        _H.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, raw))
        if self.path.endswith("/getMe"):
            code, body = 200, b'{"ok":true,"result":{"id":1,"username":"farm_alerts_bot"}}'
        elif self.path.endswith("/sendMessage"):
            code, body = 200, b'{"ok":true,"result":{"message_id":9}}'
        elif self.path.endswith("/method/messages.send"):
            code, body = 200, b'{"error":{"error_code":901,"error_msg":"Can\'t send messages for users without permission"}}'
        else:
            code, body = 404, b"nope"
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), _H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % port
reg2 = R.default_registry({"telegram": base, "vk": base})
st8 = ST.SettingsStore(os.path.join(tmp, "s8.db"), reg2.secret_keys())
st8.write_config(S.apply_patch(None, {"channels": {"telegram": {"enabled": True, "bot_token": "123456:ABCDEFGH", "chat_id": "5"},
                                                    "vk": {"enabled": True, "access_token": "vk1.a.secret", "peer_id": "987"}}}, reg2)[0])
svc8 = SV.MessengerService(reg2, st8.read_config, st8.write_config, None, None)
r = svc8.send_test("telegram")
check("57. НАСТОЯЩИЙ HTTP: /bot<token>/sendMessage дошёл, наш User-Agent, ответ разобран",
      r.ok and r.message_id == 9 and any(p == "/bot123456:ABCDEFGH/sendMessage" and h.get("user-agent") == "3DIWELL-FarmManager-messengers" for p, h, _ in _H.seen), (r, [x[0] for x in _H.seen]))
r = svc8.send_test("vk")
check("58. VK через настоящий HTTP: форма дошла, 901 разобран", r.reason == M.REASON_RECIPIENT_NOT_ALLOWED)
pm8 = PR.PairingManager(reg2, svc8, lambda k, p: True, None)
ok8, data8 = pm8._api(reg2.get("telegram"), {"bot_token": "123456:ABCDEFGH"}, "getMe", {})
check("59. вызов API мастера через настоящий HTTP: getMe разобран", ok8 and data8.get("username") == "farm_alerts_bot", data8)
srv.shutdown()
check("60. нет связи -> network, а не падение",
      SV.MessengerService(R.default_registry({"telegram": "http://127.0.0.1:1"}), st8.read_config, st8.write_config, None, None).send_test("telegram").reason == M.REASON_NETWORK)

# ── 9. Ядро: провайдер копии, карта БД, реестры, чистота ─────────────────────────────────
print("\n--- 9. Ядро и упаковка ---")
prov = MP.get_provider("messengers")
check("61. провайдер резервной копии модуля зарегистрирован: настройки без секретов, msg_secrets в спеках нет",
      prov is not None and prov.data_class == MP.DATA_CLASS_PROVIDER and prov.settings_source == "msg_settings"
      and prov.table_specs == () and MP.check_export_completeness(["inventory", "cost", "quality", "messengers"]) == [])
snap = prov.export_snapshot(MP.DictModuleStore(settings={"config": json.dumps({"lang": "ru", "channels": {"telegram": {"enabled": True, "chat_id": "5"}}})}), installed_version="0.1.8")
check("62. снимок копии: канонический JSON настроек, ключей нет", snap["settings"]["config"] and "bot_token" not in snap["settings"]["config"] and prov.validate_snapshot(snap))
SRC = rd("server.py")
check("63. карта БД модулей в ядре знает farm_messengers.db / msg_settings", '"messengers": ("farm_messengers.db", "msg_settings", ("key", "value"))' in SRC)
check("64. ядро чистое: встроенной версии 2.993 не осталось (маршруты, диспетчер, карточка, стили, раздел настроек)",
      "/api/messengers/" not in SRC and "_MSG." not in SRC and "_msg_service" not in SRC and not os.path.isdir(os.path.join(REPO, "app", "messengers"))
      and 'id="fm-sec-msg"' not in rd("web", "index.html") and "msgLoad" not in rd("web", "app.js")
      and ".fm-msg-" not in rd("web", "app.css") and "/api/messengers/" not in rd("app", "route_policy_registry.py")
      and '_s("messengers"' not in rd("app", "config_backup", "settings_registry.py"))
check("65. переводы уведомлений принтера остались в ядре (модуль читает их при наличии)", "HMS_KNOWN_TEXT" in rd("app", "printer_health_policy.py"))
mj = json.loads(rd("modules", "messengers", "module.json"))
#  2.1002 (заказ владельца 11.09.2026): у модуля ОДНИ НАСТРОЙКИ, своего окна он не имеет.
#  В манифесте это выражено прямо: entry НЕТ, есть только settings_entry. Ядро такой модуль
#  не выводит ни окном, ни кнопкой на баре — он живёт ячейкой во вкладке «Настройки → Модули».
check("66. манифест: id, версия, иконка из набора ядра — и НИКАКОГО entry",
      mj["id"] == "messengers" and mj["version"] == __import__("app.module_catalog", fromlist=["x"]).KNOWN_MODULE_RELEASES.get("messengers")
      and "entry" not in mj
      and mj["settings_entry"] == "web/MessengersSettings.js"
      and ("  %s:" % mj["icon"]) in rd("web", "design", "icons.js"))
PANEL = rd("modules", "messengers", "web", "MessengersPanel.js")
SET = rd("modules", "messengers", "web", "MessengersSettings.js")
check("67. ячейка настроек: default-export, props lang/access, вызовы /api/mod/messengers/",
      "export default" in SET and "MESSENGERS_PROPS" in SET and "access:" in PANEL
      and "/api/mod/messengers/" in PANEL)
check("67а. окна у модуля больше НЕТ: ни оболочки с наложением, ни default-export в реализации",
      "teleport" not in PANEL and "export default" not in PANEL and "$emit('close')" not in PANEL)
check("67б. реализация общая: логика, свойства и содержимое вынесены и берутся ячейкой",
      all(x in PANEL for x in ("export function useMessengers", "MESSENGERS_BODY", "MESSENGERS_PROPS"))
      and "from './MessengersPanel.js'" in SET)
check("68. право — только через contract ядра: props.access.can('admin'), без своей таблицы ролей",
      "props.access.can(cap)" in PANEL and "can('admin')" in PANEL and "role ===" not in PANEL and "=== 'admin'" not in PANEL)
check("69. мастер в окне: кнопки «Подключить», ссылка на сайт площадки, ввод ключа, «Открыть бота», «Готово»",
      all(m in PANEL for m in ("data-msg-connect", "data-msg-token", "data-msg-next", "data-msg-open", "data-msg-done", "data-msg-wizard")))
check("70. секреты окно не хранит: после сохранения поля ключей очищаются", "if (f.secret && adv[kind]) adv[kind][f.key] = ''" in PANEL)
check("70б. в окне есть кнопка «Назад» между шагами (раньше вернуться к ссылке было нечем)",
      "data-msg-back" in PANEL and "const prevStep" in PANEL and "pair/stop" in PANEL)
check("70в. готовый адрес бота с кнопкой «Копировать» — придумывать адрес не нужно",
      "data-msg-suggest" in PANEL and "data-msg-copy" in PANEL and "suggestBotUsername" in PANEL
      and "_bot'" in PANEL)
check("70г. сверху окна — короткая справка, почему один шаг делается руками",
      "data-msg-how" in PANEL and "защита от рассылок" in PANEL)
check("70д. переводы строк в шагах видны как строки (иначе инструкция слипается в абзац)",
      "white-space:pre-line" in PANEL)
check("70е. на шаге ключа есть вторая кнопка на площадку (data-msg-site)",
      PANEL.count("data-msg-site") >= 2)
check("70ж. шаг-инструкция без поля ввода отрисовывается (у VK таких два)",
      'v-if="s.next"' in PANEL and "s.link_url" in PANEL)
check("70з. мастер не привязан к трём шагам: последний считается от длины списка",
      "const lastStep" in PANEL and "lastStep(kind)" in PANEL and "wiz[p.kind].step = 2;" not in PANEL)
sys.path.insert(0, os.path.join(REPO, "tools"))
import build_messengers_zip as BZ  # noqa: E402
out, names, mj2 = BZ.build(os.path.join(tmp, "3diwell-module-messengers.zip"))
check("71. ZIP собирается: манифест, backend, библиотека, окно; мусора нет",
      "messengers/module.json" in names and "messengers/backend.py" in names and "messengers/fm_messengers/pairing.py" in names
      and "messengers/web/MessengersPanel.js" in names and not any(n.endswith((".pyc", ".db")) for n in names), names)
check("72. в ZIP нет файлов БД и __pycache__", not any("__pycache__" in n or n.endswith(".db") for n in names))
check("73. module.json лежит в единственной верхней папке (как ждёт установщик ядра)", all(n.startswith("messengers/") for n in names))
check("74. модуль не импортирует ядро и не держит своих прав",
      "import server" not in rd("modules", "messengers", "backend.py") and "_ROLE_PERMS" not in rd("modules", "messengers", "backend.py"))
#  26.09.2026: AGENTS.md — карта для ИИ-помощников закрытого репозитория; в открытой выгрузке её нет.
if os.path.isfile(os.path.join(REPO, "AGENTS.md")):
    check("75. AGENTS.md знает про модуль", "messengers" in rd("AGENTS.md"))
else:
    print("SKIP — 75. AGENTS.md в этой копии нет (открытая выгрузка)")

# ── MAX (2.1006): мастер подключения и отправка ────────────────────────────────────────────
#  Контракт — dev.max.ru/docs-api (12.09.2026): ключ в заголовке Authorization, /me, /updates
#  с marker и типами bot_started/message_created (время в миллисекундах, payload из ссылки
#  https://max.ru/<бот>?start=<код>), POST /messages?chat_id= с телом {"text"} и ответом
#  {"message": {...}}. Ошибка — {"error","code","message"} c HTTP-кодом.
print("\n--- MAX: мастер подключения и отправка ---")
from fm_messengers.max import MaxProvider   # noqa: E402

MAX_TOKEN = "tok_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class FakeMax(object):
    """Поддельная платформа MAX: журнал вызовов, сценарии ok / message / old / bad_token / rate."""

    def __init__(self, mode="ok"):
        self.calls = []
        self.mode = mode
        self.updates_calls = 0
        self.code = None
        self.now_ms = int(time.time() * 1000)

    def __call__(self, req):
        u = urllib.parse.urlsplit(req.url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.calls.append((u.path, q, req.headers.get("Authorization"), req.body))
        if req.headers.get("Authorization") != MAX_TOKEN or self.mode == "bad_token":
            return 401, json.dumps({"error": "unauthorized", "code": "unauthorized",
                                    "message": "Ошибка авторизации. Токен access_token указан некорректно или недействителен"}).encode()
        if u.path == "/me":
            return 200, json.dumps({"user_id": 7, "first_name": "Ферма", "username": "ferma_bot", "is_bot": True,
                                    "last_activity_time": self.now_ms}).encode()
        if u.path == "/updates":
            self.updates_calls += 1
            if self.mode == "rate" and self.updates_calls == 1:
                return 429, json.dumps({"error": "too.many.requests", "code": "too.many.requests", "message": "slow down"}).encode()
            if self.updates_calls < 2 or self.mode == "silent":
                return 200, json.dumps({"updates": [], "marker": 100}).encode()
            user = {"user_id": 42, "first_name": "Алексей", "last_name": "С.", "username": "alex", "is_bot": False}
            if self.mode == "message":
                upd = {"update_type": "message_created", "timestamp": self.now_ms + 1000, "user_locale": "ru",
                       "message": {"sender": user, "recipient": {"chat_id": 9001, "chat_type": "dialog", "user_id": 42},
                                   "timestamp": self.now_ms + 1000, "body": {"mid": "mid.1", "seq": 1, "text": "привет"}}}
            elif self.mode == "old":
                upd = {"update_type": "bot_started", "timestamp": self.now_ms - 3600 * 1000, "chat_id": 9002,
                       "user": user, "payload": "", "user_locale": "ru"}
            else:
                upd = {"update_type": "bot_started", "timestamp": self.now_ms + 1000, "chat_id": 9001,
                       "user": user, "payload": self.code or "", "user_locale": "ru"}
            return 200, json.dumps({"updates": [upd], "marker": 100 + self.updates_calls}).encode()
        if u.path == "/messages":
            body = json.loads(req.body.decode("utf-8"))
            return 200, json.dumps({"message": {"sender": {"user_id": 7, "is_bot": True},
                                                "recipient": {"chat_id": int(q.get("chat_id") or 0), "chat_type": "dialog",
                                                              "user_id": int(q.get("user_id") or 42)},
                                                "timestamp": self.now_ms + 2000,
                                                "body": {"mid": "mid.777", "seq": 2, "text": body.get("text")}}}).encode()
        return 404, json.dumps({"error": "not.found", "code": "not.found", "message": "no such method"}).encode()


mx = reg.get("max")
mcat = [c for c in cat if c["kind"] == "max"][0]
check("M1. MAX в каталоге: мастер из трёх шагов — сайт платформы, ключ, Start; ссылка на официальную инструкцию",
      isinstance(mx, MaxProvider) and mcat["has_wizard"] and len(mcat["wizard"]) == 3
      and mcat["wizard"][0].get("url", "").startswith("https://business.max.ru")
      and "dev.max.ru" in mcat["wizard"][0].get("link_url", "")
      and mcat["wizard"][1].get("input") == "token" and mcat["wizard"][2].get("wait"), mcat["wizard"])
_w0 = mcat["wizard"][0]["text"]
check("M2. первый шаг честен: проверенный профиль (ИП/самозанятый/организация), модерация и статус «Опубликован»",
      all(x in _w0 for x in ("ПРОВЕРЕННЫЙ", "ИП", "самозанят", "модерац", "Опубликован", "Чат-боты"))
      and "BotFather" in _w0, _w0[:120])
check("M3. в описании нет привязки к стране, кроме требования платформы (резидент РФ — это её правило, не наше)",
      "Росси" not in mcat["note"] and "Russia" not in mcat["note"])
_req = mx.build_request({"access_token": MAX_TOKEN, "chat_id": "9001"}, "Печать завершена")
check("M4. отправка по документации: POST platform-api2.max.ru/messages?chat_id=…, ключ ТОЛЬКО в заголовке, тело {text, notify}",
      _req.method == "POST" and _req.url.startswith("https://platform-api2.max.ru/messages?")
      and "chat_id=9001" in _req.url and "disable_link_preview=true" in _req.url
      and _req.headers.get("Authorization") == MAX_TOKEN and "Bearer" not in _req.headers.get("Authorization")
      and MAX_TOKEN not in _req.url and json.loads(_req.body.decode("utf-8")) == {"text": "Печать завершена", "notify": True}
      and MAX_TOKEN in _req.secrets, (_req.url, _req.headers))
check("M5. предел текста MAX — 4000 знаков (не 4096): длиннее режется с многоточием",
      mx.text_limit == 4000 and len(mx.prepare_text("x" * 5000)) == 4000 and mx.prepare_text("x" * 5000).endswith("…"))
check("M6. разбор ответа: {message.body.mid} -> ok с id; 401 -> bad_token; 404 -> bad_recipient; 429 -> rate_limited; 400 -> bad_request",
      mx.parse_response(200, b'{"message":{"body":{"mid":"mid.1","seq":1,"text":"x"}}}').message_id == "mid.1"
      and mx.parse_response(401, b'{"error":"unauthorized","code":"unauthorized","message":"bad"}').reason == M.REASON_BAD_TOKEN
      and mx.parse_response(404, b'{"code":"chat.not.found","message":"x"}').reason == M.REASON_BAD_RECIPIENT
      and mx.parse_response(429, b'{"code":"too.many.requests","message":"x"}').reason == M.REASON_RATE_LIMITED
      and mx.parse_response(400, b'{"code":"bad.request","message":"x"}').reason == M.REASON_BAD_REQUEST
      and mx.parse_response(503, b"<html>").reason == M.REASON_BAD_RESPONSE)
check("M7. ключ в ошибке вычищается (он стоит в заголовке, но и в тексте ошибки его быть не должно)",
      MAX_TOKEN not in M.clip_detail("boom " + MAX_TOKEN, (MAX_TOKEN,)))
check("M8. ключ вычленяется из вставленной строки с подписью", mx.extract_token("Токен: " + MAX_TOKEN + " (скопируйте)") == MAX_TOKEN)
check("M9. без chat_id слать нельзя (not_configured / bad_request), с числовым — можно",
      mx.validate({"access_token": MAX_TOKEN}) is not None and mx.validate({"access_token": MAX_TOKEN, "chat_id": "abc"}) is not None
      and mx.validate({"access_token": MAX_TOKEN, "chat_id": "9001"}) is None)

mnet = FakeMax()
mstore, msvc, mpm = mk_stack(mnet)
st = mpm.start("max", "Токен: " + MAX_TOKEN)
mnet.code = st["link"].split("start=")[1] if st.get("link") else ""
check("M10. ключ проверен через /me: waiting, ссылка https://max.ru/<никнейм>?start=<код>, имя бота",
      st["state"] == "waiting" and st["link"].startswith("https://max.ru/ferma_bot?start=") and st["bot_name"] == "@ferma_bot", st)
st = wait_state(mpm, "max", ("paired", "error", "timeout"))
mch = mstore.read_config()["channels"]["max"]
check("M11. bot_started с нашим кодом -> paired: chat_id и user_id сохранены сами, имя человека, канал включён",
      st["state"] == "paired" and st["target_name"] == "Алексей С." and mch["chat_id"] == "9001" and mch["user_id"] == "42"
      and mch["bot_username"] == "ferma_bot" and mch["enabled"] is True, (st, mch))
_paths = [c[0] for c in mnet.calls]
check("M12. порядок вызовов: /me -> /updates… -> /messages; пробное ушло в chat_id=9001 с ключом в заголовке",
      _paths[:2] == ["/me", "/updates"] and _paths[-1] == "/messages"
      and mnet.calls[-1][1].get("chat_id") == "9001" and mnet.calls[-1][2] == MAX_TOKEN, _paths)
_upd = [c for c in mnet.calls if c[0] == "/updates"]
check("M13. долгий опрос по документации: types=bot_started,message_created, timeout задан, marker из ответа передан дальше",
      len(_upd) >= 2 and _upd[0][1].get("types") == "bot_started,message_created" and _upd[0][1].get("timeout")
      and "marker" not in _upd[0][1] and _upd[1][1].get("marker") == "100", [u[1] for u in _upd[:2]])
check("M14. ключ MAX лежит отдельно: в таблице настроек его нет, в конфиге для отправки — есть",
      MAX_TOKEN not in json.dumps(mstore.public_raw()) and mch["access_token"] == MAX_TOKEN)

mnet2 = FakeMax(mode="message")
mstore2, _, mpm2 = mk_stack(mnet2)
st = mpm2.start("max", MAX_TOKEN); mnet2.code = st["link"].split("start=")[1]
st = wait_state(mpm2, "max", ("paired", "error", "timeout"))
check("M15. человек просто написал боту (message_created в диалоге, свежее) -> paired по recipient.chat_id",
      st["state"] == "paired" and mstore2.read_config()["channels"]["max"]["chat_id"] == "9001", st)

mnet3 = FakeMax(mode="old")
mstore3, _, mpm3 = mk_stack(mnet3, clock=lambda: 1000.0)
st = mpm3.start("max", MAX_TOKEN); mnet3.code = st["link"].split("start=")[1]
time.sleep(0.6)
check("M16. старое bot_started без кода (событие до начала подключения) НЕ привязывает — ждём дальше",
      mpm3.status("max")["state"] == "waiting" and not mstore3.read_config()["channels"]["max"].get("chat_id"))
mpm3.stop("max")
check("M17. отмена мастера MAX -> stopped", wait_state(mpm3, "max", ("stopped",))["state"] == "stopped")

mnet4 = FakeMax(mode="bad_token")
_, _, mpm4 = mk_stack(mnet4)
st = mpm4.start("max", "wrongwrongwrongwrongwrong")
check("M18. неверный ключ: сразу error/bad_token, в сеть — только /me, поток не запущен",
      st["state"] == "error" and st["reason"] == M.REASON_BAD_TOKEN and [c[0] for c in mnet4.calls] == ["/me"], st)

mnet5 = FakeMax(mode="rate")
mstore5, _, mpm5 = mk_stack(mnet5)
st = mpm5.start("max", MAX_TOKEN); mnet5.code = st["link"].split("start=")[1]
st = wait_state(mpm5, "max", ("paired", "error", "timeout"), timeout=8.0)
check("M19. 429 на /updates не роняет мастер: пауза и повтор -> paired",
      st["state"] == "paired" and sum(1 for c in mnet5.calls if c[0] == "/updates") >= 2, st)

_res = msvc.send_test("max")
check("M20. после мастера «Проверить» шлёт в MAX и получает id сообщения", _res.ok and _res.message_id == "mid.777", _res)
check("M21. подпись «куда подключено» без секретов: @бот → человек",
      mx.connected_label(mch) == "@ferma_bot → Алексей С." and MAX_TOKEN not in mx.connected_label(mch))

# ── ШАБЛОНЫ СООБЩЕНИЙ (2.1007) ─────────────────────────────────────────────────────────────
#  Заказ владельца 12.09.2026: принтер в заголовке, файл отдельной строкой и выделен, статус в
#  конце со значком; и чтобы текст можно было настроить самому.
print("\n--- Шаблоны сообщений ---")
from fm_messengers import templates as TPL   # noqa: E402
from fm_messengers import settings as SETT   # noqa: E402

_fin = {"kind": M.EVENT_PRINT_FINISHED, "printer_name": "H2D_01", "file": "bracket_v3.gcode", "elapsed_s": 8100}
_txt = SV.format_event(_fin, "ru")
check("T1. по умолчанию: принтер в ПЕРВОЙ строке, файл — ОТДЕЛЬНОЙ строкой в кавычках со значком, статус — ПОСЛЕДНИМ со своим значком",
      _txt.split("\n") == ["🖨 H2D_01", "📄 «bracket_v3.gcode»", "✅ Печать завершена · 2 ч 15 мин"], _txt)
_txt_en = SV.format_event(_fin, "en")
check("T2. то же по-английски: слова из программы, раскладка та же",
      _txt_en.split("\n") == ["🖨 H2D_01", "📄 «bracket_v3.gcode»", "✅ Print finished · 2h 15m"], _txt_en)
_nofile = SV.format_event({"kind": M.EVENT_PRINT_FAILED, "printer_name": "K2-02", "percent": 43}, "ru")
check("T3. нет файла — строка файла выброшена целиком, кавычки не остаются; статус со сбоем и процентом",
      _nofile.split("\n") == ["🖨 K2-02", "❌ Печать прервана сбоем · 43%"], _nofile)
_nodur = SV.format_event({"kind": M.EVENT_PRINT_FINISHED, "printer_name": "P1S", "file": "a.gcode"}, "ru")
check("T4. нет длительности — висящая точка « · » убрана", _nodur.split("\n")[-1] == "✅ Печать завершена", _nodur)
_note = SV.format_event({"kind": M.EVENT_PRINTER_NOTICE, "printer_name": "X1C", "code": "0700-2000-0002-0001",
                         "severity": "serious", "module": "ams"}, "ru",
                        hms_text={"0700-2000-0002-0001": {"ru": "Филамент закончился", "en": "Filament ran out"}})
check("T5. уведомление принтера: расшифровка и «узел · серьёзность · код» отдельными строками",
      _note.split("\n") == ["🖨 X1C", "🔔 Уведомление на экране принтера", "Филамент закончился", "AMS · серьёзно · 0700-2000-0002-0001"], _note)
_off = SV.format_event({"kind": M.EVENT_PRINTER_OFFLINE, "printer_name": "X1C", "minutes": 7}, "ru")
_on = SV.format_event({"kind": M.EVENT_PRINTER_OFFLINE, "printer_name": "X1C", "online": True}, "ru")
check("T6. нет связи / связь восстановлена — свои значок и статус", _off.split("\n") == ["🖨 X1C", "📴 Нет связи уже 7 мин"]
      and _on.split("\n") == ["🖨 X1C", "📶 Связь восстановлена"], (_off, _on))
_err = SV.format_event({"kind": M.EVENT_PRINTER_ERROR, "printer_name": "X1C", "code": "0300-8100-0001-0002"}, "ru")
check("T7. ошибка принтера: код отдельной строкой со значком", _err.split("\n") == ["🖨 X1C", "⚠️ Ошибка принтера", "⚙ 0300-8100-0001-0002"], _err)
check("T8. пробное сообщение — постоянный текст, шаблонам не подчиняется",
      SV.format_event({"kind": M.EVENT_TEST, "channel_title": "MAX"}, "ru").startswith("🔔 Farm Manager подключён"))

_custom = {M.EVENT_PRINT_FINISHED: "{printer}: готово {file} за {duration} в {time}"}
_c = SV.format_event(_fin, "ru", templates=_custom)
check("T9. свой шаблон подставляется: все подстановки на месте, время — ЧЧ:ММ",
      _c.startswith("H2D_01: готово bracket_v3.gcode за 2 ч 15 мин в ") and len(_c.rsplit(" ", 1)[-1]) == 5, _c)
check("T10. неизвестная подстановка остаётся как есть (опечатку видно), пустой свой шаблон = по умолчанию",
      "{oops}" in TPL.render("{printer} {oops}", {"printer": "A"})
      and SV.format_event(_fin, "ru", templates={M.EVENT_PRINT_FINISHED: "  "}) == _txt)
check("T11. строка выбрасывается ТОЛЬКО когда пусты все её подстановки; строка без подстановок остаётся",
      TPL.render("A\n{file}\n{printer} · {file}\nB", {"file": "", "printer": "P"}) == "A\nP\nB")

_ns = SETT.normalize({"templates": {M.EVENT_PRINT_FINISHED: "x" * 700, M.EVENT_PRINT_FAILED: TPL.DEFAULTS[M.EVENT_PRINT_FAILED],
                                    "bogus": "y"}}, reg)
check("T12. настройки: шаблон обрезается до предела, совпадающий с умолчанием хранится ПУСТЫМ, чужие ключи отброшены",
      len(_ns["templates"][M.EVENT_PRINT_FINISHED]) == TPL.TEMPLATE_MAX and _ns["templates"][M.EVENT_PRINT_FAILED] == ""
      and "bogus" not in _ns["templates"] and set(_ns["templates"]) == set(M.EVENT_KEYS))
_cfg2, _ch2 = SETT.apply_patch(_ns, {"templates": {M.EVENT_PRINT_CANCELLED: "{printer} стоп"}}, reg)
check("T13. правка шаблона фиксируется как изменение templates.<событие>, остальные не тронуты",
      _ch2 == ["templates." + M.EVENT_PRINT_CANCELLED] and _cfg2["templates"][M.EVENT_PRINT_CANCELLED] == "{printer} стоп"
      and _cfg2["templates"][M.EVENT_PRINT_FINISHED] == _ns["templates"][M.EVENT_PRINT_FINISHED])
check("T14. в показе настроек шаблоны видны (секретов среди них нет)", "templates" in SETT.public_view(_cfg2, reg)
      and SETT.public_view(_cfg2, reg)["templates"][M.EVENT_PRINT_CANCELLED] == "{printer} стоп")

_bd = svc.settings_bundle("ru")["templates"]
check("T15. окну отдаются умолчания, список подстановок с подсказками, образцы данных и готовый предпросмотр на каждое событие",
      set(_bd) == {"defaults", "vars", "hints", "sample", "preview"} and list(_bd["vars"]) == list(TPL.VARS)
      and all(k in _bd["preview"] and k in _bd["sample"] and k in _bd["defaults"] for k in M.EVENT_KEYS)
      and _bd["preview"][M.EVENT_PRINT_FINISHED].split("\n")[0] == "🖨 H2D_01"
      and all(v in _bd["hints"] for v in TPL.VARS), list(_bd))
_r = svc.update_settings({"templates": {M.EVENT_PRINT_FINISHED: "{icon} {printer} {file}"}})
check("T16. сохранение через сервис: записано, следующее событие уходит по новому шаблону",
      _r["saved"] and _r["settings"]["templates"][M.EVENT_PRINT_FINISHED] == "{icon} {printer} {file}"
      and SV.format_event(_fin, "ru", templates=svc.config()["templates"]) == "✅ H2D_01 bracket_v3.gcode")
_r2 = svc.update_settings({"templates": {M.EVENT_PRINT_FINISHED: ""}})
check("T17. пустая строка возвращает умолчание", _r2["settings"]["templates"][M.EVENT_PRINT_FINISHED] == ""
      and SV.format_event(_fin, "ru", templates=svc.config()["templates"]) == _txt)
_P = rd("modules", "messengers", "web", "MessengersPanel.js")
check("T18. окно: карточка «Текст сообщений» — поле на каждое событие, предпросмотр, подстановки, сброс, сохранение",
      all(x in _P for x in ("data-msg-templates", "data-msg-tpl-in", "data-msg-tpl-prev", "data-msg-var", "data-msg-tpl-reset",
                             "data-msg-tpl-save", "const renderTpl", "tplPreview(k)")))
check("T19. предпросмотр в окне считается тем же правилом, что на сервере (пустые подстановки, « · », «»)",
      "known.every((v) => v === '')" in _P and "split(' · ')" in _P and "«»" in _P)

# ── 16.10.2026 (R-151, аудит data-safety-10): откат на старую версию модуля не стирает новое ──────
print("\n--- R-151. Непонятое старой версией сохраняется ---")
import sqlite3   # noqa: E402
_reg_new = R.default_registry()
_reg_old = R.MessengerRegistry([p for p in _reg_new.providers() if p.kind != "max"])   # сборка без MAX
_dbr = os.path.join(tmp, "r151.db")
_st_new = ST.SettingsStore(_dbr, _reg_new.secret_keys())
_cfgN, _ = S.apply_patch(None, {"channels": {
    "telegram": {"enabled": True, "bot_token": "123456:TELEGRAMSECRET", "chat_id": "5"},
    "max": {"enabled": True, "access_token": "MAXSECRET-0123456789", "chat_id": "42"}},
    "events": {M.EVENT_PRINT_CANCELLED: True}}, _reg_new)
_cfgN["future_section"] = {"a": 1}                                   # раздел более новой версии
_cfgN["channels"]["telegram"]["future_field"] = "f1"                 # новое поле известной площадки
_cfgN["events"]["future_event"] = True                               # новое событие
_cfgN["templates"]["future_event"] = "{printer} новое"               # и его шаблон
_st_new.write_config(_cfgN)
_c = sqlite3.connect(_dbr)
_c.execute("INSERT INTO msg_settings (key, value) VALUES ('zz_other', 'x')")
_c.commit()
_rowid0 = _c.execute("SELECT rowid FROM msg_settings WHERE key='config'").fetchone()[0]
_c.close()
_st_old = ST.SettingsStore(_dbr, _reg_old.secret_keys())
_svc_old = SV.MessengerService(_reg_old, _st_old.read_config, _st_old.write_config, None, None)
_res = _svc_old.update_settings({"lang": "en", "channels": {"telegram": {"chat_id": "6"}}})
_pub = json.loads(_st_old.public_raw()["config"])
check("R1. КРИТИЧНО: старая сборка без MAX сохранила свои настройки — канал MAX (включён, chat_id) остался как был",
      _res["saved"] and _pub.get("lang") == "en" and _pub["channels"]["telegram"].get("chat_id") == "6"
      and (_pub["channels"].get("max") or {}).get("enabled") is True
      and (_pub["channels"].get("max") or {}).get("chat_id") == "42", _pub)
check("R2. новые поля, события, шаблоны и разделы более новой версии сохранены без изменений",
      _pub.get("future_section") == {"a": 1} and _pub["channels"]["telegram"].get("future_field") == "f1"
      and _pub["events"].get("future_event") is True and _pub["templates"].get("future_event") == "{printer} новое", _pub)
_c = sqlite3.connect(_dbr)
_sec = dict(_c.execute("SELECT key, value FROM msg_secrets").fetchall())
_rowid1 = _c.execute("SELECT rowid FROM msg_settings WHERE key='config'").fetchone()[0]
_c.close()
check("R3. ключ бота MAX в msg_secrets не тронут, а секретов в открытой таблице нет",
      _sec.get("max.access_token") == "MAXSECRET-0123456789" and _sec.get("telegram.bot_token") == "123456:TELEGRAMSECRET"
      and "MAXSECRET" not in json.dumps(_pub) and "TELEGRAMSECRET" not in json.dumps(_pub), _sec)
check("R4. отправка старой сборки лишнего не видит: в её настройках нет ни MAX, ни нового события",
      "max" not in _svc_old.config()["channels"] and "future_event" not in _svc_old.config()["events"]
      and "max" not in _res["settings"]["channels"])
check("R5. запись — обновление строки (UPSERT), а не удаление и вставка (REPLACE): строка та же",
      _rowid1 == _rowid0, (_rowid0, _rowid1))
_back = _st_new.read_config()
check("R6. новая сборка после возврата видит MAX целиком — с ключом и chat_id — и правку старой сборки",
      (_back["channels"].get("max") or {}).get("access_token") == "MAXSECRET-0123456789"
      and _back["channels"]["max"].get("chat_id") == "42" and _back["channels"]["telegram"].get("chat_id") == "6"
      and _back.get("lang") == "en", _back)
_pk = S.preserve_unknown({"channels": {"telegram": {"chat_id": "старый"}}, "events": {"print_finished": False}},
                         {"channels": {"telegram": {"enabled": True, "chat_id": "новый"}}, "events": {"print_finished": True}},
                         _reg_new)
check("R7. известное берётся из новой правки, а не из сохранённого (preserve_unknown не откатывает изменения)",
      _pk["channels"]["telegram"]["chat_id"] == "новый" and _pk["events"]["print_finished"] is True, _pk)

BE._svc.stop()
try:
    shutil.rmtree(tmp, ignore_errors=True)
except Exception:
    pass
print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
