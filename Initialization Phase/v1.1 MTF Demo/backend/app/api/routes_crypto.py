"""
Crypto (Binance Futures) API Routes
=====================================
GET  /api/crypto/symbols     — list all USDT-perp futures symbols
GET  /api/crypto/timeframes  — list supported timeframes
POST /api/crypto/backtest    — run a backtest using Binance data
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
from app.providers.binance_provider import BinanceProvider
from app.api.routes_backtest import progress_store  # reuse same store

router = APIRouter(prefix="/api/crypto", tags=["crypto"])

# ─── Shared Binance provider instance ────────────────────────────
binance_provider = BinanceProvider()


# ─── Startup connect (no auth needed) ────────────────────────────
async def ensure_connected():
    if not binance_provider.connected:
        binance_provider.connect()


# ─── Endpoints ───────────────────────────────────────────────────
@router.get("/symbols")
async def crypto_symbols():
    """Return all tradable USDT-perpetual Binance Futures symbols."""
    await ensure_connected()
    symbols = binance_provider.get_symbols()
    return {"symbols": symbols}


@router.get("/timeframes")
async def crypto_timeframes():
    """Return supported Binance Futures timeframes."""
    return {"timeframes": binance_provider.get_timeframes()}


# ─── Request model ───────────────────────────────────────────────
class CryptoBacktestRequest(BaseModel):
    symbol: str
    timeframe: str
    date_from: str
    date_to: str
    strategy: str
    settings: dict = {}
    initial_balance: float = 10000.0
    lot_size: float = 0.01          # smaller default for crypto
    commission_per_lot: float = 0.0
    task_id: Optional[str] = None


# ─── Backtest endpoint ───────────────────────────────────────────
@router.post("/backtest")
async def crypto_backtest(req: CryptoBacktestRequest):
    """Run a backtest on Binance Futures data."""
    await ensure_connected()

    # Validate strategy
    registry = auto_discover_strategies()
    if req.strategy not in registry:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{req.strategy}' not found. "
                   f"Available: {list(registry.keys())}",
        )

    # Parse dates
    try:
        date_from = datetime.fromisoformat(req.date_from)
        date_to   = datetime.fromisoformat(req.date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    # Fetch data
    try:
        if req.task_id:
            progress_store[req.task_id] = {
                "current": 0, "total": 100, "status": "running",
                "message": "Fetching data from Binance Futures...",
            }
        data = binance_provider.fetch_ohlcv(
            symbol=req.symbol,
            timeframe=req.timeframe,
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as e:
        if req.task_id:
            progress_store[req.task_id] = {"status": "error", "message": str(e)}
        raise HTTPException(status_code=400, detail=str(e))

    # Get symbol info for PnL calculation
    symbol_info = binance_provider.get_symbol_info(req.symbol)
    if symbol_info is None:
        raise HTTPException(
            status_code=400,
            detail=f"Could not get info for symbol '{req.symbol}'",
        )

    # Build config — Binance futures: pip_size = tick_size, no spread
    tick = symbol_info["point"]
    digits = symbol_info["digits"]

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
        use_spread_from_data=False,
        fixed_spread_points=0,
        point=tick,
        digits=digits,
        contract_size=1.0,                      # Binance: 1 contract = 1 base unit
        tick_value=tick,
    )

    strategy_cls = registry[req.strategy]
    strategy     = strategy_cls(settings=req.settings)

    def update_progress(current: int, total: int, message: str = "Processing bars..."):
        if req.task_id:
            progress_store[req.task_id] = {
                "current": current, "total": total,
                "status": "running", "message": message,
            }

    if req.task_id:
        update_progress(0, len(data), "Starting engine simulation...")

    try:
        engine = Backtester(config)
        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, engine.run, data, strategy, update_progress)

        if req.task_id:
            progress_store[req.task_id] = {
                "current": len(data), "total": len(data),
                "status": "done", "message": "Backtest complete!",
            }
    except Exception as e:
        if req.task_id:
            progress_store[req.task_id] = {"status": "error", "message": str(e)}
        raise HTTPException(status_code=500, detail=f"Backtest execution error: {e}")

    # Serialize trades
    trades_data = []
    for t in result.trades:
        def _fmt(dt):
            if isinstance(dt, datetime):
                return dt.replace(tzinfo=None).isoformat()
            return str(dt)

        trades_data.append({
            "trade_id":         t.trade_id,
            "entry_time":       _fmt(t.entry_time),
            "exit_time":        _fmt(t.exit_time),
            "direction":        t.direction,
            "entry_price":      t.entry_price,
            "exit_price":       t.exit_price,
            "lot_size":         t.lot_size,
            "pnl_pips":         t.pnl_pips,
            "pnl_money":        t.pnl_money,
            "spread_cost_pips": t.spread_cost_pips,
            "bars_held":        t.bars_held,
            "sl_price":         t.sl_price,
            "tp_price":         t.tp_price,
            "exit_reason":      t.exit_reason,
        })

    return {
        "success": True,
        "config": {
            "symbol":          config.symbol,
            "timeframe":       config.timeframe,
            "date_from":       config.date_from.isoformat(),
            "date_to":         config.date_to.isoformat(),
            "strategy":        config.strategy_name,
            "settings":        config.strategy_settings,
            "initial_balance": config.initial_balance,
            "lot_size":        config.lot_size,
        },
        "metrics":        result.metrics,
        "trades":         trades_data,
        "equity_curve":   result.equity_curve,
        "indicator_data": result.indicator_data,
        "bar_data":       result.bar_data,
        "total_bars":     len(result.bar_data),
    }
