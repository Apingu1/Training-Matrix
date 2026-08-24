. "$PSScriptRoot\common.ps1"

Assert-Administrator
Assert-Docker
Assert-Installed

$sourceRoot = Split-Path $PSScriptRoot -Parent
$sourceFull = (Resolve-Path $sourceRoot).Path.TrimEnd('\')
$installFull = (Resolve-Path $script:InstallRoot).Path.TrimEnd('\')
if ($sourceFull -eq $installFull) {
    throw "Run UPDATE_WINDOWS.bat from an extracted new release, not from the installed application folder."
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$releaseArchive = Join-Path (Split-Path $script:InstallRoot -Parent) "TrainingMatrixReleases\$timestamp"
New-Item -ItemType Directory -Path $releaseArchive -Force | Out-Null
Copy-ApplicationFiles $script:InstallRoot $releaseArchive

Write-Host "Creating a verified pre-update database backup..."
Invoke-Compose exec -T api python -m app.cli create-backup --type PRE_UPDATE --reason "Automatic safety backup before server update $timestamp"
Invoke-Compose stop web api backup-scheduler

try {
    Copy-ApplicationFiles $sourceRoot $script:InstallRoot
    Invoke-Compose up -d --build
    $healthPort = [int](Get-EnvValue (Join-Path $script:InstallRoot ".env") "APP_HEALTH_PORT")
    $health = Wait-LocalHealth -Port $healthPort
    Write-OperationLog "UPDATE" "Updated successfully to $($health.version); prior application files=$releaseArchive"
    Write-Host "Update complete. Version $($health.version) is healthy." -ForegroundColor Green
    Write-Host "Prior application files retained at $releaseArchive"
}
catch {
    Write-OperationLog "UPDATE_FAILED" $_.Exception.Message
    Write-Host "Update failed. The database backup and prior application files were retained." -ForegroundColor Red
    Write-Host "Archive: $releaseArchive"
    throw
}
