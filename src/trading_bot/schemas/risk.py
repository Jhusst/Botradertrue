from decimal import Decimal

from pydantic import BaseModel, Field

from trading_bot.core.enums import SetupGrade, TradeDirection


class AccountRiskState(BaseModel):
    balance_usdt: Decimal
    daily_pnl_usdt: Decimal = Decimal("0")
    weekly_pnl_usdt: Decimal = Decimal("0")
    consecutive_losses: int = 0
    current_drawdown_percent: Decimal = Decimal("0")
    open_positions_count: int = 0
    profile_type: str = "conservative"
    risk_setup_a: Decimal | None = None
    risk_setup_b: Decimal | None = None
    max_leverage: int | None = None
    min_setup_grade: str = "A"


class SetupCandidate(BaseModel):
    symbol: str
    direction: TradeDirection
    primary_timeframe: str
    entry_price: Decimal
    stop_loss: Decimal
    take_profit_1: Decimal
    take_profit_2: Decimal
    setup_grade: SetupGrade
    confidence_score: Decimal = Field(ge=0, le=100)
    technical_explanation: str
    invalidation_conditions: str
    atr_percent: Decimal | None = None
    has_high_impact_event_nearby: bool = False
    manual_approval: bool = False


class RiskAssessment(BaseModel):
    approved: bool
    direction: TradeDirection
    setup_grade: SetupGrade
    risk_percent: Decimal
    risk_usdt: Decimal
    rejection_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PositionSizingInput(BaseModel):
    balance_usdt: Decimal
    risk_percent: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    take_profit_1: Decimal
    take_profit_2: Decimal
    direction: TradeDirection
    setup_grade: SetupGrade
    primary_timeframe: str
    atr_percent: Decimal | None = None
    volatility_multiplier: Decimal = Decimal("1")
    drawdown_percent: Decimal = Decimal("0")
    has_high_impact_event_nearby: bool = False
    liquidity_score: Decimal = Decimal("1")
    asset_class: str = "crypto"
    max_leverage_cap: int | None = None


class PositionSizingResult(BaseModel):
    position_size_usdt: Decimal
    margin_required_usdt: Decimal
    recommended_leverage: int
    risk_usdt: Decimal
    max_loss_usdt: Decimal
    estimated_gain_tp1_usdt: Decimal
    estimated_gain_tp2_usdt: Decimal
    stop_distance_percent: Decimal
    tp1_distance_percent: Decimal
    tp2_distance_percent: Decimal
    risk_reward_ratio: Decimal
    liquidation_price: Decimal | None
    recommended_capital_usdt: Decimal
