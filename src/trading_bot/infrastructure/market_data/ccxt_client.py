from datetime import UTC, datetime

import pandas as pd

from trading_bot.config.settings import get_settings
from trading_bot.core.asset_catalog import is_futures_symbol
from trading_bot.infrastructure.resilience import exchange_breaker, with_retry


class DataCollector:
    """Recolecta OHLCV desde exchanges vía CCXT (solo lectura)."""

    def __init__(self, exchange_id: str = "binance") -> None:
        self.exchange_id = exchange_id
        self._exchange = None

    @property
    def exchange(self):
        if self._exchange is None:
            import ccxt

            settings = get_settings()
            config: dict = {"enableRateLimit": True}
            if settings.binance_api_key:
                config["apiKey"] = settings.binance_api_key
                config["secret"] = settings.binance_api_secret
            config["options"] = {"defaultType": "future"}
            exchange_id = self.exchange_id
            if settings.binance_testnet and settings.binance_api_key:
                exchange_id = "binanceusdm"
            exchange_class = getattr(ccxt, exchange_id)
            self._exchange = exchange_class(config)
            if settings.binance_testnet and settings.binance_api_key:
                self._exchange.set_sandbox_mode(True)
        return self._exchange

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        resolved = self._resolve_symbol(symbol)
        raw = self._fetch_ohlcv_raw(resolved, timeframe, limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    @with_retry()
    def _fetch_ohlcv_raw(self, resolved_symbol: str, timeframe: str, limit: int) -> list:
        exchange_breaker.check()
        try:
            raw = self.exchange.fetch_ohlcv(resolved_symbol, timeframe=timeframe, limit=limit)
        except Exception:
            exchange_breaker.record_failure()
            raise
        exchange_breaker.record_success()
        return raw

    def fetch_multi_timeframe(self, symbol: str) -> dict[str, pd.DataFrame]:
        """Límites mínimos para la estrategia (4h≥200, 1h≥50, 15m≥30) — menos llamadas = más rápido."""
        return {
            "4h": self.fetch_ohlcv(symbol, "4h", 220),
            "1h": self.fetch_ohlcv(symbol, "1h", 120),
            "15m": self.fetch_ohlcv(symbol, "15m", 80),
        }

    def _resolve_symbol(self, symbol: str) -> str:
        """Mapea símbolos spot a futuros cuando el exchange lo requiere."""
        if is_futures_symbol(symbol):
            return symbol
        futures_map = {
            "BTC/USDT": "BTC/USDT:USDT",
            "ETH/USDT": "ETH/USDT:USDT",
            "SOL/USDT": "SOL/USDT:USDT",
            "BNB/USDT": "BNB/USDT:USDT",
            "DOGE/USDT": "DOGE/USDT:USDT",
            "XRP/USDT": "XRP/USDT:USDT",
            "WIF/USDT": "WIF/USDT:USDT",
            "LINK/USDT": "LINK/USDT:USDT",
            "AVAX/USDT": "AVAX/USDT:USDT",
            "ADA/USDT": "ADA/USDT:USDT",
            "HYPE/USDT": "HYPE/USDT:USDT",
        }
        return futures_map.get(symbol, symbol)

    @staticmethod
    def generate_sample_data(periods: int = 500) -> dict[str, pd.DataFrame]:
        """Datos sintéticos para desarrollo sin conexión a exchange."""
        import numpy as np

        rng = np.random.default_rng(42)
        dates = pd.date_range(end=datetime.now(UTC), periods=periods, freq="1h")
        price = 50000 + np.cumsum(rng.normal(0, 100, periods))
        df = pd.DataFrame(
            {
                "timestamp": dates,
                "open": price,
                "high": price + rng.uniform(50, 200, periods),
                "low": price - rng.uniform(50, 200, periods),
                "close": price + rng.normal(0, 50, periods),
                "volume": rng.uniform(100, 1000, periods),
            }
        )
        return {"4h": df.iloc[::4].reset_index(drop=True), "1h": df, "15m": df}

    @staticmethod
    def generate_trending_bullish_data(periods: int = 500) -> dict[str, pd.DataFrame]:
        """Datos alcistas deterministas para tests de estrategia."""
        import numpy as np

        dates = pd.date_range(end=datetime.now(UTC), periods=periods, freq="1h")
        trend = np.linspace(40000, 55000, periods)
        noise = np.sin(np.linspace(0, 20, periods)) * 200
        close = trend + noise
        df = pd.DataFrame(
            {
                "timestamp": dates,
                "open": close - 50,
                "high": close + 150,
                "low": close - 150,
                "close": close,
                "volume": np.linspace(500, 1200, periods),
            }
        )
        pullback_idx = periods - 5
        df.loc[pullback_idx, "low"] = df.loc[pullback_idx, "close"] - 300
        df.loc[pullback_idx, "close"] = df.loc[pullback_idx, "open"] - 100
        df.loc[periods - 1, "close"] = df.loc[periods - 2, "close"] + 200
        df.loc[periods - 1, "open"] = df.loc[periods - 2, "close"]
        df.loc[periods - 1, "high"] = df.loc[periods - 1, "close"] + 100
        df.loc[periods - 1, "volume"] = 1500
        return {"4h": df.iloc[::4].reset_index(drop=True), "1h": df, "15m": df}
