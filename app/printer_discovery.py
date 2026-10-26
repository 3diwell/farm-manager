# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.980 (R-092) — программа сама находит принтеры, объявившиеся в сети.

ЧТО ЭТО. Принтеры трёх марок сами рассказывают о себе в локальную сеть: Bambu Lab рассылает
SSDP-объявление со своим серийным номером и моделью, Creality и всё, что построено на Klipper,
объявляется по mDNS, FlashForge отвечает визитной карточкой на пустую датаграмму. Этот модуль
слушает такие объявления и превращает их в список «вот что видно в сети».

ЧЕГО ЗДЕСЬ НЕТ И НЕ БУДЕТ (решение владельца, пункт карты R-092 дословно): «Чего нельзя делать:
перебирать всю сеть подряд. Это нагружает сеть, выглядит для роутера как чужая программа и в
некоторых сетях запрещено. Слушать надо только то, что принтеры объявляют о себе сами.» Поэтому:
  * перебора адресов подсети нет;
  * сканирования портов нет;
  * ни одной команды, которая что-то запускает, останавливает или меняет на принтере, нет;
  * всё, что уходит наружу, перечислено В ОДНОЙ неизменяемой таблице ALLOWED_ASK и является
    стандартным запросом «представься», который в той же сети десятки раз в минуту шлёт сам
    Windows (mDNS PTR, SSDP M-SEARCH) либо фирменная программа марки (пустая датаграмма
    FlashForge). Полезная нагрузка — литералы модуля, она не собирается из переменных.

КОД ДОСТУПА принтер по сети не объявляет и объявлять не должен — его владелец вводит руками.

ОТКУДА КОНТРАКТЫ (правило проекта: адреса, команды и поля не выдумываются):
  * Bambu — перехваты живых пакетов P1S (nuxx.net, 19.12.2024) и X1C (c-base/fake-x1c,
    sniff_x1x.py), плюс независимая реализация StudioBridge; коды моделей — из имён профилей
    в репозитории BambuStudio.
  * FlashForge — двоичная раскладка ответа из работающих реализаций (GhostTypes/ff-5mp-api-py,
    Slugger2k/FlashForgePrinterApi, ffpp): разбор по ДЛИНЕ пакета, порядок байт big-endian.
  * mDNS — RFC 6762/6763, разбор своими руками (библиотеки zeroconf в проекте нет и ставить её
    без разрешения владельца нельзя).
  * Moonraker — официальная документация внешнего API (/access/info, /printer/info).
  * Creality — mDNS-имена служб и GET /info; таблица кодов плат F0xx НЕ подтверждена
    первоисточниками и поэтому в модель НЕ переводится: показывается как есть.
  * 16.10.2026 (R-092): вопрос Bambu «кто здесь» на порт 2021 — дословно как у Bambuddy
    (maziggy/bambuddy, backend/app/services/discovery.py): M-SEARCH с ST
    urn:bambulab-com:device:3dprinter:1 на 239.255.255.250:2021, повтор каждые 3 с; настоящие
    принтеры шлют на 255.255.255.255 (там же, virtual_printer/ssdp_server.py) — поэтому и туда.
    Moonraker по SSDP — исходник Arksine/moonraker, components/zeroconf.py (SERVER «Moonraker
    SSDP/UPNP Server», USN uuid:<instance_uuid>::…, LOCATION …/server/zeroconf/ssdp; включается
    разделом [zeroconf] в moonraker.conf, по умолчанию выключен). Creality на заводской прошивке
    объявляет mDNS-службу _Creality-<серийник>._udp (K1C, prestonbrown/helixscreen issue 1447);
    имена _http._tcp и _workstation._tcp с creality/k1/k2 — как их узнаёт интеграция
    3dg1luk43/ha_creality_ws (manifest.json).

ЧЕГО ПРОВЕРИТЬ НЕЛЬЗЯ БЕЗ ФЕРМЫ. У разработки принтеров нет. Разбор пакетов проверен на
дословных образцах из перехватов, приём — на своих же датаграммах; «нашёлся живой принтер»
подтверждает только ферма. Для этого рядом лежит инструмент записи: tools/printer_net_capture.py
пишет всё, что принтеры шлют в сеть, сырьём — этот дамп и есть настоящий контракт вашей фермы.
"""

import json
import os
import re
import select
import socket
import struct
import threading
import time
from urllib.parse import urlsplit

# ── что и куда мы имеем право отправить ─────────────────────────────────────────────────────
#  Таблица неизменяемая и полная: ничего, чего здесь нет, модуль в сеть не шлёт. Полезная
#  нагрузка — литералы; она не является аргументом функции и не собирается из переменных.
MDNS_GROUP = "224.0.0.251"
MDNS_PORT = 5353
SSDP_GROUP = "239.255.255.250"
SSDP_PORT = 1900
BAMBU_PORTS = (2021, 1990)
FF_GROUP = "225.0.0.9"

SSDP_MSEARCH = (
    b"M-SEARCH * HTTP/1.1\r\n"
    b"HOST: 239.255.255.250:1900\r\n"
    b'MAN: "ssdp:discover"\r\n'
    b"MX: 2\r\n"
    b"ST: upnp:rootdevice\r\n"
    b"\r\n"
)

#  16.10.2026 (R-092): вопрос «кто здесь» для Bambu Lab — тот же, что шлют Bambuddy и слайсеры
#  марки (источник в шапке модуля). Принтер отвечает на адрес и порт отправителя — ответ приходит
#  на открытый сокет запроса, и порт 2021, занятый Bambu Studio или OrcaSlicer на этом же
#  компьютере, ему не мешает. Без этого вопроса Bambu находился только по случайно услышанному
#  объявлению: наш общий M-SEARCH (ST upnp:rootdevice на 1900) принтеры Bambu не слушают.
BAMBU_MSEARCH = (
    b"M-SEARCH * HTTP/1.1\r\n"
    b"HOST: 239.255.255.250:2021\r\n"
    b'MAN: "ssdp:discover"\r\n'
    b"MX: 3\r\n"
    b"ST: urn:bambulab-com:device:3dprinter:1\r\n"
    b"\r\n"
)

#  Имена служб mDNS, о которых спрашиваем. _services._dns-sd._udp — перечисление ВСЕХ типов
#  служб: оно ловит и то, чьё имя мы не знаем заранее, и ничего при этом не угадывает.
MDNS_ASK_NAMES = (
    "_services._dns-sd._udp.local",
    "_moonraker._tcp.local",
    "_octoprint._tcp.local",
    "_prusalink._tcp.local",
    "_http._tcp.local",
    "_workstation._tcp.local",      # 16.10.2026 (R-092): так объявляет себя Linux принтера (avahi)
)


def _mdns_query_bytes():
    """Один запрос mDNS сразу обо всех интересующих именах (QDCOUNT > 1)."""
    return build_mdns_ptr_query(MDNS_ASK_NAMES)


#  (имя зонда, адрес, порт, полезная нагрузка). Пустая датаграмма FlashForge — именно пустая:
#  прошивка содержимое запроса не разбирает, а пустой пакет возмущает сеть меньше всего.
ALLOWED_ASK = (
    ("mdns-ptr", MDNS_GROUP, MDNS_PORT, None),          # тело собирается _mdns_query_bytes()
    ("ssdp-msearch", SSDP_GROUP, SSDP_PORT, SSDP_MSEARCH),
    ("flashforge-19000", FF_GROUP, 19000, b""),
    ("flashforge-8899", FF_GROUP, 8899, b""),
    ("flashforge-48899", "255.255.255.255", 48899, b""),
    ("bambu-msearch-2021", SSDP_GROUP, 2021, BAMBU_MSEARCH),            # 16.10.2026 (R-092)
    ("bambu-msearch-bcast", "255.255.255.255", 2021, BAMBU_MSEARCH),    # принтеры Bambu шлют на broadcast
    #  16.10.2026 (R-092): та же пустая датаграмма FlashForge и на broadcast портов 19000 и 8899 —
    #  так делает ff-5mp-api-py (flashforge/discovery/discovery.py, _send_discovery_packets: пустой
    #  пакет на 255.255.255.255 по всем трём портам). Многоадресную группу 225.0.0.9 роутеры с
    #  IGMP snooping часто не пропускают, а broadcast в своей сети доходит.
    ("flashforge-19000-bcast", "255.255.255.255", 19000, b""),
    ("flashforge-8899-bcast", "255.255.255.255", 8899, b""),
)

#  16.10.2026 (R-092): какие вопросы повторяются за окно поиска и как часто. UDP теряет пакеты,
#  а Bambuddy повторяет свой M-SEARCH каждые 3 секунды. Повторяется тот же литерал из таблицы
#  выше, через тот же сокет, — ничего нового не отправляется. Повторов ровно два (решение по
#  пункту: «ещё дважды примерно через 3 с»): трёх вопросов хватает на потерю пакета, а сеть фермы
#  не засыпается вопросами все 25-90 секунд поиска.
REPEAT_ASK = ("bambu-msearch-2021", "bambu-msearch-bcast")
ASK_REPEAT_S = 3.0
ASK_REPEATS = 2

#  Порты, которые слушаем. «Слушать» — это ноль отправленных байт.
LISTEN_PORTS = (2021, 1990, 5353, 1900)

#  Порты сырой записи для инструмента владельца: сюда добавлены и те, куда отвечают марки,
#  которых программа пока не поддерживает — дамп нужен полный.
CAPTURE_PORTS = (2021, 1990, 5353, 1900, 19000, 8899, 48899, 3000, 20054)

_MCAST_FOR_PORT = {5353: MDNS_GROUP, 1900: SSDP_GROUP, 2021: SSDP_GROUP, 1990: SSDP_GROUP}


# ════════════════════════════════════════════════════════════════════════════════════════════
#  СЛОЙ 1 — ЧИСТЫЕ РАЗБОРЩИКИ. Ни одного сокета, ни одного файла: всё проверяется офлайн на
#  дословных образцах пакетов.
# ════════════════════════════════════════════════════════════════════════════════════════════

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(s, limit=120):
    """Текст из сети — недоверенный: он приходит от устройства и может содержать что угодно.
    Режем управляющие символы и длину ДО того, как значение куда-то попадёт."""
    s = _CTRL_RE.sub("", str(s or "")).strip()
    return s[:limit]


def parse_ssdp_headers(buf):
    """HTTP-подобная датаграмма -> (первая строка, {заголовок в нижнем регистре: значение}).
    Регистр заголовков у разных прошивок разный, у значения бывает лишний пробел."""
    try:
        txt = bytes(buf).decode("utf-8", "ignore")
    except Exception:
        return "", {}
    lines = txt.replace("\r\n", "\n").split("\n")
    start = lines[0].strip() if lines else ""
    out = {}
    for ln in lines[1:]:
        if not ln.strip():
            continue
        k, _, v = ln.partition(":")
        if not _:
            continue
        out[k.strip().lower()] = v.strip()
    return start, out


def _is_ssdp_question(start_line):
    """16.10.2026 (R-092): первая строка «M-SEARCH * HTTP/1.1» — это вопрос, который кто-то задаёт
    сети (мы сами, Bambu Studio, OrcaSlicer, Bambuddy), а не устройство, ответившее о себе."""
    return str(start_line or "").strip().upper().startswith("M-SEARCH")


#  Коды моделей Bambu -> человеческие имена. Источник: имена профилей машин в репозитории
#  BambuStudio; длинные псевдонимы отдают старые прошивки X1-серии.
BAMBU_MODEL_CODES = {
    "BL-P001": "X1 Carbon", "3DPrinter-X1-Carbon": "X1 Carbon",
    "BL-P002": "X1", "3DPrinter-X1": "X1",
    "C13": "X1E", "C11": "P1P", "C12": "P1S",
    "N1": "A1 mini", "N2S": "A1", "N6": "X2D", "N7": "P2S", "N9": "A2L",
    "O1C": "H2C", "O1C2": "H2C", "O1D": "H2D", "O1E": "H2D Pro", "O1S": "H2S",
}

#  Коды моделей FlashForge (PID из двоичного ответа).
FLASHFORGE_PIDS = {
    0x0023: "Adventurer 5M", 0x0024: "Adventurer 5M Pro", 0x0026: "AD5X",
    0x0028: "Creator 5", 0x0029: "Creator 5 Pro",
    0x0008: "Adventurer 3", 0x000D: "Adventurer 3 Lite", 0x001D: "Adventurer 3 Pro 2",
    0x0016: "Adventurer 4 Lite", 0x001E: "Adventurer 4 Pro",
    0x0004: "Guider 2", 0x0009: "Guider 2S", 0x0019: "Guider 3 Plus",
    0x001F: "Guider 3 Ultra", 0x0025: "Guider 4", 0x0027: "Guider 4 Pro",
}
FF_VID = 0x2B71


def parse_bambu_notify(buf, src_ip=""):
    """Объявление Bambu Lab (UDP 2021/1990) -> сведения о принтере либо None.

    Дословный образец (P1S, прошивка 01.07.00.00):
        NOTIFY * HTTP/1.1
        Location: 192.168.1.105
        NT: urn:bambulab-com:device:3dprinter:1
        USN: <серийный номер>
        DevModel.bambu.com: C12
        DevName.bambu.com: Bambu Lab P1S
        DevConnect.bambu.com: lan
    Заголовок HOST в пакете лжёт (в нём 1900 или 1990) — на него не смотрим.
    """
    start, h = parse_ssdp_headers(buf)
    #  16.10.2026 (R-092): M-SEARCH — это ВОПРОС «кто здесь», а не принтер. В нём тот же ST
    #  urn:bambulab-com…, и без этой проверки наш собственный вопрос (группа 239.255.255.250:2021
    #  возвращается и на наш же слушатель порта 2021) или вопрос Bambu Studio с соседнего
    #  компьютера показывались «новым принтером Bambu» по адресу компьютера. Принтер говорит
    #  только объявлением NOTIFY или ответом «HTTP/1.1 200 OK».
    if _is_ssdp_question(start):
        return None
    kind = (h.get("nt") or h.get("st") or "")
    if "bambulab-com:device:3dprinter" not in kind.lower():
        return None
    #  Location у Bambu — ГОЛЫЙ адрес без схемы: через разбор ссылок его пропускать нельзя.
    loc = _clean(h.get("location") or "", 64)
    ip = loc if _looks_like_ip(loc) else _clean(src_ip, 64)
    usn = _clean(h.get("usn") or "", 64)
    if usn.lower().startswith("uuid:"):
        usn = usn[5:].strip()
    code = _clean(h.get("devmodel.bambu.com") or "", 40)
    dev = {
        "family": "bambu", "adapter": "bambu", "ip": ip, "port": 8883,
        "serial": usn, "model_code": code,
        "model": BAMBU_MODEL_CODES.get(code, ""),
        "name": _clean(h.get("devname.bambu.com") or "", 80),
        "firmware": _clean(h.get("devversion.bambu.com") or "", 40),
        "connect_mode": _clean(h.get("devconnect.bambu.com") or "", 20).lower(),
        "bind_state": _clean(h.get("devbind.bambu.com") or "", 20).lower(),
        "signal_dbm": _clean(h.get("devsignal.bambu.com") or "", 12),
        "probe": "bambu-ssdp",
        "alive": "ssdp:byebye" not in (h.get("nts") or "").lower(),
    }
    if not dev["ip"]:
        return None
    return dev


def _looks_like_ip(s):
    try:
        socket.inet_aton(str(s or ""))
        return str(s).count(".") == 3
    except Exception:
        return False


_MOONRAKER_SERVER = "moonraker ssdp/upnp server"
_MOONRAKER_URN = "urn:arksine.github.io:device:moonraker:1"


def parse_moonraker_ssdp(buf, src_ip=""):
    """16.10.2026 (R-092): ответ или объявление Moonraker по SSDP -> принтер Klipper либо None.

    Формат — из исходника Moonraker (components/zeroconf.py): SERVER «Moonraker SSDP/UPNP Server»,
    USN «uuid:<instance_uuid>::upnp:rootdevice», LOCATION «http://<адрес>:<порт>/server/zeroconf/ssdp»,
    у объявления NT «urn:arksine.github.io:device:Moonraker:1». uuid — тот же, что в TXT записи
    mDNS-службы _moonraker._tcp, поэтому это постоянный признак принтера.
    Узнаём по любому из трёх признаков: чужой rootdevice (роутер, телевизор) сюда не проходит."""
    start, h = parse_ssdp_headers(buf)
    if _is_ssdp_question(start):
        return None                   # чужой вопрос «кто здесь» — не принтер (см. parse_bambu_notify)
    server = (h.get("server") or "").lower()
    kind = (h.get("nt") or h.get("st") or "").lower()
    loc = _clean(h.get("location") or "", 200)
    is_mr = (_MOONRAKER_SERVER in server or kind == _MOONRAKER_URN
             or loc.lower().split("?")[0].rstrip("/").endswith("/server/zeroconf/ssdp"))
    if not is_mr:
        return None
    ip, port = "", 0
    try:
        u = urlsplit(loc)
        host = u.hostname or ""
        if _looks_like_ip(host):
            ip = host
        if loc:
            port = int(u.port or (443 if (u.scheme or "").lower() == "https" else 80))
    except Exception:
        ip, port = "", 0
    if not ip:
        ip = _clean(src_ip, 64)
    usn = _clean(h.get("usn") or "", 120)
    uid = ""
    if usn.lower().startswith("uuid:"):
        uid = usn[5:].split("::", 1)[0].strip()
    dev = {
        "family": "klipper", "adapter": "klipper", "vendor_hint": "klipper",
        "ip": ip, "port": port or 7125, "uuid": _clean(uid, 64),
        "name": "", "model": "", "model_code": "", "serial": "",
        "probe": "ssdp", "alive": "ssdp:byebye" not in (h.get("nts") or "").lower(),
    }
    if not dev["ip"]:
        return None
    return dev


def parse_flashforge_packet(buf, src_ip=""):
    """Визитная карточка FlashForge -> сведения о принтере либо None.

    Двоичный пакет, порядок байт big-endian; формат определяется ДЛИНОЙ, а не портом:
      >= 276 байт — новый: имя [0x00:0x80], порт команд 0x84, VID 0x86, PID 0x88,
                    состояние 0x8A, порт HTTP 0x8E, серийный номер [0x92:0x92+128];
      >= 140 байт — старый: то же самое без серийного номера;
      меньше — не наш пакет.
    Проверка VID == 0x2B71 отсекает чужие датаграммы, случайно попавшие на тот же порт.
    """
    b = bytes(buf or b"")
    if len(b) < 140:
        return None
    try:
        port_cmd = int.from_bytes(b[0x84:0x86], "big")
        vid = int.from_bytes(b[0x86:0x88], "big")
        pid_code = int.from_bytes(b[0x88:0x8A], "big")
        state = int.from_bytes(b[0x8A:0x8C], "big")
    except Exception:
        return None
    if vid != FF_VID:
        return None
    name = _cstr(b[0x00:0x80])
    serial = _cstr(b[0x92:0x92 + 128]) if len(b) >= 276 else ""
    port_http = int.from_bytes(b[0x8E:0x90], "big") if len(b) >= 276 else 0
    return {
        "family": "flashforge", "adapter": "flashforge",
        "ip": _clean(src_ip, 64), "port": port_http or 8898,
        "port_gcode": port_cmd or 8899,
        "serial": _clean(serial, 64), "name": _clean(name, 80),
        "model_code": "0x%04X" % pid_code,
        "model": FLASHFORGE_PIDS.get(pid_code, ""),
        "state_code": state, "probe": "flashforge-udp", "alive": True,
    }


def _cstr(raw):
    """Строка, оканчивающаяся нулевым байтом. Имя может быть кириллицей или иероглифами."""
    b = bytes(raw or b"")
    z = b.find(b"\x00")
    if z >= 0:
        b = b[:z]
    try:
        return b.decode("utf-8", "ignore")
    except Exception:
        return ""


# ── mDNS: разбор своими руками (библиотеки zeroconf в проекте нет) ───────────────────────────

def build_mdns_ptr_query(names, unicast=False):
    """Запрос PTR сразу о нескольких именах. QTYPE=12 (PTR), QCLASS=1 (IN);
    старший бит класса (0x8000) — просьба ответить юникастом (RFC 6762 §5.4)."""
    names = tuple(names or ())
    out = struct.pack(">HHHHHH", 0, 0, len(names), 0, 0, 0)
    qclass = 0x8001 if unicast else 0x0001
    for nm in names:
        out += _encode_dns_name(nm) + struct.pack(">HH", 12, qclass)
    return out


def _encode_dns_name(name):
    out = b""
    for part in str(name or "").strip(".").split("."):
        p = part.encode("utf-8")[:63]
        out += bytes([len(p)]) + p
    return out + b"\x00"


def read_dns_name(buf, off, depth=0):
    """Имя из сообщения DNS с учётом сжатия (указатель 0xC0).

    Возвращает (имя, смещение СРАЗУ ЗА именем в исходном месте). Защиты обязательны: указатель
    вперёд или на себя — это петля, на которой разборщик зависнет, а такой пакет может прислать
    кто угодно в сети.
    """
    b = bytes(buf)
    parts = []
    jumped = False
    end = off
    steps = 0
    while True:
        steps += 1
        if steps > 128 or depth > 20:
            raise ValueError("mdns: слишком длинное имя или петля указателей")
        if off >= len(b):
            raise ValueError("mdns: имя выходит за границу пакета")
        ln = b[off]
        if ln == 0:
            off += 1
            if not jumped:
                end = off
            break
        if (ln & 0xC0) == 0xC0:
            if off + 1 >= len(b):
                raise ValueError("mdns: обрезанный указатель")
            ptr = ((ln & 0x3F) << 8) | b[off + 1]
            if ptr >= off:
                raise ValueError("mdns: указатель вперёд или на себя")
            if not jumped:
                end = off + 2
                jumped = True
            off = ptr
            depth += 1
            continue
        off += 1
        if off + ln > len(b):
            raise ValueError("mdns: метка выходит за границу пакета")
        parts.append(b[off:off + ln].decode("utf-8", "ignore"))
        off += ln
        if not jumped:
            end = off
    return ".".join(parts), end


def parse_dns_txt(rdata):
    """TXT-запись: набор строк <длина>ключ=значение."""
    out = {}
    b = bytes(rdata or b"")
    i = 0
    while i < len(b):
        ln = b[i]
        i += 1
        chunk = b[i:i + ln]
        i += ln
        if not chunk:
            continue
        k, _, v = chunk.decode("utf-8", "ignore").partition("=")
        if k:
            out[k.strip().casefold()] = v.strip()
    return out


def parse_mdns_message(buf):
    """Сообщение mDNS -> {'ptr': [...], 'srv': {...}, 'txt': {...}, 'a': {...}}.

    Разбираем и вопросы, и ответы: чужой вопрос пропускаем, интересуют записи. Битый пакет —
    не ошибка программы: в эфире их достаточно, поэтому разбор терпимый.
    """
    b = bytes(buf or b"")
    res = {"ptr": [], "srv": {}, "txt": {}, "a": {}}
    if len(b) < 12:
        return res
    try:
        _id, _flags, qd, an, ns, ar = struct.unpack(">HHHHHH", b[:12])
    except Exception:
        return res
    off = 12
    try:
        for _ in range(qd):
            _nm, off = read_dns_name(b, off)
            off += 4
        for _ in range(an + ns + ar):
            nm, off = read_dns_name(b, off)
            if off + 10 > len(b):
                break
            rtype, rclass, _ttl, rdlen = struct.unpack(">HHIH", b[off:off + 10])
            off += 10
            rdata = b[off:off + rdlen]
            nxt = off + rdlen
            if rtype == 12:                                   # PTR
                tgt, _ = read_dns_name(b, off)
                res["ptr"].append((nm, tgt))
            elif rtype == 33 and rdlen >= 6:                  # SRV
                _pri, _w, port = struct.unpack(">HHH", rdata[:6])
                host, _ = read_dns_name(b, off + 6)
                res["srv"][nm] = {"port": int(port), "host": host}
            elif rtype == 16:                                 # TXT
                res["txt"][nm] = parse_dns_txt(rdata)
            elif rtype == 1 and rdlen == 4:                   # A
                #  16.10.2026 (R-092): у имени бывает несколько адресов; адрес самоназначения
                #  169.254.x (сеть без DHCP) уступает настоящему, а не затирает его.
                ip4 = socket.inet_ntoa(rdata)
                cur = res["a"].get(nm)
                if not cur or (cur.startswith("169.254.") and not ip4.startswith("169.254.")):
                    res["a"][nm] = ip4
            off = nxt
    except Exception:
        return res
    return res


#  Имена служб, по которым узнаём принтер. Всё прочее пропускаем молча.
_SVC_FAMILY = (
    ("_moonraker._tcp", "klipper"),
    ("_octoprint._tcp", "octoprint"),
    ("_prusalink._tcp", "prusa"),
)


#  16.10.2026 (R-092): заводская прошивка Creality объявляет службу _Creality-<серийник>._udp
#  (источник в шапке модуля); _http._tcp и _workstation._tcp — общие службы любого компьютера,
#  поэтому из них берём только имена с creality, k1 или k2 в начале слова.
_CREALITY_SN_RE = re.compile(r"_creality-([^.\s]+)\._udp", re.I)
_CREALITY_LABEL_RE = re.compile(r"creality|(?:^|[^a-z0-9])k[12]", re.I)
_GENERIC_SVC = ("_http._tcp", "_workstation._tcp")
_MAC_SUFFIX_RE = re.compile(r"\s*\[([0-9a-f]{2}(?::[0-9a-f]{2}){5})\]\s*$", re.I)


def devices_from_mdns(msg, src_ip=""):
    """Из разобранного сообщения mDNS — список находок. Своих выводов не делаем: если имя
    службы неизвестно, устройство не выдумывается."""
    out = []
    a_map = dict(msg.get("a") or {})
    srv = dict(msg.get("srv") or {})
    txt = dict(msg.get("txt") or {})
    seen = set()

    def _ip_for(inst):
        host = (srv.get(inst) or {}).get("host") or ""
        ip = a_map.get(host) or a_map.get(host.rstrip(".")) or ""
        src = _clean(src_ip, 64)
        #  16.10.2026 (R-092): адрес самоназначения 169.254.x уступает адресу, с которого пакет
        #  пришёл на самом деле.
        if ip.startswith("169.254.") and src and not src.startswith("169.254."):
            return src
        return ip or src

    for nm, tgt in (msg.get("ptr") or []):
        low = (nm or "").lower()
        #  16.10.2026 (R-092): служба заводской прошивки Creality с серийным номером в имени —
        #  и в перечислении всех служб (_services._dns-sd), и в прямом ответе о ней самой.
        m_sn = _CREALITY_SN_RE.search((nm or "") + " " + (tgt or ""))
        if m_sn:
            inst = tgt or nm
            sn = _clean(m_sn.group(1), 64)
            if ("sn:" + sn) in seen:
                continue
            seen.add("sn:" + sn)
            out.append({
                "family": "klipper", "adapter": "creality", "vendor_hint": "creality",
                "ip": _clean(_ip_for(inst), 64), "port": 9999,
                "name": _clean("Creality-" + sn, 80), "service": _clean(inst, 120),
                "uuid": "", "model": "", "model_code": "",
                "serial": sn, "probe": "mdns", "alive": True,
            })
            continue
        if any(g in low for g in _GENERIC_SVC) and tgt and tgt.lower() != low:
            label = tgt.split(".")[0]
            mac_m = _MAC_SUFFIX_RE.search(label)
            plain = _MAC_SUFFIX_RE.sub("", label)
            if not _CREALITY_LABEL_RE.search(plain):
                continue
            if tgt in seen:
                continue
            seen.add(tgt)
            out.append({
                #  Прошивка (заводская или Moonraker) по этим службам не видна: форма заполнится
                #  как Klipper, а проба адреса при сохранении сама предложит службу Creality.
                "family": "klipper", "adapter": "klipper", "vendor_hint": "creality",
                "ip": _clean(_ip_for(tgt), 64), "port": 0,
                "name": _clean(plain, 80), "service": _clean(tgt, 120),
                "uuid": "", "model": "", "model_code": "", "serial": "",
                "mac": _norm_mac(mac_m.group(1)) if mac_m else "",
                "probe": "mdns", "alive": True,
            })
            continue
        fam = ""
        for pref, f in _SVC_FAMILY:
            if pref in low:
                fam = f
                break
        if not fam and "creality" in low + " " + (tgt or "").lower():
            fam = "creality"
        if not fam:
            continue
        inst = tgt or nm
        if inst in seen:
            continue
        seen.add(inst)
        rec = txt.get(inst) or {}
        port = int((srv.get(inst) or {}).get("port") or 0)
        label = _clean((inst.split(".")[0] if inst else ""), 80)
        out.append({
            "family": "klipper" if fam in ("klipper", "creality") else fam,
            "adapter": "klipper" if fam in ("klipper", "creality") else "",
            "vendor_hint": "creality" if fam == "creality" else fam,
            "ip": _clean(_ip_for(inst), 64), "port": port or (7125 if fam == "klipper" else 80),
            "name": label, "service": _clean(inst, 120),
            "uuid": _clean(rec.get("uuid") or "", 64),
            "model": "", "model_code": "",
            "serial": "", "probe": "mdns", "alive": True,
        })
    return [d for d in out if d.get("ip")]


def parse_moonraker_info(access_info, printer_info, system_info=None):
    """Ответы Moonraker -> имя, версия прошивки и вечный признак (MAC).
    Все три запроса — чистое чтение, ничего не запускают."""
    out = {"name": "", "firmware": "", "mac": "", "confirmed": False}
    ai = (access_info or {}).get("result") or access_info or {}
    if isinstance(ai, dict) and (ai.get("default_source") or ai.get("available_sources")):
        out["confirmed"] = True
    pi = (printer_info or {}).get("result") or printer_info or {}
    if isinstance(pi, dict):
        out["name"] = _clean(pi.get("hostname") or "", 80)
        out["firmware"] = _clean(pi.get("software_version") or "", 60)
        if pi.get("state"):
            out["confirmed"] = True
    si = ((system_info or {}).get("result") or system_info or {}).get("system_info") or {}
    net = si.get("network") or {}
    if isinstance(net, dict):
        for _iface, val in net.items():
            mac = (val or {}).get("mac_address") if isinstance(val, dict) else ""
            if mac:
                out["mac"] = _norm_mac(mac)
                break
    return out


def parse_creality_info(obj):
    """Ответ Creality GET /info -> модель и MAC. MAC — вечный признак этого принтера."""
    o = obj if isinstance(obj, dict) else {}
    return {"model_code": _clean(o.get("model") or o.get("machine") or "", 40),
            "mac": _norm_mac(o.get("mac") or ""),
            "name": _clean(o.get("hostname") or o.get("name") or "", 80)}


def _norm_mac(mac):
    s = re.sub(r"[^0-9A-Fa-f]", "", str(mac or ""))
    return s.upper()[:12] if len(s) >= 12 else ""


def parse_m115(text):
    """Ответ FlashForge на ~M115 (только чтение, ничего не двигает).
    Разбор по ПРЕФИКСАМ строк; регистр названия марки у разных прошивок разный."""
    out = {"name": "", "model": "", "firmware": "", "serial": ""}
    for ln in str(text or "").replace("\r\n", "\n").split("\n"):
        s = ln.strip()
        low = s.lower()
        if low.startswith("machine type:"):
            out["model"] = _clean(s.split(":", 1)[1], 60)
        elif low.startswith("machine name:"):
            out["name"] = _clean(s.split(":", 1)[1], 80)
        elif low.startswith("firmware:"):
            out["firmware"] = _clean(s.split(":", 1)[1], 60)
        elif low.startswith("sn:") or low.startswith("serial number:"):
            out["serial"] = _clean(s.split(":", 1)[1], 64)
    return out


# ── опознание модели, вечный признак, слияние и сверка с заведёнными ─────────────────────────

def canonical_model(family, code, name_hint="", cover_names=()):
    """Код модели -> имя, которое ТОЧНО есть среди обложек принтеров. Точного совпадения нет —
    модель не подставляем: неверное имя хуже пустого (обложка не появится, а подбор совместимого
    g-code начнёт врать)."""
    plain = []
    if family == "bambu":
        plain.append(BAMBU_MODEL_CODES.get(str(code or ""), ""))
    elif family == "flashforge":
        try:
            plain.append(FLASHFORGE_PIDS.get(int(str(code or "0"), 16), ""))
        except Exception:
            pass
    plain.append(_clean(name_hint, 60))
    #  Обложки названы С МАРКОЙ: «Bambu Lab P1S», «Flashforge Adventurer 5M Pro», «Creality K2 Plus».
    #  Поэтому кроме голого имени модели пробуем и его же с маркой впереди.
    brand = {"bambu": "Bambu Lab ", "flashforge": "Flashforge ", "klipper": "Creality "}.get(family, "")
    cand = []
    for c in plain:
        if not c:
            continue
        cand.append(c)
        if brand and not c.lower().startswith(brand.strip().lower()):
            cand.append(brand + c)
    idx = {_norm_model_key(c): c for c in (cover_names or ())}
    for c in cand:
        hit = idx.get(_norm_model_key(c))
        if hit:
            return hit, (plain[0] or c)
        if not cover_names:
            return c, c
    return "", ((plain[0] if plain else "") or _clean(name_hint, 60))


def _norm_model_key(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def identity_key(dev):
    """Вечный признак устройства — то, по чему его узнают после смены адреса.
    Адрес признаком не является НИКОГДА."""
    d = dev or {}
    if d.get("serial"):
        return ("serial", str(d["serial"]))
    if d.get("mac"):
        return ("mac", str(d["mac"]))
    if d.get("uuid"):
        return ("uuid", str(d["uuid"]))
    return None


def _dev_keys(dev):
    """Ключи слияния по убыванию надёжности: вечный признак, затем (адрес, семейство), затем адрес."""
    keys = []
    ik = identity_key(dev)
    if ik:
        keys.append("id:%s:%s" % ik)
    ip = dev.get("ip") or ""
    if ip:
        keys.append("ipfam:%s:%s" % (ip, dev.get("family") or ""))
        keys.append("ip:%s" % ip)
    return keys


_FIELD_RANK = {"mdns": 1, "bambu-ssdp": 2, "flashforge-udp": 2, "ssdp": 1,
               "http-confirm": 3, "m115": 3}


def merge_devices(seq):
    """Одно устройство приходит несколько раз: FlashForge отвечает на три порта, Bambu шлёт на
    два, PrusaLink объявляет три службы. Без слияния один принтер занял бы четыре места.

    Правило: сначала объединяем по вечному признаку, затем по (адрес, семейство), затем по
    адресу. Непустое поле побеждает пустое; при двух непустых — более достоверный источник."""
    groups = []          # [{"keys": set, "dev": dict}]
    index = {}
    for raw in (seq or []):
        if not raw or not raw.get("ip"):
            continue
        dev = dict(raw)
        keys = _dev_keys(dev)
        hit = None
        for k in keys:
            g = index.get(k)
            if g is not None:
                hit = g
                break
        if hit is None:
            g = {"keys": set(keys), "dev": dev, "sources": [dev.get("probe") or ""]}
            groups.append(g)
            for k in keys:
                index[k] = g
            continue
        _merge_into(hit["dev"], dev)
        hit["sources"].append(dev.get("probe") or "")
        for k in keys + _dev_keys(hit["dev"]):
            hit["keys"].add(k)
            index[k] = hit
    out = []
    for g in groups:
        d = dict(g["dev"])
        d["sources"] = sorted({s for s in g["sources"] if s})
        ik = identity_key(d)
        d["key"] = ("%s:%s" % ik) if ik else ("ip:%s" % d.get("ip"))
        out.append(d)
    out.sort(key=lambda x: (x.get("family") or "", x.get("ip") or ""))
    return out


def _merge_into(base, add):
    for k, v in (add or {}).items():
        if k in ("probe", "sources", "key"):
            continue
        if v in (None, "", 0):
            continue
        cur = base.get(k)
        if cur in (None, "", 0):
            base[k] = v
            continue
        if k in ("model", "name", "firmware", "model_code"):
            if _FIELD_RANK.get(add.get("probe"), 0) > _FIELD_RANK.get(base.get("probe"), 0):
                base[k] = v
    if _FIELD_RANK.get(add.get("probe"), 0) > _FIELD_RANK.get(base.get("probe"), 0):
        base["probe"] = add.get("probe")


#  16.10.2026 (R-092): какие найденные семейства подходят заведённому типу принтера. Creality в
#  поиске числится семейством klipper (mDNS у них общий), поэтому к нему подходят и принтер на
#  заводской прошивке (тип creality), и с Moonraker (тип klipper).
_TYPE_FAMILIES = {
    "bambu": ("bambu",),
    "flashforge": ("flashforge",),
    "klipper": ("klipper",),
    "creality": ("klipper",),
}


def classify(devices, printers, identities=None):
    """Сверка найденного с уже заведёнными принтерами. Пять состояний, порядок проверки важен:

      known       — вечный признак совпал и адрес тот же: показать серым, добавлять нечего;
                    16.10.2026 (R-092): либо по адресу заведённого принтера отвечает устройство
                    той же марки, а признака, по которому их можно было бы различить, у
                    заведённого ещё нет (Klipper и Creality серийника в базе не держат) —
                    это он и есть; признак программа тогда запоминает (server.py);
      moved       — вечный признак совпал, адрес другой: предложить обновить адрес;
      conflict    — по этому адресу заведён ДРУГОЙ принтер: другая марка либо признаки одного
                    вида у обоих известны и различаются. Адрес мог достаться от DHCP чужому,
                    и молча ничего менять нельзя;
      unsupported — марка, для которой в программе нет адаптера: показать честно и не обещать;
      new         — ничего из перечисленного: можно добавить.
    """
    ident = dict(identities or {})
    by_id, by_ip, p_ids = {}, {}, {}
    for p in (printers or []):
        pid = str((p or {}).get("id") or "")
        if not pid:
            continue
        ids = {}
        rec = ident.get(pid) or {}
        if rec.get("kind") and rec.get("value"):
            by_id["%s:%s" % (rec["kind"], rec["value"])] = pid
            ids.setdefault(str(rec["kind"]), set()).add(str(rec["value"]))
        if (p.get("serial") or "").strip():
            by_id["serial:%s" % p["serial"].strip()] = pid
            ids.setdefault("serial", set()).add(p["serial"].strip())
        if (p.get("ip") or "").strip():
            by_ip[p["ip"].strip()] = pid
        p_ids[pid] = ids
    pmap = {str((p or {}).get("id") or ""): p for p in (printers or [])}
    out = []
    for d in (devices or []):
        dev = dict(d)
        ik = identity_key(dev)
        idk = ("%s:%s" % ik) if ik else ""
        pid = by_id.get(idk, "")
        same_ip_pid = by_ip.get(dev.get("ip") or "", "")
        if pid:
            p = pmap.get(pid) or {}
            if (p.get("ip") or "") == (dev.get("ip") or ""):
                dev["state"], dev["printer_id"] = "known", pid
            else:
                dev["state"], dev["printer_id"] = "moved", pid
                dev["old_ip"] = p.get("ip") or ""
        elif same_ip_pid:
            p = pmap.get(same_ip_pid) or {}
            fams = _TYPE_FAMILIES.get(str(p.get("type") or "").strip().lower(), ())
            known_ids = p_ids.get(same_ip_pid) or {}
            if (dev.get("family") or "") not in fams:
                dev["state"] = "conflict"                       # другая марка на этом адресе
            elif ik and ik[0] in known_ids and ik[1] not in known_ids[ik[0]]:
                dev["state"] = "conflict"                       # признаки одного вида различаются
            else:
                dev["state"] = "known"
            dev["printer_id"] = same_ip_pid
        elif not dev.get("adapter"):
            dev["state"] = "unsupported"
        else:
            dev["state"] = "new"
        out.append(dev)
    return out


def redact(dev):
    """То, что уходит в интерфейс. Длины обрезаны, управляющие символы вырезаны ещё при разборе;
    здесь — окончательный отбор полей, чтобы наружу случайно не уехало лишнее."""
    d = dev or {}
    keep = ("key", "family", "adapter", "vendor_hint", "ip", "port", "port_gcode", "name",
            "model", "model_code", "serial", "firmware", "connect_mode", "bind_state",
            "signal_dbm", "state", "printer_id", "old_ip", "sources", "service", "uuid", "mac")
    out = {}
    for k in keep:
        if k in d and d[k] not in (None, ""):
            out[k] = d[k]
    return out


# ════════════════════════════════════════════════════════════════════════════════════════════
#  СЛОЙ 2 — СОКЕТЫ. Тонкий: ничего не решает, наружу не бросает.
# ════════════════════════════════════════════════════════════════════════════════════════════

def iter_local_ipv4():
    """Адреса локальных сетевых карт. Нужны, чтобы вступить в группу многоадресной рассылки
    и отправить запрос НА КАЖДОЙ карте: у владельца бывает и кабель, и Wi-Fi, и виртуальные
    сети, а один запрос уйдёт только через маршрут по умолчанию."""
    ips = []
    try:
        for res in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = res[4][0]
            if ip and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 53))       # маршрут выбирается ядром, пакеты не отправляются
            ip = s.getsockname()[0]
            if ip and ip not in ips:
                ips.insert(0, ip)
        finally:
            s.close()
    except Exception:
        pass
    good = [ip for ip in ips if not ip.startswith("127.") and not ip.startswith("169.254.")]
    return good or ips


def recv_all(sock, limit=32):
    """Всё, что успело прийти на неблокирующий сокет. -> ([(данные, (адрес, порт))], была_ошибка).
    «Нечего читать» ошибкой не считается; ошибка — сбой сокета (например, отказ сети Windows),
    по ней вызывающий решает, держать ли сокет дальше, чтобы не крутиться на нём впустую."""
    out, err = [], False
    if not sock:
        return out, err
    for _ in range(limit):
        try:
            data, addr = sock.recvfrom(9000)
        except (BlockingIOError, InterruptedError, socket.timeout):
            break
        except Exception:
            err = True
            break
        if not data:
            break
        out.append((data, addr))
    return out, err


class UdpListener:
    """Один слушающий порт. Ноль отправленных байт.

    SO_REUSEADDR ставится ДО bind и обязателен: порт 2021 на том же компьютере может держать
    Bambu Studio или OrcaSlicer. SO_EXCLUSIVEADDRUSE не ставится НИКОГДА — иначе мы отберём
    порт у слайсера владельца, и принтеры перестанут находиться уже в нём.
    """

    def __init__(self, port, group="", interfaces=()):
        self.port = int(port)
        self.group = group or ""
        self.error = ""
        self.joined = 0
        self.sock = None
        self._ifaces = tuple(interfaces or ())

    def open(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
            except Exception:
                pass
            s.bind(("", self.port))
            s.setblocking(False)
            self.sock = s
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            self.sock = None
            return False
        if self.group:
            for ip in (self._ifaces or ("0.0.0.0",)):
                try:
                    mreq = socket.inet_aton(self.group) + socket.inet_aton(ip)
                    self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    self.joined += 1
                except Exception:
                    continue
        return True

    def read(self, limit=32):
        """Всё, что успело прийти. -> [(данные, (адрес, порт))]"""
        out = []
        if not self.sock:
            return out
        for _ in range(limit):
            try:
                data, addr = self.sock.recvfrom(9000)
            except Exception:
                break
            if not data:
                break
            out.append((data, addr))
        return out

    def close(self):
        s, self.sock = self.sock, None
        if not s:
            return
        if self.group:
            for ip in (self._ifaces or ("0.0.0.0",)):
                try:
                    mreq = socket.inet_aton(self.group) + socket.inet_aton(ip)
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                except Exception:
                    pass
        try:
            s.close()
        except Exception:
            pass


class UdpAsker:
    """Отправка запросов «представься». Шлёт ТОЛЬКО то, что перечислено в ALLOWED_ASK.

    08.10.2026 (обход фермы, R-092: «найдено 0», хотя в сети 5 принтеров). Ответ на запрос
    приходит ТУДА, ОТКУДА ушёл запрос: FlashForge и SSDP отвечают на адрес и порт отправителя,
    а mDNS-ответчик на запрос не с порта 5353 обязан ответить так же (RFC 6762, §6.7). Прежде
    сокет запроса закрывался сразу после отправки, и все ответы терялись: находились только
    принтеры, которые сами в этот момент рассылали объявление. С keep_open сокет остаётся
    открытым до конца поиска и читается вместе со слушателями. Отправляется ровно то же, что
    и раньше. Бонус для фермы: брандмауэр Windows по умолчанию пропускает ответы на собственные
    многоадресные и широковещательные запросы программы (3 секунды), даже если входящие
    пакеты для неё не разрешены."""

    def __init__(self, interfaces=(), keep_open=False):
        self._ifaces = tuple(interfaces or ()) or ("0.0.0.0",)
        self.sent = []
        self.error = ""
        self.keep_open = bool(keep_open)
        self.socks = []        # [(сокет, имя запроса)] — при keep_open ждут ответов
        self._dest = {}        # 16.10.2026: сокет -> (карта, адрес, порт, тело) — для повтора вопроса

    def drop(self, sock):
        """Закрыть один сокет ожидания (он сбоит) — остальные продолжают ждать."""
        keep = []
        for s, name in self.socks:
            if s is sock:
                self._dest.pop(s, None)
                try:
                    s.close()
                except Exception:
                    pass
            else:
                keep.append((s, name))
        self.socks = keep

    def close_all(self):
        socks, self.socks = self.socks, []
        self._dest = {}
        for s, _name in socks:
            try:
                s.close()
            except Exception:
                pass

    def ask_all(self, allow_names=None):
        """-> число отправленных датаграмм. allow_names сужает список, расширить его нельзя."""
        names = set(allow_names or [n for n, _a, _p, _b in ALLOWED_ASK])
        n = 0
        for name, addr, port, payload in ALLOWED_ASK:
            if name not in names:
                continue
            body = _mdns_query_bytes() if payload is None else payload
            for ip in self._ifaces:
                if self._send_one(ip, addr, port, body, name):
                    n += 1
        return n

    def resend(self, allow_names):
        """16.10.2026 (R-092): повторить уже заданный вопрос ТЕМ ЖЕ сокетом -> число датаграмм.
        Повторяется только то, что ушло через ask_all, — то есть только строки ALLOWED_ASK;
        ответ на повтор придёт на тот же открытый сокет. Без keep_open сокетов нет — тогда
        вопрос задаётся заново тем же ask_all."""
        names = set(allow_names or ())
        if not names:
            return 0
        if not self.keep_open:
            return self.ask_all(names)
        n = 0
        for s, name in list(self.socks):
            if name not in names:
                continue
            dest = self._dest.get(s)
            if not dest:
                continue
            iface_ip, addr, port, body = dest
            try:
                s.sendto(body, (addr, int(port)))
                self.sent.append({"probe": name, "iface": iface_ip, "to": "%s:%d" % (addr, port),
                                  "bytes": len(body), "repeat": True})
                n += 1
            except Exception as e:
                self.error = "%s: %s" % (type(e).__name__, e)
        return n

    def _send_one(self, iface_ip, addr, port, body, name):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if addr.endswith(".255") or addr == "255.255.255.255":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            else:
                try:
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
                    if iface_ip != "0.0.0.0":
                        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                     socket.inet_aton(iface_ip))
                except Exception:
                    pass
            if iface_ip != "0.0.0.0":
                try:
                    s.bind((iface_ip, 0))
                except Exception:
                    pass
            s.settimeout(1.0)
            s.sendto(body, (addr, int(port)))
            self.sent.append({"probe": name, "iface": iface_ip, "to": "%s:%d" % (addr, port),
                              "bytes": len(body)})
            if self.keep_open:
                s.setblocking(False)
                self.socks.append((s, name))
                self._dest[s] = (iface_ip, addr, int(port), body)
                s = None                  # закроет close_all в конце поиска
            return True
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            return False
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass


# ════════════════════════════════════════════════════════════════════════════════════════════
#  СЛОЙ 3 — СЕССИИ
# ════════════════════════════════════════════════════════════════════════════════════════════

class DiscoverySession:
    """Одно окно поиска. Промежуточные результаты видны сразу: снимок обновляется на каждом
    принятом пакете, а не в конце."""

    #  08.10.2026 (R-092): сокеты запросов ждут ответа до конца поиска (см. UdpAsker). Набор
    #  проверок выключает это, чтобы доказать, что без него ответ теряется.
    KEEP_ASK_SOCKETS = True
    #  16.10.2026 (R-092): пауза между повторами вопроса Bambu (набор проверок её укорачивает)
    #  и сколько раз вопрос повторяется после первого.
    ASK_REPEAT_S = ASK_REPEAT_S
    ASK_REPEATS = ASK_REPEATS

    def __init__(self, log=None):
        self.log = log
        self._lock = threading.RLock()
        self._reset()

    def _reset(self):
        self.active = False
        self.status = "idle"
        self.started = 0.0
        self.deadline = 0.0
        self.seconds = 0
        self.warnings = []
        self.ports = []
        self.asked = []
        self.received = {}     # сколько датаграмм пришло: «порт 2021», «ответ mdns-ptr»…
        self.raw = []          # накопленные находки до слияния
        self._stop = threading.Event()
        self._ready = threading.Event()   # порты открыты (или честно помечены занятыми)
        self._done = threading.Event()

    # ── управление ──────────────────────────────────────────────────────────────────────
    def start(self, seconds=25, ask=True, on_done=None):
        with self._lock:
            if self.active:
                return False, "already_running"
            self._reset()
            self.active = True
            self.status = "listening"
            self.seconds = max(10, min(90, int(seconds or 25)))
            self.started = time.monotonic()
            self.deadline = self.started + self.seconds
        t = threading.Thread(target=self._run, args=(bool(ask), on_done),
                             name="discovery-session", daemon=True)
        t.start()
        #  Ждём, пока сокеты открыты: первый же снимок должен честно показать, какие порты
        #  заняты. Ожидание короткое и ограниченное — поток при неудаче всё равно завершится.
        self._ready.wait(3.0)
        return True, ""

    def stop(self):
        with self._lock:
            if not self.active:
                return False
            self._stop.set()
        #  Ждём, пока поток действительно закроет сокеты: иначе сразу после «Остановить»
        #  снимок ещё показывал бы поиск идущим, и владелец решил бы, что кнопка не работает.
        self._done.wait(2.0)
        return True

    def snapshot(self, printers=None, identities=None, cover_names=()):
        with self._lock:
            raw = list(self.raw)
            out = {
                #  Поле называется «phase», а не «status»: ответы маршрутов программы уже несут
                #  своё поле status ("ok"/"error"), и одноимённое поле снимка его затирало.
                "active": self.active, "phase": self.status,
                "seconds": self.seconds,
                "elapsed_s": round(max(0.0, time.monotonic() - self.started), 1) if self.started else 0,
                "remaining_s": round(max(0.0, self.deadline - time.monotonic()), 1) if self.active else 0,
                "ports": list(self.ports), "warnings": list(self.warnings),
                "asked": list(self.asked), "received": dict(self.received),
            }
        devs = merge_devices(raw)
        for d in devs:
            nice, rawlbl = canonical_model(d.get("family"), d.get("model_code"),
                                           d.get("model") or d.get("name"), cover_names)
            d["model"] = nice
            d["model_label"] = rawlbl
        out["devices"] = [redact(d) for d in classify(devs, printers or [], identities or {})]
        out["found"] = len(out["devices"])
        return out

    # ── работа ──────────────────────────────────────────────────────────────────────────
    def _run(self, ask, on_done):
        listeners = []
        asker = None
        try:
            ifaces = iter_local_ipv4()
            if not ifaces:
                self._warn("no_interfaces", "не удалось определить ни одной сетевой карты")
            for port in LISTEN_PORTS:
                l = UdpListener(port, _MCAST_FOR_PORT.get(port, ""), ifaces)
                ok = l.open()
                with self._lock:
                    self.ports.append({"port": port, "open": bool(ok), "joined": l.joined,
                                       "error": l.error})
                if ok:
                    listeners.append(l)
                else:
                    self._warn("port_busy", "порт %d занять не удалось: %s" % (port, l.error))
            self._ready.set()
            if ask:
                asker = UdpAsker(ifaces, keep_open=self.KEEP_ASK_SOCKETS)
                asker.ask_all()
                with self._lock:
                    self.asked = list(asker.sent)
            next_repeat = time.monotonic() + max(0.2, float(self.ASK_REPEAT_S or 3.0))
            repeats_left = max(0, int(self.ASK_REPEATS or 0))
            while not self._stop.is_set() and time.monotonic() < self.deadline:
                if asker is not None and repeats_left > 0 and time.monotonic() >= next_repeat:
                    #  16.10.2026 (R-092): повтор вопроса Bambu тем же сокетом (UDP теряет пакеты).
                    repeats_left -= 1
                    next_repeat = time.monotonic() + max(0.2, float(self.ASK_REPEAT_S or 3.0))
                    if asker.resend(REPEAT_ASK):
                        with self._lock:
                            self.asked = list(asker.sent)
                socks = [l.sock for l in listeners if l.sock] + [s for s, _n in (asker.socks if asker else [])]
                if not socks:
                    break
                try:
                    ready, _w, _x = select.select(socks, [], [], 0.5)
                except Exception:
                    break
                for l in listeners:
                    if l.sock in ready:
                        for data, addr in l.read():
                            self._count("порт %d" % l.port)
                            self._absorb(l.port, data, addr)
                for s, probe in list(asker.socks if asker else []):
                    if s in ready:
                        got, err = recv_all(s)
                        for data, addr in got:
                            self._count("ответ " + probe)
                            self._absorb_reply(probe, data, addr)
                        if err and not got:
                            asker.drop(s)      # сокет сбоит — не крутимся на нём до конца поиска
            with self._lock:
                self.status = "stopped" if self._stop.is_set() else "done"
        except Exception as e:
            self._warn("error", "%s: %s" % (type(e).__name__, e))
            with self._lock:
                self.status = "error"
        finally:
            for l in listeners:
                l.close()
            if asker is not None:
                asker.close_all()
            self._log_summary()
            with self._lock:
                self.active = False
            self._ready.set()
            self._done.set()
            if callable(on_done):
                try:
                    on_done()
                except Exception:
                    pass

    def _absorb(self, port, data, addr):
        src = (addr or ("", 0))[0]
        found = None
        try:
            if port in BAMBU_PORTS or port == SSDP_PORT:
                found = parse_bambu_notify(data, src)
                if found is None and port == SSDP_PORT:
                    found = parse_moonraker_ssdp(data, src)   # 16.10.2026 (R-092): Klipper с [zeroconf]
            elif port == MDNS_PORT:
                for d in devices_from_mdns(parse_mdns_message(data), src):
                    self._add(d)
                return
            if found is None:
                ff = parse_flashforge_packet(data, src)
                if ff:
                    found = ff
        except Exception:
            found = None
        if found:
            self._add(found)

    def _absorb_reply(self, probe, data, addr):
        """Ответ на наш запрос — разбирается по виду запроса, на который он пришёл."""
        src = (addr or ("", 0))[0]
        found = None
        try:
            if probe.startswith("mdns"):
                for d in devices_from_mdns(parse_mdns_message(data), src):
                    self._add(d)
                return
            if probe.startswith("ssdp") or probe.startswith("bambu"):
                found = parse_bambu_notify(data, src)
                if found is None:
                    found = parse_moonraker_ssdp(data, src)   # 16.10.2026 (R-092)
            if found is None:
                found = parse_flashforge_packet(data, src)
        except Exception:
            found = None
        if found:
            self._add(found)

    def _count(self, key):
        with self._lock:
            self.received[key] = self.received.get(key, 0) + 1

    def _log_summary(self):
        """Одна строка в журнал фермы по итогам поиска: по ней видно, приходило ли вообще что-то
        (брандмауэр, сеть) или приходило, но принтером не опознано."""
        if self.log is None:
            return
        try:
            with self._lock:
                found = len(merge_devices(list(self.raw)))
                rx = dict(self.received)
                closed = ["%s (%s)" % (p.get("port"), p.get("error")) for p in self.ports if not p.get("open")]
                asked = len(self.asked)
            self.log.info("[DISCOVERY] поиск окончен: найдено %d; запросов отправлено %d; пакетов пришло: %s; "
                          "не открылись порты: %s", found, asked,
                          (", ".join("%s — %d" % (k, v) for k, v in sorted(rx.items())) or "ни одного"),
                          (", ".join(closed) or "нет"))
        except Exception:
            pass

    def _add(self, dev):
        if not dev or not dev.get("ip"):
            return
        with self._lock:
            self.raw.append(dev)

    def _warn(self, code, text):
        with self._lock:
            self.warnings.append({"code": code, "text": _clean(text, 200)})
        if self.log is not None:
            try:
                self.log.debug("[DISCOVERY] %s: %s", code, text)
            except Exception:
                pass


class NetCaptureSession:
    """Сырая запись всего, что принтеры шлют в сеть — для снятия настоящего контракта на ферме.
    По умолчанию НЕ ОТПРАВЛЯЕТ НИ ОДНОГО БАЙТА."""

    def __init__(self, log=None):
        self.log = log
        self._lock = threading.RLock()
        self.active = False
        self.path = ""
        self.packets = 0
        self.by_port = {}
        self.sources = {}
        self.error = ""
        self._stop = threading.Event()

    def start(self, out_dir, seconds=600, ports=(), say_hello=False):
        with self._lock:
            if self.active:
                return False, "already_running"
            self.active = True
            self.packets = 0
            self.by_port = {}
            self.sources = {}
            self.error = ""
            self._stop = threading.Event()
        t = threading.Thread(target=self._run,
                             args=(out_dir, int(seconds or 600), tuple(ports or CAPTURE_PORTS),
                                   bool(say_hello)),
                             name="discovery-capture", daemon=True)
        t.start()
        return True, ""

    def stop(self):
        self._stop.set()
        return True

    def snapshot(self):
        with self._lock:
            return {"active": self.active, "path": self.path, "packets": self.packets,
                    "by_port": dict(self.by_port), "sources": dict(self.sources),
                    "error": self.error}

    def _run(self, out_dir, seconds, ports, say_hello):
        listeners = []
        asker = None
        fh = None
        try:
            os.makedirs(out_dir, exist_ok=True)
            name = "printer_net_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(out_dir, name)
            with self._lock:
                self.path = path
            fh = open(path, "w", encoding="utf-8", newline="\n")
            ifaces = iter_local_ipv4()
            for port in ports:
                l = UdpListener(port, _MCAST_FOR_PORT.get(port, ""), ifaces)
                if l.open():
                    listeners.append(l)
            if say_hello:
                asker = UdpAsker(ifaces, keep_open=True)
                asker.ask_all()
            t0 = time.monotonic()
            deadline = t0 + seconds if seconds > 0 else float("inf")
            while not self._stop.is_set() and time.monotonic() < deadline:
                socks = [l.sock for l in listeners if l.sock] + [s for s, _n in (asker.socks if asker else [])]
                if not socks:
                    break
                try:
                    ready, _w, _x = select.select(socks, [], [], 0.5)
                except Exception:
                    break
                for l in listeners:
                    if l.sock in ready:
                        for data, addr in l.read(64):
                            self._write(fh, l.port, data, addr, t0)
                for s, probe in list(asker.socks if asker else []):
                    if s in ready:
                        got, err = recv_all(s, 64)
                        for data, addr in got:
                            self._write(fh, 0, data, addr, t0, reply_to=probe)
                        if err and not got:
                            asker.drop(s)
        except Exception as e:
            with self._lock:
                self.error = "%s: %s" % (type(e).__name__, e)
        finally:
            for l in listeners:
                l.close()
            if asker is not None:
                asker.close_all()
            if fh is not None:
                try:
                    fh.close()
                except Exception:
                    pass
            with self._lock:
                self.active = False

    def _write(self, fh, port, data, addr, t0, reply_to=""):
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mono": round(time.monotonic() - t0, 3),
            "listen_port": int(port), "proto": "udp",
            "src_ip": (addr or ("", 0))[0], "src_port": (addr or ("", 0))[1],
            "len": len(data), "hex": bytes(data).hex(),
            "text": _CTRL_RE.sub(".", bytes(data).decode("utf-8", "ignore"))[:2000],
        }
        if reply_to:
            rec["reply_to"] = reply_to        # ответ на наш запрос «представься» (listen_port 0)
        try:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
        except Exception:
            return
        with self._lock:
            self.packets += 1
            self.by_port[str(port)] = self.by_port.get(str(port), 0) + 1
            self.sources[rec["src_ip"]] = self.sources.get(rec["src_ip"], 0) + 1
