# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Модуль «Уведомления в мессенджеры» (messengers) v0.1.0 — backend.
#
# Что делает: пишет владельцу в Telegram / VK / MAX / WhatsApp о событиях фермы — печать завершена,
# прервана сбоем или остановлена, ошибка принтера, критичное уведомление на его экране,
# пропажа связи. Подключение — мастером: человек создаёт бота (Telegram) или сообщество (VK)
# по кнопке, вставляет ключ, нажимает Start / пишет сообществу — модуль сам находит адрес
# получателя, включает канал и шлёт пробное сообщение.
#
# Модуль ВЛАДЕЕТ своей БД farm_messengers.db (core.resolve_db): настройки в msg_settings,
# ключи ботов — отдельно в msg_secrets (в резервную копию не входят). Библиотека площадок
# лежит в папке модуля (fm_messengers/) и ставится вместе с ним из ZIP.
#
# Источники событий: хук ядра print_run_finished (конец печати) и наблюдатель по снимку
# core.printer_states() (ошибки, уведомления HMS, связь). ЖЕЛЕЗНОЕ ПРАВИЛО: ничто здесь не
# влияет на печать — все входы fail-open, сеть только в своих потоках.
import asyncio
import logging
import os
import sys
import threading
import time

from fastapi import Request

log = logging.getLogger("fm.mod.messengers")

core = None            # ядро (ModuleCore) — задаётся в register()
_lib = None            # пакет fm_messengers из папки модуля
_store = None          # хранилище настроек (БД модуля)
_svc = None            # диспетчер отправки
_pair = None           # мастер подключения
_names = {"at": 0.0, "map": {}}
_names_lock = threading.Lock()


def _load_lib(module_dir):
    """Пакет fm_messengers лежит рядом с backend.py; ядро грузит backend через importlib,
    поэтому относительные импорты недоступны — добавляем папку модуля в sys.path."""
    module_dir = os.path.abspath(module_dir)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    import fm_messengers                      # noqa: F401
    from fm_messengers import registry, service, store, pairing, models, settings  # noqa: F401
    return fm_messengers


def _printer_name(pid):
    """Имя принтера по id — из core.printers() (белый список полей), кэш на 30 секунд."""
    try:
        now = time.monotonic()
        with _names_lock:
            if now - _names["at"] > 30.0:
                _names["map"] = {str(p.get("id")): str(p.get("name") or p.get("id"))
                                 for p in (core.printers() or []) if isinstance(p, dict)}
                _names["at"] = now
            return _names["map"].get(str(pid)) or str(pid)
    except Exception:
        return str(pid)


def _snapshot():
    """Копия живых состояний принтеров для наблюдателя (ссылок на ядро не держим)."""
    try:
        src = core.printer_states() or {}
        return {pid: dict(st or {}) for pid, st in list(src.items())}
    except Exception:
        return {}


def _hms_text():
    """Переводы уведомлений принтера, если ядро их знает (не обязательно)."""
    try:
        from app import printer_health_policy as hp
        return dict(getattr(hp, "HMS_KNOWN_TEXT", {}) or {})
    except Exception:
        return {}


async def _json(req):
    try:
        d = await req.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_channel(kind, patch):
    """Мастер подключения записывает поля канала (и включает его)."""
    res = _svc.update_settings({"channels": {kind: dict(patch or {})}})
    return bool(res.get("saved"))


# ── HTTP: настройки ───────────────────────────────────────────────────────────────────────
async def api_msg_settings_get(req: Request):
    """Настройки без секретов, каталог площадок (шаги мастера, поля), итог последней отправки,
    состояние мастера по каждой площадке."""
    lang = str(req.query_params.get("lang") or "")
    out = {"status": "ok"}
    out.update(_svc.settings_bundle(lang if lang in ("ru", "en") else None))
    out["pairing"] = _pair.status()
    return out


async def api_msg_settings_set(req: Request):
    """Частичная правка: {lang?, channels?: {kind: {enabled?, поле?…}}, events?: {…}}.
    Пустой секрет прежний ключ не стирает, явный null — стирает."""
    body = await _json(req)
    res = await asyncio.to_thread(_svc.update_settings, body)
    if not res.get("saved"):
        return {"status": "error", "reason": "write_failed", **res}
    return {"status": "ok", **res}


async def api_msg_test(req: Request):
    """Пробное сообщение в один канал по сохранённым настройкам (выключенный канал — тоже)."""
    body = await _json(req)
    kind = str(body.get("kind") or "").strip().lower()
    res = await asyncio.to_thread(_svc.send_test, kind)
    return {"status": "ok" if res.ok else "error", "kind": kind, "result": res.as_dict()}


# ── HTTP: мастер подключения ──────────────────────────────────────────────────────────────
async def api_msg_pair_start(req: Request):
    """{kind, token} -> проверить ключ, выдать ссылку «нажмите Start», ждать человека."""
    body = await _json(req)
    kind = str(body.get("kind") or "").strip().lower()
    token = str(body.get("token") or "")
    st = await asyncio.to_thread(_pair.start, kind, token)
    return {"status": "ok" if st.get("state") in ("waiting", "paired") else "error", "pairing": st}


async def api_msg_pair_status(req: Request):
    """Состояние мастера: ?kind=telegram — одной площадки, без kind — всех."""
    kind = str(req.query_params.get("kind") or "").strip().lower()
    return {"status": "ok", "pairing": _pair.status(kind or None)}


async def api_msg_pair_stop(req: Request):
    body = await _json(req)
    kind = str(body.get("kind") or "").strip().lower()
    _pair.stop(kind)
    return {"status": "ok", "pairing": _pair.status(kind)}


# ── регистрация ───────────────────────────────────────────────────────────────────────────
def register(_core):
    global core, _lib, _store, _svc, _pair
    core = _core
    _lib = _load_lib(core.module_dir)
    reg = _lib.registry.default_registry()
    _store = _lib.store.SettingsStore(core.resolve_db("farm_messengers.db"), reg.secret_keys())
    _svc = _lib.service.MessengerService(reg, _store.read_config, _store.write_config,
                                         _printer_name, log, hms_text=_hms_text())
    _pair = _lib.pairing.PairingManager(reg, _svc, _save_channel, log)
    core.add_route("settings", api_msg_settings_get, ["GET"], policy_id="messengers.settings.read")
    core.add_route("settings", api_msg_settings_set, ["POST"], policy_id="messengers.settings.write")
    core.add_route("test", api_msg_test, ["POST"], policy_id="messengers.test.send")
    core.add_route("pair/start", api_msg_pair_start, ["POST"], policy_id="messengers.pair.start")
    core.add_route("pair/status", api_msg_pair_status, ["GET"], policy_id="messengers.pair.status")
    core.add_route("pair/stop", api_msg_pair_stop, ["POST"], policy_id="messengers.pair.stop")
    core.add_hook("print_run_finished", _svc.on_run_finished)
    threading.Thread(target=_svc.poll_loop, args=(_snapshot,), daemon=True,
                     name="messengers-observe").start()
    log.info("[messengers] module registered: 6 routes, hook print_run_finished, observer thread")
