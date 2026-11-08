@echo off
rem Shows whether the assistant, Ollama and the model are running. Changes nothing.
title AI4EngAlum status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0status.ps1"
pause
