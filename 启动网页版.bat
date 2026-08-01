@echo off
chcp 65001 >nul
title bilibili_learning_bot - Web Panel [Port:18083]
cd /d "%~dp0"

echo.
echo ========================================
echo    WARNING / DISCLAIMER
echo ========================================
echo.
echo   This project is for learning purposes only.
echo   Any consequences are solely your own responsibility.
echo.
echo ========================================
echo.

set "BILI_DISCLAIMER_SKIP=1"
set "BILI_WEB_AUTO_OPEN=1"
set "BILI_BOT_AUTO_START=0"
python web_panel.py
pause
