. "$PSScriptRoot\common.ps1"
Assert-Administrator
Assert-Docker
Assert-Installed

$confirmation = Read-Host "Type STOP AND UNINSTALL APP to remove containers while retaining all data"
if ($confirmation -cne "STOP AND UNINSTALL APP") { throw "Confirmation did not match; nothing was removed." }
Invoke-Compose -ComposeArguments @("down")
if (Get-NetFirewallRule -DisplayName "Eaststone Training Matrix HTTPS" -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -DisplayName "Eaststone Training Matrix HTTPS"
}
Write-OperationLog "UNINSTALL_APP" "Containers/network removed; database volumes, installation files, documents and backups retained"
Write-Host "Application containers were removed." -ForegroundColor Yellow
Write-Host "Database volumes, installed files, controlled documents and backup files were retained."
