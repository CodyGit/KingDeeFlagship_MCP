@echo off
REM date: 2026-11-09 23:05
REM author: cody
REM description: 双击入口。先运行 setup.bat，再运行本脚本：把连接器打包成 Kimi 插件并注册安装到本机 Kimi
chcp 65001 >nul
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
