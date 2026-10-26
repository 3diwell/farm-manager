# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""R-149 / R-109 (16.10.2026): памятка «ПРОЧТИ МЕНЯ» в папке выпуска говорит правду.

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ (настоящие функции tools/build_release.py на временной папке):
  1. Файл — UTF-8 с BOM и переводами строк Windows (его открывают Блокнотом).
  2. Нет прежних неправд: фиксированного порта 8000 в брандмауэре; есть то, что делает установщик
     сейчас: папка и «Порт программы» выбираются в мастере, где потом увидеть порт, обновление со
     своим портом, доступ из сети, Smart App Control, адрес поддержки, журналы.
  3. Сверка SHA-256 стоит ДО совета «Выполнить в любом случае».
  4. Строка PowerShell из памятки по-настоящему работает (если есть powershell.exe): на папке с
     русской подпапкой и SHA256SUMS.txt, записанным build_release.write_sums, — все OK; после
     порчи одного байта — ровно одна строка BAD с именем этого файла.
Сборка не запускается, сети нет, папка выпуска на компьютере не трогается.

Запуск: python tools/test_release_readme.py   (0 = пройдено)
"""
import io
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
sys.path.insert(0, os.path.join(REPO, "tools"))
import build_release as B  # noqa: E402

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


TMP = tempfile.mkdtemp(prefix="fm_readme_")
try:
    rel = os.path.join(TMP, "Release_3.0")
    client_dir = os.path.join(rel, B.CLIENT_SUBDIR)
    os.makedirs(client_dir)
    main_out = os.path.join(rel, "3DIWELL_Farm_Manager_Setup_3.0.exe")
    client_out = os.path.join(client_dir, "3DIWELL_Farm_Manager_Client_Setup_3.0.exe")
    zip_out = os.path.join(rel, "3diwell-module-inventory.zip")
    env_out = os.path.join(rel, B.ENV_NAME)
    for p, data in ((main_out, b"MZ setup " * 300), (client_out, b"MZ client " * 200),
                    (zip_out, b"PK zip " * 100), (env_out, "окружение\r\n".encode("utf-8"))):
        io.open(p, "wb").write(data)

    section("1. файл памятки")
    B.write_readme(rel, "3.0", main_out, client_out,
                   [("3diwell-module-inventory.zip", "Складской учёт", "1.7.32", zip_out)])
    raw = io.open(os.path.join(rel, B.README_NAME), "rb").read()
    body = raw[3:]
    check("1.1 UTF-8 с BOM — Блокнот показывает русский текст", raw.startswith(b"\xef\xbb\xbf"))
    check("1.2 все переводы строк Windows (CRLF)", b"\n" in body and body.count(b"\n") == body.count(b"\r\n"))
    text = body.decode("utf-8").replace("\r\n", "\n")
    check("1.3 шаблон заполнен целиком: нет непрошедших подстановок и удвоенных скобок",
          "{{" not in text and "}}" not in text and "{main" not in text and "{sums" not in text
          and "{ver" not in text and "{env" not in text, [l for l in text.splitlines() if "{" in l][:3])
    check("1.4 названы установщик, модуль, версия и подпапка клиента",
          "3DIWELL_Farm_Manager_Setup_3.0.exe" in text and "3diwell-module-inventory.zip" in text
          and "Складской учёт (версия 1.7.32)" in text and B.CLIENT_SUBDIR in text and "версия 3.0" in text)

    section("2. содержание сверено с установщиком")
    for bad in ("TCP 8000", "порт 8000 в брандмауэре", "Программа:  C:\\Program Files"):
        check("2.1 нет прежнего утверждения %r" % bad, bad not in text)
    #  Суммы лежат в той же папке, что и установщик: от подмены папки они не защищают, и памятка
    #  не должна это обещать (замечание проверки 16.10.2026).
    check("2.1 суммы не выдаются за защиту от подмены; сказано, что от подмены папки они не защищают",
          "подменён" not in text and "от подмены всей папки они не защищают" in text)
    for frag, why in (
            ("Порт программы", "страница выбора порта названа"),
            ("Задать порт вручную", "ручной порт описан"),
            ("от 1024 до 65535", "диапазон ручного порта"),
            ("C:\\Program Files\\3DIWELL Farm Manager, можно выбрать другую", "папка по умолчанию и что её можно сменить"),
            ("«Сеть и доступ»", "где потом увидеть порт"),
            ("«Порт сервера»", "строка с портом в программе"),
            ("«Автоматически» снова начинает с 8000", "обновление со своим портом"),
            ("«Доступ из локальной сети»", "доступ с других компьютеров"),
            ("«Доступ и аудит»", "вход по паролю для доступа из сети"),
            ("«Хранение данных»", "перенос папки данных"),
            ("Smart App Control", "Smart App Control"),
            ("«Запуск от имени администратора»", "совет запускать двойным щелчком"),
            ("@Sup3DiwellBot", "поддержка: Telegram"),
            ("https://t.me/Sup3DiwellBot", "поддержка: ссылка"),
            ("https://www.3diwell.com", "сайт"),
            ("%LOCALAPPDATA%\\3DIWELL\\logs", "где журналы"),
            (B.SUMS_NAME, "файл сумм назван"),
            (B.ENV_NAME, "опись окружения названа"),
            ("-Encoding UTF8", "сверка читает файл сумм как UTF-8 (иначе русская подпапка искажается)")):
        check("2.2 %s" % why, frag in text, frag)

    section("3. порядок: сначала суммы, потом «Выполнить в любом случае»")
    i_sha = text.find("Get-FileHash")
    i_run = text.find("Выполнить в любом случае")
    i_sac = text.find("Smart App Control")
    check("3.1 сверка SHA-256 стоит раньше обхода SmartScreen и Smart App Control",
          0 <= i_sha < i_run and i_sha < i_sac, (i_sha, i_run, i_sac))
    check("3.2 обход SmartScreen — только «если контрольные суммы сошлись»",
          "Если контрольные суммы сошлись" in text[max(0, i_run - 300):i_run])

    section("4. строка PowerShell из памятки работает")
    sums = B.write_sums(rel, [main_out, client_out, zip_out, env_out])
    sraw = io.open(os.path.join(rel, B.SUMS_NAME), "rb").read()
    check("4.0 SHA256SUMS.txt без BOM и с переводами строк LF (иначе не прочтёт sha256sum -c)",
          not sraw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in sraw and len(sums) == 4)
    line = next((l.strip() for l in text.splitlines() if l.strip().startswith("Get-Content ")), "")
    check("4.1 в памятке есть строка сверки целиком", line.startswith("Get-Content " + B.SUMS_NAME)
          and "Get-FileHash -LiteralPath" in line and "'  '" in line, line)
    ps = shutil.which("powershell.exe") or shutil.which("powershell")
    if not ps or not line:
        skip("4.2-4.3 запуск строки", "нет powershell.exe")
    else:
        def run_line():
            res = os.path.join(TMP, "ps_out.txt")
            if os.path.exists(res):
                os.remove(res)
            #  Строка исполняется без изменений; вывод — в файл UTF-8, чтобы русское имя дошло целым.
            cmd = "& { %s } | Out-File -FilePath '%s' -Encoding utf8" % (line, res)
            subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                           cwd=rel, capture_output=True, timeout=120)
            out = io.open(res, encoding="utf-8-sig").read() if os.path.exists(res) else ""
            return [l for l in out.splitlines() if l.strip()]

        lines = run_line()
        check("4.2 целые файлы: OK напротив каждого из %d, включая файл в русской подпапке" % len(sums),
              len(lines) == len(sums) and all(l.startswith("OK   ") for l in lines)
              and any(B.CLIENT_SUBDIR in l for l in lines), lines)
        with open(client_out, "r+b") as f:
            f.seek(5)
            b = f.read(1)
            f.seek(5)
            f.write(bytes([b[0] ^ 0xFF]))
        lines = run_line()
        bad = [l for l in lines if l.startswith("BAD  ")]
        check("4.3 испорчен один байт — ровно одна строка BAD, и это испорченный файл",
              len(lines) == len(sums) and len(bad) == 1 and os.path.basename(client_out) in bad[0], lines)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n" + "=" * 70)
print("ИТОГО: PASS=%d FAIL=%d SKIP=%d" % (PASSED[0], len(FAILS), len(SKIPS)))
for f in FAILS:
    print("  ПРОВАЛ: " + f)
sys.exit(1 if FAILS else 0)
