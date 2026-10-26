# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Общий упаковщик модулей FM (26.09.2026): архив .zip и, по желанию, подписанный паспорт пакета.

Один упаковщик вместо разных правил в каждом сборщике: в архив не попадают кэш Python, журналы,
базы, резервные копии и служебные файлы редакторов; порядок файлов и время внутри архива
постоянные, поэтому одинаковые исходники дают одинаковый архив.

Подписанный пакет (паспорт fm-package.json) нужен официальным и платным модулям:

    python tools/module_package.py --module-dir modules/quality --out quality-0.2.3.zip
    python tools/module_package.py --module-dir examples/modules/demo_paid --out demo_paid.zip ^
        --sign-key D:\\keys\\vendor-pkg.pem --key-id vendor-pkg-2026 ^
        --released-at 2026-09-26T00:00:00Z --licensing freemium --paid-feature pro_report ^
        --edition pro --embed-sdk --embed-trust D:\\keys\\trust-for-component.json

--embed-sdk кладёт в пакет копию app/licensing/fm_license_sdk.py и (11.10.2026) готовую самопроверку
платного модуля app/licensing/fm_paid_guard.py, --embed-trust — файл fm_embedded.py с ОТКРЫТЫМИ ключами
поставщика, выпуском этого пакета (EMBEDDED_RELEASE) и моделью лицензирования (EMBEDDED_LICENSING):
платный компонент проверяет лицензию сам, своими ключами и своим выпуском, не доверяя ответу ядра.
Закрытый ключ читается только вне папки проекта и никуда не копируется.
"""
import argparse
import io
import json
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app.licensing import fm_license_sdk as S  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKIP_DIRS = {"__pycache__", ".git", ".svn", ".idea", ".vscode", "node_modules", ".pytest_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".bak", ".log", ".db", ".db-wal", ".db-shm", ".sqlite", ".tmp", ".swp",
                 ".orig", ".rej", ".zip", ".fmlic", ".pem", ".key")
SKIP_NAMES = {"Thumbs.db", "desktop.ini", ".DS_Store", S.PACKAGE_MANIFEST_NAME}
EMBEDDED_NAME = "fm_embedded.py"
SDK_NAME = "fm_license_sdk.py"
GUARD_NAME = "fm_paid_guard.py"
ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def inside_repo(path):
    a = os.path.normcase(os.path.realpath(path))
    r = os.path.normcase(os.path.realpath(REPO))
    return a == r or a.startswith(r + os.sep)


def collect_files(module_dir, extra_skip=()):
    """{относительный путь: байты} файлов модуля по общим правилам исключения."""
    out = {}
    root = os.path.abspath(module_dir)
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".staging"))
        for name in sorted(files):
            if name in SKIP_NAMES or name.lower().endswith(SKIP_SUFFIXES):
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if any(rel == x or rel.startswith(x.rstrip("/") + "/") for x in extra_skip):
                continue
            why = S.path_problem(rel)
            if why:
                raise SystemExit("файл с недопустимым именем: %s (%s)" % (rel, why))
            with open(full, "rb") as f:
                out[rel] = f.read()
    return out


def embedded_source(release, trusted_keys, licensing="paid"):
    """Текст fm_embedded.py: выпуск пакета, модель лицензирования и ОТКРЫТЫЕ ключи поставщика для
    самопроверки компонента."""
    keys = [{"key_id": k["key_id"], "purpose": k["purpose"], "public_key": k["public_key"],
             "label": k.get("label", "")} for k in trusted_keys]
    return ("# -*- coding: utf-8 -*-\n"
            "# Сгенерировано tools/module_package.py при сборке пакета. Не править руками: файл подписан\n"
            "# вместе с пакетом, и любая правка делает пакет недействительным.\n"
            "EMBEDDED_RELEASE = %s\n"
            "EMBEDDED_LICENSING = %s\n"
            "TRUSTED_KEYS = %s\n") % (json.dumps(release, ensure_ascii=False, sort_keys=True),
                                      json.dumps(str(licensing)),
                                      json.dumps(keys, ensure_ascii=False, sort_keys=True, indent=1))


def make_zip(module_id, files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files):
            info = zipfile.ZipInfo("%s/%s" % (module_id, rel), date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[rel])
    return buf.getvalue()


def build_package(module_dir, sign_key=None, key_id="", released_at="", licensing="free", paid_features=(),
                  edition=None, channel="stable", embed_sdk=False, embed_trust=None):
    """-> (байты zip, документ паспорта или None). Без sign_key — обычный архив без подписи."""
    with open(os.path.join(module_dir, "module.json"), encoding="utf-8") as f:
        man = json.load(f)
    mid = str(man["id"])
    files = collect_files(module_dir)
    if not sign_key:
        return make_zip(mid, files), None
    if licensing != "free" and (not embed_sdk or embed_trust is None):
        #  Платная сборка без своей копии SDK, самопроверки и ключей работала бы бесплатно — не собираем.
        raise ValueError("платная сборка (%s) требует --embed-sdk и --embed-trust" % licensing)
    edition = edition or ("free" if licensing == "free" else "standard")
    release = {"module_id": mid, "edition": edition, "version": str(man.get("version", "")),
               "channel": channel, "released_at": released_at}
    if embed_sdk:
        for name in (SDK_NAME, GUARD_NAME):
            with open(os.path.join(REPO, "app", "licensing", name), "rb") as f:
                files[name] = f.read()
    if embed_trust is not None:
        files[EMBEDDED_NAME] = embedded_source(release, embed_trust, licensing).encode("utf-8")
    web = str(man.get("entry") or "")
    payload = {"schema_version": 1, "product_id": S.PRODUCT_ID, "module_id": mid, "edition": edition,
               "version": release["version"], "channel": channel, "released_at": released_at,
               "core_contract": str(man.get("core_contract") or man.get("version") or ""),
               "licensing": {"model": licensing, "paid_features": list(paid_features)},
               "entry": {"backend": "backend.py" if "backend.py" in files else "",
                         "web": web if web in files else ""},
               "files": {rel: S.sha256_bytes(data) for rel, data in files.items()}}
    doc = S.sign_document(S.FORMAT_PACKAGE, payload, sign_key, key_id)
    S.validate_package(doc["payload"])
    files[S.PACKAGE_MANIFEST_NAME] = S.dump_document(doc)
    return make_zip(mid, files), doc


def load_private_key(path, passphrase=None):
    if inside_repo(path):
        raise SystemExit("закрытый ключ внутри папки проекта не читается: храните его отдельно")
    from cryptography.hazmat.primitives import serialization
    with open(path, "rb") as f:
        data = f.read()
    if b"ENCRYPTED" in data and passphrase is None:
        import getpass
        passphrase = getpass.getpass("Пароль закрытого ключа: ")
    return serialization.load_pem_private_key(data, password=passphrase.encode("utf-8") if passphrase else None)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Упаковать модуль FM в .zip (по желанию — с подписью)")
    ap.add_argument("--module-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sign-key", default="")
    ap.add_argument("--key-id", default="")
    ap.add_argument("--passphrase-env", default="", help="имя переменной окружения с паролем ключа")
    ap.add_argument("--released-at", default="")
    ap.add_argument("--licensing", choices=S.LICENSING_MODELS, default="free")
    ap.add_argument("--paid-feature", action="append", default=[])
    ap.add_argument("--edition", default=None)
    ap.add_argument("--channel", choices=S.CHANNELS, default="stable")
    ap.add_argument("--embed-sdk", action="store_true")
    ap.add_argument("--embed-trust", default="", help="JSON-список ОТКРЫТЫХ ключей для fm_embedded.py")
    a = ap.parse_args(argv)
    key = None
    if a.sign_key:
        if not a.key_id or not a.released_at:
            raise SystemExit("для подписи нужны --key-id и --released-at")
        pw = os.environ.get(a.passphrase_env) if a.passphrase_env else None
        key = load_private_key(a.sign_key, pw)
    trust = None
    if a.embed_trust:
        with open(a.embed_trust, encoding="utf-8") as f:
            trust = json.load(f)
        if any("private" in json.dumps(k).lower() for k in trust):
            raise SystemExit("в файле доверенных ключей есть что-то похожее на закрытый ключ")
    try:
        data, doc = build_package(a.module_dir, key, a.key_id, a.released_at, a.licensing, a.paid_feature,
                                  a.edition, a.channel, a.embed_sdk, trust)
    except ValueError as e:
        raise SystemExit(str(e))
    with open(a.out, "wb") as f:
        f.write(data)
    if doc:
        p = doc["payload"]
        print("подписанный пакет: %s (%s %s, %s, выпуск %s, файлов %d)"
              % (a.out, p["module_id"], p["version"], p["licensing"]["model"], p["released_at"], len(p["files"])))
    else:
        print("пакет без подписи: %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
