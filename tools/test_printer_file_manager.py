# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.823 — экспериментальный файловый менеджер принтеров.
#
#  ПОЛНОСТЬЮ OFFLINE. Ни рабочей БД, ни DATA_DIR, ни сети, ни принтеров, ни
#  production-рантайма. Чистый слой app/printer_files/ исполняется НАПРЯМУЮ с
#  фейковыми транспортами; серверные обработчики (_pf_list_impl/_pf_delete_impl/
#  флаги/транспорт FTPS) извлекаются из server.py разбором AST и исполняются в
#  изоляции; frontend-блок извлекается из web/app.js и исполняется в Node на
#  стабах (fetch/confirm/alert управляемы); раскладка меряется в реальном движке
#  (headless Edge) с настоящим app.css. Sentinel играет роль «секрета»: он не
#  должен утечь в логи/аудит/ответы.
#
#  Запуск:  python tools/test_printer_file_manager.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import io
import json
import os
import re
import socket
import subprocess

import sys
import tempfile
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _edge_dom   # Alpha 2.834: DOM через CDP + проверка живости движка

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

# ── Ловушка: ни одного реального сокета за прогон ────────────────────────────
_SOCKETS = []
_RealSocket = socket.socket


class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
        raise AssertionError("offline-тест: сокеты запрещены")


socket.socket = _TrapSocket

FAILED = []
PASSED = [0]
SKIPPED = []


def check(name, ok, detail=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:180]) if detail else ""))


def skip(name, why):
    SKIPPED.append(name)
    print("SKIP — %s (%s)" % (name, why))


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "PRINTER_FILE_MANAGER_SENTINEL_2_823"
SECRET = SENTINEL + ":code"      # фейковый access code — не должен утечь никуда

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
INDEXHTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
APPCSS = open(os.path.join(REPO, "web", "app.css"), encoding="utf-8", errors="surrogateescape").read()
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
HEALTH = open(os.path.join(REPO, "app", "printer_health_policy.py"), encoding="utf-8").read()
OWN = open(os.path.abspath(__file__), encoding="utf-8").read()
PF_DIR = os.path.join(REPO, "app", "printer_files")
PF_SRC = {f: open(os.path.join(PF_DIR, f), encoding="utf-8").read()
          for f in ("models.py", "security.py", "base.py", "registry.py", "bambu.py", "moonraker.py", "flashforge.py")}


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


EDGE = next((p for p in [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"] if os.path.isfile(p)), None)

# Alpha 2.835: наличие бинарника не значит работоспособность, НО неработоспособность движка
# больше НЕ повод пропускать браузерные проверки — это КРАСНЫЙ тест с точной причиной. Прежний
# SKIP был слепой зоной: именно он однажды спрятал реальный дефект интерфейса.
_ENGINE_WHY = ""
if not EDGE:
    _ENGINE_WHY = "движок рендера (Edge/Chrome) не найден"
elif not _edge_dom.engine_usable(EDGE):
    _ENGINE_WHY = "движок найден (%s), но не отдаёт документ по CDP" % EDGE
    EDGE = None

from app.printer_files import models as M                      # noqa: E402
from app.printer_files import security as S                    # noqa: E402
from app.printer_files import registry as PR                   # noqa: E402
from app.printer_files.base import PrinterFileError, PrinterFileProvider   # noqa: E402
from app.printer_files.bambu import BambuFileProvider, parse_list_line     # noqa: E402
from app.printer_files.moonraker import MoonrakerFileProvider  # noqa: E402
from app.printer_files.flashforge import FlashforgeFileProvider  # noqa: E402

print("=== Alpha 2.823: файловый менеджер принтеров (offline) ===")

# ════════════════════════════════════════════════════════════════════════════
section("CAPABILITIES (1-8)")

_ftp_calls = {"made": 0, "deleted": [], "listed": []}


class _FakeFtp(object):
    """Фейковая FTPS-сессия Bambu: каталоги root/cache/model/timelapse."""
    tree = {
        "/": ["-rw-r--r--   1 r r  100 Jan 01 10:00 boot.cfg",
              "drwxr-xr-x   2 r r 4096 Jan 01 10:00 cache",
              "drwxr-xr-x   2 r r 4096 Jan 01 10:00 model",
              "drwxr-xr-x   2 r r 4096 Jan 01 10:00 timelapse"],
        "/cache": ["-rw-r--r--   1 r r  52428800 Jan 02 11:00 partA.gcode.3mf",
                   "-rw-r--r--   1 r r  1048576 Feb 03  2025 old_job.gcode",
                   "-rw-r--r--   1 r r  512 Jan 02 11:00 .hidden"],
        "/model": ["-rw-r--r--   1 r r  2048 Jan 05 09:30 shape.3mf"],
        "/timelapse": ["-rw-r--r--   1 r r  99614720 Jan 06 08:00 video_001.mp4",
                       "-rw-r--r--   1 r r  10485760 Mar 01  2025 clip_old.avi"],
    }

    def __init__(self):
        _ftp_calls["made"] += 1

    def retrlines(self, cmd, cb):
        path = cmd.split(" ", 1)[1]
        _ftp_calls["listed"].append(path)
        for line in self.tree.get(path if path != "" else "/", []):
            cb(line)

    def nlst(self, d):
        raise AssertionError("LIST должен разбираться; nlst — только fallback")

    def delete(self, path):
        _ftp_calls["deleted"].append(path)

    def quit(self):
        pass


_moon_files = {
    "gcodes": [{"path": "job1.gcode", "size": 1000, "modified": 1700000000},
               {"path": "sub/job2.3mf", "size": 2000, "modified": 1700000100},
               {"path": "active.gcode", "size": 3000, "modified": 1700000200}],
    "timelapse": [{"path": "tl_001.mp4", "size": 8000000, "modified": 1600000000}],
}
_moon_deleted = []


def _moon_get(pid, path):
    if path == "/server/files/roots":
        return {"result": [{"name": "gcodes"}, {"name": "timelapse"}, {"name": "config"}]}
    if path.startswith("/server/files/directory"):
        return {"result": {"disk_usage": {"total": 10 ** 9, "free": 4 * 10 ** 8}}}
    m = re.match(r"/server/files/list\?root=(.+)", path)
    if m:
        root = m.group(1)
        if root == "config":
            return {"result": [{"path": "printer.cfg", "size": 10, "modified": 1}]}
        return {"result": [dict(x) for x in _moon_files.get(root, [])]}
    raise PrinterFileError(M.REASON_NOT_FOUND)


def _moon_delete(pid, path):
    _moon_deleted.append(path)
    # фейковое устройство реально «удаляет»: пост-проверка листингом видит отсутствие
    m = re.match(r"/server/files/([^/]+)/(.+)$", path)
    if m:
        root, rel = m.group(1), m.group(2)
        _moon_files[root] = [x for x in _moon_files.get(root, []) if x["path"] != rel]
    return {"result": {"item": {"path": path}, "action": "delete_file"}}


def _mk_registry(ftp_factory=None, moon_get=None, moon_del=None, ff_list=None):
    return PR.ProviderRegistry({
        "bambu": BambuFileProvider(ftp_factory or (lambda pid: _FakeFtp())),
        "klipper": MoonrakerFileProvider(moon_get or _moon_get, moon_del or _moon_delete),
        "flashforge": FlashforgeFileProvider(ff_list or (lambda pid: ["a.gcode", "b.3mf"])),
    })


REG = _mk_registry()
P_BAMBU = {"id": "p_b", "type": "bambu", "model": "Bambu Lab X1 Carbon", "gen": "auto", "has_credentials": True}
P_BAMBU_H2 = {"id": "p_h", "type": "bambu", "model": "Bambu Lab H2D", "gen": "auto", "has_credentials": True}
P_BAMBU_NOCRED = {"id": "p_n", "type": "bambu", "model": "Bambu Lab X1 Carbon", "gen": "auto", "has_credentials": False}
P_KLIP = {"id": "p_k", "type": "klipper", "model": "RatRig", "gen": "", "has_credentials": True}
P_FF = {"id": "p_f", "type": "flashforge", "model": "AD5M", "gen": "auto", "has_credentials": True}
P_UNK = {"id": "p_u", "type": "prusa", "model": "MK4", "gen": "", "has_credentials": True}

c_b = REG.capabilities(P_BAMBU)
c_k = REG.capabilities(P_KLIP)
c_f = REG.capabilities(P_FF)
c_u = REG.capabilities(P_UNK)
check("1. registry выбирает Bambu-адаптер", c_b.adapter == "bambu" and c_b.supported)
check("2. registry выбирает Moonraker-адаптер", c_k.adapter == "klipper" and c_k.supported)
check("3. registry выбирает FlashForge-адаптер", c_f.adapter == "flashforge" and c_f.supported)
check("4. неизвестный adapter получает unsupported (не пустой список)",
      not c_u.supported and c_u.reason == M.REASON_UNSUPPORTED)
check("5. capabilities не придумываются: FlashForge честно без delete/размеров/папок",
      c_f.list_files and not c_f.delete_files and not c_f.read_sizes and not c_f.browse_directories)
check("6. read и delete — отдельные capabilities (list_files != delete_files)",
      c_f.list_files and not c_f.delete_files and c_b.list_files and c_b.delete_files)
check("7. storage capabilities различаются (X1=sd, H2=internal, Moonraker=internal)",
      c_b.storage_types == ("sd",) and REG.capabilities(P_BAMBU_H2).storage_types == ("internal",)
      and c_k.storage_types == ("internal",))
check("8. ограничение прошивки/конфигурации -> reason code (Bambu без кода доступа)",
      not REG.capabilities(P_BAMBU_NOCRED).supported
      and REG.capabilities(P_BAMBU_NOCRED).reason == M.REASON_NO_CREDENTIALS)

# ════════════════════════════════════════════════════════════════════════════
section("STORAGES (9-15)")

st_k = REG.provider_for(P_KLIP).list_storages(P_KLIP)
st_b = REG.provider_for(P_BAMBU).list_storages(P_BAMBU)
st_ids = [s.storage_id for s in st_k]
check("9. internal storage отображается", any(s.type == M.STORAGE_INTERNAL for s in st_k))
check("10/11. SD отображается только когда подтверждён (X1 -> sd; USB не выдумывается)",
      st_b[0].type == M.STORAGE_SD and all(s.type != M.STORAGE_USB for s in st_k + st_b))
check("12. offline/размеры storage честны (Moonraker отдаёт disk usage, Bambu — None)",
      st_k[0].total_bytes == 10 ** 9 and st_k[0].free_bytes == 4 * 10 ** 8 and st_b[0].total_bytes is None)
check("13. read-only storage не позволяет delete (config writable=False; политика адаптера)",
      any(s.storage_id == "config" and not s.writable for s in st_k)
      and not MoonrakerFileProvider(_moon_get, _moon_delete).storage_writable(P_KLIP, "config"))
check("14. storage IDs opaque ([a-z0-9_-], не путь)",
      all(S.storage_id_ok(s.storage_id) for s in st_k + st_b))
check("15. frontend не получает абсолютные roots (в as_dict нет путей)",
      all("/" not in s.storage_id and ":" not in s.storage_id for s in st_k + st_b)
      and all(set(s.as_dict()) == {"storage_id", "display_name", "type", "writable",
                                   "total_bytes", "free_bytes", "online"} for s in st_k))

# ════════════════════════════════════════════════════════════════════════════
section("СЕРВЕРНЫЙ СЛОЙ: AST-извлечение _pf_list_impl/_pf_delete_impl")

_audit_rec = []
_log_rec = []


class _FakeLog(object):
    def _w(self, msg, *a):
        try:
            _log_rec.append(str(msg) % a if a else str(msg))
        except Exception:
            _log_rec.append(str(msg) + " " + " ".join(str(x) for x in a))
    info = warning = error = debug = _w


_printer_rows = {
    "p_b": {"id": "p_b", "type": "bambu", "model": "Bambu Lab X1 Carbon", "gen": "auto",
            "token": SECRET, "ip": "203.0.113.9", "port": None, "name": "B1"},
    "p_k": {"id": "p_k", "type": "klipper", "model": "RatRig", "gen": "", "token": "",
            "ip": "203.0.113.10", "port": 7125, "name": "K1"},
    "p_f": {"id": "p_f", "type": "flashforge", "model": "AD5M", "gen": "auto", "token": SECRET,
            "ip": "203.0.113.11", "port": 8898, "name": "F1"},
    "p_u": {"id": "p_u", "type": "prusa", "model": "MK4", "gen": "", "token": "",
            "ip": "203.0.113.12", "port": None, "name": "U1"},
}
_settings = {}
_P_STATES = {}

NS = {
    "time": time, "threading": threading, "json": json, "re": re,
    "_pf_models": M, "_pf_security": S, "_PfError": PrinterFileError,
    "_pf_registry": lambda: REG, "_PF_REFS": S.RefRegistry(),
    "_PF_ACTIVE_STATUSES": ("RUNNING", "PREPARE", "PAUSE", "PAUSED", "SLICING", "PRINTING", "BUSY"),
    "_PF_LIST_CACHE": {}, "_PF_LIST_CACHE_TTL": 10.0, "_PF_LIST_CACHE_MAX": 200,
    "_pf_locks": {}, "_pf_locks_guard": threading.Lock(),
    "p_states": _P_STATES,
    "_pf_printer_row": lambda pid: _printer_rows.get(str(pid)),
    "_get_setting": lambda k, d="": _settings.get(k, d),
    "_set_setting": lambda k, v: _settings.__setitem__(k, str(v)),
    "_audit": lambda username, action, target="", result="ok", req=None:
        _audit_rec.append({"user": username, "action": action, "target": target, "result": result}),
    "log": _FakeLog(), "_exc_brief": lambda: "err",
}
for _f in ("_pf_printer_lock", "_pf_read_enabled", "_pf_delete_enabled", "_pf_safe_printer",
           "_pf_active_context", "_pf_err", "_pf_list_impl", "_pf_delete_impl"):
    src = fn_src(_f)
    assert src, "нет функции %s в server.py" % _f
    exec(compile(src, "<server>", "exec"), NS)

pf_list_impl = NS["_pf_list_impl"]
pf_delete_impl = NS["_pf_delete_impl"]
REFS = NS["_PF_REFS"]

section("LISTING (16-28)")

r_root = pf_list_impl("p_b", "sd", "", False, None, None)
check("16. root listing работает (Bambu LIST разобран)",
      r_root["status"] == "ok" and any(e["name"] == "cache" and e["is_directory"] for e in r_root["entries"]))
_cache_dir = next(e for e in r_root["entries"] if e["name"] == "cache")
r_cache = pf_list_impl("p_b", "sd", "cache", False, None, None)
check("17. folder navigation работает (cache со своими файлами)",
      r_cache["status"] == "ok" and any(e["name"] == "partA.gcode.3mf" for e in r_cache["entries"]))
r_pg = pf_list_impl("p_k", "gcodes", "", True, 0, 2)
r_pg2 = pf_list_impl("p_k", "gcodes", "", False, r_pg["cursor_next"], 2)
check("18. pagination работает (cursor/limit; корень gcodes: папка sub + 2 файла)",
      len(r_pg["entries"]) == 2 and r_pg["cursor_next"] == "2" and r_pg["total"] == 3
      and len(r_pg2["entries"]) == 1 and r_pg2["cursor_next"] is None)


def _empty_get(pid, path):
    if path == "/server/files/roots":
        return {"result": [{"name": "gcodes"}]}
    if "list" in path:
        return {"result": []}
    return {"result": {}}


REG_EMPTY = _mk_registry(moon_get=_empty_get)
NS["_pf_registry"] = lambda: REG_EMPTY
r_empty = pf_list_impl("p_k", "gcodes", "", True, None, None)
NS["_pf_registry"] = lambda: REG
check("19. empty storage работает (ok + 0 entries, не ошибка)",
      r_empty["status"] == "ok" and r_empty["total"] == 0)
r_unsup = pf_list_impl("p_u", "internal", "", False, None, None)
check("20. unsupported — отдельное состояние (reason unsupported, не пустой ok)",
      r_unsup["status"] == "error" and r_unsup["reason"] == "unsupported")


def _timeout_get(pid, path):
    raise PrinterFileError(M.REASON_TIMEOUT)


REG_TMO = _mk_registry(moon_get=_timeout_get)
NS["_pf_registry"] = lambda: REG_TMO
r_tmo = pf_list_impl("p_k", "gcodes", "", True, None, None)
NS["_pf_registry"] = lambda: REG
check("21. timeout не выглядит как empty (status=error, reason=timeout)",
      r_tmo["status"] == "error" and r_tmo["reason"] == "timeout")


def _bad_get(pid, path):
    if path == "/server/files/roots":
        return {"result": [{"name": "gcodes"}]}
    return {"result": "GARBAGE"}


REG_BAD = _mk_registry(moon_get=_bad_get)
NS["_pf_registry"] = lambda: REG_BAD
r_bad = pf_list_impl("p_k", "gcodes", "", True, None, None)
NS["_pf_registry"] = lambda: REG
check("22. malformed response -> fail-closed (malformed_response, не пустой список)",
      r_bad["status"] == "error" and r_bad["reason"] == "malformed_response")
_e1 = next(e for e in r_cache["entries"] if e["name"] == "partA.gcode.3mf")
check("23. entries нормализованы (opaque refs, без путей/IP в ответе)",
      _e1["file_ref"].startswith("pfr_") and "cache" not in _e1["file_ref"]
      and "203.0.113" not in json.dumps(r_cache) and SECRET not in json.dumps(r_cache))
check("24. size нормализован (int байты из LIST)", _e1["size_bytes"] == 52428800)
check("25. modified time нормализован (epoch int) либо честный None",
      isinstance(_e1["modified_at"], int)
      and next(e for e in r_root["entries"] if e["name"] == "cache")["size_bytes"] is None)
_r_tl = pf_list_impl("p_b", "sd", "timelapse", False, None, None)
check("26. unknown date не попадает в old filter (см. UI-часть S5) и не выдумывается",
      all(("modified_at" in e) for e in _r_tl["entries"]))
check("27. directory не считается файлом (is_directory=True, ref pfd_)",
      _cache_dir["is_directory"] and _cache_dir["file_ref"].startswith("pfd_"))
r_sub = pf_list_impl("p_k", "gcodes", "sub", False, None, None)
check("28. duplicate names в разных папках не смешиваются (sub/ отдельно от корня)",
      [e["name"] for e in r_sub["entries"]] == ["job2.3mf"]
      and any(e["name"] == "sub" and e["is_directory"] for e in r_pg["entries"] + r_pg2["entries"]))

# ════════════════════════════════════════════════════════════════════════════
section("CATEGORIES (29-34)")

check("29. G-code/3MF классифицируются как programs",
      S.categorize("a.gcode")[0] == M.CAT_PROGRAM and S.categorize("b.3mf")[0] == M.CAT_PROGRAM
      and _e1["category"] == "program")
_tl_e = next(e for e in _r_tl["entries"] if e["name"] == "video_001.mp4")
check("30. video классифицируется как video", _tl_e["category"] == "video")
check("31. timelapse требует контекста (в /timelapse — да, в /cache — нет)",
      _tl_e["timelapse"] is True
      and S.categorize("x.mp4", "sd/cache", ("sd/timelapse",)) == (M.CAT_VIDEO, False))
check("32. image классифицируется", S.categorize("p.png")[0] == M.CAT_IMAGE)
check("33. system log protected (журналы не удаляются)",
      S.protection_for("k.log", False, M.CAT_LOG, True, ()) == (False, M.REASON_SYSTEM_FILE))
check("34. unknown extension -> other (и protected fail-closed)",
      S.categorize("z.xyz")[0] == M.CAT_OTHER
      and not S.protection_for("z.xyz", False, M.CAT_OTHER, True, ())[0])

# ════════════════════════════════════════════════════════════════════════════
section("SECURITY (35-50)")

check("35. `..` блокируется", S.normalize_rel_path("../x") is None and S.normalize_rel_path("a/../b") is None)
check("36. absolute path блокируется", S.normalize_rel_path("/abs") is None
      and S.normalize_rel_path("C:" + chr(92) + "x") is None)
check("37. UNC блокируется", S.normalize_rel_path(chr(92) * 2 + "host" + chr(92) + "share") is None
      and S.normalize_rel_path("//host/share") is None)
check("38. file:// блокируется", S.normalize_rel_path("file://x") is None)
check("39. javascript: блокируется", S.normalize_rel_path("javascript:alert(1)") is None)
_ref_pb = _e1["file_ref"]
check("40. подмена printer ID блокируется (ref другого принтера не резолвится)",
      REFS.resolve(_ref_pb, "p_k") is None and REFS.resolve(_ref_pb, "p_b") is not None)
_r_res = pf_list_impl("p_b", "model", "", False, None, None)
check("41. подмена storage ID блокируется (bad_request для чужого storage)",
      _r_res["status"] == "error" and _r_res["reason"] == "bad_request")
check("42. stale/мусорный file_ref блокируется",
      REFS.resolve("pfr_deadbeefdeadbeefdeadbeef", "p_b") is None
      and REFS.resolve("../../x", "p_b") is None)
_settings["printer_files_delete_enabled"] = "1"
_dir_res = pf_delete_impl("p_b", [_cache_dir["file_ref"]], "tester")
check("43. directory delete блокируется (reason=directory, DELE не вызывался)",
      _dir_res["results"][0]["reason"] == "directory" and not _ftp_calls["deleted"])
_P_STATES["p_b"] = {"status": "RUNNING", "file_name": "partA.gcode.3mf"}
_act_res = pf_delete_impl("p_b", [_e1["file_ref"]], "tester")
check("44. active print file delete блокируется (печать идёт -> запрет всего delete у Bambu)",
      _act_res["status"] == "error" and _act_res["reason"] == "printing_delete_unverified"
      and not _ftp_calls["deleted"])
_P_STATES["p_b"] = {"status": "IDLE", "file_name": ""}
_r_root2 = pf_list_impl("p_b", "sd", "", True, None, None)
_sys_e = next(e for e in _r_root2["entries"] if e["name"] == "boot.cfg")
_sys_res = pf_delete_impl("p_b", [_sys_e["file_ref"]], "tester")
check("45. system file delete блокируется (cfg protected)",
      not _sys_res["results"][0]["ok"] and _sys_res["results"][0]["reason"] == "system_file"
      and not _ftp_calls["deleted"])
check("46. unknown entry delete блокируется (протухший ref -> stale_reference)",
      pf_delete_impl("p_b", ["pfr_0000000000000000"], "tester")["results"][0]["reason"] == "stale_reference")
check("47. delete без права блокируется (обработчик pf_delete начинается с _require_system_admin)",
      re.search(r"async def pf_delete\(req[\s\S]{0,400}_require_system_admin\(req\)", fn_src("pf_delete"))
      and fn_src("pf_delete").index("_require_system_admin") < fn_src("pf_delete").index("_pf_delete_enabled"))
_settings.pop("printer_files_delete_enabled", None)
check("48. delete при выключенном флаге блокируется (default off)",
      NS["_pf_delete_enabled"]() is False and S.PRINTER_FILE_DELETE_ENABLED_DEFAULT is False
      and "'1' if _pf_security.PRINTER_FILE_DELETE_ENABLED_DEFAULT else '0'" in fn_src("_pf_delete_enabled").replace('"', "'"))
check("49. Client не может обойти серверный guard (проверка флага и прав — В обработчике, до impl)",
      fn_src("pf_delete").index("_pf_delete_enabled") < fn_src("pf_delete").index("_pf_delete_impl")
      and "delete_ui_allowed" not in fn_src("pf_delete"))   # frontend-флагу сервер не доверяет
check("50. credentials не попадают в response/log (sentinel-код нигде не всплыл)",
      SECRET not in json.dumps(_audit_rec) and SECRET not in "".join(_log_rec)
      and SECRET not in json.dumps(r_cache) + json.dumps(_r_tl))

# ════════════════════════════════════════════════════════════════════════════
section("DELETE (51-61)")

_settings["printer_files_delete_enabled"] = "1"
_ftp_calls["deleted"] = []
_r_cache3 = pf_list_impl("p_b", "sd", "cache", True, None, None)
_old_e = next(e for e in _r_cache3["entries"] if e["name"] == "old_job.gcode")
_n_listed0 = len(_ftp_calls["listed"])
_del1 = pf_delete_impl("p_b", [_old_e["file_ref"]], "tester")
check("51/52. single delete: backend ПОВТОРНО листит каталог на устройстве до и после DELE",
      _ftp_calls["listed"][_n_listed0:].count("/cache") >= 2)
# файл остаётся в фейковом дереве -> пост-проверка видит его -> delete_unconfirmed (честно)
check("53. delete success подтверждается ПОСЛЕ пост-проверки (файл остался -> unconfirmed, не ложный успех)",
      _del1["results"][0]["reason"] == "delete_unconfirmed" and _ftp_calls["deleted"] == ["/cache/old_job.gcode"])
_FakeFtp.tree["/cache"] = [l for l in _FakeFtp.tree["/cache"] if "old_job" not in l]
_r_cache4 = pf_list_impl("p_b", "sd", "cache", True, None, None)
_gone = next((e for e in _r_cache4["entries"] if e["name"] == "old_job.gcode"), None)
check("54. not found идемпотентно: исчезнувший файл -> ok c reason not_found",
      _gone is None)
_ftp_calls["deleted"] = []


class _FtpDeleteOk(_FakeFtp):
    tree = {"/": ["drwxr-xr-x 2 r r 4096 Jan 01 10:00 cache"],
            "/cache": ["-rw-r--r-- 1 r r 100 Jan 01 10:00 zz.gcode"]}

    def delete(self, path):
        _ftp_calls["deleted"].append(path)
        self.__class__.tree["/cache"] = []          # файл реально исчезает -> пост-проверка подтверждает


REG_OK = _mk_registry(ftp_factory=lambda pid: _FtpDeleteOk())
NS["_pf_registry"] = lambda: REG_OK
_r_zz = pf_list_impl("p_b", "sd", "cache", True, None, None)
_zz = next(e for e in _r_zz["entries"] if e["name"] == "zz.gcode")
_delok = pf_delete_impl("p_b", [_zz["file_ref"]], "tester")
check("53b. подтверждённое удаление -> ok=true (пост-листинг не видит файла)",
      _delok["status"] == "ok" and _delok["deleted"] == 1 and _delok["results"][0]["ok"])
_zz_again = pf_list_impl("p_b", "sd", "cache", True, None, None)
_FtpDeleteOk.tree["/cache"] = ["-rw-r--r-- 1 r r 100 Jan 01 10:00 zz.gcode"]
_r_zz2 = pf_list_impl("p_b", "sd", "cache", True, None, None)
_zz2 = next(e for e in _r_zz2["entries"] if e["name"] == "zz.gcode")


class _FtpTimeout(_FtpDeleteOk):
    calls = {"n": 0}

    def delete(self, path):
        self.__class__.calls["n"] += 1
        raise TimeoutError("no answer")


REG_TMO2 = _mk_registry(ftp_factory=lambda pid: _FtpTimeout())
NS["_pf_registry"] = lambda: REG_TMO2
_deltmo = pf_delete_impl("p_b", [_zz2["file_ref"]], "tester")
NS["_pf_registry"] = lambda: REG
check("55. timeout -> unknown/failed (timeout), НЕ ложный success",
      not _deltmo["results"][0]["ok"] and _deltmo["results"][0]["reason"] == "timeout")
check("59. автоматического retry destructive operation НЕТ (ровно 1 попытка DELE)",
      _FtpTimeout.calls["n"] == 1)
check("56. bulk delete ограничен (>100 refs -> bad_request в обработчике)",
      "len(refs) > 100" in fn_src("pf_delete") and "[:100]" in fn_src("_pf_delete_impl"))
_settings["printer_files_delete_enabled"] = "1"
_r_mix = pf_list_impl("p_k", "gcodes", "", True, None, None)
_P_STATES["p_k"] = {"status": "RUNNING", "file_name": "active.gcode"}
_r_mix = pf_list_impl("p_k", "gcodes", "", True, None, None)
_mix_active = next(e for e in _r_mix["entries"] if e["name"] == "active.gcode")
_mix_ok = next(e for e in _r_mix["entries"] if e["name"] == "job1.gcode")
_moon_deleted.clear()
_bulk = pf_delete_impl("p_k", [_mix_active["file_ref"], _mix_ok["file_ref"]], "tester")
check("57. protected entries исключаются (active file skip, другой удаляется — Moonraker durante печати)",
      any(r["reason"] == "active_print_file" and not r["ok"] for r in _bulk["results"])
      and "gcodes/job1.gcode" in " ".join(_moon_deleted))
check("58. partial result показывается по файлам (status=partial, пофайловые причины)",
      _bulk["status"] == "partial" and len(_bulk["results"]) == 2)
check("60/61. директория не удаляется и рекурсивного delete нет",
      "rmtree" not in PF_SRC["moonraker.py"] + PF_SRC["bambu.py"] + fn_src("_pf_delete_impl")
      and "rmdir" not in PF_SRC["bambu.py"].lower())
_P_STATES["p_k"] = {"status": "IDLE", "file_name": ""}

# ════════════════════════════════════════════════════════════════════════════
section("ACTIVE PRINT (62-68)")

check("62. current file protected (совпадение имени печати)",
      not S.protection_for("active.gcode", False, M.CAT_PROGRAM, True, ("active.gcode",))[0])
check("63. preparing file protected (PREPARE в списке активных статусов)",
      "PREPARE" in NS["_PF_ACTIVE_STATUSES"] and "SLICING" in NS["_PF_ACTIVE_STATUSES"])
check("64. busy file protected (BUSY статус учитывается)", "BUSY" in NS["_PF_ACTIVE_STATUSES"])
check("65. другие файлы при печати разрешены ТОЛЬКО при подтверждённой capability "
      "(Moonraker=True, Bambu=False, FlashForge=False)",
      MoonrakerFileProvider(_moon_get, _moon_delete).delete_safe_during_print is True
      and BambuFileProvider(lambda pid: None).delete_safe_during_print is False
      and FlashforgeFileProvider(lambda pid: []).delete_safe_during_print is False)
check("66. неизвестная безопасность при печати -> delete blocked (см. 44; default в base=False)",
      PrinterFileProvider.delete_safe_during_print is False)
_impl_src = fn_src("_pf_list_impl") + fn_src("_pf_delete_impl")
check("67. file manager не меняет lifecycle state (нет lifecycle/latch/user_stopped в импл.)",
      not any(t in _impl_src for t in ("_user_stopped", "_cancel_latch", "job_finished",
                                       "observe_printer_job", "print_run")))
check("68. file manager не меняет done counters (нет printed_qty/parts_catalog в импл.)",
      "printed_qty" not in _impl_src and "parts_catalog" not in _impl_src)

# ════════════════════════════════════════════════════════════════════════════
section("FTPS-транспорт server.py: замок и секреты (изоляция)")

_ftp_ns = {
    "_pf_printer_row": lambda pid: _printer_rows.get(str(pid)),
    "_PfError": PrinterFileError, "_pf_models": M, "log": _FakeLog(), "socket": socket,
    "_ftp_lock": lambda ip: threading.Lock(),
    "ImplicitFTP_TLS": type("F", (), {"connect": lambda s, *a, **k: (_ for _ in ()).throw(TimeoutError())}),
}
exec(compile(fn_src("_PfFtpSession"), "<srv>", "exec"), _ftp_ns)
exec(compile(fn_src("_pf_ftp_factory"), "<srv>", "exec"), _ftp_ns)
try:
    _ftp_ns["_pf_ftp_factory"]("p_b")
    _ftp_err = ""
except PrinterFileError as e:
    _ftp_err = e.reason
check("T1. таймаут FTPS -> безопасный reason timeout (без raw-текста)", _ftp_err == "timeout")
check("T2. access code не утёк в лог транспорта", SECRET not in "".join(_log_rec))

# ════════════════════════════════════════════════════════════════════════════
section("UI (69-94): статика + Node-исполнение извлечённого блока")

check("69. workspace существует (.fm-printer-files-workspace, контракт leftColH)",
      'class="fm-printer-files-workspace"' in INDEXHTML
      and ':style="{ height: leftColH }"' in INDEXHTML.split("fm-printer-files-workspace")[1][:400])
#  2.974: пункт уехал из контекстного меню карточки в пульт принтера (оформление 3.0):
#  кнопка «Файлы принтера» открывает файлы ВЫБРАННОГО принтера. Смысл прежний —
#  открытие всегда с явным принтером, а не «какой был последним».
check("70. открытие всегда с явным принтером (кнопка пульта -> openPrinterFiles(ui3Printer))",
      '@click="openPrinterFiles(ui3Printer)"' in INDEXHTML and '"Printer files": "Файлы принтера"' in APPJS)
check("70b. общий пункт меню (Настройки -> Инструменты) существует",
      'openPrinterFiles()"' in INDEXHTML)
check("71. storage tabs создаются из backend data (v-for s in pfStorages)",
      'v-for="s in pfStorages"' in INDEXHTML and 'pfSelectStorage(s.storage_id)' in INDEXHTML)
check("72-75. search/sort в разметке (pfSearch, pfSetSort по name/size/date)",
      'v-model="pfSearch"' in INDEXHTML and "pfSetSort('name')" in INDEXHTML
      and "pfSetSort('size')" in INDEXHTML and "pfSetSort('date')" in INDEXHTML)
check("76/77. фильтры программ и таймлапсов существуют",
      'value="program"' in INDEXHTML and 'value="timelapse"' in INDEXHTML)
# Alpha 2.825: checkbox зависит ТОЛЬКО от selectable (не каталог); удаление — по-прежнему
# отдельно по deletable. Старая связка checkbox<->deletable и была дефектом приёмки 2.824.
check("80. checkbox по selectable (независим от delete); кнопка удаления по deletable",
      ':disabled="!pfSelectable(e)"' in INDEXHTML
      and ':disabled="e.is_directory || !e.deletable"' not in INDEXHTML
      and ':disabled="!e.deletable || !pfDeleteAllowed || pfDeleteBusy"' in INDEXHTML
      and '@click="pfRowClick($event, e)"' in INDEXHTML)
check("81. delete-disabled state понятен (подсказка, где включить)",
      "Настройки → Система → Файлы принтеров" in INDEXHTML)
check("82/83/84. unsupported/offline/empty/error — разные состояния в разметке",
      "pfState==='unsupported'" in INDEXHTML and "pfState==='offline'" in INDEXHTML
      and "pfState==='empty'" in INDEXHTML and "pfState==='error'" in INDEXHTML)
check("85. breadcrumbs работают (pfCrumbTo/pfPath)",
      "pfCrumbTo(-1)" in INDEXHTML and 'v-for="(c,i) in pfPath"' in INDEXHTML)
check("86. refresh работает (pfRefresh с fresh=true в коде)",
      "pfRefresh()" in INDEXHTML and "pfLoadList(true)" in APPJS)
check("88. workspace scroll внутренний (.pfw-body flex:1 + overflow:auto + overscroll contain)",
      ".pfw-body{flex:1 1 auto;min-height:0;overflow:auto;overscroll-behavior:contain}" in APPCSS)
check("89. sidebar остаётся видимым (workspace в том же flex-слоте: main v-show по workspaceView)",
      "workspaceView==='projects'" in INDEXHTML
      and "showPrinterFiles.value ? 'printerFiles'" in APPJS)
check("93. Browser/Desktop используют один DOM (одна секция, нет отдельной desktop-разметки)",
      INDEXHTML.count('class="fm-printer-files-workspace"') == 1)
check("94. Client delete подчиняется server permissions (кнопки шлют только refs; прав нет — сервер 401/403)",
      "file_refs: refs" in APPJS and "delete_ui_allowed" in APPJS)
check("E1. Escape-цепочка закрывает экран (вставка после диагностики)",
      "if (showPrinterFiles.value) { closePrinterFiles(); return; }" in APPJS)
#  Alpha 2.898: в том же слоте появился третий экран — «Отчёты», и он тоже обязан уводить
#  «Файлы принтеров». Поэтому вхождений стало три, а не две.
check("E2. взаимное исключение экранов (настройки, диагностика и отчёты закрывают printerFiles)",
      APPJS.count("if (showPrinterFiles.value) closePrinterFiles();") == 3)
#  Alpha 2.900: и наоборот — открытие «Файлов принтеров» обязано увести «Отчёты». Дефект 2.898:
#  два рабочих экрана делили один слот пополам, обе таблицы были обрезаны.
check("E2a. открытие «Файлов принтеров» закрывает «Отчёты»",
      "if (showReports.value) closeReports();" in APPJS.split("const openPrinterFiles")[1][:400])

# ── Node-исполнение извлечённого pf-блока ────────────────────────────────────
_i0 = APPJS.find("    const showPrinterFiles = ref(false);")
_i1 = APPJS.find("const closePrinterFiles = () => { showPrinterFiles.value = false; _pfGen++; };")
PF_BLOCK = APPJS[_i0:_i1 + len("const closePrinterFiles = () => { showPrinterFiles.value = false; _pfGen++; };")]
check("N0. pf-блок извлечён из app.js", _i0 > 0 and _i1 > _i0 and "pfRowsView" in PF_BLOCK)

NODE_RES = {}
if _i0 > 0 and _i1 > _i0:
    HARNESS = r"""
'use strict';
const ref = (v) => ({ value: v });
const computed = (fn) => ({ get value() { return fn(); } });
const lang = ref('ru');
const printers = ref([{ id: 'p1', name: 'P1' }, { id: 'p2', name: 'P2' }]);
const showDiag = ref(false), showSettings = ref(false);
const closeDiagnostics = () => { showDiag.value = false; };
const closeSettings = () => { showSettings.value = false; };
const localStorage = { _m: {}, getItem(k) { return this._m[k] || null; }, setItem(k, v) { this._m[k] = String(v); } };
let confirmCalls = 0, confirmResult = true;
const confirm = (t) => { confirmCalls++; return confirmResult; };
const alerts = [];
const alert = (t) => alerts.push(String(t));
const fetchLog = [];
let fetchImpl = async (url, opts) => ({ json: async () => ({ status: 'ok' }) });
const fetch = (url, opts) => { fetchLog.push({ url, body: (opts && opts.body) ? JSON.parse(opts.body) : null }); return fetchImpl(url, opts); };
// 2.825: стабы существующего print-flow (pf-блок ссылается на них ТОЛЬКО в момент вызова)
const wsData = ref({});
const sendReserved = ref(new Set());
const cellBusy = (pid) => ((wsData.value[pid] || {}).status === 'RUNNING') || sendReserved.value.has(pid);
//  2.959: вопросы задаёт САМА программа (askConfirm), а не окно браузера confirm().
//  Ответ берём из того же confirmResult, что и раньше, и считаем тем же счётчиком —
//  сцена «оператор отказался» продолжает работать без изменений.
const askConfirm = async () => { confirmCalls++; return confirmResult; };
//  2.959: подписи на двух языках.
const _L = (ru, en) => String(ru);
const toasts = [];
const pushToast = (t, k) => toasts.push(String(t));
const tr = (s) => String(s);
const _printerNameOf = (pid) => pid;
const sendCalls = [];
const handleSendResp = (resp, ctx) => { sendCalls.push({ resp, ctx }); return (resp && resp.accepted) ? 'accepted' : 'other'; };
const printStartCalls = [];
const openPrintStart = (ctx) => { printStartCalls.push(ctx); };
const activeModalPrinterId = ref('');
const printerFiles = ref([]);
const printFileName = ref('');
%%BLOCK%%
const CAPS_OK = { status: 'ok', read_enabled: true, delete_enabled: true, delete_ui_allowed: true,
  capabilities: { supported: true, list_files: true, delete_files: true }, printer: { id: 'p1', name: 'P1' } };
const STOR_OK = { status: 'ok', storages: [{ storage_id: 'sd', display_name: 'SD', type: 'sd', writable: true, online: true, total_bytes: null, free_bytes: null }] };
const mkEntry = (o) => Object.assign({ file_ref: 'pfr_' + Math.abs(o.name.length * 7919).toString(16) + o.name.replace(/[^a-z0-9]/gi, ''), name: o.name,
  is_directory: false, category: 'program', timelapse: false, extension: '.gcode', size_bytes: 100,
  modified_at: 1700000000, storage_id: 'sd', deletable: true, protected_reason: '', active_print: false }, o);
(async () => {
  const out = {};
  // S1: ошибка чтения != empty
  fetchImpl = async (url) => ({ json: async () => url.includes('capabilities') ? CAPS_OK : (url.includes('storages') ? STOR_OK : { status: 'error', reason: 'timeout' }) });
  await pfSelectPrinter('p1');
  out.s1_offline = pfState.value;
  fetchImpl = async (url) => ({ json: async () => url.includes('capabilities') ? CAPS_OK : (url.includes('storages') ? STOR_OK : { status: 'error', reason: 'malformed_response' }) });
  await pfLoadList(true);
  out.s1_error = pfState.value; out.s1_reason = pfReason.value;
  // S2: stale-ответ прошлого принтера игнорируется
  let releaseP1; const gateP1 = new Promise((res) => { releaseP1 = res; });
  fetchImpl = async (url, opts) => {
    const body = (opts && opts.body) ? JSON.parse(opts.body) : {};
    if (url.includes('capabilities')) return { json: async () => CAPS_OK };
    if (url.includes('storages')) return { json: async () => STOR_OK };
    if (body.printer_id === 'p1') { await gateP1; return { json: async () => ({ status: 'ok', entries: [mkEntry({ name: 'FROM_P1.gcode' })], total: 1, cursor_next: null }) }; }
    return { json: async () => ({ status: 'ok', entries: [mkEntry({ name: 'from_p2.gcode' })], total: 1, cursor_next: null }) };
  };
  const p1run = pfSelectPrinter('p1');
  await new Promise((r) => setTimeout(r, 5));   // p1 успевает ВЫДАТЬ list-запрос (printer_id=p1) и повиснуть на gate
  const p2run = pfSelectPrinter('p2');
  await p2run; releaseP1(); await p1run;
  await new Promise((r) => setTimeout(r, 10));
  out.s2_names = (pfEntries.value || []).map((e) => e.name);
  // S3: unsupported
  fetchImpl = async (url) => ({ json: async () => url.includes('capabilities')
    ? { status: 'ok', read_enabled: true, delete_enabled: false, delete_ui_allowed: false, capabilities: { supported: false, reason: 'no_credentials' }, printer: { id: 'p1', name: 'P1' } }
    : { status: 'error', reason: 'unsupported' } });
  await pfSelectPrinter('p1');
  out.s3_state = pfState.value; out.s3_reason = pfReason.value;
  // S4: read disabled
  fetchImpl = async (url) => ({ json: async () => url.includes('capabilities')
    ? Object.assign({}, CAPS_OK, { read_enabled: false }) : { status: 'error', reason: 'read_disabled' } });
  await pfSelectPrinter('p1');
  out.s4_state = pfState.value;
  // подготовка данных для фильтров/удаления
  fetchImpl = async (url) => ({ json: async () => url.includes('capabilities') ? CAPS_OK : (url.includes('storages') ? STOR_OK
    : { status: 'ok', total: 5, cursor_next: null, entries: [
        mkEntry({ name: 'new.gcode', modified_at: Math.floor(Date.now() / 1000) - 3600 }),
        mkEntry({ name: 'old.gcode', modified_at: Math.floor(Date.now() / 1000) - 40 * 86400 }),
        mkEntry({ name: 'nodate.gcode', modified_at: null }),
        mkEntry({ name: 'tl.mp4', category: 'video', timelapse: true, modified_at: Math.floor(Date.now() / 1000) - 3600 }),
        mkEntry({ name: 'prot.cfg', category: 'other', deletable: false, protected_reason: 'system_file', modified_at: Math.floor(Date.now() / 1000) - 3600 }),
      ] }) });
  await pfSelectPrinter('p1');
  out.s5_total = (pfEntries.value || []).length;
  pfAge.value = 7;
  out.s5_age = pfRowsView.value.map((e) => e.name);         // только old.gcode + tl? tl имеет дату now
  pfAge.value = 0; pfCat.value = 'timelapse';
  out.s6_tl = pfRowsView.value.map((e) => e.name);
  pfCat.value = '';
  // S7 (2.825): выбор НЕЗАВИСИМ от удаления — protected строка ВЫБИРАЕТСЯ,
  // но deletable-подмножество считается отдельно и её не включает.
  pfToggleSel((pfEntries.value || []).find((e) => e.name === 'prot.cfg'));
  out.s7_protsel = pfSelected.value.size;                   // 1: файл выбран
  pfSelectShown();
  out.s7_shown = pfSelected.value.size;                     // все 5 показанных файлов
  out.s7_deletable = (pfEntries.value || []).filter((e) => pfSelected.value.has(e.file_ref) && e.deletable).length;
  // S8: подтверждение обязательно; отказ -> нет запроса
  fetchLog.length = 0; confirmCalls = 0; confirmResult = false;
  await pfDeleteOne((pfEntries.value || []).find((e) => e.name === 'new.gcode'));
  out.s8_declined = { confirms: confirmCalls, deletes: fetchLog.filter((f) => f.url.includes('/delete')).length };
  confirmResult = true; fetchLog.length = 0; confirmCalls = 0;
  fetchImpl = async (url) => ({ json: async () => url.includes('/delete')
    ? { status: 'ok', deleted: 1, failed: 0, results: [{ ok: true }] }
    : { status: 'ok', entries: [], total: 0, cursor_next: null } });
  await pfDeleteOne((pfEntries.value || []).find((e) => e.name === 'new.gcode'));
  const delCall = fetchLog.find((f) => f.url.includes('/delete'));
  out.s8_ok = { confirms: confirmCalls, body: delCall ? delCall.body : null };
  // S10: без разрешения удаление не выполняется
  pfFlags.value = { read_enabled: true, delete_enabled: false, delete_ui_allowed: false };
  fetchLog.length = 0; confirmCalls = 0;
  await pfDeleteOne(mkEntry({ name: 'x.gcode' }));
  out.s10 = { confirms: confirmCalls, deletes: fetchLog.filter((f) => f.url.includes('/delete')).length };
  process.stdout.write('@@RES@@' + JSON.stringify(out) + '@@END@@');
})().catch((e) => { process.stdout.write('@@RES@@' + JSON.stringify({ fatal: String(e && e.stack || e) }) + '@@END@@'); });
"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_pf_node_") as _td:
        hp = os.path.join(_td, "h.js")
        io.open(hp, "w", encoding="utf-8", newline="\n").write(HARNESS.replace("%%BLOCK%%", PF_BLOCK))
        try:
            pr = subprocess.run(["node", hp], capture_output=True, text=True, encoding="utf-8", timeout=60)
            m = re.search(r"@@RES@@(\{.*\})@@END@@", pr.stdout or "", re.S)
            NODE_RES = json.loads(m.group(1)) if m else {"fatal": (pr.stdout or "") + (pr.stderr or "")}
        except Exception as e:
            NODE_RES = {"fatal": str(e)}

check("N1. Node-исполнение pf-блока прошло", NODE_RES and "fatal" not in NODE_RES,
      NODE_RES.get("fatal", ""))
if NODE_RES and "fatal" not in NODE_RES:
    check("N2/21b. ошибка чтения НЕ выглядит как пустой список (timeout->offline, malformed->error)",
          NODE_RES["s1_offline"] == "offline" and NODE_RES["s1_error"] == "error"
          and NODE_RES["s1_reason"] == "malformed_response")
    check("N3/87. stale response другого принтера игнорируется (в UI только p2)",
          NODE_RES["s2_names"] == ["from_p2.gcode"])
    check("N4/82b. unsupported показывает состояние и причину (no_credentials)",
          NODE_RES["s3_state"] == "unsupported" and NODE_RES["s3_reason"] == "no_credentials")
    check("N5. read-флаг выключен -> отдельное состояние readdisabled",
          NODE_RES["s4_state"] == "readdisabled")
    check("N6/78. возрастной фильтр работает ТОЛЬКО по достоверной дате (nodate исключён)",
          NODE_RES["s5_age"] == ["old.gcode"] and NODE_RES["s5_total"] == 5)
    check("N7/77b. фильтр таймлапсов отделяет их от прочего видео/файлов",
          NODE_RES["s6_tl"] == ["tl.mp4"])
    check("N8/79. multi-select независим от delete: protected строка выбирается, deletable-подмножество отдельно",
          NODE_RES["s7_protsel"] == 1 and NODE_RES["s7_shown"] == 5
          and NODE_RES["s7_deletable"] == 4)
    check("N9/51b. отказ от подтверждения -> удаление НЕ отправляется",
          NODE_RES["s8_declined"]["confirms"] == 1 and NODE_RES["s8_declined"]["deletes"] == 0)
    check("N10. подтверждённое удаление шлёт ТОЛЬКО opaque refs (без имён/путей в теле)",
          NODE_RES["s8_ok"]["confirms"] == 1 and NODE_RES["s8_ok"]["body"]
          and list(NODE_RES["s8_ok"]["body"].keys()) == ["printer_id", "file_refs"]
          and all(str(r).startswith("pfr_") for r in NODE_RES["s8_ok"]["body"]["file_refs"]))
    check("N11. при выключенном разрешении delete не выполняется и не спрашивается",
          NODE_RES["s10"]["confirms"] == 0 and NODE_RES["s10"]["deletes"] == 0)
else:
    for _n in ("N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11"):
        check("%s. Node-блок недоступен" % _n, False, "node harness failed")

# ════════════════════════════════════════════════════════════════════════════
section("LAYOUT в реальном движке (90-92: zoom 125-200, RU/EN)")


def pfw_page(langv, bz):
    css_href = "file:///" + os.path.join(REPO, "web", "app.css").replace("\\", "/")
    long_name = ("очень_длинное_имя_файла_печати_кронштейн_усиленный_v12_final" if langv == "ru"
                 else "very_long_print_file_name_bracket_reinforced_v12_final") + ".gcode.3mf"
    rows = "".join(
        "<tr><td class='pfw-thc'><input type='checkbox'></td>"
        "<td class='pfw-name'><span class='pfw-file'><span class='pfw-nm'>%s_%d</span></span></td>"
        "<td>%s</td><td class='pfw-num'>52.4 МБ</td><td>01.02.2026 11:00</td><td>—</td>"
        "<td class='pfw-thc'><button class='pfw-del'>x</button></td></tr>" % (long_name, i,
        ("Программа" if langv == "ru" else "Program")) for i in range(40))
    L = {"ru": {"t": "Файлы принтеров", "e": "Экспериментально", "r": "Обновить", "s": "Поиск по имени",
                "old": "Старые программы", "sel": "Выбрать показанные", "del": "Удалить выбранные",
                "sum": "40 файлов · 2.1 ГБ · свободно 3.4 ГБ из 28 ГБ"},
         "en": {"t": "Printer files", "e": "Experimental", "r": "Refresh", "s": "Search by name",
                "old": "Old programs", "sel": "Select shown", "del": "Delete selected",
                "sum": "40 files · 2.1 GB · free 3.4 GB of 28 GB"}}[langv]
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<link rel='stylesheet' href='" + css_href + "'>"
            "<style>html,body{margin:0;height:100%;overflow:hidden;background:#141416}"
            "#__res{position:fixed;left:-9999px;top:0}#bz{zoom:" + str(bz) + ";height:100%}"
            ".main-cols{display:flex;gap:8px;width:100%;height:100%;min-height:0;padding:8px}"
            ".left-col{width:360px;flex:0 0 auto;background:#1b1b1e;border:1px solid #333}"
            "</style></head><body><div id='bz'><div class='main-cols'>"
            "<div class='left-col' id='side'></div>"
            "<section class='fm-printer-files-workspace' id='ws'>"
            "<div class='pfw-head' id='ph'><svg class='pfw-ico'></svg>"
            "<span class='pfw-title'>" + L["t"] + "</span><span class='pfw-exp'>" + L["e"] + "</span>"
            "<div class='pfw-group'><select class='pfw-sel'><option>Bambu Lab X1 Carbon (FFA5M-1)</option></select>"
            "<button class='pfw-btn'>" + L["r"] + "</button></div><span class='pfw-flex'></span>"
            "<button class='pfw-x'>x</button></div>"
            "<div class='pfw-storages'><button class='pfw-stab on'>SD-карта</button>"
            "<button class='pfw-stab'>Таймлапсы</button></div>"
            "<div class='pfw-bar' id='pb'><div class='pfw-crumbs'><button class='pfw-crumb'>SD-карта</button>"
            "<span class='pfw-csep'>/</span><button class='pfw-crumb'>cache</button></div>"
            "<input class='pfw-search' placeholder='" + L["s"] + "'>"
            "<div class='pfw-group'><select class='pfw-sel'><option>Программы печати</option></select>"
            "<select class='pfw-sel'><option>Старше 30 дней</option></select>"
            "<button class='pfw-btn'>" + L["old"] + "</button></div></div>"
            "<div class='pfw-sum'>" + L["sum"] + "</div>"
            "<div class='pfw-body' id='pbody'><table class='pfw-tbl'><thead><tr>"
            "<th class='pfw-thc'></th><th>Имя</th><th>Категория</th><th class='pfw-num'>Размер</th>"
            "<th>Дата</th><th>Состояние</th><th class='pfw-thc'></th></tr></thead><tbody>" + rows +
            "</tbody></table></div>"
            "<div class='pfw-selbar' id='psel'><button class='pfw-btn'>" + L["sel"] + "</button>"
            "<span class='pfw-selinfo'>Выбрано: 12 · 640 МБ</span><span class='pfw-flex'></span>"
            "<button class='pfw-delsel'>" + L["del"] + "</button></div>"
            "</section></div></div><pre id='__res'></pre><script>"
            "function measure(){var o={ok:true,fails:[]};function bad(m){o.ok=false;o.fails.push(m);}"
            "var ws=document.getElementById('ws'),side=document.getElementById('side'),"
            "ph=document.getElementById('ph'),pb=document.getElementById('pb'),"
            "pbody=document.getElementById('pbody'),psel=document.getElementById('psel');"
            "var btns=[].slice.call(document.querySelectorAll('.pfw-btn,.pfw-stab,.pfw-delsel,.pfw-crumb'));"
            "btns.forEach(function(b,i){if(b.scrollWidth>b.clientWidth+2)bad('btn#'+i+' hoverflow');"
            "if(b.scrollHeight>b.clientHeight+3)bad('btn#'+i+' voverflow');});"
            "var de=document.documentElement;"
            "if(de.scrollWidth>de.clientWidth+2)bad('page hscroll '+de.scrollWidth+'>'+de.clientWidth);"
            "var rB=pbody.getBoundingClientRect(),rW=ws.getBoundingClientRect(),rS=side.getBoundingClientRect();"
            "if(rB.height<100)bad('body too small '+Math.round(rB.height));"
            "if(pbody.scrollHeight<=pbody.clientHeight)bad('body does not scroll (40 rows)');"
            "if(rS.width<300)bad('sidebar collapsed');"
            "if(rW.left<rS.right-2)bad('workspace overlaps sidebar');"
            "var rH=ph.getBoundingClientRect(),rSel=psel.getBoundingClientRect();"
            # selbar видима либо достижима ВНУТРЕННЕЙ прокруткой workspace (extreme-zoom fallback)
            "if(rSel.bottom>rW.bottom+2 && ws.scrollHeight<=ws.clientHeight+2)bad('selbar clipped');"
            "if(ph.scrollWidth>ph.clientWidth+2)bad('head content overflow');"
            "if(pb.scrollWidth>pb.clientWidth+2)bad('bar content overflow');"
            "o.bodyH=Math.round(rB.height);return o;}"
            "document.getElementById('__res').textContent='@@RES@@'+JSON.stringify(measure())+'@@END@@';"
            "</script></body></html>")


def run_pfw_layout(td, langv, bz, w, h, idx):
    pg = os.path.join(td, "pfw_%s_%s_%d.html" % (langv, str(bz), idx))
    io.open(pg, "w", encoding="utf-8", newline="\n").write(pfw_page(langv, bz))
    prof = os.path.join(td, "prof%d" % idx)
    # Alpha 2.834: Edge 150 не отдаёт DOM по --dump-dom (headless detached) -> CDP.
    dom = _edge_dom.dump_dom_compatible(EDGE, "file:///" + pg.replace("\\", "/"), prof,
                                        window_size=(w, h), budget_ms=4000)
    m = re.search(r"@@RES@@(\{.*?\})@@END@@", dom, re.S)
    return json.loads(m.group(1)) if m else None


L_CASES = [("90a. RU 1440x900 zoom100", "ru", 1.0, 1440, 900), ("90b. RU zoom125", "ru", 1.25, 1440, 900),
           ("90c. RU zoom150", "ru", 1.5, 1440, 900), ("90d. RU zoom175", "ru", 1.75, 1440, 900),
           ("90e. RU zoom200", "ru", 2.0, 1440, 900), ("91. RU узкое 1100x700", "ru", 1.0, 1100, 700),
           ("92. EN 1366x768 + zoom150", "en", 1.5, 1366, 768)]
if not EDGE:
    for lbl, *_ in L_CASES:
        check("L.%s" % lbl, False, _ENGINE_WHY)
else:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_pfw_lay_") as _ltd:
        for _i, (lbl, lv, bz, w, h) in enumerate(L_CASES):
            R = run_pfw_layout(_ltd, lv, bz, w, h, _i)
            if R is None:
                check("L.%s" % lbl, False, "нет ответа рендера")
                continue
            check("L.%s (body=%s)" % (lbl, R.get("bodyH")), bool(R.get("ok")), "; ".join(R.get("fails", [])))

# ════════════════════════════════════════════════════════════════════════════
section("SETTINGS (95-101)")

check("95. read flag существует (настройка printer_files_read_enabled, default on)",
      "printer_files_read_enabled" in SRV and S.PRINTER_FILE_READ_ENABLED_DEFAULT is True
      and NS["_pf_read_enabled"]() is True)
check("96. delete flag default false (константа + рантайм-хелпер)",
      S.PRINTER_FILE_DELETE_ENABLED_DEFAULT is False
      and (lambda: (_settings.pop("printer_files_delete_enabled", None), NS["_pf_delete_enabled"]())[1])() is False)
check("97. только admin меняет delete flag (pf_settings_set начинается с _require_system_admin; "
      "карточка настроек под can('admin'))",
      "_require_system_admin(req)" in fn_src("pf_settings_set")
      and "pfSetFlag('delete_enabled'" in INDEXHTML
      and re.search(r'v-if="can\(\'admin\'\)"[^>]*>.{0,400}Файлы принтеров', INDEXHTML.replace("\n", " ")) is not None)
check("98. config write atomic (литеральные ключи + _set_setting UPSERT+commit, строгий boolean)",
      "_set_setting('printer_files_read_enabled', '1' if v else '0')" in fn_src("pf_settings_set")
      and "_set_setting('printer_files_delete_enabled', '1' if v else '0')" in fn_src("pf_settings_set")
      and "isinstance(v, bool)" in fn_src("pf_settings_set"))
# Считаем ИДЕНТИФИКАТОРЫ, а не прозу докстрингов (свои же комментарии — не улика).
_pf_set_src = fn_src("pf_settings_set") + fn_src("_pf_delete_impl")
check("99/100. флаги не включают DISPATCH/TRANSPORT (нет присваиваний/чтений этих флагов)",
      not re.search(r"DISPATCH_ENABLED\s*=|_orch\.DISPATCH|TRANSPORT_ENABLED\s*=|_orch\.TRANSPORT", _pf_set_src))
check("101. флаг не меняет LAN/AUTH/port (пишутся только ключи printer_files_*)",
      "lan_access" not in _pf_set_src and "server_port" not in _pf_set_src
      and "_SECURITY_ENABLED" not in _pf_set_src and "_prepare_port_change" not in _pf_set_src
      and sorted(re.findall(r"_set_setting\('([a-z_]+)'", fn_src("pf_settings_set")))
      == ["printer_files_delete_enabled", "printer_files_read_enabled"])

# ════════════════════════════════════════════════════════════════════════════
section("AUDIT (102-107)")

_ok_audit = [a for a in _audit_rec if a["action"] == "printer_files_delete" and a["result"].startswith("ok:")]
check("102. success записывается в аудит (printer_files_delete ok:basename)",
      any(a["result"] == "ok:zz.gcode" for a in _ok_audit))
check("103. отказ по защите не пишет секретов (нет token/пути в записях)",
      all(SECRET not in json.dumps(a) for a in _audit_rec))
check("104. path не записывается (в target только printer_id; в result только basename)",
      all("/" not in a["result"] and chr(92) not in a["result"] for a in _audit_rec)
      and all(a["target"] in ("p_b", "p_k", "p_f") or "=" in a["target"] for a in _audit_rec))
check("105. credentials не записываются в лог (sentinel-код отсутствует во всех строках)",
      all(SECRET not in l for l in _log_rec))
check("106. bulk result агрегирован (status partial + deleted/failed счётчики)",
      _bulk["deleted"] == 1 and _bulk["failed"] == 1)
check("107. list refresh не создаёт log storm (листинг не пишет INFO-строк)",
      not any("[PF]" in l and "удал" not in l for l in _log_rec))

# ════════════════════════════════════════════════════════════════════════════
section("REGRESSION (108-125)")

check("108. Bambu stop fix 2.820 сохраняется (BAMBU_CANCEL_HMS)", "BAMBU_CANCEL_HMS" in HEALTH)
check("109. Diagnostics 2.821 сохраняется (группы toolbar)",
      "diag-view-options" in INDEXHTML and "diag-actions-group" in INDEXHTML)
check("110. Project thumbnails 2.822 сохраняются (p2ed-thumb + резолверы)",
      INDEXHTML.count('class="p2ed-thumb"') == 2 and "const p2PartThumb" in APPJS)
check("111. Workspace height сохраняется (leftColH на всех трёх экранах)",
      INDEXHTML.count(':style="{ height: leftColH }"') >= 2)
check("112. Nested modal stack сохраняется (fm-overlay-root)",
      "fm-overlay-root" in INDEXHTML)
check("113. Restart E2E сохраняется (restart_supervisor + restart_cli)",
      "from app import restart_supervisor" in SRV and "restart_cli" in SRV)
check("114. Port management сохраняется (POST /api/network + server_port)",
      '@app.post("/api/network")' in SRV and "server_port" in SRV)
check("115. Module management сохраняется (/api/modules)", "/api/modules" in SRV)
check("116. printer telemetry сохраняется (p_states пишется адаптерами, g_files не тронут)",
      'def g_files(pid: str)' in SRV and "p_states[pid]" in SRV)
check("117. DB schema не меняется (нет новых CREATE TABLE/ALTER для файлового менеджера)",
      "printer_files" not in "".join(re.findall(r"CREATE TABLE[^\)]*\)", SRV))
      and "ALTER TABLE" not in fn_src("_pf_delete_impl"))
check("118. routes зарегистрированы в policy (5 маршрутов в реестре, source=server.py)",
      all(('/api/printer-files/' + p) in open(os.path.join(REPO, "app", "route_policy_registry.py"),
                                              encoding="utf-8").read()
          for p in ("capabilities", "storages", "list", "delete", "settings")))
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
_mods = {m: (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(open(os.path.join(REPO, "modules", m, "module.json"), encoding="utf-8")))
         for m in ("inventory", "cost", "quality")}
#  Склад поднят до 1.7.28 (2.946), качество до 0.2.3 (2.964); ранее 1.7.27 в 2.890-2.891: он научился видеть подачу CFS у Creality K2.
#  3.0: cost — «Расчёт заказа» 0.2.0 на месте удалённой «Себестоимости печати» (слово владельца).
check("119. Module ZIP/версии не меняются (1.7.29/0.2.0/0.2.3)",
      _mods == {"inventory": "1.7.29", "cost": "0.2.0", "quality": "0.2.3"}, _mods)
check("120. DISPATCH_ENABLED false", re.search(r"^DISPATCH_ENABLED = False\s*$", ORCH, re.M) is not None)
check("121. TRANSPORT_ENABLED false", re.search(r"^TRANSPORT_ENABLED = False\s*$", ORCH, re.M) is not None)
check("122. реальные printer commands отсутствуют (пакет без сетевых импортов: ftplib/"
      "urllib.request/socket/http.client; ни одного сокета за прогон; urllib.parse — чистые строки)",
      not any(re.search(r"^\s*(import|from) (ftplib|socket|http\.client|requests)\b|urllib\.request", src, re.M)
              for src in PF_SRC.values()) and not _SOCKETS)
check("123. `_incoming/` не используется", not any("_incoming" in s for s in PF_SRC.values())
      and "_incoming" not in fn_src("_pf_delete_impl"))
check("124. test artifacts отсутствуют (tools/_e2e_payload.json нет)",
      not os.path.isfile(os.path.join(REPO, "tools", "_e2e_payload.json")))
_tmp_probe = tempfile.mkdtemp(prefix="fm_pf_probe_")
os.rmdir(_tmp_probe)
check("125. temp-root удаляется (все TemporaryDirectory закрыты контекстами)",
      not os.path.exists(_tmp_probe))

section("2.824 РЕГРЕССИЯ ДЕФЕКТА: workspace-placement + FlashForge shared read + render")

# ── Placement: секция файлов принтеров ДОЛЖНА быть внутри .main-cols, как settings/diag.
#    Прежний дефект: секция стояла ПОСЛЕ закрытия .main-cols (sibling), из-за чего при
#    открытии правая рабочая область оставалась пустой (main скрыт, секция вне flex-строки).
from html.parser import HTMLParser as _HP


def _section_parents():
    s = INDEXHTML.find('<div id="app"')
    depth = 0
    end = -1
    for m in re.finditer(r"<div\b|</div>", INDEXHTML[s:]):
        if m.group(0) == "</div>":
            depth -= 1
            if depth == 0:
                end = s + m.end()
                break
        else:
            depth += 1
    tpl = INDEXHTML[s:end]
    _VOID = {"img", "br", "hr", "input", "meta", "link", "source", "area", "col", "use",
             "path", "circle", "rect", "line", "polyline", "polygon", "stop", "ellipse"}

    class _P(_HP):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack = []
            self.parents = {}

        def handle_starttag(self, tag, attrs):
            cls = dict(attrs).get("class", "") or ""
            for t in ("projects-pane", "fm-settings-workspace", "fm-diagnostics-workspace",
                      "fm-printer-files-workspace"):
                if t in cls and t not in self.parents:
                    self.parents[t] = " ".join(x[1] for x in self.stack[-1:])
            if tag not in _VOID:
                self.stack.append((tag, cls))

        def handle_endtag(self, tag):
            for j in range(len(self.stack) - 1, -1, -1):
                if self.stack[j][0] == tag:
                    del self.stack[j:]
                    break

    p = _P()
    p.feed(tpl)
    return p.parents


_par = _section_parents()
check("R1/4-6. секция файлов принтеров вложена в .main-cols (как settings/diagnostics/projects)",
      "main-cols" in _par.get("fm-printer-files-workspace", "")
      and "main-cols" in _par.get("fm-settings-workspace", "")
      and "main-cols" in _par.get("fm-diagnostics-workspace", "")
      and "main-cols" in _par.get("projects-pane", ""))
# все четыре области — в одном контейнере (единый workspace-слот)
check("R1b. все workspace-области в ОДНОМ контейнере .main-cols (единый flex-слот)",
      len(set(v.split()[0] if v else "" for v in _par.values())) == 1
      and (list(_par.values())[0] or "").split()[0] == "main-cols")

# ── Header всегда виден: .pfw-head НЕ внутри v-if/v-else внутри секции (иначе ошибка -> пусто).
_sec_i = INDEXHTML.find('<section v-if="showPrinterFiles"')
_sec = INDEXHTML[_sec_i:INDEXHTML.find("</section>", _sec_i)]
# внутренность секции — ПОСЛЕ её открывающего тега (её собственный v-if="showPrinterFiles"
# — это workspace-гейт, как у settings/diag, и он ОЖИДАЕМ; проверяем, что ВНУТРИ секции
# перед header нет доп. гейтов, т.е. header виден всегда, как только секция смонтирована).
_sec_open_end = _sec.find(">") + 1
_head_i = _sec.find('<div class="pfw-head"')
_before_head = _sec[_sec_open_end:_head_i]
_head_tag = _sec[_head_i:_sec.find(">", _head_i) + 1] if _head_i >= 0 else ""
check("7-8/R. header (.pfw-head) виден всегда: перед ним нет гейтов И сам тег .pfw-head без v-if/v-show",
      _head_i > _sec_open_end and _before_head.strip() == ""
      and "v-if" not in _before_head and "v-show" not in _before_head and '<pre' not in _before_head
      and "v-if" not in _head_tag and "v-show" not in _head_tag)
check("R. тело секции покрывает ВСЕ состояния (loading/idle/unsupported/offline/nostorage/error/empty/table)",
      all(("pfState==='%s'" % s) in _sec for s in ("loading", "idle", "unsupported", "offline", "nostorage", "error", "empty")))

# ── FlashForge: единый низкоуровневый чтец; оба вызывающих идут через него (ЭТАП 6).
_ff_helper = fn_src("_flashforge_gcode_list")
check("9/R. единый чтец _flashforge_gcode_list определён один раз и делает POST /gcodeList",
      SRV.count("def _flashforge_gcode_list(") == 1 and "/gcodeList" in _ff_helper)
check("9b/R. старая выпадашка _flashforge_files ИДЁТ через общий чтец (не свой запрос)",
      "_flashforge_gcode_list(" in fn_src("_flashforge_files")
      and "urlopen" not in fn_src("_flashforge_files"))
check("12/R. новый provider _pf_ff_list ИДЁТ через тот же общий чтец (не свой запрос)",
      "_flashforge_gcode_list(" in fn_src("_pf_ff_list")
      and "urlopen" not in fn_src("_pf_ff_list"))
check("R. запрос /gcodeList формируется РОВНО в одном месте (нет двух реализаций)",
      SRV.count('+ "/gcodeList"') == 1 and SRV.count('"/gcodeList"') == 1)

# ── FlashForge provider контракт (list-only, delete unsupported) — исполнение.
_ff_caps = REG.capabilities({"id": "f", "type": "flashforge", "has_credentials": True})
check("13-15/R. FlashForge: supported, list_files, delete_files=false (unsupported delete)",
      _ff_caps.supported and _ff_caps.list_files and not _ff_caps.delete_files
      and _ff_caps.storage_types == (M.STORAGE_INTERNAL,))
_ff_entries = pf_list_impl("p_f", "internal", "", True, None, None)
_cube = next((e for e in _ff_entries.get("entries", []) if e["name"] == "a.gcode"), None)
check("10-12/R. FlashForge list через provider отдаёт файлы (name, category program, size/date None)",
      _ff_entries["status"] == "ok" and _cube is not None and _cube["category"] == "program"
      and _cube["size_bytes"] is None and _cube["modified_at"] is None and not _cube["deletable"]
      and _cube["protected_reason"] in ("unsupported", "read_only"))

# ── Реальный Edge render harness: изолированное монтирование секции + pf-логики.
def _render_harness(fresh_state=True):
    css_href = "file:///" + os.path.join(REPO, "web", "app.css").replace("\\", "/")
    vue_href = "file:///" + os.path.join(REPO, "web", "vendor", "vue.esm-browser.js").replace("\\", "/")
    i0 = APPJS.find("    const showPrinterFiles = ref(false);")
    i1 = APPJS.find("const closePrinterFiles = () => { showPrinterFiles.value = false; _pfGen++; };")
    pf_block = APPJS[i0:i1 + len("const closePrinterFiles = () => { showPrinterFiles.value = false; _pfGen++; };")]
    si = INDEXHTML.find('<section v-if="showPrinterFiles"')
    section_html = INDEXHTML[si:INDEXHTML.find("</section>", si) + len("</section>")]
    pf_names = ("showPrinterFiles, openPrinterFiles, closePrinterFiles, pfPrinterId, pfSelectPrinter, pfStorages, "
                "pfStorageId, pfSelectStorage, pfStorage, pfPath, pfCrumbTo, pfOpenDir, pfEntries, pfRowsView, "
                "pfState, pfReason, pfReasonText, pfSearch, pfCat, pfAge, pfSortKey, pfSortDir, pfSetSort, "
                "pfSelected, pfToggleSel, pfSelectShown, pfClearSel, pfPresetOldPrograms, pfSummary, pfBusy, "
                "pfDeleteBusy, pfRefresh, pfDeleteOne, pfDeleteSelected, pfDeleteAllowed, pfCaps, pfCapsResp, "
                "pfFmtSize, pfFmtDate, pfCatText, pfFlags, "
                "pfSelectable, pfRowClick, pfPrintTarget, pfPrintBlockReason, pfActionBusy, pfSelectForPrint, pfPrintNow, "
                "pfRowMenu, pfRowMenuFor, pfRowMenuClose, pfRowMenuAct, pfStatusText, pfStatusTitle, pfShowSize, pfShowDate, pfMetaNote, "
                #  2.989: предпросмотр файла — кнопка в строке и окно с картинкой.
                "pfPreview, pfCanPreview, pfPreviewOpen, pfPreviewClose")
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<script>window.__e=[];var _c=console.error;console.error=function(){window.__e.push(Array.from(arguments).map(String).join(' '));_c.apply(console,arguments)};"
            "window.addEventListener('error',function(e){window.__e.push('onerror:'+e.message)});"
            "window.addEventListener('unhandledrejection',function(e){window.__e.push('reject:'+String((e.reason&&e.reason.message)||e.reason))});"
            "function J(o){return{ok:true,status:200,json:function(){return Promise.resolve(o)}}}"
            "window.fetch=function(u){u=String(u);"
            "if(u.indexOf('capabilities')>=0)return Promise.resolve(J({status:'ok',read_enabled:true,delete_enabled:false,delete_ui_allowed:false,capabilities:{supported:true,list_files:true,delete_files:false,browse_directories:false,adapter:'flashforge',storage_types:['internal'],reason:''},printer:{id:'node_ff',name:'FFA5M-1',type:'flashforge'}}));"
            "if(u.indexOf('storages')>=0)return Promise.resolve(J({status:'ok',storages:[{storage_id:'internal',display_name:'Память принтера',type:'internal',writable:false,online:true,total_bytes:null,free_bytes:null}]}));"
            "if(u.indexOf('/list')>=0)return Promise.resolve(J({status:'ok',total:1,cursor_next:null,entries:[{file_ref:'pfr_x',name:'Cube_PETG_25m30s.gcode',is_directory:false,category:'program',timelapse:false,extension:'.gcode',size_bytes:null,modified_at:null,storage_id:'internal',deletable:false,protected_reason:'unsupported',active_print:false}]}));"
            "return Promise.resolve(J({}))};"
            "window.confirm=function(){return true};window.alert=function(){};</script>"
            "<link rel='stylesheet' href='" + css_href + "'>"
            "<script type='importmap'>{\"imports\":{\"vue\":\"" + vue_href + "\"}}</script>"
            "<style>html,body{margin:0}.left-col{width:360px;flex:0 0 auto;background:#222}"
            ".main-cols{display:flex;height:600px;width:1200px;gap:8px}main.projects-pane{flex:1 1 auto}</style>"
            "</head><body><div id='app'>"
            "<div class='main-cols'>"
            "<div class='left-col'></div>"
            "<main class='projects-pane' v-show=\"workspaceView==='projects'\">PROJECTS_AREA</main>"
            + section_html +
            "</div></div><div id='fm-overlay-root'></div><pre id='__res'></pre>"
            "<script type='module'>"
            "import { createApp, ref, reactive, computed, nextTick } from 'vue';"
            "const SvgIcon={props:['name','sw','class'],template:'<span class=\"svg-stub\"></span>'};"
            "const app=createApp({setup(){"
            "const lang=ref('ru');const tr=(s)=>s;"
            "const printers=ref([{id:'node_ff',name:'FFA5M-1',type:'flashforge',model:'AD5M',credential_configured:true}]);"
            "const showSettings=ref(false),showDiag=ref(false);const leftColH='600px';"
            #  Alpha 2.900: openPrinterFiles уводит и «Отчёты» — четвёртый рабочий экран в том же
            #  слоте. Без этих двух строк стенд падает на ReferenceError ещё при монтировании.
            "const showReports=ref(false);const closeReports=()=>{showReports.value=false};"
            "const closeDiagnostics=()=>{showDiag.value=false};const closeSettings=()=>{showSettings.value=false};"
            "const wsData=ref({node_ff:{status:'IDLE'}});const sendReserved=ref(new Set());"
            "const cellBusy=(pid)=>((wsData.value[pid]||{}).status==='RUNNING')||sendReserved.value.has(pid);"
            "window.__toasts=[];const pushToast=(t,k)=>window.__toasts.push(String(t));"
            "const _printerNameOf=(pid)=>pid;const handleSendResp=(resp,ctx)=>((resp&&resp.accepted)?'accepted':'other');"
            "window.__printStarts=[];const openPrintStart=(ctx)=>window.__printStarts.push(ctx);"
            "const activeModalPrinterId=ref('');const printerFiles=ref([]);const printFileName=ref('');"
            + pf_block +
            ";const workspaceView=computed(()=>showSettings.value?'settings':(showDiag.value?'diagnostics':(showPrinterFiles.value?'printerFiles':'projects')));"
            "window.__ss={openPrinterFiles,closePrinterFiles,workspaceView,showPrinterFiles,pfState};"
            "return { lang, tr, printers, showSettings, showDiag, leftColH, workspaceView, " + pf_names + " };"
            "}});app.component('SvgIcon',SvgIcon);app.mount('#app');"
            "(async()=>{const sl=(m)=>new Promise(r=>setTimeout(r,m));const rv=(r)=>r&&'value'in r?r.value:r;"
            "const out={};const ss=window.__ss;"
            "out.wvInitial=rv(ss.workspaceView);"
            "ss.openPrinterFiles('node_ff');"
            "for(let i=0;i<80;i++){const s=rv(ss.pfState);if(['ready','empty','error','unsupported','offline'].indexOf(s)>=0)break;await sl(50);}"
            "await sl(150);await nextTick();"
            "const ws=document.querySelector('.fm-printer-files-workspace');"
            "out.wvAfter=rv(ss.workspaceView);out.pfState=rv(ss.pfState);"
            "out.wsExists=!!ws;out.wsVisible=!!(ws&&ws.offsetWidth>200&&ws.offsetHeight>100);"
            "out.headVisible=!!(document.querySelector('.pfw-head')&&document.querySelector('.pfw-head').offsetHeight>0);"
            "out.headText=(document.querySelector('.pfw-title')||{}).textContent||'';"
            "out.hasCube=(ws?ws.textContent:'').indexOf('Cube_PETG_25m30s.gcode')>=0;"
            "out.mainHidden=(function(){var m=document.querySelector('main.projects-pane');return m?getComputedStyle(m).display==='none':null})();"
            "const main0=document.querySelector('main.projects-pane');"
            "const x=document.querySelector('.pfw-x');if(x)x.click();await sl(120);await nextTick();"
            "out.afterClose_wsExists=!!document.querySelector('.fm-printer-files-workspace');"
            "out.afterClose_wv=rv(ss.workspaceView);"
            "out.afterClose_mainShown=(function(){var m=document.querySelector('main.projects-pane');return m?getComputedStyle(m).display!=='none':null})();"
            "out.errors=(window.__e||[]).filter(e=>e.indexOf('favicon')<0).slice(0,6);"
            "document.getElementById('__res').textContent='@@R@@'+JSON.stringify(out)+'@@E@@';document.title='ready';})();"
            "</script></body></html>")
    return html


if not EDGE:
    for _n in ("R-render.mount", "R-render.visible", "R-render.cube", "R-render.close", "R-render.noerr"):
        check(_n, False, _ENGINE_WHY)
else:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_pf824_") as _rtd:
        _pg = os.path.join(_rtd, "r.html")
        io.open(_pg, "w", encoding="utf-8", newline="\n").write(_render_harness())
        _prof = os.path.join(_rtd, "p")
        # Alpha 2.834: Edge 150 не отдаёт DOM по --dump-dom (headless detached) -> CDP.
        _dom = _edge_dom.dump_dom_compatible(EDGE, "file:///" + _pg.replace("\\", "/"), _prof,
                                             window_size=(1300, 800), budget_ms=12000)
        _m = re.search(r"@@R@@(\{.*?\})@@E@@", _dom, re.S)
        _R = json.loads(_m.group(1)) if _m else {}
        check("R-render.mount. изолированный Vue-стенд смонтировался и открыл workspace",
              bool(_R) and _R.get("wvAfter") == "printerFiles", str(_R)[:200])
        check("R-render.visible. workspace ВИДИМ (не пустая правая область): секция + header с размерами",
              _R.get("wsExists") and _R.get("wsVisible") and _R.get("headVisible")
              and "Файлы принтеров" in (_R.get("headText") or ""), str(_R)[:200])
        check("R-render.mainHidden. основной экран проектов скрыт, пока открыт workspace",
              _R.get("mainHidden") is True)
        check("R-render.cube. FlashForge-файл Cube_PETG_25m30s.gcode ОТОБРАЖАЕТСЯ в списке",
              _R.get("hasCube") is True and _R.get("pfState") == "ready")
        check("R-render.close. закрытие возвращает Projects (секция убрана, main показан)",
              _R.get("afterClose_wsExists") is False and _R.get("afterClose_wv") == "projects"
              and _R.get("afterClose_mainShown") is True)
        check("R-render.noerr. рендер без console errors / необработанных исключений",
              not _R.get("errors"), str(_R.get("errors"))[:200])

# ── Границы 2.824: другие адаптеры и предохранители не тронуты
check("R. Bambu provider не изменён (delete_safe_during_print False, list+delete)",
      REG.capabilities(P_BAMBU).delete_files and BambuFileProvider(lambda pid: None).delete_safe_during_print is False)
check("R. Moonraker provider не изменён (usage + delete)",
      REG.capabilities(P_KLIP).read_storage_usage and REG.capabilities(P_KLIP).delete_files)
check("R. delete-предохранитель по-прежнему выключен по умолчанию",
      S.PRINTER_FILE_DELETE_ENABLED_DEFAULT is False)

# ── Sentinel ─────────────────────────────────────────────────────────────────
check("S1. sentinel отсутствует в production-исходниках",
      all(SENTINEL not in s for s in (SRV, APPJS, INDEXHTML, APPCSS, ORCH, HEALTH))
      and all(SENTINEL not in s for s in PF_SRC.values()))
check("S2. sentinel определён один раз в оснастке теста", OWN.count(SENTINEL) == 1)
check("S3. sentinel не утёк в аудит/лог/ответы (см. 50/103/105)",
      SENTINEL not in json.dumps(_audit_rec) and SENTINEL not in "".join(_log_rec))

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if SKIPPED:
    print("ПРОПУЩЕНО %d: %s" % (len(SKIPPED), ", ".join(SKIPPED)))
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _DONE["ok"] = True
    sys.exit(1)
print("PASS: файловый менеджер принтеров — все %d проверок пройдены; server.py не импортирован (AST); "
      "провайдеры исполнены с фейковыми транспортами; UI-блок исполнен в Node; раскладка измерена в Edge"
      % _total)
_DONE["ok"] = True
sys.exit(0)
