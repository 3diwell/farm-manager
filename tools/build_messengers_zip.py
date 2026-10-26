# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Сборка установочного zip модуля «Уведомления в мессенджеры» (messengers).
# Пакует ТОЛЬКО нужные файлы модуля (белый список) с верхней папкой messengers/:
#   messengers/module.json, messengers/backend.py, messengers/fm_messengers/*.py,
#   messengers/web/*.js
# Никогда не включает: __pycache__/*.pyc, бэкапы/temp, файлы БД (*.db/-wal/-shm),
# пользовательские данные. После сборки zip проверяется изнутри.
# Запуск: python tools/build_messengers_zip.py [путь_к_zip]
import json
import os
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "modules", "messengers")
#  ЕДИНЫЙ ДОМ СОБРАННЫХ МОДУЛЕЙ (решение владельца 11.09.2026): папка modules проекта —
#  та же, где лежат исходники модулей. Никаких «Загрузок»: владелец ставит модуль через
#  Настройки -> Модули -> Установить и ищет .zip там, где лежит проект.
MODULES_DIR = os.path.join(REPO, "modules")
DEFAULT_OUT = os.path.join(MODULES_DIR, "3diwell-module-messengers.zip")

FORBIDDEN = (".db", ".db-wal", ".db-shm", ".pyc", ".pyo", ".bak", ".old", ".tmp", ".log", ".zip")
FORBIDDEN_DIRS = ("__pycache__", "new folder", "backup", "temp", "tmp")


def collect():
    """Белый список файлов модуля: manifest, backend, библиотека площадок, web-скрипты."""
    files = []
    for name in ("module.json", "backend.py"):
        p = os.path.join(SRC, name)
        if not os.path.isfile(p):
            raise SystemExit("FATAL: missing " + name)
        files.append((p, "messengers/" + name))
    for sub, exts in (("fm_messengers", (".py",)), ("web", (".js",))):
        d = os.path.join(SRC, sub)
        if not os.path.isdir(d):
            raise SystemExit("FATAL: missing folder " + sub)
        for root, dirs, names in os.walk(d):
            dirs[:] = [x for x in dirs if x.lower() not in FORBIDDEN_DIRS]
            for n in sorted(names):
                low = n.lower()
                if low.endswith(FORBIDDEN) or low.startswith("~") or not low.endswith(exts):
                    continue
                full = os.path.join(root, n)
                rel = "messengers/%s/%s" % (sub, os.path.relpath(full, d).replace(os.sep, "/"))
                files.append((full, rel))
    return files


def build(out=DEFAULT_OUT):
    files = collect()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in files:
            z.write(full, rel)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        mj = json.loads(z.read("messengers/module.json"))
        #  2.1007: запретные ПАПКИ проверяются по сегментам пути, а не подстрокой — иначе файл
        #  templates.py считался бы мусором из-за «temp» внутри имени.
        junk = [n for n in names
                if n.lower().endswith(FORBIDDEN)
                or any(seg.lower() in FORBIDDEN_DIRS for seg in n.split("/")[:-1])]
        assert "messengers/backend.py" in names, "backend.py missing in zip"
        assert "messengers/fm_messengers/__init__.py" in names, "library missing in zip"
        assert "messengers/web/MessengersPanel.js" in names, "panel missing in zip"
        assert not junk, "junk in zip: %r" % junk
        assert mj.get("id") == "messengers", "bad module id"
    return out, names, mj


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    out, names, mj = build(out)
    print("OK: %d files, id=%s v%s" % (len(names), mj.get("id"), mj.get("version")))
    for n in names:
        print("   ", n)
    print("ZIP:", out)


if __name__ == "__main__":
    main()
