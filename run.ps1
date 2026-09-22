# Launch Warehouse Mapper always using the virtual environment
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

$VenvPython = if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    "$ScriptDir\.venv\Scripts\python.exe"
} elseif (Test-Path "$ScriptDir\..\..\.venv\Scripts\python.exe") {
    (Resolve-Path "$ScriptDir\..\..\.venv\Scripts\python.exe").Path
} else {
    "python"
}

& "$VenvPython" "$ScriptDir\warehouse_mapper.py" @args
