@echo off
chcp 65001 > nul
title Online Lead Parser Access
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo ===================================================================
    echo [INFO] First-time setup required. Please run START.bat first!
    echo ===================================================================
    pause
    exit /b
)

echo ===================================================================
echo   🚀 LAUNCHING WEB PARSER AND CREATING PUBLIC SHAREABLE URL
echo ===================================================================
echo.
echo [1/2] Starting local web server...
start "LeadParser Web Server" /min .\venv\Scripts\python.exe web_ui.py

timeout /t 2 /nobreak > nul

echo [2/2] Connecting secure public tunnel...
echo.
echo ===================================================================
echo   👉 Copy the https://*.lhr.life URL below and send to your friend!
echo   👉 Or scan the QR code on mobile camera!
echo ===================================================================
echo.

ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R 80:localhost:8080 nokey@localhost.run

if errorlevel 1 (
    echo.
    echo Fallback to localtunnel:
    npx --yes localtunnel --port 8080
)

pause
