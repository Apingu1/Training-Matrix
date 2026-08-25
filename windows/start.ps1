. "$PSScriptRoot\common.ps1"
Assert-Administrator
Assert-Docker
Assert-Installed
$tlsFolder = Convert-FromDockerPath (Get-EnvValue (Join-Path $script:InstallRoot ".env") "TLS_CERT_HOST_PATH")
Protect-DockerTlsKey -TlsFolder $tlsFolder
Invoke-Compose -ComposeArguments @("up", "--detach")
$healthPort = [int](Get-EnvValue (Join-Path $script:InstallRoot ".env") "APP_HEALTH_PORT")
$health = Wait-LocalHealth -Port $healthPort
Write-OperationLog "START" "Version $($health.version)"
Write-Host "Eaststone Training Matrix is healthy (version $($health.version))." -ForegroundColor Green
