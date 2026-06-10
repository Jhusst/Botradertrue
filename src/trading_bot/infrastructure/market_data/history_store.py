"""Cache local incremental de OHLCV en Parquet.

Layout: {data_dir}/ohlcv/{exchange}/{símbolo_sanitizado}/{timeframe}.parquet
Siempre UTC, dedup por timestamp, descarta la vela en formación.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import structlog

from trading_bot.config.settings import Settings, get_settings
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector

logger = structlog.get_logger()

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _sanitize_symbol(symbol: str) -> str:
    return symbol.replace("/", "_").replace(":", "-")


class HistoryStore:
    def __init__(
        self,
        collector: DataCollector | None = None,
        data_dir: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.collector = collector or DataCollector("binance")
        self.data_dir = Path(data_dir or self.settings.data_dir)

    def _path(self, symbol: str, timeframe: str) -> Path:
        return (
            self.data_dir
            / "ohlcv"
            / self.collector.exchange_id
            / _sanitize_symbol(symbol)
            / f"{timeframe}.parquet"
        )

    def load(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """Lee SOLO la cache (sin red)."""
        path = self._path(symbol, timeframe)
        if not path.exists():
            return pd.DataFrame(columns=OHLCV_COLUMNS)
        df = pd.read_parquet(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df.sort_values("timestamp").reset_index(drop=True)

    def get(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Lee la cache filtrando por rango (sin red — usa update() antes)."""
        df = self.load(symbol, timeframe)
        if df.empty:
            return df
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        mask = df["timestamp"] >= start
        if end is not None:
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            mask &= df["timestamp"] <= end
        return df[mask].reset_index(drop=True)

    def update(self, symbol: str, timeframe: str, *, backfill_days: int | None = None) -> int:
        """Descarga SOLO el gap desde la última vela cacheada. Devuelve velas nuevas."""
        existing = self.load(symbol, timeframe)
        now = datetime.now(UTC)
        if existing.empty:
            days = backfill_days or self.settings.history_backfill_days
            since = now - timedelta(days=days)
        else:
            since = existing["timestamp"].max().to_pydatetime()

        fresh = self.collector.fetch_ohlcv_range(
            symbol, timeframe, since_ms=int(since.timestamp() * 1000)
        )
        if fresh.empty:
            return 0

        fresh = self._drop_unclosed(fresh, timeframe, now)
        if fresh.empty:
            return 0

        combined = pd.concat([existing, fresh], ignore_index=True)
        combined = (
            combined.drop_duplicates(subset="timestamp", keep="last")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )
        added = len(combined) - len(existing)

        path = self._path(symbol, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(path, index=False)
        logger.info("history_updated", symbol=symbol, timeframe=timeframe, added=added)
        return added

    def load_multi_timeframe(
        self, symbol: str, start: datetime, end: datetime | None = None
    ) -> dict[str, pd.DataFrame]:
        return {tf: self.get(symbol, tf, start, end) for tf in ("4h", "1h", "15m")}

    @staticmethod
    def _drop_unclosed(df: pd.DataFrame, timeframe: str, now: datetime) -> pd.DataFrame:
        """Elimina la vela cuyo cierre aún no ocurrió (estaría en formación)."""
        tf_ms = DataCollector._timeframe_to_ms(timeframe)
        cutoff = pd.Timestamp(now) - pd.Timedelta(milliseconds=tf_ms)
        return df[df["timestamp"] <= cutoff].reset_index(drop=True)
