@REM SPDX-License-Identifier: MPL-2.0
@REM SPDX-FileCopyrightText: 2025-2026 3DiWell Team
@REM This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
@REM If a copy of the MPL was not distributed with this file, You can obtain one at
@REM https://mozilla.org/MPL/2.0/.
@echo off
setlocal
title 3DIWELL - Controlled one-shot print
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0real_one_shot_print.ps1"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo The helper ended with an error. It never calls /start by itself.
echo Press any key to close this window.
pause >nul
exit /b %RC%
