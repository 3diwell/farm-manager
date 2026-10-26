# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.10.2026 (R-020) — неполный адрес принтера не принимается и не уходит в сеть.

ЧТО СЛУЧИЛОСЬ. У двух принтеров Klipper в карточках записано «198.68.104» и «198.68.109». Windows
такую строку не отвергает, а достраивает: «198.68.104» -> 198.68.0.104, ПУБЛИЧНЫЙ адрес интернета.
Опрос принтера раз в пару секунд уходил на чужой узел, а у Bambu туда же ушёл бы код доступа.

ЧТО ДОКАЗЫВАЕТСЯ (исполнением, а не по тексту кода):
  1. Проверка адреса (app/printer_address.py) на образцах: неполный, с ведущими нулями, имя узла,
     IPv6, адрес из интернета (только предупреждение).
  2. Сохранение принтеров (настоящий s_printers из server.py на базе в памяти): новый или
     изменённый неполный адрес -> 400 bad_address и ни одной записи; старая битая запись, которая
     не меняется, сохранению остальных не мешает.
  3. Проба адреса (verify_printer): по неполному адресу не делается ни одной попытки соединения.
     «Обновить адрес» из поиска (api_discovery_rebind) неверный адрес не записывает, а верный —
     записывает и сразу перезапускает связь.
  4. Перезапуск связи (restart_workers): для неполного адреса воркер не запускается, на карточке
     причина «Неполный адрес …», в журнале одна строка; исправили адрес — воркер пошёл.
  5. Список принтеров для интерфейса: поле address_problem.
  6. Интерфейс на стенде (настоящие index.html + app.js в браузере), четыре размера окна, оба
     интерфейса: красная метка на карточке во всех видах, ничего не вылезает за край; нажатие на
     метку открывает форму с ошибкой под полем адреса и недоступной кнопкой «Сохранить»;
     дописанный адрес ошибку снимает. Консоль чистая.

Сервер не запускается, сети нет (кроме стенда на 127.0.0.1), рабочая папка данных не трогается.
Запуск: python tools/test_printer_address.py   (0 = пройдено)
Снимки стенда для осмотра: FM_ADDR_SHOTS=<папка> python tools/test_printer_address.py
"""
import ast
import io
import json
import os
import socket
import sqlite3
import sys
import threading

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "PRINTER_ADDRESS_SENTINEL_R020"
fails = []


def check(name, ok, extra=""):
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:600] if (not ok and extra != "") else ""))
    if not ok:
        fails.append(name)


SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)


def grab(name):
    for n in TREE.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(SRC, n)
    return None


try:
    from app import printer_address as pa
except Exception as _e:          # старая копия программы: модуля ещё нет — проверки краснеют
    pa = None
    print("  (app/printer_address.py недоступен: %s)" % _e)

# ════════════════════════════════════════════════════════════════════════════════════════════
print("--- 1. Проверка адреса ---")
check("0. модуль проверки адреса есть", pa is not None)


def verdict(s):
    try:
        return pa.check_printer_address(s)[0]
    except Exception as e:
        return "ERR:%s" % e


#  Замер, из-за которого пункт и заведён: Windows (и inet_aton вообще) достраивает неполный адрес.
_completed = None
try:
    _completed = socket.inet_ntoa(socket.inet_aton("198.68.104"))
except Exception:
    pass
check("1. исходная беда воспроизводится: «198.68.104» система понимает как 198.68.0.104",
      _completed == "198.68.0.104", _completed)
check("2. «198.68.104» и «198.68.109» — неполные адреса",
      verdict("198.68.104") == "short" and verdict("198.68.109") == "short",
      (verdict("198.68.104"), verdict("198.68.109")))
check("3. полный адрес локальной сети принимается", verdict("192.168.1.104") == "ok", verdict("192.168.1.104"))
check("4. ведущие нули отвергаются (inet_aton читает «010» как восьмеричное 8)",
      verdict("192.168.001.104") == "bad" and verdict("192.168.1.010") == "bad",
      (verdict("192.168.001.104"), verdict("192.168.1.010")))
check("5. имя принтера в сети допускается", verdict("k2plus.local") == "ok" and verdict("voron_2") == "ok",
      (verdict("k2plus.local"), verdict("voron_2")))
check("6. IPv6 допускается", verdict("fe80::1") == "ok", verdict("fe80::1"))
check("7. адрес из интернета — только предупреждение, не отказ (фермы бывают за VPN)",
      verdict("8.8.8.8") == "global" and pa is not None and not pa.is_blocking("global"), verdict("8.8.8.8"))
check("8. адрес VPN (100.64.x, Tailscale) интернетом не считается", verdict("100.64.1.2") == "ok", verdict("100.64.1.2"))
check("9. число без точек — неполный адрес (inet_aton понял бы его как 32-битное число)",
      verdict("1921681104") == "short", verdict("1921681104"))
check("10. число больше 255 и пять частей — неверный адрес",
      verdict("256.1.1.1") == "bad" and verdict("1.2.3.4.5") == "bad", (verdict("256.1.1.1"), verdict("1.2.3.4.5")))
check("11. адрес с портом или ссылкой — неверный (связь по такому не идёт)",
      verdict("192.168.1.5:7125") == "bad" and verdict("http://192.168.1.5") == "bad",
      (verdict("192.168.1.5:7125"), verdict("http://192.168.1.5")))
check("12. пробелы по краям не мешают, внутри — мешают",
      pa is not None and pa.check_printer_address("  10.0.0.5 ") == ("ok", "10.0.0.5") and verdict("10.0.0 .5") == "bad",
      (pa.check_printer_address("  10.0.0.5 ") if pa else None, verdict("10.0.0 .5")))
check("13. пустой адрес — отдельный вердикт, не отказ (у виртуального принтера адреса нет)",
      verdict("") == "empty" and pa is not None and not pa.is_blocking("empty"))
if pa is not None:
    check("14. для карточки: неполный -> 'short', исправный и интернет -> нет пометки, виртуальный -> нет",
          pa.address_problem("198.68.104", "klipper") == "short" and pa.address_problem("10.0.0.5", "bambu") is None
          and pa.address_problem("8.8.8.8", "bambu") is None and pa.address_problem("", "demo") is None)
    check("15. текст причины — тот, что увидит владелец",
          pa.describe("short", "198.68.104") == "Неполный адрес 198.68.104: нужно 4 числа через точку",
          pa.describe("short", "198.68.104"))

# ════════════════════════════════════════════════════════════════════════════════════════════
print("--- 2. Сохранение принтеров: настоящий s_printers на базе в памяти ---")
DDL = ("CREATE TABLE printers (id TEXT PRIMARY KEY, name TEXT, type TEXT DEFAULT 'bambu', "
       "ip TEXT, port INTEGER, token TEXT, last_parts TEXT DEFAULT '{}', order_idx INTEGER DEFAULT 0, "
       "gen TEXT DEFAULT 'auto', serial TEXT DEFAULT '', model TEXT DEFAULT '')")


class P(object):
    """Заменитель PrUpdate: ровно те атрибуты, что читает обработчик."""

    def __init__(self, pid, ip, type="klipper", name="P", port=None, token=None, serial=None):
        self.id = pid; self.name = name; self.type = type; self.ip = ip
        self.port = port; self.token = token; self.gen = "auto"; self.serial = serial; self.model = ""


class _Log(object):
    def __init__(self):
        self.lines = []

    def __getattr__(self, lvl):
        def rec(*a, **k):
            try:
                self.lines.append((lvl, str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0])))
            except Exception:
                self.lines.append((lvl, str(a)))
        return rec


def save_env(rows):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(DDL)
    for i, (pid, typ, ip) in enumerate(rows):
        conn.execute("INSERT INTO printers (id, name, type, ip, token, order_idx) VALUES (?,?,?,?,?,?)",
                     (pid, pid, typ, ip, "FIXTURE_TOKEN", i))
    conn.commit()
    calls = {"restart": 0}
    ns = {"threading": threading, "os": os, "log": _Log(), "_exc_brief": (lambda: "x"),
          "conn_pr": conn, "lock_pr": threading.Lock(),
          "contextmanager": __import__("contextlib").contextmanager,
          "_req_role": (lambda req: None), "_has_perm": (lambda r, p: True),
          "restart_workers": (lambda: calls.__setitem__("restart", calls["restart"] + 1)),
          "_apply_project_print_fuses": (lambda: None),
          "JSONResponse": (lambda d, status_code=200: {"_json": d, "_code": status_code}),
          "List": list, "PrUpdate": P, "Request": object, "_paddr": pa}
    exec(grab("_rollback_sqlite_on_error"), ns)
    ns["_rollback_sqlite_on_error"] = ns["contextmanager"](ns["_rollback_sqlite_on_error"])
    exec(grab("_merge_printer_secret"), ns)
    exec(grab("s_printers"), ns)
    return ns, conn, calls


def ips(conn):
    return {r["id"]: r["ip"] for r in conn.execute("SELECT id, ip FROM printers")}


def code_of(r):
    return r.get("_code") if isinstance(r, dict) else None


#  2а. Новый принтер с неполным адресом.
ns, conn, calls = save_env([("k_old", "klipper", "10.0.0.5")])
try:
    r = ns["s_printers"]([P("k_old", "10.0.0.5"), P("k_new", "198.68.104")], None)
except Exception as e:
    r = {"exc": repr(e)}
check("16. НОВЫЙ принтер с адресом «198.68.104» не сохраняется: ответ 400 bad_address",
      code_of(r) == 400 and (r.get("_json") or {}).get("error") == "bad_address"
      and (r.get("_json") or {}).get("printer_id") == "k_new", r)
check("17. при отказе в базе ничего не изменилось и связь не перезапускалась",
      ips(conn) == {"k_old": "10.0.0.5"} and calls["restart"] == 0, (ips(conn), calls))

#  2б. Старая битая запись не мешает сохранить остальные (форма шлёт весь список).
ns, conn, calls = save_env([("node_gftic", "klipper", "198.68.104"), ("b1", "bambu", "10.0.0.7")])
try:
    r = ns["s_printers"]([P("node_gftic", "198.68.104"), P("b1", "10.0.0.7", type="bambu"),
                          P("k2", "10.0.0.8")], None)
except Exception as e:
    r = {"exc": repr(e)}
check("18. уже записанный неполный адрес, который не меняется, сохранению других не мешает",
      isinstance(r, dict) and r.get("status") == "success"
      and ips(conn) == {"node_gftic": "198.68.104", "b1": "10.0.0.7", "k2": "10.0.0.8"}, (r, ips(conn)))

#  2в. Смена адреса на неполный.
ns, conn, calls = save_env([("b1", "bambu", "10.0.0.7")])
try:
    r = ns["s_printers"]([P("b1", "198.68.109", type="bambu")], None)
except Exception as e:
    r = {"exc": repr(e)}
check("19. ИЗМЕНЁННЫЙ адрес «198.68.109» не принимается, прежний адрес остаётся",
      code_of(r) == 400 and ips(conn) == {"b1": "10.0.0.7"}, (r, ips(conn)))

#  2г. Исправление битой записи и виртуальный принтер без адреса.
ns, conn, calls = save_env([("node_l9bkh", "klipper", "198.68.109")])
try:
    r = ns["s_printers"]([P("node_l9bkh", "198.68.1.109"), P("demo1", "", type="demo")], None)
except Exception as e:
    r = {"exc": repr(e)}
check("20. исправленный адрес принимается; виртуальный принтер без адреса — тоже",
      isinstance(r, dict) and r.get("status") == "success"
      and ips(conn) == {"node_l9bkh": "198.68.1.109", "demo1": ""} and calls["restart"] == 1, (r, ips(conn)))

ns, conn, calls = save_env([])
try:
    r = ns["s_printers"]([P("h1", "k2plus.local"), P("h2", "8.8.8.8", type="bambu")], None)
except Exception as e:
    r = {"exc": repr(e)}
check("21. имя узла и адрес из интернета (VPN) сохраняются",
      isinstance(r, dict) and r.get("status") == "success" and len(ips(conn)) == 2, (r, ips(conn)))

# ════════════════════════════════════════════════════════════════════════════════════════════
print("--- 3. Проба адреса: по неполному адресу ни одной попытки соединения ---")
probes = []


def _probe(ip, port, timeout=1.0):
    probes.append((ip, port))
    return {"reachable": port == 7125}


class V(object):
    def __init__(self, ip, type="klipper", port=None):
        self.ip = ip; self.type = type; self.port = port


vns = {"_tcp_probe": _probe, "_paddr": pa}
exec(grab("verify_printer"), vns)
try:
    rv = vns["verify_printer"](V("198.68.104"))
except Exception as e:
    rv = {"exc": repr(e)}
check("22. неполный адрес: проба не стучится никуда и честно говорит почему",
      probes == [] and rv.get("bad_address") is True and rv.get("address_problem") == "short"
      and rv.get("reachable") is False, (probes, rv))
probes[:] = []
rv = vns["verify_printer"](V("192.168.1.104"))
check("23. полный адрес пробуется как раньше (порт выбранного типа)",
      probes[:1] == [("192.168.1.104", 7125)] and rv.get("match") is True and "address_warning" not in rv, (probes, rv))
probes[:] = []
rv = vns["verify_printer"](V("8.8.8.8"))
check("24. адрес из интернета пробуется, но с предупреждением",
      bool(probes) and rv.get("address_warning") == "global", (probes, rv))

# ════════════════════════════════════════════════════════════════════════════════════════════
print("--- 3б. «Обновить адрес» из поиска: адрес проверяется так же, связь перезапускается ---")
#  Разбор объявления пропускает «010.0.0.5» (inet_aton понимает его как 8.0.0.5) — такой адрес
#  «Обновить адрес» записывать не должен, как не записало бы его и сохранение принтеров.
import typing  # noqa: E402
from app import printer_discovery as _pdisc_mod  # noqa: E402

rconn = sqlite3.connect(":memory:", check_same_thread=False)
rconn.row_factory = sqlite3.Row
rconn.execute(DDL)
rconn.execute("INSERT INTO printers (id, name, type, ip, port, token) VALUES ('b1','b1','bambu','192.168.1.9',8883,'FIXTURE_TOKEN')")
rconn.commit()
_rdev = {}
_rcalls = {"restart": 0, "learn": []}
rns = {"_discovery_snapshot": (lambda: {"devices": [dict(_rdev)]}), "lock_pr": threading.Lock(), "conn_pr": rconn,
       "log": _Log(), "_exc_brief": (lambda: "x"), "_pdisc": _pdisc_mod, "_paddr": pa,
       "_discovery_learn_identity": (lambda *a: _rcalls["learn"].append(a) or True),
       "restart_workers": (lambda: _rcalls.__setitem__("restart", _rcalls["restart"] + 1)),
       "Dict": typing.Dict, "Any": typing.Any}
_rsrc = grab("api_discovery_rebind")
if _rsrc:
    exec(_rsrc, rns)


def _rebind(ip):
    _rdev.clear()
    _rdev.update({"key": "id:serial:SN1", "state": "moved", "printer_id": "b1", "ip": ip, "serial": "SN1",
                  "family": "bambu", "old_ip": "192.168.1.9"})
    try:
        return rns["api_discovery_rebind"]({"printer_id": "b1", "device_key": "id:serial:SN1"})
    except Exception as e:
        return {"exc": repr(e)}


_rb = _rebind("010.0.0.5")
check("24а. адрес из объявления «010.0.0.5» не записывается: отказ bad_address, адрес и связь не тронуты",
      _rb.get("reason") == "bad_address" and ips(rconn) == {"b1": "192.168.1.9"}
      and _rcalls["restart"] == 0 and not _rcalls["learn"], (_rb, ips(rconn), _rcalls))
_rb = _rebind("192.168.1.105")
check("24б. полный адрес записывается, и связь сразу перезапускается по нему",
      _rb.get("status") == "ok" and ips(rconn) == {"b1": "192.168.1.105"} and _rcalls["restart"] == 1, (_rb, ips(rconn), _rcalls))

# ════════════════════════════════════════════════════════════════════════════════════════════
print("--- 4. Перезапуск связи: для неполного адреса воркер не запускается ---")
wconn = sqlite3.connect(":memory:", check_same_thread=False)
wconn.row_factory = sqlite3.Row
wconn.execute(DDL)
for _pid, _t, _ip in (("node_gftic", "klipper", "198.68.104"), ("k_ok", "klipper", "192.168.1.104"),
                      ("b_bad", "bambu", "198.68.109"), ("b_ok", "bambu", "192.168.1.50"), ("demo1", "demo", "")):
    wconn.execute("INSERT INTO printers (id, name, type, ip, port, token) VALUES (?,?,?,?,?,?)",
                  (_pid, _pid, _t, _ip, 7125 if _t == "klipper" else None, "FIXTURE_TOKEN"))
wconn.commit()
started = []


class _Thr(object):
    def __init__(self, target=None, args=(), daemon=None, name=None):
        self.args = args

    def start(self):
        started.append(("thread", self.args[1].__name__, self.args[2], self.args[3]))


class _Threading(object):
    Thread = _Thr


class _Asyncio(object):
    @staticmethod
    def run_coroutine_threadsafe(coro, loop):
        started.append(("task", coro[1].__name__, coro[2], coro[3] if len(coro) > 3 else ""))
        return type("T", (), {"cancel": lambda self: None})()


def run_bambu(*a): pass
def run_klipper(*a): pass
def run_flashforge(*a): pass
def run_demo(*a): pass
def run_creality(*a): pass


wlog = _Log()
wns = {"worker_epoch": 0, "mqtt_cls": {}, "kl_tasks": {}, "lock_pr": threading.Lock(), "conn_pr": wconn,
       "printer_kinds": {}, "log": wlog, "_exc_brief": (lambda: "x"), "threading": _Threading,
       "asyncio": _Asyncio, "main_loop": object(), "run_bambu": run_bambu, "run_klipper": run_klipper,
       "run_flashforge": run_flashforge, "run_demo": run_demo, "run_creality": run_creality,
       "_run_guarded": (lambda *a: None), "_run_guarded_async": (lambda label, fn, *a: (label, fn) + tuple(a)),
       "p_states": {}, "OFFLINE_STATE": {"status": "OFFLINE", "percent": 0}, "_paddr": pa,
       "_addr_problem_logged": set()}
for _helper in ("_printer_address_blocked", "restart_workers"):
    _s = grab(_helper)
    if _s:
        exec(_s, wns)
try:
    wns["restart_workers"]()
    wns["restart_workers"]()          # второй перезапуск — журнал не должен повторяться
    _werr = ""
except Exception as e:
    _werr = repr(e)
_ids = {x[2] for x in started}
check("25. воркеры исправных принтеров (и виртуального) запущены", {"k_ok", "b_ok", "demo1"} <= _ids, (started, _werr))
check("26. по неполному адресу воркер НЕ запускается — ни Klipper, ни Bambu (код доступа не уходит)",
      "node_gftic" not in _ids and "b_bad" not in _ids, started)
_st = wns["p_states"].get("node_gftic") or {}
check("27. карточка получает причину «нет связи»: «Неполный адрес 198.68.104: нужно 4 числа через точку»",
      _st.get("status") == "OFFLINE" and _st.get("err_msg") == "Неполный адрес 198.68.104: нужно 4 числа через точку",
      _st)
_warn = [m for lvl, m in wlog.lines if "198.68.104" in m]
check("28. в журнале одна строка о принтере, а не на каждом перезапуске", len(_warn) == 1, wlog.lines)
#  Владелец исправил адрес — следующий перезапуск поднимает воркер, пометка снимается.
wconn.execute("UPDATE printers SET ip='198.68.1.104' WHERE id='node_gftic'")
wconn.commit()
started[:] = []
try:
    wns["restart_workers"]()
except Exception as e:
    _werr = repr(e)
check("29. исправили адрес — воркер пошёл по НОВОМУ адресу, прежняя причина снята",
      ("task", "run_klipper", "node_gftic", "198.68.1.104") in started
      and not (wns["p_states"].get("node_gftic") or {}).get("address_problem"), (started, wns["p_states"].get("node_gftic")))

# ════════════════════════════════════════════════════════════════════════════════════════════
print("--- 5. Список принтеров для интерфейса: поле address_problem ---")
try:
    from app import printer_dto as dto
    _d1 = dto.printer_public_dto({"id": "node_gftic", "type": "klipper", "ip": "198.68.104", "token": "FIXTURE_T"})
    _d2 = dto.printer_public_dto({"id": "k", "type": "klipper", "ip": "192.168.1.104"})
    _d3 = dto.printer_public_dto({"id": "d", "type": "demo", "ip": ""})
    check("30. неполный адрес помечен, исправный и виртуальный — нет, секрет не уходит",
          _d1.get("address_problem") == "short" and _d2.get("address_problem") is None
          and _d3.get("address_problem") is None and "token" not in _d1, (_d1, _d2, _d3))
except Exception as e:
    check("30. поле address_problem в списке принтеров", False, repr(e))

# ════════════════════════════════════════════════════════════════════════════════════════════
print("--- 6. Интерфейс на стенде: метка на карточке и ошибка в форме ---")
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402

PR = [
    {"id": "k2", "name": "K2 Plus", "type": "klipper", "model": "Creality K2 Plus", "ip": "192.0.2.10",
     "port": 7125, "serial": "", "gen": "auto", "credential_configured": False, "address_problem": None, "order_idx": 0},
    {"id": "node_gftic", "name": "Klipper 104", "type": "klipper", "model": "Creality K2 Plus", "ip": "198.68.104",
     "port": 7125, "serial": "", "gen": "auto", "credential_configured": False, "address_problem": "short", "order_idx": 1},
    {"id": "node_l9bkh", "name": "Klipper 109 с длинным именем принтера", "type": "klipper", "model": "Creality K2 Plus",
     "ip": "198.68.109", "port": 7125, "serial": "", "gen": "auto", "credential_configured": False,
     "address_problem": "short", "order_idx": 2},
]

JS = r"""
return new Promise(function(res){
  var out = {views: [], form: null};
  var l = byText('button', ['Позже', 'Later']); if (l) click(l);
  function sc(){ return document.querySelector('.pc-scroll'); }
  function viewOf(){ var c = sc(); if (!c) return '';
    var k = c.className; if (k.indexOf('pc-grid-cols')>=0) return 'grid'; if (k.indexOf('pc-dash-cols')>=0) return 'dash';
    if (k.indexOf('pc-rows')>=0) return 'rows'; return 'list'; }
  function measure(){
    var v = {view: viewOf(), marks: [], hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1};
    [].slice.call(document.querySelectorAll('.pc-scroll .printer-card')).forEach(function(card){
      var m = card.querySelector('.pc-addr-bad');
      var cr = card.getBoundingClientRect();
      var pid = card.getAttribute('data-pid');
      if (!m) { v.marks.push({pid: pid, mark: false}); return; }
      var r = m.getBoundingClientRect();
      v.marks.push({pid: pid, mark: true, text: (m.textContent||'').trim(), tip: m.getAttribute('title') || '',
        visible: r.width > 0 && r.height > 0 && getComputedStyle(m).visibility !== 'hidden',
        inside: r.left >= cr.left - 0.5 && r.right <= cr.right + 0.5 && r.top >= cr.top - 0.5 && r.bottom <= cr.bottom + 0.5,
        clipped: m.scrollWidth > m.clientWidth + 1, color: getComputedStyle(m).color});
    });
    return v;
  }
  var seen = {};
  function step(n){
    var v = viewOf();
    if (v && !seen[v]) { seen[v] = 1; out.views.push(measure()); }
    var sw = document.querySelector('[data-help="pview"]');
    if (n <= 0 || !sw) return openForm();
    click(sw);
    setTimeout(function(){ step(n - 1); }, 700);
  }
  function openForm(){
    //  Вид «Ячейки» (list) — там метка рядом с именем; нажимаем её, как владелец.
    var guard = 0;
    (function toList(){
      if (viewOf() === 'list' || guard++ > 5) {
        var card = document.querySelector('.printer-card[data-pid="node_gftic"]');
        var m = card ? card.querySelector('.pc-addr-bad') : null;
        if (m) click(m);
        setTimeout(function(){
          var f = {};
          var err = document.querySelector('.fm-addp-err');
          var ip = document.querySelector('[data-help="pf-ip"]');
          var save = document.querySelector('[data-help="pf-save"]');
          var sheet = document.querySelector('.fm-addp-sheet') || document.querySelector('.fm-addp-body');
          f.opened = !!ip; f.ipValue = ip ? ip.value : null;
          f.err = err ? (err.textContent||'').trim() : '';
          if (err && sheet) { var er = err.getBoundingClientRect(), sr = sheet.getBoundingClientRect();
            f.errInside = er.left >= sr.left - 0.5 && er.right <= sr.right + 0.5 && er.width > 0;
            f.errOverflow = err.scrollWidth > err.clientWidth + 1; }
          f.ipBad = !!(ip && ip.className.indexOf('fm-addp-bad') >= 0);
          f.saveDisabled = !!(save && save.disabled);
          if (ip) { ip.value = '198.68.1.104'; ip.dispatchEvent(new Event('input', {bubbles: true})); }
          setTimeout(function(){
            f.fixedErr = !!document.querySelector('.fm-addp-err');
            var s2 = document.querySelector('[data-help="pf-save"]'); f.fixedSaveDisabled = !!(s2 && s2.disabled);
            if (ip) { ip.value = '192.168.1.010'; ip.dispatchEvent(new Event('input', {bubbles: true})); }
            setTimeout(function(){
              var e3 = document.querySelector('.fm-addp-err'); f.zeroErr = e3 ? (e3.textContent||'').trim() : '';
              var s3 = document.querySelector('[data-help="pf-save"]'); f.zeroSaveDisabled = !!(s3 && s3.disabled);
              f.hscroll = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
              out.form = f;
              res(dump(out));
            }, 400);
          }, 400);
        }, 900);
        return;
      }
      var sw = document.querySelector('[data-help="pview"]'); if (sw) click(sw);
      setTimeout(toList, 600);
    })();
  }
  setTimeout(function(){ step(4); }, 1200);
});
"""

SIZES = ((1600, 1000), (1280, 800), (1024, 640), (853, 533))
PAGES = (("/ui3?ls=farm_lang:ru&ls=farm_view:list", "UI 3.0", ("list", "rows", "grid", "dash")),
         ("/?ls=farm_lang:ru&ls=farm_view:list", "UI 2.0", ("list", "grid")))
SHOTS = os.environ.get("FM_ADDR_SHOTS") or ""

if not stage.engine_ready():
    check("31. браузерный движок доступен (без него вид проверить нечем)", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/printers": PR})
    try:
        for path, label, want_views in PAGES:
            for (w, h) in SIZES:
                tag = "%s %dx%d" % (label, w, h)
                shot = os.path.join(SHOTS, "addr_%s_%dx%d.png" % ("ui3" if "ui3" in path else "ui2", w, h)) if SHOTS else None
                R = stage.run(JS, window_size=(w, h), path=path, settle_ms=2200, shot_path=shot)
                if not R:
                    check("31. %s: сценарий выполнился" % tag, False, str(stage.last_diag())[:300])
                    continue
                probs = stage.page_problems(R)
                views = {v.get("view"): v for v in (R.get("views") or [])}
                check("31. %s: пройдены все виды (%s)" % (tag, ", ".join(want_views)),
                      set(want_views) <= set(views), sorted(views))
                for vname in want_views:
                    v = views.get(vname) or {}
                    ms = {m.get("pid"): m for m in (v.get("marks") or [])}
                    bad = [ms.get("node_gftic") or {}, ms.get("node_l9bkh") or {}]
                    check("32. %s, вид %s: красная метка «Неполный адрес» у обоих принтеров, у исправного — нет"
                          % (tag, vname),
                          all(b.get("mark") and b.get("text") == "Неполный адрес" and b.get("visible") for b in bad)
                          and (ms.get("k2") or {}).get("mark") is False, v)
                    check("33. %s, вид %s: метка внутри карточки, текст не обрезан, страница не уезжает вбок"
                          % (tag, vname),
                          all(b.get("inside") and not b.get("clipped") for b in bad) and not v.get("hscroll"), v)
                f = R.get("form") or {}
                check("34. %s: нажатие на метку открывает этот принтер с его адресом" % tag,
                      f.get("opened") and f.get("ipValue") == "198.68.104", f)
                check("35. %s: под полем ошибка «Неполный адрес», поле красное, «Сохранить» недоступна" % tag,
                      f.get("err", "").startswith("Неполный адрес") and f.get("ipBad") and f.get("saveDisabled")
                      and f.get("errInside") and not f.get("errOverflow"), f)
                check("36. %s: дописали адрес — ошибка исчезла, сохранить можно" % tag,
                      f.get("opened") and f.get("fixedErr") is False and f.get("fixedSaveDisabled") is False, f)
                check("37. %s: адрес с ведущим нулём — снова ошибка и кнопка недоступна" % tag,
                      f.get("zeroErr", "").startswith("Так адрес не записывается") and f.get("zeroSaveDisabled")
                      and not f.get("hscroll"), f)
                check("38. %s: консоль браузера чистая" % tag, not probs, probs)
    finally:
        stage.set_api(None)

print()
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: FAIL=%d" % len(fails))
sys.exit(1 if fails else 0)
