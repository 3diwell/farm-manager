# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Склад: операции телефона (FM Client) с катушками в принтере — протоколы 2, 6 и 7.

ЗАЧЕМ. 10.10.2026 разобран FM Client 0.15.15 второго разработчика. Самые рискованные операции
телефона — установка, замена и снятие катушки (протокол 2), списание пустой катушки (6) и замена
со списанием (7) — снимают катушки с работающих принтеров и убирают их со склада, а ни один набор
проекта их не проверял. Запросы здесь собраны ровно так, как их собирает приложение 0.15.15
(имена полей и номера протоколов сняты с его байткода: InventoryRepository.slotRequest,
writeOffRequest, replaceWriteOffRequest).

ЧТО ДОКАЗЫВАЕТСЯ (песочница: модуль склада из исходников, база в памяти, подставное ядро;
сервер не запускается, данные владельца не читаются, принтеров нет):
  A. склад объявляет все возможности, которые проверяет приложение;
  B. протокол 2: установка в пустую ячейку, замена, снятие; устаревшее «что стоит в ячейке» — отказ;
  C. во время печати, паузы и подготовки, а также без свежих данных принтера — отказ, ничего не меняется;
  D. 1.7.38: после отменённой или сбойной печати (FAILED) снять и заменить катушку можно, но
     незакрытая печать по-прежнему защищает катушку;
  E. протокол 6: списание катушки со склада и из принтера — вес 0, запись «out», снятие «move»;
     изменившаяся катушка или нет подтверждения — отказ;
  F. протокол 7: замена со списанием — старая списана, новая в ячейке, одной транзакцией; повтор того
     же запроса не списывает второй раз; неудача на установке новой откатывает и списание.

Запуск: python tools/test_inventory_mobile_protocols.py   (0 = все проверки пройдены)
"""
import importlib.util
import json
import logging
import os
import sys
import uuid

sys.dont_write_bytecode = True
logging.getLogger("fm.mod.inventory").setLevel(logging.CRITICAL)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(REPO, "modules", "inventory", "backend.py")
SENTINEL = "INVENTORY_MOBILE_PROTOCOLS_SENTINEL_1010"

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:600]) if detail else ""))


STATE = {"status": "IDLE", "fresh": True}
PID = "node_p1"


class Core:
    """Подставное ядро: один принтер Bambu с двумя ячейками AMS; состояние задаёт тест."""
    def resolve_db(self, name):
        return ":memory:"

    def add_route(self, *a, **k):
        pass

    def add_hook(self, *a, **k):
        pass

    def new_id(self, prefix=""):
        return prefix + uuid.uuid4().hex[:12]

    def printers(self):
        return [{"id": PID, "name": "P1"}]

    def printer_states(self):
        return {PID: {"status": STATE["status"], "ams_trays": [
            {"index": 0, "unit": 0, "tray": 0, "type": "PLA", "color": "FF0000FF"},
            {"index": 1, "unit": 0, "tray": 1, "type": "PLA", "color": "00FF00FF"}]}}

    def get_printer_reported_filament(self, pid):
        return {"telemetry_fresh": STATE["fresh"], "telemetry_available": True}


spec = importlib.util.spec_from_file_location("inv_backend_mobile_protocols", BACKEND)
be = importlib.util.module_from_spec(spec)
spec.loader.exec_module(be)
be._watch_pending_loop = lambda: None      # фоновый сторож незакрытых печатей в песочнице не нужен
be.register(Core())
G = vars(be)
DB = be.conn_inv


def call(body, action, sid=""):
    """Тело уходит через JSON, как по сети; ответ — (код, тело)."""
    body = json.loads(json.dumps(body))
    r = be._mobile.dispatch(G, body, action, sid)
    if hasattr(r, "body"):
        return r.status_code, json.loads(r.body)
    return 200, r


def rid():
    return str(uuid.uuid4())                # как Java UUID.randomUUID().toString()


META = be.api_inv_filament()["mobile"]
SERVER = META["server_id"]
LOC = be.inv_create_location({"name": "Shelf A"})["id"]


def envelope(code, kind):                    # InventoryRepository.envelope: протокол 1
    return {"protocol": 1, "server_id": SERVER, "request_id": rid(), "code": code, "code_kind": kind}


def receipt(code, weight=1000.0):
    st, r = call({"mobile": envelope(code, "unique"), "location": LOC, "weight_total_g": weight, "label": "",
                  "filament": {"vendor_name": "Bambu Lab", "material": "PLA", "color_name": "Red", "diameter": 1.75}},
                 "receipt")
    assert st == 200 and r.get("ok"), (st, r)
    return r["id"]


def row(sid):
    r = DB.execute("SELECT * FROM inv_spools WHERE id=?", (sid,)).fetchone()
    return dict(r) if r else None


def slot_of(sid):
    r = row(sid)
    return (r["ams_printer_id"] or "", r["ams_slot"]) if r else None


def ledger(sid):
    return [(r["kind"], float(r["qty"] or 0)) for r in DB.execute(
        "SELECT kind, qty FROM inv_ledger WHERE ref_type='spool' AND ref_id=? ORDER BY rowid", (sid,))]


def slot_req(op, sid, slot, expected):       # InventoryRepository.slotRequest: протокол 2
    m = envelope("fm1:slot:%s:%s:%d" % (SERVER, PID, slot), "unique")
    m["protocol"] = 2
    m["operation"] = op
    return call({"mobile": m, "printer_id": PID, "ams_slot": slot, "external": slot == -1,
                 "expected_spool_id": expected}, "bind", sid)


def writeoff_body(sid):                       # InventoryRepository.writeOffRequest: протокол 6
    s = row(sid)
    return {"mobile": {"protocol": 6, "operation": "writeoff", "server_id": SERVER, "request_id": rid()},
            "spool_id": sid, "confirm_empty": True, "expected_filament_id": s["filament_id"],
            "expected_printer_id": s["ams_printer_id"] or "", "expected_ams_slot": int(s["ams_slot"]),
            "expected_weight_remaining_g": float(s["weight_remaining_g"])}


def replace_writeoff_body(old, new):          # replaceWriteOffRequest: протокол 7
    d = writeoff_body(old)
    n = row(new)
    d["mobile"].update(protocol=7, operation="replace_writeoff", request_id=rid())
    d.update(new_spool_id=new, expected_new_filament_id=n["filament_id"],
             expected_new_weight_remaining_g=float(n["weight_remaining_g"]))
    return d


def set_state(status, fresh=True):
    STATE["status"], STATE["fresh"] = status, fresh


# ════════════════════════════════════════════════════════════════════════════
print("\n--- A. возможности склада для телефона ---")
APP_FEATURES = ["slot_exchange_v2", "prepared_labels_v3", "nfc_spools_v4", "empty_spool_writeoff_v6", "slot_replace_writeoff_v7"]
check("A1. склад объявляет все возможности, которые проверяет FM Client 0.15.15",
      all(f in META.get("features", []) for f in APP_FEATURES), META.get("features"))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- B. протокол 2: установка, замена, снятие ---")
A, B = receipt("SN-A-0001"), receipt("SN-B-0002")
st, r = slot_req("bind", A, 0, "")
check("B1. установка в пустую ячейку: катушка в принтере, запись перемещения, вес не тронут",
      st == 200 and r.get("operation") == "bind" and slot_of(A) == (PID, 0) and ledger(A)[-1] == ("move", 0.0)
      and row(A)["weight_remaining_g"] == 1000.0, (st, r, ledger(A)))
st, r = slot_req("bind", B, 1, "spool_gone")
check("B2. телефон думает, что в ячейке что-то стоит, а она пуста — отказ «binding_changed», ничего не меняется",
      r.get("error") == "binding_changed" and not (row(B)["ams_printer_id"] or ""), (st, r, slot_of(B)))
st, r = slot_req("replace", B, 0, A)
check("B3. замена: новая в ячейке, старая снята и лежит на складе с прежним весом",
      st == 200 and r.get("operation") == "replace" and r.get("removed_spool_id") == A
      and slot_of(B) == (PID, 0) and not (row(A)["ams_printer_id"] or "") and row(A)["is_deleted"] == 0
      and row(A)["weight_remaining_g"] == 1000.0, (st, r))
st, r = slot_req("replace", A, 0, A)
check("B4. замена по устаревшему снимку (в ячейке уже другая) — отказ «binding_changed»",
      r.get("error") == "binding_changed" and slot_of(B) == (PID, 0), (st, r))
st, r = slot_req("unbind", B, 0, B)
check("B5. снятие: ячейка пуста, катушка на складе, запись перемещения",
      st == 200 and r.get("operation") == "unbind" and not (row(B)["ams_printer_id"] or "")
      and ledger(B)[-1] == ("move", 0.0), (st, r))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- C. принтер занят или без связи — отказ ---")
st, r = slot_req("bind", A, 0, "")
for status in ("RUNNING", "PREPARE", "PAUSE", "PAUSED"):
    set_state(status)
    st1, r1 = slot_req("unbind", A, 0, A)
    st2, r2 = call(replace_writeoff_body(A, B), "writeoff")
    check("C1. %s: снять и заменить со списанием нельзя («printer_not_idle»), катушка на месте и не списана" % status,
          r1.get("error") == "printer_not_idle" and r2.get("error") == "printer_not_idle"
          and slot_of(A) == (PID, 0) and row(A)["is_deleted"] == 0 and row(B)["is_deleted"] == 0, (r1, r2))
set_state("IDLE", fresh=False)
st, r = slot_req("unbind", A, 0, A)
check("C2. нет свежих данных принтера — отказ «printer_offline_or_stale»",
      r.get("error") == "printer_offline_or_stale" and slot_of(A) == (PID, 0), (st, r))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- D. 1.7.38: после отменённой печати (FAILED) ---")
set_state("FAILED")
st, r = slot_req("unbind", A, 0, A)
check("D1. FAILED: снять катушку можно (раньше — «printer_not_idle», хотя на компьютере можно)",
      st == 200 and r.get("operation") == "unbind" and not (row(A)["ams_printer_id"] or ""), (st, r))
st, r = slot_req("bind", A, 0, "")
check("D2. FAILED: установить катушку можно", st == 200 and slot_of(A) == (PID, 0), (st, r))
DB.execute("INSERT INTO inv_pending_prints(id, printer_id, fname, deductions, status) VALUES(?,?,?,?,?)",
           ("pp_test", PID, "part.3mf", json.dumps([[A, 12.5]]), "active"))
DB.commit()
st, r = slot_req("unbind", A, 0, A)
st2, r2 = call(replace_writeoff_body(A, B), "writeoff")
check("D3. FAILED, но печать склада ещё не закрыта — катушку не трогаем («pending_print»)",
      r.get("error") == "pending_print" and r2.get("error") == "pending_print"
      and slot_of(A) == (PID, 0) and row(A)["is_deleted"] == 0, (r, r2))
DB.execute("DELETE FROM inv_pending_prints WHERE id='pp_test'")
DB.commit()
st, r = call(replace_writeoff_body(A, B), "writeoff")
check("D4. FAILED, печать закрыта: замена со списанием проходит",
      st == 200 and r.get("operation") == "replace_writeoff" and r.get("removed_spool_id") == A
      and row(A)["is_deleted"] == 1 and slot_of(B) == (PID, 0), (st, r))
set_state("IDLE")

# ════════════════════════════════════════════════════════════════════════════
print("\n--- E. протокол 6: списание пустой катушки ---")
C = receipt("SN-C-0003", 812.5)
body = writeoff_body(C)
body["expected_weight_remaining_g"] = 800.0
st, r = call(body, "writeoff")
check("E1. катушка изменилась после показа (другой вес) — отказ «writeoff_spool_changed», катушка цела",
      r.get("error") == "writeoff_spool_changed" and row(C)["is_deleted"] == 0 and row(C)["weight_remaining_g"] == 812.5, (st, r))
body = writeoff_body(C)
body["confirm_empty"] = False
st, r = call(body, "writeoff")
check("E2. без подтверждения «катушка пуста» — отказ", st == 400 and r.get("error") == "invalid_writeoff_confirmation", (st, r))
st, r = call(writeoff_body(C), "writeoff")
check("E3. списание со склада: вес 0, катушка удалена, запись «out» на весь остаток",
      st == 200 and r.get("written_off_g") == 812.5 and row(C)["is_deleted"] == 1
      and row(C)["weight_remaining_g"] == 0 and ("out", 812.5) in ledger(C), (st, r, ledger(C)))
D = receipt("SN-D-0004", 300.0)
slot_req("bind", D, 1, "")
st, r = call(writeoff_body(D), "writeoff")
check("E4. списание из принтера: снятие («move»), списание остатка («out»), удаление («del»), ячейка пуста",
      st == 200 and row(D)["is_deleted"] == 1 and not (row(D)["ams_printer_id"] or "")
      and [k for k, _ in ledger(D)][-3:] == ["move", "out", "del"] and ("out", 300.0) in ledger(D), (st, r, ledger(D)))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- F. протокол 7: замена со списанием ---")
E, F = receipt("SN-E-0005"), receipt("SN-F-0006", 950.0)
slot_req("bind", E, 1, "")
body = replace_writeoff_body(E, F)
st, r = call(body, "writeoff")
outs_before = [k for k, _ in ledger(E)].count("out")
check("F1. старая списана, новая стоит в той же ячейке — одной операцией",
      st == 200 and r.get("operation") == "replace_writeoff" and row(E)["is_deleted"] == 1 and slot_of(F) == (PID, 1)
      and r.get("written_off_g") == 1000.0, (st, r))
st, r = call(body, "writeoff")
check("F2. повтор того же запроса (ответ потерялся в сети) — тот же ответ, второго списания нет",
      st == 200 and r.get("replayed") is True and [k for k, _ in ledger(E)].count("out") == outs_before == 1, (st, r))
body2 = json.loads(json.dumps(body))
body2["expected_new_weight_remaining_g"] = 1.0
st, r = call(body2, "writeoff")
check("F3. тот же номер запроса с другим содержимым — отказ «request_id_reused»", r.get("error") == "request_id_reused", (st, r))
H, K = receipt("SN-H-0007"), receipt("SN-K-0008")
slot_req("unbind", F, 1, F)
slot_req("bind", H, 1, "")
DB.execute("UPDATE inv_spools SET status='archived' WHERE id=?", (K,))
DB.commit()
st, r = call(replace_writeoff_body(H, K), "writeoff")
hr = row(H)
check("F4. новая катушка не годится (в архиве) — отказ, и списание старой ОТКАТИЛОСЬ: она на месте и с весом",
      r.get("ok") is False and hr["is_deleted"] == 0 and hr["weight_remaining_g"] == 1000.0 and slot_of(H) == (PID, 1)
      and "out" not in [k for k, _ in ledger(H)], (st, r, hr))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- метка-ловушка ---")
check("K1. метка-ловушка не попала в код модуля склада",
      SENTINEL not in open(BACKEND, encoding="utf-8").read()
      and SENTINEL not in open(os.path.join(REPO, "modules", "inventory", "mobile_api.py"), encoding="utf-8").read())

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
