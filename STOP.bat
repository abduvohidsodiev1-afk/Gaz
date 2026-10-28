@echo off
cd /d "%~dp0"
chcp 65001 >nul
"%~dp0PropanBot.exe" --stop
pause
