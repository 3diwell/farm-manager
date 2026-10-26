# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — контракт резервного копирования конфигурации (крипто/контейнер/реестр/сериализатор).

Оффлайн, server.py НЕ импортируется (только читается как текст для проверки полноты реестра —
против ложно-зелёного из-за named-mutex работающей программы). Sentinel-метка доказывает, что
секрет НЕ попадает в открытые байты контейнера.
"""
import ast
import io
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app.config_backup import crypto, container_v1, schemas, serializer
from app.config_backup import settings_registry as reg
from app.config_backup.errors import BackupError
from app.config_backup.repository import DictGateway

# Уникальная метка-ловушка: если она окажется в открытых байтах контейнера — шифрование дырявое.
SENTINEL = "CONFIG_BACKUP_CONTRACT_SENTINEL_2_827"

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


# ── КРИПТО ────────────────────────────────────────────────────────────────────
def sec_crypto():
    print("--- крипто (AES-256-GCM / scrypt) ---")
    salt, nonce = crypto.new_salt(), crypto.new_nonce()
    aad = b"header-bytes"
    pt = ("секрет " + SENTINEL).encode("utf-8")
    ct = crypto.encrypt(pt, "pw-correct", salt, nonce, aad)
    check("1. round-trip расшифровывает исходный текст",
          crypto.decrypt(ct, "pw-correct", salt, nonce, aad) == pt)
    check("2. ciphertext НЕ содержит открытый sentinel (реально зашифровано)",
          SENTINEL.encode("utf-8") not in ct)
    try:
        crypto.decrypt(ct, "pw-WRONG", salt, nonce, aad); ok = False
    except BackupError as e:
        ok = e.reason == "backup_corrupted_or_wrong_password"
    check("3. неверный пароль -> единый код backup_corrupted_or_wrong_password", ok)
    try:
        crypto.decrypt(ct, "pw-correct", salt, nonce, b"tampered-aad"); ok = False
    except BackupError as e:
        ok = e.reason == "backup_corrupted_or_wrong_password"
    check("4. подмена AAD -> ТОТ ЖЕ код (без oracle-различия)", ok)
    ct2 = crypto.encrypt(pt, "pw-correct", crypto.new_salt(), crypto.new_nonce(), aad)
    check("5. другой salt/nonce -> другой ciphertext (недетерминированность)", ct != ct2)
    check("6. cipher/kdf идентификаторы зафиксированы",
          crypto.CIPHER_ID == "AES-256-GCM" and crypto.KDF_ID == "scrypt" and crypto.KEY_LEN == 32)
    check("6a. new_nonce() даёт разные значения (не детерминирован)",
          crypto.new_nonce() != crypto.new_nonce() and len(crypto.new_nonce()) == crypto.NONCE_LEN)
    check("6b. new_salt() даёт разные значения (не детерминирован)",
          crypto.new_salt() != crypto.new_salt() and len(crypto.new_salt()) == crypto.SALT_LEN)
    # KDF границы
    for n, r, p, why in [(1 << 10, 8, 1, "слабый N"), (1 << 15, 1, 1, "слабый r"),
                         (1 << 21, 8, 1, "чрезмерный N"), (7, 8, 1, "не степень двойки")]:
        try:
            crypto.validate_kdf_params(n, r, p); bad = True
        except BackupError:
            bad = False
        check("7. KDF границы отклоняют %s" % why, not bad)
    check("8. floor N=2^14 допустим", crypto.validate_kdf_params(1 << 14, 8, 1) is None)
    try:
        crypto.encode_passphrase(""); empty_ok = True
    except BackupError:
        empty_ok = False
    check("9. пустой пароль запрещён", not empty_ok)
    check("10. правило пароля: UTF-8 без нормализации/trim",
          crypto.encode_passphrase("  Å ") == "  Å ".encode("utf-8"))


# ── КОНТЕЙНЕР ─────────────────────────────────────────────────────────────────
def sec_container():
    print("--- контейнер v1 (ZIP: header.json + payload.enc) ---")
    meta = {"created_by_app": "t", "created_at": "t", "required_reader_capabilities": ["aes256gcm-scrypt-v1"]}
    blob = container_v1.write_container(meta, container_v1.canonical_json_bytes({"x": 1}), "pw")
    check("11. контейнер — валидный ZIP", blob[:2] == b"PK")
    hb, hdr, ct = container_v1.read_container(blob)
    check("12. ровно header.json + payload.enc; версии на месте",
          hdr["format_id"] == schemas.FORMAT_ID and hdr["container_format_version"] == 1)
    check("13. канонические байты детерминированы (sort_keys)",
          container_v1.canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}')
    # future container version -> reject
    import zipfile, json as _json
    fut = dict(hdr); fut["container_format_version"] = 999
    fb = io.BytesIO()
    with zipfile.ZipFile(fb, "w") as zf:
        zf.writestr("header.json", container_v1.canonical_json_bytes(fut))
        zf.writestr("payload.enc", ct)
    try:
        container_v1.read_container(fb.getvalue()); ok = False
    except BackupError as e:
        ok = e.reason == "backup_from_newer_version"
    check("14. контейнер из БУДУЩЕЙ версии отклонён", ok)
    # unknown required capability -> reject
    cap = dict(hdr); cap["required_reader_capabilities"] = ["quantum-v9"]
    cb = io.BytesIO()
    with zipfile.ZipFile(cb, "w") as zf:
        zf.writestr("header.json", container_v1.canonical_json_bytes(cap))
        zf.writestr("payload.enc", ct)
    try:
        container_v1.read_container(cb.getvalue()); ok = False
    except BackupError as e:
        ok = e.reason == "unsupported_format"
    check("15. неизвестная ОБЯЗАТЕЛЬНАЯ возможность ридера отклонена", ok)
    # extra entry -> reject
    xb = io.BytesIO()
    with zipfile.ZipFile(xb, "w") as zf:
        zf.writestr("header.json", hb); zf.writestr("payload.enc", ct); zf.writestr("evil.sh", b"rm -rf /")
    try:
        container_v1.read_container(xb.getvalue()); ok = False
    except BackupError:
        ok = True
    check("16. лишний entry в контейнере отклонён (ровно два)", ok)
    check("17. не-ZIP отклонён", _rejects(lambda: container_v1.read_container(b"not a zip at all")))


def _rejects(fn):
    try:
        fn(); return False
    except BackupError:
        return True


# ── РЕЕСТР ПОЛНОТЫ: каждая постоянная настройка server.py зарегистрирована ──────
def sec_registry_exhaustive():
    print("--- полнота реестра настроек (сверка с server.py как ТЕКСТОМ) ---")
    src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server.py"))
    src = open(src_path, encoding="utf-8", errors="replace").read()
    setting_keys = set(re.findall(r'_(?:get|set)_setting\(\s*["\']([a-z_]+)["\']', src))
    cfg_keys = set(re.findall(r'cfg\[\s*["\']([a-z_]+)["\']\s*\]', src))
    cfg_keys |= set(re.findall(r'_read_config\(\)\.get\(\s*["\']([a-z_]+)["\']', src))
    # Ключи миграции/порта, которые ведёт _port_cfg (не литералы cfg[...] в server.py):
    known = reg.all_keys()
    miss_settings = sorted(k for k in setting_keys if k not in known)
    check("18. все _get/_set_setting-ключи server.py зарегистрированы (%d ключей)" % len(setting_keys),
          not miss_settings) or print("      НЕ зарегистрированы:", miss_settings)
    miss_cfg = sorted(k for k in cfg_keys if k not in known)
    check("19. все config.json-ключи (cfg[...]/_read_config) зарегистрированы (%d)" % len(cfg_keys),
          not miss_cfg) or print("      НЕ зарегистрированы:", miss_cfg)
    check("20. каждая запись реестра имеет корректную классификацию",
          all(e.portability in (reg.PORT_PORTABLE, reg.PORT_MACHINE_BOUND, reg.PORT_OPERATIONAL,
                                reg.PORT_SECRET_DERIVED) for e in reg.all_settings()))
    check("21. секрет-производные и операционные ИСКЛЮЧЕНЫ из snapshot",
          all(e.restore_behavior == reg.RB_EXCLUDE for e in reg.excluded_settings()))
    check("22. деструктивная (printer_files_delete_enabled) импортируется как OFF",
          reg.get("printer_files_delete_enabled").restore_behavior == reg.RB_IMPORT_AS_OFF)
    check("23. пути машинно-зависимы (data_dir/archive_dir/slicer_path -> current_only)",
          all(reg.get(k).restore_behavior == reg.RB_CURRENT_ONLY
              for k in ("data_dir", "archive_dir", "slicer_path", "server_port")))


# ── СЕРИАЛИЗАТОР: типы, исключения, секрет только в шифре, sentinel не течёт ─────
def sec_serializer():
    print("--- сериализатор + сквозной экспорт ---")
    gw = DictGateway(
        config={"lan_access_enabled": True, "project_print_enabled": False, "modules_disabled": [],
                "data_dir": "D:\\d", "server_port": 8000, "pending_server_port": 9000, "migrate_from": "C:\\o"},
        app_settings={"net_monitor": "0", "security_enabled": "1", "printer_files_delete_enabled": "1",
                      "slicer_path": "C:\\o.exe", "slicer_callback_token_hash": SENTINEL,
                      "archive_dir": "E:\\a"},
        printers=[{"id": "p1", "name": "n", "type": "bambu", "ip": "10.0.0.1", "port": 8883,
                   "token": SENTINEL, "last_parts": "{}", "order_idx": 0, "gen": "auto",
                   "serial": "S1", "model": "X1C"}])
    blob = serializer.export_backup(gw, "pw", created_by="t", created_at="t")
    check("24. SENTINEL-секрет (token + token_hash) НЕ в открытых байтах контейнера",
          SENTINEL.encode("utf-8") not in blob)
    payload = serializer.decode_payload(blob, "pw")
    check("25. операционные ключи исключены (pending_server_port/migrate_from)",
          "pending_server_port" not in payload.core.machine_bound
          and "migrate_from" not in payload.core.machine_bound)
    check("26. секрет-производный slicer_callback_token_hash исключён",
          "slicer_callback_token_hash" not in payload.core.values
          and "slicer_callback_token_hash" not in payload.core.machine_bound)
    check("27. типы: bool/int/list восстановлены как типы",
          payload.core.values["lan_access_enabled"] is True
          and payload.core.machine_bound["server_port"] == 8000
          and isinstance(payload.core.values["modules_disabled"], list))
    check("28. секрет принтера сохранён ТОЛЬКО внутри шифра",
          payload.printers[0].credentials["token"] == SENTINEL)
    check("29. last_parts (операционный кэш) не переносится",
          "last_parts" not in payload.printers[0].as_dict())
    mut = serializer.payload_to_mutation(payload, ["core", "printers"], apply_machine_bound=False)
    check("30. import_as_off форсирует delete=0 в мутации",
          mut.app_set.get("printer_files_delete_enabled") == "0")
    check("31. machine_bound по умолчанию не применяется",
          "data_dir" not in mut.config_set and "server_port" not in mut.config_set)
    info = serializer.inspect_container(blob)
    check("32. inspect без пароля отдаёт версии/счётчики, но не payload",
          info["container_format_version"] == 1 and info["printer_count"] == 1
          and "core_values" not in info)


if __name__ == "__main__":
    sec_crypto()
    sec_container()
    sec_registry_exhaustive()
    sec_serializer()
    print("\n" + "=" * 60)
    print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
    sys.exit(1 if _n["fail"] else 0)
