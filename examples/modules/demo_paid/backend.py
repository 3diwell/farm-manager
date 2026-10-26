# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""ДЕМОНСТРАЦИОННЫЙ платный модуль FM (26.09.2026). На рабочую ферму не ставится.

Что показывает — контракт независимой проверки в коммерческом компоненте:

  * бесплатная часть (GET status) работает всегда, лицензия ей не нужна;
  * платная функция pro_report (GET report) объявлена через core.add_paid_route: ядро штатно
    отвечает 402 без действующей лицензии, НО компонент не верит ядру и перед выполнением
    проверяет всё сам — прямо внутри платной операции:
      1. паспорт своего пакета (core.package_document) — подписью ВШИТОГО в себя ключа пакетов
         и совпадение с выпуском, ВШИТЫМ в свой код (fm_embedded.EMBEDDED_RELEASE);
      2. целостность своих файлов по этому паспорту;
      3. исходные документы лицензий (core.license_documents) — своей копией SDK
         (fm_license_sdk.py внутри пакета) и своими ключами лицензий;
      4. право на функцию, редакцию и ЭТОТ выпуск (released_at < updates_before), привязку.
  * та же проверка — в фоновой работе (nightly_job): платное не выполняется в обход маршрута.

Чего НЕ показывает: защиту закрытого кода от владельца компьютера. Это открытый пример; его
можно изменить и убрать проверку. Настоящая ценная логика живёт в отдельно лицензируемом
компоненте, который проверяет право перед своей ценной операцией.

Файлы fm_license_sdk.py и fm_embedded.py кладёт в пакет упаковщик (tools/module_package.py
--embed-sdk --embed-trust ...); в исходниках их нет. Без них платная функция недоступна.
"""
import datetime
import os

core = None
_sdk = None
_emb = None
_load_error = ""
PAID_FEATURE = "pro_report"


def _load_embedded():
    """Своя копия SDK и вшитые ключи/выпуск — только из проверенных файлов пакета."""
    global _sdk, _emb, _load_error
    try:
        _sdk = core.import_module_file("fm_license_sdk.py", "fm_demo_paid_sdk")
        _emb = core.import_module_file("fm_embedded.py", "fm_demo_paid_embedded")
    except Exception as e:   # пакет без подписи / сборка разработчика: платного нет
        _sdk, _emb = None, None
        _load_error = e.__class__.__name__


def verify_paid(feature):
    """Независимая проверка права. -> (ok: bool, code: str, license_id: str)."""
    if _sdk is None or _emb is None:
        return False, "no_embedded_trust", ""
    try:
        trusted = _sdk.trusted_set(_emb.TRUSTED_KEYS)
    except Exception:
        return False, "bad_embedded_trust", ""
    pkg_keys = {k: v for k, v in trusted.items() if v.purpose == _sdk.PURPOSE_PACKAGE}
    lic_keys = {k: v for k, v in trusted.items() if v.purpose == _sdk.PURPOSE_LICENSE}
    release = dict(_emb.EMBEDDED_RELEASE)
    # 1-2. свой пакет: паспорт подписан поставщиком, совпадает с вшитым выпуском, файлы целы
    try:
        raw_pkg = core.package_document()
        if not raw_pkg:
            return False, "no_package", ""
        pkg = _sdk.verify_package_manifest(raw_pkg, pkg_keys)
        if not _sdk.embedded_release_matches(release, pkg):
            return False, "release_mismatch", ""
        _sdk.verify_installed_package(core.module_dir, pkg_keys)
    except _sdk.Rejected as e:
        return False, "package_" + e.code, ""
    # 3. исходные документы лицензий — своими ключами
    payloads = []
    for raw in core.license_documents():
        try:
            payloads.append(_sdk.verify_license(raw, lic_keys))
        except _sdk.Rejected:
            continue
    # 4. право на функцию, редакцию и ЭТОТ выпуск
    d = _sdk.best_decision(payloads, release["module_id"], feature=feature, edition=release["edition"],
                           release=release, install_id=core.install_id(),
                           now=datetime.datetime.now(datetime.timezone.utc))
    return d.ok, d.code, d.license_id


def api_demo_paid_status():
    """Бесплатная часть: работает без лицензии."""
    ok, code, lid = verify_paid(PAID_FEATURE)
    return {"module": "demo_paid", "free_part": True, "pro_report_available": ok, "code": code,
            "core_view": core.license_status()}


def api_demo_paid_report():
    """Платная функция. Ядро уже проверило лицензию, но компонент проверяет сам."""
    from fastapi.responses import JSONResponse
    ok, code, lid = verify_paid(PAID_FEATURE)
    if not ok:
        return JSONResponse(status_code=402, content={"status": "error", "reason": "license_required",
                                                      "code": code, "checked_by": "component"})
    return {"status": "ok", "report": "демонстрационный отчёт", "license_id": lid, "checked_by": "component"}


def nightly_job():
    """Фоновая платная работа: та же проверка, что у маршрута. -> то, что сделано (для проверки)."""
    ok, code, _lid = verify_paid(PAID_FEATURE)
    return "done" if ok else "skipped:" + code


def register(_core):
    global core
    core = _core
    _load_embedded()
    core.add_route("status", api_demo_paid_status, ["GET"], policy_id="demo_paid.status")
    core.add_paid_route("report", api_demo_paid_report, PAID_FEATURE, ["GET"], policy_id="demo_paid.report")
