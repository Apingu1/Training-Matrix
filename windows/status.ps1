. "$PSScriptRoot\common.ps1"
Assert-Docker
Assert-Installed
Invoke-Compose -ComposeArguments @("ps")
$healthPort = [int](Get-EnvValue (Join-Path $script:InstallRoot ".env") "APP_HEALTH_PORT")
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$healthPort/health" -TimeoutSec 5
    Write-Host "Health: $($health.status); version $($health.version); database $($health.database)" -ForegroundColor Green
}
catch {
    Write-Host "Health endpoint unavailable: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
