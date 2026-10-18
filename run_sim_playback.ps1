# run_sim_playback.ps1
# Full automated closed-loop simulation & parity test runner for Garmin Connect IQ Simulator
#
# Usage:
#   .\run_sim_playback.ps1
#   .\run_sim_playback.ps1 -FitFile -1
#   .\run_sim_playback.ps1 -FitFile "data\2026-10-18-15-08-27_pushup_15reps_24769590980.fit"

param(
    [string]$FitFile = "-1",
    [int]$ExtraWaitSeconds = 4
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PROJECT = $PSScriptRoot

# Resolve FIT file path using detect_pushups.py helper or negative index
$resolvedPath = python -c "import sys; import detect_pushups; print(detect_pushups.resolve_fit_path(r'$FitFile'))"
if (-not $resolvedPath -or -not (Test-Path $resolvedPath)) {
    $fullFit = [IO.Path]::GetFullPath((Join-Path $PROJECT $FitFile))
} else {
    $fullFit = [IO.Path]::GetFullPath($resolvedPath)
}

if (-not (Test-Path $fullFit)) {
    throw "Target FIT file not found: $fullFit (input: $FitFile)"
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  GARMIN CONNECT IQ SIMULATOR CLOSED-LOOP PARITY TEST" -ForegroundColor Cyan
Write-Host "  Target File: $([IO.Path]::GetFileName($fullFit))" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# -------------------------------------------------------------------------
# Step 1: Ensure Simulator is Running
# -------------------------------------------------------------------------
$simProc = Get-Process -Name simulator -ErrorAction SilentlyContinue
if (-not $simProc) {
    Write-Host "[1/6] Launching Connect IQ Simulator..." -ForegroundColor Yellow
    & "$PROJECT\scratch\launch_sim.ps1"
    Start-Sleep -Seconds 4
    $simProc = Get-Process -Name simulator -ErrorAction SilentlyContinue
}

if (-not $simProc) {
    Write-Host "Task launch yielded no process. Attempting direct fallback launch..." -ForegroundColor Yellow
    $SDK_BIN = "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin"
    $simExe = Join-Path $SDK_BIN "simulator.exe"
    Start-Process -FilePath $simExe -WorkingDirectory $SDK_BIN
    Start-Sleep -Seconds 4
    $simProc = Get-Process -Name simulator -ErrorAction SilentlyContinue
}

if (-not $simProc) {
    throw "Connect IQ Simulator could not be launched. Please verify SDK installation."
}
Write-Host "[1/6] Simulator is running (PID: $($simProc.Id))." -ForegroundColor Green

# -------------------------------------------------------------------------
# Step 2: Build and push fresh binary to simulator
# -------------------------------------------------------------------------
Write-Host "`n[2/6] Building and pushing app to simulator..." -ForegroundColor Yellow
$SDK_BIN = "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin"
& "$SDK_BIN\monkeyc.bat" -d fr165m -f (Join-Path $PROJECT "monkey.jungle") -o (Join-Path $PROJECT "bin\PushUp.prg") -y (Join-Path $PROJECT "..\PullUp\developer_key") | Out-Null
Start-Process "$SDK_BIN\monkeydo.bat" -ArgumentList "bin/PushUp.prg", "fr165m" -WindowStyle Hidden
Start-Sleep -Seconds 4
Write-Host "App pushed and initialized at Glance view." -ForegroundColor Green

# -------------------------------------------------------------------------
# Step 3: Run Interactive Automation via Scheduled Task Bridge
# -------------------------------------------------------------------------
Write-Host "`n[3/6] Automating dialog, file loading, and watch recording..." -ForegroundColor Yellow

# Calculate file duration using Python
$durationS = [int](python -c "import detect_pushups; df = detect_pushups.extract_high_freq_accel(r'$fullFit'); print(int(len(df)/100))")
$totalWait = $durationS + $ExtraWaitSeconds
Write-Host "Workout duration: $durationS seconds (Playback wait: $totalWait seconds)" -ForegroundColor Cyan

$workerScript = Join-Path $PROJECT "sim_playback_worker.ps1"
$doneFile = Join-Path $PROJECT "scratch\playback_done.txt"
Remove-Item $doneFile -ErrorAction SilentlyContinue

# Create a small launcher wrapper to capture stdout/stderr to log
$wrapperScript = Join-Path $PROJECT "scratch\run_playback_wrapper.ps1"
$workerLog = Join-Path $PROJECT "scratch\worker_output.log"
Remove-Item $workerLog -ErrorAction SilentlyContinue

$wrapperCode = "& `"$workerScript`" -FitFile `"$fullFit`" -DurationSeconds $durationS -ExtraWaitSeconds $ExtraWaitSeconds *>&1 | Out-File `"$workerLog`" -Encoding utf8"
[IO.File]::WriteAllText($wrapperScript, $wrapperCode, [Text.Encoding]::UTF8)

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapperScript`""
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "CIQ_RunPlayback_PushUp" -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "CIQ_RunPlayback_PushUp"

Write-Host "Playback in progress (~$($totalWait + 12)s total)..." -ForegroundColor Yellow
$maxWait = $totalWait + 40
for ($i = 0; $i -lt $maxWait; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $doneFile) { break }
}
Unregister-ScheduledTask -TaskName "CIQ_RunPlayback_PushUp" -Confirm:$false -ErrorAction SilentlyContinue

if (Test-Path $workerLog) {
    Get-Content $workerLog | ForEach-Object { Write-Host "  [Worker] $_" -ForegroundColor DarkGray }
}

if (-not (Test-Path $doneFile)) {
    throw "Worker did not complete within expected timeout ($maxWait seconds)."
}
Write-Host "Simulation playback completed successfully!" -ForegroundColor Green

# -------------------------------------------------------------------------
# Step 4: Parse Simulator Output Activity FIT
# -------------------------------------------------------------------------
Write-Host "`n[4/6] Parsing Simulator Output Activity..." -ForegroundColor Yellow
$activitiesDir = "$env:LOCALAPPDATA\Temp\com.garmin.connectiq\GARMIN\Activities"
$latestActivity = Get-ChildItem -Path "$activitiesDir\*.fit" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$simReps = $null
if ($latestActivity) {
    Write-Host "Latest generated FIT: $($latestActivity.FullName) ($($latestActivity.LastWriteTime))" -ForegroundColor Cyan
    $simData = python (Join-Path $PROJECT "read_fit_reps.py") $latestActivity.FullName
    $simData | ForEach-Object { Write-Host $_ }
    $repLine = $simData | Where-Object { $_ -like "*Total Reps:*" -or $_ -like "*reps=*" }
    if ($repLine) {
        $m = [regex]::Match($repLine, '\d+')
        if ($m.Success) {
            $simReps = [int]$m.Value
        }
    }
} else {
    Write-Warning "No activity file found in $activitiesDir"
}

# -------------------------------------------------------------------------
# Step 5: Run Offline Python Analysis on Input File
# -------------------------------------------------------------------------
Write-Host "`n[5/6] Running Offline Python Detector on Input File..." -ForegroundColor Yellow
$offlineData = python (Join-Path $PROJECT "detect_pushups.py") $fullFit
$offlineData | ForEach-Object { Write-Host $_ }
$offlineRepLine = $offlineData | Where-Object { $_ -like "Detected : *" }
$offlineReps = $null
if ($offlineRepLine) {
    $m = [regex]::Match($offlineRepLine, 'Detected\s*:\s*(\d+)')
    if ($m.Success) {
        $offlineReps = [int]$m.Groups[1].Value
    }
}

# -------------------------------------------------------------------------
# Step 6: Parity Verification & Comparison
# -------------------------------------------------------------------------
Write-Host "`n[6/6] Parity Verification Summary:" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Input FIT File           : $([IO.Path]::GetFileName($fullFit))"
Write-Host "Simulator Detected Reps  : $simReps"
Write-Host "Offline Python Reps      : $offlineReps"
Write-Host "Mid-Workout Screenshot   : $PROJECT\mid_workout_reps.png"
Write-Host "Final Screenshot         : $PROJECT\final_set_complete.png"

if ($simReps -ne $null -and $offlineReps -ne $null -and $simReps -eq $offlineReps) {
    Write-Host "`n>>> RESULT: 100% PARITY CONFIRMED! (Simulator == Offline == $simReps reps) <<<" -ForegroundColor Green
} else {
    Write-Warning "Parity discrepancy detected! Sim: $simReps, Offline: $offlineReps"
}
Write-Host "============================================================" -ForegroundColor Cyan
