@echo off
chcp 65001 > nul
title Загрузка парсера на GitHub
cd /d "%~dp0"

echo ===================================================================
echo   🚀 ЗАГРУЗКА ПАРСЕРА НА GITHUB ДЛЯ ДЕПЛОЯ НА RENDER / RAILWAY
echo ===================================================================
echo.
echo 1. Создайте новый пустой репозиторий на https://github.com/new
echo    (назовите, например: lead-parser, галочки README не ставьте)
echo 2. Скопируйте ссылку на созданный репозиторий
echo.
set /p REPO_URL="👉 Вставьте ссылку на репозиторий (https://github.com/...): "

if "%REPO_URL%"=="" (
    echo [ОШИБКА] Ссылка не была введена!
    pause
    exit /b
)

echo.
echo Подключение к GitHub и отправка файлов...
git remote remove origin >nul 2>&1
git remote add origin %REPO_URL%
git branch -M main
git push -u origin main

if errorlevel 1 (
    echo.
    echo ===================================================================
    echo [ПОДСКАЗКА ПО АВТОРИЗАЦИИ GITHUB]
    echo Если появилось окно браузера — нажмите "Sign in with your browser".
    echo Если просит пароль — введите Personal Access Token (PAT) от GitHub:
    echo Создать токен: https://github.com/settings/tokens (права repo)
    echo ===================================================================
) else (
    echo.
    echo ===================================================================
    echo   🎉 УСПЕШНО! Код загружен на GitHub.
    echo.
    echo   Теперь откройте:
    echo   👉 Render: https://dashboard.render.com -> New + -> Web Service
    echo   👉 Или Railway: https://railway.app/new -> Deploy from GitHub
    echo.
    echo   Выберите ваш репозиторий — деплой начнется автоматически!
    echo ===================================================================
)

pause
