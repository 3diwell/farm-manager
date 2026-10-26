# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Тест защиты от повторного запуска (Alpha 2.770).

БЕЗОПАСЕН: НЕ импортирует production server.py (читает его только как ТЕКСТ),
не открывает рабочие БД, не обращается к принтерам, не запускает сервер.
Замок берётся под УНИКАЛЬНЫМ именем на каждый прогон — рабочая копия программы,
если она запущена, этим тестом не затрагивается.

Запуск:  python tools/test_single_instance_guard.py
"""

import os
import subprocess
import sys
import time
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import single_instance as si   # noqa: E402  (после правки sys.path)

_fail = 0
_pass = 0


def check(name, cond):
    global _fail, _pass
    if cond:
        _pass += 1
        print("  OK   %s" % name)
    else:
        _fail += 1
        print("  FAIL %s" % name)


def uniq_name():
    """Своё имя замка на каждую проверку — чтобы не пересечься с рабочей копией."""
    return r"Local\3DIWELL_TEST_%s" % uuid.uuid4().hex


# Дочерний процесс: берёт замок и (в режиме hold) держит его заданное время.
HELPER = (
    "import sys, time\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from app import single_instance as si\n"
    "name, mode, wait = sys.argv[2], sys.argv[3], float(sys.argv[4])\n"
    "r = si.acquire(is_pool_worker=(mode == 'pool'), wait_seconds=wait, mutex_name=name)\n"
    "print(r.status)\n"
    "sys.stdout.flush()\n"
    "if mode == 'hold' and r.ok:\n"
    "    time.sleep(float(sys.argv[5]))\n"
)


def spawn(name, mode, wait=0.0, hold=0.0):
    """Запустить дочерний процесс-помощник. Возвращает Popen."""
    args = [sys.executable, "-c", HELPER, ROOT, name, mode, str(wait), str(hold)]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")


def first_line(proc, timeout=20.0):
    """Прочитать первую строку stdout дочернего процесса (его статус)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        line = proc.stdout.readline()
        if line:
            return line.strip()
        if proc.poll() is not None:
            return (proc.stdout.read() or "").strip()
    return "<timeout>"


def run(name, mode, wait=0.0):
    """Синхронно выполнить помощника и вернуть его статус."""
    p = spawn(name, mode, wait)
    out = first_line(p)
    p.wait(timeout=20)
    return out


print("=== Тест защиты от повторного запуска (single instance) ===")
IS_WIN = sys.platform.startswith("win")
if not IS_WIN:
    print("  (не Windows: проверяется только fail-open поведение)")

# --- 1. Первый процесс получает замок ---------------------------------------
NAME = uniq_name()
holder = spawn(NAME, "hold", 0.0, 8.0)
st_holder = first_line(holder)
check("1. первый процесс получает mutex", st_holder == si.ACQUIRED)

# --- 2. Второй обычный запуск: already_running и БЕЗ ожидания ----------------
if IS_WIN:
    t0 = time.time()
    st_second = run(NAME, "normal", 0.0)
    dt = time.time() - t0
    check("2. второй обычный запуск -> already_running", st_second == si.ALREADY_RUNNING)
    check("2b. второй запуск НЕ ждёт (быстрый отказ)", dt < 6.0)
else:
    check("2. (не Windows) guard fail-open", si.acquire(mutex_name=NAME).status == si.UNSUPPORTED)
    check("2b. (не Windows) пропуск проверки времени", True)

# --- 3. Замок первого перехватить нельзя ------------------------------------
if IS_WIN:
    check("3. повторная попытка тоже отклонена (замок не перехвачен)",
          run(NAME, "normal", 0.0) == si.ALREADY_RUNNING and holder.poll() is None)
else:
    check("3. (не Windows) пропуск", True)

# --- 7. Воркер пула обходит guard (даже пока замок занят) -------------------
check("7. multiprocessing worker обходит guard", run(NAME, "pool", 0.0) == si.POOL_WORKER)

# --- 5. Штатный restart: ждёт и получает замок после ухода старой копии ------
if IS_WIN:
    waiter = spawn(NAME, "normal", 15.0)       # режим ожидания, как при перезапуске кнопкой
    time.sleep(0.5)
    check("5a. ожидающий НЕ получает замок, пока старая копия жива", waiter.poll() is None)
    holder.terminate()                          # старая копия завершилась
    t0 = time.time()
    st_wait = first_line(waiter, timeout=25.0)
    check("5b. после завершения старой копии ожидающий получает mutex", st_wait == si.ACQUIRED)
    check("5c. ожидание уложилось в таймаут", time.time() - t0 < 20.0)
    waiter.wait(timeout=20)
else:
    holder.terminate()
    check("5a. (не Windows) пропуск", True)
    check("5b. (не Windows) пропуск", True)
    check("5c. (не Windows) пропуск", True)

try:
    holder.wait(timeout=10)
except Exception:
    pass

# --- 4. После завершения первого замок снова свободен ------------------------
NAME2 = uniq_name()
h2 = spawn(NAME2, "hold", 0.0, 1.0)
check("4a. первый владелец занял замок", first_line(h2) == si.ACQUIRED)
h2.wait(timeout=15)
check("4. после завершения владельца замок снова свободен",
      run(NAME2, "normal", 0.0) in (si.ACQUIRED, si.UNSUPPORTED))

# --- 6. Restart timeout завершается безопасно --------------------------------
if IS_WIN:
    NAME3 = uniq_name()
    h3 = spawn(NAME3, "hold", 0.0, 10.0)
    check("6a. владелец занял замок", first_line(h3) == si.ACQUIRED)
    t0 = time.time()
    st_to = run(NAME3, "normal", 1.0)           # ждём всего 1 с — старая копия не уйдёт
    dt = time.time() - t0
    check("6. restart timeout -> wait_timeout", st_to == si.WAIT_TIMEOUT)
    check("6b. таймаут ограничен (не висит)", dt < 12.0)
    h3.terminate()
    try:
        h3.wait(timeout=10)
    except Exception:
        pass
else:
    check("6a. (не Windows) пропуск", True)
    check("6. (не Windows) пропуск", True)
    check("6b. (не Windows) пропуск", True)

# --- 9 / 10. Handle живёт в процессе; повторный вызов идемпотентен -----------
NAME4 = uniq_name()
r1 = si.acquire(mutex_name=NAME4)
check("9. handle сохранён на время жизни процесса",
      (si._handle is not None) if IS_WIN else (r1.status == si.UNSUPPORTED))
r2 = si.acquire(mutex_name=uniq_name())        # даже с ДРУГИМ именем — исход кэширован
check("10. повторный вызов идемпотентен (тот же результат)", r2 is r1)

# --- 8. Fallback не-Windows не ломает модуль --------------------------------
si._reset_for_tests()
_orig = si._is_windows
try:
    si._is_windows = lambda: False
    rf = si.acquire(mutex_name=uniq_name())
    check("8. не-Windows fallback -> unsupported и ok=True", rf.status == si.UNSUPPORTED and rf.ok)
finally:
    si._is_windows = _orig
    si._reset_for_tests()

check("8b. модуль не тянет ctypes на уровне импорта (импорт безопасен везде)",
      "import ctypes" not in open(os.path.join(ROOT, "app", "single_instance.py"),
                                  encoding="utf-8").read().split("def ")[0])

# --- Статическая проверка ПОРЯДКА в server.py --------------------------------
def code_only(text):
    """Исходник БЕЗ комментариев и докстрок.

    Важно: пояснительные комментарии намеренно упоминают удалённые имена
    (taskkill, _free_port_if_ours) — чтобы будущий читатель понимал, что и почему
    убрано. Наивный поиск по всему тексту принял бы это за живой код, поэтому
    ищем только в РЕАЛЬНОМ коде. Строковые литералы НЕ вырезаем: вызов вида
    subprocess.run(["taskkill", ...]) обязан быть пойман.
    """
    import ast
    import io
    import tokenize
    try:
        tree = ast.parse(text)
    except Exception:
        return text
    blank = set()
    for node in ast.walk(tree):          # докстроки = одиночные строковые выражения
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                blank.add(ln)
    rows = text.splitlines(True)
    rows = ["\n" if (i + 1) in blank else r for i, r in enumerate(rows)]
    txt = "".join(rows)
    try:
        cuts = {}
        for tok in tokenize.generate_tokens(io.StringIO(txt).readline):
            if tok.type == tokenize.COMMENT:
                cuts.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))
        rows = txt.splitlines(True)
        for row, spans in cuts.items():
            s = rows[row - 1]
            for a, b in sorted(spans, reverse=True):
                s = s[:a] + s[b:]
            rows[row - 1] = s
        return "".join(rows)
    except Exception:
        return txt


print("--- порядок вызова guard в server.py ---")
_raw = open(os.path.join(ROOT, "server.py"), encoding="utf-8", errors="surrogateescape").read()
src = code_only(_raw)
check("G-. комментарии и докстроки отброшены (проверяем живой код)", len(src) < len(_raw))

i_guard = src.find("single_instance")
check("G0. guard присутствует в server.py", i_guard > 0)

for label, anchor in (
    ("DATA_DIR = _data_dir()", "DATA_DIR = _data_dir()"),
    ("_resolve_db", "_resolve_db("),
    ("открытие SQLite", "sqlite3.connect("),
    ("_backup_dbs", "_backup_dbs"),
    ("RotatingFileHandler", "RotatingFileHandler"),
    ("init_db", "init_db("),
    ("_load_modules", "_load_modules"),
):
    idx = src.find(anchor)
    check("G. guard раньше, чем %s" % label, idx > 0 and i_guard < idx)

check("G8. воркер пула обходит guard (is_pool_worker передан)",
      "is_pool_worker=_IS_POOL_WORKER" in src)
check("G9. штатный restart ждёт замок (FM_RESTART_WAIT_PORT -> wait_seconds)",
      "RESTART_WAIT_SECONDS if os.environ.get(\"FM_RESTART_WAIT_PORT\")" in src)

# --- Разрушительное поведение удалено ----------------------------------------
print("--- taskkill удалён из стартового пути ---")
check("K1. в server.py нет taskkill", "taskkill" not in src)
check("K2. _pid_image_path удалён", "_pid_image_path" not in src)
check("K3. _free_port_if_ours удалён", "_free_port_if_ours" not in src)
check("K4. проверка порта не завершает процессы", "def _port_available(port):" in src)

print("")
print("PASS: %d проверок" % _pass if not _fail else "FAIL: %d из %d проверок провалено" % (_fail, _pass + _fail))
sys.exit(1 if _fail else 0)
