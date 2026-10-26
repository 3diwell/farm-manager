# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""12.10.2026 — разбор чужого MJPEG-потока (multipart/x-mixed-replace) на целые кадры JPEG.

ЗАЧЕМ. Камеру FlashForge Adventurer 5M Pro отдаёт стример самого принтера
(http://<адрес>:8080/?action=stream, mjpg-streamer). Чтобы на принтер шло ОДНО соединение, сколько
бы окон камеры ни открыли в программе, поток читает один владелец (app/camera_hub.py) и раздаёт
зрителям последний кадр. Владельцу нужны целые кадры — их и выделяет этот модуль.

КАК. Каждая часть потока: заголовки (обычно с Content-Length), пустая строка, байты JPEG. Если длина
названа — берём ровно столько байт от начала JPEG (метка FF D8). Если нет — до метки конца JPEG
(FF D9). Размер кадра и буфера ограничен: битый или чужой поток не съест память.

Модуль не знает ни про сеть, ни про адреса — только байты, поэтому проверяется без принтера.
"""
import re

__all__ = ["MjpegSplitter", "browser_part", "MAX_FRAME_BYTES"]

MAX_FRAME_BYTES = 8 * 1024 * 1024      # кадр камеры принтера — десятки-сотни КБ; 8 МБ — с большим запасом
_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"
_LEN_RE = re.compile(rb"content-length\s*:\s*(\d+)", re.I)
_HEADER_KEEP = 4096                     # заголовки одной части — сотня байт; больше без кадра — мусор


class MjpegSplitter(object):
    """feed(байты) -> список целых кадров JPEG, пришедших к этому моменту."""

    def __init__(self, max_frame=MAX_FRAME_BYTES):
        self._buf = bytearray()
        self._max = int(max_frame)

    def feed(self, data):
        if data:
            self._buf += data
        out = []
        while True:
            soi = self._buf.find(_SOI)
            if soi < 0:
                # Начала кадра ещё нет. Хвост держим: в нём заголовки части (Content-Length) и, быть может,
                # половина метки FF D8. Сбрасываем только явный мусор сверх предела заголовков.
                if len(self._buf) > _HEADER_KEEP:
                    del self._buf[:-_HEADER_KEEP]
                break
            n = None
            hdr = bytes(self._buf[:soi])
            found = _LEN_RE.findall(hdr)
            if found:
                n = int(found[-1])
                if n < 4 or n > self._max:
                    n = None
            if n is not None:
                if len(self._buf) < soi + n:
                    break                          # кадр ещё не дочитан
                frame = bytes(self._buf[soi:soi + n])
                del self._buf[:soi + n]
            else:
                eoi = self._buf.find(_EOI, soi + 2)
                if eoi < 0:
                    if len(self._buf) - soi > self._max:
                        del self._buf[:soi + 2]    # конца нет слишком долго — это не кадр, ищем дальше
                        continue
                    break
                frame = bytes(self._buf[soi:eoi + 2])
                del self._buf[:eoi + 2]
            out.append(frame)
        return out


def browser_part(jpeg):
    """Часть потока для браузера — тот же вид, что у камер Bambu (граница «frame»)."""
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
