# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Диагностика камеры и место журнала (Alpha 2.938).
#
# БЕЗ сервера, сети, принтеров и рабочей папки данных: _camera_probe и _camera_http_head
# извлекаются из server.py ДОСЛОВНО через AST и исполняются со стабами; отчёт строится
# настоящей app.diagnostics.diagnose.
#
# ЗАЧЕМ ЭТО ЕСТЬ. Случай клиента 27.08.2026: камера Creality K2 Pro не подключается, а в
# журнале об этом ни строчки — журнал замер, потому что писался в C:\Program Files, куда
# обычной программе Windows писать нельзя. Здесь сторожим оба вывода:
#   * журнал живёт в папке данных, а не в папке программы, и выгрузка для поддержки
#     называет его путь и признаётся, если журнал не пишется;
#   * кнопка диагностики на карточке принтера проверяет камеру и НАЗЫВАЕТ причину отказа.
#
# 16.10.2026 (R-062): «камера в порядке» — только по итогу НАСТОЯЩЕЙ попытки открыть камеру (или по
# живому MJPEG), а не по открытому порту 8000: на прошивке 1.1.5.5 порт открыт, а видео нет. Версию
# прошивки отчёт берёт у принтера сам (служба 9999); тип «creality» проверяется тоже.
#
# Запуск: python tools/test_camera_diagnostics.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

fail = 0
TOTAL = 0


def check(name, cond, detail=""):
    global fail, TOTAL
    TOTAL += 1
    print(("PASS" if cond else "FAIL") + " — " + name + (("  ::  " + str(detail)[:200]) if (not cond and detail) else ""))
    if not cond:
        fail += 1


def grab(fn_name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name:
            return ast.get_source_segment(SRC, n)
    raise AssertionError("функция не найдена: " + fn_name)


print("--- 1. журнал живёт в папке данных, а не в папке программы ---")
#  Именно эта строка была корнем немого журнала у клиента.
check("1. LOG_DIR считается от DATA_DIR",
      'LOG_DIR = os.path.join(DATA_DIR, "logs")' in SRC)
check("2. LOG_DIR НЕ считается от папки программы",
      'LOG_DIR = os.path.join(BASE_DIR, "logs")' not in SRC)
check("3. старые файлы журнала переносятся однократно",
      "_migrate_log_files" in SRC and "shutil.copy2(src, dst)" in SRC)
check("4. причина отказа журнала запоминается, а не гасится молча",
      "_LOG_SETUP_ERROR" in SRC and "_LOG_SETUP_ERROR = _exc_brief()" in SRC)
check("5. выгрузка для поддержки называет путь журнала",
      'H.append("Файл журнала:    " + LOG_FILE)' in SRC)
check("6. выгрузка признаётся, когда журнал не пишется",
      "журнал НЕ ПИШЕТСЯ" in SRC)

print("")
print("--- 2. проба путей камеры: что она вообще пробует ---")
ns = {}
exec("import json, urllib.request", ns)


class _Log(object):
    def __init__(self):
        self.lines = []

    def _mk(self, lvl):
        def rec(*a, **k):
            try:
                self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
            except Exception:
                self.lines.append(str(a))
        return rec

    def __getattr__(self, item):
        return self._mk(item)


ns["log"] = _Log()
TRIED = []


def _fake_tcp(ip, port, timeout=2.0):
    TRIED.append(("tcp", ip, port))
    return {"reachable": port == 8000, "latency_ms": 5 if port == 8000 else None}


ns["_tcp_probe"] = _fake_tcp
exec(grab("_camera_http_head"), ns)


def _fake_head(url, timeout=2.0):
    TRIED.append(("http", url))
    return {"ok": "8080" in url, "code": 200, "ctype": "multipart/x-mixed-replace", "error": None}


def _fake_service(p, timeout=2.0):
    TRIED.append(("service", p.get("ip")))
    return {"reachable": True, "features": ["videoInfo.videoEncryption"], "webrtc": 1, "video": 1, "fw": "1.1.6.7"}


def _fake_info(ip, timeout=2.0):
    TRIED.append(("info", ip))
    return {"ok": True, "model": "F012", "video_port": 443, "wss_port": None, "secure": False, "via": "https"}


ns["_camera_http_head"] = _fake_head
ns["_cam_service_probe"] = _fake_service
ns["_cam_info_probe"] = _fake_info
ns["_cam_signal_last"] = {}
ns["_cam_port"] = lambda port: int(port)          # у владельца порты настоящие
exec(grab("_camera_probe"), ns)
probe = ns["_camera_probe"]

P_K2 = {"id": "k2", "name": "к2 pro", "type": "klipper", "model": "Creality K2 Pro",
        "ip": "192.168.1.92", "port": ""}

TRIED[:] = []
res = probe(P_K2)
keys = sorted(res or {})
check("7. пробуются все пути камеры: прежние шесть, служба 9999 и /info",
      keys == ["alt_443", "fluidd_page", "info", "mjpeg_8080", "mjpeg_root", "moonraker", "service", "webrtc_8000"], keys)
check("8. проверяется порт 8000 — тот, которым пользуется сама программа",
      ("tcp", "192.168.1.92", 8000) in TRIED, TRIED)
check("9. при пустом порте Moonraker спрашивается на 7125",
      any(t[0] == "http" and ":7125/server/webcams/list" in t[1] for t in TRIED), TRIED)
check("10. проверяются оба типовых адреса MJPEG",
      any("webcam/?action=stream" in t[1] for t in TRIED if t[0] == "http")
      and any(":8080/?action=stream" in t[1] for t in TRIED if t[0] == "http"), TRIED)
check("11. проверяются 443, /camera.html, служба 9999 (признаки и версия прошивки) и /info",
      ("tcp", "192.168.1.92", 443) in TRIED and ("service", "192.168.1.92") in TRIED and ("info", "192.168.1.92") in TRIED
      and any("/camera.html" in t[1] for t in TRIED if t[0] == "http"), TRIED)
check("12. итог пробы попадает в журнал (иначе улика опять потеряется)",
      any("camera probe" in x for x in ns["log"].lines), ns["log"].lines[:3])

for bad, why in ((dict(P_K2, type="bambu"), "у Bambu камера по другому протоколу"),
                 (dict(P_K2, ip=""), "без адреса пробовать нечего")):
    check("13. проба не запускается там, где она бессмысленна (%s)" % why, probe(bad) is None)

#  16.10.2026 (R-062, R-146): Creality на заводской прошивке — та же проба, без Moonraker и Fluidd.
TRIED[:] = []
P_CR = {"id": "cr9", "name": "K1C", "type": "creality", "model": "Creality K1C", "ip": "192.168.1.93", "port": 9999}
ns["_cam_signal_last"]["cr9"] = {"answered": True, "path": "https:443+token", "fw": "1.3.5.22", "tried": ["https:443+token=200"]}
res_cr = probe(P_CR)
check("13а. Creality на заводской прошивке: камера тоже проверяется (без Moonraker и страницы Fluidd)",
      sorted(res_cr or {}) == ["alt_443", "info", "mjpeg_8080", "mjpeg_root", "service", "signal", "webrtc_8000"]
      and not any(":7125/" in t[1] or "/camera.html" in t[1] for t in TRIED if t[0] == "http"), sorted(res_cr or {}))
check("13б. в пробу попадает итог последней настоящей попытки открыть камеру — по нему отчёт и судит",
      (res_cr or {}).get("signal", {}).get("answered") is True and (res_cr or {}).get("signal", {}).get("path") == "https:443+token")

print("")
print("--- 3. проба не подвешивает кнопку диагностики ---")
#  Настоящая проба по заведомо недостижимому адресу (RFC 5737 TEST-NET-1, маршрута нет): и служба 9999,
#  и /info — настоящие функции программы, не заглушки.
import ssl as _ssl  # noqa: E402
from app import creality_native as _cn_mod  # noqa: E402
from app import creality_video as _cv_mod  # noqa: E402
ns2 = {}
exec("import json, urllib.request, ssl, socket, time, os, sys", ns2)
#  Срок памяти «служба закрыта» — настоящее значение из server.py (присваивание исполняется как есть).
_closed_s = [n for n in TREE.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_CAM_9999_CLOSED_S" for t in n.targets)]
exec(ast.get_source_segment(SRC, _closed_s[0]) if _closed_s else "_CAM_9999_CLOSED_S = None", ns2)
ns2.update({"log": _Log(), "_cn": _cn_mod, "_cv": _cv_mod, "_creality_snap": {}, "_CAM_9999_CLOSED": {},
            "_CAM_INFO_CACHE": {}, "_E2E": None, "_cam_signal_last": {},
            "_exc_brief": lambda: ""})
from app.diagnostics import tcp_probe as _real_tcp  # noqa: E402
ns2["_tcp_probe"] = _real_tcp
for _fn in ("_creality_connect", "_cam_port", "_cam_tls_ctx", "_cam_service_query", "_cam_info", "_cam_service_probe",
            "_cam_info_probe", "_camera_http_head", "_camera_probe"):
    exec(grab(_fn), ns2)
t0 = time.time()
out = ns2["_camera_probe"](dict(P_K2, ip="192.0.2.1"), timeout=1.0)
dt = time.time() - t0
check("14. недостижимый принтер не подвешивает пробу (уложились в 6 с)", dt < 6.0, "%.1f с" % dt)
check("15. при недостижимом принтере ни один путь не отмечен рабочим",
      not any((v or {}).get("ok") or (v or {}).get("reachable") for v in (out or {}).values()), out)
#  16.10.2026: «служба 9999 закрыта» запоминается только после ЯВНОГО отказа подключения и только при
#  открытии камеры. Тайм-аут (принтер загружается, сбой Wi-Fi) не запоминается: иначе на 10 минут пропадал
#  путь с токеном, и камера K2 с защитой видео не открывалась. Кнопка диагностики проверяет «сейчас».
check("15а. недостижимый принтер (тайм-аут) не записан в «служба закрыта» — ни пробой диагностики, ни открытием камеры",
      ("192.0.2.1", 9999) not in ns2["_CAM_9999_CLOSED"], dict(ns2["_CAM_9999_CLOSED"]))
_q = ns2["_cam_service_query"]("192.0.2.1", 9999, want_token=False, wait=0.5)
check("15б. тайм-аут при открытии камеры тоже не запоминается: следующая попытка снова спросит службу",
      _q.get("error") == "TimeoutError" and ("192.0.2.1", 9999) not in ns2["_CAM_9999_CLOSED"]
      and not ns2["_cam_service_query"]("192.0.2.1", 9999, want_token=False, wait=0.5).get("closed_cached"),
      (_q, dict(ns2["_CAM_9999_CLOSED"])))
import socket as _sock  # noqa: E402
_s = _sock.socket()
_s.bind(("127.0.0.1", 0))
_closed_port = _s.getsockname()[1]
_s.close()                                         # порт свободен: подключение к нему — явный отказ
_q = ns2["_cam_service_query"]("127.0.0.1", _closed_port, want_token=False, wait=0.5, remember=False)
check("15в. диагностика (без памяти) на закрытом порте: отказ виден, но в «служба закрыта» не записан",
      _q.get("error") == "ConnectionRefusedError" and ("127.0.0.1", _closed_port) not in ns2["_CAM_9999_CLOSED"],
      (_q, dict(ns2["_CAM_9999_CLOSED"])))
_q = ns2["_cam_service_query"]("127.0.0.1", _closed_port, want_token=False, wait=0.5)
_t0 = time.time()
_q2 = ns2["_cam_service_query"]("127.0.0.1", _closed_port, want_token=False, wait=0.5)
check("15г. явный отказ при открытии камеры запоминается (у Voron этой службы нет) — повтор не ждёт, но не дольше минуты",
      _q.get("error") == "ConnectionRefusedError" and _q2.get("closed_cached") is True and time.time() - _t0 < 0.5
      and 0 < ns2["_CAM_9999_CLOSED"].get(("127.0.0.1", _closed_port), 0) - time.monotonic() <= 61,
      (_q, _q2, ns2["_CAM_9999_CLOSED"]))
#  Принтер типа 'creality': службу держит воркер, «закрыто» для него не запоминается — открытие камеры
#  с отказом службы не отключает путь с токеном на следующие попытки.
_posts = []


def _fake_cam_post(ip, scheme, port, body, read_timeout):
    _posts.append((scheme, port))
    return {"stage": "connect", "status": None, "body": b"", "error": "ConnectionRefusedError"}


ns2.update({"_cam_post": _fake_cam_post, "_cam_local_ip": lambda ip, ch: "", "_CAM_9999_CLOSED": {}})
exec(grab("_cam_signal"), ns2)
_ans, _res = ns2["_cam_signal"]("crx", {"ip": "127.0.0.1", "type": "creality", "port": _closed_port}, "v=0\r\n", "")
check("15д. Creality на заводской прошивке: отказ службы при открытии камеры не запоминается",
      _ans is None and _res.get("service") is False and ns2["_CAM_9999_CLOSED"] == {} and _posts,
      (_res, ns2["_CAM_9999_CLOSED"]))
ns2["_cam_port"] = lambda port: _closed_port if int(port) == 9999 else int(port)   # чужой 9999 машины не трогаем
_ans, _res = ns2["_cam_signal"]("vx", {"ip": "127.0.0.1", "type": "klipper", "port": 7125}, "v=0\r\n", "")
check("15е. итог попытки говорит, дошло ли подключение до порта камеры (по нему диагностика отличает Voron)",
      _res.get("reached") is False and _res.get("tried"), _res)

print("")
print("--- 4. отчёт называет причину, а не просто «не работает» ---")
from app.diagnostics import diagnose  # noqa: E402

CTRL = {"reachable": True, "latency_ms": 12}


def cam_check(cam, lang="ru", p=None):
    rep = diagnose(p or P_K2, {}, 3, 0, None, {"control": CTRL, "file": None, "camera": cam}, lang=lang)
    got = [c for c in rep["checks"] if c["key"] == "camera"]
    return got[0] if got else None


c = cam_check({"webrtc_8000": {"reachable": True}})
check("16. КРИТИЧНО: открытый порт 8000 — ещё не «камера в порядке» (на прошивке 1.1.5.5 порт открыт, а видео нет): "
      "отчёт просит открыть камеру и повторить",
      c and c["status"] == "warn" and "не открывали" in c["value"] and "Откройте окно камеры" in (c["advice"] or ""), c)

c = cam_check({"webrtc_8000": {"reachable": False}, "alt_443": {"reachable": True},
               "service": {"reachable": True, "webrtc": 1, "fw": "1.1.6.7"},
               "signal": {"answered": True, "path": "https:443+token", "fw": "1.1.6.7", "tried": ["https:443+token=200"]}})
check("16а. камера по-настоящему ответила — зелено, с путём и версией прошивки",
      c and c["status"] == "ok" and "443" in c["value"] and "с токеном" in c["value"] and "прошивка 1.1.6.7" in c["value"], c)

c = cam_check({"webrtc_8000": {"reachable": True}, "signal": {"answered": True, "path": "http:8000 raw", "tried": []}})
check("16б. прежний путь (порт 8000, исходное предложение браузера) тоже называется прямо",
      c and c["status"] == "ok" and "8000" in c["value"] and "исходное предложение" in c["value"], c)

c = cam_check({"webrtc_8000": {"reachable": False}, "mjpeg_8080": {"ok": True}})
check("17. рабочий MJPEG — зелено", c and c["status"] == "ok" and "MJPEG" in c["value"], c)

c = cam_check({"webrtc_8000": {"reachable": False}, "moonraker": {"ok": True, "cams": 1}})
check("18. камера настроена, а поток молчит — внимание, а не отказ",
      c and c["status"] == "warn" and c["advice"], c)

c = cam_check({"webrtc_8000": {"reachable": True}, "alt_443": {"reachable": True}, "fluidd_page": {"ok": True},
               "service": {"reachable": True, "webrtc": 1, "fw": "1.1.5.5"},
               "signal": {"answered": False, "encrypted": True, "token": False, "fw": "1.1.5.5",
                          "tried": ["https:443=ConnectionRefusedError", "http:8000=200", "http:8000 raw=200", "http:80=404"]}})
check("19. камера не ответила на прошивке с защитой видео без токена — отказ с причиной и списком путей; "
      "версию прошивки отчёт называет сам, в поддержку не отсылает",
      c and c["status"] == "fail" and "токен" in (c["advice"] or "") and "https:443" in (c["advice"] or "")
      and "прошивка 1.1.5.5" in c["value"] and "поддержк" not in (c["advice"] or "").lower(), c)

c = cam_check({"webrtc_8000": {"reachable": True}, "service": {"reachable": False},
               "signal": {"answered": False, "encrypted": False, "token": False, "tried": ["http:8000=ReadTimeout"]}})
check("19а. камера не ответила по обычному пути — отказ, совет проверить камеру и прислать журнал",
      c and c["status"] == "fail" and "Скачать логи" in (c["advice"] or "") and "1.1.5.5" not in (c["advice"] or ""), c)

c = cam_check({"webrtc_8000": {"reachable": False}, "moonraker": {"ok": False},
               "alt_443": {"reachable": False}, "fluidd_page": {"ok": False}})
check("20. когда камеры нет вовсе — совет другой, без выдумок про прошивку",
      c and c["status"] == "fail" and "1.1.5.5" not in (c["advice"] or ""), c)

c_en = cam_check({"webrtc_8000": {"reachable": True}, "service": {"reachable": True, "webrtc": 1, "fw": "1.1.5.5"},
                  "signal": {"answered": False, "encrypted": True, "token": False, "tried": ["https:443=Timeout"]}}, lang="en")
check("21. английский текст говорит о том же",
      c_en and c_en["status"] == "fail" and "token" in (c_en["advice"] or "") and "firmware 1.1.5.5" in c_en["value"], c_en)

c = cam_check({"webrtc_8000": {"reachable": False}, "mjpeg_8080": {"ok": False},
               "service": {"reachable": True, "webrtc": 0, "fw": "V1.1.0.17"}})
check("21а. принтер сам сообщил «WebRTC нет», а MJPEG 8080 молчит — отказ с подсказкой про 8080",
      c and c["status"] == "fail" and "8080" in (c["advice"] or "") and "V1.1.0.17" in c["value"], c)

c = cam_check({"webrtc_8000": {"reachable": False}, "service": {"reachable": False},
               "info": {"ok": True, "wss_port": 443, "video_port": 443}})
check("21б. служба 9999 закрыта, а /info сообщает защищённый порт — отчёт называет безопасный режим",
      c and c["status"] == "warn" and "безопасный режим" in (c["advice"] or ""), c)

#  16.10.2026: Voron и другой Klipper без камеры WebRTC — окно камеры всё равно пробовало WebRTC, и попытка
#  кончилась отказом подключения. Это не довод «принтер не ответил на открытие камеры»: отчёт прежний.
P_VORON = {"id": "v24", "name": "Voron 2.4", "type": "klipper", "model": "Voron 2.4", "ip": "192.168.1.70", "port": 7125}
c = cam_check({"webrtc_8000": {"reachable": False}, "mjpeg_root": {"ok": False}, "mjpeg_8080": {"ok": False},
               "alt_443": {"reachable": False}, "fluidd_page": {"ok": True}, "moonraker": {"ok": True, "cams": 1},
               "service": {"reachable": False, "error": "ConnectionRefusedError"}, "info": {"ok": False},
               "signal": {"answered": False, "encrypted": False, "token": False, "service": False, "reached": False,
                          "tried": ["http:8000=ConnectionRefusedError"]}}, p=P_VORON)
check("21в. Voron: камера есть в Moonraker, поток молчит, а неудачная попытка WebRTC — лишь отказ подключения: "
      "«внимание» про Moonraker, а не «принтер не ответил»",
      c and c["status"] == "warn" and "Moonraker" in c["value"] and "не ответил" not in c["value"], c)
c = cam_check({"webrtc_8000": {"reachable": False}, "moonraker": {"ok": True, "cams": 1},
               "service": {"reachable": False},
               "signal": {"answered": False, "encrypted": False, "token": False, "service": False,
                          "tried": ["http:8000=404"]}}, p=P_VORON)
check("21г. порт камеры ответил (HTTP 404) — это уже попытка, о которой стоит сказать: отказ с перечнем путей",
      c and c["status"] == "fail" and "http:8000=404" in (c["advice"] or ""), c)

rep = diagnose(P_K2, {}, 3, 0, None, {"control": CTRL, "file": None}, lang="ru")
check("22. без пробы камеры проверка не появляется — обзор всего парка не тяжелеет",
      not [x for x in rep["checks"] if x["key"] == "camera"])

check("23. камеру пробует только отчёт по ОДНОМУ принтеру",
      SRC.count('"camera": _camera_probe(p)') == 1, SRC.count('"camera": _camera_probe(p)'))

#  16.10.2026 (R-146): у Creality на заводской прошивке файл уходит на порт 80 — строка в отчёте.
_crp = dict(P_CR)
_f_ok = [x for x in diagnose(_crp, {}, 3, 0, None, {"control": CTRL, "file": {"reachable": True}}, lang="ru")["checks"] if x["key"] == "file"]
_f_bad = [x for x in diagnose(_crp, {}, 3, 0, None, {"control": CTRL, "file": {"reachable": False}}, lang="en")["checks"] if x["key"] == "file"]
check("24. Creality на заводской прошивке: в отчёте есть «Загрузка файла (порт 80)» — доступен / недоступен с советом",
      _f_ok and _f_ok[0]["label"] == "Загрузка файла (порт 80)" and _f_ok[0]["status"] == "ok"
      and _f_bad and _f_bad[0]["status"] == "fail" and "80" in _f_bad[0]["label"] and _f_bad[0]["advice"], (_f_ok, _f_bad))

print("")
print("Итого: %d проверок, провалено %d" % (TOTAL, fail))
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
