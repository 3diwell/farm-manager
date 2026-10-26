# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — контракт серверного порта (Alpha 2.806).

ТОЛЬКО стандартная библиотека, БЕЗ импорта server.py/FastAPI/БД. Чистые функции над
dict конфигурации + атомарная запись JSON + честная проверка занятости порта.
Всё тестируется offline (socket подменяется фабрикой).

КОНТРАКТ ПОЛЕЙ config.json (существующие поля сохраняются, схема БД не участвует):
  server_port          — подтверждённый РАБОЧИЙ порт (default 8000);
  pending_server_port  — новый порт, ожидающий применения при следующем запуске;
  previous_server_port — прежний рабочий порт ТОЛЬКО на период переключения (rollback).

ГЛАВНОЕ ПРАВИЛО: pending становится server_port ТОЛЬКО после фактически успешного
bind (подтверждение выполняет вызывающая сторона после старта listener). Неудачный
bind возвращает предыдущий рабочий порт и восстанавливает config.
"""

import json
import os
import re
import socket

DEFAULT_PORT = 8000
PORT_MIN = 1024
PORT_MAX = 65535

KEY_ACTIVE = "server_port"
KEY_PENDING = "pending_server_port"
KEY_PREVIOUS = "previous_server_port"

# Причины отказа валидации (машинные коды; тексты пользователю — на стороне UI).
REASON_EMPTY = "empty"
REASON_NOT_INT = "not_integer"
REASON_RANGE = "out_of_range"


def validate_server_port(value):
    """Строгая валидация пользовательского ввода порта.
    -> (port:int, "") либо (None, reason).
    Разрешено: целое 1024–65535; пробелы ТОЛЬКО по краям строки.
    Запрещено: пусто, не-число, 0/отрицательные/дробные, hex/octal (в т.ч. '0x1F90',
    '0o17320', ведущие '+'), 'host:port', URL, пробелы внутри числа."""
    if value is None:
        return (None, REASON_EMPTY)
    if isinstance(value, bool):                      # bool — подкласс int, но портом не является
        return (None, REASON_NOT_INT)
    if isinstance(value, int):
        port = value
    elif isinstance(value, float):
        return (None, REASON_NOT_INT)                # дробные запрещены (даже 8000.0)
    else:
        s = str(value).strip()                       # пробелы допустимы только по краям
        if s == "":
            return (None, REASON_EMPTY)
        if not re.fullmatch(r"[0-9]+", s):           # только десятичные цифры: отсекает hex/octal/
            return (None, REASON_NOT_INT)            # 'host:port'/URL/минус/плюс/пробелы внутри
        if len(s) > 1 and s[0] == "0":
            return (None, REASON_NOT_INT)            # '0800' читалось бы как octal-запись — отклоняем
        port = int(s, 10)
    if not (PORT_MIN <= port <= PORT_MAX):
        return (None, REASON_RANGE)
    return (port, "")


def read_port_state(cfg):
    """Состояние портов из dict конфигурации (отсутствующие/битые значения — безопасные
    default'ы; обратная совместимость со старым config без ключей порта).
    -> {"active": int, "pending": int|None, "previous": int|None}."""
    cfg = cfg or {}

    def _clean(key, fallback=None):
        p, err = validate_server_port(cfg.get(key))
        return p if not err else fallback

    return {"active": _clean(KEY_ACTIVE, DEFAULT_PORT) or DEFAULT_PORT,
            "pending": _clean(KEY_PENDING),
            "previous": _clean(KEY_PREVIOUS)}


def plan_change(cfg, new_port):
    """Записать в dict намерение сменить порт: pending + previous. Вызывается ТОЛЬКО после
    успешной валидации и проверки занятости. No-op (new == active, pending нет) возвращает
    False и НИЧЕГО не меняет. Неизвестные поля cfg не трогаются."""
    state = read_port_state(cfg)
    if int(new_port) == state["active"] and state["pending"] is None:
        return False
    cfg[KEY_PENDING] = int(new_port)
    cfg[KEY_PREVIOUS] = state["active"]
    return True


def commit_pending(cfg):
    """Pending подтверждён ФАКТИЧЕСКИ успешным bind: становится рабочим портом, поля
    переключения очищаются. -> подтверждённый порт либо None (pending не было)."""
    state = read_port_state(cfg)
    if state["pending"] is None:
        return None
    cfg[KEY_ACTIVE] = state["pending"]
    cfg.pop(KEY_PENDING, None)
    cfg.pop(KEY_PREVIOUS, None)
    return state["pending"]


def rollback_pending(cfg):
    """Bind pending-порта не удался: вернуться к прежнему рабочему порту, очистить поля
    переключения. -> порт, на котором продолжаем работать."""
    state = read_port_state(cfg)
    keep = state["previous"] if state["previous"] is not None else state["active"]
    cfg[KEY_ACTIVE] = keep
    cfg.pop(KEY_PENDING, None)
    cfg.pop(KEY_PREVIOUS, None)
    return keep


def atomic_write_json(path, cfg):
    """Атомарная запись JSON: временный файл в ТОЙ ЖЕ папке -> flush -> fsync ->
    os.replace. При любой ошибке исходный файл остаётся нетронутым. -> bool."""
    tmp = str(path) + ".tmp"
    try:
        d = os.path.dirname(str(path))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg or {}, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


def check_port_availability(port, lan_enabled, sock_factory=None, current_port=None):
    """Честная проверка занятости порта РЕАЛЬНЫМ пробным bind (затем socket закрывается).

    * bind-хост соответствует текущему режиму: LAN OFF -> 127.0.0.1, LAN ON -> 0.0.0.0;
    * НИКАКИХ reuse-опций (SO_REUSEADDR на Windows замаскировал бы настоящий конфликт,
      SO_REUSEPORT не используется вовсе) — конфликт должен быть виден честно;
    * bounded timeout, сканирования сети нет;
    * текущий АКТИВНЫЙ порт (no-op пользователя) конфликтом не считается — на нём слушаем мы;
    * предварительная проверка не абсолютна: окончательная — production bind при старте.
    -> (True, "") либо (False, "busy"|"bind_failed")."""
    p = int(port)
    if current_port is not None and p == int(current_port):
        return (True, "")
    factory = sock_factory or socket.socket
    host = "0.0.0.0" if lan_enabled else "127.0.0.1"
    s = None
    try:
        s = factory(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(1.0)
        except Exception:
            pass
        s.bind((host, p))
        return (True, "")
    except OSError:
        return (False, "busy")
    except Exception:
        return (False, "bind_failed")
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass


def startup_plan(cfg):
    """Порядок портов для запуска listener'а (ЭТАП 6): pending первым (если есть), затем
    рабочий. -> список кандидатов без дубликатов, длиной 1 или 2."""
    state = read_port_state(cfg)
    plan = []
    if state["pending"] is not None:
        plan.append(state["pending"])
    fallback = state["previous"] if state["previous"] is not None else state["active"]
    if fallback not in plan:
        plan.append(fallback)
    if state["active"] not in plan:
        plan.append(state["active"])
    return plan
