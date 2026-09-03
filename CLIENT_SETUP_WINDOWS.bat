@echo off
setlocal
pushd "%~dp0" || (
  echo Unable to open the Client Deployment folder.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "windows\client_setup.ps1"
set "EASTSTONE_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%EASTSTONE_EXIT_CODE%"=="0" echo Client installation failed with exit code %EASTSTONE_EXIT_CODE%.
pause
exit /b %EASTSTONE_EXIT_CODE%
