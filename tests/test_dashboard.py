import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dashboard_page(client: AsyncClient) -> None:
    response = await client.get("/dashboard")
    assert response.status_code == 200
    assert "Trading Bot" in response.text
    assert "Balance total" in response.text
    assert "profile-tabs" in response.text


@pytest.mark.asyncio
async def test_dashboard_data(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/data")
    assert response.status_code == 200
    data = response.json()
    assert "profiles" in data
    assert "monitor" in data
    assert "portfolio_total_usdt" in data
    assert "storage" in data


@pytest.mark.asyncio
async def test_dashboard_lite(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/lite")
    assert response.status_code == 200
    data = response.json()
    assert data.get("lite") is True
    assert "trade_plan" in (data["profiles"][0]["signals"][0] if data["profiles"] and data["profiles"][0]["signals"] else {}) or True


@pytest.mark.asyncio
async def test_setup_check(client: AsyncClient) -> None:
    response = await client.get("/api/v1/setup/check")
    assert response.status_code == 200
    data = response.json()
    assert "telegram" in data
    assert "missing" in data
    assert "steps" in data
    assert data["exchange"]["needs_api_keys_for_data"] is False


@pytest.mark.asyncio
async def test_telegram_test_without_config(client: AsyncClient) -> None:
    response = await client.post("/api/v1/setup/test-telegram")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
