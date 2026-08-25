@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\update.ps1"
set "UPDATE_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%UPDATE_EXIT_CODE%"=="0" (
    echo Update command finished successfully.
) else (
    echo Update command failed with exit code %UPDATE_EXIT_CODE%.
)
echo Review the result above and LAST_UPDATE_RESULT.txt in the installed application folder.
pause
exit /b %UPDATE_EXIT_CODE%
