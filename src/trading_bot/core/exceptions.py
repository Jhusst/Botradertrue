class TradingBotError(Exception):
    """Error base del sistema."""


class RiskBlockedError(TradingBotError):
    """Operación bloqueada por gestión de riesgo."""


class LiveModeBlockedError(TradingBotError):
    """Ejecución real bloqueada hasta validaciones."""


class InvalidSetupError(TradingBotError):
    """Setup no cumple criterios mínimos."""
