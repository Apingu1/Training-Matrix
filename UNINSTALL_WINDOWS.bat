@echo off
setlocal
pushd "%~dp0" || (echo Unable to open the extracted Training Matrix folder. & pause & exit /b 1)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "windows\uninstall.ps1"
set "EASTSTONE_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%EASTSTONE_EXIT_CODE%"=="0" pause
exit /b %EASTSTONE_EXIT_CODE%
