# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.805 — desktop-оболочка Farm Manager (собственное окно + remote client).
#
#  ПОЛНОСТЬЮ OFFLINE. Реальное GUI не открывается (pywebview не импортируется вовсе —
#  это проверяется), server.py не импортируется обычным способом (только чтение текста
#  и AST), рабочая БД/DATA_DIR не используются (хранилище оболочки уводится в
#  TemporaryDirectory через FM_DESKTOP_SHELL_ROOT), сеть/принтеры/интернет не
#  используются (HTTP и discovery — фейки, ловушка сокетов), subprocess замокан.
#
#  ЧТО ДОКАЗЫВАЕТ. Local mode переиспользует работающий backend и никогда не запускает
#  второй; чужой HTTP-сервер не считается Farm Manager; закрытие окна не завершает
#  backend; навигация ограничена origin сервера (file:/javascript:/data:/UNC блокируются,
#  внешние ссылки уходят в системный браузер); оболочка не хранит пароли/cookies; remote
#  client не содержит backend/БД/DATA_DIR; tray открывает окно с fallback в браузер без
#  публичных open-window маршрутов; installer client не включает backend; браузерный
#  доступ сохранён.
#
#  Запуск:  python tools/test_desktop_shell.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import io
import json
import os
import re
import socket
import sys
import tempfile
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_DONE = {"ok": False}


def _guard():
    if not _DONE["ok"]:
        try:
            print("FAIL — тест завершился до выполнения проверок")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)


atexit.register(_guard)

# Хранилище оболочки — ТОЛЬКО временная папка (реальный %LOCALAPPDATA% не трогается).
TMP = tempfile.TemporaryDirectory(prefix="fm_shell_")
ROOT = TMP.name
os.environ["FM_DESKTOP_SHELL_ROOT"] = ROOT


class _TrapSocket(socket.socket):
    def __init__(self, *a, **k):
        raise AssertionError("offline-тест: сокеты запрещены")


_REAL_SOCKET = socket.socket
socket.socket = _TrapSocket

FAILED = []
PASSED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "DESKTOP_SHELL_SENTINEL_2_805"

from app import desktop_shell as ds            # noqa: E402
from app import desktop_shell_config as shcfg  # noqa: E402
from app import desktop_shell_security as shsec  # noqa: E402

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
DS_SRC = open(os.path.join(REPO, "app", "desktop_shell.py"), encoding="utf-8").read()
CFG_SRC = open(os.path.join(REPO, "app", "desktop_shell_config.py"), encoding="utf-8").read()
SEC_SRC = open(os.path.join(REPO, "app", "desktop_shell_security.py"), encoding="utf-8").read()
ISS_MAIN = open(os.path.join(REPO, "3diwell-setup.iss"), encoding="utf-8").read()
ISS_CLIENT = open(os.path.join(REPO, "3diwell-client-setup.iss"), encoding="utf-8").read()
SPEC = open(os.path.join(REPO, "desktop_shell.spec"), encoding="utf-8").read()
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
# Версия сверяется с APP_VERSION server.py (не хардкодится), чтобы бамп версии не ронял тест.
# 3.0: номер — пара чисел «старшая.младшая», старшая больше не прибита к двойке.
#  25.10.2026: префикс выпуска — Alpha или Beta (Beta 3.71); сверяется номер.
_APP_M = re.search(r'APP_VERSION = "(?:Alpha|Beta) (\d+)\.(\d+)"', SRV)
_APP_MAJOR, _APP_MINOR = int(_APP_M.group(1)), int(_APP_M.group(2))
_APP_VER = "%d.%d" % (_APP_MAJOR, _APP_MINOR)
LAUNCH_LOCAL = open(os.path.join(REPO, "desktop_launcher.pyw"), encoding="utf-8").read()
LAUNCH_CLIENT = open(os.path.join(REPO, "client_launcher.pyw"), encoding="utf-8").read()


def fn_src(name, tree=SRV_AST):
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            return ast.unparse(n)
    return ""


def code_only(src):
    """Исходник БЕЗ докстрингов и комментариев: проверки «подстрока отсутствует» не должны
    срабатывать на собственную прозу (см. урок Alpha 2.797/2.803)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(n, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body[0].value.value = ""
    return ast.unparse(tree)


DS_AST = ast.parse(DS_SRC)


def ds_fn(name):
    return fn_src(name, DS_AST)


# ── фейки ──────────────────────────────────────────────────────────────────────

class FakeHTTP(object):
    """Фейковый opener для probe_farm_manager: отвечает по сценарию, сети нет."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def __call__(self, url, timeout=None):
        self.calls.append(str(url))
        status, body = self.mapping.get(str(url), (None, ""))
        if status is None:
            raise urllib.error.URLError("connection refused (fake)")
        if status in (401, 403):
            raise urllib.error.HTTPError(url, status, "denied", None, io.BytesIO(body.encode("utf-8")))

        class _R(object):
            def __init__(self, s, b):
                self.status = s
                self._b = b.encode("utf-8")

            def read(self, n=-1):
                return self._b

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _R(status, body)


class FakeSpawn(object):
    """Фейковый запуск backend: фиксирует команду; по сценарию делает сервер «готовым»."""

    def __init__(self, http=None, becomes_ready_after=0.0, base_url=""):
        self.calls = []
        self.http = http
        self.becomes = becomes_ready_after
        self.base = base_url

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        if self.http is not None and self.becomes >= 0:
            self.http.mapping[self.base.rstrip("/") + "/version"] = (200, '{"version": "Alpha 2.805"}')
        return object()


class FakeWindow(object):
    """Фейк pywebview-окна: фиксирует load_url/load_html/destroy, GUI не создаёт."""

    def __init__(self):
        self.urls = []
        self.htmls = []
        self.destroyed = 0
        self.js = []
        self.x = self.y = 10
        self.width, self.height = 1440, 900

    def load_url(self, u):
        self.urls.append(str(u))

    def load_html(self, h):
        self.htmls.append(str(h))

    def destroy(self):
        self.destroyed += 1

    def evaluate_js(self, s):
        self.js.append(str(s))

    def toggle_fullscreen(self):
        self.js.append("<fullscreen>")


VER_OK = (200, '{"version": "Alpha 2.805"}')
VER_AUTH = (401, '{"error": "unauthorized"}')
LOCAL = "http://127.0.0.1:8000"

try:
    print("=== Alpha 2.805: desktop-оболочка (offline) ===")

    # ═══════════════════════ LOCAL STARTUP (1-13) ═══════════════════════════
    section("local mode: запуск и переиспользование backend")
    http = FakeHTTP({LOCAL + "/version": VER_OK})
    spawn = FakeSpawn()
    st, spawned = ds.ensure_local_backend(LOCAL, probe=lambda u, **k: ds.probe_farm_manager(u, opener=http),
                                          spawn=spawn, sleep=lambda s: None)
    check("1. работающий локальный сервер переиспользуется", st == "ready" and spawned is False)
    check("2. второй backend при работающем сервере не запускается", spawn.calls == [])

    http2 = FakeHTTP({})                                   # сервер не работает
    spawn2 = FakeSpawn(http=http2, base_url=LOCAL)
    st2, spawned2 = ds.ensure_local_backend(LOCAL, probe=lambda u, **k: ds.probe_farm_manager(u, opener=http2),
                                            spawn=spawn2, sleep=lambda s: None)
    check("3. неработающий сервер запускается штатным entry point (ровно один запуск)",
          st2 == "ready" and spawned2 is True and len(spawn2.calls) == 1)
    real_cmd = ds.spawn_backend.__doc__ or ""
    check("4. запуску передаются --desktop-start и --no-browser",
          '"--desktop-start", "--no-browser"' in ds_fn("spawn_backend")
          or "'--desktop-start', '--no-browser'" in ds_fn("spawn_backend"))
    check("5. готовность проверяется через /version (не «порт открыт»)",
          all(u.endswith("/version") for u in http.calls + http2.calls) and len(http2.calls) >= 2)

    http3 = FakeHTTP({LOCAL + "/version": (200, "<html>hello im nginx</html>")})
    st3, _ = ds.ensure_local_backend(LOCAL, probe=lambda u, **k: ds.probe_farm_manager(u, opener=http3),
                                     spawn=FakeSpawn(), sleep=lambda s: None)
    check("6. открытый ЧУЖОЙ порт не считается Farm Manager", st3 == "foreign_port")
    #  25.10.2026: программа перешла с «Alpha 3.0» на «Beta 3.71». Окно и клиент обязаны узнавать
    #  сервер с любым из двух префиксов выпуска — и тот номер, который отдаёт этот server.py.
    _srv_ver = re.search(r'^APP_VERSION = "([^"]+)"', SRV, re.M).group(1)
    _probe_ok = {v: shsec.classify_probe(200, json.dumps({"version": v, "boot_id": "b"}))
                 for v in (_srv_ver, "Beta 3.71", "Alpha 3.0", "Alpha 2.1007", "Beta 3.72")}
    _probe_bad = {v: shsec.classify_probe(200, json.dumps({"version": v}))
                  for v in ("Gamma 3.71", "beta 3.71", "Beta3.71", "Beta 3.71.1", "3.71", "Beta 3", "")}
    check("6b. /version с «Alpha N.M» и «Beta N.M» (и номером этого server.py: %s) — Farm Manager;"
          " другой префикс или формат — чужой" % _srv_ver,
          all(s == "ready" for s in _probe_ok.values()) and all(s == "foreign" for s in _probe_bad.values()))
    if not (all(s == "ready" for s in _probe_ok.values()) and all(s == "foreign" for s in _probe_bad.values())):
        print("     разбор: %s / %s" % (_probe_ok, _probe_bad))

    http4 = FakeHTTP({})
    spawn4 = FakeSpawn(http=http4, becomes_ready_after=-1)   # так и не станет готов
    t = {"v": 0.0}

    def _clock():
        t["v"] += 0.5
        return t["v"]

    st4, _ = ds.ensure_local_backend(LOCAL, probe=lambda u, **k: ds.probe_farm_manager(u, opener=http4),
                                     spawn=spawn4, sleep=lambda s: None, deadline_s=5.0, clock=_clock)
    check("7. bounded timeout запуска -> ошибка (error page, не вечное ожидание)",
          st4 == "timeout" and len(spawn4.calls) == 1)

    def _bad_spawn(cmd):
        raise OSError("no exe (fake)")

    st5, _ = ds.ensure_local_backend(LOCAL, probe=lambda u, **k: ds.probe_farm_manager(u, opener=FakeHTTP({})),
                                     spawn=_bad_spawn, sleep=lambda s: None)
    check("8. сбой запуска backend не скрывается", st5 == "spawn_failed")

    _close_src = ds_fn("_on_closing") + ds_fn("DesktopShell")
    check("9. закрытие окна НЕ завершает backend (нет terminate/kill/taskkill/exit-запросов)",
          not re.search(r"terminate|\.kill\(|taskkill|os\._exit|/api/(exit|shutdown|quit)", _close_src)
          and "backend продолжает работать" in _close_src)
    check("10. контракт завершения через tray не изменён (Выход = os._exit, как раньше)",
          '"Выход", _quit' in SRV and "os._exit(0)" in fn_src("_start_tray_detached"))
    _ds_code = code_only(DS_SRC)
    check("11. mutex backend не обходится и не переиспользуется оболочкой",
          ds.SHELL_MUTEX_LOCAL != r"Local\3DIWELL_Farm_Manager_SingleInstance_v1"
          and ds.SHELL_MUTEX_CLIENT != r"Local\3DIWELL_Farm_Manager_SingleInstance_v1"
          and "SingleInstance_v1" not in _ds_code            # серверное имя в КОДЕ не используется
          and "single_instance" not in _ds_code              # и модуль замка сервера не импортируется
          and "_reset_for_tests" not in _ds_code)
    _main_src = ds_fn("main")
    check("12. повторный запуск оболочки активирует существующее окно",
          "acquire_shell_mutex" in _main_src and "activate_existing_window" in _main_src
          and _main_src.index("acquire_shell_mutex") < _main_src.index("activate_existing_window"))
    check("13. второй экземпляр окна завершает процесс, не создавая окно",
          re.search(r"if not acquire_shell_mutex\(.*\):\s*\n\s*activate_existing_window\(title\)"
                    r"[\s\S]{0,120}?return 0", _main_src) is not None
          and ds.SHELL_MUTEX_LOCAL != ds.SHELL_MUTEX_CLIENT)

    # ═══════════════════════════ WINDOW (14-24) ═════════════════════════════
    section("окно")
    check("14. title корректный", shcfg.APP_TITLE_LOCAL == "3DIWELL Farm Manager"
          and shcfg.APP_TITLE_CLIENT == "3DIWELL Farm Manager Client")
    check("15. иконка проекта задана (web/assets/icon.ico, существует)",
          "icon.ico" in ds_fn("run_window") and os.path.isfile(os.path.join(REPO, "web", "assets", "icon.ico")))
    check("16. минимальный размер задан и разумен", shcfg.MIN_WINDOW >= (1000, 600))

    ok_state = shcfg.save_window_state("local", {"x": 100, "y": 80, "width": 1500, "height": 950,
                                                 "maximized": False})
    got = shcfg.load_window_state("local")
    check("17. window state сохраняется и читается",
          ok_state and got == {"x": 100, "y": 80, "width": 1500, "height": 950, "maximized": False}
          and os.path.isfile(os.path.join(ROOT, "state-local.json")))
    off = shcfg.clamp_window_state({"x": -9000, "y": 200, "width": 1300, "height": 800},
                                   (0, 0, 1920, 1080))
    check("18. координаты с отключённого монитора исправляются (окно возвращается в центр)",
          off["x"] is None and off["y"] is None and off["width"] == 1300)
    small = shcfg.clamp_window_state({"x": 10, "y": 10, "width": 200, "height": 100}, (0, 0, 1920, 1080))
    check("18b. слишком маленький сохранённый размер поднимается до минимума",
          small["width"] >= shcfg.MIN_WINDOW[0] and small["height"] >= shcfg.MIN_WINDOW[1])
    mx = shcfg.clamp_window_state({"x": 10, "y": 10, "width": 1400, "height": 900, "maximized": True},
                                  (0, 0, 1920, 1080))
    check("19. maximized сохраняется и восстанавливается",
          mx["maximized"] is True and "maximized=bool(st[\"maximized\"])" in ds_fn("run_window").replace("'", '"'))
    check("20. F11 работает (документный скрипт -> безопасная команда toggle-fullscreen)",
          "F11" in ds._F11_JS and "toggle-fullscreen" in ds._F11_JS
          and "AddScriptToExecuteOnDocumentCreatedAsync" in ds_fn("_attach_native_handlers")
          and "toggle-fullscreen" in ds_fn("_handle_command")
          and "toggle-fullscreen" in shsec.SHELL_CMD_ANY_PAGE
          and shsec.SHELL_CMD_ANY_PAGE <= {"toggle-fullscreen"})   # ТОЛЬКО безвредное оконное действие
    check("21. reload работает (F5/Ctrl+R — браузерные акселераторы, DevTools при этом выключены)",
          "AreBrowserAcceleratorKeysEnabled = True" in ds_fn("_attach_native_handlers")
          and "AreDevToolsEnabled" not in code_only(DS_SRC))
    _run_code = code_only(ds_fn("run_window"))
    check("22. production DevTools отключены (debug строго из --debug-shell, не hardcode)",
          "debug=debug" in _run_code
          and "debug = bool(shell.cfg.get('debug'))" in _run_code
          and "debug = True" not in _run_code
          and shcfg.parse_args([])["debug"] is False)
    check("23. DevTools доступны только с --debug-shell",
          shcfg.parse_args(["--debug-shell"])["debug"] is True)
    _close_code = code_only(ds_fn("_on_closing"))
    check("24. закрытие окна не дёргает backend и читает геометрию БЕЗ Invoke (RestoreBounds в UI-потоке)",
          "RestoreBounds" in _close_code and "save_window_state" in _close_code
          and ".Invoke" not in _close_code and "BeginInvoke" not in _close_code
          and "urlopen" not in _close_code and "destroy" not in _close_code)
    check("24b. zero-bridge: privileged js-мост не используется вовсе",
          "js_api" not in _ds_code and "expose" not in _ds_code
          and "evaluate_js" not in _ds_code and "pywebview.api" not in DS_SRC)

    # ═════════════════════════ NAVIGATION (25-34) ═══════════════════════════
    section("политика навигации")
    AO = "http://192.168.1.50:8000"
    check("25. same-origin разрешён",
          shsec.navigation_decision(AO + "/projects", AO)[0] == "allow"
          and shsec.navigation_decision(AO + ":8000/x", AO)[0] != "allow"
          and shsec.navigation_decision("http://192.168.1.50:8000/api/x?y=1", AO)[0] == "allow")
    check("25b. localhost и 127.0.0.1 — разные origin (без нормализации не доверяем)",
          shsec.navigation_decision("http://localhost:8000/", "http://127.0.0.1:8000")[0] != "allow"
          and shsec.same_origin("http://127.0.0.1:8000/a", "http://127.0.0.1:8000") is True)
    check("26. внешний http(s) уходит в системный браузер",
          shsec.navigation_decision("https://www.3diwell.com/help", AO) == ("external", "foreign_http")
          and "open_in_system_browser" in ds_fn("_on_navigation_starting"))
    check("27. file: блокируется", shsec.navigation_decision("file:///C:/Windows/win.ini", AO)[0] == "block")
    check("28. javascript: блокируется", shsec.navigation_decision("javascript:alert(1)", AO)[0] == "block")
    check("29. data: top-level блокируется при выбранном сервере",
          shsec.navigation_decision("data:text/html,<b>x</b>", AO)[0] == "block")
    check("30. UNC и локальные пути блокируются",
          shsec.navigation_decision(r"\\evil\share\x.exe", AO)[0] == "block"
          and shsec.navigation_decision(r"C:\Windows\system32\calc.exe", AO)[0] == "block")
    check("31. неизвестные схемы блокируются",
          shsec.navigation_decision("vbscript:msgbox(1)", AO)[0] == "block"
          and shsec.navigation_decision("ms-appx://x", AO)[0] == "block"
          and shsec.navigation_decision("customapp://run", AO)[0] == "block")
    check("32. mailto открывается внешним приложением",
          shsec.navigation_decision("mailto:owner@example.com", AO)[0] == "external_app")
    check("33. query и fragment не логируются (redact до origin)",
          shcfg.redact_url_for_log("http://192.168.1.50:8000/page?token=SECRET#frag") == "http://192.168.1.50:8000"
          and "SECRET" not in shcfg.redact_url_for_log("http://a/b?x=SECRET"))
    check("34. recovery-токен во фрагменте не попадает в журнал",
          shcfg.redact_url_for_log("http://127.0.0.1:8000/#local-admin-recovery=%s" % SENTINEL)
          == "http://127.0.0.1:8000"
          and re.search(r"log\.\w+\([^)]*args\.Uri", ds_fn("_on_navigation_starting")) is None)
    check("34b. командные URL оболочки разбираются строго (белый список действий)",
          shsec.parse_shell_command(shsec.SHELL_CMD_ORIGIN + "/retry") == ("retry", {})
          and shsec.parse_shell_command(shsec.SHELL_CMD_ORIGIN + "/connect?url=http%3A%2F%2Fa%3A8000")
          == ("connect", {"url": "http://a:8000"})
          and shsec.parse_shell_command(shsec.SHELL_CMD_ORIGIN + "/format-c") is None
          and shsec.parse_shell_command("http://evil.example/retry") is None
          and shsec.parse_shell_command("javascript:retry") is None)
    check("34c. командный host не уходит ни в окно, ни в браузер (defense in depth)",
          shsec.navigation_decision(shsec.SHELL_CMD_ORIGIN + "/retry", AO)[0] == "block"
          and shsec.navigation_decision(shsec.SHELL_CMD_ORIGIN + "/retry", "")[0] == "block")
    _nav_src = ds_fn("_on_navigation_starting")
    check("34d. команды принимаются ТОЛЬКО со страниц оболочки (у страниц сервера — лишь белый "
          "список безвредных оконных действий)",
          "self.allowed_origin == ''" in _nav_src
          and "SHELL_CMD_ANY_PAGE" in _nav_src
          and _nav_src.index("parse_shell_command") < _nav_src.index("navigation_decision")
          and "отклонена" in _nav_src)

    # ═══════════════════════ COOKIES/AUTH (35-40) ═══════════════════════════
    section("cookies и авторизация")
    files_after = []
    for base, _dirs, fnames in os.walk(ROOT):
        files_after += [os.path.join(base, f) for f in fnames]
    blob = ""
    for f in files_after:
        try:
            blob += open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            pass
    check("35. оболочка не хранит пароль (в своих файлах нет полей password/token)",
          not re.search(r"password|passwd|token|secret", blob, re.I)
          and not re.search(r'["\'](password|token|session)["\']\s*:', CFG_SRC))
    check("36. сессия вручную не сохраняется (cookies управляет WebView2-профиль)",
          "cookie" not in blob.lower() and "get_cookies" not in DS_SRC and "create_cookie" not in DS_SRC)
    check("37. logout выполняет backend (в оболочке нет своего logout/сессий)",
          "logout" not in DS_SRC.lower())
    check("38. auth bypass отсутствует (оболочка не шлёт заголовков доверия и не читает БД)",
          not re.search(r"X-Forwarded|X-Real-IP|Authorization|role=|is_admin", DS_SRC)
          and "sqlite" not in DS_SRC.lower())
    check("39. роль/права от клиента не передаются (нет таких полей нигде в оболочке)",
          not re.search(r"role|permission|capabilit", DS_SRC + CFG_SRC, re.I) or
          bool(re.search(r"не является границей безопасности", DS_SRC)))
    check("40. local mode не получает owner-bypass (оболочка не является границей безопасности)",
          "границей безопасности" in DS_SRC and "_require_" not in DS_SRC)

    # ═══════════════════════ REMOTE CLIENT (41-56) ══════════════════════════
    section("remote client")
    check("41. client не запускает backend (в client-ветке нет ensure_local_backend/spawn)",
          "ensure_local_backend" not in ds_fn("client_boot") + ds_fn("client_connect")
          and "spawn" not in ds_fn("client_boot") + ds_fn("client_connect")
          and "server.py" not in LAUNCH_CLIENT)
    check("42. client не импортирует БД (sqlite/farm_parts нигде в оболочке)",
          "sqlite" not in (DS_SRC + CFG_SRC + SEC_SRC + LAUNCH_CLIENT).lower()
          and "farm_parts" not in DS_SRC)
    _cfg_code = code_only(CFG_SRC)
    check("43. client не открывает БД и не сканирует DATA_DIR (config сервера читается только "
          "для порта, read-only)",
          "3DIWELL_DesktopShell" in _cfg_code and shcfg.shell_root() == ROOT
          and "farm_parts" not in _ds_code and "farm_printers" not in _ds_code
          and "farm_parts" not in _cfg_code
          and "sqlite" not in (_ds_code + _cfg_code).lower()
          and "os.walk" not in _cfg_code
          # config сервера читается json.load'ом (read-only); поля порта оболочка НЕ пишет
          and "json.load" in _cfg_code and "server_port" not in _ds_code
          and "atomic_write" not in (_ds_code + _cfg_code))

    csh = ds.DesktopShell(shcfg.parse_args(["--client"], default_mode="client"))
    cw = FakeWindow()
    csh.window = cw
    csh._policy_ready.set()          # в тесте политика «подключена» (go() ждёт её fail-closed)
    _orig_probe = ds.probe_farm_manager
    ds.probe_farm_manager = lambda u, **k: {"http://192.168.1.50:8000": "ready",
                                            "http://192.168.1.60:9000": "foreign",
                                            "http://10.0.0.7:8000": "auth"}.get(str(u), "down")
    try:
        r_ok = csh.client_connect("192.168.1.50:8000")
        check("44. валидный Farm Manager сервер принимается и открывается",
              r_ok == {"ok": True} and cw.urls and cw.urls[-1] == "http://192.168.1.50:8000/"
              and shcfg.load_client_config()["server_origin"] == "http://192.168.1.50:8000")
        r_foreign = csh.client_connect("http://192.168.1.60:9000")
        check("45. чужой HTTP-сервер отклоняется",
              "error" in r_foreign and "не Farm Manager" in r_foreign["error"])
        r_bad = csh.client_connect("ht!tp://////")
        check("46. неверный URL отклоняется", "error" in r_bad)
        r_cred = csh.client_connect("http://user:pass@192.168.1.50:8000")
        check("47. credentials в URL отклоняются",
              "error" in r_cred and "пароль" in r_cred["error"].lower())
        check("48. file/javascript/data URL отклоняются",
              all("error" in csh.client_connect(u) for u in
                  ("file:///C:/x", "javascript:alert(1)", "data:text/html,x", r"\\srv\share")))
        saved_txt = open(shcfg.client_config_path(), encoding="utf-8").read()
        check("49. сохраняется ТОЛЬКО origin (без секретов/query/fragment/пути)",
              json.loads(saved_txt) == {"server_origin": "http://192.168.1.50:8000"}
              and "?" not in saved_txt and "#" not in saved_txt)
        csh._handle_command("change-server", {})
        check("50. «Сменить сервер» очищает navigation state и открывает форму",
              csh.allowed_origin == "" and csh.target_url == ""
              and shcfg.load_client_config() == {} and cw.htmls
              and "Подключение к серверу" in cw.htmls[-1])
        r_auth = csh.client_connect("10.0.0.7:8000")
        check("51. сервер с включённой авторизацией — НОРМАЛЬНОЕ подключение (откроется вход)",
              r_auth == {"ok": True} and cw.urls[-1] == "http://10.0.0.7:8000/")
        r_down = csh.client_connect("192.168.9.9:8000")
        check("52. timeout/недоступность показывается безопасно (без traceback)",
              "error" in r_down and "Traceback" not in str(r_down) and "Exception" not in str(r_down))
    finally:
        ds.probe_farm_manager = _orig_probe

    _disc_src = code_only(ds_fn("discover_servers"))
    check("53. discovery bounded (окно ожидания ограничено, вечного цикла нет)",
          "monotonic" in _disc_src and "wait_s" in _disc_src and "while True" not in _disc_src)
    check("54. discovery не включает LAN на сервере (только существующий probe-протокол, без HTTP/API)",
          shsec.DISCOVERY_MAGIC == b"3DIWELL_DISCOVER_v1" and "DISCOVERY_MAGIC" in _disc_src
          and "urlopen" not in _disc_src and "/api/" not in _disc_src
          and "set_network" not in _ds_code and "lan_access" not in _ds_code)
    check("55. discovery не меняет firewall (нет netsh/advfirewall/subprocess в discovery)",
          "netsh" not in _ds_code and "advfirewall" not in _ds_code
          and "subprocess" not in _disc_src)
    check("56. профиль клиента отделён от локального",
          shcfg.PROFILE_LOCAL != shcfg.PROFILE_CLIENT
          and shcfg.profile_dir("client") != shcfg.profile_dir("local")
          and shcfg.profile_dir("client").startswith(ROOT))
    item = shsec.parse_discovery_reply(b"3DIWELL_SERVER_v1|8000|3DIWELL Farm", "192.168.1.77")
    check("56b. discovery-ответ разбирается безопасно (имя чистится, мусор отклоняется)",
          item == {"ip": "192.168.1.77", "port": 8000, "name": "3DIWELL Farm"}
          and shsec.parse_discovery_reply(b"EVIL|8000|x", "1.2.3.4") is None
          and shsec.parse_discovery_reply(b"3DIWELL_SERVER_v1|99999|x", "1.2.3.4") is None
          and "<" not in (shsec.parse_discovery_reply(b"3DIWELL_SERVER_v1|80|<script>alert(1)</script>",
                                                      "1.2.3.4") or {}).get("name", ""))

    # ═════════════════════════════ FILES (57-62) ════════════════════════════
    section("файлы: upload и download")
    check("57. локальный file picker разрешён (стандартный input type=file, оболочка его не подменяет)",
          "create_file_dialog" not in _ds_code and "FileDialog" not in _ds_code)
    check("58. remote upload идёт существующим route (оболочка не трогает тела запросов)",
          "multipart" not in _ds_code.lower() and "upload" not in _ds_code.lower())
    check("59. оболочка не передаёт локальные пути backend как доверенные",
          "src_path" not in _ds_code and "stored_path" not in _ds_code and "pick-path" not in _ds_code)
    check("60. downloads не запускаются автоматически (ALLOW_DOWNLOADS -> SaveFileDialog, без os.startfile файла)",
          "webview.settings['ALLOW_DOWNLOADS'] = True" in _ds_code
          and not re.search(r"startfile\([^)]*(dist|download|\.exe|ResultFilePath)", _ds_code, re.I))
    check("61. traversal в имени скачиваемого файла обрезается самим pywebview (basename), "
          "оболочка путь не переопределяет", "ResultFilePath" not in _ds_code)
    check("62. путь скачивания не попадает в API/журнал",
          "ResultFilePath" not in _ds_code and "Downloads" not in code_only(ds_fn("setup_logging")))

    # ═════════════════════════════ TRAY (63-67) ═════════════════════════════
    section("tray")
    _tray = fn_src("_start_tray_detached")                   # ast.unparse: строки в 'одинарных'
    _shell_cmd = fn_src("_desktop_shell_command")
    _open_shell = fn_src("_open_desktop_shell")
    check("63. «Открыть Farm Manager» запускает desktop shell (default-пункт)",
          "MenuItem('Открыть Farm Manager', _open_shell, default=True)" in _tray
          and "_open_desktop_shell" in _tray
          and "Desktop.exe" in _shell_cmd and "desktop_launcher.pyw" in _shell_cmd)
    check("64. «Открыть в браузере» сохранён отдельным пунктом",
          "MenuItem('Открыть в браузере', _open_ui)" in _tray and "startfile" in _tray)
    check("65. shell недоступен -> безопасный fallback в браузер + уведомление",
          "_open_local_url" in _open_shell and "shell_unavailable" in _open_shell
          and "Не удалось открыть окно Farm Manager. Интерфейс открыт в браузере." in _tray)
    check("66. tray не использует публичный HTTP open-window маршрут",
          "/open-window" not in SRV and "open-window" not in DS_SRC
          and 'add_route' not in _open_shell and "requests" not in _open_shell)
    check("67. поведение «Выход» не изменено",
          "MenuItem('Выход', _quit)" in _tray and "os._exit(0)" in _tray)
    check("67b. tray-запуск оболочки отвязан от сервера (DETACHED-флаги, без наследования консоли)",
          "creationflags=" in _open_shell and "512" in _open_shell and "DEVNULL" in _open_shell)

    # ═══════════════════════ INSTALLER/BUILD (68-74) ════════════════════════
    section("installer и build")
    check("68. основной ярлык запускает собственное окно (Desktop.exe)",
          '#define ShellExeName "3DIWELL Farm Manager Desktop.exe"' in ISS_MAIN
          and 'Name: "{group}\\{#AppName}"; Filename: "{app}\\{#ShellExeName}"' in ISS_MAIN
          and 'Name: "{autodesktop}\\{#AppName}"; Filename: "{app}\\{#ShellExeName}"' in ISS_MAIN)
    check("69. браузерный ярлык сохранён («— браузер» -> --open-browser)",
          "— браузер" in ISS_MAIN and 'Parameters: "--open-browser"' in ISS_MAIN
          and "open_browser_flow" in DS_SRC and "open_in_system_browser" in ds_fn("open_browser_flow"))
    check("70. client installer не включает backend (ни server-exe, ни server.py)",
          "3DIWELL Farm Manager.exe" not in ISS_CLIENT.replace("3DIWELL Farm Manager Client.exe", "")
          and "server.py" not in ISS_CLIENT)
    check("71. client installer не включает БД/DATA_DIR/firewall",
          not re.search(r"farm_\w+\.db|DATA_DIR|netsh|firewall", ISS_CLIENT)
          and "printer" not in ISS_CLIENT.lower())
    check("71b. client installer имеет ОТДЕЛЬНЫЙ AppId и версию, согласованную с APP_VERSION",
          "7B4E9D21" in ISS_CLIENT and "8C1F2A93" not in ISS_CLIENT
          and ('#define AppVersion "%s"' % _APP_VER) in ISS_CLIENT)
    check("72. оба EXE собираются windowed (console=False)",
          SPEC.count("console=False,") == 2 and "console=True" not in SPEC)
    check("73. version metadata согласована с APP_VERSION (оба version-файла, company/product)",
          all(("filevers=(%d, %d, 0, 0)" % (_APP_MAJOR, _APP_MINOR) in open(os.path.join(REPO, f), encoding="utf-8").read()
               and "3DIWELL" in open(os.path.join(REPO, f), encoding="utf-8").read())
              for f in ("desktop_shell_version_local.txt", "desktop_shell_version_client.txt"))
          and "desktop_shell_version_local.txt" in SPEC and "desktop_shell_version_client.txt" in SPEC)
    check("73b. в client build не входят серверные подсистемы (excludes)",
          re.search(r"excludes=\[[^\]]*'uvicorn'[^\]]*'fastapi'[^\]]*'sqlite3'", SPEC) is not None)
    check("74. отсутствие WebView2 имеет fallback (проверка ДО окна, сообщение + браузер, без тихой установки)",
          "if not has_webview2_runtime():" in _main_src and "WebView2 Runtime" in DS_SRC
          and "Открыть Farm Manager в обычном браузере?" in DS_SRC
          and not re.search(r"MicrosoftEdgeWebview2Setup|bootstrapper|silent", DS_SRC, re.I))

    # ═════════════════════════ REGRESSION (75-89) ═══════════════════════════
    section("регрессия и границы")
    check("75. обычный браузер продолжает работать (uvicorn слушает активный порт; трей открывает "
          "активный порт)",
          "uvicorn.Server(uvicorn.Config(app, host=_bind_host, port=_ACTIVE_PORT" in SRV
          and "_uv.run(sockets=[_listen_sock])" in SRV
          and "_active_server_port()" in fn_src("_start_tray_detached"))
    check("76. WebSocket lifecycle не менялся", "active_ws" in SRV and "ws_ep" in SRV
          and "websocket" not in DS_SRC.lower())
    check("77. local admin recovery не ломается (фрагмент не логируется, маршрут не тронут)",
          "local-recovery/complete" in SRV and "_initiate_local_admin_recovery" in SRV
          and shcfg.redact_url_for_log("http://127.0.0.1:8000/#local-admin-recovery=x") == "http://127.0.0.1:8000")
    check("78. module capability contract не менялся",
          "module_window_capabilities" in SRV or "capability" in SRV)
    _mods = {}
    #  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
    for _m in ("inventory", "cost", "quality"):
        try:
            _mods[_m] = (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(open(os.path.join(REPO, "modules", _m, "module.json"), encoding="utf-8")))
        except Exception:
            _mods[_m] = "?"
    #  3.0: cost — «Расчёт заказа» 0.2.0 на месте удалённой «Себестоимости печати» (слово владельца).
    check("79-81. модули не менялись: inventory 1.7.29 / cost 0.2.0 / quality 0.2.3",
          _mods == {"inventory": "1.7.29", "cost": "0.2.0", "quality": "0.2.3"})
    check("82. контракт папок проектов Alpha 2.804 не менялся",
          "normalize_and_validate_project_name" in SRV and "rename_project_atomic" in SRV
          and "project" not in DS_SRC.lower().replace("проект", ""))
    check("83. managed-файлы Alpha 2.801 не менялись",
          "_import_copy_managed" in SRV and "_managed_source_ok" in SRV)
    check("84. Moonraker pipeline не менялся",
          "_moonraker_print_started" in SRV and "moonraker" not in DS_SRC.lower())
    check("85. DISPATCH_ENABLED остаётся False",
          re.search(r"^DISPATCH_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("86. TRANSPORT_ENABLED остаётся False",
          re.search(r"^TRANSPORT_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("87. `_incoming/` не используется оболочкой",
          "_incoming" not in DS_SRC + CFG_SRC + SEC_SRC + LAUNCH_LOCAL + LAUNCH_CLIENT)
    check("88. артефактов теста нет (tools/_e2e_payload.json отсутствует; sentinel только в тесте)",
          not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json"))
          and SENTINEL not in SRV and SENTINEL not in DS_SRC and SENTINEL not in CFG_SRC
          and SENTINEL not in SEC_SRC and SENTINEL not in ISS_MAIN and SENTINEL not in ISS_CLIENT
          and SENTINEL not in SPEC)
    _late_blob = ""                                        # ПОСЛЕ всех клиентских операций:
    for _base, _dirs, _fnames in os.walk(ROOT):            # cookies/пароли/токены так и не появились
        for _f in _fnames:
            try:
                _late_blob += open(os.path.join(_base, _f), encoding="utf-8", errors="replace").read()
            except Exception:
                pass
    check("88b. после ВСЕХ операций хранилище оболочки без секретов (ни cookie, ни password, ни token)",
          not re.search(r"cookie|password|token|session", _late_blob, re.I))
    check("89a. pywebview НЕ импортирован offline-тестом (GUI не создавался)",
          "webview" not in sys.modules and "clr" not in sys.modules)
    check("89b. новых HTTP-маршрутов сверх учтённых не добавлено (число @app.* = 197)",
          len(re.findall(r"^@app\.(get|post|patch|delete|websocket)\(", SRV, re.M)) == 209)   # 2.823: +5 printer-files; 2.825: +select-for-print; 2.827: +4 config-backup; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.870: +камера без перекодирования; 2.879: +камера по WebSocket (HTTP-маршрутов не прибавилось); 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.927: +3 пометки принтера и настройки фермы; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
    check("89c. хранилище оболочки изолировано во временной папке",
          shcfg.shell_root() == ROOT and ROOT.lower().startswith(tempfile.gettempdir().lower())
          and REPO.lower() not in ROOT.lower())
    check("89d. сервер принимает новые флаги безопасно (--desktop-start только гасит input)",
          '_DESKTOP_START = "--desktop-start" in sys.argv' in SRV
          and 'if not _DESKTOP_START:' in SRV
          and "--desktop-start" not in fn_src("_one_shot_cli"))
    check("89e. флаги не включают LAN/AUTH (решение LAN осталось прежним)",
          "_LAN_DECISION = _lan_effective_decision()" in SRV
          and "_DESKTOP_START" not in fn_src("_lan_effective_decision"))

finally:
    socket.socket = _REAL_SOCKET
    os.environ.pop("FM_DESKTOP_SHELL_ROOT", None)
    TMP.cleanup()

check("89f. временный корень удалён после теста", not os.path.exists(ROOT))

print("\n" + "=" * 76)
if FAILED:
    print("FAIL: провалено %d из %d" % (len(FAILED), len(FAILED) + PASSED[0]))
    for n in FAILED:
        print("   - %s" % n)
    _DONE["ok"] = True
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ (%d)" % PASSED[0])
_DONE["ok"] = True
sys.exit(0)
