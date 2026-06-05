from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_mode: Literal["PAPER", "LIVE"] = "PAPER"
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./trading_bot.db"
    database_url_sync: str = "sqlite:///./trading_bot.db"
    redis_url: str = "redis://localhost:6379/0"

    default_account_balance: float = 60.0
    default_risk_percent: float = 0.25
    max_daily_loss_percent: float = 2.0
    max_weekly_loss_percent: float = 5.0
    max_consecutive_losses: int = 2
    min_risk_reward_ratio: float = 2.0
    consecutive_loss_cooldown_hours: int = 4

    # Riesgo por grado de setup
    risk_setup_a: float = 1.0
    risk_setup_a_manual: float = 1.5
    risk_setup_b: float = 0.5
    risk_setup_c: float = 0.0

    # Apalancamiento
    max_leverage: int = 20
    min_leverage: int = 1

    # Backtest / paper unlock
    min_paper_trades_for_live: int = 100
    min_profit_factor_for_live: float = 1.3
    max_drawdown_for_live: float = 10.0
    max_loss_streak_for_live: int = 5

    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = False
    broker_enabled: bool = False
    auto_execute_on_enter: bool = False
    sync_balance_from_broker: bool = False

    # Modo autónomo (sin intervención humana)
    autonomous_trading_enabled: bool = False
    ai_gate_auto_trade: bool = True
    ai_required_for_auto_trade: bool = False
    ai_auto_min_verdict: str = "CONFIRM"
    min_balance_for_autonomous: float = 1.0
    compound_balance_on_close: bool = True

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    live_mode_enabled: bool = Field(default=False, description="Candado de ejecución real")

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    ollama_vision_model: str = "llava"
    ai_enabled: bool = False
    ai_max_confidence_adjustment: float = 10.0

    # Monitoreo automático
    monitor_enabled: bool = True
    watch_symbols: str = "BTC/USDT,ETH/USDT,SOL/USDT,AVAX/USDT,ADA/USDT,HYPE/USDT"
    scan_interval_seconds: int = 300
    price_check_interval_seconds: int = 30
    entry_proximity_percent: float = 0.5
    signal_ttl_hours: int = 4
    dedup_signal_minutes: int = 30
    auto_paper_trade: bool = True
    monitor_use_live_data: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
