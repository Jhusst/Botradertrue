"""Health checks: liviano siempre 200, profundo refleja breaker/monitor."""
import pytest
from httpx import AsyncClient

from trading_bot.infrastructure.resilience import exchange_breaker


@pytest.mark.asyncio
async def test_health_liviano(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_deep_sano(client: AsyncClient) -> None:
    exchange_breaker.record_success()  # asegurar CLOSED
    response = await client.get("/health/deep")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"]["ok"] is True


@pytest.mark.asyncio
async def test_health_deep_degradado_con_breaker_abierto(client: AsyncClient) -> None:
    threshold = exchange_breaker.failure_threshold
    for _ in range(threshold):
        exchange_breaker.record_failure()
    try:
        response = await client.get("/health/deep")
        assert response.status_code == 503
        assert response.json()["checks"]["circuit_breaker"]["state"] == "OPEN"
    finally:
        exchange_breaker.record_success()  # no contaminar otros tests
