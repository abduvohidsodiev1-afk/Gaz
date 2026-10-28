@echo off
cd /d "%~dp0"
chcp 65001 >nul
echo Avval botni STOP.bat bilan toxtating. Telegram JSON eksportini tanlaysiz.
"%~dp0PropanBot.exe" --import-history
pause
