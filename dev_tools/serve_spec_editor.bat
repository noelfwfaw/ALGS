@echo off
rem Serve dev_tools/ over http so the browser is allowed to keep the local
rem autosave. A page opened as file:// is an opaque origin: Chrome silently
rem drops IndexedDB, so every reload would start from an empty editor and the
rem cards drawn over an afternoon would be gone. Same page over
rem http://127.0.0.1 keeps them.
rem
rem The editor stores one record per page plus one per screenshot, so editing a
rem card writes a few kilobytes, not the whole spec.
setlocal
cd /d "%~dp0"

set "PORT=22269"
set "PY=%~dp0..\toolkit\python.exe"
if not exist "%PY%" set "PY=python"

start "AlGS Spec Editor Server" /min "%PY%" -m http.server %PORT% --directory "%~dp0.."
timeout /t 2 >nul
rem http.server sends no Cache-Control, and a tab that opened the page before
rem an edit keeps the old copy. A different query string forces a fresh read.
start "" "http://127.0.0.1:%PORT%/dev_tools/spec_editor.html?v=%RANDOM%"

echo AlGS Spec Editor: http://127.0.0.1:%PORT%/dev_tools/spec_editor.html
echo The server runs in the minimized window "AlGS Spec Editor Server".
echo Close that window when you are done.
pause >nul
