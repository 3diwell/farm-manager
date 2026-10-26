# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.833 — надёжное подтверждение запуска печати Klipper/Moonraker.
#
#  ПОЛНОСТЬЮ OFFLINE: server.py не импортируется; функция _send_file_to_printer и класс
#  _PrintSendManager извлекаются AST-разбором и исполняются с ПОДДЕЛЬНЫМ urllib (fake
#  Moonraker) и синхронным пулом. Реальных принтеров/сети/БД нет; ловушка сокетов активна.
#
#  ЧТО ДОКАЗЫВАЕТ (сценарий K2 Plus, 23:50:12):
#   • READ timeout ПОСЛЕ отправки upload+print → PENDING (waiting_confirmation), НЕ ошибка;
#   • команда никогда не повторяется автоматически (ровно один POST);
#   • телеметрия того же принтера/файла через секунду подтверждает старт (completed);
#   • reservation не снимается преждевременно; lifecycle один; уверенный отказ ≠ timeout;
#   • контракт confirmed/pending/rejected/failed_before_send/uncertain (app/klipper_start.py).
#
#  Запуск:  python tools/test_klipper_start_confirmation.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import io
import json
import os
import socket
import sys
import threading
import time as _time
import types
import urllib.error as _urlerr
import urllib.request as _urlreq
from collections import deque

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_DONE = {"ok": False}

def _guard():
    if not _DONE["ok"]:
        try:
            print("FAIL — тест завершился до выполнения проверок"); sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)

atexit.register(_guard)

_ORIG_SOCKET = socket.socket

class _TrapSocket(object):
    def __init__(self, *a, **k):
        raise AssertionError("offline-тест: реальные сокеты запрещены")

socket.socket = _TrapSocket

FAILED = []
PASSED = [0]

def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1; print("PASS — %s" % name)
    else:
        FAILED.append(name); print("FAIL — %s%s" % (name, (" | " + extra) if extra else ""))
    return ok

def section(t):
    print("\n--- %s ---" % t)

# Метка-ловушка: ТОЛЬКО в фикстурах теста (фиктивный токен). В production-исходники не попадает.
SENTINEL = "KLIPPER_START_CONFIRMATION_SENTINEL_2_833"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)

def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""

def cls_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, ast.ClassDef) and n.name == name:
            return ast.unparse(n)
    return ""

from app import klipper_start as K   # чистый контракт — импортируется напрямую

# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.833: подтверждение запуска Klipper (offline, fake transport) ===")
section("контракт решений (app/klipper_start.py)")

check("C1. классификация: read-timeout после отправки -> PENDING (не провал)",
      K.classify_transport_failure(K.KIND_TIMEOUT_AFTER_SEND) == K.PENDING_CONFIRMATION)
check("C2. классификация: connect/DNS до отправки -> FAILED_BEFORE_SEND",
      K.classify_transport_failure(K.KIND_CONNECT_ERROR) == K.FAILED_BEFORE_SEND
      and K.classify_transport_failure(K.KIND_DNS_ERROR) == K.FAILED_BEFORE_SEND)
check("C3. классификация: HTTP-ошибка / print_started=false -> REJECTED",
      K.classify_transport_failure(K.KIND_HTTP_ERROR) == K.REJECTED
      and K.classify_transport_failure(K.KIND_PRINT_STARTED_FALSE) == K.REJECTED)
check("C4. неизвестный сбой -> PENDING (команда могла уйти; не ложный провал, не повтор)",
      K.classify_transport_failure("???") == K.PENDING_CONFIRMATION)
check("C5. авто-retry запрещён для pending/uncertain/confirmed; разрешён (ручной) для rejected/failed_before_send",
      not K.retry_allowed(K.PENDING_CONFIRMATION) and not K.retry_allowed(K.UNCERTAIN)
      and not K.retry_allowed(K.CONFIRMED) and K.retry_allowed(K.REJECTED) and K.retry_allowed(K.FAILED_BEFORE_SEND))
check("C6. сообщения RU·EN: pending без слова «ошибка», uncertain НЕ утверждает «печать не запущена»",
      "жидание подтверждения" in K.user_message(K.PENDING_CONFIRMATION)
      and "шибка" not in K.user_message(K.PENDING_CONFIRMATION)
      and "Печать не запущена" not in K.user_message(K.UNCERTAIN)
      and "Проверьте" in K.user_message(K.UNCERTAIN) and "Check the printer" in K.user_message(K.UNCERTAIN))

section("идентичность имени файла Moonraker (проверка 10)")
check("F1. normalization: регистр/путь/basename",
      K.filenames_match("M Frame_4h19m.gcode", "M FRAME_4H19M.GCODE")
      and K.filenames_match("M Frame_4h19m.gcode", "gcodes/M Frame_4h19m.gcode")
      and K.filenames_match("job\\part.gcode", "sub/dir/part.gcode"))
check("F2. другой файл НЕ совпадает; пустое наблюдение НЕ совпадает",
      not K.filenames_match("a.gcode", "b.gcode") and not K.filenames_match("a.gcode", "")
      and not K.filenames_match("", "a.gcode"))

section("evaluate_confirmation: телеметрия -> решение (проверки 7, 11-15, 18-20)")
ATT = K.PrintStartAttempt("p1", "M Frame_4h19m.gcode", started_at=1000.0, confirmation_window=45.0)
check("E1(7). printing + тот же принтер/файл -> CONFIRMED",
      K.evaluate_confirmation(ATT, "p1", "printing", "mframe_4h19m.gcode".replace("mframe", "M Frame"), 1001.0) == K.CONFIRMED)
check("E2(11). ДРУГОЙ файл printing -> НЕ подтверждает (pending)",
      K.evaluate_confirmation(ATT, "p1", "printing", "other.gcode", 1001.0) == K.PENDING_CONFIRMATION)
check("E3(12). ДРУГОЙ принтер printing -> НЕ подтверждает",
      K.evaluate_confirmation(ATT, "p2", "printing", "M Frame_4h19m.gcode", 1001.0) == K.PENDING_CONFIRMATION)
check("E4(13). СТАРАЯ физическая сессия (session_start < attempt) -> НЕ подтверждает",
      K.evaluate_confirmation(ATT, "p1", "printing", "M Frame_4h19m.gcode", 1001.0, session_start=900.0) == K.PENDING_CONFIRMATION)
check("E4b. свежая сессия (>= attempt-slack) подтверждает",
      K.evaluate_confirmation(ATT, "p1", "printing", "M Frame_4h19m.gcode", 1002.0, session_start=1000.5) == K.CONFIRMED)
check("E5(14). paused + тот же файл -> CONFIRMED (job был запущен)",
      K.evaluate_confirmation(ATT, "p1", "paused", "M Frame_4h19m.gcode", 1005.0) == K.CONFIRMED)
check("E6(15). complete БЕЗ наблюдавшегося старта -> НЕ confirmed",
      K.evaluate_confirmation(ATT, "p1", "complete", "M Frame_4h19m.gcode", 1005.0) != K.CONFIRMED)
check("E7(18). дедлайн истёк, доказательств нет -> UNCERTAIN",
      K.evaluate_confirmation(ATT, "p1", "standby", "", 1046.0) == K.UNCERTAIN)
check("E8. до дедлайна, покой -> PENDING (ещё ждём)",
      K.evaluate_confirmation(ATT, "p1", "standby", "", 1010.0) == K.PENDING_CONFIRMATION)
check("E9. НЕсвежая телеметрия -> PENDING (ничего не утверждаем)",
      K.evaluate_confirmation(ATT, "p1", "standby", "", 2000.0, fresh=False) == K.PENDING_CONFIRMATION)
check("E10(20). ПОЗДНЕЕ подтверждение (после дедлайна, printing тот же файл) -> CONFIRMED",
      K.evaluate_confirmation(ATT, "p1", "printing", "M Frame_4h19m.gcode", 1100.0) == K.CONFIRMED)

# ════════════════════════════════════════════════════════════════════════════
section("транспорт _send_file_to_printer (klipper): fake Moonraker")

_SCEN = {"mode": "ok", "requests": []}

class _FakeResp(object):
    def __init__(self, body): self._b = body
    def read(self): return self._b

def _fake_urlopen(req, timeout=None):
    url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
    _SCEN["requests"].append({"url": url, "len": len(req.data or b"") if hasattr(req, "data") else 0})
    m = _SCEN["mode"]
    if m == "ok":
        return _FakeResp(json.dumps({"item": {"path": "f.gcode"}, "print_started": True}).encode())
    if m == "read_timeout":
        raise TimeoutError("timed out")            # READ timeout: запрос уже полностью отправлен
    if m == "connect_error":
        raise _urlerr.URLError(OSError(10061, "refused"))   # фаза отправки: соединение не установлено
    if m == "http_500":
        raise _urlerr.HTTPError(url, 500, "err", {}, io.BytesIO(b"{}"))
    if m == "started_false":
        return _FakeResp(json.dumps({"print_started": False}).encode())
    return _FakeResp(b"{}")

_fake_urllib = types.SimpleNamespace(
    request=types.SimpleNamespace(Request=_urlreq.Request, urlopen=_fake_urlopen),
    error=_urlerr, parse=__import__("urllib.parse", fromlist=["parse"]))

class _Log(object):
    def __init__(self): self.lines = []
    def _r(self, *a, **k):
        try: self.lines.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception: self.lines.append(" ".join(str(x) for x in a))
    info = warning = error = debug = exception = _r

LOG = _Log()
HOOKS = {"after_dispatch": 0, "stash": 0}
NS = {
    "urllib": _fake_urllib, "json": json, "time": _time, "os": os, "re": __import__("re"),
    "io": io, "zipfile": __import__("zipfile"),
    "log": LOG, "server_print": {}, "_server_print_ts": {},
    "print_run_events": types.SimpleNamespace(stash_dispatch=lambda *a, **k: None),
    "_run_after_dispatch_hooks": lambda *a, **k: HOOKS.__setitem__("after_dispatch", HOOKS["after_dispatch"] + 1),
    "_stash_run_assignments": lambda *a, **k: HOOKS.__setitem__("stash", HOOKS["stash"] + 1),
    "_klstart": K,
    "p_states": {}, "_exc_brief": lambda: "",
    #  2.978: перед новой отправкой сервер снимает отметку «оператор нажал Стоп».
    #  Пустой словарь = никто ничего не останавливал.
    "_user_stopped": {},
}
#  Alpha 2.890: путь запуска Klipper спрашивает, с какого слота списывать филамент
#  (CFS у Creality K2). Берём НАСТОЯЩУЮ функцию сервера, а не заглушку: при пустом
#  состоянии принтеров она обязана вернуть прежнее «слот 0, внешняя катушка».
for _f in ("_send_sanitize_err", "_moonraker_print_started", "_moonraker_http_error_reason",
           "_klipper_dispatch_slots", "_send_file_to_printer"):
    exec(compile(fn_src(_f), "<server>", "exec"), NS)
send = NS["_send_file_to_printer"]
FDATA = b"; fake gcode " + SENTINEL.encode() + b"\nG28\n"

def run_send(mode, fname="M Frame_4h19m.gcode"):
    _SCEN["mode"] = mode; _SCEN["requests"] = []
    HOOKS["after_dispatch"] = 0; HOOKS["stash"] = 0
    LOG.lines[:] = []
    seen = {"command_ok": False, "stages": []}
    def _pcb(**kw):
        if kw.get("command_ok"): seen["command_ok"] = True
        if kw.get("stage"): seen["stages"].append(kw["stage"])
    res = send("klipper", "10.0.0.99", None, SENTINEL, "pK2", fname, FDATA, progress_cb=_pcb)
    return res, seen

res, seen = run_send("ok")
check("T1(1). success-ответ -> status ok, command_ok (confirmed путь)",
      res.get("status") == "ok" and not res.get("pending_confirmation") and seen["command_ok"])
res, seen = run_send("read_timeout")
check("T2(2). read-timeout ПОСЛЕ отправки -> pending (НЕ красная ошибка)",
      res.get("status") == "ok" and res.get("pending_confirmation") is True)
check("T3(3). pending НЕ содержит текста ошибки (нет «Ошибка запуска печати»)",
      "Ошибка запуска печати" not in str(res.get("reason", "")))
check("T4(28). read-timeout -> РОВНО один POST (авто-retry команды/upload НЕТ)",
      len(_SCEN["requests"]) == 1)
check("T5(30). лог timeout БЕЗ вводящего в заблуждение «ERROR uploading/printing»",
      not any("ERROR uploading/printing" in l for l in LOG.lines)
      and any("awaiting telemetry confirmation" in l for l in LOG.lines))
check("T6(27). timeout-ветка не удаляет загруженный файл (нет delete-вызова)",
      not any("delete" in q["url"].lower() for q in _SCEN["requests"]))
res, seen = run_send("connect_error")
check("T7(17). connect failure ДО отправки -> error «Нет связи» (failed_before_send), command_ok НЕТ",
      res.get("status") == "error" and "нет связи" in str(res.get("reason", "")).lower()
      and not seen["command_ok"] and HOOKS["after_dispatch"] == 0)
res, seen = run_send("http_500")
check("T8(16). явный HTTP-отказ Moonraker -> rejected с кодом (НЕ timeout-маскировка)",
      res.get("status") == "error" and "HTTP 500" in str(res.get("reason", "")))
res, seen = run_send("started_false")
check("T9(26/29). upload принят, но печать НЕ началась -> ТОЧНАЯ стадийная причина",
      res.get("status") == "error" and ("не начал печать" in res["reason"] or "did not start" in res["reason"]))

# ════════════════════════════════════════════════════════════════════════════
section("менеджер отправок: pending -> телеметрия -> completed (проверки 5-9, 21-25)")

class _SyncFuture(object):
    def __init__(self, val): self._v = val
    def result(self): return self._v

class _SyncPool(object):
    def __init__(self, *a, **k): pass
    def submit(self, fn, *a, **k): return _SyncFuture(fn(*a, **k))

#  2.990: сторож подтверждения перестал считать покоем принтер, который ВЫПОЛНЯЕТ
#  стадию (парковка, прогрев), и сам просит свежий отчёт. В песочнице оба признака
#  управляемые: _WORKING — «принтер занят стадией», _REPORTS — счётчик запросов отчёта.
_PSTATUS = {"status": "IDLE", "fresh": True}
_WORKING = {"on": False}
_REPORTS = []
MNS = {
    "threading": threading, "time": _time, "os": os, "log": LOG,
    "_SendPool": _SyncPool, "_send_deque": deque, "deque": deque,
    "_uid": (lambda prefix: prefix + str(len(MREG))),
    "_exc_brief": lambda: "",
    "_send_sanitize_err": NS["_send_sanitize_err"],
    "_send_printer_status": lambda pid: (_PSTATUS["status"], _PSTATUS["fresh"]),
    "_send_working_stage": lambda pid: _WORKING["on"],
    "_bambu_request_report": lambda pid: _REPORTS.append(pid) or True,
    "_hold_public": lambda h: h,
    "JSONResponse": dict,
}
MREG = []
for _c in ("_SEND_STATES", "_SEND_TERMINAL", "_SEND_DONE_TTL", "_SEND_CONFIRM_GRACE",
           "_SEND_QUEUE_ORPHAN_GRACE", "_SEND_MAX_WORKERS", "_SEND_HISTORY"):
    for n in ast.walk(SRV_AST):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == _c for t in n.targets):
            exec(compile(ast.unparse(n), "<const>", "exec"), MNS)
            break
exec(compile(cls_src("_PrintSendManager"), "<mgr>", "exec"), MNS)   # _SendPool в MNS уже = _SyncPool
Mgr = MNS["_PrintSendManager"]

def send_pending(progress):
    """Как klipper-ветка при read-timeout: command_ok + pending-результат."""
    progress(stage="uploading"); progress(command_ok=True)
    return {"status": "ok", "pending_confirmation": True}

def send_fail(progress):
    progress(stage="uploading")
    return {"status": "error", "reason": "Нет связи"}

fired = []
m = Mgr()
ok, jid, why = m.begin_direct("pK2", "K2 Plus", "M Frame_4h19m.gcode", "print_path", send_pending, on_result=lambda r: fired.append(r))
j = m._jobs[jid]
check("M1(2). pending-отправка -> job в waiting_confirmation (НЕ failed)",
      ok and j["state"] == "waiting_confirmation" and j["error"] is None)
check("M2(5). on_result (job_failed-канал) НЕ вызван при pending", fired == [])
check("M3(6). reservation НЕ снята преждевременно (принтер занят наш attempt)",
      m.reserved_ids() == {"pK2"})
ok2, jid2, why2 = m.begin_direct("pK2", "K2 Plus", "second.gcode", "print_path", send_pending)
check("M4(23). double-click -> ВТОРОЙ attempt отвергнут (busy), attempt один",
      ok2 is False and why2 == "busy" and jid2 == jid and len([x for x in m._jobs.values() if x["state"] not in ("completed", "failed")]) == 1)
m.note_printer_running("pK2")   # телеметрия через ~1 сек: PREPARE/RUNNING того же принтера
check("M5(7/8/9). телеметрия printing -> job completed, reservation снята (сценарий K2 Plus)",
      m._jobs[jid]["state"] == "completed" and m.reserved_ids() == set())
m.note_printer_running("pK2")   # duplicate/late телеметрия
check("M6(21/22). повторная/поздняя телеметрия идемпотентна (job остаётся completed, второго lifecycle нет)",
      m._jobs[jid]["state"] == "completed" and len(m._jobs) == 1 or m._jobs[jid]["state"] == "completed")

# watchdog: устойчиво-свежий покой -> start_not_confirmed; stale -> ждём
m2 = Mgr()
ok, jid, _ = m2.begin_direct("pK2", "K2 Plus", "f.gcode", "print_path", send_pending)
_PSTATUS.update({"status": "IDLE", "fresh": True})
m2._jobs[jid]["updated_at"] = _time.time() - (MNS["_SEND_CONFIRM_GRACE"] + 5)
m2.tick()
check("M7(18). bounded deadline: свежий устойчивый покой > grace -> failed 'start_not_confirmed' + release",
      m2._jobs[jid]["state"] == "failed" and m2._jobs[jid]["error"] == "start_not_confirmed"
      and m2.reserved_ids() == set())
m3 = Mgr()
ok, jid, _ = m3.begin_direct("pK2", "K2 Plus", "f.gcode", "print_path", send_pending)
_PSTATUS.update({"status": "OFFLINE", "fresh": False})
m3._jobs[jid]["updated_at"] = _time.time() - (MNS["_SEND_CONFIRM_GRACE"] + 5)
m3.tick()
check("M8. stale/offline телеметрия -> остаёмся waiting_confirmation (НЕ ложный release, НЕ ложный провал)",
      m3._jobs[jid]["state"] == "waiting_confirmation" and m3.reserved_ids() == {"pK2"})

#  2.990 (фото владельца 10.09.2026): H2D уже парковал голову и грел стол, а gcode_state
#  ещё показывал IDLE. Сторож объявлял «старт не подтверждён» и показывал владельцу
#  красную ошибку, хотя печать шла. Стадия работы — не покой.
_PSTATUS.update({"status": "IDLE", "fresh": True})
_WORKING["on"] = True
_REPORTS.clear()
m3b = Mgr()
ok, jid3b, _ = m3b.begin_direct("pK2", "K2 Plus", "f.gcode", "print_path", send_pending)
m3b._jobs[jid3b]["updated_at"] = _time.time() - (MNS["_SEND_CONFIRM_GRACE"] + 5)
m3b.tick()
check("M8b. КОРЕНЬ ДЕФЕКТА: принтер ВЫПОЛНЯЕТ стадию (статус ещё IDLE) — отправка НЕ гасится",
      m3b._jobs[jid3b]["state"] == "waiting_confirmation" and m3b.reserved_ids() == {"pK2"},
      (m3b._jobs[jid3b]["state"], m3b._jobs[jid3b].get("error")))
check("M8c. и пока ждём подтверждения, свежий отчёт СПРАШИВАЕТСЯ, а не ожидается планового",
      _REPORTS == ["pK2"], _REPORTS)

#  НЕ ВАКУУМ: без признака стадии те же данные по-прежнему гасят отправку — значит
#  проверка меряет разницу, а не саму себя.
_WORKING["on"] = False
m3c = Mgr()
ok, jid3c, _ = m3c.begin_direct("pK2", "K2 Plus", "f.gcode", "print_path", send_pending)
m3c._jobs[jid3c]["updated_at"] = _time.time() - (MNS["_SEND_CONFIRM_GRACE"] + 5)
m3c.tick()
check("M8d. НЕ ВАКУУМ: принтер действительно в покое — отправка честно гасится как прежде",
      m3c._jobs[jid3c]["state"] == "failed" and m3c._jobs[jid3c]["error"] == "start_not_confirmed")
_PSTATUS.update({"status": "IDLE", "fresh": True})
m4 = Mgr()
ok, jid, _ = m4.begin_direct("pK2", "K2 Plus", "f.gcode", "print_path", send_fail)
check("M9. настоящий провал ДО отправки -> failed сразу + on_result-канал открыт",
      m4._jobs[jid]["state"] == "failed")
# Гонка: телеметрия ПРИШЛА, но command_ok ещё не выставлен (sending_command) -> job НЕ завершается
# вслепую (только пометка _saw_running); телеметрия чужого старта не закрывает наш attempt.
m5 = Mgr()
ok, jid5, _ = m5.reserve("pK2", "K2 Plus", "f.gcode", "print_path")
j5 = m5._jobs[jid5]; j5["state"] = "sending_command"
m5.note_printer_running("pK2")
check("M10. телеметрия ДО command_ok НЕ завершает job (нет слепого подтверждения без отправленной команды)",
      j5["state"] == "sending_command" and j5.get("_saw_running") is True and m5.reserved_ids() == {"pK2"})

section("отсутствие скрытого повтора и персистентности команды (проверки 24-25)")
check("R1(24). _send_file_to_printer вызывается РОВНО из одного места (замыкание _mk_file_send) — reconnect фронта не создаёт второй путь",
      SRV.count("_send_file_to_printer(ptype, pip, pport, ptoken, pid, fname, fdata, ams_slot, print_opts, progress_cb=progress)") == 1
      and SRV.count("def _send_file_to_printer") == 1)
_mgr_txt = cls_src("_PrintSendManager")
check("R2(25). менеджер не персистит send_callable/команду (restart backend НЕ может повторить ambiguous start)",
      "'send_callable'" not in _mgr_txt and '"send_callable"' not in _mgr_txt   # callable не хранится в job-dict
      and "sqlite" not in _mgr_txt.lower() and "conn_pr" not in _mgr_txt        # состояние только в памяти
      and "j['_command_sent'] = True" in _mgr_txt.replace('"', "'"))            # факт отправки — да, команда — нет
check("R3(4). timeout-ветка не создаёт device_error (health-канал не задет)",
      "device_error" not in fn_src("_send_file_to_printer"))
_klbranch = fn_src("_send_file_to_printer")
check("R4. в klipper-ветке нет цикла повтора urlopen (одна попытка)",
      _klbranch.count("urllib.request.urlopen(req, timeout=15.0)") == 1
      and "for _attempt" not in _klbranch and "while" not in _klbranch.split("elif ptype == 'bambu'")[0])

section("UI-текст uncertain (проверка 12) + sentinel")
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
_errfn = APPJS.split("const sendErrLabel")[1].split("const sendIsTerminal")[0] if "const sendErrLabel" in APPJS else ""
check("U1(12). start_not_confirmed -> «Не удалось подтвердить запуск…», а НЕ «Печать не запущена»",
      "start_not_confirmed" in _errfn
      and "Не удалось подтвердить запуск. Проверьте состояние принтера перед повторной отправкой." in _errfn
      and "Could not confirm the start" in _errfn
      and "Печать не запущена" not in _errfn)
check("U2. панель отправок использует sendErrLabel (маппинг кода, не сырой код ошибки)",
      "sendErrLabel(j)" in open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
      and ", sendErrLabel," in APPJS)   # и он возвращён из setup (урок 2.831)
_leaks = []
for _p in ("server.py", "web/app.js", "web/index.html", "app/klipper_start.py", "app/klipper_prestart.py",
           "app/route_policy_registry.py", "app/config_backup/settings_registry.py"):
    if SENTINEL in open(os.path.join(REPO, _p), encoding="utf-8", errors="surrogateescape").read():
        _leaks.append(_p)
check("S1. sentinel отсутствует в production-исходниках", not _leaks, str(_leaks))

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
print("Итого: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
_DONE["ok"] = True
socket.socket = _ORIG_SOCKET
sys.exit(1 if FAILED else 0)
