"""
Trading API Routes
==================
POST /api/trading/order       — Place a market or pending order
GET  /api/trading/positions   — Get all open positions
POST /api/trading/close/{ticket} — Close a specific position
POST /api/trading/close-all   — Close all open positions
GET  /api/trading/account     — Get account balance/equity
POST /api/trading/risk-threshold — Set risk threshold
GET  /api/trading/risk-status    — Get current risk threshold status
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes_backtest import mt5_provider
from app.api.routes_mtf import _broadcast

router = APIRouter(prefix="/api/trading", tags=["trading"])

# ─── Risk Threshold State ───────────────────────────────────────
risk_state = {
    "enabled": False,
    "threshold_pct": 5.0,       # default 5% risk threshold
    "initial_balance": None,     # set when threshold is enabled
    "breached": False,
}
_risk_monitor_task: asyncio.Task = None


# ─── Request Models ─────────────────────────────────────────────
class OrderRequest(BaseModel):
    symbol: str
    order_type: str         # "market" | "pending"
    direction: str          # "buy" | "sell"
    volume: float
    price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    sl_enabled: bool = False
    tp_enabled: bool = False


class RiskThresholdRequest(BaseModel):
    enabled: bool
    threshold_pct: float = 5.0


# ─── Order Endpoints ───────────────────────────────────────────
@router.post("/order")
async def place_order(req: OrderRequest):
    """Place a market or pending order."""
    if not mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    result = await asyncio.to_thread(
        mt5_provider.send_order,
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

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


# ─── Positions Endpoints ────────────────────────────────────────
@router.get("/positions")
async def get_positions(symbol: Optional[str] = None):
    """Get all open positions."""
    if not mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    positions = await asyncio.to_thread(mt5_provider.get_positions, symbol)
    return {"positions": positions}


@router.post("/close/{ticket}")
async def close_position(ticket: int):
    """Close a specific position by ticket."""
    if not mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    result = await asyncio.to_thread(mt5_provider.close_position, ticket)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/close-all")
async def close_all_positions(symbol: Optional[str] = None):
    """Close all open positions."""
    if not mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    result = await asyncio.to_thread(mt5_provider.close_all_positions, symbol)
    return result


# ─── Account Endpoint ──────────────────────────────────────────
@router.get("/account")
async def get_account():
    """Get current account balance/equity."""
    if not mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    info = await asyncio.to_thread(mt5_provider.get_account_equity)
    if info is None:
        raise HTTPException(status_code=500, detail="Failed to get account info")

    return info


# ─── Risk Threshold Endpoints ──────────────────────────────────
@router.post("/risk-threshold")
async def set_risk_threshold(req: RiskThresholdRequest):
    """Set or disable the risk threshold."""
    global _risk_monitor_task

    risk_state["enabled"] = req.enabled
    risk_state["threshold_pct"] = req.threshold_pct
    risk_state["breached"] = False

    if req.enabled:
        # Capture initial balance snapshot
        info = await asyncio.to_thread(mt5_provider.get_account_equity)
        if info:
            risk_state["initial_balance"] = info["balance"]
        else:
            risk_state["initial_balance"] = None

        # Start monitor if not running
        if _risk_monitor_task is None or _risk_monitor_task.done():
            _risk_monitor_task = asyncio.create_task(_risk_monitor_loop())
    else:
        # Stop monitor
        if _risk_monitor_task and not _risk_monitor_task.done():
            _risk_monitor_task.cancel()
            _risk_monitor_task = None
        risk_state["initial_balance"] = None

    return {"success": True, **risk_state}


@router.get("/risk-status")
async def get_risk_status():
    """Get current risk threshold status."""
    info = None
    if mt5_provider.connected:
        info = await asyncio.to_thread(mt5_provider.get_account_equity)

    drawdown_pct = 0.0
    if info and risk_state["initial_balance"] and risk_state["initial_balance"] > 0:
        drawdown_pct = ((risk_state["initial_balance"] - info["equity"]) / risk_state["initial_balance"]) * 100
        drawdown_pct = max(0, drawdown_pct)

    return {
        **risk_state,
        "current_equity": info["equity"] if info else None,
        "current_balance": info["balance"] if info else None,
        "drawdown_pct": round(drawdown_pct, 2),
    }


# ─── Background Risk Monitor ───────────────────────────────────
async def _risk_monitor_loop():
    """Polls account equity every 2s and auto-closes all positions if threshold is breached."""
    while True:
        try:
            if not risk_state["enabled"] or not mt5_provider.connected:
                await asyncio.sleep(2.0)
                continue

            info = await asyncio.to_thread(mt5_provider.get_account_equity)
            if info is None or risk_state["initial_balance"] is None:
                await asyncio.sleep(2.0)
                continue

            initial = risk_state["initial_balance"]
            equity = info["equity"]
            threshold = risk_state["threshold_pct"]

            # Calculate drawdown percentage
            if initial > 0:
                drawdown_pct = ((initial - equity) / initial) * 100
            else:
                drawdown_pct = 0

            # Check threshold breach
            if drawdown_pct >= threshold and not risk_state["breached"]:
                risk_state["breached"] = True
                print(f"[RISK] Threshold breached! Drawdown: {drawdown_pct:.2f}% >= {threshold}%. Closing all positions.")

                # Force close all positions
                close_result = await asyncio.to_thread(mt5_provider.close_all_positions)

                # Broadcast alert via WebSocket
                await _broadcast({
                    "type": "risk_alert",
                    "data": {
                        "message": f"Risk threshold breached! Drawdown: {drawdown_pct:.2f}%",
                        "drawdown_pct": round(drawdown_pct, 2),
                        "threshold_pct": threshold,
                        "positions_closed": close_result.get("closed_count", 0),
                        "initial_balance": initial,
                        "current_equity": equity,
                    }
                })

                # Disable monitoring after breach
                risk_state["enabled"] = False
                break

            await asyncio.sleep(2.0)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[RISK] Monitor error: {e}")
            await asyncio.sleep(3.0)
