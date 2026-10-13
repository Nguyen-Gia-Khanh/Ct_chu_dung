@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Repository Python is missing. Run setup_venv.cmd first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m barcode_web.server %*
if errorlevel 1 (
    echo.
    echo Server could not start. See the error above.
    pause
)
