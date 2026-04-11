"""
Watchlist API Routes
=====================
POST /api/watchlist/start     — Start live feed for symbol+timeframe, return historical bars
POST /api/watchlist/stop      — Stop a live feed by watch_id
WS   /api/watchlist/ws/{id}   — Stream live bar updates (candles only) + receive signal markers

Indicator endpoints (v1.9):
GET    /api/watchlist/indicators/catalog       — Available indicator types + schemas
POST   /api/watchlist/{watch_id}/indicators    — Add indicator to chart
DELETE /api/watchlist/{watch_id}/indicators/{ind_id} — Remove indicator
PUT    /api/watchlist/{watch_id}/indicators/{ind_id} — Update indicator settings
GET    /api/watchlist/{watch_id}/indicators    — List active indicators with data

These endpoints ONLY fetch data from the data collector and stream candles.
No strategy involvement. Charts are independent of the strategy system.
"""

import asyncio
import json
from fastapi import APIRouter, Request, HTTPException, WebSocket, WebSocketDisconnect

from main.models import WatchStartRequest, IndicatorAddRequest, IndicatorUpdateRequest
from main.logger import get_logger
from data_collector.router import get_mt5
from watchlist.engine import WatchlistEngine
from watchlist.indicators import INDICATOR_REGISTRY
from signals.bus import SignalBus

log = get_logger("watchlist")
router = APIRouter()

# Active watchlist engines — keyed by watch_id
_active_watches: dict[str, WatchlistEngine] = {}
# WebSocket connections per watch for live bar broadcasting
_watch_websockets: dict[str, list[WebSocket]] = {}
_watch_counter = 0


@router.post("/start")
async def start_watch(req: WatchStartRequest, request: Request):
    """
    Start a live chart data feed for a symbol+timeframe pair.
    Returns historical bars for immediate chart rendering.
    Live bar updates are streamed via the WebSocket endpoint.
    """
    mt5 = get_mt5()
    if req.provider == "mt5" and not mt5.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    provider = mt5 if req.provider == "mt5" else None
    if provider is None:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    global _watch_counter
    _watch_counter += 1
    watch_id = f"watch-{_watch_counter}"

    async def broadcast(payload):
        """Broadcast live bar updates to all connected WebSockets for this watch."""
        ws_list = _watch_websockets.get(watch_id, [])
        dead = []
        for ws in ws_list:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ws_list.remove(ws)

    engine = WatchlistEngine(
        watch_id=watch_id,
        symbol=req.symbol,
        timeframe=req.timeframe,
        provider=provider,
        broadcast_callback=broadcast,
    )

    # Fetch historical data synchronously
    try:
        hist_bars = await asyncio.to_thread(engine.get_historical_bars)
    except Exception as e:
        log.error(f"Watchlist historical fetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load chart data: {e}")

    # Store engine and start live polling
    _active_watches[watch_id] = engine
    _watch_websockets[watch_id] = []

    # Start live polling in background
    asyncio.create_task(engine.start_polling())

    log.info(f"Watchlist started | id={watch_id} | {req.symbol}/{req.timeframe}")

    return {
        "success": True,
        "watch_id": watch_id,
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "historical_bars": hist_bars,
    }


@router.post("/stop")
async def stop_watch(request: Request):
    """Stop a live chart feed by watch_id."""
    body = await request.json()
    watch_id = body.get("watch_id", "")

    if watch_id in _active_watches:
        _active_watches[watch_id].stop()
        del _active_watches[watch_id]
        # Close all WebSockets for this watch
        for ws in _watch_websockets.pop(watch_id, []):
            try:
                await ws.close()
            except Exception:
                pass
        # Reset counter when no watches active
        global _watch_counter
        if not _active_watches:
            _watch_counter = 0
        log.info(f"Watchlist stopped | id={watch_id}")
        return {"success": True}

    return {"success": False, "detail": "Watch not found"}


# ── Indicator Endpoints ────────────────────────────────────────────────

@router.get("/indicators/catalog")
async def get_indicator_catalog():
    """Return the full catalog of available indicators with settings schemas."""
    return {"indicators": INDICATOR_REGISTRY}


@router.post("/{watch_id}/indicators")
async def add_indicator(watch_id: str, req: IndicatorAddRequest, request: Request):
    """
    Add an indicator to a chart. Computes from the engine's cached DataFrame
    (same data source as the candle bars).
    """
    engine = _active_watches.get(watch_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Watch not found")

    # Validate indicator type
    valid_types = {r["id"] for r in INDICATOR_REGISTRY}
    if req.type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown indicator type: {req.type}. Valid: {sorted(valid_types)}"
        )

    try:
        result = await asyncio.to_thread(engine.add_indicator, req.type, req.settings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Indicator computation failed: {e}")

    # Broadcast to all connected WS clients so all chart instances update
    ws_list = _watch_websockets.get(watch_id, [])
    if ws_list:
        msg = {"type": "indicator_added", "data": result}
        dead = []
        for ws in ws_list:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ws_list.remove(ws)

    return result


@router.delete("/{watch_id}/indicators/{indicator_id}")
async def remove_indicator(watch_id: str, indicator_id: str, request: Request):
    """Remove an indicator from a chart."""
    engine = _active_watches.get(watch_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Watch not found")

    removed = engine.remove_indicator(indicator_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Indicator not found")

    # Broadcast removal to all WS clients
    ws_list = _watch_websockets.get(watch_id, [])
    if ws_list:
        msg = {"type": "indicator_removed", "data": {"indicator_id": indicator_id}}
        dead = []
        for ws in ws_list:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ws_list.remove(ws)

    return {"success": True, "indicator_id": indicator_id}


@router.put("/{watch_id}/indicators/{indicator_id}")
async def update_indicator(
    watch_id: str, indicator_id: str, req: IndicatorUpdateRequest, request: Request
):
    """Update indicator settings and recompute from the same DataFrame."""
    engine = _active_watches.get(watch_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Watch not found")

    try:
        result = await asyncio.to_thread(engine.update_indicator, indicator_id, req.settings)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Indicator update failed: {e}")

    if not result:
        raise HTTPException(status_code=404, detail="Indicator not found")

    # Broadcast to all WS clients
    ws_list = _watch_websockets.get(watch_id, [])
    if ws_list:
        msg = {"type": "indicator_updated", "data": result}
        dead = []
        for ws in ws_list:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ws_list.remove(ws)

    return result


@router.get("/{watch_id}/indicators")
async def list_indicators(watch_id: str, request: Request):
    """
    List all active indicators with their full computed data.
    Used when a new chart instance needs to sync (e.g., after page refresh).
    """
    engine = _active_watches.get(watch_id)
    if not engine:
        raise HTTPException(status_code=404, detail="Watch not found")

    try:
        all_data = await asyncio.to_thread(engine.get_all_indicator_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compute indicators: {e}")

    return {
        "watch_id": watch_id,
        "indicators": all_data,
        "active": engine.get_active_indicators(),
    }


# ── WebSocket ──────────────────────────────────────────────────────────

@router.websocket("/ws/{watch_id}")
async def watch_ws(websocket: WebSocket, watch_id: str):
    """
    WebSocket for live chart candle updates.
    Also subscribes to SignalBus for the matching symbol+timeframe
    so signal markers are pushed to the chart.

    Messages sent to client:
      {"type": "bar_updates",       "data": {"bars": [...], "indicators": {...}}}
      {"type": "signal",            "data": {...}}   — signal marker from SignalBus
      {"type": "trade_update",      "data": {...}}   — TP/SL hit update
      {"type": "indicator_added",   "data": {...}}   — indicator added via REST
      {"type": "indicator_removed", "data": {...}}   — indicator removed via REST
      {"type": "indicator_updated", "data": {...}}   — indicator settings changed
      {"type": "indicator_sync",    "data": {...}}   — full indicator state on connect
    """
    await websocket.accept()

    # Register this WS connection for chart bar updates
    if watch_id not in _watch_websockets:
        _watch_websockets[watch_id] = []
    _watch_websockets[watch_id].append(websocket)

    # Get engine info for SignalBus subscription
    engine = _active_watches.get(watch_id)
    symbol = engine.symbol if engine else None
    timeframe = engine.timeframe if engine else None
    bus = SignalBus.get()

    async def on_signal(payload: dict):
        """Forward signal from SignalBus to chart WebSocket."""
        try:
            await websocket.send_json(payload)
        except Exception:
            raise

    # Subscribe to signals matching this chart's symbol+timeframe
    if symbol and timeframe:
        bus.subscribe_chart(symbol, timeframe, on_signal)

    # Send current indicator state to this new WS client
    if engine and engine._indicators:
        try:
            all_data = engine.get_all_indicator_data()
            if all_data:
                await websocket.send_json({
                    "type": "indicator_sync",
                    "data": {
                        "indicators": all_data,
                        "active": engine.get_active_indicators(),
                    },
                })
        except Exception as e:
            log.error(f"Indicator sync failed | watch={watch_id}: {e}")

    log.info(f"Watchlist WS connected | watch={watch_id} | {symbol}/{timeframe}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("action") == "stop":
                    break
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error(f"Watchlist WS error | watch={watch_id}: {e}")
    finally:
        # Unsubscribe from SignalBus
        if symbol and timeframe:
            bus.unsubscribe_chart(symbol, timeframe, on_signal)

        # Unregister this WS
        ws_list = _watch_websockets.get(watch_id, [])
        if websocket in ws_list:
            ws_list.remove(websocket)

        log.info(f"Watchlist WS disconnected | watch={watch_id}")

        # If no more WS clients, auto-stop the orphaned engine
        remaining = _watch_websockets.get(watch_id, [])
        if not remaining and watch_id in _active_watches:
            log.info(f"No WS clients left — auto-stopping watchlist {watch_id}")
            _active_watches[watch_id].stop()
            del _active_watches[watch_id]
            _watch_websockets.pop(watch_id, None)
            global _watch_counter
            if not _active_watches:
                _watch_counter = 0
