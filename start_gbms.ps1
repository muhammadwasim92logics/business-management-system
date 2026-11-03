$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectPath

Write-Host "Starting GBMS..." -ForegroundColor Green

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

. ".\.venv\Scripts\Activate.ps1"

Write-Host "Installing dependencies if needed..." -ForegroundColor Yellow
python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt | Out-Null

Write-Host "Applying database migrations..." -ForegroundColor Yellow
python manage.py migrate

Write-Host "Registering daily notification checks..." -ForegroundColor Yellow
$taskScript = Join-Path $projectPath "run_notification_checks.ps1"
$taskAction = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$taskScript`""
schtasks.exe /Create /TN "GBMS Notification Checks" /TR $taskAction /SC HOURLY /MO 1 /ST 00:05 /F | Out-Null

Write-Host "Opening application in browser..." -ForegroundColor Cyan
Start-Process "http://127.0.0.1:8000/"

Write-Host "Starting Django server..." -ForegroundColor Green
python manage.py runserver 127.0.0.1:8000
