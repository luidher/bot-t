@echo off
setlocal enabledelayedexpansion
title Bot Autopilot — Instalador de Dependencias
color 0B

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║        BOT AUTOPILOT — INSTALADOR v1.0              ║
echo  ║    Instala todas las dependencias necesarias         ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: ─────────────────────────────────────────────────────────
:: PASO 1: Verificar Python 3.11 o 3.12
:: ─────────────────────────────────────────────────────────
echo [1/6] Buscando Python compatible (3.11 o 3.12)...
echo.

set PYTHON_CMD=
set PYTHON_VERSION=

:: Intentar py launcher con versiones especificas
for %%V in (3.12 3.11) do (
    if "!PYTHON_CMD!"=="" (
        py -%%V --version >nul 2>nul
        if not errorlevel 1 (
            set PYTHON_CMD=py -%%V
            for /f "tokens=2" %%i in ('py -%%V --version 2^>^&1') do set PYTHON_VERSION=%%i
        )
    )
)

:: Fallback: python directo
if "%PYTHON_CMD%"=="" (
    python --version >nul 2>nul
    if not errorlevel 1 (
        for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
        :: Validar que sea 3.11 o 3.12
        for /f "tokens=1,2 delims=." %%a in ("!PYTHON_VERSION!") do (
            if "%%a"=="3" (
                if "%%b"=="11" set PYTHON_CMD=python
                if "%%b"=="12" set PYTHON_CMD=python
            )
        )
    )
)

if "%PYTHON_CMD%"=="" (
    echo.
    echo  [ERROR] No se encontro Python 3.11 ni 3.12 en tu sistema.
    echo.
    echo  Instala Python desde:
    echo    https://www.python.org/downloads/windows/
    echo.
    echo  IMPORTANTE al instalar:
    echo    - Marca "Add python.exe to PATH"
    echo    - Elige version 3.11 o 3.12
    echo.
    pause
    exit /b 1
)

echo  [OK] Python encontrado: %PYTHON_CMD% ^(%PYTHON_VERSION%^)
echo.

:: ─────────────────────────────────────────────────────────
:: PASO 2: Crear entorno virtual
:: ─────────────────────────────────────────────────────────
echo [2/6] Preparando entorno virtual (venv)...
echo.

set VENV_PYTHON=venv\Scripts\python.exe
set VENV_PIP=venv\Scripts\pip.exe
set NEED_CREATE=0

if not exist "venv\Scripts\activate.bat" (
    set NEED_CREATE=1
) else (
    venv\Scripts\python.exe --version >nul 2>nul
    if errorlevel 1 (
        echo  [AVISO] El venv existente esta danado. Recreando...
        set NEED_CREATE=1
    )
)

if "%NEED_CREATE%"=="1" (
    if exist "venv" (
        echo  Eliminando venv anterior...
        rmdir /s /q "venv"
    )
    echo  Creando nuevo entorno virtual...
    %PYTHON_CMD% -m venv venv
    if errorlevel 1 (
        echo.
        echo  [ERROR] No se pudo crear el entorno virtual.
        echo  Verifica que Python este bien instalado.
        pause
        exit /b 1
    )
    echo  [OK] Entorno virtual creado.
) else (
    echo  [OK] Entorno virtual existente y funcional.
)
echo.

:: ─────────────────────────────────────────────────────────
:: PASO 3: Actualizar pip
:: ─────────────────────────────────────────────────────────
echo [3/6] Actualizando pip...
echo.

"%VENV_PYTHON%" -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo  [AVISO] No se pudo actualizar pip. Continuando con la version actual...
) else (
    echo  [OK] pip actualizado.
)
echo.

:: ─────────────────────────────────────────────────────────
:: PASO 4: Instalar dependencias de Python
:: ─────────────────────────────────────────────────────────
echo [4/6] Instalando dependencias de Python...
echo  (Esto puede tardar varios minutos la primera vez)
echo.

"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ERROR] Fallo la instalacion de dependencias.
    echo  Intenta ejecutar este script como Administrador.
    echo.
    pause
    exit /b 1
)

echo.
echo  [OK] Dependencias de Python instaladas correctamente.
echo.

:: ─────────────────────────────────────────────────────────
:: PASO 5: Instalar navegadores de Playwright (Chromium)
:: ─────────────────────────────────────────────────────────
echo [5/6] Instalando navegador Chromium para Playwright...
echo  (Descarga ~200MB — puede tardar segun tu conexion)
echo.

"%VENV_PYTHON%" -m playwright install chromium
if errorlevel 1 (
    echo.
    echo  [AVISO] Fallo la instalacion de Chromium via Playwright.
    echo  El bot necesita Chromium para funcionar.
    echo  Intenta ejecutar manualmente:
    echo    venv\Scripts\python.exe -m playwright install chromium
    echo.
    set PLAYWRIGHT_OK=0
) else (
    echo.
    echo  [OK] Chromium instalado correctamente.
    set PLAYWRIGHT_OK=1
)
echo.

:: ─────────────────────────────────────────────────────────
:: PASO 6: Instalar dependencias del sistema de Playwright
:: ─────────────────────────────────────────────────────────
echo [6/6] Verificando dependencias del sistema para Playwright...
echo.

"%VENV_PYTHON%" -m playwright install-deps chromium >nul 2>nul
if errorlevel 1 (
    echo  [INFO] install-deps no aplica en Windows (es solo para Linux). OK.
) else (
    echo  [OK] Dependencias del sistema verificadas.
)
echo.

:: ─────────────────────────────────────────────────────────
:: RESUMEN FINAL
:: ─────────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║              INSTALACION COMPLETADA                  ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  Dependencias instaladas en: %~dp0venv
echo.
echo  Para iniciar el bot, usa uno de estos archivos:
echo.
echo    iniciar_autopilot.bat  — Modo Autopilot (sin interfaz)
echo    iniciar_web.bat        — Consola web en el navegador
echo    iniciar_widget.bat     — Widget de escritorio (PyQt5)
echo.

if "%PLAYWRIGHT_OK%"=="0" (
    echo  [!] ATENCION: Playwright/Chromium no se instalo correctamente.
    echo      El bot NO podra navegar sin el navegador.
    echo      Ejecuta manualmente:
    echo        venv\Scripts\python.exe -m playwright install chromium
    echo.
)

echo  Presiona cualquier tecla para cerrar este instalador.
pause >nul
endlocal
