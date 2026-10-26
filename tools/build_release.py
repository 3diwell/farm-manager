# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Сборка выпуска 3DIWELL Farm Manager одной командой (3.0, решение владельца 12.09.2026).

    python tools/build_release.py              # всё: EXE -> проверки -> установщики -> папка выпуска
    python tools/build_release.py --skip-exe   # EXE уже собраны в staging: только проверки и установщики
    python tools/build_release.py --no-stand   # без стенда «папка без права записи» (только для отладки)
    python tools/build_release.py --env-only   # только шаги 1-2: версия, компоненты Windows, пакеты сборки

ЗАЧЕМ ОДНОЙ КОМАНДОЙ. Владелец будет присылать правки, и выпуск придётся пересобирать не раз.
Каждый шаг ниже раньше делался руками и по памяти, а память подводит: 02.09.2026 сборка 2.939
прошла проверку «код внутри EXE» и не запустилась у владельца — стенда «папка без права
записи» тогда не было. Здесь все шаги закреплены, идут в одном порядке и красный шаг
останавливает всё.

ШАГИ (каждый печатает свой итог):
 1. версия читается из server.py (APP_VERSION) — единственный источник номера;
 2. установщики компонентов Windows лежат в C:\\3DIWELL_Builds\\vendor: WebView2 Runtime и
    .NET Framework 4.8 (см. tools/installer/prereqs.iss: где взять и как проверить подпись).
    R-149 (16.10.2026): пакеты обоих сборочных Python совпадают с закреплёнными версиями —
    сервер с requirements-build.txt, окно и клиент (buildenv) с requirements-desktop-shell.txt;
    расхождение останавливает сборку ДО PyInstaller с точной командой pip install;
 3. три EXE: сервер — системным Python (3diwell.spec), оболочки — интерпретатором buildenv
    (desktop_shell.spec). Staging C:\\3DIWELL_Builds\\<версия>\\dist (Beta_3.71, Alpha_3.0), рабочие папки
    PyInstaller — снаружи репозитория (контракт чистого репозитория, AGENTS.md §14);
 4. рядом с EXE кладётся удостоверение e2e-supported.txt — по нему
    tools/test_packaged_restart_end_to_end.py соглашается гонять именно эту сборку;
 5. packaged proof: заглядываем ВНУТРЬ архива каждого EXE (а не в его размер): версия в коде
    сервера та же, файлы разработки (.md/.bat/.mjs) внутрь не попали, интерфейс, обложки,
    ffmpeg и VCRUNTIME на месте; у оболочек — WebView2 и Python.Runtime. У всех трёх EXE
    номер в свойствах файла равен APP_VERSION (R-149; у установщиков — после шага 7).
    Затем тексты лицензий (R-130): tools/collect_third_party_licenses.py читает состав каждого
    EXE (тем интерпретатором, которым EXE собран) и сверяет с отслеживаемым файлом
    packaging/installer/licenses/THIRD_PARTY_LICENSES.txt — его ставит установщик в папку
    licenses. Файл устарел — выпуск останавливается с точной командой обновления; сама сборка
    в репозиторий ничего не пишет;
 6. стенд «папка без права записи» (docs/validation/release.md §4): сервер-EXE 20 секунд
    живёт в папке, куда писать нельзя, — как в Program Files у пользователя. Зелёный только
    если процесс дожил, в журнале есть «lifespan: YIELD» и нет PermissionError;
 7. оба установщика Inno Setup с /DReleaseBuild: без компонентов Windows компиляция
    останавливается — выпуск обязан ставиться на чистую Windows без интернета;
 8. ZIP всех модулей пересобираются (tools/build_*_zip.py) и кладутся в папку выпуска
    рядом с установщиком;
 9. ПРОЧТИ МЕНЯ.txt для пользователя, BUILD_ENVIRONMENT.txt (чем собрано: версии Python и
    пакетов обоих окружений, Inno Setup, суммы компонентов Windows и ffmpeg — без путей этого
    компьютера) и SHA256SUMS.txt.

ПАПКА ВЫПУСКА: C:\\3DIWELL_Builds\\Release_<версия>\\ — ровно то, что отдаётся пользователю.
Полный прогон проверок (tools/release_gate.py) этот скрипт НЕ запускает: он по слову владельца.
Другой сборочный корень, папку компонентов Windows и Python оболочек можно задать переменными
FM_BUILD_ROOT, FM_VENDOR_DIR, FM_SHELL_PYTHON (без них — прежние пути, см. docs/dev/building.md).
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#  R-130 (29.09.2026): пути можно переопределить переменными окружения — для сборки на другом
#  компьютере. Без переменных всё как прежде.
BUILD_ROOT = os.environ.get("FM_BUILD_ROOT") or r"C:\3DIWELL_Builds"
VENDOR = os.environ.get("FM_VENDOR_DIR") or os.path.join(BUILD_ROOT, "vendor")
BUILDENV_PY = os.environ.get("FM_SHELL_PYTHON") or os.path.join(BUILD_ROOT, "buildenv", "Scripts", "python.exe")

SERVER_EXE = "3DIWELL Farm Manager.exe"
DESKTOP_EXE = "3DIWELL Farm Manager Desktop.exe"
CLIENT_EXE = "3DIWELL Farm Manager Client.exe"
PREREQS = ("MicrosoftEdgeWebView2RuntimeInstallerX64.exe", "ndp48-x86-x64-allos-enu.exe")
CERT_NAME = "e2e-supported.txt"
CLIENT_SUBDIR = "Клиент для другого компьютера"
README_NAME = "ПРОЧТИ МЕНЯ.txt"
SUMS_NAME = "SHA256SUMS.txt"
ENV_NAME = "BUILD_ENVIRONMENT.txt"
LICENSES_FILE = os.path.join("packaging", "installer", "licenses", "THIRD_PARTY_LICENSES.txt")
COLLECTOR = os.path.join("tools", "collect_third_party_licenses.py")
DEV_ONLY_EXT = (".md", ".bat", ".mjs")
STAND_SECONDS = 20
#  R-149 (16.10.2026): закреплённые версии пакетов сборки. requirements-build.txt включает
#  requirements.txt (пакеты программы) и добавляет PyInstaller; окно и клиент — своё окружение.
REQ_BUILD = "requirements-build.txt"
REQ_SHELL = "requirements-desktop-shell.txt"
VERSION_INFO_HELPER = os.path.join(REPO, "tools", "build_version_info.py")

#  Модули: (сборщик, имя ZIP, папка исходников) — имя ZIP задаёт сам сборщик, здесь оно
#  повторено, чтобы в папку выпуска попали ровно актуальные файлы и ничего лишнего: ZIP модуля,
#  которого в списке нет (например, удалённой «Себестоимости печати»), из папки выпуска убирается.
#  12.09.2026: «Себестоимость печати» заменена «Расчётом заказа» (тот же id cost), добавлено
#  «Оформление и темы» — оба по слову владельца.
MODULES = (
    ("build_inventory_zip.py", "3diwell-module-inventory.zip", "inventory"),
    ("build_cost_zip.py", "3diwell-module-order-calculation.zip", "cost"),
    ("build_quality_zip.py", "3diwell-module-quality.zip", "quality"),
    ("build_camera_wall_zip.py", "3diwell-module-camera-wall.zip", "camera_wall"),
    ("build_messengers_zip.py", "3diwell-module-messengers.zip", "messengers"),
    ("build_appearance_zip.py", "3diwell-module-appearance.zip", "appearance"),
)
#  25.10.2026 (Beta 3.71, слово владельца): платные модули идут к пользователям только ПЛАТНОЙ сборкой — подписанным
#  пакетом со своей копией SDK и ключей (без лицензии — только просмотр). Обычный архив без подписи работает
#  бесплатно, поэтому в папку выпуска он не кладётся; для своей фермы он остаётся в C:DIWELL\modules.
#  Подпись — рабочим ключом пакетов: путь к закрытому ключу (вне проекта, имя файла = key_id.pem) и к файлу
#  с его паролем дают переменные окружения. Без них выпуск не собирается (или --unsigned-paid — внутренняя
#  сборка для своей фермы, не для пользователей).
PAID_MODULES = ("inventory", "cost")
ENV_SIGN_KEY = "FM_PACKAGE_SIGN_KEY"
ENV_SIGN_PASSFILE = "FM_PACKAGE_SIGN_PASSFILE"


def say(msg=""):
    print(msg, flush=True)


def die(msg):
    say("")
    say("ОШИБКА: %s" % msg)
    sys.exit(1)


def run(cmd, cwd=REPO, env=None):
    say("  > " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if r.returncode != 0:
        die("команда завершилась с кодом %d: %s" % (r.returncode, cmd[0]))


#  25.10.2026: выпуск называется «Alpha N.M» или «Beta N.M» (с Beta 3.71). Номер — пара чисел, в
#  установщиках и свойствах файлов он без префикса; полная версия нужна там, где её видит человек
#  или сверяет программа: удостоверение сборки, проверка кода внутри EXE, папка staging.
_APP_VERSION_RE = re.compile(r'^APP_VERSION\s*=\s*"((?:Alpha|Beta)\s+(\d+\.\d+))"', re.M)


def _app_version_match():
    src = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
    m = _APP_VERSION_RE.search(src)
    if not m:
        die("APP_VERSION не найден в server.py")
    return m


def app_version():
    """Номер без префикса: «3.71»."""
    return _app_version_match().group(2)


def app_version_label():
    """Полная версия, как в APP_VERSION: «Beta 3.71»."""
    return " ".join(_app_version_match().group(1).split())


def staging_dist(label):
    """Папка собранных EXE версии: C:\\3DIWELL_Builds\\Beta_3.71\\dist (у Alpha 3.0 — Alpha_3.0)."""
    return os.path.join(BUILD_ROOT, label.replace(" ", "_"), "dist")


def find_iscc():
    cands = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
             r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
             r"C:\Program Files\Inno Setup 6\ISCC.exe"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    w = shutil.which("ISCC")
    if w:
        return w
    die("ISCC.exe (Inno Setup 6) не найден — см. .ai/CURRENT_STATE.md §1, где он лежит")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mb(path):
    return os.path.getsize(path) / (1024.0 * 1024.0)


# ── 2. пакеты сборки = закреплённые версии (R-149) ────────────────────────────

def norm_name(name):
    """Имя пакета по правилу PEP 503: «PyYAML», «typing_extensions» и «Typing.Extensions» — одно."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def read_pins(path, _seen=None):
    """{нормализованное имя: версия} из файла закреплений.

    Строка — «имя==версия» (необязательные [extras] отбрасываются) или «-r файл»: тот читается
    тоже, путь — от папки текущего файла. Комментарии (# …) и пустые строки пропускаются.
    Любая другая строка — ValueError: незакреплённый пакет здесь означал бы «возьми свежий».
    """
    path = os.path.abspath(path)
    seen = _seen if _seen is not None else set()
    if path in seen:
        return {}
    seen.add(path)
    pins = {}
    with io.open(path, encoding="utf-8-sig") as f:
        for n, raw in enumerate(f, 1):
            line = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()
            if not line:
                continue
            inc = re.match(r"^-r\s+(\S+)$", line)
            if inc:
                pins.update(read_pins(os.path.join(os.path.dirname(path), inc.group(1)), seen))
                continue
            m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([0-9][^\s;,]*)$", line)
            if not m:
                raise ValueError("%s:%d: ожидается «имя==версия» или «-r файл», а не %r"
                                 % (os.path.basename(path), n, line))
            pins[norm_name(m.group(1))] = m.group(2)
    return pins


def env_mismatch(pins, installed):
    """Расхождения окружения с закреплёнными версиями -> ["имя: нужно X, стоит Y" | "…, стоит: нет"].

    installed — список «Имя==версия», как его отдаёт _py_packages. Лишние установленные пакеты
    (numpy, pip) не мешают: сборке важно только, чтобы закреплённые стояли ровно своей версии.
    """
    have = {}
    for item in installed:
        name, _, ver = item.partition("==")
        have[norm_name(name)] = ver.strip()
    out = []
    for name in sorted(pins):
        got = have.get(name)
        if got != pins[name]:
            out.append("%s: нужно %s, стоит %s" % (name, pins[name], got if got else "нет"))
    return out


def pip_install_command(py, req):
    """Точная команда, которой владелец приводит окружение к закреплённым версиям."""
    return '"%s" -m pip install -r %s' % (py, req)


def check_build_env(envs=None):
    """[2/9] Оба сборочных Python держат ровно закреплённые версии — иначе остановка ДО сборки.

    envs — [(интерпретатор, файл закреплений, подпись)]; по умолчанию сервер (этот Python)
    против requirements-build.txt и оболочки (buildenv) против requirements-desktop-shell.txt.
    Сам ничего не ставит: только читает списки пакетов и печатает команду, если нужно.
    """
    envs = envs or ((sys.executable, REQ_BUILD, "сервер"),
                    (BUILDENV_PY, REQ_SHELL, "окно и клиент"))
    say("[2/9] пакеты сборки против закреплённых версий (%s)"
        % ", ".join(req for _py, req, _tag in envs))
    for py, req, tag in envs:
        if not os.path.isfile(py):
            die("нет Python для части «%s»: %s (см. docs/dev/building.md)" % (tag, py))
        try:
            pins = read_pins(os.path.join(REPO, req))
        except (OSError, ValueError) as e:
            die("файл закреплений %s не читается: %s" % (req, e))
        pyver, installed = _py_packages(py)
        if not installed:
            die("не удалось прочитать список пакетов %s (Python %s)" % (py, pyver))
        bad = env_mismatch(pins, installed)
        if bad:
            die("пакеты части «%s» не совпадают с %s:\n  %s\n"
                "Поставьте закреплённые версии командой из папки проекта:\n  %s\n"
                "и повторите сборку." % (tag, req, "\n  ".join(bad), pip_install_command(py, req)))
        say("  ok  %s: %d пакетов ровно как в %s (Python %s)" % (tag, len(pins), req, pyver))


# ── номер версии в свойствах EXE (R-149) ─────────────────────────────────────

def _version_info():
    """tools/build_version_info.py по пути — его же грузит 3diwell.spec."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fm_build_version_info", VERSION_INFO_HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def version_quad(ver):
    """«3.0» -> (3, 0, 0, 0): номер читается парой «старшая.младшая» (CLAUDE.md §8)."""
    major, minor = (int(x) for x in ver.split("."))
    return (major, minor, 0, 0)


def exe_version_problems(paths, ver):
    """Файлы, у которых двоичная версия в свойствах не равна APP_VERSION -> ["имя: стоит …"]."""
    want = version_quad(ver)
    vi = _version_info()
    out = []
    for p in paths:
        try:
            got, _strings = vi.read_exe_version(p)
        except Exception as e:
            got = "не читается (%s)" % type(e).__name__
        if got != want:
            out.append("%s: стоит %s, нужно %s" % (
                os.path.basename(p), ".".join(map(str, got)) if isinstance(got, tuple) else (got or "нет"),
                ".".join(map(str, want))))
    return out


# ── 3. EXE ────────────────────────────────────────────────────────────────────

def build_exes(dist, work):
    say("[3/9] PyInstaller: сервер (системный Python) и оболочки (buildenv)")
    if not os.path.isfile(BUILDENV_PY):
        die("нет сборочного окружения оболочек: %s (см. docs/validation/release.md §3)" % BUILDENV_PY)
    os.makedirs(dist, exist_ok=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", dist, "--workpath", os.path.join(work, "server"), "3diwell.spec"])
    run([BUILDENV_PY, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", dist, "--workpath", os.path.join(work, "shell"), "desktop_shell.spec"])
    for name in (SERVER_EXE, DESKTOP_EXE, CLIENT_EXE):
        p = os.path.join(dist, name)
        if not os.path.isfile(p):
            die("после сборки нет файла %s" % p)
        say("  собрано: %s (%.1f МБ)" % (name, mb(p)))


# ── 5. packaged proof ─────────────────────────────────────────────────────────

def _archive(exe):
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except Exception as e:
        die("PyInstaller не импортируется, packaged proof невозможен: %s" % e)
    try:
        return CArchiveReader(exe)
    except Exception as e:
        die("архив внутри %s не читается: %s" % (os.path.basename(exe), e))


def _pyz_modules(arc):
    for name in arc.toc:
        if name.lower().endswith(".pyz"):
            try:
                return set(arc.open_embedded_archive(name).toc.keys())
            except Exception as e:
                die("PYZ внутри EXE не читается: %s" % e)
    return set()


def _dev_files(names):
    """Наши файлы разработки внутри EXE: инструкция по обучению, ревизии текстов, проверялки.
    Смотрим только СВОИ пути (web/ и корень сборки): у сторонних пакетов в *.dist-info лежат
    их лицензии LICENSE.md — это не разработка, и убирать их нельзя."""
    return [n for n in names
            if (n.startswith("web/") or "/" not in n) and n.lower().endswith(DEV_ONLY_EXT)]


def proof(dist, ver, label=None):
    say("[5/9] packaged proof: смотрим внутрь каждого EXE")
    label = label or app_version_label()
    bad = []

    def need(cond, what):
        (say if cond else bad.append)("  %s %s" % ("ok " if cond else "НЕТ", what))

    # сервер
    arc = _archive(os.path.join(dist, SERVER_EXE))
    names = [n.replace("\\", "/") for n in arc.toc]
    low = [n.lower() for n in names]
    script = arc.extract("server") if "server" in arc.toc else b""
    need(label.encode("utf-8") in script, "сервер: в коде APP_VERSION = %s" % label)
    dev = _dev_files(names)
    need(not dev, "сервер: файлов разработки (web/*.md, .bat, .mjs) внутри нет%s" % ("" if not dev else ": " + ", ".join(dev[:5])))
    need("web/index.html" in names and "web/app.js" in names and "web/app.css" in names, "сервер: интерфейс (web/) внутри")
    need("web/ui3/ui3.css" in names, "сервер: оформление 3.0 внутри")
    need(any(n.startswith("printer_covers/") for n in names), "сервер: обложки принтеров внутри")
    need("ffmpeg.exe" in names, "сервер: ffmpeg.exe внутри (камеры Bambu)")
    need(all(n in names for n in ("web/design/fonts.css", "web/design/fonts/3diwell-wide-j.woff2",
                                  "web/design/fonts/3diwell-wide-j-bold.woff2",
                                  "web/design/fonts/OFL-Jura.txt")),
         "сервер: шрифт интерфейса по умолчанию 3DIWELL Wide J и его лицензия внутри")
    need("sony_sketch.ttf" not in low and b"Sony Sketch Custom" not in script,
         "сервер: прежнего шрифта Sony Sketch внутри нет")
    need("vcruntime140.dll" in low, "сервер: VCRUNTIME140.dll внутри (без него EXE не стартует на чистой Windows)")
    mods = _pyz_modules(arc)
    need("app.route_policy_registry" in mods and "fastapi" in mods and "uvicorn" in mods, "сервер: пакеты app/*, fastapi, uvicorn в PYZ")
    say("  сервер: %d файлов в архиве, %d модулей в PYZ" % (len(names), len(mods)))
    # оболочки
    for exe in (DESKTOP_EXE, CLIENT_EXE):
        arc = _archive(os.path.join(dist, exe))
        names = [n.replace("\\", "/") for n in arc.toc]
        low = [n.lower() for n in names]
        mods = _pyz_modules(arc)
        tag = "окно" if exe == DESKTOP_EXE else "клиент"
        need("app.desktop_shell" in mods, "%s: app.desktop_shell в PYZ" % tag)
        need(any("webview2" in n for n in low), "%s: библиотеки WebView2 внутри" % tag)
        need(any(n.endswith("python.runtime.dll") for n in low), "%s: Python.Runtime.dll (pythonnet) внутри" % tag)
        need("vcruntime140.dll" in low, "%s: VCRUNTIME140.dll внутри" % tag)
        dev = _dev_files(names)
        need(not dev, "%s: файлов разработки внутри нет%s" % (tag, "" if not dev else ": " + ", ".join(dev[:5])))
        need(not any(m in mods for m in ("fastapi", "uvicorn", "paho")), "%s: серверных пакетов внутри нет (оболочка тонкая)" % tag)
    #  R-149: номер в свойствах файла. У сервера его даёт 3diwell.spec из APP_VERSION, у окна и
    #  клиента — desktop_shell_version_*.txt: здесь же ловится, если те файлы отстали от номера.
    vbad = exe_version_problems([os.path.join(dist, n) for n in (SERVER_EXE, DESKTOP_EXE, CLIENT_EXE)], ver)
    need(not vbad, "все три EXE: версия в свойствах файла = %s%s"
         % (".".join(map(str, version_quad(ver))), "" if not vbad else " (" + "; ".join(vbad) + ")"))
    if bad:
        die("packaged proof не пройден:\n" + "\n".join(bad))


# ── 5. тексты лицензий сторонних пакетов (R-130) ──────────────────────────────

def licenses_update_command(server_part, shell_part):
    """Команда, которой владелец обновляет отслеживаемый файл лицензий после смены пакетов."""
    return ('python %s --assemble "%s" "%s" --out %s'
            % (COLLECTOR, server_part, shell_part, LICENSES_FILE))


def licenses_check(dist, work):
    say("[5/9] тексты лицензий: %s против состава EXE" % LICENSES_FILE)
    if not os.path.isfile(BUILDENV_PY):
        die("нет сборочного окружения оболочек: %s (см. docs/dev/building.md)" % BUILDENV_PY)
    os.makedirs(work, exist_ok=True)
    srv = os.path.join(work, "licenses_server.json")
    shl = os.path.join(work, "licenses_shell.json")
    #  Каждая часть — тем интерпретатором, которым собран EXE: пакеты сопоставляются с ЕГО
    #  установленными версиями, а расхождение версий сборщик лицензий считает ошибкой.
    run([sys.executable, COLLECTOR, "--from-exe", os.path.join(dist, SERVER_EXE), "--part-out", srv])
    run([BUILDENV_PY, COLLECTOR, "--from-exe", os.path.join(dist, DESKTOP_EXE),
         os.path.join(dist, CLIENT_EXE), "--part-out", shl])
    r = subprocess.run([sys.executable, COLLECTOR, "--assemble", srv, shl, "--check", LICENSES_FILE], cwd=REPO)
    if r.returncode != 0:
        die("файл лицензий не совпадает с составом собранных EXE (сменились пакеты или их версии).\n"
            "Обновите его командой из папки проекта:\n  %s\n"
            "затем зафиксируйте изменение (git commit) и повторите сборку: python tools/build_release.py --skip-exe"
            % licenses_update_command(srv, shl))
    say("  ok  файл лицензий совпадает с составом всех трёх EXE")


# ── 6. стенд «папка без права записи» ─────────────────────────────────────────

def _icacls(path, *args):
    return subprocess.run(["icacls", path] + list(args), capture_output=True)


def stand_no_write(dist, work):
    say("[6/9] стенд: сервер-EXE %d с в папке БЕЗ права записи (как Program Files)" % STAND_SECONDS)
    user = os.environ.get("USERNAME") or ""
    if not user:
        die("USERNAME не определён — стенд не может задать запрет")
    root = os.path.join(work, "stand")
    app = os.path.join(root, "app")
    if os.path.isdir(app):
        _icacls(app, "/remove:d", user)          # хвост прошлого прогона, если тот упал посреди
    if os.path.isdir(root):
        shutil.rmtree(root)
    data, tmp, out = (os.path.join(root, d) for d in ("data", "tmp", "out"))
    for d in (app, data, tmp, out):
        os.makedirs(d)
    shutil.copy2(os.path.join(dist, SERVER_EXE), app)
    r = _icacls(app, "/deny", "%s:(WD,AD)" % user)
    if r.returncode != 0:
        die("icacls не смог поставить запрет: %s" % r.stderr.decode("utf-8", "replace"))
    try:
        os.makedirs(os.path.join(app, "probe"))
        _icacls(app, "/remove:d", user)
        die("запрет записи не сработал: внутри папки удалось создать подпапку — стенд ничего не доказывает")
    except PermissionError:
        say("  ok  запрет записи действует (создать подпапку внутри нельзя)")
    env = dict(os.environ)
    env.update({"LOCALAPPDATA": data, "APPDATA": data, "TEMP": tmp, "TMP": tmp})
    so = open(os.path.join(out, "stdout.txt"), "wb")
    se = open(os.path.join(out, "stderr.txt"), "wb")
    #  Без аргументов — как у пользователя ярлыком. --no-browser сервер и так знает и браузер
    #  никогда не открывает сам; лишних флагов не передаём (release.md §4).
    p = subprocess.Popen([os.path.join(app, SERVER_EXE)], cwd=app, env=env, stdout=so, stderr=se,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(STAND_SECONDS):
            time.sleep(1)
            if p.poll() is not None:
                break
        alive = p.poll() is None
    finally:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        time.sleep(1.5)
        so.close()
        se.close()
        _icacls(app, "/remove:d", user)
    logs = ""
    for lp in glob.glob(os.path.join(data, "**", "logs", "*.log"), recursive=True):
        logs += io.open(lp, encoding="utf-8", errors="replace").read()
    outs = "".join(io.open(os.path.join(out, f), encoding="utf-8", errors="replace").read()
                   for f in ("stdout.txt", "stderr.txt"))
    yielded = "lifespan: YIELD" in logs or "lifespan: YIELD" in outs
    perm = "PermissionError" in logs or "PermissionError" in outs
    say("  %s процесс дожил до конца отсчёта" % ("ok " if alive else "НЕТ"))
    say("  %s в журнале есть «lifespan: YIELD» (HTTP включён)" % ("ok " if yielded else "НЕТ"))
    say("  %s PermissionError в выводе нет" % ("ok " if not perm else "НЕТ"))
    if not (alive and yielded and not perm):
        tail = outs[-1500:] or logs[-1500:]
        die("стенд не пройден. Хвост вывода:\n" + tail)


# ── 7. установщики ────────────────────────────────────────────────────────────

def build_installers(dist, rel, ver):
    say("[7/9] Inno Setup: оба установщика (с компонентами Windows внутри)")
    iscc = find_iscc()
    main_out = os.path.join(rel, "3DIWELL_Farm_Manager_Setup_%s.exe" % ver)
    client_dir = os.path.join(rel, CLIENT_SUBDIR)
    client_out = os.path.join(client_dir, "3DIWELL_Farm_Manager_Client_Setup_%s.exe" % ver)
    for old in (main_out, client_out):
        if os.path.isfile(old):
            os.remove(old)                       # прошлый выпуск того же номера — пересобираем
    common = ["/DDistDir=" + dist, "/DVendorDir=" + VENDOR, "/DReleaseBuild"]
    run([iscc] + common + ["/O" + rel, "3diwell-setup.iss"])
    run([iscc] + common + ["/O" + client_dir, "3diwell-client-setup.iss"])
    for p in (main_out, client_out):
        if not os.path.isfile(p):
            die("установщик не появился: %s" % p)
        say("  собран: %s (%.1f МБ)" % (os.path.relpath(p, rel), mb(p)))
    #  R-149: VersionInfoVersion={#AppVersion} в обоих .iss — номер в свойствах установщика.
    vbad = exe_version_problems([main_out, client_out], ver)
    if vbad:
        die("у установщиков в свойствах файла не та версия (нужна %s из AppVersion = APP_VERSION):\n  %s"
            % (".".join(map(str, version_quad(ver))), "\n  ".join(vbad)))
    say("  ok  версия в свойствах обоих установщиков = %s" % ".".join(map(str, version_quad(ver))))
    return main_out, client_out


# ── 8. модули ─────────────────────────────────────────────────────────────────

def paid_signer(unsigned_paid=False):
    """-> None (внутренняя сборка с --unsigned-paid) или (закрытый ключ, key_id, дата выпуска, рабочие ключи)."""
    if unsigned_paid:
        say("  ВНИМАНИЕ: --unsigned-paid — платные модули обычными архивами без подписи (работают бесплатно).")
        say("            Такой выпуск — только для своей фермы, пользователям его не отдавать.")
        return None
    kp, pf = os.environ.get(ENV_SIGN_KEY, "").strip(), os.environ.get(ENV_SIGN_PASSFILE, "").strip()
    if not kp or not os.path.isfile(kp):
        die("платные модули для выпуска подписываются рабочим ключом пакетов: задайте %s (путь к .pem вне проекта)"
            " и %s (файл с паролем); для внутренней сборки своей фермы — --unsigned-paid" % (ENV_SIGN_KEY, ENV_SIGN_PASSFILE))
    sys.path.insert(0, REPO)
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import module_package as MP
    from app.licensing import trust as TR
    key_id = os.path.splitext(os.path.basename(kp))[0]
    prod = {k["key_id"]: k for k in TR.PRODUCTION_KEYS}
    if prod.get(key_id, {}).get("purpose") != "package":
        die("ключ %s не записан в рабочих ключах пакетов программы (app/licensing/trust.py)" % key_id)
    pw = io.open(pf, encoding="utf-8").read().strip() if pf else None
    key = MP.load_private_key(kp, pw)
    from cryptography.hazmat.primitives import serialization
    from app.licensing import fm_license_sdk as S
    pub = S.b64u_encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    if pub != prod[key_id]["public_key"]:
        die("закрытый ключ %s не соответствует открытому в app/licensing/trust.py" % key_id)
    released = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime())
    say("  платные модули: подпись ключом пакетов %s, дата выпуска %s" % (key_id, released))
    return key, key_id, released, [dict(k) for k in TR.PRODUCTION_KEYS]


def sign_paid(src_dir, dst, signer):
    """Платная сборка модуля -> dst; паспорт проверяется рабочими ключами программы до записи."""
    import zipfile
    import module_package as MP
    from app.licensing import fm_license_sdk as S
    from app.licensing import trust as TR
    key, key_id, released, keys = signer
    data, doc = MP.build_package(os.path.join(REPO, "modules", src_dir), key, key_id, released, licensing="paid",
                                 edition="standard", embed_sdk=True, embed_trust=keys)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        raw = z.read("%s/%s" % (doc["payload"]["module_id"], S.PACKAGE_MANIFEST_NAME))
    S.verify_package_manifest(raw, {k: v for k, v in TR.trusted_keys().items() if v.purpose == S.PURPOSE_PACKAGE})
    with open(dst, "wb") as f:
        f.write(data)


def build_modules(rel, unsigned_paid=False):
    say("[8/9] модули: пересборка ZIP и копирование в папку выпуска")
    signer = paid_signer(unsigned_paid)
    out = []
    for builder, zip_name, src_dir in MODULES:
        run([sys.executable, os.path.join(REPO, "tools", builder)])
        src = os.path.join(REPO, "modules", zip_name)
        if not os.path.isfile(src):
            die("сборщик %s не создал %s" % (builder, src))
        dst = os.path.join(rel, zip_name)
        paid = src_dir in PAID_MODULES and signer is not None
        if paid:
            sign_paid(src_dir, dst, signer)
        else:
            shutil.copy2(src, dst)
        man = json.load(io.open(os.path.join(REPO, "modules", src_dir, "module.json"), encoding="utf-8"))
        out.append((zip_name, (man.get("ru") or src_dir) + (" — платный: без лицензии только просмотр" if paid else ""),
                    man.get("version") or "?", dst))
        say("  %s — %s %s (%.0f КБ)" % (zip_name, out[-1][1], out[-1][2], os.path.getsize(dst) / 1024.0))
    for stray in glob.glob(os.path.join(rel, "3diwell-module-*.zip")):
        if os.path.basename(stray) not in [m[1] for m in MODULES]:
            os.remove(stray)                     # ZIP модуля, которого больше нет в списке
    return out


# ── 9. ПРОЧТИ МЕНЯ и суммы ────────────────────────────────────────────────────

def write_readme(rel, ver, main_out, client_out, modules):
    """ПРОЧТИ МЕНЯ.txt для пользователя (UTF-8 с BOM, переводы строк Windows).

    R-149 (16.10.2026): текст сверен с установщиком — папка и порт выбираются в мастере (порт 8000
    больше не обещается), сверка SHA-256 стоит ДО «Выполнить в любом случае», есть Smart App
    Control, обновление со своим портом, доступ из сети и адрес поддержки. Строка PowerShell
    проверена на настоящем Release_3.0 (9 из 9 OK) и в tools/test_release_readme.py; это
    шаблон str.format, поэтому её фигурные скобки удвоены.
    """
    mod_lines = "\n".join("  %-34s — %s (версия %s)" % (z, ru, mv) for z, ru, mv, _ in modules)
    text = """3DIWELL FARM MANAGER — версия {ver}
====================================

ЧТО В ЭТОЙ ПАПКЕ
  {main:<34} — установщик программы
  3diwell-module-*.zip               — модули (расширения), ставятся из самой программы
  {client_dir}\\ — установщик клиента: нужен, только если к ферме
                                       подключаются со второго компьютера
  {sums:<34} — контрольные суммы файлов (как проверить — ниже)
  {env:<34} — чем собран выпуск: версии Python и библиотек

СНАЧАЛА ПРОВЕРЬТЕ, ЧТО ФАЙЛЫ ЦЕЛЫ
Установщик пока без цифровой подписи, поэтому Windows не может сама подтвердить, что файл
цел. Контрольные суммы из {sums} показывают, что файлы скачались без порчи.
Суммы лежат в той же папке, что и установщик, поэтому от подмены всей папки они не защищают:
берите выпуск только по ссылке от 3DIWELL. Как сверить:
1. Откройте эту папку в Проводнике, щёлкните по адресной строке, наберите  powershell
   и нажмите Enter — откроется окно PowerShell, уже в этой папке.
2. Вставьте в него строку ниже целиком (это одна длинная строка) и нажмите Enter:

Get-Content {sums} -Encoding UTF8 | ForEach-Object {{ $h, $f = $_ -split '  ', 2; if ((Get-FileHash -LiteralPath $f).Hash -eq $h) {{ 'OK   ' + $f }} else {{ 'BAD  ' + $f }} }}

3. Напротив каждого файла должно стоять OK. Если хоть где-то BAD или PowerShell пишет
   ошибку — этот файл не запускайте: скачайте его заново и напишите в поддержку (адрес ниже).
Один файл можно проверить и отдельно: команда  Get-FileHash {main}
печатает его сумму — она должна совпасть с его строкой в {sums}
(большие и маленькие буквы не важны).

КАК УСТАНОВИТЬ ПРОГРАММУ
1. Запустите {main} обычным двойным щелчком, а не через
   «Запуск от имени администратора»: так настройка порта попадёт в вашу учётную запись,
   даже если права администратора у другой. Разрешение администратора Windows спросит сама —
   оно нужно, чтобы поставить программу и открыть её порт в брандмауэре Windows.
   Если контрольные суммы сошлись, а Windows показывает окно «Система Windows защитила ваш
   компьютер» (издатель неизвестен), нажмите «Подробнее» → «Выполнить в любом случае».
   Если Windows пишет, что запуск заблокировала функция Smart App Control
   («Интеллектуальное управление приложениями»): разрешить в ней отдельную программу нельзя,
   так она устроена. Поставить программу можно, только выключив эту защиту: «Параметры» →
   «Конфиденциальность и защита» → «Безопасность Windows» → «Управление приложениями/браузером»
   → Smart App Control. Это защита всего компьютера, решение за вами. По словам Microsoft,
   после последних обновлений Windows её можно включить обратно без переустановки системы.
   На только что установленной Windows 11 эта защита сначала работает в режиме оценки и
   установке не мешает.
2. Дальше обычный мастер: язык, лицензия, папка установки (по умолчанию
   C:\\Program Files\\3DIWELL Farm Manager, можно выбрать другую), ярлыки.
3. Страница «Порт программы» — номер, по которому открывается интерфейс программы:
   - «Автоматически (рекомендуется)» — порт 8000, а если он занят другой программой, ближайший
     свободный;
   - «Задать порт вручную» — любой номер от 1024 до 65535.
   Установщик откроет в брандмауэре Windows именно получившийся порт.
4. Установщик сам проверит, есть ли на компьютере компоненты Windows, нужные окну программы
   (Microsoft Edge WebView2 и .NET Framework), и поставит недостающие. То, что уже стоит,
   не переустанавливается. Интернет для этого не нужен: всё вложено в установщик.
   Если .NET Framework пришлось ставить, в конце установщик может попросить перезагрузку.
5. Программа запустится сама. В следующий раз открывайте её ярлыком «3DIWELL Farm Manager»
   с рабочего стола или из меню «Пуск».

Какой порт получился, видно в самой программе: «Настройки» → «Система» → «Сеть и доступ»,
строка «Порт сервера».

ОБНОВЛЕНИЕ
Прежнюю версию удалять не нужно: запустите установщик новой версии, он обновит программу на
месте. Ваши данные (принтеры, проекты, настройки) при этом не трогаются. Папку установки
оставьте прежней.
Если программа работала на своём порту (не 8000), на странице «Порт программы» выберите
«Задать порт вручную» и введите этот номер. «Автоматически» снова начинает с 8000 и может
сменить порт — тогда другие компьютеры и клиент перестанут открывать программу по прежнему
адресу.

КАК ПОСТАВИТЬ МОДУЛИ
Откройте программу → «Настройки» → «Модули» → «Установить» и выберите zip-файл из этой
папки. Ставить можно любые и в любом порядке; после установки программа предложит перезапуск.
{mods}

ТРЕБОВАНИЯ
64-разрядная Windows 10 или Windows 11. На другой системе установщик откажет с объяснением.

ЧТО ПОЯВИТСЯ НА КОМПЬЮТЕРЕ
- Программа: в папке, выбранной при установке (по умолчанию
  C:\\Program Files\\3DIWELL Farm Manager).
- Ваши данные (база принтеров, проекты, настройки, журналы):  %LOCALAPPDATA%\\3DIWELL
  Отдельная папка, обновление её не трогает. Перенести её можно в самой программе:
  «Настройки» → «Система» → «Хранение данных».
- Правило брандмауэра «3DIWELL Farm Server»: входящие TCP на порт, выбранный при установке.
  Если позже смените порт в самой программе, новый порт в брандмауэре разрешите вручную.
- Правило брандмауэра «3DIWELL Farm Manager - printer discovery»: входящие UDP 2021, 1990
  и 5353 только для самой программы — чтобы «Найти в сети» слышала принтеры.
  При удалении программы оба правила удаляются.

ДВА СПОСОБА ОТКРЫТЬ ИНТЕРФЕЙС
- Ярлык «3DIWELL Farm Manager» — собственное окно программы.
- Ярлык «3DIWELL Farm Manager — браузер» — то же самое в обычном браузере.
  Пригодится, если с окном возникнут сложности.

ДРУГИЕ КОМПЬЮТЕРЫ И КЛИЕНТ
Сразу после установки программа открывается только на этом компьютере. Чтобы открыть её с
других компьютеров сети или из клиента:
1. включите вход по паролю и создайте администратора: «Настройки» → «Система» →
   «Доступ и аудит»;
2. включите «Доступ из локальной сети»: «Настройки» → «Система» → «Сеть и доступ»;
3. там же появится строка «Адрес для других компьютеров» — откройте этот адрес в браузере
   на другом компьютере или введите его в клиенте в поле «Адрес сервера».

ЕСЛИ ЧТО-ТО ПОШЛО НЕ ТАК
Напишите в поддержку: Telegram @Sup3DiwellBot (https://t.me/Sup3DiwellBot),
сайт https://www.3diwell.com.
Опишите, что делали, что ожидали увидеть и что увидели на самом деле, и приложите последний
файл из папки  %LOCALAPPDATA%\\3DIWELL\\logs  (если папку данных переносили — из папки logs
внутри новой).

КАК УДАЛИТЬ
Обычным способом: «Параметры» → «Приложения» → «3DIWELL Farm Manager».
Папка с вашими данными при этом остаётся — удалите её вручную, если не нужна.
""".format(ver=ver, main=os.path.basename(main_out), client_dir=CLIENT_SUBDIR, mods=mod_lines,
           sums=SUMS_NAME, env=ENV_NAME)
    io.open(os.path.join(rel, README_NAME), "w", encoding="utf-8-sig", newline="\r\n").write(text)


def _py_packages(py):
    """(версия Python, ["имя==версия", ...]) окружения — без путей."""
    code = ("import sys, json, importlib.metadata as m; print(json.dumps([sys.version.split()[0], "
            "sorted(set('%s==%s' % (d.metadata['Name'], d.version) for d in m.distributions()))]))")
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, timeout=120)
        ver, pkgs = json.loads(r.stdout.decode("utf-8", "replace"))
        return ver, pkgs
    except Exception as e:
        return "не определена (%s)" % type(e).__name__, []


def _iscc_version(iscc):
    """Версия Inno Setup. Сам ISCC номер не печатает, а у файла ISCC.exe версия 0.0.0.0 —
    берём её из записи установленной программы в реестре (только чтение)."""
    try:
        import winreg
        for hive, sub in ((winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                          (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                          (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")):
            try:
                with winreg.OpenKey(hive, sub + r"\Inno Setup 6_is1") as k:
                    return str(winreg.QueryValueEx(k, "DisplayVersion")[0])
            except OSError:
                continue
    except Exception:
        pass
    return "не определена (%s)" % os.path.basename(iscc)


def build_environment_text(ver, server_env, shell_env, iscc_ver, vendor_sums, ffmpeg_sum, label=None):
    """Опись окружения сборки (R-130). Только версии, имена файлов и суммы — ни одного пути.
    label — полная версия («Beta 3.71»); без неё в заголовке только номер."""
    out = ["3DIWELL Farm Manager %s — окружение сборки / build environment" % (label or ver), ""]
    for title, (pyv, pkgs) in (("Сервер (3DIWELL Farm Manager.exe)", server_env),
                               ("Окно и клиент (Desktop.exe, Client.exe)", shell_env)):
        out.append("%s: Python %s" % (title, pyv))
        out += ["  " + p for p in pkgs]
        out.append("")
    out.append("Inno Setup: %s" % iscc_ver)
    out.append("")
    out.append("Компоненты Windows в установщике (SHA-256):")
    out += ["  %s  %s" % (h, n) for n, h in vendor_sums]
    if ffmpeg_sum:
        out += ["", "ffmpeg.exe (SHA-256): %s" % ffmpeg_sum]
    return "\n".join(out) + "\n"


def write_build_environment(rel, ver):
    ff = os.path.join(REPO, "ffmpeg.exe")
    text = build_environment_text(
        ver, _py_packages(sys.executable), _py_packages(BUILDENV_PY), _iscc_version(find_iscc()),
        [(n, sha256(os.path.join(VENDOR, n))) for n in PREREQS if os.path.isfile(os.path.join(VENDOR, n))],
        sha256(ff) if os.path.isfile(ff) else "", label=app_version_label())
    path = os.path.join(rel, ENV_NAME)
    io.open(path, "w", encoding="utf-8", newline="\r\n").write(text)
    return path


def write_sums(rel, files):
    lines = []
    for p in files:
        lines.append("%s  %s" % (sha256(p), os.path.relpath(p, rel).replace("\\", "/")))
    io.open(os.path.join(rel, SUMS_NAME), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    return lines


# ── главный порядок ───────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="Сборка выпуска 3DIWELL Farm Manager")
    ap.add_argument("--skip-exe", action="store_true", help="не пересобирать EXE (взять из staging)")
    ap.add_argument("--no-stand", action="store_true", help="пропустить стенд «папка без права записи»")
    ap.add_argument("--env-only", action="store_true",
                    help="только шаги 1-2: версия, компоненты Windows и пакеты сборки; ничего не собирать")
    ap.add_argument("--unsigned-paid", action="store_true",
                    help="внутренняя сборка своей фермы: платные модули без подписи (работают бесплатно)")
    a = ap.parse_args(argv)

    t0 = time.time()
    ver = app_version()
    label = app_version_label()
    dist = staging_dist(label)
    work = os.path.join(BUILD_ROOT, "work", ver.replace(".", "_"))
    rel = os.path.join(BUILD_ROOT, "Release_" + ver)
    say("[1/9] версия из server.py: %s" % label)
    say("      staging: %s" % dist)
    say("      выпуск:  %s" % rel)

    say("[2/9] компоненты Windows в %s" % VENDOR)
    for name in PREREQS:
        p = os.path.join(VENDOR, name)
        if not os.path.isfile(p):
            die("нет %s — где взять и как проверить подпись, написано в tools/installer/prereqs.iss" % p)
        say("  ok  %s (%.0f МБ)" % (name, mb(p)))
    #  R-149: и с --skip-exe тоже — сверка лицензий и packaged proof читают те же окружения.
    check_build_env()
    if a.env_only:
        say("")
        say("ГОТОВО (--env-only): окружение сборки совпадает с закреплёнными версиями, ничего не собиралось.")
        return

    if a.skip_exe:
        say("[3/9] EXE не пересобираются (--skip-exe)")
        for name in (SERVER_EXE, DESKTOP_EXE, CLIENT_EXE):
            if not os.path.isfile(os.path.join(dist, name)):
                die("в staging нет %s — уберите --skip-exe" % name)
    else:
        build_exes(dist, work)

    say("[4/9] удостоверение сборки: %s = %s" % (CERT_NAME, label))
    io.open(os.path.join(dist, CERT_NAME), "w", encoding="utf-8").write("%s\n" % label)

    proof(dist, ver, label)
    licenses_check(dist, work)

    if a.no_stand:
        say("[6/9] стенд пропущен (--no-stand) — сборка НЕ считается проверенной")
    else:
        stand_no_write(dist, work)

    os.makedirs(rel, exist_ok=True)
    main_out, client_out = build_installers(dist, rel, ver)
    modules = build_modules(rel, a.unsigned_paid)

    say("[9/9] ПРОЧТИ МЕНЯ.txt, %s и SHA256SUMS.txt" % ENV_NAME)
    write_readme(rel, ver, main_out, client_out, modules)
    env_file = write_build_environment(rel, ver)
    sums = write_sums(rel, [main_out, client_out] + [m[3] for m in modules] + [env_file])
    for ln in sums:
        say("  " + ln)

    say("")
    say("ГОТОВО за %.0f с. Папка выпуска: %s" % (time.time() - t0, rel))
    say("  %s (%.1f МБ)" % (os.path.basename(main_out), mb(main_out)))
    say("  %s\\%s (%.1f МБ)" % (CLIENT_SUBDIR, os.path.basename(client_out), mb(client_out)))
    say("  модулей: %d, %s, %s" % (len(modules), README_NAME, SUMS_NAME))
    say("Полный прогон проверок (tools/release_gate.py) не запускался — он по слову владельца.")


if __name__ == "__main__":
    main()
