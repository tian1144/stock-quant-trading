@echo off
chcp 65001 >nul
echo ========================================
echo 股票行情 - 实时数据网页启动脚本
echo ========================================
echo.

echo 正在启动后端服务...
start "股票行情服务" cmd /k "cd /d %~dp0backend && python run_simple.py"
timeout /t 3 >nul

echo.
echo ========================================
echo 服务已启动！
echo.
echo 本地访问：http://localhost:8000
echo.
echo 给朋友分享时，使用以下地址：
echo http://你的IP地址:8000
echo.
echo 查看本机IP，在命令行输入：ipconfig
echo ========================================
echo.

start http://localhost:8000

pause
