from decimal import Decimal

from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.schemas.signal import SignalCreate


def test_format_no_trade() -> None:
    signal = SignalCreate(
        symbol="BTC/USDT",
        direction="NO_TRADE",
        primary_timeframe="1h",
        account_balance=Decimal("10000"),
        risk_percent=Decimal("0"),
        setup_grade="C",
        technical_explanation="Sin setup",
        rejection_reason="Mercado lateral",
        should_trade=False,
    )
    text = TelegramNotifier()._format_signal(signal)
    assert "NO TRADE" in text
    assert "BTC/USDT" in text


def test_not_configured_without_token() -> None:
    from trading_bot.config.settings import Settings

    notifier = TelegramNotifier(Settings(telegram_bot_token="", telegram_chat_id=""))
    assert notifier.is_configured is False
