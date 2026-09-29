﻿﻿﻿@echo off
chcp 65001 > nul
title Лид-Парсер Карт - Консольный режим
if exist ".\venv\Scripts\python.exe" (
    .\venv\Scripts\python.exe main.py --cli
) else (
    python main.py --cli
)
pause
