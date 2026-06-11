# Abre el dashboard del Trading Bot; si el bot no está corriendo, lo arranca primero.
# Uso: doble clic en el acceso directo del escritorio, o .\scripts\start_dashboard.ps1

$ErrorActionPreference = "SilentlyContinue"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$Url = "http://127.0.0.1:8000/dashboard"

# Reactivar el guardián (por si el bot fue apagado con stop_bot.ps1)
Enable-ScheduledTask -TaskName "TradingBotKeepAlive" | Out-Null

# Ollama (gate de IA) también debe estar vivo
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 -UseBasicParsing | Out-Null
} catch {
    $ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path $ollamaExe) { Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden }
}

$alive = $false
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 -UseBasicParsing
    $alive = $response.StatusCode -eq 200
} catch {}

if (-not $alive) {
    Write-Output "Bot apagado - arrancando..."
    $env:PYTHONPATH = Join-Path $ProjectDir "src"
    Start-Process -FilePath (Join-Path $ProjectDir ".venv\Scripts\python.exe") `
        -ArgumentList "-m","uvicorn","trading_bot.main:app","--host","127.0.0.1","--port","8000" `
        -WorkingDirectory $ProjectDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $ProjectDir "logs\uvicorn_out.log") `
        -RedirectStandardError (Join-Path $ProjectDir "logs\uvicorn_err.log")
    # Esperar hasta 30s a que la API responda
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 2
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) { break }
        } catch {}
    }
}

Start-Process $Url
