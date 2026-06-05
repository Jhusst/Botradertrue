## Learned User Preferences

- Responder siempre en español.
- Usa Fish shell; preferir scripts con rutas directas a `.venv/bin/*` sin depender de `source .venv/bin/activate`.
- Quiere alertas Telegram cuando haya señales o entradas operables para no perder trades (p. ej. aviso "ENTRA AHORA").
- Es su primer bot de trading; necesita guías paso a paso claras para configurar y probar.
- Opera en Bitunix en real; objetivo: segundo ingreso y dolarización desde México.
- Prioriza crecimiento controlado con riesgo limitado sobre rentabilidad agresiva.

## Learned Workspace Facts

- Bot semiautomático Python/FastAPI: genera señales y paper trading; no ejecuta en real al inicio.
- Dashboard en `http://localhost:8000/dashboard`, servido por la API FastAPI.
- Datos de mercado vía CCXT con Binance (público); Bitunix no está en CCXT — el usuario opera ahí manualmente.
- SQLite por defecto (`trading_bot.db`); arranque con `./scripts/run_api.sh`.
- Monitor en background al levantar la API (escaneo ~5 min, vigilancia de precios ~30 seg).
- Telegram se configura con `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en `.env`; la simulación no requiere acceso a la cuenta del exchange.
- Modo LIVE bloqueado hasta cumplir backtest, ≥100 operaciones paper positivas y confirmación manual.
