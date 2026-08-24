@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\reset_admin_password.ps1"
if errorlevel 1 pause
