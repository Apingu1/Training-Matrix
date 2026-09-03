$ErrorActionPreference = "Stop"

$script:InstallRoot = Join-Path $env:ProgramData "Eaststone\TrainingMatrix"
$script:ComposeFile = Join-Path $script:InstallRoot "infra\docker-compose.yml"
$script:ComposeWindowsOverrideFile = Join-Path $script:InstallRoot "infra\docker-compose.windows.generated.yml"
$script:OperationsLog = Join-Path $script:InstallRoot "operations.log"
$script:SmbCredentials = @{}

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
    param([Parameter(Mandatory = $true)][string[]]$ComposeArguments)
    Push-Location $script:InstallRoot
    try {
        $composeFiles = @("-f", "infra/docker-compose.yml")
        if (Test-Path -LiteralPath $script:ComposeWindowsOverrideFile) {
            $composeFiles += @("-f", "infra/docker-compose.windows.generated.yml")
        }
        & docker compose --env-file .env @composeFiles @ComposeArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

function Convert-MappedDriveToUnc {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ($Path -notmatch '^(?<Drive>[A-Za-z]):(?<Tail>[\\/].*)?$') {
        return $Path
    }
    $drive = $Matches.Drive.ToUpperInvariant()
    $tail = if ($Matches.Tail) { $Matches.Tail.Replace('/', '\') } else { '' }
    $registryPath = "Registry::HKEY_CURRENT_USER\Network\$drive"
    try {
        $remote = (Get-ItemProperty -LiteralPath $registryPath -Name RemotePath -ErrorAction Stop).RemotePath
        if ($remote) {
            $unc = $remote.TrimEnd('\') + $tail
            Write-Host "Resolved mapped drive ${drive}: to $unc" -ForegroundColor Cyan
            return $unc
        }
    }
    catch {
        # The mapping may be unavailable to the elevated token; a pasted UNC path remains supported.
    }
    return $Path
}

function Resolve-FolderPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [bool]$AllowCreate = $false
    )
    $trimmed = $Path.Trim().Trim('"')
    $candidate = Convert-MappedDriveToUnc -Path $trimmed
    if (-not (Test-Path -LiteralPath $candidate)) {
        if (-not $AllowCreate) {
            throw "Folder not found: $candidate. For mapped drives hidden by Windows elevation, enter the full UNC path such as \\server\share\Approved Documents."
        }
        New-Item -ItemType Directory -Path $candidate -Force | Out-Null
    }
    $item = Get-Item -LiteralPath $candidate -ErrorAction Stop
    if (-not $item.PSIsContainer) {
        throw "The selected path is not a folder: $candidate"
    }
    return $item.FullName
}

function Select-Folder {
    param(
        [string]$Description,
        [string]$InitialDirectory = "",
        [bool]$AllowCreate = $false
    )
    Write-Host ""
    Write-Host $Description -ForegroundColor Cyan
    Write-Host "You may paste a local path or a UNC network path (for example \\server\share\Approved Documents)."
    Write-Host "Mapped drives may be hidden from elevated Windows dialogs; a visible drive letter is automatically resolved to UNC where possible."
    $entered = Read-Host "Enter the full folder path, or press Enter to browse"
    if (-not [string]::IsNullOrWhiteSpace($entered)) {
        return Resolve-FolderPath -Path $entered -AllowCreate $AllowCreate
    }
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
    return Resolve-FolderPath -Path $dialog.SelectedPath -AllowCreate $AllowCreate
}

function Convert-ToDockerPath {
    param([string]$Path)
    return $Path.Replace("\", "/")
}

function Convert-FromDockerPath {
    param([string]$Path)
    return $Path.Replace("/", "\")
}

function Test-IsUncPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return $Path -match '^\\\\[^\\]+\\[^\\]+'
}

function Split-UncPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ($Path -notmatch '^\\\\(?<Server>[^\\]+)\\(?<Share>[^\\]+)(?:\\(?<Relative>.*))?$') {
        throw "Invalid UNC path: $Path. Use a path in the form \\server\share\folder."
    }
    return [pscustomobject]@{
        Server = $Matches.Server
        Share = $Matches.Share
        Relative = if ($Matches.Relative) { $Matches.Relative.Trim('\').Replace('\', '/') } else { '' }
        Device = "//$($Matches.Server)/$($Matches.Share)"
    }
}

function Invoke-DockerQuiet {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell can promote native stderr to a terminating NativeCommandError
        # when the script-wide preference is Stop. Exit codes are checked explicitly here.
        $ErrorActionPreference = "Continue"
        & docker @Arguments *> $null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-SmbCredentialForServer {
    param([Parameter(Mandatory = $true)][string]$Server)
    if ($script:SmbCredentials.ContainsKey($Server)) {
        return $script:SmbCredentials[$Server]
    }
    Write-Host "Docker requires an authorised SMB account to mount the remote share on $Server." -ForegroundColor Cyan
    Write-Host "Enter an account that has read access to controlled documents and write access to the backup folder."
    Write-Host "The credential is used to create Docker's protected SMB volume and is not written to the Training Matrix .env file." -ForegroundColor Yellow
    $credential = Get-Credential -Message "Credentials for \\$Server"
    if (-not $credential) { throw "Network credential entry was cancelled." }
    $script:SmbCredentials[$Server] = $credential
    return $credential
}

function Get-UncVolumeName {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("documents", "backups")][string]$Purpose,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $normalised = $Path.TrimEnd('\').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalised))
    }
    finally { $sha.Dispose() }
    $suffix = ([BitConverter]::ToString($hash).Replace('-', '').Substring(0, 12)).ToLowerInvariant()
    return "training-matrix-$Purpose-unc-v2-$suffix"
}

function Get-LegacyUncVolumeName {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("documents", "backups")][string]$Purpose,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $normalised = $Path.TrimEnd('\').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalised)) }
    finally { $sha.Dispose() }
    $suffix = ([BitConverter]::ToString($hash).Replace('-', '').Substring(0, 12)).ToLowerInvariant()
    return "training-matrix-$Purpose-unc-$suffix"
}

function Remove-LegacyUncVolumes {
    param(
        [Parameter(Mandatory = $true)][string]$DocumentsPath,
        [Parameter(Mandatory = $true)][string]$BackupPath
    )
    if (Test-IsUncPath -Path $DocumentsPath) {
        Invoke-DockerQuiet -Arguments @("volume", "rm", (Get-LegacyUncVolumeName -Purpose "documents" -Path $DocumentsPath)) | Out-Null
    }
    if (Test-IsUncPath -Path $BackupPath) {
        Invoke-DockerQuiet -Arguments @("volume", "rm", (Get-LegacyUncVolumeName -Purpose "backups" -Path $BackupPath)) | Out-Null
    }
}

function Ensure-DockerUncVolume {
    param(
        [Parameter(Mandatory = $true)][string]$VolumeName,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$ReadOnly
    )
    $unc = Split-UncPath -Path $Path
    if ((Invoke-DockerQuiet -Arguments @("volume", "inspect", $VolumeName)) -eq 0) {
        return
    }

    $credential = Get-SmbCredentialForServer -Server $unc.Server
    $networkCredential = $credential.GetNetworkCredential()
    foreach ($value in @($networkCredential.UserName, $networkCredential.Domain, $networkCredential.Password)) {
        if ($value -and $value.Contains(',')) {
            throw "The SMB username, domain and password cannot contain a comma because Docker's CIFS volume driver uses comma-separated mount options. Use a dedicated service account without commas in its credential."
        }
    }
    $options = @(
        "username=$($networkCredential.UserName)",
        "password=$($networkCredential.Password)",
        "vers=3.0",
        "iocharset=utf8",
        "uid=10001",
        "gid=10001",
        "file_mode=0660",
        "dir_mode=0770",
        "noperm"
    )
    if ($networkCredential.Domain) { $options += "domain=$($networkCredential.Domain)" }
    if ($ReadOnly) { $options += "ro" }

    Write-Host "Creating Docker SMB volume for $Path..." -ForegroundColor Cyan
    & docker volume create --driver local --opt type=cifs --opt "device=$($unc.Device)" --opt "o=$($options -join ',')" $VolumeName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker could not create the SMB volume for $Path. Confirm TCP 445 access, the share path and the supplied network account."
    }
}

function Write-WindowsComposeOverride {
    param(
        [Parameter(Mandatory = $true)][string]$DocumentsPath,
        [Parameter(Mandatory = $true)][string]$BackupPath
    )
    $lines = @("services:")
    $hasOverride = $false
    if (Test-IsUncPath -Path $DocumentsPath) {
        $documentsUnc = Split-UncPath -Path $DocumentsPath
        $documentsVolumeName = Get-UncVolumeName -Purpose "documents" -Path $DocumentsPath
        $hasOverride = $true
        $documentMount = @(
            "  api:",
            "    volumes:",
            "      - type: volume",
            "        source: training-matrix-controlled-documents-unc",
            "        target: /controlled-documents",
            "        read_only: true"
        )
        if ($documentsUnc.Relative) {
            $documentMount += @("        volume:", "          subpath: $($documentsUnc.Relative | ConvertTo-Json -Compress)")
        }
        $lines += $documentMount
    }
    if (Test-IsUncPath -Path $BackupPath) {
        $backupUnc = Split-UncPath -Path $BackupPath
        $hasOverride = $true
        if (-not (Test-IsUncPath -Path $DocumentsPath)) {
            $lines += @("  api:", "    volumes:")
        }
        $backupMounts = @(
            "      - type: volume",
            "        source: training-matrix-backups-unc",
            "        target: /backups"
        )
        if ($backupUnc.Relative) {
            $backupMounts += @("        volume:", "          subpath: $($backupUnc.Relative | ConvertTo-Json -Compress)")
        }
        $backupMounts += @(
            "  backup-scheduler:",
            "    volumes:",
            "      - type: volume",
            "        source: training-matrix-backups-unc",
            "        target: /backups"
        )
        if ($backupUnc.Relative) {
            $backupMounts += @("        volume:", "          subpath: $($backupUnc.Relative | ConvertTo-Json -Compress)")
        }
        $lines += $backupMounts
    }
    if ($hasOverride) {
        $lines += @("volumes:")
        if (Test-IsUncPath -Path $DocumentsPath) {
            $lines += @("  training-matrix-controlled-documents-unc:", "    external: true", "    name: $documentsVolumeName")
        }
        if (Test-IsUncPath -Path $BackupPath) {
            $backupVolumeName = Get-UncVolumeName -Purpose "backups" -Path $BackupPath
            $lines += @("  training-matrix-backups-unc:", "    external: true", "    name: $backupVolumeName")
        }
        Set-Content -LiteralPath $script:ComposeWindowsOverrideFile -Value $lines -Encoding UTF8
    }
    elseif (Test-Path -LiteralPath $script:ComposeWindowsOverrideFile) {
        Remove-Item -LiteralPath $script:ComposeWindowsOverrideFile -Force
    }
}

function Initialize-WindowsStorageMounts {
    param(
        [Parameter(Mandatory = $true)][string]$DocumentsPath,
        [Parameter(Mandatory = $true)][string]$BackupPath
    )
    if (Test-IsUncPath -Path $DocumentsPath) {
        $documentsVolumeName = Get-UncVolumeName -Purpose "documents" -Path $DocumentsPath
        Ensure-DockerUncVolume -VolumeName $documentsVolumeName -Path $DocumentsPath -ReadOnly $true
    }
    if (Test-IsUncPath -Path $BackupPath) {
        $backupVolumeName = Get-UncVolumeName -Purpose "backups" -Path $BackupPath
        Ensure-DockerUncVolume -VolumeName $backupVolumeName -Path $BackupPath -ReadOnly $false
    }
    Write-WindowsComposeOverride -DocumentsPath $DocumentsPath -BackupPath $BackupPath
}

function Ensure-InstallerImage {
    Write-Host "Checking the TLS and folder-validation image..." -ForegroundColor Cyan
    if ((Invoke-DockerQuiet -Arguments @("image", "inspect", "alpine/openssl:latest")) -eq 0) { return }
    Write-Host "Downloading alpine/openssl for first-time installation. This requires Docker Hub access."
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Write-Host "Docker image download attempt $attempt of 3..."
        & docker pull alpine/openssl:latest
        if ($LASTEXITCODE -eq 0) { return }
        if ($attempt -lt 3) {
            Write-Host "The download failed. Waiting 5 seconds before retrying..." -ForegroundColor Yellow
            Start-Sleep -Seconds 5
        }
    }
    throw "Docker could not download alpine/openssl after three attempts. Check Docker Desktop DNS/proxy access, run 'docker pull alpine/openssl:latest', then rerun this installer and choose RESUME INSTALLATION."
}

function Test-DockerDocumentAccess {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-IsUncPath -Path $Path) {
        $unc = Split-UncPath -Path $Path
        $volumeName = Get-UncVolumeName -Purpose "documents" -Path $Path
        $mountSpec = "type=volume,source=$volumeName,target=/probe,readonly"
        if ($unc.Relative) { $mountSpec += ",volume-subpath=$($unc.Relative)" }
        $mountArguments = @("--mount", $mountSpec)
    }
    else {
        $dockerPath = Convert-ToDockerPath $Path
        $mountArguments = @("--mount", "type=bind,source=$dockerPath,target=/probe,readonly")
    }
    $result = & docker run --rm --entrypoint sh @mountArguments alpine/openssl:latest -c 'find /probe -type f ! -name "~\$*" \( -iname "*.pdf" -o -iname "*.docx" \) -print | wc -l'
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop cannot read the selected controlled-document folder. Use a Docker-accessible local path or UNC path and check Docker Desktop file-sharing/proxy settings."
    }
    $count = 0
    if (-not [int]::TryParse(($result | Select-Object -Last 1).Trim(), [ref]$count)) {
        throw "Docker accessed the folder but the recursive PDF/DOCX count could not be verified."
    }
    Write-Host "Docker verified read-only access to $count PDF/DOCX files across all nested folders." -ForegroundColor Green
    return $count
}

function Test-DockerBackupAccess {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-IsUncPath -Path $Path) {
        $unc = Split-UncPath -Path $Path
        $volumeName = Get-UncVolumeName -Purpose "backups" -Path $Path
        $mountSpec = "type=volume,source=$volumeName,target=/probe"
        if ($unc.Relative) { $mountSpec += ",volume-subpath=$($unc.Relative)" }
        $mountArguments = @("--mount", $mountSpec)
    }
    else {
        $dockerPath = Convert-ToDockerPath $Path
        $mountArguments = @("--mount", "type=bind,source=$dockerPath,target=/probe")
    }
    & docker run --rm --entrypoint sh @mountArguments alpine/openssl:latest -c 'testfile=/probe/.eaststone-training-matrix-write-test; : > "$testfile" && rm -f "$testfile"'
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop cannot write to the selected backup folder. Select a writable Docker-accessible folder."
    }
    Write-Host "Docker verified write access to the backup folder." -ForegroundColor Green
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

function Publish-ClientDeployment {
    param(
        [Parameter(Mandatory = $true)][string]$PackageSystemRoot,
        [Parameter(Mandatory = $true)][string]$ServerName,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$CertificatePath,
        [Parameter(Mandatory = $true)][string]$AppVersion
    )
    $packageRoot = Split-Path $PackageSystemRoot -Parent
    $clientFolder = Join-Path $packageRoot "CLIENT DEPLOYMENT"
    if (-not (Test-Path -LiteralPath $clientFolder)) {
        throw "The release is missing its CLIENT DEPLOYMENT folder: $clientFolder"
    }
    if (-not (Test-Path -LiteralPath $CertificatePath)) {
        throw "The installed server certificate was not found: $CertificatePath"
    }

    $clientCertificate = Join-Path $clientFolder "server.crt"
    Copy-Item -LiteralPath $CertificatePath -Destination $clientCertificate -Force
    $configuration = [ordered]@{
        server_name = $ServerName
        https_port = $Port
        certificate_filename = "server.crt"
        certificate_sha256 = (Get-FileHash -LiteralPath $CertificatePath -Algorithm SHA256).Hash
        app_version = $AppVersion
        generated_at = (Get-Date).ToString("o")
    }
    $configuration | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $clientFolder "client-config.json") -Encoding UTF8
    Write-Host "Client Deployment was configured automatically for https://${ServerName}:$Port." -ForegroundColor Green
}

function Wait-LocalHealth {
    param([int]$Port, [int]$TimeoutSeconds = 900)
    Write-Host "Waiting for the web application and database to become healthy (first build can take several minutes)..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastNotice = Get-Date
    do {
        try {
            $result = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
            if ($result.status -eq "ok") {
                Write-Host "Application health check passed." -ForegroundColor Green
                return $result
            }
        }
        catch {}
        if (((Get-Date) - $lastNotice).TotalSeconds -ge 15) {
            Write-Host "Still starting; the installer is continuing to wait..."
            $lastNotice = Get-Date
        }
        Start-Sleep -Seconds 3
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
        "/XD", ".git", ".venv", "node_modules", "dist", ".pytest_cache", ".ruff_cache", "backups", "runtime", "tls",
        "/XF", ".env", "docker-compose.windows.generated.yml", "operations.log", "INITIAL_ADMIN_CREDENTIALS.txt", "INSTALLATION_LOG.txt", "INSTALLATION_REPORT.txt", "UPDATE_LOG.txt", "LAST_UPDATE_RESULT.txt"
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

function Protect-DockerTlsKey {
    param([Parameter(Mandatory = $true)][string]$TlsFolder)
    $keyPath = Join-Path $TlsFolder "server.key"
    & icacls $TlsFolder /grant "*S-1-5-32-545:(RX)" *> $null
    & icacls $keyPath /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" "*S-1-5-32-545:(R)" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to grant Docker Desktop read access to the TLS private key."
    }
}
