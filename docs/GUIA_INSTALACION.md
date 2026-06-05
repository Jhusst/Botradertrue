# Guía de instalación — Trading Bot (uso local)

Esta guía es para que **tú y tus amigos** instalen el bot en **su propia computadora**, cada uno con **su cuenta de Binance** y **sus propias API keys**.

> **Importante:** No hay un servidor central compartido. Cada persona corre su copia del proyecto en local. Tus claves **nunca** deben compartirse ni subirse a GitHub.

---

## ¿Cómo funciona el modelo?

```
Tu amigo                    Otro amigo
   │                            │
   ▼                            ▼
Copia del repo              Copia del repo
   │                            │
   ▼                            ▼
Su .env (sus keys)          Su .env (sus keys)
   │                            │
   ▼                            ▼
Su Binance                  Su Binance
Su Telegram                 Su Telegram
Su trading_bot.db           Su trading_bot.db
```

- **Sí compartes:** el código del proyecto (zip, Git, USB).
- **No compartes:** archivo `.env`, API keys, tokens de Telegram, base de datos `trading_bot.db`.

---

## Requisitos

| Requisito | Detalle |
|-----------|---------|
| **Sistema** | Linux, macOS o Windows (con WSL recomendado en Windows) |
| **Python** | 3.11, 3.12, 3.13 o 3.14 |
| **Internet** | Para precios de Binance y alertas Telegram |
| **Cuenta Binance** | Con Futures (USDⓈ-M) activado — solo si quieres conectar broker |
| **Telegram** | Recomendado para alertas en el móvil |

Opcional (modo autónomo con IA):

- [Ollama](https://ollama.com) instalado y modelo `llama3.2`

---

## Paso 1 — Obtener el proyecto

### Opción A: Git

```bash
git clone <URL_DEL_REPOSITORIO> bot_traiding
cd bot_traiding
```

### Opción B: Archivo ZIP

1. Descomprime el zip en una carpeta, por ejemplo `~/bot_traiding`.
2. Abre terminal en esa carpeta.

---

## Paso 2 — Instalación automática

```bash
chmod +x scripts/*.sh
./scripts/setup.sh
```

Esto hace:

- Crea el entorno virtual `.venv`
- Instala dependencias (`requirements.txt`)
- Copia `.env.example` → `.env` si no existe

**Fish shell** (no uses `source .venv/bin/activate` de bash):

```fish
# Para arrancar basta con:
./scripts/run_api.sh
```

---

## Paso 3 — Configurar `.env` (cada quien el suyo)

Abre el archivo `.env` en la raíz del proyecto. **Cada amigo edita el suyo con sus datos.**

### 3.1 Telegram (recomendado)

Guía detallada: [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md)

```env
TELEGRAM_BOT_TOKEN=tu_token_de_botfather
TELEGRAM_CHAT_ID=tu_chat_id
```

Cada persona crea **su propio bot** en @BotFather o comparte un bot pero con **su propio chat_id**.

### 3.2 Binance API (tu cuenta, tus keys)

En Binance → **API Management** → Crear API:

| Permiso | ¿Activar? |
|---------|-----------|
| Habilitar lectura | ✅ Sí |
| Habilitar Futuros | ✅ Sí (si quieres broker/auto) |
| Habilitar Retiros | ❌ **NUNCA** |

```env
BINANCE_API_KEY=tu_clave_api
BINANCE_API_SECRET=tu_clave_secreta
```

- **Clave API** → `BINANCE_API_KEY`
- **Clave secreta** → `BINANCE_API_SECRET` (solo se muestra una vez al crearla)

**IP confiable (opcional):** en Binance añade la IP pública de la PC donde corre el bot:

```bash
curl https://api.ipify.org
```

Si la IP cambia (internet de casa), habrá que actualizarla en Binance.

### 3.3 Monedas a escanear

Por defecto (6 criptos):

```env
WATCH_SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT,AVAX/USDT,ADA/USDT,HYPE/USDT
```

Puedes quitar o añadir pares. **Menos pares = app más rápida.**

### 3.4 Balance para cálculo de riesgo

```env
DEFAULT_ACCOUNT_BALANCE=60.0
```

También puedes cambiarlo en el dashboard (perfil Conservador / Agresivo).

---

## Paso 4 — Modos de uso (elige uno)

### Modo 1 — Solo señales (más seguro para empezar)

Recibes alertas y ves el dashboard. **Operas manual** en Bitunix, Binance u otro exchange.

```env
MONITOR_ENABLED=true
MONITOR_USE_LIVE_DATA=true
AUTO_PAPER_TRADE=true
BROKER_ENABLED=false
LIVE_MODE_ENABLED=false
AUTONOMOUS_TRADING_ENABLED=false
```

No necesitas API keys de Binance para **precios** (son públicos). Las keys solo hacen falta si quieres ver balance en el dashboard.

### Modo 2 — Binance conectado (lectura + registro manual)

Ves balance y posiciones en el dashboard. Entradas manuales con apalancamiento personalizado.

```env
BROKER_ENABLED=true
LIVE_MODE_ENABLED=false
AUTONOMOUS_TRADING_ENABLED=false
```

### Modo 3 — Bot autónomo (avanza con cuidado)

El monitor entra solo cuando el precio toca la entrada (con filtros de riesgo e IA opcional).

```env
BROKER_ENABLED=true
LIVE_MODE_ENABLED=true
AUTONOMOUS_TRADING_ENABLED=true
AUTO_PAPER_TRADE=false
AI_ENABLED=true
AI_GATE_AUTO_TRADE=true
```

Requiere:

- Ollama corriendo: `ollama serve` y `ollama pull llama3.2`
- USDT en **Futuros USDⓈ-M** en Binance (no solo Spot)
- Capital suficiente (mínimo práctico ~10–20 USDT por órdenes pequeñas)

**Probar sin dinero real primero:**

```env
BINANCE_TESTNET=true
```

Cuenta y keys en [testnet.binancefuture.com](https://testnet.binancefuture.com).

---

## Paso 5 — Arrancar el bot

```bash
./scripts/run_api.sh
```

Deberías ver algo como:

```
Uvicorn running on http://0.0.0.0:8000
```

Abre en el navegador:

| URL | Qué es |
|-----|--------|
| http://localhost:8000/dashboard | Panel principal |
| http://localhost:8000/docs | API interactiva |
| http://localhost:8000/api/v1/broker/status | Estado Binance |
| http://localhost:8000/api/v1/setup/check | Diagnóstico |

---

## Paso 6 — Verificar que todo funciona

### Health

```bash
curl http://localhost:8000/health
```

### Binance conectado

```bash
curl http://localhost:8000/api/v1/broker/status
```

Busca:

- `"api_configured": true`
- `"account": { "connected": true, "message": "Conectado a Binance Futures" }`

### Telegram

```bash
curl -X POST http://localhost:8000/api/v1/setup/test-telegram
```

### Tests (opcional)

```bash
./scripts/run_tests.sh
```

---

## Uso diario del dashboard

1. **Mercados** — precios de las criptos configuradas.
2. **Señales** — entrada, SL, TP, apalancamiento sugerido.
3. **Copiar niveles** — pegar en tu exchange manual.
4. **Tu apalancamiento** — campo para registrar trade manual con otro lev (ej. Bitunix).
5. **Perfiles** — Conservador (10x máx) / Agresivo (20x máx).

El bot autónomo y tu entrada manual **pueden coexistir**: el bot puede operar en Binance y tú en otro exchange con otros niveles.

---

## Dejarlo corriendo

La terminal con `./scripts/run_api.sh` debe **seguir abierta** (o usar `tmux`, `screen`, systemd).

También necesitas:

- Internet estable
- Si usas IA autónoma: `ollama serve` en otra terminal

Telegram te avisa aunque no mires el dashboard.

---

## Seguridad — reglas para todos

1. **Nunca** subas `.env` a GitHub, Discord ni capturas públicas.
2. **Nunca** actives permiso de **retiros** en la API de Binance.
3. Cada quien usa **sus propias** API keys.
4. Si filtraste una key por error → revócala en Binance y crea una nueva.
5. El archivo `.env` está en `.gitignore` — no lo quites.
6. Empieza con **testnet** o capital muy bajo hasta entender el flujo.

---

## Solución de problemas

| Problema | Solución |
|----------|----------|
| `connected: false` en broker | Revisa API key/secret, permisos Futuros, IP en whitelist |
| Balance `0.0` | Transfiere USDT a wallet **Futuros** en Binance |
| App lenta | Reduce `WATCH_SYMBOLS` a menos monedas |
| Sin alertas Telegram | Revisa token, chat_id, y pulsa Start en tu bot |
| `BROKER_ENABLED=false` | Pon `BROKER_ENABLED=true` en `.env` y reinicia API |
| Error IP | `curl https://api.ipify.org` y actualiza en Binance |
| Primera carga lenta | Normal (~15 s); CCXT carga mercados la primera vez |

---

## Compartir con amigos — checklist

Para quien **distribuye** el proyecto:

- [ ] Comparte el código (git/zip), **sin** `.env` ni `trading_bot.db`
- [ ] Indica que lean esta guía
- [ ] Recuerda: **cada quien sus API keys**
- [ ] Recomienda empezar en Modo 1 (solo señales)

Para quien **instala**:

- [ ] `./scripts/setup.sh`
- [ ] Editar `.env` con sus datos
- [ ] `./scripts/run_api.sh`
- [ ] Abrir dashboard y probar `/api/v1/setup/check`
- [ ] Configurar Telegram
- [ ] (Opcional) Binance API y broker

---

## Variables `.env` — referencia rápida

| Variable | Descripción |
|----------|-------------|
| `BINANCE_API_KEY` | Clave API pública de Binance |
| `BINANCE_API_SECRET` | Clave secreta de Binance |
| `BINANCE_TESTNET` | `true` = futuros de prueba |
| `BROKER_ENABLED` | Conectar cuenta Binance |
| `LIVE_MODE_ENABLED` | Permitir órdenes reales |
| `AUTONOMOUS_TRADING_ENABLED` | Bot opera sin pulsar botones |
| `AUTO_PAPER_TRADE` | Simulación automática en paper |
| `WATCH_SYMBOLS` | Lista de pares a escanear |
| `TELEGRAM_BOT_TOKEN` | Token del bot de alertas |
| `TELEGRAM_CHAT_ID` | ID de chat de Telegram |
| `AI_ENABLED` | Usar Ollama para filtrar entradas |
| `DEFAULT_ACCOUNT_BALANCE` | Balance base para sizing |

Plantilla completa: `.env.example` en la raíz del proyecto.

---

## Más documentación

- [TELEGRAM_SETUP.md](TELEGRAM_SETUP.md) — Alertas paso a paso
- [ARCHITECTURE.md](ARCHITECTURE.md) — Cómo está armado el sistema
- [README.md](../README.md) — Resumen del proyecto

---

*Última actualización: junio 2025 — Bot semiautomático con dashboard, Binance Futures, modo manual y autónomo.*
