from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from trading_bot import __version__
from trading_bot.api.router import API_PREFIX, FEATURE_ROUTERS, health_router
from trading_bot.config.settings import get_settings
from trading_bot.db.init_db import create_tables
from trading_bot.db.session import async_session_factory, engine
from trading_bot.features.alerts.command_listener import (
    start_command_listener,
    stop_command_listener,
)
from trading_bot.infrastructure.logging_setup import configure_logging
from trading_bot.infrastructure.workers.background import start_background_monitor, stop_background_monitor


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    await create_tables(engine)

    # Reconciliación de arranque ANTES de monitorear: repone SLs, cierra
    # trades que el exchange ya cerró y resuelve intents huérfanos.
    if settings.broker_enabled and settings.binance_api_key:
        from trading_bot.features.reconciliation.startup import reconcile_on_startup

        try:
            await reconcile_on_startup(async_session_factory, settings)
        except Exception:  # noqa: BLE001 — el arranque no debe morir por esto
            import structlog

            structlog.get_logger().exception("startup_reconcile_failed")

    if settings.monitor_enabled:
        await start_background_monitor()
    await start_command_listener(async_session_factory)
    yield
    await stop_command_listener()
    await stop_background_monitor()


app = FastAPI(
    title="Trading Bot API",
    description="Sistema semiautomático de señales con gestión de riesgo controlada",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(health_router)
for feature_router in FEATURE_ROUTERS:
    app.include_router(feature_router, prefix=API_PREFIX)


@app.get("/dashboard")
async def dashboard_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")
