# Configurar Binance API (por usuario)

Cada persona que use el bot necesita **su propia cuenta** y **sus propias API keys**. Esta guía es independiente por usuario.

---

## 1. Preparar la cuenta

1. Cuenta en [binance.com](https://www.binance.com) con verificación (KYC).
2. Activar **Derivados → USDⓈ-M Futures**.
3. Transferir **USDT** a la wallet de **Futuros** (no dejar todo en Spot si quieres operar).

---

## 2. Crear API Key

**Perfil → API Management → Create API**

### Permisos recomendados

| Opción | Estado |
|--------|--------|
| Habilitar lectura | ✅ ON |
| Habilitar Futuros | ✅ ON |
| Habilitar trading Spot/Margen | ❌ OFF |
| Habilitar Retiros | ❌ **OFF siempre** |
| Transferencias universales | ❌ OFF |

### Restricción por IP (recomendado)

1. Elige **Restringir acceso a IPs confiables**.
2. Obtén tu IP pública en la PC donde correrá el bot:

```bash
curl https://api.ipify.org
```

3. Pega esa IP en Binance y guarda.

> Si tu IP de casa cambia, tendrás que actualizarla o la conexión fallará.

---

## 3. Guardar en `.env`

```env
BINANCE_API_KEY=pega_aqui_la_clave_api
BINANCE_API_SECRET=pega_aqui_la_clave_secreta
```

| Campo en Binance | Variable en `.env` |
|------------------|-------------------|
| Clave API | `BINANCE_API_KEY` |
| Clave secreta | `BINANCE_API_SECRET` |

Sin comillas. Sin espacios al final.

---

## 4. Modo prueba (testnet)

Antes de dinero real:

1. Regístrate en [testnet.binancefuture.com](https://testnet.binancefuture.com)
2. Crea API keys **del testnet** (no uses las de cuenta real)
3. En `.env`:

```env
BINANCE_TESTNET=true
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
```

---

## 5. Activar broker en el bot

Solo lectura de cuenta (balance en dashboard):

```env
BROKER_ENABLED=true
LIVE_MODE_ENABLED=false
```

Ejecución automática (modo autónomo):

```env
BROKER_ENABLED=true
LIVE_MODE_ENABLED=true
AUTONOMOUS_TRADING_ENABLED=true
```

Reinicia siempre después de cambiar `.env`:

```bash
./scripts/run_api.sh
```

---

## 6. Comprobar conexión

```bash
curl http://localhost:8000/api/v1/broker/status
```

Éxito:

```json
"api_configured": true,
"account": {
  "connected": true,
  "message": "Conectado a Binance Futures"
}
```

Balance `0.0` → falta USDT en Futuros o es testnet sin fondos de prueba.

---

## 7. Errores frecuentes

| Error | Causa | Qué hacer |
|-------|-------|-----------|
| Invalid API-key | Key mal copiada o revocada | Crear API nueva |
| IP restrict | IP no coincide | Actualizar IP en Binance |
| Permission denied | Sin permiso Futuros | Activar "Habilitar Futuros" |
| `-2015` | Keys de mainnet en testnet o viceversa | Alinear `BINANCE_TESTNET` con las keys |

---

## Seguridad

- No compartas keys con nadie.
- No subas `.env` a redes ni repositorios.
- Si expones una key → revócala de inmediato en Binance.
- El bot **no necesita** permiso de retiros para operar.
