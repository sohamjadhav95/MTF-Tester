"""
Shared Pydantic Models
=======================
ALL request/response models for the entire application live here.
Import pattern: from main.models import LoginRequest, BacktestRequest, etc.
"""

from __future__ import annotations
from typing import Optional, Literal, List, Any
from pydantic import BaseModel, Field, field_validator
import re

# ── Auth (Removed) ─────────────────────────────────────────────────────

# ── MT5 ────────────────────────────────────────────────────────────────
class MT5ConnectRequest(BaseModel):
    server: str = Field(..., min_length=1)
    login: int = Field(..., gt=0)
    password: str = Field(..., min_length=1)

# ── Backtest ───────────────────────────────────────────────────────────
class BacktestRequest(BaseModel):
    symbol: str
    date_from: str
    date_to: str
    strategy_name: str
    settings: dict = {}
    initial_balance: float = Field(default=10000.0, gt=0)
    lot_size: float = Field(default=0.1, gt=0)
    commission_per_lot: float = Field(default=0.0, ge=0)
    fixed_spread_points: int = Field(default=20, ge=0)
    use_spread_from_data: bool = False
    provider: Literal["mt5", "binance"] = "mt5"

# ── MTF Scanner ────────────────────────────────────────────────────────
class MTFStartRequest(BaseModel):
    symbol: str
    name: Optional[str] = None
    strategy_name: str
    settings: dict = {}
    provider: Literal["mt5", "binance"] = "mt5"

# ── Watchlist ──────────────────────────────────────────────────────────
class WatchStartRequest(BaseModel):
    symbol: str
    timeframe: str
    provider: Literal["mt5", "binance"] = "mt5"



# ── Orders ─────────────────────────────────────────────────────────────
class AutoTradeConfig(BaseModel):
    scanner_id: str
    enabled: bool
    volume: float = Field(default=0.1, gt=0, description="Fixed lots per auto-trade")
    override_sl: Optional[float] = None
    override_tp: Optional[float] = None

class OrderRequest(BaseModel):
    symbol: str
    order_type: Literal["market", "pending"]
    direction: Literal["buy", "sell"]
    volume: float = Field(..., gt=0)
    price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    sl_enabled: bool = False
    tp_enabled: bool = False
    confirm: bool = False   # Must be True for manual orders — frontend sets this

class ClosePositionRequest(BaseModel):
    ticket: int

class RiskThresholdRequest(BaseModel):
    enabled: bool
    threshold_pct: float = Field(default=5.0, ge=0.1, le=100.0)
    auto_close: bool = False   # If True, auto-close all positions on breach

# ── Engine Models (moved from engine/models.py) ────────────────────────
class Trade(BaseModel):
    entry_time: Any
    exit_time: Any
    direction: str
    entry_price: float
    exit_price: float
    lot_size: float
    pnl_pips: float
    pnl_money: float
    spread_cost_pips: float
    bars_held: int
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    exit_reason: str = "signal"

class Position(BaseModel):
    direction: str
    entry_price: float
    entry_time: Any
    lot_size: float
    entry_bar_index: int
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None

class BacktestConfig(BaseModel):
    symbol: str
    timeframe: str
    initial_balance: float
    lot_size: float
    commission_per_lot: float
    fixed_spread_points: int
    use_spread_from_data: bool
    point: float = 0.00001
    digits: int = 5
    contract_size: float = 100000.0

class BacktestResult(BaseModel):
    config: BacktestConfig
    trades: List[Trade]
    equity_curve: List[dict]
    metrics: dict
    bar_data: List[dict]


