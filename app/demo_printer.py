# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Виртуальный принтер (тип "demo") — Alpha 2.970, заказ владельца.

ЗАЧЕМ. Владельцу нужен принтер, на котором можно ПО-НАСТОЯЩЕМУ запускать файлы и смотреть,
что делает программа: какие окна всплывают, как считается количество в задачах и проектах,
как ведут себя очередь, склад, панель отправок. Занимать ради этого настоящий принтер нельзя,
а без принтера половину пути не проверить вовсе.

ГЛАВНЫЙ ПРИНЦИП: виртуальный принтер НИЧЕГО НЕ СЧИТАЕТ САМ и не обходит механизмы программы.
Он делает ровно то же, что делает адаптер настоящего принтера: сообщает своё состояние. Всё
остальное — списание количества в задачах, закрытие детали в проекте, журнал качества, склад,
очередь — выполняет тот же код ядра, что и для Bambu, Klipper и FlashForge. Именно поэтому
проверка на нём проверяет НАСТОЯЩИЕ механизмы, а не их подобие.

ЧТО ОН ДЕЛАЕТ (сроки заданы владельцем):
    10 секунд греет стол   -> PREPARE, температура стола ползёт к цели
    10 секунд греет сопло  -> PREPARE, температура сопла ползёт к цели
    20 секунд печатает     -> RUNNING, проценты идут от 0 до 100
    дальше                 -> FINISH и остывание, как у настоящего принтера с готовой печатью.

ОТКУДА ЦЕЛИ НАГРЕВА, по порядку:
    1) из самого файла — обычный текстовый g-code читается, ищутся M140/M190 (стол)
       и M104/M109 (сопло);
    2) из того, что задано руками на пульте;
    3) значения по умолчанию (60 и 220) — и это честно названо в журнале.
Упакованный .3mf не разбирается: угадывать его содержимое мы не будем.

ЧЕГО ЗДЕСЬ НЕТ: сети. Виртуальный принтер не открывает ни одного соединения, у него нет ни
адреса, ни порта, ни кода доступа. Этот файл не импортирует ни socket, ни urllib.

Модуль чистый: наружу отдаёт только словари состояния. Часы передаются аргументом, поэтому
поведение проверяется без ожидания в реальном времени.
"""

import os
import re
import threading

# ── Сроки и температуры ────────────────────────────────────────────────────────────────
BED_S = 10.0                # столько греется стол
NOZZLE_S = 10.0             # столько греется сопло
PRINT_S = 20.0              # столько идёт печать
COOL_S = 30.0               # столько остывает после печати
TOTAL_S = BED_S + NOZZLE_S + PRINT_S

AMBIENT_C = 25              # комнатная температура, от неё начинается нагрев
BED_DEFAULT_C = 60          # если цель не нашлась ни в файле, ни на пульте
NOZZLE_DEFAULT_C = 220
BED_MAX_C = 120             # выше этого значение из файла считаем мусором
NOZZLE_MAX_C = 350

# Строки g-code, задающие нагрев. Ищем и «задать», и «задать и ждать»:
#   стол  — M140 (задать), M190 (задать и ждать)
#   сопло — M104 (задать), M109 (задать и ждать)
_BED_RE = re.compile(rb"^\s*M1(?:40|90)\b[^\n]*?\bS(\d{1,3})", re.M)
_NOZ_RE = re.compile(rb"^\s*M10(?:4|9)\b[^\n]*?\bS(\d{1,3})", re.M)
_HEAD_BYTES = 524288        # преамбулы g-code хватает; весь файл читать незачем

_lock = threading.RLock()
_files = {}                 # pid -> [имена файлов, «лежащих» на принтере]
_jobs = {}                  # pid -> состояние текущей печати
_targets = {}               # pid -> {"bed": int, "nozzle": int} — заданное руками на пульте


def temps_from_file(fdata):
    """Цели нагрева из самого файла. -> (bed|None, nozzle|None).

    Читается только обычный текстовый g-code и только начало файла. Упакованный .3mf
    (он начинается с сигнатуры zip) не разбирается: там значений в открытом виде нет,
    а выдумывать их запрещено правилами проекта."""
    try:
        head = (fdata or b"")[:_HEAD_BYTES]
        if head[:2] == b"PK":
            return (None, None)
        b = _BED_RE.search(head)
        n = _NOZ_RE.search(head)
        _b = int(b.group(1)) if b else None
        _n = int(n.group(1)) if n else None
        return (_b if (_b and 0 < _b <= BED_MAX_C) else None,
                _n if (_n and 0 < _n <= NOZZLE_MAX_C) else None)
    except Exception:
        return (None, None)


_FILE_DATA = {}     # (pid, fname) -> bytes: начало и конец файла, где слайсеры пишут вес филамента
_KEEP = 262144      # хватает и заголовку Bambu/Orca, и хвосту PrusaSlicer


def remember(pid, fname, fdata):
    """2.977 (R-095): запомнить кусок файла, по которому склад считает вес. Целиком файлы не
    держим — только начало и конец, там и живут комментарии «filament used [g]»."""
    if not fdata:
        return
    b = bytes(fdata)
    if len(b) > 2 * _KEEP:
        b = b[:_KEEP] + b"\n" + b[-_KEEP:]
    _FILE_DATA[(str(pid), str(fname))] = b


def file_data(pid, fname):
    """Запомненный кусок файла или b"" — если файл на принтер клали не через программу."""
    return _FILE_DATA.get((str(pid), str(fname)), b"")


def add_file(pid, fname):
    """Запомнить файл как лежащий «на принтере» (список для выпадашки выбора файла)."""
    with _lock:
        lst = _files.setdefault(pid, [])
        if fname and fname not in lst:
            lst.append(fname)


def files(pid):
    with _lock:
        return list(_files.get(pid, []))


def start(pid, fname, fdata, now):
    """Начать печать. Возвращает (bed, nozzle, откуда) — для журнала.

    Ничего не считает и никого не уведомляет: количество засчитывает ядро на переходе
    в FINISH, тем же кодом, что и для настоящих принтеров."""
    bed_f, noz_f = temps_from_file(fdata)
    with _lock:
        man = dict(_targets.get(pid) or {})
        bed = int(bed_f or man.get("bed") or BED_DEFAULT_C)
        noz = int(noz_f or man.get("nozzle") or NOZZLE_DEFAULT_C)
        src = "файл" if (bed_f or noz_f) else ("пульт" if man else "по умолчанию")
        _jobs[pid] = {"file": os.path.basename(str(fname or "")), "t0": float(now),
                      "bed": bed, "noz": noz, "paused_at": None, "paused_s": 0.0,
                      "ended": None, "ended_at": None, "src": src}
    return (bed, noz, src)


def pause(pid, on, now):
    """Пауза и продолжение. На паузе часы задания стоят — как у настоящего принтера."""
    with _lock:
        j = _jobs.get(pid)
        if not j or j["ended"]:
            return False
        if on and j["paused_at"] is None:
            j["paused_at"] = float(now)
        elif not on and j["paused_at"] is not None:
            j["paused_s"] += float(now) - j["paused_at"]
            j["paused_at"] = None
        else:
            return False
        return True


def stop(pid, now):
    """Остановка: задание закончилось ничем, принтер остывает и снова свободен."""
    with _lock:
        j = _jobs.get(pid)
        if not j or j["ended"]:
            return False
        j["ended"], j["ended_at"] = "cancel", float(now)
        return True


def set_target(pid, what, temp_c):
    """Ручная установка температуры с пульта. Влияет на СЛЕДУЮЩУЮ печать; идущую не трогаем,
    чтобы цифры на экране не расходились с тем, что человек уже видит."""
    if what not in ("bed", "nozzle", "chamber"):
        return False
    with _lock:
        _targets.setdefault(pid, {})[what] = int(temp_c or 0)
        return True


def forget(pid):
    """Убрать всё, что помнили о принтере (его удалили из фермы)."""
    with _lock:
        _files.pop(pid, None)
        _jobs.pop(pid, None)
        _targets.pop(pid, None)


def _ramp(a_c, b_c, part):
    """Линейный переход температуры от a к b. part — доля пути, 0..1."""
    part = max(0.0, min(1.0, part))
    return round(a_c + (b_c - a_c) * part, 1)


def _ceil_min(seconds):
    """Секунды -> минуты вверх. Поле remaining_time во всей программе в МИНУТАХ, и
    двадцатисекундная печать не должна показывать ноль всё время, пока идёт."""
    s = max(0.0, float(seconds))
    return int(s // 60 + (1 if s % 60 else 0))


def state(pid, now):
    """Состояние принтера СЕЙЧАС — в том же виде, в каком его отдают настоящие адаптеры.
    Ничего не пишет, только считает по часам."""
    with _lock:
        j = dict(_jobs.get(pid) or {})
        man = dict(_targets.get(pid) or {})
    st = {"status": "IDLE", "status_raw": "idle", "percent": 0, "remaining_time": 0,
          "file_name": "", "total_time": 0, "nozzle_count": 1,
          "nozzle_temp": AMBIENT_C, "bed_temp": AMBIENT_C,
          "nozzle_target": int(man.get("nozzle") or 0), "bed_target": int(man.get("bed") or 0),
          #  R-104: у виртуального принтера камера есть — чтобы функцию можно было проверить без
          #  настоящего. Греется «мгновенно»: это стенд, а не физика.
          "chamber_heater": True,
          "chamber_target": int(man.get("chamber") or 0),
          "chamber_temp": (int(man.get("chamber") or 0) if int(man.get("chamber") or 0) > 0 else AMBIENT_C)}
    if not j:
        return st

    bed, noz = j["bed"], j["noz"]
    if j["paused_at"] is not None:
        el = j["paused_at"] - j["t0"] - j["paused_s"]
    else:
        el = float(now) - j["t0"] - j["paused_s"]
    el = max(0.0, el)
    st["file_name"] = j["file"]
    st["total_time"] = int(TOTAL_S)

    if j["ended"] == "cancel":
        cool = (float(now) - (j["ended_at"] or now)) / COOL_S
        st.update({"status": "IDLE", "status_raw": "cancelled", "percent": 0,
                   "file_name": "", "total_time": 0,
                   "bed_temp": _ramp(bed, AMBIENT_C, cool),
                   "nozzle_temp": _ramp(noz, AMBIENT_C, cool),
                   "bed_target": 0, "nozzle_target": 0})
        return st

    if el < BED_S:                                        # 1) греется стол
        st.update({"status": "PREPARE", "status_raw": "heating_bed",
                   "bed_temp": _ramp(AMBIENT_C, bed, el / BED_S), "nozzle_temp": AMBIENT_C,
                   "bed_target": bed, "nozzle_target": 0,
                   "remaining_time": _ceil_min(TOTAL_S - el)})
    elif el < BED_S + NOZZLE_S:                           # 2) греется сопло
        st.update({"status": "PREPARE", "status_raw": "heating_nozzle",
                   "bed_temp": bed,
                   "nozzle_temp": _ramp(AMBIENT_C, noz, (el - BED_S) / NOZZLE_S),
                   "bed_target": bed, "nozzle_target": noz,
                   "remaining_time": _ceil_min(TOTAL_S - el)})
    elif el < TOTAL_S:                                    # 3) печатает
        done = (el - BED_S - NOZZLE_S) / PRINT_S
        st.update({"status": "RUNNING", "status_raw": "printing",
                   "percent": int(min(99, done * 100)),
                   "bed_temp": bed, "nozzle_temp": noz,
                   "bed_target": bed, "nozzle_target": noz,
                   "remaining_time": _ceil_min(TOTAL_S - el)})
    else:                                                 # 4) готово, остывает
        st.update({"status": "FINISH", "status_raw": "finish", "percent": 100,
                   "remaining_time": 0,
                   "bed_temp": _ramp(bed, AMBIENT_C, (el - TOTAL_S) / COOL_S),
                   "nozzle_temp": _ramp(noz, AMBIENT_C, (el - TOTAL_S) / COOL_S),
                   "bed_target": 0, "nozzle_target": 0})

    if j["paused_at"] is not None and st["status"] in ("PREPARE", "RUNNING"):
        st["status"], st["status_raw"] = "PAUSED", "paused"
    return st
