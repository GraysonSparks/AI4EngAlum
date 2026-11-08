# Starts Ollama, loads the models onto the GPU, starts the assistant and opens the test site.
# Press Ctrl+C in this window to stop everything; it then confirms the model is no longer running.

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

if (-not (Test-Path $Python)) { Fail "the Python environment is missing. Run Setup.bat first." }
if (-not (Test-Path (Join-Path $env:CHROMA_DIR "chroma.sqlite3"))) { Fail "the search index is missing. Run Setup.bat first." }
if (Get-AppProcessId) { Fail "something is already using port $AppPort. Run Stop.bat, then try again." }

Write-Step "Starting Ollama"
Start-Ollama
Write-Ok "running at $OllamaUrl"

Write-Step "Loading the models"
# An empty request loads a model without generating anything. The app makes the same calls, so after
# 5 idle minutes Ollama unloads them on its own and the next question reloads them (a few seconds).
Invoke-RestMethod "$OllamaUrl/api/generate" -Method Post -ContentType "application/json" `
    -Body (@{ model = $ChatModel; think = $false } | ConvertTo-Json) | Out-Null
Invoke-RestMethod "$OllamaUrl/api/embed" -Method Post -ContentType "application/json" `
    -Body (@{ model = "nomic-embed-text"; input = "warm up" } | ConvertTo-Json) | Out-Null
foreach ($m in Get-LoadedModels) {
    $where = Format-Placement $m
    if ($where -eq "100% GPU") { Write-Ok "$($m.name): $where" }
    else { Write-Warn "$($m.name): $where. Close games or other GPU apps and restart for full speed." }
}

Write-Step "Starting the assistant"
$app = Start-Process $Python -ArgumentList "-m", "uvicorn", "app:app", "--port", $AppPort `
    -WorkingDirectory $RagDir -NoNewWindow -PassThru
try {
    $up = $false
    for ($i = 0; $i -lt 60 -and -not $app.HasExited; $i++) {
        try { Invoke-WebRequest $AppUrl -UseBasicParsing -TimeoutSec 2 | Out-Null; $up = $true; break } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $up) { Fail "the assistant did not start. See the messages above." }
    Start-Process $AppUrl
    Write-Banner "RUNNING at $AppUrl   (Ctrl+C here to stop everything)" Green
    Wait-Process -Id $app.Id
} finally {
    # Runs on Ctrl+C or if the server exits. Closing the window with the X skips this; use Stop.bat then.
    & "$PSScriptRoot\stop.ps1"
}
