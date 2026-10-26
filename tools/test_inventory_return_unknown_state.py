# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""29.09.2026 — склад не возвращает филамент, пока исход печати неизвестен (склад 1.7.31).

ЖАЛОБА (аудит 26.09.2026). После перезапуска программы посреди печати остаток катушки вырастал:
склад «возвращал» неизрасходованную часть за печать, которая на самом деле шла дальше. Так же
срабатывал любой обрыв связи с принтером. Учёт катушек уходил, и настоящий финиш его не чинил.

ПРИЧИНА (воспроизводится этим набором на прежнем коде). Наблюдатель возвратов раз в 5 секунд
сверяет «ожидающие печати» с состоянием принтеров и считал остановкой всё, что не печать, не
финиш и не сбой, — в том числе OFFLINE и ПУСТОЕ состояние. Сразу после запуска программы
состояний ещё нет (принтеры подключаются позже), обрыв Wi-Fi даёт OFFLINE. Запись закрывалась
возвратом по последнему проценту, и пришедший потом финиш уже ничего не менял.

ИСПРАВЛЕНИЕ — в модуле склада, ядро не трогали. OFFLINE, пустое и незнакомое состояние — «исход
неизвестен»: ничего не решаем. Покой (IDLE) засчитывается как остановка, только если держится
минуту подряд и с запуска программы прошло две минуты: первый неполный отчёт Bambu после запуска
даёт IDLE по умолчанию. FINISH и FAILED — ответ самого принтера, по ним решается сразу, как
раньше. Запись принтера, удалённого из фермы, закрывается без возврата — иначе катушка числилась
бы «в печати» вечно.

ЧТО ДОКАЗЫВАЕТСЯ: перезапуск посреди печати (пустые состояния, долгий OFFLINE, ложный IDLE, FINISH
и FAILED после перезапуска); обрыв связи на 10 секунд и на полчаса; незнакомое состояние; настоящая
отмена (возврат после минуты подтверждённого покоя, перерыв покоя начинает счёт заново); отмена,
пока программа была выключена; печать, которая так и не началась; два принтера независимо;
удалённый из фермы принтер; сбой чтения списка принтеров; границы правки по исходнику.

Безопасность прогона: рабочая база НЕ открывается — SQLite в памяти, поддельное ядро, функции
склада берутся из исходника дословно, время задаётся явно. Сети и принтеров нет.

Запуск: python tools/test_inventory_return_unknown_state.py   (0 = все проверки пройдены)
"""
import ast
import inspect
import io
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SRC_PATH = os.path.join(REPO, "modules", "inventory", "backend.py")
SRC = io.open(SRC_PATH, encoding="utf-8").read()

SENTINEL = "INVENTORY_RETURN_UNKNOWN_STATE_SENTINEL_2909"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


# ── Функции склада — дословно из исходника ────────────────────────────────────────────────
FUNCS = {"_inv_gcode_text", "_inv_gcode_weights", "_printer_confirmed_no_ams", "_inv_match_bound_spool_id",
         "_inv_autodeduct", "_pending_open", "_pending_finalize", "_reconcile_pending", "_inv_pending_spool_ids",
         #  16.10.2026 (склад, R-136): граммы по номеру филамента — списание и проверка зовут
         #  _inv_plate_weights (slice_info плиты, затем прежняя шапка G-code).
         "_inv_plate_weights", "_inv_slice_info_plate", "_inv_project_filament_count"}
CONSTS = {"_ST_PRINTING", "_ST_OK", "_ST_BAD", "_ST_IDLE", "_PENDING_T0", "_PENDING_BOOT_GRACE_S",
          "_PENDING_IDLE_CONFIRM_S", "_pending_idle_since"}
TREE = ast.parse(SRC)
FNODE = {n.name: n for n in TREE.body if isinstance(n, ast.FunctionDef)}
CHOSEN = [n for n in TREE.body
          if (isinstance(n, ast.FunctionDef) and n.name in FUNCS)
          or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTS for t in n.targets))]
SCHEMAS = next(ast.literal_eval(n.value) for n in TREE.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "_INIT_SQL" for t in n.targets))
CODE = compile(ast.Module(body=CHOSEN, type_ignores=[]), "inventory_under_test", "exec")

PID = "p1"
PID2 = "p2"
OFFLINE = {"status": "OFFLINE", "percent": 0}


class Core:
    """Поддельное ядро: состояния принтеров, доклад о подаче и состав фермы задаёт тест."""

    def __init__(self):
        self.states = {}
        self.reported = {}
        self.farm = {PID, PID2}
        self.printers_fail = False

    def new_id(self, prefix=""):
        return prefix + uuid.uuid4().hex[:12]

    def printer_states(self):
        return self.states

    def get_printer_reported_filament(self, pid):
        return self.reported.get(pid, {"telemetry_fresh": False, "positions": []})

    def printers(self):
        if self.printers_fail:
            raise RuntimeError("список принтеров не прочитан")
        return [{"id": p, "name": p} for p in sorted(self.farm)]


def new_db():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    for sql in SCHEMAS:
        c.execute(sql)
    return c


def new_env(conn=None):
    """Отдельное «исполнение» склада. Тот же conn в новом окружении — это перезапуск программы:
    момент загрузки модуля и счёт покоя начинаются заново, ожидающие печати берутся из базы."""
    core = Core()
    env = dict(io=io, zipfile=zipfile, re=re, json=json, time=time, core=core,
               lock_inv=threading.Lock(), log=logging.getLogger("inv_return_test"))
    exec(CODE, env)
    env["conn_inv"] = conn or new_db()
    return env, core, env["conn_inv"]


def spool(conn, sid, pid, slot, rem_g, total_g=1000.0):
    conn.execute("INSERT INTO inv_spools(id, ams_printer_id, ams_slot, weight_total_g, weight_remaining_g, status) "
                 "VALUES(?,?,?,?,?,?)", (sid, pid, slot, total_g, rem_g, "loaded"))
    conn.commit()


def rem(conn, sid):
    return round(float(conn.execute("SELECT weight_remaining_g FROM inv_spools WHERE id=?", (sid,)).fetchone()[0]), 2)


def ledger(conn, kind=None):
    rows = [dict(r) for r in conn.execute("SELECT kind, ref_id, qty, reason FROM inv_ledger ORDER BY rowid").fetchall()]
    return [r for r in rows if kind is None or r["kind"] == kind]


def pending(conn, status=None):
    rows = [dict(r) for r in conn.execute("SELECT * FROM inv_pending_prints ORDER BY rowid").fetchall()]
    return [r for r in rows if status is None or r["status"] == status]


def refunds(conn):
    return [r["qty"] for r in ledger(conn, "in")]


def tick(env, t):
    """Один проход наблюдателя в момент t. Прежний код (откат правки) времени не принимает —
    тогда он зовётся так же, как его зовёт фоновый поток; проверки ниже это покажут."""
    fn = env["_reconcile_pending"]
    if "now" in inspect.signature(fn).parameters:
        fn(now=t)
    else:
        fn()


#  Расход — как в настоящем «Single x5.gcode»: 20,80 г. Катушка 231 г -> после списания 210,2 г.
GC_ONE = b"; filament used [g] = 20.80\n; total filament used [g] = 20.80\nG1 X10 Y10\n"


def start_print(env, core, db, pid=PID, sid="sp"):
    """Старт печати: внешняя катушка 231 г, списано 20,8 г, открыта ожидающая печать."""
    core.states[pid] = {"status": "IDLE"}
    core.reported[pid] = {"telemetry_fresh": True, "positions": []}
    spool(db, sid, pid, -1, 231.0)
    env["_inv_autodeduct"](pid, [0], GC_ONE, "Single x5.gcode")
    return [r for r in pending(db, "active") if r["printer_id"] == pid][-1]["started_ts"]


def printing(pct=40):
    """Печать идёт: принтер сообщил RUNNING с процентом pct, наблюдатель это записал."""
    env, core, db = new_env()
    t0 = start_print(env, core, db)
    core.states[PID] = {"status": "RUNNING", "percent": pct}
    tick(env, t0 + 10)
    return env, core, db, t0


def restart(db):
    """Перезапуск программы: новое исполнение склада на той же базе; состояний принтеров ещё нет."""
    env2, core2, _ = new_env(db)
    return env2, core2, env2.get("_PENDING_T0", time.time())


def after_grace(env, t0):
    """Момент заведомо после выдержки запуска — чтобы доказывать правило «исход неизвестен», а не выдержку."""
    return max(env.get("_PENDING_T0", t0) + env.get("_PENDING_BOOT_GRACE_S", 120) + 10, t0 + 20)


def snap(db, sid="sp"):
    return rem(db, sid), refunds(db), [(p["status"], p["note"]) for p in pending(db)]


print("=== 13.10.2026: «готово» прошлой печати, а новая не началась — материал возвращается ===")
_e, _c, _db = new_env()
_t0 = start_print(_e, _c, _db)
_c.states[PID] = {"status": "FINISH", "percent": 100}          # «липкий» финиш прошлой печати, старта нет
_b = after_grace(_e, _t0)
for _s in range(0, 241, 5):
    tick(_e, _b + _s)
_early = snap(_db)
_early_active = len(pending(_db, "active"))
for _s in range(245, 1001, 5):
    tick(_e, _b + _s)
check("F1. принтер стоит в «готово» прошлой печати, новая не стартовала: через 3 минуты расход НЕ засчитан (как было)",
      _early[1] == [] and _early_active == 1, _early)
check("F2. ...а через 15 минут материал возвращён — «печать не началась» (раньше списывался полностью)",
      len(refunds(_db)) == 1 and [p["note"] for p in pending(_db)] == ["печать не началась"], snap(_db))
print()

print("=== 29.09.2026: склад не возвращает филамент, пока исход печати неизвестен ===")
print()
print("--- 0. Основа ---")
env, core, db, t0 = printing(40)
act = pending(db, "active")
check("0. печать идёт: списано 20,8 г (231 -> 210,2), ожидающая печать открыта и видит 40 %",
      rem(db, "sp") == 210.2 and len(act) == 1 and act[0]["seen_printing"] == 1 and act[0]["last_percent"] == 40,
      (rem(db, "sp"), act))

print()
print("--- 1. Перезапуск программы посреди печати ---")
env2, core2, T = restart(db)
for s in range(0, 61, 5):
    tick(env2, T + s)
check("1. КЛЮЧЕВОЕ: минута после перезапуска без состояний принтеров — возврата нет, остаток 210,2, запись ждёт",
      rem(db, "sp") == 210.2 and not refunds(db) and len(pending(db, "active")) == 1, snap(db))
core2.states[PID] = {"status": "FINISH", "percent": 100}
tick(env2, T + 65)
check("2. КЛЮЧЕВОЕ: затем принтер сообщил финиш — запись закрыта как «печать завершена», ни одного возврата в журнале",
      rem(db, "sp") == 210.2 and not refunds(db) and [p["note"] for p in pending(db)] == ["печать завершена"], snap(db))

env, core, db, t0 = printing(40)
env2, core2, T = restart(db)
core2.states[PID] = dict(OFFLINE)
for s in range(5, 181, 5):
    tick(env2, T + s)
waited = (rem(db, "sp"), refunds(db), len(pending(db, "active")))
core2.states[PID] = {"status": "RUNNING", "percent": 60}
tick(env2, T + 185)
core2.states[PID] = {"status": "FINISH", "percent": 100}
tick(env2, T + 190)
check("3. после перезапуска принтер 3 минуты не на связи (OFFLINE) — возврата нет, запись ждёт",
      waited == (210.2, [], 1), waited)
check("3. ...потом он печатает дальше и финиширует — возврата так и нет, запись закрыта как завершённая",
      rem(db, "sp") == 210.2 and not refunds(db) and [p["note"] for p in pending(db)] == ["печать завершена"], snap(db))

env, core, db, t0 = printing(40)
env2, core2, T = restart(db)
core2.states[PID] = {"status": "IDLE"}
for s in range(5, 36, 5):
    tick(env2, T + s)
core2.states[PID] = {"status": "RUNNING", "percent": 45}
tick(env2, T + 40)
act = pending(db, "active")
check("4. КЛЮЧЕВОЕ: после перезапуска первый неполный отчёт Bambu даёт IDLE на полминуты, затем RUNNING — "
      "возврата нет, печать учитывается дальше (45 %)",
      rem(db, "sp") == 210.2 and not refunds(db) and len(act) == 1 and act[0]["last_percent"] == 45, snap(db))

env, core, db, t0 = printing(40)
env2, core2, T = restart(db)
core2.states[PID] = {"status": "IDLE"}
for s in range(5, 116, 5):
    tick(env2, T + s)
core2.states[PID] = {"status": "RUNNING", "percent": 50}
tick(env2, T + 118)
check("5. ложный IDLE держится почти две минуты после запуска (потерялись два полных отчёта) — пока идёт "
      "выдержка после запуска, возврата нет",
      rem(db, "sp") == 210.2 and not refunds(db) and len(pending(db, "active")) == 1, snap(db))

env, core, db, t0 = printing(50)
env2, core2, T = restart(db)
core2.states[PID] = {"status": "FAILED", "percent": 50}
tick(env2, T + 5)
check("6. сбой (FAILED) после перезапуска — это ответ самого принтера: возврат 10,4 г сразу, как раньше",
      refunds(db) == [10.4] and rem(db, "sp") == 220.6, snap(db))

print()
print("--- 2. Обрыв связи посреди печати ---")
env, core, db, t0 = printing(40)
base = after_grace(env, t0)
core.states[PID] = dict(OFFLINE)
for s in (0, 5, 10):
    tick(env, base + s)
core.states[PID] = {"status": "RUNNING", "percent": 55}
tick(env, base + 15)
act = pending(db, "active")
check("7. КЛЮЧЕВОЕ: обрыв связи на 10 секунд посреди печати — возврата нет, печать учитывается дальше (55 %)",
      rem(db, "sp") == 210.2 and not refunds(db) and len(act) == 1 and act[0]["last_percent"] == 55, snap(db))

env, core, db, t0 = printing(40)
base = after_grace(env, t0)
core.states[PID] = dict(OFFLINE)
for s in range(0, 1801, 5):
    tick(env, base + s)
waited = (rem(db, "sp"), refunds(db), len(pending(db, "active")))
core.states[PID] = {"status": "FINISH", "percent": 100}
tick(env, base + 1805)
check("8. связи нет полчаса — возврата нет, запись ждёт", waited == (210.2, [], 1), waited)
check("8. ...печать тем временем закончилась, принтер вернулся с FINISH — запись закрыта как завершённая, без возврата",
      rem(db, "sp") == 210.2 and not refunds(db) and [p["note"] for p in pending(db)] == ["печать завершена"], snap(db))

env, core, db, t0 = printing(40)
base = after_grace(env, t0)
core.states[PID] = {"status": "BUSY", "percent": 0}
for s in range(0, 301, 5):
    tick(env, base + s)
check("9. незнакомое состояние (BUSY) пять минут — исход неизвестен, возврата нет, запись ждёт",
      rem(db, "sp") == 210.2 and not refunds(db) and len(pending(db, "active")) == 1, snap(db))

print()
print("--- 3. Настоящая остановка по-прежнему возвращает неизрасходованное ---")
env, core, db, t0 = printing(40)
base = after_grace(env, t0)
core.states[PID] = {"status": "IDLE"}
for s in (0, 30, 55):
    tick(env, base + s)
early = (rem(db, "sp"), refunds(db))
tick(env, base + 61)
check("10. отмена: покой держится меньше минуты — возврата ещё нет", early == (210.2, []), early)
check("11. КЛЮЧЕВОЕ: покой держится минуту — возвращено 12,5 г (60 % от 20,8), остаток 222,68, запись «печать прервана»",
      refunds(db) == [12.5] and rem(db, "sp") == 222.68 and [p["note"] for p in pending(db)] == ["печать прервана"],
      snap(db))
check("11. причина в истории катушки прежняя: «возврат: печать остановлена на ~40%»",
      [r["reason"] for r in ledger(db, "in")] == ["возврат: печать остановлена на ~40%"], ledger(db, "in"))

env, core, db, t0 = printing(40)
base = after_grace(env, t0)
core.states[PID] = {"status": "IDLE"}
for s in range(0, 51, 5):
    tick(env, base + s)
core.states[PID] = dict(OFFLINE)
tick(env, base + 55)
core.states[PID] = {"status": "IDLE"}
for s in range(60, 111, 5):
    tick(env, base + s)
mid = (rem(db, "sp"), refunds(db))
for s in (115, 120):
    tick(env, base + s)
check("12. покой, прерванный обрывом связи, считается заново: 50 с покоя, обрыв, ещё 50 с — возврата нет",
      mid == (210.2, []), mid)
check("12. ...через минуту НЕПРЕРЫВНОГО покоя возврат приходит (12,5 г)", refunds(db) == [12.5], snap(db))

env, core, db, t0 = printing(40)
env2, core2, T = restart(db)
core2.states[PID] = {"status": "IDLE"}
for s in range(5, 116, 5):
    tick(env2, T + s)
inside = (rem(db, "sp"), refunds(db))
tick(env2, T + 121)
check("13. печать отменили, пока программа была выключена: в первые две минуты после запуска возврата нет",
      inside == (210.2, []), inside)
check("13. ...после выдержки и минуты покоя — возврат 12,5 г по последнему известному проценту",
      refunds(db) == [12.5] and rem(db, "sp") == 222.68, snap(db))

env, core, db = new_env()
t0 = start_print(env, core, db)
core.states[PID] = dict(OFFLINE)
for s in range(0, 1201, 20):
    tick(env, t0 + s)
still = (rem(db, "sp"), refunds(db), len(pending(db, "active")))
core.states[PID] = {"status": "IDLE"}
tick(env, t0 + 1205)
tick(env, t0 + 1240)
mid = rem(db, "sp")
tick(env, t0 + 1270)
check("14. отправленная печать не началась, принтер 20 минут не на связи — возврата нет, запись ждёт",
      still == (210.2, [], 1), still)
check("15. принтер вернулся в покое, покой подтверждён — возвращено всё (остаток снова 231), причина «печать не началась»",
      mid == 210.2 and rem(db, "sp") == 231.0
      and [r["reason"] for r in ledger(db, "in")] == ["возврат: печать не началась"], snap(db))

env, core, db = new_env()
t0 = start_print(env, core, db)
base = after_grace(env, t0)
for s in range(0, 181, 5):
    tick(env, base + s)
check("16. печать ещё не началась, принтер в покое 3 минуты (меньше 15 минут с отправки) — ждём старта, "
      "возврата нет (как раньше)",
      rem(db, "sp") == 210.2 and not refunds(db) and len(pending(db, "active")) == 1, snap(db))

env, core, db = new_env()
start_print(env, core, db, PID, "sp_a")
t0b = start_print(env, core, db, PID2, "sp_b")
core.states[PID] = {"status": "RUNNING", "percent": 40}
core.states[PID2] = {"status": "RUNNING", "percent": 40}
tick(env, t0b + 10)
base = after_grace(env, t0b)
core.states[PID] = dict(OFFLINE)
core.states[PID2] = {"status": "IDLE"}
for s in range(0, 66, 5):
    tick(env, base + s)
check("17. два принтера: у остановленного (покой) возврат пришёл, у потерявшего связь — нет",
      rem(db, "sp_a") == 210.2 and rem(db, "sp_b") == 222.68 and len(pending(db, "active")) == 1
      and pending(db, "active")[0]["printer_id"] == PID, (rem(db, "sp_a"), rem(db, "sp_b"), pending(db)))

print()
print("--- 4. Принтер удалён из фермы ---")
env, core, db, t0 = printing(40)
core.farm.discard(PID)
core.states.pop(PID, None)
tick(env, t0 + 20)
notes = [p["note"] for p in pending(db)]
check("18. принтер удалён из фермы (состояния нет) — запись закрыта БЕЗ возврата, остаток 210,2",
      rem(db, "sp") == 210.2 and not refunds(db) and not pending(db, "active")
      and notes == ["принтер удалён из фермы — исход неизвестен, остаток не менялся"], snap(db))
check("18. ...катушка больше не числится «в незавершённой печати»: её снова можно удалить или отвязать",
      env["_inv_pending_spool_ids"]() == set(), env["_inv_pending_spool_ids"]())

env, core, db, t0 = printing(40)
core.farm.discard(PID)          # удалён, пока программа работает: воркера нет, состояние застыло на RUNNING
for s in (20, 25):
    tick(env, t0 + s)
check("19. принтер удалён во время работы программы (застывшее RUNNING) — запись закрыта без возврата",
      rem(db, "sp") == 210.2 and not refunds(db) and not pending(db, "active"), snap(db))

env, core, db, t0 = printing(40)
core.printers_fail = True
core.states.pop(PID, None)
tick(env, t0 + 20)
first = len(pending(db, "active"))
core.printers_fail = False
core.farm = set()
tick(env, t0 + 25)
check("20. список принтеров не прочитался или пуст — ничего не решаем: запись ждёт, возврата нет",
      first == 1 and len(pending(db, "active")) == 1 and rem(db, "sp") == 210.2 and not refunds(db), snap(db))

env, core, db, t0 = printing(40)
base = after_grace(env, t0)
core.states[PID] = dict(OFFLINE)
for s in range(0, 121, 5):
    tick(env, base + s)
check("21. принтер в ферме, но не на связи — запись не закрывается как «удалённый» и не возвращает",
      rem(db, "sp") == 210.2 and not refunds(db) and len(pending(db, "active")) == 1, snap(db))

print()
print("--- 5. Границы правки (по исходнику) ---")
rp = FNODE.get("_reconcile_pending")
wl = FNODE.get("_watch_pending_loop")
_args = [a.arg for a in rp.args.args] if rp else []
_defs = [getattr(d, "value", "?") for d in rp.args.defaults] if rp else []
check("22. наблюдатель принимает время явно (только для проверок), фоновый поток зовёт его без аргументов, как раньше",
      _args == ["now"] and _defs == [None] and wl is not None and "_reconcile_pending()" in ast.unparse(wl),
      (_args, _defs))


def _finalize_calls(nodes):
    out = []
    for n in nodes:
        for c in ast.walk(n):
            if isinstance(c, ast.Call) and ast.unparse(c.func) == "_pending_finalize" and len(c.args) == 3:
                out.append((ast.unparse(c.args[1]), getattr(c.args[2], "value", "?")))
    return out


_loop = next((n for n in ast.walk(rp) if isinstance(n, ast.For) and ast.unparse(n.target) == "row"), None) if rp else None
_body = _loop.body if _loop else []
_guard = next((i for i, n in enumerate(_body) if isinstance(n, ast.If)
               and ast.unparse(n.test) in ("status not in _ST_IDLE", "not _idle_like") and not n.orelse
               and len(n.body) == 1 and isinstance(n.body[0], ast.Continue)), None)
_bad = next((i for i, n in enumerate(_body) if isinstance(n, ast.If) and ast.unparse(n.test) == "status in _ST_BAD"), None)
_after = _finalize_calls(_body[_guard + 1:]) if _guard is not None else []
_before = _finalize_calls(_body[:_guard]) if _guard is not None else []
check("23. «печать прервана» и «печать не началась» стоят только за стражем «состояние — покой»: OFFLINE, пустое "
      "и незнакомое до возврата не доходят",
      _guard is not None and _bad is not None and _bad < _guard
      and sorted(w for _f, w in _after) == ["печать не началась", "печать прервана"], (_guard, _bad, _after))
check("24. до стража запись закрывают только ответы принтера (финиш, сбой) и удалённый из фермы принтер — "
      "последний долей 1.0, то есть без возврата",
      sorted(_before) == sorted([("1.0", "печать завершена"), ("None", "сбой/остановка"),
                                 ("1.0", "принтер удалён из фермы — исход неизвестен, остаток не менялся")]), _before)
env0, _c0, _d0 = new_env()
check("25. выдержка после запуска не меньше 2 минут, подтверждение покоя не меньше минуты (полный отчёт Bambu "
      "запрашивается раз в ~30 с), счёт покоя живёт только в памяти",
      env0.get("_PENDING_BOOT_GRACE_S", 0) >= 120 and env0.get("_PENDING_IDLE_CONFIRM_S", 0) >= 60
      and env0.get("_pending_idle_since") == {},
      (env0.get("_PENDING_BOOT_GRACE_S"), env0.get("_PENDING_IDLE_CONFIRM_S")))
env, core, db = new_env()
start_print(env, core, db)
core.states[PID] = {"status": "RUNNING", "percent": 30}
_ok = True
try:
    env["_reconcile_pending"]()
except Exception as _e:
    _ok = repr(_e)
act = pending(db, "active")
check("26. вызов без времени — как из фонового потока — работает: печать замечена, 30 %",
      _ok is True and len(act) == 1 and act[0]["seen_printing"] == 1 and act[0]["last_percent"] == 30, (_ok, act))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
