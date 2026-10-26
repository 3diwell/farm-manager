# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.804 — папка проекта называется РОВНО как проект.
#
#  ПОЛНОСТЬЮ OFFLINE. server.py НЕ импортируется обычным способом: реальные функции контракта имени,
#  создания, переименования, резолвера и согласования извлекаются разбором AST и исполняются в
#  изоляции поверх ВРЕМЕННОЙ SQLite (схема взята из самого server.py) и ВРЕМЕННОГО managed-корня.
#  Ни рабочей БД, ни рабочего DATA_DIR, ни сети, ни принтера, ни слайсера, ни отправки печати.
#  Реальные пользовательские файлы не используются; содержимое файлов и абсолютные пути не печатаются.
#
#  ЧТО ДОКАЗЫВАЕТ. В имени папки не остаётся НИЧЕГО, кроме текущего названия проекта: ни
#  «__project_<id>», ни «proj_<id>», ни UUID, ни даты, ни счётчика. Названия живых проектов
#  уникальны по семантике Windows (регистр, NFC, хвостовые точки/пробелы); создание дубликата и
#  переименование в дубликат блокируются (HTTP 409), занятая физическая папка тоже блокирует и НЕ
#  усыновляется. Переименование — ОДНА атомарная операция: папка и БД меняются вместе либо не
#  меняются вовсе (откат при отказе БД, полный отказ при занятой Windows папке). Папки конвенции
#  Alpha 2.803 мигрируют одним os.rename с обновлением stored_path; байты, SHA-256, file/part/plate
#  идентификаторы и неизвестные файлы пользователя сохраняются; rmtree не используется; массовой
#  миграции при старте нет.
#
#  Запуск:  python tools/test_project_name_only_folders.py   (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import atexit
import contextlib
import hashlib
import os
import re
import secrets
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unicodedata
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_DONE = {"ok": False}


def _guard():
    """atexit-страж: преждевременный выход (в т.ч. sys.exit(0)) не должен выглядеть успехом."""
    if not _DONE["ok"]:
        try:
            print("FAIL — тест завершился до выполнения проверок")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)


atexit.register(_guard)


class _TrapSocket(object):
    def __init__(self, *a, **k):
        raise AssertionError("offline-тест: сокеты запрещены")


socket.socket = _TrapSocket

FAILED = []
PASSED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "PROJECT_NAME_ONLY_FOLDER_SENTINEL_2_804"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
INDEX = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8", errors="surrogateescape").read()


def _node(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            return n
    return None


def fn_src(name):
    n = _node(name)
    return ast.unparse(n) if n is not None else ""


def calls_attr(name, attr):
    """Есть ли в функции ФАКТИЧЕСКИЙ вызов x.<attr>(...) — по AST, а не по подстроке: иначе проверка
    срабатывала бы на собственной докстроке (ложная зелень)."""
    n = _node(name)
    if n is None:
        return False
    for x in ast.walk(n):
        if isinstance(x, ast.Call):
            f = x.func
            if isinstance(f, ast.Attribute) and f.attr == attr:
                return True
            if isinstance(f, ast.Name) and f.id == attr:
                return True
    return False


def fn_src_nodec(name):
    """Исходник обработчика БЕЗ декораторов @app.post/@app.patch — чтобы исполнить его в изоляции."""
    n = _node(name)
    if n is None:
        return ""
    n = ast.parse(ast.unparse(n)).body[0]
    n.decorator_list = []
    return ast.unparse(n)


class _Log(object):
    def _r(self, *a, **k):
        pass

    info = warning = error = debug = exception = _r


class _OsShim(object):
    """Прокси os: моделирует «папку держит Windows» (отказ os.rename)."""

    def __init__(self, real):
        self._r = real
        self.fail_rename = False
        self.renames = 0

    def rename(self, a, b):
        if self.fail_rename:
            raise PermissionError("synthetic: folder is in use")
        self.renames += 1
        return self._r.rename(a, b)

    def __getattr__(self, n):
        return getattr(self._r, n)


class _Resp(object):
    """Заглушка fastapi.responses.JSONResponse: фиксирует тело и статус, наружу ничего не шлёт."""

    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class _Req(object):
    def __init__(self, body):
        self._body = body


class _AsyncioShim(object):
    """asyncio для обработчиков: to_thread выполняет функцию синхронно. Настоящий event loop не
    поднимается намеренно — на Windows он открыл бы сокет самопробуждения, а ловушка сокетов должна
    остаться в силе (offline-тест доказывает, что сеть не используется вообще)."""

    @staticmethod
    async def to_thread(fn, *a, **k):
        return fn(*a, **k)


def run_coro(coro):
    """Прогон корутины без event loop: обработчики ничего по-настоящему не ждут."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise AssertionError("обработчик ожидал настоящий event loop — в offline-тесте это запрещено")


# ── изолированное окружение ────────────────────────────────────────────────
ROOT = tempfile.mkdtemp(prefix="fm_nameonly_")
DATA = os.path.join(ROOT, "data")
PF = os.path.join(DATA, "project_files")
UP = os.path.join(DATA, "slicer_uploads")
TMPF = os.path.join(DATA, "temp_files")
USB = os.path.join(ROOT, "usb")
for d in (PF, UP, TMPF, USB):
    os.makedirs(d)
DBP = os.path.join(DATA, "test_parts.db")

conn = sqlite3.connect(DBP, check_same_thread=False)
conn.row_factory = sqlite3.Row
DDL = [m.group(0) for m in re.finditer(
    r"CREATE TABLE IF NOT EXISTS (?:projects|project_files|project_parts|project_file_parts|staging_files) \([^\"]*?\)(?=\")", SRV)]
assert len(DDL) >= 5, "не найдены DDL таблиц в server.py"
for q in DDL:
    conn.execute(q)
for col in ["src_path TEXT DEFAULT ''"]:
    try:
        conn.execute("ALTER TABLE staging_files ADD COLUMN %s" % col)
    except Exception:
        pass
conn.commit()

OS_SHIM = _OsShim(os)
NS = {
    "os": OS_SHIM, "re": re, "hashlib": hashlib, "secrets": secrets, "shutil": shutil, "log": _Log(),
    "contextmanager": contextlib.contextmanager, "threading": threading, "asyncio": _AsyncioShim,
    "time": time, "uuid": uuid, "_unicodedata": unicodedata,
    "conn_p": conn, "lock_p": threading.Lock(),
    "JSONResponse": _Resp, "_exc_brief": lambda *a: "",
    "PROJECT_FILES_DIR": PF, "UPLOAD_DIR": UP, "TEMP_FILES_DIR": TMPF,
    "_PROJ_EXTS": (".gcode.3mf", ".3mf", ".gcode", ".stl"),
    "_OWNER_DIR_TAG": ast.literal_eval(re.search(r"^_OWNER_DIR_TAG = (\{.*?\})$", SRV, re.M).group(1)),
    "_MANAGED_IMPORT_MAX": 2 * 1024 * 1024 * 1024,
    "_WIN_RESERVED_NAMES": frozenset(
        ["CON", "PRN", "AUX", "NUL"] + ["COM%d" % i for i in range(1, 10)] + ["LPT%d" % i for i in range(1, 10)]),
    "_PROJECT_NAME_MAX": int(re.search(r"^_PROJECT_NAME_MAX = (\d+)", SRV, re.M).group(1)),
    "_PROJECT_DIR_PATH_MAX": int(re.search(r"^_PROJECT_DIR_PATH_MAX = (\d+)", SRV, re.M).group(1)),
}
# таблица «reason -> HTTP-статус» берётся ИЗ server.py дословно
_HTTP_SRC = re.search(r"^_PROJECT_NAME_HTTP = \{[^}]*\}", SRV, re.M | re.S)
assert _HTTP_SRC, "не найдена таблица _PROJECT_NAME_HTTP"
exec(compile(_HTTP_SRC.group(0), "<server>", "exec"), NS)
NS["_lock_pname"] = threading.RLock()

for _f in ("ProjectNameError", "_rollback_sqlite_on_error", "_uid", "_get_project", "_safe_archive_name",
           "_unlink_in_managed", "_unique_dest", "_managed_file_sha256", "_safe_managed_filename",
           "_trash_managed_copy", "_prune_trash_dir",
           "_managed_source_ok", "_import_copy_managed", "_short_owner_id", "_safe_owner_dir_name",
           "_managed_owner_root", "_dir_under_root", "_owner_stored_dirs", "_project_name_is_unique",
           "_project_name_error_response", "_project_name_canonical_key", "_project_name_reject_reason",
           "normalize_and_validate_project_name", "_project_name_taken_by", "_project_folder_state",
           "_assert_project_name_available", "_project_owner_dir_name", "rename_project_atomic",
           "desired_project_directory", "_dir_is_plain", "_owner_suffix_dirs",
           "_rename_owner_dir_to_desired", "resolve_managed_owner_directory", "_reconcile_owner_files",
           "_project_dir", "_purge_orphan_files", "create_project", "update_project",
           "_unique_import_project_name"):
    src = fn_src(_f)
    assert src, "функция %s не найдена в server.py" % _f
    exec(compile(src, "<server>", "exec"), NS)

exec(compile("async def _json_body(req):\n    return req._body\n", "<test>", "exec"), NS)
for _h in ("c_project2", "u_project2"):
    src = fn_src_nodec(_h)
    assert src, "обработчик %s не найден" % _h
    exec(compile(src, "<server>", "exec"), NS)

norm = NS["normalize_and_validate_project_name"]
PNErr = NS["ProjectNameError"]
create = NS["create_project"]
rename = NS["rename_project_atomic"]
resolve = NS["resolve_managed_owner_directory"]
reconcile = NS["_reconcile_owner_files"]
rename_dir = NS["_rename_owner_dir_to_desired"]
desired = NS["desired_project_directory"]
folder_state = NS["_project_folder_state"]
taken_by = NS["_project_name_taken_by"]
canon_key = NS["_project_name_canonical_key"]
reject = NS["_project_name_reject_reason"]
sha256_of = NS["_managed_file_sha256"]
purge = NS["_purge_orphan_files"]
project_dir = NS["_project_dir"]

THUMB = b"; thumbnail begin 16x16\n; iVBORw0KGgoAAAANSUhEUg==\n; thumbnail end\n"
BODY = b"; synthetic gcode " + SENTINEL.encode() + b"\nG28\n" + b"G1 X1 Y1 E1\n" * 40


def make(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def add_file(fid, pid, fname, stored="", src=""):
    conn.execute("INSERT INTO project_files (id, project_id, filename, src_path, stored_path) VALUES (?,?,?,?,?)",
                 (fid, pid, fname, src, stored))
    conn.commit()
    return fid


def stored_of(fid):
    r = conn.execute("SELECT stored_path FROM project_files WHERE id=?", (fid,)).fetchone()
    return r["stored_path"] if r else ""


def name_of(pid):
    r = conn.execute("SELECT name FROM projects WHERE id=?", (pid,)).fetchone()
    return r["name"] if r else ""


def dirs_now():
    return sorted(d for d in os.listdir(PF) if os.path.isdir(os.path.join(PF, d)))


def rb(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def reason_of(fn, *a):
    """reason отказа контракта имени, '' — если операция прошла."""
    try:
        fn(*a)
        return ""
    except PNErr as e:
        return e.reason


def api_create(name, due=""):
    """POST /api/projects2 через РЕАЛЬНЫЙ обработчик c_project2."""
    return run_coro(NS["c_project2"](_Req({"name": name, "due_date": due})))


def api_patch(pid, body):
    """PATCH /api/projects2/{id} через РЕАЛЬНЫЙ обработчик u_project2."""
    return run_coro(NS["u_project2"](pid, _Req(body)))


def http_of(resp):
    return getattr(resp, "status_code", 200)


def reason_body(resp):
    c = getattr(resp, "content", None)
    return (c or {}).get("reason", "") if isinstance(c, dict) else ""


try:
    print("=== Alpha 2.804: папка проекта = РОВНО название проекта (offline) ===")

    # ═════════════════════ FOLDER NAME CONTRACT (1-8) ══════════════════════
    section("контракт имени папки")
    p898 = create("898")
    P898 = p898["id"]
    d898 = resolve("project", P898, "898")
    check("1. проект «898» использует папку «898»", os.path.basename(d898) == "898")
    check("2. project ID отсутствует в имени папки",
          P898 not in os.path.basename(d898) and NS["_short_owner_id"](P898) not in os.path.basename(d898))
    check("3. «__project_» отсутствует в имени папки", "__project_" not in os.path.basename(d898))
    check("4. «proj_» отсутствует в имени папки", "proj_" not in os.path.basename(d898))
    check("5. UUID/hex-хвост отсутствует в имени папки",
          re.search(r"[0-9a-f]{8,}", os.path.basename(d898)) is None)
    _i = norm("  Заказ 898  ")
    check("6. имя папки строково равно нормализованному названию проекта",
          _i["folder"] == _i["display"] == "Заказ 898"
          and _i["folder"].encode("utf-8") == _i["display"].encode("utf-8")
          and os.path.basename(desired(P898, "Заказ 898")) == "Заказ 898")
    pempty = create("Пустой проект")
    reconcile("project", pempty["id"])
    check("7. проект без файлов может не иметь физической папки",
          not os.path.exists(os.path.join(PF, "Пустой проект")))
    _first = make(os.path.join(resolve("project", P898, "898"), "plate.gcode.3mf"), THUMB + BODY)
    FID898 = add_file("pf_898", P898, "plate.gcode.3mf", stored=_first)
    check("8. первый файл создаёт папку точного имени",
          os.path.isdir(os.path.join(PF, "898")) and os.path.isfile(_first)
          and os.path.dirname(_first) == os.path.join(PF, "898"))

    # ═════════════════════════ CREATE CONFLICT (9-16) ═══════════════════════
    section("создание дубликата блокируется")
    _dirs_before, _rows_before = dirs_now(), conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"]
    check("9. второй проект «898» не создаётся", reason_of(create, "898") == "project_name_conflict")
    check("10. «898» и «898 » конфликтуют (хвостовой пробел не создаёт новое имя)",
          reason_of(create, "898 ") == "project_name_conflict"
          and canon_key("898") == canon_key("898 ") == canon_key(" 898"))
    ptest = create("Test")
    check("11. «Test» и «test» конфликтуют (Windows не различает регистр)",
          reason_of(create, "test") == "project_name_conflict"
          and reason_of(create, "TEST") == "project_name_conflict"
          and canon_key("ABC") == canon_key("abc"))
    _nfc = unicodedata.normalize("NFC", "Ёлка")
    _nfd = unicodedata.normalize("NFD", "Ёлка")
    pnfc = create(_nfc)
    check("12. Unicode NFC-эквивалентные имена конфликтуют",
          _nfc != _nfd and reason_of(create, _nfd) == "project_name_conflict"
          and name_of(pnfc["id"]) == _nfc)
    check("13. при конфликте запись в БД не создаётся",
          conn.execute("SELECT COUNT(*) c FROM projects").fetchone()["c"] == _rows_before + 2)
    check("14. при конфликте папка не создаётся",
          dirs_now() == _dirs_before and not os.path.exists(os.path.join(PF, "test")))
    _r409 = api_create("898")
    check("15. HTTP-статус конфликта = 409 (и это не 500)",
          http_of(_r409) == 409 and NS["_PROJECT_NAME_HTTP"]["project_name_conflict"] == 409)
    check("16. reason = project_name_conflict", reason_body(_r409) == "project_name_conflict")

    # ═════════════════════════ RENAME CONFLICT (17-24) ══════════════════════
    section("переименование в дубликат блокируется")
    p123 = create("123")
    P123 = p123["id"]
    d123 = resolve("project", P123, "123")
    f123 = make(os.path.join(d123, "a.gcode"), BODY + b"123")
    FID123 = add_file("pf_123", P123, "a.gcode", stored=f123)
    _bytes123, _sha123 = rb(f123), sha256_of(f123)
    _dirs_pre = dirs_now()
    check("17. проект «123» нельзя переименовать в «898»",
          reason_of(rename, P123, "898") == "project_name_conflict")
    check("18. старое название проекта сохранено", name_of(P123) == "123")
    check("19. старая папка сохранена", os.path.isdir(d123) and dirs_now() == _dirs_pre)
    check("20. stored_path сохранены", os.path.normcase(stored_of(FID123)) == os.path.normcase(f123))
    check("21. байты файла сохранены", rb(f123) == _bytes123 and sha256_of(f123) == _sha123)
    check("22. второй проект не изменён",
          name_of(P898) == "898" and os.path.isfile(stored_of(FID898))
          and os.path.dirname(stored_of(FID898)) == os.path.join(PF, "898"))
    check("23. частичной файловой операции нет (папки «898» вида-дубля не появилось)",
          sorted(dirs_now()) == sorted(_dirs_pre) and OS_SHIM.fail_rename is False)
    check("24. case-only конфликт с другим проектом блокируется",
          reason_of(rename, P123, "TEST") == "project_name_conflict"
          and reason_of(rename, P123, "ёЛКА") == "project_name_conflict")

    # ══════════════════ PHYSICAL FOLDER CONFLICT (25-31) ════════════════════
    section("конфликт физической папки")
    unknown_dir = os.path.join(PF, "ABC")
    unknown_file = make(os.path.join(unknown_dir, "чертёж пользователя.pdf"), b"user pdf " + SENTINEL.encode())
    _unk_bytes = rb(unknown_file)
    check("25. неизвестная папка «ABC» блокирует создание проекта «ABC»",
          reason_of(create, "ABC") == "project_folder_conflict")
    os.makedirs(os.path.join(PF, "Пусто"))
    check("26. пустая неизвестная папка также блокирует",
          reason_of(create, "Пусто") == "project_folder_conflict"
          and folder_state(None, "Пусто") == "foreign")
    check("27. занятая физическая папка блокирует переименование при свободном названии",
          taken_by(P123, canon_key("ABC")) == ""            # проекта с таким названием нет вообще
          and reason_of(rename, P123, "ABC") == "project_folder_conflict"
          and name_of(P123) == "123")
    check("27b. владелец папки определяется по ссылкам БД, а не по совпадению имени",
          folder_state(P123, "898") == "foreign" and folder_state(P898, "898") == "own"
          and "project_id" in fn_src("_project_folder_state"))
    check("28. неизвестные файлы не удаляются", os.path.isfile(unknown_file) and rb(unknown_file) == _unk_bytes)
    check("29. неизвестная папка не переименовывается и не переносится",
          os.path.isdir(unknown_dir) and "ABC" in dirs_now() and "Пусто" in dirs_now())
    _rf = NS["_project_name_error_response"](PNErr("project_folder_conflict"))
    check("30. API не раскрывает абсолютный путь (в теле только reason)",
          set(_rf.content.keys()) == {"status", "reason"}
          and PF not in str(_rf.content) and DATA not in str(_rf.content))
    check("31. reason = project_folder_conflict и статус 409",
          reason_body(_rf) == "project_folder_conflict" and http_of(_rf) == 409)

    # ═══════════════════════════ VALIDATION (32-52) ═════════════════════════
    section("контракт названия проекта")
    check("32. пустое имя блокируется", reason_of(create, "") == "project_name_required")
    check("33. имя из пробелов блокируется", reason_of(create, "    ") == "project_name_required")
    check("34. «.» блокируется", reason_of(create, ".") == "project_name_invalid")
    check("35. «..» блокируется", reason_of(create, "..") == "project_name_invalid")
    check("36. slash блокируется", reason_of(create, "a/b") == "project_name_invalid")
    check("37. backslash блокируется", reason_of(create, "a\\b") == "project_name_invalid")
    check("38. ADS «name:stream» блокируется", reason_of(create, "plan:$DATA") == "project_name_invalid")
    check("39. «< > \" | ? *» блокируются",
          all(reject("a%sb" % ch) == "project_name_invalid" for ch in '<>"|?*'))
    check("40. управляющие символы блокируются",
          reject("a\x01b") == "project_name_invalid" and reject("a\nb") == "project_name_invalid"
          and reject("a\x7fb") == "project_name_invalid")
    check("41. хвостовая точка блокируется",
          reason_of(create, "Проект.") == "project_name_invalid" and reject("Проект.") == "project_name_invalid")
    check("42. хвостовой пробел как имя папки блокируется (нормализация его снимает)",
          reject("898 ") == "project_name_invalid" and reject(" 898") == "project_name_invalid"
          and norm(" Заказ ")["folder"] == "Заказ")
    check("43. CON блокируется", reason_of(create, "CON") == "project_name_reserved")
    check("44. PRN блокируется", reason_of(create, "PRN") == "project_name_reserved")
    check("45. AUX блокируется", reason_of(create, "AUX") == "project_name_reserved")
    check("46. NUL блокируется", reason_of(create, "NUL") == "project_name_reserved")
    check("47. COM1–COM9 блокируются",
          all(reject("COM%d" % i) == "project_name_reserved" for i in range(1, 10))
          and reject("com5") == "project_name_reserved")
    check("48. LPT1–LPT9 блокируются",
          all(reject("LPT%d" % i) == "project_name_reserved" for i in range(1, 10)))
    check("49. reserved-имя с расширением тоже блокируется",
          reject("CON.txt") == "project_name_reserved" and reject("nul.gcode") == "project_name_reserved")
    check("50. слишком длинное имя блокируется",
          reject("Я" * (NS["_PROJECT_NAME_MAX"] + 1)) == "project_name_too_long"
          and reject("Я" * NS["_PROJECT_NAME_MAX"]) == "")
    pru = create("Заказ Иванов — партия №7")
    check("51. Unicode/кириллица разрешены",
          os.path.basename(desired(pru["id"], "Заказ Иванов — партия №7")) == "Заказ Иванов — партия №7")
    check("52. внутренние пробелы разрешены и не схлопываются",
          norm("Заказ  Иванов")["display"] == "Заказ  Иванов")

    # ═════════════════════ MIGRATION FROM 2.803 (53-64) ═════════════════════
    section("миграция папок конвенции Alpha 2.803")
    PM = "proj_139390a3e710"
    conn.execute("INSERT INTO projects (id, name) VALUES (?,?)", (PM, "897"))
    conn.commit()
    old_dir = os.path.join(PF, "897__project_" + NS["_short_owner_id"](PM))
    fm1 = make(os.path.join(old_dir, "plate_1.gcode.3mf"), THUMB + BODY + b"M")
    FIDM = add_file("pf_mig", PM, "plate_1.gcode.3mf", stored=fm1)
    conn.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name) VALUES ('ptm',?,'Крышка','крышка')", (PM,))
    conn.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) VALUES ('pfpm',?,?,'ptm',4)", (PM, FIDM))
    conn.commit()
    unknown_in_owner = make(os.path.join(old_dir, "заметки.txt"), b"user notes " + SENTINEL.encode())
    sha_before, bytes_before = sha256_of(fm1), rb(fm1)
    rmig = reconcile("project", PM)
    newm = stored_of(FIDM)
    check("53. «897__project_<id>» переименовано в «897»",
          rmig["renamed"] == 1 and os.path.basename(os.path.dirname(newm)) == "897"
          and not os.path.isdir(old_dir))
    check("54. stored_path обновлены", os.path.isfile(newm) and os.path.dirname(newm) == os.path.join(PF, "897"))
    check("55. file ID не изменился",
          conn.execute("SELECT COUNT(*) c FROM project_files WHERE id=?", (FIDM,)).fetchone()["c"] == 1
          and conn.execute("SELECT project_id FROM project_files WHERE id=?", (FIDM,)).fetchone()["project_id"] == PM)
    _fp = conn.execute("SELECT file_id, part_id, on_plate_qty FROM project_file_parts WHERE id='pfpm'").fetchone()
    check("56. part/plate mapping не изменился",
          _fp["file_id"] == FIDM and _fp["part_id"] == "ptm" and _fp["on_plate_qty"] == 4)
    check("57. SHA-256 не изменился", sha256_of(newm) == sha_before and rb(newm) == bytes_before)
    check("58. preview: встроенная миниатюра слайсера на месте", (rb(newm) or b"").startswith(THUMB))
    check("59. analysis: содержимое читается и не изменено", len(rb(newm) or b"") == len(bytes_before))
    check("60. print resolver (stored_path or src_path) указывает на существующий файл",
          os.path.isfile((stored_of(FIDM) or "")) and rb(stored_of(FIDM)) == bytes_before)
    check("61. старая папка исчезла только после успеха; неизвестный файл переехал вместе с ней",
          not os.path.isdir(old_dir) and os.path.isfile(os.path.join(PF, "897", "заметки.txt")))

    PD = "proj_dbfail000001"
    conn.execute("INSERT INTO projects (id, name) VALUES (?,?)", (PD, "Откат"))
    conn.commit()
    dd = os.path.join(PF, "Откат__project_" + NS["_short_owner_id"](PD))
    fd = make(os.path.join(dd, "x.gcode"), BODY)
    FIDD = add_file("pf_dbfail", PD, "x.gcode", stored=fd)

    class _BrokenConn(object):
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a, **k):
            if sql.strip().upper().startswith("UPDATE PROJECT_FILES"):
                raise sqlite3.OperationalError("synthetic DB failure")
            return self._real.execute(sql, *a, **k)

        def __getattr__(self, n):
            return getattr(self._real, n)

    NS["conn_p"] = _BrokenConn(conn)
    try:
        reconcile("project", PD)
    except Exception:
        pass
    NS["conn_p"] = conn
    check("62. отказ БД возвращает старую папку (переименование откатано)",
          os.path.isdir(dd) and os.path.isfile(fd)
          and os.path.normcase(stored_of(FIDD)) == os.path.normcase(fd)
          and not os.path.isdir(os.path.join(PF, "Откат")))

    PL = "proj_locked000001"
    conn.execute("INSERT INTO projects (id, name) VALUES (?,?)", (PL, "Занята"))
    conn.commit()
    dl = os.path.join(PF, "Занята__project_" + NS["_short_owner_id"](PL))
    fl = make(os.path.join(dl, "l.gcode"), BODY)
    FIDL = add_file("pf_locked", PL, "l.gcode", stored=fl)
    OS_SHIM.fail_rename = True
    rlock = reconcile("project", PL)
    OS_SHIM.fail_rename = False
    check("63. отказ переименования Windows сохраняет старое имя и старую папку",
          rlock["retry"] is True and rlock["renamed"] == 0 and os.path.isdir(dl)
          and name_of(PL) == "Занята" and not os.path.isdir(os.path.join(PF, "Занята"))
          and os.path.normcase(stored_of(FIDL)) == os.path.normcase(fl))
    _again = reconcile("project", PM)
    check("64. повтор миграции идемпотентен",
          _again["renamed"] == 0 and _again["moved"] == 0 and _again["dirs_removed"] == 0
          and os.path.dirname(stored_of(FIDM)) == os.path.join(PF, "897"))

    # ═══════════════════════ PROJECT RENAME (65-74) ═════════════════════════
    section("переименование проекта — одна атомарная операция")
    unknown_before = make(os.path.join(PF, "898", "спецификация.txt"), b"user spec " + SENTINEL.encode())
    _b898, _s898 = rb(stored_of(FID898)), sha256_of(stored_of(FID898))
    _name_in_dir = os.path.basename(stored_of(FID898))
    ok65 = rename(P898, "Новый заказ")
    n898 = stored_of(FID898)
    check("65. «898» -> «Новый заказ» выполнено", ok65 is True and name_of(P898) == "Новый заказ")
    check("66. папка стала «Новый заказ»",
          os.path.isdir(os.path.join(PF, "Новый заказ")) and os.path.dirname(n898) == os.path.join(PF, "Новый заказ"))
    check("67. старой папки после успеха нет", not os.path.isdir(os.path.join(PF, "898")))
    check("68. название в БД и имя папки изменились ОДНОЙ пользовательской операцией",
          name_of(P898) == "Новый заказ" and os.path.isfile(n898)
          and calls_attr("rename_project_atomic", "rename")          # фактический os.rename, не докстрока
          and "UPDATE projects SET name" in fn_src("rename_project_atomic")
          and "UPDATE project_files SET stored_path" in fn_src("rename_project_atomic"))
    check("71. неизвестные файлы папки владельца переехали вместе с ней",
          os.path.isfile(os.path.join(PF, "Новый заказ", "спецификация.txt")))
    check("73. имя файла внутри папки не изменилось", os.path.basename(n898) == _name_in_dir)
    check("74. байты и SHA-256 файла не изменились", rb(n898) == _b898 and sha256_of(n898) == _s898)

    PR = "proj_rollback0001"
    conn.execute("INSERT INTO projects (id, name) VALUES (?,?)", (PR, "Родное"))
    conn.commit()
    dr = resolve("project", PR, "Родное")
    fr = make(os.path.join(dr, "r.gcode"), BODY)
    FIDR = add_file("pf_rb", PR, "r.gcode", stored=fr)
    NS["conn_p"] = _BrokenConn(conn)
    _rb_reason = reason_of(rename, PR, "Переименованное")
    NS["conn_p"] = conn
    check("69. отказ БД откатывает переименование папки",
          _rb_reason == "project_rename_failed" and os.path.isdir(dr)
          and not os.path.isdir(os.path.join(PF, "Переименованное"))
          and name_of(PR) == "Родное"
          and os.path.normcase(stored_of(FIDR)) == os.path.normcase(fr))
    OS_SHIM.fail_rename = True
    _fs_reason = reason_of(rename, PR, "Переименованное")
    OS_SHIM.fail_rename = False
    check("70. отказ файловой системы не меняет название в БД",
          _fs_reason == "project_folder_locked" and name_of(PR) == "Родное"
          and os.path.isdir(dr) and not os.path.isdir(os.path.join(PF, "Переименованное")))
    _ren_src = fn_src("rename_project_atomic")
    check("72. rmtree не вызывается в переименовании и согласовании (проверка по AST, не по тексту)",
          not any(calls_attr(f, "rmtree") for f in
                  ("rename_project_atomic", "_reconcile_owner_files", "_rename_owner_dir_to_desired",
                   "_purge_orphan_files", "create_project"))
          and calls_attr("_reconcile_owner_files", "rmdir"))
    check("72b. порядок жёстко зафиксирован: проверка конфликта -> os.rename -> транзакция БД -> откат",
          0 < _ren_src.find("_assert_project_name_available") < _ren_src.find("os.rename(src, tgt)")
          < _ren_src.find("UPDATE projects SET name") and "os.rename(tgt, src)" in _ren_src)

    # ═════════════════════════ CONCURRENCY (75-80) ══════════════════════════
    section("параллельные запросы")

    def _race(fn, n=2):
        bar, out = threading.Barrier(n), []
        lock = threading.Lock()

        def work(i):
            bar.wait()
            try:
                fn(i)
                with lock:
                    out.append("ok")
            except PNErr as e:
                with lock:
                    out.append(e.reason)
            except Exception as e:
                with lock:
                    out.append("err:" + type(e).__name__)

        th = [threading.Thread(target=work, args=(i,)) for i in range(n)]
        for t in th:
            t.start()
        for t in th:
            t.join(30)
        return out

    res75 = _race(lambda i: create("Гонка"))
    check("75. два параллельных create «Гонка» -> ровно один успех",
          res75.count("ok") == 1 and res75.count("project_name_conflict") == 1
          and conn.execute("SELECT COUNT(*) c FROM projects WHERE name='Гонка'").fetchone()["c"] == 1)
    PRA = create("Гонка A")["id"]
    PRB = create("Гонка B")["id"]
    res76 = _race(lambda i: rename(PRA if i == 0 else PRB, "Гонка C"))
    check("76. два параллельных rename в одно имя -> ровно один успех",
          res76.count("ok") == 1 and res76.count("project_name_conflict") == 1
          and conn.execute("SELECT COUNT(*) c FROM projects WHERE name='Гонка C'").fetchone()["c"] == 1)
    _keys = [canon_key(r["name"]) for r in
             conn.execute("SELECT name FROM projects WHERE is_deleted=0").fetchall()]
    check("77. в БД нет двух записей с одним каноническим ключом", len(_keys) == len(set(_keys)))
    _dl = [os.path.normcase(d) for d in dirs_now()]
    check("78. нет двух owner-папок с одним именем", len(_dl) == len(set(_dl)))
    _cre_src = fn_src("create_project")
    check("79. проверка и запись идут под ОДНИМ ограниченным локом (без сна и сети внутри)",
          "with _lock_pname:" in _cre_src and "_assert_project_name_available" in _cre_src
          and "with _lock_pname:" in _ren_src
          and not any(t in _cre_src + _ren_src for t in ("time.sleep", "urllib", "socket", "requests"))
          and NS["_lock_pname"].acquire(blocking=False) and (NS["_lock_pname"].release() or True))
    check("80. конфликт не превращается в 500",
          {NS["_PROJECT_NAME_HTTP"][k] for k in ("project_name_conflict", "project_folder_conflict",
                                                 "project_folder_locked")} == {409}
          and http_of(NS["_project_name_error_response"](PNErr("project_name_invalid"))) == 400)

    # ══════════════════════════ FRONTEND (81-89) ════════════════════════════
    section("предупреждения фронтенда")
    RU_CONFLICT = "Проект с таким названием уже существует. Выберите другое название."
    RU_FOLDER = "Папка с таким названием уже существует в хранилище Farm Manager. Выберите другое название."
    RU_LOCKED = ("Не удалось переименовать папку проекта. Закройте программы, использующие файлы "
                 "проекта, и повторите попытку.")
    EN_CONFLICT = "A project with this name already exists. Choose a different name."
    EN_FOLDER = "A folder with this name already exists in Farm Manager storage. Choose a different name."
    check("81. RU-предупреждения присутствуют",
          RU_CONFLICT in APPJS and RU_FOLDER in APPJS and RU_LOCKED in APPJS)
    check("82. EN-предупреждения присутствуют (ключи словаря = английский текст)",
          EN_CONFLICT in APPJS and EN_FOLDER in APPJS
          and ('"%s": "%s"' % (EN_CONFLICT, RU_CONFLICT)) in APPJS
          and ('"%s": "%s"' % (EN_FOLDER, RU_FOLDER)) in APPJS)
    _cp = re.search(r"const createProject2 = async \(\) => \{.*?\n    \};", APPJS, re.S).group(0)
    _sp = re.search(r"const saveProject2Name = async \(pid, name\) => \{.*?\n    \};", APPJS, re.S).group(0)
    check("83. форма не закрывается при отказе (закрытие только после успешного ответа)",
          _cp.find("if (!r.ok)") < _cp.find("showNewProject2.value = false")
          and "project2Busy.value = false; _p2FocusNew(); return;" in _cp)
    check("84. введённое значение сохраняется (очистка поля — только после успеха; список не перечитывается)",
          _cp.find("if (!r.ok)") < _cp.find("newProject2Name.value = ''")
          and _sp.find("if (!r.ok)") < _sp.find("await loadProjects2();"))
    check("85. повторная отправка блокируется",
          "if (project2Busy.value) return;" in _cp and "if (p2RenameBusy.has(pid)) return;" in _sp)
    check("85b. поле получает error-state и фокус возвращается в него",
          "_p2FocusNew()" in _cp and "_p2FocusRename(pid)" in _sp
          and "project2NameErr ? 'border-color:#f5a524' : ''" in INDEX
          and "fm-p2name-" in INDEX and "project2RenameErr[pr.id]" in INDEX)
    _msg = re.search(r"const P2_NAME_MSG = \{.*?\n    \};", APPJS, re.S).group(0)
    check("86. абсолютный путь пользователю не показывается",
          not any(t in _msg for t in ("DATA_DIR", "project_files", "C:\\", "${", "AppData")))
    check("87. traceback/текст исключения сервера не показывается",
          "traceback" not in _msg.lower() and "sqlite" not in _msg.lower()
          and "reason" not in _msg and "e.message" not in _cp + _sp)
    check("88. backend-ответ 409 обрабатывается отдельно (читается машинный reason)",
          "_p2Reason(r)" in _cp and "_p2Reason(r)" in _sp
          and "j.reason" in APPJS.replace("(j && j.reason)", "j.reason"))
    check("89. frontend precheck не является границей безопасности: сервер проверяет заново",
          "НЕ граница безопасности" in _cp and "НЕ граница безопасности" in _sp
          and "_assert_project_name_available" in fn_src("create_project")
          and "_assert_project_name_available" in fn_src("rename_project_atomic")
          and "create_project" in fn_src("c_project2")
          and "rename_project_atomic" in fn_src("u_project2")
          # устаревший список на клиенте не обходит границу: проверка идёт ПОД локом, а не по запросу
          and fn_src("create_project").index("with _lock_pname:")
              < fn_src("create_project").index("INSERT INTO projects"))

    # ═══════════════════════════ REGRESSION (90-101) ════════════════════════
    section("регрессия Alpha 2.800–2.803 и границы")
    usb_src = make(os.path.join(USB, "usb_plate.gcode.3mf"), THUMB + BODY + b"USB")
    _usb_sha = sha256_of(usb_src)
    _dest_dir = resolve("project", P123, "123")
    _copied, _sha_c, _sz = NS["_import_copy_managed"](usb_src, _dest_dir, "usb_plate.gcode.3mf")
    add_file("pf_usb", P123, "usb_plate.gcode.3mf", stored=_copied)
    check("90. managed-копия с внешнего носителя (Alpha 2.801) работает",
          os.path.isfile(_copied) and _sha_c == _usb_sha and sha256_of(_copied) == _usb_sha
          and os.path.dirname(_copied) == os.path.join(PF, "123") and os.path.isfile(usb_src))
    check("91. оригинальный предпросмотр слайсера (Alpha 2.800) сохраняется",
          (rb(_copied) or b"").startswith(THUMB) and (rb(stored_of(FIDM)) or b"").startswith(THUMB))
    orphan = make(os.path.join(PF, "123", "orphan.gcode"), BODY)
    purge()
    check("92. стартовая чистка (Alpha 2.802) не удаляет папки с DB-referenced файлами",
          os.path.isfile(stored_of(FID123)) and os.path.isfile(_copied)
          and os.path.isdir(os.path.join(PF, "123")) and not os.path.exists(orphan)
          and os.path.isfile(os.path.join(PF, "123", "_removed", "orphan.gcode"))   # 16.10.2026: в «_removed»
          and os.path.isfile(unknown_file) and os.path.isdir(unknown_dir))
    check("93. папки конвенции Alpha 2.803 безопасно мигрируются (без потери единственной копии)",
          os.path.isfile(stored_of(FIDM)) and os.path.dirname(stored_of(FIDM)) == os.path.join(PF, "897")
          and os.path.isfile(stored_of(FIDL)) and os.path.isdir(dl))
    _to_proj = fn_src("staging_to_project")
    check("94. task->project пишет в папку с именем проекта (через единый резолвер)",
          "_unique_dest(_project_dir(project)" in _to_proj
          and "resolve_managed_owner_directory" in fn_src("_project_dir")
          and project_dir({"id": P123, "name": "123"}) == os.path.join(PF, "123")
          and "staging_files (filename TEXT PRIMARY KEY" in SRV)
    check("94b. контракт задач не изменён: одна общая папка slicer_uploads",
          resolve("task", "any", "Задача") == UP and NS["_managed_owner_root"]("task") == UP)
    check("95. Moonraker pipeline не изменён",
          "_moonraker_print_started" in SRV and "_moonraker_http_error_reason" in SRV)
    check("96. границы auth/LAN/WebSocket не менялись",
          "_SECURITY_ENABLED" in SRV and "_lan_effective_decision" in SRV and "active_ws" in SRV)
    check("97. DISPATCH_ENABLED остаётся False",
          re.search(r"^DISPATCH_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("98. TRANSPORT_ENABLED остаётся False",
          re.search(r"^TRANSPORT_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("99. `_incoming/` не используется продуктовым кодом",
          not any(t in SRV for t in ('"_incoming"', "'_incoming'", "_incoming/", "_incoming\\\\"))
          and "_incoming" not in APPJS)
    check("100. артефакты тестов не создаются",
          not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json"))
          and SENTINEL not in SRV and SENTINEL not in ORCH and SENTINEL not in APPJS
          and SENTINEL not in INDEX)
    check("100b. массовой миграции при старте нет и DATA_DIR рекурсивно не сканируется",
          "_reconcile_owner_files" not in fn_src("lifespan")
          and "_rename_owner_dir_to_desired" not in fn_src("lifespan")
          and "rename_project_atomic" not in fn_src("lifespan")
          and "os.walk" not in fn_src("_reconcile_owner_files")
          and "os.walk" not in fn_src("_rename_owner_dir_to_desired")
          and "os.walk" not in fn_src("_owner_suffix_dirs"))
    check("100c. схема БД не менялась (столбцы projects прежние)",
          {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()} ==
          {"id", "name", "due_date", "order_idx", "is_deleted", "created_at", "updated_at", "is_archived"}
          and "ALTER TABLE projects ADD COLUMN canonical" not in SRV)
    check("100d. временный корень изолирован от рабочих папок",
          os.path.normcase(ROOT).startswith(os.path.normcase(tempfile.gettempdir()))
          and REPO.lower() not in ROOT.lower())

finally:
    conn.close()
    shutil.rmtree(ROOT, ignore_errors=True)

check("101. временный корень удалён после теста", not os.path.exists(ROOT))

print("\n" + "=" * 76)
if FAILED:
    print("FAIL: провалено %d из %d" % (len(FAILED), len(FAILED) + PASSED[0]))
    for n in FAILED:
        print("   - %s" % n)
    _DONE["ok"] = True
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ (%d)" % PASSED[0])
_DONE["ok"] = True
sys.exit(0)
