@REM SPDX-License-Identifier: MPL-2.0
@REM SPDX-FileCopyrightText: 2025-2026 3DiWell Team
@REM This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
@REM If a copy of the MPL was not distributed with this file, You can obtain one at
@REM https://mozilla.org/MPL/2.0/.
@echo off
chcp 65001 >nul
title Запись сетевых объявлений принтеров (3DIWELL)
cd /d "%~dp0.."
echo.
echo   Инструмент записывает то, что принтеры сами рассказывают о себе в сеть.
echo   Он ничего не отправляет и ничего на принтерах не меняет.
echo.
python tools\printer_net_capture.py --seconds 600
echo.
pause
