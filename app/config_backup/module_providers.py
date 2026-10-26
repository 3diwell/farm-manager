# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — ПОСТОЯННЫЙ контракт резервного копирования данных модулей.

Правило (AGENTS §13 / docs/MODULE_BACKUP_CONTRACT.md): КАЖДЫЙ установленный модуль обязан быть
классифицирован как ровно одно из:
  • persistent_data_with_backup_provider — есть пользовательские данные И есть provider;
  • no_persistent_user_data               — доказано, что пользовательских данных нет;
  • backup_temporarily_unsupported        — данные есть, provider ещё нет (ПОЛНЫЙ export БЛОКИРУЕТСЯ).
Модуль с пользовательскими данными без provider НЕ может молча пропускаться: полный export
завершается ошибкой с именем модуля. Незарегистрированный установленный модуль = красный тест.

Provider выдаёт ЛОГИЧЕСКУЮ каноническую JSON-модель (НЕ raw SQL dump, НЕ ORM rows, НЕ pickle),
имеет СОБСТВЕННУЮ backup_schema_version и append-only миграции, детерминирован, не обращается
к принтерам, не включает runtime-кэш и НИЧЕГО не меняет при inspect/plan.

Identity модуля = стабильный module_id (НЕ display name). Версия модуля — метаданные, не схема.

Провайдеры трёх текущих модулей живут В ЯДРЕ (module ZIP не меняются): ядро уже владеет
resolve_db и физическими путями. Будущий модуль может регистрировать собственный provider.

Forensic-обоснование состава (Alpha 2.829, читать до правок):
  inventory  -> есть данные (vendors/filaments/locations/items/spools/settings/ledger);
                inv_pending_prints — runtime-трекинг активных печатей, ИСКЛЮЧЁН.
                v2 (R-125): + мобильная приёмка — inv_mobile_codes/nfc/label_batches/labels;
                inv_mobile_ops (квитанции повторов запросов телефона) ИСКЛЮЧЁН.
  cost       -> v1 описывала прежнюю «Себестоимость печати» (cost_config/cost_printer_settings/
                cost_calculations; cost_run_durations — история печати — ИСКЛЮЧЁН).
                v2 (R-125): «Расчёт заказа» 3.0 — order_config, ставки моделей и принтеров,
                модели принтеров, счётчик номеров, заказы; order_files (копии файлов моделей по
                абсолютному пути) ИСКЛЮЧЁН — файлы копия не несёт. Старые данные v1 при миграции
                уходят в extensions, а не применяются.
  quality    -> НЕТ пользовательских данных: все 4 HTTP-маршрута GET-only, все колонки
                print_runs/print_run_materials/print_run_event_aliases захватываются
                автоматически из событий печати = журнал истории печати (менять запрещено).
  messengers -> настройки msg_settings без ключей ботов (msg_secrets не входит).
  appearance, camera_wall -> НЕТ пользовательских данных на сервере: только интерфейс, всё
                хранится в браузере (localStorage).
"""
import copy

from app.config_backup.errors import (BackupError, VALIDATION_FAILED, BACKUP_INVALID,
                                       BACKUP_FROM_NEWER_VERSION, MIGRATION_MISSING,
                                       MANUAL_RESOLUTION_REQUIRED)

# ── Классы модулей (fail-closed реестр) ────────────────────────────────────────
DATA_CLASS_PROVIDER = "persistent_data_with_backup_provider"
DATA_CLASS_NO_DATA = "no_persistent_user_data"
DATA_CLASS_UNSUPPORTED = "backup_temporarily_unsupported"
DATA_CLASSES = frozenset((DATA_CLASS_PROVIDER, DATA_CLASS_NO_DATA, DATA_CLASS_UNSUPPORTED))

MODULE_DATA_SECTION_SCHEMA = 1     # схема секции module_data (растёт независимо)

#  13.10.2026: пределы подняты — общий размер копии и так ограничен контейнером (12 МБ шифротекста),
#  а прежние 100 000 строк и 64 КБ на значение отменяли ВСЮ копию: журнал склада за ~год работы фермы,
#  заказ «Расчёта заказа» из ~29 файлов (payload_json больше 64 КБ).
MAX_ROWS_PER_TABLE = 1000000
MAX_STR = 4 * 1024 * 1024


class TableSpec(object):
    """Явная спецификация таблицы: имя, ключ, СПИСОК колонок (ничего лишнего не читается),
    внутренние ссылки (col -> таблица снапшота) и внешние ссылки (col -> 'printers').

    unique (R-125): наборы колонок с ограничением UNIQUE в схеме модуля (кроме ключа). Строка
    копии, чьё уникальное значение на цели занято ДРУГОЙ записью, при UPSERT нарушила бы
    ограничение и откатила ВСЁ восстановление посреди применения — поэтому такой конфликт
    находится заранее, на этапе плана (restore_conflicts)."""
    __slots__ = ("name", "key", "columns", "refs", "external_refs", "unique")

    def __init__(self, name, key, columns, refs=None, external_refs=None, unique=()):
        self.name = name
        self.key = key
        self.columns = tuple(columns)
        self.refs = dict(refs or {})
        self.external_refs = dict(external_refs or {})
        self.unique = tuple(tuple(u) for u in (unique or ()))


class DictModuleStore(object):
    """In-memory хранилище модуля для тестов: {таблица: [строки]} + settings map."""

    def __init__(self, tables=None, settings=None):
        self._tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}
        self._settings = dict(settings or {})

    def read_table(self, name):
        return [dict(r) for r in self._tables.get(name, [])]

    def read_settings(self):
        return dict(self._settings)

    def upsert_rows(self, name, rows, key):
        cur = self._tables.setdefault(name, [])
        idx = {str(r.get(key)): i for i, r in enumerate(cur)}
        for row in rows:
            k = str(row.get(key))
            if k in idx:
                cur[idx[k]] = dict(row)
            else:
                cur.append(dict(row))

    def write_settings(self, mapping):
        self._settings.update({str(k): str(v) for k, v in (mapping or {}).items()})

    def full_snapshot(self):
        return {"tables": copy.deepcopy(self._tables), "settings": dict(self._settings)}

    def restore_full(self, snap):
        snap = snap or {}
        self._tables = copy.deepcopy(snap.get("tables") or {})
        self._settings = dict(snap.get("settings") or {})


def _clip(v, where=""):
    if isinstance(v, str) and len(v) > MAX_STR:
        raise BackupError(VALIDATION_FAILED, "string too long in module data" + (" (%s)" % where if where else ""))
    return v


class ModuleBackupProvider(object):
    """Базовый provider: export/validate/migrate/plan/apply/verify по TableSpec-ам.

    ДЕТЕРМИНИРОВАН: строки сортируются по ключу; только явные колонки; настройки — плоская map.
    Restore = UPSERT по стабильному ключу; записи «только на текущей машине» НЕ удаляются
    (тот же принцип, что для принтеров). Никаких обращений к принтерам/сети/локали.
    """
    module_id = ""                      # стабильная identity (НЕ display name)
    backup_schema_version = 1
    data_class = DATA_CLASS_PROVIDER
    table_specs = ()                    # tuple[TableSpec]
    settings_source = None              # имя таблицы настроек (для документации)
    MIGRATIONS = None                   # {from_version: fn(domain_dict)->domain_dict} append-only

    # -- export ----------------------------------------------------------------
    def export_snapshot(self, store, installed_version="", enabled=True):
        """store -> канонический snapshot модуля (ЧТЕНИЕ; ничего не меняет)."""
        if self.data_class != DATA_CLASS_PROVIDER:
            return {"module_id": self.module_id, "backup_schema_version": self.backup_schema_version,
                    "data_class": self.data_class, "installed_module_version_at_export": str(installed_version),
                    "enabled": bool(enabled), "settings": {}, "domain_data": None,
                    "attachments_manifest": [], "extensions": {}}
        tables = {}
        for spec in self.table_specs:
            rows_out = []
            for row in store.read_table(spec.name):
                rows_out.append({c: _clip(row.get(c), "%s.%s.%s" % (self.module_id, spec.name, c)) for c in spec.columns})
            rows_out.sort(key=lambda r: str(r.get(spec.key)))
            if len(rows_out) > MAX_ROWS_PER_TABLE:
                raise BackupError(VALIDATION_FAILED, "too many rows in %s.%s" % (self.module_id, spec.name))
            tables[spec.name] = rows_out
        return {"module_id": self.module_id, "backup_schema_version": self.backup_schema_version,
                "data_class": self.data_class, "installed_module_version_at_export": str(installed_version),
                "enabled": bool(enabled), "settings": {str(k): str(v) for k, v in store.read_settings().items()},
                "domain_data": {"tables": tables}, "attachments_manifest": [], "extensions": {}}

    # -- migrate ---------------------------------------------------------------
    def migrate_snapshot(self, snapshot):
        """Append-only миграции СХЕМЫ МОДУЛЯ (не версии модуля!). Новее ридера -> отказ."""
        v = snapshot.get("backup_schema_version")
        if not isinstance(v, int) or v < 1:
            raise BackupError(BACKUP_INVALID, "bad module backup_schema_version")
        if v > self.backup_schema_version:
            raise BackupError(BACKUP_FROM_NEWER_VERSION,
                              "module '%s' snapshot from newer schema" % self.module_id)
        out = snapshot
        guard = 0
        while v < self.backup_schema_version:
            fn = (self.MIGRATIONS or {}).get(v)
            if fn is None:
                raise BackupError(MIGRATION_MISSING, "missing migration %s v%d" % (self.module_id, v))
            out = fn(copy.deepcopy(out))
            nv = out.get("backup_schema_version")
            if nv != v + 1:
                raise BackupError(MIGRATION_MISSING, "module migration v%d did not yield v%d" % (v, v + 1))
            v = nv
            guard += 1
            if guard > 1000:
                raise BackupError(MIGRATION_MISSING, "module migration loop guard")
        return out

    # -- validate --------------------------------------------------------------
    def validate_snapshot(self, snapshot):
        """Структура/уникальность ключей/внутренняя ссылочная целостность. Данные, не команды."""
        if snapshot.get("module_id") != self.module_id:
            raise BackupError(VALIDATION_FAILED, "module_id mismatch")
        if self.data_class != DATA_CLASS_PROVIDER:
            return snapshot
        dd = snapshot.get("domain_data")
        if not isinstance(dd, dict) or not isinstance(dd.get("tables"), dict):
            raise BackupError(VALIDATION_FAILED, "module domain_data missing")
        tables = dd["tables"]
        keysets = {}
        for spec in self.table_specs:
            rows = tables.get(spec.name)
            if rows is None:
                rows = []
            if not isinstance(rows, list):
                raise BackupError(VALIDATION_FAILED, "table %s not list" % spec.name)
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise BackupError(VALIDATION_FAILED, "row not object in %s" % spec.name)
                k = str(row.get(spec.key) or "")
                if not k:
                    raise BackupError(VALIDATION_FAILED, "empty key in %s" % spec.name)
                if k in seen:
                    raise BackupError(VALIDATION_FAILED, "duplicate key in %s" % spec.name)
                seen.add(k)
            keysets[spec.name] = seen
        # Alpha 2.830 (root cause validation_failed на реальной копии 2.829): непустая внутренняя
        # ссылка на ОТСУТСТВУЮЩУЮ запись (пример: локация удалена, а товар/катушка ещё на неё
        # ссылаются) — ЛЕГИТИМНОЕ состояние живой БД, НЕ повреждение. Такая запись СОХРАНЯЕТСЯ как
        # есть (значение не обнуляется), связь считается неактивной — тот же принцип, что и для
        # внешних ссылок на принтеры. Referential integrity здесь СОВЕТУЮЩАЯ (warning в плане),
        # НЕ фатальная. Структурная целостность выше (dict/пустой-ключ/дубликат/тип/длина)
        # остаётся ФАТАЛЬНОЙ — она отражает реальное повреждение снапшота.
        return snapshot

    def unresolved_internal_refs(self, snapshot):
        """Несопоставленные внутренние ссылки (цель удалена). ТОЛЬКО имена таблиц/колонок и
        счётчики — без значений. Для предупреждений плана; НЕ фатально (Alpha 2.830)."""
        out = []
        if self.data_class != DATA_CLASS_PROVIDER:
            return out
        dd = snapshot.get("domain_data")
        if not isinstance(dd, dict) or not isinstance(dd.get("tables"), dict):
            return out
        tables = dd["tables"]
        keysets = {}
        for spec in self.table_specs:
            keysets[spec.name] = {str(r.get(spec.key) or "") for r in (tables.get(spec.name) or [])
                                  if isinstance(r, dict)}
        for spec in self.table_specs:
            for col, target in spec.refs.items():
                tgt = keysets.get(target, set())
                cnt = 0
                for row in tables.get(spec.name) or []:
                    if not isinstance(row, dict):
                        continue
                    ref = str(row.get(col) or "")
                    if ref and ref not in tgt:
                        cnt += 1
                if cnt:
                    out.append({"table": spec.name, "column": col, "target": target, "count": cnt})
        return out

    # -- plan (только чтение) --------------------------------------------------
    def build_restore_plan(self, store, snapshot, known_printer_ids=None):
        """Diff по ключам: added/updated/current_only + warnings по внешним ссылкам на принтеры.
        НИЧЕГО не меняет. Секреты/значения наружу не отдаёт — только счётчики и ключи предупреждений."""
        if self.data_class != DATA_CLASS_PROVIDER or not snapshot.get("domain_data"):
            return {"module_id": self.module_id, "items": {}, "warnings": [], "counts":
                    {"added": 0, "updated": 0, "current_only": 0}}
        plan = {"module_id": self.module_id, "items": {}, "warnings": [],
                "counts": {"added": 0, "updated": 0, "current_only": 0}}
        tables = snapshot["domain_data"]["tables"]
        for spec in self.table_specs:
            cur_keys = {str(r.get(spec.key)) for r in store.read_table(spec.name)}
            snap_rows = tables.get(spec.name) or []
            snap_keys = {str(r.get(spec.key)) for r in snap_rows}
            added = len(snap_keys - cur_keys)
            updated = len(snap_keys & cur_keys)
            cur_only = len(cur_keys - snap_keys)
            plan["items"][spec.name] = {"added": added, "updated": updated, "current_only": cur_only}
            plan["counts"]["added"] += added
            plan["counts"]["updated"] += updated
            plan["counts"]["current_only"] += cur_only
            # внешние ссылки на принтеры: отсутствующий принтер НЕ удаляет запись — только warning
            if known_printer_ids is not None:
                for col, ext in spec.external_refs.items():
                    if ext != "printers":
                        continue
                    missing = sorted({str(r.get(col)) for r in snap_rows
                                      if str(r.get(col) or "") and str(r.get(col)) not in known_printer_ids})
                    for pid in missing:
                        plan["warnings"].append({"code": "missing_printer_ref",
                                                 "table": spec.name, "printer_id": pid})
        # Alpha 2.830: несопоставленные ВНУТРЕННИЕ ссылки (удалённая локация и т.п.) — запись
        # сохраняется как есть; предупреждаем счётчиком (без значений), restore не блокируется.
        for ur in self.unresolved_internal_refs(snapshot):
            plan["warnings"].append({"code": "dangling_internal_ref", "table": ur["table"],
                                     "column": ur["column"], "target": ur["target"],
                                     "count": ur["count"]})
        return plan

    # -- конфликты уникальности (только чтение; R-125) --------------------------
    def restore_conflicts(self, store, snapshot):
        """Строки копии, чьё значение из TableSpec.unique на цели уже занято ДРУГОЙ записью
        (другой ключ). -> [{code, table, column, count, field_path}] — только имена схемы и
        счётчики, без значений. Пусто — конфликтов нет. NULL в ограничении не участвует, как и
        в SQLite. НИЧЕГО не меняет."""
        out = []
        if self.data_class != DATA_CLASS_PROVIDER or not snapshot.get("domain_data"):
            return out
        tables = snapshot["domain_data"].get("tables") or {}
        for spec in self.table_specs:
            rows = tables.get(spec.name) or []
            if not spec.unique or not rows:
                continue
            current = store.read_table(spec.name)
            for cols in spec.unique:
                owners = {}
                for r in current:
                    val = tuple(r.get(c) for c in cols)
                    if any(v is None for v in val):
                        continue
                    owners.setdefault(tuple(str(v) for v in val), set()).add(str(r.get(spec.key)))
                cnt = 0
                for r in rows:
                    val = tuple(r.get(c) for c in cols)
                    if any(v is None for v in val):
                        continue
                    taken = owners.get(tuple(str(v) for v in val)) or set()
                    if taken - {str(r.get(spec.key))}:
                        cnt += 1
                if cnt:
                    out.append({"code": "module_restore_conflict", "table": spec.name,
                                "column": ",".join(cols), "count": cnt,
                                "field_path": "%s.%s" % (spec.name, cols[0])})
        return out

    # -- apply (мутация; вызывается ТОЛЬКО движком multistore под журналом) -----
    def apply_restore(self, store, snapshot):
        """UPSERT всех таблиц по ключам + настройки. Записи текущей машины не удаляются."""
        if self.data_class != DATA_CLASS_PROVIDER or not snapshot.get("domain_data"):
            return
        tables = snapshot["domain_data"]["tables"]
        for spec in self.table_specs:
            rows = tables.get(spec.name) or []
            store.upsert_rows(spec.name, [{c: r.get(c) for c in spec.columns} for r in rows], spec.key)
        store.write_settings(snapshot.get("settings") or {})

    # -- verify ----------------------------------------------------------------
    @staticmethod
    def _norm_val(v):
        """Каноникализация значения для сравнения: числа приводятся к float (SQLite REAL
        возвращает 1200.0 там, где снапшот несёт 1200 — это ОДНО значение)."""
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return float(v)
        return v

    def verify_restore(self, store, snapshot):
        """Перечитать store и сравнить канонические строки снапшота (нормализованные значения)."""
        if self.data_class != DATA_CLASS_PROVIDER or not snapshot.get("domain_data"):
            return True
        tables = snapshot["domain_data"]["tables"]
        for spec in self.table_specs:
            want = {str(r.get(spec.key)): {c: self._norm_val(r.get(c)) for c in spec.columns}
                    for r in (tables.get(spec.name) or [])}
            got = {str(r.get(spec.key)): {c: self._norm_val(r.get(c)) for c in spec.columns}
                   for r in store.read_table(spec.name)}
            for k, row in want.items():
                if k not in got:
                    return False
                if got[k] != row:
                    return False
        cur = store.read_settings()
        for k, v in (snapshot.get("settings") or {}).items():
            if str(cur.get(k)) != str(v):
                return False
        return True

    def describe_scope(self, locale="ru"):
        return {"module_id": self.module_id, "data_class": self.data_class, "tables":
                [s.name for s in self.table_specs]}


# ═══════════════════════════════════════════════════════════════════════════════
# Провайдер: Складской учёт (inventory). Схема backup v1 заморожена; v2 (R-125) добавила
# мобильную приёмку: коды QR/штрихкодов, метки NFC и подготовленные наклейки.
# ═══════════════════════════════════════════════════════════════════════════════
_INVENTORY_MOBILE_TABLES = ("inv_mobile_codes", "inv_mobile_nfc", "inv_mobile_label_batches",
                            "inv_mobile_labels")


def _inventory_v1_to_v2(snap):
    """v1 -> v2 (append-only). В копиях до R-125 мобильных таблиц склада не было: они
    добавляются ПУСТЫМИ, и восстановление такой копии их не трогает (UPSERT пустого списка —
    ничего), коды и метки на цели остаются. Остальные таблицы и настройки — без изменений."""
    out = dict(snap)
    dd = snap.get("domain_data")
    if isinstance(dd, dict) and isinstance(dd.get("tables"), dict):
        tables = dict(dd["tables"])
        for name in _INVENTORY_MOBILE_TABLES:
            tables.setdefault(name, [])
        out["domain_data"] = dict(dd, tables=tables)
    out["backup_schema_version"] = 2
    return out


class InventoryBackupProvider(ModuleBackupProvider):
    module_id = "inventory"
    backup_schema_version = 2
    data_class = DATA_CLASS_PROVIDER
    settings_source = "inv_settings"
    MIGRATIONS = {1: _inventory_v1_to_v2}
    table_specs = (
        TableSpec("inv_vendors", "id",
                  ("id", "name", "notes", "order_idx", "is_deleted", "created_at", "updated_at")),
        TableSpec("inv_filaments", "id",
                  ("id", "vendor_id", "material", "color_name", "color_hex", "diameter", "density",
                   "temp_min", "temp_max", "spool_weight_g", "price_per_kg", "notes", "order_idx",
                   "is_deleted", "created_at", "updated_at"),
                  refs={"vendor_id": "inv_vendors"}),
        TableSpec("inv_locations", "id",
                  ("id", "name", "parent_id", "notes", "order_idx", "is_deleted", "created_at")),
        TableSpec("inv_items", "id",
                  ("id", "name", "category", "unit", "qty", "min_qty", "max_qty", "location_id",
                   "price", "printer_brand", "printer_model", "notes", "order_idx", "is_deleted",
                   "created_at", "updated_at"),
                  refs={"location_id": "inv_locations"}),
        TableSpec("inv_spools", "id",
                  ("id", "filament_id", "label", "weight_total_g", "weight_remaining_g",
                   "location_id", "price", "lot", "purchased_at", "opened_at", "status", "nfc_uid",
                   "ams_printer_id", "ams_slot", "notes", "order_idx", "is_deleted",
                   "created_at", "updated_at"),
                  refs={"filament_id": "inv_filaments", "location_id": "inv_locations"},
                  external_refs={"ams_printer_id": "printers"}),
        # Складская книга операций — пользовательская учётная история склада (НЕ история печати).
        TableSpec("inv_ledger", "id",
                  ("id", "ts", "kind", "ref_type", "ref_id", "qty", "reason", "job_id",
                   "username", "note")),
        # inv_pending_prints ИСКЛЮЧЁН: runtime-трекинг активных печатей (forensic 2.829).
        # ── v2 (R-125, data-safety-07): мобильная приёмка (modules/inventory/mobile_api.py) ──
        # Коды QR/штрихкодов, привязанные к филаменту или катушке (и «nfc:bambu:<uid>»). Без них
        # после восстановления телефон не узнаёт уже принятые коды и примет катушку второй раз.
        TableSpec("inv_mobile_codes", "code", ("code", "kind", "filament_id", "spool_id"),
                  refs={"filament_id": "inv_filaments", "spool_id": "inv_spools"}),
        # Метки NFC катушек; строка живёт и после удаления катушки (повторной приёмки не будет).
        TableSpec("inv_mobile_nfc", "uid", ("uid", "spool_id", "created_at"),
                  refs={"spool_id": "inv_spools"}),
        # Подготовленные наклейки: партия и её номера. id наклейки — будущий id катушки, а
        # код на наклейке несёт inv_settings.mobile_server_id — он восстанавливается настройками.
        TableSpec("inv_mobile_label_batches", "id",
                  ("id", "name", "filament_id", "caption", "weight_total_g", "label", "created_at"),
                  refs={"filament_id": "inv_filaments"}),
        TableSpec("inv_mobile_labels", "id",
                  ("id", "batch_id", "ordinal", "status", "location_id", "received_at",
                   "cancelled_at"),
                  refs={"batch_id": "inv_mobile_label_batches", "location_id": "inv_locations"},
                  unique=(("batch_id", "ordinal"),)),
        # inv_mobile_ops ИСКЛЮЧЁН: квитанции повторов запросов телефона — служебный журнал
        # идемпотентности, как inv_pending_prints, а не данные склада.
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Провайдер: модуль cost. Схема backup v1 (заморожена) описывала прежнюю «Себестоимость
# печати»: cost_printer_settings, cost_calculations и настройки cost_config. С 3.0 под тем же id
# стоит «Расчёт заказа» (слово владельца 12.09.2026) со СВОИМИ таблицами — v1 давала пустую
# копию заказов, а старая копия на чистой 3.0 откатывала всё восстановление (таблиц cost_*
# нет — UPSERT молча пропускался, проверка падала). v2 (R-125, modules-05/data-safety-06)
# описывает настоящую схему модуля (modules/cost/backend.py, DDL).
# ═══════════════════════════════════════════════════════════════════════════════
LEGACY_COST_EXT = "x-legacy_cost_v1"


def _cost_v1_to_v2(snap):
    """v1 («Себестоимость печати») -> v2 («Расчёт заказа»), append-only.

    Модуль 3.0 таблиц cost_* не создаёт и не читает: применять их некуда. Данные при этом НЕ
    выбрасываются — переносятся как есть в extensions[LEGACY_COST_EXT] (остаются в копии,
    план сообщает о них счётчиком), а таблицы и настройки v2 в такой копии пустые: восстановление
    не трогает заказы на цели и не откатывает остальное восстановление."""
    out = dict(snap)
    dd = snap.get("domain_data")
    tables = dd.get("tables") if isinstance(dd, dict) and isinstance(dd.get("tables"), dict) else {}
    ext = dict(snap.get("extensions") or {})
    ext[LEGACY_COST_EXT] = {
        "tables": {str(k): (list(v) if isinstance(v, list) else []) for k, v in tables.items()},
        "settings": dict(snap.get("settings") or {}),
    }
    out["extensions"] = ext
    out["settings"] = {}
    if isinstance(dd, dict):
        out["domain_data"] = {"tables": {}}
    out["backup_schema_version"] = 2
    return out


def _as_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


class CostBackupProvider(ModuleBackupProvider):
    module_id = "cost"
    backup_schema_version = 2
    data_class = DATA_CLASS_PROVIDER
    # Настройки «Расчёта заказа» — строка 'global' таблицы order_config. Она не «ключ-значение»:
    # у order_config есть колонка updated_at NOT NULL, поэтому таблица идёт обычной TableSpec.
    settings_source = None
    MIGRATIONS = {1: _cost_v1_to_v2}
    SEQUENCE_TABLE = "order_sequence"
    table_specs = (
        TableSpec("order_config", "key", ("key", "value", "updated_at")),
        TableSpec("order_model_rates", "model_key",
                  ("model_key", "model_name", "power_w", "amortization_per_hour",
                   "service_per_hour", "updated_at")),
        TableSpec("order_printer_rates", "printer_id",
                  ("printer_id", "printer_model", "amortization_per_hour", "service_per_hour",
                   "power_override_w", "amortization_override_enabled",
                   "service_override_enabled", "updated_at"),
                  external_refs={"printer_id": "printers"}),
        TableSpec("order_printer_models", "printer_id",
                  ("printer_id", "model_name", "model_key", "source", "updated_at"),
                  external_refs={"printer_id": "printers"}),
        # Счётчик номеров заказов по годам: применяется как MAX(текущее, из копии), иначе после
        # восстановления старой копии номера пошли бы повторно (apply/verify ниже).
        TableSpec("order_sequence", "year", ("year", "last_seq")),
        # Заказы целиком (расчёт и состав — в payload_json/calculation_json). order_number
        # уникален в схеме модуля: занятый ДРУГИМ заказом номер блокирует восстановление модуля
        # на этапе плана (restore_conflicts), а не откатом посреди применения.
        TableSpec("orders", "internal_id",
                  ("internal_id", "order_number", "title", "status", "created_date", "due_date",
                   "project_id", "project_name", "external_crm_id", "crm_sync_status", "currency",
                   "currency_symbol", "full_cost", "customer_price", "payload_json",
                   "calculation_json", "created_at", "updated_at"),
                  unique=(("order_number",),)),
        # order_files ИСКЛЮЧЁН: строки описывают копии файлов моделей в cost_order_files\ по
        # абсолютному пути; сами файлы копия не несёт (вложения — формат контейнера v3, решение
        # владельца). Заказ восстанавливается без файлов — это написано в окне копии.
        # Таблицы прежней «Себестоимости» (cost_*) модуль 3.0 не использует — их нет в v2.
    )

    def build_restore_plan(self, store, snapshot, known_printer_ids=None):
        plan = super().build_restore_plan(store, snapshot, known_printer_ids=known_printer_ids)
        legacy = (snapshot.get("extensions") or {}).get(LEGACY_COST_EXT)
        if isinstance(legacy, dict):
            rows = sum(len(v) for v in (legacy.get("tables") or {}).values() if isinstance(v, list))
            if rows or legacy.get("settings"):
                plan["warnings"].append({
                    "code": "legacy_cost_not_restored", "count": rows,
                    "text": "Данные прежней «Себестоимости печати» из этой копии не восстанавливаются "
                            "(модуль «Расчёт заказа» их не использует): записей %d" % rows,
                    "text_en": "Data of the former “Print cost” module in this backup is not "
                               "restored (Order calculation does not use it): %d records" % rows})
        return plan

    def apply_restore(self, store, snapshot):
        """UPSERT как у базового; счётчик номеров — MAX(текущее, из копии)."""
        if self.data_class != DATA_CLASS_PROVIDER or not snapshot.get("domain_data"):
            return
        tables = dict(snapshot["domain_data"].get("tables") or {})
        seq = tables.get(self.SEQUENCE_TABLE) or []
        if seq:
            cur = {str(r.get("year")): _as_int(r.get("last_seq"))
                   for r in store.read_table(self.SEQUENCE_TABLE)}
            tables[self.SEQUENCE_TABLE] = [
                dict(r, last_seq=max(_as_int(r.get("last_seq")), cur.get(str(r.get("year")), 0)))
                for r in seq]
        snap = dict(snapshot)
        snap["domain_data"] = dict(snapshot["domain_data"], tables=tables)
        return super().apply_restore(store, snap)

    def verify_restore(self, store, snapshot):
        """Как у базового, но счётчик номеров сверяется «не меньше, чем в копии»."""
        if self.data_class != DATA_CLASS_PROVIDER or not snapshot.get("domain_data"):
            return True
        tables = snapshot["domain_data"].get("tables") or {}
        rest = dict(snapshot)
        rest["domain_data"] = {"tables": {k: v for k, v in tables.items()
                                          if k != self.SEQUENCE_TABLE}}
        if not super().verify_restore(store, rest):
            return False
        got = {str(r.get("year")): _as_int(r.get("last_seq"), -1)
               for r in store.read_table(self.SEQUENCE_TABLE)}
        for r in tables.get(self.SEQUENCE_TABLE) or []:
            if got.get(str(r.get("year")), -1) < _as_int(r.get("last_seq")):
                return False
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# Провайдер: Аналитика качества (quality) — ДОКАЗАНО no_persistent_user_data:
# 0 write-маршрутов; print_runs/print_run_materials/print_run_event_aliases — авто-журнал
# истории печати (контракт запрещает менять историю печати при restore).
# ═══════════════════════════════════════════════════════════════════════════════
class QualityBackupProvider(ModuleBackupProvider):
    module_id = "quality"
    backup_schema_version = 1
    data_class = DATA_CLASS_NO_DATA
    table_specs = ()
    MIGRATIONS = {}


# ════════════════════════════════════════════════════════
# Провайдер: Уведомления в мессенджеры (messengers, 2.994) — persistent_data_with_backup_provider.
# Данные модуля: msg_settings (key/value: JSON раздела настроек БЕЗ секретов — язык, события,
# включён ли канал, chat_id/peer_id, имя бота, название сообщества). Таблица msg_secrets
# (ключи ботов) в спеках НАРОЧНО отсутствует: ключи в копию не входят — два экземпляра фермы
# с одними ключами слали бы всё дважды, а копия может уйти постороннему. После восстановления
# на другой машине каналы подключают заново мастером (две кнопки), остальное восстанавливается.
# ════════════════════════════════════════════════════════
class MessengersBackupProvider(ModuleBackupProvider):
    module_id = "messengers"
    backup_schema_version = 1
    data_class = DATA_CLASS_PROVIDER
    settings_source = "msg_settings"
    table_specs = ()
    MIGRATIONS = {}


# ════════════════════════════════════════════════════════
# Провайдер: Оформление и темы (appearance, 3.0) — ДОКАЗАНО no_persistent_user_data.
# Модуль только интерфейса: бэкенда, базы данных и маршрутов у него нет, темы лежат в браузере
# (localStorage, ключи fm_appearance_*) и на сервер не попадают. Без этой классификации установка
# модуля блокировала бы полный экспорт копии (fail-closed) — это показала проверка на настоящем
# сервере 12.09.2026. Доказательство — tools/test_appearance_module.py (A3, A5).
# ════════════════════════════════════════════════════════
class AppearanceBackupProvider(ModuleBackupProvider):
    module_id = "appearance"
    backup_schema_version = 1
    data_class = DATA_CLASS_NO_DATA
    table_specs = ()
    MIGRATIONS = {}


# ════════════════════════════════════════════════════════
# Провайдер: Видеостена (camera_wall, R-125) — ДОКАЗАНО no_persistent_user_data.
# Модуль только интерфейса: backend.py нет, значит нет ни базы, ни маршрутов. Источники камер,
# выбор и раскладка лежат в браузере (localStorage, ключи «3diwell.camera_wall.*»,
# modules/camera_wall/web/camera-store.js), с сервера модуль только читает (/api/printers,
# камеры принтеров). Без этой классификации установленная «Видеостена» блокировала полный
# экспорт копии (fail-closed, 409 manual_resolution_required).
# ════════════════════════════════════════════════════════
class CameraWallBackupProvider(ModuleBackupProvider):
    module_id = "camera_wall"
    backup_schema_version = 1
    data_class = DATA_CLASS_NO_DATA
    table_specs = ()
    MIGRATIONS = {}


# ── Реестр провайдеров (fail-closed) ──────────────────────────────────────────
_PROVIDERS = {}
for _p in (InventoryBackupProvider(), CostBackupProvider(), QualityBackupProvider(), MessengersBackupProvider(),
           AppearanceBackupProvider(), CameraWallBackupProvider()):
    if _p.module_id in _PROVIDERS:
        raise RuntimeError("duplicate module_id in provider registry: %s" % _p.module_id)
    _PROVIDERS[_p.module_id] = _p


def get_provider(module_id):
    return _PROVIDERS.get(str(module_id))


def all_providers():
    return dict(_PROVIDERS)


def check_export_completeness(installed_module_ids):
    """Fail-closed: полный export невозможен, если установлен модуль без классификации
    либо с data_class=backup_temporarily_unsupported. -> список проблемных имён (пусто = ок)."""
    problems = []
    for mid in sorted(set(str(m) for m in installed_module_ids)):
        p = _PROVIDERS.get(mid)
        if p is None:
            problems.append(mid)
        elif p.data_class == DATA_CLASS_UNSUPPORTED:
            problems.append(mid)
    return problems


def require_export_completeness(installed_module_ids):
    problems = check_export_completeness(installed_module_ids)
    if problems:
        raise BackupError(MANUAL_RESOLUTION_REQUIRED,
                          "modules without backup provider: %s" % ",".join(problems))
