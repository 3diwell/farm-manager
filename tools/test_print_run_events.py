# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Автотест generic-событий печати ядра (app/print_run_events.py) — Alpha 2.717 (переработка).
# Ядро — БЕЗ базы данных: тест проверяет и поведение событий, и то, что ядро не владеет
# quality-хранилищем (нет farm_quality.db, нет таблицы print_runs, нет /api/print-runs).
# Запуск: python tools/test_print_run_events.py   (0 = все проверки пройдены)
import importlib.util
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-консоль cp1252
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("pre_events_test", os.path.join(REPO, "app", "print_run_events.py"))
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)

_fail = 0
def check(name, cond):
    global _fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        _fail += 1

events = []                                    # (name, payload)
def capture(name, payload):
    events.append((name, payload))

PINFO = {"p1": {"name": "Printer One", "type": "bambu", "model": "X1C", "gen": "auto"}}
E = ev.PrintRunEvents(log=None, printer_info_fn=lambda pid: PINFO.get(pid), hook_fire=capture)

def ctx(fn, **kw):
    d = {"file_norm": fn, "filename": fn + ".gcode", "source": "quick",
         "src_raw": "quick", "server_sent": True, "pstate": {"percent": 0, "nozzle_count": 1, "ams_trays": []}}
    d.update(kw)
    return d

def by(name):
    return [p for n, p in events if n == name]

# 1. start event создаётся один раз
r1 = E.on_start("p1", ctx("filea"))
check("1. started-событие создаётся (run_id, снапшоты, outcome=running)",
      bool(r1) and len(by("print_run_started")) == 1
      and by("print_run_started")[0]["outcome_raw"] == "running"
      and by("print_run_started")[0]["printer_snapshot"].get("model") == "X1C")

# 2. повторный PREPARE/RUNNING не дублируется
r1b = E.on_start("p1", ctx("filea"))
check("2. повторный PREPARE/RUNNING того же задания — событие не дублируется",
      r1b == r1 and len(by("print_run_started")) == 1)

# 3. PAUSED не завершает
E.on_terminal("p1", "PAUSED", {"percent": 40})
check("3. PAUSED не порождает finished", len(by("print_run_finished")) == 0)

# 4. FINISH вызывает ровно один finished event
out = E.on_terminal("p1", "FINISH", {"percent": 100})
fin = by("print_run_finished")
check("4. FINISH → одно finished-событие (finished, percent, finished_at)",
      out == "finished" and len(fin) == 1 and fin[0]["outcome_raw"] == "finished"
      and fin[0]["final_percent"] == 100.0 and fin[0]["finished_at"] and fin[0]["run_id"] == r1)

# 5. повторный FINISH игнорируется
out2 = E.on_terminal("p1", "FINISH", {"percent": 100})
check("5. повторный терминал без активного события — no-op", out2 is None and len(by("print_run_finished")) == 1)

# 6. FAILED и CANCELLED различаются
r2 = E.on_start("p1", ctx("fileb")); E.on_terminal("p1", "FAILED", {"percent": 33})
r3 = E.on_start("p1", ctx("filec")); E.on_terminal("p1", "STOP", {"percent": 10})
outs = {p["run_id"]: p["outcome_raw"] for p in by("print_run_finished")}
check("6. FAILED→failed, STOP→cancelled (различаются)", outs.get(r2) == "failed" and outs.get(r3) == "cancelled")

# 7. два запуска одного filename получают разные run_id
ra = E.on_start("p1", ctx("same")); E.on_terminal("p1", "FINISH", {"percent": 100})
rb = E.on_start("p1", ctx("same"))
check("7. повторный запуск того же файла = новый run_id", ra and rb and ra != rb)

# 8. callback получает КОПИЮ (мутация полученного payload не влияет на будущие события)
started_rb = [p for p in by("print_run_started") if p["run_id"] == rb][0]
started_rb["printer_snapshot"]["model"] = "HACKED"
started_rb["source"] = "hacked"
E.on_terminal("p1", "FINISH", {"percent": 100})
fin_rb = [p for p in by("print_run_finished") if p["run_id"] == rb][0]
check("8. подписчик получает копию — мутации не протекают в ядро",
      fin_rb["printer_snapshot"].get("model") == "X1C" and fin_rb["source"] == "quick")

# 9. падающий callback не ломает остальные (паттерн _fire_print_run_hooks ядра)
calls = []
def _fire_like_core(name, snapshot):
    for fn in (lambda s: (_ for _ in ()).throw(RuntimeError("boom")), lambda s: calls.append(name)):
        try:
            fn(dict(snapshot))
        except Exception:
            pass   # ядро глотает ошибку подписчика
E2 = ev.PrintRunEvents(printer_info_fn=lambda pid: PINFO.get(pid), hook_fire=_fire_like_core)
rid = E2.on_start("p1", ctx("hooky"))
check("9. падающий подписчик не мешает остальным и не ломает событие",
      bool(rid) and calls == ["print_run_started"])
def _fire_raises(name, snapshot):
    raise RuntimeError("hook_fire exploded")
E3 = ev.PrintRunEvents(hook_fire=_fire_raises)
rid3 = E3.on_start("p1", ctx("hooky2"))
check("9b. исключение самого hook_fire проглатывается (печать не пострадает)", bool(rid3))

# ── Назначение материала задания (семантическая правка): реальный ams_mapping, не «все катушки» ──
BA = ev.build_assignments
check("13. build_assignments([2],[120]) → одна позиция slot 2, planned_g=120",
      BA([2], [120.0], False) == [{"filament_index": 0, "ams_slot": 2, "external": False, "planned_g": 120.0}])
check("13b. известные веса: только реально печатаемый филамент (slot 0), 0-граммовые отброшены",
      BA([0, 1, 2, 3], [10.0, 0, 0, 0], False) == [{"filament_index": 0, "ams_slot": 0, "external": False, "planned_g": 10.0}])
check("13c. многоцветная: две позиции с пофиламентным весом по индексу",
      BA([0, 1], [12.5, 8.3], False) == [{"filament_index": 0, "ams_slot": 0, "external": False, "planned_g": 12.5},
                                         {"filament_index": 1, "ams_slot": 1, "external": False, "planned_g": 8.3}])
check("13d. пустой map + external → одна внешняя позиция ams_slot=-1 (2.737: совпадает с overview external -1 для cost/quality)",
      BA([], [40.0], True) == [{"filament_index": 0, "ams_slot": -1, "external": True, "planned_g": 40.0}])
check("13e. пустой map без external → пусто (никаких выдуманных катушек)", BA([], [], False) == [])
check("13f. слот -1 (не назначен) пропускается",
      BA([-1, 3], [5.0, 7.0], False) == [{"filament_index": 1, "ams_slot": 3, "external": False, "planned_g": 7.0}])

# 14. on_start несёт material_assignments из stash_assignments; whitelist полей
E4 = ev.PrintRunEvents(printer_info_fn=lambda pid: PINFO.get(pid), hook_fire=capture)
E4.stash_assignments("p1", [2], None, False)
E4.on_start("p1", ctx("asg"))
st = [p for n, p in events if n == "print_run_started" and p.get("file_norm") == "asg"]
check("14. on_start несёт material_assignments задания (slot 2)",
      len(st) == 1 and st[0].get("material_assignments") == [{"filament_index": 0, "ams_slot": 2, "external": False, "planned_g": None}])
_allowed = {"filament_index", "ams_slot", "external", "planned_g"}
check("14b. whitelist: только позиционные/весовые поля (нет token/serial/spool/vendor)",
      all(set(a.keys()) <= _allowed for a in st[0]["material_assignments"]))
E4.on_start("p1", ctx("noasg"))   # другой файл, без stash → назначение неизвестно
st2 = [p for n, p in events if n == "print_run_started" and p.get("file_norm") == "noasg"]
check("14c. без назначения → material_assignments == []", len(st2) == 1 and st2[0].get("material_assignments") == [])

# 10-12. Ядро не владеет quality-хранилищем (проверка по исходникам)
core_src = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
events_src = open(os.path.join(REPO, "app", "print_run_events.py"), encoding="utf-8").read()
check("10. ядро не открывает farm_quality.db (нет resolve/connect к ней)",
      "farm_quality" not in core_src
      and 'resolve_db("farm_quality' not in events_src and "sqlite3.connect" not in events_src)
check("11. в ядре нет таблицы print_runs (SQL/DDL отсутствуют)",
      "CREATE TABLE IF NOT EXISTS print_runs" not in core_src
      and "import sqlite3" not in events_src
      and "CREATE TABLE" not in events_src)
check("12. в ядре нет /api/print-runs", '"/api/print-runs"' not in core_src and "'/api/print-runs'" not in core_src)

print("\n" + ("FAIL: %d проверок провалено" % _fail if _fail else "PASS: generic-события печати — все сценарии пройдены"))
sys.exit(1 if _fail else 0)
