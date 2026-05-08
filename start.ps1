# Start server using venv Python and open browser
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (!(Test-Path $venvPython)) {
    Write-Host ".venv Python not found. Creating virtualenv and installing requirements..."
    python -m venv .venv
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
}
# Start the server
Start-Process -FilePath $venvPython -ArgumentList '"base de datos y backend\app.py"'
Start-Sleep -Seconds 1
Start-Process "http://127.0.0.1:5000"
