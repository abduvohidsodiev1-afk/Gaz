@echo off
cd /d "%~dp0"
chcp 65001 >nul
echo Ollama ishlasin. Avval botni STOP.bat bilan toxtating.
"%~dp0PropanBot.exe" --ai-hybrid-test
pause
