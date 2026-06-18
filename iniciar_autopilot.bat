@echo off
title Autopilot DB — Standalone
cd /d "%~dp0"
echo Iniciando Autopilot Standalone...
venv\Scripts\python.exe autopilot_standalone.py
if errorlevel 1 (
    echo.
    echo [ERROR] El programa cerro con un error. Revisa la consola.
    pause
)
