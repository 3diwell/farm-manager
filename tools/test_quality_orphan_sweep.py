# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.964 — уборка записей, оставшихся «печатается» (модуль «Аналитика качества» 0.2.3).

ЗАЧЕМ. Запись о печати создаётся со словом running, а исход дописывает событие конца печати.
Если программа в этот момент была выключена, дописать некому — запись висит вечно. Владелец
выбрал разбор при запуске программы: спросить у самих принтеров, что они делают.

ЗДЕСЬ ПРОВЕРЯЕТСЯ ГЛАВНОЕ — что уборка НЕ МОЖЕТ закрыть живую печать. Это опаснее, чем
оставить лишнюю запись: закрытая запись живой печати испортит историю и материалы. Поэтому
проверяются все состояния принтера, молчание, отсутствие принтера на ферме, повторный запуск
и падение ядра при опросе.

БЕЗОПАСНОСТЬ: временный DATA_DIR, рабочая база не используется; ни сети, ни принтеров.

Запуск:  python tools/test_quality_orphan_sweep.py   (0 = все проверки пройдены)
"""
import importlib.util
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("quality_sweep_test", os.path.join(REPO, "modules", "quality", "backend.py"))
qb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qb)

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


tmp = tempfile.mkdtemp(prefix="fm_quality_sweep_")


class FakeCore:
    """ModuleCore ровно в той части, которой пользуется уборка: своя БД, принтеры, живые состояния."""

    def __init__(self):
        self.states = {}
        self.plist = []
        self.states_raise = False
        self.printers_raise = False

    def resolve_db(self, name):
        return os.path.join(tmp, name)

    def add_route(self, path, fn, methods, policy_id=None):
        return True

    def add_hook(self, name, fn):
        return True

    def printers(self):
        if self.printers_raise:
            raise RuntimeError("printers boom")
        return list(self.plist)

    def printer_states(self):
        if self.states_raise:
            raise RuntimeError("states boom")
        return dict(self.states)


fc = FakeCore()
qb.SWEEP_DELAY_S = 36000        # таймер из register() в тесте не должен сработать
qb.register(fc)


def add_run(run_id, pid, outcome="running"):
    now = "2026-09-01 10:00:00"
    with qb.lock_q:
        qb.conn_q.execute(
            "INSERT INTO print_runs (run_id, source, printer_id, printer_name, printer_type, printer_model, "
            "filename, file_norm, started_at, outcome_raw, origin, schema_version, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "quick", pid, "Printer " + pid, "bambu", "X1C", "korpus.gcode", "korpusgcode",
             now, outcome, "live", 1, now, now))
        qb.conn_q.commit()


def row(run_id):
    with qb.lock_q:
        r = qb.conn_q.execute("SELECT outcome_raw, terminal_reason, finished_at, elapsed_s, final_percent "
                              "FROM print_runs WHERE run_id=?", (run_id,)).fetchone()
    return dict(r) if r else None


print("--- 1. принтер сам решает судьбу записи ---")
#  По одной зависшей записи на каждое состояние, в котором принтер может оказаться.
CASES = [
    ("run-print", "p-print", "RUNNING", False),
    ("run-prep", "p-prep", "PREPARE", False),
    ("run-pause", "p-pause", "PAUSED", False),
    ("run-slice", "p-slice", "SLICING", False),
    ("run-idle", "p-idle", "IDLE", True),
    ("run-fin", "p-fin", "FINISH", True),
    ("run-fail", "p-fail", "FAILED", True),
    ("run-off", "p-off", "OFFLINE", False),
    ("run-mute", "p-mute", None, False),          # состояния нет вовсе
]
for rid, pid, st, _ in CASES:
    add_run(rid, pid)
    fc.plist.append({"id": pid})
    if st is not None:
        fc.states[pid] = {"status": st, "file_name": "sovsem_drugoi_fail"}

add_run("run-gone", "p-gone")                     # принтера на ферме больше нет
add_run("run-done", "p-idle", outcome="finished")  # уже закрытая запись — трогать нельзя

res = qb.q_sweep_orphans()

_live = [rid for rid, _p, _s, close in CASES if not close]
check("1. печатающий принтер: запись НЕ закрыта ни в одном состоянии печати",
      all(row(r)["outcome_raw"] == "running" for r in ("run-print", "run-prep", "run-pause", "run-slice")),
      {r: row(r)["outcome_raw"] for r in ("run-print", "run-prep", "run-pause", "run-slice")})
check("2. принтер на связи и не печатает: запись закрыта как «не определён»",
      all(row(r)["outcome_raw"] == "unknown" and row(r)["terminal_reason"] == "program_was_off"
          for r in ("run-idle", "run-fin", "run-fail")),
      {r: row(r) for r in ("run-idle", "run-fin", "run-fail")})
check("3. принтер молчит (offline или состояния нет): запись оставлена до следующего запуска",
      row("run-off")["outcome_raw"] == "running" and row("run-mute")["outcome_raw"] == "running",
      (row("run-off"), row("run-mute")))
check("4. принтера нет на ферме: запись закрыта с честной причиной",
      row("run-gone")["outcome_raw"] == "unknown" and row("run-gone")["terminal_reason"] == "printer_removed",
      row("run-gone"))
check("5. уже закрытая запись не переписывается",
      row("run-done")["outcome_raw"] == "finished" and row("run-done")["terminal_reason"] is None,
      row("run-done"))
check("6. закрывая запись, время печати и процент не выдумываются",
      row("run-idle")["elapsed_s"] is None and row("run-idle")["final_percent"] is None
      and bool(row("run-idle")["finished_at"]),
      row("run-idle"))
check("7. сводка сходится: проверено 10, закрыто 4, оставлено 6",
      res == {"checked": 10, "closed": 4, "left": 6,
              "reasons": {"program_was_off": 3, "printer_removed": 1}}, res)

print("--- 2. повторные запуски и сбои ---")
res2 = qb.q_sweep_orphans()
check("8. повторный запуск ничего не портит: закрывать больше нечего",
      res2["closed"] == 0 and res2["checked"] == 6 and res2["left"] == 6, res2)

fc.states["p-print"] = {"status": "IDLE"}        # печать кончилась, программа теперь работает
res3 = qb.q_sweep_orphans()
check("9. когда принтер освободился, его запись закрывается на следующем запуске",
      res3["closed"] == 1 and row("run-print")["terminal_reason"] == "program_was_off",
      (res3, row("run-print")))

fc.states_raise = True
res4 = qb.q_sweep_orphans()
fc.states_raise = False
check("10. ядро не отдало состояния — уборка молча отступает, журнал цел",
      res4["closed"] == 0 and res4["left"] == res4["checked"] and row("run-off")["outcome_raw"] == "running", res4)

fc.printers_raise = True
add_run("run-gone2", "p-nowhere")
res5 = qb.q_sweep_orphans()
fc.printers_raise = False
check("11. список принтеров не прочитался — удалённые не ищем, живое не трогаем",
      row("run-gone2")["outcome_raw"] == "running" and res5["closed"] == 0, (res5, row("run-gone2")))

print("--- 3. согласие с остальной программой ---")
SRC = open(os.path.join(REPO, "modules", "quality", "backend.py"), encoding="utf-8").read()
check("12. решение принимает принтер: ни имя файла, ни часы в уборке не участвуют",
      "file_norm" not in SRC.split("def q_sweep_orphans", 1)[1].split("def ", 1)[0]
      and "started_at" not in SRC.split("def q_sweep_orphans", 1)[1].split("def ", 1)[0])
check("13. уборка заводится при запуске модуля и не задерживает загрузку",
      'if hasattr(core, "printer_states"):' in SRC and "threading.Timer(SWEEP_DELAY_S, q_sweep_orphans)" in SRC
      and "_t.daemon = True" in SRC)
MAN = open(os.path.join(REPO, "modules", "quality", "module.json"), encoding="utf-8").read()
REG = open(os.path.join(REPO, "app", "route_policy_registry.py"), encoding="utf-8").read()
check("14. версия модуля поднята и совпадает с реестром прав (иначе маршруты не подключатся)",
      '"version": "0.2.3"' in MAN and REG.count("('quality', '0.2.3',") == 4
      and "('quality', '0.2.2'," not in REG)

print("\nQUALITY_ORPHAN_SWEEP_SENTINEL_2_964: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
