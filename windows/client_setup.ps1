param(
    [string]$ServerName,
    [int]$Port = 0,
    [string]$CertificatePath
)
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run client setup as Administrator so the approved server certificate can be trusted."
}
$configurationPath = Join-Path $PSScriptRoot "client-config.json"
if (-not (Test-Path -LiteralPath $configurationPath)) {
    throw "Client Deployment has not been prepared by the server installer. Run the server installer/update from the shared extracted package first."
}
$configuration = Get-Content -LiteralPath $configurationPath -Raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($ServerName)) { $ServerName = [string]$configuration.server_name }
if ($Port -eq 0) { $Port = [int]$configuration.https_port }
if ([string]::IsNullOrWhiteSpace($CertificatePath)) {
    $CertificatePath = Join-Path $PSScriptRoot ([string]$configuration.certificate_filename)
}
if ([string]::IsNullOrWhiteSpace($ServerName) -or $Port -lt 1 -or $Port -gt 65535) {
    throw "The generated client configuration does not contain a valid server name and HTTPS port."
}
if (-not (Test-Path -LiteralPath $CertificatePath)) {
    throw "The server certificate referenced by client-config.json is missing: $CertificatePath"
}
$certificateHash = (Get-FileHash -LiteralPath $CertificatePath -Algorithm SHA256).Hash
if ($configuration.certificate_sha256 -and $certificateHash -ne [string]$configuration.certificate_sha256) {
    throw "The client certificate does not match the SHA-256 fingerprint in client-config.json. Obtain a newly prepared Client Deployment folder from the server package."
}
$certificate = [Security.Cryptography.X509Certificates.X509Certificate2]::new((Resolve-Path $CertificatePath).Path)
if ($certificate.Subject -notmatch "CN=$([regex]::Escape($ServerName))") {
    throw "Certificate subject '$($certificate.Subject)' does not match requested server '$ServerName'."
}
Import-Certificate -FilePath $CertificatePath -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "Eaststone Training Matrix.url"
Set-Content -LiteralPath $shortcutPath -Value @("[InternetShortcut]", "URL=https://${ServerName}:$Port", "IconIndex=0") -Encoding ASCII
Write-Host "Trusted certificate thumbprint: $($certificate.Thumbprint)" -ForegroundColor Green
Write-Host "Client shortcut created for https://${ServerName}:$Port"
