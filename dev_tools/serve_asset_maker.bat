@echo off
rem Serve dev_tools/ over http so the browser is allowed to remember the
rem export directory. A page opened as file:// is an opaque origin: Chrome
rem silently drops the FileSystemDirectoryHandle and IndexedDB, so the folder
rem dialog comes back on every export. Same page over http://127.0.0.1 keeps it.
setlocal
cd /d "%~dp0"

set "PORT=22268"
set "PY=%~dp0..\toolkit\python.exe"
if not exist "%PY%" set "PY=python"

start "AlGS Asset Maker Server" /min "%PY%" -m http.server %PORT%
timeout /t 2 >nul
start "" "http://127.0.0.1:%PORT%/asset_maker.html"

echo AlGS Asset Maker: http://127.0.0.1:%PORT%/asset_maker.html
echo The server runs in the minimized window "AlGS Asset Maker Server".
echo Close that window when you are done exporting.
pause >nul
