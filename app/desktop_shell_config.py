# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — конфигурация desktop-оболочки (Alpha 2.805).

ТОЛЬКО стандартная библиотека, БЕЗ импорта server.py, pywebview, FastAPI и БД.
Чистая логика: разбор аргументов, пути хранилища оболочки, состояние окна,
клиентская конфигурация, редактирование URL для журнала. Всё тестируется offline.

ГРАНИЦЫ. Оболочка НЕ хранит пароли/токены/cookies (cookies живут только в профиле
WebView2), НЕ пишет в DATA_DIR сервера (своя папка %LOCALAPPDATA%\\3DIWELL_DesktopShell),
НЕ является границей безопасности (все проверки прав выполняет backend).
"""

import json
import os
import re

SHELL_VERSION = "2.821"

APP_TITLE_LOCAL = "3DIWELL Farm Manager"
APP_TITLE_CLIENT = "3DIWELL Farm Manager Client"

# Порт локального Farm Manager по умолчанию (Alpha 2.806 — сервер разрешает менять его через трей).
# Фактический порт оболочка читает из config сервера: сначала ожидающий (pending), затем рабочий.
DEFAULT_LOCAL_PORT = 8000
DEFAULT_LOCAL_URL = "http://127.0.0.1:%d" % DEFAULT_LOCAL_PORT


def server_config_path():
    """Путь к config.json СЕРВЕРА. Он ВСЕГДА лежит в папке данных по умолчанию
    (%LOCALAPPDATA%\\3DIWELL) — так его находит сам сервер. FM_SERVER_CONFIG — только для тестов."""
    override = os.environ.get("FM_SERVER_CONFIG", "").strip()
    if override:
        return override
    la = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(la, "3DIWELL", "config.json")


def candidate_local_ports():
    """Порты, на которых может слушать локальный backend, в порядке проверки: ожидающий (pending)
    первым, затем рабочий (server_port), и — только при незавершённом переходе — прежний.
    Битые/отсутствующие значения игнорируются; при пустом результате — [8000] (значение по
    умолчанию применяется ТОЛЬКО когда настройки нет вовсе). Оболочка сам порт не выбирает,
    config сервера не пишет и диапазоны портов не сканирует."""
    try:
        with open(server_config_path(), encoding="utf-8") as f:
            cfg = json.load(f) or {}
    except Exception:
        cfg = {}
    def _take(key, ports):
        v = cfg.get(key)
        if isinstance(v, bool):
            return
        if isinstance(v, int) and 1024 <= v <= 65535 and v not in ports:
            ports.append(v)

    ports = []
    _take("pending_server_port", ports)
    _take("server_port", ports)
    # Alpha 2.812: прежний порт — кандидат ТОЛЬКО при незавершённом переходе (есть ожидающий).
    # Тогда сервер мог честно откатиться на него, не успев обновить настройку. В обычном
    # состоянии прежний порт — просто история, и стучаться в него незачем.
    if cfg.get("pending_server_port") is not None:
        _take("previous_server_port", ports)
    return ports or [DEFAULT_LOCAL_PORT]

# Отдельные постоянные профили WebView2: cookies локального окна и клиента не смешиваются
# ни между собой, ни с обычным Edge пользователя.
PROFILE_LOCAL = "FarmManagerDesktopLocal"
PROFILE_CLIENT = "FarmManagerDesktopClient"

MIN_WINDOW = (1100, 700)          # меньше — текущий UI становится нечитаемым
DEFAULT_WINDOW = (1440, 900)

READY_TIMEOUT_S = 60.0            # ждать готовности запущенного backend не дольше этого
PROBE_TIMEOUT_S = 3.0             # один HTTP-запрос проверки
DISCOVERY_WAIT_S = 2.0            # bounded-окно сбора ответов discovery (без фонового сканирования)


def parse_args(argv, default_mode="local"):
    """Разбор аргументов оболочки. Неизвестные аргументы игнорируются (не падаем).
    -> dict(mode, server_url, port, debug, open_browser, reset_window_state)."""
    args = list(argv or [])
    cfg = {
        "mode": default_mode,
        "server_url": "",
        # 🔒 Alpha 2.812, ROOT CAUSE. Здесь стояло DEFAULT_LOCAL_PORT (8000), то есть «порт задан
        # всегда». А оболочка проверяет `if cfg["port"]` и при заданном порте НЕ читает config
        # сервера вовсе — поэтому появившееся в 2.806 следование за активным портом было мёртвым
        # кодом при каждом обычном запуске ярлыком. Пока сервер жил на 8000, совпадение скрывало
        # дефект; после смены порта на 8123 окно стучалось в пустой 8000 и предлагало запустить
        # второй backend. 0 означает «порт НЕ задан пользователем»: явный --port по-прежнему
        # работает как переопределение, а по умолчанию источником истины остаётся config сервера.
        "port": 0,
        "debug": False,
        "open_browser": False,
        "reset_window_state": False,
        # Alpha 2.813: раздел интерфейса, на котором открыть окно («#logs» из трея). Это ЯКОРЬ
        # внутри своей же страницы, а не адрес: ни хоста, ни пути, ни параметров он задать не
        # может, поэтому подсунуть им чужой сервер невозможно.
        "open_fragment": "",
    }
    for i, a in enumerate(args):
        if a == "--local":
            cfg["mode"] = "local"
        elif a == "--client":
            cfg["mode"] = "client"
        elif a == "--debug-shell":
            cfg["debug"] = True
        elif a == "--open-browser":
            cfg["open_browser"] = True
        elif a == "--reset-window-state":
            cfg["reset_window_state"] = True
        elif a == "--open-fragment" and i + 1 < len(args):
            cfg["open_fragment"] = normalize_fragment(args[i + 1])
        elif a.startswith("--open-fragment="):
            cfg["open_fragment"] = normalize_fragment(a.split("=", 1)[1])
        elif a == "--server-url" and i + 1 < len(args) and not str(args[i + 1]).startswith("--"):
            cfg["server_url"] = str(args[i + 1]).strip()
        elif a.startswith("--server-url="):
            cfg["server_url"] = a.split("=", 1)[1].strip()
        elif a == "--port" and i + 1 < len(args):
            try:
                cfg["port"] = int(args[i + 1])
            except Exception:
                pass
        elif a.startswith("--port="):
            try:
                cfg["port"] = int(a.split("=", 1)[1])
            except Exception:
                pass
    return cfg


_FRAGMENT_RE = re.compile(r"^#?[A-Za-z0-9_\-/]{1,40}$")


def normalize_fragment(raw):
    """Безопасный якорь раздела («#logs»). -> «#logs» либо "" (всё сомнительное отбрасываем).

    Разрешены только буквы, цифры, дефис, подчёркивание и косая черта: ни схемы, ни хоста, ни
    параметров, ни второй решётки. Поэтому этим аргументом нельзя ни увести окно на чужой сервер,
    ни протащить токен."""
    s = str(raw or "").strip()
    if not s or not _FRAGMENT_RE.match(s):
        return ""
    return s if s.startswith("#") else "#" + s


def shell_root():
    """Корень данных оболочки. Отдельная папка: DATA_DIR сервера (%LOCALAPPDATA%\\3DIWELL)
    оболочка не трогает. Переопределение FM_DESKTOP_SHELL_ROOT — только для offline-тестов."""
    override = os.environ.get("FM_DESKTOP_SHELL_ROOT", "").strip()
    if override:
        return override
    la = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(la, "3DIWELL_DesktopShell")


def profile_dir(mode):
    """Папка данных WebView2-профиля (cookies управляются самим WebView2)."""
    name = PROFILE_CLIENT if mode == "client" else PROFILE_LOCAL
    return os.path.join(shell_root(), "profiles", name)


def state_path(mode):
    return os.path.join(shell_root(), "state-%s.json" % ("client" if mode == "client" else "local"))


def client_config_path():
    return os.path.join(shell_root(), "client.json")


def log_path(mode):
    return os.path.join(shell_root(), "logs", "shell-%s.log" % ("client" if mode == "client" else "local"))


# ── состояние окна ─────────────────────────────────────────────────────────────

_STATE_KEYS = ("x", "y", "width", "height", "maximized")


def load_window_state(mode):
    """Сохранённое состояние окна либо {}. Битый файл читается как пустой."""
    try:
        with open(state_path(mode), encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        out = {}
        for k in _STATE_KEYS:
            v = raw.get(k)
            if k == "maximized":
                out[k] = bool(v)
            elif isinstance(v, (int, float)):
                out[k] = int(v)
        return out
    except Exception:
        return {}


def save_window_state(mode, state):
    """Сохранить состояние окна. ТОЛЬКО геометрия — никаких URL/cookies/секретов."""
    try:
        clean = {}
        for k in _STATE_KEYS:
            if k in (state or {}):
                clean[k] = bool(state[k]) if k == "maximized" else int(state[k])
        p = state_path(mode)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def clamp_window_state(state, virtual_screen, min_size=MIN_WINDOW, default=DEFAULT_WINDOW):
    """Привести сохранённое состояние к безопасному: не меньше минимума, не за пределами
    ВИРТУАЛЬНОГО экрана (все мониторы). Окно на отключённом мониторе возвращается на центр
    основного. virtual_screen = (vx, vy, vw, vh) в тех же логических координатах.
    -> dict(x|None, y|None, width, height, maximized) — x/y None = центрировать."""
    vx, vy, vw, vh = virtual_screen
    st = dict(state or {})
    w = max(int(st.get("width") or default[0]), int(min_size[0]))
    h = max(int(st.get("height") or default[1]), int(min_size[1]))
    w = min(w, max(vw, min_size[0]))
    h = min(h, max(vh, min_size[1]))
    x, y = st.get("x"), st.get("y")
    if x is None or y is None:
        x = y = None                       # первое открытие — центрирование
    else:
        x, y = int(x), int(y)
        # окно считается видимым, если внутри виртуального экрана остаётся заметная часть
        margin = 48
        if (x + w < vx + margin or x > vx + vw - margin
                or y < vy - margin or y > vy + vh - margin):
            x = y = None                   # координаты с отключённого монитора — в центр
    return {"x": x, "y": y, "width": w, "height": h, "maximized": bool(st.get("maximized"))}


# ── клиентская конфигурация ────────────────────────────────────────────────────

def load_client_config():
    """{'server_origin': ...} либо {}. Хранится ТОЛЬКО origin сервера — ни паролей,
    ни токенов, ни cookies (ими владеет WebView2-профиль)."""
    try:
        with open(client_config_path(), encoding="utf-8") as f:
            raw = json.load(f)
        origin = str((raw or {}).get("server_origin") or "").strip()
        return {"server_origin": origin} if origin else {}
    except Exception:
        return {}


def save_client_config(server_origin):
    """Сохранить origin выбранного сервера (без учётных данных, query и fragment)."""
    try:
        p = client_config_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"server_origin": str(server_origin or "")}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def clear_client_config():
    """Забыть сохранённый сервер (кнопка «Сменить сервер»). Файл переписывается пустым
    объектом — удаление файлов оболочка не выполняет."""
    try:
        p = client_config_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({}, f)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


# ── журнал: приватность ────────────────────────────────────────────────────────

def redact_url_for_log(url):
    """В журнал попадает ТОЛЬКО origin (scheme://host[:port]) — без пути, query, fragment
    и credentials. Recovery-токен живёт во фрагменте — он не логируется никогда."""
    s = str(url or "").strip()
    m = re.match(r"^(https?)://([^/@?#]*@)?(\[[0-9A-Fa-f:%.]+\]|[^/:?#]+)(:\d+)?", s)
    if not m:
        return "<non-http-url>"
    return "%s://%s%s" % (m.group(1).lower(), m.group(3), m.group(4) or "")
