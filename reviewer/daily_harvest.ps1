# Daily hall-of-fame free harvest routine.
#
# NOTE (2026-09-19, midnight probe): there is NO quota reset at 00:00 local
# time.  The API uses a sliding-window rate limit -- a fresh burst gets ~5
# submits before a 429 (retry-after 900s), and a retry right after a 900s wait
# can still be 429.  Measured pattern: bursts of 1-5 runs per ~15 min window,
# fading to 0 as the day's bucket drains (~19-47 games/day observed).  The
# script stops by itself after two consecutive 429s, so it is safe to run at
# ANY time and to leave running; a long --gap (e.g. 600s) keeps a trickle
# going through the day instead of burning the burst in one go.
#
# Requires the BIGCOACH_COOKIE environment variable.
#
#   powershell -File reviewer\daily_harvest.ps1          (gap 45s, bursty)
#   powershell -File reviewer\daily_harvest.ps1 -Gap 600  (slow trickle)
#
param(
    [int]$Target = 20,
    [int]$Gap = 45
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $env:BIGCOACH_COOKIE) {
    Write-Host "set BIGCOACH_COOKIE first, e.g.:" -ForegroundColor Yellow
    Write-Host '  $env:BIGCOACH_COOKIE = "cf_clearance=...; session=..."'
    exit 2
}

$date = Get-Date -Format "yyyyMMdd"
$log  = "reviewer\out\_daily_$date.log"

Write-Host "=== daily harvest $date (target $Target, gap ${Gap}s) ==="
& .\.venv\Scripts\python.exe -u reviewer\adaptive_harvest.py `
    --target $Target --gap $Gap 2>&1 | Tee-Object -FilePath $log

Write-Host ""
Write-Host "done -> log: $log"
$n = (Get-ChildItem "reviewer\out\hof_free\*.json" |
      Where-Object { $_.Name -ne "_index.json" }).Count
Write-Host "total free reviews now: $n / 300"