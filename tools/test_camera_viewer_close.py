# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Камеры: поток зрителя закрывается сразу, код доступа принтера не попадает в журнал (12.10.2026).

ЗАЧЕМ. При работе над камерой FlashForge измерено: StreamingResponse (Starlette 1.6) синхронный
генератор при уходе зрителя не закрывает, и finally генератора ждёт сборщика мусора. Для камер это
значило: окно закрыли, а подписка висит — владелец потока Bambu не гаснет (ffmpeg и сессия камеры
живут дальше, а принтер держит одну-две сессии), прокси Klipper/Creality держит соединение со
стримером принтера. Второе: ключ владельца потока Bambu — «адрес|код доступа», и он целиком писался
в farm.log («[CAM] 10.0.0.5|<код>: владелец потока поднят…»), а журнал владелец отправляет разработке.

  A. исходник: все HTTP-потоки камер отдаются через _ViewerStreamingResponse;
  B. оба раздатчика (app/camera_hub.py, app/camera_fmp4.py) пишут в журнал только адрес;
  C. НАСТОЯЩИЙ процесс программы: камера Klipper (прокси стримера) — окно закрыли, соединение со
     стримером принтера закрыто за секунды, повторное открытие работает.

Сети наружу нет: имитаторы и программа — на 127.0.0.1. Рабочие данные и принтеры не трогаются.
Запуск: python tools/test_camera_viewer_close.py   (0 = пройдено)
"""
import ast
import http.server
import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app import camera_hub as CH  # noqa: E402
from app import camera_fmp4 as CF  # noqa: E402
from app import e2e_isolation as ISO  # noqa: E402

fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""), flush=True)
    if not ok:
        fails.append(name)


SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

# ════════════════════════════════════════════════════════════════════════════
print("\n--- A. все HTTP-потоки камер закрываются при уходе зрителя ---")
streams = re.findall(r"(?<![A-Za-z_])(_?[A-Za-z]*StreamingResponse)\(\s*(_[a-z0-9_]+)\(", SRC)
cam = [(cls, gen) for cls, gen in streams if "camera" in gen or "hub" in gen]
check("A1. потоки камер найдены: Bambu (владелец, P1, fMP4), Klipper/Creality (прокси), FlashForge",
      {g for _, g in cam} >= {"_bambu_p1_camera_frames", "_bambu_hub_frames", "_bambu_hub_fmp4", "_klipper_camera_proxy",
                              "_ff_hub_frames"}, cam)
check("A2. каждый из них — _ViewerStreamingResponse (закрывает генератор, как только ответ окончен)",
      cam and all(cls == "_ViewerStreamingResponse" for cls, _ in cam), [c for c in cam if c[0] != "_ViewerStreamingResponse"])
tree = ast.parse(SRC)
vsr = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_ViewerStreamingResponse"]
body = ast.get_source_segment(SRC, vsr[0]) if vsr else ""
check("A3. закрытие — в finally ответа и без ожидания (быстро: генератор лишь снимает подписку)",
      "finally:" in body and ".close()" in body and "await super().__call__" in body)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- B. код доступа принтера не попадает в журнал ---")
CODE = "SECRETCODE" + secrets.token_hex(3)
KEY = "10.0.0.5|" + CODE


class Log(object):
    def __init__(self):
        self.lines = []

    def _w(self, msg, *a):
        self.lines.append(msg % a if a else msg)
    info = warning = debug = error = _w


class FrameSrc(object):
    def __init__(self, key):
        self.closed = False

    def frames(self):
        for i in range(3):
            if self.closed:
                return
            yield b"--frame\r\n" + bytes([i])
            time.sleep(0.05)
        raise OSError("конец")

    def close(self):
        self.closed = True


L1 = Log()
names_seen = []
hub = CH.CameraHub(open_source=FrameSrc, first_frame_timeout=1.0, stall_timeout=0.5, idle_grace=0.2,
                   retry_base=0.1, retry_max=0.2, log=L1)
sub = hub.subscribe(KEY)
names_seen += [t.name for t in threading.enumerate()]
got = []
for f in sub.frames(timeout=2.0):
    got.append(f)
    if len(got) >= 2:
        break
sub.close()
for _ in range(10):
    hub.tick()
    time.sleep(0.1)
hub.shutdown()
check("B1. раздатчик кадров работает и пишет в журнал (поднят, кадр, остановлен)",
      len(got) == 2 and any("поднят" in x for x in L1.lines) and any("остановлен" in x for x in L1.lines), L1.lines[:4])
check("B2. в журнале раздатчика кадров только адрес — кода доступа нет ни в одной строке",
      L1.lines and all(CODE not in x for x in L1.lines) and any("10.0.0.5" in x for x in L1.lines),
      [x for x in L1.lines if CODE in x][:2])
check("B3. и в имени потока владельца кода нет", all(CODE not in n for n in names_seen), [n for n in names_seen if CODE in n])


class Fmp4Src(object):
    def __init__(self, key):
        self.closed = False

    def chunks(self):
        raise OSError("нет принтера")

    def close(self):
        self.closed = True


L2 = Log()
hub2 = CF.Fmp4Hub(open_source=Fmp4Src, first_data_timeout=0.5, stall_timeout=0.5, idle_grace=0.2,
                  retry_base=0.1, retry_max=0.2, log=L2)
s2 = hub2.subscribe(KEY)
for _ in range(8):
    hub2.tick()
    time.sleep(0.1)
s2.close()
for _ in range(5):
    hub2.tick()
    time.sleep(0.1)
hub2.shutdown()
check("B4. раздатчик без перекодирования (fMP4) тоже пишет только адрес",
      L2.lines and all(CODE not in x for x in L2.lines) and any("10.0.0.5" in x for x in L2.lines), L2.lines[:4])
check("B5. ключ для журнала: «адрес|код» -> «адрес|…»; адрес потока без «|» — как есть",
      CH.log_key(KEY) == "10.0.0.5|…" and CF.log_key(KEY) == "10.0.0.5|…"
      and CH.log_key("http://1.2.3.4:8080/?action=stream") == "http://1.2.3.4:8080/?action=stream")

# ════════════════════════════════════════════════════════════════════════════
print("\n--- C. настоящий процесс: камера Klipper отпускает стример принтера ---")


class Sim(object):
    cam_port = 0
    active = 0
    total = 0
    lock = threading.Lock()


SIM = Sim()
FRAMES = [b"\xff\xd8" + (b"KL-%02d-" % i) * 30 + b"\xff\xd9" for i in range(5)]


class Moon(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/server/webcams/list"):
            out = {"result": {"webcams": [{"name": "cam", "stream_url": "http://127.0.0.1:%d/?action=stream" % SIM.cam_port}]}}
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    do_POST = do_GET


class Cam(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        with SIM.lock:
            SIM.active += 1
            SIM.total += 1
        try:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=bd")
            self.end_headers()
            i = 0
            while True:
                j = FRAMES[i % len(FRAMES)]
                self.wfile.write(b"--bd\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(j) + j + b"\r\n")
                self.wfile.flush()
                i += 1
                time.sleep(0.1)
        except (ConnectionError, OSError):
            pass
        finally:
            with SIM.lock:
                SIM.active -= 1


class TServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def listening(port):
    s = socket.socket(); s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def wait(fn, t):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.3)
    return None


moon_port, SIM.cam_port = free_port(), free_port()
for srv in (TServer(("127.0.0.1", moon_port), Moon), TServer(("127.0.0.1", SIM.cam_port), Cam)):
    threading.Thread(target=srv.serve_forever, daemon=True).start()

PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
root = tempfile.mkdtemp(prefix="fm_e2e_camclose_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD) + os.sep)
port = free_port()
token = "CAMCLOSE_E2E_" + secrets.token_hex(8)
json.dump({"token": token, "sentinel": "CAMCLOSE_E2E_1210"}, open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8"))
cfgp = os.path.join(root, "config.json")
json.dump({"server_port": port}, open(cfgp, "w", encoding="utf-8"))
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_CAMCLOSE_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "1",
            ISO.ENV_NO_MODULES: "1", "PYTHONDONTWRITEBYTECODE": "1"})
SRC_VER = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
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


def view(n):
    """Зритель: открыл камеру, взял n кадров, закрыл окно."""
    r = urllib.request.urlopen("http://127.0.0.1:%d/api/printer/k1/camera" % port, timeout=20)
    buf, seen = b"", 0
    try:
        end = time.monotonic() + 20
        while seen < n and time.monotonic() < end:
            buf += r.read1(65536)
            seen = buf.count(b"\xff\xd9")
        return seen
    finally:
        r.close()


proc = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                        cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=(0x00000008 | 0x00000200))
try:
    up = wait(lambda: listening(port) and call("GET", "/version")[1].get("version") == SRC_VER, 150)
    check("C1. изолированный экземпляр поднялся (своя папка, порт, замок)", bool(up))
    st, js = call("POST", "/api/printers/save", [{"id": "k1", "name": "Klipper cam", "type": "klipper", "ip": "127.0.0.1",
                                                  "port": moon_port, "model": "Voron 2.4 300"}])
    check("C2. принтер Klipper сохранён", st == 200, (st, js))
    n = view(3)
    check("C3. камера Klipper показывает кадры стримера принтера", n >= 3, n)
    gone = wait(lambda: SIM.active == 0, 10)
    check("C4. окно закрыли — соединение программы со стримером принтера закрыто за секунды", bool(gone), SIM.active)
    n2 = view(2)
    gone2 = wait(lambda: SIM.active == 0, 10)
    check("C5. повторное открытие работает и снова отпускает принтер", n2 >= 2 and bool(gone2) and SIM.total >= 2,
          (n2, SIM.active, SIM.total))
finally:
    try:
        open(os.path.join(root, "stop.request"), "w", encoding="utf-8").write(token)
        wait(lambda: not listening(port), 60)
    except Exception:
        pass
    if proc.poll() is None and listening(port):
        proc.terminate()
    shutil.rmtree(root, ignore_errors=True)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (len(names) - len(fails), len(fails)))
for f in fails:
    print("  FAIL:", f)
sys.exit(1 if fails else 0)
