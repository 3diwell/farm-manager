# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  3DIWELL Farm Manager — сборка desktop-оболочки (Alpha 2.805, PyInstaller).
#  Два независимых EXE из одного spec:
#    dist\3DIWELL Farm Manager Desktop.exe — собственное окно (local mode);
#    dist\3DIWELL Farm Manager Client.exe  — клиент для другого компьютера.
#  Запуск:  pyinstaller desktop_shell.spec   (обычно через tools\build_desktop_shell.ps1)
#
#  В сборку НЕ входят: server.py, рабочая БД, DATA_DIR, printer-транспорты,
#  конфигурация пользователя — оболочка тонкая по контракту.
# ============================================================================

from PyInstaller.utils.hooks import collect_all

datas = [('web/assets/icon.ico', 'web/assets')]   # иконка окна в dev-ветке пути
binaries = []
hiddenimports = [
    'webview.platforms.winforms',      # WinForms-хост pywebview
    'webview.platforms.edgechromium',  # backend WebView2
    'app', 'app.desktop_shell', 'app.desktop_shell_config', 'app.desktop_shell_security',
]

# pywebview: interop-DLL WebView2 лежат в данных пакета; pythonnet: Python.Runtime.dll.
for _pkg in ('webview', 'pythonnet', 'clr_loader', 'proxy_tools', 'bottle'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

_common = dict(
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['uvicorn', 'fastapi', 'paho', 'sqlite3', 'openpyxl', 'PIL', 'pystray'],
    noarchive=False,
)

a_local = Analysis(['desktop_launcher.pyw'], **_common)
a_client = Analysis(['client_launcher.pyw'], **_common)

pyz_local = PYZ(a_local.pure)
pyz_client = PYZ(a_client.pure)

exe_local = EXE(
    pyz_local,
    a_local.scripts,
    a_local.binaries,
    a_local.datas,
    [],
    name='3DIWELL Farm Manager Desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,               # собственное окно: консоли нет вовсе
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='web/assets/icon.ico',
    version='desktop_shell_version_local.txt',
)

exe_client = EXE(
    pyz_client,
    a_client.scripts,
    a_client.binaries,
    a_client.datas,
    [],
    name='3DIWELL Farm Manager Client',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='web/assets/icon.ico',
    version='desktop_shell_version_client.txt',
)
