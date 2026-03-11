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

class MTFStartRequest(BaseModel):
    symbol: str
    timeframes: List[str]
    strategy: str
    settings: dict = {}
    market_type: str = "forex"

@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.remove(websocket)

async def _mtf_polling_loop():
    global mtf_engine, mtf_provider_ref
    while True:
        try:
            if mtf_engine and mtf_provider_ref and getattr(mtf_provider_ref, "connected", True):
                signals, updates = await asyncio.to_thread(mtf_engine.process_latest_data)
                
                if signals:
                    for sig in signals:
                        payload = {"type": "signal", "data": sig}
                        for ws in active_websockets:
                            try:
                                await ws.send_json(payload)
                            except Exception:
                                pass
                if updates:
                    payload = {"type": "bar_updates", "data": updates}
                    for ws in active_websockets:
                        try:
                            await ws.send_json(payload)
                        except Exception:
                            pass
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"MTF polling error: {e}")
            await asyncio.sleep(2.0)

@router.post("/start")
async def start_mtf(req: MTFStartRequest):
    global mtf_engine, mtf_task, mtf_provider_ref
    
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
        mtf_engine = MTFLiveEngine(
            symbol=req.symbol,
            timeframes=req.timeframes,
            strategy_name=req.strategy,
            settings=req.settings,
            provider=provider
        )
        
        # Pre-fetch recent data and signals so UI can render immediately
        historical_candles, historical_signals = await asyncio.to_thread(mtf_engine.get_historical_context)
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    if mtf_task is None or mtf_task.done():
        mtf_task = asyncio.create_task(_mtf_polling_loop())
        
    return {
        "success": True, 
        "message": "MTF Engine started",
        "historical_candles": historical_candles,
        "historical_signals": historical_signals
    }

@router.post("/stop")
async def stop_mtf():
    global mtf_task, mtf_engine
    if mtf_task:
        mtf_task.cancel()
        mtf_task = None
    mtf_engine = None
    return {"success": True, "message": "MTF Engine stopped"}
