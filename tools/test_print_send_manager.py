# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Тесты изолированного менеджера фоновых отправок _PrintSendManager (Alpha 2.728).
# БЕЗ сервера/принтеров/сети: из server.py ИЗВЛЕКАЕТСЯ ДОСЛОВНЫЙ блок менеджера (константы +
# _send_sanitize_err + _send_printer_status + класс) и исполняется со стабами. send_callable —
# управляемые заглушки с событиями (никаких реальных сетевых операций/принтеров).
#
# Покрытие: атомарная reservation + 409; exactly-once run/run_tracked; ограниченный пул (≤4);
# release при ошибке; удержание reservation при успехе до телеметрии; телеметрия RUNNING после и ДО
# waiting_confirmation; RUNNING во время upload игнорируется; watchdog авто-fail устойчивой IDLE и
# НЕ-release живого worker'а; stale/offline не даёт ложного release; cancel_reserved; dismiss;
# bounded history; санитайзен snapshot; монотонный прогресс Bambu; C1/остальные progress=null;
# A19 — ЕДИНЫЙ concurrency gate: 4 прямых + queue(run_tracked) + recovery(begin_or_adopt_tracked)
# суммарно ≤4 send callables (ждущие permit — 'queued', стартуют после освобождения слота, exactly-once).
#
# Запуск: python tools/test_print_send_manager.py   (0 = все проверки пройдены)
# ============================================================================
import os, sys, re, time, threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()

fail = 0
def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1

# ── извлечь дословный блок менеджера ──
block = SRC[SRC.index("from concurrent.futures import ThreadPoolExecutor as _SendPool"):SRC.index("\ndef _send_watchdog_loop")]
check("A0. извлечён дословный блок менеджера (класс + reservation + tick)",
      "class _PrintSendManager" in block and "def reserve" in block and "def note_printer_running" in block and "def tick" in block)

_uidc = [0]
def _uid(prefix=""):
    _uidc[0] += 1
    return str(prefix) + format(_uidc[0], "06d")

CNS = {
    "threading": threading, "time": time, "os": os, "re": re,
    "_uid": _uid, "p_states": {}, "last_seen": {}, "STALE_FAIL_S": 60,
    "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None), "warning": staticmethod(lambda *a, **k: None), "info": staticmethod(lambda *a, **k: None)})(),
    "_exc_brief": (lambda: ""),
}
exec(block, CNS)
Mgr = CNS["_PrintSendManager"]

# ── управляемая заглушка send_callable ──
def slow_send(hold_evt=None, result=None, before_stage="uploading"):
    """Заглушка: preparing→uploading (+ opt. hold) → sending_command → command_ok → result."""
    def send(progress):
        progress(stage=before_stage)
        if hold_evt is not None:
            hold_evt.wait(5.0)
        progress(stage="sending_command")
        r = result if result is not None else {"status": "ok"}
        if r.get("status") == "ok":
            progress(command_ok=True)
        return r
    return send

# ═══ A1: атомарная reservation + 409 ═══
m = Mgr()
ok1, jid1, _ = m.reserve("P1", "Printer1", "a.3mf", "task")
ok2, jid2, r2 = m.reserve("P1", "Printer1", "b.3mf", "task")
ok3, jid3, _ = m.reserve("P2", "Printer2", "c.3mf", "task")
check("A1. второй reserve того же принтера → busy с existing job_id; другой принтер независим",
      ok1 and not ok2 and r2 == "busy" and jid2 == jid1 and ok3 and jid3 != jid1)

# ═══ A2: exactly-once run ═══
calls = [0]
def once_send(progress):
    calls[0] += 1
    progress(stage="uploading"); progress(stage="sending_command"); progress(command_ok=True)
    return {"status": "ok"}
r_a = m.run(jid1, once_send); r_b = m.run(jid1, once_send)
time.sleep(0.3)
check("A2. run дважды → второй отказан; send_callable вызван РОВНО один раз", r_a is True and r_b is False and calls[0] == 1)

# ═══ A3: успешная команда → waiting_confirmation, reservation УДЕРЖАНА ═══
m3 = Mgr()
ok, j3, _ = m3.begin_direct("PX", "PX", "f.3mf", "task", slow_send())
time.sleep(0.3)
snap = m3.snapshot()
jj = [x for x in snap["jobs"] if x["job_id"] == j3][0]
check("A3. успех → state=waiting_confirmation и принтер ещё зарезервирован (до телеметрии)",
      jj["state"] == "waiting_confirmation" and "PX" in snap["reserved_printer_ids"])

# ═══ A4: телеметрия RUNNING после command → completed + release ═══
m3.note_printer_running("PX")
snap = m3.snapshot()
jj = [x for x in snap["jobs"] if x["job_id"] == j3][0]
check("A4. телеметрия RUNNING (команда отправлена) → completed + reservation снята",
      jj["state"] == "completed" and "PX" not in snap["reserved_printer_ids"])

# ═══ A5: ошибка отправки → failed + release + on_result ═══
m5 = Mgr()
fired = [0]
ok, j5, _ = m5.begin_direct("PE", "PE", "e.3mf", "project", slow_send(result={"status": "error", "reason": "boom"}), on_result=lambda r: fired.__setitem__(0, fired[0] + 1))
time.sleep(0.3)
snap = m5.snapshot()
jj = [x for x in snap["jobs"] if x["job_id"] == j5][0]
check("A5. ошибка → failed + reservation снята + on_result вызван один раз",
      jj["state"] == "failed" and "PE" not in snap["reserved_printer_ids"] and fired[0] == 1 and (jj["error"] or "") != "")

# ═══ A6: RUNNING ДО перехода в waiting_confirmation (во время sending_command) → completed ═══
m6 = Mgr()
hold = threading.Event()
def race_send(progress):
    progress(stage="uploading")
    progress(stage="sending_command")
    hold.wait(5.0)                     # держим в sending_command
    progress(command_ok=True)          # команда подтверждается ПОСЛЕ телеметрии
    return {"status": "ok"}
ok, j6, _ = m6.begin_direct("PR", "PR", "r.3mf", "task", race_send)
time.sleep(0.2)                        # job в sending_command
m6.note_printer_running("PR")          # RUNNING пришёл раньше command_ok → _saw_running
snap_mid = m6.snapshot()
mid_reserved = "PR" in snap_mid["reserved_printer_ids"]
hold.set()                             # теперь command_ok
time.sleep(0.3)
snap = m6.snapshot()
jj = [x for x in snap["jobs"] if x["job_id"] == j6][0]
check("A6. RUNNING во время sending_command удержал reservation, затем command_ok → completed+release",
      mid_reserved and jj["state"] == "completed" and "PR" not in snap["reserved_printer_ids"])

# ═══ A7: RUNNING во время uploading (команда НЕ отправлена) → игнор, reservation держится ═══
m7 = Mgr()
hold7 = threading.Event()
def up_send(progress):
    progress(stage="uploading")
    hold7.wait(5.0)                    # держим в uploading
    progress(stage="sending_command"); progress(command_ok=True)
    return {"status": "ok"}
ok, j7, _ = m7.begin_direct("PU", "PU", "u.3mf", "task", up_send)
time.sleep(0.2)
m7.note_printer_running("PU")          # RUNNING во время uploading — НЕ наш старт
snap = m7.snapshot()
still = "PU" in snap["reserved_printer_ids"] and [x for x in snap["jobs"] if x["job_id"] == j7][0]["state"] == "uploading"
hold7.set(); time.sleep(0.3)
check("A7. RUNNING во время uploading игнорируется (команда не отправлена), reservation держится", still)

# ═══ A8: ограниченный пул (≤4 одновременно) при 20 job'ах ═══
m8 = Mgr(max_workers=4)
cur = [0]; mx = [0]; clock = threading.Lock(); barrier = threading.Event()
def busy_send(progress):
    with clock:
        cur[0] += 1; mx[0] = max(mx[0], cur[0])
    progress(stage="uploading")
    barrier.wait(5.0)
    progress(stage="sending_command"); progress(command_ok=True)
    with clock:
        cur[0] -= 1
    return {"status": "ok"}
t0 = time.time()
accepted = 0
for i in range(20):
    ok, jid, _ = m8.begin_direct("PB%02d" % i, "PB%02d" % i, "b.3mf", "task", busy_send)
    if ok: accepted += 1
accept_ms = (time.time() - t0) * 1000
time.sleep(0.4)
peak = mx[0]
barrier.set(); time.sleep(0.6)
check("A8. 20 job'ов быстро приняты (accept<300мс), одновременно работает ≤4 worker'а (пик=%d)" % peak,
      accepted == 20 and accept_ms < 300 and 1 <= peak <= 4)

# ═══ A9: watchdog — waiting_confirmation + свежая устойчивая IDLE после grace → failed+release ═══
m9 = Mgr()
CNS["p_states"] = {"PW": {"status": "IDLE"}}; CNS["last_seen"] = {"PW": time.time()}
ok, j9, _ = m9.begin_direct("PW", "PW", "w.3mf", "task", slow_send())
time.sleep(0.3)   # → waiting_confirmation
# подделываем «старый» updated_at, чтобы превысить grace
with m9._lock:
    m9._jobs[j9]["updated_at"] = time.time() - (CNS["STALE_FAIL_S"] * 0 + 100)
m9.tick(now=time.time())
snap = m9.snapshot()
jj = [x for x in snap["jobs"] if x["job_id"] == j9][0]
check("A9. watchdog: свежая устойчивая IDLE после grace, старт не подтверждён → failed+release",
      jj["state"] == "failed" and "PW" not in snap["reserved_printer_ids"])

# ═══ A10: stale/offline телеметрия → watchdog НЕ освобождает (нет ложной двойной печати) ═══
m10 = Mgr()
CNS["p_states"] = {"PS": {"status": "OFFLINE"}}; CNS["last_seen"] = {"PS": time.time() - 999}
ok, j10, _ = m10.begin_direct("PS", "PS", "s.3mf", "task", slow_send())
time.sleep(0.3)
with m10._lock:
    m10._jobs[j10]["updated_at"] = time.time() - 100
m10.tick(now=time.time())
snap = m10.snapshot()
jj = [x for x in snap["jobs"] if x["job_id"] == j10][0]
check("A10. stale/offline телеметрия → остаётся waiting_confirmation, reservation держится",
      jj["state"] == "waiting_confirmation" and "PS" in snap["reserved_printer_ids"])

# ═══ A11: watchdog НЕ освобождает job с живым worker'ом ═══
m11 = Mgr()
holdw = threading.Event()
def hang_send(progress):
    progress(stage="uploading")
    holdw.wait(5.0)   # worker «висит» в uploading
    progress(stage="sending_command"); progress(command_ok=True)
    return {"status": "ok"}
CNS["p_states"] = {"PH": {"status": "IDLE"}}; CNS["last_seen"] = {"PH": time.time()}
ok, j11, _ = m11.begin_direct("PH", "PH", "h.3mf", "task", hang_send)
time.sleep(0.2)
with m11._lock:
    m11._jobs[j11]["updated_at"] = time.time() - 100
m11.tick(now=time.time())
snap = m11.snapshot()
held = "PH" in snap["reserved_printer_ids"] and [x for x in snap["jobs"] if x["job_id"] == j11][0]["state"] == "uploading"
holdw.set(); time.sleep(0.3)
check("A11. watchdog НЕ трогает job с активным worker'ом (передачу нельзя остановить)", held)

# ═══ A12: cancel_reserved queued (не запущен) освобождает; live не трогает ═══
m12 = Mgr()
ok, j12, _ = m12.reserve("PC", "PC", "c.3mf", "queue")   # queued, worker не запущен
c_ok = m12.cancel_reserved(j12)
snap = m12.snapshot()
check("A12. cancel_reserved у queued (не запущен) → failed+release", c_ok and "PC" not in snap["reserved_printer_ids"])

m12b = Mgr(); holdc = threading.Event()
def live_send(progress):
    progress(stage="uploading"); holdc.wait(5.0); progress(stage="sending_command"); progress(command_ok=True); return {"status": "ok"}
ok, j12b, _ = m12b.begin_direct("PCL", "PCL", "cl.3mf", "task", live_send)
time.sleep(0.2)
c_ref = m12b.cancel_reserved(j12b)
snap = m12b.snapshot()
live_held = (c_ref is False) and "PCL" in snap["reserved_printer_ids"]
holdc.set(); time.sleep(0.3)
check("A12b. cancel_reserved у активного worker'а ОТКАЗАН, reservation держится", live_held)

# ═══ A13: dismiss терминального ок, активного — отказ ═══
m13 = Mgr()
ok, j13, _ = m13.begin_direct("PD", "PD", "d.3mf", "task", slow_send())
time.sleep(0.3); m13.note_printer_running("PD")   # → completed
d_ok, _ = m13.dismiss(j13)
ok2, j13b, _ = m13.reserve("PD2", "PD2", "d2.3mf", "queue")   # активный queued
d_no, reason = m13.dismiss(j13b)
check("A13. dismiss: терминальный удаляется из панели; активный НЕ удаляется",
      d_ok and (j13 not in [x["job_id"] for x in m13.snapshot()["jobs"]]) and (d_no is False) and reason == "active")

# ═══ A14: bounded history — активные не режутся, старые терминальные уходят ═══
m14 = Mgr(history=5)
for i in range(12):
    ok, jid, _ = m14.begin_direct("PT%02d" % i, "PT%02d" % i, "t.3mf", "task", slow_send())
    time.sleep(0.02); m14.note_printer_running("PT%02d" % i)   # каждый → completed
ok, jact, _ = m14.reserve("PACT", "PACT", "act.3mf", "queue")   # активный queued
time.sleep(0.2)
jobs = m14.snapshot()["jobs"]
term = [x for x in jobs if x["state"] == "completed"]
check("A14. терминальная история ограничена (≤5), активный queued НЕ вырезан лимитом",
      len(term) <= 5 and any(x["job_id"] == jact for x in jobs))

# ═══ A15: snapshot без секретов/путей ═══
m15 = Mgr()
ok, j15, _ = m15.begin_direct("PSAN", "PSAN", "C:\\secret\\path\\file.3mf",
                              "task", slow_send(result={"status": "error", "reason": "login bblp:ACCESSCODE failed at C:\\Users\\x\\farm.db"}))
time.sleep(0.3)
snap = m15.snapshot()
jj = [x for x in snap["jobs"] if x["job_id"] == j15][0]
blob = str(snap)
check("A15. snapshot: file_name без пути; error без token/path; полей payload/ip/token нет",
      jj["file_name"] == "file.3mf" and "ACCESSCODE" not in blob and "C:\\" not in blob and "bblp" not in blob
      and set(jj.keys()) == {"job_id", "printer_id", "printer_name", "file_name", "source", "state", "progress", "bytes_sent", "bytes_total", "created_at", "updated_at", "error", "queue_id"})

# ═══ A16: монотонный реальный прогресс Bambu (байты) ═══
m16 = Mgr()
seen = []
def bytes_send(progress):
    progress(stage="uploading", total=1000)
    for s in (100, 400, 400, 900, 1000):   # включая «повтор/просадку» 400 — прогресс монотонный
        progress(sent=s, total=1000)
        snapj = [x for x in m16.snapshot()["jobs"] if x["printer_id"] == "PBY"][0]
        seen.append(snapj["progress"])
    progress(stage="sending_command"); progress(command_ok=True)
    return {"status": "ok"}
ok, j16, _ = m16.begin_direct("PBY", "PBY", "by.3mf", "task", bytes_send)
time.sleep(0.4)
mono = all(seen[i] <= seen[i + 1] for i in range(len(seen) - 1)) and seen[-1] == 100.0 and seen[0] == 10.0
check("A16. Bambu: прогресс монотонный 0..100 по реальным байтам (0.4вниз не отматывает): %s" % seen, mono)

# ═══ A17: C1/остальные транспорты — progress=null (только стадии) ═══
m17 = Mgr()
def stage_only(progress):
    progress(stage="sending_command"); progress(command_ok=True); return {"status": "ok"}
ok, j17, _ = m17.begin_direct("PC1", "PC1", "onprinter.3mf", "printer_file", stage_only)
time.sleep(0.3)
jj = [x for x in m17.snapshot()["jobs"] if x["job_id"] == j17][0]
check("A17. C1/стадийный транспорт: progress=null, bytes=null, дошёл до waiting_confirmation",
      jj["progress"] is None and jj["bytes_sent"] is None and jj["bytes_total"] is None and jj["state"] == "waiting_confirmation")

# ═══ A18: run_tracked (очередь inline) exactly-once + возвращает результат ═══
m18 = Mgr()
ok, j18, _ = m18.reserve("PQ", "PQ", "q.3mf", "queue")
res = m18.run_tracked(j18, slow_send(result={"status": "ok"}))
res2 = m18.run_tracked(j18, slow_send())   # второй запуск того же job → None (уже стартовал/терминал)
jj = [x for x in m18.snapshot()["jobs"] if x["job_id"] == j18][0]
check("A18. run_tracked (staggered-очередь): возвращает результат отправки; повторный запуск отказан",
      isinstance(res, dict) and res.get("status") == "ok" and res2 is None and jj["state"] == "waiting_confirmation")

# ═══ A19: ЕДИНЫЙ предел параллельности ≤4 для direct + queue + recovery (concurrency gate, Alpha 2.728) ═══
# Мешаный сценарий: 4 медленных ПРЯМЫХ job'а занимают весь выделенный пул (max_workers=4); ОДНОВРЕМЕННО
# очередь (run_tracked) и recovery (begin_or_adopt_tracked) пытаются запустить 5-й/6-й. Пик активных send
# callables СУММАРНО должен быть строго ≤4; ждущие permit остаются 'queued' (не ложный 'uploading');
# после освобождения слотов ждущие стартуют; exactly-once и reservation сохраняются; дедлока нет.
m19 = Mgr()
g_lock = threading.Lock(); g_active = [0]; g_peak = [0]
def _counted(entered=None, hold=None):
    def send(progress):
        if entered is not None: entered[0] += 1
        with g_lock:
            g_active[0] += 1
            if g_active[0] > g_peak[0]: g_peak[0] = g_active[0]
        progress(stage="uploading")
        if hold is not None: hold.wait(5.0)
        with g_lock:
            g_active[0] -= 1
        progress(stage="sending_command"); progress(command_ok=True)
        return {"status": "ok"}
    return send

holds = [threading.Event() for _ in range(4)]
for i in range(4):
    m19.begin_direct("D%d" % i, "D%d" % i, "d.3mf", "task", _counted(hold=holds[i]))
_dl = time.time() + 3.0
while g_active[0] < 4 and time.time() < _dl: time.sleep(0.01)   # ждём, пока 4 прямых займут пул

# очередь: reserve на enqueue + run_tracked при диспетче (реальный путь воркера очереди)
q_entered = [0]; q_hold = threading.Event(); q_res = [None]
okq, jq, _ = m19.reserve("Q5", "Q5", "q.3mf", "queue")
def _q_dispatch(): q_res[0] = m19.run_tracked(jq, _counted(entered=q_entered, hold=q_hold))
tq = threading.Thread(target=_q_dispatch, daemon=True); tq.start()
# recovery: begin_or_adopt_tracked (свежая reservation) — тоже через gate
r_entered = [0]; r_hold = threading.Event(); r_res = [None]
def _r_dispatch():
    r_res[0], _rj = m19.begin_or_adopt_tracked("R6", "R6", "r.3mf", "recovery", _counted(entered=r_entered, hold=r_hold))
tr = threading.Thread(target=_r_dispatch, daemon=True); tr.start()
time.sleep(0.5)   # даём (ошибочный) шанс запуститься 5-му/6-му поверх лимита

snap = m19.snapshot()
jqs = [x for x in snap["jobs"] if x["job_id"] == jq][0]["state"]
_rjob = [x for x in snap["jobs"] if x["printer_id"] == "R6"]
jrs = _rjob[0]["state"] if _rjob else "?"
check("A19a. 4 прямых насытили пул; queue(run_tracked)+recovery(adopt) НЕ запустили send callable; пик==4; ждущие в 'queued'; их reservation держится",
      g_peak[0] == 4 and q_entered[0] == 0 and r_entered[0] == 0
      and jqs == "queued" and jrs == "queued"
      and "Q5" in snap["reserved_printer_ids"] and "R6" in snap["reserved_printer_ids"])

# освобождаем ДВА прямых → 2 permit'а свободны → queue+recovery стартуют, суммарный пик по-прежнему ≤4
holds[0].set(); holds[1].set()
_dl = time.time() + 3.0
while (q_entered[0] == 0 or r_entered[0] == 0) and time.time() < _dl: time.sleep(0.01)
check("A19b. после завершения прямых — ждавшие queue+recovery стартовали (send callable вошёл); суммарный пик строго ≤4",
      q_entered[0] == 1 and r_entered[0] == 1 and 1 <= g_peak[0] <= 4)

# дренаж: отпускаем всё, ждём завершения диспетч-потоков (проверка отсутствия дедлока)
q_hold.set(); r_hold.set(); holds[2].set(); holds[3].set()
tq.join(3.0); tr.join(3.0)
res_q2 = m19.run_tracked(jq, _counted())   # повторный запуск того же job → None (exactly-once)
snap = m19.snapshot()
jqf = [x for x in snap["jobs"] if x["job_id"] == jq][0]["state"]
check("A19c. exactly-once (повторный run_tracked→None); queue+recovery дошли до waiting_confirmation; общий пик за весь тест ≤4; reservation держится до телеметрии; дедлока нет",
      res_q2 is None and (q_res[0] or {}).get("status") == "ok" and (r_res[0] or {}).get("status") == "ok"
      and jqf == "waiting_confirmation" and g_peak[0] == 4
      and (not tq.is_alive()) and (not tr.is_alive())
      and "Q5" in snap["reserved_printer_ids"])

# ═══ A20 (Alpha 2.771, Q-1): watchdog брошенных reservation ОЧЕРЕДИ ═══
# sweep_queue_orphans освобождает job ТОЛЬКО когда за него доказанно никто не отвечает.
# Активные отправки очереди приходят готовым множеством (порядок замков: print_queue_lock
# берётся и отпускается вызывающим ДО обращения к менеджеру).
OLD = 10000.0   # «возраст» заведомо больше любого grace

m20 = Mgr()
_, j_orphan, _ = m20.reserve("W1", "W1", "a.gcode", "queue")
_, j_inqueue, _ = m20.reserve("W2", "W2", "b.gcode", "queue")
_, j_disp, _ = m20.reserve("W3", "W3", "c.gcode", "queue")
_, j_direct, _ = m20.reserve("W4", "W4", "d.gcode", "task")       # прямая отправка — не очередь
_, j_proj, _ = m20.reserve("W5", "W5", "e.gcode", "project")      # проектная — тоже не очередь
_, j_started, _ = m20.reserve("W6", "W6", "f.gcode", "queue")
m20._jobs[j_started]["_started"] = True                            # ждёт permit общего пула

for _j in (j_orphan, j_inqueue, j_disp, j_direct, j_proj, j_started):
    m20._jobs[_j]["created_at"] -= OLD                             # состарили все

# очередь отвечает за j_inqueue (ждёт в print_queue) и j_disp (воркер уже диспетчеризует)
rel = m20.sweep_queue_orphans(frozenset({j_inqueue, j_disp}))
rel_ids = {r["job_id"] for r in rel}

check("A20a. брошенная queued-reservation очереди освобождена (ссылки в очереди нет)",
      rel_ids == {j_orphan} and "W1" not in m20.reserved_ids())
check("A20b. элемент, ЖДУЩИЙ в print_queue, не тронут при любом возрасте",
      j_inqueue not in rel_ids and "W2" in m20.reserved_ids())
check("A20c. элемент в диспетчеризации не тронут при любом возрасте",
      j_disp not in rel_ids and "W3" in m20.reserved_ids())
check("A20d. прямые отправки source=task/project не трогаются",
      j_direct not in rel_ids and j_proj not in rel_ids
      and "W4" in m20.reserved_ids() and "W5" in m20.reserved_ids())
check("A20e. job, ждущий permit пула (_started=True), не считается брошенным",
      j_started not in rel_ids and "W6" in m20.reserved_ids())

# grace: свежая reservation без ссылки в очереди НЕ освобождается
m21 = Mgr()
_, j_fresh, _ = m21.reserve("W7", "W7", "g.gcode", "queue")
check("A20f. свежая reservation не освобождается (grace защищает от гонок)",
      m21.sweep_queue_orphans(frozenset()) == [] and "W7" in m21.reserved_ids())

# активные стадии отправки watchdog не трогает даже без ссылки в очереди
m22 = Mgr()
_, j_act, _ = m22.reserve("W8", "W8", "h.gcode", "queue")
m22._jobs[j_act]["created_at"] -= OLD
_bad_stage = None
for _st in ("preparing", "uploading", "sending_command", "waiting_confirmation"):
    m22._jobs[j_act]["state"] = _st
    if m22.sweep_queue_orphans(frozenset()):
        _bad_stage = _st
        break
check("A20g. preparing/uploading/sending_command/waiting_confirmation не трогаются",
      _bad_stage is None and "W8" in m22.reserved_ids())

# повторный проход идемпотентен, чужие reservation не затрагиваются
m23 = Mgr()
_, j_o1, _ = m23.reserve("W9", "W9", "i.gcode", "queue")
_, j_o2, _ = m23.reserve("WA", "WA", "j.gcode", "queue")
m23._jobs[j_o1]["created_at"] -= OLD
m23._jobs[j_o2]["created_at"] -= OLD
r1 = m23.sweep_queue_orphans(frozenset({j_o2}))
r2 = m23.sweep_queue_orphans(frozenset({j_o2}))
check("A20h. повторный проход идемпотентен; чужая активная reservation цела",
      {x["job_id"] for x in r1} == {j_o1} and r2 == [] and "WA" in m23.reserved_ids())

print()
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if fail == 0 else ("ПРОВАЛЕНО ПРОВЕРОК: " + str(fail)))
sys.exit(1 if fail else 0)
