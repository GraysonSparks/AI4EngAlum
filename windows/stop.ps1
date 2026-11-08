# Stops the assistant, unloads the models from the GPU, quits Ollama, and checks that nothing is left.
# Start.bat runs this when you press Ctrl+C. Run Stop.bat yourself if you closed that window instead.

param([switch]$Quiet)   # setup.ps1 uses this to skip the final banner

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

Write-Step "Stopping the assistant"
$appPid = Get-AppProcessId
if ($appPid) {
    Stop-Process -Id $appPid -Force -ErrorAction SilentlyContinue
    Write-Ok "stopped (process $appPid)"
} else {
    Write-Ok "was not running"
}

Write-Step "Unloading the models"
foreach ($m in Get-LoadedModels) {
    & ollama stop $m.name
    Write-Ok "unloaded $($m.name)"
}
for ($i = 0; $i -lt 15 -and (Get-LoadedModels).Count -gt 0; $i++) { Start-Sleep -Seconds 1 }

Write-Step "Quitting Ollama"
Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
for ($i = 0; $i -lt 10 -and (Get-Process -Name "ollama*" -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Seconds 1 }

# Check, don't assume: no Ollama process (so nothing holds GPU memory) and nothing on the app's port.
$leftOllama = @(Get-Process -Name "ollama*" -ErrorAction SilentlyContinue)
$leftApp = Get-AppProcessId
if ($leftOllama.Count -gt 0 -or $leftApp) {
    if ($leftOllama.Count -gt 0) { Write-Warn "still running: $(($leftOllama | ForEach-Object { "$($_.Name) ($($_.Id))" }) -join ', ')" }
    if ($leftApp) { Write-Warn "port $AppPort is still in use by process $leftApp" }
    Write-Banner "NOT FULLY STOPPED. Run Stop.bat again, or end those processes in Task Manager." Red
    exit 1
}
Write-Ok "no Ollama processes left, port $AppPort is free"
if (-not $Quiet) { Write-Banner "STOPPED. The model is not running and its GPU memory is free." Green }
