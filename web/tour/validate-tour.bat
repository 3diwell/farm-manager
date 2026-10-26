@REM SPDX-License-Identifier: MPL-2.0
@REM SPDX-FileCopyrightText: 2025-2026 3DiWell Team
@REM This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
@REM If a copy of the MPL was not distributed with this file, You can obtain one at
@REM https://mozilla.org/MPL/2.0/.
@echo off
setlocal
cd /d "%~dp0"
node validate-tour.mjs
pause
