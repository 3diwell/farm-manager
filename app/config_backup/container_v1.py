# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — внешний контейнер backup v1 (ZIP: header.json + payload.enc).

СТРОГО: ровно два entry с фиксированными именами; никаких extractall, extra entries,
path traversal, absolute paths, nested archives, symlink, encrypted-zip, ZIP-bomb.
Streaming-чтение с жёсткими лимитами. Данные из backup НИКОГДА не исполняются.
Весь логический payload зашифрован ЦЕЛИКОМ (даже имена/IP принтеров — внутри payload.enc).
"""
import base64
import io
import json
import zipfile

from app.config_backup import crypto
from app.config_backup import schemas
from app.config_backup.errors import (BackupError, BACKUP_INVALID, UNSUPPORTED_FORMAT)

HEADER_NAME = "header.json"
PAYLOAD_NAME = "payload.enc"
_ALLOWED = (HEADER_NAME, PAYLOAD_NAME)

MAX_CONTAINER_BYTES = 16 * 1024 * 1024      # весь файл .3diwell-backup
MAX_HEADER_BYTES = 64 * 1024                # header.json (несекретные metadata)
MAX_PAYLOAD_ENC_BYTES = 12 * 1024 * 1024    # payload.enc (ciphertext)
MAX_COMPRESS_RATIO = 200                    # анти-ZIP-bomb (uncompressed/compressed)


def canonical_json_bytes(obj):
    """Детерминированные байты: sort_keys, компактно, UTF-8. Порядок словаря не влияет."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _unb64(s):
    try:
        return base64.b64decode(str(s), validate=True)
    except Exception:
        raise BackupError(BACKUP_INVALID, "bad base64 in header")


def build_header(meta, salt, nonce, n, r, p):
    """Собрать header (несекретные metadata + блок шифрования). meta — уже несекретное."""
    h = dict(meta or {})
    h["format_id"] = schemas.FORMAT_ID
    h["container_format_version"] = schemas.CONTAINER_FORMAT_VERSION
    h["encryption"] = {
        "kdf": crypto.KDF_ID, "n": int(n), "r": int(r), "p": int(p),
        "salt": _b64(salt), "cipher": crypto.CIPHER_ID, "nonce": _b64(nonce),
    }
    return h


def write_container(header_meta, payload_plaintext, passphrase):
    """Собрать .3diwell-backup в память -> bytes. payload_plaintext уже канонический JSON (bytes)."""
    salt, nonce = crypto.new_salt(), crypto.new_nonce()
    n, r, p = crypto.KDF_N_DEFAULT, crypto.KDF_R_DEFAULT, crypto.KDF_P_DEFAULT
    header = build_header(header_meta, salt, nonce, n, r, p)
    header_bytes = canonical_json_bytes(header)
    if len(header_bytes) > MAX_HEADER_BYTES:
        raise BackupError(BACKUP_INVALID, "header too large")
    ciphertext = crypto.encrypt(payload_plaintext, passphrase, salt, nonce, aad=header_bytes, n=n, r=r, p=p)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(zipfile.ZipInfo(HEADER_NAME), header_bytes)
        zf.writestr(zipfile.ZipInfo(PAYLOAD_NAME), ciphertext)
    return buf.getvalue()


def _read_entry(zf, zi, cap):
    """Строгое streaming-чтение одного entry с лимитом (анти-bomb)."""
    if zi.flag_bits & 0x1:
        raise BackupError(UNSUPPORTED_FORMAT, "encrypted zip entry")
    mode = (zi.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        raise BackupError(BACKUP_INVALID, "symlink entry")
    if zi.is_dir() or ("/" in zi.filename) or ("\\" in zi.filename) or (".." in zi.filename):
        raise BackupError(BACKUP_INVALID, "path traversal / nested entry")
    if zi.file_size > cap:
        raise BackupError(BACKUP_INVALID, "entry too large")
    if zi.compress_size > 0 and (zi.file_size / max(1, zi.compress_size)) > MAX_COMPRESS_RATIO:
        raise BackupError(BACKUP_INVALID, "suspicious compression ratio")
    with zf.open(zi, "r") as f:
        data = f.read(cap + 1)
    if len(data) > cap:
        raise BackupError(BACKUP_INVALID, "entry exceeds cap")
    return data


def read_container(container_bytes):
    """Строго разобрать контейнер -> (header_bytes_raw, header_dict, ciphertext).
    Ничего не расшифровывает и не меняет. header_bytes_raw используется как AAD при decrypt."""
    if not isinstance(container_bytes, (bytes, bytearray)):
        raise BackupError(BACKUP_INVALID, "container not bytes")
    if len(container_bytes) > MAX_CONTAINER_BYTES:
        raise BackupError(BACKUP_INVALID, "container too large")
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
        header_bytes = _read_entry(zf, by[HEADER_NAME], MAX_HEADER_BYTES)
        ciphertext = _read_entry(zf, by[PAYLOAD_NAME], MAX_PAYLOAD_ENC_BYTES)
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
    if cfv > schemas.CONTAINER_FORMAT_VERSION:
        from app.config_backup.errors import BACKUP_FROM_NEWER_VERSION
        raise BackupError(BACKUP_FROM_NEWER_VERSION, "container from newer version")
    if cfv < 1:
        raise BackupError(UNSUPPORTED_FORMAT, "container version too old")
    # Незнакомые ОБЯЗАТЕЛЬНЫЕ возможности ридера -> безопасный отказ.
    for cap in (header.get("required_reader_capabilities") or []):
        if cap not in schemas.KNOWN_READER_CAPABILITIES:
            raise BackupError(UNSUPPORTED_FORMAT, "unknown required reader capability")
    return header_bytes, header, ciphertext


def decrypt_payload(header_bytes_raw, header, ciphertext, passphrase):
    """Расшифровать payload.enc. AAD = точные байты header (подмена header детектируется)."""
    enc = header.get("encryption") or {}
    if enc.get("kdf") != crypto.KDF_ID or enc.get("cipher") != crypto.CIPHER_ID:
        raise BackupError(UNSUPPORTED_FORMAT, "unknown kdf/cipher")
    n, r, p = enc.get("n"), enc.get("r"), enc.get("p")
    if not all(isinstance(x, int) for x in (n, r, p)):
        raise BackupError(BACKUP_INVALID, "bad kdf params")
    crypto.validate_kdf_params(n, r, p)   # floor/ceiling ДО тяжёлого KDF
    salt, nonce = _unb64(enc.get("salt")), _unb64(enc.get("nonce"))
    if len(salt) < 8 or len(nonce) != crypto.NONCE_LEN:
        raise BackupError(BACKUP_INVALID, "bad salt/nonce length")
    return crypto.decrypt(ciphertext, passphrase, salt, nonce, aad=header_bytes_raw, n=n, r=r, p=p)
