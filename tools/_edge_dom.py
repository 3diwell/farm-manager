# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.834 — получение отрендеренного DOM из Edge/Chromium БЕЗ --dump-dom.

ПРИЧИНА. Edge 150.0.4078.83 (обновился на ферменном ПК) перестал печатать документ по
`--headless=new --dump-dom`: процесс выходит с кодом 0, stdout ПУСТОЙ, рендер 0.0 с. Из-за этого
все offline-харнессы, читавшие DOM из stdout, начали получать пустую строку — тесты краснели, хотя
приложение исправно. Это деградация ИНСТРУМЕНТА, а не кода Farm Manager.

РЕШЕНИЕ. Тот же headless-Edge поднимается с `--remote-debugging-port`, и документ читается через
Chrome DevTools Protocol (`Runtime.evaluate` -> outerHTML). Контракт для тестов сохранён: функция
возвращает СТРОКУ документа — ровно то, что прежде приходило в stdout, поэтому все дословные
проверки харнессов остаются неизменными.

Реализация — на stdlib (socket + base64 + hashlib): минимальный клиент WebSocket на текстовых
фреймах, без внешних зависимостей и без Node-моста. Никогда не бросает: при любой проблеме
возвращает None (харнесс сам решает, это SKIP или FAIL).
"""
import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Многие харнессы ставят offline-ловушку `socket.socket = _TrapSocket`, доказывая, что ПРОДУКТОВЫЙ
# код не ходит в сеть. Этот модуль — часть оснастки: ему нужно ровно одно соединение с СОБСТВЕННЫМ
# headless-браузером на 127.0.0.1 (никакой сети, никаких принтеров, никакого DATA_DIR). Поэтому
# захватываем настоящий класс сокета в момент импорта (импорт стоит ВЫШЕ установки ловушки) и
# используем только его: ловушка продолжает ловить любые сокеты продуктового кода.
_ORIG_SOCKET = socket.socket


def _playwright_chromium():
    """Локальный Chromium из кеша Playwright (%LOCALAPPDATA%\\ms-playwright\\chromium-*) или None.

    ЗАЧЕМ ОН ПЕРВЫЙ. Установленный на ферменном ПК Edge 150.0.4078.83 не поддаётся автоматизации:
    --dump-dom печатает пустоту, а --remote-debugging-port не создаёт DevToolsActivePort ни в одном
    режиме (headless=new/old, обычное окно). Этот Chromium — обычный движок того же семейства, он
    отдаёт CDP штатно, поэтому геометрические/zoom-замеры снова выполняются, а не пропускаются.
    Скачан локально в кеш пользователя; в проект, БД, DATA_DIR и сборку не входит."""
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    if not os.path.isdir(root):
        return None
    # headless_shell идёт ПЕРВЫМ: на этой сборке Windows полный chrome.exe из пакета Playwright не
    # стартует (WinError 14001, side-by-side/CRT), а headless_shell запускается и отдаёт CDP штатно.
    cands = []
    for name in sorted(os.listdir(root)):
        try:
            rev = int(name.rsplit("-", 1)[1])
        except Exception:
            rev = 0
        if name.startswith("chromium_headless_shell-"):
            cands.append((2, rev, os.path.join(root, name, "chrome-win", "headless_shell.exe")))
        elif name.startswith("chromium-"):
            cands.append((1, rev, os.path.join(root, name, "chrome-win", "chrome.exe")))
    for _pri, _rev, exe in sorted(cands, reverse=True):
        if os.path.exists(exe):
            return exe
    return None


def find_edge():
    """Путь к движку рендера или None.

    ПОРЯДОК ПРОВЕРЕН ЗАМЕРОМ. Штатный Edge, поднятый этим мостом (CDP + --in-process-gpu), отдаёт
    документ за ~5 с — сломан у него был только --dump-dom, а не сам движок. Playwright-Chromium из
    кеша пользователя на этой машине к CDP не отвечает (headless_shell не создаёт рабочий page-target,
    полный chrome.exe не стартует из-за side-by-side/CRT), поэтому он остаётся лишь последним
    резервом, если системного Edge/Chrome в системе нет вообще."""
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    return shutil.which("msedge") or shutil.which("chrome") or _playwright_chromium()


def _find_node():
    """Путь к node.exe (тем же способом, что и остальные харнессы проекта) или None."""
    for p in (os.path.join("C:" + os.sep, "Program Files", "nodejs", "node.exe"),
              os.path.join("C:" + os.sep, "Program Files (x86)", "nodejs", "node.exe")):
        if os.path.exists(p):
            return p
    return shutil.which("node")


class _WS(object):
    """Минимальный клиент WebSocket (только то, что нужно CDP: текстовые фреймы, без расширений)."""

    def __init__(self, url, timeout=20.0):
        u = url.split("://", 1)[1]
        hostport, _, path = u.partition("/")
        host, _, port = hostport.partition(":")
        self.s = _ORIG_SOCKET(socket.AF_INET, socket.SOCK_STREAM)   # мимо offline-ловушек харнессов
        self.s.settimeout(timeout)
        self.s.connect((host, int(port or 80)))
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key))
        self.s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            ch = self.s.recv(4096)
            if not ch:
                raise IOError("handshake closed")
            buf += ch
        if b" 101 " not in buf.split(b"\r\n", 1)[0]:
            raise IOError("no 101 upgrade")
        exp = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode().lower()
        if exp.encode() not in buf.lower():
            raise IOError("bad accept")
        self._rest = buf.split(b"\r\n\r\n", 1)[1]

    def send_text(self, text):
        payload = text.encode("utf-8")
        n = len(payload)
        hdr = b"\x81"
        if n < 126:
            hdr += struct.pack("!B", 0x80 | n)
        elif n < 65536:
            hdr += struct.pack("!BH", 0x80 | 126, n)
        else:
            hdr += struct.pack("!BQ", 0x80 | 127, n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.s.sendall(hdr + mask + masked)

    def _read(self, n):
        while len(self._rest) < n:
            ch = self.s.recv(max(4096, n - len(self._rest)))
            if not ch:
                raise IOError("closed")
            self._rest += ch
        out, self._rest = self._rest[:n], self._rest[n:]
        return out

    def recv_text(self):
        """Одно текстовое сообщение (собирает продолжения, игнорирует ping/pong). -> str"""
        chunks = []
        while True:
            b0, b1 = struct.unpack("!BB", self._read(2))
            op, fin, ln = b0 & 0x0F, b0 & 0x80, b1 & 0x7F
            if ln == 126:
                ln = struct.unpack("!H", self._read(2))[0]
            elif ln == 127:
                ln = struct.unpack("!Q", self._read(8))[0]
            data = self._read(ln) if ln else b""
            if op == 0x8:
                raise IOError("server close")
            if op in (0x9, 0xA):
                continue
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", "replace")

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def _free_port():
    s = _ORIG_SOCKET(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _http_get(port, path, timeout=2.0):
    """Минимальный HTTP GET к 127.0.0.1:port (тело ответа строкой) через настоящий сокет.
    urllib здесь не годится: он создаёт сокет через подменённый харнессом socket.socket."""
    s = _ORIG_SOCKET(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        s.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n" % path).encode())
        buf = b""
        while True:
            ch = s.recv(65536)
            if not ch:
                break
            buf += ch
    finally:
        try:
            s.close()
        except Exception:
            pass
    head, _, body = buf.partition(b"\r\n\r\n")
    if b"Transfer-Encoding: chunked" in head:      # DevTools иногда отвечает чанками
        out, rest = b"", body
        while rest:
            ln, _, rest = rest.partition(b"\r\n")
            try:
                n = int(ln.strip() or b"0", 16)
            except Exception:
                break
            if n == 0:
                break
            out += rest[:n]
            rest = rest[n + 2:]
        body = out
    return body.decode("utf-8", "replace")


def render_dom(url, edge=None, profile_dir=None, window_size=(1440, 900), extra_args=(),
               settle_ms=900, timeout=180.0, eval_js=None, shot_path=None, diag_path=None):
    """Открыть url в headless-движке и вернуть отрендеренный DOM строкой (или None).

    Работа делается мостом tools/_edge_cdp.mjs (Node): там есть готовые fetch и WebSocket, а
    самописный WS-клиент на этой машине упирался в таймауты рукопожатия. Alpha 2.835: shot_path —
    необязательный PNG видимой области (нужен, чтобы судить раскладку глазами); diag_path — файл, в
    который мост кладёт ошибки консоли, предупреждения (в т.ч. «[Vue warn]»), необработанные
    исключения и отказы промисов (без них браузерная проверка не могла краснеть на ошибке страницы).
    Мост же ставит --in-process-gpu (иначе отдельный GPU-процесс падает и уносит браузер) и закрывает
    движок через Browser.close, поэтому профиль реально удаляется. Никогда не бросает."""
    edge = edge or find_edge()
    node = _find_node()
    if not edge or not node:
        return None
    own_tmp = None
    if not profile_dir:
        own_tmp = tempfile.mkdtemp(prefix="fm_cdp_")
        profile_dir = os.path.join(own_tmp, "prof")
    bridge = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_edge_cdp.mjs")
    if not os.path.exists(bridge):
        return None
    ev_path = ""
    if eval_js:
        # Сценарий отдаём файлом: в нём кавычки и переводы строк, аргументом командной строки
        # такое передавать нельзя.
        fd, ev_path = tempfile.mkstemp(prefix="fm_eval_", suffix=".js")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(eval_js)
    # Alpha 2.835: ДВЕ попытки. Поднятие headless-движка — операция с внешними ресурсами
    # (временный профиль, порт, файлы), и под посторонней нагрузкой она изредка срывается
    # (EBUSY на профиле, порт не успевает появиться). Это свойство среды, а не продукта.
    # Настоящий дефект проваливает обе попытки, поэтому сигнал не ослабляется.
    try:
        for _attempt in range(2):
            _prof = profile_dir if _attempt == 0 else (profile_dir + "_r%d" % _attempt)
            pr = subprocess.run([node, bridge, edge, url, _prof,
                                 str(int(window_size[0])), str(int(window_size[1])),
                                 str(int(settle_ms)), json.dumps(list(extra_args)), ev_path,
                                 shot_path or "", diag_path or ""],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout)
            out = pr.stdout or ""
            if out.strip():
                return out
            if _attempt == 0:
                _kill_by_profile(_prof)
                time.sleep(1.5)
        return None
    except Exception:
        return None
    finally:
        if ev_path:
            try:
                os.unlink(ev_path)
            except Exception:
                pass
        # Сначала гарантированно снимаем движок этого профиля (мост мог не успеть — например,
        # если его самого убил таймаут), только потом убираем папки.
        _kill_by_profile(profile_dir)
        for _target in ([own_tmp] if own_tmp else [profile_dir]):
            for _try in range(8):
                if not os.path.exists(_target):
                    break
                try:
                    shutil.rmtree(_target)
                    break
                except Exception:
                    time.sleep(0.35)


def _kill_by_profile(profile_dir):
    """Снять процессы движка, которые держат ИМЕННО этот временный профиль.

    Alpha 2.835: гарантия со стороны Python. Мост убирает за собой сам, но если Node не успел
    (таймаут subprocess, аварийное завершение), headless-движок остаётся жить, держит профиль и
    ест память — за прогон набора так накапливались сотни процессов, и от этой нагрузки начинали
    плавать браузерные замеры. Фильтр — точный путь профиля, обычный браузер владельца задеть
    невозможно.
    """
    if not profile_dir:
        return
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -and $_.CommandLine.Contains(%s) } | "
          "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"
          % json.dumps(profile_dir))
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


_USABLE = {"checked": False, "ok": False}


def engine_usable(edge=None):
    """Умеет ли движок на ЭТОЙ машине реально отрендерить страницу и отдать DOM. Результат кешируется.

    Нужна потому, что наличие msedge.exe/chrome.exe больше НЕ означает работоспособность: на
    ферменном ПК (Windows 10 IoT LTSC) рендерер Chromium не поднимается — DevTools-порт отвечает по
    HTTP, но ни одна CDP-команда не обрабатывается (ни по WebSocket, ни по pipe), а --dump-dom
    печатает пустоту. Alpha 2.835: харнессы вызывают эту проверку и, если движка фактически нет,
    КРАСЯТ геометрические проверки с точной причиной. Прежний SKIP был слепой зоной — именно он
    однажды спрятал реальный дефект интерфейса, поэтому пропуска здесь больше нет."""
    if _USABLE["checked"]:
        return _USABLE["ok"]
    _USABLE["checked"] = True
    exe = edge or find_edge()
    if not exe or not _find_node():
        return False
    td = tempfile.mkdtemp(prefix="fm_probe_")
    try:
        pg = os.path.join(td, "probe.html")
        with open(pg, "w", encoding="utf-8") as fh:
            fh.write("<html><body><div id='__p'>FM_PROBE_OK</div></body></html>")
        # Alpha 2.835: две попытки и запас по времени. Одиночная короткая проба на загруженной
        # машине иногда не успевала — и весь браузерный блок теста краснел «движок недоступен»,
        # хотя движок исправен. Ответ «движка нет» должен означать именно это.
        for _try in range(2):
            dom = render_dom("file:///" + pg.replace("\\", "/"), edge=exe,
                             profile_dir=os.path.join(td, "prof%d" % _try), window_size=(800, 600),
                             settle_ms=300, timeout=120.0)
            if dom and "FM_PROBE_OK" in dom:
                _USABLE["ok"] = True
                break
    except Exception:
        _USABLE["ok"] = False
    finally:
        for _ in range(6):
            if not os.path.exists(td):
                break
            try:
                shutil.rmtree(td)
            except Exception:
                time.sleep(0.3)
    return _USABLE["ok"]


def dump_dom_compatible(edge, url, profile_dir, window_size=(1440, 900), budget_ms=4000,
                        extra_args=(), eval_js=None):
    """Совместимая замена прежнего вызова `msedge --dump-dom ... > stdout`.
    Возвращает СТРОКУ документа (как прежний stdout) либо '' — чтобы регулярные выражения
    существующих харнессов работали без изменений."""
    s = render_dom(url, edge=edge, profile_dir=profile_dir, window_size=window_size,
                   extra_args=extra_args, settle_ms=max(600, min(4000, int(budget_ms))),
                   eval_js=eval_js)
    return s or ""
