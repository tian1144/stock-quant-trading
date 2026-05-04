@echo off
chcp 65001 >nul
setlocal

set "DOMAIN=www.lianghuagongju222333.com"
set "LOCAL_URL=http://localhost:8000"
set "PYTHON_EXE=backend\venv\Scripts\python.exe"
set "TUNNEL_NAME=lianghua-h5"

echo ========================================
echo   量化工具公网访问启动器
echo ========================================
echo.
echo 本地服务: %LOCAL_URL%
echo 目标域名: https://%DOMAIN%
echo.

where cloudflared >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未检测到 cloudflared。
  echo 请先安装 Cloudflare Tunnel 客户端：
  echo https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  echo.
  echo 临时替代方案可参考 deploy\public_access.md。
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo [ERROR] 未找到 %PYTHON_EXE%
  echo 请确认后端虚拟环境存在，或先按项目说明安装依赖。
  pause
  exit /b 1
)

echo [1/2] 正在启动本地 H5 后端窗口...
start "Lianghua H5 Backend" cmd /k "%PYTHON_EXE%" preview_server.py

echo [2/2] 正在启动 Cloudflare Tunnel: %TUNNEL_NAME%
echo.
echo 如果这里提示找不到隧道或 DNS 未配置，请按 deploy\public_access.md 完成首次配置。
echo 成功后公网地址为: https://%DOMAIN%
echo.
timeout /t 5 /nobreak >nul
cloudflared tunnel run %TUNNEL_NAME%

pause
