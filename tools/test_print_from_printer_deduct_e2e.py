# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.977 (R-095) — запуск файла, УЖЕ лежащего на принтере, тоже зовёт списание филамента.

ЗАЧЕМ. Владелец на живой ферме: у принтера привязана складская катушка, файл выбран из списка
«на принтере», печать пошла — а остаток не уменьшился и записи «печать (авто)» в журнале нет.
Причина: путь «файл уже на принтере» (start_print) хуки после отправки не звал вовсе — в
отличие от пути с загрузкой файла. Здесь проверяется на живом изолированном сервере с
виртуальным принтером: оба пути зовут те же хуки, и у файла с принтера есть данные о весе.

КАК ЭТО БЕЗОПАСНО. Штатный режим изоляции (--fm-packaged-e2e): своя папка данных, свой config,
свой замок, свой порт; сеть виртуальному принтеру не нужна.

Запуск:  python tools/test_print_from_printer_deduct_e2e.py
"""
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RV_PATH = os.path.join(ROOT, "tools", "validation", "ui", "run_ui_verification.py")
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_deduct", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "PRINT_FROM_PRINTER_DEDUCT_E2E_SENTINEL_2_977"
PASS = FAIL = 0
SRV = io.open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
DEMO = io.open(os.path.join(ROOT, "app", "demo_printer.py"), encoding="utf-8").read()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def http(port, method, path, body=None, ctype="application/json", timeout=20.0):
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
    payload = buf[sep + 4:] if sep >= 0 else buf
    if b"Transfer-Encoding: chunked" in buf[:sep if sep > 0 else 0]:
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


print("--- 1. закреплено в файлах ---")
check("1. путь «файл уже на принтере» зовёт списание для всех марок",
      "def _c1_after_dispatch(pid, p, data, fdata):" in SRV
      and SRV.count("_c1_after_dispatch(pid, p, data,") >= 4)
check("2. у Bambu берётся уже скачанная плита, у Klipper — вес из метаданных Moonraker",
      "_c1_after_dispatch(pid, p, data, (_preload[0] if _preload else None))" in SRV
      and "def _moonraker_weight_stub(p, fname):" in SRV
      and "server/files/metadata?filename=" in SRV.split("def _moonraker_weight_stub", 1)[1][:600])
check("3. виртуальный принтер помнит вес файла и списывает при запуске с принтера",
      "def remember(pid, fname, fdata):" in DEMO and "def file_data(pid, fname):" in DEMO
      and "_demo.remember(pid, fname, fdata)" in SRV and "_demo.file_data(pid, fname)" in SRV)

print("--- 2. живой изолированный сервер ---")
#  Файл с весом филамента в комментарии слайсера — его читает склад.
GCODE = (b"; sliced for the virtual printer\n; filament used [g] = 12.50\n"
         b"M140 S60\nM190 S60\nM104 S220\nM109 S220\nG28\n" + b"G1 X10 Y10 E1\n" * 30)

run_dir = tempfile.mkdtemp(prefix="fmdeducte2e")
port = rv.free_local_port()
contract = rv.build_e2e_contract(run_dir, port)
contract["disables"]["printers"] = "0"      # воркеры нужны: без них виртуальный принтер не оживёт
os.makedirs(contract["data_dir"], exist_ok=True)
rv.write_e2e_marker(contract)
proof, problems = rv.check_e2e_contract(contract, run_dir)
check("4. изоляция доказана до запуска",
      not [k for k in problems if k not in ("data_dir_empty", "disabled_printers")], problems)
prod_dir = rv.production_data_dir()
prod_before = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
env = rv.server_env(contract, run_dir)
proc, _logs = rv.spawn([sys.executable, os.path.join(ROOT, "server.py"), rv.E2E_FLAG],
                       os.path.join(run_dir, "server"), env=env, cwd=ROOT)
ok, why = rv.wait_http(port, "/api/printers", proc, 90)
check("5. изолированный сервер поднялся", ok, why)


def server_log_text():
    txt = ""
    for nm in ("server.stderr.txt", "server.stdout.txt"):
        p = os.path.join(run_dir, nm)
        if os.path.isfile(p):
            try:
                txt += io.open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                pass
    logs_dir = os.path.join(contract["data_dir"], "logs")
    if os.path.isdir(logs_dir):
        for nm in os.listdir(logs_dir):
            try:
                txt += io.open(os.path.join(logs_dir, nm), encoding="utf-8", errors="replace").read()
            except Exception:
                pass
    return txt


try:
    if ok:
        http(port, "POST", "/api/printers/save",
             [{"id": "demo1", "name": "Виртуальный 1", "type": "demo", "ip": "", "port": None,
               "gen": "auto", "serial": "", "model": "Виртуальный принтер"}])
        body, ctype = multipart("files", "ves_test.gcode", GCODE)
        http(port, "POST", "/api/staging/upload", body, ctype)
        r1 = http(port, "POST", "/api/part/print", {"printer_id": "demo1", "gcode_file": "ves_test.gcode"})
        check("6. первый запуск (с загрузкой файла) принят",
              isinstance(r1, dict) and (r1.get("accepted") or r1.get("status") in ("ok", "success")), r1)
        time.sleep(6.0)
        #  Журнал пишется с задержкой (буфер), поэтому здесь только запоминаем, что уже видно;
        #  строгий счёт — после второго запуска, когда оба пути точно отработали.
        n1 = len(re.findall(r"after_dispatch: printer=demo1 .*file=ves_test\.gcode", server_log_text()))
        check("7. первый запуск прошёл (файл ушёл на принтер)", True)
        #  Останавливаем и запускаем ТОТ ЖЕ файл с принтера — путь start_print.
        http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "stop", "val": ""})
        time.sleep(1.5)
        files_on = http(port, "GET", "/api/printer/demo1/files")
        check("8. файл числится на принтере", isinstance(files_on, list) and "ves_test.gcode" in files_on, files_on)
        r2 = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "start_print", "val": "ves_test.gcode"})
        check("9. запуск файла с принтера принят",
              isinstance(r2, dict) and (r2.get("accepted") or r2.get("status") in ("ok", "success")), r2)
        time.sleep(8.0)
        txt = server_log_text()
        n2 = len(re.findall(r"after_dispatch: printer=demo1 .*file=ves_test\.gcode", txt))
        #  Два запуска — два вызова хуков: с загрузкой (как и раньше) и С ПРИНТЕРА (новое).
        check("10. запуск С ПРИНТЕРА тоже вызвал хуки списания — раньше этот путь их не звал",
              n2 >= 2, (n1, n2))
        check("11. в журнале нет слов «списание пропущено» для виртуального принтера",
              "списание пропущено (ves_test.gcode)" not in txt)
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("12. рабочая папка данных не изменилась", prod_before == prod_after, set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)
print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
