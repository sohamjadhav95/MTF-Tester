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
from fastapi import APIRouter, HTTPException
from main.models import OrderRequest, ClosePositionRequest, RiskThresholdRequest, AutoTradeConfig
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
async def place_order_route(req: OrderRequest):
    from order.pipeline import place_order, OrderContext
    ctx = OrderContext(source="manual")
    try:
        result = await place_order(req, ctx, _risk_guard)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Order failed"))
    return result


@router.post("/close/{ticket}")
async def close_position(ticket: int):
    mt5 = get_mt5()

    # Fetch position details BEFORE closing for complete audit
    positions = await asyncio.to_thread(mt5.get_positions)
    pos_info = next((p for p in positions if p["ticket"] == ticket), None)
    pos_symbol = pos_info["symbol"] if pos_info else None
    pos_direction = pos_info["type"] if pos_info else None  # "buy" or "sell"
    pos_volume = pos_info["volume"] if pos_info else None

    result = await asyncio.to_thread(mt5.close_position, ticket)

    write_order_audit(
        action="close" if result["success"] else "close_failed",
        symbol=pos_symbol,
        direction=pos_direction,
        volume=pos_volume,
        result=result,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    log.info(f"Position closed | user=local | ticket={ticket} | {pos_symbol}")
    return result


@router.post("/close-all")
async def close_all():
    mt5 = get_mt5()

    result = await asyncio.to_thread(mt5.close_all_positions)

    write_order_audit(
        action="close_all", result=result,
    )

    log.info(f"Close all | user=local | closed={result.get('closed_count')}")
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
async def set_risk(req: RiskThresholdRequest):
    _risk_guard.configure(
        enabled=req.enabled,
        threshold_pct=req.threshold_pct,
        auto_close=req.auto_close,
    )
    log.info(
        f"Risk threshold set | user=local | "
        f"enabled={req.enabled} | threshold={req.threshold_pct}% | auto_close={req.auto_close}"
    )
    return {"message": "Risk threshold updated", "state": _risk_guard.get_state()}


@router.get("/risk")
async def get_risk():
    return _risk_guard.get_state()


@router.get("/history")
async def get_history(limit: int = 100):
    """Return order audit log."""
    history = get_order_history(limit)
    return {"history": history}


@router.post("/auto/configure")
async def configure_auto(req: AutoTradeConfig):
    """Enable or disable auto-trade for a scanner, with per-trade config."""
    from order.auto_executor import AutoExecutor
    ae = AutoExecutor.get()

    # Validate scanner exists
    from chart.router import _active_scanners
    if req.scanner_id not in _active_scanners:
        raise HTTPException(status_code=404, detail=f"Scanner {req.scanner_id} not found")

    if req.enabled:
        ae.enable(req.scanner_id, volume=req.volume,
                  override_sl=req.override_sl, override_tp=req.override_tp)
    else:
        ae.disable(req.scanner_id)
    return {"success": True, "config": ae.get_all_configs().get(req.scanner_id)}


@router.get("/auto/status")
async def auto_status():
    """Return current auto-trade state for all scanners."""
    from order.auto_executor import AutoExecutor
    from main.config import AUTO_EXEC_KILL_SWITCH
    ae = AutoExecutor.get()
    return {"configs": ae.get_all_configs(), "kill_switch": AUTO_EXEC_KILL_SWITCH}


@router.get("/auto/history")
async def auto_history(limit: int = 50):
    """
    Return recent auto-trades by querying order_audit where result_json.source='auto'.
    Useful for debugging and showing auto-trade history in the UI.
    """
    from main.db import get_order_history
    rows = get_order_history(limit=500)  # pull extra, filter in Python
    auto_rows = []
    import json as _json
    for r in rows:
        try:
            result = _json.loads(r["result_json"]) if r["result_json"] else {}
            if result.get("source") == "auto":
                auto_rows.append({**r, "scanner_id": result.get("scanner_id"),
                                  "signal_id": result.get("signal_id")})
        except Exception:
            continue
        if len(auto_rows) >= limit:
            break
    return {"auto_trades": auto_rows}
