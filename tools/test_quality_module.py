# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Автотест модуля «Аналитика качества» (modules/quality/backend.py).
# Работает ТОЛЬКО с временным DATA_DIR (реальная DATA_DIR не используется и не трогается).
# Запуск: python tools/test_quality_module.py   (0 = все проверки пройдены)
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows-консоль cp1252
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("quality_backend_test", os.path.join(REPO, "modules", "quality", "backend.py"))
qb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qb)

_fail = 0
_total = 0
def check(name, cond):
    global _fail, _total
    _total += 1
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        _fail += 1

tmp = tempfile.mkdtemp(prefix="fm_quality_test_")   # временный DATA_DIR

class FakeCore:
    """Имитация ModuleCore: resolve_db в temp-папку, учёт роутов/хуков + generic-снимок филамента."""
    def __init__(self):
        self.routes = []
        self.policy_ids = []
        self.hooks = {}
        self.filament = {}          # pid -> {"has_ams":bool,"slots":[...]} — имитация ядерного снимка
        self.filament_raises = set()  # pid, на которых «провайдер» бросает исключение
    def resolve_db(self, name):
        return os.path.join(tmp, name)
    def add_route(self, path, fn, methods, policy_id=None):
        # Alpha 2.785: policy_id обязателен для маршрутов модулей — ссылка на запись
        # в едином реестре прав ядра. Форму self.routes не меняем, id копим отдельно.
        self.routes.append((path, tuple(methods)))
        self.policy_ids.append(policy_id)
        return True
    def add_hook(self, name, fn):
        self.hooks[name] = fn
        return True
    def get_printer_filament_snapshot(self, printer_id=None):
        """Как в ядре: fail-open + глубокая копия. Провайдер может «падать» (filament_raises)."""
        import json as _j
        if printer_id is not None and str(printer_id) in self.filament_raises:
            raise RuntimeError("provider boom")
        src = self.filament.get(str(printer_id), {}) if printer_id is not None else self.filament
        return _j.loads(_j.dumps(src))

fc = FakeCore()
qb.register(fc)
started, finished = fc.hooks["print_run_started"], fc.hooks["print_run_finished"]

def snap(run_id, fn="filea", pid="p1", **kw):
    d = {"run_id": run_id, "source": "quick", "printer_id": pid, "printer_name": "Printer One",
         "printer_type": "bambu", "printer_model": "X1C", "filename": fn + ".gcode", "file_norm": fn,
         "started_at": "2026-07-11 10:00:00", "outcome_raw": "running", "origin": "live", "schema_version": 1,
         "source_payload": {"src_raw": "quick"}, "profile_snapshot": {"layer_height": "0.2"},
         "printer_snapshot": {"model": "X1C"}}
    d.update(kw)
    return d

def rows():
    with qb.lock_q:
        return [dict(r) for r in qb.conn_q.execute("SELECT * FROM print_runs ORDER BY created_at, run_id").fetchall()]

# 1. модуль создаёт отдельную farm_quality.db в DATA_DIR
qdb_path = os.path.join(tmp, "farm_quality.db")
check("1. модуль создал СВОЮ farm_quality.db в DATA_DIR", os.path.isfile(qdb_path))

# 2. схема создаётся повторно безопасно (вкл. таблицу алиасов)
qb._init_tables()
with qb.lock_q:
    idx = [r[0] for r in qb.conn_q.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_pruns_%'").fetchall()]
    mode = qb.conn_q.execute("PRAGMA journal_mode").fetchone()[0]
    tables = {r[0] for r in qb.conn_q.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    aidx = qb.conn_q.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_prea_persistent'").fetchone()
    puniq = qb.conn_q.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_prm_run_pos'").fetchone()
check("2. повторная инициализация идемпотентна (print_runs + 7 индексов + алиасы + материалы + UNIQUE + WAL)",
      len(idx) == 7 and mode == "wal" and "print_run_event_aliases" in tables
      and "print_run_materials" in tables and bool(aidx) and bool(puniq))

# 3. started event создаёт run
started(snap("run_a", "filea"))
check("3. started → запись running", len(rows()) == 1 and rows()[0]["outcome_raw"] == "running")

# 4. повторный started с тем же run_id не создаёт дубль
started(snap("run_a", "filea"))
check("4. повторный started (тот же run_id) — без дубля", len(rows()) == 1)

# 5. finished завершает нужный run (+ orphan с полным снапшотом создаёт терминальную запись)
finished(snap("run_a", "filea", outcome_raw="finished", terminal_reason="printer_state:FINISH",
              finished_at="2026-07-11 11:00:00", elapsed_s=3600, final_percent=100))
finished(snap("run_orphan", "orphan", outcome_raw="failed", terminal_reason="printer_state:FAILED",
              finished_at="2026-07-11 11:05:00", elapsed_s=60, final_percent=5))
ra = [r for r in rows() if r["run_id"] == "run_a"][0]
orph = [r for r in rows() if r["run_id"] == "run_orphan"]
check("5. finished → терминальный UPDATE; orphan-finished с полным снапшотом сохранён",
      ra["outcome_raw"] == "finished" and ra["final_percent"] == 100.0
      and len(orph) == 1 and orph[0]["outcome_raw"] == "failed")

# 6. повторный finished не меняет терминальный исход
finished(snap("run_a", "filea", outcome_raw="cancelled", terminal_reason="x", final_percent=1))
check("6. повторный finished игнорируется (исход не переписан)",
      [r for r in rows() if r["run_id"] == "run_a"][0]["outcome_raw"] == "finished")

# 7. PAUSED не приходит как терминал (ядро гарантирует) — запись остаётся running до finished
started(snap("run_b", "fileb"))
check("7. без finished запись остаётся running (пауза не терминал по контракту ядра)",
      [r for r in rows() if r["run_id"] == "run_b"][0]["outcome_raw"] == "running")

# ── Recovery по инварианту run_id: persistent id НИКОГДА не меняется, event id связывается алиасом ──
def alias_of(eid):
    with qb.lock_q:
        r = qb.conn_q.execute("SELECT persistent_run_id FROM print_run_event_aliases WHERE event_run_id=?", (eid,)).fetchone()
    return r["persistent_run_id"] if r else None

# 8. рестарт ядра во время ТОЙ ЖЕ печати: новый event id 'run_b2' для printer/file run_b
started(snap("run_b2", "fileb"))
only_b = [r for r in rows() if r["file_norm"] == "fileb"]
check("8. persistent run_id сохранён: одна строка fileb, run_id='run_b', started_at первоначальный; alias B→A создан",
      len(only_b) == 1 and only_b[0]["run_id"] == "run_b"
      and only_b[0]["started_at"] == "2026-07-11 10:00:00" and alias_of("run_b2") == "run_b")

# 8b. единый резолвер: прямое совпадение, алиас, сирота
check("8b. resolve_persistent_run_id: direct / alias / orphan=None",
      qb.resolve_persistent_run_id("run_b") == "run_b"
      and qb.resolve_persistent_run_id("run_b2") == "run_b"
      and qb.resolve_persistent_run_id("run_nonexistent") is None)

# 8c. дочерняя fixture-запись, ссылающаяся на persistent id A
with qb.lock_q:
    qb.conn_q.execute("CREATE TABLE IF NOT EXISTS test_child (id TEXT PRIMARY KEY, run_id TEXT)")
    qb.conn_q.execute("INSERT OR IGNORE INTO test_child VALUES ('child1', 'run_b')")
    qb.conn_q.commit()

# 8d. перезагрузка backend МЕЖДУ started B и finished B: алиас в БД, не в памяти
spec2 = importlib.util.spec_from_file_location("quality_backend_test2", os.path.join(REPO, "modules", "quality", "backend.py"))
qb2 = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(qb2)
fc2 = FakeCore()
qb2.register(fc2)
fc2.hooks["print_run_finished"](snap("run_b2", "fileb", outcome_raw="finished",
                                     terminal_reason="printer_state:FINISH",
                                     finished_at="2026-07-11 12:00:00", elapsed_s=7200, final_percent=100))
rb = [r for r in rows() if r["run_id"] == "run_b"][0]
check("8d. finished с event id B (после перезагрузки модуля) завершил строку A через алиас",
      rb["outcome_raw"] == "finished" and rb["final_percent"] == 100.0)
fc2.hooks["print_run_finished"](snap("run_b2", "fileb", outcome_raw="failed", terminal_reason="x", final_percent=1))
check("8e. повторный finished с event id B не меняет терминальный исход",
      [r for r in rows() if r["run_id"] == "run_b"][0]["outcome_raw"] == "finished")
with qb.lock_q:
    child = qb.conn_q.execute("SELECT pr.outcome_raw AS o FROM test_child c JOIN print_runs pr ON pr.run_id=c.run_id WHERE c.id='child1'").fetchone()
check("8f. дочерняя запись осталась связанной с A после recovery", child and child["o"] == "finished")

# 9. другой файл закрывает running как superseded и создаёт НОВЫЙ persistent run
started(snap("run_d", "filed"))
started(snap("run_e", "filee"))
rd = [r for r in rows() if r["run_id"] == "run_d"][0]
check("9. другой файл → прежняя запись unknown/superseded_by_new_job, новая строка создана",
      rd["outcome_raw"] == "unknown" and rd["terminal_reason"] == "superseded_by_new_job"
      and any(r["run_id"] == "run_e" and r["outcome_raw"] == "running" for r in rows()))

# 9b. в backend.py нет UPDATE первичного ключа run_id (инвариант зафиксирован по исходнику)
import re as _re
_src = open(os.path.join(REPO, "modules", "quality", "backend.py"), encoding="utf-8").read()
check("9b. в backend.py отсутствует UPDATE print_runs SET run_id",
      not _re.search(r"UPDATE\s+print_runs\s+SET\s+run_id", _src, _re.IGNORECASE)
      and "INSERT OR IGNORE INTO print_run_event_aliases" in _src)

# ══ Снимок материалов ПО НАЗНАЧЕНИЯМ ЗАДАНИЯ (v0.2.0, семантическая правка) ══
# Инвариант: пишем ТОЛЬКО материалы, назначенные конкретному заданию (material_assignments),
# сопоставленные с привязанной катушкой. «Все непустые слоты AMS» не сохраняются никогда.
def mats(rid):
    with qb.lock_q:
        return [dict(r) for r in qb.conn_q.execute(
            "SELECT * FROM print_run_materials WHERE persistent_run_id=? ORDER BY ams_slot, id", (rid,)).fetchall()]

def _slot(idx, sid, material="PLA", vendor="Bambu", lot="", unit="0", external=False, remaining=800.0,
          total=1000.0, color="00A0E3", diameter=1.75, fil_id="fil1", ven_id="v1"):
    return {"index": idx, "unit": unit, "tray": None, "external": external, "offline": False,
            "spool": {"id": sid, "vendor_name": vendor, "material": material, "color_name": "", "color_hex": color,
                      "weight_remaining_g": remaining, "weight_total_g": total, "label": "", "filament_id": fil_id,
                      "vendor_id": ven_id, "diameter": diameter, "lot": lot, "opened_at": "", "purchased_at": ""}}

def _fil(has_ams, *sl):
    return {"has_ams": has_ams, "slots": list(sl)}

def _asg(filament_index, ams_slot, external=False, planned_g=None):
    return {"filament_index": filament_index, "ams_slot": ams_slot, "external": external, "planned_g": planned_g}

def snapM(run_id, fn, pid, assignments=None, planned=None):
    prof = {"layer_height": "0.2"}
    if planned is not None:
        prof["planned_weight_g"] = planned
    s = snap(run_id, fn, pid=pid, profile_snapshot=prof)
    s["material_assignments"] = list(assignments or [])
    return s

# M1: 4 привязанных катушки в AMS, назначен только слот 2 → РОВНО одна строка (slot 2)
fc.filament["pm1"] = _fil(True, _slot(0, "sA"), _slot(1, "sB"),
                          _slot(2, "sC", material="PETG", vendor="V2", lot="L2", remaining=850.0), _slot(3, "sD"))
started(snapM("rm1", "fm1", "pm1", assignments=[_asg(0, 2, planned_g=120.0)], planned=120.0))
m1 = mats("rm1")
check("M1. 4 катушки в AMS, назначен только слот 2 → ровно одна строка (slot 2), денормализована",
      len(m1) == 1 and m1[0]["spool_id"] == "sC" and m1[0]["ams_slot"] == 2 and m1[0]["material"] == "PETG"
      and m1[0]["lot"] == "L2" and m1[0]["remaining_g_at_capture"] == 850.0
      and m1[0]["planned_g"] == 120.0 and m1[0]["allocation_confidence"] == "exact")

# M2: повторный started того же задания — без дубля
started(snapM("rm1", "fm1", "pm1", assignments=[_asg(0, 2, planned_g=120.0)], planned=120.0))
check("M2. повторный started → дубля материала нет", len(mats("rm1")) == 1)

# M3: назначены слоты 0 и 3 → РОВНО две строки; привязанные слоты 1,2 исключены
fc.filament["pm3"] = _fil(True, _slot(0, "sB0", material="PLA", lot="LB0"), _slot(1, "sB1"),
                          _slot(2, "sB2"), _slot(3, "sB3", material="PETG", lot="LB3"))
started(snapM("rm3", "fm3", "pm3", assignments=[_asg(0, 0, planned_g=100.0), _asg(1, 3, planned_g=80.0)], planned=180.0))
m3 = mats("rm3")
check("M3. назначены слоты 0 и 3 → ровно две строки; привязанные слоты 1,2 исключены",
      len(m3) == 2 and {r["ams_slot"] for r in m3} == {0, 3} and {r["spool_id"] for r in m3} == {"sB0", "sB3"})

# M4: 4 катушки, назначения НЕТ → ни одной строки (run сохраняется) — ГЛАВНЫЙ тест правки
fc.filament["pm4"] = _fil(True, _slot(0, "x0"), _slot(1, "x1"), _slot(2, "x2"), _slot(3, "x3"))
started(snapM("rm4", "fm4", "pm4", assignments=[]))
check("M4. 4 катушки, назначения нет → ни одной строки; run записан",
      len(mats("rm4")) == 0 and any(r["run_id"] == "rm4" for r in rows()))

# M5: non-AMS однофиламентный + явное внешнее назначение → одна строка exact/external
fc.filament["pm5"] = _fil(False, _slot(0, "ext0", material="PLA", unit=None, external=True))
started(snapM("rm5", "fm5", "pm5", assignments=[_asg(0, 0, external=True, planned_g=50.0)], planned=50.0))
m5 = mats("rm5")
check("M5. non-AMS + внешнее назначение → одна строка, source_type=external, exact",
      len(m5) == 1 and m5[0]["spool_id"] == "ext0" and m5[0]["source_type"] == "external"
      and m5[0]["allocation_confidence"] == "exact")

# M6: назначение в пустой слот (нет привязанной катушки) → строк нет, status partial
fc.filament["pm6"] = _fil(True, _slot(0, "only0"))
started(snapM("rm6", "fm6", "pm6", assignments=[_asg(0, 2, planned_g=30.0)]))
det6 = qb.api_q_print_run_one("rm6")
check("M6. назначение в пустой слот → строк нет, capture_status=partial",
      len(mats("rm6")) == 0 and det6["material_assignment_count"] == 1 and det6["material_capture_status"] == "partial")

# M7: два назначения, совпало одно → одна строка, status partial
fc.filament["pm7"] = _fil(True, _slot(0, "g0", material="PLA"))
started(snapM("rm7", "fm7", "pm7", assignments=[_asg(0, 0, planned_g=40.0), _asg(1, 1, planned_g=20.0)], planned=60.0))
det7 = qb.api_q_print_run_one("rm7")
check("M7. два назначения, совпало одно → одна строка (slot 0), status partial",
      len(mats("rm7")) == 1 and mats("rm7")[0]["ams_slot"] == 0
      and det7["material_matched_count"] == 1 and det7["material_assignment_count"] == 2
      and det7["material_capture_status"] == "partial")

# M8: слот, не участвующий в задании, никогда не в snapshot (по rm1/rm3)
check("M8. неучаствующие слоты не попали в snapshot",
      {r["ams_slot"] for r in mats("rm1")} == {2} and {r["ams_slot"] for r in mats("rm3")} == {0, 3})

# M9: пофиламентные веса связаны через filament_index (slot0=100, slot3=80, exact)
m3map = {r["ams_slot"]: r for r in mats("rm3")}
check("M9. пофиламентный вес связан через filament_index",
      m3map[0]["planned_g"] == 100.0 and m3map[3]["planned_g"] == 80.0
      and m3map[0]["allocation_confidence"] == "exact" and m3map[3]["allocation_confidence"] == "exact")

# M10: общий вес многоцветной печати НЕ суммируется дважды (planned_total_g ровно на одной строке)
tot3 = [r["planned_total_g"] for r in mats("rm3") if r["planned_total_g"] is not None]
check("M10. planned_total_g ровно на одной строке (нет двойного суммирования), = 180",
      len(tot3) == 1 and tot3[0] == 180.0)

# M11: recovery alias НЕ меняет первоначальные материалы (даже при другом provider/назначении)
fc.filament["pm1"] = _fil(True, _slot(2, "CHANGED", material="ABS", vendor="NEW", lot="ZZ"))
started(snapM("rm1b", "fm1", "pm1", assignments=[_asg(0, 2, planned_g=999.0)]))   # alias к rm1
m1r = mats("rm1")
check("M11. recovery alias не меняет исходный снимок, дубля нет, alias создан",
      len(m1r) == 1 and m1r[0]["spool_id"] == "sC" and m1r[0]["planned_g"] == 120.0 and alias_of("rm1b") == "rm1")

# M12: resume без назначений НЕ захватывает все катушки; с доказанным назначением — захватывает
fc.filament["pm12"] = _fil(True, _slot(0, "r0"), _slot(1, "r1"), _slot(2, "r2"), _slot(3, "r3"))
started(snapM("rm12a", "fm12", "pm12", assignments=[]))          # старт без назначения → 0 материалов
check("M12a. старт без назначения → 0 материалов (4 катушки НЕ захвачены)", len(mats("rm12a")) == 0)
started(snapM("rm12b", "fm12", "pm12", assignments=[]))          # resume без назначения → всё ещё 0
check("M12b. resume без назначения НЕ захватывает все катушки", len(mats("rm12a")) == 0)
started(snapM("rm12c", "fm12", "pm12", assignments=[_asg(0, 1, planned_g=10.0)]))   # resume с назначением
m12 = mats("rm12a")
check("M12c. resume с доказанным назначением → одна строка (slot 1), phase=resume",
      len(m12) == 1 and m12[0]["ams_slot"] == 1 and m12[0]["capture_phase"] == "resume")

# M13: screen-печать без надёжного mapping → материалов нет, status unavailable
fc.filament["pm13"] = _fil(True, _slot(0, "s0"), _slot(1, "s1"))
started(snapM("rm13", "fm13", "pm13", assignments=[]))
det13 = qb.api_q_print_run_one("rm13")
check("M13. screen-печать без mapping → материалов нет, status unavailable",
      len(mats("rm13")) == 0 and det13["material_capture_status"] == "unavailable")

# M14: нет provider → run сохраняется, материалов нет
started(snapM("rm14", "fm14", "pm14_none", assignments=[_asg(0, 0, planned_g=10.0)]))
check("M14. нет provider → run записан, материалов нет",
      any(r["run_id"] == "rm14" for r in rows()) and len(mats("rm14")) == 0)

# M15: провайдер падает → started не падает, run записан
fc.filament_raises.add("pm15")
crashed = False
try:
    started(snapM("rm15", "fm15", "pm15", assignments=[_asg(0, 0, planned_g=5.0)]))
except Exception:
    crashed = True
check("M15. провайдер бросает исключение → started не падает, run записан, материалов нет",
      not crashed and any(r["run_id"] == "rm15" for r in rows()) and len(mats("rm15")) == 0)
fc.filament_raises.discard("pm15")

# M16: API detail — materials[]+snapshot + диагностика; отдельный materials-эндпоинт
det = qb.api_q_print_run_one("rm3")
check("M16. detail: materials[]+snapshot + diagnostics (assignment=2/matched=2/status=exact)",
      isinstance(det.get("materials"), list) and len(det["materials"]) == 2
      and isinstance(det["materials"][0].get("snapshot"), dict)
      and det["material_assignment_count"] == 2 and det["material_matched_count"] == 2
      and det["material_capture_status"] == "exact")
me = qb.api_q_print_run_materials("rm3")
check("M16b. API /print-runs/{id}/materials работает", isinstance(me.get("materials"), list) and len(me["materials"]) == 2)

# M17: список /print-runs НЕ тянет snapshot_json/materials
lst = qb.api_q_print_runs(limit=5)
check("M17. список /print-runs без snapshot_json/materials",
      all("materials" not in r and "snapshot_json" not in r for r in lst["runs"]))

# M18: summary — capture rate + материалы в recent
sm = qb.api_q_summary()
check("M18. summary: runs_with_material/without/ capture_rate + материалы в recent",
      "runs_with_material" in sm and "runs_without_material" in sm and "material_capture_rate" in sm
      and sm["runs_with_material"] >= 3 and 0.0 <= sm["material_capture_rate"] <= 1.0
      and all("materials" in r for r in sm["recent"]))

# M19: ИНВАРИАНТ — захват строго по material_assignments, а не по всем слотам провайдера
qsrc = open(os.path.join(REPO, "modules", "quality", "backend.py"), encoding="utf-8").read()
check("M19. инвариант: захват по material_assignments (нет «все непустые слоты = использованные»)",
      "material_assignments" in qsrc and "if not assignments" in qsrc
      and "for a in assignments" in qsrc and "prov.get(slot)" in qsrc)

# M20/M21: нет прямой зависимости от склада (функциональные маркеры кода, не прозы в комментариях)
check("M20. нет импорта склада и HTTP-клиента; данные — только через generic-геттер ядра",
      _re.search(r"(?m)^\s*(?:from|import)\b.*inventory", qsrc) is None
      and "fm_module_inventory" not in qsrc
      and _re.search(r"\b(?:requests|urllib|httpx|http\.client|urlopen|aiohttp)\b", qsrc) is None
      and "get_printer_filament_snapshot" in qsrc)
check("M21. нет прямого открытия farm_inventory.db (нет resolve_db/connect к складу)",
      _re.search(r"""resolve_db\(\s*['"]farm_inventory""", qsrc) is None
      and _re.search(r"connect\([^)\n]*inventory", qsrc) is None)

# M22: переустановка/reload backend на ту же farm_quality.db не теряет данные
before = len(mats("rm1"))
qb.register(FakeCore())
check("M22. переустановка модуля не удаляет farm_quality.db (материалы на месте)",
      len(mats("rm1")) == before == 1)

# 10. фильтры API/helper
flt = qb.q_query(printer_id="p1", outcome="failed")
check("10. фильтры query работают", len(flt) == 1 and flt[0]["run_id"] == "run_orphan"
      and isinstance(flt[0].get("profile_snapshot"), dict))

# 11. limit clamp
check("11. limit clamp 1..500 (+ limit=2 работает)",
      len(qb.q_query(limit=99999)) == len(rows()) and len(qb.q_query(limit=2)) == 2)

# 12. ошибка БД модуля не влияет на simulated core callback
qb.conn_q.close()   # имитация мёртвой БД модуля
try:
    started(snap("run_dead", "filedead"))
    finished(snap("run_dead", "filedead", outcome_raw="finished"))
    survived = True
except Exception:
    survived = False
check("12. падение БД модуля не выбрасывается в ядро (callback выживает)", survived)

# 13. zip модуля собирается и не содержит БД/мусора
r = subprocess.run([sys.executable, os.path.join(REPO, "tools", "build_quality_zip.py")],
                   capture_output=True, text=True)
zip_path = os.path.join(REPO, "modules", "3diwell-module-quality.zip")   # сборщик пишет в modules/ (с 11.09.2026)
zok = False
if r.returncode == 0 and os.path.isfile(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        zbk = z.read("quality/backend.py").decode("utf-8", "ignore")
        zmj = json.loads(z.read("quality/module.json"))
        zok = ("quality/module.json" in names and "quality/backend.py" in names
               and "quality/web/QualityPanel.js" in names and zmj.get("version") == "0.2.3"
               and "print_run_event_aliases" in zbk and "print_run_materials" in zbk   # ОБНОВЛЁННЫЙ backend
               and not [n for n in names if n.lower().endswith((".db", ".db-wal", ".db-shm", ".pyc"))
                        or "__pycache__" in n.lower() or "new folder" in n.lower()])
check("13. zip собран: module.json(0.2.3)+backend(материалы)+web, без БД/__pycache__/мусора", zok)

# ── UI-инварианты окна (v0.2.1): компактная шапка, ограниченная иконка (§7 Quality) ──
qui = open(os.path.join(REPO, "modules", "quality", "web", "QualityPanel.js"), encoding="utf-8").read()
check("U1. иконка header ограничена: scoped .quality-ico svg{24px} + фикс-бокс 44px + явный 24px на svg-icon",
      ".quality-ico svg{width:24px" in qui and "width:44px;height:44px" in qui and "width:24px;height:24px;display:block" in qui)
check("U2. внутренний SVG не растянется (нет w-5 h-5 / width:100% / height:auto у header-иконки)",
      'class="w-5 h-5"' not in qui and _re.search(r"svg-icon[^>]*width:100%", qui) is None and "height:auto" not in qui)
check("U3. шапка горизонтальная и фиксированная (flex align-items:center, flex:0 0 auto, subtitle)",
      "flex:0 0 auto;display:flex;align-items:center" in qui and "История печатей, материалов и результатов" in qui)
check("U4. content не смещён иконкой: единственная прокрутка content (flex:1 min-height:0 overflow-y:auto)",
      "flex:1 1 auto;min-height:0;overflow-y:auto" in qui and qui.count("overflow-y:auto") == 1)
check("U5. окно в пределах viewport (max-height min(...,calc(100vh - 40px)))",
      "calc(100vh - 40px)" in qui and "calc(100vw - 40px)" in qui and ";overflow:hidden" in qui)
check("U6. стили только локальные .quality-* (нет глобальных селекторов; head-инъекция по id)",
      "quality-panel-styles" in qui and _re.search(r"(?m)^\s*(?:svg|div|span|button)\s*\{", qui) is None)
check("U7. Escape/Close не сломаны (backdrop @click + кнопка Закрыть → $emit('close'))",
      qui.count("@click=\"$emit('close')\"") >= 2 and "'Закрыть','Close'" in qui)

print("\n" + ("FAIL: %d проверок провалено" % _fail if _fail else "PASS: модуль quality — все %d проверок пройдены" % _total))
sys.exit(1 if _fail else 0)
