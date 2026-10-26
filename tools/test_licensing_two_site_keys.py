# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Переход 135 сайта (26.10.2026): программа доверяет ДВУМ ключам лицензий сайта — прежнему (fm-pilot091-…, им
подписаны выданные лицензии и ответы для них) и постоянному (fm-license-prod-2026-01, новые выдачи после активации).

Проверяется ПОВЕДЕНИЕ службы лицензий программы (LicenseService) на одноразовых ключах во временной папке; сеть,
рабочая ферма и настоящие закрытые ключи не используются:
  A. в программе вписаны оба ключа сайта с назначением license и точными отпечатками; старый не заменён;
  B. лицензии, подписанные каждым из двух ключей, принимаются и лежат рядом; повтор — без дубля;
  C. подделка под новый key_id (подписана другим ключом) — bad_signature; незнакомый key_id — unknown_key;
     прежнее состояние после отказов не меняется;
  D. ответ службы старым ключом «аннулирована» сохраняется; поддельный «ok» и сетевой сбой отзыв не снимают;
     ответ новым ключом для лицензии нового ключа принимается; вложенная лицензия с чужой подписью — отказ всего ответа.
"""
import datetime
import hashlib
import os
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from app.licensing import fm_license_sdk as S  # noqa: E402
from app.licensing import service as SV  # noqa: E402
from app.licensing import trust as TR  # noqa: E402

PASS, FAIL = [0], []


def check(name, ok, extra=""):
    if ok:
        PASS[0] += 1
        print("PASS — " + name)
    else:
        FAIL.append(name)
        print("FAIL — " + name + ("  :: " + repr(extra)[:600] if extra != "" else ""))


def pub(k):
    return S.b64u_encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def code_of(fn):
    try:
        fn()
        return "ok"
    except S.Rejected as e:
        return e.code


def utc(dt=None):
    return (dt or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def license_doc(lid, key, key_id, grants=("inventory",)):
    body = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": lid,
            "grants": [{"module_id": m, "edition": "standard", "features": ["*"]} for m in grants],
            "use_type": "perpetual", "updates_before": "2029-10-19T00:00:00Z", "issued_at": "2026-10-20T12:00:00Z"}
    return S.dump_document(S.sign_document(S.FORMAT_LICENSE, body, key, key_id))


# ── A. ключи в самой программе ───────────────────────────────────────────────────────────────
print("--- A. оба ключа сайта в программе ---")
OLD_ID, NEW_ID = "fm-pilot091-f2495abcaa0c1ed0", "fm-license-prod-2026-01"
lic_keys = {k["key_id"]: (k["purpose"], hashlib.sha256(S.b64u_decode(k["public_key"])).hexdigest())
            for k in TR.PRODUCTION_KEYS if k["purpose"] == "license"}
check("A1. ключи лицензий программы — ровно прежний и постоянный ключ сайта, с точными отпечатками", lic_keys == {
    OLD_ID: ("license", "14be9932bc9d575680d297311567aa51447472871ec1ef32a4888de8d2304ea4"),
    NEW_ID: ("license", "2a65085670cc8ace30360c15a2dab08bff9c5d8183b6bb8831c621eb5679ff3c")}, lic_keys)
check("A2. постоянный адрес службы, без адреса пилота", TR.LICENSE_SERVICE_URL ==
      "https://3diwell.com/local/3diwell/fm-license-service/mark.php")

# ── B–D на одноразовых ключах с теми же ролями ────────────────────────────────────────────────
K_OLD, K_NEW, K_FAKE = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
TRUST = S.trusted_set([S.TrustedKey("t-site-old", "license", pub(K_OLD)),
                       S.TrustedKey("t-site-new", "license", pub(K_NEW))])
TMP = tempfile.mkdtemp(prefix="fm_two_keys_")
try:
    svc = SV.LicenseService(os.path.join(TMP, "data"), trusted=TRUST)
    svc.give_consent()
    print("--- B. лицензии обоими ключами ---")
    raw_a = license_doc("FM-T135-OLD", K_OLD, "t-site-old")
    raw_b = license_doc("FM-T135-NEW", K_NEW, "t-site-new", grants=("cost",))
    check("B1. лицензия прежним ключом принята", code_of(lambda: svc.import_document(raw_a)) == "ok")
    check("B2. лицензия постоянным ключом принята", code_of(lambda: svc.import_document(raw_b)) == "ok")
    svc.import_document(raw_a)
    ids = sorted(r.get("license_id") for r in svc.public_list() if r.get("ok"))
    check("B3. обе лицензии действуют рядом, повтор не дал дубля", ids == ["FM-T135-NEW", "FM-T135-OLD"], ids)

    print("--- C. подделки отклоняются, состояние не меняется ---")
    forged = license_doc("FM-T135-FORGED", K_FAKE, "t-site-new")
    check("C1. лицензия под key_id постоянного ключа, подписанная другим ключом, — bad_signature",
          code_of(lambda: svc.import_document(forged)) == S.R_BAD_SIGNATURE)
    alien = license_doc("FM-T135-ALIEN", K_FAKE, "t-site-unknown")
    check("C2. лицензия незнакомым ключом — unknown_key", code_of(lambda: svc.import_document(alien)) == S.R_UNKNOWN_KEY)
    ids2 = sorted(r.get("license_id") for r in svc.public_list() if r.get("ok"))
    check("C3. после отказов прежние лицензии на месте, лишних нет", ids2 == ids and len(svc.public_list()) == 2,
          svc.public_list())

    print("--- D. ответы службы и прежний отзыв ---")
    reqs = {r["license_id"]: r for r in svc.take_due({"inventory": "1.7.41", "cost": "0.2.5"}, "Beta 3.71", force=True)}
    check("D0. отметки по обеим лицензиям — ровно 10 полей протокола",
          set(reqs) == {"FM-T135-OLD", "FM-T135-NEW"} and all(len(r) == 10 for r in reqs.values()),
          {k: sorted(v) for k, v in reqs.items()})

    def verdict(req, status, reason, key, key_id, when=None, lic=None):
        pl = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": req["license_id"], "machine": req["machine"],
              "nonce": req["nonce"], "status": status, "reason": reason, "checked_at": utc(when)}
        if lic is not None:
            pl["license"] = lic
        return S.dump_document(S.sign_document(S.FORMAT_VERDICT, pl, key, key_id))

    ra, rb = reqs["FM-T135-OLD"], reqs["FM-T135-NEW"]
    p = svc.apply_verdict(verdict(ra, "revoked", "refund", K_OLD, "t-site-old"))
    row = {r["license_id"]: r for r in svc.public_list()}["FM-T135-OLD"]
    check("D1. «аннулирована» прежним ключом принята и показана", p["status"] == "revoked" and row["service_state"] == "revoked",
          row.get("service_state"))
    reqs2 = {r["license_id"]: r for r in svc.take_due({"inventory": "1.7.41"}, "Beta 3.71", force=True)}
    ra2 = reqs2.get("FM-T135-OLD") or ra
    rb = reqs2.get("FM-T135-NEW") or rb      # вторая отметка дала новое случайное число и по этой лицензии
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5)
    check("D2. поддельный «ok» (чужая подпись под прежним key_id) отклонён",
          code_of(lambda: svc.apply_verdict(verdict(ra2, "ok", "", K_FAKE, "t-site-old", later))) == S.R_BAD_SIGNATURE)
    check("D3. «ok» незнакомым ключом отклонён",
          code_of(lambda: svc.apply_verdict(verdict(ra2, "ok", "", K_FAKE, "t-site-unknown", later))) == S.R_UNKNOWN_KEY)
    svc.note_failure("FM-T135-OLD", "network")
    row = {r["license_id"]: r for r in svc.public_list()}["FM-T135-OLD"]
    check("D4. после отказов и сетевого сбоя отзыв на месте, права не вернулись", row["service_state"] == "revoked",
          row.get("service_state"))
    svc2 = SV.LicenseService(os.path.join(TMP, "data"), trusted=TRUST)
    row = {r["license_id"]: r for r in svc2.public_list()}["FM-T135-OLD"]
    check("D5. после перезапуска отзыв сохранён", row["service_state"] == "revoked", row.get("service_state"))
    bad_renew = license_doc("FM-T135-NEW", K_FAKE, "t-site-new", grants=("cost", "inventory"))
    check("D6. ответ с вложенной лицензией с чужой подписью отклонён целиком",
          code_of(lambda: svc2.apply_verdict(verdict(rb, "ok", "", K_NEW, "t-site-new", lic=S.load_document(bad_renew))))
          == SV.R_VERDICT_BAD_LICENSE)
    p = svc2.apply_verdict(verdict(rb, "ok", "", K_NEW, "t-site-new"))
    row = {r["license_id"]: r for r in svc2.public_list()}["FM-T135-NEW"]
    grants = sorted(g["module_id"] for g in row.get("grants") or [])
    check("D7. ответ постоянным ключом для лицензии постоянного ключа принят, состав лицензии прежний",
          p["status"] == "ok" and row["service_state"] == "ok" and grants == ["cost"], (row.get("service_state"), grants))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\nИТОГО: PASS=%d FAIL=%d" % (PASS[0], len(FAIL)))
sys.exit(1 if FAIL else 0)
