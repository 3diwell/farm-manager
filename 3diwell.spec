# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  3DIWELL Farm Manager — сборка одного самодостаточного .exe (PyInstaller).
#  Запуск:  pyinstaller 3diwell.spec
#  (обычно через build.bat — он сам ставит зависимости и вызывает это).
#
#  Почему .spec, а не длинная команда в .bat: команда PyInstaller с десятком
#  --add-data/--hidden-import и переносами строк (^) легко ломается в cmd
#  (особенно с кириллическими комментариями и неверной кодировкой). .spec —
#  это обычный Python: парсит его сам PyInstaller, никаких проблем cmd нет.
# ============================================================================

import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

# --- Данные, вшиваемые ВНУТРЬ .exe (доступны в рантайме через sys._MEIPASS) ---
#  server.py ищет их через resource_path()/_web_path()/_covers_dir(): сперва рядом
#  с .exe, затем внутри сборки — поэтому всё работает и из вшитой копии.
#  Alpha 2.939: каталог web/ берётся ПОФАЙЛОВО, а не целиком.
#  ПРАВИЛО ВЛАДЕЛЬЦА: релизная и бета-сборка содержат только саму программу — без исходников,
#  без служебных скриптов и без документации по проектированию. Каталог web/ хранит и то, и
#  другое: рядом с работающим SPA лежат инструкция по правкам обучения, две ревизии его текстов
#  и селекторов, описание графических ресурсов и проверялка обучения (validate-tour.bat/.mjs).
#  Программа их не читает — единственная ссылка на TOUR_GUIDE_RU.md стоит в КОММЕНТАРИИ
#  web/app.js, — но до 2.938 они попадали внутрь EXE и уезжали бета-тестеру.
#  ПОЧЕМУ ОТБОР ПО РАСШИРЕНИЮ БЕЗОПАСЕН: среди работающих файлов web/ расширений .md/.bat/.mjs
#  нет вовсе (17 .js, 6 .css, 1 .html и ассеты) — проверено пофайлово. Появится нужный файл с
#  таким расширением — его придётся внести в исключение явно.
WEB_DEV_ONLY = ('.md', '.bat', '.mjs')


def _web_runtime_files():
    taken, skipped = [], []
    for _root, _dirs, _files in os.walk('web'):
        for _f in _files:
            (skipped if _f.lower().endswith(WEB_DEV_ONLY) else taken).append((os.path.join(_root, _f), _root))
    print('[spec] web/: %d runtime files bundled, %d development files excluded' % (len(taken), len(skipped)))
    for _src, _ in skipped:
        print('[spec]   excluded: ' + _src)
    return taken


datas = _web_runtime_files()
binaries = []

# 26.09.2026: обложки принтеров — необязательный вход сборки, как ffmpeg.exe ниже.
# В открытом репозитории их нет (права на них не подтверждены), и сборка из чистой копии не должна
# падать. Без обложек программа показывает значки-заглушки.
# Официальный выпуск проверяет их наличие сам (tools/build_release.py, проверка содержимого EXE).
# Шрифты интерфейса (по умолчанию 3DIWELL Wide J, SIL OFL) лежат в web/design/fonts/ и попадают
# в сборку вместе с web/. Прежний коммерческий шрифт удалён из программы 26.09.2026.
if os.path.isdir('printer_covers'):
    datas += [('printer_covers', 'printer_covers')]   # PNG-обложки моделей принтеров
    print('[spec] printer_covers/ found -> bundled')
else:
    print('[spec] WARNING: printer_covers/ NOT found -> printer cards show placeholder icons')

# ffmpeg.exe — нужен для трансляции камер Bambu Lab (RTSP → MJPEG через ffmpeg). Лежит рядом с server.py.
# server.py находит его через resource_path("ffmpeg.exe") (сперва внутри сборки _MEIPASS, затем рядом с .exe).
# Если файла рядом нет — сборка НЕ падает, но видео с камер Bambu в .exe работать не будет.
if os.path.exists('ffmpeg.exe'):
    datas += [('ffmpeg.exe', '.')]
    print('[spec] ffmpeg.exe found -> bundled (Bambu camera streaming will work)')
else:
    print('[spec] WARNING: ffmpeg.exe NOT found next to the spec -> Bambu camera streaming will NOT work in this build!')

# --- Скрытые импорты: то, что PyInstaller не находит сам (динамические импорты) ---
hiddenimports = [
    'pystray._win32',                      # бэкенд значка трея для Windows
    # пакет app/* — модуль app.import_worker исполняется в дочерних процессах пула
    'app', 'app.utils', 'app.part_counter', 'app.part_contours',
    'app.import_worker', 'app.model_compat', 'app.diagnostics',
]
hiddenimports += collect_submodules('uvicorn')    # циклы и протоколы uvicorn (asyncio, h11/httptools, websockets, lifespan)
hiddenimports += collect_submodules('pydantic')   # pydantic v2 (вкл. pydantic_core)

# Пакеты с ленивыми импортами и/или своими данными — берём целиком и аккуратно
# (если какого-то нет в окружении — просто пропускаем, сборка не падает).
for _pkg in ('openpyxl', 'multipart', 'python_multipart', 'paho', 'cryptography',
             'websockets', 'httptools', 'h11', 'wsproto', 'anyio', 'starlette'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 09.10.2026, решение владельца: numpy программе не нужен, но openpyxl берёт его необязательным
    # импортом (openpyxl.compat.numbers, openpyxl.utils.dataframe), если пакет стоит в Python сборки.
    # 07.10 numpy появился в системном Python — и сервер вырос на 6,6 МБ лишнего пакета, который
    # грузился при каждом старте вместе с openpyxl. Без numpy openpyxl работает как прежде.
    excludes=['numpy'],
    noarchive=False,
)

pyz = PYZ(a.pure)

# 16.10.2026 (R-149): номер версии в свойствах файла сервера (Свойства → Подробно). Ресурс
# собирается при сборке из APP_VERSION server.py (tools/build_version_info.py) — отдельного файла
# с номером нет, мест версии из CLAUDE.md §8 не прибавилось. Помощник грузится по пути: папки
# tools в путях импорта у PyInstaller нет.
import importlib.util as _ilu
_vi_spec = _ilu.spec_from_file_location('fm_build_version_info',
                                        os.path.join(SPECPATH, 'tools', 'build_version_info.py'))
_vi = _ilu.module_from_spec(_vi_spec)
_vi_spec.loader.exec_module(_vi)
_server_version = _vi.server_version_info(SPECPATH)
print('[spec] version resource: %d.%d.0.0 from APP_VERSION' % _vi.app_version_pair(SPECPATH))

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='3DIWELL Farm Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,            # приложение само прячет консоль в трей (SW_HIDE); консоль нужна для логов и кнопки «Показать консоль»
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='web/assets/icon.ico',
    version=_server_version,
)
