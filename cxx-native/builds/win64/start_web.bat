@echo off
rem Windows one-click web panel launcher.
rem Usage: start_web.bat [data_dir]
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  set "DATA=%LOCALAPPDATA%\BiliLearn"
) else (
  set "DATA=%~1"
)
echo [OK] data dir: %DATA%
start "" /min bili.exe -data "%DATA%" -web 8080
timeout /t 3 /nobreak >nul
start http://127.0.0.1:8080
