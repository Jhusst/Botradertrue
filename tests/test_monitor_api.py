from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_monitor_status(client: AsyncClient) -> None:
    response = await client.get("/api/v1/monitor/status")
    assert response.status_code == 200
    data = response.json()
    assert "running" in data
    assert "symbols" in data


@pytest.mark.asyncio
async def test_monitor_run_once(client: AsyncClient) -> None:
    mock_monitor = MagicMock()
    mock_monitor.run_cycle = AsyncMock(return_value={"scanned": 0, "alerts_sent": 0, "cycle": 1})
    mock_monitor.status.return_value = {"running": False, "symbols": ["BTC/USDT"]}
    with patch("trading_bot.api.routes.monitor.get_monitor", return_value=mock_monitor):
        response = await client.post("/api/v1/monitor/run-once")
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_paper_trades_list(client: AsyncClient) -> None:
    response = await client.get("/api/v1/paper-trades")
    assert response.status_code == 200
    assert "items" in response.json()
