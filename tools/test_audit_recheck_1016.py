# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Аудит 26.09.2026, перепроверка 16.10.2026 (R-142): исправления подтверждённых замечаний.

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ (настоящие функции из server.py, исполненные на временных данных):
  A. config.json: битый файл не затирается молча — рядом остаётся его копия; запись атомарная
     (data-safety-13).
  B. Папка «_removed»: срок хранения считается от удаления, а не от загрузки файла — старый файл,
     удалённый сегодня, не стирается тут же (найдено при разборе data-safety-15).
  C. Ответ на внутреннюю ошибку не несёт текста исключения, только номер для журнала (arch-auth-14).
  D. Тело запроса: не-словарь — пустой словарь; тело входа больше предела не читается
     (arch-auth-10).
  E. Журнал аудита: перевод строки в имени не создаёт поддельную строку (arch-auth-10).
  F. Файлы модуля: «\\», «:» и соседняя папка «web<что-то>» не отдаются (modules-10).
  G. Проверка источника запроса: её сбой закрывает изменяющий запрос (arch-auth-18).
  H. Подсказки окна в форме {ru, en} показывают русский текст (docs-materials-15).

Сервер не запускается, сети нет, рабочая папка данных владельца не трогается.
Запуск: python tools/test_audit_recheck_1016.py   (0 = пройдено)
"""
import ast
import asyncio
import io
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app import server_port_config as _port_cfg  # noqa: E402

fails = []


def check(name, ok, extra=""):
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:500] if (not ok and extra != "") else ""))
    if not ok:
        fails.append(name)


SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)


def fn_src(name):
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            seg = ast.get_source_segment(SRC, node)
            # декораторы маршрутов здесь не нужны — исполняем саму функцию
            return seg
    raise KeyError(name)


class _Log:
    def __init__(self):
        self.lines = []

    def _w(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(" ".join(str(x) for x in a))

    info = debug = warning = error = _w


TMP = tempfile.mkdtemp(prefix="fm_audit1016_")


def sec_A():
    # ── A. config.json ────────────────────────────────────────────────────────────────────────

    print("--- A. config.json ---")
    log = _Log()
    cfg_path = os.path.join(TMP, "config.json")
    NS = {"os": os, "json": json, "time": time, "log": log, "_port_cfg": _port_cfg,
          "_exc_brief": lambda: "", "_config_path": lambda: cfg_path, "_default_data_dir": lambda: TMP}
    exec("_config_bad_seen = set()\n" + "\n\n".join(fn_src(n) for n in (
        "_config_keep_unreadable", "_read_config", "_write_config", "_write_config_atomic")), NS)
    good = {"data_dir": "D:\\Ферма", "server_port": 8123, "lan_access_enabled": True, "modules_disabled": ["x"]}
    check("A1. запись и чтение настроек", NS["_write_config"](good) is True and NS["_read_config"]() == good)
    check("A2. запись атомарная: временного файла не остаётся", not os.path.exists(cfg_path + ".tmp"))
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write('{"data_dir": "D:\\\\Фер')          # обрыв посреди записи
    bad_bytes = open(cfg_path, "rb").read()
    r1 = NS["_read_config"]()
    r2 = NS["_read_config"]()
    copies = [n for n in os.listdir(TMP) if n.startswith("config.json.corrupt-")]
    check("A3. битый config.json читается как пусто, но его копия сохранена рядом — один раз",
          r1 == {} and r2 == {} and len(copies) == 1
          and open(os.path.join(TMP, copies[0]), "rb").read() == bad_bytes, (r1, copies))
    check("A4. в журнал записано, где лежит копия", any("corrupt" in x for x in log.lines), log.lines)
    NS["_write_config"]({"server_port": 8000})
    check("A5. после новой записи битая копия остаётся — прежние настройки можно вернуть руками",
          os.path.isfile(os.path.join(TMP, copies[0])) and NS["_read_config"]() == {"server_port": 8000})



def sec_B():
    # ── B. «_removed»: срок от удаления ───────────────────────────────────────────────────────

    print("--- B. папка «_removed» ---")
    PF, UP, TF = (os.path.join(TMP, d) for d in ("project_files", "slicer_uploads", "temp_files"))
    for d in (PF, UP, TF):
        os.makedirs(d)
    NS = {"os": os, "time": time, "log": _Log(), "_exc_brief": lambda: "",
          "PROJECT_FILES_DIR": PF, "UPLOAD_DIR": UP, "TEMP_FILES_DIR": TF}
    exec("\n\n".join(fn_src(n) for n in ("_unique_dest", "_prune_trash_dir", "_trash_managed_copy")), NS)
    old = os.path.join(UP, "загружен_месяц_назад.gcode")
    with open(old, "wb") as f:
        f.write(b";G1 X1\n")
    month = time.time() - 30 * 86400
    os.utime(old, (month, month))
    dest = NS["_trash_managed_copy"](old)
    check("B1. файл, загруженный месяц назад и удалённый сегодня, лежит в «_removed» (не стёрт чисткой)",
          bool(dest) and os.path.isfile(dest) and not os.path.exists(old), dest)
    stale = os.path.join(UP, "_removed", "удалён_давно.gcode")
    with open(stale, "wb") as f:
        f.write(b"x")
    os.utime(stale, (month, month))
    NS["_prune_trash_dir"](os.path.join(UP, "_removed"))
    check("B2. а пролежавшее в «_removed» дольше 14 дней чистка убирает, свежеудалённое — нет",
          not os.path.exists(stale) and os.path.isfile(dest))



class _Resp:
    def __init__(self, status_code=200, content=None):
        self.status_code, self.content = status_code, content


def sec_C():
    # ── C. ответ на внутреннюю ошибку ─────────────────────────────────────────────────────────

    print("--- C. ответ 500 ---")
    log = _Log()

    class _URL:
        path = "/api/x"

    class _Req:
        method = "POST"
        url = _URL()

    NS = {"log": log, "secrets": secrets, "JSONResponse": _Resp, "Request": object}
    src = fn_src("_unhandled_exception_handler")
    exec(src, NS)
    try:
        raise ValueError("C:\\Users\\Someone\\AppData\\secret.db: SELECT * FROM users")
    except ValueError as e:
        r = asyncio.run(NS["_unhandled_exception_handler"](_Req(), e))
    body = json.dumps(r.content, ensure_ascii=False)
    check("C1. клиенту — 500 без текста исключения, путей и SQL",
          r.status_code == 500 and r.content.get("reason") == "internal_error"
          and "secret.db" not in body and "SELECT" not in body and "ValueError" not in body, body)
    check("C2. номер ошибки в ответе совпадает с номером в журнале",
          bool(r.content.get("ref")) and any(r.content["ref"] in x and "ValueError" in x for x in log.lines),
          (r.content, log.lines))



def sec_D():
    # ── D. тело запроса ───────────────────────────────────────────────────────────────────────

    print("--- D. тело запроса ---")

    class _BReq:
        def __init__(self, raw, clen=None):
            self._raw = raw
            self.headers = {} if clen is None else {"content-length": str(clen)}

        async def json(self):
            return json.loads(self._raw.decode("utf-8"))

        async def body(self):
            return self._raw

    NS = {"json": json}
    exec(fn_src("_json_body") + "\n\n_AUTH_BODY_MAX = 16384\n\n" + fn_src("_json_body_small"), NS)
    jb, jbs = NS["_json_body"], NS["_json_body_small"]
    check("D1. массив в теле — пустой словарь (раньше обработчик падал на .get)",
          asyncio.run(jb(_BReq(b'["a", "b"]'))) == {} and asyncio.run(jb(_BReq(b'{"a": 1}'))) == {"a": 1})
    big = json.dumps({"username": "a" * 50000, "password": "x"}).encode()
    check("D2. тело входа больше 16 КБ не принимается — ни по заголовку длины, ни по факту",
          asyncio.run(jbs(_BReq(big, len(big)))) == {} and asyncio.run(jbs(_BReq(big))) == {})
    ok_body = json.dumps({"username": "admin", "password": "пароль"}).encode()
    check("D3. обычное тело входа читается как прежде; массив — пустой словарь",
          asyncio.run(jbs(_BReq(ok_body, len(ok_body)))) == {"username": "admin", "password": "пароль"}
          and asyncio.run(jbs(_BReq(b"[1]"))) == {})



def sec_E():
    # ── E. журнал аудита ──────────────────────────────────────────────────────────────────────

    print("--- E. журнал аудита ---")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE audit_log (ts, username, action, target, result, ip)")
    log = _Log()
    NS = {"re": re, "time": time, "log": log, "conn_p": conn, "lock_p": threading.RLock()}
    exec(fn_src("_audit"), NS)
    NS["_audit"]("evil\n2026-10-16 [INFO] [audit] user=admin action=login result=ok", "login", "t\r\nx", "fail")
    row = conn.execute("SELECT username, target FROM audit_log").fetchone()
    check("E1. перевод строки в имени не попадает ни в базу аудита, ни в журнал",
          "\n" not in row[0] and "\r" not in row[1] and all("\n" not in x for x in log.lines), (row, log.lines))
    NS["_audit"]("x" * 5000, "login")
    check("E2. длина имени в журнале ограничена",
          len(conn.execute("SELECT username FROM audit_log ORDER BY rowid DESC").fetchone()[0]) == 128)



def sec_F():
    # ── F. файлы модуля ───────────────────────────────────────────────────────────────────────

    print("--- F. файлы модуля ---")
    mdir = os.path.join(TMP, "modules", "demo")
    os.makedirs(os.path.join(mdir, "web"))
    os.makedirs(os.path.join(mdir, "webx"))
    with open(os.path.join(mdir, "web", "panel.js"), "w") as f:
        f.write("export default 1;")
    with open(os.path.join(mdir, "webx", "secret.js"), "w") as f:
        f.write("secret")

    class _R:
        def __init__(self, status_code=200, content=None, media_type=None, headers=None):
            self.status_code, self.content = status_code, content

    class _Pkg:
        @staticmethod
        def asset_ok(pkg, rel, data):
            return True

    NS = {"os": os, "Response": _R, "_loaded_modules": {"demo": {"dir": mdir, "package": None}},
          "_lic_pkg": _Pkg(), "log": _Log()}
    exec(fn_src("_serve_module_asset"), NS)
    serve = NS["_serve_module_asset"]
    check("F1. обычный файл модуля отдаётся", serve("demo", "panel.js").status_code == 200)
    #  Обход прежней проверки: сегмент, начинающийся с «\», сбрасывает os.path.join к корню диска, а
    #  startswith без разделителя принимает соседнюю папку «webx» за «web».
    sneaky = os.path.splitdrive(os.path.join(mdir, "webx", "secret.js"))[1]
    r_sneaky = serve("demo", sneaky)
    check("F2. путь без буквы диска в соседнюю папку «webx» — 404 (раньше файл отдавался)",
          r_sneaky.status_code == 404, (sneaky, r_sneaky.status_code, r_sneaky.content))
    check("F3. «:» и «..» в пути — 404",
          serve("demo", "C:/x.js").status_code == 404 and serve("demo", "..\\webx\\secret.js").status_code == 404)



def sec_G():
    # ── G. проверка источника запроса ─────────────────────────────────────────────────────────

    print("--- G. сбой проверки источника ---")

    class _Pol:
        @staticmethod
        def origin_allowed(*a):
            raise RuntimeError("сбой разбора")

        @staticmethod
        def is_mutating_method(m):
            return m not in ("GET", "HEAD", "OPTIONS")

    class _H(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    class _GReq:
        def __init__(self, method):
            self.method = method
            self.headers = _H(origin="http://evil.example", host="127.0.0.1:8000")
            self.url = type("U", (), {"scheme": "http"})()

    async def _next(req):
        return _Resp(200, {"ok": True})

    NS = {"_security_policy": _Pol(), "JSONResponse": lambda c, status_code=200: _Resp(status_code, c),
          "log": _Log(), "_exc_brief": lambda: ""}
    exec(fn_src("_origin_guard"), NS)
    g = NS["_origin_guard"]
    check("G1. сбой самой проверки: изменяющий запрос закрыт (403), чтение проходит",
          asyncio.run(g(_GReq("POST"), _next)).status_code == 403
          and asyncio.run(g(_GReq("GET"), _next)).status_code == 200)



def sec_H():
    # ── H. подсказки окна ─────────────────────────────────────────────────────────────────────

    print("--- H. подсказки ---")
    app_js = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
    m = re.search(r"const _helpEntry = \(key\) => \{[\s\S]*?\n    \};", app_js)
    hints = io.open(os.path.join(REPO, "web", "composables", "helpHints.js"), encoding="utf-8").read()
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    if not m or not os.path.isfile(node):
        check("H0. блок _helpEntry найден и node доступен", False, (bool(m), node))
    else:
        js = (re.sub(r"\bexport\s+(const|default)\b", lambda x: "const" if x.group(1) == "const" else "", hints)
              + "\nconst lang = {value: 'ru'};\n" + m.group(0).strip() + "\n"
              + "const out = {ru: _helpEntry('set-mod-pick'), old: _helpEntry('set-security'), "
                "lic: _helpEntry('set-license-sent')};\n"
              + "lang.value = 'en'; out.en = _helpEntry('set-mod-pick');\n"
              + "console.log(JSON.stringify(out));\n")
        jf = os.path.join(TMP, "hints_check.js")
        io.open(jf, "w", encoding="utf-8").write(js)
        p = subprocess.run([node, jf], capture_output=True, text=True, encoding="utf-8", timeout=60)
        try:
            out = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            out = {}
        ru = out.get("ru") or {}
        check("H1. подсказка в форме {ru, en} в русском окне показывает русский текст (раньше — пустая рамка)",
              bool(ru.get("title")) and bool(ru.get("text")) and "папке выпуска" in ru.get("text", ""),
              (out, p.stderr[-300:]))
        check("H2. подсказки прежней формы и английский вариант не изменились",
              bool((out.get("old") or {}).get("text")) and bool((out.get("en") or {}).get("text"))
              and bool((out.get("lic") or {}).get("text")), out)



try:
    for _sec in (sec_A, sec_B, sec_C, sec_D, sec_E, sec_F, sec_G, sec_H):
        try:
            _sec()
        except Exception as _e:
            check("%s0. раздел выполнился до конца" % _sec.__name__[-1], False, repr(_e))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\nИТОГО: %s" % ("PASS" if not fails else "FAIL=%d" % len(fails)))
for f in fails:
    print("  FAIL: " + f)
sys.exit(1 if fails else 0)
