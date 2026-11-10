@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0toolkit\python.exe"
set "ADB=%~dp0toolkit\Lib\site-packages\adbutils\binaries\adb.exe"
set "SERIAL=127.0.0.1:16640"
set "ENV_URL=https://github.com/noelfwfaw/ALGS/releases/latest/download/toolkit.zip"
set "RELEASES=https://github.com/noelfwfaw/ALGS/releases/latest"

rem Trust the local CA bundle (only needed behind a TLS-inspecting proxy)
if exist "%~dp0toolkit\ca-bundle.pem" set "REQUESTS_CA_BUNDLE=%~dp0toolkit\ca-bundle.pem"

if not exist "%PY%" call :install_toolkit
if exist "%~dp0toolkit\ca-bundle.pem" set "REQUESTS_CA_BUNDLE=%~dp0toolkit\ca-bundle.pem"
if not exist "%PY%" (
  echo [ERROR] toolkit\python.exe still not found.
  echo         Download the full package instead: %RELEASES%
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
exit /b

:install_toolkit
set "ZIPFILE=%~dp0toolkit.zip"
echo ============================================================
echo  [AlGS] toolkit\python.exe not found.
echo  Downloading the built-in Python environment ^(about 213 MB, once only^).
echo  If GitHub is slow, set HTTPS_PROXY before starting this script.
echo ============================================================
where curl.exe >nul 2>nul
if not errorlevel 1 (
  curl.exe -fL --retry 3 --retry-delay 2 -o "%ZIPFILE%" "%ENV_URL%"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%ENV_URL%' -OutFile '%ZIPFILE%' -UseBasicParsing"
)
if errorlevel 1 goto :toolkit_fail
if not exist "%ZIPFILE%" goto :toolkit_fail
echo [AlGS] Extracting toolkit ...
where tar.exe >nul 2>nul
if not errorlevel 1 (
  tar.exe -xf "%ZIPFILE%"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force -Path '%ZIPFILE%' -DestinationPath '.'"
)
if errorlevel 1 goto :toolkit_fail
del /f /q "%ZIPFILE%" >nul 2>nul
if exist "%PY%" (
  echo [AlGS] Environment ready.
  goto :eof
)
:toolkit_fail
if exist "%ZIPFILE%" del /f /q "%ZIPFILE%" >nul 2>nul
echo [ERROR] Could not prepare the built-in environment automatically.
echo         Download the full package instead: %RELEASES%
goto :eof
