# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Камера Creality по WebRTC — чистые функции подключения (16.10.2026, R-062).

ЗАЧЕМ. У клиента не подключается камера K2 Pro. Программа знала один путь: POST на
http://<адрес>:8000/call/webrtc_local без токена. Новые прошивки Creality (признак
videoInfo.videoEncryption в списке features) ждут предложение по HTTPS на порту видео (443) и с токеном,
который принтер выдаёт по своей службе 9999. Этот модуль повторяет поведение официального клиента
Creality Print 7.3; сеть — только у вызывающего (server.py, printer_webrtc), здесь — разбор и сборка.

ЧИСТЫЙ МОДУЛЬ: только стандартная библиотека, без сети и файлов. Проверяется без принтера
(tools/test_creality_video.py).

ИСТОЧНИКИ (поведение, код не копируется):
  [CP]  Creality Print v7.3.0 (CrealityOfficial/CrealityPrint): resources/web/deviceMgr/assets/BZCDzYbb.js —
        признак шифрования features.includes("videoInfo.videoEncryption"); порт видео
        secureConnection && videoPort || 443; адрес https://<ip>:<порт>/call/webrtc_local, иначе
        http://<ip>:8000/call/webrtc_local; токен — printer.videoToken (запрос {method:"get",
        params:{getToken:1}} по службе 9999); фильтр SDP kr(): один кодек H.264 с динамическим номером
        96..127 и все строки, не относящиеся к кодекам. src/slic3r/GUI/print_manage/Routes/DeviceMgrRoutes.cpp
        (get_webrtc_local_param): адрес mDNS в строке кандидата заменяется своим IP в сторону принтера,
        тело — base64(JSON{type:"offer", sdp, token}), Content-Type "plain/text", при ошибке HTTPS —
        повтор на http://<ip>:8000 тем же телом. LanDeviceProbe.cpp: https://<ip>:443/info, затем
        http://<ip>:80/info (model, wssPort, videoPort).
  [GK]  geckotdf/Creality-K2-Camera-Fix: при шифровании — POST на http://<ip>/call/webrtc_local (порт 80)
        с токеном.
  [G2R] go2rtc #1600 и client_creality.go: ответ — base64(JSON{type:"answer", sdp}); [HA] ha_creality_ws —
        бывает и сырой SDP («v=0…»).
"""
import base64
import ipaddress
import json
import re

ENCRYPTION_FEATURE = "videoInfo.videoEncryption"
SIGNAL_PATH = "/call/webrtc_local"
HTTP_PORT = 8000            # прежний путь (родная страница принтера, go2rtc)
HTTPS_DEFAULT_PORT = 443    # [CP]: videoPort || 443
PLAIN_PORT = 80             # [GK]
CONTENT_TYPE = "plain/text"  # именно так у [CP] и у родной страницы принтера


def has_video_encryption(features):
    """Есть ли у прошивки признак videoInfo.videoEncryption (камера ждёт HTTPS и токен)."""
    if isinstance(features, str):
        features = [features]
    if not isinstance(features, (list, tuple, set)):
        return False
    return any(str(f).strip() == ENCRYPTION_FEATURE for f in features)


def _port(v):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 65536 else None


def signaling_urls(ip, encrypted, video_port=None, have_token=False):
    """Адреса сигнализации в порядке попыток -> [{"scheme", "port", "url"}].

    С шифрованием — как [CP]: https на порту видео (или 443), затем запасной http :8000 ([CP] сам
    так повторяет), затем http :80 ([GK]). Без шифрования — прежний :8000, и :80 только если есть
    токен (у прошивок без шифрования путь :80 не описан нигде, кроме [GK] с токеном)."""
    ip = str(ip or "").strip()
    out = []

    def add(scheme, port):
        out.append({"scheme": scheme, "port": port, "url": "%s://%s:%d%s" % (scheme, ip, port, SIGNAL_PATH)})
    if encrypted:
        add("https", _port(video_port) or HTTPS_DEFAULT_PORT)
        add("http", HTTP_PORT)
        add("http", PLAIN_PORT)
    else:
        add("http", HTTP_PORT)
        if have_token:
            add("http", PLAIN_PORT)
    return out


def _split_sdp(sdp):
    sep = "\r\n" if "\r\n" in sdp else "\n"
    lines = sdp.split(sep)
    tail = ""
    if lines and lines[-1] == "":
        lines, tail = lines[:-1], sep
    return lines, sep, tail


_RTPMAP = re.compile(r"^a=rtpmap:(\d+)\s+([A-Za-z0-9_.-]+)/", re.I)
_CODEC_LINE = re.compile(r"^a=(?:rtpmap|fmtp|rtcp-fb):(\d+)[\s/]", re.I)


def filter_h264(sdp):
    """Оставить в видеосекции один кодек — первый H.264 с динамическим номером 96..127 — и все строки,
    не относящиеся к кодекам (ICE, DTLS, направление и т. п.). Строка m= не меняется ([CP] kr()).
    Нет H.264 — SDP возвращается без изменений: решать за принтер, что он поймёт, нельзя."""
    if not isinstance(sdp, str) or not sdp:
        return sdp
    lines, sep, tail = _split_sdp(sdp)
    out, i, n, changed = [], 0, len(lines), False
    while i < n:
        ln = lines[i]
        if not ln.startswith("m=video"):
            out.append(ln)
            i += 1
            continue
        j = i + 1
        while j < n and not lines[j].startswith("m="):
            j += 1
        section = lines[i:j]
        keep_pt = None
        for x in section:
            m = _RTPMAP.match(x)
            if m and m.group(2).upper() == "H264" and 96 <= int(m.group(1)) <= 127:
                keep_pt = m.group(1)
                break
        if keep_pt is None:
            out.extend(section)
        else:
            for x in section:
                m = _CODEC_LINE.match(x)
                if m and m.group(1) != keep_pt:
                    changed = True
                    continue
                out.append(x)
        i = j
    return sep.join(out) + tail if changed else sdp


def replace_mdns(sdp, ipv4):
    """В строках «a=candidate:» адрес вида xxxx.local (mDNS, так их прячут Chrome и Edge) заменить
    реальным IPv4 — часть прошивок Creality такие имена не разбирает ([CP], [GK])."""
    if not isinstance(sdp, str) or not sdp or not ipv4:
        return sdp
    lines, sep, tail = _split_sdp(sdp)
    changed = False
    for k, ln in enumerate(lines):
        if not ln.startswith("a=candidate:"):
            continue
        f = ln.split(" ")
        if len(f) > 5 and f[4].lower().endswith(".local"):
            f[4] = ipv4
            lines[k] = " ".join(f)
            changed = True
    return sep.join(lines) + tail if changed else sdp


def encode_offer(sdp, token=None):
    """Тело запроса: base64(JSON{type:"offer", sdp, token}) — компактный JSON, как JSON.stringify у [CP].
    Токен кладётся, только если он есть."""
    obj = {"type": "offer", "sdp": sdp}
    if token:
        obj["token"] = str(token)
    return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def legacy_offer(sdp):
    """Тело, которое программа слала до 16.10.2026 (сырое предложение, без токена) — для одного
    повтора на :8000, чтобы работающий у владельца путь K2 Plus не сломался."""
    return base64.b64encode(json.dumps({"type": "offer", "sdp": sdp}).encode())


def decode_answer(body):
    """Ответ принтера -> {"type": "answer", "sdp": …} или None (ответа нет: пусто, «{}», мусор).
    Понимает base64(JSON) ([CP], [G2R]), просто JSON и сырой SDP «v=0…» ([HA])."""
    if isinstance(body, (bytes, bytearray)):
        text = bytes(body).decode("utf-8", "replace")
    else:
        text = str(body or "")
    text = text.strip()
    if not text:
        return None
    if text.startswith("v=0"):
        return {"type": "answer", "sdp": text}
    obj = None
    if not text.startswith("{"):
        try:
            raw = base64.b64decode(text + "=" * (-len(text) % 4), validate=False)
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            obj = None
    if obj is None:
        try:
            obj = json.loads(text)
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None
    sdp = obj.get("sdp")
    if not isinstance(sdp, str) or "v=0" not in sdp:
        return None
    return {"type": str(obj.get("type") or "answer"), "sdp": sdp}


def parse_info(obj):
    """Ответ /info принтера -> {"model", "video_port", "wss_port", "secure"}. MAC и прочее не берётся."""
    if not isinstance(obj, dict):
        return None
    wss = _port(obj.get("wssPort"))
    return {"model": str(obj.get("model") or "")[:40], "video_port": _port(obj.get("videoPort")),
            "wss_port": wss, "secure": wss is not None}


_FW_RE = (re.compile(r"DWIN sw ver:\s*([^;]+);?", re.I), re.compile(r"printer sw ver:\s*([^;]+);?", re.I))


def firmware_from(model_version):
    """Версия прошивки из modelVersion службы 9999 («…;DWIN sw ver:1.1.6.7;») -> «1.1.6.7» или ""."""
    s = str(model_version or "")
    for rx in _FW_RE:
        m = rx.search(s)
        if m and m.group(1).strip():
            v = re.sub(r"[^0-9A-Za-z._-]", "", m.group(1).strip())
            if v:
                return v[:40]
    return ""


def is_private_ipv4(addr):
    """Адрес частной сети IPv4 (не петля и не 0.0.0.0) — годится для кандидата в предложении."""
    try:
        a = ipaddress.ip_address(str(addr or "").strip())
    except ValueError:
        return False
    return a.version == 4 and a.is_private and not a.is_loopback and not a.is_unspecified and not a.is_link_local


def path_label(scheme, port, token_sent=False, raw=False):
    """Короткая метка пути для журнала и итога попытки: «https:443+token», «http:8000 raw»."""
    return "%s:%s%s%s" % (scheme, port, "+token" if token_sent else "", " raw" if raw else "")
