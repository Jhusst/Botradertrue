"""Retry con backoff exponencial + jitter para llamadas al exchange.

Solo reintenta errores de red transitorios. Errores de negocio
(fondos insuficientes, orden inválida, auth) se propagan inmediato.

IMPORTANTE: nunca decorar con esto un create_order de entrada cuyo envío
pudo haberse completado (timeout ambiguo): el llamador debe consultar
primero por clientOrderId antes de reintentar.
"""
from __future__ import annotations

import functools
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger()

F = TypeVar("F", bound=Callable[..., Any])


def _retryable_exceptions() -> tuple[type[Exception], ...]:
    import ccxt

    return (
        ccxt.NetworkError,
        ccxt.ExchangeNotAvailable,
        ccxt.RequestTimeout,
        ccxt.DDoSProtection,
        ccxt.RateLimitExceeded,
    )


def _non_retryable_exceptions() -> tuple[type[Exception], ...]:
    import ccxt

    return (
        ccxt.InsufficientFunds,
        ccxt.InvalidOrder,
        ccxt.PermissionDenied,
        ccxt.AuthenticationError,
    )


def with_retry(
    max_attempts: int | None = None,
    base_delay: float | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[F], F]:
    """Decorador síncrono: backoff 2^n * base + jitter uniforme(0, base)."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from trading_bot.config.settings import get_settings

            settings = get_settings()
            attempts = max_attempts if max_attempts is not None else settings.exchange_retry_max_attempts
            base = base_delay if base_delay is not None else settings.exchange_retry_backoff_base
            retryable = _retryable_exceptions()
            non_retryable = _non_retryable_exceptions()

            last_exc: Exception | None = None
            for attempt in range(attempts):
                try:
                    return func(*args, **kwargs)
                except non_retryable:
                    raise
                except retryable as exc:
                    last_exc = exc
                    if attempt >= attempts - 1:
                        break
                    delay = (2**attempt) * base + random.uniform(0, base)
                    logger.warning(
                        "exchange_retry",
                        func=func.__name__,
                        attempt=attempt + 1,
                        max_attempts=attempts,
                        delay=round(delay, 2),
                        error=str(exc),
                    )
                    sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
