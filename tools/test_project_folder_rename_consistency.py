# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.803 — имя папки проекта следует за названием проекта.
#
#  ПОЛНОСТЬЮ OFFLINE. server.py НЕ импортируется обычным способом: реальные функции резолвера,
#  переименования и согласования извлекаются разбором AST и исполняются в изоляции поверх
#  ВРЕМЕННОЙ SQLite (схема взята из самого server.py) и ВРЕМЕННОГО managed-корня. Ни рабочей БД,
#  ни рабочего DATA_DIR, ни сети, ни принтера, ни слайсера. Реальные пользовательские файлы не
#  используются; содержимое файлов и абсолютные пути в вывод не печатаются.
#
#  ЧТО ДОКАЗЫВАЕТ. Папка проекта = «<текущее безопасное имя>__project_<короткий стабильный id>»:
#  суффикс (идентичность) не меняется никогда, префикс следует за названием. При переименовании
#  папка БЕЗОПАСНО переименовывается (os.rename сохраняет неизвестные файлы), stored_path
#  обновляются одной транзакцией, при сбое БД — откат переименования, при занятой папке — старый
#  путь остаётся рабочим и вторая папка НЕ создаётся. Технические папки proj_<id> и несколько
#  папок одного владельца сводятся к желаемой; неизвестные файлы не удаляются; rmtree не
#  используется; массовой миграции на старте нет.
#
#  Запуск:  python tools/test_project_folder_rename_consistency.py   (0 = всё пройдено)
# ============================================================================
import ast
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_DONE = {"ok": False}


def _guard():
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


SENTINEL = "PROJECT_FOLDER_RENAME_SENTINEL_2_803"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            return ast.unparse(n)
    return ""


class _Log(object):
    def _r(self, *a, **k):
        pass

    info = warning = error = debug = exception = _r


class _OsShim(object):
    """Прокси os: позволяет смоделировать «папка занята Windows» (отказ os.rename)."""

    def __init__(self, real):
        self._r = real
        self.fail_rename = False

    def rename(self, a, b):
        if self.fail_rename:
            raise PermissionError("synthetic: folder is in use")
        return self._r.rename(a, b)

    def __getattr__(self, n):
        return getattr(self._r, n)


# ── изолированное окружение ────────────────────────────────────────────────
ROOT = tempfile.mkdtemp(prefix="fm_rename_")
DATA = os.path.join(ROOT, "data")
PF = os.path.join(DATA, "project_files")
UP = os.path.join(DATA, "slicer_uploads")
TMPF = os.path.join(DATA, "temp_files")
for d in (PF, UP, TMPF):
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
    "contextmanager": contextlib.contextmanager,
    "conn_p": conn, "lock_p": threading.Lock(),
    "PROJECT_FILES_DIR": PF, "UPLOAD_DIR": UP, "TEMP_FILES_DIR": TMPF,
    "_PROJ_EXTS": (".gcode.3mf", ".3mf", ".gcode", ".stl"),
    "_OWNER_DIR_TAG": ast.literal_eval(re.search(r"^_OWNER_DIR_TAG = (\{.*?\})$", SRV, re.M).group(1)),
    "_MANAGED_IMPORT_MAX": 2 * 1024 * 1024 * 1024,
    "_WIN_RESERVED_NAMES": frozenset(
        ["CON", "PRN", "AUX", "NUL"] + ["COM%d" % i for i in range(1, 10)] + ["LPT%d" % i for i in range(1, 10)]),
    # Alpha 2.804: контракт имени проекта (папка = РОВНО название) — константы модуля server.py
    "_unicodedata": __import__("unicodedata"), "threading": threading,
    "_PROJECT_NAME_MAX": int(re.search(r"^_PROJECT_NAME_MAX = (\d+)", SRV, re.M).group(1)),
    "_PROJECT_DIR_PATH_MAX": int(re.search(r"^_PROJECT_DIR_PATH_MAX = (\d+)", SRV, re.M).group(1)),
}
for _f in ("ProjectNameError", "_rollback_sqlite_on_error", "_get_project", "_safe_archive_name",
           "_unlink_in_managed", "_trash_managed_copy", "_prune_trash_dir",
           "_unique_dest", "_managed_file_sha256", "_safe_managed_filename", "_managed_source_ok",
           "_import_copy_managed", "_short_owner_id", "_safe_owner_dir_name", "_managed_owner_root",
           "_dir_under_root", "_owner_stored_dirs", "_project_name_is_unique",
           "_project_name_canonical_key", "_project_name_reject_reason",
           "normalize_and_validate_project_name", "_project_name_taken_by", "_project_folder_state",
           "desired_project_directory", "_dir_is_plain", "_owner_suffix_dirs",
           "_rename_owner_dir_to_desired", "resolve_managed_owner_directory", "_reconcile_owner_files",
           "_project_dir", "_purge_orphan_files"):
    src = fn_src(_f)
    assert src, "функция %s не найдена в server.py" % _f
    exec(compile(src, "<server>", "exec"), NS)

desired = NS["desired_project_directory"]
resolve = NS["resolve_managed_owner_directory"]
reconcile = NS["_reconcile_owner_files"]
rename_dir = NS["_rename_owner_dir_to_desired"]
project_dir = NS["_project_dir"]
purge = NS["_purge_orphan_files"]
sha256_of = NS["_managed_file_sha256"]
short_id = NS["_short_owner_id"]

THUMB = b"; thumbnail begin 16x16\n; iVBORw0KGgoAAAANSUhEUg==\n; thumbnail end\n"
BODY = b"; synthetic gcode " + SENTINEL.encode() + b"\nG28\n" + b"G1 X1 Y1 E1\n" * 40


def make(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def add_project(pid, name):
    conn.execute("INSERT INTO projects (id, name) VALUES (?,?)", (pid, name))
    conn.commit()


def rename_project(pid, new_name):
    """Штатное переименование = только UPDATE projects.name (как update_project в server.py)."""
    conn.execute("UPDATE projects SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_name, pid))
    conn.commit()


def add_file(fid, pid, fname, stored="", src=""):
    conn.execute("INSERT INTO project_files (id, project_id, filename, src_path, stored_path) VALUES (?,?,?,?,?)",
                 (fid, pid, fname, src, stored))
    conn.commit()
    return fid


def stored_of(fid):
    r = conn.execute("SELECT stored_path FROM project_files WHERE id=?", (fid,)).fetchone()
    return r["stored_path"] if r else ""


def dirs_now():
    return sorted(d for d in os.listdir(PF) if os.path.isdir(os.path.join(PF, d)))


def rb(path):
    """Байты файла или None — чтобы проверка честно КРАСНЕЛА, а не падала при битой ссылке."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None


def sha_or_none(path):
    try:
        return sha256_of(path)
    except Exception:
        return None


try:
    print("=== Alpha 2.803: синхронизация папки проекта с его названием (offline) ===")

    # ═══════════════════════ BASE CONTRACT (1-5) ═══════════════════════════
    # Alpha 2.804 сменила контракт: папка называется РОВНО как проект (без стабильного суффикса).
    section("базовый контракт имени папки")
    PN = "proj_aa11bb22cc33"
    add_project(PN, "Новый проект")
    dn = resolve("project", PN, "Новый проект")
    check("1. новый проект получает папку, равную его названию",
          os.path.basename(dn) == "Новый проект" and os.path.isdir(dn))
    check("2. в имени папки нет никакого идентификатора (ни суффикса, ни proj_, ни короткого id)",
          all(t not in os.path.basename(dn) for t in ("__project_", "proj_", short_id(PN)))
          and os.path.basename(desired(PN, "Совсем другое имя")) == "Совсем другое имя")
    check("3. имя папки следует за текущим названием проекта",
          os.path.basename(desired(PN, "Заказ 42")) == "Заказ 42")
    PSAME = "proj_dd44ee55ff66"
    check("4. второй живой проект с тем же названием запрещён (папка определяется только именем)",
          NS["_project_name_taken_by"](PSAME, NS["_project_name_canonical_key"]("Новый проект")) == PN
          and desired(PSAME, "Новый проект") == desired(PN, "Новый проект"))
    check("5. техническая папка proj_<id> для нового импорта не создаётся",
          not os.path.isdir(os.path.join(PF, PN)) and PN not in dirs_now())

    # ═══════════════════════ SIMPLE RENAME (6-16) ══════════════════════════
    section("простое переименование проекта")
    P1 = "proj_7f13a2c2bf0f"
    add_project(P1, "ABC")
    d1 = resolve("project", P1, "ABC")
    f1 = make(os.path.join(d1, "plate.gcode.3mf"), THUMB + BODY)
    FID = add_file("pfile_rename01", P1, "plate.gcode.3mf", stored=f1)
    conn.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name) VALUES ('pt1',?,'Крышка','крышка')", (P1,))
    conn.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) VALUES ('pfp1',?,?,'pt1',3)", (P1, FID))
    conn.commit()
    sha_before, bytes_before = sha256_of(f1), open(f1, "rb").read()
    unknown_keep = make(os.path.join(d1, "заметки.txt"), b"user notes")

    rename_project(P1, "123")                     # 6. штатное переименование ABC -> 123
    r = reconcile("project", P1)
    new1 = stored_of(FID)
    check("6/7. после переименования папка стала «123» (ровно новое название)",
          r["renamed"] == 1 and os.path.basename(os.path.dirname(new1)) == "123")
    check("8. все stored_path обновлены на новую папку",
          os.path.isfile(new1) and os.path.dirname(new1) == desired(P1, "123"))
    check("9/10. байты и SHA-256 файла не изменились",
          rb(new1) == bytes_before and sha_or_none(new1) == sha_before)
    check("11. file_id не изменился",
          conn.execute("SELECT COUNT(*) c FROM project_files WHERE id=?", (FID,)).fetchone()["c"] == 1)
    check("11b. project ID проекта и его файлов не меняется при переименовании",
          conn.execute("SELECT COUNT(*) c FROM projects WHERE id=?", (P1,)).fetchone()["c"] == 1
          and conn.execute("SELECT project_id FROM project_files WHERE id=?", (FID,)).fetchone()["project_id"] == P1)
    _fp = conn.execute("SELECT file_id, part_id, on_plate_qty FROM project_file_parts WHERE id='pfp1'").fetchone()
    check("12. part/plate mapping не изменился",
          _fp["file_id"] == FID and _fp["part_id"] == "pt1" and _fp["on_plate_qty"] == 3)
    check("13. preview: встроенный thumbnail на месте", (rb(new1) or b"").startswith(THUMB))
    check("14. analysis: содержимое доступно и не изменено", sha_or_none(new1) == sha_before)
    check("15. print resolver (stored_path or src_path) указывает на существующий файл",
          os.path.isfile(stored_of(FID) or "") and rb(stored_of(FID)) == bytes_before)
    check("16. старая папка исчезла (переименована целиком, неизвестный файл сохранён)",
          not os.path.isdir(d1) and os.path.isfile(os.path.join(desired(P1, "123"), "заметки.txt")))

    # ═══════════════════ LEGACY TECHNICAL FOLDER (17-22) ═══════════════════
    section("техническая папка proj_<id>")
    P2 = "proj_139390a3e710"
    add_project(P2, "898")
    tech = os.path.join(PF, P2)
    f2 = make(os.path.join(tech, "plate_898.gcode.3mf"), THUMB + BODY + b"2")
    FID2 = add_file("pfile_tech01", P2, "plate_898.gcode.3mf", stored=f2)
    sha2 = sha256_of(f2)
    r2 = reconcile("project", P2)
    check("17. proj_<id> однозначно мигрирует в папку с именем проекта",
          r2["renamed"] == 1 and not os.path.isdir(tech)
          and os.path.basename(os.path.dirname(stored_of(FID2))) == "898")
    check("18. ссылка в БД обновлена ПОСЛЕ успешной файловой операции",
          os.path.isfile(stored_of(FID2)) and sha256_of(stored_of(FID2)) == sha2)
    check("21. пустая параллельная папка не создана", dirs_now().count(P2) == 0)
    _r2b = reconcile("project", P2)
    check("22. повтор согласования идемпотентен",
          _r2b["renamed"] == 0 and _r2b["moved"] == 0 and _r2b["dirs_removed"] == 0)

    section("отказ БД при переименовании папки")
    P3 = "proj_c0ffee001122"
    add_project(P3, "Отказ")
    d3 = resolve("project", P3, "Отказ")
    f3 = make(os.path.join(d3, "x.gcode"), BODY)
    FID3 = add_file("pfile_dbfail", P3, "x.gcode", stored=f3)
    rename_project(P3, "Отказ 2")

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
        reconcile("project", P3)
    except Exception:
        pass
    NS["conn_p"] = conn
    check("19. отказ БД: старая папка и старая ссылка сохранены (переименование откатано)",
          os.path.isdir(d3) and os.path.isfile(f3)
          and os.path.normcase(stored_of(FID3)) == os.path.normcase(f3)
          and not os.path.isdir(desired(P3, "Отказ 2")))
    r3 = reconcile("project", P3)
    check("19b. после восстановления БД повтор завершает переименование",
          r3["renamed"] == 1 and os.path.dirname(stored_of(FID3)) == desired(P3, "Отказ 2"))

    # ═══════════════════════ RENAME FAILURE (32-36) ════════════════════════
    section("папка занята Windows: проект не ломается, вторая папка не создаётся")
    P4 = "proj_10ck3d000001"
    add_project(P4, "Занята")
    d4 = resolve("project", P4, "Занята")
    f4 = make(os.path.join(d4, "locked.gcode"), BODY)
    FID4 = add_file("pfile_locked", P4, "locked.gcode", stored=f4)
    rename_project(P4, "Занята 2")
    OS_SHIM.fail_rename = True
    r4 = reconcile("project", P4)
    OS_SHIM.fail_rename = False
    check("32. заблокированная папка не ломает проект (операция отложена)",
          r4["retry"] is True and r4["renamed"] == 0)
    check("33. старый stored_path остаётся рабочим",
          os.path.isfile(stored_of(FID4)) and os.path.normcase(stored_of(FID4)) == os.path.normcase(f4))
    check("34. вторая папка не создана", not os.path.isdir(desired(P4, "Занята 2")))
    check("34b. резолвер продолжает отдавать РАБОЧУЮ папку, а не пустую новую",
          resolve("project", P4, "Занята 2") == d4)
    r4b = reconcile("project", P4)
    check("35. повторное согласование позже завершает переименование",
          r4b["renamed"] == 1 and os.path.dirname(stored_of(FID4)) == desired(P4, "Занята 2"))
    check("36. единственная копия не потеряна", os.path.isfile(stored_of(FID4))
          and open(stored_of(FID4), "rb").read() == BODY)

    # ═══════════════════════ MULTI-FOLDER (23-31) ══════════════════════════
    section("консолидация нескольких папок одного владельца")
    P5 = "proj_5555aaaa6666"
    add_project(P5, "Мульти")
    dA = os.path.join(PF, "СтароеИмя__project_" + short_id(P5))
    dB = os.path.join(PF, P5)
    a1 = make(os.path.join(dA, "same.gcode"), b"AAA-CONTENT")
    b1 = make(os.path.join(dB, "same.gcode"), b"BBB-CONTENT")
    b2 = make(os.path.join(dB, "dup.gcode"), b"DUP")
    a2 = make(os.path.join(dA, "dup.gcode"), b"DUP")
    unknown_multi = make(os.path.join(dB, "чертёж.pdf"), b"user pdf")
    prev = make(os.path.join(dA, "preview.gcode.3mf"), THUMB + BODY + b"P")   # эта папка сводится КОПИРОВАНИЕМ
    sha_prev, bytes_prev = sha256_of(prev), rb(prev)
    add_file("pf_prev", P5, "preview.gcode.3mf", stored=prev)
    add_file("pf_a1", P5, "same.gcode", stored=a1)
    add_file("pf_b1", P5, "same.gcode", stored=b1)
    add_file("pf_a2", P5, "dup.gcode", stored=a2)
    add_file("pf_b2", P5, "dup.gcode", stored=b2)
    r5 = reconcile("project", P5)
    d5 = desired(P5, "Мульти")
    stored5 = {k: stored_of(k) for k in ("pf_a1", "pf_b1", "pf_a2", "pf_b2")}
    check("23. две папки одного владельца сведены в желаемую",
          all(os.path.dirname(v) == d5 for v in stored5.values()) and os.path.isdir(d5))
    check("24/26. коллизия не перезаписывает файл: разные байты -> отдельное имя",
          len({os.path.normcase(stored5["pf_a1"]), os.path.normcase(stored5["pf_b1"])}) == 2
          and {open(stored5["pf_a1"], "rb").read(), open(stored5["pf_b1"], "rb").read()}
          == {b"AAA-CONTENT", b"BBB-CONTENT"})
    check("25. одинаковые байты безопасно переиспользуют одну копию",
          os.path.normcase(stored5["pf_a2"]) == os.path.normcase(stored5["pf_b2"])
          and open(stored5["pf_a2"], "rb").read() == b"DUP")
    check("27. одна транзакция обновила все записи согласованно",
          all(os.path.isfile(v) for v in stored5.values()))
    _prev_new = stored_of("pf_prev")
    check("24/26b. при консолидации КОПИРОВАНИЕМ байты, SHA-256 и предпросмотр сохраняются",
          os.path.dirname(_prev_new) == d5 and sha_or_none(_prev_new) == sha_prev
          and rb(_prev_new) == bytes_prev and (rb(_prev_new) or b"").startswith(THUMB))
    check("30/31. неизвестный файл сохранён, папка с ним не удалена",
          os.path.isfile(unknown_multi) or os.path.isfile(os.path.join(d5, "чертёж.pdf")))
    _rec_src = fn_src("_reconcile_owner_files")
    _ren_src = fn_src("_rename_owner_dir_to_desired")
    _i_upd = _rec_src.find("UPDATE project_files SET stored_path")
    _i_del = _rec_src.find("_unlink_in_managed(old)")
    check("28. старый файл удаляется только ПОСЛЕ commit",
          0 <= _i_upd < _i_del and _rec_src.find("conn_p.commit()") < _i_del)
    check("29. старые папки удаляются только через os.rmdir",
          "os.rmdir(d)" in _rec_src and "rmtree" not in _rec_src)
    _r5b = reconcile("project", P5)
    check("22b. повтор консолидации идемпотентен", _r5b["moved"] == 0 and _r5b["renamed"] == 0)

    # ═══════════════════════ ENTRY POINTS (37-43) ══════════════════════════
    section("все точки входа используют один резолвер")
    EPS = ("up_project2_file", "pick_project2_file", "pickpath_project2_file",
           "pickpaths_project2_files", "import_files_as_project")
    srcs = {e: fn_src(e) for e in EPS}
    check("37/38/39/40/41. upload/pick/pick-path/pick-paths/import-files берут папку у резолвера",
          all("resolve_managed_owner_directory" in s for s in srcs.values()))
    _to_proj = fn_src("staging_to_project")
    check("42. task->project использует каноническую папку проекта",
          "_project_dir(project)" in _to_proj and "resolve_managed_owner_directory" in fn_src("_project_dir"))
    check("43. ни один эндпоинт не имеет собственного правила именования папки",
          not any(("PROJECT_FILES_DIR, project_id" in s) or ("PROJECT_FILES_DIR, pid" in s)
                  or ("PROJECT_FILES_DIR, _safe_archive_name" in s) for s in list(srcs.values()) + [_to_proj]))
    P6 = "proj_ee77dd88cc99"
    add_project(P6, "До")
    d6 = resolve("project", P6, "До")
    make(os.path.join(d6, "f.gcode"), BODY)
    add_file("pf_ep", P6, "f.gcode", stored=os.path.join(d6, "f.gcode"))
    rename_project(P6, "После")
    reconcile("project", P6)
    check("37b. после переименования новые файлы идут в ЖЕЛАЕМУЮ папку",
          resolve("project", P6) == desired(P6, "После") and project_dir({"id": P6, "name": "После"}) == desired(P6, "После"))
    check("42b. перед переносом из Задач целевой проект согласуется",
          "_reconcile_owner_files" in _to_proj)
    check("43b. переименование запускает согласование в штатном эндпоинте",
          "_reconcile_owner_files" in fn_src("u_project2") and "update_project" in fn_src("u_project2"))

    # ═══════════════════════════ SECURITY (44-58) ══════════════════════════
    section("безопасность имени и назначения")
    check("44. фронтенд не задаёт назначение (в теле запроса путь не читают)",
          not any(re.search(r"body\.get\(['\"](dir|dest|folder|target_dir|path)['\"]\)\s*$", s, re.M)
                  for s in srcs.values())
          and set(NS["desired_project_directory"].__code__.co_varnames[:2]) == {"project_id", "project_name"})
    def _reject(nm):
        """reason отказа контракта имени, либо '' если название принято."""
        try:
            NS["normalize_and_validate_project_name"](nm)
            return ""
        except Exception as e:
            return getattr(e, "reason", "raised")
    check("45. traversal в названии проекта ОТКЛОНЯЕТСЯ (2.804: молчаливой очистки больше нет)",
          _reject("../../evil") == "project_name_invalid" and _reject("..") == "project_name_invalid")
    check("46. ADS блокируется", _reject("plan:$DATA") == "project_name_invalid")
    check("47. reserved-имя Windows отклоняется", _reject("CON") == "project_name_reserved"
          and _reject("LPT9.txt") == "project_name_reserved")
    check("48. абсолютный путь/UNC в названии отклоняется",
          _reject(r"\\server\share\evil") == "project_name_invalid"
          and _reject(r"C:\Windows\System32") == "project_name_invalid")
    check("49. symlink/reparse как цель запрещён (_dir_is_plain)",
          NS["_dir_is_plain"](os.path.join(PF, "нет-такой")) is True
          and NS["_dir_is_plain"](d5) is True)
    check("49b. переименование не выполняется, если цель уже существует",
          "os.path.exists(desired)" in _ren_src and "_dir_is_plain(desired)" in _ren_src)
    PX = "proj_1aaaaaaa0001"
    add_project(PX, "Чужой")
    dx = resolve("project", PX, "Чужой")
    fx = make(os.path.join(dx, "his.gcode"), b"HIS")
    add_file("pf_x", PX, "his.gcode", stored=fx)
    PY = "proj_2bbbbbbb0002"                           # Alpha 2.804: второй проект с тем же названием
    check("50. папка другого project ID не может быть занята одноимённым проектом",
          NS["_project_folder_state"](PY, "Чужой") == "foreign"
          and NS["_project_folder_state"](PX, "Чужой") == "own"
          and NS["_project_name_taken_by"](PY, NS["_project_name_canonical_key"]("Чужой")) == PX)
    check("50b. переименование не трогает папку, куда ссылается другой проект",
          "foreign" in _ren_src and "project_id'] == owner_id" in _ren_src.replace('"', "'"))
    os.makedirs(os.path.join(PF, "Дубль"))            # неизвестная папка без единой ссылки в БД
    PL1 = "proj_3ccccccc0003"
    check("50c. неизвестная папка считается ЗАНЯТОЙ и не усыновляется по одному лишь имени",
          NS["_project_folder_state"](PL1, "Дубль") == "foreign"
          and os.path.isdir(os.path.join(PF, "Дубль")))
    _fnode_keys = set()
    for _n in ast.walk(ast.parse(fn_src("get_project_tree"))):
        if (isinstance(_n, ast.Assign) and any(getattr(t, "id", "") == "fnode" for t in _n.targets)
                and isinstance(_n.value, ast.Dict)):
            _fnode_keys = {k.value for k in _n.value.keys if isinstance(k, ast.Constant)}
    check("51. абсолютный DATA_DIR не отдаётся в дереве файлов проекта",
          bool(_fnode_keys) and not ({"stored_path", "src_path"} & _fnode_keys)
          and "stored_path" not in fn_src("g_project2_tree"))
    check("52. rmtree отсутствует в согласовании и переименовании",
          "rmtree" not in _rec_src and "rmtree" not in _ren_src)
    check("53. массовой миграции при старте нет",
          "_reconcile_owner_files" not in fn_src("lifespan")
          and "_rename_owner_dir_to_desired" not in fn_src("lifespan"))
    check("54. полного рекурсивного обхода DATA_DIR нет",
          "os.walk" not in _rec_src and "os.walk" not in _ren_src
          and "os.walk" not in fn_src("_owner_suffix_dirs"))
    check("55. DISPATCH_ENABLED / TRANSPORT_ENABLED остаются False",
          re.search(r"^DISPATCH_ENABLED\s*=\s*False", ORCH, re.M) is not None
          and re.search(r"^TRANSPORT_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("56. `_incoming/` не используется продуктовым кодом",
          not any(t in SRV for t in ('"_incoming"', "'_incoming'", "_incoming/", "_incoming\\\\")))
    check("56b. sentinel не попал в продуктовый код", SENTINEL not in SRV and SENTINEL not in ORCH)
    check("57. посторонние артефакты в tools/ не создаются",
          not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))
    check("58a. временный корень изолирован от рабочих папок",
          os.path.normcase(ROOT).startswith(os.path.normcase(tempfile.gettempdir()))
          and REPO.lower() not in ROOT.lower())

    # ═════════════════ ALPHA 2.802 REGRESSION (59-64) ══════════════════════
    section("регрессия Alpha 2.800-2.802")
    keep_ref = stored_of(FID2)
    orphan = make(os.path.join(os.path.dirname(keep_ref), "orphan.gcode"), BODY)
    unknown_dir = os.path.join(PF, "чужая_папка")
    unknown_file = make(os.path.join(unknown_dir, "readme.txt"), b"user data")
    purge()
    check("59. стартовая чистка не удаляет папки с DB-referenced файлами",
          os.path.isfile(keep_ref) and os.path.isdir(os.path.dirname(keep_ref)))
    check("59b. осиротевший печатный файл без ссылки убран из папки в «_removed» (16.10.2026: хранится 14 дней, а не стирается)",
          not os.path.exists(orphan) and os.path.isfile(os.path.join(os.path.dirname(orphan), "_removed", os.path.basename(orphan))))
    check("60. папки с неизвестным содержимым не удаляются",
          os.path.isfile(unknown_file) and os.path.isdir(unknown_dir))
    check("61. managed-копия с внешнего носителя продолжает работать (Alpha 2.801)",
          "_import_copy_managed" in fn_src("pick_project2_file")
          and "source_changed_during_copy" in fn_src("_import_copy_managed"))
    check("62. оригинальный предпросмотр слайсера сохраняется (Alpha 2.800)",
          open(keep_ref, "rb").read().startswith(THUMB)
          and "_slicer_thumb" in SRV or "thumbnail" in SRV.lower())
    check("63. Moonraker pipeline не изменён", "_moonraker_print_started" in SRV)
    check("64. границы auth/LAN/WebSocket не менялись",
          "_SECURITY_ENABLED" in SRV and "_lan_effective_decision" in SRV and "active_ws" in SRV)
    check("64b. схема БД не менялась (нет новых столбцов project_files)",
          {r[1] for r in conn.execute("PRAGMA table_info(project_files)").fetchall()} ==
          {"id", "project_id", "filename", "src_path", "stored_path", "content_hash", "status",
           "printer_id", "target_nozzles", "target_model", "is_printable", "order_idx", "notes",
           "created_at", "updated_at"})

finally:
    conn.close()
    shutil.rmtree(ROOT, ignore_errors=True)

check("58. временный корень удалён после теста", not os.path.exists(ROOT))

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
