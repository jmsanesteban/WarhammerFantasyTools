$ErrorActionPreference = "Stop"
. "$PSScriptRoot\config.ps1"

Write-Host "==> Deploying to STAGING ($StagingHost)" -ForegroundColor Cyan

& ssh -i $SshKey $StagingHost "cd /opt/wft && git pull && docker compose up --build -d"
if ($LASTEXITCODE -ne 0) { throw "Deploy failed on staging" }

Write-Host "==> Waiting for the app to respond..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri $StagingUrl -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
    Start-Sleep -Seconds 3
}

if ($ok) {
    Write-Host "==> Staging is up: $StagingUrl" -ForegroundColor Green
} else {
    Write-Host "==> Staging did not respond in time - check logs:" -ForegroundColor Yellow
    Write-Host "    ssh -i $SshKey $StagingHost `"docker logs wft_app --tail 50`""
}
