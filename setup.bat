@echo off
REM date: 2026-11-09 21:15
REM author: cody
REM description: 双击入口。运行 scripts\setup.ps1 初始化 32 位虚拟环境并安装依赖（仅对本次进程放行脚本执行）
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1" %*
set RC=%ERRORLEVEL%
if not defined KIS_NO_PAUSE pause
exit /b %RC%
