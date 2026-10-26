# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  26.09.2026 — «Запомнить это устройство» и «любая версия модуля» на НАСТОЯЩЕМ процессе программы.
#
#  ЗАЧЕМ. Набор tools/test_remembered_devices.py изображает перезапуск сбросом памяти. Здесь
#  программа поднимается по-настоящему (python server.py в изолированном режиме app/e2e_isolation:
#  своя временная папка данных, свой config, свободный порт, свой замок одиночного экземпляра, без
#  трея, браузера, обнаружения и принтеров), останавливается штатно (файл-просьба в своей же папке)
#  и поднимается снова. Проверяется главное требование владельца: телефон остаётся в системе после
#  перезапуска программы, а отозванный — не возвращается. Заодно: старая версия модуля (0.2.0 без
#  core_contract) загружается и отвечает по своему праву, а в списке стоит «есть новее».
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: рабочие DATA_DIR/config/БД/порт/замок не используются, рабочая программа не
#  останавливается; принтерам ничего не отправляется; временная папка удаляется в конце.
#
#  Запуск:  PYTHONIOENCODING=utf-8 python tools/test_remembered_devices_process.py   (0 = пройдено)
# ============================================================================
import json, os, re, secrets, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app import e2e_isolation as ISO

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)
PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
fails = []
names = []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,)) if (not ok and extra != "") else ""), flush=True)
    if not ok:
        fails.append(name)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def listening(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=0x08000000).stdout
    return any(len(l.split()) >= 5 and l.split()[3] == "LISTENING" and l.split()[1] == "127.0.0.1:%d" % port for l in out.splitlines())


def wait(fn, t):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return None


def call(port, method, path, body=None, cookie="", ua=""):
    data = json.dumps(body).encode("utf-8") if body is not None else (b"" if method != "GET" else None)
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", "fm_session=" + cookie)
    if ua:
        req.add_header("User-Agent", ua)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            sc = r.headers.get_all("Set-Cookie") or []
            return r.status, json.loads(r.read().decode("utf-8") or "{}"), sc
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}"), e.headers.get_all("Set-Cookie") or []
        except Exception:
            return e.code, {}, []


def cookie_of(setcookies):
    for c in setcookies:
        m = re.match(r"fm_session=([^;]*)", c)
        if m:
            return m.group(1), c
    return "", ""


root = tempfile.mkdtemp(prefix="fm_e2e_dev_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD)), "временная папка внутри рабочей!"
port = free_port()
token = "DEVICE_E2E_" + secrets.token_hex(8)
with open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
    json.dump({"token": token, "sentinel": "DEVICE_E2E_0926"}, f)
cfgp = os.path.join(root, "config.json")
with open(cfgp, "w", encoding="utf-8") as f:
    json.dump({"server_port": port}, f)
# старая версия модуля качества (0.2.0 без core_contract) — раньше ядро её не загружало
md = os.path.join(root, "modules", "quality")
shutil.copytree(os.path.join(REPO, "modules", "quality"), md, ignore=shutil.ignore_patterns("__pycache__"))
mj = json.load(open(os.path.join(md, "module.json"), encoding="utf-8"))
mj["version"] = "0.2.0"
json.dump(mj, open(os.path.join(md, "module.json"), "w", encoding="utf-8"), ensure_ascii=False)

env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_DEV_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "1",
            ISO.ENV_NO_MODULES: "0"})


def start():
    p = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                         cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=(0x00000008 | 0x00000200))
    ok = wait(lambda: call(port, "GET", "/version")[1].get("version") == APP_VERSION if listening(port) else None, 150)
    return p, bool(ok)


def stop():
    with open(os.path.join(root, "stop.request"), "w", encoding="utf-8") as f:
        f.write(token)
    gone = wait(lambda: not listening(port), 60)
    if not gone and proc is not None and proc.poll() is None:
        proc.terminate()   # только СВОЙ процесс, по его идентификатору; рабочую программу не трогаем
        gone = wait(lambda: not listening(port), 20)
    try:
        os.unlink(os.path.join(root, "stop.request"))
    except Exception:
        pass
    return bool(gone)


UA = "Dalvik/2.1.0 (Linux; U; Android 14; SM-S918B Build/UP1A.231005.007)"
print("изолированный экземпляр: порт %d, папка %s" % (port, root))
proc = None
proc, ok = start()
check("E1. изолированный экземпляр поднялся (своя папка, порт, замок)", ok)
try:
    st, js, sc = call(port, "POST", "/api/auth/setup", {"username": "boss", "password": "Admin-pass-2"})
    admin, _ = cookie_of(sc)
    check("E2. защита включена, администратор создан", st == 200 and js.get("ok") and admin)
    st, js, _ = call(port, "POST", "/api/auth/users", {"username": "ivan", "password": "Phone-pass-1", "role": "operator"}, admin)
    check("E3. пользователь телефона создан", st == 200 and js.get("ok"), js)
    st, js, sc = call(port, "POST", "/api/auth/login", {"username": "ivan", "password": "Phone-pass-1", "remember_device": True}, ua=UA)
    dev, raw = cookie_of(sc)
    check("E4. вход с «Запомнить это устройство»: токен устройства и срок cookie в годах",
          st == 200 and (js.get("device") or {}).get("persistent") is True and dev.startswith("fmd_")
          and re.search(r"Max-Age=(\d+)", raw, re.I) and int(re.search(r"Max-Age=(\d+)", raw, re.I).group(1)) > 10 ** 8, (st, js, raw[:120]))
    st, js, _ = call(port, "GET", "/api/auth/status", cookie=dev)
    check("E5. телефон вошёл: status authenticated и device", js.get("authenticated") is True and js.get("device"), js)
    st, js, _ = call(port, "GET", "/api/mod/quality/summary", cookie=dev)
    check("E6. СТАРЫЙ модуль качества 0.2.0 загружен и отвечает оператору по своему праву (view)", st == 200, (st, js))
    st, js, _ = call(port, "GET", "/api/modules", cookie=admin)
    q = next((m for m in js.get("modules", []) if m.get("id") == "quality"), {})
    check("E7. в списке модулей: loaded и пометка «есть новее»", q.get("state") == "loaded" and q.get("newer_version") == "0.2.3", q)

    check("E8. штатная остановка процесса", stop())
    proc, ok = start()
    check("E9. процесс запущен заново", ok)
    st, js, _ = call(port, "GET", "/api/auth/status", cookie=dev)
    check("E10. ГЛАВНОЕ: после перезапуска программы телефон по-прежнему в системе", js.get("authenticated") is True
          and (js.get("device") or {}).get("persistent") is True, js)
    st, js, _ = call(port, "GET", "/api/auth/status", cookie=admin)
    check("E11. обычная сессия, как и раньше, закончилась с перезапуском", js.get("authenticated") is False, js)
    st, js, sc = call(port, "POST", "/api/auth/login", {"username": "boss", "password": "Admin-pass-2"})
    admin, _ = cookie_of(sc)
    st, js, _ = call(port, "GET", "/api/auth/users", cookie=admin)
    devs = js.get("devices") or []
    check("E12. администратор видит запомненный телефон в списке (без токена)", len(devs) == 1 and devs[0]["name"] == "SM-S918B"
          and dev not in json.dumps(js), devs)
    st, js, _ = call(port, "PATCH", "/api/auth/users/%s" % devs[0]["user_id"], {"revoke_device": devs[0]["id"]}, admin)
    check("E13. «Отозвать»: ok и записано на диск", st == 200 and js.get("ok") and js.get("persisted") is True, js)
    st, js, _ = call(port, "GET", "/api/auth/status", cookie=dev)
    check("E14. отозванный телефон сразу не принимается", js.get("authenticated") is False, js)
    check("E15. остановка", stop())
    proc, ok = start()
    st, js, _ = call(port, "GET", "/api/auth/status", cookie=dev)
    check("E16. после второго перезапуска отозванный телефон не вернулся", ok and js.get("authenticated") is False, js)
finally:
    stop()
    shutil.rmtree(root, ignore_errors=True)
print("ИТОГО: проверок %d, провалено %d" % (len(names), len(fails)))
sys.exit(1 if fails else 0)
