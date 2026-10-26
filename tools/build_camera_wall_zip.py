# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Сборка установочного zip модуля «Видеостена» (camera_wall).
# Пакует ТОЛЬКО нужные файлы модуля (белый список) с верхней папкой camera_wall/:
#   camera_wall/module.json, camera_wall/web/*.js  (серверной части у модуля нет)
# Никогда не включает: __pycache__/*.pyc, бэкапы/temp, файлы БД (*.db/-wal/-shm),
# пользовательские данные. После сборки zip проверяется изнутри.
# Запуск: python tools/build_camera_wall_zip.py
import json
import os
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-консоль cp1252
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "modules", "camera_wall")
#  ЕДИНЫЙ ДОМ СОБРАННЫХ МОДУЛЕЙ (решение владельца 11.09.2026): C:DIWELL\modules —
#  та же папка, где лежат исходники модулей. Никаких «Загрузок»: владелец ставит модуль
#  через Настройки → Модули → Установить и ищет .zip там, где лежит проект.
MODULES_DIR = os.path.join(REPO, "modules")
OUT = os.path.join(MODULES_DIR, "3diwell-module-camera-wall.zip")

FORBIDDEN = (".db", ".db-wal", ".db-shm", ".pyc", ".pyo", ".bak", ".old", ".tmp", ".log", ".zip")
FORBIDDEN_DIRS = ("__pycache__", "new folder", "backup", "temp", "tmp")

# Alpha 2.872: пакуем ВСЁ, что ядро умеет отдавать модулю (см. _serve_module_asset
# в server.py). Прежде здесь стояло «только .js» — наследство сборщика модуля
# «Качество», у которого стилей нет вовсе, — и camera-wall.css молча терялся.
ALLOWED = (".js", ".css", ".json", ".svg", ".png", ".jpg", ".jpeg",
           ".woff2", ".woff", ".ttf", ".otf")


def collect():
    """Белый список файлов модуля: manifest и web-скрипты."""
    files = []
    # У видеостены серверной части нет вовсе: она работает через маршруты ядра.
    for name in ("module.json",):
        p = os.path.join(SRC, name)
        if not os.path.isfile(p):
            raise SystemExit("FATAL: missing " + name)
        files.append((p, "camera_wall/" + name))
    webdir = os.path.join(SRC, "web")
    if os.path.isdir(webdir):
        for root, dirs, names in os.walk(webdir):
            dirs[:] = [d for d in dirs if d.lower() not in FORBIDDEN_DIRS]
            for n in sorted(names):
                low = n.lower()
                if low.endswith(FORBIDDEN) or low.startswith("~"):
                    continue
                if not low.endswith(ALLOWED):
                    continue
                full = os.path.join(root, n)
                rel = "camera_wall/web/" + os.path.relpath(full, webdir).replace(os.sep, "/")
                files.append((full, rel))
    return files


def main():
    files = collect()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in files:
            z.write(full, rel)
    # ── сторож полноты: тихо потерянный файл ломает модуль у пользователя ──
    packed = set(rel for _f, rel in files)
    missing = []
    webdir = os.path.join(SRC, "web")
    for root, dirs, names in os.walk(webdir):
        dirs[:] = [d for d in dirs if d.lower() not in FORBIDDEN_DIRS]
        for n in sorted(names):
            low = n.lower()
            if low.endswith(FORBIDDEN) or low.startswith("~"):
                continue
            rel = "camera_wall/web/" + os.path.relpath(os.path.join(root, n), webdir).replace(os.sep, "/")
            if rel not in packed:
                missing.append(rel)
    if missing:
        raise SystemExit("FATAL: файлы модуля не попали в архив: " + ", ".join(missing))

    # ── проверка изнутри ──
    with zipfile.ZipFile(OUT) as z:
        names = z.namelist()
        mj = json.loads(z.read("camera_wall/module.json"))
        junk = [n for n in names
                if n.lower().endswith(FORBIDDEN) or any(d in n.lower() for d in FORBIDDEN_DIRS)]
        assert not junk, "junk in zip: %r" % junk
        assert mj.get("id") == "camera_wall", "bad module id"
        print("OK: %d files, id=%s v%s" % (len(names), mj.get("id"), mj.get("version")))
        for n in names:
            print("   ", n)
    print("ZIP:", OUT)


if __name__ == "__main__":
    main()
