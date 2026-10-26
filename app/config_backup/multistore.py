# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — атомарное восстановление НЕСКОЛЬКИХ хранилищ (core + модули) как ОДНОЙ операции.

Core (config.json + farm_parts.app_settings + printers) и модули (свои SQLite) — разные файлы:
одна SQLite-транзакция их не покрывает. Поэтому: pre-image КАЖДОГО хранилища (+SHA-256) в журнале
ДО применения; документированный порядок применения core -> модули (по module_id); откат строго в
ОБРАТНОМ порядке; проверка КАЖДОГО отката; verify всех хранилищ + guard неизменности
projects/tasks; pre-images затираются ТОЛЬКО после общей verification. Нельзя получить
«core восстановлен + Inventory старый» или наоборот — любой сбой откатывает ВСЁ.

Состояния журнала (машина состояний, каждая запись durable: temp+fsync+os.replace):
  prepared -> staging_modules -> applying_core -> applying_module:<id> ...
  -> committed_pending_verify -> verifying_core -> verifying_module:<id> ...
  -> complete
  (сбой) -> rolling_back_module:<id> ... -> rolling_back_core -> complete | rollback_required
"""
import hashlib
import json

from app.config_backup import module_providers as mp
from app.config_backup import serializer, restore_plan
from app.config_backup.restore_engine import _verify as _verify_core
from app.config_backup.errors import (BackupError, MANUAL_RESOLUTION_REQUIRED,
                                       ROLLBACK_COMPLETED, ROLLBACK_FAILED)

# Текст плана для старых копий (payload v1: секции module_data НЕ БЫЛО).
ABSENT_NOTE_RU = "Данные модулей отсутствуют в этой версии резервной копии и не будут изменены"


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def module_block_reasons(prov, store, snap):
    """R-125: почему данные модуля из копии НЕЛЬЗЯ применить к ЭТОЙ установке (только чтение).

    Без этой проверки обе причины всплывали только посреди применения и откатывали ВСЁ
    восстановление, ядро тоже:
      * module_not_initialized — модуль установлен, но ни разу не запускался (отключён сразу
        после установки или не загрузился): файла его базы нет. Лечится включением модуля и
        перезапуском программы, а не обновлением;
      * module_tables_missing — в копии есть строки таблицы (или настройки), которой у модуля на
        этом компьютере нет: модуль старее копии. UPSERT молча пропускал такую таблицу,
        проверка после применения падала;
      * module_restore_conflict — уникальное значение (номер заказа, номер наклейки в партии) на
        цели занято ДРУГОЙ записью: UPSERT нарушил бы ограничение UNIQUE схемы модуля.
    -> список предупреждений {code, ..., field_path} (имена схемы и счётчики, без значений).
    Хранилище без has_table (DictModuleStore тестов) таблицы не проверяет — прежнее поведение."""
    out = []
    has = getattr(store, "has_table", None)
    db_exists = getattr(store, "db_exists", None)
    if callable(has):
        tables = (snap.get("domain_data") or {}).get("tables") or {}
        missing = [s.name for s in prov.table_specs if (tables.get(s.name) or []) and not has(s.name)]
        st_table = getattr(store, "settings_table", None)
        if (snap.get("settings") or {}) and st_table and not has(st_table):
            missing.append(st_table)
        if missing and callable(db_exists) and not db_exists():
            out.append({"code": "module_not_initialized", "count": len(missing),
                        "field_path": sorted(missing)[0],
                        "text": ("Модуль %s на этом компьютере ещё ни разу не запускался: его база не "
                                 "создана. Включите модуль, перезапустите программу и повторите "
                                 "восстановление" % prov.module_id)})
        elif missing:
            out.append({"code": "module_tables_missing", "tables": sorted(missing),
                        "count": len(missing), "field_path": sorted(missing)[0],
                        "text": ("Модуль %s на этом компьютере старее копии: нет нужных таблиц (%d). "
                                 "Обновите модуль и повторите восстановление" % (prov.module_id, len(missing)))})
    conf = getattr(prov, "restore_conflicts", None)
    if callable(conf):
        for c in conf(store, snap) or []:
            w = dict(c)
            w.setdefault("text", "Записей копии модуля %s, чьё уникальное значение (%s) здесь занято "
                                 "другой записью: %s" % (prov.module_id, w.get("column"), w.get("count")))
            out.append(w)
    return out


def _selected_module_snaps(payload, installed_modules, module_stores, exclude_modules,
                           strict=True):
    """Отобрать применимые снапшоты модулей: мигрировать (append-only) + провалидировать.
    strict: отсутствие установленного модуля/store при наличии данных -> manual_resolution_required."""
    md = payload.module_data
    out, missing = [], []
    if md is None:
        return out, missing, True                     # секция ОТСУТСТВУЕТ — модули не трогаем
    for entry in md.get("modules") or []:
        mid = entry.get("module_id")
        if mid in (exclude_modules or ()):
            continue
        if entry.get("data_class") != mp.DATA_CLASS_PROVIDER or entry.get("domain_data") is None:
            continue                                  # нет данных — нечего применять
        prov = mp.get_provider(mid)
        installed = mid in (installed_modules or {})
        store = (module_stores or {}).get(mid)
        if prov is None or not installed or store is None:
            missing.append(mid)
            continue
        try:
            snap = prov.migrate_snapshot(entry)       # append-only chain модуля; новее ридера -> отказ
            prov.validate_snapshot(snap)
        except BackupError as e:                       # Alpha 2.830: safe-структура для UI/route
            if e.section is None:
                e.section = "modules"
            if e.module_id is None:
                e.module_id = mid
            if e.stage is None:
                e.stage = "module_validate"
            raise
        out.append((mid, prov, snap))
    out.sort(key=lambda t: t[0])                      # ДЕТЕРМИНИРОВАННЫЙ порядок применения
    if strict and missing:
        raise BackupError(MANUAL_RESOLUTION_REQUIRED,
                          "modules required for restore: %s" % ",".join(sorted(missing)))
    return out, missing, False


def build_full_plan(gateway, payload, sections, module_stores=None, installed_modules=None,
                    apply_machine_bound=False, exclude_modules=(), known_printer_ids=None,
                    hold_keys=None):
    """ТОЛЬКО ЧТЕНИЕ: единый план core+printers+modules для UI. Ничего не мутирует.
    hold_keys (R-128) — см. restore_plan.build_plan (None — то же правило, что у применения)."""
    plan = restore_plan.build_plan(gateway, payload, sections, apply_machine_bound=apply_machine_bound,
                                   hold_keys=hold_keys)
    sel = set(sections or ())
    mplan = {"absent": False, "modules": [], "warnings": [], "blocked": False,
             "blocked_modules": [], "excluded": []}
    if "modules" in sel:
        md = payload.module_data
        if md is None:
            mplan["absent"] = True
            mplan["warnings"].append({"code": "module_data_absent", "text": ABSENT_NOTE_RU})
        else:
            snaps, missing, _ = _selected_module_snaps(payload, installed_modules, module_stores,
                                                       exclude_modules, strict=False)
            # Модули, которые пользователь исключил из восстановления («Восстановить без этого
            # модуля»): их данные на этом компьютере не меняются. Только те, что есть в копии.
            _in_backup = {str(e.get("module_id")) for e in (md.get("modules") or [])}
            mplan["excluded"] = sorted({str(m) for m in (exclude_modules or ())} & _in_backup)
            for mid in missing:
                mplan["warnings"].append({"code": "missing_module", "module_id": mid,
                                          "text": "Для восстановления данных требуется модуль %s" % mid})
                mplan["blocked"] = True               # полный restore блокируется (manual resolution)
                mplan["blocked_modules"].append(mid)
            for entry in (md.get("modules") or []):
                if entry.get("module_id") in mplan["excluded"]:
                    continue
                if entry.get("data_class") == mp.DATA_CLASS_NO_DATA:
                    mplan["modules"].append({"module_id": entry.get("module_id"),
                                             "data_class": mp.DATA_CLASS_NO_DATA,
                                             "counts": None})
            for mid, prov, snap in snaps:
                p = prov.build_restore_plan(module_stores[mid], snap, known_printer_ids=known_printer_ids)
                p["data_class"] = mp.DATA_CLASS_PROVIDER
                p["backup_schema_version"] = snap.get("backup_schema_version")
                blocks = module_block_reasons(prov, module_stores[mid], snap)   # R-125
                if blocks:
                    p["blocked"] = True
                    mplan["blocked"] = True           # полный restore блокируется, как missing_module
                    mplan["blocked_modules"].append(mid)
                    p["warnings"] = list(p.get("warnings") or []) + blocks
                mplan["modules"].append(p)
                for w in p.get("warnings") or []:
                    ww = {"module_id": mid}
                    ww.update(w)
                    if not ww.get("text") and ww.get("code") == "missing_printer_ref":
                        ww["text"] = ("Принтер для привязки не найден: %s (запись сохранится, "
                                      "привязка станет неактивной)" % ww.get("printer_id"))
                    if not ww.get("text") and ww.get("code") == "dangling_internal_ref":
                        ww["text"] = ("Записей со ссылкой на удалённую запись: %s — связь "
                                      "сохранится как есть" % ww.get("count"))
                    mplan["warnings"].append(ww)
    # Выход для пользователя: заблокированный модуль можно исключить (exclude_modules) —
    # остальное восстановление пройдёт, данные этого модуля на компьютере не изменятся.
    mplan["blocked_modules"] = sorted(set(mplan["blocked_modules"]))
    plan["module_data"] = mplan
    plan["warnings"] = list(plan.get("warnings") or []) + mplan["warnings"]
    return plan


def apply_restore_multistore(gateway, payload, sections, journal, module_stores=None,
                             installed_modules=None, apply_machine_bound=False,
                             exclude_modules=(), hold_keys=None):
    """Атомарно применить payload к core + выбранным модулям через ОДИН журнал.
    hold_keys (R-128): ключи core, которые не пишутся; None — посчитать тем же правилом, что и
    план (restore_plan.security_hold_keys) по состоянию хранилища на момент применения."""
    sel = set(sections or ())
    mod_snaps = []
    if "modules" in sel:
        mod_snaps, _missing, _absent = _selected_module_snaps(
            payload, installed_modules, module_stores, exclude_modules, strict=True)
        # R-125: модуль, чьи данные нельзя применить к этой установке (нет таблиц, конфликт
        # уникальных значений), останавливает восстановление ДО любых изменений — а не откатом
        # всего посреди применения. Тот же отказ, что у missing module.
        for mid, prov, snap in mod_snaps:
            try:
                blocks = module_block_reasons(prov, module_stores[mid], snap)
            except Exception as e:
                from app.config_backup.errors import DATABASE_BUSY
                raise BackupError(DATABASE_BUSY, "module check failed: %s" % type(e).__name__,
                                  section="modules", module_id=mid)
            if blocks:
                raise BackupError(MANUAL_RESOLUTION_REQUIRED,
                                  "module data cannot be applied here: %s %s" % (mid, blocks[0]["code"]),
                                  section="modules", module_id=mid,
                                  field_path=blocks[0].get("field_path"))
    if hold_keys is None:
        hold_keys = restore_plan.security_hold_keys(gateway, payload, sel)
    core_mut = serializer.payload_to_mutation(payload, sel, apply_machine_bound=apply_machine_bound,
                                              hold_keys=hold_keys)
    if core_mut.is_empty() and not mod_snaps:
        return {"status": "noop", "changed": False, "held_keys": sorted(hold_keys or ())}
    # R-128: смена флага защиты вступает в силу только с перезапуском — считаем ДО применения.
    restart_on_change = restore_plan.restart_on_change(gateway, core_mut)

    # Guard неизменности projects/tasks: fingerprint ДО (если хранилище его умеет).
    fp_fn = getattr(gateway, "immutable_fingerprint", None)
    fp_before = fp_fn() if callable(fp_fn) else None

    # PRE-IMAGES всех хранилищ + SHA-256 каждого — в журнал ДО каких-либо мутаций.
    # Сбой чтения (например, запертая SQLite) здесь БЕЗОПАСЕН: ничего ещё не менялось.
    try:
        pre = {"__multi__": True,
               "core": gateway.full_snapshot(),
               "modules": {mid: module_stores[mid].full_snapshot() for mid, _p, _s in mod_snaps}}
    except Exception as e:
        from app.config_backup.errors import DATABASE_BUSY
        raise BackupError(DATABASE_BUSY, "pre-image failed: %s" % type(e).__name__)
    hashes = {"core": _sha(pre["core"])}
    for mid in pre["modules"]:
        hashes["module:" + mid] = _sha(pre["modules"][mid])
    order = ["core"] + [mid for mid, _p, _s in mod_snaps]
    journal.set_prepared(pre, meta={"sections": sorted(sel), "order": order, "hashes": hashes})
    journal.set_state("staging_modules")              # снапшоты уже мигрированы/провалидированы

    applied = []                                      # диагностический список (журнал/отчёт)
    def _rollback(reason):
        # ОБРАТНЫЙ порядок: ВСЕ выбранные модули (reversed) -> core. Откатываются и те store,
        # что упали ПОСРЕДИ apply (частичные изменения!), и нетронутые (no-op к своему pre-image);
        # каждый откат проверяется по SHA pre-image.
        ok_all = True
        for mid in reversed([m for m, _p, _s in mod_snaps]):
            journal.set_state("rolling_back_module:%s" % mid)
            try:
                module_stores[mid].restore_full(pre["modules"][mid])
                ok_all &= (_sha(module_stores[mid].full_snapshot()) == hashes["module:" + mid])
            except Exception:
                ok_all = False
        journal.set_state("rolling_back_core")
        try:
            gateway.restore_full(pre["core"])
            ok_all &= (_sha(gateway.full_snapshot()) == hashes["core"])
        except Exception:
            ok_all = False
        if not ok_all:
            journal.set_rollback_required(reason)
            raise BackupError(ROLLBACK_FAILED, "rollback failed after: %s" % reason)
        journal.complete()
        raise BackupError(ROLLBACK_COMPLETED, "rolled back: %s" % reason)

    try:
        journal.set_state("applying_core")
        gateway.apply_mutation(core_mut)
        applied.append("core")
        for mid, prov, snap in mod_snaps:
            journal.set_state("applying_module:%s" % mid)
            prov.apply_restore(module_stores[mid], snap)
            applied.append(mid)
    except BackupError:
        raise
    except Exception as e:
        _rollback("apply failed: %s" % type(e).__name__)

    journal.set_state("committed_pending_verify")
    journal.set_state("verifying_core")
    ok = False
    try:
        ok = _verify_core(gateway, core_mut)
    except Exception:
        ok = False
    if ok:
        for mid, prov, snap in mod_snaps:
            journal.set_state("verifying_module:%s" % mid)
            try:
                if not prov.verify_restore(module_stores[mid], snap):
                    ok = False
                    break
            except Exception:
                ok = False
                break
    immutable_violated = False
    if ok and fp_before is not None:
        try:
            immutable_violated = (fp_fn() != fp_before)
        except Exception:
            immutable_violated = True
        if immutable_violated:
            ok = False
    if not ok:
        _rollback("immutable data changed (projects/tasks)" if immutable_violated
                  else "verify failed")

    journal.complete()                                # общая verification пройдена -> pre-images затёрты
    from app.config_backup import settings_registry as reg
    restart = restart_on_change or any((reg.get(k) and reg.get(k).restart_required)
                                       for k in list(core_mut.config_set) + list(core_mut.app_set))
    return {"status": "ok", "changed": True, "restart_required": restart,
            "modules_applied": [m for m, _p, _s in mod_snaps],
            "config_changed": sorted(core_mut.config_set.keys()),
            "app_changed": sorted(core_mut.app_set.keys()),
            "printers_written": [r.get("id") for r in core_mut.printers_upsert],
            "held_keys": sorted(hold_keys or ())}


def recover_on_startup_multi(journal, gateway, module_stores=None):
    """Восстановление после падения процесса: multi-журнал откатывает ВСЕ хранилища
    (модули в обратном порядке, затем core). Одиночный (2.827/2.828) журнал — прежний путь."""
    j = journal.read()
    if not j or not journal.is_pending():
        return {"recovered": False}
    pre = j.get("pre_image")
    if not (isinstance(pre, dict) and pre.get("__multi__")):
        from app.config_backup.recovery import recover_on_startup
        return recover_on_startup(journal, gateway)
    mods = pre.get("modules") or {}
    mod_failed = []
    for mid in sorted(mods.keys(), reverse=True):
        store = (module_stores or {}).get(mid)
        if store is not None:
            try:
                store.restore_full(mods[mid])
            except Exception:
                #  13.10.2026: раньше сбой молча глотался, и ниже complete() стирал образ «до» —
                #  модуль оставался полувосстановленным, а повторить откат было нечем.
                mod_failed.append(mid)
        # store недоступен (модуль удалён между падением и стартом) — core всё равно откатываем
    try:
        gateway.restore_full(pre.get("core") or {})
    except Exception:
        journal.set_rollback_required("startup multi rollback failed")
        return {"recovered": True, "action": "rollback_failed", "state": j.get("state")}
    if mod_failed:
        #  Как у отката в работающей программе (_rollback): образ «до» сохраняется, журнал остаётся
        #  незавершённым — следующий запуск повторит откат модуля.
        journal.set_rollback_required("startup module rollback failed: " + ", ".join(mod_failed))
        return {"recovered": True, "action": "rollback_failed", "state": j.get("state"),
                "modules_failed": mod_failed}
    journal.complete()
    return {"recovered": True, "action": "rolled_back_multi", "state": j.get("state")}
