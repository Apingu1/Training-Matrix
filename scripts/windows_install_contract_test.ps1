$ErrorActionPreference = "Stop"

. "$PSScriptRoot\..\windows\common.ps1"

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "eaststone-training-matrix-windows-contract"
if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $testRoot "infra") -Force | Out-Null
Set-Content -LiteralPath (Join-Path $testRoot ".env") -Value "APP_PORT=8090" -Encoding UTF8
Set-Content -LiteralPath (Join-Path $testRoot "infra\docker-compose.yml") -Value "services: {}" -Encoding UTF8
$script:InstallRoot = $testRoot
$script:ComposeFile = Join-Path $testRoot "infra\docker-compose.yml"
$script:ComposeWindowsOverrideFile = Join-Path $testRoot "infra\docker-compose.windows.generated.yml"
$script:capturedDockerArguments = @()

function docker {
    $script:capturedDockerArguments = @($args)
    $global:LASTEXITCODE = 0
}

try {
    Invoke-Compose -ComposeArguments @("up", "--detach", "--build")
    $expected = @("compose", "--env-file", ".env", "-f", "infra/docker-compose.yml", "up", "--detach", "--build")
    if (($script:capturedDockerArguments -join "|") -ne ($expected -join "|")) {
        throw "Invoke-Compose altered Docker arguments. Actual: $($script:capturedDockerArguments -join ' ')"
    }

    $converted = Convert-ToDockerPath "C:\Eaststone\Approved Documents"
    if ($converted -ne "C:/Eaststone/Approved Documents") {
        throw "Windows-to-Docker path conversion failed: $converted"
    }
    $roundTrip = Convert-FromDockerPath $converted
    if ($roundTrip -ne "C:\Eaststone\Approved Documents") {
        throw "Docker-to-Windows path conversion failed: $roundTrip"
    }
    $uncConverted = Convert-ToDockerPath "\\fileserver\quality\Approved Documents"
    if ($uncConverted -ne "//fileserver/quality/Approved Documents") {
        throw "UNC-to-Docker path conversion failed: $uncConverted"
    }
    if (-not (Test-IsUncPath "\\fileserver\quality\Approved Documents")) {
        throw "UNC detection failed"
    }
    $uncParts = Split-UncPath "\\fileserver\quality\Approved Documents\SOPs"
    if ($uncParts.Device -ne "//fileserver/quality" -or $uncParts.Relative -ne "Approved Documents/SOPs") {
        throw "UNC parsing failed"
    }
    $documentVolume = Get-UncVolumeName -Purpose "documents" -Path "\\fileserver\quality\Approved Documents"
    if ($documentVolume -notmatch '^training-matrix-documents-unc-v2-[0-9a-f]{12}$') {
        throw "Deterministic UNC volume name is invalid: $documentVolume"
    }
    Write-WindowsComposeOverride -DocumentsPath "\\fileserver\quality\Approved Documents" -BackupPath "\\fileserver\backups\Training Matrix"
    $override = Get-Content -LiteralPath $script:ComposeWindowsOverrideFile -Raw
    foreach ($requiredText in @("read_only: true", "target: /controlled-documents", "target: /backups", "subpath:", "Approved Documents", "external: true", $documentVolume)) {
        if (-not $override.Contains($requiredText)) { throw "Generated UNC Compose override is missing: $requiredText" }
    }
    Invoke-Compose -ComposeArguments @("config")
    $expectedOverrideArgument = "infra/docker-compose.windows.generated.yml"
    if (-not ($script:capturedDockerArguments -contains $expectedOverrideArgument)) {
        throw "Invoke-Compose did not load the generated Windows UNC override"
    }
    if ((Resolve-FolderPath -Path $testRoot) -ne $testRoot) {
        throw "Existing folder resolution failed"
    }

    $windowsScripts = Get-ChildItem (Join-Path $PSScriptRoot "..\windows") -Filter *.ps1
    foreach ($scriptFile in $windowsScripts) {
        $content = Get-Content -LiteralPath $scriptFile.FullName -Raw
        if ($scriptFile.Name -ne "common.ps1" -and $content -match 'Invoke-Compose\s+(?!-ComposeArguments)') {
            throw "$($scriptFile.Name) invokes Docker Compose without the explicit argument array"
        }
    }

    $installer = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\windows\install.ps1") -Raw
    foreach ($requiredText in @(
        "RESUME INSTALLATION",
        "Test-DockerDocumentAccess",
        "Test-DockerBackupAccess",
        "Initialize-WindowsStorageMounts",
        "Protect-DockerTlsKey",
        'Set-EnvValue $envFile "APP_VERSION" $packageVersion',
        '@("up", "--detach", "--build")'
    )) {
        if (-not $installer.Contains($requiredText)) {
            throw "Installer contract is missing: $requiredText"
        }
    }

    $updater = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\windows\update.ps1") -Raw
    foreach ($requiredText in @(
        "LAST_UPDATE_RESULT.txt",
        "UPDATE_LOG.txt",
        'if ([string]$health.version -ne $packageVersion)',
        "pdf.worker.min-*.js",
        "Status: SUCCESS",
        "Status: FAILED"
    )) {
        if (-not $updater.Contains($requiredText)) {
            throw "Updater contract is missing: $requiredText"
        }
    }

    $updateLauncher = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\UPDATE_WINDOWS.bat") -Raw
    foreach ($requiredText in @("UPDATE_EXIT_CODE", "LAST_UPDATE_RESULT.txt", "pause")) {
        if (-not $updateLauncher.Contains($requiredText)) {
            throw "Update launcher contract is missing: $requiredText"
        }
    }

    $common = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\windows\common.ps1") -Raw
    foreach ($requiredText in @(
        'for ($attempt = 1; $attempt -le 3; $attempt++)',
        'Invoke-DockerQuiet -Arguments @("image", "inspect", "alpine/openssl:latest")',
        'type=cifs',
        'volume-subpath=',
        '"runtime", "tls"',
        '"*S-1-5-32-545:(R)"'
    )) {
        if (-not $common.Contains($requiredText)) {
            throw "Common installer contract is missing: $requiredText"
        }
    }

    Write-Host "Windows installer contract tests passed." -ForegroundColor Green
}
finally {
    Remove-Item Function:\docker -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
