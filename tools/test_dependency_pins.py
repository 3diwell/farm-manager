# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-149 (16.10.2026): версии пакетов сборки закреплены точно и сборка это проверяет.

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ:
  1. requirements.txt, requirements-build.txt, requirements-desktop-shell.txt — только строки
     «имя==версия» и «-r файл»: ни одного пакета «какой найдётся свежий».
  2. Перечень лицензий, который ставит установщик (THIRD_PARTY_LICENSES.txt), и закрепления
     говорят об одном составе: каждый пакет перечня закреплён той же версией, а каждый пакет
     программы (requirements.txt) есть в перечне с той же версией. Сменили версию в одном месте и
     забыли другое — красное.
  3. tools/build_release.py: read_pins разбирает «-r», [extras], комментарии и имена по PEP 503;
     env_mismatch называет расхождения и не мешает лишним пакетам; check_build_env останавливает
     сборку с точной командой pip, а --env-only ничего не собирает.
Ничего не ставит и не обновляет, в сеть не ходит; от того, какие пакеты стоят на компьютере, итог
не зависит (проверка окружения идёт на временных файлах закреплений).

Запуск: python tools/test_dependency_pins.py   (0 = пройдено)
"""
import contextlib
import importlib.metadata as md
import io
import os
import re
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

FAILS, PASSED = [], [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — " + name)
    else:
        FAILS.append(name)
        print("FAIL — " + name + (("  :: %s" % (extra,))[:700] if extra != "" else ""))


def section(t):
    print("\n--- %s ---" % t)


def norm(name):
    return re.sub(r"[-_.]+", "-", name).strip().lower()


FILES = ("requirements.txt", "requirements-build.txt", "requirements-desktop-shell.txt")
LICENSES = os.path.join(REPO, "packaging", "installer", "licenses", "THIRD_PARTY_LICENSES.txt")
PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([0-9][^\s;,]*)$")


def own_parse(path):
    """Независимый от build_release разбор: -> (закрепления [(имя, версия)], включения, плохие строки)."""
    pins, incs, bad = [], [], []
    for raw in io.open(path, encoding="utf-8-sig"):
        line = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()
        if not line:
            continue
        m = re.match(r"^-r\s+(\S+)$", line)
        if m:
            incs.append(m.group(1))
            continue
        m = PIN_RE.match(line)
        if m:
            pins.append((norm(m.group(1)), m.group(2)))
        else:
            bad.append(line)
    return pins, incs, bad


# ════════════════════════════════════════════════════════════════════════════
section("1. три файла закреплений: только «имя==версия» и «-r файл»")
PINS = {}
for f in FILES:
    p = os.path.join(REPO, f)
    if not os.path.isfile(p):
        check("1. %s есть" % f, False, "нет файла")
        continue
    pins, incs, bad = own_parse(p)
    PINS[f] = pins
    check("1. %s: %d закреплений, незакреплённых строк нет" % (f, len(pins)), pins and not bad, bad)
    dup = sorted(set(n for n, _ in pins if [x for x, _ in pins].count(n) > 1))
    check("1. %s: каждый пакет назван один раз" % f, not dup, dup)
    if f == "requirements-build.txt":
        check("1b. сборка сервера подключает пакеты программы (-r requirements.txt)",
              incs == ["requirements.txt"], incs)
    else:
        check("1b. %s не подключает других файлов" % f, not incs, incs)
srv = dict(PINS.get("requirements.txt", []))
check("1c. numpy не закреплён: сборка сервера его исключает (3diwell.spec excludes)", "numpy" not in srv)
check("1d. пакеты программы на месте: fastapi, uvicorn, cryptography, paho-mqtt, pillow, pystray",
      all(k in srv for k in ("fastapi", "uvicorn", "cryptography", "paho-mqtt", "pillow", "pystray")),
      sorted(srv))
shell = dict(PINS.get("requirements-desktop-shell.txt", []))
check("1e. окно и клиент: pywebview, pythonnet, clr-loader, pyinstaller закреплены",
      all(k in shell for k in ("pywebview", "pythonnet", "clr-loader", "pyinstaller")), sorted(shell))

# ════════════════════════════════════════════════════════════════════════════
section("2. закрепления и перечень лицензий установщика — один состав")
lic_lines = io.open(LICENSES, encoding="utf-8").read().splitlines()
LIC = []
for i, ln in enumerate(lic_lines[:-1]):
    if ln.startswith("===="):
        m = re.match(r"^(\S+) (\d\S*) — ", lic_lines[i + 1])
        if m:
            LIC.append((norm(m.group(1)), m.group(2)))
check("2.0 в перечне лицензий найдены пакеты Python (%d)" % len(LIC), len(LIC) >= 30, len(LIC))
ALL = set()
for pins in PINS.values():
    ALL.update(pins)
missing = ["%s %s" % x for x in LIC if x not in ALL]
check("2.1 каждый пакет перечня лицензий закреплён ровно этой версией в одном из трёх файлов",
      LIC and not missing, missing)
lic_set = set(LIC)
not_in_lic = ["%s==%s" % x for x in PINS.get("requirements.txt", []) if x not in lic_set]
check("2.2 каждый пакет программы (requirements.txt) есть в перечне лицензий той же версией",
      PINS.get("requirements.txt") and not not_in_lic, not_in_lic)
#  Пакет, который есть и в программе (requirements.txt), и в окне/клиенте, попадает в оба EXE —
#  каждая его версия (а они в двух окружениях бывают разные) должна стоять в перечне лицензий.
#  Конкретные версии здесь не записаны: смена версии в обоих местах сразу останется зелёной.
shared = sorted(set(srv) & set(shell))
unlisted = ["%s %s (%s)" % (n, v, where) for n in shared
            for v, where in ((srv[n], "сервер"), (shell[n], "окно")) if (n, v) not in lic_set]
check("2.3 пакеты, общие для программы и окна (%s): версия КАЖДОГО окружения есть в перечне лицензий"
      % ", ".join(shared), shared and not unlisted, unlisted)

# ════════════════════════════════════════════════════════════════════════════
section("3. build_release.read_pins")
import build_release as B  # noqa: E402

TMP = tempfile.mkdtemp(prefix="fm_pins_")
try:
    base = os.path.join(TMP, "base.txt")
    top = os.path.join(TMP, "top.txt")
    io.open(base, "w", encoding="utf-8").write(
        "# шапка\n\nuvicorn[standard]==0.52.4   # с extras\nPyYAML==6.0.3\ntyping_extensions==4.16.0\n")
    io.open(top, "w", encoding="utf-8").write("-r base.txt\npyinstaller==6.22.2\n")
    got = B.read_pins(top)
    check("3.1 «-r» читается, [extras] и комментарии отброшены, имена — по PEP 503",
          got == {"uvicorn": "0.52.4", "pyyaml": "6.0.3", "typing-extensions": "4.16.0",
                  "pyinstaller": "6.22.2"}, got)
    for bad_line in ("fastapi\n", "fastapi>=0.100\n", "fastapi==\n", "--index-url https://x\n"):
        bp = os.path.join(TMP, "bad.txt")
        io.open(bp, "w", encoding="utf-8").write("ok==1.0\n" + bad_line)
        try:
            B.read_pins(bp)
            refused = False
        except ValueError as e:
            refused = "bad.txt:2" in str(e)
        check("3.2 незакреплённая строка %r — отказ с именем файла и номером строки" % bad_line.strip(), refused)
    real = B.read_pins(os.path.join(REPO, "requirements-build.txt"))
    #  Число пакетов не закреплено: добавить или убрать инструмент сборки — не ошибка. Важно, что
    #  сборка сервера ставит ВСЕ пакеты программы теми же версиями и сам PyInstaller.
    differ = sorted("%s: %s / %s" % (n, v, real.get(n)) for n, v in srv.items() if real.get(n) != v)
    check("3.3 настоящий requirements-build.txt: все пакеты программы теми же версиями + PyInstaller (%d)"
          % len(real), srv and not differ and "pyinstaller" in real, differ or sorted(real))

    # ════════════════════════════════════════════════════════════════════════
    section("4. build_release.env_mismatch")
    pins = {"fastapi": "0.141.1", "pyyaml": "6.0.3"}
    check("4.1 всё совпало (имена в другом написании, лишние numpy и pip) — расхождений нет",
          B.env_mismatch(pins, ["FastAPI==0.141.1", "PyYAML==6.0.3", "numpy==2.5.3", "pip==26.2.1"]) == [])
    r = B.env_mismatch(pins, ["fastapi==0.142.0", "PyYAML==6.0.3"])
    check("4.2 другая версия — названы пакет, нужная и стоящая", r == ["fastapi: нужно 0.141.1, стоит 0.142.0"], r)
    r = B.env_mismatch(pins, ["fastapi==0.141.1"])
    check("4.3 пакета нет — «стоит нет»", r == ["pyyaml: нужно 6.0.3, стоит нет"], r)

    # ════════════════════════════════════════════════════════════════════════
    section("5. build_release.check_build_env и --env-only")
    #  Закрепление строим из того, что РЕАЛЬНО стоит у этого Python, — итог не зависит от компьютера.
    dist = next(d for d in md.distributions() if d.metadata["Name"])
    name, ver = dist.metadata["Name"], dist.version
    good = os.path.join(TMP, "good.txt")
    wrong = os.path.join(TMP, "wrong.txt")
    io.open(good, "w", encoding="utf-8").write("%s==%s\n" % (name, ver))
    io.open(wrong, "w", encoding="utf-8").write("%s==%s.999\n" % (name, ver))
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            B.check_build_env([(sys.executable, good, "проба")])
        passed = True
    except SystemExit:
        passed = False
    check("5.1 окружение совпадает с закреплением — сборка идёт дальше («ok» в выводе)",
          passed and "ok" in buf.getvalue(), buf.getvalue()[-300:])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            B.check_build_env([(sys.executable, wrong, "проба")])
        stopped = False
    except SystemExit as e:
        stopped = e.code == 1
    out = buf.getvalue()
    check("5.2 расхождение — остановка с пакетом, версиями и точной командой pip install -r",
          stopped and ("%s: нужно %s.999, стоит %s" % (norm(name), ver, ver)) in out
          and ('"%s" -m pip install -r %s' % (sys.executable, wrong)) in out, out[-500:])
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            B.check_build_env([(os.path.join(TMP, "нет", "python.exe"), good, "проба")])
        stopped = False
    except SystemExit:
        stopped = True
    check("5.3 нет Python окружения — остановка, а не молчаливый пропуск", stopped, buf.getvalue()[-200:])

    vendor = os.path.join(TMP, "vendor")
    os.makedirs(vendor)
    for n in B.PREREQS:
        io.open(os.path.join(vendor, n), "wb").write(b"x")
    calls = []

    def _boom(*a, **k):
        calls.append("build")
        raise RuntimeError("сборка не должна была начаться")

    saved = (B.VENDOR, B.check_build_env, B.build_exes)
    B.VENDOR, B.build_exes = vendor, _boom
    try:
        B.check_build_env = lambda *a, **k: calls.append("env")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = B.main(["--env-only"])
        check("5.4 --env-only: версия, компоненты Windows и пакеты проверены, ничего не собиралось",
              calls == ["env"] and rc is None and "--env-only" in buf.getvalue(), (calls, buf.getvalue()[-300:]))
        calls[:] = []
        B.check_build_env = lambda *a, **k: (calls.append("env"), B.die("пакеты не совпадают (проба)"))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                B.main([])
            stopped = False
        except SystemExit:
            stopped = True
        check("5.5 обычная сборка: при расхождении пакетов остановка ДО PyInstaller",
              stopped and calls == ["env"], calls)
        calls[:] = []
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                B.main(["--skip-exe"])
        except SystemExit:
            pass
        check("5.6 и с --skip-exe пакеты сверяются (лицензии и проверка EXE читают те же окружения)",
              calls[:1] == ["env"], calls)
    finally:
        B.VENDOR, B.check_build_env, B.build_exes = saved
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 70)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILS)))
for f in FAILS:
    print("  ПРОВАЛ: " + f)
sys.exit(1 if FAILS else 0)
