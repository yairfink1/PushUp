param(
    [ValidateSet("prg", "iq", "all")]
    [string]$Target = "prg",
    [string]$Device = "fr165m"
)

$SDK_DIR = "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2"
$MONKEYC = Join-Path $SDK_DIR "bin\monkeyc.bat"
$KEY = "developer_key"

if (-not (Test-Path $MONKEYC)) {
    Write-Error "Could not locate Connect IQ compiler at: $MONKEYC"
    exit 1
}

New-Item -ItemType Directory -Force -Path "bin" | Out-Null

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Building PUSH-UP PRODUCTION App" -ForegroundColor Green
Write-Host " Jungle: monkey.jungle" -ForegroundColor Gray
Write-Host " ID: 90999ee4-98c8-4aa6-98b8-ff9980608e0b" -ForegroundColor Gray
Write-Host "==========================================" -ForegroundColor Cyan

if ($Target -eq "prg" -or $Target -eq "all") {
    Write-Host "Compiling device PRG ($Device) -> bin/PushUp.prg..." -ForegroundColor Green
    & $MONKEYC -d $Device -f monkey.jungle -o bin/PushUp.prg -y $KEY
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($Target -eq "iq" -or $Target -eq "all") {
    Write-Host "Compiling Store package IQ -> bin/PushUp.iq..." -ForegroundColor Green
    & $MONKEYC -e -f monkey.jungle -o bin/PushUp.iq -y $KEY
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "`n[OK] PushUp Production build complete!" -ForegroundColor Green
