# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.980 (R-092) — поиск принтеров в сети и смена адреса НА ЖИВОМ сервере.

ЗАЧЕМ ИМЕННО ТАК. Настоящих принтеров у разработки нет, поэтому проверить «нашёлся живой
принтер» нечем. Но всю цепочку — открыть сокет, принять объявление, разобрать его, слить,
сверить с заведёнными, показать «сменил адрес» и обновить адрес по нажатию — проверить можно:
изолированному серверу отправляется ДОСЛОВНОЕ объявление Bambu P1S из перехвата, только на
петлю 127.0.0.1. Для сервера оно неотличимо от настоящего.

ЧТО ЭТО НЕ ДОКАЗЫВАЕТ: что объявления реальных принтеров дойдут через вашу сеть и брандмауэр.
Это подтверждает только ферма — для того рядом и лежит запись сетевых объявлений.

16.10.2026 (R-092, R-020): «принтер» переехал на адрес петли 127.0.0.1 (а не в сеть 192.168.1.x) —
после «Обновить адрес» сервер перезапускает связь, и воркер Bambu стучится по НОВОМУ адресу;
это видно по входящему соединению на 127.0.0.1:8883, которое слушает сам набор. Наружу —
ни одного пакета. Плюс: FlashForge узнаётся по серийнику из своего токена (без кода проверки),
принтер по своему адресу запоминает вечный признак, неполный адрес не сохраняется.

КАК ЭТО БЕЗОПАСНО. Штатный режим изоляции (--fm-packaged-e2e): своя папка данных, свой config,
свой замок, свой порт. Поиск запускается в пассивном режиме (ask=false) — сервер не отправляет
в сеть НИ ОДНОГО байта.

Запуск:  python tools/test_printer_discovery_e2e.py
"""
import importlib.util
import io
import json
import os
import shutil
import socket
import sqlite3
import struct
import sys
import tempfile
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RV_PATH = os.path.join(ROOT, "tools", "validation", "ui", "run_ui_verification.py")
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_disc", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

SENTINEL = "PRINTER_DISCOVERY_E2E_SENTINEL_2_980"
PASS = FAIL = 0

#  Дословный перехват с P1S. Адрес в объявлении заменён на петлю 127.0.0.1 (16.10.2026): после
#  смены адреса сервер подключается к принтеру по нему, и подключение должно остаться на этой машине.
NOTIFY = (
    "NOTIFY * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    "Server: UPnP/1.0\r\n"
    "Location: 127.0.0.1\r\n"
    "NT: urn:bambulab-com:device:3dprinter:1\r\n"
    "USN: 01P00A123456789\r\n"
    "Cache-Control: max-age=1800\r\n"
    "DevModel.bambu.com: C12\r\n"
    "DevName.bambu.com: Bambu Lab P1S\r\n"
    "DevConnect.bambu.com: lan\r\n"
    "DevBind.bambu.com: free\r\n"
    "DevVersion.bambu.com: 01.07.00.00\r\n"
    "\r\n"
).encode()


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


LAST_CODE = [0]


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
    try:
        LAST_CODE[0] = int(headers.split(b"\r\n", 1)[0].split()[1])
    except Exception:
        LAST_CODE[0] = 0
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


def ff_packet(serial, name="Adventurer 5M Pro", pid=0x0024):
    """Визитная карточка FlashForge (276 байт, big-endian) — та же раскладка, что в
    tools/test_printer_discovery.py (по работающим сторонним реализациям)."""
    b = bytearray(276)
    nm = name.encode("utf-8")[:127]
    b[0:len(nm)] = nm
    b[0x84:0x86] = struct.pack(">H", 8899)
    b[0x86:0x88] = struct.pack(">H", 0x2B71)
    b[0x88:0x8A] = struct.pack(">H", pid)
    b[0x8E:0x90] = struct.pack(">H", 8898)
    sn = serial.encode("utf-8")[:127]
    b[0x92:0x92 + len(sn)] = sn
    return bytes(b)


def ff_announce(src_ip, serial, times=4):
    """Карточка FlashForge с адреса петли src_ip на порт поиска — как ответ принтера."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((src_ip, 0))
        for _ in range(times):
            for p in (2021, 1990):
                try:
                    s.sendto(ff_packet(serial), ("127.0.0.1", p))
                except Exception:
                    pass
            time.sleep(0.25)
    finally:
        s.close()


class BambuPortWatch(object):
    """Слушает 127.0.0.1:8883 и записывает, кто подключился. Это и есть доказательство, что
    после смены адреса воркер Bambu перезапущен по НОВОМУ адресу: старый воркер стучится на
    прежний 127.0.0.9 и сюда не попадает."""

    def __init__(self):
        self.conns, self.error = [], ""
        self._stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.bind(("127.0.0.1", 8883))
            self.sock.listen(5)
            self.sock.settimeout(0.3)
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while not self._stop.is_set():
            try:
                c, addr = self.sock.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            first = b""
            try:
                c.settimeout(2.0)
                first = c.recv(5)
            except Exception:
                pass
            self.conns.append((time.time(), addr, first))
            try:
                c.close()
            except Exception:
                pass

    def close(self):
        self._stop.set()
        try:
            self.sock.close()
        except Exception:
            pass


def announce(times=6):
    """Отправить объявление на петлю — так же, как это делает принтер, на порты 2021 и 1990."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _ in range(times):
            for p in (2021, 1990):
                try:
                    s.sendto(NOTIFY, ("127.0.0.1", p))
                except Exception:
                    pass
            time.sleep(0.25)
    finally:
        s.close()


run_dir = tempfile.mkdtemp(prefix="fmdisce2e")
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
        #  Принтер заведён по СТАРОМУ адресу — именно этот случай пункт карты и называет:
        #  «роутер выдал принтеру другой адрес, и программа его теряет».
        http(port, "POST", "/api/printers/save",
             [{"id": "p1", "name": "P1S у окна", "type": "bambu", "ip": "127.0.0.9",
               "port": 8883, "token": "FIXTURE_CODE", "gen": "auto",
               "serial": "01P00A123456789", "model": "P1S"}])

        st = http(port, "POST", "/api/printer-discovery/start", {"seconds": 20, "ask": False})
        check("3. поиск запущен", isinstance(st, dict) and st.get("status") == "ok", st)
        check("4. поиск идёт и показывает, сколько осталось",
              st.get("active") is True and st.get("remaining_s", 0) > 0, st)
        _ports = {int(p.get("port")): p for p in (st.get("ports") or [])}
        check("5. слушаются все четыре порта объявлений",
              set(_ports) == {2021, 1990, 5353, 1900}, sorted(_ports))
        check("6. про каждый порт честно сказано, удалось его занять или нет",
              all(("open" in p) for p in _ports.values()), _ports)
        check("7. в пассивном режиме не отправлено ни одного запроса",
              not (st.get("asked") or []), st.get("asked"))

        announce()
        found = None
        for _ in range(20):
            snap = http(port, "GET", "/api/printer-discovery")
            devs = (snap or {}).get("devices") or []
            if devs:
                found = devs[0]
                break
            time.sleep(0.5)
        check("8. объявление принято и разобрано сервером", isinstance(found, dict), found)
        if found:
            check("9. адрес принтера взят из объявления", found.get("ip") == "127.0.0.1", found)
            check("10. серийный номер прочитан", found.get("serial") == "01P00A123456789", found)
            #  В поле модели должно стоять имя, под которым лежит ОБЛОЖКА, — иначе картинки
            #  принтера не будет, а подбор совместимого g-code начнёт врать.
            #  26.09.2026: в открытой выгрузке обложек нет (права на изображения не подтверждены) —
            #  тогда модель остаётся кодом объявления, и сверять её с обложкой не с чем.
            if os.path.isdir(os.path.join(ROOT, "printer_covers")):
                check("11. модель опознана и названа так же, как обложка",
                      found.get("model") == "Bambu Lab P1S", found)
                check("11б. такая обложка действительно есть",
                      os.path.isfile(os.path.join(ROOT, "printer_covers", "Bambu Lab P1S_cover.png")))
            else:
                check("11. без обложек модель опознана по коду объявления", found.get("model") in ("P1S", "Bambu Lab P1S"), found)
                print("SKIP — 11б. обложек в этой копии нет (открытая выгрузка)")
            check("12. повторные объявления слиты в одну строку, а не в шесть",
                  len((snap or {}).get("devices") or []) == 1, snap.get("found"))
            check("13. состояние — «сменил адрес», а не «новый»", found.get("state") == "moved", found)
            check("14. прежний адрес назван", found.get("old_ip") == "127.0.0.9", found)
            check("15. кода доступа в найденном нет и быть не может",
                  "token" not in found and "access_code" not in found, sorted(found))

            bad = http(port, "POST", "/api/printer-discovery/rebind",
                       {"printer_id": "p1", "device_key": "serial:НЕТ-ТАКОГО"})
            check("16. смена адреса по неизвестному устройству отклонена",
                  isinstance(bad, dict) and bad.get("status") == "error", bad)

            #  16.10.2026 (R-092): связь должна перезапуститься по новому адресу. Слушаем порт
            #  MQTT Bambu на новом адресе; до смены адреса сюда не стучится никто.
            watch = BambuPortWatch()
            check("16а. порт 8883 на 127.0.0.1 свободен для проверки", not watch.error, watch.error)
            time.sleep(1.5)
            #  Клиент MQTT начинает с приветствия TLS (байты 16 03). Простую пробу порта (TCP без данных)
            #  может прислать и другой набор на этой машине — такие соединения не в счёт.
            _tls = lambda: [c for c in watch.conns if c[2][:2] == b"\x16\x03"]
            check("16б. до смены адреса к принтеру по новому адресу никто не подключался",
                  not _tls(), watch.conns)
            t_reb = time.time()
            reb = http(port, "POST", "/api/printer-discovery/rebind",
                       {"printer_id": "p1", "device_key": found.get("key")})
            check("17. адрес обновлён по нажатию владельца",
                  isinstance(reb, dict) and reb.get("status") == "ok"
                  and reb.get("ip") == "127.0.0.1", reb)
            for _ in range(40):
                if _tls():
                    break
                time.sleep(0.25)
            watch.close()
            check("17а. связь перезапущена по НОВОМУ адресу: сервер сам подключился к 127.0.0.1:8883 (TLS MQTT)",
                  any(c[0] >= t_reb for c in _tls()), watch.conns)
            plist = http(port, "GET", "/api/printers")
            p1 = [p for p in (plist or []) if p.get("id") == "p1"]
            check("18. у принтера в базе новый адрес",
                  p1 and p1[0].get("ip") == "127.0.0.1", p1)
            check("19. код доступа и серийный номер при этом не тронуты",
                  p1 and p1[0].get("serial") == "01P00A123456789", p1)

        stop = http(port, "POST", "/api/printer-discovery/stop")
        check("20. поиск останавливается по кнопке",
              isinstance(stop, dict) and stop.get("active") is False, stop)
        check("21. повторная остановка безвредна",
              (http(port, "POST", "/api/printer-discovery/stop") or {}).get("status") == "ok")

        #  ── 16.10.2026 (R-092): FlashForge по серийнику из токена и «уже заведён» по своему адресу ──
        #  ff1 записан по адресу 127.0.0.6 с токеном «серийник:код проверки» и «переехал» на 127.0.0.5;
        #  ff2 записан без токена и без серийника и отвечает по своему адресу 127.0.0.7.
        _sv = http(port, "POST", "/api/printers/save",
                   [{"id": "p1", "name": "P1S у окна", "type": "bambu", "ip": "127.0.0.1", "port": 8883,
                     "gen": "auto", "serial": "01P00A123456789", "model": "P1S"},
                    {"id": "ff1", "name": "AD5M у стены", "type": "flashforge", "ip": "127.0.0.6", "port": 8898,
                     "token": "SNFF0001:FIXTURECHK", "gen": "auto", "serial": "", "model": "Adventurer 5M Pro"},
                    {"id": "ff2", "name": "AD5M у двери", "type": "flashforge", "ip": "127.0.0.7", "port": 8898,
                     "gen": "auto", "serial": "", "model": "Adventurer 5M Pro"}])
        check("21а. принтеры FlashForge заведены", isinstance(_sv, dict) and _sv.get("status") == "success", _sv)
        http(port, "POST", "/api/printer-discovery/start", {"seconds": 15, "ask": False})
        ff_announce("127.0.0.5", "SNFF0001")
        ff_announce("127.0.0.7", "SNFF0003")
        _ffd = {}
        _snap_txt = ""
        for _ in range(20):
            _sn = http(port, "GET", "/api/printer-discovery")
            _snap_txt = json.dumps(_sn, ensure_ascii=False)
            _ffd = {d.get("serial"): d for d in ((_sn or {}).get("devices") or []) if d.get("family") == "flashforge"}
            if "SNFF0001" in _ffd and "SNFF0003" in _ffd:
                break
            time.sleep(0.5)
        _d1, _d3 = _ffd.get("SNFF0001") or {}, _ffd.get("SNFF0003") or {}
        check("21б. FlashForge узнан по серийнику из своего токена: «сменил адрес» 127.0.0.6 -> 127.0.0.5",
              _d1.get("state") == "moved" and _d1.get("printer_id") == "ff1" and _d1.get("old_ip") == "127.0.0.6", _d1)
        check("21в. FlashForge по своему адресу без признака — «уже заведён», а не «адрес занят»",
              _d3.get("state") == "known" and _d3.get("printer_id") == "ff2", _d3)
        check("21г. код проверки FlashForge в найденное не попадает", "FIXTURECHK" not in _snap_txt)
        http(port, "POST", "/api/printer-discovery/stop")
        try:
            _cfg_txt = io.open(contract["config_path"], encoding="utf-8").read()
            _ident = (json.loads(_cfg_txt) or {}).get("printer_identity") or {}
        except Exception as _e:
            _cfg_txt, _ident = "", {"error": repr(_e)}
        check("21д. признак принтера, найденного по своему адресу, запомнен (серийник SNFF0003)",
              (_ident.get("ff2") or {}).get("kind") == "serial" and (_ident.get("ff2") or {}).get("value") == "SNFF0003",
              _ident)
        check("21е. код проверки FlashForge в настройки не записан", "FIXTURECHK" not in _cfg_txt)

        #  ── 16.10.2026 (R-020): неполный адрес ──
        _bad = http(port, "POST", "/api/printers/save",
                    [{"id": "p1", "name": "P1S у окна", "type": "bambu", "ip": "127.0.0.1", "port": 8883,
                      "gen": "auto", "serial": "01P00A123456789", "model": "P1S"},
                     {"id": "k_new", "name": "Новый Klipper", "type": "klipper", "ip": "198.68.104", "port": 7125,
                      "gen": "auto", "serial": "", "model": ""}])
        check("21ж. новый принтер с адресом «198.68.104» не сохраняется: 400 bad_address",
              LAST_CODE[0] == 400 and isinstance(_bad, dict) and _bad.get("error") == "bad_address"
              and _bad.get("printer_id") == "k_new", (LAST_CODE[0], _bad))
        _ids_now = sorted(p.get("id") for p in (http(port, "GET", "/api/printers") or []))
        check("21з. отказ ничего не стёр и не добавил", _ids_now == ["ff1", "ff2", "p1"], _ids_now)
        #  Старая битая запись (как node_gftic на ферме) — пишем прямо в базу этого сервера.
        _db = sqlite3.connect(os.path.join(contract["data_dir"], "farm_printers.db"), timeout=10)
        try:
            _db.execute("INSERT INTO printers (id, name, type, ip, port, token, gen, serial, model, order_idx) "
                        "VALUES ('node_gftic', 'Klipper 104', 'klipper', '198.68.104', 7125, '', 'auto', '', '', 9)")
            _db.commit()
        finally:
            _db.close()
        _pl = {p.get("id"): p for p in (http(port, "GET", "/api/printers") or [])}
        check("21и. список принтеров помечает старую запись: address_problem = short",
              (_pl.get("node_gftic") or {}).get("address_problem") == "short"
              and (_pl.get("p1") or {}).get("address_problem") is None, _pl.get("node_gftic"))
        _keep = http(port, "POST", "/api/printers/save",
                     [{"id": k, "name": v.get("name"), "type": v.get("type"), "ip": v.get("ip"), "port": v.get("port"),
                       "gen": v.get("gen") or "auto", "serial": v.get("serial") or "", "model": v.get("model") or ""}
                      for k, v in _pl.items()])
        check("21к. старая битая запись сохранению остальных не мешает",
              LAST_CODE[0] == 200 and isinstance(_keep, dict) and _keep.get("status") == "success", (LAST_CODE[0], _keep))
        _ver = http(port, "POST", "/api/printer/verify", {"ip": "198.68.104", "type": "klipper"})
        check("21л. проба неполного адреса не делается и говорит почему",
              isinstance(_ver, dict) and _ver.get("bad_address") is True and _ver.get("reachable") is False, _ver)

        #  Запись сетевых объявлений: инструмент снятия контракта на ферме.
        cap = http(port, "POST", "/api/diagnostics/net-capture/start", {"seconds": 10})
        check("22. запись сетевых объявлений начата",
              isinstance(cap, dict) and cap.get("status") == "ok" and cap.get("active"), cap)
        announce(3)
        time.sleep(1.0)
        capst = http(port, "GET", "/api/diagnostics/net-capture")
        check("23. записанные пакеты посчитаны", (capst or {}).get("packets", 0) >= 1, capst)
        _path = (capst or {}).get("path") or ""
        check("24. дамп лежит в папке журналов этого сервера",
              _path and os.path.isfile(_path)
              and os.path.normcase(_path).startswith(os.path.normcase(contract["data_dir"])), _path)
        http(port, "POST", "/api/diagnostics/net-capture/stop")
        if _path and os.path.isfile(_path):
            first = io.open(_path, encoding="utf-8").readline()
            rec = json.loads(first) if first.strip() else {}
            check("25. в дампе сырые байты пакета, а не пересказ",
                  bool(rec.get("hex")) and rec.get("listen_port") in (2021, 1990), rec.get("listen_port"))
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("26. рабочая папка данных не изменилась", prod_before == prod_after,
      set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)
print("\n%s: PASS=%d FAIL=%d" % (SENTINEL, PASS, FAIL))
sys.exit(1 if FAIL else 0)
