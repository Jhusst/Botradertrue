from fastapi import APIRouter

from trading_bot.workers.background import get_monitor, start_background_monitor, stop_background_monitor

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/status")
async def monitor_status() -> dict:
    return get_monitor().status()


@router.post("/start")
async def monitor_start() -> dict:
    await start_background_monitor()
    return {"ok": True, "status": get_monitor().status()}


@router.post("/stop")
async def monitor_stop() -> dict:
    await stop_background_monitor()
    return {"ok": True, "status": get_monitor().status()}


@router.post("/run-once")
async def monitor_run_once() -> dict:
    """Ejecuta un ciclo manual (útil para pruebas)."""
    result = await get_monitor().run_cycle()
    return {"ok": True, **result, "status": get_monitor().status()}
