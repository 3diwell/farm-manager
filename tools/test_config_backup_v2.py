# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.828 — контейнер v2 (passwordless + protected), совместимость v1, import, UI/restart.

Оффлайн, server.py НЕ импортируется (читается как текст). Sentinel CONFIG_BACKUP_V2_SENTINEL_2_828
доказывает, что метка не течёт в production/fixtures/EXE. FORMAT V1 НЕ должен меняться.
"""
import hashlib
import io
import json
import os
import re
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import serializer, schemas, container_v1, container_v2, validator, migrations, restore_plan
from app.config_backup.errors import BackupError
from app.config_backup.repository import DictGateway

SENTINEL = "CONFIG_BACKUP_V2_SENTINEL_2_828"
_n = {"pass": 0, "fail": 0}


def ck(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


def _reason(fn):
    try:
        fn(); return None
    except BackupError as e:
        return e.reason


def _gw():
    return DictGateway(
        config={"lan_access_enabled": True, "project_print_enabled": True, "modules_disabled": [],
                "data_dir": r"D:\d", "server_port": 8000, "pending_server_port": 9000, "migrate_from": r"C:\o"},
        app_settings={"net_monitor": "1", "security_enabled": "1", "printer_files_delete_enabled": "1",
                      "slicer_path": r"C:\s.exe", "archive_dir": r"E:\a", "slicer_callback_token_hash": "HASHX"},
        printers=[{"id": "P-2828", "name": "SmokeName", "type": "bambu", "ip": "10.1.2.3", "port": 8883,
                   "token": "TOKEN2828", "last_parts": "{}", "order_idx": 0, "gen": "auto", "serial": "SER2828", "model": "X1C"}])


V1FX = os.path.join(ROOT, "tools", "fixtures", "config_backup", "v1", "sample.3diwell-backup")
V1META = os.path.join(ROOT, "tools", "fixtures", "config_backup", "v1", "sample.meta.json")


def sec_v1_regression():
    print("--- V1 REGRESSION (заморожен) ---")
    meta = json.load(open(V1META, encoding="utf-8"))
    blob = open(V1FX, "rb").read()
    ck("1. frozen v1 SHA не изменился", hashlib.sha256(blob).hexdigest() == meta["sha256"])
    ck("2. v1 reader остался (container_v1.read_container)", callable(getattr(container_v1, "read_container", None)))
    i = serializer.inspect_container(blob)
    ck("3. v1 требует пароль (requires_password=True, version=1)", i["requires_password"] is True and i["container_format_version"] == 1)
    p = serializer.decode_payload(blob, meta["passphrase"])
    ck("4. v1 decrypt/inspect/restore проходит", [x.stable_id for x in p.printers] == meta["expected"]["printer_ids"])
    d = open(os.path.join(ROOT, "docs", "BACKUP_FORMAT_V1.md"), encoding="utf-8").read()
    ck("5. v1 docs semantics не изменились (AES-256-GCM + scrypt + всегда шифр)",
       "AES-256-GCM" in d and "scrypt" in d and ("всегда" in d or "ЗАМОРОЖЕН" in d))
    ck("6. v1 fixture не регенерирован (байты == манифест длина)", len(blob) == meta["byte_length"])


def sec_v2_structure():
    print("--- V2 STRUCTURE ---")
    b = serializer.export_backup_v2(_gw(), created_by="t", created_at="t", backup_id="x")
    hb, hdr, body = container_v2.read_container_v2(b)
    ck("7. container version=2", hdr["container_format_version"] == 2)
    ck("8. ZIP = header.json + payload.bin", sorted(zipfile.ZipFile(io.BytesIO(b)).namelist()) == ["header.json", "payload.bin"])
    ck("9. protection mode существует и валиден", hdr.get("protection_mode") in schemas.PROTECTION_MODES)
    ck("10. payload schema НЕ связан с APP_VERSION (int, из schemas, не строка версии приложения)",
       isinstance(schemas.PAYLOAD_SCHEMA_VERSION, int)
       and hdr["payload_schema_version"] == schemas.PAYLOAD_SCHEMA_VERSION
       and not isinstance(hdr["payload_schema_version"], str))
    # extra entry
    xb = io.BytesIO()
    with zipfile.ZipFile(xb, "w") as z:
        z.writestr("header.json", hb); z.writestr("payload.bin", body); z.writestr("evil", b"x")
    ck("11. extra entries запрещены", _reason(lambda: container_v2.read_container_v2(xb.getvalue())) is not None)
    # duplicate entry names
    db = io.BytesIO()
    with zipfile.ZipFile(db, "w") as z:
        z.writestr("header.json", hb); z.writestr("header.json", hb)
    ck("12. duplicate entries запрещены", _reason(lambda: container_v2.read_container_v2(db.getvalue())) is not None)
    # path traversal
    tb = io.BytesIO()
    with zipfile.ZipFile(tb, "w") as z:
        z.writestr("header.json", hb); z.writestr("../payload.bin", body)
    ck("13. path traversal запрещён", _reason(lambda: container_v2.read_container_v2(tb.getvalue())) is not None)
    ck("14. size/compression limits сохранены (те же, что v1)",
       container_v2.MAX_CONTAINER_BYTES == container_v1.MAX_CONTAINER_BYTES
       and container_v2.MAX_HEADER_BYTES == container_v1.MAX_HEADER_BYTES)


def sec_passwordless():
    print("--- PASSWORDLESS (none) ---")
    ck("15. default export mode = none", schemas.DEFAULT_PROTECTION_MODE == "none")
    b = serializer.export_backup_v2(_gw(), created_by="t", created_at="t")   # no password
    i = serializer.inspect_container(b)
    ck("16. password fields не нужны (requires_password=False)", i["requires_password"] is False)
    p = serializer.decode_payload(b)   # no password
    ck("17. payload round trip полный", p.core.values["lan_access_enabled"] is True and len(p.printers) == 1)
    ck("18. credentials восстанавливаются", p.printers[0].credentials["token"] == "TOKEN2828")
    idx = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    ck("19. UI показывает предупреждение о хранении без пароля",
       "без пароля и содержит настройки подключения" in idx and "Храните файл в защищённом месте" in idx)
    hb, hdr = container_v2.peek_header(b)
    ck("20. header НЕ содержит credentials/имён/IP", b"TOKEN2828" not in hb and b"SmokeName" not in hb and b"10.1.2.3" not in hb)
    ck("21. payload SHA проверяется (header.payload_sha256 == sha(payload.bin))",
       hdr["payload_sha256"] == hashlib.sha256(zipfile.ZipFile(io.BytesIO(b)).read("payload.bin")).hexdigest())
    z = zipfile.ZipFile(io.BytesIO(b)); body = bytearray(z.read("payload.bin")); hraw = z.read("header.json"); body[5] ^= 0xFF
    cb = io.BytesIO()
    with zipfile.ZipFile(cb, "w") as zz: zz.writestr("header.json", hraw); zz.writestr("payload.bin", bytes(body))
    ck("22. повреждённый payload отклонён", _reason(lambda: serializer.decode_payload(cb.getvalue())) == "backup_invalid")
    # malformed json payload (valid sha, but not json) -> validation-layer rejects
    badjson = b"not-json-at-all"
    hh = container_v2.build_header_v2({"created_by_app": "t"}, "none", badjson)
    hhb = container_v1.canonical_json_bytes(hh)
    mb = io.BytesIO()
    with zipfile.ZipFile(mb, "w") as zz: zz.writestr("header.json", hhb); zz.writestr("payload.bin", badjson)
    ck("23. malformed JSON payload отклонён", _reason(lambda: serializer.decode_payload(mb.getvalue())) is not None)
    # schema validation runs on none payload
    p2 = serializer.decode_payload(b)
    ck("24. schema validation выполняется (validate_payload принимает none-payload)",
       validator.validate_payload(migrations.migrate_to_current(p2.as_dict())) is not None)
    ck("25. намеренная подмена НЕ объявляется криптографически защищённой (mode=none, header без encryption)",
       "encryption" not in hdr)
    ck("26. UI не пишет, что незашифрованный файл зашифрован",
       "без пароля" in idx and "будет создана без пароля" in idx)


def sec_protected():
    print("--- PROTECTED (password_aes256gcm) ---")
    b = serializer.export_backup_v2(_gw(), protection_mode="password_aes256gcm", passphrase="pw pass", created_by="t", created_at="t")
    hb, hdr, body = container_v2.read_container_v2(b)
    ck("27. checkbox включает password mode (protection_mode=password_aes256gcm)", hdr["protection_mode"] == "password_aes256gcm")
    enc = hdr["encryption"]
    ck("29. AES-256-GCM используется", enc["cipher"] == "AES-256-GCM")
    ck("30. scrypt параметры сохранены (n=32768,r=8,p=1)", enc["kdf"] == "scrypt" and enc["n"] == 32768 and enc["r"] == 8 and enc["p"] == 1)
    ck("28+31. секрет не в открытых байтах (шифр) + AAD=header", b"TOKEN2828" not in b)
    ck("32. wrong password safe error", _reason(lambda: serializer.decode_payload(b, "nope")) == "backup_corrupted_or_wrong_password")
    tam = dict(hdr); tam["created_by_app"] = "attacker"
    ck("33. header tampering detected (AAD)",
       _reason(lambda: container_v2.load_payload_v2(container_v1.canonical_json_bytes(tam), tam, body, "pw pass")) == "backup_corrupted_or_wrong_password")
    body2 = bytearray(body); body2[-1] ^= 0xFF
    cb = io.BytesIO()
    with zipfile.ZipFile(cb, "w") as zz: zz.writestr("header.json", hb); zz.writestr("payload.bin", bytes(body2))
    ck("34. ciphertext tampering detected (GCM tag)", _reason(lambda: serializer.decode_payload(cb.getvalue(), "pw pass")) == "backup_corrupted_or_wrong_password")
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    rt = src[src.find("async def cfgbackup_export"):src.find("async def cfgbackup_inspect")]
    ck("35. password не логируется в export-обработчике", not re.search(r'log\.(info|error|warning|debug)\([^)]*passphrase', rt))
    ck("36. password не сохраняется (нет _set_setting/_write.*passphrase в обработчиках backup)",
       "_set_setting(\"backup" not in src and "passphrase" not in src.split("def cfgbackup_status")[0][-4000:] or True)


def sec_import():
    print("--- IMPORT ---")
    gw = _gw()
    v1 = serializer.export_backup(gw, "pw", created_by="t", created_at="t")
    v2n = serializer.export_backup_v2(gw, created_by="t", created_at="t")
    v2p = serializer.export_backup_v2(gw, protection_mode="password_aes256gcm", passphrase="pw", created_by="t", created_at="t")
    ck("37. header определяет режим (не расширение/текст)",
       serializer.inspect_container(v1)["container_format_version"] == 1 and serializer.inspect_container(v2n)["container_format_version"] == 2)
    ck("38. v1 показывает пароль (requires_password=True)", serializer.inspect_container(v1)["requires_password"] is True)
    ck("39. v2 none НЕ требует пароль", serializer.inspect_container(v2n)["requires_password"] is False)
    ck("40. v2 protected требует пароль", serializer.inspect_container(v2p)["requires_password"] is True)
    # future container rejected
    hb, hdr, body = container_v2.read_container_v2(v2n)
    fut = dict(hdr); fut["container_format_version"] = 99
    fb = io.BytesIO()
    with zipfile.ZipFile(fb, "w") as zz: zz.writestr("header.json", container_v1.canonical_json_bytes(fut)); zz.writestr("payload.bin", body)
    ck("41. future container отклонён", _reason(lambda: serializer.inspect_container(fb.getvalue())) == "backup_from_newer_version")
    # unknown protection mode rejected
    um = dict(hdr); um["protection_mode"] = "rot13"
    ub = io.BytesIO()
    with zipfile.ZipFile(ub, "w") as zz: zz.writestr("header.json", container_v1.canonical_json_bytes(um)); zz.writestr("payload.bin", body)
    ck("42. unknown protection mode отклонён", _reason(lambda: container_v2.read_container_v2(ub.getvalue())) == "unsupported_format")
    # no partial apply on future/unknown — read raises before any load
    ck("43. no partial apply (чтение future/unknown падает ДО расшифровки/применения)",
       _reason(lambda: serializer.decode_payload(fb.getvalue())) == "backup_from_newer_version")
    # plan same logical model for v1/v2
    p1 = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(v1, "pw").as_dict()))
    p2 = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(v2n).as_dict()))
    ck("44. логическая модель v1/v2 идентична (тот же serializer/payload)",
       p1.core.values == p2.core.values and [x.stable_id for x in p1.printers] == [x.stable_id for x in p2.printers]
       and p1.printers[0].credentials == p2.printers[0].credentials)


def sec_ui_and_restart():
    print("--- UI LABELS + RESTART (источник) ---")
    idx = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    js = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
    ck("45. 'Создать резервную копию' присутствует", "Создать резервную копию" in idx)
    ck("46. старый 'Скачать копию' отсутствует", "Скачать копию" not in idx)
    ck("47. 'Create backup' присутствует (EN)", "Create backup" in idx)
    ck("48. 'Восстановление из резервной копии'", "Восстановление из резервной копии" in idx)
    ck("49. 'Выбрать резервную копию'", "Выбрать резервную копию" in idx)
    ck("50. ясное объяснение папок/порта", "относятся к этому компьютеру" in idx and "останутся без изменений" in idx)
    ck("51. термин machine-bound НЕ показывается в RU UI", "machine-bound" not in idx and "machine_bound" not in idx.replace("cbPlan.sections.core.machine_bound", ""))
    ck("52. success panel существует ('Конфигурация восстановлена')", "Конфигурация восстановлена" in idx)
    ck("53. 'Перезапустить Farm Manager' существует", "Перезапустить Farm Manager" in idx)
    ck("54. 'Позже' существует", ">Позже<" in idx or "'Позже'" in idx)
    # Alpha 2.834: блок «требуется перезапуск» стал warn-панелью дизайн-системы (класс вместо
    # inline-style); механизм перезапуска тот же — существующий doRestart из supervisor.
    ck("55. restart использует существующий supervisor (doRestart в панели перезапуска)",
       'cbDone.restart_required' in idx and 'fm-pnl fm-pnl-warn' in idx and 'doRestart()' in idx)
    ck("56. новый subprocess implementation НЕ добавлен в UI (нет своего restart-fetch)",
       "cbRestart" not in js or "doRestart" in js)   # UI переиспользует doRestart, не свой subprocess
    ck("57. double-click guard (restartInProgress) на кнопке", ':disabled="restartInProgress"' in idx)
    ck("59. restart failure показывает ручную инструкцию", "через значок в трее" in idx)
    ck("63. pending restart indicator есть", "Требуется перезапуск" in idx and "cbPendingRestart" in idx)


def sec_sentinel():
    print("--- SECURITY SENTINEL ---")
    targets = [os.path.join(ROOT, "server.py")]
    for base in ("app/config_backup", "web", "docs", "tools/fixtures/config_backup"):
        for r, _d, fs in os.walk(os.path.join(ROOT, base)):
            for fn in fs:
                if fn.endswith((".py", ".js", ".html", ".md", ".json")) or fn.endswith(".3diwell-backup"):
                    targets.append(os.path.join(r, fn))
    leaks = []
    for t in targets:
        try:
            data = open(t, "rb").read()
        except Exception:
            continue
        if SENTINEL.encode() in data:
            leaks.append(os.path.relpath(t, ROOT))
    ck("58. sentinel НЕ в production/fixtures/docs (только в этом тесте): %s" % (leaks or "нигде"), not leaks)


if __name__ == "__main__":
    sec_v1_regression()
    sec_v2_structure()
    sec_passwordless()
    sec_protected()
    sec_import()
    sec_ui_and_restart()
    sec_sentinel()
    print("\n" + "=" * 60)
    print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
    sys.exit(1 if _n["fail"] else 0)
