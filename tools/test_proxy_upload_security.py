# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.788 — защита Moonraker-совместимого приёма файла POST /server/files/upload.
#
#  ЧАСТЬ 1 (ХАРАКТЕРИЗАЦИЯ). Как маршрут вёл себя ДО правки, то есть в Alpha 2.787:
#  политика PUBLIC, никакой машинной аутентификации, multipart разбирался зависимостью
#  FastAPI File(...) ДО входа в тело обработчика — то есть до любой проверки источника.
#  Историческое состояние берётся из коммита 46a5c7f через git show и остаётся зелёным
#  после исправления: оно описывает 2.787, а не текущий код.
#
#  ЧАСТЬ 2+. Новая граница: loopback из транспорта И действующий ключ интеграции 2.781,
#  проверка ДО разбора формы, чтения потока, записи файла и изменений БД; сохранённая
#  защита имени файла (F1, Alpha 2.724) и прежний Moonraker-ответ.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * production server.py НЕ импортируется: реальные функции извлекаются разбором AST и
#     исполняются в изоляции — проверяется настоящий код, а не пересказ. Поэтому тест
#     можно запускать при РАБОТАЮЩЕЙ программе: named mutex одиночного экземпляра не
#     трогается и ложно-зелёного нуля проверок не бывает.
#   * рабочие БД, DATA_DIR и config.json не открываются: временная папка и sqlite в памяти.
#   * ни одного сокета, uvicorn, слайсера и обращения к принтерам.
#
#  Запуск:  python tools/test_proxy_upload_security.py   (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.append(os.path.join(REPO, "tools"))
import _history_baseline as HB   # noqa: E402

PARENT = "46a5c7f"   # HEAD до Alpha 2.788 (handoff 2.787)

FAILED = []
PASSED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)


def section(t):
    print("\n--- %s ---" % t)


# Метка-ловушка: живёт ТОЛЬКО в оснастке теста. При отказе она не должна попасть никуда —
# ни в ответ, ни в журнал, ни в БД, ни на диск, ни во временные файлы.
SENTINEL = "MOONRAKER_UPLOAD_SENTINEL_2_788"

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRC_AST = ast.parse(SRC)

from app import security_policy as _secpol          # noqa: E402  (чистые, только stdlib)
from app import slicer_callback_auth as _cb         # noqa: E402
from app import route_policy_registry as reg        # noqa: E402
from app import filesystem_access_policy as _fsp    # noqa: E402  (Alpha 2.789)


def fn_src(tree_or_src, name):
    tree = tree_or_src if isinstance(tree_or_src, ast.AST) else ast.parse(tree_or_src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return None


def sig_of(src):
    """Первая строка def. Сигнатуру берём именно так: слова вроде File(...) законно
    встречаются в пояснении к коду, и поиск по всему телу дал бы ложный результат."""
    for ln in (src or "").splitlines():
        if ln.lstrip().startswith(("def ", "async def ")):
            return ln.strip()
    return ""


#  Эталон — коммит закрытой истории. В открытой копии его нет: исторические проверки там
#  печатаются как SKIP с причиной (tools/_history_baseline.py), текущие выполняются как обычно.
HIST = HB.Baseline(REPO, PARENT, ["server.py", "app/route_policy_registry.py"], check)
hcheck = HIST.check


def git_show(rel):
    return HIST.show(rel)


PAR_SRC = git_show("server.py")
PAR_REG = git_show("app/route_policy_registry.py")
PAR_AST = ast.parse(PAR_SRC) if PAR_SRC else None


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.788: защита Moonraker-совместимого upload callback ===")
section("характеризация: как маршрут вёл себя в Alpha 2.787 (эталон %s)" % PARENT)

PAR_PU = fn_src(PAR_AST, "proxy_upload") if PAR_AST else ""
CUR_PU = fn_src(SRC_AST, "proxy_upload") or ""

hcheck("H0. эталон %s прочитан (server.py и реестр)" % PARENT,
       lambda: bool(PAR_SRC) and bool(PAR_REG) and bool(PAR_PU))
hcheck("H1. (1) политика маршрута была PUBLIC",
       lambda: PAR_REG is not None
       and "'/server/files/upload', 'proxy_upload', 'core', 'browser', 'PUBLIC'" in PAR_REG
       and "('DATABASE', 'FILESYSTEM'), 'NONE'" in PAR_REG)
hcheck("H2. (2) ключ интеграции не проверялся вовсе",
       lambda: bool(PAR_PU) and "_require_slicer_callback" not in PAR_PU and "X-Api-Key" not in PAR_PU)
hcheck("H3. (3) адрес отправителя не проверялся — loopback не требовался",
       lambda: bool(PAR_PU) and "is_loopback" not in PAR_PU and "client" not in PAR_PU)
hcheck("H4. (4) неверный ключ не имел значения: сравнения не было",
       lambda: bool(PAR_PU) and "compare_digest" not in PAR_PU and "verify_token" not in PAR_PU)
hcheck("H5. (5) токен из query не проверялся (обращений к query_params нет)",
       lambda: bool(PAR_PU) and "query_params" not in PAR_PU)
hcheck("H6. (6) заголовки прокси не проверялись",
       lambda: bool(PAR_PU) and not any(h in PAR_PU for h in ("X-Forwarded-For", "X-Real-IP", "Forwarded", "headers")))
hcheck("H7. (7) multipart разбирался ЗАВИСИМОСТЬЮ до тела обработчика",
       lambda: "File(...)" in sig_of(PAR_PU) and "UploadFile" in sig_of(PAR_PU))
hcheck("H8. (8) побочные эффекты (файл на диске и запись в БД) начинались без аутентификации",
       lambda: "open(file_path, 'wb')" in PAR_PU.replace('"', "'")
       and "parts_catalog" in PAR_PU)
hcheck("H9. (9) сессия браузера маршрут не защищала: гейт смотрит только пути под /api/",
       lambda: PAR_SRC is not None and "/server/files/upload" in PAR_SRC
       and not "/server/files/upload".startswith("/api/"))
hcheck("H10. (10) при AUTH OFF поведение было тем же: маршрут был доступен сети",
       lambda: PAR_REG is not None and "if not path.startswith('/api/'):" in PAR_REG.replace('"', "'"))
check("H11. (11) маршрут лежит вне обычного workflow /api/",
      not "/server/files/upload".startswith("/api/"))
check("H12. (12) production server не импортируется", "server" not in sys.modules)
check("H13. (13) рабочие БД/DATA_DIR/config не открываются (temp + sqlite в памяти)", True)
check("H14. (14) реальные файлы пользователя не создаются (только временная папка)", True)
check("H15. (15) сеть не используется", "uvicorn" not in sys.modules)


# ════════════════════════════════════════════════════════════════════════════
# ИЗОЛИРОВАННОЕ ИСПОЛНЕНИЕ РЕАЛЬНОГО КОДА server.py
# ════════════════════════════════════════════════════════════════════════════
section("изолированное исполнение реального обработчика")

TMP = tempfile.mkdtemp(prefix="fm_upload_788_")
UPLOAD_DIR = os.path.join(TMP, "slicer_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
OUTSIDE = os.path.join(TMP, "OUTSIDE_SENTINEL.txt")
with open(OUTSIDE, "wb") as _f:
    _f.write(b"ORIGINAL-DO-NOT-TOUCH")

DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.execute("CREATE TABLE parts_catalog (part_name TEXT PRIMARY KEY, required_qty INTEGER, project_name TEXT)")
DB.commit()

SETTINGS = {}
SPY = {}


def spy_reset():
    SPY.clear()
    SPY.update({"form": 0, "read": 0, "count_parts": 0, "db_exec": 0, "db_commit": 0,
                "log": [], "fs_before": _fs_snapshot()})


def _fs_snapshot():
    snap = {}
    for root, _d, files in os.walk(TMP):
        for fn in files:
            p = os.path.join(root, fn)
            try:
                with open(p, "rb") as f:
                    snap[p] = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                pass
    return snap


class _Log:
    def _r(self, *a, **k):
        try:
            SPY["log"].append(str(a[0]) % tuple(a[1:]) if len(a) > 1 else str(a[0]))
        except Exception:
            SPY["log"].append(" ".join(str(x) for x in a))
    info = warning = error = debug = _r


class _Lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _DB:
    """Обёртка над sqlite в памяти: считает обращения, чтобы доказать отсутствие записи при отказе."""
    def execute(self, *a, **k):
        SPY["db_exec"] += 1
        return DB.execute(*a, **k)

    def commit(self):
        SPY["db_commit"] += 1
        return DB.commit()


class _Resp:
    """Заменитель JSONResponse: тело сохраняем как есть, чтобы проверить контракт ответа."""
    def __init__(self, content=None, status_code=200):
        self.content = content
        self.status_code = status_code


def _count_plate_parts(path):
    SPY["count_parts"] += 1
    return {"status": "ignored", "parts": []}


NS = {
    "_security_policy": _secpol, "_slicer_cb": _cb, "_fs_policy": _fsp,
    "_get_setting": lambda k, d="": SETTINGS.get(k, d),
    "JSONResponse": _Resp, "log": _Log(), "os": os,
    "UPLOAD_DIR": UPLOAD_DIR, "lock_p": _Lock(), "conn_p": _DB(),
    "_count_plate_parts": _count_plate_parts, "_exc_brief": lambda: "err",
    "re": __import__("re"),
    "app": type("A", (), {"post": lambda *a, **k: (lambda f: f),
                          "get": lambda *a, **k: (lambda f: f)})(),
    "Request": object, "UploadFile": object, "File": lambda *a, **k: None,
}
def const_src(tree, name):
    """Модульная константа из server.py — берём НАСТОЯЩЕЕ определение, а не копию в тесте."""
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.unparse(n)
    return None


exec(compile(const_src(SRC_AST, "_UPLOAD_CTRL_RE"), "<server>", "exec"), NS)
for _name in ("_safe_upload_name", "_within_upload_dir", "_require_slicer_callback", "proxy_upload"):
    exec(compile(fn_src(SRC_AST, _name), "<server>", "exec"), NS)

safe_name_of = NS["_safe_upload_name"]
within_upload = NS["_within_upload_dir"]
upload = NS["proxy_upload"]

# Тот же реальный обработчик из эталонного коммита — для характеризации поведения 2.787.
# Исполняется только при наличии эталона (в открытой копии его нет).
par_upload = None
if HIST.present:
    PAR_NS = dict(NS)
    exec(compile(const_src(PAR_AST, "_UPLOAD_CTRL_RE"), "<server-parent>", "exec"), PAR_NS)
    for _name in ("_safe_upload_name", "_within_upload_dir", "proxy_upload"):
        exec(compile(fn_src(PAR_AST, _name), "<server-parent>", "exec"), PAR_NS)
    par_upload = PAR_NS["proxy_upload"]

check("X1. реальные функции обработчика исполнены изолированно",
      callable(upload) and callable(safe_name_of))
hcheck("X1h. прежний обработчик эталона %s исполнен изолированно" % PARENT,
       lambda: callable(par_upload))


class FakeUpload:
    def __init__(self, filename, data=b"; harmless\nG28\n"):
        self.filename = filename
        self._data = data

    async def read(self):
        SPY["read"] += 1
        return self._data


class FakeForm(dict):
    def values(self):
        return list(super().values())


class FakeRequest:
    """Минимальный Request: адрес из транспорта, заголовки и форма. form() считается шпионом —
    именно так доказывается, что при отказе тело запроса вообще не читается."""
    def __init__(self, client="127.0.0.1", headers=None, fields=None, form_raises=False):
        self.client = type("C", (), {"host": client})() if client is not None else None
        self.headers = dict(headers or {})
        self._fields = fields
        self._raises = form_raises
        self.query_params = {}

    async def form(self):
        SPY["form"] += 1
        if self._raises:
            raise ValueError("bad multipart")
        return FakeForm(self._fields if self._fields is not None else {})


TOKEN = _cb.generate_token()
SETTINGS["slicer_callback_token_hash"] = _cb.hash_token(TOKEN)
SETTINGS["slicer_callback_enabled"] = "1"
HDR = _cb.HEADER_NAME


def call(req):
    spy_reset()
    return asyncio.run(upload(req))


def good(fname="benchy.gcode", data=b"; harmless\nG28\n"):
    return {"file": FakeUpload(fname, data)}


def req_ok(fname="benchy.gcode", client="127.0.0.1", data=b"; harmless\nG28\n"):
    return FakeRequest(client=client, headers={HDR: TOKEN}, fields=good(fname, data))


# ── характеризация поведения 2.787 на РЕАЛЬНОМ прежнем коде ────────────────────
_par_resp = None
_par_file = os.path.join(UPLOAD_DIR, "charact_2787.gcode")
if par_upload is not None:
    spy_reset()
    _par_resp = asyncio.run(par_upload(FakeUpload("charact_2787.gcode", b"; old\n")))
hcheck("H16. (доказано исполнением) обработчик 2.787 принимал файл БЕЗ ключа и БЕЗ loopback: 200",
       lambda: getattr(_par_resp, "status_code", None) == 200 and os.path.isfile(_par_file))
if os.path.exists(_par_file):
    os.remove(_par_file)


# ════════════════════════════════════════════════════════════════════════════
section("граница: loopback и ключ (пункты 21-40)")

r = call(req_ok())
check("21. 127.0.0.1 + верный ключ -> разрешено", r.status_code == 200)
os.remove(os.path.join(UPLOAD_DIR, "benchy.gcode"))

r = call(FakeRequest(client="::1", headers={HDR: TOKEN}, fields=good("v6.gcode")))
check("22. ::1 + верный ключ -> разрешено", r.status_code == 200)
os.remove(os.path.join(UPLOAD_DIR, "v6.gcode"))

r = call(FakeRequest(client="::ffff:127.0.0.1", headers={HDR: TOKEN}, fields=good("m.gcode")))
check("23. IPv4-mapped loopback + верный ключ -> разрешено (контракт общей политики)",
      r.status_code == 200)
os.remove(os.path.join(UPLOAD_DIR, "m.gcode"))

DENY = [
    ("24. не-loopback + верный ключ -> отказ",
     FakeRequest(client="192.168.1.50", headers={HDR: TOKEN}, fields=good())),
    ("25. loopback без ключа -> отказ",
     FakeRequest(client="127.0.0.1", headers={}, fields=good())),
    ("26. loopback + пустой ключ -> отказ",
     FakeRequest(client="127.0.0.1", headers={HDR: ""}, fields=good())),
    ("27. loopback + неверный ключ -> отказ",
     FakeRequest(client="127.0.0.1", headers={HDR: _cb.generate_token()}, fields=good())),
    ("28. не-loopback + неверный ключ -> отказ",
     FakeRequest(client="10.0.0.7", headers={HDR: SENTINEL}, fields=good())),
    ("29. ключ в query -> отказ (query не читается)",
     FakeRequest(client="127.0.0.1", headers={}, fields=good())),
    ("30. ключ в cookie -> отказ",
     FakeRequest(client="127.0.0.1", headers={"Cookie": "%s=%s" % (HDR, TOKEN)}, fields=good())),
    ("31. ключ в поле multipart -> отказ",
     FakeRequest(client="127.0.0.1", headers={}, fields={"api_key": TOKEN, "file": FakeUpload("x.gcode")})),
    ("32. X-Forwarded-For: 127.0.0.1 не даёт обхода",
     FakeRequest(client="203.0.113.9", headers={HDR: TOKEN, "X-Forwarded-For": "127.0.0.1"}, fields=good())),
    ("33. X-Real-IP: 127.0.0.1 не даёт обхода",
     FakeRequest(client="203.0.113.9", headers={HDR: TOKEN, "X-Real-IP": "127.0.0.1"}, fields=good())),
    ("34. Forwarded: for=127.0.0.1 не даёт обхода",
     FakeRequest(client="203.0.113.9", headers={HDR: TOKEN, "Forwarded": "for=127.0.0.1"}, fields=good())),
    ("35. Host: localhost не даёт обхода",
     FakeRequest(client="203.0.113.9", headers={HDR: TOKEN, "Host": "localhost:8000"}, fields=good())),
    ("38. искажённый заголовок -> отказ",
     FakeRequest(client="127.0.0.1", headers={HDR: TOKEN + " "}, fields=good())),
    ("40. сессия администратора без ключа -> отказ",
     FakeRequest(client="127.0.0.1", headers={"Cookie": "fm_session=admin-session-id"}, fields=good())),
]
for _name, _req in DENY:
    _r = call(_req)
    check(_name, _r.status_code == 401 and SPY["form"] == 0)

_qp = FakeRequest(client="127.0.0.1", headers={}, fields=good())
_qp.query_params = {"api_key": TOKEN, "token": TOKEN}
check("29b. значение из query не принимается даже при наличии в query_params",
      call(_qp).status_code == 401)

check("36. сравнение ключа — constant-time helper 2.781, своей копии сравнения нет",
      "compare_digest" in open(os.path.join(REPO, "app", "slicer_callback_auth.py"),
                               encoding="utf-8").read()
      and "compare_digest" not in CUR_PU and "hash_token" not in CUR_PU)

SETTINGS["slicer_callback_token_hash"] = ""
check("37. секрет недоступен -> fail closed (доступ не открывается)",
      call(req_ok()).status_code == 401)
SETTINGS["slicer_callback_token_hash"] = _cb.hash_token(TOKEN)
SETTINGS["slicer_callback_enabled"] = "0"
check("37b. интеграция отключена -> fail closed", call(req_ok()).status_code == 401)
SETTINGS["slicer_callback_enabled"] = "1"


class _DupHeaders(dict):
    """Два разных значения одного заголовка: неоднозначность на границе доверия."""
    def items(self):
        return [(HDR, TOKEN), (HDR, _cb.generate_token())]


check("39. дублирующийся конфликтующий заголовок -> отказ",
      call(FakeRequest(client="127.0.0.1", headers=_DupHeaders(), fields=good())).status_code == 401)


# ════════════════════════════════════════════════════════════════════════════
section("порядок побочных эффектов при отказе (пункты 41-53)")

_deny_req = FakeRequest(client="192.168.1.77", headers={HDR: SENTINEL},
                        fields={"file": FakeUpload(SENTINEL + ".gcode", SENTINEL.encode())})
_before = _fs_snapshot()
_r = call(_deny_req)
_after = _fs_snapshot()

check("41-43. при отказе форма/тело/multipart не читаются", SPY["form"] == 0)
check("44. поток файла не читается", SPY["read"] == 0)
check("45-46. временный файл не создаётся и файловая система не меняется", _before == _after)
check("47. БД не открывается для побочных эффектов загрузки",
      SPY["db_exec"] == 0 and SPY["db_commit"] == 0)
check("48. состояние не меняется (анализатор плиты не вызывался)", SPY["count_parts"] == 0)
check("49-50. очередь/recovery/принтер не вызываются: их имён нет в обработчике",
      not any(x in CUR_PU for x in ("_pjob", "reserve", "recover", "_send_file_to_printer",
                                    "printQueue", "urllib", "requests")))
check("51. отказ не отражает payload: имя файла и содержимое в ответ не попадают",
      SENTINEL not in str(_r.content))
check("52. ключ не журналируется", not any(TOKEN in ln or SENTINEL in ln for ln in SPY["log"]))
check("53a. метка отсутствует в ответе", SENTINEL not in str(_r.content))
check("53b. метка отсутствует в журнале", not any(SENTINEL in ln for ln in SPY["log"]))
_dbdump = "".join(str(row) for row in DB.execute("SELECT * FROM parts_catalog").fetchall())
check("53c. метка отсутствует в БД", SENTINEL not in _dbdump)
check("53d. метка отсутствует на диске и во временных файлах",
      not any(SENTINEL in os.path.basename(p) for p in _after))
check("53e. метка отсутствует в git-tracked исходниках приложения",
      SENTINEL not in SRC
      and SENTINEL not in open(os.path.join(REPO, "app", "route_policy_registry.py"),
                               encoding="utf-8").read()
      and SENTINEL not in open(os.path.join(REPO, "web", "app.js"),
                               encoding="utf-8", errors="surrogateescape").read())
check("53f. отказ отдаёт единый безопасный код без внутренней причины",
      _r.status_code == 401 and str(_r.content.get("error")) == _cb.REASON_DENIED
      and not any(k in str(_r.content) for k in ("X-Api-Key", "loopback", "127.0.0.1",
                                                 "hash", "DATA_DIR", "Traceback")))


# ════════════════════════════════════════════════════════════════════════════
section("успешный путь не изменён (пункты 54-65)")

_r = call(req_ok("normal.gcode"))
check("54. локальная загрузка с верным ключом проходит прежним обработчиком",
      _r.status_code == 200 and os.path.isfile(os.path.join(UPLOAD_DIR, "normal.gcode")))
check("59. успешный JSON совпадает с прежним контрактом Moonraker",
      _r.content == {"status": "ok", "message": "Received and parsed"})
check("62. тело читается ТОЛЬКО после разрешения",
      SPY["form"] == 1 and SPY["read"] == 1)
check("63. ключ не попадает в ответ", TOKEN not in str(_r.content))

# 55-57: семантика имени сохранена (F1, Alpha 2.724).
ATTACKS = [
    ("..\\..\\farm_printers.db", "basename", "farm_printers.db"),
    ("../../server.py",          "basename", "server.py"),
    ("C:\\Windows\\evil.exe",    "basename", "evil.exe"),
    ("/etc/passwd",              "basename", "passwd"),
    ("\\\\srv\\share\\e.gcode",  "basename", "e.gcode"),
    ("C:evil.gcode",             "reject",   None),
    ("evil.gcode:stream",        "reject",   None),
    ("bad\x00name.gcode",        "reject",   None),
    ("ctrl\x1fname.gcode",       "reject",   None),
    ("",                         "reject",   None),
    (None,                       "reject",   None),
    (".",                        "reject",   None),
    ("..",                       "reject",   None),
]
_ok_attacks = True
for raw, policy, base in ATTACKS:
    _before = _fs_snapshot()
    _r = call(req_ok(raw))
    if policy == "reject":
        good_case = (_r.status_code == 400 and _fs_snapshot() == _before)
    else:
        target = os.path.join(UPLOAD_DIR, base)
        good_case = (_r.status_code == 200 and os.path.isfile(target)
                     and within_upload(target))
        if os.path.isfile(target):
            os.remove(target)
    if not good_case:
        _ok_attacks = False
        print("     (провал на %r)" % (raw,))
check("55-56. семантика имени и защита пути сохранены: %d кейсов traversal/ADS/абсолютных путей"
      % len(ATTACKS), _ok_attacks)
check("56b. внешний файл вне UPLOAD_DIR дословно не изменён",
      open(OUTSIDE, "rb").read() == b"ORIGINAL-DO-NOT-TOUCH")
check("55b. составное расширение сохраняется",
      safe_name_of("MyModel.gcode.3mf") == "MyModel.gcode.3mf")
check("56c. defense-in-depth: цель вне UPLOAD_DIR не считается допустимой",
      within_upload(os.path.join(UPLOAD_DIR, "x.gcode"))
      and not within_upload(os.path.join(TMP, "farm_printers.db")))

# 57: поведение при повторной загрузке того же имени.
_p = os.path.join(UPLOAD_DIR, "dup.gcode")
call(req_ok("dup.gcode", data=b"first"))
_first = open(_p, "rb").read()
_r = call(req_ok("dup.gcode", data=b"second"))
check("57. поведение при дубликате сохранено: перезапись прежним обработчиком, 200",
      _r.status_code == 200 and _first == b"first" and open(_p, "rb").read() == b"second")
os.remove(_p)

# 58: неудачная загрузка не оставляет мусора.
_before = _fs_snapshot()
_r = call(FakeRequest(client="127.0.0.1", headers={HDR: TOKEN}, form_raises=True))
check("58. битый multipart после разрешения: 400 и ни одного временного файла",
      _r.status_code == 400 and _fs_snapshot() == _before)
_before = _fs_snapshot()
_r = call(FakeRequest(client="127.0.0.1", headers={HDR: TOKEN}, fields={"print": "true"}))
check("60. форма без файла: контролируемая ошибка обработчика, мусор не остаётся",
      _r.status_code == 400 and _fs_snapshot() == _before)
check("61. downstream-поведение сохранено: анализатор плиты вызывается только после записи",
      "_count_plate_parts" in CUR_PU and "parts_catalog" in CUR_PU)
check("64. ключ не попадает в сохранённые метаданные",
      not any(TOKEN in str(row) for row in DB.execute("SELECT * FROM parts_catalog").fetchall()))
check("65. ротация ключа использует единственный источник истины 2.781",
      "slicer_callback_token_hash" in SRC and SRC.count("_slicer_cb.generate_token()") == 1
      and "generate_token" not in CUR_PU)


# ════════════════════════════════════════════════════════════════════════════
section("порядок в исходнике и единственность секрета")

_body_after_def = CUR_PU.split(":", 1)[1] if ":" in CUR_PU else CUR_PU
_i_guard = _body_after_def.find("_require_slicer_callback")
_i_form = _body_after_def.find("request.form()")
_i_read = _body_after_def.find(".read()")
check("O1. граница стоит ДО разбора формы в тексте обработчика",
      _i_guard >= 0 and _i_form > _i_guard)
check("O2. граница стоит ДО чтения потока файла",
      _i_read > _i_guard)
check("O3. граница вызывается ровно один раз",
      CUR_PU.count("_require_slicer_callback(") == 1)
check("O4. второго секрета не заведено: источник истины один",
      "moonraker_token" not in SRC and "upload_token" not in SRC)
hcheck("O4h. число упоминаний slicer_callback_token_hash то же, что в эталоне %s" % PARENT,
       lambda: SRC.count("slicer_callback_token_hash") == PAR_SRC.count("slicer_callback_token_hash"))
check("O5. отдельного модуля-адаптера не потребовалось",
      not os.path.exists(os.path.join(REPO, "app", "moonraker_upload_auth.py")))
check("O6. заголовок один и тот же, алиасов не добавлено",
      _cb.HEADER_NAME == "X-Api-Key"
      and open(os.path.join(REPO, "app", "slicer_callback_auth.py"),
               encoding="utf-8").read().count("HEADER_NAME =") == 1)
check("O7. файл читается один раз (двойного чтения не появилось)",
      CUR_PU.count(".read()") == 1)


# ════════════════════════════════════════════════════════════════════════════
section("реестр маршрутов (пункты 7-20)")

_t = reg.core_http_policy("POST", "/server/files/upload")
_all = [p for p in reg.CORE_POLICIES if p.path == "/server/files/upload"]
check("7. маршрут существует ровно один раз", len(_all) == 1)
check("8. метод POST", _t.method == "POST")
check("9. обработчик совпадает", _t.handler == "proxy_upload")
check("10. политика CALLBACK_SECRET", _t.enforced_access.value == "CALLBACK_SECRET")
check("11. маршрут больше не PUBLIC", _t.enforced_access.value != "PUBLIC")
_core = [p for p in reg.CORE_POLICIES if p.kind is reg.RouteKind.HTTP]
#  2.903: +3 PUBLIC — страница UI 3.0 и её файлы (обычная статика браузера).
#  16.10.2026 (R-149): файлы модулей /modules/* — только после входа, PUBLIC 27 -> 26, SESSION_ONLY 3 -> 4.
check("12. PUBLIC: 26 (было 24 до второго интерфейса, 27 до 16.10.2026)",
      sum(1 for p in _core if p.enforced_access.value == "PUBLIC") == 26)
check("13. CALLBACK_SECRET стало на один больше: 3",
      sum(1 for p in _core if p.enforced_access.value == "CALLBACK_SECRET") == 3)
_c = reg.registry_counts()
check("14. итоги описи ожидаемые: 233/188/45/2 (2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup; 2.831 +2 printer-sort-mode; 2.833 +2 klipper-prestart); 2.903: +3 UI 3.0 (вторая страница интерфейса); 2.920: +5 очередь ожидания (список, добавить, убрать, запуск, флаг принтера); 2.927: +3 пометки принтера и настройки фермы",
      _c["total"] == 260 and _c["core"] == 209 and _c["modules"] == 51 and _c["websocket"] == 2)   # 12.09.2026 -1 маршрут пометок принтера; 196->204 / 241->249; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers
check("15. /api/slicer-hook не изменён",
      reg.core_http_policy("POST", "/api/slicer-hook").enforced_access.value == "CALLBACK_SECRET")
check("16. /api/files/local не изменён",
      reg.core_http_policy("POST", "/api/files/local").enforced_access.value == "CALLBACK_SECRET")
check("17. остальные маршруты ядра не изменили политику (2.813: GET /api/diagnostics -> SYSTEM_ADMIN; "
      "2.823/2.825: printer-files; 2.827: +4 config-backup SYSTEM_ADMIN; 2.831/2.833: +4 CAPABILITY)",
      sum(1 for p in _core if p.enforced_access.value == "CAPABILITY") == 145   #; 16.09.2026 +2 маршрута подтверждения «Стол очищен»; 2.920: +5 очередь ожидания; 2.927: +3 пометки и настройки фермы; 12.09.2026 -1 маршрут пометок принтера
      and sum(1 for p in _core if p.enforced_access.value == "SYSTEM_ADMIN") == 22
      and sum(1 for p in _core if p.enforced_access.value == "HANDLER_ADMIN") == 6
      and sum(1 for p in _core if p.enforced_access.value == "SESSION_ONLY") == 4)   # 16.10.2026 (R-149): +/modules/*
check("18. права модулей не изменены",
      len(reg.MODULE_POLICIES) == 51
      and sum(1 for p in reg.MODULE_POLICIES if p.required_capability == "view") == 21
      and sum(1 for p in reg.MODULE_POLICIES if p.required_capability == "admin") == 11)
# Alpha 2.879 добавила ВТОРОЙ сокет — камеру. Смысл проверки прежний: у всех сокетов
# та же граница доступа, что и была.
check("19. политика WebSocket не изменена",
      set(p.enforced_access.value for p in reg.CORE_POLICIES
          if p.kind is reg.RouteKind.WEBSOCKET) == {"CAPABILITY"})
hcheck("20. политика LAN не изменена: решение о bind принимает прежний модуль",
       lambda: PAR_AST is not None and fn_src(PAR_AST, "_lan_effective_decision") == fn_src(SRC_AST, "_lan_effective_decision"))
check("20b. историческое право маршрута (current_permission) не переписано",
      _t.current_permission == "project")


# ════════════════════════════════════════════════════════════════════════════
section("режимы авторизации (пункты 75-80)")

check("75. AUTH OFF не отменяет проверку callback: решение не зависит от режима входа",
      not any(x in CUR_PU for x in ("_SECURITY_ENABLED", "_session_check", "_req_role")))
check("76-77. сессия браузера ключ не заменяет: обработчик не смотрит ни сессию, ни роль",
      "session" not in CUR_PU.lower() and "role" not in CUR_PU.lower())
check("78. верный ключ + loopback работают без сессии браузера",
      call(req_ok("nosession.gcode")).status_code == 200)
os.remove(os.path.join(UPLOAD_DIR, "nosession.gcode"))
check("79. клиент из локальной сети отклоняется даже с верным ключом",
      call(FakeRequest(client="192.168.0.10", headers={HDR: TOKEN},
                       fields=good())).status_code == 401)
check("80. при AUTH OFF маршрут описан как callback+loopback, а не как открытый",
      _t.auth_off_scope.value == "CALLBACK_LOOPBACK")


# ════════════════════════════════════════════════════════════════════════════
shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 76)
sys.exit(HIST.summary(PASSED[0], FAILED))
