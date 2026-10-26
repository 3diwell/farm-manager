# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — провайдер Quality: доказанная классификация no_persistent_user_data.

Forensic: все 4 HTTP-маршрута модуля — GET-only (0 write-маршрутов); все колонки
print_runs/print_run_materials/print_run_event_aliases захватываются автоматически из событий
печати. Это журнал ИСТОРИИ ПЕЧАТИ, который пользовательский контракт запрещает менять при
restore. Пользовательских данных нет; attachments нет -> контейнер v3 НЕ требуется (решение A).
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import module_providers as mp

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


Q = mp.get_provider("quality")
check("31. классификация: no_persistent_user_data (доказано forensic-ом)",
      Q.data_class == mp.DATA_CLASS_NO_DATA)

# Доказательство по коду модуля: 0 write-маршрутов (все GET).
src = open(os.path.join(os.path.dirname(__file__), "..", "modules", "quality", "backend.py"),
           encoding="utf-8").read()
routes = re.findall(r'core\.add_route\([^)]*\[([^\]]*)\]', src)
check("доказательство: ВСЕ HTTP-маршруты quality — GET-only",
      routes and all(("POST" not in r and "PATCH" not in r and "DELETE" not in r) for r in routes))

snap = Q.export_snapshot(mp.DictModuleStore(), installed_version="0.2.2")
check("снапшот — маркер классификации: domain_data=None, settings={}",
      snap["domain_data"] is None and snap["settings"] == {})
check("32. relations: журнал ссылается на печать/принтеры и НЕ переносится (не в снапшоте)",
      "print_runs" not in str(snap))
check("33. attachments contract: манифест пуст (бинарных вложений нет -> v3 не нужен)",
      snap["attachments_manifest"] == [])

# restore ничего не трогает
store = mp.DictModuleStore(tables={"print_runs": [{"run_id": "KEEP"}]})
before = store.full_snapshot()
Q.apply_restore(store, snap)
check("34. restore quality — no-op: журнал печати не изменён (round trip тождествен)",
      store.full_snapshot() == before and Q.verify_restore(store, snap))
plan = Q.build_restore_plan(store, snap)
check("план quality пуст (нет счётчиков изменений)", plan["counts"]["added"] == 0
      and plan["counts"]["updated"] == 0)

print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
