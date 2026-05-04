@echo off
echo ========================================
echo   内网穿透工具 - 让外地朋友访问你的系统
echo ========================================
echo.
echo 前置条件：
echo   1. 后端服务已在 8000 端口运行
echo   2. 已安装以下任一穿透工具
echo.

echo ----------------------------------------
echo 方案1: ngrok (推荐，全球节点)
echo ----------------------------------------
echo 下载地址: https://ngrok.com/download
echo.
echo 安装步骤：
echo   1. 注册账号并获取 authtoken
echo   2. 运行: ngrok config add-authtoken 你的token
echo   3. 运行: ngrok http 8000
echo.
echo 获取公网地址后，修改前端配置：
echo   miniapp/utils/api.js 中的 BASE_URL 改为 ngrok 地址
echo.

echo ----------------------------------------
echo 方案2: cpolar (国内推荐)
echo ----------------------------------------
echo 下载地址: https://www.cpolar.com/
echo.
echo 安装步骤：
echo   1. 注册账号
echo   2. 运行: cpolar http 8000
echo.

echo ----------------------------------------
echo 方案3: frp (需要公网服务器)
echo ----------------------------------------
echo 下载地址: https://github.com/fatedier/frp/releases
echo.
echo 需要一台有公网IP的服务器作为中转
echo.

echo ----------------------------------------
echo 方案4: localtunnel (无需注册)
echo ----------------------------------------
echo 安装: npm install -g localtunnel
echo 运行: lt --port 8000
echo.

echo ========================================
echo 穿透成功后，前端访问地址修改方法：
echo ========================================
echo.
echo 1. 打开 miniapp/utils/api.js
echo 2. 修改 return '' 为 return '你的穿透地址'
echo    例如: return 'https://xxxx.ngrok.io'
echo 3. 重新编译前端: cd miniapp ^&^& npm run dev:h5
echo.
echo 注意：穿透地址每次启动可能变化
echo 如需固定地址，请使用付费版 ngrok 或 cpolar
echo.
pause
