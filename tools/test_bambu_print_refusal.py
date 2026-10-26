# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""15.09.2026 — принтер Bambu отверг команду печати: причина словами принтера и запасное имя файла.

ЗАЧЕМ. Владелец 15.09.2026 (фото панели отправок): P1S не принял файл
«T72 E-5 (1-6) B39_PETG_2h14m.gcode.3mf» ни в одном формате пути, программа советовала
«выставить поколение вручную», а следующий файл тот же принтер напечатал. Ответ прошивки и код
ошибки при этом писались только в журнал — владелец причины не видел.

ЧТО СДЕЛАНО. (1) Причина отказа (reason из ответа прошивки на project_file и код print_error,
появившийся после команды) запоминается на каждую попытку и уходит в панель отправок вместе с
текстом кода из официальной таблицы Bambu. (2) Если все форматы отвергнуты, файл отправляется
ещё раз под запасным именем по правилу Bambu Studio (PrintJob.cpp: пробел и <>[]:/\\|?*" -> «_»,
ряды «_» схлопнуты, длина < 100) и строже — всё, что не буква/цифра/точка/дефис, тоже «_».
Учёт печати ведётся по исходному имени; norm() отбрасывает всё, кроме букв и цифр, поэтому задача
и печать сопоставляются как прежде.

ЧТО ДОКАЗЫВАЕТСЯ. Чистая функция имени (в т. ч. на имени с фото владельца и на правиле Studio);
исполнением — НАСТОЯЩИЙ _bambu_send_project с подставными publish/outcome: причина и код
собираются по каждой схеме; текст причины с кодом из таблицы; по исходнику — запасная отправка
стоит ПОСЛЕ отказа и ДО хуков, память отказов сбрасывается перед каждой отправкой.

БЕЗОПАСНОСТЬ. server.py не импортируется целиком, сеть и принтеры не используются.

Запуск: python tools/test_bambu_print_refusal.py   (0 = все проверки пройдены)
"""
import ast
import io
import json
import os
import re
import sys
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from app import printer_health_policy as H  # noqa: E402
from app import bambu_start_policy as B  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        print("FAIL — %s%s" % (name, ("  :: %s" % (str(detail)[:300],)) if detail else ""))


SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_TREE = ast.parse(SRC)


def _fn(name):
    for node in _TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SRC, node)
    raise AssertionError("не найдена функция %r" % name)


NORM_RE = re.compile(r'[^a-zA-Z0-9]')
norm = lambda s: NORM_RE.sub('', s).lower() if s else ""   # noqa: E731 — как в server.py

# ── A. запасное имя ─────────────────────────────────────────────────────────────────────────
print("--- A. запасное имя файла ---")
NS = {"os": os, "re": re}
exec(_fn("_bambu_safe_upload_name"), NS)   # noqa: S102 — свой исходник
safe = NS["_bambu_safe_upload_name"]
OWNER = "T72 E-5 (1-6) B39_PETG_2h14m.gcode.3mf"
check("A1. ФОТО ВЛАДЕЛЬЦА: пробелы и скобки ушли, буквы, цифры и дефисы на месте, расширение цело",
      safe(OWNER) == "T72_E-5_1-6_B39_PETG_2h14m.gcode.3mf", safe(OWNER))
check("A2. учёт не теряет файл: norm() исходного и запасного имени совпадают",
      norm("T72 E-5 (1-6) B39_PETG_2h14m") == norm("T72_E-5_1-6_B39_PETG_2h14m") == "t72e516b39petg2h14m")
check("A3. правило Bambu Studio: <>[]:/\\|?*\" и пробел -> «_», ряды «_» схлопнуты",
      safe('a<b>c:d|e?f*g"h[i]j  k.3mf') == "a_b_c_d_e_f_g_h_i_j_k.3mf", safe('a<b>c:d|e?f*g"h[i]j  k.3mf'))
check("A4. буквы любого алфавита сохраняются (прошивка принимает UTF-8)",
      safe("Кронштейн v2 (новый).gcode") == "Кронштейн_v2_новый.gcode", safe("Кронштейн v2 (новый).gcode"))
check("A5. уже безопасное имя не меняется — запасная отправка не нужна",
      safe("plain_ok-1.gcode.3mf") == "plain_ok-1.gcode.3mf" and safe("x.gcode") == "x.gcode")
check("A6. пустое после уборки имя — «print», не пустая строка", safe("((( ))).3mf") == "print.3mf" and safe("") == "print")
_long = safe("x" * 150 + ".gcode.3mf")
check("A7. длина ограничена правилом Studio (< 100), расширение не отрезано", len(_long) < 100 and _long.endswith(".gcode.3mf"))
check("A8. путь срезается до имени файла", safe(r"C:\tmp\a b.gcode") == "a_b.gcode")

# ── B. НАСТОЯЩИЙ перебор схем: причина и код запоминаются ────────────────────────────────────
print("--- B. перебор схем: причина отказа запоминается ---")
S2 = {"os": os, "re": re, "json": json, "time": types.SimpleNamespace(monotonic=lambda: 100.0, sleep=lambda s: None,
                                                                     perf_counter=lambda: 0.0),
      "_bstart": B, "_health": H, "_exc_brief": lambda: "?",
      "log": types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None, warning=lambda *a, **k: None),
      "_bambu_cmd_ack": {}, "_bambu_last_refusal": {}, "_bambu_ok_scheme": {},
      "p_states": {"p1": {"status": "IDLE", "print_error": 0, "mc_err": "0", "hms_n": 0, "nozzle_count": 1, "stage": -1}},
      "_sniff_sanitize": lambda o, _d=0: o,
      "_printer_gen": lambda pid: "auto",
      "_bambu_print_started": lambda pid: False,
      "_bambu_busy_before_start": lambda pid, wait=3.0: "",
      "_bambu_busy_now": lambda pid: False,
      "_bambu_request_report": lambda pid: True,
      "_bambu_wait_started": lambda pid, seconds: False,
      #  16.10.2026 (R-138): перед первой командой отправка запоминает стадию принтера (база признака старта).
      "_bambu_stage_mark": lambda pid: None,
      }
SENT = []
def _publish(pid, topic, payload, attempts=10, delay=0.6):
    SENT.append(json.loads(payload)["print"])
    d = json.loads(payload)["print"]
    if d.get("command") == "project_file":
        #  прошивка отвечает отказом с причиной и поднимает print_error 0500-400A («имя файла не поддерживается»)
        S2["_bambu_cmd_ack"][pid] = {"command": "project_file", "result": "fail", "reason": "unsupported file name", "ts": 100.0}
        S2["p_states"][pid]["print_error"] = 0x0500400A
    return True
S2["_bambu_publish"] = _publish
S2["_bambu_print_outcome"] = lambda pid, b_pe, b_mce, b_hms, timeout=9.0, since=None, first=False: "fail"
for name in ("_norm_bambu_error_code", "_SCHEME_URL", "_bambu_scheme_order", "_bambu_refusal_note", "_bambu_refusal_reason", "_bambu_send_project"):
    seg = None
    for node in _TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.Assign)):
            nm = node.name if isinstance(node, ast.FunctionDef) else getattr(node.targets[0], "id", "")
            if nm == name:
                seg = ast.get_source_segment(SRC, node)
    assert seg, "нет %s" % name
    exec(seg, S2)   # noqa: S102 — свой исходник
check("B1. исходники функций найдены и исполняются", callable(S2["_bambu_send_project"]) and callable(S2["_bambu_refusal_reason"]))
ok = S2["_bambu_send_project"]("p1", "SER1", {"sequence_id": "0", "command": "project_file", "param": "Metadata/plate_1.gcode", "subtask_name": "T72"}, OWNER)
rf = S2["_bambu_last_refusal"].get("p1") or {}
#  16.10.2026 (R-114): односопельному brtc://emmc больше не предлагается (это путь H2D; ha-bambulab шлёт
#  X1/P1/A1 только file:///sdcard) — схем три: sd, ftp, mnt. Имя в url — то, что передали отправке.
check("B2. все схемы отвергнуты -> False; команда ушла в каждой из трёх схем односопельного (sd, ftp, mnt), "
      "без brtc://emmc",
      ok is False and [s["url"] for s in SENT if s.get("command") == "project_file"]
      == ["file:///sdcard/" + OWNER, "ftp:///" + OWNER, "file:///mnt/sdcard/" + OWNER], [s.get("url") for s in SENT][:5])
_ord = S2["_bambu_scheme_order"]
S2["p_states"]["p2"] = {"nozzle_count": 2}
check("B2b. порядок схем: односопельный — sd, ftp, mnt; двухсопельный (H2D) — по-прежнему ftp, emmc, sd, mnt",
      _ord("p1") == ["sd", "ftp", "mnt"] and _ord("p2") == ["ftp", "emmc", "sd", "mnt"], (_ord("p1"), _ord("p2")))
check("B3. причина отказа словами прошивки запомнена один раз (не четыре) и код print_error 0500-400A",
      rf.get("reasons") == ["unsupported file name"] and rf.get("code") == "0500-400A", rf)
H.ERROR_TEXT_LOOKUP = lambda code: ({"ru": "Имя файла не поддерживается. Переименуйте и перезапустите задание печати.",
                                     "en": "The file name is not supported. Please rename and restart the task."}
                                    if code == "0500-400A" else None)
msg = S2["_bambu_refusal_reason"]("p1")
check("B4. текст для панели: причина принтера + текст кода из официальной таблицы + код, по-русски",
      msg.startswith("Принтер отклонил команду печати: unsupported file name. Имя файла не поддерживается.") and "[0500-400A]" in msg, msg)
check("B5. текст не длиннее 200 знаков (панель отправок режет длиннее)", len(msg) <= 200, len(msg))
H.ERROR_TEXT_LOOKUP = None
check("B6. без таблицы — причина и код, без выдуманного текста",
      S2["_bambu_refusal_reason"]("p1") == "Принтер отклонил команду печати: unsupported file name. [0500-400A] · The printer refused the print command: unsupported file name. [0500-400A]",
      S2["_bambu_refusal_reason"]("p1"))
check("B7. принтер ничего не объяснил — пусто (останется прежний совет про поколение)",
      S2["_bambu_refusal_reason"]("нет-такого") == "")
S2["_bambu_last_refusal"].clear(); S2["_bambu_cmd_ack"].clear(); S2["p_states"]["p1"]["print_error"] = 0
def _publish_ok(pid, topic, payload, attempts=10, delay=0.6):
    S2["_bambu_cmd_ack"][pid] = {"command": "project_file", "result": "success", "reason": "", "ts": 100.0}
    return True
S2["_bambu_publish"] = _publish_ok
S2["_bambu_print_outcome"] = lambda pid, b_pe, b_mce, b_hms, timeout=9.0, since=None, first=False: "ok"
check("B8. принятая команда: отказов нет, схема запомнена",
      S2["_bambu_send_project"]("p1", "SER1", {"sequence_id": "0", "command": "project_file"}, "ok.3mf") is True
      and not S2["_bambu_last_refusal"].get("p1") and S2["_bambu_ok_scheme"].get("p1") == "sd")

# ── C. НАСТОЯЩАЯ отправка файла (16.10.2026, R-114): имя на принтере — безопасное с первой попытки ──
print("--- C. отправка файла: безопасное имя с первой попытки, причина в ошибке ---")
import zipfile  # noqa: E402
_zb = io.BytesIO()
with zipfile.ZipFile(_zb, "w") as _z:
    _z.writestr("Metadata/plate_1.gcode", "; g\nG28\n")
FAKE3MF = _zb.getvalue()
UPL, CMDS, HOOKS, STASH = [], [], [], []
S3 = {"os": os, "re": re, "json": json, "io": io, "zipfile": zipfile,
      "time": types.SimpleNamespace(monotonic=lambda: 100.0, sleep=lambda s: None, perf_counter=lambda: 0.0),
      "log": types.SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None,
                                   warning=lambda *a, **k: None, error=lambda *a, **k: None),
      "_exc_brief": lambda: "?", "_health": H, "_bstart": B,
      "server_print": {}, "_server_print_ts": {}, "_user_stopped": {},
      "print_run_events": types.SimpleNamespace(stash_dispatch=lambda *a, **k: None),
      "bambu_serials": {"p1": "SER1"}, "p_states": {"p1": {"nozzle_count": 1}},
      "_bambu_ok_scheme": {}, "_bambu_last_refusal": {}, "BAMBU_SLOW_MBPS": 0.5,
      #  подача — слот AMS 0 (выбор подачи проверяет tools/test_bambu_print_payload.py)
      "_bambu_goes_external": lambda pid, slot, fd: (False, True, None),
      "_bambu_resolve_ams": lambda pid, slot, fd: (True, [0], [{"ams_id": 0, "slot_id": 0}]),
      #  16.10.2026 (R-006, проверка пакета): сопло слота у двухсопельного — проверяет test_bambu_print_payload.py
      "_bambu_cross_nozzle": lambda pid, fd, mapping=None, ams_slot=None: None,
      "_bambu_wire_mapping": lambda m: list(m), "_apply_bambu_print_opts": lambda base, po: None,
      "_run_after_dispatch_hooks": lambda pid, m, fd, fn: HOOKS.append((pid, list(m), fn)),
      "_stash_run_assignments": lambda *a, **k: STASH.append((a, k)),
      }
def _ftp(pip, tok, name, fdata, attempts=3, timing=None, progress_cb=None):
    UPL.append(name)
    return True, "ok"
S3["_bambu_ftp_upload"] = _ftp
_SEND_OK = [False]
def _send_proj(pid, serial, base, name):
    CMDS.append((dict(base), name, dict(S3["_bambu_last_refusal"])))
    return _SEND_OK[0]
S3["_bambu_send_project"] = _send_proj
for _name in ("_bambu_safe_upload_name", "_bambu_refusal_reason", "_norm_bambu_error_code", "_send_file_to_printer"):
    exec(_fn(_name), S3)   # noqa: S102 — свой исходник
_sendf = S3["_send_file_to_printer"]

S3["_bambu_last_refusal"]["p1"] = {"reasons": ["старый отказ"], "code": None}
r = _sendf("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "p1", OWNER, FAKE3MF, ams_slot=0)
check("C1. ФОТО ВЛАДЕЛЬЦА: файл ложится на принтер СРАЗУ под безопасным именем — одна загрузка, без второго круга",
      UPL == ["T72_E-5_1-6_B39_PETG_2h14m.gcode.3mf"], UPL)
check("C2. команда печати — с тем же безопасным именем (url строится по нему) и subtask_name без пробелов и скобок",
      len(CMDS) == 1 and CMDS[0][1] == "T72_E-5_1-6_B39_PETG_2h14m.gcode.3mf"
      and CMDS[0][0].get("subtask_name") == "T72_E-5_1-6_B39_PETG_2h14m.gcode", [c[1] for c in CMDS])
check("C3. память отказов сброшена ПЕРЕД первой командой этой отправки", CMDS and CMDS[0][2] == {}, CMDS[:1])
check("C4. принтер не принял команду: в ошибке — совет про поколение (принтер ничего не объяснил), повторной загрузки нет",
      isinstance(r, dict) and r.get("status") == "error" and "set Generation manually" in r.get("reason", "")
      and len(UPL) == 1 and not HOOKS, r)
check("C5. учёт печати — по ИСХОДНОМУ имени: server_print получает имя с пробелами и скобками",
      S3["server_print"].get("p1") == OWNER, S3["server_print"])

UPL[:] = []; CMDS[:] = []; HOOKS[:] = []
def _send_busy(pid, serial, base, name):
    CMDS.append((dict(base), name, {}))
    S3["_bambu_last_refusal"].setdefault(pid, {"reasons": [], "code": None})["busy"] = {
        "ru": "принтер занят — выполняет подготовку: стадия 13 (homing_toolhead)",
        "en": "the printer is busy: it is running a preparation step, stage 13 (homing_toolhead)"}
    return False
S3["_bambu_send_project"] = _send_busy
r = _sendf("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "p1", "plain.gcode.3mf", FAKE3MF, ams_slot=0)
check("C6. отказ «занят» до команды: в ошибке — причина со стадией, а не совет про поколение",
      isinstance(r, dict) and r.get("status") == "error" and r.get("reason", "").startswith("Печать не запущена: принтер занят")
      and "стадия 13" in r.get("reason", "") and "Generation" not in r.get("reason", ""), r)

UPL[:] = []; CMDS[:] = []; HOOKS[:] = []
S3["_bambu_send_project"] = _send_proj
_SEND_OK[0] = True
r = _sendf("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "p1", OWNER, FAKE3MF, ams_slot=0)
check("C7. принятая команда: хуки склада получают ИСХОДНОЕ имя, загрузка одна",
      r == {"status": "ok"} and HOOKS == [("p1", [0], OWNER)] and len(UPL) == 1, (r, HOOKS, UPL))
UPL[:] = []; CMDS[:] = []
r = _sendf("bambu", "10.0.0.9", 990, "FIXTURE_TOKEN", "p1", "plain_ok-1.gcode.3mf", FAKE3MF, ams_slot=0)
check("C8. уже безопасное имя уходит как есть", UPL == ["plain_ok-1.gcode.3mf"] and CMDS[0][1] == "plain_ok-1.gcode.3mf",
      (UPL, [c[1] for c in CMDS]))
_SEND_OK[0] = False

_proj = _fn("_bambu_send_project")
check("C9. причина фиксируется на КАЖДУЮ отвергнутую схему до повторной попытки и до clean_print_error",
      "_bambu_refusal_note(pid, b_pe, _t_sent)" in _proj and _proj.index("_bambu_refusal_note(pid, b_pe, _t_sent)") < _proj.index("clean_print_error"))
check("C10. «Что нового» говорит об этом словами пользователя",
      "программа называет причину словами принтера, а файл с пробелами и скобками в имени сразу ложится на принтер под безопасным именем" in SRC)

print()
print("=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
