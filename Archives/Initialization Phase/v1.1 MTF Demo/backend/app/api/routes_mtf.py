import asyncio
from typing import List, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.registry import auto_discover_strategies
from engine.mtf_engine import MTFLiveEngine
from app.api.routes_backtest import mt5_provider
from app.api.routes_crypto import binance_provider, ensure_connected
from app.providers.base_provider import DataProvider

router = APIRouter(prefix="/api/mtf", tags=["mtf"])

active_websockets: list[WebSocket] = []
mtf_task: asyncio.Task = None
mtf_engine: MTFLiveEngine = None
mtf_provider_ref: DataProvider = None
main_loop: asyncio.AbstractEventLoop = None

class MTFStartRequest(BaseModel):
    symbol: str
    timeframes: List[str]
    strategy: str
    settings: dict = {}
    market_type: str = "forex"
    start_time: Optional[str] = None

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

def broadcast_callback(payload: dict):
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast(payload), main_loop)

async def _mtf_polling_loop():
    global mtf_engine, mtf_provider_ref
    while True:
        try:
            if mtf_engine and mtf_provider_ref and getattr(mtf_provider_ref, "connected", True):
                signals, updates = await asyncio.to_thread(mtf_engine.process_latest_data)
                
                if signals:
                    for sig in signals:
                        payload = {"type": "signal", "data": sig}
                        await _broadcast(payload)
                if updates:
                    payload = {"type": "bar_updates", "data": updates}
                    await _broadcast(payload)
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"MTF polling error: {e}")
            await asyncio.sleep(2.0)

@router.post("/start")
async def start_mtf(req: MTFStartRequest):
    global mtf_engine, mtf_task, mtf_provider_ref, main_loop
    
    main_loop = asyncio.get_event_loop()
    
    if req.market_type == "crypto":
        await ensure_connected()
        provider = binance_provider
    else:
        if not mt5_provider.connected:
            raise HTTPException(status_code=400, detail="MT5 not connected")
        provider = mt5_provider
        
    mtf_provider_ref = provider
    registry = auto_discover_strategies()
    
    if req.strategy not in registry:
        raise HTTPException(status_code=404, detail=f"Strategy {req.strategy} not found.")
        
    try:
        if mtf_engine:
            mtf_engine.stop()
            
        mtf_engine = MTFLiveEngine(
            symbol=req.symbol,
            timeframes=req.timeframes,
            strategy_name=req.strategy,
            settings=req.settings,
            provider=provider,
            broadcast_callback=broadcast_callback,
            start_time=req.start_time
        )
        
        # Pre-fetch recent data and signals so UI can render immediately
        historical_candles, historical_signals, historical_indicators = await asyncio.to_thread(mtf_engine.get_historical_context)
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    if mtf_task is None or mtf_task.done():
        mtf_task = asyncio.create_task(_mtf_polling_loop())
        
    return {
        "success": True, 
        "message": "MTF Engine started",
        "historical_candles": historical_candles,
        "historical_signals": historical_signals,
        "historical_indicators": historical_indicators
    }

@router.post("/stop")
async def stop_mtf():
    global mtf_task, mtf_engine
    if mtf_task:
        mtf_task.cancel()
        mtf_task = None
    if mtf_engine:
        mtf_engine.stop()
    mtf_engine = None
    return {"success": True, "message": "MTF Engine stopped"}
