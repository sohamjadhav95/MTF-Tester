"""
Backtest & MT5 API Routes
=========================
POST /api/backtest  — run a backtest
POST /api/mt5/*     — MT5 connection management
GET  /api/symbols   — symbol listing
GET  /api/timeframes — timeframe listing
"""

from __future__ import annotations

from datetime import datetime
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.registry import auto_discover_strategies
from app.core.models import BacktestConfig
from app.core.engine import Backtester
from app.providers.mt5_provider import MT5Provider

router = APIRouter(prefix="/api", tags=["backtest"])

# ─── Shared provider instance ───────────────────────────────────
mt5_provider = MT5Provider()

# ─── Progress Store ─────────────────────────────────────────────
# In-memory dict for tracking task progress: task_id -> {current, total, message, status}
progress_store = {}

@router.get("/progress/{task_id}")
async def get_progress(task_id: str):
    """Poll progress of a running background task."""
    return progress_store.get(task_id, {"status": "not_found"})

# ─── Request Models ─────────────────────────────────────────────
class MT5ConnectRequest(BaseModel):
    server: str
    login: int
    password: str


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str
    date_from: str  # ISO format datetime string
    date_to: str  # ISO format datetime string
    strategy: str
    settings: dict = {}
    initial_balance: float = 10000.0
    lot_size: float = 0.1
    commission_per_lot: float = 0.0
    use_spread_from_data: bool = True
    fixed_spread_points: int = 0
    task_id: Optional[str] = None


# ─── MT5 Endpoints ──────────────────────────────────────────────
@router.post("/mt5/connect")
async def mt5_connect(req: MT5ConnectRequest):
    """Connect to MT5 terminal."""
    try:
        result = mt5_provider.connect(
            server=req.server,
            login=req.login,
            password=req.password,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected server error: {str(e)}")
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/mt5/disconnect")
async def mt5_disconnect():
    """Disconnect from MT5 terminal."""
    return mt5_provider.disconnect()


@router.get("/mt5/status")
async def mt5_status():
    """Check MT5 connection status."""
    return {
        "connected": mt5_provider.connected,
        "account": mt5_provider.account_info,
    }


# ─── Symbol Endpoints ──────────────────────────────────────────
@router.get("/symbols")
async def get_symbols(group: str = "*"):
    """Get available trading symbols."""
    if not mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")
    symbols = mt5_provider.get_symbols(group=group)
    return {"symbols": symbols}


@router.get("/symbol/{name}")
async def get_symbol_info(name: str):
    """Get detailed info for a specific symbol."""
    if not mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")
    info = mt5_provider.get_symbol_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{name}' not found")
    return info


# ─── Timeframe Endpoint ────────────────────────────────────────
@router.get("/timeframes")
async def get_timeframes():
    """Get supported timeframes."""
    return {"timeframes": mt5_provider.get_timeframes()}


# ─── Backtest Endpoint ─────────────────────────────────────────
@router.post("/backtest")
async def run_backtest(req: BacktestRequest):
    """Run a backtest with the specified configuration."""
    # Validate MT5 connection
    if not mt5_provider.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    # Validate strategy
    registry = auto_discover_strategies()
    if req.strategy not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{req.strategy}' not found. Available: {list(registry.keys())}",
        )

    # Parse dates
    try:
        date_from = datetime.fromisoformat(req.date_from)
        date_to = datetime.fromisoformat(req.date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    # Fetch data from provider
    try:
        if req.task_id:
            progress_store[req.task_id] = {"current": 0, "total": 100, "status": "running", "message": "Fetching data from MT5..."}
        
        data = mt5_provider.fetch_ohlcv(
            symbol=req.symbol,
            timeframe=req.timeframe,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as e:
        if req.task_id:
            progress_store[req.task_id] = {"status": "error", "message": str(e)}
        raise HTTPException(status_code=400, detail=str(e))

    # Get symbol info for accurate PnL calculation
    symbol_info = mt5_provider.get_symbol_info(req.symbol)
    if symbol_info is None:
        raise HTTPException(
            status_code=400,
            detail=f"Could not get info for symbol '{req.symbol}'",
        )

    # Build backtest config
    config = BacktestConfig(
        symbol=req.symbol,
        timeframe=req.timeframe,
        date_from=date_from,
        date_to=date_to,
        strategy_name=req.strategy,
        strategy_settings=req.settings,
        initial_balance=req.initial_balance,
        lot_size=req.lot_size,
        commission_per_lot=req.commission_per_lot,
        use_spread_from_data=req.use_spread_from_data,
        fixed_spread_points=req.fixed_spread_points,
        point=symbol_info.get("point", 0.00001),
        digits=symbol_info.get("digits", 5),
        contract_size=symbol_info.get("trade_contract_size", 100000.0),
        tick_value=symbol_info.get("trade_tick_value", 1.0),
    )

    # Instantiate strategy with validated Pydantic config
    strategy_cls = registry[req.strategy]
    strategy = strategy_cls(settings=req.settings)
    
    def update_progress(current: int, total: int, message: str = "Processing bars..."):
        if req.task_id:
            progress_store[req.task_id] = {"current": current, "total": total, "status": "running", "message": message}

    if req.task_id:
        update_progress(0, len(data), "Starting engine simulation...")

    # Run backtest
    try:
        engine = Backtester(config)
        loop = asyncio.get_running_loop()
        # Offload CPU-bound engine.run to threadpool so event loop can serve progress requests
        result = await loop.run_in_executor(None, engine.run, data, strategy, update_progress)
        
        if req.task_id:
            progress_store[req.task_id] = {"current": len(data), "total": len(data), "status": "done", "message": "Backtest complete!"}
    except Exception as e:
        if req.task_id:
            progress_store[req.task_id] = {"status": "error", "message": str(e)}
        raise HTTPException(
            status_code=500,
            detail=f"Backtest execution error: {str(e)}",
        )

    # Serialize trades
    trades_data = []
    for t in result.trades:
        def _fmt_dt(dt):
            if isinstance(dt, datetime):
                return dt.replace(tzinfo=None).isoformat()
            return str(dt)

        trades_data.append({
            "entry_time": _fmt_dt(t.entry_time),
            "exit_time": _fmt_dt(t.exit_time),
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "lot_size": t.lot_size,
            "pnl_pips": t.pnl_pips,
            "pnl_money": t.pnl_money,
            "spread_cost_pips": t.spread_cost_pips,
            "bars_held": t.bars_held,
            "sl_price": t.sl_price,
            "tp_price": t.tp_price,
            "exit_reason": t.exit_reason,
        })

    return {
        "success": True,
        "config": {
            "symbol": config.symbol,
            "timeframe": config.timeframe,
            "date_from": config.date_from.isoformat(),
            "date_to": config.date_to.isoformat(),
            "strategy": config.strategy_name,
            "settings": config.strategy_settings,
            "initial_balance": config.initial_balance,
            "lot_size": config.lot_size,
        },
        "metrics": result.metrics,
        "trades": trades_data,
        "equity_curve": result.equity_curve,
        "indicator_data": result.indicator_data,
        "bar_data": result.bar_data,
        "total_bars": len(result.bar_data),
    }
