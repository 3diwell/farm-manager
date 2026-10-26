# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — desktop-оболочка на WebView2 (Alpha 2.805).

Собственное окно для СУЩЕСТВУЮЩЕГО web-интерфейса: pywebview (EdgeChromium/WebView2)
показывает тот же SPA, что и браузер. Backend остаётся единственным и живёт отдельно:
оболочка НЕ импортирует server.py, НЕ открывает БД, НЕ трогает DATA_DIR и не является
границей безопасности — auth/права/origin проверяет сам сервер.

Два режима:
  * local  — на компьютере фермы: переиспользует уже работающий Farm Manager либо
    запускает штатный backend отдельным процессом и ждёт готовности; закрытие окна
    НЕ останавливает backend (он продолжает жить в трее);
  * client — на другом компьютере: только окно + экран подключения; backend, БД,
    DATA_DIR, принтеры и очередь остаются на сервере.

АРХИТЕКТУРА «БЕЗ МОСТА» (zero-bridge). Привилегированный JS-мост НЕ используется вовсе:
  * кнопки собственных страниц оболочки (запуск/ошибка/подключение) отправляют навигацию
    на фиктивный командный host (fmshell.invalid) — обработчик NavigationStarting
    ОТМЕНЯЕТ её до сети и кладёт команду в очередь; команды принимаются ТОЛЬКО со
    страниц самой оболочки (пока origin сервера не выбран) — страница сервера
    командовать оболочкой не может;
  * горячие клавиши (F5/Ctrl+R — reload, F11 — полный экран) — нативное событие
    AcceleratorKeyPressed WebView2;
  * геометрия окна читается в момент закрытия из WinForms-формы (UI-поток, без Invoke);
  * статус на стартовой странице — прямой ExecuteScriptAsync (fire-and-forget).

pywebview импортируется ТОЛЬКО внутри функций запуска окна — offline-тесты импортируют
модуль без GUI-зависимостей.
"""

import json
import logging
import logging.handlers
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from app import desktop_shell_config as shcfg
from app import desktop_shell_security as shsec

log = logging.getLogger("fm.desktop_shell")

# Мьютексы ОКНА (per-user session). Это НЕ мьютекс backend: замок сервера
# (имя *_SingleInstance_v1 в app/single_instance.py) принадлежит server.py, оболочка
# его не берёт и не обходит.
SHELL_MUTEX_LOCAL = r"Local\3DIWELL_FM_DesktopShell_Local_v1"
SHELL_MUTEX_CLIENT = r"Local\3DIWELL_FM_DesktopShell_Client_v1"

_ERROR_ALREADY_EXISTS = 183
_mutex_handle = None          # хэндл держится до конца процесса


# ── журнал оболочки ────────────────────────────────────────────────────────────

def setup_logging(mode, debug=False):
    """Отдельный ограниченный журнал оболочки. В журнал не попадают пароли, cookies,
    токены, тела запросов и полные URL (только origin через redact_url_for_log)."""
    try:
        p = shcfg.log_path(mode)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        h = logging.handlers.RotatingFileHandler(p, maxBytes=512 * 1024, backupCount=2,
                                                 encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.DEBUG if debug else logging.INFO)
    except Exception:
        pass


# ── обнаружение и запуск локального backend ────────────────────────────────────

def probe_farm_manager(base_url, timeout=shcfg.PROBE_TIMEOUT_S, opener=None):
    """Проверка «это действительно Farm Manager»: GET /version и классификация ответа.
    Открытый порт ЧУЖОЙ программы не считается Farm Manager.
    -> "ready" | "auth" | "foreign" | "down"."""
    opener = opener or urllib.request.urlopen
    url = str(base_url or "").rstrip("/") + "/version"
    try:
        with opener(url, timeout=timeout) as r:
            body = r.read(4096).decode("utf-8", "replace")
            status = int(getattr(r, "status", 200))
        return shsec.classify_probe(status, body)
    except urllib.error.HTTPError as e:                     # 401/403 — тоже ответ
        try:
            body = e.read(4096).decode("utf-8", "replace")
        except Exception:
            body = ""
        return shsec.classify_probe(int(e.code), body)
    except Exception:
        return "down"


def server_command():
    """Команда запуска ШТАТНОГО backend. -> список аргументов либо None.
    Сборка: рядом с оболочкой лежит существующий «3DIWELL Farm Manager.exe».
    Dev: python + server.py из корня репозитория."""
    if getattr(sys, "frozen", False):
        exe = os.path.join(os.path.dirname(sys.executable), "3DIWELL Farm Manager.exe")
        return [exe] if os.path.isfile(exe) else None
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    srv = os.path.join(repo, "server.py")
    if not os.path.isfile(srv):
        return None
    return [sys.executable, srv]


def spawn_backend(cmd):
    """Запустить backend ОТДЕЛЬНЫМ процессом, не привязанным к оболочке: закрытие окна
    не завершает сервер (полное завершение — только штатный «Выход» в трее).
    Передаются флаги --desktop-start (без консольных пауз) и --no-browser."""
    flags = 0
    if sys.platform.startswith("win"):
        flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(list(cmd) + ["--desktop-start", "--no-browser"],
                            creationflags=flags, close_fds=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, cwd=os.path.dirname(str(cmd[-1])) or None)


def ensure_local_backend(base_url, status_cb=None, probe=None, spawn=None,
                         deadline_s=shcfg.READY_TIMEOUT_S, sleep=time.sleep, clock=time.monotonic):
    """Гарантировать работающий ЛОКАЛЬНЫЙ Farm Manager. Уже работает (ready/auth) —
    ничего не запускаем (второй backend недопустим и отсечён ещё и mutex'ом сервера).
    Не отвечает — запускаем штатный entry point и ждём готовности не дольше deadline_s.
    -> ("ready"|"auth", запускали ли мы) | ("no_backend"|"foreign_port"|"timeout"|"spawn_failed", flag)."""
    probe = probe or probe_farm_manager
    spawn = spawn or spawn_backend
    say = status_cb or (lambda *_: None)
    st = probe(base_url)
    if st in ("ready", "auth"):
        log.info("[local] существующий сервер переиспользован (%s)", st)
        return (st, False)
    if st == "foreign":
        log.warning("[local] на %s отвечает ПОСТОРОННЯЯ программа", shcfg.redact_url_for_log(base_url))
        return ("foreign_port", False)
    cmd = server_command()
    if not cmd:
        log.error("[local] исполняемый файл Farm Manager не найден рядом с оболочкой")
        return ("no_backend", False)
    say("Запуск Farm Manager…")
    try:
        spawn(cmd)
    except Exception as e:
        log.error("[local] запуск backend не удался: %s", str(e)[:120])
        return ("spawn_failed", True)
    t0 = clock()
    while clock() - t0 < float(deadline_s):
        sleep(0.5)
        st = probe(base_url)
        if st in ("ready", "auth"):
            log.info("[local] backend запущен оболочкой и готов за %.1f c (%s)", clock() - t0, st)
            return (st, True)
        if st == "foreign":
            return ("foreign_port", True)
        say("Запуск Farm Manager… (%d с)" % int(clock() - t0))
    log.error("[local] backend не стал готов за %.0f c", float(deadline_s))
    return ("timeout", True)


# ── одиночное окно (per-user mutex + активация существующего) ─────────────────

def acquire_shell_mutex(mode):
    """Занять мьютекс ОКНА. -> True (окно наше) | False (окно уже открыто).
    Не-Windows/сбой WinAPI — fail-open (окно важнее замка)."""
    global _mutex_handle
    if not sys.platform.startswith("win"):
        return True
    try:
        import ctypes
        name = SHELL_MUTEX_CLIENT if mode == "client" else SHELL_MUTEX_LOCAL
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        h = k32.CreateMutexW(None, True, name)
        if not h:
            return True
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            k32.CloseHandle(h)
            return False
        _mutex_handle = h
        return True
    except Exception:
        return True


def activate_existing_window(title):
    """Вынести уже открытое окно оболочки на передний план (повторный запуск не создаёт
    второго окна — он активирует существующее)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.FindWindowW.restype = ctypes.c_void_p
        hwnd = u.FindWindowW(None, str(title))
        if not hwnd:
            return False
        u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        u.ShowWindow(hwnd, 9)          # SW_RESTORE
        u.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def has_webview2_runtime():
    """Установлен ли Microsoft Edge WebView2 Runtime (обе ветки реестра + per-user)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        keys = [(winreg.HKEY_LOCAL_MACHINE,
                 r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                (winreg.HKEY_LOCAL_MACHINE,
                 r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                (winreg.HKEY_CURRENT_USER,
                 r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")]
        for hive, path in keys:
            try:
                with winreg.OpenKey(hive, path) as k:
                    pv = str(winreg.QueryValueEx(k, "pv")[0] or "")
                    if pv and pv != "0.0.0.0":
                        return True
            except OSError:
                continue
    except Exception:
        return False
    return False


def message_box(title, text, yesno=False):
    """Нативное окно сообщения (без Python traceback наружу)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        MB = 0x00000040 | 0x00010000 | 0x00040000           # ICONINFORMATION|SETFOREGROUND|TOPMOST
        if yesno:
            MB |= 0x00000004                                # MB_YESNO
        rc = ctypes.windll.user32.MessageBoxW(None, str(text), str(title), MB)
        return rc == 6                                      # IDYES
    except Exception:
        return False


def open_in_system_browser(url):
    """Открыть URL в СИСТЕМНОМ браузере (внешние ссылки не живут внутри окна)."""
    try:
        os.startfile(url)                                    # Windows: браузер по умолчанию
        return True
    except Exception:
        try:
            import webbrowser
            return bool(webbrowser.open(url))
        except Exception:
            return False


# ── локальные страницы оболочки (автономные, frontend не копируется) ───────────
# Кнопки страниц отправляют навигацию на фиктивный командный host оболочки
# (shsec.SHELL_CMD_ORIGIN); NavigationStarting отменяет её ДО сети и исполняет команду.
# Никакого window.pywebview / privileged-моста на страницах нет.

_PAGE_CSS = """
html,body{margin:0;height:100%;background:#0b1118;color:#dbe4ee;font:14px 'Segoe UI',sans-serif}
.wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:14px}
.logo{font-size:26px;font-weight:700;letter-spacing:2px;color:#22d3ee}
.sub{color:#8aa0b6}
.spin{width:34px;height:34px;border:3px solid #1d2a38;border-top-color:#22d3ee;border-radius:50%;
animation:s 0.9s linear infinite}@keyframes s{to{transform:rotate(360deg)}}
.card{background:#101a26;border:1px solid #1d2a38;border-radius:12px;padding:22px 26px;max-width:540px;width:92%}
.btn{display:inline-block;margin:4px 6px 0 0;padding:7px 14px;border-radius:8px;border:1px solid #22d3ee55;
background:#22d3ee14;color:#22d3ee;cursor:pointer;font-size:13px;text-decoration:none}
.btn.gray{border-color:#33465c;color:#9fb2c8;background:transparent}
input,select{background:#0b141d;border:1px solid #24384e;border-radius:8px;color:#dbe4ee;padding:7px 9px;font-size:13px}
.err{color:#f5a524;font-size:13px;min-height:18px}
.list .btn{display:block;margin-top:6px}
label{font-size:12px;color:#8aa0b6}
"""

_CMD_JS = """
function fmCmd(action, params){
  var q = '';
  if (params) {
    var parts = [];
    for (var k in params) parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
    q = '?' + parts.join('&');
  }
  window.location.href = '%s/' + action + q;   /* перехватывается оболочкой ДО сети */
}
""" % shsec.SHELL_CMD_ORIGIN


def page_starting(status="Запуск Farm Manager…"):
    return ("<!doctype html><meta charset='utf-8'><title>3DIWELL Farm Manager</title>"
            "<style>%s</style><div class='wrap'><div class='logo'>3DIWELL</div>"
            "<div class='spin'></div><div id='st' class='sub'>%s</div></div>"
            "<script>function fmSetStatus(t){var e=document.getElementById('st');"
            "if(e)e.textContent=t}</script>" % (_PAGE_CSS, status))


def page_error(reason_text, show_change_server=False, address_line="", show_start_server=False):
    """Страница ошибки: безопасная причина, проверенные порты, без путей и traceback.

    Alpha 2.812: «Повторить» и «Запустить сервер» — РАЗНЫЕ действия. Повтор только перечитывает
    настройку порта и заново спрашивает сервер (полезно, когда пользователь запустил его сам);
    запуск сервера дополнительно поднимает backend. Две кнопки с одинаковым поведением сбивали
    бы с толку, поэтому вторая появляется только там, где ей есть что делать."""
    change = ("<span class='btn gray' onclick=\"fmCmd('change-server')\">Сменить сервер</span>"
              if show_change_server else "")
    start = ("<span class='btn gray' onclick=\"fmCmd('start-server')\">Запустить сервер</span>"
             if show_start_server else "")
    addr = ("<div class='sub' style='margin-top:4px'>%s</div>" % address_line) if address_line else ""
    return ("<!doctype html><meta charset='utf-8'><title>3DIWELL Farm Manager</title>"
            "<style>%s</style><script>%s</script><div class='wrap'><div class='card'>"
            "<div class='logo' style='font-size:20px'>3DIWELL Farm Manager</div>"
            "<div style='margin-top:10px'>Не удалось подключиться к локальному Farm Manager</div>%s"
            "<div class='err' style='margin-top:8px'>%s</div><div style='margin-top:12px'>"
            "<span class='btn' onclick=\"fmCmd('retry')\">Повторить</span>%s"
            "<span class='btn gray' onclick=\"fmCmd('browser')\">Открыть в браузере</span>"
            "%s<span class='btn gray' onclick=\"fmCmd('close')\">Закрыть</span>"
            "</div></div></div>" % (_PAGE_CSS, _CMD_JS, addr, reason_text, start, change))


def page_connect(saved_origin="", error_text="", found=None):
    """Экран подключения клиента: локальный HTML, backend не требуется. Список найденных
    серверов рендерится оболочкой (страница пересобирается после «Найти серверы»)."""
    items = ""
    for s in (found or []):
        label = "%s — %s:%d" % (s.get("name", "?"), s.get("ip", "?"), int(s.get("port", 0)))
        items += ("<span class='btn gray' onclick=\"fmCmd('connect',{url:'http://%s:%d'})\">%s</span>"
                  % (s.get("ip", ""), int(s.get("port", 0)), label))
    saved_note = ("<div class='sub' style='margin-top:6px'>Сохранённый сервер: %s</div>" % saved_origin
                  if saved_origin else "")
    return ("<!doctype html><meta charset='utf-8'><title>3DIWELL Farm Manager Client</title>"
            "<style>%s</style><script>%s\n"
            "function fmVal(){var h=document.getElementById('host').value.trim();"
            "var p=document.getElementById('port').value.trim();var s=document.getElementById('sc').value;"
            "if(!h)return '';return s+'://'+h+(p?(':'+p):'');}\n"
            "function fmConnect(u){var v=u||fmVal();"
            "if(!v){document.getElementById('err').textContent='Введите адрес сервера.';return;}"
            "document.getElementById('err').textContent='Проверка подключения…';"
            "fmCmd('connect',{url:v});}\n"
            "function fmBrowser(){var v=fmVal();if(!v){document.getElementById('err').textContent="
            "'Введите адрес сервера.';return;}fmCmd('open-browser',{url:v});}\n"
            "</script><div class='wrap'><div class='card'>"
            "<div class='logo' style='font-size:20px'>3DIWELL Farm Manager</div>"
            "<div class='sub'>Подключение к серверу фермы</div>"
            "<div style='margin-top:12px;display:flex;gap:8px;align-items:end;flex-wrap:wrap'>"
            "<div><label>Протокол</label><br><select id='sc'><option>http</option><option>https</option></select></div>"
            "<div style='flex:1;min-width:170px'><label>Адрес сервера</label><br>"
            "<input id='host' style='width:100%%' placeholder='192.168.1.50'></div>"
            "<div style='width:86px'><label>Порт</label><br><input id='port' style='width:100%%' value='8000'></div>"
            "</div><div id='err' class='err' style='margin-top:8px'>%s</div>"
            "<div style='margin-top:10px'>"
            "<span class='btn' onclick='fmConnect()'>Подключиться</span>"
            "<span class='btn gray' onclick=\"fmCmd('discover')\">Найти серверы</span>"
            "<span class='btn gray' onclick='fmBrowser()'>Открыть в браузере</span>"
            "</div><div class='list' style='margin-top:8px'>%s</div>%s"
            "<div class='sub' style='margin-top:12px;font-size:11px'>Пароль вводится на странице входа"
            " самого сервера; клиент его не сохраняет.</div></div></div>"
            % (_PAGE_CSS, _CMD_JS, error_text, items, saved_note))


# Горячие клавиши: F5/Ctrl+R обрабатывает сам WebView2 (браузерные акселераторы включены,
# DevTools при этом остаются выключенными), F11 — постоянный документный скрипт, который
# шлёт безопасную команду toggle-fullscreen на командный host (перехватывается до сети).
_F11_JS = ("window.addEventListener('keydown',function(e){if(e.key==='F11'){"
           "e.preventDefault();window.location.href='%s/toggle-fullscreen';}},true);"
           % shsec.SHELL_CMD_ORIGIN)


# ── discovery (bounded, переиспользует существующий протокол сервера) ──────────

def discover_servers(wait_s=shcfg.DISCOVERY_WAIT_S):
    """Разослать существующий probe 3DIWELL_DISCOVER_v1 и собрать ответы не дольше wait_s.
    Ничего не включает на серверах (отвечают только те, у кого LAN уже включён),
    firewall не меняет, фонового сканирования не оставляет."""
    found, seen = [], set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(0.3)
            s.sendto(shsec.DISCOVERY_MAGIC, ("255.255.255.255", shsec.DISCOVERY_PORT))
            t0 = time.monotonic()
            while time.monotonic() - t0 < float(wait_s):
                try:
                    data, addr = s.recvfrom(1024)
                except socket.timeout:
                    continue
                item = shsec.parse_discovery_reply(data, addr[0])
                if item and (item["ip"], item["port"]) not in seen:
                    seen.add((item["ip"], item["port"]))
                    found.append(item)
        finally:
            s.close()
    except Exception:
        pass
    return found


# ── сама оболочка ─────────────────────────────────────────────────────────────

class DesktopShell(object):
    """Состояние одного окна. Отвечает ТОЛЬКО за окно/навигацию/адрес сервера —
    никакой бизнес-логики, прав и данных фермы здесь нет."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = cfg.get("mode") or "local"
        self.window = None
        self.allowed_origin = ""            # origin, разрешённый для навигации ('' = только страницы оболочки)
        self.target_url = ""
        self._commands = queue.Queue()      # команды со страниц оболочки (fmshell.invalid)
        self._policy_ready = threading.Event()

    # ---- адреса ----
    def local_candidate_urls(self):
        """Локальные адреса-кандидаты в порядке проверки.

        Приоритет: явно указанный пользователем адрес/порт, иначе — порты из config СЕРВЕРА
        (ожидающий, затем рабочий, затем прежний для незавершённого перехода). Оболочка сам порт
        не выбирает и config не пишет: единственный источник истины — конфигурация сервера и
        фактический ответ `/version`.
        Alpha 2.812: список читается ЗАНОВО при каждом обращении — после перезапуска сервера или
        смены порта окну не нужно перезапускаться, чтобы узнать новый адрес."""
        if self.cfg.get("server_url"):
            origin, err = shsec.normalize_server_url(self.cfg["server_url"])
            if not err:
                return [origin]
        if self.cfg.get("port"):          # только явный --port; по умолчанию он НЕ задан
            return ["http://127.0.0.1:%d" % int(self.cfg["port"])]
        return ["http://127.0.0.1:%d" % p for p in shcfg.candidate_local_ports()]

    def find_running_local(self):
        """Найти УЖЕ работающий локальный Farm Manager. -> (адрес, статус) либо ("", "").

        Проверяются все кандидаты по порядку, и настоящим сервером считается только тот, кто
        ответил `/version` как Farm Manager: открытый порт чужой программы отклоняется и НЕ
        останавливает перебор."""
        for base in self.local_candidate_urls():
            st = probe_farm_manager(base)
            if st in ("ready", "auth"):
                return base, st
        return "", ""

    def local_base_url(self):
        """Первый кандидат — для сообщений/браузерного fallback (без сетевых обращений)."""
        return self.local_candidate_urls()[0]

    def browser_url(self):
        return self.target_url or (self.local_base_url() if self.mode == "local" else "")

    # ---- нативная интеграция (CLR): политика навигации + горячие клавиши ----
    def _native_parts(self):
        """(BrowserForm, WebView2-контрол) текущего окна pywebview."""
        from webview.platforms.winforms import BrowserView
        bv = BrowserView.instances.get(self.window.uid)
        return bv, bv.browser.webview

    def _attach_native_handlers(self, deadline_s=20.0):
        """Подключить NavigationStarting (политика + команды) и AcceleratorKeyPressed
        (F5/Ctrl+R/F11) к CoreWebView2. Ожидание готовности — bounded; подписка — в
        UI-потоке (form.Invoke). -> True при успехе. Политика обязана быть подключена
        ДО первой навигации на сервер (go() ждёт _policy_ready)."""
        shell = self
        done = {"ok": False}
        t0 = time.monotonic()
        while time.monotonic() - t0 < float(deadline_s):
            try:
                # Форма и контрол появляются ПОСЛЕ старта GUI-цикла — получать их надо
                # внутри цикла ожидания (func стартует раньше создания BrowserForm).
                from System import Action
                form, wb = self._native_parts()

                def _subscribe():
                    try:
                        core = wb.CoreWebView2
                        if core is None:
                            return
                        core.NavigationStarting += shell._on_navigation_starting
                        try:
                            # F5/Ctrl+R — браузерные акселераторы (DevTools/меню остаются выключены
                            # отдельными настройками pywebview при debug=False).
                            core.Settings.AreBrowserAcceleratorKeysEnabled = True
                            core.AddScriptToExecuteOnDocumentCreatedAsync(_F11_JS)
                        except Exception:
                            log.warning("[keys] горячие клавиши подключить не удалось")
                        done["ok"] = True
                    except Exception as e:
                        log.error("[nav] подписка не удалась: %s", str(e)[:120])

                form.Invoke(Action(_subscribe))
                if done["ok"]:
                    self._policy_ready.set()
                    log.info("[nav] политика навигации и клавиши подключены")
                    return True
            except Exception:
                pass                                       # форма/контрол ещё не созданы — ждём
            time.sleep(0.2)
        log.error("[nav] CoreWebView2 не стал готов за %.0f c — политика НЕ подключена", deadline_s)
        return False

    def _on_navigation_starting(self, sender, args):
        """ЕДИНСТВЕННЫЙ судья top-level навигаций. Выполняется в UI-потоке — только
        быстрые решения, без блокировок и без Invoke."""
        try:
            uri = str(args.Uri)
            cmd = shsec.parse_shell_command(uri)
            if cmd is not None:
                args.Cancel = True
                # Команды принимаются ТОЛЬКО со страниц оболочки; исключение — явный белый
                # список безвредных оконных действий (F11), разрешённых с любой страницы.
                if self.allowed_origin == "" or cmd[0] in shsec.SHELL_CMD_ANY_PAGE:
                    self._commands.put(cmd)
                else:
                    log.warning("[nav] команда оболочки со страницы сервера отклонена: %s", cmd[0])
                return
            decision, why = shsec.navigation_decision(uri, self.allowed_origin)
            if decision == "allow":
                return
            args.Cancel = True
            safe = shcfg.redact_url_for_log(uri)
            if decision in ("external", "external_app"):
                log.info("[nav] внешняя ссылка -> системное приложение: %s", safe)
                threading.Thread(target=open_in_system_browser, args=(uri,), daemon=True).start()
            else:
                log.warning("[nav] навигация заблокирована (%s): %s", why, safe)
        except Exception:
            try:
                args.Cancel = True               # fail-closed: сомнительная навигация не проходит
            except Exception:
                pass

    def _ui_async(self, fn):
        """Выполнить fn(form, webview) в UI-потоке БЕЗ ожидания (BeginInvoke)."""
        try:
            from System import Action
            form, wb = self._native_parts()
            form.BeginInvoke(Action(lambda: fn(form, wb)))
        except Exception:
            log.debug("[ui] BeginInvoke подавил исключение")

    # ---- статус на стартовой странице (fire-and-forget, без js-моста) ----
    def _status(self, text):
        js = "if(window.fmSetStatus)fmSetStatus(%s)" % json.dumps(str(text))
        self._ui_async(lambda form, wb: wb.CoreWebView2.ExecuteScriptAsync(js)
                       if wb.CoreWebView2 is not None else None)

    # ---- геометрия окна: читается нативно в момент закрытия (UI-поток) ----
    def _on_closing(self):
        """Событие closing pywebview выполняется СИНХРОННО в UI-потоке — читаем WinForms
        напрямую (Invoke не нужен и запрещён: это источник взаимоблокировок закрытия).
        Backend НЕ трогаем: окно закрылось, ферма продолжает работать."""
        try:
            form, _wb = self._native_parts()
            import System.Windows.Forms as WinForms
            maximized = (form.WindowState == WinForms.FormWindowState.Maximized)
            b = form.RestoreBounds if maximized else form.Bounds
            scale = float(getattr(form, "_scale", 1.0) or 1.0)
            st = {"x": int(b.X / scale), "y": int(b.Y / scale),
                  "width": int(b.Width / scale), "height": int(b.Height / scale),
                  "maximized": bool(maximized)}
            if st["width"] >= 200:
                shcfg.save_window_state(self.mode, st)
        except Exception:
            log.debug("[window] сохранение геометрии пропущено")
        log.info("[window] окно закрыто пользователем (backend продолжает работать)")

    # ---- переходы ----
    def go(self, base_url):
        """Открыть интерфейс сервера. Политика навигации обязана быть подключена ДО
        первой серверной страницы (fail-closed: без политики не открываем)."""
        if not self._policy_ready.wait(20.0):
            self.show_error("Внутренняя ошибка оболочки (политика навигации не готова).",
                            address_line=shcfg.redact_url_for_log(base_url))
            return
        # Alpha 2.813: если трей попросил открыть конкретный раздел («#logs» — встроенный журнал),
        # добавляем ЯКОРЬ к своему же адресу. Origin от этого не меняется, поэтому политика
        # навигации остаётся прежней; якорь проверен при разборе аргументов.
        frag = shcfg.normalize_fragment(self.cfg.get("open_fragment"))
        self.target_url = str(base_url).rstrip("/") + "/" + frag
        self.allowed_origin = base_url
        try:
            self.window.load_url(self.target_url)
        except Exception:
            log.error("[nav] load_url не удался")

    def show_error(self, reason_text, address_line="", checked=None, offer_start=False):
        """Показать ошибку подключения. checked — проверенные адреса: пользователю называются
        именно ПОРТЫ (не пути и не команды), чтобы «не отвечает» перестало быть загадкой."""
        ports = []
        for base in (checked or []):
            p = shsec.origin_port(base)
            if p and p not in ports:
                ports.append(p)
        if not address_line and ports:
            address_line = "Проверены порты: " + ", ".join(str(p) for p in ports)
        try:
            self.window.load_html(page_error(reason_text, show_change_server=(self.mode == "client"),
                                             address_line=address_line,
                                             show_start_server=(offer_start and self.mode == "local")))
        except Exception:
            pass

    # ---- worker команд со страниц оболочки ----
    def start_command_worker(self):
        threading.Thread(target=self._command_loop, daemon=True,
                         name="fm-shell-commands").start()

    def _command_loop(self):
        while True:
            try:
                action, params = self._commands.get()
            except Exception:
                return
            try:
                self._handle_command(action, dict(params or {}))
            except Exception:
                log.exception("[cmd] команда %r завершилась ошибкой", action)

    def _handle_command(self, action, params):
        log.info("[cmd] %s", action)
        if action == "retry":
            self.boot(start_server=False)      # перечитать порт и спросить сервер, ничего не запуская
        elif action == "start-server" and self.mode == "local":
            self.boot(start_server=True)
        elif action == "browser":
            # Alpha 2.812: адрес для браузера берётся у ФАКТИЧЕСКИ ответившего сервера, а при его
            # отсутствии — из свежего списка кандидатов. Прежде здесь мог оказаться устаревший
            # первый кандидат (в собранной оболочке — всегда 8000).
            url = self.target_url
            if not url and self.mode == "local":
                found, _st = self.find_running_local()
                url = found or self.local_base_url()
            if not url:
                url = shcfg.load_client_config().get("server_origin") or ""
            if url:
                open_in_system_browser(url.rstrip("/") + "/")
        elif action == "close":
            self._ui_async(lambda form, wb: form.Close())
        elif action == "toggle-fullscreen":
            self._ui_async(lambda form, wb: form.toggle_fullscreen())
        elif action == "change-server" and self.mode == "client":
            shcfg.clear_client_config()
            self.allowed_origin = ""
            self.target_url = ""
            self.window.load_html(page_connect(""))
        elif action == "discover" and self.mode == "client":
            found = discover_servers()
            err = "" if found else "Серверы не найдены. Введите адрес вручную."
            self.window.load_html(page_connect("", error_text=err, found=found))
        elif action == "open-browser" and self.mode == "client":
            origin, err = shsec.normalize_server_url(params.get("url", ""))
            if err:
                self.window.load_html(page_connect("", error_text="Некорректный адрес сервера."))
            else:
                open_in_system_browser(origin + "/")
        elif action == "connect" and self.mode == "client":
            self.client_connect(params.get("url", ""))

    # ---- local mode ----
    def boot(self, start_server=True):
        """Открыть Farm Manager. start_server=False — только найти уже работающий сервер
        (кнопка «Повторить» не должна молча плодить процессы)."""
        if self.mode == "client":
            return self.client_boot()
        # Сначала ищем УЖЕ работающий backend среди кандидатов (ожидающий/рабочий порт из config
        # сервера) — настоящим сервером считается только ответивший `/version`, чужой порт
        # отклоняется. Второй backend не запускаем, если хоть один кандидат ответил.
        base, st = self.find_running_local()
        if base:
            log.info("[local] найден работающий сервер на %s", shcfg.redact_url_for_log(base))
            self.go(base)
            return
        if not start_server:
            # «Повторить»: пользователь мог сам запустить сервер — перечитываем config и
            # проверяем заново, но НИЧЕГО не запускаем.
            self.show_error("Локальный Farm Manager не найден.",
                            checked=self.local_candidate_urls(), offer_start=True)
            return
        # Никто не отвечает — запускаем backend и ждём готовности на первом кандидате (сервер сам
        # применит ожидающий порт по своему startup-контракту).
        candidates = self.local_candidate_urls()
        first = candidates[0]
        st, spawned = ensure_local_backend(first, status_cb=self._status)
        if st in ("ready", "auth"):
            self.go(first)
            return
        # Alpha 2.812: сервер мог подняться НЕ на том порту, который мы выбрали до его старта
        # (применённый ожидающий порт или откат к прежнему). Поэтому после запуска config
        # перечитывается и кандидаты проверяются заново — окно не залипает на старом адресе.
        if spawned:
            self._status("Проверка адреса сервера…")
            base2, _st2 = self.find_running_local()
            if base2:
                log.info("[local] сервер поднялся на другом порту — используем %s",
                         shcfg.redact_url_for_log(base2))
                self.go(base2)
                return
        reasons = {
            "no_backend": "Исполняемый файл Farm Manager не найден рядом с оболочкой.",
            "foreign_port": "Порт занят посторонней программой (это не Farm Manager).",
            "timeout": "Сервер не ответил за отведённое время. Закройте лишние программы и повторите попытку.",
            "spawn_failed": "Не удалось запустить процесс Farm Manager.",
        }
        self.show_error(reasons.get(st, "Неизвестная ошибка запуска."),
                        checked=self.local_candidate_urls())

    # ---- client mode ----
    def client_boot(self):
        saved = shcfg.load_client_config().get("server_origin") or ""
        if self.cfg.get("server_url"):
            origin, err = shsec.normalize_server_url(self.cfg["server_url"])
            if not err:
                saved = origin
        if not saved:
            try:
                self.window.load_html(page_connect(""))
            except Exception:
                pass
            return
        st = probe_farm_manager(saved)
        if st in ("ready", "auth"):
            shcfg.save_client_config(saved)
            self.go(saved)
            return
        msg = ("Порт отвечает, но это не Farm Manager." if st == "foreign"
               else "Сервер не отвечает. Проверьте, что Farm Manager запущен и LAN-доступ включён.")
        self.show_error(msg, address_line=shcfg.redact_url_for_log(saved))

    def client_connect(self, raw):
        """Проверить адрес и подключиться. Ошибка возвращается НА страницу подключения
        (форма остаётся, введённое значение пользователь видит в полях)."""
        origin, err = shsec.normalize_server_url(raw)
        if err:
            errors = {"empty": "Введите адрес сервера.",
                      "bad_scheme": "Допустимы только http и https.",
                      "credentials_in_url": "Логин и пароль в адресе не допускаются.",
                      "query_not_allowed": "Уберите параметры (?…) из адреса.",
                      "fragment_not_allowed": "Уберите фрагмент (#…) из адреса.",
                      "path_not_allowed": "Укажите только адрес и порт, без пути.",
                      "bad_port": "Неверный порт.", "bad_host": "Неверный адрес сервера.",
                      "no_host": "Введите адрес сервера.", "invalid_url": "Неверный адрес сервера."}
            msg = errors.get(err, "Неверный адрес сервера.")
            try:
                self.window.load_html(page_connect("", error_text=msg))
            except Exception:
                pass
            return {"error": msg}
        st = probe_farm_manager(origin)
        if st == "down":
            msg = "Сервер не отвечает. Проверьте адрес, сеть и LAN-доступ на сервере."
            try:
                self.window.load_html(page_connect("", error_text=msg))
            except Exception:
                pass
            return {"error": msg}
        if st == "foreign":
            msg = "По этому адресу отвечает не Farm Manager."
            try:
                self.window.load_html(page_connect("", error_text=msg))
            except Exception:
                pass
            return {"error": msg}
        shcfg.save_client_config(origin)                  # сохраняется ТОЛЬКО origin
        log.info("[client] подключение к %s (%s)", shcfg.redact_url_for_log(origin), st)
        self.go(origin)
        return {"ok": True}


# ── запуск ────────────────────────────────────────────────────────────────────

def _set_dpi_aware():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)     # PER_MONITOR_DPI_AWARE
    except Exception:
        pass


def _virtual_screen():
    """(x, y, w, h) виртуального экрана (все мониторы), для клампинга сохранённого окна."""
    try:
        import ctypes
        g = ctypes.windll.user32.GetSystemMetrics
        return (int(g(76)), int(g(77)), int(g(78)), int(g(79)))
    except Exception:
        return (0, 0, 1920, 1080)


def run_window(shell):
    """Создать окно и войти в GUI-цикл (блокирует до закрытия окна)."""
    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True             # SaveFileDialog, без автозапуска файла
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False   # решает наша политика навигации
    webview.settings["ALLOW_FILE_URLS"] = False

    title = shcfg.APP_TITLE_CLIENT if shell.mode == "client" else shcfg.APP_TITLE_LOCAL
    saved = {} if shell.cfg.get("reset_window_state") else shcfg.load_window_state(shell.mode)
    st = shcfg.clamp_window_state(saved, _virtual_screen())
    icon = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "web", "assets", "icon.ico")
    kwargs = dict(width=st["width"], height=st["height"],
                  min_size=shcfg.MIN_WINDOW, background_color="#0b1118",
                  maximized=bool(st["maximized"]))
    if st["x"] is not None and st["y"] is not None:
        kwargs["x"], kwargs["y"] = st["x"], st["y"]
    shell.window = webview.create_window(title, html=page_starting(), **kwargs)
    shell.window.events.closing += shell._on_closing

    def _boot_bg():
        try:
            # 1) политика навигации и клавиши — ДО первой серверной страницы (fail-closed);
            # 2) очередь команд страниц оболочки; 3) обнаружение/запуск backend.
            shell._attach_native_handlers()
            shell.start_command_worker()
            shell.boot()
        except Exception:
            log.exception("[boot] сбой запуска оболочки")
            shell.show_error("Внутренняя ошибка оболочки. Подробности — в журнале оболочки.")

    debug = bool(shell.cfg.get("debug"))
    log.info("[start] режим=%s, debug=%s, версия оболочки %s", shell.mode, debug, shcfg.SHELL_VERSION)
    webview.start(func=_boot_bg, private_mode=False,
                  storage_path=shcfg.profile_dir(shell.mode),
                  icon=(icon if os.path.isfile(icon) else None),
                  debug=debug)


def open_browser_flow(cfg):
    """Ярлык «— браузер»: гарантировать backend и открыть системный браузер. Без WebView2.

    Alpha 2.812: тот же резолвер, что и у окна. Сначала ищем уже работающий сервер среди
    кандидатов и открываем ИМЕННО его адрес; только если никто не ответил — запускаем backend и
    после запуска перечитываем порт (сервер мог применить ожидающий или откатиться к прежнему)."""
    shell = DesktopShell(cfg)
    base, st = shell.find_running_local()
    if base:
        open_in_system_browser(base + "/")
        return 0
    first = shell.local_base_url()
    st, spawned = ensure_local_backend(first)
    if st not in ("ready", "auth") and spawned:
        found, _st2 = shell.find_running_local()
        if found:
            open_in_system_browser(found + "/")
            return 0
    open_in_system_browser(first + "/")
    return 0 if st in ("ready", "auth") else 1


def main(argv=None, default_mode="local"):
    """Точка входа оболочки. -> код возврата процесса."""
    cfg = shcfg.parse_args(list(sys.argv[1:] if argv is None else argv), default_mode=default_mode)
    setup_logging(cfg["mode"], cfg["debug"])
    _set_dpi_aware()

    if cfg["mode"] == "local" and cfg.get("open_browser"):
        return open_browser_flow(cfg)

    title = shcfg.APP_TITLE_CLIENT if cfg["mode"] == "client" else shcfg.APP_TITLE_LOCAL
    if not acquire_shell_mutex(cfg["mode"]):
        activate_existing_window(title)
        log.info("[start] окно уже открыто — активировано существующее")
        return 0

    if not has_webview2_runtime():
        log.warning("[start] WebView2 Runtime не найден — предлагаем браузер")
        want = message_box("3DIWELL Farm Manager",
                           "Для собственного окна требуется Microsoft Edge WebView2 Runtime.\n"
                           "Открыть Farm Manager в обычном браузере?", yesno=True)
        if want:
            if cfg["mode"] == "local":
                return open_browser_flow(cfg)
            saved = shcfg.load_client_config().get("server_origin")
            if saved:
                open_in_system_browser(saved + "/")
        return 2

    shell = DesktopShell(cfg)
    try:
        run_window(shell)
        return 0
    except Exception as e:
        log.error("[start] окно не создано: %s", str(e)[:160])
        want = message_box("3DIWELL Farm Manager",
                           "Не удалось открыть окно Farm Manager.\nОткрыть в обычном браузере?",
                           yesno=True)
        if want and cfg["mode"] == "local":
            return open_browser_flow(cfg)
        return 3
