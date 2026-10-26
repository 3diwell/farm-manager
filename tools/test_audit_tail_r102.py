# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-102 — хвост находок сплошной проверки кода (три оставшиеся названные находки).

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ.
  1. Bambu FTP: соединение закрывается на ЛЮБОМ исходе — в списке файлов принтера (g_files),
     в менеджере файлов принтера (_pf_ftp_factory) и в загрузке 3mf перед запуском C1
     (_c1_load_plate_compat). Раньше при сорванном входе сокет TLS висел до сборки мусора.
     После ошибки — close() без QUIT; замок отпускается последним.
  2. Выгрузка проектов (GET /api/projects2/export): адреса файлов на диске получает только
     роль с правом project; наблюдателю колонка file_path отдаётся пустой, формат не меняется.
  3. Превью файла на принтере Klipper: метка «превью нет» (.miss) действует ограниченный срок,
     а не навсегда.

server.py НЕ импортируется (правило проекта): функции вырезаются разбором исходника и
исполняются в изолированном пространстве имён со стабами. Сети и принтеров набор не трогает.
"""
import ast
import io
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = "AUDIT_TAIL_R102_SENTINEL"
PASS = FAIL = 0


def check(name, ok, extra=None):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("   [%r]" % (extra,)) if extra is not None else ""))


SRC = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8", errors="replace").read()
TREE = ast.parse(SRC)
FUNCS = {}
ASSIGNS = {}
for _n in TREE.body:
    if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FUNCS.setdefault(_n.name, ast.get_source_segment(SRC, _n))
    elif isinstance(_n, ast.Assign) and len(_n.targets) == 1 and isinstance(_n.targets[0], ast.Name):
        ASSIGNS.setdefault(_n.targets[0].id, ast.get_source_segment(SRC, _n))


def body(name):
    return FUNCS.get(name) or ""


def load(name, ns):
    src = body(name)
    if not src:
        return None
    exec(compile(src, "<server.py:%s>" % name, "exec"), ns)
    return ns[name]


class _Log:
    def __getattr__(self, _):
        return lambda *a, **k: None


class _RecLock:
    """Замок, записывающий порядок событий в общий журнал EV."""
    def __init__(self, ev):
        self.ev = ev
        self._lk = threading.Lock()

    def acquire(self, *a, **k):
        self.ev.append("acquire")
        return self._lk.acquire(*a, **k)

    def release(self):
        self.ev.append("release")
        self._lk.release()

    def locked(self):
        return self._lk.locked()


def make_ftp(ev, fail_on=None, nlst_map=None, payload=b""):
    """Фальшивый ImplicitFTP_TLS: пишет вызовы в EV, бросает на шаге fail_on."""
    class F:
        def _step(self, name):
            ev.append(name)
            if name == fail_on:
                raise OSError("fake %s failure" % name)

        def connect(self, *a, **k): self._step("connect")
        def login(self, *a, **k): self._step("login")
        def prot_p(self): self._step("prot_p")
        def set_pasv(self, *a, **k): self._step("set_pasv")

        def nlst(self, d):
            self._step("nlst")
            if nlst_map is None or d not in nlst_map:
                raise OSError("no dir")
            return list(nlst_map[d])

        def retrbinary(self, cmd, cb):
            self._step("retrbinary")
            cb(payload)

        def quit(self): self._step("quit")
        def close(self): ev.append("close")
    return F


# ════════════════════════════════════════════════════════════════════════════
print("--- 1. Bambu FTP: список файлов принтера (g_files) ---")


class _Cur:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class _Conn:
    def __init__(self, row): self.row = row
    def execute(self, *a, **k): return _Cur(self.row)


BAMBU_ROW = {"id": "b1", "type": "bambu", "ip": "192.0.2.10", "token": "FIXTURE_CODE", "port": None}


def run_g_files(ev, ftp_cls):
    lk = _RecLock(ev)
    ns = {"lock_pr": threading.Lock(), "conn_pr": _Conn(BAMBU_ROW), "_demo": None,
          "urllib": None, "json": None, "log": _Log(), "_exc_brief": lambda: "e",
          "_ftp_lock": lambda ip: lk, "ImplicitFTP_TLS": ftp_cls,
          "_flashforge_files": lambda *a: []}
    fn = load("g_files", ns)
    return fn("b1"), lk


check("1. g_files найден в исходнике", bool(body("g_files")))
_ev = []
_res, _lk = run_g_files(_ev, make_ftp(_ev, fail_on="login"))
check("2. сорванный вход: ответ — пустой список", _res == [], _res)
check("3. сорванный вход: соединение закрыто ровно один раз", _ev.count("close") == 1, _ev)
check("4. сорванный вход: QUIT по битому каналу не посылается", "quit" not in _ev, _ev)
check("5. сорванный вход: замок свободен и отпущен ПОСЛЕ закрытия",
      not _lk.locked() and _ev[-2:] == ["close", "release"], _ev)
_ev = []
_res, _lk = run_g_files(_ev, make_ftp(_ev, fail_on="prot_p"))
check("6. сбой prot_p: соединение закрыто, замок свободен",
      _res == [] and _ev.count("close") == 1 and not _lk.locked(), _ev)
_ev = []
_res, _lk = run_g_files(_ev, make_ftp(_ev, nlst_map={"/": ["b.3mf", "a.gcode", "x.txt"],
                                                      "/cache": ["/cache/c.3mf"]}))
check("7. удачный путь: список файлов отсортирован, лишнее отброшено",
      _res == ["a.gcode", "b.3mf", "cache/c.3mf"], _res)
check("8. удачный путь: quit выполнен, затем сокет закрыт, замок свободен",
      _ev.count("quit") == 1 and "close" in _ev and _ev.index("quit") < _ev.index("close")
      and _ev[-1] == "release" and not _lk.locked(), _ev)

# ════════════════════════════════════════════════════════════════════════════
print("--- 2. Bambu FTP: менеджер файлов принтера (_pf_ftp_factory) ---")


class _PfError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


_PF_MODELS = types.SimpleNamespace(REASON_BAD_REQUEST="bad_request", REASON_NO_CREDENTIALS="no_credentials",
                                   REASON_FILE_BUSY="file_busy", REASON_TIMEOUT="timeout",
                                   REASON_CONNECTION_LOST="connection_lost")


def run_factory(ev, ftp_cls):
    lk = _RecLock(ev)
    ns = {"_pf_printer_row": lambda pid: BAMBU_ROW, "_PfError": _PfError, "_pf_models": _PF_MODELS,
          "_ftp_lock": lambda ip: lk, "ImplicitFTP_TLS": ftp_cls, "socket": __import__("socket"),
          "_PfFtpSession": lambda ftp, l: ("session", ftp, l), "log": _Log()}
    fn = load("_pf_ftp_factory", ns)
    try:
        return fn("b1"), None, lk
    except _PfError as e:
        return None, e.reason, lk


check("9. _pf_ftp_factory найден в исходнике", bool(body("_pf_ftp_factory")))
_ev = []
_res, _reason, _lk = run_factory(_ev, make_ftp(_ev, fail_on="login"))
check("10. сорванный вход: безопасная причина connection_lost", _reason == "connection_lost", _reason)
check("11. сорванный вход: сокет закрыт ровно один раз и до освобождения замка",
      _ev.count("close") == 1 and _ev[-2:] == ["close", "release"] and not _lk.locked(), _ev)
_ev = []
_res, _reason, _lk = run_factory(_ev, make_ftp(_ev))
check("12. удачный вход: сеанс отдан, сокет НЕ закрыт, замок остаётся за сеансом",
      _reason is None and _res and _res[0] == "session" and "close" not in _ev and _lk.locked(), _ev)

# ════════════════════════════════════════════════════════════════════════════
print("--- 3. Bambu FTP: загрузка 3mf перед запуском C1 (_c1_load_plate_compat) ---")
TMPD = tempfile.mkdtemp(prefix="fm_r102_")


def run_c1(ev, ftp_cls):
    lk = _RecLock(ev)
    ns = {"os": os, "io": io, "zipfile": __import__("zipfile"), "TEMP_FILES_DIR": TMPD, "log": _Log(),
          "_exc_brief": lambda: "e", "_ftp_lock": lambda ip: lk, "ImplicitFTP_TLS": ftp_cls,
          "_check_file_compatible": lambda *a: (True, "")}
    fn = load("_c1_load_plate_compat", ns)
    data = types.SimpleNamespace(val="/r102_missing.3mf", force=False)
    return fn("b1", BAMBU_ROW, data), lk


check("13. _c1_load_plate_compat найден в исходнике", bool(body("_c1_load_plate_compat")))
_ev = []
_res, _lk = run_c1(_ev, make_ftp(_ev, fail_on="retrbinary"))
check("14. сбой скачивания: файла нет, плита по умолчанию, запуск не заблокирован",
      _res == (None, "Metadata/plate_1.gcode", None), _res)
check("15. сбой скачивания: сокет закрыт один раз, без QUIT, замок отпущен последним",
      _ev.count("close") == 1 and "quit" not in _ev and _ev[-2:] == ["close", "release"]
      and not _lk.locked(), _ev)
_ev = []
_res, _lk = run_c1(_ev, make_ftp(_ev, fail_on="login"))
check("16. сорванный вход: сокет закрыт, замок свободен",
      _res[0] is None and _ev.count("close") == 1 and not _lk.locked(), _ev)
_zbuf = io.BytesIO()
with __import__("zipfile").ZipFile(_zbuf, "w") as _z:
    _z.writestr("Metadata/plate_2.gcode", "G28\n")
_ev = []
_res, _lk = run_c1(_ev, make_ftp(_ev, payload=_zbuf.getvalue()))
check("17. удачный путь: 3mf скачан, плита найдена, quit до close, замок свободен",
      _res[0] == _zbuf.getvalue() and _res[1] == "Metadata/plate_2.gcode" and _res[2] is None
      and all(x in _ev for x in ("retrbinary", "quit", "close"))
      and _ev.index("retrbinary") < _ev.index("quit") < _ev.index("close") and not _lk.locked(), _ev)
check("18. сигнатура не изменилась (на неё опирается запуск печати)",
      "def _c1_load_plate_compat(pid, p, data):" in SRC and "_c1_load_plate_compat(pid, p, data)" in SRC)

# ════════════════════════════════════════════════════════════════════════════
print("--- 4. Выгрузка проектов: пути на диске только с правом project ---")


class _Resp:
    def __init__(self, content=b"", media_type=None, headers=None, status_code=200):
        self.content = content
        self.media_type = media_type
        self.headers = headers or {}
        self.status_code = status_code


ROLE = {"v": None}
_exp_ns = {"HAS_XLSX": False, "time": time, "io": io, "csv": __import__("csv"), "Response": _Resp,
           "Request": object, "openpyxl": None,
           "_build_projects2_rows": lambda project="": [
               {"project_name": "P", "part_name": "A", "file_name": "a.3mf", "file_path": "C:/x/a.3mf",
                "on_plate_qty": 1},
               {"project_name": "P", "part_name": "B", "file_name": "", "file_path": ""}],
           "_req_role": lambda req: ROLE["v"]}
for _a in ("EXPORT2_COLS", "_ROLE_PERMS"):
    if ASSIGNS.get(_a):
        exec(compile(ASSIGNS[_a], "<server.py:%s>" % _a, "exec"), _exp_ns)
load("_has_perm", _exp_ns)
_export = load("export_projects2", _exp_ns)
check("19. export_projects2, EXPORT2_COLS и _ROLE_PERMS найдены",
      _export is not None and "EXPORT2_COLS" in _exp_ns and "_ROLE_PERMS" in _exp_ns)


def export_as(role):
    ROLE["v"] = role
    try:
        r = _export(object(), project="")
    except TypeError:
        r = _export(project="")      # прежняя сигнатура без request
    return r.content


_csv = {}
for _role in ("observer", "assembler", "operator", "admin", None):
    try:
        _csv[_role] = export_as(_role)
    except Exception as _e:
        _csv[_role] = "ERROR %r" % (_e,)
_hdr = lambda t: t.splitlines()[0] if t and not t.startswith("ERROR") else t
check("20. наблюдателю путь на диске не отдаётся", "C:/x/a.3mf" not in _csv["observer"], _csv["observer"])
check("21. сборщику (без права project) путь не отдаётся", "C:/x/a.3mf" not in _csv["assembler"])
check("22. оператору и администратору путь отдаётся (нужен для повторного импорта)",
      "C:/x/a.3mf" in _csv["operator"] and "C:/x/a.3mf" in _csv["admin"])
check("23. при выключенной защите (роль None) всё как прежде — путь есть", "C:/x/a.3mf" in _csv[None])
check("24. строка заголовка одинакова для всех ролей, колонка FILE_PATH на месте",
      len({_hdr(v) for v in _csv.values()}) == 1 and "FILE_PATH" in _hdr(_csv[None]), {k: _hdr(v) for k, v in _csv.items()})
check("25. у наблюдателя остальные данные на месте (имя файла, деталь)",
      "a.3mf" in _csv["observer"] and ",A," in _csv["observer"])
check("26. право маршрута в карте прав не менялось (GET /api/projects2/export → None)",
      "('GET', '/api/projects2/export', 'export_projects2', 'projects', 'browser', 'OPERATIONAL', ('NONE',), 'NONE', None)"
      in io.open(os.path.join(ROOT, "app", "route_policy_registry.py"), encoding="utf-8").read())

# ════════════════════════════════════════════════════════════════════════════
print("--- 5. Превью файла Klipper: срок у метки «превью нет» ---")
CACHE = tempfile.mkdtemp(prefix="fm_r102_thumb_")
NET = {"n": 0}
PNG = b"\x89PNG\r\n\x1a\n" + b"R102" * 8


class _Raw:
    def __init__(self, b): self.b = b
    def read(self): return self.b


def _urlopen(url, timeout=None):
    NET["n"] += 1
    if "/server/files/metadata" in url:
        return _Raw(b'{"result":{"thumbnails":[{"width":32,"height":32,"relative_path":".thumbs/a.png"}]}}')
    return _Raw(PNG)


_fake_urllib = types.SimpleNamespace(request=types.SimpleNamespace(urlopen=_urlopen), parse=urllib.parse)
_th_ns = {"g_printers": lambda: [{"id": "k1", "type": "klipper", "ip": "192.0.2.20", "port": 7125}],
          "THUMB_CACHE_DIR": CACHE, "os": os, "time": time, "json": __import__("json"),
          "urllib": _fake_urllib, "Response": _Resp,
          "FileResponse": lambda fp, **k: _Resp(content=("FILE", fp), status_code=200), "log": _Log()}
if ASSIGNS.get("_THUMB_MISS_TTL"):
    exec(compile(ASSIGNS["_THUMB_MISS_TTL"], "<server.py:_THUMB_MISS_TTL>", "exec"), _th_ns)
_thumb = load("printer_file_thumb", _th_ns)
_ttl = _th_ns.get("_THUMB_MISS_TTL")
check("27. printer_file_thumb и срок _THUMB_MISS_TTL (1..3600 с) найдены",
      _thumb is not None and isinstance(_ttl, (int, float)) and 0 < _ttl <= 3600, _ttl)
import hashlib as _hl
_key = _hl.md5("k1:dir/part.gcode".encode("utf-8")).hexdigest()
_miss = os.path.join(CACHE, _key + ".miss")
_png = os.path.join(CACHE, _key + ".png")
open(_miss, "wb").close()
NET["n"] = 0
try:
    _r = _thumb("k1", "/dir/part.gcode")
except Exception as _e:
    _r = _Resp(status_code=("ERROR", repr(_e)))
check("28. свежая метка: 404 без обращения к принтеру", _r.status_code == 404 and NET["n"] == 0,
      (_r.status_code, NET["n"]))
_old = time.time() - (float(_ttl or 600) + 1)
os.utime(_miss, (_old, _old))
NET["n"] = 0
try:
    _r = _thumb("k1", "/dir/part.gcode")
except Exception as _e:
    _r = _Resp(status_code=("ERROR", repr(_e)))
check("29. протухшая метка: превью запрошено заново и отдано", _r.status_code == 200 and _r.content == PNG
      and NET["n"] == 2, (_r.status_code, NET["n"]))
check("30. протухшая метка снята, PNG закэширован на диск",
      not os.path.exists(_miss) and os.path.exists(_png) and open(_png, "rb").read() == PNG)
NET["n"] = 0
_r = _thumb("k1", "/dir/part.gcode")
check("31. повторный запрос берётся из кэша без обращения к принтеру",
      _r.status_code == 200 and _r.content == ("FILE", _png) and NET["n"] == 0)
check("32. метка по-прежнему ставится, когда превью у файла нет (запись .miss сохранена)",
      'open(miss_fp, "wb").close()' in body("printer_file_thumb"))

# ════════════════════════════════════════════════════════════════════════════
print("--- 6. Прежние образцы не вернулись ---")
_gf = body("g_files")
check("33. g_files: закрытие в finally перед освобождением замка",
      "ftp.close()" in _gf and _gf.index("finally:") < _gf.index("ftp.close()") < _gf.index("_flk.release()", _gf.index("finally:")))
_c1 = body("_c1_load_plate_compat")
check("34. _c1_load_plate_compat: закрытие в finally перед освобождением замка",
      "_ftp.close()" in _c1 and _c1.index("finally:") < _c1.index("_ftp.close()") < _c1.index("_flk.release()"))
_th = body("printer_file_thumb")
check("35. printer_file_thumb: безусловного «метка есть → 404 навсегда» больше нет",
      "if os.path.exists(miss_fp):\n        return Response(status_code=404)" not in _th and "_THUMB_MISS_TTL" in _th)

shutil.rmtree(TMPD, ignore_errors=True)
shutil.rmtree(CACHE, ignore_errors=True)
print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
