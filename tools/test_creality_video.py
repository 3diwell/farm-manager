# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Камера Creality по WebRTC — как официальный Creality Print 7.3 (R-062, R-146, 16.10.2026).

ЗАЧЕМ. У клиента не подключается камера K2 Pro. Программа знала один путь — POST на
http://<адрес>:8000/call/webrtc_local без токена. Прошивки с признаком videoInfo.videoEncryption ждут
предложение по HTTPS на порту видео (443) и с токеном, который принтер выдаёт по службе 9999. Теперь
программа идёт тем же порядком, что Creality Print: 9999 (признаки, токен) -> https:443 -> http:8000 ->
http:80; SDP чистится так же (один кодек H.264, адреса mDNS -> реальный IP); на :8000 без ответа — один
повтор прежним телом, чтобы работающий у владельца K2 Plus не сломался. Диагностика говорит «камера
в порядке» только по настоящему ответу принтера. Источники контракта — app/creality_video.py.

Принтера у разработки нет, поэтому:
  A. чистые функции app/creality_video.py — на предложении в том виде, в каком его строит Chrome;
  B. НАСТОЯЩИЙ процесс программы (изолированный экземпляр) против имитатора принтера: служба 9999
     (признаки и getToken), HTTPS с самоподписанным сертификатом (/info и сигнализация), HTTP :8000 и :80.
     Порядок путей, тело (base64 JSON с токеном), Content-Type, повтор сырым предложением на :8000,
     ответ 409 при webrtcSupport 0, отчёт диагностики и отсутствие токена в журнале;
  C. окно камеры на стенде интерфейса: браузер открывает WebRTC без STUN-сервера в интернете
     и с направлением sendrecv (web/app.js).

Сети наружу нет: всё на 127.0.0.1. Рабочие данные, порт и принтеры владельца не трогаются.
Запуск: python tools/test_creality_video.py   (0 = пройдено)
"""
import base64
import datetime
import http.server
import io
import json
import os
import re
import secrets
import shutil
import socket
import socketserver
import ssl
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
sys.path.insert(0, os.path.join(REPO, "tools"))
from app import creality_video as CV  # noqa: E402
from app import e2e_isolation as ISO  # noqa: E402

fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""),
          flush=True)
    if not ok:
        fails.append(name)


#  Предложение браузера в том виде, в каком его строит Chrome/Edge (WebView2): несколько кодеков с
#  повторной передачей, кандидаты спрятаны за именами mDNS.
OFFER = "\r\n".join([
    "v=0", "o=- 4611731400430051336 2 IN IP4 127.0.0.1", "s=-", "t=0 0", "a=group:BUNDLE 0",
    "a=extmap-allow-mixed", "a=msid-semantic: WMS",
    "m=video 9 UDP/TLS/RTP/SAVPF 96 97 102 103 104 105 45 46",
    "c=IN IP4 0.0.0.0", "a=rtcp:9 IN IP4 0.0.0.0",
    "a=candidate:1 1 udp 2113937151 3f1b2a9c-77e1-4c21-9a8e-0d5f1c2b3a4d.local 54321 typ host generation 0",
    "a=candidate:2 1 tcp 2113939711 3f1b2a9c-77e1-4c21-9a8e-0d5f1c2b3a4d.local 9 typ host tcptype active generation 0",
    "a=candidate:3 1 udp 1677729535 203.0.113.7 54322 typ srflx raddr 0.0.0.0 rport 0 generation 0",
    "a=ice-ufrag:Wq1e", "a=ice-pwd:8vYc1r2Uz3x4w5v6t7s8r9q0", "a=ice-options:trickle",
    "a=fingerprint:sha-256 6B:8B:F0:65:5F:78:E2:51:3B:AC:6F:F3:3F:46:1B:35:DC:B8:5F:64:1A:24:C2:43:F0:A1:58:D0:A1:2C:19:08",
    "a=setup:actpass", "a=mid:0", "a=extmap:1 urn:ietf:params:rtp-hdrext:toffset", "a=sendrecv",
    "a=msid:- 1a2b", "a=rtcp-mux", "a=rtcp-rsize",
    "a=rtpmap:96 VP8/90000", "a=rtcp-fb:96 goog-remb", "a=rtcp-fb:96 nack",
    "a=rtpmap:97 rtx/90000", "a=fmtp:97 apt=96",
    "a=rtpmap:102 H264/90000", "a=rtcp-fb:102 goog-remb", "a=rtcp-fb:102 nack", "a=rtcp-fb:102 nack pli",
    "a=fmtp:102 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42001f",
    "a=rtpmap:103 rtx/90000", "a=fmtp:103 apt=102",
    "a=rtpmap:104 H264/90000", "a=fmtp:104 level-asymmetry-allowed=1;packetization-mode=0;profile-level-id=42001f",
    "a=rtpmap:105 rtx/90000", "a=fmtp:105 apt=104",
    "a=rtpmap:45 AV1/90000", "a=rtpmap:46 rtx/90000", "a=fmtp:46 apt=45",
    "a=ssrc-group:FID 1111 2222", "a=ssrc:1111 cname:abc", "a=ssrc:2222 cname:abc", ""])
ANSWER = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 102\r\na=rtpmap:102 H264/90000\r\na=sendrecv\r\n"

# ════════════════════════════════════════════════════════════════════════════
print("\n--- A. чистые функции (app/creality_video.py) ---")
check("A1. признак шифрования видео распознаётся только точным словом из features",
      CV.has_video_encryption(["videoInfo.videoEncryption"]) and CV.has_video_encryption(["x", "videoInfo.videoEncryption"])
      and not CV.has_video_encryption([]) and not CV.has_video_encryption(None) and not CV.has_video_encryption(["videoInfo"]))
u_enc = [x["url"] for x in CV.signaling_urls("10.0.0.5", True)]
u_enc_port = [x["url"] for x in CV.signaling_urls("10.0.0.5", True, video_port="8443")]
u_plain = [x["url"] for x in CV.signaling_urls("10.0.0.5", False)]
u_plain_tok = [x["url"] for x in CV.signaling_urls("10.0.0.5", False, have_token=True)]
check("A2. порядок путей: с шифрованием — https:<порт видео|443>, http:8000, http:80; без — только :8000 (и :80 с токеном)",
      u_enc == ["https://10.0.0.5:443/call/webrtc_local", "http://10.0.0.5:8000/call/webrtc_local", "http://10.0.0.5:80/call/webrtc_local"]
      and u_enc_port[0] == "https://10.0.0.5:8443/call/webrtc_local"
      and u_plain == ["http://10.0.0.5:8000/call/webrtc_local"]
      and u_plain_tok == ["http://10.0.0.5:8000/call/webrtc_local", "http://10.0.0.5:80/call/webrtc_local"],
      (u_enc, u_enc_port, u_plain, u_plain_tok))
F = CV.filter_h264(OFFER)
codec_pts = sorted(set(re.findall(r"^a=(?:rtpmap|fmtp|rtcp-fb):(\d+)", F, re.M)))
check("A3. фильтр как у Creality Print: остался один кодек — первый H.264 (102) со своими строками",
      codec_pts == ["102"] and "a=rtpmap:102 H264/90000" in F and "a=fmtp:102 level-asymmetry-allowed=1;packetization-mode=1" in F
      and "a=rtcp-fb:102 nack pli" in F and "VP8" not in F and "AV1" not in F and "rtx" not in F, codec_pts)
check("A4. и ничего лишнего не тронуто: строка m=, ICE, DTLS, кандидаты, ssrc, переводы строк CRLF",
      "m=video 9 UDP/TLS/RTP/SAVPF 96 97 102 103 104 105 45 46\r\n" in F and "a=ice-ufrag:Wq1e\r\n" in F
      and "a=fingerprint:sha-256" in F and "a=setup:actpass" in F and F.count("a=candidate:") == 3
      and "a=ssrc:1111 cname:abc" in F and F.endswith("\r\n") and "\n" not in F.replace("\r\n", ""))
NO264 = OFFER.replace("H264", "VP9")
check("A5. в предложении нет H.264 — SDP уходит без изменений (решать за принтер нельзя)", CV.filter_h264(NO264) == NO264)
M = CV.replace_mdns(F, "192.168.1.20")
check("A6. адреса mDNS (*.local) в кандидатах заменены реальным IP, остальные кандидаты не тронуты",
      ".local" not in M and "a=candidate:1 1 udp 2113937151 192.168.1.20 54321 typ host generation 0" in M
      and "a=candidate:2 1 tcp 2113939711 192.168.1.20 9 typ host tcptype active" in M
      and "203.0.113.7 54322 typ srflx" in M and CV.replace_mdns(F, "") == F)
b_tok = CV.encode_offer(M, "TOK123")
b_no = CV.encode_offer(M)
j_tok = json.loads(base64.b64decode(b_tok).decode())
check("A7. тело — base64(JSON{type:offer, sdp, token}) компактным JSON; без токена поля token нет",
      j_tok == {"type": "offer", "sdp": M, "token": "TOK123"} and b'":"' in base64.b64decode(b_tok)
      and "token" not in json.loads(base64.b64decode(b_no).decode()))
check("A8. прежнее тело (для одного повтора на :8000) — ровно то, что программа слала до 16.10.2026",
      CV.legacy_offer(OFFER) == base64.b64encode(json.dumps({"type": "offer", "sdp": OFFER}).encode()))
ans_b64 = base64.b64encode(json.dumps({"type": "answer", "sdp": ANSWER}).encode())
check("A9. ответ принтера: base64(JSON), JSON и сырой SDP понимаются; «{}», пусто и мусор — «ответа нет»",
      CV.decode_answer(ans_b64) == {"type": "answer", "sdp": ANSWER}
      and CV.decode_answer(json.dumps({"type": "answer", "sdp": ANSWER})) == {"type": "answer", "sdp": ANSWER}
      and CV.decode_answer(ANSWER)["sdp"] == ANSWER.strip()
      and CV.decode_answer(b"{}") is None and CV.decode_answer("") is None and CV.decode_answer(b"   ") is None
      and CV.decode_answer(base64.b64encode(b"{}")) is None and CV.decode_answer(b"<html>error</html>") is None
      and CV.decode_answer(base64.b64encode(json.dumps({"type": "answer", "sdp": ""}).encode())) is None)
info = CV.parse_info({"model": "F012", "mac": "AA:BB:CC:DD:EE:FF", "wssPort": "443", "videoPort": 443, "ip": "10.0.0.5"})
check("A10. /info: модель, порт видео и wss; MAC и адрес не берутся",
      info == {"model": "F012", "video_port": 443, "wss_port": 443, "secure": True}
      and CV.parse_info({"videoPort": "x"}) == {"model": "", "video_port": None, "wss_port": None, "secure": False}
      and CV.parse_info([]) is None, info)
check("A11. версия прошивки из modelVersion службы 9999 (K2 и KE)",
      CV.firmware_from("printer hw ver:;printer sw ver:;DWIN hw ver:CR0CN240319C10;DWIN sw ver:1.1.6.7;") == "1.1.6.7"
      and CV.firmware_from("printer hw ver:;printer sw ver:;DWIN hw ver:F005;DWIN sw ver:V1.1.0.17;") == "V1.1.0.17"
      and CV.firmware_from("printer sw ver:2.3.4;") == "2.3.4" and CV.firmware_from("") == "" and CV.firmware_from(None) == "")
check("A12. адрес для кандидата: только частная сеть IPv4 (не петля, не 0.0.0.0)",
      CV.is_private_ipv4("192.168.1.20") and CV.is_private_ipv4("10.1.2.3") and not CV.is_private_ipv4("127.0.0.1")
      and not CV.is_private_ipv4("8.8.8.8") and not CV.is_private_ipv4("0.0.0.0") and not CV.is_private_ipv4("fe80::1")
      and not CV.is_private_ipv4("x"))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- B. настоящий процесс программы и имитатор камеры Creality ---")
from websockets.sync.server import serve  # noqa: E402
from cryptography import x509  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

TOKEN = "VTOK-" + secrets.token_hex(12)
SNAP = {"state": 0, "deviceState": 0, "model": "F012", "hostname": "K2PRO-NAME-1016", "webrtcSupport": 1, "video": 1,
        "features": ["videoInfo.videoEncryption"], "nozzleTemp": "25.0", "bedTemp0": "24.0", "printProgress": 0,
        "modelVersion": "printer hw ver:;printer sw ver:;DWIN hw ver:CR0CN240319C10;DWIN sw ver:1.1.6.7;"}


class Svc(object):
    """Служба 9999: полный снимок при подключении, токен камеры по запросу getToken."""
    def __init__(self, snap):
        self.snap = dict(snap)
        self.got = []

    def handler(self, ws):
        try:
            ws.send(json.dumps(self.snap))
            while True:
                try:
                    msg = ws.recv(timeout=0.5)
                except TimeoutError:
                    continue
                self.got.append(msg)
                try:
                    obj = json.loads(msg)
                except Exception:
                    continue
                if (obj.get("params") or {}).get("getToken"):
                    ws.send(json.dumps({"videoToken": TOKEN}))
        except Exception:
            pass


SIG = []                                           # (кто, путь, Content-Type, тело)
MODE = {"https": "answer", "8000": "404", "80": "404"}


def make_handler(tag):
    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            pass

        def _reply(self, code, body, ctype="text/plain"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if tag == "https" and self.path == "/info":
                return self._reply(200, json.dumps({"model": "F012", "mac": "AA:BB:CC:DD:EE:01", "wssPort": 443,
                                                    "videoPort": 443}).encode(), "application/json")
            return self._reply(404, b"not found")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n)
            SIG.append((tag, self.path, self.headers.get("Content-Type"), body))
            mode = MODE.get(tag, "404")
            if mode == "legacy_only":                  # отвечает только на прежнее тело (сырое предложение без токена)
                try:
                    j = json.loads(base64.b64decode(body).decode())
                except Exception:
                    j = {}
                mode = "answer" if (j.get("sdp") == OFFER and "token" not in j) else "empty"
            if mode == "answer":
                return self._reply(200, base64.b64encode(json.dumps({"type": "answer", "sdp": ANSWER}).encode()))
            if mode == "raw":
                return self._reply(200, ANSWER.encode())
            if mode == "empty":
                return self._reply(200, b"{}")
            return self._reply(404, b"not found")
    return H


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


root = tempfile.mkdtemp(prefix="fm_e2e_crcam_")
#  самоподписанный сертификат «принтера» — как у настоящего (программа его не сверяет, как и Creality Print)
key = ec.generate_private_key(ec.SECP256R1())
nm = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "creality-k2-test")])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(nm).issuer_name(nm).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=2)).sign(key, hashes.SHA256()))
certf, keyf = os.path.join(root, "c.pem"), os.path.join(root, "k.pem")
open(certf, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
open(keyf, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))

p_https, p_8000, p_80, p_ws, p_ws0, p_dead, p_dead2 = (free_port() for _ in range(7))
srv_https = TServer(("127.0.0.1", p_https), make_handler("https"))
_sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
_sctx.load_cert_chain(certf, keyf)
srv_https.socket = _sctx.wrap_socket(srv_https.socket, server_side=True)
for srv in (srv_https, TServer(("127.0.0.1", p_8000), make_handler("8000")), TServer(("127.0.0.1", p_80), make_handler("80"))):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
SVC = Svc(SNAP)
SVC0 = Svc(dict(SNAP, webrtcSupport=0, features=[], model="F005"))      # KE: WebRTC нет, камера MJPEG
for svc, prt in ((SVC, p_ws), (SVC0, p_ws0)):
    _ws = serve(svc.handler, "127.0.0.1", prt, compression=None)
    threading.Thread(target=_ws.serve_forever, daemon=True).start()

PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD) + os.sep)
port = free_port()
token = "CRCAM_E2E_" + secrets.token_hex(8)
json.dump({"token": token, "sentinel": "CRCAM_E2E_1610"}, open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8"))
cfgp = os.path.join(root, "config.json")
json.dump({"server_port": port}, open(cfgp, "w", encoding="utf-8"))
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_CRCAM_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "0",
            ISO.ENV_NO_MODULES: "1", "PYTHONDONTWRITEBYTECODE": "1",
            #  порты «принтера» 443, 8000, 80, 9999 и 8080 — наши имитаторы (только тестовый экземпляр из исходников)
            "FM_CREALITY_TEST_CAM_PORTS": "443=%d,8000=%d,80=%d,9999=%d,8080=%d" % (p_https, p_8000, p_80, p_ws, p_dead2)})
SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
SRC_VER = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)


def call(method, path, body=None, timeout=90):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}


def offer_body(b):
    try:
        return json.loads(base64.b64decode(b).decode("utf-8"))
    except Exception:
        return {}


def cam_check():
    st, rep = call("GET", "/api/printer/k2/diagnose?lang=ru")
    got = [c for c in (rep.get("checks") or []) if c.get("key") == "camera"]
    return got[0] if got else {}


proc = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                        cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=(0x00000008 | 0x00000200))
try:
    up = wait(lambda: listening(port) and call("GET", "/version")[1].get("version") == SRC_VER, 150)
    check("B1. изолированный экземпляр поднялся (своя папка, порт, замок)", bool(up))
    st, js = call("POST", "/api/printers/save", [
        {"id": "k2", "name": "K2 Pro test", "type": "klipper", "ip": "127.0.0.1", "port": p_dead, "gen": "auto", "serial": "",
         "model": "Creality K2 Pro"},
        {"id": "cr0", "name": "KE test", "type": "creality", "ip": "127.0.0.1", "port": p_ws0, "gen": "auto", "serial": "",
         "model": "Creality Ender-3 V3 KE"}])
    check("B2. принтеры сохранены (K2 Pro на Klipper, KE на заводской прошивке)", st == 200, (st, js))

    st, rep = call("GET", "/api/printer/k2/diagnose?lang=ru")
    c0 = [c for c in (rep.get("checks") or []) if c.get("key") == "camera"]
    c0 = c0[0] if c0 else {}
    check("B3. до первой попытки: порты открыты, но отчёт НЕ говорит «камера в порядке» — просит открыть камеру; "
          "версию прошивки называет сам", c0.get("status") == "warn" and "прошивка 1.1.6.7" in str(c0.get("value")), c0)

    # S1: прошивка с защитой видео, HTTPS отвечает
    SIG[:] = []
    n_svc = len(SVC.got)
    MODE.update({"https": "answer", "8000": "404", "80": "404"})
    st, js = call("POST", "/api/printer/k2/webrtc", {"type": "offer", "sdp": OFFER})
    first = SIG[0] if SIG else ("", "", "", b"")
    sent = offer_body(first[3])
    check("B4. ГЛАВНОЕ: прошивка с videoInfo.videoEncryption — программа берёт токен по 9999 и открывает камеру по HTTPS, "
          "ответ принтера доходит до окна",
          st == 200 and js.get("sdp") == ANSWER and any('"getToken":1' in m for m in SVC.got[n_svc:])
          and [x[0] for x in SIG] == ["https"], (st, js, [x[0] for x in SIG], SVC.got[n_svc:]))
    check("B5. запрос как у Creality Print: POST /call/webrtc_local, Content-Type plain/text, base64(JSON) с токеном",
          first[1] == "/call/webrtc_local" and first[2] == "plain/text" and sent.get("type") == "offer"
          and sent.get("token") == TOKEN, (first[1], first[2], {k: (v if k != "sdp" else len(v)) for k, v in sent.items()}))
    _sdp = sent.get("sdp") or ""
    check("B6. предложение очищено: один кодек H.264, адреса mDNS заменены реальным IP компьютера",
          sorted(set(re.findall(r"^a=rtpmap:(\d+)", _sdp, re.M))) == ["102"] and ".local" not in _sdp
          and "a=candidate:1 1 udp 2113937151 127.0.0.1 54321" in _sdp, _sdp[:300])

    # S2: HTTPS не отвечает, :8000 отвечает только прежнему телу — работающий путь K2 Plus не сломан
    SIG[:] = []
    MODE.update({"https": "404", "8000": "legacy_only", "80": "404"})
    st, js = call("POST", "/api/printer/k2/webrtc", {"type": "offer", "sdp": OFFER})
    legacy = offer_body(SIG[2][3]) if len(SIG) > 2 else {}
    check("B7. HTTPS отказал -> :8000 очищенным предложением -> один повтор прежним телом (сырое предложение, "
          "без токена) — камера открылась, порт 80 не понадобился",
          st == 200 and js.get("sdp") == ANSWER and [x[0] for x in SIG] == ["https", "8000", "8000"]
          and offer_body(SIG[1][3]).get("token") == TOKEN and legacy == {"type": "offer", "sdp": OFFER}
          and SIG[2][3] == base64.b64encode(json.dumps({"type": "offer", "sdp": OFFER}).encode()),
          (st, [x[0] for x in SIG], legacy.keys() if legacy else None))

    # S3: путь geckotdf — :80 с токеном, ответ сырым SDP
    SIG[:] = []
    MODE.update({"https": "empty", "8000": "404", "80": "raw"})
    st, js = call("POST", "/api/printer/k2/webrtc", {"type": "offer", "sdp": OFFER})
    check("B8. HTTPS ответил пусто («{}»), :8000 — 404: дальше http:80 с токеном; сырой SDP в ответе понят",
          st == 200 and (js.get("sdp") or "").strip() == ANSWER.strip() and [x[0] for x in SIG] == ["https", "8000", "8000", "80"]
          and offer_body(SIG[3][3]).get("token") == TOKEN, (st, [x[0] for x in SIG]))

    # S4: никто не ответил
    SIG[:] = []
    MODE.update({"https": "404", "8000": "empty", "80": "404"})
    st, js = call("POST", "/api/printer/k2/webrtc", {"type": "offer", "sdp": OFFER})
    c = cam_check()
    check("B9. ни один путь не ответил — окну 502 (оно уйдёт на MJPEG), а диагностика честно пишет «не ответил» и перечисляет пути",
          st == 502 and c.get("status") == "fail" and "не ответил" in str(c.get("value")) and "https:443" in str(c.get("advice"))
          and "http:8000 raw" in str(c.get("advice")), (st, js, c))
    MODE.update({"https": "answer", "8000": "404", "80": "404"})
    st, js = call("POST", "/api/printer/k2/webrtc", {"type": "offer", "sdp": OFFER})
    c = cam_check()
    check("B10. после настоящего ответа принтера отчёт зелёный: путь (HTTPS, порт 443, с токеном) и версия прошивки",
          st == 200 and c.get("status") == "ok" and "443" in str(c.get("value")) and "с токеном" in str(c.get("value"))
          and "прошивка 1.1.6.7" in str(c.get("value")), c)

    # S5: принтер Creality сам сообщил «WebRTC нет» — сразу 409, без обращений к принтеру
    ready = wait(lambda: call("POST", "/api/printer/cr0/webrtc", {"type": "offer", "sdp": OFFER})[0] == 409, 40)
    SIG[:] = []
    t0 = time.monotonic()
    st, js = call("POST", "/api/printer/cr0/webrtc", {"type": "offer", "sdp": OFFER})
    dt = time.monotonic() - t0
    check("B11. webrtcSupport 0 (KE): ответ 409 сразу — окно камеры идёт на MJPEG 8080, как Creality Print; к принтеру ни одного запроса",
          bool(ready) and st == 409 and js.get("error") == "webrtc_unsupported" and dt < 2.0 and not SIG, (st, js, round(dt, 2), SIG[:1]))

    logf = os.path.join(root, "logs", "farm.log")
    logtxt = io.open(logf, encoding="utf-8", errors="replace").read() if os.path.isfile(logf) else ""
    check("B12. в журнале — какой путь сработал; токена камеры в журнале нет ни разу",
          "камера ответила по пути https:443+token" in logtxt and TOKEN not in logtxt and "K2PRO-NAME-1016" not in logtxt,
          (TOKEN in logtxt, logtxt[-600:]))
finally:
    try:
        open(os.path.join(root, "stop.request"), "w", encoding="utf-8").write(token)
        wait(lambda: not listening(port), 60)
    except Exception:
        pass
    if proc.poll() is None and listening(port):
        proc.terminate()
    shutil.rmtree(root, ignore_errors=True)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- C. окно камеры в браузере (стенд интерфейса) ---")
import _fm_ui_stage as stage  # noqa: E402

PR = [{"id": "k1", "name": "K2 Plus", "type": "klipper", "ip": "192.0.2.10", "port": 7125, "gen": "auto", "serial": "",
       "model": "Creality K2 Plus", "order_idx": 0}]
LIVE = {"k1": {"status": "IDLE", "nozzle_temp": 25, "bed_temp": 24, "percent": 0, "remaining_time": 0, "file_name": "",
               "seen_ago": 0}}
JS = r"""
return new Promise(function(res){
  var rec = { cfg: null, tr: null, posts: [] };
  var Orig = window.RTCPeerConnection;
  window.RTCPeerConnection = function(cfg){ rec.cfg = cfg; var pc = new Orig(cfg); var at = pc.addTransceiver.bind(pc);
    pc.addTransceiver = function(k, o){ rec.tr = [k, o]; return at(k, o); }; return pc; };
  var of = window.fetch;
  window.fetch = function(u, o){ if (String(u).indexOf('/webrtc') >= 0) { try { rec.posts.push(JSON.parse(o.body)); } catch(e) { rec.posts.push('?'); } }
    return of.apply(this, arguments); };
  var tries = 0;
  (function go(){
    var b = Array.prototype.slice.call(document.querySelectorAll('button')).filter(function(x){
      var t = (x.getAttribute('title') || ''); return t === 'Камера' || t === 'Camera'; })[0];
    if (!b) { if (++tries > 40) { dump({ found: false }); res(true); return; } setTimeout(go, 250); return; }
    b.click();
    setTimeout(function(){
      dump({ found: true, cfg: rec.cfg, tr: rec.tr, posts: rec.posts.length,
             sdpOk: !!(rec.posts[0] && rec.posts[0].sdp && rec.posts[0].sdp.indexOf('v=0') === 0) });
      res(true);
    }, 3500);
  })();
});
"""
if not stage.engine_ready():
    check("C1. браузерный движок доступен (без него проверить нечем)", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR})
    stage.set_live(LIVE)
    R = stage.run(JS, window_size=(1600, 1000), settle_ms=4000, path="/")
    stage.set_api(None)
    stage.set_live(None)
    stage.stop()
    if not R:
        check("C1. страница отработала", False, str(stage.last_diag())[:250])
    else:
        check("C1. окно камеры Klipper/Creality открыто кнопкой на карточке принтера", R.get("found") is True, R)
        check("C2. браузер открывает WebRTC без STUN-сервера в интернете (iceServers пуст), как Creality Print в сети",
              R.get("cfg") == {"iceServers": []}, R.get("cfg"))
        check("C3. направление видео — sendrecv (как у Creality Print и родной страницы принтера)",
              R.get("tr") == ["video", {"direction": "sendrecv"}], R.get("tr"))
        check("C4. предложение ушло на сервер программы (сигнализация — через ядро)", R.get("posts") == 1 and R.get("sdpOk") is True, R)
        _d = R.get("__diag") or {}
        _warn = [w for w in (_d.get("consoleWarnings") or []) if "[WebRTC] camera failed" not in str(w)]
        check("C5. консоль браузера чистая (ответа камеры на стенде нет — ожидаемый переход на MJPEG не в счёт)",
              not (_d.get("consoleErrors") or _d.get("pageErrors") or _d.get("unhandled"))
              and not [w for w in _warn if "Vue warn" in str(w)], json.dumps(_d, ensure_ascii=False)[:300])

print("\n" + "=" * 76)
if fails:
    print("FAIL: провалено %d из %d" % (len(fails), len(names)))
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % len(names))
sys.exit(0)
