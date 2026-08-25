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

$workerOutput = @(Invoke-Compose -ComposeArguments @(
    "exec", "--no-TTY", "web", "sh", "-c",
    "find /usr/share/nginx/html/assets -maxdepth 1 -type f \( -name 'pdf.worker.min-*.js' -o -name 'pdf.worker.min-*.mjs' \) -print"
))
$bundledWorker = $workerOutput | Where-Object { $_ -match '/pdf\.worker\.min-[^/]+\.js$' } | Select-Object -Last 1
$externalWorker = $workerOutput | Where-Object { $_ -match '/pdf\.worker\.min-[^/]+\.mjs$' } | Select-Object -Last 1
if ($bundledWorker) {
    Write-Host "PDF viewer worker: bundled and verified ($bundledWorker)" -ForegroundColor Green
}
elseif ($externalWorker) {
    Write-Host "PDF viewer worker: legacy external module detected ($externalWorker)" -ForegroundColor Yellow
}
else {
    Write-Host "PDF viewer worker: no production worker asset found" -ForegroundColor Red
}

$updateResultFile = Join-Path $script:InstallRoot "LAST_UPDATE_RESULT.txt"
if (Test-Path -LiteralPath $updateResultFile) {
    Write-Host ""
    Write-Host "Last update result:" -ForegroundColor Cyan
    Get-Content -LiteralPath $updateResultFile | ForEach-Object { Write-Host "  $_" }
}
