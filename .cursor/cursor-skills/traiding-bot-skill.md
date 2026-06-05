# Skill: Trading Bot Developer - Growth & Risk Controlled System

Actúa como un desarrollador senior especializado en trading algorítmico, gestión de riesgo, Python, FastAPI, backtesting, análisis técnico, cripto, futuros, oro, plata y sistemas de señales.

## Objetivo del sistema

Crear un bot semiautomático de trading cuyo objetivo sea hacer crecer una cuenta poco a poco, buscando superar rendimientos tradicionales como S&P 500, FIBRAs o inversión pasiva, pero sin asumir riesgos destructivos.

El bot debe generar señales con:

* Dirección: LONG, SHORT o NO TRADE.
* Precio de entrada.
* Stop loss.
* Take profit.
* Riesgo/beneficio.
* Porcentaje recomendado de la cuenta.
* Capital recomendado en USDT.
* Apalancamiento recomendado.
* Confianza del setup.
* Motivo técnico de la señal.
* Condiciones de invalidación.
* Riesgo máximo de pérdida si falla.

## Filosofía principal

El bot debe rascar oportunidades del mercado, no apostar.

Debe priorizar:

1. Preservar capital.
2. Crecimiento compuesto.
3. Riesgo controlado.
4. Evitar liquidaciones.
5. Evitar sobreoperar.
6. Evitar decisiones emocionales.
7. Decir “NO TRADE” cuando no haya ventaja clara.

## Reglas obligatorias de riesgo

1. El riesgo por operación debe estar entre 0.25% y 1% de la cuenta.
2. En setups de alta calidad se puede permitir hasta 1.5%, pero nunca más sin aprobación manual.
3. La pérdida máxima diaria debe ser 2% de la cuenta.
4. La pérdida máxima semanal debe ser 5% de la cuenta.
5. Después de 2 pérdidas seguidas, el bot debe bloquear nuevas señales por un periodo configurable.
6. El bot nunca debe recomendar martingala.
7. El bot nunca debe promediar pérdidas automáticamente.
8. El bot nunca debe aumentar apalancamiento para recuperar pérdidas.
9. El apalancamiento debe calcularse con base en la distancia al stop loss, volatilidad y riesgo máximo permitido.
10. El bot debe mostrar siempre cuánto se puede perder en USDT antes de mostrar cuánto se puede ganar.

## Cálculo de tamaño de posición

El bot debe calcular:

* Balance total de la cuenta.
* Riesgo permitido en porcentaje.
* Riesgo permitido en USDT.
* Distancia entre entrada y stop loss.
* Tamaño de posición.
* Margen requerido.
* Apalancamiento recomendado.
* Pérdida máxima estimada.
* Ganancia potencial estimada.

Fórmula base:

riesgo_usdt = balance * riesgo_porcentaje

position_size = riesgo_usdt / distancia_stop_porcentual

margen_requerido = position_size / apalancamiento

El apalancamiento recomendado NO debe ser fijo. Debe depender de:

* Volatilidad actual.
* Temporalidad.
* Distancia al stop loss.
* Calidad del setup.
* Tendencia mayor.
* Eventos económicos cercanos.
* Liquidez del activo.
* Drawdown actual de la cuenta.

## Clasificación de setups

El bot debe clasificar las señales en:

### Setup A - Alta calidad

Condiciones:

* Tendencia alineada en temporalidades mayores.
* Entrada en zona de alta probabilidad.
* Confirmación de volumen.
* RSI sin sobreextensión peligrosa.
* Stop loss claro.
* Ratio riesgo/beneficio mínimo 1:2.
* Sin noticia económica fuerte cercana.
* Volatilidad controlada.

Riesgo permitido:

* 1% máximo.
* 1.5% solo con aprobación manual.

Apalancamiento:

* Bajo a moderado.
* Debe calcularse automáticamente.
* Nunca debe recomendar apalancamiento alto solo por confianza.

### Setup B - Calidad media

Condiciones:

* Hay oportunidad, pero no todas las temporalidades están alineadas.
* Existe confirmación parcial.
* El ratio riesgo/beneficio es aceptable.

Riesgo permitido:

* 0.5% máximo.

Apalancamiento:

* Bajo.

### Setup C - Baja calidad

Condiciones:

* Mercado lateral.
* Alta volatilidad.
* Noticias cercanas.
* Stop loss poco claro.
* Ratio menor a 1:2.

Resultado:

* NO TRADE.

## Señal esperada

Cada señal debe tener este formato:

Activo: BTCUSDT
Dirección: LONG / SHORT / NO TRADE
Temporalidad principal: 15m / 1h / 4h
Entrada sugerida:
Stop loss:
Take profit 1:
Take profit 2:
Ratio riesgo/beneficio:
Balance de cuenta:
Riesgo recomendado: 0.5%
Riesgo máximo en USDT:
Capital recomendado:
Apalancamiento recomendado:
Pérdida máxima si falla:
Ganancia estimada si cumple TP1:
Ganancia estimada si cumple TP2:
Confianza del setup: A / B / C
Motivo de la señal:
Invalidación:
¿Operar?: Sí / No

## Stack técnico

Backend:

* Python
* FastAPI
* Pydantic
* SQLAlchemy
* PostgreSQL
* Redis
* Celery o RQ

Trading/data:

* CCXT para exchanges cripto
* MetaTrader5 para oro, plata y forex
* pandas
* numpy
* pandas-ta
* vectorbt
* backtesting.py

IA:

* Ollama local
* LLaVA o modelo de visión compatible
* La IA visual solo debe complementar el análisis, nunca decidir sola

Alertas:

* Telegram Bot API
* Webhooks
* Dashboard web

Frontend:

* Next.js o Astro
* Tailwind CSS
* Dashboard limpio y responsive

Seguridad:

* API keys en variables de entorno
* Nunca hardcodear credenciales
* Logs auditables
* Modo demo por defecto
* Modo real bloqueado hasta pasar validaciones

## Módulos del sistema

1. data_collector
2. market_analyzer
3. multi_timeframe_analyzer
4. economic_events_analyzer
5. strategy_engine
6. risk_manager
7. position_sizer
8. signal_generator
9. backtester
10. paper_trading
11. execution_engine
12. ai_chart_analyzer
13. telegram_alerts
14. dashboard
15. audit_logger

## Validaciones antes de una señal

Antes de generar una señal, el sistema debe revisar:

* Tendencia en 1D, 4H, 1H y 15M.
* Soportes y resistencias.
* EMA 20, EMA 50 y EMA 200.
* RSI.
* Volumen.
* ATR.
* Volatilidad.
* Liquidez.
* Noticias económicas cercanas.
* Drawdown actual.
* Operaciones abiertas.
* Correlación con otros activos.
* Historial reciente de pérdidas.
* Ratio riesgo/beneficio.

## Condiciones para NO TRADE

El bot debe marcar NO TRADE si:

* El stop loss no es claro.
* El ratio riesgo/beneficio es menor a 1:2.
* Hay noticia económica de alto impacto cercana.
* La volatilidad está fuera de rango.
* La cuenta ya perdió el límite diario.
* Hay más de 2 pérdidas consecutivas.
* El mercado está lateral y sin volumen.
* El precio está lejos de una zona de valor.
* El setup depende únicamente de intuición o IA visual.

## Backtesting obligatorio

Toda estrategia debe probarse con:

* Al menos 1 año de datos históricos.
* Distintas condiciones de mercado.
* Mercado alcista.
* Mercado bajista.
* Mercado lateral.
* Eventos económicos.
* Comisiones.
* Slippage.
* Apalancamiento.
* Liquidación estimada.
* Drawdown máximo.

Métricas mínimas:

* Winrate.
* Profit factor.
* Max drawdown.
* Sharpe ratio.
* Expectancy.
* Promedio de ganancia.
* Promedio de pérdida.
* Número total de trades.
* Racha máxima de pérdidas.
* Resultado neto después de comisiones.

## Regla importante

El sistema nunca debe prometer ganancias.
Debe diseñarse para tomar decisiones probabilísticas, controlar pérdidas y dejar correr ganancias.

El objetivo es crecimiento compuesto controlado, no apuestas de alto riesgo.
