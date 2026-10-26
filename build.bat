@REM SPDX-License-Identifier: MPL-2.0
@REM SPDX-FileCopyrightText: 2025-2026 3DiWell Team
@REM This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
@REM If a copy of the MPL was not distributed with this file, You can obtain one at
@REM https://mozilla.org/MPL/2.0/.
@echo off
REM ============================================================================
REM  3DIWELL Farm Manager - build the .exe and (optionally) the installer.
REM  Run this from the project folder (the one that contains server.py).
REM
REM  Plain ASCII on purpose; calls 3diwell.spec (PyInstaller) and, if Inno Setup
REM  is installed, compiles 3diwell-setup.iss into a setup.exe.
REM ============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py"

echo.
echo ===========================================================
echo  3DIWELL Farm Manager - build
echo ===========================================================
echo  Python launcher: %PY%
echo.

echo [1/5] Installing dependencies (pinned: app requirements + PyInstaller)...
REM 16.10.2026 (R-149): exact versions of the Alpha 3.0 build. requirements-build.txt
REM includes requirements.txt and pins PyInstaller, so a newer release is never taken silently.
%PY% -m pip install --upgrade pip
if errorlevel 1 goto :fail
%PY% -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

echo.
echo [2/5] Cleaning previous build...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo.
echo [3/5] Building the .exe (this can take a few minutes)...
%PY% -m PyInstaller --noconfirm --clean "3diwell.spec"
if errorlevel 1 goto :fail
if not exist "dist\3DIWELL Farm Manager.exe" goto :nofile

echo.
echo [4/5] Building the installer (optional - needs Inno Setup 6)...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC goto :no_installer
echo   Compiling 3diwell-setup.iss ...
"!ISCC!" "3diwell-setup.iss"
if errorlevel 1 goto :installer_failed
echo   Installer created in the "installer" folder.
goto :after_installer
:no_installer
echo   Inno Setup not found - skipped this step.
echo   To make a setup.exe: install Inno Setup 6 from https://jrsoftware.org/isdl.php
echo   then run build.bat again (or compile 3diwell-setup.iss yourself).
goto :after_installer
:installer_failed
echo   Installer compilation FAILED - scroll up for the message.
:after_installer

echo.
echo [5/5] Done.
echo.
echo ===========================================================
echo  SUCCESS
echo ===========================================================
echo  Standalone program:  dist\3DIWELL Farm Manager.exe
if defined ISCC echo  Installer (setup):   installer\3DIWELL_Farm_Manager_Setup_*.exe
echo.
echo  Share the installer with users for a normal setup wizard
echo  (license, install folder, shortcuts). The plain .exe also
echo  runs on its own. User data is stored separately from the .exe.
echo.
pause
exit /b 0

:nofile
echo.
echo  Build finished but dist\3DIWELL Farm Manager.exe was not found.
echo  Scroll up to check for errors.
echo.
pause
exit /b 1

:fail
echo.
echo ===========================================================
echo  BUILD FAILED - scroll up to read the error message.
echo ===========================================================
echo  Common fixes:
echo    - install Python 3.14 and make sure it is on PATH
echo    - run this file from the folder that contains server.py
echo    - check your internet connection (pip needs to download)
echo    - make sure ffmpeg.exe is next to server.py (for Bambu cameras)
echo.
pause
exit /b 1
