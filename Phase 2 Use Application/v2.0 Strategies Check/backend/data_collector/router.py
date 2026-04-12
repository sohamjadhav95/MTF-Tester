"""
Data Collector API Routes
==========================
GET  /api/data/timeframes          — List supported timeframes
GET  /api/data/symbols             — List available symbols (MT5)
GET  /api/data/symbols/{symbol}    — Symbol info
POST /api/data/mt5/connect         — Connect MT5
POST /api/data/mt5/disconnect      — Disconnect MT5
GET  /api/data/mt5/status          — MT5 connection status + account info

All routes require auth (handled by middleware).
"""

import asyncio
from fastapi import APIRouter, Request, HTTPException
from main.models import MT5ConnectRequest
from main.auth import decrypt_mt5_password
from main.db import load_mt5_credentials
from main.logger import get_logger
from data_collector.mt5 import MT5Provider

log = get_logger("api")
router = APIRouter()

# Single provider instance — acceptable for local single-user desktop app
_mt5_provider = MT5Provider()


def get_mt5() -> MT5Provider:
    """Returns the global MT5 provider. Used by chart and order modules."""
    return _mt5_provider


@router.get("/timeframes")
async def get_timeframes():
    return {"timeframes": _mt5_provider.get_timeframes()}


@router.get("/symbols")
async def get_symbols(group: str = "*"):
    if not _mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")
    symbols = await asyncio.to_thread(_mt5_provider.get_symbols, group=group)
    return {"symbols": symbols}


@router.get("/symbols/{symbol}")
async def get_symbol_info(symbol: str):
    if not _mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")
    info = await asyncio.to_thread(_mt5_provider.get_symbol_info, symbol)
    if not info:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
    return info


@router.post("/mt5/connect")
async def connect_mt5(req: MT5ConnectRequest, request: Request):
    result = await asyncio.to_thread(
        _mt5_provider.connect,
        server=req.server,
        login=req.login,
        password=req.password,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    # Save credentials if requested
    if req.save_credentials:
        from main.auth import encrypt_mt5_password
        from main.db import save_mt5_credentials
        enc = encrypt_mt5_password(req.password)
        save_mt5_credentials(request.state.user_id, req.server, req.login, enc)

    log.info(f"MT5 connected | user={request.state.user_id} | server={req.server}")
    return result


@router.post("/mt5/connect-saved")
async def connect_mt5_saved(request: Request):
    """Auto-connect using saved encrypted credentials."""
    creds = load_mt5_credentials(request.state.user_id)
    if not creds:
        raise HTTPException(status_code=404, detail="No saved credentials found")
    try:
        plain_password = decrypt_mt5_password(creds["password_enc"])
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt credentials. Re-enter password.")

    result = await asyncio.to_thread(
        _mt5_provider.connect,
        server=creds["server"],
        login=creds["login"],
        password=plain_password,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    log.info(f"MT5 auto-connected from saved creds | user={request.state.user_id}")
    return result


@router.post("/mt5/disconnect")
async def disconnect_mt5(request: Request):
    result = _mt5_provider.disconnect()
    log.info(f"MT5 disconnected | user={request.state.user_id}")
    return result


@router.get("/mt5/status")
async def mt5_status():
    return {
        "connected": _mt5_provider.connected,
        "account": _mt5_provider.account_info,
    }
