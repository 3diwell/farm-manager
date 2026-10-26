# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Сводка платного модуля при нескольких лицензиях (24.10.2026, замечание сайта по пилоту).

ЗАЧЕМ. К оплаченной лицензии «Расчёта заказа» (бессрочно, обновления до 19.10.2028) добавили временную
(пользование и обновления до 20.11.2026). Строка модуля под списком лицензий стала показывать «обновления до
20.11.2026» — будто временная лицензия сократила оплаченный срок. Причина: сводку брали из той лицензии, что
best_decision нашёл ПЕРВОЙ. Теперь сводка — по всем лицензиям, каждая из которых сама даёт право на этот
выпуск сейчас; остановленные и аннулированные службой, истёкшие и неподходящие в счёт не идут.

  A. оба порядка добавления: бессрочно, обновления до 19.10.2028; у каждой лицензии в списке — свои сроки;
  B. после перезапуска (новая служба на тех же файлах) — то же;
  C. временная истекла — сводка по оплаченной, право есть;
  D. оплаченную служба остановила / аннулировала — сводка только по временной (пользование до 20.11.2026);
     временная истекла и оплаченная остановлена — права нет, сроков в сводке нет;
  E. выпуск после «обновления до» временной, но до оплаченной — право по оплаченной, сводка по ней;
  F. лицензия другого модуля или другой редакции в сводку не попадает.

Запуск: python tools/test_licensing_module_summary.py   (0 = все проверки пройдены)
"""
import datetime
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app.licensing import fm_license_sdk as S  # noqa: E402
from app.licensing import package as P  # noqa: E402
from app.licensing import service as SV  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

_pass, _fail = [0], []


def check(name, cond, extra=""):
    if cond:
        _pass[0] += 1
        print("PASS — " + name)
    else:
        _fail.append(name)
        print("FAIL — " + name + (("  :: " + repr(extra)[:700]) if extra != "" else ""))


LK = Ed25519PrivateKey.generate()
KEY_ID = "t-lic-summary"
TRUSTED = S.trusted_set([{"key_id": KEY_ID, "purpose": "license", "test": True, "label": "t",
                          "public_key": S.b64u_encode(LK.public_key().public_bytes(serialization.Encoding.Raw,
                                                                                   serialization.PublicFormat.Raw))}])
M1 = "a" * 64


def utc(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def lic(license_id, use_type="perpetual", updates="2028-10-19T00:00:00Z", until=None, module="cost", edition="standard"):
    body = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": license_id,
            "grants": [{"module_id": module, "edition": edition, "features": ["*"]}],
            "use_type": use_type, "updates_before": updates, "issued_at": "2026-10-19T10:00:00Z"}
    if use_type == "term":
        body.update({"use_valid_from": "2026-10-20T00:00:00Z", "use_valid_until": until})
    return S.dump_document(S.sign_document(S.FORMAT_LICENSE, body, LK, KEY_ID))


def pkg(released="2026-10-18T00:00:00Z", module="cost"):
    return {"state": P.STATE_VERIFIED, "payload": {"module_id": module, "edition": "standard", "version": "0.2.5",
                                                   "channel": "stable", "released_at": released,
                                                   "licensing": {"model": "paid"}}}


PAID = lic("FM-P104", updates="2028-10-19T00:00:00Z")
TEMP = lic("FM-M113", use_type="term", updates="2026-11-20T00:00:00Z", until="2026-11-20T00:00:00Z")
NOW = utc("2026-10-24T12:00:00Z")
AFTER_TEMP = utc("2026-11-25T12:00:00Z")
TMPS = []


def service(order):
    d = tempfile.mkdtemp(prefix="fm_lic_summary_")
    TMPS.append(d)
    s = SV.LicenseService(d, trusted=TRUSTED)
    s.store.machine = lambda components=None: M1
    s.give_consent()
    for raw in order:
        s.import_document(raw)
    return s, d


def reopen(d):
    s = SV.LicenseService(d, trusted=TRUSTED)
    s.store.machine = lambda components=None: M1
    return s


def stop(s, license_id, status="stop", reason="seat_taken"):
    """Подписанный ответ службы «остановить/аннулировать» для этого компьютера — как его принимает программа."""
    req = [r for r in s.take_due({"cost": "0.2.5"}, "Alpha 3.0", force=True) if r["license_id"] == license_id][0]
    v = S.sign_document(S.FORMAT_VERDICT, {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": license_id,
                                           "machine": M1, "nonce": req["nonce"], "status": status, "reason": reason,
                                           "checked_at": S.format_utc(datetime.datetime.now(datetime.timezone.utc))},
                        LK, KEY_ID)
    s.apply_verdict(S.dump_document(v))


def summary(s, now=NOW, p=None):
    st = s.module_status("cost", p or pkg(), now=now)
    return {k: st.get(k) for k in ("license", "use_type", "updates_before", "use_valid_until", "license_ids")}


WANT_PAID = {"license": SV.LICENSE_OK, "use_type": "perpetual", "updates_before": "2028-10-19T00:00:00Z"}


def is_paid_summary(x):
    return all(x.get(k) == v for k, v in WANT_PAID.items()) and not x.get("use_valid_until")


try:
    print("--- A/B. оба порядка добавления, перезапуск ---")
    for name, order in (("сначала оплаченная", (PAID, TEMP)), ("сначала временная", (TEMP, PAID))):
        s, d = service(order)
        x = summary(s)
        check("A. %s: сводка — бессрочно, обновления до 19.10.2028 (обе лицензии в счёте)" % name,
              is_paid_summary(x) and x.get("license_ids") == ["FM-M113", "FM-P104"], x)
        rows = {r["license_id"]: r for r in s.public_list()}
        check("A. %s: в списке у каждой лицензии свои сроки (временная — до 20.11.2026, оплаченная — до 19.10.2028)" % name,
              rows["FM-M113"]["updates_before"] == "2026-11-20T00:00:00Z" and rows["FM-M113"]["use_valid_until"] == "2026-11-20T00:00:00Z"
              and rows["FM-P104"]["updates_before"] == "2028-10-19T00:00:00Z" and rows["FM-P104"]["use_type"] == "perpetual", rows)
        x2 = summary(reopen(d))
        check("B. %s: после перезапуска сводка та же" % name, is_paid_summary(x2), x2)

    print("\n--- C. временная истекла ---")
    s, d = service((TEMP, PAID))
    x = summary(s, now=AFTER_TEMP)
    check("C1. временная истекла — право есть, сводка по оплаченной (бессрочно, до 19.10.2028)",
          is_paid_summary(x) and x.get("license_ids") == ["FM-P104"], x)

    print("\n--- D. ответы службы ---")
    s, d = service((PAID, TEMP))
    stop(s, "FM-P104")
    x = summary(s)
    check("D1. оплаченную служба остановила — сводка только по временной: пользование и обновления до 20.11.2026",
          x.get("license") == SV.LICENSE_OK and x.get("use_type") == "term" and x.get("use_valid_until") == "2026-11-20T00:00:00Z"
          and x.get("updates_before") == "2026-11-20T00:00:00Z" and x.get("license_ids") == ["FM-M113"], x)
    x = summary(s, now=AFTER_TEMP)
    check("D2. и временная истекла — права нет, «действует» и сводных сроков оплаченной нет",
          x.get("license") != SV.LICENSE_OK and not x.get("license_ids"), x)
    s, d = service((TEMP, PAID))
    stop(s, "FM-P104", status="revoked", reason="refund")
    x = summary(s)
    check("D3. оплаченная аннулирована — в сводке её срока нет (только временная)",
          x.get("license") == SV.LICENSE_OK and x.get("updates_before") == "2026-11-20T00:00:00Z" and x.get("license_ids") == ["FM-M113"], x)

    print("\n--- E. более поздний выпуск ---")
    s, d = service((TEMP, PAID))
    x = summary(s, p=pkg(released="2026-12-01T00:00:00Z"))
    check("E1. выпуск после «обновления до» временной — право по оплаченной, сводка по ней", is_paid_summary(x)
          and x.get("license_ids") == ["FM-P104"], x)
    x = summary(s, p=pkg(released="2028-10-19T00:00:00Z"))
    check("E2. выпуск ровно на границе оплаченной — не покрыт (сроков «действует» нет)",
          x.get("license") == S.R_UPDATE_NOT_COVERED and not x.get("license_ids"), x)

    print("\n--- F. чужой модуль и редакция ---")
    OTHER = lic("FM-INV", updates="2030-01-01T00:00:00Z", module="inventory")
    PRO = lic("FM-PRO", updates="2031-01-01T00:00:00Z", edition="pro")
    s, d = service((OTHER, PRO, TEMP, PAID))
    x = summary(s)
    check("F1. лицензии другого модуля и другой редакции с более поздними датами в сводку не попадают",
          is_paid_summary(x) and x.get("license_ids") == ["FM-M113", "FM-P104"], x)
finally:
    for d in TMPS:
        shutil.rmtree(d, ignore_errors=True)

print()
print("=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("   - " + f)
sys.exit(1 if _fail else 0)
