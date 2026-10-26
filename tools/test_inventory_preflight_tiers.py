# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.848 — три уровня проверки склада перед запуском печати (inventory 1.7.24).

ЗАЧЕМ. 17.08.2026 на ферме из 9 принтеров девятый не напечатал: склад отказал по нехватке
филамента, отказ потерялся в очереди, а владелец увидел лишь сообщение про освобождённую бронь.
Согласованный сценарий заменяет прежнее «отказ или ничего» на три исхода:

  1. ВПРИТЫК — нехватка в пределах погрешности учёта (INV_TIGHT_TOLERANCE_G): печать идёт,
     владелец получает уведомление. Катушки не взвешивают до грамма, и останавливать запуск
     из-за десятка граммов неправильно.
  2. КОНЧИЛАСЬ, НО ЕСТЬ НА СКЛАДЕ — учёт сам выполняет штатную замену катушки и уведомляет.
     ТОЛЬКО для внешней подачи и ТОЛЬКО когда принтер подтверждает тот же тип материала:
     подтверждение — доказательство, что оператор заправил то же самое.
  3. ЗАМЕНИТЬ НЕЧЕМ — блокирующий ответ с подробностями для окна решения.

Голой кнопки «печатать всё равно» в сценарии нет намеренно: она не чинит причину, и учёт
расходится с реальностью дальше. С Alpha 2.850 такой ответ существует, но не голым — вместе
с запуском он списывает остаток и оставляет строку в журнале склада; проверяет его отдельный
набор tools/test_print_anyway_option.py.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ. Разбор ответов хука на каждом уровне И фактическое состояние БД после
второго уровня (замена действительно проведена, а не только объявлена). Отдельно — что защита
не срабатывает вхолостую: при достаточном остатке ответа нет вовсе, а при неподтверждённом
материале замена НЕ делается.

БЕЗОПАСНОСТЬ. Временная БД в системном temp; настоящая папка данных фермы не открывается.
Принтеры поддельные, ничего никуда не отправляется.

Запуск:  python tools/test_inventory_preflight_tiers.py      (0 = сценарий работает)
"""
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
SENTINEL = "INVENTORY_PREFLIGHT_TIERS_SENTINEL_2_848"

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


class FakeCore:
    """Ядро для модуля: выдаёт id и телеметрию филамента. Ничего не печатает и никуда не ходит."""
    def __init__(self):
        self._n = 0
        self.reported = {}

    def new_id(self, prefix=""):
        self._n += 1
        return str(prefix) + format(self._n, "08d")

    def printers(self):
        return []

    def printer_states(self):
        return {}

    def get_printer_reported_filament(self, pid):
        return dict(self.reported.get(pid) or {"telemetry_available": False, "telemetry_fresh": False, "positions": []})


def reports(material, presence="setting"):
    """Свежая телеметрия принтера БЕЗ AMS: во внешней подаче указан материал.

    presence — ЧЕМ он подтверждён (ядро, 16.09.2026): "setting" — выбран на экране принтера
    (у внешней катушки Bambu датчика наличия нет, выбор остаётся и после того, как катушка
    кончилась); "sensor" — подтверждён датчиком. Замену катушки учёт делает только по датчику."""
    return {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [{"index": None, "external": True, "present": True, "presence": presence,
                           "reported_material": material, "reported_color": ""}]}


def reports_sensor(material):
    """Тот же отчёт, но подтверждённый датчиком подачи."""
    return reports(material, presence="sensor")


_OPENED = []          # соединения закрываем сами: Windows не отдаёт файл БД открытому процессу


def load_backend(dbpath, core):
    spec = importlib.util.spec_from_file_location("inv_backend_tiers", BACKEND)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.core = core
    m.conn_inv = sqlite3.connect(dbpath, check_same_thread=False)
    m.conn_inv.row_factory = sqlite3.Row
    m.lock_inv = threading.RLock()
    m._init_tables()
    m._inv_gcode_weights = lambda fdata: (list(fdata) if isinstance(fdata, (list, tuple)) else [])
    _OPENED.append(m.conn_inv)
    return m


def make_filament(m, material="PETG", color="Зелёный"):
    fid = m.core.new_id("fil_")
    with m.lock_inv:
        m.conn_inv.execute("INSERT INTO inv_filaments (id, material, color_name) VALUES (?,?,?)", (fid, material, color))
        m.conn_inv.commit()
    return fid


def make_spool(m, fid, remaining, status="in_stock", pid="", slot=-1, total=1000.0):
    sid = m.core.new_id("spool_")
    with m.lock_inv:
        m.conn_inv.execute(
            "INSERT INTO inv_spools (id, filament_id, weight_total_g, weight_remaining_g, status, ams_printer_id, ams_slot) "
            "VALUES (?,?,?,?,?,?,?)", (sid, fid, total, remaining, status, pid, slot))
        m.conn_inv.commit()
    return sid


def spool_row(m, sid):
    with m.lock_inv:
        r = m.conn_inv.execute("SELECT status, ams_printer_id, ams_slot, weight_remaining_g FROM inv_spools WHERE id=?", (sid,)).fetchone()
    return dict(r) if r else None


PID = "node_x11"


def r16_slot(r):
    """Слот первой нехватки в ответе хука (для проверок плана подачи)."""
    return (((r or {}).get("shortfall") or [{}])[0]).get("slot")

with tempfile.TemporaryDirectory(prefix="fm_inv_tiers_", ignore_cleanup_errors=True) as td:
    db = os.path.join(td, "farm_inventory.db")

    # ── УРОВЕНЬ 0: материала хватает — защита молчит (иначе все проверки ниже были бы вакуумными) ──
    core = FakeCore(); core.reported[PID] = reports("PETG")
    m = load_backend(db + ".0", core)
    fid = make_filament(m)
    make_spool(m, fid, 800.0, status="loaded", pid=PID, slot=-1)
    check("1. материала хватает — хук молчит (ответа нет)", m._inv_hook_pre_print(PID, [120.0], -1, "p.3mf") is None)

    # ── УРОВЕНЬ 1 (1.7.33, решение владельца 08.10.2026): допуска «впритык» больше нет ─────────
    #  Прежде нехватка до 30 г была лишь уведомлением «на исходе», и окно «Материал закончился» на
    #  ферме «не появлялось» (R-019). Теперь окно — при ЛЮБОЙ нехватке, даже в 1 г, и у пустой катушки.
    check("2. допуск «впритык» — 0 г", m.INV_TIGHT_TOLERANCE_G == 0.0, m.INV_TIGHT_TOLERANCE_G)
    for _i, (_have, _need, _what) in enumerate(((100.0, 120.0, "нехватка 20 г"), (100.0, 101.0, "нехватка 1 г"),
                                                 (0.0, 20.0, "пустая катушка, печать на 20 г"))):
        core = FakeCore(); core.reported[PID] = reports("PETG")
        m = load_backend(db + ".1%d" % _i, core)
        fid = make_filament(m)
        sid = make_spool(m, fid, _have, status="loaded", pid=PID, slot=-1)
        r = m._inv_hook_pre_print(PID, [_need], -1, "p.3mf")
        check("3.%d. %s — ОТКАЗ с окном решения (low_filament), а не надпись «на исходе»" % (_i + 1, _what),
              isinstance(r, dict) and r.get("status") == "low_filament" and len(r.get("shortfall") or []) == 1
              and not (r.get("tight") or []), r)
        check("4.%d. %s — катушка не тронута (замены не было)" % (_i + 1, _what),
              (spool_row(m, sid) or {}).get("status") == "loaded", spool_row(m, sid))

    # ── УРОВЕНЬ 2: кончилась, такая же есть на складе, материал подтверждён ДАТЧИКОМ подачи ──
    core = FakeCore(); core.reported[PID] = reports_sensor("PETG")
    m = load_backend(db + ".2", core)
    fid = make_filament(m)
    old = make_spool(m, fid, 10.0, status="loaded", pid=PID, slot=-1)
    new = make_spool(m, fid, 1000.0, status="in_stock")
    r = m._inv_hook_pre_print(PID, [500.0], -1, "p.3mf")
    check("5. кончилась + есть на складе + материал подтверждён ДАТЧИКОМ — печать НЕ блокируется",
          isinstance(r, dict) and r.get("status") == "advice", r)
    check("6. уведомление названо «катушка заменена»",
          isinstance(r, dict) and r.get("kind") == "spool_replaced" and len(r.get("resolved") or []) == 1, r)
    _old, _new = spool_row(m, old), spool_row(m, new)
    check("7. замена ПРОВЕДЕНА в учёте: прежняя помечена пустой и отвязана",
          _old and _old["status"] == "empty" and not _old["ams_printer_id"], _old)
    check("8. замена ПРОВЕДЕНА в учёте: новая привязана к тому же принтеру и слоту",
          _new and _new["status"] == "loaded" and _new["ams_printer_id"] == PID and _new["ams_slot"] == -1, _new)

    # ── 1.7.29: ВЫБОР МАТЕРИАЛА НА ЭКРАНЕ принтера подтверждением заправки НЕ является ──────
    #  У внешней катушки Bambu датчика наличия нет: выбранный на экране тип остаётся, когда катушка
    #  кончилась или её сняли. Прежде учёт по такому «подтверждению» САМ менял катушку и списывал бы
    #  с той, что лежит на полке (воспроизведено 16.09.2026). Теперь вопрос уходит к человеку.
    core = FakeCore(); core.reported[PID] = reports("PETG")          # presence="setting"
    m = load_backend(db + ".2s", core)
    fid = make_filament(m)
    old = make_spool(m, fid, 10.0, status="loaded", pid=PID, slot=-1)
    new = make_spool(m, fid, 1000.0, status="in_stock")
    r = m._inv_hook_pre_print(PID, [500.0], -1, "p.3mf")
    check("8a. материал только «по настройке принтера» — автозамены НЕТ, спрашиваем человека",
          isinstance(r, dict) and r.get("status") == "low_filament", r)
    _o, _n = spool_row(m, old), spool_row(m, new)
    check("8b. учёт не переписан: прежняя катушка на месте, складская осталась в наличии",
          _o and _o["status"] == "loaded" and _o["ams_printer_id"] == PID
          and _n and _n["status"] == "in_stock" and not _n["ams_printer_id"], (_o, _n))
    _sh = ((r or {}).get("shortfall") or [{}])[0]
    check("8c. в окне решения всё равно сказано, что показывает принтер, и что это не подтверждение",
          _sh.get("reported_material") == "PETG" and _sh.get("material_confirmed") is False, _sh)

    # ── УРОВЕНЬ 2 НЕ применяется, если принтер сообщает ДРУГОЙ материал ──────────────
    core = FakeCore(); core.reported[PID] = reports_sensor("PLA")   # датчик видит не то, что по учёту
    m = load_backend(db + ".3", core)
    fid = make_filament(m, material="PETG")
    old = make_spool(m, fid, 10.0, status="loaded", pid=PID, slot=-1)
    make_spool(m, fid, 1000.0, status="in_stock")
    r = m._inv_hook_pre_print(PID, [500.0], -1, "p.3mf")
    check("9. принтер сообщает ДРУГОЙ материал — автозамены НЕ делаем, спрашиваем человека",
          isinstance(r, dict) and r.get("status") == "low_filament", r)
    check("10. и катушка при этом НЕ тронута (учёт не переписан вслепую)",
          (spool_row(m, old) or {}).get("status") == "loaded", spool_row(m, old))

    # ── УРОВЕНЬ 3: заменить нечем — отказ с данными для окна решения ─────────────────
    core = FakeCore(); core.reported[PID] = reports_sensor("PETG")
    m = load_backend(db + ".4", core)
    fid = make_filament(m)
    old = make_spool(m, fid, 5.0, status="loaded", pid=PID, slot=-1)
    r = m._inv_hook_pre_print(PID, [500.0], -1, "p.3mf")
    check("11. кончилась и на складе такой нет — блокирующий ответ",
          isinstance(r, dict) and r.get("status") == "low_filament", r)
    sh = ((r or {}).get("shortfall") or [{}])[0]
    check("12. в ответе сказано, что подача ВНЕШНЯЯ и склад пуст", sh.get("external") is True and sh.get("stock") == 0, sh)
    check("13. есть материал, цвет и числа для человека",
          bool(sh.get("material")) and sh.get("needed") and sh.get("available") is not None, sh)
    check("14. есть чем оприходовать новую существующими маршрутами (филамент и номинал)",
          bool(sh.get("filament_id")) and float(sh.get("weight_total_g") or 0) > 0, sh)

    # ── AMS: остаток ведётся сам, окна решения не показываем, но и молча не гасим ────
    core = FakeCore()
    core.reported[PID] = {"telemetry_available": True, "telemetry_fresh": True,
                          "positions": [{"index": 0, "external": False, "present": True, "reported_material": "PETG"}]}
    m = load_backend(db + ".5", core)
    fid = make_filament(m)
    make_spool(m, fid, 5.0, status="loaded", pid=PID, slot=0)
    r = m._inv_hook_pre_print(PID, [500.0], 0, "p.3mf")
    sh = ((r or {}).get("shortfall") or [{}])[0]
    check("15. AMS-слот: отказ есть (молча не гасим), но помечен как НЕ внешний",
          isinstance(r, dict) and r.get("status") == "low_filament" and sh.get("external") is False, r)

    # ── 1.7.29: сверяется ТОТ слот, из которого пойдёт печать (план подачи от ядра) ──────────
    #  При запуске из очереди и пачкой слот в запросе не задан, и проверка смотрела в слот 0, пока
    #  печать шла из другого слота, с внешней катушки или из ячейки CFS.
    core = FakeCore(); core.reported[PID] = reports("PETG")
    m = load_backend(db + ".6", core)
    fid = make_filament(m)
    #  Оснастка нарочно такая, что запасной путь ВИДЕН: в слоте 0 пусто, в слоте 1 материал есть.
    #  Тогда «без плана» обязано дать отказ по слоту 0, а «подача не определена» — молчание.
    make_spool(m, fid, 5.0, status="loaded", pid=PID, slot=0)        # слот 0 почти пуст
    make_spool(m, fid, 1000.0, status="loaded", pid=PID, slot=1)     # а печать пойдёт из слота 1
    _r16 = m._inv_hook_pre_print(PID, [500.0], None, "p.3mf")
    check("16. без плана (старое ядро, четыре аргумента) сверяется слот 0 — отказ по нему",
          isinstance(_r16, dict) and r16_slot(_r16) == 0, _r16)
    check("17. с планом сверяется слот 1, где материала хватает — запуск не блокируется",
          m._inv_hook_pre_print(PID, [500.0], None, "p.3mf", plan={"slots": [1], "external": False}) is None)
    check("18. подача не определена (пустой список слотов) — не сверяем ничего, как и автосписание",
          m._inv_hook_pre_print(PID, [500.0], None, "p.3mf", plan={"slots": []}) is None)
    _r19 = m._inv_hook_pre_print(PID, [500.0], None, "p.3mf", plan={"slots": None})
    check("19. плана нет (None) — поведение как раньше, по слоту 0",
          isinstance(_r19, dict) and r16_slot(_r19) == 0, _r19)

    #  1.7.29: два филамента из ОДНОГО слота складываются до сравнения (иначе 30+30 «помещались»
    #  в катушку с 40 г и печать вставала посреди второй порции).
    core = FakeCore(); core.reported[PID] = reports("PETG")
    m = load_backend(db + ".7", core)
    fid = make_filament(m)
    make_spool(m, fid, 40.0, status="loaded", pid=PID, slot=1)
    r = m._inv_hook_pre_print(PID, [60.0, 60.0], None, "p.3mf", plan={"slots": [1], "external": False})
    _sh = ((r or {}).get("shortfall") or [{}])[0]
    check("20. два филамента из одного слота: сверяется СУММА (120 г против 40 г), а не каждый отдельно",
          isinstance(r, dict) and r.get("status") == "low_filament" and _sh.get("needed") == 120.0, r)
    #  Порознь каждая порция «поместилась» бы в остаток — и печать встала бы посреди второй.
    r2 = m._inv_hook_pre_print(PID, [30.0, 30.0], None, "p.3mf", plan={"slots": [1], "external": False})
    _sh2 = (((r2 or {}).get("tight") or []) + ((r2 or {}).get("shortfall") or []) + [{}])[0]
    check("20b. 30+30 против 40 г — нехватка видна (60 г), а не молчание",
          isinstance(r2, dict) and _sh2.get("needed") == 60.0, r2)

print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
if _fail:
    print("НЕ ПРОЙДЕНО:")
    for f in _fail:
        print("   - %s" % f)
sys.exit(1 if _fail else 0)
