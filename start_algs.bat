@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0toolkit\python.exe"
set "ADB=%~dp0toolkit\Lib\site-packages\adbutils\binaries\adb.exe"
set "SERIAL=127.0.0.1:16640"

rem Trust the local CA bundle (only needed behind a TLS-inspecting proxy)
if exist "%~dp0toolkit\ca-bundle.pem" set "REQUESTS_CA_BUNDLE=%~dp0toolkit\ca-bundle.pem"

if not exist "%PY%" (
  echo [ERROR] toolkit\python.exe not found.
  pause
  exit /b 1
)

echo Connecting emulator %SERIAL%
"%ADB%" start-server
"%ADB%" connect %SERIAL%

echo Starting AlGS WebUI at http://127.0.0.1:22267
"%PY%" gui.py --host 127.0.0.1 -p 22267

echo.
echo AlGS exited with code %ERRORLEVEL%.
pause
