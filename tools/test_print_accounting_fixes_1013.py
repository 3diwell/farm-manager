# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Учёт печати: исправления проверки ядра 13.10.2026.

ЧТО НАШЛА ПРОВЕРКА И ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ.
  1. Имя отправляемого файла запоминалось ДО отправки и при неудаче не снималось: следующая печать на
     принтере (с экрана, из слайсера) учитывалась под именем неотправленного файла. Теперь:
       · отправка на занятый принтер (печатает, пауза, готовится, цикл отмены) отклоняется сразу —
         printer_busy, ДО загрузки файла и до любых записей (_hold_block у всех четырёх входов);
       · неудачная отправка (ошибка или «старт не подтверждён») снимает запомненное имя.
  2. Сторож подтверждения старта гасил отправку молча: проектное задание висело «отправлено», деталь
     плана — «ждёт подтверждения старта» с удержанным принтером. Теперь он вызывает обратный вызов
     отправителя с reason=start_not_confirmed, а тот переводит деталь в «решает человек».
  3. «Стоп» или сбой во время ПАУЗЫ не закрывал печать в учёте: таймер печати не сбрасывался, и у
     следующей печати время шло от старта отменённой.

  A. настоящий блок менеджера отправок из server.py со стабами (как tools/test_print_send_manager.py);
  B. настоящий процесс программы против имитатора FlashForge: занятый принтер, неудачный старт,
     стоп во время паузы.

Сети наружу нет: всё на 127.0.0.1. Рабочие данные и принтеры владельца не трогаются.
Запуск: python tools/test_print_accounting_fixes_1013.py   (0 = пройдено)
"""
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
from app import e2e_isolation as ISO  # noqa: E402
from websockets.sync.client import connect as ws_connect  # noqa: E402

fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""), flush=True)
    if not ok:
        fails.append(name)


SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

# ════════════════════════════════════════════════════════════════════════════
print("\n--- A. менеджер отправок и проверка занятости (настоящий код server.py) ---")
block = SRC[SRC.index("from concurrent.futures import ThreadPoolExecutor as _SendPool"):SRC.index("\ndef _send_watchdog_loop")]
_uidc = [0]


def _uid(prefix=""):
    _uidc[0] += 1
    return str(prefix) + format(_uidc[0], "06d")


ORCH = []
CNS = {
    "threading": threading, "time": time, "os": os, "re": re,
    "_uid": _uid, "p_states": {}, "last_seen": {}, "STALE_FAIL_S": 60,
    "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None), "warning": staticmethod(lambda *a, **k: None),
                          "info": staticmethod(lambda *a, **k: None)})(),
    "_exc_brief": (lambda: ""),
    "server_print": {}, "_server_print_ts": {}, "print_source": {}, "plan_part": {},
    "norm": (lambda s: re.sub(r"[^a-z0-9]", "", str(s).lower()) if s else ""),
    "_orch": type("O", (), {"on_printer_failed": staticmethod(lambda *a, **k: ORCH.append(a))})(),
}


def _clear_job_state(pid, live=False, timer=False, dispatch=False):
    if dispatch:
        for d in (CNS["server_print"], CNS["_server_print_ts"], CNS["print_source"], CNS["plan_part"]):
            d.pop(pid, None)


CNS["_clear_job_state"] = _clear_job_state
exec(block, CNS)
Mgr = CNS["_PrintSendManager"]


def send_ok(progress):
    progress(stage="uploading")
    progress(command_ok=True)
    return {"status": "ok"}


def send_fail(progress):
    progress(stage="uploading")
    return {"status": "error", "reason": "printer refused"}


#  A1: неудачная отправка снимает запомненное имя ЭТОГО файла
m = Mgr()
CNS["server_print"]["P1"] = "partA.gcode"; CNS["print_source"]["P1"] = "plan"; CNS["plan_part"]["P1"] = "partA"
ok, j1, _ = m.begin_direct("P1", "P1", "partA.gcode", "task", send_fail)
time.sleep(0.4)
check("A1. отправка не удалась — запомненная «серверная» печать этого файла снята (и её источник)",
      "P1" not in CNS["server_print"] and "P1" not in CNS["print_source"] and "P1" not in CNS["plan_part"],
      (CNS["server_print"], CNS["print_source"]))
CNS["server_print"]["P2"] = "other.gcode"
ok, j2, _ = m.begin_direct("P2", "P2", "partB.gcode", "task", send_fail)
time.sleep(0.4)
check("A2. имя ДРУГОГО файла не трогается (неудача чужой отправки не стирает идущую печать)",
      CNS["server_print"].get("P2") == "other.gcode", CNS["server_print"])

#  A3: сторож «старт не подтверждён» зовёт отправителя с reason=start_not_confirmed
GOT = []
m3 = Mgr()
CNS["p_states"] = {"PW": {"status": "IDLE"}}; CNS["last_seen"] = {"PW": time.time()}
CNS["server_print"]["PW"] = "w.gcode"
ok, j3, _ = m3.begin_direct("PW", "PW", "w.gcode", "task", send_ok, lambda r: GOT.append(r))
time.sleep(0.3)
with m3._lock:
    m3._jobs[j3]["updated_at"] = time.time() - 100
m3.tick(now=time.time())
st3 = [x for x in m3.snapshot()["jobs"] if x["job_id"] == j3][0]["state"]
check("A3. старт не подтвердился — отправка failed, отправитель узнаёт reason=start_not_confirmed",
      st3 == "failed" and GOT == [{"status": "error", "reason": "start_not_confirmed"}], (st3, GOT))
check("A4. ...и запомненное имя этого файла снято (следующая печать не учтётся под ним)",
      "PW" not in CNS["server_print"], CNS["server_print"])
_ou = CNS.get("_orch_unconfirmed") or (lambda *a: None)
_ou("PW", "w.gcode", "pj-1", {"status": "error", "reason": "start_not_confirmed"})
_ou("PW", "w.gcode", "pj-2", {"status": "error", "reason": "upload failed"})
check("A5. деталь плана: неподтверждённый старт -> «решает человек»; обычная ошибка отправки — не здесь",
      ORCH == [("PW", "w.gcode", "pj-1", "start_not_confirmed")], ORCH)

#  A6-A8: занятый принтер отклоняется до отправки
SNAP = {}
CNS["_get_printer_safety_snapshot"] = lambda pid: dict(SNAP)
CNS["_send_mgr"] = Mgr()
hb = CNS["_hold_block"]
SNAP.clear(); SNAP.update({"fresh": True, "printing_active": True, "status": "IDLE", "status_raw": "RUNNING", "transport": "bambu"})
r6 = hb("PX")
SNAP.clear(); SNAP.update({"fresh": True, "printing_active": False, "status": "PAUSED"})
r7 = hb("PX")
SNAP.clear(); SNAP.update({"fresh": True, "printing_active": False, "status": "BUSY"})
r7b = hb("PX")
check("A6. печать идёт (в т.ч. цикл отмены под маской IDLE), пауза, «Занят» — отказ printer_busy до отправки",
      all(isinstance(x, dict) and x.get("reason") == "printer_busy" for x in (r6, r7, r7b)), (r6, r7, r7b))
SNAP.clear(); SNAP.update({"fresh": True, "printing_active": False, "status": "FINISH"})
r8a = hb("PX")
SNAP.clear(); SNAP.update({"fresh": False, "printing_active": True, "status": "OFFLINE"})
r8b = hb("PX")
check("A7. «готово, снимите деталь» и принтер не на связи — занятостью не считаются (как прежде)", r8a is None and r8b is None,
      (r8a, r8b))
SNAP.clear()
SNAP.update({"fresh": True, "printing_active": True, "user_stopped_pending": True, "status": "IDLE",
             "status_raw": "IDLE", "transport": "bambu"})
r8c = hb("PX")
check("A7а. после «Стоп» цикл отмены закончился (сырой IDLE), пометка ещё стоит — новую печать отправить МОЖНО",
      r8c is None, r8c)
check("A8. «принтер занят» понимают очередь и запуск как «доказанно не отправляли» (элемент ждёт, а не сбой)",
      '"printer_busy"' in SRC.split("_QW_SENT_NOT_STARTED = (", 1)[1][:200]
      and '"printer_busy"' in SRC.split("_definite = (", 1)[1][:200])

#  A9-A11: Bambu — настоящие строки разбора отчёта из server.py
_ln_st = [ln.strip() for ln in SRC.splitlines() if 'st = d.get("gcode_state"' in ln]
_ns = {"d": {}, "prev": {"status": "IDLE", "status_raw": "RUNNING"}}
if _ln_st:
    exec(_ln_st[0], _ns)
check("A9. Bambu: неполный отчёт без gcode_state после «Стоп» берёт СЫРОЕ прежнее состояние (RUNNING), а не маску IDLE",
      len(_ln_st) == 1 and _ns.get("st") == "RUNNING", (_ln_st, _ns.get("st")))
_ln_np = [ln.strip() for ln in SRC.splitlines() if ln.strip().startswith("_new_print = prev.get(\"status_raw\")")]
_r = {}
for raw_prev in ("PAUSE", "IDLE", "FINISH"):
    _ns2 = {"prev": {"status_raw": raw_prev}, "st": "RUNNING"}
    if _ln_np:
        exec(_ln_np[0], _ns2)
    _r[raw_prev] = _ns2.get("_new_print")
check("A10. Bambu: продолжение после паузы — не новая печать (пометка «Стоп» не слетает); после покоя/готово — новая",
      len(_ln_np) == 1 and _r == {"PAUSE": False, "IDLE": True, "FINISH": True}, _r)
check("A11. нет отсчёта времени — наблюдению уходит «неизвестно» (None), а не 0 «только началась»",
      "elapsed_seconds=(_print_elapsed(pid, _pst) if print_start_ts.get(pid) else None)" in SRC)

#  A12-A15: Creality K2 с CFS, режим «как в файле» — ячейка из строки T<n> файла (настоящая функция)
from app import gcode_tool_slot as _GTS  # noqa: E402
_i = SRC.find("def _klipper_dispatch_slots(pid")
_j = SRC.find("\n\n\n", _i)
_NSK = {"log": CNS["log"], "_exc_brief": (lambda: ""), "_gts": _GTS}
exec(compile(SRC[_i:_j], "<server>", "exec"), _NSK)
_disp = _NSK["_klipper_dispatch_slots"]
_TR = [{"index": i, "unit": 0, "tray": i, "label": "T1" + "ABCD"[i]} for i in range(4)]
_NSK["p_states"] = {"k2": {"cfs_trays": _TR, "cfs_now": 0}, "k2e": {"cfs_trays": _TR, "cfs_now": -1}}
F_T1 = b"START_PRINT EXTRUDER_TEMP=250\nT1\nM104 S250\n; filament used [g] = 0.00, 3.66\n"
F_NONE = b"START_PRINT\nG1 X1\n"
F_MULTI = b"T0\nG1 X1\nT2\nG1 X2\n"
check("A12. K2 CFS «как в файле»: файл нарезан под T1B (строка T1), в голове T1A — списание с T1B",
      _disp("k2", None, F_T1) == ([1], False), _disp("k2", None, F_T1))
check("A13. голова пуста (cfs_now -1), файл под T1B — списание с T1B (раньше — ни с чего)",
      _disp("k2e", None, F_T1) == ([1], False), _disp("k2e", None, F_T1))
check("A14. строк T<n> нет или их несколько — прежнее правило: заправленная ячейка",
      _disp("k2", None, F_NONE) == ([0], False) and _disp("k2", None, F_MULTI) == ([0], False))
check("A15. выбранная человеком ячейка по-прежнему главнее файла; без файла — как раньше",
      _disp("k2", 3, F_T1) == ([3], False) and _disp("k2", None, None) == ([0], False))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- B. настоящий процесс против имитатора FlashForge ---")


class Sim(object):
    status = "ready"
    fname = ""
    uploads = []
    started = []
    refuse_print = False


SIM = Sim()
SERIAL, CHECK = "SNFF5M0001", "chk" + secrets.token_hex(3)


class Api(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, out):
        data = json.dumps(out).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        if self.path == "/uploadGcode":
            m = re.search(rb'filename="([^"]+)"', raw)
            SIM.uploads.append(m.group(1).decode() if m else "?")
            return self._reply({"code": 0, "message": "Success"})
        body = json.loads(raw.decode("utf-8") or "{}")
        if body.get("serialNumber") != SERIAL or body.get("checkCode") != CHECK:
            return self._reply({"code": 1, "message": "auth"})
        if self.path == "/detail":
            return self._reply({"code": 0, "message": "Success", "detail": {
                "status": SIM.status, "printProgress": 0.2 if SIM.status != "ready" else 0, "printFileName": SIM.fname,
                "estimatedTime": 30, "rightTemp": 200.0, "platTemp": 50.0, "cameraStreamUrl": ""}})
        if self.path == "/gcodeList":
            return self._reply({"code": 0, "gcodeList": list(SIM.uploads)})
        if self.path == "/printGcode":
            if SIM.refuse_print:
                return self._reply({"code": 1, "message": "printer busy"})
            SIM.started.append(body.get("fileName"))
            SIM.status, SIM.fname = "printing", "/data/" + str(body.get("fileName"))
            return self._reply({"code": 0, "message": "Success"})
        if self.path == "/control":
            return self._reply({"code": 0, "message": "Success"})
        return self._reply({"code": 1, "message": "unknown"})


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


api_port = free_port()
threading.Thread(target=TServer(("127.0.0.1", api_port), Api).serve_forever, daemon=True).start()
PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
root = tempfile.mkdtemp(prefix="fm_e2e_acct_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD) + os.sep)
port = free_port()
token = "ACCT_E2E_" + secrets.token_hex(8)
json.dump({"token": token, "sentinel": "ACCT_E2E_1310"}, open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8"))
cfgp = os.path.join(root, "config.json")
json.dump({"server_port": port}, open(cfgp, "w", encoding="utf-8"))
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_ACCT_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "0",
            ISO.ENV_NO_MODULES: "1", "PYTHONDONTWRITEBYTECODE": "1"})
SRC_VER = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)


def call(method, path, body=None, raw=None, ctype=None):
    data = json.dumps(body).encode("utf-8") if body is not None else raw
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}


def multipart(field, fname, data):
    b = "----fmacct" + secrets.token_hex(6)
    body = (("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
             "Content-Type: application/octet-stream\r\n\r\n") % (b, field, fname)).encode("utf-8") + data + ("\r\n--%s--\r\n" % b).encode()
    return body, "multipart/form-data; boundary=" + b


CARD = {}


def ws_reader():
    while True:
        try:
            with ws_connect("ws://127.0.0.1:%d/ws" % port, open_timeout=5, max_size=8 * 1024 * 1024) as c:
                while True:
                    m = json.loads(c.recv(timeout=60))
                    if isinstance(m, dict) and "ff1" in m and isinstance(m["ff1"], dict):
                        CARD.clear()
                        CARD.update(m["ff1"])
        except Exception:
            time.sleep(1.0)


def task_status(name):
    st, js = call("GET", "/api/staging")
    rows = js if isinstance(js, list) else (js.get("files") or js.get("staging") or [])
    for r in rows:
        if str(r.get("filename")) == name:
            return str(r.get("status") or "")
    return None


GCODE = b";FLAVOR:Marlin\n;TIME:600\nG28\nG1 X10 Y10 F3000\n" * 20
proc = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                        cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=(0x00000008 | 0x00000200))
try:
    up = wait(lambda: listening(port) and call("GET", "/version")[1].get("version") == SRC_VER, 150)
    check("B0. изолированный экземпляр поднялся", bool(up))
    st, js = call("POST", "/api/printers/save", [{"id": "ff1", "name": "AD5M test", "type": "flashforge", "ip": "127.0.0.1",
                                                  "port": api_port, "token": SERIAL + ":" + CHECK, "serial": SERIAL,
                                                  "model": "Flashforge Adventurer 5M"}])
    threading.Thread(target=ws_reader, daemon=True).start()
    for nm in ("taskA.gcode", "taskB.gcode"):
        body, ct = multipart("files", nm, GCODE)
        call("POST", "/api/staging/upload", raw=body, ctype=ct)
    check("B1. две задачи в «Задачах», принтер свободен", task_status("taskA.gcode") is not None
          and task_status("taskB.gcode") is not None and wait(lambda: CARD.get("status") == "IDLE", 30), (CARD.get("status")))

    #  B2: принтер печатает A с экрана — отправка B отклоняется сразу, файл на принтер не уходит
    SIM.status, SIM.fname = "printing", "/data/taskA.gcode"
    wait(lambda: CARD.get("status") == "RUNNING", 20)
    n_up = len(SIM.uploads)
    body, ct = multipart("file", "taskB.gcode", GCODE)
    st, js = call("POST", "/api/printer/ff1/upload_print", raw=body, ctype=ct)
    time.sleep(2)
    check("B2. ГЛАВНОЕ: печатающему принтеру новая печать не уходит — отказ printer_busy, файл не загружается",
          st == 409 and js.get("reason") == "printer_busy" and len(SIM.uploads) == n_up, (st, js, SIM.uploads[n_up:]))
    check("B3. задача A засчитана как печатающаяся по имени, B — нет", task_status("taskA.gcode") == "printing"
          and task_status("taskB.gcode") != "printing", (task_status("taskA.gcode"), task_status("taskB.gcode")))

    #  B4: пауза -> стоп (отмена) -> новая печать: таймер новой печати с нуля
    time.sleep(8)
    SIM.status = "pause"
    wait(lambda: CARD.get("status") == "PAUSED", 20)
    time.sleep(3)
    SIM.status = "cancel"
    wait(lambda: CARD.get("status") in ("IDLE",) or CARD.get("status_raw") == "cancel", 20)
    time.sleep(3)
    SIM.status, SIM.fname = "ready", ""
    wait(lambda: CARD.get("status") == "IDLE", 20)
    SIM.status, SIM.fname = "printing", "/data/screen_other.gcode"
    c = wait(lambda: CARD.get("status") == "RUNNING" and CARD.get("file_name") == "screen_other" and dict(CARD), 20)
    time.sleep(2)
    el = CARD.get("elapsed")
    check("B4. стоп во время паузы закрыл печать: у следующей время печати с нуля, а не от старта отменённой",
          bool(c) and el is not None and el < 8, (el, CARD.get("status")))
    check("B5. задача A после стопа не висит «печатается»", task_status("taskA.gcode") != "printing", task_status("taskA.gcode"))

    #  B6: отправка B на свободный принтер не удалась (принтер отказал старт) — следующая печать с экрана
    #  НЕ записывается на задачу B
    SIM.status, SIM.fname = "ready", ""
    wait(lambda: CARD.get("status") == "IDLE", 20)
    SIM.refuse_print = True
    body, ct = multipart("file", "taskB.gcode", GCODE)
    st, js = call("POST", "/api/printer/ff1/upload_print", raw=body, ctype=ct)
    jid = js.get("job_id")
    failed = wait(lambda: [j for j in call("GET", "/api/send-jobs")[1].get("jobs", []) if j.get("job_id") == jid
                           and j.get("state") == "failed"], 40)
    check("B6. отправка принята, но принтер отказал старт — отправка «не удалась»", bool(failed), call("GET", "/api/send-jobs")[1])
    SIM.refuse_print = False
    time.sleep(11)                        # «тихое окно» после команды старта FlashForge
    SIM.status, SIM.fname = "printing", "/data/screen_third.gcode"
    c = wait(lambda: CARD.get("status") == "RUNNING" and dict(CARD), 25)
    time.sleep(3)
    check("B7. ГЛАВНОЕ: чужая печать после неудачной отправки идёт под своим именем, задача B не «печатается»",
          bool(c) and CARD.get("file_name") == "screen_third" and task_status("taskB.gcode") != "printing",
          (CARD.get("file_name"), task_status("taskB.gcode")))
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
