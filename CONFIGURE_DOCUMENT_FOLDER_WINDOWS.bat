@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\configure_document_folder.ps1"
if errorlevel 1 pause
