@echo off
cd /d "%~dp0"
chcp 65001 >nul
if not exist "PropanBot.exe" (
  echo PropanBot.exe topilmadi. Avval ZIP faylni toliq oching.
  pause
  exit /b 1
)
if not exist ".env" (
  if not exist ".env.example" (
    echo .env yoki .env.example topilmadi.
    pause
    exit /b 1
  )
  copy ".env.example" ".env" >nul
  echo .env fayliga bot tokenini kiriting va saqlang. Keyin START.bat ni yana bosing.
  notepad ".env"
  exit /b 1
)
"%~dp0PropanBot.exe"
if errorlevel 1 pause
