"""
Strategy Tester API
FastAPI application with all REST endpoints.
Serves the frontend as static files (no Node.js needed).
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import sys
import os

# Add backend directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CORS_ORIGINS
from mt5.connection import MT5Connection
from data.provider import fetch_ohlcv
from engine.backtester import Backtester
from engine.models import BacktestConfig
from strategies.loader import discover_strategies, get_strategy_list

# Path to the frontend directory (one level up from backend)
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')

# ─── App Setup ──────────────────────────────────────────────
app = FastAPI(
    title="Strategy Tester API",
    description="Trading Strategy Backtesting Engine",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Global State ────────────────────────────────────────────
mt5_conn = MT5Connection()
strategy_registry: dict = {}


# ─── Startup ─────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global strategy_registry
    strategy_registry = discover_strategies()
    print(f"Loaded {len(strategy_registry)} strategies: {list(strategy_registry.keys())}")


# ─── Request/Response Models ─────────────────────────────────
class MT5ConnectRequest(BaseModel):
    server: str
    login: int
    password: str


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str
    date_from: str  # ISO format datetime string
    date_to: str    # ISO format datetime string
    strategy: str
    settings: dict = {}
    initial_balance: float = 10000.0
    lot_size: float = 0.1
    commission_per_lot: float = 0.0
    use_spread_from_data: bool = True
    fixed_spread_points: int = 0
    time_of_day_start: Optional[str] = None
    time_of_day_end: Optional[str] = None


# ─── MT5 Endpoints ───────────────────────────────────────────
@app.post("/api/mt5/connect")
async def mt5_connect(req: MT5ConnectRequest):
    """Connect to MT5 terminal."""
    try:
        result = mt5_conn.connect(
            server=req.server,
            login=req.login,
            password=req.password,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected server error: {str(e)}")
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/api/mt5/disconnect")
async def mt5_disconnect():
    """Disconnect from MT5 terminal."""
    return mt5_conn.disconnect()


@app.get("/api/mt5/status")
async def mt5_status():
    """Check MT5 connection status."""
    return {
        "connected": mt5_conn.connected,
        "account": mt5_conn.account_info,
    }


# ─── Symbol Endpoints ────────────────────────────────────────
@app.get("/api/symbols")
async def get_symbols(group: str = "*"):
    """Get available trading symbols."""
    if not mt5_conn.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")
    symbols = mt5_conn.get_symbols(group=group)
    return {"symbols": symbols}


@app.get("/api/symbol/{name}")
async def get_symbol_info(name: str):
    """Get detailed info for a specific symbol."""
    if not mt5_conn.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")
    info = mt5_conn.get_symbol_info(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{name}' not found")
    return info


# ─── Timeframe Endpoint ──────────────────────────────────────
@app.get("/api/timeframes")
async def get_timeframes():
    """Get supported timeframes."""
    return {"timeframes": mt5_conn.get_timeframes()}


# ─── Strategy Endpoints ──────────────────────────────────────
@app.get("/api/strategies")
async def list_strategies():
    """List all available strategies."""
    global strategy_registry
    # Re-discover to pick up any new files
    strategy_registry = discover_strategies()
    strategies = get_strategy_list(strategy_registry)
    return {"strategies": strategies}


@app.get("/api/strategies/{name}/settings")
async def get_strategy_settings(name: str):
    """Get settings schema for a specific strategy."""
    global strategy_registry
    strategy_registry = discover_strategies()

    if name not in strategy_registry:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{name}' not found. Available: {list(strategy_registry.keys())}",
        )

    cls = strategy_registry[name]
    instance = cls()
    return {
        "name": instance.name,
        "description": instance.description,
        "settings": instance.settings_schema,
    }


# ─── Backtest Endpoint ───────────────────────────────────────
@app.post("/api/backtest")
async def run_backtest(req: BacktestRequest):
    """Run a backtest with the specified configuration."""
    # Validate MT5 connection
    if not mt5_conn.connected:
        raise HTTPException(status_code=400, detail="MT5 not connected")

    # Validate strategy
    global strategy_registry
    strategy_registry = discover_strategies()

    if req.strategy not in strategy_registry:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{req.strategy}' not found. Available: {list(strategy_registry.keys())}",
        )

    # Parse dates
    try:
        date_from = datetime.fromisoformat(req.date_from)
        date_to = datetime.fromisoformat(req.date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    # Fetch data from MT5
    try:
        data = fetch_ohlcv(
            symbol=req.symbol,
            timeframe=req.timeframe,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Get symbol info for accurate PnL calculation
    symbol_info = mt5_conn.get_symbol_info(req.symbol)
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
        time_of_day_start=req.time_of_day_start,
        time_of_day_end=req.time_of_day_end,
        point=symbol_info.get("point", 0.00001),
        digits=symbol_info.get("digits", 5),
        contract_size=symbol_info.get("trade_contract_size", 100000.0),
        tick_value=symbol_info.get("trade_tick_value", 1.0),
    )

    # Instantiate strategy with user settings
    strategy_cls = strategy_registry[req.strategy]
    strategy = strategy_cls(settings=req.settings)

    # Run backtest
    try:
        engine = Backtester(config)
        result = engine.run(data, strategy)
    except Exception as e:
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
            "exit_time":  _fmt_dt(t.exit_time),
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


# ─── Frontend Serving ─────────────────────────────────────────
@app.get("/")
async def serve_frontend():
    """Serve the frontend HTML page."""
    return FileResponse(os.path.join(FRONTEND_DIR, 'index.html'))


@app.get("/api/health")
async def health_check():
    return {
        "app": "Strategy Tester API",
        "version": "1.0.0",
        "mt5_connected": mt5_conn.connected,
    }


# Mount static files (CSS, JS) — MUST be last so it doesn't catch API routes
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
