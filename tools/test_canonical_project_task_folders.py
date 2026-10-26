# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.802 — ЕДИНАЯ каноническая папка для каждого проекта и задачи.
#
#  ПОЛНОСТЬЮ OFFLINE. server.py НЕ импортируется обычным способом: реальные функции резолвера
#  и согласования извлекаются разбором AST и исполняются в изоляции поверх ВРЕМЕННОЙ SQLite
#  (схема взята из самого server.py) и ВРЕМЕННОГО managed-корня. Ни рабочей БД, ни рабочего
#  DATA_DIR, ни сети, ни принтера, ни слайсера. Реальные пользовательские файлы не используются;
#  содержимое файлов в вывод не печатается; абсолютные пути пользователя не выводятся.
#
#  ЧТО ДОКАЗЫВАЕТ. У одного проекта — ОДНА физическая папка: резолвер переиспользует уже
#  используемую папку (в т.ч. legacy «898») и не заводит рядом вторую с техническим именем;
#  все способы добавления файла берут папку у ОДНОГО резолвера; ранее созданные копии
#  согласуются идемпотентно и БЕЗОПАСНО (копия+SHA-256 -> одна транзакция БД -> и только потом
#  удаление старой копии и ПУСТОЙ старой папки); неизвестные файлы не удаляются; стартовая
#  чистка больше не сносит папку целиком по одному лишь имени.
#
#  Запуск:  python tools/test_canonical_project_task_folders.py   (0 = всё пройдено)
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


SENTINEL = "CANONICAL_OWNER_FOLDER_SENTINEL_2_802"

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


# ── изолированное окружение ────────────────────────────────────────────────
ROOT = tempfile.mkdtemp(prefix="fm_canon_")
DATA = os.path.join(ROOT, "data")
PF = os.path.join(DATA, "project_files")
UP = os.path.join(DATA, "slicer_uploads")
TMPF = os.path.join(DATA, "temp_files")
USB = os.path.join(ROOT, "USB_DRIVE")
for d in (PF, UP, TMPF, USB):
    os.makedirs(d)
DBP = os.path.join(DATA, "test_parts.db")

conn = sqlite3.connect(DBP, check_same_thread=False)
conn.row_factory = sqlite3.Row
DDL = [m.group(0) for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (?:projects|project_files|staging_files) \([^\"]*?\)(?=\")", SRV)]
assert len(DDL) >= 3, "не найдены DDL таблиц в server.py"
for q in DDL:
    conn.execute(q)
# те же аддитивные ALTER-миграции, что применяет init_db в server.py (staging_files.src_path и др.)
for col in ["required_qty INTEGER DEFAULT 1", "printed_qty INTEGER DEFAULT 0", "target_nozzles INTEGER DEFAULT 0",
            "target_model TEXT DEFAULT ''", "is_printable INTEGER DEFAULT 0", "notes TEXT DEFAULT ''",
            "src_path TEXT DEFAULT ''"]:
    try:
        conn.execute("ALTER TABLE staging_files ADD COLUMN %s" % col)
    except Exception:
        pass
conn.commit()

NS = {
    "os": os, "re": re, "hashlib": hashlib, "secrets": secrets, "shutil": shutil, "log": _Log(),
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
           "_rename_owner_dir_to_desired",
           "resolve_managed_owner_directory", "_reconcile_owner_files", "_project_dir",
           "_purge_orphan_files"):
    src = fn_src(_f)
    assert src, "функция %s не найдена в server.py" % _f
    exec(compile(src, "<server>", "exec"), NS)

resolve = NS["resolve_managed_owner_directory"]
reconcile = NS["_reconcile_owner_files"]
owner_dirs = NS["_owner_stored_dirs"]
dir_name = NS["_safe_owner_dir_name"]
project_dir = NS["_project_dir"]
purge = NS["_purge_orphan_files"]
sha256_of = NS["_managed_file_sha256"]

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


def add_file(fid, pid, fname, stored="", src=""):
    conn.execute("INSERT INTO project_files (id, project_id, filename, src_path, stored_path) VALUES (?,?,?,?,?)",
                 (fid, pid, fname, src, stored))
    conn.commit()


def stored_of(fid):
    r = conn.execute("SELECT stored_path FROM project_files WHERE id=?", (fid,)).fetchone()
    return r["stored_path"] if r else ""


def dirs_now():
    return sorted(d for d in os.listdir(PF) if os.path.isdir(os.path.join(PF, d)))


try:
    print("=== Alpha 2.802: единая каноническая папка проекта и задачи (offline) ===")

    # ─────────────────────────────────────────────────────────────────────
    section("сценарий владельца: проект «898» с двумя параллельными папками")
    P1, N1 = "proj_4c748803c47c", "898"
    add_project(P1, N1)
    f_old = make(os.path.join(PF, "898", "plate_A.gcode.3mf"), THUMB + BODY)     # папка по ИМЕНИ (legacy)
    f_new = make(os.path.join(PF, P1, "plate_B.gcode"), THUMB + BODY + b"B")     # папка по ID (Alpha 2.801)
    add_file("pfile_A", P1, "plate_A.gcode.3mf", stored=f_old)
    add_file("pfile_B", P1, "plate_B.gcode", stored=f_new)
    sha_new_before = sha256_of(f_new)

    check("10. несколько managed-папок одного владельца обнаруживаются по БД",
          set(owner_dirs("project", P1)) == {"898", P1})
    check("1. существующая папка проекта «898» переиспользуется резолвером",
          os.path.basename(resolve("project", P1, N1)) == "898")
    check("35. резолвер не принимает путь назначения (нет параметра пути в сигнатуре)",
          set(NS["resolve_managed_owner_directory"].__code__.co_varnames[:4]) ==
          {"owner_kind", "owner_id", "display_name", "create"})

    # Alpha 2.803 уточнила контракт (папка догоняет название), Alpha 2.804 — довела его до конца:
    # желаемое имя папки = РОВНО название проекта, без идентификатора (см.
    # test_project_name_only_folders и test_project_folder_rename_consistency).
    DESIRED1 = "898"
    res = reconcile("project", P1, N1)
    new_path = stored_of("pfile_B")
    check("11. DB-referenced файл безопасно перенесён в каноническую папку",
          res["moved"] == 1 and os.path.isfile(new_path)
          and os.path.basename(os.path.dirname(new_path)) == DESIRED1)
    check("12. stored_path обновлён только на проверенную копию (SHA-256 совпал)",
          sha256_of(new_path) == sha_new_before and open(new_path, "rb").read() == THUMB + BODY + b"B")
    check("13. старая копия удалена ПОСЛЕ commit (по старому пути файла нет)", not os.path.exists(f_new))
    check("19. пустая техническая папка удалена после успешного согласования",
          res["dirs_removed"] == 1 and not os.path.isdir(os.path.join(PF, P1)))
    check("2. параллельная папка proj_<id> не остаётся и не создаётся заново", dirs_now() == [DESIRED1])
    check("5. все файлы проекта лежат в одном каталоге",
          {os.path.dirname(stored_of(f)) for f in ("pfile_A", "pfile_B")} == {os.path.join(PF, DESIRED1)})
    _rec_src = fn_src("_reconcile_owner_files")
    _i_ver = _rec_src.find("_managed_file_sha256(new) != sha")
    _i_upd = _rec_src.find("UPDATE project_files SET stored_path")
    _i_del = _rec_src.find("_unlink_in_managed(old)")
    check("12b. порядок жёстко зафиксирован: проверка копии -> UPDATE+commit -> удаление старой",
          0 <= _i_ver < _i_upd < _i_del and "conn_p.commit()" in _rec_src
          and _rec_src.find("conn_p.commit()") < _i_del)
    check("13b. удаление старой копии идёт только через _unlink_in_managed (внутри managed-папок)",
          "os.remove(old)" not in _rec_src and "shutil.rmtree" not in _rec_src)
    _again = reconcile("project", P1, N1)
    check("20. повторное согласование идемпотентно (переносить и переименовывать нечего)",
          _again["moved"] == 0 and _again["skipped"] == 0 and _again["dirs_removed"] == 0
          and _again["renamed"] == 0 and dirs_now() == [DESIRED1])
    check("4. upload и выбор с диска получают ОДНУ И ТУ ЖЕ папку",
          resolve("project", P1, N1) == resolve("project", P1) == os.path.join(PF, DESIRED1))

    section("сохранность содержимого после переноса: превью, анализ, печать")
    moved = open(new_path, "rb").read()
    check("21/24. предпросмотр слайсера (Alpha 2.800) сохраняется — thumbnail на месте",
          moved.startswith(THUMB) and b"thumbnail begin" in moved)
    check("22. анализ работает: байты и SHA-256 не изменились", sha256_of(new_path) == sha_new_before)
    resolver = lambda stored, src: stored or src
    check("23. resolver печати (stored_path or src_path) указывает на существующий файл",
          os.path.isfile(resolver(stored_of("pfile_B"), "")))
    check("25. исходник на USB не требуется: src_path пуст, файл читается",
          conn.execute("SELECT src_path FROM project_files WHERE id='pfile_B'").fetchone()["src_path"] == ""
          and len(moved) > 0)

    section("имена папок новых владельцев: РОВНО название проекта (Alpha 2.804)")
    P2 = "proj_99887766aabb"
    add_project(P2, "899")
    d2 = resolve("project", P2, "899")
    check("6. ВТОРОЙ живой проект с названием «898» запрещён контрактом 2.804",
          NS["_project_name_taken_by"](P2, NS["_project_name_canonical_key"]("898")) == P1
          and NS["_project_name_taken_by"](P2, NS["_project_name_canonical_key"]("899")) == ""
          and NS["_project_folder_state"](P2, "898") == "foreign")
    check("7. новому проекту создаётся папка, равная его названию (без id и суффикса)",
          os.path.basename(d2) == "899"
          and all(t not in os.path.basename(d2) for t in ("__project_", "proj_", NS["_short_owner_id"](P2))))
    check("7b. имя папки стабильно между вызовами", resolve("project", P2, "899") == d2)

    section("переименование проекта не создаёт новую папку")
    conn.execute("UPDATE projects SET name=? WHERE id=?", ("Заказ 898 (июль)", P1))
    conn.commit()
    check("8. сразу после переименования резолвер возвращает ту же физическую папку (второй нет)",
          resolve("project", P1) == os.path.join(PF, DESIRED1)
          and sorted(dirs_now()) == sorted([DESIRED1, os.path.basename(d2)]))

    section("legacy-папка без записей в БД")
    P3 = "proj_1122334455ff"
    add_project(P3, "Кронштейн")
    os.makedirs(os.path.join(PF, "Кронштейн"))
    check("9. существующая legacy-папка с уникальным именем продолжает использоваться",
          resolve("project", P3, "Кронштейн") == os.path.join(PF, "Кронштейн"))
    P4 = "proj_ffeeddccbbaa"                     # Alpha 2.804: второго «Кронштейна» быть не может
    check("9b. занятое название и занятая папка блокируют второй проект (fail-closed)",
          NS["_project_name_taken_by"](P4, NS["_project_name_canonical_key"]("Кронштейн")) == P3
          and NS["_project_folder_state"](P4, "Кронштейн") == "foreign")

    section("коллизии имён файлов при согласовании")
    P5 = "proj_5a5a5a5a5a5a"
    add_project(P5, "Коллизии")
    canon5 = resolve("project", P5, "Коллизии")
    keep = make(os.path.join(canon5, "same.gcode"), b"ORIGINAL-KEEP")
    add_file("pfile_keep", P5, "same.gcode", stored=keep)
    other = make(os.path.join(PF, "old_dir_5", "same.gcode"), b"DIFFERENT-CONTENT")
    add_file("pfile_other", P5, "same.gcode", stored=other)
    reconcile("project", P5, "Коллизии")
    check("15. коллизия не перезаписывает чужой файл (уникальное имя, оригинал цел)",
          open(keep, "rb").read() == b"ORIGINAL-KEEP"
          and os.path.normcase(stored_of("pfile_other")) != os.path.normcase(keep)
          and open(stored_of("pfile_other"), "rb").read() == b"DIFFERENT-CONTENT")
    dup = make(os.path.join(PF, "old_dir_5b", "same.gcode"), b"ORIGINAL-KEEP")
    add_file("pfile_dup", P5, "same.gcode", stored=dup)
    reconcile("project", P5, "Коллизии")
    check("16. идентичный SHA-256 безопасно переиспользует уже лежащую копию",
          os.path.normcase(stored_of("pfile_dup")) == os.path.normcase(keep) and not os.path.exists(dup))

    section("защита неизвестных файлов и непустых папок")
    P6 = "proj_6b6b6b6b6b6b"
    add_project(P6, "Смешанная")
    canon6 = resolve("project", P6, "Смешанная")
    add_file("pfile_anchor6", P6, "anchor.gcode", stored=make(os.path.join(canon6, "anchor.gcode"), BODY))
    mixed_dir = os.path.join(PF, "old_dir_6")
    mv = make(os.path.join(mixed_dir, "move_me.gcode"), BODY)
    unknown = make(os.path.join(mixed_dir, "заметки_пользователя.txt"), b"user notes")
    add_file("pfile_mv", P6, "move_me.gcode", stored=mv)
    reconcile("project", P6, "Смешанная")
    check("17. неизвестный файл в старой папке НЕ удалён",
          os.path.isfile(unknown) and open(unknown, "rb").read() == b"user notes")
    check("18. непустая старая папка НЕ удалена", os.path.isdir(mixed_dir))
    check("18b. свой файл при этом перенесён в каноническую папку",
          os.path.dirname(stored_of("pfile_mv")) == canon6 and not os.path.exists(mv))

    section("общая ссылка и отказ БД")
    P7 = "proj_7c7c7c7c7c7c"
    add_project(P7, "Общая ссылка")
    shared = make(os.path.join(PF, "old_dir_7", "shared.gcode"), BODY)
    add_file("pfile_s1", P7, "shared.gcode", stored=shared)
    conn.execute("INSERT INTO project_files (id, project_id, filename, src_path, stored_path) VALUES (?,?,?,?,?)",
                 ("pfile_s2", "proj_other_owner", "shared.gcode", "", shared))
    conn.commit()
    reconcile("project", P7, "Общая ссылка")
    check("30. файл с ОСТАВШЕЙСЯ ссылкой другой записи не удаляется", os.path.isfile(shared))

    P8 = "proj_8d8d8d8d8d8d"
    add_project(P8, "Отказ БД")
    canon8 = resolve("project", P8, "Отказ БД")
    add_file("pfile_anchor8", P8, "anchor.gcode", stored=make(os.path.join(canon8, "anchor.gcode"), BODY))
    fail_src = make(os.path.join(PF, "old_dir_8", "fail.gcode"), BODY)
    add_file("pfile_f", P8, "fail.gcode", stored=fail_src)

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
        reconcile("project", P8, "Отказ БД")
    except Exception:
        pass
    NS["conn_p"] = conn
    check("14. при отказе БД старая копия и старая ссылка сохранены",
          os.path.isfile(fail_src) and os.path.normcase(stored_of("pfile_f")) == os.path.normcase(fail_src))
    reconcile("project", P8, "Отказ БД")
    check("14b. после восстановления БД повтор безопасно завершает перенос",
          os.path.dirname(stored_of("pfile_f")) == resolve("project", P8, "Отказ БД") and not os.path.exists(fail_src))

    section("внешние оригиналы и недоступные файлы не трогаются")
    P9 = "proj_9e9e9e9e9e9e"
    add_project(P9, "Внешние")
    canon9 = resolve("project", P9, "Внешние")
    add_file("pfile_anchor9", P9, "anchor.gcode", stored=make(os.path.join(canon9, "anchor.gcode"), BODY))
    ext = make(os.path.join(USB, "external.gcode"), BODY)
    add_file("pfile_ext", P9, "external.gcode", src=ext)
    add_file("pfile_gone", P9, "gone.gcode", stored=os.path.join(PF, "no_such_dir", "gone.gcode"))
    r9 = reconcile("project", P9, "Внешние")
    check("11b. внешний оригинал (src_path) не копируется и не изменяется",
          os.path.isfile(ext) and stored_of("pfile_ext") == "" and r9["moved"] == 0)
    check("11c. недоступный managed-файл: ссылка сохранена, запись не потеряна",
          r9["skipped"] == 1 and stored_of("pfile_gone").endswith("gone.gcode"))

    section("имена папок: traversal / ADS / reserved / разделители")
    check("31. path traversal блокируется в имени папки",
          "/" not in dir_name("project", "proj_x1x1x1x1x1x1", "../../evil")
          and "\\" not in dir_name("project", "proj_x1x1x1x1x1x1", "../../evil")
          and ".." not in dir_name("project", "proj_x1x1x1x1x1x1", "..").split("__project_")[0])
    check("32. ADS (':stream') блокируется",
          ":" not in dir_name("project", "proj_x2x2x2x2x2x2", "plan:$DATA"))
    check("33. reserved-имя Windows обезврежено",
          dir_name("project", "proj_x3x3x3x3x3x3", "CON").split("__project_")[0] == "_CON")
    check("33b. хвостовые точки/пробелы и запрещённые символы убраны",
          not dir_name("project", "proj_x4x4x4x4x4x4", 'a<b>c|d? . ').split("__project_")[0].endswith((".", " "))
          and not set('<>:"/\\|?*') & set(dir_name("project", "proj_x4x4x4x4x4x4", 'a<b>c|d?')))
    check("33c. пустое имя не даёт пустого сегмента",
          dir_name("project", "proj_x5x5x5x5x5x5", "   ").split("__project_")[0] == "project")

    section("задачи: одна каноническая папка (filename — PRIMARY KEY, task id в схеме нет)")
    check("26. задача использует одну общую каноническую папку slicer_uploads/",
          resolve("task", "any-task", "Срочный заказ") == UP and NS["_managed_owner_root"]("task") == UP)
    _ing, _loc = fn_src("_stage_ingest"), fn_src("_stage_local_paths")
    check("27. task upload и локальный выбор пишут в ОДНУ папку (UPLOAD_DIR)",
          "UPLOAD_DIR" in _ing and "UPLOAD_DIR" in _loc
          and "PROJECT_FILES_DIR" not in _ing and "PROJECT_FILES_DIR" not in _loc)
    check("26b. схема staging_files по-прежнему ключуется именем файла (task id нет)",
          "staging_files (filename TEXT PRIMARY KEY" in SRV)
    _to_proj = fn_src("staging_to_project")
    check("28. task->project берёт КАНОНИЧЕСКУЮ папку проекта (_project_dir -> резолвер)",
          "_project_dir(project)" in _to_proj and "resolve_managed_owner_directory" in fn_src("_project_dir"))
    check("28b. перед переносом задача согласует папки целевого проекта",
          "_reconcile_owner_files" in _to_proj)
    check("29. после переноса файл лежит в папке ПРОЕКТА, а не в папке задачи",
          "_unique_dest(_project_dir(project)" in _to_proj and "UPLOAD_DIR" not in _to_proj.split("dest =")[1][:400])
    check("28c. каноническая папка проекта вычисляется без участия задачи",
          project_dir({"id": P1, "name": "Заказ 898 (июль)"}) == os.path.join(PF, DESIRED1))

    section("единый резолвер во ВСЕХ путях добавления файла")
    ENDPOINTS = ("pick_project2_file", "pickpath_project2_file", "pickpaths_project2_files",
                 "import_files_as_project", "up_project2_file")
    srcs = {e: fn_src(e) for e in ENDPOINTS}
    check("3. все project-эндпоинты берут папку у резолвера",
          all("resolve_managed_owner_directory" in s for s in srcs.values()))
    check("3b. ни один эндпоинт не собирает путь из PROJECT_FILES_DIR и id/имени",
          not any(("PROJECT_FILES_DIR, project_id" in s) or ("PROJECT_FILES_DIR, pid" in s)
                  or ("PROJECT_FILES_DIR, _safe_archive_name" in s) for s in srcs.values()))
    check("3c. согласование запускается при добавлении файла и при открытии проекта",
          all("_reconcile_owner_files" in s for s in srcs.values() if s is not srcs["import_files_as_project"])
          and "_reconcile_owner_files" in fn_src("g_project2_tree"))
    check("35b. фронтенд не задаёт папку назначения (в теле запроса её не читают)",
          not any(re.search(r"body\.get\(['\"](dir|dest|folder|target_dir|path_dir)['\"]", s) for s in srcs.values()))
    _fnode_keys = set()
    for _n in ast.walk(ast.parse(fn_src("get_project_tree"))):
        if (isinstance(_n, ast.Assign) and any(getattr(t, "id", "") == "fnode" for t in _n.targets)
                and isinstance(_n.value, ast.Dict)):
            _fnode_keys = {k.value for k in _n.value.keys if isinstance(k, ast.Constant)}
    check("34. API проекта не отдаёт stored_path/абсолютный путь в дереве файлов",
          bool(_fnode_keys) and not ({"stored_path", "src_path"} & _fnode_keys)
          and "stored_path" not in fn_src("g_project2_tree"))

    section("массовой миграции нет; стартовая чистка больше не сносит папку по имени")
    _purge_src = fn_src("_purge_orphan_files")
    check("39a. стартовая чистка не удаляет папки целиком (shutil.rmtree убран)",
          "shutil.rmtree" not in _purge_src and "proj_names" not in _purge_src)
    check("39b. массовой миграции всех проектов при старте нет",
          "_reconcile_owner_files" not in fn_src("lifespan")
          and not re.search(r"for .* in list_projects\(\)[\s\S]{0,200}_reconcile_owner_files", SRV))
    P10 = "proj_aaaabbbbcccc"
    add_project(P10, "Чистка")
    keep_ref = make(os.path.join(PF, P10, "referenced.gcode"), BODY)      # папка с ТЕХНИЧЕСКИМ именем
    add_file("pfile_keep2", P10, "referenced.gcode", stored=keep_ref)
    orphan = make(os.path.join(PF, P10, "orphan.gcode"), BODY)
    keep_unknown = make(os.path.join(PF, "old_dir_6", "заметки_пользователя.txt"), b"user notes")
    purge()
    check("39c. файл с ссылкой в БД переживает стартовую чистку в ЛЮБОЙ папке",
          os.path.isfile(keep_ref) and os.path.isdir(os.path.join(PF, P10)))
    check("39d. осиротевший печатный файл без ссылки убран из папки в «_removed» (16.10.2026: хранится 14 дней, а не стирается)",
          not os.path.exists(orphan) and os.path.isfile(os.path.join(os.path.dirname(orphan), "_removed", os.path.basename(orphan))))
    check("39e. папка с неизвестным файлом сохраняется", os.path.isfile(keep_unknown))

    section("границы: schema / dispatch / _incoming / артефакты")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(project_files)").fetchall()}
    check("36a. схема project_files не менялась (нет новых столбцов)",
          cols == {"id", "project_id", "filename", "src_path", "stored_path", "content_hash", "status",
                   "printer_id", "target_nozzles", "target_model", "is_printable", "order_idx", "notes",
                   "created_at", "updated_at"})
    check("36b. новых ALTER TABLE/миграций для 2.802 нет",
          "ALTER TABLE project_files ADD COLUMN" not in SRV and "DROP TABLE" not in SRV)
    check("36. DISPATCH_ENABLED остаётся False", re.search(r"^DISPATCH_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("37. TRANSPORT_ENABLED остаётся False", re.search(r"^TRANSPORT_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("38. `_incoming/` не используется продуктовым кодом",
          not any(t in SRV for t in ('"_incoming"', "'_incoming'", "_incoming/", "_incoming\\\\")))
    check("38b. sentinel не попал в продуктовый код", SENTINEL not in SRV)
    check("39. посторонние артефакты в tools/ не создаются",
          not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))
    check("40a. временный корень изолирован от рабочих папок",
          os.path.normcase(ROOT).startswith(os.path.normcase(tempfile.gettempdir()))
          and REPO.lower() not in ROOT.lower())

finally:
    conn.close()
    import shutil as _sh
    _sh.rmtree(ROOT, ignore_errors=True)

check("40. временный корень удалён после теста", not os.path.exists(ROOT))

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
