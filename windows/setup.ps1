# One-time install for the Windows laptop. Safe to run again: each step skips what is already done.
#   Setup.bat            install everything, then run all checks (including the 63-case eval)
#   Setup.bat -SkipEval  same, without the eval (it takes a few minutes)

param([switch]$SkipEval)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow with the progress bar on
. "$PSScriptRoot\common.ps1"

Write-Host "AI4EngAlum setup: $Root"

Write-Step "Checking the GPU"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Ok (& nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader)
} else {
    Write-Warn "nvidia-smi not found. Update the NVIDIA driver, or the model will run on the CPU (much slower)."
}

Write-Step "Installing uv (Python installer)"
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Ok "already installed: $(& uv --version)"
} else {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail "uv did not install." }
    Write-Ok (& uv --version)
}

Write-Step "Creating Python $PythonVersion environment in $VenvDir"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$current = if (Test-Path $Python) { (& $Python --version) -replace "Python ", "" } else { "" }
if ($current -ne $PythonVersion) {
    if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
    & uv venv --python $PythonVersion $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "could not create the Python environment." }
}
Write-Ok (& $Python --version)

Write-Step "Installing the exact package versions (rag\requirements-windows.txt)"
# sync (not install) also removes anything that is not in the list, so the environment matches exactly.
& uv pip sync --python $Python (Join-Path $RagDir "requirements-windows.txt")
if ($LASTEXITCODE -ne 0) { Fail "package install failed." }
Write-Ok "packages installed"

Write-Step "Installing Ollama $OllamaVersion"
$have = ""
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    # With no server running it prints "client version is X"; prefer that over a running server's version.
    $text = (& ollama --version) -join " "
    if ($text -match "client version is (\d+\.\d+\.\d+)") { $have = $Matches[1] }
    elseif ($text -match "(\d+\.\d+\.\d+)") { $have = $Matches[1] }
}
if ($have -eq $OllamaVersion) {
    Write-Ok "already installed: $have"
} else {
    if ($have) { Write-Warn "found Ollama $have, replacing it with $OllamaVersion to match the desktop" }
    # Quit any running copy first, or the installer cannot replace its files.
    Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
    $installer = Join-Path $env:TEMP "OllamaSetup-$OllamaVersion.exe"
    Invoke-WebRequest "https://github.com/ollama/ollama/releases/download/v$OllamaVersion/OllamaSetup.exe" -OutFile $installer -UseBasicParsing
    # Wait for the installer only: -Wait would also wait for the Ollama tray app it launches at the end.
    $proc = Start-Process $installer -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -PassThru
    $proc.WaitForExit()
    Remove-Item $installer -ErrorAction SilentlyContinue
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Fail "Ollama did not install." }
    Write-Ok "installed: $(& ollama --version)"
}

Write-Step "Downloading the models (about 7 GB the first time)"
Start-Ollama
foreach ($name in $Models.Keys) {
    & ollama pull $name
    if ($LASTEXITCODE -ne 0) { Fail "could not download $name." }
}
$tags = (Invoke-RestMethod "$OllamaUrl/api/tags").models
$mismatch = $false
foreach ($name in $Models.Keys) {
    $digest = ($tags | Where-Object { $_.name -eq $name }).digest
    if ($digest -eq $Models[$name]) {
        Write-Ok "$name matches the desktop ($($digest.Substring(0, 12)))"
    } else {
        $mismatch = $true
        Write-Warn "$name is a different build than the desktop's (got $digest)."
    }
}
if ($mismatch) {
    Write-Warn "The model tag was updated upstream, so answers may differ from the desktop."
    Write-Warn "To match exactly, copy the files from the desktop (see windows\README.md)."
}

Write-Step "Building the search index (ingest.py)"
Push-Location $RagDir
try {
    & $Python ingest.py
    if ($LASTEXITCODE -ne 0) { Fail "ingest.py failed." }

    # The checks print FAIL (capitals, at the start of a line) for a failed case; eval_models.py sets no exit code.
    # Case-sensitive on purpose: test_notify.py has a passing check named "a failed webhook doesn't raise".
    $checks = @("test_contact.py", "test_notify.py", "test_chatlog.py", "test_recap.py")
    if (-not $SkipEval) { $checks += "eval_models.py" }
    $failed = @()
    foreach ($script in $checks) {
        Write-Step "Running $script"
        & $Python $script | Tee-Object -Variable out
        if ($LASTEXITCODE -ne 0 -or ($out -cmatch "^\s*FAIL")) { $failed += $script }
    }
} finally {
    Pop-Location
}

# Leave nothing running after setup; Start.bat starts it all again.
& "$PSScriptRoot\stop.ps1" -Quiet

if ($failed.Count -gt 0) {
    Write-Banner "SETUP FINISHED, BUT THESE CHECKS FAILED: $($failed -join ', ')" Red
    exit 1
}
Write-Banner "SETUP COMPLETE. Double-click Start.bat to run the assistant." Green
