# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Платные модули в папке выпуска (25.10.2026, Beta 3.71): tools/build_release.py подписывает «Складской учёт» и
«Расчёт заказа» рабочим ключом пакетов, а обычный архив без подписи (он работает бесплатно) в выпуск не кладёт.

Проверяется ПОВЕДЕНИЕ шага сборки на одноразовом ключе во временной папке (вне проекта):
  A. без ключа выпуск не собирается; ключ не из рабочих ключей программы и чужой закрытый ключ — отказ;
  B. платная сборка: паспорт подписан и проходит проверку рабочими ключами программы, модель paid, в пакете —
     своя копия SDK и рабочие ключи программы (модуль сам проверяет лицензию), дата выпуска — сегодня;
  C. --unsigned-paid — внутренняя сборка: подписи нет, и шаг об этом предупреждает.
Сеть, рабочая ферма и настоящие ключи не используются.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
import contextlib

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from app.licensing import fm_license_sdk as S  # noqa: E402
from app.licensing import trust as TR  # noqa: E402
import build_release as BR  # noqa: E402

PASS, FAIL = [0], []


def check(name, ok, extra=""):
    if ok:
        PASS[0] += 1
        print("PASS — " + name)
    else:
        FAIL.append(name)
        print("FAIL — " + name + ("  :: " + repr(extra)[:600] if extra != "" else ""))


TMP = tempfile.mkdtemp(prefix="fm_paid_rel_")
KEY_ID = "t-pkg-release-check"


def write_key(name, key, password):
    p = os.path.join(TMP, name + ".pem")
    with open(p, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.BestAvailableEncryption(password.encode("utf-8"))))
    pf = os.path.join(TMP, name + ".pass")
    with open(pf, "w", encoding="utf-8") as f:
        f.write(password + "\n")
    return p, pf


def pub(key):
    return S.b64u_encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def signer_with(env):
    """paid_signer() с заданными переменными -> (результат или None, код выхода или None, вывод)."""
    saved = {k: os.environ.get(k) for k in (BR.ENV_SIGN_KEY, BR.ENV_SIGN_PASSFILE)}
    for k in saved:
        os.environ.pop(k, None)
    os.environ.update(env)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            try:
                return BR.paid_signer(), None, buf.getvalue()
            except SystemExit as e:
                return None, e.code, buf.getvalue()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


KEY = Ed25519PrivateKey.generate()
OTHER = Ed25519PrivateKey.generate()
kp, pf = write_key(KEY_ID, KEY, "release-check-pass")
saved_prod = TR.PRODUCTION_KEYS
TR.PRODUCTION_KEYS = tuple(saved_prod) + ({"key_id": KEY_ID, "purpose": "package", "public_key": pub(KEY),
                                            "label": "одноразовый ключ проверки выпуска"},)
try:
    print("--- A. без рабочего ключа пакетов выпуск не собирается ---")
    r, code, out = signer_with({})
    check("A1. ключ не задан — сборка останавливается и говорит, что задать", r is None and code == 1
          and BR.ENV_SIGN_KEY in out and "--unsigned-paid" in out, (code, out[-300:]))
    stray_p, stray_pf = write_key("t-pkg-not-in-trust", OTHER, "x")
    r, code, out = signer_with({BR.ENV_SIGN_KEY: stray_p, BR.ENV_SIGN_PASSFILE: stray_pf})
    check("A2. ключ, которого нет в рабочих ключах пакетов программы, — отказ", r is None and code == 1
          and "не записан в рабочих ключах" in out, out[-300:])
    wrong_p, wrong_pf = write_key(KEY_ID + "-copy", OTHER, "y")
    os.makedirs(os.path.join(TMP, "wrong"))
    wrong_named = os.path.join(TMP, "wrong", KEY_ID + ".pem")      # имя как у рабочего ключа, а пара — чужая
    shutil.move(wrong_p, wrong_named)
    r, code, out = signer_with({BR.ENV_SIGN_KEY: wrong_named, BR.ENV_SIGN_PASSFILE: wrong_pf})
    check("A3. закрытый ключ под нужным именем, но чужой (не пара открытому в программе) — отказ", r is None and code == 1
          and "не соответствует открытому" in out, out[-300:])

    print("--- B. платная сборка подписана и проверяема ---")
    signer, code, out = signer_with({BR.ENV_SIGN_KEY: kp, BR.ENV_SIGN_PASSFILE: pf})
    check("B0. правильный ключ и пароль из файла — подписывающий готов", signer is not None and signer[1] == KEY_ID, (code, out))
    for src_dir in BR.PAID_MODULES:
        dst = os.path.join(TMP, "%s.zip" % src_dir)
        with contextlib.redirect_stdout(io.StringIO()):
            BR.sign_paid(src_dir, dst, signer)
        with zipfile.ZipFile(dst) as z:
            names = z.namelist()
            man = json.loads(z.read("%s/module.json" % src_dir).decode("utf-8")) if "%s/module.json" % src_dir in names else {}
            mid = man.get("id", src_dir)
            raw = z.read("%s/%s" % (mid, S.PACKAGE_MANIFEST_NAME))
            emb = z.read("%s/fm_embedded.py" % mid).decode("utf-8")
            has_sdk = "%s/fm_license_sdk.py" % mid in names and "%s/fm_paid_guard.py" % mid in names
        pkg_keys = {k: v for k, v in TR.trusted_keys().items() if v.purpose == S.PURPOSE_PACKAGE}
        payload = S.verify_package_manifest(raw, pkg_keys)
        check("B1. %s: паспорт подписан и проходит проверку рабочими ключами программы" % src_dir,
              payload["module_id"] == mid and payload["version"] == man.get("version"), payload.get("version"))
        check("B2. %s: модель — paid, редакция standard, дата выпуска — сегодня" % src_dir,
              payload["licensing"]["model"] == "paid" and payload["edition"] == "standard"
              and payload["released_at"] == signer[2], (payload["licensing"], payload["released_at"]))
        lic_ids = [k["key_id"] for k in saved_prod if k["purpose"] == "license"]
        check("B3. %s: своя копия SDK и самопроверки, в ней рабочие ключи лицензий программы" % src_dir,
              has_sdk and lic_ids and all(i in emb for i in lic_ids), (has_sdk, lic_ids))
        doc = S.load_document(raw)
        check("B4. %s: подпись — тем самым ключом пакетов" % src_dir, doc.get("sig", {}).get("key_id") == KEY_ID,
              doc.get("sig", {}).get("key_id"))

    print("--- C. внутренняя сборка своей фермы ---")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = BR.paid_signer(unsigned_paid=True)
    check("C1. --unsigned-paid: подписи нет, и сборка предупреждает, что такой выпуск не для пользователей",
          r is None and "не отдавать" in buf.getvalue(), buf.getvalue())
finally:
    TR.PRODUCTION_KEYS = saved_prod
    shutil.rmtree(TMP, ignore_errors=True)

print("\nИТОГО: PASS=%d FAIL=%d" % (PASS[0], len(FAIL)))
sys.exit(1 if FAIL else 0)
