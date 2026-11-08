# Shows what is running right now: the assistant, Ollama, and which models are loaded (GPU or CPU).
# Changes nothing.

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

$appPid = Get-AppProcessId
$ollama = @(Get-Process -Name "ollama*" -ErrorAction SilentlyContinue)
$models = @(Get-LoadedModels)

Write-Step "Status"
if ($appPid) { Write-Ok "assistant: running at $AppUrl (process $appPid)" } else { Write-Host "    --  assistant: not running" }
if ($ollama.Count -gt 0) { Write-Ok "Ollama: running" } else { Write-Host "    --  Ollama: not running" }
if ($models.Count -eq 0) {
    Write-Host "    --  models: none loaded"
} else {
    foreach ($m in $models) {
        # Ollama sends nanoseconds; trim to what [datetime] can parse.
        try { $until = ([datetime]($m.expires_at -replace '(\.\d{1,7})\d*', '$1')).ToLocalTime().ToString("h:mm tt") }
        catch { $until = $m.expires_at }
        Write-Ok "model: $($m.name), $(Format-Placement $m), unloads itself at $until if idle"
    }
}

if (-not $appPid -and $ollama.Count -eq 0) { Write-Banner "NOTHING IS RUNNING." Green }
elseif ($models.Count -gt 0) { Write-Banner "A MODEL IS LOADED AND USING THE GPU. Stop.bat stops everything." Yellow }
else { Write-Banner "RUNNING, NO MODEL LOADED RIGHT NOW. Stop.bat stops everything." Yellow }
