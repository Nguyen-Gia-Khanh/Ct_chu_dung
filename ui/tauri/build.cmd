@echo off
rem Build the Tauri desktop app and place warehouse_mapper_tauri.exe in the project root.
rem Needs Node.js (npm) and the Rust MSVC toolchain; run setup_venv.cmd first for Python.
setlocal
cd /d "%~dp0"
if not exist node_modules call npm install || exit /b 1
call npx tauri build || exit /b 1
copy /y "src-tauri\target\release\warehouse-mapper.exe" "..\..\warehouse_mapper_tauri.exe" >nul || exit /b 1
echo Built ..\..\warehouse_mapper_tauri.exe
