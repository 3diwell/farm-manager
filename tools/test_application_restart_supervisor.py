# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Надёжный перезапуск Farm Manager — core Alpha 2.809.
=================================================================================================
ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ.

Пользователь установил модули и нажал кнопку перезапуска. Прежний процесс завершился, новый не
запустился, интерфейс не вернулся — программу пришлось запускать вручную. Журнал фермы показывает
ровно это: последняя строка старого процесса в 15:19:07, затем 34 секунды тишины, затем запись
уже запущенного вручную процесса в 15:19:41. Ни строки об ошибке, ни следа преемника.

ПРИЧИНА НЕ В ОДНОЙ СТРОКЕ, А В СХЕМЕ. Прежний `_restart_self` создавал процесс «вслепую» и
НЕМЕДЛЕННО завершал себя (`os._exit(0)`), считая сам вызов Popen доказательством успеха. При этом
каждый путь раннего выхода преемника молчал: он ждёт освобождения замка одиночного экземпляра и
порта с ограниченным таймаутом, а об отказе сообщает через print() — которого у собранного
GUI-приложения не видно (backend запускается оболочкой как DETACHED-процесс). Сбой преемника был
одновременно невидимым и невосстановимым: старого сервера уже не существовало.

ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ. Чистый движок app/restart_supervisor.py проверяется напрямую с полностью
поддельными пробами (процессы, порты, замок, HTTP, часы), поэтому весь сценарий перезапуска
воспроизводится мгновенно и без единого настоящего процесса. Проводка server.py и фронтенда
сверяется по фактическому тексту исходников.

ПОЛНОСТЬЮ OFFLINE: временная папка, поддельные процессы и порты, поддельные часы; рабочая БД и
DATA_DIR не используются, настоящий Farm Manager не завершается, сеть и принтеры не участвуют.

Запуск: PYTHONIOENCODING=utf-8 python tools/test_application_restart_supervisor.py   (0 = пройдено)
"""
import atexit
import json
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "APPLICATION_RESTART_SUPERVISOR_SENTINEL_2_809"

# ── Ловушки-шпионы ─────────────────────────────────────────────────────────────────────────────
import socket as _socket_mod
import subprocess as _subprocess_mod

_VIOLATIONS = []


class _NoSocket(object):
    def __init__(self, *a, **k):
        _VIOLATIONS.append("socket")
        raise RuntimeError("сеть в offline-тесте запрещена")


_socket_mod.socket = _NoSocket
_socket_mod.create_connection = lambda *a, **k: _NoSocket()


def _no_subprocess(*a, **k):
    _VIOLATIONS.append("subprocess")
    raise RuntimeError("запуск процессов в offline-тесте запрещён")


_subprocess_mod.Popen = _no_subprocess
_subprocess_mod.run = _no_subprocess

_TMP = tempfile.TemporaryDirectory(prefix="fm_restart_2809_")
TMP_ROOT = os.path.realpath(_TMP.name)

from app import restart_supervisor as R

_SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_APP = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
_HTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()

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


# ── Поддельный мир ─────────────────────────────────────────────────────────────────────────────
class World(object):
    """Поддельные процессы, порт, замок и HTTP. Часы виртуальные: ожидания не занимают времени."""

    def __init__(self, parent_alive=True, lock_held=True, port_busy=True,
                 parent_exit_at=1.0, lock_free_at=1.5, port_free_at=2.0,
                 successor_version="Alpha 2.809", ready_at=3.0, spawn_ok=True,
                 successor_dies=False, foreign_version=None, answer_port=None):
        self.t = 0.0
        self.parent_alive = parent_alive
        self.lock_held = lock_held
        self.port_busy = port_busy
        self.parent_exit_at = parent_exit_at
        self.lock_free_at = lock_free_at
        self.port_free_at = port_free_at
        self.successor_version = successor_version
        self.foreign_version = foreign_version
        self.answer_port = answer_port
        self.ready_at = ready_at
        self.spawn_ok = spawn_ok
        self.successor_dies = successor_dies
        self.spawns = []          # список запущенных команд
        self.launched_at = None

    # -- часы
    def now(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)

    # -- пробы
    def pid_alive(self, pid):
        return self.parent_alive and self.t < self.parent_exit_at

    def lock_free(self):
        return not (self.lock_held and self.t < self.lock_free_at)

    def port_in_use(self, port):
        return self.port_busy and self.t < self.port_free_at

    def http_version(self, port):
        if self.launched_at is None:
            return None
        if self.t < self.launched_at + self.ready_at:
            return None
        # Alpha 2.811: преемник отвечает на КОНКРЕТНОМ порту. Если задан answer_port, на всех
        # остальных портах ответа нет — так проверяется смена порта и откат.
        if self.answer_port is not None and int(port) != int(self.answer_port):
            return None
        if self.foreign_version is not None:
            return self.foreign_version
        return self.successor_version

    def spawn(self, command, workdir):
        self.spawns.append((list(command), workdir))
        if not self.spawn_ok:
            return None
        self.launched_at = self.t
        return {"h": len(self.spawns)}

    def process_alive(self, handle):
        if handle is None:
            return False
        if self.successor_dies and self.launched_at is not None and self.t > self.launched_at + 1.0:
            return False
        return True

    def probes(self):
        return R.Probes(pid_alive=self.pid_alive, port_in_use=self.port_in_use,
                        lock_free=self.lock_free, http_version=self.http_version,
                        spawn=self.spawn, now=self.now, sleep=self.sleep,
                        process_alive=self.process_alive)


EXE = os.path.join(TMP_ROOT, "3DIWELL Farm Manager.exe")
DESKTOP_EXE = os.path.join(TMP_ROOT, "3DIWELL Farm Manager Desktop.exe")
CLIENT_EXE = os.path.join(TMP_ROOT, "3DIWELL Farm Manager Client.exe")
SCRIPT = os.path.join(TMP_ROOT, "server.py")
for _p in (EXE, DESKTOP_EXE, CLIENT_EXE, SCRIPT):
    with open(_p, "w", encoding="utf-8") as f:
        f.write("# " + SENTINEL + "\n")
JOURNAL = os.path.join(TMP_ROOT, "restart-state.json")


def plan(frozen=True, executable=EXE, script=SCRIPT, argv=("--desktop-start", "--no-browser"),
         workdir=TMP_ROOT, port=8000, version="Alpha 2.809", pid=4242):
    return R.build_plan(frozen, executable, script, list(argv), workdir, port, version, pid,
                        "rid-1", JOURNAL)


print("=" * 95)
print("A. ИСТОРИЧЕСКАЯ РЕГРЕССИЯ: прежняя схема убивала сервер без гарантии преемника")
print("=" * 95)

_old = _SRV[_SRV.index("\ndef _restart_self("):]
_old = _old[:_old.index("\n# ═")] if "\n# ═" in _old else _old[:4000]
check("A1. прежний путь сохранён в исходнике как аварийный (для сравнения контрактов)",
      "def _restart_self(" in _SRV)
check("A2. КРИТИЧНО: прежняя схема действительно завершала процесс сразу после Popen",
      "subprocess.Popen(args" in _old and "os._exit(0)" in _old)
check("A3. КРИТИЧНО: ни одно место программы больше НЕ вызывает прежний путь",
      len(re.findall(r"(?<!def )_restart_self\(\)", _SRV)) == 0
      and "target=_restart_self" not in _SRV)
check("A4. КРИТИЧНО: перезапуск после модулей и перезапуск при смене порта — ОДИН механизм",
      _SRV.count("perform_restart_async()") >= 2
      and "def perform_restart_async(" in _SRV)
check("A5. root cause закрыт assertion'ом: сервер завершается ТОЛЬКО после подтверждения",
      "ok, why = request_restart()" in _SRV
      and _SRV.index("ok, why = request_restart()") < _SRV.index("def _bye():"))

print()
print("=" * 95)
print("B. ПЛАН ПЕРЕЗАПУСКА")
print("=" * 95)

p = plan(frozen=True)
check("B1. собранная программа: преемник — тот же серверный .exe",
      p["mode"] == R.MODE_PACKAGED and p["command"][0] == EXE)
check("B2. КРИТИЧНО: оболочка Desktop не считается серверным файлом",
      not R.is_server_executable(DESKTOP_EXE))
check("B3. КРИТИЧНО: клиент не считается серверным файлом",
      not R.is_server_executable(CLIENT_EXE))
check("B4. серверный .exe признаётся допустимым", R.is_server_executable(EXE))
ps = plan(frozen=False)
check("B5. запуск из исходников: интерпретатор + абсолютный путь server.py",
      ps["mode"] == R.MODE_SOURCE and ps["command"][0] == EXE and ps["command"][1] == SCRIPT)
check("B6. пути абсолютные", os.path.isabs(p["executable"]) and os.path.isabs(p["workdir"]))
check("B7. рабочая папка сохранена", p["workdir"] == os.path.abspath(TMP_ROOT))
check("B8. команда — СПИСОК строк (никакой конкатенации)",
      isinstance(p["command"], list) and all(isinstance(x, str) for x in p["command"]))
check("B9. КРИТИЧНО: одноразовые и служебные аргументы не переносятся",
      R.filter_args(["--desktop-start", "--allow-print-once", "--arm-transport",
                     "--fm-restart-supervisor", "x.json", "--no-browser"])
      == ["--desktop-start", "x.json", "--no-browser"])
check("B10. обычные аргументы сохраняются",
      "--desktop-start" in p["command"] and "--no-browser" in p["command"])
check("B11. в плане нет секретов и окружения",
      not any(k in p for k in ("env", "environment", "token", "password", "cookie")))

print()
print("=" * 95)
print("C. ПРОВЕРКА ВЫПОЛНИМОСТИ (preflight) — до остановки сервера")
print("=" * 95)

ok, why = R.preflight(plan())
check("C1. корректный план проходит проверку", ok and why == "")
ok, why = R.preflight(plan(executable=os.path.join(TMP_ROOT, "нет-такого.exe")))
check("C2. КРИТИЧНО: отсутствующий исполняемый файл отклоняется", not ok and why == R.ERR_NO_EXECUTABLE)
ok, why = R.preflight(plan(frozen=True, executable=DESKTOP_EXE))
check("C3. КРИТИЧНО: Desktop.exe как backend отклоняется", not ok and why == R.ERR_WRONG_EXECUTABLE)
ok, why = R.preflight(plan(frozen=True, executable=CLIENT_EXE))
check("C4. КРИТИЧНО: Client.exe как backend отклоняется", not ok and why == R.ERR_WRONG_EXECUTABLE)
ok, why = R.preflight(plan(frozen=False, script=os.path.join(TMP_ROOT, "нет.py")))
check("C5. отсутствующий server.py отклоняется", not ok and why == R.ERR_NO_ENTRY)
ok, why = R.preflight(plan(workdir=os.path.join(TMP_ROOT, "нет-папки")))
check("C6. отсутствующая рабочая папка отклоняется", not ok and why == R.ERR_NO_WORKDIR)
ok, why = R.preflight(plan(version=""))
check("C7. без ожидаемой версии план отклоняется", not ok and why == R.ERR_BAD_COMMAND)
for bad_port in (0, -1, 70000):
    ok, why = R.preflight(plan(port=bad_port))
    if ok:
        check("C8. КРИТИЧНО: недопустимый порт (%s) отклоняется" % bad_port, False)
        break
else:
    check("C8. КРИТИЧНО: недопустимый порт отклоняется", True)
_meta = plan()
_meta["command"] = [EXE, "--x & calc.exe"]
ok, why = R.preflight(_meta)
check("C9. КРИТИЧНО: команда с символами интерпретации оболочкой отклоняется",
      not ok and why == R.ERR_BAD_COMMAND)
_empty = plan(); _empty["command"] = []
check("C10. пустая команда отклоняется", not R.preflight(_empty)[0])

print()
print("=" * 95)
print("D. РАБОТА SUPERVISOR")
print("=" * 95)

w = World()
p = plan()
ok, why = R.run_supervisor(p, w.probes(), journal_path=JOURNAL)
check("D1. КРИТИЧНО: обычный сценарий — перезапуск подтверждён готовностью", ok and why == "")
check("D2. КРИТИЧНО: преемник запущен РОВНО один раз", len(w.spawns) == 1)
check("D3. запущена именно запланированная команда", w.spawns[0][0] == p["command"])
check("D4. КРИТИЧНО: преемник стартовал ПОСЛЕ ухода прежнего процесса",
      w.launched_at >= w.parent_exit_at)
check("D5. КРИТИЧНО: преемник стартовал ПОСЛЕ освобождения замка", w.launched_at >= w.lock_free_at)
check("D6. КРИТИЧНО: преемник стартовал ПОСЛЕ освобождения порта", w.launched_at >= w.port_free_at)
check("D7. журнал доведён до стадии ready", R.read_journal(JOURNAL)["stage"] == R.STAGE_READY)

w = World(parent_exit_at=10 ** 6)
ok, why = R.run_supervisor(plan(), w.probes(), journal_path=JOURNAL)
check("D8. КРИТИЧНО: прежний процесс не ушёл -> преемник НЕ запускается",
      not ok and why == R.ERR_PARENT_ALIVE and not w.spawns)

w = World(lock_free_at=10 ** 6)
ok, why = R.run_supervisor(plan(), w.probes(), journal_path=JOURNAL)
check("D9. КРИТИЧНО: замок занят -> преемник НЕ запускается (второго backend не будет)",
      not ok and why == R.ERR_LOCK_BUSY and not w.spawns)

w = World(port_free_at=10 ** 6)
ok, why = R.run_supervisor(plan(), w.probes(), journal_path=JOURNAL)
check("D10. КРИТИЧНО: порт занят -> преемник НЕ запускается",
      not ok and why == R.ERR_PORT_BUSY and not w.spawns)

w = World(foreign_version="Some Other Server 1.0")
ok, why = R.run_supervisor(plan(), w.probes(), journal_path=JOURNAL)
check("D11. КРИТИЧНО: чужой сервер на нашем порту успехом НЕ считается",
      not ok and why == R.ERR_FOREIGN_SERVER)

w = World(successor_version="Alpha 2.808")
ok, why = R.run_supervisor(plan(version="Alpha 2.809"), w.probes(), journal_path=JOURNAL)
check("D12. КРИТИЧНО: неверная версия успехом НЕ считается", not ok)

w = World(spawn_ok=False)
ok, why = R.run_supervisor(plan(), w.probes(), journal_path=JOURNAL)
check("D13. ошибка создания процесса возвращается безопасным кодом",
      not ok and why == R.ERR_SPAWN_FAILED)
check("D14. при отказе запуска сделан ровно один повтор (и не больше)", len(w.spawns) == 2)

w = World(successor_dies=True)
ok, why = R.run_supervisor(plan(), w.probes(), journal_path=JOURNAL)
check("D15. КРИТИЧНО: преемник, умерший сразу после старта, успехом не считается",
      not ok and why == R.ERR_SUCCESSOR_EXITED)
check("D16. КРИТИЧНО: бесконечного цикла повторов нет — не более двух попыток",
      len(w.spawns) <= 2 and R.MAX_LAUNCH_ATTEMPTS == 2)

w = World(ready_at=10 ** 6)
ok, why = R.run_supervisor(plan(), w.probes(), journal_path=JOURNAL)
check("D17. неготовность в пределах таймаута завершается отказом, а не зависанием "
      "(2.811: отдельный код readiness_timeout — преемник жив, но не ответил)",
      not ok and why == R.ERR_READINESS_TIMEOUT)

# ── Alpha 2.811: два РАЗНЫХ смысла порта. Прежде supervisor и ждал освобождения, и проверял
#    готовность на ОДНОМ порту — поэтому удачная смена порта всегда считалась провалом.
def port_plan(wait_port, ready_ports):
    return R.build_plan(True, EXE, SCRIPT, ["--desktop-start"], TMP_ROOT, ready_ports[0],
                        "Alpha 2.809", 4242, "rid-port", JOURNAL,
                        wait_port=wait_port, ready_ports=ready_ports)


w = World(answer_port=8123)
ok, why = R.run_supervisor(port_plan(8000, [8123, 8000]), w.probes(), journal_path=JOURNAL)
check("D18. КРИТИЧНО (2.811): смена порта — ждём освобождения СТАРОГО порта, а готовность "
      "принимаем на НОВОМ", ok and why == "")
check("D19. КРИТИЧНО: журнал зафиксировал порт фактического ответа преемника",
      int((R.read_journal(JOURNAL) or {}).get("ready_port") or 0) == 8123)

w = World(answer_port=8000)
ok, why = R.run_supervisor(port_plan(8000, [8123, 8000]), w.probes(), journal_path=JOURNAL)
check("D20. КРИТИЧНО: честный откат преемника на прежний порт — тоже успех перезапуска",
      ok and int((R.read_journal(JOURNAL) or {}).get("ready_port") or 0) == 8000)

w = World(answer_port=9999)
ok, why = R.run_supervisor(port_plan(8000, [8123, 8000]), w.probes(), journal_path=JOURNAL)
check("D21. КРИТИЧНО: ответ на постороннем порту успехом не считается",
      not ok and why == R.ERR_READINESS_TIMEOUT)

print()
print("=" * 95)
print("E. ЖУРНАЛ ПЕРЕЗАПУСКА")
print("=" * 95)

p = plan()
p["requested_at"] = 1000.0
p["updated_at"] = 1000.0
R.write_journal(JOURNAL, p)
check("E1. журнал читается обратно", (R.read_journal(JOURNAL) or {}).get("restart_id") == "rid-1")
check("E2. запись атомарна (временные файлы не остаются)",
      not [f for f in os.listdir(TMP_ROOT) if f.startswith(".restart-")])
_pub = R.journal_public(R.read_journal(JOURNAL))
_pubs = json.dumps(_pub, ensure_ascii=False)
check("E3. КРИТИЧНО: наружу не уходят пути, команда и окружение",
      "command" not in _pub and "executable" not in _pub and "workdir" not in _pub
      and TMP_ROOT not in _pubs)
check("E4. КРИТИЧНО: наружу не уходят секреты",
      not re.search(r"token|password|cookie|secret", _pubs, re.I))
check("E5. в публичном срезе есть стадия и безопасная причина",
      "stage" in _pub and "error" in _pub)
with open(JOURNAL, "w", encoding="utf-8") as f:
    f.write("{ это не json")
check("E6. битый журнал не роняет чтение", R.read_journal(JOURNAL) is None)
R.write_journal(JOURNAL, dict(p, updated_at=1000.0))
check("E7. КРИТИЧНО: устаревший журнал распознаётся и сам ничего не запускает",
      R.is_stale_journal(R.read_journal(JOURNAL), now=1000.0 + 4000.0))
check("E8. свежий журнал устаревшим не считается",
      not R.is_stale_journal(R.read_journal(JOURNAL), now=1000.0 + 10.0))
check("E9. журнал ограничен по составу полей", len(R.journal_public(R.read_journal(JOURNAL))) <= 14)

print()
print("=" * 95)
print("F. ПРОВОДКА В СЕРВЕРЕ")
print("=" * 95)

_CLI = open(os.path.join(REPO, "app", "restart_cli.py"), encoding="utf-8").read()
check("F1. КРИТИЧНО (2.810): режим supervisor — САМАЯ РАННЯЯ ветка, до замка одиночного экземпляра",
      _SRV.index("'--fm-restart-supervisor' in sys.argv")
      < _SRV.index("_SINGLE_INSTANCE = _single_instance.acquire"))
check("F1b. КРИТИЧНО (2.810): ветка supervisor стоит ДО тяжёлых импортов (root cause: helper "
      "умирал на module-level коде до неё)",
      _SRV.index("'--fm-restart-supervisor' in sys.argv") < _SRV.index("import paho.mqtt.client"))
check("F2. КРИТИЧНО: supervisor НЕ берёт замок одиночного экземпляра (только OpenMutexW)",
      "OpenMutexW" in _CLI and ".acquire(" not in _CLI)
check("F3. supervisor завершает процесс и сервером не становится",
      "sys.exit(_restart_cli.main(sys.argv))" in _SRV)
check("F4. КРИТИЧНО: запуск преемника без оболочки (shell=False по умолчанию, список аргументов)",
      "shell=True" not in _SRV and "shell=True" not in _CLI)
check("F5. преемник запускается самостоятельным процессом (DETACHED + новая группа) и с DEVNULL "
      "вместо отсутствующих std-handles (root cause 2.810)",
      "0x00000008 | 0x00000200" in _CLI
      and _CLI.count("stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL") >= 1)
_restart_route = _SRV[_SRV.index('@app.post("/api/restart")'):]
_restart_route = _restart_route[:_restart_route.index("\n@app.")]
check("F6. КРИТИЧНО: маршрут перезапуска закрыт системным админом",
      "_require_system_admin(req)" in _restart_route)
check("F6b. КРИТИЧНО: права проверяются ДО подготовки перезапуска",
      _restart_route.index("_require_system_admin") < _restart_route.index("perform_restart_async"))
check("F7. КРИТИЧНО: отказ подготовки НЕ останавливает сервер (ответ 409, процесс жив)",
      '"restart_armed": False' in _SRV and "status_code=409" in _SRV)
check("F8. успех сообщает restart_armed", '"restart_armed": True' in _SRV)
check("F9. КРИТИЧНО: одновременно выполняется только один перезапуск",
      "_restart_lock.acquire(blocking=False)" in _SRV and '"restart_in_progress"' in _SRV)
check("F10. журнал перезапуска лежит вне репозитория (в папке данных)",
      'os.path.join(DATA_DIR, "restart-state.json")' in _SRV)
_req = _SRV[_SRV.index("def request_restart("):]
_req = _req[:_req.index("\ndef ")]
check("F10b. КРИТИЧНО: выполнимость проверяется ВНУТРИ запроса перезапуска",
      "_restart_sup.preflight(plan)" in _req)
check("F10c. КРИТИЧНО: непройденная проверка ПРЕРЫВАЕТ перезапуск (сервер остаётся жив)",
      re.search(r"ok, why = _restart_sup\.preflight\(plan\)\s*\n\s*if not ok:(?:.|\n){0,220}?return False, why", _req) is not None)
check("F10d. КРИТИЧНО: supervisor запускается ТОЛЬКО после успешной проверки",
      _req.index("_restart_sup.preflight(plan)") < _req.index("supervisor_command("))
check("F11. смена порта использует тот же механизм",
      "def _restart_for_port(" in _SRV
      and "perform_restart_async()" in _SRV[_SRV.index("def _restart_for_port("):
                                            _SRV.index("def _restart_for_port(") + 900])
check("F12. новых HTTP-маршрутов сверх учтённых не добавлено (@app.* = 197)",
      len(re.findall(r'@app\.(get|post|patch|delete|websocket)\(', _SRV)) == 209)   # Alpha 2.823: +5 printer-files; 2.825: +select-for-print; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.927: +3 пометки принтера и настройки фермы; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера

print()
print("=" * 95)
print("G. ИНТЕРФЕЙС")
print("=" * 95)

check("G1. КРИТИЧНО: интерфейс ждёт подтверждения restart_armed",
      "j.restart_armed === true" in _APP)
check("G2. КРИТИЧНО: без подтверждения экран перезапуска НЕ показывается",
      "restartPhase.value = 'failed'" in _APP
      and _APP.index("if (!armed)") < _APP.index("await restartWaitReady();"))
check("G3. КРИТИЧНО: пути запросов абсолютные (прежние обратные слеши были управляющими символами)",
      "fetch('/api/restart'" in _APP and "fetch('/version'" in _APP
      and "'\\api\\restart'" not in _APP)
check("G4. опрос готовности ограничен по числу попыток",
      re.search(r"for \(let i = 0; i < \d+; i\+\+\)", _APP) is not None)
# Alpha 2.829: restartProbe возвращает { alive, bootId } — успех по-прежнему только при
# реально ответившем /version с версией; НОВЫЙ процесс определяется по смене boot_id
# (root cause 2.829: ранний bind сокета делал down-окно невидимым для опроса).
check("G5. успех — только реально ответивший /version с версией (+boot_id 2.829)",
      "alive: !!(j && j.version)" in _APP and "probe.bootId !== oldBoot" in _APP)
check("G6. по таймауту — НЕблокирующий экран с инструкцией (2.829: повтор/обновление/трей)",
      "restartPhase.value = 'timeout'" in _APP
      and "Не удалось автоматически подключиться после перезапуска" in _APP
      and "через значок в трее" in _APP)
check("G7. есть кнопка повторного подключения", "retryRestartConnection" in _APP and "retryRestartConnection()" in _HTML)
check("G8. КРИТИЧНО: повторный клик не создаёт второй перезапуск",
      "if (restartInProgress.value) return;" in _APP)
check("G9. экран ожидания переживает отключение сервера (оверлей уже загруженной страницы)",
      "restartPhase==='waiting'" in _HTML and "teleport" in _HTML)
check("G10. предупреждение про печати показано пользователю",
      "текущие печати на принтерах продолжатся" in _HTML)
_reasons_block = _APP[_APP.index("const RESTART_REASONS"):_APP.index("const restartReasonText")]
check("G11. причина отказа показывается человеческим текстом, без путей, команд и traceback",
      "restartReasonText" in _APP
      and not re.search(r"[A-Za-z]:\\\\|Traceback|\.exe|sys\.argv", _reasons_block))
check("G12. новые состояния экспортированы в шаблон (2.810: + restartReasonCode)",
      "restartPhase, restartMessage, restartReasonCode, retryRestartConnection, dismissRestartState," in _APP)

print()
print("=" * 95)
print("H. РЕГРЕССИИ И ГРАНИЦЫ")
print("=" * 95)

check("H1. Alpha 2.807: единая модель наблюдения печати на месте",
      "observe_printer_job(" in _SRV and os.path.isfile(os.path.join(REPO, "app", "printer_job_lifecycle.py")))
check("H2. КРИТИЧНО (2.809): номер наблюдения прежнего процесса сбрасывается при восстановлении",
      "UPDATE printer_job_sessions SET sequence=0" in _SRV)
check("H3. КРИТИЧНО: частые события журналируются с прореживанием (журнал не вытесняет сам себя)",
      "_PJL_NOISY_EVENTS" in _SRV and "stale_observation_ignored" in _SRV)
check("H4. Alpha 2.808: управление модулями на месте",
      "_failed_modules" in _SRV and "MODULE_STATE_VERSION_MISMATCH" in _SRV)
check("H5. Alpha 2.808: карточка «Модули» не гейтится редакцией",
      not re.search(r"_editionRemoved = \{[^}]*'modules'", _APP))
check("H6. схема БД не менялась",
      "CREATE TABLE IF NOT EXISTS printer_job_sessions" in _SRV
      and "ALTER TABLE printer_job_sessions" not in _SRV
      and "DROP TABLE" not in _SRV)
check("H7. движок supervisor не импортирует server.py, БД и сеть",
      all(s not in open(os.path.join(REPO, "app", "restart_supervisor.py"), encoding="utf-8").read()
          for s in ("import server", "sqlite3", "import socket", "urllib", "requests")))
check("H8. движок supervisor не содержит бизнес-логики печати",
      not re.search(r"printer|printed_qty|gcode",
                    open(os.path.join(REPO, "app", "restart_supervisor.py"), encoding="utf-8").read(), re.I))
_orch = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
check("H9. автоматическая отправка выключена", re.search(r"^DISPATCH_ENABLED = False", _orch, re.M) is not None)
check("H10. транспорт выключен", re.search(r"^TRANSPORT_ENABLED = False", _orch, re.M) is not None)
check("H11. тест не открывал сокетов и не запускал процессов", not _VIOLATIONS)
check("H12. sentinel живёт только в оснастке теста",
      SENTINEL not in _SRV and SENTINEL not in _APP and SENTINEL not in _HTML
      and SENTINEL not in open(os.path.join(REPO, "app", "restart_supervisor.py"), encoding="utf-8").read())
check("H13. КРИТИЧНО: программа не убивает прежний процесс — он завершается штатно сам",
      "taskkill" not in _SRV.split("def request_restart(")[1][:4000]
      and "os.kill(" not in _SRV)
check("H14. работа шла только во временной папке", os.path.realpath(JOURNAL).startswith(TMP_ROOT))

print()
print("=" * 95)
_verdict[0] = True
print("Проверок выполнено: %d, провалено: %d" % (_checked, fail))
if fail:
    print("FAIL: %d проверок провалено" % fail)
else:
    print("PASS: перезапуск подтверждается ДО остановки сервера; преемник запускается только после "
          "ухода прежнего процесса, освобождения замка и порта; успехом считается лишь реально "
          "ответивший Farm Manager нужной версии; при любой неудаче старый сервер продолжает "
          "работать либо пользователь получает понятную инструкцию.")
raise SystemExit(1 if fail else 0)
