# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""26.09.2026 — тексты лицензий сторонних компонентов, вшитых в программу, ставятся вместе с ней.

ЧТО ЗАЩИЩАЕТ. В основной программе (сервер фермы) лежат чужие материалы со своими лицензиями:
FFmpeg (GNU GPL v3), изображения принтеров из OrcaSlicer (GNU AGPL v3), шрифты интерфейса (SIL OFL
1.1). Эти лицензии разрешают раздачу, только если рядом лежит их полный текст, а для FFmpeg —
ещё и сведения, где взять исходный код. До 26.09.2026 выданные установщики этого не содержали.

  1. Тексты GPL-3.0 и AGPL-3.0 — дословные с gnu.org (сверка SHA-256).
  2. Примечание к FFmpeg называет версию, лицензию, параметры сборки, ссылку на исходный код и
     предложение выдать исходный код по запросу; версия совпадает с настоящим ffmpeg.exe проекта.
  3. Примечание к изображениям называет источник (OrcaSlicer), лицензию и число файлов — ровно
     столько, сколько лежит в printer_covers.
  4. Установщик основной программы ставит всё это в папку licenses рядом с программой;
     4a — там же тексты лицензий пакетов Python внутри EXE (THIRD_PARTY_LICENSES.txt, R-130).
  5. Перечень сторонних компонентов, страница лицензии установщика и окно «О программе»
     указывают на папку licenses.

Запуск:  python tools/test_license_files.py      (0 = всё в порядке)
"""
import glob
import hashlib
import io
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIC = os.path.join(REPO, "packaging", "installer", "licenses")
GNU_SHA256 = {"GPL-3.0.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
              "AGPL-3.0.txt": "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"}
FFMPEG_VERSION = "8.1.1"

_pass, _fail, _skip = [0], [], []


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


def skip(name, why):
    _skip.append(name)
    print("SKIP — %s: %s" % (name, why))


def read(p):
    return io.open(p, encoding="utf-8-sig").read()


print("=" * 78)
print("1. Тексты лицензий")
print("=" * 78)
for n, want in GNU_SHA256.items():
    p = os.path.join(LIC, n)
    got = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else ""
    check("1.%s — дословный текст с gnu.org" % n, got == want, got)

print("\n" + "=" * 78)
print("2. FFmpeg")
print("=" * 78)
FF = read(os.path.join(LIC, "FFMPEG_NOTICE.txt"))
check("2.1 названы версия, сборка и лицензия",
      ("FFmpeg %s" % FFMPEG_VERSION) in FF and "gyan.dev" in FF and "GNU General Public License, версия 3" in FF
      and "GPL-3.0.txt" in FF)
check("2.2 указано, где исходный код, и параметры сборки",
      ("https://ffmpeg.org/releases/ffmpeg-%s.tar.xz" % FFMPEG_VERSION) in FF and "--enable-gpl --enable-version3" in FF)
check("2.3 есть предложение выдать исходный код по запросу (не меньше трёх лет)",
      "Предложение исходного кода" in FF and "не меньше трёх лет" in FF and "Written offer" in FF)
exe = os.path.join(REPO, "ffmpeg.exe")
if os.path.isfile(exe):
    try:
        out = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.decode("utf-8", "replace")
    except Exception as e:
        out = str(e)
    m = re.search(r"ffmpeg version (\S+)", out)
    ver = m.group(1) if m else ""
    check("2.4 примечание описывает именно тот ffmpeg.exe, что лежит в проекте (%s)" % ver,
          ver.startswith(FFMPEG_VERSION + "-essentials_build-www.gyan.dev") and "--enable-gpl --enable-version3" in out, ver)
    cfg = re.search(r"configuration: (.*)", out)
    flags = cfg.group(1).split() if cfg else []
    ff_flags = set(re.findall(r"--[\w-]+", FF))
    check("2.5 параметры сборки в примечании совпадают с настоящими", flags and set(flags) <= ff_flags,
          sorted(set(flags) - ff_flags))
else:
    skip("2.4-2.5 сверка с ffmpeg.exe", "ffmpeg.exe в этой копии нет")

print("\n" + "=" * 78)
print("3. Изображения принтеров")
print("=" * 78)
PI = read(os.path.join(LIC, "PRINTER_IMAGES_NOTICE.txt"))
check("3.1 названы источник и лицензия",
      "https://github.com/OrcaSlicer/OrcaSlicer" in PI and "GNU Affero General Public License, версия 3" in PI
      and "AGPL-3.0.txt" in PI and "Файлы не изменялись" in PI)
covers = glob.glob(os.path.join(REPO, "printer_covers", "*_cover.png"))
m = re.search(r"содержат (\d+) изображени", PI)
if covers:
    check("3.2 число изображений в примечании (%s) — ровно столько, сколько в printer_covers (%d)"
          % (m.group(1) if m else "?", len(covers)), m and int(m.group(1)) == len(covers))
else:
    skip("3.2 сверка числа изображений", "printer_covers в этой копии нет")

print("\n" + "=" * 78)
print("4. Установщик")
print("=" * 78)
ISS = read(os.path.join(REPO, "3diwell-setup.iss"))
check("4.1 установщик основной программы ставит тексты и примечания в папку licenses",
      'Source: "packaging\\installer\\licenses\\*.txt"; DestDir: "{app}\\licenses"' in ISS
      and 'Source: "web\\design\\fonts\\OFL-*.txt"; DestDir: "{app}\\licenses"' in ISS)
#  R-130 (29.09.2026): + THIRD_PARTY_LICENSES.txt — тексты лицензий пакетов Python внутри EXE;
#  установщик ставит его той же строкой (всё *.txt этой папки), правка .iss не нужна.
need = ["GPL-3.0.txt", "AGPL-3.0.txt", "FFMPEG_NOTICE.txt", "PRINTER_IMAGES_NOTICE.txt",
        "THIRD_PARTY_LICENSES.txt"]
check("4.2 все файлы, которые ставит установщик, на месте",
      all(os.path.isfile(os.path.join(LIC, n)) for n in need)
      and all(os.path.isfile(os.path.join(REPO, "web", "design", "fonts", n)) for n in ("OFL-Jura.txt", "OFL-Play.txt")))
check("4.3 в папке licenses нет лишних файлов (ставится всё, что там лежит)",
      sorted(os.path.basename(p) for p in glob.glob(os.path.join(LIC, "*"))) == sorted(need),
      sorted(os.listdir(LIC)))
check("4.4 тексты — без нулевых и служебных символов (путь в установщике не испорчен)",
      "\x0c" not in ISS and all("\x00" not in read(os.path.join(LIC, n)) for n in need))

print("\n" + "=" * 78)
print("4a. Тексты лицензий пакетов Python внутри программы (R-130)")
print("=" * 78)
TPL_PATH = os.path.join(LIC, "THIRD_PARTY_LICENSES.txt")
TPL = read(TPL_PATH) if os.path.isfile(TPL_PATH) else ""
_heads = re.findall(r"(?m)^={76}\r?\n([^\r\n]+)\r?\n={76}\r?$", TPL)
_names = set(h.split(" ", 1)[0].lower() for h in _heads)
check("4a.1 файл есть и собран инструментом (шапка на двух языках, MPL для своего кода)",
      TPL.startswith("Тексты лицензий сторонних компонентов 3DIWELL Farm Manager")
      and "Mozilla Public License 2.0" in TPL[:600] and "collect_third_party_licenses.py" in TPL[:600])
#  Пакеты, которые вшиты в EXE наверняка: сервер (fastapi/uvicorn и то, что 3diwell.spec берёт
#  целиком через collect_all — websockets, httptools), трей (pystray), оболочки (pywebview,
#  pythonnet). До R-130 сборщик терял websockets и httptools из-за кавычек в маркере extra;
#  packaging (Apache-2.0 / BSD-2-Clause, вшит во все три EXE) терялся, потому что совпадал по имени
#  с папкой packaging/ проекта.
_must = ("fastapi", "uvicorn", "starlette", "pydantic", "websockets", "httptools", "pystray", "pillow",
         "paho-mqtt", "openpyxl", "cryptography", "pywebview", "pythonnet", "clr_loader", "bottle",
         "packaging")
check("4a.2 в файле есть все заведомо вшитые пакеты (%d)" % len(_must),
      all(n in _names for n in _must), sorted(n for n in _must if n not in _names))
check("4a.3 у каждого пакета указаны версия и хотя бы текст или ссылка",
      len(_heads) >= 20 and all(re.match(r"\S+ \d[\w.+!-]* — ", h) for h in _heads[5:]),
      [h for h in _heads[5:] if not re.match(r"\S+ \d[\w.+!-]* — ", h)][:3])
check("4a.4 внутренних путей сборочной машины в файле нет",
      not re.search(r"[A-Za-z]:[\\/]+Users[\\/]|3DIWELL_Builds|site-packages|buildenv", TPL, re.I))
_raw = open(TPL_PATH, "rb").read() if TPL else b""
check("4a.5 окончания строк CRLF по всему файлу (как у остальных текстов для Windows)",
      _raw.count(b"\n") > 100 and _raw.count(b"\n") == _raw.count(b"\r\n"))
check("4a.6 файл не раздут: меньше 1 МБ (крупный файл в git требует отдельного назначения)",
      0 < len(_raw) < 1024 * 1024, len(_raw))

print("\n" + "=" * 78)
print("5. Где об этом сказано")
print("=" * 78)
TPN = read(os.path.join(REPO, "THIRD_PARTY_NOTICES.md"))
check("5.1 перечень сторонних компонентов указывает на тексты в папке licenses",
      all(("licenses\\" + n) in TPN for n in need + ["OFL-Jura.txt", "OFL-Play.txt"]))
for name, key in (("license-page-ru.txt", "licenses в папке программы"), ("license-page-en.txt", "licenses folder")):
    check("5.2 страница лицензии установщика (%s) называет компоненты и папку licenses" % name,
          key in read(os.path.join(REPO, "packaging", "installer", name)))
IDX = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
check("5.3 окно «О программе» указывает на папку licenses",
      "файл THIRD_PARTY_NOTICES.txt и папка licenses в папке программы" in IDX)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d SKIP=%d" % (_pass[0], len(_fail), len(_skip)))
if _fail:
    for f in _fail:
        print("   - " + f)
sys.exit(1 if _fail else 0)
