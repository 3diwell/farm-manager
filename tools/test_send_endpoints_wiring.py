# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Статическая проверка ПРОВОДКИ фоновой отправки (Alpha 2.728): что ВСЕ сетевые точки запуска печати
# идут через единый менеджер (reservation), нет обхода, _send_file_to_printer вызывается ровно один раз,
# after_dispatch не задваивается, очередь/recovery/telemetry/watchdog подключены. Дополняет поведенческий
# tools/test_print_send_manager.py (там reservation/exactly-once/release/гонки/watchdog в рантайме).
# Запуск: python tools/test_send_endpoints_wiring.py   (0 = пройдено)
import os, sys, re
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
fail = 0
def check(name, cond):
    global fail; print(("PASS" if cond else "FAIL") + " — " + name); fail += 0 if cond else 1
def sl(a, b):
    i = SRC.index(a); return SRC[i:SRC.index(b, i)]

# W1: нет обхода — прямых run_in_executor(_send_file_to_printer) не осталось; _send_file_to_printer зовётся 1 раз
check("W1. нет прямого run_in_executor(_send_file_to_printer); _send_file_to_printer вызывается РОВНО один раз (в _mk_file_send)",
      "run_in_executor(None, _send_file_to_printer" not in SRC
      and len(re.findall(r"(?<!def )_send_file_to_printer\(", SRC)) == 1
      and "def _mk_file_send" in SRC and "progress_cb=progress" in SRC)

# W2: прямые endpoints идут через begin_direct
for fn, marker in [("upload_print", 'async def u_print('), ("print_path", 'async def u_print_path('), ("part/print", 'async def part_print(')]:
    body = sl(marker, "\n@app." if marker != 'async def part_print(' else "\ndef _bambu_start_print(")
    check("W2." + fn + ": через _send_mgr.begin_direct + _send_accept_response (accepted/409)",
          "_send_mgr.begin_direct" in body and "_send_accept_response" in body)

# W3: project — reserve СНАЧАЛА, project-job после (без фантома на 409); _from_queue → begin_or_adopt_tracked
proj = sl("async def _do_project2_file_print(", "\n@app.post")
check("W3. project: reserve до create_project_print_job (нет фантома на 409); очередь → begin_or_adopt_tracked; on_fail снимает задание",
      "_send_mgr.reserve(printer_id" in proj and proj.index("_send_mgr.reserve") < proj.index("create_project_print_job(project_id, file_id, printer_id, fname)\n    def _on_fail2")
      and "begin_or_adopt_tracked" in proj and "fail_project_print_job" in proj)

# W4: C1 start_print — через begin_direct, отдельным callable (после_dispatch НЕ добавлен)
cmd = sl("def _cmd_start_print_send(", "\n@app.post(\"/api/slicer-hook\")")
check("W4. C1 (/cmd start_print): через _send_mgr.begin_direct + _cmd_start_print_send; after_dispatch НЕ вызывается (хук-поведение не изменено)",
      "_send_mgr.begin_direct(pid, p[\"name\"], _fname, \"printer_file\"" in cmd and "_run_after_dispatch_hooks" not in cmd)

# W5: after_dispatch по-прежнему ТОЛЬКО после успешной команды (внутри if _cmd_ok) и не задвоен
send = sl("def _send_file_to_printer(", "\nfrom concurrent.futures import ThreadPoolExecutor as _SendPool")
check("W5. after_dispatch — ровно 5 мест (klipper accept + klipper pending-timeout (2.833) + bambu + flashforge + виртуальный принтер (2.979)), bambu внутри if _cmd_ok; не задвоено",
      send.count("_run_after_dispatch_hooks(") == 5
      and send.index("_pcb(command_ok=True)   # команда принята") < send.index("_run_after_dispatch_hooks(pid, _ams_map"))

# W6: телеметрия handle_state → note_printer_running (снятие reservation по подтверждению старта)
hs = sl("def handle_state(", "\ndef ")
check("W6. handle_state вызывает _send_mgr.note_printer_running при PREPARE/RUNNING", "_send_mgr.note_printer_running(pid)" in hs)

# W7: очередь — reserve на enqueue + send_job_id; worker адоптирует (_from_queue/_send_job_id)
# Alpha 2.741: третий элемент reserve() перестал быть «_» — enqueue разбирает причину отказа, чтобы
# отличить удержание (printer_held) от занятости и показать его в ответе. Смысл проверки прежний:
# reserve берётся на enqueue и его send_job_id кладётся в элемент, а worker его адоптирует.
check("W7. enqueue: _send_mgr.reserve + send_job_id в элементе; _start_queued_print пробрасывает _from_queue/_send_job_id",
      re.search(r'_rok, _sjid, _\w* = _send_mgr\.reserve\(pid', SRC) and '"send_job_id": _sjid' in SRC
      and "_from_queue=True, _send_job_id=q.get(\"send_job_id\")" in SRC and '"_from_queue": True, "_send_job_id": q.get("send_job_id")' in SRC)

# W8: отмена очереди освобождает reservation; recovery заново резервирует
check("W8. queue cancel (обычный+durable) → _send_mgr.cancel_reserved; _print_queue_recover → свежий reserve",
      SRC.count("_send_mgr.cancel_reserved(_sj,") == 2
      and SRC.count("_send_mgr.cancel_reserved(_sjid,") == 1   # Alpha 2.771 (Q-1): третья точка — воркер освобождает reservation недоставленного элемента
      and "item[\"send_job_id\"] = _rsjid if _rrok else None" in SRC)

# W9: watchdog-петля запущена демоном на старте
check("W9. watchdog менеджера запущен daemon-потоком на старте",
      "threading.Thread(target=_send_watchdog_loop, daemon=True).start()" in SRC and "def _send_watchdog_loop" in SRC)

# W10: API панели — снимок и dismiss
check("W10. GET /api/send-jobs (snapshot) и POST /api/send-jobs/{job_id}/dismiss (только терминальные)",
      '@app.get("/api/send-jobs")' in SRC and '@app.post("/api/send-jobs/{job_id}/dismiss")' in SRC
      and "_send_mgr.snapshot()" in SRC and "_send_mgr.dismiss(" in SRC)

# W11: прочие команды /cmd НЕ изменены (pause/resume/stop идут прежним синхронным путём)
# Alpha 2.782: имена в p_cmd изменились (data.cmd -> нормализованное _act из политики команд),
# ПОВЕДЕНИЕ прежнее — pause/resume/stop по-прежнему идут синхронно, мимо менеджера отправок.
# Якоря обновлены под новый текст; смысл проверки не ослаблен, а усилен явным требованием,
# чтобы менеджер в этой ветке не появился.
_pcmd_sync = SRC[SRC.index("_printer_cmd_policy.parse_command("):SRC.index('@app.post("/api/slicer-hook")')]
check("W11. прочие /cmd (pause/resume/stop) не тронуты — идут синхронно, не через менеджер",
      'if _act in ("pause", "resume", "stop")' in SRC and 'if _act == "stop":' in SRC
      and "_send_mgr" not in _pcmd_sync)

# W12: _send_file_to_printer/_bambu_ftp_upload progress_cb — необязательный (обратная совместимость)
check("W12. progress_cb=None по умолчанию у _send_file_to_printer и _bambu_ftp_upload (старые вызовы совместимы)",
      "def _send_file_to_printer(ptype, pip, pport, ptoken, pid, fname, fdata, ams_slot=None, print_opts=None, progress_cb=None)" in SRC
      and "def _bambu_ftp_upload(pip, ptoken, fname, fdata, attempts=3, timing=None, progress_cb=None)" in SRC)

# W13: C1 confirm restore — совместимость Bambu проверяется СИНХРОННО (_c1_load_plate_compat) ДО begin_direct;
# несовместимый блок возвращается ДО reservation; force/preload прокинуты в фоновый _cmd_start_print_send
# Alpha 2.782: конец ветки start_print теперь помечен вызовом политики команд, а не
# прежним 'elif data.cmd == "stop":'. Сама ветка start_print НЕ менялась.
pcmd_sp = sl('if data.cmd == "start_print":', '    _ok, _norm, _why = _printer_cmd_policy.parse_command(')
check("W13. C1 confirm restore: p_cmd делает _c1_load_plate_compat синхронно ДО begin_direct; incompatible → return до reserve; _preload прокинут в _cmd_start_print_send",
      "_c1_load_plate_compat(pid, p, data)" in pcmd_sp
      and pcmd_sp.index("_c1_load_plate_compat") < pcmd_sp.index("_send_mgr.begin_direct")
      and "return _blk" in pcmd_sp
      and "_cmd_start_print_send(p, pid, data, _preload)" in pcmd_sp
      and "def _c1_load_plate_compat(pid, p, data)" in SRC)

# W14: единый concurrency gate — run_tracked (очередь/recovery) выполняет worker через ТОТ ЖЕ выделенный пул
# self._ex (max_workers=4), а не напрямую в потоке-вызывателе → суммарный предел ≤4 send callables соблюдён
rt = sl("def run_tracked(", "\n    def begin_direct(")
check("W14. concurrency gate: run_tracked идёт через self._ex.submit(self._worker) (общий пул ≤4) и блокируется на fut.result(); прямого self._worker(...) в обход пула больше нет",
      "self._ex.submit(self._worker, job_id, send_callable, on_result)" in rt
      and "return fut.result()" in rt
      and "return self._worker(" not in rt)

print()
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ" if fail == 0 else ("ПРОВАЛЕНО: " + str(fail)))
sys.exit(1 if fail else 0)
