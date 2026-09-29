@echo off
chcp 65001 > nul
title Онлайн-Доступ к Лид-Парсеру
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo ===================================================================
    echo [ИНФО] Первичная настройка парсера... Запустите сначала START.bat!
    echo ===================================================================
    pause
    exit /b
)

echo ===================================================================
echo   🚀 ЗАПУСК ВЕБ-ПАРСЕРА И СОЗДАНИЕ ПУБЛИЧНОЙ ОНЛАЙН-ССЫЛКИ
echo ===================================================================
echo.
echo [1/2] Запуск локального сервера парсера...
start "LeadParser Web Server" /min .\venv\Scripts\python.exe web_ui.py

timeout /t 2 /nobreak > nul

echo [2/2] Генерация ссылки для отправки другу...
echo.
echo ===================================================================
echo   👉 Скопируйте ссылку https://*.lhr.life (или сканируйте QR-код):
echo   👉 Отправьте ее другу — он откроет парсер в браузере!
echo ===================================================================
echo.

ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R 80:localhost:8080 nokey@localhost.run

if errorlevel 1 (
    echo.
    echo Запасной канал связи:
    npx --yes localtunnel --port 8080
)

pause
