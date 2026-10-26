# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-149 (16.10.2026): номер версии в свойствах сервер-EXE и установщиков.

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ:
  1. tools/build_version_info.py читает APP_VERSION парой «старшая.младшая» (CLAUDE.md §8):
     «Alpha 3.0» -> 3.0.0.0, «Alpha 2.1007» -> 2.1007.0.0, «Beta 3.71» -> 3.71.0.0; без строки,
     с чужим префиксом или с числом больше 65535 — отказ, а не молча «0.0».
  2. Ресурс версии настоящий: он записывается в копию загрузчика PyInstaller тем же способом, что
     при сборке, и читается обратно (номер и строки: файл, продукт, компания).
  3. 3diwell.spec передаёт этот ресурс в EXE(version=...): спецификация исполняется с
     подставными Analysis/PYZ/EXE, и проверяется, ЧТО получил EXE.
  4. В 3diwell.spec нет пар строк ('x', 'y') кроме источников datas (ловушка набора гигиены 3b).
  5. Оба установщика: VersionInfoVersion равна AppVersion (если есть ISCC — пробный установщик из
     этой же строки даёт N.M.0.0); AppId прежние — иначе сломаются обновление и удаление.
  6. tools/build_release.py exe_version_problems: файл с верной версией проходит, без ресурса —
     назван; если на компьютере есть собранные окно и клиент, их номер равен APP_VERSION.
Сборка не запускается, сети нет; всё пишется во временную папку.

Запуск: python tools/test_build_version_info.py   (0 = пройдено)
"""
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

FAILS, PASSED, SKIPS = [], [0], []


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — " + name)
    else:
        FAILS.append(name)
        print("FAIL — " + name + (("  :: %s" % (extra,))[:700] if extra != "" else ""))


def skip(name, why):
    SKIPS.append(name)
    print("SKIP — %s: %s" % (name, why))


def section(t):
    print("\n--- %s ---" % t)


_spec = importlib.util.spec_from_file_location("fm_bvi_test", os.path.join(REPO, "tools", "build_version_info.py"))
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

try:
    from PyInstaller.utils.win32 import versioninfo as VI
    import PyInstaller
    HAVE_PI = True
except Exception:
    HAVE_PI = False


def strings_of(info):
    out = {}
    for kid in info.kids:
        for table in getattr(kid, "kids", []):
            for s in getattr(table, "kids", []):
                if hasattr(s, "name") and hasattr(s, "val"):
                    out[s.name] = s.val
    return out


TMP = tempfile.mkdtemp(prefix="fm_verinfo_")
try:
    section("1. номер из APP_VERSION — парой чисел")

    def fake_repo(line):
        d = tempfile.mkdtemp(dir=TMP)
        io.open(os.path.join(d, "server.py"), "w", encoding="utf-8").write("# x\n%s\nprint(1)\n" % line)
        return d

    r30, r2k, rnone, rbig = (fake_repo('APP_VERSION = "Alpha 3.0"'), fake_repo('APP_VERSION = "Alpha 2.1007"'),
                             fake_repo('VERSION = "3.0"'), fake_repo('APP_VERSION = "Alpha 3.70000"'))
    check("1.1 «Alpha 3.0» -> (3, 0)", V.app_version_pair(r30) == (3, 0))
    check("1.2 «Alpha 2.1007» -> (2, 1007): номер — счётчик, а не дробь", V.app_version_pair(r2k) == (2, 1007))
    #  25.10.2026: выпуск «Beta 3.71». Префикс в номер Windows не входит; посторонний — отказ.
    rbeta, rgamma = fake_repo('APP_VERSION = "Beta 3.71"'), fake_repo('APP_VERSION = "Gamma 3.71"')
    check("1.2b «Beta 3.71» -> (3, 71): префикс выпуска не влияет на номер", V.app_version_pair(rbeta) == (3, 71))
    try:
        V.app_version_pair(rgamma)
        _gamma_refused = False
    except ValueError:
        _gamma_refused = True
    check("1.2c «Gamma 3.71» — отказ: префикс выпуска только Alpha или Beta", _gamma_refused)
    for d, why in ((rnone, "строки APP_VERSION нет"), (rbig, "число больше 65535")):
        try:
            V.app_version_pair(d)
            refused = False
        except ValueError:
            refused = True
        check("1.3 %s — отказ (ValueError), а не номер наугад" % why, refused)
    pair = V.app_version_pair(REPO)
    check("1.4 настоящий server.py читается: %d.%d" % pair, pair[0] >= 3)

    if not HAVE_PI:
        skip("2-3, 6", "PyInstaller не установлен в этом Python")
    else:
        section("2. ресурс версии — настоящий")
        for d, (ma, mi) in ((r30, (3, 0)), (r2k, (2, 1007))):
            info = V.server_version_info(d)
            check("2.1 %d.%d: двоичная версия файла и продукта = %d.%d.0.0" % (ma, mi, ma, mi),
                  info.ffi.fileVersionMS == (ma << 16 | mi) and info.ffi.fileVersionLS == 0
                  and info.ffi.productVersionMS == (ma << 16 | mi) and info.ffi.productVersionLS == 0)
            back = VI.VSVersionInfo()
            back.fromRaw(info.toRaw())
            st = strings_of(back)
            check("2.2 %d.%d: строки переживают запись в байты и чтение обратно" % (ma, mi),
                  st.get("FileVersion") == "%d.%d" % (ma, mi) and st.get("ProductVersion") == "%d.%d" % (ma, mi)
                  and st.get("OriginalFilename") == "3DIWELL Farm Manager.exe"
                  and st.get("ProductName") == "3DIWELL Farm Manager" and st.get("CompanyName") == "3DIWELL", st)
        boot = os.path.join(os.path.dirname(PyInstaller.__file__), "bootloader", "Windows-64bit-intel", "run.exe")
        if not os.path.isfile(boot):
            skip("2.3-2.4 запись в EXE", "нет загрузчика PyInstaller %s" % boot)
            no_res = with_res = None
        else:
            no_res = os.path.join(TMP, "без_версии.exe")
            with_res = os.path.join(TMP, "с_версией.exe")
            shutil.copy2(boot, no_res)
            shutil.copy2(boot, with_res)
            VI.write_version_info_to_executable(with_res, V.server_version_info(r30))
            got, st = V.read_exe_version(with_res)
            check("2.3 ресурс записан в EXE так же, как при сборке, и читается: 3.0.0.0 и строки",
                  got == (3, 0, 0, 0) and st.get("FileVersion") == "3.0"
                  and st.get("FileDescription", "").startswith("3DIWELL Farm Manager"), (got, st))
            check("2.4 у файла без ресурса версии — (None, {})", V.read_exe_version(no_res) == (None, {}))

        section("3. 3diwell.spec отдаёт ресурс в EXE(version=...)")
        captured = {}

        class _A(object):
            def __init__(self, *a, **k):
                self.pure, self.scripts, self.binaries, self.datas = [], [], [], []

        hooks = types.ModuleType("PyInstaller.utils.hooks")
        hooks.collect_submodules = lambda *a, **k: []
        hooks.collect_all = lambda *a, **k: ([], [], [])
        saved_hooks = sys.modules.get("PyInstaller.utils.hooks")
        sys.modules["PyInstaller.utils.hooks"] = hooks
        cwd = os.getcwd()
        spec_src = io.open(os.path.join(REPO, "3diwell.spec"), encoding="utf-8").read()
        g = {"__name__": "__main__", "SPECPATH": REPO, "Analysis": _A, "PYZ": lambda *a, **k: object(),
             "EXE": lambda *a, **k: captured.update(k)}
        try:
            os.chdir(REPO)
            import contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(spec_src, "3diwell.spec", "exec"), g)
            spec_err = ""
        except Exception as e:
            spec_err = "%s: %s" % (type(e).__name__, e)
        finally:
            os.chdir(cwd)
            if saved_hooks is not None:
                sys.modules["PyInstaller.utils.hooks"] = saved_hooks
            else:
                sys.modules.pop("PyInstaller.utils.hooks", None)
        ver = captured.get("version")
        check("3.1 спецификация исполняется и вызывает EXE", not spec_err and "name" in captured, spec_err)
        check("3.2 EXE получает ресурс версии из APP_VERSION (%d.%d.0.0), а не файл с номером" % pair,
              isinstance(ver, VI.VSVersionInfo) and ver.ffi.fileVersionMS == (pair[0] << 16 | pair[1])
              and ver.ffi.fileVersionLS == 0, type(ver).__name__)
        check("3.3 имя EXE прежнее", captured.get("name") == "3DIWELL Farm Manager", captured.get("name"))

    section("4. ловушка набора гигиены 3b")
    spec_text = io.open(os.path.join(REPO, "3diwell.spec"), encoding="utf-8").read()
    pairs = re.findall(r"\(\s*'([^']+)'\s*,\s*'[^']*'\s*\)", spec_text)
    missing = [p for p in pairs if not os.path.exists(os.path.join(REPO, p))]
    check("4.1 каждая пара строк в 3diwell.spec — существующий источник datas (%d)" % len(pairs),
          pairs and not missing, missing)

    section("5. установщики: VersionInfoVersion = AppVersion, AppId прежние")
    APP_IDS = {"3diwell-setup.iss": "{{8C1F2A93-5E47-4B6A-9D3C-1A2B3C4D5E6F}",
               "3diwell-client-setup.iss": "{{7B4E9D21-0A6C-4F8E-B1D5-2C3E4F5A6B7C}"}
    iss_lines = {}
    for iss, app_id in APP_IDS.items():
        t = io.open(os.path.join(REPO, iss), encoding="utf-8-sig").read()
        defines = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', t, re.M))
        m = re.search(r"^\[Setup\]\s*$(.*?)^\[", t, re.M | re.S)
        setup = {}
        for ln in (m.group(1) if m else "").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith(";") and "=" in ln:
                k, v = ln.split("=", 1)
                setup[k.strip()] = v.strip()
        raw_vi = setup.get("VersionInfoVersion", "")
        resolved = re.sub(r"\{#(\w+)\}", lambda mm: defines.get(mm.group(1), "?"), raw_vi)
        iss_lines[iss] = (defines.get("AppVersion", ""), raw_vi)
        check("5.1 %s: VersionInfoVersion в [Setup] раскрывается в AppVersion (%s)" % (iss, resolved),
              raw_vi and resolved == defines.get("AppVersion") and resolved == "%d.%d" % pair, (raw_vi, resolved))
        check("5.2 %s: AppId не менялся (иначе не обновится и не удалится прежняя установка)" % iss,
              setup.get("AppId") == app_id, setup.get("AppId"))
    iscc = None
    for c in (os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
              r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"):
        if os.path.isfile(c):
            iscc = c
            break
    if not iscc:
        skip("5.3 пробный установщик", "нет ISCC.exe (Inno Setup 6)")
    else:
        app_ver, raw_vi = iss_lines["3diwell-setup.iss"]
        probe = os.path.join(TMP, "probe.iss")
        io.open(probe, "w", encoding="utf-8-sig").write(
            '#define AppVersion "%s"\n[Setup]\nAppId={{00000000-0000-0000-0000-000000000149}\nAppName=Probe\n'
            'AppVersion={#AppVersion}\n%s\nDefaultDirName={autopf}\\Probe\nOutputDir=out\n'
            'OutputBaseFilename=probe\nPrivilegesRequired=lowest\nCreateAppDir=no\n'
            % (app_ver, "VersionInfoVersion=" + raw_vi))
        r = subprocess.run([iscc, "/Q", probe], cwd=TMP, capture_output=True, timeout=180)
        out_exe = os.path.join(TMP, "out", "probe.exe")
        got = V.read_exe_version(out_exe) if (r.returncode == 0 and os.path.isfile(out_exe)) else (None, {})
        check("5.3 Inno Setup с этой строкой ставит в свойства установщика %d.%d.0.0 (а не 0.0.0.0)" % pair,
              got[0] == (pair[0], pair[1], 0, 0), (r.returncode, got, r.stdout[-300:]))

    section("6. сверка номера в сборщике выпуска")
    import build_release as B
    if HAVE_PI and no_res and with_res:
        check("6.1 верная версия проходит, файл без ресурса назван",
              B.exe_version_problems([with_res], "3.0") == []
              and len(B.exe_version_problems([with_res, no_res], "3.0")) == 1
              and "без_версии.exe: стоит нет" in B.exe_version_problems([no_res], "3.0")[0],
              B.exe_version_problems([with_res, no_res], "3.0"))
        check("6.2 другой номер (2.1007) — расхождение названо", B.exe_version_problems([with_res], "2.1007")
              == ["с_версией.exe: стоит 3.0.0.0, нужно 2.1007.0.0"], B.exe_version_problems([with_res], "2.1007"))
    else:
        skip("6.1-6.2", "нет PyInstaller или загрузчика")
    ver_s = "%d.%d" % pair
    #  25.10.2026: папка сборки называется полной версией (Beta_3.71, у Alpha 3.0 — Alpha_3.0).
    check("6.0 номер сборщика выпуска совпадает с номером ресурса, папка staging — по полной версии",
          B.app_version() == ver_s and B.app_version_label().endswith(" " + ver_s)
          and B.staging_dist("Beta 3.71") == os.path.join(B.BUILD_ROOT, "Beta_3.71", "dist")
          and B.staging_dist("Alpha 3.0") == os.path.join(B.BUILD_ROOT, "Alpha_3.0", "dist"),
          (B.app_version(), B.app_version_label()))
    dist = B.staging_dist(B.app_version_label())
    shells = [os.path.join(dist, n) for n in (B.DESKTOP_EXE, B.CLIENT_EXE)]
    if not all(os.path.isfile(p) for p in shells):
        skip("6.3 собранные окно и клиент", "нет %s" % dist)
    else:
        probs = B.exe_version_problems(shells, ver_s)
        check("6.3 собранные окно и клиент (%s): номер в свойствах = %s.0.0" % (B.app_version_label(), ver_s),
              not probs, probs)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 70)
print("ИТОГО: PASS=%d FAIL=%d SKIP=%d" % (PASSED[0], len(FAILS), len(SKIPS)))
for f in FAILS:
    print("  ПРОВАЛ: " + f)
sys.exit(1 if FAILS else 0)
