"""
Order API Routes
================
ALL order operations go through this module ONLY.
No other module sends orders.

POST /api/order/place              — Place market or pending order
POST /api/order/close/{ticket}     — Close specific position
POST /api/order/close-all          — Close all positions
GET  /api/order/positions          — Get open positions
GET  /api/order/account            — Get account equity/balance
POST /api/order/risk               — Set risk threshold
GET  /api/order/risk               — Get risk status
GET  /api/order/history            — Get order audit log for this user

All routes require auth. Every order attempt is written to order_audit.
"""

import asyncio
from fastapi import APIRouter, Request, HTTPException
from main.models import OrderRequest, ClosePositionRequest, RiskThresholdRequest
from main.db import write_order_audit, get_order_history
from main.logger import get_logger
from order.validator import validate_order
from order.risk import RiskGuard
from data_collector.router import get_mt5

log = get_logger("order")
router = APIRouter()

# One risk guard instance (Phase 1: per-app, not per-user)
_risk_guard = RiskGuard()


@router.post("/place")
async def place_order(req: OrderRequest, request: Request):
    mt5 = get_mt5()
    user_id = request.state.user_id
    ip = request.client.host if request.client else "unknown"

    log.info(
        f"Order requested | user={user_id} | {req.direction.upper()} {req.volume} "
        f"{req.symbol} {req.order_type}"
    )

    # Validate BEFORE any MT5 call
    try:
        validate_order(req, mt5, _risk_guard.get_state())
    except ValueError as e:
        log.warning(f"Order rejected | user={user_id} | reason={e}")
        write_order_audit(
            user_id=user_id, action="rejected",
            symbol=req.symbol, direction=req.direction, volume=req.volume,
            result={"error": str(e)}, ip_address=ip,
            session_id=request.state.session_id,
        )
        raise HTTPException(status_code=400, detail=str(e))

    # Send order
    result = await asyncio.to_thread(
        mt5.send_order,
        symbol=req.symbol,
        order_type=req.order_type,
        direction=req.direction,
        volume=req.volume,
        price=req.price,
        sl=req.sl,
        tp=req.tp,
        sl_enabled=req.sl_enabled,
        tp_enabled=req.tp_enabled,
    )

    # ALWAYS audit — success or failure
    write_order_audit(
        user_id=user_id,
        action="place" if result["success"] else "failed",
        symbol=req.symbol, direction=req.direction,
        volume=req.volume, price=result.get("price"),
        sl=req.sl, tp=req.tp,
        result=result, ip_address=ip,
        session_id=request.state.session_id,
    )

    if not result["success"]:
        log.error(f"Order failed | user={user_id} | error={result.get('error')}")
        raise HTTPException(status_code=400, detail=result["error"])

    log.info(
        f"Order placed | user={user_id} | ticket={result.get('ticket')} | "
        f"{req.direction.upper()} {req.volume} {req.symbol} @ {result.get('price')}"
    )
    return result


@router.post("/close/{ticket}")
async def close_position(ticket: int, request: Request):
    mt5 = get_mt5()
    user_id = request.state.user_id
    ip = request.client.host if request.client else "unknown"

    # Fetch position details BEFORE closing for complete audit
    positions = await asyncio.to_thread(mt5.get_positions)
    pos_info = next((p for p in positions if p["ticket"] == ticket), None)
    pos_symbol = pos_info["symbol"] if pos_info else None
    pos_direction = pos_info["type"] if pos_info else None  # "buy" or "sell"
    pos_volume = pos_info["volume"] if pos_info else None

    result = await asyncio.to_thread(mt5.close_position, ticket)

    write_order_audit(
        user_id=user_id,
        action="close" if result["success"] else "close_failed",
        symbol=pos_symbol,
        direction=pos_direction,
        volume=pos_volume,
        result=result, ip_address=ip,
        session_id=request.state.session_id,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    log.info(f"Position closed | user={user_id} | ticket={ticket} | {pos_symbol}")
    return result


@router.post("/close-all")
async def close_all(request: Request):
    mt5 = get_mt5()
    user_id = request.state.user_id

    result = await asyncio.to_thread(mt5.close_all_positions)

    write_order_audit(
        user_id=user_id, action="close_all", result=result,
        ip_address=request.client.host if request.client else None,
        session_id=request.state.session_id,
    )

    log.info(f"Close all | user={user_id} | closed={result.get('closed_count')}")
    return result


@router.get("/positions")
async def get_positions(symbol: str = None):
    mt5 = get_mt5()
    positions = await asyncio.to_thread(mt5.get_positions, symbol)
    return {"positions": positions}


@router.get("/account")
async def get_account():
    mt5 = get_mt5()
    equity = await asyncio.to_thread(mt5.get_account_equity)
    if not equity:
        raise HTTPException(status_code=400, detail="MT5 not connected or account info unavailable")
    return equity


@router.post("/risk")
async def set_risk(req: RiskThresholdRequest, request: Request):
    _risk_guard.configure(
        enabled=req.enabled,
        threshold_pct=req.threshold_pct,
        auto_close=req.auto_close,
    )
    log.info(
        f"Risk threshold set | user={request.state.user_id} | "
        f"enabled={req.enabled} | threshold={req.threshold_pct}% | auto_close={req.auto_close}"
    )
    return {"message": "Risk threshold updated", "state": _risk_guard.get_state()}


@router.get("/risk")
async def get_risk():
    return _risk_guard.get_state()


@router.get("/history")
async def get_history(request: Request, limit: int = 100):
    """Return order audit log for current user."""
    history = get_order_history(request.state.user_id, limit)
    return {"history": history}
