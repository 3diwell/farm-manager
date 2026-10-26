# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Административная граница выбора ИСПОЛНЯЕМОГО ФАЙЛА слайсера (Alpha 2.780).
#
# БЕЗ сервера/сети/принтеров/рабочей БД/DATA_DIR: обработчики извлекаются из server.py
# ДОСЛОВНО через AST и исполняются со стабами. НАСТОЯЩИЙ слайсер не запускается никогда:
# вместо subprocess.Popen и системного окна выбора файла стоят шпионы, фиксирующие вызов.
# «Исполняемый» файл в тестах — пустышка в tempfile, её никто не запускает.
#
# ЗАКРЫВАЕМАЯ ЦЕПОЧКА. Путь к слайсеру сохраняется в app_settings и позже подставляется
# как argv[0] в subprocess.Popen. До 2.780 сохранить его мог кто угодно с правом
# 'project' (оператор цеха), а при выключенной защите — любой клиент из локальной сети.
# Отдельно: /api/projects2/files/{id}/slice принимал путь к слайсеру ПРЯМО В ТЕЛЕ запроса
# и запускал его немедленно, вообще ничего не сохраняя.
#
# ГРАНИЦА ЗАДАЧИ. /api/slicer-hook — ВНЕШНИЙ callback слайсера (в _GATE_EXCLUDE, без
# сессии приложения). Он пишет только манифест плиты и к executable path отношения не
# имеет: админ-guard на него вешать НЕЛЬЗЯ, иначе сломается приём от слайсера.
#
# Запуск: python tools/test_slicer_executable_boundary.py   (0 = все проверки пройдены)
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
    """Тело функции без докстроки."""
    fn = FN.get(fn_name)
    if not fn:
        return []
    return [s for s in fn.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                    and isinstance(s.value.value, str))]


def guard_is_first(fn_name):
    """Стоит ли вызов _require_system_admin ПЕРВЫМ исполняемым оператором тела."""
    body = body_stmts(fn_name)
    if not body:
        return False
    return isinstance(body[0], ast.Assign) and "_require_system_admin" in (ast.unparse(body[0].value) or "")


def calls_anywhere(fn_name, needle):
    fn = FN.get(fn_name)
    return bool(fn) and needle in (ast.unparse(fn) or "")


def route_of(fn_name):
    """(метод, путь) из декоратора @app.<method>("...")."""
    fn = FN.get(fn_name)
    if not fn:
        return (None, None)
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args:
            a0 = d.args[0]
            if isinstance(a0, ast.Constant):
                return (d.func.attr, a0.value)
    return (None, None)


# ── Стабы: ничего настоящего не выполняется ────────────────────────────────
class Req(object):
    """Минимальная замена Request: адрес клиента, cookie сессии, JSON-тело."""

    class _C(object):
        def __init__(self, host):
            self.host = host

    def __init__(self, client="127.0.0.1", cookie=None, no_client=False, body=None):
        self.client = None if no_client else Req._C(client)
        self.cookies = {"fm_session": cookie} if cookie else {}
        self.headers = {}
        self._body = body if body is not None else {}

    async def json(self):
        return self._body


class Spy(object):
    """Фиксирует вызовы, ничего не делая по-настоящему."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return self.result

    @property
    def called(self):
        return bool(self.calls)


def deny_for(role_or_client):
    """Заглушка _require_system_admin: 'admin'/loopback -> None, иначе отказ."""
    def _g(req):
        if role_or_client == "allow":
            return None
        return {"_json": {"error": "forbidden"}, "_code": 403}
    return _g


def run_handler(fn_name, ns, *args, **kw):
    """Исполнить обработчик (sync или async) в изолированном namespace."""
    exec(grab(fn_name), ns)
    fn = ns[fn_name]
    res = fn(*args, **kw)
    if asyncio.iscoroutine(res):
        res = asyncio.run(res)
    return res


def base_ns(guard="allow", settings=None):
    """Namespace со шпионами вместо записи настроек, picker и subprocess."""
    store = dict(settings or {})
    set_spy = Spy()
    pick_spy = Spy(result=[])
    popen_spy = Spy()

    def _set_setting(key, value):
        set_spy((key, value))
        store[key] = value

    def _get_setting(key, default=""):
        return store.get(key, default)

    ns = {
        "os": os, "sys": sys,
        "_require_system_admin": deny_for(guard),
        "_set_setting": _set_setting, "_get_setting": _get_setting,
        "_native_pick_files": pick_spy,
        "subprocess": type("S", (), {"Popen": staticmethod(popen_spy)})(),
        "log": type("L", (), {"debug": staticmethod(lambda *a, **k: None),
                              "info": staticmethod(lambda *a, **k: None),
                              "warning": staticmethod(lambda *a, **k: None),
                              "error": staticmethod(lambda *a, **k: None)})(),
        "_exc_brief": (lambda: "x"),
    }
    ns["_store"] = store
    ns["_set_spy"] = set_spy
    ns["_pick_spy"] = pick_spy
    ns["_popen_spy"] = popen_spy
    return ns


TMP = tempfile.mkdtemp(prefix="fm_slicer_test_")
FAKE_EXE = os.path.join(TMP, "FakeSlicer.exe")
with open(FAKE_EXE, "w", encoding="utf-8") as _f:
    _f.write("")          # пустышка: НИКОГДА не запускается, нужна только для os.path.isfile
FAKE_BAT = os.path.join(TMP, "evil.bat")
with open(FAKE_BAT, "w", encoding="utf-8") as _f:
    _f.write("")

print("=== Alpha 2.780: граница выбора исполняемого файла слайсера ===")

# ═══ ЧАСТЬ 1. Карта маршрутов: кто вообще меняет executable path ═══
print("--- карта маршрутов ---")

check("M1. /api/slicer/choose — POST, обработчик slicer_choose",
      route_of("slicer_choose") == ("post", "/api/slicer/choose"))
check("M2. /api/slicer/pick — POST, обработчик slicer_pick",
      route_of("slicer_pick") == ("post", "/api/slicer/pick"))
check("M3. /api/slicer/list — GET, только чтение (executable path не меняет)",
      route_of("slicer_list_api") == ("get", "/api/slicer/list")
      and not calls_anywhere("slicer_list_api", "_set_setting"))
check("M4. /api/projects2/files/{file_id}/slice — POST, запускает subprocess",
      route_of("project2_file_slice") == ("post", "/api/projects2/files/{file_id}/slice")
      and calls_anywhere("project2_file_slice", "subprocess.Popen"))
check("M5. /api/staging/{filename}/slice — POST, запускает subprocess",
      route_of("staging_slice") == ("post", "/api/staging/{filename}/slice")
      and calls_anywhere("staging_slice", "subprocess.Popen"))

# Единственные писатели slicer_path во всём server.py — два маршрута, и никаких других.
_writers = set()
for _name, _fn in FN.items():
    _u = ast.unparse(_fn) or ""
    if "_set_setting('slicer_path'" in _u or '_set_setting("slicer_path"' in _u:
        _writers.add(_name)
check("M6. slicer_path пишут РОВНО два обработчика (нет обходных путей записи): %s"
      % ", ".join(sorted(_writers)),
      _writers == {"slicer_choose", "slicer_pick"})

# Генерического settings-эндпоинта с произвольным ключом быть не должно.
#  2.947: ключ может стоять модульной ПОСТОЯННОЙ (STAGING_SYNC_KEY = "staging_project_sync").
#  Смысл проверки — «нет записи произвольного ключа», а постоянная с текстовым значением
#  ничем не отличается от литерала: снаружи её подменить нельзя. Собираем такие постоянные
#  и разворачиваем их в значение; всё остальное по-прежнему считается переменной.
_const_keys = {}
for _m in ast.walk(TREE):
    if isinstance(_m, ast.Assign) and isinstance(_m.value, ast.Constant) and isinstance(_m.value.value, str):
        for _t in _m.targets:
            if isinstance(_t, ast.Name) and _t.id.isupper():
                _const_keys[_t.id] = _m.value.value

_setting_keys = set()
for _m in ast.walk(TREE):
    if isinstance(_m, ast.Call) and isinstance(_m.func, ast.Name) and _m.func.id == "_set_setting":
        if _m.args and isinstance(_m.args[0], ast.Constant):
            _setting_keys.add(_m.args[0].value)
        elif _m.args and isinstance(_m.args[0], ast.Name) and _m.args[0].id in _const_keys:
            _setting_keys.add(_const_keys[_m.args[0].id])
        else:
            _setting_keys.add("<ПЕРЕМЕННАЯ>")
check("M7. _set_setting вызывается только с литеральными ключами (нет записи произвольного ключа): %s"
      % ", ".join(sorted(map(str, _setting_keys))),
      "<ПЕРЕМЕННАЯ>" not in _setting_keys)

# ═══ ЧАСТЬ 2. ХАРАКТЕРИЗАЦИЯ: чего НЕ хватает до исправления ═══
# Эти проверки КРАСНЫЕ до product-правки — в этом и смысл этапа.
print("--- требуемая административная граница ---")

check("G1. slicer_choose: _require_system_admin — ПЕРВЫЙ исполняемый оператор",
      guard_is_first("slicer_choose"))
check("G2. slicer_pick: _require_system_admin — ПЕРВЫЙ исполняемый оператор",
      guard_is_first("slicer_pick"))
check("G3. slicer_pick принимает Request (иначе guard физически некуда подать)",
      any(a.arg in ("req", "request") for a in (FN["slicer_pick"].args.args or [])))

# Порядок: guard обязан стоять ДО чтения тела, ДО файлового диалога и ДО записи настройки.
def guard_before(fn_name, needle):
    fn = FN.get(fn_name)
    if not fn:
        return False
    src = ast.unparse(fn) or ""
    if "_require_system_admin" not in src or needle not in src:
        return False
    return src.index("_require_system_admin") < src.index(needle)


check("G4. slicer_choose: guard ДО чтения тела запроса",
      guard_before("slicer_choose", ".json()") or guard_before("slicer_choose", "_json_body"))
check("G5. slicer_choose: guard ДО записи настройки",
      guard_before("slicer_choose", "_set_setting"))
check("G6. slicer_pick: guard ДО системного окна выбора файла",
      guard_before("slicer_pick", "_native_pick_files"))
check("G7. slicer_pick: guard ДО записи настройки",
      guard_before("slicer_pick", "_set_setting"))

# ═══ ЧАСТЬ 3. Поведение при отказе: ни одного побочного эффекта ═══
print("--- при отказе не должно быть побочных эффектов ---")

ns = base_ns(guard="deny")
res = run_handler("slicer_choose", ns, Req(client="192.168.1.50", body={"path": FAKE_EXE}))
check("D1. slicer_choose, отказ -> настройка НЕ записана",
      not ns["_set_spy"].called)
check("D2. slicer_choose, отказ -> вернулся отказ, а не сохранённое значение",
      isinstance(res, dict) and res.get("_code") in (401, 403))

ns2 = base_ns(guard="deny")
try:
    res2 = run_handler("slicer_pick", ns2, Req(client="192.168.1.50"))
    _pick_ok = True
except TypeError:
    res2, _pick_ok = None, False      # до правки slicer_pick не принимает Request
check("D3. slicer_pick, отказ -> системное окно выбора файла НЕ открыто",
      _pick_ok and not ns2["_pick_spy"].called)
check("D4. slicer_pick, отказ -> настройка НЕ записана",
      _pick_ok and not ns2["_set_spy"].called)

# ═══ ЧАСТЬ 4. Сохранение произвольного пути без администратора ═══
print("--- характеризация уязвимости (до 2.780 это ПРОХОДИТ) ---")

ns3 = base_ns(guard="deny")
run_handler("slicer_choose", ns3, Req(client="192.168.1.50", body={"path": FAKE_EXE}))
check("V1. удалённый (не-loopback) клиент НЕ может сохранить executable path",
      ns3["_store"].get("slicer_path") != FAKE_EXE)

# ═══ ЧАСТЬ 5. Валидация пути (после успешного guard) ═══
print("--- валидация сохраняемого пути ---")

BAD = [
    ("http://evil.example/x.exe", "URL"),
    ("file:///C:/x.exe", "file://"),
    ("C:\\x.exe\x00.txt", "null byte"),
    ("\\\\.\\PhysicalDrive0", "device path"),
    ("\\\\?\\GLOBALROOT\\Device\\X", "GLOBALROOT"),
    ("\\\\.\\pipe\\x", "pipe path"),
    (TMP, "директория вместо файла"),
    (FAKE_BAT, ".bat вместо .exe"),
    ("", "пустая строка"),
    ("   ", "только пробелы"),
]
_HAS_VALIDATOR = "_validate_slicer_executable" in SRC or "validate_slicer_executable" in SRC
check("P0. в коде есть серверная валидация пути слайсера", _HAS_VALIDATOR)

if _HAS_VALIDATOR:
    _mod = None
    try:
        from app import slicer_policy as _mod          # noqa: F401
    except Exception:
        _mod = None
    if _mod is not None and hasattr(_mod, "validate_slicer_executable"):
        _val = _mod.validate_slicer_executable
    else:
        _vns = {"os": os, "sys": sys}
        exec(grab("_validate_slicer_executable"), _vns)
        _val = _vns["_validate_slicer_executable"]

    for bad, label in BAD:
        ok = _val(bad)[0]
        check("P. отклонено: %-26s" % label, not ok)
    ok, norm, _reason = _val(FAKE_EXE)
    check("P1. настоящий .exe принят и путь абсолютный",
          ok and os.path.isabs(norm))
    _e = _val("C:\\Secret\\Folder\\thing.txt")
    check("P2. текст ошибки не раскрывает полный абсолютный путь",
          not _e[0] and "C:\\Secret\\Folder" not in str(_e[2]))

# ═══ ЧАСТЬ 6. Override слайсера в /api/projects2/files/{id}/slice ═══
# Тело {"slicer": путь} запускало ПРОИЗВОЛЬНЫЙ бинарник немедленно. UI пользуется этим
# полем легально (выбор слайсера в шапке), поэтому путь ограничивается известным набором,
# а не закрывается админ-границей: обычный сценарий оператора должен уцелеть.
print("--- override слайсера: только известные слайсеры ---")

_p2 = ast.unparse(FN["project2_file_slice"]) if "project2_file_slice" in FN else ""
check("O1. override проверяется по списку известных слайсеров, а не только os.path.isfile",
      "_slicer_allowed" in _p2 or "_slicer_candidates" in _p2)
check("O2. на маршрут открытия модели НЕ навешен админ-guard (сценарий оператора цел)",
      not guard_is_first("project2_file_slice"))

# ═══ ЧАСТЬ 7. Внешний callback слайсера — граница задачи ═══
print("--- внешний callback слайсера не трогаем ---")

check("E1. /api/slicer-hook остаётся в _GATE_EXCLUDE (у слайсера нет сессии приложения)",
      '"/api/slicer-hook"' in SRC and "_GATE_EXCLUDE" in SRC)
check("E2. /api/slicer-hook НЕ получает админ-guard (иначе приём манифеста сломается)",
      not guard_is_first("s_hook"))
check("E3. /api/slicer-hook не меняет executable path",
      not calls_anywhere("s_hook", "_set_setting"))

# ═══ ЧАСТЬ 8. Контракт запуска subprocess ═══
print("--- контракт запуска ---")

check("S1. shell=True не используется в server.py нигде", "shell=True" not in SRC)


def popen_contract(fn_name):
    """Структурно: Popen вызывается argv-СПИСКОМ, argv[0] — отдельное имя переменной
    (не склейка строк, не f-string), shell=True не передаётся. Проверка по AST, поэтому
    переименование переменной её не ломает — важна форма вызова, а не текст."""
    fn = FN.get(fn_name)
    if not fn:
        return False
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "Popen"):
            continue
        if any(k.arg == "shell" and getattr(k.value, "value", False) is True for k in n.keywords):
            return False
        if not (n.args and isinstance(n.args[0], ast.List) and n.args[0].elts):
            return False
        if not isinstance(n.args[0].elts[0], ast.Name):   # argv[0] — простое имя, без конкатенации
            return False
        return True
    return False


for _fn in ("project2_file_slice", "staging_slice"):
    check("S2. %s: запуск argv-списком, слайсер — отдельный argv[0], без shell" % _fn,
          popen_contract(_fn))

check("S3. настоящий слайсер за весь тест не запускался", True)   # Popen всюду был шпионом

# ═══ ЧАСТЬ 9. USE-TIME BOUNDARY: сохранённый config НЕ доверенный ═══
# То, что путь уже лежит в app_settings, не делает его безопасным: он мог быть записан
# версией до 2.780 (проверялся лишь os.path.isfile), правкой БД вручную, повреждённым
# config — либо указывать на файл, который с тех пор удалили или подменили.
print("--- legacy slicer_path из config не доверенный ---")

from app import slicer_policy as _sp                                  # noqa: E402
_VAL = _sp.validate_slicer_executable

UNC_EXE = "\\\\server\\share\\Slicer.exe"
DEVICE_P = "\\\\.\\PhysicalDrive0"
GONE_EXE = os.path.join(TMP, "Deleted.exe")
NEIGHBOUR = os.path.join(TMP, "Neighbour.exe")
with open(NEIGHBOUR, "w", encoding="utf-8") as _f:
    _f.write("")
SUBDIR = os.path.join(TMP, "sub")
os.makedirs(SUBDIR, exist_ok=True)
NESTED = os.path.join(SUBDIR, "Nested.exe")
with open(NESTED, "w", encoding="utf-8") as _f:
    _f.write("")


def env_with(saved="", candidates=()):
    """Namespace для _slicer_allowlist / _slicer_allowed / _slicer_for_launch."""
    ns = base_ns(guard="allow", settings={"slicer_path": saved} if saved else {})
    ns["_slicer_policy"] = _sp
    ns["_slicer_candidates"] = (lambda: list(candidates))
    exec(grab("_validate_slicer_executable"), ns)
    exec(grab("_slicer_allowlist"), ns)
    exec(grab("_slicer_allowed"), ns)
    exec(grab("_slicer_for_launch"), ns)
    return ns


# 1-4. Негодный legacy config: ни в allowlist, ни к запуску, и config НЕ переписывается.
for bad_saved, label in ((FAKE_BAT, "legacy .bat"),
                         (UNC_EXE, "legacy UNC .exe"),
                         (DEVICE_P, "legacy device path"),
                         (GONE_EXE, "legacy несуществующий .exe")):
    e = env_with(saved=bad_saved, candidates=[])
    allow = e["_slicer_allowlist"]()
    path, why = e["_slicer_for_launch"]()
    check("U. %-26s -> НЕ в allowlist" % label, not allow)
    check("U. %-26s -> к запуску НЕ отдан" % label, path == "")
    check("U. %-26s -> причина saved_slicer_invalid" % label, why == "saved_slicer_invalid")
    check("U. %-26s -> config НЕ переписан автоматически" % label,
          e["_store"].get("slicer_path") == bad_saved and not e["_set_spy"].called)

# 5. Был валиден при сохранении, затем удалён до запуска -> Popen не вызывается.
TRANSIENT = os.path.join(TMP, "Transient.exe")
with open(TRANSIENT, "w", encoding="utf-8") as _f:
    _f.write("")
e5 = env_with(saved=TRANSIENT, candidates=[])
check("U5a. пока файл на месте — путь к запуску отдаётся", e5["_slicer_for_launch"]()[0] != "")
os.remove(TRANSIENT)
check("U5b. файл удалён после сохранения -> к запуску НЕ отдан",
      e5["_slicer_for_launch"]()[0] == "")
check("U5c. удалённый файл не проходит валидацию вплотную к запуску", not _VAL(TRANSIENT)[0])

# 6. Был валиден, затем заменён каталогом -> Popen не вызывается.
SWAPPED = os.path.join(TMP, "Swapped.exe")
with open(SWAPPED, "w", encoding="utf-8") as _f:
    _f.write("")
e6 = env_with(saved=SWAPPED, candidates=[])
check("U6a. пока это файл — путь отдаётся", e6["_slicer_for_launch"]()[0] != "")
os.remove(SWAPPED)
os.makedirs(SWAPPED, exist_ok=True)          # теперь по тому же пути КАТАЛОГ
check("U6b. подменён каталогом -> к запуску НЕ отдан", e6["_slicer_for_launch"]()[0] == "")
check("U6c. каталог не проходит валидацию (not_a_file)", _VAL(SWAPPED)[2] == "not_a_file")

# 7-8. Авто-кандидаты тоже не доверенные.
e7 = env_with(saved="", candidates=[FAKE_BAT, UNC_EXE, DEVICE_P, FAKE_EXE])
check("U7. кандидат с запрещённым расширением/UNC/device исключён, валидный остался",
      [os.path.normcase(x) for x in e7["_slicer_allowlist"]()] == [os.path.normcase(FAKE_EXE)])
check("U8. похожее имя рядом не даёт разрешения произвольному соседнему .exe",
      e7["_slicer_allowed"](NEIGHBOUR) == "")

# 9. Override с ".." — разрешается только если КАНОНИЧЕСКИ совпал с элементом allowlist.
e9 = env_with(saved="", candidates=[FAKE_EXE])
DOTDOT_OK = os.path.join(SUBDIR, "..", os.path.basename(FAKE_EXE))
DOTDOT_BAD = os.path.join(SUBDIR, "..", os.path.basename(NEIGHBOUR))
check("U9a. '..' , канонически ведущий к разрешённому файлу -> разрешён",
      _sp.same_executable(e9["_slicer_allowed"](DOTDOT_OK), FAKE_EXE))
check("U9b. '..' , ведущий к ДРУГОМУ файлу -> запрещён", e9["_slicer_allowed"](DOTDOT_BAD) == "")

# 10. Регистр Windows: тот же канонический файл — совпадение.
check("U10. различие регистра -> тот же файл считается совпадением",
      _sp.same_executable(e9["_slicer_allowed"](FAKE_EXE.upper()), FAKE_EXE)
      if os.name == "nt" else True)

# 11. Другой .exe в том же каталоге запрещён (членство поштучное, не по каталогу).
check("U11. другой .exe в том же каталоге -> запрещён", e9["_slicer_allowed"](NEIGHBOUR) == "")
check("U11b. .exe во вложенном каталоге -> запрещён", e9["_slicer_allowed"](NESTED) == "")

# 12. Сохранённый ВАЛИДНЫЙ .exe доступен операторскому override.
e12 = env_with(saved=FAKE_EXE, candidates=[])
check("U12. сохранённый валидный .exe разрешён override-ом",
      _sp.same_executable(e12["_slicer_allowed"](FAKE_EXE), FAKE_EXE))

# 13-14. Результаты pick/choose валидируются ДО сохранения.
check("U13. slicer_pick: валидация ДО записи настройки",
      guard_before("slicer_pick", "_validate_slicer_executable")
      and (ast.unparse(FN["slicer_pick"]) or "").index("_validate_slicer_executable")
          < (ast.unparse(FN["slicer_pick"]) or "").index("_set_setting('slicer_path'"))
check("U14. slicer_choose: валидация ДО записи настройки",
      (ast.unparse(FN["slicer_choose"]) or "").index("_validate_slicer_executable")
      < (ast.unparse(FN["slicer_choose"]) or "").rindex("_set_setting('slicer_path'"))

_pick_src = ast.unparse(FN["slicer_pick"]) or ""
_choose_src = ast.unparse(FN["slicer_choose"]) or ""
check("U13b. slicer_pick сохраняет КАНОНИЧЕСКИЙ путь от валидатора, а не выбор picker'а",
      "_set_setting('slicer_path', norm)" in _pick_src)
check("U14b. slicer_choose сохраняет КАНОНИЧЕСКИЙ путь, а не строку из запроса",
      "_set_setting('slicer_path', norm)" in _choose_src)

# 15-16. Вплотную к Popen — канонический путь от валидатора, не сырая строка.
for _fn in ("project2_file_slice", "staging_slice"):
    _u = ast.unparse(FN[_fn]) or ""
    check("U15. %s: перед Popen выполняется повторная валидация" % _fn,
          "_validate_slicer_executable" in _u
          and _u.index("_validate_slicer_executable") < _u.index("subprocess.Popen"))
    check("U16. %s: в Popen идёт канонический exe, а не сырая строка" % _fn,
          "subprocess.Popen([exe," in _u)

# 17. Ошибка legacy-пути не переписывает config автоматически.
_all_src = "\n".join(ast.unparse(FN[n]) or "" for n in
                     ("_slicer_for_launch", "_slicer_allowlist", "_slicer_allowed",
                      "slicer_list_api", "project2_file_slice", "staging_slice"))
check("U17. ни один путь чтения/запуска не стирает и не переписывает slicer_path",
      "_set_setting" not in _all_src)

# 18. Настоящий процесс не создавался ни разу.
check("U18. subprocess.Popen за весь тест не вызывался по-настоящему",
      not ns["_popen_spy"].called and not ns3["_popen_spy"].called)

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
