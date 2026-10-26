# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Политика браузерного Origin (Alpha 2.775): HTTP-гард изменяющих запросов + WebSocket.
#
# БЕЗ сервера/сети/рабочей БД/DATA_DIR: тестируется ЧИСТЫЙ модуль app/security_policy.py
# (только стандартная библиотека) + статическая проводка в server.py.
#
# CHARACTERIZATION: до 2.775 стоял wildcard CORS allow_origins=["*"], серверной проверки
# Origin для изменяющих запросов не было вовсе, а WebSocket-рукопожатие Origin не смотрело.
#
# Запуск: python tools/test_browser_origin_policy.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def code_only(text):
    """Код без комментариев и докстрок: пояснения намеренно упоминают и удалённый
    CORSMiddleware, и заголовки прокси, которым модуль НЕ доверяет."""
    import io
    import tokenize
    try:
        t = ast.parse(text)
    except Exception:
        return text
    blank = set()
    for node in ast.walk(t):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                blank.add(ln)
    rows = ["\n" if (i + 1) in blank else r for i, r in enumerate(text.splitlines(True))]
    txt = "".join(rows)
    try:
        cuts = {}
        for tok in tokenize.generate_tokens(io.StringIO(txt).readline):
            if tok.type == tokenize.COMMENT:
                cuts.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))
        rr = txt.splitlines(True)
        for row, spans in cuts.items():
            s = rr[row - 1]
            for a, b in sorted(spans, reverse=True):
                s = s[:a] + s[b:]
            rr[row - 1] = s
        return "".join(rr)
    except Exception:
        return txt


SRC = code_only(open(os.path.join(REPO, "server.py"), encoding="utf-8").read())

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


print("=== Alpha 2.775: политика браузерного Origin ===")

# ── Чистый модуль политики ──────────────────────────────────────────────────
try:
    from app import security_policy as sp
    _imported = True
except Exception as e:
    _imported = False
    print("  (модуль app/security_policy.py недоступен: %s)" % e)
check("A0. чистый модуль app/security_policy.py импортируется", _imported)

if _imported:
    _POL = code_only(open(os.path.join(REPO, "app", "security_policy.py"), encoding="utf-8").read())
    check("A1. модуль не тянет server.py / FastAPI / sqlite (проверка по живому коду)",
          "FastAPI" not in _POL and "sqlite3" not in _POL and "import server" not in _POL)

    HOST = "127.0.0.1:8000"

    # ── Разрешённые: точное совпадение origin ───────────────────────────────
    ALLOW = [
        ("http://127.0.0.1:8000", "127.0.0.1:8000", "same-origin loopback"),
        ("http://localhost:8000", "localhost:8000", "same-origin localhost"),
        ("http://192.168.1.50:8000", "192.168.1.50:8000", "same-origin LAN IP"),
        ("http://127.0.0.1:8000", "127.0.0.1:8000", "повтор — стабильность"),
        ("HTTP://127.0.0.1:8000", "127.0.0.1:8000", "регистр схемы"),
        ("http://LOCALHOST:8000", "localhost:8000", "регистр hostname"),
        ("http://example.com", "example.com", "дефолтный порт HTTP (80) с обеих сторон"),
        ("https://example.com", "example.com:443", "дефолтный порт HTTPS (443)"),
        ("http://[::1]:8000", "[::1]:8000", "IPv6 loopback"),
    ]
    for origin, host, label in ALLOW:
        check("ALLOW %-46s %s" % (label, origin), sp.is_same_origin(origin, host, "http" if origin.lower().startswith("http:") else "https"))

    # ── Отклоняемые ────────────────────────────────────────────────────────
    DENY = [
        ("http://evil.example", HOST, "чужой домен"),
        ("http://localhost.evil.example:8000", HOST, "похожий hostname (суффикс)"),
        ("http://127.0.0.1.evil.example:8000", HOST, "похожий IP-hostname"),
        ("http://evil.example/127.0.0.1:8000", HOST, "путь-обманка"),
        ("http://127.0.0.1:9000", HOST, "другой порт"),
        ("https://127.0.0.1:8000", HOST, "другая схема"),
        ("null", HOST, "Origin: null"),
        ("", HOST, "пустой Origin"),
        ("не-url", HOST, "битый Origin"),
        ("http://user:pass@evil.example", HOST, "userinfo-обманка"),
        ("http://127.0.0.1:8000 http://evil.example", HOST, "несколько значений Origin"),
        ("http://[::1]:9000", "[::1]:8000", "IPv6, другой порт"),
    ]
    for origin, host, label in DENY:
        check("DENY  %-46s %r" % (label, origin), not sp.is_same_origin(origin, host, "http"))

    # ── Определение изменяющего метода ─────────────────────────────────────
    for m in ("POST", "PUT", "PATCH", "DELETE", "post", "delete"):
        check("MUT   %-6s считается изменяющим" % m, sp.is_mutating_method(m))
    for m in ("GET", "HEAD", "OPTIONS", "get"):
        check("SAFE  %-6s НЕ считается изменяющим" % m, not sp.is_mutating_method(m))

    # ── Итоговое решение гарда ─────────────────────────────────────────────
    check("D1. изменяющий запрос БЕЗ Origin разрешён (слайсеры и нативные клиенты)",
          sp.origin_allowed(None, HOST, "http", "POST") and sp.origin_allowed("", HOST, "http", "POST"))
    check("D2. изменяющий запрос с same-origin разрешён",
          sp.origin_allowed("http://127.0.0.1:8000", HOST, "http", "POST"))
    check("D3. изменяющий запрос с чужим Origin ОТКЛОНЁН",
          not sp.origin_allowed("http://evil.example", HOST, "http", "POST"))
    check("D4. изменяющий запрос с Origin: null ОТКЛОНЁН",
          not sp.origin_allowed("null", HOST, "http", "POST"))
    check("D5. GET с чужим Origin не блокируется гардом (навигация и статика не ломаются)",
          sp.origin_allowed("http://evil.example", HOST, "http", "GET"))

    # ── WebSocket ──────────────────────────────────────────────────────────
    check("W1. WS same-origin принимается", sp.ws_origin_allowed("http://127.0.0.1:8000", HOST, "http"))
    check("W2. WS без Origin принимается (нативные клиенты)", sp.ws_origin_allowed(None, HOST, "http"))
    check("W3. WS чужой Origin отклоняется", not sp.ws_origin_allowed("http://evil.example", HOST, "http"))
    check("W4. WS Origin: null отклоняется", not sp.ws_origin_allowed("null", HOST, "http"))
    check("W5. WS битый Origin отклоняется", not sp.ws_origin_allowed("не-url", HOST, "http"))
    check("W6. WS другой порт отклоняется", not sp.ws_origin_allowed("http://127.0.0.1:9000", HOST, "http"))
    check("W7. WS другая схема отклоняется", not sp.ws_origin_allowed("https://127.0.0.1:8000", HOST, "http"))
    check("W8. WS похожий hostname отклоняется",
          not sp.ws_origin_allowed("http://localhost.evil.example:8000", HOST, "http"))

    # ── Alpha 2.779: ТРАНСПОРТНАЯ схема сокета (регрессия 2.775) ────────────
    # ПОЧЕМУ регрессия дожила до релиза: все проверки W1–W8 выше подают scheme="http",
    # а в бою ws_ep передаёт ws.url.scheme, то есть "ws"/"wss" (из ASGI-скоупа).
    # Браузер в Origin присылает ВСЕГДА http/https — схемы "ws://" в Origin не бывает,
    # поэтому прямое сравнение ws!=http отклоняло собственный интерфейс до accept().
    print("--- Alpha 2.779: транспортная схема WebSocket (ws/wss) ---")

    # 1-2. Собственный браузерный сокет обязан приниматься при РЕАЛЬНОЙ схеме транспорта.
    check("T1. ws + Origin http, тот же host:port — РАЗРЕШЕНО",
          sp.ws_origin_allowed("http://127.0.0.1:8000", "127.0.0.1:8000", "ws"))
    check("T2. wss + Origin https, эффективный порт 443 — РАЗРЕШЕНО",
          sp.ws_origin_allowed("https://example.local", "example.local", "wss"))

    # 3-4. Понижение/повышение транспорта запрещено: ws соответствует ТОЛЬКО http, wss — ТОЛЬКО https.
    check("T3. ws + Origin https — ЗАПРЕЩЕНО (подмена схемы)",
          not sp.ws_origin_allowed("https://127.0.0.1:8000", "127.0.0.1:8000", "ws"))
    check("T4. wss + Origin http — ЗАПРЕЩЕНО (подмена схемы)",
          not sp.ws_origin_allowed("http://example.local", "example.local", "wss"))

    # 5-8. Строгость сравнения при новой схеме не ослабла.
    check("T5. ws, другой порт — ЗАПРЕЩЕНО",
          not sp.ws_origin_allowed("http://127.0.0.1:9000", "127.0.0.1:8000", "ws"))
    check("T6. ws, другой hostname — ЗАПРЕЩЕНО",
          not sp.ws_origin_allowed("http://evil.example:8000", "127.0.0.1:8000", "ws"))
    check("T7. ws, localhost.evil.example — ЗАПРЕЩЕНО (суффикс не считается совпадением)",
          not sp.ws_origin_allowed("http://localhost.evil.example:8000", "localhost:8000", "ws"))
    check("T8. ws, 127.0.0.1.evil.example — ЗАПРЕЩЕНО (префикс не считается совпадением)",
          not sp.ws_origin_allowed("http://127.0.0.1.evil.example:8000", "127.0.0.1:8000", "ws"))

    # 9-10. Формы записи адреса, которые обязаны совпадать.
    check("T9. ws, IPv6 loopback — РАЗРЕШЕНО",
          sp.ws_origin_allowed("http://[::1]:8000", "[::1]:8000", "ws"))
    check("T10. ws, разный регистр hostname и схемы — РАЗРЕШЕНО",
          sp.ws_origin_allowed("HTTP://LOCALHOST:8000", "localhost:8000", "WS"))

    # 11-16. Контракт по «непригодным» Origin при транспортной схеме — без послаблений.
    check("T11. ws, Origin отсутствует — РАЗРЕШЕНО (нативные клиенты, прежний контракт)",
          sp.ws_origin_allowed(None, "127.0.0.1:8000", "ws")
          and sp.ws_origin_allowed("", "127.0.0.1:8000", "ws"))
    check("T12. ws, Origin: null — ЗАПРЕЩЕНО",
          not sp.ws_origin_allowed("null", "127.0.0.1:8000", "ws"))
    check("T13. ws, битый Origin — ЗАПРЕЩЕНО",
          not sp.ws_origin_allowed("не-url", "127.0.0.1:8000", "ws"))
    check("T14. ws, userinfo-обманка — ЗАПРЕЩЕНО",
          not sp.ws_origin_allowed("http://127.0.0.1:8000@evil.example", "127.0.0.1:8000", "ws"))
    check("T15. ws, path/query/fragment в Origin — ЗАПРЕЩЕНО",
          not sp.ws_origin_allowed("http://127.0.0.1:8000/ws", "127.0.0.1:8000", "ws")
          and not sp.ws_origin_allowed("http://127.0.0.1:8000?a=1", "127.0.0.1:8000", "ws")
          and not sp.ws_origin_allowed("http://127.0.0.1:8000#f", "127.0.0.1:8000", "ws"))
    check("T16. ws, несколько значений Origin — ЗАПРЕЩЕНО",
          not sp.ws_origin_allowed("http://127.0.0.1:8000 http://evil.example", "127.0.0.1:8000", "ws"))

    # 17. HTTP-политика 2.775 не сдвинулась ни на шаг (нормализация — только в ws_origin_allowed).
    check("T17. HTTP is_same_origin: 'ws' по-прежнему НЕ равен 'http' (общий парсер не ослаблен)",
          not sp.is_same_origin("http://127.0.0.1:8000", "127.0.0.1:8000", "ws"))
    check("T17b. HTTP origin_allowed сохраняет прежнее поведение",
          sp.origin_allowed("http://127.0.0.1:8000", HOST, "http", "POST")
          and not sp.origin_allowed("http://evil.example", HOST, "http", "POST")
          and not sp.origin_allowed("null", HOST, "http", "POST")
          and sp.origin_allowed(None, HOST, "http", "POST")
          and sp.origin_allowed("http://evil.example", HOST, "http", "GET"))

    # ── 18. Изолированное WebSocket-рукопожатие ────────────────────────────
    # Тот же ПОРЯДОК, что в production ws_ep (Origin -> сессия -> accept), на чистом ASGI:
    # без импорта server.py, без DATA_DIR, без реального порта и без сети.
    def _isolated_ws(origin, host, scheme):
        """Возвращает (accepted, close_code, body_ran) для изолированного эндпоинта."""
        import asyncio
        sent, state = [], {"body_ran": False}
        headers = [(b"host", host.encode())]
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        scope = {"type": "websocket", "scheme": scheme, "path": "/ws", "headers": headers}

        async def receive():
            return {"type": "websocket.connect"}

        async def send(message):
            sent.append(message)

        async def endpoint(scope, receive, send):
            hdr = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            if not sp.ws_origin_allowed(hdr.get("origin"), hdr.get("host"), scope["scheme"]):
                await send({"type": "websocket.close", "code": 1008})
                return
            # здесь в бою стоит проверка сессии (_SECURITY_ENABLED / _session_check) —
            # порядок «Origin -> сессия -> accept» проверяется статически ниже (S10).
            await send({"type": "websocket.accept"})
            state["body_ran"] = True          # тело эндпоинта: подписка на рассылку телеметрии

        asyncio.run(endpoint(scope, receive, send))
        accepted = any(m["type"] == "websocket.accept" for m in sent)
        closes = [m for m in sent if m["type"] == "websocket.close"]
        return accepted, (closes[0].get("code") if closes else None), state["body_ran"]

    _ok_acc, _ok_code, _ok_body = _isolated_ws("http://127.0.0.1:8000", "127.0.0.1:8000", "ws")
    check("W-ISO1. браузерное same-origin рукопожатие ПРИНИМАЕТСЯ (accept, тело запущено)",
          _ok_acc and _ok_code is None and _ok_body)

    _no_acc, _no_code, _no_body = _isolated_ws("http://evil.example", "127.0.0.1:8000", "ws")
    check("W-ISO2. чужой Origin закрывается ДО accept с кодом 1008 (policy violation)",
          (not _no_acc) and _no_code == 1008)
    check("W-ISO3. при отказе тело эндпоинта (рассылка телеметрии) НЕ запускается",
          not _no_body)

    _nl_acc, _nl_code, _nl_body = _isolated_ws("null", "127.0.0.1:8000", "ws")
    check("W-ISO4. Origin: null закрывается до accept, тело не запускается",
          (not _nl_acc) and _nl_code == 1008 and not _nl_body)

    _na_acc, _na_code, _na_body = _isolated_ws(None, "127.0.0.1:8000", "ws")
    check("W-ISO5. нативный клиент без Origin принимается (прежний контракт)",
          _na_acc and _na_code is None and _na_body)

    # ── Заголовки прокси НЕ являются источником истины ──────────────────────
    for h in ("X-Forwarded-For", "X-Real-IP", "Forwarded"):
        check("P. модуль политики не читает заголовок %s (проверка по живому коду)" % h, h not in _POL)

# ── Статическая проводка в server.py ────────────────────────────────────────
print("--- проводка в server.py ---")
check("S1. wildcard CORS удалён", 'allow_origins=["*"]' not in SRC)
check("S2. CORSMiddleware не подключается", "CORSMiddleware" not in SRC)
check("S3. HTTP-гард Origin подключён как middleware",
      "_origin_guard" in SRC and "@app.middleware" in SRC)
check("S4. гард отклоняет ДО вызова обработчика (возврат 403 без call_next)",
      "status_code=403" in SRC and "origin_allowed" in SRC)
check("S5. WebSocket проверяет Origin ДО accept()",
      "ws_origin_allowed" in SRC
      and SRC.index("ws_origin_allowed") < SRC.index("await ws.accept()"))
check("S6. проверка доступа WebSocket сохранена и УСИЛЕНА (Alpha 2.786: сессия + право view)",
      "_ws_auth_state" in SRC and "_ws_access.evaluate" in SRC and "_SECURITY_ENABLED" in SRC)
# Порядок проверяем ВНУТРИ тела ws_ep: имя _session_check(tok) встречается в server.py и
# раньше (определение функции ~7208), поэтому сравнение индексов по всему файлу было бы ложным.
_I0 = SRC.find("async def ws_ep(")
_I1 = SRC.find("\n@app.", _I0 + 1) if _I0 >= 0 else -1
_WS_EP = SRC[_I0:(_I1 if _I1 > 0 else len(SRC))] if _I0 >= 0 else ""
# Alpha 2.786 заменила одиночную проверку сессии на полную авторизацию (сессия, субъект,
# роль, право view) — порядок остался прежним и стал строже, Origin по-прежнему ПЕРВЫЙ.
check("S10. порядок в ws_ep: Origin -> авторизация -> accept (Alpha 2.779 не ослаблена)",
      bool(_WS_EP)
      and "ws_origin_allowed" in _WS_EP and "_ws_auth_state" in _WS_EP
      and _WS_EP.index("ws_origin_allowed") < _WS_EP.index("_ws_auth_state")
      < _WS_EP.index("_ws_access.evaluate") < _WS_EP.index("await ws.accept()"))
check("S11. ws_ep по-прежнему передаёт в политику ФАКТИЧЕСКУЮ схему транспорта",
      "ws.url.scheme" in SRC)
check("S7. _GATE_EXCLUDE не изменён (контур слайсеров не тронут)",
      '"/api/slicer-hook"' in SRC and '"/api/files/local"' in SRC)
check("S8. ролевая модель не тронута", "_ROLE_PERMS" in SRC and "_route_perm" in SRC)
check("S9. /api/printers не тронут", "SELECT * FROM printers ORDER BY order_idx ASC" in SRC)

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
