@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
) else if exist "%~dp0..\..\.venv\Scripts\activate.bat" (
    call "%~dp0..\..\.venv\Scripts\activate.bat"
)

python warehouse_mapper.py %*
