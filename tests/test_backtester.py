from decimal import Decimal

from trading_bot.features.backtest.engine import BacktestEngine
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector


def test_backtest_runs_without_error() -> None:
    data = DataCollector.generate_sample_data(500)
    engine = BacktestEngine(initial_balance=Decimal("10000"))
    metrics = engine.run(data["4h"], data["1h"], data["15m"])
    assert metrics.total_trades >= 0
    assert metrics.final_balance > Decimal("0")
    assert isinstance(metrics.profit_factor, Decimal)
