from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot import __version__
from trading_bot.config.settings import get_settings
from trading_bot.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Liviano: 200 si el proceso vive (para NSSM/monitores externos)."""
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "mode": settings.app_mode,
        "live_enabled": settings.live_mode_enabled,
    }


@router.get("/health/deep")
async def health_deep(response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """Profundo: 503 si DB no responde, heartbeat viejo, breaker abierto o kill-switch."""
    settings = get_settings()
    checks: dict[str, dict] = {}
    healthy = True

    # DB
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "error": str(exc)}
        healthy = False

    # Heartbeat del monitor
    heartbeat_age: float | None = None
    try:
        from trading_bot.db.init_db import ensure_bot_state

        state = await ensure_bot_state(db)
        hb = state.last_heartbeat_at
        if hb is not None:
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=UTC)
            heartbeat_age = (datetime.now(UTC) - hb).total_seconds()
        monitor_ok = (
            not settings.monitor_enabled
            or (heartbeat_age is not None and heartbeat_age < settings.watchdog_stale_after_seconds)
        )
        checks["monitor"] = {
            "ok": monitor_ok,
            "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        }
        if not monitor_ok:
            healthy = False
        checks["kill_switch"] = {
            "engaged": state.kill_switch_engaged,
            "reason": state.kill_switch_reason,
        }
    except Exception as exc:  # noqa: BLE001
        checks["monitor"] = {"ok": False, "error": str(exc)}
        healthy = False

    # Circuit breaker
    from trading_bot.infrastructure.resilience import exchange_breaker

    breaker_state = exchange_breaker.state
    checks["circuit_breaker"] = {"ok": breaker_state != "OPEN", "state": breaker_state}
    if breaker_state == "OPEN":
        healthy = False

    if not healthy:
        response.status_code = 503
    return {"status": "ok" if healthy else "degraded", "checks": checks}
