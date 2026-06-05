from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from trading_bot import __version__
from trading_bot.api.routes.ai import router as ai_router
from trading_bot.api.routes.autonomous import router as autonomous_router
from trading_bot.api.routes.broker import router as broker_router
from trading_bot.api.routes.dashboard import router as dashboard_router
from trading_bot.api.routes.health import router as health_router
from trading_bot.api.routes.monitor import router as monitor_router
from trading_bot.api.routes.paper_trades import router as paper_trades_router
from trading_bot.api.routes.profiles import router as profiles_router
from trading_bot.api.routes.setup import router as setup_router
from trading_bot.api.routes.signals import router as signals_router
from trading_bot.api.routes.user_trades import router as user_trades_router
from trading_bot.config.settings import get_settings
from trading_bot.db.init_db import create_tables
from trading_bot.db.session import engine
from trading_bot.workers.background import start_background_monitor, stop_background_monitor


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await create_tables(engine)
    if get_settings().monitor_enabled:
        await start_background_monitor()
    yield
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
app.include_router(signals_router, prefix="/api/v1")
app.include_router(monitor_router, prefix="/api/v1")
app.include_router(paper_trades_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(setup_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(user_trades_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(broker_router, prefix="/api/v1")
app.include_router(autonomous_router, prefix="/api/v1")


@app.get("/dashboard")
async def dashboard_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")
