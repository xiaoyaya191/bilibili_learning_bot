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
echo   Any consequences are your own responsibility.
echo.
echo ========================================
echo.

set /p AGREE="请输入'我同意'以继续: "
if /i not "%AGREE%"=="我同意" (
    echo.
    echo 输入不匹配，程序退出。
    pause
    exit /b 1
)

echo.
echo [OK] 已确认，启动中...
echo.

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

:: === Detect Python ===
python --version >nul 2>nul
if not errorlevel 1 (
    set "PY=python"
    goto :found_python
)
py -3 --version >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
    goto :found_python
)
echo [ERROR] Python not found. Install Python 3 first.
pause
exit /b 1

:found_python
echo [CHECK] Python version:
%PY% --version

:: === Ensure account2 Data dir ===
if not exist "account2" (
    echo [INIT] Creating account2 directory...
    mkdir "account2"
)
if not exist "account2\Data" (
    echo [INIT] Creating account2\Data directory...
    mkdir "account2\Data"
)
if not exist "account2\Data\config.json" (
    if exist "config.example.json" (
        echo [INIT] Copying config.example.json to account2\Data\config.json ...
        copy /y "config.example.json" "account2\Data\config.json" >nul
        echo [INFO] Edit account2\Data\config.json with your second account credentials.
    ) else (
        echo [WARN] config.example.json missing. Create account2\Data\config.json manually.
    )
)

:: === Check dependencies ===
echo.
echo [CHECK] Dependencies...
%PY% -c "import bilibili_api, colorama, httpx, openai, qrcode, requests" >nul 2>nul
if errorlevel 1 (
    echo [INSTALL] Installing requirements...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed.
        pause
        exit /b 1
    )
)

:: === Launch ===
echo.
echo [START] http://127.0.0.1:8081
echo [INFO] Close this window to stop the web panel.
echo.

start "" "http://127.0.0.1:8081"
set "WEB_PORT=8081"
set "BILI_ACCOUNT_DATA_DIR=account2/Data"
set "BILI_ACCOUNT_NAME=Account2"
set "BILI_DISCLAIMER_SKIP=1"
%PY% web_panel.py

echo.
echo [STOP] Web panel stopped.
pause
