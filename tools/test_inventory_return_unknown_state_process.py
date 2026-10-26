# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  29.09.2026 — склад 1.7.31 на НАСТОЯЩЕМ процессе программы: после перезапуска посреди печати
#  филамент не возвращается, пока состояние принтера неизвестно.
#
#  Набор-близнец tools/test_inventory_return_unknown_state.py (там — все сценарии на функциях
#  склада). Здесь то же доказывается на настоящем server.py, куда склад поставлен так же, как его
#  ставит владелец: .zip из исходников modules/inventory -> «Установить модуль» -> перезапуск.
#  Именно в настоящем процессе возникала причина дефекта: модули грузятся при запуске раньше, чем
#  подключаются принтеры, и первые секунды состояний принтеров нет вовсе.
#
#  Сценарий: в изолированной папке данных лежат две «ожидающие печати», с катушек уже списано по
#  20,8 г, печать шла на 40 %. Одна — на принтере фермы, чьё состояние неизвестно (воркеры принтеров
#  в изолированном режиме не запускаются — ровно первые секунды после перезапуска); другая — на
#  принтере, которого в ферме больше нет (положительный контроль: наблюдатель жив и работает на
#  настоящем ядре). Прежний склад вернул бы по 12,5 г на обе катушки в первые 5 секунд.
#
#  Программа поднимается по-настоящему (python server.py в изолированном режиме app/e2e_isolation:
#  своя временная папка данных, свой config, свободный порт, свой замок, без трея, браузера,
#  обнаружения и воркеров принтеров). Сеть наружу не нужна.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: рабочие DATA_DIR/config/БД/порт/замок не используются; принтерам ничего не
#  отправляется; временная папка удаляется в конце.
#
#  Запуск:  PYTHONIOENCODING=utf-8 python tools/test_inventory_return_unknown_state_process.py
#           (0 = пройдено)
# ============================================================================
import fnmatch
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.dont_write_bytecode = True
from app import e2e_isolation as ISO  # noqa: E402

MOD_SRC = os.path.join(REPO, "modules", "inventory")
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)
MOD_VERSION = json.load(open(os.path.join(MOD_SRC, "module.json"), encoding="utf-8"))["version"]
PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
SENTINEL = "INVENTORY_RETURN_PROCESS_SENTINEL_2909"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra))[:600] if (not cond and extra != "") else ""), flush=True)
    if not cond:
        fail += 1


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def listening(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                         creationflags=0x08000000).stdout
    return any(len(l.split()) >= 5 and l.split()[3] == "LISTENING" and l.split()[1] == "127.0.0.1:%d" % port
               for l in out.splitlines())


def wait(fn, t):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return None


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else (b"" if method != "GET" else None)
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": repr(e)}


def build_zip(dst):
    """Установочный .zip склада — по тем же правилам, что tools/build_inventory_zip.py (верхняя папка
    inventory/, без __pycache__, *.pyc, временных файлов и аварийного spool-states.generated.js)."""
    excl_dirs = {"__pycache__", ".git"}
    excl_globs = ["*.pyc", "*.pyo", "*.tmp", "*.bak", "*~", ".DS_Store", "Thumbs.db"]
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, dirs, files in os.walk(MOD_SRC):
            dirs[:] = [d for d in dirs if d not in excl_dirs]
            for fn in sorted(files):
                if any(fnmatch.fnmatch(fn, g) for g in excl_globs):
                    continue
                full = os.path.join(base, fn)
                rel = os.path.relpath(full, MOD_SRC).replace("\\", "/")
                if rel == "web/spool-states.generated.js":
                    continue
                zf.write(full, "inventory/" + rel)
    return dst


root = tempfile.mkdtemp(prefix="fm_e2e_invret_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD)), "временная папка внутри рабочей!"
work = os.path.join(root, "_work")
os.makedirs(work)
ZIP = build_zip(os.path.join(work, "3diwell-module-inventory.zip"))
port = free_port()
token = "INVRET_E2E_" + secrets.token_hex(8)
with open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
    json.dump({"token": token, "sentinel": SENTINEL}, f)
cfgp = os.path.join(root, "config.json")
json.dump({"server_port": port}, open(cfgp, "w", encoding="utf-8"))
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_INVRET_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "1",
            ISO.ENV_NO_MODULES: "0", "PYTHONDONTWRITEBYTECODE": "1"})
proc = None


def start():
    p = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                         cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=(0x00000008 | 0x00000200))
    ok = wait(lambda: call("GET", "/version")[1].get("version") == APP_VERSION if listening(port) else None, 150)
    return p, bool(ok)


def stop():
    with open(os.path.join(root, "stop.request"), "w", encoding="utf-8") as f:
        f.write(token)
    gone = wait(lambda: not listening(port), 60)
    if not gone and proc is not None and proc.poll() is None:
        proc.terminate()   # только СВОЙ процесс; рабочую программу не трогаем
        gone = wait(lambda: not listening(port), 20)
    try:
        os.unlink(os.path.join(root, "stop.request"))
    except Exception:
        pass
    if proc is not None:
        try:
            proc.wait(timeout=20)   # базы освобождены — их можно править
        except Exception:
            pass
    return bool(gone)


def inv_module():
    return next((m for m in call("GET", "/api/modules")[1].get("modules", []) if m.get("id") == "inventory"), {})


def db(name, ro=False):
    path = os.path.join(root, name)
    if ro:
        c = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=10)
    else:
        c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def pending_rows():
    c = db("farm_inventory.db", ro=True)
    try:
        return {r["id"]: dict(r) for r in c.execute("SELECT id, printer_id, status, note FROM inv_pending_prints")}
    finally:
        c.close()


def row_status(rid):
    """Состояние записи для ожидания; база на миг занята сервером — «пока не знаем», а не падение."""
    try:
        return pending_rows().get(rid, {}).get("status")
    except sqlite3.Error:
        return None


def spool_state(sid):
    c = db("farm_inventory.db", ro=True)
    try:
        rem = c.execute("SELECT weight_remaining_g FROM inv_spools WHERE id=?", (sid,)).fetchone()[0]
        ins = [dict(r) for r in c.execute("SELECT qty, reason FROM inv_ledger WHERE kind='in' AND ref_id=?", (sid,))]
        return round(float(rem), 2), ins
    finally:
        c.close()


print("изолированный экземпляр: порт %d, папка %s" % (port, root))
proc, ok = start()
check("A1. изолированный экземпляр поднялся (своя папка, порт, замок; воркеры принтеров выключены)", ok)
try:
    st, js = call("POST", "/api/modules/install-path", {"path": ZIP})
    check("A2. склад %s поставлен из .zip, как его ставит владелец" % MOD_VERSION,
          st == 200 and js.get("status") == "ok" and js.get("id") == "inventory" and js.get("version") == MOD_VERSION, js)
    check("A3. экземпляр остановлен штатно", stop())
    proc, ok = start()
    m = inv_module()
    check("A4. после перезапуска склад загружен: выпуск %s, все маршруты с правом из карты, «есть новее» нет" % MOD_VERSION,
          ok and m.get("state") == "loaded" and m.get("version") == MOD_VERSION
          and not m.get("admin_only_routes") and not m.get("skipped_routes") and not m.get("newer_version"), m)
    check("A5. экземпляр остановлен штатно (базы свободны для подготовки сценария)", stop())

    # ── сценарий: печать шла на 40 %, программа перезапускается ────────────────────────────────
    now = time.time()
    c = db("farm_printers.db")
    c.execute("INSERT INTO printers (id, name, type, ip, port, order_idx) VALUES (?,?,?,?,?,?)",
              ("e2e_live", "E2E в ферме", "demo", "", 0, 0))
    c.commit()
    c.close()
    c = db("farm_inventory.db")
    for sid, pid in (("sp_live", "e2e_live"), ("sp_gone", "e2e_gone"), ("sp_wait", "e2e_live")):
        c.execute("INSERT INTO inv_spools (id, ams_printer_id, ams_slot, weight_total_g, weight_remaining_g, status) "
                  "VALUES (?,?,?,?,?,?)", (sid, pid, -1, 1000.0, 210.2, "loaded"))
    rows = (("pp_live", "e2e_live", "sp_live", 1, 40.0, now - 600),     # печатал, состояние неизвестно
            ("pp_gone", "e2e_gone", "sp_gone", 1, 40.0, now - 600),     # принтера в ферме больше нет
            ("pp_wait", "e2e_live", "sp_wait", 0, 0.0, now - 1800))     # не видели старта, 30 мин назад
    for rid, pid, sid, seen, pct, ts in rows:
        c.execute("INSERT INTO inv_pending_prints (id, printer_id, fname, started_ts, seen_printing, last_percent, "
                  "deductions, status) VALUES (?,?,?,?,?,?,?,?)",
                  (rid, pid, "e2e.gcode", ts, seen, pct, json.dumps([[sid, 20.8]]), "active"))
    c.commit()
    c.close()

    proc, ok = start()
    check("B1. программа «перезапущена посреди печати» и поднялась", ok)
    closed = wait(lambda: row_status("pp_gone") == "done", 60)
    time.sleep(12)   # ещё два прохода наблюдателя (раз в 5 с)
    pr = pending_rows()
    check("B2. (контроль) наблюдатель возвратов жив на настоящем ядре: запись принтера, удалённого из фермы, "
          "закрыта без возврата", bool(closed) and pr["pp_gone"]["note"].startswith("принтер удалён из фермы")
          and spool_state("sp_gone") == (210.2, []), (pr.get("pp_gone"), spool_state("sp_gone")))
    check("B3. КЛЮЧЕВОЕ: печать на принтере фермы, чьё состояние после перезапуска неизвестно, — возврата нет, "
          "остаток 210,2, запись ждёт ответа принтера",
          pr["pp_live"]["status"] == "active" and spool_state("sp_live") == (210.2, []),
          (pr.get("pp_live"), spool_state("sp_live")))
    check("B4. КЛЮЧЕВОЕ: печать, старта которой не видели (30 минут назад), при неизвестном состоянии тоже не "
          "возвращается целиком", pr["pp_wait"]["status"] == "active" and spool_state("sp_wait") == (210.2, []),
          (pr.get("pp_wait"), spool_state("sp_wait")))
    check("B5. склад по-прежнему загружен и отвечает", inv_module().get("state") == "loaded"
          and call("GET", "/api/mod/inventory/summary")[0] == 200)
finally:
    check("Z1. изолированный экземпляр остановлен", stop())
    shutil.rmtree(root, ignore_errors=True)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
