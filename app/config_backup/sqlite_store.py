# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — SQLite-адаптер хранилища модуля для резервного копирования.

ГРАНИЦА ХРАНИЛИЩА: знает физическую БД модуля и работает ТОЛЬКО с таблицами из явных
TableSpec провайдера + таблицей настроек. Runtime-таблицы модуля (не в спеках) не читает
и не трогает. Канонический пользовательский backup остаётся ЛОГИЧЕСКИМ (JSON от провайдера);
этот адаптер лишь читает/пишет строки. Короткоживущие подключения (busy_timeout) — модульные
backend'ы держат собственные соединения в том же процессе (WAL это допускает); запертая БД
даёт исключение -> движок multistore выполняет откат (fail-safe).

full_snapshot()/restore_full() — ЛОГИЧЕСКИЙ pre-image (строки спек-таблиц + настройки) для
внутреннего rollback текущей установки; это НЕ пользовательский формат резервной копии.
С 16.10.2026 (R-151) строки pre-image содержат ВСЕ столбцы таблицы, а не только столбцы спецификации.

R-125: файла базы может ещё не быть — модуль установлен, но ни разу не запускался (например,
отключён сразу после установки: отключённые модули тоже входят в копию). Такая база читается как
пустая и НЕ создаётся: экспорт и план ничего не меняют на диске. has_table() даёт движку
multistore узнать ДО применения, что таблиц из копии на цели нет (модуль старее копии) —
вместо молчаливого пропуска и отката всего восстановления.
"""
import base64
import os
import sqlite3

BUSY_TIMEOUT_MS = 5000


class SqliteModuleStore(object):
    def __init__(self, db_path, table_specs, settings_table=None, settings_cols=("key", "value")):
        self.db_path = str(db_path)
        self.specs = {s.name: s for s in (table_specs or ())}
        self.settings_table = settings_table
        self.settings_cols = tuple(settings_cols)

    def _db_exists(self):
        return os.path.isfile(self.db_path)

    def _conn(self):
        c = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_MS / 1000.0)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
        return c

    def _table_exists(self, c, name):
        return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                         (name,)).fetchone() is not None

    def db_exists(self):
        """Создан ли файл базы модуля (модуль хоть раз запускался). Только чтение."""
        return self._db_exists()

    def has_table(self, name):
        """Есть ли таблица в базе модуля (нет файла базы — нет и таблицы). Только чтение."""
        if not self._db_exists():
            return False
        c = self._conn()
        try:
            return self._table_exists(c, name)
        finally:
            c.close()

    # ── чтение (export/plan) ──────────────────────────────────────────────────
    def read_table(self, name):
        spec = self.specs.get(name)
        if spec is None or not self._db_exists():
            return []
        c = self._conn()
        try:
            if not self._table_exists(c, name):
                return []
            cols = ", ".join('"%s"' % col for col in spec.columns)
            return [{col: r[col] for col in spec.columns}
                    for r in c.execute("SELECT %s FROM \"%s\"" % (cols, name)).fetchall()]
        finally:
            c.close()

    def read_settings(self):
        if not self.settings_table or not self._db_exists():
            return {}
        k, v = self.settings_cols[0], self.settings_cols[1]
        c = self._conn()
        try:
            if not self._table_exists(c, self.settings_table):
                return {}
            return {str(r[k]): ("" if r[v] is None else str(r[v]))
                    for r in c.execute('SELECT "%s","%s" FROM "%s"'
                                       % (k, v, self.settings_table)).fetchall()}
        finally:
            c.close()

    # ── запись (apply; вызывается ТОЛЬКО движком multistore под журналом) ─────
    def upsert_rows(self, name, rows, key):
        spec = self.specs.get(name)
        if spec is None or not rows or not self._db_exists():
            return
        c = self._conn()
        try:
            if not self._table_exists(c, name):
                return
            cols = list(spec.columns)
            ph = ", ".join("?" for _ in cols)
            upd = ", ".join('"%s"=excluded."%s"' % (col, col) for col in cols if col != key)
            sql = ('INSERT INTO "%s" (%s) VALUES (%s) ON CONFLICT("%s") DO UPDATE SET %s'
                   % (name, ", ".join('"%s"' % col for col in cols), ph, key, upd))
            with c:                                    # транзакция: commit/rollback атомарно
                for row in rows:
                    c.execute(sql, tuple(row.get(col) for col in cols))
        finally:
            c.close()

    def write_settings(self, mapping):
        if not self.settings_table or not mapping or not self._db_exists():
            return
        k, v = self.settings_cols[0], self.settings_cols[1]
        c = self._conn()
        try:
            if not self._table_exists(c, self.settings_table):
                return
            with c:
                for kk, vv in mapping.items():
                    c.execute('INSERT INTO "%s" ("%s","%s") VALUES (?,?) '
                              'ON CONFLICT("%s") DO UPDATE SET "%s"=excluded."%s"'
                              % (self.settings_table, k, v, k, v, v), (str(kk), str(vv)))
        finally:
            c.close()

    # ── pre-image / rollback (внутренний механизм, НЕ пользовательский формат) ─
    #  16.10.2026 (R-151, аудит data-safety-11): pre-image хранит ВСЕ столбцы строки, а не только
    #  столбцы спецификации провайдера. Прежде откат неудачного восстановления очищал таблицу и
    #  вставлял строки без столбцов, которых спецификация ядра ещё не знала (их добавила более новая
    #  версия модуля), — значения в них сбрасывались, а сверка хеша этого не видела (считалась по
    #  тому же урезанному набору). Байтовые значения хранятся как {"$b64": ...}: журнал — JSON.
    #  Экспорт (read_table) по-прежнему отдаёт только столбцы спецификации.
    _B64 = "$b64"

    def _read_table_physical(self, name):
        spec = self.specs.get(name)
        if spec is None or not self._db_exists():
            return []
        c = self._conn()
        try:
            if not self._table_exists(c, name):
                return []
            order = (' ORDER BY "%s"' % spec.key) if getattr(spec, "key", None) else ""
            out = []
            for r in c.execute('SELECT * FROM "%s"%s' % (name, order)).fetchall():
                row = {}
                for col in r.keys():
                    v = r[col]
                    if isinstance(v, (bytes, bytearray, memoryview)):
                        v = {self._B64: base64.b64encode(bytes(v)).decode("ascii")}
                    row[col] = v
                out.append(row)
            return out
        finally:
            c.close()

    @classmethod
    def _decode_value(cls, v):
        if isinstance(v, dict) and set(v) == {cls._B64}:
            try:
                return base64.b64decode(v[cls._B64])
            except Exception:
                return None
        return v

    def full_snapshot(self):
        out = {"tables": {}, "settings": self.read_settings()}
        for name in self.specs:
            out["tables"][name] = self._read_table_physical(name)
        return out

    def restore_full(self, snap):
        """Вернуть спек-таблицы и настройки к pre-image: очистить и вставить прежние строки.
        Таблицы вне спеков (runtime) не трогаются. Нет файла базы — возвращать нечего.

        Таблица (или настройки), которой НЕТ в pre-image, не трогается: журнал мог остаться от
        прежней сборки с другим составом таблиц (обновление программы после сбоя посреди
        восстановления). Очистка такой таблицы стёрла бы данные, которые тот restore не менял
        (заказы, коды QR/NFC). Свой pre-image содержит все спек-таблицы — поведение прежнее.

        16.10.2026 (R-151): вставляются все столбцы строки pre-image, которые есть в таблице сейчас
        (PRAGMA table_info) — так сохраняются и столбцы более новой версии модуля. Журнал прежнего
        формата (только столбцы спецификации) восстанавливается как раньше."""
        snap = snap or {}
        snap_tables = snap.get("tables") or {}
        if not self._db_exists():
            return
        c = self._conn()
        try:
            with c:
                for name, spec in self.specs.items():
                    if name not in snap_tables or not self._table_exists(c, name):
                        continue
                    physical = [str(r[1]) for r in c.execute('PRAGMA table_info("%s")' % name).fetchall()]
                    c.execute('DELETE FROM "%s"' % name)
                    rows = snap_tables.get(name) or []
                    for row in rows:
                        cols = [col for col in physical if col in (row or {})]
                        if not cols:
                            continue
                        ph = ", ".join("?" for _ in cols)
                        c.execute('INSERT INTO "%s" (%s) VALUES (%s)'
                                  % (name, ", ".join('"%s"' % col for col in cols), ph),
                                  tuple(self._decode_value(row.get(col)) for col in cols))
                if (self.settings_table and "settings" in snap
                        and self._table_exists(c, self.settings_table)):
                    k, v = self.settings_cols[0], self.settings_cols[1]
                    c.execute('DELETE FROM "%s"' % self.settings_table)
                    for kk, vv in (snap.get("settings") or {}).items():
                        c.execute('INSERT INTO "%s" ("%s","%s") VALUES (?,?)'
                                  % (self.settings_table, k, v), (str(kk), str(vv)))
        finally:
            c.close()
