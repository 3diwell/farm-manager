# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""FM License SDK — офлайн-проверка подписанных пакетов модулей и лицензий 3DIWELL Farm Manager.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. Открытое ядро FM владелец компьютера может пересобрать и изменить, поэтому
коммерческий модуль НЕ доверяет ответу ядра «лицензия есть». Модуль кладёт в свой пакет КОПИЮ этого
файла вместе со своими доверенными открытыми ключами и сам проверяет исходный подписанный документ
прямо перед платной операцией. Ядро пользуется тем же файлом для показа статусов, импорта лицензий и
проверки пакетов при установке. Файл самодостаточен: стандартная библиотека + пакет `cryptography`
(Ed25519, RFC 8032) — без импортов FM, без сети, без часов компьютера для бессрочных прав.

ЛИЦЕНЗИЯ (16.10.2026, R-149). Mozilla Public License 2.0 — как ядро; заголовок выше тот же, что
ставит выгрузка открытой копии (tools/public_export.py). Платный модуль кладёт в свой пакет копию
этого файла БЕЗ ИЗМЕНЕНИЙ (tools/module_package.py --embed-sdk копирует байты); остальной код
модуля может быть под любой лицензией — MPL 2.0 разрешает такое «более крупное произведение»
(раздел 3.3). Изменённую копию можно распространять только вместе с её исходным кодом.

ЧТО ГАРАНТИРУЕТ ПОДПИСЬ И ЧЕГО НЕТ. Без закрытого ключа поставщика нельзя изготовить лицензию или
«официальный» пакет, которые пройдут проверку. Подпись НЕ мешает изменить сам код, который её
проверяет: офлайн-приложение невозможно сделать невзламываемым. Цель — защита от простого копирования,
подделки лицензий и обхода штатного интерфейса, а не абсолютная защита.

ФОРМАТ ПОДПИСАННОГО ДОКУМЕНТА (лицензия и паспорт пакета одинаково):

    {"format": "fm-license" | "fm-package", "v": 1,
     "payload": {...подписываемые поля...},
     "sig": {"alg": "Ed25519", "key_id": "<id доверенного ключа>", "value": "<base64url подписи>"}}

Подписываются байты  b"FM-SIGNED-V1\\n" + format + b"\\n" + canonical_bytes(payload)  — разделение
областей не даёт выдать подпись паспорта пакета за подпись лицензии. canonical_bytes — JSON с
отсортированными ключами, без пробелов, UTF-8; числа только целые, float запрещён. key_id внутри
payload обязан совпадать с key_id подписи. Открытый ключ из самого документа НИКОГДА не принимается:
ключи берутся только из доверенного набора, переданного вызывающим.

ПРАВИЛО ОБНОВЛЕНИЙ (право использования отдельно от права на новые выпуски):

    release.released_at < license.updates_before

Сравниваются два подписанных значения, а не дата компьютера. Для бессрочной лицензии время компьютера
не участвует вовсе; для срочной (use_type="term") нужно текущее время — и защита от перевода часов при
полной автономности принципиально ограничена.
"""

import base64
import binascii
import datetime
import hashlib
import json
import os
import posixpath
import re
import secrets
import zlib

SDK_VERSION = "1.3"
PRODUCT_ID = "3diwell-fm"
FORMAT_LICENSE = "fm-license"
FORMAT_PACKAGE = "fm-package"
FORMAT_VERSION = 1
SCHEMA_VERSION = 1
PURPOSE_LICENSE = "license"
PURPOSE_PACKAGE = "package"
SIGN_DOMAIN = b"FM-SIGNED-V1\n"
MAX_DOCUMENT_BYTES = 512 * 1024
MAX_KEY_DOCUMENT_BYTES = 64 * 1024          # 1.3: предел распакованного ключа FMK1 (документ ~0,6 КБ)
PACKAGE_MANIFEST_NAME = "fm-package.json"   # имя паспорта пакета в корне модуля/архива

_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MODULE_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")
_UTC_RE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z\Z")
_CUSTOMER_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SIG_RE = re.compile(r"\A[A-Za-z0-9_-]{86}\Z")     # 64 байта подписи в каноническом base64url без «=»
_HEX64_RE = re.compile(r"\A[0-9a-f]{64}\Z")
CHANNELS = ("stable", "beta")
USE_TYPES = ("perpetual", "term")
LICENSING_MODELS = ("free", "paid", "freemium")

# Коды отказа — машинные, стабильные, без данных о клиенте.
R_MALFORMED = "malformed"
R_WRONG_FORMAT = "wrong_format"
R_UNKNOWN_KEY = "unknown_key"
R_BAD_SIGNATURE = "bad_signature"
R_WRONG_PRODUCT = "wrong_product"
R_UNKNOWN_FIELD = "unknown_field"
R_MISSING_FIELD = "missing_field"
R_BAD_VALUE = "bad_value"
R_NO_GRANT = "no_grant"
R_EDITION = "edition_not_granted"
R_FEATURE = "feature_not_granted"
R_USE_NOT_STARTED = "use_not_started"
R_USE_EXPIRED = "use_expired"
R_TIME_REQUIRED = "time_required"
R_BINDING = "binding_mismatch"
R_CHANNEL = "channel_not_granted"
R_RELEASE_SCOPE = "release_scope"
R_UPDATE_NOT_COVERED = "update_not_covered"
R_FILE_MISSING = "file_missing"
R_FILE_MISMATCH = "file_mismatch"
R_EXTRA_FILE = "extra_file"
R_CRYPTO_UNAVAILABLE = "crypto_unavailable"
R_RELEASE_REQUIRED = "release_required"
R_RELEASE_MISMATCH = "release_mismatch"
R_NO_PACKAGE = "no_package"


class Rejected(Exception):
    """Документ, пакет или право не приняты. code — один из R_*; detail — безопасная подсказка."""

    def __init__(self, code, detail=""):
        Exception.__init__(self, "%s: %s" % (code, detail) if detail else code)
        self.code = code
        self.detail = detail


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Каноническая сериализация и кодировки
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _check_canonical(obj, depth=0):
    if depth > 16:
        raise Rejected(R_MALFORMED, "слишком глубокая вложенность")
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, int):
        if abs(obj) > 2 ** 53:
            raise Rejected(R_BAD_VALUE, "слишком большое число")
        return
    if isinstance(obj, float):
        raise Rejected(R_MALFORMED, "дробные числа в подписанных данных запрещены")
    if isinstance(obj, str):
        return
    if isinstance(obj, list):
        for x in obj:
            _check_canonical(x, depth + 1)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise Rejected(R_MALFORMED, "ключи объекта — только строки")
            _check_canonical(v, depth + 1)
        return
    raise Rejected(R_MALFORMED, "недопустимый тип значения")


def canonical_bytes(obj):
    """Детерминированные байты для подписи: JSON, ключи по порядку, без пробелов, UTF-8."""
    _check_canonical(obj)
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (UnicodeEncodeError, ValueError):     # 1.3: одиночный суррогат («\ud800») и т. п.
        raise Rejected(R_MALFORMED, "недопустимые символы")


def signing_input(fmt, payload):
    return SIGN_DOMAIN + str(fmt).encode("ascii") + b"\n" + canonical_bytes(payload)


def b64u_encode(raw):
    return base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode("ascii")


def b64u_decode(text):
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", text or ""):
        raise Rejected(R_MALFORMED, "не base64url")
    pad = "=" * (-len(text.rstrip("=")) % 4)
    try:
        return base64.urlsafe_b64decode(text.rstrip("=") + pad)
    except (binascii.Error, ValueError):
        raise Rejected(R_MALFORMED, "не base64url")


def parse_utc(text, field):
    """Строго «ГГГГ-ММ-ДДTчч:мм:ссZ» -> aware datetime UTC. Иначе Rejected(bad_value)."""
    m = _UTC_RE.match(text) if isinstance(text, str) else None
    if not m:
        raise Rejected(R_BAD_VALUE, "%s: ожидается дата вида 2027-10-01T00:00:00Z" % field)
    try:
        return datetime.datetime(*[int(x) for x in m.groups()], tzinfo=datetime.timezone.utc)
    except ValueError:
        raise Rejected(R_BAD_VALUE, "%s: несуществующая дата" % field)


def format_utc(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Доверенные ключи и подпись
# ──────────────────────────────────────────────────────────────────────────────────────────────

class TrustedKey(object):
    """Доверенный ОТКРЫТЫЙ ключ поставщика. purpose — license или package: ключи разделены."""

    __slots__ = ("key_id", "purpose", "public_key", "label", "test")

    def __init__(self, key_id, purpose, public_key, label="", test=False):
        if not _ID_RE.match(str(key_id or "")):
            raise ValueError("недопустимый key_id")
        if purpose not in (PURPOSE_LICENSE, PURPOSE_PACKAGE):
            raise ValueError("недопустимое назначение ключа")
        raw = b64u_decode(public_key) if isinstance(public_key, str) else bytes(public_key)
        if len(raw) != 32:
            raise ValueError("открытый ключ Ed25519 — 32 байта")
        self.key_id = str(key_id)
        self.purpose = purpose
        self.public_key = raw
        self.label = str(label or "")
        self.test = bool(test)


def trusted_set(keys):
    """[TrustedKey|dict, ...] -> {key_id: TrustedKey}. Повтор key_id — ошибка, а не молчаливая замена."""
    out = {}
    for k in keys or ():
        if isinstance(k, dict):
            k = TrustedKey(k.get("key_id"), k.get("purpose"), k.get("public_key"), k.get("label", ""),
                           bool(k.get("test")))
        if k.key_id in out:
            raise ValueError("ключ %s указан дважды" % k.key_id)
        out[k.key_id] = k
    return out


def _ed25519():
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.exceptions import InvalidSignature
        return ed25519, InvalidSignature
    except Exception:
        raise Rejected(R_CRYPTO_UNAVAILABLE, "нет библиотеки cryptography")


def verify_signature(public_key_raw, message, signature):
    ed25519, InvalidSignature = _ed25519()
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(bytes(public_key_raw)).verify(bytes(signature), bytes(message))
    except InvalidSignature:
        raise Rejected(R_BAD_SIGNATURE)
    except Exception:
        raise Rejected(R_BAD_SIGNATURE)


def _pairs_no_repeats(pairs):
    """1.3: повтор ключа в объекте JSON (в том числе записанного по-разному: "a" и "\\u0061") — отказ.
    Иначе разные разборщики видели бы разные данные под одной подписью."""
    out = {}
    for k, v in pairs:
        if k in out:
            raise Rejected(R_MALFORMED, "повтор ключа JSON")
        out[k] = v
    return out


def _no_constant(name):
    raise Rejected(R_MALFORMED, "NaN и Infinity в JSON запрещены")


def load_document(raw):
    """bytes|str|dict -> dict документа (без проверки подписи). Размер и тип ограничены; повтор ключа
    JSON и NaN/Infinity — отказ (1.3)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > MAX_DOCUMENT_BYTES:
        raise Rejected(R_MALFORMED, "документ пуст или слишком велик")
    try:
        doc = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_pairs_no_repeats,
                         parse_constant=_no_constant)
    except Rejected:
        raise
    except Exception:
        raise Rejected(R_MALFORMED, "не JSON")
    if not isinstance(doc, dict):
        raise Rejected(R_MALFORMED, "не объект")
    return doc


def verify_document(raw, fmt, purpose, trusted):
    """Проверить подпись документа -> payload (dict). Схему payload проверяет вызывающий
    (validate_license / validate_package). trusted — {key_id: TrustedKey}."""
    doc = load_document(raw)
    if set(doc.keys()) != {"format", "v", "payload", "sig"}:
        raise Rejected(R_MALFORMED, "лишние или недостающие поля документа")
    if doc.get("format") != fmt:
        raise Rejected(R_WRONG_FORMAT, "ожидается %s" % fmt)
    if doc.get("v") != FORMAT_VERSION or isinstance(doc.get("v"), bool):
        raise Rejected(R_WRONG_FORMAT, "неизвестная версия формата")
    sig, payload = doc.get("sig"), doc.get("payload")
    if not isinstance(sig, dict) or set(sig.keys()) != {"alg", "key_id", "value"}:
        raise Rejected(R_MALFORMED, "поле sig")
    if sig.get("alg") != "Ed25519":
        raise Rejected(R_WRONG_FORMAT, "поддерживается только Ed25519")
    if not isinstance(payload, dict):
        raise Rejected(R_MALFORMED, "поле payload")
    key = (trusted or {}).get(sig.get("key_id")) if isinstance(sig.get("key_id"), str) else None
    if key is None or key.purpose != purpose:
        raise Rejected(R_UNKNOWN_KEY)
    if payload.get("key_id") != key.key_id:
        raise Rejected(R_BAD_SIGNATURE, "key_id внутри данных не совпадает с подписью")
    sv = sig.get("value")
    if not isinstance(sv, str) or not _SIG_RE.match(sv):
        raise Rejected(R_BAD_SIGNATURE, "подпись не в каноническом base64url")
    signature = b64u_decode(sv)
    if len(signature) != 64 or b64u_encode(signature) != sv:
        raise Rejected(R_BAD_SIGNATURE, "подпись не в каноническом base64url")
    verify_signature(key.public_key, signing_input(fmt, payload), signature)
    return payload


def sign_document(fmt, payload, private_key, key_id):
    """Подписать payload закрытым ключом (ТОЛЬКО для утилиты поставщика и тестов). -> dict документа.
    private_key — объект cryptography Ed25519PrivateKey или 32 байта seed."""
    ed25519, _ = _ed25519()
    if isinstance(private_key, (bytes, bytearray)):
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(bytes(private_key))
    body = dict(payload)
    body["key_id"] = key_id
    sig = private_key.sign(signing_input(fmt, body))
    return {"format": fmt, "v": FORMAT_VERSION, "payload": body,
            "sig": {"alg": "Ed25519", "key_id": key_id, "value": b64u_encode(sig)}}


def dump_document(doc):
    """Документ -> байты для файла (читаемый JSON; подпись от форматирования файла не зависит)."""
    return (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Схемы: строгая проверка полей
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _req(p, field, kind):
    if field not in p:
        raise Rejected(R_MISSING_FIELD, field)
    v = p[field]
    if kind is int and (not isinstance(v, int) or isinstance(v, bool)):
        raise Rejected(R_BAD_VALUE, field)
    if kind is not int and not isinstance(v, kind):
        raise Rejected(R_BAD_VALUE, field)
    return v


def _only(p, allowed):
    extra = sorted(set(p.keys()) - set(allowed))
    if extra:
        raise Rejected(R_UNKNOWN_FIELD, ", ".join(extra[:5]))


LICENSE_FIELDS = ("schema_version", "product_id", "license_id", "customer_ref", "grants", "use_type",
                  "use_valid_from", "use_valid_until", "updates_before", "release_scope", "channel",
                  "installation_binding", "issued_at", "key_id")
GRANT_FIELDS = ("module_id", "edition", "features")


def validate_license(p):
    """Строгая схема лицензии. Нет даты — это НЕ «бессрочно»: обязательные поля обязательны."""
    if not isinstance(p, dict):
        raise Rejected(R_MALFORMED, "payload")
    _only(p, LICENSE_FIELDS)
    if _req(p, "schema_version", int) != SCHEMA_VERSION:
        raise Rejected(R_WRONG_FORMAT, "schema_version")
    if _req(p, "product_id", str) != PRODUCT_ID:
        raise Rejected(R_WRONG_PRODUCT)
    if not _ID_RE.match(_req(p, "license_id", str)):
        raise Rejected(R_BAD_VALUE, "license_id")
    if "customer_ref" in p and (not isinstance(p["customer_ref"], str) or not _CUSTOMER_RE.match(p["customer_ref"])):
        raise Rejected(R_BAD_VALUE, "customer_ref")
    grants = _req(p, "grants", list)
    if not grants or len(grants) > 64:
        raise Rejected(R_BAD_VALUE, "grants")
    seen = set()
    for g in grants:
        if not isinstance(g, dict):
            raise Rejected(R_BAD_VALUE, "grants")
        _only(g, GRANT_FIELDS)
        if not _MODULE_ID_RE.match(_req(g, "module_id", str)):
            raise Rejected(R_BAD_VALUE, "grants.module_id")
        if not _ID_RE.match(_req(g, "edition", str)):
            raise Rejected(R_BAD_VALUE, "grants.edition")
        feats = _req(g, "features", list)
        if len(feats) > 128 or any(not isinstance(f, str) or not (f == "*" or _ID_RE.match(f)) for f in feats):
            raise Rejected(R_BAD_VALUE, "grants.features")
        if (g["module_id"], g["edition"]) in seen:         # 1.3: права в лицензии уникальны
            raise Rejected(R_BAD_VALUE, "grants: повтор модуля")
        seen.add((g["module_id"], g["edition"]))
    use_type = _req(p, "use_type", str)
    if use_type not in USE_TYPES:
        raise Rejected(R_BAD_VALUE, "use_type")
    if use_type == "term":
        a = parse_utc(_req(p, "use_valid_from", str), "use_valid_from")
        b = parse_utc(_req(p, "use_valid_until", str), "use_valid_until")
        if not a < b:
            raise Rejected(R_BAD_VALUE, "use_valid_from < use_valid_until")
    elif "use_valid_from" in p or "use_valid_until" in p:
        raise Rejected(R_BAD_VALUE, "у бессрочной лицензии нет срока использования")
    parse_utc(_req(p, "updates_before", str), "updates_before")
    parse_utc(_req(p, "issued_at", str), "issued_at")
    if "channel" in p and p["channel"] not in CHANNELS:
        raise Rejected(R_BAD_VALUE, "channel")
    if "release_scope" in p:
        rs = p["release_scope"]
        if not isinstance(rs, dict):
            raise Rejected(R_BAD_VALUE, "release_scope")
        _only(rs, ("max_major",))
        mm = _req(rs, "max_major", int)
        if mm < 0:
            raise Rejected(R_BAD_VALUE, "release_scope.max_major")
    if "installation_binding" in p:
        ib = p["installation_binding"]
        if not isinstance(ib, dict):
            raise Rejected(R_BAD_VALUE, "installation_binding")
        _only(ib, ("install_id",))
        if not _ID_RE.match(_req(ib, "install_id", str)):
            raise Rejected(R_BAD_VALUE, "installation_binding.install_id")
    if not _ID_RE.match(_req(p, "key_id", str)):
        raise Rejected(R_BAD_VALUE, "key_id")
    return p


PACKAGE_FIELDS = ("schema_version", "product_id", "module_id", "edition", "version", "channel", "released_at",
                  "core_contract", "licensing", "entry", "files", "key_id")


_WIN_RESERVED = re.compile(r"\A(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?\Z", re.I)
_BAD_NAME_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def path_problem(path):
    """Что не так с путём файла пакета — или "" если путь годится. Кроме «..» и абсолютных путей
    отсекаются имена, которые Windows молча переделывает: «backend.py.» и «backend.py » ложатся
    в тот же файл backend.py, а CON, NUL и т. п. — не файлы вовсе."""
    if not isinstance(path, str) or not path or len(path) > 240 or "\\" in path:
        return "недопустимый путь"
    n = posixpath.normpath(path)
    if n != path or n.startswith("/") or n.startswith("../") or n == "..":
        return "путь выходит за папку модуля"
    for part in n.split("/"):
        if not part or part in (".", ".."):
            return "пустая часть пути"
        if part[-1] in ". ":
            return "имя кончается точкой или пробелом"
        if _BAD_NAME_CHARS.search(part):
            return "недопустимый символ в имени"
        if _WIN_RESERVED.match(part):
            return "зарезервированное имя Windows"
    return ""


def _norm_rel(path):
    """Путь файла пакета: только прямые слэши, без «..», без абсолютных и без пустых частей."""
    why = path_problem(path)
    if why:
        raise Rejected(R_BAD_VALUE, "files: %s" % why)
    return path


def validate_package(p):
    if not isinstance(p, dict):
        raise Rejected(R_MALFORMED, "payload")
    _only(p, PACKAGE_FIELDS)
    if _req(p, "schema_version", int) != SCHEMA_VERSION:
        raise Rejected(R_WRONG_FORMAT, "schema_version")
    if _req(p, "product_id", str) != PRODUCT_ID:
        raise Rejected(R_WRONG_PRODUCT)
    if not _MODULE_ID_RE.match(_req(p, "module_id", str)):
        raise Rejected(R_BAD_VALUE, "module_id")
    if not _ID_RE.match(_req(p, "edition", str)):
        raise Rejected(R_BAD_VALUE, "edition")
    v = _req(p, "version", str)
    if not v or len(v) > 32:
        raise Rejected(R_BAD_VALUE, "version")
    if _req(p, "channel", str) not in CHANNELS:
        raise Rejected(R_BAD_VALUE, "channel")
    parse_utc(_req(p, "released_at", str), "released_at")
    if len(_req(p, "core_contract", str)) > 32:
        raise Rejected(R_BAD_VALUE, "core_contract")
    lic = _req(p, "licensing", dict)
    _only(lic, ("model", "paid_features"))
    if _req(lic, "model", str) not in LICENSING_MODELS:
        raise Rejected(R_BAD_VALUE, "licensing.model")
    pf = lic.get("paid_features", [])
    if not isinstance(pf, list) or any(not isinstance(f, str) or not _ID_RE.match(f) for f in pf):
        raise Rejected(R_BAD_VALUE, "licensing.paid_features")
    if lic["model"] == "free" and pf:
        raise Rejected(R_BAD_VALUE, "у бесплатного модуля нет платных возможностей")
    ent = _req(p, "entry", dict)
    _only(ent, ("backend", "web"))
    files = _req(p, "files", dict)
    if not files or len(files) > 5000:
        raise Rejected(R_BAD_VALUE, "files")
    folded = set()
    for rel, digest in files.items():
        _norm_rel(rel)
        if not isinstance(digest, str) or not _HEX64_RE.match(digest):
            raise Rejected(R_BAD_VALUE, "files: sha256")
        if rel.casefold() in folded:
            raise Rejected(R_BAD_VALUE, "files: два имени отличаются только регистром")
        folded.add(rel.casefold())
        if is_ignored(rel) or rel == PACKAGE_MANIFEST_NAME:
            raise Rejected(R_BAD_VALUE, "files: кэш Python и паспорт пакета в состав не входят")
    for k in ("backend", "web"):
        e = ent.get(k, "")
        if not isinstance(e, str) or (e and e not in files):
            raise Rejected(R_BAD_VALUE, "entry.%s" % k)
    if not _ID_RE.match(_req(p, "key_id", str)):
        raise Rejected(R_BAD_VALUE, "key_id")
    return p


def verify_license(raw, trusted):
    """Полная проверка файла лицензии -> payload. Любое отклонение — Rejected."""
    return validate_license(verify_document(raw, FORMAT_LICENSE, PURPOSE_LICENSE, trusted))


def verify_package_manifest(raw, trusted):
    return validate_package(verify_document(raw, FORMAT_PACKAGE, PURPOSE_PACKAGE, trusted))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Состав пакета: хеши файлов
# ──────────────────────────────────────────────────────────────────────────────────────────────

IGNORED_PARTS = ("__pycache__",)


def is_ignored(rel):
    """Только папки __pycache__. 1.1: отдельный .pyc/.pyo вне __pycache__ — ЛИШНИЙ файл, а не кэш:
    Python исполняет такой файл вместо отсутствующего .py. Содержимое __pycache__ подписанного
    пакета ядро не исполняет вовсе (app/licensing/package.py грузит код из проверенных байтов)."""
    return any(p in IGNORED_PARTS for p in rel.split("/"))


def sha256_bytes(data):
    return hashlib.sha256(bytes(data)).hexdigest()


def check_files(package_payload, present):
    """present — {относительный_путь: sha256} ФАКТИЧЕСКОГО содержимого (без паспорта пакета).
    Каждый подписанный файл обязан быть на месте с тем же хешем; лишний файл — отказ: подменить
    пакет, дописав в него файл, нельзя. Не считается только содержимое папок __pycache__."""
    listed = package_payload["files"]
    for rel, digest in listed.items():
        if rel not in present:
            raise Rejected(R_FILE_MISSING, rel)
        if present[rel] != digest:
            raise Rejected(R_FILE_MISMATCH, rel)
    for rel in present:
        if rel not in listed and not is_ignored(rel) and rel != PACKAGE_MANIFEST_NAME:
            raise Rejected(R_EXTRA_FILE, rel)
    return True


def hash_tree(root):
    """{относительный_путь: sha256} всех файлов папки (кроме __pycache__). Ссылки и точки
    повторной обработки (junction) — отказ: подписанный пакет состоит только из обычных файлов."""
    import os
    out = {}
    root = os.path.abspath(root)
    for base, dirs, files in os.walk(root, followlinks=False):
        keep = []
        for d in dirs:
            full = os.path.join(base, d)
            if os.path.islink(full) or _is_reparse(full):
                raise Rejected(R_EXTRA_FILE, "ссылка вместо папки: %s" % d)
            if d not in IGNORED_PARTS:
                keep.append(d)
        dirs[:] = sorted(keep)
        for name in sorted(files):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full) or _is_reparse(full):
                raise Rejected(R_EXTRA_FILE, "ссылка вместо файла: %s" % rel)
            with open(full, "rb") as f:
                out[rel] = sha256_bytes(f.read())
    return out


def _is_reparse(path):
    import os
    import stat
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def verify_installed_package(module_dir, trusted):
    """Паспорт fm-package.json в папке модуля + проверка всех файлов. -> payload или Rejected.
    Для самопроверки коммерческого компонента: он передаёт СВОИ вшитые ключи пакетов."""
    import os
    p = os.path.join(module_dir, PACKAGE_MANIFEST_NAME)
    if not os.path.isfile(p):
        raise Rejected(R_NO_PACKAGE, "нет паспорта пакета")
    with open(p, "rb") as f:
        payload = verify_package_manifest(f.read(), trusted)
    check_files(payload, hash_tree(module_dir))
    return payload


RELEASE_FIELDS = ("module_id", "edition", "version", "channel", "released_at")


def embedded_release_matches(embedded, package_payload):
    """Совпадает ли выпуск, вшитый в код компонента, с проверенным паспортом пакета."""
    return isinstance(embedded, dict) and all(embedded.get(k) == package_payload.get(k) for k in RELEASE_FIELDS)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Права: использование отдельно от обновлений
# ──────────────────────────────────────────────────────────────────────────────────────────────

class Decision(object):
    __slots__ = ("ok", "code", "license_id", "detail")

    def __init__(self, ok, code="", license_id="", detail=""):
        self.ok, self.code, self.license_id, self.detail = bool(ok), code, license_id, detail

    def __repr__(self):
        return "Decision(ok=%r, code=%r, license_id=%r)" % (self.ok, self.code, self.license_id)


def _major(version):
    m = re.match(r"\s*v?(\d+)", str(version or ""))
    return int(m.group(1)) if m else None


def evaluate(license_payload, module_id, feature=None, edition=None, release=None,
             install_id=None, now=None):
    """Даёт ли ПРОВЕРЕННАЯ лицензия право. -> Decision.

    module_id/edition/feature — что проверяется; release — выпуск, который должен быть покрыт
    лицензией: {module_id, edition, version, channel, released_at}. 1.1: release ОБЯЗАТЕЛЕН — без
    него правило «released_at < updates_before» не применить, и новый выпуск прошёл бы по старой
    лицензии. Коммерческий компонент передаёт выпуск, ВШИТЫЙ в свой код (EMBEDDED_RELEASE), а не
    файл паспорта с диска: паспорт можно подменить копированием. now — aware datetime UTC, нужен
    ТОЛЬКО срочной лицензии."""
    p = license_payload
    lid = p.get("license_id", "")
    if not isinstance(release, dict) or not all(isinstance(release.get(k), str) for k in RELEASE_FIELDS):
        return Decision(False, R_RELEASE_REQUIRED, lid, "не передан выпуск модуля")
    grant = None
    for g in p["grants"]:
        if g["module_id"] == module_id and (edition is None or g["edition"] == edition):
            grant = g
            break
    if grant is None:
        codes = [g for g in p["grants"] if g["module_id"] == module_id]
        return Decision(False, R_EDITION if codes else R_NO_GRANT, lid)
    if feature is not None and "*" not in grant["features"] and feature not in grant["features"]:
        return Decision(False, R_FEATURE, lid)
    if p["use_type"] == "term":
        if now is None:
            return Decision(False, R_TIME_REQUIRED, lid)
        if now < parse_utc(p["use_valid_from"], "use_valid_from"):
            return Decision(False, R_USE_NOT_STARTED, lid)
        if now >= parse_utc(p["use_valid_until"], "use_valid_until"):
            return Decision(False, R_USE_EXPIRED, lid)
    if "installation_binding" in p and p["installation_binding"]["install_id"] != (install_id or ""):
        return Decision(False, R_BINDING, lid)
    if release.get("module_id") != module_id:
        return Decision(False, R_NO_GRANT, lid, "выпуск другого модуля")
    if release.get("edition") != grant["edition"]:
        return Decision(False, R_EDITION, lid)
    lic_channel = p.get("channel", "stable")
    if release.get("channel") == "beta" and lic_channel != "beta":
        return Decision(False, R_CHANNEL, lid)
    rs = p.get("release_scope")
    if rs is not None:
        mj = _major(release.get("version"))
        if mj is None or mj > rs["max_major"]:
            return Decision(False, R_RELEASE_SCOPE, lid)
    try:
        released = parse_utc(release["released_at"], "released_at")
    except Rejected:
        return Decision(False, R_RELEASE_REQUIRED, lid, "неверная дата выпуска")
    if not released < parse_utc(p["updates_before"], "updates_before"):
        return Decision(False, R_UPDATE_NOT_COVERED, lid)
    return Decision(True, "", lid)


_CODE_ORDER = ("license_revoked", "license_stopped", R_UPDATE_NOT_COVERED, R_USE_EXPIRED, R_BINDING, R_FEATURE, R_EDITION, R_CHANNEL,
               R_RELEASE_SCOPE, R_USE_NOT_STARTED, R_TIME_REQUIRED, R_NO_GRANT, R_RELEASE_REQUIRED)


def best_decision(license_payloads, module_id, verdicts=None, machine=None, **kw):
    """Лучший ответ по набору ПРОВЕРЕННЫХ лицензий: первое разрешение, иначе самая полезная причина
    отказа (например, «выпуск не покрыт обновлениями» полезнее, чем «нет лицензии»).
    1.2: verdicts — проверенные ответы службы лицензий, machine — номер этого компьютера: лицензия,
    которую служба для этого компьютера остановила или аннулировала, разрешения не даёт."""
    fails = []
    for p in license_payloads or ():
        d = evaluate(p, module_id, **kw)
        if d.ok:
            blk = verdict_block(verdicts, d.license_id, machine) if verdicts else None
            if blk is None:
                return d
            d = blk
        fails.append(d)
    if not fails:
        return Decision(False, R_NO_GRANT)
    fails.sort(key=lambda d: _CODE_ORDER.index(d.code) if d.code in _CODE_ORDER else len(_CODE_ORDER))
    return fails[0]


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 1.2 (10.10.2026): ключ текстом, отметка у службы лицензий, её ответ и номер компьютера
#
# Продажа «вариант 3» (docs/release_prep/PAID_MODULES_SALES_CONCEPT.md): покупатель вставляет ключ —
# модуль работает сразу и без интернета (подпись ключа проверяется здесь же). Когда есть связь,
# программа «отмечается» у службы лицензий: ключ стоит на компьютере с таким-то номером. Служба
# отвечает подписанным документом fm-verdict: «работает», «остановить» (ключ на другом компьютере
# сверх купленного числа, перенесён или заблокирован владельцем) или «аннулирована» (возврат денег).
# Ответ «остановить»/«аннулирована» для ЭТОГО компьютера закрывает платные функции; ответа нет —
# лицензия работает (ферма без интернета — штатный случай). Договорённость с сайтом —
# docs/release_prep/SITE_LICENSING_BRIEF.md.
# ──────────────────────────────────────────────────────────────────────────────────────────────

KEY_PREFIX = "FMK1."
FORMAT_VERDICT = "fm-verdict"
MAX_KEY_CHARS = 16384
R_LICENSE_STOPPED = "license_stopped"
R_LICENSE_REVOKED = "license_revoked"
VERDICT_FIELDS = ("schema_version", "product_id", "license_id", "machine", "nonce", "status", "reason",
                  "checked_at", "key_id", "license")
VERDICT_STATUSES = ("ok", "stop", "revoked")
_NONCE_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_REASON_RE = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")
MACHINE_SALT = b"3diwell-fm-machine-v1"
_BAD_IDS = frozenset(("00000000-0000-0000-0000-000000000000", "ffffffff-ffff-ffff-ffff-ffffffffffff",
                      "03000200-0400-0500-0006-000700080009", "to be filled by o.e.m.", "default string",
                      "none", "0", "00000000"))


def is_key_text(text):
    return isinstance(text, str) and re.sub(r"\s+", "", text).startswith(KEY_PREFIX)


def encode_key(doc):
    """Документ лицензии -> ключ текстом: "FMK1." + base64url(zlib(JSON документа)). Для утилит и проверок."""
    return KEY_PREFIX + b64u_encode(zlib.compress(canonical_bytes(load_document(doc)), 9))


def decode_key(text):
    """Ключ текстом -> байты документа fm-license (подпись НЕ проверяется — это делает verify_license).
    Пробелы и переводы строк внутри ключа (письмо могло перенести строку) не мешают."""
    if not isinstance(text, str):
        raise Rejected(R_MALFORMED, "ключ — текст")
    t = re.sub(r"\s+", "", text)
    if len(t) > MAX_KEY_CHARS or not t.startswith(KEY_PREFIX):
        raise Rejected(R_WRONG_FORMAT, "ожидается ключ FMK1.")
    raw = b64u_decode(t[len(KEY_PREFIX):])
    d = zlib.decompressobj()                    # только zlib (RFC 1950): gzip и «голый» deflate — отказ
    try:
        out = d.decompress(raw, MAX_KEY_DOCUMENT_BYTES + 1)
    except zlib.error:
        raise Rejected(R_MALFORMED, "ключ повреждён")
    #  1.3: оборванный поток, данные после конца потока и слишком большой документ — отказ.
    if len(out) > MAX_KEY_DOCUMENT_BYTES or d.unconsumed_tail or not d.eof or d.unused_data:
        raise Rejected(R_MALFORMED, "ключ повреждён или слишком велик")
    return bytes(out)


def license_proof(raw):
    """Доказательство владения лицензией для службы: sha256 от строки подписи документа. Номер
    лицензии можно увидеть где угодно, а саму подпись знает только тот, у кого есть документ."""
    doc = load_document(raw)
    sig = doc.get("sig") if isinstance(doc, dict) else None
    v = sig.get("value") if isinstance(sig, dict) else None
    if not isinstance(v, str) or not v:
        raise Rejected(R_MALFORMED, "sig")
    return hashlib.sha256(v.encode("ascii", "replace")).hexdigest()


def validate_verdict(p):
    """Строгая схема ответа службы лицензий. Незнакомая причина «остановить» принимается (её
    добавит сайт позже), незнакомое состояние — нет."""
    if not isinstance(p, dict):
        raise Rejected(R_MALFORMED, "payload")
    _only(p, VERDICT_FIELDS)
    if _req(p, "schema_version", int) != SCHEMA_VERSION:
        raise Rejected(R_WRONG_FORMAT, "schema_version")
    if _req(p, "product_id", str) != PRODUCT_ID:
        raise Rejected(R_WRONG_PRODUCT)
    if not _ID_RE.match(_req(p, "license_id", str)):
        raise Rejected(R_BAD_VALUE, "license_id")
    if not _HEX64_RE.match(_req(p, "machine", str)):
        raise Rejected(R_BAD_VALUE, "machine")
    if not _NONCE_RE.match(_req(p, "nonce", str)):
        raise Rejected(R_BAD_VALUE, "nonce")
    status = _req(p, "status", str)
    if status not in VERDICT_STATUSES:
        raise Rejected(R_BAD_VALUE, "status")
    reason = _req(p, "reason", str)
    if status == "ok" and reason != "":
        raise Rejected(R_BAD_VALUE, "reason")
    if status != "ok" and not _REASON_RE.match(reason):
        raise Rejected(R_BAD_VALUE, "reason")
    parse_utc(_req(p, "checked_at", str), "checked_at")
    if not _ID_RE.match(_req(p, "key_id", str)):
        raise Rejected(R_BAD_VALUE, "key_id")
    if "license" in p and not isinstance(p["license"], dict):
        raise Rejected(R_BAD_VALUE, "license")
    return p


def verify_verdict(raw, trusted):
    """Подписанный ответ службы -> payload. Подписан ключом ЛИЦЕНЗИЙ (тот же, что выдаёт ключи),
    область подписи своя (fm-verdict). Вложенную лицензию (продление) вызывающий проверяет отдельно
    verify_license и сверяет license_id."""
    return validate_verdict(verify_document(raw, FORMAT_VERDICT, PURPOSE_LICENSE, trusted))


def verdict_answers(verdict, request):
    """Отвечает ли ответ службы на ЭТОТ запрос: та же лицензия, тот же компьютер, то же случайное число."""
    return isinstance(verdict, dict) and isinstance(request, dict) and all(
        verdict.get(k) == request.get(k) for k in ("license_id", "machine", "nonce"))


def verdict_block(verdicts, license_id, machine):
    """Последний (по checked_at) проверенный ответ службы для лицензии на ЭТОМ компьютере ->
    Decision(False, ...), если он «остановить» или «аннулирована»; иначе None (лицензия работает)."""
    best = None
    for v in verdicts or ():
        if not isinstance(v, dict) or v.get("license_id") != license_id or v.get("machine") != machine or not machine:
            continue
        if best is None or str(v.get("checked_at", "")) > str(best.get("checked_at", "")):
            best = v
    if best is None or best.get("status") == "ok":
        return None
    code = R_LICENSE_REVOKED if best.get("status") == "revoked" else R_LICENSE_STOPPED
    return Decision(False, code, license_id, str(best.get("reason", "")))


def new_nonce():
    return secrets.token_hex(16)


_WIRE_VERSION_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9 _.+()/\-]{0,63}\Z")


def wire_version(value):
    """1.3: версия для отметки по шаблону службы ([A-Za-z0-9] и затем до 63 знаков из «_.+()/- » и
    пробела). Посторонние знаки убираются; пусто (модуль не установлен) — «0»: пустая строка службой
    не принимается."""
    s = re.sub(r"[^A-Za-z0-9 _.+()/\-]", "", str(value or ""))
    s = s.lstrip(" _.+()/-")[:64].rstrip()
    return s if _WIRE_VERSION_RE.match(s) else "0"


def mark_request(license_raw, machine, module_id, module_version, fm_version, nonce, via="direct"):
    """Тело отметки для службы лицензий. Только номер лицензии, доказательство владения, номер
    компьютера, модуль и версии — без имён, адресов, принтеров и данных фермы."""
    doc = load_document(license_raw)
    lid = (doc.get("payload") or {}).get("license_id") if isinstance(doc.get("payload"), dict) else None
    if not isinstance(lid, str) or not _ID_RE.match(lid):
        raise Rejected(R_MALFORMED, "license_id")
    if not _HEX64_RE.match(str(machine or "")) or not _NONCE_RE.match(str(nonce or "")):
        raise Rejected(R_BAD_VALUE, "machine/nonce")
    return {"schema_version": SCHEMA_VERSION, "product_id": PRODUCT_ID, "license_id": lid,
            "proof": license_proof(doc), "machine": machine, "module_id": str(module_id or "")[:64],
            "module_version": wire_version(module_version), "fm_version": wire_version(fm_version),
            "nonce": nonce, "via": "browser" if via == "browser" else "direct"}


# ── номер компьютера ──────────────────────────────────────────────────────────────────────────

def _component_hash(name, value):
    return hashlib.sha256(MACHINE_SALT + b"\n" + name.encode("ascii") + b"\n" + value.encode("utf-8")).hexdigest()


def _smbios_uuid():
    """UUID материнской платы из таблицы SMBIOS (тип 1) — через GetSystemFirmwareTable, без программ."""
    import ctypes
    from ctypes import wintypes
    f = ctypes.windll.kernel32.GetSystemFirmwareTable
    f.argtypes = (wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    f.restype = wintypes.UINT
    sig = 0x52534D42                                    # 'RSMB'
    size = f(sig, 0, None, 0)
    if not size or size > 1 << 20:
        return ""
    buf = ctypes.create_string_buffer(size)
    if f(sig, 0, buf, size) != size:
        return ""
    data = buf.raw
    length = int.from_bytes(data[4:8], "little")
    table = data[8:8 + length]
    i = 0
    while i + 4 <= len(table):
        typ, ln = table[i], table[i + 1]
        if ln < 4:
            break
        if typ == 1 and ln >= 0x19 and i + 24 <= len(table):
            u = table[i + 8:i + 24]
            return "%08x-%04x-%04x-%s-%s" % (int.from_bytes(u[0:4], "little"), int.from_bytes(u[4:6], "little"),
                                             int.from_bytes(u[6:8], "little"), u[8:10].hex(), u[10:16].hex())
        j = i + ln
        while j + 1 < len(table) and not (table[j] == 0 and table[j + 1] == 0):
            j += 1
        i = j + 2
        if typ == 127:
            break
    return ""


def _system_volume_serial():
    import ctypes
    from ctypes import wintypes
    root = (os.environ.get("SystemDrive") or "C:") + "\\"
    serial = wintypes.DWORD(0)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), None, 0, ctypes.byref(serial),
                                                       None, None, None, 0)
    return ("%08x" % serial.value) if ok and serial.value else ""


def _raw_components():
    out = {}
    if os.name == "nt":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                               winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0))
            out["os"] = winreg.QueryValueEx(k, "MachineGuid")[0]
        except Exception:
            pass
        for name, fn in (("board", _smbios_uuid), ("disk", _system_volume_serial)):
            try:
                out[name] = fn()
            except Exception:
                pass
    else:
        for name, path in (("os", "/etc/machine-id"), ("board", "/sys/class/dmi/id/product_uuid")):
            try:
                with open(path, encoding="ascii", errors="replace") as f:
                    out[name] = f.read()
            except Exception:
                pass
    return out


def machine_components():
    """Части номера компьютера -> {имя: свёртка}. Только то, что удалось прочитать; сами значения
    (номер Windows, UUID платы, серийный номер тома) наружу не выходят."""
    out = {}
    for name, value in _raw_components().items():
        v = str(value or "").strip().lower()
        if v and v not in _BAD_IDS:
            out[name] = _component_hash(name, v)
    return out


def fingerprint_of(components):
    if not components:
        return ""
    return hashlib.sha256(MACHINE_SALT + b"\nfp\n" + "|".join(sorted(components.values())).encode("ascii")).hexdigest()


def machine_identity(stored=None, components=None):
    """-> (номер компьютера, новое состояние для хранения).

    Решает плата. Номер Windows и серийный номер тома живут на системном диске и меняются (и
    копируются) вместе, поэтому сами по себе они компьютер не определяют. Тот же UUID платы — тот же
    компьютер, даже после переустановки Windows и замены диска; другая плата — другой компьютер, даже
    если на него перенесли копию диска со всей папкой данных. Плата не читается — тогда тот же
    компьютер, только если совпали обе другие части. Меньше двух частей прочитано — решить нельзя:
    остаётся прежний номер, сохранённое состояние не трогается (одна неудачная загрузка его не портит)."""
    comps = machine_components() if components is None else dict(components)
    if (isinstance(stored, dict) and _HEX64_RE.match(str(stored.get("fingerprint") or ""))
            and isinstance(stored.get("parts"), dict)):
        sp = stored["parts"]
        if "board" in comps and "board" in sp:
            same = comps["board"] == sp["board"]
        else:
            same = all(k in comps and comps[k] == sp.get(k) for k in ("os", "disk"))
        if same:
            merged = dict(sp)
            merged.update(comps)            # непрочитанные сейчас части остаются прежними
            return stored["fingerprint"], {"fingerprint": stored["fingerprint"], "parts": merged}
        if len(comps) < 2:
            return stored["fingerprint"], stored
    fp = fingerprint_of(comps)
    return fp, {"fingerprint": fp, "parts": comps}


def short_number(fingerprint):
    """Короткий номер компьютера для людей: «XXXX-XXXX» — тот же покажет личный кабинет."""
    f = str(fingerprint or "")
    return (f[:4] + "-" + f[4:8]).upper() if _HEX64_RE.match(f) else ""
