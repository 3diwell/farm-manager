# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Приложение для телефона FM Client 0.15.15: что программа обязана ему отдавать.

ЗАЧЕМ. 10.10.2026 разобран FM Client 0.15.15 второго разработчика (исходников нет — договорённость
снята с байткода APK, docs/release_prep/ANDROID_CLIENT_NOTES.md). У приложения появился экран фермы:
принтеры, живые данные, команды, камера, проекты, задачи, запуск печати. Набор держит то, без чего
оно перестаёт работать, и две правки программы под него:

  A. адреса и методы, которые зовёт приложение, есть у сервера и модулей (склад, качество);
  B. завершённая отправка на печать держится в /api/send-jobs час: телефон снимает свою пометку
     «запуск не проверен», только увидев свою отправку completed/failed, а за прежние 10 с
     телефон в кармане её пропускал — и печать с телефона блокировалась. Бронь принтера при этом
     снимается в момент завершения, как прежде;
  C. панель отправок на компьютере по-прежнему показывает completed 10 с (фильтр в web/app.js);
  D. файл проекта, которого нет на диске, помечен в дереве (missing) — телефон не предлагает его
     печатать; путь к файлу в дерево не попадает;
  E. отметка лицензий через телефон (24.10.2026, исходники приложения — android/FM_Android_Client,
     core/LicenseRelay.java): /api/licenses/import принимает форму application/x-www-form-urlencoded
     в том самом виде, в каком её кодирует приложение (FmApi.formEncode), — поля text, relay_license_id,
     relay_status, relay_retry_after. Проверяется вызовом настоящей функции маршрута из server.py.

Запуск: python tools/test_android_client_fm_contract.py   (0 = все проверки пройдены)
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
NODE = r"C:\Program Files\nodejs\node.exe" if os.path.isfile(r"C:\Program Files\nodejs\node.exe") else (shutil.which("node") or "node")
SENTINEL = "ANDROID_CLIENT_FM_CONTRACT_SENTINEL_1010"
TMP = tempfile.mkdtemp(prefix="fm_android_contract_")

_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:600]) if detail else ""))


# ════════════════════════════════════════════════════════════════════════════
print("\n--- A. адреса, которые зовёт FM Client 0.15.15 ---")
CORE = [("get", "/api/auth/status"), ("post", "/api/auth/login"), ("post", "/api/auth/logout"),
        ("get", "/api/modules"), ("get", "/api/printers"), ("get", "/api/printer-badges"), ("get", "/api/printer-filament"),
        ("get", "/api/farm-settings"), ("post", "/api/farm-settings"), ("get", "/api/send-jobs"),
        ("get", "/api/staging"), ("get", "/api/staging/{filename}/thumb"), ("get", "/api/projects2"),
        ("get", "/api/projects2/{project_id}/tree"), ("get", "/api/projects2/files/{file_id}/thumb"),
        ("post", "/api/part/print"), ("post", "/api/projects2/{project_id}/files/{file_id}/print"),
        ("post", "/api/printer/{pid}/cmd"), ("get", "/api/printer/{pid}/camera"), ("post", "/api/printer/{pid}/webrtc"),
        ("get", "/covers/{filename}"), ("websocket", "/ws"),
        ("get", "/api/licenses"), ("post", "/api/licenses/import")]
missing = [m.upper() + " " + p for m, p in CORE if ('@app.%s("%s")' % (m, p)) not in SRC]
check("A1. все адреса ядра, которые зовёт телефон, на месте (вход, принтеры, команды, камера, проекты, задачи, печать, /ws)",
      not missing, missing)
INV = open(os.path.join(REPO, "modules", "inventory", "backend.py"), encoding="utf-8").read()
QUAL = open(os.path.join(REPO, "modules", "quality", "backend.py"), encoding="utf-8").read()
MOD = [(INV, "filament", "GET"), (INV, "locations", "GET"), (INV, "ams", "GET"), (INV, "spool", "POST"),
       (INV, "spool/{sid}/bind", "POST"), (INV, "spools/bulk-delete", "POST"), (QUAL, "print-runs", "GET")]
missing = [p for src, p, m in MOD if not re.search(r'core\.add_route\("%s", \w+, \["%s"\]' % (re.escape(p), m), src)]
check("A2. маршруты склада (катушки, ячейки, списание) и журнала качества («повторить печать») на месте", not missing, missing)
MOB = open(os.path.join(REPO, "modules", "inventory", "mobile_api.py"), encoding="utf-8").read()
need = ["slot_exchange_v2", "prepared_labels_v3", "nfc_spools_v4", "empty_spool_writeoff_v6", "slot_replace_writeoff_v7"]
check("A3. склад объявляет все возможности, которые проверяет телефон (подробно — test_inventory_mobile_protocols.py)",
      all(('"%s"' % f) in MOB for f in need), [f for f in need if ('"%s"' % f) not in MOB])

# ════════════════════════════════════════════════════════════════════════════
print("\n--- B. завершённая отправка держится час, бронь снимается сразу ---")
block = SRC[SRC.index("from concurrent.futures import ThreadPoolExecutor as _SendPool"):SRC.index("\ndef _send_watchdog_loop")]
_uidc = [0]


def _uid(prefix=""):
    _uidc[0] += 1
    return str(prefix) + format(_uidc[0], "06d")


NS = {"threading": threading, "time": time, "os": os, "re": re, "_uid": _uid, "p_states": {}, "last_seen": {},
      "STALE_FAIL_S": 60, "_exc_brief": (lambda: ""),
      "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None), "warning": staticmethod(lambda *a, **k: None),
                            "info": staticmethod(lambda *a, **k: None)})()}
exec(block, NS)
check("B1. срок хранения завершённой отправки — не меньше часа", NS["_SEND_DONE_TTL"] >= 3600, NS["_SEND_DONE_TTL"])
mgr = NS["_PrintSendManager"]()
done = threading.Event()


def send_ok(progress):
    progress(stage="uploading")
    progress(stage="sending_command", command_ok=True)
    return {"status": "ok"}


ok, job_id, _r = (lambda r: (r[0], r[1], r))(mgr.begin_direct("P1", "P1", "a.3mf", "project", send_ok, on_result=lambda *a: done.set()))
for _ in range(100):
    if any(j["job_id"] == job_id and j["state"] == "waiting_confirmation" for j in mgr.snapshot()["jobs"]):
        break
    time.sleep(0.02)
mgr.note_printer_running("P1")
snap = mgr.snapshot()
st = {j["job_id"]: j["state"] for j in snap["jobs"]}
check("B2. принтер начал печатать — отправка completed, бронь принтера снята сразу",
      ok and st.get(job_id) == "completed" and "P1" not in snap["reserved_printer_ids"], (ok, st, snap["reserved_printer_ids"]))
t0 = time.time()
mgr.tick(now=t0 + 600)
check("B3. через 10 минут завершённая отправка ещё в списке — телефон, вернувшись, её увидит",
      any(j["job_id"] == job_id and j["state"] == "completed" for j in mgr.snapshot()["jobs"]))
mgr.tick(now=t0 + NS["_SEND_DONE_TTL"] + 5)
check("B4. по истечении срока она убрана — список не растёт", not any(j["job_id"] == job_id for j in mgr.snapshot()["jobs"]))
ok2, job2, _ = mgr.begin_direct("P1", "P1", "b.3mf", "project", send_ok)
check("B5. пока завершённая запись лежит в истории, новый запуск на тот же принтер не блокируется", bool(ok2), (ok2, job2))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- C. панель на компьютере показывает completed, как прежде, 10 с ---")
a = APPJS.index("const SEND_TERMINAL = ['completed', 'failed'];")
b = APPJS.index("const _sendScheduleNext")
snippet = APPJS[a:b]
js = r"""
const ref = (v) => ({ value: v });
const computed = (f) => ({ get value() { return f(); } });
let RESP = null;
globalThis.fetch = async () => ({ ok: true, json: async () => RESP });
%s
const run = async (jobs) => { RESP = { jobs, reserved_printer_ids: [], server_time: 1000 }; await fetchSendJobs(); return sendJobsSrv.value.map((j) => j.job_id); };
(async () => {
  const out = {};
  out.shown = await run([
    { job_id: 'fresh_done', state: 'completed', updated_at: 995, created_at: 900 },
    { job_id: 'old_done', state: 'completed', updated_at: 980, created_at: 900 },
    { job_id: 'old_failed', state: 'failed', updated_at: 100, created_at: 50 },
    { job_id: 'active', state: 'uploading', updated_at: 100, created_at: 60 },
    { job_id: 'done_no_time', state: 'completed', created_at: 70 }]);
  addOptimisticJob({ job_id: 'old_done', printer_id: 'P1' });
  await run([{ job_id: 'old_done', state: 'completed', updated_at: 900, created_at: 800 }]);
  out.optimisticCleared = sendOptimistic.value.length === 0;
  console.log(JSON.stringify(out));
})();
""" % snippet
p = os.path.join(TMP, "panel.mjs")
open(p, "w", encoding="utf-8").write(js)
r = subprocess.run([NODE, p], capture_output=True, text=True, encoding="utf-8", timeout=60)
try:
    C = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    C = {"__error__": (r.stderr or r.stdout)[-500:]}
check("C1. панель: свежая завершённая (5 с), ошибка и активная видны; завершённая 20 с назад скрыта; "
      "без времени завершения — видна, как прежде",
      C.get("shown") == ["fresh_done", "old_failed", "active", "done_no_time"], C)
check("C2. оптимистичная строка панели убирается и тогда, когда сервер вернул её уже давно завершённой",
      C.get("optimisticCleared") is True, C)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- D. файл проекта, которого нет на диске, помечен в дереве ---")
fsrc = SRC[SRC.index("def get_project_tree(project_id):"):SRC.index("\ndef get_project_parts_view")]
db = sqlite3.connect(":memory:", check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE project_files (id TEXT, project_id TEXT, filename TEXT, target_model TEXT, target_nozzles TEXT, is_printable INTEGER,
  printer_id TEXT, status TEXT, content_hash TEXT, stored_path TEXT, src_path TEXT, order_idx INTEGER, created_at TEXT);
CREATE TABLE project_file_parts (id TEXT, project_id TEXT, file_id TEXT, part_id TEXT, order_idx INTEGER, on_plate_qty INTEGER, is_manual INTEGER);
CREATE TABLE project_parts (id TEXT, project_id TEXT, is_deleted INTEGER);
CREATE TABLE project_print_jobs (project_id TEXT, status TEXT, counted_at TEXT, snapshot_json TEXT);
""")
present = os.path.join(TMP, "present.3mf")
open(present, "wb").write(b"x")
gone = os.path.join(TMP, "gone.3mf")
db.execute("INSERT INTO project_files VALUES('f1','pr1','present.3mf','',NULL,1,'','ready','',?,'',0,'')", (present,))
db.execute("INSERT INTO project_files VALUES('f2','pr1','gone.3mf','',NULL,1,'','ready','',?,'',1,'')", (gone,))
db.execute("INSERT INTO project_files VALUES('f3','pr1','nopath.3mf','',NULL,1,'','ready','','','',2,'')")
DNS = {"os": os, "json": json, "lock_p": threading.RLock(), "conn_p": db,
       "_get_project": lambda pid: {"id": pid, "name": "P", "due_date": ""},
       "_fleet_for_compat": lambda: [], "_local_file_target": lambda path: {"model": ""},
       "_compatible_pids_for": lambda t, n, f: [], "_make_part_node": lambda *a: {}}
exec(fsrc, DNS)
tree = DNS["get_project_tree"]("pr1")
miss = {n["file_id"]: n.get("missing") for n in tree["nodes"]}
check("D1. файл на диске — missing=false; удалённый и без пути — missing=true (как проверяет запуск печати)",
      miss == {"f1": False, "f2": True, "f3": True}, miss)
check("D2. путь к файлу в дерево не попадает (дерево видит и наблюдатель)",
      TMP not in json.dumps(tree, ensure_ascii=False) and "stored_path" not in json.dumps(tree), tree["nodes"][0].keys())
check("D3. признак ставится той же проверкой, что у запуска печати файла проекта («file missing on disk»)",
      'path = fr["stored_path"] or fr["src_path"]\n    if not path or not os.path.isfile(path):' in SRC
      and '_on_disk = bool(_fp) and os.path.isfile(_fp)' in fsrc)

# ════════════════════════════════════════════════════════════════════════════
print("\n--- E. отметка лицензий через телефон: форма, которую шлёт приложение ---")
import ast
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, Request

_tree = ast.parse(SRC)
_fn = next(n for n in _tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "api_licenses_import")
_lines = SRC.splitlines(True)
_route_src = "".join(_lines[min(d.lineno for d in _fn.decorator_list) - 1:_fn.end_lineno])


class _LicSpy:
    def __init__(self):
        self.notes, self.imports = [], []

    def note_relay(self, lid, status, retry_after):
        self.notes.append((lid, status, retry_after))
        return "network" if status == "network" else str(status)

    def consent_given(self):
        return True

    def give_consent(self):
        pass

    def import_any(self, raw):
        self.imports.append(raw)
        return "verdict", {"license_id": "L-1", "status": "stop", "reason": "seat_taken"}


class _SdkRejected(Exception):
    code = "bad"


_SPY = _LicSpy()
_ENS = {"app": FastAPI(), "Request": Request, "UploadFile": UploadFile, "File": File, "Form": Form,
        "_require_system_admin": (lambda req: None), "_LICENSES": _SPY, "_license_mark_wake": threading.Event(),
        "_exc_brief": (lambda: ""), "log": NS["log"],
        "_lic_sdk": type("Sdk", (), {"MAX_DOCUMENT_BYTES": 65536, "MAX_KEY_CHARS": 4096, "FORMAT_VERDICT": "verdict",
                                     "Rejected": _SdkRejected, "is_key_text": staticmethod(lambda t: False),
                                     "load_document": staticmethod(lambda t: {"format": "verdict"})})}
exec(compile(_route_src, "server.py:api_licenses_import", "exec"), _ENS)


def _form_post(body):
    """POST формы через ASGI, как его отправляет FmApi.callForm (httpx в окружении нет)."""
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": "/api/licenses/import", "raw_path": b"/api/licenses/import", "root_path": "", "query_string": b"",
             "headers": [(b"content-type", b"application/x-www-form-urlencoded; charset=utf-8"),
                         (b"content-length", str(len(body)).encode())],
             "client": ("192.168.1.50", 40000), "server": ("192.168.1.10", 8000)}
    out = {"status": None, "body": b""}
    sent = [False]

    async def receive():
        if sent[0]:
            return {"type": "http.disconnect"}
        sent[0] = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"") or b""

    asyncio.run(_ENS["app"](scope, receive, send))
    try:
        return out["status"], json.loads(out["body"].decode("utf-8"))
    except Exception:
        return out["status"], out["body"][:300]


#  Тела — ровно то, что выдаёт FmApi.formEncode (см. LicenseRelayTest.formEncodingMatchesUrlencodedRules).
st1, r1 = _form_post(b"relay_license_id=L-1&relay_status=429&relay_retry_after=Wed%2C+21+Oct+2026+07%3A28%3A00+GMT")
check("E1. отказ службы с Retry-After: FM получил номер лицензии, код и срок в исходном виде и ответил relay_noted",
      st1 == 200 and r1 == {"status": "ok", "kind": "relay_noted"}
      and _SPY.notes[-1:] == [("L-1", "429", "Wed, 21 Oct 2026 07:28:00 GMT")], (st1, r1, _SPY.notes))
st2, r2 = _form_post(b"relay_license_id=L-1&relay_status=network")
check("E2. «нет связи» без Retry-After: поле срока отсутствует — FM видит None, а не пустую строку",
      st2 == 200 and r2.get("kind") == "relay_noted" and _SPY.notes[-1:] == [("L-1", "network", None)], (st2, r2, _SPY.notes))
st3, r3 = _form_post(b"relay_license_id=L-1&relay_status=rejected")
check("E3. ответ службы не принят: relay_status=rejected доходит до FM", st3 == 200 and _SPY.notes[-1:] == [("L-1", "rejected", None)],
      (st3, r3, _SPY.notes))
st4, r4 = _form_post(b"text=%7B%22a%22%3A%22%D0%B1%26c%3Dd%2Be%22%7D")
check("E4. ответ службы полем text: FM получил его байт в байт (& = + и кириллица не испорчены) и вернул вердикт",
      st4 == 200 and _SPY.imports[-1:] == ['{"a":"б&c=d+e"}'.encode("utf-8")]
      and r4 == {"status": "ok", "kind": "verdict", "license_id": "L-1", "service_state": "stop", "service_reason": "seat_taken"},
      (st4, r4, _SPY.imports[-1:]))
check("E5. запись итога отметки не считается импортом, импорт — не записью итога", len(_SPY.notes) == 3 and len(_SPY.imports) == 1,
      (len(_SPY.notes), len(_SPY.imports)))

# ════════════════════════════════════════════════════════════════════════════
print("\n--- метка-ловушка и уборка ---")
check("K1. метка-ловушка не попала в server.py и web/app.js", SENTINEL not in SRC and SENTINEL not in APPJS)
shutil.rmtree(TMP, ignore_errors=True)
check("K2. временная папка убрана", not os.path.isdir(TMP))

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
