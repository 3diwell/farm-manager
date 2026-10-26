# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.789 — граница клиентских файловых путей.
#
#  ЧАСТЬ 1 (ХАРАКТЕРИЗАЦИЯ). Как было в Alpha 2.788 (эталон b932089): три маршрута
#  файлового менеджера были GET и потому получали общее право view — при включённой
#  авторизации observer мог перечислить любую папку и прочитать превью любого файла,
#  доступного процессу; форма пути не проверялась вовсе (os.path.abspath без разбора),
#  а смена папки архива создавала каталог по пути клиента с правом project.
#
#  ЧАСТЬ 2+. Новое: чистая политика app/filesystem_access_policy.py (форма пути +
#  принадлежность каталогу через commonpath), применённая до обращения к диску, и
#  приведение прав четырёх маршрутов к их фактическому назначению.
#
#  ЧЕГО ЭТОТ ЭТАП НЕ ДЕЛАЕТ — и это осознанное решение владельца. Модель «разрешённых
#  корней» НЕ вводится: встроенный файловый менеджер по замыслу даёт обзор всего диска,
#  а модели привязываются по абсолютному пути без копирования. Ограничение места обзора
#  сломало бы и выбор моделей из произвольной папки, и уже привязанные файлы.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * production server.py НЕ импортируется: реальные функции извлекаются разбором AST и
#     исполняются в изоляции. Тест запускается при РАБОТАЮЩЕЙ программе.
#   * рабочие БД, DATA_DIR и config.json не открываются; всё во временной папке.
#   * реальные пользовательские файлы не читаются, не создаются и не удаляются.
#   * ни одного сокета, uvicorn, слайсера и обращения к принтерам.
#
#  Запуск:  python tools/test_filesystem_path_boundary.py   (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.append(os.path.join(REPO, "tools"))
import _history_baseline as HB   # noqa: E402

PARENT = "b932089"   # HEAD до Alpha 2.789 (handoff 2.788)

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


SENTINEL = "FILESYSTEM_ROOT_SENTINEL_2_789"

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRC_AST = ast.parse(SRC)

from app import filesystem_access_policy as P     # noqa: E402
from app import route_policy_registry as reg      # noqa: E402


def fn_src(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return None


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["server.py", "app/route_policy_registry.py"], check)
hcheck = HIST.check


def git_show(rel):
    return HIST.show(rel)


PAR_SRC = git_show("server.py")
PAR_REG = git_show("app/route_policy_registry.py")
PAR_AST = ast.parse(PAR_SRC) if PAR_SRC else None

CORE = [p for p in reg.CORE_POLICIES if p.kind is reg.RouteKind.HTTP]


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.789: граница клиентских файловых путей ===")
section("характеризация: как было в Alpha 2.788 (эталон %s)" % PARENT)

PAR_LIST = fn_src(PAR_AST, "fs_list") if PAR_AST else ""
PAR_THUMB = fn_src(PAR_AST, "fs_thumb") if PAR_AST else ""
PAR_STAGE = fn_src(PAR_AST, "fs_stage") if PAR_AST else ""
PAR_ARCH = fn_src(PAR_AST, "set_storage_archive") if PAR_AST else ""

hcheck("H0. эталон %s прочитан" % PARENT, lambda: bool(PAR_SRC) and bool(PAR_REG) and bool(PAR_LIST))
hcheck("H1. (1) существовали ровно четыре маршрута /api/fs/*",
       lambda: PAR_REG is not None
       and all(("'%s'" % p) in PAR_REG for p in
              ("/api/fs/list", "/api/fs/roots", "/api/fs/stage", "/api/fs/thumb"))
       and PAR_REG.count("'/api/fs/") == 4)
hcheck("H2. (2) обзор всего диска был НАМЕРЕННОЙ функцией, а не дефектом",
       lambda: "полный доступ к диску" in PAR_SRC and "FILE_MANAGER_ENABLED = True" in PAR_SRC)
hcheck("H3. (3) fs_list принимал абсолютный путь клиента без разбора формы",
       lambda: "os.path.abspath(path)" in PAR_LIST and "_fs_policy" not in PAR_LIST)
hcheck("H4. (4) fs_thumb читал файл по пути клиента без разбора формы",
       lambda: "os.path.abspath(path)" in PAR_THUMB and "_fs_policy" not in PAR_THUMB)
hcheck("H5. (5) fs_stage принимал список путей клиента без разбора формы",
       lambda: bool(PAR_STAGE) and "_fs_policy" not in PAR_STAGE)
hcheck("H6. (6) UNC, \\\\?\\, \\\\.\\, drive-relative, ADS и имена устройств не отсекались",
       lambda: PAR_SRC is not None and "filesystem_access_policy" not in PAR_SRC)
hcheck("H7. (7) чистой политики файловых путей не существовало",
       lambda: PAR_SRC is not None and git_show("app/filesystem_access_policy.py") is None)
hcheck("H8. (8) fs_list/fs_thumb/fs_roots имели право view (observer обходил диск)",
       lambda: PAR_REG is not None
       and '"GET /api/fs/list"' not in PAR_REG and '"GET /api/fs/thumb"' not in PAR_REG
       and "'/api/fs/list', 'fs_list', 'files', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None" in PAR_REG)
hcheck("H9. (9) смена папки архива создавала каталог по пути клиента с правом project",
       lambda: "os.makedirs(target, exist_ok=True)" in PAR_ARCH
       and "_fs_policy" not in PAR_ARCH
       and "'/api/storage/archive', 'set_storage_archive', 'core', 'browser', 'OPERATIONAL', ('FILESYSTEM', 'CONFIG'), 'NONE', 'project'" in PAR_REG)
hcheck("H10. (10) при AUTH OFF отдельной файловой границы не появлялось",
       lambda: PAR_SRC is not None and bool(PAR_LIST) and "_SECURITY_ENABLED" not in PAR_LIST)
check("H11. (11) production server.py не импортируется", "server" not in sys.modules)
check("H12. (12) рабочие БД, DATA_DIR и config не открываются", True)
check("H13. (13) реальные файлы пользователя не изменяются (только временная папка)", True)


# ════════════════════════════════════════════════════════════════════════════
section("чистая политика: форма пути (пункты 20-38)")

_psrc = open(os.path.join(REPO, "app", "filesystem_access_policy.py"), encoding="utf-8").read()
_pimports = {(n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0])
             for n in ast.walk(ast.parse(_psrc)) if isinstance(n, (ast.Import, ast.ImportFrom))}
check("P0. политика не тянет фреймворк, БД, сеть, subprocess и логирование",
      not _pimports & {"fastapi", "starlette", "sqlite3", "socket", "urllib", "requests",
                       "subprocess", "logging", "json"})
check("P1. политика не обращается к файловой системе",
      not any(x in _psrc for x in ("os.listdir", "os.scandir", "os.stat", "os.remove",
                                   "os.makedirs", "os.rename", "open(", "realpath(",
                                   "shutil.", "Path(")))


def ok(p, **kw):
    return P.check_client_path(p, **kw).allow


def why(p, **kw):
    return P.check_client_path(p, **kw).reason


check("20. обычный абсолютный путь -> разрешён",
      ok(r"C:\Users\Someone\Models\part.stl") and ok("C:/Users/Someone/Models/part.stl"))
check("21. '..' в пути допустим по форме (обзор диска не ограничен местом)",
      ok(r"C:\Models\..\Other\part.stl"))
check("22. смешанные и повторяющиеся разделители нормализуются",
      ok(r"C:\Models//sub\\part.stl")
      and P.check_client_path(r"C:\Models//sub\\part.stl").path == os.path.normpath(r"C:\Models/sub/part.stl"))
check("25. другой диск допустим по форме (менеджер перечисляет все диски)",
      ok(r"D:\Models\part.stl"))
check("26. drive-relative 'C:folder' -> отказ",
      not ok(r"C:folder\x.stl") and why(r"C:folder\x.stl") == P.REASON_DRIVE_RELATIVE)
check("27. UNC \\\\server\\share -> отказ",
      not ok(r"\\server\share\x.stl") and why(r"\\server\share\x.stl") == P.REASON_UNC
      and not ok("//server/share/x.stl"))
check("28. extended-путь \\\\?\\ -> отказ",
      not ok(r"\\?\C:\x.stl") and why(r"\\?\C:\x.stl") == P.REASON_EXTENDED)
check("29. device-путь \\\\.\\ -> отказ",
      not ok(r"\\.\PhysicalDrive0") and why(r"\\.\PhysicalDrive0") == P.REASON_DEVICE)
check("30. NUL и управляющие символы -> отказ",
      not ok("C:\\a\x00b.stl") and why("C:\\a\x00b.stl") == P.REASON_CONTROL_CHARS
      and not ok("C:\\a\x1fb.stl"))
check("31. альтернативный поток NTFS -> отказ",
      not ok(r"C:\a\file.txt:stream") and why(r"C:\a\file.txt:stream") == P.REASON_ADS)
check("32. ведущий разделитель без диска -> отказ (не абсолютный локальный путь)",
      not ok(r"\Windows\System32") and why(r"\Windows\System32") == P.REASON_NOT_ABSOLUTE)
check("33. пустой путь -> отказ", not ok("") and why("") == P.REASON_EMPTY)
check("33b. не строка -> отказ",
      not ok(None) and why(None) == P.REASON_NOT_STRING and not ok(123))
check("36. завершающая точка или пробел в компоненте -> отказ",
      not ok(r"C:\a\name.") and not ok(r"C:\a\name ")
      and why(r"C:\a\name.") == P.REASON_TRAILING_DOT_SPACE)
check("36b. зарезервированные имена устройств -> отказ",
      not ok(r"C:\a\CON") and not ok(r"C:\a\con.txt") and not ok(r"C:\a\LPT1.stl")
      and why(r"C:\a\CON") == P.REASON_RESERVED_NAME and ok(r"C:\a\CONTOUR.stl"))
check("36c. слишком длинное значение отклоняется ДО разбора",
      not ok("C:\\" + "a" * (P.MAX_PATH_LEN + 10))
      and why("C:\\" + "a" * (P.MAX_PATH_LEN + 10)) == P.REASON_TOO_LONG)
check("37. относительный путь не принимается там, где требуется абсолютный",
      not ok(r"Models\part.stl") and ok(r"Models\part.stl", require_absolute=False))
check("38. решение детерминировано и не мутирует вход",
      P.check_client_path(r"C:\a\b.stl") == P.check_client_path(r"C:\a\b.stl"))
check("38b. код причины не содержит самого пути",
      all(SENTINEL not in why(p) for p in (r"\\server\%s" % SENTINEL, "C:\\%s\x00" % SENTINEL,
                                           r"C:\a\%s:ads" % SENTINEL)))


# ════════════════════════════════════════════════════════════════════════════
section("принадлежность каталогу: commonpath, а не префикс (пункты 34-35)")

check("34. атака соседом с общим префиксом -> не принадлежит",
      not P.is_within(r"C:\Data\Farm", r"C:\Data\Farm-evil\x.db")
      and r"C:\Data\Farm-evil\x.db".startswith(r"C:\Data\Farm"))
check("34b. настоящий вложенный путь -> принадлежит",
      P.is_within(r"C:\Data\Farm", r"C:\Data\Farm\sub\x.db"))
check("34c. сам каталог принадлежит себе", P.is_within(r"C:\Data\Farm", r"C:\Data\Farm"))
check("35. регистр Windows не даёт обхода",
      P.is_within(r"C:\Data\Farm", r"c:\data\FARM\x.db"))
check("35b. другой диск -> не принадлежит",
      not P.is_within(r"C:\Data\Farm", r"D:\Data\Farm\x.db"))
check("35c. родитель не принадлежит потомку",
      not P.is_within(r"C:\Data\Farm\sub", r"C:\Data\Farm"))
check("35d. пустые и не-строковые аргументы -> не принадлежит",
      not P.is_within("", r"C:\x") and not P.is_within(r"C:\x", "")
      and not P.is_within(None, r"C:\x"))
check("35e. check_within отдаёт безопасный код причины",
      P.check_within(r"C:\Data\Farm", r"C:\Other\x").reason == P.REASON_OUTSIDE_BASE)


# ════════════════════════════════════════════════════════════════════════════
# ИЗОЛИРОВАННОЕ ИСПОЛНЕНИЕ РЕАЛЬНЫХ ОБРАБОТЧИКОВ
# ════════════════════════════════════════════════════════════════════════════
section("порядок побочных эффектов при отказе (пункты 72-82)")

TMP = tempfile.mkdtemp(prefix="fm_fsb_789_")
SPY = {}


def spy_reset():
    SPY.clear()
    SPY.update({"scandir": 0, "listdir": 0, "stat": 0, "isfile": 0, "isdir": 0,
                "open": 0, "makedirs": 0, "rename": 0, "remove": 0, "migrate": 0,
                "subprocess": 0, "db": 0, "log": []})


class _OsPathSpy(object):
    """Прокси os.path: считает обращения, поведение настоящее."""
    def __getattr__(self, name):
        real = getattr(os.path, name)
        if name in ("isfile", "isdir"):
            def wrapped(*a, **k):
                SPY[name] += 1
                return real(*a, **k)
            return wrapped
        return real


class _OsSpy(object):
    """Прокси os: считает файловые обращения, поведение настоящее."""
    path = _OsPathSpy()
    sep = os.sep

    def __getattr__(self, name):
        real = getattr(os, name)
        if name in ("scandir", "listdir", "stat", "makedirs", "rename", "remove", "unlink"):
            key = "remove" if name == "unlink" else name
            def wrapped(*a, **k):
                SPY[key] += 1
                return real(*a, **k)
            return wrapped
        return real


class _Log:
    def _r(self, *a, **k):
        try:
            SPY["log"].append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            SPY["log"].append(" ".join(str(x) for x in a))
    info = warning = error = debug = _r


class _Resp:
    def __init__(self, content=None, status_code=200, **kw):
        self.content, self.status_code = content, status_code


def _spy_open(*a, **k):
    SPY["open"] += 1
    raise AssertionError("open() вызван при отказе — граница не сработала")


NS = {
    "_fs_policy": P, "os": _OsSpy(), "log": _Log(), "JSONResponse": _Resp,
    "FILE_MANAGER_ENABLED": True, "open": _spy_open,
    "_fm_entry": lambda full, nm, d: {"name": nm}, "_fm_crumbs": lambda p: [],
    "_exc_brief": lambda: "e",
    "FileResponse": _Resp, "Response": _Resp,
    "_extract_local_png": lambda *a: None, "_render_mesh_png": lambda *a: None,
    "THUMB_CACHE_DIR": TMP, "_RENDER_VER": "1", "hashlib": __import__("hashlib"),
    # Настоящий _stage_local_paths при пустом списке выходит ДО обращения к БД —
    # заглушка обязана вести себя так же, иначе проверка «БД не тронута» была бы ложной.
    "_stage_local_paths": (lambda paths: list(paths) if not paths
                           else (SPY.__setitem__("db", SPY["db"] + 1), list(paths))[1]),
    "base64": __import__("base64"), "json": __import__("json"),
    "_documents_dir": lambda: os.path.join(TMP, "Documents"),
    "_archive_dir": lambda: os.path.join(TMP, "Archive"),
    "_migrate_dir": lambda a, b: SPY.__setitem__("migrate", SPY["migrate"] + 1),
    "_set_setting": lambda k, v: SPY.__setitem__("db", SPY["db"] + 1),
    "_json_body": None, "Request": object, "Dict": dict, "Any": object,
    "app": type("A", (), {"get": lambda *a, **k: (lambda f: f),
                          "post": lambda *a, **k: (lambda f: f)})(),
}
for _n in ("fs_list", "fs_thumb", "fs_stage", "part_pick_path", "import_path",
           "set_storage_archive"):
    exec(compile(fn_src(SRC_AST, _n), "<server>", "exec"), NS)


async def _fake_json_body(req):
    return req._data


NS["_json_body"] = _fake_json_body


class Req:
    def __init__(self, data):
        self._data = data
    async def json(self):
        return self._data


fs_list, fs_thumb = NS["fs_list"], NS["fs_thumb"]
fs_stage, pick_path = NS["fs_stage"], NS["part_pick_path"]
import_path, set_arch = NS["import_path"], NS["set_storage_archive"]

check("X1. реальные обработчики исполнены изолированно",
      all(callable(f) for f in (fs_list, fs_thumb, fs_stage, pick_path, import_path, set_arch)))

BAD = [
    (r"\\server\share\%s.stl" % SENTINEL, "UNC"),
    (r"\\?\C:\%s.stl" % SENTINEL, "extended"),
    (r"\\.\PhysicalDrive0", "device"),
    ("C:\\a\\%s\x00.stl" % SENTINEL, "NUL"),
    (r"C:\a\%s.txt:stream" % SENTINEL, "ADS"),
    (r"C:folder\%s.stl" % SENTINEL, "drive-relative"),
    (r"C:\a\CON", "устройство"),
]

_all_deny = True
for bad, label in BAD:
    spy_reset()
    r = fs_list(bad)
    touched = SPY["scandir"] + SPY["listdir"] + SPY["isdir"] + SPY["isfile"] + SPY["stat"] + SPY["open"]
    if not (isinstance(r, dict) and r.get("status") == "error" and touched == 0):
        _all_deny = False
        print("     (fs_list пропустил или тронул диск: %s)" % label)
check("72. fs_list: отказ ДО scandir/listdir/stat для всех %d форм" % len(BAD), _all_deny)

_all_deny = True
for bad, label in BAD:
    spy_reset()
    r = fs_thumb(bad)
    touched = SPY["isfile"] + SPY["stat"] + SPY["open"] + SPY["scandir"]
    if not (getattr(r, "status_code", None) == 400 and touched == 0):
        _all_deny = False
        print("     (fs_thumb пропустил или тронул диск: %s)" % label)
check("73. fs_thumb: отказ ДО открытия и чтения файла", _all_deny)

spy_reset()
r = asyncio.run(fs_stage(Req({"paths": [b for b, _l in BAD]})))
check("74+80. fs_stage: ни один путь не дошёл до записи в БД",
      r.get("added") == [] and SPY["db"] == 0)

spy_reset()
r = asyncio.run(pick_path(Req({"path": BAD[0][0]})))
check("73b. part_pick_path: отказ ДО обращения к диску",
      r.get("status") == "error" and SPY["isfile"] == 0 and SPY["open"] == 0)

spy_reset()
r = import_path({"path": BAD[0][0]})
check("73c. import_path: отказ ДО чтения файла",
      r.get("status") == "error" and SPY["isfile"] == 0 and SPY["open"] == 0)

spy_reset()
r = asyncio.run(set_arch(Req({"path": BAD[0][0]})))
check("75+77. set_storage_archive: отказ ДО makedirs и переноса данных",
      r.get("status") == "error" and SPY["makedirs"] == 0 and SPY["migrate"] == 0
      and SPY["open"] == 0)

check("78-79. временные файлы и subprocess при отказе не создаются",
      SPY["open"] == 0 and SPY["subprocess"] == 0)
check("81. путь клиента не отражается в ответе",
      all(SENTINEL not in str(x) for x in
          (fs_list(BAD[0][0]), import_path({"path": BAD[0][0]}),
           asyncio.run(set_arch(Req({"path": BAD[0][0]}))))))
check("82a. метка отсутствует в журнале", not any(SENTINEL in ln for ln in SPY["log"]))
check("82b. метка отсутствует в исходниках приложения",
      SENTINEL not in SRC and SENTINEL not in _psrc
      and SENTINEL not in open(os.path.join(REPO, "app", "route_policy_registry.py"),
                               encoding="utf-8").read()
      and SENTINEL not in open(os.path.join(REPO, "web", "app.js"),
                               encoding="utf-8", errors="surrogateescape").read())

# ── обычный рабочий путь по-прежнему работает ────────────────────────────────
WORK = os.path.join(TMP, "Models")
os.makedirs(WORK, exist_ok=True)
with open(os.path.join(WORK, "part.stl"), "w") as _f:
    _f.write("solid\n")
NS["open"] = open        # для успешного пути настоящий open нужен
spy_reset()
r = fs_list(WORK)
check("84. обычная папка по-прежнему перечисляется (обзор диска сохранён)",
      isinstance(r, dict) and r.get("status") == "ok" and SPY["scandir"] >= 1)
spy_reset()
r = fs_list(os.path.join(TMP, "Models", "..", "Models"))
check("84b. путь с '..' внутри обычной папки работает как прежде",
      isinstance(r, dict) and r.get("status") == "ok")
spy_reset()
r = asyncio.run(fs_stage(Req({"paths": [os.path.join(WORK, "part.stl")]})))
check("85. обычный файл по-прежнему добавляется в задачи", SPY["db"] == 1)


# ════════════════════════════════════════════════════════════════════════════
section("карта прав: объявленные изменения и неизменность остальных")


def cap(method, path):
    p = reg.core_http_policy(method, path)
    return p.required_capability if p else "<нет>"


check("64-65. observer больше не обходит диск: перечисление требует project",
      cap("GET", "/api/fs/list") == "project" and cap("GET", "/api/fs/thumb") == "project"
      and cap("GET", "/api/fs/roots") == "project")
check("64b. раскрытие абсолютного пути архива тоже требует project",
      cap("GET", "/api/archive-path") == "project")
check("69. создание каталога по пути клиента требует admin",
      cap("POST", "/api/storage/archive") == "admin")
check("67. operator сохраняет работу с файлами проектов и задач",
      cap("POST", "/api/fs/stage") == "project"
      and cap("POST", "/api/part/pick-path") == "project"
      and cap("POST", "/api/import-path") == "project")
check("68. установка модуля из файла остаётся системной",
      reg.core_http_policy("POST", "/api/modules/install-path").enforced_access.value
      == "SYSTEM_ADMIN")

# Полное распределение прав ядра: этого утверждения в наборе НЕ БЫЛО — смена права
# любого маршрута ядра прежде не краснела ни в одном тесте.
import collections   # noqa: E402
CAPS = collections.Counter(p.required_capability for p in CORE
                           if p.enforced_access.value == "CAPABILITY")
#  2.920: очередь ожидания — GET (view) и четыре POST (project).
#  2.927: пометки и настройки фермы — GET (view) и два POST (project).
#  12.09.2026: −1 POST (project) — пометки принтера удалены по слову владельца.
check("R1. распределение прав ядра: view 46, project 69, admin 11, operate 6, "
      "printer_write 6, count 1, rework 1 (2.978: смена папки данных стала административной; "
      "2.980: обнаружение принтеров — printer_write, снимок сети — admin)",
      CAPS["view"] == 46 and CAPS["project"] == 69 and CAPS["admin"] == 11   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»
      and CAPS["operate"] == 6 and CAPS["printer_write"] == 6
      and CAPS["count"] == 1 and CAPS["rework"] == 1)   # 2.831: +GET/POST printer-sort-mode; 2.833: +GET (view) +POST (project) klipper-prestart
#  16.10.2026 (R-149): файлы модулей /modules/* — только после входа, PUBLIC 27 -> 26, SESSION_ONLY 3 -> 4.
check("R2. границы доступа ожидаемые: PUBLIC 26, CALLBACK_SECRET 3, SYSTEM_ADMIN 22, "
      "HANDLER_ADMIN 6, SESSION_ONLY 4, CAPABILITY 145, LOCAL_RECOVERY 1 "
      "(2.813: GET /api/diagnostics -> SYSTEM_ADMIN; 2.823/2.825: printer-files; 2.827: +4 config-backup SYSTEM_ADMIN)",
      collections.Counter(p.enforced_access.value for p in CORE) ==
      {"PUBLIC": 26, "CALLBACK_SECRET": 3, "SYSTEM_ADMIN": 22, "HANDLER_ADMIN": 6,
       "SESSION_ONLY": 4, "CAPABILITY": 145, "LOCAL_RECOVERY": 1})   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»   # 12.09.2026 -1 маршрут пометок принтера; 2.947 +staging/sync; 2.948 -pending-printable; 2.978 storage/data project->admin; 2.979 +files/locate; 2.980 +3 net-capture (admin), +4 printer-discovery (printer_write)   # 2.831/2.833: +4 CAPABILITY
_c = reg.registry_counts()
check("104. опись не изменилась: 233/188/45/2 (2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup); 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы",
      _c["total"] == 260 and _c["core"] == 209 and _c["modules"] == 51   # 196->204 / 241->249; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
      and _c["websocket"] == 2)
check("88. callback-маршруты приёма файлов не ослаблены",
      reg.core_http_policy("POST", "/server/files/upload").enforced_access.value == "CALLBACK_SECRET"
      and reg.core_http_policy("POST", "/api/files/local").enforced_access.value == "CALLBACK_SECRET")
check("105. права модулей не изменены",
      len(reg.MODULE_POLICIES) == 51
      and sum(1 for p in reg.MODULE_POLICIES if p.required_capability == "view") == 21)
# Alpha 2.879 добавила ВТОРОЙ сокет — камеру. Смысл проверки прежний: у всех сокетов
# та же граница доступа, что и была.
check("106. политика WebSocket не изменена",
      set(p.enforced_access.value for p in reg.CORE_POLICIES
          if p.kind is reg.RouteKind.WEBSOCKET) == {"CAPABILITY"})
hcheck("107. политика LAN не изменена",
       lambda: PAR_AST is not None and fn_src(PAR_AST, "_lan_effective_decision") == fn_src(SRC_AST, "_lan_effective_decision"))


# ════════════════════════════════════════════════════════════════════════════
section("единственность реализации и неизменность соседних границ")

check("E1. проверка принадлежности каталогу существует в единственном экземпляре",
      "os.path.commonpath(" not in SRC and _psrc.count("os.path.commonpath(") == 1
      and "_fs_policy.is_within" in fn_src(SRC_AST, "_within_upload_dir"))
hcheck("E2. приём файла от слайсера не изменён",
       lambda: PAR_AST is not None and fn_src(PAR_AST, "proxy_upload") == fn_src(SRC_AST, "proxy_upload"))
# Alpha 2.801: _stage_local_paths намеренно изменён (copy-on-import выбранного файла в managed
# slicer_uploads/ вместо привязки по внешнему src_path) — это НЕ ослабление файловой границы, а
# добавление безопасной managed-копии (проверка источника + SHA-256 + atomic replace).
# Контракт проверяется отдельно в tools/test_managed_project_task_files.py, поэтому здесь функция
# из списка «неизменных» границ убрана. Прочие границы доступа остаются под этой проверкой.
# 16.10.2026: ws_ep убрана — её меняли аудит arch-auth-18 (сбой проверки источника закрывает
# сокет) и R-150 (перепроверка доступа всегда, и при выключенной защите). Поведение сокета
# закрепляет tools/test_websocket_session_lifecycle.py (пункты 11-51c).
# 16.10.2026 (R-151): add_route только ДОПОЛНЕНА — модуль, не уложившийся в срок запуска (core._revoked),
# маршруты больше не добавляет; остальные строки эталона на месте (сверку «по порядку» держат test_auth_session_hardening,
# test_lan_auth_prerequisites и test_websocket_session_lifecycle).
UNCHANGED = ("_require_slicer_callback", "_auth_gate", "_gate_decide",
             "_require_admin", "_require_system_admin", "_route_perm", "_has_perm",
             "octo_files_local", "fs_roots",
             "open_storage_folder", "_migrate_dir")
#  Без эталона список расхождений не вычисляется (None): пустой список без эталона был бы
#  ложной зеленью.
_diffs = ([f for f in UNCHANGED if fn_src(PAR_AST, f) != fn_src(SRC_AST, f)]
          if PAR_AST else None)
hcheck("E3. соседние границы и алгоритмы не изменены: расхождений %s (%s)"
       % ((len(_diffs), ", ".join(_diffs) or "нет") if _diffs is not None else ("?", "эталона нет")),
       lambda: _diffs == [])
hcheck("E4. изменены намеренно ровно шесть обработчиков",
       lambda: sorted(f for f in ("fs_list", "fs_thumb", "fs_stage", "part_pick_path", "import_path",
                         "set_storage_archive", "_within_upload_dir")
             if PAR_AST and fn_src(PAR_AST, f) != fn_src(SRC_AST, f))
       == ["_within_upload_dir", "fs_list", "fs_stage", "fs_thumb", "import_path",
          "part_pick_path", "set_storage_archive"])
hcheck("E5. алгоритм сохранения и приёма файлов не переписан",
       lambda: "_safe_upload_name" in SRC and "_within_upload_dir" in SRC
       and PAR_AST is not None and fn_src(PAR_AST, "_safe_upload_name") == fn_src(SRC_AST, "_safe_upload_name"))


shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
