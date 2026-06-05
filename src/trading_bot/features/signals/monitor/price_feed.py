import time
from decimal import Decimal

from trading_bot.infrastructure.market_data.ccxt_client import DataCollector

# Un solo cliente CCXT compartido (evita reload de mercados)
_shared_collector: DataCollector | None = None


def get_shared_collector() -> DataCollector:
    global _shared_collector
    if _shared_collector is None:
        _shared_collector = DataCollector()
    return _shared_collector


class PriceFeed:
    """Obtiene precios actuales desde CCXT con caché breve."""

    CACHE_TTL_SECONDS = 15
    _cache: dict[str, tuple[Decimal, float]] = {}

    def __init__(self, use_live: bool = True) -> None:
        self.use_live = use_live

    @property
    def collector(self) -> DataCollector:
        return get_shared_collector()

    def get_price(self, symbol: str, *, use_cache: bool = True) -> Decimal:
        prices = self.get_prices_batch([symbol], use_cache=use_cache)
        return prices[symbol]

    def get_prices_batch(self, symbols: list[str], *, use_cache: bool = True) -> dict[str, Decimal]:
        if not symbols:
            return {}

        now = time.time()
        result: dict[str, Decimal] = {}
        to_fetch: list[str] = []

        for symbol in symbols:
            if use_cache and symbol in self._cache:
                cached_price, cached_at = self._cache[symbol]
                if now - cached_at < self.CACHE_TTL_SECONDS:
                    result[symbol] = cached_price
                    continue
            to_fetch.append(symbol)

        if not to_fetch:
            return result

        if not self.use_live:
            data = DataCollector.generate_sample_data(10)
            sample = Decimal(str(round(float(data["1h"]["close"].iloc[-1]), 2)))
            for symbol in to_fetch:
                self._cache[symbol] = (sample, now)
                result[symbol] = sample
            return result

        resolved_map = {symbol: self.collector._resolve_symbol(symbol) for symbol in to_fetch}
        try:
            tickers = self.collector.exchange.fetch_tickers(list(resolved_map.values()))
        except Exception:
            for symbol in to_fetch:
                resolved = resolved_map[symbol]
                ticker = self.collector.exchange.fetch_ticker(resolved)
                price = Decimal(str(ticker["last"]))
                self._cache[symbol] = (price, now)
                result[symbol] = price
            return result

        for symbol, resolved in resolved_map.items():
            ticker = tickers.get(resolved) or {}
            last = ticker.get("last")
            if last is None:
                continue
            price = Decimal(str(last))
            self._cache[symbol] = (price, now)
            result[symbol] = price

        return result

    def get_market_data(self, symbol: str) -> dict:
        if not self.use_live:
            return DataCollector.generate_sample_data(500)
        return self.collector.fetch_multi_timeframe(symbol)
