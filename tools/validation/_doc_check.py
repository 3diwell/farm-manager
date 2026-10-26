# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Структурная проверка markdown-файла: ссылки ведут в существующие файлы.

Проверяет только относительные ссылки внутри репозитория. Внешние адреса (http, mailto)
и якоря не трогает — проверить их без сети нельзя, а сеть здесь запрещена.

Только чтение. Ничего не пишет, подпроцессов не создаёт, в сеть не ходит.
Вызывается исполнителем профиля как команда `fast.doc_check`.

    python tools/validation/_doc_check.py <файл.md>        (0 = ссылки целы)
"""
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LINK = re.compile(r"\]\(([^)\s]+)\)")


def main(argv):
    if len(argv) != 1:
        print("FAIL — ожидается ровно один путь к .md")
        return 2
    path = argv[0]
    if not os.path.isfile(path):
        print("FAIL — файл не найден: %s" % path)
        print("ИТОГО: PASS=0 FAIL=1")
        return 1
    src = io.open(path, encoding="utf-8", errors="replace").read()
    base = os.path.dirname(os.path.abspath(path))
    ok, bad = 0, []
    for m in LINK.finditer(src):
        target = m.group(1).split("#")[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if os.path.exists(os.path.normpath(os.path.join(base, target))):
            ok += 1
        else:
            bad.append(target)
    for b in bad:
        print("FAIL — ссылка ведёт в никуда: %s" % b)
    if not bad:
        print("PASS — %s: относительных ссылок %d, все ведут в существующие файлы"
              % (path, ok))
    print("ИТОГО: PASS=%d FAIL=%d" % (ok if not bad else 0, len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
