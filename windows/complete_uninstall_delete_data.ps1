. "$PSScriptRoot\common.ps1"
Assert-Administrator
Assert-Docker
Assert-Installed

Write-Host "DANGER: this permanently deletes Training Matrix database volumes and installed application files." -ForegroundColor Red
Write-Host "The external controlled-document and backup folders are not deleted."
$first = Read-Host "Type DELETE TRAINING MATRIX DATABASE"
if ($first -cne "DELETE TRAINING MATRIX DATABASE") { throw "First confirmation did not match; nothing was deleted." }
$second = Read-Host "Type the server name $env:COMPUTERNAME"
if ($second -cne $env:COMPUTERNAME) { throw "Server-name confirmation did not match; nothing was deleted." }

Invoke-Compose -ComposeArguments @("down", "--volumes", "--remove-orphans", "--rmi", "local")
$installedEnv = Join-Path $script:InstallRoot ".env"
$documentsPath = Convert-FromDockerPath (Get-EnvValue $installedEnv "DOCUMENTS_HOST_PATH")
$backupPath = Convert-FromDockerPath (Get-EnvValue $installedEnv "BACKUP_HOST_PATH")
if (Test-IsUncPath -Path $documentsPath) {
    Invoke-DockerQuiet -Arguments @("volume", "rm", (Get-UncVolumeName -Purpose "documents" -Path $documentsPath)) | Out-Null
}
if (Test-IsUncPath -Path $backupPath) {
    Invoke-DockerQuiet -Arguments @("volume", "rm", (Get-UncVolumeName -Purpose "backups" -Path $backupPath)) | Out-Null
}
if (Get-NetFirewallRule -DisplayName "Eaststone Training Matrix HTTPS" -ErrorAction SilentlyContinue) {
    Remove-NetFirewallRule -DisplayName "Eaststone Training Matrix HTTPS"
}
$parent = Split-Path $script:InstallRoot -Parent
$tombstone = Join-Path $parent "TrainingMatrix_DELETED_$(Get-Date -Format 'yyyyMMdd_HHmmss').txt"
Set-Content -LiteralPath $tombstone -Value "Deleted by $env:USERNAME at $(Get-Date -Format o). External controlled documents and backups were retained." -Encoding UTF8
Remove-Item -LiteralPath $script:InstallRoot -Recurse -Force
Write-Host "Training Matrix database volumes and installed files were deleted." -ForegroundColor Red
Write-Host "External documents and database backup files remain in their separately configured folders."
