# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Принтеры Creality на заводской прошивке — родная служба Creality (12.10.2026).

ЗАЧЕМ. У Ender-3 V3 KE, Ender-5 Max, K1 и других принтеров Creality заводская прошивка работает на
Klipper, но Moonraker в ней нет — программа их не видела (обращение клиента 11.10.2026). Root и
установка Moonraker помогают, но это вмешательство в принтер. Сам принтер держит родную службу —
WebSocket на порту 9999, через неё работает Creality Print. Этот модуль говорит с ней.

ЧИСТЫЙ МОДУЛЬ: только стандартная библиотека. Сеть — только у вызывающего (server.py): здесь разбор
сообщений принтера, сборка команд, тела загрузки файла и обезличивание текста для журнала. Так всё
проверяется без принтера (tools/test_creality_native.py).

ИСТОЧНИК КОНТРАКТА. Публичного описания Creality не выпускала. Поля и команды взяты из открытого кода,
который работает с этой службой (ниже, ИСТОЧНИКИ); у разработки принтера нет. Поэтому:
  * незнакомое число состояния остаётся незнакомым (fail-closed) — покоем и успехом оно не становится;
  * первое полное сообщение принтера уходит в журнал обезличенным — по нему контракт уточняется;
  * команд, которых нет хотя бы в двух источниках, модуль не строит (произвольный G-code — никогда).

ИСТОЧНИКИ (проверено по коду 12.10.2026):
  [CP]   CrealityPrint (CrealityOfficial/CrealityPrint): веб-часть управления устройствами
         resources/web/deviceMgr (класс DeviceInterface: pause/stop/opGcodeFile/температуры, подписи
         значений state, сверка загруженного файла CheckUploadFileReady), загрузка файла —
         src/slic3r/GUI/print_manage/Device/Klipper4408Interface.cpp (POST /upload/<имя>, поле file,
         успех — «OK» в ответе).
  [HA]   ha_creality_ws (Home Assistant): живой клиент той же службы; запись обмена с настоящим K1C
         (прошивка 1.3.5.22): полный снимок при подключении, дальше только изменения, температуры
         строками. Сердцебиение {"ModeCode":"heart_beat"} шлёт КЛИЕНТ, принтер отвечает строкой "ok";
         сам принтер heart_beat не шлёт (16.10.2026, R-146: так в [HA] tools/simulator/protocol.py и в
         creality-k1-api). При тишине [HA] и [CP] сами спрашивают принтер запросом только на чтение
         {"method":"get","params":{"reqPrintObjects":1}} — бывают принтеры, которые молчат, пока их не
         спросят. С этой службой работает и Ender-3 V3 KE (модель F005, прошивка V1.1.0.17).
  [ORCA] OrcaSlicer, src/slic3r/Utils/CrealityPrint.cpp: ws://<ip>:9999/, текстовые кадры,
         opGcodeFile "printprt:<путь>"; после команды старта K1 закрывает соединение.
  Код этих проектов в программу НЕ копируется (у [HA] — AGPL): взяты только факты протокола.
"""
import json
import os
import re
import urllib.parse

DEFAULT_PORT = 9999          # служба Creality (WebSocket)
UPLOAD_PORT = 80             # приём файла печати (HTTP POST /upload/<имя>)
DEFAULT_GCODE_DIR = "/usr/data/printer_data/gcodes"   # K1-семейство (запись K1C); путь берётся из списка файлов
SILENCE_RECONNECT_S = 30.0   # нет ни одного сообщения — соединение считается потерянным ([CP]: 20 с)
#  16.10.2026 (R-146): тишина дольше этого — спросить принтер запросом только на чтение (cmd_ask_objects).
#  [CP] спрашивает после 5 с тишины (проверка раз в 5 с), [HA] — reqPrintObjects каждые 2 с; здесь — не
#  чаще раза в 8 с: этого хватает, чтобы карточка не устаревала (CREALITY_FRESH_S в server.py — 20 с).
ASK_AFTER_SILENCE_S = 8.0

# ── состояние задания: число прошивки -> слово программы ─────────────────────────────────────────
#  [CP] подписи: 0 простой, 1 печать, 2 завершено, 3 сбой, 4 прервано, 5 пауза, 6 ставится на паузу,
#  7 останавливается, 8 восстанавливается, 9 печать (начало: самотест, нагрев), 101/102/103 —
#  выполняется стоп/пауза/продолжение. Запись K1C при отмене: 0 -> 9 -> 1 -> 7 -> 4.
STATE_WORDS = {
    0: "idle",
    1: "printing", 8: "printing", 9: "printing", 103: "printing",
    7: "printing", 101: "printing",          # останавливается — задание ещё идёт, пока не станет 4
    5: "paused", 6: "paused", 102: "paused",
    2: "complete",
    3: "error",
    4: "cancelled",
}
CARD_STATUS = {"idle": "IDLE", "printing": "RUNNING", "paused": "PAUSED", "complete": "FINISH",
               "error": "FAILED", "cancelled": "FAILED"}
#  Занят (deviceState 1: едет домой, калибруется) и незнакомое число — НЕ «свободен»: карточка «Занят»,
#  очередь такой принтер не берёт, отправка отказывает. Это и не начало, и не конец печати (учёт
#  печати на «Занят» не реагирует), поэтому короткое незнакомое состояние посреди печати её не закрывает.
CARD_BUSY = "BUSY"
#  Состояния, в которых на принтер можно отправить новую печать (покой, печать закончена/отменена/сбой).
SENDABLE = ("idle", "complete", "cancelled", "error")

#  16.10.2026 (R-146): ответ на reqPrintObjects (список объектов стола) в снимок тоже не кладётся — он
#  бывает большим, а карточке не нужен.
_DROP_KEYS = ("retGcodeFileInfo", "retGcodeFileInfo2", "retGcodeFileInfo3", "historyList", "retHistory",
              "current_object", "excluded_objects", "objects")


def _int(v, default=None):
    try:
        if isinstance(v, bool):
            return default
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        return int(float(s)) if s else default
    except (TypeError, ValueError):
        return default


def _num(v, default=0.0):
    """Число из значения прошивки: у K1-семейства температуры приходят строками ("21.530000"),
    при загрузке принтера — пустой строкой."""
    try:
        if isinstance(v, bool):
            return default
        s = str(v).strip()
        return round(float(s), 1) if s else default
    except (TypeError, ValueError):
        return default


# ── сообщения ───────────────────────────────────────────────────────────────────────────────────
def is_heartbeat(obj):
    """Сердцебиение {"ModeCode": "heart_beat", ...}. По источникам его шлёт клиент, а принтер отвечает
    "ok"; если же сердцебиение пришло от принтера, ответ тот же — строка "ok"."""
    return isinstance(obj, dict) and obj.get("ModeCode") == "heart_beat"


def parse_frame(text):
    """Текст кадра -> dict или None. Не каждый кадр — JSON: строка "ok" и прочее пропускаются."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t or t[0] != "{":
        return None
    try:
        obj = json.loads(t)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def merge(snapshot, frame):
    """Свести изменения в снимок: принтер шлёт полный снимок при подключении, дальше — только
    изменившиеся поля. Список файлов и история в снимок не попадают (их разбирает отдельно тот, кто
    их запрашивал). Пустая строка вместо температуры (принтер загружается) прежнее значение не стирает."""
    if not isinstance(frame, dict):
        return snapshot
    for k, v in frame.items():
        if k in _DROP_KEYS or k == "ModeCode":
            continue
        if isinstance(v, str) and v.strip() == "" and k in snapshot and ("Temp" in k):
            continue
        snapshot[k] = v
    return snapshot


def state_word(snapshot):
    """Слово состояния для программы: idle|printing|paused|complete|error|cancelled; незнакомое
    число — "state_<n>", нет поля — "" (неизвестно). «idle» — только если и устройство свободно
    (deviceState 0): при deviceState 1 принтер занят (возвращается домой, калибруется) — "busy"."""
    st = _int((snapshot or {}).get("state"))
    if st is None:
        return ""
    w = STATE_WORDS.get(st)
    if w is None:
        return "state_%d" % st
    if w == "idle":
        ds = _int(snapshot.get("deviceState"), 0)
        if ds not in (0, None):
            return "busy"
    return w


def file_stem(path):
    """Имя файла без каталога и расширения печати — как его показывает карточка."""
    name = os.path.basename(str(path or "").replace("\\", "/"))
    low = name.lower()
    for ext in (".gcode.3mf", ".gcode", ".3mf"):
        if low.endswith(ext):
            return name[:-len(ext)]
    return name


def to_state(snapshot):
    """Снимок прошивки -> поля карточки программы (без исхода завершения: его решает ядро).

    -> dict: status, status_raw, percent, remaining_time (минуты), total_time (секунды), file_name,
    nozzle_temp, bed_temp, nozzle_target, bed_target, chamber_temp, chamber_target, err_code,
    err_text, filament_out, layer, total_layer, model_code."""
    s = snapshot or {}
    raw = state_word(s)
    status = CARD_STATUS.get(raw, CARD_BUSY)
    #  16.10.2026 (R-146): запасные поля, как у [HA]: dProgress — если нет printProgress, printTimeLeft —
    #  если нет printLeftTime (часть прошивок называет их так).
    pct = _int(s.get("printProgress"), None)
    if pct is None:
        pct = _int(s.get("dProgress"), 0)
    pct = max(0, min(100, pct or 0))
    if raw == "complete":
        pct = 100
    left = _int(s.get("printLeftTime"), None)
    if left is None:
        left = _int(s.get("printTimeLeft"), 0)
    left = max(0, left or 0)
    job = max(0, _int(s.get("printJobTime"), 0) or 0)
    active = raw in ("printing", "paused")
    err = s.get("err") if isinstance(s.get("err"), dict) else {}
    code = _int(err.get("errcode"), 0) or 0
    key = err.get("key")
    return {
        "status": status, "status_raw": raw,
        "percent": pct,
        "remaining_time": int(round(left / 60.0)) if active else 0,
        "total_time": (job + left) if active else 0,
        "file_name": file_stem(s.get("printFileName")),
        "nozzle_temp": _num(s.get("nozzleTemp")), "bed_temp": _num(s.get("bedTemp0")),
        "nozzle_target": _num(s.get("targetNozzleTemp")), "bed_target": _num(s.get("targetBedTemp0")),
        "chamber_temp": _num(s.get("boxTemp")), "chamber_target": _num(s.get("targetBoxTemp")),
        "err_code": str(code) if code else "",
        "err_text": ("" if key in (None, "", 0, "0") else str(key)[:120]),
        "filament_out": _int(s.get("materialStatus"), 0) == 1,
        "layer": _int(s.get("layer"), 0) or 0, "total_layer": _int(s.get("TotalLayer"), 0) or 0,
        "model_code": str(s.get("model") or "")[:40],
    }


def messages(state):
    """Сообщения принтера для блока «Сообщения принтера» (тот же вид, что у других принтеров).
    Код ошибки показывается только пока задание идёт или завершилось сбоем: прошивка оставляет
    в покое старые коды (видели 500 и 116), и выдавать их за свежие нельзя."""
    out = []
    st = state or {}
    if st.get("filament_out"):
        out.append({"code": "", "severity": "common", "module": "filament",
                    "text": {"ru": "Датчик филамента: филамент закончился", "en": "Filament sensor: filament ran out"}})
    if st.get("err_code") and st.get("status_raw") in ("printing", "paused", "error"):
        extra = (" (%s)" % st["err_text"]) if st.get("err_text") else ""
        out.append({"code": st["err_code"], "severity": ("error" if st.get("status_raw") == "error" else "common"),
                    "module": "printer",
                    "text": {"ru": "Код на экране принтера: %s%s" % (st["err_code"], extra),
                             "en": "Code on the printer screen: %s%s" % (st["err_code"], extra)}})
    return out


def fault_text(state):
    """Текст для сбоя (status_raw == "error"): код с экрана, если прошивка его дала."""
    st = state or {}
    if st.get("err_code"):
        return "Принтер Creality сообщил о сбое печати, код %s%s · Creality printer reported a print failure, code %s" % (
            st["err_code"], (" (%s)" % st["err_text"]) if st.get("err_text") else "", st["err_code"])
    return ""


# ── список файлов на принтере ([CP] CheckUploadFileReady) ───────────────────────────────────────
def parse_file_list(frame):
    """Ответ на {"method":"get","params":{"reqGcodeFile":1}} -> [{name, path, size, ctime}] или None,
    если в кадре списка нет. Три вида ответа прошивок: retGcodeFileInfo2 (массив), retGcodeFileInfo
    ("каталог:имя:размер:…:время;…") и retGcodeFileInfo3 ("имя:размер:время;…")."""
    if not isinstance(frame, dict):
        return None
    if isinstance(frame.get("retGcodeFileInfo2"), list):
        out = []
        for it in frame["retGcodeFileInfo2"]:
            if not isinstance(it, dict):
                continue
            out.append({"name": str(it.get("name") or ""), "path": str(it.get("path") or ""),
                        "size": _int(it.get("file_size", it.get("size")), 0) or 0,
                        "ctime": _int(it.get("create_time", it.get("time")), 0) or 0})
        return out
    for key, kind in (("retGcodeFileInfo", 1), ("retGcodeFileInfo3", 3)):
        v = frame.get(key)
        if isinstance(v, dict) and isinstance(v.get("fileInfo"), str):
            out = []
            for row in v["fileInfo"].split(";"):
                parts = row.split(":")
                if kind == 1 and len(parts) >= 3:
                    d, n = parts[0], parts[1]
                    out.append({"name": n, "path": (d.rstrip("/") + "/" + n) if d.startswith("/") else "",
                                "size": _int(parts[2], 0) or 0, "ctime": _int(parts[4], 0) if len(parts) > 4 else 0})
                elif kind == 3 and len(parts) >= 2 and parts[0]:
                    out.append({"name": parts[0], "path": "", "size": _int(parts[1], 0) or 0,
                                "ctime": _int(parts[2], 0) if len(parts) > 2 else 0})
            return out
    return None


def gcode_dir_from(path):
    """Каталог файлов печати из пути, который назвал сам принтер (…/gcodes/имя -> …/gcodes)."""
    p = str(path or "").replace("\\", "/")
    m = re.match(r"\A(/.*?/gcodes)(?:/|\Z)", p)
    return m.group(1) if m else ""


def find_file(files, name):
    """Запись файла с этим именем из списка принтера (или None)."""
    for f in files or ():
        if os.path.basename(str(f.get("name") or "")) == name or os.path.basename(str(f.get("path") or "")) == name:
            return f
    return None


# ── отправка файла и команды ────────────────────────────────────────────────────────────────────
_NAME_DROP = re.compile(r'[\\/:*?"\'<>|#&=+\x00-\x1f]')


def safe_name(fname):
    """Имя файла для принтера: без каталога и знаков, которые [CP] вычищает из имени (\\ / : * ? " ' < > | # & = +).
    Не длиннее 200 байт UTF-8 (предел имени файла в Linux — 255 байт), расширение .gcode сохраняется.
    -> "" если имя не годится (пусто или не .gcode)."""
    n = _NAME_DROP.sub("", os.path.basename(str(fname or "").replace("\\", "/"))).strip()
    if not n.lower().endswith(".gcode"):
        return ""
    stem = n[:-6].rstrip()
    while stem and len((stem + ".gcode").encode("utf-8")) > 200:
        stem = stem[:-1].rstrip()
    return (stem + ".gcode") if stem else ""


def upload_url(ip, name, port=UPLOAD_PORT):
    return "http://%s:%d/upload/%s" % (ip, int(port or UPLOAD_PORT), urllib.parse.quote(name, safe=""))


def upload_body(name, data, boundary):
    """Тело multipart/form-data с одним полем file ([CP] form_add_file("file", …, имя))."""
    fn = name.replace('"', "")
    head = ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n' % (boundary, fn)).encode("utf-8")
    return head + bytes(data or b"") + ("\r\n--%s--\r\n" % boundary).encode("ascii")


def upload_ok(status, body):
    """Принтер принял файл: HTTP 200 и «OK» в ответе ([CP]: icontains(body, "OK"))."""
    try:
        text = bytes(body or b"").decode("utf-8", "replace") if not isinstance(body, str) else body
    except Exception:
        text = ""
    #  «OK» отдельным словом ([CP] ищет подстроку; здесь строже: "token" и "book" — не согласие).
    return int(status or 0) == 200 and re.search(r"(?<![a-z])ok(?![a-z])", text.lower()) is not None


def cmd_set(params):
    return {"method": "set", "params": dict(params)}


def cmd_pause():
    return cmd_set({"pause": 1})


def cmd_resume():
    return cmd_set({"pause": 0})


def cmd_stop():
    return cmd_set({"stop": 1})


def cmd_print_file(path):
    """Начать печать файла, лежащего на принтере. enableSelfTest 0 — как кнопка «Печать» в
    Creality Print без калибровки ([CP] StartNormalPrint)."""
    p = str(path or "")
    if not p.startswith("/") or "\n" in p or "\r" in p:
        raise ValueError("путь файла на принтере")
    return cmd_set({"opGcodeFile": "printprt:" + p, "enableSelfTest": 0})


def cmd_nozzle_temp(c):
    return cmd_set({"nozzleTempControl": int(c)})


def cmd_bed_temp(c):
    return cmd_set({"bedTempControl": {"num": 0, "val": int(c)}})


def cmd_file_list():
    return {"method": "get", "params": {"reqGcodeFile": 1}}


def cmd_ask_objects():
    """Запрос только на чтение при тишине — то, что шлёт [CP] в heartbeat() и [HA] в опросе:
    принтер отвечает кадром (список объектов стола), и молчащий принтер «оживает»."""
    return {"method": "get", "params": {"reqPrintObjects": 1}}


def dumps(obj):
    """Команда — компактный JSON текстовым кадром ([ORCA]: K1 принимает только текстовые кадры)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# ── обезличивание для журнала (журнал владелец отправляет разработке) ────────────────────────────
_SECRET_KEYS = {"serialnumber", "serial", "sn", "mac", "macaddr", "macaddress", "wifimac", "ip", "ipaddr",
                "ipaddress", "localip", "ssid", "password", "passwd", "token", "accesscode", "devicesn",
                "cloudid", "deviceid", "printerid", "hostname", "wifiname", "uid", "userid", "account",
                "gettoken", "token",
                #  16.10.2026 (R-062): токен камеры (videoToken) — доступ к видео принтера, в журнал не идёт.
                "videotoken"}
_SECRET_RE = re.compile(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}|\b(?:\d{1,3}\.){3}\d{1,3}\b")
LOG_MAX = 4000


def _key_norm(k):
    return "".join(ch for ch in str(k or "").lower() if ch.isalnum())


def redact(obj, _depth=0):
    """Значения ключей-секретов -> «***» на любой глубине; ключи остаются (видна структура)."""
    if _depth > 20:
        return "***"
    if isinstance(obj, dict):
        return {k: ("***" if (isinstance(k, str) and _key_norm(k) in _SECRET_KEYS) else redact(v, _depth + 1))
                for k, v in obj.items() if k not in _DROP_KEYS}
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth + 1) for v in obj]
    return obj


#  В журнал — только поля, нужные для разбора контракта, и список имён всех полей (без значений). Имя
#  файла печати (в нём бывают имена заказчиков) — только каталогом; имя принтера, номера и сеть — нет.
LOG_FIELDS = ("state", "deviceState", "model", "modelVersion", "printProgress", "printLeftTime", "printJobTime",
              "nozzleTemp", "targetNozzleTemp", "bedTemp0", "targetBedTemp0", "boxTemp", "targetBoxTemp", "err",
              "materialStatus", "withSelfTest", "enableSelfTest", "layer", "TotalLayer", "webrtcSupport", "video",
              "cfsConnect", "feedState", "connectionCount", "tfCard", "upgradeStatus", "printFileType",
              #  16.10.2026 (R-062): признаки прошивки — по ним видно, нужен ли камере токен (videoInfo.videoEncryption).
              "features")


def log_snapshot(frame, secrets=()):
    """Полный снимок службы -> текст для журнала по списку LOG_FIELDS."""
    f = frame if isinstance(frame, dict) else {}
    out = {k: f[k] for k in LOG_FIELDS if k in f}
    if f.get("printFileName"):
        out["printFileDir"] = gcode_dir_from(f.get("printFileName")) or "?"
    out["_fields"] = sorted(str(k) for k in f.keys())[:200]
    return log_text(out, secrets)


def log_text(obj, secrets=()):
    """Сообщение принтера -> текст для журнала: секреты заменены, адреса и MAC вырезаны, длина
    ограничена. Известные значения (адрес принтера и т. п.) вычищаются и из строк."""
    try:
        text = json.dumps(redact(obj), ensure_ascii=False, default=str)
    except Exception:
        return ""
    for s in secrets or ():
        s = str(s or "")
        if len(s) >= 4:
            text = text.replace(s, "***")
    text = _SECRET_RE.sub("***", text)
    return text[:LOG_MAX]
