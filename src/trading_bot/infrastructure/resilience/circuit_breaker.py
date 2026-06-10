"""Circuit breaker: tras N fallos seguidos del exchange, pausa y alerta.

Estados: CLOSED (normal) → OPEN (tras N fallos: rechaza llamadas) →
HALF_OPEN (tras reset_seconds: deja pasar 1 llamada de prueba) →
CLOSED si la prueba tiene éxito, OPEN si vuelve a fallar.
"""
from __future__ import annotations

import time
from collections.abc import Callable

import structlog

from trading_bot.core.exceptions import CircuitOpenError

logger = structlog.get_logger()

STATE_CLOSED = "CLOSED"
STATE_OPEN = "OPEN"
STATE_HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int | None = None,
        reset_seconds: float | None = None,
        on_open: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._reset_seconds = reset_seconds
        self.on_open = on_open
        self._clock = clock
        self._failures = 0
        self._state = STATE_CLOSED
        self._opened_at: float | None = None

    @property
    def failure_threshold(self) -> int:
        if self._failure_threshold is not None:
            return self._failure_threshold
        from trading_bot.config.settings import get_settings

        return get_settings().circuit_breaker_failure_threshold

    @property
    def reset_seconds(self) -> float:
        if self._reset_seconds is not None:
            return self._reset_seconds
        from trading_bot.config.settings import get_settings

        return get_settings().circuit_breaker_reset_seconds

    @property
    def state(self) -> str:
        if self._state == STATE_OPEN and self._opened_at is not None:
            if self._clock() - self._opened_at >= self.reset_seconds:
                return STATE_HALF_OPEN
        return self._state

    def check(self) -> None:
        """Lanza CircuitOpenError si el circuito está abierto (sin expirar)."""
        if self.state == STATE_OPEN:
            raise CircuitOpenError(
                f"Circuit breaker '{self.name}' abierto: exchange fallando de forma sostenida"
            )

    def record_success(self) -> None:
        if self._state != STATE_CLOSED:
            logger.info("circuit_closed", breaker=self.name)
        self._failures = 0
        self._state = STATE_CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        # En HALF_OPEN un solo fallo reabre el circuito
        if self.state == STATE_HALF_OPEN:
            self._open()
            return
        self._failures += 1
        if self._failures >= self.failure_threshold and self._state == STATE_CLOSED:
            self._open()

    def _open(self) -> None:
        self._state = STATE_OPEN
        self._opened_at = self._clock()
        logger.error("circuit_opened", breaker=self.name, failures=self._failures)
        if self.on_open is not None:
            try:
                self.on_open(self.name)
            except Exception:  # noqa: BLE001 — la alerta nunca debe romper el flujo
                logger.warning("circuit_on_open_callback_failed", breaker=self.name)


# Breaker compartido para todas las llamadas al exchange
exchange_breaker = CircuitBreaker("exchange")
