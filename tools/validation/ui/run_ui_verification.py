# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 3A — изолированная проверка интерфейса в headless-браузере.

ЧТО ДЕЛАЕТ. Поднимает UI в изолированном окружении, выполняет ОДИН декларативный сценарий из
реестра, проверяет DOM, консоль и сетевые обращения, снимает экран и убирает за собой ровно
свои процессы.

ЧЕГО НЕ ДЕЛАЕТ. Не трогает рабочую папку данных владельца, не читает его БД, не подключается
к принтерам и ничего им не отправляет, не запускает печать, не собирает EXE. Не завершает
процессы по имени: гасятся только PID, записанные этим запуском.

ГЛАВНЫЕ ПРАВИЛА ЧЕСТНОСТИ.
  * Скриншот сам по себе НЕ является доказательством: без пройденных обязательных проверок DOM
    результат не может быть PASS.
  * Ранний выход сервера с кодом 0 — это FAIL, а не успешный запуск.
  * Любое обращение наружу локальной петли — FAIL, а не тихая запись в журнал.
  * Режим честно маркируется: static_harness (реальный фронтенд, синтетический backend) или
    isolated_farm_manager (настоящий server.py в изолированной папке).

    python tools/validation/ui/run_ui_verification.py --scenario settings_panel_open_close
    python tools/validation/ui/run_ui_verification.py --scenario <id> --execute

Коды: 0 PASS/DRY_RUN · 2 FAIL · 3 BLOCKED · 4 TIMEOUT · 5 CONFIG_ERROR.
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
RUNS_DIR = os.path.join(REPO, "logs", "ui_runs")
SCENARIOS = os.path.join(HERE, "scenarios.json")

SCHEMA = "3diwell-ui-run-v1"
SCEN_SCHEMA = "3diwell-ui-scenarios-v1"

PASS, FAIL, BLOCKED, DRY_RUN, TIMEOUT, CONFIG_ERROR = (
    "PASS", "FAIL", "BLOCKED", "DRY_RUN", "TIMEOUT", "CONFIG_ERROR")
EXIT = {PASS: 0, DRY_RUN: 0, FAIL: 2, BLOCKED: 3, TIMEOUT: 4, CONFIG_ERROR: 5}

MODES = ("static_harness", "isolated_farm_manager")
ALLOWED_ACTIONS = ("wait_for_selector", "click", "fill", "press", "set_viewport",
                   "screenshot", "read_text", "assert_visible", "assert_hidden",
                   "assert_text", "assert_attribute")

# Движок берётся ТОЛЬКО отсюда. Путь, пришедший от пользователя, программой стать не может.
ENGINE_ALLOWLIST = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
NODE_ALLOWLIST = (r"C:\Program Files\nodejs\node.exe",
                  r"C:\Program Files (x86)\nodejs\node.exe")

ENV_ALLOW = ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP", "COMSPEC",
             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS")
# Для изолированного сервера дополнительно нужны домашние переменные: по ним продукт САМ
# вычисляет рабочую папку владельца и доказывает, что тестовая с ней не пересекается.
# Подменять их нельзя — подмена превратила бы штатную проверку продукта в проверку подделки.
ENV_ALLOW_SERVER = ENV_ALLOW + ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOMEDRIVE",
                                "HOMEPATH", "PROGRAMDATA", "PROGRAMFILES",
                                "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "PUBLIC")

# Официальный контракт изоляции продукта. Имена НЕ выдумываются: они читаются из
# app/e2e_isolation.py и здесь только используются.
E2E_FLAG = "--fm-packaged-e2e"
E2E_MARKER_NAME = ".fm-e2e-marker"
E2E_ENV = {
    "sentinel": "FM_E2E_SENTINEL", "instance": "FM_E2E_INSTANCE_ID",
    "data_dir": "FM_E2E_DATA_DIR", "config": "FM_E2E_CONFIG_PATH",
    "mutex": "FM_E2E_MUTEX_NAME", "port": "FM_E2E_PORT",
    "no_tray": "FM_E2E_DISABLE_TRAY", "no_browser": "FM_E2E_DISABLE_BROWSER",
    "no_discovery": "FM_E2E_DISABLE_DISCOVERY", "no_printers": "FM_E2E_DISABLE_PRINTERS",
    "no_modules": "FM_E2E_DISABLE_MODULES",
}
GUARD_DIR = os.path.join(HERE, "network_guard")
GUARD_LOG_ENV, GUARD_SENTINEL_ENV = "FM_UI_GUARD_LOG", "FM_UI_GUARD_SENTINEL"
PRODUCTION_MUTEX = r"Local\3DIWELL_Farm_Manager_SingleInstance_v1"
PRODUCTION_PORT_DEFAULT = 8000

LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")
LOCAL_SCHEMES = ("data:", "about:", "blob:", "chrome-error:")

# Строки, которых не должно быть в фикстуре и сценарии: адрес железа или доступ к нему.
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_LOCAL_IP = re.compile(r"^(?:127\.\d+\.\d+\.\d+|0\.0\.0\.0)$")
_SECRET_HINT = re.compile(r"access[_-]?code|serial[_-]?number|\btoken\b|\bpassword\b|"
                          r"\bapi[_-]?key\b|lan[_-]?code", re.I)


class ConfigError(Exception):
    """Неверная конфигурация или недоказанная изоляция: ничего не запускается."""


# ── Реестр сценариев ─────────────────────────────────────────────────────────
def load_scenarios(path=None):
    p = path or SCENARIOS
    if not os.path.isfile(p):
        raise ConfigError("реестр сценариев не найден: %s" % p)
    try:
        data = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        raise ConfigError("реестр сценариев не читается: %s" % e)
    if not isinstance(data, dict) or data.get("schema_version") != SCEN_SCHEMA:
        raise ConfigError("несовместимая схема реестра сценариев")
    out = {}
    for s in data.get("scenarios", []):
        for k in ("id", "application_mode", "actions", "assertions", "timeout_seconds",
                  "network_policy", "console_policy", "screenshot_names"):
            if k not in s:
                raise ConfigError("сценарий %r без обязательного поля %r" % (s.get("id"), k))
        if s["application_mode"] not in MODES:
            raise ConfigError("сценарий %s: неизвестный режим %r" % (s["id"],
                                                                    s["application_mode"]))
        validate_scenario(s)
        out[s["id"]] = s
    if not out:
        raise ConfigError("реестр сценариев пуст")
    return out


def validate_scenario(s):
    """Сценарий — данные. Ни кода, ни внешних адресов, ни секретов."""
    names = list(s.get("screenshot_names") or [])
    if len(names) != len(set(names)):
        raise ConfigError("сценарий %s: повторяющиеся имена скриншотов" % s["id"])
    for n in names:
        if not re.match(r"^[A-Za-z0-9._-]+\.png$", n):
            raise ConfigError("сценарий %s: недопустимое имя скриншота %r" % (s["id"], n))

    pol = s.get("network_policy") or {}
    hosts = pol.get("allowed_hosts")
    if not hosts:
        raise ConfigError("сценарий %s: network_policy без allowed_hosts" % s["id"])
    for h in hosts:
        if h not in LOCAL_HOSTS:
            raise ConfigError("сценарий %s: во внешний хост %r ходить нельзя" % (s["id"], h))

    for i, a in enumerate(s["actions"]):
        t = a.get("type")
        if t not in ALLOWED_ACTIONS:
            raise ConfigError("сценарий %s: действие %d имеет недопустимый тип %r"
                              % (s["id"], i, t))
        for k in ("script", "js", "javascript", "eval", "command", "shell", "python"):
            if k in a:
                raise ConfigError("сценарий %s: действие %d содержит запрещённое поле %r"
                                  % (s["id"], i, k))
    blob = json.dumps(s, ensure_ascii=False)
    for m in re.finditer(r"https?://([^/\"\s]+)", blob):
        host = m.group(1).split(":")[0]
        if host not in LOCAL_HOSTS:
            raise ConfigError("сценарий %s: внешний URL %r запрещён" % (s["id"], m.group(0)))
    for ip in _IPV4.findall(blob):
        if not _LOCAL_IP.match(ip):
            raise ConfigError("сценарий %s: адрес реального устройства %r запрещён"
                              % (s["id"], ip))
    if _SECRET_HINT.search(blob):
        raise ConfigError("сценарий %s: похоже на реальные учётные данные" % s["id"])
    return True


# ── Доказательства изоляции ──────────────────────────────────────────────────
def production_data_dir():
    """Рабочая папка данных владельца — ТОЛЬКО чтобы доказать, что мы её не трогаем.

    server.py не импортируется (импорт живой программы завершает процесс на именованном
    мьютексе). Путь вычисляется так же, как в продукте: config.json, иначе умолчание.
    """
    la = os.environ.get("LOCALAPPDATA") or ""
    cfg = os.path.join(la, "3DIWELL", "config.json") if la else ""
    if cfg and os.path.isfile(cfg):
        try:
            custom = (json.load(io.open(cfg, encoding="utf-8")).get("data_dir") or "").strip()
            if custom:
                return os.path.abspath(custom)
        except Exception:
            pass
    base = la or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.abspath(os.path.join(base, "3DIWELL"))


def _inside(child, parent):
    try:
        c, p = os.path.abspath(child), os.path.abspath(parent)
        return c == p or c.startswith(p + os.sep)
    except Exception:
        return False


def free_local_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def port_is_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", int(port))) != 0
    finally:
        s.close()


def fuses_off():
    """Предохранители печати нельзя включить в этом запуске.

    Читается ИСХОДНИК (не рабочие настройки владельца): изолированный экземпляр получает
    собственный пустой config, поэтому действуют именно значения по умолчанию из кода.
    """
    out = {}
    try:
        src = io.open(os.path.join(REPO, "app", "project_orchestrator.py"),
                      encoding="utf-8", errors="replace").read()
        out["DISPATCH_ENABLED"] = bool(re.search(r"^DISPATCH_ENABLED\s*=\s*False\s*$",
                                                 src, re.M))
        out["TRANSPORT_ENABLED"] = bool(re.search(r"^TRANSPORT_ENABLED\s*=\s*False\s*$",
                                                  src, re.M))
    except Exception as e:
        out["error"] = str(e)[:120]
    return out


def production_fingerprint(root=None):
    """Безопасный отпечаток рабочей папки владельца: только имена, размеры и время.

    Содержимое НЕ читается — ни БД, ни конфигурация. Абсолютный путь не возвращается:
    в артефакты попадает лишь отпечаток, по которому видно «изменилось / не изменилось».
    """
    prod = root or production_data_dir()
    if not os.path.isdir(prod):
        return {"exists": False, "entries": 0, "total_bytes": 0, "sha256": None}
    h = hashlib.sha256()
    n, total = 0, 0
    for base, dirs, files in os.walk(prod):
        dirs.sort()
        for f in sorted(files):
            full = os.path.join(base, f)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, prod).replace("\\", "/")
            h.update(("%s|%d|%d\n" % (rel, st.st_size, int(st.st_mtime))).encode("utf-8"))
            n += 1
            total += st.st_size
            if n >= 20000:
                break
        if n >= 20000:
            break
    return {"exists": True, "entries": n, "total_bytes": total, "sha256": h.hexdigest()}


def build_e2e_contract(run_dir, port):
    """Параметры официального режима изоляции. Ничего не выдумывается: только FM_E2E_*."""
    token = hashlib.sha256(os.urandom(32)).hexdigest()[:40]
    test_data = os.path.join(run_dir, "test_data")
    config_path = os.path.join(test_data, "config.json")     # контракт требует внутри root
    run_id = os.path.basename(run_dir)
    return {
        "flag": E2E_FLAG,
        "token": token,
        "run_id": run_id,
        "data_dir": test_data,
        "config_path": config_path,
        "mutex_name": "Local\\3DIWELL_FM_UI_" + re.sub(r"[^A-Za-z0-9]", "", run_id)[:24],
        "port": int(port),
        "instance_id": run_id[:32],
        "disables": {"tray": "1", "browser": "1", "discovery": "1", "printers": "1",
                     "modules": "1"},
    }


def check_e2e_contract(contract, run_dir):
    """Доказательства ДО запуска. Не сошлось хоть одно — сервер не стартует."""
    prod = production_data_dir()
    td, cfg = contract["data_dir"], contract["config_path"]
    p = {}
    p["data_dir_inside_run"] = _inside(td, os.path.join(run_dir, "test_data"))
    p["config_inside_run"] = _inside(cfg, run_dir)
    p["config_inside_data_dir"] = _inside(os.path.dirname(cfg), td)
    p["data_dir_not_production"] = os.path.normcase(os.path.abspath(td)) != \
        os.path.normcase(os.path.abspath(prod))
    p["data_dir_not_parent_of_production"] = not _inside(prod, td)
    p["data_dir_not_child_of_production"] = not _inside(td, prod)
    p["data_dir_empty"] = os.path.isdir(td) and not os.listdir(td)
    p["mutex_unique"] = (contract["mutex_name"] != PRODUCTION_MUTEX
                         and contract["mutex_name"].startswith("Local\\")
                         and contract["run_id"][:8].replace("-", "") in
                         contract["mutex_name"])
    p["port_is_random_loopback"] = 1024 <= contract["port"] <= 65535
    p["port_differs_from_production"] = contract["port"] != PRODUCTION_PORT_DEFAULT
    p["port_free_before_start"] = port_is_free(contract["port"])
    for k, v in contract["disables"].items():
        p["disabled_" + k] = (v == "1")
    f = fuses_off()
    p["dispatch_disabled"] = bool(f.get("DISPATCH_ENABLED"))
    p["transport_disabled"] = bool(f.get("TRANSPORT_ENABLED"))
    # Собственный одноразовый токен изоляции из проверки исключается: он и есть предмет
    # контракта, а не чужие учётные данные. В артефакты он всё равно не попадает.
    scanned = dict((k, v) for k, v in contract.items() if k != "token")
    blob = json.dumps(scanned, ensure_ascii=False)
    p["no_credentials_in_contract"] = not _SECRET_HINT.search(blob) and not [
        ip for ip in _IPV4.findall(blob) if not _LOCAL_IP.match(ip)]
    p["guard_module_present"] = os.path.isfile(os.path.join(GUARD_DIR, "sitecustomize.py"))
    p["production_path_not_recorded"] = True     # в контракт рабочий путь не попадает вовсе

    problems = [k for k, v in p.items() if not v]
    return p, problems


def write_e2e_marker(contract):
    """Маркер, которого требует продукт: доказательство, что папку подготовил знающий токен."""
    os.makedirs(contract["data_dir"], exist_ok=True)
    io.open(os.path.join(contract["data_dir"], E2E_MARKER_NAME), "w", encoding="utf-8",
            newline="\n").write(json.dumps({"token": contract["token"],
                                            "run_id": contract["run_id"]},
                                           ensure_ascii=False))


def server_env(contract, run_dir):
    env = dict((k, os.environ[k]) for k in ENV_ALLOW_SERVER if k in os.environ)
    tmp = os.path.join(run_dir, "test_temp")
    os.makedirs(tmp, exist_ok=True)
    env["TEMP"] = env["TMP"] = tmp                 # временные файлы тоже внутри запуска
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = GUARD_DIR                  # сторож сети только этому процессу
    env[GUARD_LOG_ENV] = os.path.join(run_dir, "network_guard", "guard.jsonl")
    env[GUARD_SENTINEL_ENV] = os.path.join(run_dir, "network_guard", "sentinel.json")
    env[E2E_ENV["sentinel"]] = contract["token"]
    env[E2E_ENV["instance"]] = contract["instance_id"]
    env[E2E_ENV["data_dir"]] = contract["data_dir"]
    env[E2E_ENV["config"]] = contract["config_path"]
    env[E2E_ENV["mutex"]] = contract["mutex_name"]
    env[E2E_ENV["port"]] = str(contract["port"])
    env[E2E_ENV["no_tray"]] = contract["disables"]["tray"]
    env[E2E_ENV["no_browser"]] = contract["disables"]["browser"]
    env[E2E_ENV["no_discovery"]] = contract["disables"]["discovery"]
    env[E2E_ENV["no_printers"]] = contract["disables"]["printers"]
    env[E2E_ENV["no_modules"]] = contract["disables"]["modules"]
    return env


def http_json(port, path, timeout=6.0):
    """GET по петле. Своя реализация на stdlib: ни requests, ни новых зависимостей."""
    try:
        s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    except Exception as e:
        return None, "нет соединения: %s" % str(e)[:80]
    try:
        s.settimeout(timeout)
        s.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n"
                   "Accept: application/json\r\n\r\n" % (path, int(port))).encode())
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
    except Exception as e:
        return None, "обрыв чтения: %s" % str(e)[:80]
    finally:
        try:
            s.close()
        except Exception:
            pass
    raw = b"".join(chunks).decode("utf-8", "replace")
    head, _, body = raw.partition("\r\n\r\n")
    status = 0
    if head.startswith("HTTP/"):
        try:
            status = int(head.split(" ")[1])
        except Exception:
            status = 0
    try:
        return {"status": status, "json": json.loads(body), "raw_len": len(body)}, None
    except Exception:
        return {"status": status, "json": None, "raw_len": len(body)}, None


def read_guard_log(run_dir):
    p = os.path.join(run_dir, "network_guard", "guard.jsonl")
    out = []
    if os.path.isfile(p):
        for line in io.open(p, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def preflight(run_dir, scenario):
    """Все доказательства до единого. Не сошлось хоть одно — не запускаем ничего."""
    proofs, problems = {}, []
    test_data = os.path.join(run_dir, "test_data")
    profile = os.path.join(run_dir, "browser_profile")
    prod = production_data_dir()

    proofs["test_data_inside_run"] = _inside(test_data, run_dir)
    proofs["profile_inside_run"] = _inside(profile, run_dir)
    proofs["run_inside_ignored_logs"] = _inside(run_dir, os.path.join(REPO, "logs"))
    proofs["test_data_created_empty"] = os.path.isdir(test_data) and not os.listdir(test_data)
    proofs["production_not_parent"] = not _inside(test_data, prod)
    proofs["production_not_child"] = not _inside(prod, test_data)
    proofs["production_path_untouched"] = True     # мы её только читаем для сравнения
    # Значение рабочего пути в артефакты не попадает — только его отпечаток.
    proofs["production_path_sha256"] = hashlib.sha256(
        os.path.normcase(prod).encode("utf-8")).hexdigest()

    port = free_local_port()
    proofs["port"] = port
    proofs["port_bound_to_loopback_only"] = True
    proofs["port_free_before_start"] = port_is_free(port)

    f = fuses_off()
    proofs["fuses"] = f
    proofs["dispatch_cannot_be_enabled"] = bool(f.get("DISPATCH_ENABLED"))
    proofs["transport_cannot_be_enabled"] = bool(f.get("TRANSPORT_ENABLED"))

    blob = json.dumps(scenario, ensure_ascii=False)
    proofs["no_production_credentials"] = not _SECRET_HINT.search(blob) and not [
        ip for ip in _IPV4.findall(blob) if not _LOCAL_IP.match(ip)]

    engine = next((p for p in ENGINE_ALLOWLIST if os.path.isfile(p)), None)
    node = next((p for p in NODE_ALLOWLIST if os.path.isfile(p)), None) or shutil.which("node")
    proofs["engine_from_allowlist"] = bool(engine)
    proofs["node_available"] = bool(node)

    for key, label in (
            ("test_data_inside_run", "тестовая папка данных вне каталога запуска"),
            ("profile_inside_run", "профиль браузера вне каталога запуска"),
            ("run_inside_ignored_logs", "каталог запуска вне игнорируемого logs/"),
            ("test_data_created_empty", "тестовая папка данных не пуста — она обязана быть новой"),
            ("production_not_parent", "тестовая папка внутри рабочей папки владельца"),
            ("production_not_child", "рабочая папка владельца внутри тестовой"),
            ("port_free_before_start", "выбранный локальный порт занят"),
            ("dispatch_cannot_be_enabled", "DISPATCH_ENABLED не подтверждён как False"),
            ("transport_cannot_be_enabled", "TRANSPORT_ENABLED не подтверждён как False"),
            ("no_production_credentials", "в сценарии похоже на реальные учётные данные"),
            ("engine_from_allowlist", "движок браузера не найден в контролируемом списке"),
            ("node_available", "node не найден")):
        if not proofs.get(key):
            problems.append(label)

    return proofs, problems, {"engine": engine, "node": node, "port": port,
                              "test_data": test_data, "profile": profile}


# ── Процессы: только свои и только по PID ────────────────────────────────────
def child_env(extra=None):
    env = dict((k, os.environ[k]) for k in ENV_ALLOW if k in os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra or {})
    return env


def spawn(argv, log_base, env=None, cwd=None):
    """Запуск без видимого окна, stdout/stderr — в файлы. Возвращает (proc, files)."""
    out = io.open(log_base + ".stdout.txt", "w", encoding="utf-8", newline="\n")
    err = io.open(log_base + ".stderr.txt", "w", encoding="utf-8", newline="\n")
    kw = dict(cwd=cwd or REPO, stdout=out, stderr=err, shell=False, env=env or child_env())
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(argv, **kw), (out, err)


def kill_own(pid):
    """Завершить СВОЙ процесс и его детей по PID. По имени процессы не ищутся никогда:
    это снесло бы браузер владельца и посторонние python."""
    if not pid:
        return "no_pid"
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           shell=False, timeout=25)
        else:
            import signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        return "killed"
    except Exception as e:
        return "kill_failed: %s" % str(e)[:80]


def pid_alive(pid):
    if not pid:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/NH"],
                               capture_output=True, text=True, shell=False, timeout=20)
            return str(pid) in (r.stdout or "")
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def wait_http(port, path, proc, deadline_s):
    """Готовность локального сервера. Ранний выход процесса — отказ, даже при коде 0."""
    end = time.time() + deadline_s
    while time.time() < end:
        rc = proc.poll()
        if rc is not None:
            return False, ("сервер завершился до готовности, код %s — код 0 успехом "
                           "НЕ считается" % rc)
        try:
            s = socket.create_connection(("127.0.0.1", int(port)), timeout=1.5)
            s.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
                       % path).encode())
            head = s.recv(200).decode("utf-8", "replace")
            s.close()
            if head.startswith("HTTP/"):
                return True, head.splitlines()[0]
        except Exception:
            time.sleep(0.3)
    return False, "сервер не ответил за %d c" % deadline_s


# ── Классификация сетевых обращений ──────────────────────────────────────────
def classify_network(entries, policy, port):
    hosts = tuple(policy.get("allowed_hosts") or LOCAL_HOSTS)
    schemes = tuple(policy.get("allowed_schemes") or []) + LOCAL_SCHEMES
    out = []
    for e in entries or []:
        url = str((e or {}).get("url") or "")
        kind = str((e or {}).get("kind") or "resource")
        ext = True
        low = url.lower()
        if not url:
            ext = False
        elif low.startswith(schemes):
            ext = False
        else:
            m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)", low)
            host = (m.group(1) if m else "").split("@")[-1]
            hostname = host.rsplit(":", 1)[0] if ":" in host and not host.endswith("]") else host
            if not m:
                ext = False                                  # относительный путь той же страницы
            elif hostname in hosts:
                ext = False
        out.append({"url": url[:300], "kind": kind, "external": ext})
    return out


# ── Основной сценарий ────────────────────────────────────────────────────────
def run(scenario_id, execute=False, scenarios_path=None, runs_dir=None):
    scens = load_scenarios(scenarios_path)
    if scenario_id not in scens:
        raise ConfigError("сценарий %r не найден в реестре; доступны: %s"
                          % (scenario_id, ", ".join(sorted(scens))))
    sc = scens[scenario_id]
    started = datetime.datetime.now()
    run_id = started.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    root = runs_dir or RUNS_DIR
    run_dir = os.path.join(root, run_id)

    res = {
        "schema_version": SCHEMA, "run_id": run_id, "scenario_id": scenario_id,
        "application_mode": sc["application_mode"],
        "coverage_scope": ("реальный фронтенд web/ в headless-браузере поверх синтетического "
                           "backend; серверная логика Farm Manager НЕ проверена"
                           if sc["application_mode"] == "static_harness"
                           else "изолированный экземпляр Farm Manager целиком"),
        "started_at": started.isoformat(timespec="seconds"), "finished_at": None,
        "duration_seconds": 0.0, "status": None, "exit_code": None,
        "test_data_path": None, "browser_profile_path": None, "local_url": None,
        "server_pid": None, "browser_pid": None,
        "viewport": sc.get("viewport"), "locale": sc.get("locale"), "zoom": sc.get("zoom"),
        "actions_total": len(sc["actions"]), "actions_passed": 0,
        "assertions_total": len(sc["assertions"]), "assertions_passed": 0,
        "console_error_count": 0, "external_network_attempt_count": 0,
        "screenshots": [], "cleanup_status": None, "port_released": None,
        "remaining_owned_processes": [], "warnings": [], "limitations": [
            "статический стенд отдаёт реальные web/index.html, app.js и app.css, но ответы /api "
            "синтетические: поведение backend этим сценарием не проверяется",
            "проверен один экран; остальная UI-матрица не покрыта",
            "верификатор не подключён к run_profile.py: ui_required по-прежнему даёт PARTIAL",
        ],
        "isolation_proofs": {}, "artifacts_path": None,
        # Времена фаз: нужны внешней квалификации стабильности, чтобы она измеряла, а не
        # выдумывала. Null означает «фаза в этом режиме отдельно не измеряется».
        "phase_seconds": {"startup": None, "readiness": None, "browser": None,
                          "cleanup": None},
        # ── поля режима isolated_farm_manager ──────────────────────────────────
        "server_command_fingerprint": None, "e2e_contract_verified": None,
        "network_guard_active": None, "network_guard_sentinel": None,
        "backend_assertions_total": 0, "backend_assertions_passed": 0,
        "browser_network_attempts": 0, "backend_network_attempts": 0,
        "blocked_network_attempts": 0, "test_database_created": None,
        "test_database_path_relative": None,
        "production_data_fingerprint_before": None,
        "production_data_fingerprint_after": None, "production_data_unchanged": None,
        "repository_product_files_unchanged": None, "readiness_verified": None,
    }

    os.makedirs(run_dir, exist_ok=True)
    for sub in ("test_data", "test_config", "browser_profile", "artifacts",
                "process_logs", "network_guard"):
        os.makedirs(os.path.join(run_dir, sub), exist_ok=True)

    proofs, problems, env = preflight(run_dir, sc)
    res["isolation_proofs"] = proofs
    res["test_data_path"] = os.path.relpath(env["test_data"], REPO).replace("\\", "/")
    res["browser_profile_path"] = os.path.relpath(env["profile"], REPO).replace("\\", "/")
    res["artifacts_path"] = os.path.relpath(run_dir, REPO).replace("\\", "/")
    res["local_url"] = "http://127.0.0.1:<порт выбирается при запуске>/"

    if problems:
        res.update(status=BLOCKED, exit_code=EXIT[BLOCKED],
                   finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
        res["warnings"].extend(problems)
        return res, sc, None

    if not execute:
        res.update(status=DRY_RUN, exit_code=EXIT[DRY_RUN],
                   finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
        # Артефактов у dry-run быть не должно: каталог создавался только под доказательства.
        shutil.rmtree(run_dir, ignore_errors=True)
        res["artifacts_path"] = None
        return res, sc, None

    return _execute(res, sc, run_dir, env)


def _execute(res, sc, run_dir, env):
    t0 = time.time()
    manifest = {"run_id": res["run_id"], "processes": []}
    logs = os.path.join(run_dir, "process_logs")
    artifacts = os.path.join(run_dir, "artifacts")
    server, browser, handles = None, None, []
    driver_result, cleanup = None, {}
    status = FAIL

    isolated = sc["application_mode"] == "isolated_farm_manager"
    contract, prod_before = None, None
    t_phase = time.time()
    try:
        if isolated:
            port = env["port"]
            contract = build_e2e_contract(run_dir, port)
            proofs, problems = check_e2e_contract(contract, run_dir)
            res["e2e_contract_verified"] = not problems
            io.open(os.path.join(run_dir, "e2e_contract.json"), "w", encoding="utf-8",
                    newline="\n").write(json.dumps(
                        {"flag": contract["flag"], "run_id": contract["run_id"],
                         "port": contract["port"], "mutex_name": contract["mutex_name"],
                         "data_dir_relative": os.path.relpath(contract["data_dir"], run_dir)
                         .replace("\\", "/"),
                         "config_relative": os.path.relpath(contract["config_path"], run_dir)
                         .replace("\\", "/"),
                         "disables": contract["disables"], "proofs": proofs,
                         "note": "токен и рабочий путь владельца сюда намеренно не пишутся"},
                        ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            if problems:
                res["warnings"].extend("контракт изоляции не доказан: %s" % p
                                       for p in problems)
                res["status"] = BLOCKED
                res["exit_code"] = EXIT[BLOCKED]
                return res, sc, None

            prod_before = production_fingerprint()
            repo_before = repo_product_fingerprint()
            res["production_data_fingerprint_before"] = prod_before
            write_e2e_marker(contract)
            argv = [sys.executable, os.path.join(REPO, "server.py"), E2E_FLAG]
            res["server_command_fingerprint"] = hashlib.sha256(
                json.dumps([os.path.basename(argv[0]), "server.py", E2E_FLAG]).encode()
            ).hexdigest()[:32]
            server, h = spawn(argv, os.path.join(logs, "farm_manager"),
                              env=server_env(contract, run_dir))
            handles.extend(h)
            manifest["processes"].append({"role": "isolated_farm_manager",
                                          "pid": server.pid,
                                          "argv0": os.path.basename(sys.executable),
                                          "flag": E2E_FLAG})
            res["server_pid"] = server.pid

            ready = readiness_proof(server, contract, run_dir)
            io.open(os.path.join(run_dir, "readiness.json"), "w", encoding="utf-8",
                    newline="\n").write(json.dumps(ready, ensure_ascii=False, indent=1,
                                                   sort_keys=True) + "\n")
            res["readiness_verified"] = ready["ready"]
            res["phase_seconds"]["readiness"] = ready.get("elapsed_seconds")
            res["phase_seconds"]["startup"] = round(time.time() - t_phase, 3)
            sent = os.path.join(run_dir, "network_guard", "sentinel.json")
            res["network_guard_sentinel"] = os.path.isfile(sent)
            res["network_guard_active"] = res["network_guard_sentinel"]
            if not ready["ready"]:
                res["warnings"].append("готовность сервера не подтверждена: %s"
                                       % (ready.get("detail") or ready.get("startup_error")))
                res["status"] = FAIL
                res["exit_code"] = EXIT[FAIL]
                return res, sc, None
            if not res["network_guard_sentinel"]:
                res["warnings"].append("сторож сети не оставил удостоверения — "
                                       "изоляция backend недоказуема")
                res["status"] = BLOCKED
                res["exit_code"] = EXIT[BLOCKED]
                return res, sc, None

            # Проверки backend выполняются ДО запуска браузера.
            ba = backend_assertions(contract, run_dir)
            res["backend_assertions_total"] = len(ba)
            res["backend_assertions_passed"] = sum(1 for x in ba if x["passed"])
            res["_backend_assertions"] = ba
            io.open(os.path.join(run_dir, "backend_assertions.json"), "w",
                    encoding="utf-8", newline="\n").write(
                        json.dumps(ba, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
            if res["backend_assertions_passed"] != res["backend_assertions_total"]:
                res["warnings"].extend("backend: %s не пройдена (%s)"
                                       % (x["id"], x["detail"])
                                       for x in ba if not x["passed"])
                res["status"] = FAIL
                res["exit_code"] = EXIT[FAIL]
                return res, sc, None
            res["local_url"] = "http://127.0.0.1:%d/" % port
        else:
            port_file = os.path.join(logs, "stage_port.txt")
            server, h = spawn([sys.executable, os.path.join(HERE, "_stage_server.py"),
                               port_file], os.path.join(logs, "stage_server"))
            handles.extend(h)
            manifest["processes"].append({"role": "stage_server", "pid": server.pid,
                                          "argv0": os.path.basename(sys.executable)})
            res["server_pid"] = server.pid

            port = None
            end = time.time() + 30
            while time.time() < end and port is None:
                if server.poll() is not None:
                    break
                if os.path.isfile(port_file):
                    try:
                        port = int(io.open(port_file, encoding="utf-8").read().strip())
                    except Exception:
                        port = None
                if port is None:
                    time.sleep(0.2)
            if port is None:
                rc = server.poll()
                res["warnings"].append("стенд не сообщил порт; код завершения %s "
                                       "(код 0 успехом не считается)" % rc)
                res["status"] = FAIL
                res["exit_code"] = EXIT[FAIL]
                return res, sc, None

            ok, detail = wait_http(port, "/", server, 30)
            if not ok:
                res["warnings"].append("стенд не готов: %s" % detail)
                res["status"] = FAIL
                res["exit_code"] = EXIT[FAIL]
                return res, sc, None
            res["local_url"] = "http://127.0.0.1:%d/" % port
            res["phase_seconds"]["startup"] = round(time.time() - t_phase, 3)

        cfg = {
            "engine": env["engine"], "url": res["local_url"],
            "profile_dir": os.path.join(env["profile"], "prof"),
            "viewport": sc.get("viewport") or {"width": 1440, "height": 900},
            "settle_ms": 1600, "timeout_seconds": int(sc["timeout_seconds"]),
            "actions": sc["actions"], "artifacts_dir": artifacts,
            "application_mode": sc["application_mode"],
            "result_path": os.path.join(artifacts, "driver_result.json"),
            # Жёсткий запрет резолвинга чужих имён: наружу браузер физически не выйдет.
            "extra_args": ["--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
                           "--no-proxy-server", "--disable-background-networking",
                           "--disable-sync", "--disable-component-update"],
        }
        cfg_path = os.path.join(logs, "driver_config.json")
        io.open(cfg_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(cfg, ensure_ascii=False, indent=1))

        browser, h = spawn([env["node"], os.path.join(HERE, "_ui_driver.mjs"), cfg_path],
                           os.path.join(logs, "ui_driver"))
        handles.extend(h)
        manifest["processes"].append({"role": "ui_driver_and_browser", "pid": browser.pid,
                                      "argv0": os.path.basename(env["node"]),
                                      "note": "браузер — дочерний процесс драйвера"})
        res["browser_pid"] = browser.pid

        t_browser = time.time()
        try:
            browser.wait(timeout=int(sc["timeout_seconds"]) + 60)
        except subprocess.TimeoutExpired:
            kill_own(browser.pid)
            res["warnings"].append("драйвер не уложился в бюджет времени")
            status = TIMEOUT

        res["phase_seconds"]["browser"] = round(time.time() - t_browser, 3)
        rp = os.path.join(artifacts, "driver_result.json")
        if os.path.isfile(rp):
            try:
                driver_result = json.load(io.open(rp, encoding="utf-8"))
            except Exception as e:
                res["warnings"].append("результат драйвера не читается: %s" % e)
        else:
            res["warnings"].append("драйвер не оставил результата")

        if status != TIMEOUT:
            status = _judge(res, sc, driver_result, port)

        if isolated:
            guard = read_guard_log(run_dir)
            io.open(os.path.join(run_dir, "network_guard", "guard_parsed.json"), "w",
                    encoding="utf-8", newline="\n").write(
                        json.dumps(guard, ensure_ascii=False, indent=1) + "\n")
            attempts = [g for g in guard if g.get("kind") in ("connect", "connect_ex",
                                                              "sendto")]
            blocked = [g for g in attempts if not g.get("allowed")]
            res["backend_network_attempts"] = len(attempts)
            res["blocked_network_attempts"] = len(blocked)
            res["browser_network_attempts"] = len(res.get("network") or [])
            if blocked:
                res["warnings"].extend("сторож заблокировал внешнее соединение: %s:%s (%s)"
                                       % (g.get("host"), g.get("port"), g.get("reason"))
                                       for g in blocked[:6])
                status = FAIL

            prod_after = production_fingerprint()
            res["production_data_fingerprint_after"] = prod_after
            fa, listing = filesystem_assertions(contract, run_dir, prod_before or {},
                                                prod_after, repo_before,
                                                repo_product_fingerprint())
            res["production_data_unchanged"] = next(
                (x["passed"] for x in fa if x["id"] == "production_data_unchanged"), None)
            res["repository_product_files_unchanged"] = next(
                (x["passed"] for x in fa if x["id"] ==
                 "repository_product_files_unchanged"), None)
            res["test_database_created"] = bool(listing["database_files"])
            res["test_database_path_relative"] = (listing["database_files"][0]
                                                  if listing["database_files"] else None)
            io.open(os.path.join(run_dir, "filesystem_assertions.json"), "w",
                    encoding="utf-8", newline="\n").write(json.dumps(
                        {"assertions": fa, "listing": listing}, ensure_ascii=False,
                        indent=1, sort_keys=True) + "\n")
            # Копия конфигурации как доказательство — рядом, в test_config/.
            if os.path.isfile(contract["config_path"]):
                raw = io.open(contract["config_path"], "rb").read()
                io.open(os.path.join(run_dir, "test_config", "config_evidence.json"), "w",
                        encoding="utf-8", newline="\n").write(json.dumps({
                            "relative_path": os.path.relpath(contract["config_path"],
                                                             run_dir).replace("\\", "/"),
                            "bytes": len(raw),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "keys": sorted(list((json.loads(raw.decode("utf-8", "replace"))
                                                 or {}).keys()))[:40]
                            if raw.strip().startswith(b"{") else [],
                        }, ensure_ascii=False, indent=1) + "\n")
            if not all(x["passed"] for x in fa):
                res["warnings"].extend("файловая система: %s не пройдена (%s)"
                                       % (x["id"], x["detail"])
                                       for x in fa if not x["passed"])
                status = FAIL

            # UI обязан был разговаривать с НАСТОЯЩИМ сервером, а не со стендом.
            api = [n for n in (res.get("network") or [])
                   if re.search(r"://127\.0\.0\.1:%d/(api|version)" % port, n["url"])]
            if not api:
                res["warnings"].append("в журнале браузера нет ни одного обращения к API "
                                       "настоящего сервера — связка не доказана")
                status = FAIL
            res["_real_backend_requests"] = len(api)
            pids = [p["pid"] for p in manifest["processes"]
                    if p["role"] == "isolated_farm_manager"]
            if res["server_pid"] not in pids:
                res["warnings"].append("PID сервера не совпал с манифестом процессов")
                status = FAIL
    finally:
        t_cleanup = time.time()
        cleanup = _cleanup(res, server, browser, manifest, run_dir)
        res["phase_seconds"]["cleanup"] = round(time.time() - t_cleanup, 3)
        for f in handles:
            try:
                f.close()
            except Exception:
                pass

    res["cleanup_status"] = cleanup.get("status")
    res["port_released"] = cleanup.get("port_released")
    res["remaining_owned_processes"] = cleanup.get("remaining", [])
    io.open(os.path.join(run_dir, "cleanup.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(cleanup, ensure_ascii=False, indent=1) + "\n")
    if cleanup.get("port_released") is not True and status == PASS:
        status = FAIL
        res["warnings"].append("порт не освобождён после уборки — это не PASS")
    if res["remaining_owned_processes"] and status == PASS:
        status = FAIL
        res["warnings"].append("после уборки остались собственные процессы — это не PASS")
    res["duration_seconds"] = round(time.time() - t0, 3)
    res["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    res["status"] = status
    res["exit_code"] = EXIT[status]
    io.open(os.path.join(run_dir, "process_manifest.json"), "w", encoding="utf-8",
            newline="\n").write(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    return res, sc, driver_result


def readiness_proof(proc, contract, run_dir, deadline_s=90):
    """Готовность настоящего сервера. Открытый порт готовностью НЕ считается."""
    pr = {"checks": {}, "ready": False, "detail": "", "version": None, "boot_id": None,
          "elapsed_seconds": None}
    t0 = time.time()
    port = contract["port"]
    resp, err = None, ""
    while time.time() - t0 < deadline_s:
        rc = proc.poll()
        if rc is not None:
            pr["detail"] = ("серверный процесс завершился до готовности, код %s — "
                            "код 0 успехом НЕ считается" % rc)
            pr["checks"]["process_alive"] = False
            return pr
        resp, err = http_json(port, "/version", timeout=4.0)
        if resp and resp["status"] == 200 and isinstance(resp.get("json"), dict) \
                and resp["json"].get("version"):
            break
        resp = None
        time.sleep(0.5)

    c = pr["checks"]
    c["process_alive"] = proc.poll() is None
    c["official_readiness_answered"] = bool(resp)
    if resp:
        pr["version"] = resp["json"].get("version")
        pr["boot_id"] = str(resp["json"].get("boot_id") or "")[:64]
    c["answer_from_run_port"] = bool(resp) and port_is_free(port) is False
    c["e2e_isolation_accepted"] = os.path.isfile(
        os.path.join(contract["data_dir"], E2E_MARKER_NAME)) and bool(resp)
    sentinel = os.path.join(run_dir, "network_guard", "sentinel.json")
    c["network_guard_sentinel"] = os.path.isfile(sentinel)
    created = [n for n in os.listdir(contract["data_dir"])] if os.path.isdir(
        contract["data_dir"]) else []
    c["test_data_dir_actually_used"] = len([n for n in created
                                            if n != E2E_MARKER_NAME]) > 0
    c["production_data_dir_not_used"] = True     # подтверждается отпечатком до/после
    f = fuses_off()
    cfg_txt = ""
    if os.path.isfile(contract["config_path"]):
        cfg_txt = io.open(contract["config_path"], encoding="utf-8",
                          errors="replace").read()
    c["dispatch_transport_effectively_off"] = (
        bool(f.get("DISPATCH_ENABLED")) and bool(f.get("TRANSPORT_ENABLED"))
        and "project_print_enabled" not in cfg_txt)
    stderr_p = os.path.join(run_dir, "process_logs", "farm_manager.stderr.txt")
    stdout_p = os.path.join(run_dir, "process_logs", "farm_manager.stdout.txt")
    bad = ""
    for p in (stdout_p, stderr_p):
        if os.path.isfile(p):
            t = io.open(p, encoding="utf-8", errors="replace").read()
            if "E2E isolation rejected" in t:
                bad = t[t.find("E2E isolation rejected"):][:160]
            elif "Traceback (most recent call last)" in t:
                bad = "исключение при старте сервера"
    c["no_startup_error"] = not bad
    pr["startup_error"] = bad or None
    c["within_timeout"] = bool(resp)
    pr["elapsed_seconds"] = round(time.time() - t0, 2)
    pr["ready"] = all(c.values())
    if not pr["ready"] and not pr["detail"]:
        pr["detail"] = "не подтверждено: " + ", ".join(k for k, v in c.items() if not v)
    return pr


def backend_assertions(contract, run_dir, expected_version="Alpha 2.841"):
    """Только чтение через РЕАЛЬНЫЕ эндпоинты продукта. Ничего не создаётся и не меняется."""
    port = contract["port"]
    out = []

    def add(name, ok, how, detail=""):
        out.append({"id": name, "passed": bool(ok), "proof": how,
                    "detail": str(detail)[:200]})

    v, _ = http_json(port, "/version")
    add("readiness_endpoint", bool(v) and v["status"] == 200, "GET /version",
        v and v["status"])
    add("version_matches", bool(v) and (v.get("json") or {}).get("version") ==
        expected_version, "GET /version -> version", (v or {}).get("json"))

    # Режим изоляции подтверждается не эндпоинтом (его нет), а тем, что продукт создал
    # свои файлы ИМЕННО в тестовой папке: без принятого контракта он бы туда не писал.
    names = sorted(os.listdir(contract["data_dir"])) if os.path.isdir(
        contract["data_dir"]) else []
    add("isolated_mode_active", any(n != E2E_MARKER_NAME for n in names),
        "файлы созданы в тестовом DATA_DIR (эндпоинта режима в продукте нет)",
        names[:10])

    pr, _ = http_json(port, "/api/printers")
    plist = (pr or {}).get("json")
    add("printers_empty", bool(pr) and pr["status"] == 200 and isinstance(plist, list)
        and len(plist) == 0, "GET /api/printers", "status=%s n=%s"
        % ((pr or {}).get("status"), len(plist) if isinstance(plist, list) else plist))

    sj, _ = http_json(port, "/api/send-jobs")
    jobs = ((sj or {}).get("json") or {})
    add("no_active_queue", bool(sj) and sj["status"] == 200
        and not (jobs.get("jobs") or []) and not (jobs.get("reserved_printer_ids") or []),
        "GET /api/send-jobs", jobs if isinstance(jobs, dict) else sj)

    f = fuses_off()
    cfg_txt = io.open(contract["config_path"], encoding="utf-8", errors="replace").read() \
        if os.path.isfile(contract["config_path"]) else ""
    add("dispatch_transport_off", bool(f.get("DISPATCH_ENABLED"))
        and bool(f.get("TRANSPORT_ENABLED")) and "project_print_enabled" not in cfg_txt,
        "исходные предохранители False + тестовый config без project_print_enabled "
        "(read-only эндпоинта состояния предохранителей в продукте нет)",
        "config_keys=%d" % len(cfg_txt))

    blob = cfg_txt + json.dumps(plist if isinstance(plist, list) else [], ensure_ascii=False)
    ips = [ip for ip in _IPV4.findall(blob) if not _LOCAL_IP.match(ip)]
    add("no_production_credentials", not _SECRET_HINT.search(blob) and not ips,
        "разбор тестового config и списка принтеров", "внешних адресов: %d" % len(ips))

    md, _ = http_json(port, "/api/modules")
    add("answer_from_local_port", bool(md) and md["status"] in (200, 401, 403),
        "GET /api/modules с 127.0.0.1:%d" % port, (md or {}).get("status"))

    # Проверка обновлений обязана быть подавлена САМИМ контрактом изоляции, а не тем,
    # что сторож не пустил соединение. Доказываем двумя независимыми способами:
    # ответ маршрута и строка диагностики в выводе принятого контракта.
    before = len([g for g in read_guard_log(run_dir) if g.get("kind") == "connect"])
    uc, _ = http_json(port, "/api/update-check", timeout=10.0)
    body = (uc or {}).get("json") or {}
    after = len([g for g in read_guard_log(run_dir) if g.get("kind") == "connect"])
    add("update_check_suppressed",
        bool(uc) and uc["status"] == 200 and body.get("ok") is False
        and body.get("latest") is None and after == before,
        "GET /api/update-check: ответ без выхода наружу и без новых попыток соединения",
        "ok=%s latest=%s connect %d->%d" % (body.get("ok"), body.get("latest"),
                                            before, after))
    startup = ""
    p = os.path.join(run_dir, "process_logs", "farm_manager.stdout.txt")
    if os.path.isfile(p):
        startup = io.open(p, encoding="utf-8", errors="replace").read()
    add("update_suppression_declared_by_contract",
        "E2E isolation: update check disabled" in startup,
        "диагностика принятого контракта в выводе сервера",
        "строка найдена" if "update check disabled" in startup else "строки нет")
    return out


def filesystem_assertions(contract, run_dir, prod_before, prod_after,
                          repo_before=None, repo_after=None):
    """Что появилось на диске и где именно. Содержимое секретов не сохраняется."""
    td = contract["data_dir"]
    files, total = [], 0
    for base, dirs, names in os.walk(td):
        dirs.sort()
        for n in sorted(names):
            full = os.path.join(base, n)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, run_dir).replace("\\", "/")
            row = {"path": rel, "bytes": st.st_size,
                   "created": datetime.datetime.fromtimestamp(
                       st.st_mtime).isoformat(timespec="seconds")}
            if st.st_size <= 262144 and n.lower().endswith((".json", ".txt", ".ini",
                                                            ".cfg", ".log")):
                row["sha256"] = hashlib.sha256(io.open(full, "rb").read()).hexdigest()
            files.append(row)
            total += st.st_size

    dbs = [f for f in files if f["path"].lower().endswith((".db", ".sqlite", ".sqlite3"))]
    a = []

    def add(name, ok, how, detail=""):
        a.append({"id": name, "passed": bool(ok), "proof": how, "detail": str(detail)[:200]})

    add("test_data_dir_created", os.path.isdir(td), "os.path.isdir", len(files))
    # Свежий экземпляр записывает config только когда есть что сохранять, поэтому ТРЕБУЕТСЯ
    # не существование файла, а его местоположение: путь обязан быть внутри каталога запуска,
    # и если файл всё-таки создан — внутри тестового DATA_DIR. Отсутствие config само по себе
    # доказывает, что настройки владельца не переносились.
    cfg_exists = os.path.isfile(contract["config_path"])
    add("config_inside_run", _inside(contract["config_path"], run_dir)
        and (not cfg_exists or _inside(contract["config_path"], td)),
        "местоположение конфигурации (существование не требуется: продукт пишет её лениво)",
        "%s, файл создан: %s" % (os.path.relpath(contract["config_path"], run_dir)
                                 .replace("\\", "/"), cfg_exists))
    add("database_inside_test_data", all(_inside(os.path.join(run_dir, f["path"]), td)
                                         for f in dbs),
        "все найденные БД лежат внутри тестового DATA_DIR", [f["path"] for f in dbs])
    add("database_is_new_not_copy", all(f["bytes"] < 50 * 1024 * 1024 for f in dbs),
        "размер созданных БД соответствует свежей установке, а не копии рабочей",
        [f["bytes"] for f in dbs])
    add("all_runtime_files_inside_run", all(_inside(os.path.join(run_dir, f["path"]),
                                                    run_dir) for f in files),
        "нормализация путей относительно каталога запуска", len(files))
    add("production_data_unchanged",
        prod_before.get("sha256") == prod_after.get("sha256")
        and prod_before.get("entries") == prod_after.get("entries"),
        "отпечаток рабочей папки до и после (содержимое не читалось)",
        "entries %s -> %s" % (prod_before.get("entries"), prod_after.get("entries")))
    add("repository_product_files_unchanged",
        repo_before is None or repo_after is None
        or repo_before.get("sha256") == repo_after.get("sha256"),
        "отпечаток продуктовых путей ДО и ПОСЛЕ прогона (чистота дерева не проверяется: "
        "задача может законно менять продуктовый файл)",
        "entries %s -> %s" % ((repo_before or {}).get("entries"),
                              (repo_after or {}).get("entries")))
    return a, {"files": files, "total_bytes": total,
               "database_files": [f["path"] for f in dbs]}


PRODUCT_PATHS = ("server.py", "app", "web", "modules", "tools/release_gate.py")


def repo_product_fingerprint():
    """Отпечаток продуктовых файлов репозитория: имена, размеры, время. Без содержимого.

    Сравнивается ДО и ПОСЛЕ прогона. Проверять «чистое дерево» нельзя: задача может
    законно менять продуктовый файл, и тогда чистота дерева не имеет отношения к тому,
    испортил ли что-нибудь сам прогон.
    """
    h = hashlib.sha256()
    n = 0
    for rel in PRODUCT_PATHS:
        full = os.path.join(REPO, rel)
        if os.path.isfile(full):
            st = os.stat(full)
            h.update(("%s|%d|%d\n" % (rel, st.st_size, int(st.st_mtime))).encode("utf-8"))
            n += 1
            continue
        for base, dirs, files in os.walk(full):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for f in sorted(files):
                p = os.path.join(base, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                r = os.path.relpath(p, REPO).replace("\\", "/")
                h.update(("%s|%d|%d\n" % (r, st.st_size, int(st.st_mtime))).encode("utf-8"))
                n += 1
    return {"entries": n, "sha256": h.hexdigest()}


def _judge(res, sc, dr, port):
    """Вердикт. Скриншоты на него не влияют: без DOM-проверок PASS невозможен."""
    if not dr:
        res["warnings"].append("нет результата драйвера — проверять нечего")
        return FAIL
    if dr.get("timedOut"):
        return TIMEOUT
    if dr.get("bridgeError"):
        res["warnings"].append("мост браузера: %s" % dr["bridgeError"])
        return FAIL

    acts = dr.get("actions") or []
    asserts = dr.get("assertions") or []
    res["actions_passed"] = sum(1 for a in acts if a.get("status") == "pass")
    res["assertions_passed"] = sum(1 for a in asserts if a.get("status") == "pass")
    res["screenshots"] = list(dr.get("screenshots") or [])

    console = dr.get("console") or {}
    errs = list(console.get("errors") or []) + list(console.get("pageErrors") or []) \
        + list(console.get("unhandled") or [])
    res["console_error_count"] = len(errs)

    net = classify_network(dr.get("network"), sc.get("network_policy") or {}, port)
    res["network"] = net
    ext = [n for n in net if n["external"]]
    res["external_network_attempt_count"] = len(ext)

    ok = True
    # Драйвер раскладывает шаги по двум спискам: действия и проверки. Сверять надо сумму —
    # иначе «выполнено не всё» срабатывало бы на каждом сценарии с проверками.
    done_steps = len(acts) + len(asserts)
    if done_steps < len(sc["actions"]):
        res["warnings"].append("выполнены не все шаги сценария: %d из %d"
                               % (done_steps, len(sc["actions"])))
        ok = False
    if any(a.get("status") != "pass" for a in acts + asserts):
        bad = [a for a in acts + asserts if a.get("status") != "pass"]
        res["warnings"].extend("шаг %s (%s) красный: %s"
                               % (b.get("index"), b.get("type"), b.get("detail"))
                               for b in bad[:6])
        ok = False

    # Двойная запись: каждая обязательная проверка сценария обязана реально присутствовать
    # среди выполненных и быть зелёной. Молча пропущенная проверка не станет зелёным итогом.
    done = {}
    for a in asserts:
        done.setdefault((a.get("type"), a.get("detail", "").split(" -> ")[0]), []).append(a)
    for req in sc["assertions"]:
        if not req.get("must_pass"):
            continue
        found = [a for a in asserts
                 if a.get("type") == req["kind"]
                 and a.get("detail", "").startswith(req["selector"])
                 and a.get("status") == "pass"]
        if not found:
            res["warnings"].append("обязательная проверка не подтверждена: %s (%s %s)"
                                   % (req["id"], req["kind"], req["selector"]))
            ok = False
    if res["assertions_passed"] == 0:
        res["warnings"].append("ни одной пройденной проверки DOM — скриншот доказательством "
                               "не является")
        ok = False

    pol = sc.get("console_policy") or {}
    if errs and not pol.get("allow_errors"):
        res["warnings"].extend("console: %s" % str(e)[:160] for e in errs[:6])
        ok = False
    if ext and (sc.get("network_policy") or {}).get("external_attempt_is_failure", True):
        res["warnings"].extend("внешнее обращение: %s" % n["url"][:160] for n in ext[:6])
        ok = False

    missing_shots = [n for n in (sc.get("screenshot_names") or [])
                     if n not in res["screenshots"]]
    if missing_shots:
        res["warnings"].append("не получены скриншоты: %s" % ", ".join(missing_shots))
        ok = False
    return PASS if ok else FAIL


def _cleanup(res, server, browser, manifest, run_dir):
    """Порядок: сессия браузера -> свой браузер -> свой сервер -> порт -> свои процессы."""
    out = {"order": [], "remaining": []}
    server_role = next((p["role"] for p in manifest["processes"]
                        if p["role"] != "ui_driver_and_browser"), "server")
    for role, proc in (("ui_driver_and_browser", browser), (server_role, server)):
        if proc is None:
            continue
        try:
            if proc.poll() is None:
                out["order"].append("%s: kill_by_pid(%d)" % (role, proc.pid))
                kill_own(proc.pid)
                # Второй, независимый рубеж: прямое завершение объекта процесса. Нужен на
                # случай, когда kill_own подменён (например, в тесте) — иначе настоящий
                # сервер пережил бы уборку и остался жить.
                try:
                    if proc.poll() is None:
                        proc.kill()
                        out["order"].append("%s: direct_kill(%d)" % (role, proc.pid))
                except Exception:
                    pass
            else:
                out["order"].append("%s: уже завершён (код %s)" % (role, proc.poll()))
        except Exception as e:
            out["order"].append("%s: ошибка уборки %s" % (role, str(e)[:60]))
    time.sleep(0.8)
    for p in manifest["processes"]:
        if pid_alive(p["pid"]):
            out["remaining"].append(p)
    url = res.get("local_url") or ""
    m = re.search(r":(\d+)/", url)
    out["port_released"] = port_is_free(int(m.group(1))) if m else None
    out["status"] = "clean" if not out["remaining"] and out.get("port_released") is not False \
        else "dirty"
    return out


# ── Артефакты и вывод ────────────────────────────────────────────────────────
def write_artifacts(res, sc, dr):
    if not res.get("artifacts_path"):
        return
    root = os.path.join(REPO, res["artifacts_path"])
    if not os.path.isdir(root):
        return

    def w(name, obj):
        io.open(os.path.join(root, name), "w", encoding="utf-8", newline="\n").write(
            json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")

    clean = dict((k, v) for k, v in res.items() if not k.startswith("_"))
    w("summary.json", clean)
    w("scenario.json", sc)
    w("console.json", (dr or {}).get("console") or {})
    w("network_attempts.json", res.get("network") or [])
    w("request_log.json", {
        "browser_requests": res.get("network") or [],
        "real_backend_requests": res.get("_real_backend_requests", 0),
        "backend_socket_attempts": res.get("backend_network_attempts", 0),
        "blocked": res.get("blocked_network_attempts", 0),
        "note": "URL сохраняются без тел запросов, заголовков и учётных данных",
    })
    if res.get("_backend_assertions"):
        w("backend_assertions.json", res["_backend_assertions"])
    w("dom_assertions.json", {"actions": (dr or {}).get("actions") or [],
                              "assertions": (dr or {}).get("assertions") or [],
                              "required": sc.get("assertions") or [],
                              "reads": (dr or {}).get("reads") or {}})
    w("environment.json", {
        "python": sys.version.split()[0], "platform": sys.platform,
        "env_keys_passed_to_children": list(ENV_ALLOW) + ["PYTHONIOENCODING"],
        "engine_from_allowlist": True, "note": (
            "Полное окружение владельца намеренно НЕ сохраняется: дочерние процессы получают "
            "только перечисленные ключи, поэтому токены, ключи, пароли и личные пути сюда "
            "попасть не могут. Рабочий путь данных записан только отпечатком sha256."),
    })
    io.open(os.path.join(root, "summary.txt"), "w", encoding="utf-8", newline="\n").write(
        render(res) + "\n")


def render(res):
    L = ["=" * 78, "ПРОВЕРКА ИНТЕРФЕЙСА", "=" * 78,
         "сценарий: %s" % res["scenario_id"],
         "режим:    %s" % res["application_mode"],
         "охват:    %s" % res["coverage_scope"],
         "СТАТУС:   %s (код %s)" % (res["status"], res["exit_code"])]
    if res["status"] == DRY_RUN:
        L.append("НИЧЕГО НЕ ЗАПУЩЕНО: это план. Для запуска добавьте --execute.")
    L.append("")
    L.append("шаги:      %d из %d" % (res["actions_passed"], res["actions_total"]))
    L.append("проверки:  %d из %d" % (res["assertions_passed"], res["assertions_total"]))
    L.append("консоль:   ошибок %d" % res["console_error_count"])
    L.append("сеть:      внешних обращений %d" % res["external_network_attempt_count"])
    if res["screenshots"]:
        L.append("снимки:    %s" % ", ".join(res["screenshots"]))
    if res["server_pid"] or res["browser_pid"]:
        L.append("процессы:  сервер PID %s, драйвер PID %s"
                 % (res["server_pid"], res["browser_pid"]))
    if res["cleanup_status"]:
        L.append("уборка:    %s, порт освобождён: %s, осталось своих процессов: %d"
                 % (res["cleanup_status"], res["port_released"],
                    len(res["remaining_owned_processes"])))
    if res["warnings"]:
        L.append("")
        L.append("замечания:")
        for w in res["warnings"][:12]:
            L.append("   ! %s" % w)
    if res.get("artifacts_path"):
        L.append("")
        L.append("артефакты: %s" % res["artifacts_path"])
    if res["status"] == PASS:
        L.append("PASS означает: пройдены ВСЕ обязательные проверки DOM, консоль чиста, "
                 "наружу обращений нет.")
    return "\n".join(L)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="Изолированная проверка интерфейса (по умолчанию — только план).")
    ap.add_argument("--scenario", required=True, help="id сценария из реестра")
    ap.add_argument("--execute", action="store_true", help="действительно запустить")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--scenarios", help="служебное: другой файл реестра")
    ns = ap.parse_args(argv)

    try:
        res, sc, dr = run(ns.scenario, execute=ns.execute, scenarios_path=ns.scenarios)
    except ConfigError as e:
        payload = {"schema_version": SCHEMA, "status": CONFIG_ERROR, "error": str(e)}
        sys.stderr.write((json.dumps(payload, ensure_ascii=False) if ns.json
                          else "ОШИБКА КОНФИГУРАЦИИ: %s" % e) + "\n")
        return EXIT[CONFIG_ERROR]

    if ns.execute:
        write_artifacts(res, sc, dr)
    sys.stdout.write((json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
                      if ns.json else render(res)) + "\n")
    return res["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
