# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# БЕЗОПАСНАЯ КЛАССИФИКАЦИЯ inv_ams_overview для внешней подачи ams_slot=-1 (Alpha 2.737 / inventory 1.7.20).
# Гарантирует, что РЕАЛЬНАЯ AMS-катушка слота 0 (в т.ч. на offline/stale-принтере) НИКОГДА не показывается во
# внешней ячейке (где её можно ошибочно отвязать). Точная -1 — всегда external; legacy слот 0 — external лишь при
# СВЕЖЕМ подтверждении отсутствия AMS (_printer_confirmed_no_ams); иначе слот 0 — нейтральная «unconfirmed»-позиция.
#
# Сценарии A-H (временная БД; реальная DATA_DIR не трогается).
# Запуск:  python tools/test_inventory_overview_classification.py   (0 = все тесты пройдены)
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


def set_live_ams(core, pid, n=4):
    core._states[pid] = {"ams_trays": [{"index": i, "unit": 0, "tray": i} for i in range(n)]}
    core._reported[pid] = {"telemetry_available": True, "telemetry_fresh": True,
                           "positions": [{"index": i, "external": False} for i in range(n)]}
def set_offline(core, pid):
    core._states[pid] = {}
    core._reported[pid] = {"telemetry_available": False, "telemetry_fresh": False, "positions": []}
def set_stale(core, pid):
    core._states[pid] = {}
    core._reported[pid] = {"telemetry_available": True, "telemetry_fresh": False, "positions": []}
def set_fresh_noams(core, pid):   # свежий online no-AMS (Bambu без AMS ИЛИ Klipper/FF)
    core._states[pid] = {}
    core._reported[pid] = {"telemetry_available": True, "telemetry_fresh": True,
                           "positions": [{"index": None, "external": True}]}
def set_fresh_noams_klipper(core, pid):   # Klipper/FF: last_seen свежий, но НЕТ trays/ext (telemetry_available=False)
    core._states[pid] = {}
    core._reported[pid] = {"telemetry_available": False, "telemetry_fresh": True, "positions": []}


def load_backend(dbpath, core):
    spec = importlib.util.spec_from_file_location("inv_backend_ovtest", BACKEND)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.core = core
    m.conn_inv = sqlite3.connect(dbpath, check_same_thread=False)
    m.conn_inv.row_factory = sqlite3.Row
    m.lock_inv = threading.RLock()
    m._init_tables()
    return m


def mk(m):
    return m.inv_create_spool({"filament": {"material": "PLA", "color_name": "c"},
                               "weight_total_g": 1000, "weight_remaining_g": 1000, "status": "in_stock"})["id"]


def bind0(m, sid, pid):   # прямая привязка на слот 0 (эмуляция реального AMS0 ИЛИ legacy external)
    m.conn_inv.execute("UPDATE inv_spools SET ams_printer_id=?, ams_slot=0, status='loaded' WHERE id=?", (pid, sid))
    m.conn_inv.commit()


def main():
    fd, db = tempfile.mkstemp(suffix=".db", prefix="fm_ov_")
    os.close(fd)
    try:
        core = FakeCore()
        core._printers = [{"id": p, "name": p} for p in ("A", "B", "C", "D", "E", "F", "G", "H", "K")]
        m = load_backend(db, core)

        def slots(pid):
            for p in m.inv_ams_overview()["printers"]:
                if p["printer_id"] == pid:
                    return p["slots"]
            return []
        def ext_cell(pid):
            return next((s for s in slots(pid) if s.get("external")), None)
        def ams_cell(pid, idx):
            return next((s for s in slots(pid) if s.get("index") == idx and not s.get("external") and not s.get("unconfirmed")), None)
        def unc_cell(pid):
            return next((s for s in slots(pid) if s.get("unconfirmed")), None)
        def spid(cell):
            return (cell or {}).get("spool", {}) and (cell.get("spool") or {}).get("id")

        # ── A. Bambu live AMS + spool slot0 -> только AMS0; external свободна; external-cell не содержит AMS0 ──
        set_live_ams(core, "A"); A0 = mk(m); m.inv_bind_spool(A0, "A", 0)
        eA, a0A, uA = ext_cell("A"), ams_cell("A", 0), unc_cell("A")
        check("A. live AMS + slot0: показывается только AMS0 (спул в AMS-слоте 0); external свободна; external-ячейка НЕ получила spool id AMS0; unconfirmed нет",
              a0A and a0A.get("spool") and a0A["spool"]["id"] == A0
              and eA is not None and eA.get("spool") is None and uA is None)

        # ── B. Тот же принтер offline/stale -> AMS0 НЕ в external; unconfirmed; действий через external нет ──
        set_offline(core, "A")
        eB, uB = ext_cell("A"), unc_cell("A")
        check("B. тот же принтер offline: AMS0 НЕ переехал в external (external-ячейка пуста); спул виден как unconfirmed (не external, не AMS0)",
              eB is not None and eB.get("spool") is None
              and uB is not None and uB.get("spool") and uB["spool"]["id"] == A0 and not uB.get("external"))

        # ── C. Reconnect live AMS -> снова AMS0, без дублей ──
        set_live_ams(core, "A")
        a0C = ams_cell("A", 0)
        dup = sum(1 for s in slots("A") if s.get("spool") and s["spool"].get("id") == A0)
        check("C. reconnect live AMS: спул снова в AMS0; дублей нет (ровно одна ячейка со спулом A0)",
              a0C and a0C["spool"]["id"] == A0 and dup == 1 and unc_cell("A") is None)

        # ── D. Новый external slot=-1 при offline -> остаётся external; AMS0-запись отдельно/неподтверждена ──
        set_offline(core, "D"); Dext = mk(m); m.inv_bind_spool(Dext, "D", -1, external=True)
        Dams = mk(m); bind0(m, Dams, "D")
        eD, uD = ext_cell("D"), unc_cell("D")
        check("D. offline: точная external -1 остаётся external даже offline; отдельная slot0-запись — unconfirmed (не подменяет external)",
              eD and eD.get("spool") and eD["spool"]["id"] == Dext
              and uD and uD["spool"]["id"] == Dams)

        # ── E. Fresh confirmed no-AMS + legacy slot0 -> external (backward compatibility) ──
        set_fresh_noams(core, "E"); L = mk(m); bind0(m, L, "E")
        eE, uE = ext_cell("E"), unc_cell("E")
        check("E. свежий подтверждённый no-AMS + legacy slot0: показывается как external (обратная совместимость); unconfirmed нет",
              eE and eE.get("spool") and eE["spool"]["id"] == L and uE is None)
        # Klipper/FF (свежий, но telemetry_available=False) — тоже подтверждается no-AMS (last_seen свежий)
        set_fresh_noams_klipper(core, "K"); LK = mk(m); bind0(m, LK, "K")
        eK = ext_cell("K")
        check("E2. Klipper/FF (свежий online, без trays/ext_tray): legacy slot0 показывается как external (подтверждение по telemetry_fresh, БЕЗ требования telemetry_available; без догадок по модели)",
              eK and eK.get("spool") and eK["spool"]["id"] == LK)

        # ── F. Неоднозначная (stale) telemetry -> нет ложной классификации; БД/ledger/history не меняются ──
        set_stale(core, "F"); X = mk(m); bind0(m, X, "F")
        before_row = m.conn_inv.execute("SELECT ams_printer_id, ams_slot, weight_remaining_g FROM inv_spools WHERE id=?", (X,)).fetchone()
        before_led = m.conn_inv.execute("SELECT COUNT(*) FROM inv_ledger WHERE ref_id=?", (X,)).fetchone()[0]
        eF, uF, a0F = ext_cell("F"), unc_cell("F"), ams_cell("F", 0)
        after_row = m.conn_inv.execute("SELECT ams_printer_id, ams_slot, weight_remaining_g FROM inv_spools WHERE id=?", (X,)).fetchone()
        after_led = m.conn_inv.execute("SELECT COUNT(*) FROM inv_ledger WHERE ref_id=?", (X,)).fetchone()[0]
        check("F. stale telemetry: НЕ external и НЕ AMS0, а unconfirmed; БД (printer/slot/остаток) и ledger не изменились (read-only overview)",
              eF.get("spool") is None and a0F is None and uF is not None and uF["spool"]["id"] == X
              and tuple(after_row) == tuple(before_row) and after_led == before_led)

        # ── G. external -1 + AMS0 одновременно: online — две позиции; offline — external цел, AMS0 не подменяет; unbind external не трогает AMS0 ──
        set_live_ams(core, "G"); Ge = mk(m); m.inv_bind_spool(Ge, "G", -1, external=True); Ga = mk(m); m.inv_bind_spool(Ga, "G", 0)
        onE, onA = ext_cell("G"), ams_cell("G", 0)
        set_offline(core, "G")
        offE, offU = ext_cell("G"), unc_cell("G")
        m.inv_unbind_spool(Ge)   # отвязать external
        rGe = m.conn_inv.execute("SELECT ams_printer_id, ams_slot FROM inv_spools WHERE id=?", (Ge,)).fetchone()
        rGa = m.conn_inv.execute("SELECT ams_printer_id, ams_slot FROM inv_spools WHERE id=?", (Ga,)).fetchone()
        check("G. external -1 + AMS0: online — две отдельные позиции; offline — external(Ge) цел, AMS0(Ga) как unconfirmed (не подменяет external); unbind external НЕ трогает AMS0",
              onE and onE["spool"]["id"] == Ge and onA and onA["spool"]["id"] == Ga
              and offE and offE.get("spool") and offE["spool"]["id"] == Ge
              and offU and offU["spool"]["id"] == Ga
              and rGe["ams_printer_id"] == "" and rGa["ams_printer_id"] == "G" and int(rGa["ams_slot"]) == 0)

        # ── H. provider/grid-indicator: не получают ложную external из AMS0; exact external -1 получают ──
        set_offline(core, "H"); He = mk(m); m.inv_bind_spool(He, "H", -1, external=True); Ha = mk(m); bind0(m, Ha, "H")
        prov = m._inv_filament_provider()
        pslots = prov.get("H", {}).get("slots", [])
        ext_prov = next((s for s in pslots if s.get("external")), None)
        ha_prov = next((s for s in pslots if s.get("spool") and s["spool"].get("id") == Ha), None)
        check("H. generic provider: exact external -1 (He) помечен external:true; slot0-спул (Ha) НЕ помечен external (index не -1) — ложной external из AMS0 нет",
              ext_prov and ext_prov.get("spool") and ext_prov["spool"]["id"] == He and ext_prov["index"] == -1
              and (ha_prov is None or (not ha_prov.get("external") and ha_prov.get("index") != -1)))

        print("\n" + ("FAIL: " + str(fail) + " проверок провалено" if fail else
              "PASS: overview — точная -1 всегда external (в т.ч. offline); реальный AMS0 НИКОГДА не показывается external; legacy slot0 -> external лишь при свежем подтверждении no-AMS (Klipper/FF по telemetry_fresh); неоднозначный slot0 -> нейтральный unconfirmed без действий и без изменения БД; external -1 + AMS0 раздельны; provider без ложной external"))
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
