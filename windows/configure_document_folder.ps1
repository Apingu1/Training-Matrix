. "$PSScriptRoot\common.ps1"
Assert-Administrator
Assert-Docker
Assert-Installed

$envFile = Join-Path $script:InstallRoot ".env"
$oldPath = Get-EnvValue $envFile "DOCUMENTS_HOST_PATH"
$newPath = Select-Folder "Select Eaststone's controlled PDF/DOCX folder. The container receives read-only access." ($oldPath.Replace('/', '\'))
$newDockerPath = Convert-ToDockerPath $newPath
Set-EnvValue $envFile "DOCUMENTS_HOST_PATH" $newDockerPath
Protect-SensitiveFile $envFile
Invoke-Compose up -d --force-recreate api
$healthPort = [int](Get-EnvValue $envFile "APP_HEALTH_PORT")
Wait-LocalHealth -Port $healthPort | Out-Null
Write-OperationLog "DOCUMENT_FOLDER_CHANGED" "$oldPath -> $newDockerPath"
Write-Host "Controlled-document folder changed to $newPath." -ForegroundColor Green
Write-Host "Verify source status in System Administration and confirm existing document hashes before use."
