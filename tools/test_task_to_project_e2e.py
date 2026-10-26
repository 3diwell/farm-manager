# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.976 — перенос задачи в проект НАСКВОЗЬ: настоящий сервер, настоящая база.

ЗАЧЕМ. Владелец переносил из задач в проект файл, который уже печатался несколько раз, — и файл
вставал в проект с нулями. Заказ: счёт (план, напечатано) и заметки переходят такими, какими
были в момент переноса; одноимённый файл в проекте — программа спрашивает «заменить или
отменить», при замене переносятся актуальные данные.

КАК ЭТО БЕЗОПАСНО. Штатный режим изоляции (--fm-packaged-e2e): своя папка данных, свой config,
свой замок, свой порт. Рабочая папка данных не открывается и не изменяется — проверяется в конце.

Запуск:  python tools/test_task_to_project_e2e.py
"""
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
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_t2p", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "TASK_TO_PROJECT_E2E_SENTINEL_2_976"
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


GCODE1 = b"; kub v1\nM140 S60\nM104 S220\nG28\n" + b"G1 X10 Y10 E1\n" * 40
GCODE2 = b"; kub v2 (new slicing)\nM140 S65\nM104 S225\nG28\n" + b"G1 X12 Y12 E1\n" * 40
FN = "kub_test.gcode"

run_dir = tempfile.mkdtemp(prefix="fmt2pe2e")
port = rv.free_local_port()
contract = rv.build_e2e_contract(run_dir, port)
os.makedirs(contract["data_dir"], exist_ok=True)
rv.write_e2e_marker(contract)
proof, problems = rv.check_e2e_contract(contract, run_dir)
check("1. изоляция доказана до запуска", not [k for k in problems if k not in ("data_dir_empty",)], problems)

prod_dir = rv.production_data_dir()
prod_before = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []

env = rv.server_env(contract, run_dir)
proc, _logs = rv.spawn([sys.executable, os.path.join(ROOT, "server.py"), rv.E2E_FLAG],
                       os.path.join(run_dir, "server"), env=env, cwd=ROOT)
ok, why = rv.wait_http(port, "/api/printers", proc, 90)
check("2. изолированный сервер поднялся", ok, why)


def parts_of(pid):
    pv = http(port, "GET", "/api/projects2/%s/partsview" % pid)
    return (pv.get("parts") if isinstance(pv, dict) else None) or []


try:
    if ok:
        pr = http(port, "POST", "/api/projects2", {"name": "Заказ переноса"})
        pid = (pr.get("id") if isinstance(pr, dict) else None) or ((pr.get("project") or {}).get("id") if isinstance(pr, dict) else None)
        check("3. проект создан", bool(pid), pr)

        #  ── 1) задача с накопленным счётом ──
        body, ctype = multipart("files", FN, GCODE1)
        up = http(port, "POST", "/api/staging/upload", body, ctype)
        check("4. файл лёг в задачи", isinstance(up, dict) and up.get("saved") == [FN], up)
        sv = http(port, "POST", "/api/staging/save", {"filename": FN, "required_qty": 7, "printed_qty": 3, "notes": "красный PETG"})
        check("5. у задачи план 7, напечатано 3 и заметка", isinstance(sv, dict) and sv.get("status") == "ok", sv)

        #  ── 2) перенос: счёт переходит ──
        mv = http(port, "POST", "/api/staging/%s/to-project" % FN, {"project_id": pid})
        check("6. перенос принят, в ответе сказано, что перенесено",
              isinstance(mv, dict) and mv.get("status") == "ok"
              and (mv.get("carried") or {}).get("required") == 7 and (mv.get("carried") or {}).get("printed") == 3, mv)
        parts = parts_of(pid)
        check("7. деталь в проекте получила план 7, напечатано 3 и заметку задачи — а не нули",
              len(parts) == 1 and parts[0].get("required_qty") == 7 and parts[0].get("printed_qty") == 3
              and parts[0].get("notes") == "красный PETG",
              [(p.get("part_name"), p.get("required_qty"), p.get("printed_qty"), p.get("notes")) for p in parts])
        st = http(port, "GET", "/api/staging")
        check("8. из задач файл ушёл", isinstance(st, list) and not [f for f in st if f.get("filename") == FN], st)

        #  ── 3) тот же файл снова в задачах, с другим счётом ──
        body, ctype = multipart("files", FN, GCODE2)
        http(port, "POST", "/api/staging/upload", body, ctype)
        http(port, "POST", "/api/staging/save", {"filename": FN, "required_qty": 9, "printed_qty": 5, "notes": "новая нарезка"})
        mv2 = http(port, "POST", "/api/staging/%s/to-project" % FN, {"project_id": pid})
        check("9. одноимённый файл в проекте — программа спрашивает (exists), а не подсовывает копию",
              isinstance(mv2, dict) and mv2.get("status") == "exists" and (mv2.get("project") or {}).get("id") == pid, mv2)
        parts = parts_of(pid)
        check("10. без подтверждения в проекте ничего не изменилось",
              len(parts) == 1 and parts[0].get("required_qty") == 7 and parts[0].get("printed_qty") == 3,
              [(p.get("required_qty"), p.get("printed_qty")) for p in parts])
        st2 = http(port, "GET", "/api/staging")
        check("11. и задача осталась на месте", isinstance(st2, list) and [f for f in st2 if f.get("filename") == FN])

        #  ── 4) замена по подтверждению: актуальные данные ──
        mv3 = http(port, "POST", "/api/staging/%s/to-project" % FN, {"project_id": pid, "replace": True})
        check("12. замена принята", isinstance(mv3, dict) and mv3.get("status") == "ok" and mv3.get("replaced") is True, mv3)
        parts = parts_of(pid)
        check("13. в проекте один файл и деталь с НОВЫМ счётом: план 9, напечатано 5, заметка новая",
              len(parts) == 1 and parts[0].get("required_qty") == 9 and parts[0].get("printed_qty") == 5
              and parts[0].get("notes") == "новая нарезка",
              [(p.get("part_name"), p.get("required_qty"), p.get("printed_qty"), p.get("notes")) for p in parts])
        tree = http(port, "GET", "/api/projects2/%s/tree" % pid)
        _files = [n for n in ((tree.get("nodes") if isinstance(tree, dict) else None) or []) if n.get("type") == "file"]
        check("14. файл в проекте один и под своим именем — без « (2)»",
              len(_files) == 1 and _files[0].get("filename") == FN, [n.get("filename") for n in _files])
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("15. рабочая папка данных не изменилась", prod_before == prod_after, set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)

print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
