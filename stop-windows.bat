@echo off
cd /d "%~dp0"
docker compose stop
echo Stopped. Your data is safe in the data folder. Double-click start-windows.bat to start again.
timeout /t 5 >nul
