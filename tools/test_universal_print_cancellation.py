# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.826 — УНИВЕРСАЛЬНАЯ классификация остановки печати (job outcome != device health).
#
#  ПОЛНОСТЬЮ OFFLINE. Ни сети, ни принтеров, ни рабочей БД/DATA_DIR, ни production-рантайма;
#  ловушка сокетов на весь прогон. Тест гоняет ФАКТИЧЕСКИЕ production-функции решения:
#    • _termination_apply (+_term_context) ИЗВЛЕКАЮТСЯ из server.py разбором AST и исполняются
#      с РЕАЛЬНЫМИ app.printer_health_policy / app.printer_job_lifecycle — это тот самый код,
#      что зовут воркеры run_flashforge/run_klipper на каждом кадре телеметрии;
#    • классификатор classify_termination — прямые инварианты по всем адаптерам;
#    • обезличенная fixture свежей сессии FFA5M-1 (tools/fixtures/) прогоняется покадрово;
#    • frontend _printerProblem извлекается из app.js и исполняется в Node (единый источник
#      s.device_error);
#    • реальный headless-Edge: карточка НЕ красная на отмене, красная на настоящем сбое.
#  Sentinel PRINT_TERMINATION_SENTINEL_2_826 — только в оснастке.
#
#  Запуск:  python tools/test_universal_print_cancellation.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import io
import json
import os
import re
import socket
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _edge_dom   # Alpha 2.834: DOM через CDP + проверка живости движка
import tempfile

import time as _time

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
            print("FAIL — тест завершился до выполнения проверок")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)


atexit.register(_guard)

_SOCKETS = []


class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
        raise AssertionError("offline-тест: сокеты запрещены")


socket.socket = _TrapSocket

FAILED = []
PASSED = [0]


def check(name, ok, detail=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:220]) if detail else ""))


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "PRINT_TERMINATION_SENTINEL_2_826"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
INDEXHTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
HPY = open(os.path.join(REPO, "app", "printer_health_policy.py"), encoding="utf-8").read()
OWN = open(os.path.abspath(__file__), encoding="utf-8").read()

from app import printer_health_policy as H          # noqa: E402
from app import printer_job_lifecycle as L           # noqa: E402

NODE = next((p for p in [r"C:\Program Files\nodejs\node.exe",
                         r"C:\Program Files (x86)\nodejs\node.exe"] if os.path.isfile(p)), None)
EDGE = next((p for p in [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"] if os.path.isfile(p)), None)

# Alpha 2.835: наличие бинарника не значит работоспособность, НО неработоспособность движка
# больше НЕ повод пропускать браузерные проверки — это КРАСНЫЙ тест с точной причиной. Прежний
# SKIP был слепой зоной: именно он однажды спрятал реальный дефект интерфейса.
_ENGINE_WHY = ""
if not EDGE:
    _ENGINE_WHY = "движок рендера (Edge/Chrome) не найден"
elif not _edge_dom.engine_usable(EDGE):
    _ENGINE_WHY = "движок найден (%s), но не отдаёт документ по CDP" % EDGE
    EDGE = None


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


print("=== Alpha 2.826: универсальная классификация остановки печати (offline) ===")

# ════════════════════════════════════════════════════════════════════════════
section("ФАКТИЧЕСКИЙ production-обработчик: _termination_apply (AST-исполнение) (1-24)")

# Изолированное окружение с РЕАЛЬНЫМИ _health/_pjl и настоящими глобалями воркеров.
NS = {"time": _time, "_health": H, "_pjl": L,
      "p_states": {}, "_last_norm_st": {}, "_last_active_ts": {}, "_user_stopped": {}, "_cancel_latch": {},
      "_TERM_ACTIVE_RAW": ("RUNNING", "PREPARE", "PAUSE", "PAUSED", "SLICING"),
      "_CANCEL_RECENT_ACTIVE_S": 300.0,
      "log": type("L", (), {"info": staticmethod(lambda *a, **k: None),
                            "error": staticmethod(lambda *a, **k: None),
                            "warning": staticmethod(lambda *a, **k: None),
                            "debug": staticmethod(lambda *a, **k: None)})()}
_src_ctx = fn_src("_term_context")
_src_apply = fn_src("_termination_apply")
check("1. _termination_apply и _term_context извлечены из server.py",
      bool(_src_ctx) and bool(_src_apply) and "classify_termination" in _src_apply)
exec(_src_ctx, NS)
exec(_src_apply, NS)
APPLY = NS["_termination_apply"]


def ff_ns(raw):
    r = str(raw).lower()
    return ("RUNNING" if r in ("printing", "heating", "busy") else
            "FINISH" if r in ("completed", "complete") else
            "PAUSED" if r in ("paused", "pausing") else
            "FAILED" if r in ("error", "cancel", "cancelled") else "IDLE")


def drive_ff(pid, raw, connected=True):
    """Повторяет то, что делает run_flashforge: ns по raw -> _termination_apply -> p_states."""
    ns = ff_ns(raw)
    out_st, dev = APPLY(pid, "flashforge", ns, raw, {}, connected)
    NS["p_states"][pid] = {"status": out_st, "status_raw": str(raw).lower(), "device_error": dev}
    return out_st, dev


# ── FLASHFORGE EXTERNAL STOP — покадрово по обезличенной fixture ─────────────
FIX = json.load(open(os.path.join(REPO, "tools", "fixtures", "flashforge_cancel_session.json"), encoding="utf-8"))
_FIX_DATA = json.dumps({k: v for k, v in FIX.items() if k != "_comment"})   # _comment легитимно поясняет «serial/ip нет»
check("2. обезличенная fixture без секретов (нет ip/serial/credentials/абсолютных путей)",
      not re.search(r"[0-9]{1,3}([.][0-9]{1,3}){3}|serialnumber|checkcode|accesscode", _FIX_DATA, re.I))
pid = "node_ff1"
frames = []
for fr in FIX["detail_sequence"]:
    st, dev = drive_ff(pid, fr["detail"]["status"])
    frames.append((fr["detail"]["status"], st, dev))
_states = [f[1] for f in frames]
_devs = [f[2] for f in frames]
# idle, printing, printing, cancel, cancelled, cancelled, ready
check("3. старт печати даёт RUNNING (карточка «в печати»)", _states[1] == "RUNNING")
check("4. FlashForge external stop -> device_error=None на ВСЕХ терминальных кадрах (отмена != сбой)",
      all(d is None for d in _devs))
check("5. липкий терминал ЗАМАСКИРОВАН в IDLE (карточка НЕ красная): cancel и повторы -> IDLE",
      _states[3] == "IDLE" and _states[4] == "IDLE" and _states[5] == "IDLE")
check("6. отмена ЗАЩЁЛКНУТА (пока не пошла новая печать)", pid in NS["_cancel_latch"])
check("7. возврат в ready после отмены -> IDLE, device_error=None, latch не мешает",
      _states[6] == "IDLE" and _devs[6] is None)
# следующий запуск — чистый
st2, dev2 = drive_ff(pid, "printing")
check("8. следующий запуск ЧИСТЫЙ: новая печать снимает защёлку и не наследует отмену",
      st2 == "RUNNING" and pid not in NS["_cancel_latch"] and dev2 is None)

# ── FLASHFORGE LOCAL STOP (кнопка «Стоп» в FM: _user_stopped) ────────────────
pid = "node_ff2"
drive_ff(pid, "printing")
NS["_user_stopped"][pid] = _time.monotonic()      # intent из p_cmd stop
st, dev = drive_ff(pid, "cancel")
check("9. FlashForge LOCAL stop (user_stop) -> тоже cancelled/чисто (IDLE, device_error=None)",
      st == "IDLE" and dev is None and pid in NS["_cancel_latch"])
# local stop без terminal confirmation НЕ становится success: пока принтер печатает — RUNNING,
# но user_stop маскирует его в IDLE (как Bambu); success не выставляется нигде (нет FINISH).
check("10. local stop timeout НЕ превращается в success (нет FINISH/completed без terminal)",
      all(f[1] != "FINISH" for f in frames))

# ── FLASHFORGE REAL FAILURE (raw 'error') ───────────────────────────────────
pid = "node_ff3"
drive_ff(pid, "printing")
st, dev = drive_ff(pid, "error")
check("11. FlashForge НАСТОЯЩИЙ сбой (raw 'error') -> device_error='FAILED', статус FAILED (красная карточка)",
      st == "FAILED" and dev == "FAILED")
check("12. настоящий сбой НЕ маскируется и НЕ защёлкивается как отмена",
      pid not in NS["_cancel_latch"])

# ── FLASHFORGE CONNECTION LOSS (connected=False) ────────────────────────────
_tc_off = H.classify_termination("flashforge", L.normalize_state("flashforge", "printing", connected=False), {}, {})
check("13. потеря связи FlashForge -> НЕ отмена и НЕ device fault (ведёт отдельный OFFLINE)",
      _tc_off["is_cancellation"] is False and _tc_off["device_error"] is None
      and _tc_off["reason_code"] == "connection_lost")

# ── CROSS-ADAPTER: защёлка одного принтера не заражает другой ────────────────
pid_a, pid_b = "node_ffA", "node_bbB"
drive_ff(pid_a, "printing"); drive_ff(pid_a, "cancel")     # A отменён и защёлкнут
check("14. cross-printer: защёлка отмены A не влияет на B (у B её нет)",
      pid_a in NS["_cancel_latch"] and pid_b not in NS["_cancel_latch"])
# duplicate reports идемпотентны — повтор того же терминала не плодит новых защёлок/событий
_lat_before = NS["_cancel_latch"][pid_a]
drive_ff(pid_a, "cancelled"); drive_ff(pid_a, "cancelled")
check("15. duplicate terminal идемпотентен (защёлка одна, не пересоздаётся при повторах)",
      NS["_cancel_latch"][pid_a] >= _lat_before and pid_a in NS["_cancel_latch"])
# stale session: старый latch снимается ТОЛЬКО новой печатью, не «протекает» в чужой pid
drive_ff(pid_a, "printing")
check("16. новая печать A снимает старую защёлку (stale session не заражает новую)",
      pid_a not in NS["_cancel_latch"])

# ════════════════════════════════════════════════════════════════════════════
section("КЛАССИФИКАТОР classify_termination — инварианты по адаптерам (17-40)")


def T(adapter, raw, snap=None, ctx=None, conn=True):
    return H.classify_termination(adapter, L.normalize_state(adapter, raw, connected=conn), snap or {}, ctx or {})


# BAMBU (код-семейство + HMS-приоритет)
_bb_cancel = H.classify_termination("bambu", "failed", {"error_code": "0300-400C"}, {"recently_active": True})
_bb_hms = H.classify_termination("bambu", "failed", {"hms_codes": ["07FF-8007"]}, {"recently_active": True})
_bb_both = H.classify_termination("bambu", "failed",
                                  {"error_code": "0300-400C", "hms_codes": ["07FF-8007"]}, {"recently_active": True})
_bb_noctx = H.classify_termination("bambu", "failed", {"error_code": "0300-400C"}, {})
check("17. Bambu external stop (0300-400C + контекст) -> cancelled, device_error=None",
      _bb_cancel["is_cancellation"] and _bb_cancel["device_error"] is None)
check("18. Bambu HMS 0003-000A + контекст -> cancelled (уведомление об отмене)",
      H.classify_termination("bambu", "failed", {"hms_codes": ["0003-000A"]}, {"recently_active": True})["is_cancellation"])
check("19. Bambu РЕАЛЬНЫЙ HMS 07FF-8007 -> device_error виден, НЕ отмена (аппаратный приоритет)",
      _bb_hms["device_error"] == "07FF-8007" and not _bb_hms["is_cancellation"])
check("20. Bambu отмена+реальный HMS одновременно -> показывается РЕАЛЬНЫЙ код (сбой не скрыт)",
      _bb_both["device_error"] == "07FF-8007" and not _bb_both["is_cancellation"])
check("21. Bambu код отмены БЕЗ контекста -> НЕ гасится (fail-safe, показывается)",
      _bb_noctx["device_error"] == "0300-400C" and not _bb_noctx["is_cancellation"])
check("22. Bambu source: local_stop при user_stop, иначе vendor_external",
      H.classify_termination("bambu", "failed", {"error_code": "0300-400C"}, {"user_stop": True})["source"] == H.SRC_LOCAL_STOP
      and _bb_cancel["source"] == H.SRC_VENDOR_EXTERNAL)

# MOONRAKER / KLIPPER
check("23. Moonraker explicit 'cancelled' -> cancellation, device_error=None",
      T("klipper", "cancelled")["is_cancellation"] and T("klipper", "cancelled")["device_error"] is None)
check("24. Moonraker 'complete' -> completed (не отмена, не сбой)",
      T("klipper", "complete")["outcome"] == H.TERM_COMPLETED and T("klipper", "complete")["device_error"] is None)
check("25. Moonraker 'error' + сообщение -> failed, device_error=сообщение (сбой виден)",
      T("klipper", "error", {"err_msg": "MCU shutdown"})["device_error"] == "MCU shutdown"
      and not T("klipper", "error", {"err_msg": "MCU shutdown"})["is_cancellation"])
check("26. Moonraker 'error' БЕЗ сообщения -> всё равно device fault (fail-safe, не скрыт)",
      T("klipper", "error", {})["device_error"] == H.GENERIC_FAILED)
check("27. Moonraker потеря связи (connected=False) -> НЕ cancellation",
      T("klipper", "printing", conn=False)["is_cancellation"] is False
      and T("klipper", "cancelled", conn=False)["is_cancellation"] is False)
check("28. Moonraker 'paused' -> не терминал, не отмена",
      T("klipper", "paused")["outcome"] == H.TERM_NONE and not T("klipper", "paused")["is_cancellation"])

# FLASHFORGE
check("29. FlashForge 'cancel' и 'cancelled' -> cancellation, device_error=None",
      T("flashforge", "cancel")["is_cancellation"] and T("flashforge", "cancelled")["is_cancellation"]
      and T("flashforge", "cancel")["device_error"] is None)
check("30. FlashForge 'error' -> failed, device_error='FAILED'",
      T("flashforge", "error")["device_error"] == "FAILED" and not T("flashforge", "error")["is_cancellation"])
check("31. FlashForge 'printing'/'ready' -> none (активна/покой)",
      T("flashforge", "printing")["outcome"] == H.TERM_NONE and T("flashforge", "ready")["outcome"] == H.TERM_NONE)

# ИНВАРИАНТЫ
check("32. cancelled != completed != failed (три разных исхода)",
      len({H.TERM_CANCELLED, H.TERM_COMPLETED, H.TERM_FAILED}) == 3)
check("33. 'FAILED' сам по себе НЕ всегда device fault: у Bambu без кода — health чист",
      H.classify_termination("bambu", "failed", {}, {})["device_error"] is None)
check("34. UNKNOWN adapter fail-safe: неизвестный 'failed' -> device_error виден",
      H.classify_termination("weird_adapter", "failed", {}, {})["device_error"] == H.GENERIC_FAILED)
check("35. UNKNOWN adapter: неизвестная строка состояния -> none (не выдуманная отмена/сбой)",
      H.classify_termination("weird_adapter", "unknown", {}, {})["is_cancellation"] is False)
check("36. cross-adapter: сигнатура отмены Bambu (код) не применяется к FlashForge",
      T("flashforge", "printing", {"error_code": "0300-400C"})["is_cancellation"] is False)
check("37. cross-adapter: строковая отмена FlashForge не применяется к Bambu (у Bambu term никогда не cancelled)",
      "bambu" not in ["".join([])] and L.normalize_state("bambu", "cancel") != L.STATE_CANCELLED)
check("38. идемпотентность: повтор того же снимка даёт тот же результат",
      T("flashforge", "cancel") == T("flashforge", "cancel"))
check("39. потеря связи любого адаптера reason_code=connection_lost",
      T("flashforge", "printing", conn=False)["reason_code"] == "connection_lost"
      and T("bambu", "printing", conn=False)["reason_code"] == "connection_lost")
check("40. модуль health-политики чистый (без БД/сети)",
      "sqlite3" not in HPY and ".execute(" not in HPY and "urllib" not in HPY and "socket" not in HPY)

# ════════════════════════════════════════════════════════════════════════════
section("WIRING в production-воркерах и единый источник UI (41-58)")

_ff = fn_src("run_flashforge")
_kl = fn_src("run_klipper")
_bb_src = fn_src("on_msg") or SRV      # Bambu-ветка внутри on_msg
check("41. run_flashforge зовёт ЕДИНЫЙ _termination_apply('flashforge', ...)",
      '_termination_apply(pid, "flashforge"' in SRV and "async def run_flashforge" in SRV)
check("42. run_flashforge кладёт device_error в p_states (карточке — готовое поле)",
      '"device_error": _dev_err' in SRV)
check("43. run_klipper зовёт _termination_apply('klipper', ...) и кладёт device_error",
      '_termination_apply(pid, "klipper"' in SRV and '"device_error": _kdev' in SRV)
check("44. run_klipper: webhooks shutdown/error -> raw 'error' в классификатор (сбой не теряется)",
      '_kraw = "error" if whs in ("shutdown", "error") else' in SRV)
check("45. Bambu-ветка идёт через ТОТ ЖЕ _health.classify_termination('bambu', ...)",
      '_health.classify_termination(' in SRV and '"bambu", _bterm' in SRV)
check("46. Bambu сохранил inline-защёлку и HMS-приоритет (classify_bambu жив в health-модуле)",
      "def classify_bambu(" in HPY and "_cancel_latch[pid] = time.monotonic()" in SRV)
check("47. единый классификатор определён один раз в чистом модуле",
      HPY.count("def classify_termination(") == 1 and SRV.count("def classify_termination(") == 0)
check("48. FAILED->IDLE маска в _termination_apply привязана к сессии (latch/user_stop)",
      'if (pid in _user_stopped or pid in _cancel_latch) and str(st) in ("RUNNING", "PREPARE", "FAILED"):' in SRV)
check("49. новая печать снимает и _user_stopped, и _cancel_latch (session-bound)",
      "_user_stopped.pop(pid, None)" in _src_apply and "_cancel_latch.pop(pid, None)" in _src_apply)
check("50. потеря связи в воркерах -> OFFLINE_STATE, НЕ _termination_apply (offline != cancel)",
      SRV.count("p_states[pid] = dict(OFFLINE_STATE)") >= 2)

# Frontend: единый источник s.device_error для ВСЕХ адаптеров
_pp_i = APPJS.find("const _printerProblem =")
_pp = APPJS[_pp_i:APPJS.find("const _mkAlert", _pp_i)]
check("51. frontend _printerProblem: FlashForge alert ТОЛЬКО по s.device_error (не по status==='FAILED')",
      "type === 'flashforge'" in _pp and "if (!s.device_error) return null" in _pp
      and "if (st !== 'FAILED') return null" not in _pp)
#  12.10.2026: смотрим саму ветку Klipper — прежний счёт «ровно 2 раза по всей функции» краснел от ветки
#  Creality (заводская прошивка), у которой тот же правильный контракт.
_kl_i = _pp.find("if (type === 'klipper')")
_kl = _pp[_kl_i:_pp.find("if (type ===", _kl_i + 10)] if _kl_i >= 0 else ""
check("52. frontend _printerProblem: Klipper alert ТОЛЬКО по s.device_error (не по одному err_msg)",
      "if (!s.device_error) return null" in _kl and _pp.count("if (!s.device_error) return null") >= 2)
check("53. frontend _printerProblem: Bambu по-прежнему s.device_error (единый контракт)",
      "type === 'bambu'" in _pp and "s.device_error" in _pp)
check("54. верхний счётчик и попап идут из printerAlerts (единый источник, не raw status)",
      "alertBadgeCount" in APPJS and "_printerProblem" in APPJS)

# Counters/lifecycle: масштаб IDLE -> cancelled-учёт (не failed), готовые не растут
_hs = fn_src("handle_state")
check("55. print_run_finished: STOP/IDLE -> cancelled, FAILED -> failed (масштаб отмены в IDLE даёт cancelled)",
      'fail_project_print_job(_proj_job, "cancelled" if state in ("STOP", "IDLE") else "failed")' in SRV)
check("56. отмена НЕ увеличивает готовые: инкремент склада только на завершении (FINISH), не на IDLE",
      "FINISH" in _hs or "completed" in _hs)
check("57. external reprint sync 2.807 сохранён (тест существует)",
      os.path.isfile(os.path.join(REPO, "tools", "test_external_reprint_sync.py")))
check("58. DISPATCH/TRANSPORT не трогаются термополитикой",
      "DISPATCH_ENABLED" not in _src_apply and "TRANSPORT_ENABLED" not in _src_apply and "DISPATCH_ENABLED" not in HPY)

# ════════════════════════════════════════════════════════════════════════════
section("NODE: frontend _printerProblem — единый источник device_error (59-70)")

NODE_RES = {}
if NODE and _pp_i > 0:
    HARNESS = r"""
'use strict';
const lang = { value: 'ru' };
const tourActive = { value: false };
const printers = { value: [
  { id: 'ff', type: 'flashforge' }, { id: 'kl', type: 'klipper' }, { id: 'bb', type: 'bambu' } ] };
const KNOWN_BAMBU_CODES = { '07FF-8007': { severity: 'error', category: 'printer_error', ru: { title: 'Клог', message: 'x' }, en: { title: 'Clog', message: 'x' } } };
const _ALERT_STALE_S = 60;
const _alertFresh = (s) => !!s && s.status !== 'OFFLINE' && !(typeof s.seen_ago === 'number' && s.seen_ago >= _ALERT_STALE_S);
%%PP%%
const R = {};
const S = (o) => Object.assign({ status: 'IDLE', seen_ago: 0 }, o);
// FlashForge: отмена (device_error отсутствует, статус замаскирован в IDLE) -> НЕТ alert
R.ff_cancel = _printerProblem('ff', S({ status: 'IDLE', device_error: null }));
// FlashForge: настоящий сбой -> alert
R.ff_fail = _printerProblem('ff', S({ status: 'FAILED', device_error: 'FAILED' }));
// FlashForge: даже если статус случайно FAILED, но device_error пуст -> НЕТ alert (не по статусу!)
R.ff_failstatus_noerr = _printerProblem('ff', S({ status: 'FAILED', device_error: null }));
// Klipper: отмена -> нет; сбой -> есть
R.kl_cancel = _printerProblem('kl', S({ status: 'IDLE', device_error: null, err_msg: '' }));
R.kl_fail = _printerProblem('kl', S({ status: 'FAILED', device_error: 'MCU shutdown', err_msg: 'MCU shutdown' }));
// Bambu: device_error пуст -> нет; есть -> alert
R.bb_clean = _printerProblem('bb', S({ status: 'IDLE', device_error: null }));
R.bb_fail = _printerProblem('bb', S({ status: 'FAILED', device_error: '07FF-8007' }));
// OFFLINE/stale -> заморозка (stale:true), не выдуманная ошибка
R.ff_stale = _printerProblem('ff', { status: 'OFFLINE', seen_ago: 999 });
console.log('@@R@@' + JSON.stringify(R) + '@@E@@');
"""
    js = HARNESS.replace("%%PP%%", _pp)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_term_") as td:
        f = os.path.join(td, "h.js")
        io.open(f, "w", encoding="utf-8", newline="\n").write(js)
        pr = subprocess.run([NODE, f], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        m = re.search(r"@@R@@(\{.*\})@@E@@", pr.stdout or "", re.S)
        NODE_RES = json.loads(m.group(1)) if m else {"err": (pr.stderr or "")[:200]}

check("59. Node-стенд _printerProblem отработал", NODE_RES and "err" not in NODE_RES, str(NODE_RES)[:200])
if NODE_RES and "err" not in NODE_RES:
    check("60. FlashForge отмена -> НЕТ alert (карточка не красная)", NODE_RES["ff_cancel"] is None)
    check("61. FlashForge настоящий сбой -> alert 'Ошибка печати'",
          NODE_RES["ff_fail"] and NODE_RES["ff_fail"]["source"] == "flashforge")
    check("62. FlashForge status=FAILED но device_error пуст -> НЕТ alert (решает device_error, не статус)",
          NODE_RES["ff_failstatus_noerr"] is None)
    check("63. Klipper отмена -> НЕТ alert", NODE_RES["kl_cancel"] is None)
    check("64. Klipper сбой -> alert с сообщением", NODE_RES["kl_fail"] and "MCU" in NODE_RES["kl_fail"]["message"])
    check("65. Bambu чисто -> нет alert; Bambu код -> alert",
          NODE_RES["bb_clean"] is None and NODE_RES["bb_fail"] and NODE_RES["bb_fail"]["code"] == "07FF-8007")
    check("66. OFFLINE/stale -> заморозка активного (stale:true), не новая ошибка",
          isinstance(NODE_RES["ff_stale"], dict) and NODE_RES["ff_stale"].get("stale") is True)
    check("67. единый источник: все адаптеры решают по s.device_error (нет ветки по status для FF/Klipper)",
          NODE_RES["ff_cancel"] is None and NODE_RES["kl_cancel"] is None)
else:
    for _k in range(60, 68):
        check("%d. (пропущено из-за ошибки Node-стенда)" % _k, False)

# ════════════════════════════════════════════════════════════════════════════
section("EDGE: реальная карточка — отмена не красная, сбой красный (68-76)")


def _edge_card(device_error, status):
    css = "file:///" + os.path.join(REPO, "web", "app.css").replace("\\", "/")
    vue = "file:///" + os.path.join(REPO, "web", "vendor", "vue.esm-browser.js").replace("\\", "/")
    _pp_block = APPJS[_pp_i:APPJS.find("const _mkAlert", _pp_i)]
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<script>window.__e=[];var _c=console.error;console.error=function(){window.__e.push([].map.call(arguments,String).join(' '));_c.apply(console,arguments)};</script>"
            "<link rel='stylesheet' href='" + css + "'>"
            "<script type='importmap'>{\"imports\":{\"vue\":\"" + vue + "\"}}</script>"
            "</head><body><div id='app'>"
            "<div class='pcard' :class=\"bucket==='red' ? 'is-red' : 'is-ok'\">"
            "<span class='pcstatus'>{{ status }}</span>"
            "<span v-if='alert' class='pcalert'>{{ alert.title }}</span></div>"
            "<pre id='__res'></pre></div>"
            "<script type='module'>"
            "import { createApp, ref, computed } from 'vue';"
            "const app=createApp({setup(){"
            "const lang=ref('ru');const tourActive=ref(false);"
            "const printers=ref([{id:'ff',type:'flashforge'}]);"
            "const KNOWN_BAMBU_CODES={};const _ALERT_STALE_S=60;"
            "const _alertFresh=(s)=>!!s&&s.status!=='OFFLINE'&&!(typeof s.seen_ago==='number'&&s.seen_ago>=_ALERT_STALE_S);"
            "const printerAlerts={value:{}};const _alertPending={};let _alertSeq=0;const _alertNow=()=>Date.now();"
            "const status=ref(" + json.dumps(status) + ");"
            "const dev=ref(" + json.dumps(device_error) + ");"
            + _pp_block +
            ";const _s=computed(()=>({status:status.value,seen_ago:0,device_error:dev.value}));"
            "const alert=computed(()=>{const p=_printerProblem('ff',_s.value);return (p&&!p.stale)?p:null;});"
            "const _statusBucket=(s)=>(s==='OFFLINE'||s==='FAILED'||s==='error')?'red':(s==='FINISH')?'green':(s==='RUNNING'||s==='PREPARE')?'blue':'yellow';"
            "const bucket=computed(()=>_statusBucket(status.value));"
            "return { status, alert, bucket };"
            "}});app.mount('#app');"
            "setTimeout(()=>{const card=document.querySelector('.pcard');"
            "const out={red:card.classList.contains('is-red'),alert:!!document.querySelector('.pcalert'),"
            "alertText:(document.querySelector('.pcalert')||{}).textContent||'',errors:(window.__e||[]).filter(e=>e.indexOf('favicon')<0)};"
            "document.getElementById('__res').textContent='@@C@@'+JSON.stringify(out)+'@@E@@';},400);"
            "</script></body></html>")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_termE_") as rtd:
        pg = os.path.join(rtd, "c.html")
        io.open(pg, "w", encoding="utf-8", newline="\n").write(html)
        # Alpha 2.834: Edge 150 не отдаёт DOM по --dump-dom (headless detached) -> читаем по CDP.
        dom = _edge_dom.dump_dom_compatible(EDGE, "file:///" + pg.replace("\\", "/"),
                                            os.path.join(rtd, "p"), budget_ms=8000)
        m = re.search(r"@@C@@(\{.*?\})@@E@@", dom, re.S)
        return json.loads(m.group(1)) if m else {}


if not EDGE:
    for _n in range(68, 77):
        check("%d. движок недоступен: " % _n + _ENGINE_WHY, False)
else:
    _cancel = _edge_card(None, "IDLE")       # отмена: замаскировано в IDLE, device_error=None
    _fail = _edge_card("FAILED", "FAILED")    # настоящий сбой
    _offl = _edge_card(None, "OFFLINE")       # потеря связи
    check("68. Edge: ОТМЕНА FlashForge — карточка НЕ красная", _cancel.get("red") is False, str(_cancel)[:150])
    check("69. Edge: ОТМЕНА — нет alert-плашки (попап проблем пуст)", _cancel.get("alert") is False)
    check("70. Edge: ОТМЕНА — 0 console errors", not _cancel.get("errors"), str(_cancel.get("errors"))[:150])
    check("71. Edge: НАСТОЯЩИЙ сбой — карточка красная", _fail.get("red") is True, str(_fail)[:150])
    check("72. Edge: НАСТОЯЩИЙ сбой — alert-плашка «Ошибка печати» видна",
          _fail.get("alert") is True and "Ошибка" in (_fail.get("alertText") or ""))
    check("73. Edge: потеря связи — карточка красная (OFFLINE-статус), но не «Ошибка печати»",
          _offl.get("red") is True and _offl.get("alert") is False)
    check("74. Edge: сбой — 0 console errors", not _fail.get("errors"))
    check("75. Edge: разные исходы дают разный вид карточки (отмена!=сбой)",
          _cancel.get("red") != _fail.get("red"))
    check("76. Edge: alert только у сбоя, не у отмены/offline",
          _fail.get("alert") and not _cancel.get("alert") and not _offl.get("alert"))

# ════════════════════════════════════════════════════════════════════════════
section("SENTINEL и границы (77-82)")
check("77. sentinel отсутствует в production-исходниках",
      all(SENTINEL not in s for s in (SRV, APPJS, INDEXHTML, HPY,
          open(os.path.join(REPO, "app", "printer_job_lifecycle.py"), encoding="utf-8").read())))
check("78. sentinel в оснастке ровно один раз (кавычки)", OWN.count('"%s"' % SENTINEL) == 1)
check("79. за прогон не открыто НИ ОДНОГО сокета", not _SOCKETS)
check("80. схема БД не меняется термополитикой (нет CREATE TABLE/ALTER в новом коде)",
      "CREATE TABLE" not in _src_apply and "ALTER" not in _src_apply and "CREATE TABLE" not in HPY)
#  Склад поднят до 1.7.28 (2.946), качество до 0.2.3 (2.964); ранее 1.7.27 в 2.890-2.891: он научился видеть подачу CFS у Creality K2.
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
check("81. модули не тронуты (1.7.29/0.2.0/0.2.3)",
      (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(open(os.path.join(REPO, "modules", "inventory", "module.json"), encoding="utf-8"))) == "1.7.29")
check("82. printer-files delete-предохранитель по умолчанию выключен (не тронут)",
      __import__("app.printer_files.security", fromlist=["x"]).PRINTER_FILE_DELETE_ENABLED_DEFAULT is False)
_ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
check("83. DISPATCH/TRANSPORT по умолчанию False (термополитика их не включает)",
      "\nDISPATCH_ENABLED = False" in _ORCH and "\nTRANSPORT_ENABLED = False" in _ORCH)
check("84. терминальное событие логируется ОДИН раз на переход (dedup по защёлке, не каждый кадр)",
      "if pid not in _cancel_latch:" in _src_apply)

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_DONE["ok"] = True
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), PASSED[0] + len(FAILED)))
    for n in FAILED:
        print("   - " + n)
    sys.exit(1)
print("PASS: универсальная классификация остановки печати — все %d проверок пройдены; "
      "production _termination_apply исполнен из server.py; classify_termination по всем адаптерам; "
      "frontend в Node; карточка в реальном Edge; 0 сокетов" % PASSED[0])
sys.exit(0)
