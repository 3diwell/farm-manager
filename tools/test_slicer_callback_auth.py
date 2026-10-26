# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Граница доверия нативных callback-маршрутов слайсера (Alpha 2.781).
#
# БЕЗ сервера/сети/принтеров/рабочей БД/DATA_DIR: обработчики извлекаются из server.py
# ДОСЛОВНО через AST и исполняются со стабами. Настоящий слайсер не запускается, реальный
# subprocess не создаётся, файлы пишутся только во временный каталог.
#
# ЧТО ЗАКРЫВАЕТСЯ. Маршруты в _GATE_EXCLUDE обходят session-гейт: у нативного слайсера нет
# сессии приложения. До 2.781 они принимали данные вообще без доказательства источника —
# любой локальный или сетевой клиент мог загрузить файл в Quick Tasks и подменить манифест
# плиты.
#
# ОТПРАВИТЕЛЬ И ЗАГОЛОВОК. Реальный отправитель — встроенный OctoPrint-клиент слайсера
# (OrcaSlicer/PrusaSlicer/Bambu Studio, тип хоста OctoPrint). Он передаёт ключ заголовком
# X-Api-Key — это протокол OctoPrint, произвольный заголовок такой клиент отправить не может.
# Поэтому контракт 2.781 — ровно один заголовок X-Api-Key; секрет не попадает в URL.
#
# ГРАНИЦА ЗАДАЧИ. /api/version, /api/server, /api/connection — статический OctoPrint-
# handshake: константы, без побочных эффектов и без раскрытия данных (класс D). Отдельный
# секрет им не требуется. Браузерные маршруты (upload/import/файлы проектов) НЕ в
# _GATE_EXCLUDE — их закрывает обычный session-гейт, и callback-политика их не касается.
#
# Запуск: python tools/test_slicer_callback_auth.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import asyncio
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC)

SENTINEL = "SLICER_CALLBACK_SECRET_SENTINEL_2_781"

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


FN = {}
for _n in ast.walk(TREE):
    if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FN.setdefault(_n.name, _n)


def grab(fn_name):
    fn = FN.get(fn_name)
    if not fn:
        raise AssertionError("функция не найдена: " + fn_name)
    return ast.get_source_segment(SRC, fn)


def body_stmts(fn_name):
    fn = FN.get(fn_name)
    if not fn:
        return []
    return [s for s in fn.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str))]


def guard_is_first(fn_name, needle):
    body = body_stmts(fn_name)
    if not body:
        return False
    return needle in (ast.unparse(body[0]) or "")


def route_of(fn_name):
    fn = FN.get(fn_name)
    if not fn:
        return (None, None)
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args:
            if isinstance(d.args[0], ast.Constant):
                return (d.func.attr, d.args[0].value)
    return (None, None)


def src_of(fn_name):
    return ast.unparse(FN[fn_name]) if fn_name in FN else ""


class Spy(object):
    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return self.result

    @property
    def called(self):
        return bool(self.calls)


class UploadStub(object):
    """Замена UploadFile: фиксирует сам факт чтения — при отказе его быть не должно."""

    def __init__(self, filename="plate.gcode", data=b"G28\n"):
        self.filename = filename
        self._data = data
        self.read_calls = 0

    async def read(self):
        self.read_calls += 1
        return self._data


class FormStub(dict):
    def __init__(self, upload=None, **kw):
        super().__init__(**kw)
        self._upload = upload
        self.read_calls = 0

    def values(self):
        self.read_calls += 1
        vals = list(super().values())
        if self._upload is not None:
            vals.append(self._upload)
        return vals


class Req(object):
    """Минимальная замена Request: адрес клиента, заголовки, cookie, form/json."""

    class _C(object):
        def __init__(self, host):
            self.host = host

    def __init__(self, client="127.0.0.1", headers=None, cookie=None,
                 no_client=False, form=None, json_body=None, query=""):
        self.client = None if no_client else Req._C(client)
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.cookies = {"fm_session": cookie} if cookie else {}
        self._form = form
        self._json = json_body if json_body is not None else {}
        self.form_calls = 0
        self.json_calls = 0

        class _U(object):
            path = "/api/files/local"
        self.url = _U()
        self.url.query = query
        self.base_url = "http://127.0.0.1:8000/"

    async def form(self):
        self.form_calls += 1
        return self._form if self._form is not None else FormStub()

    async def json(self):
        self.json_calls += 1
        return self._json


TMP = tempfile.mkdtemp(prefix="fm_cb_test_")

print("=== Alpha 2.781: граница доверия нативных callback слайсера ===")

# ═══ ЧАСТЬ 1. Карта маршрутов и классификация ═══
print("--- карта маршрутов ---")

check("M1. /api/files/local — POST, приём файла от слайсера (класс A)",
      route_of("octo_files_local") == ("post", "/api/files/local"))
check("M2. /api/slicer-hook — POST, запись манифеста плиты (класс A)",
      route_of("s_hook") == ("post", "/api/slicer-hook"))
for _fn, _p in (("octo_version", "/api/version"), ("octo_server", "/api/server"),
                ("octo_connection", "/api/connection")):
    check("M3. %s — GET, статический handshake без побочных эффектов (класс D)" % _p,
          route_of(_fn) == ("get", _p)
          and "conn_p" not in src_of(_fn) and "open(" not in src_of(_fn))

_gate = [l for l in SRC.splitlines() if l.startswith("_GATE_EXCLUDE")]
check("M4. _GATE_EXCLUDE содержит ровно 5 известных маршрутов (новый без guard уронит тест)",
      len(_gate) == 1
      and set(__import__("re").findall(r'"(/api/[^"]+)"', _gate[0]))
      == {"/api/slicer-hook", "/api/version", "/api/server", "/api/connection", "/api/files/local"})

# Браузерные маршруты не должны попасть под callback-политику.
for _fn in ("octo_files_local", "s_hook"):
    check("M5. %s остаётся в _GATE_EXCLUDE (у слайсера нет сессии приложения)" % _fn,
          route_of(_fn)[1] in _gate[0])
_browser = ("api_projects2_files_upload", "fs_stage", "staging_upload")
for _fn in _browser:
    if _fn in FN:
        check("M6. браузерный %s НЕ получает callback-guard" % _fn,
              "_require_slicer_callback" not in src_of(_fn))

# ═══ ЧАСТЬ 2. Чистый модуль политики ═══
print("--- чистый модуль политики ---")

try:
    from app import slicer_callback_auth as cba
    _has_mod = True
except Exception as _e:
    cba, _has_mod = None, False
    print("  (app/slicer_callback_auth.py недоступен: %s)" % _e)
check("A0. app/slicer_callback_auth.py импортируется", _has_mod)

if _has_mod:
    _POL = open(os.path.join(REPO, "app", "slicer_callback_auth.py"), encoding="utf-8").read()
    check("A1. модуль не тянет server.py / FastAPI / sqlite / сеть",
          all(x not in _POL for x in ("import server", "FastAPI", "sqlite3", "import requests",
                                      "urllib.request", "socket")))
    check("A2. модуль не логирует секрет", "log." not in _POL and "print(" not in _POL)

    # 1-2. Генерация и энтропия.
    t1, t2 = cba.generate_token(), cba.generate_token()
    check("S1. два generate дают разные token", t1 != t2)
    check("S2. энтропия не ниже 256 бит (>=43 символа token_urlsafe(32))",
          len(t1) >= 43 and cba.TOKEN_BYTES >= 32)
    check("S2b. token не выводится из имени машины/пользователя/времени",
          all(x not in _POL for x in ("COMPUTERNAME", "getuser", "time.time", "uuid.getnode")))

    # 3. Хранится hash, не raw.
    h1 = cba.hash_token(t1)
    check("S3. hash не равен token и имеет длину sha256-hex", h1 != t1 and len(h1) == 64)
    check("S3b. по hash нельзя восстановить token (односторонность: hash != token)",
          t1 not in h1)

    # 4-9. Проверка значения заголовка.
    check("S4. верный token проходит", cba.verify_token(t1, h1) is True)
    check("S5. неверный token отклоняется", cba.verify_token(t2, h1) is False)
    check("S6. пустой/пробелы отклоняются",
          cba.verify_token("", h1) is False and cba.verify_token("   ", h1) is False)
    check("S6b. None отклоняется", cba.verify_token(None, h1) is False)
    check("S8. слишком длинное значение отклоняется до дорогой обработки",
          cba.verify_token("x" * (cba.MAX_TOKEN_LEN + 1), h1) is False)
    check("S9. сравнение constant-time (hmac.compare_digest)", "compare_digest" in _POL)
    check("S9b. отсутствует наивное сравнение строк token ==",
          "token ==" not in _POL and "== token" not in _POL)

    # 7. Несколько значений заголовка.
    ok_multi, _r = cba.check_header({"x-api-key": t1 + ", " + t2}, h1)
    check("S7. несколько значений в заголовке отклоняются", ok_multi is False)
    ok_dup, _r = cba.check_header({"x-api-key": t1 + "," + t1}, h1)
    check("S7b. повтор того же значения тоже отклоняется", ok_dup is False)

    # 6. Единый reason: не различать отсутствие/неверный/отозванный.
    _r_absent = cba.check_header({}, h1)[1]
    _r_wrong = cba.check_header({"x-api-key": t2}, h1)[1]
    _r_revoked = cba.check_header({"x-api-key": t1}, "")[1]
    check("S10. reason одинаков для отсутствующего, неверного и отозванного",
          _r_absent == _r_wrong == _r_revoked == "callback_not_authorized")

    # Ровно один заголовок, token не из query/cookie/body.
    check("S11. принимается ровно заголовок X-Api-Key", cba.HEADER_NAME.lower() == "x-api-key")
    check("S12. модуль не читает query/cookie/body/Origin/User-Agent",
          all(x not in _POL for x in ("query", "cookie", "Origin", "User-Agent", "body")))

    # Sentinel не утекает из модуля.
    _s_ok, _s_reason = cba.check_header({"x-api-key": SENTINEL}, cba.hash_token(SENTINEL))
    check("SENT1. sentinel проходит как валидный token (механика верна)", _s_ok is True)
    check("SENT2. sentinel не появляется в reason", SENTINEL not in str(_s_reason))
    check("SENT3. sentinel не хранится в модуле в открытом виде", SENTINEL not in _POL)

# ═══ ЧАСТЬ 3. Guard на callback-маршрутах ═══
print("--- guard на callback-маршрутах ---")

GUARD = "_require_slicer_callback"
check("G0. в server.py есть единый guard %s" % GUARD, GUARD in SRC)
for _fn in ("octo_files_local", "s_hook"):
    check("G1. %s: guard — ПЕРВЫЙ исполняемый оператор" % _fn, guard_is_first(_fn, GUARD))
    _u = src_of(_fn)

    def _before(text, a, b):
        """Стоит ли a раньше b. Отсутствие любого из них — не пройдено (а не исключение:
        до правки guard в коде нет, и тест обязан показать FAIL, а не упасть)."""
        return a in text and b in text and text.index(a) < text.index(b)

    for _side, _label in ((".form()", "чтения multipart"), (".read()", "чтения файла"),
                          ("conn_p.execute", "записи в БД")):
        if _side in _u:
            check("G2. %s: guard ДО %s" % (_fn, _label), _before(_u, GUARD, _side))

check("G3. handshake-маршруты guard НЕ получают (класс D, ничего не пишут)",
      not guard_is_first("octo_version", GUARD)
      and not guard_is_first("octo_server", GUARD)
      and not guard_is_first("octo_connection", GUARD))

_g_src = src_of(GUARD) if GUARD in FN else ""
check("G4. guard не принимает token из query", "query" not in _g_src)
check("G5. guard не принимает token из cookie", "cookie" not in _g_src)
check("G6. guard не доверяет заголовкам прокси и Host",
      all(x not in _g_src for x in ("x-forwarded-for", "X-Forwarded-For", "x-real-ip", "forwarded")))
check("G7. guard требует loopback через чистую политику",
      "is_loopback_client" in _g_src)
check("G8. guard не читает тело запроса", ".json()" not in _g_src and ".form()" not in _g_src)

# ── Исполнение обработчиков со стабами ─────────────────────────────────────
def make_ns(token_hash="", enabled=True, allow=None):
    """Namespace для исполнения guard и обработчиков. allow=None -> настоящий guard."""
    db_spy, ingest_spy, bg_spy = Spy(), Spy(result=True), Spy()

    ns = {
        "os": os, "sys": sys, "json": __import__("json"),
        "_get_setting": (lambda k, d="": {"slicer_callback_token_hash": token_hash,
                                          "slicer_callback_enabled": "1" if enabled else "0"}.get(k, d)),
        "_set_setting": Spy(),
        "_security_policy": __import__("app.security_policy", fromlist=["x"]),
        "_stage_ingest": ingest_spy,
        "conn_p": type("C", (), {"execute": staticmethod(db_spy),
                                 "commit": staticmethod(lambda: None)})(),
        "lock_p": __import__("threading").Lock(),
        "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None),
                              "info": staticmethod(lambda *a, **k: None),
                              "warning": staticmethod(lambda *a, **k: None),
                              "error": staticmethod(lambda *a, **k: None)})(),
        "_exc_brief": (lambda: "x"),
        "_OCTO_EXTS": (".gcode", ".3mf"),
        "JSONResponse": (lambda d, status_code=200: {"_json": d, "_code": status_code}),
    }
    if _has_mod:
        ns["_slicer_cb"] = cba          # так модуль назван в server.py
    ns["_db_spy"], ns["_ingest_spy"], ns["_bg_spy"] = db_spy, ingest_spy, bg_spy
    if allow is None and GUARD in FN:
        exec(grab(GUARD), ns)
    else:
        ns[GUARD] = (lambda req: None if allow else {"_json": {"error": "callback_not_authorized"},
                                                     "_code": 401})
    return ns


def run(fn_name, ns, *a, **kw):
    exec(grab(fn_name), ns)
    res = ns[fn_name](*a, **kw)
    if asyncio.iscoroutine(res):
        res = asyncio.run(res)
    return res


if _has_mod and GUARD in FN:
    TOK = cba.generate_token()
    HASH = cba.hash_token(TOK)

    def hdr(t):
        return {"X-Api-Key": t}

    # 13-14. Нет / неверный token -> deny ДО тела.
    for _label, _h in (("нет token", {}), ("неверный token", hdr(cba.generate_token()))):
        ns = make_ns(HASH)
        up = UploadStub()
        r = run("octo_files_local", ns, Req(headers=_h, form=FormStub(upload=up)))
        check("C. %-16s -> отказ" % _label, isinstance(r, dict) and r.get("_code") in (401, 403))
        check("C. %-16s -> multipart НЕ читался" % _label, not ns["_ingest_spy"].called)
        check("C. %-16s -> файл НЕ читался" % _label, up.read_calls == 0)

    ns = make_ns(HASH)
    r = run("s_hook", ns, Req(headers={}, json_body={"filename": "x", "parts": {}}))
    check("C. slicer-hook без token -> отказ", isinstance(r, dict) and r.get("_code") in (401, 403))
    check("C. slicer-hook без token -> в БД НЕ писали", not ns["_db_spy"].called)

    # 15. Верный token + loopback -> обработчик выполняется.
    ns = make_ns(HASH)
    up = UploadStub()
    r = run("octo_files_local", ns, Req(client="127.0.0.1", headers=hdr(TOK),
                                        form=FormStub(upload=up)))
    check("C15. верный token + loopback -> обработчик отработал", ns["_ingest_spy"].called)

    # 16-17. LAN и подделка прокси-заголовков.
    ns = make_ns(HASH)
    up = UploadStub()
    r = run("octo_files_local", ns, Req(client="192.168.1.50", headers=hdr(TOK),
                                        form=FormStub(upload=up)))
    check("C16. верный token с LAN-адреса -> отказ", r.get("_code") in (401, 403))
    check("C16b. LAN -> файл не читался", up.read_calls == 0)

    ns = make_ns(HASH)
    h = hdr(TOK); h["X-Forwarded-For"] = "127.0.0.1"
    r = run("octo_files_local", ns, Req(client="192.168.1.50", headers=h,
                                        form=FormStub(upload=UploadStub())))
    check("C17. подделка X-Forwarded-For при LAN-транспорте -> отказ", r.get("_code") in (401, 403))

    ns = make_ns(HASH)
    h = hdr(TOK); h["Host"] = "localhost:8000"
    r = run("octo_files_local", ns, Req(client="192.168.1.50", headers=h,
                                        form=FormStub(upload=UploadStub())))
    check("C17b. Host: localhost при LAN-транспорте -> отказ", r.get("_code") in (401, 403))

    ns = make_ns(HASH)
    r = run("octo_files_local", ns, Req(no_client=True, headers=hdr(TOK),
                                        form=FormStub(upload=UploadStub())))
    check("C17c. отсутствующий request.client -> отказ", r.get("_code") in (401, 403))

    # 18. Admin-сессия без callback token не проходит.
    ns = make_ns(HASH)
    r = run("octo_files_local", ns, Req(cookie="admin-session", headers={},
                                        form=FormStub(upload=UploadStub())))
    check("C18. admin-сессия БЕЗ callback token -> отказ", r.get("_code") in (401, 403))

    # 25-27. Token из query/cookie/body не принимается.
    ns = make_ns(HASH)
    r = run("octo_files_local", ns, Req(headers={}, query="apikey=" + TOK,
                                        form=FormStub(upload=UploadStub())))
    check("C25. token в query не принимается", r.get("_code") in (401, 403))

    ns = make_ns(HASH)
    r = run("octo_files_local", ns, Req(headers={}, cookie=TOK,
                                        form=FormStub(upload=UploadStub())))
    check("C26. token в cookie не принимается", r.get("_code") in (401, 403))

    ns = make_ns(HASH)
    r = run("s_hook", ns, Req(headers={}, json_body={"filename": "x", "parts": {},
                                                     "api_key": TOK}))
    check("C27. token в теле JSON не принимается (контракт — заголовок)",
          r.get("_code") in (401, 403))

    # 20. AUTH ON/OFF не меняет требование callback-token.
    check("C20. guard не смотрит на _SECURITY_ENABLED (требование не зависит от режима)",
          "_SECURITY_ENABLED" not in _g_src)

    # 11. Revoke/отсутствие hash отклоняет прежний token.
    ns = make_ns("")
    r = run("octo_files_local", ns, Req(headers=hdr(TOK), form=FormStub(upload=UploadStub())))
    check("C11. после revoke (hash пуст) прежний token отклоняется", r.get("_code") in (401, 403))

    ns = make_ns(HASH, enabled=False)
    r = run("octo_files_local", ns, Req(headers=hdr(TOK), form=FormStub(upload=UploadStub())))
    check("C33. при выключенной интеграции верный token отклоняется", r.get("_code") in (401, 403))

    # 10. Rotation отзывает старый token.
    NEW = cba.generate_token()
    ns = make_ns(cba.hash_token(NEW))
    r = run("octo_files_local", ns, Req(headers=hdr(TOK), form=FormStub(upload=UploadStub())))
    check("C10. после rotation старый token отклоняется", r.get("_code") in (401, 403))
    ns = make_ns(cba.hash_token(NEW))
    r = run("octo_files_local", ns, Req(headers=hdr(NEW), form=FormStub(upload=UploadStub())))
    check("C10b. новый token после rotation работает", ns["_ingest_spy"].called)

    # 8. Заведомо длинное значение.
    ns = make_ns(HASH)
    r = run("octo_files_local", ns, Req(headers=hdr("x" * 100000),
                                        form=FormStub(upload=UploadStub())))
    check("C8. огромное значение заголовка -> отказ без чтения тела",
          r.get("_code") in (401, 403) and not ns["_ingest_spy"].called)

    # SENTINEL: секрет не отражается в ответе.
    ns = make_ns(HASH)
    r = run("octo_files_local", ns, Req(headers=hdr(SENTINEL),
                                        form=FormStub(upload=UploadStub())))
    check("SENT4. отклонённый token не отражается в теле ответа", SENTINEL not in repr(r))
    check("SENT5. sentinel отсутствует в исходниках server.py", SENTINEL not in SRC)

# ═══ ЧАСТЬ 4. Management endpoints ═══
print("--- управление ключом интеграции ---")

MGMT = [n for n in FN if n.startswith("slicer_callback_")]
check("N0. есть административные endpoints управления ключом: %s" % (", ".join(sorted(MGMT)) or "—"),
      len(MGMT) >= 3)
for _fn in MGMT:
    check("N1. %s: _require_system_admin — ПЕРВЫЙ оператор" % _fn,
          guard_is_first(_fn, "_require_system_admin"))
    check("N2. %s: НЕ в _GATE_EXCLUDE" % _fn, route_of(_fn)[1] not in _gate[0])
    if "status" in _fn:
        _u = src_of(_fn)
        check("N3. status не возвращает raw token и не возвращает hash",
              "token_hash" not in _u.split("return")[-1] and "raw" not in _u)
for _fn in MGMT:
    if "status" not in _fn:
        check("N4. %s: отказ происходит ДО записи config" % _fn,
              "_require_system_admin" in src_of(_fn)
              and ("_set_setting" not in src_of(_fn)
                   or src_of(_fn).index("_require_system_admin") < src_of(_fn).index("_set_setting")))

check("N5. raw token нигде не сохраняется в настройках",
      "_set_setting('slicer_callback_token'," not in SRC
      and '_set_setting("slicer_callback_token",' not in SRC)
check("N6. в аудит/лог token не пишется",
      "slicer_callback_token" not in "\n".join(
          l for l in SRC.splitlines() if "log." in l or "_audit(" in l))

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
