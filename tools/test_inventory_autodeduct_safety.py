# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# БЕЗОПАСНОСТЬ автосписания при внешней подаче ams_slot=-1 (Alpha 2.737 / inventory 1.7.20).
# Проверяет, что внешнее назначение печати (slot=-1) НИКОГДА не списывает материал из НАСТОЯЩЕГО AMS-слота 0,
# и что legacy-fallback -1 -> слот 0 срабатывает ТОЛЬКО при свежем однозначном подтверждении отсутствия AMS.
# Ключевые функции: _inv_match_bound_spool_id (сопоставление слота печати -> id катушки), _printer_confirmed_no_ams
# (свежесть/no-AMS через core.get_printer_reported_filament), _inv_autodeduct / inv_check_print.
#
# ВРЕМЕННАЯ тестовая БД (реальная DATA_DIR не трогается). _inv_gcode_weights монки-патчится (веса задаём явно).
# Запуск:  python tools/test_inventory_autodeduct_safety.py   (0 = все тесты пройдены)
# ============================================================================
import importlib.util
import logging
import os
import sqlite3
import sys
import tempfile
import threading

logging.getLogger("fm.mod.inventory").setLevel(logging.CRITICAL)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(REPO, "modules", "inventory", "backend.py")

fail = 0
def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


class FakeCore:
    def __init__(self):
        self._n = 0
        self._printers = []
        self._states = {}
        self._reported = {}
    def new_id(self, prefix=""):
        self._n += 1
        return str(prefix) + format(self._n, "08d")
    def printers(self):
        return list(self._printers)
    def printer_states(self):
        return dict(self._states)
    def get_printer_reported_filament(self, pid):
        return dict(self._reported.get(pid) or {"telemetry_available": False, "telemetry_fresh": False, "positions": []})


REP_LIVE_AMS = {"telemetry_available": True, "telemetry_fresh": True,
                "positions": [{"index": i, "external": False} for i in range(4)]}          # свежий живой AMS (слоты 0..3)
REP_FRESH_NOAMS = {"telemetry_available": True, "telemetry_fresh": True,
                   "positions": [{"index": None, "external": True}]}                        # свежий no-AMS: только external
REP_OFFLINE = {"telemetry_available": False, "telemetry_fresh": False, "positions": []}     # offline/stale


def load_backend(dbpath, core):
    spec = importlib.util.spec_from_file_location("inv_backend_dedtest", BACKEND)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.core = core
    m.conn_inv = sqlite3.connect(dbpath, check_same_thread=False)
    m.conn_inv.row_factory = sqlite3.Row
    m.lock_inv = threading.RLock()
    m._init_tables()
    m._inv_gcode_weights = lambda fdata: (list(fdata) if isinstance(fdata, (list, tuple)) else [])   # веса = переданный список
    m._pending_open = lambda *a, **k: None   # изолируем сопоставление-списание от механизма возврата филамента (отдельная фича)
    return m


def mk(m):
    return m.inv_create_spool({"filament": {"material": "PLA", "color_name": "c"},
                               "weight_total_g": 1000, "weight_remaining_g": 1000, "status": "in_stock"})["id"]


def wt(m, sid):
    return float(m.conn_inv.execute("SELECT weight_remaining_g FROM inv_spools WHERE id=?", (sid,)).fetchone()[0])


def led_out(m, sid):
    return m.conn_inv.execute("SELECT COUNT(*) FROM inv_ledger WHERE ref_type='spool' AND ref_id=? AND kind='out'", (sid,)).fetchone()[0]


def bind_legacy0(m, sid, pid):
    m.conn_inv.execute("UPDATE inv_spools SET ams_printer_id=?, ams_slot=0, status='loaded' WHERE id=?", (pid, sid))
    m.conn_inv.commit()


def main():
    fd, db = tempfile.mkstemp(suffix=".db", prefix="fm_deduct_")
    os.close(fd)
    try:
        core = FakeCore()
        core._printers = [{"id": p, "name": p} for p in ("MX", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P9")]   # для inv_ams_overview/provider
        m = load_backend(db, core)

        # ── прямые unit-проверки безопасного матчера/классификатора ──
        core._reported = {"U_AMS": REP_LIVE_AMS, "U_NO": REP_FRESH_NOAMS, "U_OFF": REP_OFFLINE}
        check("U1. _printer_confirmed_no_ams: живой AMS -> False; свежий no-AMS -> True; offline/stale -> False",
              m._printer_confirmed_no_ams("U_AMS") is False
              and m._printer_confirmed_no_ams("U_NO") is True
              and m._printer_confirmed_no_ams("U_OFF") is False)
        sA = mk(m); m.inv_bind_spool(sA, "MX", 0); s5 = mk(m); m.inv_bind_spool(s5, "MX", 5)
        with m.lock_inv:
            match_ams = m._inv_match_bound_spool_id("MX", 0, False)
            match_5 = m._inv_match_bound_spool_id("MX", 5, False)
            match_ext_noconfirm = m._inv_match_bound_spool_id("MX", -1, False)   # нет -1, no_ams=False -> None (не откат к 0!)
        check("U2. matcher: AMS-слот -> точное совпадение (0->A, 5->A5); внешняя -1 БЕЗ -1-катушки и БЕЗ подтверждения no-AMS -> None (живой AMS0 защищён)",
              match_ams == sA and match_5 == s5 and match_ext_noconfirm is None)

        # ── 1. Один принтер: external E(-1) + AMS A(0); внешнее назначение -1 списывает ТОЛЬКО E ──
        core._reported["P1"] = REP_LIVE_AMS
        E = mk(m); m.inv_bind_spool(E, "P1", -1, external=True)
        A = mk(m); m.inv_bind_spool(A, "P1", 0)
        m._inv_autodeduct("P1", [], [10.0], "f1.gcode")   # пустой map = внешняя подача
        check("1. external assignment=-1: списан ТОЛЬКО E (-10 г), AMS A(0) не изменён, ledger 'out' один раз только у E",
              abs(wt(m, E) - 990.0) < 1e-6 and abs(wt(m, A) - 1000.0) < 1e-6 and led_out(m, E) == 1 and led_out(m, A) == 0)

        # ── 2. Живой AMS, external -1 ОТСУТСТВУЕТ, есть AMS0; внешнее назначение -1 НЕ списывает AMS0 (fail-open) ──
        core._reported["P2"] = REP_LIVE_AMS
        A2 = mk(m); m.inv_bind_spool(A2, "P2", 0)
        m._inv_autodeduct("P2", [], [10.0], "f2.gcode")
        check("2. живой AMS, нет external -1: внешнее назначение -1 КАТЕГОРИЧЕСКИ не списывает AMS0 (fail-open, без ledger)",
              abs(wt(m, A2) - 1000.0) < 1e-6 and led_out(m, A2) == 0)

        # ── 3. AMS назначение=0 списывает ТОЛЬКО AMS0; external -1 не тронут ──
        core._reported["P3"] = REP_LIVE_AMS
        E3 = mk(m); m.inv_bind_spool(E3, "P3", -1, external=True)
        A3 = mk(m); m.inv_bind_spool(A3, "P3", 0)
        m._inv_autodeduct("P3", [0], [10.0], "f3.gcode")   # AMS слот 0
        check("3. AMS assignment=0: списан ТОЛЬКО AMS0 (-10 г), external -1 не изменён, ledger только у AMS0",
              abs(wt(m, A3) - 990.0) < 1e-6 and abs(wt(m, E3) - 1000.0) < 1e-6 and led_out(m, A3) == 1 and led_out(m, E3) == 0)

        # ── 4. Legacy no-AMS, external на слоте 0, свежее подтверждение no-AMS: -1 находит legacy 0, списание один раз ──
        core._reported["P4"] = REP_FRESH_NOAMS
        L = mk(m); bind_legacy0(m, L, "P4")
        m._inv_autodeduct("P4", [], [10.0], "f4.gcode")
        check("4. legacy no-AMS (external слот 0) + свежее подтверждение: внешнее -1 находит legacy 0, списано РОВНО один раз (-10 г)",
              abs(wt(m, L) - 990.0) < 1e-6 and led_out(m, L) == 1)

        # ── 5. Offline/stale: slot 0 НЕЛЬЗЯ считать legacy external -> ничего не списываем ──
        core._reported["P5"] = REP_OFFLINE
        O = mk(m); bind_legacy0(m, O, "P5")   # на самом деле это может быть настоящий AMS0 offline-принтера
        m._inv_autodeduct("P5", [], [10.0], "f5.gcode")
        ok5_off = abs(wt(m, O) - 1000.0) < 1e-6 and led_out(m, O) == 0
        core._reported["P5"] = REP_FRESH_NOAMS   # после восстановления связи и подтверждения no-AMS
        m._inv_autodeduct("P5", [], [10.0], "f5b.gcode")
        check("5. offline/stale: slot0 не списан (неоднозначность -> fail-open); после свежего подтверждения no-AMS — корректно списывается",
              ok5_off and abs(wt(m, O) - 990.0) < 1e-6 and led_out(m, O) == 1)

        # ── 6. Был no-AMS, появился live AMS: legacy slot0 не считается ОДНОВРЕМЕННО external и AMS0; без двойного ledger ──
        core._reported["P6"] = REP_LIVE_AMS   # теперь живой AMS
        S0 = mk(m); bind_legacy0(m, S0, "P6")
        m._inv_autodeduct("P6", [], [10.0], "f6ext.gcode")   # внешнее назначение -1: live AMS -> НЕ откатывается к слоту 0
        after_ext = wt(m, S0)
        m._inv_autodeduct("P6", [0], [10.0], "f6ams.gcode")  # AMS назначение 0: слот 0 = настоящий AMS0
        check("6. live AMS + slot0-запись: внешнее -1 её НЕ трогает; AMS0 списывает её как обычный слот; двойного ledger нет (ровно 1 'out')",
              abs(after_ext - 1000.0) < 1e-6 and abs(wt(m, S0) - 990.0) < 1e-6 and led_out(m, S0) == 1)

        # ── 7. Multi-AMS/HT: 5 и 512 — как AMS; external -1 их не затрагивает ──
        core._reported["P7"] = REP_LIVE_AMS
        A5 = mk(m); m.inv_bind_spool(A5, "P7", 5)
        A512 = mk(m); m.inv_bind_spool(A512, "P7", 512)
        E7 = mk(m); m.inv_bind_spool(E7, "P7", -1, external=True)
        m._inv_autodeduct("P7", [5], [10.0], "f7a.gcode")
        m._inv_autodeduct("P7", [512], [7.0], "f7b.gcode")
        m._inv_autodeduct("P7", [], [3.0], "f7c.gcode")
        check("7. multi-AMS/HT: слот5 -> A5(-10), слот512 -> A512(-7), внешняя -1 -> E7(-3); каждое точно, без перекрёстного списания",
              abs(wt(m, A5) - 990.0) < 1e-6 and abs(wt(m, A512) - 993.0) < 1e-6 and abs(wt(m, E7) - 997.0) < 1e-6
              and led_out(m, A5) == 1 and led_out(m, A512) == 1 and led_out(m, E7) == 1)

        # ── 8. Quality/Cost: build_assignments внешней подачи = -1 (совпадает с overview/provider index -1); схема не меняется ──
        BA = m if hasattr(m, "build_assignments") else None
        import importlib.util as _il
        pre = _il.spec_from_file_location("_pre_ev", os.path.join(REPO, "app", "print_run_events.py"))
        ev = _il.module_from_spec(pre); pre.loader.exec_module(ev)
        asg = ev.build_assignments([], [40.0], True)   # внешняя печать
        prov = m._inv_filament_provider()
        pslots = prov.get("P7", {}).get("slots", [])
        ext_prov = next((s for s in pslots if s.get("external")), None)
        check("8. quality/cost: build_assignments внешней подачи -> ams_slot=-1; provider external index=-1 (совпадение assignment<->snapshot), схема БД не менялась",
              asg == [{"filament_index": 0, "ams_slot": -1, "external": True, "planned_g": 40.0}]
              and ext_prov is not None and ext_prov["index"] == -1)

        # ── 9. Exactly-once: один вызов autodeduct -> ровно одно 'out'-списание на филамент ──
        core._reported["P9"] = REP_FRESH_NOAMS
        N = mk(m); m.inv_bind_spool(N, "P9", -1, external=True)
        m._inv_autodeduct("P9", [], [12.0], "f9.gcode")
        check("9. exactly-once: один вызов after_dispatch/autodeduct -> ровно одно 'out'-списание (-12 г), одна ledger-строка (повтор события — на уровне пайплайна: один after_dispatch на dispatch)",
              abs(wt(m, N) - 988.0) < 1e-6 and led_out(m, N) == 1)

        print("\n" + ("FAIL: " + str(fail) + " проверок провалено" if fail else
              "PASS: внешнее назначение -1 НИКОГДА не списывает живой AMS0; legacy fallback -1->0 только при свежем однозначном подтверждении отсутствия AMS; offline/stale -> fail-open; multi-AMS/HT точны; build_assignments external=-1; exactly-once"))
        return 1 if fail else 0
    finally:
        try:
            m.conn_inv.close()
        except Exception:
            pass
        try:
            os.remove(db)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
