@echo off
rem Stops the assistant and Ollama, then confirms the model is no longer running.
title AI4EngAlum stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
pause
