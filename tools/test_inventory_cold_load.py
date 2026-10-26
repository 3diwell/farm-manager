# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Regression-тест «холодной» загрузки склада (Alpha 2.713).
# Доказывает, что backend-логика чтения (inv_filament_data) отдаёт ВСЕ существующие
# катушки СРАЗУ, из свежего подключения, БЕЗ каких-либо мутаций (POST/INSERT).
#
# БЕЗОПАСНОСТЬ: БД открывается СТРОГО read-only (mode=ro, uri) — тест физически не может
# изменить данные. DATA_DIR не трогается. Тест только СЧИТАЕТ и СРАВНИВАЕТ.
#
# Запуск:  python tools/test_inventory_cold_load.py
#          python tools/test_inventory_cold_load.py "C:\\path\\to\\farm_inventory.db"
# Код возврата 0 — тест пройден, 1 — расхождение (баг холодной загрузки).
import importlib.util
import os
import sqlite3
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(REPO, "modules", "inventory", "backend.py")


def _default_db():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "3DIWELL", "farm_inventory.db")


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else _default_db()
    if not os.path.isfile(db):
        print("SKIP: inventory DB not found:", db)
        return 0

    # 1) Ground truth — прямой read-only SELECT (уважает WAL).
    truth = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    truth.row_factory = sqlite3.Row
    n_spools = truth.execute("SELECT COUNT(*) FROM inv_spools WHERE is_deleted=0").fetchone()[0]
    n_fil = truth.execute("SELECT COUNT(*) FROM inv_filaments WHERE is_deleted=0").fetchone()[0]
    n_vnd = truth.execute("SELECT COUNT(*) FROM inv_vendors WHERE is_deleted=0").fetchone()[0]
    truth.close()

    # 2) «Холодный» backend: импортируем модуль, подсовываем СВЕЖЕЕ read-only подключение
    #    (как при старте программы) и зовём ту же функцию чтения, что и endpoint /filament.
    spec = importlib.util.spec_from_file_location("inv_backend_coldtest", BACKEND)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.conn_inv = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    m.conn_inv.row_factory = sqlite3.Row
    if getattr(m, "lock_inv", None) is None:
        m.lock_inv = threading.RLock()

    data = m.inv_filament_data()
    got_spools = len(data.get("spools", []))
    got_fil = len(data.get("filaments", []))
    got_vnd = len(data.get("vendors", []))
    m.conn_inv.close()

    print("DB (ground truth): spools=%d filaments=%d vendors=%d" % (n_spools, n_fil, n_vnd))
    print("Cold backend read: spools=%d filaments=%d vendors=%d" % (got_spools, got_fil, got_vnd))

    ok = (got_spools == n_spools and got_fil == n_fil and got_vnd == n_vnd)
    if ok:
        print("PASS: cold backend read returns the full existing base with NO mutation.")
        return 0
    print("FAIL: cold read does not match the DB -> backend/init/DB-path bug.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
