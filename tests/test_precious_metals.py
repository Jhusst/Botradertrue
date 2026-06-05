from decimal import Decimal

from trading_bot.core.asset_catalog import get_asset_info, quantize_price
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector
from trading_bot.features.signals.generator import SignalGenerator
from trading_bot.features.signals.strategies.precious_metals_mvp import PreciousMetalsMVPStrategy
from trading_bot.features.signals.strategies.trend_pullback_mvp import MarketContext
from trading_bot.schemas.risk import AccountRiskState


def test_asset_catalog_metals() -> None:
    gold = get_asset_info("XAU/USDT:USDT")
    silver = get_asset_info("XAG/USDT:USDT")
    btc = get_asset_info("BTC/USDT")
    assert gold.asset_class == "precious_metal"
    assert silver.asset_class == "precious_metal"
    assert gold.strategy_name == "PreciousMetalsMVP"
    assert btc.asset_class == "crypto"
    assert btc.strategy_name == "TrendPullbackMVP"


def test_quantize_price_silver_three_decimals() -> None:
    price = quantize_price(Decimal("68.2567"), "XAG/USDT:USDT")
    assert price == Decimal("68.257")


def test_metals_strategy_on_trending_data() -> None:
    data = DataCollector.generate_trending_bullish_data(500)
    ctx = MarketContext(symbol="XAU/USDT:USDT", df_4h=data["4h"], df_1h=data["1h"], df_15m=data["15m"])
    out = PreciousMetalsMVPStrategy().analyze(ctx)
    assert out.direction.value in ("LONG", "SHORT", "NO_TRADE")
    assert out.setup_grade.value in ("A", "B", "C")


def test_generator_routes_metals_strategy() -> None:
    data = DataCollector.generate_trending_bullish_data(500)
    ctx = MarketContext(symbol="XAG/USDT:USDT", df_4h=data["4h"], df_1h=data["1h"], df_15m=data["15m"])
    account = AccountRiskState(
        balance_usdt=Decimal("60"),
        risk_setup_a=Decimal("0.25"),
        risk_setup_b=Decimal("0.15"),
        min_setup_grade="B",
    )
    sig = SignalGenerator().generate(ctx, account)
    assert sig.strategy_name == "PreciousMetalsMVP"
