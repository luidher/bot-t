@echo off
title Vision Bot Widget Launcher
color 05

echo ===================================================
echo             Vision Bot PyQt5 Widget Loader
echo ===================================================
echo.

cd /d "%~dp0"

set NEED_CREATE=0

:: Check if virtual environment exists and its Python executable still works
if not exist "venv\Scripts\activate.bat" (
    set NEED_CREATE=1
) else (
    venv\Scripts\python.exe --version >nul 2>nul
    if errorlevel 1 (
        echo [WARNING] El entorno virtual existe, pero su Python interno no arranca.
        set NEED_CREATE=1
    )
)

if "%NEED_CREATE%"=="1" (
    echo [INFO] Recreando entorno virtual venv...
    if exist "venv" rmdir /s /q "venv"
    echo.
    py -3.12 -m venv venv
    if errorlevel 1 (
        py -m venv venv
    )
    if errorlevel 1 (
        python -m venv venv
    )
    if not exist "venv\Scripts\activate.bat" (
        echo [ERROR] No se pudo crear el venv. Asegurate de tener Python instalado y en el PATH.
        echo         Requisito: Python 3.11 o 3.12.
        pause
        exit /b 1
    )
    echo [INFO] Entorno virtual creado con exito.
)

echo [INFO] Activando entorno virtual...
call venv\Scripts\activate.bat

echo [INFO] Validando dependencias...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [WARNING] Hubo un problema al instalar dependencias. Intentando continuar...
)

echo.
echo [START] Iniciando Widget de Vision Bot...
echo.
start "" venv\Scripts\pythonw.exe widget.py

exit /b 0
