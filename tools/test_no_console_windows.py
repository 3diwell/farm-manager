# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""17.09.2026 — ни одна консольная программа продукта не показывает своего окна.

ЗАЧЕМ. Слово владельца 17.09.2026: «при загрузке более одного файла в фарм менеджер у меня
выскакивали окна cmd и не закрывались; на последней версии повторить не удалось». Воспроизвести
сценарий у разработки не получилось (нужна живая машина владельца), но в Windows у такого
поведения одна причина: программа запускает КОНСОЛЬНУЮ программу без флага CREATE_NO_WINDOW,
и система выдаёт ей собственное чёрное окно. Ровно это уже случалось с камерами — Alpha 2.873,
два окна при двух камерах, снимок владельца — и было вылечено этим флагом.

ПОЧЕМУ ИМЕННО ЗАГРУЗКА ФАЙЛОВ. Окно выбора файлов Windows программа открывает через powershell
(_native_pick_files). Этот процесс ЖДЁТ ЧЕЛОВЕКА до десяти минут: если Windows выдала ему окно,
оно и будет висеть всё это время — «выскочило и не закрывается». Столько же живут и окна при
повторных вызовах выбора файлов.

ЧТО ДОКАЗЫВАЕТСЯ. Каждый запуск процесса в продуктовом коде либо получает флаг запуска
(creationflags), либо стоит в списке ОСОЗНАННЫХ исключений с причиной. Новый запуск без флага
красит набор — значит, разговор о нём состоится до выпуска, а не после жалобы владельца.

Безопасность прогона: только чтение исходников (ast), ни один процесс не запускается.

Запуск: python tools/test_no_console_windows.py   (0 = все проверки пройдены)
"""
import ast
import io
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SENTINEL = "NO_CONSOLE_WINDOWS_SENTINEL_1709"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


#  Консольные программы Windows: у них ОБЯЗАН быть флаг, иначе система рисует окно.
CONSOLE_PROGRAMS = {"powershell", "pwsh", "cmd", "tasklist", "netsh", "taskkill", "wmic", "reg", "sc"}
#  Оконные программы: консоли им не выдают, флаг не нужен и ничего не меняет.
GUI_PROGRAMS = {"explorer", "open", "xdg-open"}
#  Осознанные исключения без флага: программа оконная или запуск не под Windows.
ALLOWED_NO_FLAG = {
    ("server.py", "explorer"): "проводник — оконная программа, консоли ей не выдают",
    ("server.py", "open"): "macOS, не Windows",
    ("server.py", "xdg-open"): "Linux, не Windows",
    ("server.py", "(переменная)"): "слайсер: оконная программа, путь берётся из настройки",
}

FILES = ["server.py", "app/desktop_shell.py", "app/restart_cli.py"]
SPAWN_ATTRS = {"run", "Popen", "call", "check_output", "check_call"}


def collect(path):
    """Все запуски процессов в файле: (функция, программа, есть ли флаг, строка)."""
    src = io.open(os.path.join(REPO, path), encoding="utf-8").read()
    tree = ast.parse(src)
    parents = {}
    for node in ast.walk(tree):
        for kid in ast.iter_child_nodes(node):
            parents[kid] = node
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in SPAWN_ATTRS
                and isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
            continue
        prog = "(переменная)"
        if node.args:
            a0 = node.args[0]
            if isinstance(a0, (ast.List, ast.Tuple)) and a0.elts and isinstance(a0.elts[0], ast.Constant) \
                    and isinstance(a0.elts[0].value, str):
                prog = os.path.basename(a0.elts[0].value).lower()
            elif isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                prog = os.path.basename(a0.value).lower()
        flags = [k for k in node.keywords if k.arg == "creationflags"]
        no_window = any("_no_window_flags" in ast.dump(k.value) for k in flags)
        fn = "(модуль)"
        p = parents.get(node)
        while p is not None:
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = p.name
                break
            p = parents.get(p)
        out.append({"file": path, "func": fn, "prog": prog, "has_flags": bool(flags),
                    "no_window": no_window, "line": node.lineno})
    return out


ALL = []
for p in FILES:
    ALL += collect(p)

print("=== 17.09.2026: окна консоли ===")
print()
print("--- 1. Запуски процессов в продукте ---")
check("1. запуски процессов найдены (набор действительно что-то меряет)", len(ALL) >= 15, len(ALL))
for r in sorted(ALL, key=lambda x: (x["file"], x["line"])):
    print("     %-22s %-14s %-16s флаг=%s%s"
          % (r["file"], r["func"][:14], r["prog"][:16], "да " if r["has_flags"] else "НЕТ",
             " (без окна)" if r["no_window"] else ""))

print()
print("--- 2. Консольные программы запускаются без своего окна ---")
console = [r for r in ALL if r["prog"] in CONSOLE_PROGRAMS]
check("2. консольные программы в продукте есть (иначе проверка ниже пуста)", len(console) >= 4, len(console))
bad = [r for r in console if not r["no_window"]]
check("3. КЛЮЧЕВОЕ: каждая консольная программа получает флаг «без окна»", not bad,
      [(r["file"], r["func"], r["prog"], r["line"]) for r in bad])

picker = [r for r in ALL if r["func"] == "_native_pick_files"]
check("4. ЖАЛОБА ВЛАДЕЛЬЦА: окно выбора файлов (powershell) запускается без окна консоли",
      len(picker) == 1 and picker[0]["no_window"], picker)
tasklist = [r for r in ALL if r["prog"] == "tasklist"]
check("5. список процессов (tasklist) — без окна", tasklist and all(r["no_window"] for r in tasklist), tasklist)
netsh = [r for r in ALL if r["prog"] == "netsh"]
check("6. правило брандмауэра (netsh) — без окна", len(netsh) == 2 and all(r["no_window"] for r in netsh), netsh)
ps = [r for r in ALL if r["prog"] in ("powershell", "pwsh")]
check("7. все запуски powershell — без окна", len(ps) >= 2 and all(r["no_window"] for r in ps), ps)

print()
print("--- 3. Исключения названы поимённо ---")
noflag = [r for r in ALL if not r["has_flags"]]
unknown = [r for r in noflag if (r["file"], r["prog"]) not in ALLOWED_NO_FLAG]
check("8. запуск без флага бывает только у оконных программ и не-Windows веток", not unknown,
      [(r["file"], r["func"], r["prog"], r["line"]) for r in unknown])
check("9. оконные программы флага не требуют (список исключений не пустой и объяснён)",
      all(isinstance(v, str) and len(v) > 10 for v in ALLOWED_NO_FLAG.values()))
detached = [r for r in ALL if r["has_flags"] and not r["no_window"]]
check("10. осознанные особые запуски (перезапуск, помощник, backend оболочки) флаг ставят сами",
      len(detached) >= 3, [(r["file"], r["func"], r["line"]) for r in detached])

print()
print("--- 4. Сам флаг ---")
SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
check("11. помощник флага есть и возвращает CREATE_NO_WINDOW",
      "def _no_window_flags():" in SRV and 'getattr(subprocess, "CREATE_NO_WINDOW", 0)' in SRV)
check("12. на не-Windows флага нет — поведение прежнее (getattr с нулём по умолчанию)",
      getattr(subprocess, "CREATE_NO_WINDOW", 0) == (0x08000000 if sys.platform.startswith("win") else 0))
check("13. правило записано словами в самом коде — следующий читатель поймёт, почему так",
      "выскакивали окна cmd" in SRV and "tools/test_no_console_windows.py" in SRV)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
