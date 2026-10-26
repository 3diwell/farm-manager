# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — граница хранилища (storage gateway).

ЕДИНСТВЕННОЕ место, знающее физические имена таблиц/файлов/колонок. Всё остальное
(serializer/validator/restore_engine) работает с логическими DTO. НЕ сериализуем ORM-строки,
НЕ используем row.__dict__, НЕ используем pickle — читаем и пишем ТОЛЬКО явные колонки/ключи.

Реальный gateway (ServerStorageGateway) собирается в server.py из уже существующих
атомарных примитивов (_read_config/_write_config_atomic/_get_setting/_set_setting/conn_pr).
Здесь — протокол + DictGateway (для тестов) + отображение printer-строки ⇄ PrinterSnapshot.
"""
from app.config_backup import schemas
from app.config_backup.models import PrinterSnapshot

# Явный список колонок таблицы printers (id — идентичность, token — секрет, last_parts — кэш).
PRINTER_COLUMNS = ("id", "name", "type", "ip", "port", "token",
                   "last_parts", "order_idx", "gen", "serial", "model")

# last_parts — операционный кэш (последние детали), НЕ конфигурация: в резерв не входит.
PRINTER_OPERATIONAL_COLUMNS = ("last_parts",)

# Известные типы принтеров (значение колонки type). Неизвестный тип не роняет экспорт —
# сохраняется как есть с adapter_schema_version=1 (forward-friendly).
KNOWN_PRINTER_TYPES = frozenset(schemas.ADAPTER_SCHEMAS.keys())


def _adapter_schema_for(ptype):
    return int(schemas.ADAPTER_SCHEMAS.get(str(ptype or "").strip().lower(), 1))


def printer_row_to_snapshot(row):
    """Явное отображение строки printers -> PrinterSnapshot. Секрет (token) идёт в credentials
    (только внутри шифра). id сохраняется как stable_id (идентичность принтера при restore)."""
    ptype = str(row.get("type") or "bambu").strip().lower()
    port = row.get("port")
    try:
        port = int(port) if port not in (None, "") else None
    except Exception:
        port = None
    try:
        order_idx = int(row.get("order_idx") or 0)
    except Exception:
        order_idx = 0
    return PrinterSnapshot(
        stable_id=str(row.get("id") or ""),
        adapter=ptype,
        adapter_schema_version=_adapter_schema_for(ptype),
        display_name=str(row.get("name") or ""),
        model=str(row.get("model") or ""),
        enabled=True,
        connection={"ip": str(row.get("ip") or ""), "port": port,
                    "gen": str(row.get("gen") or "auto"), "serial": str(row.get("serial") or "")},
        options={"order_idx": order_idx},
        credentials={"token": str(row.get("token") or "")},
    )


def snapshot_to_printer_row(snap):
    """Обратное отображение PrinterSnapshot -> строка printers (явные колонки).
    last_parts НЕ трогаем при restore существующего (сохраняем текущий кэш); для нового = '{}'."""
    conn = snap.connection or {}
    opts = snap.options or {}
    creds = snap.credentials or {}
    return {
        "id": str(snap.stable_id or ""),
        "name": str(snap.display_name or ""),
        "type": str(snap.adapter or "bambu").strip().lower(),
        "ip": str(conn.get("ip") or ""),
        "port": conn.get("port"),
        "token": str(creds.get("token") or ""),
        "order_idx": int(opts.get("order_idx") or 0),
        "gen": str(conn.get("gen") or "auto"),
        "serial": str(conn.get("serial") or ""),
        "model": str(snap.model or ""),
    }


class StorageGateway(object):
    """Протокол (документация). Конкретные реализации: DictGateway (тест), ServerStorageGateway.

    Экспорт (только чтение):
      get_config_json() -> dict
      get_app_setting(key) -> str | None
      list_printers() -> list[dict]        (явные колонки PRINTER_COLUMNS)
      get_module_settings() -> dict        (module_id -> {"enabled": bool, "values": dict})

    Restore (мутации; атомарность обеспечивает конкретная реализация):
      full_snapshot() -> opaque            (pre-image для rollback: всё хранилище)
      restore_full(opaque) -> None         (компенсирующий откат к pre-image)
      apply_mutation(mutation) -> None     (атомарно применить набор изменений)
    """

    def get_config_json(self):
        raise NotImplementedError

    def get_app_setting(self, key):
        raise NotImplementedError

    def list_printers(self):
        raise NotImplementedError

    def get_module_settings(self):
        raise NotImplementedError

    def full_snapshot(self):
        raise NotImplementedError

    def restore_full(self, snap):
        raise NotImplementedError

    def apply_mutation(self, mutation):
        raise NotImplementedError


class Mutation(object):
    """Набор изменений для атомарного применения при restore."""

    def __init__(self):
        self.config_set = {}        # key -> value (config.json)
        self.app_set = {}           # key -> str value (app_settings)
        self.printers_upsert = []   # list[row dict] (явные колонки)
        # v1: принтеры «только на текущей машине» НЕ удаляются (owner-решение).

    def is_empty(self):
        return not (self.config_set or self.app_set or self.printers_upsert)


class DictGateway(StorageGateway):
    """In-memory реализация для тестов: тривиально атомарна (глубокая копия)."""

    def __init__(self, config=None, app_settings=None, printers=None, modules=None):
        import copy
        self._config = copy.deepcopy(dict(config or {}))
        self._app = dict(app_settings or {})
        self._printers = [dict(p) for p in (printers or [])]
        self._modules = copy.deepcopy(dict(modules or {}))

    def get_config_json(self):
        import copy
        return copy.deepcopy(self._config)

    def get_app_setting(self, key):
        return self._app.get(key)

    def list_printers(self):
        return [dict(p) for p in self._printers]

    def get_module_settings(self):
        import copy
        return copy.deepcopy(self._modules)

    def full_snapshot(self):
        import copy
        return {"config": copy.deepcopy(self._config), "app": dict(self._app),
                "printers": [dict(p) for p in self._printers], "modules": copy.deepcopy(self._modules)}

    def restore_full(self, snap):
        import copy
        self._config = copy.deepcopy(snap.get("config") or {})
        self._app = dict(snap.get("app") or {})
        self._printers = [dict(p) for p in (snap.get("printers") or [])]
        self._modules = copy.deepcopy(snap.get("modules") or {})

    def apply_mutation(self, mutation):
        for k, v in mutation.config_set.items():
            self._config[k] = v
        for k, v in mutation.app_set.items():
            self._app[k] = v
        by_id = {p.get("id"): i for i, p in enumerate(self._printers)}
        for row in mutation.printers_upsert:
            pid = row.get("id")
            if pid in by_id:
                # обновляем существующий, сохраняя операционный last_parts текущей машины
                cur = self._printers[by_id[pid]]
                merged = dict(row)
                for opcol in PRINTER_OPERATIONAL_COLUMNS:
                    if opcol in cur:
                        merged[opcol] = cur[opcol]
                self._printers[by_id[pid]] = merged
            else:
                nr = dict(row)
                nr.setdefault("last_parts", "{}")
                self._printers.append(nr)
