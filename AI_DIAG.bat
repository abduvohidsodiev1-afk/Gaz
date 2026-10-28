@echo off
cd /d "%~dp0"
echo AI diagnostika v2. Ollama ishlab tursin.
echo Avval botni STOP.bat bilan toxtating.
"%~dp0PropanBot.exe" --ai-diagnose
pause
