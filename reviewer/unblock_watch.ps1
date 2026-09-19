# Probe review.bigcoach.work until the IP_BLACKLISTED block lifts. (PS 5.1 compatible)
# Writes one line per probe to _unblock_watch.log; exits 0 when unblocked.
$log = Join-Path $PSScriptRoot "out\_unblock_watch.log"
$url = 'https://review.bigcoach.work/api/v2/tasks/4a99a233b1f58be0/result'
$headers = @{ 'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36' }
while ($true) {
    $msg = ''
    try {
        $r = Invoke-WebRequest -Uri $url -Headers $headers -TimeoutSec 30 -UseBasicParsing
        $body = $r.Content
        if ($r.StatusCode -eq 200) {
            Add-Content $log "UNBLOCKED $(Get-Date -Format o) HTTP 200"
            exit 0
        } elseif ($body -match 'IP_BLACKLISTED') {
            $msg = "blocked $(Get-Date -Format o)"
        } else {
            Add-Content $log "changed $(Get-Date -Format o) HTTP $($r.StatusCode) body=$($body.Substring(0, [Math]::Min(120, $body.Length)))"
            exit 1
        }
    } catch {
        $code = $null
        try { $code = $_.Exception.Response.StatusCode.value__ } catch {}
        $detail = ''
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $detail = $_.ErrorDetails.Message }
        if ($code -eq 403 -and $detail -match 'IP_BLACKLISTED') {
            $msg = "blocked $(Get-Date -Format o)"
        } elseif ($code -eq 403) {
            Add-Content $log "still-403 $(Get-Date -Format o) body=$($detail.Substring(0, [Math]::Min(120, $detail.Length)))"
        } else {
            Add-Content $log "probe-error $(Get-Date -Format o) code=$code $($_.Exception.Message)"
            exit 1
        }
    }
    if ($msg) { Add-Content $log $msg }
    Start-Sleep -Seconds 900
}