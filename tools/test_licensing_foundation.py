# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""26.09.2026 — основа платных модулей: подписанные пакеты и лицензии, офлайн.

Проверяется без сервера, на настоящих модулях проекта:
  1. SDK: подпись, схема, правило обновлений «released_at < updates_before», выпуск обязателен,
     привязка, срочная лицензия, имена файлов, опасные для Windows, кэш Python.
  2. Пакет в ядре (app/licensing/package.py): состояния, подложенный .pyc не исполняется, файл,
     изменённый после проверки, не грузится, лишний файл не импортируется.
  3. Служба лицензий (app/licensing/service.py): статусы, платная функция, отказ в обновлении,
     импорт и удаление, рабочая сборка не принимает тестовые ключи.
  4. Упаковщик и утилита поставщика: одинаковый архив из одинаковых исходников, вшитые ключи и
     выпуск, закрытый ключ не читается и не пишется внутри проекта, пароль ключа.
  5. Демонстрационный платный модуль проверяет лицензию САМ: подменённый ответ ядра «лицензия
     есть» не открывает платную функцию (критерий приёмки 6).
  6. В коде лицензирования нет обращений к сети.

Ключи — одноразовые, создаются в памяти и во временной папке; рабочих ключей здесь нет и быть не
может. Запуск:  PYTHONIOENCODING=utf-8 python tools/test_licensing_foundation.py   (0 = пройдено)
"""
import ast
import datetime
import importlib.util
import io
import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.dont_write_bytecode = True

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from app.licensing import fm_license_sdk as S  # noqa: E402
from app.licensing import package as P  # noqa: E402
from app.licensing import service as SV  # noqa: E402
from app.licensing import trust as TR  # noqa: E402
import module_package as MP  # noqa: E402

FAILS, PASSED = [], [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — " + name)
    else:
        FAILS.append(name)
        print("FAIL — " + name + (("  :: %s" % (extra,))[:500] if extra != "" else ""))


def section(t):
    print("\n--- %s ---" % t)


def rej(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except S.Rejected as e:
        return e.code
    return None


def pub(key):
    return S.b64u_encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


TMP = tempfile.mkdtemp(prefix="fm_lic_found_")
LIC_KEY, PKG_KEY, OTHER_KEY = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
TRUST_ITEMS = [{"key_id": "t-lic", "purpose": "license", "public_key": pub(LIC_KEY), "label": "тест", "test": True},
               {"key_id": "t-pkg", "purpose": "package", "public_key": pub(PKG_KEY), "label": "тест", "test": True}]
TRUSTED = S.trusted_set(TRUST_ITEMS)
UTC = datetime.timezone.utc


def lic(**over):
    body = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": "L-0001",
            "grants": [{"module_id": "demo_paid", "edition": "pro", "features": ["pro_report"]}],
            "use_type": "perpetual", "updates_before": "2027-10-01T00:00:00Z", "issued_at": "2026-09-26T00:00:00Z"}
    body.update(over)
    return body


def signed_lic(key=LIC_KEY, key_id="t-lic", **over):
    return S.dump_document(S.sign_document(S.FORMAT_LICENSE, lic(**over), key, key_id))


REL = {"module_id": "demo_paid", "edition": "pro", "version": "1.0.0", "channel": "stable",
       "released_at": "2027-09-20T00:00:00Z"}

# ════════════════════════════════════════════════════════════════════════════
section("1. SDK: подпись и строгий формат")
raw = signed_lic()
p = S.verify_license(raw, TRUSTED)
check("S1. подписанная лицензия проверяется", p["license_id"] == "L-0001")
check("S2. каноническая запись: ключи по порядку, без пробелов, дробные числа запрещены",
      S.canonical_bytes({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}' and rej(S.canonical_bytes, {"x": 1.5}) == S.R_MALFORMED)
d = json.loads(raw)
d["payload"]["updates_before"] = "2099-01-01T00:00:00Z"
check("S3. изменённый срок обновлений — неверная подпись", rej(S.verify_license, json.dumps(d), TRUSTED) == S.R_BAD_SIGNATURE)
check("S4. чужой ключ — неизвестный ключ", rej(S.verify_license, signed_lic(OTHER_KEY, "x-lic"), TRUSTED) == S.R_UNKNOWN_KEY)
check("S5. лицензия, подписанная ключом ПАКЕТОВ, не принимается (назначения ключей разделены)",
      rej(S.verify_license, signed_lic(PKG_KEY, "t-pkg"), TRUSTED) == S.R_UNKNOWN_KEY)
pkgdoc = S.dump_document(S.sign_document(S.FORMAT_PACKAGE, {"x": 1}, PKG_KEY, "t-pkg"))
check("S6. паспорт пакета нельзя выдать за лицензию (разные форматы и области подписи)",
      rej(S.verify_license, pkgdoc, TRUSTED) == S.R_WRONG_FORMAT)
d = json.loads(raw)
d["payload"]["key_id"] = "t-pkg"
check("S7. key_id в данных обязан совпадать с ключом подписи", rej(S.verify_license, json.dumps(d), TRUSTED) == S.R_BAD_SIGNATURE)
d = json.loads(raw)
d["trusted_public_key"] = pub(OTHER_KEY)
check("S8. лишнее поле документа (например, «свой» ключ) — отказ, ключ из документа не принимается",
      rej(S.verify_license, json.dumps(d), TRUSTED) == S.R_MALFORMED)
check("S9. нет срока обновлений — это НЕ «бессрочно», а отказ",
      rej(S.validate_license, {k: v for k, v in lic().items() if k != "updates_before"} | {"key_id": "t"}) == S.R_MISSING_FIELD)
check("S10. у бессрочной лицензии не бывает срока использования",
      rej(S.validate_license, lic(use_valid_until="2027-01-01T00:00:00Z", key_id="t")) == S.R_BAD_VALUE)
check("S11. срочная лицензия без дат — отказ", rej(S.validate_license, lic(use_type="term", key_id="t")) == S.R_MISSING_FIELD)
check("S12. незнакомое поле — отказ", rej(S.validate_license, lic(paid=True, key_id="t")) == S.R_UNKNOWN_FIELD)
check("S13. другой продукт — отказ", rej(S.validate_license, lic(product_id="other", key_id="t")) == S.R_WRONG_PRODUCT)
check("S14. дата не по формату — отказ", rej(S.validate_license, lic(updates_before="2027-10-01", key_id="t")) == S.R_BAD_VALUE)

section("2. SDK: право использования отдельно от права на выпуски")
L = S.verify_license(raw, TRUSTED)
ev = lambda **kw: S.evaluate(L, "demo_paid", **kw)
check("E1. выпуск обязателен: без него право на обновление не проверить", ev(feature="pro_report").code == S.R_RELEASE_REQUIRED)
check("E2. выпуск 20.09.2027 покрыт лицензией «обновления до 01.10.2027»", ev(feature="pro_report", release=REL).ok)
check("E3. выпуск 10.10.2027 не покрыт — нужна продление",
      ev(feature="pro_report", release=dict(REL, released_at="2027-10-10T00:00:00Z")).code == S.R_UPDATE_NOT_COVERED)
check("E4. граница исключающая: выпуск ровно 01.10.2027 не покрыт",
      ev(feature="pro_report", release=dict(REL, released_at="2027-10-01T00:00:00Z")).code == S.R_UPDATE_NOT_COVERED)
check("E5. бессрочная лицензия не смотрит на часы: покрытый выпуск работает и в 2030 году",
      ev(feature="pro_report", release=REL, now=datetime.datetime(2030, 1, 1, tzinfo=UTC)).ok)
check("E6. функция, которой нет в лицензии, не даётся", ev(feature="other", release=REL).code == S.R_FEATURE)
check("E7. другая редакция не даётся", ev(feature="pro_report", release=dict(REL, edition="lite")).code == S.R_EDITION)
check("E8. лицензия на другой модуль не даёт права", S.evaluate(L, "cost", release=dict(REL, module_id="cost")).code == S.R_NO_GRANT)
Lb = S.verify_license(signed_lic(installation_binding={"install_id": "fm-abc"}), TRUSTED)
check("E9. привязка: чужая установка — отказ, своя — право",
      S.evaluate(Lb, "demo_paid", release=REL, install_id="fm-xyz").code == S.R_BINDING
      and S.evaluate(Lb, "demo_paid", release=REL, install_id="fm-abc").ok)
Lt = S.verify_license(signed_lic(use_type="term", use_valid_from="2026-01-01T00:00:00Z",
                                 use_valid_until="2027-01-01T00:00:00Z"), TRUSTED)
check("E10. срочная: без времени — отказ, в срок — право, после — истекла, до начала — ещё нет",
      S.evaluate(Lt, "demo_paid", release=REL).code == S.R_TIME_REQUIRED
      and S.evaluate(Lt, "demo_paid", release=REL, now=datetime.datetime(2026, 6, 1, tzinfo=UTC)).ok
      and S.evaluate(Lt, "demo_paid", release=REL, now=datetime.datetime(2027, 2, 1, tzinfo=UTC)).code == S.R_USE_EXPIRED
      and S.evaluate(Lt, "demo_paid", release=REL, now=datetime.datetime(2025, 2, 1, tzinfo=UTC)).code == S.R_USE_NOT_STARTED)
check("E11. бета-выпуск по стабильной лицензии не даётся",
      ev(feature="pro_report", release=dict(REL, channel="beta")).code == S.R_CHANNEL)
Ls = S.verify_license(signed_lic(release_scope={"max_major": 1}), TRUSTED)
check("E12. ограничение основной версии: 1.x можно, 2.0 нельзя",
      S.evaluate(Ls, "demo_paid", release=REL).ok
      and S.evaluate(Ls, "demo_paid", release=dict(REL, version="2.0.0")).code == S.R_RELEASE_SCOPE)
L2 = S.verify_license(signed_lic(license_id="L-0002", updates_before="2028-10-01T00:00:00Z"), TRUSTED)
check("E13. продление: из двух лицензий берётся та, что покрывает выпуск",
      S.best_decision([L, L2], "demo_paid", release=dict(REL, released_at="2027-12-01T00:00:00Z")).license_id == "L-0002")
check("E14. самая полезная причина отказа: «выпуск не покрыт» важнее «нет лицензии»",
      S.best_decision([L], "demo_paid", release=dict(REL, released_at="2028-01-01T00:00:00Z")).code == S.R_UPDATE_NOT_COVERED
      and S.best_decision([], "demo_paid", release=REL).code == S.R_NO_GRANT)

section("3. SDK: состав пакета")
for bad in ("backend.py.", "web/x.js ", "a/CON.txt", "con.js", "a\\b.py", "../x.py", "x//y.py", "a:b.py", "/abs.py"):
    check("N. имя «%s» отклоняется" % bad, S.path_problem(bad) != "", bad)
check("N. обычные имена проходят", all(S.path_problem(n) == "" for n in ("backend.py", "web/Panel.js", "a/b-c_d.1.json")))
base_pl = {"schema_version": 1, "product_id": S.PRODUCT_ID, "module_id": "m", "edition": "free", "version": "1.0.0",
           "channel": "stable", "released_at": "2026-09-26T00:00:00Z", "core_contract": "1", "key_id": "t-pkg",
           "licensing": {"model": "free", "paid_features": []}, "entry": {"backend": "", "web": ""},
           "files": {"a.py": "0" * 64}}
check("N. два имени, отличающиеся регистром, — отказ (Windows сольёт их в один файл)",
      rej(S.validate_package, dict(base_pl, files={"a.py": "0" * 64, "A.py": "1" * 64})) == S.R_BAD_VALUE)
check("N. кэш Python и паспорт в составе пакета — отказ",
      rej(S.validate_package, dict(base_pl, files={"__pycache__/a.cpython-314.pyc": "0" * 64})) == S.R_BAD_VALUE)
check("N. у бесплатного пакета не бывает платных функций",
      rej(S.validate_package, dict(base_pl, licensing={"model": "free", "paid_features": ["x"]})) == S.R_BAD_VALUE)
pl = dict(base_pl, files={"a.py": "a" * 64})
check("F1. отдельный .pyc вне __pycache__ — лишний файл (Python исполнил бы его вместо .py)",
      rej(S.check_files, pl, {"a.py": "a" * 64, "b.pyc": "b" * 64}) == S.R_EXTRA_FILE)
check("F2. содержимое __pycache__ не считается составом", S.check_files(pl, {"a.py": "a" * 64, "__pycache__/a.cpython-314.pyc": "c" * 64}))
check("F3. пропавший и изменённый файл — отказ",
      rej(S.check_files, pl, {}) == S.R_FILE_MISSING and rej(S.check_files, pl, {"a.py": "b" * 64}) == S.R_FILE_MISMATCH)
check("F4. выпуск, вшитый в код, сверяется с паспортом",
      S.embedded_release_matches(REL, dict(REL, files={})) and not S.embedded_release_matches(REL, dict(REL, version="1.0.1")))

# ════════════════════════════════════════════════════════════════════════════
section("4. упаковщик и проверка пакета в ядре")
DEMO_FREE = os.path.join(REPO, "examples", "modules", "demo_free")
DEMO_PAID = os.path.join(REPO, "examples", "modules", "demo_paid")
z1, doc1 = MP.build_package(DEMO_FREE, PKG_KEY, "t-pkg", "2026-09-26T00:00:00Z", "free")
z2, doc2 = MP.build_package(DEMO_FREE, PKG_KEY, "t-pkg", "2026-09-26T00:00:00Z", "free")
check("M1. одинаковые исходники — одинаковый паспорт и одинаковый состав архива",
      doc1["payload"] == doc2["payload"] and zipfile.ZipFile(io.BytesIO(z1)).namelist() == zipfile.ZipFile(io.BytesIO(z2)).namelist())
junk = os.path.join(TMP, "junkmod")
#  Кэш, оставленный в исходниках проверкой синтаксиса (py_compile), в копию не берём — мусор подкладываем сами.
shutil.copytree(DEMO_FREE, junk, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
os.makedirs(os.path.join(junk, "__pycache__"), exist_ok=True)
for n, b in (("__pycache__/backend.cpython-314.pyc", b"x"), ("farm.db", b"x"), ("run.log", b"x"), ("old.bak", b"x"),
             ("stray.pyc", b"x"), ("L-1.fmlic", b"x"), ("key.pem", b"x")):
    with open(os.path.join(junk, *n.split("/")), "wb") as f:
        f.write(b)
check("M2. в пакет не попадают кэш, базы, журналы, резервные копии, лицензии и ключи",
      sorted(MP.collect_files(junk)) == ["backend.py", "module.json"], sorted(MP.collect_files(junk)))


def unpack(zbytes, dest):
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        top = z.namelist()[0].split("/")[0]
        z.extractall(dest)
    return os.path.join(dest, top)


def manifest(d):
    return json.load(open(os.path.join(d, "module.json"), encoding="utf-8"))


free_dir = unpack(z1, os.path.join(TMP, "free"))
pk = {k: v for k, v in TRUSTED.items() if v.purpose == "package"}
check("P1. подписанный бесплатный пакет — «проверен»", P.inspect_dir(free_dir, pk, manifest(free_dir))["state"] == P.STATE_VERIFIED)
check("P2. пакет без паспорта — «без подписи» (старые, сторонние и разработческие модули работают)",
      P.inspect_dir(DEMO_FREE, pk, manifest(DEMO_FREE))["state"] == P.STATE_UNSIGNED)
check("P3. подписанный ключом, которого программа не знает, — «не доверен»",
      P.inspect_dir(free_dir, {}, manifest(free_dir))["state"] == P.STATE_UNTRUSTED)
t1 = unpack(z1, os.path.join(TMP, "t1"))
with open(os.path.join(t1, "backend.py"), "a", encoding="utf-8") as f:
    f.write("\n# подмена\n")
check("P4. изменённый файл — «повреждён»", P.inspect_dir(t1, pk, manifest(t1))["code"] == S.R_FILE_MISMATCH)
t2 = unpack(z1, os.path.join(TMP, "t2"))
open(os.path.join(t2, "extra.py"), "w").write("x = 1\n")
check("P5. дописанный файл — «повреждён»", P.inspect_dir(t2, pk, manifest(t2))["code"] == S.R_EXTRA_FILE)
t3 = unpack(z1, os.path.join(TMP, "t3"))
mj = manifest(t3)
mj["version"] = "9.9.9"
check("P6. module.json не совпадает с паспортом — «повреждён»", P.inspect_dir(t3, pk, mj)["state"] == P.STATE_INVALID)
t4 = unpack(z1, os.path.join(TMP, "t4"))
_pkg_raw = json.loads(open(os.path.join(t4, "fm-package.json"), encoding="utf-8").read())
_pkg_raw["payload"]["licensing"] = {"model": "free", "paid_features": []}
_pkg_raw["payload"]["edition"] = "pro"
open(os.path.join(t4, "fm-package.json"), "w", encoding="utf-8").write(json.dumps(_pkg_raw))
check("P7. правка паспорта (редакция, платность) обычным редактором — «повреждён»",
      P.inspect_dir(t4, pk, manifest(t4))["code"] == S.R_BAD_SIGNATURE)
check("P8. архив с именами, которые Windows сливает, не распаковывается",
      len(P.zip_member_problems(["backend.py", "BACKEND.PY", "web/a.js."])) == 2 and not P.zip_member_problems(["backend.py", "web/a.js"]))

section("5. код подписанного пакета исполняется только из проверенных байтов")
# Настоящий приём атаки: .pyc «без проверки хеша» (PEP 552) в __pycache__ рядом с проверенным backend.py.
evil = os.path.join(TMP, "evil_src")
os.makedirs(evil)
with open(os.path.join(evil, "backend.py"), "w", encoding="utf-8") as f:
    f.write("WHO = 'ПОДМЕНА'\n")
import py_compile  # noqa: E402
v_dir = unpack(z1, os.path.join(TMP, "v"))
pyc_path = importlib.util.cache_from_source(os.path.join(v_dir, "backend.py"))
os.makedirs(os.path.dirname(pyc_path), exist_ok=True)
py_compile.compile(os.path.join(evil, "backend.py"), cfile=pyc_path, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
check("L0. подложенный .pyc есть на диске, а пакет всё равно «проверен» (кэш не часть состава)",
      os.path.isfile(pyc_path) and P.inspect_dir(v_dir, pk, manifest(v_dir))["state"] == P.STATE_VERIFIED)
_spec = importlib.util.spec_from_file_location("fm_plain_probe", os.path.join(v_dir, "backend.py"))
_plain = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_plain)
check("L1. контроль: обычный загрузчик Python исполнил бы подложенный .pyc", getattr(_plain, "WHO", "") == "ПОДМЕНА")
_pkgv = P.inspect_dir(v_dir, pk, manifest(v_dir))
_modv = P.load_verified_backend("fm_module_probe_v", v_dir, _pkgv["payload"])
check("L2. КРИТИЧНО: загрузчик ядра исполнил проверенный исходник, а не .pyc",
      getattr(_modv, "WHO", None) is None and hasattr(_modv, "register"))
check("L3. папки __pycache__ подписанного пакета убраны перед запуском", not os.path.exists(os.path.dirname(pyc_path)))
with open(os.path.join(v_dir, "backend.py"), "a", encoding="utf-8") as f:
    f.write("\nWHO = 'после проверки'\n")
try:
    P.load_verified_backend("fm_module_probe_v2", v_dir, _pkgv["payload"])
    _late = False
except ImportError:
    _late = True
check("L4. файл, изменённый ПОСЛЕ проверки, не загружается", _late)
# соседний файл, которого нет в паспорте, через обычный import
sib = unpack(z1, os.path.join(TMP, "sib"))
_pkgs = P.inspect_dir(sib, pk, manifest(sib))
P.register_verified_dir(sib, _pkgs["payload"])
open(os.path.join(sib, "fm_probe_unlisted.py"), "w").write("X = 1\n")
sys.path.insert(0, sib)
try:
    import fm_probe_unlisted  # noqa: F401
    _blocked = False
except ImportError:
    _blocked = True
finally:
    sys.path.remove(sib)
    P.unregister_dir(sib)
check("L5. файл вне паспорта в папке подписанного пакета не импортируется даже обычным import", _blocked)
#  Имена с заглавными буквами (на Windows регистр путей не различается) и порядок поиска: файл
#  подписанного пакета с именем стандартного модуля не перехватывает его у остальной программы.
cs_src = os.path.join(TMP, "cs_src")
os.makedirs(cs_src)
json.dump({"id": "cs_probe", "version": "1.0.0"}, open(os.path.join(cs_src, "module.json"), "w"))
open(os.path.join(cs_src, "backend.py"), "w").write("def register(core):\n    pass\n")
open(os.path.join(cs_src, "HelperCase.py"), "w").write("WHO = 'helper'\n")
open(os.path.join(cs_src, "colorsys.py"), "w", encoding="utf-8").write("WHO = 'ПЕРЕХВАТ'\n")
zcs, _ = MP.build_package(cs_src, PKG_KEY, "t-pkg", "2026-09-26T00:00:00Z", "free")
cs_dir = unpack(zcs, os.path.join(TMP, "cs"))
_pcs = P.inspect_dir(cs_dir, pk, manifest(cs_dir))
P.register_verified_dir(cs_dir, _pcs["payload"])
sys.path.append(cs_dir)
sys.modules.pop("colorsys", None)
try:
    import HelperCase  # noqa: F401
    import colorsys
    _case_ok = getattr(HelperCase, "WHO", "") == "helper"
    _std_ok = hasattr(colorsys, "rgb_to_hsv") and getattr(colorsys, "WHO", None) is None
except Exception as e:
    _case_ok = _std_ok = False
    print("   исключение:", e)
finally:
    sys.path.remove(cs_dir)
    P.unregister_dir(cs_dir)
check("L7. файл с заглавными буквами из подписанного пакета импортируется (Windows не различает регистр)", _case_ok)
check("L8. КРИТИЧНО: подписанный модуль с файлом colorsys.py не перехватывает стандартный модуль у программы", _std_ok)
check("L9. поисковик стоит перед обычным поиском Python, а не первым в цепочке",
      P._FINDER in sys.meta_path and sys.meta_path.index(P._FINDER) > 0
      and sys.meta_path.index(P._FINDER) < sys.meta_path.index(importlib.machinery.PathFinder))
check("L6. ресурс отдаётся, только если он в паспорте и не изменён",
      P.asset_ok(_pkgs, "module.json", open(os.path.join(sib, "module.json"), "rb").read())
      and not P.asset_ok(_pkgs, "module.json", b"{}") and not P.asset_ok(_pkgs, "web/nope.js", b"")
      and P.asset_ok({"state": "unsigned"}, "web/x.js", b"any"))

# ════════════════════════════════════════════════════════════════════════════
section("6. служба лицензий ядра")
trust_file = os.path.join(TMP, "trust.json")
json.dump([dict(k) for k in TRUST_ITEMS], open(trust_file, "w", encoding="utf-8"))
zp, docp = MP.build_package(DEMO_PAID, PKG_KEY, "t-pkg", "2027-09-20T00:00:00Z", "freemium", ["pro_report"], "pro",
                            embed_sdk=True, embed_trust=TRUST_ITEMS)
paid_dir = unpack(zp, os.path.join(TMP, "paid"))
pkg_paid = P.inspect_dir(paid_dir, pk, manifest(paid_dir))
check("V0. подписанный платный демо-пакет «проверен»; внутри своя копия SDK и вшитые ключи",
      pkg_paid["state"] == P.STATE_VERIFIED and "fm_license_sdk.py" in pkg_paid["payload"]["files"]
      and "fm_embedded.py" in pkg_paid["payload"]["files"])
emb_txt = open(os.path.join(paid_dir, "fm_embedded.py"), encoding="utf-8").read()
check("V0b. во вшитом файле только открытые ключи и выпуск этого пакета",
      "PRIVATE" not in emb_txt.upper() and '"released_at": "2027-09-20T00:00:00Z"' in emb_txt)
#  R-149 (16.10.2026): SDK и самопроверка — MPL-2.0, как ядро. Заголовок стоит в первых 600 байтах (там
#  его ищет выгрузка открытой копии — второй не добавит), а в платный пакет копия ложится байт в байт:
#  условие MPL «неизменённая копия» выполняется само.
_sdk_ok = []
for _n in ("fm_license_sdk.py", "fm_paid_guard.py"):
    _repo_b = open(os.path.join(REPO, "app", "licensing", _n), "rb").read()
    _pkg_p = os.path.join(paid_dir, _n)
    _pkg_b = open(_pkg_p, "rb").read() if os.path.isfile(_pkg_p) else b""
    _sdk_ok.append(b"# SPDX-License-Identifier: MPL-2.0\n" in _repo_b[:600]
                   and b"Mozilla Public License, v. 2.0" in _repo_b[:600]
                   and S.sha256_bytes(_pkg_b) == S.sha256_bytes(_repo_b))
check("V0c. SDK и самопроверка несут заголовок MPL-2.0 и лежат в платном пакете без изменений", all(_sdk_ok), _sdk_ok)
data_dir = os.path.join(TMP, "data")
svc = SV.LicenseService(data_dir, trusted=TRUSTED)
check("V1. без подписи — платного нет", svc.module_status("x", {"state": "unsigned"})["license"] == SV.UNSIGNED_PACKAGE)
check("V2. подписанный бесплатный — лицензия не нужна",
      svc.module_status("demo_free", P.inspect_dir(free_dir, pk, manifest(free_dir)))["license"] == SV.LICENSE_NOT_REQUIRED)
check("V3. платный без лицензии — «нет лицензии»; бесплатная функция доступна, платная — нет",
      svc.module_status("demo_paid", pkg_paid)["license"] == SV.LICENSE_MISSING
      and svc.feature_decision("demo_paid", "status_only", pkg_paid).ok
      and not svc.feature_decision("demo_paid", "pro_report", pkg_paid).ok)
r0 = svc.revision()
try:
    svc.import_document(signed_lic(OTHER_KEY, "x-lic"))
    _stored = True
except S.Rejected:
    #  10.10.2026: в папке лицензий есть и служебные файлы (номер компьютера) — считаются только лицензии.
    _stored = os.path.isdir(os.path.join(data_dir, "licenses")) and any(
        n.endswith(".fmlic") for n in os.listdir(os.path.join(data_dir, "licenses")))
check("V4. поддельная лицензия не принимается и не сохраняется", not _stored)
raw_ok = signed_lic()
svc.import_document(raw_ok)
check("V5. настоящая лицензия сохранена как есть, байт в байт; номер изменений вырос",
      open(os.path.join(data_dir, "licenses", "L-0001.fmlic"), "rb").read() == raw_ok and svc.revision() > r0)
check("V6. после импорта — «действует», платная функция доступна",
      svc.module_status("demo_paid", pkg_paid)["license"] == SV.LICENSE_OK and svc.feature_decision("demo_paid", "pro_report", pkg_paid).ok)
check("V7. исходные документы выдаются модулю как есть", svc.raw_documents() == [raw_ok])
zn, _ = MP.build_package(DEMO_PAID, PKG_KEY, "t-pkg", "2027-10-10T00:00:00Z", "freemium", ["pro_report"], "pro",
                         embed_sdk=True, embed_trust=TRUST_ITEMS)
new_dir = unpack(zn, os.path.join(TMP, "paid_new"))
pkg_new = P.inspect_dir(new_dir, pk, manifest(new_dir))
check("V8. выпуск после окончания обновлений: «не покрыт», замену рабочей версии ядро отклонит",
      svc.module_status("demo_paid", pkg_new)["license"] == S.R_UPDATE_NOT_COVERED
      and svc.update_refusal("demo_paid", pkg_new, pkg_paid) == S.R_UPDATE_NOT_COVERED)
check("V9. повторная установка покрытого выпуска разрешена", svc.update_refusal("demo_paid", pkg_paid, pkg_paid) == "")
open(os.path.join(data_dir, "licenses", "L-0002.fmlic"), "wb").write(signed_lic(license_id="L-0002", updates_before="2028-10-01T00:00:00Z"))
check("V10. продление, положенное в папку лицензий вручную, замечено; новый выпуск теперь покрыт",
      svc.module_status("demo_paid", pkg_new)["license"] == SV.LICENSE_OK and svc.update_refusal("demo_paid", pkg_new, pkg_paid) == "")
check("V11. удаление лицензии закрывает платное сразу, данные не трогаются",
      svc.remove("L-0002") and svc.remove("L-0001") and not svc.feature_decision("demo_paid", "pro_report", pkg_paid).ok
      and not svc.remove("L-0001") and not svc.remove("../x"))
check("V12. номер установки — случайный, без личных данных, постоянный",
      svc.install_id().startswith("fm-") and svc.install_id() == SV.LicenseService(data_dir, trusted=TRUSTED).install_id())
iid_dir = os.path.join(TMP, "iid")
os.makedirs(iid_dir)
open(os.path.join(iid_dir, "install_id.txt"), "w", encoding="utf-8-sig").write("fm-0123456789abcdef01234567\n")
_bom = SV.LicenseService(iid_dir, trusted=TRUSTED).install_id()
open(os.path.join(iid_dir, "install_id.txt"), "w", encoding="utf-8").write("испорчено!!")
_bad = SV.LicenseService(iid_dir, trusted=TRUSTED).install_id()
_kept = open(os.path.join(iid_dir, "install_id.txt"), encoding="utf-8").read()
check("V12b. КРИТИЧНО: номер установки не меняется молча — BOM от Блокнота читается, испорченный файл не перезаписывается",
      _bom == "fm-0123456789abcdef01234567" and _bad == "" and _kept == "испорчено!!", (_bom, _bad, _kept))
_env = os.environ.pop(TR.ENV_TEST_KEYS, None)
#  25.10.2026: рабочие ключи вписаны (переход к рабочему комплекту сайта). Проверяется ровно согласованный набор:
#  key_id, назначение и отпечаток SHA-256 сырых 32 байт открытого ключа — а не одно наличие похожего имени.
_PROD_EXPECTED = {
    "fm-pilot091-f2495abcaa0c1ed0": ("license", "14be9932bc9d575680d297311567aa51447472871ec1ef32a4888de8d2304ea4"),
    "fm-license-prod-2026-01": ("license", "2a65085670cc8ace30360c15a2dab08bff9c5d8183b6bb8831c621eb5679ff3c"),
    "fm-pkg-prod-2026-01": ("package", "beb4b4236f05064acc3f7d421edb4d383fdc87e2de99e8948353e5ea8a3a1ed7"),
    "fm-pkg-pilot091-build": ("package", "e0bd4015298ef4cc97c9ec3d21e0f6920a9488a54924f7cd88f7d66d6cb1847b"),
}
_prod_seen = {k.key_id: (k.purpose, hashlib.sha256(k.public_key).hexdigest()) for k in TR.trusted_keys().values()}
check("V13. без переменной программа доверяет ровно рабочим ключам (key_id, назначение, отпечаток), тестовым — нет",
      _prod_seen == _PROD_EXPECTED, _prod_seen)
os.environ[TR.ENV_TEST_KEYS] = trust_file
_ok_src = set(TR.trusted_keys()) == {"t-lic", "t-pkg"} | set(_PROD_EXPECTED)
sys.frozen = True
_frozen = TR.trusted_keys()
del sys.frozen
if _env is None:
    os.environ.pop(TR.ENV_TEST_KEYS, None)
else:
    os.environ[TR.ENV_TEST_KEYS] = _env
check("V14. КРИТИЧНО: собранная программа тестовые ключи не принимает ни при каких настройках",
      _ok_src and set(_frozen) == set(_PROD_EXPECTED))
check("V15. рабочая служба по умолчанию отклоняет тестовую лицензию",
      rej(SV.LicenseService(os.path.join(TMP, "prod"), trusted=S.trusted_set([])).import_document, raw_ok) == S.R_UNKNOWN_KEY)

# ════════════════════════════════════════════════════════════════════════════
section("7. платный компонент не верит ядру (критерий приёмки 6)")


class FakeCore(object):
    """Ядро, которое «врёт»: всегда говорит, что лицензия есть."""

    def __init__(self, mdir, pkg, docs, iid="fm-test"):
        self.module_id, self.module_dir, self._pkg, self._docs, self._iid = "demo_paid", mdir, pkg, docs, iid
        self.routes = []

    def license_status(self):
        return {"license": "active", "state": "verified"}

    def feature_allowed(self, feature):
        return True

    def license_documents(self):
        return list(self._docs)

    def install_id(self):
        return self._iid

    def package_document(self):
        return self._pkg

    def import_module_file(self, rel, name=None):
        return P.load_verified_file(name or rel, self.module_dir, pkg_paid["payload"], rel)

    def add_route(self, *a, **k):
        self.routes.append(("free",) + a)

    def add_paid_route(self, *a, **k):
        self.routes.append(("paid",) + a)


def component(core_obj):
    spec = importlib.util.spec_from_file_location("fm_demo_paid_probe_%d" % id(core_obj), os.path.join(paid_dir, "backend.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.register(core_obj)
    return mod


pkg_raw = pkg_paid["raw"]
c_none = component(FakeCore(paid_dir, pkg_raw, []))
check("C1. КРИТИЧНО: ядро говорит «лицензия есть», документов нет — компонент отказывает",
      c_none.verify_paid("pro_report")[0] is False and c_none.nightly_job().startswith("skipped"))
c_forged = component(FakeCore(paid_dir, pkg_raw, [signed_lic(OTHER_KEY, "t-lic")]))
check("C2. КРИТИЧНО: подделанная лицензия (чужой ключ под нашим key_id) — отказ", c_forged.verify_paid("pro_report")[0] is False)
c_ok = component(FakeCore(paid_dir, pkg_raw, [raw_ok]))
check("C3. настоящая лицензия — компонент выполняет платную функцию", c_ok.verify_paid("pro_report")[0] is True
      and c_ok.nightly_job() == "done")
c_newpass = component(FakeCore(paid_dir, pkg_new["raw"], [raw_ok]))
check("C4. КРИТИЧНО: подсунутый паспорт другого выпуска — «выпуск не совпадает», отказ",
      c_newpass.verify_paid("pro_report")[1] == "release_mismatch")
c_bound = component(FakeCore(paid_dir, pkg_raw, [signed_lic(installation_binding={"install_id": "fm-other"})]))
check("C5. лицензия другой установки — отказ", c_bound.verify_paid("pro_report")[1] == S.R_BINDING)
with open(os.path.join(paid_dir, "web_extra.txt"), "w") as f:
    f.write("x")
check("C6. компонент сам сверяет свои файлы: дописанный файл — отказ",
      c_ok.verify_paid("pro_report")[1] == "package_" + S.R_EXTRA_FILE)
os.remove(os.path.join(paid_dir, "web_extra.txt"))
check("C7. бесплатная часть демо объявлена обычным маршрутом, платная — платным",
      [r[0] for r in c_ok.__dict__["core"].routes] == ["free", "paid"])

# ════════════════════════════════════════════════════════════════════════════
section("8. утилита поставщика: закрытые ключи вне проекта")
tool = [sys.executable, os.path.join(REPO, "tools", "fm_license_tool.py")]
env = dict(os.environ, PYTHONIOENCODING="utf-8", FM_TEST_KEY_PW="тестовый-пароль-123")
r = subprocess.run(tool + ["keygen", "--purpose", "license", "--key-id", "k-in-repo", "--out", os.path.join(REPO, "tools"), "--no-passphrase"],
                   capture_output=True, env=env)
check("T1. ключ внутрь папки проекта не пишется", r.returncode != 0 and not os.path.exists(os.path.join(REPO, "tools", "k-in-repo.pem")))
kdir = os.path.join(TMP, "keys")
r = subprocess.run(tool + ["keygen", "--purpose", "license", "--key-id", "k-enc", "--out", kdir, "--passphrase-env", "FM_TEST_KEY_PW"],
                   capture_output=True, env=env)
pem = open(os.path.join(kdir, "k-enc.pem"), "rb").read() if os.path.exists(os.path.join(kdir, "k-enc.pem")) else b""
check("T2. рабочий ключ зашифрован паролем", r.returncode == 0 and b"ENCRYPTED" in pem, r.stderr[-300:])
spec_p = os.path.join(TMP, "spec.json")
json.dump(lic(), open(spec_p, "w", encoding="utf-8"))
r = subprocess.run(tool + ["sign-license", "--key", os.path.join(kdir, "k-enc.pem"), "--key-id", "k-enc", "--spec", spec_p,
                           "--out", os.path.join(REPO, "L-test.fmlic"), "--passphrase-env", "FM_TEST_KEY_PW"], capture_output=True, env=env)
check("T3. лицензия покупателя не записывается в папку проекта", r.returncode != 0 and not os.path.exists(os.path.join(REPO, "L-test.fmlic")))
out_l = os.path.join(TMP, "issued", "L-0001.fmlic")
os.makedirs(os.path.dirname(out_l))
r = subprocess.run(tool + ["sign-license", "--key", os.path.join(kdir, "k-enc.pem"), "--key-id", "k-enc", "--spec", spec_p,
                           "--out", out_l, "--passphrase-env", "FM_TEST_KEY_PW"], capture_output=True, env=env)
kpub = json.load(open(os.path.join(kdir, "k-enc.public.json"), encoding="utf-8"))
check("T4. выданная лицензия проверяется открытым ключом",
      r.returncode == 0 and S.verify_license(open(out_l, "rb").read(), S.trusted_set([kpub]))["license_id"] == "L-0001", r.stderr[-300:])
inrepo_key = os.path.join(REPO, "tools", "_probe_key.pem")
try:
    open(inrepo_key, "wb").write(pem)
    r = subprocess.run(tool + ["sign-license", "--key", inrepo_key, "--key-id", "k-enc", "--spec", spec_p,
                               "--out", os.path.join(TMP, "x.fmlic"), "--passphrase-env", "FM_TEST_KEY_PW"], capture_output=True, env=env)
    check("T5. закрытый ключ из папки проекта не читается", r.returncode != 0 and not os.path.exists(os.path.join(TMP, "x.fmlic")))
finally:
    if os.path.exists(inrepo_key):
        os.remove(inrepo_key)

# ════════════════════════════════════════════════════════════════════════════
section("9. никакой сети")
NET = {"socket", "urllib", "http", "requests", "httpx", "ssl", "ftplib", "smtplib", "websocket", "websockets"}
paths = [os.path.join(REPO, "app", "licensing", n) for n in os.listdir(os.path.join(REPO, "app", "licensing")) if n.endswith(".py")]
paths += [os.path.join(REPO, "tools", "module_package.py"), os.path.join(REPO, "tools", "fm_license_tool.py"),
          os.path.join(DEMO_PAID, "backend.py"), os.path.join(DEMO_FREE, "backend.py")]
net_hits = []
for pth in paths:
    tree = ast.parse(open(pth, encoding="utf-8").read())
    for node in ast.walk(tree):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        for n in names:
            if n.split(".")[0] in NET:
                net_hits.append("%s: %s" % (os.path.basename(pth), n))
check("W1. код лицензирования, упаковщик, утилита и демо-модули не обращаются к сети", not net_hits, net_hits)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 76)
if FAILS:
    print("FAIL: провалено %d из %d" % (len(FAILS), len(FAILS) + PASSED[0]))
    for f in FAILS:
        print("   - " + f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % PASSED[0])
sys.exit(0)
