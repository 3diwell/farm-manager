# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.827 — крипто-слой резервного копирования (ТОЛЬКО проверенный AEAD).

Контракт v1 (заморожен):
  KDF     = scrypt (cryptography.hazmat), выход 256 бит;
  cipher  = AES-256-GCM (cryptography.hazmat AESGCM);
  AAD     = канонические байты header.json (подмена header детектируется);
  salt/nonce случайны на КАЖДЫЙ backup;
  passphrase -> UTF-8 БЕЗ trim и БЕЗ нормализации (чётко зафиксированное правило).

Никакого XOR/самописного шифра/Fernet/ZIP-пароля/только-HMAC. Слабые/чрезмерные параметры
KDF отклоняются (floor против слабости, ceiling против DoS). Неверный пароль и повреждение
дают ОДНУ И ТУ ЖЕ ошибку (без oracle).
"""
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.config_backup.errors import (BackupError, BACKUP_CORRUPTED_OR_WRONG_PASSWORD,
                                       WEAK_ENCRYPTION_PARAMS, EXCESSIVE_ENCRYPTION_PARAMS)

CIPHER_ID = "AES-256-GCM"
KDF_ID = "scrypt"

KEY_LEN = 32          # 256-bit
NONCE_LEN = 12        # 96-bit GCM nonce
SALT_LEN = 16

# Параметры KDF выпуска v1 (пишутся в header; importer проверяет границы навсегда).
KDF_N_DEFAULT = 1 << 15     # 32768
KDF_R_DEFAULT = 8
KDF_P_DEFAULT = 1

# Границы (НЕИЗМЕНЯЕМЫЙ security floor + DoS-ceiling).
KDF_N_MIN = 1 << 14         # 16384 — floor против слабых параметров
KDF_N_MAX = 1 << 20         # 1048576 — ceiling против DoS/памяти
KDF_R_MIN, KDF_R_MAX = 8, 32
KDF_P_MIN, KDF_P_MAX = 1, 16
# scrypt память ~ 128*N*r; защита от исчерпания памяти обеспечивается ceiling'ом N/r
# (validate_kdf_params отклоняет параметры выше границ ДО запуска KDF).


def _is_pow2(n):
    return isinstance(n, int) and n > 1 and (n & (n - 1)) == 0


def validate_kdf_params(n, r, p):
    """Проверить границы KDF. Слишком слабые -> weak; слишком большие -> excessive."""
    if not (_is_pow2(n) and isinstance(r, int) and isinstance(p, int)):
        raise BackupError(WEAK_ENCRYPTION_PARAMS, "kdf params malformed")
    if n < KDF_N_MIN or r < KDF_R_MIN or p < KDF_P_MIN:
        raise BackupError(WEAK_ENCRYPTION_PARAMS, "kdf below floor")
    if n > KDF_N_MAX or r > KDF_R_MAX or p > KDF_P_MAX:
        raise BackupError(EXCESSIVE_ENCRYPTION_PARAMS, "kdf above ceiling")


def encode_passphrase(passphrase):
    """ЗАФИКСИРОВАННОЕ правило: UTF-8, БЕЗ trim, БЕЗ нормализации. Пустой пароль запрещён."""
    if passphrase is None or passphrase == "":
        raise BackupError(WEAK_ENCRYPTION_PARAMS, "empty passphrase")
    return passphrase.encode("utf-8")


def derive_key(passphrase, salt, n=KDF_N_DEFAULT, r=KDF_R_DEFAULT, p=KDF_P_DEFAULT):
    validate_kdf_params(n, r, p)
    kdf = Scrypt(salt=salt, length=KEY_LEN, n=n, r=r, p=p)
    return kdf.derive(encode_passphrase(passphrase))


def new_salt():
    return os.urandom(SALT_LEN)


def new_nonce():
    return os.urandom(NONCE_LEN)


def encrypt(plaintext, passphrase, salt, nonce, aad, n=KDF_N_DEFAULT, r=KDF_R_DEFAULT, p=KDF_P_DEFAULT):
    """AES-256-GCM(scrypt(passphrase)). aad = канонические байты header. -> ciphertext(+tag)."""
    if not isinstance(plaintext, (bytes, bytearray)):
        raise BackupError(WEAK_ENCRYPTION_PARAMS, "plaintext must be bytes")
    key = derive_key(passphrase, salt, n, r, p)
    try:
        return AESGCM(key).encrypt(nonce, bytes(plaintext), aad)
    finally:
        del key


def decrypt(ciphertext, passphrase, salt, nonce, aad, n=KDF_N_DEFAULT, r=KDF_R_DEFAULT, p=KDF_P_DEFAULT):
    """Расшифровать. ЛЮБАЯ неудача (неверный пароль ИЛИ повреждение ИЛИ подмена header)
    -> ОДИН безопасный код backup_corrupted_or_wrong_password (без oracle-различий)."""
    validate_kdf_params(n, r, p)
    try:
        key = derive_key(passphrase, salt, n, r, p)
    except BackupError:
        raise
    except Exception:
        raise BackupError(BACKUP_CORRUPTED_OR_WRONG_PASSWORD, "kdf failed")
    try:
        return AESGCM(key).decrypt(nonce, bytes(ciphertext), aad)
    except InvalidTag:
        raise BackupError(BACKUP_CORRUPTED_OR_WRONG_PASSWORD, "auth tag mismatch")
    except Exception:
        raise BackupError(BACKUP_CORRUPTED_OR_WRONG_PASSWORD, "decrypt failed")
    finally:
        del key
