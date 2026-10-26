# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.850 — третий ответ в окне «Материал закончился»: «Печатать всё равно».

ЗАЧЕМ. 18.08.2026 владелец запускал пачку принтеров с задержкой. На одном материал кончился,
и окно предложило два ответа: оприходовать такую же катушку или пропустить принтер. Оприходовать
было нечего — материал кончился в слоте AMS, где учёт замену не предлагает вовсе, — и цепочка
запусков рвалась на ровном месте. Третий ответ запускает печать и при этом НЕ оставляет учёт
сломанным молча: остаток привязанной катушки списывается в ноль со строкой в журнале склада.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ — вся цепочка, а не одна кнопка:
  · модуль склада отдаёт готовые шаги списания (override_steps) в КАЖДОМ блокирующем ответе,
    включая слот AMS, где прежде не было ни одного выполнимого действия;
  · шаги ведут на СУЩЕСТВУЮЩИЙ маршрут модуля и, будучи выполненными, действительно обнуляют
    остаток и оставляют строку в журнале (проверяется по БД, а не по тексту ответа);
  · ядро пропускает элемент с принятым решением мимо складской проверки — иначе очередь
    переспросила бы склад через минуту и упёрлась в тот же отказ;
  · решение доезжает до самого старта (элемент очереди несёт метку, quick-поток её передаёт);
  · ядро по-прежнему НЕ знает адресов склада: шаги берутся из ответа, а не зашиты в интерфейс;
  · кнопка требует подтверждения — первый клик только взводит, печать уходит со второго.

НЕ ВАКУУМ. Отдельно проверяется, что защита не снята целиком: без метки решения проверка склада
как вызывалась, так и вызывается, а при достаточном остатке блокировки и шагов нет вовсе.

БЕЗОПАСНОСТЬ. Временная БД в системном temp; настоящая папка данных фермы не открывается.
server.py не импортируется — он разбирается как текст (AST). Принтеров нет, команд никуда
не уходит, ничего не печатается.

Запуск:  python tools/test_print_anyway_option.py      (0 = сценарий работает)
"""
import ast
import importlib.util
import io
import logging
import os
import re
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
SERVER = os.path.join(REPO, "server.py")
APPJS = os.path.join(REPO, "web", "app.js")
INDEX = os.path.join(REPO, "web", "index.html")
SENTINEL = "PRINT_ANYWAY_OPTION_SENTINEL_2_850"

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
#  ЧАСТЬ 1. Модуль склада: шаги «печатать всё равно» и их реальное действие на БД
# ══════════════════════════════════════════════════════════════════════════════

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


def reports_external(material):
    """Свежая телеметрия принтера БЕЗ AMS: во внешней подаче лежит указанный материал."""
    return {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [{"index": None, "external": True, "present": True,
                           "reported_material": material, "reported_color": ""}]}


def reports_ams(material):
    """Свежая телеметрия принтера С AMS: материал лежит в слоте, внешней подачи нет."""
    return {"telemetry_available": True, "telemetry_fresh": True,
            "positions": [{"index": 0, "external": False, "present": True,
                           "reported_material": material, "reported_color": ""}]}


_OPENED = []          # соединения закрываем сами: Windows не отдаёт файл БД открытому процессу


def load_backend(dbpath, core):
    spec = importlib.util.spec_from_file_location("inv_backend_anyway", BACKEND)
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


def run_steps(m, steps):
    """Выполняет шаги ответа ТАК ЖЕ, как их выполнит интерфейс: адрес разбирается, вызывается
    соответствующая функция модуля. Так проверяется не текст шага, а его последствие в БД."""
    done = 0
    for st in steps or []:
        mm = re.match(r"^/api/mod/([^/]+)/spool/([^/]+)/adjust$", str(st.get("url") or ""))
        if not mm:
            continue
        body = st.get("body") or {}
        m.inv_adjust_spool(mm.group(2), float(body.get("delta_g") or 0), str(body.get("reason") or ""))
        done += 1
    return done


def spool_remaining(m, sid):
    with m.lock_inv:
        r = m.conn_inv.execute("SELECT weight_remaining_g FROM inv_spools WHERE id=?", (sid,)).fetchone()
    return float(r["weight_remaining_g"]) if r else None


def ledger_reasons(m, sid):
    with m.lock_inv:
        rows = m.conn_inv.execute("SELECT reason FROM inv_ledger WHERE ref_type='spool' AND ref_id=?", (sid,)).fetchall()
    return [str(r["reason"] or "") for r in rows]


PID = "node_h2d"

with tempfile.TemporaryDirectory(prefix="fm_print_anyway_", ignore_cleanup_errors=True) as td:
    db = os.path.join(td, "farm_inventory.db")

    print("--- 1. Слот AMS: раньше решать было нечем, теперь есть выполнимое действие ---")
    core = FakeCore(); core.reported[PID] = reports_ams("PETG")
    m = load_backend(db + ".ams", core)
    fid = make_filament(m)
    sid = make_spool(m, fid, 40.0, status="loaded", pid=PID, slot=0)
    r = m._inv_hook_pre_print(PID, [600.0], 0, "plate.3mf")
    check("1. слот AMS: отказ по материалу есть (молча не гасим)",
          isinstance(r, dict) and r.get("status") == "low_filament", r)
    sh = ((r or {}).get("shortfall") or [{}])[0]
    check("2. слот AMS помечен как НЕ внешний — замену катушки учёт тут не предлагает",
          sh.get("external") is False, sh)
    check("3. НЕ ВАКУУМ: оприходовать нечего — шагов «поставил новую катушку» здесь по-прежнему нет",
          not (sh.get("resolve_steps") or []), sh.get("resolve_steps"))
    steps = sh.get("override_steps") or []
    check("4. зато есть шаги «печатать всё равно» — ровно один", len(steps) == 1, steps)
    st = steps[0] if steps else {}
    check("5. шаг ведёт на СУЩЕСТВУЮЩИЙ маршрут модуля (spool/{id}/adjust), новых точек входа нет",
          bool(re.match(r"^/api/mod/inventory/spool/[^/]+/adjust$", str(st.get("url") or ""))), st)
    check("6. шаг списывает остаток В НОЛЬ, а не наугад: delta = минус остаток",
          abs(float((st.get("body") or {}).get("delta_g") or 0) + 40.0) < 0.05, st.get("body"))
    check("7. причина списания названа словами — она попадёт в журнал склада",
          len(str((st.get("body") or {}).get("reason") or "")) > 10, st.get("body"))
    check("8. остаток ДО выполнения шага не тронут (ответ хука ничего не переписывает вслепую)",
          spool_remaining(m, sid) == 40.0, spool_remaining(m, sid))
    check("9. шаг выполнен интерфейсом", run_steps(m, steps) == 1)
    check("10. ПОСЛЕДСТВИЕ В БД: остаток стал нулём", spool_remaining(m, sid) == 0.0, spool_remaining(m, sid))
    check("11. ПОСЛЕДСТВИЕ В БД: в журнале склада осталась строка о неподтверждённом расходе",
          any("не подтверждён" in x for x in ledger_reasons(m, sid)), ledger_reasons(m, sid))

    print("--- 2. Внешняя подача без склада: третий ответ добавлен, прежние не сломаны ---")
    core = FakeCore(); core.reported[PID] = reports_external("PETG")
    m = load_backend(db + ".ext", core)
    fid = make_filament(m)
    sid = make_spool(m, fid, 5.0, status="loaded", pid=PID, slot=-1)
    r = m._inv_hook_pre_print(PID, [500.0], -1, "plate.3mf")
    sh = ((r or {}).get("shortfall") or [{}])[0]
    check("12. блокирующий ответ на месте", isinstance(r, dict) and r.get("status") == "low_filament", r)
    check("13. прежний ответ «поставил новую катушку» СОХРАНЁН (два шага модуля)",
          len(sh.get("resolve_steps") or []) == 2, sh.get("resolve_steps"))
    check("14. и рядом появился ответ «печатать всё равно»", len(sh.get("override_steps") or []) == 1, sh.get("override_steps"))
    check("15. оба набора шагов ведут на маршруты ОДНОГО модуля склада",
          all(str(x.get("url") or "").startswith("/api/mod/inventory/")
              for x in list(sh.get("resolve_steps") or []) + list(sh.get("override_steps") or [])), sh)

    print("--- 3. Списывать нечего и молчать не о чем: границы ---")
    core = FakeCore(); core.reported[PID] = reports_ams("PETG")
    m = load_backend(db + ".zero", core)
    fid = make_filament(m)
    make_spool(m, fid, 0.0, status="loaded", pid=PID, slot=0)
    r = m._inv_hook_pre_print(PID, [600.0], 0, "plate.3mf")
    sh = ((r or {}).get("shortfall") or [{}])[0]
    check("16. остаток уже нулевой — блокировка есть, но списывать нечего (шагов нет)",
          isinstance(r, dict) and r.get("status") == "low_filament" and not (sh.get("override_steps") or []), sh)

    core = FakeCore(); core.reported[PID] = reports_ams("PETG")
    m = load_backend(db + ".enough", core)
    fid = make_filament(m)
    make_spool(m, fid, 900.0, status="loaded", pid=PID, slot=0)
    check("17. НЕ ВАКУУМ: материала хватает — ни блокировки, ни шагов не появляется",
          m._inv_hook_pre_print(PID, [120.0], 0, "plate.3mf") is None)

for c in _OPENED:
    try:
        c.close()
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
#  ЧАСТЬ 2. Ядро: решение владельца обходит проверку и доезжает до старта
#  server.py разбирается как AST — подстрочный поиск нашёл бы собственные комментарии.
# ══════════════════════════════════════════════════════════════════════════════

print("--- 4. Ядро: принятое решение не переспрашивают ---")
_srv_tree = ast.parse(read(SERVER))
_fn = {n.name: n for n in ast.walk(_srv_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def const_strings(node):
    return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def calls_named(node, name):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id == name:
                out.append(n)
            elif isinstance(f, ast.Attribute) and f.attr == name:
                out.append(n)
    return out


_pre = _fn.get("_enqueue_preflight")
check("18. функция предстартовой проверки очереди на месте", _pre is not None)

if _pre is not None:
    _hook_calls = calls_named(_pre, "_run_pre_print_hooks")
    check("19. НЕ ВАКУУМ: склад по-прежнему спрашивают — вызов проверки в функции остался",
          len(_hook_calls) == 1, len(_hook_calls))
    # ранний выход по метке решения: If, в тесте которого есть строка 'skip_filament',
    # в теле — continue, и расположен он ДО вызова складской проверки
    _guards = [n for n in ast.walk(_pre) if isinstance(n, ast.If)
               and "skip_filament" in const_strings(n.test)
               and any(isinstance(b, ast.Continue) for b in ast.walk(n))]
    check("20. есть ранний выход по метке принятого решения", len(_guards) == 1, len(_guards))
    if _guards and _hook_calls:
        check("21. и он стоит ДО обращения к складу — иначе отказ пришёл бы снова",
              _guards[0].lineno < _hook_calls[0].lineno, (_guards[0].lineno, _hook_calls[0].lineno))
        _appends = [n for n in ast.walk(_guards[0]) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == "append"
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "allowed"]
        check("22. элемент при этом попадает в РАЗРЕШЁННЫЕ, а не теряется по дороге", len(_appends) == 1, len(_appends))

_enq = _fn.get("api_print_queue_enqueue")
check("23. постановка в очередь на месте", _enq is not None)
if _enq is not None:
    _keys = [n for n in ast.walk(_enq) if isinstance(n, ast.Dict)
             for k in n.keys if isinstance(k, ast.Constant) and k.value == "skip_filament"]
    check("24. элемент очереди НЕСЁТ метку решения (переживает очередь и восстановление после рестарта)",
          len(_keys) == 1, len(_keys))

_start = _fn.get("_start_queued_print")
check("25. запуск отложенного элемента на месте", _start is not None)
if _start is not None:
    _pp = calls_named(_start, "part_print")
    check("26. quick-поток очереди получает элемент", len(_pp) == 1, len(_pp))
    if _pp:
        _arg = _pp[0].args[0] if _pp[0].args else None
        _has = isinstance(_arg, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == "skip_filament" for k in _arg.keys)
        check("27. и метка решения передаётся ему — иначе склад переспросил бы при старте", _has, ast.dump(_arg)[:200] if _arg else None)

# ══════════════════════════════════════════════════════════════════════════════
#  ЧАСТЬ 3. Интерфейс: кнопка, подтверждение и граница модульности
# ══════════════════════════════════════════════════════════════════════════════

print("--- 5. Интерфейс: кнопка есть, требует подтверждения, адресов склада не знает ---")
_js = read(APPJS)
_html = read(INDEX)

check("28. кнопка «Печатать всё равно» есть в окне решения и по-русски, и по-английски",
      "Печатать всё равно" in _html and "Print anyway" in _html)
check("29. кнопка вызывает свой обработчик", _html.count("filForceStart(r)") == 1, _html.count("filForceStart(r)"))
check("30. прежние два ответа никуда не делись",
      _html.count("filReceiveAndStart(r)") == 1 and _html.count("filSkipPrinter(r)") == 1)

_i = _js.find("const filForceStart = async (row) => {")
check("31. обработчик объявлен в интерфейсе ровно один раз",
      _i >= 0 and _js.count("const filForceStart") == 1, _js.count("const filForceStart"))
_body = _js[_i:_js.find("\n    };", _i)] if _i >= 0 else ""
check("32. первый клик только ВЗВОДИТ кнопку, печать уходит со второго (защита от случайного нажатия)",
      "filDecision.value.confirm !== row.printer_id" in _body and "return; }" in _body, _body[:200])
check("33. шаги списания берутся ИЗ ОТВЕТА склада, а не зашиты в интерфейс",
      "row.override_steps" in _body, _body[:200])
check("34. запуск ставится в ту же очередь с меткой принятого решения",
      "/api/print-queue/enqueue" in _body and "skip_filament: true" in _body, _body[:200])
_ord_stock = _body.find("override_steps")
_ord_send = _body.find("/api/print-queue/enqueue")
check("35. ПОРЯДОК: сначала правится учёт, потом уходит печать",
      _ord_stock >= 0 and _ord_send > _ord_stock, (_ord_stock, _ord_send))
check("36. неудача склада НЕ отменяет печать — владелец уже решил печатать",
      "stockOk" in _body and _body.find("stockOk = false") < _ord_send, _body[:200])
check("37. ГРАНИЦА МОДУЛЬНОСТИ: ядро интерфейса по-прежнему не знает адресов склада",
      "/api/mod/inventory" not in _js)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
