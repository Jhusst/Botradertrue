from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from trading_bot.core.enums import SetupGrade, SignalStatus, TradeDirection


class SignalCreate(BaseModel):
    symbol: str
    direction: TradeDirection
    primary_timeframe: str
    entry_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit_1: Decimal | None = None
    take_profit_2: Decimal | None = None
    risk_reward_ratio: Decimal | None = None
    account_balance: Decimal
    risk_percent: Decimal
    risk_usdt: Decimal | None = None
    recommended_capital_usdt: Decimal | None = None
    recommended_leverage: int | None = None
    max_loss_usdt: Decimal | None = None
    estimated_gain_tp1_usdt: Decimal | None = None
    estimated_gain_tp2_usdt: Decimal | None = None
    position_size: Decimal | None = None
    margin_required: Decimal | None = None
    stop_distance_percent: Decimal | None = None
    tp1_distance_percent: Decimal | None = None
    tp2_distance_percent: Decimal | None = None
    liquidation_price: Decimal | None = None
    setup_grade: SetupGrade
    confidence_score: Decimal | None = None
    technical_explanation: str | None = None
    invalidation_conditions: str | None = None
    should_trade: bool = False
    rejection_reason: str | None = None
    strategy_name: str = "TrendPullbackMVP"
    ml_probability: float | None = None
    ml_model_version: str | None = None


class SignalResponse(BaseModel):
    id: int
    symbol: str
    direction: TradeDirection
    primary_timeframe: str
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit_1: Decimal | None
    take_profit_2: Decimal | None
    risk_reward_ratio: Decimal | None
    account_balance: Decimal
    risk_percent: Decimal
    risk_usdt: Decimal | None
    recommended_capital_usdt: Decimal | None
    recommended_leverage: int | None
    max_loss_usdt: Decimal | None
    estimated_gain_tp1_usdt: Decimal | None
    estimated_gain_tp2_usdt: Decimal | None
    position_size: Decimal | None
    margin_required: Decimal | None
    stop_distance_percent: Decimal | None
    tp1_distance_percent: Decimal | None
    tp2_distance_percent: Decimal | None
    liquidation_price: Decimal | None
    setup_grade: SetupGrade
    confidence_score: Decimal | None
    technical_explanation: str | None
    invalidation_conditions: str | None
    should_trade: bool
    status: SignalStatus
    rejection_reason: str | None
    strategy_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SignalListResponse(BaseModel):
    items: list[SignalResponse]
    total: int
    page: int
    page_size: int
