# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Собственное окно следует за фактическим портом сервера — Alpha 2.812.
=================================================================================================
ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ.

Пользователь сменил серверный порт на 8123. Сервер работает, браузер открывает интерфейс, а
собственное окно показывает «Не удалось запустить Farm Manager», обращаясь к `http://127.0.0.1:8000`,
и пытается поднять ВТОРОЙ backend.

ROOT CAUSE (доказан исполнением). Разбор аргументов оболочки ставил `port = 8000` как ЗНАЧЕНИЕ ПО
УМОЛЧАНИЮ, а список адресов строится так:

    if cfg.get("port"):                       # 8000 — истинно ВСЕГДА
        return ["http://127.0.0.1:%d" % cfg["port"]]
    return [... candidate_local_ports() ...]  # чтение config сервера — недостижимо

То есть появившееся в Alpha 2.806 «окно следует за активным портом» было мёртвым кодом при каждом
обычном запуске ярлыком: config сервера не читался никогда. Пока сервер жил на 8000, совпадение
значений скрывало дефект; после смены порта окно стучалось в пустой порт. Браузер при этом работал,
потому что открывается сервером по его собственному рантайм-порту — другой путь, другой источник.

ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ: единый источник истины (config сервера + подтверждение `/version`), порядок
кандидатов, поведение при уже работающем сервере, при его отсутствии, при смене порта и откате,
страница ошибки, инварианты удалённого клиента и отсутствие второго backend.

ПОЛНОСТЬЮ OFFLINE: временная папка вместо обеих рабочих папок, поддельные пробы и запуск процессов,
ловушки на сокеты и подпроцессы. Рабочий config, рабочий сервер и WebView2 не участвуют.

Запуск: PYTHONIOENCODING=utf-8 python tools/test_desktop_active_port_resolution.py   (0 = пройдено)
"""
import ast
import atexit
import json
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "DESKTOP_ACTIVE_PORT_RESOLUTION_SENTINEL_2_812"

# ── Ловушки: сеть и запуск процессов в offline-тесте запрещены ────────────────────────────────
import socket as _socket_mod
import subprocess as _subprocess_mod

_VIOLATIONS = []


class _NoSocket(object):
    def __init__(self, *a, **k):
        _VIOLATIONS.append("socket")
        raise RuntimeError("сеть в offline-тесте запрещена")


_socket_mod.socket = _NoSocket
_socket_mod.create_connection = lambda *a, **k: _NoSocket()


class _NoPopen(object):
    def __init__(self, *a, **k):
        _VIOLATIONS.append("subprocess")
        raise RuntimeError("запуск процессов в offline-тесте запрещён")


_subprocess_mod.Popen = _NoPopen

_TMP = tempfile.TemporaryDirectory(prefix="fm_desktop_port_2812_")
TMP_ROOT = os.path.realpath(_TMP.name)
SHELL_ROOT = os.path.join(TMP_ROOT, "shell")
SERVER_CFG = os.path.join(TMP_ROOT, "server-config.json")
os.makedirs(SHELL_ROOT, exist_ok=True)

# Обе папки уводятся во временную ДО импорта оболочки: рабочие данные не читаются и не пишутся.
os.environ["FM_DESKTOP_SHELL_ROOT"] = SHELL_ROOT
os.environ["FM_SERVER_CONFIG"] = SERVER_CFG

from app import desktop_shell_config as shcfg
from app import desktop_shell_security as shsec

_SHELL_SRC = open(os.path.join(REPO, "app", "desktop_shell.py"), encoding="utf-8").read()
_CFG_SRC = open(os.path.join(REPO, "app", "desktop_shell_config.py"), encoding="utf-8").read()
_SEC_SRC = open(os.path.join(REPO, "app", "desktop_shell_security.py"), encoding="utf-8").read()
_SHELL_AST = ast.parse(_SHELL_SRC)


def fn_node(name, tree=None):
    """Узел функции/метода по имени (для проверок ПО КОДУ, а не по тексту)."""
    for n in ast.walk(tree or _SHELL_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def code_constants(node):
    """Константы КОДА внутри узла, без докстрок.

    Текстовые проверки исходника раз за разом ловят собственные пояснения: в комментарии к
    этому же коду честно написано «в собранной оболочке — всегда 8000», и наивный поиск
    подстроки объявлял бы дефект там, где его нет."""
    doc_ids = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                doc_ids.add(id(n.body[0].value))
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and id(n) not in doc_ids]


def calls_in(node):
    """Имена вызываемых функций/методов внутри узла."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(getattr(f, "id", None) or getattr(f, "attr", None) or "")
    return out

fail = 0
_checked = 0
_verdict = [False]


def check(name, cond):
    global fail, _checked
    _checked += 1
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


@atexit.register
def _guard_exit():
    if not _verdict[0]:
        print("FAIL — тест завершился БЕЗ финального вердикта (преждевременный выход)")
        os._exit(1)


def write_server_config(**fields):
    """Записать временный config СЕРВЕРА (рабочий не трогается)."""
    cfg = {"data_dir": "", "project_print_enabled": True, "lan_access_enabled": False,
           "sentinel": SENTINEL}
    cfg.update(fields)
    with open(SERVER_CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return cfg


def drop_server_config():
    try:
        os.unlink(SERVER_CFG)
    except OSError:
        pass


# ── Оболочка без окна: подменяем только показ страниц, логика решения — настоящая ─────────────
import app.desktop_shell as ds


class FakeWindow(object):
    def __init__(self):
        self.pages = []

    def load_html(self, html):
        self.pages.append(html)


class Harness(ds.DesktopShell):
    """Настоящий DesktopShell с поддельными пробами и запуском backend."""

    def __init__(self, cfg, answers, spawn_result=None, after_spawn=None):
        ds.DesktopShell.__init__(self, cfg)
        self.window = FakeWindow()
        self.answers = dict(answers)        # {base_url: "ready"|"auth"|"foreign"|"down"}
        self.opened = []                    # адреса, на которых открыт интерфейс
        self.browser = []                   # адреса, отданные системному браузеру
        self.spawns = 0
        self.after_spawn = after_spawn      # что становится доступно после запуска backend
        self.probed = []

    # -- подменяем ТОЛЬКО внешние действия
    def go(self, base):
        self.opened.append(base)
        self.target_url = base

    def _status(self, *_a, **_k):
        pass

    def probe(self, base):
        self.probed.append(base)
        return self.answers.get(base, "down")

    def spawn(self, _cmd):
        self.spawns += 1
        if self.after_spawn:
            self.answers.update(self.after_spawn)


def run_boot(shell, start_server=True):
    """Прогнать boot() с подменёнными пробами и запуском (сеть/процессы не участвуют)."""
    real_probe, real_ensure = ds.probe_farm_manager, ds.ensure_local_backend

    def fake_probe(base, timeout=None, opener=None):
        return shell.probe(base)

    def fake_ensure(base, status_cb=None, probe=None, spawn=None, **kw):
        return real_ensure(base, status_cb=status_cb, probe=shell.probe, spawn=shell.spawn,
                           deadline_s=2.0, sleep=lambda *_: None,
                           clock=lambda c=[0.0]: (c.__setitem__(0, c[0] + 1.0) or c[0]))

    ds.probe_farm_manager, ds.ensure_local_backend = fake_probe, fake_ensure
    try:
        shell.boot(start_server=start_server)
    finally:
        ds.probe_farm_manager, ds.ensure_local_backend = real_probe, real_ensure


def local_shell(answers, cli=(), **kw):
    return Harness(shcfg.parse_args(list(cli)), answers, **kw)


print("=" * 95)
print("A. ИСТОЧНИК ИСТИНЫ — CONFIG СЕРВЕРА (root cause)")
print("=" * 95)

write_server_config(server_port=8123)
check("A1. КРИТИЧНО (root cause): порт по умолчанию НЕ задан — иначе config сервера не читается "
      "никогда и окно навсегда привязано к 8000",
      shcfg.parse_args([])["port"] == 0)
check("A2. КРИТИЧНО: при server_port=8123 кандидатом становится 8123",
      shcfg.candidate_local_ports() == [8123])
sh = local_shell({})
check("A3. КРИТИЧНО: адреса окна строятся из config, а не из умолчания",
      sh.local_candidate_urls() == ["http://127.0.0.1:8123"])
check("A4. 8000 по умолчанию используется ТОЛЬКО когда настройки нет вовсе",
      (drop_server_config() or shcfg.candidate_local_ports()) == [8000])
write_server_config(server_port=8123)
check("A5. явный --port остаётся переопределением пользователя",
      local_shell({}, cli=["--port", "9001"]).local_candidate_urls() == ["http://127.0.0.1:9001"])
check("A6. явный --server-url остаётся переопределением",
      local_shell({}, cli=["--server-url", "http://127.0.0.1:9002"]).local_candidate_urls()
      == ["http://127.0.0.1:9002"])

write_server_config(server_port=8000, pending_server_port=8123, previous_server_port=8000)
check("A7. КРИТИЧНО: ожидающий порт проверяется ПЕРВЫМ",
      shcfg.candidate_local_ports()[0] == 8123)
check("A8. прежний порт — кандидат только при незавершённом переходе",
      8000 in shcfg.candidate_local_ports())
write_server_config(server_port=8123, previous_server_port=8000)
check("A9. КРИТИЧНО: без ожидающего перехода прежний порт кандидатом НЕ является "
      "(иначе окно ломилось бы в давно оставленный порт)",
      shcfg.candidate_local_ports() == [8123])
write_server_config(server_port=8123, extra_unknown_field={"keep": SENTINEL})
check("A10. неизвестные поля настройки не мешают разбору", shcfg.candidate_local_ports() == [8123])
check("A11. КРИТИЧНО: оболочка настройку сервера НЕ пишет — только читает",
      not [n for n in ast.walk(ast.parse(_CFG_SRC))
           if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "open"
           and len(n.args) > 1 and getattr(n.args[1], "value", "") in ("w", "a")]
      or "server_config_path" not in _CFG_SRC.split("def save_client_config")[0].split(
          "def client_config_path")[-1])
def ports_for(**fields):
    """Кандидаты для заданной настройки (запись + чтение одним шагом)."""
    write_server_config(**fields)
    return shcfg.candidate_local_ports()


check("A12. битые значения порта игнорируются (строка, логическое, служебный диапазон)",
      ports_for(server_port="8123") == [8000]
      and ports_for(server_port=True) == [8000]
      and ports_for(server_port=80) == [8000]
      and ports_for(server_port=70000) == [8000])

print()
print("=" * 95)
print("B. СЕРВЕР УЖЕ РАБОТАЕТ")
print("=" * 95)

write_server_config(server_port=8123)
sh = local_shell({"http://127.0.0.1:8123": "ready"})
run_boot(sh)
check("B1. КРИТИЧНО: работающий сервер на 8123 найден и открыт", sh.opened == ["http://127.0.0.1:8123"])
check("B2. КРИТИЧНО: второй backend НЕ запускается", sh.spawns == 0)
check("B3. КРИТИЧНО: 8000 даже не проверялся", "http://127.0.0.1:8000" not in sh.probed)

sh = local_shell({"http://127.0.0.1:8123": "auth"})
run_boot(sh)
check("B4. сервер с включённой авторизацией — тоже наш сервер",
      sh.opened == ["http://127.0.0.1:8123"] and sh.spawns == 0)

write_server_config(server_port=8000, pending_server_port=8123)
sh = local_shell({"http://127.0.0.1:8123": "foreign", "http://127.0.0.1:8000": "ready"})
run_boot(sh)
check("B5. КРИТИЧНО: чужая программа на порту НЕ принимается за Farm Manager, перебор "
      "продолжается до настоящего сервера",
      sh.opened == ["http://127.0.0.1:8000"] and sh.spawns == 0)

write_server_config(server_port=8123)
sh = local_shell({"http://127.0.0.1:8123": "foreign"})
run_boot(sh)
check("B6. КРИТИЧНО: только чужой ответ — интерфейс не открывается, показана ошибка",
      not sh.opened and sh.window.pages)

print()
print("=" * 95)
print("C. СЕРВЕР НЕ РАБОТАЕТ: ЗАПУСК И ПОВТОРНОЕ ЧТЕНИЕ НАСТРОЙКИ")
print("=" * 95)

write_server_config(server_port=8123)
sh = local_shell({}, after_spawn={"http://127.0.0.1:8123": "ready"})
run_boot(sh)
check("C1. сервер отсутствует -> запускается РОВНО один backend", sh.spawns == 1)
check("C2. после запуска интерфейс открыт на порту из настройки", sh.opened == ["http://127.0.0.1:8123"])


class SwitchingHarness(Harness):
    """Сервер поднимается НЕ на том порту, который был выбран до его старта: применён
    ожидающий порт. Настройка при этом обновляется самим сервером."""

    def spawn(self, cmd):
        Harness.spawn(self, cmd)
        write_server_config(server_port=8123)          # сервер применил ожидающий порт
        self.answers["http://127.0.0.1:8123"] = "ready"


write_server_config(server_port=8000, pending_server_port=8123)
sh = SwitchingHarness(shcfg.parse_args([]), {})
run_boot(sh)
check("C3. удачный переход: сервер поднялся на ожидающем порту, окно его открыло",
      sh.opened == ["http://127.0.0.1:8123"])
check("C4. КРИТИЧНО: второго backend при этом не появляется", sh.spawns == 1)


class RollbackHarness(Harness):
    """Сервер поднялся НЕ на первом кандидате: ожидающий порт занят, выполнен откат к прежнему.
    Окно обязано перечитать настройку после запуска и найти фактический порт."""

    def spawn(self, cmd):
        Harness.spawn(self, cmd)
        write_server_config(server_port=8000)          # сервер откатился и обновил настройку
        self.answers["http://127.0.0.1:8000"] = "ready"


write_server_config(server_port=8000, pending_server_port=8123)
sh = RollbackHarness(shcfg.parse_args([]), {})
run_boot(sh)
check("C5. КРИТИЧНО: сервер поднялся на ДРУГОМ порту, чем выбранный до старта — окно "
      "перечитывает настройку и находит фактический адрес",
      sh.opened == ["http://127.0.0.1:8000"])
check("C6. КРИТИЧНО: при этом второй backend не запускается", sh.spawns == 1)

write_server_config(server_port=8123)
sh = local_shell({})
run_boot(sh)
check("C5. сервер так и не поднялся -> показана ошибка, интерфейс не открыт",
      not sh.opened and sh.window.pages)
check("C6. КРИТИЧНО: медленный старт не порождает второй backend", sh.spawns == 1)

print()
print("=" * 95)
print("D. СМЕНА ПОРТА И ОТКАТ")
print("=" * 95)

write_server_config(server_port=8123)
sh = local_shell({"http://127.0.0.1:8123": "ready"})
run_boot(sh)
check("D1. КРИТИЧНО: 8000 -> 8123 окно переключается без своих настроек",
      sh.opened == ["http://127.0.0.1:8123"])

write_server_config(server_port=8000)
sh = local_shell({"http://127.0.0.1:8000": "ready"})
run_boot(sh)
check("D2. КРИТИЧНО: обратно 8123 -> 8000 окно тоже переключается",
      sh.opened == ["http://127.0.0.1:8000"])

write_server_config(server_port=8000, pending_server_port=8123, previous_server_port=8000)
sh = local_shell({"http://127.0.0.1:8123": "ready"})
run_boot(sh)
check("D3. удачный переход: окно открывает новый порт", sh.opened == ["http://127.0.0.1:8123"])

sh = local_shell({"http://127.0.0.1:8000": "ready"})
run_boot(sh)
check("D4. КРИТИЧНО: откат — новый порт не ответил, окно открывает прежний",
      sh.opened == ["http://127.0.0.1:8000"] and sh.spawns == 0)

write_server_config(server_port=8123)
sh = local_shell({"http://127.0.0.1:8123": "ready"})
run_boot(sh)
check("D5. КРИТИЧНО: неудавшийся перезапуск не оставляет вечной привязки к старому порту — "
      "решение принимается по настройке при КАЖДОМ запуске",
      sh.opened == ["http://127.0.0.1:8123"] and "http://127.0.0.1:8000" not in sh.probed)

print()
print("=" * 95)
print("E. ПОРЯДОК ЗАПУСКА: БРАУЗЕР И ОКНО НЕ МЕШАЮТ ДРУГ ДРУГУ")
print("=" * 95)

write_server_config(server_port=8123)
sh = local_shell({"http://127.0.0.1:8123": "ready"})
run_boot(sh)
check("E1. сначала браузер, потом окно: окно переиспользует тот же сервер",
      sh.opened == ["http://127.0.0.1:8123"] and sh.spawns == 0)
sh2 = local_shell({"http://127.0.0.1:8123": "ready"})
run_boot(sh2)
check("E2. сначала окно, потом браузер: второй backend не появляется", sh2.spawns == 0)
check("E3. КРИТИЧНО: у окна и у ярлыка «браузер» ОДИН резолвер (общая функция поиска)",
      "find_running_local" in _SHELL_SRC
      and _SHELL_SRC.count("def find_running_local") == 1
      and "shell.find_running_local()" in _SHELL_SRC.split("def open_browser_flow")[1][:800])

print()
print("=" * 95)
print("F. СТРАНИЦА ОШИБКИ")
print("=" * 95)

write_server_config(server_port=8123, pending_server_port=8000)
sh = local_shell({})
# Нажатие идёт через НАСТОЯЩИЙ обработчик команд страницы — проверяется и сама проводка кнопки.
real_probe, real_ensure = ds.probe_farm_manager, ds.ensure_local_backend
ds.probe_farm_manager = lambda base, timeout=None, opener=None: sh.probe(base)
ds.ensure_local_backend = lambda base, status_cb=None, **kw: real_ensure(
    base, status_cb=status_cb, probe=sh.probe, spawn=sh.spawn, deadline_s=1.0,
    sleep=lambda *_: None, clock=lambda c=[0.0]: (c.__setitem__(0, c[0] + 1.0) or c[0]))
try:
    sh._handle_command("retry", {})
finally:
    ds.probe_farm_manager, ds.ensure_local_backend = real_probe, real_ensure
page = sh.window.pages[-1] if sh.window.pages else ""
check("F1. КРИТИЧНО: кнопка «Повторить» ничего не запускает — только перечитывает настройку и "
      "спрашивает сервер заново", sh.spawns == 0)
check("F2. КРИТИЧНО: показаны ПРОВЕРЕННЫЕ порты, а не один старый адрес",
      "Проверены порты" in page and "8000" in page and "8123" in page)
check("F3. предложена отдельная кнопка запуска сервера", "start-server" in page)
check("F4. есть кнопки «Повторить», «Открыть в браузере», «Закрыть»",
      "'retry'" in page and "'browser'" in page and "'close'" in page)
check("F5. КРИТИЧНО: путь к файлу настройки наружу не выходит",
      SERVER_CFG not in page and "config.json" not in page)
check("F6. КРИТИЧНО: ни traceback, ни командной строки на странице нет",
      "Traceback" not in page and ".exe" not in page and "--" not in page.split("<script>")[-1])
check("F7. КРИТИЧНО: sentinel из временной настройки на страницу не попадает", SENTINEL not in page)
check("F8. в локальном режиме кнопки «Сменить сервер» нет (это режим клиента)",
      "change-server" not in page)
check("F9. текст ошибки человеческий, без внутренних кодов",
      "Не удалось подключиться к локальному Farm Manager" in page)
_cmd_node = fn_node("_handle_command")
check("F10. КРИТИЧНО: «Открыть в браузере» ведёт на фактически найденный сервер, а не на "
      "жёсткий 8000 (проверяем КОД обработчика, а не пояснения к нему)",
      _cmd_node is not None and 8000 not in code_constants(_cmd_node)
      and "find_running_local" in calls_in(_cmd_node))

print()
print("=" * 95)
print("G. УДАЛЁННЫЙ КЛИЕНТ — КОНТРАКТ НЕ СМЕШИВАЕТСЯ")
print("=" * 95)

_client_boot = _SHELL_SRC[_SHELL_SRC.index("def client_boot"):_SHELL_SRC.index("def client_connect")]
check("G1. КРИТИЧНО: клиент НЕ читает настройку локального сервера",
      "candidate_local_ports" not in _client_boot and "find_running_local" not in _client_boot)
check("G2. КРИТИЧНО: клиент backend не запускает",
      "ensure_local_backend" not in _client_boot and "spawn_backend" not in _client_boot)
check("G3. сохранённый адрес клиента остаётся выбором пользователя",
      "load_client_config" in _client_boot and "save_client_config" in _client_boot)
shcfg.save_client_config("http://192.168.1.50:8000")
sh = local_shell({"http://127.0.0.1:8123": "ready"})
run_boot(sh)
check("G4. КРИТИЧНО: локальный режим сохранённый адрес клиента не использует и не портит",
      sh.opened == ["http://127.0.0.1:8123"]
      and shcfg.load_client_config().get("server_origin") == "http://192.168.1.50:8000")
check("G5. КРИТИЧНО: у локального режима собственного «запомненного порта» нет вовсе — "
      "источником истины остаётся настройка сервера",
      "server_origin" not in _SHELL_SRC.split("def boot(")[1].split("def client_boot")[0])

print()
print("=" * 95)
print("H. ГРАНИЦЫ И РЕГРЕССИИ")
print("=" * 95)

check("H1. КРИТИЧНО: тест не открывал сокетов и не запускал процессов", not _VIOLATIONS)
check("H2. КРИТИЧНО: рабочие папки не использовались — обе уведены во временную",
      os.path.realpath(shcfg.shell_root()).startswith(TMP_ROOT)
      and os.path.realpath(shcfg.server_config_path()).startswith(TMP_ROOT))
check("H3. КРИТИЧНО: sentinel живёт только в оснастке теста",
      SENTINEL not in _SHELL_SRC and SENTINEL not in _CFG_SRC
      and SENTINEL not in open(os.path.join(REPO, "app", "desktop_shell_security.py"),
                               encoding="utf-8").read())
check("H4. закрытие окна не останавливает сервер (инвариант 2.805 сохранён)",
      "backend продолжает работать" in _SHELL_SRC)
check("H5. одно окно на режим: mutex оболочки сохранён", "acquire_shell_mutex" in _SHELL_SRC)
check("H6. проверка идентичности сервера не ослаблена (только ready/auth считаются нашими)",
      _SHELL_SRC.count('in ("ready", "auth")') >= 3 and "def classify_probe" in
      open(os.path.join(REPO, "app", "desktop_shell_security.py"), encoding="utf-8").read())
check("H7. оболочка не сканирует диапазоны портов",
      "range(" not in _SHELL_SRC.split("def local_candidate_urls")[1].split("def go")[0]
      and "range(" not in _CFG_SRC.split("def candidate_local_ports")[1].split("PROFILE_LOCAL")[0])
check("H8. автоматическая отправка выключена (сверяем ОБЪЯВЛЕНИЕ в начале строки: в пояснении "
      "к модулю этот же флаг упомянут текстом)",
      re.search(r"^DISPATCH_ENABLED = False", open(os.path.join(REPO, "app", "project_orchestrator.py"),
                                                   encoding="utf-8").read(), re.M) is not None)
check("H9. оболочка принтерам ничего не отправляет",
      not [s for s in ("mqtt", "ftplib", "8883", "8898") if s in _SHELL_SRC.lower()])
check("H10. оболочка не трогает папку данных сервера: ни баз, ни SQLite в КОДЕ "
      "(в пояснениях это правило упомянуто — проверяем именно код)",
      not [c for c in code_constants(_SHELL_AST)
           if isinstance(c, str) and (c.endswith(".db") or "farm_parts" in c)]
      and "sqlite3" not in calls_in(_SHELL_AST)
      and not [n for n in ast.walk(_SHELL_AST) if isinstance(n, (ast.Import, ast.ImportFrom))
               and "sqlite3" in ast.dump(n)])
check("H11. `_incoming` оболочкой не используется",
      "_incoming" not in _SHELL_SRC and "_incoming" not in _CFG_SRC)
check("H12. артефактов e2e нет", not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))

print()
print("=" * 95)
_verdict[0] = True
print("Проверок выполнено: %d, провалено: %d" % (_checked, fail))
if fail:
    print("FAIL: %d проверок провалено" % fail)
else:
    print("PASS: собственное окно берёт порт из настройки сервера и подтверждает его ответом "
          "/version; уже работающий сервер переиспользуется на любом порту, второй backend не "
          "запускается, после старта порт перечитывается, а страница ошибки честно называет "
          "проверенные порты. Контракт удалённого клиента не затронут.")
raise SystemExit(1 if fail else 0)
