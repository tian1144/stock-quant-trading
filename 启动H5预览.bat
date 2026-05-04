@echo off
setlocal
title Quant Hunter H5 Preview

set "ROOT=%~dp0"
set "PY=%ROOT%backend\venv\Scripts\python.exe"
set "LAUNCHER=%ROOT%preview_server.py"

if not exist "%PY%" (
  echo [ERROR] Python not found:
  echo %PY%
  pause
  exit /b 1
)

if not exist "%LAUNCHER%" (
  echo [ERROR] Launcher not found:
  echo %LAUNCHER%
  pause
  exit /b 1
)

echo Starting Quant Hunter preview...
echo This window is the backend server. Do not close it while previewing.
echo.
"%PY%" "%LAUNCHER%"

echo.
echo Server stopped.
pause
endlocal
