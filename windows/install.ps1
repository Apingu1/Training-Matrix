. "$PSScriptRoot\common.ps1"

Assert-Administrator
Assert-Docker

$sourceRoot = Split-Path $PSScriptRoot -Parent
$packageVersionFile = Join-Path $sourceRoot "APP_VERSION"
$packageVersion = if (Test-Path -LiteralPath $packageVersionFile) { (Get-Content -LiteralPath $packageVersionFile -Raw).Trim() } else { "0.2.1" }
if ($packageVersion -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "The package APP_VERSION value is invalid."
}
$envFile = Join-Path $script:InstallRoot ".env"
$reportFile = Join-Path $script:InstallRoot "INSTALLATION_REPORT.txt"
$logFile = Join-Path $script:InstallRoot "INSTALLATION_LOG.txt"
New-Item -ItemType Directory -Path $script:InstallRoot -Force | Out-Null
$transcriptStarted = $false

try {
    Start-Transcript -LiteralPath $logFile -Append | Out-Null
    $transcriptStarted = $true

    $resume = Test-Path -LiteralPath $envFile
    if ($resume -and (Test-Path -LiteralPath $reportFile)) {
        throw "A completed installation already exists. Use UPDATE_WINDOWS.bat to preserve and update it."
    }

    if ($resume) {
        Write-Host "An incomplete installation was detected." -ForegroundColor Yellow
        Write-Host "The existing database password, administrator password, folder paths and port will be preserved."
        $confirmation = Read-Host "Type RESUME INSTALLATION to continue"
        if ($confirmation -cne "RESUME INSTALLATION") {
            throw "Resume confirmation did not match. No installation data was changed."
        }
        Copy-ApplicationFiles $sourceRoot $script:InstallRoot
        $documentsPath = Convert-FromDockerPath (Get-EnvValue $envFile "DOCUMENTS_HOST_PATH")
        $backupPath = Convert-FromDockerPath (Get-EnvValue $envFile "BACKUP_HOST_PATH")
        $tlsWindows = Convert-FromDockerPath (Get-EnvValue $envFile "TLS_CERT_HOST_PATH")
        $appPort = [int](Get-EnvValue $envFile "APP_PORT")
        $healthPort = [int](Get-EnvValue $envFile "APP_HEALTH_PORT")
        $temporaryAdminPassword = Get-EnvValue $envFile "INITIAL_ADMIN_PASSWORD"
        Set-EnvValue $envFile "APP_VERSION" $packageVersion
        Protect-SensitiveFile $envFile
        Write-Host "Resuming the existing partial installation on HTTPS port $appPort." -ForegroundColor Cyan
    }
    else {
        $documentsPath = Select-Folder "Select Eaststone's approved controlled PDF/DOCX root folder. Every nested subfolder will be available read-only."
        $backupPath = Select-Folder "Select or create the Training Matrix database backup folder." -AllowCreate $true

        $portText = Read-Host "HTTPS port for users [8090]"
        $appPort = if ([string]::IsNullOrWhiteSpace($portText)) { 8090 } else { [int]$portText }
        if ($appPort -lt 1 -or $appPort -gt 65535) { throw "Port must be between 1 and 65535." }
        $healthPort = 18090

        Copy-ApplicationFiles $sourceRoot $script:InstallRoot
        $tlsWindows = Join-Path $script:InstallRoot "tls"
        New-Item -ItemType Directory -Path $tlsWindows -Force | Out-Null

        $databaseSecret = New-RandomSecret 42
        $jwtSecret = New-RandomSecret 64
        $temporaryAdminPassword = "Tm!" + (New-RandomSecret 24).Substring(0, 22) + "9aZ"
        $documentsDocker = Convert-ToDockerPath $documentsPath
        $backupDocker = Convert-ToDockerPath $backupPath
        $tlsDocker = Convert-ToDockerPath $tlsWindows

        $envLines = @(
            "APP_NAME=`"Eaststone Training Matrix`"",
            "APP_VERSION=`"$packageVersion`"",
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
        Set-Content -LiteralPath $envFile -Value $envLines -Encoding UTF8
        Protect-SensitiveFile $envFile
    }

    $documentsPath = Resolve-FolderPath -Path $documentsPath
    $backupPath = Resolve-FolderPath -Path $backupPath -AllowCreate $true
    New-Item -ItemType Directory -Path $tlsWindows -Force | Out-Null
    Ensure-InstallerImage
    $documentFileCount = Test-DockerDocumentAccess -Path $documentsPath
    Test-DockerBackupAccess -Path $backupPath

    $serverName = ($env:COMPUTERNAME).ToLowerInvariant()
    $certificatePath = Join-Path $tlsWindows "server.crt"
    $keyPath = Join-Path $tlsWindows "server.key"
    if (-not (Test-Path -LiteralPath $certificatePath) -or -not (Test-Path -LiteralPath $keyPath)) {
        Write-Host "Generating the server TLS certificate..." -ForegroundColor Cyan
        $tlsDocker = Convert-ToDockerPath $tlsWindows
        & docker run --rm -v "${tlsDocker}:/certs" alpine/openssl:latest req -x509 -nodes -newkey rsa:3072 -sha256 -days 825 -subj "/CN=$serverName" -addext "subjectAltName=DNS:$serverName,DNS:localhost" -keyout /certs/server.key -out /certs/server.crt
        if ($LASTEXITCODE -ne 0) { throw "TLS certificate generation failed." }
    }
    Protect-DockerTlsKey -TlsFolder $tlsWindows

    Write-Host "Building and starting the Training Matrix in detached mode..." -ForegroundColor Cyan
    Invoke-Compose -ComposeArguments @("up", "--detach", "--build")
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
        "PDF/DOCX files found recursively during preflight: $documentFileCount",
        "Database backups: $backupPath",
        "Database volume: training-matrix-db-data",
        "Health: $($health.status)",
        "TLS certificate SHA-256: $((Get-FileHash $certificatePath -Algorithm SHA256).Hash)"
    )
    Set-Content -LiteralPath $reportFile -Value $report -Encoding UTF8
    Write-OperationLog "INSTALL" "Version $($health.version); documents=$documentsPath; backups=$backupPath; port=$appPort; recursive_files=$documentFileCount"

    Write-Host ""
    Write-Host "Eaststone Training Matrix installed successfully." -ForegroundColor Green
    Write-Host "URL: https://${serverName}:$appPort"
    Write-Host "Initial credentials: $credentialsFile" -ForegroundColor Yellow
    Write-Host "Installation report: $reportFile"
    Write-Host "Distribute and trust tls\server.crt on authorised clients before use."
}
catch {
    Write-Host ""
    Write-Host "Installation did not complete: $($_.Exception.Message)" -ForegroundColor Red
    if (Test-Path -LiteralPath $envFile) {
        Write-Host "The partial installation was preserved safely. Rerun this installer and choose RESUME INSTALLATION after correcting the reported issue." -ForegroundColor Yellow
    }
    throw
}
finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
