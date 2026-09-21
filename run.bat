@echo off
setlocal
cd /d "%~dp0"
call "%~dp0.venv\Scripts\activate.bat"
python warehouse_mapper.py %*
