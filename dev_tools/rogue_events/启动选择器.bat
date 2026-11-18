@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 卡厄思事件偏好选择器：起一个本地静态服务再打开浏览器。
rem 直接双击 index.html 也能用（数据用 <script src> 加载，不走 fetch），
rem 但 file:// 下 localStorage 的隔离规则各浏览器不一致，所以这里走 http。

set PORT=8899
set "PYTHON=%~dp0..\..\toolkit\python.exe"

:check_port
netstat -ano | findstr ":%PORT% " | findstr LISTENING >nul
if not errorlevel 1 (
    "%PYTHON%" -c "import urllib.request; assert b'id=\x22btn-export\x22' in urllib.request.urlopen('http://127.0.0.1:%PORT%/index.html', timeout=2).read()" >nul 2>&1
    if not errorlevel 1 goto open_page
    if "%PORT%"=="8900" goto open_file
    set PORT=8900
    goto check_port
)

echo 正在启动本地服务（端口 %PORT%）...
start "czn-rogue-events" /min "%PYTHON%" -m http.server %PORT% --bind 127.0.0.1
timeout /t 2 >nul

:open_page
start "" "http://127.0.0.1:%PORT%/index.html"
echo.
echo 页面已打开。关掉这个窗口不会停服务；服务窗口是最小化的那个 cmd。
exit /b 0

:open_file
echo 本地端口不可用，改为直接打开文件。此模式的浏览器草稿与本地服务页面分开保存。
start "" "%~dp0index.html"
exit /b 0
