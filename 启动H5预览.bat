@echo off
chcp 65001 >nul
echo ========================================
echo 股票行情 - H5网页预览启动脚本
echo ========================================
echo.

echo [1/3] 检查后端服务...
netstat -ano | findstr :8000 | findstr LISTENING >nul
if %errorlevel%==0 (
    echo 后端服务已运行 ✓
) else (
    echo 正在启动后端服务...
    start "后端服务" cmd /k "cd /d %~dp0backend && python run_simple.py"
    timeout /t 3 >nul
    echo 后端服务已启动 ✓
)

echo.
echo [2/3] 安装前端依赖（首次运行需要）...
cd /d %~dp0miniapp
if not exist node_modules (
    echo 正在安装依赖，这可能需要几分钟...
    call npm install
) else (
    echo 依赖已安装 ✓
)

echo.
echo [3/3] 启动H5预览服务...
echo.
echo ========================================
echo 启动后请访问：http://localhost:5173
echo.
echo 给朋友分享时，使用以下地址：
echo http://你的IP地址:5173
echo.
echo 查看本机IP：ipconfig
echo ========================================
echo.

call npm run dev:h5

pause
