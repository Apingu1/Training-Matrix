param(
    [Parameter(Mandatory = $true)][string]$ServerName,
    [int]$Port = 8090,
    [string]$CertificatePath = (Join-Path $PSScriptRoot "server.crt")
)
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run client setup as Administrator so the approved server certificate can be trusted."
}
if (-not (Test-Path $CertificatePath)) {
    throw "Copy the server's approved tls\server.crt beside this script or pass -CertificatePath."
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
