@echo off
chcp 65001 >nul
title bilibili_learning_bot - Web Panel [Account2:8081]
cd /d "%~dp0"

echo.
echo ========================================
echo    WARNING / 免责声明 / DISCLAIMER
echo ========================================
echo.
echo   本项目仅供学习参考，
echo   若因使用本项目产生任何后果，本人概不负责。
echo.
echo   This project is for learning purposes only.
echo   Any consequences are solely your own responsibility.
echo.
echo ========================================
echo.

python web_panel.py --port 8081
pause
