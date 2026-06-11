# Arranca la API FastAPI (equivalente Windows de run_api.sh)
# Uso: .\scripts\run_api.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectDir

$env:PYTHONPATH = Join-Path $ProjectDir "src"
if (-not $env:DATABASE_URL) {
    $env:DATABASE_URL = "sqlite+aiosqlite:///./trading_bot.db"
}

$Uvicorn = Join-Path $ProjectDir ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $Uvicorn)) {
    Write-Error "No existe $Uvicorn. Crea el venv: python -m venv .venv"
}

& $Uvicorn trading_bot.main:app --reload --host 0.0.0.0 --port 8000
