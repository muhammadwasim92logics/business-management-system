$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectPath
& "$projectPath\.venv\Scripts\python.exe" manage.py check_notifications