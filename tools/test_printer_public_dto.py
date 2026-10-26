# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Безопасный публичный DTO принтеров (Alpha 2.777, закрытие S-3).
#
# БЕЗ сервера/сети/принтеров/рабочей БД/DATA_DIR: обработчик g_printers извлекается из
# server.py ДОСЛОВНО через AST, БД — ':memory:'. Реальные credentials не используются —
# только уникальные фиктивные sentinel-строки, по которым ищется утечка.
#
# CHARACTERIZATION: до 2.777 GET /api/printers делал SELECT * + dict(row), поэтому в JSON
# уходил token — access code Bambu, serial:checkcode FlashForge, API key Klipper. Любой
# новый столбец БД автоматически попадал бы в ответ.
#
# Запуск: python tools/test_printer_public_dto.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import json
import os
import re
import sqlite3
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


def grab(fn_name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name:
            return ast.get_source_segment(SRC, n)
    raise AssertionError("функция не найдена: " + fn_name)


def _grab_assign(name):
    """Значение модульной константы из server.py — literal_eval, без исполнения чужого кода."""
    for n in ast.walk(TREE):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return eval(compile(ast.Expression(n.value), "<const>", "eval"),
                        {"frozenset": frozenset, "__builtins__": {}}, {})
    raise AssertionError("константа не найдена: " + name)


# ── Уникальные фиктивные секреты: по ним ищем утечку в любом выводе ──────────
S_BAMBU = "BAMBU_SECRET_SENTINEL_2_777"
S_FF = "FLASHFORGE_CHECKCODE_SENTINEL_2_777"
S_KLIPPER = "KLIPPER_API_KEY_SENTINEL_2_777"
SENTINELS = (S_BAMBU, S_FF, S_KLIPPER)

DDL = ("CREATE TABLE printers (id TEXT PRIMARY KEY, name TEXT, type TEXT DEFAULT 'bambu', "
       "ip TEXT, port INTEGER, token TEXT, last_parts TEXT DEFAULT '{}', order_idx INTEGER DEFAULT 0, "
       "gen TEXT DEFAULT 'auto', serial TEXT DEFAULT '', model TEXT DEFAULT '', "
       "future_secret_column TEXT DEFAULT '')")   # столбец, которого DTO знать не должен

ROWS = [
    ("pr1", "Bambu X1", "bambu", "10.0.0.11", 8883, S_BAMBU, "01PFAKESERIAL1", "X1C"),
    ("pr2", "FlashForge", "flashforge", "10.0.0.12", 8898, S_FF, "", "AD5M"),
    ("pr3", "Klipper", "klipper", "10.0.0.13", 7125, S_KLIPPER, "", "Voron"),
    ("pr4", "Без токена", "bambu", "10.0.0.14", 8883, "", "", "P1S"),
]


def make_env():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(DDL)
    for i, (pid, nm, tp, ip, port, tok, ser, mdl) in enumerate(ROWS):
        conn.execute("INSERT INTO printers (id, name, type, ip, port, token, serial, model, order_idx, "
                     "future_secret_column) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (pid, nm, tp, ip, port, tok, ser, mdl, i, "FUTURE_COLUMN_SENTINEL"))
    conn.commit()
    ns = {"threading": threading, "os": os, "json": json,
          "conn_pr": conn, "lock_pr": threading.Lock(),
          "_resolve_cover": (lambda m: {"model_key": (m or "").lower() or None, "cover_url": ""}),
          "JSONResponse": (lambda d, status_code=200: {"_json": d, "_code": status_code})}
    try:
        from app import printer_dto as _dto
        ns["_printer_dto"] = _dto
    except Exception:
        pass
    #  2.986: g_printers с 2.983 (R-104) спрашивает у модели, есть ли нагрев камеры.
    #  Песочница исполняет ДОСЛОВНЫЙ исходник, поэтому подкладываем и эту функцию с её
    #  опорой — иначе получаем NameError вместо проверки утечки секретов.
    ns["re"] = re
    ns["_CHAMBER_HEATER_MODEL_KEYS"] = _grab_assign("_CHAMBER_HEATER_MODEL_KEYS")
    exec(grab("_norm_model_key"), ns)
    exec(grab("_chamber_heater_by_model"), ns)
    exec(grab("g_printers"), ns)
    return ns, conn


print("=== Alpha 2.777: безопасный публичный DTO принтеров ===")

# ── Чистый модуль DTO ───────────────────────────────────────────────────────
try:
    from app import printer_dto as dto
    _has_dto = True
except Exception as e:
    _has_dto = False
    print("  (модуль app/printer_dto.py недоступен: %s)" % e)
check("A0. чистый модуль app/printer_dto.py импортируется", _has_dto)

if _has_dto:
    src_dto = open(os.path.join(REPO, "app", "printer_dto.py"), encoding="utf-8").read()
    check("A1. модуль не импортирует server.py / FastAPI / sqlite",
          "import server" not in src_dto and "FastAPI" not in src_dto and "sqlite3" not in src_dto)
    check("A2. используется ЯВНЫЙ allowlist полей", "PUBLIC_PRINTER_FIELDS" in src_dto)
    check("A3. нет blacklist-подхода (копия строки с последующим удалением token)",
          'pop("token")' not in src_dto and "pop('token')" not in src_dto)

    row = {"id": "pr1", "name": "X1", "type": "bambu", "ip": "10.0.0.11", "port": 8883,
           "token": S_BAMBU, "serial": "01PFAKESERIAL1", "model": "X1C", "order_idx": 0,
           "last_parts": "{}", "future_secret_column": "FUTURE_COLUMN_SENTINEL"}
    orig = dict(row)
    d = dto.printer_public_dto(row)
    js = json.dumps(d, ensure_ascii=False)

    check("1. DTO Bambu: token отсутствует, credential_configured=True",
          "token" not in d and d.get("credential_configured") is True and S_BAMBU not in js)
    check("5. неизвестный будущий столбец БД НЕ попал в DTO",
          "future_secret_column" not in d and "FUTURE_COLUMN_SENTINEL" not in js)
    check("6. исходная строка БД НЕ мутирована", row == orig)
    check("7. DTO сериализуем в JSON", isinstance(js, str) and len(js) > 10)
    check("A4. last_parts (кэш телеметрии) в DTO не попадает", "last_parts" not in d)

    check("2. без token -> credential_configured=False",
          dto.printer_public_dto({**row, "token": ""}).get("credential_configured") is False)
    check("8a. token=None -> False", dto.printer_public_dto({**row, "token": None}).get("credential_configured") is False)
    check("8b. token из пробелов -> False", dto.printer_public_dto({**row, "token": "   "}).get("credential_configured") is False)

    check("3. FlashForge serial:checkcode полностью отсутствует",
          S_FF not in json.dumps(dto.printer_public_dto({**row, "type": "flashforge", "token": S_FF})))
    check("4. Klipper API key отсутствует",
          S_KLIPPER not in json.dumps(dto.printer_public_dto({**row, "type": "klipper", "token": S_KLIPPER})))
    check("A5. не отдаётся ни длина, ни фрагмент, ни хеш секрета",
          all(k not in d for k in ("token_len", "token_hash", "token_preview", "token_masked")))

    # DTO одинаков независимо от вызывающего
    check("A6. DTO детерминирован для одной и той же записи",
          dto.printer_public_dto(row) == dto.printer_public_dto(dict(row)))

# ── Реальный обработчик GET /api/printers ───────────────────────────────────
ns, conn = make_env()
out = ns["g_printers"]()
js_all = json.dumps(out, ensure_ascii=False, default=str)

for s, lbl in ((S_BAMBU, "Bambu access code"), (S_FF, "FlashForge serial:checkcode"),
               (S_KLIPPER, "Klipper API key")):
    check("SENTINEL. %-32s отсутствует в ответе GET /api/printers" % lbl, s not in js_all)
check("9. в списке нет ключа token ни на одном уровне", '"token"' not in js_all)
check("5b. будущий столбец БД не просочился в GET", "FUTURE_COLUMN_SENTINEL" not in js_all)
check("A7. credential_configured присутствует и корректен",
      isinstance(out, list) and out and out[0].get("credential_configured") is True
      and [p for p in out if p["id"] == "pr4"][0].get("credential_configured") is False)
check("A8. UI-поля сохранены (id/name/type/ip/port/gen/model/order_idx)",
      all(k in out[0] for k in ("id", "name", "type", "ip", "port", "gen", "model", "order_idx")))
check("A9. производные model_key/cover_url сохранены (нужны модулю склада)",
      "model_key" in out[0] and "cover_url" in out[0])

# ── Статические проверки production-кода ────────────────────────────────────
print("--- статические проверки ---")


def code_only(text):
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
        for row_, spans in cuts.items():
            s_ = rr[row_ - 1]
            for a, b in sorted(spans, reverse=True):
                s_ = s_[:a] + s_[b:]
            rr[row_ - 1] = s_
        return "".join(rr)
    except Exception:
        return txt


GP = code_only(grab("g_printers"))
check("28. публичный обработчик проходит через allowlist-сериализатор",
      "printer_public_dto" in GP)
# dict(r) сам по себе безвреден — он лишь материализует строку. Опасно ВОЗВРАЩАТЬ её наружу.
# Верный инвариант: наружу уходит результат allowlist-сериализатора, а не сырые строки.
check("29. сырые строки БД наружу не возвращаются (возврат идёт через DTO)",
      "return rows" not in GP and "printer_public_dto" in GP)

# save-response не отражает payload
SP = code_only(grab("s_printers"))
check("10. ответ /api/printers/save не возвращает записи принтеров",
      "return {\"status\": \"success\"}" in SP or "'status': 'success'" in SP)

# WebSocket-рассылка идёт из p_states, а не из строк БД
WS = code_only(grab("ws_loop"))
check("11. WebSocket-рассылка не читает таблицу printers",
      "FROM printers" not in WS and "conn_pr" not in WS)

# core.printers() для модулей — явный список колонок без token
CP = code_only(grab("printers"))
check("A10. core.printers() для модулей отдаёт явные колонки без token",
      "SELECT id, name, type, ip, port, order_idx FROM printers" in CP)

# Фронтенд больше не читает token из DTO
APP = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
check("14. фронтенд не читает p.token из ответа списка принтеров",
      "p.token" not in APP)
check("15. фронтенд использует признак credential_configured",
      "credential_configured" in APP)
check("6b. введённый token не попадает в общий массив printers.value",
      "_p.token =" not in APP)

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
