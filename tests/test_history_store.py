"""HistoryStore: cache incremental Parquet sin red."""
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from trading_bot.infrastructure.market_data.history_store import HistoryStore


def _make_df(start: datetime, periods: int, freq: str = "1h") -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": [100.0 + i for i in range(periods)],
            "high": [101.0 + i for i in range(periods)],
            "low": [99.0 + i for i in range(periods)],
            "close": [100.5 + i for i in range(periods)],
            "volume": [10.0] * periods,
        }
    )


@pytest.fixture
def store(tmp_path) -> HistoryStore:
    collector = MagicMock()
    collector.exchange_id = "binance"
    return HistoryStore(collector=collector, data_dir=str(tmp_path))


def test_update_descarga_incremental_solo_gap(store: HistoryStore) -> None:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    first = _make_df(now - timedelta(hours=49), 24)
    store.collector.fetch_ohlcv_range.return_value = first
    added = store.update("BTC/USDT", "1h")
    assert added == 24

    # Segunda llamada: el since debe ser el último timestamp cacheado
    second = _make_df(now - timedelta(hours=25), 12)
    store.collector.fetch_ohlcv_range.return_value = second
    store.update("BTC/USDT", "1h")
    since_ms = store.collector.fetch_ohlcv_range.call_args.kwargs["since_ms"]
    expected = int(first["timestamp"].max().timestamp() * 1000)
    assert since_ms == expected


def test_get_lee_cache_sin_red(store: HistoryStore) -> None:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    store.collector.fetch_ohlcv_range.return_value = _make_df(now - timedelta(hours=49), 24)
    store.update("BTC/USDT", "1h")
    store.collector.fetch_ohlcv_range.reset_mock()

    df = store.get("BTC/USDT", "1h", start=now - timedelta(hours=49))
    assert not df.empty
    store.collector.fetch_ohlcv_range.assert_not_called()


def test_dedup_y_orden_timestamps(store: HistoryStore) -> None:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    base = _make_df(now - timedelta(hours=49), 24)
    store.collector.fetch_ohlcv_range.return_value = base
    store.update("BTC/USDT", "1h")

    # Solapamiento total + desorden: no debe duplicar
    overlap = base.iloc[::-1].reset_index(drop=True)
    store.collector.fetch_ohlcv_range.return_value = overlap
    added = store.update("BTC/USDT", "1h")
    assert added == 0

    df = store.load("BTC/USDT", "1h")
    assert df["timestamp"].is_monotonic_increasing
    assert not df["timestamp"].duplicated().any()


def test_descarta_vela_no_cerrada(store: HistoryStore) -> None:
    now = datetime.now(UTC)
    # Última vela con timestamp = hora actual → todavía en formación
    df = _make_df(now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=5), 6)
    store.collector.fetch_ohlcv_range.return_value = df
    store.update("BTC/USDT", "1h")
    cached = store.load("BTC/USDT", "1h")
    assert len(cached) < 6
    horizon = pd.Timestamp(now) - pd.Timedelta(hours=1)
    assert (cached["timestamp"] <= horizon).all()
