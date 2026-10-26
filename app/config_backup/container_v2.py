# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.828 — внешний контейнер backup v2 (ZIP: header.json + payload.bin).

v2 добавляет ТОЛЬКО упаковку и режим защиты. Логическая модель payload та же (serializer один).
Два режима (header.protection_mode):
  • none               — payload.bin = канонический UTF-8 JSON БЕЗ шифрования; SHA-256+ZIP CRC
                          защищают от СЛУЧАЙНОГО повреждения (НЕ от намеренной подмены);
  • password_aes256gcm — payload.bin = ciphertext; тот же проверенный стек v1 (scrypt+AES-256-GCM),
                          AAD = канонические байты header.

container v1 (payload.enc, всегда шифр) НЕ трогается — этот модуль его переиспользует для
безопасного чтения записей (_c1._read_entry) и канонизации, ничего в нём не меняя.
Данные из backup НИКОГДА не исполняются; строгий разбор (ровно 2 entry, анти-traversal/symlink/bomb).
"""
import base64
import hashlib
import io
import json
import zipfile

from app.config_backup import crypto
from app.config_backup import schemas
from app.config_backup import container_v1 as _c1
from app.config_backup.errors import (BackupError, BACKUP_INVALID, UNSUPPORTED_FORMAT,
                                       BACKUP_FROM_NEWER_VERSION, BACKUP_CORRUPTED_OR_WRONG_PASSWORD)

HEADER_NAME = schemas.HEADER_NAME               # "header.json"
PAYLOAD_NAME = schemas.PAYLOAD_NAME_V2           # "payload.bin"
_ALLOWED = (HEADER_NAME, PAYLOAD_NAME)

# Те же лимиты, что у v1 (переиспользуем — не задаём новых, слабее прежних).
MAX_CONTAINER_BYTES = _c1.MAX_CONTAINER_BYTES
MAX_HEADER_BYTES = _c1.MAX_HEADER_BYTES
MAX_PAYLOAD_BYTES = _c1.MAX_PAYLOAD_ENC_BYTES


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _unb64(s):
    try:
        return base64.b64decode(str(s), validate=True)
    except Exception:
        raise BackupError(BACKUP_INVALID, "bad base64 in header")


def _sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def build_header_v2(meta, protection_mode, payload_plaintext, salt=None, nonce=None,
                    n=None, r=None, p=None):
    """Собрать header v2 (несекретный). payload_length/payload_sha256 — по ОТКРЫТОМУ payload
    (для password это plaintext; sha привязан через AAD). Header не содержит пользовательских
    данных: имён/IP/credentials/значений настроек в нём нет."""
    if protection_mode not in schemas.PROTECTION_MODES:
        raise BackupError(BACKUP_INVALID, "unknown protection_mode")
    h = dict(meta or {})
    h["format_id"] = schemas.FORMAT_ID
    h["container_format_version"] = schemas.CONTAINER_FORMAT_VERSION_2
    h["payload_schema_version"] = schemas.PAYLOAD_SCHEMA_VERSION
    h["protection_mode"] = protection_mode
    h["payload_encoding"] = schemas.PAYLOAD_ENCODING_CANONICAL_JSON
    h["payload_length"] = len(payload_plaintext)
    h["payload_sha256"] = _sha256_hex(payload_plaintext)
    if protection_mode == schemas.PROTECTION_MODE_PASSWORD:
        h["encryption"] = {"kdf": crypto.KDF_ID, "n": int(n), "r": int(r), "p": int(p),
                           "salt": _b64(salt), "cipher": crypto.CIPHER_ID, "nonce": _b64(nonce)}
        h["required_reader_capabilities"] = ["aes256gcm-scrypt-v1"]
    else:
        h.pop("encryption", None)
        h["required_reader_capabilities"] = ["cleartext-json-v2"]
    return h


def write_container_v2(header_meta, payload_plaintext, protection_mode, passphrase=None):
    """Собрать .3diwell-backup v2 -> bytes. payload_plaintext — канонический JSON (bytes).
    none: без пароля. password_aes256gcm: пустой пароль запрещён (не «скрытый ключ»)."""
    if not isinstance(payload_plaintext, (bytes, bytearray)):
        raise BackupError(BACKUP_INVALID, "payload must be bytes")
    if protection_mode not in schemas.PROTECTION_MODES:
        raise BackupError(BACKUP_INVALID, "unknown protection_mode")

    if protection_mode == schemas.PROTECTION_MODE_PASSWORD:
        crypto.encode_passphrase(passphrase)                 # пустой/None -> weak_encryption_params
        salt, nonce = crypto.new_salt(), crypto.new_nonce()
        n, r, p = crypto.KDF_N_DEFAULT, crypto.KDF_R_DEFAULT, crypto.KDF_P_DEFAULT
        header = build_header_v2(header_meta, protection_mode, payload_plaintext, salt, nonce, n, r, p)
        header_bytes = _c1.canonical_json_bytes(header)
        if len(header_bytes) > MAX_HEADER_BYTES:
            raise BackupError(BACKUP_INVALID, "header too large")
        body = crypto.encrypt(payload_plaintext, passphrase, salt, nonce, aad=header_bytes, n=n, r=r, p=p)
    else:
        header = build_header_v2(header_meta, protection_mode, payload_plaintext)
        header_bytes = _c1.canonical_json_bytes(header)
        if len(header_bytes) > MAX_HEADER_BYTES:
            raise BackupError(BACKUP_INVALID, "header too large")
        body = bytes(payload_plaintext)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(zipfile.ZipInfo(HEADER_NAME), header_bytes)
        zf.writestr(zipfile.ZipInfo(PAYLOAD_NAME), body)
    return buf.getvalue()


def peek_header(container_bytes):
    """БЕЗОПАСНО прочитать ТОЛЬКО header.json (для маршрутизации по версии). Ничего не
    расшифровывает и не парсит payload. -> (header_bytes_raw, header_dict)."""
    if not isinstance(container_bytes, (bytes, bytearray)):
        raise BackupError(BACKUP_INVALID, "container not bytes")
    if len(container_bytes) > MAX_CONTAINER_BYTES:
        raise BackupError(BACKUP_INVALID, "container too large")
    try:
        zf = zipfile.ZipFile(io.BytesIO(container_bytes), "r")
    except Exception:
        raise BackupError(BACKUP_INVALID, "not a zip container")
    with zf:
        by = {zi.filename: zi for zi in zf.infolist()}
        if HEADER_NAME not in by:
            raise BackupError(BACKUP_INVALID, "no header.json")
        header_bytes = _c1._read_entry(zf, by[HEADER_NAME], MAX_HEADER_BYTES)
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except Exception:
        raise BackupError(BACKUP_INVALID, "header not valid json")
    if not isinstance(header, dict):
        raise BackupError(BACKUP_INVALID, "header not object")
    if header.get("format_id") != schemas.FORMAT_ID:
        raise BackupError(UNSUPPORTED_FORMAT, "wrong format_id")
    return header_bytes, header


def read_container_v2(container_bytes):
    """Строго разобрать v2 -> (header_bytes_raw, header_dict, body_bytes). Ничего не расшифровывает."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(container_bytes), "r")
    except Exception:
        raise BackupError(BACKUP_INVALID, "not a zip container")
    with zf:
        infos = zf.infolist()
        if len(infos) != 2:
            raise BackupError(BACKUP_INVALID, "container must have exactly 2 entries")
        names = [zi.filename for zi in infos]
        if sorted(names) != sorted(_ALLOWED) or len(set(names)) != 2:
            raise BackupError(BACKUP_INVALID, "unexpected/duplicate entries")
        by = {zi.filename: zi for zi in infos}
        header_bytes = _c1._read_entry(zf, by[HEADER_NAME], MAX_HEADER_BYTES)
        body = _c1._read_entry(zf, by[PAYLOAD_NAME], MAX_PAYLOAD_BYTES)
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except Exception:
        raise BackupError(BACKUP_INVALID, "header not valid json")
    if not isinstance(header, dict):
        raise BackupError(BACKUP_INVALID, "header not object")
    if header.get("format_id") != schemas.FORMAT_ID:
        raise BackupError(UNSUPPORTED_FORMAT, "wrong format_id")
    cfv = header.get("container_format_version")
    if not isinstance(cfv, int):
        raise BackupError(BACKUP_INVALID, "bad container_format_version")
    if cfv != schemas.CONTAINER_FORMAT_VERSION_2:
        if cfv > schemas.MAX_CONTAINER_FORMAT_VERSION:
            raise BackupError(BACKUP_FROM_NEWER_VERSION, "container from newer version")
        raise BackupError(BACKUP_INVALID, "not a v2 container")
    mode = header.get("protection_mode")
    if mode not in schemas.PROTECTION_MODES:
        raise BackupError(UNSUPPORTED_FORMAT, "unknown protection_mode")
    if header.get("payload_encoding") != schemas.PAYLOAD_ENCODING_CANONICAL_JSON:
        raise BackupError(UNSUPPORTED_FORMAT, "unknown payload encoding")
    for cap in (header.get("required_reader_capabilities") or []):
        if cap not in schemas.KNOWN_READER_CAPABILITIES:
            raise BackupError(UNSUPPORTED_FORMAT, "unknown required reader capability")
    return header_bytes, header, body


def requires_password(header):
    return (header or {}).get("protection_mode") == schemas.PROTECTION_MODE_PASSWORD


def load_payload_v2(header_bytes_raw, header, body, passphrase=None):
    """Вернуть открытый канонический payload (bytes). none: проверить SHA-256 (случайное
    повреждение) и вернуть body. password: расшифровать (AAD=header) и проверить SHA-256 plaintext.
    Неверный пароль/повреждение шифра -> единый безопасный код."""
    mode = header.get("protection_mode")
    want_sha = header.get("payload_sha256")
    want_len = header.get("payload_length")
    if not isinstance(want_sha, str):
        raise BackupError(BACKUP_INVALID, "missing payload_sha256")

    if mode == schemas.PROTECTION_MODE_NONE:
        # SHA/длина — защита ТОЛЬКО от случайного повреждения; importer всё равно валидирует всё.
        if isinstance(want_len, int) and len(body) != want_len:
            raise BackupError(BACKUP_INVALID, "payload length mismatch")
        if _sha256_hex(body) != want_sha:
            raise BackupError(BACKUP_INVALID, "payload sha-256 mismatch (corrupted)")
        return bytes(body)

    if mode == schemas.PROTECTION_MODE_PASSWORD:
        enc = header.get("encryption") or {}
        if enc.get("kdf") != crypto.KDF_ID or enc.get("cipher") != crypto.CIPHER_ID:
            raise BackupError(UNSUPPORTED_FORMAT, "unknown kdf/cipher")
        n, r, pp = enc.get("n"), enc.get("r"), enc.get("p")
        if not all(isinstance(x, int) for x in (n, r, pp)):
            raise BackupError(BACKUP_INVALID, "bad kdf params")
        crypto.validate_kdf_params(n, r, pp)
        salt, nonce = _unb64(enc.get("salt")), _unb64(enc.get("nonce"))
        if len(salt) < 8 or len(nonce) != crypto.NONCE_LEN:
            raise BackupError(BACKUP_INVALID, "bad salt/nonce length")
        plaintext = crypto.decrypt(body, passphrase, salt, nonce, aad=header_bytes_raw, n=n, r=r, p=pp)
        if _sha256_hex(plaintext) != want_sha:   # уже аутентифицировано GCM+AAD; двойная проверка
            raise BackupError(BACKUP_CORRUPTED_OR_WRONG_PASSWORD, "plaintext sha mismatch")
        return plaintext

    raise BackupError(UNSUPPORTED_FORMAT, "unknown protection_mode")
