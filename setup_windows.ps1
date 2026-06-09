param(
    [string]$Model = "llama3.1",
    [string]$OllamaHost = "http://localhost:11434",
    [string]$TesseractPath = "C:\Program Files\Tesseract-OCR\tesseract.exe",
    [switch]$DiagnosticsOnly
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )

    if ($Python.Args.Count -gt 0) {
        & $Python.Command @($Python.Args) @Arguments
    } else {
        & $Python.Command @Arguments
    }
}

function Get-PythonVersion {
    param([hashtable]$Python)

    $code = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    $output = Invoke-Python -Python $Python -Arguments @("-c", $code) 2>$null
    if (-not $output) {
        return $null
    }

    return [version]($output | Select-Object -First 1)
}

function Find-CompatiblePython {
    $candidates = @()

    if (Test-CommandExists "py") {
        $candidates += @{ Label = "py -3.12"; Command = "py"; Args = @("-3.12") }
        $candidates += @{ Label = "py -3.11"; Command = "py"; Args = @("-3.11") }
    }

    if (Test-CommandExists "python") {
        $candidates += @{ Label = "python"; Command = "python"; Args = @() }
    }

    foreach ($candidate in $candidates) {
        try {
            $version = Get-PythonVersion -Python $candidate
            if ($version -and $version.Major -eq 3 -and $version.Minor -ge 11 -and $version.Minor -le 12) {
                $candidate.Version = $version
                return $candidate
            }
        } catch {
            continue
        }
    }

    return $null
}

function Find-Tesseract {
    param([string]$PreferredPath)

    if (Test-Path $PreferredPath) {
        return $PreferredPath
    }

    $command = Get-Command "tesseract" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    return $null
}

function Test-OllamaHttp {
    param([string]$HostUrl)

    $cleanHost = $HostUrl.TrimEnd("/")
    try {
        return Invoke-RestMethod -Uri "$cleanHost/api/tags" -TimeoutSec 4
    } catch {
        return $null
    }
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$problems = New-Object System.Collections.Generic.List[string]

Write-Host "Vision Bot Windows setup" -ForegroundColor White
Write-Host "Proyecto: $projectRoot"
Write-Host "Modo: $(if ($DiagnosticsOnly) { 'diagnostico' } else { 'setup' })"

Write-Step "Validando Python 3.11/3.12"
$python = Find-CompatiblePython
if ($python) {
    Write-Ok "Python compatible encontrado: $($python.Label) ($($python.Version))"
} else {
    Write-Fail "No se encontro Python 3.11 o 3.12 en PATH."
    Write-Host "Instala Python desde https://www.python.org/downloads/windows/ y marca 'Add python.exe to PATH'."
    $problems.Add("Python 3.11/3.12 no disponible.")
}

Write-Step "Validando Tesseract OCR"
$tesseract = Find-Tesseract -PreferredPath $TesseractPath
if ($tesseract) {
    Write-Ok "Tesseract encontrado: $tesseract"
    try {
        $tessVersion = & $tesseract --version 2>$null | Select-Object -First 1
        if ($tessVersion) {
            Write-Host "     $tessVersion"
        }
    } catch {
        Write-Warn "Tesseract existe, pero no se pudo ejecutar --version."
    }
} else {
    Write-Fail "No se encontro Tesseract OCR."
    Write-Host "Instalalo y verifica que exista: $TesseractPath"
    Write-Host "Tambien puedes ejecutar este script con -TesseractPath 'C:\ruta\tesseract.exe'."
    $problems.Add("Tesseract OCR no disponible.")
}

Write-Step "Validando Ollama"
if (Test-CommandExists "ollama") {
    Write-Ok "Comando ollama encontrado."
} else {
    Write-Warn "No se encontro el comando ollama en PATH."
    Write-Host "Instala Ollama desde https://ollama.com/download y reinicia PowerShell."
    $problems.Add("Ollama CLI no disponible.")
}

$tags = Test-OllamaHttp -HostUrl $OllamaHost
if ($tags) {
    Write-Ok "Ollama responde en $OllamaHost"
    $models = @($tags.models | ForEach-Object { $_.name })
    if ($models.Count -gt 0) {
        Write-Host "     Modelos: $($models -join ', ')"
    } else {
        Write-Warn "Ollama responde, pero no reporta modelos descargados."
    }

    $modelFound = $false
    foreach ($name in $models) {
        if ($name -eq $Model -or $name.StartsWith("$Model" + ":")) {
            $modelFound = $true
            break
        }
    }

    if ($modelFound) {
        Write-Ok "Modelo requerido encontrado: $Model"
    } else {
        Write-Warn "No se encontro el modelo '$Model'."
        Write-Host "Ejecuta: ollama pull $Model"
        $problems.Add("Modelo Ollama '$Model' no descargado.")
    }
} else {
    Write-Fail "Ollama no responde en $OllamaHost."
    Write-Host "Abre Ollama o ejecuta 'ollama serve', luego vuelve a correr este script."
    $problems.Add("Servicio Ollama no responde.")
}

if (-not $DiagnosticsOnly -and $python) {
    Write-Step "Preparando entorno virtual"
    $venvPython = Join-Path $projectRoot "venv\Scripts\python.exe"
    $venvOk = $false

    if (Test-Path $venvPython) {
        try {
            & $venvPython --version >$null 2>$null
            if ($LASTEXITCODE -eq 0) {
                $venvOk = $true
                Write-Ok "venv existente funciona."
            }
        } catch {
            $venvOk = $false
        }
    }

    if (-not $venvOk) {
        if (Test-Path "venv") {
            Write-Warn "venv existe, pero no funciona. Eliminalo manualmente si quieres recrearlo:"
            Write-Host "     Remove-Item -Recurse -Force .\venv"
            $problems.Add("venv roto detectado; requiere recreacion manual.")
        } else {
            Write-Host "Creando venv..."
            Invoke-Python -Python $python -Arguments @("-m", "venv", "venv")
            Write-Ok "venv creado."
        }
    }

    if (Test-Path $venvPython) {
        Write-Step "Instalando dependencias bloqueadas"
        & $venvPython -m pip install --upgrade pip
        & $venvPython -m pip install -r requirements.txt
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Dependencias instaladas."
        } else {
            Write-Fail "pip fallo al instalar dependencias."
            $problems.Add("Instalacion de dependencias fallo.")
        }
    }
}

Write-Step "Resumen"
if ($problems.Count -eq 0) {
    Write-Ok "Diagnostico limpio. El proyecto esta listo para ejecutarse."
    Write-Host "Para iniciar la consola web:"
    Write-Host "     .\venv\Scripts\python.exe web_app.py"
    exit 0
}

Write-Fail "Se encontraron $($problems.Count) problema(s):"
foreach ($problem in $problems) {
    Write-Host " - $problem"
}
exit 1
