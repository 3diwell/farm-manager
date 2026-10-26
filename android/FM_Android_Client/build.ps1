# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
param([switch]$Offline, [string]$CoreReference = '')
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$jdk = Get-ChildItem -LiteralPath "$root\toolchain\java" -Directory | Select-Object -First 1
if (!$jdk) { throw 'JDK 17 missing: see README_RU.md' }
$env:JAVA_HOME = $jdk.FullName
$env:ANDROID_HOME = "$root\toolchain\sdk"
$env:ANDROID_USER_HOME = "$root\toolchain\android-user"
$env:GRADLE_USER_HOME = "$root\toolchain\gradle-cache"
$env:FM_CAMERA_TEST_OUTPUT = "$root\app\build\camera-fixtures"
$env:FM_CONTROL_TEST_OUTPUT = "$root\app\build\control-fixtures"
$env:FM_REPEAT_TEST_OUTPUT = "$root\app\build\repeat-fixtures"
$gradle = "$root\toolchain\gradle\gradle-8.11.1\bin\gradle.bat"
$params = @('--no-daemon', '--console=plain', '-p', $root, 'testDebugUnitTest', 'assembleDebug', 'lintDebug')
if ($Offline) { $params += '--offline' }
& $gradle @params
if ($LASTEXITCODE -ne 0) { throw 'Android build or validation failed' }
node "$root\tests\test_farm_camera.js" $env:FM_CAMERA_TEST_OUTPUT
if ($LASTEXITCODE -ne 0) { throw 'Printer camera lifecycle checks failed' }
python "$root\tests\test_mobile_api.py"
if ($LASTEXITCODE -ne 0) { throw 'Server tests failed' }
python "$root\tests\test_prepared_labels.py"
if ($LASTEXITCODE -ne 0) { throw 'Prepared label tests failed' }
python "$root\tests\test_demo_http.py"
if ($LASTEXITCODE -ne 0) { throw 'HTTP integration tests failed' }
python "$root\tests\test_nfc_inventory.py"
if ($LASTEXITCODE -ne 0) { throw 'NFC inventory tests failed' }
python "$root\tests\test_branding_010.py"
if ($LASTEXITCODE -ne 0) { throw 'Branding resource checks failed' }
python "$root\tests\test_localization_013.py"
if ($LASTEXITCODE -ne 0) { throw 'Localization and theme checks failed' }
python "$root\tests\test_mobile_09_boundaries.py"
if ($LASTEXITCODE -ne 0) { throw 'Camera behavior checks failed' }
python "$root\tests\test_operation_hints_014.py"
if ($LASTEXITCODE -ne 0) { throw 'Operation hint resource and boundary checks failed' }
if ($CoreReference) {
    $env:FM_CORE_REFERENCE = [IO.Path]::GetFullPath($CoreReference)
    if (!(Test-Path -LiteralPath "$env:FM_CORE_REFERENCE\server.py" -PathType Leaf)) { throw 'FM core reference is missing.' }
    python "$root\tests\test_printer_controls_contract.py"
    if ($LASTEXITCODE -ne 0) { throw 'Printer control reference checks failed' }
    python "$root\tests\test_printer_repeat_contract.py"
    if ($LASTEXITCODE -ne 0) { throw 'Printer repeat reference checks failed' }
} else {
    Write-Output 'FM reference checks skipped: pass -CoreReference to verify against the supplied core.'
}
# Separate builder produces the opt-in module update; never installs it in FM.
Copy-Item -LiteralPath "$root\app\build\outputs\apk\debug\app-debug.apk" -Destination "$root\dist\FM-Client-0.15.15-debug.apk"
Get-FileHash "$root\dist\FM-Client-0.15.15-debug.apk"
