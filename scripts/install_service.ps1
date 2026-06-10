# Instala el bot como servicio de Windows con NSSM (reinicio automático ante crash).
# Requisitos: NSSM en el PATH (https://nssm.cc) y venv creado en .venv
# Uso (PowerShell como Administrador):  .\scripts\install_service.ps1

$ErrorActionPreference = "Stop"

$ServiceName = "TradingBot"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LogsDir = Join-Path $ProjectDir "logs"

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Error "NSSM no encontrado. Descarga desde https://nssm.cc y agrega al PATH."
}
if (-not (Test-Path $PythonExe)) {
    Write-Error "No existe $PythonExe — crea el venv primero (python -m venv .venv)."
}
New-Item -ItemType Directory -Force $LogsDir | Out-Null

$existing = Get-Service $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Output "El servicio $ServiceName ya existe; actualizando configuración..."
    nssm stop $ServiceName
} else {
    nssm install $ServiceName $PythonExe "-m" "uvicorn" "trading_bot.main:app" "--host" "127.0.0.1" "--port" "8000"
}

nssm set $ServiceName AppDirectory $ProjectDir
nssm set $ServiceName AppEnvironmentExtra "PYTHONPATH=$ProjectDir\src"
nssm set $ServiceName AppExit Default Restart
nssm set $ServiceName AppThrottle 10000
nssm set $ServiceName AppStdout (Join-Path $LogsDir "service_stdout.log")
nssm set $ServiceName AppStderr (Join-Path $LogsDir "service_stderr.log")
nssm set $ServiceName AppRotateFiles 1
nssm set $ServiceName AppRotateBytes 10485760
nssm set $ServiceName Start SERVICE_AUTO_START

nssm start $ServiceName
Write-Output "Servicio $ServiceName instalado y arrancado. Logs en $LogsDir"
Write-Output "Healthcheck: curl http://127.0.0.1:8000/health/deep"
