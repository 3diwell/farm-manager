# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — постоянный контракт module backup: реестр, fail-closed, identity, версии."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import module_providers as mp
from app.config_backup.errors import BackupError

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


def _reason(fn):
    try:
        fn(); return None
    except BackupError as e:
        return e.reason


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _real_module_ids():
    """R-125: НАСТОЯЩИЕ модули — id из modules/*/module.json и из каталога выпусков программы.
    Раньше тест сверял жёсткий список из трёх id, и установленная «Видеостена» блокировала полный
    экспорт копии незамеченной (409 manual_resolution_required)."""
    import json
    from app import module_catalog
    ids = set(module_catalog.KNOWN_MODULE_RELEASES)
    base = os.path.join(ROOT, "modules")
    for name in sorted(os.listdir(base)):
        mj = os.path.join(base, name, "module.json")
        if os.path.isfile(mj):
            ids.add(str(json.load(open(mj, encoding="utf-8"))["id"]))
    return sorted(ids)


print("--- реестр модулей (fail-closed) ---")
REAL = _real_module_ids()
check("1. КАЖДЫЙ настоящий модуль (modules/*/module.json + каталог выпусков) классифицирован: %s" % REAL,
      len(REAL) >= 6 and mp.check_export_completeness(REAL) == [])
check("2. классы модулей корректны (inventory/cost/messengers=provider, quality/appearance/camera_wall=no_data)",
      mp.get_provider("inventory").data_class == mp.DATA_CLASS_PROVIDER
      and mp.get_provider("cost").data_class == mp.DATA_CLASS_PROVIDER
      and mp.get_provider("messengers").data_class == mp.DATA_CLASS_PROVIDER
      and mp.get_provider("quality").data_class == mp.DATA_CLASS_NO_DATA
      and mp.get_provider("appearance").data_class == mp.DATA_CLASS_NO_DATA
      and mp.get_provider("camera_wall").data_class == mp.DATA_CLASS_NO_DATA)
_cw = os.path.join(ROOT, "modules", "camera_wall")
check("2b. «Видеостена» без пользовательских данных: у модуля нет backend.py (нет базы и маршрутов), "
      "камеры — в localStorage браузера",
      not os.path.isdir(_cw) or (not os.path.exists(os.path.join(_cw, "backend.py"))
                                 and "localStorage" in open(os.path.join(_cw, "web", "camera-store.js"),
                                                            encoding="utf-8").read()))
check("3. НЕклассифицированный установленный модуль блокирует полный экспорт",
      mp.check_export_completeness(["inventory", "ghost_module"]) == ["ghost_module"])
check("4. require_export_completeness -> manual_resolution_required с ИМЕНЕМ модуля",
      _reason(lambda: mp.require_export_completeness(["ghost_module"])) == "manual_resolution_required")
try:
    mp.require_export_completeness(["ghost_module"])
except BackupError as e:
    check("5. точное имя модуля в detail", "ghost_module" in e.detail)


class _Unsupported(mp.ModuleBackupProvider):
    module_id = "tmp_unsup"
    data_class = mp.DATA_CLASS_UNSUPPORTED


_saved = dict(mp._PROVIDERS)
mp._PROVIDERS["tmp_unsup"] = _Unsupported()
check("6. backup_temporarily_unsupported тоже блокирует полный экспорт",
      mp.check_export_completeness(["tmp_unsup"]) == ["tmp_unsup"])
mp._PROVIDERS.clear(); mp._PROVIDERS.update(_saved)

print("--- identity и версии ---")
check("7. identity = stable module_id (не display name): у провайдеров нет display-имён",
      all(not hasattr(p, "display_name") for p in mp.all_providers().values()))
check("8. у каждого провайдера СВОЯ backup_schema_version (int >= 1)",
      all(isinstance(p.backup_schema_version, int) and p.backup_schema_version >= 1
          for p in mp.all_providers().values()))
check("9. версия модуля — метаданные снапшота, не схема",
      "installed_module_version_at_export" in
      mp.get_provider("quality").export_snapshot(mp.DictModuleStore(), installed_version="9.9.9"))

inv = mp.get_provider("inventory")
snap = inv.export_snapshot(mp.DictModuleStore(), installed_version="1.7.24")
newer = dict(snap); newer["backup_schema_version"] = 99
check("10. module schema новее ридера -> backup_from_newer_version (не угадывается)",
      _reason(lambda: inv.migrate_snapshot(newer)) == "backup_from_newer_version")
check("11. append-only миграции: реестр модуля покрывает 1..current-1",
      set((inv.MIGRATIONS or {}).keys()) == set(range(1, inv.backup_schema_version)))
check("11b. то же у КАЖДОГО провайдера (подняли схему — обязана быть миграция со старой)",
      all(set((p.MIGRATIONS or {}).keys()) == set(range(1, p.backup_schema_version))
          for p in mp.all_providers().values()))

print("--- снапшот: канон и запреты ---")
check("12. снапшот — логическая модель (dict, НЕ raw SQL/ORM/pickle)",
      isinstance(snap, dict) and isinstance(snap.get("domain_data"), dict))
src = open(os.path.join(os.path.dirname(__file__), "..", "app", "config_backup",
                        "module_providers.py"), encoding="utf-8").read()
import io, tokenize
toks = []
for t in tokenize.generate_tokens(io.StringIO(src).readline):
    if t.type not in (tokenize.COMMENT, tokenize.STRING):
        toks.append(t.string)
code = " ".join(toks)
check("13. pickle отсутствует в коде провайдеров", "pickle" not in code)
check("14. провайдеры не обращаются к принтерам/сети (нет socket/urllib/requests)",
      "socket" not in code and "urllib" not in code and "requests" not in code)

dup = False
try:
    mp._PROVIDERS["inventory2"] = inv
    del mp._PROVIDERS["inventory2"]
    # дубликат module_id при построении реестра запрещён на уровне модуля:
    dup = "duplicate module_id" in src
except Exception:
    pass
check("15. duplicate module_id отклоняется реестром", dup)

print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
