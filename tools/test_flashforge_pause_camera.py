# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""FlashForge Adventurer 5M / 5M Pro: пауза и камера (12.10.2026).

ЗАЧЕМ. Клиент: на 5M и 5M Pro после «Паузы» из программы принтер показывался «Свободен», хотя стоял на
паузе посреди печати; камера 5M Pro в программе не работала. Причины:
  · состояние принтера (detail.status) разбиралось по короткому списку слов, и всё незнакомое — в том
    числе «pause», которым часть прошивок FlashForge называет паузу (открытая библиотека FlashForge
    ff-5mp-api, MachineInfo.getMachineState), — становилось «Свободен»;
  · у типа «flashforge» не было ни кнопки камеры, ни потока: камеру 5M Pro отдаёт стример самого
    принтера, http://<адрес>:8080/?action=stream (там же, Endpoints.CAMERA_STREAM_PORT = 8080), а
    адрес потока принтер называет в ответе /detail (cameraStreamUrl).

Принтера у разработки нет, поэтому:
  A. таблица состояний и разбор адреса камеры — прямо из исходника server.py;
  B. нарезка чужого MJPEG-потока на кадры (app/mjpeg_split.py) — на байтах;
  C. НАСТОЯЩИЙ процесс программы (изолированный экземпляр) против имитатора FlashForge по тому же
     контракту: /detail и /control на одном порту, стример камеры — на другом. Пауза из программы,
     «pause» от принтера — карточка «пауза»; незнакомое слово — «Занят»; камера — кадры принтера,
     и ОДНО соединение со стримером на двух зрителей; камеры нет — честный 404 сразу.

16.10.2026 (R-147, R-141): «Свободен» — только по доказанному покою («ready»/«idle»). Пустое состояние —
«Занят»; «canceling» (идёт отмена) — знакомое слово, «Занят»; отказ принтера на /detail (code 1, без detail:
неверный серийный номер или код) — «не в сети» с причиной и одной строкой в журнале. Материал задания со
слов принтера (rightFilamentType) — на карточке только во время печати или паузы, для показа.

Сети наружу нет: всё на 127.0.0.1. Рабочие данные, порт и принтеры владельца не трогаются.
Запуск: python tools/test_flashforge_pause_camera.py   (0 = пройдено)
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
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app import mjpeg_split as MS  # noqa: E402
from app import printer_state_policy as SP  # noqa: E402
from app import printer_job_lifecycle as PJL  # noqa: E402
from app import e2e_isolation as ISO  # noqa: E402
from websockets.sync.client import connect as ws_connect  # noqa: E402

fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""), flush=True)
    if not ok:
        fails.append(name)


SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)


def pick(*wanted):
    """Определения верхнего уровня server.py по именам — исполняются отдельно, без запуска программы."""
    out = []
    for node in TREE.body:
        nm = getattr(node, "name", None)
        if nm is None and isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
        if nm in wanted:
            out.append(ast.get_source_segment(SRC, node))
    return "\n\n".join(out)


# ════════════════════════════════════════════════════════════════════════════
print("\n--- A. состояние принтера и адрес камеры (из server.py) ---")
ns = {}
exec(pick("_FF_CARD_STATUS", "_ff_card_status"), ns)
fs = ns["_ff_card_status"]
check("A1. «pause», «paused», «pausing» — пауза (раньше «pause» давало «Свободен»)",
      [fs(x) for x in ("pause", "paused", "pausing", "PAUSE")] == ["PAUSED"] * 4)
check("A2. печать, нагрев, «busy» — печатает; «completed» — готово; ошибка и отмена — сбой (как раньше)",
      [fs(x) for x in ("printing", "heating", "busy", "completed", "error", "cancel")]
      == ["RUNNING", "RUNNING", "RUNNING", "FINISH", "FAILED", "FAILED"])
#  16.10.2026 (R-147): пустое или отсутствующее состояние больше НЕ «Свободен» — принтер не доказал покой.
check("A3. свободен — только «ready» и «idle»; пустое поле и его отсутствие — «Занят» (было «Свободен»)",
      [fs(x) for x in ("ready", "idle", "READY")] == ["IDLE"] * 3 and [fs(x) for x in ("", None)] == ["BUSY"] * 2)
check("A3а. «canceling» (идёт отмена, слово прошивки) — «Занят» и считается знакомым словом",
      fs("canceling") == "BUSY" and "canceling" in ns["_FF_CARD_STATUS"])
ns_ok = {}
exec(pick("FF_NO_ACCESS_TEXT", "_ff_reply_ok"), ns_ok)
_ok = ns_ok["_ff_reply_ok"]
check("A3б. ответ принимается только с code 0 и блоком detail; отказ (code 1) и ответ без detail — нет",
      _ok({"code": 0, "message": "Success", "detail": {"status": "ready"}}) and _ok({"code": "0", "detail": {}})
      and not _ok({"code": 1, "message": "error"}) and not _ok({"code": 0, "message": "Success"})
      and not _ok({"code": 0, "data": {"status": "ready"}}) and not _ok({"detail": {"status": "ready"}})
      and not _ok(None) and not _ok([]))
check("A4. калибровка, загрузка файла и ЛЮБОЕ незнакомое слово — «Занят», а не «Свободен»",
      [fs(x) for x in ("calibrate_doing", "downloading", "something_new")] == ["BUSY"] * 3)
check("A5. таблица ядра: «pause» у FlashForge — пауза (для решений о печати и отмене)",
      SP.normalize_raw("flashforge", "pause") == SP.Lifecycle.PAUSED
      and PJL.normalize_state("flashforge", "pause") == PJL.normalize_state("flashforge", "paused"))
ns2 = {}
exec(pick("_ACTIVE_RAW"), ns2)
check("A6. на паузе и при калибровке «Стол очищен» не подтверждается — задание идёт",
      {"pause", "paused", "calibrate_doing"} <= set(ns2["_ACTIVE_RAW"]["flashforge"]))
ns3 = {"urllib": urllib}
exec(pick("_FF_CAM_URL", "FF_CAMERA_PORT", "_ff_note_camera", "_ff_camera_url"), ns3)
note, url = ns3["_ff_note_camera"], ns3["_ff_camera_url"]
check("A7. без адреса от принтера — штатный поток стримера: http://<адрес>:8080/?action=stream",
      url("p1", "192.168.1.50") == "http://192.168.1.50:8080/?action=stream")
note("p1", "192.168.1.50", "http://192.168.1.50:8080/?action=stream&x=1")
check("A8. адрес, который назвал сам принтер (cameraStreamUrl), берётся", url("p1", "192.168.1.50") == "http://192.168.1.50:8080/?action=stream&x=1")
note("p1", "192.168.1.50", "http://10.9.9.9:8080/?action=stream")
a9 = url("p1", "192.168.1.50")
note("p1", "192.168.1.50", "file:///C:/Windows/win.ini")
a9b = url("p1", "192.168.1.50")
check("A9. адрес на ДРУГОЙ узел или не http — не берётся (программа не ходит, куда скажут)",
      a9 == a9b == "http://192.168.1.50:8080/?action=stream", (a9, a9b))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- B. нарезка потока камеры на кадры (app/mjpeg_split.py) ---")
J1 = b"\xff\xd8" + b"\x10" * 300 + b"\xff\xd9"
J2 = b"\xff\xd8" + bytes(range(256)) * 3 + b"\xff\xd9"
J3 = b"\xff\xd8" + b"\xff\xd9inside" + b"\x22" * 50 + b"\xff\xd9"      # метка конца ВНУТРИ кадра


def part(j, with_len=True):
    h = b"--boundarydonotcross\r\nContent-Type: image/jpeg\r\n"
    if with_len:
        h += b"Content-Length: %d\r\nX-Timestamp: 1.5\r\n" % len(j)
    return h + b"\r\n" + j + b"\r\n"


stream = part(J1) + part(J2) + part(J3)
sp = MS.MjpegSplitter()
check("B1. поток mjpg-streamer (с Content-Length) — целые кадры, байт в байт, даже с меткой конца внутри",
      sp.feed(stream) == [J1, J2, J3])
sp = MS.MjpegSplitter()
got = []
for i in range(0, len(stream), 7):
    got += sp.feed(stream[i:i + 7])
check("B2. поток кусками по 7 байт — те же кадры (граница кадра в любом месте)", got == [J1, J2, J3])
sp = MS.MjpegSplitter()
check("B3. без Content-Length — по меткам начала и конца JPEG", sp.feed(part(J1, False) + part(J2, False)) == [J1, J2])
sp = MS.MjpegSplitter(max_frame=1000)
junk = sp.feed(b"\xff\xd8" + b"\x00" * 5000)
check("B4. мусор без конца кадра сверх предела — отброшен, память не растёт", junk == [] and len(sp._buf) <= 4096
      and sp.feed(part(J1)) == [J1], len(sp._buf))
check("B5. часть для браузера — граница «frame», как у камер Bambu",
      MS.browser_part(J1) == b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + J1 + b"\r\n")

# ════════════════════════════════════════════════════════════════════════════
print("\n--- C. настоящий процесс программы против имитатора FlashForge ---")


class Sim(object):
    status = "printing"
    deny = False                   # «принтер» отвечает отказом на /detail (неверный код и т. п.)
    refuse = False          # 16.10.2026 (R-145, R-147): принтер отвечает на /control отказом (code 1)
    cam_url = ""
    controls = []
    cam_conns = 0
    cam_active = 0
    cam_max = 0
    lock = threading.Lock()


SIM = Sim()
SERIAL, CHECK = "SNFF5MPRO01", "chk" + secrets.token_hex(3)


class Api(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        if body.get("serialNumber") != SERIAL or body.get("checkCode") != CHECK:
            out = {"code": 1, "message": "auth"}
        elif self.path == "/detail" and SIM.deny:
            out = {"code": 1, "message": "error"}
        elif self.path == "/detail":
            #  rightFilamentType — как у настоящего 5M (ff-5mp-hass#4): в покое пусто, при печати — материал задания.
            out = {"code": 0, "message": "Success", "detail": {
                "status": SIM.status, "printProgress": 0.3, "printFileName": "/data/part.gcode", "estimatedTime": 600,
                "rightTemp": 220.0, "rightTargetTemp": 220.0, "platTemp": 60.0, "platTargetTemp": 60.0,
                "rightFilamentType": "PLA" if SIM.status in ("printing", "pause") else "", "leftFilamentType": "",
                "cameraStreamUrl": SIM.cam_url, "errorCode": ""}}
        elif self.path == "/control" and SIM.refuse:
            SIM.controls.append(body.get("payload") or body)
            out = {"code": 1, "message": "Printer busy"}
        elif self.path == "/control":
            SIM.controls.append(body.get("payload") or body)
            p = body.get("payload") or {}
            act = (p.get("args") or {}).get("action")
            if p.get("cmd") == "jobCtl_cmd" and act == "pause":
                SIM.status = "pause"               # так паузу пишут прошивки, из-за которых и был «Свободен»
            elif p.get("cmd") == "jobCtl_cmd" and act == "continue":
                SIM.status = "printing"
            out = {"code": 0, "message": "Success"}
        else:
            out = {"code": 1, "message": "unknown"}
        data = json.dumps(out).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


FRAMES = [b"\xff\xd8" + (b"FRAME-%02d-" % i) * 40 + b"\xff\xd9" for i in range(6)]


class Cam(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        if not self.path.startswith("/?action=stream"):
            self.send_response(404)
            self.end_headers()
            return
        with SIM.lock:
            SIM.cam_conns += 1
            SIM.cam_active += 1
            SIM.cam_max = max(SIM.cam_max, SIM.cam_active)
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace;boundary=boundarydonotcross")
        self.end_headers()
        i = 0
        try:
            while True:
                j = FRAMES[i % len(FRAMES)]
                self.wfile.write(b"--boundarydonotcross\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n"
                                 b"X-Timestamp: %d.0\r\n\r\n" % (len(j), i) + j + b"\r\n")
                self.wfile.flush()
                i += 1
                time.sleep(0.1)
        except (ConnectionError, OSError):
            return
        finally:
            with SIM.lock:
                SIM.cam_active -= 1


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


api_port, cam_port, dead_port = free_port(), free_port(), free_port()
SIM.cam_url = "http://127.0.0.1:%d/?action=stream" % cam_port
for srv in (TServer(("127.0.0.1", api_port), Api), TServer(("127.0.0.1", cam_port), Cam)):
    threading.Thread(target=srv.serve_forever, daemon=True).start()

PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
root = tempfile.mkdtemp(prefix="fm_e2e_ffcam_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD) + os.sep)
port = free_port()
token = "FFCAM_E2E_" + secrets.token_hex(8)
json.dump({"token": token, "sentinel": "FFCAM_E2E_1210"}, open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8"))
cfgp = os.path.join(root, "config.json")
json.dump({"server_port": port}, open(cfgp, "w", encoding="utf-8"))
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_FFCAM_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "0",
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


CARD = {}
CARD_HIST = []                     # все состояния карточки подряд — «ни разу не Свободен» проверяется по ним


def ws_reader():
    """Карточка принтера — из того же канала /ws, что видит окно программы."""
    while True:
        try:
            with ws_connect("ws://127.0.0.1:%d/ws" % port, open_timeout=5, max_size=8 * 1024 * 1024) as c:
                while True:
                    m = json.loads(c.recv(timeout=60))
                    if isinstance(m, dict) and "ff1" in m and isinstance(m["ff1"], dict):
                        CARD.clear()
                        CARD.update(m["ff1"])
                        CARD_HIST.append(m["ff1"].get("status"))
        except Exception:
            time.sleep(1.0)


def read_frames(n, timeout=20):
    """Зритель: читает поток камеры программы до n частей «--frame» -> список JPEG."""
    r = urllib.request.urlopen("http://127.0.0.1:%d/api/printer/ff1/camera" % port, timeout=timeout)
    buf, out = b"", []
    end = time.monotonic() + timeout
    try:
        while len(out) < n and time.monotonic() < end:
            buf += r.read1(65536)
            while True:
                m = re.search(rb"--frame\r\nContent-Type: image/jpeg\r\n\r\n", buf)
                if not m:
                    break
                e = buf.find(b"\xff\xd9", m.end())
                if e < 0:
                    break
                out.append(buf[m.end():e + 2])
                buf = buf[e + 2:]
        return out, r.headers.get("Content-Type")
    finally:
        r.close()


proc = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                        cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=(0x00000008 | 0x00000200))
try:
    up = wait(lambda: listening(port) and call("GET", "/version")[1].get("version") == SRC_VER, 150)
    check("C1. изолированный экземпляр поднялся (своя папка, порт, замок)", bool(up))
    st, js = call("POST", "/api/printers/save", [{"id": "ff1", "name": "AD5M Pro test", "type": "flashforge", "ip": "127.0.0.1",
                                                  "port": api_port, "token": SERIAL + ":" + CHECK, "serial": SERIAL,
                                                  "model": "Flashforge Adventurer 5M Pro"}])
    check("C2. принтер типа «flashforge» сохранён", st == 200, (st, js))
    cur = lambda: dict(CARD)
    threading.Thread(target=ws_reader, daemon=True).start()
    c = wait(lambda: cur().get("status") == "RUNNING" and cur(), 40)
    check("C3. карточка: печать идёт по /detail; принтер сообщил о камере — признак «есть камера»",
          bool(c) and c.get("percent") == 30 and c.get("has_camera") is True, cur())
    check("C3а. при печати карточка знает материал задания со слов принтера (только для показа)",
          bool(c) and c.get("job_material") == "PLA", cur())
    st, js = call("POST", "/api/printer/ff1/cmd", {"cmd": "pause"})
    sent = wait(lambda: [x for x in SIM.controls if x.get("cmd") == "jobCtl_cmd" and (x.get("args") or {}).get("action") == "pause"], 10)
    c = wait(lambda: cur().get("status") == "PAUSED" and cur(), 20)
    time.sleep(3)
    check("C4. ГЛАВНОЕ: пауза из программы — принтер пишет «pause», карточка «На паузе», НЕ «Свободен» (и держится)",
          bool(sent) and bool(c) and cur().get("status") == "PAUSED" and cur().get("status_raw") == "pause", (js, cur()))
    st, js = call("POST", "/api/printer/ff1/cmd", {"cmd": "resume"})
    c = wait(lambda: cur().get("status") == "RUNNING" and cur(), 20)
    check("C5. продолжение — снова «печатает»", bool(c) and any((x.get("args") or {}).get("action") == "continue" for x in SIM.controls))
    #  16.10.2026 (R-145, R-147): ответ принтера читается у паузы, продолжения и нагрева, как у «стоп».
    SIM.refuse = True
    st, js = call("POST", "/api/printer/ff1/cmd", {"cmd": "pause"})
    SIM.refuse = False
    time.sleep(2)
    check("C5а. принтер отказал в паузе (code 1) — программа говорит «принтер не подтвердил» (502), а не «ок»; печать идёт",
          st == 502 and js.get("reason") == "command_not_confirmed" and cur().get("status") == "RUNNING", (st, js, cur()))
    st, js = call("POST", "/api/printer/ff1/cmd", {"cmd": "bed", "val": "65"})
    check("C5б. принятая принтером команда нагрева — 200 ok", st == 200 and js.get("status") == "ok", (st, js))
    SIM.status = "something_new"
    c = wait(lambda: cur().get("status") == "BUSY" and cur(), 20)
    logp = os.path.join(root, "logs", "farm.log")
    logged = wait(lambda: os.path.isfile(logp) and "незнакомое состояние принтера 'something_new'" in open(logp, encoding="utf-8", errors="replace").read(), 10)
    check("C6. незнакомое состояние — «Занят» (не «Свободен»), слово один раз в журнале для разбора", bool(c) and bool(logged), cur())
    SIM.status = "canceling"
    c = wait(lambda: cur().get("status_raw") == "canceling" and cur(), 20)
    time.sleep(2.5)
    _lt = open(logp, encoding="utf-8", errors="replace").read() if os.path.isfile(logp) else ""
    check("C6а. «canceling» (идёт отмена) — «Занят», и журнал не засоряется строкой «незнакомое состояние»",
          bool(c) and c.get("status") == "BUSY" and "незнакомое состояние принтера 'canceling'" not in _lt, (cur(), _lt[-300:]))
    SIM.status = ""
    c = wait(lambda: cur().get("status_raw") == "" and cur(), 20)
    check("C6б. пустое состояние от принтера — «Занят», не «Свободен»", bool(c) and c.get("status") == "BUSY", cur())
    SIM.status = "ready"
    c = wait(lambda: cur().get("status") == "IDLE" and cur(), 20)
    check("C7. «ready» — свободен; материала задания в покое нет (5M в покое его не сообщает)",
          bool(c) and c.get("job_material") == "", cur())

    # ── камера ──
    frames, ctype = read_frames(3)
    check("C8. камера: кадры принтера доходят до окна байт в байт (поток MJPEG, граница «frame»)",
          len(frames) == 3 and all(f in FRAMES for f in frames) and "boundary=frame" in str(ctype), (len(frames), ctype))
    gone = wait(lambda: SIM.cam_active == 0, 30)
    check("C9. окно камеры закрыли — программа отпускает принтер (соединение со стримером закрыто)", bool(gone),
          SIM.cam_active)
    SIM.cam_max = 0
    res = {}

    def viewer(k):
        res[k] = read_frames(4)[0]
    th = [threading.Thread(target=viewer, args=(k,)) for k in ("a", "b")]
    for t in th:
        t.start()
    for t in th:
        t.join(40)
    check("C9а. два окна камеры сразу — оба получают кадры, а к принтеру ОДНО соединение",
          len(res.get("a") or []) == 4 and len(res.get("b") or []) == 4 and SIM.cam_max == 1,
          (len(res.get("a") or []), len(res.get("b") or []), SIM.cam_max))
    SIM.cam_url = "http://127.0.0.1:%d/?action=stream" % dead_port
    time.sleep(3)
    t0 = time.monotonic()
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/api/printer/ff1/camera" % port, timeout=15).close()
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    check("C10. камеры нет (или выключена на принтере) — честный 404 за секунды, а не вечная загрузка",
          code == 404 and time.monotonic() - t0 < 6, (code, round(time.monotonic() - t0, 1)))
    st, models = call("GET", "/api/printer-models")
    t1max = [m for m in (models if isinstance(models, list) else []) if m.get("name") == "FLSun T1 Max"]
    check("C11. в окне добавления принтера есть модель «FLSun T1 Max» со своей картинкой",
          len(t1max) == 1 and str(t1max[0].get("cover") or t1max[0].get("cover_url") or "").startswith("/covers/"), t1max)
    SIM.cam_url = ""
    c = wait(lambda: cur().get("has_camera") is False and cur(), 20)
    check("C12. принтер о камере не сообщает (5M без камеры) — признака «есть камера» нет, кнопки не будет",
          bool(c), cur().get("has_camera"))

    # ── 16.10.2026 (R-147, R-141): отказ принтера (неверный серийный номер или код) — не «Свободен» ──
    n_hist = len(CARD_HIST)
    SIM.deny = True
    c = wait(lambda: cur().get("status") == "OFFLINE" and cur(), 20)
    time.sleep(6)                                   # ещё три опроса с отказом
    # «ни разу не Свободен» считаем с первого «не в сети»: до первого опроса с отказом сервер
    # ещё рассылает прежнюю карточку «Свободен» — это не ответ на отказ (плавало 1 раз из 4)
    seen = CARD_HIST[n_hist:]
    seen = seen[seen.index("OFFLINE"):] if "OFFLINE" in seen else seen
    _lt = open(logp, encoding="utf-8", errors="replace").read() if os.path.isfile(logp) else ""
    check("C13. КРИТИЧНО: принтер отвечает отказом (code 1, без detail) — карточка «не в сети» с причиной, ни разу не «Свободен»",
          bool(c) and c.get("err_msg") == "нет доступа к принтеру (проверьте серийный номер и код)"
          and "IDLE" not in seen and cur().get("status") == "OFFLINE", (cur(), seen[-6:]))
    check("C14. об отказе — одна строка в журнале, а не на каждый опрос",
          _lt.count("принтер отказал в ответе /detail") == 1, _lt.count("принтер отказал в ответе /detail"))
    SIM.deny = False
    c = wait(lambda: cur().get("status") == "IDLE" and cur(), 20)
    check("C15. доступ вернулся — снова «Свободен» по доказанному покою", bool(c) and not c.get("err_msg"), cur())
    if fails and os.environ.get("FF_TEST_DUMP_CAM"):
        for ln in open(os.path.join(root, "logs", "farm.log"), encoding="utf-8", errors="replace"):
            if "CAM" in ln and ln.startswith(time.strftime("%Y-%m-%d")):
                print("   LOG:", ln.rstrip()[:200])
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
