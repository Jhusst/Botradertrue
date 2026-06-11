class TradingBotError(Exception):
    """Error base del sistema."""


class RiskBlockedError(TradingBotError):
    """Operación bloqueada por gestión de riesgo."""


class LiveModeBlockedError(TradingBotError):
    """Ejecución real bloqueada hasta validaciones."""


class InvalidSetupError(TradingBotError):
    """Setup no cumple criterios mínimos."""


class ProtectionFailedError(TradingBotError):
    """No se pudo garantizar stop-loss para una posición abierta."""


class CircuitOpenError(TradingBotError):
    """Circuit breaker abierto: el exchange está fallando de forma sostenida."""


class KillSwitchEngagedError(TradingBotError):
    """Kill-switch activado: toda apertura de posiciones está bloqueada."""
