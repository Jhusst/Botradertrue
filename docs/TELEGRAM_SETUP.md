# Cómo configurar Telegram (paso a paso)

No necesitas haber tenido un bot antes. Solo necesitas **Telegram en el móvil o PC** y **5 minutos**.

## ¿Por qué "no se puede conectar"?

El sistema **no falla** — simplemente **faltan dos datos en tu archivo `.env`** que solo tú puedes crear:

| Variable | Qué es | ¿Quién la genera? |
|----------|--------|-------------------|
| `TELEGRAM_BOT_TOKEN` | Contraseña de tu bot | Tú, con @BotFather |
| `TELEGRAM_CHAT_ID` | Tu número de usuario en Telegram | Tú, con @userinfobot |

Sin estos valores el código **no tiene a dónde enviar mensajes**. No es un bug: es como intentar enviar un WhatsApp sin número de teléfono.

**No necesitas API keys de Binance** para recibir señales — los precios son públicos.

---

## Paso 1: Crear el bot

1. Abre **Telegram**
2. Busca **@BotFather** (verificado, icono azul)
3. Envía: `/newbot`
4. Elige un nombre: `Mi Trading Alerts`
5. Elige un usuario: `mi_trading_alerts_bot` (debe terminar en `bot`)
6. BotFather te dará algo como:

```
1234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Eso es tu **TELEGRAM_BOT_TOKEN**. Cópialo completo.

---

## Paso 2: Obtener tu Chat ID

1. Busca **@userinfobot** en Telegram
2. Pulsa **Start** o envía `/start`
3. Te responderá con tu **Id**, por ejemplo: `987654321`

Eso es tu **TELEGRAM_CHAT_ID**.

> Si usas un grupo para alertas, añade el bot al grupo y usa @getidsbot para obtener el ID del grupo (número negativo).

---

## Paso 3: Hablar con tu bot (importante)

1. Busca tu bot por el usuario que creaste (`mi_trading_alerts_bot`)
2. Pulsa **Start** o envía `/start`

Si no haces esto, el bot no podrá enviarte mensajes la primera vez.

---

## Paso 4: Configurar el proyecto

Edita el archivo `.env` en la raíz del proyecto:

```env
TELEGRAM_BOT_TOKEN=1234567890:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_CHAT_ID=987654321
MONITOR_ENABLED=true
MONITOR_USE_LIVE_DATA=true
```

---

## Paso 5: Probar

```bash
./scripts/run_api.sh
```

En otra terminal:

```bash
curl -X POST http://localhost:8000/api/v1/setup/test-telegram
```

Deberías recibir en Telegram: **"Trading Bot conectado"**.

O abre el dashboard: http://localhost:8000/dashboard y pulsa **Probar conexión Telegram**.

---

## Qué alertas recibirás

| Alerta | Cuándo |
|--------|--------|
| NUEVA SEÑAL | El bot detecta un setup operable |
| PRECIO CERCA DE ENTRADA | El precio está a menos del 0.5% de tu entrada |
| 🚨 ENTRA AHORA | El precio tocó la entrada — momento de actuar |
| PAPER TRADE ABIERTO | Simulación automática (si está activada) |
| STOP LOSS / TAKE PROFIT | Cierre de la operación paper |

---

## Problemas comunes

| Problema | Solución |
|----------|----------|
| No llega el mensaje de prueba | Verifica token y chat_id. Pulsa Start en tu bot. |
| `chat not found` | Chat ID incorrecto o no iniciaste conversación con el bot |
| `Unauthorized` | Token incorrecto o copiado incompleto |
| No hay señales | Normal si el mercado no cumple reglas. Espera o revisa el dashboard. |

---

## Seguridad

- **Nunca** compartas tu `TELEGRAM_BOT_TOKEN` públicamente
- No lo subas a GitHub (`.env` está en `.gitignore`)
- Si se filtra, revócalo con @BotFather → `/revoke`
