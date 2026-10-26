# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Мастер подключения: ключ → проверка → ссылка «нажмите Start» → авто-привязка → пробное.

Человек делает две вещи: создаёт бота/сообщество на сайте площадки (кнопки открывают нужную
страницу) и вставляет ключ. Остальное — здесь: модуль проверяет ключ, даёт ссылку, ждёт в
своём потоке первого сообщения, сам запоминает адрес получателя, включает канал и шлёт пробное.

Telegram (core.telegram.org/bots/api): getMe → username; ссылка https://t.me/<username>?start=<код>;
  getUpdates (долгий опрос, offset=update_id+1) — привязываемся к чату, откуда пришло
  «/start <код>» либо любое личное сообщение, отправленное уже после начала подключения.
  409 (у бота включён webhook) → deleteWebhook и продолжаем.
VK (dev.vk.com, 5.199): groups.getTokenPermissions → нужно право «messages»; groups.getById →
  id и имя сообщества; ссылка https://vk.me/club<id>; messages.getConversations (extended=1) —
  привязываемся к первому личному диалогу, где последнее сообщение — от человека и не старше
  начала подключения.

MAX (dev.max.ru/docs-api, 12.09.2026): /me → никнейм; ссылка https://max.ru/<никнейм>?start=<код>;
  /updates (долгий опрос, marker из ответа, types=bot_started,message_created) — привязываемся
  к чату, откуда пришло bot_started с нашим кодом либо любое свежее bot_started/личное
  сообщение уже после начала подключения. Время событий MAX — в МИЛЛИСЕКУНДАХ.

Состояния сессии: checking → waiting → paired | error | timeout | stopped.
"""
import random
import string
import threading
import time

from . import models as M
from . import transport as T

PAIR_WINDOW_S = 600
TG_POLL_TIMEOUT_S = 15
VK_POLL_INTERVAL_S = 3.0
MAX_POLL_TIMEOUT_S = 15
_ALPHABET = string.ascii_letters + string.digits


def _code(n=10):
    rng = random.SystemRandom()
    return "".join(rng.choice(_ALPHABET) for _ in range(n))


def _person(d):
    d = d or {}
    name = " ".join(str(d.get(k) or "").strip() for k in ("first_name", "last_name")).strip()
    return name or str(d.get("title") or d.get("username") or "").strip()


class PairingManager(object):
    """Одна сессия на площадку. API: start(kind, token) / status(kind|None) / stop(kind)."""

    def __init__(self, registry, service, save_fn, log=None, transport=None, clock=None, wall=None):
        """save_fn(kind, patch) — записать поля канала (ключ, chat_id, имя бота…) и включить
        канал; service.send_test(kind) — пробное после привязки."""
        self.registry = registry
        self.service = service
        self._save = save_fn
        self._log = log
        self._send = transport or T.http_send
        self._clock = clock or time.monotonic
        self._wall = wall or time.time
        self._lock = threading.Lock()
        self._sessions = {}

    # ── журнал ────────────────────────────────────────────────────────────────────────────
    def _info(self, msg):
        try:
            if self._log:
                self._log.info("[MSG-PAIR] " + msg)
        except Exception:
            pass

    # ── вызов API площадки ────────────────────────────────────────────────────────────────
    def _api(self, prov, cfg, method, params=None):
        """-> (ok, data). Сетевой сбой -> (False, {"reason": "network", …})."""
        req = prov.api_request(cfg, method, params)
        if req is None:
            return (False, {"reason": M.REASON_BAD_RESPONSE, "detail": "no api"})
        try:
            status, body = self._send(req)
        except T.TransportError as e:
            return (False, {"reason": M.REASON_NETWORK, "detail": e.detail})
        except Exception as e:
            return (False, {"reason": M.REASON_PLATFORM_ERROR,
                            "detail": M.clip_detail("%s: %s" % (type(e).__name__, e), req.secrets)})
        return prov.parse_api(status, body)

    # ── состояние ─────────────────────────────────────────────────────────────────────────
    def _set(self, kind, **kw):
        with self._lock:
            s = self._sessions.setdefault(kind, {"kind": kind, "state": "idle"})
            s.update(kw)
            s["updated_at"] = self._wall()

    def status(self, kind=None):
        with self._lock:
            if kind is not None:
                s = self._sessions.get(kind)
                return self._public(s) if s else {"kind": kind, "state": "idle"}
            return {k: self._public(v) for k, v in self._sessions.items()}

    @staticmethod
    def _public(s):
        keys = ("kind", "state", "link", "bot_name", "target_name", "reason", "detail", "updated_at")
        return {k: s.get(k) for k in keys if k in s}

    def stop(self, kind):
        with self._lock:
            s = self._sessions.get(kind)
            if s and s.get("stop_event"):
                s["stop_event"].set()
        self._set(kind, state="stopped")
        return True

    # ── запуск ────────────────────────────────────────────────────────────────────────────
    def start(self, kind, token):
        """Проверяет ключ синхронно (одна-две секунды), потом ждёт человека в потоке."""
        prov = self.registry.get(kind)
        if prov is None or not prov.has_wizard:
            return {"kind": kind, "state": "error", "reason": M.REASON_UNKNOWN_KIND, "detail": str(kind)}
        #  2.995: принимаем и целое сообщение площадки — ключ выберем из него сами.
        token = prov.extract_token(token)
        if not token:
            return {"kind": prov.kind, "state": "error", "reason": M.REASON_NOT_CONFIGURED, "detail": "empty token"}
        self.stop(prov.kind)
        self._set(prov.kind, state="checking", link=None, bot_name=None, target_name=None, reason=None, detail=None)
        #  2.1006: площадок с мастером три — выбор по таблице, а не веткой if.
        check_fn, wait_fn = self._flow(prov.kind)
        res = check_fn(prov, token)
        if res.get("state") != "waiting":
            self._set(prov.kind, **res)
            return self.status(prov.kind)
        stop_ev = threading.Event()
        started = self._wall()
        self._set(prov.kind, stop_event=stop_ev, started_at=started, **res)
        t = threading.Thread(target=self._guarded, args=(wait_fn, prov, token, res, stop_ev, started),
                             daemon=True, name="messengers-pair-" + prov.kind)
        t.start()
        return self.status(prov.kind)

    def _flow(self, kind):
        """kind -> (проверка ключа, ожидание человека). Новая площадка — одна строка здесь."""
        table = {"telegram": (self._tg_check, self._tg_wait),
                 "vk": (self._vk_check, self._vk_wait),
                 "max": (self._max_check, self._max_wait)}
        return table.get(kind, (self._vk_check, self._vk_wait))

    def _guarded(self, fn, prov, token, res, stop_ev, started):
        try:
            fn(prov, token, res, stop_ev, started)
        except Exception as e:
            self._set(prov.kind, state="error", reason=M.REASON_PLATFORM_ERROR,
                      detail=M.clip_detail("%s: %s" % (type(e).__name__, e), (token,)))

    def _finish(self, prov, token, patch, target_name):
        """Сохранить канал, включить, отправить пробное, отметить paired."""
        full = dict(patch)
        full["enabled"] = True
        try:
            self._save(prov.kind, full)
        except Exception as e:
            self._set(prov.kind, state="error", reason=M.REASON_PLATFORM_ERROR,
                      detail=M.clip_detail("save: %s" % e, (token,)))
            return
        self._set(prov.kind, state="paired", target_name=target_name)
        self._info("%s paired -> %s" % (prov.kind, target_name))
        try:
            self.service.send_test(prov.kind)
        except Exception:
            pass

    # ── Telegram ──────────────────────────────────────────────────────────────────────────
    def _tg_check(self, prov, token):
        cfg = {"bot_token": token}
        ok, data = self._api(prov, cfg, "getMe", {})
        if not ok:
            return {"state": "error", "reason": data.get("reason"), "detail": data.get("detail")}
        me = data if isinstance(data, dict) else {}
        username = str(me.get("username") or "").strip()
        if not username:
            return {"state": "error", "reason": M.REASON_BAD_RESPONSE, "detail": "getMe without username"}
        code = _code()
        try:
            self._save(prov.kind, {"bot_token": token, "bot_username": username})
        except Exception as e:
            return {"state": "error", "reason": M.REASON_PLATFORM_ERROR, "detail": M.clip_detail("save: %s" % e, (token,))}
        return {"state": "waiting", "link": "https://t.me/%s?start=%s" % (username, code),
                "bot_name": "@" + username, "code": code}

    def _tg_wait(self, prov, token, res, stop_ev, started):
        cfg = {"bot_token": token}
        code = res.get("code") or ""
        offset = None
        deadline = self._clock() + PAIR_WINDOW_S
        while not stop_ev.is_set() and self._clock() < deadline:
            params = {"timeout": TG_POLL_TIMEOUT_S, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            ok, data = self._api(prov, cfg, "getUpdates", params)
            if not ok:
                if data.get("code") == 409:
                    self._api(prov, cfg, "deleteWebhook", {"drop_pending_updates": False})
                    continue
                if data.get("reason") == M.REASON_NETWORK:
                    stop_ev.wait(3.0)
                    continue
                self._set(prov.kind, state="error", reason=data.get("reason"), detail=data.get("detail"))
                return
            for upd in (data if isinstance(data, list) else []):
                if not isinstance(upd, dict):
                    continue
                uid = upd.get("update_id")
                if isinstance(uid, int):
                    offset = uid + 1
                msg = upd.get("message") if isinstance(upd.get("message"), dict) else None
                if not msg:
                    continue
                chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
                text = str(msg.get("text") or "")
                chat_id = chat.get("id")
                if chat_id is None:
                    continue
                by_code = bool(code) and text.strip() == "/start " + code
                fresh_private = (chat.get("type") == "private"
                                 and isinstance(msg.get("date"), int) and msg.get("date") >= int(started) - 5)
                if by_code or fresh_private:
                    who = _person(chat) if chat.get("type") == "private" else str(chat.get("title") or chat_id)
                    self._finish(prov, token, {"bot_token": token, "chat_id": str(chat_id),
                                               "bot_username": res.get("bot_name", "").lstrip("@"),
                                               "chat_title": who}, who)
                    return
            stop_ev.wait(0.5)
        if not stop_ev.is_set():
            self._set(prov.kind, state="timeout")

    # ── VK ────────────────────────────────────────────────────────────────────────────────
    def _vk_check(self, prov, token):
        cfg = {"access_token": token}
        ok, data = self._api(prov, cfg, "groups.getTokenPermissions", {})
        if not ok:
            return {"state": "error", "reason": data.get("reason"), "detail": data.get("detail")}
        perms = data.get("permissions") if isinstance(data, dict) else None
        names = {str(p.get("name")) for p in (perms or []) if isinstance(p, dict)}
        if "messages" not in names:
            return {"state": "error", "reason": M.REASON_NO_PERMISSION,
                    "detail": "token without the community messages permission"}
        gid, gname = "", ""
        ok2, info = self._api(prov, cfg, "groups.getById", {})
        if ok2:
            groups = info.get("groups") if isinstance(info, dict) else info
            if isinstance(groups, list) and groups and isinstance(groups[0], dict):
                gid = str(groups[0].get("id") or "")
                gname = str(groups[0].get("name") or "")
        try:
            self._save(prov.kind, {"access_token": token, "group_id": gid, "group_name": gname})
        except Exception as e:
            return {"state": "error", "reason": M.REASON_PLATFORM_ERROR, "detail": M.clip_detail("save: %s" % e, (token,))}
        link = ("https://vk.me/club%s" % gid) if gid else "https://vk.com/im"
        return {"state": "waiting", "link": link, "bot_name": gname or "VK", "group_id": gid, "group_name": gname}

    def _vk_wait(self, prov, token, res, stop_ev, started):
        cfg = {"access_token": token}
        deadline = self._clock() + PAIR_WINDOW_S
        while not stop_ev.is_set() and self._clock() < deadline:
            ok, data = self._api(prov, cfg, "messages.getConversations",
                                 {"count": 20, "filter": "all", "extended": 1, "fields": "first_name,last_name"})
            if not ok:
                if data.get("reason") == M.REASON_NETWORK:
                    stop_ev.wait(VK_POLL_INTERVAL_S)
                    continue
                self._set(prov.kind, state="error", reason=data.get("reason"), detail=data.get("detail"))
                return
            items = data.get("items") if isinstance(data, dict) else None
            profiles = {str(p.get("id")): p for p in (data.get("profiles") or []) if isinstance(p, dict)} if isinstance(data, dict) else {}
            for it in (items or []):
                conv = it.get("conversation") if isinstance(it, dict) else None
                peer = (conv or {}).get("peer") if isinstance(conv, dict) else None
                lm = it.get("last_message") if isinstance(it, dict) else None
                if not isinstance(peer, dict) or not isinstance(lm, dict):
                    continue
                if peer.get("type") != "user":
                    continue
                from_id = lm.get("from_id")
                date = lm.get("date")
                if not (isinstance(from_id, int) and from_id > 0 and isinstance(date, int) and date >= int(started) - 60):
                    continue
                peer_id = str(peer.get("id"))
                who = _person(profiles.get(str(from_id))) or peer_id
                self._finish(prov, token, {"access_token": token, "peer_id": peer_id,
                                           "group_id": res.get("group_id", ""), "group_name": res.get("group_name", ""),
                                           "peer_title": who}, who)
                return
            stop_ev.wait(VK_POLL_INTERVAL_S)
        if not stop_ev.is_set():
            self._set(prov.kind, state="timeout")

    # ── MAX ───────────────────────────────────────────────────────────────────────────────
    def _max_check(self, prov, token):
        cfg = {"access_token": token}
        ok, data = self._api(prov, cfg, "me", {})
        if not ok:
            return {"state": "error", "reason": data.get("reason"), "detail": data.get("detail")}
        me = data if isinstance(data, dict) else {}
        username = str(me.get("username") or "").strip().lstrip("@")
        name = str(me.get("first_name") or me.get("name") or "").strip()
        if not username:
            return {"state": "error", "reason": M.REASON_BAD_RESPONSE, "detail": "/me without username"}
        code = _code()
        try:
            self._save(prov.kind, {"access_token": token, "bot_username": username, "bot_name": name})
        except Exception as e:
            return {"state": "error", "reason": M.REASON_PLATFORM_ERROR, "detail": M.clip_detail("save: %s" % e, (token,))}
        return {"state": "waiting", "link": "https://max.ru/%s?start=%s" % (username, code),
                "bot_name": "@" + username, "code": code, "bot_title": name}

    def _max_wait(self, prov, token, res, stop_ev, started):
        cfg = {"access_token": token}
        code = res.get("code") or ""
        marker = None
        deadline = self._clock() + PAIR_WINDOW_S
        fresh_ms = (int(started) - 5) * 1000
        while not stop_ev.is_set() and self._clock() < deadline:
            params = {"timeout": MAX_POLL_TIMEOUT_S, "types": ["bot_started", "message_created"]}
            if marker is not None:
                params["marker"] = marker
            ok, data = self._api(prov, cfg, "updates", params)
            if not ok:
                if data.get("reason") in (M.REASON_NETWORK, M.REASON_RATE_LIMITED):
                    stop_ev.wait(3.0)
                    continue
                self._set(prov.kind, state="error", reason=data.get("reason"), detail=data.get("detail"))
                return
            if isinstance(data, dict) and isinstance(data.get("marker"), int):
                marker = data.get("marker")
            for upd in ((data or {}).get("updates") if isinstance(data, dict) else []) or []:
                if not isinstance(upd, dict):
                    continue
                kind = str(upd.get("update_type") or "")
                ts = upd.get("timestamp")
                fresh = isinstance(ts, int) and ts >= fresh_ms
                chat_id = user_id = None
                who = ""
                by_code = False
                if kind == "bot_started":
                    chat_id = upd.get("chat_id")
                    user = upd.get("user") if isinstance(upd.get("user"), dict) else {}
                    user_id = user.get("user_id")
                    who = _person(user)
                    by_code = bool(code) and str(upd.get("payload") or "").strip() == code
                elif kind == "message_created":
                    msg = upd.get("message") if isinstance(upd.get("message"), dict) else {}
                    rcp = msg.get("recipient") if isinstance(msg.get("recipient"), dict) else {}
                    snd = msg.get("sender") if isinstance(msg.get("sender"), dict) else {}
                    if rcp.get("chat_type") not in (None, "dialog"):
                        continue
                    chat_id = rcp.get("chat_id")
                    user_id = snd.get("user_id") or rcp.get("user_id")
                    who = _person(snd)
                    body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
                    text = str(body.get("text") or "").strip()
                    by_code = bool(code) and text in ("/start " + code, code)
                    mts = msg.get("timestamp")
                    if isinstance(mts, int):
                        fresh = mts >= fresh_ms
                else:
                    continue
                if chat_id is None and user_id is None:
                    continue
                if by_code or fresh:
                    who = who or str(chat_id or user_id)
                    patch = {"access_token": token, "chat_id": str(chat_id or ""), "user_id": str(user_id or ""),
                             "bot_username": str(res.get("bot_name") or "").lstrip("@"),
                             "bot_name": str(res.get("bot_title") or ""), "chat_title": who}
                    self._finish(prov, token, patch, who)
                    return
            stop_ev.wait(0.5)
        if not stop_ev.is_set():
            self._set(prov.kind, state="timeout")
