$ErrorActionPreference = "Stop"

$script:InstallRoot = Join-Path $env:ProgramData "Eaststone\TrainingMatrix"
$script:ComposeFile = Join-Path $script:InstallRoot "infra\docker-compose.yml"
$script:OperationsLog = Join-Path $script:InstallRoot "operations.log"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script as Administrator."
    }
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is not installed or is not available in PATH."
    }
    & docker version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker is installed but the Docker engine is not running."
    }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is required."
    }
}

function Assert-Installed {
    if (-not (Test-Path $script:ComposeFile) -or -not (Test-Path (Join-Path $script:InstallRoot ".env"))) {
        throw "Eaststone Training Matrix is not installed at $script:InstallRoot."
    }
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    Push-Location $script:InstallRoot
    try {
        & docker compose --env-file .env -f infra/docker-compose.yml @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

function Select-Folder {
    param([string]$Description, [string]$InitialDirectory = "")
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $Description
    $dialog.ShowNewFolderButton = $true
    if ($InitialDirectory -and (Test-Path $InitialDirectory)) {
        $dialog.SelectedPath = $InitialDirectory
    }
    if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "Folder selection was cancelled."
    }
    return (Resolve-Path $dialog.SelectedPath).Path
}

function Convert-ToDockerPath {
    param([string]$Path)
    return $Path.Replace("\", "/")
}

function New-RandomSecret {
    param([int]$ByteCount = 36)
    $bytes = New-Object byte[] $ByteCount
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_").TrimEnd("=")
}

function Set-EnvValue {
    param([string]$File, [string]$Name, [string]$Value)
    $lines = @(Get-Content -LiteralPath $File)
    $replacement = "$Name=`"$Value`""
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Name))=") {
            $found = $true
            $replacement
        }
        else {
            $line
        }
    }
    if (-not $found) { $updated += $replacement }
    Set-Content -LiteralPath $File -Value $updated -Encoding UTF8
}

function Get-EnvValue {
    param([string]$File, [string]$Name)
    $line = Get-Content -LiteralPath $File | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
    if (-not $line) { return $null }
    return ($line.Substring($line.IndexOf("=") + 1)).Trim().Trim('"')
}

function Write-OperationLog {
    param([string]$Action, [string]$Detail)
    $entry = "{0:u}`t{1}`t{2}`t{3}" -f (Get-Date), $env:USERNAME, $Action, $Detail
    Add-Content -LiteralPath $script:OperationsLog -Value $entry -Encoding UTF8
}

function Wait-LocalHealth {
    param([int]$Port, [int]$TimeoutSeconds = 300)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $result = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
            if ($result.status -eq "ok") { return $result }
        }
        catch { Start-Sleep -Seconds 3 }
    } while ((Get-Date) -lt $deadline)
    throw "The application did not become healthy within $TimeoutSeconds seconds."
}

function Copy-ApplicationFiles {
    param([string]$SourceRoot, [string]$DestinationRoot)
    New-Item -ItemType Directory -Path $DestinationRoot -Force | Out-Null
    $arguments = @(
        $SourceRoot,
        $DestinationRoot,
        "/MIR", "/R:2", "/W:2", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
        "/XD", ".git", ".venv", "node_modules", "dist", ".pytest_cache", ".ruff_cache", "backups", "runtime",
        "/XF", ".env", "operations.log", "INITIAL_ADMIN_CREDENTIALS.txt"
    )
    & robocopy @arguments | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Application file copy failed with robocopy exit code $LASTEXITCODE."
    }
}

function Protect-SensitiveFile {
    param([string]$Path)
    & icacls $Path /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" *> $null
}
