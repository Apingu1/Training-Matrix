. "$PSScriptRoot\common.ps1"

$updateLogFile = Join-Path $script:InstallRoot "UPDATE_LOG.txt"
$updateResultFile = Join-Path $script:InstallRoot "LAST_UPDATE_RESULT.txt"
$transcriptStarted = $false
$releaseArchive = $null
$packageVersion = "unknown"
$startedAt = Get-Date

try {
    Assert-Administrator
    Assert-Docker
    Assert-Installed

    Start-Transcript -LiteralPath $updateLogFile -Append | Out-Null
    $transcriptStarted = $true

    $sourceRoot = Split-Path $PSScriptRoot -Parent
    $packageVersionFile = Join-Path $sourceRoot "APP_VERSION"
    if (-not (Test-Path -LiteralPath $packageVersionFile)) {
        throw "The extracted release is missing APP_VERSION. Download a complete commercial package."
    }
    $packageVersion = (Get-Content -LiteralPath $packageVersionFile -Raw).Trim()
    if ($packageVersion -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
        throw "The package APP_VERSION value is invalid."
    }
    $sourceFull = (Resolve-Path $sourceRoot).Path.TrimEnd('\')
    $installFull = (Resolve-Path $script:InstallRoot).Path.TrimEnd('\')
    if ($sourceFull -eq $installFull) {
        throw "Run UPDATE_WINDOWS.bat from an extracted new release, not from the installed application folder."
    }

    Set-Content -LiteralPath $updateResultFile -Value @(
        "Status: IN PROGRESS",
        "Target version: $packageVersion",
        "Started: $($startedAt.ToString('o'))",
        "Source: $sourceFull"
    ) -Encoding UTF8

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $releaseArchive = Join-Path (Split-Path $script:InstallRoot -Parent) "TrainingMatrixReleases\$timestamp"
    New-Item -ItemType Directory -Path $releaseArchive -Force | Out-Null
    Copy-ApplicationFiles $script:InstallRoot $releaseArchive

    Write-Host "Creating a verified pre-update database backup..."
    Invoke-Compose -ComposeArguments @("exec", "--no-TTY", "api", "python", "-m", "app.cli", "create-backup", "--type", "PRE_UPDATE", "--reason", "Automatic safety backup before server update $timestamp")
    Invoke-Compose -ComposeArguments @("stop", "web", "api", "backup-scheduler")

    Copy-ApplicationFiles $sourceRoot $script:InstallRoot
    $installedEnv = Join-Path $script:InstallRoot ".env"
    Set-EnvValue $installedEnv "APP_VERSION" $packageVersion
    Protect-SensitiveFile $installedEnv
    $tlsFolder = Convert-FromDockerPath (Get-EnvValue $installedEnv "TLS_CERT_HOST_PATH")
    Protect-DockerTlsKey -TlsFolder $tlsFolder
    Invoke-Compose -ComposeArguments @("up", "--detach", "--build")

    $healthPort = [int](Get-EnvValue $installedEnv "APP_HEALTH_PORT")
    $health = Wait-LocalHealth -Port $healthPort
    if ([string]$health.version -ne $packageVersion) {
        throw "The server reported version $($health.version), but the update package is version $packageVersion."
    }

    $workerOutput = @(Invoke-Compose -ComposeArguments @(
        "exec", "--no-TTY", "web", "sh", "-c",
        "find /usr/share/nginx/html/assets -maxdepth 1 -type f -name 'pdf.worker.min-*.js' -print -quit"
    ))
    $workerAsset = $workerOutput | Where-Object { $_ -match '/pdf\.worker\.min-[^/]+\.js$' } | Select-Object -Last 1
    if ([string]::IsNullOrWhiteSpace([string]$workerAsset)) {
        throw "The rebuilt web container does not contain the bundled PDF.js worker."
    }

    $completedAt = Get-Date
    Set-Content -LiteralPath $updateResultFile -Value @(
        "Status: SUCCESS",
        "Version: $($health.version)",
        "Started: $($startedAt.ToString('o'))",
        "Completed: $($completedAt.ToString('o'))",
        "Health: $($health.status)",
        "PDF worker: $workerAsset",
        "Prior application files: $releaseArchive",
        "Update log: $updateLogFile"
    ) -Encoding UTF8
    Write-OperationLog "UPDATE" "Updated successfully to $($health.version); pdf_worker=$workerAsset; prior application files=$releaseArchive"

    Write-Host ""
    Write-Host "Update complete. Version $($health.version) is healthy." -ForegroundColor Green
    Write-Host "Bundled PDF worker verified: $workerAsset" -ForegroundColor Green
    Write-Host "Update result: $updateResultFile"
    Write-Host "Prior application files retained at $releaseArchive"
}
catch {
    $message = $_.Exception.Message
    if (Test-Path -LiteralPath $script:InstallRoot) {
        try {
            Set-Content -LiteralPath $updateResultFile -Value @(
                "Status: FAILED",
                "Target version: $packageVersion",
                "Started: $($startedAt.ToString('o'))",
                "Failed: $((Get-Date).ToString('o'))",
                "Error: $message",
                "Prior application files: $releaseArchive",
                "Update log: $updateLogFile"
            ) -Encoding UTF8
        }
        catch {}
        try { Write-OperationLog "UPDATE_FAILED" $message } catch {}
    }

    Write-Host ""
    Write-Host "Update failed: $message" -ForegroundColor Red
    Write-Host "The database backup and prior application files were retained." -ForegroundColor Yellow
    if ($releaseArchive) { Write-Host "Archive: $releaseArchive" }
    if (Test-Path -LiteralPath $updateResultFile) { Write-Host "Update result: $updateResultFile" }
    throw
}
finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
}
