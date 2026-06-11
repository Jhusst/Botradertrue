"""Alt-data LEGAL de Binance Futures: funding, open interest, long/short ratio.

Nada de información privilegiada: todo son datos públicos del exchange.
Todos los campos son nullable y los métodos degradan a None/vacío ante
cualquier fallo — el alt-data enriquece, nunca rompe el flujo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import structlog

from trading_bot.config.settings import Settings, get_settings
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector

logger = structlog.get_logger()


@dataclass
class DerivativesSnapshot:
    funding_rate: float | None = None
    funding_zscore_7d: float | None = None
    open_interest_usdt: float | None = None
    oi_change_1h_pct: float | None = None
    oi_change_24h_pct: float | None = None
    long_short_ratio_global: float | None = None
    long_short_ratio_top: float | None = None
    taker_buy_sell_ratio: float | None = None


class DerivativesDataClient:
    def __init__(
        self,
        collector: DataCollector | None = None,
        settings: Settings | None = None,
        data_dir: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.collector = collector or DataCollector("binance")
        self.data_dir = Path(data_dir or self.settings.data_dir)

    @property
    def exchange(self):
        return self.collector.exchange

    def _binance_symbol(self, symbol: str) -> str:
        """BTC/USDT → BTCUSDT (formato de los endpoints fapiData)."""
        return symbol.split(":")[0].replace("/", "")

    # ------------------------------------------------------------------
    # Series históricas
    # ------------------------------------------------------------------

    def fetch_funding_history(self, symbol: str, since: datetime | None = None) -> pd.DataFrame:
        try:
            resolved = self.collector._resolve_symbol(symbol)
            since_ms = int(since.timestamp() * 1000) if since else None
            raw = self.exchange.fetch_funding_rate_history(resolved, since=since_ms, limit=1000)
            df = pd.DataFrame(
                [
                    {"timestamp": r.get("timestamp"), "funding_rate": r.get("fundingRate")}
                    for r in raw
                ]
            )
            if df.empty:
                return df
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            return df.dropna().sort_values("timestamp").reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("funding_history_failed", symbol=symbol, error=str(exc))
            return pd.DataFrame(columns=["timestamp", "funding_rate"])

    def fetch_open_interest_history(
        self, symbol: str, timeframe: str = "1h", since: datetime | None = None
    ) -> pd.DataFrame:
        try:
            resolved = self.collector._resolve_symbol(symbol)
            since_ms = int(since.timestamp() * 1000) if since else None
            raw = self.exchange.fetch_open_interest_history(
                resolved, timeframe=timeframe, since=since_ms, limit=500
            )
            df = pd.DataFrame(
                [
                    {
                        "timestamp": r.get("timestamp"),
                        "open_interest_usdt": r.get("openInterestValue")
                        or (r.get("info", {}) or {}).get("sumOpenInterestValue"),
                    }
                    for r in raw
                ]
            )
            if df.empty:
                return df
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df["open_interest_usdt"] = pd.to_numeric(df["open_interest_usdt"], errors="coerce")
            return df.dropna().sort_values("timestamp").reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("oi_history_failed", symbol=symbol, error=str(exc))
            return pd.DataFrame(columns=["timestamp", "open_interest_usdt"])

    def fetch_long_short_ratio(
        self, symbol: str, period: str = "1h", *, top_traders: bool = False
    ) -> pd.DataFrame:
        """Long/short ratio (Binance solo expone los últimos 30 días)."""
        try:
            params = {"symbol": self._binance_symbol(symbol), "period": period, "limit": 500}
            if top_traders:
                raw = self.exchange.fapiDataGetTopLongShortPositionRatio(params)
            else:
                raw = self.exchange.fapiDataGetGlobalLongShortAccountRatio(params)
            df = pd.DataFrame(
                [
                    {"timestamp": int(r["timestamp"]), "long_short_ratio": float(r["longShortRatio"])}
                    for r in raw
                ]
            )
            if df.empty:
                return df
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            return df.sort_values("timestamp").reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ls_ratio_failed", symbol=symbol, error=str(exc))
            return pd.DataFrame(columns=["timestamp", "long_short_ratio"])

    def fetch_taker_ratio(self, symbol: str, period: str = "1h") -> pd.DataFrame:
        try:
            params = {"symbol": self._binance_symbol(symbol), "period": period, "limit": 500}
            raw = self.exchange.fapiDataGetTakerlongshortRatio(params)
            df = pd.DataFrame(
                [
                    {"timestamp": int(r["timestamp"]), "taker_ratio": float(r["buySellRatio"])}
                    for r in raw
                ]
            )
            if df.empty:
                return df
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            return df.sort_values("timestamp").reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("taker_ratio_failed", symbol=symbol, error=str(exc))
            return pd.DataFrame(columns=["timestamp", "taker_ratio"])

    # ------------------------------------------------------------------
    # Cache acumulativa (crítica para L/S ratio: solo 30 días en Binance)
    # ------------------------------------------------------------------

    def _cache_path(self, symbol: str, name: str) -> Path:
        clean = symbol.split(":")[0].replace("/", "_")
        return self.data_dir / "derivatives" / clean / f"{name}.parquet"

    def accumulate(self, symbol: str) -> dict[str, int]:
        """Acumula series de derivados en cache local (job diario)."""
        added: dict[str, int] = {}
        series = {
            "funding": self.fetch_funding_history(symbol),
            "open_interest": self.fetch_open_interest_history(symbol),
            "ls_ratio_global": self.fetch_long_short_ratio(symbol),
            "ls_ratio_top": self.fetch_long_short_ratio(symbol, top_traders=True),
            "taker_ratio": self.fetch_taker_ratio(symbol),
        }
        for name, fresh in series.items():
            if fresh.empty:
                added[name] = 0
                continue
            path = self._cache_path(symbol, name)
            if path.exists():
                existing = pd.read_parquet(path)
                existing["timestamp"] = pd.to_datetime(existing["timestamp"], utc=True)
                combined = pd.concat([existing, fresh], ignore_index=True)
            else:
                combined = fresh
            combined = (
                combined.drop_duplicates(subset="timestamp", keep="last")
                .sort_values("timestamp")
                .reset_index(drop=True)
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            combined.to_parquet(path, index=False)
            added[name] = len(fresh)
        return added

    def load_cached(self, symbol: str, name: str) -> pd.DataFrame:
        path = self._cache_path(symbol, name)
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    # ------------------------------------------------------------------
    # Snapshot para el monitor live y el feature builder
    # ------------------------------------------------------------------

    def snapshot(self, symbol: str) -> DerivativesSnapshot:
        snap = DerivativesSnapshot()
        try:
            funding = self.fetch_funding_history(symbol)
            if not funding.empty:
                snap.funding_rate = float(funding["funding_rate"].iloc[-1])
                window = funding["funding_rate"].tail(21)  # ~7 días (cada 8h)
                std = float(window.std())
                if std > 0:
                    snap.funding_zscore_7d = float(
                        (snap.funding_rate - float(window.mean())) / std
                    )
        except Exception:  # noqa: BLE001
            pass
        try:
            oi = self.fetch_open_interest_history(symbol)
            if not oi.empty:
                last = float(oi["open_interest_usdt"].iloc[-1])
                snap.open_interest_usdt = last
                if len(oi) >= 2:
                    prev_1h = float(oi["open_interest_usdt"].iloc[-2])
                    if prev_1h > 0:
                        snap.oi_change_1h_pct = (last - prev_1h) / prev_1h * 100
                if len(oi) >= 25:
                    prev_24h = float(oi["open_interest_usdt"].iloc[-25])
                    if prev_24h > 0:
                        snap.oi_change_24h_pct = (last - prev_24h) / prev_24h * 100
        except Exception:  # noqa: BLE001
            pass
        try:
            ls = self.fetch_long_short_ratio(symbol)
            if not ls.empty:
                snap.long_short_ratio_global = float(ls["long_short_ratio"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass
        try:
            ls_top = self.fetch_long_short_ratio(symbol, top_traders=True)
            if not ls_top.empty:
                snap.long_short_ratio_top = float(ls_top["long_short_ratio"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass
        try:
            taker = self.fetch_taker_ratio(symbol)
            if not taker.empty:
                snap.taker_buy_sell_ratio = float(taker["taker_ratio"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass
        return snap
