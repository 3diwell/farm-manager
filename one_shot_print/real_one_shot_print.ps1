# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
$ErrorActionPreference = 'Stop'

# 3DIWELL controlled one-shot print helper (version-independent).
# This helper NEVER calls /start and NEVER confirms plate clearance itself.
# The operator performs BOTH confirmations in the web UI:
#   1) "Plate cleared" (initial confirmation; printer must be safely idle);
#   2) "Controlled single print" with its four checkboxes.
# The helper only: picks the ready item, arms the server via CLI flags, opens the UI,
# watches progress, and restores the normal safe mode afterwards.
#
# NOT pinned to any app version: it checks that the server EXPOSES one-shot arming
# (the /api/project-orchestrator/transport-status endpoint) instead of matching an exact
# version string. So the same helper keeps working across app updates.

$BaseUrl = 'http://localhost:8000'
$ConfirmPhrase = 'I_UNDERSTAND_THIS_SENDS_A_REAL_PRINT'
$armedProcess = $null
$normalWasClosed = $false

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host ('=== ' + $Text + ' ===') -ForegroundColor Cyan
}

function Get-HttpJson([string]$Url) {
    return Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 8
}

function Get-TransportStatus {
    # Returns the parsed transport-status object, or $null if the endpoint is missing/unreachable.
    try {
        return Get-HttpJson ($BaseUrl + '/api/project-orchestrator/transport-status')
    } catch {
        return $null
    }
}

function Test-ServerUp {
    return ($null -ne (Get-TransportStatus))
}

function Test-OneShotSupported($Status) {
    # Capability check (version-independent): the status object carries the arming fields.
    if ($null -eq $Status) { return $false }
    foreach ($field in @('armed', 'dispatch_enabled', 'transport_enabled')) {
        if ($null -eq $Status.PSObject.Properties[$field]) { return $false }
    }
    return $true
}

function Wait-Server([bool]$ShouldBeUp, [int]$Seconds = 60) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ((Test-ServerUp) -eq $ShouldBeUp) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Resolve-ProjectDir {
    # The helper lives in <app>\one_shot_print, so server.py is one level up. Fall back to the
    # script folder itself and to the known install path.
    $candidates = @()
    $parent = Split-Path -Parent $PSScriptRoot
    if ($parent) { $candidates += $parent }
    $candidates += $PSScriptRoot
    $candidates += 'C:\3DIWELL_Farm_Manager'
    foreach ($dir in $candidates) {
        if ($dir -and (Test-Path -LiteralPath (Join-Path $dir 'server.py'))) { return $dir }
    }
    throw 'server.py was not found. Keep the one_shot_print folder inside C:\3DIWELL_Farm_Manager and run the BAT again.'
}

function Resolve-Python {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { $cmd = Get-Command python -ErrorAction SilentlyContinue }
    if ($null -eq $cmd) { throw 'Python was not found in PATH.' }
    return $cmd.Source
}

function Start-FarmServer([string]$Python, [string]$ProjectDir, [string[]]$Arguments) {
    return Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $ProjectDir -PassThru
}

function Stop-ExactProcess($Process) {
    if ($null -eq $Process) { return }
    try {
        if (-not $Process.HasExited) {
            Stop-Process -Id $Process.Id -ErrorAction Stop
            $Process.WaitForExit(10000) | Out-Null
        }
    } catch {
        Write-Warning ('Could not stop the exact armed process: ' + $_.Exception.Message)
    }
}

function Get-ItemState([string]$RunId, [string]$ItemId) {
    try {
        $detail = Get-HttpJson ($BaseUrl + '/api/project-runs/' + [Uri]::EscapeDataString($RunId))
        foreach ($item in @($detail.items)) {
            if ([string]$item.item_id -eq $ItemId) {
                return [pscustomobject]@{ ItemState = [string]$item.state; RunState = [string]$detail.state }
            }
        }
    } catch { }
    return [pscustomobject]@{ ItemState = ''; RunState = '' }
}

try {
    Write-Host '3DIWELL CONTROLLED ONE-SHOT PRINT' -ForegroundColor Green
    Write-Host 'This helper never calls /start and never confirms the plate itself.'
    Write-Host 'You will do both confirmations in the web UI. This helper arms, watches and restores.'

    $projectDir = Resolve-ProjectDir
    $python = Resolve-Python

    Write-Step '1 of 8 - Reading ready project items from the normal server'
    $initialStatus = Get-TransportStatus
    if ($null -eq $initialStatus) {
        throw 'The Farm Manager server is not running on http://localhost:8000. Start it normally, then run this BAT again.'
    }
    if (-not (Test-OneShotSupported $initialStatus)) {
        throw 'This server build does not expose one-shot arming (transport-status has no arming fields). Update Farm Manager, then run this BAT again.'
    }
    if ($initialStatus.armed -or $initialStatus.dispatch_enabled -or $initialStatus.transport_enabled) {
        throw 'The current server is already armed. Stop it and start Farm Manager normally before the real print.'
    }

    $active = Get-HttpJson ($BaseUrl + '/api/project-runs?active=1')
    $candidates = @()
    foreach ($runSummary in @($active.runs)) {
        $runId = [string]$runSummary.run_id
        if ([string]::IsNullOrWhiteSpace($runId)) { continue }
        try {
            $detail = Get-HttpJson ($BaseUrl + '/api/project-runs/' + [Uri]::EscapeDataString($runId))
        } catch {
            Write-Warning ('Could not read run ' + $runId + ': ' + $_.Exception.Message)
            continue
        }
        $printersById = @{}
        foreach ($p in @($detail.printers)) { $printersById[[string]$p.printer_id] = $p }
        $projectName = if ($runSummary.PSObject.Properties['project_name'] -and $runSummary.project_name) { [string]$runSummary.project_name } else { 'Project unavailable' }
        # The current run item is the first pending/eligible one; arming must target exactly it.
        foreach ($item in @($detail.items)) {
            if ([string]$item.state -notin @('pending', 'eligible')) { continue }
            $feed = $item.feed_plan
            if ($null -eq $feed -or [string]$feed.effective_status -ne 'ready') { continue }
            $printerId = [string]$feed.printer_id
            $itemId = [string]$item.item_id
            if ([string]::IsNullOrWhiteSpace($printerId) -or [string]::IsNullOrWhiteSpace($itemId)) { continue }
            $printer = $printersById[$printerId]
            if ($null -eq $printer) { continue }
            # Only a safely idle printer with fresh telemetry qualifies: the initial "Plate cleared"
            # confirmation requires exactly this on the server side.
            if (-not $printer.telemetry_fresh -or -not $printer.safe_idle) {
                Write-Host ('  skipped: printer ' + $printerId + ' is not safely idle (' + [string]$printer.unsafe_reason + ')') -ForegroundColor DarkYellow
                continue
            }
            $fileName = if ($item.PSObject.Properties['filename'] -and $item.filename) { [string]$item.filename } else { [string]$item.file_id }
            $slot = if ($null -ne $feed.ams_slot) { [string]$feed.ams_slot } else { '?' }
            $candidates += [pscustomobject]@{
                RunId = $runId; ItemId = $itemId; PrinterId = $printerId
                Project = $projectName; File = $fileName; Slot = $slot
            }
            break   # one candidate per run: only the current run item is startable
        }
    }

    if ($candidates.Count -eq 0) {
        throw 'No ready current run item on a safely idle printer was found. In the app: confirm the material and the empty plate first, then run this BAT again. Nothing was armed.'
    }

    Write-Host ''
    for ($i = 0; $i -lt $candidates.Count; $i++) {
        $c = $candidates[$i]
        Write-Host ('[{0}] Project: {1} | Item: {2} | Printer: {3} | Slot: {4}' -f ($i + 1), $c.Project, $c.File, $c.PrinterId, $c.Slot)
    }
    if ($candidates.Count -eq 1) {
        $selected = $candidates[0]
        Write-Host 'Exactly one candidate was found; it was selected automatically.' -ForegroundColor Green
    } else {
        $answer = Read-Host ('Choose one line (1-' + $candidates.Count + '), or press Ctrl+C to cancel')
        $choice = 0
        if (-not [int]::TryParse($answer, [ref]$choice) -or $choice -lt 1 -or $choice -gt $candidates.Count) {
            throw 'Invalid selection. Nothing was armed.'
        }
        $selected = $candidates[$choice - 1]
    }

    Write-Step '2 of 8 - Physical preparation (do it NOW, before the 15-minute timer starts)'
    Write-Host ('Printer for this print: ' + $selected.PrinterId) -ForegroundColor Yellow
    Write-Host 'Prepare BEFORE arming, because arming lasts only 15 minutes:'
    Write-Host '  - the plate is physically empty, previous parts are removed;'
    Write-Host '  - the correct spool is loaded and the material matches the plan;'
    Write-Host '  - the printer is idle and healthy;'
    Write-Host '  - you stay NEXT TO the printer for the whole print.'
    Read-Host 'When the physical preparation is done, press Enter'

    Write-Step '3 of 8 - Close the normal Farm Manager'
    Read-Host 'Close the normal Farm Manager/server now. When it is closed, press Enter'
    if (-not (Wait-Server $false 60)) {
        throw 'Port 8000 is still occupied. Nothing was armed. Close the normal server and try again.'
    }
    $normalWasClosed = $true

    Write-Step '4 of 8 - Starting the one-shot armed server (15-minute window begins)'
    $serverArgs = @(
        'server.py',
        '--project-one-shot-run', $selected.RunId,
        '--project-one-shot-item', $selected.ItemId,
        '--project-one-shot-printer', $selected.PrinterId,
        '--project-one-shot-confirm', $ConfirmPhrase
    )
    $armedProcess = Start-FarmServer $python $projectDir $serverArgs
    if (-not (Wait-Server $true 60)) {
        throw 'The armed server did not become available. No print request was sent.'
    }
    $status = Get-TransportStatus
    $scopeOk = ($null -ne $status -and $null -ne $status.scope -and $status.scope.run_id -eq $selected.RunId -and $status.scope.item_id -eq $selected.ItemId -and $status.scope.printer_id -eq $selected.PrinterId)
    if ($null -eq $status -or -not $status.armed -or $status.consumed -or -not $scopeOk -or -not [string]::IsNullOrEmpty([string]$status.error)) {
        throw ('Arming verification failed. Status: ' + ($status | ConvertTo-Json -Compress -Depth 6))
    }
    Write-Host ('ARMED OK. TTL: ' + $status.expires_in_s + ' seconds.') -ForegroundColor Green
    Start-Process ($BaseUrl + '/') | Out-Null

    Write-Step '5 of 8 - YOUR two actions in the web UI (in this order)'
    Write-Host 'In the project, on the current run:' -ForegroundColor Yellow
    Write-Host '  ACTION 1: press "Plate cleared" (the button is enabled only while the printer is'
    Write-Host '            safely idle with fresh telemetry);'
    Write-Host '  ACTION 2: press "Controlled single print", tick ALL FOUR checkboxes, then send.'
    Write-Host 'This helper will only WATCH. It will not press anything for you.'

    Write-Step '6 of 8 - Watching the print (Ctrl+C aborts watching only, not the print)'
    $lastLine = ''
    $accepted = $false
    $finished = $false
    while (-not $finished) {
        Start-Sleep -Seconds 5
        $st = Get-TransportStatus
        if ($null -eq $st) {
            Write-Warning 'The armed server stopped responding. If the command was already sent, check the printer physically.'
            continue
        }
        $probe = Get-ItemState $selected.RunId $selected.ItemId
        $line = ('arm consumed=' + $st.consumed + ' | item=' + $probe.ItemState + ' | run=' + $probe.RunState)
        if ($line -ne $lastLine) { Write-Host ('  ' + $line); $lastLine = $line }
        if ($st.consumed -and -not $accepted) {
            $accepted = $true
            Write-Host 'The one-shot arm is consumed: a second start is IMPOSSIBLE without re-arming.' -ForegroundColor Yellow
        }
        switch ($probe.ItemState) {
            'waiting_start_confirmation' { }
            'printing' { }
            'waiting_plate_clear' {
                Write-Host ''
                Write-Host 'The print FINISHED (item is waiting_plate_clear).' -ForegroundColor Green
                $finished = $true
            }
            'completed' {
                Write-Host 'Item is completed.' -ForegroundColor Green
                $finished = $true
            }
            'ambiguous_after_dispatch' {
                Write-Host ''
                Write-Host 'AMBIGUOUS RESULT: it is unknown whether the print started.' -ForegroundColor Red
                Write-Host 'DO NOT retry and DO NOT re-arm. Check the printer physically and decide in the UI' -ForegroundColor Red
                Write-Host '("Print started" / "Print not started"). The helper will now restore normal mode.' -ForegroundColor Red
                $finished = $true
            }
            'failed_before_dispatch' {
                Write-Host ''
                Write-Host 'The start FAILED before dispatch: nothing was sent to the printer.' -ForegroundColor Yellow
                Write-Host 'See the reason in the UI. To try again, re-run this helper from the beginning.' -ForegroundColor Yellow
                $finished = $true
            }
            default { }
        }
        if ($st.armed -eq $false -and $st.consumed -eq $false -and -not $accepted -and $st.expires_in_s -eq 0) {
            Write-Host ''
            Write-Host 'The 15-minute arming window EXPIRED before the start was sent.' -ForegroundColor Yellow
            Write-Host 'Nothing was printed. Re-run this helper to arm again.' -ForegroundColor Yellow
            $finished = $true
        }
    }

    Write-Step '7 of 8 - After the print'
    if ($accepted) {
        Write-Host 'Remove the printed part from the plate. Then, in the web UI, press "Plate cleared"'
        Write-Host 'again (this time it is the normal post-print confirmation).'
        Read-Host 'When the part is removed and the plate is confirmed in the UI, press Enter'
        $probe = Get-ItemState $selected.RunId $selected.ItemId
        Write-Host ('Final state: item=' + $probe.ItemState + ' | run=' + $probe.RunState)
        if ($probe.RunState -eq 'completed') {
            Write-Host 'The whole plan is COMPLETED and the printer hold is released.' -ForegroundColor Green
        } else {
            Write-Host 'The next run becomes current in the app. Re-run this helper to print it (one print per run).' -ForegroundColor Yellow
        }
    }

    Write-Step '8 of 8 - Restoring normal safe mode'
    Stop-ExactProcess $armedProcess
    $armedProcess = $null
    if (-not (Wait-Server $false 30)) {
        throw 'Port 8000 did not close after stopping the armed process. For safety, the helper will not start another server.'
    }
    $null = Start-FarmServer $python $projectDir @('server.py')
    if (-not (Wait-Server $true 60)) {
        throw 'The normal server did not become available. Start it manually without one-shot flags.'
    }
    $safeStatus = Get-TransportStatus
    if ($null -eq $safeStatus -or $safeStatus.armed -or $safeStatus.dispatch_enabled -or $safeStatus.transport_enabled -or $null -ne $safeStatus.scope) {
        throw ('Normal-mode verification failed: ' + ($safeStatus | ConvertTo-Json -Compress -Depth 6))
    }
    Write-Host ''
    Write-Host 'SUCCESS: normal safe mode restored (armed/dispatch/transport are all OFF).' -ForegroundColor Green
    Start-Process ($BaseUrl + '/') | Out-Null
    exit 0
}
catch {
    Write-Host ''
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'This helper did not call /start and did not confirm the plate.' -ForegroundColor Yellow
    if ($null -ne $armedProcess) {
        Write-Host 'Stopping the exact armed process started by this helper...'
        Stop-ExactProcess $armedProcess
        $armedProcess = $null
        Wait-Server $false 20 | Out-Null
    }
    if ($normalWasClosed -and -not (Test-ServerUp)) {
        try {
            Write-Host 'Attempting to restore normal safe mode...'
            $projectDir = Resolve-ProjectDir
            $python = Resolve-Python
            $null = Start-FarmServer $python $projectDir @('server.py')
            if (Wait-Server $true 60) {
                $safe = Get-TransportStatus
                if ($null -ne $safe -and -not $safe.armed -and -not $safe.dispatch_enabled -and -not $safe.transport_enabled) {
                    Write-Host 'Normal safe mode restored.' -ForegroundColor Green
                } else {
                    Write-Warning 'A server is running, but its safe status could not be confirmed.'
                }
            }
        } catch {
            Write-Warning ('Automatic safe restart failed: ' + $_.Exception.Message)
        }
    }
    exit 1
}
