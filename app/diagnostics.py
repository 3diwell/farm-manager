# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Диагностика связи с принтерами (Этап 1).
# Здесь только ЧИСТАЯ логика: лёгкая TCP-проба (доступность порта + задержка) и
# правила формирования отчёта/советов. Пассивные данные (статус, время последнего
# обновления, счётчик разрывов, коды ошибок) собирает сервер и передаёт сюда.
# Активная часть — только короткий TCP-connect (сотни байт). НИЧЕГО на принтер не пишет.
import socket
import time

# Пороги (мс / секунды / штуки)
LATENCY_WARN_MS = 150     # выше — сеть заметно подтормаживает
LATENCY_FAIL_MS = 600     # выше — сеть очень плохая
STALE_WARN_S = 20         # статус не обновлялся дольше — внимание
STALE_FAIL_S = 60         # дольше — связь, скорее всего, потеряна
RECONNECT_WARN = 3        # разрывов за сессию больше — нестабильно
HW_MIN_SAMPLES = 10       # столько замеров нужно, чтобы судить о «типичной» задержке (надёжность вывода)
HW_SLOW_MS = 350          # типичная (медианная) задержка выше — принтер отвечает медленно (вероятно слабее железо/Wi-Fi)


def tcp_probe(ip, port, timeout=2.0):
    """Короткий TCP-connect: доступность порта и задержка (мс). Данные не передаёт."""
    if not ip or not port:
        return {"reachable": False, "latency_ms": None, "error": "no_address"}
    t0 = time.perf_counter()
    try:
        s = socket.create_connection((str(ip), int(port)), timeout=timeout)
        s.close()
        return {"reachable": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "error": None}
    except Exception as e:
        return {"reachable": False, "latency_ms": None, "error": type(e).__name__}


def ports_for(printer):
    """Порты для проверки у принтера данного типа: (управляющий, файловый|None)."""
    t = (printer.get("type") or "bambu").lower()
    if t == "bambu":
        return 8883, 990            # MQTT (управление) + FTPS (загрузка файла)
    if t == "klipper":
        return int(printer.get("port") or 7125), None
    if t == "flashforge":
        return int(printer.get("port") or 8898), None
    if t == "creality":
        return int(printer.get("port") or 9999), 80   # 12.10.2026: служба Creality + приём файла печати
    p = printer.get("port")
    return (int(p) if p else None), None


def _worst(statuses):
    order = {"ok": 0, "warn": 1, "fail": 2}
    w = "ok"
    for s in statuses:
        if order.get(s, 0) > order.get(w, 0):
            w = s
    return w


def _t(lang, ru, en):
    """Двуязычная строка отчёта: en — для английского интерфейса, иначе ru."""
    return en if lang == "en" else ru


def _cam_path_text(sig, lang):
    """Каким путём открылась камера (итог printer_webrtc): «HTTPS, порт 443, с токеном» и т. п."""
    path = str(sig.get("path") or "")
    scheme, _, rest = path.partition(":")
    port = "".join(ch for ch in rest if ch.isdigit()) or "?"
    parts = [scheme.upper() or "HTTP", _t(lang, "порт %s" % port, "port %s" % port)]
    if "+token" in path:
        parts.append(_t(lang, "с токеном", "with token"))
    if path.endswith(" raw"):
        parts.append(_t(lang, "исходное предложение браузера", "browser's original offer"))
    return ", ".join(parts)


def diagnose(printer, state, last_seen_age, reconnects, mqtt_connected, probes, now=None, lang="ru"):
    """Отчёт по одному принтеру из пассивных данных + результатов проб.
    printer: dict с id,name,type,model,gen,serial,ip,port
    state: p_states[pid] или {}
    last_seen_age: секунд с последнего обновления статуса (None — ни разу)
    reconnects: счётчик разрывов связи
    mqtt_connected: bool|None (только для bambu)
    probes: {"control": tcp_probe(...), "file": tcp_probe(...)|None,
             "camera": результат пробы путей камеры|None — только в отчёте по одному принтеру}
    lang: 'ru'|'en' — язык текстов label/value/advice (структура и ключи не зависят от языка).
    Возвращает {pid,name,type,model,state,online,overall,checks:[...]}."""
    t = (printer.get("type") or "bambu").lower()
    checks = []
    ctrl = probes.get("control") or {}
    filep = probes.get("file")

    L_NET = _t(lang, "Сеть", "Network")
    L_NET_LAT = _t(lang, "Сеть (задержка)", "Network (latency)")

    # 1) Сеть: доступность управляющего порта + задержка
    if ctrl.get("reachable"):
        lat = ctrl.get("latency_ms")
        if lat is None:
            checks.append({"key": "network", "label": L_NET, "status": "ok", "value": _t(lang, "доступен", "reachable"), "advice": None})
        elif lat >= LATENCY_FAIL_MS:
            checks.append({"key": "network", "label": L_NET_LAT, "status": "fail", "value": _t(lang, "%.0f мс" % lat, "%.0f ms" % lat),
                           "advice": _t(lang, "Очень высокая задержка сети. Слабый сигнал Wi-Fi или перегруженная сеть — перенесите принтер ближе к роутеру или подключите по Ethernet.",
                                            "Very high network latency. A weak Wi-Fi signal or a congested network — move the printer closer to the router or connect it over Ethernet.")})
        elif lat >= LATENCY_WARN_MS:
            checks.append({"key": "network", "label": L_NET_LAT, "status": "warn", "value": _t(lang, "%.0f мс" % lat, "%.0f ms" % lat),
                           "advice": _t(lang, "Заметная задержка сети. Возможен слабый сигнал Wi-Fi — проверьте расположение принтера и роутера.",
                                            "Noticeable network latency. The Wi-Fi signal may be weak — check the placement of the printer and the router.")})
        elif ctrl.get("degraded"):
            checks.append({"key": "network", "label": L_NET_LAT, "status": "warn", "value": _t(lang, "%.0f мс" % lat, "%.0f ms" % lat),
                           "advice": _t(lang, "Задержка выросла относительно обычной для этого принтера — возможна перегрузка сети или слабеющий сигнал.",
                                            "Latency has risen above the usual level for this printer — possibly network congestion or a weakening signal.")})
        else:
            checks.append({"key": "network", "label": L_NET_LAT, "status": "ok", "value": _t(lang, "%.0f мс" % lat, "%.0f ms" % lat), "advice": None})
    else:
        checks.append({"key": "network", "label": L_NET, "status": "fail", "value": _t(lang, "недоступен", "unreachable"),
                       "advice": _t(lang, "Принтер не отвечает по сети. Проверьте, включён ли он, в той ли он сети и верен ли IP-адрес.",
                                        "The printer does not respond over the network. Check that it is powered on, is on the same network, and that the IP address is correct.")})

    L_MQTT = _t(lang, "MQTT (управление)", "MQTT (control)")
    # 2) Канал управления (MQTT у Bambu)
    if t == "bambu":
        if mqtt_connected:
            checks.append({"key": "control", "label": L_MQTT, "status": "ok", "value": _t(lang, "подключено", "connected"), "advice": None})
        elif ctrl.get("reachable"):
            checks.append({"key": "control", "label": L_MQTT, "status": "fail", "value": _t(lang, "нет сессии", "no session"),
                           "advice": _t(lang, "Порт открыт, но MQTT не подключается. Чаще всего неверный Access Code (токен) или принтер не в LAN-режиме. Проверьте токен и режим разработчика/LAN.",
                                            "The port is open, but MQTT does not connect. Most often the Access Code (token) is wrong or the printer is not in LAN mode. Check the token and the developer/LAN mode.")})
        else:
            checks.append({"key": "control", "label": L_MQTT, "status": "fail", "value": _t(lang, "нет связи", "no link"),
                           "advice": _t(lang, "Нет связи с принтером по каналу управления.", "No connection to the printer over the control channel.")})

    L_FILE = _t(lang, "Загрузка файла (FTPS)", "File upload (FTPS)")
    # 3) Канал загрузки файла (FTPS у Bambu)
    if t == "bambu" and filep is not None:
        if filep.get("reachable"):
            checks.append({"key": "file", "label": L_FILE, "status": "ok", "value": _t(lang, "доступен", "reachable"), "advice": None})
        else:
            checks.append({"key": "file", "label": L_FILE, "status": "fail", "value": _t(lang, "недоступен", "unreachable"),
                           "advice": _t(lang, "Порт загрузки файлов (FTPS 990) закрыт — отправка g-code на принтер невозможна. Проверьте сеть и прошивку принтера.",
                                            "The file upload port (FTPS 990) is closed — sending g-code to the printer is not possible. Check the network and the printer firmware.")})
    #  16.10.2026 (R-146): у Creality на заводской прошивке файл печати уходит на порт 80 — проба его уже
    #  делалась (ports_for), а строки в отчёте не было.
    if t == "creality" and filep is not None:
        L_FILE80 = _t(lang, "Загрузка файла (порт 80)", "File upload (port 80)")
        if filep.get("reachable"):
            checks.append({"key": "file", "label": L_FILE80, "status": "ok", "value": _t(lang, "доступен", "reachable"), "advice": None})
        else:
            checks.append({"key": "file", "label": L_FILE80, "status": "fail", "value": _t(lang, "недоступен", "unreachable"),
                           "advice": _t(lang, "Порт приёма файлов (80) закрыт — отправить файл печати на принтер нельзя. Проверьте сеть и что принтер включён.",
                                            "The file upload port (80) is closed — print files cannot be sent to the printer. Check the network and that the printer is on.")})

    #  3a) Камера (Klipper, Creality). Alpha 2.938: раньше отказ камеры не попадал в отчёт вовсе.
    #  16.10.2026 (R-062): «камера в порядке» — только если принтер действительно прислал ответ на
    #  попытку открыть камеру (итог последней попытки, signal) или отвечает поток MJPEG. Открытый
    #  TCP-порт 8000 доказательством больше не считается: на прошивке 1.1.5.5 он открыт, а видео нет.
    #  Версия прошивки берётся у самого принтера (служба 9999) — клиента о ней больше не спрашиваем.
    cam = probes.get("camera")
    if cam:
        L_CAM = _t(lang, "Камера", "Camera")
        sig = cam.get("signal") or {}
        svc = cam.get("service") or {}
        info = cam.get("info") or {}
        fw = str(svc.get("fw") or sig.get("fw") or "").strip()
        fw_txt = (_t(lang, "; прошивка %s", "; firmware %s") % fw) if fw else ""
        _mjpeg = next((k for k in ("mjpeg_root", "mjpeg_8080") if (cam.get(k) or {}).get("ok")), None)
        _cams = (cam.get("moonraker") or {}).get("cams")
        _port8000 = bool((cam.get("webrtc_8000") or {}).get("reachable"))
        _alt = bool((cam.get("alt_443") or {}).get("reachable"))
        _wrtc_flag = svc.get("webrtc")
        #  16.10.2026: окно камеры пробует WebRTC у любого Klipper, поэтому неудачная попытка есть и у Voron без
        #  камеры WebRTC. Её итог — довод, только если перед нами действительно камера Creality по WebRTC:
        #  тип 'creality', служба 9999 отвечает, прошивка сообщила признаки или шифрование, порт камеры
        #  принял подключение или открыт сейчас. Иначе отчёт идёт прежним путём (Moonraker, MJPEG).
        _sig_tried = [str(x) for x in (sig.get("tried") or [])]
        _sig_creality = bool(sig) and bool(
            t == "creality" or sig.get("reached") or sig.get("service") or sig.get("encrypted") or sig.get("token")
            or svc.get("reachable") or _wrtc_flag == 1 or _port8000
            or any(x.rpartition("=")[2].isdigit() for x in _sig_tried))
        _secure_hint = ""
        if not svc.get("reachable") and info.get("wss_port"):
            _secure_hint = _t(lang, " Служба Creality (порт 9999) не отвечает, а принтер сообщает защищённый порт %s — похоже, на нём включён безопасный режим Creality; его программа пока не поддерживает." % info.get("wss_port"),
                              " The Creality service (port 9999) does not answer while the printer reports secure port %s — the Creality secure mode seems to be on; the app does not support it yet." % info.get("wss_port"))
        if sig.get("answered"):
            checks.append({"key": "camera", "label": L_CAM, "status": "ok",
                           "value": _t(lang, "поток WebRTC открыт (%s)", "WebRTC stream opened (%s)") % _cam_path_text(sig, lang) + fw_txt,
                           "advice": None})
        elif _mjpeg:
            checks.append({"key": "camera", "label": L_CAM, "status": "ok",
                           "value": _t(lang, "поток MJPEG доступен", "MJPEG stream available") + fw_txt, "advice": None})
        elif _wrtc_flag == 0:
            checks.append({"key": "camera", "label": L_CAM, "status": "fail",
                           "value": _t(lang, "поток MJPEG не отвечает", "MJPEG stream does not answer") + fw_txt,
                           "advice": _t(lang, "Принтер сообщает, что камера у него без WebRTC, а поток MJPEG (порт 8080) не отвечает. Проверьте, подключена ли камера и включена ли она на экране принтера.",
                                              "The printer reports a camera without WebRTC, and the MJPEG stream (port 8080) does not answer. Check that the camera is connected and enabled on the printer screen.")})
        elif _sig_creality:
            _tried = ", ".join(sig.get("tried") or []) or "—"
            if sig.get("encrypted") and not sig.get("token"):
                _why = _t(lang, "Прошивка защищает видео токеном, а служба Creality (порт 9999) токен не выдала. Проверьте, что принтер в сети, и откройте камеру ещё раз.",
                          "The firmware protects video with a token, and the Creality service (port 9999) did not issue one. Check that the printer is online and open the camera again.")
            else:
                _why = _t(lang, "Проверьте, включена ли камера на экране принтера, и откройте окно камеры ещё раз. Если не поможет — пришлите журнал (Настройки → Система → Диагностика → «Скачать логи»).",
                          "Check that the camera is enabled on the printer screen and open the camera window again. If that does not help, send the log (Settings → System → Diagnostics → Download logs).")
            checks.append({"key": "camera", "label": L_CAM, "status": "fail",
                           "value": _t(lang, "принтер не ответил на открытие камеры", "the printer did not answer when the camera was opened") + fw_txt,
                           "advice": _t(lang, "Программа пробовала: %s. " % _tried, "The app tried: %s. " % _tried) + _why + _secure_hint})
        elif _wrtc_flag == 1 or _port8000 or _alt or info.get("video_port"):
            checks.append({"key": "camera", "label": L_CAM, "status": "warn",
                           "value": _t(lang, "камеру ещё не открывали", "the camera has not been opened yet") + fw_txt,
                           "advice": _t(lang, "Камера этого принтера работает по WebRTC: проверить её можно только настоящим подключением. Откройте окно камеры и повторите диагностику.",
                                              "This printer's camera uses WebRTC: it can only be checked by a real connection. Open the camera window and run the diagnostics again.") + _secure_hint})
        elif _cams:
            checks.append({"key": "camera", "label": L_CAM, "status": "warn",
                           "value": _t(lang, "Moonraker знает камеру, но поток не открылся",
                                             "Moonraker lists a camera, but the stream did not open") + fw_txt,
                           "advice": _t(lang, "Камера настроена в Moonraker, а её поток не отвечает. Проверьте, включена ли камера в интерфейсе принтера и не занята ли она другой программой.",
                                              "The camera is configured in Moonraker but its stream does not respond. Check that the camera is enabled in the printer interface and not held by another application.")})
        else:
            checks.append({"key": "camera", "label": L_CAM, "status": "fail",
                           "value": _t(lang, "поток не открывается", "stream does not open") + fw_txt,
                           "advice": _t(lang, "Программа не смогла получить видео. Ни один известный путь камеры не ответил. Проверьте, есть ли камера у этого принтера и включена ли она в его интерфейсе.",
                                              "The app could not obtain video. None of the known camera paths answered. Check whether this printer has a camera and whether it is enabled in the printer interface.") + _secure_hint})

    #  3б) Система подачи катушек (CFS у Creality K2). Alpha 2.942: раньше об этом узле в
    #  отчёте не было ни строчки, а именно он решает, с какой катушки списывать филамент.
    #  Данные берутся из уже собранного состояния принтера — лишних обращений к нему нет.
    trays = state.get("cfs_trays") or []
    if trays:
        L_CFS = _t(lang, "Система подачи (CFS)", "Filament system (CFS)")
        now = int(state.get("cfs_now", -1) or -1)
        cands = state.get("cfs_now_candidates") or []
        loaded = next((x for x in trays if int(x.get("index", -1)) == now), None)
        filled = [x for x in trays if (x.get("type") or "Empty") != "Empty"]
        spent = [x for x in trays if x.get("spent")]
        _lab = lambda xs: ", ".join(str(x.get("label") or x.get("index")) for x in xs)
        parts = [_t(lang, "слотов: %d, с филаментом: %d", "slots: %d, with filament: %d")
                 % (len(trays), len(filled))]
        if spent:
            parts.append(_t(lang,
                            "метка прежней катушки без филамента: %s",
                            "label of a previous spool with no filament: %s") % _lab(spent))
        if loaded is not None:
            parts.append(_t(lang, "заправлен %s (%s)", "loaded %s (%s)")
                         % (loaded.get("label") or now, loaded.get("type") or "?"))
            checks.append({"key": "cfs", "label": L_CFS, "status": "ok",
                           "value": "; ".join(parts), "advice": None})
        else:
            #  Списание филамента опирается на тот же вывод, поэтому молчание здесь стоит денег.
            if len(cands) > 1:
                names = _lab([x for x in trays if int(x.get("index", -1)) in cands])
                adv = _t(lang,
                         "Принтер сообщает материал заправленного, но не номер слота, а под описание подходит несколько: %s. Пока это так, филамент со слотов не списывается. Помогает разный материал или цвет в этих слотах." % names,
                         "The printer reports the loaded material but not the slot number, and several slots match: %s. While this holds, no filament is deducted. Different material or colour in those slots resolves it." % names)
            elif filled:
                adv = _t(lang,
                         "Материал, заправленный в голову, не совпал ни с одним слотом короба. Филамент не списывается. Проверьте, из короба ли идёт подача.",
                         "The material loaded in the head matches no slot in the box. No filament is deducted. Check whether feeding comes from the box at all.")
            else:
                adv = _t(lang,
                         "Ни в одном слоте короба нет филамента. Списывать не с чего.",
                         "No slot in the box holds filament. There is nothing to deduct from.")
            checks.append({"key": "cfs", "label": L_CFS, "status": "warn",
                           "value": "; ".join(parts + [_t(lang, "заправленный слот не определён",
                                                          "loaded slot not determined")]),
                           "advice": adv})

    L_FRESH = _t(lang, "Свежесть статуса", "Status freshness")
    # 4) Свежесть статуса
    p1_hint = _t(lang, " Для серии P1 укажите серийный номер — без него принтер не транслирует статус (нужен pushall).",
                       " For the P1 series, enter the serial number — without it the printer does not broadcast status (pushall is required).") if (t == "bambu" and not (printer.get("serial") or "").strip()) else ""
    if last_seen_age is None:
        checks.append({"key": "freshness", "label": L_FRESH, "status": "warn", "value": _t(lang, "нет данных", "no data"),
                       "advice": _t(lang, "Сервер ещё ни разу не получал статус от этого принтера.", "The server has not yet received any status from this printer.") + p1_hint})
    elif last_seen_age >= STALE_FAIL_S:
        checks.append({"key": "freshness", "label": L_FRESH, "status": "fail", "value": _t(lang, "%d с назад" % int(last_seen_age), "%d s ago" % int(last_seen_age)),
                       "advice": _t(lang, "Статус давно не обновлялся — связь, скорее всего, потеряна.", "Status has not updated for a long time — the connection is most likely lost.") + p1_hint})
    elif last_seen_age >= STALE_WARN_S:
        checks.append({"key": "freshness", "label": L_FRESH, "status": "warn", "value": _t(lang, "%d с назад" % int(last_seen_age), "%d s ago" % int(last_seen_age)),
                       "advice": _t(lang, "Статус обновляется редко — возможна нестабильная связь.", "Status updates rarely — the connection may be unstable.")})
    else:
        checks.append({"key": "freshness", "label": L_FRESH, "status": "ok", "value": _t(lang, "%d с назад" % int(last_seen_age), "%d s ago" % int(last_seen_age)), "advice": None})

    L_STAB = _t(lang, "Стабильность связи", "Connection stability")
    # 5) Стабильность связи (разрывы) — отслеживается у Bambu
    if t == "bambu":
        if reconnects and reconnects >= RECONNECT_WARN:
            checks.append({"key": "stability", "label": L_STAB, "status": "warn", "value": _t(lang, "%d разрывов" % reconnects, "%d drops" % reconnects),
                           "advice": _t(lang, "Частые переподключения за эту сессию — признак нестабильной сети или слабого сигнала.",
                                            "Frequent reconnects during this session — a sign of an unstable network or a weak signal.")})
        else:
            checks.append({"key": "stability", "label": L_STAB, "status": "ok",
                           "value": (_t(lang, "%d разрывов" % reconnects, "%d drops" % reconnects)) if reconnects else _t(lang, "стабильно", "stable"), "advice": None})

    L_ERR = _t(lang, "Ошибки принтера", "Printer errors")
    # 6) Ошибки: показываем ТОЛЬКО то, что реально сообщает принтер, без нашей трактовки.
    status = (state.get("status") or "").upper()
    kmsg = (state.get("err_msg") or "").strip() if t == "klipper" else ""
    if kmsg:
        checks.append({"key": "errors", "label": L_ERR, "status": "fail", "value": _t(lang, "ошибка", "error"),
                       "advice": _t(lang, "Сообщение Klipper: ", "Klipper message: ") + kmsg})
    elif status == "FAILED":
        checks.append({"key": "errors", "label": L_ERR, "status": "warn", "value": _t(lang, "сбой печати", "print failure"),
                       "advice": _t(lang, "Последняя печать завершилась сбоем. Откройте панель принтера и проверьте сообщение.",
                                        "The last print failed. Open the printer panel and check the message.")})
    else:
        checks.append({"key": "errors", "label": L_ERR, "status": "ok", "value": _t(lang, "нет", "none"), "advice": None})

    # 7) Схема пути печати (информативно; частая причина 0500-4002)
    if t == "bambu":
        gen = (printer.get("gen") or "auto").lower()
        gen_label = {"auto": _t(lang, "авто", "auto"), "ftp": "FTP", "new": "New", "old": "Old"}.get(gen, gen)
        checks.append({"key": "path", "label": _t(lang, "Схема пути печати", "Print path scheme"), "status": "ok", "value": gen_label,
                       "advice": None if gen == "auto" else _t(lang, "Схема выбрана вручную. Если печать не стартует с ошибкой 0500-4002 — для P2S/H2S нужен FTP, для H2D — New, для X1/P1 — Old, либо верните «авто».",
                                                                     "The scheme is selected manually. If printing does not start with error 0500-4002 — use FTP for P2S/H2S, New for H2D, Old for X1/P1, or switch back to auto.")})

    # 8) Отзывчивость / класс «железа»
    base = ctrl.get("base_ms")
    samples = ctrl.get("samples") or 0
    if base is not None and samples >= HW_MIN_SAMPLES and ctrl.get("reachable") and base >= HW_SLOW_MS:
        checks.append({"key": "hardware", "label": _t(lang, "Отзывчивость (железо)", "Responsiveness (hardware)"), "status": "warn", "value": _t(lang, "медленно, ~%.0f мс" % base, "slow, ~%.0f ms" % base),
                       "advice": _t(lang, "Принтер стабильно отвечает медленно (высокая типичная задержка). Вероятно слабее сетевой модуль или процессор — при операциях с ним возможны заметные задержки перед откликом. Это особенность принтера, а не сбой связи.",
                                        "The printer consistently responds slowly (high typical latency). Its network module or processor is probably weaker — operations with it may have noticeable delays before responding. This is a characteristic of the printer, not a connection failure.")})

    online = (last_seen_age is not None and last_seen_age < STALE_FAIL_S) and bool(ctrl.get("reachable"))
    overall = _worst([c["status"] for c in checks])
    return {
        "pid": printer.get("id"),
        "name": printer.get("name") or printer.get("id"),
        "type": t,
        "model": printer.get("model") or "",
        "state": state.get("status") or "—",
        "online": bool(online),
        "overall": overall,
        "checks": checks,
    }
