# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — атомарность восстановления: план (read-only), apply, откат, журнал, recovery."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, validator, migrations, restore_plan, restore_engine, recovery
from app.config_backup.repository import DictGateway
from app.config_backup.errors import BackupError

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


def _src():
    return DictGateway(
        config={"lan_access_enabled": True, "project_print_enabled": True,
                "modules_disabled": ["quality"], "data_dir": "D:\\src", "server_port": 8123},
        app_settings={"net_monitor": "0", "security_enabled": "1",
                      "printer_files_delete_enabled": "1", "slicer_path": "C:\\src.exe"},
        printers=[{"id": "src-b", "name": "SB", "type": "bambu", "ip": "10.0.0.1", "port": 8883,
                   "token": "SRCTOK", "last_parts": "{\"a\":1}", "order_idx": 0, "gen": "auto",
                   "serial": "SS", "model": "X1C"}])


def _target():
    return DictGateway(
        config={"lan_access_enabled": False, "project_print_enabled": False, "modules_disabled": [],
                "data_dir": "C:\\tgt", "server_port": 8000},
        app_settings={"net_monitor": "1", "security_enabled": "0", "printer_files_delete_enabled": "0",
                      "slicer_path": "C:\\tgt.exe"},
        printers=[{"id": "tgt-local", "name": "TL", "type": "bambu", "ip": "10.9.9.9", "port": 8883,
                   "token": "LOCALTOK", "last_parts": "{}", "order_idx": 0, "gen": "auto",
                   "serial": "TT", "model": "P1S"}])


def _payload():
    blob = serializer.export_backup(_src(), "pw", created_by="t", created_at="t")
    raw = serializer.decode_payload(blob, "pw").as_dict()
    return validator.validate_payload(migrations.migrate_to_current(raw))


def _journal():
    return recovery.RecoveryJournal(os.path.join(tempfile.mkdtemp(), "j.json"))


def sec_plan():
    print("--- план восстановления (только чтение) ---")
    tgt = _target()
    before = tgt.full_snapshot()
    plan = restore_plan.build_plan(tgt, _payload(), ["core", "printers"], apply_machine_bound=False)
    check("1. план не мутирует хранилище", tgt.full_snapshot() == before)
    codes = {w["code"] for w in plan["warnings"]}
    check("2. предупреждение о сетевой экспозиции (lan_access)", "network_exposure" in codes)
    check("3. предупреждение о смене безопасности (security_enabled)", "security_change" in codes)
    check("4. предупреждение о деструктивной OFF (delete)", "destructive_off" in codes)
    check("5. предупреждение: пути/порт машины сохраняются", "machine_bound_kept" in codes)
    check("6. рестарт требуется (lan_access restart_required)", plan["restart_required"] is True)
    check("7. оба принтера — добавление (id нет на цели)", plan["counts"]["printers_added"] == 1)


def sec_apply():
    print("--- атомарное применение + проверка ---")
    tgt = _target()
    jr = _journal()
    res = restore_engine.apply_restore(tgt, _payload(), ["core", "printers"], jr,
                                       apply_machine_bound=False)
    check("8. apply успешен", res["status"] == "ok")
    # Alpha 2.828: после УСПЕШНОГО apply журнал ДОЛЖЕН быть complete (restart-кнопку зовём только
    # после завершённого restore) + pre-image затёрт.
    check("8a. журнал complete + pre-image затёрт после успешного apply",
          (jr.read() or {}).get("state") == "complete" and (jr.read() or {}).get("pre_image") is None
          and not jr.is_pending())
    c = tgt.get_config_json()
    check("9. portable применены (lan_access True, project_print True)",
          c["lan_access_enabled"] is True and c["project_print_enabled"] is True)
    check("10. machine_bound НЕ применены (data_dir/server_port цели)",
          c["data_dir"] == "C:\\tgt" and c["server_port"] == 8000)
    check("11. delete импортирован как OFF", tgt.get_app_setting("printer_files_delete_enabled") == "0")
    check("12. slicer_path машины сохранён", tgt.get_app_setting("slicer_path") == "C:\\tgt.exe")
    ids = {p["id"] for p in tgt.list_printers()}
    check("13. локальный принтер сохранён + добавлен из копии", ids == {"tgt-local", "src-b"})
    src_b = [p for p in tgt.list_printers() if p["id"] == "src-b"][0]
    check("14. секрет принтера восстановлен", src_b["token"] == "SRCTOK")
    check("15. restart_required проброшен", res.get("restart_required") is True)


def sec_rollback():
    print("--- откат при сбое применения ---")
    tgt = _target()
    before = tgt.full_snapshot()
    orig = tgt.apply_mutation

    def boom(m):
        orig(m)
        raise RuntimeError("disk full mid-apply")
    tgt.apply_mutation = boom
    jr = _journal()
    reason = None
    try:
        restore_engine.apply_restore(tgt, _payload(), ["core", "printers"], jr)
    except BackupError as e:
        reason = e.reason
    check("16. сбой применения -> rollback_completed", reason == "rollback_completed")
    check("17. хранилище полностью откатано к pre-image", tgt.full_snapshot() == before)
    check("18. журнал завершён и pre-image затёрт",
          (jr.read() or {}).get("state") == "complete" and (jr.read() or {}).get("pre_image") is None)


def sec_recovery():
    print("--- журнал восстановления и recovery на старте ---")
    # crash в состоянии applying -> откат к pre-image
    tgt = _target()
    pre = tgt.full_snapshot()
    jr = _journal()
    jr.set_prepared(pre, meta={"sections": ["core", "printers"]})
    jr.set_applying()
    tgt.apply_mutation(serializer.payload_to_mutation(_payload(), ["core", "printers"]))
    check("19. журнал в состоянии pending после applying", jr.is_pending())
    rec = recovery.recover_on_startup(jr, tgt)
    check("20. recovery откатил незавершённый restore", rec["action"] == "rolled_back")
    check("21. состояние вернулось к pre-image", tgt.full_snapshot() == pre)
    check("22. журнал больше не pending", not jr.is_pending())
    # committed_pending_verify + валидное состояние -> verified (без отката)
    tgt2 = _target()
    jr2 = _journal()
    jr2.set_prepared(tgt2.full_snapshot(), meta={})
    jr2.set_applying()
    payload = _payload()
    tgt2.apply_mutation(serializer.payload_to_mutation(payload, ["core", "printers"]))
    jr2.set_committed_pending_verify()
    vfn = restore_engine.make_verify_fn(payload, ["core", "printers"])
    rec2 = recovery.recover_on_startup(jr2, tgt2, verify_fn=vfn)
    check("23. committed_pending_verify + валидно -> verified (применённое сохранено)",
          rec2["action"] == "verified" and tgt2.get_config_json()["lan_access_enabled"] is True)


if __name__ == "__main__":
    sec_plan()
    sec_apply()
    sec_rollback()
    sec_recovery()
    print("\n" + "=" * 60)
    print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
    sys.exit(1 if _n["fail"] else 0)
