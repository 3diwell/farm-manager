# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-104 (2.983) — преднагрев термокамеры НА ЖИВОМ сервере с виртуальным принтером.

ЗАЧЕМ. Настоящих принтеров с нагревом камеры у разработки нет. Но всю цепочку — разбор команды
политикой, маршрут, цель у принтера, живое состояние в потоке к интерфейсу — проверить можно
на виртуальном принтере: он принимает те же действия из того же закрытого списка и проходит
тот же разбор, что и настоящие. Плюс здесь проверяется, что чужим типам камера НЕ шлётся,
а значение вне предела отклоняется, а не подрезается молча.

ЧТО ЭТО НЕ ДОКАЗЫВАЕТ: что настоящий H2D или K2 Plus примет команду. Контракты взяты из
исходников слайсера и извлечённой прошивки, но подтверждает их только ферма.

КАК ЭТО БЕЗОПАСНО. Штатный режим изоляции (--fm-packaged-e2e): своя папка данных, свой
config, свой замок, свой порт; виртуальному принтеру сеть не нужна, FlashForge заведён на
недостижимый адрес документационной подсети.

Запуск:  python tools/test_chamber_demo_e2e.py
"""
import base64
import importlib.util
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
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_chamber", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "CHAMBER_DEMO_E2E_SENTINEL_2_983"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def http(port, method, path, body=None, timeout=60.0):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
    head = "%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n" % (method, path)
    if body is not None:
        head += "Content-Type: application/json\r\nContent-Length: %d\r\n" % len(raw)
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
    try:
        code = int(buf.split(b" ", 2)[1])
    except Exception:
        code = 0
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
        return code, json.loads(payload.decode("utf-8", "replace"))
    except Exception:
        return code, payload.decode("utf-8", "replace")


def ws_state(port, pid, wait_s=8.0):
    """Один кадр живого состояния из /ws (тот же поток, что читает интерфейс). Минимальный клиент
    RFC 6455: рукопожатие и чтение текстовых кадров до первого, где есть нужный принтер."""
    s = socket.create_connection(("127.0.0.1", int(port)), timeout=wait_s)
    s.settimeout(wait_s)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET /ws HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (int(port), key)).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    if b" 101 " not in buf.split(b"\r\n", 1)[0]:
        s.close()
        return None
    rest = buf[buf.find(b"\r\n\r\n") + 4:]
    t0 = time.monotonic()
    found = None
    while time.monotonic() - t0 < wait_s and found is None:
        while len(rest) < 2:
            rest += s.recv(65536)
        b0, b1 = rest[0], rest[1]
        ln = b1 & 0x7F
        off = 2
        if ln == 126:
            while len(rest) < 4:
                rest += s.recv(65536)
            ln = int.from_bytes(rest[2:4], "big"); off = 4
        elif ln == 127:
            while len(rest) < 10:
                rest += s.recv(65536)
            ln = int.from_bytes(rest[2:10], "big"); off = 10
        while len(rest) < off + ln:
            rest += s.recv(65536)
        frame, rest = rest[off:off + ln], rest[off + ln:]
        if (b0 & 0x0F) == 1:
            try:
                obj = json.loads(frame.decode("utf-8", "replace"))
            except Exception:
                obj = None
            if isinstance(obj, dict) and pid in obj:
                found = obj[pid]
    s.close()
    return found


DEAD_FF = "192.0.2.12"
run_dir = tempfile.mkdtemp(prefix="fmchambere2e")
port = rv.free_local_port()
contract = rv.build_e2e_contract(run_dir, port)
contract["disables"]["printers"] = "0"      # воркеры нужны: без них виртуальный принтер не оживёт
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
        http(port, "POST", "/api/printers/save", [
            {"id": "demo1", "name": "Виртуальный 1", "type": "demo", "ip": "", "port": None,
             "gen": "auto", "serial": "", "model": "Виртуальный принтер"},
            {"id": "ff1", "name": "FlashForge", "type": "flashforge", "ip": DEAD_FF, "port": 8898,
             "token": "FIXTURE_SERIAL:FIXTURE_CHECK", "gen": "auto", "serial": "", "model": "Adventurer 5M"},
        ])
        _c, plist = http(port, "GET", "/api/printers")
        pm = {p.get("id"): p for p in (plist if isinstance(plist, list) else [])}
        check("3. в списке принтеров у виртуального есть признак нагрева камеры",
              pm.get("demo1", {}).get("chamber_heater") is True, pm.get("demo1"))
        check("4. у FlashForge (Adventurer 5M) признака нагрева камеры нет",
              pm.get("ff1", {}).get("chamber_heater") is False, pm.get("ff1"))
        time.sleep(2.0)   # воркер виртуального принтера должен успеть отдать первое состояние

        c1, r1 = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "chamber", "val": "50"})
        check("5. команда «камера 50°» виртуальному принтеру принята",
              c1 == 200 and isinstance(r1, dict) and r1.get("status") == "ok", (c1, r1))
        st = None
        for _ in range(6):
            st = ws_state(port, "demo1", 6.0)
            if st and int(st.get("chamber_target") or 0) == 50:
                break
        check("6. в живом состоянии у принтера цель камеры 50°",
              isinstance(st, dict) and int(st.get("chamber_target") or 0) == 50, st and {k: st.get(k) for k in ("chamber_target", "chamber_temp", "chamber_heater")})
        check("7. и признак нагрева камеры в самом состоянии",
              isinstance(st, dict) and st.get("chamber_heater") is True, st and st.get("chamber_heater"))

        c2, r2 = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "chamber", "val": "0"})
        check("8. «камера 0°» (выключить) принята", c2 == 200 and isinstance(r2, dict) and r2.get("status") == "ok", (c2, r2))
        st2 = None
        for _ in range(6):
            st2 = ws_state(port, "demo1", 6.0)
            if st2 and int(st2.get("chamber_target") or 0) == 0:
                break
        check("9. цель камеры снята", isinstance(st2, dict) and int(st2.get("chamber_target") or 0) == 0,
              st2 and st2.get("chamber_target"))

        c3, r3 = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "chamber", "val": "90"})
        check("10. 90° — выше предела: отказ, а не молчаливая подрезка",
              c3 == 400 and isinstance(r3, dict) and r3.get("reason") == "value_out_of_range", (c3, r3))
        c4, r4 = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "chamber", "val": "50\nM112"})
        check("11. инъекция через перевод строки отклонена", c4 == 400, (c4, r4))
        c5, r5 = http(port, "POST", "/api/printer/ff1/cmd", {"cmd": "chamber", "val": "50"})
        check("12. FlashForge: камера не поддерживается — отказ ДО обращения к принтеру",
              c5 == 400 and isinstance(r5, dict) and r5.get("reason") == "unsupported_command", (c5, r5))
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("13. рабочая папка данных не изменилась", prod_before == prod_after, set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)
print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
