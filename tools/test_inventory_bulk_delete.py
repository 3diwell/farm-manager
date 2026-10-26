# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Тесты пакетного (множественного) удаления катушек — inventory 1.7.0.
# Проверяют backend-логику inv_bulk_delete / inv_bulk_delete_preview на ВРЕМЕННОЙ
# тестовой БД. Реальная DATA_DIR НЕ трогается (создаётся свежий файл в tempdir).
#
# Покрытие: массовое удаление (18 проверок — дубликаты, пустой/невалидный/большой список,
# not_found, блокировка bound/pending, сохранность журнала, partial success, идемпотентность,
# откат транзакции, «preview ничего не меняет») + ОДИНОЧНОЕ удаление через ЕДИНУЮ проверку
# (S1–S11: доступное/привязанное/pending, гонка preview→delete, один общий classification-helper,
# одинаковые причины в single и bulk, сохранность истории, идемпотентность, invalid id).
#
# Запуск:  python tools/test_inventory_bulk_delete.py   (0 = все тесты пройдены)
# ============================================================================
import importlib.util
import logging
import os
import sqlite3
import sys
import tempfile
import threading

logging.getLogger("fm.mod.inventory").setLevel(logging.CRITICAL)   # тест №13 намеренно роняет транзакцию — не шумим её трейсом

try:                                   # вывод RU-текста в любой консоли (Windows cp1251/cp1255 и т.п.)
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
    """Минимальный core для модуля: только new_id (bulk-удаление больше ничего от core не требует)."""
    def __init__(self):
        self._n = 0
    def new_id(self, prefix=""):
        self._n += 1
        return str(prefix) + format(self._n, "08d")


def load_backend(dbpath):
    spec = importlib.util.spec_from_file_location("inv_backend_bulktest", BACKEND)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.core = FakeCore()
    m.conn_inv = sqlite3.connect(dbpath, check_same_thread=False)
    m.conn_inv.row_factory = sqlite3.Row
    m.lock_inv = threading.RLock()
    m._init_tables()
    return m


def mk_spool(m, remaining=1000, total=1000, status="in_stock"):
    r = m.inv_create_spool({"filament": {"material": "PLA", "color_name": "c"},
                            "weight_total_g": total, "weight_remaining_g": remaining, "status": status})
    return r["id"]


def is_deleted(m, sid):
    r = m.conn_inv.execute("SELECT is_deleted FROM inv_spools WHERE id=?", (sid,)).fetchone()
    return None if r is None else int(r["is_deleted"] or 0)


def ledger_kinds(m, sid):
    return [r["kind"] for r in m.conn_inv.execute(
        "SELECT kind FROM inv_ledger WHERE ref_type='spool' AND ref_id=? ORDER BY rowid", (sid,)).fetchall()]


def spool_row(m, sid):
    return m.conn_inv.execute("SELECT ams_printer_id, ams_slot, is_deleted FROM inv_spools WHERE id=?", (sid,)).fetchone()


def spool_meta(m, sid):
    r = m.conn_inv.execute(
        "SELECT s.weight_remaining_g AS w, s.price AS p, s.status AS st, f.material AS mat, v.name AS vnd "
        "FROM inv_spools s LEFT JOIN inv_filaments f ON f.id=s.filament_id LEFT JOIN inv_vendors v ON v.id=f.vendor_id "
        "WHERE s.id=?", (sid,)).fetchone()
    return {"w": r["w"], "p": r["p"], "st": r["st"], "mat": r["mat"], "vnd": r["vnd"]}


def ledger_io_count(m, sid):
    return m.conn_inv.execute("SELECT COUNT(*) AS n FROM inv_ledger WHERE ref_type='spool' AND ref_id=? AND kind IN ('in','out')", (sid,)).fetchone()["n"]


def mk_spool_full(m, remaining=742, total=1000, price=25, vendor="Bambu"):
    r = m.inv_create_spool({"filament": {"material": "PETG", "color_name": "black", "vendor_name": vendor},
                            "weight_total_g": total, "weight_remaining_g": remaining, "price": price})
    return r["id"]


def run(m):
    # 1) Удаление одного доступного spool (через общий helper: soft-delete + маркер в журнал)
    s1 = mk_spool(m)
    r = m.inv_bulk_delete([s1])
    check("1. один доступный spool удалён", r["ok"] and r["deleted_ids"] == [s1] and is_deleted(m, s1) == 1)
    check("1b. общий helper: добавлен маркер 'del' в журнал (история не тронута)",
          ledger_kinds(m, s1).count("del") == 1 and "in" in ledger_kinds(m, s1))

    # 2) Удаление 50 доступных одним запросом
    many = [mk_spool(m) for _ in range(50)]
    r = m.inv_bulk_delete(list(many))
    check("2. 50 доступных удалены одним запросом",
          len(r["deleted_ids"]) == 50 and all(is_deleted(m, x) == 1 for x in many))

    # 3) Дубликаты id не вызывают повторное удаление
    s3 = mk_spool(m)
    r = m.inv_bulk_delete([s3, s3, s3])
    check("3. дубликаты id -> удаление один раз",
          r["deleted_ids"] == [s3] and ledger_kinds(m, s3).count("del") == 1 and not r["not_found_ids"])

    # 4) Пустой список отклоняется
    r_empty = m.inv_bulk_delete([])
    r_none = m.inv_bulk_delete(None)
    check("4. пустой список / None отклонены (error=empty)",
          r_empty.get("ok") is False and r_empty.get("error") == "empty"
          and r_none.get("ok") is False and r_none.get("error") == "empty")

    # 5) Невалидные id отклоняются / отсеиваются
    r_all_bad = m.inv_bulk_delete(["", "   ", {"x": 1}, ["a"], True])
    s5 = mk_spool(m)
    r_mix = m.inv_bulk_delete([s5, "", "bad id with space"])
    check("5. полностью невалидный список отклонён (error=no_valid_ids)",
          r_all_bad.get("ok") is False and r_all_bad.get("error") == "no_valid_ids")
    check("5b. валидные обрабатываются, мусор -> invalid_ids",
          r_mix["ok"] and r_mix["deleted_ids"] == [s5] and len(r_mix["invalid_ids"]) == 2)

    # 6) Несуществующие id возвращаются отдельно
    r = m.inv_bulk_delete(["spool_doesnotexist"])
    check("6. несуществующий id -> not_found_ids, ничего не удалено",
          r["ok"] and r["not_found_ids"] == ["spool_doesnotexist"] and r["deleted_ids"] == [])

    # 7) Привязанная катушка блокируется
    s7 = mk_spool(m)
    m.inv_bind_spool(s7, "PRN1", 0)
    r = m.inv_bulk_delete([s7])
    check("7. привязанная катушка заблокирована (reason=bound), не удалена",
          r["deleted_ids"] == [] and any(b["id"] == s7 and b["reason"] == "bound" for b in r["blocked"])
          and is_deleted(m, s7) == 0)

    # 8) Pending/активная катушка блокируется
    s8 = mk_spool(m)
    m.conn_inv.execute("INSERT INTO inv_pending_prints (id, printer_id, fname, started_ts, deductions, status) VALUES (?,?,?,?,?,?)",
                       ("pp_t8", "PRN2", "job.gcode", 0, '[["%s", 120.0]]' % s8, "active"))
    m.conn_inv.commit()
    r = m.inv_bulk_delete([s8])
    check("8. pending-катушка заблокирована (reason=pending), не удалена",
          r["deleted_ids"] == [] and any(b["id"] == s8 and b["reason"] == "pending" for b in r["blocked"])
          and is_deleted(m, s8) == 0)

    # 9) История ledger сохраняется
    s9 = mk_spool(m)
    m.inv_adjust_spool(s9, -100.0, "печать (авто)")   # расход
    m.inv_adjust_spool(s9, +30.0, "возврат")          # приход
    before = m.conn_inv.execute("SELECT COUNT(*) AS n FROM inv_ledger WHERE ref_type='spool' AND ref_id=? AND kind IN ('in','out')", (s9,)).fetchone()["n"]
    m.inv_bulk_delete([s9])
    after = m.conn_inv.execute("SELECT COUNT(*) AS n FROM inv_ledger WHERE ref_type='spool' AND ref_id=? AND kind IN ('in','out')", (s9,)).fetchone()["n"]
    check("9. история расхода (in/out) в журнале сохранена после удаления", before >= 3 and after == before)

    # 10) Другие катушки не изменяются
    a10 = mk_spool(m, remaining=800)
    b10 = mk_spool(m, remaining=640)
    m.inv_bulk_delete([a10])
    rb = m.conn_inv.execute("SELECT is_deleted, weight_remaining_g FROM inv_spools WHERE id=?", (b10,)).fetchone()
    check("10. соседняя катушка не тронута (is_deleted=0, вес не изменён)",
          int(rb["is_deleted"] or 0) == 0 and abs(float(rb["weight_remaining_g"]) - 640) < 1e-6)

    # 11) Partial success корректен (deletable + bound + not_found в одном запросе)
    ok1 = mk_spool(m); ok2 = mk_spool(m); bnd = mk_spool(m)
    m.inv_bind_spool(bnd, "PRN3", 1)
    r = m.inv_bulk_delete([ok1, bnd, "spool_ghost", ok2])
    check("11. partial success: удалены доступные, заблокирована привязанная, отдельно not_found",
          set(r["deleted_ids"]) == {ok1, ok2}
          and any(b["id"] == bnd and b["reason"] == "bound" for b in r["blocked"])
          and r["not_found_ids"] == ["spool_ghost"]
          and is_deleted(m, ok1) == 1 and is_deleted(m, ok2) == 1 and is_deleted(m, bnd) == 0)

    # 12) Повторный запрос идемпотентен
    s12 = mk_spool(m)
    r_first = m.inv_bulk_delete([s12])
    r_second = m.inv_bulk_delete([s12])
    check("12. повторное удаление идемпотентно (2-й раз: not_found, без ошибок, без 2-го 'del')",
          r_first["deleted_ids"] == [s12] and r_second["deleted_ids"] == []
          and r_second["not_found_ids"] == [s12] and not r_second["errors"]
          and ledger_kinds(m, s12).count("del") == 1)

    # 13) Ошибка в транзакции не оставляет повреждённого состояния (полный откат)
    t1 = mk_spool(m); t2 = mk_spool(m); t3 = mk_spool(m)
    orig = m._inv_delete_spool_sql
    state = {"n": 0}
    def boom(sid):
        state["n"] += 1
        orig(sid)                 # реальный soft-delete (ещё не закоммичен)
        if state["n"] == 2:
            raise RuntimeError("boom in transaction")
    m._inv_delete_spool_sql = boom
    try:
        r = m.inv_bulk_delete([t1, t2, t3])
    finally:
        m._inv_delete_spool_sql = orig
    check("13. сбой транзакции откатан целиком (deleted пуст, есть errors, все катушки живы)",
          r["deleted_ids"] == [] and len(r["errors"]) >= 1
          and is_deleted(m, t1) == 0 and is_deleted(m, t2) == 0 and is_deleted(m, t3) == 0)

    # 14) Ограничение размера списка
    big = ["spool_%08d" % i for i in range(m._INV_BULK_MAX + 1)]
    r = m.inv_bulk_delete(big)
    check("14. превышение потолка списка отклонено (error=too_many)",
          r.get("ok") is False and r.get("error") == "too_many")

    # 15) Preview ничего не меняет
    s15 = mk_spool(m)
    p = m.inv_bulk_delete_preview([s15])
    check("15. preview: катушка в deletable, но НЕ удалена и без маркера 'del'",
          p["ok"] and p["deletable"] == [s15] and is_deleted(m, s15) == 0
          and ledger_kinds(m, s15).count("del") == 0)

    # 15b) Preview классифицирует смешанный набор так же, как удаление
    d1 = mk_spool(m); bnd2 = mk_spool(m); m.inv_bind_spool(bnd2, "PRN4", 0)
    p = m.inv_bulk_delete_preview([d1, bnd2, "spool_ghost2"])
    check("15b. preview: deletable/blocked/not_found разложены корректно",
          p["deletable"] == [d1]
          and any(b["id"] == bnd2 and b["reason"] == "bound" for b in p["blocked"])
          and p["not_found"] == ["spool_ghost2"] and p["total"] == 3)


def run_single(m):
    """Одиночное удаление через ЕДИНУЮ проверку (inv_delete_spool_checked) — тот же helper, что и bulk.
    Закрывает обход блокировок через ПКМ → «Удалить»."""
    # S1) Одиночное удаление доступной катушки работает
    s1 = mk_spool(m)
    r = m.inv_delete_spool_checked(s1)
    check("S1. одиночное удаление доступной катушки: state=deleted, is_deleted=1",
          r["state"] == "deleted" and r.get("ok") is True and is_deleted(m, s1) == 1)

    # S2) Одиночное удаление привязанной катушки блокируется
    s2 = mk_spool(m); m.inv_bind_spool(s2, "PRN1", 0)
    r = m.inv_delete_spool_checked(s2)
    check("S2. одиночное удаление привязанной блокируется (blocked_bound, reason=bound), is_deleted=0",
          r["state"] == "blocked_bound" and r.get("blocked") is True and r.get("reason") == "bound"
          and is_deleted(m, s2) == 0)

    # S3) Одиночное удаление pending-катушки блокируется
    s3 = mk_spool(m)
    m.conn_inv.execute("INSERT INTO inv_pending_prints (id, printer_id, fname, started_ts, deductions, status) VALUES (?,?,?,?,?,?)",
                       ("pp_s3", "PRN2", "job.gcode", 0, '[["%s", 90.0]]' % s3, "active"))
    m.conn_inv.commit()
    r = m.inv_delete_spool_checked(s3)
    check("S3. одиночное удаление pending блокируется (blocked_pending, reason=pending), is_deleted=0",
          r["state"] == "blocked_pending" and r.get("reason") == "pending" and is_deleted(m, s3) == 0)

    # S4) Заблокированная катушка остаётся is_deleted=0 (явно)
    check("S4. заблокированные катушки не помечены удалёнными", is_deleted(m, s2) == 0 and is_deleted(m, s3) == 0)

    # S5) Ledger заблокированной катушки НЕ получает маркер удаления
    check("S5. журнал заблокированной катушки без маркера 'del'",
          "del" not in ledger_kinds(m, s2) and "del" not in ledger_kinds(m, s3))

    # S6) Гонка: preview сказал deletable, состояние изменилось до DELETE -> повторно блокируется
    s6 = mk_spool(m)
    p = m.inv_bulk_delete_preview([s6])
    before = (p["deletable"] == [s6])
    m.inv_bind_spool(s6, "PRN3", 0)                          # состояние изменилось ПОСЛЕ preview
    r = m.inv_delete_spool_checked(s6)                       # DELETE обязан перепроверить
    check("S6. preview deletable -> привязали -> DELETE повторно блокирует (гонка), is_deleted=0",
          before and r["state"] == "blocked_bound" and is_deleted(m, s6) == 0)

    # S7) Single и bulk используют ОДИН classification-helper (доказательство: перехват вызовов)
    orig = m._classify_spool_for_delete
    calls = {"single": 0, "bulk": 0, "mode": None}
    def spy(spool_id, pending_ids=None):
        if calls["mode"] == "single": calls["single"] += 1
        elif calls["mode"] == "bulk": calls["bulk"] += 1
        return orig(spool_id, pending_ids)
    a7 = mk_spool(m); b7 = mk_spool(m)
    try:
        m._classify_spool_for_delete = spy
        calls["mode"] = "single"; m.inv_delete_spool_checked(a7)
        calls["mode"] = "bulk"; m.inv_bulk_delete_preview([b7])
    finally:
        m._classify_spool_for_delete = orig; calls["mode"] = None
    check("S7. single и bulk используют один helper _classify_spool_for_delete (оба вызвали его)",
          calls["single"] >= 1 and calls["bulk"] >= 1)

    # S8) Причины bound/pending ОДИНАКОВЫ в single и bulk
    sb = mk_spool(m); m.inv_bind_spool(sb, "PRN5", 0)
    sp = mk_spool(m)
    m.conn_inv.execute("INSERT INTO inv_pending_prints (id, printer_id, fname, started_ts, deductions, status) VALUES (?,?,?,?,?,?)",
                       ("pp_s8", "PRN6", "j.gcode", 0, '[["%s", 50.0]]' % sp, "active"))
    m.conn_inv.commit()
    single_bound = m.inv_delete_spool_checked(sb).get("reason")
    single_pend = m.inv_delete_spool_checked(sp).get("reason")
    pv = m.inv_bulk_delete_preview([sb, sp])
    bulk_reasons = {b["id"]: b["reason"] for b in pv["blocked"]}
    check("S8. причины блокировки одинаковы в single и bulk (bound/pending)",
          single_bound == "bound" and single_pend == "pending"
          and bulk_reasons.get(sb) == "bound" and bulk_reasons.get(sp) == "pending")

    # S9) Доступное одиночное удаление сохраняет историю ledger
    s9 = mk_spool(m)
    m.inv_adjust_spool(s9, -120.0, "печать (авто)")
    m.inv_adjust_spool(s9, +40.0, "возврат")
    io_before = m.conn_inv.execute("SELECT COUNT(*) AS n FROM inv_ledger WHERE ref_type='spool' AND ref_id=? AND kind IN ('in','out')", (s9,)).fetchone()["n"]
    m.inv_delete_spool_checked(s9)
    io_after = m.conn_inv.execute("SELECT COUNT(*) AS n FROM inv_ledger WHERE ref_type='spool' AND ref_id=? AND kind IN ('in','out')", (s9,)).fetchone()["n"]
    check("S9. одиночное удаление сохраняет историю расхода (in/out) в журнале",
          io_before >= 3 and io_after == io_before and is_deleted(m, s9) == 1)

    # S10) Повторное одиночное удаление идемпотентно (not_found, без 2-го маркера)
    r2 = m.inv_delete_spool_checked(s9)
    check("S10. повторное одиночное удаление -> not_found, is_deleted остаётся 1, один маркер 'del'",
          r2["state"] == "not_found" and r2.get("not_found") is True
          and is_deleted(m, s9) == 1 and ledger_kinds(m, s9).count("del") == 1)

    # S11) Невалидный id -> state invalid (одиночный путь тоже отсеивает мусор)
    r3 = m.inv_delete_spool_checked("bad id !!")
    check("S11. невалидный id одиночного удаления -> state=invalid",
          r3["state"] == "invalid" and r3.get("ok") is False)


def run_unbind(m):
    """Явная отвязка катушки от принтера/AMS (inv_unbind_spool) — общий SQL-helper, pending-блокировка,
    идемпотентность, неизменность материала/веса/истории/is_deleted."""
    # U1) Отвязка внешней катушки (принтер без AMS -> слот 0)
    e1 = mk_spool(m); m.inv_bind_spool(e1, "PRN_EXT", 0)
    r = m.inv_unbind_spool(e1); row = spool_row(m, e1)
    check("U1. отвязка внешней катушки: ok, ams очищен, previous возвращён",
          r["ok"] and r.get("previous_printer_id") == "PRN_EXT" and r.get("previous_ams_slot") == 0
          and row["ams_printer_id"] == "" and int(row["ams_slot"]) == -1)

    # U2) Отвязка AMS slot 0
    a0 = mk_spool(m); m.inv_bind_spool(a0, "PRN_AMS", 0)
    r = m.inv_unbind_spool(a0)
    check("U2. отвязка AMS slot 0 (0 не считается «не привязана»)",
          r["ok"] and r["previous_ams_slot"] == 0 and spool_row(m, a0)["ams_printer_id"] == "")

    # U3) Отвязка AMS slot 1/2/3
    ok3 = True
    for slot in (1, 2, 3):
        a = mk_spool(m); m.inv_bind_spool(a, "PRN_AMS", slot)
        r = m.inv_unbind_spool(a)
        if not (r["ok"] and r["previous_ams_slot"] == slot and int(spool_row(m, a)["ams_slot"]) == -1):
            ok3 = False
    check("U3. отвязка AMS slot 1/2/3", ok3)

    # U4) Отвязанная катушка остаётся is_deleted=0
    check("U4. отвязанные катушки остаются is_deleted=0", is_deleted(m, e1) == 0 and is_deleted(m, a0) == 0)

    # U5) Вес/материал/vendor/цена не меняются отвязкой (меняется только статус loaded->in_stock)
    w1 = mk_spool_full(m, remaining=742, price=25, vendor="Bambu")
    before = spool_meta(m, w1)
    m.inv_bind_spool(w1, "PRN2", 0); m.inv_unbind_spool(w1)
    after = spool_meta(m, w1)
    check("U5. вес/материал/vendor/цена не изменены отвязкой (статус loaded->in_stock)",
          before["w"] == after["w"] and before["mat"] == after["mat"] and before["vnd"] == after["vnd"]
          and before["p"] == after["p"] and after["st"] == "in_stock")

    # U6) История ledger сохранена; отвязка НЕ пишет ledger
    l1 = mk_spool(m); m.inv_adjust_spool(l1, -100.0, "печать (авто)")
    lb = ledger_io_count(m, l1)
    m.inv_bind_spool(l1, "PRN3", 0); m.inv_unbind_spool(l1)
    la = ledger_io_count(m, l1)
    check("U6. история (in/out) цела; отвязка не добавляет ledger-записей и не пишет 'del'",
          lb == la and lb >= 2 and "del" not in ledger_kinds(m, l1))

    # U7) Pending-катушка блокируется
    p1 = mk_spool(m); m.inv_bind_spool(p1, "PRN4", 0)
    m.conn_inv.execute("INSERT INTO inv_pending_prints (id, printer_id, fname, started_ts, deductions, status) VALUES (?,?,?,?,?,?)",
                       ("pp_u7", "PRN4", "j.gcode", 0, '[["%s", 120.0]]' % p1, "active"))
    m.conn_inv.commit()
    r = m.inv_unbind_spool(p1)
    check("U7. pending-катушка: отвязка заблокирована (blocked, reason=pending)",
          r.get("blocked") is True and r.get("reason") == "pending")

    # U8) Заблокированная остаётся привязанной (ams не очищен), pending-запись не закрыта
    prow = spool_row(m, p1)
    pend_open = m.conn_inv.execute("SELECT COUNT(*) AS n FROM inv_pending_prints WHERE id='pp_u7' AND status='active'").fetchone()["n"]
    check("U8. заблокированная остаётся привязанной; pending-запись не закрыта",
          prow["ams_printer_id"] == "PRN4" and int(prow["ams_slot"]) == 0 and pend_open == 1)

    # U9) Повторная отвязка идемпотентна
    u9 = mk_spool(m); m.inv_bind_spool(u9, "PRN5", 1)
    r1 = m.inv_unbind_spool(u9); r2 = m.inv_unbind_spool(u9)
    check("U9. повторная отвязка идемпотентна (2-й раз ok, already_unbound, previous пуст)",
          r1["ok"] and r2["ok"] and r2.get("already_unbound") is True and r2.get("previous_printer_id") == "")

    # U10) Другие катушки/слоты не меняются
    keep = mk_spool(m); m.inv_bind_spool(keep, "PRN6", 2)
    victim = mk_spool(m); m.inv_bind_spool(victim, "PRN6", 3)
    m.inv_unbind_spool(victim)
    kr = spool_row(m, keep)
    check("U10. соседняя привязка (тот же принтер, другой слот) не тронута",
          kr["ams_printer_id"] == "PRN6" and int(kr["ams_slot"]) == 2 and spool_row(m, victim)["ams_printer_id"] == "")

    # U11) Гонка: pending появился ПОСЛЕ того как отвязка была бы разрешена -> backend перепроверяет при мутации
    rc = mk_spool(m); m.inv_bind_spool(rc, "PRN7", 0)
    check("U11a. до pending отвязка была бы разрешена (нет в pending)", rc not in m._inv_pending_spool_ids())
    m.conn_inv.execute("INSERT INTO inv_pending_prints (id, printer_id, fname, started_ts, deductions, status) VALUES (?,?,?,?,?,?)",
                       ("pp_u11", "PRN7", "j", 0, '[["%s", 50.0]]' % rc, "active"))
    m.conn_inv.commit()
    r = m.inv_unbind_spool(rc)
    check("U11b. гонка: pending появился до отвязки -> backend блокирует, катушка остаётся привязанной",
          r.get("blocked") is True and spool_row(m, rc)["ams_printer_id"] == "PRN7")

    # U12) Общий SQL-helper отвязки существует (bind и unbind не дублируют SQL)
    check("U12. общий helper _inv_unbind_spool_sql существует (SQL отвязки в одном месте)",
          hasattr(m, "_inv_unbind_spool_sql"))

    # U13) Несуществующая катушка -> not_found (без падения)
    r = m.inv_unbind_spool("spool_nope")
    check("U13. отвязка несуществующей -> not_found", r.get("not_found") is True and r.get("ok") is False)


def main():
    tmp = tempfile.mkdtemp(prefix="inv_bulk_test_")
    dbpath = os.path.join(tmp, "farm_inventory_test.db")
    m = None
    try:
        m = load_backend(dbpath)
        run(m)          # пакетное удаление (18 проверок)
        run_single(m)   # одиночное удаление через единую проверку (S1–S11)
        run_unbind(m)   # явная отвязка от принтера/AMS (U1–U13)
    finally:
        try:
            if m is not None:
                m.conn_inv.close()
        except Exception:
            pass
        for fn in os.listdir(tmp):
            try:
                os.remove(os.path.join(tmp, fn))
            except Exception:
                pass
        try:
            os.rmdir(tmp)
        except Exception:
            pass

    print("\n" + ("FAIL: %d тестов провалено" % fail if fail else "PASS: пакетное удаление — все backend-тесты пройдены"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
