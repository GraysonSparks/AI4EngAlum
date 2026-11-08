# Shared settings for setup.ps1, start.ps1, stop.ps1 and status.ps1. Not meant to be run on its own.
# Everything is pinned to what the Linux desktop runs, so answers on the laptop match the desktop.

$Root = Split-Path -Parent $PSScriptRoot          # 3_Code\
$RagDir = Join-Path $Root "rag"

# Kept outside the project folder, like ~/.local/share/venvs on Linux, so a synced or shared copy of the code stays clean.
$DataDir = Join-Path $env:LOCALAPPDATA "AI4EngAlum"
$VenvDir = Join-Path $DataDir "venv"
$Python = Join-Path $VenvDir "Scripts\python.exe"

$PythonVersion = "3.12.14"
$OllamaVersion = "0.40.6"
# 127.0.0.1, not localhost: Ollama listens on IPv4 only, and Windows tries ::1 first.
$OllamaUrl = "http://127.0.0.1:11434"
$AppPort = 8000
$AppUrl = "http://127.0.0.1:$AppPort/"   # 127.0.0.1 for the same reason as Ollama

# Model tags and the exact digests the desktop uses. A different digest means the tag was updated upstream.
$Models = [ordered]@{
    "qwen3.5:9b"              = "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7"
    "nomic-embed-text:latest" = "0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f"
}
$ChatModel = "qwen3.5:9b"

# config.py reads these. The index and visitor requests stay outside the project folder; UTF-8 matches
# how Linux reads the content files; no __pycache__ gets written into the project folder.
$env:CHROMA_DIR = Join-Path $DataDir "chroma_db"
$env:OLLAMA_URL = $OllamaUrl
$env:CONTACT_REQUESTS_FILE = Join-Path $DataDir "data\contact_requests.jsonl"
$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONUNBUFFERED = "1"   # so test output appears as it runs

# uv and Ollama install per user; make sure this window can find them even right after installing.
$env:Path = "$env:USERPROFILE\.local\bin;$env:LOCALAPPDATA\Programs\Ollama;$env:Path"

function Write-Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }
function Fail($msg) {
    Write-Host ""
    Write-Host "FAILED: $msg" -ForegroundColor Red
    exit 1
}
function Write-Banner($msg, $color) {
    $line = "=" * ($msg.Length + 4)
    Write-Host ""
    Write-Host $line -ForegroundColor $color
    Write-Host "  $msg" -ForegroundColor $color
    Write-Host $line -ForegroundColor $color
}

function Test-OllamaUp {
    try { Invoke-RestMethod "$OllamaUrl/api/version" -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

function Start-Ollama {
    if (Test-OllamaUp) { return }
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Fail "Ollama is not installed. Run Setup.bat first." }
    # Its output goes to a log, so a failed start can say why.
    New-Item -ItemType Directory -Force $DataDir | Out-Null
    $log = Join-Path $DataDir "ollama-serve.log"
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden -RedirectStandardError $log -RedirectStandardOutput "$log.out"
    # The first start after a reboot or driver update can spend a while detecting the GPU.
    for ($i = 0; $i -lt 90; $i++) {
        if (Test-OllamaUp) { return }
        Start-Sleep -Seconds 1
    }
    if (Test-Path $log) { Write-Host ""; Get-Content $log -Tail 15 | ForEach-Object { Write-Host "    $_" } }
    Fail "Ollama did not start within 90 seconds. Its last messages are above (full log: $log)."
}

# Models Ollama currently has loaded, with how much of each is on the GPU.
function Get-LoadedModels {
    if (-not (Test-OllamaUp)) { return @() }
    return @((Invoke-RestMethod "$OllamaUrl/api/ps").models)
}

function Format-Placement($m) {
    if ($m.size -le 0) { return "unknown" }
    $gpu = [math]::Round(100 * $m.size_vram / $m.size)
    if ($gpu -ge 100) { return "100% GPU" }
    if ($gpu -le 0) { return "100% CPU" }
    return "$gpu% GPU / $(100 - $gpu)% CPU"
}

function Get-AppProcessId {
    $conn = Get-NetTCPConnection -LocalPort $AppPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) { return $conn.OwningProcess }
    return $null
}
