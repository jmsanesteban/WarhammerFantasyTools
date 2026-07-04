$ErrorActionPreference = "Stop"
. "$PSScriptRoot\config.ps1"

Write-Host "==> This will deploy to PRODUCTION ($ProdHost)" -ForegroundColor Yellow
$confirm = Read-Host "Type 'yes' to continue"
if ($confirm -ne "yes") {
    Write-Host "Aborted." -ForegroundColor Red
    exit 1
}

Write-Host "==> Deploying to PRODUCTION ($ProdHost)" -ForegroundColor Cyan

& ssh -i $SshKey $ProdHost "cd /opt/wft && git pull && docker compose up --build -d"
if ($LASTEXITCODE -ne 0) { throw "Deploy failed on production" }

Write-Host "==> Waiting for the app to respond..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri $ProdUrl -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
    Start-Sleep -Seconds 3
}

if ($ok) {
    Write-Host "==> Production is up: $ProdUrl" -ForegroundColor Green
} else {
    Write-Host "==> Production did not respond in time - check logs:" -ForegroundColor Yellow
    Write-Host "    ssh -i $SshKey $ProdHost `"docker logs wft_app --tail 50`""
}
