# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Ресурс версии сервер-EXE «3DIWELL Farm Manager.exe» — из APP_VERSION при сборке (R-149, 16.10.2026).

ЗАЧЕМ. В свойствах файла сервера (Свойства → Подробно) версии не было вовсе: 3diwell.spec вызывал
EXE() без version=. У окна и клиента номер есть — его держат desktop_shell_version_*.txt.

ПОЧЕМУ НЕ ЕЩЁ ОДИН ФАЙЛ ВЕРСИИ. Номер живёт в пяти файлах (CLAUDE.md §8), и каждое новое место —
лишняя возможность разойтись. Поэтому ресурс собирается в момент сборки прямо из APP_VERSION
server.py: 3diwell.spec загружает этот файл по пути и передаёт server_version_info() в EXE(version=).
PyInstaller принимает в version= готовый объект VSVersionInfo так же, как путь к текстовому файлу
(PyInstaller/building/api.py: путь он сам загружает в тот же объект).

Номер читается ПАРОЙ «старшая.младшая» (CLAUDE.md §8): «Alpha 3.0» -> (3, 0), «Alpha 2.1007» ->
(2, 1007), «Beta 3.71» -> (3, 71); в ресурсе это 3.0.0.0, 2.1007.0.0 и 3.71.0.0 — так же, как у окна
и клиента. Префикс выпуска (Alpha или Beta, с 25.10.2026 — Beta) в номер Windows не входит.

read_exe_version() читает готовый EXE (pefile, только чтение) — им сборщик выпуска сверяет номер
у всех трёх EXE и обоих установщиков, а tools/test_build_version_info.py — поведение.
"""
import io
import os
import re

COMPANY = "3DIWELL"
PRODUCT = "3DIWELL Farm Manager"
SERVER_EXE_BASE = "3DIWELL Farm Manager"
DESCRIPTION = "3DIWELL Farm Manager — сервер фермы"
COPYRIGHT = "© 2025–2026 3DiWell Team"
#  Та же языковая пара, что у окна и клиента (desktop_shell_version_*.txt): русский, Unicode.
LANG_CODEPAGE = "041904B0"
TRANSLATION = [1049, 1200]

_APP_VERSION_RE = re.compile(r'^APP_VERSION\s*=\s*"(?:Alpha|Beta)\s+(\d+)\.(\d+)"', re.M)


def app_version_pair(repo):
    """(старшая, младшая) из APP_VERSION в <repo>/server.py. Нет строки — ValueError."""
    src = io.open(os.path.join(repo, "server.py"), encoding="utf-8").read()
    m = _APP_VERSION_RE.search(src)
    if not m:
        raise ValueError("APP_VERSION не найден в %s" % os.path.join(repo, "server.py"))
    major, minor = int(m.group(1)), int(m.group(2))
    if not (0 <= major <= 0xFFFF and 0 <= minor <= 0xFFFF):
        #  В двоичной версии Windows каждое число — 16 бит; больше не поместится.
        raise ValueError("номер %d.%d не помещается в версию Windows (до 65535)" % (major, minor))
    return major, minor


def version_strings(major, minor):
    """Строки ресурса версии (имя -> значение)."""
    text = "%d.%d" % (major, minor)
    return {
        "CompanyName": COMPANY,
        "FileDescription": DESCRIPTION,
        "FileVersion": text,
        "InternalName": SERVER_EXE_BASE,
        "LegalCopyright": COPYRIGHT,
        "OriginalFilename": SERVER_EXE_BASE + ".exe",
        "ProductName": PRODUCT,
        "ProductVersion": text,
    }


def server_version_info(repo):
    """VSVersionInfo для EXE(version=...) в 3diwell.spec. Нужен установленный PyInstaller."""
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct,
                                                     StringTable, VarFileInfo, VarStruct,
                                                     VSVersionInfo)
    major, minor = app_version_pair(repo)
    quad = (major, minor, 0, 0)
    strings = version_strings(major, minor)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=quad, prodvers=quad, mask=0x3F, flags=0x0, OS=0x40004,
                          fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable(LANG_CODEPAGE,
                                        [StringStruct(k, v) for k, v in strings.items()])]),
            VarFileInfo([VarStruct("Translation", list(TRANSLATION))]),
        ])


def read_exe_version(path):
    """(двоичная FileVersion как (a, b, c, d) или None, {строка: значение}) готового EXE.

    Только чтение, через pefile (он стоит вместе с PyInstaller). Ресурса версии нет — (None, {}).
    """
    import pefile
    pe = pefile.PE(path, fast_load=True)
    try:
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        binary = None
        fixed = getattr(pe, "VS_FIXEDFILEINFO", None)
        if fixed:
            ffi = fixed[0]
            binary = (ffi.FileVersionMS >> 16, ffi.FileVersionMS & 0xFFFF,
                      ffi.FileVersionLS >> 16, ffi.FileVersionLS & 0xFFFF)
        strings = {}
        for group in getattr(pe, "FileInfo", None) or []:
            #  pefile отдаёт FileInfo списком списков (новые версии) или плоским списком (старые).
            for entry in (group if isinstance(group, list) else [group]):
                for table in getattr(entry, "StringTable", None) or []:
                    for k, v in table.entries.items():
                        #  Inno Setup дополняет строки пробелами до своей длины — их отрезаем.
                        strings[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace").rstrip(" \x00")
        return binary, strings
    finally:
        pe.close()
