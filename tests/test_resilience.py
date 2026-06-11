"""Tests de retry con backoff y circuit breaker."""
import ccxt
import pytest

from trading_bot.core.exceptions import CircuitOpenError
from trading_bot.infrastructure.resilience.circuit_breaker import CircuitBreaker
from trading_bot.infrastructure.resilience.retry import with_retry


def test_with_retry_reintenta_errores_de_red() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    @with_retry(max_attempts=3, base_delay=0.5, sleep=sleeps.append)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ccxt.NetworkError("timeout")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    # Backoff exponencial: 2^0*0.5 <= d1 < 2^0*0.5+0.5 ; 2^1*0.5 <= d2 < 2^1*0.5+0.5
    assert 0.5 <= sleeps[0] < 1.0
    assert 1.0 <= sleeps[1] < 1.5


def test_with_retry_agota_intentos_y_propaga() -> None:
    @with_retry(max_attempts=2, base_delay=0.01, sleep=lambda _d: None)
    def always_fails() -> None:
        raise ccxt.RequestTimeout("dead")

    with pytest.raises(ccxt.RequestTimeout):
        always_fails()


def test_with_retry_no_reintenta_errores_de_negocio() -> None:
    calls = {"n": 0}

    @with_retry(max_attempts=5, base_delay=0.01, sleep=lambda _d: None)
    def no_funds() -> None:
        calls["n"] += 1
        raise ccxt.InsufficientFunds("broke")

    with pytest.raises(ccxt.InsufficientFunds):
        no_funds()
    assert calls["n"] == 1


def test_breaker_abre_tras_n_fallos_y_recupera() -> None:
    now = {"t": 0.0}
    opened: list[str] = []
    breaker = CircuitBreaker(
        "test", failure_threshold=3, reset_seconds=10, on_open=opened.append, clock=lambda: now["t"]
    )

    breaker.check()  # CLOSED: no lanza
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state == "OPEN"
    assert opened == ["test"]
    with pytest.raises(CircuitOpenError):
        breaker.check()

    # Tras reset_seconds pasa a HALF_OPEN: check() ya no lanza (1 llamada de prueba)
    now["t"] = 11.0
    assert breaker.state == "HALF_OPEN"
    breaker.check()

    # Éxito en la prueba → CLOSED
    breaker.record_success()
    assert breaker.state == "CLOSED"


def test_breaker_half_open_reabre_con_un_fallo() -> None:
    now = {"t": 0.0}
    breaker = CircuitBreaker("test", failure_threshold=2, reset_seconds=5, clock=lambda: now["t"])
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "OPEN"
    now["t"] = 6.0
    assert breaker.state == "HALF_OPEN"
    breaker.record_failure()
    assert breaker.state == "OPEN"
    with pytest.raises(CircuitOpenError):
        breaker.check()
