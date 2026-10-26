# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.864 — оснастка обязана убирать за собой: временные каталоги и процессы движка.

ЗАЧЕМ ЭТОТ НАБОР. 22.08.2026 на рабочей машине владельца измерено:

  · 6591 временный каталог и 14 ГБ в папке `_3diwell_gate_tmp`, накопленные за трое суток.
    Папку заводили и раздавали дочерним процессам как TEMP, но не убирали НИКОГДА;
  · 1035 брошенных процессов `msedge.exe`, самый старый прожил шесть суток, и 115 профилей
    `edgeboot_*` в TEMP на 15 ГБ. Профили не удалялись именно потому, что их держали эти
    процессы.

ROOT CAUSE ВТОРОГО — ОДНА СТРОКА, КОТОРАЯ НЕ РАБОТАЛА НИ РАЗУ. В `run_cdp` стояло

    Get-Process msedge,chrome | Where-Object { $_.Path -like '*edgeboot_*' } | Stop-Process

`$_.Path` — путь к самому исполняемому файлу движка (`...\\Edge\\Application\\msedge.exe`).
Метка профиля в нём не встречается никогда, условие не совпадало ни с одним процессом, и не
закрывался ни один. Метка живёт в СТРОКЕ ЗАПУСКА (`--user-data-dir=...`).

Дефект прожил долго ровно потому, что «уборка» выглядела написанной. Никто не измерял, что
она делает. Этот набор измеряет — и уборку каталогов, и способ отбора процессов.

ЧТО ПРОВЕРЯЕТСЯ:
  · `purge_gate_tmp` реально удаляет содержимое, сохраняя саму папку;
  · отметка времени соблюдается: свежее чужого прогона остаётся, старое уносится;
  · занятый файл не роняет уборку, а попадает в «оставлено»;
  · уборка вызывается в `finally` — то есть и при падении, и при прерывании с клавиатуры;
  · уборка вызывается ДО прогона (мусор прошлых запусков);
  · ни один инструмент больше не отбирает процессы по `$_.Path`;
  · отбор идёт по `CommandLine`, и реализация ровно одна на весь проект;
  · ЖИВОЕ ДОКАЗАТЕЛЬСТВО на настоящем процессе: отбор по `CommandLine` находит процесс с
    меткой, отбор по `$_.Path` — не находит. Именно эта разница и была дефектом.

Ни сервера, ни сети, ни браузера: живая часть поднимает обычный `powershell -Command Start-Sleep`
с меткой в аргументах и снимает его за собой в `finally`.

Запуск:  python tools/test_gate_cleanup_and_browser_kill.py      (0 = оснастка убирает за собой)
"""
import ast
import io
import re
import os
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SENTINEL = "GATE_CLEANUP_BROWSER_KILL_SENTINEL_2_864"
_pass = [0]
_fail = []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace").read()


# ═══════════════ 1. Уборка временных каталогов работает ═══════════════
print("--- 1. purge_gate_tmp реально убирает ---")

import release_gate as RG  # noqa: E402

check("1. функция уборки существует", hasattr(RG, "purge_gate_tmp"))

sandbox = tempfile.mkdtemp(prefix="gatepurge_")
try:
    for i in range(3):
        os.makedirs(os.path.join(sandbox, "leftover_%d" % i))
        io.open(os.path.join(sandbox, "leftover_%d" % i, "junk.txt"), "w").write("x")
    io.open(os.path.join(sandbox, "loose.tmp"), "w").write("x")

    gone, kept = RG.purge_gate_tmp(sandbox)
    check("2. убраны и каталоги, и одиночные файлы", gone == 4 and kept == 0, (gone, kept))
    check("3. содержимое действительно исчезло с диска", os.listdir(sandbox) == [],
          os.listdir(sandbox))
    check("4. САМА папка оставлена — её путь уже роздан дочерним процессам как TEMP",
          os.path.isdir(sandbox))

    # Отметка времени: старое уносим, свежее чужого прогона оставляем.
    old_d = os.path.join(sandbox, "old_run")
    new_d = os.path.join(sandbox, "fresh_run")
    os.makedirs(old_d)
    os.makedirs(new_d)
    past = time.time() - 3600
    os.utime(old_d, (past, past))
    gone, kept = RG.purge_gate_tmp(sandbox, older_than=time.time() - 60)
    check("5. старое унесено, свежее оставлено (не выдёргиваем файлы из-под соседнего прогона)",
          gone == 1 and kept == 1 and os.path.isdir(new_d) and not os.path.exists(old_d),
          (gone, kept, os.listdir(sandbox)))

    # Занятый файл не роняет уборку.
    busy = os.path.join(sandbox, "busy.tmp")
    fh = io.open(busy, "w")
    fh.write("held")
    fh.flush()
    try:
        gone, kept = RG.purge_gate_tmp(sandbox)
        check("6. занятый файл не роняет уборку — он попадает в «оставлено»", kept >= 1,
              (gone, kept))
    finally:
        fh.close()

    check("7. несуществующая папка не роняет уборку",
          RG.purge_gate_tmp(os.path.join(sandbox, "нет-такой")) == (0, 0))
    check("8. пустой путь не роняет уборку", RG.purge_gate_tmp("") == (0, 0))
finally:
    import shutil
    shutil.rmtree(sandbox, ignore_errors=True)


# ═══════════════ 2. Уборка ВЫЗЫВАЕТСЯ, причём в finally ═══════════════
print("\n--- 2. уборка вызывается и переживает падение прогона ---")

GATE = src("tools/release_gate.py")
tree = ast.parse(GATE)
main_fn = next((n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
check("9. функция main разбирается", main_fn is not None)

calls_in_finally = 0
has_try_finally = False
for node in ast.walk(main_fn) if main_fn else []:
    if isinstance(node, ast.Try) and node.finalbody:
        has_try_finally = True
        for sub in ast.walk(ast.Module(body=node.finalbody, type_ignores=[])):
            if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") == "purge_gate_tmp":
                calls_in_finally += 1

check("10. прогон обёрнут в try/finally", has_try_finally)
check("11. уборка за собой стоит именно в finally — иначе падение и Ctrl+C оставят мусор",
      calls_in_finally >= 1, calls_in_finally)

all_calls = sum(1 for n in ast.walk(main_fn) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "purge_gate_tmp") if main_fn else 0
check("12. уборка вызывается дважды: до прогона (мусор прошлых) и после (свой)",
      all_calls >= 2, all_calls)


# ═══════════════ 3. Отбор процессов движка ═══════════════
print("\n--- 3. процессы движка отбираются по строке запуска, а не по пути к программе ---")

import glob  # noqa: E402

offenders = []
for p in sorted(glob.glob(os.path.join(ROOT, "tools", "**", "*.py"), recursive=True)):
    if os.path.basename(p) == os.path.basename(__file__):
        continue
    s = io.open(p, encoding="utf-8", errors="replace").read()
    for line in s.splitlines():
        if line.lstrip().startswith("#"):
            continue          # объяснение дефекта в комментарии — не дефект
        if "$_.Path" in line and "Stop-Process" in s:
            offenders.append(os.path.relpath(p, ROOT))
            break

check("13. ни один инструмент не отбирает процессы движка по `$_.Path` — путь к msedge.exe "
      "метку профиля не содержит НИКОГДА", not offenders, offenders)

EDGE = src("tools/_edge_dom.py")
check("14. общий драйвер отбирает по CommandLine",
      "CommandLine" in EDGE and "Win32_Process" in EDGE)

BOOT = src("tools/test_frontend_boot_and_printer_sort.py")
check("15. набор boot-регрессии снимает движок по профилю", "_kill_by_profile(prof)" in BOOT)
check("16. и делает это ЧУЖОЙ реализацией из общего драйвера, а не своей второй копией",
      "_edge_dom._kill_by_profile" in BOOT and "Get-Process msedge,chrome" not in BOOT)

# Подметальщик гейта — вторая линия обороны: он снимает движки, за которыми набор не прибрал.
# Работает по списку известных меток профилей. Метки 'edgeboot_' в списке НЕ БЫЛО, и это вторая
# причина накопления: собственная уборка набора не работала, а подметальщик про его профили не
# знал. Любой новый префикс временного профиля обязан попадать в этот список.
PREFIXES = set()
for p in sorted(glob.glob(os.path.join(ROOT, "tools", "**", "*.py"), recursive=True)):
    if os.path.basename(p) == os.path.basename(__file__):
        continue
    s = io.open(p, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r'mkdtemp\(\s*prefix\s*=\s*["\']([A-Za-z0-9_.-]+)["\']', s):
        PREFIXES.add(m.group(1))

BROWSER_PREFIXES = sorted(x for x in PREFIXES
                          if x.startswith(("edgeboot", "fm_cdp", "fm-cdp", "fm_stage", "fm-bridge")))
missing = [x for x in BROWSER_PREFIXES if x.rstrip("_-") not in RG._SWEEP]
check("17. подметальщик гейта знает КАЖДУЮ метку временного профиля движка — иначе брошенные "
      "процессы не подберёт никто", not missing, {"нет в списке": missing,
                                                  "найденные метки": BROWSER_PREFIXES})
check("18. метка edgeboot_ в списке подметальщика (её отсутствие и дало 1035 процессов)",
      "edgeboot_" in RG._SWEEP)
check("19. подметальщик отбирает по CommandLine, а не по пути к программе",
      "CommandLine" in RG._SWEEP and "$_.Path" not in RG._SWEEP)


# ═══════════════ 4. Живое доказательство разницы ═══════════════
print("\n--- 4. живое доказательство: почему старый фильтр не находил ничего ---")

marker = "fmproof_" + uuid.uuid4().hex[:10]
proc = None
try:
    proc = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "$x='%s'; Start-Sleep -Seconds 25" % marker],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(2.5)

    def ps(expr):
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", expr],
                           capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.stdout.decode("utf-8", "replace").strip()

    by_cmdline = ps("@(Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | "
                    "Where-Object { $_.CommandLine -and $_.CommandLine.Contains('%s') }).Count" % marker)
    by_path = ps("@(Get-Process powershell -ErrorAction SilentlyContinue | "
                 "Where-Object { $_.Path -like '*%s*' }).Count" % marker)

    check("20. отбор по CommandLine НАХОДИТ процесс с меткой (так делает исправленный код)",
          by_cmdline.isdigit() and int(by_cmdline) >= 1, by_cmdline)
    check("21. отбор по `$_.Path` НЕ находит его — ровно поэтому старая уборка не закрывала "
          "ни одного процесса", by_path.isdigit() and int(by_path) == 0, by_path)
finally:
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            pass

# ── Alpha 2.880: уборка СИСТЕМНОЙ временной папки ─────────────────────────────────────────
# ПОЧЕМУ ПОЯВИЛОСЬ. Прежняя уборка работала только когда TEMP и репозиторий на РАЗНЫХ дисках:
# тогда прогон подменял TEMP своей папкой и чистил её. После переезда проекта на C: подмены не
# стало — и уборки не стало вовсе. Измерено 26.08.2026: в системной временной папке 24 992
# каталога наборов и 71,6 ГБ. Здесь проверяется, что уборка есть, убирает СВОЁ и не трогает
# чужое.
check("22. уборка системной временной папки существует и не зависит от подмены TEMP",
      hasattr(RG, "purge_system_tmp") and isinstance(getattr(RG, "TEST_TMP_PREFIXES", None), tuple))
check("23. список префиксов закрытый и не пустой",
      len(getattr(RG, "TEST_TMP_PREFIXES", ())) >= 10)

_probe = tempfile.mkdtemp(prefix="gatepurge_probe_")
try:
    _own_old = os.path.join(_probe, RG.TEST_TMP_PREFIXES[0] + "old")
    _own_new = os.path.join(_probe, RG.TEST_TMP_PREFIXES[0] + "new")
    _alien = os.path.join(_probe, "claude_not_ours")
    for d in (_own_old, _own_new, _alien):
        os.makedirs(d, exist_ok=True)
        io.open(os.path.join(d, "x.txt"), "w", encoding="utf-8").write("x")
    _past = time.time() - 3600.0
    os.utime(_own_old, (_past, _past))
    os.utime(_alien, (_past, _past))
    _gone, _kept = RG.purge_system_tmp(older_than=time.time() - 60.0, tmp_root=_probe)
    check("24. чужое имя без известного префикса не удаляется даже старым",
          os.path.isdir(_alien), _alien)
    check("25. своё старое убрано, своё свежее осталось",
          not os.path.isdir(_own_old) and os.path.isdir(_own_new), (_gone, _kept))
finally:
    import shutil
    shutil.rmtree(_probe, ignore_errors=True)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for f in _fail:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if _fail else 0)
