@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 卡厄思事件偏好选择器：起一个本地静态服务再打开浏览器。
rem 直接双击 index.html 也能用（数据用 <script src> 加载，不走 fetch），
rem 但 file:// 下 localStorage 的隔离规则各浏览器不一致，所以这里走 http。

set PORT=8899

rem 端口已被占用就直接打开，不重复起服务。
netstat -ano | findstr ":%PORT% " | findstr LISTENING >nul
if not errorlevel 1 (
    echo 端口 %PORT% 已在监听，直接打开页面。
    start "" "http://127.0.0.1:%PORT%/index.html"
    exit /b 0
)

echo 正在启动本地服务（端口 %PORT%）...
start "czn-rogue-events" /min "%~dp0..\..\toolkit\python.exe" -m http.server %PORT% --bind 127.0.0.1 --directory "%~dp0"
timeout /t 2 >nul
start "" "http://127.0.0.1:%PORT%/index.html"
echo.
echo 页面已打开。关掉这个窗口不会停服务；服务窗口是最小化的那个 cmd。
exit /b 0
