import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "PAPER"
    assert data["live_enabled"] is False


@pytest.mark.asyncio
async def test_generate_signal(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/signals/generate",
        params={"symbol": "BTC/USDT", "balance": 10000, "notify_telegram": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "BTC/USDT"
    assert float(data["account_balance"]) == 10000
    assert "direction" in data
    assert "setup_grade" in data


@pytest.mark.asyncio
async def test_list_and_get_signal(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/signals/generate",
        params={"notify_telegram": False},
    )
    assert create.status_code == 200
    signal_id = create.json()["id"]

    listing = await client.get("/api/v1/signals")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1

    detail = await client.get(f"/api/v1/signals/{signal_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == signal_id


@pytest.mark.asyncio
async def test_get_signal_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/signals/99999")
    assert response.status_code == 404
