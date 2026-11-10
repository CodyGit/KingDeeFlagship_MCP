@echo off
chcp 65001 >nul
REM date: 2026-11-10 11:40
REM author: cody
REM description: install or upgrade the Kimi plugin: build + register to the personal market.
REM              Run scripts\setup.bat first. The script detects whether the plugin is
REM              already installed and bumps the version accordingly.
REM options: --offline (Kimi must be closed; replace the installed copy directly)
REM          --dry-run (print the version plan only) / --build-only / --clean
setlocal
set PY=%~dp0..\.venv32\Scripts\python.exe
if not exist "%PY%" (
  echo 没找到 .venv32，请先运行 scripts\setup.bat
  if not defined KIS_NO_PAUSE pause
  exit /b 1
)
"%PY%" "%~dp0kimi_setup.py" %*
set RC=%ERRORLEVEL%
if not defined KIS_NO_PAUSE pause
exit /b %RC%
