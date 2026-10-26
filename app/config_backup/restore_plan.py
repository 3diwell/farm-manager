# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — построение плана восстановления (ТОЛЬКО чтение, без мутаций).

Показывает пользователю ДО применения: что добавится/изменится по секциям, что останется
без изменений, что машинно-зависимо и по умолчанию НЕ применяется, где нужен рестарт и какие
предупреждения (сеть/безопасность/деструктивно). План — основа честного подтверждения.
"""
from app.config_backup import settings_registry as reg

SECTIONS = ("core", "printers")   # v1 применяет core + printers; modules — отдельной итерацией

# ── R-128 (arch-auth-07): восстановление копии не запирает вход ───────────────────
# Копия с включённой защитой входом, восстановленная на компьютер без администратора, раньше
# писала security_enabled=1 молча: процесс работал дальше без защиты, а после ЛЮБОГО
# перезапуска вход закрывался навсегда — пользователей в копии нет (таблица users в неё не
# входит), первичная настройка отвечает «уже включено», восстановление из трея не находит
# администратора, повторное восстановление копии требует входа администратора.
# Правило одно для плана и для применения (security_hold_keys): копия ВКЛЮЧАЕТ защиту, а
# хранилище не подтверждает активного администратора (ABSENT или UNKNOWN — сбой проверки
# тоже «нельзя») — ключ не применяется, план предупреждает. Хранилище без метода
# enabled_admin_state (DictGateway тестов, замороженные фикстуры) ведёт себя как раньше.
SECURITY_KEY = "security_enabled"
ADMIN_PRESENT = "PRESENT"
SECURITY_HELD_CODE = "security_held_no_admin"
SECURITY_HELD_TEXT_RU = ("В копии включена защита входом, но на этом компьютере нет администратора. "
                         "Защита останется выключенной: создайте администратора в «Доступ и аудит».")
SECURITY_HELD_TEXT_EN = ("The backup has sign-in protection enabled, but this computer has no administrator. "
                         "Protection stays off: create an administrator in “Access & audit”.")
# Ключи, чья смена требует перезапуска, хотя в реестре restart_required=False (реестр закреплён
# тестами и не меняется): флаг защиты процесс читает только при запуске, поэтому без
# перезапуска восстановленное значение включилось бы (или выключилось) молча потом.
RESTART_ON_CHANGE = (SECURITY_KEY,)


def admin_state(gateway):
    """Состояние «есть ли включённый администратор» от хранилища: 'PRESENT' | 'ABSENT' |
    'UNKNOWN', либо None, если хранилище этого не умеет (прежнее поведение). Сбой самой
    проверки — 'UNKNOWN': техническая неудача не считается доказанным администратором."""
    fn = getattr(gateway, "enabled_admin_state", None)
    if not callable(fn):
        return None
    try:
        st = fn()
    except Exception:
        return "UNKNOWN"
    st = str(getattr(st, "value", st) or "").strip().upper()
    return st or "UNKNOWN"


def security_hold_keys(gateway, payload, selected_sections):
    """R-128: ключи core, которые восстановление НЕ применяет (кортеж; пустой — ограничений нет).

    Одно правило для плана и для применения: копия включает защиту входом, сейчас она
    выключена, а активного администратора на этом компьютере нет или это не подтвердилось."""
    if "core" not in set(selected_sections or ()):
        return ()
    e = reg.get(SECURITY_KEY)
    vals = payload.core.values or {}
    if e is None or SECURITY_KEY not in vals:
        return ()
    if e.restore_behavior in (reg.RB_EXCLUDE, reg.RB_CURRENT_ONLY, reg.RB_IMPORT_AS_OFF):
        return ()
    if not reg.coerce_out(e, vals[SECURITY_KEY]):
        return ()                                     # копия защиту не включает
    if _current_core(gateway).get(SECURITY_KEY):
        return ()                                     # защита уже включена — копия её не меняет
    st = admin_state(gateway)
    if st is None or st == ADMIN_PRESENT:
        return ()
    return (SECURITY_KEY,)


def restart_on_change(gateway, mutation):
    """R-128: True, если мутация действительно МЕНЯЕТ ключ из RESTART_ON_CHANGE (в любую
    сторону). Читает текущее значение — вызывать ДО применения мутации."""
    cur = None
    for k in RESTART_ON_CHANGE:
        e = reg.get(k)
        if e is None:
            continue
        src = mutation.app_set if e.store == reg.STORE_APP_SETTINGS else mutation.config_set
        if k not in src:
            continue
        if cur is None:
            cur = _current_core(gateway)
        if reg.coerce_out(e, src[k]) != cur.get(k):
            return True
    return False


def _current_core(gateway):
    cfg = gateway.get_config_json() or {}
    cur = {}
    for e in reg.serializable_settings():
        if e.store == reg.STORE_CONFIG_JSON:
            cur[e.key] = reg.coerce_out(e, cfg.get(e.key))
        else:
            cur[e.key] = reg.coerce_out(e, gateway.get_app_setting(e.key))
    return cur


def build_plan(gateway, payload, selected_sections, apply_machine_bound=False, hold_keys=None):
    """-> dict: {sections:{core:{items,warnings}, printers:{items}}, restart_required, warnings, counts}.

    hold_keys (R-128): ключи, которые применение НЕ запишет (action='held'). None — посчитать
    здесь тем же правилом security_hold_keys, что и применение."""
    sel = set(selected_sections or ())
    cur = _current_core(gateway)
    held = set(security_hold_keys(gateway, payload, sel) if hold_keys is None else (hold_keys or ()))
    plan = {"sections": {}, "warnings": [], "restart_required": False,
            "counts": {"core_changed": 0, "printers_added": 0, "printers_updated": 0,
                       "machine_bound_shown": 0}}

    if "core" in sel:
        items, warnings = [], []
        vals = payload.core.values or {}
        for e in reg.portable_settings():
            if e.key not in vals:
                continue
            if e.restore_behavior in (reg.RB_EXCLUDE, reg.RB_CURRENT_ONLY):
                continue
            new_val = vals[e.key]
            if e.restore_behavior == reg.RB_IMPORT_AS_OFF:
                new_val = False
            cur_val = cur.get(e.key)
            action = "unchanged" if new_val == cur_val else "update"
            if action == "update" and e.key in held:
                action = "held"                       # R-128: значение копии НЕ применяется
            if action == "update":
                plan["counts"]["core_changed"] += 1
                if e.restart_required or e.key in RESTART_ON_CHANGE:
                    plan["restart_required"] = True
            it = {"key": e.key, "action": action, "current": cur_val, "new": new_val,
                  "sensitivity": e.sensitivity, "restart_required": e.restart_required,
                  "restore_behavior": e.restore_behavior}
            items.append(it)
            if action == "held" and e.key == SECURITY_KEY:
                warnings.append({"code": SECURITY_HELD_CODE, "key": e.key,
                                 "text": SECURITY_HELD_TEXT_RU, "text_en": SECURITY_HELD_TEXT_EN})
            if action == "update" and e.sensitivity == reg.SENS_NETWORK and bool(new_val):
                warnings.append({"code": "network_exposure", "key": e.key,
                                 "text": "Будет включён сетевой доступ/экспозиция"})
            if action == "update" and e.sensitivity == reg.SENS_SECURITY:
                warnings.append({"code": "security_change", "key": e.key,
                                 "text": "Меняется настройка безопасности"})
            if e.restore_behavior == reg.RB_IMPORT_AS_OFF:
                warnings.append({"code": "destructive_off", "key": e.key,
                                 "text": "Деструктивная функция восстановлена ВЫКЛЮЧЕННОЙ"})
        # machine-bound — информационно, по умолчанию не применяется
        mb_items = []
        mb = payload.core.machine_bound or {}
        for e in reg.machine_bound_settings():
            if e.key not in mb:
                continue
            plan["counts"]["machine_bound_shown"] += 1
            applied = bool(apply_machine_bound)
            if applied and mb[e.key] != cur.get(e.key) and e.restart_required:
                plan["restart_required"] = True
            mb_items.append({"key": e.key, "backup": mb[e.key], "current": cur.get(e.key),
                             "applied": applied, "sensitivity": e.sensitivity})
        if not apply_machine_bound and mb_items:
            warnings.append({"code": "machine_bound_kept",
                             "text": "Пути и порт этой машины сохраняются (не переносятся)"})
        plan["sections"]["core"] = {"items": items, "machine_bound": mb_items, "warnings": warnings}
        plan["warnings"].extend(warnings)

    if "printers" in sel:
        cur_ids = {str(p.get("id")) for p in (gateway.list_printers() or [])}
        pitems = []
        for snap in payload.printers:
            action = "update" if snap.stable_id in cur_ids else "add"
            if action == "add":
                plan["counts"]["printers_added"] += 1
            else:
                plan["counts"]["printers_updated"] += 1
            pitems.append({"stable_id": snap.stable_id, "action": action,
                           "display_name": snap.display_name, "adapter": snap.adapter,
                           "model": snap.model})
        pw = []
        if plan["counts"]["printers_updated"] > 0:
            pw.append({"code": "printers_overwrite",
                       "text": "Существующие принтеры с тем же id будут перезаписаны (включая доступ)"})
        plan["sections"]["printers"] = {"items": pitems, "warnings": pw}
        plan["warnings"].extend(pw)

    # Универсальное предупреждение: потерянный пароль восстановить нельзя (для UI).
    return plan
