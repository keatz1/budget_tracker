@echo off
REM Double-click this file to start the budget app on Windows.
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is not installed.
  echo Opening the download page. Install it, open it once, then double-click this file again.
  start https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop is installed but not running. Starting it...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
  echo Waiting for Docker to start ^(this can take a minute^)...
  :waitdocker
  timeout /t 3 >nul
  docker info >nul 2>&1
  if errorlevel 1 goto waitdocker
)

if not exist .env (
  for /f %%i in ('powershell -NoProfile -Command "-join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })"') do set SECRET=%%i
  echo BT_SECRET_KEY=%SECRET%> .env
  echo BT_PORT=8000>> .env
)

echo Starting the budget app. The first time takes a few minutes...
docker compose up -d --build
if errorlevel 1 (
  echo Something went wrong. Take a photo of this window.
  pause
  exit /b 1
)

echo Waiting for it to come up...
timeout /t 8 >nul
start http://localhost:8000
echo.
echo The app keeps running in the background, even after you close this window.
echo To stop it, double-click stop-windows.bat.
timeout /t 5 >nul
