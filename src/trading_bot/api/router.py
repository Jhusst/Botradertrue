"""Registro centralizado de routers por feature."""
from fastapi import APIRouter

from trading_bot.api.routes.health import router as health_router
from trading_bot.features.ai.routes import router as ai_router
from trading_bot.features.autonomous.routes import router as autonomous_router
from trading_bot.features.broker.routes import router as broker_router
from trading_bot.features.dashboard.routes import router as dashboard_router
from trading_bot.features.monitoring.routes import router as monitoring_router
from trading_bot.features.profiles.routes import router as profiles_router
from trading_bot.features.safety.routes import router as safety_router
from trading_bot.features.setup.routes import router as setup_router
from trading_bot.features.signals.monitor_routes import router as monitor_router
from trading_bot.features.signals.outcome_routes import router as signal_outcomes_router
from trading_bot.features.signals.routes import router as signals_router
from trading_bot.features.trades.paper_routes import router as paper_trades_router
from trading_bot.features.trades.user_routes import router as user_trades_router

API_PREFIX = "/api/v1"

FEATURE_ROUTERS: list[APIRouter] = [
    signals_router,
    signal_outcomes_router,
    monitor_router,
    paper_trades_router,
    dashboard_router,
    setup_router,
    profiles_router,
    user_trades_router,
    ai_router,
    broker_router,
    autonomous_router,
    safety_router,
    monitoring_router,
]

__all__ = [
    "API_PREFIX",
    "FEATURE_ROUTERS",
    "ai_router",
    "autonomous_router",
    "broker_router",
    "dashboard_router",
    "health_router",
    "monitoring_router",
    "monitor_router",
    "paper_trades_router",
    "profiles_router",
    "safety_router",
    "setup_router",
    "signals_router",
    "user_trades_router",
]
