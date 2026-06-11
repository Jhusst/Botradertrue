## Learned User Preferences

- Responder siempre en español.
- Usa Fish shell; preferir scripts con rutas directas a `.venv/bin/*` sin depender de `source .venv/bin/activate`.
- Quiere alertas Telegram cuando haya señales o entradas operables para no perder trades (p. ej. aviso "ENTRA AHORA").
- Es su primer bot de trading; necesita guías paso a paso claras para configurar y probar.
- Prefiere Binance para automatización (balance sync y órdenes); opera manualmente en Bitunix fuera del bot.
- Prioriza crecimiento controlado con riesgo limitado sobre rentabilidad agresiva; quiere evitar FOMO y quemar la cuenta.
- Meta de ingreso ~$20 USD/día; capital real en Binance Futures muy limitado (~decenas USDT, no los 10k del default).
- Quiere máxima automatización para ahorrar análisis, pero conservar señales consultables para entrada manual con otro apalancamiento.
- Planea compartir el bot con amigos: documentación de instalación local y cada quien con su `.env`/API keys.
- Es de México; busca un segundo ingreso dolarizado.

## Learned Workspace Facts

- Bot semiautomático Python/FastAPI: señales, paper trading y ejecución opcional en Binance Futures.
- Dashboard en `http://localhost:8000/dashboard`; la API corre solo en local — sin acceso remoto salvo PC encendido + túnel.
- Datos de mercado y broker vía CCXT/Binance; Bitunix no está en CCXT — operación manual allí. Binance API requiere permiso Futures + IP whitelist; error `-2015` si mal configurada.
- SQLite por defecto (`trading_bot.db`); arranque con `./scripts/run_api.sh`; reiniciar tras cambios en `.env`.
- Monitor en background (escaneo ~5 min, precios ~30 seg) + módulo `/api/v1/monitoring/` y panel dashboard del ciclo de trades.
- Telegram: `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en `.env`; el usuario debe pulsar Start en el bot.
- Modo LIVE requiere `BROKER_ENABLED`, `LIVE_MODE_ENABLED` y `AUTONOMOUS_TRADING_ENABLED`; por defecto paper. Gate `min_paper_trades_for_live=100` en settings.
- Código por features en `src/trading_bot/features/` + `infrastructure/`; ver `docs/ARCHITECTURE.md` y `docs/GUIA_INSTALACION.md`.
- Watchlist: BTC, ETH, SOL, AVAX, ADA, HYPE (+ estrategias oro/plata).
- Perfiles conservador/agresivo con balance editable; `ACTIVE_PROFILE_TYPES` define cuál opera (usuario usa solo agresivo sincronizado con Binance).
- IA local Ollama (`qwen2.5:7b`, `scripts/run_ollama.sh`) filtra entradas con `AI_GATE_AUTO_TRADE`; auto-entrada solo con veredicto ≥ CONFIRM (CAUTION bloquea).
- `scripts/clean_trade_history.py` limpia historial; fallo del broker live no crea OPEN local sin orden confirmada en Binance.
