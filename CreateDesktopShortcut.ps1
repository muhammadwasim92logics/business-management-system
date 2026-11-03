$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$shortcutPath = [Environment]::GetFolderPath('Desktop') + '\GBMS.lnk'
$target = Join-Path $projectPath 'start_gbms_hidden.vbs'
$sourcePng = Join-Path $projectPath 'static\img\desktop_icon.png'
$icon = Join-Path $projectPath 'static\img\desktop_icon.ico'

if (-not (Test-Path $icon) -or ((Get-Item $icon).Length -lt 1024)) {
    if (Test-Path $sourcePng) {
        $pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
        if (-not (Test-Path $pythonPath)) {
            $pythonPath = 'python'
        }

        $iconScript = @'
from PIL import Image
src = 'static/img/desktop_icon.png'
out = 'static/img/desktop_icon.ico'
img = Image.open(src).convert('RGBA')
img.save(out, format='ICO')
'@

        $scriptPath = Join-Path $projectPath 'tmp_build_icon.py'
        Set-Content -Path $scriptPath -Value $iconScript -Encoding UTF8
        & $pythonPath $scriptPath
        Remove-Item $scriptPath -Force
    }
}

if (-not (Test-Path $icon)) {
    $icon = Join-Path $projectPath 'static\img\favicon.ico'
}
if (-not (Test-Path $icon)) {
    $icon = Join-Path $projectPath 'static\img\favicon.png'
}
if (-not (Test-Path $icon)) {
    $icon = '%SystemRoot%\\System32\\Shell32.dll'
}

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
}

$WScriptShell = New-Object -ComObject WScript.Shell
$shortcut = $WScriptShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $projectPath
$shortcut.IconLocation = $icon
$shortcut.WindowStyle = 7
$shortcut.Description = 'GBMS - Gas Business Management System'
$shortcut.Save()

Write-Host "Desktop shortcut created: $shortcutPath" -ForegroundColor Green
Write-Host "Target: $target" -ForegroundColor Cyan
Write-Host "Using icon: $icon" -ForegroundColor Cyan
