@echo off
cd /d "%~dp0"
chcp 65001 >nul
"%~dp0PropanBot.exe" --version
"%~dp0PropanBot.exe" --self-test
pause
