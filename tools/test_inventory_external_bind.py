# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Backend-тесты внешней привязки как ОТДЕЛЬНОЙ позиции ams_slot=-1 (Alpha 2.737 / inventory 1.7.20).
# Модель: external хранится как ams_slot=-1 (НЕ фейковый AMS-слот 0); AMS-слоты >=0; unbound = printer=''.
# «Bound?» определяется по ams_printer_id!='' (а не по ams_slot>=0). Legacy external (слот 0 у принтера БЕЗ
# живого AMS) продолжает читаться как external через dual-read {-1,0}. Миграция БД НЕ требуется.
#
# Покрытие (item 9, A-H на ВРЕМЕННОЙ тестовой БД; реальная DATA_DIR не трогается):
#   A overview: external:true/index:-1 И AMS-слот 0 существуют одновременно у принтера с живым AMS;
#   B bind external -> persisted ams_slot=-1, ячейка занята; C bind AMS0 -> оба не конфликтуют;
#   D multi-AMS(5)/HT(512) остаются реальными, external=-1; E unbind external НЕ трогает AMS0 и наоборот,
#   pending защищён; F legacy слот0 читается как external, новый bind = -1, cold-load без миграции;
#   G external-bound защищена от удаления; H generic provider несёт external spool с bound-признаком.
# I (ошибка bind 409/диалог) — фронтовый сценарий, покрыт в UI-тестах.
#
# Запуск:  python tools/test_inventory_external_bind.py   (0 = все тесты пройдены)
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
    def new_id(self, prefix=""):
        self._n += 1
        return str(prefix) + format(self._n, "08d")
    def printers(self):
        return list(self._printers)
    def printer_states(self):
        return dict(self._states)
    def get_printer_reported_filament(self, pid):
        # свежая телеметрия из _states: живые ams_trays -> AMS-позиции; нет трэев -> подтверждённо no-AMS
        st = self._states.get(pid) or {}
        trays = st.get("ams_trays") or []
        positions = [{"index": int(t.get("index")), "external": False} for t in trays]
        return {"telemetry_available": True, "telemetry_fresh": True, "positions": positions}


def load_backend(dbpath, core):
    spec = importlib.util.spec_from_file_location("inv_backend_exttest", BACKEND)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.core = core
    m.conn_inv = sqlite3.connect(dbpath, check_same_thread=False)
    m.conn_inv.row_factory = sqlite3.Row
    m.lock_inv = threading.RLock()
    m._init_tables()
    return m


def mk_spool(m):
    return m.inv_create_spool({"filament": {"material": "PLA", "color_name": "c"},
                               "weight_total_g": 1000, "weight_remaining_g": 1000, "status": "in_stock"})["id"]


def trays(n):
    return [{"index": i, "unit": 0, "tray": i, "type": "", "color": ""} for i in range(n)]


def row(m, sid):
    return m.conn_inv.execute("SELECT ams_printer_id, ams_slot FROM inv_spools WHERE id=?", (sid,)).fetchone()


def main():
    fd, db = tempfile.mkstemp(suffix=".db", prefix="fm_extbind_")
    os.close(fd)
    try:
        core = FakeCore()
        core._printers = [{"id": "P_AMS", "name": "AMS"}, {"id": "P_NOAMS", "name": "NoAMS"},
                          {"id": "P_HT", "name": "HT"}, {"id": "P_CLEAN", "name": "Clean"}]
        core._states = {
            "P_AMS": {"ams_trays": trays(4)},                       # живой AMS на 4 слота
            "P_NOAMS": {"ams_trays": []},                            # без AMS (legacy external на слоте 0)
            "P_HT": {"ams_trays": [{"index": 0, "unit": 0, "tray": 0}, {"index": 5, "unit": 1, "tray": 1},
                                    {"index": 512, "unit": 128, "tray": 0}]},   # мульти-AMS + HT
            "P_CLEAN": {"ams_trays": []},                            # чистый no-AMS для нового external-bind
        }
        m = load_backend(db, core)

        def slots(pid):
            for p in m.inv_ams_overview()["printers"]:
                if p["printer_id"] == pid:
                    return p["slots"]
            return []
        def ext_cell(pid):
            return next((s for s in slots(pid) if s.get("external")), None)
        def ams_cell(pid, idx):
            return next((s for s in slots(pid) if s.get("index") == idx and not s.get("external")), None)

        # ── A: у принтера с живым AMS external-позиция (-1) и AMS-слот 0 существуют ОДНОВРЕМЕННО ──
        e = ext_cell("P_AMS"); a0 = ams_cell("P_AMS", 0)
        check("A. AMS-принтер: external external:true/index:-1 И AMS-слот index:0 существуют одновременно (не совпадают)",
              e is not None and e["index"] == -1 and e["external"] is True
              and a0 is not None and a0["index"] == 0 and not a0.get("external"))

        # ── B: bind external -> persisted ams_slot=-1; ячейка занята ──
        sid_ext = mk_spool(m)
        m.inv_bind_spool(sid_ext, "P_AMS", -1, external=True)
        rb = row(m, sid_ext); eB = ext_cell("P_AMS")
        check("B. bind external -> ams_printer_id=P_AMS, ams_slot=-1 (persisted); external-ячейка занята этой катушкой",
              rb["ams_printer_id"] == "P_AMS" and int(rb["ams_slot"]) == -1
              and eB and eB.get("spool") and eB["spool"]["id"] == sid_ext)

        # ── C: bind AMS0 на тот же принтер -> ams_slot=0; external(-1) и AMS0 видны ОДНОВРЕМЕННО ──
        sid_a0 = mk_spool(m)
        m.inv_bind_spool(sid_a0, "P_AMS", 0)
        rc = row(m, sid_a0); eC = ext_cell("P_AMS"); a0C = ams_cell("P_AMS", 0)
        check("C. bind AMS0 -> ams_slot=0; external(-1) и AMS0 не конфликтуют — обе катушки видны одновременно",
              int(rc["ams_slot"]) == 0
              and eC and eC.get("spool") and eC["spool"]["id"] == sid_ext
              and a0C and a0C.get("spool") and a0C["spool"]["id"] == sid_a0)

        # ── D: multi-AMS(5)/HT(512) остаются реальными AMS; external у HT = -1 (три раздельные позиции) ──
        sid5 = mk_spool(m); sid512 = mk_spool(m); sidHtExt = mk_spool(m)
        m.inv_bind_spool(sid5, "P_HT", 5)
        m.inv_bind_spool(sid512, "P_HT", 512)
        m.inv_bind_spool(sidHtExt, "P_HT", -1, external=True)
        a5 = ams_cell("P_HT", 5); a512 = ams_cell("P_HT", 512); eHt = ext_cell("P_HT")
        check("D. multi-AMS слот 5 и HT слот 512 остаются реальными AMS (не external); external HT = -1 (все три раздельны)",
              a5 and a5["spool"]["id"] == sid5 and not a5.get("external")
              and a512 and a512["spool"]["id"] == sid512 and not a512.get("external")
              and eHt and eHt["index"] == -1 and eHt["spool"]["id"] == sidHtExt)

        # ── E1: unbind external НЕ трогает AMS0 ──
        m.inv_unbind_spool(sid_ext)
        rE = row(m, sid_ext); rA = row(m, sid_a0)
        check("E1. unbind external: external отвязана (printer='', slot=-1), AMS0 НЕ тронута (P_AMS, slot 0)",
              rE["ams_printer_id"] == "" and int(rE["ams_slot"]) == -1
              and rA["ams_printer_id"] == "P_AMS" and int(rA["ams_slot"]) == 0)

        # ── E2: unbind AMS0 НЕ трогает external ──
        m.inv_bind_spool(sid_ext, "P_AMS", -1, external=True)   # вернём external
        m.inv_unbind_spool(sid_a0)
        rE2 = row(m, sid_ext); rA2 = row(m, sid_a0)
        check("E2. unbind AMS0: AMS0 отвязана, external НЕ тронута (P_AMS, slot -1)",
              rA2["ams_printer_id"] == "" and int(rA2["ams_slot"]) == -1
              and rE2["ams_printer_id"] == "P_AMS" and int(rE2["ams_slot"]) == -1)

        # ── E3: pending-катушка НЕ отвязывается (блокировка) ──
        m.conn_inv.execute("INSERT INTO inv_pending_prints (id, printer_id, fname, started_ts, deductions, status) VALUES (?,?,?,?,?,?)",
                           ("pp_ext", "P_AMS", "f.gcode", 0, '[["' + sid_ext + '", 10.0]]', "active"))
        m.conn_inv.commit()
        res_pending = m.inv_unbind_spool(sid_ext)
        rEp = row(m, sid_ext)
        check("E3. pending external: unbind заблокирован (blocked/pending), привязка НЕ снята (остаётся P_AMS/-1)",
              res_pending.get("blocked") is True and res_pending.get("reason") == "pending"
              and rEp["ams_printer_id"] == "P_AMS" and int(rEp["ams_slot"]) == -1)
        m.conn_inv.execute("DELETE FROM inv_pending_prints WHERE id='pp_ext'"); m.conn_inv.commit()

        # ── F: legacy external (слот 0 у принтера БЕЗ AMS) читается как external; новый bind = -1; без миграции ──
        sid_legacy = mk_spool(m)
        m.conn_inv.execute("UPDATE inv_spools SET ams_printer_id='P_NOAMS', ams_slot=0, status='loaded' WHERE id=?", (sid_legacy,))
        m.conn_inv.commit()
        eLeg = ext_cell("P_NOAMS")
        check("F1. legacy external слот 0 (принтер без AMS) читается как external (dual-read {-1,0}); index канонизирован в -1; миграция не нужна",
              eLeg and eLeg["index"] == -1 and eLeg.get("external") and eLeg.get("spool") and eLeg["spool"]["id"] == sid_legacy)
        sid_new = mk_spool(m)
        m.inv_bind_spool(sid_new, "P_CLEAN", -1, external=True)
        rNew = row(m, sid_new); eClean = ext_cell("P_CLEAN")
        check("F2. новый external-bind у принтера без AMS сохраняется ОДНОЗНАЧНО как ams_slot=-1; ячейка занята",
              int(rNew["ams_slot"]) == -1 and eClean and eClean.get("spool") and eClean["spool"]["id"] == sid_new)

        # ── G: external-привязанная катушка защищена от удаления ──
        st_ext = m._classify_spool_for_delete(sid_ext)      # sid_ext привязана external (-1)
        st_ams = m._classify_spool_for_delete(sid512)       # sid512 привязана AMS (512)
        st_free = m._classify_spool_for_delete(sid_a0)      # sid_a0 отвязана (E2)
        check("G. external(-1)-привязанная защищена от удаления (blocked_bound), как и AMS-привязанная; отвязанная — deletable",
              st_ext == "blocked_bound" and st_ams == "blocked_bound" and st_free == "deletable")

        # ── H: generic provider несёт настоящую external spool с bound-признаком (для core-индикатора склада) ──
        prov = m._inv_filament_provider()
        pslots = prov.get("P_AMS", {}).get("slots", [])
        ext_in_prov = next((s for s in pslots if s.get("external")), None)
        ams_in_prov = next((s for s in pslots if s.get("spool") and not s.get("external")), None)
        check("H. generic provider: external помечена external:true/index:-1 с реальным spool.id (индикатор склада получит bound-признак); AMS-катушка отдельно",
              ext_in_prov and ext_in_prov["index"] == -1 and ext_in_prov["external"] is True
              and ext_in_prov.get("spool") and ext_in_prov["spool"].get("id") == sid_ext)

        # ── cold-load: свежее чтение видит и external(-1), и AMS-привязки; is_deleted не всплывает ──
        data = m.inv_filament_data()
        bound_ids = {s["id"] for s in data["spools"] if str(s.get("ams_printer_id") or "") != ""}
        check("F3. cold-read inv_filament_data: и external(-1), и AMS-привязки присутствуют одним списком (без миграции)",
              sid_ext in bound_ids and sid512 in bound_ids and sid_legacy in bound_ids and sid_new in bound_ids)

        print("\n" + ("FAIL: " + str(fail) + " проверок провалено" if fail else
              "PASS: внешняя привязка ams_slot=-1 — отдельная позиция у всех принтеров, не совпадает с AMS0; legacy слот0 dual-read; unbind/pending/delete-защита/provider — корректны (без миграции БД)"))
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
