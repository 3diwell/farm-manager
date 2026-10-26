# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Платные модули, «вариант 3» (10.10.2026): ключ текстом, номер компьютера, ответ службы лицензий.

ЗАЧЕМ. Покупатель вставляет ключ из письма — модуль работает сразу и без интернета. Когда есть
связь, программа сообщает службе лицензий «этот ключ стоит на компьютере № …»; служба отвечает
подписанным fm-verdict: «работает», «остановить» (ключ на другом компьютере, перенесён,
заблокирован) или «аннулирована». Здесь — детали, которых не покрывает сквозной набор
tools/test_licensing_process.py (там — настоящий процесс программы и подставная служба):

  A. ключ текстом: туда и обратно, переносы строк из письма, подделка, мусор, «бомба» сжатия;
  B. ответ службы: строгая схема, чужой ключ, ключ пакетов вместо ключа лицензий;
  C. решение «можно ли платное» с учётом ответов: только для ЭТОГО компьютера и по последнему;
  D. номер компьютера: решает плата — переустановка Windows и замена диска не меняют номер, копия
     диска на другой плате даёт новый; одна неудачная загрузка состояние не портит;
  E. служба ядра: согласие, продление не затирается старым ключом, отметка без лишних данных,
     новое случайное число в каждой отметке и без повтора до срока (11.10.2026, стенд 043), ответ
     только на свою последнюю отметку, продление в ответе, удаление лицензии убирает её ответы.

Запуск: python tools/test_licensing_variant3.py   (0 = все проверки пройдены)
"""
import json
import os
import re
import shutil
import sys
import tempfile
import zlib

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app.licensing import fm_license_sdk as S  # noqa: E402
from app.licensing import service as SV  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

SENTINEL = "LICENSING_VARIANT3_SENTINEL_1010"
_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:600]) if detail else ""))


def pub(k):
    return S.b64u_encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


LK, PK, XK = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
TRUSTED = S.trusted_set([{"key_id": "t-lic", "purpose": "license", "public_key": pub(LK)},
                         {"key_id": "t-pkg", "purpose": "package", "public_key": pub(PK)}])
LIC_KEYS = {k: v for k, v in TRUSTED.items() if v.purpose == S.PURPOSE_LICENSE}


def lic(license_id="L-1", issued="2026-10-10T00:00:00Z", updates="2027-10-11T00:00:00Z", key=LK, key_id="t-lic"):
    return S.sign_document(S.FORMAT_LICENSE, {
        "schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": license_id,
        "grants": [{"module_id": "inventory", "edition": "standard", "features": ["*"]}],
        "use_type": "perpetual", "updates_before": updates, "issued_at": issued}, key, key_id)


def verdict(machine, nonce, status="ok", reason="", at="2026-10-10T12:00:00Z", license_id="L-1", key=LK, key_id="t-lic", **extra):
    pl = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": license_id, "machine": machine, "nonce": nonce,
          "status": status, "reason": reason, "checked_at": at}
    pl.update(extra)
    return S.sign_document(S.FORMAT_VERDICT, pl, key, key_id)


def code_of(fn):
    try:
        fn()
        return "ok"
    except S.Rejected as e:
        return e.code


RELEASE = {"module_id": "inventory", "edition": "standard", "version": "1.7.38", "channel": "stable",
           "released_at": "2026-10-10T00:00:00Z"}
M1, M2 = "a" * 64, "b" * 64

# ════════════════════════════════════════════════════════════════════════════
print("\n--- A. ключ текстом ---")
doc = lic()
key = S.encode_key(doc)
check("A1. ключ начинается с FMK1., только латиница/цифры/«-_.» и короче 1500 знаков",
      key.startswith("FMK1.") and re.fullmatch(r"FMK1\.[A-Za-z0-9_-]+", key) and len(key) < 1500, (len(key), key[:40]))
check("A2. ключ -> тот же документ, подпись сходится", S.verify_license(S.decode_key(key), LIC_KEYS)["license_id"] == "L-1")
wrapped = "\n".join(key[i:i + 60] for i in range(0, len(key), 60)) + "  \n"
check("A3. ключ, разбитый письмом на строки и с пробелами, принимается", S.verify_license(S.decode_key(wrapped), LIC_KEYS)["license_id"] == "L-1")
forged = S.encode_key(lic(key=XK))
check("A4. ключ, подписанный чужим ключом, не принимается", code_of(lambda: S.verify_license(S.decode_key(forged), LIC_KEYS)) == S.R_BAD_SIGNATURE)
check("A5. не ключ — «не тот формат»; испорченный хвост — «повреждён»",
      code_of(lambda: S.decode_key("ABC.123")) == S.R_WRONG_FORMAT and code_of(lambda: S.decode_key(key[:-12])) == S.R_MALFORMED)
bomb = "FMK1." + S.b64u_encode(zlib.compress(b" " * (S.MAX_DOCUMENT_BYTES * 4), 9))
check("A6. «бомба» сжатия (ключ, раздувающийся больше предела) отклоняется, а не распаковывается целиком",
      code_of(lambda: S.decode_key(bomb)) == S.R_MALFORMED)
check("A7. доказательство владения — sha256 строки подписи; у ключа и файла одно и то же",
      S.license_proof(doc) == S.license_proof(S.decode_key(key)) and re.fullmatch(r"[0-9a-f]{64}", S.license_proof(doc)))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- B. ответ службы лицензий ---")
n = S.new_nonce()
check("B1. верный ответ принимается", S.verify_verdict(verdict(M1, n), LIC_KEYS)["status"] == "ok")
check("B2. «работает» с причиной, незнакомое состояние, лишнее поле — отказ",
      code_of(lambda: S.verify_verdict(verdict(M1, n, "ok", "seat_taken"), LIC_KEYS)) == S.R_BAD_VALUE
      and code_of(lambda: S.verify_verdict(verdict(M1, n, "maybe"), LIC_KEYS)) == S.R_BAD_VALUE
      and code_of(lambda: S.verify_verdict(verdict(M1, n, extra_field="x"), LIC_KEYS)) == S.R_UNKNOWN_FIELD)
check("B3. новая причина «остановить», о которой программа ещё не знает, принимается (сайт может добавить)",
      S.verify_verdict(verdict(M1, n, "stop", "fraud_review"), LIC_KEYS)["reason"] == "fraud_review")
check("B4. ответ, подписанный ключом ПАКЕТОВ или чужим, не принимается",
      code_of(lambda: S.verify_verdict(verdict(M1, n, key=PK, key_id="t-pkg"), TRUSTED)) == S.R_UNKNOWN_KEY
      and code_of(lambda: S.verify_verdict(verdict(M1, n, key=XK), LIC_KEYS)) == S.R_BAD_SIGNATURE)
check("B5. подпись лицензии не выдать за подпись ответа (разные области подписи)",
      code_of(lambda: S.verify_verdict(dict(doc, format=S.FORMAT_VERDICT), LIC_KEYS)) in (S.R_BAD_SIGNATURE, S.R_MISSING_FIELD, S.R_UNKNOWN_FIELD))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- C. решение с учётом ответов ---")
L1 = S.verify_license(doc, LIC_KEYS)
V = lambda *a, **k: S.verify_verdict(verdict(*a, **k), LIC_KEYS)  # noqa: E731
bd = lambda vs, m: S.best_decision([L1], "inventory", edition="standard", release=RELEASE, verdicts=vs, machine=m)  # noqa: E731
check("C1. ответов нет — лицензия работает (ферма без интернета)", bd([], M1).ok)
check("C2. «остановить» для ЭТОГО компьютера — платное закрыто, причина видна",
      (lambda d: not d.ok and d.code == S.R_LICENSE_STOPPED and d.detail == "seat_taken")(bd([V(M1, n, "stop", "seat_taken")], M1)))
check("C3. «остановить» для ДРУГОГО компьютера этот не трогает", bd([V(M2, n, "stop", "seat_taken")], M1).ok)
check("C4. решает последний ответ: «работает» после «остановить» (перенос подтверждён) — открыто",
      bd([V(M1, n, "stop", "seat_taken", at="2026-10-10T12:00:00Z"), V(M1, n, "ok", at="2026-10-11T12:00:00Z")], M1).ok)
check("C5. «аннулирована» закрывает", bd([V(M1, n, "revoked", "refunded")], M1).code == S.R_LICENSE_REVOKED)
check("C6. номер компьютера не прочитан (пусто) — ответы не применяются, лицензия работает",
      bd([V(M1, n, "stop", "seat_taken")], "").ok)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- D. номер компьютера ---")
real = S.machine_components()
check("D1. на этом компьютере прочитаны все три части (номер Windows, плата, системный диск) — только свёртки",
      sorted(real) == ["board", "disk", "os"] and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in real.values()), sorted(real))
comps = {"os": "1" * 64, "board": "2" * 64, "disk": "3" * 64}
fp, st = S.machine_identity(None, comps)
check("D2. номер — 64 hex, короткий — XXXX-XXXX", re.fullmatch(r"[0-9a-f]{64}", fp) and re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}", S.short_number(fp)))
fp1, st1 = S.machine_identity(st, dict(comps, disk="4" * 64))
check("D3. заменили диск — тот же компьютер", fp1 == fp)
fp2, _ = S.machine_identity(st1, dict(comps, disk="9" * 64, os="5" * 64))
check("D4. переустановили Windows с форматированием (сменились и номер Windows, и том) — тот же компьютер: плата та же", fp2 == fp)
fp3, _ = S.machine_identity(st, dict(comps, board="8" * 64))
check("D5. КОПИЯ системного диска со всей папкой данных на другом компьютере (номер Windows и том те же, плата другая) — новый номер",
      fp3 != fp and fp3)
check("D6. ни одна часть не прочитана — номера нет", S.machine_identity(None, {})[0] == "")
nb = {"os": "1" * 64, "disk": "3" * 64}
fpn, stn = S.machine_identity(None, nb)
check("D7. плата не читается: тот же компьютер, только если совпали обе другие части",
      S.machine_identity(stn, dict(nb))[0] == fpn and S.machine_identity(stn, dict(nb, os="6" * 64))[0] != fpn)
fpb, stb = S.machine_identity(st, {"disk": "3" * 64})
check("D8. одна неудачная загрузка (прочитана одна часть) — прежний номер, сохранённое состояние не испорчено",
      fpb == fp and stb == st)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- E. служба лицензий ядра ---")
TMP = tempfile.mkdtemp(prefix="fm_lic_v3_")
svc = SV.LicenseService(TMP, trusted=TRUSTED)
svc.store.machine = lambda components=None: M1      # номер компьютера в проверке — подставной
check("E1. без согласия отметок нет", svc.take_due({"inventory": "1.7.38"}, "Alpha 3.0") == [] and not svc.consent_given())
kind, p = svc.import_any(S.encode_key(lic(issued="2026-10-10T00:00:00Z", updates="2027-10-11T00:00:00Z")))
check("E2. ключ текстом принят как лицензия", kind == "license" and p["license_id"] == "L-1")
svc.import_any(json.dumps(lic(issued="2027-10-01T00:00:00Z", updates="2028-10-11T00:00:00Z")))
svc.import_any(S.encode_key(lic(issued="2026-10-10T00:00:00Z", updates="2027-10-11T00:00:00Z")))
check("E3. продление сохранено, а старый ключ из старого письма его не затёр",
      [x["updates_before"] for x in svc.valid_payloads()] == ["2028-10-11T00:00:00Z"])
svc.give_consent()
r1 = svc.take_due({"inventory": "1.7.38"}, "Alpha 3.0")
r1b = svc.take_due({"inventory": "1.7.38"}, "Alpha 3.0")
check("E4. отметка: ровно разрешённые поля, номер компьютера, модуль и версии; повторно до срока не отдаётся",
      len(r1) == 1 and set(r1[0]) == {"schema_version", "product_id", "license_id", "proof", "machine", "module_id",
                                     "module_version", "fm_version", "nonce", "via"}
      and r1[0]["machine"] == M1 and r1[0]["module_version"] == "1.7.38" and r1b == [], (r1, r1b))
check("E5. чужой компьютер, чужое число, неизвестная лицензия — ответ не принят",
      code_of(lambda: svc.apply_verdict(verdict(M2, r1[0]["nonce"]))) == SV.R_VERDICT_FOREIGN
      and code_of(lambda: svc.apply_verdict(verdict(M1, S.new_nonce()))) == SV.R_VERDICT_STALE
      and code_of(lambda: svc.apply_verdict(verdict(M1, r1[0]["nonce"], license_id="L-9"))) == SV.R_VERDICT_UNKNOWN)
renew = lic(issued="2027-12-01T00:00:00Z", updates="2029-10-11T00:00:00Z")
svc.apply_verdict(verdict(M1, r1[0]["nonce"], "stop", "seat_taken", at="2026-10-10T12:00:00Z", license=renew))
row = svc.public_list()[0]
check("E6. «остановить» сохранён: в окне лицензии «остановлена, ключ на другом компьютере»; продление из ответа принято",
      row.get("service_state") == "stop" and row.get("service_reason") == "seat_taken"
      and row.get("updates_before") == "2029-10-11T00:00:00Z", row)
r2 = svc.take_due({"inventory": "1.7.38"}, "Alpha 3.0", force=True)
check("E7. после ответа — новое случайное число; повтор прежнего ответа не принимается",
      r2[0]["nonce"] != r1[0]["nonce"]
      and code_of(lambda: svc.apply_verdict(verdict(M1, r1[0]["nonce"], "ok", at="2026-10-11T00:00:00Z"))) == SV.R_VERDICT_STALE)
check("E8. ответ СТАРШЕ сохранённого (подложили старое «работает») не принимается",
      code_of(lambda: svc.apply_verdict(verdict(M1, r2[0]["nonce"], "ok", at="2026-10-09T00:00:00Z"))) == SV.R_VERDICT_STALE)
svc.apply_verdict(verdict(M1, r2[0]["nonce"], "ok", at="2026-10-11T00:00:00Z"))
check("E9. «работает» (перенос подтверждён) — лицензия снова действует", svc.public_list()[0].get("service_state") == "ok")
r3 = svc.take_due({"inventory": "1.7.38"}, "Alpha 3.0", force=True)
check("E10. ответ с датой намного позже часов компьютера (ошибка часов службы) не принимается",
      code_of(lambda: svc.apply_verdict(verdict(M1, r3[0]["nonce"], "stop", "seat_taken", at="2099-01-01T00:00:00Z"))) == SV.R_VERDICT_FUTURE)
svc.apply_verdict(verdict(M1, r3[0]["nonce"], "revoked", "refunded", at="2026-10-11T00:00:01Z"))
svc.remove("L-1")
check("E11. удаление лицензии убирает ждущую отметку, но НЕ ответ службы",
      os.listdir(os.path.join(TMP, "licenses", "verdicts")) and not svc.store.marks()["pending"])
svc.import_any(json.dumps(lic(issued="2027-12-01T00:00:00Z", updates="2029-10-11T00:00:00Z")))
check("E12. «Удалить» и снова «Добавить» тот же ключ аннулирование не снимает (ферма без интернета)",
      svc.public_list()[0].get("service_state") == "revoked")
io_ = __import__("io")
io_.open(os.path.join(TMP, "licenses", "marks.json"), "w", encoding="utf-8").write('{"pending": [], "answers": {"L-1": "x"}}')
ok_list = True
try:
    svc.public_list()
    svc.take_due({"inventory": "1.7.38"}, "Alpha 3.0", force=True)
except Exception as e:
    ok_list = repr(e)
check("E13. испорченный файл отметок (верный JSON, неверное устройство) не роняет окно лицензий и отметку", ok_list is True, ok_list)
shutil.rmtree(os.path.join(TMP, "licenses", "verdicts"))
io_.open(os.path.join(TMP, "licenses", "verdicts"), "w").write("not a folder")
ok_v = True
try:
    svc.verdict_payloads()
    svc.public_list()
except Exception as e:
    ok_v = repr(e)
check("E14. на месте папки ответов оказался файл — программа не падает", ok_v is True, ok_v)
shutil.rmtree(TMP, ignore_errors=True)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- метка-ловушка ---")
SRC = "".join(open(os.path.join(REPO, "app", "licensing", f), encoding="utf-8").read() for f in os.listdir(os.path.join(REPO, "app", "licensing")) if f.endswith(".py"))
check("K1. метка-ловушка не попала в код лицензирования", SENTINEL not in SRC)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
