# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-109 (16.10.2026): проверка установщика на чистой Windows не трогает компьютер фермы.

tools/installer/sandbox/run_install_test.ps1 СТАВИТ программу, пишет порт в config.json папки
данных, меняет брандмауэр и запускает окно. Внутри Windows Sandbox это и нужно, а на компьютере,
где работает ферма, это переставило бы программу поверх и записало бы порт в настоящие настройки.

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ (скрипт запускается по-настоящему, Windows PowerShell 5.1):
  1. Вне песочницы без ключей — отказ, код 2, папка результатов не создана.
  2. С -AllowOutsideSandbox, но на компьютере уже есть папка программы в Program Files — отказ,
     код 2, ничего не создано. То же, если есть папка данных %LOCALAPPDATA%\\3DIWELL.
  3. С -AllowOutsideSandbox на чистом компьютере — скрипт работает и пишет result.json.
  4. Второй ключ -IKnowThisIsNotTheFarm снимает отказ из пункта 2.
БЕЗОПАСНОСТЬ ПРОГОНА: Program Files и LOCALAPPDATA подменены временными папками (подмена
сверяется в том же процессе PowerShell до запуска скрипта — не подменилось, скрипт не запускается
и набор краснеет); папка выпуска
пустая, поэтому установщика нет и ставить нечего; окна программы во временной Program Files нет,
поэтому запускать нечего. Брандмауэр только читается. Сети нет.

Запуск: python tools/test_install_sandbox_guard.py   (0 = пройдено)
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "tools", "installer", "sandbox", "run_install_test.ps1")

FAILS, PASSED, SKIPS = [], [0], []


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — " + name)
    else:
        FAILS.append(name)
        print("FAIL — " + name + (("  :: %s" % (extra,))[:700] if extra != "" else ""))


def finish():
    print("\n" + "=" * 70)
    print("ИТОГО: PASS=%d FAIL=%d SKIP=%d" % (PASSED[0], len(FAILS), len(SKIPS)))
    for f in FAILS:
        print("  ПРОВАЛ: " + f)
    sys.exit(1 if FAILS else 0)


PS = shutil.which("powershell.exe") or shutil.which("powershell")
if not PS or not os.path.isfile(SCRIPT):
    SKIPS.append("all")
    print("SKIP — нет powershell.exe или скрипта %s" % SCRIPT)
    finish()

TMP = tempfile.mkdtemp(prefix="fm_sbx_guard_")


def q(s):
    """Строка PowerShell в одинарных кавычках."""
    return "'" + s.replace("'", "''") + "'"


SENTINEL = 97     # код «подмена не сработала» — скрипт при этом НЕ запускался


def ps_run(pf, lad, args):
    """Запустить скрипт в PowerShell с подменёнными Program Files и LOCALAPPDATA.

    Подмена делается внутри самого процесса PowerShell: переданную снаружи переменную ProgramFiles
    Windows при запуске 64-разрядного процесса выставляет заново (замерено 16.10.2026 — приходила
    настоящая C:\\Program Files). Перед запуском скрипта подмена сверяется; не сошлась — выход с
    кодом SENTINEL, и скрипт не запускается вовсе."""
    cmd = ("$env:ProgramFiles = {pf}; $env:LOCALAPPDATA = {lad}; $env:USERNAME = 'fm_guard_test'; "
           "if (($env:ProgramFiles -ne {pf}) -or ($env:LOCALAPPDATA -ne {lad}) -or "
           "([Environment]::GetEnvironmentVariable('ProgramFiles') -ne {pf})) {{ exit {s} }}; "
           "& {script} {args}; exit $LASTEXITCODE").format(
        pf=q(pf), lad=q(lad), s=SENTINEL, script=q(SCRIPT), args=" ".join(args))
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                       capture_output=True, timeout=300)
    return r.returncode


def run(case, extra_args, busy_pf=False, busy_data=False):
    base = os.path.join(TMP, case)
    pf, lad, rel = (os.path.join(base, x) for x in ("pf", "lad", "release"))
    out = os.path.join(base, "out")
    for d in (pf, lad, rel):
        os.makedirs(d)
    if busy_pf:
        os.makedirs(os.path.join(pf, "3DIWELL Farm Manager"))
    if busy_data:
        os.makedirs(os.path.join(lad, "3DIWELL"))
    rc = ps_run(pf, lad, ["-ReleaseDir", q(rel), "-OutDir", q(out), "-WaitSeconds", "1"] + extra_args)
    if rc == SENTINEL:
        #  Подмена не сработала — скрипт мог бы увидеть настоящую программу и данные; он не запускался.
        check("%s: Program Files и LOCALAPPDATA подменены временными папками" % case, False, rc)
        return None, out
    return rc, out


try:
    print("\n--- 1. вне песочницы без ключей ---")
    rc, out = run("plain", [])
    check("1.1 отказ: код 2, папка результатов не создана", rc == 2 and not os.path.exists(out), rc)

    print("\n--- 2. -AllowOutsideSandbox на компьютере, где уже есть Farm Manager ---")
    rc, out = run("busy_pf", ["-AllowOutsideSandbox"], busy_pf=True)
    check("2.1 есть папка программы в Program Files — отказ: код 2, ничего не создано",
          rc == 2 and not os.path.exists(out), rc)
    rc, out = run("busy_data", ["-AllowOutsideSandbox"], busy_data=True)
    check("2.2 есть папка данных %LOCALAPPDATA%\\3DIWELL — отказ: код 2, ничего не создано",
          rc == 2 and not os.path.exists(out), rc)

    print("\n--- 3. -AllowOutsideSandbox на чистом компьютере ---")
    rc, out = run("clean", ["-AllowOutsideSandbox"])
    res = os.path.join(out, "result.json") if out else ""
    data = {}
    if res and os.path.isfile(res):
        try:
            data = json.loads(io.open(res, encoding="utf-8-sig").read())
        except ValueError:
            data = {}
    check("3.1 скрипт отработал и записал result.json (установщика в пустой папке нет — ok=false)",
          rc == 0 and data.get("user") == "fm_guard_test" and data.get("ok") is False
          and any(c.get("name") == "setup_found" for c in data.get("checks", [])), (rc, sorted(data)))

    print("\n--- 4. второй ключ -IKnowThisIsNotTheFarm ---")
    rc, out = run("override", ["-AllowOutsideSandbox", "-IKnowThisIsNotTheFarm"], busy_pf=True, busy_data=True)
    check("4.1 с обоими ключами отказа нет: result.json записан",
          rc == 0 and out and os.path.isfile(os.path.join(out, "result.json")), rc)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

finish()
