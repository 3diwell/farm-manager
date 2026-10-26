# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Подписанные пакеты модулей в ядре FM (26.09.2026): проверка до запуска кода.

Политика (docs/licensing/MODULE_LICENSING_FOUNDATION.md, раздел «Пакеты»):

  * Пакет БЕЗ паспорта fm-package.json — «без подписи»: старые, сторонние и разработческие модули.
    Грузятся как раньше; платных возможностей у них нет (выпуск ничем не подтверждён).
  * Пакет С паспортом проверяется целиком ДО импорта backend.py, регистрации маршрутов и выдачи
    ресурсов: подпись доверенным ключом пакетов, совпадение с module.json, хеш каждого файла, ни
    одного лишнего файла. Не прошёл — код не исполняется, данные модуля не трогаются.
  * Код подписанного пакета исполняется из тех байтов, чей хеш только что сверен: кэш Python
    (__pycache__/*.pyc) для папки такого модуля не читается и не пишется. Так подложенный .pyc
    не выполнится вместо проверенного исходника, а файл, подменённый после проверки, не пройдёт
    сверку при чтении.

Предел: модуль работает внутри процесса ядра. Это проверка происхождения и целостности пакета,
а не песочница: проверенный код может всё, что может само ядро.
"""
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys
import threading

from app.licensing import fm_license_sdk as S

STATE_UNSIGNED = "unsigned"
STATE_VERIFIED = "verified"
STATE_INVALID = "integrity_failed"
STATE_UNTRUSTED = "untrusted"


def zip_member_problems(names):
    """Имена записей архива модуля, которые нельзя распаковывать как есть -> [(имя, причина)].
    Ловит в том числе пары, которые Windows сливает в один файл: «backend.py» и «BACKEND.PY»,
    «backend.py» и «backend.py.» — иначе распаковался бы не тот файл, что проверялся."""
    problems, seen = [], {}
    for n in names:
        if n.endswith("/"):
            continue
        why = S.path_problem(n)
        if why:
            problems.append((n, why))
            continue
        key = n.casefold()
        if key in seen and seen[key] != n:
            problems.append((n, "совпадает с %s без учёта регистра" % seen[key]))
        seen.setdefault(key, n)
    return problems


def inspect_dir(mdir, trusted, manifest):
    """Состояние пакета в папке модуля -> {state, code, detail, payload, raw}.
    manifest — уже прочитанный module.json (id и version должны совпасть с паспортом)."""
    p = os.path.join(mdir, S.PACKAGE_MANIFEST_NAME)
    if not os.path.isfile(p):
        return {"state": STATE_UNSIGNED, "code": "", "detail": "", "payload": None, "raw": None}
    try:
        with open(p, "rb") as f:
            raw = f.read()
        payload = S.verify_package_manifest(raw, trusted)
    except S.Rejected as e:
        state = STATE_UNTRUSTED if e.code in (S.R_UNKNOWN_KEY, S.R_CRYPTO_UNAVAILABLE) else STATE_INVALID
        return {"state": state, "code": e.code, "detail": e.detail, "payload": None, "raw": None}
    except OSError:
        return {"state": STATE_INVALID, "code": S.R_FILE_MISSING, "detail": S.PACKAGE_MANIFEST_NAME,
                "payload": None, "raw": None}
    mid = str((manifest or {}).get("id") or "").strip()
    ver = str((manifest or {}).get("version") or "").strip()
    if payload["module_id"] != mid or payload["version"] != ver:
        return {"state": STATE_INVALID, "code": S.R_FILE_MISMATCH, "detail": "module.json не совпадает с паспортом",
                "payload": None, "raw": None}
    try:
        S.check_files(payload, S.hash_tree(mdir))
    except S.Rejected as e:
        return {"state": STATE_INVALID, "code": e.code, "detail": e.detail, "payload": None, "raw": None}
    except OSError as e:
        return {"state": STATE_INVALID, "code": S.R_FILE_MISSING, "detail": str(e.__class__.__name__),
                "payload": None, "raw": None}
    return {"state": STATE_VERIFIED, "code": "", "detail": "", "payload": payload, "raw": raw}


def summary(pkg):
    """То, что можно показать в интерфейсе: без путей и без содержимого паспорта."""
    pl = pkg.get("payload") or {}
    out = {"state": pkg.get("state", STATE_UNSIGNED), "code": pkg.get("code", "")}
    if pl:
        out.update({"edition": pl.get("edition", ""), "channel": pl.get("channel", ""),
                    "released_at": pl.get("released_at", ""),
                    "model": (pl.get("licensing") or {}).get("model", "free"),
                    "paid_features": list((pl.get("licensing") or {}).get("paid_features") or [])})
    return out


# ── исполнение кода из проверенных байтов ────────────────────────────────────────────────────

_lock = threading.Lock()
_verified_dirs = {}   # нормализованный путь папки -> {rel: sha256}


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _owner(path):
    """(папка подписанного пакета, её файлы, относительный путь) или (None, None, None)."""
    n = _norm(path)
    for d, files in list(_verified_dirs.items()):
        if n.startswith(d + os.sep):
            return d, files, os.path.relpath(n, d).replace(os.sep, "/")
    return None, None, None


class VerifiedSourceLoader(importlib.machinery.SourceFileLoader):
    """Загрузчик исходника подписанного пакета: байты сверяются с паспортом при КАЖДОМ чтении,
    байт-код не читается (любой путь, кроме самого исходника, — «нет файла») и не пишется."""

    def __init__(self, fullname, path, digest):
        importlib.machinery.SourceFileLoader.__init__(self, fullname, path)
        self._digest = digest

    def get_data(self, path):
        if _norm(path) != _norm(self.path):
            raise OSError("байт-код подписанного пакета не используется")
        with open(path, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() != self._digest:
            raise ImportError("файл подписанного модуля изменён после проверки: %s" % os.path.basename(path))
        return data

    def set_data(self, path, data, *args, **kwargs):
        return None   # кэш .pyc рядом с подписанным кодом не создаётся


class _VerifiedFinder(importlib.abc.MetaPathFinder):
    """Импорт файла из папки подписанного пакета идёт через VerifiedSourceLoader; файл, которого нет
    в паспорте (например, подложенный .pyc или .pyd), не импортируется вовсе.

    Порядок поиска НЕ меняется: файл ищется тем же PathFinder по тем же путям (sys.path или
    __path__ пакета), что и без этого поисковика, а встроенные и стандартные модули находятся раньше
    — поисковик стоит в sys.meta_path сразу перед PathFinder. Только если найденный обычным порядком
    файл лежит в папке подписанного пакета, подменяется загрузчик. Так модуль с файлом csv.py не
    перехватит стандартный csv у остальной программы."""

    def find_spec(self, fullname, path=None, target=None):
        if not _verified_dirs:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or not spec.origin or spec.origin in ("built-in", "frozen"):
            return None
        d, files, rel = _owner(spec.origin)
        if d is None:
            return None
        digest = files.get(rel)
        if digest is None:
            raise ImportError("файл не входит в подписанный пакет: %s" % rel)
        if spec.origin.lower().endswith(".py"):
            spec.loader = VerifiedSourceLoader(fullname, spec.origin, digest)
            spec.cached = None
            return spec
        #  Двоичное расширение (.pyd/.so), перечисленное в паспорте: сверяем хеш перед загрузкой.
        #  Между сверкой и загрузкой файл читается ещё раз — это предел, описанный в документации.
        with open(spec.origin, "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != digest:
                raise ImportError("файл подписанного модуля изменён после проверки: %s" % rel)
        return spec


_FINDER = _VerifiedFinder()


def _file_key(rel):
    """Ключ файла паспорта для сравнения с путём на диске: на Windows регистр не различается
    (validate_package уже не пускает имена, различающиеся только регистром)."""
    return os.path.normcase(rel.replace("/", os.sep)).replace(os.sep, "/")


def register_verified_dir(mdir, payload):
    with _lock:
        _verified_dirs[_norm(mdir)] = {_file_key(k): v for k, v in payload["files"].items()}
        if _FINDER not in sys.meta_path:
            #  Сразу перед PathFinder: встроенные, замороженные и прочие поисковики — раньше нас.
            idx = next((i for i, f in enumerate(sys.meta_path) if f is importlib.machinery.PathFinder),
                       len(sys.meta_path))
            sys.meta_path.insert(idx, _FINDER)


def unregister_dir(mdir):
    with _lock:
        _verified_dirs.pop(_norm(mdir), None)


def purge_bytecode(mdir):
    """Убрать папки __pycache__ подписанного пакета перед запуском. Кэш одноразовый, но подложенный
    .pyc выполнился бы вместо проверенного исходника у модуля, который грузит соседний файл через
    importlib.util.spec_from_file_location без загрузчика ядра. -> сколько папок убрано."""
    import shutil
    n = 0
    for base, dirs, _files in os.walk(mdir):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                dirs.remove(d)
                n += 1
    return n


def load_verified_file(module_name, mdir, payload, rel_path):
    """Импортировать файл подписанного пакета (точку входа или соседний файл) из проверенных байтов."""
    rel_path = str(rel_path).replace("\\", "/").lstrip("/")
    digest = payload["files"].get(rel_path)
    if digest is None or not rel_path.endswith(".py"):
        raise ImportError("файл не входит в подписанный пакет: %s" % rel_path)
    register_verified_dir(mdir, payload)
    path = os.path.join(mdir, *rel_path.split("/"))
    loader = VerifiedSourceLoader(module_name, path, digest)
    spec = importlib.util.spec_from_file_location(module_name, path, loader=loader)
    spec.cached = None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_verified_backend(module_name, mdir, payload):
    """Импортировать backend.py подписанного пакета из проверенных байтов -> объект модуля."""
    entry = payload.get("entry", {}).get("backend") or "backend.py"
    purge_bytecode(mdir)
    return load_verified_file(module_name, mdir, payload, entry)


def asset_ok(pkg, rel_path, data):
    """Можно ли отдать ресурс подписанного пакета: файл в паспорте и хеш совпадает."""
    pl = (pkg or {}).get("payload")
    if not pl:
        return True
    digest = pl["files"].get(rel_path)
    return digest is not None and hashlib.sha256(data).hexdigest() == digest
