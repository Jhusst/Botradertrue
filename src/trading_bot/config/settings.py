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
    active_profile_types: str = "conservative,aggressive"

    def active_profile_type_set(self) -> set[str]:
        return {p.strip() for p in self.active_profile_types.split(",") if p.strip()}

    # Idempotencia / reconciliación
    client_order_prefix: str = "tbot"
    reconcile_interval_seconds: int = 60
    reconcile_on_startup: bool = True
    adopt_unknown_positions: bool = False

    # Protección garantizada (SL obligatorio)
    sl_placement_max_retries: int = 4
    sl_placement_backoff_base_seconds: float = 1.0
    flatten_on_protection_failure: bool = True

    # Resiliencia de red
    exchange_retry_max_attempts: int = 4
    exchange_retry_backoff_base: float = 0.5
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_seconds: float = 120.0
    monitor_cycle_timeout_seconds: int = 120
    watchdog_interval_seconds: int = 60
    watchdog_stale_after_seconds: int = 180

    # Kill-switch / límite absoluto de pérdida (pensado para cuenta chica)
    max_total_loss_usdt: float = 50.0
    min_equity_usdt: float = 0.0
    initial_equity_usdt: float = 500.0
    telegram_commands_enabled: bool = False
    telegram_command_poll_seconds: int = 5

    # Logging / operación
    log_file_path: str = "./logs/trading_bot.log"
    log_max_bytes: int = 10_485_760
    log_backup_count: int = 10
    startup_alert_enabled: bool = True

    # Datos históricos / alt-data
    data_dir: str = "./data"
    history_backfill_days: int = 730
    derivatives_enabled: bool = True

    # Régimen de mercado
    regime_detection_enabled: bool = True

    # Kelly fraccionado (solo reduce el riesgo, nunca lo aumenta)
    kelly_enabled: bool = False
    kelly_fraction: float = 0.25
    kelly_lookback_trades: int = 50
    kelly_min_trades: int = 20
    kelly_cap_risk_percent: float = 0.5
    kelly_floor_risk_percent: float = 0.1

    # Filtro ML (meta-labeling)
    ml_filter_enabled: bool = False
    ml_filter_mode: Literal["filter", "advise"] = "advise"
    ml_min_success_probability: float = 0.55
    ml_models_dir: str = "./models"
    ml_retrain_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
