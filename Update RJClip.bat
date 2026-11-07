@echo off
rem Double-click to get the latest RJClip from GitHub (incl. speech-to-text) and start it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start.ps1" -Update -WithAI %*
if errorlevel 1 if not defined CI pause
