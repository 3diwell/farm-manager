# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  R-151 (16.10.2026) — данные фермы не раздваиваются, модуль не держит печать и запуск.
#
#  ЧТО ДОКАЗЫВАЕТСЯ (исполнением настоящего кода; server.py разбирается по AST, кроме разделов E2E,
#  где он запускается изолированным экземпляром):
#    A. хуки печати со сроком: зависший модуль не держит запуск дольше срока, печать идёт с
#       предупреждением «проверка не выполнена»; пока хук висит, он пропускается сразу; отказ,
#       пришедший вовремя, останавливает как раньше; отказ по лицензии — только уведомление;
#       левая внешняя катушка H2D (-2) уходит только хукам, объявившим ext_left;
#    B. «Загрузить» (print_path): план подачи и хуки идут в потоке — цикл событий сервера живой;
#    C. зависший register() модуля: модуль снимается по сроку (load_error, причина timeout), его
#       поздние подписки отклоняются, ModuleCore.data_dir() — папка в module_data;
#    D. откат восстановления копии сохраняет столбцы, которых провайдер ядра не знает;
#    E. настоящий изолированный сервер: своя папка данных отключена — красный режим, изменения
#       отклоняются (503), второй фермы нет; папка вернулась — программа перезапустилась сама и
#       открыла настоящую ферму; модуль с зависшим register() не держит запуск;
#    F. стенд интерфейса: красное окно на четырёх размерах экрана без выхода за края и ошибок,
#       его кнопки; «Хранение данных» — настройки этого окна в файл;
#    G. текст уведомления «модуль не ответил» в интерфейсе (функция из web/app.js под Node).
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: рабочие DATA_DIR/config/БД/порт/замок не используются (изолированный
#  экземпляр app/e2e_isolation во временной папке); принтерам ничего не отправляется; сети нет.
#
#  Запуск:  PYTHONIOENCODING=utf-8 python tools/test_data_safety_r151.py   (0 = всё пройдено)
#  FM_R151_SKIP_E2E=1 — без разделов с настоящим сервером и стендом (быстрый прогон при отладке;
#  такой прогон НЕ считается пройденным: итог печатает BLOCKED).
# ============================================================================
import ast
import asyncio
import copy
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.dont_write_bytecode = True
SENTINEL = "DATA_SAFETY_R151_2026_10_16"

from app import data_dir_items as D                     # noqa: E402
from app import route_policy_registry as R              # noqa: E402
from app import route_access_control as RA              # noqa: E402
from app import module_catalog as MC                    # noqa: E402
from app import module_runtime_policy as MRP            # noqa: E402
from app.licensing import package as LPKG               # noqa: E402
from app.licensing import service as LSVC               # noqa: E402
from app.config_backup import serializer, validator, migrations, multistore, recovery   # noqa: E402
from app.config_backup import module_providers as mp    # noqa: E402
from app.config_backup.sqlite_store import SqliteModuleStore   # noqa: E402
from app.config_backup.repository import DictGateway    # noqa: E402
from app.config_backup.errors import BackupError        # noqa: E402

PASS, FAIL = [0], []
SKIPPED = []


def check(name, ok, extra=""):
    if ok:
        PASS[0] += 1
        print("PASS — %s" % name, flush=True)
    else:
        FAIL.append(name)
        print("FAIL — %s%s" % (name, ("  :: %s" % (extra,))[:900] if extra != "" else ""), flush=True)


def section(t):
    print("\n--- %s ---" % t, flush=True)


SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRV)
TMP = tempfile.mkdtemp(prefix="fm_r151_")


def fn_node(name):
    for n in TREE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            n2 = copy.deepcopy(n)
            if isinstance(n2, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n2.decorator_list = []          # маршрут в приложении регистрировать не нужно
            return n2
    raise AssertionError("в server.py нет %s" % name)


def assign_node(name):
    for n in TREE.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return n
    raise AssertionError("в server.py нет %s" % name)


MISSING = set()       # имена, которых нет в server.py (на прежнем коде — помощники R-151)


def load(ns, consts=(), funcs=()):
    body = []
    for c in consts:
        try:
            body.append(assign_node(c))
        except AssertionError:
            MISSING.add(c)
    for f in funcs:
        try:
            body.append(fn_node(f))
        except AssertionError:
            MISSING.add(f)
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), "server.py", "exec"), ns)
    return ns


class _Log(object):
    def __init__(self):
        self.lines = []

    def _rec(self, *a, **k):
        try:
            self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = _rec


def exc_brief():
    e = sys.exc_info()[1]
    return "%s: %s" % (type(e).__name__, e) if e else ""


# ════════════════════════════════════════════════════════════════════════════
section("A. хуки печати: срок, предупреждение, отказ, лицензия, левая внешняя катушка")

HOOK_FUNCS = ("_register_print_hook", "_call_hook", "_hook_accepts", "_hook_module_name", "_plan_has_ext_left",
              "_hook_wants_plan", "_run_pre_print_hooks", "_run_after_dispatch_hooks", "_fire_print_run_hooks")
HOOK_CONSTS = ("HOOK_DEADLINE_S", "_hook_call_lock", "_hooks_lock", "_hook_busy", "_hook_owner", "_hook_plan_arg",
               "_print_hooks", "HOOK_LATE_CAP")


def hooks_ns(deadline):
    ns = {"log": _Log(), "_exc_brief": exc_brief, "threading": threading, "time": time,
          "_loaded_modules": {"inventory": {"manifest": {"id": "inventory", "ru": "Складской учёт", "en": "Inventory"}}}}
    load(ns, HOOK_CONSTS, HOOK_FUNCS)
    ns["HOOK_DEADLINE_S"] = {k: float(deadline) for k in (ns.get("HOOK_DEADLINE_S") or {})}
    return ns


def add(ns, name, fn, owner="inventory"):
    ns["_print_hooks"][name].append(fn)
    ns.setdefault("_hook_owner", {})[id(fn)] = owner


ns = hooks_ns(0.3)
_release = threading.Event()
_calls = []


def hook_slow(printer_id, fdata, ams_slot, fname, plan=None):
    _calls.append("slow")
    _release.wait(10)
    return {"status": "low_filament", "shortfall": [{"slot": 0}]}


add(ns, "pre_print_check", hook_slow)
_adv = []
_t0 = time.monotonic()
_r = ns["_run_pre_print_hooks"]("p1", b"G28", None, "a.gcode", advice_out=_adv, plan={"slots": [0]})
_dt = time.monotonic() - _t0
check("A1. КРИТИЧНО: зависший склад не держит запуск — через срок печать идёт (ответ None), а владелец "
      "получает уведомление «проверка не выполнена» с именем модуля",
      _r is None and _dt < 0.9 and len(_adv) == 1 and _adv[0].get("kind") == "check_unavailable"
      and _adv[0].get("status") == "advice" and _adv[0].get("reason") == "timeout"
      and _adv[0].get("module_id") == "inventory" and _adv[0].get("module_name") == "Складской учёт"
      and _adv[0].get("module_name_en") == "Inventory",
      (_r, round(_dt, 2), _adv))
_adv2 = []
_t0 = time.monotonic()
_r2 = ns["_run_pre_print_hooks"]("p1", b"G28", None, "a.gcode", advice_out=_adv2, plan={"slots": [0]})
_dt2 = time.monotonic() - _t0
check("A2. пока тот вызов висит, хук пропускается СРАЗУ (потоки не копятся), уведомление то же",
      _r2 is None and _dt2 < 0.15 and _calls == ["slow"] and [a.get("reason") for a in _adv2] == ["busy"]
      and _adv2[0].get("kind") == "check_unavailable", (_dt2, _calls, _adv2))
_release.set()
_t0 = time.monotonic()
while ns.get("_hook_busy") and time.monotonic() - _t0 < 3:
    time.sleep(0.02)
_r3 = ns["_run_pre_print_hooks"]("p1", b"G28", None, "a.gcode", advice_out=[], plan={"slots": [0]})
check("A3. зависший вызов закончился — хук снова спрашивается, и его отказ, пришедший вовремя, "
      "останавливает запуск ровно как раньше",
      not ns.get("_hook_busy") and _calls == ["slow", "slow"] and isinstance(_r3, dict)
      and _r3.get("status") == "low_filament", (_calls, _r3))

ns = hooks_ns(2.0)
_block = {"status": "low_filament", "shortfall": [{"slot": 1, "needed": 30, "available": 5}]}
add(ns, "pre_print_check", lambda printer_id, fdata, ams_slot, fname: _block)
_r = ns["_run_pre_print_hooks"]("p1", b"", 1, "a.gcode", advice_out=[])
check("A4. отказ склада вовремя — тот же самый ответ, что вернул модуль (окно «Материал закончился»)",
      _r is _block)

ns = hooks_ns(2.0)


def hook_boom(printer_id, fdata, ams_slot, fname):
    raise RuntimeError("склад упал (изображено набором)")


add(ns, "pre_print_check", hook_boom)
_adv = []
_r = ns["_run_pre_print_hooks"]("p1", b"", None, "a.gcode", advice_out=_adv)
check("A5. упавший модуль: печать идёт, уведомление с причиной «ошибка» (раньше — молча, только в журнал)",
      _r is None and [(a.get("kind"), a.get("reason")) for a in _adv] == [("check_unavailable", "error")], _adv)

ns = hooks_ns(2.0)
add(ns, "pre_print_check", lambda printer_id, fdata, ams_slot, fname:
    {"status": "low_filament", "reason_class": "license", "shortfall": []})
_adv = []
_r = ns["_run_pre_print_hooks"]("p1", b"", None, "a.gcode", advice_out=_adv)
check("A6. отказ модуля по ЛИЦЕНЗИИ печать не останавливает — только уведомление (handoff §8)",
      _r is None and len(_adv) == 1 and _adv[0].get("reason") == "license"
      and _adv[0].get("kind") == "check_unavailable" and _adv[0].get("blocked_status") == "low_filament", _adv)

#  Левая внешняя катушка H2D: внутренний код -2 (у Bambu vir_slot 254).
ns = hooks_ns(2.0)
_seen = {}


def h_old(printer_id, fdata, ams_slot, fname):
    _seen["old"] = ams_slot


def h_plan(printer_id, fdata, ams_slot, fname, plan=None):
    _seen["plan"] = (ams_slot, plan)


def h_ext(printer_id, fdata, ams_slot, fname, plan=None, ext_left=False):
    _seen["ext"] = (ams_slot, plan, ext_left)


def h_kw(printer_id, fdata, ams_slot, fname, **kw):
    _seen["kw"] = (ams_slot, kw)


for _h in (h_old, h_plan, h_ext, h_kw):
    add(ns, "pre_print_check", _h)
_PL = {"slots": [-2], "external": True, "ext": 254, "source": "bambu_ext"}
_adv = []
_r = ns["_run_pre_print_hooks"]("p1", b"", -2, "a.gcode", advice_out=_adv, plan=_PL)
check("A7. левая внешняя катушка: хук, объявивший ext_left, получает план [-2] и ext_left=True",
      _seen.get("ext") == (-2, _PL, True), _seen.get("ext"))
check("A8. хук с планом, но без ext_left, -2 не видит: план с пустыми слотами («сверять не с чем»), "
      "слот не передан; **kwargs не считается объявлением ext_left",
      _seen.get("plan") == (None, dict(_PL, slots=[]))
      and _seen.get("kw") == (None, {"plan": dict(_PL, slots=[])}), (_seen.get("plan"), _seen.get("kw")))
check("A9. хук без плана и без ext_left при левой внешней катушке пропускается (старый склад сверил бы "
      "не ту катушку); исходный план не испорчен; ложного «проверка не выполнена» нет",
      "old" not in _seen and _PL["slots"] == [-2] and _r is None and _adv == [], (_seen, _adv))
_seen.clear()
_P0 = {"slots": [0], "source": "bambu_auto"}
ns["_run_pre_print_hooks"]("p1", b"", None, "a.gcode", advice_out=[], plan=_P0)
check("A10. обычная печать — как раньше: все хуки вызваны, ext_left никому не передан",
      _seen.get("old", "нет") is None and _seen.get("plan") == (None, _P0) and _seen.get("ext") == (None, _P0, False)
      and _seen.get("kw") == (None, {"plan": _P0}), _seen)

ns = hooks_ns(2.0)
_ad = []


def a_old(printer_id, ams_map, fdata, fname):
    _ad.append(("old", list(ams_map)))


def a_ext(printer_id, ams_map, fdata, fname, ext_left=False):
    _ad.append(("ext", list(ams_map), ext_left))


add(ns, "after_dispatch", a_old)
add(ns, "after_dispatch", a_ext)
ns["_run_after_dispatch_hooks"]("p1", [-2], b"", "a.gcode")
_ad_left = list(_ad)
_ad.clear()
ns["_run_after_dispatch_hooks"]("p1", [0], b"", "a.gcode")
check("A11. списание после отправки с левой внешней катушки — только модулю, объявившему ext_left; "
      "старый пропущен с записью в журнал; обычная отправка — всем, как раньше",
      _ad_left == [("ext", [-2], True)] and _ad == [("old", [0]), ("ext", [0], False)]
      and any("левую внешнюю" in ln for ln in ns["log"].lines), (_ad_left, _ad))

ns = hooks_ns(0.3)
_rel2 = threading.Event()
add(ns, "after_dispatch", lambda printer_id, ams_map, fdata, fname: _rel2.wait(10))
_got = []
add(ns, "print_run_finished", lambda snap: _rel2.wait(10))
add(ns, "print_run_finished", lambda snap: (snap.__setitem__("outcome_raw", "испорчено"), _got.append(snap)))
_t0 = time.monotonic()
ns["_run_after_dispatch_hooks"]("p1", [0], b"", "a.gcode")
_snap = {"run_id": "r1", "outcome_raw": "finished"}
ns["_fire_print_run_hooks"]("print_run_finished", _snap)
_dt = time.monotonic() - _t0
_rel2.set()
check("A12. зависшие after_dispatch и print_run_* держат отправку и наблюдение за печатью не дольше "
      "срока; следующий подписчик всё равно получает событие (копию: исходник не меняется)",
      _dt < 1.5 and len(_got) == 1 and _snap["outcome_raw"] == "finished", (round(_dt, 2), _got))
check("A13. сроки по умолчанию: проверка 20 с, после отправки 30 с, события печати 10 с",
      load({"threading": threading}, ("HOOK_DEADLINE_S",)).get("HOOK_DEADLINE_S")
      == {"pre_print_check": 20.0, "after_dispatch": 30.0, "print_run_started": 10.0, "print_run_finished": 10.0})

#  16.10.2026 (ревизия R-151): отметка «висит» — по вызову. Два одновременных вызова одного хука:
#  первый завис и пережил срок, второй закончился нормально — отметка первого должна остаться.
ns = hooks_ns(1.0)
_relH, _a_out = threading.Event(), threading.Event()
_hres = {}


def h_two(mode):
    if mode == "hang":
        _relH.wait(10)
    elif mode == "quick":
        _a_out.wait(5)                  # заканчивается ПОСЛЕ того, как первый вызов пережил срок
    return mode


def _call_a():
    _hres["a"] = ns["_call_hook"]("pre_print_check", h_two, ("hang",))
    _a_out.set()


_ta = threading.Thread(target=_call_a, daemon=True)
_ta.start()
time.sleep(0.5)
_tb = threading.Thread(target=lambda: _hres.__setitem__("b", ns["_call_hook"]("pre_print_check", h_two, ("quick",))),
                       daemon=True)
_tb.start()
_ta.join(5)
_tb.join(5)
_t0 = time.monotonic()
_hres["c"] = ns["_call_hook"]("pre_print_check", h_two, ("hang",))
_dtc = time.monotonic() - _t0
_relH.set()
check("A14. два вызова одного хука: первый завис, второй закончился вовремя — третий всё равно "
      "пропускается СРАЗУ (отметку «висит» снимает только сам зависший вызов)",
      _hres.get("a") == ("timeout", None) and _hres.get("b") == ("ok", "quick")
      and _hres.get("c") == ("busy", None) and _dtc < 0.5, (_hres, round(_dtc, 2)))
_t0 = time.monotonic()
while ns.get("_hook_busy") and time.monotonic() - _t0 < 3:
    time.sleep(0.02)
check("A14b. зависший вызов закончился — отметка снята, хук снова вызывается",
      not ns.get("_hook_busy") and ns["_call_hook"]("pre_print_check", h_two, ("x",)) == ("ok", "x"),
      ns.get("_hook_busy"))

#  Списание после отправки: зависшее прежнее списание НЕ отменяет следующее, а само доходит позже.
ns = hooks_ns(0.3)
_relD = threading.Event()
_ded = []


def a_deduct(printer_id, ams_map, fdata, fname):
    if printer_id == "p1":
        _relD.wait(10)                  # склад один раз думал дольше срока
    _ded.append(printer_id)


add(ns, "after_dispatch", a_deduct)
_t0 = time.monotonic()
ns["_run_after_dispatch_hooks"]("p1", [0], b"", "big.3mf")
ns["_run_after_dispatch_hooks"]("p2", [0], b"", "small.gcode")
_dtd = time.monotonic() - _t0
_ded_before = list(_ded)
_relD.set()
_t0 = time.monotonic()
#  запись в журнал об опоздании идёт сразу после снятия отметки — её тоже ждём
while (len(_ded) < 2 or ns.get("_hook_busy") or not any("после срока" in ln for ln in ns["log"].lines)) \
        and time.monotonic() - _t0 < 3:
    time.sleep(0.02)
check("A15. КРИТИЧНО: склад один раз не уложился в срок — следующая отправка всё равно списана "
      "(прежде пропускалась молча, и остаток расходился), а опоздавшее списание дошло само",
      _ded_before == ["p2"] and sorted(_ded) == ["p1", "p2"] and _dtd < 1.2 and not ns.get("_hook_busy")
      and any("после срока" in ln and "printer=p1" in ln and "big.3mf" in ln for ln in ns["log"].lines),
      (_ded_before, _ded, round(_dtd, 2), ns["log"].lines[-4:]))

ns = hooks_ns(0.2)
ns["HOOK_LATE_CAP"] = 2
_relE = threading.Event()
_ded2 = []
add(ns, "after_dispatch", lambda printer_id, ams_map, fdata, fname: (_relE.wait(10), _ded2.append(printer_id)))
for _p in ("p1", "p2", "p3"):
    ns["_run_after_dispatch_hooks"](_p, [0], b"", _p + ".gcode")
_relE.set()
_t0 = time.monotonic()
while (len(_ded2) < 2 or ns.get("_hook_busy")) and time.monotonic() - _t0 < 3:
    time.sleep(0.02)
check("A16. настоящее зависание: зависших списаний одного хука не больше предела (потоки и файлы в памяти "
      "не копятся), а пропущенное названо в журнале с принтером, файлом и «проверьте остаток»",
      sorted(_ded2) == ["p1", "p2"]
      and any("проверьте остаток" in ln and "printer=p3" in ln and "p3.gcode" in ln for ln in ns["log"].lines),
      (_ded2, ns["log"].lines[-3:]))

# ════════════════════════════════════════════════════════════════════════════
section("B. «Загрузить»: план подачи и хуки — в потоке, цикл событий сервера живой (R-148)")


class _Req(object):
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _JSONResponse(dict):
    def __init__(self, content, status_code=200):
        dict.__init__(self, content)
        self.status_code = status_code


class _SendMgr(object):
    def __init__(self):
        self.calls = []

    def begin_direct(self, pid, name, fname, source, send_callable):
        self.calls.append(pid)
        return True, "job_1", ""

    def reserved_ids(self):
        return set()


_pdb = sqlite3.connect(":memory:", check_same_thread=False)
_pdb.row_factory = sqlite3.Row
_pdb.execute("CREATE TABLE printers (id TEXT, name TEXT, type TEXT, ip TEXT, port INTEGER, token TEXT)")
_pdb.execute("INSERT INTO printers VALUES ('p1', 'Принтер 1', 'flashforge', '127.0.0.1', 8899, 'FIXTURE_TOKEN')")
_GFILE = os.path.join(TMP, "part.gcode")
io.open(_GFILE, "w", encoding="utf-8").write("; filament used [g] = 5\nG28\n")


def upp_ns(deadline, plan_delay):
    ns = hooks_ns(deadline)
    ns.update({"os": os, "asyncio": asyncio, "JSONResponse": _JSONResponse, "Request": _Req,
               "lock_pr": threading.RLock(), "conn_pr": _pdb, "_send_mgr": _SendMgr(),
               "_hold_block": lambda pid: None,
               "_mk_file_send": lambda *a, **k: (lambda progress: {"status": "ok"}),
               "_launch_feed_plan": lambda *a, **k: (time.sleep(plan_delay), {"slots": [0], "source": "t"})[1],
               "_send_accept_response": lambda ok, job, reason, pid, extra=None:
                   dict({"status": "accepted" if ok else "error", "job_id": job}, **(extra or {}))})
    load(ns, (), ("u_print_path",))
    return ns


async def _scenario(ns):
    ticks, stop = [0], [False]

    async def ticker():
        while not stop[0]:
            ticks[0] += 1
            await asyncio.sleep(0.05)
    t = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    t0 = time.monotonic()
    res = await ns["u_print_path"]("p1", _Req({"path": _GFILE}))
    dt = time.monotonic() - t0
    stop[0] = True
    await t
    return res, ticks[0], dt


ns = upp_ns(5.0, 0.5)
add(ns, "pre_print_check", lambda printer_id, fdata, ams_slot, fname, plan=None: (time.sleep(1.0), None)[1])
_res, _ticks, _dt = asyncio.run(_scenario(ns))
check("B1. КРИТИЧНО: пока разбирается файл (0,5 с) и отвечает склад (1 с), сервер продолжает "
      "обслуживать остальных — цикл событий не замирает; запуск принят",
      _res.get("status") == "accepted" and _ticks >= 15 and 1.3 <= _dt < 4, (_res, _ticks, round(_dt, 2)))
ns = upp_ns(0.3, 0.0)
add(ns, "pre_print_check", lambda printer_id, fdata, ams_slot, fname, plan=None: (time.sleep(2.0), None)[1])
_res, _ticks, _dt = asyncio.run(_scenario(ns))
_notes = _res.get("notes") or []
check("B2. склад не ответил за срок — печать отправлена, в ответе уведомление с именем принтера для окна",
      _res.get("status") == "accepted" and _dt < 1.5 and len(_notes) == 1
      and _notes[0].get("kind") == "check_unavailable" and _notes[0].get("printer_name") == "Принтер 1",
      (_res, round(_dt, 2)))


def _offloaded(fn_name):
    """Каждый вызов хуков и каждое упоминание плана подачи в fn_name — внутри await asyncio.to_thread(...)."""
    fn = fn_node(fn_name)
    inside = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Await) and isinstance(n.value, ast.Call) \
                and ast.unparse(n.value.func) == "asyncio.to_thread":
            inside.update(id(x) for x in ast.walk(n.value))
    hooks = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_run_pre_print_hooks"]
    plans = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "_launch_feed_plan"]
    return bool(hooks) and bool(plans) and all(id(x) in inside for x in hooks + plans)


check("B3. так же устроены «печать детали» и печать файла проекта: план и хуки — в потоке",
      _offloaded("part_print") and _offloaded("_do_project2_file_print") and _offloaded("u_print_path"))

# ════════════════════════════════════════════════════════════════════════════
section("C. модуль, чей register() завис: снят по сроку, программа поднимается без него")

DD = os.path.join(TMP, "data")
os.makedirs(DD)


class _App(object):
    def __init__(self):
        self.routes = []

    def add_api_route(self, path, handler, methods=None):
        self.routes.append((tuple(methods or ()), path))


MOD_CONSTS = ("MODULE_STATE_LOADED", "MODULE_STATE_DISABLED", "MODULE_STATE_VERSION_MISMATCH",
              "MODULE_STATE_ROUTE_MISMATCH", "MODULE_STATE_INVALID_MANIFEST", "MODULE_STATE_LOAD_ERROR",
              "MODULE_STATE_PENDING_RESTART", "MODULE_STATE_INTEGRITY_FAILED", "MODULE_STATE_PACKAGE_UNTRUSTED",
              "MODULE_STATES", "MODULE_REGISTER_DEADLINE_S", "MODULE_REGISTER_WARN_S")
MOD_FUNCS = ("_module_id_ok", "_read_manifest", "ModuleCore", "_module_routes_validate", "_module_rollback",
             "_module_failure_state", "_module_expected_version", "_note_failed_module", "_module_core_contract",
             "_module_run_register", "_register_module", "_module_feature_gate", "_module_licensing_view",
             "api_modules_list", "_register_print_hook")
MNS = {"re": re, "os": os, "_jsonmod": json, "_ilu": importlib.util, "log": _Log(), "app": _App(),
       "_route_registry": R, "_route_access": RA, "_module_catalog": MC, "_module_rt_policy": MRP,
       "_exc_brief": exc_brief, "_loaded_modules": {}, "_failed_modules": {}, "_disabled_modules": {},
       "_registered_backends": set(), "_modules_restart_needed": False,
       "_print_hooks": {"pre_print_check": [], "after_dispatch": [], "print_run_started": [], "print_run_finished": []},
       "_printer_badge_providers": [], "_printer_filament_providers": [], "_lic_pkg": LPKG,
       "_LICENSES": LSVC.LicenseService(os.path.join(TMP, "lic"), trusted={}), "secrets": secrets,
       "threading": threading, "time": time, "_hooks_lock": threading.RLock(), "_hook_owner": {},
       "DATA_DIR": DD, "_resolve_db": lambda n: os.path.join(DD, n), "_uid": lambda p="": p + secrets.token_hex(4)}
load(MNS, MOD_CONSTS, MOD_FUNCS)
MNS["MODULE_REGISTER_DEADLINE_S"] = 0.5
MNS["MODULE_REGISTER_WARN_S"] = 0.2


def make_module(mid, body):
    d = os.path.join(TMP, "mods", mid)
    os.makedirs(d)
    io.open(os.path.join(d, "module.json"), "w", encoding="utf-8").write(
        json.dumps({"id": mid, "ru": "Модуль " + mid, "en": "Module " + mid, "version": "0.0.1"}))
    io.open(os.path.join(d, "backend.py"), "w", encoding="utf-8").write(body)
    return d


SLOW = make_module("r151slow", (
    "import json, os, time\n"
    "OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'late.json')\n"
    "def _early(snap):\n    pass\n"
    "def _late(*a, **k):\n    return None\n"
    "def register(core):\n"
    "    core.add_hook('print_run_finished', _early)\n"
    "    time.sleep(1.2)\n"
    "    res = {'hook': core.add_hook('pre_print_check', _late),\n"
    "           'badge': core.add_printer_badge_provider(lambda: {})}\n"
    "    try:\n"
    "        core.add_route('late', _late, ['GET'], policy_id='x.late')\n"
    "        res['route'] = 'принят'\n"
    "    except RuntimeError:\n"
    "        res['route'] = 'отклонён'\n"
    "    io = open(OUT, 'w')\n    io.write(json.dumps(res))\n    io.close()\n"))
_t0 = time.monotonic()
_mid = MNS["_register_module"](SLOW, "user")
_dt = time.monotonic() - _t0
_fm = MNS["_failed_modules"].get("r151slow") or {}
check("C1. КРИТИЧНО: register() завис — загрузчик ждёт не дольше срока и идёт дальше; модуль не "
      "подключён (load_error, причина timeout)",
      _mid is None and _dt < 1.0 and _fm.get("state") == "load_error" and _fm.get("reason") == "timeout"
      and "r151slow" not in MNS["_loaded_modules"], (_mid, round(_dt, 2), _fm))
check("C2. то, что модуль успел подписать до зависания, снято (хук событий печати)",
      MNS["_print_hooks"]["print_run_finished"] == [])
_lst = [m for m in MNS["api_modules_list"]()["modules"] if m["id"] == "r151slow"]
check("C3. список модулей показывает причину timeout — интерфейс объяснит «не ответил при запуске»",
      len(_lst) == 1 and _lst[0].get("state") == "load_error" and _lst[0].get("reason") == "timeout", _lst)
_late_path = os.path.join(SLOW, "late.json")
_t0 = time.monotonic()
while not os.path.isfile(_late_path) and time.monotonic() - _t0 < 5:
    time.sleep(0.05)
time.sleep(0.1)
_late = json.load(io.open(_late_path, encoding="utf-8")) if os.path.isfile(_late_path) else {}
check("C4. проснувшийся позже register() ничего не подключает: хук и провайдер отклонены, маршрут отклонён",
      _late == {"hook": False, "badge": False, "route": "отклонён"}
      and MNS["_print_hooks"]["pre_print_check"] == [] and MNS["_printer_badge_providers"] == [], _late)
OKM = make_module("r151ok", "def _h(*a, **k):\n    return None\n"
                            "def register(core):\n    core.add_hook('pre_print_check', _h)\n")
_mid = MNS["_register_module"](OKM, "user")
check("C5. обычный модуль загружается как раньше (через тот же срок), владелец хука записан для уведомлений",
      _mid == "r151ok" and len(MNS["_print_hooks"]["pre_print_check"]) == 1
      and MNS["_hook_owner"].get(id(MNS["_print_hooks"]["pre_print_check"][0])) == "r151ok")
BAD = make_module("r151bad", "def register(core):\n    raise RuntimeError('упал')\n")
_mid = MNS["_register_module"](BAD, "user")
check("C6. упавший register() — load_error без причины timeout (как раньше)",
      _mid is None and (MNS["_failed_modules"].get("r151bad") or {}).get("state") == "load_error"
      and (MNS["_failed_modules"].get("r151bad") or {}).get("reason") == "")
_core = MNS["ModuleCore"]("r151ok", OKM, "0.0.1")
_want = os.path.join(DD, "module_data", "r151ok")
_before = os.path.exists(_want)
_got = _core.data_dir() if hasattr(_core, "data_dir") else None
check("C7. ModuleCore.data_dir(): папка файлов модуля — <папка данных>/module_data/<id>, создаётся при "
      "первом обращении; в общем списке папки данных она переезжает (MOVE)",
      not _before and _got == _want and os.path.isdir(_want) and _got is not None and _core.data_dir() == _want
      and D.classify("module_data", True).action == D.MOVE, (_got, _want))
check("C8. срок запуска модуля по умолчанию — 30 с (меньше 60 с, которые оболочка ждёт сервер)",
      load({}, ("MODULE_REGISTER_DEADLINE_S",)).get("MODULE_REGISTER_DEADLINE_S") == 30.0)

# ════════════════════════════════════════════════════════════════════════════
section("D. откат восстановления копии сохраняет столбцы более новой версии модуля")

INV = mp.get_provider("inventory")


def _inv_rows(label="L"):
    return [{"id": "s1", "filament_id": "", "label": label, "weight_total_g": 1,
             "weight_remaining_g": 1, "location_id": "", "price": 0, "lot": "", "purchased_at": "",
             "opened_at": "", "status": "in_stock", "nfc_uid": "", "ams_printer_id": "",
             "ams_slot": -1, "notes": "", "order_idx": 0, "is_deleted": 0,
             "created_at": "t", "updated_at": "t"}]


def mk_inv_db(path):
    c = sqlite3.connect(path)
    for sp in INV.table_specs:
        cols = ", ".join('"%s"%s' % (col, " PRIMARY KEY" if col == sp.key else "") for col in sp.columns)
        if sp.name == "inv_spools":
            cols += ', "extra" TEXT DEFAULT \'\', "raw_blob" BLOB'      # столбцы «новой версии модуля»
        c.execute('CREATE TABLE "%s" (%s)' % (sp.name, cols))
    c.execute('CREATE TABLE "inv_settings" (key TEXT PRIMARY KEY, value TEXT)')
    c.commit()
    c.close()


def spool_row(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute("SELECT * FROM inv_spools ORDER BY id")]
    finally:
        c.close()


DBI = os.path.join(TMP, "farm_inventory.db")
mk_inv_db(DBI)
sq = SqliteModuleStore(DBI, INV.table_specs, "inv_settings", ("key", "value"))
sq.upsert_rows("inv_spools", _inv_rows("исходная"), "id")
_c = sqlite3.connect(DBI)
_c.execute("UPDATE inv_spools SET extra='x', raw_blob=? WHERE id='s1'", (b"\x00\x01\xff",))
_c.commit()
_c.close()
_pre = sq.full_snapshot()
_pre_json = json.loads(json.dumps(_pre))           # журнал восстановления — JSON
_row = (_pre["tables"].get("inv_spools") or [{}])[0]
check("D1. pre-image хранит ВСЕ столбцы строки (и байты — в виде, который переживает JSON-журнал)",
      _row.get("extra") == "x" and isinstance(_row.get("raw_blob"), dict) and _pre_json == _pre, _row)
_c = sqlite3.connect(DBI)
_c.execute("UPDATE inv_spools SET extra='changed', label='чужая', raw_blob=NULL")
_c.execute("INSERT INTO inv_spools (id, label) VALUES ('s2', 'лишняя')")
_c.commit()
_c.close()
sq.restore_full(_pre_json)
_rows = spool_row(DBI)
check("D2. КРИТИЧНО: откат к pre-image вернул и столбцы, которых нет в спецификации ядра (extra, байты)",
      len(_rows) == 1 and _rows[0]["extra"] == "x" and _rows[0]["label"] == "исходная"
      and _rows[0]["raw_blob"] == b"\x00\x01\xff", _rows)
check("D3. сверка отката по SHA видит все столбцы и сходится",
      multistore._sha(sq.full_snapshot()) == multistore._sha(_pre))
check("D4. экспорт (резервная копия) по-прежнему читает только столбцы спецификации",
      set((sq.read_table("inv_spools") or [{}])[0]) == set([s for s in INV.table_specs if s.name == "inv_spools"][0].columns))
_legacy = {"tables": {"inv_spools": sq.read_table("inv_spools")}, "settings": {}}
_c = sqlite3.connect(DBI)
_c.execute("UPDATE inv_spools SET label='после'")
_c.commit()
_c.close()
sq.restore_full(_legacy)
check("D5. журнал прежнего формата (только столбцы спецификации) восстанавливается как раньше",
      [r["label"] for r in spool_row(DBI)] == ["исходная"])

#  Настоящий движок восстановления: применение падает посреди модуля — откат обязан вернуть extra.
DBI2 = os.path.join(TMP, "farm_inventory2.db")
mk_inv_db(DBI2)


class BoomStore(SqliteModuleStore):
    def upsert_rows(self, name, rows, key):
        SqliteModuleStore.upsert_rows(self, name, rows, key)
        if name == "inv_spools":
            raise RuntimeError("сбой посреди восстановления (изображено набором)")


sq2 = BoomStore(DBI2, INV.table_specs, "inv_settings", ("key", "value"))
SqliteModuleStore.upsert_rows(sq2, "inv_spools", _inv_rows("живая"), "id")
_c = sqlite3.connect(DBI2)
_c.execute("UPDATE inv_spools SET extra='x'")
_c.commit()
_c.close()
_snap = INV.export_snapshot(mp.DictModuleStore(tables={"inv_spools": _inv_rows("из копии")},
                                               settings={"currency": "RUB"}), "1.7.24")
_blob = serializer.export_backup_v2(DictGateway(config={"lan_access_enabled": True}, app_settings={}, printers=[]),
                                    created_by="t", created_at="t", module_exports=[_snap])
_payload = validator.validate_payload(migrations.migrate_to_current(serializer.decode_payload(_blob).as_dict()))
_why = None
try:
    multistore.apply_restore_multistore(DictGateway(config={"lan_access_enabled": False}, app_settings={}, printers=[]),
                                        _payload, ["modules"],
                                        recovery.RecoveryJournal(os.path.join(TMP, "j.json")),
                                        {"inventory": sq2}, {"inventory": "1.7.24"})
except BackupError as e:
    _why = e.reason
_rows2 = spool_row(DBI2)
check("D6. КРИТИЧНО: восстановление копии упало посреди модуля — «безопасный откат» вернул строку "
      "целиком, включая столбец новой версии модуля (прежде он сбрасывался)",
      _why == "rollback_completed" and len(_rows2) == 1 and _rows2[0]["label"] == "живая"
      and _rows2[0]["extra"] == "x", (_why, _rows2))

# ════════════════════════════════════════════════════════════════════════════
#  E. Настоящий изолированный сервер
# ════════════════════════════════════════════════════════════════════════════
from app import e2e_isolation as ISO      # noqa: E402

APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRV, re.M).group(1)
PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
_SKIP_E2E = os.environ.get("FM_R151_SKIP_E2E") == "1"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def listening(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                         creationflags=0x08000000).stdout
    return any(len(l.split()) >= 5 and l.split()[3] == "LISTENING" and l.split()[1] == "127.0.0.1:%d" % port
               for l in out.splitlines())


def wait(fn, t):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return None


class Inst(object):
    """Изолированный экземпляр: своя временная папка, config, порт, замок; без трея и принтеров."""

    def __init__(self, label, modules=False):
        self.root = tempfile.mkdtemp(prefix="fm_r151_e2e_")
        assert not os.path.normcase(self.root).startswith(os.path.normcase(PROD)), "временная папка внутри рабочей!"
        self.port = free_port()
        self.token = "R151_E2E_" + secrets.token_hex(8)
        with open(os.path.join(self.root, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
            json.dump({"token": self.token, "sentinel": SENTINEL}, f)
        self.cfgp = os.path.join(self.root, "config.json")
        self.env = dict(os.environ)
        self.env.update({ISO.ENV_SENTINEL: self.token, ISO.ENV_INSTANCE: "e2e-r151-" + label,
                         ISO.ENV_DATA_DIR: self.root, ISO.ENV_CONFIG: self.cfgp,
                         ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_R151_" + secrets.token_hex(6),
                         ISO.ENV_PORT: str(self.port), ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1",
                         ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "1",
                         ISO.ENV_NO_MODULES: "0" if modules else "1", "PYTHONDONTWRITEBYTECODE": "1",
                         "FM_DATA_DIR_WAIT_S": "1"})
        for k in ("FM_LICENSE_TEST_KEYS", "FM_EFFECTIVE_DATA_DIR"):
            self.env.pop(k, None)
        self.proc = None

    def config(self, cfg):
        cfg = dict(cfg)
        cfg["server_port"] = self.port
        json.dump(cfg, open(self.cfgp, "w", encoding="utf-8"))

    def call(self, method, path, body=None, timeout=60):
        data = json.dumps(body).encode("utf-8") if body is not None else (b"" if method != "GET" else None)
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8") or "{}")
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"error": repr(e)}

    def start(self, limit=180):
        self.proc = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start",
                                      "--no-browser"], cwd=REPO, env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=(0x00000008 | 0x00000200))
        t0 = time.monotonic()
        ok = wait(lambda: self.call("GET", "/version")[1].get("version") == APP_VERSION
                  if listening(self.port) else None, limit)
        return bool(ok), time.monotonic() - t0

    def stop(self):
        with open(os.path.join(self.root, "stop.request"), "w", encoding="utf-8") as f:
            f.write(self.token)
        gone = wait(lambda: not listening(self.port), 60)
        if not gone and self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()       # только СВОЙ процесс; рабочую программу не трогаем
            gone = wait(lambda: not listening(self.port), 20)
        if self.proc is not None:
            try:
                self.proc.wait(timeout=20)
            except Exception:
                pass
        try:
            os.unlink(os.path.join(self.root, "stop.request"))
        except Exception:
            pass
        return bool(gone)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def farm_dbs(folder):
    try:
        return sorted(n for n in os.listdir(folder) if D.is_database_name(n))
    except OSError:
        return []


if _SKIP_E2E:
    SKIPPED.append("E, F — настоящий сервер и стенд (FM_R151_SKIP_E2E=1)")
else:
    section("E. настоящий сервер: своя папка данных отключена — красный режим, второй фермы нет")
    I1 = Inst("ddu")
    GONE = os.path.join(I1.root, "usb_stick", "Farm")
    I1.config({"data_dir": GONE})
    try:
        _ok, _dt = I1.start()
        check("E1. сервер поднялся и отвечает, хотя своей папки данных нет (ожидание ограничено)", _ok, round(_dt, 1))
        _st, _sto = I1.call("GET", "/api/storage")
        _u = (_sto or {}).get("data_dir_unavailable") or {}
        check("E2. «Хранение данных» сообщает: папка недоступна, причина «missing», путь — своя папка",
              _st == 200 and _u.get("reason") == "missing" and _u.get("configured") == GONE
              and _sto.get("data_dir_pending") == "", _sto)
        check("E3. КРИТИЧНО: вторая ферма не заведена — ни своей папки, ни баз в папке по умолчанию; "
              "программа работает из пустой временной папки",
              not os.path.exists(GONE) and farm_dbs(I1.root) == []
              and D.same_path(_sto.get("data_dir") or "", os.path.join(I1.root, D.UNAVAILABLE_DIR)), _sto)
        _st1, _j1 = I1.call("POST", "/api/projects2", {"name": "Проект в пустой ферме"})
        _st2, _j2 = I1.call("POST", "/api/farm-settings", {"stagger_sec": "33"})
        check("E4. изменения в пустой временной ферме отклоняются (503 data_dir_unavailable)",
              _st1 == 503 and _j1.get("reason") == "data_dir_unavailable" and _st2 == 503, (_st1, _j1, _st2))
        _st3, _j3 = I1.call("POST", "/api/storage/data", {"path": os.path.join(I1.root, "empty_dir")})
        check("E5. выбор папки открыт, но пустую папку вместо фермы не принимает",
              _st3 == 200 and _j3.get("reason") == "data_dir_unavailable_choose_farm", (_st3, _j3))
        check("E6. config.json не переписан (своя папка осталась своей)",
              json.load(open(I1.cfgp, encoding="utf-8")).get("data_dir") == GONE)
        #  Флешку вставили: в папке — настоящая ферма (её главная база с настройкой-меткой).
        _boot0 = I1.call("GET", "/version")[1].get("boot_id")
        os.makedirs(GONE)
        _c = sqlite3.connect(os.path.join(GONE, "farm_parts.db"))
        _c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT DEFAULT '')")
        _c.execute("INSERT INTO app_settings (key, value) VALUES ('farm_stagger_sec', '77')")
        _c.commit()
        _c.close()
        _t0 = time.monotonic()
        _back = wait(lambda: (lambda v: v if (v.get("boot_id") and v.get("boot_id") != _boot0) else None)(
            I1.call("GET", "/version", timeout=5)[1]), 150)
        _dt = time.monotonic() - _t0
        check("E7. КРИТИЧНО: папка вернулась — программа перезапустилась САМА (сторож data-dir-watch)",
              bool(_back), round(_dt, 1))
        if _back:
            _st, _sto2 = I1.call("GET", "/api/storage")
            _fs = I1.call("GET", "/api/farm-settings")[1]
            check("E8. после перезапуска открыта настоящая ферма: папка — своя, красного режима нет, "
                  "данные фермы на месте",
                  D.same_path(_sto2.get("data_dir") or "", GONE) and not _sto2.get("data_dir_unavailable")
                  and (_fs.get("settings") or {}).get("stagger_sec") == "77", (_sto2, _fs))
            _st4, _j4 = I1.call("POST", "/api/farm-settings", {"module_ui": {"camera_wall": {"ip_sources": [
                {"id": "c1", "name": "Камера", "url": "rtsp://camera.example/s"}]}}})
            _fs2 = I1.call("GET", "/api/farm-settings")[1]
            check("E9. настройки интерфейса модулей (камеры видеостены) сохраняются на сервере и читаются "
                  "обратно — в settings и на верхнем уровне ответа",
                  _st4 == 200 and _j4.get("ok") is True
                  and ((_fs2.get("module_ui") or {}).get("camera_wall") or {}).get("ip_sources", [{}])[0].get("id") == "c1"
                  and ((_fs2.get("settings") or {}).get("module_ui") or {}).get("camera_wall") == (_fs2.get("module_ui") or {}).get("camera_wall"),
                  (_st4, _j4, _fs2))
    finally:
        check("E10. изолированный экземпляр остановлен штатно", I1.stop())
        I1.cleanup()

    section("E'. настоящий сервер: модуль с зависшим register() не держит запуск программы")
    I2 = Inst("slowmod", modules=True)
    I2.config({})
    try:
        _ok, _dt = I2.start()
        check("E11. изолированный экземпляр с модулями поднялся", _ok, round(_dt, 1))
        _zp = os.path.join(TMP, "r151slow.zip")
        with zipfile.ZipFile(_zp, "w") as z:
            z.writestr("r151slow/module.json", json.dumps({"id": "r151slow", "ru": "Медленный", "en": "Slow",
                                                           "version": "0.0.1"}))
            z.writestr("r151slow/backend.py", "import time\n"
                                             "def _late(*a, **k):\n    return None\n"
                                             "def register(core):\n    time.sleep(45)\n"
                                             "    core.add_hook('pre_print_check', _late)\n")
        _st, _js = I2.call("POST", "/api/modules/install-path", {"path": _zp})
        check("E12. тестовый модуль с зависающим register() установлен (из временной папки, не из modules/)",
              _st == 200 and _js.get("status") == "ok", (_st, _js))
        check("E13. остановлен перед перезапуском", I2.stop())
        _t0 = time.monotonic()
        _ok, _dt = I2.start(limit=150)
        check("E14. КРИТИЧНО: программа поднялась, не дождавшись модуля: ответ через ~30 с, а не 45+",
              _ok and _dt < 44, round(_dt, 1))
        _mods = {m["id"]: m for m in I2.call("GET", "/api/modules")[1].get("modules", [])}
        check("E15. модуль показан как не подключённый по сроку (load_error, reason timeout)",
              (_mods.get("r151slow") or {}).get("state") == "load_error"
              and (_mods.get("r151slow") or {}).get("reason") == "timeout", _mods.get("r151slow"))
        wait(lambda: time.monotonic() - _t0 > 50, 60)
        _hooks = I2.call("GET", "/api/print-hooks")[1]
        check("E16. проснувшийся register() хук не подключил: проверок перед печатью — ноль",
              _hooks.get("pre_print_check") == 0, _hooks)
    finally:
        check("E17. изолированный экземпляр остановлен штатно", I2.stop())
        I2.cleanup()

    # ════════════════════════════════════════════════════════════════════════
    section("F. стенд интерфейса: красное окно «папка данных недоступна» на четырёх размерах")
    import _fm_ui_stage as st   # noqa: E402

    if not st.engine_ready():
        check("F0. браузерный движок стенда доступен (Edge + Node)", False, st.last_diag())
    else:
        st.set_api({"/api/storage": {"data_dir": "C:/Users/x/AppData/Local/3DIWELL/data-unavailable",
                                     "archive_dir": "D:/FarmArchive", "data_dir_is_default": False,
                                     "archive_dir_is_default": True, "data_dir_pending": "",
                                     "data_dir_unavailable": {"configured": "E:\\Farm", "configured_abs": "E:\\Farm",
                                                              "reason": "missing", "since": 1, "returned": False,
                                                              "move_from": ""}}})
        WAIT_WIN = r"""
function waitWin(cb){ var t0=Date.now(); (function w(){ var x=document.querySelector('.fm-ddu-win');
  if(!x && Date.now()-t0<15000) return setTimeout(w,150); cb(x); })(); }
function measure(w){
  var out = {found: !!w};
  if (!w) return out;
  var vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  var r = w.getBoundingClientRect();
  out.win = {l: r.left, t: r.top, r: r.right, b: r.bottom, vw: vw, vh: vh};
  out.title = (w.querySelector('.fm-ddu-title') || {}).textContent || '';
  out.text = (w.querySelector('.fm-ddu-text') || {}).textContent || '';
  out.buttons = [].slice.call(w.querySelectorAll('button')).map(function(b){
    var br = b.getBoundingClientRect();
    return {t: (b.textContent||'').trim(), over: b.scrollWidth > b.clientWidth + 1 || b.scrollHeight > b.clientHeight + 1,
            inside: br.left >= r.left - 0.5 && br.right <= r.right + 0.5 && br.bottom <= r.bottom + 0.5}; });
  out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
  var tt = w.querySelector('.fm-ddu-title'); out.titleOver = tt ? tt.scrollWidth > tt.clientWidth + 1 : true;
  return out;
}
"""
        JS_LOOK = WAIT_WIN + r"""
return new Promise(function(res){ waitWin(function(w){ dump(measure(w)); res(true); }); });
"""
        JS_CLICKS = WAIT_WIN + r"""
return new Promise(function(res){ waitWin(function(w){
  var out = measure(w);
  click(document.querySelector('.fm-ddu-back'));
  setTimeout(function(){
    out.stillOpen = !!document.querySelector('.fm-ddu-win');
    click(document.querySelector('.fm-ddu-retry'));
    setTimeout(function(){
      var rr = document.querySelector('.fm-ddu-restart');
      out.restartText = rr ? (rr.textContent || '') : '';
      out.stillOpen2 = !!document.querySelector('.fm-ddu-win');
      click(document.querySelector('.fm-ddu-new'));
      setTimeout(function(){
        var ask = document.querySelector('.fm-ask-back');
        out.confirm = ask ? (ask.textContent || '') : '';
        out.confirmTrash = !!document.querySelector('.fm-ask-ic.danger');
        var cancel = ask ? [].slice.call(ask.querySelectorAll('button')).filter(function(b){
          return /Отмена|Cancel/.test(b.textContent||''); })[0] : null;
        click(cancel);
        setTimeout(function(){
          out.afterCancel = !!document.querySelector('.fm-ddu-win') && !document.querySelector('.fm-ask-back');
          click(document.querySelector('.fm-ddu-pick'));
          setTimeout(function(){
            out.pickHidesWin = !document.querySelector('.fm-ddu-win');
            dump(out); res(true);
          }, 900);
        }, 500);
      }, 600);
    }, 900);
  }, 400);
}); });
"""
        SHOTS = os.environ.get("FM_R151_SHOTS", "")
        RU_BTNS = ["Начать новую пустую ферму в папке по умолчанию", "Папка теперь в другом месте…", "Повторить"]
        EN_BTNS = ["Start a new empty farm in the default folder", "The folder is elsewhere now…", "Retry"]
        for (w, h, lng) in ((1600, 1000, "ru"), (1280, 800, "ru"), (1024, 640, "ru"), (853, 533, "ru"),
                            (853, 533, "en")):
            r = st.run(JS_LOOK, window_size=(w, h), path="/?ls=farm_lang:" + lng,
                       shot_path=(os.path.join(SHOTS, "ddu_%dx%d_%s.png" % (w, h, lng)) if SHOTS else None))
            probs = st.page_problems(r) if r else ["нет результата: %s" % (st.last_diag(),)]
            r = r or {}
            win = r.get("win") or {}
            ru = lng == "ru"
            check("F1. %dx%d %s: красное окно показано, с путём своей папки, пояснением и тремя кнопками" % (w, h, lng),
                  r.get("found") and "E:\\Farm" in (r.get("title") or "")
                  and (r.get("title") or "").startswith("Папка данных фермы недоступна" if ru else "The farm data folder is unavailable")
                  and [b["t"] for b in r.get("buttons") or []] == (RU_BTNS if ru else EN_BTNS)
                  and ("Принтеры продолжают печатать" if ru else "Printers keep printing") in (r.get("text") or ""),
                  {k: r.get(k) for k in ("found", "title", "text", "buttons")})
            check("F2. %dx%d %s: окно целиком в экране, текст кнопок и заголовка не вылезает, горизонтальной "
                  "прокрутки нет" % (w, h, lng),
                  win and win["l"] >= 0 and win["t"] >= 0 and win["r"] <= win["vw"] + 0.5 and win["b"] <= win["vh"] + 0.5
                  and not any(b["over"] or not b["inside"] for b in r.get("buttons") or [])
                  and not r.get("hscroll") and not r.get("titleOver"), (win, r.get("buttons"), r.get("hscroll")))
            check("F3. %dx%d %s: консоль чистая" % (w, h, lng), not probs, probs)
        r = st.run(JS_CLICKS, window_size=(1280, 800), path="/?ls=farm_lang:ru") or {}
        probs = st.page_problems(r) if r else ["нет результата"]
        check("F4. щелчок мимо окно не закрывает (закрыть его нельзя — работать в пустой ферме нечего)",
              r.get("stillOpen") is True, r)
        check("F5. «Повторить» запускает перезапуск, и его ход виден прямо в красном окне",
              r.get("stillOpen2") is True and "перезапуск" in (r.get("restartText") or "").lower(), r.get("restartText"))
        check("F6. «Начать новую пустую ферму» сначала спрашивает и говорит, что данные на E:\\Farm не тронуты "
              "(без значка корзины — это не удаление); «Отмена» возвращает красное окно",
              "E:\\Farm" in (r.get("confirm") or "") and "нетронутыми" in (r.get("confirm") or "")
              and r.get("confirmTrash") is False and r.get("afterCancel") is True, r.get("confirm"))
        check("F7. «Папка теперь в другом месте…» открывает выбор папки, красное окно на это время уходит",
              r.get("pickHidesWin") is True, r)
        check("F8. консоль чистая после всех нажатий", not probs, probs)

        #  «Хранение данных»: настройки, которые живут только в этом окне браузера, — в файл.
        st.set_api(None)
        JS_STORAGE = r"""
return new Promise(function(res){ openStage('system', function(){
  setTimeout(function(){
    var line = document.querySelector('.fm-browser-settings'), out = {found: !!line};
    if (line) {
      line.scrollIntoView({block: 'center'});
      var box = (document.querySelector('.fm-set-scroll') || document.body).getBoundingClientRect();
      var lr = line.getBoundingClientRect();
      out.line = {l: lr.left, r: lr.right, boxL: box.left, boxR: box.right};
      out.buttons = [].slice.call(line.querySelectorAll('button')).map(function(b){
        var br = b.getBoundingClientRect();
        return {t: (b.textContent||'').trim(), over: b.scrollWidth > b.clientWidth + 1,
                inside: br.left >= lr.left - 0.5 && br.right <= lr.right + 0.5}; });
      out.hint = ((line.querySelector('.fm-set-hint') || {}).textContent || '');
      out.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      click(line.querySelector('.fm-bs-export'));
      setTimeout(function(){
        var msg = line.parentNode.querySelector('.fm-pnl-info .fm-pnl-b');
        out.msg = msg ? (msg.textContent || '') : '';
        dump(out); res(true);
      }, 500);
    } else { dump(out); res(true); }
  }, 600);
}, 'ru'); });
"""
        for (w, h) in ((1600, 1000), (1280, 800), (1024, 640), (853, 533)):
            r = st.run(JS_STORAGE, window_size=(w, h),
                       path="/?ls=3diwell.camera_wall.ip_sources.v1:camera-list",
                       shot_path=(os.path.join(SHOTS, "storage_%dx%d.png" % (w, h)) if SHOTS else None))
            probs = st.page_problems(r) if r else ["нет результата: %s" % (st.last_diag(),)]
            r = r or {}
            ln = r.get("line") or {}
            check("F9. %dx%d: в «Хранении данных» строка «Настройки этого окна» с кнопками «Сохранить в файл» и "
                  "«Загрузить из файла»; ничего не вылезает за края" % (w, h),
                  r.get("found") and [b["t"] for b in r.get("buttons") or []] == ["Сохранить в файл", "Загрузить из файла"]
                  and not any(b["over"] or not b["inside"] for b in r.get("buttons") or [])
                  and ln and ln["l"] >= ln["boxL"] - 0.5 and ln["r"] <= ln["boxR"] + 0.5 and not r.get("hscroll")
                  and "видеостены" in (r.get("hint") or ""), r)
            check("F10. %dx%d: «Сохранить в файл» сохраняет настройки модулей этого окна (камеры видеостены), "
                  "консоль чистая" % (w, h),
                  (r.get("msg") or "").startswith("Сохранено настроек: 1") and not probs, (r.get("msg"), probs))
        st.stop()

# ════════════════════════════════════════════════════════════════════════════
section("G. текст уведомления в интерфейсе: «модуль не ответил» — предупреждением, не «на исходе»")
_APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
_g0 = _APPJS.find("    const filShort = ")
_g1 = _APPJS.find("\n", _APPJS.find("    const pushFilNote = "))
_NODE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
if _g0 < 0 or _g1 < 0 or not os.path.isfile(_NODE):
    check("G0. функции уведомлений найдены в web/app.js и Node доступен", False, (_g0, _g1, _NODE))
else:
    _js = ("const lang = {value: 'ru'}; const tr = (s) => s; const toasts = [];\n"
           "const installedModules = {value: [{id: 'inventory', ru: 'Складской учёт', en: 'Inventory'}]};\n"
           "const pushToast = (m, t) => toasts.push([m, t]);\n" + _APPJS[_g0:_g1] + "\n"
           "const out = {};\n"
           "pushFilNote({kind: 'check_unavailable', module_id: 'inventory', reason: 'timeout', printer_name: 'X1C-1'});\n"
           "pushFilNote({kind: 'check_unavailable', module_id: 'inventory', reason: 'license', printer_name: 'X1C-1'});\n"
           "pushFilNote({kind: 'tight', printer_name: 'X1C-1', tight: [{material: 'PLA', color_name: 'Белый'}]});\n"
           "lang.value = 'en';\n"
           "pushFilNote({kind: 'check_unavailable', module_id: 'inventory', reason: 'error', printer_name: 'X1C-1'});\n"
           #  16.10.2026 (ревизия): настоящий сервер шлёт и module_name (по-русски), и module_name_en
           "pushFilNote({kind: 'check_unavailable', module_id: 'inventory', module_name: 'Складской учёт', "
           "module_name_en: 'Inventory', reason: 'timeout', printer_name: 'X1C-1'});\n"
           "installedModules.value = [];\n"
           "pushFilNote({kind: 'check_unavailable', module_id: 'inventory', module_name: 'Складской учёт', "
           "module_name_en: 'Inventory', reason: 'timeout', printer_name: 'X1C-1'});\n"
           "lang.value = 'ru';\n"
           "pushFilNote({kind: 'check_unavailable', module_id: 'inventory', module_name: 'Складской учёт', "
           "module_name_en: 'Inventory', reason: 'timeout', printer_name: 'X1C-1'});\n"
           "console.log(JSON.stringify(toasts));\n")
    _jp = os.path.join(TMP, "notes.js")
    io.open(_jp, "w", encoding="utf-8").write(_js)
    _p = subprocess.run([_NODE, _jp], capture_output=True, timeout=60)
    try:
        _toasts = json.loads(_p.stdout.decode("utf-8").strip().splitlines()[-1])
    except Exception:
        _toasts = None
    check("G1. «модуль не ответил вовремя» — предупреждение с именем принтера и модуля: печать запущена без проверки",
          _toasts and _toasts[0] == ["X1C-1: модуль «Складской учёт» не ответил вовремя — печать запущена без проверки остатка", "warn"],
          (_toasts, _p.stderr.decode("utf-8", "replace")[-400:]))
    check("G2. лицензия и ошибка модуля названы своими словами (ru/en); «на исходе» — прежняя справка",
          _toasts and _toasts[1][0].endswith("работает без действующей лицензии — печать запущена без проверки остатка")
          and _toasts[2] == ["X1C-1: PLA Белый на исходе — катушку скоро менять", "info"]
          and _toasts[3] == ['X1C-1: module "Inventory" could not run its check — the print started without the stock check', "warn"],
          _toasts)
    check("G3. в английском интерфейсе имя модуля английское и тогда, когда сервер прислал русское "
          "module_name (из списка модулей или из module_name_en); в русском — русское",
          _toasts and len(_toasts) == 7
          and _toasts[4][0] == 'X1C-1: module "Inventory" did not answer in time — the print started without the stock check'
          and _toasts[5][0] == _toasts[4][0]
          and _toasts[6][0] == "X1C-1: модуль «Складской учёт» не ответил вовремя — печать запущена без проверки остатка",
          _toasts)

check("Z. все функции и константы R-151, которые исполняет набор, найдены в server.py", not MISSING, sorted(MISSING))
shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
if SKIPPED:
    print("BLOCKED — пропущено: %s" % "; ".join(SKIPPED))
print("ИТОГО: PASS=%d FAIL=%d%s" % (PASS[0], len(FAIL), (" SKIPPED=%d" % len(SKIPPED)) if SKIPPED else ""))
for f in FAIL:
    print("  FAIL: %s" % f)
sys.exit(1 if (FAIL or SKIPPED) else 0)
