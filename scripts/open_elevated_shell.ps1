$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Cmd = "Set-Location '$RepoRoot'; & '.\.venv\Scripts\python.exe' 'scripts\cli.py' doctor"
Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $Cmd)
