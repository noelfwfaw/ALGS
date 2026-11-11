@echo off
rem Serve the repository over http so the browser is allowed to keep the local
rem autosave. A page opened as file:// is an opaque origin: Chrome silently
rem drops IndexedDB, so every reload would start from an empty editor and the
rem cards drawn over an afternoon would be gone. Same page over
rem http://127.0.0.1 keeps them.
rem
rem The editor stores one record per page plus one per screenshot, so editing a
rem card writes a few kilobytes, not the whole spec.
rem
rem Two things that are easy to get wrong here:
rem - http.server binds 0.0.0.0 by default, and this one serves the whole
rem   repository: without --bind 127.0.0.1 the configs and logs are reachable
rem   from the LAN. Keep it on loopback.
rem - The game / namespace dropdowns are baked into the html, so they are
rem   regenerated first. Forgetting that is why a new game never shows up.
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"

set "PORT=22269"
set "PY=%~dp0..\toolkit\python.exe"
if not exist "%PY%" set "PY=python"

rem Idempotent: rewrites only the GAMES / NAMESPACES block, prints two lines.
"%PY%" -m dev_tools.spec_games

start "AlGS Spec Editor Server" /min "%PY%" -m http.server %PORT% --bind 127.0.0.1
timeout /t 2 >nul
rem http.server sends no Cache-Control, and a tab that opened the page before
rem an edit keeps the old copy. A different query string forces a fresh read.
start "" "http://127.0.0.1:%PORT%/dev_tools/spec_editor.html?v=%RANDOM%"

echo AlGS Spec Editor: http://127.0.0.1:%PORT%/dev_tools/spec_editor.html
echo The server runs in the minimized window "AlGS Spec Editor Server".
echo If the page does not load, port %PORT% may be taken - close an old server window first.
echo Close that window when you are done.
pause >nul
