"""
Chart + Backtest API Routes
============================
POST /api/chart/backtest           — Run backtest, return full result
GET  /api/chart/strategies         — List available strategies + their config schemas
GET  /api/chart/strategies/{name}  — Get single strategy config schema

WebSocket:
WS   /api/chart/ws/{symbol}        — Live MTF scanner stream

All routes require auth.
"""

import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, WebSocket, WebSocketDisconnect
from main.models import BacktestRequest, MTFStartRequest
from main.logger import get_logger
from chart.registry import auto_discover_strategies
from chart.engine import Backtester
from chart.mtf_engine import MTFLiveEngine
from data_collector.router import get_mt5

log = get_logger("engine")
router = APIRouter()

# Active scanner engines — keyed by user_id+symbol+tf combination
_active_scanners: dict[str, MTFLiveEngine] = {}


@router.get("/strategies")
async def list_strategies():
    registry = auto_discover_strategies()
    result = []
    for name, cls in registry.items():
        schema = {}
        if hasattr(cls, "config_model") and cls.config_model:
            try:
                schema = cls.config_model.model_json_schema()
            except Exception:
                pass
        result.append({
            "name": name,
            "description": getattr(cls, "description", ""),
            "schema": schema,
        })
    return {"strategies": result}


@router.get("/strategies/{name}")
async def get_strategy(name: str):
    registry = auto_discover_strategies()
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"Strategy '{name}' not found")
    cls = registry[name]
    schema = {}
    if hasattr(cls, "config_model") and cls.config_model:
        schema = cls.config_model.model_json_schema()
    return {"name": name, "description": getattr(cls, "description", ""), "schema": schema}


@router.post("/backtest")
async def run_backtest(req: BacktestRequest, request: Request):
    mt5 = get_mt5()
    if not mt5.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    from main.models import BacktestConfig
    from main.config import TIMEFRAME_MAP

    # Fetch data
    try:
        date_from = datetime.fromisoformat(req.date_from)
        date_to = datetime.fromisoformat(req.date_to)
        data = await asyncio.to_thread(
            mt5.fetch_ohlcv,
            symbol=req.symbol,
            timeframe=req.timeframe,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Data fetch failed: {e}")

    if data.empty:
        raise HTTPException(status_code=400, detail="No data returned for the specified range")

    # Get symbol info for contract specs
    sym_info = mt5.get_symbol_info(req.symbol)
    point = sym_info.get("point", 0.00001) if sym_info else 0.00001
    digits = sym_info.get("digits", 5) if sym_info else 5

    config = BacktestConfig(
        symbol=req.symbol,
        timeframe=req.timeframe,
        initial_balance=req.initial_balance,
        lot_size=req.lot_size,
        commission_per_lot=req.commission_per_lot,
        fixed_spread_points=req.fixed_spread_points,
        use_spread_from_data=req.use_spread_from_data,
        point=point,
        digits=digits,
    )

    # Get strategy
    registry = auto_discover_strategies()
    if req.strategy_name not in registry:
        raise HTTPException(status_code=404, detail=f"Strategy '{req.strategy_name}' not found")

    strategy_cls = registry[req.strategy_name]
    strategy = strategy_cls(settings=req.settings)
    # Inject point for SL/TP calculations
    strategy._point = point

    # Run backtest
    backtester = Backtester(config)
    try:
        result = await asyncio.to_thread(backtester.run, data, strategy)
    except Exception as e:
        log.error(f"Backtest failed | symbol={req.symbol} | strategy={req.strategy_name} | error={e}")
        raise HTTPException(status_code=500, detail=f"Backtest engine error: {e}")

    log.info(
        f"Backtest complete | symbol={req.symbol} | tf={req.timeframe} | "
        f"strategy={req.strategy_name} | trades={len(result.trades)} | "
        f"pnl={result.metrics.get('net_pnl', 0):.2f}"
    )

    return result


@router.websocket("/ws/{client_id}")
async def scanner_ws(websocket: WebSocket, client_id: str):
    """
    WebSocket endpoint for live MTF scanner.
    Client sends JSON: {"action": "start", "config": MTFStartRequest}
                    or {"action": "stop"}
    Server sends JSON: {"type": "signal" | "bar_update" | "error", "data": {...}}
    """
    await websocket.accept()
    engine: MTFLiveEngine = None

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "start":
                config = MTFStartRequest(**msg.get("config", {}))
                mt5 = get_mt5()
                if config.provider == "mt5" and not mt5.connected:
                    await websocket.send_json({"type": "error", "data": "MT5 not connected"})
                    continue

                provider = mt5 if config.provider == "mt5" else None  # Binance TBD

                async def broadcast(payload):
                    try:
                        await websocket.send_json(payload)
                    except Exception:
                        pass

                engine = MTFLiveEngine(
                    symbol=config.symbol,
                    timeframes=config.timeframes,
                    strategy_name=config.strategy_name,
                    settings=config.settings,
                    provider=provider,
                    broadcast_callback=broadcast,
                    start_time=config.start_time,
                )
                asyncio.create_task(engine.start())
                await websocket.send_json({"type": "started", "data": config.symbol})

            elif action == "stop":
                if engine:
                    engine.stop()
                    engine = None
                await websocket.send_json({"type": "stopped"})

    except WebSocketDisconnect:
        if engine:
            engine.stop()
    except Exception as e:
        log.error(f"WebSocket error | client={client_id} | error={e}")
        try:
            await websocket.send_json({"type": "error", "data": str(e)})
        except Exception:
            pass
