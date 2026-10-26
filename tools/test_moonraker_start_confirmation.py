# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.799 — честное подтверждение запуска печати через Moonraker (Klipper).
#
#  ПОЛНОСТЬЮ OFFLINE. server.py НЕ импортируется обычным способом: реальная функция
#  _send_file_to_printer и хелперы извлекаются разбором AST и исполняются в изоляции
#  с ПОДДЕЛЬНЫМ urllib (fake Moonraker) — без реального принтера, без LAN, без сокетов,
#  без рабочей БД/config. Реальный G-code не используется (фиктивный payload). Секреты
#  в вывод не печатаются.
#
#  ЧТО ДОКАЗЫВАЕТ. HTTP-ошибка (401/403/404/5xx), недоступность принтера и ответ
#  Moonraker print_started=false БОЛЬШЕ НЕ маскируются под успех (и, как следствие, под
#  start_not_confirmed): транспорт возвращает ТОЧНУЮ причину, а command_ok выставляется
#  ТОЛЬКО при подтверждённом старте (print_started=true либо отсутствие поля у старого
#  Moonraker — обратная совместимость).
#
#  Запуск:  python tools/test_moonraker_start_confirmation.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import io
import json
import os
import socket
import sys
import types
import urllib.error as _urlerr
import urllib.request as _urlreq

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# ── Страж преждевременного выхода ────────────────────────────────────────────
_DONE = {"ok": False}

def _guard():
    if not _DONE["ok"]:
        try:
            print("FAIL — тест завершился до выполнения проверок")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)

atexit.register(_guard)

# ── Ловушка реальных сокетов: транспорт в тесте НЕ должен открыть сеть ────────
_REAL_SOCKETS = []
_ORIG_SOCKET = socket.socket

class _TrapSocket(object):
    def __init__(self, *a, **k):
        _REAL_SOCKETS.append(a)
        raise AssertionError("offline-тест: реальные сокеты запрещены (используется fake urllib)")

socket.socket = _TrapSocket

FAILED = []
PASSED = [0]

def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)

def section(t):
    print("\n--- %s ---" % t)

# Метка-ловушка: только в фикстурах теста (как фиктивный токен/имя).
SENTINEL = "MOONRAKER_START_SENTINEL_2_799"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
OWN = open(os.path.abspath(__file__), encoding="utf-8").read()

def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""

# ── Fake Moonraker: подставной urllib, управляемый текущим сценарием ─────────
_SCENARIO = {"mode": "started_true", "requests": []}

class _FakeResp(object):
    def __init__(self, body):
        self._b = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
    def read(self):
        return self._b

def _fake_urlopen(req, timeout=None):
    # Захватываем факт запроса (url + тело) для проверок; НЕ открываем сеть.
    try:
        url = req.get_full_url()
        data = req.data
    except Exception:
        url, data = str(req), None
    _SCENARIO["requests"].append({"url": url, "len": (len(data) if data else 0),
                                  "body": (data or b"")})
    m = _SCENARIO["mode"]
    if m == "started_true":
        return _FakeResp(json.dumps({"item": {"path": "f.gcode", "root": "gcodes"},
                                     "print_started": True, "action": "create_file"}))
    if m == "started_false":
        return _FakeResp(json.dumps({"item": {"path": "f.gcode", "root": "gcodes"},
                                     "print_started": False, "action": "create_file"}))
    if m == "started_false_nested":
        return _FakeResp(json.dumps({"result": {"item": {}, "print_started": False}}))
    if m == "no_field":   # старый Moonraker без print_started
        return _FakeResp(json.dumps({"item": {"path": "f.gcode", "root": "gcodes"}}))
    if m == "bad_json":
        return _FakeResp(b"<html>not json</html>")
    if m in ("http_401", "http_403", "http_404", "http_500"):
        code = int(m.split("_")[1])
        raise _urlerr.HTTPError("http://fake/server/files/upload", code, "err", {}, io.BytesIO(b"{}"))
    if m == "urlerror":
        raise _urlerr.URLError("timed out")
    if m == "read_timeout":
        # Alpha 2.833: READ timeout ПОСЛЕ полной отправки запроса — bare TimeoutError
        # (do_open оборачивает в URLError только фазу ОТПРАВКИ; getresponse бросает голый).
        raise TimeoutError("timed out")
    if m == "exception":
        raise RuntimeError("unexpected boom")
    return _FakeResp(b"{}")

_fake_urllib = types.SimpleNamespace(
    request=types.SimpleNamespace(Request=_urlreq.Request, urlopen=_fake_urlopen),
    error=_urlerr)

# ── Стабы модульных зависимостей _send_file_to_printer (klipper-ветка) ────────
class _Log(object):
    def __init__(self): self.lines = []
    def _r(self, *a, **k):
        try: self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception: self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = exception = _r

LOG = _Log()
HOOKS = {"after_dispatch": 0, "stash": 0}
PRE = types.SimpleNamespace(stash_dispatch=lambda *a, **k: None)

from app import klipper_start as _klstart_mod   # Alpha 2.833: контракт исхода запуска (pending и т.д.)

NS = {
    "urllib": _fake_urllib, "json": json, "time": __import__("time"), "os": os, "re": __import__("re"),
    "io": io, "zipfile": __import__("zipfile"),
    "log": LOG, "server_print": {}, "_server_print_ts": {}, "print_run_events": PRE,
    "_run_after_dispatch_hooks": lambda *a, **k: HOOKS.__setitem__("after_dispatch", HOOKS["after_dispatch"] + 1),
    "_stash_run_assignments": lambda *a, **k: HOOKS.__setitem__("stash", HOOKS["stash"] + 1),
    "_klstart": _klstart_mod,   # Alpha 2.833: timeout-ветка берёт user_message из контракта
    "p_states": {}, "_exc_brief": lambda: "",
    #  2.978: перед новой отправкой сервер снимает отметку «оператор нажал Стоп».
    #  Пустой словарь = никто ничего не останавливал.
    "_user_stopped": {},
}
#  Alpha 2.890: путь запуска Klipper спрашивает, с какого слота списывать филамент
#  (CFS у Creality K2). Берём НАСТОЯЩУЮ функцию сервера, а не заглушку: при пустом
#  состоянии принтеров она обязана вернуть прежнее «слот 0, внешняя катушка».
for _f in ("_send_sanitize_err", "_moonraker_print_started", "_moonraker_http_error_reason",
           "_klipper_dispatch_slots", "_send_file_to_printer", "_merge_printer_secret"):
    exec(compile(fn_src(_f), "<server>", "exec"), NS)
send = NS["_send_file_to_printer"]
merge_secret = NS["_merge_printer_secret"]
started_of = NS["_moonraker_print_started"]

FDATA = b"; fake gcode " + SENTINEL.encode() + b"\nG28\n"   # фиктивный «G-code», не настоящий

def run_send(mode, fname="Part_1.gcode", port=None, pcb=None):
    _SCENARIO["mode"] = mode
    _SCENARIO["requests"] = []
    HOOKS["after_dispatch"] = 0; HOOKS["stash"] = 0
    seen = {"command_ok": False, "stages": []}
    def _pcb(**kw):
        if kw.get("command_ok"):
            seen["command_ok"] = True
        if kw.get("stage"):
            seen["stages"].append(kw["stage"])
    res = send("klipper", "10.0.0.99", port, SENTINEL, "pX", fname, FDATA, progress_cb=(pcb or _pcb))
    return res, seen


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.799: честное подтверждение запуска Moonraker (offline, fake transport) ===")
section("чистые хелперы разбора ответа Moonraker")

check("H1. print_started=true -> True", started_of(json.dumps({"print_started": True}).encode()) is True)
check("H2. print_started=false -> False", started_of(json.dumps({"print_started": False}).encode()) is False)
check("H3. print_started во вложенном result -> читается",
      started_of(json.dumps({"result": {"print_started": False}}).encode()) is False)
check("H4. поля нет (старый Moonraker) -> None (не ломаем обратную совместимость)",
      started_of(json.dumps({"item": {}}).encode()) is None)
check("H5. битый JSON -> None (никогда не бросает)", started_of(b"<html>") is None)
check("H6. не-словарь -> None", started_of(json.dumps([1, 2]).encode()) is None)
_r401 = NS["_moonraker_http_error_reason"](401)
_r404 = NS["_moonraker_http_error_reason"](404)
_r500 = NS["_moonraker_http_error_reason"](500)
check("H7. 401/403 -> причина про авторизацию (не start_not_confirmed)",
      "авториз" in _r401.lower() and "start_not_confirmed" not in _r401)
check("H8. 404 -> причина про endpoint", "endpoint" in _r404.lower())
check("H9. 5xx -> причина про отклонение с кодом", "HTTP 500" in _r500)


# ════════════════════════════════════════════════════════════════════════════
section("транспорт: успех и подтверждение старта")

res, seen = run_send("started_true")
check("1. print_started=true -> status ok, command_ok выставлен",
      res.get("status") == "ok" and seen["command_ok"] is True)
check("1b. успех вызывает after_dispatch и stash ровно по одному разу",
      HOOKS["after_dispatch"] == 1 and HOOKS["stash"] == 1)
res, seen = run_send("no_field")
check("9. поля print_started нет (старый Moonraker) -> считаем принятым (обратная совместимость)",
      res.get("status") == "ok" and seen["command_ok"] is True)


# ════════════════════════════════════════════════════════════════════════════
section("транспорт: ошибки НЕ маскируются под start_not_confirmed")

def _no_mask(res, seen):
    return (res.get("status") == "error" and seen["command_ok"] is False
            and "start_not_confirmed" not in str(res.get("reason", ""))
            and HOOKS["after_dispatch"] == 0 and HOOKS["stash"] == 0)

res, seen = run_send("started_false")
check("3/6. print_started=false -> error 'start_rejected'-класса, command_ok НЕ выставлен, "
      "after_dispatch не вызван",
      _no_mask(res, seen) and ("не начал печать" in res["reason"] or "did not start" in res["reason"]))
res, seen = run_send("started_false_nested")
check("6b. print_started=false во вложенном result -> тоже error", _no_mask(res, seen))
res, seen = run_send("http_401")
check("2. HTTP 401 -> error (авторизация), НЕ start_not_confirmed",
      _no_mask(res, seen) and "авториз" in res["reason"].lower())
res, seen = run_send("http_403")
check("3. HTTP 403 -> error (авторизация), НЕ start_not_confirmed",
      _no_mask(res, seen) and "авториз" in res["reason"].lower())
res, seen = run_send("http_404")
check("4. HTTP 404 -> error (endpoint), НЕ start_not_confirmed",
      _no_mask(res, seen) and "endpoint" in res["reason"].lower())
res, seen = run_send("http_500")
check("5. HTTP 500 -> error (отклонение), НЕ start_not_confirmed",
      _no_mask(res, seen) and "HTTP 500" in res["reason"])
res, seen = run_send("urlerror")
check("7. недоступный принтер (URLError) -> error (нет связи), start НЕ вызван",
      _no_mask(res, seen) and ("нет связи" in res["reason"].lower() or "no connection" in res["reason"].lower()))
res, seen = run_send("exception")
check("10. неожиданное исключение транспорта НЕ проглатывается -> error (не ok, не command_ok)",
      _no_mask(res, seen))

# ── Alpha 2.833: READ timeout после отправки — PENDING, а не ложная ошибка ────
res, seen = run_send("read_timeout")
check("T1. read-timeout ПОСЛЕ отправки -> НЕ error (нет ложной «Ошибка запуска печати»)",
      res.get("status") == "ok" and res.get("pending_confirmation") is True)
check("T2. read-timeout -> command_ok (job переходит в waiting_confirmation, ждём телеметрию)",
      seen["command_ok"] is True)
check("T3. read-timeout -> хуки как при принятой команде (ровно один раз, без повтора)",
      HOOKS["after_dispatch"] == 1 and HOOKS["stash"] == 1)
check("T4. read-timeout -> ровно ОДИН POST (автоповтора команды НЕТ)",
      len(_SCENARIO["requests"]) == 1)
check("T5. сообщение pending — «ожидание подтверждения», RU и EN, без слова «ошибка»",
      ("жидание подтверждения" in str(res.get("reason", "")) and "Waiting for start confirmation" in str(res.get("reason", "")))
      and "шибка" not in str(res.get("reason", "")))
res, seen = run_send("bad_json")
check("6c. HTTP 2xx с непарсируемым телом -> поле не найдено -> принято (обратная совместимость, не крэш)",
      res.get("status") == "ok" and seen["command_ok"] is True)


# ════════════════════════════════════════════════════════════════════════════
section("контракт запроса: один POST, порт, имя файла, отсутствие ретрая")

res, seen = run_send("started_true", fname="My Part 1.gcode")
reqs = _SCENARIO["requests"]
check("13. один клик -> РОВНО один POST на /server/files/upload (нет второго start)",
      len(reqs) == 1 and reqs[0]["url"].endswith("/server/files/upload"))
check("11/8. загрузка+запуск одним POST с print=true; имя файла в теле, upload проверяется",
      b'name="print"' in reqs[0]["body"] and b"true" in reqs[0]["body"]
      and b'filename="My Part 1.gcode"' in reqs[0]["body"])
check("14. автоматического ретрая нет (одна попытка на вызов)", len(reqs) == 1)
check("14b. urlopen вызывается с timeout (нет вечного зависания на мёртвом принтере)",
      "urlopen(req, timeout=" in fn_src("_send_file_to_printer"))
res, _ = run_send("started_true", port=None)
check("11b. порт по умолчанию 7125 при пустом порте",
      ":7125/server/files/upload" in _SCENARIO["requests"][0]["url"])
res, _ = run_send("started_true", port=8125)
check("11c. явный порт используется как есть",
      ":8125/server/files/upload" in _SCENARIO["requests"][0]["url"])
res, seen = run_send("http_401")
check("15. при ошибке транспорта start-хуки не запускаются (реальный принтер не «стартует»)",
      HOOKS["after_dispatch"] == 0)


# ════════════════════════════════════════════════════════════════════════════
section("сохранение секрета принтера (Alpha 2.776) — не регрессировало")

check("16. пустое поле токена при редактировании -> сохранённый токен ОСТАЁТСЯ",
      merge_secret(None, "OLD_SECRET") == "OLD_SECRET"
      and merge_secret("", "OLD_SECRET") == "OLD_SECRET"
      and merge_secret("   ", "OLD_SECRET") == "OLD_SECRET")
check("16b. непустое значение -> заменяет; удаление секрета — только удалением принтера",
      merge_secret("NEW", "OLD_SECRET") == "NEW")
check("17. секрет не возвращается фронтенду из формы (merge не раскрывает stored наружу — только пишет в БД)",
      "return stored" in fn_src("_merge_printer_secret"))
check("18. секрет/токен не попал в журнал теста",
      not any(SENTINEL in l for l in LOG.lines))


# ════════════════════════════════════════════════════════════════════════════
section("side-effect order и предохранители")

check("SE1. reason ошибки санируется (без токенов/путей) перед отдачей в UI",
      "def _send_sanitize_err" in SRV and "_send_sanitize_err(e)" in fn_src("_send_file_to_printer"))
check("SE2. за прогон не открыт ни один реальный сокет (fake transport)", not _REAL_SOCKETS)
check("SE3. sentinel отсутствует в production-исходниках",
      SENTINEL not in SRV and SENTINEL not in ORCH)
check("SE4. sentinel определён один раз в оснастке теста", OWN.count(SENTINEL) == 1)
check("19. DISPATCH_ENABLED остаётся False",
      __import__("re").search(r"^DISPATCH_ENABLED = False\s*$", ORCH, __import__("re").M) is not None)
check("20. TRANSPORT_ENABLED остаётся False",
      __import__("re").search(r"^TRANSPORT_ENABLED = False\s*$", ORCH, __import__("re").M) is not None)
# start_not_confirmed остаётся ВАЛИДНЫМ только для подлинного случая (команда принята, но
# телеметрия не показала RUNNING) — этот код в sweep менеджера НЕ трогался.
check("21. start_not_confirmed остаётся только в подлинном месте (sweep менеджера), "
      "транспорт его НЕ возвращает",
      "start_not_confirmed" in fn_src("_confirm_sweep") if fn_src("_confirm_sweep")
      else ("start_not_confirmed" not in fn_src("_send_file_to_printer")))
check("21b. транспорт klipper НЕ возвращает start_not_confirmed (точные причины вместо маскировки)",
      "start_not_confirmed" not in fn_src("_send_file_to_printer"))


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _DONE["ok"] = True
    sys.exit(1)
print("PASS: подтверждение запуска Moonraker — все %d проверок пройдены; server.py не импортирован" % _total)
_DONE["ok"] = True
sys.exit(0)
