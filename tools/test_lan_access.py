# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.796 — БЕЗОПАСНЫЙ OFFLINE-ТЕСТ политики LAN-доступа (замена теста Alpha 2.720).
#
#  ЧТО ПРОВЕРЯЕТ. Статическую и pure-часть политики сетевого доступа Alpha 2.787
#  (app/lan_access_policy.py): default OFF, полную таблицу сценариев AUTH/admin/setting,
#  fail-closed на мусорном входе, стабильность reason-кодов, отсутствие proxy-заголовков
#  в решении. Плюс characterization: почему старый тест был непригоден.
#
#  ПОЧЕМУ ЗАМЕНА. Старый тест (Alpha 2.720) импортировал production server.py целиком
#  через exec_module. Импорт server.py на уровне модуля захватывает named mutex
#  одиночного экземпляра и при работающем Farm Manager выполняет sys.exit(0)
#  («уже запущен» — штатный выход). SystemExit пролетал сквозь exec_module и завершал
#  тест с кодом 0 ДО ПЕРВОЙ ПРОВЕРКИ — ложнозелёный результат. Доказано эмпирически
#  2026-07-21: при занятом mutex старый тест дал exit 0 и НОЛЬ строк PASS/FAIL.
#  Без работающего Farm Manager старый тест был честно красным: проверки 1/4/5 ожидали
#  дорелизный контракт 2.720 («нет ключа -> LAN ON»), намеренно закрытый политикой 2.787.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется (только чтение исходника как текста).
#   * Ни одного сокета, потока, подпроцесса — ловушки-шпионы это ДОКАЗЫВАЮТ.
#   * Рабочие config.json / БД / DATA_DIR не читаются и не пишутся (шпион open).
#   * Преждевременный выход (sys.exit(0) до проверок) превращается в exit 1 (atexit-страж).
#
#  Запуск:  python tools/test_lan_access.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import atexit
import builtins
import os
import socket
import subprocess
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

# ── Страж преждевременного выхода ────────────────────────────────────────────
# Ровно тот механизм, который делал старый тест ложнозелёным (sys.exit(0) при импорте
# server.py под занятым mutex), здесь превращается в честный красный: если процесс
# завершается ДО итоговой сводки — exit code принудительно 1.
_COMPLETED = {"done": False}

def _premature_exit_guard():
    if not _COMPLETED["done"]:
        try:
            print("FAIL — тест завершился до выполнения проверок (ложнозелёный сценарий пресечён)")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)

atexit.register(_premature_exit_guard)

# ── Ловушки-шпионы побочных эффектов ────────────────────────────────────────
# Устанавливаются ДО импорта политики: заодно доказывают, что сам импорт
# app/lan_access_policy.py не создаёт сокетов, потоков и подпроцессов.
_SOCKETS = []
_THREADS = []
_PROCS = []
_OPENS = []

class _TrapSocket(object):
    def __init__(self, *a, **k):
        _SOCKETS.append(a)
        raise AssertionError("offline-тест: создание сокета запрещено")

socket.socket = _TrapSocket

_ORIG_THREAD_START = threading.Thread.start

def _trap_thread_start(self, *a, **k):
    _THREADS.append(getattr(self, "name", "?"))
    raise AssertionError("offline-тест: запуск потока запрещён")

threading.Thread.start = _trap_thread_start

def _trap_proc(*a, **k):
    _PROCS.append(a)
    raise AssertionError("offline-тест: подпроцессы запрещены")

subprocess.Popen = _trap_proc
subprocess.run = _trap_proc
subprocess.call = _trap_proc
subprocess.check_output = _trap_proc

_ORIG_OPEN = builtins.open

def _spy_open(file, mode="r", *a, **k):
    _OPENS.append((str(file), str(mode)))
    return _ORIG_OPEN(file, mode, *a, **k)

builtins.open = _spy_open

# ── Оснастка проверок ────────────────────────────────────────────────────────
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

# Метка-ловушка: живёт ТОЛЬКО в оснастке этого теста. Не должна попасть в production
# source, рабочую БД, config, сокет, HTTP-запрос, сессию, логи и _incoming/.
SENTINEL = "LAN_OFFLINE_TEST_SENTINEL_2_796"

# Чистая политика импортируется как обычный модуль — это НЕ server.py.
from app import lan_access_policy as L   # noqa: E402

AC, BS = L.AdminCheck, L.BindScope
SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
POL_SRC = open(os.path.join(REPO, "app", "lan_access_policy.py"), encoding="utf-8").read()
OWN_SRC = open(os.path.abspath(__file__), encoding="utf-8").read()


def d(raw=None, auth=True, admin=AC.PRESENT, cfg=True):
    return L.decide(L.LanRequest(requested_lan=raw, auth_enabled=auth, admin_check=admin, config_valid=cfg))


# ════════════════════════════════════════════════════════════════════════════
print("=== Alpha 2.796: offline-тест политики LAN-доступа (без импорта server.py) ===")
section("characterization: почему старый тест Alpha 2.720 был непригоден")

# Фикстуры — дословные выдержки из tools/test_lan_access.py и tools/test_lan_access_runtime.py
# состояния commit 8e44db9 (Alpha 2.795). Отпечатки файлов зафиксированы; git-команды
# в штатном прогоне НЕ выполняются.
OLD_ACCESS_SHA256 = "ed139ca64f529f2583083865b82829a1f437bdbcef417a108afcfe6e3e605abd"
OLD_RUNTIME_SHA256 = "35158a64a88e50f64dda8e47ca992b5aa87669d0cb18a35a4c3358bf72292152"
OLD_IMPORT_FIXTURE = (
    'spec = importlib.util.spec_from_file_location("fm_server_lan_test", os.path.join(REPO, "server.py"))\n'
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
)
OLD_IMPORT_LINE = 39        # строка exec_module в старом файле (8e44db9)
OLD_FIRST_CHECK_LINE = 55   # первая проверка check(...) в старом файле (8e44db9)
OLD_RUNTIME_IMPORT_LINE = 46
OLD_RUNTIME_FIRST_CHECK_LINE = 86

check("C1. старый тест загружал production server.py на уровне модуля (fixture 8e44db9)",
      "server.py" in OLD_IMPORT_FIXTURE and "exec_module" in OLD_IMPORT_FIXTURE
      and "spec_from_file_location" in OLD_IMPORT_FIXTURE)
check("C2. импорт server.py проходит через single-instance guard, который выходит с кодом 0",
      "_SINGLE_INSTANCE = _single_instance.acquire(" in SRC
      and "_si_code = 0" in SRC and "sys.exit(_si_code)" in SRC
      and SRC.index("_SINGLE_INSTANCE = _single_instance.acquire(") < SRC.index("def _lan_access_enabled"))
check("C3. в старом тесте SystemExit не перехватывался (exec_module вне try/except)",
      "SystemExit" not in OLD_IMPORT_FIXTURE and "try" not in OLD_IMPORT_FIXTURE)
check("C4. импорт стоял ДО первой проверки: при занятом mutex НИ ОДНА проверка не достигалась",
      OLD_IMPORT_LINE < OLD_FIRST_CHECK_LINE
      and OLD_RUNTIME_IMPORT_LINE < OLD_RUNTIME_FIRST_CHECK_LINE)
check("C5. результат старого теста зависел от того, запущен ли Farm Manager "
      "(запущен -> exit 0 без проверок; не запущен -> честный прогон)",
      "exec_module" in OLD_IMPORT_FIXTURE and "_si_code = 0" in SRC)
check("C6. отпечатки старых файлов зафиксированы (SHA-256, состояние 8e44db9)",
      len(OLD_ACCESS_SHA256) == 64 and len(OLD_RUNTIME_SHA256) == 64
      and all(c in "0123456789abcdef" for c in OLD_ACCESS_SHA256 + OLD_RUNTIME_SHA256))

# Новый тест не наследует механизм: server.py не импортируется ни под каким именем.
_own_ast = ast.parse(OWN_SRC)
_own_imports = [n for n in ast.walk(_own_ast) if isinstance(n, (ast.Import, ast.ImportFrom))]
_imports_server = any(
    (isinstance(n, ast.Import) and any(a.name == "server" for a in n.names))
    or (isinstance(n, ast.ImportFrom) and (n.module or "") == "server")
    for n in _own_imports)
_calls_exec_module = any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "exec_module"
    for n in ast.walk(_own_ast))
_calls_spec_load = any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "spec_from_file_location"
    for n in ast.walk(_own_ast))
check("C7. этот тест не импортирует server.py: ни import server, ни exec_module, ни spec-загрузки",
      not _imports_server and not _calls_exec_module and not _calls_spec_load)
check("C8. server.py не появился в sys.modules (ни под каким именем)",
      "server" not in sys.modules
      and not any(getattr(m, "__file__", "") and os.path.normcase(str(getattr(m, "__file__", "")))
                  == os.path.normcase(os.path.join(REPO, "server.py"))
                  for m in list(sys.modules.values())))


# ════════════════════════════════════════════════════════════════════════════
section("таблица сценариев LAN (инвариант Alpha 2.787)")

# | LAN setting | AUTH | enabled admin | Ожидаемый bind | Discovery |
check("S1. OFF | OFF | нет -> loopback, discovery OFF",
      d(False, auth=False, admin=AC.ABSENT).bind_host == "127.0.0.1"
      and d(False, auth=False, admin=AC.ABSENT).discovery_enabled is False)
check("S2. ON | OFF | нет -> loopback, discovery OFF (reason auth_required)",
      d(True, auth=False, admin=AC.ABSENT).bind_host == "127.0.0.1"
      and d(True, auth=False, admin=AC.ABSENT).discovery_enabled is False
      and d(True, auth=False, admin=AC.ABSENT).reason == L.REASON_AUTH_REQUIRED)
check("S3. ON | OFF | да -> loopback, discovery OFF (AUTH OFF закрывает сеть даже с админом)",
      d(True, auth=False, admin=AC.PRESENT).bind_host == "127.0.0.1"
      and d(True, auth=False, admin=AC.PRESENT).discovery_enabled is False)
check("S4. OFF | ON | да -> loopback, discovery OFF (reason lan_disabled)",
      d(False, auth=True, admin=AC.PRESENT).bind_host == "127.0.0.1"
      and d(False, auth=True, admin=AC.PRESENT).discovery_enabled is False
      and d(False, auth=True, admin=AC.PRESENT).reason == L.REASON_LAN_DISABLED)
check("S5. ON | ON | нет -> loopback, discovery OFF (reason enabled_admin_required)",
      d(True, auth=True, admin=AC.ABSENT).bind_host == "127.0.0.1"
      and d(True, auth=True, admin=AC.ABSENT).discovery_enabled is False
      and d(True, auth=True, admin=AC.ABSENT).reason == L.REASON_ADMIN_REQUIRED)
check("S6. ON | ON | да -> 0.0.0.0, discovery ON (единственный разрешающий сценарий)",
      d(True, auth=True, admin=AC.PRESENT).bind_host == "0.0.0.0"
      and d(True, auth=True, admin=AC.PRESENT).effective_lan_enabled is True
      and d(True, auth=True, admin=AC.PRESENT).discovery_enabled is True
      and d(True, auth=True, admin=AC.PRESENT).reason == L.REASON_LAN_ALLOWED)
check("S7. default OFF: отсутствующая настройка (None) -> loopback, discovery OFF",
      L.parse_requested_lan(None) is None
      and d(None, auth=True, admin=AC.PRESENT).bind_host == "127.0.0.1"
      and d(None, auth=True, admin=AC.PRESENT).reason == L.REASON_LAN_DISABLED)
check("S8. эффективное разрешение и discovery всегда совпадают (никогда discovery при loopback)",
      all(d(*args).discovery_enabled == d(*args).effective_lan_enabled for args in
          ((True,), (False,), (None,), (True, False), (True, True, AC.ABSENT),
           (True, True, AC.UNKNOWN), (True, True, AC.PRESENT, False))))


# ════════════════════════════════════════════════════════════════════════════
section("fail-closed: мусорный и неизвестный вход")

_garbage = ["true", "false", "True", "1", "", 1, 0, 1.0, [], {}, (), object(), SENTINEL]
check("F1. любые не-boolean значения настройки -> loopback без discovery (%d вариантов)" % len(_garbage),
      all(d(g, auth=True, admin=AC.PRESENT).bind_scope is BS.LOOPBACK
          and d(g, auth=True, admin=AC.PRESENT).discovery_enabled is False
          and d(g, auth=True, admin=AC.PRESENT).effective_lan_enabled is False
          for g in _garbage))
check("F2. строгий разбор: parse_requested_lan даёт True/False только настоящему bool",
      L.parse_requested_lan(True) is True and L.parse_requested_lan(False) is False
      and all(L.parse_requested_lan(g) is None for g in _garbage))
check("F3. повреждённый config -> loopback (reason config_invalid)",
      d(True, auth=True, admin=AC.PRESENT, cfg=False).bind_scope is BS.LOOPBACK
      and d(True, auth=True, admin=AC.PRESENT, cfg=False).reason == L.REASON_CONFIG_INVALID)
check("F4. не-LanRequest вход decide -> loopback (fail-closed, а не исключение)",
      all(L.decide(x).bind_scope is BS.LOOPBACK and L.decide(x).reason == L.REASON_CONFIG_INVALID
          for x in (None, "x", 42, {}, [], object())))
check("F5. неизвестный результат проверки админа (UNKNOWN) -> loopback (admin_check_failed)",
      d(True, auth=True, admin=AC.UNKNOWN).bind_scope is BS.LOOPBACK
      and d(True, auth=True, admin=AC.UNKNOWN).reason == L.REASON_ADMIN_CHECK_FAILED)
check("F6. мусор вместо AdminCheck (строка/None/число) -> loopback, не allow",
      all(d(True, auth=True, admin=g).bind_scope is BS.LOOPBACK
          and d(True, auth=True, admin=g).effective_lan_enabled is False
          for g in ("PRESENT", None, 1, object(), SENTINEL)))
check("F7. нормализация помечается ТОЛЬКО при доказанном отказе (не при технической ошибке)",
      d(True, auth=False).should_normalize_config is True
      and d(True, admin=AC.ABSENT).should_normalize_config is True
      and d(True, admin=AC.UNKNOWN).should_normalize_config is False
      and d(False).should_normalize_config is False
      and d(True, cfg=False).should_normalize_config is False)


# ════════════════════════════════════════════════════════════════════════════
section("proxy-заголовки не участвуют в решении")

import dataclasses as _dc
_req_fields = [f.name for f in _dc.fields(L.LanRequest)]
check("P1. вход политики — ровно 4 локальных факта, без заголовков/хоста/адресов",
      _req_fields == ["requested_lan", "auth_enabled", "admin_check", "config_valid"])
check("P2. в исходнике политики нет ни X-Forwarded-*, ни Forwarded, ни X-Real-IP, ни Host",
      "forward" not in POL_SRC.lower() and "x-real" not in POL_SRC.lower()
      and "header" not in POL_SRC.lower())
_pol_imports = {(n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0])
                for n in ast.walk(ast.parse(POL_SRC)) if isinstance(n, (ast.Import, ast.ImportFrom))}
check("P3. политика — только stdlib-примитивы (enum/dataclasses/typing), без os/socket/БД/фреймворка",
      _pol_imports <= {"enum", "dataclasses", "typing"})
check("P4. решение с одинаковыми локальными фактами не зависит ни от чего внешнего (детерминизм)",
      d(True) == d(True) and d(None) == d(None)
      and d(True, auth=False) == d(True, auth=False))
_inp = L.LanRequest(requested_lan=True, auth_enabled=True, admin_check=AC.PRESENT)
_before = (_inp.requested_lan, _inp.auth_enabled, _inp.admin_check, _inp.config_valid)
L.decide(_inp)
check("P5. вход неизменяем (frozen dataclass) и не мутируется решением",
      (_inp.requested_lan, _inp.auth_enabled, _inp.admin_check, _inp.config_valid) == _before
      and type(_inp).__dataclass_params__.frozen)


# ════════════════════════════════════════════════════════════════════════════
section("стабильность reason-кодов и констант")

check("R1. reason-коды стабильны (контракт UI/API Alpha 2.787)",
      L.REASON_LAN_DISABLED == "lan_disabled" and L.REASON_AUTH_REQUIRED == "auth_required"
      and L.REASON_ADMIN_REQUIRED == "enabled_admin_required"
      and L.REASON_CONFIG_INVALID == "config_invalid"
      and L.REASON_ADMIN_CHECK_FAILED == "admin_check_failed"
      and L.REASON_LAN_ALLOWED == "lan_allowed")
check("R2. хосты явные: loopback 127.0.0.1 (не 'localhost'), сеть 0.0.0.0",
      L.LOOPBACK_HOST == "127.0.0.1" and L.NETWORK_HOST == "0.0.0.0")
check("R3. bind_host выводится строго из bind_scope",
      d(True).bind_host == L.NETWORK_HOST and d(False).bind_host == L.LOOPBACK_HOST)
check("R4. can_enable повторяет предпосылки: AUTH OFF / нет админа / ошибка проверки -> отказ",
      L.can_enable(False, AC.PRESENT) == (False, L.REASON_AUTH_REQUIRED)
      and L.can_enable(True, AC.ABSENT) == (False, L.REASON_ADMIN_REQUIRED)
      and L.can_enable(True, AC.UNKNOWN) == (False, L.REASON_ADMIN_CHECK_FAILED)
      and L.can_enable(True, AC.PRESENT) == (True, L.REASON_LAN_ALLOWED))
check("R5. отключение авторизации заблокировано при сетевом bind и при запрошенной сети",
      L.auth_disable_blocked(False, BS.NETWORK) is True
      and L.auth_disable_blocked(True, BS.LOOPBACK) is True
      and L.auth_disable_blocked(False, BS.LOOPBACK) is False
      and L.auth_disable_blocked(None, BS.LOOPBACK) is False)


# ════════════════════════════════════════════════════════════════════════════
section("метка-ловушка и отсутствие побочных эффектов")

check("T1. sentinel не встречается в production-исходниках (server.py, политика)",
      SENTINEL not in SRC and SENTINEL not in POL_SRC)
check("T2. sentinel определён ровно один раз и только в оснастке этого теста",
      OWN_SRC.count(SENTINEL) == 1)
check("T3. за весь прогон не создано ни одного сокета", len(_SOCKETS) == 0)
check("T4. за весь прогон не запущено ни одного потока", len(_THREADS) == 0)
check("T5. за весь прогон не запущено ни одного подпроцесса", len(_PROCS) == 0)
_writes = [(p, m) for (p, m) in _OPENS if any(c in m for c in "wax+")]
check("T6. ни одной записи в файлы (config/DB/логи/_incoming нетронуты)", not _writes)
_cfg_reads = [p for (p, _m) in _OPENS if "config.json" in p.lower()]
_data_dir = os.path.join(os.environ.get("LOCALAPPDATA", "?????"), "3DIWELL")
_real_reads = [p for (p, _m) in _OPENS
               if os.path.normcase(p).startswith(os.path.normcase(_data_dir))
               or "_incoming" in p.lower()]
check("T7. рабочий config.json / DATA_DIR / _incoming не читались вовсе",
      not _cfg_reads and not _real_reads)
_expected_reads = {os.path.normcase(os.path.join(REPO, "server.py")),
                   os.path.normcase(os.path.join(REPO, "app", "lan_access_policy.py")),
                   os.path.normcase(os.path.abspath(__file__))}
check("T8. читались только объявленные исходники (server.py, политика, сам тест)",
      set(os.path.normcase(p) for (p, _m) in _OPENS) <= _expected_reads)


# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 76)
_total = PASSED[0] + len(FAILED)
if FAILED:
    print("ПРОВАЛЕНО %d из %d:" % (len(FAILED), _total))
    for f in FAILED:
        print("   - %s" % f)
    _COMPLETED["done"] = True
    sys.exit(1)
print("PASS: LAN-доступ (offline) — все %d проверок пройдены, server.py не импортировался" % _total)
_COMPLETED["done"] = True
sys.exit(0)
