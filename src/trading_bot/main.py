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
from trading_bot.db.session import engine
from trading_bot.infrastructure.workers.background import start_background_monitor, stop_background_monitor


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
for feature_router in FEATURE_ROUTERS:
    app.include_router(feature_router, prefix=API_PREFIX)


@app.get("/dashboard")
async def dashboard_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")
