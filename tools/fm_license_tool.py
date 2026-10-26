# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Утилита поставщика FM: ключи, лицензии и подписанные пакеты модулей (26.09.2026).

Работает полностью без сети. Закрытые ключи НИКОГДА не кладутся в папку проекта: утилита
отказывается писать и читать ключ внутри репозитория (с учётом ссылок и junction), а файл
лицензии покупателя не записывает в папку проекта. Рабочий ключ шифруется паролем; храните две
копии в разных местах. В программу и в пакеты попадают только ОТКРЫТЫЕ ключи.

    python tools/fm_license_tool.py keygen --purpose license --key-id vendor-lic-2026 --out D:\\keys
    python tools/fm_license_tool.py keygen --purpose package --key-id test-pkg --out %TEMP%\\k --no-passphrase --test
    python tools/fm_license_tool.py sign-license --key D:\\keys\\vendor-lic-2026.pem --key-id vendor-lic-2026 ^
        --spec spec.json --out D:\\issued\\L-0001.fmlic
    python tools/fm_license_tool.py sign-package --key D:\\keys\\vendor-pkg-2026.pem --key-id vendor-pkg-2026 ^
        --module-dir modules/quality --released-at 2026-09-26T00:00:00Z --out D:\\issued\\quality-0.2.3.zip
    python tools/fm_license_tool.py sign-release --key D:\\keys\\vendor-rel-2026.pem --key-id vendor-rel-2026 ^
        --version "Alpha 3.1" --url https://3diwell.com/farm/3DIWELL_Farm_Manager_Setup_3.1.exe ^
        --sha256 <из SHA256SUMS.txt> --released-at 2026-10-01T00:00:00Z --notes "..." --out D:\\issued\\latest.json
    python tools/fm_license_tool.py verify --trusted keys.json FILE

Ключ выпуска создаётся так же, как ключ пакетов (keygen --purpose package), а его ОТКРЫТАЯ часть
вписывается в app/licensing/trust.py в список RELEASE_KEYS. С этого выпуска программа принимает
только подписанный latest.json.

ПЕРЕХОД САЙТА НА ПОДПИСАННЫЙ ФАЙЛ. Выпуски, которые уже у пользователей (Alpha 3.0 и раньше), читают
из latest.json только верхние поля version, url, notes. sign-release кладёт их копию сверху рядом с
подписью, поэтому ОДИН подписанный latest.json по прежнему адресу понимают и старые выпуски (баннер
как раньше), и новые (проверяют подпись). Верхние поля руками не править: новые выпуски отклоняют
файл, где они расходятся с подписанными.

spec.json лицензии — поля payload без key_id (docs/licensing/MODULE_LICENSING_FOUNDATION.md), например:
    {"schema_version": 1, "product_id": "3diwell-fm", "license_id": "L-0001",
     "grants": [{"module_id": "cost", "edition": "pro", "features": ["*"]}],
     "use_type": "perpetual", "updates_before": "2027-10-01T00:00:00Z", "issued_at": "2026-09-26T00:00:00Z"}
"""
import argparse
import getpass
import io
import json
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
from app.licensing import fm_license_sdk as S  # noqa: E402
import module_package as MP  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _inside_repo(path):
    return MP.inside_repo(path)


def _passphrase(a, confirm=False):
    if getattr(a, "passphrase_env", ""):
        v = os.environ.get(a.passphrase_env)
        if not v:
            raise SystemExit("переменная %s пуста" % a.passphrase_env)
        return v
    p1 = getpass.getpass("Пароль закрытого ключа: ")
    if confirm and p1 != getpass.getpass("Ещё раз: "):
        raise SystemExit("пароли не совпали")
    if confirm and len(p1) < 12:
        raise SystemExit("пароль короче 12 символов")
    return p1


def cmd_keygen(a):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    if _inside_repo(a.out):
        raise SystemExit("папка для закрытого ключа не может быть внутри проекта")
    os.makedirs(a.out, exist_ok=True)
    priv_path = os.path.join(a.out, a.key_id + ".pem")
    if os.path.exists(priv_path):
        raise SystemExit("файл уже есть: %s — ключ не перезаписывается" % priv_path)
    enc = (serialization.NoEncryption() if a.no_passphrase
           else serialization.BestAvailableEncryption(_passphrase(a, confirm=True).encode("utf-8")))
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)
    with open(priv_path, "wb") as f:
        f.write(pem)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    entry = {"key_id": a.key_id, "purpose": a.purpose, "public_key": S.b64u_encode(pub),
             "label": a.label or a.key_id}
    if a.test:
        entry["test"] = True
    with open(os.path.join(a.out, a.key_id + ".public.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=1)
    print("закрытый ключ: %s (%s; храните отдельно, не отправляйте, сделайте резервную копию)"
          % (priv_path, "без пароля — только для тестов" if a.no_passphrase else "зашифрован паролем"))
    print("открытый ключ для программы:")
    print(json.dumps(entry, ensure_ascii=False))


def _load_private(a):
    pw = os.environ.get(a.passphrase_env) if getattr(a, "passphrase_env", "") else None
    return MP.load_private_key(a.key, pw)


def cmd_sign_license(a):
    if _inside_repo(a.out):
        raise SystemExit("лицензия покупателя не записывается в папку проекта: укажите папку выдачи вне проекта")
    key = _load_private(a)
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    doc = S.sign_document(S.FORMAT_LICENSE, spec, key, a.key_id)
    S.validate_license(doc["payload"])
    with open(a.out, "wb") as f:
        f.write(S.dump_document(doc))
    print("лицензия записана: %s" % a.out)


def cmd_sign_package(a):
    key = _load_private(a)
    trust = None
    if a.embed_trust:
        with open(a.embed_trust, encoding="utf-8") as f:
            trust = json.load(f)
    data, doc = MP.build_package(a.module_dir, key, a.key_id, a.released_at, a.licensing,
                                 a.paid_feature or (), a.edition, a.channel, a.embed_sdk, trust)
    with open(a.out, "wb") as f:
        f.write(data)
    print("пакет записан: %s (%s %s, файлов %d)" % (a.out, doc["payload"]["module_id"],
                                                     doc["payload"]["version"], len(doc["payload"]["files"])))


def release_payload(version, url, sha256, released_at, notes=""):
    """Поля описания выпуска (latest.json, формат fm-release) без key_id. Проверяются теми же
    правилами, что и в программе (app/update_manifest.py): подписать неверный файл нельзя."""
    from app import update_manifest as UM
    p = {"schema_version": 1, "product_id": S.PRODUCT_ID, "version": str(version or "").strip(),
         "released_at": str(released_at or ""), "url": str(url or ""), "sha256": str(sha256 or "").lower()}
    if notes:
        p["notes"] = str(notes)
    probe = dict(p, key_id="probe")
    try:
        UM._check_release_payload(probe)
    except UM.Rejected as e:
        raise SystemExit("описание выпуска не прошло бы проверку программы: %s" % e)
    if UM.clean_notes(p.get("notes")) != p.get("notes"):
        raise SystemExit("пояснение длиннее %d знаков или со служебными символами" % UM.NOTES_MAX)
    return p


def cmd_sign_release(a):
    from app import update_manifest as UM
    if not a.out.lower().endswith(".json"):
        raise SystemExit("файл описания выпуска — .json (на сайте он называется latest.json)")
    payload = release_payload(a.version, a.url, a.sha256, a.released_at, a.notes)
    key = _load_private(a)
    #  Верхние version/url/notes — для выпусков, которые уже у пользователей (см. шапку файла).
    doc = UM.with_legacy_fields(S.sign_document(UM.FORMAT_RELEASE, payload, key, a.key_id))
    with open(a.out, "wb") as f:
        f.write(S.dump_document(doc))
    print("описание выпуска записано: %s (%s)" % (a.out, payload["version"]))
    print("сверху — version/url/notes для выпусков Alpha 3.0 и раньше; файл кладётся по прежнему адресу")
    print("в программу вписывается ОТКРЫТЫЙ ключ %s — в app/licensing/trust.py, список RELEASE_KEYS" % a.key_id)


def cmd_verify(a):
    with open(a.trusted, encoding="utf-8") as f:
        items = json.load(f)
    trusted = S.trusted_set(items if isinstance(items, list) else [items])
    with open(a.file, "rb") as f:
        raw = f.read()
    if a.file.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next(n for n in z.namelist() if n.endswith("/" + S.PACKAGE_MANIFEST_NAME))
            raw = z.read(name)
    doc = S.load_document(raw)
    try:
        if doc.get("format") == "fm-release":
            from app import update_manifest as UM
            try:
                p = UM.parse(raw, trusted, require_signature=True)
            except UM.Rejected as e:
                print("ОТКЛОНЕНО: %s" % e.code)
                return 1
            print("описание выпуска подлинное: %s -> %s" % (p["latest"], p["url"]))
        elif doc.get("format") == S.FORMAT_PACKAGE:
            p = S.verify_package_manifest(raw, trusted)
            print("пакет подлинный: %s %s (%s)" % (p["module_id"], p["version"], p["released_at"]))
        else:
            p = S.verify_license(raw, trusted)
            print("лицензия подлинная: %s, обновления до %s" % (p["license_id"], p["updates_before"]))
    except S.Rejected as e:
        print("ОТКЛОНЕНО: %s" % e.code)
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--purpose", choices=(S.PURPOSE_LICENSE, S.PURPOSE_PACKAGE), required=True)
    k.add_argument("--key-id", required=True)
    k.add_argument("--label", default="")
    k.add_argument("--out", required=True)
    k.add_argument("--no-passphrase", action="store_true", help="без пароля (только тестовые ключи)")
    k.add_argument("--test", action="store_true", help="пометить открытый ключ как тестовый")
    k.add_argument("--passphrase-env", default="")
    s = sub.add_parser("sign-license")
    s.add_argument("--key", required=True)
    s.add_argument("--key-id", required=True)
    s.add_argument("--spec", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--passphrase-env", default="")
    p = sub.add_parser("sign-package")
    p.add_argument("--key", required=True)
    p.add_argument("--key-id", required=True)
    p.add_argument("--module-dir", required=True)
    p.add_argument("--released-at", required=True)
    p.add_argument("--licensing", choices=S.LICENSING_MODELS, default="free")
    p.add_argument("--paid-feature", action="append")
    p.add_argument("--edition", default=None)
    p.add_argument("--channel", choices=S.CHANNELS, default="stable")
    p.add_argument("--embed-sdk", action="store_true")
    p.add_argument("--embed-trust", default="")
    p.add_argument("--out", required=True)
    p.add_argument("--passphrase-env", default="")
    r = sub.add_parser("sign-release", help="подписать описание выпуска для сайта (latest.json)")
    r.add_argument("--key", required=True)
    r.add_argument("--key-id", required=True)
    r.add_argument("--version", required=True, help='например "Alpha 3.1"')
    r.add_argument("--url", required=True, help="https-ссылка на установщик на 3diwell.com")
    r.add_argument("--sha256", required=True, help="SHA-256 установщика (из SHA256SUMS.txt выпуска)")
    r.add_argument("--released-at", required=True, help="2026-10-01T00:00:00Z")
    r.add_argument("--notes", default="")
    r.add_argument("--out", required=True)
    r.add_argument("--passphrase-env", default="")
    v = sub.add_parser("verify")
    v.add_argument("--trusted", required=True)
    v.add_argument("file")
    a = ap.parse_args(argv)
    return {"keygen": cmd_keygen, "sign-license": cmd_sign_license, "sign-package": cmd_sign_package,
            "sign-release": cmd_sign_release, "verify": cmd_verify}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
