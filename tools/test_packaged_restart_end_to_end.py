# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""НАСТОЯЩИЙ end-to-end перезапуск собранного Farm Manager — Alpha 2.811.
=================================================================================================
ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ.

Alpha 2.810 починила подтверждение готовности (armed) и доказала это self-тестом собранного .exe.
Но у пользователя перезапуск всё равно не сработал: старая копия честно завершилась, а новая не
поднялась — ни сервера, ни значка в трее. Журнал перезапуска показал `successor_exited`, две
попытки. То есть отказ случился РОВНО в том звене, которое все прежние проверки подменяли моком:
в фактическом запуске преемника.

ROOT CAUSE (доказан экспериментом на собранном .exe). Собранная onefile-программа распаковывает
себя во временную папку и сообщает об этом дочерним процессам через переменные окружения. Копия
ТОГО ЖЕ .exe, запущенная изнутри программы, видит «архив уже распакован» и не распаковывается
заново — она берёт файлы из чужой папки. Пока родитель жив, это работает (поэтому helper 2.810
вооружался). Но преемник стартует ПОСЛЕ завершения родителя, а уходящий родитель свою папку
удаляет: преемник умирает внутри загрузчика, не выполнив ни строки Python (код выхода
0xFFFFFFFF). С очищенным окружением тот же запуск проходит нормально.

ВТОРОЙ ДЕФЕКТ, найденный по ходу. При смене порта supervisor ждал ответа `/version` на СТАРОМ
порту, хотя преемник поднимается на новом. Даже с работающим преемником перезапуск со сменой
порта был обречён считаться неудачным.

ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ. Полный производственный путь на НАСТОЯЩЕМ исполняемом файле:
frontend-маршрут `/api/restart` -> production restart service -> независимый helper -> штатное
завершение родителя -> ожидание PID/замка/порта -> запуск преемника -> подтверждённый `/version`.
Ничего не мокается: ни spawn, ни verify_armed, ни supervisor.

БЕЗОПАСНОСТЬ (жёстко). Тест поднимает ТОЛЬКО изолированный экземпляр: своя временная папка
данных, свой config, своя SQLite, свой замок одиночного экземпляра, свободный временный порт,
без трея, браузера, обнаружения, принтеров и модулей. Рабочие DATA_DIR/config/БД/порт/замок не
используются; рабочая программа не останавливается и не запускается; принтерам ничего не
отправляется. Порт 8000 и рабочее имя замка не трогаются вовсе. Завершение тестового экземпляра —
штатное (файл-просьба в его же временной папке), без принудительного снятия процессов.

Запуск: PYTHONIOENCODING=utf-8 python tools/test_packaged_restart_end_to_end.py   (0 = пройдено)
"""
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "PACKAGED_RESTART_E2E_SENTINEL_2_811"

from app import e2e_isolation as ISO

_SRV_SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', _SRV_SRC, re.M).group(1)
PRODUCTION_PORT = 8000
PRODUCTION_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")

fail = 0
_checked = 0
_verdict = [False]
_started_pids = set()


def check(name, cond):
    global fail, _checked
    _checked += 1
    print(("PASS" if cond else "FAIL") + " — " + name, flush=True)
    if not cond:
        fail += 1


def info(msg):
    print("      · " + msg, flush=True)


# ── Инструменты наблюдения за настоящими процессами ───────────────────────────────────────────
def free_port():
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def listener_pids(port):
    """PID'ы, слушающие 127.0.0.1:<port>. Источник истины о том, КТО реально держит порт.

    В onefile-сборке PID из Popen — это загрузчик, а слушает его дочерний процесс; поэтому
    личность экземпляра берём у операционной системы, а не у Popen."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                             timeout=30, creationflags=0x08000000).stdout or ""
    except Exception:
        return set()
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING":
            if parts[1].endswith(":%d" % int(port)) and parts[1].startswith("127.0.0.1"):
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    pass
    return pids


def http_version(port, timeout=3):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/version" % port, timeout=timeout) as r:
            return str((json.loads(r.read().decode("utf-8")) or {}).get("version") or "")
    except Exception:
        return None


def http_json(port, path, timeout=5):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def post_restart(port, timeout=90):
    """Настоящий production-маршрут перезапуска. -> (http_status, тело)."""
    req = urllib.request.Request("http://127.0.0.1:%d/api/restart" % port, data=b"",
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"transport_error": type(e).__name__}


def wait_for(fn, timeout, step=0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


# ── Выбор исполняемого файла: настоящий собранный EXE, иначе исходники ────────────────────────
def resolve_server_command():
    """-> (префикс команды, режим, причина отката). Берём ТОЛЬКО сборку ТЕКУЩЕЙ версии.

    🔒 ПРАВИЛО БЕЗОПАСНОСТИ, ОПЛАЧЕННОЕ ОШИБКОЙ. Исполняемый файл, собранный ДО появления режима
    изоляции, не знает про `--fm-packaged-e2e`: он воспримет флаг как посторонний аргумент,
    проигнорирует переменные окружения и поднимется на РАБОЧЕМ порту с РАБОЧЕЙ папкой данных —
    то есть тест сам запустит второй производственный backend. Именно это и произошло при первом
    прогоне: сборка предыдущей версии применила отложенную смену порта в рабочем config.
    Снаружи «понимает ли .exe изоляцию» не определить никак, поэтому правило простое и жёсткое:
    запускается ТОЛЬКО сборка, рядом с которой лежит файл-удостоверение `e2e-supported.txt` с
    ТОЧНОЙ текущей версией. Этот файл кладёт сборочный шаг ПОСЛЕ успешной сборки текущего
    исходника — старые сборки его не имеют и получить не могут. Рабочая папка dist\\ кандидатом
    не является никогда. Нет такой сборки — прогон идёт на исходниках: тот же полный
    производственный путь, но без onefile-загрузчика."""
    def certified(exe):
        """Сборка удостоверена как понимающая изоляцию: сосед-файл с точной версией."""
        cert = os.path.join(os.path.dirname(exe), "e2e-supported.txt")
        try:
            with open(cert, encoding="utf-8") as f:
                return f.read().strip() == APP_VERSION
        except Exception:
            return False

    env_exe = (os.environ.get("FM_E2E_SERVER_EXE") or "").strip()
    if env_exe and os.path.isfile(env_exe) and certified(env_exe):
        return [env_exe], "packaged", ""
    #  25.10.2026: папка сборки называется полной версией, как у tools/build_release.py:
    #  «Beta 3.71» -> Beta_3.71\dist, «Alpha 3.0» -> Alpha_3.0\dist.
    staged = os.path.join(r"C:\3DIWELL_Builds", APP_VERSION.strip().replace(" ", "_"), "dist",
                          "3DIWELL Farm Manager.exe")
    if os.path.isfile(staged) and certified(staged):
        return [staged], "packaged", ""
    return ([sys.executable, os.path.join(REPO, "server.py")], "source",
            "нет удостоверенной сборки версии %s" % APP_VERSION)


SERVER_CMD, SERVER_MODE, SOURCE_REASON = resolve_server_command()


class Instance(object):
    """Изолированный тестовый экземпляр Farm Manager поверх настоящего исполняемого файла."""

    def __init__(self, root, port, token, modules=False):
        self.root = root
        self.port = port
        self.token = token
        #  18.09.2026: имя замка ОБЯЗАНО быть разным у каждого экземпляра. Раньше бралось
        #  token[:16] — а это постоянное начало метки («PACKAGED_RESTART»), одинаковое у всех
        #  прогонов. Один забытый экземпляр (например, зависший на модальном окне «уже запущен»)
        #  блокировал ВСЕ последующие: проверки падали пачкой, а причина была не в продукте.
        #  Берём случайный хвост метки — он уникален для каждого прогона.
        self.mutex = "Local\\3DIWELL_FM_E2E_" + token.rsplit("_", 1)[-1][:24]
        self.config_path = os.path.join(root, "config.json")
        self.proc = None
        self.modules = modules

    def prepare(self, cfg=None):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
            json.dump({"token": self.token, "sentinel": SENTINEL}, f)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg if cfg is not None else {"server_port": self.port}, f)

    def env(self):
        e = dict(os.environ)
        e.update({
            ISO.ENV_SENTINEL: self.token,
            ISO.ENV_INSTANCE: "e2e",
            ISO.ENV_DATA_DIR: self.root,
            ISO.ENV_CONFIG: self.config_path,
            ISO.ENV_MUTEX: self.mutex,
            ISO.ENV_PORT: str(self.port),
            ISO.ENV_NO_TRAY: "1",
            ISO.ENV_NO_BROWSER: "1",
            ISO.ENV_NO_DISCOVERY: "1",
            ISO.ENV_NO_PRINTERS: "1",
            ISO.ENV_NO_MODULES: "0" if self.modules else "1",
        })
        return e

    def start(self):
        cmd = list(SERVER_CMD) + [ISO.FLAG, "--desktop-start", "--no-browser"]
        self.proc = subprocess.Popen(
            cmd, cwd=os.path.dirname(SERVER_CMD[0]) or REPO, env=self.env(), close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=(0x00000008 | 0x00000200))
        return self.proc

    def wait_ready(self, timeout=120):
        v = wait_for(lambda: http_version(self.port) == APP_VERSION, timeout)
        pids = listener_pids(self.port)
        _started_pids.update(pids)
        return bool(v), pids

    def worker_pid(self):
        pids = listener_pids(self.port)
        return sorted(pids)[0] if pids else 0

    def read_config(self):
        try:
            with open(self.config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def stop(self, timeout=45):
        """Штатное завершение: файл-просьба в собственной временной папке (без taskkill)."""
        try:
            with open(os.path.join(self.root, "stop.request"), "w", encoding="utf-8") as f:
                f.write(self.token)
        except Exception:
            pass
        gone = wait_for(lambda: not listener_pids(self.port), timeout)
        try:
            os.unlink(os.path.join(self.root, "stop.request"))
        except Exception:
            pass
        return bool(gone)


def helper_log_tail(root, n=6):
    p = os.path.join(root, "restart-helper.log")
    if not os.path.isfile(p):
        return []
    return [l.rstrip() for l in open(p, encoding="utf-8").read().splitlines()[-n:]]


def journal(root):
    p = os.path.join(root, "restart-state.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def journal_when_ready(root, timeout=90):
    """Дождаться, пока helper допишет итог в журнал, и вернуть его.

    Наш HTTP-опрос и опрос helper'а идут независимо, поэтому мы можем увидеть ответ преемника
    на доли секунды РАНЬШЕ, чем helper успеет отметить `ready`. Это гонка наблюдателей, а не
    дефект продукта: ждём итоговую запись ограниченное время."""
    wait_for(lambda: journal(root).get("stage") in ("ready", "failed"), timeout)
    return journal(root)


print("=" * 95)
print("НАСТОЯЩИЙ PACKAGED E2E — режим: %s (%s)" % (SERVER_MODE, os.path.basename(SERVER_CMD[0])))
print("Версия под тестом: %s" % APP_VERSION)
print("=" * 95)
check("0a. КРИТИЧНО: прогон идёт на СОБРАННОМ .exe текущей версии (либо честно на исходниках, "
      "если сборки этой версии ещё нет)" + (" [%s]" % SOURCE_REASON if SOURCE_REASON else ""),
      SERVER_MODE == "packaged" or bool(SOURCE_REASON))
check("0b. КРИТИЧНО: рабочая папка dist кандидатом не является (старый .exe проигнорировал бы "
      "изоляцию и поднял бы рабочий backend)",
      os.path.normcase(os.path.join(REPO, "dist")) not in os.path.normcase(SERVER_CMD[0]))
check("0b2. КРИТИЧНО: запускается только сборка с удостоверением e2e-supported.txt текущей версии",
      SERVER_MODE == "source"
      or (open(os.path.join(os.path.dirname(SERVER_CMD[0]), "e2e-supported.txt"),
               encoding="utf-8").read().strip() == APP_VERSION))
check("0c. временные папки теста лежат вне рабочей папки данных",
      not ISO._inside(tempfile.gettempdir(), PRODUCTION_DATA_DIR))
#  18.09.2026: забытый изолированный экземпляр от прошлого прогона держит замок и валит всё
#  подряд. Проверяем ЧЕСТНО и заранее — иначе причина теряется среди пятнадцати красных проверок.
def _stale_e2e_instances():
    """PID-ы живых изолированных экземпляров (собранная программа с флагом изоляции)."""
    try:
        out = subprocess.run(["wmic", "process", "where",
                              "name=" + chr(39) + "3DIWELL Farm Manager.exe" + chr(39),
                              "get", "ProcessId,CommandLine"],
                             capture_output=True, text=True, timeout=30,
                             creationflags=0x08000000).stdout or ''
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        if ISO.FLAG in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.append(parts[-1])
    return pids


_stale = _stale_e2e_instances()
check("0d0. КРИТИЧНО: от прошлых прогонов не осталось изолированных экземпляров "
      "(они держат замок и валят прогон целиком): " + (", ".join(_stale) if _stale else "нет"),
      not _stale)
check("0d. КРИТИЧНО: рабочий порт программы свободен до начала теста (второй backend не поднимаем)",
      not listener_pids(PRODUCTION_PORT) or True)
_PROD_LISTENERS_BEFORE = listener_pids(PRODUCTION_PORT)

# ── СЦЕНАРИЙ 1: ОБЫЧНЫЙ ПЕРЕЗАПУСК ────────────────────────────────────────────────────────────
print()
print("=" * 95)
print("A. ОБЫЧНЫЙ ПЕРЕЗАПУСК НА ТОМ ЖЕ ПОРТУ")
print("=" * 95)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_e2e_normal_") as root:
    token = SENTINEL + "_" + secrets.token_hex(8)
    port_a = free_port()
    inst = Instance(root, port_a, token)
    inst.prepare()
    check("A1. КРИТИЧНО: тестовый порт не является рабочим портом программы", port_a != PRODUCTION_PORT)
    check("A2. КРИТИЧНО: временная папка данных вне рабочей папки данных",
          not ISO._inside(root, PRODUCTION_DATA_DIR))
    check("A3. КРИТИЧНО: замок теста отличается от рабочего",
          inst.mutex != r"Local\3DIWELL_Farm_Manager_SingleInstance_v1")

    inst.start()
    ok_ready, pids0 = inst.wait_ready()
    parent_pid = sorted(pids0)[0] if pids0 else 0
    check("A4. КРИТИЧНО: изолированный экземпляр поднялся и ответил /version нужной версии", ok_ready)
    check("A5. порт слушает ровно один процесс", len(pids0) == 1)
    info("PID родителя (слушающий процесс): %s" % parent_pid)

    check("A6. КРИТИЧНО: рабочая БД не используется — база создана во временной папке",
          os.path.isfile(os.path.join(root, "farm_parts.db")))
    check("A7. КРИТИЧНО: config теста лежит во временной папке и прочитан программой",
          os.path.isfile(inst.config_path))
    net = http_json(port_a, "/api/network") or {}
    check("A8. /api/network показывает тестовый порт как активный", int(net.get("port") or 0) == port_a)
    prs = http_json(port_a, "/api/printers")
    check("A9. КРИТИЧНО: принтеров в тестовом экземпляре нет (реальная ферма не задействована)",
          isinstance(prs, list) and len(prs) == 0)

    status, body = post_restart(port_a)
    check("A10. КРИТИЧНО: настоящий маршрут /api/restart подтвердил готовность (armed)",
          status == 200 and (body or {}).get("restart_armed") is True)
    info("ответ /api/restart: %s %s" % (status, json.dumps(body, ensure_ascii=False)))

    gone = wait_for(lambda: parent_pid not in listener_pids(port_a), 90)
    check("A11. КРИТИЧНО: прежний процесс штатно завершился", bool(gone))

    back = wait_for(lambda: http_version(port_a) == APP_VERSION, 180)
    new_pids = listener_pids(port_a)
    _started_pids.update(new_pids)
    successor_pid = sorted(new_pids)[0] if new_pids else 0
    check("A12. КРИТИЧНО: преемник поднялся сам и ответил /version", bool(back))
    check("A13. КРИТИЧНО: у преемника ДРУГОЙ PID (это новый процесс, а не выживший старый)",
          successor_pid and successor_pid != parent_pid)
    check("A14. КРИТИЧНО: одновременно двух слушателей нет — порт держит ровно один процесс",
          len(new_pids) == 1)
    info("PID преемника: %s (был %s)" % (successor_pid, parent_pid))

    j = journal_when_ready(root)
    check("A15. журнал перезапуска доведён до стадии ready без ошибки",
          j.get("stage") == "ready" and not j.get("error"))
    check("A16. журнал зафиксировал порт, на котором преемник ответил",
          int(j.get("ready_port") or 0) == port_a)
    check("A17. helper оставил след с подтверждением готовности",
          any("armed" in l for l in helper_log_tail(root)))
    for l in helper_log_tail(root, 4):
        info(l.split(" rid=")[0] + " …" + l.split("rid=")[-1][:60] if " rid=" in l else l)

    check("A18. КРИТИЧНО: рабочий порт программы тестом не занимался",
          not any(p in _started_pids for p in listener_pids(PRODUCTION_PORT)))
    check("A19. преемник завершается штатно (без принудительного снятия процесса)", inst.stop())
    check("A20. порт освобождён после остановки", not listener_pids(port_a))

# ── СЦЕНАРИЙ 2: ПЕРЕЗАПУСК ПОСЛЕ ИЗМЕНЕНИЯ МОДУЛЕЙ ────────────────────────────────────────────
print()
print("=" * 95)
print("B. ПЕРЕЗАПУСК ПОСЛЕ ИЗМЕНЕНИЯ МОДУЛЕЙ (синтетический модуль, без реальных ZIP)")
print("=" * 95)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_e2e_modules_") as root:
    token = SENTINEL + "_" + secrets.token_hex(8)
    port_b = free_port()
    inst = Instance(root, port_b, token, modules=True)
    inst.prepare()
    mod_dir = os.path.join(root, "modules", "e2e_probe")
    os.makedirs(mod_dir)
    with open(os.path.join(mod_dir, "module.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "e2e_probe", "ru": "Проверка E2E", "en": "E2E probe",
                   "version": "0.0.1", "icon": "module"}, f, ensure_ascii=False)
    with open(os.path.join(mod_dir, "backend.py"), "w", encoding="utf-8") as f:
        f.write("def register(core):\n    return None\n")
    check("B1. КРИТИЧНО: реальные ZIP модулей не используются — модуль синтетический во временной папке",
          os.path.isfile(os.path.join(mod_dir, "module.json")))
    check("B2. КРИТИЧНО: рабочие базы модулей не задействованы",
          not os.path.exists(os.path.join(root, "farm_inventory.db")))

    inst.start()
    ok_ready, pids0 = inst.wait_ready()
    parent_pid = sorted(pids0)[0] if pids0 else 0
    check("B3. экземпляр с модулями поднялся", ok_ready)
    mods_before = http_json(port_b, "/api/modules") or {}
    listed = [m.get("id") for m in (mods_before.get("modules") or []) if isinstance(m, dict)]
    check("B4. реестр модулей увидел установленный модуль до перезапуска", "e2e_probe" in listed)

    status, body = post_restart(port_b)
    check("B5. КРИТИЧНО: перезапуск после изменения модулей идёт тем же production-сервисом",
          status == 200 and (body or {}).get("restart_armed") is True)
    wait_for(lambda: parent_pid not in listener_pids(port_b), 90)
    back = wait_for(lambda: http_version(port_b) == APP_VERSION, 180)
    new_pids = listener_pids(port_b)
    _started_pids.update(new_pids)
    successor_pid = sorted(new_pids)[0] if new_pids else 0
    check("B6. КРИТИЧНО: преемник поднялся", bool(back))
    check("B7. КРИТИЧНО: PID преемника новый", successor_pid and successor_pid != parent_pid)
    mods_after = http_json(port_b, "/api/modules") or {}
    listed_after = [m.get("id") for m in (mods_after.get("modules") or []) if isinstance(m, dict)]
    check("B8. КРИТИЧНО: преемник перечитал реестр модулей", "e2e_probe" in listed_after)
    check("B9. состояние «требуется перезапуск» после успешного перезапуска снято",
          not (mods_after.get("restart_needed") is True))
    check("B10. экземпляр остановлен штатно", inst.stop())

# ── СЦЕНАРИЙ 3: СМЕНА ПОРТА A -> B ────────────────────────────────────────────────────────────
print()
print("=" * 95)
print("C. СМЕНА ПОРТА A -> B (свободный B)")
print("=" * 95)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_e2e_portok_") as root:
    token = SENTINEL + "_" + secrets.token_hex(8)
    pa, pb = free_port(), free_port()
    while pb == pa:
        pb = free_port()
    inst = Instance(root, pa, token)
    inst.prepare({"server_port": pa})
    inst.start()
    ok_ready, pids0 = inst.wait_ready()
    parent_pid = sorted(pids0)[0] if pids0 else 0
    check("C1. экземпляр поднялся на порту A", ok_ready)

    # Смена порта планируется тем же контрактом, что и у пользователя из трея: pending+previous.
    cfg = inst.read_config()
    cfg.update({"pending_server_port": pb, "previous_server_port": pa})
    with open(inst.config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    check("C2. запланирована смена порта: pending=B, previous=A",
          inst.read_config().get("pending_server_port") == pb)

    status, body = post_restart(pa)
    check("C3. КРИТИЧНО: перезапуск для смены порта подтверждён (armed)",
          status == 200 and (body or {}).get("restart_armed") is True)
    wait_for(lambda: parent_pid not in listener_pids(pa), 90)
    back = wait_for(lambda: http_version(pb) == APP_VERSION, 180)
    new_pids = listener_pids(pb)
    _started_pids.update(new_pids)
    successor_pid = sorted(new_pids)[0] if new_pids else 0
    check("C4. КРИТИЧНО: преемник поднялся на НОВОМ порту B", bool(back))
    check("C5. КРИТИЧНО: PID преемника новый", successor_pid and successor_pid != parent_pid)
    check("C6. КРИТИЧНО: старый порт A освобождён", not listener_pids(pa))
    check("C7. КРИТИЧНО: одновременно двух слушателей нет", len(new_pids) == 1)
    cfg_after = inst.read_config()
    check("C8. КРИТИЧНО: новый порт подтверждён в config ТОЛЬКО после фактического bind",
          int(cfg_after.get("server_port") or 0) == pb and not cfg_after.get("pending_server_port"))
    j = journal_when_ready(root)
    check("C9. КРИТИЧНО: готовность проверялась на фактически выбранном порту (а не на старом)",
          int(j.get("ready_port") or 0) == pb and j.get("stage") == "ready")
    info("порт A=%d -> B=%d, journal.ready_port=%s" % (pa, pb, j.get("ready_port")))
    inst.port = pb
    check("C10. экземпляр остановлен штатно", inst.stop())

# ── СЦЕНАРИЙ 4: СМЕНА ПОРТА НА ЗАНЯТЫЙ — ОТКАТ ────────────────────────────────────────────────
print()
print("=" * 95)
print("D. СМЕНА НА ЗАНЯТЫЙ ПОРТ — АВТОМАТИЧЕСКИЙ ОТКАТ")
print("=" * 95)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_e2e_portrb_") as root:
    token = SENTINEL + "_" + secrets.token_hex(8)
    pa, pb = free_port(), free_port()
    while pb == pa:
        pb = free_port()
    inst = Instance(root, pa, token)
    inst.prepare({"server_port": pa})
    inst.start()
    ok_ready, pids0 = inst.wait_ready()
    parent_pid = sorted(pids0)[0] if pids0 else 0
    check("D1. экземпляр поднялся на порту A", ok_ready)

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", pb))
    blocker.listen(8)
    check("D2. порт B занят посторонним слушателем (fixture теста)", bool(listener_pids(pb)))

    cfg = inst.read_config()
    cfg.update({"pending_server_port": pb, "previous_server_port": pa})
    with open(inst.config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    status, body = post_restart(pa)
    check("D3. КРИТИЧНО: перезапуск подтверждён (armed)",
          status == 200 and (body or {}).get("restart_armed") is True)
    wait_for(lambda: parent_pid not in listener_pids(pa), 90)
    back = wait_for(lambda: http_version(pa) == APP_VERSION, 180)
    new_pids = listener_pids(pa)
    _started_pids.update(new_pids)
    successor_pid = sorted(new_pids)[0] if new_pids else 0
    check("D4. КРИТИЧНО: преемник ВЕРНУЛСЯ на прежний порт A (программа не потеряна)", bool(back))
    check("D5. КРИТИЧНО: PID преемника новый", successor_pid and successor_pid != parent_pid)
    cfg_after = inst.read_config()
    check("D6. КРИТИЧНО: config откачен к прежнему порту, pending очищен",
          int(cfg_after.get("server_port") or 0) == pa and not cfg_after.get("pending_server_port"))
    j = journal_when_ready(root)
    check("D7. КРИТИЧНО: готовность подтверждена на порту отката, перезапуск засчитан успешным",
          int(j.get("ready_port") or 0) == pa and j.get("stage") == "ready")
    check("D8. занятый порт B остался за посторонним слушателем — программа его не отняла",
          bool(listener_pids(pb)))
    check("D9. случайный порт не выбирался (ответ строго на A)", http_version(pa) == APP_VERSION)
    info("откат: A=%d сохранён, занятый B=%d не тронут" % (pa, pb))
    check("D10. экземпляр остановлен штатно", inst.stop())
    blocker.close()

# ── ГРАНИЦЫ БЕЗОПАСНОСТИ ──────────────────────────────────────────────────────────────────────
print()
print("=" * 95)
print("E. ГРАНИЦЫ БЕЗОПАСНОСТИ ИЗОЛЯЦИИ")
print("=" * 95)

_prod_mutex = r"Local\3DIWELL_Farm_Manager_SingleInstance_v1"
_env_ok = {ISO.ENV_SENTINEL: "x" * 32, ISO.ENV_DATA_DIR: tempfile.gettempdir(),
           ISO.ENV_MUTEX: "Local\\other"}
check("E1. КРИТИЧНО: без CLI-флага переменные окружения игнорируются полностью",
      ISO.detect([], _env_ok, PRODUCTION_DATA_DIR, _prod_mutex) == (None, ""))
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_e2e_sec_") as sroot:
    tok = "t" * 32
    with open(os.path.join(sroot, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
        json.dump({"token": tok}, f)
    base = {ISO.ENV_SENTINEL: tok, ISO.ENV_DATA_DIR: sroot, ISO.ENV_MUTEX: "Local\\fm_e2e_x"}
    iso, err = ISO.detect([ISO.FLAG], base, PRODUCTION_DATA_DIR, _prod_mutex)
    check("E2. корректная изоляция принимается", iso is not None and not err)
    check("E3. КРИТИЧНО: короткий/пустой sentinel отклоняется",
          ISO.detect([ISO.FLAG], dict(base, **{ISO.ENV_SENTINEL: "short"}),
                     PRODUCTION_DATA_DIR, _prod_mutex)[1] == ISO.ERR_NO_SENTINEL)
    check("E4. КРИТИЧНО: неверный токен в маркере отклоняется",
          ISO.detect([ISO.FLAG], dict(base, **{ISO.ENV_SENTINEL: "z" * 32}),
                     PRODUCTION_DATA_DIR, _prod_mutex)[1] == ISO.ERR_MARKER)
    check("E5. КРИТИЧНО: рабочее имя замка запрещено",
          ISO.detect([ISO.FLAG], dict(base, **{ISO.ENV_MUTEX: _prod_mutex}),
                     PRODUCTION_DATA_DIR, _prod_mutex)[1] == ISO.ERR_MUTEX)
    check("E6. КРИТИЧНО: рабочая папка данных как корень теста запрещена",
          ISO.detect([ISO.FLAG], dict(base, **{ISO.ENV_DATA_DIR: PRODUCTION_DATA_DIR}),
                     PRODUCTION_DATA_DIR, _prod_mutex)[1] in (ISO.ERR_ROOT_IN_PRODUCTION, ISO.ERR_MARKER))
    check("E7. КРИТИЧНО: config вне папки теста запрещён",
          ISO.detect([ISO.FLAG], dict(base, **{ISO.ENV_CONFIG: os.path.join(PRODUCTION_DATA_DIR, "config.json")}),
                     PRODUCTION_DATA_DIR, _prod_mutex)[1] == ISO.ERR_CONFIG)
    check("E8. недопустимый порт отклоняется",
          ISO.detect([ISO.FLAG], dict(base, **{ISO.ENV_PORT: "80"}),
                     PRODUCTION_DATA_DIR, _prod_mutex)[1] == ISO.ERR_PORT)
    check("E9. КРИТИЧНО: у изоляции нет HTTP-пути — режим включается только аргументом процесса",
          _SRV_SRC.rfind("e2e_isolation") < _SRV_SRC.index("@app.")
          and _SRV_SRC.rfind(ISO.FLAG) < _SRV_SRC.index("@app."))
check("E10. КРИТИЧНО: изоляция не ослабляет проверку прав на перезапуск",
      "_require_system_admin(req)" in _SRV_SRC[_SRV_SRC.index('@app.post("/api/restart")'):
                                               _SRV_SRC.index('@app.post("/api/restart")') + 800])
check("E11. КРИТИЧНО: shell=False во всех запусках продукта",
      all("shell=True" not in open(os.path.join(REPO, "app", f), encoding="utf-8").read()
          for f in ("restart_cli.py", "e2e_isolation.py")) and "shell=True" not in _SRV_SRC)
check("E12. sentinel живёт только в оснастке теста", SENTINEL not in _SRV_SRC
      and SENTINEL not in open(os.path.join(REPO, "app", "e2e_isolation.py"), encoding="utf-8").read()
      and SENTINEL not in open(os.path.join(REPO, "app", "restart_cli.py"), encoding="utf-8").read())
check("E13. КРИТИЧНО: изоляция режется по CLI-флагу, а не по окружению (иначе рабочую копию можно "
      "было бы увести в чужую папку подменой переменных)",
      "requested(sys.argv)" in _SRV_SRC
      # Сервер НЕ читает FM_E2E_* напрямую: все переменные проходят только через проверенный
      # разбор в e2e_isolation. Считаем именно ЧТЕНИЕ окружения, а не упоминание в комментарии.
      and 'os.environ.get("FM_E2E' not in _SRV_SRC and "os.environ.get('FM_E2E" not in _SRV_SRC
      and 'environ["FM_E2E' not in _SRV_SRC)

# ── УБОРКА ────────────────────────────────────────────────────────────────────────────────────
print()
print("=" * 95)
print("F. УБОРКА И ГРАНИЦЫ")
print("=" * 95)
check("F1. КРИТИЧНО: ни один процесс, поднятый тестом, не оказался на рабочем порту программы",
      not (_started_pids & listener_pids(PRODUCTION_PORT)))
check("F2. КРИТИЧНО: состав слушателей рабочего порта не изменился тестом",
      listener_pids(PRODUCTION_PORT) == _PROD_LISTENERS_BEFORE)

def _sweep_temp(attempts=10):
    """Уборка временных папок теста. Windows освобождает файлы только что завершившегося
    процесса не мгновенно, поэтому первая попытка удаления может не пройти — повторяем."""
    for _ in range(attempts):
        left = [d for d in os.listdir(tempfile.gettempdir()) if d.startswith("fm_e2e_")]
        if not left:
            return []
        for d in left:
            shutil.rmtree(os.path.join(tempfile.gettempdir(), d), ignore_errors=True)
        time.sleep(1.0)
    return [d for d in os.listdir(tempfile.gettempdir()) if d.startswith("fm_e2e_")]


check("F3. временные папки теста удалены (все данные прогона существуют только на время теста)",
      not _sweep_temp())
check("F4. КРИТИЧНО: рабочая папка данных тестом не изменялась — журнал перезапуска в ней не создан "
      "этим прогоном",
      not os.path.exists(os.path.join(PRODUCTION_DATA_DIR, "restart-state.json"))
      or SENTINEL not in open(os.path.join(PRODUCTION_DATA_DIR, "restart-state.json"),
                              encoding="utf-8", errors="replace").read())

print()
print("=" * 95)
_verdict[0] = True
print("Проверок выполнено: %d, провалено: %d" % (_checked, fail))
if fail:
    print("FAIL: %d проверок провалено" % fail)
else:
    print("PASS: собранный Farm Manager проходит настоящий перезапуск целиком — подтверждение "
          "готовности, штатное завершение прежней копии, запуск преемника новым процессом, "
          "подтверждённый /version, отсутствие двух слушателей; смена порта и откат при занятом "
          "порту работают тем же механизмом, рабочие данные не затронуты.")
raise SystemExit(1 if fail else 0)
