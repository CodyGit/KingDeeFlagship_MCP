@echo off
chcp 65001 >nul
REM date: 2026-11-10 16:30
REM author: cody
REM description: install the WorkBuddy integration: merge mcp.json and
REM              install the kingdee-kis skill. Idempotent, safe to re-run.
REM              Run scripts\setup.bat first.
setlocal
set PY=%~dp0..\.venv32\Scripts\python.exe
if not exist "%PY%" (
  echo 没找到 .venv32，请先运行 scripts\setup.bat
  if not defined KIS_NO_PAUSE pause
  exit /b 1
)
"%PY%" "%~dp0workbuddy_setup.py" %*
set RC=%ERRORLEVEL%
if not defined KIS_NO_PAUSE pause
exit /b %RC%
