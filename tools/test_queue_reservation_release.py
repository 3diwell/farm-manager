# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Тесты освобождения reservation в очереди печати и recovery (Alpha 2.771, дефект Q-1).
#
# БЕЗ сервера/принтеров/сети/рабочей БД: из server.py ИЗВЛЕКАЮТСЯ ДОСЛОВНЫЕ блоки
# (менеджер отправок + блок очереди печати) и исполняются со стабами. БД — in-memory sqlite.
# Реальные _do_project2_file_print/part_print заменены управляемыми заглушками.
#
# CHARACTERIZATION: до Alpha 2.771 ветка «recovered-элемент не прошёл проверку» выполняла
# только `pass` — элемент уже удалён из print_queue, а его reservation навсегда оставалась
# в _PrintSendManager._resv. Принтер после этого считался занятым до перезапуска программы.
#
# Запуск: python tools/test_queue_reservation_release.py   (0 = все проверки пройдены)
# ============================================================================
import asyncio
import json as _json
import os
import sqlite3
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


# ── извлечь дословные блоки production-кода ─────────────────────────────────
MGR_BLOCK = SRC[SRC.index("from concurrent.futures import ThreadPoolExecutor as _SendPool"):
                SRC.index("\ndef _send_watchdog_loop")]
Q_BLOCK = SRC[SRC.index("print_queue = []"):SRC.index('\n@app.get("/api/print-queue")')]

check("A0. извлечён дословный блок менеджера отправок",
      "class _PrintSendManager" in MGR_BLOCK and "def cancel_reserved" in MGR_BLOCK)
check("A1. извлечён дословный блок очереди печати",
      "async def _print_queue_worker" in Q_BLOCK and "def _recovered_launch_ok" in Q_BLOCK)

_uidc = [0]


def _uid(prefix=""):
    _uidc[0] += 1
    return str(prefix) + format(_uidc[0], "06d")


class _Log(object):
    """Стаб журнала: копит записи, чтобы проверить факт (и отсутствие) сообщений."""

    def __init__(self):
        self.lines = []

    def _rec(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(str(a))

    debug = info = warning = error = _rec


def make_env(send_result=None, raise_in_start=False, via_manager=False):
    """Свежее окружение: менеджер, in-memory БД, очередь, стабы запуска печати.

    via_manager=True — стаб ведёт себя как настоящий part_print из очереди: адоптирует
    reservation через begin_or_adopt_tracked и реально прогоняет отправку через менеджер.
    """
    log = _Log()
    ns_mgr = {
        "threading": threading, "time": time, "os": os, "re": __import__("re"),
        "_uid": _uid, "p_states": {}, "last_seen": {}, "STALE_FAIL_S": 60,
        "log": log, "_exc_brief": (lambda: "stub"),
    }
    exec(MGR_BLOCK, ns_mgr)
    mgr = ns_mgr["_PrintSendManager"]()

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE print_launch_queue (id TEXT PRIMARY KEY, batch_id TEXT DEFAULT '', "
                 "printer_id TEXT, printer_name TEXT DEFAULT '', flow TEXT DEFAULT 'quick', "
                 "job_ref TEXT DEFAULT '', due_ts REAL, status TEXT DEFAULT 'pending', "
                 "attempts INTEGER DEFAULT 0, last_error TEXT DEFAULT '', payload TEXT DEFAULT '', "
                 "created_at REAL, updated_at REAL, recovery_eligible INTEGER DEFAULT 1)")
    conn.commit()

    calls = {"start": 0, "last": None}

    def _ok_send_callable(progress):
        progress(stage="uploading")
        progress(command_ok=True)
        return {"status": "ok"}

    async def _fake_part_print(data):
        calls["start"] += 1
        calls["last"] = data
        if raise_in_start:
            raise RuntimeError("boom")
        if via_manager:
            # как настоящий part_print при _from_queue: адопт своей reservation + реальная отправка
            _r, _jid = mgr.begin_or_adopt_tracked(
                str(data.get("printer_id")), str(data.get("printer_id")), "a.gcode", "queue",
                _ok_send_callable, None, data.get("_send_job_id"))
            calls["adopted_job_id"] = _jid
            return _r or {"status": "ok"}
        return send_result if send_result is not None else {"status": "ok"}

    async def _fake_project_print(*a, **k):
        calls["start"] += 1
        calls["last"] = {"args": a, "kw": k}
        if raise_in_start:
            raise RuntimeError("boom")
        return send_result if send_result is not None else {"status": "ok"}

    ns_q = {
        "threading": threading, "time": time, "os": os, "asyncio": asyncio,
        "_uid": _uid, "log": log, "_exc_brief": (lambda: "stub"),
        "lock_pr": threading.Lock(), "conn_pr": conn, "p_states": {},
        "_send_mgr": mgr, "_jsonmod": _json,
        "part_print": _fake_part_print, "_do_project2_file_print": _fake_project_print,
        "_hold_public": (lambda h: h), "_print_queue_persist": (lambda *a, **k: None),
    }
    exec(Q_BLOCK, ns_q)
    return {"mgr": mgr, "conn": conn, "ns": ns_q, "log": log, "calls": calls}


def add_durable(env, did, pid, status="pending", eligible=1):
    ts = time.time()
    env["conn"].execute(
        "INSERT INTO print_launch_queue (id, printer_id, due_ts, status, created_at, updated_at, recovery_eligible) "
        "VALUES (?,?,?,?,?,?,?)", (did, pid, ts, status, ts, ts, eligible))
    env["conn"].commit()


def durable_status(env, did):
    r = env["conn"].execute("SELECT status, last_error FROM print_launch_queue WHERE id=?", (did,)).fetchone()
    return (r["status"], r["last_error"]) if r else (None, None)


def run_worker_once(env, seconds=1.6):
    """Прогнать production-цикл воркера ровно столько, чтобы он обработал готовый элемент."""
    async def _run():
        task = asyncio.ensure_future(env["ns"]["_print_queue_worker"]())
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    asyncio.new_event_loop().run_until_complete(_run()) if False else asyncio.run(_run())


def enqueue_recovered(env, pid="P1", did="plq_1", due_offset=-1.0, recovered=True):
    """Положить в очередь восстановленный элемент с СОБСТВЕННОЙ reservation (как recovery/continue)."""
    ok, sjid, _ = env["mgr"].reserve(pid, pid, "a.gcode", "queue")
    item = {"id": "1", "durable_id": did, "send_job_id": sjid, "printer_id": pid,
            "printer_name": pid, "flow": "quick", "due_ts": time.time() + due_offset,
            "gcode_file": "a.gcode", "source": "quick", "part_name": None,
            "project_id": None, "file_id": None, "ams_slot": None, "print_opts": None}
    if recovered:
        item["recovered"] = True
    env["ns"]["print_queue"].append(item)
    return ok, sjid, item


print("=== Q-1: освобождение reservation в очереди и recovery ===")

# ═══ 1. Recovered + принтер НЕ IDLE: запуск не вызван, durable=attention, reservation свободна ═══
env = make_env()
add_durable(env, "plq_1", "P1", status="pending", eligible=1)
ok, sjid, _ = enqueue_recovered(env, "P1", "plq_1")
env["ns"]["p_states"]["P1"] = {"status": "RUNNING"}      # принтер занят → запускать нельзя
check("1a. reservation взята на постановку", ok and "P1" in env["mgr"].reserved_ids())
run_worker_once(env)
check("1b. запуск печати НЕ вызывался", env["calls"]["start"] == 0)
check("1c. элемент снят с очереди", len(env["ns"]["print_queue"]) == 0)
check("1d. durable → recovery_attention", durable_status(env, "plq_1")[0] == "recovery_attention")
check("1e. [ХАРАКТЕРИЗАЦИЯ Q-1] reservation ОСВОБОЖДЕНА (принтер снова доступен)",
      "P1" not in env["mgr"].reserved_ids())

# ═══ 2. Recovered + durable уже НЕ pending: запуск не вызван, reservation свободна, статус не перетёрт ═══
env = make_env()
add_durable(env, "plq_2", "P2", status="canceled", eligible=1)
_, sjid2, _ = enqueue_recovered(env, "P2", "plq_2")
env["ns"]["p_states"]["P2"] = {"status": "IDLE"}
run_worker_once(env)
check("2a. запуск НЕ вызывался", env["calls"]["start"] == 0)
check("2b. существующий durable-статус НЕ перезаписан", durable_status(env, "plq_2")[0] == "canceled")
check("2c. reservation освобождена", "P2" not in env["mgr"].reserved_ids())

# ═══ 3. Ошибка чтения durable precheck: запуск не вызван, reservation свободна, цикл жив ═══
env = make_env()
add_durable(env, "plq_3", "P3", status="pending", eligible=1)
_, sjid3, _ = enqueue_recovered(env, "P3", "plq_3")
env["conn"].close()                                       # любое чтение теперь бросает
run_worker_once(env)
check("3a. запуск НЕ вызывался при ошибке чтения", env["calls"]["start"] == 0)
check("3b. reservation освобождена", "P3" not in env["mgr"].reserved_ids())
check("3c. ошибка чтения залогирована", any("precheck" in s for s in env["log"].lines))

# ═══ 4. Успешный recovered launch: adopt того же job, reservation НЕ снимается досрочно ═══
env = make_env(via_manager=True)
add_durable(env, "plq_4", "P4", status="pending", eligible=1)
_, sjid4, _ = enqueue_recovered(env, "P4", "plq_4")
env["ns"]["p_states"]["P4"] = {"status": "IDLE"}
run_worker_once(env)
check("4a. запуск вызван ровно один раз", env["calls"]["start"] == 1)
check("4b. adopt переиспользовал ТОТ ЖЕ send_job_id (второго job не создано)",
      (env["calls"]["last"] or {}).get("_send_job_id") == sjid4
      and env["calls"].get("adopted_job_id") == sjid4
      and len(env["mgr"].snapshot()["jobs"]) == 1)
check("4c. reservation НЕ освобождена досрочно (ждём телеметрию)", "P4" in env["mgr"].reserved_ids())
check("4d. durable → sent", durable_status(env, "plq_4")[0] == "sent")
env["mgr"].note_printer_running("P4")                     # телеметрия подтвердила старт
check("4e. после RUNNING reservation штатно снята", "P4" not in env["mgr"].reserved_ids())

# ═══ 5. Hold появился после enqueue: отправка не идёт, reservation освобождается ═══
env = make_env(send_result={"status": "error", "reason": "printer_held"})
add_durable(env, "plq_5", "P5", status="pending", eligible=1)
_, sjid5, _ = enqueue_recovered(env, "P5", "plq_5", recovered=False)   # обычный элемент
run_worker_once(env)
check("5a. durable → failed", durable_status(env, "plq_5")[0] == "failed")
check("5b. reservation освобождена — принтер снова доступен", "P5" not in env["mgr"].reserved_ids())
_ok5, _, _ = env["mgr"].reserve("P5", "P5", "b.gcode", "queue")
check("5c. принтер реально можно занять заново", _ok5)

# ═══ 6. Ошибка ВНУТРИ уже запущенного worker: release ровно один раз, доп. cleanup безопасен ═══
env = make_env()
mgr = env["mgr"]
okr, jid6, _ = mgr.reserve("P6", "P6", "c.gcode", "queue")


def _failing_send(progress):
    progress(stage="uploading")
    return {"status": "error", "reason": "upload failed"}


r6 = mgr.run_tracked(jid6, _failing_send)
check("6a. worker сам перевёл job в failed", (r6 or {}).get("status") == "error")
check("6b. reservation освобождена самим worker'ом", "P6" not in mgr.reserved_ids())
check("6c. повторный cancel_reserved — безопасный no-op (False, без исключения)",
      mgr.cancel_reserved(jid6, "queue launch not started") is False)

# ═══ 7. Успешная отправка: reservation держится до подтверждения ═══
env = make_env()
mgr = env["mgr"]
_, jid7, _ = mgr.reserve("P7", "P7", "d.gcode", "queue")


def _ok_send(progress):
    progress(stage="uploading")
    progress(command_ok=True)
    return {"status": "ok"}


mgr.run_tracked(jid7, _ok_send)
check("7a. после успешной отправки reservation ещё удерживается", "P7" in mgr.reserved_ids())
check("7b. состояние — waiting_confirmation",
      next(j["state"] for j in mgr.snapshot()["jobs"] if j["job_id"] == jid7) == "waiting_confirmation")

# ═══ 13. Чужой job: cleanup одного элемента не трогает reservation другого ═══
env = make_env()
mgr = env["mgr"]
_, jA, _ = mgr.reserve("PA", "PA", "a", "queue")
_, jB, _ = mgr.reserve("PB", "PB", "b", "queue")
mgr.cancel_reserved(jA, "queue launch not started")
check("13. освобождение своего job не затронуло чужой",
      "PA" not in mgr.reserved_ids() and "PB" in mgr.reserved_ids())

# ═══ 14. Повторный cleanup идемпотентен ═══
check("14. повторный cancel_reserved — no-op без исключения",
      mgr.cancel_reserved(jA, "again") is False)

# ═══ 15/16. Отмена очереди и durable-cancel продолжают освобождать reservation ═══
env = make_env()
mgr = env["mgr"]
_, sjidC, itemC = enqueue_recovered(env, "PC", "plq_c", due_offset=600.0, recovered=False)
check("15a. элемент стоит в очереди с будущим стартом", len(env["ns"]["print_queue"]) == 1)
_rel = [q.get("send_job_id") for q in env["ns"]["print_queue"]]
env["ns"]["print_queue"][:] = []                       # как делает api_print_queue_cancel
for _sj in _rel:
    mgr.cancel_reserved(_sj, "queue canceled")
check("15b. отмена очереди освободила reservation", "PC" not in mgr.reserved_ids())

# ═══ 17. Воркер продолжает работать после отказавшего элемента ═══
env = make_env(send_result={"status": "error", "reason": "boom"})
add_durable(env, "plq_a", "PX", status="pending", eligible=1)
add_durable(env, "plq_b", "PY", status="pending", eligible=1)
enqueue_recovered(env, "PX", "plq_a", due_offset=-2.0, recovered=False)
enqueue_recovered(env, "PY", "plq_b", due_offset=-1.0, recovered=False)
run_worker_once(env, seconds=2.6)                      # два тика: по одному элементу за тик
check("17a. обработаны ОБА элемента (цикл не умер после отказа)", env["calls"]["start"] == 2)
check("17b. обе reservation освобождены",
      "PX" not in env["mgr"].reserved_ids() and "PY" not in env["mgr"].reserved_ids())

# ═══ Статические проверки production-кода ═══
print("--- статические проверки ---")
check("S1. в воркере нет «немой» ветки pass для recovered-элемента",
      "if q.get(\"recovered\") and not _recovered_launch_ok(q):\n                pass" not in SRC)
check("S2. воркер освобождает reservation через cancel_reserved",
      "cancel_reserved" in Q_BLOCK)
check("S3. есть набор диспетчеризуемых отправок под print_queue_lock",
      "_queue_dispatching_send_job_ids" in Q_BLOCK)
check("S4. есть снимок активных queue-reservation для watchdog",
      "def _queue_active_send_job_ids" in Q_BLOCK)
check("S5. менеджер умеет подметать orphan queue-reservation",
      "def sweep_queue_orphans" in MGR_BLOCK)

# Порядок блокировок: snapshot берётся ДО вызова менеджера, print_queue_lock отпущен.
_wd = SRC[SRC.index("def _send_watchdog_loop"):SRC.index("@app.get(\"/api/send-jobs\")")]
check("S6. watchdog сначала берёт снимок очереди, потом зовёт менеджер",
      "_queue_active_send_job_ids()" in _wd and
      _wd.index("_queue_active_send_job_ids()") < _wd.index("sweep_queue_orphans"))
def code_only(text):
    """Код без комментариев и докстрок: пояснения намеренно упоминают print_queue_lock
    (объясняя, что менеджер его НЕ берёт), и наивный поиск принял бы их за живой код."""
    import ast
    import io
    import tokenize
    try:
        tree = ast.parse(text)
    except Exception:
        return text
    blank = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                blank.add(ln)
    rows = ["\n" if (i + 1) in blank else r for i, r in enumerate(text.splitlines(True))]
    txt = "".join(rows)
    try:
        cuts = {}
        for tok in tokenize.generate_tokens(io.StringIO(txt).readline):
            if tok.type == tokenize.COMMENT:
                cuts.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))
        rows = txt.splitlines(True)
        for row, spans in cuts.items():
            s = rows[row - 1]
            for a, b in sorted(spans, reverse=True):
                s = s[:a] + s[b:]
            rows[row - 1] = s
        return "".join(rows)
    except Exception:
        return txt


_mgr_code = code_only(MGR_BLOCK)
check("S7. менеджер отправок НИГДЕ не берёт print_queue_lock (обратного порядка нет в коде)",
      "print_queue_lock" not in _mgr_code and len(_mgr_code) < len(MGR_BLOCK))

# ═══ 18. Поведенческая проверка: нет дедлока print_queue_lock ⇄ _send_mgr._lock ═══
env = make_env()
mgr = env["mgr"]
ns = env["ns"]
_stop = threading.Event()
_errors = []


def _enqueuer():
    """Как api_print_queue_enqueue / recovery-continue: reserve ПОД print_queue_lock."""
    try:
        i = 0
        while not _stop.is_set():
            i += 1
            pid = "PD%d" % (i % 5)
            with ns["print_queue_lock"]:
                ok, sj, _ = mgr.reserve(pid, pid, "x.gcode", "queue")
                if ok:
                    ns["print_queue"].append({"id": str(i), "printer_id": pid, "send_job_id": sj,
                                              "due_ts": time.time() + 3600})
            with ns["print_queue_lock"]:
                keep = [q for q in ns["print_queue"] if q["printer_id"] != pid]
                gone = [q for q in ns["print_queue"] if q["printer_id"] == pid]
                ns["print_queue"][:] = keep
            for q in gone:
                mgr.cancel_reserved(q["send_job_id"], "test")
    except Exception as e:
        _errors.append(repr(e))


def _sweeper():
    """Как _send_watchdog_loop: снимок под print_queue_lock, затем менеджер под своим _lock."""
    try:
        while not _stop.is_set():
            active = ns["_queue_active_send_job_ids"]()
            mgr.sweep_queue_orphans(active)
    except Exception as e:
        _errors.append(repr(e))


_t1 = threading.Thread(target=_enqueuer, daemon=True)
_t2 = threading.Thread(target=_sweeper, daemon=True)
_t1.start(); _t2.start()
time.sleep(2.0)
_stop.set()
_t1.join(timeout=5.0); _t2.join(timeout=5.0)
check("18. нет дедлока между print_queue_lock и _send_mgr._lock (оба потока завершились)",
      not _t1.is_alive() and not _t2.is_alive() and not _errors)

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
