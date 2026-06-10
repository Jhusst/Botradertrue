"""Endpoints de seguridad: estado, pausa, flatten-all, kill-switch y rearme.

Las acciones destructivas exigen confirmación literal en el body para
evitar ejecuciones accidentales desde el dashboard o curl.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.db.session import get_db
from trading_bot.features.safety.service import SafetyService

router = APIRouter(prefix="/safety", tags=["safety"])


class PauseRequest(BaseModel):
    reason: str = "manual"


class FlattenAllRequest(BaseModel):
    confirm: str
    reason: str = "manual"


class KillRequest(BaseModel):
    confirm: str
    reason: str = "manual"


class ArmRequest(BaseModel):
    confirm: str


@router.get("/status")
async def safety_status(db: AsyncSession = Depends(get_db)) -> dict:
    return await SafetyService(db).status_summary()


@router.post("/pause")
async def pause_entries(body: PauseRequest, db: AsyncSession = Depends(get_db)) -> dict:
    state = await SafetyService(db).pause_entries(body.reason, by="api")
    return {"ok": True, "entries_paused": state.entries_paused, "reason": state.pause_reason}


@router.post("/resume")
async def resume_entries(db: AsyncSession = Depends(get_db)) -> dict:
    service = SafetyService(db)
    state = await service.get_state()
    if state.kill_switch_engaged:
        raise HTTPException(409, "Kill-switch activado: usa POST /safety/arm para rearmar")
    state = await service.resume_entries(by="api")
    return {"ok": True, "entries_paused": state.entries_paused}


@router.post("/flatten-all")
async def flatten_all(body: FlattenAllRequest, db: AsyncSession = Depends(get_db)) -> dict:
    if body.confirm != "FLATTEN":
        raise HTTPException(400, 'Confirmación requerida: envía {"confirm": "FLATTEN"}')
    result = await SafetyService(db).flatten_all(body.reason, by="api")
    return {
        "ok": result.ok,
        "closed_symbols": result.closed_symbols,
        "failed_symbols": result.failed_symbols,
        "db_trades_closed": result.db_trades_closed,
        "message": result.message,
    }


@router.post("/kill")
async def kill_switch(body: KillRequest, db: AsyncSession = Depends(get_db)) -> dict:
    if body.confirm != "KILL":
        raise HTTPException(400, 'Confirmación requerida: envía {"confirm": "KILL"}')
    result = await SafetyService(db).engage_kill_switch(body.reason, flatten=True, by="api")
    return {
        "ok": result.engaged,
        "message": result.message,
        "flatten": {
            "closed_symbols": result.flatten.closed_symbols if result.flatten else [],
            "failed_symbols": result.flatten.failed_symbols if result.flatten else [],
        },
    }


@router.post("/arm")
async def arm(body: ArmRequest, db: AsyncSession = Depends(get_db)) -> dict:
    if body.confirm != "ARM":
        raise HTTPException(400, 'Confirmación requerida: envía {"confirm": "ARM"}')
    state = await SafetyService(db).arm(by="api")
    return {"ok": True, "kill_switch_engaged": state.kill_switch_engaged}
