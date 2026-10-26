# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-106 (2.982) — главная страница программы отдаёт интерфейс 3.0; 2.0 остаётся по адресу /?ui=2.

ЗАЧЕМ. Решение владельца: 3.0 становится основным, переключатель в шапке скрывается, но код
2.0 остаётся — «в дальнейшем это нам может снова понадобиться». Здесь это проверяется на
ЖИВОМ изолированном сервере тремя запросами: «/» несёт флаг 3.0 и лист оформления,
«/?ui=2» — нет (это прежняя страница 2.0), «/ui3» — тот же 3.0.

КАК ЭТО БЕЗОПАСНО. Штатный режим изоляции (--fm-packaged-e2e): своя папка данных, свой
config, свой замок, свой порт. Принтеры выключены.

Запуск:  python tools/test_ui3_default_page_e2e.py
"""
import importlib.util
import os
import shutil
import socket
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RV_PATH = os.path.join(ROOT, "tools", "validation", "ui", "run_ui_verification.py")
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_ui3def", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "UI3_DEFAULT_PAGE_E2E_SENTINEL_2_982"
PASS = FAIL = 0
FLAG = "window.__UI3_MODE__=true"
SHEET = '<link rel="stylesheet" href="/ui3/ui3.css">'


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def get(port, path, timeout=30.0):
    s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    s.settimeout(timeout)
    s.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n" % path).encode("utf-8"))
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
    head = buf[:sep].decode("utf-8", "replace") if sep > 0 else ""
    body = buf[sep + 4:] if sep >= 0 else buf
    try:
        code = int(head.split(" ", 2)[1])
    except Exception:
        code = 0
    return code, body.decode("utf-8", "replace")


run_dir = tempfile.mkdtemp(prefix="fmui3def")
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
        c1, b1 = get(port, "/")
        check("3. главная страница отвечает", c1 == 200 and "<html" in b1.lower(), c1)
        check("4. главная страница — интерфейс 3.0 (флаг режима стоит)", FLAG in b1)
        check("5. главная страница подключает лист оформления 3.0", SHEET in b1)
        check("6. флаг стоит РАНЬШЕ скрипта выбора интерфейса (иначе страница перенаправляла бы сама себя)",
              FLAG in b1 and "farm_ui_version')==='3'" in b1 and b1.index(FLAG) < b1.index("farm_ui_version')==='3'"))
        c2, b2 = get(port, "/?ui=2")
        check("7. адрес /?ui=2 отвечает", c2 == 200 and "<html" in b2.lower(), c2)
        check("8. /?ui=2 — прежний интерфейс 2.0: флага 3.0 нет", FLAG not in b2)
        check("9. /?ui=2 не подключает лист оформления 3.0", SHEET not in b2)
        _INJ = ('<script>window.__UI3_MODE__=true;'
                "try{localStorage.setItem('farm_ui_version','3')}catch(e){}</script>"
                '<link rel="stylesheet" href="/ui3/ui3.css">')
        check("10. код 2.0 не удалён: страница 2.0 — ТА ЖЕ разметка, что и 3.0, без вставки флага",
              b1.replace(_INJ, "", 1) == b2, (len(b1), len(b2)))
        c3, b3 = get(port, "/ui3")
        check("11. /ui3 по-прежнему отдаёт 3.0", c3 == 200 and FLAG in b3 and SHEET in b3)
        check("12. переключатель 2.0/3.0 в шапке спрятан (v-if по флагу)",
              'v-if="uiSwitchVisible" class="fm-ui-switch"' in b1)
        c4, b4 = get(port, "/ui3/ui3.css")
        check("13. лист оформления 3.0 отдаётся", c4 == 200 and "html.ui3-mode" in b4)
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("14. рабочая папка данных не изменилась", prod_before == prod_after, set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)
print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
