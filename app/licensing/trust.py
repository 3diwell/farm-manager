# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Доверенные открытые ключи поставщика для ядра FM (26.09.2026).

РАБОЧИЕ КЛЮЧИ (25.10.2026, переход от закрытого пилота сайта к рабочему комплекту): ключ лицензий сайта
и ключи пакетов модулей — ниже, только ОТКРЫТЫЕ части. Закрытые ключи в проект не попадают никогда.

ТЕСТОВЫЕ КЛЮЧИ принимаются ТОЛЬКО при запуске из исходников (не собранный .exe) и только если
переменная окружения FM_LICENSE_TEST_KEYS указывает на файл со списком тестовых открытых ключей.
Рабочая сборка тестовые лицензии не принимает ни при каких настройках.
"""
import json
import os
import re
import sys

from app.licensing import fm_license_sdk as S

# Открытые ключи поставщика: {"key_id", "purpose": "license"|"package", "public_key": base64url, "label"}.
# Ключи лицензий и ключи пакетов разные. Для смены ключа добавьте новый рядом со старым: прежние
# лицензии продолжат проверяться прежним ключом, пока его не уберут сознательно.
# 25.10.2026, письмо сайта «переход к рабочему комплекту»:
#  * лицензии и ответы службы (fm-license, fm-verdict). Ключ fm-pilot091-… — ключ принятой конфигурации сайта:
#    им подписаны выданные лицензии пилота, их продления и ответы; отпечаток SHA-256 сырых 32 байт
#    14be9932bc9d575680d297311567aa51447472871ec1ef32a4888de8d2304ea4 сверен с письмом сайта. Постоянный ключ сайта
#    fm-license-prod-2026-01 (переход 135, экспорт сайта 26.10.2026, отпечаток
#    2a65085670cc8ace30360c15a2dab08bff9c5d8183b6bb8831c621eb5679ff3c сверен) — РЯДОМ: им сайт подписывает новые
#    выдачи после своей активации. Старый ключ не убирается: прежние лицензии и их ответы остаются с ним.
#  * пакеты модулей. fm-pkg-prod-2026-01 — рабочий ключ 3DiWell для публичных платных ZIP (закрытая часть вне
#    проекта). fm-pkg-pilot091-build — ключ пакетов пилотной сборки: оставлен, чтобы уже установленные на
#    компьютере пилота платные модули продолжали работать; убрать, когда их там переустановят.
PRODUCTION_KEYS = (
    {"key_id": "fm-pilot091-f2495abcaa0c1ed0", "purpose": "license",
     "public_key": "wQAEGy9q6e68yQrPL7PTuZzp8B5HRib41JAc0xY_dVw",
     "label": "лицензии и ответы службы сайта 3diwell.com (ключ принятой конфигурации сайта, с 17.10.2026)"},
    {"key_id": "fm-license-prod-2026-01", "purpose": "license",
     "public_key": "6cedrItsp8PU3TVEPhoOWde1TKIorOPAO-omjw7Mt2w",
     "label": "лицензии и ответы службы сайта 3diwell.com (постоянный ключ, переход 135, 26.10.2026)"},
    {"key_id": "fm-pkg-prod-2026-01", "purpose": "package",
     "public_key": "G2cMdnQGePFval4MLZvSP_p6kK38rplzPQ0nXf_MRjQ",
     "label": "пакеты модулей 3DiWell (рабочий ключ, создан 25.10.2026)"},
    {"key_id": "fm-pkg-pilot091-build", "purpose": "package",
     "public_key": "_CempIfdqLZKblYNEs1-BqccbuOCWZylrdUADFbVwTo",
     "label": "пакеты модулей пилотной сборки сайта (переходный: уже установленные модули пилота)"},
)

# R-131 (29.09.2026): открытые ключи, которыми подписывается описание выпуска на сайте (latest.json,
# формат "fm-release"). Та же форма записи, назначение — "package". Список ОТДЕЛЬНЫЙ от ключей
# модулей намеренно: ключ, выданный для подписи модулей, не должен заодно подписывать «новую версию
# программы», а добавление ключа модулей не должно само включать обязательную подпись выпуска.
# Пока список пуст, проверка обновлений принимает прежний неподписанный latest.json (после строгой
# проверки формы и адреса). Как только сюда вписан рабочий ключ — ТОЛЬКО подписанный им ответ.
RELEASE_KEYS = ()

ENV_TEST_KEYS = "FM_LICENSE_TEST_KEYS"


def is_frozen_build():
    return bool(getattr(sys, "frozen", False))


def _test_keys():
    path = os.environ.get(ENV_TEST_KEYS, "")
    if not path or is_frozen_build():
        return ()
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        return tuple(S.TrustedKey(k["key_id"], k["purpose"], k["public_key"], k.get("label", ""), test=True)
                     for k in items)
    except Exception:
        return ()


def trusted_keys():
    """{key_id: TrustedKey} — рабочие ключи плюс (только из исходников и по переменной) тестовые.
    Испорченный файл тестовых ключей не мешает рабочим: берутся только рабочие."""
    keys = [S.TrustedKey(k["key_id"], k["purpose"], k["public_key"], k.get("label", ""))
            for k in PRODUCTION_KEYS]
    prod = S.trusted_set(keys)
    try:
        return S.trusted_set(keys + [k for k in _test_keys() if k.key_id not in prod])
    except Exception:
        return prod


def test_keys_enabled():
    return bool(_test_keys())


def release_keys():
    """{key_id: TrustedKey} для подписи описания выпуска: рабочие RELEASE_KEYS плюс (только из
    исходников и по переменной) тестовые ключи назначения package. Испорченный файл тестовых
    ключей не мешает рабочим."""
    keys = [S.TrustedKey(k["key_id"], k["purpose"], k["public_key"], k.get("label", ""))
            for k in RELEASE_KEYS]
    prod = S.trusted_set(keys)
    try:
        extra = [k for k in _test_keys() if k.key_id not in prod and k.purpose == S.PURPOSE_PACKAGE]
        return S.trusted_set(keys + extra)
    except Exception:
        return prod


def release_signature_required():
    """Подпись описания выпуска обязательна, как только вписан хотя бы один РАБОЧИЙ ключ выпуска."""
    return bool(RELEASE_KEYS)


# 10.10.2026, продажа «вариант 3»: адрес службы лицензий для отметки (docs/release_prep/
# SITE_LICENSING_BRIEF.md). Его даёт второй разработчик, когда сайт заработает; пока адрес пустой —
# программа никуда не обращается, лицензии работают как раньше (полностью офлайн).
# 25.10.2026: постоянный адрес службы сайта — и для прямой отметки, и для отметки через браузер/телефон.
# Прежний адрес пилота (fm-computers-099) сайт сохраняет для уже установленных пилотных сборок; эта программа
# на него не откатывается.
LICENSE_SERVICE_URL = "https://3diwell.com/local/3diwell/fm-license-service/mark.php"
LICENSE_TERMS_URL = ""     # лицензионный договор на сайте — покажется ссылкой у согласия, когда сайт даст адрес
LICENSE_PRIVACY_URL = ""   # политика обработки персональных данных — так же
SERVICE_HOST = "3diwell.com"
ENV_TEST_SERVICE = "FM_LICENSE_TEST_SERVICE"
# 11.10.2026: только для проверок из исходников — прямой отметки нет, только через браузер (так проверяется
# ферма без интернета: отметку относит телефон). Собранная программа переменную не читает.
ENV_TEST_RELAY_ONLY = "FM_LICENSE_TEST_RELAY_ONLY"
_SITE_URL_RE = re.compile(r"\Ahttps://((?:[a-z0-9-]+\.)*3diwell\.com)(?::443)?(?:/[A-Za-z0-9._~%/+-]*)?(?:\?[A-Za-z0-9._~%=&+-]*)?\Z")
_TEST_URL_RE = re.compile(r"\Ahttps?://(127\.0\.0\.1|localhost)(?::\d{1,5})?(?:/[A-Za-z0-9._~%/+-]*)?\Z")


def _service_url_ok(url, test=False):
    """Только https на 3diwell.com и его поддомены (без логина в адресе, без чужого порта); для
    проверок — http(s)://127.0.0.1. Разбор без сетевых модулей: пакет лицензирования к сети не обращается."""
    u = str(url or "")
    if test and _TEST_URL_RE.match(u):
        return True
    return bool(_SITE_URL_RE.match(u.lower() if u[:8].lower() == "https://" else u))


def site_page_url(url):
    """Адрес страницы сайта для ссылки в окне согласия или ""."""
    return url if _service_url_ok(url) else ""


def direct_marks_disabled_for_test():
    return (not is_frozen_build()) and os.environ.get(ENV_TEST_RELAY_ONLY, "").strip() == "1"


def license_service_url():
    """Адрес отметки или "". Рабочий — только https на сайт 3DiWell (3diwell.com и его поддомены).
    Для проверок из исходников (не собранный .exe) — адрес из переменной FM_LICENSE_TEST_SERVICE,
    в том числе http://127.0.0.1:<порт>."""
    if not is_frozen_build():
        t = os.environ.get(ENV_TEST_SERVICE, "").strip()
        if t:
            return t if _service_url_ok(t, test=True) else ""
    return LICENSE_SERVICE_URL if _service_url_ok(LICENSE_SERVICE_URL) else ""
