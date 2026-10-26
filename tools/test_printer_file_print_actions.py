# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.825 — выбор и печать файлов с принтера (printer file print actions).
#
#  ПОЛНОСТЬЮ OFFLINE. Ни рабочей БД, ни DATA_DIR, ни сети, ни принтеров, ни
#  production-рантайма; ловушка сокетов на весь прогон. Проверяется:
#    • selectable/printable/deletable — ТРИ независимые возможности (чистая
#      политика security.printable_for + серверная сериализация);
#    • «Выбрать для печати»: resolve непрозрачной ссылки на backend с ПОВТОРНОЙ
#      проверкой на устройстве (_pf_resolve_print_target исполняется в изоляции);
#    • «Печать»: существующий C1-flow (p_cmd start_print) + существующий
#      pre-start диалог (printStart) — никакой второй реализации старта;
#    • Node-исполнение pf-блока и printStart-блока из app.js на стабах;
#    • реальный headless-Edge render: checkbox активен, selection bar с
#      действиями, «Выбрать для печати» -> toast без /cmd, «Печать» -> диалог
#      без /cmd, metadata-note для FlashForge (размер/дата честно скрыты).
#  Sentinel PRINTER_FILE_PRINT_ACTIONS_SENTINEL_2_825 — только в оснастке.
#
#  Запуск:  python tools/test_printer_file_print_actions.py   (0 = всё пройдено)
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
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _edge_dom   # Alpha 2.834: DOM через CDP + проверка живости движка

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

# ── Ловушка: ни одного реального сокета за прогон ────────────────────────────
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
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:200]) if detail else ""))


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "PRINTER_FILE_PRINT_ACTIONS_SENTINEL_2_825"

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
APPJS = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
INDEXHTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
APPCSS = open(os.path.join(REPO, "web", "app.css"), encoding="utf-8", errors="surrogateescape").read()
OWN = open(os.path.abspath(__file__), encoding="utf-8").read()
RPR = open(os.path.join(REPO, "app", "route_policy_registry.py"), encoding="utf-8").read()
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()


def fn_src(name, tree=None):
    for n in ast.walk(tree or SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


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

from app.printer_files import models as M                      # noqa: E402
from app.printer_files import security as S                    # noqa: E402
from app.printer_files.base import PrinterFileError, PrinterFileProvider   # noqa: E402
from app.printer_files.bambu import BambuFileProvider          # noqa: E402
from app.printer_files.moonraker import MoonrakerFileProvider  # noqa: E402
from app.printer_files.flashforge import FlashforgeFileProvider  # noqa: E402

print("=== Alpha 2.825: выбор и печать файлов с принтера (offline) ===")

# ════════════════════════════════════════════════════════════════════════════
section("КОНТРАКТ ВОЗМОЖНОСТЕЙ: selectable / printable / deletable независимы (1-16)")

ffp = FlashforgeFileProvider(lambda pid: [])
bbp = BambuFileProvider(lambda pid: None)
mrp = MoonrakerFileProvider(lambda pid, path: {}, lambda pid, path: {})
FF_CAPS = ffp.probe_capabilities({"id": "f", "type": "flashforge", "has_credentials": True})
BB_CAPS = bbp.probe_capabilities({"id": "b", "type": "bambu", "has_credentials": True, "model": "X1C"})
MR_CAPS = mrp.probe_capabilities({"id": "k", "type": "klipper"})

check("1. FlashForge: print_existing_files=True (доказанный C1 /printGcode), delete_files=False",
      FF_CAPS.print_existing_files and not FF_CAPS.delete_files and FF_CAPS.list_files)
check("2. Bambu: print_existing_files=True (доказанный C1 _bambu_start_print)",
      BB_CAPS.print_existing_files and BB_CAPS.delete_files)
check("3. Moonraker: print_existing_files=True (доказанный C1 /printer/print/start)",
      MR_CAPS.print_existing_files and MR_CAPS.delete_files)
check("4. print_existing_files сериализуется в capabilities-ответ",
      FF_CAPS.as_dict().get("print_existing_files") is True
      and "print_existing_files" in M.PrinterFileCapabilities(supported=False).as_dict())

# printable_for — чистая fail-closed политика
_pf = S.printable_for
check("5. FlashForge .gcode printable (программа, доказанное расширение)",
      _pf("Cube_PETG_25m30s.gcode", False, M.CAT_PROGRAM, "internal", True,
          ffp.printable_extensions, ffp.printable_storages) == (True, ""))
check("6. FlashForge .3mf НЕ printable (2.764: контейнер вешает прошивку A5M)",
      ".3mf" not in ffp.printable_extensions
      and _pf("x.3mf", False, M.CAT_PROGRAM, "internal", True,
              ffp.printable_extensions, ffp.printable_storages)[0] is False)
check("7. Каталог НЕ printable (reason=directory)",
      _pf("dir", True, M.CAT_OTHER, "internal", True, ffp.printable_extensions, None)
      == (False, M.REASON_DIRECTORY))
check("8. Видео/таймлапс НЕ printable (file_not_printable)",
      _pf("tl.mp4", False, M.CAT_VIDEO, "internal", True, ffp.printable_extensions, None)
      == (False, M.REASON_FILE_NOT_PRINTABLE))
check("9. Неизвестный тип НЕ printable (file_not_printable)",
      _pf("data.bin", False, M.CAT_OTHER, "internal", True, ffp.printable_extensions, None)
      == (False, M.REASON_FILE_NOT_PRINTABLE))
check("10. Без capability print_existing_files ничего не printable (unknown adapter)",
      _pf("a.gcode", False, M.CAT_PROGRAM, "internal", False, (".gcode",), None)
      == (False, M.REASON_PRINT_STORAGE_UNSUPPORTED))
check("11. Bambu: существующий .3mf printable (тот же фильтр, что выпадашка g_files)",
      _pf("cache/x.gcode.3mf".split("/")[-1], False, M.CAT_PROGRAM, "sd", True,
          bbp.printable_extensions, bbp.printable_storages) == (True, ""))
check("12. Klipper: печать ТОЛЬКО из root gcodes (timelapse -> print_from_storage_unsupported)",
      mrp.printable_storages == ("gcodes",)
      and _pf("a.gcode", False, M.CAT_PROGRAM, "timelapse", True,
              mrp.printable_extensions, mrp.printable_storages)
      == (False, M.REASON_PRINT_STORAGE_UNSUPPORTED)
      and _pf("a.gcode", False, M.CAT_PROGRAM, "gcodes", True,
              mrp.printable_extensions, mrp.printable_storages) == (True, ""))
check("13. Модель entry несёт printable/print_blocked_reason (и это отдельные поля от deletable)",
      "printable" in M.PrinterFileEntry("r", "n").as_dict()
      and "print_blocked_reason" in M.PrinterFileEntry("r", "n").as_dict())
check("14. Новые reason-коды в безопасном словаре",
      all(r in M.SAFE_REASONS for r in ("file_not_printable", "printer_offline", "printer_busy",
                                        "print_from_storage_unsupported", "preflight_failed")))
check("15. Базовый провайдер fail-closed: printable_extensions пуст по умолчанию",
      PrinterFileProvider.printable_extensions == () and PrinterFileProvider.printable_storages is None)
check("16. _pf_list_impl считает printable ЦЕНТРАЛЬНО через printable_for (авторитет backend)",
      "printable_for" in fn_src("_pf_list_impl")
      and "printable=printable" in fn_src("_pf_list_impl"))

# ════════════════════════════════════════════════════════════════════════════
section("BACKEND: resolve цели печати + существующий старт (17-38)")

_RT_SRC = fn_src("_pf_resolve_print_target")


def _code_only(name):
    """Исходник функции БЕЗ докстроки (проверка не должна ловить собственную прозу)."""
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            body = list(n.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]
            return chr(10).join(ast.unparse(x) for x in body)
    return ""


_RT_CODE = _code_only("_pf_resolve_print_target")
check("17. _pf_resolve_print_target существует и НИЧЕГО не отправляет принтеру "
      "(в КОДЕ только list_directory; никаких print/start/delete вызовов)",
      bool(_RT_SRC) and "list_directory" in _RT_CODE
      and not re.search(r"_flashforge_print|_bambu_start_print|print/start|begin_direct|delete", _RT_CODE))
check("18. resolve проверяет capability print_existing_files",
      "print_existing_files" in _RT_SRC)
check("19. resolve повторно ищет файл на устройстве (как delete): совпадение имени и не-каталог",
      "is_dir" in _RT_SRC and "row is None" in _RT_SRC and "REASON_NOT_FOUND" in _RT_SRC)
check("20. resolve пере-проверяет printable (категория+расширение+storage)",
      "printable_for" in _RT_SRC and "REASON_FILE_NOT_PRINTABLE" in _RT_SRC)

# Исполнение resolve в изоляции: реальные security/models, фейковый провайдер
_ns = {"_pf_models": M, "_pf_security": S, "_PfError": PrinterFileError,
       "log": type("L", (), {"debug": staticmethod(lambda *a: None)})(),
       "_exc_brief": lambda: "x"}
exec(fn_src("_pf_err"), _ns)          # безопасный формат ошибок
_REFS = S.RefRegistry()
_ns["_PF_REFS"] = _REFS


class _FakeProv(object):
    adapter = "flashforge"
    timelapse_dirs = ()
    printable_extensions = (".gcode", ".gx", ".g", ".gco")
    printable_storages = None
    delete_safe_during_print = False

    def __init__(self):
        self.listing = [{"name": "Cube_PETG_25m30s.gcode", "is_dir": False, "size": None, "mtime": None},
                        {"name": "clip.mp4", "is_dir": False, "size": None, "mtime": None}]
        self.caps = M.PrinterFileCapabilities(
            supported=True, list_files=True, print_existing_files=True,
            storage_types=(M.STORAGE_INTERNAL,), adapter="flashforge")

    def probe_capabilities(self, sp):
        return self.caps

    def list_directory(self, sp, sid, rel):
        return list(self.listing)

    def storage_writable(self, sp, sid):
        return False


_prov = _FakeProv()
_ns["_pf_printer_row"] = lambda pid: ({"id": pid} if pid in ("p1", "p2") else None)
_ns["_pf_safe_printer"] = lambda p: {"id": p["id"], "type": "flashforge", "has_credentials": True}
_ns["_pf_registry"] = lambda: type("R", (), {"provider_for": staticmethod(lambda sp: _prov)})()
exec(_RT_SRC, _ns)
_resolve = _ns["_pf_resolve_print_target"]

_ref_ok = _REFS.make("p1", "internal", "Cube_PETG_25m30s.gcode", False)
_ref_vid = _REFS.make("p1", "internal", "clip.mp4", False)
_ref_dir = _REFS.make("p1", "internal", "somedir", True)
_ref_gone = _REFS.make("p1", "internal", "vanished.gcode", False)

_r = _resolve("p1", _ref_ok)
check("21. resolve OK: печатаемый gcode -> нормализованный print_name (формат выпадашки, без raw path)",
      _r.get("status") == "ok" and _r.get("print_name") == "Cube_PETG_25m30s.gcode"
      and _r.get("name") == "Cube_PETG_25m30s.gcode" and _r.get("storage_id") == "internal")
check("22. stale/чужой ref -> stale_reference (мусор не проходит)",
      _resolve("p1", "pfr_bogus").get("reason") == "stale_reference"
      and _resolve("p1", "").get("reason") == "stale_reference")
check("23. ref ДРУГОГО принтера отвергается ПРИВЯЗКОЙ ссылки (stale_reference, не not_found)",
      _resolve("p2", _ref_ok).get("reason") == "stale_reference")
check("24. каталог -> directory",
      _resolve("p1", _ref_dir).get("reason") == "directory")
check("25. исчезнувший файл -> not_found (повторная проверка НА УСТРОЙСТВЕ)",
      _resolve("p1", _ref_gone).get("reason") == "not_found")
check("26. видео -> file_not_printable (printable перепроверяется при resolve)",
      _resolve("p1", _ref_vid).get("reason") == "file_not_printable")
_prov.caps = M.PrinterFileCapabilities(supported=True, list_files=True, print_existing_files=False,
                                       storage_types=(M.STORAGE_INTERNAL,), adapter="flashforge")
check("27. адаптер без print_existing_files -> print_from_storage_unsupported",
      _resolve("p1", _ref_ok).get("reason") == "print_from_storage_unsupported")
_prov.caps = M.PrinterFileCapabilities(supported=True, list_files=True, print_existing_files=True,
                                       storage_types=(M.STORAGE_INTERNAL,), adapter="flashforge")


def _listing_err(sp, sid, rel):
    raise PrinterFileError(M.REASON_TIMEOUT)


_prov.list_directory = _listing_err
check("28. ошибка связи при resolve -> честный reason (timeout), не «пусто» и не успех",
      _resolve("p1", _ref_ok).get("reason") == "timeout")

# Маршрут select-for-print и его политика
check("29. маршрут POST /api/printer-files/select-for-print объявлен и защищён printer_files_read",
      '@app.post("/api/printer-files/select-for-print")' in SRV
      and '"POST /api/printer-files/select-for-print": (EnforcedAccess.CAPABILITY, "printer_files_read")' in RPR)
check("30. select-for-print уважает предохранитель чтения (_pf_read_enabled)",
      "_pf_read_enabled" in fn_src("pf_select_for_print"))
check("31. select-for-print НЕ имеет пути старта печати (только resolve)",
      not re.search(r"begin_direct|_flashforge_print|_bambu_start_print|server_print",
                    fn_src("pf_select_for_print")))

# p_cmd: существующий старт + file_ref-перепроверка
_PC = fn_src("p_cmd")
check("32. PCmd.file_ref — необязательное поле (старый путь карточки не изменён ни байтом)",
      re.search(r"class PCmd\(BaseModel\):[\s\S]{0,900}file_ref: Optional\[str\] = None", SRV))
check("33. p_cmd start_print: при file_ref сервер резолвит и ЗАМЕНЯЕТ val (подмена имени невозможна)",
      "_pf_resolve_print_target(pid, data.file_ref)" in _PC
      and "data.val = _rt['print_name']" in _PC)
check("34. перепроверка file_ref идёт ДО hold/preflight/reservation (отказ без команд принтеру)",
      _PC.find("_pf_resolve_print_target") < _PC.find("_hold_block(pid)") < _PC.find("_c1_load_plate_compat")
      < _PC.find("_send_mgr.begin_direct"))
check("35. отказ resolve -> безопасный reason, никакого fallback на клиентский val",
      re.search(r"if not isinstance\(_rt, dict\) or _rt\.get\('status'\) != 'ok':[\s\S]{0,300}return \{'status': 'error'", _PC))
check("36. существующий C1-старт сохранён: hold -> bambu compat -> reservation -> send-callable",
      all(t in _PC for t in ("_hold_block(pid)", "_c1_load_plate_compat", "_send_mgr.begin_direct", "'printer_file'")))
check("37. фактический send per-type не менялся (klipper /print/start, ff _flashforge_print, bambu MQTT)",
      all(t in fn_src("_cmd_start_print_send") for t in ("print/start", "_flashforge_print", "_bambu_start_print")))
check("38. ЕДИНСТВЕННЫЙ вход печати из файлового менеджера — существующий p_cmd "
      "(нет нового start-маршрута printer-files)",
      "printer-files/print\"" not in SRV and "printer-files/start" not in SRV
      and "prepare-print" not in SRV)

# ════════════════════════════════════════════════════════════════════════════
section("NODE: pf-блок — выбор, «Выбрать для печати», «Печать» (39-58)")

_i0 = APPJS.find("    const showPrinterFiles = ref(false);")
_i1 = APPJS.find("const closePrinterFiles = () => { showPrinterFiles.value = false; _pfGen++; };")
PF_BLOCK = APPJS[_i0:_i1 + len("const closePrinterFiles = () => { showPrinterFiles.value = false; _pfGen++; };")]
check("39. pf-блок извлечён (в нём есть pfSelectForPrint/pfPrintNow/pfStartCmd)",
      _i0 > 0 and all(t in PF_BLOCK for t in ("pfSelectForPrint", "pfPrintNow", "pfStartCmd", "pfSelectable")))

NODE_RES = {}
if NODE and _i0 > 0:
    HARNESS = r"""
'use strict';
const ref = (v) => ({ value: v });
const computed = (fn) => ({ get value() { return fn(); } });
const lang = ref('ru');
const printers = ref([{ id: 'p1', name: 'P1' }]);
const showDiag = ref(false), showSettings = ref(false);
const closeDiagnostics = () => {}; const closeSettings = () => {};
const localStorage = { _m: {}, getItem(k) { return this._m[k] || null; }, setItem(k, v) { this._m[k] = String(v); } };
let confirmResult = true; let confirmCalls = 0;
const confirm = () => { confirmCalls++; return confirmResult; };
const alert = () => {};
const toasts = [];
const pushToast = (t, k) => toasts.push(String(t));
const tr = (s) => String(s);
const _printerNameOf = (pid) => pid;
const sendCalls = [];
const handleSendResp = (resp, ctx) => { sendCalls.push({ resp, ctx }); return (resp && resp.accepted) ? 'accepted' : 'other'; };
const printStartCalls = [];
const openPrintStart = (ctx) => { printStartCalls.push(ctx); };
const wsData = ref({ p1: { status: 'IDLE' } });
const sendReserved = ref(new Set());
const cellBusy = (pid) => ((wsData.value[pid] || {}).status === 'RUNNING') || sendReserved.value.has(pid);
const activeModalPrinterId = ref('');
const printerFiles = ref([]);
const printFileName = ref('');
const fetchLog = [];
let cmdResp = { accepted: true, job_id: 'j1' };
let sfpResp = { status: 'ok', printer_id: 'p1', storage_id: 'internal', name: 'Cube_PETG_25m30s.gcode', print_name: 'Cube_PETG_25m30s.gcode' };
const fetch = (url, opts) => {
  fetchLog.push({ url: String(url), body: (opts && opts.body) ? JSON.parse(opts.body) : null });
  const j = String(url).includes('select-for-print') ? sfpResp
    : String(url).includes('/cmd') ? cmdResp
    : String(url).includes('capabilities') ? { status: 'ok', read_enabled: true, delete_enabled: false, delete_ui_allowed: false,
        capabilities: { supported: true, list_files: true, delete_files: false, print_existing_files: true, read_sizes: false, read_mtime: false }, printer: { id: 'p1', name: 'P1' } }
    : String(url).includes('storages') ? { status: 'ok', storages: [{ storage_id: 'internal', display_name: 'S', type: 'internal', writable: false, online: true }] }
    : String(url).includes('/list') ? { status: 'ok', entries: LIST_ENTRIES.map((e) => Object.assign({}, e)), total: LIST_ENTRIES.length, cursor_next: null }
    : { status: 'ok' };
  return Promise.resolve({ json: () => Promise.resolve(j) });
};
let LIST_ENTRIES = [
  { file_ref: 'pfr_a', name: 'Cube_PETG_25m30s.gcode', is_directory: false, category: 'program', timelapse: false, extension: '.gcode',
    size_bytes: null, modified_at: null, storage_id: 'internal', deletable: false, protected_reason: 'unsupported', printable: true, print_blocked_reason: '', active_print: false },
  { file_ref: 'pfr_b', name: 'second.gcode', is_directory: false, category: 'program', timelapse: false, extension: '.gcode',
    size_bytes: null, modified_at: null, storage_id: 'internal', deletable: false, protected_reason: 'unsupported', printable: true, print_blocked_reason: '', active_print: false },
  { file_ref: 'pfr_v', name: 'clip.mp4', is_directory: false, category: 'video', timelapse: false, extension: '.mp4',
    size_bytes: null, modified_at: null, storage_id: 'internal', deletable: false, protected_reason: 'unsupported', printable: false, print_blocked_reason: 'file_not_printable', active_print: false },
  { file_ref: 'pfd_d', name: 'somedir', is_directory: true, category: 'other', timelapse: false, extension: '',
    size_bytes: null, modified_at: null, storage_id: 'internal', deletable: false, protected_reason: 'directory', printable: false, print_blocked_reason: 'directory', active_print: false },
];
%%BLOCK%%
(async () => {
  const out = {};
  await pfSelectPrinter('p1');
  const byName = (n) => (pfEntries.value || []).find((e) => e.name === n);
  // ВЫБОР: printable/non-printable/каталог
  pfToggleSel(byName('Cube_PETG_25m30s.gcode'));
  out.sel_gcode = pfSelected.value.size;                       // 1 — выбор независим от delete
  pfToggleSel(byName('clip.mp4'));
  out.sel_video = pfSelected.value.size;                       // 2 — видео тоже выбирается (просмотр)
  pfToggleSel(byName('somedir'));
  out.sel_dir = pfSelected.value.size;                         // 2 — каталог НЕ выбирается
  out.block_multi = pfPrintBlockReason.value;                  // «один файл»
  out.multi_target_null = pfPrintTarget.value === null;        // цель печати при multi = null
  pfClearSel(); pfToggleSel(byName('clip.mp4'));
  out.block_video = pfPrintBlockReason.value;                  // «нельзя напечатать»
  pfClearSel(); pfToggleSel(byName('Cube_PETG_25m30s.gcode'));
  out.block_ok = pfPrintBlockReason.value;                     // '' — можно
  wsData.value = { p1: { status: 'OFFLINE' } };
  out.block_offline = pfPrintBlockReason.value;
  wsData.value = { p1: { status: 'RUNNING' } };
  out.block_busy = pfPrintBlockReason.value;
  wsData.value = { p1: { status: 'IDLE' } };
  // «ВЫБРАТЬ ДЛЯ ПЕЧАТИ»: resolve на backend; старый dropdown получает тот же файл; /cmd НЕ зовётся
  activeModalPrinterId.value = 'p1'; printerFiles.value = ['Cube_PETG_25m30s.gcode'];
  fetchLog.length = 0; toasts.length = 0;
  await pfSelectForPrint();
  out.sfp_fetches = fetchLog.map((f) => f.url);
  out.sfp_body = fetchLog[0] ? fetchLog[0].body : null;
  out.sfp_dropdown = printFileName.value;
  out.sfp_toast = toasts.length;
  out.sfp_cmd_calls = fetchLog.filter((f) => f.url.includes('/cmd')).length;
  // resolve-отказ not_found -> честный toast, selection очищен
  sfpResp = { status: 'error', reason: 'not_found' };
  toasts.length = 0;
  pfClearSel(); pfToggleSel(byName('Cube_PETG_25m30s.gcode'));
  await pfSelectForPrint();
  out.sfp_nf_toast = toasts.join('|');
  out.sfp_nf_selection = pfSelected.value.size;
  sfpResp = { status: 'ok', printer_id: 'p1', storage_id: 'internal', name: 'Cube_PETG_25m30s.gcode', print_name: 'Cube_PETG_25m30s.gcode' };
  // «ПЕЧАТЬ»: resolve -> СУЩЕСТВУЮЩИЙ pre-start диалог; /cmd НЕ уходит до подтверждения
  await pfSelectPrinter('p1');
  pfToggleSel((pfEntries.value || []).find((e) => e.name === 'Cube_PETG_25m30s.gcode'));
  fetchLog.length = 0; printStartCalls.length = 0;
  await pfPrintNow();
  out.pn_dialog = printStartCalls.length;
  out.pn_dialog_c1 = printStartCalls[0] ? !!printStartCalls[0].c1 : null;
  out.pn_label = printStartCalls[0] ? printStartCalls[0].label : '';
  out.pn_cmd_before_confirm = fetchLog.filter((f) => f.url.includes('/cmd')).length;   // 0!
  // подтверждение диалога -> существующий C1 endpoint c file_ref и серверным val
  if (printStartCalls[0] && printStartCalls[0].onConfirm) await printStartCalls[0].onConfirm(null, -1);
  const cmd = fetchLog.filter((f) => f.url.includes('/cmd'));
  out.pn_cmd_after_confirm = cmd.length;
  out.pn_cmd_body = cmd[0] ? cmd[0].body : { };
  // отказ backend -> честный тост, никакого «успеха»
  cmdResp = { status: 'error', reason: 'stale_reference' };
  toasts.length = 0; fetchLog.length = 0;
  await pfStartCmd('p1', 'Cube_PETG_25m30s.gcode', 'pfr_a', -1);
  out.pn_err_toast = toasts.length;
  cmdResp = { accepted: true, job_id: 'j1' };
  console.log('@@RES@@' + JSON.stringify(out) + '@@END@@');
})().catch((e) => { console.log('@@RES@@' + JSON.stringify({ harness_error: String(e && e.message || e) }) + '@@END@@'); });
"""
    _js = HARNESS.replace("%%BLOCK%%", PF_BLOCK)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_pfpa_") as _td:
        _f = os.path.join(_td, "h.js")
        io.open(_f, "w", encoding="utf-8", newline="\n").write(_js)
        _pr = subprocess.run([NODE, _f], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=120)
        _m = re.search(r"@@RES@@(\{.*\})@@END@@", _pr.stdout or "", re.S)
        NODE_RES = json.loads(_m.group(1)) if _m else {"harness_error": (_pr.stderr or "")[:300]}

check("40. Node-стенд отработал без ошибок", NODE_RES and "harness_error" not in NODE_RES,
      str(NODE_RES)[:200])
if NODE_RES and "harness_error" not in NODE_RES:
    check("41. printable non-deletable файл ВЫБИРАЕТСЯ (независимость от delete)", NODE_RES["sel_gcode"] == 1)
    check("42. видео выбирается (для просмотра/будущего управления), печать ему не положена",
          NODE_RES["sel_video"] == 2)
    check("43. каталог НЕ выбирается", NODE_RES["sel_dir"] == 2)
    check("44. multi-select блокирует печать: подсказка «один файл» И цель печати null",
          "один файл" in NODE_RES["block_multi"] and NODE_RES["multi_target_null"] is True)
    check("45. non-printable single -> печать заблокирована с причиной",
          "нельзя напечатать" in NODE_RES["block_video"])
    check("46. один printable + принтер IDLE -> печать разрешена (причин нет)",
          NODE_RES["block_ok"] == "")
    check("47. printer offline -> «Принтер не в сети» (выбор сохраняется)",
          "не в сети" in NODE_RES["block_offline"])
    check("48. printer busy (RUNNING) -> «Принтер занят»",
          "занят" in NODE_RES["block_busy"])
    check("49. «Выбрать для печати»: РОВНО один запрос select-for-print с opaque ref (никакого raw path)",
          NODE_RES["sfp_fetches"] == ["/api/printer-files/select-for-print"]
          and NODE_RES["sfp_body"] == {"printer_id": "p1", "file_ref": "pfr_a"})
    check("50. старый dropdown карточки получает ТОТ ЖЕ файл (print_name от сервера)",
          NODE_RES["sfp_dropdown"] == "Cube_PETG_25m30s.gcode")
    check("51. toast показан; печать НЕ началась (0 обращений к /cmd)",
          NODE_RES["sfp_toast"] == 1 and NODE_RES["sfp_cmd_calls"] == 0)
    check("52. resolve not_found -> «Файл больше не найден», stale-выбор очищен",
          "Файл больше не найден" in NODE_RES["sfp_nf_toast"] and NODE_RES["sfp_nf_selection"] == 0)
    check("53. «Печать» открывает СУЩЕСТВУЮЩИЙ pre-start диалог (c1) с именем файла",
          NODE_RES["pn_dialog"] == 1 and NODE_RES["pn_dialog_c1"] is True
          and NODE_RES["pn_label"] == "Cube_PETG_25m30s.gcode")
    check("54. ДО подтверждения diálога /cmd НЕ вызывается (кнопка не шлёт команду сразу)",
          NODE_RES["pn_cmd_before_confirm"] == 0)
    check("55. подтверждение -> ОДИН вызов существующего C1 /api/printer/p1/cmd",
          NODE_RES["pn_cmd_after_confirm"] == 1
          and str(NODE_RES["pn_cmd_body"].get("cmd")) == "start_print")
    check("56. тело старта несёт opaque file_ref (сервер перепроверит и подставит своё имя)",
          NODE_RES["pn_cmd_body"].get("file_ref") == "pfr_a"
          and NODE_RES["pn_cmd_body"].get("val") == "Cube_PETG_25m30s.gcode")
    check("57. внешняя катушка по умолчанию для C1 (ams_slot=-1 от диалога)",
          NODE_RES["pn_cmd_body"].get("ams_slot") == -1)
    check("58. отказ backend (stale_reference) -> честный тост, не тихий успех",
          NODE_RES["pn_err_toast"] == 1)
else:
    for _k in range(41, 59):
        check("%d. (пропущено из-за ошибки Node-стенда)" % _k, False)

# ════════════════════════════════════════════════════════════════════════════
section("NODE: существующий pre-start диалог printStart (59-66)")

#  16.10.2026 (R-137): у _printSrcOptions второй аргумент — двухсопельный ли принтер.
_p0 = APPJS.find("    const _printSrcOptions = (trays")
_p1 = APPJS.find("const printStartTypeLabel = (t) =>")
_p1e = APPJS.find("\n", APPJS.find("};", _p1))
PS_BLOCK = APPJS[_p0:_p1e]
check("59. printStart-блок извлечён (openPrintStart/confirmPrintStart/closePrintStart)",
      _p0 > 0 and all(t in PS_BLOCK for t in ("openPrintStart", "confirmPrintStart", "closePrintStart")))

PS_RES = {}
if NODE and _p0 > 0:
    PS_HARNESS = r"""
'use strict';
const ref = (v) => ({ value: v });
const lang = ref('ru');
const printers = ref([{ id: 'b1', name: 'B1', type: 'bambu', model: 'X1C' }, { id: 'f1', name: 'F1', type: 'flashforge', model: 'AD5M' }]);
const printerCapabilities = (p) => ({ bambu: (p.type === 'bambu') });
const wsData = ref({ b1: { ams_trays: [{ index: 0, unit: 0, tray: 0, type: 'PLA' }, { index: 1, unit: 0, tray: 1, type: 'PETG' }] }, f1: {} });
const PRINT_OPTS_DEFAULT = { timelapse: false, bed_leveling: true, flow_cal: false };
const _loadPrintOpts = () => Object.assign({}, PRINT_OPTS_DEFAULT);
const _printerNameOf = (pid) => pid;
const localStorage = { _m: {}, getItem(k) { return this._m[k] || null; }, setItem(k, v) { this._m[k] = String(v); } };
const console2 = console;
%%BLOCK%%
const out = {};
// c1 на Bambu с AMS: нет «Авто», по умолчанию внешняя катушка
openPrintStart({ printerId: 'b1', label: 'x.gcode', c1: true, onConfirm: null });
out.c1_flag = printStart.value.c1;
out.c1_has_auto = printStart.value.srcOptions.some((o) => o.v === 'auto');
out.c1_src = printStart.value.src;
closePrintStart();
// обычный (карточка/задачи): «Авто» на месте — прежнее поведение не тронуто
openPrintStart({ printerId: 'b1', label: 'x.gcode', onConfirm: null });
out.norm_has_auto = printStart.value.srcOptions.some((o) => o.v === 'auto');
out.norm_c1 = printStart.value.c1;
closePrintStart();
// Cancel НЕ вызывает onConfirm
let confirms = [];
openPrintStart({ printerId: 'b1', label: 'x.gcode', c1: true, onConfirm: (o, s) => confirms.push([o, s]) });
closePrintStart();
out.cancel_calls = confirms.length;
// Confirm вызывает ровно один раз; c1 срез: внешняя катушка -> srcSlot -1
openPrintStart({ printerId: 'b1', label: 'x.gcode', c1: true, onConfirm: (o, s) => confirms.push([o, s]) });
confirmPrintStart();
out.confirm_calls = confirms.length;
out.confirm_srcSlot = confirms[0] ? confirms[0][1] : null;
// не-Bambu (FlashForge): диалог без Bambu-блока; confirm отдаёт (null, undefined)
confirms = [];
openPrintStart({ printerId: 'f1', label: 'Cube_PETG_25m30s.gcode', c1: true, onConfirm: (o, s) => confirms.push([o, s]) });
out.ff_bambu_block = !!(printStart.value.caps && printStart.value.caps.bambu);
confirmPrintStart();
out.ff_confirm = confirms.length === 1 && confirms[0][0] === null && confirms[0][1] === undefined;
console.log('@@RES@@' + JSON.stringify(out) + '@@END@@');
"""
    _js = PS_HARNESS.replace("%%BLOCK%%", PS_BLOCK)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_pfps_") as _td:
        _f = os.path.join(_td, "ps.js")
        io.open(_f, "w", encoding="utf-8", newline="\n").write(_js)
        _pr = subprocess.run([NODE, _f], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
        _m = re.search(r"@@RES@@(\{.*\})@@END@@", _pr.stdout or "", re.S)
        PS_RES = json.loads(_m.group(1)) if _m else {"harness_error": (_pr.stderr or "")[:300]}

check("60. printStart-стенд отработал", PS_RES and "harness_error" not in PS_RES, str(PS_RES)[:200])
if PS_RES and "harness_error" not in PS_RES:
    check("61. c1: «Авто» скрыт (в C1 не существует), по умолчанию внешняя катушка (-1)",
          PS_RES["c1_flag"] is True and PS_RES["c1_has_auto"] is False and PS_RES["c1_src"] == -1)
    check("62. обычный путь карточки/задач НЕ изменён («Авто» на месте, c1=false)",
          PS_RES["norm_has_auto"] is True and PS_RES["norm_c1"] is False)
    check("63. Cancel закрывает диалог и НЕ вызывает onConfirm (команда не уходит)",
          PS_RES["cancel_calls"] == 0)
    check("64. Confirm вызывает onConfirm РОВНО один раз; c1 внешняя катушка -> srcSlot=-1",
          PS_RES["confirm_calls"] == 1 and PS_RES["confirm_srcSlot"] == -1)
    check("65. FlashForge: Bambu-блока в диалоге нет; confirm отдаёт (null, undefined)",
          PS_RES["ff_bambu_block"] is False and PS_RES["ff_confirm"] is True)
    check("66. Bambu-опции запуска скрыты в c1-режиме разметки (v-if по printStart.c1 на трёх label)",
          INDEXHTML.count('v-if="!printStart.c1"') == 3)
else:
    for _k in range(61, 67):
        check("%d. (пропущено из-за ошибки printStart-стенда)" % _k, False)

# ════════════════════════════════════════════════════════════════════════════
section("METADATA: честность и capability-driven колонки (67-76)")

check("67. FlashForge caps честно: read_sizes=False, read_mtime=False (в /gcodeList только имена)",
      FF_CAPS.read_sizes is False and FF_CAPS.read_mtime is False)
check("68. Bambu/Moonraker caps: read_sizes/read_mtime=True (колонки НЕ скрываются)",
      BB_CAPS.read_sizes and BB_CAPS.read_mtime and MR_CAPS.read_sizes and MR_CAPS.read_mtime)
_ff_reader = fn_src("_flashforge_gcode_list")
check("69. единый чтец /gcodeList не выдумывает метаданные (нет size/mtime/time/date synthesis)",
      bool(_ff_reader) and not re.search(r"time\.time\(\)|datetime|size|mtime|getsize", _ff_reader))
check("70. _pf_ff_list отдаёт ТОЛЬКО имена через единый чтец (без придуманных полей)",
      "_flashforge_gcode_list(" in fn_src("_pf_ff_list")
      and not re.search(r"time\.time\(\)|getsize|len\(name\)", fn_src("_pf_ff_list")))
check("71. сериализация entry берёт size/mtime ТОЛЬКО из ответа провайдера (get('size')/get('mtime'))",
      re.search(r"size_bytes=\(r or \{\}\)\.get\('size'\)", fn_src("_pf_list_impl"))
      and re.search(r"modified_at=\(r or \{\}\)\.get\('mtime'\)", fn_src("_pf_list_impl")))
check("72. колонки Размер/Дата в разметке под capability (v-if pfShowSize/pfShowDate на th И td)",
      '<th v-if="pfShowSize"' in INDEXHTML and '<td v-if="pfShowSize"' in INDEXHTML
      and '<th v-if="pfShowDate"' in INDEXHTML and '<td v-if="pfShowDate"' in INDEXHTML)
check("73. pfShowSize/pfShowDate скрывают колонку ТОЛЬКО при честном false от адаптера",
      "pfCaps.value.read_sizes !== false" in APPJS and "pfCaps.value.read_mtime !== false" in APPJS)
check("74. metadata-note объясняет отсутствие размера/даты (RU) и есть EN-вариант",
      "Этот принтер передаёт только имена файлов" in INDEXHTML
      and "This printer reports file names only" in INDEXHTML)
check("75. capability-note: «Печать доступна» + «Удаление не поддерживается принтером» с tooltip",
      "Печать доступна" in INDEXHTML and "Удаление не поддерживается принтером" in INDEXHTML
      and "нет доказанного протокола удаления" in INDEXHTML)
check("76. сведения строки честны при отсутствии метаданных («Размер: принтер не сообщает»)",
      "Размер: принтер не сообщает" in INDEXHTML)

# ════════════════════════════════════════════════════════════════════════════
section("EDGE RENDER: реальный движок — checkbox, selection bar, действия (77-88)")


def _edge_run(lang_val):
    css_href = "file:///" + os.path.join(REPO, "web", "app.css").replace("\\", "/")
    vue_href = "file:///" + os.path.join(REPO, "web", "vendor", "vue.esm-browser.js").replace("\\", "/")
    si = INDEXHTML.find('<section v-if="showPrinterFiles"')
    section_html = INDEXHTML[si:INDEXHTML.find("</section>", si) + len("</section>")]
    pf_names = ("showPrinterFiles, openPrinterFiles, closePrinterFiles, pfPrinterId, pfSelectPrinter, pfStorages, "
                "pfStorageId, pfSelectStorage, pfStorage, pfPath, pfCrumbTo, pfOpenDir, pfEntries, pfRowsView, "
                "pfState, pfReason, pfReasonText, pfSearch, pfCat, pfAge, pfSortKey, pfSortDir, pfSetSort, "
                "pfSelected, pfSelectable, pfToggleSel, pfSelectShown, pfClearSel, pfPresetOldPrograms, pfSummary, pfBusy, "
                "pfDeleteBusy, pfRefresh, pfDeleteOne, pfDeleteSelected, pfDeleteAllowed, pfCaps, pfCapsResp, "
                "pfFmtSize, pfFmtDate, pfCatText, pfFlags, pfRowClick, pfPrintTarget, pfPrintBlockReason, pfActionBusy, "
                "pfSelectForPrint, pfPrintNow, pfRowMenu, pfRowMenuFor, pfRowMenuClose, pfRowMenuAct, "
                "pfStatusText, pfStatusTitle, pfShowSize, pfShowDate, pfMetaNote, "
                #  2.989: предпросмотр файла — кнопка в строке и окно с картинкой.
                "pfPreview, pfCanPreview, pfPreviewOpen, pfPreviewClose")
    html = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<script>window.__e=[];var _c=console.error;console.error=function(){window.__e.push(Array.from(arguments).map(String).join(' '));_c.apply(console,arguments)};"
            "window.addEventListener('error',function(e){window.__e.push('onerror:'+e.message)});"
            "window.addEventListener('unhandledrejection',function(e){window.__e.push('reject:'+String((e.reason&&e.reason.message)||e.reason))});"
            "function J(o){return{ok:true,status:200,json:function(){return Promise.resolve(o)}}}"
            "window.__fetches=[];"
            "window.fetch=function(u,opts){u=String(u);window.__fetches.push({u:u,body:(opts&&opts.body)||null});"
            "if(u.indexOf('select-for-print')>=0)return Promise.resolve(J({status:'ok',printer_id:'node_ff',storage_id:'internal',name:'Cube_PETG_25m30s.gcode',print_name:'Cube_PETG_25m30s.gcode'}));"
            "if(u.indexOf('capabilities')>=0)return Promise.resolve(J({status:'ok',read_enabled:true,delete_enabled:false,delete_ui_allowed:false,capabilities:{supported:true,list_files:true,delete_files:false,print_existing_files:true,read_sizes:false,read_mtime:false,browse_directories:false,adapter:'flashforge',storage_types:['internal'],reason:''},printer:{id:'node_ff',name:'FFA5M-1',type:'flashforge'}}));"
            "if(u.indexOf('storages')>=0)return Promise.resolve(J({status:'ok',storages:[{storage_id:'internal',display_name:'" + ("Память принтера" if lang_val == "ru" else "Printer memory") + "',type:'internal',writable:false,online:true,total_bytes:null,free_bytes:null}]}));"
            "if(u.indexOf('/list')>=0)return Promise.resolve(J({status:'ok',total:1,cursor_next:null,entries:[{file_ref:'pfr_x',name:'Cube_PETG_25m30s.gcode',is_directory:false,category:'program',timelapse:false,extension:'.gcode',size_bytes:null,modified_at:null,storage_id:'internal',deletable:false,protected_reason:'unsupported',printable:true,print_blocked_reason:'',active_print:false}]}));"
            "return Promise.resolve(J({}))};"
            "window.confirm=function(){return true};window.alert=function(){};</script>"
            "<link rel='stylesheet' href='" + css_href + "'>"
            "<script type='importmap'>{\"imports\":{\"vue\":\"" + vue_href + "\"}}</script>"
            "<style>html,body{margin:0}.left-col{width:360px;flex:0 0 auto;background:#222}"
            ".main-cols{display:flex;height:600px;width:1200px;gap:8px}main.projects-pane{flex:1 1 auto}</style>"
            "</head><body><div id='app'>"
            "<div class='main-cols'><div class='left-col'></div>"
            "<main class='projects-pane' v-show=\"workspaceView==='projects'\">PROJECTS_AREA</main>"
            + section_html +
            "</div></div><div id='fm-overlay-root'></div><pre id='__res'></pre>"
            "<script type='module'>"
            "import { createApp, ref, computed, nextTick } from 'vue';"
            "const SvgIcon={props:['name','sw','class'],template:'<span class=\"svg-stub\"></span>'};"
            "const app=createApp({setup(){"
            "const lang=ref('" + lang_val + "');const tr=(s)=>s;"
            "const printers=ref([{id:'node_ff',name:'FFA5M-1',type:'flashforge',model:'AD5M',credential_configured:true}]);"
            "const showSettings=ref(false),showDiag=ref(false);const leftColH='600px';"
            #  Alpha 2.900: openPrinterFiles уводит и «Отчёты» — четвёртый рабочий экран в том же
            #  слоте. Без этих двух строк стенд падает на ReferenceError ещё при монтировании.
            "const showReports=ref(false);const closeReports=()=>{showReports.value=false};"
            "const closeDiagnostics=()=>{};const closeSettings=()=>{};"
            "const wsData=ref({node_ff:{status:'IDLE'}});const sendReserved=ref(new Set());"
            "const cellBusy=(pid)=>((wsData.value[pid]||{}).status==='RUNNING')||sendReserved.value.has(pid);"
            "window.__toasts=[];const pushToast=(t,k)=>window.__toasts.push(String(t));"
            "const _printerNameOf=(pid)=>pid;const handleSendResp=(resp,ctx)=>((resp&&resp.accepted)?'accepted':'other');"
            "window.__printStarts=[];const openPrintStart=(ctx)=>window.__printStarts.push(ctx);"
            "const activeModalPrinterId=ref('');const printerFiles=ref([]);const printFileName=ref('');"
            + APPJS[_i0:_i1 + len("const closePrinterFiles = () => { showPrinterFiles.value = false; _pfGen++; };")] +
            ";const workspaceView=computed(()=>showSettings.value?'settings':(showDiag.value?'diagnostics':(showPrinterFiles.value?'printerFiles':'projects')));"
            "window.__ss={openPrinterFiles,workspaceView,pfState};"
            "return { lang, tr, printers, showSettings, showDiag, leftColH, workspaceView, " + pf_names + " };"
            "}});app.component('SvgIcon',SvgIcon);app.mount('#app');"
            "(async()=>{const sl=(m)=>new Promise(r=>setTimeout(r,m));const rv=(r)=>r&&'value'in r?r.value:r;"
            "const out={};const ss=window.__ss;"
            "ss.openPrinterFiles('node_ff');"
            "for(let i=0;i<80;i++){if(['ready','empty','error'].indexOf(rv(ss.pfState))>=0)break;await sl(50);}"
            "await sl(120);await nextTick();"
            "const ws=document.querySelector('.fm-printer-files-workspace');"
            "out.state=rv(ss.pfState);"
            "const cb=ws?ws.querySelector('tbody input[type=checkbox]'):null;"
            "out.cbExists=!!cb;out.cbEnabled=!!(cb&&!cb.disabled);"
            "out.metaNote=!!(ws&&ws.querySelector('.pfw-metanote'));"
            "out.sizeHeader=(ws?ws.textContent:'').indexOf('" + ("Размер" if lang_val == "ru" else "Size") + "')>=0;"
            "out.capNote=(ws?ws.textContent:'').indexOf('" + ("Печать доступна" if lang_val == "ru" else "Printing available") + "')>=0;"
            "if(cb){cb.click();await sl(60);await nextTick();}"
            "const row=ws?ws.querySelector('tbody tr'):null;"
            "out.rowSelected=!!(row&&row.classList.contains('pfw-rowsel'));"
            "const bar=ws?ws.querySelector('.pfw-selbar'):null;"
            "out.selInfo=bar?bar.textContent:'';"
            "const btns=bar?Array.from(bar.querySelectorAll('button')):[];"
            "const byTxt=(t)=>btns.find(b=>b.textContent.indexOf(t)>=0)||null;"
            "const bSel=byTxt('" + ("Выбрать для печати" if lang_val == "ru" else "Select for print") + "');"
            "const bPrn=byTxt('" + ("Печать" if lang_val == "ru" else "Print") + "');"
            "const bDel=byTxt('" + ("Удалить" if lang_val == "ru" else "Delete") + "');"
            "out.bSel=!!bSel;out.bPrn=!!(bPrn&&!bPrn.disabled&&bPrn.classList.contains('pfw-printsel'));"
            "out.bDelDisabled=!!(bDel&&bDel.disabled&&(bDel.title||'').length>0);"
            "out.fitSel=bSel?(bSel.scrollWidth<=bSel.clientWidth+1):null;"
            "out.fitPrn=bPrn?(bPrn.scrollWidth<=bPrn.clientWidth+1):null;"
            "if(bSel){bSel.click();await sl(150);await nextTick();}"
            "out.sfpToasts=(window.__toasts||[]).length;"
            "out.sfpCmd=(window.__fetches||[]).filter(f=>f.u.indexOf('/cmd')>=0).length;"
            "if(bPrn){bPrn.click();await sl(150);await nextTick();}"
            "out.prnDialogs=(window.__printStarts||[]).length;"
            "out.prnDialogC1=window.__printStarts[0]?!!window.__printStarts[0].c1:null;"
            "out.prnCmd=(window.__fetches||[]).filter(f=>f.u.indexOf('/cmd')>=0).length;"
            "const more=ws?ws.querySelector('.pfw-more'):null;"
            "if(more){more.click();await sl(80);await nextTick();}"
            "const menu=document.querySelector('.pfw-rowmenu');"
            "out.rowMenu=!!menu;out.rowMenuItems=menu?menu.querySelectorAll('.pfw-mi').length:0;"
            "out.errors=(window.__e||[]).filter(e=>e.indexOf('favicon')<0).slice(0,5);"
            "document.getElementById('__res').textContent='@@R@@'+JSON.stringify(out)+'@@E@@';})();"
            "</script></body></html>")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True, prefix="fm_pfe_") as _rtd:
        _pg = os.path.join(_rtd, "r.html")
        io.open(_pg, "w", encoding="utf-8", newline="\n").write(html)
        # Alpha 2.834: Edge 150 не отдаёт DOM по --dump-dom (headless detached) -> CDP.
        _dom = _edge_dom.dump_dom_compatible(EDGE, "file:///" + _pg.replace("\\", "/"),
                                             os.path.join(_rtd, "p"),
                                             window_size=(1300, 800), budget_ms=15000)
        _m = re.search(r"@@R@@(\{.*?\})@@E@@", _dom, re.S)
        return json.loads(_m.group(1)) if _m else {}


if not EDGE:
    for _n in range(77, 89):
        check("%d. движок недоступен: %s" % (_n, _ENGINE_WHY), False)
else:
    R = _edge_run("ru")
    check("77. RU: workspace ready, checkbox у non-deletable printable файла АКТИВЕН (сам дефект приёмки)",
          R.get("state") == "ready" and R.get("cbExists") and R.get("cbEnabled"), str(R)[:200])
    check("78. RU: metadata-note видна, колонок Размер/Дата нет (capability-driven для FlashForge)",
          R.get("metaNote") is True and R.get("sizeHeader") is False)
    check("79. RU: capability-note «Печать доступна» видна", R.get("capNote") is True)
    check("80. RU: клик по checkbox выделяет строку (pfw-rowsel)", R.get("rowSelected") is True)
    check("81. RU: selection bar показывает «Выбрано: 1» и имя файла",
          "Выбрано: 1" in (R.get("selInfo") or "") and "Cube_PETG_25m30s.gcode" in (R.get("selInfo") or ""))
    check("82. RU: «Выбрать для печати» есть; «Печать» — primary и активна; «Удалить» disabled с tooltip",
          R.get("bSel") and R.get("bPrn") and R.get("bDelDisabled"))
    check("83. RU: тексты не вылезают из кнопок действий",
          R.get("fitSel") is True and R.get("fitPrn") is True)
    check("84. RU: «Выбрать для печати» -> toast, БЕЗ обращений к /cmd",
          R.get("sfpToasts", 0) >= 1 and R.get("sfpCmd") == 0)
    check("85. RU: «Печать» -> существующий pre-start диалог (c1), /cmd НЕ вызван до подтверждения",
          R.get("prnDialogs") == 1 and R.get("prnDialogC1") is True and R.get("prnCmd") == 0)
    check("86. RU: меню строки ⋯ открывается (3 действия)",
          R.get("rowMenu") is True and R.get("rowMenuItems") == 3)
    check("87. RU: 0 console errors", not R.get("errors"), str(R.get("errors"))[:200])
    E = _edge_run("en")
    check("88. EN: те же элементы работают (checkbox, selbar, печать через диалог, 0 ошибок)",
          E.get("cbEnabled") and E.get("bSel") and E.get("prnDialogs") == 1
          and E.get("sizeHeader") is False and not E.get("errors"), str(E)[:200])

# ════════════════════════════════════════════════════════════════════════════
section("DELETE и границы 2.825 (89-100)")

FFSRC = open(os.path.join(REPO, "app", "printer_files", "flashforge.py"), encoding="utf-8").read()
SEC = open(os.path.join(REPO, "app", "printer_files", "security.py"), encoding="utf-8").read()
check("89. FlashForge delete_files остаётся False (доказанного протокола НЕТ; forensic 2.825: "
      "в проекте только /detail,/control,/gcodeList,/printGcode,/uploadGcode)",
      "delete_files=False," in FFSRC and not FF_CAPS.delete_files)
check("90. предохранитель удаления по умолчанию ВЫКЛЮЧЕН",
      "\nPRINTER_FILE_DELETE_ENABLED_DEFAULT = False" in SEC)
check("91. кнопка удаления строки по-прежнему по deletable (checkbox от неё отвязан)",
      ':disabled="!e.deletable || !pfDeleteAllowed || pfDeleteBusy"' in INDEXHTML)
check("92. bulk-delete удаляет ТОЛЬКО deletable-подмножество выбора",
      "e && e.deletable && !e.is_directory" in APPJS)
check("93. кнопка «Удалить» в selbar активна только при selDeletable и показывает счётчик",
      "pfSummary.selDeletable.length" in INDEXHTML)
check("94. DISPATCH/TRANSPORT по умолчанию False (файловый менеджер их не трогает)",
      "\nDISPATCH_ENABLED = False" in ORCH and "\nTRANSPORT_ENABLED = False" in ORCH
      and "DISPATCH_ENABLED" not in PF_BLOCK)
check("95. схема БД не меняется (нет новых CREATE TABLE/ALTER в изменениях 2.825)",
      "CREATE TABLE" not in _RT_SRC and "ALTER" not in _RT_SRC
      and "CREATE TABLE" not in fn_src("pf_select_for_print"))
check("96. `_incoming/` не используется новым кодом",
      "_incoming" not in _RT_SRC and "_incoming" not in PF_BLOCK)
check("97. workspace placement 2.824 сохранён (страж-тест существует и отдельно зелёный)",
      os.path.isfile(os.path.join(REPO, "tools", "test_printer_files_workspace_placement.py")))
check("98. opaque refs: resolve строго через _PF_REFS с привязкой к printer_id (raw path от UI не принимается)",
      "_PF_REFS.resolve(str(file_ref or ''), pid)" in _RT_SRC
      and "file_refs" in fn_src("pf_delete"))
#  Alpha 2.890: складской модуль поднят до 1.7.25 — он научился видеть слоты CFS у Creality K2
#  (см. tools/test_creality_cfs.py). К файловому менеджеру принтеров это отношения не имеет,
#  смысл проверки прежний: ЭТА подсистема модули не трогает.
#  3.0: cost — «Расчёт заказа» 0.2.0 на месте удалённой «Себестоимости печати» (слово владельца).
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
check("99. модули не тронуты этой подсистемой (версии 1.7.29/0.2.0/0.2.3)",
      (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(open(os.path.join(REPO, "modules", "inventory", "module.json"), encoding="utf-8"))) == "1.7.29"
      and (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(open(os.path.join(REPO, "modules", "cost", "module.json"), encoding="utf-8"))) == "0.2.0"
      and (lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(open(os.path.join(REPO, "modules", "quality", "module.json"), encoding="utf-8"))) == "0.2.3")
check("100. за прогон не открыто НИ ОДНОГО сокета (ловушка пуста)", not _SOCKETS)

# ── Sentinel ─────────────────────────────────────────────────────────────────
section("SENTINEL")
check("S1. sentinel отсутствует в production-исходниках",
      all(SENTINEL not in s for s in (SRV, APPJS, INDEXHTML, APPCSS, RPR, ORCH, FFSRC, SEC)))
check("S2. sentinel определён в оснастке ровно один раз (кавычки)",
      OWN.count('"%s"' % SENTINEL) == 1)
_ART = os.path.join(REPO, "tools", "_e2e_payload.json")
check("S3. test artifacts отсутствуют", not os.path.isfile(_ART))

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_DONE["ok"] = True
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), PASSED[0] + len(FAILED)))
    for n in FAILED:
        print("   - " + n)
    sys.exit(1)
print("PASS: печать файлов с принтера — все %d проверок пройдены; server.py не импортирован (AST); "
      "resolve исполнен в изоляции; pf-блок и printStart исполнены в Node; render в реальном Edge (RU+EN); "
      "0 сокетов" % PASSED[0])
sys.exit(0)
