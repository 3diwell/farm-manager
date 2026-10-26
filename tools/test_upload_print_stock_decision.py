# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-019 (29.09.2026) — «Загрузить» (файл с компьютера на принтер) и склад.

ЗАЧЕМ. Запуск из задач, проекта и очереди сверяется со складом, а когда материала не хватает,
показывает окно «Материал закончился» с тремя ответами: «Поставил новую катушку», «Пропустить
принтер», «Печатать всё равно» (два нажатия, остаток катушки списывается в ноль с записью в журнале
склада). Путь «Загрузить» (кнопка «Загр.» в пульте принтера и в новом интерфейсе → проводник →
«Печать», маршрут /api/printer/{pid}/print_path) склад не спрашивал вовсе. Решение владельца:
сделать так же, как в остальных путях.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ — ИСПОЛНЕНИЕМ, а не поиском строк:
  ЧАСТЬ 1. Настоящая функция маршрута print_path (вырезана из server.py) вместе с настоящим
    обходчиком хуков ядра и НАСТОЯЩИМ хуком модуля склада на временной БД:
      · материала не хватает → ответ low_filament с шагами списания, отправки на принтер НЕТ;
      · шаги, выполненные как их выполнит окно, обнуляют остаток и оставляют строку в журнале;
      · повтор с решением владельца (skip_filament) → склад не переспрашивается, отправка идёт;
      · материала хватает / склада нет → отправка идёт как раньше, форма ответа прежняя;
      · уведомление склада («впритык») печать не останавливает и доходит до окна полем notes;
      · принтер удержан планом или уже отправляет файл — ранний отказ 409 ДО склада: хук не
        вызван, учёт не тронут (иначе склад менялся бы ради заведомого отказа).
  ЧАСТЬ 2. Настоящие функции интерфейса (вырезаны из web/app.js) исполняются в Node:
      · отказ склада на «Загрузить» открывает ТО ЖЕ окно решения, в очередь ничего не ставится;
      · «Печатать всё равно»: первый клик взводит, второй — сначала отправка файла с решением
        владельца, и только после «принято» списание остатка; принтер отказал — списания нет;
        очередь не трогается;
      · «Поставил новую катушку»: шаги склада, потом отправка БЕЗ обхода склада;
      · прежний путь окна (пачка → очередь) не изменился.
  ЧАСТЬ 3. Разметка окна: подпись для одиночной отправки на двух языках.

БЕЗОПАСНОСТЬ. server.py не импортируется и не запускается. Временная БД в системном temp;
настоящая папка данных фермы не открывается. Отправка на принтер подменена записью вызова —
в сеть ничего не уходит, принтеров нет, ничего не печатается.

Запуск:  python tools/test_upload_print_stock_decision.py      (0 = сценарий работает)
"""
import ast
import asyncio
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
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
SERVER = os.path.join(REPO, "server.py")
APPJS = os.path.join(REPO, "web", "app.js")
INDEX = os.path.join(REPO, "web", "index.html")
NODE = r"C:\Program Files\nodejs\node.exe" if os.path.isfile(r"C:\Program Files\nodejs\node.exe") else (shutil.which("node") or "node")
SENTINEL = "UPLOAD_PRINT_STOCK_DECISION_SENTINEL_R019"

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def read(path):
    return io.open(path, encoding="utf-8", errors="surrogateescape").read()


# ══════════════════════════════════════════════════════════════════════════════
#  ЧАСТЬ 1. Сервер: настоящая функция маршрута + настоящий хук склада
# ══════════════════════════════════════════════════════════════════════════════

_src = read(SERVER)
_tree = ast.parse(_src)
_fns = {n.name: n for n in _tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
NEED = ("u_print_path", "_send_accept_response", "_run_pre_print_hooks", "_hook_wants_plan", "_hold_block",
        #  16.10.2026 (R-151): хуки вызываются со сроком (_call_hook) и правилом левой внешней катушки
        "_call_hook", "_hook_accepts", "_hook_module_name", "_plan_has_ext_left")
_HOOK_CONSTS = ("HOOK_DEADLINE_S", "_hook_call_lock", "_hooks_lock", "_hook_busy", "_hook_owner", "HOOK_LATE_CAP")
_const_nodes = [n for n in _tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id in _HOOK_CONSTS for t in n.targets)]
for _n in NEED:
    check("0. в server.py есть функция %s" % _n, _n in _fns)
if any(n not in _fns for n in NEED):
    print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
    sys.exit(1)


class Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class JSONResponse(dict):
    def __init__(self, content, status_code=200):
        super().__init__(content)
        self.status_code = status_code


class SendMgr:
    """Менеджер отправок: только ЗАПИСЫВАЕТ, что отправка началась бы. На принтер ничего не уходит.
    Удержание (holds) и занятость (reserved) отвечают так же, как настоящий reserve: отказом."""
    def __init__(self):
        self.calls = []
        self.holds = {}
        self.reserved = set()

    def begin_direct(self, pid, name, fname, source, send_callable):
        if pid in self.holds:
            return False, None, "printer_held"
        if pid in self.reserved:
            return False, "job_other", "busy"
        self.calls.append({"pid": pid, "fname": fname, "source": source})
        return True, "job_%d" % len(self.calls), ""

    def get_hold(self, pid):
        return self.holds.get(pid)

    def reserved_ids(self):
        return set(self.reserved)


class _Log:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass


def make_ns(printer_db, hooks, plan_calls):
    ns = {
        "Request": Req, "JSONResponse": JSONResponse, "os": os, "log": _Log(),
        "lock_pr": threading.RLock(), "conn_pr": printer_db,
        "_send_mgr": SendMgr(), "_print_hooks": {"pre_print_check": list(hooks)},
        "_hook_plan_arg": {}, "_exc_brief": lambda: "",
        "_hold_public": lambda h: h,
        #  13.10.2026: _hold_block проверяет и занятость принтера (printer_busy) — здесь принтер свободен,
        #  набор про решение склада; занятость проверяет tools/test_print_accounting_fixes_1013.py.
        "_dispatch_busy": lambda pid: False,
        "_mk_file_send": lambda *a, **k: (lambda progress: {"status": "ok"}),
        "_launch_feed_plan": lambda *a, **k: (plan_calls.append(a), None)[1],
        "asyncio": asyncio, "threading": threading, "time": __import__("time"), "_loaded_modules": {},
    }
    exec(compile(ast.Module(body=list(_const_nodes), type_ignores=[]), SERVER, "exec"), ns)
    for _n in NEED:
        exec(compile(ast.Module(body=[_strip(_fns[_n])], type_ignores=[]), SERVER, "exec"), ns)
    return ns


def _strip(node):
    """Функция БЕЗ декоратора маршрута: регистрировать её в приложении не нужно."""
    import copy
    n = copy.deepcopy(node)
    n.decorator_list = []
    return n


def call_route(ns, pid, body):
    return asyncio.run(ns["u_print_path"](pid, Req(body)))


# --- модуль склада на временной БД (как в test_print_anyway_option) ---
class FakeCore:
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


def reports_ams(material):
    return {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [{"index": 0, "external": False, "present": True,
                           "reported_material": material, "reported_color": ""}]}


_OPENED = []


def load_backend(dbpath, core):
    spec = importlib.util.spec_from_file_location("inv_backend_r019", BACKEND)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.core = core
    m.conn_inv = sqlite3.connect(dbpath, check_same_thread=False)
    m.conn_inv.row_factory = sqlite3.Row
    m.lock_inv = threading.RLock()
    m._init_tables()
    # вес печати берётся из «файла»: в нём записано число граммов — так файл на диске настоящий,
    # а разбор g-code (не предмет этой проверки) не нужен
    m._inv_gcode_weights = lambda fdata: [float(bytes(fdata).decode("ascii").strip())]
    _OPENED.append(m.conn_inv)
    return m


def make_spool(m, remaining, pid, slot):
    fid = m.core.new_id("fil_")
    sid = m.core.new_id("spool_")
    with m.lock_inv:
        m.conn_inv.execute("INSERT INTO inv_filaments (id, material, color_name) VALUES (?,?,?)", (fid, "PETG", "Зелёный"))
        m.conn_inv.execute(
            "INSERT INTO inv_spools (id, filament_id, weight_total_g, weight_remaining_g, status, ams_printer_id, ams_slot) "
            "VALUES (?,?,?,?,?,?,?)", (sid, fid, 1000.0, remaining, "loaded", pid, slot))
        m.conn_inv.commit()
    return sid


def remaining(m, sid):
    with m.lock_inv:
        r = m.conn_inv.execute("SELECT weight_remaining_g FROM inv_spools WHERE id=?", (sid,)).fetchone()
    return float(r["weight_remaining_g"]) if r else None


def ledger(m, sid):
    with m.lock_inv:
        rows = m.conn_inv.execute("SELECT reason FROM inv_ledger WHERE ref_type='spool' AND ref_id=?", (sid,)).fetchall()
    return [str(r["reason"] or "") for r in rows]


def run_steps(m, steps):
    done = 0
    for st in steps or []:
        mm = re.match(r"^/api/mod/([^/]+)/spool/([^/]+)/adjust$", str(st.get("url") or ""))
        if not mm:
            continue
        body = st.get("body") or {}
        m.inv_adjust_spool(mm.group(2), float(body.get("delta_g") or 0), str(body.get("reason") or ""))
        done += 1
    return done


PID = "node_x1c"

with tempfile.TemporaryDirectory(prefix="fm_r019_", ignore_cleanup_errors=True) as td:
    pdb = sqlite3.connect(os.path.join(td, "printers.db"), check_same_thread=False)
    pdb.row_factory = sqlite3.Row
    pdb.execute("CREATE TABLE printers (id TEXT, name TEXT, type TEXT, ip TEXT, port INTEGER, token TEXT)")
    pdb.execute("INSERT INTO printers VALUES (?,?,?,?,?,?)", (PID, "X1C-7", "bambu", "192.0.2.10", 990, "FIXTURE_TOKEN"))
    pdb.commit()
    gfile = os.path.join(td, "plate.gcode")
    with open(gfile, "wb") as fh:
        fh.write(b"600")                       # печати нужно 600 г

    print("--- 1. Материала не хватает: отказ до отправки, в ответе — шаги окна решения ---")
    core = FakeCore(); core.reported[PID] = reports_ams("PETG")
    m = load_backend(os.path.join(td, "inv_a.db"), core)
    sid = make_spool(m, 40.0, PID, 0)
    seen = []

    def spy_hook(printer_id, fdata, ams_slot, fname, plan=None):
        seen.append((printer_id, bytes(fdata), ams_slot, fname))
        return m._inv_hook_pre_print(printer_id, fdata, ams_slot, fname, plan=plan)

    plans = []
    ns = make_ns(pdb, [spy_hook], plans)
    r = call_route(ns, PID, {"path": gfile, "ams_slot": 0})
    check("1. «Загрузить» теперь спрашивает склад: хук вызван ровно один раз", len(seen) == 1, seen)
    check("2. склад получил НАСТОЯЩИЙ файл, слот и имя файла",
          seen and seen[0] == (PID, b"600", 0, "plate.gcode"), seen)
    check("3. слот сверяется по плану подачи, как в остальных путях (_launch_feed_plan вызван)",
          len(plans) == 1 and plans[0][:3] == (PID, "bambu", 0), plans)
    check("4. ответ — отказ склада low_filament, как у задач и очереди",
          isinstance(r, dict) and r.get("status") == "low_filament", r)
    check("5. ГЛАВНОЕ: файл на принтер НЕ отправлен", ns["_send_mgr"].calls == [], ns["_send_mgr"].calls)
    sh = ((r or {}).get("shortfall") or [{}])[0]
    steps = sh.get("override_steps") or []
    check("6. в ответе есть шаги «Печатать всё равно» от модуля склада", len(steps) == 1, sh)
    check("7. остаток до решения не тронут", remaining(m, sid) == 40.0, remaining(m, sid))

    print("--- 2. «Печатать всё равно»: списание в ноль, затем отправка без повторной проверки ---")
    check("8. шаги окна выполнены", run_steps(m, steps) == 1)
    check("9. В БД: остаток списан в ноль", remaining(m, sid) == 0.0, remaining(m, sid))
    check("10. В БД: в журнале склада строка о неподтверждённом расходе",
          any("не подтверждён" in x for x in ledger(m, sid)), ledger(m, sid))
    r2 = call_route(ns, PID, {"path": gfile, "ams_slot": 0, "skip_filament": True})
    check("11. с решением владельца склад НЕ переспрашивается", len(seen) == 1, len(seen))
    check("12. файл отправлен на принтер ровно один раз, тем же путём print_path",
          len(ns["_send_mgr"].calls) == 1 and ns["_send_mgr"].calls[0]["source"] == "print_path", ns["_send_mgr"].calls)
    check("13. ответ — «принято», как раньше", r2.get("status") == "ok" and r2.get("accepted") is True, r2)
    check("14. НЕ ВАКУУМ: без решения тот же запрос снова упирается в склад (остаток 0)",
          call_route(ns, PID, {"path": gfile, "ams_slot": 0}).get("status") == "low_filament"
          and len(ns["_send_mgr"].calls) == 1)

    print("--- 3. Материала хватает / склада нет: всё как раньше ---")
    core = FakeCore(); core.reported[PID] = reports_ams("PETG")
    m2 = load_backend(os.path.join(td, "inv_b.db"), core)
    make_spool(m2, 900.0, PID, 0)
    ns2 = make_ns(pdb, [m2._inv_hook_pre_print], [])
    r3 = call_route(ns2, PID, {"path": gfile, "ams_slot": 0})
    check("15. материала хватает — файл отправлен", len(ns2["_send_mgr"].calls) == 1, ns2["_send_mgr"].calls)
    check("16. форма ответа прежняя: лишних полей нет",
          set(r3.keys()) == {"status", "accepted", "job_id"}, r3)
    ns3 = make_ns(pdb, [], [])
    r4 = call_route(ns3, PID, {"path": gfile})
    check("17. склад не установлен — отправка как раньше",
          len(ns3["_send_mgr"].calls) == 1 and set(r4.keys()) == {"status", "accepted", "job_id"}, r4)
    ns4 = make_ns(pdb, [lambda *a: {"status": "advice", "kind": "filament_tight", "tight": [{"material": "PETG"}]}], [])
    r5 = call_route(ns4, PID, {"path": gfile})
    check("18. «впритык» печать НЕ останавливает", len(ns4["_send_mgr"].calls) == 1, ns4["_send_mgr"].calls)
    _nt = (r5.get("notes") or [{}])[0]
    check("19. уведомление склада доходит до окна полем notes, с принтером",
          _nt.get("kind") == "filament_tight" and _nt.get("printer_id") == PID and _nt.get("printer_name") == "X1C-7", r5)
    ns5 = make_ns(pdb, [lambda *a: 1 / 0], [])
    call_route(ns5, PID, {"path": gfile})
    check("20. сбой склада печать не срывает (fail-open, как у всех путей)", len(ns5["_send_mgr"].calls) == 1)
    r6 = call_route(ns2, PID, {"path": os.path.join(td, "нет_такого.gcode")})
    check("21. нет файла — прежний ответ, склад не спрашивается", r6.get("reason") == "Файл не найден", r6)

    print("--- 3а. Принтер удержан планом / уже отправляет файл: склад НЕ трогается ---")
    # Настоящий хук склада на катушке, которой НЕ хватает: без раннего отказа он вернул бы окно
    # «Материал закончился», и владелец списал бы остаток ради печати, которую принтер не примет.
    core = FakeCore(); core.reported[PID] = reports_ams("PETG")
    m3 = load_backend(os.path.join(td, "inv_c.db"), core)
    sid3 = make_spool(m3, 40.0, PID, 0)
    seen3 = []

    def spy3(printer_id, fdata, ams_slot, fname, plan=None):
        seen3.append(printer_id)
        return m3._inv_hook_pre_print(printer_id, fdata, ams_slot, fname, plan=plan)

    ns6 = make_ns(pdb, [spy3], [])
    ns6["_send_mgr"].holds[PID] = {"owner_type": "project_run", "owner_id": "prun_1"}
    r7 = call_route(ns6, PID, {"path": gfile, "ams_slot": 0})
    check("43. удержанный принтер: склад НЕ спрашивается (хук не вызван)", seen3 == [], seen3)
    check("44. удержанный принтер: отказ 409 printer_held, отправки нет",
          getattr(r7, "status_code", None) == 409 and r7.get("reason") == "printer_held"
          and ns6["_send_mgr"].calls == [], (r7, getattr(r7, "status_code", None)))
    r7b = call_route(ns6, PID, {"path": gfile, "ams_slot": 0, "skip_filament": True})
    check("45. и с «Печатать всё равно» удержанный принтер отказывает 409, отправки нет",
          getattr(r7b, "status_code", None) == 409 and r7b.get("reason") == "printer_held"
          and ns6["_send_mgr"].calls == [], r7b)
    del ns6["_send_mgr"].holds[PID]
    ns6["_send_mgr"].reserved.add(PID)
    r8 = call_route(ns6, PID, {"path": gfile, "ams_slot": 0})
    check("46. принтер уже отправляет файл: склад НЕ спрашивается, отказ 409 printer_send_busy",
          seen3 == [] and getattr(r8, "status_code", None) == 409 and r8.get("error") == "printer_send_busy"
          and ns6["_send_mgr"].calls == [], (r8, seen3))
    check("47. учёт склада не тронут: остаток прежний, журнал пуст",
          remaining(m3, sid3) == 40.0 and ledger(m3, sid3) == [], (remaining(m3, sid3), ledger(m3, sid3)))
    ns6["_send_mgr"].reserved.clear()
    r9 = call_route(ns6, PID, {"path": gfile, "ams_slot": 0})
    check("48. НЕ ВАКУУМ: принтер свободен — тот же запрос доходит до склада и упирается в него",
          seen3 == [PID] and isinstance(r9, dict) and r9.get("status") == "low_filament", (r9, seen3))
    pdb.close()

for c in _OPENED:
    try:
        c.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  ЧАСТЬ 2. Интерфейс: настоящие функции из web/app.js исполняются в Node
# ══════════════════════════════════════════════════════════════════════════════

print("--- 4. Интерфейс: «Загрузить» открывает то же окно решения ---")
_js = read(APPJS)


def cut(start, what):
    i = _js.find(start)
    if i < 0:
        return None
    j = _js.find("\n    };\n", _js.find(what, i))
    return _js[i:j + len("\n    };\n")] if j > 0 else None


blk_dec = cut("    const filDecision = ref(", "const filForceStart = async")
blk_send = cut("    const handleSendResp = (resp, ctx) => {", "const handleSendResp")
blk_ex = cut("    const exPrint = async (amsSlot", "const exPrint = async")
blk_rr = cut("    const READINESS_REASON_RU = {", "const readinessReasonText")
check("22. функции окна решения, отправки и «Загрузить» найдены в app.js",
      bool(blk_dec) and bool(blk_send) and bool(blk_ex) and bool(blk_rr))

HARNESS = r"""
'use strict';
const ref = (v) => ({ value: v });
const computed = (fn) => ({ get value() { return fn(); } });
const lang = ref('ru');
const tr = (s) => s;
const toasts = [], calls = [], optimistic = [];
const pushToast = (t, k) => toasts.push([String(t), k]);
const addOptimisticJob = (j) => optimistic.push(j);
const fetchSendJobs = () => {}, fetchPrintQueue = () => {};
const setTimeout = () => {};
const alert = (x) => toasts.push(['ALERT ' + x, 'alert']);
const openPrintStart = () => { throw new Error('окно параметров не должно открываться: print_opts передан'); };
const _printerNameOf = (pid) => 'X1C-7';
const exAmsOpen = ref(false), exOpen = ref(true), showModal = ref(true);
const exSelItem = ref({ name: 'plate.gcode', ext: '.gcode', path: 'C:/files/plate.gcode', is_dir: false });
const exPrintPid = ref('node_x1c');
let answer = () => ({ status: 'ok', accepted: true, job_id: 'j1' });
const fetch = async (url, opt) => {
    const body = opt && opt.body ? JSON.parse(opt.body) : null;
    calls.push({ url, body });
    const r = answer(url, body);
    return { json: async () => r };
};
/*CODE*/
const LOW = { status: 'low_filament', shortfall: [{ material: 'PETG', color_name: 'Зелёный', needed: 600, available: 40, slot: 0,
    external: false, resolve_steps: [], override_steps: [{ url: '/api/mod/inventory/spool/S1/adjust', method: 'POST', body: { delta_g: -40, reason: 'x' } }] }] };
const out = {};
(async () => {
    // A. отказ склада на «Загрузить»
    answer = () => LOW;
    await exPrint(0, null);
    out.a_open = filDecision.value.open === true;
    out.a_direct = filDecision.value.direct === true;
    out.a_rows = filDecision.value.rows.map(r => [r.printer_id, r.printer_name, r.override_steps.length]);
    out.a_calls = calls.map(c => c.url);
    out.a_first_body = calls[0] && calls[0].body;
    out.a_toasts = toasts.slice();
    out.a_optimistic = optimistic.length;
    // B. «Печатать всё равно»: первый клик только взводит
    calls.length = 0;
    const row = filDecision.value.rows[0];
    await filForceStart(row);
    out.b_armed = filDecision.value.confirm === 'node_x1c';
    out.b_calls_after_first = calls.length;
    // второй клик: списание, затем отправка с решением владельца
    answer = (url) => url.indexOf('/adjust') > 0 ? { ok: true } : { status: 'ok', accepted: true, job_id: 'j2' };
    await filForceStart(row);
    out.b_calls = calls.map(c => [c.url, c.body]);
    out.b_state = row.state;
    out.b_optimistic = optimistic.map(j => j.job_id);
    out.b_toasts = toasts.slice(out.a_toasts.length);
    // C. «Поставил новую катушку»: шаги склада, затем отправка без обхода склада
    calls.length = 0; toasts.length = 0; optimistic.length = 0;
    answer = () => LOW;
    await exPrint(0, null);
    const row2 = filDecision.value.rows[0];
    row2.resolve_steps = [{ url: '/api/mod/inventory/spools', method: 'POST', body: { a: 1 } }];
    calls.length = 0;
    answer = (url) => url.indexOf('/api/mod/') === 0 ? { ok: true } : { status: 'ok', accepted: true, job_id: 'j3',
        notes: [{ status: 'advice', kind: 'filament_tight', tight: [{ material: 'PETG' }], printer_id: 'node_x1c', printer_name: 'X1C-7' }] };
    await filReceiveAndStart(row2);
    out.c_calls = calls.map(c => [c.url, c.body]);
    out.c_state = row2.state;
    out.c_toasts = toasts.slice();
    // D. прежний путь окна (пачка → очередь) не изменился
    calls.length = 0;
    openFilamentDecision([{ printer_id: 'p9', printer_name: 'P9', shortfall: LOW.shortfall }], [{ printer_id: 'p9', flow: 'quick', gcode_file: 'a.gcode' }], 60);
    out.d_direct = filDecision.value.direct === true;
    answer = (url) => url.indexOf('/adjust') > 0 ? { ok: true } : { queued: ['p9'] };
    const row3 = filDecision.value.rows[0];
    await filForceStart(row3); await filForceStart(row3);
    out.d_calls = calls.map(c => [c.url, c.body]);
    // E. обычная отправка: уведомление склада показывается, окно не открывается
    closeFilamentDecision(); calls.length = 0; toasts.length = 0;
    answer = () => ({ status: 'ok', accepted: true, job_id: 'j4', notes: [{ status: 'advice', kind: 'filament_tight', tight: [{ material: 'PETG' }], printer_id: 'node_x1c', printer_name: 'X1C-7' }] });
    await exPrint(0, null);
    out.e_open = filDecision.value.open;
    out.e_toasts = toasts.slice();
    // F. «Печатать всё равно», а принтер отказал (удержан планом): остаток НЕ списывается
    calls.length = 0; toasts.length = 0; optimistic.length = 0;
    answer = () => LOW;
    await exPrint(0, null);
    const row4 = filDecision.value.rows[0];
    calls.length = 0;
    answer = (url) => url.indexOf('/adjust') > 0 ? { ok: true } : { status: 'error', reason: 'printer_held', printer_id: 'node_x1c', hold: {} };
    await filForceStart(row4); await filForceStart(row4);
    out.f_calls = calls.map(c => c.url);
    out.f_state = row4.state;
    out.f_toasts = toasts.slice();
    out.f_optimistic = optimistic.length;
    // G. обычная «Загрузить» на удержанный принтер: причина словами, а не кодом
    closeFilamentDecision(); calls.length = 0; toasts.length = 0;
    answer = () => ({ status: 'error', reason: 'printer_held', printer_id: 'node_x1c', hold: {} });
    await exPrint(0, null);
    out.g_toasts = toasts.slice();
    // H. 16.10.2026 (R-019): не хватает на ДВУХ катушках — в окне обе, «Печатать всё равно» списывает обе
    closeFilamentDecision(); calls.length = 0; toasts.length = 0; optimistic.length = 0;
    const LOW2 = { status: 'low_filament', shortfall: [LOW.shortfall[0], { material: 'PLA', color_name: 'Белый', needed: 300, available: 12,
        slot: 1, external: false, resolve_steps: [], override_steps: [{ url: '/api/mod/inventory/spool/S2/adjust', method: 'POST', body: { delta_g: -12, reason: 'x' } }] }] };
    answer = () => LOW2;
    await exPrint(0, null);
    const row5 = filDecision.value.rows[0];
    out.h_shorts = (row5.shorts || []).map(s => s.material + ':' + s.needed + '/' + s.available);
    calls.length = 0;
    answer = (url) => url.indexOf('/adjust') > 0 ? { ok: true } : { status: 'ok', accepted: true, job_id: 'j5' };
    await filForceStart(row5); await filForceStart(row5);
    out.h_calls = calls.map(c => c.url);
    // I. «Поставил новую катушку» — склад снова против (вторая катушка): строка остаётся открытой с новой нехваткой
    closeFilamentDecision(); calls.length = 0; toasts.length = 0;
    answer = () => ({ status: 'low_filament', shortfall: [Object.assign({}, LOW.shortfall[0], { resolve_steps: [{ url: '/api/mod/inventory/spools', method: 'POST', body: { a: 1 } }] })] });
    await exPrint(0, null);
    const row6 = filDecision.value.rows[0];
    calls.length = 0;
    answer = (url) => url.indexOf('/api/mod/') === 0 ? { ok: true } : { status: 'low_filament', shortfall: [LOW2.shortfall[1]] };
    await filReceiveAndStart(row6);
    out.i_open = filDecision.value.open;
    out.i_state = row6.state;
    out.i_mat = (row6.shorts || []).map(s => s.material + ':' + s.needed);
    out.i_calls = calls.map(c => c.url);
    out.i_toasts = toasts.map(t => t[0]);
    console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
"""

res = {}
if blk_dec and blk_send and blk_ex and blk_rr:
    with tempfile.TemporaryDirectory(prefix="fm_r019_js_", ignore_cleanup_errors=True) as tdj:
        hp = os.path.join(tdj, "harness.js")
        with io.open(hp, "w", encoding="utf-8") as fh:
            fh.write(HARNESS.replace("/*CODE*/", blk_rr + blk_dec + blk_send + blk_ex))
        try:
            pr = subprocess.run([NODE, hp], capture_output=True, text=True, encoding="utf-8", timeout=60)
            _last = (pr.stdout or "").strip().splitlines()[-1:] or ["{}"]
            res = json.loads(_last[0])
        except Exception as ex:
            res = {"error": "node: %s" % ex}
check("23. сценарий интерфейса исполнился без ошибок", "error" not in res, res.get("error"))

check("24. отказ склада открыл окно «Материал закончился»", res.get("a_open") is True, res)
check("25. окно помечено как одиночная отправка (подпись без «остальные в очереди»)", res.get("a_direct") is True, res)
check("26. в окне одна строка — этот принтер, с шагами списания от склада",
      res.get("a_rows") == [["node_x1c", "X1C-7", 1]], res.get("a_rows"))
check("27. первый запрос — print_path без обхода склада",
      res.get("a_calls") == ["/api/printer/node_x1c/print_path"] and "skip_filament" not in (res.get("a_first_body") or {}),
      (res.get("a_calls"), res.get("a_first_body")))
check("28. при отказе нет ни ложного «принято», ни тоста об ошибке",
      res.get("a_optimistic") == 0 and res.get("a_toasts") == [], (res.get("a_optimistic"), res.get("a_toasts")))
check("29. «Печатать всё равно»: первый клик только взводит, запросов нет",
      res.get("b_armed") is True and res.get("b_calls_after_first") == 0, res)
_bc = res.get("b_calls") or []
check("30. второй клик: СНАЧАЛА принтер принимает файл, ПОТОМ списание остатка (шаг склада)",
      [c[0] for c in _bc] == ["/api/printer/node_x1c/print_path", "/api/mod/inventory/spool/S1/adjust"], _bc)
check("31. файл уходит с решением владельца (skip_filament) и тем же путём и слотом",
      len(_bc) == 2 and (_bc[0][1] or {}).get("skip_filament") is True and (_bc[0][1] or {}).get("path") == "C:/files/plate.gcode"
      and (_bc[0][1] or {}).get("ams_slot") == 0, _bc)
check("32. в очередь ничего не ставится — «Загрузить» отправляет сразу",
      not any("/api/print-queue/enqueue" in c[0] for c in _bc), _bc)
check("33. строка отмечена, отправка появилась в панели отправок",
      res.get("b_state") == "queued" and res.get("b_optimistic") == ["j2"], (res.get("b_state"), res.get("b_optimistic")))
check("34. тост честно говорит: файл отправляется, остаток списан",
      any("файл отправляется на принтер, остаток списан" in t[0] for t in (res.get("b_toasts") or [])), res.get("b_toasts"))
_cc = res.get("c_calls") or []
check("35. «Поставил новую катушку»: шаг склада, затем отправка",
      [c[0] for c in _cc] == ["/api/mod/inventory/spools", "/api/printer/node_x1c/print_path"], _cc)
check("36. …и отправка БЕЗ обхода склада — учёт исправлен, склад проверит снова",
      len(_cc) == 2 and "skip_filament" not in (_cc[1][1] or {}), _cc)
check("37. уведомление склада после отправки показано", any("на исходе" in t[0] for t in (res.get("c_toasts") or [])), res.get("c_toasts"))
_dc = res.get("d_calls") or []
check("38. НЕ ВАКУУМ: прежнее окно пачки — не одиночное и по-прежнему ставит в очередь с решением",
      res.get("d_direct") is False and [c[0] for c in _dc] == ["/api/mod/inventory/spool/S1/adjust", "/api/print-queue/enqueue"]
      and ((_dc[1][1] or {}).get("items") or [{}])[0].get("skip_filament") is True, (res.get("d_direct"), _dc))
check("39. обычная «Загрузить»: окно не открывается, уведомление «впритык» показано",
      res.get("e_open") is False and any("на исходе" in t[0] for t in (res.get("e_toasts") or [])), (res.get("e_open"), res.get("e_toasts")))
check("49. ГЛАВНОЕ: принтер отказал (удержан) — остаток НЕ списан, запрос к складу не ушёл",
      res.get("f_calls") == ["/api/printer/node_x1c/print_path"], res.get("f_calls"))
check("50. строка отмечена «Не удалось», ложного «остаток списан» и «принято» нет",
      res.get("f_state") == "error" and res.get("f_optimistic") == 0
      and not any("остаток списан" in t[0] for t in (res.get("f_toasts") or [])), (res.get("f_state"), res.get("f_toasts")))
check("51. причина отказа словами: «Принтер удержан», а не код printer_held",
      any(t[0] == "Принтер удержан" for t in (res.get("f_toasts") or []))
      and not any("printer_held" in t[0] for t in (res.get("f_toasts") or [])), res.get("f_toasts"))
check("53. (16.10.2026, R-019) не хватает на двух катушках — в строке окна обе нехватки",
      res.get("h_shorts") == ["PETG:600/40", "PLA:300/12"], res.get("h_shorts"))
check("54. (R-019) «Печатать всё равно»: файл принят, потом списаны ОБЕ катушки (раньше — только первая)",
      res.get("h_calls") == ["/api/printer/node_x1c/print_path", "/api/mod/inventory/spool/S1/adjust",
                             "/api/mod/inventory/spool/S2/adjust"], res.get("h_calls"))
check("55. (R-019) «Поставил новую катушку», а склад снова против — окно открыто с новой нехваткой, а не «не удалось»",
      res.get("i_open") is True and res.get("i_state") == "" and res.get("i_mat") == ["PLA:300"]
      and res.get("i_calls") == ["/api/mod/inventory/spools", "/api/printer/node_x1c/print_path"]
      and any("снова сообщает нехватку" in t for t in (res.get("i_toasts") or [])), res)
check("52. обычная «Загрузить» на удержанный принтер — тоже словами",
      [t[0] for t in (res.get("g_toasts") or [])] == ["Принтер удержан"], res.get("g_toasts"))

# ══════════════════════════════════════════════════════════════════════════════
#  ЧАСТЬ 3. Разметка окна
# ══════════════════════════════════════════════════════════════════════════════
print("--- 5. Разметка окна решения ---")
_html = read(INDEX)
_i = _html.find('v-if="filDecision.open"')
_card = _html[_i:_html.find("</teleport>", _i)] if _i >= 0 else ""
check("40. подпись одиночной отправки — по-русски и по-английски",
      "filDecision.direct" in _card and "Нужно ваше решение — на складе такой катушки нет." in _card
      and "Your decision is needed — there is no such spool in stock." in _card)
check("41. прежняя подпись пачки на месте", "Остальные принтеры уже поставлены в очередь." in _card)
check("42. отметка строки для одиночной отправки — «Отправляется» / «Sending»",
      "'Отправляется'" in _card and "'Sending'" in _card)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
