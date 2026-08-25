$ErrorActionPreference = "Stop"

. "$PSScriptRoot\..\windows\common.ps1"

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "eaststone-training-matrix-windows-contract"
if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $testRoot "infra") -Force | Out-Null
Set-Content -LiteralPath (Join-Path $testRoot ".env") -Value "APP_PORT=8090" -Encoding UTF8
Set-Content -LiteralPath (Join-Path $testRoot "infra\docker-compose.yml") -Value "services: {}" -Encoding UTF8
$script:InstallRoot = $testRoot
$script:ComposeFile = Join-Path $testRoot "infra\docker-compose.yml"
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
        "Protect-DockerTlsKey",
        'Set-EnvValue $envFile "APP_VERSION" $packageVersion',
        '@("up", "--detach", "--build")'
    )) {
        if (-not $installer.Contains($requiredText)) {
            throw "Installer contract is missing: $requiredText"
        }
    }

    $common = Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\windows\common.ps1") -Raw
    foreach ($requiredText in @(
        'for ($attempt = 1; $attempt -le 3; $attempt++)',
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
