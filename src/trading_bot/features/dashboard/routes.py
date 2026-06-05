from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import get_settings
from trading_bot.core.asset_catalog import asset_class_label, get_asset_info, parse_watch_symbols
from trading_bot.core.enums import SignalStatus
from trading_bot.features.signals.monitor.price_feed import PriceFeed
from trading_bot.core.profile_presets import PRESETS
from trading_bot.db.models.account import Account
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.trade import PaperTrade
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.db.session import get_db
from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.infrastructure.workers.background import get_monitor

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _trade_source(notes: str | None) -> str:
    if not notes:
        return "manual"
    if notes.startswith("manual|"):
        return "manual"
    if "auto-entry" in notes or "Binance order" in notes:
        return "auto"
    return "manual"


def _distance_percent(entry: Decimal | None, price: Decimal | None) -> float | None:
    if not entry or not price or entry == 0:
        return None
    return float(abs(price - entry) / entry * 100)


def _format_ttl(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds <= 0:
        return "Caducada"
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _entry_state(
    direction: str,
    entry: Decimal | None,
    price: Decimal | None,
    status: str,
    expires_in: int | None,
) -> dict:
    """Estado real de la entrada según dirección, precio y vigencia."""
    if status == SignalStatus.EXPIRED.value:
        return {
            "action": "EXPIRED",
            "label": "Caducada — ya no operar",
            "urgent": False,
            "can_enter": False,
        }
    if status == SignalStatus.INVALIDATED.value:
        return {
            "action": "INVALIDATED",
            "label": "Invalidada — precio tocó el stop antes de entrar",
            "urgent": False,
            "can_enter": False,
        }
    if status in (SignalStatus.CLOSED.value, SignalStatus.ACTIVE.value):
        label = (
            "Señal activa — consulta niveles o registra tu entrada manual (otro apalancamiento)"
            if status == SignalStatus.ACTIVE.value
            else "Trade cerrado"
        )
        return {
            "action": "ACTIVE" if status == SignalStatus.ACTIVE.value else "CLOSED",
            "label": label,
            "urgent": False,
            "can_enter": False,
            "can_enter_manual": status == SignalStatus.ACTIVE.value,
        }
    if expires_in is not None and expires_in <= 0:
        return {
            "action": "EXPIRED",
            "label": "Caducada — ventana de 4h agotada",
            "urgent": False,
            "can_enter": False,
        }
    if not entry or not price:
        return {
            "action": "WAITING",
            "label": "Esperando precio en vivo…",
            "urgent": False,
            "can_enter": False,
        }

    dist = float(abs(price - entry) / entry * 100)

    if direction == "LONG":
        if price <= entry:
            return {
                "action": "ENTER_NOW",
                "label": "ENTRAR AHORA — precio en o bajo la entrada LONG",
                "urgent": True,
                "can_enter": True,
                "can_enter_manual": True,
            }
        if dist <= 0.5:
            return {
                "action": "APPROACHING",
                "label": f"Acercándose — precio {dist:.2f}% arriba (espera que baje a {entry})",
                "urgent": False,
                "can_enter": False,
                "can_enter_manual": True,
            }
        return {
            "action": "WAITING",
            "label": f"Esperando pullback — precio {dist:.2f}% arriba de entrada",
            "urgent": False,
            "can_enter": False,
            "can_enter_manual": False,
        }

    if direction == "SHORT":
        if price >= entry:
            return {
                "action": "ENTER_NOW",
                "label": "ENTRAR AHORA — precio en o sobre la entrada SHORT",
                "urgent": True,
                "can_enter": True,
                "can_enter_manual": True,
            }
        if dist <= 0.5:
            return {
                "action": "APPROACHING",
                "label": f"Acercándose — precio {dist:.2f}% debajo (espera que suba a {entry})",
                "urgent": False,
                "can_enter": False,
                "can_enter_manual": True,
            }
        return {
            "action": "WAITING",
            "label": f"Esperando rebote — precio {dist:.2f}% debajo de entrada",
            "urgent": False,
            "can_enter": False,
            "can_enter_manual": False,
        }

    return {
        "action": "WAITING",
        "label": "—",
        "urgent": False,
        "can_enter": False,
        "can_enter_manual": False,
    }


def _build_trade_plan(
    direction: str,
    expires_iso: str | None,
    expires_in: int | None,
    status: str,
    opened_at_iso: str | None,
    signal_ttl_hours: int,
    invalidation: str | None = None,
) -> dict:
    is_active = status == SignalStatus.ACTIVE.value
    return {
        "entry_window": _format_ttl(expires_in) if not is_active else "Ya entraste — gestiona el trade",
        "entry_valid_until": expires_iso,
        "tp1_rule": "Al tocar TP1: cierra ~50% o mueve el SL a tu precio de entrada (breakeven).",
        "tp2_rule": "Al tocar TP2: cierra el resto. Es el objetivo principal del setup.",
        "sl_rule": "Si toca el SL → sal de inmediato. No esperes ni muevas el SL en contra.",
        "max_hold": (
            f"Máximo ~{signal_ttl_hours}h desde la señal. Setup 1H: suele resolverse en 2–8h tras entrar."
        ),
        "invalidation": invalidation or "Cierre de vela 1H en contra de tu dirección.",
        "opened_at": opened_at_iso,
        "is_active": is_active,
    }


async def _build_markets_overview(
    db: AsyncSession,
    watch_symbols: list[str],
    use_live: bool,
    *,
    fetch_live_prices: bool = True,
) -> list[dict]:
    price_feed = PriceFeed(use_live=use_live) if fetch_live_prices else None
    result = await db.execute(
        select(Signal).where(
            Signal.should_trade.is_(True),
            Signal.status.in_([SignalStatus.WATCHING.value, SignalStatus.ACTIVE.value]),
        )
    )
    active_signals = result.scalars().all()

    price_map: dict[str, str] = {}
    if fetch_live_prices and price_feed:
        try:
            batch = price_feed.get_prices_batch(watch_symbols)
            price_map = {sym: str(price) for sym, price in batch.items()}
        except Exception:
            price_map = {}

    markets: list[dict] = []
    for symbol in watch_symbols:
        asset = get_asset_info(symbol)
        sym_signals = [s for s in active_signals if s.symbol == symbol]
        price_str: str | None = price_map.get(symbol)
        if not price_str and sym_signals and sym_signals[0].last_price:
            price_str = str(sym_signals[0].last_price)
        urgent = any(
            _entry_state(s.direction, s.entry_price, s.last_price, s.status, None)["action"] == "ENTER_NOW"
            for s in sym_signals
        )
        markets.append({
            "symbol": symbol,
            "display_name": asset.display_name,
            "asset_class": asset.asset_class,
            "asset_class_label": asset_class_label(asset.asset_class),
            "strategy_name": asset.strategy_name,
            "last_price": price_str,
            "active_signals": len(sym_signals),
            "has_signal": bool(sym_signals),
            "status_label": (
                "ENTRAR AHORA" if urgent else ("Señal activa" if sym_signals else "Escaneando…")
            ),
            "urgent": urgent,
        })
    return markets


async def _build_dashboard_payload(
    db: AsyncSession,
    *,
    fetch_live_prices: bool,
) -> dict:
    settings = get_settings()
    monitor = get_monitor()
    notifier = TelegramNotifier(settings)

    accounts_result = await db.execute(select(Account).order_by(Account.id))
    accounts = accounts_result.scalars().all()

    profiles_data = []
    total_equity = Decimal("0")

    for acc in accounts:
        preset = PRESETS.get(acc.profile_type)
        trades_q = await db.execute(select(UserTrade).where(UserTrade.account_id == acc.id))
        user_trades = trades_q.scalars().all()
        open_trades = [t for t in user_trades if t.status == "OPEN"]
        closed_trades = [t for t in user_trades if t.status == "CLOSED"]
        realized_pnl = sum(
            (t.pnl_usdt or Decimal("0") for t in closed_trades),
            Decimal("0"),
        )
        equity = acc.balance_usdt
        total_equity += equity

        signals_q = await db.execute(
            select(Signal)
            .where(Signal.account_id == acc.id, Signal.should_trade.is_(True))
            .order_by(Signal.created_at.desc())
            .limit(10)
        )
        signals = signals_q.scalars().all()

        signal_cards = []
        for s in signals:
            expires_in = None
            if s.expires_at:
                exp = s.expires_at.replace(tzinfo=UTC) if s.expires_at.tzinfo is None else s.expires_at
                expires_in = max(0, int((exp - datetime.now(UTC)).total_seconds()))
            open_for_signal = [ut for ut in user_trades if ut.signal_id == s.id and ut.status == "OPEN"]
            manual_open = any(
                (ut.notes or "").startswith("manual|") for ut in open_for_signal
            )
            bot_open = any(
                "auto-entry" in (ut.notes or "") for ut in open_for_signal
            )
            has_open = bool(open_for_signal)
            asset = get_asset_info(s.symbol)
            entry_state = _entry_state(s.direction, s.entry_price, s.last_price, s.status, expires_in)
            created = s.created_at.replace(tzinfo=UTC) if s.created_at and s.created_at.tzinfo is None else s.created_at
            expires_iso = None
            if s.expires_at:
                exp = s.expires_at.replace(tzinfo=UTC) if s.expires_at.tzinfo is None else s.expires_at
                expires_iso = exp.isoformat()
            signal_cards.append({
                "id": s.id,
                "symbol": s.symbol,
                "display_name": asset.display_name,
                "asset_class": asset.asset_class,
                "asset_class_label": asset_class_label(asset.asset_class),
                "direction": s.direction,
                "status": s.status,
                "setup_grade": s.setup_grade,
                "strategy_name": s.strategy_name,
                "primary_timeframe": s.primary_timeframe,
                "analysis_timeframes": "4H tendencia · 1H entrada · 15M volumen",
                "entry_price": str(s.entry_price) if s.entry_price else None,
                "stop_loss": str(s.stop_loss) if s.stop_loss else None,
                "take_profit_1": str(s.take_profit_1) if s.take_profit_1 else None,
                "take_profit_2": str(s.take_profit_2) if s.take_profit_2 else None,
                "last_price": str(s.last_price) if s.last_price else None,
                "distance_percent": _distance_percent(s.entry_price, s.last_price),
                "entry_action": entry_state["action"],
                "entry_label": entry_state["label"],
                "entry_urgent": entry_state["urgent"],
                "can_enter": entry_state.get("can_enter", False) and not has_open,
                "can_enter_manual": entry_state.get("can_enter_manual", False) and not manual_open,
                "manual_trade_open": manual_open,
                "bot_trade_open": bot_open,
                "risk_percent": str(s.risk_percent),
                "risk_usdt": str(s.risk_usdt) if s.risk_usdt else None,
                "margin_required": str(s.margin_required) if s.margin_required else None,
                "recommended_leverage": s.recommended_leverage,
                "max_loss_usdt": str(s.max_loss_usdt) if s.max_loss_usdt else None,
                "estimated_gain_tp2_usdt": str(s.estimated_gain_tp2_usdt) if s.estimated_gain_tp2_usdt else None,
                "expires_at": expires_iso,
                "expires_in_seconds": expires_in,
                "expires_label": _format_ttl(expires_in),
                "created_at": created.isoformat() if created else None,
                "user_trade_open": has_open,
                "trade_plan": _build_trade_plan(
                    s.direction,
                    expires_iso,
                    expires_in,
                    s.status,
                    None,
                    settings.signal_ttl_hours,
                    s.invalidation_conditions,
                ),
            })

        profiles_data.append({
            "id": acc.id,
            "name": acc.name,
            "profile_type": acc.profile_type,
            "description": preset.description if preset else "",
            "balance_usdt": str(acc.balance_usdt),
            "realized_pnl_usdt": str(realized_pnl.quantize(Decimal("0.01"))),
            "equity_usdt": str(equity.quantize(Decimal("0.01"))),
            "risk_setup_a": str(acc.risk_setup_a),
            "risk_setup_b": str(acc.risk_setup_b),
            "max_leverage": acc.max_leverage,
            "open_trades_count": len(open_trades),
            "signals": signal_cards,
            "open_trades": [
                {
                    "id": t.id,
                    "signal_id": t.signal_id,
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "entry_price": str(t.entry_price),
                    "stop_loss": str(t.stop_loss),
                    "take_profit_1": str(t.take_profit_1) if t.take_profit_1 else None,
                    "take_profit_2": str(t.take_profit_2) if t.take_profit_2 else None,
                    "leverage": t.leverage,
                    "risk_usdt": str(t.risk_usdt),
                    "margin_used": str(t.margin_used),
                    "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                    "trade_plan": _build_trade_plan(
                        t.direction,
                        None,
                        None,
                        SignalStatus.ACTIVE.value,
                        t.opened_at.isoformat() if t.opened_at else None,
                        settings.signal_ttl_hours,
                    ),
                    "max_loss_usdt": str(t.risk_usdt),
                }
                for t in open_trades
            ],
            "is_micro_capital": equity < Decimal("10"),
        })

    all_user_trades = await db.execute(
        select(UserTrade).order_by(UserTrade.created_at.desc()).limit(20)
    )
    history = all_user_trades.scalars().all()

    paper_result = await db.execute(select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(5))
    paper_trades = paper_result.scalars().all()

    watch_list = parse_watch_symbols(settings.watch_symbols)
    markets = await _build_markets_overview(
        db, watch_list, settings.monitor_use_live_data, fetch_live_prices=fetch_live_prices
    )
    crypto_markets = [m for m in markets if m["asset_class"] == "crypto"]
    metal_markets = [m for m in markets if m["asset_class"] == "precious_metal"]

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "monitor": monitor.status(),
        "telegram_configured": notifier.is_configured,
        "mode": settings.app_mode,
        "signal_ttl_hours": settings.signal_ttl_hours,
        "price_check_interval_seconds": settings.price_check_interval_seconds,
        "watch_symbols": watch_list,
        "markets": markets,
        "markets_crypto": crypto_markets,
        "markets_metals": metal_markets,
        "portfolio_total_usdt": str(total_equity.quantize(Decimal("0.01"))),
        "profiles": profiles_data,
        "trade_history": [
            {
                "id": t.id,
                "profile_id": t.account_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "status": t.status,
                "source": _trade_source(t.notes),
                "leverage": t.leverage,
                "pnl_usdt": str(t.pnl_usdt) if t.pnl_usdt else None,
                "close_reason": t.close_reason,
                "notes": t.notes,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in history
        ],
        "auto_trades_open": [
            {
                "id": t.id,
                "profile_id": t.account_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "leverage": t.leverage,
                "entry_price": str(t.entry_price),
                "stop_loss": str(t.stop_loss),
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                "notes": t.notes,
            }
            for t in history
            if t.status == "OPEN" and _trade_source(t.notes) == "auto"
        ],
        "paper_trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "direction": t.direction,
                "status": t.status,
                "source": "paper",
                "pnl_usdt": str(t.pnl_usdt) if t.pnl_usdt else None,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            }
            for t in paper_trades
        ],
        "storage": {
            "database_file": "trading_bot.db",
            "trades_table": "user_trades",
            "note": "Tus trades se guardan localmente en SQLite al pulsar 'Entré al trade'.",
        },
        "broker": {
            "enabled": settings.broker_enabled,
            "auto_execute": settings.auto_execute_on_enter,
            "live_mode": settings.live_mode_enabled,
            "testnet": settings.binance_testnet,
            "api_configured": bool(settings.binance_api_key and settings.binance_api_secret),
            "sync_balance": settings.sync_balance_from_broker,
        },
        "autonomous": {
            "enabled": settings.autonomous_trading_enabled,
            "ai_gate": settings.ai_gate_auto_trade,
            "ai_enabled": settings.ai_enabled,
            "ai_min_verdict": settings.ai_auto_min_verdict,
            "min_balance_usdt": settings.min_balance_for_autonomous,
        },
        "lite": not fetch_live_prices,
    }


@router.get("/lite")
async def dashboard_lite(db: AsyncSession = Depends(get_db)) -> dict:
    """Respuesta rápida sin llamadas a exchange (ideal para polling frecuente)."""
    return await _build_dashboard_payload(db, fetch_live_prices=False)


@router.get("/data")
async def dashboard_data(db: AsyncSession = Depends(get_db)) -> dict:
    return await _build_dashboard_payload(db, fetch_live_prices=True)
