import asyncio
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.registry import auto_discover_strategies
from engine.mtf_engine import MTFLiveEngine
from app.api.routes_backtest import mt5_provider
from app.api.routes_crypto import binance_provider, ensure_connected
from app.providers.base_provider import DataProvider

router = APIRouter(prefix="/api/mtf", tags=["mtf"])

active_websockets: list[WebSocket] = []
mtf_engines: Dict[str, MTFLiveEngine] = {}
mtf_providers: Dict[str, DataProvider] = {}
mtf_task: asyncio.Task = None
main_loop: asyncio.AbstractEventLoop = None


class MTFStartRequest(BaseModel):
    asset_id: str
    symbol: str
    timeframes: List[str]
    strategy: str
    settings: dict = {}
    market_type: str = "forex"
    start_time: Optional[str] = None


class MTFStopRequest(BaseModel):
    asset_id: str


@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


async def _broadcast(payload: dict):
    for ws in list(active_websockets):
        try:
            await ws.send_json(payload)
        except Exception:
            if ws in active_websockets:
                active_websockets.remove(ws)


def broadcast_callback_for(asset_id: str):
    """Create a broadcast callback bound to a specific asset_id."""
    def callback(payload: dict):
        # Tag every payload with the asset_id
        payload["asset_id"] = asset_id
        if main_loop and main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_broadcast(payload), main_loop)
    return callback


async def _mtf_polling_loop():
    """Single polling loop that iterates over all active engines."""
    global mtf_engines, mtf_providers
    while True:
        try:
            for asset_id, engine in list(mtf_engines.items()):
                provider = mtf_providers.get(asset_id)
                if engine and provider and getattr(provider, "connected", True):
                    try:
                        signals, updates = await asyncio.to_thread(engine.process_latest_data)

                        if signals:
                            for sig in signals:
                                payload = {"type": "signal", "data": sig, "asset_id": asset_id}
                                await _broadcast(payload)
                        if updates:
                            payload = {"type": "bar_updates", "data": updates, "asset_id": asset_id}
                            await _broadcast(payload)
                    except Exception as e:
                        print(f"MTF polling error for {asset_id}: {e}")

            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"MTF polling loop error: {e}")
            await asyncio.sleep(2.0)


@router.post("/start")
async def start_mtf(req: MTFStartRequest):
    global mtf_engines, mtf_providers, mtf_task, main_loop

    main_loop = asyncio.get_event_loop()

    if req.market_type == "crypto":
        await ensure_connected()
        provider = binance_provider
    else:
        if not mt5_provider.connected:
            raise HTTPException(status_code=400, detail="MT5 not connected")
        provider = mt5_provider

    registry = auto_discover_strategies()

    if req.strategy not in registry:
        raise HTTPException(status_code=404, detail=f"Strategy {req.strategy} not found.")

    try:
        # Stop existing engine for this asset_id if any
        if req.asset_id in mtf_engines:
            mtf_engines[req.asset_id].stop()

        engine = MTFLiveEngine(
            symbol=req.symbol,
            timeframes=req.timeframes,
            strategy_name=req.strategy,
            settings=req.settings,
            provider=provider,
            broadcast_callback=broadcast_callback_for(req.asset_id),
            start_time=req.start_time,
        )

        mtf_engines[req.asset_id] = engine
        mtf_providers[req.asset_id] = provider

        # Pre-fetch recent data and signals so UI can render immediately
        historical_candles, historical_signals, historical_indicators = await asyncio.to_thread(
            engine.get_historical_context
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Ensure the polling loop is running
    if mtf_task is None or mtf_task.done():
        mtf_task = asyncio.create_task(_mtf_polling_loop())

    return {
        "success": True,
        "message": f"MTF Engine started for {req.asset_id}",
        "asset_id": req.asset_id,
        "historical_candles": historical_candles,
        "historical_signals": historical_signals,
        "historical_indicators": historical_indicators,
    }


@router.post("/stop")
async def stop_mtf(req: MTFStopRequest):
    global mtf_engines, mtf_providers, mtf_task

    if req.asset_id in mtf_engines:
        mtf_engines[req.asset_id].stop()
        del mtf_engines[req.asset_id]
    if req.asset_id in mtf_providers:
        del mtf_providers[req.asset_id]

    # If no more engines, cancel the polling loop
    if not mtf_engines and mtf_task:
        mtf_task.cancel()
        mtf_task = None

    return {"success": True, "message": f"MTF Engine stopped for {req.asset_id}"}


@router.post("/stop-all")
async def stop_all_mtf():
    global mtf_engines, mtf_providers, mtf_task

    for asset_id, engine in list(mtf_engines.items()):
        engine.stop()
    mtf_engines.clear()
    mtf_providers.clear()

    if mtf_task:
        mtf_task.cancel()
        mtf_task = None

    return {"success": True, "message": "All MTF Engines stopped"}
