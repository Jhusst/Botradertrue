import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_monitoring_overview(client: AsyncClient) -> None:
    response = await client.get("/api/v1/monitoring/overview")
    assert response.status_code == 200
    data = response.json()
    assert "health" in data
    assert "summary" in data


@pytest.mark.asyncio
async def test_monitoring_journal(client: AsyncClient) -> None:
    response = await client.get("/api/v1/monitoring/journal")
    assert response.status_code == 200
    data = response.json()
    assert "trades" in data
    assert "summary" in data
