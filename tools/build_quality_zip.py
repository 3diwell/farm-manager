# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Сборка установочного zip модуля «Аналитика качества» (quality).
# Пакует ТОЛЬКО нужные файлы модуля (белый список) с верхней папкой quality/:
#   quality/module.json, quality/backend.py, quality/web/*.js
# Никогда не включает: __pycache__/*.pyc, бэкапы/temp, файлы БД (*.db/-wal/-shm),
# пользовательские данные. После сборки zip проверяется изнутри.
# Запуск: python tools/build_quality_zip.py
import json
import os
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-консоль cp1252
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "modules", "quality")
#  ЕДИНЫЙ ДОМ СОБРАННЫХ МОДУЛЕЙ (решение владельца 11.09.2026): папка modules проекта —
#  та же, где лежат исходники модулей. Никаких «Загрузок»: владелец ставит модуль через
#  Настройки -> Модули -> Установить и ищет .zip там, где лежит проект.
MODULES_DIR = os.path.join(REPO, "modules")
OUT = os.path.join(MODULES_DIR, "3diwell-module-quality.zip")

FORBIDDEN = (".db", ".db-wal", ".db-shm", ".pyc", ".pyo", ".bak", ".old", ".tmp", ".log", ".zip")
FORBIDDEN_DIRS = ("__pycache__", "new folder", "backup", "temp", "tmp")


def collect():
    """Белый список файлов модуля: manifest, backend, web-скрипты."""
    files = []
    for name in ("module.json", "backend.py"):
        p = os.path.join(SRC, name)
        if not os.path.isfile(p):
            raise SystemExit("FATAL: missing " + name)
        files.append((p, "quality/" + name))
    webdir = os.path.join(SRC, "web")
    if os.path.isdir(webdir):
        for root, dirs, names in os.walk(webdir):
            dirs[:] = [d for d in dirs if d.lower() not in FORBIDDEN_DIRS]
            for n in sorted(names):
                low = n.lower()
                if low.endswith(FORBIDDEN) or low.startswith("~"):
                    continue
                if not low.endswith(".js"):
                    continue   # в web модуля качества пакуем только скрипты
                full = os.path.join(root, n)
                rel = "quality/web/" + os.path.relpath(full, webdir).replace(os.sep, "/")
                files.append((full, rel))
    return files


def main():
    files = collect()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in files:
            z.write(full, rel)
    # ── проверка изнутри ──
    with zipfile.ZipFile(OUT) as z:
        names = z.namelist()
        mj = json.loads(z.read("quality/module.json"))
        junk = [n for n in names
                if n.lower().endswith(FORBIDDEN) or any(d in n.lower() for d in FORBIDDEN_DIRS)]
        assert "quality/backend.py" in names, "backend.py missing in zip"
        assert not junk, "junk in zip: %r" % junk
        assert mj.get("id") == "quality", "bad module id"
        print("OK: %d files, id=%s v%s" % (len(names), mj.get("id"), mj.get("version")))
        for n in names:
            print("   ", n)
    print("ZIP:", OUT)


if __name__ == "__main__":
    main()
