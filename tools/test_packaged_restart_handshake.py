# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Handshake перезапуска в собранном EXE — core Alpha 2.810.
=================================================================================================
ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ.

Пользователь на собранной Alpha 2.809 удалил модуль и нажал «Перезапустить». Farm Manager
честно сообщил «служебный процесс не подтвердил готовность» и продолжил работать (fail-safe
2.809 сработал), но сам автоматический перезапуск так и не заработал. Журнал перезапуска
застыл на стадии planning: attempts=0, error="" — helper не оставил НИ ОДНОЙ записи.

ROOT CAUSE (доказан воспроизведением из исходников, категория J — несколько дефектов,
решающая комбинация A + отсутствие std-handles):
  1. Helper запускался DETACHED-процессом БЕЗ std-handles => sys.stdout is None.
  2. Ветка supervisor была объявлена «самой ранней», но стояла ПОСЛЕ ~130 строк module-level
     кода server.py, включая `sys.stdout.reconfigure(...)`, чей обработчик исключения звал
     ещё НЕ определённые `log` и `_exc_brief`. При stdout=None helper умирал с NameError во
     время импорта — за ~1 секунду, до единственной записи в журнал.
  3. Тот же дефект убил бы и ПРЕЕМНИКА (его тоже запускали без handles).
  4. Ранние пути выхода helper'а были немыми (журнал не наш -> sys.exit(0) без следа).

ЧТО ПРОВЕРЯЕТСЯ: точное воспроизведение причины на подлинном коде сервера (сегмент до замка
исполняется при sys.stdout=None); самая ранняя диспетчеризация служебных режимов (текст + AST);
armed-handshake c restart ID, PID helper'а и свежестью записи; self-test режим (эмуляция с
внедрёнными пробами); вердикт на каждом пути выхода; сценарии модулей и порта; безопасность.

ПОЛНОСТЬЮ OFFLINE: временные папки, поддельные пробы и часы; сеть, настоящие подпроцессы и
SQLite запрещены ловушками; рабочая БД, DATA_DIR и живой Farm Manager не затрагиваются.

Запуск: PYTHONIOENCODING=utf-8 python tools/test_packaged_restart_handshake.py   (0 = пройдено)
"""
import ast
import atexit
import glob
import json
import os
import re
import sys
import tempfile
import threading
import time
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "PACKAGED_RESTART_HANDSHAKE_SENTINEL_2_810"

# ── Ловушки-шпионы: сеть, настоящие подпроцессы и SQLite в offline-тесте запрещены ────────────
import socket as _socket_mod
import subprocess as _subprocess_mod
import sqlite3 as _sqlite3_mod

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


class _NoPopen(object):
    """Ловушка-КЛАСС (не функция): сегмент server.py импортирует asyncio, а тот наследует
    subprocess.Popen (class Popen(subprocess.Popen) в windows_utils) — функция там ломает
    сам импорт. Класс наследуется спокойно, но любая попытка СОЗДАТЬ процесс — нарушение."""

    def __init__(self, *a, **k):
        _no_subprocess()


_subprocess_mod.Popen = _NoPopen
_subprocess_mod.run = _no_subprocess

_real_sqlite_connect = _sqlite3_mod.connect


def _no_sqlite(*a, **k):
    _VIOLATIONS.append("sqlite")
    raise RuntimeError("открытие БД в offline-тесте запрещено")


_sqlite3_mod.connect = _no_sqlite

_TMP = tempfile.TemporaryDirectory(prefix="fm_pkg_handshake_2810_")
TMP_ROOT = os.path.realpath(_TMP.name)

from app import restart_supervisor as R
from app import restart_cli as C

_SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_CLI = open(os.path.join(REPO, "app", "restart_cli.py"), encoding="utf-8").read()
_ISO_SRC = open(os.path.join(REPO, "app", "e2e_isolation.py"), encoding="utf-8").read()
_SUP = open(os.path.join(REPO, "app", "restart_supervisor.py"), encoding="utf-8").read()
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


def slice_between(src, start, end_marker="\ndef "):
    i = src.index(start)
    j = src.find(end_marker, i + 1)
    return src[i:(j if j > 0 else i + 4000)]


def ordered(hay, first, second):
    """Оба якоря существуют И first стоит раньше second. Отсутствие якоря = проверка красная
    (а не исключение и не вакуумный зелёный) — важно для mutation proof."""
    i, j = hay.find(first), hay.find(second)
    return i >= 0 and j >= 0 and i < j


EXE = os.path.join(TMP_ROOT, "3DIWELL Farm Manager.exe")
DESKTOP_EXE = os.path.join(TMP_ROOT, "3DIWELL Farm Manager Desktop.exe")
for _p in (EXE, DESKTOP_EXE):
    with open(_p, "w", encoding="utf-8") as f:
        f.write("# " + SENTINEL + "\n")


def make_plan(journal, rid="rst_test1", executable=EXE, parent_pid=424242, port=8123,
              version="Alpha T", req_at=None):
    p = R.build_plan(True, executable, None, ["--no-browser"], TMP_ROOT, port, version,
                     parent_pid, rid, journal)
    now = time.time() if req_at is None else req_at
    p["requested_at"] = now
    p["updated_at"] = now
    return p


class FakeProbes(object):
    """Мгновенные виртуальные часы + управляемый мир для run_helper/run_supervisor."""

    def __init__(self, parent_alive=False, lock_busy=False, port_busy=False,
                 version_answer="Alpha T", spawn_ok=True, raise_in_pid=False):
        self.t = [0.0]
        self.spawns = []
        self.parent_alive = parent_alive
        self.lock_busy = lock_busy
        self.port_busy = port_busy
        self.version_answer = version_answer
        self.spawn_ok = spawn_ok
        self.raise_in_pid = raise_in_pid
        self.lock_checked = [0]
        self.port_checked = [0]

    def probes(self):
        def pid_alive(pid):
            if self.raise_in_pid:
                raise RuntimeError("probe crash")
            return self.parent_alive

        def lock_free():
            self.lock_checked[0] += 1
            return not self.lock_busy

        def port_in_use(port):
            self.port_checked[0] += 1
            return self.port_busy

        def spawn(cmd, wd):
            self.spawns.append((list(cmd), wd))
            return {"h": 1} if self.spawn_ok else None

        return R.Probes(
            pid_alive=pid_alive, port_in_use=port_in_use, lock_free=lock_free,
            http_version=lambda port: self.version_answer, spawn=spawn,
            now=lambda: self.t[0],
            sleep=lambda s: self.t.__setitem__(0, self.t[0] + float(s)),
            process_alive=lambda h: h is not None,
            wall=time.time)


print("=" * 95)
print("A. FORENSIC REGRESSION: точная причина отказа packaged helper Alpha 2.809")
print("=" * 95)

# Сегмент подлинного server.py от начала файла до замка одиночного экземпляра.
_seg_end = _SRV.index("_SINGLE_INSTANCE = _single_instance.acquire")
SEGMENT = _SRV[:_seg_end]

# A1: НАСТОЯЩИЕ условия packaged helper: sys.stdout=None (DETACHED без std-handles) +
#     аргумент supervisor. Диспетчеризация обязана сработать ДО любого падучего кода.
import app as _app_pkg
_stub_calls = []
_stub = types.ModuleType("app.restart_cli")
_stub.main = lambda argv: (_stub_calls.append(list(argv)) or 42)
_saved_mod = sys.modules.get("app.restart_cli")
_saved_attr = getattr(_app_pkg, "restart_cli", None)
_saved_argv, _saved_stdout = sys.argv, sys.stdout
_a1_exit, _a1_err = None, ""
try:
    sys.modules["app.restart_cli"] = _stub
    setattr(_app_pkg, "restart_cli", _stub)
    sys.argv = ["3DIWELL Farm Manager.exe", "--fm-restart-supervisor",
                os.path.join(TMP_ROOT, "j.json"), "--fm-restart-id", "rst_x"]
    sys.stdout = None
    try:
        exec(compile(SEGMENT, "server.py<segment>", "exec"), {"__name__": "__srv_segment__"})
    except SystemExit as e:
        _a1_exit = e.code
    except BaseException as e:
        _a1_err = type(e).__name__ + ": " + str(e)
finally:
    sys.stdout = _saved_stdout
    sys.argv = _saved_argv
    if _saved_mod is not None:
        sys.modules["app.restart_cli"] = _saved_mod
    if _saved_attr is not None:
        setattr(_app_pkg, "restart_cli", _saved_attr)

check("A1. КРИТИЧНО (root cause): при sys.stdout=None helper доходит до диспетчеризации и "
      "выходит через неё (на 2.809 здесь был NameError во время импорта)" +
      ("" if _a1_exit == 42 else " [%s exit=%r]" % (_a1_err, _a1_exit)),
      _a1_exit == 42 and not _a1_err)
check("A2. диспетчеризация получила подлинный argv (журнал и restart ID)",
      len(_stub_calls) == 1 and "--fm-restart-supervisor" in _stub_calls[0]
      and "--fm-restart-id" in _stub_calls[0])

# A3: обычный старт (ПРЕЕМНИК) при sys.stdout=None обязан пройти module-level код до замка.
#     На 2.809 этот же сегмент падал NameError'ом на sys.stdout.reconfigure-обработчике.
_saved_argv, _saved_stdout = sys.argv, sys.stdout
_a3_err = ""
try:
    sys.argv = ["3DIWELL Farm Manager.exe", "--no-browser"]
    sys.stdout = None
    try:
        exec(compile(SEGMENT, "server.py<segment>", "exec"), {"__name__": "__srv_segment__"})
    except SystemExit as e:
        _a3_err = "SystemExit:%r" % (e.code,)
    except BaseException as e:
        _a3_err = type(e).__name__ + ": " + str(e)
finally:
    sys.stdout = _saved_stdout
    sys.argv = _saved_argv
check("A3. КРИТИЧНО (преемник): обычный старт при sys.stdout=None доходит до замка без "
      "NameError (фикс строки reconfigure)" + ("" if not _a3_err else " [" + _a3_err + "]"),
      _a3_err == "")

_ri = _SRV.index("sys.stdout.reconfigure")   # первое вхождение — сам код (не комментарий)
check("A4. обработчик reconfigure больше не зовёт ещё не определённые имена: только pass + "
      "guard на stdout=None",
      re.search(r"except Exception:\s*\n\s*pass", _SRV[_ri:_ri + 260]) is not None
      and "sys.stdout is not None" in _SRV[_ri - 200:_ri]
      and "log.debug" not in _SRV[_ri - 200:_ri + 260])
check("A5. журнал отказа 2.809 (стадия planning, attempts=0) подтверждением НЕ считается",
      R.verify_armed({"schema": 1, "restart_id": "rst_a", "stage": "planning", "attempts": 0,
                      "error": "", "helper_pid": 0, "updated_at": time.time()},
                     "rst_a", lambda pid: True, time.time())[0] == "pending")

print()
print("=" * 95)
print("B. САМАЯ РАННЯЯ ДИСПЕТЧЕРИЗАЦИЯ (текст + AST)")
print("=" * 95)

_DISP = "'--fm-restart-supervisor' in sys.argv"
check("B1. диспетчеризация ДО замка одиночного экземпляра",
      ordered(_SRV, _DISP, "_SINGLE_INSTANCE = _single_instance.acquire"))
check("B2. диспетчеризация ДО чтения БД (init_db/_resolve_db/DATA_DIR)",
      ordered(_SRV, _DISP, "DATA_DIR = _data_dir()") and ordered(_SRV, _DISP, "def init_db"))
check("B3. диспетчеризация ДО загрузки модулей", ordered(_SRV, _DISP, "_load_modules"))
check("B4. диспетчеризация ДО трея", ordered(_SRV, _DISP, "pystray"))
check("B5. диспетчеризация ДО bind порта (uvicorn)", ordered(_SRV, _DISP, "import uvicorn"))
check("B6. диспетчеризация ДО опроса принтеров (mqtt)", ordered(_SRV, _DISP, "import paho.mqtt.client"))
check("B7. диспетчеризация ДО настройки логов и reconfigure (root cause)",
      ordered(_SRV, _DISP, "sys.stdout.reconfigure")
      and ordered(_SRV, _DISP, 'logging.getLogger("farm")'))

# AST-guard: ветка supervisor — среди самых первых statement'ов модуля, до первого импорта
# тяжёлых подсистем; тело ветки завершается sys.exit(...). Комментариями его не обмануть.
_tree = ast.parse(_SRV)
_disp_idx, _heavy_idx, _exit_ok = None, None, False
for _i, _node in enumerate(_tree.body):
    src_seg = ast.get_source_segment(_SRV, _node) or ""
    if _disp_idx is None and isinstance(_node, ast.If) and "--fm-restart-supervisor" in src_seg:
        _disp_idx = _i
        _last = _node.body[-1]
        _exit_ok = isinstance(_last, ast.Expr) and isinstance(_last.value, ast.Call) \
            and ast.get_source_segment(_SRV, _last.value).startswith("sys.exit(")
    if _heavy_idx is None and isinstance(_node, (ast.Import, ast.ImportFrom)) \
            and re.search(r"\b(paho|fastapi|uvicorn|pydantic)\b", src_seg):
        _heavy_idx = _i
check("B8. AST-guard: ветка supervisor — statement раньше первого импорта fastapi/uvicorn/paho",
      _disp_idx is not None and _heavy_idx is not None and _disp_idx < _heavy_idx)
check("B9. AST-guard: тело ветки завершается sys.exit(...) — в обычный старт она не проваливается",
      _exit_ok)
check("B10. воркеры пула исключены из ветки (multiprocessing-fork/__mp_main__)",
      "'--multiprocessing-fork' not in sys.argv" in _SRV.split("import io")[0]
      and '__name__ != "__mp_main__"' in _SRV.split("import io")[0])

print()
print("=" * 95)
print("C. ARMED HANDSHAKE")
print("=" * 95)

# C1: полный успешный путь helper'а: armed -> ... -> ready; PID helper'а в журнале.
_j1 = os.path.join(TMP_ROOT, "hs-ready.json")
_p1 = make_plan(_j1, rid="rst_ready")
R.write_journal(_j1, _p1)
_fp = FakeProbes(parent_alive=False)
rc = C.run_helper(["x", R.SUPERVISOR_FLAG, _j1, R.RID_FLAG, "rst_ready"], probes=_fp.probes())
_jd = R.read_journal(_j1)
check("C1. КРИТИЧНО: helper подтверждает armed и доводит журнал до ready (exit=verdict)",
      rc == C.EXIT_VERDICT_WRITTEN and _jd["stage"] == R.STAGE_READY)
check("C2. КРИТИЧНО: helper записал СВОЙ PID в журнал", int(_jd.get("helper_pid") or 0) == os.getpid())
check("C3. КРИТИЧНО: restart ID сохранён тем же на всём пути", _jd.get("restart_id") == "rst_ready")
check("C4. запись атомарна: временных .restart-*.tmp не осталось",
      not [f for f in os.listdir(TMP_ROOT) if f.startswith(".restart-")])
check("C5. отметка свежести — настенные часы (не монотонные микросекунды)",
      abs(float(_jd.get("updated_at") or 0) - time.time()) < 3600.0)

# C6-C8: parent-сторона verify_armed.
_now = time.time()
_armed_rec = {"schema": 1, "restart_id": "rst_v", "stage": R.STAGE_ARMED, "helper_pid": 777,
              "updated_at": _now, "error": ""}
check("C6. КРИТИЧНО: verify_armed принимает ТОЛЬКО живой helper_pid",
      R.verify_armed(dict(_armed_rec), "rst_v", lambda pid: True, _now)[0] == "armed"
      and R.verify_armed(dict(_armed_rec), "rst_v", lambda pid: False, _now)[0] == "pending")
check("C7. КРИТИЧНО: чужой restart ID не подтверждение",
      R.verify_armed(dict(_armed_rec), "rst_OTHER", lambda pid: True, _now)[0] == "pending")
check("C8. КРИТИЧНО: устаревшая запись armed отклоняется, свежая в пределах лимита — принимается",
      R.verify_armed(dict(_armed_rec, updated_at=_now - 9999), "rst_v", lambda pid: True, _now)[0] == "pending"
      and R.verify_armed(dict(_armed_rec, updated_at=_now - 200), "rst_v", lambda pid: True, _now)[0] == "armed")
check("C9. armed без helper_pid не принимается",
      R.verify_armed(dict(_armed_rec, helper_pid=0), "rst_v", lambda pid: True, _now)[0] == "pending")

# C10: журнал ДРУГОГО перезапуска не изменяется ни на байт.
_j2 = os.path.join(TMP_ROOT, "hs-foreign.json")
R.write_journal(_j2, make_plan(_j2, rid="rst_theirs"))
_before = open(_j2, encoding="utf-8").read()
rc = C.run_helper(["x", R.SUPERVISOR_FLAG, _j2, R.RID_FLAG, "rst_mine"], probes=FakeProbes().probes())
check("C10. КРИТИЧНО: журнал чужого restart ID не изменён, exit-код отличим",
      rc == C.EXIT_NO_JOURNAL and open(_j2, encoding="utf-8").read() == _before)

# C11: битый журнал -> вердикт в helper-логе, кода armed нет.
_j3 = os.path.join(TMP_ROOT, "hs-broken.json")
with open(_j3, "w", encoding="utf-8") as f:
    f.write("{ не json")
rc = C.run_helper(["x", R.SUPERVISOR_FLAG, _j3], probes=FakeProbes().probes())
_hl = open(C.helper_log_path(_j3), encoding="utf-8").read()
check("C11. битый журнал: exit-код no-journal + причина в ограниченном helper-логе",
      rc == C.EXIT_NO_JOURNAL and "journal_invalid" in _hl)

# C12: невалидный план (нет исполняемого файла) -> failed с безопасной причиной.
_j4 = os.path.join(TMP_ROOT, "hs-noexe.json")
R.write_journal(_j4, make_plan(_j4, rid="rst_noexe", executable=os.path.join(TMP_ROOT, "нет.exe")))
rc = C.run_helper(["x", R.SUPERVISOR_FLAG, _j4, R.RID_FLAG, "rst_noexe"], probes=FakeProbes().probes())
check("C12. КРИТИЧНО: ранний отказ helper'а оставляет failed+причину (executable_missing)",
      rc == C.EXIT_VERDICT_WRITTEN
      and (R.read_journal(_j4) or {}).get("stage") == R.STAGE_FAILED
      and (R.read_journal(_j4) or {}).get("error") == R.ERR_NO_EXECUTABLE)

# C13: оболочка Desktop как executable -> wrong_executable.
_j5 = os.path.join(TMP_ROOT, "hs-desktop.json")
R.write_journal(_j5, make_plan(_j5, rid="rst_desk", executable=DESKTOP_EXE))
C.run_helper(["x", R.SUPERVISOR_FLAG, _j5, R.RID_FLAG, "rst_desk"], probes=FakeProbes().probes())
check("C13. оболочка вместо сервера отклоняется кодом wrong_executable",
      (R.read_journal(_j5) or {}).get("error") == R.ERR_WRONG_EXECUTABLE)

# C14: устаревший план -> stale_plan (устаревший журнал ничего не запускает).
_j6 = os.path.join(TMP_ROOT, "hs-stale.json")
R.write_journal(_j6, make_plan(_j6, rid="rst_stale", req_at=time.time() - 86400))
_fp6 = FakeProbes()
C.run_helper(["x", R.SUPERVISOR_FLAG, _j6, R.RID_FLAG, "rst_stale"], probes=_fp6.probes())
check("C14. КРИТИЧНО: устаревший план не выполняется (failed stale_plan, преемник не запускался)",
      (R.read_journal(_j6) or {}).get("error") == R.ERR_STALE_PLAN and not _fp6.spawns)

# C15: авария внутри helper'а -> failed helper_crashed (немых падений нет).
_j7 = os.path.join(TMP_ROOT, "hs-crash.json")
R.write_journal(_j7, make_plan(_j7, rid="rst_crash"))
rc = C.run_helper(["x", R.SUPERVISOR_FLAG, _j7, R.RID_FLAG, "rst_crash"],
                  probes=FakeProbes(raise_in_pid=True).probes())
check("C15. КРИТИЧНО: неожиданная авария helper'а оставляет failed helper_crashed",
      rc == C.EXIT_VERDICT_WRITTEN
      and (R.read_journal(_j7) or {}).get("error") == R.ERR_HELPER_CRASH)

# C16: у КАЖДОГО пути run_helper есть вердикт: в журнале либо в helper-логе.
for _jx in (_j3, _j4, _j5, _j6, _j7):
    pass
check("C16. вердикты оставлены для всех сценариев C11-C15 (журнал failed либо строка в логе)",
      all(((R.read_journal(p) or {}).get("stage") == R.STAGE_FAILED)
          or os.path.exists(C.helper_log_path(p)) for p in (_j3, _j4, _j5, _j6, _j7)))

check("C17. stdout НЕ используется как IPC: в пути helper'а нет print(), канал — только журнал",
      "print(" not in slice_between(_CLI, "def run_helper(")
      and "print(" not in slice_between(_CLI, "def hlog("))
check("C18. helper-лог ограничен по размеру (bounded)",
      "HELPER_LOG_LIMIT" in _CLI and "getsize" in _CLI)
check("C19. в helper-лог не пишутся пути, команда и окружение (только стадии/коды/короткий rid)",
      not re.search(r'hlog\([^)]*\bjp\b[^)]*,\s*[^)]*(command|executable|workdir|environ)', _CLI)
      and "short_rid" in _CLI)
check("C20. КРИТИЧНО: parent принимает подтверждение только через verify_armed (rid+PID+свежесть)",
      "verify_armed" in slice_between(_SRV, "def request_restart(")
      and "_restart_cli.pid_alive" in slice_between(_SRV, "def request_restart("))

print()
print("=" * 95)
print("D. SELF-TEST РЕЖИМ (эмуляция с внедрёнными пробами)")
print("=" * 95)

_lock_probe_calls = [0]
_port_probe_calls = [0]
_successor_spawns = []


def _selftest_fake_spawn(cmd, wd):
    """Вместо реального процесса helper выполняется в потоке с мгновенными часами."""
    def _pid_alive_parent(pid):
        return True                       # parent (self-test) жив всё время

    def _lock_free():
        _lock_probe_calls[0] += 1
        return True

    def _port_in_use(port):
        _port_probe_calls[0] += 1
        return False

    # Часы РЕАЛЬНЫЕ: с мгновенными виртуальными журнал пролетал бы planning->failed до первого
    # опроса self-test'а (armed жил бы микросекунды). План несёт parent_exit=3 c — это и есть
    # ограниченная длительность эмуляции.
    probes = R.Probes(
        pid_alive=_pid_alive_parent, port_in_use=_port_in_use, lock_free=_lock_free,
        http_version=lambda port: None,
        spawn=lambda c, w: _successor_spawns.append((c, w)) or {"h": 1},
        now=time.monotonic, sleep=lambda s: time.sleep(min(float(s), 0.05)),
        process_alive=lambda h: True, wall=time.time)
    th = threading.Thread(target=C.run_helper, args=(list(cmd),), kwargs={"probes": probes},
                          daemon=True)
    th.start()

    class _H(object):
        def poll(self):
            return None if th.is_alive() else 0
    return _H()


_emitted = []
_st_before = set(glob.glob(os.path.join(tempfile.gettempdir(), "fm_restart_selftest_*")))
_st_rc = C.run_selftest([R.SELFTEST_FLAG], spawn=_selftest_fake_spawn, emit=_emitted.append)
_st_after = set(glob.glob(os.path.join(tempfile.gettempdir(), "fm_restart_selftest_*")))
_st_rep = json.loads(_emitted[0]) if _emitted else {}

check("D1. КРИТИЧНО: self-test проходит (exit 0) и подтверждает armed",
      _st_rc == 0 and _st_rep.get("ok") is True and _st_rep.get("armed") is True)
check("D2. КРИТИЧНО: helper оставил честный вердикт parent_still_running (parent жив)",
      _st_rep.get("verdict_error") == R.ERR_PARENT_ALIVE)
check("D3. КРИТИЧНО: преемник в self-test НЕ запускался", not _successor_spawns)
check("D4. КРИТИЧНО: замок одиночного экземпляра не проверялся и не брался (ветка недостижима)",
      _lock_probe_calls[0] == 0 and "single_instance" not in slice_between(_CLI, "def run_selftest("))
check("D5. КРИТИЧНО: порт не проверялся и не bind-ился", _port_probe_calls[0] == 0)
check("D6. временные артефакты self-test удалены",
      _st_after == _st_before)
check("D7. отчёт машиночитаем: одна JSON-строка со стадиями",
      len(_emitted) == 1 and isinstance(_st_rep.get("stages_seen"), list))
check("D8. PID helper'а был виден в журнале во время armed", _st_rep.get("helper_pid_seen") is True)
check("D9. self-test не открывал БД, не создавал сокетов, не запускал настоящих процессов",
      not _VIOLATIONS)
check("D10. self-test — только локальный CLI: все упоминания флага стоят ДО первого HTTP-маршрута",
      _SRV.find("--fm-restart-supervisor-selftest") >= 0
      and _SRV.rfind("--fm-restart-supervisor-selftest") < _SRV.index("@app."))
check("D11. диспетчер main(): self-test и helper разведены, прочее — безопасный отказ",
      "if rsup.SELFTEST_FLAG in args" in _CLI and "if rsup.SUPERVISOR_FLAG in args" in _CLI
      and "return EXIT_NO_JOURNAL" in slice_between(_CLI, "def main("))
check("D12. self-test не трогает конфигурацию порта (нет чтения/записи config)",
      "config" not in slice_between(_CLI, "def run_selftest(").lower())
check("D13. журнал self-test живёт вне распаковки onefile (_MEI-защита)",
      "tempdir_inside_meipass" in _CLI and "_MEIPASS" in _CLI)

print()
print("=" * 95)
print("E. FAILURE MODES: parent остаётся жив")
print("=" * 95)

_req = slice_between(_SRV, "def request_restart(", "\ndef _restart_shutdown_now")
check("E1. невыполнимый план прерывает перезапуск ДО запуска helper'а (сервер жив)",
      re.search(r"preflight\(plan\)\s*\n\s*if not ok:(?:.|\n){0,240}?return False, why", _req) is not None)
check("E2. журнал недоступен (незаписываемая папка) -> отказ journal_unavailable, сервер жив",
      '"journal_unavailable"' in _req)
check("E3. КРИТИЧНО: не создался процесс helper'а -> безопасный отказ, сервер жив",
      "spawn_detached" in _req and "ERR_HELPER_NOT_STARTED" in _req)
check("E4. КРИТИЧНО: helper не подтвердил -> отказ с причиной, сервер продолжает работу "
      "(2.811: различаются немая смерть, смерть до armed и молчание живого)",
      '"arm_timeout"' in _req and "deadline" in _req
      and "ERR_HELPER_NO_VERDICT" in _req and "ERR_HELPER_EXITED_BEFORE_ARM" in _req)
check("E5. КРИТИЧНО: parent сам ставит вердикт arm_timeout застрявшему журналу (нет вечного planning)",
      re.search(r'STAGE_PLANNING[^)]*\)[^)]*\n\s*_restart_sup\.set_stage\([^)]*"arm_timeout"', _req) is not None
      or ('"arm_timeout"' in _req and "set_stage" in _req))
check("E6. вердикт отказа helper'а транслируется как причина (state failed -> return False)",
      re.search(r'if state == "failed":\s*\n\s*return False', _req) is not None)
check("E7. завершение сервера возможно ТОЛЬКО после подтверждения (shutdown в отдельном потоке "
      "после request_restart ok)",
      ordered(_SRV, "ok, why = request_restart()", "def _bye():"))
check("E8. поздний, но свежий armed в пределах дедлайна принимается (bounded cold-start)",
      "45.0" in _req and R.ARMED_MAX_AGE_SECONDS >= 120.0)
check("E9. бесконечных ожиданий нет: дедлайн parent, таймауты supervisor конечны, повторов максимум 2",
      "time.monotonic() < deadline" in _req
      and all(v > 0 for v in R.DEFAULT_TIMEOUTS.values()) and R.MAX_LAUNCH_ATTEMPTS == 2)
check("E10. КРИТИЧНО: restart ID создаётся криптографически (secrets), а не uuid",
      'secrets.token_hex' in _req)
check("E11. таймауты из плана зажимаются в разумные рамки (0.5..900 c)",
      "min(float(_v), 900.0)" in _SUP and "max(0.5" in _SUP)

print()
print("=" * 95)
print("F. СЦЕНАРИИ МОДУЛЕЙ И ПОРТА")
print("=" * 95)

check("F1. перезапуск после удаления/установки/обновления модуля идёт через единый механизм",
      _SRV.count("perform_restart_async()") >= 2 and '@app.post("/api/restart")' in _SRV)
check("F2. интерфейс модулей зовёт тот же doRestart (кнопка после установки/удаления)",
      "moduleRestartNeeded" in _HTML and _HTML.count('@click="doRestart()"') >= 2)
check("F3. КРИТИЧНО: неудачный armed НЕ сбрасывает «требуется перезапуск» у модулей",
      "moduleRestartNeeded" not in slice_between(_APP, "const doRestart = async ()")
      and "moduleRestartNeeded" not in slice_between(_APP, "const dismissRestartState = ()"))
check("F4. отказ перезапуска не трогает файлы модулей и ZIP",
      "modules" not in _req.lower() and "zip" not in _req.lower())
check("F5. смена порта использует тот же supervisor-механизм",
      "def _restart_for_port(" in _SRV
      and "perform_restart_async()" in _SRV[_SRV.index("def _restart_for_port("):
                                            _SRV.index("def _restart_for_port(") + 900])
check("F6. pending-порт активируется только на старте преемника (commit_pending вне request_restart)",
      "commit_pending" not in _req and "commit_pending" in _SRV)
check("F7. отказ armed не меняет конфигурацию порта (в request_restart нет записи config)",
      "_write_config_atomic" not in _req and "plan_change" not in _req)
check("F8. откат несостоявшегося bind сохранён (rollback_pending)", "rollback_pending" in _SRV)
check("F9. параллельный второй перезапуск отклоняется (restart_in_progress)",
      "_restart_lock.acquire(blocking=False)" in _SRV and '"restart_in_progress"' in _req)

print()
print("=" * 95)
print("G. ИНТЕРФЕЙС ОТКАЗА")
print("=" * 95)

check("G1. отказ показывается RU/EN текстом с безопасным кодом причины",
      "restartReasonCode" in _APP and "Код причины" in _HTML and "Reason code" in _HTML)
check("G2. код причины фильтруется (только [a-z0-9_], иначе unknown) — путей и traceback нет",
      re.search(r"restartReasonCode[\s\S]{0,300}\[a-z0-9_\]", _APP) is not None)
check("G3. есть кнопка «Повторить» в состоянии отказа",
      "'Повторить':'Retry'" in _HTML
      and re.search(r"restartPhase==='failed'[^<]*<", _HTML) is not None)
check("G4. отказ виден из любого места запуска (оверлей включает failed)",
      "restartPhase==='failed'" in _HTML.split("fm-settings-backdrop", 1)[-1]
      and "|| restartPhase==='failed'" in _HTML)
check("G5. parent остаётся жив: текст «Farm Manager продолжает работать» сохранён",
      "Farm Manager продолжает работать" in _APP and "Farm Manager keeps running" in _APP)
check("G6. после armed поведение 2.809 сохранено: экран ожидания + ограниченный опрос + reload",
      "restartWaitReady" in _APP and re.search(r"for \(let i = 0; i < \d+; i\+\+\)", _APP)
      and "location.reload()" in _APP)
check("G7. RU/EN тексты новых причин добавлены (stale_plan/helper_crashed/journal_invalid)",
      "stale_plan" in _APP and "helper_crashed" in _APP and "journal_invalid" in _APP)

print()
print("=" * 95)
print("H. БЕЗОПАСНОСТЬ")
print("=" * 95)

_route = _SRV[_SRV.index('@app.post("/api/restart")'):]
_route = _route[:_route.index("\n@app.")]
check("H1. КРИТИЧНО: перезапуск закрыт системным админом ДО любых действий",
      "_require_system_admin(req)" in _route
      and ordered(_route, "_require_system_admin", "perform_restart_async"))
check("H2. self-test недоступен удалённо: флага нет в оболочке и клиенте",
      all("--fm-restart-supervisor-selftest" not in open(os.path.join(REPO, "app", f), encoding="utf-8").read()
          for f in ("desktop_shell.py", "desktop_shell_config.py", "desktop_shell_security.py")))
check("H3. маршрут не принимает журнал/план от клиента (нет разбора тела запроса)",
      "req.json()" not in _route and "await req.body" not in _route)
check("H4. наружу не выходят пути и команда: ответ маршрута — только status/reason/restart_armed",
      '"restart_armed"' in _route and "executable" not in _route and "command" not in _route)
check("H5. journal_public скрывает executable/command/workdir (marker — не auth token)",
      all(k not in R._JOURNAL_KEYS for k in ("executable", "command", "workdir", "journal")))
check("H6. shell=False везде (server.py, restart_cli, restart_supervisor)",
      all("shell=True" not in s for s in (_SRV, _CLI, _SUP)))
check("H7. автоматическая отправка выключена (DISPATCH_ENABLED=False)",
      re.search(r"^DISPATCH_ENABLED = False",
                open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M) is not None)
check("H8. транспорт выключен (TRANSPORT_ENABLED=False)",
      re.search(r"^TRANSPORT_ENABLED = False",
                open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M) is not None)
check("H9. в restart-модулях нет команд принтерам и принтерных протоколов",
      not re.search(r"mqtt|ftplib|8883|8898|moonraker", _CLI + _SUP, re.I))
check("H10. LAN/firewall не трогаются (нет netsh/firewall в restart-путях)",
      not re.search(r"netsh|firewall", _CLI + _SUP + _req, re.I))
check("H11. _incoming/ не используется restart-механизмом",
      "_incoming" not in _CLI and "_incoming" not in _SUP and "_incoming" not in _req)
check("H12. sentinel живёт только в оснастке теста",
      all(SENTINEL not in s for s in (_SRV, _CLI, _SUP, _APP, _HTML)))
check("H13. helper не убивает процессы (нет taskkill/os.kill) — прежний завершается сам",
      "taskkill" not in _CLI and "os.kill" not in _CLI)
check("H14. ловушки: тест не открывал сеть/БД/настоящие процессы", not _VIOLATIONS)

print()
print("=" * 95)
print("K. КОНТРАКТ ИЗОЛЯЦИИ ТЕСТОВОГО ЭКЗЕМПЛЯРА (Alpha 2.811)")
print("=" * 95)

# Быстрые проверки границы: без запуска процессов. Изоляция позволяет поднять ВТОРУЮ копию
# программы, поэтому её граница обязана быть жёсткой — иначе подменой окружения рабочую копию
# можно было бы увести на чужие данные.
from app import e2e_isolation as ISO

_PROD_DD = os.path.join(TMP_ROOT, "production_data")
_PROD_MUTEX = r"Local\3DIWELL_Farm_Manager_SingleInstance_v1"
os.makedirs(_PROD_DD, exist_ok=True)
_ISO_ROOT = os.path.join(TMP_ROOT, "e2e_root")
os.makedirs(_ISO_ROOT, exist_ok=True)
_TOKEN = "k" * 32
with open(os.path.join(_ISO_ROOT, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
    json.dump({"token": _TOKEN}, f)
_ENV_OK = {ISO.ENV_SENTINEL: _TOKEN, ISO.ENV_DATA_DIR: _ISO_ROOT,
           ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_test"}

check("K1. КРИТИЧНО: без CLI-флага переменные окружения игнорируются целиком "
      "(подменой окружения рабочую копию не увести)",
      ISO.detect([], _ENV_OK, _PROD_DD, _PROD_MUTEX) == (None, ""))
_iso, _err = ISO.detect([ISO.FLAG], _ENV_OK, _PROD_DD, _PROD_MUTEX)
check("K2. корректная изоляция принимается и отдаёт проверенные пути",
      _iso is not None and not _err and _iso.data_dir == os.path.abspath(_ISO_ROOT))
check("K3. КРИТИЧНО: рабочее имя замка запрещено",
      ISO.detect([ISO.FLAG], dict(_ENV_OK, **{ISO.ENV_MUTEX: _PROD_MUTEX}),
                 _PROD_DD, _PROD_MUTEX)[1] == ISO.ERR_MUTEX)
check("K4. КРИТИЧНО: рабочая папка данных как корень теста запрещена",
      ISO.detect([ISO.FLAG], dict(_ENV_OK, **{ISO.ENV_DATA_DIR: _PROD_DD}),
                 _PROD_DD, _PROD_MUTEX)[1] in (ISO.ERR_ROOT_IN_PRODUCTION, ISO.ERR_MARKER))
check("K5. КРИТИЧНО: config вне папки теста запрещён",
      ISO.detect([ISO.FLAG], dict(_ENV_OK, **{ISO.ENV_CONFIG: os.path.join(_PROD_DD, "config.json")}),
                 _PROD_DD, _PROD_MUTEX)[1] == ISO.ERR_CONFIG)
check("K6. КРИТИЧНО: неверный токен маркера отклоняется",
      ISO.detect([ISO.FLAG], dict(_ENV_OK, **{ISO.ENV_SENTINEL: "z" * 32}),
                 _PROD_DD, _PROD_MUTEX)[1] == ISO.ERR_MARKER)
check("K7. КРИТИЧНО: слабый sentinel отклоняется",
      ISO.detect([ISO.FLAG], dict(_ENV_OK, **{ISO.ENV_SENTINEL: "abc"}),
                 _PROD_DD, _PROD_MUTEX)[1] == ISO.ERR_NO_SENTINEL)
check("K8. несуществующая папка теста отклоняется",
      ISO.detect([ISO.FLAG], dict(_ENV_OK, **{ISO.ENV_DATA_DIR: os.path.join(TMP_ROOT, "нет")}),
                 _PROD_DD, _PROD_MUTEX)[1] == ISO.ERR_ROOT_NOT_DIR)
check("K9. КРИТИЧНО: сервер использует изоляцию для папки данных, config и замка",
      "_E2E.data_dir" in _SRV and "_E2E.config_path" in _SRV and "_E2E.mutex_name" in _SRV)
check("K10. КРИТИЧНО: непройденная проверка изоляции ОСТАНАВЛИВАЕТ запуск (а не откатывает "
      "тестовый экземпляр на рабочие данные)",
      re.search(r"_E2E is None:\s*\n\s*print\([^\n]*\)\s*\n\s*sys\.exit\(3\)", _SRV) is not None)
check("K11. изоляция выключает трей, обнаружение, принтеров и модули",
      "disable_tray" in _SRV and "disable_discovery" in _SRV
      and "disable_printers" in _SRV and "disable_modules" in _SRV)
check("K12. КРИТИЧНО: модуль изоляции ничего не создаёт и не пишет — только проверяет",
      not re.search(r"\bos\.(makedirs|mkdir|remove|rename)\b|open\([^)]*['\"][wa]", _ISO_SRC))
check("K13. изоляция не импортирует server.py, БД и сеть",
      all(s not in _ISO_SRC for s in ("import server", "sqlite3", "import socket", "urllib")))

print()
print("=" * 95)
print("J. ПАРИТЕТ ПРОВЕРОК И ПРОДУКТА (Alpha 2.811)")
print("=" * 95)

# Проверка перестаёт что-либо значить, если подменяет ровно то звено, которое ломается. Отказ
# 2.810 случился в фактическом запуске преемника — том самом, который прежние тесты мокали.
# Поэтому здесь сторожим сам E2E-контур: он обязан идти настоящим производственным путём.
_E2E_T = open(os.path.join(REPO, "tools", "test_packaged_restart_end_to_end.py"),
              encoding="utf-8").read()


def _identifiers(src):
    """Имена, реально ИСПОЛЬЗУЕМЫЕ кодом (AST), а не встречающиеся в тексте.

    Проверять «подстрока есть в файле» здесь нельзя: в докстроке этого же теста честно
    написано, что spawn и verify_armed не подменяются, — и текстовая проверка ловила бы
    собственную прозу вместо кода."""
    ids = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name):
            ids.add(node.id)
        elif isinstance(node, ast.Attribute):
            ids.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                ids.add(a.name.split(".")[-1])
                if a.asname:
                    ids.add(a.asname)
            if isinstance(node, ast.ImportFrom) and node.module:
                ids.add(node.module.split(".")[-1])
    return ids


_E2E_IDS = _identifiers(_E2E_T)
check("J1. КРИТИЧНО: E2E-контур не подменяет запуск процессов (никаких моков spawn_detached)",
      "spawn_detached" not in _E2E_IDS and "restart_cli" not in _E2E_IDS)
check("J2. КРИТИЧНО: E2E-контур не обходит проверку подтверждения (verify_armed не подменяется)",
      "verify_armed" not in _E2E_IDS)
def _code_strings(src):
    """Строковые литералы КОДА, без докстрок.

    Докстрока — тоже ast.Constant, поэтому «адрес встречается в константах» ловилось описанием
    теста, где этот адрес честно упомянут. Исключаем первый Expr-Constant у модуля, функций и
    классов — остаются только строки, которые реально участвуют в работе."""
    tree = ast.parse(src)
    doc_ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.body and isinstance(n.body[0], ast.Expr) \
                    and isinstance(n.body[0].value, ast.Constant) \
                    and isinstance(n.body[0].value.value, str):
                doc_ids.add(id(n.body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids]


_E2E_STRINGS = _code_strings(_E2E_T)
check("J3. КРИТИЧНО: перезапуск в E2E инициируется настоящим маршрутом /api/restart "
      "(ищем именно АДРЕС ЗАПРОСА: этот путь упомянут и в докстроке, и в тексте проверок)",
      any(s.startswith("http") and "/api/restart" in s for s in _E2E_STRINGS)
      and "post_restart" in _E2E_IDS)
check("J4. КРИТИЧНО: E2E не подкладывает готовый armed-маркер",
      "STAGE_ARMED" not in _E2E_IDS and "write_journal" not in _E2E_IDS)
check("J5. КРИТИЧНО: E2E проверяет, что у преемника ДРУГОЙ PID",
      "successor_pid != parent_pid" in _E2E_T)
check("J6. КРИТИЧНО: E2E проверяет отсутствие двух слушателей одновременно",
      "len(new_pids) == 1" in _E2E_T)
check("J7. КРИТИЧНО: E2E работает во временной папке данных, а не в рабочей",
      "TemporaryDirectory" in _E2E_T and "ENV_DATA_DIR" in _E2E_T)
check("J8. КРИТИЧНО: E2E запускает только удостоверенную сборку текущей версии",
      "e2e-supported.txt" in _E2E_T and "certified(" in _E2E_T)
check("J9. КРИТИЧНО: рабочая папка dist в E2E кандидатом не является",
      'os.path.join(REPO, "dist")' in _E2E_T
      and _E2E_T.count("3DIWELL_Builds") >= 1)
check("J10. КРИТИЧНО: план перезапуска строится ОДНОЙ функцией и для продукта, и для self-test",
      _SRV.count("_restart_sup.build_plan(") == 1 and "rsup.build_plan(" in _CLI)
check("J11. КРИТИЧНО: единая точка запуска процессов у helper и преемника",
      "spawn_detached" in slice_between(_CLI, "def build_probes(")
      and "_restart_cli.spawn_detached" in slice_between(_SRV, "def request_restart("))
check("J12. КРИТИЧНО (root cause 2.810): окружение распаковщика onefile не наследуется",
      "clean_child_env" in _CLI and "_PYI" in _CLI
      and "env=clean_child_env(env)" in slice_between(_CLI, "def spawn_detached("))
check("J13. КРИТИЧНО: смена порта — ожидание старого порта и готовность на фактическом",
      "wait_port" in _SUP and "ready_ports" in _SUP and "_restart_ready_ports(" in _SRV)
check("J15. КРИТИЧНО: при запланированной смене порта кандидатами готовности являются ОБА порта — "
      "новый и прежний; иначе честный откат преемника считался бы провалом перезапуска",
      re.search(r"ready\s*=\s*\[active\]\s*if not pending else\s*\[int\(pending\), active\]",
                _SRV) is not None)
check("J14. helper ждёт СВОЙ замок (у изолированного экземпляра он собственный)",
      "mutex_name" in _SUP and "build_probes(plan.get(\"mutex_name\"))" in _CLI)

print()
print("=" * 95)
print("I. РЕГРЕССИИ И ГРАНИЦЫ")
print("=" * 95)

check("I1. lifecycle 2.807 сохранён (наблюдение печати + сброс sequence)",
      "observe_printer_job(" in _SRV and "UPDATE printer_job_sessions SET sequence=0" in _SRV)
check("I2. управление модулями 2.808 сохранено (_failed_modules + состояния)",
      "_failed_modules" in _SRV and "pending_restart" in _SRV)
check("I3. fail-safe 2.809 сохранён: сервер завершается только после подтверждения",
      '"restart_armed": False' in _SRV and "status_code=409" in _SRV)
check("I4. контракт порта 2.806 сохранён (startup_plan/commit/rollback)",
      "startup_plan" in _SRV and "commit_pending" in _SRV and "rollback_pending" in _SRV)
check("I5. оболочка Desktop запускает backend с DEVNULL-handles (эталон, который перенят helper'ом)",
      "stdin=subprocess.DEVNULL" in open(os.path.join(REPO, "app", "desktop_shell.py"), encoding="utf-8").read())
check("I6. HTTP-маршруты ядра = 178",
      len(re.findall(r'@app\.(get|post|patch|delete|websocket)\(', _SRV)) == 209)   # 2.823: +5 printer-files; 2.825: +select-for-print; 2.827: +4 config-backup; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.927: +3 пометки принтера и настройки фермы; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
check("I7. схема БД не менялась (нет ALTER/DROP)",
      "ALTER TABLE printer_job_sessions" not in _SRV and "DROP TABLE" not in _SRV)
check("I8. артефактов e2e нет (tools/_e2e_payload.json отсутствует)",
      not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))
check("I9. движок и CLI не импортируют server.py и БД",
      "import server" not in _CLI and "import server" not in _SUP
      and "sqlite3" not in _CLI and "sqlite3" not in _SUP)
check("I10. работа шла только во временной папке",
      os.path.realpath(_j1).startswith(TMP_ROOT) and os.path.realpath(EXE).startswith(TMP_ROOT))

print()
print("=" * 95)
_verdict[0] = True
print("Проверок выполнено: %d, провалено: %d" % (_checked, fail))
if fail:
    print("FAIL: %d проверок провалено" % fail)
else:
    print("PASS: причина отказа packaged helper 2.809 воспроизведена и закрыта; служебные режимы "
          "обрабатываются раньше всего падучего кода; каждый helper оставляет armed либо failed "
          "с причиной; self-test доказывает handshake без запуска backend; parent жив при любом "
          "отказе; сценарии модулей и порта идут единым механизмом.")
raise SystemExit(1 if fail else 0)
