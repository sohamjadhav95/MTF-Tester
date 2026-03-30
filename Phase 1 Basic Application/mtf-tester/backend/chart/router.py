"""
Chart + Backtest API Routes
============================
POST /api/chart/backtest           — Run backtest, return full result
GET  /api/chart/strategies         — List available strategies + their config schemas
GET  /api/chart/strategies/{name}  — Get single strategy config schema
POST /api/chart/scanner/start      — Start MTF scanner, return historical data (REST)
POST /api/chart/scanner/stop       — Stop a running scanner

WebSocket:
WS   /api/chart/ws/{client_id}     — Live bar updates stream (after scanner started via REST)

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

# Active scanner engines — keyed by scanner_id
_active_scanners: dict[str, MTFLiveEngine] = {}
# WebSocket connections per scanner for live broadcasting
_scanner_websockets: dict[str, list[WebSocket]] = {}
_scanner_counter = 0


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


# ═══ REST-based Scanner Start/Stop (returns historical data) ═══════════

@router.post("/scanner/start")
async def start_scanner(req: MTFStartRequest, request: Request):
    """
    Start a new MTF scanner. Returns historical candles, signals, and indicators
    so the frontend can render charts immediately. Live bar updates are streamed
    via the WebSocket endpoint.
    """
    mt5 = get_mt5()
    if req.provider == "mt5" and not mt5.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    provider = mt5 if req.provider == "mt5" else None

    global _scanner_counter
    _scanner_counter += 1
    scanner_id = f"scan-{_scanner_counter}"

    async def broadcast(payload):
        """Broadcast live updates to all connected WebSockets for this scanner."""
        ws_list = _scanner_websockets.get(scanner_id, [])
        dead = []
        for ws in ws_list:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ws_list.remove(ws)

    engine = MTFLiveEngine(
        symbol=req.symbol,
        timeframes=req.timeframes,
        strategy_name=req.strategy_name,
        settings=req.settings,
        provider=provider,
        broadcast_callback=broadcast,
        start_time=req.start_time,
    )

    # Fetch historical data synchronously (before starting live loop)
    try:
        hist_candles, hist_signals, hist_indicators = await asyncio.to_thread(
            engine.get_historical_context
        )
    except Exception as e:
        log.error(f"Historical fetch failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load historical data: {e}")

    # Store engine and start live polling
    _active_scanners[scanner_id] = engine
    _scanner_websockets[scanner_id] = []

    # Start live updates (polling or WS streams) in background
    asyncio.create_task(engine.start_live_only())

    log.info(f"Scanner started | id={scanner_id} | symbol={req.symbol} | tfs={req.timeframes}")

    return {
        "success": True,
        "scanner_id": scanner_id,
        "historical_candles": hist_candles,
        "historical_signals": hist_signals,
        "historical_indicators": hist_indicators,
    }


@router.post("/scanner/stop")
async def stop_scanner(request: Request):
    """Stop a running scanner by scanner_id."""
    body = await request.json()
    scanner_id = body.get("scanner_id", "")

    if scanner_id in _active_scanners:
        _active_scanners[scanner_id].stop()
        del _active_scanners[scanner_id]
        # Close all WebSockets for this scanner
        for ws in _scanner_websockets.pop(scanner_id, []):
            try:
                await ws.close()
            except Exception:
                pass
        log.info(f"Scanner stopped | id={scanner_id}")
        return {"success": True}

    return {"success": False, "detail": "Scanner not found"}


# ═══ WebSocket for Live Updates Only ═══════════════════════════════════

@router.websocket("/ws/{scanner_id}")
async def scanner_ws(websocket: WebSocket, scanner_id: str):
    """
    WebSocket for live bar updates and signals.
    Client connects AFTER calling /scanner/start which returns historical data.
    This WS only receives live updates — no historical replay.
    """
    await websocket.accept()

    # Register this WS connection for the scanner
    if scanner_id not in _scanner_websockets:
        _scanner_websockets[scanner_id] = []
    _scanner_websockets[scanner_id].append(websocket)

    log.info(f"WS connected | scanner={scanner_id}")

    try:
        while True:
            # Keep connection alive; listen for stop/ping messages
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
        log.error(f"WS error | scanner={scanner_id} | error={e}")
    finally:
        # Unregister
        ws_list = _scanner_websockets.get(scanner_id, [])
        if websocket in ws_list:
            ws_list.remove(websocket)
        log.info(f"WS disconnected | scanner={scanner_id}")
