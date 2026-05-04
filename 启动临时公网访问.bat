@echo off
setlocal

cd /d "%~dp0"

set "LOCAL_URL=http://localhost:8000"
set "PYTHON_EXE=%~dp0backend\venv\Scripts\python.exe"
set "CLOUDFLARED=cloudflared"

echo ========================================
echo   Lianghua Temporary Public Access
echo ========================================
echo.
echo Project dir: %~dp0
echo Local URL:   %LOCAL_URL%
echo.

where cloudflared >nul 2>nul
if errorlevel 1 (
  if exist "%USERPROFILE%\Downloads\cloudflared.exe" (
    set "CLOUDFLARED=%USERPROFILE%\Downloads\cloudflared.exe"
  ) else if exist "%USERPROFILE%\Desktop\cloudflared.exe" (
    set "CLOUDFLARED=%USERPROFILE%\Desktop\cloudflared.exe"
  ) else if exist "C:\cloudflared\cloudflared.exe" (
    set "CLOUDFLARED=C:\cloudflared\cloudflared.exe"
  ) else if exist "%~dp0cloudflared.exe" (
    set "CLOUDFLARED=%~dp0cloudflared.exe"
  ) else (
    echo [ERROR] cloudflared.exe was not found.
    echo Put cloudflared.exe in one of these locations:
    echo   %USERPROFILE%\Downloads\cloudflared.exe
    echo   %USERPROFILE%\Desktop\cloudflared.exe
    echo   C:\cloudflared\cloudflared.exe
    echo   %~dp0cloudflared.exe
    echo.
    pause
    exit /b 1
  )
)

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python venv was not found:
  echo %PYTHON_EXE%
  echo.
  pause
  exit /b 1
)

echo [1/2] Checking local backend port 8000...
netstat -ano | findstr /R /C:":8000 .*LISTENING" >nul
if errorlevel 1 (
  echo Port 8000 is free. Starting local backend...
  start "Lianghua H5 Backend" cmd /k ""%PYTHON_EXE%" preview_server.py"
  timeout /t 5 /nobreak >nul
) else (
  echo Port 8000 is already running. Reusing the existing backend.
)

echo [2/2] Starting temporary Cloudflare tunnel...
echo.
echo Wait for a line like this:
echo   https://xxxx.trycloudflare.com
echo or:
echo   Your quick Tunnel has been created! Visit it at ...
echo.
echo Send that URL to your friend. Keep this window open.
echo.
"%CLOUDFLARED%" tunnel --url %LOCAL_URL%

pause
