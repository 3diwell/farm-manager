# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.980 (R-092) — разбор объявлений принтеров и правила поиска в сети.

ЧТО ПРОВЕРЯЕТСЯ. Разбор идёт на ДОСЛОВНЫХ образцах пакетов из перехватов (Bambu P1S и X1C) и на
двоичной раскладке FlashForge из работающих сторонних реализаций. Приём проверяется настоящими
сокетами на петле 127.0.0.1 — своей же датаграммой, не сетью фермы.

ОТДЕЛЬНО ПРОВЕРЯЕТСЯ ЗАПРЕТ ВЛАДЕЛЬЦА (пункт карты R-092): перебора адресов подсети и
сканирования портов в модуле нет, а всё, что уходит наружу, перечислено в одной таблице.

server.py здесь не импортируется.

Запуск:  python tools/test_printer_discovery.py
"""
import io
import os
import socket
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import printer_discovery as pd   # noqa: E402

SENTINEL = "PRINTER_DISCOVERY_SENTINEL_2_980"
PASS = FAIL = 0
SRC = io.open(os.path.join(ROOT, "app", "printer_discovery.py"), encoding="utf-8").read()


def check(name, ok, extra=None):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("   [%r]" % (extra,)) if extra is not None else ""))


# ════════════════════════════════════════════════════════════════════════════
print("--- 1. Bambu Lab: дословный перехват с живого принтера ---")
#  Снимок с P1S (прошивка 01.07.00.00). Заголовок HOST в пакете называет порт 1900,
#  хотя пакет пришёл на 2021 — на HOST мы намеренно не смотрим.
P1S = (
    "NOTIFY * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    "Server: UPnP/1.0\r\n"
    "Location: 192.168.1.105\r\n"
    "NT: urn:bambulab-com:device:3dprinter:1\r\n"
    "USN: 01P00A123456789\r\n"
    "Cache-Control: max-age=1800\r\n"
    "DevModel.bambu.com: C12\r\n"
    "DevName.bambu.com: Bambu Lab P1S\r\n"
    "DevSignal.bambu.com: -30\r\n"
    "DevConnect.bambu.com: lan\r\n"
    "DevBind.bambu.com: free\r\n"
    "Devseclink.bambu.com: secure\r\n"
    "DevVersion.bambu.com: 01.07.00.00\r\n"
    "DevCap.bambu.com: 1\r\n"
    "\r\n"
).encode()
d = pd.parse_bambu_notify(P1S, "192.168.1.105")
check("1. объявление P1S разобрано", isinstance(d, dict), d)
check("2. адрес взят из Location как есть, без разбора ссылки", d.get("ip") == "192.168.1.105", d)
check("3. серийный номер = USN", d.get("serial") == "01P00A123456789", d)
check("4. код модели C12 переведён в «P1S»", d.get("model") == "P1S", d)
check("5. имя принтера прочитано", d.get("name") == "Bambu Lab P1S", d)
check("6. версия прошивки прочитана", d.get("firmware") == "01.07.00.00", d)
check("7. режим подключения виден (локальный или облако)", d.get("connect_mode") == "lan", d)
check("8. семейство и порт проставлены", d.get("family") == "bambu" and d.get("port") == 8883, d)

#  Снимок с X1C: другой набор заголовков, длинный псевдоним модели у старых прошивок.
X1C = (
    "NOTIFY * HTTP/1.1\r\n"
    "Host: 239.255.255.250:1990\r\n"
    "Server: UPnP/1.0\r\n"
    "Location: 10.0.0.51\r\n"
    "NT: urn:bambulab-com:device:3dprinter:1\r\n"
    "NTS: ssdp:alive\r\n"
    "USN: 00M00A000000001\r\n"
    "DevModel.bambu.com: BL-P001\r\n"
    "DevName.bambu.com: 3DP-00M-001\r\n"
    "DevSignal.bambu.com: -62\r\n"
    "DevConnect.bambu.com: lan\r\n"
    "DevBind.bambu.com: free\r\n"
    "DevInf.bambu.com: wlan0\r\n"
    "\r\n"
).encode()
d2 = pd.parse_bambu_notify(X1C, "10.0.0.51")
check("9. BL-P001 переведён в «X1 Carbon»", (d2 or {}).get("model") == "X1 Carbon", d2)
check("10. отсутствие версии прошивки не ломает разбор", (d2 or {}).get("firmware") == "", d2)
_alias = pd.parse_bambu_notify(X1C.replace(b"BL-P001", b"3DPrinter-X1-Carbon"), "10.0.0.51")
check("11. длинный псевдоним старых прошивок тоже опознан",
      (_alias or {}).get("model") == "X1 Carbon", _alias)

_bye = pd.parse_bambu_notify(X1C.replace(b"ssdp:alive", b"ssdp:byebye"), "10.0.0.51")
check("12. прощальное объявление помечено как «уже не в сети»", (_bye or {}).get("alive") is False, _bye)
check("13. чужая датаграмма на том же порту принтером не считается",
      pd.parse_bambu_notify(b"NOTIFY * HTTP/1.1\r\nNT: urn:schemas-upnp-org:device:Basic:1\r\n\r\n", "1.2.3.4") is None)
check("14. мусор не роняет разбор", pd.parse_bambu_notify(b"\x00\x01\x02", "1.2.3.4") is None)
check("15. регистр заголовков не важен",
      (pd.parse_bambu_notify(P1S.replace(b"DevModel.bambu.com", b"DEVMODEL.BAMBU.COM"), "192.168.1.105") or {}).get("model") == "P1S")

# ════════════════════════════════════════════════════════════════════════════
print("--- 2. FlashForge: двоичная визитная карточка ---")


def ff_packet(name="Adventurer 5M Pro", serial="SNFF0001", pid=0x0024, size=276,
              vid=pd.FF_VID, port_cmd=8899, port_http=8898, state=0):
    b = bytearray(size)
    nm = name.encode("utf-8")[:127]
    b[0:len(nm)] = nm
    b[0x84:0x86] = struct.pack(">H", port_cmd)
    b[0x86:0x88] = struct.pack(">H", vid)
    b[0x88:0x8A] = struct.pack(">H", pid)
    b[0x8A:0x8C] = struct.pack(">H", state)
    b[0x8C:0x8E] = struct.pack(">H", 0x5A02)
    b[0x8E:0x90] = struct.pack(">H", port_http)
    if size >= 276:
        sn = serial.encode("utf-8")[:127]
        b[0x92:0x92 + len(sn)] = sn
    return bytes(b)


f = pd.parse_flashforge_packet(ff_packet(), "10.0.0.60")
check("16. новый формат (276 байт) разобран", isinstance(f, dict), f)
check("17. имя принтера прочитано до нулевого байта", f.get("name") == "Adventurer 5M Pro", f)
check("18. серийный номер прочитан", f.get("serial") == "SNFF0001", f)
check("19. PID 0x0024 переведён в модель", f.get("model") == "Adventurer 5M Pro", f)
check("20. порт команд прочитан из пакета", f.get("port_gcode") == 8899, f)
check("21. адрес взят у отправителя (в пакете его нет)", f.get("ip") == "10.0.0.60", f)

f140 = pd.parse_flashforge_packet(ff_packet(size=140, pid=0x001D), "10.0.0.61")
check("22. старый формат (140 байт) разобран", isinstance(f140, dict), f140)
check("23. у старого формата серийного номера нет — и не выдумывается",
      f140.get("serial") == "", f140)
check("24. модель старого принтера опознана по PID", f140.get("model") == "Adventurer 3 Pro 2", f140)
check("25. чужой производитель (VID не тот) отвергнут",
      pd.parse_flashforge_packet(ff_packet(vid=0x1234), "10.0.0.62") is None)
check("26. короткий пакет отвергнут", pd.parse_flashforge_packet(b"\x00" * 100, "10.0.0.63") is None)
check("27. неизвестный PID не выдумывает модель",
      (pd.parse_flashforge_packet(ff_packet(pid=0x7777), "10.0.0.64") or {}).get("model") == "")

# ════════════════════════════════════════════════════════════════════════════
print("--- 3. mDNS: разбор своими руками, без сторонних библиотек ---")
q = pd.build_mdns_ptr_query(("_moonraker._tcp.local", "_octoprint._tcp.local"))
_id, _fl, qd, an, _ns, _ar = struct.unpack(">HHHHHH", q[:12])
check("28. в запросе ровно два вопроса", qd == 2 and an == 0, (qd, an))
check("29. тип запроса PTR (12), класс IN (1)", q[-4:] == struct.pack(">HH", 12, 1), q[-4:])
_nm, _off = pd.read_dns_name(q, 12)
check("30. имя службы кодируется и читается обратно", _nm == "_moonraker._tcp.local", _nm)


def mdns_reply():
    """Ответ mDNS со сжатием имён: PTR + SRV + TXT + A, как это делает настоящий отвечающий."""
    base = b"\x0a_moonraker\x04_tcp\x05local\x00"          # _moonraker._tcp.local  (смещение 12)
    inst = b"\x06voron1\xc0\x0c"                            # voron1.<указатель на 12>
    host = b"\x06voron1\x05local\x00"
    msg = struct.pack(">HHHHHH", 0, 0x8400, 0, 4, 0, 0)
    msg += base + struct.pack(">HHIH", 12, 1, 120, len(inst)) + inst          # PTR
    off_inst = len(msg) - len(inst)
    srv = struct.pack(">HHH", 0, 0, 7125) + host
    msg += struct.pack(">H", 0xC000 | off_inst) + struct.pack(">HHIH", 33, 1, 120, len(srv)) + srv
    _t = b"uuid=abc-123-def-4567"
    txt = bytes([len(_t)]) + _t
    msg += struct.pack(">H", 0xC000 | off_inst) + struct.pack(">HHIH", 16, 1, 120, len(txt)) + txt
    a_off = len(msg)
    msg += host + struct.pack(">HHIH", 1, 1, 120, 4) + socket.inet_aton("10.0.0.70")
    return msg, a_off


msg, _ = mdns_reply()
parsed = pd.parse_mdns_message(msg)
check("31. запись PTR прочитана", any("_moonraker" in a for a, _b in parsed["ptr"]), parsed["ptr"])
check("32. сжатие имён (указатель) развёрнуто",
      any(k.startswith("voron1._moonraker._tcp.local") for k in parsed["srv"]), list(parsed["srv"]))
check("33. порт службы прочитан",
      any(v.get("port") == 7125 for v in parsed["srv"].values()), parsed["srv"])
check("34. адрес из записи A прочитан", "10.0.0.70" in parsed["a"].values(), parsed["a"])
check("35. TXT разобран в пары ключ-значение",
      any(v.get("uuid") == "abc-123-def-4567" for v in parsed["txt"].values()), parsed["txt"])

devs = pd.devices_from_mdns(parsed, "10.0.0.70")
check("36. из объявления получился принтер Klipper",
      len(devs) == 1 and devs[0]["family"] == "klipper" and devs[0]["ip"] == "10.0.0.70", devs)
check("37. порт взят из записи службы, а не угадан", devs[0]["port"] == 7125, devs)
check("38. вечный признак uuid подхвачен", devs[0]["uuid"] == "abc-123-def-4567", devs)

#  Пакет с петлёй указателей — такой может прислать кто угодно в сети.
loop = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0) + struct.pack(">H", 0xC00C)
try:
    pd.read_dns_name(loop, 12)
    _loop_ok = False
except ValueError:
    _loop_ok = True
check("39. петля указателей отвергается, а не вешает разбор", _loop_ok)
check("40. битый пакет mDNS не роняет разбор",
      pd.parse_mdns_message(b"\x00\x01\x02\x03") == {"ptr": [], "srv": {}, "txt": {}, "a": {}})

# ════════════════════════════════════════════════════════════════════════════
print("--- 4. Один принтер — одна строка ---")
merged = pd.merge_devices([
    dict(pd.parse_bambu_notify(P1S, "192.168.1.105")),          # порт 2021
    dict(pd.parse_bambu_notify(P1S, "192.168.1.105")),          # тот же, порт 1990
    dict(pd.parse_flashforge_packet(ff_packet(), "10.0.0.60")),  # FlashForge, порт 19000
    dict(pd.parse_flashforge_packet(ff_packet(), "10.0.0.60")),  # он же, порт 48899
])
check("41. повторные объявления слиты: два принтера, а не четыре", len(merged) == 2, merged)
check("42. у каждой строки есть вечный ключ",
      all(m.get("key") and m["key"].startswith("serial:") for m in merged), merged)

diff_ip = pd.merge_devices([
    dict(pd.parse_bambu_notify(P1S, "192.168.1.105")),
    dict(pd.parse_bambu_notify(X1C, "10.0.0.51")),
])
check("43. разные принтеры не слипаются", len(diff_ip) == 2, diff_ip)

#  Тот же принтер по другому адресу — сливается по серийному номеру, а не по адресу.
moved_raw = dict(pd.parse_bambu_notify(P1S.replace(b"192.168.1.105", b"192.168.1.200"), "192.168.1.200"))
same = pd.merge_devices([dict(pd.parse_bambu_notify(P1S, "192.168.1.105")), moved_raw])
check("44. сменивший адрес принтер — одна строка, а не две", len(same) == 1, same)

# ════════════════════════════════════════════════════════════════════════════
print("--- 5. Сверка с уже заведёнными принтерами ---")
PRINTERS = [
    {"id": "p1", "name": "P1S у окна", "type": "bambu", "ip": "192.168.1.105", "serial": "01P00A123456789"},
    {"id": "p2", "name": "Второй", "type": "klipper", "ip": "10.0.0.70", "serial": ""},
]
st = {d["key"]: d["state"] for d in pd.classify(pd.merge_devices([
    dict(pd.parse_bambu_notify(P1S, "192.168.1.105"))]), PRINTERS)}
check("45. заведённый принтер по тому же адресу — «уже заведён»",
      list(st.values()) == ["known"], st)

st2 = pd.classify(pd.merge_devices([moved_raw]), PRINTERS)
check("46. тот же серийник по новому адресу — «сменил адрес»",
      st2[0]["state"] == "moved" and st2[0]["old_ip"] == "192.168.1.105", st2)

st3 = pd.classify(pd.merge_devices([dict(pd.parse_bambu_notify(X1C, "10.0.0.51"))]), PRINTERS)
check("47. незнакомый принтер — «новый»", st3[0]["state"] == "new", st3)

#  DHCP отдал адрес заведённого принтера другому устройству — молча менять ничего нельзя.
alien = dict(pd.parse_bambu_notify(X1C.replace(b"10.0.0.51", b"192.168.1.105"), "192.168.1.105"))
st4 = pd.classify(pd.merge_devices([alien]), PRINTERS)
check("48. чужой принтер на занятом адресе — «разобраться», а не тихая подмена",
      st4[0]["state"] == "conflict", st4)

unsup = pd.classify([{"ip": "10.0.0.90", "family": "elegoo", "adapter": "", "serial": "X"}], PRINTERS)
check("49. марка без адаптера помечается «не поддерживается»",
      unsup[0]["state"] == "unsupported", unsup)

# ════════════════════════════════════════════════════════════════════════════
print("--- 6. Модель подставляется только при точном совпадении с обложкой ---")
COVERS = ("P1S", "X1 Carbon", "Adventurer 5M Pro", "K2 Plus")
check("50. код модели переводится в имя обложки",
      pd.canonical_model("bambu", "C12", "", COVERS)[0] == "P1S")
check("51. имени нет среди обложек — модель не подставляется",
      pd.canonical_model("bambu", "N9", "", COVERS)[0] == "")
check("52. но сырое обозначение сохраняется, чтобы показать владельцу",
      pd.canonical_model("bambu", "N9", "", COVERS)[1] == "A2L")
check("53. FlashForge: PID переводится в имя обложки",
      pd.canonical_model("flashforge", "0x0024", "", COVERS)[0] == "Adventurer 5M Pro")
check("54. неподтверждённые коды плат Creality в модель НЕ переводятся",
      pd.canonical_model("klipper", "F008", "", COVERS)[0] == "")
check("55. таблицы кодов плат Creality в модуле нет вовсе",
      "F001" not in SRC and "CREALITY_BOARD" not in SRC)

# ════════════════════════════════════════════════════════════════════════════
print("--- 7. Вечный признак и то, что уходит в интерфейс ---")
check("56. серийный номер важнее MAC и uuid",
      pd.identity_key({"serial": "S1", "mac": "AABB", "uuid": "u"}) == ("serial", "S1"))
check("57. без серийника берётся MAC", pd.identity_key({"mac": "AABBCC"}) == ("mac", "AABBCC"))
check("58. адрес вечным признаком не считается никогда",
      pd.identity_key({"ip": "10.0.0.1"}) is None)
_red = pd.redact({"ip": "10.0.0.1", "serial": "S", "secret": "нельзя", "token": "нельзя"})
check("59. наружу уходят только разрешённые поля",
      "secret" not in _red and "token" not in _red and _red.get("ip") == "10.0.0.1", _red)
check("60. управляющие символы из имени вырезаются при разборе",
      pd.parse_bambu_notify(P1S.replace(b"Bambu Lab P1S", b"Bad\x07Name"), "192.168.1.105")["name"] == "BadName")

# ════════════════════════════════════════════════════════════════════════════
print("--- 8. Запрет владельца: перебора сети нет ---")
check("61. в модуле нет перебора адресов подсети",
      "range(1, 255)" not in SRC and "range(1,255)" not in SRC and "for host in" not in SRC)
check("62. нет сканирования портов (connect_ex по списку портов)",
      "connect_ex" not in SRC)
check("63. всё отправляемое перечислено в одной таблице", "ALLOWED_ASK" in SRC)
#  16.10.2026 (R-092): добавлен вопрос Bambu «кто здесь» на порт 2021 — группа и broadcast, тот же
#  литерал, что у Bambuddy, и пустая датаграмма FlashForge на broadcast портов 19000 и 8899, как у
#  ff-5mp-api-py. Число записей поднято сознательно: 5 -> 9.
check("64. в таблице ровно девять записей и ни одной вендорской команды",
      len(pd.ALLOWED_ASK) == 9
      and all(p in (None, b"", pd.SSDP_MSEARCH, getattr(pd, "BAMBU_MSEARCH", b"-"))
              for _n, _a, _pt, p in pd.ALLOWED_ASK), pd.ALLOWED_ASK)
_names = {n for n, _a, _p, _b in pd.ALLOWED_ASK}
check("65. запросов, что-то запускающих на принтере, нет",
      not [n for n in _names if "print" in n or "start" in n or "cmd" in n], _names)
check("66. команды печати и G-code в модуле не встречаются",
      "start_print" not in SRC and "M104" not in SRC and "gcode_line" not in SRC)
check("67. по умолчанию SDCP (Elegoo) и Snapmaker не опрашиваются",
      not [1 for _n, _a, _p, _b in pd.ALLOWED_ASK if _p in (3000, 20054)]
      and 3000 not in pd.LISTEN_PORTS and 20054 not in pd.LISTEN_PORTS
      and not [1 for _n, _a, _p, _b in pd.ALLOWED_ASK if _b and b"M99999" in _b])
check("68. модуль не импортирует server.py", "import server" not in SRC)
check("69. новых зависимостей нет — только стандартная библиотека",
      "import zeroconf" not in SRC and "from zeroconf" not in SRC
      and "import scapy" not in SRC and "import requests" not in SRC)
check("70. порт у слушателя не отбирается у слайсера (SO_EXCLUSIVEADDRUSE не ставится)",
      "setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE" not in SRC
      and "socket.SO_REUSEADDR, 1)" in SRC)

# ════════════════════════════════════════════════════════════════════════════
print("--- 9. Приём настоящими сокетами (петля 127.0.0.1) ---")
_l = pd.UdpListener(19000)
_opened = _l.open()
check("71. слушающий сокет поднялся", _opened, _l.error)
if _opened:
    _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _s.sendto(ff_packet(name="Петлевой", serial="LOOP1"), ("127.0.0.1", 19000))
        time.sleep(0.4)
        got = _l.read()
        check("72. датаграмма принята", len(got) == 1, len(got))
        if got:
            parsed_ff = pd.parse_flashforge_packet(got[0][0], got[0][1][0])
            check("73. принятый пакет разобран как принтер FlashForge",
                  (parsed_ff or {}).get("serial") == "LOOP1", parsed_ff)
            check("74. имя с кириллицей прочитано верно",
                  (parsed_ff or {}).get("name") == "Петлевой", parsed_ff)
    finally:
        _s.close()
        _l.close()
check("75. повторное закрытие слушателя не падает", _l.close() is None)

_ifaces = pd.iter_local_ipv4()
check("76. локальные сетевые карты перечислены", isinstance(_ifaces, list) and len(_ifaces) >= 1, _ifaces)
check("77. петлевой адрес в список не попадает (если есть настоящая карта)",
      all(not i.startswith("127.") for i in _ifaces) or _ifaces == ["127.0.0.1"], _ifaces)

# ════════════════════════════════════════════════════════════════════════════
#  08.10.2026 (обход фермы, R-092: «найдено 0», хотя в сети 5 принтеров). Ответ на запрос
#  «представься» приходит на порт, с которого запрос ушёл. Прежде этот сокет закрывался сразу
#  после отправки — ответы терялись. Проверка исполнением на петле: подставной «принтер»
#  FlashForge отвечает визитной карточкой отправителю. Таблица запросов на время проверки
#  подменяется адресом петли — в сеть фермы ничего не уходит.
print("--- 10. Ответ на запрос доходит до поиска (петля 127.0.0.1) ---")
import threading  # noqa: E402


def _ask_reply_run(keep):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(6.0)
    port = srv.getsockname()[1]
    asked = []

    def _printer():
        try:
            data, addr = srv.recvfrom(2048)
            asked.append(addr)
            srv.sendto(ff_packet(name="Ответчик", serial="REPLY1"), addr)
        except Exception:
            pass

    th = threading.Thread(target=_printer, daemon=True)
    th.start()
    old_ask, old_if, old_keep = pd.ALLOWED_ASK, pd.iter_local_ipv4, pd.DiscoverySession.KEEP_ASK_SOCKETS
    pd.ALLOWED_ASK = (("flashforge-19000", "127.0.0.1", port, b""),)
    pd.iter_local_ipv4 = lambda: ["127.0.0.1"]
    pd.DiscoverySession.KEEP_ASK_SOCKETS = keep
    sess = pd.DiscoverySession(log=None)
    try:
        sess.start(seconds=10, ask=True)
        t_end = time.monotonic() + 4.0
        while time.monotonic() < t_end:
            if any((d or {}).get("serial") == "REPLY1" for d in list(sess.raw)):
                break
            time.sleep(0.1)
        found = any((d or {}).get("serial") == "REPLY1" for d in list(sess.raw))
        snap = sess.snapshot()
    finally:
        sess.stop()
        pd.ALLOWED_ASK, pd.iter_local_ipv4 = old_ask, old_if
        pd.DiscoverySession.KEEP_ASK_SOCKETS = old_keep
        th.join(1.0)
        srv.close()
    return found, asked, snap


_f1, _a1, _s1 = _ask_reply_run(True)
check("78. запрос дошёл до «принтера» на петле", len(_a1) == 1, _a1)
check("79. ответ на запрос принят: принтер найден, ответ посчитан в снимке",
      _f1 and (_s1.get("received") or {}).get("ответ flashforge-19000", 0) >= 1, _s1.get("received"))
_f0, _a0, _s0 = _ask_reply_run(False)
check("80. непустота: если сокет запроса закрыть сразу (как до 08.10.2026), тот же ответ теряется",
      len(_a0) == 1 and not _f0, (_a0, _s0.get("received")))
check("81. таблица запросов после проверки прежняя (девять записей)", len(pd.ALLOWED_ASK) == 9, pd.ALLOWED_ASK)
check("82. итог поиска пишется в журнал фермы одной строкой",
      "[DISCOVERY] поиск окончен: найдено %d" in SRC and "self.log.info(" in SRC)

# ════════════════════════════════════════════════════════════════════════════
#  16.10.2026 (R-092): вопрос Bambu «кто здесь» на порт 2021. Источник литерала — Bambuddy
#  (backend/app/services/discovery.py): M-SEARCH с ST urn:bambulab-com:device:3dprinter:1, повтор
#  каждые 3 с. Ответ принтера — «HTTP/1.1 200 OK» с теми же заголовками DevModel/DevName, что в
#  объявлении (формат — gist fritzw, имитация ответа принтера для Bambu Studio).
print("--- 11. Bambu: вопрос «кто здесь» на 2021 и ответ на него ---")
BM = getattr(pd, "BAMBU_MSEARCH", None)
check("83. литерал вопроса Bambu — дословно как у Bambuddy",
      BM == (b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:2021\r\nMAN: "ssdp:discover"\r\n'
             b'MX: 3\r\nST: urn:bambulab-com:device:3dprinter:1\r\n\r\n'), BM)
_asks = {n: (a, p, b) for n, a, p, b in pd.ALLOWED_ASK}
check("84. вопрос уходит в группу 239.255.255.250:2021 и на broadcast 255.255.255.255:2021",
      _asks.get("bambu-msearch-2021", ())[:2] == ("239.255.255.250", 2021)
      and _asks.get("bambu-msearch-bcast", ())[:2] == ("255.255.255.255", 2021)
      and BM is not None and _asks["bambu-msearch-2021"][2] is BM and _asks["bambu-msearch-bcast"][2] is BM, _asks)
BAMBU_REPLY = (
    "HTTP/1.1 200 OK\r\n"
    "Server: Buildroot/2018.02-rc3 UPnP/1.0 ssdpd/1.8\r\n"
    "Location: 192.168.1.106\r\n"
    "ST: urn:bambulab-com:device:3dprinter:1\r\n"
    "EXT:\r\n"
    "USN: 01P00A000000002\r\n"
    "Cache-Control: max-age=1800\r\n"
    "DevModel.bambu.com: C12\r\n"
    "DevName.bambu.com: P1S ответ\r\n"
    "DevConnect.bambu.com: lan\r\n"
    "DevBind.bambu.com: free\r\n"
    "\r\n"
).encode()
_br = pd.parse_bambu_notify(BAMBU_REPLY, "192.168.1.106")
check("85. ответ принтера «200 OK» разобран: адрес, серийник, модель",
      (_br or {}).get("ip") == "192.168.1.106" and (_br or {}).get("serial") == "01P00A000000002"
      and (_br or {}).get("model") == "P1S", _br)


def _bambu_ask_run(repeat_s):
    """Подставной «принтер Bambu» на петле: принимает вопросы и отвечает на первый."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv.settimeout(0.3)
    port = srv.getsockname()[1]
    got, stop = [], threading.Event()

    def _printer():
        while not stop.is_set():
            try:
                data, addr = srv.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception:
                break
            got.append((data, addr))
            if len(got) == 1:
                try:
                    srv.sendto(BAMBU_REPLY.replace(b"192.168.1.106", b"127.0.0.1"), addr)
                except Exception:
                    pass

    th = threading.Thread(target=_printer, daemon=True)
    th.start()
    old = (pd.ALLOWED_ASK, pd.iter_local_ipv4, pd.DiscoverySession.KEEP_ASK_SOCKETS,
           getattr(pd.DiscoverySession, "ASK_REPEAT_S", None))
    pd.ALLOWED_ASK = (("bambu-msearch-2021", "127.0.0.1", port, BM or b"-"),)
    pd.iter_local_ipv4 = lambda: ["127.0.0.1"]
    pd.DiscoverySession.KEEP_ASK_SOCKETS = True
    pd.DiscoverySession.ASK_REPEAT_S = repeat_s
    sess = pd.DiscoverySession(log=None)
    try:
        sess.start(seconds=10, ask=True)
        time.sleep(2.6)
        snap = sess.snapshot()
    finally:
        sess.stop()
        pd.ALLOWED_ASK, pd.iter_local_ipv4, pd.DiscoverySession.KEEP_ASK_SOCKETS = old[0], old[1], old[2]
        if old[3] is None:
            del pd.DiscoverySession.ASK_REPEAT_S
        else:
            pd.DiscoverySession.ASK_REPEAT_S = old[3]
        stop.set()
        th.join(1.0)
        srv.close()
    return got, snap


_got, _snap = _bambu_ask_run(0.3)
#  16.10.2026: повторов ровно два (решение по пункту) — за 2,6 с при паузе 0,3 с без ограничения
#  ушло бы восемь вопросов, а должно уйти ровно три: первый и два повтора.
check("86. вопрос повторяется (UDP теряет пакеты), но ровно дважды: за 2,6 с при паузе 0,3 с — три вопроса",
      len(_got) == 1 + pd.ASK_REPEATS == 3, len(_got))
check("87. каждый повтор — тот же литерал из таблицы, байт в байт",
      bool(_got) and all(d == BM for d, _a in _got), [d[:60] for d, _a in _got][:3])
check("88. повтор идёт тем же сокетом (тот же порт отправителя), новых сокетов на каждый повтор нет",
      len({a for _d, a in _got}) == 1, {a for _d, a in _got})
_devs = [d for d in (_snap.get("devices") or []) if d.get("serial") == "01P00A000000002"]
check("89. ответ на вопрос принят: принтер Bambu найден, ответ посчитан",
      len(_devs) == 1 and (_snap.get("received") or {}).get("ответ bambu-msearch-2021", 0) >= 1,
      (_snap.get("devices"), _snap.get("received")))
check("90. таблица запросов после проверки прежняя", len(pd.ALLOWED_ASK) == 9)

#  16.10.2026: свой же вопрос «кто здесь» — не принтер. Группа 239.255.255.250:2021 возвращает
#  его и на наш слушатель порта 2021 (тот вступает в ту же группу), и вопрос Bambu Studio с
#  соседнего компьютера приходит туда же. В вопросе тот же ST urn:bambulab-com…, и до правки
#  он показывался «новым принтером Bambu» по адресу компьютера.
check("90а. свой вопрос M-SEARCH принтером Bambu не считается",
      BM is not None and pd.parse_bambu_notify(BM, "192.168.1.50") is None, pd.parse_bambu_notify(BM or b"", "192.168.1.50"))
_q_mr = (b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
         b"ST: urn:arksine.github.io:device:Moonraker:1\r\n\r\n")
check("90б. чужой вопрос о Moonraker принтером Klipper не считается",
      getattr(pd, "parse_moonraker_ssdp", None) is not None and pd.parse_moonraker_ssdp(_q_mr, "192.168.1.51") is None)
_s_echo = pd.DiscoverySession(log=None)
_s_echo._absorb(2021, BM or b"", ("192.168.1.50", 50123))
_s_echo._absorb(2021, BM or b"", ("192.168.1.52", 50999))     # вопрос слайсера с соседнего компьютера
_s_echo._absorb(1900, pd.SSDP_MSEARCH, ("192.168.1.50", 50124))
_s_echo._absorb(1900, _q_mr, ("192.168.1.51", 50125))
_echo_devs = _s_echo.snapshot().get("devices")
check("90в. поиск, услышавший вопросы (свой и слайсера), не показывает ни одного «принтера»",
      _echo_devs == [], _echo_devs)
check("90г. настоящее объявление и ответ Bambu по-прежнему принимаются",
      (pd.parse_bambu_notify(P1S, "192.168.1.105") or {}).get("serial") == "01P00A123456789"
      and (pd.parse_bambu_notify(BAMBU_REPLY, "192.168.1.106") or {}).get("serial") == "01P00A000000002")
_ffb = {n: (a, p, b) for n, a, p, b in pd.ALLOWED_ASK if n.startswith("flashforge")}
check("90д. FlashForge спрашивается и на broadcast 255.255.255.255 портов 19000 и 8899 — пустой датаграммой",
      _ffb.get("flashforge-19000-bcast") == ("255.255.255.255", 19000, b"")
      and _ffb.get("flashforge-8899-bcast") == ("255.255.255.255", 8899, b"")
      and all(b == b"" for _a, _p, b in _ffb.values()), _ffb)

# ════════════════════════════════════════════════════════════════════════════
#  Формат Moonraker — исходник components/zeroconf.py (Arksine/moonraker): SERVER «Moonraker
#  SSDP/UPNP Server», USN «uuid:<instance_uuid>::…», LOCATION «…/server/zeroconf/ssdp». SSDP
#  включается разделом [zeroconf] в moonraker.conf (по умолчанию выключен).
print("--- 12. Moonraker по SSDP ---")
MR_REPLY = (
    "HTTP/1.1 200 OK\r\n"
    "CACHE-CONTROL: max-age=1800\r\n"
    "EXT:\r\n"
    "LOCATION: http://10.0.0.80:7125/server/zeroconf/ssdp\r\n"
    "SERVER: Moonraker SSDP/UPNP Server\r\n"
    "ST: upnp:rootdevice\r\n"
    "USN: uuid:e3a2f6b8-0000-4000-8000-0123456789ab::upnp:rootdevice\r\n"
    "\r\n"
).encode()
MR_NOTIFY = (
    "NOTIFY * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    "CACHE-CONTROL: max-age=1800\r\n"
    "LOCATION: http://10.0.0.81:7125/server/zeroconf/ssdp\r\n"
    "NT: urn:arksine.github.io:device:Moonraker:1\r\n"
    "NTS: ssdp:alive\r\n"
    "SERVER: Moonraker SSDP/UPNP Server\r\n"
    "USN: uuid:0b5d7c1e-1111-4222-8333-444455556666::urn:arksine.github.io:device:Moonraker:1\r\n"
    "\r\n"
).encode()
ROUTER = (
    "HTTP/1.1 200 OK\r\nLOCATION: http://192.168.1.1:1900/rootDesc.xml\r\n"
    "SERVER: Linux/5.4 UPnP/1.1 MiniUPnPd/2.2\r\nST: upnp:rootdevice\r\n"
    "USN: uuid:abcdef::upnp:rootdevice\r\n\r\n"
).encode()
_pm = getattr(pd, "parse_moonraker_ssdp", None)
_m1 = _pm(MR_REPLY, "10.0.0.80") if _pm else None
check("91. ответ Moonraker разобран: Klipper, адрес и порт из LOCATION, uuid из USN",
      (_m1 or {}).get("family") == "klipper" and (_m1 or {}).get("adapter") == "klipper"
      and (_m1 or {}).get("ip") == "10.0.0.80" and (_m1 or {}).get("port") == 7125
      and (_m1 or {}).get("uuid") == "e3a2f6b8-0000-4000-8000-0123456789ab", _m1)
_m2 = _pm(MR_NOTIFY, "10.0.0.81") if _pm else None
check("92. объявление Moonraker (NT urn:arksine…) разобрано, uuid тот же, что в mDNS",
      (_m2 or {}).get("uuid") == "0b5d7c1e-1111-4222-8333-444455556666" and (_m2 or {}).get("ip") == "10.0.0.81", _m2)
check("93. чужой rootdevice (роутер) и объявление Bambu принтером Klipper не считаются",
      _pm is not None and _pm(ROUTER, "192.168.1.1") is None and _pm(P1S, "192.168.1.105") is None)
_s12 = pd.DiscoverySession(log=None)
_s12._absorb(1900, MR_NOTIFY, ("10.0.0.81", 1900))
_s12._absorb_reply("ssdp-msearch", MR_REPLY, ("10.0.0.80", 1900))
_got12 = sorted((d.get("ip"), d.get("uuid")) for d in _s12.raw)
check("94. поиск принимает Moonraker и с порта 1900, и ответом на свой M-SEARCH (раньше отбрасывал)",
      _got12 == [("10.0.0.80", "e3a2f6b8-0000-4000-8000-0123456789ab"),
                 ("10.0.0.81", "0b5d7c1e-1111-4222-8333-444455556666")], _got12)

# ════════════════════════════════════════════════════════════════════════════
#  Creality: заводская прошивка K1C объявляет _Creality-<SN>._udp (helixscreen issue 1447);
#  имена _http._tcp/_workstation._tcp с creality/k1/k2 — как в ha_creality_ws.
print("--- 13. mDNS: Creality и _workstation ---")


def _rr(name, rtype, rdata):
    return pd._encode_dns_name(name) + struct.pack(">HHIH", rtype, 1, 120, len(rdata)) + rdata


def _msg(*rrs):
    return struct.pack(">HHHHHH", 0, 0x8400, 0, len(rrs), 0, 0) + b"".join(rrs)


_enum = _msg(_rr("_services._dns-sd._udp.local", 12, pd._encode_dns_name("_Creality-F012A7C3B9._udp.local")))
_ce = pd.devices_from_mdns(pd.parse_mdns_message(_enum), "10.0.0.90")
check("95. служба _Creality-<серийник>._udp: серийный номер взят, подключение — служба Creality :9999",
      len(_ce) == 1 and _ce[0].get("serial") == "F012A7C3B9" and _ce[0].get("adapter") == "creality"
      and _ce[0].get("port") == 9999 and _ce[0].get("ip") == "10.0.0.90" and _ce[0].get("family") == "klipper", _ce)
_ws_inst = "K1C-2F4A [aa:bb:cc:dd:ee:ff]._workstation._tcp.local"
_ws = _msg(_rr("_workstation._tcp.local", 12, pd._encode_dns_name(_ws_inst)),
           _rr(_ws_inst, 33, struct.pack(">HHH", 0, 0, 9) + pd._encode_dns_name("K1C-2F4A.local")),
           _rr("K1C-2F4A.local", 1, socket.inet_aton("169.254.10.20")),
           _rr("K1C-2F4A.local", 1, socket.inet_aton("10.0.0.91")))
_cw = pd.devices_from_mdns(pd.parse_mdns_message(_ws), "10.0.0.91")
check("96. _workstation с K1 в имени: принтер Creality, MAC из [..] — вечный признак, имя без MAC",
      len(_cw) == 1 and _cw[0].get("mac") == "AABBCCDDEEFF" and _cw[0].get("name") == "K1C-2F4A"
      and _cw[0].get("vendor_hint") == "creality", _cw)
check("97. из двух адресов взят настоящий, а не самоназначенный 169.254.x", _cw and _cw[0].get("ip") == "10.0.0.91", _cw)
_a2 = pd.parse_mdns_message(_msg(_rr("h.local", 1, socket.inet_aton("10.0.0.92")),
                                 _rr("h.local", 1, socket.inet_aton("169.254.1.2"))))
check("98. порядок записей не важен: 169.254.x не затирает настоящий адрес", _a2["a"].get("h.local") == "10.0.0.92", _a2)
_desk = _msg(_rr("_workstation._tcp.local", 12, pd._encode_dns_name("Desk1-PC [11:22:33:44:55:66]._workstation._tcp.local")))
check("99. обычный компьютер (_workstation без creality/k1/k2 в начале слова) принтером не считается",
      pd.devices_from_mdns(pd.parse_mdns_message(_desk), "10.0.0.93") == [])
_http = _msg(_rr("_http._tcp.local", 12, pd._encode_dns_name("creality-k2plus._http._tcp.local")))
_ch = pd.devices_from_mdns(pd.parse_mdns_message(_http), "10.0.0.94")
check("100. _http._tcp с creality в имени — кандидат Creality; порт не угадывается (проба формы решит)",
      len(_ch) == 1 and _ch[0].get("vendor_hint") == "creality" and not _ch[0].get("port"), _ch)
check("101. в запрос mDNS добавлена служба _workstation._tcp",
      "_workstation._tcp.local" in pd.MDNS_ASK_NAMES and b"\x0c_workstation" in pd._mdns_query_bytes())

# ════════════════════════════════════════════════════════════════════════════
#  16.10.2026 (R-092): ложное «Адрес занят» у уже заведённых Klipper, Creality и FlashForge.
print("--- 14. Сверка: принтер по своему адресу — «уже заведён», а не «адрес занят» ---")
PR2 = [
    {"id": "k1", "type": "klipper", "ip": "10.0.0.70", "serial": ""},
    {"id": "cr1", "type": "creality", "ip": "10.0.0.90", "serial": ""},
    {"id": "ff1", "type": "flashforge", "ip": "10.0.0.60", "serial": ""},
    {"id": "ff2", "type": "flashforge", "ip": "10.0.0.61", "serial": "SNFF0002"},   # серийник из токена
    {"id": "b1", "type": "bambu", "ip": "192.168.1.105", "serial": "01P00A123456789"},
]


def _st(dev, ident=None):
    r = pd.classify([dev], PR2, ident or {})[0]
    return r.get("state"), r.get("printer_id"), r.get("old_ip")


_kl = {"family": "klipper", "adapter": "klipper", "ip": "10.0.0.70", "uuid": ""}
check("102. Klipper без признака по адресу заведённого Klipper — «уже заведён»",
      _st(_kl) == ("known", "k1", None), _st(_kl))
check("103. Klipper с uuid по тому же адресу — «уже заведён» (признак запомнит сервер)",
      _st(dict(_kl, uuid="U1")) == ("known", "k1", None), _st(dict(_kl, uuid="U1")))
_ff = dict(pd.parse_flashforge_packet(ff_packet(serial="SNFF0001"), "10.0.0.60"))
check("104. FlashForge по своему адресу — «уже заведён»", _st(_ff) == ("known", "ff1", None), _st(_ff))
_ff2 = dict(pd.parse_flashforge_packet(ff_packet(serial="SNFF0002"), "10.0.0.61"))
check("105. FlashForge, чей серийник есть в базе (из токена), — «уже заведён»", _st(_ff2) == ("known", "ff2", None), _st(_ff2))
check("106. Bambu по-прежнему «уже заведён»",
      _st(dict(pd.parse_bambu_notify(P1S, "192.168.1.105")))[0] == "known")
check("107. служба Creality по адресу принтера Creality — «уже заведён»",
      _st(dict(_ce[0])) == ("known", "cr1", None) if _ce else False, _ce)
check("108. ДРУГАЯ марка по адресу заведённого принтера — по-прежнему «адрес занят»",
      _st(dict(pd.parse_bambu_notify(X1C.replace(b"10.0.0.51", b"10.0.0.70"), "10.0.0.70")))[0] == "conflict")
check("109. признаки одного вида у обоих известны и различаются — «адрес занят»",
      _st(dict(_kl, uuid="U2"), {"k1": {"kind": "uuid", "value": "U1"}})[0] == "conflict")
check("110. запомненный uuid по новому адресу — «сменил адрес»: Klipper теперь тоже узнаётся",
      _st(dict(_kl, uuid="U1", ip="10.0.0.77"), {"k1": {"kind": "uuid", "value": "U1"}}) == ("moved", "k1", "10.0.0.70"))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
