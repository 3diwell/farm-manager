# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Тексты сообщений Bambu Lab — из официальной таблицы производителя (15.09.2026).

ЗАЧЕМ. По MQTT принтер присылает только числа (attr, code); текст сообщения рисует прошивка
из своей таблицы. До 15.09.2026 программа знала два кода, снятых с фотографий владельца, а все
остальные показывала кодом и узлом. Владелец просил, чтобы сообщения с экрана принтера были
видны в программе — значит, нужна та же таблица, что у принтера.

ИСТОЧНИК — ТОТ ЖЕ, ЧТО У QR-КОДА НА ЭКРАНЕ. Ссылка на экране принтера ведёт на e.bambulab.com;
у сайта есть открытый запрос `https://e.bambulab.com/query.php?lang=<язык>`, которым сама
Bambu Studio получает таблицу (HMSQuery). Ответ проверен 15.09.2026: JSON с разделами
    data.device_hms.<lang>   — уведомления (HMS): ecode из 16 HEX (attr+code), intro — текст;
    data.device_error.<lang> — ошибки печати (print_error): ecode из 8 HEX, intro — текст;
на русском и английском — 2040 уведомлений и 488 ошибок. Ничего не выдумываем: текст
показывается только тот, что пришёл из этой таблицы.

КАК ЖИВЁТ. Таблица скачивается в фоне (при старте и раз в сутки, если старше недели) и хранится
в папке данных программы (bambu_hms_texts.json), чтобы работать без интернета. Сеть недоступна —
остаётся прежняя таблица или две встроенные записи. Изолированному тестовому экземпляру наружу
ходить запрещено (тот же признак, что у проверки обновлений). Сбой загрузки на печать и на
опрос принтеров не влияет: всё fail-open.
"""
import io
import json
import os
import threading
import time
import urllib.request

QUERY_URL = "https://e.bambulab.com/query.php?lang=%s"
LANGS = ("ru", "en")
CACHE_NAME = "bambu_hms_texts.json"
CACHE_TTL_S = 7 * 24 * 3600          # старше недели — обновить при случае
CHECK_EVERY_S = 24 * 3600            # как часто фоновая петля смотрит, не пора ли
FIRST_DELAY_S = 20.0                 # старт программы важнее таблицы: подождать, пока всё поднимется
FETCH_TIMEOUT_S = 8.0

_lock = threading.Lock()
_state = {"dir": None, "tables": {}, "fetched_at": 0.0, "ver": ""}
_thread = None


# ── чистый разбор ───────────────────────────────────────────────────────────────────────────
def _norm_hex(s):
    return "".join(ch for ch in str(s or "").upper() if ch in "0123456789ABCDEF")


def hms_key(code):
    """Печатный код уведомления «0C00-0100-0001-0004» -> ключ таблицы «0C00010000010004» (16 HEX)."""
    k = _norm_hex(code)
    return k if len(k) == 16 else ""


def error_key(code):
    """Код ошибки печати «0300-400C» -> ключ таблицы «0300400C» (8 HEX)."""
    k = _norm_hex(code)
    return k if len(k) == 8 else ""


def parse_payload(obj, lang):
    """Ответ query.php -> {"hms": {ключ: текст}, "error": {ключ: текст}, "ver": str}.
    Мусор и записи без кода/текста пропускаются; неверная форма -> пустые словари."""
    out = {"hms": {}, "error": {}, "ver": ""}
    if not isinstance(obj, dict):
        return out
    data = obj.get("data")
    if not isinstance(data, dict):
        return out
    out["ver"] = str(obj.get("ver") or data.get("ver") or "")
    for section, keyfn in (("device_hms", hms_key), ("device_error", error_key)):
        sec = data.get(section)
        rows = sec.get(lang) if isinstance(sec, dict) else None
        if not isinstance(rows, list):
            continue
        dst = out["hms" if section == "device_hms" else "error"]
        for r in rows:
            if not isinstance(r, dict):
                continue
            k = keyfn(r.get("ecode"))
            t = " ".join(str(r.get("intro") or "").split())
            if k and t and k not in dst:
                dst[k] = t
    return out


# ── таблицы в памяти ────────────────────────────────────────────────────────────────────────
def _texts(section, key):
    if not key:
        return None
    with _lock:
        tables = _state["tables"]
        out = {}
        for lang in LANGS:
            t = ((tables.get(lang) or {}).get(section) or {}).get(key)
            if t:
                out[lang] = t
    return out or None


def hms_text(code):
    """Текст уведомления по печатному коду -> {"ru": ..., "en": ...} (только известные языки) или None."""
    return _texts("hms", hms_key(code))


def error_text(code):
    """Текст ошибки печати по коду «XXXX-XXXX» -> {"ru": ..., "en": ...} или None."""
    return _texts("error", error_key(code))


def known_hms_dict():
    """Все уведомления в виде {"XXXX-XXXX-XXXX-XXXX": {"ru":..., "en":...}} — для модулей, которые
    берут таблицу снимком (уведомления в мессенджеры)."""
    with _lock:
        tables = dict(_state["tables"])
    keys = set()
    for lang in LANGS:
        keys.update(((tables.get(lang) or {}).get("hms") or {}).keys())
    out = {}
    for k in keys:
        rec = {}
        for lang in LANGS:
            t = ((tables.get(lang) or {}).get("hms") or {}).get(k)
            if t:
                rec[lang] = t
        if rec:
            out["%s-%s-%s-%s" % (k[0:4], k[4:8], k[8:12], k[12:16])] = rec
    return out


def counts():
    with _lock:
        return {lang: {"hms": len((_state["tables"].get(lang) or {}).get("hms") or {}),
                       "error": len((_state["tables"].get(lang) or {}).get("error") or {})}
                for lang in LANGS}


def status():
    with _lock:
        return {"fetched_at": _state["fetched_at"], "ver": _state["ver"], "dir": _state["dir"]}


# ── кеш в папке данных ──────────────────────────────────────────────────────────────────────
def cache_path(data_dir):
    return os.path.join(data_dir, CACHE_NAME)


def load_cache(data_dir):
    """Прочитать таблицу из папки данных. -> True, если что-то загружено. Ошибки глотаются."""
    try:
        p = cache_path(data_dir)
        with _lock:
            _state["dir"] = data_dir
        if not os.path.isfile(p):
            return False
        with io.open(p, encoding="utf-8") as f:
            obj = json.load(f)
        tables = obj.get("tables") if isinstance(obj, dict) else None
        if not isinstance(tables, dict):
            return False
        clean = {}
        for lang in LANGS:
            t = tables.get(lang)
            if isinstance(t, dict):
                clean[lang] = {"hms": {str(k): str(v) for k, v in (t.get("hms") or {}).items()},
                               "error": {str(k): str(v) for k, v in (t.get("error") or {}).items()}}
        if not any(clean.get(l, {}).get("hms") for l in LANGS):
            return False
        with _lock:
            _state["tables"] = clean
            _state["fetched_at"] = float(obj.get("fetched_at") or 0)
            _state["ver"] = str(obj.get("ver") or "")
        return True
    except Exception:
        return False


def save_cache(data_dir):
    """Записать таблицу в папку данных: во временный файл, затем подменить (без полузаписанных файлов)."""
    with _lock:
        obj = {"fetched_at": _state["fetched_at"], "ver": _state["ver"], "tables": _state["tables"]}
    p = cache_path(data_dir)
    tmp = p + ".tmp"
    os.makedirs(data_dir, exist_ok=True)
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)


def needs_refresh(now=None):
    now = time.time() if now is None else now
    with _lock:
        return (now - float(_state["fetched_at"] or 0)) >= CACHE_TTL_S or not _state["tables"]


# ── загрузка с сайта производителя ──────────────────────────────────────────────────────────
def fetch_lang(lang, timeout=FETCH_TIMEOUT_S):
    """Один язык с e.bambulab.com -> разобранная таблица. Исключения наружу — решает вызывающий."""
    req = urllib.request.Request(QUERY_URL % lang, headers={"User-Agent": "3DIWELL-Farm-Manager"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return parse_payload(json.loads(raw), lang)


def refresh(data_dir, fetcher=None, log=None, now=None):
    """Скачать оба языка, принять и сохранить. -> True при успехе. Частичный ответ (один язык
    пустой) не принимается: лучше прежняя полная таблица, чем половина новой."""
    fetcher = fetcher or fetch_lang
    got, ver = {}, ""
    for lang in LANGS:
        try:
            t = fetcher(lang)
        except Exception as e:
            if log:
                log.info("[HMS-TEXT] таблица %s не загружена: %s", lang, "%s: %s" % (type(e).__name__, e))
            return False
        if not isinstance(t, dict) or not t.get("hms"):
            if log:
                log.info("[HMS-TEXT] таблица %s пришла пустой — оставляем прежнюю", lang)
            return False
        got[lang] = {"hms": dict(t["hms"]), "error": dict(t.get("error") or {})}
        ver = str(t.get("ver") or ver or "")
    with _lock:
        _state["tables"] = got
        _state["fetched_at"] = time.time() if now is None else now
        _state["ver"] = ver
        _state["dir"] = data_dir
    try:
        save_cache(data_dir)
    except Exception as e:
        if log:
            log.info("[HMS-TEXT] таблица загружена, но не сохранена в папку данных: %s", e)
    if log:
        c = counts()
        log.info("[HMS-TEXT] таблица сообщений Bambu обновлена: ru %d/%d, en %d/%d (уведомления/ошибки)",
                 c["ru"]["hms"], c["ru"]["error"], c["en"]["hms"], c["en"]["error"])
    return True


def start_background(data_dir, enabled=True, log=None, on_update=None, first_delay=FIRST_DELAY_S):
    """Фоновая петля: через first_delay с — обновить, если таблица старше недели или её нет; дальше
    раз в сутки та же проверка. enabled=False (изолированный экземпляр) — поток не создаётся."""
    global _thread
    if not enabled:
        if log:
            log.info("[HMS-TEXT] загрузка таблицы сообщений Bambu отключена (изолированный экземпляр)")
        return None
    if _thread is not None and _thread.is_alive():
        return _thread

    def _loop():
        time.sleep(max(0.0, float(first_delay)))
        while True:
            try:
                if needs_refresh() and refresh(data_dir, log=log) and on_update:
                    try:
                        on_update()
                    except Exception:
                        pass
            except Exception as e:
                if log:
                    log.debug("[HMS-TEXT] фоновое обновление: %s", e)
            time.sleep(CHECK_EVERY_S)

    _thread = threading.Thread(target=_loop, name="fm-hms-texts", daemon=True)
    _thread.start()
    return _thread


def _reset_for_tests():
    """Только для наборов проверок: чистое состояние между сценариями."""
    global _thread
    with _lock:
        _state.update({"dir": None, "tables": {}, "fetched_at": 0.0, "ver": ""})
    _thread = None
