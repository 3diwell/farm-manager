# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Сборка установочного zip модуля «Оформление и темы» (appearance).
#
# Модуль — только интерфейс: манифест и ES-модули в web/. Бэкенда и маршрутов у него нет,
# поэтому в карте прав ядра он не значится и ядро его версию не сверяет.
#
# Пакует ТОЛЬКО то, что исполняется у пользователя (белый список), с верхней папкой appearance/:
#   appearance/module.json, appearance/web/**/*.js (+ css/svg/png/шрифты, если появятся)
# НЕ пакует документы автора модуля, лежащие рядом в исходниках: README_RU.md,
# IPHONE_THEME_NOTES_RU.md, QA_*.json — это описание и отчёты разработки. Решение владельца
# 12.09.2026: в выпуске для пользователя нет ничего, что относится к проектированию.
#
# После сборки zip проверяется изнутри: манифест, точка входа, КАЖДЫЙ относительный импорт
# каждого скрипта разрешается в файл внутри архива (иначе модуль упадёт у пользователя на
# загрузке), лишнего нет.
# Запуск: python tools/build_appearance_zip.py
import json
import os
import posixpath
import re
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-консоль cp1252
except Exception:
    pass

MID = "appearance"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "modules", MID)
#  ЕДИНЫЙ ДОМ СОБРАННЫХ МОДУЛЕЙ (решение владельца 11.09.2026): C:\3DIWELL\modules.
MODULES_DIR = os.path.join(REPO, "modules")
OUT = os.path.join(MODULES_DIR, "3diwell-module-appearance.zip")

WEB_EXT = (".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".woff", ".woff2", ".ttf", ".otf")
FORBIDDEN_DIRS = ("__pycache__", "new folder", "backup", "temp", "tmp")
IMPORT_RX = re.compile(r"""(?:^|[\s;])import\s[^'"]*?from\s+['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)""", re.M)


def collect():
    """Белый список: манифест и файлы web/ с расширениями интерфейса."""
    files = []
    manifest = os.path.join(SRC, "module.json")
    if not os.path.isfile(manifest):
        raise SystemExit("FATAL: missing module.json")
    files.append((manifest, MID + "/module.json"))
    webdir = os.path.join(SRC, "web")
    if not os.path.isdir(webdir):
        raise SystemExit("FATAL: missing web/")
    for root, dirs, names in os.walk(webdir):
        dirs[:] = sorted(d for d in dirs if d.lower() not in FORBIDDEN_DIRS)
        for n in sorted(names):
            low = n.lower()
            if low.startswith("~") or not low.endswith(WEB_EXT):
                continue
            full = os.path.join(root, n)
            rel = MID + "/web/" + os.path.relpath(full, webdir).replace(os.sep, "/")
            files.append((full, rel))
    return files


def verify(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        mj = json.loads(z.read(MID + "/module.json").decode("utf-8"))
        assert mj.get("id") == MID, "bad module id: %r" % mj.get("id")
        assert mj.get("version"), "module.json without version"
        entry = str(mj.get("entry") or "")
        assert entry.startswith("web/") and (MID + "/" + entry) in names, "entry %r missing in zip" % entry
        extra = [n for n in names if n != MID + "/module.json" and not n.startswith(MID + "/web/")]
        assert not extra, "лишнее в архиве: %r" % extra
        docs = [n for n in names if n.lower().endswith((".md", ".txt")) or (n.lower().endswith(".json") and n != MID + "/module.json")]
        assert not docs, "документы разработки в архиве: %r" % docs
        junk = [n for n in names if any(seg.lower() in FORBIDDEN_DIRS for seg in n.split("/")[:-1])]
        assert not junk, "мусор в архиве: %r" % junk
        missing = []
        for n in names:
            if not n.endswith(".js"):
                continue
            src = z.read(n).decode("utf-8", "replace")
            for m in IMPORT_RX.finditer(src):
                spec = m.group(1) or m.group(2)
                if not spec.startswith("."):
                    continue                      # 'vue' и т. п. — из importmap ядра
                target = posixpath.normpath(posixpath.join(posixpath.dirname(n), spec))
                if target not in names:
                    missing.append("%s -> %s" % (n, spec))
        assert not missing, "импорты без файла: %r" % missing[:5]
        return mj, names


def main():
    files = collect()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for full, rel in files:
            z.write(full, rel)
    mj, names = verify(OUT)
    print("OK: %d files, id=%s v%s, entry=%s" % (len(names), mj.get("id"), mj.get("version"), mj.get("entry")))
    for n in names:
        print("   ", n)
    print("ZIP:", OUT)


if __name__ == "__main__":
    main()
