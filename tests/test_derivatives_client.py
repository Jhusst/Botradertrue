"""DerivativesDataClient: parsing y degradación elegante."""
from unittest.mock import MagicMock

import pytest

from trading_bot.infrastructure.market_data.derivatives_client import DerivativesDataClient


@pytest.fixture
def client(tmp_path) -> DerivativesDataClient:
    collector = MagicMock()
    collector._resolve_symbol.side_effect = lambda s: s + ":USDT" if ":" not in s else s
    instance = DerivativesDataClient(collector=collector, data_dir=str(tmp_path))
    return instance


def test_funding_history_parsea(client: DerivativesDataClient) -> None:
    client.collector.exchange.fetch_funding_rate_history.return_value = [
        {"timestamp": 1700000000000, "fundingRate": 0.0001},
        {"timestamp": 1700028800000, "fundingRate": -0.0002},
    ]
    df = client.fetch_funding_history("BTC/USDT")
    assert len(df) == 2
    assert list(df.columns) == ["timestamp", "funding_rate"]
    assert df["timestamp"].is_monotonic_increasing


def test_ls_ratio_parsea(client: DerivativesDataClient) -> None:
    client.collector.exchange.fapiDataGetGlobalLongShortAccountRatio.return_value = [
        {"timestamp": "1700000000000", "longShortRatio": "1.85"},
    ]
    df = client.fetch_long_short_ratio("BTC/USDT")
    assert df["long_short_ratio"].iloc[0] == pytest.approx(1.85)


def test_fallo_de_red_devuelve_vacio(client: DerivativesDataClient) -> None:
    client.collector.exchange.fetch_funding_rate_history.side_effect = RuntimeError("red caída")
    df = client.fetch_funding_history("BTC/USDT")
    assert df.empty


def test_snapshot_con_todo_fallando_devuelve_nones(client: DerivativesDataClient) -> None:
    exchange = client.collector.exchange
    exchange.fetch_funding_rate_history.side_effect = RuntimeError("x")
    exchange.fetch_open_interest_history.side_effect = RuntimeError("x")
    exchange.fapiDataGetGlobalLongShortAccountRatio.side_effect = RuntimeError("x")
    exchange.fapiDataGetTopLongShortPositionRatio.side_effect = RuntimeError("x")
    exchange.fapiDataGetTakerlongshortRatio.side_effect = RuntimeError("x")

    snap = client.snapshot("BTC/USDT")
    assert snap.funding_rate is None
    assert snap.open_interest_usdt is None
    assert snap.long_short_ratio_global is None


def test_accumulate_no_duplica(client: DerivativesDataClient) -> None:
    rows = [{"timestamp": 1700000000000, "fundingRate": 0.0001}]
    exchange = client.collector.exchange
    exchange.fetch_funding_rate_history.return_value = rows
    exchange.fetch_open_interest_history.return_value = []
    exchange.fapiDataGetGlobalLongShortAccountRatio.return_value = []
    exchange.fapiDataGetTopLongShortPositionRatio.return_value = []
    exchange.fapiDataGetTakerlongshortRatio.return_value = []

    client.accumulate("BTC/USDT")
    client.accumulate("BTC/USDT")  # misma data otra vez
    cached = client.load_cached("BTC/USDT", "funding")
    assert len(cached) == 1
