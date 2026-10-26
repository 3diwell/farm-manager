# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.848 — очередь признаёт успехом ТОЛЬКО подтверждённый запуск.

ЧТО ЗАЩИЩАЕТ. 17.08.2026 на ферме из 9 принтеров восьмой запустился, девятый — нет, а владелец
увидел «orphan queue reservation released» и не понял причины. Разбор журнала показал: запуск
остановил хук склада ответом {'status': 'low_filament'}, но проверка успеха в `_start_queued_print`
была ЧЁРНЫМ списком:

    ok = not (isinstance(r, dict) and r.get("status") in ("error", "incompatible"))

`low_filament` в списке отказов не значился, поэтому отказ прошёл как успех. Последствия цепочкой:
в журнал записалось «start X11: ok», в durable-очередь — «отправлено», worker счёл отправку
состоявшейся и НЕ вернул reservation, а через секунду её снял watchdog брошенных броней — с тем
самым непонятным сообщением. Печать при этом не начиналась вовсе.

ЧТО ПРОВЕРЯЕТСЯ. Правило признания успеха: успех — ТОЛЬКО status == 'ok' (так отвечают ОБА потока
очереди, quick и project). Любой другой ответ — отказ, после которого worker возвращает reservation
и пишет причину. Проверяются и уже известные отказы, и `low_filament`, и произвольный будущий
статус: чёрный список пропустил бы последний так же, как пропустил low_filament.

Правило берётся ИЗ ИСХОДНИКА (разбор AST реального выражения в server.py), а не переписывается в
тест: копия правила проверяла бы сама себя и осталась бы зелёной, даже если в продукте всё сломано.

БЕЗОПАСНОСТЬ. server.py НЕ импортируется (импорт поднял бы приложение); файл только читается.
Ни принтеров, ни сети. 16.10.2026 (R-117): исход СТРОКИ очереди ожидания проверяется исполнением
настоящей цепочки (воркер очереди запусков -> part_print -> менеджер отправок) на базе в памяти;
отправка на принтер подменена функцией, которая только отвечает.

Запуск:  python tools/test_queue_launch_verdict.py      (0 = правило верное)
"""
import ast
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO, "server.py")
SENTINEL = "QUEUE_LAUNCH_VERDICT_SENTINEL_2_848"

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def extract_ok_expr():
    """Достаёт из server.py выражение, которым `_start_queued_print` признаёт запуск успешным."""
    src = io.open(SERVER, encoding="utf-8", errors="surrogateescape").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "_start_queued_print":
            continue
        for st in ast.walk(node):
            if isinstance(st, ast.Assign) and len(st.targets) == 1:
                t = st.targets[0]
                if isinstance(t, ast.Name) and t.id == "ok":
                    return ast.unparse(st.value)
    return None


EXPR = extract_ok_expr()
check("1. правило признания успеха найдено в server.py (_start_queued_print)", bool(EXPR), EXPR)

if EXPR:
    print("   правило: %s" % EXPR)

    def verdict(r):
        """Вычисляет НАСТОЯЩЕЕ выражение из server.py на подставленном ответе."""
        return bool(eval(EXPR, {"isinstance": isinstance, "dict": dict, "str": str}, {"r": r}))

    # ── успех: так отвечают оба потока очереди ────────────────────────────────
    check("2. подтверждённый запуск (quick) считается успехом",
          verdict({"status": "ok", "accepted": True, "job_id": "send_1"}) is True)
    check("3. подтверждённый запуск (project, с pjob_id) считается успехом",
          verdict({"status": "ok", "pjob_id": "pj_1", "job_id": "pj_1"}) is True)

    # ── отказы: каждый обязан быть отказом ────────────────────────────────────
    for st, why in (("low_filament", "отказ склада — ИМЕННО ОН прошёл как успех 17.08.2026"),
                    ("error", "обычная ошибка отправки"),
                    ("incompatible", "файл нарезан под другой принтер"),
                    ("printer_held", "принтер удерживается другим владельцем"),
                    ("printer_send_busy", "принтер уже занят другой отправкой")):
        check("4. отказ '%s' НЕ считается успехом (%s)" % (st, why),
              verdict({"status": st, "reason": "x"}) is False)

    # ── будущее: неизвестный отказ обязан быть отказом, а не «успехом по умолчанию» ──
    check("5. НЕИЗВЕСТНЫЙ будущий статус не считается успехом (корень дефекта: чёрный список "
          "пропускал всё, чего в нём нет)",
          verdict({"status": "some_future_block", "reason": "x"}) is False)
    check("6. ответ без статуса не считается успехом", verdict({"reason": "x"}) is False)
    check("7. не-словарь не считается успехом", verdict(None) is False and verdict("ok") is False)

    # ── проверка не вакуумная: ПРЕЖНЕЕ правило обязано провалить пункты 4-6 ────
    OLD = "not (isinstance(r, dict) and r.get('status') in ('error', 'incompatible'))"

    def old_verdict(r):
        return bool(eval(OLD, {"isinstance": isinstance, "dict": dict}, {"r": r}))

    _old_missed = [st for st in ("low_filament", "printer_held", "some_future_block")
                   if old_verdict({"status": st}) is True]
    check("8. НЕ ВАКУУМ: прежнее (чёрное) правило действительно пропускало эти отказы как успех — "
          "значит проверка меряет разницу, а не сама себя",
          _old_missed == ["low_filament", "printer_held", "some_future_block"], _old_missed)
    check("9. НЕ ВАКУУМ: прежнее правило при этом верно признавало успех — дефект был только "
          "в неполноте списка отказов",
          old_verdict({"status": "ok"}) is True)

# ══ 16.10.2026 (R-117): исход СТРОКИ ОЧЕРЕДИ ОЖИДАНИЯ — по признаку отправки и по сторожу старта ══
#  Исполняется НАСТОЯЩАЯ цепочка: воркер очереди запусков -> _start_queued_print -> part_print (вырезан из
#  server.py) -> менеджер отправок (блок вырезан целиком) -> исход строки. Отправка на принтер подменена
#  функцией, которая только отвечает; ни сети, ни принтеров, база — в памяти.
print("--- R-117: строка очереди ожидания после запуска ---")
import asyncio as _aio                     # noqa: E402
import json as _json                       # noqa: E402
import sqlite3 as _sql                     # noqa: E402
import tempfile as _tf                     # noqa: E402
import threading as _th                    # noqa: E402
import time as _time                       # noqa: E402
from typing import Any, Dict               # noqa: E402,F401 — аннотации part_print

_SRC = io.open(SERVER, encoding="utf-8", errors="surrogateescape").read()
_MGR = _SRC[_SRC.index("from concurrent.futures import ThreadPoolExecutor as _SendPool"):_SRC.index("\ndef _send_watchdog_loop")]
_QB = _SRC[_SRC.index("print_queue = []"):_SRC.index('\n@app.get("/api/print-queue")')]
_pp = next(n for n in ast.parse(_SRC).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "part_print")
_PP = ast.get_source_segment(_SRC, _pp)


class _QLog(object):
    def __getattr__(self, _n):
        return lambda *a, **k: None


_seq = [0]


def _uid(prefix=""):
    _seq[0] += 1
    return "%s%06d" % (prefix, _seq[0])


_tmpd = _tf.mkdtemp(prefix="qlv117_")
_gfile = os.path.join(_tmpd, "a.gcode")
io.open(_gfile, "w", encoding="utf-8").write("G28\n")


def _env(send_answer):
    """Свежая цепочка: менеджер, очередь, part_print. send_answer — что «ответит принтер»."""
    ns_m = {"threading": _th, "time": _time, "os": os, "re": __import__("re"), "_uid": _uid,
            "p_states": {}, "last_seen": {}, "STALE_FAIL_S": 60, "log": _QLog(), "_exc_brief": (lambda: "stub")}
    exec(_MGR, ns_m)                                                   # noqa: S102 — свой исходник
    mgr = ns_m["_PrintSendManager"]()
    conn = _sql.connect(":memory:", check_same_thread=False)
    conn.row_factory = _sql.Row
    conn.execute("CREATE TABLE printers (id TEXT, name TEXT, type TEXT, ip TEXT, port INTEGER, token TEXT)")
    conn.execute("INSERT INTO printers VALUES ('P1','K2-01','klipper','10.0.0.99',7125,'FIXTURE_TOKEN')")
    conn.execute("CREATE TABLE print_launch_queue (id TEXT PRIMARY KEY, printer_id TEXT, status TEXT, "
                 "payload TEXT DEFAULT '{}', attempts INTEGER DEFAULT 0, last_error TEXT DEFAULT '', "
                 "updated_at REAL, recovery_eligible INTEGER DEFAULT 1)")
    conn.execute("CREATE TABLE queue_wait (id TEXT PRIMARY KEY, state TEXT, note TEXT, updated_at REAL)")
    conn.execute("INSERT INTO queue_wait VALUES ('rw1','launching','запускается на K2-01',0)")
    conn.commit()

    def _mk_send(*a, **k):
        def _send(progress):
            r = dict(send_answer)
            if r.get("status") == "ok":
                progress(command_ok=True)          # файл и команда приняты — ждём подтверждения старта
            return r
        return _send
    ns_q = {"threading": _th, "time": _time, "os": os, "asyncio": _aio, "_uid": _uid, "log": _QLog(),
            "_exc_brief": (lambda: "stub"), "lock_pr": _th.RLock(), "conn_pr": conn, "p_states": {},
            "_send_mgr": mgr, "_jsonmod": _json, "Dict": Dict, "Any": Any, "JSONResponse": dict,
            "_do_project2_file_print": None, "_hold_public": (lambda h: h),
            "_print_queue_persist": (lambda *a, **k: None),
            "_staging_path": (lambda fname, part=None: _gfile), "_hold_block": (lambda pid: None),
            "_check_file_compatible": (lambda *a: (True, "")), "_launch_feed_plan": (lambda *a, **k: {}),
            "_run_pre_print_hooks": (lambda *a, **k: None), "print_source": {}, "plan_part": {},
            "_mk_file_send": _mk_send, "_send_accept_response": (lambda *a, **k: {"status": "ok"}),
            "_qw_auto_ok": (lambda rid: None), "_qw_auto_inflight": set(), "_qw_auto_bump": (lambda *a: None)}
    exec(_QB, ns_q)                                                    # noqa: S102
    exec(_PP, ns_q)                                                    # noqa: S102
    ok, sj, _w = mgr.reserve("P1", "K2-01", "a.gcode", "queue")
    ns_q["print_queue"].append({"id": "1", "durable_id": "", "send_job_id": sj, "printer_id": "P1",
                                "printer_name": "K2-01", "flow": "quick", "due_ts": _time.time() - 1,
                                "gcode_file": "a.gcode", "source": "quick", "part_name": "", "qw_id": "rw1",
                                "ams_slot": None, "print_opts": None})

    async def _run():
        task = _aio.ensure_future(ns_q["_print_queue_worker"]())
        await _aio.sleep(1.6)
        task.cancel()
        try:
            await task
        except BaseException:
            pass
    _aio.run(_run())
    row = conn.execute("SELECT state, note FROM queue_wait WHERE id='rw1'").fetchone()
    return {"mgr": mgr, "ns_m": ns_m, "conn": conn, "row": (row["state"], row["note"])}


#  (а) отправка сказала «ничего не ушло» (sent=False) с текстом, которого нет в списке причин.
_NOCONN = "No connection to the printer to upload the file. Make sure the printer is powered on and online."
_e1 = _env({"status": "error", "sent": False, "reason": _NOCONN})
check("10. (R-117) нет связи при загрузке (sent=False) — строка вернулась в ОЖИДАНИЕ с причиной кодом, "
      "а не «требует внимания»",
      _e1["row"][0] == "waiting" and str(_e1["row"][1] or "").startswith("not_started:"), _e1["row"])
#  НЕ ВАКУУМ: тот же текст без признака — исход неясен, «требует внимания» (как прежде).
_e2 = _env({"status": "error", "reason": _NOCONN})
check("11. НЕ ВАКУУМ: тот же отказ без признака sent — «требует внимания» (команда могла уйти)",
      _e2["row"][0] == "attention", _e2["row"])
#  (б) принтер принял файл, а печать не началась: сторож отправок через 45 секунд устойчивого покоя.
_e3 = _env({"status": "ok"})
check("12. отправка принята — строка закрыта «запущено»", _e3["row"][0] == "done", _e3["row"])
_e3["ns_m"]["p_states"]["P1"] = {"status": "IDLE"}
_e3["ns_m"]["last_seen"]["P1"] = _time.time()
_e3["mgr"].tick(now=_time.time() + 120)
_r3 = _e3["conn"].execute("SELECT state, note FROM queue_wait WHERE id='rw1'").fetchone()
check("13. (R-117) принтер принял файл, но печать не началась — строка «требует внимания» (start_not_confirmed), "
      "сама не перезапускается",
      (_r3["state"], _r3["note"]) == ("attention", "start_not_confirmed")
      and not _e3["mgr"].reserved_ids(), tuple(_r3))
_e4 = _env({"status": "ok"})
_e4["ns_m"]["p_states"]["P1"] = {"status": "RUNNING"}
_e4["ns_m"]["last_seen"]["P1"] = _time.time()
_e4["mgr"].note_printer_running("P1")
_e4["mgr"].tick(now=_time.time() + 120)
_r4 = _e4["conn"].execute("SELECT state FROM queue_wait WHERE id='rw1'").fetchone()
check("14. НЕ ВАКУУМ: печать пошла — строка так и остаётся «запущено»", _r4["state"] == "done", tuple(_r4))

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    print("НЕ ПРОЙДЕНО:")
    for f in _fail:
        print("   - %s" % f)
sys.exit(1 if _fail else 0)
