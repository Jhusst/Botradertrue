# Operación 24/7 en Windows

Guía para correr el bot desatendido en un PC Windows con capital chico.

## 1. Instalación como servicio (NSSM, recomendado)

NSSM reinicia el proceso ante crash, arranca al boot sin sesión iniciada y rota logs.

1. Descarga NSSM desde https://nssm.cc y agrega `nssm.exe` al PATH.
2. PowerShell **como Administrador**:

```powershell
cd D:\Proyectos\Botrader
.\scripts\install_service.ps1
```

3. Verifica: `curl http://127.0.0.1:8000/health/deep` (200 = sano, 503 = degradado).
4. Desinstalar: `.\scripts\uninstall_service.ps1`

### Plan B: Tarea Programada

Si no quieres NSSM: Programador de tareas → Crear tarea → Desencadenador "Al iniciar el equipo" →
Acción `D:\Proyectos\Botrader\.venv\Scripts\python.exe -m uvicorn trading_bot.main:app --port 8000`
(directorio de inicio: raíz del proyecto, variable `PYTHONPATH=src`) → pestaña Configuración:
"Reiniciar cada 1 minuto si la tarea falla". Limitación: no detecta procesos colgados (el watchdog
interno del bot mitiga esto).

## 2. Configuración de energía de Windows

- Panel de control → Energía → plan **Alto rendimiento**.
- Desactivar suspensión e hibernación: `powercfg /change standby-timeout-ac 0` y `powercfg /change hibernate-timeout-ac 0`.
- BIOS: activar "Restore AC Power Loss" para que el PC reencienda tras un corte de luz
  (con SQLite en modo WAL la base sobrevive cortes).
- Windows Update → Horas activas amplias para evitar reinicios en horario de mercado
  (cripto es 24/7: revisa actualizaciones manualmente cuando no haya posiciones abiertas).

## 3. Candados de seguridad (orden de defensa)

1. `LIVE_MODE_ENABLED=false` — nada toca dinero real hasta que lo actives.
2. `MAX_TOTAL_LOSS_USDT` — piso de equity absoluto: si se cruza, kill-switch + cierre de todo.
3. `FLATTEN_ON_PROTECTION_FAILURE=true` — si el SL no se puede colocar, la posición se cierra al instante.
4. Reconciliación cada 60 s — repone SLs cancelados y corrige divergencias DB↔exchange.
5. Watchdog — reinicia el monitor si se cuelga; NSSM reinicia el proceso si muere.

## 4. Emergencias por Telegram

Con `TELEGRAM_COMMANDS_ENABLED=true` (solo responde a tu `TELEGRAM_CHAT_ID`):

| Comando | Acción |
|-|-|
| `/status` | Equity, kill-switch, breaker, heartbeat |
| `/pause` | Pausar entradas nuevas (posiciones siguen protegidas) |
| `/resume` | Reanudar entradas |
| `/flatten CONFIRMAR` | Cerrar TODO a mercado y cancelar órdenes |
| `/kill CONFIRMAR` | Kill-switch: flatten + bloquear todo |
| `/close <id>` | Cerrar un trade concreto a mercado |

El rearme tras kill-switch es **solo** por API: `POST /api/v1/safety/arm` con `{"confirm": "ARM"}` —
decisión consciente, nunca un dedazo.

## 5. Checklist antes de pasar a LIVE

- [ ] `BINANCE_TESTNET=true` probado: matar el proceso a media entrada → al reiniciar repone SL o aplana.
- [ ] Cancelar el SL a mano en Binance → la reconciliación lo repone en <60 s.
- [ ] 100+ paper trades con profit factor > 1.3 y drawdown < 10 % (criterio del bot).
- [ ] API key de Binance **sin permiso de retiro** y con restricción de IP.
- [ ] `MAX_TOTAL_LOSS_USDT` ajustado a lo que de verdad estás dispuesto a perder.
