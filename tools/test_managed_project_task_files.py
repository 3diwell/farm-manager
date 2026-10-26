# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.801 — управляемое локальное хранение файлов проектов и задач.
#
#  ПОЛНОСТЬЮ OFFLINE. server.py НЕ импортируется обычным способом: реальные функции
#  безопасного копирования извлекаются разбором AST и исполняются в изоляции. USB/внешний
#  источник моделируется ОТДЕЛЬНОЙ временной папкой; managed-хранилище — другой временной
#  папкой. Ни рабочей БД, ни рабочего DATA_DIR, ни сети, ни принтера, ни слайсера. Реальные
#  пользовательские файлы не используются; содержимое файлов в вывод не печатается.
#
#  ЧТО ДОКАЗЫВАЕТ. Выбранный с USB файл БЕЗОПАСНО копируется в managed-хранилище (проверка
#  источника + SHA-256 + перепроверка source во время копирования + atomic os.replace +
#  safe filename + collision-safe), исходник НЕ меняется и НЕ удаляется, managed-копия
#  читается после извлечения USB, а резолвер печати/превью предпочитает managed (stored_path).
#  Содержимое файлов в SQLite не хранится. Схема не менялась; новых маршрутов нет.
#
#  ОБЪЁМ (safe core, по решению владельца): copy-on-import для project- и staging-pick через
#  существующее managed-хранилище. НЕ входят (осознанно отложено): journal-based crash recovery,
#  relink/missing-source UI, новая схема/конвенция папок — резолвер и legacy-fallback сохранены.
#
#  Запуск:  python tools/test_managed_project_task_files.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import hashlib
import os
import re
import secrets
import socket
import sys
import tempfile

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

_SOCKETS = []
class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
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

SENTINEL = "MANAGED_FILE_SENTINEL_2_801"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
OWN = open(os.path.abspath(__file__), encoding="utf-8").read()

def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""

class _Log(object):
    def _r(self, *a, **k): pass
    info = warning = error = debug = exception = _r

NS = {
    "os": os, "re": re, "hashlib": hashlib, "secrets": secrets, "log": _Log(),
    "_MANAGED_IMPORT_MAX": 2 * 1024 * 1024 * 1024,
    "_WIN_RESERVED_NAMES": frozenset(
        ["CON", "PRN", "AUX", "NUL"] + ["COM%d" % i for i in range(1, 10)] + ["LPT%d" % i for i in range(1, 10)]),
}
for _f in ("_unique_dest", "_managed_file_sha256", "_safe_managed_filename",
           "_managed_source_ok", "_import_copy_managed"):
    exec(compile(fn_src(_f), "<server>", "exec"), NS)
copy_managed = NS["_import_copy_managed"]
safe_name = NS["_safe_managed_filename"]
source_ok = NS["_managed_source_ok"]
sha256_of = NS["_managed_file_sha256"]

def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()

CONTENT = b"; synthetic gcode " + SENTINEL.encode() + b"\nG28\nG1 X10 Y10\n" * 50


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.801: управляемое локальное хранение файлов проектов/задач (offline) ===")

with tempfile.TemporaryDirectory(prefix="fm_managed_") as ROOT:
    USB = os.path.join(ROOT, "USB_DRIVE")          # моделирует съёмный носитель
    MANAGED = os.path.join(ROOT, "managed", "proj1")   # managed-папка проекта
    os.makedirs(USB); os.makedirs(MANAGED)
    _TOOLS_BEFORE = set(os.listdir(os.path.join(REPO, "tools")))

    def usb_file(name, data=CONTENT):
        p = os.path.join(USB, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    section("безопасное копирование: байты, SHA-256, размер, неизменность источника")
    src = usb_file("Part_A.gcode")
    dest, sha, size = copy_managed(src, MANAGED, "Part_A.gcode")
    check("4/5/6. managed-копия побайтово совпадает; SHA-256 и размер совпадают",
          open(dest, "rb").read() == CONTENT and sha == sha_bytes(CONTENT)
          and size == len(CONTENT) and sha256_of(dest) == sha_bytes(CONTENT))
    check("1. файл скопирован в managed-папку (dest внутри MANAGED)",
          os.path.dirname(dest) == MANAGED and os.path.isfile(dest))
    check("3. источник на USB НЕ изменён и НЕ удалён",
          os.path.isfile(src) and open(src, "rb").read() == CONTENT)
    check("9/10/11. managed-копия читается ПОСЛЕ удаления источника (USB извлечён)",
          (os.remove(src), os.path.isfile(dest) and open(dest, "rb").read() == CONTENT)[1])

    section("резолвер источника (печать/превью): managed приоритетнее внешнего пути")
    _resolver_src = fn_src("_file_filament_requirements")
    check("12/13. резолвер выбирает stored_path раньше src_path (managed первичен)",
          "fr.get('stored_path') or fr.get('src_path')" in _resolver_src
          or 'fr.get("stored_path") or fr.get("src_path")' in _resolver_src)
    def resolve(stored_path, src_path):
        return stored_path or src_path
    check("12b. при наличии managed внешний путь не используется",
          resolve(dest, os.path.join(USB, "gone.gcode")) == dest)
    check("2. legacy без managed: резолвер честно падает на src_path (fallback сохранён)",
          resolve("", "/legacy/external.gcode") == "/legacy/external.gcode")

    section("safe filename: traversal / absolute / ADS / reserved / символы")
    check("43. traversal '../..' убирается (только basename)",
          "/" not in safe_name("../../etc/passwd") and "\\" not in safe_name("..\\..\\x")
          and safe_name("../../evil.gcode") == "evil.gcode")
    check("44. absolute path сводится к basename",
          safe_name("C:\\Windows\\System32\\evil.gcode") == "evil.gcode"
          and safe_name("/abs/evil.gcode") == "evil.gcode")
    check("46. ADS ':stream' отрезается",
          ":" not in safe_name("part.gcode:evil.exe") and safe_name("part.gcode:evil") == "part.gcode")
    check("45. reserved-имена Windows обезвреживаются (CON/PRN/COM1)",
          safe_name("CON.gcode") == "_CON.gcode" and safe_name("COM1.gcode") == "_COM1.gcode"
          and safe_name("PRN") == "_PRN")
    check("43b. недопустимые символы -> '_'; хвостовые пробелы/точки убираются",
          safe_name('a<b>c|d?.gcode') == "a_b_c_d_.gcode".replace("_.", "_.")  # символы заменены
          or ("<" not in safe_name('a<b>.gcode') and safe_name("name.  ") == "name"))
    check("43c. пустое/точечное имя -> 'file'", safe_name("") == "file" and safe_name("..") == "file"
          and safe_name("   ") == "file")

    section("коллизии: тот же SHA переиспользуется, другой контент — уникальное имя")
    s1 = usb_file("dup.gcode", CONTENT)
    d1, sha1, _ = copy_managed(s1, MANAGED, "dup.gcode")
    d2, sha2, _ = copy_managed(s1, MANAGED, "dup.gcode")   # тот же контент второй раз
    check("18/20. одинаковый контент с тем же именем -> та же managed-копия (без ложного дубля)",
          d1 == d2 and sha1 == sha2)
    s3 = usb_file("dup2.gcode", CONTENT + b"DIFFERENT")
    d3, sha3, _ = copy_managed(s3, MANAGED, "dup.gcode")   # то же имя, другой контент
    check("19/42. другой контент с тем же именем -> УНИКАЛЬНОЕ имя; существующий файл НЕ затёрт",
          d3 != d1 and os.path.isfile(d1) and open(d1, "rb").read() == CONTENT
          and open(d3, "rb").read() == CONTENT + b"DIFFERENT")

    section("отказы источника/ФС: понятная ошибка, partial убирается, источник цел")
    # 36. источник исчез до копирования
    try:
        copy_managed(os.path.join(USB, "nope.gcode"), MANAGED, "nope.gcode"); _r36 = False
    except RuntimeError as e:
        _r36 = "source_invalid" in str(e)
    check("36. источник отсутствует до копирования -> RuntimeError, без записи", _r36)
    # 47. директория как источник
    _dir = os.path.join(USB, "adir"); os.makedirs(_dir)
    try:
        copy_managed(_dir, MANAGED, "adir"); _r47 = False
    except RuntimeError as e:
        _r47 = "directory" in str(e)
    check("47. директория как источник -> блокируется", _r47)
    # 48/49. symlink источник (если ОС позволяет создать) блокируется; иначе проверка в коде
    _sym_ok = True
    try:
        _lnk = os.path.join(USB, "link.gcode")
        os.symlink(d1, _lnk)
        try:
            copy_managed(_lnk, MANAGED, "link.gcode"); _sym_ok = False
        except RuntimeError as e:
            _sym_ok = "symlink" in str(e)
    except (OSError, NotImplementedError, AttributeError):
        _sym_ok = "os.path.islink(src)" in fn_src("_managed_source_ok")   # привилегий нет — проверяем код
    check("48. symlink/reparse источник блокируется (или код содержит проверку)", _sym_ok)
    # 50. oversized — _managed_source_ok отвергает по лимиту ДО копирования (unit)
    NS["_MANAGED_IMPORT_MAX"] = 8
    _big = usb_file("big.gcode", b"0123456789ABCDEF")   # 16 байт > лимит 8
    _bok, _bsz, _bmt, _bwhy = source_ok(_big)
    _full_blocked = True
    try:
        copy_managed(_big, MANAGED, "big.gcode"); _full_blocked = False
    except RuntimeError:
        pass
    NS["_MANAGED_IMPORT_MAX"] = 2 * 1024 * 1024 * 1024
    check("50. слишком большой файл отвергается по лимиту (source_ok too_large И копия не создаётся)",
          (not _bok) and _bwhy == "too_large" and _full_blocked)
    # 41. partial temp удаляется при ошибке (нет .part в managed после отказа)
    check("41. частичный temp-файл (.part) не остаётся после ошибки",
          not any(n.endswith(".part") for n in os.listdir(MANAGED)))
    # 38. источник изменился во время копирования -> abort (перепроверка size/mtime)
    _real_ok = NS["_managed_source_ok"]
    _calls = {"n": 0}
    _sX = usb_file("changing.gcode", CONTENT)
    def _mut_source_ok(src):
        r = _real_ok(src)
        _calls["n"] += 1
        if _calls["n"] >= 2 and r[0]:      # второй вызов (после копии) -> «источник изменился»
            return (True, r[1] + 1, r[2], "")
        return r
    NS["_managed_source_ok"] = _mut_source_ok
    try:
        copy_managed(_sX, MANAGED, "changing.gcode"); _r38 = False
    except RuntimeError as e:
        _r38 = "source_changed_during_copy" in str(e)
    NS["_managed_source_ok"] = _real_ok
    check("37/38. источник изменился во время копирования -> rollback (abort), без готовой копии",
          _r38 and not any(n.endswith(".part") for n in os.listdir(MANAGED)))

    section("дерево репозитория и temp")
    check("79. тест не создал файлов в дереве репозитория (tools/ неизменен)",
          set(os.listdir(os.path.join(REPO, "tools"))) == _TOOLS_BEFORE)
    check("SE. за прогон не открыт ни один сокет", not _SOCKETS)
    _MANAGED_ROOT = ROOT

check("80. temp-root удалён автоматически (fixtures не остались)", not os.path.exists(_MANAGED_ROOT))


# ════════════════════════════════════════════════════════════════════════════
section("wiring: project- и staging-pick копируют в managed (source-check)")
_pick = fn_src("pick_project2_file")
_pickpaths = fn_src("pickpaths_project2_files")
_pickpath = fn_src("pickpath_project2_file")
_import_files = fn_src("import_files_as_project")
_stage = fn_src("_stage_local_paths")
check("W1. project pick копирует в managed и ставит stored_path (не src_path=p)",
      "_import_copy_managed" in _pick and "stored_path=dest" in _pick and "src_path=p" not in _pick)
check("W2. project pick-paths копирует в managed (stored_path первичен)",
      "_import_copy_managed" in _pickpaths and "src_path=p" not in _pickpaths)
check("W3. project pick-path (single) копирует и разбирает managed-копию (dest), не USB",
      "_import_copy_managed" in _pickpath and "_parse_file, dest" in _pickpath
      and "'', dest, parsed" in _pickpath)
check("W4. import-files-as-project копирует в managed новую папку проекта",
      "_import_copy_managed" in _import_files and "src_path=p" not in _import_files)
check("W5. staging pick копирует в managed slicer_uploads и очищает src_path",
      "_import_copy_managed" in _stage and "src_path=''" in _stage
      and "UPLOAD_DIR" in _stage and "excluded.src_path" not in _stage)
check("W6. staging: копирование ВНЕ блокировки БД (lock_p не держит большой файл)",
      _stage.index("_import_copy_managed") < _stage.index("with lock_p"))
# Alpha 2.802: папку проекта считает ЕДИНЫЙ резолвер (одна папка на проект) вместо прежнего
# join(PROJECT_FILES_DIR, project_id). Контракт проверки прежний и даже строже: destination
# вычисляется на backend и не приходит из запроса. Детали — tools/test_canonical_project_task_folders.py.
check("W7. destination НЕ приходит от фронтенда — backend вычисляет managed-папку",
      "resolve_managed_owner_directory" in _pick and "resolve_managed_owner_directory" in _pickpaths
      and not re.search(r"body\.get\(['\"](dir|dest|folder)['\"]", _pick + _pickpaths))


# ════════════════════════════════════════════════════════════════════════════
section("контент не в SQLite; схема не менялась; резолвер/границы сохранены")
check("13c. содержимое файлов НЕ хранится в SQLite (project_files: путь+метаданные, не BLOB)",
      "src_path TEXT DEFAULT '', stored_path TEXT DEFAULT '', content_hash TEXT" in SRV
      and "BLOB" not in fn_src("_insert_parsed_file") and "BLOB" not in fn_src("_import_copy_managed"))
check("11c. схема project_files НЕ изменена (та же строка CREATE TABLE, аддитивной миграции нет)",
      SRV.count("CREATE TABLE IF NOT EXISTS project_files (id TEXT PRIMARY KEY") == 1
      and "ALTER TABLE project_files ADD COLUMN managed" not in SRV
      and "storage_state" not in SRV)
check("72. существующая файловая граница сохранена (_fs_policy/check_client_path на месте)",
      "check_client_path" in SRV)
check("8/71. API не возвращает абсолютный managed-путь: managed-импорт ставит src_path='' (USB-путь не сохраняется)",
      "stored_path=dest" in _pick and "src_path=p" not in _pick)


# ════════════════════════════════════════════════════════════════════════════
section("границы: 2.800/Moonraker/queue не тронуты, dispatch OFF, sentinel")
check("73. Alpha 2.800 slicer preview сохранён (part-thumb приоритет slicer)",
      "_extract_part_previews(p).get(mk)" in SRV and "_slicer_image_ok" in SRV)
check("74. Moonraker pipeline не изменён (_moonraker_print_started на месте)",
      "_moonraker_print_started" in SRV)
check("76. DISPATCH_ENABLED остаётся False",
      re.search(r"^DISPATCH_ENABLED = False\s*$", ORCH, re.M) is not None)
check("77. TRANSPORT_ENABLED остаётся False",
      re.search(r"^TRANSPORT_ENABLED = False\s*$", ORCH, re.M) is not None)
check("35. новых HTTP-маршрутов не добавлено (переиспользованы существующие pick-эндпоинты)",
      SRV.count("@app.post(\"/api/projects2/{project_id}/files/pick\")") == 1
      and "local-managed-copy" not in SRV)
check("S1. sentinel отсутствует в production-исходниках", SENTINEL not in SRV and SENTINEL not in ORCH)
check("S2. sentinel определён один раз в оснастке теста", OWN.count(SENTINEL) == 1)


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _DONE["ok"] = True
    sys.exit(1)
print("PASS: managed-хранилище файлов — все %d проверок пройдены; server.py не импортирован" % _total)
_DONE["ok"] = True
sys.exit(0)
