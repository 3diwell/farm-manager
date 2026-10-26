# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Хранение настроек модуля в его собственной БД (core.resolve_db("farm_messengers.db")).

Две таблицы, нарочно раздельные:
  msg_settings(key, value) — всё, что НЕ секрет: язык, события, включён ли канал, chat_id,
                             имя бота, название сообщества. Эта таблица входит в резервную
                             копию (провайдер модуля в ядре читает именно её).
  msg_secrets(key, value)  — ключи ботов. В копию НЕ входят: два экземпляра фермы с одними
                             ключами слали бы каждое сообщение дважды, а копия может уйти
                             постороннему. На новой машине канал подключают заново.

Ключи в msg_settings: "config" — JSON всего раздела без секретных полей.
Ключи в msg_secrets: "<kind>.<поле>" — по одному значению на секрет.
"""
import json
import sqlite3
import threading

DDL = (
    "CREATE TABLE IF NOT EXISTS msg_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS msg_secrets (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')",
)


class SettingsStore(object):
    def __init__(self, db_path, secret_keys):
        """secret_keys: {kind: [имена секретных полей]} — из реестра площадок."""
        self.db_path = str(db_path)
        self._secret_keys = {k: list(v) for k, v in (secret_keys or {}).items()}
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            for ddl in DDL:
                self._conn.execute(ddl)
            self._conn.commit()

    def _get(self, table, key):
        r = self._conn.execute("SELECT value FROM %s WHERE key=?" % table, (key,)).fetchone()
        return r["value"] if r else None

    def read_config(self):
        """-> сырой раздел настроек С секретами (для диспетчера) или None, если пусто."""
        with self._lock:
            raw = self._get("msg_settings", "config")
            try:
                cfg = json.loads(raw) if raw else None
            except Exception:
                cfg = None
            if not isinstance(cfg, dict):
                cfg = {}
            chans = cfg.get("channels") if isinstance(cfg.get("channels"), dict) else {}
            cfg["channels"] = chans
            for kind, keys in self._secret_keys.items():
                ch = chans.get(kind) if isinstance(chans.get(kind), dict) else {}
                for k in keys:
                    v = self._get("msg_secrets", "%s.%s" % (kind, k))
                    if v:
                        ch[k] = v
                if ch:
                    chans[kind] = ch
            return cfg

    def write_config(self, cfg):
        """Раздел С секретами -> секреты в msg_secrets, остальное в msg_settings. -> True."""
        cfg = dict(cfg or {})
        chans = dict(cfg.get("channels") or {})
        public_chans = {}
        secrets = []
        for kind, ch in chans.items():
            ch = dict(ch or {})
            for k in self._secret_keys.get(kind, ()):
                secrets.append(("%s.%s" % (kind, k), str(ch.pop(k, "") or "")))
            public_chans[kind] = ch
        cfg["channels"] = public_chans
        with self._lock:
            #  16.10.2026 (R-151): UPSERT вместо REPLACE — REPLACE удаляет строку целиком и вставляет
            #  заново, а такие строки должны только обновляться.
            self._conn.execute("INSERT INTO msg_settings (key, value) VALUES (?, ?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                               ("config", json.dumps(cfg, ensure_ascii=False, sort_keys=True)))
            for key, val in secrets:
                if val:
                    self._conn.execute("INSERT INTO msg_secrets (key, value) VALUES (?, ?) "
                                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, val))
                else:
                    self._conn.execute("DELETE FROM msg_secrets WHERE key=?", (key,))
            self._conn.commit()
        return True

    def public_raw(self):
        """Содержимое msg_settings как есть (для проверок: секретов здесь быть не должно)."""
        with self._lock:
            return {r["key"]: r["value"] for r in self._conn.execute("SELECT key, value FROM msg_settings")}

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
