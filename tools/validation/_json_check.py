# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Проверка JSON-файла: разбирается ли он и является ли объектом или массивом.

Только чтение. Ничего не пишет, подпроцессов не создаёт, в сеть не ходит.
Вызывается исполнителем профиля как команда `fast.json_check`.

    python tools/validation/_json_check.py <файл.json>     (0 = разобран)
"""
import io
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(argv):
    if len(argv) != 1:
        print("FAIL — ожидается ровно один путь к .json")
        return 2
    path = argv[0]
    try:
        data = json.load(io.open(path, encoding="utf-8"))
    except Exception as e:
        print("FAIL — %s не разобран как JSON: %s" % (path, e))
        print("ИТОГО: PASS=0 FAIL=1")
        return 1
    kind = type(data).__name__
    if not isinstance(data, (dict, list)):
        print("FAIL — %s: верхний уровень %s, ожидается объект или массив" % (path, kind))
        print("ИТОГО: PASS=0 FAIL=1")
        return 1
    size = len(data)
    print("PASS — %s: корректный JSON (%s, элементов: %d)" % (path, kind, size))
    print("ИТОГО: PASS=1 FAIL=0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
