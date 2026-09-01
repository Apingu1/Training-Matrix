. "$PSScriptRoot\common.ps1"
Assert-Administrator
Assert-Docker
Assert-Installed

$envFile = Join-Path $script:InstallRoot ".env"
$oldPath = Get-EnvValue $envFile "DOCUMENTS_HOST_PATH"
$backupPath = Convert-FromDockerPath (Get-EnvValue $envFile "BACKUP_HOST_PATH")
$newPath = Select-Folder "Select Eaststone's controlled PDF/DOCX folder. The container receives read-only access." ($oldPath.Replace('/', '\'))
$newDockerPath = Convert-ToDockerPath $newPath
Ensure-InstallerImage
Initialize-WindowsStorageMounts -DocumentsPath $newPath -BackupPath $backupPath
$documentFileCount = Test-DockerDocumentAccess -Path $newPath
try {
    Set-EnvValue $envFile "DOCUMENTS_HOST_PATH" $newDockerPath
    Protect-SensitiveFile $envFile
    Invoke-Compose -ComposeArguments @("up", "--detach", "--force-recreate", "api")
    $healthPort = [int](Get-EnvValue $envFile "APP_HEALTH_PORT")
    Wait-LocalHealth -Port $healthPort | Out-Null
}
catch {
    Set-EnvValue $envFile "DOCUMENTS_HOST_PATH" $oldPath
    Initialize-WindowsStorageMounts -DocumentsPath (Convert-FromDockerPath $oldPath) -BackupPath $backupPath
    Protect-SensitiveFile $envFile
    Invoke-Compose -ComposeArguments @("up", "--detach", "--force-recreate", "api")
    throw
}
$oldWindowsPath = Convert-FromDockerPath $oldPath
if ((Test-IsUncPath -Path $oldWindowsPath) -and ($oldWindowsPath -ne $newPath)) {
    $oldVolumeName = Get-UncVolumeName -Purpose "documents" -Path $oldWindowsPath
    Invoke-DockerQuiet -Arguments @("volume", "rm", $oldVolumeName) | Out-Null
}
Write-OperationLog "DOCUMENT_FOLDER_CHANGED" "$oldPath -> $newDockerPath; recursive_files=$documentFileCount"
Write-Host "Controlled-document folder changed to $newPath." -ForegroundColor Green
Write-Host "$documentFileCount PDF/DOCX files were found recursively. Open Source discovery and run a controlled scan."
