# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — ВЕЧНАЯ совместимость: замороженная v1-фикстура обязана восстанавливаться всегда.

Этот тест — «страховой полис» контракта. Он загружает ЗАМОРОЖЕННЫЙ файл sample.3diwell-backup
(снятый один раз в Alpha 2.827) и требует, чтобы ЛЮБАЯ будущая версия кода:
  • читала его байты,
  • расшифровывала известным паролем,
  • мигрировала к текущей схеме,
  • восстанавливала принтеры (с идентичностью и секретами) и настройки.
Если этот тест покраснел — сломан контракт обратной совместимости: старые копии пользователей
перестанут восстанавливаться. Чинить нужно КОД (добавив миграцию), а НЕ фикстуру.

ФИКСТУРУ НЕЛЬЗЯ ПЕРЕГЕНЕРИРОВАТЬ И МЕНЯТЬ НИКОГДА (проверяется по SHA-256).
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, validator, migrations, restore_plan, restore_engine, recovery
from app.config_backup.repository import DictGateway

FIX_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "config_backup", "v1")
BLOB_PATH = os.path.join(FIX_DIR, "sample.3diwell-backup")
META_PATH = os.path.join(FIX_DIR, "sample.meta.json")

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


def main():
    print("--- вечная совместимость: замороженная v1-фикстура ---")
    check("0. фикстура и её манифест присутствуют",
          os.path.isfile(BLOB_PATH) and os.path.isfile(META_PATH))
    blob = open(BLOB_PATH, "rb").read()
    meta = json.load(open(META_PATH, encoding="utf-8"))

    sha = hashlib.sha256(blob).hexdigest()
    check("1. SHA-256 фикстуры НЕ изменился (файл заморожен)", sha == meta["sha256"])
    check("2. размер фикстуры совпадает с манифестом", len(blob) == meta["byte_length"])

    pw = meta["passphrase"]
    exp = meta["expected"]

    # inspect без пароля
    info = serializer.inspect_container(blob)
    check("3. inspect: версия контейнера/payload = 1",
          info["container_format_version"] == exp["container_format_version"]
          and info["payload_schema_version"] == exp["payload_schema_version"])

    # decrypt + migrate + validate
    raw = serializer.decode_payload(blob, pw).as_dict()
    migrated = migrations.migrate_to_current(raw)
    payload = validator.validate_payload(migrated)
    check("4. расшифровка известным паролем + миграция к текущей схеме успешны",
          payload.payload_schema_version == migrations.schemas.PAYLOAD_SCHEMA_VERSION)

    ids = [p.stable_id for p in payload.printers]
    check("5. идентичность принтеров сохранена", ids == exp["printer_ids"])
    check("6. адаптеры принтеров сохранены (bambu/flashforge/klipper)",
          {p.stable_id: p.adapter for p in payload.printers} == exp["printer_adapters"])
    check("7. секреты принтеров восстановлены ТОЛЬКО из шифра",
          {p.stable_id: p.credentials.get("token") for p in payload.printers} == exp["printer_tokens"])
    check("8. portable core-настройки совпадают", payload.core.values == exp["core_values"])
    check("9. machine_bound core-настройки совпадают", payload.core.machine_bound == exp["core_machine_bound"])

    # секрет не в открытых байтах
    for tok in exp["printer_tokens"].values():
        if tok:
            if tok.encode("utf-8") in blob:
                check("10. секрет '%s' НЕ в открытых байтах" % tok, False)
                break
    else:
        check("10. ни один секрет принтера не встречается в открытых байтах фикстуры", True)

    # неверный пароль -> единый безопасный код
    from app.config_backup.errors import BackupError
    try:
        serializer.decode_payload(blob, pw + "x"); wrong = False
    except BackupError as e:
        wrong = e.reason == "backup_corrupted_or_wrong_password"
    check("11. неверный пароль к фикстуре -> единый безопасный код", wrong)

    # СКВОЗНОЕ восстановление на чистую цель (in-memory) — доказать применимость навсегда
    tgt = DictGateway(config={}, app_settings={}, printers=[], modules={})
    plan = restore_plan.build_plan(tgt, payload, ["core", "printers"], apply_machine_bound=False)
    check("12. план строится (added=%d)" % plan["counts"]["printers_added"],
          plan["counts"]["printers_added"] == len(exp["printer_ids"]))
    jr = recovery.RecoveryJournal(os.path.join(os.environ.get("TEMP", "."), "cfgbackup_fixture_journal.json"))
    res = restore_engine.apply_restore(tgt, payload, ["core", "printers"], jr, apply_machine_bound=False)
    check("13. восстановление применяется атомарно", res["status"] == "ok")
    got_ids = {p["id"] for p in tgt.list_printers()}
    check("14. все принтеры фикстуры восстановлены", got_ids == set(exp["printer_ids"]))
    check("15. delete-флаг импортирован как OFF (деструктив)",
          tgt.get_app_setting("printer_files_delete_enabled") == "0")
    # migration path len from v1 is 0 today; must never require a missing migration
    check("16. путь миграции от v1 определён (нет пропущенных миграций)",
          migrations.migration_path_len(1) == migrations.schemas.PAYLOAD_SCHEMA_VERSION - 1)

    enumerate_all_versions()


def _discover_fixtures():
    """АВТО-перечисление ВСЕХ замороженных фикстур всех версий контейнера.
    v1: sample.3diwell-backup + sample.meta.json (одиночная запись).
    vN>=2: fixture_manifest.json со списком fixtures. Новая папка vN подхватывается сама."""
    import glob
    root = os.path.join(os.path.dirname(__file__), "fixtures", "config_backup")
    found = []
    # v1 (совместимость с исходным манифестом)
    if os.path.isfile(META_PATH):
        m = json.load(open(META_PATH, encoding="utf-8"))
        found.append({"version_dir": "v1", "file": os.path.basename(BLOB_PATH), "path": BLOB_PATH,
                      "passphrase": m.get("passphrase"), "requires_password": True,
                      "sha256": m["sha256"], "expected": m["expected"]})
    # vN>=2 и module_data (2.829) через fixture_manifest.json — новые папки подхватываются сами
    pats = (sorted(glob.glob(os.path.join(root, "v*", "fixture_manifest.json")))
            + sorted(glob.glob(os.path.join(root, "module_data", "fixture_manifest.json"))))
    for man_path in pats:
        vdir = os.path.basename(os.path.dirname(man_path))
        man = json.load(open(man_path, encoding="utf-8"))
        for e in man.get("fixtures", []):
            found.append({"version_dir": vdir, "file": e["file"],
                          "path": os.path.join(os.path.dirname(man_path), e["file"]),
                          "passphrase": e.get("passphrase"), "requires_password": e.get("requires_password", False),
                          "sha256": e["sha256"], "expected": e["expected"]})
    return found


def enumerate_all_versions():
    print("--- АВТО-перечисление всех замороженных фикстур (v1/v2 ...) ---")
    from app.config_backup.errors import BackupError
    fx = _discover_fixtures()
    versions = sorted({f["version_dir"] for f in fx})
    check("17. авто-перечисление находит и v1, и v2", "v1" in versions and "v2" in versions)
    check("18. найдено >= 3 замороженных фикстур (v1 + v2 none + v2 protected)", len(fx) >= 3)
    for f in fx:
        tag = "%s/%s" % (f["version_dir"], f["file"])
        blob = open(f["path"], "rb").read()
        check("SHA-256 заморожен: %s" % tag, hashlib.sha256(blob).hexdigest() == f["sha256"])
        info = serializer.inspect_container(blob)
        check("inspect requires_password корректен: %s" % tag,
              bool(info.get("requires_password")) == bool(f["requires_password"]))
        # decode: пароль ТОЛЬКО если требуется (v2 none — без пароля)
        payload = serializer.decode_payload(blob, f["passphrase"] if f["requires_password"] else None)
        migrated = validator.validate_payload(migrations.migrate_to_current(payload.as_dict()))
        exp = f["expected"]
        check("идентичность принтеров: %s" % tag, [p.stable_id for p in migrated.printers] == exp["printer_ids"])
        check("секреты восстановлены: %s" % tag,
              {p.stable_id: p.credentials.get("token") for p in migrated.printers} == exp["printer_tokens"])
        check("core значения совпадают: %s" % tag, migrated.core.values == exp["core_values"])
        # сквозной restore на чистую цель
        tgt = DictGateway(config={}, app_settings={}, printers=[], modules={})
        jr = recovery.RecoveryJournal(os.path.join(os.environ.get("TEMP", "."), "cfgbackup_%s.json" % f["version_dir"]))
        res = restore_engine.apply_restore(tgt, migrated, ["core", "printers"], jr, apply_machine_bound=False)
        check("сквозной restore применяется: %s" % tag,
              res["status"] == "ok" and {p["id"] for p in tgt.list_printers()} == set(exp["printer_ids"]))
        check("delete-флаг импортирован OFF: %s" % tag, tgt.get_app_setting("printer_files_delete_enabled") == "0")
        if f["requires_password"]:
            try:
                serializer.decode_payload(blob, (f["passphrase"] or "") + "x"); bad = True
            except BackupError as e:
                bad = e.reason != "backup_corrupted_or_wrong_password"
            check("неверный пароль -> единый код: %s" % tag, not bad)
    # ридер существует для каждой версии контейнера
    from app.config_backup import container_v1 as _c1, container_v2 as _c2
    check("19. reader v1 существует (container_v1.read_container)", callable(getattr(_c1, "read_container", None)))
    check("20. reader v2 существует (container_v2.read_container_v2)", callable(getattr(_c2, "read_container_v2", None)))


if __name__ == "__main__":
    main()
    print("\n" + "=" * 60)
    print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
    sys.exit(1 if _n["fail"] else 0)
