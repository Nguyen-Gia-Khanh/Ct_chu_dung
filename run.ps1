# Launch Warehouse Mapper always using the project's virtual environment
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir
& "$ScriptDir\.venv\Scripts\python.exe" "$ScriptDir\warehouse_mapper.py" @args
