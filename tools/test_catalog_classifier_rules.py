# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.884 — правило классификатора про адреса: доказательство поведением.

ЗАЧЕМ. Классификатор решает, можно ли запускать набор проверок автоматически. Он считал
«работой с живым принтером» ЛЮБОЙ адрес вида 10.0.0.9 в тексте — даже выдуманные данные. Из-за
этого 40 наборов не запускались никогда, и у 14 адрес был единственной помехой (среди них все
проверки резервного копирования).

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ. Адрес опасен ровно тогда, когда набору ЕСТЬ ЧЕМ по нему пойти: сокет,
http-клиент, собственный сервер, оболочка, подпроцесс, импорт server.py. Проверяется настоящим
классификатором на синтетических исходниках — и в обе стороны: где выйти в сеть нечем, помехи
нет; где есть — помеха остаётся. Ослабление правила поймается сразу: проверки 3-6 краснеют.

БЕЗОПАСНОСТЬ. Только чтение и разбор текста. Ни сети, ни принтеров, ни БД, ни подпроцессов.

Запуск:  python tools/test_catalog_classifier_rules.py
"""
import importlib.util
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = "CATALOG_CLASSIFIER_RULES_SENTINEL_2_884"

_spec = importlib.util.spec_from_file_location(
    "btc", os.path.join(REPO, "tools", "validation", "build_test_catalog.py"))
btc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(btc)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def caps(src):
    sc, _ = btc.classify_python(src)
    return sc.caps, sc.reasons


IP_ONLY = 'PRINTER = "10.0.0.9"\nDATA = {"ip": PRINTER}\n'
IP_SOCKET = 'import socket\nPRINTER = "10.0.0.9"\n'
IP_URLLIB = 'import urllib.request\nPRINTER = "10.0.0.9"\n'
IP_SUBPROC = 'import subprocess\nPRINTER = "10.0.0.9"\nsubprocess.run(["x"])\n'
LOOPBACK = 'import socket\nHOST = "127.0.0.1"\n'

print("--- 1. Адрес в данных без способа выйти в сеть ---")
c, r = caps(IP_ONLY)
check("1. адрес сам по себе больше не закрывает автозапуск", not c.get("real_printer"), c)
check("2. причина всё равно записана — молча ничего не решается",
      any("адрес в данных" in x for x in r), r)

print("--- 2. Тот же адрес, но выйти в сеть есть чем ---")
check("3. адрес + сокет = работа с принтером", caps(IP_SOCKET)[0].get("real_printer"))
check("4. адрес + http-клиент = работа с принтером", caps(IP_URLLIB)[0].get("real_printer"))
check("5. адрес + подпроцесс = работа с принтером", caps(IP_SUBPROC)[0].get("real_printer"))

print("--- 3. Свои адреса и версия правил ---")
check("6. петлевой адрес принтером не считается никогда",
      not caps(LOOPBACK)[0].get("real_printer"))
check("7. версия правил поднята вместе с правилом (иначе старый каталог выглядел бы свежим)",
      btc.CLASSIFIER == "2b.4", btc.CLASSIFIER)

print("--- 4. Каталог в репозитории соответствует правилам ---")
#  Свежесть проверяется В ЭТОМ ЖЕ процессе, а НЕ запуском подпроцесса: набор с подпроцессом
#  классификатор справедливо считает способным выйти в сеть, и тогда он сам себе закрыл бы
#  автозапуск — из-за адресов, которые стоят здесь как данные проверки.
_diffs, _fresh = btc.freshness()
check("8. tools/validation/test_catalog.json не устарел", not _diffs,
      "; ".join(str(d) for d in (_diffs or [])[:3]))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
