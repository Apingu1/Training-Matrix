@echo off
setlocal
pushd "%~dp0" || (echo Unable to open the extracted Training Matrix folder. & pause & exit /b 1)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "windows\update.ps1"
set "UPDATE_EXIT_CODE=%ERRORLEVEL%"
popd
echo.
if "%UPDATE_EXIT_CODE%"=="0" (
    echo Update command finished successfully.
) else (
    echo Update command failed with exit code %UPDATE_EXIT_CODE%.
)
echo Review the result above and LAST_UPDATE_RESULT.txt in the installed application folder.
pause
exit /b %UPDATE_EXIT_CODE%
