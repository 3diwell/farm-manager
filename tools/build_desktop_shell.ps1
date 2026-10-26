# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  3DIWELL Farm Manager - build desktop shell EXEs (Alpha 2.805).
#  Builds:  dist\3DIWELL Farm Manager Desktop.exe  (local window)
#           dist\3DIWELL Farm Manager Client.exe   (remote client)
#  Then, if Inno Setup is installed, compiles the CLIENT installer:
#           installer\3DIWELL_Farm_Manager_Client_Setup_<ver>.exe
#  Usage:   powershell -ExecutionPolicy Bypass -File tools\build_desktop_shell.ps1
#  ASCII only (PowerShell 5.1 safe).
# ============================================================================
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "[1/3] PyInstaller: desktop_shell.spec"
python -m PyInstaller --noconfirm desktop_shell.spec
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller FAILED"; exit 1 }

$exe1 = Join-Path $repo 'dist\3DIWELL Farm Manager Desktop.exe'
$exe2 = Join-Path $repo 'dist\3DIWELL Farm Manager Client.exe'
if (-not (Test-Path $exe1)) { Write-Host "MISSING: $exe1"; exit 1 }
if (-not (Test-Path $exe2)) { Write-Host "MISSING: $exe2"; exit 1 }
Write-Host "[2/3] Built:"
Get-Item $exe1, $exe2 | ForEach-Object { "  {0}  ({1:N0} bytes)" -f $_.Name, $_.Length }

$iscc = @('C:\Program Files (x86)\Inno Setup 6\ISCC.exe', 'C:\Program Files\Inno Setup 6\ISCC.exe') |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    Write-Host "[3/3] Inno Setup: 3diwell-client-setup.iss"
    & $iscc "3diwell-client-setup.iss"
    if ($LASTEXITCODE -ne 0) { Write-Host "ISCC FAILED"; exit 1 }
} else {
    Write-Host "[3/3] Inno Setup not found - client installer skipped (EXEs are ready in dist\)"
}
Write-Host "DONE."
