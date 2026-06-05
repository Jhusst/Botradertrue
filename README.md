# Trading Bot — Sistema Semiautomático de Señales

Bot de trading local con señales, gestión de riesgo, dashboard web, alertas Telegram y conexión opcional a **Binance Futures** (manual o autónomo).

Cada usuario corre **su propia copia** en su PC con **sus API keys** — no hay servidor compartido.

## Documentación

| Guía | Para quién |
|------|------------|
| **[docs/GUIA_INSTALACION.md](docs/GUIA_INSTALACION.md)** | Instalación completa (tú y tus amigos) |
| **[docs/BINANCE_SETUP.md](docs/BINANCE_SETUP.md)** | API keys de Binance por usuario |
| **[docs/TELEGRAM_SETUP.md](docs/TELEGRAM_SETUP.md)** | Alertas en el móvil |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Arquitectura técnica |

## Inicio rápido

```bash
chmod +x scripts/*.sh
./scripts/setup.sh
cp .env.example .env   # si setup no lo creó — edita con TUS claves
./scripts/run_api.sh
```

- **Dashboard**: http://localhost:8000/dashboard
- **API docs**: http://localhost:8000/docs
- **Diagnóstico**: http://localhost:8000/api/v1/setup/check

> **Compartir con amigos:** envía el código (git/zip), **nunca** el archivo `.env`. Cada quien pone sus keys. Ver [GUIA_INSTALACION.md](docs/GUIA_INSTALACION.md).

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Estado del sistema |
| GET | `/api/v1/signals` | Listar señales |
| GET | `/api/v1/signals/{id}` | Detalle de señal |
| POST | `/api/v1/signals/generate` | Generar señal (paper) |

### Ejemplo

```bash
# Health check
curl http://localhost:8000/health

# Generar señal (datos sintéticos, sin exchange)
curl -X POST "http://localhost:8000/api/v1/signals/generate?symbol=BTC/USDT&balance=10000&notify_telegram=false"

# Listar señales
curl http://localhost:8000/api/v1/signals

# Datos reales de Binance (requiere red)
curl -X POST "http://localhost:8000/api/v1/signals/generate?symbol=BTC/USDT&use_live_data=true&notify_telegram=false"
```

Documentación interactiva: http://localhost:8000/docs

## Alertas en tiempo real (no perder entradas)

Con Telegram configurado, el monitor envía:

1. **NUEVA SEÑAL** — cuando detecta un setup operable
2. **PRECIO CERCA DE ENTRADA** — cuando el precio está a <0.5% de la entrada
3. **🚨 ENTRA AHORA** — cuando el precio toca la entrada (notificación urgente)
4. **Paper trade abierto** — simulación automática si `AUTO_PAPER_TRADE=true`

El monitor arranca solo con la API (`MONITOR_ENABLED=true`). También puedes ejecutarlo aparte:

```bash
./scripts/run_monitor.sh
```

### Configurar Telegram

1. Habla con [@BotFather](https://t.me/BotFather) y crea un bot
2. Obtén tu `chat_id` con [@userinfobot](https://t.me/userinfobot)
3. Edita `.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321
MONITOR_USE_LIVE_DATA=true
PRICE_CHECK_INTERVAL_SECONDS=30
```

## Cómo probar el proyecto

### Paso 1 — Instalar

```bash
cd /home/cykes/Projects/bot_traiding
./scripts/setup.sh
source .venv/bin/activate
```

### Paso 2 — Ejecutar tests (26 tests)

```bash
./scripts/run_tests.sh
```

Debe mostrar: `26 passed`

### Paso 3 — Levantar la API

```bash
./scripts/run_api.sh
```

Por defecto usa **SQLite** (`trading_bot.db` en la raíz). No necesitas Docker para probar.

### Paso 4 — Probar endpoints

En otra terminal:

```bash
curl http://localhost:8000/health
curl -X POST "http://localhost:8000/api/v1/signals/generate?notify_telegram=false" | jq
curl http://localhost:8000/api/v1/signals | jq
```

O abre http://localhost:8000/docs y prueba desde el navegador.

### Paso 5 — Telegram (opcional)

Edita `.env`:

```
TELEGRAM_BOT_TOKEN=tu_token
TELEGRAM_CHAT_ID=tu_chat_id
```

Luego genera una señal con `notify_telegram=true`.

### Paso 6 — PostgreSQL (opcional, producción)

```bash
docker compose up -d
```

Cambia en `.env`:

```
DATABASE_URL=postgresql+asyncpg://trading:trading_dev@localhost:5432/trading_bot
```

## Arquitectura

Ver [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) para diagramas, flujos y criterios de desbloqueo de modo LIVE.

## Módulos

| Módulo | Estado |
|--------|--------|
| `risk_manager` | ✅ Implementado |
| `position_sizer` | ✅ Implementado |
| `strategy_engine` (TrendPullbackMVP) | ✅ Implementado |
| `signal_generator` | ✅ Implementado |
| `backtester` | ✅ MVP |
| `paper_trading` | ✅ Simulador |
| `telegram_alerts` | ✅ Implementado |
| `execution_engine` / Binance broker | ✅ Opcional (`BROKER_ENABLED`) |
| `ai_chart_analyzer` (Ollama) | ✅ Opcional |
| `dashboard` | ✅ HTML en `/dashboard` |
| `autonomous_trader` | ✅ Opcional (`AUTONOMOUS_TRADING_ENABLED`) |

## Reglas de riesgo

- Riesgo por trade: 0.25%–1% (hasta 1.5% manual en setup A)
- Pérdida máxima diaria: 2%
- Pérdida máxima semanal: 5%
- Bloqueo tras 2 pérdidas consecutivas
- R:R mínimo: 1:2
- Sin martingala, sin promediar pérdidas

## Modo LIVE (bloqueado)

Requisitos para activar ejecución real:

1. Backtest con profit factor > 1.3
2. Paper trading ≥ 100 operaciones
3. Drawdown aceptable (< 10%)
4. `LIVE_MODE_ENABLED=true` + confirmación manual

## Estructura

```
src/trading_bot/
├── api/              # FastAPI routes
├── config/           # Settings
├── core/             # Enums, excepciones
├── db/               # SQLAlchemy models
├── modules/
│   ├── data_collector/
│   ├── strategy_engine/
│   ├── risk_manager/
│   ├── position_sizer/
│   ├── signal_generator/
│   ├── backtester/
│   ├── paper_trading/
│   ├── telegram_alerts/
│   └── execution_engine/  (bloqueado)
└── schemas/          # Pydantic DTOs
```
