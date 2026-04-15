"""
Signals API Routes
===================
GET  /api/signals/list   — Get recent signals (with optional ?symbol=&timeframe=&limit= filters)
WS   /api/signals/ws     — Global signal stream (all signals from all strategies)

The global WS replaces per-scanner WebSockets for signal delivery.
Frontend connects once and receives all signals + trade updates.
"""

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional

from signals.bus import SignalBus
from main.logger import get_logger

log = get_logger("signals")
router = APIRouter()


@router.get("/list")
async def list_signals(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe"),
    limit: int = Query(100, ge=1, le=500, description="Max signals to return"),
):
    """Get recent signals, optionally filtered by symbol and/or timeframe."""
    bus = SignalBus.get()
    signals = bus.get_signals(symbol=symbol, timeframe=timeframe, limit=limit)
    return {"signals": signals, "count": len(signals)}


@router.websocket("/ws")
async def global_signal_ws(websocket: WebSocket):
    """
    Global signal WebSocket — receives ALL signals from ALL strategies.
    Drives the left sidebar signal list and trade update status.

    Messages sent to client:
      {"type": "signal", "data": {...}}         — new trading signal
      {"type": "trade_update", "data": {...}}   — TP/SL hit update
    """
    await websocket.accept()
    bus = SignalBus.get()

    async def send_to_client(payload: dict):
        """Callback registered with SignalBus to forward messages."""
        try:
            await websocket.send_json(payload)
        except Exception:
            raise  # Let broadcast_to handle removal

    # Subscribe to all signals
    bus.subscribe_global(send_to_client)
    log.info("Global signal WS connected")

    try:
        # Keep connection alive — listen for ping/close
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("action") == "ping":
                    await websocket.send_json({"type": "pong"})
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error(f"Global signal WS error: {e}")
    finally:
        bus.unsubscribe_global(send_to_client)
        log.info("Global signal WS disconnected")
