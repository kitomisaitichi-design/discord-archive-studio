@echo off
cd /d "%~dp0"
if not exist "%~dp0runtime\python.exe" (
  echo Extract the entire Portable ZIP before using this launcher.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" "%~dp0app.py"
if errorlevel 1 pause
