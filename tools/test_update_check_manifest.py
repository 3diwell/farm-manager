# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-131 (29.09.2026) — проверка обновлений: строгий разбор ответа сайта и выключатель фермы.

ЧТО ЗАЩИЩАЕТ. До 29.09.2026 ответ сайта о новой версии уходил на экран как есть: ссылка
javascript:, http: или на чужой сайт и текст любой длины попадали в баннер и в window.open.
Выключить проверку пользователь не мог. Здесь закрепляется:

  1. app/update_manifest.py: только https на официальный сайт, версия по шаблону, пояснение
     обрезано и без управляющих символов, размер ответа ограничен.
  2. Подпись выпуска (формат fm-release): верная подпись принимается, подпись пакета модуля
     выдать за подпись выпуска нельзя, подменённые данные отклоняются, ключ лицензий не годится.
     Пока в программе нет рабочего ключа выпуска — принимается прежний простой JSON; как только
     ключ вписан (trust.RELEASE_KEYS), неподписанный ответ отклоняется. Ключи модулей
     (PRODUCTION_KEYS) обязательную подпись выпуска НЕ включают.
  2a. Один подписанный latest.json понимают и выпуски, которые уже у пользователей (Alpha 3.0
     читает только верхние version/url/notes), и новые (проверяют подпись; верхние поля обязаны
     совпадать с подписанными).
  3. Настоящий обработчик /api/update-check (исходник из server.py, сеть подменена): выключатель
     стоит до сети, опасная ссылка и переадресация на чужой адрес не проходят.
  4. Интерфейс: переключатель «Проверять обновления» в Настройках, окно открывает только https.
  5. Утилита поставщика подписывает latest.json и не подписывает неверный.

Ключи — одноразовые, в памяти и во временной папке вне проекта. Сети нет, server.py не
запускается. Запуск:  python tools/test_update_check_manifest.py   (0 = пройдено)
"""
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.dont_write_bytecode = True

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from app import update_manifest as UM  # noqa: E402
from app.utils import _ver_tuple as _real_ver_tuple  # noqa: E402
from app.licensing import fm_license_sdk as S  # noqa: E402
from app.licensing import trust as TR  # noqa: E402

FAILS, PASSED = [], [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — " + name)
    else:
        FAILS.append(name)
        print("FAIL — " + name + (("  :: %s" % (extra,))[:400] if extra != "" else ""))


def section(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78)


def rejected(fn, *a, **k):
    try:
        fn(*a, **k)
    except UM.Rejected as e:
        return e.code
    return None


def parsed(*a, **k):
    """Разбор без исключения: dict ответа или код отказа строкой (набор не падает на откате)."""
    try:
        return UM.parse(*a, **k)
    except UM.Rejected as e:
        return {"rejected": e.code}


def J(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


GOOD_URL = "https://3diwell.com/farm/3DIWELL_Farm_Manager_Setup_3.1.exe"

section("1. Простой ответ сайта: форма, версия, адрес, пояснение")
r = UM.parse(J({"version": "Alpha 3.1", "url": GOOD_URL, "notes": "Исправления"}))
check("1.1 правильный прежний ответ принимается (подписи пока нет — signed=False)",
      r == {"latest": "Alpha 3.1", "url": GOOD_URL, "notes": "Исправления", "signed": False}, r)
check("1.2 версия без «Alpha» и ответ без ссылки и пояснения тоже законны",
      UM.parse(J({"version": "3.1"})) == {"latest": "3.1", "url": None, "notes": None, "signed": False})
check("1.2b версия «Beta 3.72» (выпуски с 25.10.2026 — Beta) принимается",
      UM.parse(J({"version": "Beta 3.72", "url": GOOD_URL}))
      == {"latest": "Beta 3.72", "url": GOOD_URL, "notes": None, "signed": False})
check("1.3 www.3diwell.com и порт 443 — тот же официальный сайт",
      UM.parse(J({"version": "3.1", "url": "https://www.3diwell.com:443/a"}))["url"]
      == "https://www.3diwell.com:443/a")
BAD_URLS = {
    "javascript": "javascript:alert(1)",
    "http": "http://3diwell.com/farm/x.exe",
    "file": "file:///C:/Windows/System32/calc.exe",
    "data": "data:text/html,<b>x</b>",
    "чужой сайт": "https://evil.example/x.exe",
    "похожий домен": "https://3diwell.com.evil.example/x.exe",
    "логин в адресе": "https://3diwell.com@evil.example/x.exe",
    #  строка склеивается, чтобы проверка открытой копии на секреты не приняла её за e-mail
    "пароль в адресе": "https://u:p" + "@" + "3diwell.com/x.exe",
    "нестандартный порт": "https://3diwell.com:8443/x.exe",
    "обратная косая": "https://3diwell.com\\@evil.example/",
    "пробел": "https://3diwell.com/a b",
    "перевод строки": "https://3diwell.com/a\nb",
    "точка в конце хоста": "https://3diwell.com./x",
    "без схемы": "//3diwell.com/x",
    "не строка": 5,
}
bad_ok = {k: rejected(UM.parse, J({"version": "3.1", "url": v})) for k, v in BAD_URLS.items()}
check("1.4 опасные и чужие ссылки отклоняются целиком (%d видов)" % len(BAD_URLS),
      all(v == UM.R_BAD_URL for v in bad_ok.values()), {k: v for k, v in bad_ok.items() if v != UM.R_BAD_URL})
BAD_VERSIONS = ["", "9.9; rm", "Alpha 9.9.9", "<b>9.9</b>", 99, None, "Gamma 3.1", "3"]
check("1.5 версия не по шаблону — отказ",
      all(rejected(UM.parse, J({"version": v, "url": GOOD_URL})) == UM.R_BAD_VERSION for v in BAD_VERSIONS),
      [v for v in BAD_VERSIONS if rejected(UM.parse, J({"version": v})) != UM.R_BAD_VERSION])
long_notes = UM.parse(J({"version": "3.1", "notes": "Ж" * 5000}))["notes"]
check("1.6 длинное пояснение обрезается до %d знаков" % UM.NOTES_MAX,
      len(long_notes) == UM.NOTES_MAX and long_notes.endswith("…"), len(long_notes))
ctrl = UM.parse(J({"version": "3.1", "notes": "a\x00b\r\nc\u202ed\u2028e\x1b[31m"}))["notes"]
check("1.7 управляющие символы и знаки смены направления текста убираются",
      not re.search(r"[\x00-\x1f\u202e\u2028]", ctrl) and ctrl.startswith("a b c d e"), repr(ctrl))
check("1.8 пояснение не строкой — отказ", rejected(UM.parse, J({"version": "3.1", "notes": ["x"]})) == UM.R_BAD_NOTES)
check("1.9 слишком большой ответ — отказ до разбора",
      rejected(UM.parse, b"{" + b" " * UM.MAX_BYTES + b"}") == UM.R_TOO_LARGE)
check("1.10 не JSON, пусто, массив — отказ",
      rejected(UM.parse, b"<html>") == UM.R_NOT_JSON and rejected(UM.parse, b"") == UM.R_NOT_JSON
      and rejected(UM.parse, b"[1]") == UM.R_BAD_FORM)
check("1.11 воспроизведение из плана: javascript:-ссылка + 5000 знаков больше не проходят",
      rejected(UM.parse, J({"version": "Alpha 9.9", "url": "javascript:alert(1)", "notes": "x" * 5000}))
      == UM.R_BAD_URL)

section("2. Подпись описания выпуска")
rel_key, pkg_key, lic_key = (Ed25519PrivateKey.generate() for _ in range(3))


def pub(k):
    return S.b64u_encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


TRUST = S.trusted_set([S.TrustedKey("t-rel", S.PURPOSE_PACKAGE, pub(rel_key), test=True),
                       S.TrustedKey("t-lic", S.PURPOSE_LICENSE, pub(lic_key), test=True)])
PAYLOAD = {"schema_version": 1, "product_id": S.PRODUCT_ID, "version": "Alpha 3.1",
           "released_at": "2026-10-01T00:00:00Z", "url": GOOD_URL, "sha256": "ab" * 32, "notes": "Новое"}
signed = S.sign_document(UM.FORMAT_RELEASE, PAYLOAD, rel_key, "t-rel")
r = UM.parse(S.dump_document(signed), TRUST, require_signature=True)
check("2.1 верная подпись ключом выпуска принимается (signed=True)",
      r == {"latest": "Alpha 3.1", "url": GOOD_URL, "notes": "Новое", "signed": True}, r)
as_pkg = S.sign_document(S.FORMAT_PACKAGE, PAYLOAD, rel_key, "t-rel")
as_pkg["format"] = UM.FORMAT_RELEASE
check("2.2 подпись паспорта пакета нельзя выдать за подпись выпуска (разные области подписи)",
      rejected(UM.parse, S.dump_document(as_pkg), TRUST, True) == UM.R_BAD_SIGNATURE)
check("2.3 документ другого формата (fm-package) как ответ сайта не принимается",
      rejected(UM.parse, S.dump_document(S.sign_document(S.FORMAT_PACKAGE, PAYLOAD, rel_key, "t-rel")),
               TRUST, True) == UM.R_BAD_FORM)
tampered = json.loads(json.dumps(signed))
tampered["payload"]["url"] = "https://3diwell.com/farm/other.exe"
check("2.4 подменённые данные при верной на вид подписи — отказ",
      rejected(UM.parse, S.dump_document(tampered), TRUST, True) == UM.R_BAD_SIGNATURE)
check("2.5 ключ лицензий подписывать выпуск не может",
      rejected(UM.parse, S.dump_document(S.sign_document(UM.FORMAT_RELEASE, PAYLOAD, lic_key, "t-lic")),
               TRUST, True) == UM.R_BAD_SIGNATURE)
check("2.6 чужой ключ (не из доверенных) — отказ",
      rejected(UM.parse, S.dump_document(S.sign_document(UM.FORMAT_RELEASE, PAYLOAD, pkg_key, "t-rel")),
               TRUST, True) == UM.R_BAD_SIGNATURE)
evil = dict(PAYLOAD, url="javascript:alert(1)")
check("2.7 даже верно подписанная опасная ссылка отклоняется",
      rejected(UM.parse, S.dump_document(S.sign_document(UM.FORMAT_RELEASE, evil, rel_key, "t-rel")),
               TRUST, True) == UM.R_BAD_URL)
extra = dict(PAYLOAD, evil="x")
check("2.8 лишнее поле в подписанных данных — отказ",
      rejected(UM.parse, S.dump_document(S.sign_document(UM.FORMAT_RELEASE, extra, rel_key, "t-rel")),
               TRUST, True) == UM.R_BAD_FORM)
check("2.9 подпись обязательна — простой ответ отклоняется",
      rejected(UM.parse, J({"version": "3.1", "url": GOOD_URL}), TRUST, True) == UM.R_SIGNATURE_REQUIRED)
r = UM.parse(S.dump_document(signed), {}, require_signature=False)
check("2.10 ключа выпуска в программе нет: подписанный файл сайта принимается по строгой форме, "
      "но честно как непроверенный (прежние выпуски продолжают видеть новую версию)",
      r.get("signed") is False and r.get("url") == GOOD_URL, r)
check("2.11 …и опасная ссылка в нём всё равно отклоняется",
      rejected(UM.parse, S.dump_document(S.sign_document(UM.FORMAT_RELEASE, evil, rel_key, "t-rel")), {},
               False) == UM.R_BAD_URL)
check("2.12 чужой product_id в верно подписанных данных — отказ",
      rejected(UM.parse, S.dump_document(S.sign_document(UM.FORMAT_RELEASE, dict(PAYLOAD, product_id="other-app"),
                                                         rel_key, "t-rel")), TRUST, True) == UM.R_BAD_FORM)
check("2.13 есть только тестовые ключи (подпись не обязательна), а подпись неверна — всё равно отказ",
      rejected(UM.parse, S.dump_document(tampered), TRUST, False) == UM.R_BAD_SIGNATURE
      and rejected(UM.parse, S.dump_document(S.sign_document(UM.FORMAT_RELEASE, PAYLOAD, pkg_key, "t-rel")),
                   TRUST, False) == UM.R_BAD_SIGNATURE)

section("2a. Один файл на сайте для старых и новых выпусков (верхние version/url/notes)")
legacy = UM.with_legacy_fields(signed)
LEG = S.dump_document(legacy)


def read_like_alpha_30(raw):
    """Как читает ответ выпуск Alpha 3.0 и раньше (server.py до R-131): только верхние поля."""
    data = json.loads(raw.decode("utf-8", "replace"))
    return str(data.get("version", "")).strip(), data.get("url") or None, data.get("notes") or None


check("2a.1 выпуск Alpha 3.0 видит в подписанном файле новую версию, ссылку и пояснение",
      read_like_alpha_30(LEG) == ("Alpha 3.1", GOOD_URL, "Новое"), read_like_alpha_30(LEG))
check("2a.2 …а без верхних полей не видел бы ничего (поэтому они нужны)",
      read_like_alpha_30(S.dump_document(signed))[0] == "")
r = parsed(LEG, TRUST, require_signature=True)
check("2a.3 новый выпуск с ключом: тот же файл проверяется по подписи и принимается",
      r == {"latest": "Alpha 3.1", "url": GOOD_URL, "notes": "Новое", "signed": True}, r)
r = parsed(LEG, {}, require_signature=False)
check("2a.4 новый выпуск без ключа: тот же файл принимается по строгой форме (signed=False)",
      isinstance(r, dict) and r.get("signed") is False and r.get("latest") == "Alpha 3.1", r)
bad_top = {}
for f, v in (("version", "Alpha 9.9"), ("url", "https://3diwell.com/farm/other.exe"), ("notes", "Другое")):
    d = dict(legacy)
    d[f] = v
    bad_top[f] = (rejected(UM.parse, S.dump_document(d), TRUST, True), rejected(UM.parse, S.dump_document(d), {}, False))
check("2a.5 верхнее поле расходится с подписанным — файл отклоняется (и с ключом, и без)",
      all(v == (UM.R_BAD_FORM, UM.R_BAD_FORM) for v in bad_top.values()), bad_top)
no_notes = dict(legacy)
no_notes.pop("notes")
check("2a.6 верхние поля необязательны: без notes сверху файл принимается",
      (parsed(S.dump_document(no_notes), TRUST, True) or {}).get("signed") is True)
check("2a.7 постороннее верхнее поле — отказ",
      rejected(UM.parse, S.dump_document(dict(legacy, evil="x")), TRUST, True) == UM.R_BAD_FORM
      and rejected(UM.parse, S.dump_document(dict(legacy, evil="x")), {}, False) == UM.R_BAD_FORM)
check("2a.8 документ без подписи (нет sig) — отказ",
      rejected(UM.parse, J({k: v for k, v in legacy.items() if k != "sig"}), {}, False) == UM.R_BAD_FORM)

section("3. Когда подпись становится обязательной (app/licensing/trust.py)")
check("3.1 сейчас рабочих ключей выпуска нет — подпись не обязательна",
      TR.RELEASE_KEYS == () and TR.release_signature_required() is False)
_saved = (TR.PRODUCTION_KEYS, TR.RELEASE_KEYS)
try:
    TR.PRODUCTION_KEYS = ({"key_id": "vendor-pkg", "purpose": "package", "public_key": pub(pkg_key)},)
    check("3.2 ключ МОДУЛЕЙ обязательную подпись выпуска не включает и выпуск не подписывает",
          TR.release_signature_required() is False and "vendor-pkg" not in TR.release_keys())
    TR.RELEASE_KEYS = ({"key_id": "vendor-rel", "purpose": "package", "public_key": pub(rel_key)},)
    keys = TR.release_keys()
    check("3.3 вписан рабочий ключ выпуска — подпись обязательна, ключ среди доверенных",
          TR.release_signature_required() is True and "vendor-rel" in keys and not keys["vendor-rel"].test)
    doc = S.dump_document(S.sign_document(UM.FORMAT_RELEASE, PAYLOAD, rel_key, "vendor-rel"))
    check("3.4 с рабочим ключом: подписанный принимается, простой — нет",
          UM.parse(doc, keys, TR.release_signature_required())["signed"] is True
          and rejected(UM.parse, J({"version": "3.1"}), keys, TR.release_signature_required())
          == UM.R_SIGNATURE_REQUIRED)
finally:
    TR.PRODUCTION_KEYS, TR.RELEASE_KEYS = _saved

section("4. Настоящий обработчик /api/update-check (сеть подменена)")
SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)
fn = next((n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "api_update_check"), None)
UPD = ast.get_source_segment(SRC, fn) if fn else ""
check("4.1 обработчик найден", bool(UPD))
lines = {}
for n in ast.walk(ast.parse(UPD)):
    if isinstance(n, ast.If):
        d = ast.dump(n.test)
        if "_E2E" in d:
            lines.setdefault("iso", n.lineno)
        if "farm_update_check" in d:
            lines.setdefault("switch", n.lineno)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "urlopen":
        lines.setdefault("net", n.lineno)
check("4.2 порядок: изоляция -> выключатель -> сеть",
      lines.get("iso", 99) < lines.get("switch", 99) < lines.get("net", 0), lines)
check("4.3 ответ разбирает только строгий разборщик, с ключами выпуска",
      "_upd_manifest.parse(raw, _lic_trust.release_keys()," in UPD and "json.loads" not in UPD
      and "_upd_manifest.check_url(r.geturl())" in UPD and "r.read(_upd_manifest.MAX_BYTES + 1)" in UPD)
check("4.4 выключатель — настройка фермы, по умолчанию включено; ключ в списке настроек",
      '_get_setting("farm_update_check", "1") == "0"' in UPD
      and re.search(r'_FARM_SETTINGS_KEYS = \([^)]*"update_check"\)', SRC) is not None
      and 'vals["update_check"] not in ("0", "1")' in SRC)


class FakeResp(object):
    def __init__(self, body, url):
        self.body, self.url = body, url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self.url

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]


def run_handler(setting="1", body=b"", final_url="https://3diwell.com/farm/latest.json", app_version="Alpha 3.0"):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        return FakeResp(body, final_url)

    import urllib.request as _ur
    fake_urllib = types.SimpleNamespace(request=types.SimpleNamespace(Request=_ur.Request, urlopen=urlopen))
    ns = {"time": __import__("time"), "APP_VERSION": app_version, "_E2E": None,
          "_get_setting": lambda k, d="": setting if k == "farm_update_check" else d,
          "_update_cache": {"ts": 0.0, "data": None}, "_UPDATE_TTL": 1800,
          "UPDATE_MANIFEST_URL": "https://3diwell.com/farm/latest.json", "urllib": fake_urllib,
          "_upd_manifest": UM, "_lic_trust": TR, "json": json,
          #  25.10.2026: тот же разбор номера, что у сервера (app/utils.py), а не его копия.
          "_ver_tuple": _real_ver_tuple,
          "log": types.SimpleNamespace(debug=lambda *a, **k: None)}
    exec(UPD, ns)  # noqa: S102 — свой исходник в песочнице
    return ns["api_update_check"](), calls


res, calls = run_handler("0", J({"version": "Alpha 9.9", "url": GOOD_URL}))
check("4.5 выключено: на сайт не ходим вовсе, ответ «выключено»",
      calls == [] and res.get("disabled") is True and res.get("update_available") is False, (res, calls))
res, calls = run_handler("1", J({"version": "Alpha 9.9", "url": GOOD_URL, "notes": "x" * 5000}))
check("4.6 включено: новая версия видна, ссылка официальная, пояснение обрезано",
      len(calls) == 1 and res.get("ok") is True and res.get("update_available") is True
      and res.get("url") == GOOD_URL and len(res.get("notes") or "") == UM.NOTES_MAX, res)
res, _ = run_handler("1", J({"version": "Alpha 9.9", "url": "javascript:alert(1)", "notes": "x" * 5000}))
check("4.7 воспроизведение: javascript:-ссылка — баннера нет, ссылка на экран не уходит",
      res.get("ok") is False and res.get("update_available") is False and res.get("url") is None, res)
res, _ = run_handler("1", J({"version": "Alpha 9.9", "url": GOOD_URL}), final_url="http://evil.example/latest.json")
check("4.8 переадресация сайта на чужой или http-адрес — ответ не принимается",
      res.get("ok") is False and res.get("update_available") is False, res)
res, _ = run_handler("", J({"version": "Alpha 2.9", "url": GOOD_URL}))
check("4.9 записи нет — проверка работает как раньше; старая версия на сайте — баннера нет",
      res.get("ok") is True and res.get("update_available") is False and not res.get("disabled"), res)
#  25.10.2026: программа перешла с «Alpha 3.0» на «Beta 3.71». Номер сравнивается парой чисел,
#  префикс выпуска (Alpha или Beta) на сравнение не влияет.
_cmp = [(cur, site, run_handler("1", J({"version": site, "url": GOOD_URL}), app_version=cur)[0])
        for cur, site in (("Beta 3.71", "Beta 3.72"), ("Alpha 3.0", "Beta 3.71"), ("Beta 3.71", "Alpha 3.1"),
                          ("Beta 3.71", "Beta 3.71"), ("Beta 3.71", "Alpha 3.71"), ("Beta 3.71", "3.100"))]
check("4.10 Beta: 3.72 новее 3.71, Beta 3.71 новее Alpha 3.0; Alpha 3.1 и тот же номер с другим префиксом"
      " — не новее; «3.100» новее «3.71» (пара чисел, а не дробь)",
      [r.get("ok") and r.get("update_available") for _c, _s, r in _cmp] == [True, True, False, False, False, True],
      [(c, s, r.get("ok"), r.get("update_available")) for c, s, r in _cmp])

section("5. Интерфейс")
APP = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
IDX = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
HH = io.open(os.path.join(REPO, "web", "composables", "helpHints.js"), encoding="utf-8").read()
check("5.1 в Настройках → Общие → Программа есть переключатель по-русски и по-английски",
      'data-help="set-update-check"' in IDX and ':checked="updateCheckOn"' in IDX
      and 'setUpdateCheck($event.target.checked)' in IDX and "'Проверять обновления':'Check for updates'" in IDX
      and "О ферме ничего не отправляется." in IDX and "Nothing about your farm is sent." in IDX
      and '"set-update-check"' in HH)
_prog = IDX[IDX.find("data-tour=\"set-edition\""):IDX.find("data-tour=\"set-about\"")]
check("5.2 переключатель стоит в группе «Программа», менять его может тот, кому можно писать настройки фермы",
      "set-update-check" in _prog and ":disabled=\"!can('project')\"" in _prog)
check("5.3 значение — настройка фермы: читается при опросе настроек, пишется через /api/farm-settings",
      "_updateCheckFromServer(st.update_check);" in APP
      and "_updateCheckFromServer(s.update_check);" in APP     # выключили с другого компьютера — видно без перезагрузки
      and "_queueAutoPush({ update_check: on ? '1' : '0' })" in APP
      and "updateCheckOn, setUpdateCheck" in APP)
check("5.4 выключено — интерфейс не спрашивает сервер и прячет баннер",
      "if (!updateCheckOn.value) { updateInfo.value = null; return; }" in APP)
m = re.search(r"const updateUrlSafe = [^\n]+", APP)
check("5.5 окно загрузки открывается только для https-ссылки",
      m is not None and "if (updateUrlSafe(u)) window.open(u, '_blank')" in APP
      and "if (u) window.open(u, '_blank')" not in APP)
NODE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
if m and os.path.isfile(NODE):
    js = m.group(0) + "\nconsole.log(JSON.stringify(['javascript:alert(1)','http://3diwell.com/x','file:///c:/x'," \
                      "'https://3diwell.com/x','', null, 'не адрес'].map(updateUrlSafe)));"
    out = subprocess.run([NODE, "-e", js], capture_output=True, timeout=60).stdout.decode("utf-8", "replace").strip()
    check("5.6 исполнением: javascript:/http:/file:/пусто/мусор — нет, https — да",
          out == "[false,false,false,true,false,false,false]", out)
else:
    check("5.6 node найден для проверки исполнением", False, NODE)

section("6. Утилита поставщика: sign-release")
import fm_license_tool as FT  # noqa: E402
tmp = tempfile.mkdtemp(prefix="fm_rel_")
try:
    key_path = os.path.join(tmp, "rel.pem")
    with open(key_path, "wb") as f:
        f.write(rel_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    out_path = os.path.join(tmp, "latest.json")
    rc = FT.main(["sign-release", "--key", key_path, "--key-id", "t-rel", "--version", "Alpha 3.1",
                  "--url", GOOD_URL, "--sha256", "AB" * 32, "--released-at", "2026-10-01T00:00:00Z",
                  "--notes", "Исправления", "--out", out_path])
    raw = open(out_path, "rb").read() if os.path.isfile(out_path) else b""
    got = parsed(raw, TRUST, True) if raw else {}
    check("6.1 подписанный latest.json принимается программой как подлинный",
          rc == 0 and got.get("signed") is True and got.get("latest") == "Alpha 3.1", got)
    check("6.1a …и несёт сверху version/url/notes для выпусков Alpha 3.0 и раньше",
          bool(raw) and read_like_alpha_30(raw) == ("Alpha 3.1", GOOD_URL, "Исправления"),
          read_like_alpha_30(raw) if raw else "")
    trusted_file = os.path.join(tmp, "keys.json")
    json.dump([{"key_id": "t-rel", "purpose": "package", "public_key": pub(rel_key)}],
              open(trusted_file, "w", encoding="utf-8"))
    check("6.2 verify узнаёт описание выпуска", FT.main(["verify", "--trusted", trusted_file, out_path]) == 0)

    def refused(argv):
        try:
            FT.main(argv)
        except SystemExit as e:
            return str(e.code or "")
        return ""
    base = ["sign-release", "--key", key_path, "--key-id", "t-rel", "--version", "Alpha 3.1",
            "--sha256", "ab" * 32, "--released-at", "2026-10-01T00:00:00Z", "--out", os.path.join(tmp, "x.json")]
    check("6.3 опасную ссылку утилита подписывать отказывается",
          "bad_url" in refused(base + ["--url", "javascript:alert(1)"]) and not os.path.exists(os.path.join(tmp, "x.json")))
    check("6.4 длинное пояснение утилита не обрезает молча, а отказывает",
          "пояснение" in refused(base + ["--url", GOOD_URL, "--notes", "x" * 400]))
    inside = os.path.join(REPO, "no-such-dir", "k.pem")
    check("6.5 закрытый ключ внутри папки проекта не читается",
          "внутри папки проекта" in refused(["sign-release", "--key", inside, "--key-id", "t", "--version", "3.1",
                                             "--url", GOOD_URL, "--sha256", "ab" * 32,
                                             "--released-at", "2026-10-01T00:00:00Z",
                                             "--out", os.path.join(tmp, "y.json")]))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

section("7. Разборщик без сети и без побочных действий")
UMSRC = io.open(os.path.join(REPO, "app", "update_manifest.py"), encoding="utf-8").read()
check("7.1 в app/update_manifest.py нет сети, файлов и процессов",
      not re.search(r"\b(urlopen|socket|requests|http\.client|subprocess|open\()", UMSRC))

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILS)))
for f in FAILS:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILS else 0)
