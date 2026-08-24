. "$PSScriptRoot\common.ps1"

Assert-Administrator
Assert-Docker

if (Test-Path (Join-Path $script:InstallRoot ".env")) {
    throw "An installation already exists. Use UPDATE_WINDOWS.bat to preserve and update it."
}

$sourceRoot = Split-Path $PSScriptRoot -Parent
$documentsPath = Select-Folder "Select Eaststone's existing controlled PDF/DOCX folder. It will be mounted read-only."
$backupPath = Select-Folder "Select or create the Training Matrix database backup folder."

$portText = Read-Host "HTTPS port for users [8090]"
$appPort = if ([string]::IsNullOrWhiteSpace($portText)) { 8090 } else { [int]$portText }
if ($appPort -lt 1 -or $appPort -gt 65535) { throw "Port must be between 1 and 65535." }
$healthPort = 18090

Copy-ApplicationFiles $sourceRoot $script:InstallRoot
New-Item -ItemType Directory -Path (Join-Path $script:InstallRoot "tls") -Force | Out-Null

$databaseSecret = New-RandomSecret 42
$jwtSecret = New-RandomSecret 64
$temporaryAdminPassword = "Tm!" + (New-RandomSecret 24).Substring(0, 22) + "9aZ"
$documentsDocker = Convert-ToDockerPath $documentsPath
$backupDocker = Convert-ToDockerPath $backupPath
$tlsWindows = Join-Path $script:InstallRoot "tls"
$tlsDocker = Convert-ToDockerPath $tlsWindows

$envLines = @(
    "APP_NAME=`"Eaststone Training Matrix`"",
    "APP_VERSION=`"0.1.0`"",
    "APP_ENV=`"production`"",
    "APP_PORT=`"$appPort`"",
    "APP_HEALTH_PORT=`"$healthPort`"",
    "TZ=`"Europe/London`"",
    "POSTGRES_DB=`"training_matrix`"",
    "POSTGRES_USER=`"training_matrix`"",
    "POSTGRES_PASSWORD=`"$databaseSecret`"",
    "DATABASE_URL=`"postgresql+psycopg://training_matrix:$databaseSecret@db:5432/training_matrix`"",
    "JWT_SECRET=`"$jwtSecret`"",
    "JWT_EXPIRES_MINUTES=`"480`"",
    "SESSION_IDLE_MINUTES=`"15`"",
    "LOGIN_MAX_FAILURES=`"5`"",
    "LOGIN_LOCK_MINUTES=`"15`"",
    "INITIAL_ADMIN_USERNAME=`"admin`"",
    "INITIAL_ADMIN_PASSWORD=`"$temporaryAdminPassword`"",
    "DOCUMENTS_HOST_PATH=`"$documentsDocker`"",
    "BACKUP_HOST_PATH=`"$backupDocker`"",
    "TLS_CERT_HOST_PATH=`"$tlsDocker`"",
    "DOCUMENT_ROOT=`"/controlled-documents`"",
    "BACKUP_ROOT=`"/backups`"",
    "DOCUMENT_CACHE_ROOT=`"/document-cache`"",
    "RUNTIME_ROOT=`"/runtime`"",
    "BACKUP_TIME=`"02:30`"",
    "BACKUP_TIMEZONE=`"Europe/London`"",
    "BACKUP_RETENTION_DAYS=`"30`""
)
$envFile = Join-Path $script:InstallRoot ".env"
Set-Content -LiteralPath $envFile -Value $envLines -Encoding UTF8
Protect-SensitiveFile $envFile

$serverName = ($env:COMPUTERNAME).ToLowerInvariant()
& docker run --rm -v "${tlsDocker}:/certs" alpine/openssl req -x509 -nodes -newkey rsa:3072 -sha256 -days 825 -subj "/CN=$serverName" -addext "subjectAltName=DNS:$serverName,DNS:localhost" -keyout /certs/server.key -out /certs/server.crt
if ($LASTEXITCODE -ne 0) { throw "TLS certificate generation failed." }
Protect-SensitiveFile (Join-Path $tlsWindows "server.key")

Invoke-Compose up -d --build
$health = Wait-LocalHealth -Port $healthPort

if (-not (Get-NetFirewallRule -DisplayName "Eaststone Training Matrix HTTPS" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "Eaststone Training Matrix HTTPS" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $appPort | Out-Null
}

$credentialsFile = Join-Path $script:InstallRoot "INITIAL_ADMIN_CREDENTIALS.txt"
$credentials = @(
    "Eaststone Training Matrix - ONE-TIME INITIAL CREDENTIALS",
    "Server: https://${serverName}:$appPort",
    "Username: admin",
    "Temporary password: $temporaryAdminPassword",
    "",
    "Sign in immediately, change the password when prompted, then securely delete this file."
)
Set-Content -LiteralPath $credentialsFile -Value $credentials -Encoding UTF8
Protect-SensitiveFile $credentialsFile

$report = @(
    "Installation time: $(Get-Date -Format o)",
    "Application: $($health.application)",
    "Version: $($health.version)",
    "Server URL: https://${serverName}:$appPort",
    "Controlled documents: $documentsPath (read-only container mount)",
    "Database backups: $backupPath",
    "Database volume: training-matrix-db-data",
    "Health: $($health.status)",
    "TLS certificate SHA-256: $((Get-FileHash (Join-Path $tlsWindows 'server.crt') -Algorithm SHA256).Hash)"
)
Set-Content -LiteralPath (Join-Path $script:InstallRoot "INSTALLATION_REPORT.txt") -Value $report -Encoding UTF8
Write-OperationLog "INSTALL" "Version $($health.version); documents=$documentsPath; backups=$backupPath; port=$appPort"

Write-Host ""
Write-Host "Eaststone Training Matrix installed successfully." -ForegroundColor Green
Write-Host "URL: https://${serverName}:$appPort"
Write-Host "Initial credentials: $credentialsFile" -ForegroundColor Yellow
Write-Host "Distribute and trust tls\server.crt on authorised clients before use."
