# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Принтеры Creality на заводской прошивке — родная служба Creality, порт 9999 (12.10.2026).

ЗАЧЕМ. Клиент с Ender-3 V3 KE и Ender-5 Max: на заводской прошивке Moonraker нет, программа принтеры не
видела. Новый тип подключения «creality» говорит с той же службой, что Creality Print
(app/creality_native.py; источники контракта — там же). Принтера у разработки нет, поэтому:

  A. разбор сообщений службы — на кадрах в том виде, в каком их шлёт настоящий K1C (полный снимок,
     затем изменения, температуры строками, пустая строка при загрузке), таблица состояний, список
     файлов в трёх форматах прошивок, имя и тело загрузки, точные команды, обезличивание журнала;
  B. таблицы ядра: покой, активная печать, отмена, сбой, команды, разрешённые этому типу;
  C. НАСТОЯЩИЙ процесс программы (изолированный экземпляр) против имитатора принтера Creality по тому
     же контракту: карточка, ответ на сердцебиение, отправка файла (загрузка, сверка по списку, старт),
     подтверждение старта телеметрией, пауза, продолжение, стоп, температура, отказ от .3mf, потеря связи.
     16.10.2026 (R-146): имитатор как настоящий K1C — сам сердцебиение не шлёт; программа при тишине
     спрашивает принтер запросом только на чтение (reqPrintObjects), не чаще раза в 8 с. Отдельно —
     принтер, который молчит, пока его не спросят: карточка на связи, отправка не отказывает «Нет связи».

Сети наружу нет: имитатор и программа — на 127.0.0.1. Рабочие данные, порт и принтеры не трогаются.
Запуск: python tools/test_creality_native.py   (0 = пройдено)
"""
import io
import json
import os
import re
import secrets
import shutil
import socket
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
from app import creality_native as CN  # noqa: E402
from app import printer_state_policy as SP  # noqa: E402
from app import printer_job_lifecycle as PJL  # noqa: E402
from app import printer_command_policy as PCP  # noqa: E402
from app import e2e_isolation as ISO  # noqa: E402

SENTINEL = "CREALITY_NATIVE_SENTINEL_1210"
fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""), flush=True)
    if not ok:
        fails.append(name)


# ════════════════════════════════════════════════════════════════════════════
print("\n--- A. разбор сообщений службы Creality ---")
FULL = {"TotalLayer": 0, "autohome": "X:0 Y:0 Z:0", "bedTemp0": "22.030000", "boxTemp": 21, "connectionCount": 1,
        "curFeedratePct": 100, "deviceState": 0, "err": {"errcode": 0, "key": 0, "value": ""}, "hostname": "KE-1234",
        "layer": 0, "lightSw": 1, "materialStatus": 0, "model": "F005",
        "modelVersion": "printer hw ver:;printer sw ver:;DWIN hw ver:F005;DWIN sw ver:V1.1.0.17;",
        "nozzleTemp": "21.530000", "printFileName": "", "printJobTime": 0, "printLeftTime": 0, "printProgress": 0,
        "state": 0, "targetBedTemp0": 0, "targetBoxTemp": 0, "targetNozzleTemp": 0, "webrtcSupport": 0}
snap = CN.merge({}, dict(FULL))
st = CN.to_state(snap)
check("A1. полный снимок покоя -> IDLE, «idle», температуры из строк", st["status"] == "IDLE" and st["status_raw"] == "idle"
      and st["nozzle_temp"] == 21.5 and st["bed_temp"] == 22.0 and st["model_code"] == "F005", st)
CN.merge(snap, {"connectionCount": 2})
CN.merge(snap, {"nozzleTemp": "", "bedTemp0": "22.05"})
check("A2. изменения сводятся в снимок; пустая строка температуры (загрузка) прежнее значение не стирает",
      snap["nozzleTemp"] == "21.530000" and snap["bedTemp0"] == "22.05" and snap["connectionCount"] == 2)
CN.merge(snap, {"state": 9, "printFileName": "/usr/data/printer_data/gcodes/Body14_PLA.gcode", "targetNozzleTemp": 220})
st = CN.to_state(snap)
check("A3. начало печати (9: самотест, нагрев) -> RUNNING, имя файла без пути и расширения",
      st["status"] == "RUNNING" and st["status_raw"] == "printing" and st["file_name"] == "Body14_PLA" and st["nozzle_target"] == 220.0, st)
CN.merge(snap, {"state": 1, "printProgress": 37, "printLeftTime": 1500, "printJobTime": 900})
st = CN.to_state(snap)
check("A4. печать: процент, осталось в минутах, всего в секундах", st["percent"] == 37 and st["remaining_time"] == 25
      and st["total_time"] == 2400, st)
words = {n: CN.state_word({"state": n, "deviceState": 0}) for n in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 101, 102, 103)}
check("A5. все значения state из Creality Print сведены к словам программы",
      words == {0: "idle", 1: "printing", 2: "complete", 3: "error", 4: "cancelled", 5: "paused", 6: "paused", 7: "printing",
                8: "printing", 9: "printing", 101: "printing", 102: "paused", 103: "printing"}, words)
check("A6. незнакомое число и отсутствие поля — НЕ покой (fail-closed); покой при занятом устройстве — «busy»; карточка — «Занят», не «Свободен»",
      CN.state_word({"state": 42}) == "state_42" and CN.state_word({}) == "" and CN.state_word({"state": 0, "deviceState": 1}) == "busy"
      and SP.normalize_raw("creality", "state_42") == SP.Lifecycle.UNKNOWN and SP.normalize_raw("creality", "busy") == SP.Lifecycle.UNKNOWN
      and CN.to_state({"state": 42})["status"] == "BUSY" and CN.to_state({"state": 0, "deviceState": 1})["status"] == "BUSY"
      and "busy" not in CN.SENDABLE and "state_42" not in CN.SENDABLE)
check("A7. завершено — 100 %, сбой и отмена — FAILED (отмену от сбоя отделяет ядро)",
      CN.to_state({"state": 2, "printProgress": 99})["percent"] == 100
      and CN.to_state({"state": 3})["status"] == "FAILED" and CN.to_state({"state": 4})["status"] == "FAILED")
stale = CN.to_state({"state": 0, "deviceState": 0, "err": {"errcode": 500, "key": 0}})
live = CN.to_state({"state": 1, "err": {"errcode": 2839, "key": "nozzle"}})
check("A8. старый код ошибки в покое (прошивка его не сбрасывает) не показывается; при печати — показывается",
      CN.messages(stale) == [] and CN.messages(live) and CN.messages(live)[0]["code"] == "2839")
check("A9. датчик филамента: «закончился» -> сообщение принтера",
      any(m["module"] == "filament" for m in CN.messages(CN.to_state({"state": 5, "materialStatus": 1}))))
check("A10. текст сбоя — с кодом экрана; без кода — пусто (ядро даст общий)",
      "2839" in CN.fault_text(CN.to_state({"state": 3, "err": {"errcode": 2839, "key": 0}}))
      and CN.fault_text(CN.to_state({"state": 3})) == "")
check("A11. сердцебиение распознаётся; «ok» и мусор — не JSON-кадр",
      CN.is_heartbeat(CN.parse_frame('{"ModeCode":"heart_beat","msg":"2026-10-12 10:00:00"}'))
      and CN.parse_frame("ok") is None and CN.parse_frame("[1,2]") is None and CN.parse_frame(b'{"state":0}') == {"state": 0})
fl2 = CN.parse_file_list({"retGcodeFileInfo2": [{"name": "a.gcode", "path": "/usr/data/printer_data/gcodes/a.gcode",
                                                  "file_size": 1234, "create_time": 1760000000}]})
fl1 = CN.parse_file_list({"retGcodeFileInfo": {"totalNum": 1, "fileInfo": "/mnt/UDISK/printer_data/gcodes:b.gcode:99:0.2:1760000001:x;"}})
fl3 = CN.parse_file_list({"retGcodeFileInfo3": {"fileInfo": "c.gcode:77:1760000002;"}})
check("A12. список файлов — все три формата прошивок; каталог берётся из пути принтера",
      fl2[0]["path"].endswith("/a.gcode") and fl2[0]["size"] == 1234
      and fl1[0] == {"name": "b.gcode", "path": "/mnt/UDISK/printer_data/gcodes/b.gcode", "size": 99, "ctime": 1760000001}
      and fl3[0]["name"] == "c.gcode" and fl3[0]["size"] == 77
      and CN.gcode_dir_from("/mnt/UDISK/printer_data/gcodes/x.gcode") == "/mnt/UDISK/printer_data/gcodes"
      and CN.parse_file_list({"state": 1}) is None, (fl1, fl2, fl3))
_long = CN.safe_name("Д" * 300 + ".gcode")
check("A13. имя файла: без каталога и знаков, которые вычищает Creality Print; только .gcode; не длиннее 200 байт с расширением",
      CN.safe_name("C:\\x\\Деталь #1 & 2.gcode") == "Деталь 1  2.gcode" and CN.safe_name("plate.3mf") == ""
      and CN.safe_name("a.gcode.3mf") == "" and CN.safe_name(".gcode") == ""
      and _long.endswith(".gcode") and len(_long.encode("utf-8")) <= 200, _long[-12:])
body = CN.upload_body("Деталь.gcode", b"G28\n", "BND")
check("A14. загрузка: POST /upload/<имя в URL-кодировке>, одно поле file; успех — 200 и «OK» в ответе",
      CN.upload_url("10.0.0.5", "Деталь 1.gcode") == "http://10.0.0.5:80/upload/%D0%94%D0%B5%D1%82%D0%B0%D0%BB%D1%8C%201.gcode"
      and b'name="file"; filename="\xd0\x94\xd0\xb5\xd1\x82\xd0\xb0\xd0\xbb\xd1\x8c.gcode"' in body and b"\r\n\r\nG28\n\r\n--BND--\r\n" in body
      and CN.upload_ok(200, b'{"code":200,"message":"OK"}') and not CN.upload_ok(200, b"fail") and not CN.upload_ok(500, b"OK")
      and not CN.upload_ok(200, b'{"token":"x"}') and not CN.upload_ok(200, b"look"))
cmds = [CN.dumps(x) for x in (CN.cmd_pause(), CN.cmd_resume(), CN.cmd_stop(), CN.cmd_print_file("/usr/data/printer_data/gcodes/a.gcode"),
                              CN.cmd_nozzle_temp(210), CN.cmd_bed_temp(60), CN.cmd_file_list())]
check("A15. команды — ровно как у Creality Print (компактный JSON)",
      cmds == ['{"method":"set","params":{"pause":1}}', '{"method":"set","params":{"pause":0}}',
               '{"method":"set","params":{"stop":1}}',
               '{"method":"set","params":{"opGcodeFile":"printprt:/usr/data/printer_data/gcodes/a.gcode","enableSelfTest":0}}',
               '{"method":"set","params":{"nozzleTempControl":210}}', '{"method":"set","params":{"bedTempControl":{"num":0,"val":60}}}',
               '{"method":"get","params":{"reqGcodeFile":1}}'], cmds)
try:
    CN.cmd_print_file("a.gcode\nM112")
    bad_path = False
except ValueError:
    bad_path = True
check("A16. путь файла — только абсолютный и одной строкой", bad_path)
lt = CN.log_snapshot(dict(FULL, ip="10.1.2.3", devSn="SN123456", mac="AABBCCDDEEFF", printFileName="/usr/data/printer_data/gcodes/Заказ Иванова.gcode"),
                     secrets=("10.1.2.3",))
check("A17. журнал: только нужные поля и имена остальных — без имени принтера, адреса, номеров и имени файла заказчика",
      "KE-1234" not in lt and "10.1.2.3" not in lt and "SN123456" not in lt and "AABBCC" not in lt and "Иванова" not in lt
      and '"state": 0' in lt and '"printFileDir": "/usr/data/printer_data/gcodes"' in lt and '"hostname"' in lt, lt[:400])
#  16.10.2026 (R-146, R-062): запасные поля хода печати, ответ на запрос объектов, признаки прошивки и токен камеры.
_fb = CN.to_state({"state": 1, "dProgress": 42, "printTimeLeft": 1200, "printJobTime": 60})
_pr = CN.to_state({"state": 1, "printProgress": 10, "dProgress": 42, "printLeftTime": 600, "printTimeLeft": 1200})
check("A18. ход печати: нет printProgress — берётся dProgress, нет printLeftTime — printTimeLeft; основные поля важнее запасных",
      _fb["percent"] == 42 and _fb["remaining_time"] == 20 and _fb["total_time"] == 1260
      and _pr["percent"] == 10 and _pr["remaining_time"] == 10, (_fb, _pr))
_sn = CN.merge({"state": 0}, {"current_object": "a", "excluded_objects": [], "objects": [{"name": "a"}], "layer": 3})
check("A19. запрос при тишине — только чтение, ровно как у Creality Print; ответ (список объектов стола) в снимок не попадает",
      CN.dumps(CN.cmd_ask_objects()) == '{"method":"get","params":{"reqPrintObjects":1}}'
      and _sn == {"state": 0, "layer": 3} and CN.ASK_AFTER_SILENCE_S >= 8.0, _sn)
_lt2 = CN.log_snapshot(dict(FULL, features=["videoInfo.videoEncryption"], videoToken="VTOKEN-SECRET-1"))
check("A20. журнал: признаки прошивки (features) видны, токен камеры — никогда",
      '"features": ["videoInfo.videoEncryption"]' in _lt2 and "VTOKEN-SECRET-1" not in _lt2
      and "VTOKEN-SECRET-1" not in CN.log_text({"videoToken": "VTOKEN-SECRET-1"}), _lt2[:300])

# ════════════════════════════════════════════════════════════════════════════
print("\n--- B. таблицы ядра ---")
SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
check("B1. покой «idle», печать и пауза — активны, завершено/отмена/сбой — стол ждёт очистки",
      '"creality": ("idle",),' in SRC and '"creality": ("printing", "paused", "busy"),' in SRC
      and '"creality": ("complete", "cancelled", "error"),' in SRC)
check("B2. отмена отделена от сбоя; сбой — неисправность с текстом",
      PJL.normalize_state("creality", "cancelled") == PJL.STATE_CANCELLED and PJL.normalize_state("creality", "error") == PJL.STATE_FAILED
      and PJL.normalize_state("creality", "idle") != PJL.STATE_FAILED)
ok_cmds = [a for a in ("pause", "resume", "stop", "nozzle", "bed", "chamber") if PCP.parse_command(a, "50" if a in ("nozzle", "bed", "chamber") else "", "creality")[0]]
check("B3. разрешены пауза, продолжение, стоп и температуры сопла и стола; камера-нагреватель — нет",
      ok_cmds == ["pause", "resume", "stop", "nozzle", "bed"], ok_cmds)
check("B4. для подбора файла Creality на заводской прошивке — то же семейство, что Klipper; .3mf не подходит",
      '_pt = "klipper" if p["type"] == "creality" else p["type"]' in SRC
      and 'if (fmt == "3mf" and ptype in ("klipper", "creality"))' in SRC)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- C. настоящий процесс программы и имитатор принтера Creality ---")
from websockets.sync.server import serve  # noqa: E402
from websockets.sync.client import connect as ws_connect  # noqa: E402
import http.server  # noqa: E402


ASK = '{"method":"get","params":{"reqPrintObjects":1}}'
SHARED_FILES = {}                   # что принял «порт 80» — общий для всех имитаторов (как общий приёмник)


class Sim(object):
    """Имитатор службы Creality по контракту app/creality_native.py (ИСТОЧНИКИ).

    16.10.2026 (R-146): как у настоящего K1C ([HA] tools/simulator): принтер САМ сердцебиение не шлёт —
    его шлёт клиент, а принтер отвечает "ok"; полный снимок при подключении, дальше только изменения.
    silent=True — принтер, который молчит, пока его не спросят: ни снимка при подключении, ни изменений;
    на запрос объектов (reqPrintObjects) отвечает полным снимком."""
    def __init__(self, base=None, silent=False):
        self.state = dict(base or FULL)
        self.silent = silent
        self.lock = threading.Lock()
        self.clients = set()
        self.got = []
        self.got_ts = []
        self.files = SHARED_FILES
        self.ignore = False         # «принтер» принимает команды set, но не выполняет их
        #  16.10.2026 (R-146): K2, K2 Pro, K2 Plus и Hi после стопа сразу пишут state 0, без 7/4
        #  (ha_creality_ws, профили имитатора: stop_style 'state0').
        self.stop_style = "k1"

    def send_all(self, delta):
        with self.lock:
            self.state.update(delta)
            cs = list(self.clients)
        if self.silent:
            return                  # молчит: изменения узнают только по запросу
        for c in cs:
            try:
                c.send(json.dumps(delta))
            except Exception:
                pass

    def heartbeat_once(self):
        """Сердцебиение от принтера (на всякий случай: если прошивка его пришлёт, ответ — "ok")."""
        with self.lock:
            cs = list(self.clients)
        for c in cs:
            try:
                c.send(json.dumps({"ModeCode": "heart_beat", "msg": time.strftime("%Y-%m-%d %H:%M:%S")}))
            except Exception:
                pass

    def later(self, delay, delta):
        threading.Timer(delay, lambda: self.send_all(delta)).start()

    def handler(self, ws):
        with self.lock:
            self.clients.add(ws)
            first = json.dumps(self.state)
        try:
            if not self.silent:
                ws.send(first)
            while True:
                try:
                    msg = ws.recv(timeout=0.3)
                except TimeoutError:
                    continue
                self.got.append(msg)
                self.got_ts.append((time.monotonic(), msg))
                obj = CN.parse_frame(msg)
                if not obj:
                    continue
                if CN.is_heartbeat(obj):
                    ws.send("ok")             # сердцебиение клиента — ответ "ok", как у K1C
                    continue
                prm = obj.get("params") or {}
                if self.ignore and obj.get("method") == "set":
                    continue
                if obj.get("method") == "get" and prm.get("reqPrintObjects"):
                    with self.lock:
                        full = dict(self.state)
                    out = {"current_object": "", "excluded_objects": [], "objects": [{"name": "part_1", "id": 0}]}
                    if self.silent:
                        out.update(full)      # молчащий принтер на запрос отвечает полным снимком
                    ws.send(json.dumps(out))
                elif obj.get("method") == "get" and prm.get("reqGcodeFile"):
                    ws.send(json.dumps({"retGcodeFileInfo2": [
                        {"name": n, "path": "/usr/data/printer_data/gcodes/" + n, "file_size": len(b), "create_time": 1760000000}
                        for n, b in self.files.items()]}))
                elif "opGcodeFile" in prm:
                    path = prm["opGcodeFile"].split("printprt:", 1)[-1]
                    if os.path.basename(path) in self.files:
                        self.send_all({"state": 9, "printFileName": path, "deviceState": 1})
                        self.later(1.0, {"state": 1, "printProgress": 5, "printLeftTime": 600, "printJobTime": 30})
                    return            # [ORCA]: K1 закрывает соединение после команды старта
                elif "pause" in prm:
                    self.send_all({"state": 5 if prm["pause"] == 1 else 1})
                elif "stop" in prm and self.stop_style == "state0":
                    self.send_all({"state": 0, "deviceState": 0})
                elif "stop" in prm:
                    self.send_all({"state": 7})
                    self.later(0.8, {"state": 4, "deviceState": 0})
                elif "nozzleTempControl" in prm:
                    self.send_all({"targetNozzleTemp": prm["nozzleTempControl"]})
        except Exception:
            pass
        finally:
            with self.lock:
                self.clients.discard(ws)


SIM = Sim()


class Upload(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n)
        name = urllib.parse.unquote(self.path.split("/upload/", 1)[-1])
        if name.startswith("rename_me"):
            name = name.replace(".gcode", "(1).gcode")      # прошивка сохранила под другим именем
        bnd = self.headers.get("Content-Type", "").split("boundary=", 1)[-1].encode()
        start = data.find(b"\r\n\r\n") + 4
        end = data.rfind(b"\r\n--" + bnd + b"--")
        SHARED_FILES[name] = data[start:end]
        out = b'{"code":200,"message":"OK"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


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


ws_port, http_port = free_port(), free_port()
srv = serve(SIM.handler, "127.0.0.1", ws_port, compression=None)
threading.Thread(target=srv.serve_forever, daemon=True).start()
hsrv = http.server.ThreadingHTTPServer(("127.0.0.1", http_port), Upload)
threading.Thread(target=hsrv.serve_forever, daemon=True).start()

PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
root = tempfile.mkdtemp(prefix="fm_e2e_creality_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD) + os.sep)
port = free_port()
token = "CREALITY_E2E_" + secrets.token_hex(8)
json.dump({"token": token, "sentinel": "CREALITY_E2E_1210"}, open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8"))
cfgp = os.path.join(root, "config.json")
json.dump({"server_port": port}, open(cfgp, "w", encoding="utf-8"))
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_CREALITY_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "0",
            ISO.ENV_NO_MODULES: "1", "FM_CREALITY_TEST_UPLOAD_PORT": str(http_port), "PYTHONDONTWRITEBYTECODE": "1"})
SRC_VER = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)


def call(method, path, body=None, raw=None, ctype=None):
    data = json.dumps(body).encode("utf-8") if body is not None else raw
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}


def upload_print(pid, fname, data):
    b = "----fmcr" + secrets.token_hex(6)
    body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n") % (b, fname)).encode("utf-8") + data + ("\r\n--%s--\r\n" % b).encode()
    return call("POST", "/api/printer/%s/upload_print" % pid, raw=body, ctype="multipart/form-data; boundary=" + b)


CARD = {}
CARD2 = {}
CARD2_HIST = []


def ws_reader():
    while True:
        try:
            with ws_connect("ws://127.0.0.1:%d/ws" % port, open_timeout=5, max_size=8 * 1024 * 1024) as c:
                while True:
                    m = json.loads(c.recv(timeout=60))
                    if isinstance(m, dict) and "cr1" in m and isinstance(m["cr1"], dict):
                        CARD.clear()
                        CARD.update(m["cr1"])
                    if isinstance(m, dict) and "cr2" in m and isinstance(m["cr2"], dict):
                        CARD2.clear()
                        CARD2.update(m["cr2"])
                        CARD2_HIST.append(m["cr2"].get("status"))
        except Exception:
            time.sleep(1.0)


def card(pred):
    return wait(lambda: pred(dict(CARD)) and dict(CARD), 30)


proc = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                        cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=(0x00000008 | 0x00000200))
try:
    up = wait(lambda: listening(port) and call("GET", "/version")[1].get("version") == SRC_VER, 150)
    check("C1. изолированный экземпляр поднялся (своя папка, порт, замок)", bool(up))
    threading.Thread(target=ws_reader, daemon=True).start()
    st, js = call("POST", "/api/printers/save", [{"id": "cr1", "name": "KE test", "type": "creality", "ip": "127.0.0.1",
                                                  "port": ws_port, "gen": "auto", "serial": "", "model": "Creality Ender-3 V3 KE"}])
    check("C2. принтер типа «creality» сохранён", st == 200, (st, js))
    c = card(lambda d: d.get("status") == "IDLE" and d.get("status_raw") == "idle")
    check("C3. карточка: «свободен» по снимку службы, температуры из строк", bool(c) and c.get("nozzle_temp") == 21.5
          and c.get("bed_temp") == 22.0, CARD)
    #  16.10.2026 (R-146): принтер в покое молчит — программа сама спрашивает его запросом только на чтение.
    asks = wait(lambda: len([m for m in SIM.got if m == ASK]) >= 2 and [t for t, m in SIM.got_ts if m == ASK], 30)
    gaps = [round(b - a, 1) for a, b in zip(asks or [], (asks or [])[1:])]
    check("C4. принтер молчит — программа сама спрашивает его (только чтение, как Creality Print), не чаще раза в 8 с, "
          "и больше ничего не шлёт; карточка остаётся «свободен»",
          bool(asks) and all(m == ASK for m in SIM.got) and all(g >= 7.5 for g in gaps)
          and CARD.get("status") == "IDLE", (SIM.got[:6], gaps, CARD.get("status")))
    n_hb = len(SIM.got)
    SIM.heartbeat_once()
    check("C4а. если принтер всё же пришлёт сердцебиение — ответ «ok»",
          bool(wait(lambda: "ok" in SIM.got[n_hb:], 10)), SIM.got[n_hb:])
    st, js = call("POST", "/api/printer/verify", {"ip": "127.0.0.1", "type": "creality", "port": ws_port})
    check("C5. проверка адреса при добавлении: служба Creality на порту отвечает", js.get("reachable") is True and js.get("match") is True, js)
    gcode = b";FLAVOR:Klipper\n;TIME:600\nG28\nG1 X10 Y10 F3000\n" * 50
    n0 = len(SIM.got)
    st, js = upload_print("cr1", "test_part.gcode", gcode)
    check("C6. отправка файла принята программой", js.get("status") == "ok" and js.get("accepted") is True, (st, js))
    got_file = wait(lambda: SIM.files.get("test_part.gcode"), 20)
    check("C7. файл дошёл до принтера байт в байт (POST /upload/<имя>, поле file)", got_file == gcode,
          (len(got_file or b""), len(gcode)))
    start_cmd = wait(lambda: [m for m in SIM.got[n0:] if "opGcodeFile" in m], 20)
    check("C8. перед стартом программа сверилась со списком файлов принтера, затем — ровно команда Creality Print",
          any("reqGcodeFile" in m for m in SIM.got[n0:]) and bool(start_cmd)
          and start_cmd[0] == '{"method":"set","params":{"opGcodeFile":"printprt:/usr/data/printer_data/gcodes/test_part.gcode","enableSelfTest":0}}',
          SIM.got[n0:])
    c = card(lambda d: d.get("status") == "RUNNING" and d.get("percent") == 5)
    check("C9. карточка: печать идёт, имя файла и процент из телеметрии", bool(c) and c.get("file_name") == "test_part"
          and c.get("remaining_time") == 10, CARD)
    jobs = wait(lambda: [j for j in call("GET", "/api/send-jobs")[1].get("jobs", []) if j.get("printer_id") == "cr1" and j.get("state") == "completed"], 30)
    check("C10. отправка подтверждена телеметрией (принтер сам сообщил о печати)", bool(jobs), call("GET", "/api/send-jobs")[1])
    n1 = len(SIM.got)
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "pause"})
    c = card(lambda d: d.get("status") == "PAUSED")
    check("C11. пауза: ровно {\"pause\":1}, карточка — на паузе", js.get("status") == "ok" and bool(c)
          and '{"method":"set","params":{"pause":1}}' in SIM.got[n1:], (js, SIM.got[n1:]))
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "resume"})
    c = card(lambda d: d.get("status") == "RUNNING")
    check("C12. продолжение: ровно {\"pause\":0}", js.get("status") == "ok" and bool(c)
          and '{"method":"set","params":{"pause":0}}' in SIM.got[n1:])
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "nozzle", "val": "205"})
    check("C13. температура сопла: {\"nozzleTempControl\":205}", js.get("status") == "ok"
          and wait(lambda: '{"method":"set","params":{"nozzleTempControl":205}}' in SIM.got[n1:], 10))
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "chamber", "val": "40"})
    check("C14. нагрев камеры этому типу не разрешён — отказ до принтера", st == 400 and not any("box" in m.lower() for m in SIM.got[n1:]), (st, js))
    SIM.ignore = True
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "pause"})
    check("C14а. принтер не подтвердил паузу — программа так и говорит (не «готово»)", st == 502
          and js.get("reason") == "command_not_confirmed", (st, js))
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "stop"})
    time.sleep(2)
    check("C14б. КРИТИЧНО: принтер не подтвердил стоп — задание НЕ закрыто, карточка по-прежнему «печать»",
          st == 502 and js.get("reason") == "stop_not_delivered" and CARD.get("status") == "RUNNING", (st, js, CARD.get("status")))
    SIM.ignore = False
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "stop"})
    c = card(lambda d: d.get("status_raw") == "cancelled" and d.get("status") != "RUNNING")
    check("C15. стоп: {\"stop\":1}; отмена — не сбой (красной ошибки нет)", js.get("status") == "ok" and bool(c)
          and not c.get("device_error") and '{"method":"set","params":{"stop":1}}' in SIM.got[n1:], (js, CARD))
    #  16.10.2026 (R-146): стоп «в духе K2» — принтер сразу «свободен» (state 0). Засчитывается, потому
    #  что ДО команды он печатал; если же он и до команды стоял свободным, 0 ничего не доказывает.
    SIM.stop_style = "state0"
    SIM.send_all({"state": 1, "deviceState": 1, "printProgress": 40})
    c = card(lambda d: d.get("status") == "RUNNING")
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "stop"})
    check("C15в. стоп у K2/Hi (сразу state 0): печать шла — стоп подтверждён, а не «не доставлено»",
          bool(c) and st == 200 and js.get("status") == "ok", (st, js, CARD.get("status")))
    c = card(lambda d: d.get("status") == "IDLE")
    SIM.ignore = True
    st, js = call("POST", "/api/printer/cr1/cmd", {"cmd": "stop"})
    check("C15г. принтер и до команды был свободен (state 0) и стоп не выполнил — подтверждения нет (502)",
          bool(c) and st == 502 and js.get("reason") == "stop_not_delivered", (st, js, CARD.get("status")))
    SIM.ignore = False
    SIM.stop_style = "k1"
    SIM.send_all({"state": 0, "deviceState": 1})
    c = card(lambda d: d.get("status") == "BUSY")
    nf = len(SIM.files)
    st, js = upload_print("cr1", "busy_part.gcode", gcode)
    time.sleep(2)
    #  13.10.2026: отказ «принтер занят» приходит сразу ответом на запрос (общая проверка всех входов
    #  отправки), задание отправки не создаётся вовсе — раньше отказывала проверка Creality внутри задания.
    check("C15а. принтер занят (едет домой, калибруется): карточка «Занят», отправка отказана сразу, файл не загружен",
          bool(c) and st == 409 and js.get("reason") == "printer_busy" and len(SIM.files) == nf, (CARD.get("status"), st, js))
    SIM.send_all({"deviceState": 0})
    card(lambda d: d.get("status") == "IDLE")
    n2 = len(SIM.got)
    st, js = upload_print("cr1", "rename_me.gcode", gcode)
    ren = wait(lambda: [j for j in call("GET", "/api/send-jobs")[1].get("jobs", []) if j.get("file_name") == "rename_me.gcode"
                        and j.get("state") == "failed"], 30)
    check("C15б. КРИТИЧНО: принтер сохранил файл под другим именем — печать НЕ запущена (не старый файл с тем же именем)",
          bool(ren) and not any("opGcodeFile" in m for m in SIM.got[n2:]), (ren, SIM.got[n2:]))
    st, js = upload_print("cr1", "plate.3mf", b"PK\x03\x04")
    bad = wait(lambda: [j for j in call("GET", "/api/send-jobs")[1].get("jobs", []) if j.get("file_name") == "plate.3mf"
                        and j.get("state") == "failed"], 20)
    check("C16. .3mf заводской прошивке не отправляется — понятный отказ, на принтер ничего не ушло",
          bool(bad) and "plate.3mf" not in SIM.files and ".gcode" in str((bad or [{}])[0].get("error") or ""), bad)
    logf = os.path.join(root, "logs", "farm.log")
    logtxt = io.open(logf, encoding="utf-8", errors="replace").read() if os.path.isfile(logf) else ""
    check("C17. первый полный снимок — в журнале: нужные поля, без имени принтера и адреса",
          "[CREALITY] cr1: полный снимок службы:" in logtxt and "KE-1234" not in logtxt and '"model": "F005"' in logtxt, logtxt[-800:])

    # ── 16.10.2026 (R-146): принтер, который молчит, пока его не спросят ──
    SIM2 = Sim(base=dict(FULL, features=["videoInfo.videoEncryption"], webrtcSupport=1, video=1, hostname="K1C-77"), silent=True)
    ws2_port = free_port()
    srv2 = serve(SIM2.handler, "127.0.0.1", ws2_port, compression=None)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    st, js = call("POST", "/api/printers/save", [
        {"id": "cr1", "name": "KE test", "type": "creality", "ip": "127.0.0.1", "port": ws_port, "gen": "auto", "serial": "",
         "model": "Creality Ender-3 V3 KE"},
        {"id": "cr2", "name": "K1C silent", "type": "creality", "ip": "127.0.0.1", "port": ws2_port, "gen": "auto", "serial": "",
         "model": "Creality K1C"}])
    c2 = wait(lambda: CARD2.get("status") == "IDLE" and dict(CARD2), 30)
    check("C19. молчащий принтер: программа спросила сама (только чтение) — карточка «свободен»",
          st == 200 and bool(c2) and SIM2.got and all(m == ASK for m in SIM2.got), (st, CARD2, SIM2.got[:4]))
    n_h2 = len(CARD2_HIST)
    time.sleep(24)                  # дольше, чем свежесть для отправки (20 с), и почти до порога обрыва (30 с)
    check("C20. и остаётся на связи: ни разу «не в сети», программа спрашивает не чаще раза в 8 с",
          CARD2.get("status") == "IDLE" and "OFFLINE" not in CARD2_HIST[n_h2:] and all(m == ASK for m in SIM2.got)
          and 3 <= len(SIM2.got) <= 6, (CARD2.get("status"), CARD2_HIST[n_h2:][-5:], len(SIM2.got)))
    st, js = upload_print("cr2", "silent_part.gcode", gcode)
    got2 = wait(lambda: SHARED_FILES.get("silent_part.gcode"), 20)
    jobs2 = wait(lambda: [j for j in call("GET", "/api/send-jobs")[1].get("jobs", []) if j.get("printer_id") == "cr2"
                          and j.get("state") in ("completed", "failed")], 40)
    check("C21. отправка на молчащий принтер не отказывает «Нет связи»: файл дошёл, старт подтверждён по запросу",
          js.get("status") == "ok" and got2 == gcode and bool(jobs2) and jobs2[0].get("state") == "completed"
          and any("opGcodeFile" in m for m in SIM2.got), (js, jobs2, SIM2.got[-3:]))
    logtxt = io.open(logf, encoding="utf-8", errors="replace").read() if os.path.isfile(logf) else ""
    check("C22. первый снимок молчащего принтера — в журнале, с признаками прошивки (features), без имени принтера",
          "[CREALITY] cr2: полный снимок службы:" in logtxt and '"features": ["videoInfo.videoEncryption"]' in logtxt
          and "K1C-77" not in logtxt, logtxt[-600:])
    srv2.shutdown()
    srv.shutdown()
    with SIM.lock:
        cs = list(SIM.clients)
    for cl in cs:
        try:
            cl.close()
        except Exception:
            pass
    c = wait(lambda: CARD.get("status") == "OFFLINE" and dict(CARD), 45)
    check("C18. служба пропала — карточка «не в сети»", bool(c), CARD)
finally:
    try:
        open(os.path.join(root, "stop.request"), "w", encoding="utf-8").write(token)
        wait(lambda: not listening(port), 60)
    except Exception:
        pass
    if proc.poll() is None and listening(port):
        proc.terminate()
    hsrv.shutdown()
    shutil.rmtree(root, ignore_errors=True)

print("\n--- метка-ловушка ---")
check("K1. метка-ловушка не попала в код", SENTINEL not in io.open(os.path.join(REPO, "app", "creality_native.py"), encoding="utf-8").read())
print("\n" + "=" * 76)
if fails:
    print("FAIL: провалено %d из %d" % (len(fails), len(names)))
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % len(names))
sys.exit(0)
