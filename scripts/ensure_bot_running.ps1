# Guardián del bot: si la API no responde, lo arranca (idempotente, sin ventanas).
# Lo ejecuta el Programador de tareas al iniciar sesión y cada 5 minutos.

$ErrorActionPreference = "SilentlyContinue"
$ProjectDir = Split-Path -Parent $PSScriptRoot

try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing
    if ($response.StatusCode -eq 200) { exit 0 }  # ya está vivo
} catch {}

$env:PYTHONPATH = Join-Path $ProjectDir "src"
Start-Process -FilePath (Join-Path $ProjectDir ".venv\Scripts\python.exe") `
    -ArgumentList "-m","uvicorn","trading_bot.main:app","--host","127.0.0.1","--port","8000" `
    -WorkingDirectory $ProjectDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $ProjectDir "logs\uvicorn_out.log") `
    -RedirectStandardError (Join-Path $ProjectDir "logs\uvicorn_err.log")
