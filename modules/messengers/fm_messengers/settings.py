# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Настройки модуля: нормализация, слияние правок, показ без секретов.

Форма:
  {"lang": "ru"|"en",
   "channels": {"<kind>": {"enabled": bool, "<поле>": "строка", …}, …},
   "events":   {"print_finished": bool, …},
   "templates": {"print_finished": "шаблон или пусто (= по умолчанию)", …}}

Правила:
  · normalize() терпит любой мусор: недостающие ключи получают значения по умолчанию,
    лишние отбрасываются, значения приводятся к строкам и обрезаются;
  · apply_patch() — частичная правка: секретное поле, пришедшее ПУСТЫМ, ключ не стирает
    (форма его не показывает), явный null — стирает;
  · public_view() — то же без секретов: «задан/не задан» и 4 последних знака ключа.
"""
from . import models as M
from . import templates as TPL

LANGS = ("ru", "en")
DEFAULT_LANG = "ru"


def _bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None:
        return bool(default)
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on", "да"):
        return True
    if s in ("0", "false", "no", "off", "нет", ""):
        return False
    return bool(default)


def _str(v, max_len):
    return ("" if v is None else str(v)).strip()[:max(1, int(max_len))]


def normalize(raw, registry):
    raw = raw if isinstance(raw, dict) else {}
    cfg = {"lang": raw.get("lang") if raw.get("lang") in LANGS else DEFAULT_LANG,
           "channels": {}, "events": {}, "templates": {}}
    chans = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
    for prov in registry.providers():
        src = chans.get(prov.kind) if isinstance(chans.get(prov.kind), dict) else {}
        ch = {"enabled": _bool(src.get("enabled"))}
        for f in prov.fields:
            ch[f.key] = _str(src.get(f.key), f.max_len)
        cfg["channels"][prov.kind] = ch
    evs = raw.get("events") if isinstance(raw.get("events"), dict) else {}
    for k in M.EVENT_KEYS:
        cfg["events"][k] = _bool(evs.get(k), M.EVENT_DEFAULTS[k])
    tps = raw.get("templates") if isinstance(raw.get("templates"), dict) else {}
    for k in M.EVENT_KEYS:
        cfg["templates"][k] = _tpl(tps.get(k), k)
    return cfg


def _tpl(v, kind):
    """Шаблон события: обрезан по длине; совпадающий с умолчанием хранится пустым."""
    t = _str(v, TPL.TEMPLATE_MAX)
    return "" if t == TPL.DEFAULTS.get(kind, "") else t


def apply_patch(cur, patch, registry):
    """-> (новый раздел, список изменённых ключей вида 'channels.telegram.chat_id')."""
    cfg = normalize(cur, registry)
    changed = []
    patch = patch if isinstance(patch, dict) else {}
    if patch.get("lang") in LANGS and patch["lang"] != cfg["lang"]:
        cfg["lang"] = patch["lang"]
        changed.append("lang")
    pch = patch.get("channels") if isinstance(patch.get("channels"), dict) else {}
    for kind, src in pch.items():
        prov = registry.get(kind)
        if prov is None or not isinstance(src, dict):
            continue
        ch = cfg["channels"][prov.kind]
        if "enabled" in src:
            nv = _bool(src.get("enabled"))
            if nv != ch["enabled"]:
                ch["enabled"] = nv
                changed.append("channels.%s.enabled" % prov.kind)
        for f in prov.fields:
            if f.key not in src:
                continue
            v = src.get(f.key)
            if f.secret:
                if v is None:
                    nv = ""
                elif str(v).strip() == "":
                    continue
                else:
                    nv = _str(v, f.max_len)
            else:
                nv = _str(v, f.max_len)
            if nv != ch[f.key]:
                ch[f.key] = nv
                changed.append("channels.%s.%s" % (prov.kind, f.key))
    pev = patch.get("events") if isinstance(patch.get("events"), dict) else {}
    for k in M.EVENT_KEYS:
        if k in pev:
            nv = _bool(pev.get(k))
            if nv != cfg["events"][k]:
                cfg["events"][k] = nv
                changed.append("events." + k)
    ptp = patch.get("templates") if isinstance(patch.get("templates"), dict) else {}
    for k in M.EVENT_KEYS:
        if k in ptp:
            nv = _tpl(ptp.get(k), k)
            if nv != cfg["templates"][k]:
                cfg["templates"][k] = nv
                changed.append("templates." + k)
    return cfg, changed


_KNOWN_TOP = ("lang", "channels", "events", "templates")


def preserve_unknown(stored_raw, cfg, registry):
    """16.10.2026 (R-151, аудит data-safety-10): то, чего ЭТА версия модуля не понимает, при
    сохранении не теряется. Более новая версия могла записать площадку, которой здесь нет (max),
    новые поля известных площадок, новые события и шаблоны, новые ключи раздела. Прежде normalize()
    собирал раздел заново только из своего реестра, и первое же сохранение в старой версии стирало
    всё это (а ключ удалённой площадки оставался сиротой в msg_secrets).

    stored_raw — раздел как он лежит в базе (read_config), cfg — новый раздел этой версии.
    -> раздел для записи: cfg плюс непонятое из stored_raw без изменений. Для отправки сообщений
    используется normalize() — лишнее туда не попадает. Секреты незнакомых площадок в stored_raw
    не читаются вовсе (read_config знает только свои), поэтому в msg_settings они не попадают."""
    out = dict(cfg or {})
    raw = stored_raw if isinstance(stored_raw, dict) else {}
    for k, v in raw.items():
        if k not in _KNOWN_TOP and k not in out:
            out[k] = v
    chans = dict(out.get("channels") or {})
    raw_ch = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
    for kind, src in raw_ch.items():
        if not isinstance(src, dict):
            continue
        prov = registry.get(kind)
        if prov is None:
            if kind not in chans:
                chans[kind] = dict(src)          # площадка более новой версии — как была
            continue
        known = {"enabled"} | {f.key for f in prov.fields}
        ch = dict(chans.get(prov.kind) or {})
        for fk, fv in src.items():
            if fk not in known and fk not in ch:
                ch[fk] = fv                       # поле более новой версии — как было
        chans[prov.kind] = ch
    out["channels"] = chans
    for sect in ("events", "templates"):
        cur = dict(out.get(sect) or {})
        src = raw.get(sect) if isinstance(raw.get(sect), dict) else {}
        for k, v in src.items():
            if k not in M.EVENT_KEYS and k not in cur:
                cur[k] = v                        # событие или шаблон более новой версии
        out[sect] = cur
    return out


def public_view(cfg, registry):
    """Показ без секретов + состояние «подключён» для каждой площадки."""
    cfg = normalize(cfg, registry)
    out = {"lang": cfg["lang"], "channels": {}, "events": dict(cfg["events"]),
           "templates": dict(cfg["templates"])}
    for prov in registry.providers():
        ch = cfg["channels"][prov.kind]
        view = {"enabled": ch["enabled"]}
        for f in prov.fields:
            v = ch.get(f.key) or ""
            if f.secret:
                view[f.key] = ""
                view[f.key + "_set"] = bool(v)
                view[f.key + "_tail"] = v[-4:] if len(v) >= 8 else ""
            else:
                view[f.key] = v
        view["connected"] = prov.validate(ch) is None
        view["connected_label"] = prov.connected_label(ch)
        out["channels"][prov.kind] = view
    return out


def any_channel_enabled(cfg):
    return any(bool((ch or {}).get("enabled")) for ch in (cfg or {}).get("channels", {}).values())
