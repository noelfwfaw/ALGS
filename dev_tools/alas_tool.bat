@echo off
rem Double-click this file for a numbered menu. It wraps the dev_tools scripts
rem so nobody has to remember `python -m dev_tools.spec_live ...` by heart, and
rem so a path with spaces or Chinese can simply be dragged into the window.
rem
rem Drag a spec.json onto this .bat to skip the menu and probe it right away.
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

set "PY=%~dp0..\toolkit\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"

"%PY%" -m dev_tools.tool %*

echo.
pause
