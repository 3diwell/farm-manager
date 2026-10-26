# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""23.09.2026 — внешняя подача принтера без системы подачи списывается (AD5M_02).

ЖАЛОБА. FlashForge Adventurer 5M «AD5M_02»: из FM запущен «Single x5.gcode», печать успешно
закончилась, а остаток катушки остался 231 г. В файле расход 20,80 г, и склад читает его верно.

ПРИЧИНА (подтверждена разбором Codex 22.09 и воспроизведена здесь). Склад хранит внешнюю катушку
каноническим ams_slot = -1, а ядро у принтера БЕЗ системы подачи (FlashForge, Klipper без CFS)
присылает позицию [0]. Сопоставление слота для slot >= 0 искало ТОЛЬКО точный слот 0 — не находило
катушку и молча пропускало списание: ни расхода, ни «ожидающей печати» для возврата.

ИСПРАВЛЕНИЕ — в модуле склада, ядро не трогали. Слот 0 принтера без системы подачи и есть его
внешняя подача (так уже считала _inv_external_slot), но переход 0 -> -1 разрешён ТОЛЬКО при свежем
подтверждении, что живых AMS/CFS-позиций нет. Настоящий слот 0 AMS/CFS так не подменяется. Это
зеркало давнего legacy-перехода -1 -> 0, и одно и то же сопоставление служит и списанию, и проверке
«хватит ли филамента» перед стартом — оба пути понимают позицию одинаково.

ЧТО ДОКАЗЫВАЕТСЯ (список из задания): успешный старт; ошибка старта; завершение; отмена и возврат
неиспользованной части; повтор хука и опроса; перезапуск программы; настоящий слот 0 AMS/CFS;
несколько цветов; неизвестная/неподтверждённая подача; отсутствие привязанной катушки; проверка
перед стартом видит ту же катушку. Рабочая база НЕ открывается: SQLite в памяти, поддельное ядро,
функции склада берутся из исходника дословно. Сети и принтеров нет.

Запуск: python tools/test_inventory_external_feed_deduction.py   (0 = все проверки пройдены)
"""
import ast
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
SERVER = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

SENTINEL = "INVENTORY_EXTERNAL_FEED_SENTINEL_2309"
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
         "_inv_autodeduct", "_pending_open", "_pending_finalize", "_reconcile_pending", "inv_check_print",
         "_inv_external_slot",
         #  16.10.2026 (склад, R-136): граммы по номеру филамента — списание и проверка зовут
         #  _inv_plate_weights (slice_info плиты, затем прежняя шапка G-code).
         "_inv_plate_weights", "_inv_slice_info_plate", "_inv_project_filament_count"}
#  29.09.2026 (склад 1.7.31): наблюдатель возвратов ждёт подтверждённого покоя — его константы и
#  счётчик покоя тоже берутся из исходника, иначе _reconcile_pending падает NameError.
CONSTS = {"_ST_PRINTING", "_ST_OK", "_ST_BAD", "_ST_IDLE", "_PENDING_T0", "_PENDING_BOOT_GRACE_S",
          "_PENDING_IDLE_CONFIRM_S", "_pending_idle_since"}
TREE = ast.parse(SRC)
CHOSEN = []
for node in TREE.body:
    if isinstance(node, ast.FunctionDef) and node.name in FUNCS:
        CHOSEN.append(node)
    elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in CONSTS for t in node.targets):
        CHOSEN.append(node)
SCHEMAS = next(ast.literal_eval(n.value) for n in TREE.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "_INIT_SQL" for t in n.targets))
CODE = compile(ast.Module(body=CHOSEN, type_ignores=[]), "inventory_under_test", "exec")


class Core:
    """Поддельное ядро: состояние принтеров и доклад о позициях подачи задаются тестом."""

    def __init__(self):
        self.states = {}
        self.reported = {}

    def new_id(self, prefix=""):
        return prefix + uuid.uuid4().hex[:12]

    def printer_states(self):
        return self.states

    def get_printer_reported_filament(self, pid):
        return self.reported.get(pid, {"telemetry_fresh": False, "positions": []})


def new_db():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    for sql in SCHEMAS:
        c.execute(sql)
    return c


def new_env(conn=None):
    """Отдельное «исполнение» склада. Тот же conn в новом окружении — это перезапуск программы."""
    core = Core()
    env = dict(io=io, zipfile=zipfile, re=re, json=json, time=time, core=core,
               lock_inv=threading.Lock(), log=logging.getLogger("inv_test"))
    exec(CODE, env)
    env["conn_inv"] = conn or new_db()
    return env, core, env["conn_inv"]


def single_feed(core, pid):
    """FlashForge AD5M / Klipper без CFS: связь свежая, живых позиций подачи нет."""
    core.states[pid] = {"status": "IDLE"}
    core.reported[pid] = {"telemetry_fresh": True, "positions": []}


def with_ams(core, pid):
    core.states[pid] = {"status": "IDLE"}
    core.reported[pid] = {"telemetry_fresh": True,
                          "positions": [{"index": 0, "external": False}, {"index": 1, "external": False},
                                        {"index": None, "external": True}]}


def with_cfs(core, pid):
    core.states[pid] = {"status": "IDLE", "cfs_trays": [{"slot": "T1A"}]}
    core.reported[pid] = {"telemetry_fresh": True, "positions": []}


def stale(core, pid):
    core.states[pid] = {"status": "OFFLINE"}
    core.reported[pid] = {"telemetry_fresh": False, "positions": []}


def spool(conn, sid, pid, slot, rem, total_g=1000.0):
    conn.execute("INSERT INTO inv_spools(id, ams_printer_id, ams_slot, weight_total_g, weight_remaining_g, status) "
                 "VALUES(?,?,?,?,?,?)", (sid, pid, slot, total_g, rem, "loaded"))
    conn.commit()


def rem(conn, sid):
    return round(float(conn.execute("SELECT weight_remaining_g FROM inv_spools WHERE id=?", (sid,)).fetchone()[0]), 2)


def ledger(conn, kind=None):
    rows = [dict(r) for r in conn.execute("SELECT kind, ref_id, qty, reason FROM inv_ledger ORDER BY rowid").fetchall()]
    return [r for r in rows if kind is None or r["kind"] == kind]


def pending(conn, status=None):
    rows = [dict(r) for r in conn.execute("SELECT * FROM inv_pending_prints ORDER BY rowid").fetchall()]
    return [r for r in rows if status is None or r["status"] == status]


#  Два заголовка — ровно те строки, что в настоящем «Single x5.gcode» (строки 225081 и 225083).
GC_ONE = b"; filament used [g] = 20.80\n; total filament used [g] = 20.80\nG1 X10 Y10\n"
GC_TWO = b"; filament used [g] = 12.00, 8.80\nG1 X10 Y10\n"
GC_BIG = b"; filament used [g] = 250.00\nG1 X10 Y10\n"
PID = "ad5m_02"

print("=== 23.09.2026: внешняя подача принтера без системы подачи ===")
print()
print("--- 1. Сценарий AD5M_02 ---")
env, core, db = new_env()
check("1. расход файла читается как в настоящем «Single x5»: 20,8 г", env["_inv_gcode_weights"](GC_ONE) == [20.8],
      env["_inv_gcode_weights"](GC_ONE))
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "Single x5.gcode")
check("2. КЛЮЧЕВОЕ: ядро прислало [0], внешняя катушка -1 — остаток 231 -> 210,2 г", rem(db, "sp_ext") == 210.2,
      rem(db, "sp_ext"))
check("3. в журнале ровно один расход 20,8 г с именем файла",
      [(r["kind"], r["qty"]) for r in ledger(db)] == [("out", 20.8)], ledger(db))
check("4. открыта «ожидающая печать» — есть что вернуть при сбое", len(pending(db, "active")) == 1, pending(db))

print()
print("--- 2. Настоящий слот 0 AMS/CFS не подменяется ---")
env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_zero", PID, 0, 500.0)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "x.gcode")
check("5. есть и точный слот 0, и внешняя: точное совпадение главнее, внешняя не тронута",
      rem(db, "sp_zero") == 479.2 and rem(db, "sp_ext") == 231.0, (rem(db, "sp_zero"), rem(db, "sp_ext")))

env, core, db = new_env()
with_ams(core, "x1c")
spool(db, "sp_ext", "x1c", -1, 231.0)
env["_inv_autodeduct"]("x1c", [0], GC_ONE, "x.gcode")
check("6. КЛЮЧЕВОЕ: у принтера с живым AMS слот 0 внешней катушкой НЕ считается — ничего не списано",
      rem(db, "sp_ext") == 231.0 and not ledger(db) and not pending(db), (rem(db, "sp_ext"), ledger(db)))

env, core, db = new_env()
with_ams(core, "x1c")
spool(db, "sp_ams0", "x1c", 0, 500.0)
env["_inv_autodeduct"]("x1c", [0], GC_ONE, "x.gcode")
check("7. настоящий слот 0 AMS списывается как раньше", rem(db, "sp_ams0") == 479.2, rem(db, "sp_ams0"))

env, core, db = new_env()
with_cfs(core, "k2")
spool(db, "sp_ext", "k2", -1, 231.0)
env["_inv_autodeduct"]("k2", [0], GC_ONE, "x.gcode")
check("8. у принтера с живым коробом CFS слот 0 внешней катушкой НЕ считается",
      rem(db, "sp_ext") == 231.0 and not ledger(db), rem(db, "sp_ext"))

print()
print("--- 3. Неизвестная подача и пустые привязки ---")
env, core, db = new_env()
stale(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "x.gcode")
check("9. связь несвежая — отсутствие AMS не доказано, списания нет (лучше пропуск, чем чужая катушка)",
      rem(db, "sp_ext") == 231.0 and not ledger(db) and not pending(db), rem(db, "sp_ext"))

env, core, db = new_env()
single_feed(core, PID)
env["_inv_autodeduct"](PID, [0], GC_ONE, "x.gcode")
check("10. привязанной катушки нет — ни расхода, ни ожидающей печати", not ledger(db) and not pending(db))

env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_other", "другой_принтер", -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "x.gcode")
check("11. внешняя катушка ДРУГОГО принтера не списывается", rem(db, "sp_other") == 231.0 and not ledger(db))

print()
print("--- 4. Несколько цветов ---")
env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_TWO, "two.gcode")
check("12. у принтера с одной подачей оба филамента берутся из той же внешней катушки",
      rem(db, "sp_ext") == 210.2 and [r["qty"] for r in ledger(db, "out")] == [12.0, 8.8], (rem(db, "sp_ext"), ledger(db)))

env, core, db = new_env()
with_ams(core, "x1c")
spool(db, "sp_a", "x1c", 0, 500.0)
spool(db, "sp_b", "x1c", 1, 400.0)
env["_inv_autodeduct"]("x1c", [0, 1], GC_TWO, "two.gcode")
check("13. у AMS каждый цвет списывается со своего слота", (rem(db, "sp_a"), rem(db, "sp_b")) == (488.0, 391.2),
      (rem(db, "sp_a"), rem(db, "sp_b")))

print()
print("--- 5. Завершение, отмена, возврат ---")
env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "Single x5.gcode")
row = pending(db, "active")[0]
env["_pending_finalize"](row, 1.0, "печать завершена")
check("14. печать завершена — возврата нет, остаток 210,2, ожидание закрыто",
      rem(db, "sp_ext") == 210.2 and pending(db, "done") and not ledger(db, "in"), (rem(db, "sp_ext"), ledger(db)))

env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "Single x5.gcode")
env["_pending_finalize"](pending(db, "active")[0], 0.25, "сбой/остановка")
check("15. отмена на 25 % — возвращается неиспользованная часть 15,6 г (остаток 225,8)",
      rem(db, "sp_ext") == 225.8 and [r["qty"] for r in ledger(db, "in")] == [15.6], (rem(db, "sp_ext"), ledger(db)))

env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "Single x5.gcode")
env["_pending_finalize"](pending(db, "active")[0], 0.0, "печать не началась")
check("16. печать так и не началась — возвращается всё, остаток снова 231", rem(db, "sp_ext") == 231.0,
      rem(db, "sp_ext"))

print()
print("--- 6. Повторы и перезапуск ---")
env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "Single x5.gcode")
env["_inv_autodeduct"](PID, [0], GC_ONE, "Single x5.gcode")
check("17. повтор хука по той же печати не списывает дважды: первое ожидание закрывается полным возвратом",
      rem(db, "sp_ext") == 210.2 and len(pending(db, "active")) == 1, (rem(db, "sp_ext"), ledger(db)))

env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "Single x5.gcode")
core.states[PID] = {"status": "RUNNING", "percent": 40}
for _ in range(3):
    env["_reconcile_pending"]()
check("18. опрос статуса во время печати ничего не списывает", rem(db, "sp_ext") == 210.2 and len(ledger(db)) == 1,
      (rem(db, "sp_ext"), ledger(db)))
core.states[PID] = {"status": "FINISH", "percent": 100}
env["_reconcile_pending"]()
check("19. опрос увидел финиш — ожидание закрыто без возврата", rem(db, "sp_ext") == 210.2 and pending(db, "done"),
      (rem(db, "sp_ext"), pending(db)))

env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
env["_inv_autodeduct"](PID, [0], GC_ONE, "Single x5.gcode")
core.states[PID] = {"status": "RUNNING", "percent": 50}
env["_reconcile_pending"]()
env2, core2, _ = new_env(db)            # «перезапуск программы»: новое исполнение, та же база
core2.states[PID] = {"status": "FAILED", "percent": 50}
env2["_reconcile_pending"]()
check("20. после перезапуска ожидание подхватывается из базы: сбой на 50 % -> возврат 10,4 г",
      rem(db, "sp_ext") == 220.6 and [r["qty"] for r in ledger(db, "in")] == [10.4], (rem(db, "sp_ext"), ledger(db)))

print()
print("--- 7. Проверка перед стартом понимает позицию так же ---")
env, core, db = new_env()
single_feed(core, PID)
spool(db, "sp_ext", PID, -1, 231.0)
short = env["inv_check_print"](PID, GC_BIG, None, {"slots": [0]})
check("21. КЛЮЧЕВОЕ: «хватит ли филамента» видит внешнюю катушку AD5M (нужно 250, есть 231)",
      len(short) == 1 and short[0]["slot"] == 0 and short[0]["available"] == 231.0 and short[0]["needed"] == 250.0,
      short)
check("22. хватает — проверка молчит", env["inv_check_print"](PID, GC_ONE, None, {"slots": [0]}) == [])
env, core, db = new_env()
with_ams(core, "x1c")
spool(db, "sp_ext", "x1c", -1, 231.0)
check("23. у принтера с AMS внешняя катушка по слоту 0 не сверяется (как и не списывается)",
      env["inv_check_print"]("x1c", GC_BIG, None, {"slots": [0]}) == [])
env, core, db = new_env()
single_feed(core, PID)
check("24. «внешняя ли подача» и сопоставление согласны: слот 0 без подачи — внешний, с AMS — нет",
      env["_inv_external_slot"](0, PID) is True and env["_inv_external_slot"](-1, PID) is True)
with_ams(core, "x1c")
check("25. ...а у принтера с AMS слот 0 внешним не считается", env["_inv_external_slot"](0, "x1c") is False)

print()
print("--- 8. Границы правки ---")
i_hook = SERVER.find('_run_after_dispatch_hooks(pid, [0], fdata, fname)   # хуки модулей (fail-open)')
window = SERVER[max(0, i_hook - 260):i_hook]
check("26. ошибка старта: у FlashForge хук склада вызывается только ПОСЛЕ того, как принтер принял старт",
      i_hook > 0 and "if _ok:" in window and "Print started" in window, window[-160:])
check("27. ядро не менялось: FlashForge по-прежнему присылает [0] — исправление в модуле склада",
      SERVER.count("_run_after_dispatch_hooks(pid, [0], fdata, fname)") >= 1)
match_src = SRC[SRC.find("def _inv_match_bound_spool_id"):SRC.find("def _inv_autodeduct")]
check("28. переход 0 -> -1 разрешён ТОЛЬКО при подтверждённом отсутствии AMS/CFS",
      "if slot == 0 and no_ams:" in match_src and match_src.count("ams_slot=-1") >= 2)
check("29. историю остатков правка не пересчитывает: ни одной новой записи в базу вне списания",
      "UPDATE inv_spools" not in match_src and "INSERT" not in match_src)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
