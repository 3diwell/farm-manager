# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Разбор ответа сайта о новой версии (R-131, 29.09.2026).

ЗАЧЕМ. Проверка обновлений раз в несколько часов берёт с сайта маленький latest.json и
показывает в интерфейсе баннер с кнопкой. До 29.09.2026 ответ принимался как есть: ссылка
javascript:, http: или на чужой сайт и сколь угодно длинный текст уходили прямо на экран.
Здесь ответ проверяется целиком, прежде чем хоть что-то из него покажется пользователю.

ЧТО ПРИНИМАЕТСЯ.
  * Размер ответа — не больше MAX_BYTES; это JSON-объект в UTF-8.
  * Версия — «3.1», «Alpha 3.1» или «Beta 3.1» (две группы цифр).
  * Ссылка — только https на официальный сайт (ALLOWED_HOSTS), без логина и пароля в адресе,
    без нестандартного порта. Не та ссылка = не тот ответ целиком: баннера не будет.
  * Пояснение — строка; управляющие символы убираются, длина обрезается до NOTES_MAX.

ПОДПИСЬ. Подписанное описание выпуска — документ того же вида, что лицензии и паспорта модулей
(app/licensing/fm_license_sdk.py), с форматом FORMAT_RELEASE:

    {"format": "fm-release", "v": 1,
     "payload": {"schema_version": 1, "product_id": "3diwell-fm", "version": "Alpha 3.1",
                 "released_at": "2026-10-01T00:00:00Z", "url": "https://3diwell.com/...",
                 "sha256": "<64 hex установщика>", "notes": "...", "key_id": "..."},
     "sig": {"alg": "Ed25519", "key_id": "...", "value": "..."}}

  * Пока в app/licensing/trust.py нет рабочего ключа выпуска (RELEASE_KEYS пуст), принимается и
    прежний простой {"version", "url", "notes"}, и подписанный документ — но подпись такого
    документа проверить нечем, поэтому он принимается по тем же строгим правилам формы, что и
    простой ответ, с пометкой signed=False.
  * Как только рабочий ключ вписан — принимается ТОЛЬКО документ с верной подписью этим ключом.

ОДИН ФАЙЛ ДЛЯ СТАРЫХ И НОВЫХ ВЫПУСКОВ. Выпуски до этой правки (Alpha 3.0 и раньше, они уже у
пользователей) читают из latest.json только верхние поля version, url и notes. Поэтому подписанный
документ несёт их копию СВЕРХУ (LEGACY_FIELDS; утилита sign-release кладёт их сама, см.
with_legacy_fields):

    {"format": "fm-release", "v": 1, "payload": {...}, "sig": {...},
     "version": "Alpha 3.1", "url": "https://3diwell.com/...", "notes": "..."}

Старый выпуск видит обычный ответ и показывает баннер; новый снимает верхние поля ДО проверки
подписи (они не подписаны и ничего не решают) и работает только с подписанным payload. Верхние
поля обязаны совпадать с подписанными — иначе старые и новые выпуски увидели бы разное, и такой
файл отклоняется как ошибка публикации (замечание проверки R-131, 29.09.2026).

Модуль чистый: без сети, без базы, без часов. Сеть — забота вызывающего (server.py).
"""
import json
import re
import urllib.parse

from app.licensing import fm_license_sdk as S

FORMAT_RELEASE = "fm-release"
ALLOWED_HOSTS = ("3diwell.com", "www.3diwell.com")
MAX_BYTES = 64 * 1024
NOTES_MAX = 300
URL_MAX = 500
RELEASE_FIELDS = ("schema_version", "product_id", "version", "released_at", "url", "sha256", "notes",
                  "key_id")
RELEASE_REQUIRED = ("schema_version", "product_id", "version", "released_at", "url", "sha256", "key_id")
DOC_FIELDS = ("format", "v", "payload", "sig")
#  Верхние поля для выпусков до R-131 (они читают только их): копия подписанных, без подписи.
LEGACY_FIELDS = ("version", "url", "notes")

_VERSION_RE = re.compile(r"\A(?:(?:Alpha|Beta) )?\d{1,4}\.\d{1,6}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f  ​-‏‪-‮⁦-⁩]")

# Причины отказа (для журнала; пользователю не показываются — он просто не увидит баннера).
R_TOO_LARGE = "too_large"
R_NOT_JSON = "not_json"
R_BAD_FORM = "bad_form"
R_BAD_VERSION = "bad_version"
R_BAD_URL = "bad_url"
R_BAD_NOTES = "bad_notes"
R_SIGNATURE_REQUIRED = "signature_required"
R_BAD_SIGNATURE = "bad_signature"


class Rejected(Exception):
    def __init__(self, code, detail=""):
        Exception.__init__(self, "%s: %s" % (code, detail) if detail else code)
        self.code = code
        self.detail = detail


def check_url(url):
    """Ссылка на загрузку -> та же строка, если это https на официальный сайт; иначе Rejected."""
    if not isinstance(url, str) or not url or len(url) > URL_MAX:
        raise Rejected(R_BAD_URL, "не строка или слишком длинная")
    if url != url.strip() or _CTRL_RE.search(url) or any(c in url for c in ' \\"<>`'):
        raise Rejected(R_BAD_URL, "пробелы или служебные символы")
    try:
        u = urllib.parse.urlsplit(url)
        port = u.port
    except ValueError:
        raise Rejected(R_BAD_URL, "адрес не разбирается")
    if u.scheme != "https":
        raise Rejected(R_BAD_URL, "только https")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise Rejected(R_BAD_URL, "логин в адресе")
    if port not in (None, 443):
        raise Rejected(R_BAD_URL, "нестандартный порт")
    host = (u.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise Rejected(R_BAD_URL, "чужой сайт")
    #  Хост в адресе обязан быть записан ровно так, как его понял разборщик (без обходов вида
    #  «3diwell.com.» или точек-двойников).
    if u.netloc.lower() not in (host, host + ":443"):
        raise Rejected(R_BAD_URL, "хост записан необычно")
    return url


def check_version(v):
    if not isinstance(v, str) or not _VERSION_RE.match(v.strip()):
        raise Rejected(R_BAD_VERSION)
    return v.strip()


def clean_notes(n):
    """Пояснение к выпуску -> короткая строка без управляющих символов или None."""
    if n is None or n == "":
        return None
    if not isinstance(n, str):
        raise Rejected(R_BAD_NOTES, "не строка")
    s = " ".join(_CTRL_RE.sub(" ", n).split())
    if not s:
        return None
    if len(s) > NOTES_MAX:
        s = s[:NOTES_MAX - 1].rstrip() + "…"
    return s


def _check_release_payload(p):
    if not isinstance(p, dict):
        raise Rejected(R_BAD_FORM, "payload")
    extra = sorted(set(p) - set(RELEASE_FIELDS))
    if extra:
        raise Rejected(R_BAD_FORM, "лишние поля: %s" % ", ".join(extra))
    missing = [f for f in RELEASE_REQUIRED if f not in p]
    if missing:
        raise Rejected(R_BAD_FORM, "нет полей: %s" % ", ".join(missing))
    if p.get("schema_version") != 1 or isinstance(p.get("schema_version"), bool):
        raise Rejected(R_BAD_FORM, "schema_version")
    if p.get("product_id") != S.PRODUCT_ID:
        raise Rejected(R_BAD_FORM, "product_id")
    try:
        S.parse_utc(p.get("released_at"), "released_at")
    except S.Rejected:
        raise Rejected(R_BAD_FORM, "released_at")
    if not isinstance(p.get("sha256"), str) or not _SHA256_RE.match(p.get("sha256")):
        raise Rejected(R_BAD_FORM, "sha256")
    return {"latest": check_version(p.get("version")), "url": check_url(p.get("url")),
            "notes": clean_notes(p.get("notes"))}


def with_legacy_fields(doc):
    """Подписанный документ выпуска -> тот же документ плюс верхние version/url/notes — копия
    подписанных полей для выпусков до R-131 (Alpha 3.0 и раньше читают только их)."""
    p = doc["payload"]
    out = dict(doc)
    out["version"] = p["version"]
    out["url"] = p["url"]
    if p.get("notes"):
        out["notes"] = p["notes"]
    return out


def parse(raw, trusted=None, require_signature=False):
    """Ответ сайта (bytes) -> {"latest", "url", "notes", "signed"} или Rejected.

    trusted — {key_id: TrustedKey} ключей выпуска (trust.release_keys()); require_signature —
    True, когда вписан рабочий ключ выпуска (trust.release_signature_required())."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise Rejected(R_NOT_JSON, "пустой ответ")
    if len(raw) > MAX_BYTES:
        raise Rejected(R_TOO_LARGE)
    try:
        data = json.loads(bytes(raw).decode("utf-8"))
    except Exception:
        raise Rejected(R_NOT_JSON)
    if not isinstance(data, dict):
        raise Rejected(R_BAD_FORM, "не объект")

    if "format" in data or "sig" in data or "payload" in data:
        if data.get("format") != FORMAT_RELEASE:
            raise Rejected(R_BAD_FORM, "неизвестный формат")
        if not set(DOC_FIELDS) <= set(data) or set(data) - set(DOC_FIELDS) - set(LEGACY_FIELDS):
            raise Rejected(R_BAD_FORM, "документ выпуска")
        #  Верхние поля для старых выпусков снимаются ДО проверки подписи: подписан только payload.
        doc = {k: data[k] for k in DOC_FIELDS}
        if require_signature or trusted:
            try:
                payload = S.verify_document(doc, FORMAT_RELEASE, S.PURPOSE_PACKAGE, trusted or {})
            except S.Rejected as e:
                #  Подпись есть, ключи есть, но подпись не наша: при обязательной подписи — отказ.
                #  Без обязательной (только тестовые ключи из исходников) — тоже отказ: документ,
                #  который выдаёт себя за подписанный и не проходит проверку, — подделка или порча.
                raise Rejected(R_BAD_SIGNATURE, e.code)
            signed = True
        else:
            #  Ключа выпуска в программе нет: проверить подпись нечем. Принимаем по строгой форме
            #  документа, но честно помечаем как непроверенный (см. описание модуля).
            if doc.get("v") != S.FORMAT_VERSION or isinstance(doc.get("v"), bool):
                raise Rejected(R_BAD_FORM, "документ выпуска")
            payload = doc.get("payload")
            signed = False
        out = _check_release_payload(payload)
        for f in LEGACY_FIELDS:
            if f in data and data[f] != payload.get(f):
                raise Rejected(R_BAD_FORM, "верхнее поле %s не совпадает с подписанным" % f)
        out["signed"] = signed
        return out

    if require_signature:
        raise Rejected(R_SIGNATURE_REQUIRED)
    #  Прежний простой ответ {"version", "url", "notes"}. Прочие поля не используются и не мешают.
    out = {"latest": check_version(data.get("version")),
           "url": check_url(data.get("url")) if data.get("url") not in (None, "") else None,
           "notes": clean_notes(data.get("notes")),
           "signed": False}
    return out
