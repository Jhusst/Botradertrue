from fastapi import APIRouter

from trading_bot.config.settings import get_settings
from trading_bot.modules.ai_chart_analyzer.analyzer import AIChartAnalyzer
from trading_bot.modules.execution_engine.binance_broker import BinanceBroker

router = APIRouter(prefix="/autonomous", tags=["autonomous"])


@router.get("/status")
async def autonomous_status() -> dict:
    settings = get_settings()
    broker = BinanceBroker()
    can_exec, exec_reason = broker.can_execute()
    ai = AIChartAnalyzer()

    return {
        "enabled": settings.autonomous_trading_enabled,
        "ai_gate": settings.ai_gate_auto_trade,
        "ai_required": settings.ai_required_for_auto_trade,
        "ai_min_verdict": settings.ai_auto_min_verdict,
        "ai_available": ai.is_available,
        "min_balance_usdt": settings.min_balance_for_autonomous,
        "compound_on_close": settings.compound_balance_on_close,
        "broker_can_execute": can_exec,
        "broker_reason": exec_reason,
        "flow": [
            "1. Monitor detecta ENTRAR AHORA (precio toca entrada)",
            "2. IA (Ollama) evalúa el setup si AI_GATE_AUTO_TRADE=true",
            "3. Si IA ≥ CONFIRM → abre trade en DB + Binance (si broker activo)",
            "4. SL/TP en exchange + seguimiento local del P&L",
            "5. Telegram te avisa de cada acción",
        ],
        "warning": (
            "Ningún bot garantiza crecimiento de capital. Con ~2 USDT el mínimo de Binance "
            "bloqueará la mayoría de órdenes. Usa testnet o ≥10–20 USDT para probar en serio."
        ),
    }
