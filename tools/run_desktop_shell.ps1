# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  3DIWELL Farm Manager - run the DESKTOP SHELL (local mode) without building EXE.
#  Usage:  powershell -ExecutionPolicy Bypass -File tools\run_desktop_shell.ps1
#  Extra args are passed through, e.g.:  ... run_desktop_shell.ps1 --debug-shell
#  ASCII only (PowerShell 5.1 safe).
# ============================================================================
$repo = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = (Get-Command python).Source }
Start-Process -FilePath $pyw -ArgumentList (@("`"$repo\desktop_launcher.pyw`"") + $args) -WorkingDirectory $repo
Write-Host "Desktop shell starting (local mode). Window should appear shortly."
