import pytest
from httpx import ASGITransport, AsyncClient

from trading_bot.main import app


@pytest.mark.asyncio
async def test_ai_behavior_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/ai/behavior")
    assert resp.status_code == 200
    data = resp.json()
    assert "system_prompt" in data
    assert "NUNCA" in data["system_prompt"]


@pytest.mark.asyncio
async def test_ai_status_endpoint() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/ai/status")
    assert resp.status_code == 200
    assert "enabled" in resp.json()
