. "$PSScriptRoot\common.ps1"
Assert-Administrator
Assert-Docker
Assert-Installed

$envFile = Join-Path $script:InstallRoot ".env"
$oldPath = Get-EnvValue $envFile "DOCUMENTS_HOST_PATH"
$newPath = Select-Folder "Select Eaststone's controlled PDF/DOCX folder. The container receives read-only access." ($oldPath.Replace('/', '\'))
$newDockerPath = Convert-ToDockerPath $newPath
Ensure-InstallerImage
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
    Protect-SensitiveFile $envFile
    Invoke-Compose -ComposeArguments @("up", "--detach", "--force-recreate", "api")
    throw
}
Write-OperationLog "DOCUMENT_FOLDER_CHANGED" "$oldPath -> $newDockerPath; recursive_files=$documentFileCount"
Write-Host "Controlled-document folder changed to $newPath." -ForegroundColor Green
Write-Host "$documentFileCount PDF/DOCX files were found recursively. Open Source discovery and run a controlled scan."
