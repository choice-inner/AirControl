@echo off
setlocal
cd /d "%~dp0"
if not exist "E:\conda_envs\AirControl\python.exe" (
  echo Python not found: E:\conda_envs\AirControl\python.exe
  echo See docs\USER_GUIDE.md for environment setup.
  pause
  exit /b 1
)
"E:\conda_envs\AirControl\python.exe" main.py %*
if errorlevel 1 pause
