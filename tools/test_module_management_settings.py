# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Управление модулями в настройках — core Alpha 2.808.
=================================================================================================
ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ.

У владельца в «Настройки → Система» раздела «Модули» не было вовсе: были только Диагностика,
Сеть и доступ, Хранение данных и Интеграция со слайсером. Установить подготовленный .zip было
физически нечем. Причин оказалось две, независимых.

1. Карточка «Модули» гейтилась редакцией программы: `v-if="can('operate') && edHas('modules')"`.
   Редакция хранится в localStorage конкретного браузерного профиля, по умолчанию равна
   'advanced', а в списке `_editionRemoved` у 'advanced' значилось 'modules'. То есть на любом
   свежем профиле — и в браузере, и в собственном окне, и в клиенте — раздел исчезал. Управление
   установкой модулей не может быть платной возможностью редакции и тем более не может зависеть
   от localStorage клиента.

2. Даже с видимой карточкой Inventory и Cost остались бы невидимыми: `/api/modules` отдавал
   ТОЛЬКО успешно загруженные и отключённые пользователем модули. Модуль, не прошедший проверку
   прав (например, установлена версия 1.7.23, а карта прав объявляет 1.7.24), не попадал никуда
   и выглядел как «не установлен», хотя лежал на диске со своими данными.

26.09.2026: модуль другой версии (или новее программы) больше НЕ отвергается — расхождение с
картой прав идёт в заметки, неизвестный карте маршрут получает «только администратор». Раздел F3
закрепляет новое правило; подробный набор — tools/test_module_version_tolerance.py.

ЧТО ПРОВЕРЯЕТСЯ. Серверные функции берутся ДОСЛОВНО из server.py (exec нужных блоков) и
работают на ВРЕМЕННЫХ папках; фронтенд-контракт проверяется по фактическому тексту
web/index.html и web/app.js. Тест падает, если реализация уедет.

ПОЛНОСТЬЮ OFFLINE: временная папка, синтетические .zip, поддельные права, без рабочей БД и
DATA_DIR, без реальных модулей и их архивов, без сети и принтеров, без GUI.

Запуск: PYTHONIOENCODING=utf-8 python tools/test_module_management_settings.py   (0 = пройдено)
"""
import atexit
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "MODULE_MANAGEMENT_SETTINGS_SENTINEL_2_808"

# ── Ловушки-шпионы: доказываем, что тест ничего не делает наружу ────────────────────────────────
import socket as _socket_mod
import subprocess as _subprocess_mod

_VIOLATIONS = []


class _NoSocket(object):
    def __init__(self, *a, **k):
        _VIOLATIONS.append("socket")
        raise RuntimeError("сеть в offline-тесте запрещена")


_socket_mod.socket = _NoSocket
_socket_mod.create_connection = lambda *a, **k: _NoSocket()


def _no_subprocess(*a, **k):
    _VIOLATIONS.append("subprocess")
    raise RuntimeError("подпроцессы в offline-тесте запрещены")


_subprocess_mod.Popen = _no_subprocess
_subprocess_mod.run = _no_subprocess

_TMP = tempfile.TemporaryDirectory(prefix="fm_modmgmt_2808_")
TMP_ROOT = os.path.realpath(_TMP.name)

_SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_HTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
_CSS = open(os.path.join(REPO, "web", "app.css"), encoding="utf-8", errors="surrogateescape").read()
_APP = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()

fail = 0
_checked = 0
_verdict = [False]


def check(name, cond):
    global fail, _checked
    _checked += 1
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


@atexit.register
def _guard_exit():
    """Преждевременный выход (в т.ч. чужой sys.exit(0)) не должен выглядеть зелёным прогоном."""
    if not _verdict[0]:
        print("FAIL — тест завершился БЕЗ финального вердикта (преждевременный выход)")
        os._exit(1)


def _fn_src(name):
    i = _SRV.index("\ndef %s(" % name) + 1
    m = re.search(r"\n(?=def |class |@app\.|if not _IS_POOL_WORKER)", _SRV[i:])
    return _SRV[i:i + (m.start() if m else len(_SRV))]


def _route_src(decorator, fname):
    """Тело обработчика маршрута ДОСЛОВНО. Обработчик может быть как def, так и async def."""
    i = _SRV.index(decorator)
    m0 = re.search(r"\n(?:async )?def %s\(" % re.escape(fname), _SRV[i:])
    j = i + m0.start() + 1
    m = re.search(r"\n(?=(?:async )?def |class |@app\.|if not _IS_POOL_WORKER)", _SRV[j:])
    return _SRV[j:j + (m.start() if m else len(_SRV))]


def _modules_card():
    """Разметка карточки «Модули» целиком — от её открывающего div до следующей группы настроек."""
    i = _HTML.index('data-tour="set-modules"')
    # Alpha 2.834: у карточек настроек появились id (мини-навигация) и доп. классы — ищем шире.
    _opens = [m.start() for m in re.finditer(r'<div [^>]*class="fm-set-group', _HTML[:i])]
    start = _opens[-1]
    _after = [m.start() for m in re.finditer(r'<div [^>]*class="fm-set-group', _HTML[start + 10:])]
    nxt = (start + 10 + _after[0]) if _after else -1
    return _HTML[start:nxt if nxt > 0 else start + 8000]


# ── Песочница ядра ─────────────────────────────────────────────────────────────────────────────
MODULES_DIR = os.path.join(TMP_ROOT, "modules")
os.makedirs(MODULES_DIR, exist_ok=True)


class _Log(object):
    lines = []

    @classmethod
    def _rec(cls, m, *a):
        try:
            cls.lines.append(str(m) % a if a else str(m))
        except Exception:
            cls.lines.append(str(m))

    info = classmethod(lambda c, m, *a, **k: c._rec(m, *a))
    debug = classmethod(lambda c, m, *a, **k: c._rec(m, *a))
    warning = classmethod(lambda c, m, *a, **k: c._rec(m, *a))
    error = classmethod(lambda c, m, *a, **k: c._rec(m, *a))


class _FakePolicy(object):
    def __init__(self, mid, ver):
        self.module_id = mid
        self.module_version = ver


class _FakeRegistry(object):
    """Карта прав ядра: объявляет ОЖИДАЕМЫЕ версии модулей."""
    ALL_POLICIES = (_FakePolicy("inventory", "1.7.29"), _FakePolicy("cost", "0.1.3"),
                    _FakePolicy("quality", "0.2.3"), _FakePolicy(None, None))


#  26.09.2026: список модулей и установка сообщают о более новом известном выпуске через
#  app/module_catalog.py, а проверка маршрутов модуля берёт право из описи и строгую политику
#  для неизвестного маршрута — через app/module_runtime_policy.py. Это настоящие модули
#  проекта (чистые, без БД, сети и файлов) — подставляются как есть, без заглушек.
from app import module_catalog as _MC
from app import module_runtime_policy as _MRP
from app import route_access_control as _RA
from app import route_policy_registry as _RR
from app.licensing import package as _LPKG        # 26.09.2026: проверка подписанного пакета (настоящая)
from app.licensing import service as _LSVC        # 26.09.2026: служба лицензий без ключей — модули «без подписи»

NS = {
    "os": os, "re": re, "json": json, "_jsonmod": json, "_zipfile": zipfile,
    "_iomod": io, "_shutil": shutil, "log": _Log, "_exc_brief": lambda: "test-exc",
    "_route_registry": _FakeRegistry, "MODULES_USER_DIR": MODULES_DIR,
    "_loaded_modules": {}, "_disabled_modules": {}, "_failed_modules": {},
    "_modules_restart_needed": False, "_module_catalog": _MC,
    "_lic_pkg": _LPKG, "_LICENSES": _LSVC.LicenseService(os.path.join(TMP_ROOT, "lic"), trusted={}),
    "secrets": __import__("secrets"), "time": __import__("time"), "MODULES_STAGING_DIR": os.path.join(TMP_ROOT, "modules_staging"),
    "MODULES_PREVIOUS_DIR": os.path.join(TMP_ROOT, "modules_previous"),
}
NS["__builtins__"] = __builtins__

# Константы состояний — ДОСЛОВНО из server.py.
for _line in re.findall(r"^MODULE_STATE_[A-Z_]+ = \".+\"$", _SRV, re.M):
    exec(_line, NS)
exec(re.search(r"^MODULE_STATES = \(.*?\)$", _SRV, re.M | re.S).group(0), NS)

#  26.09.2026: установка читает манифест прежней версии (_read_manifest), чтобы сказать
#  «вместо 1.7.30 поставлена 1.7.20», — помощник берётся из server.py так же дословно.
#  Там же проверка id модуля (_module_id_ok: только [A-Za-z0-9_-]).
NS.setdefault("re", re)
for _f in ("_module_id_ok", "_read_manifest", "_module_failure_state", "_module_expected_version", "_module_core_contract",
           "_note_failed_module", "_modules_install_bytes", "_module_licensing_view", "_fs_retry", "_rm_dir_or_link"):
    exec(_fn_src(_f), NS)
exec(_route_src('@app.get("/api/modules")', "api_modules_list"), NS)

api_modules_list = NS["api_modules_list"]
install_bytes = NS["_modules_install_bytes"]
note_failed = NS["_note_failed_module"]
S = {k: NS[k] for k in NS if k.startswith("MODULE_STATE_")}


def reset_registry():
    NS["_loaded_modules"].clear()
    NS["_disabled_modules"].clear()
    NS["_failed_modules"].clear()
    NS["_modules_restart_needed"] = False
    _Log.lines[:] = []


def mk_manifest(mid, ver, ru=None, en=None):
    return {"id": mid, "ru": ru or ("Модуль " + mid), "en": en or ("Module " + mid),
            "version": ver, "icon": "module", "entry": "web/Panel.js"}


def mk_zip(mid, ver, extra=None, top=None, manifest=True, corrupt=False):
    """Синтетический .zip модуля. Реальные архивы проекта не используются."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        p = (top + "/") if top else ""
        if manifest:
            z.writestr(p + "module.json", json.dumps(mk_manifest(mid, ver), ensure_ascii=False))
        z.writestr(p + "backend.py", "# " + SENTINEL + "\ndef register(core):\n    pass\n")
        z.writestr(p + "web/Panel.js", "export default {}\n")
        for name, data in (extra or []):
            z.writestr(name, data)
    raw = buf.getvalue()
    if corrupt:
        raw = raw[:len(raw) // 2]
    return raw


def modules_by_id():
    return {m["id"]: m for m in api_modules_list()["modules"]}


print("=" * 95)
print("A. ВИДИМОСТЬ РАЗДЕЛА (frontend-контракт)")
print("=" * 95)

_card = re.search(r'<div [^>]*class="fm-set-group[^"]*"[^>]*data-tour="set-modules"[^>]*>', _HTML)
check("A1. карточка «Модули» существует в разметке настроек", _card is not None)
_gate = _card.group(0) if _card else ""
check("A2. КРИТИЧНО: карточка НЕ гейтится редакцией программы (edHas)", "edHas" not in _gate)
check("A3. КРИТИЧНО: 'modules' убран из списка возможностей, вычеркнутых редакцией",
      not re.search(r"_editionRemoved = \{[^}]*'modules'", _APP))
check("A4. карточка гейтится только правом оператора", "can('operate')" in _gate)
check("A5. КРИТИЧНО: список модулей приходит с backend, а не из localStorage",
      "fetch('/api/modules')" in _APP
      and not re.search(r"localStorage\.(get|set)Item\('[^']*module", _APP, re.I))
_CARD = _modules_card()
check("A6. КРИТИЧНО: в карточке «Модули» нет хардкода Inventory/Cost/Quality "
      "(будущий модуль появляется сам из реестра backend)",
      not re.search(r"inventory|cost|quality", _CARD, re.I))
check("A7. список строится циклом по данным backend",
      'v-for="m in problemModules"' in _HTML and 'v-for="l in moduleLaunchers"' in _HTML)
check("A8. раздел один и тот же для Browser/Desktop/Client (нет ветвления по оболочке)",
      not re.search(r"(isDesktop|isClient|webview|userAgent)", _gate, re.I))

print()
print("=" * 95)
print("B. РЕЕСТР: загруженные И не загруженные модули")
print("=" * 95)

reset_registry()
NS["_loaded_modules"]["quality"] = {"manifest": mk_manifest("quality", "0.2.3"), "dir": "d", "source": "user"}
note_failed("inventory", os.path.join(MODULES_DIR, "inventory"), "user",
            S["MODULE_STATE_VERSION_MISMATCH"], manifest=mk_manifest("inventory", "1.7.23"))
note_failed("cost", os.path.join(MODULES_DIR, "cost"), "user",
            S["MODULE_STATE_VERSION_MISMATCH"], manifest=mk_manifest("cost", "0.1.2"))
NS["_disabled_modules"]["demo"] = {"manifest": mk_manifest("demo", "1.0.0"), "dir": "d", "source": "user"}
mods = modules_by_id()

check("B1. КРИТИЧНО: не загрузившиеся модули ПРИСУТСТВУЮТ в ответе (раньше исчезали)",
      "inventory" in mods and "cost" in mods)
check("B2. загруженный модуль отдаётся как loaded", mods["quality"]["state"] == S["MODULE_STATE_LOADED"])
check("B3. несовпадение версии отдаётся отдельным состоянием",
      mods["inventory"]["state"] == S["MODULE_STATE_VERSION_MISMATCH"])
check("B4. отключённый пользователем модуль отдаётся как disabled",
      mods["demo"]["state"] == S["MODULE_STATE_DISABLED"])
check("B5. КРИТИЧНО: видно, что установлено и что требуется",
      mods["inventory"]["installed_version"] == "1.7.23"
      and mods["inventory"]["expected_version"] == "1.7.29"
      and mods["cost"]["installed_version"] == "0.1.2"
      and mods["cost"]["expected_version"] == "0.1.3")
check("B6. один сломанный модуль не скрывает остальные", len(mods) == 4)
_dump = json.dumps(api_modules_list(), ensure_ascii=False)
check("B7. КРИТИЧНО: в ответе нет абсолютных путей", TMP_ROOT not in _dump and ":\\" not in _dump)
check("B8. КРИТИЧНО: в ответе нет traceback и деталей исключений",
      "Traceback" not in _dump and "Exception" not in _dump and "test-exc" not in _dump)
check("B9. состояние — только объявленный машинный код",
      all(m["state"] in NS["MODULE_STATES"] for m in api_modules_list()["modules"]))

reset_registry()
note_failed("brokenmanifest", os.path.join(MODULES_DIR, "brokenmanifest"), "user",
            S["MODULE_STATE_INVALID_MANIFEST"])
note_failed("badroutes", os.path.join(MODULES_DIR, "badroutes"), "user",
            S["MODULE_STATE_ROUTE_MISMATCH"], manifest=mk_manifest("badroutes", "1.0"))
note_failed("crashed", os.path.join(MODULES_DIR, "crashed"), "user",
            S["MODULE_STATE_LOAD_ERROR"], manifest=mk_manifest("crashed", "1.0"))
mods = modules_by_id()
check("B10. повреждённый манифест виден как отдельное состояние",
      mods["brokenmanifest"]["state"] == S["MODULE_STATE_INVALID_MANIFEST"])
check("B11. несовпадение маршрутов видно как отдельное состояние",
      mods["badroutes"]["state"] == S["MODULE_STATE_ROUTE_MISMATCH"])
check("B12. ошибка запуска видна как отдельное состояние",
      mods["crashed"]["state"] == S["MODULE_STATE_LOAD_ERROR"])
check("B13. ожидаемая версия НЕ выдумывается для не-версионных отказов",
      mods["badroutes"]["expected_version"] == "" and mods["crashed"]["expected_version"] == "")
check("B14. модуль без манифеста всё равно опознан по имени папки", "brokenmanifest" in mods)

check("B15. классификация отказа: версия отделена от прочих",
      NS["_module_failure_state"](["x: версия модуля не совпадает с реестром"]) == S["MODULE_STATE_VERSION_MISMATCH"]
      and NS["_module_failure_state"](["x: метод не совпадает с реестром"]) == S["MODULE_STATE_ROUTE_MISMATCH"]
      and NS["_module_failure_state"]([]) == S["MODULE_STATE_ROUTE_MISMATCH"])
check("B16. ожидаемая версия читается из карты прав ядра",
      NS["_module_expected_version"]("inventory") == "1.7.29"
      and NS["_module_expected_version"]("nosuch") == "")

reset_registry()
check("B17. пустой реестр — это пустой список, а не ошибка", api_modules_list()["modules"] == [])
NS["_loaded_modules"]["quality"] = {"manifest": mk_manifest("quality", "0.2.3"), "dir": "d", "source": "user"}
note_failed("quality", "d", "user", S["MODULE_STATE_LOAD_ERROR"], manifest=mk_manifest("quality", "0.2.3"))
check("B18. загруженный модуль не дублируется записью об отказе",
      len([m for m in api_modules_list()["modules"] if m["id"] == "quality"]) == 1)

print()
print("=" * 95)
print("C. УСТАНОВКА .ZIP")
print("=" * 95)

reset_registry()
r = install_bytes(mk_zip("alpha", "1.0.0"))
check("C1. корректный .zip принимается", r["status"] == "ok" and r["id"] == "alpha")
check("C2. КРИТИЧНО: успех требует перезапуска", r.get("restart_required") is True and NS["_modules_restart_needed"])
check("C3. файлы распакованы в папку модуля",
      os.path.isfile(os.path.join(MODULES_DIR, "alpha", "module.json"))
      and os.path.isfile(os.path.join(MODULES_DIR, "alpha", "web", "Panel.js")))
check("C4. версия читается из module.json архива",
      json.load(open(os.path.join(MODULES_DIR, "alpha", "module.json"), encoding="utf-8"))["version"] == "1.0.0")

r = install_bytes(mk_zip("beta", "2.0.0", top="beta-1.0"))
check("C5. архив с единственной верхней папкой поддерживается",
      r["status"] == "ok" and os.path.isfile(os.path.join(MODULES_DIR, "beta", "module.json")))

check("C6. КРИТИЧНО: не-zip блокируется", install_bytes(b"this is not a zip")["status"] == "error")
check("C7. КРИТИЧНО: повреждённый архив блокируется",
      install_bytes(mk_zip("gamma", "1.0", corrupt=True))["status"] == "error")
check("C8. КРИТИЧНО: архив без module.json блокируется",
      install_bytes(mk_zip("delta", "1.0", manifest=False))["status"] == "error")

_bad_json = io.BytesIO()
with zipfile.ZipFile(_bad_json, "w") as z:
    z.writestr("module.json", "{ это не json")
check("C9. КРИТИЧНО: битый манифест блокируется", install_bytes(_bad_json.getvalue())["status"] == "error")

for bad_id in ("../evil", "a/b", "a\\b", "..", ""):
    _b = io.BytesIO()
    with zipfile.ZipFile(_b, "w") as z:
        z.writestr("module.json", json.dumps({"id": bad_id, "version": "1.0"}))
    _res = install_bytes(_b.getvalue())
    if _res["status"] != "error":
        check("C10. КРИТИЧНО: недопустимый id модуля (%r) блокируется" % bad_id, False)
        break
else:
    check("C10. КРИТИЧНО: недопустимый id модуля блокируется (traversal/разделители/пусто)", True)

_before = sorted(os.listdir(MODULES_DIR))
#  Имена файлов-беглецов делаем УНИКАЛЬНЫМИ. Прежние «escaped.txt» и «out.txt» — слишком
#  обычные: любой посторонний файл с таким именем во временной папке системы (а туда пишут все
#  подряд) превращал эту проверку в ложную тревогу. Проверка обязана ловить НАШ файл, а не чужой.
_TRAV_A = "escaped_%s.txt" % SENTINEL
_TRAV_B = "out_%s.txt" % SENTINEL
_trav = mk_zip("trav", "1.0", extra=[("../../" + _TRAV_A, b"x"), ("web/../../../" + _TRAV_B, b"x")])
_res = install_bytes(_trav)
_escaped = (os.path.isfile(os.path.join(TMP_ROOT, _TRAV_A))
            or os.path.isfile(os.path.join(os.path.dirname(TMP_ROOT), _TRAV_B))
            or os.path.isfile(os.path.join(MODULES_DIR, "..", _TRAV_A)))
check("C11. КРИТИЧНО: path traversal внутри архива не выходит за папку модуля", not _escaped)
check("C12. КРИТИЧНО: за пределами временного корня ничего не создано",
      not os.path.isfile(os.path.join(os.path.dirname(TMP_ROOT), "escaped.txt")))

_abs = mk_zip("absmod", "1.0", extra=[("C:/Windows/evil.txt", b"x"), ("/etc/evil", b"x")])
install_bytes(_abs)
check("C13. КРИТИЧНО: абсолютные пути в архиве не применяются",
      not os.path.isfile("C:/Windows/evil.txt"))

# ── Данные модуля переживают обновление кода ───────────────────────────────────────────────────
reset_registry()
install_bytes(mk_zip("keeper", "1.0.0"))
_dbdir = os.path.join(TMP_ROOT, "data")
os.makedirs(_dbdir, exist_ok=True)
_db = os.path.join(_dbdir, "farm_keeper.db")
with open(_db, "wb") as f:
    f.write(b"MODULE DATA " + SENTINEL.encode())
_userfile = os.path.join(MODULES_DIR, "keeper", "user_note.txt")
with open(_userfile, "w", encoding="utf-8") as f:
    f.write("x")
r = install_bytes(mk_zip("keeper", "2.0.0"))
check("C14. обновление модуля проходит", r["status"] == "ok")
check("C15. КРИТИЧНО: база данных модуля НЕ удаляется при обновлении кода",
      os.path.isfile(_db) and open(_db, "rb").read().startswith(b"MODULE DATA"))
check("C16. новая версия действительно записана",
      json.load(open(os.path.join(MODULES_DIR, "keeper", "module.json"), encoding="utf-8"))["version"] == "2.0.0")
check("C17. БД модуля лежит ВНЕ папки модуля (потому и переживает переустановку)",
      os.path.dirname(os.path.abspath(_db)) != os.path.abspath(os.path.join(MODULES_DIR, "keeper")))

reset_registry()
install_bytes(mk_zip("first", "1.0.0"))
install_bytes(mk_zip("second", "1.0.0"))
_first_mtime = os.path.getmtime(os.path.join(MODULES_DIR, "first", "module.json"))
install_bytes(mk_zip("second", "1.1.0"))
check("C18. КРИТИЧНО: установка одного модуля не трогает другой",
      os.path.getmtime(os.path.join(MODULES_DIR, "first", "module.json")) == _first_mtime
      and json.load(open(os.path.join(MODULES_DIR, "first", "module.json"), encoding="utf-8"))["version"] == "1.0.0")

_v_before = json.load(open(os.path.join(MODULES_DIR, "first", "module.json"), encoding="utf-8"))["version"]
install_bytes(b"garbage")
check("C19. КРИТИЧНО: отказ валидации оставляет прежнюю установленную версию",
      json.load(open(os.path.join(MODULES_DIR, "first", "module.json"), encoding="utf-8"))["version"] == _v_before)

reset_registry()
note_failed("upd", os.path.join(MODULES_DIR, "upd"), "user",
            S["MODULE_STATE_VERSION_MISMATCH"], manifest=mk_manifest("upd", "0.9"))
install_bytes(mk_zip("upd", "1.0"))
mods = modules_by_id()
check("C20. после переустановки состояние честное: установлен, ждёт перезапуска",
      mods["upd"]["state"] == S["MODULE_STATE_PENDING_RESTART"]
      and mods["upd"]["installed_version"] == "1.0")

print()
print("=" * 95)
print("D. ПРАВА И ГРАНИЦЫ")
print("=" * 95)

_inst_route = _route_src('@app.post("/api/modules/install")', "api_modules_install")
_instpath_route = _route_src('@app.post("/api/modules/install-path")', "api_modules_install_path")
_del_route = _route_src('@app.delete("/api/modules/{module_id}")', "api_modules_delete")
def _admin_guarded(src):
    """Обработчик обязан вызвать системного админа ДО любой работы. Имя параметра запроса
    у обработчиков разное (req / request) — сверяем сам факт вызова, а не написание."""
    return re.search(r"_require_system_admin\((?:req|request)\)", src) is not None


check("D1. КРИТИЧНО: установка из браузера защищена системным админом", _admin_guarded(_inst_route))
check("D2. КРИТИЧНО: установка по пути защищена системным админом", _admin_guarded(_instpath_route))
check("D3. удаление модуля защищено системным админом", _admin_guarded(_del_route))
check("D4. КРИТИЧНО: проверка прав ВЫПОЛНЯЕТСЯ ДО чтения архива",
      _inst_route.index("_require_system_admin") < _inst_route.index("file.read()"))
check("D5. КРИТИЧНО: КАЖДЫЙ маршрут установки/удаления модуля закрыт админом",
      len(re.findall(r'@app\.post\("/api/modules/install', _SRV)) == 2
      and all(_admin_guarded(s) for s in (_inst_route, _instpath_route, _del_route)))
check("D5b. КРИТИЧНО: проверка прав идёт ДО чтения файла с диска",
      _instpath_route.index("_require_system_admin") < _instpath_route.index("open(path"))
check("D6. КРИТИЧНО: путь распаковки задаёт СЕРВЕР, а не frontend",
      "MODULES_USER_DIR" in _fn_src("_modules_install_bytes")
      and "dest = os.path.join(MODULES_USER_DIR, mid)" in _fn_src("_modules_install_bytes"))
check("D7. КРИТИЧНО: оболочка не может объявить себя админом",
      not re.search(r"(webview|desktop|client).{0,40}is_admin", _SRV, re.I))
check("D8. право на управление модулями определяет backend, а не frontend",
      "can('operate')" in _gate and "_require_system_admin" in _SRV)

print()
print("=" * 95)
print("E. ИНТЕРФЕЙС: СОСТОЯНИЯ И ТЕКСТЫ")
print("=" * 95)

check("E1. кнопка установки .zip присутствует", "pickModuleZip()" in _HTML)
check("E2. выбор файла ограничен .zip", "'.zip'" in _APP and "exMode==='modzip'" in _HTML)
check("E3. КРИТИЧНО: состояние загрузки списка отделено от самого списка",
      "modulesLoadState" in _APP and "modulesLoadState" in _HTML)
check("E4. пустой список и ошибка — РАЗНЫЕ состояния",
      "Установленные модули отсутствуют." in _HTML and "Не удалось получить состояние модулей." in _HTML)
check("E5. недостаток прав — отдельное состояние", "Недостаточно прав для управления модулями." in _HTML)
#  2.999: текст переехал на вкладку «Модули» и стал точнее («не загрузились» + куда идти).
#  Проверка прежняя по смыслу: у частичной неудачи ДОЛЖНО быть своё сообщение, отдельное
#  от «модулей нет» и от «нет прав».
check("E6. частичная неудача сообщается отдельно", "не загрузились" in _HTML)
check("E7. есть кнопка повтора загрузки списка", "loadInstalledModules()" in _HTML)

#  ── 3.000: модули на баре и встроенные настройки (заказ владельца 11.09.2026) ───────────
_APPJS = _APP
check("E7а. БАР: модули выводятся кнопками рядом с «Проекты / Задачи / Очередь / Филамент»",
      'class="fm-seg-b ui3-rtabs-mod"' in _HTML and 'v-for="m in barModules"' in _HTML
      and "runModuleById(m.id)" in _HTML)
check("E7б. БАР: модули отделены чертой и прижаты вправо (штатные вкладки слева)",
      'class="ui3-rtabs-sep"' in _HTML and 'class="ui3-rtabs-mods"' in _HTML
      and ".ui3-rtabs-mods{" in _CSS and "margin-left:auto" in _CSS
      #  Группа умеет переносить кнопки: на узком экране бар становится выше, но ничего
      #  не обрезается — проверено осмотром на 1280/1600/1920/2560.
      and "flex-wrap:wrap" in _CSS.split(".ui3-rtabs-mods{")[1][:180])
check("E7в. ВЫБОР: какие модули показывать на баре — отдельная секция с флажками",
      'id="fm-sec-modbar"' in _HTML and 'v-for="m in barCandidates"' in _HTML
      and "barModuleToggle(m.id" in _HTML and "barModuleShown(m.id)" in _HTML)
check("E7г. ВЫБОР хранится на сервере как настройка фермы, а не в браузере",
      "bar_modules" in _APPJS and "bar_modules" in _SRV and "_FARM_BAR_MODULES_KEY" in _SRV
      and "_farm_bar_modules_validate" in _SRV)
check("E7д. сервер проверяет форму выбора: только список коротких id, длина ограничена",
      "_BAR_MODULES_MAX" in _SRV and "[A-Za-z0-9_-]+" in _SRV and "bad_bar_module_id" in _SRV)
check("E7е. пока владелец не выбирал — показываются ВСЕ модули с окном (а не ни одного)",
      "barModuleIds.value === null" in _APPJS and "Array.isArray(st.bar_modules)" in _APPJS
      and "barModuleIds.value = _loc;" in _APPJS)
check("E7ж. НАСТРОЙКИ МОДУЛЯ — ячейкой во вкладке «Модули», а не всплывающим окном",
      'v-for="m in modulesWithSettings"' in _HTML and ':is="m.comp"' in _HTML
      and ':embedded="true"' in _HTML and 'class="fm-set-sec-b fm-mod-cfg"' in _HTML)
check("E7з. ячейку даёт САМ модуль: ядро читает settings_entry из его манифеста",
      '"settings_entry": m.get("settings_entry", "")' in _SRV
      and "loadModuleSettingsComponents" in _APPJS and "moduleSettingsComps" in _APPJS)
check("E7и. модуль без settings_entry ячейки не получает — его настройки остаются в окне",
      "if (!m.settings_entry || moduleSettingsComps.value[m.id] || !moduleIsLoaded(m)) continue;" in _APPJS)

#  ── 2.1001: два замечания владельца 11.09.2026 ─────────────────────────────────────────
#  «Названия длинные, бар становится выше» и «галочка ни к чему не приводит».
_bar_btn = _HTML[_HTML.index('v-for="m in barModules"'):]
_bar_btn = _bar_btn[:_bar_btn.index("</button>")]
check("E7к. БАР: на кнопке модуля ТОЛЬКО значок — подписи убраны (бар не растёт от длинных имён)",
      "<svg-icon" in _bar_btn and "ui3-rtabs-mod-t" not in _HTML
      and "m.ru : m.en }}</span>" not in _bar_btn and ".ui3-rtabs-mod{gap:0" in _CSS)
check("E7л. БАР: имя модуля не потеряно — оно в подсказке и доступно чтению с экрана",
      ":title=" in _bar_btn and ":aria-label=" in _bar_btn)
check("E7м. БАР: незнакомый значок модуля подменяется общим — пустых кнопок не бывает",
      "(m.icon && icons[m.icon]) ? m.icon : 'module'" in _APPJS)
check("E7н. ГЛАВНОЕ: отказ сервера НЕ отменяет выбор владельца (было: галочка отскакивала)",
      "barModuleIds.value = prev" not in _APPJS and "barLocalOnly.value = !ok;" in _APPJS
      and "_barLocalWrite(ok ? null : next);" in _APPJS)
check("E7о. при отказе выбор хранится на этом компьютере и переживает перезагрузку страницы",
      "_BAR_LS_KEY" in _APPJS and "localStorage.setItem(_BAR_LS_KEY" in _APPJS
      and "localStorage.getItem(_BAR_LS_KEY)" in _APPJS)
check("E7п. выбор фермы главнее местного: пришёл с сервера — местная копия стирается",
      "barLocalOnly.value = false;" in _APPJS and "_barLocalWrite(null);" in _APPJS)
check("E7р. владельцу сказано, что выбор пока только на этом компьютере",
      'v-if="barLocalOnly"' in _HTML and "только на этом компьютере" in _HTML
      and "fm-set-hint-warn" in _HTML and ".fm-set-hint-warn{" in _CSS)

#  ── 2.1002: модуль, у которого есть ТОЛЬКО настройки ───────────────────────────────────
#  Заказ владельца 11.09.2026: «у модуля только настройки — значит, никакого всплывающего окна,
#  настройки встроены во вкладку „Модули“, и только пока модуль установлен».
check("E7с. КОНТРАКТ: модуль без entry — это модуль без окна; ядро узнаёт его по манифесту",
      "const cfgOnly = !m.entry && !!m.settings_entry;" in _APPJS
      and "settingsOnly: cfgOnly" in _APPJS
      and "if (!m.entry || moduleComps.value[m.id]) continue;" in _APPJS)
check("E7т. такой модуль НЕ получает кнопку на баре (там только модули с окном)",
      "moduleIsLoaded(m) && moduleHasUi(m.id)" in _APPJS)
check("E7у. строка в списке остаётся (в ней отключение и удаление), но помечена «настройки ниже»",
      'v-if="l.settingsOnly"' in _HTML and "настройки ниже" in _HTML
      and "'fm-mod-cfgonly': l.settingsOnly" in _HTML and ".fm-set-act.fm-mod-cfgonly{" in _CSS)
check("E7ф. строка без окна не притворяется кнопкой: ни role, ни попадания под Tab",
      "l.settingsOnly ? null : 'button'" in _HTML and "l.settingsOnly ? null : 0" in _HTML)
check("E7х. ячейка настроек появляется только у УСТАНОВЛЕННОГО и работающего модуля",
      "moduleIsLoaded(m) && moduleSettingsComps.value[m.id]" in _APPJS)
check("E7ц. УСТАНОВКА: пояснения убраны — остались заголовок, кнопка и итог",
      "Модуль ставится одним файлом .zip" not in _HTML
      and "Откроется встроенный Проводник" not in _HTML
      and 'id="fm-sec-modinstall"' in _HTML and "pickModuleZip()" in _HTML)

#  ── 2.1003: ячейки настроек модулей — в самом низу вкладки и без своей прокрутки ────────
check("E7ч. ячейка настроек модуля стоит ПОСЛЕ установки — то есть в самом низу вкладки",
      _HTML.index('v-for="m in modulesWithSettings"') > _HTML.index('id="fm-sec-modinstall"'))
check("E7ш. у ячейки нет своей полосы прокрутки: прокручивается сам лист настроек",
      ".fm-mod-cfg{overflow:visible}" in _CSS and "max-height:620px" not in _CSS
      #  Корень содержимого модуля тоже не должен прокручиваться внутри ячейки:
      #  правило ядра перекрывает собственный overflow модуля, каким бы он ни был.
      and ".fm-mod-cfg > *{min-height:0;overflow:visible}" in _CSS)
check("E8. КРИТИЧНО: сообщение о перезапуске присутствует",
      "требуется перезапуск Farm Manager" in _HTML)
check("E9. 401/403 не превращаются в «модулей нет»",
      "r.status === 401" in _APP and "unauthorized" in _APP)
check("E10. неуспешный ответ не оставляет молча пустой список",
      "modulesLoadState.value = 'unavailable'" in _APP)
check("E11. КРИТИЧНО: плитку запуска получает только загруженный модуль",
      "if (!moduleIsLoaded(m)) continue;" in _APP)
check("E12. незагруженный модуль показывается с причиной и кнопкой обновления",
      'v-for="m in problemModules"' in _HTML and "moduleStateText(m)" in _HTML
      and 'Обновить модуль из .zip' in _HTML)
check("E13. подсказка о версиях показывает установленную и требуемую",
      "moduleVersionHint" in _APP and "', требуется '" in _APP)
check("E14. состояние version_mismatch описано понятным текстом",
      "'Требуется обновление'" in _APP)
check("E15. КРИТИЧНО: пользователю не показывается traceback",
      "Traceback" not in _HTML and "traceback" not in _APP.lower().split("catch")[0])
check("E16. настройки не закрываются при ошибке установки (сообщение внутри карточки)",
      "moduleInstallMsg" in _HTML and "closeSettings" not in _gate)
check("E17. повторная отправка блокируется во время установки",
      ':disabled="moduleInstalling"' in _HTML)
check("E18. новые функции экспортированы в шаблон",
      all(k in _APP for k in ("modulesLoadState, problemModules", "moduleStateText", "moduleVersionHint")))

print()
print("=" * 95)
print("F. РЕГРЕССИИ И ГРАНИЦЫ БЕЗОПАСНОСТИ")
print("=" * 95)

check("F1. Alpha 2.807: единая модель наблюдения печати на месте",
      "observe_printer_job(" in _SRV and os.path.isfile(os.path.join(REPO, "app", "printer_job_lifecycle.py")))
check("F2. Alpha 2.807: уборка щадит живые наблюдаемые запуски",
      "_pjl_live_job_ids()" in _fn_src("_pjob_recover_stale"))
#  26.09.2026 (слово владельца: любая версия модуля ставится и работает). Прежде F3 закреплял
#  дословный текст отказа «версия модуля не совпадает с реестром» — теперь его в server.py нет:
#  расхождение версии идёт в заметки, а не в отказ. Смысл проверки прежний — право маршрута
#  модуля НЕ ослаблено: оно берётся только из карты прав ядра по методу и итоговому пути (тем же
#  ключом, по которому гейт ищет политику при каждом запросе), а маршрут, которого в карте нет,
#  получает «только администратор». Проверяется исполнением настоящей _module_routes_validate
#  из server.py на настоящей карте прав; подробный набор нового поведения —
#  tools/test_module_version_tolerance.py.
import types as _types

_NSV = {"_route_access": _RA, "_module_rt_policy": _MRP, "_route_registry": _RR, "__builtins__": __builtins__}
exec(_fn_src("_module_routes_validate"), _NSV)
_validate = _NSV["_module_routes_validate"]
_COST = [p for p in _RR.MODULE_POLICIES if p.module_id == "cost"]
_COST_VER = _COST[0].module_version if _COST else ""
_SRC_REG = _fn_src("_register_module")


def _decl(p, **over):
    """Объявление маршрута модулем «Расчёт заказа» — как его делает ModuleCore.add_route."""
    d = {"rel": p.module_route, "full": p.path, "methods": [p.method], "policy_id": p.policy_id,
         "handler": _types.SimpleNamespace(__name__=p.handler)}
    d.update(over)
    return d


def _run_validate(contract, routes):
    core = _types.SimpleNamespace(module_id="cost", module_version=contract, _declared_routes=routes)
    ready, errors = _validate(core)
    return ready, errors, list(getattr(core, "_route_notes", []) or [])


def _cap(d):
    """Право, которое гейт применит к подключённому маршруту: строгая политика или запись карты
    прав, найденная по методу и итоговому пути."""
    rp = d.get("runtime_policy")
    if rp is not None:
        return rp.required_capability
    pol = _RR.module_http_policy(d["methods"][0], d["full"])
    return pol.required_capability if pol is not None else None


_ready, _errs, _notes = _run_validate(_COST_VER, [_decl(p) for p in _COST])
check("F3. проверка прав маршрутов модуля НЕ ослаблена: проверка вызывается при загрузке, "
      "у каждого маршрута право из карты прав ядра",
      "_module_routes_validate(core)" in _SRC_REG
      and len(_COST) >= 5 and len(_ready) == len(_COST) and not _errs and not _notes
      and all("runtime_policy" not in d for d in _ready)
      and all(_cap(d) == p.required_capability for d, p in zip(_ready, _COST)))

_ready, _errs, _notes = _run_validate("0.0.1", [_decl(p) for p in _COST])
check("F3а. КРИТИЧНО: другая версия модуля больше НЕ отвергается — все маршруты готовы, "
      "расхождение записано в заметки, а не в отказ",
      len(_ready) == len(_COST) and not _errs
      and not any("версия модуля не совпадает" in e for e in _errs)
      and any("0.0.1" in n and _COST_VER in n for n in _notes))
check("F3б. КРИТИЧНО: при другой версии право маршрутов прежнее — из карты прав, не строгое и не ослабленное",
      all("runtime_policy" not in d for d in _ready)
      and all(_cap(d) == p.required_capability for d, p in zip(_ready, _COST)))

_idx_before = dict(_RR._RUNTIME_MODULE_HTTP_INDEX)
_new_route = _decl(_COST[0], rel="brand-new-report", full="/api/mod/cost/brand-new-report", methods=["GET"],
                   policy_id="cost.brand_new.read", handler=_types.SimpleNamespace(__name__="api_brand_new"))
_ready, _errs, _notes = _run_validate(_COST_VER, [_decl(p) for p in _COST] + [_new_route])
_rt = [d for d in _ready if d.get("runtime_policy") is not None]
check("F3в. КРИТИЧНО: маршрут, которого нет в карте прав, модуль не отвергает, но получает строгую "
      "политику — только администратор",
      len(_ready) == len(_COST) + 1 and not _errs and len(_rt) == 1
      and _rt[0]["full"] == "/api/mod/cost/brand-new-report"
      and _rt[0]["runtime_policy"].path == "/api/mod/cost/brand-new-report"
      and _rt[0]["runtime_policy"].method == "GET"
      and _rt[0]["runtime_policy"].required_capability == "admin"
      and _rt[0]["runtime_policy"].enforced_access is _RA.EnforcedAccess.CAPABILITY
      and _rt[0]["runtime_policy"].enforcement_stage is _RA.EnforcementStage.MODULE_2_785
      and _MRP.is_runtime(_rt[0]["runtime_policy"])
      and any("brand-new-report" in n for n in _notes))
check("F3г. строгая политика ставится ДО подключения маршрута, а сама проверка в карту прав ничего не пишет",
      _RR._RUNTIME_MODULE_HTTP_INDEX == _idx_before
      and "_module_rt_policy.register(_rp)" in _SRC_REG and "core.app.add_api_route(" in _SRC_REG
      and _SRC_REG.index("_module_rt_policy.register(_rp)") < _SRC_REG.index("core.app.add_api_route("))

_adm = next((p for p in _COST if p.required_capability == "admin"), None)
_view = next((p for p in _COST if p.required_capability == "view"), None)
_inv_pid = next((p.policy_id for p in _RR.MODULE_POLICIES if p.module_id == "inventory"), "")
_ok_fx = _adm is not None and _view is not None and bool(_inv_pid)
_r1, _e1, _n1 = _run_validate(_COST_VER, [_decl(_adm, policy_id=_view.policy_id,
                                                handler=_types.SimpleNamespace(__name__=_view.handler))]
                              if _ok_fx else [])
_r2, _e2, _n2 = _run_validate(_COST_VER, [_decl(_adm, policy_id=_inv_pid)] if _ok_fx else [])
check("F3д. КРИТИЧНО: чужой policy_id (своего «просмотрового» маршрута или другого модуля) и чужой "
      "обработчик права не дают — право идёт от метода и пути, админский маршрут остаётся админским",
      _ok_fx
      and len(_r1) == 1 and not _e1 and "runtime_policy" not in _r1[0] and _cap(_r1[0]) == "admin"
      and any(_view.policy_id in n and _adm.policy_id in n for n in _n1)
      and any(_adm.handler in n for n in _n1)
      and len(_r2) == 1 and not _e2 and "runtime_policy" not in _r2[0] and _cap(_r2[0]) == "admin"
      and any(_inv_pid in n for n in _n2))

_ready, _errs, _notes = _run_validate(_COST_VER, [_decl(_view, methods=["GET", "POST"]), _decl(_view), _decl(_view)]
                                      if _view is not None else [])
check("F3е. то, что подключить нельзя вовсе, по-прежнему не подключается: маршрут с двумя методами "
      "и повтор того же маршрута отвергаются поштучно, остальные маршруты готовы",
      _view is not None and len(_ready) == 1 and len(_errs) == 2
      and any("методов 2" in e for e in _errs) and any("дважды" in e for e in _errs))
check("F4. модуль, чей backend.py упал при запуске, откатывается целиком (26.09.2026: пропуск отдельных маршрутов — намеренно)",
      "_module_rollback(core)" in _fn_src("_register_module"))
check("F5. схема БД не менялась", "CREATE TABLE IF NOT EXISTS printer_job_sessions" in _SRV
      and "ALTER TABLE printer_job_sessions" not in _SRV)
_routes = len(re.findall(r'@app\.(get|post|patch|delete|websocket)\(', _SRV))
check("F6. количество HTTP-маршрутов ожидаемое (2.823 +printer-files; 2.825 +select-for-print; 2.831 +printer-sort-mode ×2; 2.833 +klipper-prestart ×2; 2.839: +klipper-contract-report; 2.870: +камера без перекодирования; 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.927: +3 пометки принтера и настройки фермы)", _routes == 209)   #; 2.947 +staging/sync; 2.948 -pending-printable; 2.978 storage/data project->admin; 2.979 +files/locate; 2.980 +3 net-capture, +4 printer-discovery; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
check("F7. автоматическая отправка выключена",
      re.search(r"^DISPATCH_ENABLED = False", open(os.path.join(REPO, "app", "project_orchestrator.py"),
                                                   encoding="utf-8").read(), re.M) is not None)
check("F8. транспорт выключен",
      re.search(r"^TRANSPORT_ENABLED = False", open(os.path.join(REPO, "app", "project_orchestrator.py"),
                                                    encoding="utf-8").read(), re.M) is not None)
check("F9. тест не открывал сокетов и не запускал подпроцессов", not _VIOLATIONS)
check("F10. sentinel живёт только в оснастке теста",
      SENTINEL not in _SRV and SENTINEL not in _HTML and SENTINEL not in _APP)
check("F11. рабочие модули репозитория тестом не менялись",
      all(os.path.isfile(os.path.join(REPO, "modules", d, "module.json"))
          for d in ("inventory", "cost", "quality")))
check("F12. установка выполнялась ТОЛЬКО во временную папку",
      os.path.realpath(MODULES_DIR).startswith(TMP_ROOT))
#  23.09.2026: стабилен КОНТРАКТ модуля с ядром (core_contract; без него — version), номер выпуска
#  меняется свободно. Смысл проверки прежний: тест не трогал модули репозитория.
def _contract(mid):
    _m = json.load(open(os.path.join(REPO, "modules", mid, "module.json"), encoding="utf-8"))
    return _m.get("core_contract") or _m["version"]


check("F13. контракты модулей в репозитории не тронуты",
      _contract("inventory") == "1.7.29" and _contract("cost") == "0.2.0"   # 3.0: «Расчёт заказа»
      and _contract("quality") == "0.2.3")

print()
print("=" * 95)
_verdict[0] = True
print("Проверок выполнено: %d, провалено: %d" % (_checked, fail))
if fail:
    print("FAIL: %d проверок провалено" % fail)
else:
    print("PASS: раздел «Модули» существует всегда и не зависит от редакции; установленные, но не "
          "загруженные модули видны с причиной и версиями; установка .zip проверяется и защищена "
          "правами; данные модулей переживают обновление кода.")
raise SystemExit(1 if fail else 0)
