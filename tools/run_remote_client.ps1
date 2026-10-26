# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  3DIWELL Farm Manager - run the REMOTE CLIENT shell without building EXE.
#  Usage:  powershell -ExecutionPolicy Bypass -File tools\run_remote_client.ps1
#  The client never starts a local backend and never opens the local DB.
#  ASCII only (PowerShell 5.1 safe).
# ============================================================================
$repo = Split-Path -Parent $PSScriptRoot
$pyw = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = (Get-Command python).Source }
Start-Process -FilePath $pyw -ArgumentList (@("`"$repo\client_launcher.pyw`"") + $args) -WorkingDirectory $repo
Write-Host "Remote client shell starting. Window should appear shortly."
