@echo off
title Lead Parser Online Access
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist "venv\Scripts\python.exe" (
    call START.bat
    exit /b
)

.\venv\Scripts\python.exe share_online.py
pause
