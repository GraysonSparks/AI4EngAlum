@echo off
rem Opens a PowerShell window that runs the assistant. Ctrl+C in that window stops everything.
start "AI4EngAlum assistant" powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0start.ps1"
