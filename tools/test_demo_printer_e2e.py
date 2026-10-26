# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.970 — виртуальный принтер НАСКВОЗЬ: настоящий сервер, настоящая печать, настоящий счёт.

ЗАЧЕМ. Отдельно автомат виртуального принтера проверен (tools/test_demo_printer.py). Но
владельцу нужен не автомат, а РАБОТАЮЩИЙ МЕХАНИЗМ: положил файл в задачи, запустил на
виртуальный принтер, увидел нагрев и печать, и количество в задаче поднялось. Проверить это
можно только на живом сервере — здесь он и поднимается.

КАК ЭТО БЕЗОПАСНО. Используется ШТАТНЫЙ режим изоляции продукта (--fm-packaged-e2e): своя
временная папка данных, свой config, свой замок, свой порт. Рабочая папка данных не
открывается и не изменяется — это проверяется отдельной проверкой в конце. Сеть виртуальному
принтеру не нужна вовсе, наружу процесс не ходит.

Запуск:  python tools/test_demo_printer_e2e.py
"""
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RV_PATH = os.path.join(ROOT, "tools", "validation", "ui", "run_ui_verification.py")
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_demo", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "DEMO_PRINTER_E2E_SENTINEL_2_972"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def http(port, method, path, body=None, ctype="application/json", timeout=20.0):
    """Запрос по петле. Стандартная библиотека: новых зависимостей не заводим."""
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


def multipart(fields_name, filename, data):
    b = "----fm%d" % int(time.time() * 1000)
    body = (("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n" % (b, fields_name, filename)).encode()
            + data + ("\r\n--%s--\r\n" % b).encode())
    return body, "multipart/form-data; boundary=%s" % b


#  Маленький настоящий g-code: по нему видно, что цели нагрева читаются из файла.
GCODE = (b"; test print for the virtual printer\n"
         b"M140 S70\nM190 S70\nM104 S245\nM109 S245\n"
         b"G28\n" + b"G1 X10 Y10 E1\n" * 50)

#  2.972: файл, нарезанный ПОД КОНКРЕТНУЮ МАРКУ. Именно на таком владелец и споткнулся:
#  программа отвечала «нет совместимых свободных принтеров», потому что виртуальный принтер
#  не Bambu, не Klipper и не FlashForge. Он обязан подходить под любой файл — для того и заведён.
GCODE_BRANDED = (b"; printer_model = Creality K2 Plus\n"
                 b"M140 S60\nM190 S60\nM104 S230\nM109 S230\n"
                 b"G28\n" + b"G1 X10 Y10 E1\n" * 50)

run_dir = tempfile.mkdtemp(prefix="fmdemoe2e")
port = rv.free_local_port()
contract = rv.build_e2e_contract(run_dir, port)
#  Принтеры ВКЛЮЧЕНЫ: без воркеров виртуальный принтер не оживёт. Сети он не открывает,
#  а других принтеров во временной базе нет.
contract["disables"]["printers"] = "0"
os.makedirs(contract["data_dir"], exist_ok=True)
rv.write_e2e_marker(contract)
proof, problems = rv.check_e2e_contract(contract, run_dir)
#  data_dir_empty: папка уже содержит маркер изоляции, который мы сами и положили.
#  disabled_printers: воркеры принтеров включены НАМЕРЕННО — без них виртуальный принтер
#  не оживёт, а сети он не открывает и других принтеров во временной базе нет.
check("1. изоляция доказана до запуска: своя папка, свой config, свой замок, свой порт",
      not [k for k in problems if k not in ("data_dir_empty", "disabled_printers")], problems)

prod_dir = rv.production_data_dir()
prod_before = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []

env = rv.server_env(contract, run_dir)
proc, _logs = rv.spawn([sys.executable, os.path.join(ROOT, "server.py"), rv.E2E_FLAG],
                       os.path.join(run_dir, "server"), env=env, cwd=ROOT)
ok, why = rv.wait_http(port, "/api/printers", proc, 90)
check("2. изолированный сервер поднялся", ok, why)

states = []
try:
    if ok:
        #  ── 1) заводим виртуальный принтер тем же роутом, что и обычный ──
        http(port, "POST", "/api/printers/save",
             [{"id": "demo1", "name": "Виртуальный 1", "type": "demo", "ip": "", "port": None,
               "gen": "auto", "serial": "", "model": "Виртуальный принтер"}])
        prs = http(port, "GET", "/api/printers")
        check("3. виртуальный принтер заведён без адреса и кода доступа",
              isinstance(prs, list) and len(prs) == 1 and prs[0]["type"] == "demo"
              and not prs[0].get("ip") and not prs[0].get("credential_configured"), prs)

        #  ── 2) кладём файл в задачи и запускаем на него печать ──
        body, ctype = multipart("files", "demo_test.gcode", GCODE)
        up = http(port, "POST", "/api/staging/upload", body, ctype)
        check("4. файл лёг в задачи", isinstance(up, dict) and up.get("saved") == ["demo_test.gcode"], up)
        st0 = http(port, "GET", "/api/staging")
        _row0 = [f for f in (st0 if isinstance(st0, list) else []) if f.get("filename") == "demo_test.gcode"]
        printed_before = (_row0[0].get("printed_qty") if _row0 else None)
        check("5. в задаче видно количество напечатанного до запуска", printed_before == 0, printed_before)

        r = http(port, "POST", "/api/part/print", {"printer_id": "demo1", "gcode_file": "demo_test.gcode"})
        check("6. запуск печати принят тем же роутом, что и для настоящего принтера",
              isinstance(r, dict) and (r.get("accepted") or r.get("status") in ("ok", "success")), r)

        #  ── 3) смотрим состояния глазами интерфейса: тот же вебсокет /ws ──
        node = None
        for c in (r"C:\Program Files\nodejs\node.exe", "node"):
            if os.path.isfile(c) or shutil.which(c):
                node = c
                break
        if node:
            js = os.path.join(run_dir, "watch.mjs")
            io.open(js, "w", encoding="utf-8", newline="\n").write(
                "const ws = new WebSocket('ws://127.0.0.1:%d/ws');\n"
                "const seen = [];\n"
                "ws.onmessage = (e) => { try { const d = JSON.parse(e.data);\n"
                "  const s = d && d['demo1']; if (s) seen.push([Date.now(), s.status, s.status_raw,\n"
                "    s.percent, s.bed_temp, s.nozzle_temp]); } catch (x) {} };\n"
                "setTimeout(() => { console.log(JSON.stringify(seen)); ws.close(); process.exit(0); }, 52000);\n"
                % port)
            out = subprocess.run([node, js], capture_output=True, text=True, timeout=90)
            try:
                states = json.loads((out.stdout or "[]").strip().splitlines()[-1])
            except Exception:
                states = []
        seq = [(s[1], s[2]) for s in states]
        uniq = [x for i, x in enumerate(seq) if i == 0 or x != seq[i - 1]]
        check("7. по вебсокету пришла та же цепочка, что задал владелец: стол, сопло, печать, готово",
              [x[1] for x in uniq][:4] == ["heating_bed", "heating_nozzle", "printing", "finish"]
              and [x[0] for x in uniq][:4] == ["PREPARE", "PREPARE", "RUNNING", "FINISH"], uniq[:6])
        _run = [(s[4], s[5]) for s in states if s[1] == "RUNNING"]
        _heat_bed = [s[4] for s in states if s[2] == "heating_bed"]
        check("8. цели нагрева взяты ИЗ ФАЙЛА: во время печати стол 70, сопло 245",
              _run and all(b == 70 and n == 245 for b, n in _run)
              and _heat_bed and min(_heat_bed) < 70,   # стол именно ГРЕЛСЯ, а не появился горячим
              (_run[:2], min(_heat_bed or [0])))
        _pcts = [s[3] for s in states if s[1] == "RUNNING"]
        check("9. проценты печати росли, а не стояли на месте",
              len(_pcts) >= 3 and _pcts[0] < _pcts[-1], (_pcts[:2], _pcts[-2:]))

        #  ── 4) главное: количество в задаче поднялось ──
        st1 = http(port, "GET", "/api/staging")
        _row1 = [f for f in (st1 if isinstance(st1, list) else []) if f.get("filename") == "demo_test.gcode"]
        printed_after = (_row1[0].get("printed_qty") if _row1 else None)
        check("10. количество напечатанного в задаче выросло — счёт ведёт ядро, а не принтер",
              printed_after == 1, (printed_before, printed_after))

        files_on = http(port, "GET", "/api/printer/demo1/files")
        check("11. отправленный файл числится лежащим на принтере",
              isinstance(files_on, list) and "demo_test.gcode" in files_on, files_on)

        #  ── 5) случай владельца: файл нарезан под конкретную марку ──
        body, ctype = multipart("files", "kub_k2.gcode", GCODE_BRANDED)
        http(port, "POST", "/api/staging/upload", body, ctype)
        st2 = http(port, "GET", "/api/staging")
        _rowb = [f for f in (st2 if isinstance(st2, list) else []) if f.get("filename") == "kub_k2.gcode"]
        _pids = (_rowb[0].get("compatible_pids") if _rowb else None)
        check("12. файл, нарезанный под чужую марку, считается совместимым с виртуальным принтером",
              isinstance(_pids, list) and "demo1" in _pids, _pids)
        rb = http(port, "POST", "/api/part/print", {"printer_id": "demo1", "gcode_file": "kub_k2.gcode"})
        check("13. и печать такого файла принимается, а не отбивается по модели",
              isinstance(rb, dict) and (rb.get("accepted") or rb.get("status") in ("ok", "success")), rb)
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("14. рабочая папка данных не изменилась", prod_before == prod_after,
      set(prod_before) ^ set(prod_after))

try:
    shutil.rmtree(run_dir, ignore_errors=True)
except Exception:
    pass

print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
