# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-130 (29.09.2026) — сборщик текстов лицензий и его место в сборке выпуска.

ЧТО ЗАЩИЩАЕТ.
  1. Маркеры зависимостей: extra в ОБЕИХ формах кавычек. До 29.09.2026 сборщик искал только
     `extra == "standard"`, а у uvicorn в метаданных `extra == 'standard'` — websockets, httptools,
     watchfiles, PyYAML и python-dotenv (всё это вшито в EXE) в файл не попадали; а необязательные
     extras fastapi, наоборот, считались нужными.
  1a. Состав EXE: пакет packaging (вшит во все EXE) не прячется за папкой packaging/ проекта;
     расхождение версии пакета в EXE с установленной останавливает сборщик.
  2. Сборка файла из частей: один раз каждая пара «пакет, версия», порядок постоянный, CRLF, без
     путей компьютера; сверка (--check) краснеет на любом расхождении и называет разницу.
  3. tools/build_release.py: сверка стоит после проверки содержимого EXE и ДО установщиков, в
     репозиторий ничего не пишет, пути переопределяются переменными FM_*, опись окружения без путей.
  4. Если на этом компьютере есть собранные EXE и окружение оболочек — отслеживаемый файл
     сверяется с настоящим составом EXE (иначе SKIP с причиной).

Сети нет, EXE не собираются и не запускаются (их архив только читается).
Запуск:  python tools/test_collect_third_party_licenses.py   (0 = пройдено)
"""
import ast
import importlib.metadata as md
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.dont_write_bytecode = True
import collect_third_party_licenses as C  # noqa: E402

FAILS, PASSED, SKIPS = [], [0], []


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — " + name)
    else:
        FAILS.append(name)
        print("FAIL — " + name + (("  :: %s" % (extra,))[:400] if extra != "" else ""))


def skip(name, why):
    SKIPS.append(name)
    print("SKIP — %s: %s" % (name, why))


def section(t):
    print("\n" + "=" * 78 + "\n" + t + "\n" + "=" * 78)


section("1. Маркеры зависимостей и extras")
ENV = dict(C.marker_env(), python_version="3.14", python_full_version="3.14.7")
cases = [
    ("extra == 'standard'", {"standard"}, True),
    ('extra == "standard"', {"standard"}, True),
    ("extra == 'standard'", set(), False),
    ('extra == "all"', {"standard"}, False),
    ("sys_platform == 'win32' and extra == 'standard'", {"standard"}, True),
    ("(sys_platform != 'win32' and sys_platform != 'cygwin') and platform_python_implementation != 'PyPy' "
     "and extra == 'standard'", {"standard"}, False),
    ('python_version < "3.8"', set(), False),
    ('python_version >= "3.10"', set(), True),
    ("os_name == 'nt' or extra == 'x'", set(), True),
    ("platform_system == 'Linux'", set(), False),
    ("непонятный маркер ###", set(), True),
]
bad = [(m, e, want) for m, e, want in cases if C.marker_true(m, e, ENV) is not want]
check("1.1 маркеры: обе формы кавычек, скобки, and/or, версии Python, платформа (%d случаев)" % len(cases),
      not bad, bad)
check("1.2 требование разбирается с extras и маркером",
      C.split_requirement('uvicorn[standard, foo]>=0.30 ; extra == "x"') == ("uvicorn", {"standard", "foo"}, 'extra == "x"')
      and C.split_requirement("websockets>=10.4; extra == 'standard'")[0] == "websockets")


def installed(n):
    try:
        md.distribution(n)
        return True
    except md.PackageNotFoundError:
        return False


if installed("uvicorn") and installed("websockets"):
    names = set(C._norm(d.metadata["Name"]) for d in C.closure(["uvicorn[standard]"], ENV)[0])
    want = set(C._norm(n) for n in ("websockets", "httptools", "watchfiles", "pyyaml", "python-dotenv")
               if installed(n))
    check("1.3 uvicorn[standard] тянет свои extras: %s" % ", ".join(sorted(want)), want <= names,
          sorted(want - names))
    plain = set(C._norm(d.metadata["Name"]) for d in C.closure(["uvicorn"], ENV)[0])
    check("1.4 uvicorn без [standard] extras не тянет", "websockets" not in plain and "httptools" not in plain,
          sorted(plain))
else:
    skip("1.3-1.4 extras uvicorn на настоящем окружении", "uvicorn не установлен в этом Python")
if installed("fastapi"):
    _d, missing = C.closure(["fastapi"], ENV)
    check("1.5 необязательные extras fastapi (fastapi-cli, httpx, jinja2…) не считаются нужными",
          not [m for m in missing if m in ("fastapi-cli", "httpx", "jinja2", "email-validator", "itsdangerous")],
          missing)
else:
    skip("1.5 extras fastapi", "fastapi не установлен")

section("1a. Свои имена проекта и сторонние пакеты в EXE")
own = C._repo_tops({"packaging": ["packaging"], "app": ["someone-else"]})
check("1a.1 папка packaging/ проекта (не пакет Python) не прячет одноимённый пакет PyPI",
      os.path.isdir(os.path.join(REPO, "packaging")) and "packaging" not in own, sorted(own))
check("1a.2 свои модули и папки остаются своими: server, app (пакет Python), web, printer_covers",
      {"server", "app", "web", "printer_covers"} <= own, sorted(own))
_real_exe_contents = C.exe_contents
try:
    if installed("packaging"):
        C.exe_contents = lambda exe: ({"app", "server", "web", "packaging", "__pycache__"}, [])
        got = [C._norm(d.metadata["Name"]) for d in C.dists_in_exes(["fake.exe"])]
        check("1a.3 пакет packaging внутри EXE попадает в состав, свои имена — нет", got == ["packaging"], got)
        ver = md.version("packaging")
        C.exe_contents = lambda exe: (set(), [("packaging", ver + ".999")])
        try:
            C.dists_in_exes(["fake.exe"])
            stopped = ""
        except SystemExit as e:
            stopped = str(e.code or "")
        check("1a.4 версия пакета в EXE не совпадает с установленной — сборщик останавливается",
              "собран не этим окружением" in stopped and "packaging" in stopped, stopped)
        C.exe_contents = lambda exe: (set(), [("packaging", ver)])
        got = [C._norm(d.metadata["Name"]) for d in C.dists_in_exes(["fake.exe"])]
        check("1a.5 та же версия — пакет в составе, остановки нет", got == ["packaging"], got)
    else:
        skip("1a.3-1a.5 состав EXE на подставном архиве", "пакет packaging не установлен в этом Python")
finally:
    C.exe_contents = _real_exe_contents

section("2. Сборка файла из частей и сверка")


def pkg(name, ver, text="MIT License text"):
    return {"name": name, "version": ver, "license": "MIT", "home": "https://example.org/" + name,
            "texts": [["licenses/LICENSE", text]] if text else []}


P1 = {"python": "3.14.7", "source": "exe", "missing": [],
      "packages": [pkg("zeta", "1.0"), pkg("Alpha_Pkg", "2.0"), pkg("cryptography", "50.0.1")]}
P2 = {"python": "3.14.7", "source": "exe", "missing": [],
      "packages": [pkg("Alpha_Pkg", "2.0"), pkg("cryptography", "49.0.0"), pkg("notext", "0.1", "")]}
TEXT = C.assemble([P1, P2])
heads = C._headings(TEXT)
pk = heads[len(C.IN_REPO):] if len(heads) > len(C.IN_REPO) else heads
check("2.1 один раз каждая пара «пакет, версия»; разные версии одного пакета — обе",
      [h.split(" — ")[0] for h in pk] == ["Alpha_Pkg 2.0", "cryptography 49.0.0", "cryptography 50.0.1",
                                           "notext 0.1", "zeta 1.0"], pk)
check("2.2 текст не зависит от порядка частей", C.assemble([P2, P1]) == TEXT)
check("2.3 пакет без текста лицензии — ссылка на его описание, а не пустое место",
      "(текст лицензии в пакете не найден; см. https://example.org/notext)" in TEXT)
check("2.4 шапка: двуязычная, своя лицензия MPL, откуда файл",
      TEXT.startswith(C.HEADER) and "Mozilla Public License 2.0" in C.HEADER)
tmp = tempfile.mkdtemp(prefix="fm_tpl_")
parts = []
for i, p in enumerate((P1, P2)):
    fp = os.path.join(tmp, "p%d.json" % i)
    json.dump(p, io.open(fp, "w", encoding="utf-8"), ensure_ascii=False)
    parts.append(fp)
out = os.path.join(tmp, "TPL.txt")
rc_out = C.main(["--assemble"] + parts + ["--out", out])
raw = open(out, "rb").read()
check("2.5 файл пишется в CRLF и UTF-8", rc_out == 0 and raw.count(b"\n") == raw.count(b"\r\n") > 10)
check("2.6 сверка с только что собранным — совпадает (0)", C.main(["--assemble"] + parts + ["--check", out]) == 0)
P1b = json.loads(json.dumps(P1))
P1b["packages"][0]["version"] = "1.1"
json.dump(P1b, io.open(parts[0], "w", encoding="utf-8"), ensure_ascii=False)
check("2.7 сменилась версия пакета — сверка красная (1)", C.main(["--assemble"] + parts + ["--check", out]) == 1)
P1b["packages"][0]["version"] = "1.0"
P1b["packages"][0]["texts"][0][1] = "Другой текст"
json.dump(P1b, io.open(parts[0], "w", encoding="utf-8"), ensure_ascii=False)
check("2.8 сменился только текст лицензии — тоже красная", C.main(["--assemble"] + parts + ["--check", out]) == 1)
check("2.9 файла нет — красная", C.main(["--assemble"] + parts + ["--check", os.path.join(tmp, "нет.txt")]) == 1)

section("3. Место в сборке выпуска (tools/build_release.py)")
BR_PATH = os.path.join(REPO, "tools", "build_release.py")
BR = io.open(BR_PATH, encoding="utf-8").read()
T = ast.parse(BR)
main_fn = next(n for n in T.body if isinstance(n, ast.FunctionDef) and n.name == "main")
order = [n.func.id for n in ast.walk(main_fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]


def pos(name):
    return order.index(name) if name in order else -1


check("3.1 сверка лицензий: после проверки содержимого EXE и до установщиков",
      0 <= pos("proof") < pos("licenses_check") < pos("build_installers"), order)
lc = next(n for n in T.body if isinstance(n, ast.FunctionDef) and n.name == "licenses_check")
LC = ast.get_source_segment(BR, lc)
check("3.2 части собираются своими интерпретаторами (сервер — sys.executable, оболочки — BUILDENV_PY)",
      re.search(r'run\(\[sys\.executable, COLLECTOR, "--from-exe", os\.path\.join\(dist, SERVER_EXE\)', LC)
      and re.search(r'run\(\[BUILDENV_PY, COLLECTOR, "--from-exe", os\.path\.join\(dist, DESKTOP_EXE\)', LC)
      and "CLIENT_EXE" in LC)
check("3.3 сборка файл только сверяет (--check), в репозиторий не пишет; при расхождении — остановка",
      '"--check", LICENSES_FILE' in LC and '"--out"' not in LC and "die(" in LC
      and "licenses_update_command(srv, shl)" in LC)
check("3.4 сверяется именно тот файл, который ставит установщик",
      'LICENSES_FILE = os.path.join("packaging", "installer", "licenses", "THIRD_PARTY_LICENSES.txt")' in BR
      and 'Source: "packaging\\installer\\licenses\\*.txt"; DestDir: "{app}\\licenses"'
      in io.open(os.path.join(REPO, "3diwell-setup.iss"), encoding="utf-8-sig").read())
check("3.5 опись окружения входит в SHA256SUMS",
      "[m[3] for m in modules] + [env_file])" in BR and "env_file = write_build_environment(rel, ver)" in BR)
env = dict(os.environ, FM_BUILD_ROOT=os.path.join(tmp, "root"), PYTHONDONTWRITEBYTECODE="1")
env.pop("FM_VENDOR_DIR", None)
env.pop("FM_SHELL_PYTHON", None)
code = ("import sys, json; sys.path.insert(0, %r); import build_release as B; "
        "print(json.dumps([B.BUILD_ROOT, B.VENDOR, B.BUILDENV_PY]))" % os.path.join(REPO, "tools"))
got = json.loads(subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, timeout=60).stdout)
root = os.path.join(tmp, "root")
check("3.6 FM_BUILD_ROOT переносит сборочный корень, остальное — от него",
      got == [root, os.path.join(root, "vendor"), os.path.join(root, "buildenv", "Scripts", "python.exe")], got)
env.update(FM_VENDOR_DIR=os.path.join(tmp, "v"), FM_SHELL_PYTHON=os.path.join(tmp, "py.exe"))
env.pop("FM_BUILD_ROOT")
got = json.loads(subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, timeout=60).stdout)
check("3.7 без переменных — прежний C:\\3DIWELL_Builds; FM_VENDOR_DIR и FM_SHELL_PYTHON задаются отдельно",
      got == [r"C:\3DIWELL_Builds", os.path.join(tmp, "v"), os.path.join(tmp, "py.exe")], got)
sys.path.insert(0, os.path.join(REPO, "tools"))
import build_release as B  # noqa: E402
etxt = B.build_environment_text("3.0", ("3.14.7", ["fastapi==0.141.1", "uvicorn==0.52.4"]),
                                ("3.14.7", ["pywebview==6.2.1"]), "6.7.3",
                                [("ndp48-x86-x64-allos-enu.exe", "ab" * 32)], "cd" * 32)
check("3.8 опись окружения: версии и суммы есть, путей компьютера нет",
      "fastapi==0.141.1" in etxt and "pywebview==6.2.1" in etxt and "Inno Setup: 6.7.3" in etxt
      and "ab" * 32 in etxt and "cd" * 32 in etxt and not re.search(r"[A-Za-z]:\\", etxt))
check("3.9 команда обновления называет сборщик, обе части и отслеживаемый файл",
      B.licenses_update_command("s.json", "h.json")
      == 'python %s --assemble "s.json" "h.json" --out %s' % (B.COLLECTOR, B.LICENSES_FILE))

section("4. Отслеживаемый файл против настоящих EXE этого компьютера")
TRACKED = os.path.join(REPO, C.TRACKED)
#  25.10.2026: версия и папка сборки — тем же разбором, что у сборщика («Beta 3.71» -> Beta_3.71\dist).
ver = B.app_version_label()
dist = B.staging_dist(ver)
exes = [os.path.join(dist, n) for n in (B.SERVER_EXE, B.DESKTOP_EXE, B.CLIENT_EXE)]
try:
    import PyInstaller  # noqa: F401
    have_pi = True
except Exception:
    have_pi = False
if not (have_pi and all(os.path.isfile(e) for e in exes) and os.path.isfile(B.BUILDENV_PY)):
    skip("4.1 сверка с настоящими EXE", "нет собранных EXE %s, PyInstaller или окружения оболочек" % ver)
else:
    sp, hp = os.path.join(tmp, "srv.json"), os.path.join(tmp, "shl.json")
    r1 = subprocess.run([sys.executable, os.path.join(REPO, "tools", "collect_third_party_licenses.py"),
                         "--from-exe", exes[0], "--part-out", sp], capture_output=True, timeout=600)
    r2 = subprocess.run([B.BUILDENV_PY, os.path.join(REPO, "tools", "collect_third_party_licenses.py"),
                         "--from-exe", exes[1], exes[2], "--part-out", hp], capture_output=True, timeout=600)
    msg = (r1.stdout + r1.stderr + r2.stdout + r2.stderr).decode("utf-8", "replace")
    if r1.returncode or r2.returncode:
        if "собран не этим окружением" in msg:
            skip("4.1 сверка с настоящими EXE", "EXE в staging собраны другими версиями пакетов — нужна пересборка")
        else:
            check("4.1 состав EXE читается", False, msg[-300:])
    else:
        rc = subprocess.run([sys.executable, os.path.join(REPO, "tools", "collect_third_party_licenses.py"),
                             "--assemble", sp, hp, "--check", TRACKED], capture_output=True, timeout=120)
        check("4.1 THIRD_PARTY_LICENSES.txt совпадает с составом всех трёх EXE %s" % ver,
              rc.returncode == 0, rc.stdout.decode("utf-8", "replace")[-400:])

shutil.rmtree(tmp, ignore_errors=True)
print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d SKIP=%d" % (PASSED[0], len(FAILS), len(SKIPS)))
for f in FAILS:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILS else 0)
