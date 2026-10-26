# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Самопроверка права в платном модуле FM (11.10.2026).

Копию этого файла упаковщик кладёт в ПОДПИСАННЫЙ платный пакет модуля рядом с копией SDK
(tools/module_package.py --embed-sdk) и файлом fm_embedded.py (открытые ключи поставщика и выпуск
пакета, --embed-trust). Модуль грузит все три файла через core.import_module_file — то есть из
проверенных ядром байтов — и перед каждой платной операцией спрашивает PaidGuard.check().

Проверка не верит ответу ядра «лицензия есть» (ядро открытое, его можно пересобрать):
  1. паспорт своего пакета — подписью вшитого ключа пакетов, совпадение с вшитым выпуском,
     целостность своих файлов;
  2. исходные документы лицензий (core.license_documents) — своей копией SDK и вшитым ключом
     лицензий; право на модуль, редакцию и ЭТОТ выпуск (released_at < updates_before);
  3. подписанные ответы службы лицензий (core.license_verdicts) — тем же ключом: «остановить» или
     «аннулирована» для этого компьютера (core.license_machine) закрывает платное. Нет ответа —
     лицензия работает: ферма без интернета — штатный случай.

Без файлов fm_embedded.py / fm_license_sdk.py (обычный бесплатный модуль, сборка из исходников)
модуль PaidGuard не создаёт и работает как раньше — платного у него нет.

ЛИЦЕНЗИЯ (16.10.2026, R-149). Mozilla Public License 2.0 — как ядро и SDK; заголовок выше тот же,
что ставит выгрузка открытой копии (tools/public_export.py). В платный пакет файл кладётся БЕЗ
ИЗМЕНЕНИЙ (--embed-sdk копирует байты); остальной код модуля может быть под любой лицензией
(MPL 2.0, раздел 3.3). Изменённую копию можно распространять только вместе с её исходным кодом.

Предел (docs/licensing/MODULE_LICENSING_FOUNDATION.md, раздел 1): код модуля открыт, проверку можно
вырезать правкой файлов. Подпись пакета не даёт подменить файлы незаметно для штатного ядра; защиту от
правки кода даёт только компиляция — отдельное решение.

Файл самодостаточен: стандартная библиотека; ответ 402 строится через FastAPI, который есть у FM.
"""
import datetime
import functools
import inspect
import threading
import time

DECISION_TTL_S = 10.0       # решение по лицензиям и ответам службы — не дольше 10 секунд
INTEGRITY_TTL_S = 300.0     # удачная сверка своих файлов с паспортом — раз в 5 минут
INTEGRITY_RETRY_S = 10.0    # неудачная (файл занят антивирусом, идёт замена) — повтор через 10 секунд
READ_METHODS = ("GET", "HEAD", "OPTIONS")


class PaidGuard(object):
    """Независимая проверка права платного модуля. check() -> (ok, code, license_id)."""

    def __init__(self, core, sdk, emb):
        self.core, self.sdk, self.emb = core, sdk, emb
        self.model = str(getattr(emb, "EMBEDDED_LICENSING", "paid"))
        self._lock = threading.Lock()
        self._integrity = (0.0, None)          # (время, "" или код отказа)
        self._decision = (0.0, None, None)     # (время, ревизия лицензий, результат)

    # ── что за модуль ─────────────────────────────────────────────────────────────────────────
    def release(self):
        return dict(self.emb.EMBEDDED_RELEASE)

    def module_id(self):
        return str(self.release().get("module_id", ""))

    # ── проверка ──────────────────────────────────────────────────────────────────────────────
    def _keys(self):
        S = self.sdk
        trusted = S.trusted_set(self.emb.TRUSTED_KEYS)
        return ({k: v for k, v in trusted.items() if v.purpose == S.PURPOSE_PACKAGE},
                {k: v for k, v in trusted.items() if v.purpose == S.PURPOSE_LICENSE})

    def _package_problem(self, pkg_keys, release):
        S = self.sdk
        t = time.monotonic()
        at, code = self._integrity
        if code == "" and t - at < INTEGRITY_TTL_S:
            return code
        if code and t - at < INTEGRITY_RETRY_S:
            return code
        try:
            raw = self.core.package_document()
            if not raw:
                code = "no_package"
            else:
                pkg = S.verify_package_manifest(raw, pkg_keys)
                if not S.embedded_release_matches(release, pkg):
                    code = "release_mismatch"
                else:
                    S.verify_installed_package(self.core.module_dir, pkg_keys)
                    code = ""
        except S.Rejected as e:
            code = "package_" + e.code
        except Exception:
            code = "package_unreadable"
        self._integrity = (t, code)
        return code

    def _check(self, feature=None):
        S = self.sdk
        try:
            pkg_keys, lic_keys = self._keys()
        except Exception:
            return (False, "bad_embedded_trust", "")
        release = self.release()
        code = self._package_problem(pkg_keys, release)
        if code:
            return (False, code, "")
        payloads = []
        for raw in self.core.license_documents():
            try:
                payloads.append(S.verify_license(raw, lic_keys))
            except Exception:
                continue
        verdicts = []
        try:
            vraws = self.core.license_verdicts()
        except Exception:
            vraws = []
        for raw in vraws:
            try:
                verdicts.append(S.verify_verdict(raw, lic_keys))
            except Exception:
                continue
        try:
            machine = self.core.license_machine()
        except Exception:
            machine = ""
        d = S.best_decision(payloads, release["module_id"], verdicts=verdicts, machine=machine, feature=feature,
                            edition=release["edition"], release=release, install_id=self.core.install_id(),
                            now=datetime.datetime.now(datetime.timezone.utc))
        return (d.ok, d.code, d.license_id)

    def check(self, feature=None):
        """Можно ли выполнить платную операцию -> (ok, code, license_id). Повторно не чаще раза в 10
        секунд; добавление, удаление или замена лицензии видны сразу."""
        try:
            rev = self.core.license_revision()
        except Exception:
            rev = None
        t = time.monotonic()
        if feature is None:
            with self._lock:
                at, r, res = self._decision
                if res is not None and r == rev and t - at < DECISION_TTL_S:
                    return res
        try:
            res = self._check(feature)
        except Exception:
            res = (False, "check_failed", "")
        if feature is None:
            with self._lock:
                self._decision = (t, rev, res)
        return res

    def view(self):
        """Для интерфейса модуля: {"paid": True, "ok", "code", "license_id"}."""
        ok, code, lid = self.check()
        return {"paid": True, "ok": bool(ok), "code": code, "license_id": lid}

    # ── граница платной операции ──────────────────────────────────────────────────────────────
    def refusal(self, feature=None):
        """Ответ 402, если платная операция сейчас недоступна, иначе None."""
        ok, code, _lid = self.check(feature)
        if ok:
            return None
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=402, content={
            "status": "error", "reason": "license_required", "module_id": self.module_id(), "code": code,
            "checked_by": "module",
            "message": {"ru": "Только просмотр: нет действующей лицензии модуля. Данные и печать не затронуты.",
                        "en": "View only: there is no valid module license. Data and printing are not affected."}})

    def wrap(self, handler, feature=None):
        """Обработчик маршрута -> он же за границей платной операции (имя и подпись сохраняются:
        по имени ядро сверяет маршрут с картой прав). feature — платная функция модели freemium."""
        if inspect.iscoroutinefunction(handler):
            @functools.wraps(handler)
            async def _paid(*a, **kw):
                r = self.refusal(feature)
                if r is not None:
                    return r
                return await handler(*a, **kw)
        else:
            @functools.wraps(handler)
            def _paid(*a, **kw):
                r = self.refusal(feature)
                if r is not None:
                    return r
                return handler(*a, **kw)
        return _paid

    def route_adder(self, add_route):
        """core.add_route -> такой же, но изменяющие маршруты (не GET) проходят границу платной
        операции. Просмотр (GET) остаётся открытым: без лицензии данные видны и выгружаются.
        Только для модели paid: у freemium бесплатные изменения остаются бесплатными, и модуль сам
        оборачивает маршруты своих платных функций — wrap(handler, feature)."""
        if self.model != "paid":
            return add_route

        def _add(path, handler, methods=("GET",), policy_id=None):
            if any(str(m).upper() not in READ_METHODS for m in (methods or ())):
                handler = self.wrap(handler)
            return add_route(path, handler, methods, policy_id=policy_id)
        return _add


def load(core, prefix):
    """PaidGuard из файлов пакета или None (обычный модуль без платной части).

    Файлы грузятся только через core.import_module_file: у подписанного пакета — из проверенных
    ядром байтов. Модель лицензирования пакета — EMBEDDED_LICENSING во вшитом файле (paid или
    freemium); free или отсутствие файла — платного нет."""
    try:
        emb = core.import_module_file("fm_embedded.py", prefix + "_embedded")
    except Exception:
        return None
    if str(getattr(emb, "EMBEDDED_LICENSING", "paid")) not in ("paid", "freemium"):
        return None
    try:
        sdk = core.import_module_file("fm_license_sdk.py", prefix + "_sdk")
    except Exception:
        sdk = None          # платный пакет без своей копии SDK: платное закрыто (check_failed), а не открыто
    return PaidGuard(core, sdk, emb)
