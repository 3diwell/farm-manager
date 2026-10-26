# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.839 — встроенный сбор контракта Klipper: только чтение и только обезличенно.
#
#  ЗАЧЕМ. Контракт подготовки печати умеет рассказать только сам принтер, а у его
#  владельца нет ни Python, ни терминала, ни адреса принтера. Кнопка в программе
#  решает это — но ровно с той же строгостью, что и CLI: принтеру уходят ТОЛЬКО GET
#  по неизменяемому allowlist, а наружу не выходит ни адреса, ни токена, ни пути.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется: маршрут извлекается разбором AST и исполняется изолированно;
#   * реальных сокетов нет — urllib подменён fake-Moonraker'ом, который ЗАПИСЫВАЕТ метод и путь;
#   * любое обращение к постороннему адресу роняет тест сразу;
#   * рабочие БД/config/DATA_DIR не открываются; печати не запускаются; принтеру ничего не шлётся.
#
#  Запуск:  python tools/test_klipper_contract_report.py     (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import io
import json
import os
import re
import sys
import types
import urllib.error as _urlerr
import urllib.parse as _urlparse
import urllib.request as _urlreq

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "KLIPPER_CONTRACT_REPORT_SENTINEL_2_839"
FAKE_HOST = "127.0.0.1"

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" | " + str(extra)[:220]) if extra else ""))
    return ok


def section(t):
    print("\n--- %s ---" % t)


SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
ORCH = io.open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


from app import klipper_contract_probe as K       # noqa: E402
from app import route_policy_registry as reg      # noqa: E402

print("=== Alpha 2.839: встроенный отчёт контракта Klipper ===")
print("МЕТКА ОСНАСТКИ: %s" % SENTINEL)

# ════════════════════════════════════════════════════════════════════════════
section("A. ALLOWLIST: только доказанно read-only эндпоинты")

check("A1. allowlist непустой и объявлен в production-модуле",
      isinstance(K.ALLOWED_PATHS, tuple) and len(K.ALLOWED_PATHS) >= 5)
check("A2. в allowlist нет исполняющих эндпоинтов",
      not any(("script" in p or "upload" in p or "restart" in p or "emergency" in p
               or "delete" in p or "database" in p) for p in K.ALLOWED_PATHS), str(K.ALLOWED_PATHS))
for bad in ("/printer/gcode/script?script=G28", "/server/files/upload", "/printer/restart",
            "/printer/firmware_restart", "/printer/emergency_stop", "/machine/reboot",
            "/server/database/item", "/access/api_key", "/server/files/delete/x",
            "http://evil/x", "", "/", "../../etc/passwd"):
    check("A3. путь отклонён: %s" % (bad or "<пусто>"), not K.is_allowed(bad))
# Вторая линия защиты: даже если исполняющий путь КАК-ТО попадёт в allowlist, запрещённый
# фрагмент обязан его завернуть. Проверяем прямо: временно расширяем список и возвращаем.
_saved_paths = K.ALLOWED_PATHS
try:
    K.ALLOWED_PATHS = _saved_paths + ("/printer/gcode/script", "/server/files/upload")
    _second_line = (not K.is_allowed("/printer/gcode/script")) and (not K.is_allowed("/server/files/upload"))
finally:
    K.ALLOWED_PATHS = _saved_paths
check("A6. вторая линия защиты: исполняющий путь отклонён даже внутри allowlist", _second_line)
check("A4. произвольный путь вне списка отклонён (fail-closed)",
      not K.is_allowed("/printer/objects/query?anything") and not K.is_allowed("/server/info/x"))
check("A5. collect НЕ запрашивает ничего вне allowlist",
      (lambda seen: all(K.is_allowed(p) for p in seen) and len(seen) == len(K.ALLOWED_PATHS))(
          [p for p in [] or (lambda acc: (K.collect(lambda x: (acc.append(x), ({}, ""))[1]), acc)[1])([])]))

# ════════════════════════════════════════════════════════════════════════════
section("B. РЕДАКЦИЯ и самопроверка")

SECRETS = ["10.0.0.42", "SUPERSECRETTOKEN0123456789", "SN-K2P-000123",
           r"C:\Users\ivan\AppData\Local\3DIWELL", "/home/ivan/printer_data"]
DIRTY = {
    "a": "хост 10.0.0.42 и http://10.0.0.42:7125/printer/info",
    "b": {"token": "SUPERSECRETTOKEN0123456789", "serial": "SN-K2P-000123"},
    "c": [r"C:\Users\ivan\AppData\Local\3DIWELL\config.json", "/home/ivan/printer_data/config"],
    "d": "mac 00:1A:2B:3C:4D:5E, ipv6 fe80::1c2d:3e4f:5a6b:7c8d",
    "e": "api_key=abcdef0123456789abcdef",
    r"C:\Users\ivan\key": "значение",
}
CLEAN = K.redact(DIRTY, SECRETS)
_ser = json.dumps(CLEAN, ensure_ascii=False)
check("B1. IPv4 вычищен", "10.0.0.42" not in _ser)
check("B2. IPv6 вычищен", "fe80::1c2d" not in _ser)
check("B3. MAC вычищен", "00:1A:2B:3C:4D:5E" not in _ser)
check("B4. токен вычищен", "SUPERSECRETTOKEN" not in _ser)
check("B5. серийный номер вычищен", "SN-K2P-000123" not in _ser)
check("B6. путь Windows вычищен", "AppData" not in _ser and "C:\\\\Users" not in _ser)
check("B7. путь Unix вычищен", "/home/ivan" not in _ser)
check("B8. URL вычищен", "http://" not in _ser)
check("B9. api_key=... вычищен", "abcdef0123456789abcdef" not in _ser)
check("B10. КЛЮЧИ словаря тоже чистятся (рекурсивно)",
      not any("Users" in k for k in CLEAN.keys()), list(CLEAN.keys()))
check("B11. самопроверка находит утечку, если редакция отключена",
      bool(K.find_leaks(json.dumps(DIRTY, ensure_ascii=False), SECRETS)))
check("B12. самопроверка чиста после редакции", K.find_leaks(_ser, SECRETS) == [], K.find_leaks(_ser, SECRETS))
check("B13. find_leaks отдаёт КАТЕГОРИИ, а не сами значения",
      all(re.fullmatch(r"[a-z_0-9]+", x) for x in K.find_leaks(json.dumps(DIRTY), SECRETS)))
check("B14. короткие/пустые «секреты» не превращают отчёт в кашу",
      K.redact_text("bed_mesh ok", ["", None, "0", "no"]) == "bed_mesh ok")

# ════════════════════════════════════════════════════════════════════════════
section("C. АНАЛИЗ макросов на синтетическом K2")


def _cfg(macros):
    return {"result": {"status": {"configfile": {"settings": {
        ("gcode_macro " + k.lower()): {"gcode": v} for k, v in macros.items()}}}}}


def scene(macros=None, cmds=None, objects=None, state=None, mesh=None, missing=()):
    macros = macros if macros is not None else {}
    cmds = cmds if cmds is not None else ["G28", "BED_MESH_CALIBRATE"]
    objects = objects if objects is not None else ["webhooks", "configfile", "print_stats",
                                                   "toolhead", "bed_mesh"]
    data = {
        "/server/info": {"result": {"moonraker_version": "v0.9.3"}},
        "/printer/info": {"result": {"software_version": "v0.12.0"}},
        "/printer/objects/list": {"result": {"objects": objects}},
        "/printer/gcode/help": {"result": {c: "" for c in cmds}},
        "/printer/objects/query?configfile": _cfg(macros),
        "/printer/objects/query?toolhead&print_stats&webhooks&idle_timeout": {"result": {"status": {
            "toolhead": {"homed_axes": (state or {}).get("homed", "xyz")},
            "print_stats": {"state": (state or {}).get("ps", "standby")},
            "webhooks": {"state": (state or {}).get("wh", "ready")},
            "idle_timeout": {"state": (state or {}).get("idle", "Ready")}}}},
        "/printer/objects/query?bed_mesh": {"result": {"status": {"bed_mesh": mesh or {
            "profiles": {"default": {}}, "profile_name": "default"}}}},
    }
    for m in missing:
        data.pop(m, None)
    calls = []

    def get(path):
        calls.append(path)
        return (data.get(path), "" if path in data else "no_data")
    return get, calls


VENDOR = {"START_PRINT": "G28\nBED_MESH_CALIBRATE\nM190 S{params.BED_TEMP}\nM109 S{params.EXTRUDER_TEMP}\n",
          "BED_MESH_CALIBRATE": "RESPOND MSG=\"vendor wrapper\"\nBED_MESH_PROFILE LOAD=default\n"}
g, _ = scene(macros=VENDOR)
REP = K.build_report(K.collect(g), app_version="Alpha 2.839", model_label="Creality K2 Plus",
                     generated_at="2026-07-28T00:00:00", secrets=SECRETS)
S = REP["sections"]
check("C1. схема отчёта объявлена", REP["report_schema_version"] == "3diwell-klipper-contract-report-v1")
check("C2. START_PRINT обнаружен", S["start_macro_analysis"]["name"] == "START_PRINT")
check("C3. параметры стартового макроса извлечены",
      S["start_macro_analysis"]["parameters"] == ["BED_TEMP", "EXTRUDER_TEMP"],
      S["start_macro_analysis"]["parameters"])
check("C4. видно, что стартовый макрос делает калибровку сам",
      S["start_macro_analysis"]["performs_bed_mesh"] is True)
check("C5. видно, что он паркует оси сам", S["start_macro_analysis"]["performs_homing"] is True)
check("C6. переопределение BED_MESH_CALIBRATE обнаружено",
      S["bed_mesh_analysis"]["overridden_by_macro"] is True
      and S["bed_mesh_analysis"]["source"] == "gcode_macro")
check("C7. загрузка профиля сетки обнаружена",
      "BED_MESH_PROFILE" in (S["bed_mesh_analysis"]["calls"] or []))
check("C8. кандидаты в критерии завершения перечислены",
      len(S["completion_evidence_candidates"]["candidates"]) >= 4)
check("C9. текущее безопасное состояние прочитано",
      S["current_safe_state"]["print_stats_state"] == "standby"
      and S["current_safe_state"]["homed_axes"] == "xyz")
check("C10. открытые вопросы честны (переопределение названо)",
      any("переопределена" in q for q in REP["unresolved_questions"]), REP["unresolved_questions"])

g2, _ = scene(macros={"PRINT_START": "G28\n"}, cmds=["G28"])
R2 = K.build_report(K.collect(g2), secrets=SECRETS)
check("C11. PRINT_START распознан как стартовый макрос",
      R2["sections"]["start_macro_analysis"]["name"] == "PRINT_START")
check("C12. отсутствие команды калибровки названо честно",
      any("калибровки" in q for q in R2["unresolved_questions"]))

g3, _ = scene(macros={"START_PRINT": "; BED_MESH_CALIBRATE в комментарии\n# G28 тоже\nM117 hi\n"})
R3 = K.build_report(K.collect(g3), secrets=SECRETS)
check("C13. КОММЕНТАРИИ не считаются вызовами команд",
      R3["sections"]["start_macro_analysis"]["performs_bed_mesh"] is False
      and R3["sections"]["start_macro_analysis"]["performs_homing"] is False)
check("C14. тело макроса в отчёте очищено и помечено redacted",
      R3["sections"]["start_macro_analysis"]["body"]["redacted"] is True
      and all(not x.startswith(";") for x in R3["sections"]["start_macro_analysis"]["body"]["lines"]))
_long = {"START_PRINT": "\n".join("G1 X%d" % i for i in range(200))}
g4, _ = scene(macros=_long)
R4 = K.build_report(K.collect(g4), secrets=SECRETS)
check("C15. длинное тело обрезано и это отмечено",
      R4["sections"]["start_macro_analysis"]["body"]["truncated"] is True
      and len(R4["sections"]["start_macro_analysis"]["body"]["lines"]) <= K.MAX_BODY_LINES)
check("C16. полный printer.cfg НЕ экспортируется (только интересные макросы)",
      len(S["relevant_macros"]["macros"]) <= len(K.MACROS_OF_INTEREST)
      and "settings" not in json.dumps(REP))
check("C17. base64-миниатюра не разбирается как G-code",
      K.macro_calls("; thumbnail\n; iVBORw0KGgoBED_MESH_CALIBRATE\n") == [])
check("C18. объекты, которые читает макрос, извлечены",
      K.macro_objects_read("{% if printer.toolhead.homed_axes %}{% endif %}") == ["toolhead"])
check("C19. Z-tilt и QGL извлекаются, если вызываются",
      (lambda m: m["calls_z_tilt"] and m["calls_quad_gantry_level"])(
          K.analyze_macro("START_PRINT", "Z_TILT_ADJUST\nQUAD_GANTRY_LEVEL\n", False, True)))

# Частичный отчёт: часть эндпоинтов недоступна.
g5, _ = scene(macros=VENDOR, missing=("/printer/objects/query?configfile",))
R5 = K.build_report(K.collect(g5), secrets=SECRETS)
check("C20. недоступная конфигурация -> секции unavailable, отчёт partial и честный",
      "configfile_unavailable" in R5["probe_warnings"]
      and R5["endpoints_failed"] and any("недоступна" in q for q in R5["unresolved_questions"]))
check("C21. при недоступности НЕ делается ложный вывод о поддержке автоматики",
      R5["sections"]["bed_mesh_analysis"]["command_exists"] is False
      or R5["sections"]["bed_mesh_analysis"]["overridden_by_macro"] is False)
check("C22. структура отчёта детерминирована (два прогона совпадают побайтно)",
      json.dumps(K.build_report(K.collect(scene(macros=VENDOR)[0]), secrets=SECRETS,
                                generated_at="X"), sort_keys=True)
      == json.dumps(K.build_report(K.collect(scene(macros=VENDOR)[0]), secrets=SECRETS,
                                   generated_at="X"), sort_keys=True))
check("C23. имя файла безопасно (без путей, адресов и пробелов)",
      K.report_filename("Creality K2 Plus", "2026-07-28")
      == "3diwell-klipper-report-Creality-K2-Plus-2026-07-28.json"
      and "/" not in K.report_filename("../../etc", "x"))

# ════════════════════════════════════════════════════════════════════════════
section("D. МАРШРУТ: изолированное исполнение реального кода server.py")

CALLS = []          # (метод, путь) всех обращений к «принтеру»
LOGS = []


class _FR(object):
    def __init__(self, b): self._b = b
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


# Адрес, настроенный у принтера в БАЗЕ. Ловушка пускает только его: если маршрут возьмёт
# адрес откуда-то ещё (например,から тела запроса) — тест упадёт сразу.
PRINTER_HOST = "10.0.0.42"
SCENE = {"data": {}, "reachable": True}


def _fake_urlopen(req, timeout=None):
    url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
    method = (req.get_method() if hasattr(req, "get_method") else "GET")
    body = getattr(req, "data", None)
    host = _urlparse.urlparse(url).hostname or ""
    if host != PRINTER_HOST:
        raise AssertionError("обращение к постороннему адресу: %s" % host)
    path = url.split(str(PRINTER_HOST), 1)[-1]
    path = path[path.find("/", path.find(":") + 1):] if ":" in path[:8] else path
    CALLS.append((method, path, body))
    if not SCENE["reachable"]:
        raise _urlerr.URLError("unreachable")
    for p, d in SCENE["data"].items():
        if path.endswith(p):
            return _FR(json.dumps(d).encode())
    return _FR(b"{}")


_fake_urllib = types.SimpleNamespace(
    request=types.SimpleNamespace(Request=_urlreq.Request, urlopen=_fake_urlopen),
    error=_urlerr, parse=_urlparse)


class _Resp(object):
    def __init__(self, content=None, status_code=200):
        self.content = content
        self.status_code = status_code


async def _mk_body(req):
    return {"ip": "9.9.9.9"}


class _Log(object):
    def _r(self, *a, **k):
        try:
            LOGS.append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            LOGS.append(" ".join(str(x) for x in a))
    info = warning = error = debug = exception = _r


class _Lock(object):
    def __enter__(self): return self
    def __exit__(self, *a): return False


PRINTERS = {}


class _Row(dict):
    def __getitem__(self, k): return dict.get(self, k)


class _Conn(object):
    def execute(self, sql, params=()):
        pid = params[0] if params else ""
        row = PRINTERS.get(pid)
        return types.SimpleNamespace(fetchone=(lambda: row))


NS = {"urllib": _fake_urllib, "json": json, "os": os, "re": re, "time": __import__("time"),
      "socket": types.SimpleNamespace(gethostname=lambda: "farm-pc-01"),
      "log": _Log(), "lock_pr": _Lock(), "conn_pr": _Conn(), "JSONResponse": _Resp,
      "_kcprobe": K, "APP_VERSION": "Alpha 2.839",
      "DATA_DIR": r"C:\Users\ivan\AppData\Local\3DIWELL", "BASE_DIR": r"C:\3DIWELL_Farm_Manager",
      "_req_role": (lambda req: None), "_has_perm": (lambda role, p: True),
      # Заглушка чтения тела: сам маршрут его НЕ читает (это проверяет E1), но при порче
      # «адрес принимается от клиента» код должен дойти до проверки, а не упасть по NameError.
      "_json_body": _mk_body,
      "app": type("A", (), {"get": lambda *a, **k: (lambda f: f),
                            "post": lambda *a, **k: (lambda f: f)})(),
      "Request": object}
for _f in ("_klipper_get_json", "klipper_contract_report"):
    _s = fn_src(_f)
    if not _s:
        print("FAIL — функция %s не найдена" % _f)
        sys.exit(1)
    exec(compile(_s, "<server>", "exec"), NS)
route = NS["klipper_contract_report"]


def call(pid, scene_data=None, reachable=True, role_ok=True):
    CALLS[:] = []
    LOGS[:] = []
    SCENE["data"] = scene_data if scene_data is not None else DEFAULT_DATA
    SCENE["reachable"] = reachable
    NS["_has_perm"] = (lambda role, p: role_ok)
    NS["_req_role"] = (lambda req: (None if role_ok else "observer"))
    r = asyncio.run(route(pid, object()))
    if isinstance(r, _Resp):
        return (r.status_code, r.content if isinstance(r.content, dict) else {})
    return (200, r if isinstance(r, dict) else {})


DEFAULT_DATA = {
    "/server/info": {"result": {"moonraker_version": "v0.9.3"}},
    "/printer/info": {"result": {"software_version": "v0.12.0"}},
    "/printer/objects/list": {"result": {"objects": ["webhooks", "configfile", "print_stats",
                                                     "toolhead", "bed_mesh"]}},
    "/printer/gcode/help": {"result": {"G28": "", "BED_MESH_CALIBRATE": "", "START_PRINT": ""}},
    "/printer/objects/query?configfile": _cfg({
        "START_PRINT": "; напечатано с 10.0.0.42\nG28\nBED_MESH_CALIBRATE\nM190 S{params.BED_TEMP}\n",
        "BED_MESH_CALIBRATE": "RESPOND MSG=\"vendor\"\n"}),
    "/printer/objects/query?toolhead&print_stats&webhooks&idle_timeout": {"result": {"status": {
        "toolhead": {"homed_axes": "xyz"}, "print_stats": {"state": "standby"},
        "webhooks": {"state": "ready"}, "idle_timeout": {"state": "Ready"}}}},
    "/printer/objects/query?bed_mesh": {"result": {"status": {"bed_mesh": {
        "profiles": {"default": {}}, "profile_name": "default"}}}},
}

PRINTERS["pK2"] = _Row({"id": "pK2", "type": "klipper", "ip": "10.0.0.42", "port": 7125,
                        "token": "SUPERSECRETTOKEN0123456789", "serial": "SN-K2P-000123",
                        "model": "Creality K2 Plus", "name": "K2"})
PRINTERS["pBambu"] = _Row({"id": "pBambu", "type": "bambu", "ip": "10.0.0.7", "port": None,
                           "token": "ACCESSCODE1234", "serial": "BBL123", "model": "X1C", "name": "X1"})
PRINTERS["pFF"] = _Row({"id": "pFF", "type": "flashforge", "ip": "10.0.0.8", "port": 8898,
                        "token": "", "serial": "FF1", "model": "AD5M", "name": "FF"})

code, body = call("pK2")
check("D1. отчёт собран для Klipper-принтера", code == 200 and body.get("status") == "ok", body)
check("D2. К ПРИНТЕРУ ушли ТОЛЬКО GET-запросы",
      CALLS and all(m == "GET" for m, _p, _b in CALLS), [c[:2] for c in CALLS[:4]])
check("D3. ни у одного запроса нет тела", all(b in (None, b"") for _m, _p, b in CALLS))
check("D4. запрошены только пути из allowlist",
      all(K.is_allowed(p.split("&_")[0]) or p == "/printer/info" for _m, p, _b in CALLS),
      [p for _m, p, _b in CALLS])
check("D5. gcode/script не запрашивался НИ РАЗУ",
      not any("gcode/script" in p for _m, p, _b in CALLS))
check("D6. upload/restart/emergency не запрашивались",
      not any(("upload" in p or "restart" in p or "emergency" in p) for _m, p, _b in CALLS))
check("D7. схема и имя файла отданы", body.get("report", {}).get("report_schema_version")
      == "3diwell-klipper-contract-report-v1" and body.get("filename", "").endswith(".json"))
_ser_out = json.dumps(body, ensure_ascii=False)
check("D8. в ответе нет адреса принтера", "10.0.0.42" not in _ser_out)
check("D9. в ответе нет токена", "SUPERSECRETTOKEN" not in _ser_out)
check("D10. в ответе нет серийного номера", "SN-K2P-000123" not in _ser_out)
check("D11. в ответе нет id принтера и имени хоста",
      "pK2" not in _ser_out and "farm-pc-01" not in _ser_out)
check("D12. в ответе нет путей DATA_DIR/BASE_DIR", "AppData" not in _ser_out
      and "3DIWELL_Farm_Manager" not in _ser_out)
check("D13. самопроверка отчёта пуста", K.find_leaks(_ser_out, ["10.0.0.42", "SUPERSECRETTOKEN0123456789"]) == [])
check("D14. сводка отдана и содержит ответ про переопределение",
      body.get("summary", {}).get("bed_mesh_overridden") is True)

code, body = call("pBambu")
check("D15. Bambu-принтер отчёт не получает", code == 400 and body.get("reason") == "not_klipper")
code, body = call("pFF")
check("D16. FlashForge-принтер отчёт не получает", code == 400 and body.get("reason") == "not_klipper")
code, body = call("pNOPE")
check("D17. неизвестный принтер -> отказ", code == 404 and body.get("reason") == "no_printer")
check("D18. к неизвестному принтеру не было ни одного обращения", CALLS == [])
code, body = call("pK2", role_ok=False)
check("D19. без права project -> отказ и ни одного запроса",
      code == 403 and CALLS == [])

code, body = call("pK2", reachable=False)
check("D20. недоступный принтер -> честный отказ, отчёт НЕ создаётся",
      code == 503 and body.get("reason") == "unreachable" and not body.get("report"))
check("D21. недоступность ограничена по времени: одна проверка, не семь таймаутов",
      len(CALLS) == 1, [c[:2] for c in CALLS])
_rt_full = fn_src("klipper_contract_report")
_rt = re.sub(r'"""[\s\S]*?"""', '', _rt_full, count=1)   # докстрока не код: иначе проверка ловит свою же прозу
check("D22. офлайн не создаёт device_error и не трогает счётчики ошибок",
      "device_error" not in _rt and "_err_count" not in _rt and "note_printer" not in _rt)
check("D23. маршрут ничего не пишет: ни БД, ни config, ни файлов",
      not any(t in _rt for t in ("_write_config", "INSERT", "UPDATE", "commit()", "open(")))

_partial = dict(DEFAULT_DATA)
_partial.pop("/printer/objects/query?configfile")
code, body = call("pK2", scene_data=_partial)
check("D24. частичный отчёт поддержан и помечен",
      code == 200 and body.get("partial") is True
      and "configfile_unavailable" in body["report"]["probe_warnings"])
check("D25. в частичном отчёте секции получают честный статус",
      ((body.get("report") or {}).get("sections") or {}).get("relevant_macros", {}).get("status")
      in ("unavailable", "complete"))

# ════════════════════════════════════════════════════════════════════════════
section("E. Границы, журнал и предохранители")

check("E1. клиент не передаёт ни адрес, ни токен, ни endpoint (тело запроса НЕ читается вовсе)",
      not any(x in _rt for x in ("_json_body", "data.get(", "req.query", "await req", "req.json")))
check("E2. адрес берётся ИЗ КОНФИГУРАЦИИ принтера по pid",
      "p['ip']" in _rt.replace('"', "'") and "WHERE id=?" in _rt)
check("E3. единственный способ обращения — _klipper_get_json через allowlist",
      "_kcprobe.is_allowed" in _rt and "_klipper_get_json" in _rt)
check("E4. самопроверка ОБЯЗАТЕЛЬНА и стоит перед выдачей отчёта",
      "find_leaks" in _rt and "if _leaks:" in _rt
      and _rt.find("find_leaks") < _rt.rfind("return {"))
check("E5. журнал безопасен: ни адреса, ни токена, ни тела отчёта",
      LOGS and not any(("10.0.0." in x or "SUPERSECRET" in x or "gcode" in x) for x in LOGS), LOGS[:2])
check("E6. журнал называет действие, результат и время",
      any("action=klipper_contract_report" in x and "result=" in x and "elapsed=" in x for x in LOGS),
      LOGS[:2])
check("E7. маршрут зарегистрирован в карте прав как OPERATIONAL/NETWORK",
      any(p.path == "/api/printer/{pid}/klipper-contract-report" and p.method == "POST"
          for p in reg.ALL_POLICIES))
check("E8. недоказанная калибровка остаётся НЕавтоматической (отчёт ничего не включает)",
      "supported_automatic" not in _rt and "build_prestart_plan" not in _rt)
# NB: подстроку "print" искать нельзя — она есть в безобидных путях вроде /printer/info.
# Проверяем ИМЕНА функций запуска и ЛИТЕРАЛЫ команд, а не случайные вхождения.
check("E9. отчёт не запускает ни калибровку, ни печать",
      not any(t in _rt for t in ("_send_file_to_printer", "_klipper_execute_prestart",
                                 "_do_project2_file_print", "BED_MESH_CALIBRATE",
                                 "gcode/script", "server/files/upload", '"G28"', "'G28'")))
check("E10. DISPATCH_ENABLED = False", re.search(r"^DISPATCH_ENABLED = False$", ORCH, re.M) is not None)
check("E11. TRANSPORT_ENABLED = False", re.search(r"^TRANSPORT_ENABLED = False$", ORCH, re.M) is not None)
check("E12. удаление файлов принтера остаётся выключенным",
      "PRINTER_FILE_DELETE_ENABLED_DEFAULT = False" in
      io.open(os.path.join(REPO, "app", "printer_files", "security.py"), encoding="utf-8").read())
#  Alpha 2.891: складской модуль поднят до 1.7.28 — он научился видеть слоты CFS у Creality K2
#  и подписывать их как сам принтер. К диагностике Klipper это отношения не имеет; смысл
#  проверки прежний: ЭТА подсистема модули не трогает.
#  23.09.2026: сверяется контракт модуля с ядром (core_contract из module.json), а не номер выпуска: выпуск склада 1.7.30 при прежнем контракте 1.7.29.
check("E13. модули не тронуты этой подсистемой (версии закреплены)",
      all((lambda _d: _d.get("core_contract") or _d.get("version"))(json.load(io.open(os.path.join(REPO, "modules", m, "module.json"), encoding="utf-8"))) == v
          for m, v in (("inventory", "1.7.29"), ("cost", "0.2.0"), ("quality", "0.2.3"))))   # 3.0: cost — «Расчёт заказа»
check("E14. метка оснастки не попала ни в продуктовый код, ни в отчёт",
      SENTINEL not in SRV and SENTINEL not in _ser_out
      and SENTINEL not in io.open(os.path.join(REPO, "app", "klipper_contract_probe.py"),
                                  encoding="utf-8").read())
check("E15. подтверждение запуска Klipper 2.833 и «Сеть и доступ» 2.837 сохранены",
      "waiting_confirmation" in SRV and "enable_blocked_reason" in SRV)
check("E16. отчёт не сохраняется на диск сервером (ни temp, ни DATA_DIR)",
      "tempfile" not in _rt and "NamedTemporary" not in _rt and "mkstemp" not in _rt)
check("E17. CLI стал обёрткой над тем же ядром (одна реализация протокола)",
      "klipper_contract_probe" in io.open(os.path.join(REPO, "tools", "klipper_probe.py"),
                                          encoding="utf-8").read())
check("E18. артефакт _e2e_payload.json не создан",
      not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
