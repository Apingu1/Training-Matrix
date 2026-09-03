@echo off
setlocal
pushd "%~dp0" || (echo Unable to open the extracted Training Matrix folder. & pause & exit /b 1)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "windows\install.ps1"
set "EASTSTONE_EXIT_CODE=%ERRORLEVEL%"
popd
if "%EASTSTONE_EXIT_CODE%"=="0" (echo Server installation command completed.) else (echo Server installation failed with exit code %EASTSTONE_EXIT_CODE%.)
pause
exit /b %EASTSTONE_EXIT_CODE%
