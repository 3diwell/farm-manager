# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Порт программы, заданный в установщике (17.09.2026).

ЗАЧЕМ. Слово владельца: «в процессе установки нужно добавить опцию выбора порта вручную, а также
автоматическую опцию, при которой установщик проверит, занят ли 8000-й порт, и если да — подберёт
в автоматическом режиме другой свободный порт, чтобы программа после установки заработала».

ПОЧЕМУ ЭТО ДЕЛАЕТ ПРОГРАММА, А НЕ САМ УСТАНОВЩИК. Порт живёт в config.json в папке данных
ПОЛЬЗОВАТЕЛЯ (на Windows — LOCALAPPDATA/3DIWELL). Установщик работает с правами администратора,
и его представление о папке пользователя может отличаться от настоящего; кроме того, в config.json
уже могут лежать другие настройки (своя папка данных, доступ по сети), и переписывать этот файл
чужим кодом нельзя. Поэтому установщик лишь ЗАПУСКАЕТ саму программу одной командой ОТ ИМЕНИ
ПОЛЬЗОВАТЕЛЯ:

    "3DIWELL Farm Manager.exe" --fm-apply-port auto --fm-port-out <файл>

Программа сама проверяет занятость честным пробным bind (app/server_port_config.py), сама
атомарно пишет config.json, сохраняя все остальные поля, и сообщает выбранный порт установщику
через файл — чтобы тот открыл в брандмауэре ИМЕННО его.

ГРАНИЦЫ. Модуль чистый: только стандартная библиотека и app/server_port_config.py. Ни FastAPI,
ни баз, ни сети, ни принтеров. Ветка в server.py стоит САМОЙ РАННЕЙ — до замка одиночного
экземпляра и до открытия любой базы, поэтому команда безопасна при работающей программе.
Битый config.json НЕ перезаписывается: лучше отказать, чем потерять чужие настройки.
"""
import io
import json
import os

from app import server_port_config as spc

AUTO = "auto"
SCAN_LIMIT = 100          # сколько портов подряд смотреть в автоматическом режиме

REASON_NO_FREE = "no_free_port"
REASON_WRITE = "write_failed"
REASON_CONFIG = "config_unreadable"
REASON_EMPTY = "empty"


def default_data_dir(env=None):
    """Папка данных по умолчанию — ТА ЖЕ, что у программы (server.py, _default_data_dir).
    Расхождение здесь означало бы, что установщик пишет порт мимо настоящего config.json."""
    env = os.environ if env is None else env
    if os.name == "nt":
        base = env.get("LOCALAPPDATA") or env.get("APPDATA")
    else:
        base = env.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    if base:
        return os.path.join(base, "3DIWELL")
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path(env=None):
    return os.path.join(default_data_dir(env), "config.json")


def read_config(path):
    """-> (настройки, можно ли писать). Файла нет — пустые настройки и «можно».
    Файл есть, но не читается — «нельзя»: чужие настройки дороже нашего порта."""
    if not os.path.isfile(path):
        return ({}, True)
    try:
        with io.open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ({}, False)
    return (data, True) if isinstance(data, dict) else ({}, False)


def is_port_free(port):
    """Честная проверка занятости порта пробным bind (реализация — server_port_config)."""
    ok, _ = spc.check_port_availability(port, lan_enabled=False)
    return bool(ok)


def pick_port(desired, is_free, scan_limit=SCAN_LIMIT):
    """Свободный порт, начиная с желаемого и далее по возрастанию.
    -> (порт, "") либо (None, причина). Выше 65535 не поднимаемся."""
    try:
        start = int(desired)
    except Exception:
        return (None, spc.REASON_NOT_INT)
    for i in range(max(0, int(scan_limit)) + 1):
        cand = start + i
        if cand > spc.PORT_MAX:
            break
        if is_free(cand):
            return (cand, "")
    return (None, REASON_NO_FREE)


def apply_choice(value, env=None, is_free=None, scan_limit=SCAN_LIMIT, writer=None):
    """'auto' — подобрать свободный начиная с 8000; число — взять ровно его (его уже проверил
    установщик на своей странице). Порт пишется как РАБОЧИЙ: незавершённых переходов у свежей
    установки нет, поэтому pending/previous очищаются.
    -> (порт, "") либо (None, причина)."""
    free = is_free or is_port_free
    if str(value if value is not None else "").strip() == "":
        return (None, REASON_EMPTY)
    if str(value).strip().lower() == AUTO:
        port, reason = pick_port(spc.DEFAULT_PORT, free, scan_limit)
    else:
        port, reason = spc.validate_server_port(value)
    if port is None:
        return (None, reason)
    path = config_path(env)
    cfg, ok = read_config(path)
    if not ok:
        return (None, REASON_CONFIG)
    cfg[spc.KEY_ACTIVE] = port
    cfg[spc.KEY_PENDING] = None
    cfg[spc.KEY_PREVIOUS] = None
    write = writer or spc.atomic_write_json
    try:
        if not write(path, cfg):
            return (None, REASON_WRITE)
    except Exception:
        return (None, REASON_WRITE)
    return (port, "")


def parse_args(argv):
    """--fm-apply-port <auto|номер> [--fm-port-out <файл>]; допускается и форма с '='.
    -> (значение|None, файл|None)."""
    value, out = None, None
    args = [str(a) for a in (argv or [])]
    for i, a in enumerate(args):
        if a == "--fm-apply-port" and i + 1 < len(args):
            value = args[i + 1]
        elif a.startswith("--fm-apply-port="):
            value = a.split("=", 1)[1]
        elif a == "--fm-port-out" and i + 1 < len(args):
            out = args[i + 1]
        elif a.startswith("--fm-port-out="):
            out = a.split("=", 1)[1]
    return (value, out)


def requested(argv):
    """Просят ли нас задать порт (по этому признаку server.py уходит в раннюю ветку)."""
    return any(str(a).startswith("--fm-apply-port") for a in (argv or []))


def main(argv, env=None, is_free=None, writer=None):
    """0 — порт записан; 1 — не удалось; 2 — команда без значения."""
    value, out = parse_args(argv)
    if not value:
        print("fm-apply-port: не задано значение (auto или номер порта)")
        return 2
    port, reason = apply_choice(value, env=env, is_free=is_free, writer=writer)
    if port is None:
        print("fm-apply-port: порт не задан (%s)" % reason)
        return 1
    if out:
        try:
            with io.open(out, "w", encoding="ascii") as f:
                f.write(str(port))
        except Exception:
            pass          # установщик переживёт: для брандмауэра у него есть значение по умолчанию
    print("fm-apply-port: %d" % port)
    return 0
