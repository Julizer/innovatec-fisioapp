# Start server using venv Python and open browser
# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python found: $pythonVersion"
} catch {
    Write-Host "ERROR: Python is not installed or not in PATH. Please install Python 3.8+ and try again."
    exit 1
}

$venvDir = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirementsFile = Join-Path $PSScriptRoot "requirements.txt"

if (!(Test-Path $venvPython)) {
    Write-Host ".venv Python not found. Creating virtualenv and installing requirements..."

    # Create virtual environment
    try {
        python -m venv $venvDir
        Write-Host "Virtual environment created successfully."
    } catch {
        Write-Host "ERROR: Failed to create virtual environment. Please check your Python installation."
        exit 1
    }

    # Verify venv was created
    if (!(Test-Path $venvPython)) {
        Write-Host "ERROR: Virtual environment was not created properly."
        exit 1
    }

    # Upgrade pip in venv
    try {
        & $venvPython -m pip install --upgrade pip
        Write-Host "Pip upgraded successfully."
    } catch {
        Write-Host "WARNING: Failed to upgrade pip, continuing with existing version..."
    }

    # Install requirements
    if (Test-Path $requirementsFile) {
        try {
            & $venvPython -m pip install -r $requirementsFile
            Write-Host "Requirements installed successfully."
        } catch {
            Write-Host "ERROR: Failed to install requirements from $requirementsFile"
            exit 1
        }
    } else {
        Write-Host "WARNING: requirements.txt not found, skipping dependency installation."
    }
}

# Start the server
Write-Host "Starting Flask server..."
try {
    Start-Process -FilePath $venvPython -ArgumentList "`"$(Join-Path $PSScriptRoot "base de datos y backend\app.py")`"" -NoNewWindow
    Write-Host "Server started. Waiting for it to initialize..."
    Start-Sleep -Seconds 3

    # Check if server is responding
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:5000" -TimeoutSec 5 -ErrorAction Stop
        Write-Host "Server is responding. Opening browser..."
        Start-Process "http://127.0.0.1:5000"
    } catch {
        Write-Host "WARNING: Server may not be ready yet or there was an error. Please check http://127.0.0.1:5000 manually."
        Write-Host "You can also try running the server manually with: & $venvPython `"$(Join-Path $PSScriptRoot "base de datos y backend\app.py")`""
    }
} catch {
    Write-Host "ERROR: Failed to start the server. Please check the Python script and try again."
    exit 1
}
