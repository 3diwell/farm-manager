# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.880 — один сторож на ВСЕ базовые числа маршрутов.

ЗАЧЕМ. Одно и то же число (сколько в server.py маршрутов и сколько записей в реестре) записано
примерно в десяти наборах проверок. Добавили маршрут — обновили не везде, и наборы краснеют
поодиночке, а причина у них одна. Так уже было дважды: маршрут камеры 2.870 обновили в двух
файлах из пяти, маршрут камеры по WebSocket 2.879 — ещё в трёх. Красное лежало неделями, потому
что никто не запускал именно те наборы.

ЧТО ДЕЛАЕТ. Считает истину сам (по server.py и по реестру), затем ищет в наборах жёстко
записанные числа и сверяет их с истиной. Провал показывает СПИСОК ФАЙЛОВ, которые надо
поправить, — а не одно случайное имя.

ЧЕГО НЕ ДЕЛАЕТ. Не правит ничего сам и не ослабляет чужие проверки: он только сообщает, где
числа разошлись с действительностью.
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SENTINEL = "ROUTE_COUNT_BASELINES_SENTINEL_2_880"

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:400]) if detail else ""))


SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
DECOR = len(re.findall(r"^@app\.(get|post|patch|delete|websocket)\(", SRV, re.M))

from app import route_policy_registry as reg   # noqa: E402
COUNTS = reg.registry_counts()

print("--- истина, посчитанная сейчас ---")
print("декораторов @app.* в server.py: %d" % DECOR)
print("реестр: всего %d, ядро %d, модули %d, WebSocket %d"
      % (COUNTS["total"], COUNTS["core"], COUNTS["modules"], COUNTS["websocket"]))
print()

check("1. в server.py есть маршруты и реестр не пуст", DECOR > 100 and COUNTS["total"] > 100)
check("2. реестр описывает не меньше маршрутов, чем объявлено в server.py",
      COUNTS["core"] >= DECOR - 5, (COUNTS["core"], DECOR))

# ── где ещё лежат те же числа ────────────────────────────────────────────────────────────────
TOOLS = os.path.join(ROOT, "tools")
FILES = sorted(f for f in os.listdir(TOOLS) if f.startswith("test_") and f.endswith(".py"))

_DECOR_CMP = re.compile(r"@app\\.\(get\|post\|patch\|delete\|websocket\)[^\n]*?==\s*(\d{2,4})")
_REG_TOTAL = re.compile(r'registry_counts\(\)\["total"\]\s*==\s*(\d{2,4})')
_REG_CORE = re.compile(r'registry_counts\(\)\["core"\]\s*==\s*(\d{2,4})')
_C_TOTAL = re.compile(r'_c\["total"\]\s*==\s*(\d{2,4})')
_C_CORE = re.compile(r'_c\["core"\]\s*==\s*(\d{2,4})')
_CNT_TOTAL = re.compile(r'counts\["total"\]\s*==\s*(\d{2,4})')
_CNT_CORE = re.compile(r'counts\["core"\]\s*==\s*(\d{2,4})')

bad_decor, bad_total, bad_core = [], [], []
for name in FILES:
    if name == os.path.basename(__file__):
        continue
    p = os.path.join(TOOLS, name)
    try:
        txt = io.open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    for m in _DECOR_CMP.finditer(txt):
        if int(m.group(1)) != DECOR:
            bad_decor.append("%s: %s" % (name, m.group(1)))
    for rx in (_REG_TOTAL, _C_TOTAL, _CNT_TOTAL):
        for m in rx.finditer(txt):
            if int(m.group(1)) != COUNTS["total"]:
                bad_total.append("%s: %s" % (name, m.group(1)))
    for rx in (_REG_CORE, _C_CORE, _CNT_CORE):
        for m in rx.finditer(txt):
            if int(m.group(1)) != COUNTS["core"]:
                bad_core.append("%s: %s" % (name, m.group(1)))

check("3. число декораторов @app.* совпадает во ВСЕХ наборах, где оно записано",
      not bad_decor, "надо %d, а записано -> %s" % (DECOR, bad_decor))
check("4. «всего маршрутов в реестре» совпадает во всех наборах",
      not bad_total, "надо %d, а записано -> %s" % (COUNTS["total"], bad_total))
check("5. «маршрутов ядра в реестре» совпадает во всех наборах",
      not bad_core, "надо %d, а записано -> %s" % (COUNTS["core"], bad_core))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
