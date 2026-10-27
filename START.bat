@echo off
cd /d "%~dp0"
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo .env fayliga bot tokenini kiriting va saqlang.
  notepad ".env"
  exit /b 1
)
"%~dp0PropanBot.exe"
if errorlevel 1 pause
