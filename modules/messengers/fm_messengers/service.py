# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Диспетчер уведомлений: события фермы → текст → очередь → площадки.

ОТКУДА СОБЫТИЯ.
  · Конец печати (завершена / сбой / остановлена) — от хука ядра print_run_finished: там
    событие ровно одно на печать, с именем принтера, файлом и длительностью.
  · Ошибка принтера, уведомление на его экране (HMS критично/серьёзно), пропажа связи —
    наблюдатель observe(): раз в две секунды сравнивает снимок состояний принтеров с прошлым.
    Первый снимок принтера — база, о нём не сообщаем: иначе каждый перезапуск программы
    пересылал бы давно висящие уведомления.

ЗАЩИТА ОТ ШУМА. Одно и то же (принтер + событие + код/файл) — не чаще раза в 10 минут;
«нет связи» — только если связи нет 3 минуты подряд, и один раз «связь восстановлена».
Очередь ограничена: если площадки недоступны, лишние события отбрасываются.

ЖЕЛЕЗНОЕ ПРАВИЛО. Ничто здесь не влияет на печать: все публичные методы ловят исключения,
сеть — только в рабочем потоке, ошибки — в строку статуса канала и в лог без секретов.
"""
import queue
import threading
import time

from . import models as M
from . import settings as S
from . import transport as T

DEDUP_WINDOW_S = 600
OFFLINE_AFTER_S = M.OFFLINE_AFTER_S
POLL_INTERVAL_S = 2.0
CFG_CACHE_S = 10.0
QUEUE_MAX = 200
NOTICE_SEVERITIES = ("fatal", "serious")

from . import templates as TPL

#  Помощники форматирования живут в templates.py; имена оставлены для совместимости.
fmt_duration = TPL.fmt_duration
_SEV = TPL.SEV
_MOD = TPL.MOD


def format_event(ev, lang, hms_text=None, templates=None):
    """Событие -> текст сообщения по шаблону (свой из настроек либо по умолчанию).
    Простой текст без разметки: у каждой площадки свои правила экранирования, а сообщение
    должно дойти, а не упасть. Пробное сообщение — постоянный текст, не шаблон."""
    ru = lang != "en"
    ev = ev or {}
    if ev.get("kind") == M.EVENT_TEST:
        ch = str(ev.get("channel_title") or "")
        return (("🔔 Farm Manager подключён. Канал %s настроен верно." % ch) if ru
                else ("🔔 Farm Manager is connected. The %s channel is set up correctly." % ch))
    return TPL.render_event(ev, lang, hms_text, templates)


class MessengerService(object):
    def __init__(self, registry, cfg_read, cfg_write, printer_name_fn=None, log=None,
                 transport=None, clock=None, hms_text=None):
        self.registry = registry
        self._cfg_read = cfg_read
        self._cfg_write = cfg_write
        self._name = printer_name_fn or (lambda pid: str(pid))
        self._log = log
        self._send = transport or T.http_send
        self._clock = clock or time.monotonic
        self._hms_text = hms_text or {}
        self._q = queue.Queue(maxsize=QUEUE_MAX)
        self._worker = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._status = {}
        self._sent = {}
        self._prev = {}
        self._offline_since = {}
        self._offline_sent = set()
        self._cfg_cache = None
        self._cfg_cache_at = -1e9
        self._nonce = int(time.time()) & 0x7FFFFFFF
        self.dropped = 0

    # ── журнал без секретов ───────────────────────────────────────────────────────────────
    def _info(self, msg):
        try:
            if self._log:
                self._log.info("[MSG] " + msg)
        except Exception:
            pass

    def _warn(self, msg):
        try:
            if self._log:
                self._log.warning("[MSG] " + msg)
        except Exception:
            pass

    def _dbg(self, msg):
        try:
            if self._log:
                self._log.debug("[MSG] " + msg)
        except Exception:
            pass

    # ── настройки ─────────────────────────────────────────────────────────────────────────
    def config(self):
        now = self._clock()
        if self._cfg_cache is not None and now - self._cfg_cache_at < CFG_CACHE_S:
            return self._cfg_cache
        try:
            raw = self._cfg_read()
        except Exception as e:
            self._dbg("config read failed: %s" % e)
            raw = None
        cfg = S.normalize(raw, self.registry)
        self._cfg_cache, self._cfg_cache_at = cfg, now
        return cfg

    def invalidate(self):
        self._cfg_cache = None

    def settings_bundle(self, lang=None):
        cfg = self.config()
        L = lang if lang in S.LANGS else cfg["lang"]
        return {"settings": S.public_view(cfg, self.registry),
                "catalog": self.registry.catalog(L),
                "events": list(M.EVENT_KEYS),
                #  2.1007: шаблоны по умолчанию, подстановки, образцы и предпросмотр.
                "templates": TPL.bundle(L, cfg.get("templates")),
                "channel_status": self.status()}

    def update_settings(self, patch):
        cfg, changed = S.apply_patch(self.config(), patch, self.registry)
        saved = True
        if changed:
            try:
                #  16.10.2026 (R-151): непонятое этой версией (площадки, поля, события более новой
                #  версии модуля) записывается обратно как было — иначе откат на старую версию стирал бы его.
                try:
                    _stored = self._cfg_read()
                except Exception:
                    _stored = None
                saved = bool(self._cfg_write(S.preserve_unknown(_stored, cfg, self.registry)))
            except Exception as e:
                self._warn("settings write failed: %s" % type(e).__name__)
                saved = False
            self.invalidate()
        if saved:
            self._cfg_cache, self._cfg_cache_at = cfg, self._clock()
        return {"settings": S.public_view(cfg if saved else self.config(), self.registry),
                "changed": changed, "saved": saved}

    def status(self):
        with self._lock:
            return {k: dict(v) for k, v in self._status.items()}

    # ── отправка ──────────────────────────────────────────────────────────────────────────
    def _record(self, kind, res, ev_kind):
        with self._lock:
            self._status[kind] = {"ok": res.ok, "reason": res.reason, "detail": res.detail,
                                  "http_status": res.http_status, "event": ev_kind,
                                  "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        if res.ok:
            self._info("%s: sent (%s)" % (kind, ev_kind))
        else:
            self._warn("%s: %s — %s (%s)" % (kind, res.reason, res.detail, ev_kind))

    def _deliver(self, kind, text, ev_kind, cfg=None):
        cfg = cfg or self.config()
        prov = self.registry.get(kind)
        if prov is None:
            return M.SendResult(False, M.REASON_UNKNOWN_KIND, str(kind))
        ch = cfg["channels"].get(prov.kind) or {}
        bad = prov.validate(ch)
        if bad:
            res = M.SendResult(False, bad[0], bad[1])
        else:
            with self._lock:
                self._nonce = (self._nonce + 1) & 0x7FFFFFFF
                nonce = self._nonce
            secrets = [ch.get(k) for k in prov.secret_keys()]
            try:
                req = prov.build_request(ch, text, nonce=nonce)
                status, body = self._send(req)
                res = prov.parse_response(status, body)
            except T.TransportError as e:
                res = M.SendResult(False, M.REASON_NETWORK, e.detail)
            except Exception as e:
                res = M.SendResult(False, M.REASON_PLATFORM_ERROR,
                                   M.clip_detail("%s: %s" % (type(e).__name__, e), secrets))
        self._record(prov.kind, res, ev_kind)
        return res

    def send_test(self, kind):
        """Пробное сообщение. Выключенный канал тоже проверяется."""
        try:
            cfg = self.config()
            prov = self.registry.get(kind)
            if prov is None:
                return M.SendResult(False, M.REASON_UNKNOWN_KIND, str(kind))
            text = format_event({"kind": M.EVENT_TEST, "channel_title": prov.title}, cfg["lang"])
            return self._deliver(prov.kind, text, M.EVENT_TEST, cfg)
        except Exception as e:
            self._dbg("send_test failed: %s" % e)
            return M.SendResult(False, M.REASON_PLATFORM_ERROR, type(e).__name__)

    def _process(self, ev):
        cfg = self.config()
        text = format_event(ev, cfg["lang"], self._hms_text, cfg.get("templates"))
        for kind, ch in cfg["channels"].items():
            if ch.get("enabled"):
                self._deliver(kind, text, ev.get("kind"), cfg)

    # ── события ───────────────────────────────────────────────────────────────────────────
    def notify(self, ev):
        try:
            ev = dict(ev or {})
            kind = ev.get("kind")
            cfg = self.config()
            if kind != M.EVENT_TEST and not cfg["events"].get(kind):
                return False
            if not S.any_channel_enabled(cfg):
                return False
            key = (str(ev.get("printer_id") or ""), str(kind), str(ev.get("key") or ""))
            now = self._clock()
            with self._lock:
                last = self._sent.get(key)
                if last is not None and now - last < DEDUP_WINDOW_S:
                    return False
                self._sent[key] = now
                if len(self._sent) > 2000:
                    self._sent = {k: v for k, v in self._sent.items() if now - v < DEDUP_WINDOW_S}
            try:
                self._q.put_nowait(ev)
            except queue.Full:
                self.dropped += 1
                self._warn("queue full, event dropped: %s" % kind)
                return False
            return True
        except Exception as e:
            self._dbg("notify failed: %s" % e)
            return False

    def on_run_finished(self, payload):
        """Хук ядра print_run_finished."""
        try:
            p = payload or {}
            kind = {"finished": M.EVENT_PRINT_FINISHED, "failed": M.EVENT_PRINT_FAILED,
                    "cancelled": M.EVENT_PRINT_CANCELLED}.get(str(p.get("outcome_raw") or ""))
            if not kind:
                return False
            pid = p.get("printer_id")
            file_ = p.get("filename") or p.get("file_norm") or ""
            return self.notify({"kind": kind, "printer_id": pid,
                                "printer_name": p.get("printer_name") or self._name(pid),
                                "file": file_, "elapsed_s": p.get("elapsed_s"),
                                "percent": p.get("final_percent"),
                                "key": p.get("run_id") or file_})
        except Exception as e:
            self._dbg("on_run_finished failed: %s" % e)
            return False

    def observe(self, snapshot, now=None):
        """Снимок {pid: состояние} -> события по переходам. Первый снимок принтера — база."""
        try:
            now = self._clock() if now is None else now
            snapshot = snapshot or {}
            for pid in list(self._prev.keys()):
                if pid not in snapshot:
                    self._prev.pop(pid, None)
                    self._offline_since.pop(pid, None)
                    self._offline_sent.discard(pid)
            for pid, st in snapshot.items():
                st = st if isinstance(st, dict) else {}
                status = str(st.get("status") or "OFFLINE").upper()
                err = st.get("device_error") or None
                hms = st.get("hms") if isinstance(st.get("hms"), list) else []
                serious = {}
                for h in hms:
                    if isinstance(h, dict) and h.get("code") and h.get("severity") in NOTICE_SEVERITIES:
                        serious[str(h.get("code"))] = h
                cur = {"status": status, "err": err, "serious": set(serious.keys())}
                prev = self._prev.get(pid)
                self._prev[pid] = cur
                if status == "OFFLINE":
                    self._offline_since.setdefault(pid, now)
                else:
                    self._offline_since.pop(pid, None)
                if prev is None:
                    #  13.10.2026: первый снимок — база (правило в заголовке файла). Принтер, который уже
                    #  был не на связи при запуске, считаем «уже сообщённым»: раньше через 3 минуты после
                    #  каждого перезапуска приходило «нет связи» по давно выключенным принтерам.
                    if status == "OFFLINE":
                        self._offline_sent.add(pid)
                    continue
                name = self._name(pid)
                if err and err != prev.get("err"):
                    self.notify({"kind": M.EVENT_PRINTER_ERROR, "printer_id": pid,
                                 "printer_name": name, "code": err, "key": str(err)})
                for code in sorted(cur["serious"] - prev.get("serious", set())):
                    h = serious.get(code) or {}
                    self.notify({"kind": M.EVENT_PRINTER_NOTICE, "printer_id": pid,
                                 "printer_name": name, "code": code,
                                 "severity": h.get("severity"), "module": h.get("module"),
                                 "key": code})
                if status == "OFFLINE":
                    since = self._offline_since.get(pid, now)
                    if pid not in self._offline_sent and now - since >= OFFLINE_AFTER_S:
                        self._offline_sent.add(pid)
                        self.notify({"kind": M.EVENT_PRINTER_OFFLINE, "printer_id": pid,
                                     "printer_name": name, "minutes": int((now - since) // 60),
                                     "key": "off"})
                elif pid in self._offline_sent:
                    self._offline_sent.discard(pid)
                    self.notify({"kind": M.EVENT_PRINTER_OFFLINE, "printer_id": pid,
                                 "printer_name": name, "online": True, "key": "on"})
        except Exception as e:
            self._dbg("observe failed: %s" % e)

    # ── потоки ────────────────────────────────────────────────────────────────────────────
    def _run(self):
        while not self._stop.is_set():
            try:
                ev = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._process(ev)
            except Exception as e:
                self._dbg("process failed: %s" % e)

    def start(self):
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return False
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, daemon=True, name="messengers-send")
            self._worker.start()
            return True

    def stop(self):
        self._stop.set()

    def poll_loop(self, snapshot_fn, interval=POLL_INTERVAL_S):
        self.start()
        while not self._stop.is_set():
            try:
                self.observe(snapshot_fn() or {})
            except Exception as e:
                self._dbg("poll failed: %s" % e)
            self._stop.wait(interval)

    def process_pending(self, limit=100):
        """Для проверок: разобрать очередь в вызывающем потоке."""
        n = 0
        while n < limit:
            try:
                ev = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                self._process(ev)
            except Exception as e:
                self._dbg("process failed: %s" % e)
            n += 1
        return n

    def pending(self):
        return self._q.qsize()
