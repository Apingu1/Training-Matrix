@echo off
set /p EASTSTONE_SERVER=Server computer name:
set /p EASTSTONE_PORT=HTTPS port [8090]:
if "%EASTSTONE_PORT%"=="" set EASTSTONE_PORT=8090
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\client_setup.ps1" -ServerName "%EASTSTONE_SERVER%" -Port %EASTSTONE_PORT% -CertificatePath "%~dp0server.crt"
pause
