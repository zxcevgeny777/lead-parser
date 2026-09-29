@echo off
chcp 65001 > nul
title Лид-Парсер Карт и Бирж

cd /d "%~dp0"

if exist "venv\Scripts\python.exe" goto RUN_APP

python --version >nul 2>&1
if errorlevel 1 goto NO_PYTHON

echo =======================================================
echo   Установка компонентов парсера (только при первом запуске)
echo =======================================================
echo.
echo [1/3] Создание виртуального окружения...
python -m venv venv
if errorlevel 1 goto ERR_VENV

echo [2/3] Установка библиотек... Подождите 1-2 минуты...
.\venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
.\venv\Scripts\pip install -r requirements.txt
if errorlevel 1 goto ERR_PIP

echo [3/3] Установка браузера Chromium...
.\venv\Scripts\playwright install chromium
if errorlevel 1 goto ERR_PW

echo.
echo =======================================================
echo   Установка завершена успешно! Запуск...
echo =======================================================
echo.

:RUN_APP
echo Запуск веб-интерфейса...
echo Адрес в браузере: http://localhost:8080
echo Для выхода закройте это окно.
echo.
.\venv\Scripts\python.exe main.py
if errorlevel 1 goto ERR_RUN
exit /b

:NO_PYTHON
echo =======================================================
echo [ОШИБКА] Python не найден на вашем компьютере!
echo =======================================================
echo.
echo Скачайте Python с официального сайта:
echo https://www.python.org/downloads/
echo.
echo ВАЖНО: При установке ОБЯЗАТЕЛЬНО поставьте галочку:
echo [x] "Add Python to PATH" (Добавить Python в PATH)
echo.
pause
exit /b

:ERR_VENV
echo [ОШИБКА] Не удалось создать папку venv.
pause
exit /b

:ERR_PIP
echo [ОШИБКА] Ошибка при установке библиотек через pip.
pause
exit /b

:ERR_PW
echo [ОШИБКА] Ошибка при скачивании браузера Playwright.
pause
exit /b

:ERR_RUN
echo.
echo [ОШИБКА] Программа завершилась с ошибкой.
pause
exit /b
