# APAGA el Trading Bot por completo (hasta que lo vuelvas a encender):
# 1. Desactiva el guardián (para que no lo reviva)
# 2. Mata el bot y Ollama (libera RAM/CPU)
# Nota: si hay posiciones abiertas, sus SL/TP viven EN Binance y siguen
# protegiéndote — pero no habrá alertas ni gestión hasta reencender.

$ErrorActionPreference = "SilentlyContinue"

# 1. Guardián fuera
Disable-ScheduledTask -TaskName "TradingBotKeepAlive" | Out-Null

# 2. Bot fuera (uvicorn y sus hijos)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "uvicorn|spawn_main" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 3. Ollama fuera (es lo que más memoria consume)
Get-Process ollama* | Stop-Process -Force

# Confirmación visual
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show(
    "Trading Bot APAGADO (bot + guardian + IA).`nPara encenderlo: doble clic en 'Trading Bot Dashboard'.",
    "Trading Bot", "OK", "Information") | Out-Null
