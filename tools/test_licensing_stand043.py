# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Платные модули: совместимость со стендом службы лицензий 043 (11.10.2026).

ЗАЧЕМ. Второй разработчик поднял тестовую службу лицензий и прислал комплект: протокол, восемь
тестовых лицензий и порядок приёмки (L01–L10 — локально, H01–H10 — владелец на стенде). Сами
лицензии комплекта приватные и в проект не кладутся: их проверяет инструмент
tools/licensing_test/stand043.py по файлам вне проекта. Здесь — то же поведение на одноразовых
ключах, чтобы набор работал на любом компьютере и без комплекта:

  S. строгий разбор (SDK 1.3): контрольный вектор канонизации, повтор ключа JSON (и записанного
     по-разному), NaN/Infinity/дробные, true вместо 1, подпись не в каноническом base64url, сжатие не
     zlib, оборванный и лишний поток, предел распакованного ключа, повтор прав, алфавит customer_ref,
     версии в отметке по шаблону службы, размер отметки;
  R. расписание отметок: новое случайное число на каждую, без повтора до срока ни напрямую, ни через
     браузер, «подождите» (429/503, Retry-After) — пауза для всех отметок, нет связи — 15 минут, отказ
     — 6 часов; ни одна ошибка связи не меняет права; ответ на прежнюю отметку и на отметку старше
     суток не принимается; продление в ответе — после проверки своей подписью и номером, неверное
     вложение отклоняет весь ответ, старый документ не откатывает новый, сбой записи оставляет прежний;
     17.10.2026 (ответ службы 043): Retry-After дольше суток — как попросила служба (ни один канал не
     отмечается раньше, в том числе после повторного ввода ключа, «Удалить»/«Добавить» и частых открытий
     окна), дата HTTP, часы перевели назад, «нет связи» от браузера — 15 минут, не больше 10 отметок в минуту;
  G. самопроверка в платном модуле (app/licensing/fm_paid_guard.py) на настоящей платной сборке
     склада: без лицензии — отказ, лицензия расчёта склад не открывает, граница обновлений, ответ
     службы для этого компьютера, подмена файла, ядро без паспорта, граница только у изменяющих
     маршрутов, 402 от модуля;
  T. разделение сред: собранная программа тестовые ключи, тестовый адрес службы и «только через
     браузер» не принимает; рабочих ключей в программе нет.

Запуск: python tools/test_licensing_stand043.py   (0 = все проверки пройдены)
"""
import asyncio
import datetime
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
import zlib

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
from app.licensing import fm_license_sdk as S  # noqa: E402
from app.licensing import service as SV  # noqa: E402
from app.licensing import store as ST  # noqa: E402
from app.licensing import trust as TR  # noqa: E402
import module_package as MP  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

SENTINEL = "LICENSING_STAND043_SENTINEL_1110"
_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:600]) if detail else ""))


def code_of(fn):
    try:
        fn()
        return "ok"
    except S.Rejected as e:
        return e.code


def pub(k):
    return S.b64u_encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


LK, PK, XK = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
TRUST = [{"key_id": "t-lic-043", "purpose": "license", "public_key": pub(LK), "label": "t", "test": True},
         {"key_id": "t-pkg-043", "purpose": "package", "public_key": pub(PK), "label": "t", "test": True}]
TRUSTED = S.trusted_set(TRUST)
LIC_KEYS = {k: v for k, v in TRUSTED.items() if v.purpose == S.PURPOSE_LICENSE}
G_INV = {"module_id": "inventory", "edition": "standard", "features": ["*"]}
G_COST = {"module_id": "cost", "edition": "standard", "features": ["*"]}


def lic(license_id="TEST-inventory", grants=(G_INV,), issued="2026-10-11T07:39:46Z", updates="2027-10-12T00:00:00Z",
        key=LK, key_id="t-lic-043", **extra):
    body = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": license_id, "grants": [dict(g) for g in grants],
            "use_type": "perpetual", "updates_before": updates, "issued_at": issued}
    body.update(extra)
    return S.sign_document(S.FORMAT_LICENSE, body, key, key_id)


def verdict(machine, nonce, status="ok", reason="", at=None, license_id="TEST-inventory", key=LK, key_id="t-lic-043", **extra):
    at = at or S.format_utc(datetime.datetime.now(datetime.timezone.utc))
    pl = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": license_id, "machine": machine, "nonce": nonce,
          "status": status, "reason": reason, "checked_at": at}
    pl.update(extra)
    return S.sign_document(S.FORMAT_VERDICT, pl, key, key_id)


def raw_json(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


# ════════════════════════════════════════════════════════════════════════════
print("\n--- S. строгий разбор (SDK 1.3) ---")
VECTOR = {"customer_ref": "C-000001", "grants": [{"edition": "standard", "features": ["*"], "module_id": "inventory"}],
          "issued_at": "2026-10-10T12:00:00Z", "key_id": "3dw-lic-test-1", "license_id": "L-2026-000001",
          "product_id": "3diwell-fm", "schema_version": 1, "updates_before": "2027-10-11T00:00:00Z", "use_type": "perpetual"}
vb = S.signing_input(S.FORMAT_LICENSE, VECTOR)
check("S1. контрольный вектор канонизации (протокол 043): 324 байта, SHA-256 c51f78fc…b075",
      len(vb) == 324 and hashlib.sha256(vb).hexdigest() == "c51f78fcdaaa070a651c767570f8da18e1cc74dd998b78090246523f7a25b075",
      (len(vb), hashlib.sha256(vb).hexdigest()))
doc = lic()
good = raw_json(doc)
check("S2. верная лицензия принимается и файлом, и ключом FMK1 — одинаково",
      S.verify_license(good, LIC_KEYS) == S.verify_license(S.decode_key(S.encode_key(doc)), LIC_KEYS))
dup_top = good[:-1] + ',"v":1}'
dup_payload = good.replace('"product_id":"3diwell-fm"', '"product_id":"3diwell-fm","product_id":"3diwell-fm"', 1)
dup_escaped = good.replace('"use_type":"perpetual"', '"use_type":"perpetual","\\u0075se_type":"perpetual"', 1)
check("S3. повтор ключа JSON — отказ (в оболочке, в данных и записанный по-разному: \"use_type\" и \"\\u0075se_type\")",
      all(code_of(lambda r=r: S.verify_license(r, LIC_KEYS)) == S.R_MALFORMED for r in (dup_top, dup_payload, dup_escaped)),
      [code_of(lambda r=r: S.verify_license(r, LIC_KEYS)) for r in (dup_top, dup_payload, dup_escaped)])
nan_doc = good.replace('"schema_version":1', '"schema_version":NaN', 1)
inf_doc = good.replace('"schema_version":1', '"schema_version":Infinity', 1)
flt = json.loads(good)
flt["payload"]["schema_version"] = 1.0
tru = json.loads(good)
tru["payload"]["schema_version"] = True
check("S4. NaN, Infinity, дробное и true вместо 1 — отказ",
      code_of(lambda: S.verify_license(nan_doc, LIC_KEYS)) == S.R_MALFORMED
      and code_of(lambda: S.verify_license(inf_doc, LIC_KEYS)) == S.R_MALFORMED
      and code_of(lambda: S.verify_license(flt, LIC_KEYS)) != "ok" and code_of(lambda: S.verify_license(tru, LIC_KEYS)) != "ok",
      [code_of(lambda: S.verify_license(x, LIC_KEYS)) for x in (nan_doc, inf_doc, flt, tru)])
sv = doc["sig"]["value"]
_last = S.b64u_decode(sv)
padded = json.loads(good)
padded["sig"]["value"] = sv + "=="
alt = json.loads(good)
_alph = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
alt["sig"]["value"] = sv[:-1] + _alph[_alph.index(sv[-1]) ^ 1]       # те же 64 байта, другая запись хвостовых битов
check("S5. подпись с «=» на конце и неканоническая запись тех же байтов — отказ; каноническая — принимается",
      code_of(lambda: S.verify_license(padded, LIC_KEYS)) == S.R_BAD_SIGNATURE
      and code_of(lambda: S.verify_license(alt, LIC_KEYS)) == S.R_BAD_SIGNATURE and len(sv) == 86,
      (code_of(lambda: S.verify_license(padded, LIC_KEYS)), code_of(lambda: S.verify_license(alt, LIC_KEYS))))
body = S.canonical_bytes(S.load_document(doc))
k_gzip = "FMK1." + S.b64u_encode(gzip.compress(body))
_co = zlib.compressobj(9, zlib.DEFLATED, -15)
k_raw = "FMK1." + S.b64u_encode(_co.compress(body) + _co.flush())
_z = zlib.compress(body, 9)
k_cut = "FMK1." + S.b64u_encode(_z[:-6])
k_tail = "FMK1." + S.b64u_encode(_z + b"\x00junk")
k_two = "FMK1." + S.b64u_encode(_z + _z)
k_big = "FMK1." + S.b64u_encode(zlib.compress(b"{" + b" " * (S.MAX_KEY_DOCUMENT_BYTES + 10) + b"}", 9))
check("S6. ключ: gzip, «голый» deflate, оборванный поток, данные после конца, два потока подряд и распаковка сверх 64 КиБ — отказ",
      all(code_of(lambda k=k: S.decode_key(k)) == S.R_MALFORMED for k in (k_gzip, k_raw, k_cut, k_tail, k_two, k_big)),
      [code_of(lambda k=k: S.decode_key(k)) for k in (k_gzip, k_raw, k_cut, k_tail, k_two, k_big)])
check("S7. два одинаковых права в лицензии — отказ; customer_ref только из букв, цифр и «_.-»",
      code_of(lambda: S.verify_license(lic(grants=(G_INV, G_INV)), LIC_KEYS)) == S.R_BAD_VALUE
      and code_of(lambda: S.verify_license(lic(customer_ref="Иванов И."), LIC_KEYS)) == S.R_BAD_VALUE
      and code_of(lambda: S.verify_license(lic(customer_ref="C-000001"), LIC_KEYS)) == "ok")
extra_top = dict(json.loads(good), extra=1)
miss = json.loads(good)
del miss["payload"]["issued_at"]
check("S8. лишнее поле, недостающее поле, неизвестный ключ, чужой продукт, несуществующая дата — отказ",
      code_of(lambda: S.verify_license(extra_top, LIC_KEYS)) == S.R_MALFORMED
      and code_of(lambda: S.verify_license(miss, LIC_KEYS)) != "ok"
      and code_of(lambda: S.verify_license(lic(key_id="t-unknown"), LIC_KEYS)) == S.R_UNKNOWN_KEY
      and code_of(lambda: S.verify_license(lic(product_id="other"), LIC_KEYS)) == S.R_WRONG_PRODUCT
      and code_of(lambda: S.verify_license(lic(updates="2027-02-30T00:00:00Z"), LIC_KEYS)) == S.R_BAD_VALUE)
check("S9. версия в отметке — по шаблону службы: «Alpha 3.0» как есть, пустая — «0», посторонние знаки убраны",
      S.wire_version("Alpha 3.0") == "Alpha 3.0" and S.wire_version("") == "0" and S.wire_version("1.7.39") == "1.7.39"
      and S.wire_version("-β1.2") == "1.2" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.+()/\-]{0,63}", S.wire_version("x" * 90)))
sur = good.replace('"use_type":"perpetual"', '"use_type":"perpetual\\ud800"', 1)
check("S11. одиночный суррогат («\\ud800») в документе — чистый отказ «malformed», а не падение программы",
      code_of(lambda: S.verify_license(sur, LIC_KEYS)) == S.R_MALFORMED, code_of(lambda: S.verify_license(sur, LIC_KEYS)))
M1, M2 = "a" * 64, "b" * 64
rq = S.mark_request(doc, M1, "inventory", "", "Alpha 3.0", S.new_nonce())
check("S10. отметка: ровно 10 полей, все строки кроме schema_version, proof и machine — 64 hex, nonce — 32 hex, тело < 4096 байт",
      set(rq) == {"schema_version", "product_id", "license_id", "proof", "machine", "module_id", "module_version",
                  "fm_version", "nonce", "via"} and rq["schema_version"] == 1
      and all(isinstance(v, str) for k, v in rq.items() if k != "schema_version")
      and re.fullmatch(r"[0-9a-f]{64}", rq["proof"]) and re.fullmatch(r"[0-9a-f]{32}", rq["nonce"])
      and rq["module_version"] == "0" and len(json.dumps(rq).encode("utf-8")) < 4096
      and rq["proof"] == hashlib.sha256(doc["sig"]["value"].encode("ascii")).hexdigest(), rq)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- R. расписание отметок и ответы службы ---")
TMP = tempfile.mkdtemp(prefix="fm_lic_043_")
svc = SV.LicenseService(TMP, trusted=TRUSTED)
svc.store.machine = lambda components=None: M1
svc.give_consent()
NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
at = lambda s: NOW + datetime.timedelta(seconds=s)  # noqa: E731
INST = {"inventory": "1.7.39", "cost": "0.2.3"}
svc.import_any(S.encode_key(lic()))
svc.import_any(raw_json(lic("TEST-both", grants=(G_INV, G_COST))))
r1 = svc.take_due(INST, "Alpha 3.0", now=NOW)
r1b = svc.take_due(INST, "Alpha 3.0", now=at(60))
check("R1. одна отметка на лицензию (модули одной лицензии — одно место); сразу повторно — ничего",
      sorted(x["license_id"] for x in r1) == ["TEST-both", "TEST-inventory"] and r1b == [], (r1, r1b))
check("R2. нет связи — через 15 минут снова, и с НОВЫМ случайным числом",
      svc.take_due(INST, "Alpha 3.0", now=at(14 * 60)) == []
      and (lambda r: len(r) == 2 and {x["nonce"] for x in r}.isdisjoint({x["nonce"] for x in r1}))(
          svc.take_due(INST, "Alpha 3.0", now=at(15 * 60 + 1))))
svc.note_failure("TEST-inventory", 429, "120", now=at(16 * 60))
check("R3. «слишком часто» (429, Retry-After 120): пауза для ВСЕХ отметок обоих каналов на 2 минуты",
      svc.take_due(INST, "Alpha 3.0", now=at(16 * 60 + 119), force=False) == []
      and svc.take_due(INST, "Alpha 3.0", via="browser", now=at(16 * 60 + 119)) == []
      and svc.store.marks()["backoff_until"] == S.format_utc(at(16 * 60 + 120)))
r3 = svc.take_due(INST, "Alpha 3.0", via="browser", now=at(31 * 60 + 2))
check("R4. после паузы отметки отданы браузеру (via=browser); прямой канал их 15 минут не повторяет",
      len(r3) == 2 and all(x["via"] == "browser" for x in r3) and svc.take_due(INST, "Alpha 3.0", now=at(31 * 60 + 300)) == []
      and svc.take_due(INST, "Alpha 3.0", now=at(31 * 60 + 2 + 15 * 60 - 1)) == [], r3)


def backoff_for(outcome, ra):
    t = tempfile.mkdtemp(prefix="fm_lic_043b_")
    s2 = SV.LicenseService(t, trusted=TRUSTED)
    s2.note_failure("X-1", outcome, ra, now=NOW)
    b = s2.store.marks()["backoff_until"]
    shutil.rmtree(t, ignore_errors=True)
    return (S.parse_utc(b, "b") - NOW).total_seconds() if b else None


_R5 = [(429, None, 900), (503, "", 300), (503, "abc", 300), (429, "0", 900), (429, "-5", 900), (429, "1.5", 900),
       (429, "1", 30), (429, " 120 ", 120), (429, str(7 * 86400), 7 * 86400), (429, str(10 ** 9), 365 * 86400),
       (429, "9" * 40, 365 * 86400)]
_r5 = [(o, ra, backoff_for(o, ra), want) for o, ra, want in _R5]
#  17.10.2026 (ответ службы 043): Retry-After дольше суток соблюдается как есть — прежний предел «сутки» снят.
check("R5. Retry-After секундами: нет, мусор, «0» — 15 мин (429) / 5 мин (503); 1 с — 30 с; неделя — неделя "
      "(НЕ сокращается до суток); сотни лет — год (защита от явной ошибки)",
      all(got == want for _o, _ra, got, want in _r5), [x for x in _r5 if x[2] != x[3]])
_EN_DAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_EN_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def http_dates(dt):
    """Три вида даты HTTP (RFC 9110, 5.6.7) для одного момента: IMF-fixdate, rfc850, asctime."""
    d, m = _EN_DAY[dt.weekday()], _EN_MON[dt.month - 1]
    return ("%s, %02d %s %04d %02d:%02d:%02d GMT" % (d[:3], dt.day, m, dt.year, dt.hour, dt.minute, dt.second),
            "%s, %02d-%s-%02d %02d:%02d:%02d GMT" % (d, dt.day, m, dt.year % 100, dt.hour, dt.minute, dt.second),
            "%s %s %2d %02d:%02d:%02d %04d" % (d[:3], m, dt.day, dt.hour, dt.minute, dt.second, dt.year))


_hd = [backoff_for(429, h) for h in http_dates(at(2 * 3600))]
_hd3 = backoff_for(503, http_dates(at(3 * 86400))[0])
_hp = backoff_for(429, http_dates(at(-3600))[0])
_hbad = [backoff_for(429, "Wed, 99 Oct 2026 07:28:00 GMT"), backoff_for(503, "Wed, 21 Oct 2026"),
         backoff_for(429, "Wed, 21 Oct 2026 25:61:00 GMT")]
check("R5а. Retry-After датой HTTP (все три вида RFC 9110): через 2 часа — пауза 2 часа; через 3 суток — 3 суток; "
      "дата в прошлом — 30 с; испорченная дата — как «не сказано» (15 / 5 минут)",
      _hd == [7200, 7200, 7200] and _hd3 == 3 * 86400 and _hp == 30 and _hbad == [900, 300, 900],
      (_hd, _hd3, _hp, _hbad, http_dates(at(2 * 3600))))
svc.note_failure("TEST-both", "rejected", now=at(32 * 60))
svc.note_failure("TEST-inventory", "network", now=at(32 * 60))
nx = svc.store.marks()["next"]
check("R6. отказ службы (неизвестная лицензия, неверный запрос) — следующая через 6 часов; нет связи — через 15 минут",
      nx["TEST-both"] == S.format_utc(at(32 * 60 + 6 * 3600)) and nx["TEST-inventory"] == S.format_utc(at(32 * 60 + 15 * 60)), nx)
# ответ на отметку: только на последнюю, только своему компьютеру
rr = svc.take_due(INST, "Alpha 3.0", force=True)
old_nonce = {x["license_id"]: x["nonce"] for x in rr}
rr2 = svc.take_due(INST, "Alpha 3.0", force=True)
new_nonce = {x["license_id"]: x["nonce"] for x in rr2}
check("R7. ответ на ПРЕЖНЮЮ отметку после новой не принимается (H10 в модели)",
      code_of(lambda: svc.apply_verdict(verdict(M1, old_nonce["TEST-inventory"]))) == SV.R_VERDICT_STALE)
svc.apply_verdict(verdict(M1, new_nonce["TEST-inventory"], "stop", "seat_taken"))
check("R8. «остановить» для этого компьютера принят; следующая отметка через 6 часов",
      svc.public_list()[[x["license_id"] for x in svc.public_list()].index("TEST-inventory")]["service_state"] == "stop"
      and svc.store.marks()["next"]["TEST-inventory"] >= S.format_utc(at(6 * 3600 - 120)))
before = sorted(os.listdir(os.path.join(TMP, "licenses", "verdicts")))
svc.note_failure("TEST-inventory", "network")
svc.note_failure("TEST-inventory", 503, "60")
svc.note_failure("TEST-inventory", "rejected")
check("R9. ошибки связи, «подождите» и отказ службы права не меняют: остановка осталась",
      svc.public_list()[[x["license_id"] for x in svc.public_list()].index("TEST-inventory")]["service_state"] == "stop"
      and sorted(os.listdir(os.path.join(TMP, "licenses", "verdicts"))) == before)
# отметка старше суток
mk = svc.store.marks()
mk["pending"]["TEST-both"] = {"nonce": "c" * 32, "created_at": S.format_utc(at(-25 * 3600)), "via": "direct"}
svc.store.save_marks(mk)
check("R10. ответ на отметку старше суток не принимается", code_of(lambda: svc.apply_verdict(
      verdict(M1, "c" * 32, license_id="TEST-both"))) == SV.R_VERDICT_STALE)
# продление в ответе
rb = {x["license_id"]: x["nonce"] for x in svc.take_due(INST, "Alpha 3.0", force=True)}
forged = lic("TEST-both", grants=(G_INV, G_COST), issued="2026-10-12T00:00:00Z", updates="2028-10-12T00:00:00Z", key=XK)
other = lic("TEST-other", grants=(G_INV, G_COST), issued="2026-10-12T00:00:00Z", updates="2028-10-12T00:00:00Z")
lic_file = os.path.join(TMP, "licenses", "TEST-both.fmlic")
h0 = hashlib.sha256(open(lic_file, "rb").read()).hexdigest()
check("R11. вложенная лицензия с чужой подписью или с другим номером — отклонён ВЕСЬ ответ, ничего не записано",
      code_of(lambda: svc.apply_verdict(verdict(M1, rb["TEST-both"], license_id="TEST-both", license=forged))) == SV.R_VERDICT_BAD_LICENSE
      and code_of(lambda: svc.apply_verdict(verdict(M1, rb["TEST-both"], license_id="TEST-both", license=other))) == SV.R_VERDICT_BAD_LICENSE
      and hashlib.sha256(open(lic_file, "rb").read()).hexdigest() == h0
      and not os.path.exists(os.path.join(TMP, "licenses", "verdicts", "TEST-both.json")))
renew = lic("TEST-both", grants=(G_INV, G_COST), issued="2026-10-12T00:00:00Z", updates="2028-10-12T00:00:00Z")
svc.apply_verdict(verdict(M1, rb["TEST-both"], license_id="TEST-both", license=renew))
ub = lambda: next(x["updates_before"] for x in svc.public_list() if x.get("license_id") == "TEST-both")  # noqa: E731
check("R12. продление в ответе принято после проверки своей подписью и номером", ub() == "2028-10-12T00:00:00Z", ub())
svc.import_any(raw_json(lic("TEST-both", grants=(G_INV, G_COST))))
check("R13. старый документ (старое письмо) продление не откатывает; повтор того же — без изменений",
      ub() == "2028-10-12T00:00:00Z" and svc.import_document(renew)["updates_before"] == "2028-10-12T00:00:00Z")
_orig = ST._atomic_write


def _boom(path, data):
    raise OSError("диск недоступен")


ST._atomic_write = _boom
newer = lic("TEST-both", grants=(G_INV, G_COST), issued="2026-10-13T00:00:00Z", updates="2029-10-12T00:00:00Z")
try:
    svc.import_document(newer)
    werr = "no-error"
except OSError:
    werr = "oserror"
ST._atomic_write = _orig
check("R14. сбой записи при продлении: ошибка видна, прежний документ цел и действует",
      werr == "oserror" and ub() == "2028-10-12T00:00:00Z", (werr, ub()))
open(os.path.join(TMP, "licenses", "marks.json"), "w", encoding="utf-8").write(
    '{"pending": {}, "answers": {}, "next": {"TEST-both": "завтра", "x": 5}, "backoff_until": 12}')
m = svc.store.marks()
check("R15. испорченные сроки в файле отметок отбрасываются, а не ломают отметку", m["next"] == {} and m["backoff_until"] == "", m)
prev = svc.preview_requests(INST, "Alpha 3.0")
check("R16. «Что передаётся» показывает отметки и ничего не запоминает", len(prev) == 2 and svc.store.marks()["next"] == {}, prev)
tr = svc.transmitted(INST, "Alpha 3.0")["requests"]
check("R17. на страницу proof уходит только началом (8 знаков и «…»)",
      tr and all(len(r["proof"]) == 9 and r["proof"].endswith("\u2026") for r in tr), [r["proof"] for r in tr])
mk = svc.store.marks()
mk["next"] = {"TEST-both": "2099-01-01T00:00:00Z", "TEST-inventory": "2099-01-01T00:00:00Z"}
mk["backoff_until"], mk["backoff_set_at"], mk["backoff_s"] = "2099-01-01T00:00:00Z", "", 0
svc.store.save_marks(mk)
check("R18. сроки из далёкого будущего без записи, когда и на сколько служба просила подождать (часы переводили "
      "вперёд, файл правили), недействительны — отметки не замолкают",
      len(svc.take_due(INST, "Alpha 3.0")) == 2 and svc.store.marks()["backoff_until"] == "")
mf = os.path.join(TMP, "licenses", "marks.json")
st0 = os.stat(mf).st_mtime_ns
import time as _t  # noqa: E402
_t.sleep(0.05)
svc.take_due(INST, "Alpha 3.0")
check("R19. когда отмечаться не пора, файл отметок не переписывается (окно лицензий открывают часто)",
      os.stat(mf).st_mtime_ns == st0)
lfile = os.path.join(TMP, "licenses", "TEST-both.fmlic")
h1 = hashlib.sha256(open(lfile, "rb").read()).hexdigest()
_open = open


def _locked_open(path, mode="r", *a, **k):
    if os.path.normcase(str(path)) == os.path.normcase(lfile) and "r" in mode:
        raise PermissionError("файл занят")
    return _open(path, mode, *a, **k)


import builtins  # noqa: E402
builtins.open = _locked_open
try:
    rr = code_of(lambda: svc.store.import_document(raw_json(lic("TEST-both", grants=(G_INV, G_COST))), LIC_KEYS))
except OSError:
    rr = "oserror"
finally:
    builtins.open = _open
check("R20. прежний файл лицензии не прочитался (занят) — более старый документ его НЕ затирает",
      rr == "oserror" and hashlib.sha256(open(lfile, "rb").read()).hexdigest() == h1, rr)
open(os.path.join(TMP, "licenses", "ZZ-bad.fmlic"), "w", encoding="utf-8").write(sur)
ok_bad = True
try:
    rows = SV.LicenseService(TMP, trusted=TRUSTED).public_list()
    ok_bad = any(r.get("file") == "ZZ-bad.fmlic" and not r["ok"] for r in rows) and sum(1 for r in rows if r["ok"]) == 2
except Exception as e:
    ok_bad = repr(e)
check("R21. испорченный файл лицензии в папке не роняет окно лицензий и не прячет остальные", ok_bad is True, ok_bad)
shutil.rmtree(TMP, ignore_errors=True)

# ── 17.10.2026 (ответ службы 043): пауза дольше суток, дата HTTP, канал браузера, действия пользователя,
#    не больше 10 отметок в минуту. Каждая проверка — на своей временной папке и своём времени.
D = 86400
_tmps = []


def fresh(n=2):
    t = tempfile.mkdtemp(prefix="fm_lic_043p_")
    _tmps.append(t)
    s = SV.LicenseService(t, trusted=TRUSTED)
    s.store.machine = lambda components=None: M1
    s.give_consent()
    ids = ["TEST-p%02d" % i for i in range(n)]
    for lid in ids:
        s.import_any(raw_json(lic(lid)))
    return s, ids


def due(s, when, via="direct"):
    return sorted(x["license_id"] for x in s.take_due(INST, "Alpha 3.0", via=via, now=when))


def quiet(s, moments):
    """Ни один канал ничего не отдаёт ни в один из моментов."""
    return [(m, v) for m in moments for v in ("direct", "browser") if due(s, m, v)]


s1, ids1 = fresh()
s1.note_failure(ids1[0], 429, str(3 * D), now=NOW)
mk1 = s1.store.marks()
q1 = quiet(s1, (at(60), at(D), at(2 * D), at(3 * D - 1)))
check("R22. КРИТИЧНО: служба попросила подождать 3 суток (Retry-After напрямую) — ни прямой канал, ни браузер не "
      "отметятся ни через сутки, ни за секунду до срока; запись паузы — «когда и на сколько»; после срока — обе отметки",
      mk1["backoff_until"] == S.format_utc(at(3 * D)) and mk1["backoff_s"] == 3 * D
      and mk1["backoff_set_at"] == S.format_utc(NOW) and not q1 and due(s1, at(3 * D + 1)) == ids1, (mk1, q1))
s2, ids2 = fresh()
o2 = s2.note_relay(ids2[0], "429", str(3 * D), now=NOW)
s3, ids3 = fresh()
o3 = s3.note_relay(ids3[0], "503", http_dates(at(3 * D))[0], now=NOW)
q2 = quiet(s2, (at(D), at(3 * D - 1)))
q3 = quiet(s3, (at(D), at(3 * D - 1)))
check("R22б. то же через браузер (страница передала программе 429 и Retry-After 3 суток секундами, или 503 и дату "
      "HTTP через 3 суток): пауза 3 суток для обоих каналов; окно «Что передаётся» показывает её",
      o2 == 429 and o3 == 503 and not q2 and not q3
      and s2.store.marks()["backoff_until"] == s3.store.marks()["backoff_until"] == S.format_utc(at(3 * D))
      and s2.transmitted(INST, "Alpha 3.0")["backoff_until"] == S.format_utc(at(3 * D)), (o2, o3, q2, q3))
#  Действия пользователя во время паузы: ключ вставлен снова (5 раз), лицензию удалили и добавили, окно
#  лицензий открывали раз за разом (каждый раз — просьба отдать отметки браузеру).
_mid = at(D)
_got = []
for _i in range(5):
    s2.import_any(raw_json(lic(ids2[0])))
    s2.import_any(S.encode_key(lic(ids2[1])))
    _got += due(s2, _mid + datetime.timedelta(seconds=_i), "browser") + due(s2, _mid + datetime.timedelta(seconds=_i))
s2.remove(ids2[1])
s2.import_any(raw_json(lic(ids2[1])))
_got += due(s2, _mid) + due(s2, _mid, "browser")
check("R23. КРИТИЧНО: во время паузы службы повторный ввод ключа, «Удалить» и «Добавить» и частые открытия окна "
      "лицензий (прямой канал и браузер по очереди) не отправляют ни одной отметки и паузу не сокращают; после срока — "
      "ровно по одной отметке на лицензию",
      _got == [] and s2.store.marks()["backoff_until"] == S.format_utc(at(3 * D))
      and due(s2, at(3 * D + 1), "browser") == ids2 and due(s2, at(3 * D + 2)) == [], _got)
s4, ids4 = fresh()
s4.note_failure(ids4[0], 429, str(3 * D), now=NOW)
s4.note_failure(ids4[1], 503, "60", now=at(D))
b4a = s4.store.marks()["backoff_until"]
s4.note_relay(ids4[1], "429", http_dates(at(D + 5 * D))[0], now=at(D))
b4b = s4.store.marks()["backoff_until"]
check("R24. более короткая просьба подождать идущую долгую паузу не сокращает; более длинная — продлевает",
      b4a == S.format_utc(at(3 * D)) and b4b == S.format_utc(at(6 * D)) and not quiet(s4, (at(6 * D - 1),)), (b4a, b4b))
#  17.10.2026 (замечание проверки): часы, отстающие хотя бы на один круг (запуск компьютера до сверки
#  времени, батарейка, ошибка руками), не переписывают паузу. Прежде она пересчитывалась от отстающих часов
#  и записывалась в файл — после поправки часов программа отмечалась через сутки вместо трёх, раньше
#  Retry-After. Теперь конец паузы в файле не сокращается: раньше него не обращается ни один канал.
s5, ids5 = fresh()
s5.note_failure(ids5[0], 429, str(3 * D), now=NOW)
mk5a = s5.store.marks()
q5 = quiet(s5, (at(-2 * D), at(-2 * D + 60)))
mk5 = s5.store.marks()
q5b = quiet(s5, (at(60), at(D + 1), at(2 * D), at(3 * D - 1)))
s5c, ids5c = fresh()
s5c.note_failure(ids5c[0], 429, str(3 * D), now=NOW)
q5c = quiet(s5c, (datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc), at(90), at(3 * D - 1)))
s6, ids6 = fresh()
s6.note_failure(ids6[0], 429, "600", now=NOW)
q6 = quiet(s6, (at(-120), at(599)))
check("R25. КРИТИЧНО: часы отстали на 2 суток (или сбросились на 2000 год) во время паузы 3 суток — отметок нет, "
      "запись паузы в файле не меняется; после поправки часов ни один канал не отмечается раньше срока службы "
      "(«поставили» + Retry-After), после срока — обе отметки; поправка часов на 2 минуты паузу не меняет",
      not q5 and mk5 == mk5a and mk5["backoff_until"] == S.format_utc(at(3 * D))
      and mk5["backoff_set_at"] == S.format_utc(NOW) and not q5b and due(s5, at(3 * D + 1)) == ids5
      and not q5c and due(s5c, at(3 * D + 1)) == ids5c
      and not q6 and s6.store.marks()["backoff_until"] == S.format_utc(at(600)) and due(s6, at(601)) == ids6,
      (q5, mk5a, mk5, q5b, q5c, q6))
s7, ids7 = fresh(1)
_m7 = s7.store.marks()
_m7.update({"backoff_until": "2099-01-01T00:00:00Z", "backoff_set_at": S.format_utc(NOW), "backoff_s": 60})
s7.store.save_marks(_m7)
r7 = due(s7, at(60))
s8, ids8 = fresh(1)
_m8 = s8.store.marks()
_m8.update({"backoff_until": S.format_utc(at(2 * 365 * D)), "backoff_set_at": S.format_utc(NOW), "backoff_s": 2 * 365 * D})
s8.store.save_marks(_m8)
r8 = due(s8, at(60))
s9, ids9 = fresh(1)
_m9 = s9.store.marks()
_m9.update({"backoff_until": S.format_utc(at(300 * D)), "backoff_set_at": S.format_utc(NOW), "backoff_s": 300 * D})
s9.store.save_marks(_m9)
check("R26. запись паузы не сходится (длина 60 с, а срок — 2099; длина больше года) — срок испорчен, отметки идут; "
      "сходящаяся пауза на 300 суток действует до своего срока",
      r7 == ids7 and r8 == ids8 and s7.store.marks()["backoff_until"] == "" and s8.store.marks()["backoff_until"] == ""
      and not quiet(s9, (at(299 * D),)) and due(s9, at(300 * D + 1)) == ids9, (r7, r8))
s10, ids10 = fresh(1)
r10 = due(s10, NOW, "browser")
q10 = quiet(s10, (at(15 * 60 - 1),))
o10 = s10.note_relay(ids10[0], "network", now=at(20))
n10 = s10.store.marks()["next"].get(ids10[0])
check("R27. отметку отдали браузеру — 15 минут её не повторяет ни один канал; браузер сообщил «нет связи» — повтор "
      "не раньше чем через 15 минут после этого, общей паузы нет (это не просьба службы подождать)",
      r10 == ids10 and not q10 and o10 == "network" and n10 == S.format_utc(at(20 + 15 * 60))
      and s10.store.marks()["backoff_until"] == "" and due(s10, at(15 * 60 + 1)) == []
      and due(s10, at(15 * 60 + 21)) == ids10, (r10, q10, o10, n10))
s11, ids11 = fresh(1)
o11 = [s11.note_relay(ids11[0], x, now=NOW) for x in ("403", "418", "garbage", "", None, " 404 ")]
n11 = s11.store.marks()["next"].get(ids11[0])
o11b = s11.note_relay(ids11[0], "429", "3600", now=NOW)
o11c = s11.note_relay(ids11[0], "503", None, now=at(10))
check("R28. от браузера: отказ службы (403, 418, 404) и непонятный ответ — следующая через 6 часов; 429 с Retry-After "
      "3600 — общая пауза час; 503 без Retry-After после неё паузу не сокращает",
      o11 == ["rejected"] * 6 and n11 == S.format_utc(at(6 * 3600)) and o11b == 429 and o11c == 503
      and s11.store.marks()["backoff_until"] == S.format_utc(at(3600)), (o11, n11))
s12, ids12 = fresh(12)
r12a = due(s12, NOW)
r12b = due(s12, at(30), "browser") + due(s12, at(59))
r12c = due(s12, at(61), "browser")
s13, ids13 = fresh(12)
r13 = s13.take_due(INST, "Alpha 3.0", now=NOW, force=True)
check("R29. 12 лицензий: не больше 10 отметок в минуту на оба канала вместе (стенд: 20 в минуту с одной сети); "
      "остальные уходят через минуту, без повторов; force (только для проверок) не ограничен",
      len(r12a) == 10 and r12b == [] and len(r12c) == 2 and sorted(r12a + r12c) == ids12 and len(r13) == 12,
      (len(r12a), r12b, r12c, len(r13)))
#  17.10.2026 (замечание проверки): запись паузы с датой у предела календаря (9999 год — файл правили или
#  он испорчен) раньше роняла расчёт «поставили + длина» (OverflowError) — каждый круг отметок и окно
#  лицензий (GET /api/licenses -> transmitted) падали, пока файл не удалят руками.
_r30 = {}
for _name, _call in (
        ("take_due", lambda s, ids: due(s, NOW)),
        ("note_failure", lambda s, ids: s.note_failure(ids[0], 429, "60", now=NOW)),
        ("note_relay", lambda s, ids: s.note_relay(ids[0], "503", None, now=NOW)),
        ("transmitted", lambda s, ids: s.transmitted(INST, "Alpha 3.0")["backoff_until"])):
    s14, ids14 = fresh(1)
    _m14 = s14.store.marks()
    _m14.update({"backoff_until": "9999-12-31T23:59:59Z", "backoff_set_at": "9999-12-31T23:30:00Z", "backoff_s": 3600})
    s14.store.save_marks(_m14)
    try:
        _r30[_name] = _call(s14, ids14)
    except Exception as e:      # noqa: BLE001 — падение и есть провал проверки
        _r30[_name] = "упало: %r" % (e,)
    if _name == "take_due":
        _r30["take_due_file"] = s14.store.marks()["backoff_until"]
    if _name == "note_failure":
        _r30["note_failure_file"] = s14.store.marks()["backoff_until"]
check("R30. запись паузы с датой 9999 года (файл испорчен или правлен) не роняет ни отметки, ни окно лицензий: "
      "срок считается испорченным и отбрасывается, отметки идут, новая просьба службы подождать записывается",
      _r30.get("take_due") == ids14 and _r30.get("take_due_file") == ""
      and _r30.get("note_failure") is None and _r30.get("note_failure_file") == S.format_utc(at(60))
      and _r30.get("note_relay") == 503 and _r30.get("transmitted") == "", _r30)
for _t in _tmps:
    shutil.rmtree(_t, ignore_errors=True)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- G. самопроверка в платном модуле (настоящая платная сборка склада) ---")
from app.licensing import package as PKG  # noqa: E402
GT = tempfile.mkdtemp(prefix="fm_lic_043g_")
REL_AT = "2026-10-11T12:00:00Z"
zinv, pdoc = MP.build_package(os.path.join(REPO, "modules", "inventory"), PK, "t-pkg-043", REL_AT, licensing="paid",
                              edition="standard", embed_sdk=True, embed_trust=TRUST)
with zipfile.ZipFile(io.BytesIO(zinv)) as z:
    z.extractall(GT)
MDIR = os.path.join(GT, "inventory")
check("G0. в платной сборке есть своя копия SDK, самопроверка и вшитые ключи с моделью «paid»",
      all(os.path.isfile(os.path.join(MDIR, n)) for n in ("fm_license_sdk.py", "fm_paid_guard.py", "fm_embedded.py"))
      and "EMBEDDED_LICENSING = \"paid\"" in open(os.path.join(MDIR, "fm_embedded.py"), encoding="utf-8").read())


class FakeCore(object):
    def __init__(self, mdir, docs=(), verdicts=(), machine=M1, passport=True, signed=True):
        self.module_dir, self.docs, self.verdicts, self.machine, self.signed = mdir, list(docs), list(verdicts), machine, signed
        self.passport = open(os.path.join(mdir, "fm-package.json"), "rb").read() if passport and os.path.isfile(
            os.path.join(mdir, "fm-package.json")) else None
        self.rev = 0

    def import_module_file(self, rel, name=None):
        if self.signed and self.passport:
            pl = json.loads(self.passport)["payload"]
            return PKG.load_verified_file(name or rel, self.module_dir, pl, rel)
        import importlib.util as ilu
        path = os.path.join(self.module_dir, rel)
        spec = ilu.spec_from_file_location(name or rel, path)
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def package_document(self):
        return self.passport

    def license_documents(self):
        return [S.dump_document(d) for d in self.docs]

    def license_verdicts(self):
        return [S.dump_document(v) for v in self.verdicts]

    def license_machine(self):
        return self.machine

    def license_revision(self):
        return self.rev

    def install_id(self):
        return "fm-test"


def guard(core):
    g = core.import_module_file("fm_paid_guard.py", "g043_guard_%d" % id(core))
    return g.load(core, "g043_%d" % id(core))


free_core = FakeCore(os.path.join(REPO, "modules", "inventory"), passport=False, signed=False)
from app.licensing import fm_paid_guard as PG  # noqa: E402
check("G1. обычный модуль из исходников (без вшитых файлов) — самопроверки нет, модуль бесплатный",
      PG.load(free_core, "g043_free") is None)
c = FakeCore(MDIR)
g = guard(c)
check("G2. без лицензии — платное закрыто (no_grant)", g is not None and g.check()[:2] == (False, S.R_NO_GRANT), g and g.check())
c.docs, c.rev = [lic("TEST-cost", grants=(G_COST,))], 1
check("G3. лицензия «Расчёта заказа» склад не открывает (L04)", g.check()[0] is False)
c.docs, c.rev = [lic("TEST-inventory")], 2
check("G4. лицензия склада открывает склад", g.check() == (True, "", "TEST-inventory"), g.check())
c.docs, c.rev = [lic("TEST-both", grants=(G_INV, G_COST))], 3
check("G5. лицензия на оба модуля открывает склад", g.check()[0] is True)
c.docs, c.rev = [lic("TEST-renewal", grants=(G_INV, G_COST), updates="2026-10-11T00:00:00Z")], 4
check("G6. выпуск 11.10.2026 12:00 вне обновлений до 11.10.2026 00:00 — не покрыт (L05)", g.check()[1] == S.R_UPDATE_NOT_COVERED, g.check())
c.docs, c.rev = [lic("TEST-edge", updates=REL_AT)], 5
check("G7. выпуск ровно на границе updates_before — не покрыт (граница исключающая)", g.check()[1] == S.R_UPDATE_NOT_COVERED)
L_OLD = S.verify_license(lic("TEST-x", updates="2026-11-01T00:00:00Z"), LIC_KEYS)
RELEASE = {"module_id": "inventory", "edition": "standard", "version": "1.7.39", "channel": "stable", "released_at": REL_AT}
check("G8. бессрочная лицензия: разрешённый выпуск работает и через годы после конца обновлений (часы не участвуют)",
      S.evaluate(L_OLD, "inventory", edition="standard", release=RELEASE,
                 now=datetime.datetime(2035, 1, 1, tzinfo=datetime.timezone.utc)).ok)
c.docs, c.rev = [lic("TEST-inventory")], 6
c.verdicts = [verdict(M1, "d" * 32, "stop", "seat_taken")]
g._decision = (0.0, None, None)
check("G9. «остановить» от службы для ЭТОГО компьютера — модуль сам закрывает платное (license_stopped)",
      g.check()[:2] == (False, S.R_LICENSE_STOPPED), g.check())
c.verdicts, c.rev = [verdict(M2, "d" * 32, "stop", "seat_taken")], 7
check("G10. остановка для ДРУГОГО компьютера этот не трогает", g.check()[0] is True)
c.verdicts, c.rev = [verdict(M1, "d" * 32, "revoked", "cancelled")], 8
check("G11. «аннулирована» закрывает (license_revoked)", g.check()[1] == S.R_LICENSE_REVOKED)
c.verdicts, c.rev = [verdict(M1, "d" * 32, "revoked", "cancelled", key=XK)], 9
check("G12. «аннулирована» с чужой подписью модулем не принимается", g.check()[0] is True)
c.verdicts, c.rev = [], 10
with open(os.path.join(MDIR, "backend.py"), "a", encoding="utf-8") as f:
    f.write("\n# подмена\n")
g2 = guard(FakeCore(MDIR, docs=[lic("TEST-inventory")], signed=False))
check("G13. изменённый после установки файл модуля — платное закрыто (package_file_mismatch)",
      g2.check()[1] == "package_" + S.R_FILE_MISMATCH, g2.check())
nopass = FakeCore(MDIR, docs=[lic("TEST-inventory")], passport=False, signed=False)
check("G14. ядро «не отдало» паспорт пакета (изменённое ядро) — платное закрыто, а не открыто",
      guard(nopass).check()[1] == "no_package")
calls = []


def h_get():
    calls.append("get")
    return {"ok": True}


async def h_post(req=None):
    calls.append("post")
    return {"ok": True}


added = []
add = g.route_adder(lambda path, handler, methods, policy_id=None: added.append((path, handler, tuple(methods))))
add("items", h_get, ["GET"], policy_id="x.read")
add("item", h_post, ["POST"], policy_id="x.write")
c.docs, c.rev = [], 11
g._decision = (0.0, None, None)
r402 = asyncio.run(added[1][1]())
check("G15. просмотр (GET) остаётся тем же обработчиком; изменение (POST) обёрнуто с тем же именем (карта прав)",
      added[0][1] is h_get and added[1][1] is not h_post and added[1][1].__name__ == "h_post")
check("G16. без лицензии изменение отвечает 402 от модуля, обработчик не вызван",
      getattr(r402, "status_code", 0) == 402 and b'"checked_by":"module"' in r402.body and "post" not in calls,
      getattr(r402, "body", r402))
c.docs, c.rev = [lic("TEST-inventory")], 12
g._decision = (0.0, None, None)
check("G17. с лицензией обработчик вызван", asyncio.run(added[1][1]()) == {"ok": True} and "post" in calls)
emb_free = MP.embedded_source(RELEASE, TRUST, "free")
check("G18. вшитая модель «free» — самопроверки нет", "EMBEDDED_LICENSING = \"free\"" in emb_free)
gi = guard(FakeCore(MDIR, docs=[lic("TEST-inventory")], signed=False))
_t0 = __import__("time").monotonic()
gi._integrity = (_t0, "package_unreadable")
_a1 = gi._package_problem(gi._keys()[0], gi.release())
gi._integrity = (_t0 - 11, "package_unreadable")
_a2 = gi._package_problem(gi._keys()[0], gi.release())
check("G19. временный сбой чтения не запирает модуль на 5 минут: неудача перепроверяется через 10 секунд",
      _a1 == "package_unreadable" and _a2 == "package_" + S.R_FILE_MISMATCH, (_a1, _a2))
gf = guard(c)
gf.model = "freemium"
_plain = []
add_f = gf.route_adder(lambda path, handler, methods, policy_id=None: _plain.append(handler))
add_f("item", h_post, ["POST"], policy_id="x.write")
check("G20. модель freemium: бесплатные изменения не закрываются автоматически (платные — wrap(handler, feature))",
      _plain[0] is h_post)
try:
    MP.build_package(os.path.join(REPO, "modules", "cost"), PK, "t-pkg-043", REL_AT, licensing="paid", edition="standard")
    refused = False
except ValueError:
    refused = True
check("G21. упаковщик не собирает платную сборку без своей копии SDK и ключей (она работала бы бесплатно)", refused)
shutil.rmtree(GT, ignore_errors=True)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- T. разделение сред (L08) ---")
TT = tempfile.mkdtemp(prefix="fm_lic_043t_")
tf = os.path.join(TT, "trust.json")
json.dump(TRUST, open(tf, "w", encoding="utf-8"))
env_backup = {k: os.environ.get(k) for k in (TR.ENV_TEST_KEYS, TR.ENV_TEST_SERVICE, TR.ENV_TEST_RELAY_ONLY)}
os.environ[TR.ENV_TEST_KEYS] = tf
os.environ[TR.ENV_TEST_SERVICE] = "https://fm-test.3diwell.com/fm-api-test-043/mark.php"
os.environ[TR.ENV_TEST_RELAY_ONLY] = "1"
src_ok = ("t-lic-043" in TR.trusted_keys() and TR.license_service_url().endswith("/mark.php")
          and TR.direct_marks_disabled_for_test())
sys.frozen = True
try:
    frozen_keys = TR.trusted_keys()
    frozen_url = TR.license_service_url()
    frozen_relay = TR.direct_marks_disabled_for_test()
finally:
    del sys.frozen
check("T1. из исходников тестовые ключи, адрес тестовой службы и «только через браузер» включаются переменными", src_ok)
check("T2. КРИТИЧНО: собранная программа тестовые ключи, тестовый адрес и «только через браузер» не принимает",
      "t-lic-043" not in frozen_keys and set(frozen_keys) == {k["key_id"] for k in TR.PRODUCTION_KEYS}
      and frozen_url == TR.LICENSE_SERVICE_URL and "fm-test" not in frozen_url and frozen_relay is False,
      (list(frozen_keys), frozen_url))
check("T3. тестовая лицензия в собранной программе не принимается (неизвестный ключ)",
      code_of(lambda: S.verify_license(lic(), {k: v for k, v in frozen_keys.items() if v.purpose == "license"})) == S.R_UNKNOWN_KEY)
for k, v in env_backup.items():
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v
check("T4. адрес службы: только https на 3diwell.com и поддоменах; чужой сайт и http — нет",
      TR._service_url_ok("https://fm-test.3diwell.com/fm-api-test-043/mark.php")
      and not TR._service_url_ok("https://fm-test.3diwell.com.evil.io/mark.php")
      and not TR._service_url_ok("http://fm-test.3diwell.com/mark.php")
      and not TR._service_url_ok("https://user" + chr(64) + "3diwell.com/mark.php"))
trust_src = open(os.path.join(REPO, "app", "licensing", "trust.py"), encoding="utf-8").read()
#  25.10.2026: рабочие ключи сайта вписаны; тестовый ключ стенда 043 среди них быть не должен.
check("T5. тестовый ключ стенда в код не вписан и в рабочих ключах его нет",
      all(not k["key_id"].startswith("3dw-lic-test") for k in TR.PRODUCTION_KEYS)
      and "3dw-lic-test-040" not in trust_src and "M6eU3" not in trust_src)
shutil.rmtree(TT, ignore_errors=True)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- метка-ловушка ---")
SRC = "".join(open(os.path.join(REPO, "app", "licensing", f), encoding="utf-8").read()
              for f in os.listdir(os.path.join(REPO, "app", "licensing")) if f.endswith(".py"))
check("K1. метка-ловушка не попала в код лицензирования", SENTINEL not in SRC)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("   - " + f)
sys.exit(1 if _fail else 0)
