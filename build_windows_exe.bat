@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller --noconfirm --clean BiliLearn.spec
if errorlevel 1 (
  echo.
  echo Build failed. Check the output above for the first error.
  exit /b %errorlevel%
)

echo.
echo Build complete: %CD%\dist\BiliLearn Web\BiliLearn Web.exe
endlocal
