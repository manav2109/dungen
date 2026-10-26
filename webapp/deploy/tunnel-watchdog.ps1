# Runs the named Cloudflare Tunnel "diagen" (bound to dev-ai.site via
# `cloudflared tunnel route dns diagen dev-ai.site`) and restarts it if it
# ever exits. Meant to be launched by Task Scheduler at logon.
#
# Public URL is fixed: https://dev-ai.site

$ErrorActionPreference = "SilentlyContinue"

$logDir  = Join-Path $PSScriptRoot "logs"
$logFile = Join-Path $logDir "tunnel.log"
$cfExe   = Join-Path $PSScriptRoot "bin\cloudflared.exe"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $cfExe)) {
    Add-Content $logFile "[watchdog] $(Get-Date) - cloudflared.exe not found at $cfExe. Run the one-time setup in README.md first."
    exit 1
}

Set-Location $PSScriptRoot

while ($true) {
    & $cfExe tunnel --no-autoupdate run --url http://127.0.0.1:8080 diagen *>> $logFile
    Add-Content $logFile "`n[watchdog] $(Get-Date) - tunnel exited, restarting in 3s`n"
    Start-Sleep -Seconds 3
}
