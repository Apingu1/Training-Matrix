. "$PSScriptRoot\common.ps1"
Assert-Administrator
Assert-Docker
Assert-Installed
Invoke-Compose stop
Write-OperationLog "STOP" "All application services stopped"
Write-Host "Eaststone Training Matrix stopped. Database volumes and files were retained." -ForegroundColor Yellow
