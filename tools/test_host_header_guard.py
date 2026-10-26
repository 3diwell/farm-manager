# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-124 (Alpha 3.0) — защита от подмены DNS при выключенном входе: проверка заголовка Host.

ЗАЧЕМ. При подмене DNS чужая страница evil.example получает адрес 127.0.0.1, и браузер
шлёт Origin=http://evil.example:PORT вместе с Host=evil.example:PORT. Они совпадают, и
проверка Origin считает страницу «своей». Без входа больше ничего её не останавливало:
она могла ставить модули, перезапускать программу, заводить своего администратора.

ЧТО ПРОВЕРЯЕТСЯ.
  1. Чистая политика app/host_header_policy.py — таблица «пропустить / отказать».
  2. Слой _HostGuard из server.py (извлечён разбором дерева) на игрушечном ASGI-приложении:
     HTTP 421 без вызова обработчика, WebSocket закрыт кодом 1008 до accept, флаг входа
     читается на каждый запрос.
  3. Подключение: слой зарегистрирован последним, то есть он самый внешний.
  4. НАСТОЯЩИЙ изолированный server.py (--fm-packaged-e2e: своя папка данных, config, замок,
     порт; принтеры и модули выключены): чужой Host -> 421 и модуль не записан, WebSocket
     с чужим Host отклонён; 127.0.0.1 и localhost работают; после включения входа
     проверки Host нет; после выключения — снова есть.

Запуск:  python tools/test_host_header_guard.py        (0 = всё зелёное)
"""
import ast
import asyncio
import importlib.util
import io
import json
import os
import re
import secrets
import shutil
import socket
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SERVER = os.path.join(ROOT, "server.py")
POLICY_PATH = os.path.join(ROOT, "app", "host_header_policy.py")

PASS = FAIL = 0
FAILED = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS — %s" % name)
    else:
        FAIL += 1
        FAILED.append(name)
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,)) if detail else ""))


def sec(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


from app import host_header_policy as HP   # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
sec("1. Чистая политика: только стандартная библиотека")

psrc = io.open(POLICY_PATH, encoding="utf-8").read()
ptree = ast.parse(psrc)
imports = set()
for n in ast.walk(ptree):
    if isinstance(n, ast.Import):
        imports.update(a.name.split(".")[0] for a in n.names)
    elif isinstance(n, ast.ImportFrom):
        imports.add((n.module or "").split(".")[0])
check("1.1 политика не тянет фреймворк, БД и сеть",
      not (imports & {"fastapi", "starlette", "sqlite3", "socket", "urllib", "server", "uvicorn"}),
      sorted(imports))
_dns_calls = [n for n in ast.walk(ptree) if isinstance(n, ast.Call)
              and re.search(r"gethostby|getaddrinfo|getfqdn|gethostname",
                            ast.get_source_segment(psrc, n.func) or "")]
check("1.2 политика не разрешает имена через DNS (ни одного такого вызова)", not _dns_calls,
      [ast.get_source_segment(psrc, n) for n in _dns_calls])

NAMES = HP.local_machine_names(["FARM-PC", "Ферма"])
check("1.3 имена компьютера: нижний регистр, .local и punycode",
      {"farm-pc", "farm-pc.local"} <= NAMES
      and any(n.startswith("xn--") for n in NAMES)
      and any(n.startswith("xn--") and n.endswith(".local") for n in NAMES), sorted(NAMES))
check("1.4 пустые и мусорные имена в список не попадают",
      HP.local_machine_names(["", None, "  ", "a b", "x@y"]) == frozenset())

DENY = [
    "evil.example:8000", "evil.example", "localhost.evil.example:8000",
    "127.0.0.1.evil.example", "farm:8000", "farm-pc.evil.example",
    "127.0.0.1 evil.example", "a b:8000", "evil.example@127.0.0.1:8000",
    "127.0.0.1:8000/x", "127.0.0.1:99999", "evil.local", "xlocalhost",
]
for i, h in enumerate(DENY, 1):
    ok, why = HP.host_allowed(h, "http", auth_enabled=False, local_names=NAMES)
    check("1.5.%d вход выключен: отказ для %r" % (i, h), ok is False and why.startswith("host_"),
          (ok, why))

ALLOW = [
    "127.0.0.1:8000", "127.0.0.1", "localhost:8000", "LOCALHOST.", "localhost",
    "[::1]:8000", "192.168.1.50:8000", "0.0.0.0:8000", "10.0.0.7", "a.localhost:8000",
    "FARM-PC:8000", "farm-pc.local:8000", "farm-pc.", "[fe80::1]:8000",
]
for i, h in enumerate(ALLOW, 1):
    ok, why = HP.host_allowed(h, "http", auth_enabled=False, local_names=NAMES)
    check("1.6.%d вход выключен: пропуск для %r" % (i, h), ok is True, (ok, why))

cyr = [n for n in NAMES if n.startswith("xn--") and not n.endswith(".local")][0]
check("1.7 кириллическое имя компьютера проходит в виде punycode",
      HP.host_allowed(cyr + ":8000", "http", auth_enabled=False, local_names=NAMES)[0] is True)
check("1.8 отсутствующий и пустой Host пропускаются",
      HP.host_allowed(None, "http", auth_enabled=False, local_names=NAMES)[0] is True
      and HP.host_allowed("", "http", auth_enabled=False, local_names=NAMES)[0] is True)
check("1.9 WebSocket-схема разбирается так же",
      HP.host_allowed("evil.example:8000", "ws", auth_enabled=False, local_names=NAMES)[0] is False
      and HP.host_allowed("127.0.0.1:8000", "ws", auth_enabled=False, local_names=NAMES)[0] is True)
check("1.10 вход включён: проверки нет вовсе",
      all(HP.host_allowed(h, "http", auth_enabled=True, local_names=NAMES)[0] is True
          for h in DENY))
check("1.11 без списка имён чужое имя всё равно отклоняется",
      HP.host_allowed("evil.example", "http", auth_enabled=False)[0] is False
      and HP.host_allowed("localhost", "http", auth_enabled=False)[0] is True)

T = HP.refusal_text(8123)
check("1.12 текст отказа: по-русски и по-английски, с адресом localhost и путём к «Доступ и аудит»",
      "http://localhost:8123" in T and "Доступ и аудит" in T and "Access and audit" in T
      and "Адрес не разрешён" in T and "not allowed" in T, T)

# ─────────────────────────────────────────────────────────────────────────────
sec("2. Слой _HostGuard из server.py на игрушечном ASGI-приложении")

SRC = io.open(SERVER, encoding="utf-8", errors="replace").read()
TREE = ast.parse(SRC)


def top_node(name, kind):
    for n in TREE.body:
        if isinstance(n, kind) and n.name == name:
            return n
    return None


guard_node = top_node("_HostGuard", ast.ClassDef)
coll_node = top_node("_collect_host_local_names", ast.FunctionDef)
check("2.1 класс _HostGuard и сбор имён найдены на верхнем уровне server.py",
      guard_node is not None and coll_node is not None)

guard_src = ast.get_source_segment(SRC, guard_node) if guard_node else ""
check("2.2 это чистый ASGI-слой (не @app.middleware(\"http\"), который не видит WebSocket)",
      "async def __call__(self, scope, receive, send)" in guard_src
      and not guard_node.decorator_list if guard_node else False)
check("2.3 флаг входа читается на каждый запрос внутри __call__",
      "auth_enabled=_SECURITY_ENABLED" in guard_src)
coll_src = ast.get_source_segment(SRC, coll_node) if coll_node else ""
check("2.4 имена компьютера собираются без DNS (без getfqdn/gethostbyaddr/gethostbyname)",
      "gethostname" in coll_src and not re.search(r"getfqdn|gethostbyaddr|gethostbyname|getaddrinfo",
                                                   coll_src))


class _Log:
    def __init__(self):
        self.lines = []

    def debug(self, *a):
        self.lines.append(a)

    info = warning = error = debug


from starlette.responses import Response as _StResponse   # noqa: E402

NS = {
    "_host_policy": HP, "_SECURITY_ENABLED": False, "socket": socket, "os": os,
    "log": _Log(), "_exc_brief": lambda: "err", "Response": _StResponse,
    "_active_server_port": lambda: 8765,
}
if guard_node is not None and coll_node is not None:
    exec(compile(ast.Module(body=[coll_node, guard_node], type_ignores=[]), SERVER, "exec"), NS)
    NS["_HOST_LOCAL_NAMES"] = NS["_collect_host_local_names"]()


class Toy:
    """Игрушечное приложение: запоминает, дошёл ли до него запрос."""

    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append(scope["type"])
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ok"})
        elif scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.accept"})
        elif scope["type"] == "lifespan":
            pass


def run_scope(kind, host, method="GET"):
    toy = Toy()
    guard = NS["_HostGuard"](toy)
    sent = []
    inbox = [{"type": "websocket.connect"}] if kind == "websocket" else \
        [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        return inbox.pop(0) if inbox else {"type": "http.disconnect"}

    async def send(msg):
        sent.append(msg)

    headers = [] if host is None else [(b"host", host.encode("latin-1"))]
    scope = {"type": kind, "scheme": "ws" if kind == "websocket" else "http", "method": method,
             "path": "/api/modules/install", "raw_path": b"/api/modules/install",
             "query_string": b"", "headers": headers + [(b"origin", b"http://" + (host or "").encode())],
             "http_version": "1.1", "root_path": ""}
    asyncio.run(guard(scope, receive, send))
    return toy.calls, sent


if "_HostGuard" in NS:
    NS["_SECURITY_ENABLED"] = False
    calls, sent = run_scope("http", "evil.example:8765", "POST")
    start = next((m for m in sent if m["type"] == "http.response.start"), {})
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    hdrs = dict(start.get("headers") or [])
    check("2.5 вход выключен, POST с чужим Host -> 421, обработчик НЕ вызван",
          start.get("status") == 421 and calls == [], (start.get("status"), calls))
    check("2.6 ответ отказа — текст UTF-8 по-русски и по-английски, с портом программы",
          b"text/plain" in hdrs.get(b"content-type", b"") and b"utf-8" in hdrs.get(b"content-type", b"")
          and "http://localhost:8765" in body.decode("utf-8") and "Доступ и аудит" in body.decode("utf-8")
          and "Access and audit" in body.decode("utf-8"), hdrs)
    check("2.7 чужой Host в ответ не подставляется", b"evil.example" not in body)
    calls, sent = run_scope("http", "evil.example:8765", "GET")
    start = next((m for m in sent if m["type"] == "http.response.start"), {})
    check("2.8 GET с чужим Host тоже 421 (чтение ответа — та же утечка)",
          start.get("status") == 421 and calls == [])
    calls, sent = run_scope("websocket", "evil.example:8765")
    check("2.9 WebSocket с чужим Host закрыт кодом 1008 до accept, приложение не вызвано",
          calls == [] and sent == [{"type": "websocket.close", "code": 1008}], (calls, sent))
    for h in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765", None):
        calls, sent = run_scope("http", h, "POST")
        start = next((m for m in sent if m["type"] == "http.response.start"), {})
        check("2.10 Host=%r проходит до обработчика" % (h,), calls == ["http"] and start.get("status") == 200,
              (calls, start.get("status")))
    calls, sent = run_scope("websocket", "127.0.0.1:8765")
    check("2.11 WebSocket с 127.0.0.1 проходит до приложения",
          calls == ["websocket"] and sent and sent[0]["type"] == "websocket.accept", (calls, sent))

    NS["_SECURITY_ENABLED"] = True
    calls, sent = run_scope("http", "evil.example:8765", "POST")
    check("2.12 вход включён на ходу — следующий же запрос проверку Host не проходит",
          calls == ["http"], calls)
    calls, sent = run_scope("websocket", "evil.example:8765")
    check("2.13 вход включён: WebSocket с любым Host идёт дальше (решают cookie и Origin)",
          calls == ["websocket"], calls)
    NS["_SECURITY_ENABLED"] = False
    calls, sent = run_scope("http", "evil.example:8765", "POST")
    check("2.14 вход выключен на ходу — проверка снова действует", calls == [], calls)

    toy = Toy()
    g = NS["_HostGuard"](toy)
    asyncio.run(g({"type": "lifespan"}, None, None))
    check("2.15 lifespan проходит без проверки", toy.calls == ["lifespan"])

    _orig = HP.host_allowed
    try:
        def _boom(*a, **k):
            raise RuntimeError("x")
        HP.host_allowed = _boom
        calls, sent = run_scope("http", "evil.example:8765", "POST")
        check("2.16 сломалась сама проверка — запрос пропускается (владельца не запираем)",
              calls == ["http"], calls)
    finally:
        HP.host_allowed = _orig

# ─────────────────────────────────────────────────────────────────────────────
sec("3. Подключение в server.py")

check("3.1 политика импортирована", "from app import host_header_policy as _host_policy" in SRC)
reg_lines = [i for i, l in enumerate(SRC.splitlines()) if l.strip() == "app.add_middleware(_HostGuard)"]
mw_lines = [i for i, l in enumerate(SRC.splitlines())
            if l.strip().startswith("@app.middleware(") or
            (l.strip().startswith("app.add_middleware(") and "_HostGuard" not in l)]
check("3.2 _HostGuard зарегистрирован ровно один раз", len(reg_lines) == 1, reg_lines)
check("3.3 зарегистрирован ПОСЛЕ всех остальных слоёв — значит самый внешний",
      reg_lines and mw_lines and reg_lines[0] > max(mw_lines), (reg_lines, mw_lines))
check("3.4 прежние слои не тронуты: _origin_guard и _auth_gate на месте",
      "async def _origin_guard(request, call_next)" in SRC and "async def _auth_gate(request, call_next)" in SRC)
check("3.5 отдельной настройки «разрешённые имена» нет",
      not re.search(r"allowed_hosts|trusted_hosts|host_allowlist", SRC, re.I))

# Порядок, который реально собирает Starlette: последний add_middleware — первый в стеке.
try:
    from fastapi import FastAPI  # noqa: E402
    probe = FastAPI()

    @probe.middleware("http")
    async def _m(request, call_next):
        return await call_next(request)
    probe.add_middleware(NS["_HostGuard"])
    check("3.6 Starlette ставит последний добавленный слой внешним (порядок-основа п.3.3)",
          probe.user_middleware[0].cls is NS["_HostGuard"])
except Exception as e:
    check("3.6 Starlette ставит последний добавленный слой внешним", False, e)

# ─────────────────────────────────────────────────────────────────────────────
sec("4. Настоящий изолированный server.py")

RV_PATH = os.path.join(ROOT, "tools", "validation", "ui", "run_ui_verification.py")
_spec = importlib.util.spec_from_file_location("fm_run_ui_iso_hostguard", RV_PATH)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)


def http(port, method, path, host, body=None, extra=None, timeout=60.0):
    """-> (код, заголовки-строкой, тело-строкой). Соединение всегда на 127.0.0.1:
    так и выглядит подмена DNS — браузер пришёл на петлю, но с чужим именем."""
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    head = "%s %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\nContent-Length: %d\r\n" % (
        method, path, host, len(raw))
    if body is not None:
        head += "Content-Type: application/json\r\n"
    for k, v in (extra or {}).items():
        head += "%s: %s\r\n" % (k, v)
    s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    s.settimeout(timeout)
    s.sendall(head.encode("utf-8") + b"\r\n" + raw)
    buf = b""
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    s.close()
    sep = buf.find(b"\r\n\r\n")
    hdr = buf[:sep].decode("latin-1") if sep > 0 else ""
    payload = buf[sep + 4:] if sep >= 0 else buf
    if "transfer-encoding: chunked" in hdr.lower():
        out, rest = b"", payload
        while True:
            e = rest.find(b"\r\n")
            if e < 0:
                break
            try:
                n = int(rest[:e].split(b";")[0], 16)
            except Exception:
                break
            if n == 0:
                break
            out += rest[e + 2:e + 2 + n]
            rest = rest[e + 2 + n + 2:]
        payload = out
    try:
        code = int(hdr.split(" ", 2)[1])
    except Exception:
        code = 0
    return code, hdr, payload.decode("utf-8", "replace")


def ws_handshake(port, host, timeout=20.0):
    """Код ответа на рукопожатие WebSocket /ws: 101 — принято, иначе — отказ."""
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    req = ("GET /ws HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (host, key))
    s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
    s.settimeout(timeout)
    s.sendall(req.encode("latin-1"))
    buf = b""
    try:
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    s.close()
    try:
        return int(buf.split(b" ", 2)[1])
    except Exception:
        return 0


def tree_listing(p):
    out = []
    for dp, dn, fn in os.walk(p):
        for f in fn:
            out.append(os.path.relpath(os.path.join(dp, f), p))
    return sorted(out)


run_dir = tempfile.mkdtemp(prefix="fmhostg")
port = rv.free_local_port()
contract = rv.build_e2e_contract(run_dir, port)
os.makedirs(contract["data_dir"], exist_ok=True)
rv.write_e2e_marker(contract)
proof, problems = rv.check_e2e_contract(contract, run_dir)
check("4.1 изоляция доказана до запуска",
      not [k for k in problems if k not in ("data_dir_empty", "disabled_printers")], problems)
prod_dir = rv.production_data_dir()
prod_before = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
env = rv.server_env(contract, run_dir)
proc, _logs = rv.spawn([sys.executable, SERVER, rv.E2E_FLAG],
                       os.path.join(run_dir, "server"), env=env, cwd=ROOT)
ok, why = rv.wait_http(port, "/api/printers", proc, 120)
check("4.2 изолированный сервер поднялся", ok, why)

EVIL = "evil.example:%d" % port
try:
    if ok:
        c, _h, b = http(port, "GET", "/", "127.0.0.1:%d" % port)
        check("4.3 вход выключен: интерфейс по 127.0.0.1 открывается", c == 200 and "<html" in b.lower(), c)
        c, _h, b = http(port, "GET", "/", "localhost:%d" % port)
        check("4.4 вход выключен: интерфейс по localhost открывается", c == 200 and "<html" in b.lower(), c)
        c, _h, b = http(port, "GET", "/ui3", "localhost:%d" % port)
        check("4.5 интерфейс 3.0 по localhost открывается", c == 200 and "<html" in b.lower(), c)
        c, _h, b = http(port, "GET", "/api/printers", "127.0.0.1:%d" % port)
        check("4.6 API по 127.0.0.1 работает", c == 200, c)

        c, h, b = http(port, "GET", "/", EVIL)
        check("4.7 подмена DNS: страница с чужим Host -> 421", c == 421, c)
        check("4.8 объяснение по-русски и по-английски, с адресом localhost:<порт>",
              "Адрес не разрешён" in b and "not allowed" in b
              and ("http://localhost:%d" % port) in b and "Доступ и аудит" in b, b[:200])
        check("4.9 чужое имя в ответ не подставлено", "evil.example" not in b)
        c, _h, b = http(port, "GET", "/api/printers", EVIL)
        check("4.10 подмена DNS: чтение API -> 421", c == 421, c)

        data_dir = contract["data_dir"]
        before = tree_listing(data_dir)
        c, _h, b = http(port, "POST", "/api/modules/install", EVIL,
                        extra={"Origin": "http://" + EVIL,
                               "Content-Type": "multipart/form-data; boundary=x"})
        after = tree_listing(data_dir)
        check("4.11 подмена DNS: установка модуля (Origin совпадает с Host) -> 421", c == 421, c)
        mods_before = [p for p in before if p.lower().startswith("modules")]
        mods_after = [p for p in after if p.lower().startswith("modules")]
        check("4.12 в папке модулей ничего не появилось", mods_before == mods_after,
              set(mods_after) ^ set(mods_before))
        c, _h, b = http(port, "POST", "/api/auth/setup", EVIL,
                        body={"username": "intruder", "password": "intruder-pass"},
                        extra={"Origin": "http://" + EVIL})
        check("4.13 подмена DNS: завести своего администратора нельзя -> 421", c == 421, c)

        check("4.14 WebSocket /ws с чужим Host отклонён", ws_handshake(port, EVIL) not in (0, 101))
        check("4.15 WebSocket /ws с 127.0.0.1 подключается",
              ws_handshake(port, "127.0.0.1:%d" % port) == 101)
        check("4.16 WebSocket /ws с localhost подключается",
              ws_handshake(port, "localhost:%d" % port) == 101)

        # Включаем вход настоящим путём (как владелец в «Доступ и аудит»).
        user = "e2e_admin"
        pwd = secrets.token_urlsafe(16)
        c, h, b = http(port, "POST", "/api/auth/setup", "127.0.0.1:%d" % port,
                       body={"username": user, "password": pwd})
        m = re.search(r"(?im)^set-cookie:\s*fm_session=([^;\r\n]+)", h)
        check("4.17 вход включён с 127.0.0.1", c == 200 and m is not None, (c, b[:120]))
        cookie = "fm_session=%s" % (m.group(1) if m else "")
        c, _h, b = http(port, "GET", "/api/auth/status", EVIL)
        check("4.18 вход включён: проверки Host нет (открытый маршрут отвечает 200)", c == 200, c)
        c, _h, b = http(port, "GET", "/api/printers", EVIL)
        check("4.19 вход включён: чужое имя без cookie упирается во вход (401), а не в Host", c == 401, c)
        c, _h, b = http(port, "GET", "/api/printers", "127.0.0.1:%d" % port, extra={"Cookie": cookie})
        check("4.20 вход включён: владелец с сессией работает", c == 200, c)

        # Выключаем вход — проверка Host возвращается сразу, без перезапуска.
        c, _h, b = http(port, "POST", "/api/auth/disable", "127.0.0.1:%d" % port,
                        body={"password": pwd}, extra={"Cookie": cookie})
        check("4.21 вход выключен обратно", c == 200, (c, b[:120]))
        c, _h, b = http(port, "GET", "/api/printers", EVIL)
        check("4.22 после выключения входа чужой Host снова -> 421", c == 421, c)
        c, _h, b = http(port, "GET", "/api/printers", "localhost:%d" % port)
        check("4.23 после выключения входа localhost работает", c == 200, c)
finally:
    try:
        rv.kill_own(proc.pid)
    except Exception:
        pass
    time.sleep(1.0)

prod_after = sorted(os.listdir(prod_dir)) if os.path.isdir(prod_dir) else []
check("4.24 рабочая папка данных не изменилась", prod_before == prod_after,
      set(prod_before) ^ set(prod_after))
shutil.rmtree(run_dir, ignore_errors=True)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS, FAIL))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAIL else 0)
