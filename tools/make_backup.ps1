# Полный бэкап проекта на рабочий стол
# Запуск: powershell -ExecutionPolicy Bypass -File tools\make_backup.ps1

$src = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not (Test-Path (Join-Path $src "bot.py"))) {
    $src = "C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$dest = Join-Path $desktop "pdf-checker-bot-backup-$stamp"

New-Item -ItemType Directory -Path $dest -Force | Out-Null

robocopy $src $dest /E `
    /XD __pycache__ node_modules .venv venv .cursor agent-tools terminals `
    /XF *.pyc `
    /NFL /NDL /NJH /NJS /nc /ns /np

$files = (Get-ChildItem $dest -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "Готово: $dest"
Write-Host "Файлов: $files"
