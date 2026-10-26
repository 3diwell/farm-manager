# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.978 — на живом изолированном сервере: «стоп» и отказ запуска больше не выдаются за успех.

ЗАЧЕМ. Две находки полной проверки, обе про одно и то же: программа сообщала владельцу об успехе
там, где до принтера ничего не дошло.

  * «Стоп». Пометка «остановлено владельцем» ставилась ДО обращения к принтеру и не откатывалась.
    Принтер без связи продолжал печатать, а программа с этого момента показывала его свободным —
    и показывала бы до конца печати: пометка снимается переходом в RUNNING, которого уже не будет.
  * Запуск на FlashForge. Ответ прошивки не читался вовсе: отказ («занят», «файла нет») выглядел
    как удачный запуск, и со склада списывались граммы за печать, которой не было.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ ИСПОЛНЕНИЕМ. Принтеры заведены на НЕСУЩЕСТВУЮЩИЕ адреса из документационной
подсети 192.0.2.0/24 (RFC 5737 — они не маршрутизируются и ничего живого задеть не могут), поэтому
команда гарантированно не доходит. Ожидание: отказ с внятной причиной, а не «ок».

КАК ЭТО БЕЗОПАСНО. Штатный режим изоляции (--fm-packaged-e2e): своя папка данных, свой config,
свой замок, свой порт. Рабочая база фермы не открывается; в конце это проверяется.

16.10.2026 (R-145, R-146, R-147): доставка проверяется у ВСЕХ команд, а не только у «стоп».
  * Пауза и нагрев недостижимому Bambu — 502 command_not_delivered (раньше «ок»).
  * FlashForge, который не ответил, — 502 command_not_confirmed (ответ принтера читается всегда).
  * Klipper (имитатор Moonraker на 127.0.0.1): медленный макрос CANCEL_PRINT — не «не доставлено»;
    тишина после отправки — «отправлено»; соединения нет — 502 command_not_delivered.
  * Нагрев нельзя выключить посреди печати без подтверждения: 409 heater_off_while_printing;
    с force — выполняется; на паузе — без вопроса.
  * Защита включена: команды принтеру и запуск печати попадают в журнал аудита с именем
    пользователя и телефона; файлы модулей /modules/* без входа не отдаются (R-149).

Запуск:  python tools/test_stop_and_refusal_e2e.py
"""
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import io
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
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_stop", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "STOP_AND_REFUSAL_E2E_SENTINEL_2_978"
PASS = FAIL = 0

#  Адреса из документационной подсети: гарантированно недостижимы и никому не принадлежат.
DEAD_BAMBU = "192.0.2.11"
DEAD_FF = "192.0.2.12"


#  16.10.2026 (R-145): имитатор Moonraker на этом компьютере. Moonraker отвечает на pause/cancel
#  только когда Klipper доработал макрос (pause_resume.py: gcode.run_script) — задержку задаёт проверка.
class _Moon(object):
    delay = {"pause": 0.0, "cancel": 0.0, "resume": 0.0}
    got = []
    refuse = False          # Moonraker отвечает ошибкой (Klippy not ready) — команда дошла, но не выполнена


class _MoonApi(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _out(self, code, obj):
        data = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def do_POST(self):
        act = self.path.split("?")[0].rsplit("/", 1)[-1]
        if self.path.startswith("/printer/print/") and act in _Moon.delay:
            _Moon.got.append(act)
            if _Moon.refuse:
                return self._out(503, {"error": {"code": 503, "message": "Klippy Host not connected"}})
            time.sleep(_Moon.delay[act])
            return self._out(200, {"result": "ok"})
        return self._out(404, {"error": "not found"})

    def do_GET(self):
        return self._out(404, {"error": "not found"})


class _TServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def http_c(port, method, path, body=None, cookie=None, timeout=90.0):
    """То же, что http(), с cookie сессии. -> (код, тело, значение fm_session из ответа или '')."""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
    head = "%s %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n" % (method, path)
    if cookie:
        head += "Cookie: fm_session=%s\r\n" % cookie
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
    headers = buf[:sep].decode("latin-1") if sep > 0 else ""
    payload = buf[sep + 4:] if sep >= 0 else buf
    try:
        code = int(buf.split(b" ", 2)[1])
    except Exception:
        code = 0
    tok = ""
    for ln in headers.split("\r\n"):
        if ln.lower().startswith("set-cookie:") and "fm_session=" in ln:
            tok = ln.split("fm_session=", 1)[1].split(";", 1)[0].strip().strip('"')
    if "transfer-encoding: chunked" in headers.lower():
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
        return code, json.loads(payload.decode("utf-8", "replace")), tok
    except Exception:
        return code, payload.decode("utf-8", "replace"), tok


def port_busy(p):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def http(port, method, path, body=None, timeout=90.0):
    """-> (код ответа, разобранное тело). Код нужен: отказ обязан быть отказом и по коду тоже."""
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
    try:
        code = int(buf.split(b" ", 2)[1])
    except Exception:
        code = 0
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
        return code, json.loads(payload.decode("utf-8", "replace"))
    except Exception:
        return code, payload.decode("utf-8", "replace")


run_dir = tempfile.mkdtemp(prefix="fmstope2e")
port = rv.free_local_port()
contract = rv.build_e2e_contract(run_dir, port)
contract["disables"]["printers"] = "0"      # воркеры нужны: без них нет ни виртуального принтера, ни связи
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
        _c, _ = http(port, "POST", "/api/printers/save", [
            {"id": "demo1", "name": "Виртуальный 1", "type": "demo", "ip": "", "port": None,
             "gen": "auto", "serial": "", "model": "Виртуальный принтер"},
            {"id": "bam1", "name": "Bambu без связи", "type": "bambu", "ip": DEAD_BAMBU, "port": 8883,
             "token": "FIXTURE_CODE", "gen": "auto", "serial": "FIXTURE0000000001", "model": "X1 Carbon"},
            {"id": "ff1", "name": "FlashForge без связи", "type": "flashforge", "ip": DEAD_FF, "port": 8898,
             "token": "FIXTURE_SERIAL:FIXTURE_CHECK", "gen": "auto", "serial": "", "model": "Adventurer 5M"},
        ])
        _c2, plist = http(port, "GET", "/api/printers")
        _ids = sorted(p.get("id") for p in plist) if isinstance(plist, list) else plist
        check("3. три принтера заведены", _ids == ["bam1", "demo1", "ff1"], _ids)

        print("--- «Стоп», который не дошёл до принтера ---")
        code, r = http(port, "POST", "/api/printer/bam1/cmd", {"cmd": "stop", "val": ""})
        check("4. «стоп» недостижимому Bambu отвечает отказом, а не «ок»",
              isinstance(r, dict) and r.get("status") == "error", (code, r))
        check("5. причина названа прямо: команда не доставлена",
              isinstance(r, dict) and r.get("reason") == "stop_not_delivered", r)
        check("6. код ответа тоже говорит об отказе (не 200)", code != 200, code)

        code2, r2 = http(port, "POST", "/api/printer/bam1/cmd", {"cmd": "stop", "val": ""})
        check("7. повторный «стоп» отвечает так же — состояние не «съехало»",
              isinstance(r2, dict) and r2.get("reason") == "stop_not_delivered", (code2, r2))

        code3, r3 = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "stop", "val": ""})
        check("8. у работающего принтера «стоп» по-прежнему успешен",
              code3 == 200 and isinstance(r3, dict) and r3.get("status") == "ok", (code3, r3))

        print("--- Запуск, который принтер не принял ---")
        code4, r4 = http(port, "POST", "/api/printer/ff1/cmd",
                         {"cmd": "start_print", "val": "нет-такого.gcode"})
        #  Запуск уходит в менеджер фоновых отправок: сам ответ — «принято в работу»,
        #  а правда о результате появляется в панели отправок.
        _job_state, _job_err = "", ""
        for _ in range(40):
            time.sleep(1.5)
            _c5, sj = http(port, "GET", "/api/send-jobs")
            jobs = (sj or {}).get("jobs") if isinstance(sj, dict) else None
            mine = [j for j in (jobs or []) if j.get("printer_id") == "ff1"]
            if mine:
                _job_state = str(mine[-1].get("state") or "")
                _job_err = str(mine[-1].get("error") or mine[-1].get("reason") or "")
            if _job_state in ("failed", "completed"):
                break
        check("9. отправка на недостижимый FlashForge завершилась НЕудачей",
              _job_state == "failed", (code4, r4, _job_state, _job_err))
        check("10. у неудачи есть внятная причина, а не пустота", bool(_job_err), _job_err)

        _c6, sj2 = http(port, "GET", "/api/send-jobs")
        _res = ((sj2 or {}).get("reserved_printer_ids") or []) if isinstance(sj2, dict) else []
        check("11. принтер не остался удержанным после неудачи", "ff1" not in _res, _res)

        # ── 16.10.2026 (R-145): доставка у ВСЕХ команд ─────────────────────────────────────────
        print("--- пауза и нагрев, которые не дошли до принтера ---")
        code, r = http(port, "POST", "/api/printer/bam1/cmd", {"cmd": "pause", "val": ""})
        check("13. пауза недостижимому Bambu: 502 command_not_delivered (раньше «ок»)",
              code == 502 and isinstance(r, dict) and r.get("reason") == "command_not_delivered", (code, r))
        code, r = http(port, "POST", "/api/printer/bam1/cmd", {"cmd": "nozzle", "val": "200"})
        check("14. нагрев сопла недостижимому Bambu: 502 command_not_delivered",
              code == 502 and isinstance(r, dict) and r.get("reason") == "command_not_delivered", (code, r))
        code, r = http(port, "POST", "/api/printer/ff1/cmd", {"cmd": "pause", "val": ""})
        check("15. FlashForge не ответил на паузу: 502 command_not_confirmed (ответ принтера читается)",
              code == 502 and isinstance(r, dict) and r.get("reason") == "command_not_confirmed", (code, r))

        print("--- Klipper: медленный макрос и нет соединения ---")
        _k9999 = port_busy(9999)
        check("K0. порт 9999 на этом компьютере свободен (иначе проверку Klipper не запускаем: команда "
              "сначала идёт родной службе Creality на :9999)", not _k9999)
        if not _k9999:
            _kport, _kdead = rv.free_local_port(), rv.free_local_port()
            _ksrv = _TServer(("127.0.0.1", _kport), _MoonApi)
            threading.Thread(target=_ksrv.serve_forever, daemon=True).start()
            _c, _ = http(port, "POST", "/api/printers/save", [
                {"id": "demo1", "name": "Виртуальный 1", "type": "demo", "ip": "", "port": None,
                 "gen": "auto", "serial": "", "model": "Виртуальный принтер"},
                {"id": "bam1", "name": "Bambu без связи", "type": "bambu", "ip": DEAD_BAMBU, "port": 8883,
                 "token": "FIXTURE_CODE", "gen": "auto", "serial": "FIXTURE0000000001", "model": "X1 Carbon"},
                {"id": "ff1", "name": "FlashForge без связи", "type": "flashforge", "ip": DEAD_FF, "port": 8898,
                 "token": "FIXTURE_SERIAL:FIXTURE_CHECK", "gen": "auto", "serial": "", "model": "Adventurer 5M"},
                {"id": "kl1", "name": "Klipper имитатор", "type": "klipper", "ip": "127.0.0.1", "port": _kport,
                 "gen": "auto", "serial": "", "model": "Voron 2.4"},
                {"id": "kl2", "name": "Klipper без связи", "type": "klipper", "ip": "127.0.0.1", "port": _kdead,
                 "gen": "auto", "serial": "", "model": "Voron 2.4"},
            ])
            _Moon.delay["cancel"] = 3.0
            _t0 = time.monotonic()
            code, r = http(port, "POST", "/api/printer/kl1/cmd", {"cmd": "stop", "val": ""})
            check("K1. «стоп» с макросом CANCEL_PRINT на 3 с — принят, а не «не доставлено» (раньше ждали 2 с)",
                  code == 200 and isinstance(r, dict) and r.get("status") == "ok" and "cancel" in _Moon.got,
                  (code, r, round(time.monotonic() - _t0, 1)))
            _Moon.delay["pause"] = 12.0
            _t0 = time.monotonic()
            code, r = http(port, "POST", "/api/printer/kl1/cmd", {"cmd": "pause", "val": ""})
            check("K2. пауза дошла, а макрос идёт дольше 10 с — «отправлено», не ошибка",
                  code == 200 and isinstance(r, dict) and r.get("status") == "ok"
                  and 9.0 <= time.monotonic() - _t0 < 30, (code, r, round(time.monotonic() - _t0, 1)))
            code, r = http(port, "POST", "/api/printer/kl2/cmd", {"cmd": "pause", "val": ""})
            check("K3. Klipper без соединения: пауза — 502 command_not_delivered (раньше «ок»)",
                  code == 502 and isinstance(r, dict) and r.get("reason") == "command_not_delivered", (code, r))
            code, r = http(port, "POST", "/api/printer/kl2/cmd", {"cmd": "bed", "val": "60"})
            check("K4. Klipper без соединения: нагрев стола — 502 command_not_delivered",
                  code == 502 and isinstance(r, dict) and r.get("reason") == "command_not_delivered", (code, r))
            _Moon.refuse = True
            code, r = http(port, "POST", "/api/printer/kl1/cmd", {"cmd": "resume", "val": ""})
            _Moon.refuse = False
            check("K5. Moonraker ответил ошибкой (Klippy not ready): «принтер не подтвердил команду», а не "
                  "«не дошла — проверьте связь» (16.10.2026)",
                  code == 502 and isinstance(r, dict) and r.get("reason") == "command_not_confirmed", (code, r))
            _ksrv.shutdown()

        print("--- выключение нагрева посреди печати ---")
        from websockets.sync.client import connect as _ws_connect
        _CARD = {}

        def _ws_reader():
            while True:
                try:
                    with _ws_connect("ws://127.0.0.1:%d/ws" % port, open_timeout=5, max_size=8 * 1024 * 1024) as c:
                        while True:
                            m = json.loads(c.recv(timeout=60))
                            if isinstance(m, dict) and isinstance(m.get("demo1"), dict):
                                _CARD.clear()
                                _CARD.update(m["demo1"])
                except Exception:
                    time.sleep(0.5)

        threading.Thread(target=_ws_reader, daemon=True).start()

        def _wait_status(want, t=20):
            end = time.monotonic() + t
            while time.monotonic() < end:
                if str(_CARD.get("status") or "") in want:
                    return True
                time.sleep(0.3)
            return False

        _wait_status(("IDLE", "FINISH"), 15)
        code, r = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "bed", "val": "0"})
        check("H1. принтер не печатает — стол выключается без вопросов",
              code == 200 and isinstance(r, dict) and r.get("status") == "ok", (code, r, _CARD.get("status")))
        code, r = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "start_print", "val": "деталь.gcode"})
        _run = _wait_status(("PREPARE", "RUNNING"), 20)
        code, r = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "bed", "val": "0"})
        code2, r2 = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "nozzle", "val": "0"})
        check("H2. печать идёт — выключить стол или сопло без подтверждения нельзя: 409 heater_off_while_printing",
              _run and code == 409 and isinstance(r, dict) and r.get("reason") == "heater_off_while_printing"
              and code2 == 409 and isinstance(r2, dict) and r2.get("reason") == "heater_off_while_printing",
              (_run, _CARD.get("status"), code, r, code2, r2))
        code, r = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "bed", "val": "60"})
        check("H3. печать идёт — изменить температуру (не ноль) можно", code == 200 and r.get("status") == "ok", (code, r))
        code, r = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "bed", "val": "0", "force": True})
        check("H4. с подтверждением (force) нагрев выключается", code == 200 and r.get("status") == "ok", (code, r))
        code, r = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "pause", "val": ""})
        _paused = _wait_status(("PAUSED",), 10)
        code, r = http(port, "POST", "/api/printer/demo1/cmd", {"cmd": "nozzle", "val": "0"})
        check("H5. на паузе остудить можно без вопроса", _paused and code == 200 and r.get("status") == "ok",
              (_paused, _CARD.get("status"), code, r))

        print("--- журнал аудита: кто послал команду ---")
        code, r, adm = http_c(port, "POST", "/api/auth/setup", {"username": "admin1", "password": "Admin-pass-16"})
        check("A0. защита включена, вошёл администратор", code == 200 and bool(adm), (code, r))
        code, r, dtok = http_c(port, "POST", "/api/auth/login",
                               {"username": "admin1", "password": "Admin-pass-16", "remember_device": True,
                                "device_name": "Тестовый телефон"})
        check("A0b. телефон запомнен", code == 200 and str(dtok).startswith("fmd_"), (code, r))
        code, r, _ = http_c(port, "POST", "/api/printer/demo1/cmd", {"cmd": "resume", "val": ""}, cookie=dtok)
        time.sleep(2.0)   # телеметрия виртуального принтера обновляется раз в 0,5 с: печать снова идёт
        code2, r2, _ = http_c(port, "POST", "/api/printer/demo1/cmd", {"cmd": "nozzle", "val": "0"}, cookie=dtok)
        code3, r3, _ = http_c(port, "POST", "/api/printer/demo1/cmd", {"cmd": "stop", "val": ""}, cookie=adm)
        _code, aud, _ = http_c(port, "GET", "/api/auth/audit?limit=50", cookie=adm)
        _rows = (aud.get("entries") or []) if isinstance(aud, dict) else []
        _cmd_rows = [x for x in _rows if isinstance(x, dict) and x.get("action") == "printer.cmd"]
        check("A1. команда с телефона в журнале: пользователь, принтер, действие и имя телефона",
              any(x.get("username") == "admin1" and "Виртуальный 1: resume" in str(x.get("target"))
                  and "Тестовый телефон" in str(x.get("target")) and x.get("result") == "ok" for x in _cmd_rows),
              (code, r, _cmd_rows[:5], aud if not _rows else ""))
        check("A2. отказ тоже в журнале — с причиной",
              any("nozzle 0°C" in str(x.get("target")) and x.get("result") == "heater_off_while_printing"
                  for x in _cmd_rows) and code2 == 409, (code2, r2, _cmd_rows[:5]))
        check("A3. команда с компьютера — без имени телефона",
              any("Виртуальный 1: stop" in str(x.get("target")) and "Тестовый телефон" not in str(x.get("target"))
                  for x in _cmd_rows), (code3, r3, _cmd_rows[:5]))
        #  После «стоп» виртуальный принтер ещё несколько секунд занят циклом отмены: запуск в это время
        #  отклоняется (printer_busy) — и отказ тоже попадает в журнал с причиной.
        _end, code, r = time.monotonic() + 20, 0, None
        while time.monotonic() < _end:
            code, r, _ = http_c(port, "POST", "/api/printer/demo1/cmd", {"cmd": "start_print", "val": "деталь2.gcode"},
                                cookie=dtok)
            if code == 200:
                break
            time.sleep(1.0)
        _code, aud, _ = http_c(port, "GET", "/api/auth/audit?limit=100", cookie=adm)
        _rows = (aud.get("entries") or []) if isinstance(aud, dict) else []
        _ps = [x for x in _rows if x.get("action") == "print.start"]
        check("A4. запуск печати с телефона в журнале (print.start): кто, принтер, файл, телефон, итог",
              code == 200 and any("Виртуальный 1: start_print деталь2.gcode" in str(x.get("target"))
                                  and "Тестовый телефон" in str(x.get("target")) and x.get("result") == "ok"
                                  and x.get("username") == "admin1" for x in _ps), (code, r, _ps[:5]))
        check("A5. отклонённый запуск (если был) записан с причиной, а не как «ok»",
              all(x.get("result") in ("ok", "printer_busy", "printer_held") for x in _ps), _ps[:5])

        #  16.10.2026 (R-149, аудит arch-auth-19): файлы интерфейса модулей — только после входа.
        #  Окно входа и проверка «вошёл ли» при этом доступны без входа, как раньше.
        _ma0, _, _ = http_c(port, "GET", "/modules/inventory/InventoryPanel.js")
        _ma1, _, _ = http_c(port, "GET", "/modules/inventory/InventoryPanel.js", cookie=adm)
        _st0, _stj, _ = http_c(port, "GET", "/api/auth/status")
        _pg0, _, _ = http_c(port, "GET", "/")
        check("A6. настоящий сервер с защитой: /modules/* без входа — 401, после входа — не 401; "
              "окно входа и /api/auth/status — без входа",
              _ma0 == 401 and _ma1 not in (0, 401) and _st0 == 200
              and isinstance(_stj, dict) and _stj.get("authenticated") is False and _pg0 == 200,
              (_ma0, _ma1, _st0, _stj, _pg0))

        #  16.10.2026 (R-145, решение c): смена пресетов прогрева (настройки фермы) — тоже в журнал:
        #  кто, с какого телефона, какие настройки и итог; отказ проверки — с причиной, а не «ok».
        _fs1, _fsj1, _ = http_c(port, "POST", "/api/farm-settings",
                                {"preheat_presets": [{"name": "PLA", "n": 215, "b": 60, "c": None}]}, cookie=dtok)
        _fs2, _fsj2, _ = http_c(port, "POST", "/api/farm-settings",
                                {"preheat_presets": [{"name": "", "n": 215, "b": 60}], "x\nevil": 1}, cookie=adm)
        _code, aud, _ = http_c(port, "GET", "/api/auth/audit?limit=200", cookie=adm)
        _rows = (aud.get("entries") or []) if isinstance(aud, dict) else []
        _fs = [x for x in _rows if isinstance(x, dict) and x.get("action") == "farm.settings"]
        check("A7. смена пресетов прогрева в журнале: кто, телефон, что изменено, итог; отказ — с причиной",
              _fs1 == 200 and isinstance(_fsj1, dict) and _fsj1.get("ok") is True
              and _fs2 == 200 and isinstance(_fsj2, dict) and _fsj2.get("ok") is False
              and any(x.get("username") == "admin1" and "preheat_presets" in str(x.get("target"))
                      and "Тестовый телефон" in str(x.get("target")) and x.get("result") == "ok" for x in _fs)
              and any(x.get("result") == _fsj2.get("error") and "Тестовый телефон" not in str(x.get("target"))
                      and "evil" not in str(x.get("target")) for x in _fs),
              (_fs1, _fsj1, _fs2, _fsj2, _fs[:5]))
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("12. рабочая папка данных не изменилась", prod_before == prod_after,
      set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)
print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
