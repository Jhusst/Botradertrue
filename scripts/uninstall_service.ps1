# Desinstala el servicio TradingBot de NSSM.
# Uso (PowerShell como Administrador):  .\scripts\uninstall_service.ps1

$ErrorActionPreference = "Stop"
$ServiceName = "TradingBot"

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Error "NSSM no encontrado en PATH."
}

$existing = Get-Service $ServiceName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Output "El servicio $ServiceName no existe."
    exit 0
}

nssm stop $ServiceName
nssm remove $ServiceName confirm
Write-Output "Servicio $ServiceName eliminado."
