param(
    [switch]$AllAgents,
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

Write-Host "[1/5] Setting up Python virtual environment..." -ForegroundColor Cyan
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd) {
    if (-not (Test-Path ".venv")) {
        $has312 = (& uv python list --only-installed 2>$null | Select-String "3\.12")
        if ($has312) {
            & uv venv .venv --python 3.12
        } else {
            & uv venv .venv
        }
    }
    $pkgSpec = if ($Dev) { ".[dev]" } else { "." }
    & uv pip install --python .\.venv\Scripts\python.exe -e $pkgSpec
} else {
    if (-not (Test-Path ".venv")) {
        & python -m venv .venv
    }
    $pkgSpec = if ($Dev) { ".[dev]" } else { "." }
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\pip.exe install -e $pkgSpec
}

Write-Host "[2/5] Initializing integrity-isolated local state & session key..." -ForegroundColor Cyan
$StateDir = Join-Path $env:LOCALAPPDATA "AntigravityControl"
if (-not (Test-Path $StateDir)) {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
}
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
$IntegrityTag = if ($IsAdmin) { "high" } else { "medium" }
$KeyPath = Join-Path $StateDir "session_$IntegrityTag.key"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
if (Test-Path $KeyPath) {
    $existing = ([System.IO.File]::ReadAllText($KeyPath)).Trim([char]0xFEFF, [char]0x20, [char]0x0D, [char]0x0A)
    if ($existing.Length -ge 32) {
        [System.IO.File]::WriteAllText($KeyPath, $existing, $Utf8NoBom)
    } else {
        Remove-Item $KeyPath -Force
    }
}
if (-not (Test-Path $KeyPath)) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $hex = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    [System.IO.File]::WriteAllText($KeyPath, $hex, $Utf8NoBom)
    if ($IsAdmin) {
        & icacls $KeyPath /inheritance:r /grant:r "*S-1-5-32-544:(R,W)" /grant:r "*S-1-5-18:(F)" | Out-Null
    } elseif ($env:USERNAME) {
        & icacls $KeyPath /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
    }
}

Write-Host "[3/5] Linking skill into multi-agent skill directories (Junction)..." -ForegroundColor Cyan
$SkillName = "antigravity-human-control"
$Targets = @(
    (Join-Path $env:USERPROFILE ".gemini\config\skills\$SkillName"),
    (Join-Path $env:USERPROFILE ".agents\skills\$SkillName")
)
$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
if ($AllAgents -or (Test-Path $ClaudeDir)) {
    $Targets += (Join-Path $ClaudeDir "skills\$SkillName")
}

foreach ($Target in $Targets) {
    $Parent = Split-Path -Parent $Target
    if (-not (Test-Path $Parent)) {
        New-Item -ItemType Directory -Path $Parent -Force | Out-Null
    }
    if (Test-Path $Target) {
        $item = Get-Item $Target -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            [System.IO.Directory]::Delete($Target, $false)
        } else {
            Write-Warning "Skipping existing non-junction directory: $Target"
            continue
        }
    }
    New-Item -ItemType Junction -Path $Target -Target $RepoRoot | Out-Null
    Write-Host "  Linked -> $Target" -ForegroundColor Green
}

Write-Host "[4/5] Starting Warm Daemon..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe scripts\cli.py daemon restart | Out-Host

Write-Host "[5/5] Running system diagnostics (doctor)..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe scripts\cli.py doctor | Out-Host

Write-Host "`nInstallation complete! No Admin privileges required." -ForegroundColor Green
