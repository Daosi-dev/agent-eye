param(
    [switch]$PurgeProfile
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$VenvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    Write-Host "[1/3] Stopping Warm Daemon & Debug HUD..." -ForegroundColor Cyan
    & $VenvPy scripts\cli.py hud off 2>$null | Out-Null
    & $VenvPy scripts\cli.py daemon stop 2>$null | Out-Null
}

Write-Host "[2/3] Removing skill directory junctions safely..." -ForegroundColor Cyan
$SkillName = "antigravity-human-control"
$Targets = @(
    (Join-Path $env:USERPROFILE ".gemini\config\skills\$SkillName"),
    (Join-Path $env:USERPROFILE ".agents\skills\$SkillName"),
    (Join-Path $env:USERPROFILE ".claude\skills\$SkillName")
)

foreach ($Target in $Targets) {
    if (Test-Path $Target) {
        $item = Get-Item $Target -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            [System.IO.Directory]::Delete($Target, $false)
            Write-Host "  Unlinked -> $Target" -ForegroundColor Green
        }
    }
}

Write-Host "[3/3] Cleaning runtime state..." -ForegroundColor Cyan
$StateDir = Join-Path $env:LOCALAPPDATA "AntigravityControl"
if (Test-Path $StateDir) {
    $RuntimeFiles = @(
        "daemon.json",
        "daemon_medium.json",
        "daemon_high.json",
        "hud.json",
        "session.key",
        "session_medium.key",
        "session_high.key",
        "winrt_ocr_worker.ps1",
        "ocr_probe.bmp",
        "extract_ocr.bmp"
    )
    foreach ($f in $RuntimeFiles) {
        $fp = Join-Path $StateDir $f
        if (Test-Path $fp) { Remove-Item $fp -Force }
    }
    $SnapDir = Join-Path $StateDir "snapshots"
    if (Test-Path $SnapDir) { Remove-Item $SnapDir -Recurse -Force }
    if ($PurgeProfile) {
        $ProfileDir = Join-Path $StateDir "BrowserProfile"
        if (Test-Path $ProfileDir) { Remove-Item $ProfileDir -Recurse -Force }
    }
}

Write-Host "Uninstall complete." -ForegroundColor Green
