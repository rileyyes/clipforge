@echo off
rem Double-click to start ClipForge (first run sets everything up).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\start.ps1" %*
if errorlevel 1 if not defined CI pause
