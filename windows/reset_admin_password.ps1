. "$PSScriptRoot\common.ps1"
Assert-Administrator
Assert-Docker
Assert-Installed

$username = Read-Host "Username to reset [admin]"
if ([string]::IsNullOrWhiteSpace($username)) { $username = "admin" }
$secure = Read-Host "New temporary password" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $plain | & docker compose --env-file (Join-Path $script:InstallRoot ".env") -f $script:ComposeFile exec -T api python -m app.cli reset-password --username $username --password-stdin --reason "Authorised emergency reset from Windows server tool"
    if ($LASTEXITCODE -ne 0) { throw "Password reset failed." }
}
finally {
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    $plain = $null
}
Write-OperationLog "SERVER_PASSWORD_RESET" "username=$username"
Write-Host "Password reset. All active sessions for $username were revoked; a change is required at next sign-in." -ForegroundColor Green
