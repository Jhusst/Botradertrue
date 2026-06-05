from fastapi import APIRouter

from trading_bot import __version__
from trading_bot.config.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "mode": settings.app_mode,
        "live_enabled": settings.live_mode_enabled,
    }
