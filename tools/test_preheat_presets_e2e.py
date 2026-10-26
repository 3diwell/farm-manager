# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-103 (2.984) — пресеты прогрева хранятся на сервере и едины на всю ферму: живой сервер.

ЗАЧЕМ. Владелец: «профили должны храниться на сервере, а не только в localStorage, чтобы ими
пользовались все операторы и компьютеры фермы». Здесь на изолированном сервере проверяется:
сохранённые пресеты возвращаются любому клиенту, битые отклоняются с причиной (а не ложатся в
базу как есть), а старые ключи настроек фермы от этого не страдают.

КАК ЭТО БЕЗОПАСНО. Штатный режим изоляции (--fm-packaged-e2e): своя папка данных, свой
config, свой замок, свой порт. Принтеры выключены.

Запуск:  python tools/test_preheat_presets_e2e.py
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
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_presets", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "PREHEAT_PRESETS_E2E_SENTINEL_2_984"
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


run_dir = tempfile.mkdtemp(prefix="fmpresetse2e")
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
        j0 = http(port, "GET", "/api/farm-settings")
        check("3. пока владелец ничего не правил, пресетов на сервере нет (интерфейс покажет встроенные)",
              isinstance(j0, dict) and j0.get("ok") and "preheat_presets" not in (j0.get("settings") or {}), j0)

        good = [{"name": "PLA", "n": 215, "b": 55, "c": None}, {"name": "PETG", "n": 240, "b": 75, "c": None},
                {"name": "ASA", "n": 255, "b": 95, "c": 55}, {"name": "Нейлон", "n": 270, "b": 90, "c": 60}]
        j1 = http(port, "POST", "/api/farm-settings", {"preheat_presets": good})
        check("4. свои пресеты сохранены", isinstance(j1, dict) and j1.get("ok") is True
              and [p["name"] for p in (j1.get("preheat_presets") or [])] == ["PLA", "PETG", "ASA", "Нейлон"], j1)
        j2 = http(port, "GET", "/api/farm-settings")
        got = (j2.get("settings") or {}).get("preheat_presets") if isinstance(j2, dict) else None
        check("5. любой клиент получает те же пресеты с сервера",
              isinstance(got, list) and len(got) == 4 and got[2].get("c") == 55 and got[0].get("c") is None
              and got[3].get("name") == "Нейлон", got)

        j3 = http(port, "POST", "/api/farm-settings", {"stagger_on": "1", "stagger_sec": "90"})
        j4 = http(port, "GET", "/api/farm-settings")
        st4 = (j4.get("settings") or {}) if isinstance(j4, dict) else {}
        check("6. запись других настроек фермы пресеты не затирает",
              isinstance(j3, dict) and j3.get("ok") and st4.get("stagger_sec") == "90"
              and len(st4.get("preheat_presets") or []) == 4, st4)

        bad_cases = [
            ("выше предела сопла", [{"name": "X", "n": 400, "b": 60}], "preset_value_out_of_range"),
            ("выше предела стола", [{"name": "X", "n": 200, "b": 130}], "preset_value_out_of_range"),
            ("выше предела камеры", [{"name": "X", "n": 200, "b": 60, "c": 90}], "preset_value_out_of_range"),
            ("без имени", [{"name": "  ", "n": 200, "b": 60}], "bad_preset_name"),
            ("имя с управляющим символом", [{"name": "PLA", "n": 200, "b": 60}], "bad_preset_name"),
            ("повтор имени", [{"name": "PLA", "n": 200, "b": 60}, {"name": "pla", "n": 210, "b": 60}], "duplicate_preset_name"),
            ("не число", [{"name": "X", "n": "двести", "b": 60}], "bad_preset_value"),
            ("не список", {"name": "X"}, "bad_presets"),
            ("слишком много", [{"name": "P%d" % i, "n": 200, "b": 60} for i in range(25)], "too_many_presets"),
        ]
        for label, payload, want in bad_cases:
            r = http(port, "POST", "/api/farm-settings", {"preheat_presets": payload})
            check("7. битые пресеты отклонены (%s)" % label,
                  isinstance(r, dict) and r.get("ok") is False and r.get("error") == want, r)
        j5 = http(port, "GET", "/api/farm-settings")
        st5 = (j5.get("settings") or {}) if isinstance(j5, dict) else {}
        check("8. после отказов на сервере остались прежние четыре пресета",
              [p.get("name") for p in (st5.get("preheat_presets") or [])] == ["PLA", "PETG", "ASA", "Нейлон"], st5.get("preheat_presets"))

        j6 = http(port, "POST", "/api/farm-settings", {"preheat_presets": [{"name": "  PLA  fast ", "n": "220", "b": 60.0, "c": ""}]})
        p6 = (j6.get("preheat_presets") or [{}])[0] if isinstance(j6, dict) else {}
        check("9. имя приводится к опрятному виду, числа-строки принимаются, пустая камера = нет",
              p6.get("name") == "PLA fast" and p6.get("n") == 220 and p6.get("b") == 60 and p6.get("c") is None, j6)
        j7 = http(port, "POST", "/api/farm-settings", {"preheat_presets": []})
        j8 = http(port, "GET", "/api/farm-settings")
        check("10. пустой список — тоже настройка (владелец убрал все пресеты)",
              isinstance(j7, dict) and j7.get("ok") is True and (j8.get("settings") or {}).get("preheat_presets") == [], (j7, j8))
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("11. рабочая папка данных не изменилась", prod_before == prod_after, set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)
print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
