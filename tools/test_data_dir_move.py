# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Папка данных: общий список, перенос без потерь и ежедневная копия всех баз (29.09.2026).

ЗАЧЕМ. До 29.09.2026 смена папки данных переносила жёсткий список (три базы ядра и четыре
папки): модули, их базы, лицензии и номер установки оставались в старой папке, и программа на
новом месте теряла модули и лицензии. Одноимённый файл в папке назначения молча побеждал
переносимый (устаревшая база подменяла рабочую), а папки-источники удалялись rmtree ещё до
проверки. Ежедневная копия знала те же три базы: базы «Расчёта заказа», «Качества» и уведомлений
не копировались никогда, а без перезапуска копия не делалась вовсе.

ЧТО ДОКАЗЫВАЕТСЯ (исполнением на временных папках; рабочая DATA_DIR не открывается, server.py
не импортируется — нужные функции вырезаются разбором исходника):
  A. общий список app/data_dir_items: решение есть для КАЖДОГО имени, которое ядро и модули
     открывают в папке данных; копии баз — по строгому шаблону своей базы;
  B. перенос: всё из списка доехало побайтно (база вместе с -wal), чужое и временное не тронуто,
     одноимённое в новой папке не перезаписано, при сбое копирования/сверки/места оригиналы
     целы и копии убраны, сбой удаления оригинала не возвращает программу в старую папку;
  C. ядро: неудачный перенос оставляет программу на прежней папке и повторит перенос,
     воркер пула никогда ничего не переносит, изолированный экземпляр не выходит за свою
     папку, смена папки отказывает в папку с данными Farm Manager и внутрь нынешней папки,
     ежедневная копия покрывает все базы и делается фоновым потоком раз в час;
  D. окно «Хранение данных» показывает итог переноса, подсказка говорит правду.

Запуск: python tools/test_data_dir_move.py   (0 = все проверки пройдены)
"""
import ast
import asyncio
import hashlib
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.dont_write_bytecode = True
SENTINEL = "DATA_DIR_MOVE_SENTINEL_2026_09_29"

from app import data_dir_items as D   # noqa: E402
from app import filesystem_access_policy as FSP   # noqa: E402

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:600]) if detail != "" else ""))


def section(t):
    print("\n--- %s ---" % t)


def rd(*parts):
    return io.open(os.path.join(REPO, *parts), encoding="utf-8", errors="replace").read()


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def tree(root):
    """{относительный путь файла: sha256} — снимок папки."""
    out = {}
    for base, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(base, f)
            out[os.path.relpath(p, root).replace("\\", "/")] = sha(p)
    return out


TMP = tempfile.mkdtemp(prefix="fm_data_dir_move_")


def fresh(name):
    p = os.path.join(TMP, name)
    os.makedirs(p)
    return p


def put(root, rel, data=b"x"):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def make_db(path, row):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t (v TEXT)")
    c.execute("INSERT INTO t VALUES (?)", (row,))
    c.commit()
    c.close()


def make_wal_db(path, row):
    """База, чья последняя запись лежит ТОЛЬКО в -wal (как после сбоя питания): копия файлов при
    открытом соединении. Без -wal рядом запись не видна — так проверяется перенос базы тройкой."""
    tmpd = tempfile.mkdtemp(dir=TMP, prefix="wal_")
    live = os.path.join(tmpd, "live.db")
    c = sqlite3.connect(live)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE t (v TEXT)")
    c.commit()
    c.execute("INSERT INTO t VALUES (?)", (row,))
    c.commit()
    for suff in ("", "-wal", "-shm"):
        shutil.copyfile(live + suff, path + suff)
    c.close()


def db_rows(path):
    """Строки базы или None (нет файла / не база) — без создания пустого файла."""
    if not os.path.isfile(path):
        return None
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    except sqlite3.Error:
        return None
    try:
        return [r[0] for r in c.execute("SELECT v FROM t")]
    except sqlite3.Error:
        return None
    finally:
        c.close()


MOVE_FILES = {
    "install_id.txt": "fm-0123456789abcdef01234567",
    "config-restore-journal.json": '{"state": "complete"}',
    "farm_cost_order_module_backup.done": "2026-09-12 10:00:00",
    "modules/cost/module.json": '{"id": "cost", "version": "0.2.2"}',
    "modules/cost/backend.py": "def register(core):\n    pass\n",
    "modules/inventory/module.json": '{"id": "inventory"}',
    "modules_previous/cost/module.json": '{"id": "cost", "version": "0.2.1"}',
    "licenses/L-1.fmlic": '{"format": "fm-license"}',
    "cost_order_files/ord_1/bracket.gcode": "G28\nG1 X1\n",
    "project_files/p1/model.3mf": os.urandom(300 * 1024),
    "slicer_uploads/task.gcode": "G28\n",
    "backups/parts_20260901.db": "old copy",
    "logs/farm.log": "log line\n",
    "logs/farm.log.1": "older log\n",
}
KEEP_FILES = {
    "config.json": '{"data_dir": ""}',
    "modules_staging/leftover/x.py": "x",
    "thumb_cache/a.png": "png",
    "bambu_hms_texts.json": "{}",
    "restart-state.json": "{}",
    "restart-helper.log": "helper",
    "data-move-report.json": "{}",
    "x.config.tmp": "обрывок записи",
}
UNKNOWN_FILES = {"notes.txt": "мои заметки", "my_folder/readme.md": "readme"}
DBS = ("farm_parts.db", "farm_printers.db", "farm_inventory.db", "farm_cost.db", "farm_quality.db",
       "farm_messengers.db", "farm_cost_before_order_module_20260912_101010.db")


def make_src(name):
    root = fresh(name)
    for rel, data in list(MOVE_FILES.items()) + list(KEEP_FILES.items()) + list(UNKNOWN_FILES.items()):
        put(root, rel, data)
    os.makedirs(os.path.join(root, "temp_files"))
    make_wal_db(os.path.join(root, "farm_parts.db"), "деталь-из-wal")
    for n in DBS[1:]:
        make_db(os.path.join(root, n), n)
    return root


class Ops(D.FileOps):
    """Файловые операции переноса с подставными сбоями."""

    def __init__(self, fail_copy=None, corrupt=None, fail_remove=None, free=None):
        self.fail_copy, self.corrupt, self.fail_remove, self.free = fail_copy, corrupt, fail_remove, free

    def copy_verified(self, src, dst):
        if self.fail_copy and src.replace("\\", "/").endswith(self.fail_copy):
            raise OSError("injected copy failure")
        self._cur = src
        return D.FileOps.copy_verified(self, src, dst)

    def after_write(self, tmp_path):
        if self.corrupt and self._cur.replace("\\", "/").endswith(self.corrupt):
            with open(tmp_path, "r+b") as f:
                f.seek(0)
                b = f.read(1)
                f.seek(0)
                f.write(bytes([b[0] ^ 0xFF]))

    def remove(self, path):
        if self.fail_remove and path.replace("\\", "/").endswith(self.fail_remove):
            raise PermissionError("injected: file is busy")
        return D.FileOps.remove(self, path)

    def disk_free(self, path):
        return self.free if self.free is not None else D.FileOps.disk_free(self, path)


# ════════════════════════════════════════════════════════════════════════════
section("A. общий список содержимого папки данных")

_dirs = ("modules", "modules_previous", "licenses", "cost_order_files", "project_files", "slicer_uploads",
         "temp_files", "backups", "logs")
_files = ("install_id.txt", "config-restore-journal.json", "farm_cost_order_module_backup.done")
check("A1. переносятся все папки и файлы данных: модули, прежние версии, лицензии, заказы, проекты, задачи, копии, журнал, номер установки",
      all(D.classify(n, True).action == D.MOVE for n in _dirs) and all(D.classify(n, False).action == D.MOVE for n in _files),
      [(n, D.classify(n, True).action) for n in _dirs])
_dbn = ("farm_parts.db", "farm_parts.db-wal", "farm_parts.db-shm", "farm_parts.db-journal", "farm_quality.db",
        "farm_future_module.db", "farm_cost_before_order_module_20260912_101010.db")
check("A2. базы — маской farm_*.db с -wal/-shm/-journal: и нынешние, и будущих модулей",
      all(D.classify(n, False).action == D.MOVE and D.classify(n, False).kind == D.KIND_DB for n in _dbn)
      and D.database_of("farm_parts.db-wal") == "farm_parts.db")
_keep = ("config.json", "bambu_hms_texts.json", "restart-state.json", "restart-helper.log", D.REPORT_NAME, ".w_test",
         "x.tmp", "a.db.part")
check("A3. не переносятся: config.json, временная папка установки модулей, кэши, журналы перезапуска, отчёт, временные файлы",
      all(D.classify(n, False).action == D.KEEP for n in _keep)
      and all(D.classify(n, True).action == D.KEEP for n in ("modules_staging", "thumb_cache")))
check("A4. чужое — «неизвестно» (не трогается): свой файл, файл с именем папки из списка, папка с именем базы",
      D.classify("notes.txt", False).action == D.UNKNOWN and D.classify("modules", False).action == D.UNKNOWN
      and D.classify("farm_x.db", True).action == D.UNKNOWN and D.classify("my_folder", True).action == D.UNKNOWN)

#  Имена, которые ядро и модули действительно открывают в папке данных. Новое имя без решения
#  «переносить или нет» делает набор красным — так список не отстанет от кода.
SRV = rd("server.py")
_used = set(re.findall(r'os\.path\.join\(DATA_DIR,\s*"([^"]+)"', SRV))
_used |= set(re.findall(r'_resolve_db\("([^"]+)"\)', SRV))
for _mod in sorted(os.listdir(os.path.join(REPO, "modules"))):
    _bp = os.path.join(REPO, "modules", _mod, "backend.py")
    if os.path.isfile(_bp):
        _ms = rd("modules", _mod, "backend.py")
        _used |= set(re.findall(r'resolve_db\("([^"]+)"\)', _ms))
        _used |= set(re.findall(r'os\.path\.join\(DATA_DIR,\s*"([^"]+)"', _ms))
        _used |= set(re.findall(r'os\.path\.dirname\(path\),\s*"([^"%]+)"', _ms))
        _used |= {s % "20260101_000000" for s in re.findall(r'"(farm_[a-z_]+_%s\.db)"', _ms)}
        _m = re.search(r"_TASK_FILE_DIRS\s*=\s*\(([^)]*)\)", _ms)
        if _m:
            _used |= set(re.findall(r'"([^"]+)"', _m.group(1)))
_lic = rd("app", "licensing", "store.py")
_used |= set(re.findall(r'(?:LICENSE_DIR_NAME|INSTALL_ID_FILE)\s*=\s*"([^"]+)"', _lic))
_used |= set(re.findall(r'CACHE_NAME\s*=\s*"([^"]+)"', rd("app", "bambu_hms_texts.py")))
_used |= set(re.findall(r'HELPER_LOG_NAME\s*=\s*"([^"]+)"', rd("app", "restart_cli.py")))
_used = {u.split("/")[0] for u in _used}
_undecided = sorted(u for u in _used if D.classify(u, True).action == D.UNKNOWN and D.classify(u, False).action == D.UNKNOWN)
check("A5. у КАЖДОГО имени, которое ядро и модули открывают в папке данных (%d шт.), есть решение в списке" % len(_used),
      len(_used) >= 18 and not _undecided, {"без решения": _undecided, "найдено": sorted(_used)})
check("A6. сторож не выродился: среди найденных имён — базы модулей, файлы заказов, лицензии, номер установки",
      {"farm_cost.db", "farm_quality.db", "farm_messengers.db", "cost_order_files", "licenses", "install_id.txt",
       "logs", "backups", "config-restore-journal.json", "restart-state.json"} <= _used, sorted(_used))

_names = ["farm_parts.db", "farm_printers.db", "farm_inventory.db", "farm_cost.db", "farm_quality.db",
          "farm_messengers.db", "farm_cost_before_order_module_20260912_101010.db", "farm_parts.db-wal", "notes.db",
          "farm_x.db.bak"]
check("A7. ежедневная копия: все базы ядра и модулей, кроме разового снимка «до Расчёта заказа»",
      D.daily_backup_databases(_names) == [("cost", "farm_cost.db"), ("inventory", "farm_inventory.db"),
                                           ("messengers", "farm_messengers.db"), ("parts", "farm_parts.db"),
                                           ("printers", "farm_printers.db"), ("quality", "farm_quality.db")],
      D.daily_backup_databases(_names))
_rx = D.backup_file_rx("cost")
check("A8. копии одной базы опознаются строго: «cost_ДАТА.db», но не копии базы cost_extra и не недописанная .part",
      bool(_rx.match("cost_20260929.db")) and not _rx.match("cost_extra_20260929.db")
      and not _rx.match("cost_20260929.db.part") and D.backup_file_name("parts", "20260929") == "parts_20260929.db")
_pa = os.path.join(TMP, "Data")
check("A9. одна и та же папка при другом регистре и с «..» — та же; «Data2» не внутри «Data»",
      D.same_path(_pa, _pa.upper() if os.name == "nt" else _pa) and D.same_path(_pa, os.path.join(_pa, "x", ".."))
      and D.is_inside(os.path.join(_pa, "sub"), _pa) and not D.is_inside(_pa + "2", _pa)
      and not D.same_path("", _pa) and not D.is_inside("", _pa))
check("A10. папка назначения внутри служебной папки программы опознаётся (modules, thumb_cache), простая подпапка — нет",
      D.inside_own_item(os.path.join(_pa, "modules", "x"), _pa) == "modules"
      and D.inside_own_item(os.path.join(_pa, "thumb_cache"), _pa) == "thumb_cache"
      and D.inside_own_item(os.path.join(_pa, "new_home"), _pa) == "" and D.inside_own_item(_pa, _pa) == ""
      and D.inside_own_item(_pa + "2", _pa) == "")

# ════════════════════════════════════════════════════════════════════════════
section("B. перенос на временных папках")

S1 = make_src("s1")
BEFORE = tree(S1)
T1 = os.path.join(TMP, "t1")
_mt = os.path.getmtime(os.path.join(S1, "slicer_uploads", "task.gcode"))
R1 = D.move_data_dir(S1, T1)
_moved_rel = set(MOVE_FILES) | {n + s for n in DBS for s in ("", "-wal", "-shm") if n + s in BEFORE}
_after_t = tree(T1)
check("B1. перенос выполнен: всё из списка лежит в новой папке побайтно как было",
      R1["status"] == "ok" and R1["switched"] is True
      and all(_after_t.get(rel) == BEFORE[rel] for rel in _moved_rel), (R1["reason"], sorted(set(_moved_rel) - set(_after_t))))
check("B2. база перенесена вместе с -wal: запись, которая была только в журнале, видна на новом месте",
      "farm_parts.db-wal" in BEFORE and db_rows(os.path.join(T1, "farm_parts.db")) == ["деталь-из-wal"])
_after_s = tree(S1)
check("B3. в прежней папке остались только непереносимое и чужое — нетронутым; переносимого там нет",
      set(_after_s) == set(KEEP_FILES) | set(UNKNOWN_FILES)
      and all(_after_s[r] == BEFORE[r] for r in _after_s), sorted(_after_s))
check("B4. чужое и временное в новую папку не попало",
      not any(r in _after_t for r in list(KEEP_FILES) + list(UNKNOWN_FILES)))
check("B5. пустые папки переносимого убраны, пустая «temp_files» доехала, прежняя папка данных цела",
      not os.path.exists(os.path.join(S1, "modules")) and not os.path.exists(os.path.join(S1, "temp_files"))
      and os.path.isdir(os.path.join(T1, "temp_files")) and os.path.isdir(S1))
check("B6. время изменения файла сохранено (задачи сортируются по нему)",
      abs(os.path.getmtime(os.path.join(T1, "slicer_uploads", "task.gcode")) - _mt) < 2.0)
check("B7. отчёт: переносимое, оставленное и чужое перечислены; число файлов сходится",
      R1["files_copied"] == len(_moved_rel) and R1["files_identical"] == 0
      and sorted(e["name"] for e in R1["unknown"]) == ["my_folder", "notes.txt"]
      and {"config.json", "thumb_cache", "modules_staging", "restart-state.json"} <= {e["name"] for e in R1["kept"]}
      and {"farm_parts.db", "modules", "licenses", "cost_order_files", "install_id.txt"} <= {e["name"] for e in R1["moved"]}
      and R1["left_count"] == 0, {k: R1[k] for k in ("files_copied", "unknown", "left", "moved_count")})

#  Одноимённая ДРУГАЯ база в новой папке: раньше она молча побеждала (устаревшие данные вместо рабочих).
S2 = make_src("s2")
B2 = tree(S2)
T2 = fresh("t2")
put(T2, "farm_parts.db", b"stale database from another farm")
_stale = sha(os.path.join(T2, "farm_parts.db"))
R2 = D.move_data_dir(S2, T2)
check("B8. КРИТИЧНО: другая база с тем же именем в новой папке — перенос отменён, её файл не перезаписан",
      R2["switched"] is False and R2["reason"] == D.R_CONFLICT and R2["reason_item"] == "farm_parts.db"
      and sha(os.path.join(T2, "farm_parts.db")) == _stale, R2["reason"])
check("B9. КРИТИЧНО: после отмены оригиналы целы до байта, а копии, сделанные до конфликта, убраны",
      tree(S2) == B2 and set(tree(T2)) == {"farm_parts.db"}, sorted(tree(T2)))

S3 = make_src("s3")
T3 = fresh("t3")
put(T3, "install_id.txt", MOVE_FILES["install_id.txt"])
put(T3, "modules/cost/module.json", MOVE_FILES["modules/cost/module.json"])
R3 = D.move_data_dir(S3, T3)
check("B10. такой же файл в новой папке засчитывается как перенесённый (повтор после обрыва), оригинал убран",
      R3["switched"] is True and R3["files_identical"] == 2 and not os.path.exists(os.path.join(S3, "install_id.txt"))
      and sha(os.path.join(T3, "install_id.txt")) == hashlib.sha256(MOVE_FILES["install_id.txt"].encode()).hexdigest(),
      (R3["reason"], R3["files_identical"]))

S4 = make_src("s4")
T4 = fresh("t4")
put(T4, "logs/farm.log", "журнал, который уже был в новой папке\n")
_their = sha(os.path.join(T4, "logs", "farm.log"))
R4 = D.move_data_dir(S4, T4)
check("B11. журнал с тем же именем в новой папке не останавливает перенос: его файл не тронут, наш остался в прежней папке",
      R4["switched"] is True and sha(os.path.join(T4, "logs", "farm.log")) == _their
      and os.path.isfile(os.path.join(S4, "logs", "farm.log")) and os.path.isfile(os.path.join(T4, "logs", "farm.log.1"))
      and {"name": "logs/farm.log", "reason": D.R_CONFLICT} in R4["left"], R4["left"])

S5 = make_src("s5")
B5 = tree(S5)
T5 = os.path.join(TMP, "t5")
R5 = D.move_data_dir(S5, T5, ops=Ops(fail_copy="project_files/p1/model.3mf"))
check("B12. КРИТИЧНО: файл не скопировался — перенос отменён, оригиналы целы, в новой папке ни одного файла",
      R5["switched"] is False and R5["reason"] == D.R_COPY_FAILED and R5["reason_item"] == "project_files/p1/model.3mf"
      and tree(S5) == B5 and tree(T5) == {}, (R5["reason"], R5["reason_item"], sorted(tree(T5))[:5]))

S6 = make_src("s6")
B6 = tree(S6)
T6 = os.path.join(TMP, "t6")
R6 = D.move_data_dir(S6, T6, ops=Ops(corrupt="modules/cost/backend.py"))
check("B13. КРИТИЧНО: копия не совпала с оригиналом по SHA-256 — перенос отменён, оригинал цел, испорченной копии нет",
      R6["switched"] is False and R6["reason"] == D.R_VERIFY_FAILED and R6["reason_item"] == "modules/cost/backend.py"
      and tree(S6) == B6 and tree(T6) == {}, (R6["reason"], R6["reason_item"]))

S7 = make_src("s7")
T7 = os.path.join(TMP, "t7")
R7 = D.move_data_dir(S7, T7, ops=Ops(fail_remove="s7/farm_quality.db"))
check("B14. оригинал базы не удалился (занят) — перенос состоялся, база цела на новом месте, прежняя тройка оставлена целиком",
      R7["switched"] is True and os.path.isfile(os.path.join(S7, "farm_quality.db"))
      and db_rows(os.path.join(T7, "farm_quality.db")) == ["farm_quality.db"]
      and {"name": "farm_quality.db", "reason": D.R_DELETE_FAILED} in R7["left"], R7["left"])

S8 = make_src("s8")
B8 = tree(S8)
T8 = os.path.join(TMP, "t8")
R8 = D.move_data_dir(S8, T8, ops=Ops(free=1024))
check("B15. места в новой папке не хватает — перенос не начат, оригиналы целы, в отчёте нужно и свободно",
      R8["switched"] is False and R8["reason"] == D.R_NO_SPACE and tree(S8) == B8 and tree(T8) == {}
      and R8.get("needed_bytes", 0) > 300 * 1024 and R8.get("free_bytes") == 1024, R8["reason"])

S9 = make_src("s9")
B9 = tree(S9)
R9 = D.move_data_dir(S9, os.path.join(S9, "modules", "inner"))
check("B16. новая папка внутри переносимой (modules/…) — отказ без копирования, оригиналы целы",
      R9["switched"] is False and R9["reason"] == D.R_TARGET_INSIDE_ITEM and R9["reason_item"] == "modules"
      and tree(S9) == B9, R9["reason"])

S10 = make_src("s10")
T10 = os.path.join(S10, "newdata")
R10 = D.move_data_dir(S10, T10)
check("B17. новая папка внутри прежней (не внутри элемента) — перенос выполнен, сама она не считается чужим",
      R10["switched"] is True and os.path.isfile(os.path.join(T10, "install_id.txt"))
      and "newdata" not in [e["name"] for e in R10["unknown"]], R10["unknown"])

S11 = make_src("s11")
B11 = tree(S11)
R11 = D.move_data_dir(S11, S11.upper() if os.name == "nt" else S11 + os.sep)
check("B18. КРИТИЧНО: «перенос» в ту же папку, записанную иначе, — ничего не удаляется (прежний код стирал папки)",
      R11["switched"] is True and R11["reason"] == D.R_SAME_FOLDER and tree(S11) == B11, R11["reason"])

S12 = make_src("s12")
put(S12, "modules_staging/cost.swap.json", '{"id": "cost", "restore_from": "x"}')
B12 = tree(S12)
T12 = os.path.join(TMP, "t12")
R12 = D.move_data_dir(S12, T12)
check("B19. незавершённая замена модуля — перенос откладывается (программа сначала вернёт модуль), оригиналы целы",
      R12["switched"] is False and R12["reason"] == D.R_MODULE_SWAP_PENDING and tree(S12) == B12
      and not os.path.exists(T12), R12["reason"])

S13 = make_src("s13")
T13 = fresh("t13")
put(T13, "install_id.txt" + D.TMP_SUFFIX, "остаток оборванной попытки")
os.chmod(os.path.join(S13, "licenses", "L-1.fmlic"), 0o444)     # «только чтение» у оригинала
R13 = D.move_data_dir(S13, T13)
check("B20. остаток оборванной попытки в новой папке заменён настоящей копией; оригинал «только чтение» перенесён и убран",
      R13["switched"] is True and not os.path.exists(os.path.join(T13, "install_id.txt" + D.TMP_SUFFIX))
      and open(os.path.join(T13, "install_id.txt"), encoding="utf-8").read() == MOVE_FILES["install_id.txt"]
      and not os.path.exists(os.path.join(S13, "licenses", "L-1.fmlic"))
      and os.access(os.path.join(T13, "licenses", "L-1.fmlic"), os.W_OK), (R13["reason"], R13["left"]))

check("B21. отчёт пишется и читается; итог для окна настроек: удачный показывается неделю, неудачный — пока ждёт повтора",
      D.write_report(T1, R1) and D.read_report(T1)["to"] == R1["to"]
      and D.summary(R1, False)["active"] is True and D.summary(R1, False, now=R1["ts"] + 8 * 86400)["active"] is False
      and D.summary(R2, True)["active"] is True and D.summary(R2, False)["active"] is False
      and D.summary(R2, True)["reason"] == D.R_CONFLICT and D.summary(R11, True) is None and D.summary(None, True) is None)

# ════════════════════════════════════════════════════════════════════════════
section("C. ядро: решение о папке, смена папки, ежедневная копия")

TREE = ast.parse(SRV)
FUNCS = {}
for _n in ast.walk(TREE):
    if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FUNCS.setdefault(_n.name, ast.get_source_segment(SRV, _n))


class _Log(object):
    def __init__(self):
        self.lines = []

    def _rec(self, *a, **k):
        try:
            self.lines.append(a[0] % a[1:] if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(str(a))
    info = warning = error = debug = _rec

    def log(self, level, *a):
        self._rec(*a)


class _E2E(object):
    def __init__(self, root):
        self.root = root
        self.data_dir = root


def datadir_ns(cfg, default, worker=False, e2e=None, config_path=None):
    state = {"cfg": dict(cfg), "writes": 0}

    def _read_config():
        return dict(state["cfg"])

    def _write_config(c):
        state["cfg"] = dict(c)
        state["writes"] += 1
        return True

    #  16.10.2026 (R-151): config.json по умолчанию — несуществующий файл (как «config ещё нет»).
    _cp = config_path or os.path.join(TMP, "no_such_dir", "config.json")
    ns = {"os": os, "json": json, "time": time, "_data_items": D, "log": _Log(), "_exc_brief": lambda: "err", "_E2E": e2e,
          "_IS_POOL_WORKER": worker, "_read_config": _read_config, "_write_config": _write_config,
          "_default_data_dir": lambda: default, "_DATA_MOVE_REPORT": None,
          "_DATA_DIR_UNAVAILABLE": None, "_config_path": lambda: _cp}
    for fn in ("_writable_dir", "_migrate_data_items", "_config_unreadable", "_data_dir_wait_s",
               "_enter_data_unavailable", "_data_dir"):
        if fn in FUNCS or fn in ("_writable_dir", "_migrate_data_items", "_data_dir"):
            exec(FUNCS[fn], ns)          # помощники R-151 — если они есть (на прежнем коде их нет)
    return ns, state


C_DEF = make_src("c_default")
C_B = tree(C_DEF)
C_NEW = os.path.join(TMP, "c_new")
ns, st = datadir_ns({"data_dir": C_NEW, "migrate_from": C_DEF}, C_DEF)
_dd = ns["_data_dir"]()
check("C1. удачный перенос: программа работает из новой папки, migrate_from снят, отчёт в новой и в прежней папке",
      _dd == C_NEW and "migrate_from" not in st["cfg"] and st["cfg"].get("data_dir") == C_NEW
      and (D.read_report(C_NEW) or {}).get("status") == "ok" and (D.read_report(C_DEF) or {}).get("to") == os.path.abspath(C_NEW)
      and ns["_DATA_MOVE_REPORT"]["switched"] is True and os.path.isfile(os.path.join(C_NEW, "farm_parts.db")), (_dd, st))

C_SRC2 = make_src("c_src2")
C_B2 = tree(C_SRC2)
C_BAD = fresh("c_bad")
put(C_BAD, "farm_printers.db", b"not ours")
ns2, st2 = datadir_ns({"data_dir": C_BAD, "migrate_from": C_SRC2}, os.path.join(TMP, "unused_default"))
_dd2 = ns2["_data_dir"]()
check("C2. КРИТИЧНО: перенос не удался — программа остаётся на прежней папке, migrate_from сохранён для повтора, данные целы",
      _dd2 == C_SRC2 and st2["cfg"].get("migrate_from") == C_SRC2 and st2["writes"] == 0
      and {k: v for k, v in tree(C_SRC2).items() if k != D.REPORT_NAME} == {k: v for k, v in C_B2.items() if k != D.REPORT_NAME}
      and (D.read_report(C_SRC2) or {}).get("status") == "failed", (_dd2, st2))

C_SRC3 = make_src("c_src3")
C_B3 = tree(C_SRC3)
C_W = os.path.join(TMP, "c_worker_target")
ns3, st3 = datadir_ns({"data_dir": C_W, "migrate_from": C_SRC3}, os.path.join(TMP, "unused_default"), worker=True)
_dd3 = ns3["_data_dir"]()
check("C3. КРИТИЧНО: воркер пула разбора файлов не переносит данные и не пишет config — работает из той же папки, что и главный",
      _dd3 == C_SRC3 and st3["writes"] == 0 and tree(C_SRC3) == C_B3 and not os.listdir(C_W), (_dd3, st3))

C_ROOT = fresh("c_e2e_root")
C_OUT = make_src("c_outside")
C_BO = tree(C_OUT)
ns4, st4 = datadir_ns({"data_dir": os.path.join(TMP, "c_outside_target"), "migrate_from": C_OUT}, C_ROOT,
                      e2e=_E2E(C_ROOT))
_dd4 = ns4["_data_dir"]()
check("C4. изолированный экземпляр не выходит за свою папку: чужой data_dir и migrate_from из config не действуют",
      _dd4 == C_ROOT and tree(C_OUT) == C_BO and not os.path.exists(os.path.join(TMP, "c_outside_target")), _dd4)

C_SAME = make_src("c_same")
C_BS = tree(C_SAME)
ns5, st5 = datadir_ns({"data_dir": C_SAME.upper() if os.name == "nt" else C_SAME + os.sep, "migrate_from": C_SAME},
                      os.path.join(TMP, "unused_default"))
_dd5 = ns5["_data_dir"]()
check("C5. та же папка другим регистром — не перенос: ничего не тронуто, migrate_from снят",
      D.same_path(_dd5, C_SAME) and "migrate_from" not in st5["cfg"] and tree(C_SAME) == C_BS
      and ns5["_DATA_MOVE_REPORT"] is None, (_dd5, st5))


class _Req(object):
    def __init__(self, body):
        self.body = body


def storage_ns(data_dir, default, cfg):
    state = {"cfg": dict(cfg)}

    async def _json_body(req):
        return req.body

    def _write_config(c):
        state["cfg"] = dict(c)
        return True

    ns = {"os": os, "_data_items": D, "_fs_policy": FSP, "DATA_DIR": data_dir, "_default_data_dir": lambda: default,
          "_read_config": lambda: dict(state["cfg"]), "_write_config": _write_config, "_json_body": _json_body,
          "_documents_dir": lambda: TMP, "_get_setting": lambda k, d="": d, "_archive_dir": lambda: TMP,
          #  16.10.2026 (R-151): режим «папка данных недоступна» (None — обычная работа)
          "_DATA_DIR_UNAVAILABLE": None, "log": _Log()}
    for fn in ("_writable_dir", "set_storage_data", "g_storage"):
        exec(FUNCS[fn], ns)
    return ns, state


S_CUR = make_src("st_current")
S_FULL = fresh("st_full")
put(S_FULL, "farm_parts.db", b"another farm")
nsS, stS = storage_ns(S_CUR, os.path.join(TMP, "st_default"), {"data_dir": ""})
_r1 = asyncio.run(nsS["set_storage_data"](_Req({"path": S_FULL})))
check("C6. смена папки в папку, где уже есть базы Farm Manager, отклоняется (по-русски и по-английски), config не меняется",
      _r1.get("status") == "error" and _r1.get("reason") == "data_dir_not_empty" and "Farm Manager" in _r1.get("message", "")
      and "Farm Manager" in _r1.get("message_en", "") and "migrate_from" not in stS["cfg"], _r1)
_inner = os.path.join(S_CUR, "modules", "new_place")
_r2 = asyncio.run(nsS["set_storage_data"](_Req({"path": _inner})))
check("C7. новая папка внутри служебной папки программы — отказ ДО создания папки (пустая папка в modules выглядела бы модулем)",
      _r2.get("reason") == "data_dir_inside_current" and not os.path.exists(_inner) and _r2.get("message_en"), _r2)
_empty = os.path.join(TMP, "st_empty")
_r3 = asyncio.run(nsS["set_storage_data"](_Req({"path": _empty})))
check("C8. пустая папка принимается: перенос запланирован на следующий запуск",
      _r3.get("status") == "ok" and _r3.get("changed") is True and stS["cfg"].get("migrate_from") == os.path.abspath(S_CUR)
      and stS["cfg"].get("data_dir") == _empty, (_r3, stS))
_sub = os.path.join(S_CUR, "new_home")
_r3b = asyncio.run(nsS["set_storage_data"](_Req({"path": _sub})))
check("C8b. простая подпапка нынешней папки данных (не служебная) принимается",
      _r3b.get("status") == "ok" and _r3b.get("changed") is True and stS["cfg"].get("data_dir") == _sub, _r3b)
_r4 = asyncio.run(nsS["set_storage_data"](_Req({"path": S_CUR.upper() if os.name == "nt" else S_CUR + os.sep})))
check("C9. выбрать нынешнюю папку (хоть другим регистром) — отмена переноса: migrate_from снят",
      _r4.get("status") == "ok" and _r4.get("changed") is False and "migrate_from" not in stS["cfg"], (_r4, stS))
_sd = FUNCS["set_storage_data"]
check("C10. проверка формы пути по-прежнему первая, до создания папки (как в 2.978)",
      _sd.index("check_client_path") < _sd.index("inside_own_item") < _sd.index("_writable_dir") < _sd.index("has_farm_data"))
D.write_report(S_CUR, R2)
stS["cfg"] = {"data_dir": os.path.join(TMP, "somewhere"), "migrate_from": S_CUR}
_g = nsS["g_storage"]()
check("C11. «Хранение данных» получает итог переноса: неудачный, ждёт повтора, с причиной",
      (_g.get("data_move") or {}).get("status") == "failed" and _g["data_move"]["active"] is True
      and _g["data_move"]["reason"] == D.R_CONFLICT and _g["data_dir_pending"], _g.get("data_move"))

# ════════════════════════════════════════════════════════════════════════════
section("U. 16.10.2026 (R-151): своя папка данных недоступна — ферма не раздваивается")

os.environ["FM_DATA_DIR_WAIT_S"] = "0.3"       # ожидание папки в наборе — доли секунды, а не 15 с


def farm_dbs(folder):
    try:
        return sorted(n for n in os.listdir(folder) if D.is_database_name(n))
    except OSError:
        return []


U_DEF = fresh("u_default")
U_GONE = os.path.join(TMP, "u_gone_drive", "Farm")
nsU1, stU1 = datadir_ns({"data_dir": U_GONE}, U_DEF)
_t0 = time.time()
_u1 = nsU1["_data_dir"]()
_u1_dt = time.time() - _t0
check("U1. КРИТИЧНО: своей папки нет — программа в пустой временной папке <по умолчанию>/data-unavailable; "
      "своя папка НЕ создана, config не тронут, причина «missing», ожидание ограничено",
      D.same_path(_u1, os.path.join(U_DEF, D.UNAVAILABLE_DIR)) and not os.path.exists(U_GONE)
      and not os.path.exists(os.path.dirname(U_GONE)) and stU1["writes"] == 0
      and (nsU1["_DATA_DIR_UNAVAILABLE"] or {}).get("reason") == D.FOLDER_MISSING
      and (nsU1["_DATA_DIR_UNAVAILABLE"] or {}).get("configured") == U_GONE and 0.25 <= _u1_dt < 5,
      (_u1, stU1, nsU1["_DATA_DIR_UNAVAILABLE"], _u1_dt))
check("U1b. в папке по умолчанию не заведена вторая ферма (ни одной базы farm_*.db)",
      farm_dbs(U_DEF) == [] and farm_dbs(_u1) == [], (farm_dbs(U_DEF), farm_dbs(_u1)))

U_EMPTY = fresh("u_wrong_stick")
nsU2, stU2 = datadir_ns({"data_dir": U_EMPTY}, U_DEF)
_u2 = nsU2["_data_dir"]()
check("U2. КРИТИЧНО: папка есть, но фермы в ней нет (чужая флешка, пустая точка подключения) — карантин, "
      "причина «no_farm_data», баз не появилось ни там, ни в папке по умолчанию",
      D.same_path(_u2, os.path.join(U_DEF, D.UNAVAILABLE_DIR))
      and (nsU2["_DATA_DIR_UNAVAILABLE"] or {}).get("reason") == D.FOLDER_NO_FARM
      and farm_dbs(U_EMPTY) == [] and farm_dbs(U_DEF) == [] and stU2["writes"] == 0,
      (_u2, nsU2["_DATA_DIR_UNAVAILABLE"]))

U_FARM = make_src("u_farm")
_uf_before = tree(U_FARM)
nsU3, stU3 = datadir_ns({"data_dir": U_FARM}, U_DEF)
_u3 = nsU3["_data_dir"]()
check("U3. папка с базой фермы — работа из неё, как раньше: без карантина и без записи config",
      _u3 == U_FARM and nsU3["_DATA_DIR_UNAVAILABLE"] is None and stU3["writes"] == 0
      and {k: v for k, v in tree(U_FARM).items() if k != ".w_test"} == _uf_before, (_u3, stU3))

U_NEW = fresh("u_move_target")
U_SRC_GONE = os.path.join(TMP, "u_unplugged", "OldFarm")
nsU4, stU4 = datadir_ns({"data_dir": U_NEW, "migrate_from": U_SRC_GONE}, U_DEF)
_u4 = nsU4["_data_dir"]()
check("U4. КРИТИЧНО: перенос запланирован, а источник отключён — карантин, migrate_from СОХРАНЁН "
      "(прежде снимался, и перенос терялся), новая папка не стала пустой фермой",
      D.same_path(_u4, os.path.join(U_DEF, D.UNAVAILABLE_DIR)) and stU4["writes"] == 0
      and stU4["cfg"].get("migrate_from") == U_SRC_GONE
      and (nsU4["_DATA_DIR_UNAVAILABLE"] or {}).get("reason") == "move_source_missing"
      and (nsU4["_DATA_DIR_UNAVAILABLE"] or {}).get("move_from") == U_SRC_GONE and farm_dbs(U_NEW) == [],
      (_u4, stU4, nsU4["_DATA_DIR_UNAVAILABLE"]))
nsU4b, stU4b = datadir_ns({"data_dir": "", "migrate_from": U_SRC_GONE}, U_DEF)
_u4b = nsU4b["_data_dir"]()
check("U4b. возврат в папку по умолчанию из отключённого диска — тоже карантин, migrate_from сохранён",
      D.same_path(_u4b, os.path.join(U_DEF, D.UNAVAILABLE_DIR)) and stU4b["cfg"].get("migrate_from") == U_SRC_GONE
      and stU4b["writes"] == 0, (_u4b, stU4b))

#  U5. Папка по умолчанию без своей папки — ровно как раньше (тот же путь, без ожидания и записи).
U_PLAIN = fresh("u_plain_default")
nsU5, stU5 = datadir_ns({}, U_PLAIN)
_t0 = time.time()
_u5 = nsU5["_data_dir"]()
nsU5b, stU5b = datadir_ns({"data_dir": "", "lan_access_enabled": True}, U_PLAIN)
_u5b = nsU5b["_data_dir"]()
check("U5. ПАПКА ПО УМОЛЧАНИЮ ведёт себя как раньше: первый запуск (config нет, фермы нет) и обычный "
      "запуск — та же папка, без карантина, без ожидания, без записи config",
      _u5 == U_PLAIN and _u5b == U_PLAIN and nsU5["_DATA_DIR_UNAVAILABLE"] is None
      and nsU5b["_DATA_DIR_UNAVAILABLE"] is None and stU5["writes"] == 0 and stU5b["writes"] == 0
      and time.time() - _t0 < 1.0 and not os.path.exists(os.path.join(U_PLAIN, D.UNAVAILABLE_DIR)), (_u5, _u5b))

os.environ["FM_EFFECTIVE_DATA_DIR"] = U_FARM
try:
    nsU6, stU6 = datadir_ns({"data_dir": U_GONE}, U_DEF, worker=True)
    _t0 = time.time()
    _u6 = nsU6["_data_dir"]()
    _u6_dt = time.time() - _t0
finally:
    os.environ.pop("FM_EFFECTIVE_DATA_DIR", None)
check("U6. воркер пула берёт папку главного процесса из окружения — не ждёт и ничего не создаёт",
      _u6 == U_FARM and _u6_dt < 0.2 and stU6["writes"] == 0 and nsU6["_DATA_DIR_UNAVAILABLE"] is None
      and not os.path.exists(U_GONE), (_u6, _u6_dt))

U_LATE = os.path.join(TMP, "u_late_usb")


def _plug_late():
    time.sleep(0.3)
    os.makedirs(U_LATE, exist_ok=True)
    make_db(os.path.join(U_LATE, "farm_parts.db"), "late")


os.environ["FM_DATA_DIR_WAIT_S"] = "3"
_th = threading.Thread(target=_plug_late)
_th.start()
nsU7, stU7 = datadir_ns({"data_dir": U_LATE}, U_DEF)
_t0 = time.time()
_u7 = nsU7["_data_dir"]()
_u7_dt = time.time() - _t0
_th.join()
os.environ["FM_DATA_DIR_WAIT_S"] = "0.3"
check("U7. флешка подключилась через 0,3 с после запуска — программа дождалась её и работает из неё",
      _u7 == U_LATE and nsU7["_DATA_DIR_UNAVAILABLE"] is None and 0.25 <= _u7_dt < 2.5, (_u7, _u7_dt))

U_CFG = os.path.join(fresh("u_cfg"), "config.json")
with open(U_CFG, "w", encoding="utf-8") as _f:
    _f.write('{"data_dir": "E:\\\\Fa')                     # обрыв записи посреди объекта
U_DEF8 = fresh("u_default8")
nsU8, stU8 = datadir_ns({}, U_DEF8, config_path=U_CFG)
_u8 = nsU8["_data_dir"]()
check("U8. config.json испорчен, а в папке по умолчанию фермы нет — карантин «config_unreadable», а не пустая ферма",
      D.same_path(_u8, os.path.join(U_DEF8, D.UNAVAILABLE_DIR))
      and (nsU8["_DATA_DIR_UNAVAILABLE"] or {}).get("reason") == "config_unreadable" and farm_dbs(U_DEF8) == [],
      (_u8, nsU8["_DATA_DIR_UNAVAILABLE"]))
make_db(os.path.join(U_DEF8, "farm_parts.db"), "default farm")
nsU8b, stU8b = datadir_ns({}, U_DEF8, config_path=U_CFG)
check("U8b. config.json испорчен, но ферма в папке по умолчанию есть — работа из неё, как раньше",
      nsU8b["_data_dir"]() == U_DEF8 and nsU8b["_DATA_DIR_UNAVAILABLE"] is None)

#  Окно «Хранение данных» и выбор папки в режиме недоступности.
nsSU, stSU = storage_ns(os.path.join(U_DEF, D.UNAVAILABLE_DIR), U_DEF, {"data_dir": U_GONE})
nsSU["_DATA_DIR_UNAVAILABLE"] = {"configured": U_GONE, "reason": D.FOLDER_MISSING, "since": 1, "returned": False, "move_from": ""}
_gu = nsSU["g_storage"]()
check("U9. «Хранение данных» в режиме недоступности: data_dir_unavailable с причиной и путём, "
      "и НЕ «после перезапуска: <папка>» (прежде окно перезапуска врало «переносится папка данных»)",
      (_gu.get("data_dir_unavailable") or {}).get("reason") == D.FOLDER_MISSING
      and (_gu.get("data_dir_unavailable") or {}).get("configured") == U_GONE
      and _gu.get("data_dir_pending") == "" and _gu.get("data_move") is None, _gu)
_ru1 = asyncio.run(nsSU["set_storage_data"](_Req({"path": U_EMPTY, "adopt": True})))
_ru2 = asyncio.run(nsSU["set_storage_data"](_Req({"path": U_EMPTY})))
check("U10. «Папка теперь в другом месте» принимает только папку с данными фермы; пустая папка и обычная "
      "смена папки отклоняются, config не меняется",
      _ru1.get("reason") == "data_dir_unavailable_choose_farm" and _ru2.get("reason") == "data_dir_unavailable_choose_farm"
      and stSU["cfg"] == {"data_dir": U_GONE} and _ru1.get("message_en"), (_ru1, _ru2, stSU))
#  16.10.2026 (ревизия R-151): причина отказа — по настоящему состоянию папки. Правильная папка на
#  медленном или закрытом для записи сетевом диске не называется «папкой без данных фермы».
_real_fs = D.folder_state
_ru10b = {}
try:
    for _st10 in (D.FOLDER_NOT_WRITABLE, D.FOLDER_UNREACHABLE, D.FOLDER_NO_FARM):
        D.folder_state = (lambda p, probe_timeout_s=5.0, _s=_st10: _s)
        _ru10b[_st10] = asyncio.run(nsSU["set_storage_data"](_Req({"path": U_FARM, "adopt": True})))
finally:
    D.folder_state = _real_fs
_nw, _un, _nf = _ru10b[D.FOLDER_NOT_WRITABLE], _ru10b[D.FOLDER_UNREACHABLE], _ru10b[D.FOLDER_NO_FARM]
check("U10b. «Папка теперь в другом месте»: закрытая для записи и не ответившая папка названы своими словами "
      "(права доступа; диск не ответил), а не «нет данных фермы»; config не меняется",
      all(r.get("reason") == "data_dir_unavailable_choose_farm" for r in (_nw, _un, _nf))
      and _nw.get("state") == D.FOLDER_NOT_WRITABLE and "записывать" in _nw.get("message", "")
      and "not writable" in _nw.get("message_en", "") and "farm_parts.db" not in _nw.get("message", "")
      and _un.get("state") == D.FOLDER_UNREACHABLE and "не ответил" in _un.get("message", "")
      and "did not answer" in _un.get("message_en", "") and "farm_parts.db" not in _un.get("message", "")
      and "farm_parts.db" in _nf.get("message", "") and stSU["cfg"] == {"data_dir": U_GONE}, (_ru10b, stSU))
_ru3 = asyncio.run(nsSU["set_storage_data"](_Req({"path": U_FARM, "adopt": True})))
check("U11. папка с этой фермой принимается как есть, БЕЗ переноса (migrate_from не ставится)",
      _ru3.get("status") == "ok" and _ru3.get("adopted") is True and stSU["cfg"].get("data_dir") == U_FARM
      and "migrate_from" not in stSU["cfg"], (_ru3, stSU))
stSU["cfg"] = {"data_dir": U_NEW, "migrate_from": U_SRC_GONE, "port": 8123}
_ru4 = asyncio.run(nsSU["set_storage_data"](_Req({"path": "", "abandon": True})))
check("U12. «Начать новую пустую ферму в папке по умолчанию»: своя папка и перенос сняты, остальные "
      "настройки целы, данные на недоступном диске не тронуты",
      _ru4.get("status") == "ok" and _ru4.get("abandoned") is True
      and stSU["cfg"] == {"data_dir": "", "port": 8123}, (_ru4, stSU))
_cfg_before13 = dict(stS["cfg"])
_ru13 = asyncio.run(nsS["set_storage_data"](_Req({"path": U_FARM, "adopt": True})))
check("U13. в обычном режиме adopt ничего не обходит: папка с данными Farm Manager отклоняется, как в C6",
      _ru13.get("reason") == "data_dir_not_empty" and stS["cfg"] == _cfg_before13, _ru13)
check("U14. общий список папки данных: временная папка остаётся на месте, файлы модулей переезжают",
      D.classify(D.UNAVAILABLE_DIR, True).action == D.KEEP and D.classify("module_data", True).action == D.MOVE)
U_SLOW = fresh("u_slow_probe")
_slow_state = []


def _slow_probe(p):
    time.sleep(1.0)
    return D.FOLDER_OK


_orig_probe = D._probe_folder
D._probe_folder = _slow_probe
try:
    _t0 = time.time()
    _st_slow = D.folder_state(U_SLOW, probe_timeout_s=0.2)
    _slow_dt = time.time() - _t0
finally:
    D._probe_folder = _orig_probe
check("U15. сетевой диск, который не отвечает, — «unreachable» за срок опроса, а не зависший запуск",
      _st_slow == D.FOLDER_UNREACHABLE and _slow_dt < 0.6, (_st_slow, _slow_dt))

#  Ежедневная копия.
B_DIR = fresh("backup_data")
for _n in DBS:
    make_db(os.path.join(B_DIR, _n), _n)
os.makedirs(os.path.join(B_DIR, "backups"))
for _i in range(35):
    put(B_DIR, "backups/cost_2025%02d%02d.db" % (1 + _i // 28, 1 + _i % 28), "old")
for _i in range(3):
    put(B_DIR, "backups/cost_extra_2025010%d.db" % (_i + 1), "чужая копия")
_today = time.strftime("%Y%m%d")
put(B_DIR, "backups/quality_%s.db.part" % _today, "обрывок")
nsB = {"os": os, "time": time, "sqlite3": sqlite3, "threading": threading, "_data_items": D, "log": _Log(),
       "_exc_brief": lambda: "err", "DATA_DIR": B_DIR, "DB_PARTS": os.path.join(B_DIR, "farm_parts.db"),
       "DB_PRINTERS": os.path.join(B_DIR, "farm_printers.db"), "DB_INVENTORY": os.path.join(B_DIR, "farm_inventory.db"),
       "_BACKUP_DBS_LOCK": threading.Lock(), "_BACKUP_DBS_KEEP": 30}
exec(FUNCS["_backup_dbs"], nsB)
nsB["_backup_dbs"]()
_bk = sorted(os.listdir(os.path.join(B_DIR, "backups")))
_todays = sorted(f for f in _bk if f.endswith("_%s.db" % _today))
check("C12. копия за день есть у КАЖДОЙ базы — ядра и модулей; разового снимка «до Расчёта заказа» в копиях нет",
      _todays == sorted("%s_%s.db" % (t, _today) for t in ("cost", "inventory", "messengers", "parts", "printers", "quality"))
      and not any("before_order_module" in f for f in _bk), _todays)
check("C13. копия — настоящая база с данными; обрывок прошлой копии (.part) убран",
      db_rows(os.path.join(B_DIR, "backups", "quality_%s.db" % _today)) == ["farm_quality.db"]
      and not os.path.exists(os.path.join(B_DIR, "backups", "quality_%s.db.part" % _today)))
check("C14. хранятся последние 30 копий базы, а копии другой базы с похожим именем (cost_extra) не тронуты",
      len([f for f in _bk if D.backup_file_rx("cost").match(f)]) == 30
      and len([f for f in _bk if f.startswith("cost_extra_")]) == 3, len(_bk))
_mt1 = {f: os.path.getmtime(os.path.join(B_DIR, "backups", f)) for f in _todays}
time.sleep(0.05)
nsB["_backup_dbs"]()
check("C15. повторный вызов в тот же день ничего не переписывает (фоновый поток каждый час — без лишней работы)",
      {f: os.path.getmtime(os.path.join(B_DIR, "backups", f)) for f in _todays} == _mt1
      and sorted(os.listdir(os.path.join(B_DIR, "backups"))) == _bk)

_calls = []


class _StopLoop(Exception):
    pass


def _fake_sleep(s):
    _calls.append(("sleep", s))
    if len([c for c in _calls if c[0] == "sleep"]) > 2:
        raise _StopLoop()


class _T(object):
    sleep = staticmethod(_fake_sleep)


nsL = {"time": _T, "log": _Log(), "_exc_brief": lambda: "err", "_BACKUP_DBS_EVERY_S": 3600,
       "_backup_dbs": lambda: _calls.append(("backup",))}
exec(FUNCS["_backup_dbs_loop"], nsL)
try:
    nsL["_backup_dbs_loop"]()
except _StopLoop:
    pass
check("C16. фоновый поток: раз в час вызывает ежедневную копию (пауза — перед вызовом, копия при запуске уже сделана)",
      _calls[:4] == [("sleep", 3600), ("backup",), ("sleep", 3600), ("backup",)]
      and re.search(r"^_BACKUP_DBS_EVERY_S = 3600\b", SRV, re.M), _calls)
_life = FUNCS.get("lifespan") or ""
check("C17. поток запускается в lifespan (не при импорте: разбор server.py не поднимает потоков)",
      'threading.Thread(target=_backup_dbs_loop, daemon=True, name="db-daily-backup").start()' in _life
      and SRV.count("target=_backup_dbs_loop") == 1)
_code = "\n".join(l for l in SRV.splitlines() if not l.lstrip().startswith("#"))
check("C18. копия при запуске осталась: после открытия баз ядра, как раньше",
      re.search(r"conn_pr = sqlite3\.connect\(DB_PRINTERS, check_same_thread=False\)\n(?:.*\n){0,2}\s*_backup_dbs\(\)", _code)
      is not None)
_mig = FUNCS["_migrate_data_items"]
_mig_calls = set()
for _n in ast.walk(ast.parse(_mig)):
    if isinstance(_n, ast.Call):
        _f = _n.func
        _mig_calls.add(_f.attr if isinstance(_f, ast.Attribute) else getattr(_f, "id", ""))
_eng_calls = set()
for _n in ast.walk(ast.parse(rd("app", "data_dir_items.py"))):
    if isinstance(_n, ast.Call):
        _f = _n.func
        _eng_calls.add(_f.attr if isinstance(_f, ast.Attribute) else getattr(_f, "id", ""))
check("C19. в переносе больше нет прежних опасных образцов: ни rmtree, ни перемещения без сверки — ни в ядре, ни в модуле переноса",
      not ({"rmtree", "move"} & _mig_calls) and "move_data_dir" in _mig_calls
      and not ({"rmtree", "move", "copytree"} & _eng_calls) and "copy_verified" in _eng_calls,
      (_mig_calls & {"rmtree", "move"}, _eng_calls & {"rmtree", "move", "copytree"}))

# ════════════════════════════════════════════════════════════════════════════
section("D. окно «Хранение данных» и подсказка")

IDX = rd("web", "index.html")
APP = rd("web", "app.js")
HINTS = rd("web", "composables", "helpHints.js")
_sec = IDX[IDX.index('id="fm-sec-storage"'):]
_sec = _sec[:_sec.index("</div></div><!--")]
check("D1. в «Хранении данных» есть строка итога переноса (ru/en), видна только когда есть что сказать",
      'v-if="storageInfo.data_move_ru"' in _sec and "storageInfo.data_move_en" in _sec
      and "fm-pnl-warn" in _sec)
check("D2. интерфейс строит текст итога по отчёту и показывает отказ смены папки на языке интерфейса",
      "const dataMoveTexts = (m) =>" in APP and "dataMoveTexts(j && j.data_move)" in APP
      and "j.message_en || j.message" in APP
      and all(k in APP for k in ("not_enough_space:", "conflict:", "verify_failed:", "module_swap_pending:")))
_hint = HINTS[HINTS.index('"set-data"'):]
_hint = _hint[:_hint.index("},\n")]
check("D3. подсказка не обещает «переносятся автоматически» и говорит, как на деле: пустая папка, сверка, ничего не удаляется при сбое",
      "переносятся автоматически" not in _hint and "сверяет" in _hint and "пустую папку" in _hint
      and "checks every copy" in _hint and "empty folder" in _hint)
check("D4. в документации пользователя описаны ежедневная копия всех баз и смена папки с отчётом",
      "data-move-report.json" in rd("docs", "user", "backup.md") and "раз\nв час" in rd("docs", "user", "backup.md"))

# ════════════════════════════════════════════════════════════════════════════
section("E. долгий перенос и помощник перезапуска (по проверке 29.09.2026)")
#  Перенос идёт при запуске, ДО порта. Помощник перезапуска ждёт ответа 120 с и затем запускал
#  ВТОРУЮ копию программы: та полминуты ждала замок и показывала ложное «закройте прежнюю копию
#  через трей», пока первая ещё переносила данные.
from app import restart_supervisor as RS   # noqa: E402
from app import restart_cli as RC          # noqa: E402


class MarkerSpy(D.FileOps):
    """Во время копирования смотрит, видит ли помощник перезапуска отметку «идёт перенос»."""

    def __init__(self, src, fail_copy=None):
        self.src, self.fail_copy, self.seen = src, fail_copy, []

    def copy_verified(self, src, dst):
        self.seen.append(D.move_in_progress(self.src))
        if self.fail_copy and src.replace("\\", "/").endswith(self.fail_copy):
            raise OSError("injected copy failure")
        return D.FileOps.copy_verified(self, src, dst)


SE1 = make_src("e_s9")
_spy = MarkerSpy(SE1)
RE1 = D.move_data_dir(SE1, os.path.join(TMP, "e_t9"), ops=_spy)
check("E1. КРИТИЧНО: пока перенос копирует файлы, в прежней папке лежит свежая отметка «идёт перенос»",
      RE1["switched"] is True and len(_spy.seen) >= 5 and all(_spy.seen), _spy.seen[:10])
check("E2. после удачного переноса отметки нет (и перенос её не увёз в новую папку)",
      not os.path.exists(os.path.join(SE1, D.MOVE_MARKER)) and not os.path.exists(os.path.join(TMP, "e_t9", D.MOVE_MARKER))
      and not D.move_in_progress(SE1) and D.classify(D.MOVE_MARKER).action == D.KEEP)
SE2 = make_src("e_s10")
_spy10 = MarkerSpy(SE2, fail_copy="licenses/L-1.fmlic")
RE2 = D.move_data_dir(SE2, os.path.join(TMP, "e_t10"), ops=_spy10)
check("E3. после неудачного переноса отметки тоже нет — помощник не ждёт зря",
      RE2["switched"] is False and any(_spy10.seen) and not os.path.exists(os.path.join(SE2, D.MOVE_MARKER)))

_mk = fresh("e_marker")
check("E4. нет отметки — перенос не идёт", not D.move_in_progress(_mk) and not D.move_in_progress(""))
with open(os.path.join(_mk, D.MOVE_MARKER), "w", encoding="utf-8") as f:
    json.dump({"updated_at": time.time() - D.MOVE_MARKER_FRESH_S - 30}, f)
check("E5. отметка оборванного процесса (старше %d с) не считается — помощник не ждёт вечно" % int(D.MOVE_MARKER_FRESH_S),
      not D.move_in_progress(_mk))
with open(os.path.join(_mk, D.MOVE_MARKER), "w", encoding="utf-8") as f:
    f.write("не json")
check("E6. испорченная отметка не считается", not D.move_in_progress(_mk))


class Clock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


_c = Clock()
_m = D._MoveMarker(_mk, "X:\\new", clock=_c)
_m.write()
_w0 = json.load(open(os.path.join(_mk, D.MOVE_MARKER), encoding="utf-8"))["updated_at"]
_c.t += 1.0
_m.beat()
_w1 = json.load(open(os.path.join(_mk, D.MOVE_MARKER), encoding="utf-8"))["updated_at"]
_c.t += D.MOVE_MARKER_BEAT_S
_m.beat()
_w2 = json.load(open(os.path.join(_mk, D.MOVE_MARKER), encoding="utf-8"))["updated_at"]
check("E7. отметка обновляется не чаще раза в %g с (перенос не тормозит на записи отметки)" % D.MOVE_MARKER_BEAT_S,
      _w0 == _w1 == 1000.0 and _w2 == 1000.0 + 1.0 + D.MOVE_MARKER_BEAT_S, (_w0, _w1, _w2))
_m.remove()

_jp = os.path.join(_mk, "restart-state.json")
with open(os.path.join(_mk, D.MOVE_MARKER), "w", encoding="utf-8") as f:
    json.dump({"updated_at": time.time()}, f)
_pr = RC._with_data_move(RC.build_probes(None), _jp)
_on = _pr.data_move_active()
os.remove(os.path.join(_mk, D.MOVE_MARKER))
check("E8. настоящий помощник перезапуска видит отметку рядом со своим журналом (там, откуда переносят)",
      _on is True and _pr.data_move_active() is False and RC._with_data_move(RC.build_probes(None), None).data_move_active() is False
      and RC.build_probes(None).data_move_active() is False)
_rcs = rd("app", "restart_cli.py")
check("E9. помощник строит пробы с путём журнала", "_with_data_move(build_probes(plan.get(\"mutex_name\")), jp)" in _rcs)


class SupWorld(object):
    """Поддельный мир помощника перезапуска: виртуальные часы, преемник переносит данные."""

    def __init__(self, move_until, ready_after_move=5.0, dies_at=None):
        self.t = 0.0
        self.move_until = move_until          # до какого момента после запуска идёт перенос
        self.ready_after_move = ready_after_move
        self.dies_at = dies_at
        self.spawns = []
        self.launched = None

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)

    def spawn(self, command, workdir):
        self.spawns.append(self.t)
        self.launched = self.t
        return {"n": len(self.spawns)}

    def alive(self, h):
        return self.dies_at is None or (self.t - self.launched) < self.dies_at

    def moving(self):
        return self.launched is not None and self.alive(None) and (self.t - self.launched) < self.move_until

    def version(self, port):
        if self.launched is None or not self.alive(None):
            return None
        return "Alpha 3.0" if (self.t - self.launched) >= self.move_until + self.ready_after_move else None

    def probes(self, with_move=True):
        return RS.Probes(pid_alive=lambda pid: False, port_in_use=lambda p: False, lock_free=lambda: True,
                         http_version=self.version, spawn=self.spawn, now=self.now, sleep=self.sleep,
                         process_alive=self.alive, data_move_active=(self.moving if with_move else None))


_sj = os.path.join(_mk, "restart-state.json")


def _sup_plan():
    _exe = put(_mk, "srv.exe", b"x")
    return RS.build_plan(True, _exe, None, [], _mk, 8000, "Alpha 3.0", 4242, "rid-e", _sj)


_w = SupWorld(move_until=900.0)
_ok, _why = RS.run_supervisor(_sup_plan(), _w.probes(), journal_path=_sj)
check("E10. КРИТИЧНО: перенос на 15 минут — помощник ждёт, ВТОРАЯ копия программы не запускается, перезапуск удался",
      _ok and _why == "" and len(_w.spawns) == 1, (_ok, _why, _w.spawns))
check("E11. журнал перезапуска отмечает, что ждали перенос данных",
      (RS.read_journal(_sj) or {}).get("data_move") is True and (RS.read_journal(_sj) or {}).get("stage") == RS.STAGE_READY)
_w = SupWorld(move_until=900.0)
_ok, _why = RS.run_supervisor(_sup_plan(), _w.probes(with_move=False), journal_path=_sj)
check("E12. сторож не выродился: без отметки тот же долгий старт даёт вторую копию (так было до правки)",
      not _ok and len(_w.spawns) == 2, (_ok, _why, _w.spawns))
_w = SupWorld(move_until=900.0, dies_at=300.0)
_ok, _why = RS.run_supervisor(_sup_plan(), _w.probes(), journal_path=_sj)
check("E13. преемник умер посреди переноса — ожидание не вечное, причина «преемник завершился»",
      not _ok and _why == RS.ERR_SUCCESSOR_EXITED and _w.t < 2 * RS.DEFAULT_TIMEOUTS["data_move"], (_why, _w.t))
_w = SupWorld(move_until=10 ** 9)
_ok, _why = RS.run_supervisor(_sup_plan(), _w.probes(), journal_path=_sj)
check("E14. перенос, который «идёт» бесконечно, ограничен пределом (%d ч), помощник не висит вечно"
      % int(RS.DEFAULT_TIMEOUTS["data_move"] / 3600),
      not _ok and _why == RS.ERR_READINESS_TIMEOUT
      and _w.t <= RS.MAX_LAUNCH_ATTEMPTS * (RS.DEFAULT_TIMEOUTS["data_move"] + 2 * RS.DEFAULT_TIMEOUTS["ready"]) + 60, (_why, _w.t))
_w = SupWorld(move_until=0.0, ready_after_move=3.0)
_ok, _why = RS.run_supervisor(_sup_plan(), _w.probes(), journal_path=_sj)
check("E15. обычный перезапуск без переноса — как раньше: один запуск, без пометки о переносе",
      _ok and len(_w.spawns) == 1 and not (RS.read_journal(_sj) or {}).get("data_move"))

_ov = IDX[IDX.index("{{ restartMessage }}"):]
_ov = _ov[:_ov.index("</teleport>")]
check("E16. окно перезапуска при смене папки говорит «переносится папка данных, не закрывайте» (ru/en)",
      "&& dataDirPending" in _ov and "Переносится папка данных" in _ov and "The data folder is being moved" in _ov)
_ovbox = IDX[:IDX.index("{{ restartMessage }}")]
_ovbox = _ovbox[_ovbox.rindex("z-index:100061"):]
check("E16b. окно перезапуска непрозрачное (раньше фон ссылался на несуществующую переменную, и текст окна "
      "«Сменить папку данных» под ним проступал сквозь надписи)",
      "background:var(--fm-surface-card)" in _ovbox and "--fm-surface-1" not in _ovbox)
_rw = APP[APP.index("const restartWaitReady = async"):]
_rw = _rw[:_rw.index("const doRestart = async")]
check("E17. интерфейс ждёт переноса дольше (30 минут вместо 90 с) и при таймауте не велит закрывать программу",
      "restartWaitLong.value = !!dataDirPending.value;" in APP and "if (i >= waitLimit) break;" in _rw
      and "const waitLimit = restartWaitLong.value ? 1800 : 90;" in _rw
      and "restartPhase.value === 'timeout' && dataDirPending.value" in APP
      and "Не закрывайте её" in APP and "Do not close it" in APP)
_bk = rd("docs", "user", "backup.md")
check("E18. владельцу сказано: нужно свободное место на весь объём папки даже на том же диске; большая папка — минуты",
      "даже если новая папка\n  на том же диске" in _bk and "несколько минут" in _bk
      and "свободное место не меньше объёма папки данных" in _sec and "even on the same drive" in _hint
      and "even on the same drive" in _sec)

# ════════════════════════════════════════════════════════════════════════════
section("уборка")
shutil.rmtree(TMP, ignore_errors=True)
if os.path.isdir(TMP):
    for _b, _ds, _fs in os.walk(TMP):
        for _f in _fs:
            try:
                os.chmod(os.path.join(_b, _f), 0o666)
            except OSError:
                pass
    shutil.rmtree(TMP, ignore_errors=True)
check("Z1. временные папки теста убраны", not os.path.isdir(TMP))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
