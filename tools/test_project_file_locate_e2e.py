# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.978 — «Открыть расположение файла» у детали проекта работает без путей в дереве.

ЗАЧЕМ. В 2.977 кнопку сделали так: дерево проекта стало отдавать абсолютный путь к файлу.
Это нарушило правило программы — дерево читает и наблюдатель, которому устройство фермы
показывать незачем (две существующие проверки как раз это и стерегут, и обе покраснели).

В 2.978 путей в дереве нет, а кнопка спрашивает папку отдельным маршрутом
POST /api/projects2/{project_id}/files/{file_id}/locate — по явному действию и по праву
на проекты. Здесь это проверяется НА ЖИВОМ изолированном сервере: дерево без путей,
маршрут отдаёт настоящую папку, а на несуществующий файл честно отвечает «не найдено».

КАК ЭТО БЕЗОПАСНО. Штатный режим изоляции (--fm-packaged-e2e): своя папка данных, свой
config, свой замок, свой порт. Принтеры не нужны и выключены.

Запуск:  python tools/test_project_file_locate_e2e.py
"""
import importlib.util
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RV_PATH = os.path.join(ROOT, "tools", "validation", "ui", "run_ui_verification.py")
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_locate", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "PROJECT_FILE_LOCATE_E2E_SENTINEL_2_978"
PASS = FAIL = 0
GCODE = b"; test plate\nM140 S60\nG28\n" + b"G1 X10 Y10 E1\n" * 20


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def http(port, method, path, body=None, ctype="application/json", timeout=60.0):
    raw = body if isinstance(body, (bytes, bytearray)) else (
        json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b"")
    head = "%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n" % (method, path)
    if body is not None:
        head += "Content-Type: %s\r\nContent-Length: %d\r\n" % (ctype, len(raw))
    s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    s.settimeout(timeout)
    s.sendall(head.encode("utf-8") + b"\r\n" + raw)
    buf = b""
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    s.close()
    sep = buf.find(b"\r\n\r\n")
    headers = buf[:sep] if sep > 0 else b""
    payload = buf[sep + 4:] if sep >= 0 else buf
    if b"Transfer-Encoding: chunked" in headers:
        out, rest = b"", payload
        while True:
            e = rest.find(b"\r\n")
            if e < 0:
                break
            try:
                n = int(rest[:e].split(b";")[0], 16)
            except Exception:
                break
            if n == 0:
                break
            out += rest[e + 2:e + 2 + n]
            rest = rest[e + 2 + n + 2:]
        payload = out
    try:
        return json.loads(payload.decode("utf-8", "replace"))
    except Exception:
        return payload.decode("utf-8", "replace")


def multipart(field, filename, data):
    b = "----fm%d" % int(time.time() * 1000)
    body = (("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n" % (b, field, filename)).encode()
            + data + ("\r\n--%s--\r\n" % b).encode())
    return body, "multipart/form-data; boundary=%s" % b


run_dir = tempfile.mkdtemp(prefix="fmlocatee2e")
port = rv.free_local_port()
contract = rv.build_e2e_contract(run_dir, port)
os.makedirs(contract["data_dir"], exist_ok=True)
rv.write_e2e_marker(contract)
proof, problems = rv.check_e2e_contract(contract, run_dir)
check("1. изоляция доказана до запуска",
      not [k for k in problems if k not in ("data_dir_empty", "disabled_printers")], problems)
prod_dir = rv.production_data_dir()
prod_before = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
env = rv.server_env(contract, run_dir)
proc, _logs = rv.spawn([sys.executable, os.path.join(ROOT, "server.py"), rv.E2E_FLAG],
                       os.path.join(run_dir, "server"), env=env, cwd=ROOT)
ok, why = rv.wait_http(port, "/api/printers", proc, 90)
check("2. изолированный сервер поднялся", ok, why)

try:
    if ok:
        pr = http(port, "POST", "/api/projects2", {"name": "Проект расположения"})
        pid = (pr or {}).get("id") or (pr or {}).get("project_id") or ""
        if not pid:
            _all = http(port, "GET", "/api/projects2")
            pid = (_all[0].get("id") if isinstance(_all, list) and _all else "")
        check("3. проект создан", bool(pid), pr)

        body, ctype = multipart("files", "plate_locate.gcode", GCODE)
        up = http(port, "POST", "/api/projects2/%s/files/upload" % pid, body, ctype)
        added = (up or {}).get("added") or []
        fid = (added[0].get("file_id") if added else "")
        check("4. файл добавлен в проект", bool(fid), up)

        tree = http(port, "GET", "/api/projects2/%s/tree" % pid)
        _txt = json.dumps(tree, ensure_ascii=False)
        check("5. дерево проекта отдаёт файл", "plate_locate.gcode" in _txt, _txt[:200])
        check("6. в дереве НЕТ путей на диске",
              '"stored_path"' not in _txt and '"src_path"' not in _txt, _txt[:300])
        check("7. в дереве нет и самой папки данных",
              contract["data_dir"].replace("\\", "/") not in _txt.replace("\\\\", "/").replace("\\", "/"),
              _txt[:300])

        loc = http(port, "POST", "/api/projects2/%s/files/%s/locate" % (pid, fid))
        check("8. маршрут отдал расположение файла",
              isinstance(loc, dict) and loc.get("status") == "ok", loc)
        _dir = (loc or {}).get("dir") or ""
        _name = (loc or {}).get("name") or ""
        check("9. названа настоящая папка на диске", bool(_dir) and os.path.isdir(_dir), _dir)
        check("10. файл в этой папке действительно лежит",
              bool(_name) and os.path.isfile(os.path.join(_dir, _name)), (_dir, _name))
        check("11. папка находится внутри папки данных этого сервера",
              os.path.normcase(os.path.realpath(_dir)).startswith(
                  os.path.normcase(os.path.realpath(contract["data_dir"]))), (_dir, contract["data_dir"]))

        #  Идентификатор латиницей: кириллица в адресе без экранирования — это уже проверка
        #  разбора запроса, а не поведения маршрута.
        bad = http(port, "POST", "/api/projects2/%s/files/%s/locate" % (pid, "pf_no_such_file"))
        check("12. на несуществующий файл отвечает «не найдено», а не путём",
              isinstance(bad, dict) and bad.get("status") == "not_found" and not bad.get("dir"), bad)
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("13. рабочая папка данных не изменилась", prod_before == prod_after,
      set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)
print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
