# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
<#
  3DIWELL Farm Manager — проверка установщика на чистой Windows без сети (R-109, 16.10.2026).

  ИНСТРУМЕНТ РАЗРАБОТКИ. В выпуск не входит, на компьютере фермы не запускается: скрипт СТАВИТ
  программу, создаёт правила брандмауэра и папку данных. Поэтому вне Windows Sandbox он
  отказывается работать (пользователь песочницы — WDAGUtilityAccount); на отдельной тестовой
  виртуальной машине его можно запустить с ключом -AllowOutsideSandbox. Но и с этим ключом он
  останавливается (код 2, ничего не меняя), если на компьютере уже есть папка программы в
  Program Files или папка данных %LOCALAPPDATA%\3DIWELL: иначе прогон переставил бы программу
  фермы и записал бы порт в её настоящие настройки. Обойти — только вторым ключом
  -IKnowThisIsNotTheFarm.

  КАК ЗАПУСТИТЬ (один раз владелец включает компонент «Песочница Windows»: «Включение или
  отключение компонентов Windows» → Windows Sandbox → перезагрузка; это системная настройка):
    1. Собрать выпуск (python tools/build_release.py) — папка C:\3DIWELL_Builds\Release_<версия>.
    2. Создать пустую папку C:\3DIWELL_Builds\sandbox_out (песочница не стартует, если папки нет).
    3. Двойной щелчок по tools\installer\sandbox\fm-install-test.wsb. Песочница без сети, папка
       выпуска подключена только для чтения как C:\Release, этот набор — как C:\Kit, результаты
       пишутся в C:\out (= C:\3DIWELL_Builds\sandbox_out). Скрипт стартует сам при входе.
    4. Через несколько минут в sandbox_out появится result.json: "ok": true — всё сошлось.
  В .wsb пути заданы полностью (Release_3.71): для другого номера выпуска поправьте HostFolder.

  ЧТО ПРОВЕРЯЕТСЯ:
    · суммы файлов выпуска по SHA256SUMS.txt (как в «ПРОЧТИ МЕНЯ»);
    · что стояло ДО установки: WebView2 Runtime (значение pv) и .NET Framework (Release) —
      по ним в result.json видно, какой путь пройден: компонент поставил установщик или он уже был;
    · тихая установка: /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG (порт — «Автоматически»),
      код завершения Inno Setup (0 — успех; 7 и 8 — остановка на шаге компонентов Windows);
    · файлы программы и лицензий в Program Files, оба правила брандмауэра и порт первого из них;
    · server_port в config.json папки данных и совпадение с портом правила брандмауэра;
    · окно: запускается Desktop.exe, сервер отвечает на http://127.0.0.1:<порт>/version номером
      «Alpha N.M» или «Beta N.M» с номером из имени установщика, появляется окно с заголовком
      «3DIWELL Farm Manager».
  Журналы установки и программы копируются в C:\out для разбора.

  НЕ ПРОВЕРЕНО НА ДЕЛЕ (16.10.2026): компонент песочницы на компьютере разработки не включён, и
  этот скрипт ещё ни разу не запускался. Есть ли WebView2 внутри песочницы и поднимает ли тихая
  установка окно UAC — неизвестно; result.json записывает и то и другое как есть.
#>
param(
    [string]$ReleaseDir = 'C:\Release',
    [string]$OutDir = 'C:\out',
    [int]$WaitSeconds = 180,
    [switch]$AllowOutsideSandbox,
    [switch]$IKnowThisIsNotTheFarm
)

$ErrorActionPreference = 'Continue'
$WV2_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
$NDP_MIN_RELEASE = 461808      # .NET Framework 4.7.2 — тот же порог, что в tools\installer\prereqs.iss
$APP_TITLE = '3DIWELL Farm Manager'

$inSandbox = ($env:USERNAME -eq 'WDAGUtilityAccount')
if ((-not $inSandbox) -and (-not $AllowOutsideSandbox)) {
    Write-Host 'Остановлено: скрипт ставит программу и меняет брандмауэр, поэтому работает только внутри'
    Write-Host 'Windows Sandbox (fm-install-test.wsb). На тестовой виртуальной машине: -AllowOutsideSandbox.'
    exit 2
}
#  16.10.2026 (R-109, замечание проверки): вне песочницы одного имени пользователя мало. На
#  компьютере, где уже стоит программа или лежит папка данных (так на компьютере разработки, где
#  работает ферма), прогон переставил бы программу поверх, записал бы порт в НАСТОЯЩИЙ config.json,
#  заменил правило брандмауэра и запустил окно на рабочих данных. Инструмент — для чистой машины,
#  поэтому такой компьютер он не трогает. Обойти — только вторым явным ключом -IKnowThisIsNotTheFarm.
if (-not $inSandbox) {
    $busy = @((Join-Path $env:ProgramFiles '3DIWELL Farm Manager'), (Join-Path $env:LOCALAPPDATA '3DIWELL')) |
        Where-Object { Test-Path -LiteralPath $_ }
    if ($busy -and (-not $IKnowThisIsNotTheFarm)) {
        Write-Host 'Остановлено: на этом компьютере уже есть Farm Manager или его данные:'
        $busy | ForEach-Object { Write-Host ('  ' + $_) }
        Write-Host 'Проверка установщика нужна чистой Windows: запустите её в Windows Sandbox или на чистой'
        Write-Host 'виртуальной машине. Ничего не изменено.'
        exit 2
    }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
try { Start-Transcript -Path (Join-Path $OutDir 'transcript.txt') -Force | Out-Null } catch {}

$checks = New-Object System.Collections.ArrayList
function Add-Check([string]$Name, [bool]$Ok, $Detail) {
    [void]$script:checks.Add([ordered]@{ name = $Name; ok = $Ok; detail = "$Detail" })
    $mark = if ($Ok) { 'ok ' } else { 'НЕТ' }
    Write-Host ("  {0} {1} {2}" -f $mark, $Name, $Detail)
}

function Get-WebView2Version {
    $keys = @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$WV2_GUID",
              "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$WV2_GUID",
              "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$WV2_GUID")
    foreach ($k in $keys) {
        try {
            $v = (Get-ItemProperty -LiteralPath $k -Name pv -ErrorAction Stop).pv
            if ($v -and ($v -ne '0.0.0.0')) { return [string]$v }
        } catch {}
    }
    return $null
}

function Get-DotNetRelease {
    try {
        return [int](Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release -ErrorAction Stop).Release
    } catch { return $null }
}

function Get-PathTaken($Before, $After, [bool]$PresentBefore, [bool]$PresentAfter) {
    if ($PresentBefore) { return 'already_present' }
    if ($PresentAfter) { return 'installed_by_setup' }
    return 'missing_after_setup'
}

$result = [ordered]@{
    tool = 'tools/installer/sandbox/run_install_test.ps1'
    started = (Get-Date).ToString('s')
    windows = [string](Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Version
    user = $env:USERNAME
}

Write-Host '[1] файлы выпуска против SHA256SUMS.txt'
$sums = Join-Path $ReleaseDir 'SHA256SUMS.txt'
if (Test-Path -LiteralPath $sums) {
    $bad = @()
    $n = 0
    Get-Content -LiteralPath $sums -Encoding UTF8 | ForEach-Object {
        $h, $f = $_ -split '  ', 2
        if ($f) {
            $n++
            $p = Join-Path $ReleaseDir $f
            if (-not (Test-Path -LiteralPath $p) -or ((Get-FileHash -LiteralPath $p).Hash -ne $h)) { $bad += $f }
        }
    }
    Add-Check 'release_sha256' (($n -gt 0) -and ($bad.Count -eq 0)) ("файлов {0}, не сошлось: {1}" -f $n, ($bad -join ', '))
} else {
    Add-Check 'release_sha256' $false 'нет SHA256SUMS.txt'
}

Write-Host '[2] что стояло до установки'
$wv2Before = Get-WebView2Version
$ndpBefore = Get-DotNetRelease
Write-Host ("  WebView2 pv: {0}; .NET Release: {1}" -f $wv2Before, $ndpBefore)

Write-Host '[3] тихая установка'
$setup = Get-ChildItem -LiteralPath $ReleaseDir -Filter '3DIWELL_Farm_Manager_Setup_*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
$expectedVersion = $null
if ($setup) {
    #  25.10.2026: в имени установщика только номер, а сервер отвечает «Alpha N.M» или «Beta N.M»
    #  (с Beta 3.71) — сверяется номер, префикс выпуска любой из двух.
    if ($setup.Name -match '_Setup_(\d+\.\d+)\.exe$') { $expectedVersion = $Matches[1] }
    $log = Join-Path $OutDir 'setup.log'
    $t0 = Get-Date
    $proc = Start-Process -FilePath $setup.FullName -PassThru -Wait -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', ('/LOG="{0}"' -f $log))
    $result.setup_file = $setup.Name
    $result.setup_seconds = [int]((Get-Date) - $t0).TotalSeconds
    $result.setup_exit_code = $proc.ExitCode
    Add-Check 'setup_exit_code' ($proc.ExitCode -eq 0) $proc.ExitCode
} else {
    Add-Check 'setup_found' $false ("в {0} нет 3DIWELL_Farm_Manager_Setup_*.exe" -f $ReleaseDir)
}

$wv2After = Get-WebView2Version
$ndpAfter = Get-DotNetRelease
$result.webview2 = [ordered]@{ before = $wv2Before; after = $wv2After
    path = (Get-PathTaken $wv2Before $wv2After ([bool]$wv2Before) ([bool]$wv2After)) }
$result.dotnet = [ordered]@{ before = $ndpBefore; after = $ndpAfter
    path = (Get-PathTaken $ndpBefore $ndpAfter ($ndpBefore -ge $NDP_MIN_RELEASE) ($ndpAfter -ge $NDP_MIN_RELEASE)) }
Add-Check 'dotnet_4_7_2_or_newer' ($ndpAfter -ge $NDP_MIN_RELEASE) ("{0} -> {1} ({2})" -f $ndpBefore, $ndpAfter, $result.dotnet.path)
Add-Check 'webview2_runtime' ([bool]$wv2After) ("{0} -> {1} ({2})" -f $wv2Before, $wv2After, $result.webview2.path)

Write-Host '[4] файлы программы'
$app = Join-Path $env:ProgramFiles $APP_TITLE
foreach ($f in @('3DIWELL Farm Manager.exe', '3DIWELL Farm Manager Desktop.exe', 'LICENSE.txt',
                 'THIRD_PARTY_NOTICES.txt', 'licenses\THIRD_PARTY_LICENSES.txt', 'unins000.exe')) {
    Add-Check ('file: ' + $f) (Test-Path -LiteralPath (Join-Path $app $f)) ''
}

Write-Host '[5] брандмауэр и порт'
$fwPort = $null
foreach ($name in @('3DIWELL Farm Server', '3DIWELL Farm Manager - printer discovery')) {
    $rule = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
    Add-Check ('firewall: ' + $name) ($null -ne $rule) ''
    if ($rule -and ($name -eq '3DIWELL Farm Server')) {
        $fwPort = [string](($rule | Get-NetFirewallPortFilter).LocalPort)
    }
}
$cfgPath = Join-Path $env:LOCALAPPDATA '3DIWELL\config.json'
$port = $null
if (Test-Path -LiteralPath $cfgPath) {
    try { $port = [int]((Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json).server_port) } catch {}
}
$result.server_port = $port
$result.firewall_port = $fwPort
Add-Check 'config.json server_port' (($port -ge 1024) -and ($port -le 65535)) $port
Add-Check 'firewall port = server_port' ($fwPort -eq [string]$port) ("{0} / {1}" -f $fwPort, $port)

Write-Host '[6] окно и сервер'
$desktop = Join-Path $app '3DIWELL Farm Manager Desktop.exe'
if ((Test-Path -LiteralPath $desktop) -and $port) {
    Start-Process -FilePath $desktop | Out-Null
    $answer = $null
    $window = $null
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline -and (-not ($answer -and $window))) {
        Start-Sleep -Seconds 3
        if (-not $answer) {
            try {
                $wc = New-Object System.Net.WebClient
                $answer = ($wc.DownloadString("http://127.0.0.1:$port/version") | ConvertFrom-Json).version
            } catch {}
        }
        if (-not $window) {
            $window = Get-Process -ErrorAction SilentlyContinue |
                Where-Object { $_.MainWindowTitle -like "$APP_TITLE*" } |
                Select-Object -First 1 -ExpandProperty MainWindowTitle
        }
    }
    $result.version_answer = $answer
    $result.window_title = $window
    $answerNumber = $null
    if ($answer -and ("$answer" -match '^(?:Alpha|Beta) (\d+\.\d+)$')) { $answerNumber = $Matches[1] }
    Add-Check 'server /version' ($answerNumber -and (($null -eq $expectedVersion) -or ($answerNumber -eq $expectedVersion))) ("{0} (ожидалось Alpha или Beta {1})" -f $answer, $expectedVersion)
    #  Без WebView2 окно программы не открывается, а предлагает браузер окном-вопросом с тем же
    #  заголовком — поэтому заголовок проверяется вместе с наличием WebView2 (шаг 2).
    Add-Check 'window' ([bool]$window) $window
} else {
    Add-Check 'window' $false 'нет Desktop.exe или порта — окно не запускалось'
}

Write-Host '[7] журналы'
$logs = Join-Path $env:LOCALAPPDATA '3DIWELL\logs'
if (Test-Path -LiteralPath $logs) {
    Copy-Item -LiteralPath $logs -Destination (Join-Path $OutDir 'program_logs') -Recurse -Force -ErrorAction SilentlyContinue
    $noWv2 = Select-String -Path (Join-Path $logs '*.log') -Pattern 'WebView2 Runtime не найден' -SimpleMatch -ErrorAction SilentlyContinue
    $result.log_says_no_webview2 = [bool]$noWv2
}

$result.checks = $checks
$result.ok = -not ($checks | Where-Object { -not $_.ok })
$result.finished = (Get-Date).ToString('s')
$json = $result | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText((Join-Path $OutDir 'result.json'), $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host ''
Write-Host ("ИТОГ: ok = {0}. Подробности — {1}" -f $result.ok, (Join-Path $OutDir 'result.json'))
try { Stop-Transcript | Out-Null } catch {}
