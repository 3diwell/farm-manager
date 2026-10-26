# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Синхронизация ВНЕШНЕЙ и ПОВТОРНОЙ печати — core Alpha 2.807.
=================================================================================================
ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ.

Пользовательский сценарий: деталь однажды отправили на принтер из Farm Manager, она напечаталась
и была засчитана. Потом оператор ПРЯМО НА ЭКРАНЕ ПРИНТЕРА выбирает тот же сохранённый файл и
запускает печать заново. Farm Manager обязан узнать эту печать, показать деталь как «печатается»
на конкретном принтере и после успешного завершения увеличить количество готовых ровно на один.

ЧТО БЫЛО СЛОМАНО (подтверждено журналом фермы и рабочей БД).
Механизм привязки экранной печати жив и матчит, НО учёт терялся: стартовая уборка «осиротевших»
заданий (Alpha 2.767) считала осиротевшим КАЖДОЕ задание, у которого нет строки-владельца в плане
«Печатать весь проект». У экранной и у обычной ручной печати такой строки нет и быть не может —
на рабочей ферме project_run_items пуст вовсе. Поэтому при каждом перезапуске программы гасились
в том числе задания ИДУЩИХ печатей («помечено failed: 15» при печатях по 6-30 часов), и до
засчёта дело не доходило никогда. Вдобавок личность запуска жила только в памяти процесса:
перезапуск создавал ВТОРУЮ запись на ту же физическую печать (дальше ambiguous_multi — «учёт не
ведём»), а повторная печать того же файла не отличалась от продолжения прежней.

ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ.
Функции берутся ДОСЛОВНО из server.py (exec нужных блоков) и работают на ВРЕМЕННОЙ SQLite со
схемой, тоже извлечённой из server.py: тест падает, если реализация уедет. Чистый движок
app/printer_job_lifecycle.py импортируется как есть.

ПОЛНОСТЬЮ OFFLINE: временная папка, временная БД, синтетические проекты/файлы/детали,
фикстуры протоколов, поддельные часы. Реальные принтеры не используются, сеть не используется,
рабочая БД и DATA_DIR не открываются, server.py не импортируется обычным способом.

Запуск: PYTHONIOENCODING=utf-8 python tools/test_external_reprint_sync.py   (0 = пройдено)
"""
import atexit
import contextlib
import os
import re
import sys
import tempfile
import threading
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "EXTERNAL_REPRINT_SYNC_SENTINEL_2_807"

# ── Ловушки-шпионы: доказываем, что тест ничего не делает наружу ────────────────────────────────
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
    raise RuntimeError("подпроцессы в offline-тесте запрещены")


_subprocess_mod.Popen = _no_subprocess
_subprocess_mod.run = _no_subprocess

import sqlite3

_TMP = tempfile.TemporaryDirectory(prefix="fm_reprint_2807_")
TMP_ROOT = os.path.realpath(_TMP.name)

_real_connect = sqlite3.connect


def _guarded_connect(target, *a, **k):
    """Открывать SQLite можно ТОЛЬКО внутри временной папки: рабочая БД неприкосновенна."""
    if isinstance(target, str) and target not in (":memory:",):
        if not os.path.realpath(target).startswith(TMP_ROOT):
            _VIOLATIONS.append("sqlite:" + os.path.basename(target))
            raise RuntimeError("открытие БД вне временной папки запрещено")
    return _real_connect(target, *a, **k)


sqlite3.connect = _guarded_connect

_SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

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
    """Преждевременный выход (в т.ч. чужой sys.exit(0)) не должен выглядеть зелёным прогоном."""
    if not _verdict[0]:
        print("FAIL — тест завершился БЕЗ финального вердикта (преждевременный выход)")
        os._exit(1)


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


def _fn_src(name):
    """Исходник функции ядра ДОСЛОВНО: от 'def name(' до следующего определения верхнего уровня."""
    i = _SRV.index("\ndef %s(" % name) + 1
    m = re.search(r"\n(?=def |class |@app\.|if not _IS_POOL_WORKER)", _SRV[i:])
    return _SRV[i:i + (m.start() if m else len(_SRV))]


# ── Песочница ядра ─────────────────────────────────────────────────────────────────────────────
from app import printer_job_lifecycle as PJL

DB = os.path.join(TMP_ROOT, "farm_parts.db")
conn_p = sqlite3.connect(DB, check_same_thread=False)
conn_p.row_factory = sqlite3.Row
for _t in ("projects", "project_files", "project_parts", "project_file_parts",
           "project_print_jobs", "printer_job_sessions", "staging_files"):
    conn_p.execute(_ddl(_t))
conn_p.execute("CREATE TABLE IF NOT EXISTS project_run_items (id TEXT PRIMARY KEY, project_print_job_id TEXT, state TEXT)")
conn_p.commit()

CLOCK = [1000.0]


class _Log(object):
    """Журнал теста: копим строки, чтобы доказать отсутствие секретов и наличие событий."""

    lines = []

    @classmethod
    def _rec(cls, msg, *a):
        try:
            cls.lines.append(str(msg) % a if a else str(msg))
        except Exception:
            cls.lines.append(str(msg))

    info = classmethod(lambda cls, m, *a, **k: cls._rec(m, *a))
    debug = classmethod(lambda cls, m, *a, **k: cls._rec(m, *a))
    warning = classmethod(lambda cls, m, *a, **k: cls._rec(m, *a))
    error = classmethod(lambda cls, m, *a, **k: cls._rec(m, *a))


NS = {
    "conn_p": conn_p, "lock_p": threading.RLock(), "os": os, "re": re, "uuid": uuid,
    "json": __import__("json"), "time": type("T", (), {"time": staticmethod(lambda: CLOCK[0]),
                                                       "monotonic": staticmethod(lambda: CLOCK[0])})(),
    "log": _Log, "_pjl": PJL, "contextmanager": contextlib.contextmanager,
    "_exc_brief": lambda: "test-exc",
    "worker_epoch": 1,
    "printer_kinds": {}, "_pjl_seq": {}, "_pjl_session_cache": {},
    "p_states": {}, "_user_stopped": set(), "print_source": {},
    "_IS_POOL_WORKER": True,
}
NS["__builtins__"] = __builtins__
# Каноническая нормализация имени ядра — ДОСЛОВНО из server.py (её использует create_project_print_job).
exec(re.search(r"^NORM_RE = .*$", _SRV, re.M).group(0), NS)
exec(re.search(r"^norm = lambda .*$", _SRV, re.M).group(0), NS)

#  Alpha 2.947: связывание печати с проектом спрашивает у задач Quick Tasks, включена ли у них
#  синхронизация (печать несинхронизированной задачи в проект не засчитывается). Функции нужны
#  здесь целиком: без них _pjl_link_project падал бы на NameError, и наблюдение молча теряло бы
#  привязку — то есть тест краснел бы по причине оснастки, а не по существу.
for _f in ("_get_setting", "_staging_sync_map", "_staging_sync_on", "_staging_task_for_print",
           "_rollback_sqlite_on_error", "_uid", "_get_project", "_recompute_project_part_status",
           "create_project_print_job", "finish_project_print_job", "fail_project_print_job",
           "_pjl_active_states", "_pjl_row_to_session", "_pjl_load_session",
           "_pjl_match_candidates", "_pjl_remote_sends", "_pjl_project_filename",
           "_pjl_resolve_match", "_pjl_log", "_pjl_close_session", "_pjl_link_project",
           "_pjl_open_session", "_pjl_touch_session", "observe_printer_job",
           "_pjl_active_session_job", "_pjl_live_job_ids", "_pjl_recover_on_start",
           "_pjob_candidates", "_pjob_name_match", "_match_project_job", "_pjob_recover_stale"):
    exec(_fn_src(_f), NS)
# Вырезка идёт от строки `def ...`, поэтому декоратор @contextmanager в неё не попадает —
# возвращаем его здесь, иначе транзакционная обёртка ядра осталась бы простым генератором.
NS["_rollback_sqlite_on_error"] = contextlib.contextmanager(NS["_rollback_sqlite_on_error"])

observe = NS["observe_printer_job"]


# ── Фикстуры протоколов (СИНТЕТИЧЕСКИЕ; без serial, IP, кодов доступа и реальных имён) ──────────
# Каждая строка — ровно то, что отдаёт прошивка в поле состояния, и ничего больше.
FIXTURES = {
    "bambu": {"idle": "IDLE", "preparing": "PREPARE", "printing": "RUNNING", "paused": "PAUSE",
              "completed": "FINISH", "failed": "FAILED", "unknown_future": "TELEPORTING"},
    "klipper": {"idle": "standby", "printing": "printing", "paused": "paused",
                "completed": "complete", "cancelled": "cancelled", "failed": "error",
                "unknown_future": "quantum"},
    "flashforge": {"idle": "ready", "preparing": "heating", "printing": "printing",
                   "paused": "paused", "completed": "completed", "cancelled": "cancel",
                   "failed": "error", "unknown_future": "hyperdrive"},
}

P_BAMBU, P_KLIP, P_FF = "prn_bambu", "prn_klipper", "prn_ff"
NS["printer_kinds"].update({P_BAMBU: "bambu", P_KLIP: "klipper", P_FF: "flashforge"})


def reset_all():
    for t in ("projects", "project_files", "project_parts", "project_file_parts",
              "project_print_jobs", "printer_job_sessions", "project_run_items", "staging_files"):
        conn_p.execute("DELETE FROM " + t)
    conn_p.commit()
    NS["_pjl_session_cache"].clear()
    NS["_pjl_seq"].clear()
    NS["_user_stopped"].clear()
    NS["worker_epoch"] = 1
    _Log.lines[:] = []


def mk_project(pid, name="Проект", archived=0, deleted=0):
    conn_p.execute("INSERT INTO projects (id, name, is_deleted, is_archived) VALUES (?,?,?,?)",
                   (pid, name, deleted, archived))
    conn_p.commit()


def mk_file(fid, project_id, filename):
    conn_p.execute("INSERT INTO project_files (id, project_id, filename) VALUES (?,?,?)",
                   (fid, project_id, filename))
    conn_p.commit()


def mk_part(part_id, project_id, name, required=10, printed=0, on_plate=1, file_id=None):
    conn_p.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
                   "VALUES (?,?,?,?,?,?)", (part_id, project_id, name, name.lower(), required, printed))
    if file_id:
        conn_p.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) "
                       "VALUES (?,?,?,?,?)", ("lnk_" + part_id, project_id, file_id, part_id, on_plate))
    conn_p.commit()


def printed_qty(part_id):
    r = conn_p.execute("SELECT printed_qty FROM project_parts WHERE id=?", (part_id,)).fetchone()
    return int(r["printed_qty"]) if r else None


def sessions(printer_id=None):
    """Порядок — СТРОГО по вставке (rowid): started_at имеет секундную точность, и два запуска
    одной секунды иначе перемешались бы, а тест проверяет именно «первый» и «второй»."""
    if printer_id:
        return [dict(r) for r in conn_p.execute(
            "SELECT * FROM printer_job_sessions WHERE printer_id=? ORDER BY rowid", (printer_id,))]
    return [dict(r) for r in conn_p.execute("SELECT * FROM printer_job_sessions ORDER BY rowid")]


def jobs(printer_id=None):
    if printer_id:
        return [dict(r) for r in conn_p.execute(
            "SELECT * FROM project_print_jobs WHERE printer_id=? ORDER BY rowid", (printer_id,))]
    return [dict(r) for r in conn_p.execute("SELECT * FROM project_print_jobs ORDER BY rowid")]


def tick(printer_id, kind_state, filename="", progress=None, elapsed=None, dispatch_job="",
         cancelled=False, connected=True):
    """Один такт телеметрии: фикстура состояния -> сырая строка прошивки -> наблюдение."""
    kind = NS["printer_kinds"][printer_id]
    raw = FIXTURES[kind].get(kind_state, kind_state)
    CLOCK[0] += 1.5
    NS["p_states"][printer_id] = {"status_raw": raw, "status": raw, "percent": progress,
                                  "total_time": None}
    return observe(printer_id, raw, filename, connected=connected, progress=progress,
                   elapsed_seconds=elapsed, dispatch_job_id=dispatch_job,
                   user_cancelled=(cancelled or printer_id in NS["_user_stopped"]))


def base_project(printer=P_BAMBU, filename="Part_A.gcode.3mf", required=10, on_plate=1):
    reset_all()
    mk_project("prj1", "Альфа")
    mk_file("f1", "prj1", filename)
    mk_part("pt1", "prj1", "Деталь А", required=required, on_plate=on_plate, file_id="f1")
    return filename


print("=" * 95)
print("A. ИСТОРИЧЕСКАЯ РЕГРЕССИЯ: перезапуск во время печати больше не теряет учёт")
print("=" * 95)

FN = base_project()
tick(P_BAMBU, "printing", "Part_A", progress=5)
_j = jobs(P_BAMBU)
check("A1. печать с экрана распознана: создана ровно одна запись задания", len(_j) == 1)
check("A2. деталь показана печатающейся на КОНКРЕТНОМ принтере",
      _j and _j[0]["printer_id"] == P_BAMBU and _j[0]["status"] == "dispatched")
check("A3. создана ровно одна сессия наблюдаемого физического запуска", len(sessions(P_BAMBU)) == 1)
check("A4. количество готовых пока НЕ изменилось (печать ещё идёт)", printed_qty("pt1") == 0)

# Перезапуск программы во время печати: память процесса пуста, БД сохраняется.
NS["_pjl_session_cache"].clear()
NS["_pjl_seq"].clear()
_acc, _kept = NS["_pjl_recover_on_start"]()
_n_stale = NS["_pjob_recover_stale"]()
check("A5. КРИТИЧНО: перезапуск НЕ гасит задание идущей печати (прежде гасил всегда)",
      _n_stale == 0 and jobs(P_BAMBU)[0]["status"] == "dispatched")
check("A6. перезапуск сохранил активный запуск и ничего не досчитал", _kept == 1 and _acc == 0)
tick(P_BAMBU, "printing", "Part_A", progress=60)
check("A7. КРИТИЧНО: после перезапуска ВТОРАЯ запись на ту же печать не создаётся",
      len(jobs(P_BAMBU)) == 1 and len(sessions(P_BAMBU)) == 1)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("A8. КРИТИЧНО: успешное завершение увеличило количество готовых ровно на один",
      printed_qty("pt1") == 1)
check("A9. root cause закрыт assertion'ом: уборка щадит задания живых наблюдаемых запусков",
      "_pjl_live_job_ids()" in _fn_src("_pjob_recover_stale"))

print()
print("=" * 95)
print("B. НОРМАЛИЗАЦИЯ: адаптер отдаёт наблюдение и НЕ трогает бизнес-состояние")
print("=" * 95)

check("B1. поддерживаемые адаптеры ровно четыре (bambu/klipper/flashforge/creality — с 12.10.2026 Creality без Moonraker)",
      PJL.SUPPORTED_ADAPTERS == frozenset(("bambu", "klipper", "flashforge", "creality")))
_obs = PJL.observe("p", "bambu", "RUNNING", "X.gcode")
check("B2. наблюдение — это PrinterJobObservation с нормализованным состоянием",
      isinstance(_obs, PJL.PrinterJobObservation) and _obs.normalized_state == PJL.STATE_PRINTING)
check("B3. неизвестное состояние прошивки -> unknown (никогда не покой и не успех)",
      PJL.normalize_state("bambu", "TELEPORTING") == PJL.STATE_UNKNOWN
      and PJL.normalize_state("klipper", "quantum") == PJL.STATE_UNKNOWN
      and PJL.normalize_state("flashforge", "hyperdrive") == PJL.STATE_UNKNOWN)
_malformed_ok = True
for bad in (None, 123, b"bytes", [], {}, "", "   ", object()):
    try:
        PJL.observe("p", "bambu", bad, bad if isinstance(bad, str) else "")
    except Exception:
        _malformed_ok = False
check("B4. мусорный/битый payload не роняет разбор (телеметрия не валит опрос)", _malformed_ok)
check("B5. без имени файла привязки к проекту не происходит",
      PJL.match_observation(PJL.observe("p", "bambu", "RUNNING", ""), candidates=[
          {"file_id": "f", "project_id": "p", "filename": "A.gcode", "has_parts": True}]).state
      == PJL.MATCH_NONE)
check("B6. completed / cancelled / failed различаются",
      PJL.normalize_state("klipper", "complete") == PJL.STATE_COMPLETED
      and PJL.normalize_state("klipper", "cancelled") == PJL.STATE_CANCELLED
      and PJL.normalize_state("klipper", "error") == PJL.STATE_FAILED)
check("B7. пауза терминалом НЕ является",
      PJL.STATE_PAUSED not in PJL.TERMINAL_STATES and PJL.STATE_PAUSED in PJL.ACTIVE_STATES)
check("B8. offline терминалом НЕ является и успехом тем более",
      PJL.STATE_OFFLINE not in PJL.TERMINAL_STATES and PJL.STATE_OFFLINE not in PJL.SUCCESS_STATES)
check("B9. idle терминалом НЕ является (исчезновение задания не доказывает успех)",
      PJL.STATE_IDLE not in PJL.TERMINAL_STATES)
check("B10. успех — ровно одно состояние: completed", PJL.SUCCESS_STATES == frozenset((PJL.STATE_COMPLETED,)))
check("B11. потеря связи даёт offline независимо от строки прошивки",
      PJL.normalize_state("bambu", "RUNNING", connected=False) == PJL.STATE_OFFLINE)
check("B12. чистый движок не импортирует server.py, БД и сеть",
      all(s not in open(os.path.join(REPO, "app", "printer_job_lifecycle.py"), encoding="utf-8").read()
          for s in ("import server", "sqlite3", "import socket", "urllib", "requests")))
check("B13. адаптер не может объявить успех действием оператора (override успехом запрещён)",
      PJL.observe("p", "bambu", "RUNNING", "A", state_override=PJL.STATE_COMPLETED).normalized_state
      == PJL.STATE_PRINTING)

print()
print("=" * 95)
print("C. ВНЕШНЯЯ ПЕЧАТЬ: базовый жизненный цикл")
print("=" * 95)

base_project()
_job = tick(P_BAMBU, "printing", "Part_A", progress=1)
check("C1. внешняя печать создаёт наблюдаемую сессию", len(sessions(P_BAMBU)) == 1)
check("C2. однозначное совпадение связывает файл/деталь проекта",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_UNIQUE_FILENAME and bool(_job))
check("C3. принтер сохранён в задании", jobs(P_BAMBU)[0]["printer_id"] == P_BAMBU)
tick(P_BAMBU, "printing", "Part_A", progress=42)
check("C4. прогресс обновляется в той же сессии", sessions(P_BAMBU)[0]["progress"] == 42)
check("C5. повторный опрос не создаёт новый запуск", len(sessions(P_BAMBU)) == 1)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("C6. завершение увеличивает готовое ровно на один", printed_qty("pt1") == 1)
tick(P_BAMBU, "completed", "Part_A", progress=100)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("C7. КРИТИЧНО: повторный терминальный отчёт НЕ увеличивает счётчик", printed_qty("pt1") == 1)
check("C8. запуск помечен учтённым", sessions(P_BAMBU)[0]["lifecycle_state"] == PJL.SESSION_ACCOUNTED)

base_project()
tick(P_KLIP, "printing", "Part_A", progress=10)
tick(P_KLIP, "cancelled", "Part_A", progress=10)
check("C9. КРИТИЧНО: отмена НЕ увеличивает количество готовых", printed_qty("pt1") == 0)
check("C10. отменённый запуск закрыт как cancelled",
      sessions(P_KLIP)[0]["lifecycle_state"] == PJL.SESSION_TERMINAL_CANCELLED)

base_project()
tick(P_KLIP, "printing", "Part_A", progress=10)
tick(P_KLIP, "failed", "Part_A", progress=10)
check("C11. КРИТИЧНО: сбой НЕ увеличивает количество готовых", printed_qty("pt1") == 0)

base_project()
tick(P_FF, "printing", "Part_A", progress=50)
tick(P_FF, "idle", "")
check("C12. КРИТИЧНО: покой БЕЗ доказательства завершения не считается успехом", printed_qty("pt1") == 0)
check("C13. такой запуск закрыт как «исход неизвестен», а не как успех",
      sessions(P_FF)[0]["lifecycle_state"] == PJL.SESSION_TERMINAL_UNKNOWN)

print()
print("=" * 95)
print("D. ПОВТОРНАЯ ПЕЧАТЬ ТОГО ЖЕ ФАЙЛА С ЭКРАНА ПРИНТЕРА (главный сценарий)")
print("=" * 95)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "completed", "Part_A", progress=100)
_run1 = sessions(P_BAMBU)[0]["observed_run_id"]
check("D1. первый запуск учтён один раз", printed_qty("pt1") == 1)
tick(P_BAMBU, "idle", "")
tick(P_BAMBU, "printing", "Part_A", progress=2)
_ss = sessions(P_BAMBU)
check("D2. КРИТИЧНО: повтор того же файла создаёт НОВЫЙ физический запуск",
      len(_ss) == 2 and _ss[1]["observed_run_id"] != _run1)
check("D3. новый запуск снова связан с той же деталью проекта",
      _ss[1]["match_state"] in (PJL.MATCH_REMOTE_MAPPING, PJL.MATCH_UNIQUE_FILENAME))
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("D4. КРИТИЧНО: второе завершение увеличивает готовое ещё ровно на один", printed_qty("pt1") == 2)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("D5. третий дублирующий терминал ничего не меняет", printed_qty("pt1") == 2)

base_project()
tick(P_KLIP, "printing", "Part_A", progress=5)
tick(P_KLIP, "cancelled", "Part_A")
tick(P_KLIP, "printing", "Part_A", progress=3)
check("D6. повтор ПОСЛЕ отмены создаёт новый запуск", len(sessions(P_KLIP)) == 2)
tick(P_KLIP, "completed", "Part_A", progress=100)
check("D7. и он засчитывается один раз", printed_qty("pt1") == 1)

base_project()
tick(P_KLIP, "printing", "Part_A", progress=5)
tick(P_KLIP, "failed", "Part_A")
tick(P_KLIP, "printing", "Part_A", progress=3)
check("D8. повтор ПОСЛЕ сбоя создаёт новый запуск", len(sessions(P_KLIP)) == 2)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=30)
tick(P_BAMBU, "paused", "Part_A", progress=30)
check("D9. КРИТИЧНО: пауза НЕ создаёт новый запуск", len(sessions(P_BAMBU)) == 1)
check("D10. пауза не терминал: запуск остаётся живым",
      sessions(P_BAMBU)[0]["lifecycle_state"] == PJL.SESSION_PAUSED)
tick(P_BAMBU, "printing", "Part_A", progress=31)
check("D11. КРИТИЧНО: возобновление НЕ создаёт новый запуск", len(sessions(P_BAMBU)) == 1)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("D12. запуск с паузой засчитан ровно один раз", printed_qty("pt1") == 1)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=40)
NS["worker_epoch"] = 2                       # переподключение адаптера: новая эпоха связи
tick(P_BAMBU, "printing", "Part_A", progress=41)
check("D13. КРИТИЧНО: переподключение НЕ создаёт дубликат запуска", len(sessions(P_BAMBU)) == 1)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("D14. после переподключения завершение засчитано один раз", printed_qty("pt1") == 1)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=40, )
_before = sessions(P_BAMBU)[0]["observed_run_id"]
NS["_pjl_session_cache"].clear(); NS["_pjl_seq"].clear()      # перезапуск программы
NS["_pjl_recover_on_start"]()
tick(P_BAMBU, "printing", "Part_A", progress=45)
check("D15. КРИТИЧНО: перезапуск НЕ создаёт новый запуск",
      len(sessions(P_BAMBU)) == 1 and sessions(P_BAMBU)[0]["observed_run_id"] == _before)

# Запоздавший/retained пакет прошлой печати несёт ВЫСОКИЙ прогресс: печать была почти закончена.
# Настоящая повторная печать начинается сначала. Это и есть доказательство старта.
base_project()
tick(P_BAMBU, "printing", "Part_A", progress=90)
tick(P_BAMBU, "completed", "Part_A", progress=100)
tick(P_BAMBU, "printing", "Part_A", progress=88)     # запоздавший пакет прошлой печати
check("D16. КРИТИЧНО: устаревший «печатается» после завершения НЕ создаёт новый запуск",
      len(sessions(P_BAMBU)) == 1 and printed_qty("pt1") == 1)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("D16b. КРИТИЧНО: «липкий» FINISH после устаревшего пакета НЕ засчитывает деталь второй раз",
      printed_qty("pt1") == 1)
tick(P_BAMBU, "printing", "Part_A", progress=2)       # настоящий новый запуск: прогресс с нуля
check("D17. настоящая повторная печать (прогресс начался заново) новый запуск СОЗДАЁТ",
      len(sessions(P_BAMBU)) == 2)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("D17b. и она засчитывается ещё ровно на один", printed_qty("pt1") == 2)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=70)
tick(P_BAMBU, "completed", "Part_A", progress=100)
tick(P_BAMBU, "preparing", "Part_A")                  # Bambu начинает следующую печать с PREPARE
check("D18a. подготовка к печати после завершения — доказательство НОВОГО запуска",
      len(sessions(P_BAMBU)) == 2)

base_project()
tick(P_KLIP, "printing", "Part_A", progress=10)
_s_before = len(sessions(P_KLIP))
tick(P_KLIP, "printing", "Part_A", progress=10)        # ровно тот же снимок (повторный опрос)
check("D18. одинаковый повторный снимок не создаёт новый запуск и не плодит событий",
      len(sessions(P_KLIP)) == _s_before)

print()
print("=" * 95)
print("E. СОПОСТАВЛЕНИЕ: fail-closed при любой неоднозначности")
print("=" * 95)

reset_all()
mk_project("prjA", "А"); mk_file("fA", "prjA", "Same.gcode.3mf"); mk_part("ptA", "prjA", "A", file_id="fA")
mk_project("prjB", "Б"); mk_file("fB", "prjB", "Same.gcode.3mf"); mk_part("ptB", "prjB", "B", file_id="fB")
tick(P_BAMBU, "printing", "Same", progress=5)
check("E1. КРИТИЧНО: одинаковое имя в двух проектах -> ambiguous, а не догадка",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_AMBIGUOUS)
check("E2. КРИТИЧНО: при неоднозначности проектное задание НЕ создаётся", len(jobs()) == 0)
tick(P_BAMBU, "completed", "Same", progress=100)
check("E3. КРИТИЧНО: неоднозначная печать не изменила счётчики ни одного проекта",
      printed_qty("ptA") == 0 and printed_qty("ptB") == 0)

reset_all()
mk_project("prjA", "А"); mk_file("fA", "prjA", "Alpha.gcode.3mf"); mk_part("ptA", "prjA", "A", file_id="fA")
tick(P_BAMBU, "printing", "Alph", progress=5)
check("E4. КРИТИЧНО: похожее имя (Alph vs Alpha) НЕ совпадает — нечёткого сопоставления нет",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_NONE and len(jobs()) == 0)
reset_all()
mk_project("prjA", "А"); mk_file("fA", "prjA", "Alpha.gcode.3mf"); mk_part("ptA", "prjA", "A", file_id="fA")
tick(P_BAMBU, "printing", "AlphaBeta", progress=5)
check("E5. КРИТИЧНО: совпадение по подстроке НЕ засчитывается",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_NONE)

reset_all()
mk_project("prjA", "А"); mk_file("fA", "prjA", "Alpha.gcode.3mf"); mk_part("ptA", "prjA", "A", file_id="fA")
tick(P_BAMBU, "printing", "ALPHA.GCODE.3MF", progress=5)
check("E6. регистр и расширение нормализуются по контракту (то же имя совпадает)",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_UNIQUE_FILENAME)

check("E7. Unicode NFC: разложенная и составная формы дают один ключ",
      PJL.normalize_filename("Пе́чать.gcode") == PJL.normalize_filename(
          __import__("unicodedata").normalize("NFC", "Пе́чать.gcode")))
check("E8. путь безопасно сводится к имени файла (traversal не протекает)",
      PJL.normalize_filename("../../etc/Part_A.gcode") == PJL.normalize_filename("Part_A.gcode")
      == PJL.normalize_filename("C:\\\\Users\\\\x\\\\Part_A.gcode"))
check("E9. ярлык плиты (plate_1) идентификатором файла не считается",
      PJL.normalize_filename("plate_1") == "" and PJL.normalize_filename("Plate 12.gcode") == "")
check("E10. одно лишь расширение совпадением не является",
      PJL.normalize_filename("A.gcode") != PJL.normalize_filename("B.gcode"))

reset_all()
mk_project("prjA", "А", deleted=1); mk_file("fA", "prjA", "Del.gcode.3mf"); mk_part("ptA", "prjA", "A", file_id="fA")
tick(P_BAMBU, "printing", "Del", progress=5)
check("E11. КРИТИЧНО: удалённый проект кандидатом не является",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_NONE and len(jobs()) == 0)

reset_all()
mk_project("prjA", "А", archived=1); mk_file("fA", "prjA", "Arc.gcode.3mf"); mk_part("ptA", "prjA", "A", file_id="fA")
tick(P_BAMBU, "printing", "Arc", progress=5)
check("E12. архивный проект кандидатом не является (контракт зафиксирован)",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_NONE)

reset_all()
mk_project("prjA", "А"); mk_file("fA", "prjA", "NoParts.gcode.3mf")     # файл БЕЗ деталей
tick(P_BAMBU, "printing", "NoParts", progress=5)
check("E13. файл без деталей не создаёт ложную связь (засчитывать нечего)",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_NONE)

reset_all()
tick(P_BAMBU, "printing", "Unknown_File", progress=5)
check("E14. печать НЕИЗВЕСТНОГО файла не привязывается к проекту",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_NONE and len(jobs()) == 0)
check("E15. неопознанная печать всё равно наблюдается (видна на принтере)",
      sessions(P_BAMBU)[0]["lifecycle_state"] == PJL.SESSION_ACTIVE_UNMATCHED)

# Приоритет: прошлая отправка ИМЕННО на этот принтер важнее совпадения имени в другом проекте.
reset_all()
mk_project("prjA", "А"); mk_file("fA", "prjA", "Dup.gcode.3mf"); mk_part("ptA", "prjA", "A", file_id="fA")
mk_project("prjB", "Б"); mk_file("fB", "prjB", "Dup.gcode.3mf"); mk_part("ptB", "prjB", "B", file_id="fB")
conn_p.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, file_norm, "
               "snapshot_json, status, counted_at) VALUES ('old','prjA','fA',?,'Dup.gcode.3mf','dupgcode3mf','[]','finished','2024-01-01')",
               (P_BAMBU,))
conn_p.commit()
tick(P_BAMBU, "printing", "Dup", progress=5)
check("E16. КРИТИЧНО: прошлая отправка на ЭТОТ принтер разрешает неоднозначность имени",
      sessions(P_BAMBU)[0]["match_state"] == PJL.MATCH_REMOTE_MAPPING
      and sessions(P_BAMBU)[0]["matched_project_id"] == "prjA")
tick(P_BAMBU, "completed", "Dup", progress=100)
check("E17. и засчитывается ИМЕННО тот проект, куда файл отправляли",
      printed_qty("ptA") == 1 and printed_qty("ptB") == 0)

reset_all()
mk_project("prjA", "А"); mk_file("fA", "prjA", "Disp.gcode.3mf"); mk_part("ptA", "prjA", "A", file_id="fA")
_dj = NS["create_project_print_job"]("prjA", "fA", P_KLIP, "Disp.gcode.3mf")
tick(P_KLIP, "printing", "Disp", progress=5, dispatch_job=_dj)
check("E18. КРИТИЧНО: корреляция с запуском Farm Manager имеет высший приоритет и НЕ дублирует задание",
      len(jobs(P_KLIP)) == 1 and sessions(P_KLIP)[0]["project_print_job_id"] == _dj
      and sessions(P_KLIP)[0]["match_state"] == PJL.MATCH_DISPATCH)
tick(P_KLIP, "completed", "Disp", progress=100)
check("E19. обычная печать из Farm Manager по-прежнему учитывается ровно один раз", printed_qty("ptA") == 1)

check("E20. адаптер не может объявить доверенным произвольный project_id",
      "project_id" not in PJL.PrinterJobObservation.__slots__
      and "file_id" not in PJL.PrinterJobObservation.__slots__)

# Прямые проверки ЧИСТОГО сопоставителя: серверный предфильтр здесь не участвует, поэтому любое
# послабление правил в самом движке становится видно.
_cands_fuzzy = [{"file_id": "f", "project_id": "p", "filename": "Alpha.gcode.3mf", "has_parts": True}]
check("E21. КРИТИЧНО (движок): префикс имени НЕ совпадает",
      PJL.match_observation(PJL.observe("pr", "bambu", "RUNNING", "Alph"),
                            candidates=_cands_fuzzy).state == PJL.MATCH_NONE)
check("E22. КРИТИЧНО (движок): имя-надмножество НЕ совпадает",
      PJL.match_observation(PJL.observe("pr", "bambu", "RUNNING", "AlphaBeta"),
                            candidates=_cands_fuzzy).state == PJL.MATCH_NONE)
check("E23. КРИТИЧНО (движок): два одинаковых имени в разных проектах -> ambiguous",
      PJL.match_observation(PJL.observe("pr", "bambu", "RUNNING", "Alpha"), candidates=[
          {"file_id": "f1", "project_id": "p1", "filename": "Alpha.gcode.3mf", "has_parts": True},
          {"file_id": "f2", "project_id": "p2", "filename": "Alpha.3mf", "has_parts": True},
      ]).state == PJL.MATCH_AMBIGUOUS)
check("E24. КРИТИЧНО (движок): точное совпадение единственного кандидата -> matched",
      PJL.match_observation(PJL.observe("pr", "bambu", "RUNNING", "Alpha"),
                            candidates=_cands_fuzzy).state == PJL.MATCH_UNIQUE_FILENAME)
check("E25. КРИТИЧНО (движок): прошлая отправка НА ДРУГОЙ принтер не используется",
      PJL.match_observation(PJL.observe("pr", "bambu", "RUNNING", "Alpha"), candidates=[], remote_sends=[
          {"printer_id": "other", "project_id": "p", "file_id": "f", "remote_filename": "Alpha.gcode.3mf"}
      ]).state == PJL.MATCH_NONE)

# ── Идентичность физического запуска по native job id (сильный признак прошивки) ────────────────
# Сегодня ни один из трёх протоколов его не сообщает, но контракт обязан быть проверен: как
# только прошивка начнёт его отдавать, решать должен ИМЕННО он, а не имя файла.
_sess_native = {"lifecycle_state": PJL.SESSION_ACTIVE_MATCHED, "filename_normalized": "parta",
                "native_job_id": "JOB-1", "connection_epoch": 1, "sequence": 1,
                "last_fingerprint": "", "progress": 40}
_d_same = PJL.decide(_sess_native, PJL.observe("pr", "bambu", "RUNNING", "Part_A",
                                               native_job_id="JOB-1", sequence=2,
                                               connection_epoch=1, progress=41))
check("E26. КРИТИЧНО: тот же native job id -> ТОТ ЖЕ запуск", _d_same.action == PJL.ACTION_CONTINUE)
_d_new = PJL.decide(_sess_native, PJL.observe("pr", "bambu", "RUNNING", "Part_A",
                                              native_job_id="JOB-2", sequence=2,
                                              connection_epoch=1, progress=3))
check("E27. КРИТИЧНО: то же имя, но ДРУГОЙ native job id -> НОВЫЙ запуск",
      _d_new.action == PJL.ACTION_OPEN and _d_new.reason == PJL.REASON_NEW_NATIVE_JOB)
_sess_named = dict(_sess_native, native_job_id="")
_d_file = PJL.decide(_sess_named, PJL.observe("pr", "bambu", "RUNNING", "Other_Part",
                                              sequence=2, connection_epoch=1, progress=3))
check("E28. без native id новый запуск определяется по смене файла",
      _d_file.action == PJL.ACTION_OPEN and _d_file.reason == PJL.REASON_NEW_FILE)
_sess_term = {"lifecycle_state": PJL.SESSION_ACCOUNTED, "filename_normalized": "parta",
              "native_job_id": "", "connection_epoch": 1, "sequence": 5,
              "last_fingerprint": "", "progress": 100}
_d_rep = PJL.decide(_sess_term, PJL.observe("pr", "bambu", "RUNNING", "Part_A",
                                            sequence=6, connection_epoch=1, progress=2))
check("E29. КРИТИЧНО: без native id повтор определяется по переходу терминал -> новый старт",
      _d_rep.action == PJL.ACTION_OPEN and _d_rep.reason == PJL.REASON_NEW_AFTER_TERMINAL)

print()
print("=" * 95)
print("F. ОДНОВРЕМЕННОСТЬ И ИДЕМПОТЕНТНОСТЬ")
print("=" * 95)

base_project(required=10)
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_KLIP, "printing", "Part_A", progress=5)
check("F1. два принтера печатают одну деталь -> два независимых запуска",
      len(sessions(P_BAMBU)) == 1 and len(sessions(P_KLIP)) == 1
      and sessions(P_BAMBU)[0]["observed_run_id"] != sessions(P_KLIP)[0]["observed_run_id"])
tick(P_BAMBU, "completed", "Part_A", progress=100)
tick(P_KLIP, "completed", "Part_A", progress=100)
check("F2. завершение каждого учтено ровно один раз (итого 2)", printed_qty("pt1") == 2)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=5)
_sid = sessions(P_BAMBU)[0]["id"]
_jid = sessions(P_BAMBU)[0]["project_print_job_id"]
_r1 = NS["finish_project_print_job"](_jid, session_id=_sid)
_r2 = NS["finish_project_print_job"](_jid, session_id=_sid)
check("F3. КРИТИЧНО: два одновременных терминала -> учёт ровно один",
      _r1 is True and _r2 is False and printed_qty("pt1") == 1)
check("F4. счётчик и отметка учёта меняются вместе (одна транзакция)",
      sessions(P_BAMBU)[0]["completion_accounted_at"] != ""
      and jobs(P_BAMBU)[0]["counted_at"] != "")

_dup = None
try:
    conn_p.execute("INSERT INTO printer_job_sessions (id, observed_run_id, printer_id) VALUES (?,?,?)",
                   ("pjs_x", sessions(P_BAMBU)[0]["observed_run_id"], P_BAMBU))
    conn_p.commit()
    _dup = False
except sqlite3.IntegrityError:
    conn_p.rollback()
    _dup = True
check("F5. КРИТИЧНО: БД не даёт создать два запуска с одним observed_run_id", _dup is True)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=5)
_sid = sessions(P_BAMBU)[0]["id"]
_r = NS["finish_project_print_job"]("no_such_job", session_id=_sid)
check("F6. учёт по несуществующему заданию не проходит и ничего не портит",
      _r is False and printed_qty("pt1") == 0
      and sessions(P_BAMBU)[0]["completion_accounted_at"] == "")

print()
print("=" * 95)
print("G. ПОРЯДОК СОБЫТИЙ, RECONNECT, УСТАРЕВШИЕ ПАКЕТЫ")
print("=" * 95)

base_project()
tick(P_KLIP, "printing", "Part_A", progress=70)
tick(P_KLIP, "printing", "Part_A", progress=80)
_seq_now = NS["_pjl_seq"][(P_KLIP, NS["worker_epoch"])]
NS["_pjl_seq"][(P_KLIP, NS["worker_epoch"])] = 0        # следующий такт получит МЕНЬШИЙ номер
tick(P_KLIP, "printing", "Part_A", progress=40)
check("G1. КРИТИЧНО: устаревший пакет прогресса игнорируется (80 не откатывается в 40)",
      sessions(P_KLIP)[0]["progress"] == 80)
NS["_pjl_seq"][(P_KLIP, NS["worker_epoch"])] = _seq_now

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=50)
tick(P_BAMBU, "completed", "Part_A", progress=100)
_lc = sessions(P_BAMBU)[0]["lifecycle_state"]
tick(P_BAMBU, "printing", "Part_A", progress=99)
check("G2. КРИТИЧНО: старый пакет не возвращает завершённый запуск в печать",
      sessions(P_BAMBU)[0]["lifecycle_state"] == _lc and printed_qty("pt1") == 1)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=50)
tick(P_BAMBU, "printing", "Part_A", progress=50, connected=False)
check("G3. КРИТИЧНО: потеря связи НЕ завершает запуск",
      sessions(P_BAMBU)[0]["lifecycle_state"] in PJL.SESSION_ACTIVE_STATES)
tick(P_BAMBU, "printing", "Part_A", progress=55)
check("G4. возврат связи продолжает ТОТ ЖЕ запуск", len(sessions(P_BAMBU)) == 1)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("G5. и завершение засчитано один раз", printed_qty("pt1") == 1)

base_project()
tick(P_FF, "printing", "Part_A", progress=50)
tick(P_FF, "idle", "")
check("G6. КРИТИЧНО: offline -> idle не считается успешным завершением", printed_qty("pt1") == 0)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=30, elapsed=600)
tick(P_BAMBU, "printing", "Part_A", progress=31, elapsed=10)   # сброс времени ВНУТРИ той же печати
check("G7. сброс времени внутри активного запуска не обязан создавать новый запуск",
      len(sessions(P_BAMBU)) == 1)

base_project()
tick(P_BAMBU, "unknown_future", "Part_A")
check("G8. неизвестное будущее состояние прошивки не открывает и не закрывает запуск",
      len(sessions(P_BAMBU)) == 0)
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "unknown_future", "Part_A")
check("G9. неизвестное состояние посреди печати не завершает её",
      sessions(P_BAMBU)[0]["lifecycle_state"] in PJL.SESSION_ACTIVE_STATES and printed_qty("pt1") == 0)

print()
print("=" * 95)
print("H. ВОССТАНОВЛЕНИЕ ПОСЛЕ ПЕРЕЗАПУСКА")
print("=" * 95)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=50)
NS["_pjl_session_cache"].clear(); NS["_pjl_seq"].clear()
_a, _k = NS["_pjl_recover_on_start"]()
check("H1. перезапуск во время печати: запуск сохранён, ничего не досчитано", _k == 1 and _a == 0)
check("H2. назначение принтера восстановлено", NS["_pjl_active_session_job"](P_BAMBU) != "")

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=50)
_sid = sessions(P_BAMBU)[0]["id"]
conn_p.execute("UPDATE printer_job_sessions SET lifecycle_state=? WHERE id=?",
               (PJL.SESSION_TERMINAL_COMPLETED, _sid))
conn_p.commit()
NS["_pjl_session_cache"].clear()
_a, _k = NS["_pjl_recover_on_start"]()
check("H3. КРИТИЧНО: успех, доказанный ДО перезапуска, досчитывается ровно один раз",
      _a == 1 and printed_qty("pt1") == 1)
_a2, _k2 = NS["_pjl_recover_on_start"]()
check("H4. КРИТИЧНО: повторное восстановление НЕ считает второй раз",
      _a2 == 0 and printed_qty("pt1") == 1)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=50)
tick(P_BAMBU, "completed", "Part_A", progress=100)
NS["_pjl_session_cache"].clear()
_a, _k = NS["_pjl_recover_on_start"]()
check("H5. перезапуск ПОСЛЕ учтённого завершения не считает повторно",
      _a == 0 and printed_qty("pt1") == 1)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=50)
NS["_pjl_session_cache"].clear(); NS["_pjl_seq"].clear()
NS["_pjl_recover_on_start"]()
tick(P_BAMBU, "idle", "")
check("H6. КРИТИЧНО: после перезапуска покой без доказательства не объявляется успехом",
      printed_qty("pt1") == 0)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=50)
NS["_pjl_session_cache"].clear(); NS["_pjl_seq"].clear()
NS["_pjl_recover_on_start"]()
tick(P_BAMBU, "printing", "Other_File", progress=5)
check("H7. пока backend был выключен начался ДРУГОЙ файл -> это новый запуск",
      len(sessions(P_BAMBU)) == 2)
check("H8. прежний запуск закрыт как «исход неизвестен», а не как успех",
      sessions(P_BAMBU)[0]["lifecycle_state"] == PJL.SESSION_TERMINAL_UNKNOWN and printed_qty("pt1") == 0)

print()
print("=" * 95)
print("I. УЧЁТ ПРОЕКТА")
print("=" * 95)

base_project(required=10)
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "completed", "Part_A", progress=100)
_p = dict(conn_p.execute("SELECT * FROM project_parts WHERE id='pt1'").fetchone())
check("I1. КРИТИЧНО: «нужно» не изменилось", _p["required_qty"] == 10)
check("I2. «готово» выросло ровно на один физический запуск", _p["printed_qty"] == 1)

base_project(required=10, on_plate=4)
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("I3. КРИТИЧНО: несколько экземпляров на плите засчитаны по сохранённой раскладке, а не «1»",
      printed_qty("pt1") == 4)

base_project(required=2)
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "completed", "Part_A", progress=100)
tick(P_BAMBU, "idle", "")
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "completed", "Part_A", progress=100)
tick(P_BAMBU, "idle", "")
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "completed", "Part_A", progress=100)
_p = dict(conn_p.execute("SELECT * FROM project_parts WHERE id='pt1'").fetchone())
check("I4. перепроизводство сохраняет фактическую историю и НЕ портит план",
      _p["printed_qty"] == 3 and _p["required_qty"] == 2)

base_project()
_fid_before = conn_p.execute("SELECT id FROM project_files WHERE project_id='prj1'").fetchone()["id"]
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "completed", "Part_A", progress=100)
check("I5. идентификаторы файла и детали не меняются учётом",
      conn_p.execute("SELECT id FROM project_files WHERE project_id='prj1'").fetchone()["id"] == _fid_before
      and conn_p.execute("SELECT COUNT(*) c FROM project_parts WHERE id='pt1'").fetchone()["c"] == 1)
check("I6. раскладка файл->деталь не меняется учётом",
      conn_p.execute("SELECT COUNT(*) c FROM project_file_parts WHERE file_id='f1'").fetchone()["c"] == 1)
check("I7. путь папки проекта в сопоставлении не участвует (identity — file_id/project_id)",
      "stored_path" not in _fn_src("_pjl_match_candidates"))

base_project()
tick(P_KLIP, "printing", "Part_A", progress=5)
tick(P_KLIP, "cancelled", "Part_A")
check("I8. отмена снимает активность и НЕ трогает «готово»",
      jobs(P_KLIP)[0]["status"] == "cancelled" and printed_qty("pt1") == 0)

base_project()
tick(P_BAMBU, "printing", "Part_A", progress=5)
NS["_user_stopped"].add(P_BAMBU)
tick(P_BAMBU, "printing", "Part_A", progress=6)     # прошивка ещё рапортует печать
check("I9. КРИТИЧНО: остановка оператором закрывает запуск без увеличения «готово»",
      printed_qty("pt1") == 0
      and sessions(P_BAMBU)[0]["lifecycle_state"] == PJL.SESSION_TERMINAL_CANCELLED)
NS["_user_stopped"].clear()
check("I10. Bambu не различает отмену и сбой в протоколе — консервативно НЕ считаем успехом",
      PJL.normalize_state("bambu", "cancelled") == PJL.STATE_UNKNOWN
      and PJL.normalize_state("bambu", "FAILED") == PJL.STATE_FAILED)

print()
print("=" * 95)
print("J. МАТРИЦА АДАПТЕРОВ: одинаковые правила для КАЖДОГО транспорта")
print("=" * 95)

for _pid, _kind in ((P_BAMBU, "bambu"), (P_KLIP, "klipper"), (P_FF, "flashforge")):
    fx = FIXTURES[_kind]
    base_project()
    tick(_pid, "idle", "")
    check("J[%s].1 покой не открывает запуск" % _kind, len(sessions(_pid)) == 0)
    tick(_pid, "printing", "Part_A", progress=5)
    check("J[%s].2 печать открывает ровно один запуск и связывает с проектом" % _kind,
          len(sessions(_pid)) == 1 and sessions(_pid)[0]["project_print_job_id"] != "")
    if "paused" in fx:
        tick(_pid, "paused", "Part_A", progress=5)
        check("J[%s].3 пауза не создаёт новый запуск и не терминал" % _kind,
              len(sessions(_pid)) == 1 and sessions(_pid)[0]["lifecycle_state"] == PJL.SESSION_PAUSED)
        tick(_pid, "printing", "Part_A", progress=6)
    tick(_pid, "printing", "Part_A", progress=7, connected=False)
    check("J[%s].4 потеря связи не завершает запуск" % _kind,
          sessions(_pid)[0]["lifecycle_state"] in PJL.SESSION_ACTIVE_STATES)
    tick(_pid, "printing", "Part_A", progress=8)
    check("J[%s].5 reconnect не создаёт дубликат" % _kind, len(sessions(_pid)) == 1)
    tick(_pid, "completed", "Part_A", progress=100)
    check("J[%s].6 завершение засчитано ровно один раз" % _kind, printed_qty("pt1") == 1)
    tick(_pid, "completed", "Part_A", progress=100)
    check("J[%s].7 дублирующий терминал игнорируется" % _kind, printed_qty("pt1") == 1)
    tick(_pid, "idle", "")
    tick(_pid, "printing", "Part_A", progress=3)
    check("J[%s].8 повтор того же файла — НОВЫЙ запуск" % _kind, len(sessions(_pid)) == 2)
    tick(_pid, "completed", "Part_A", progress=100)
    check("J[%s].9 повтор засчитан ещё ровно на один" % _kind, printed_qty("pt1") == 2)
    # Отмена/сбой — только там, где прошивка их различает.
    base_project()
    if "cancelled" in fx:
        tick(_pid, "printing", "Part_A", progress=5)
        tick(_pid, "cancelled", "Part_A")
        check("J[%s].10 отмена НЕ увеличивает «готово»" % _kind, printed_qty("pt1") == 0)
    else:
        tick(_pid, "printing", "Part_A", progress=5)
        tick(_pid, "failed", "Part_A")
        check("J[%s].10 прошивка не различает отмену и сбой -> консервативно НЕ считаем успехом"
              % _kind, printed_qty("pt1") == 0)
    base_project()
    tick(_pid, "printing", "Part_A", progress=5)
    tick(_pid, "failed", "Part_A")
    check("J[%s].11 сбой НЕ увеличивает «готово»" % _kind, printed_qty("pt1") == 0)
    base_project()
    _ok = True
    for _bad in ("", "   ", "???", "\x00", "12345"):
        try:
            tick(_pid, _bad, "Part_A")
        except Exception:
            _ok = False
    check("J[%s].12 битый/пустой payload не роняет наблюдение" % _kind, _ok)
    check("J[%s].13 счётчики от битого payload не изменились" % _kind, printed_qty("pt1") == 0)

print()
print("=" * 95)
print("K. ГРАНИЦЫ, СОБЫТИЯ И ПРИВАТНОСТЬ")
print("=" * 95)

check("K1. КРИТИЧНО: все три адаптера ходят через ОДНУ точку наблюдения (handle_state)",
      _SRV.count("handle_state(pid, st, cfn)") == 1
      and _SRV.count("handle_state(pid, ns, fn)") == 2
      and _SRV.count("_obs_job = observe_printer_job(") == 1)
check("K2. КРИТИЧНО: наблюдение вызывается из handle_state — общий путь для всех принтеров",
      "observe_printer_job(" in _fn_src("handle_state"))
check("K3. в ядре нет ветвления бизнес-логики учёта по модели принтера",
      not re.search(r'if\s+.*type\s*==\s*"bambu".*printed_qty', _SRV))
check("K4. printed_qty меняется ровно в одном месте ядра — finish_project_print_job",
      len(re.findall(r"UPDATE project_parts SET printed_qty=printed_qty\+", _SRV)) == 1)
check("K5. чистый движок НЕ меняет счётчики проекта",
      "printed_qty" not in open(os.path.join(REPO, "app", "printer_job_lifecycle.py"), encoding="utf-8").read())
_pjl_src = open(os.path.join(REPO, "app", "printer_job_lifecycle.py"), encoding="utf-8").read()
check("K6. движок не выполняет SQL и не открывает соединения",
      not re.search(r"\b(INSERT|UPDATE|DELETE|SELECT)\b", _pjl_src))

_joined = "\n".join(_Log.lines)
base_project()
tick(P_BAMBU, "printing", "Part_A", progress=5)
tick(P_BAMBU, "completed", "Part_A", progress=100)
_joined = "\n".join(_Log.lines)
check("K7. события жизненного цикла публикуются", "[LIFECYCLE]" in _joined
      and "job_session_created" in _joined and "completion_accounted" in _joined)
check("K8. КРИТИЧНО: имя файла в события не попадает",
      "Part_A" not in _joined and "part_a" not in _joined.lower())
check("K9. КРИТИЧНО: в события не попадают адреса, серийные номера и коды доступа",
      not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", _joined)
      and "access_code" not in _joined and "password" not in _joined and "token" not in _joined)
check("K10. сырой отчёт протокола целиком в события не попадает", "payload" not in _joined.lower())
check("K11. внутренний идентификатор запуска наружу уходит только укороченным",
      all(s["observed_run_id"] not in _joined for s in sessions(P_BAMBU)))
check("K12. наблюдение не создаёт публичной поверхности: таблица сессий не отдаётся маршрутом",
      not re.search(r'@app\.\w+\([^)]*\)\s*\n[^\n]*\n?[^\n]*printer_job_sessions', _SRV))
_routes = len(re.findall(r'@app\.(get|post|patch|delete|websocket)\(', _SRV))
check("K13. количество маршрутов ядра ожидаемое (2.823 +printer-files; 2.825 +select-for-print; 2.831 +printer-sort-mode ×2; 2.833 +klipper-prestart ×2; 2.839: +klipper-contract-report; 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.927: +3 пометки принтера и настройки фермы)", _routes == 209)   #; 2.947 +staging/sync; 2.948 -pending-printable; 2.978 storage/data project->admin; 2.979 +files/locate; 2.980 +3 net-capture, +4 printer-discovery; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
check("K14. КРИТИЧНО: миграция ТОЛЬКО аддитивная — таблица создаётся, ничего не удаляется",
      "DROP TABLE" not in _SRV
      and "CREATE TABLE IF NOT EXISTS printer_job_sessions" in _SRV
      and "ALTER TABLE printer_job_sessions" not in _SRV
      and "ALTER TABLE project_print_jobs" not in _SRV)
check("K14b. существующие таблицы учёта не пересоздаются и не переносятся",
      "DROP INDEX" not in _SRV and "INSERT INTO project_parts SELECT" not in _SRV)
check("K15. автоматическая отправка остаётся выключенной",
      re.search(r"^DISPATCH_ENABLED = False", open(os.path.join(REPO, "app", "project_orchestrator.py"),
                                                   encoding="utf-8").read(), re.M) is not None)
check("K16. транспорт остаётся выключенным",
      re.search(r"^TRANSPORT_ENABLED = False", open(os.path.join(REPO, "app", "project_orchestrator.py"),
                                                    encoding="utf-8").read(), re.M) is not None)
check("K17. тест не открывал сокетов и не запускал подпроцессов", not _VIOLATIONS)
check("K18. в сессии не хранятся ни сырой отчёт, ни адрес, ни секрет",
      not any(c in _ddl("printer_job_sessions") for c in ("payload", "raw_report", "ip ", "token", "access_code")))
check("K19. sentinel живёт только в оснастке теста", SENTINEL not in _SRV and SENTINEL not in _pjl_src)
check("K20. КРИТИЧНО: старый (ненадёжный) путь привязки экранной печати больше НЕ вызывается",
      _SRV.count("_scr = _screen_print_match_project(") == 0
      and "create_project_print_job(_scr[0]" not in _SRV)

print()
print("=" * 95)
_verdict[0] = True
print("Проверок выполнено: %d, провалено: %d" % (_checked, fail))
if fail:
    print("FAIL: %d проверок провалено" % fail)
else:
    print("PASS: внешняя и повторная печать синхронизируются одинаково на всех поддерживаемых "
          "адаптерах; повтор того же файла — отдельный физический запуск; успех засчитывается "
          "ровно один раз; отмена/сбой/покой/потеря связи успехом не считаются; перезапуск "
          "программы не теряет и не дублирует запуск.")
conn_p.close()
raise SystemExit(1 if fail else 0)
