"""
Engine Models
=============
Dataclasses for trades, positions, and backtest configuration/results.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


def _new_trade_id() -> str:
    """Generate a short unique trade ID (first 8 chars of UUID4)."""
    return uuid.uuid4().hex[:8].upper()


@dataclass
class Trade:
    """Represents a completed (closed) trade."""

    trade_id: str  # Unique 8-char ID, shared with the Position that spawned it
    entry_time: datetime
    exit_time: datetime
    direction: str  # "BUY" or "SELL"
    entry_price: float
    exit_price: float
    lot_size: float
    pnl_pips: float
    pnl_money: float
    spread_cost_pips: float
    bars_held: int
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    exit_reason: str = "signal"  # "signal" | "sl" | "tp" | "end"

    @property
    def is_winner(self) -> bool:
        return self.pnl_pips > 0


@dataclass
class Position:
    """Tracks the current open position during backtesting."""

    trade_id: str   # Generated at open, propagated to Trade on close
    direction: str  # "BUY" or "SELL"
    entry_price: float
    entry_time: datetime
    lot_size: float
    entry_bar_index: int
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    symbol: str
    timeframe: str
    date_from: datetime
    date_to: datetime
    strategy_name: str
    strategy_settings: dict
    initial_balance: float = 10000.0
    lot_size: float = 0.1
    commission_per_lot: float = 0.0  # per side, in account currency
    use_spread_from_data: bool = True
    fixed_spread_points: int = 0  # used if use_spread_from_data is False

    # Symbol properties (filled automatically from MT5)
    point: float = 0.00001  # point size (e.g. 0.00001 for 5-digit pairs)
    digits: int = 5
    contract_size: float = 100000.0  # standard lot
    tick_value: float = 1.0  # value of 1 point movement per lot


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""

    config: BacktestConfig
    trades: list[Trade]
    equity_curve: list[dict]  # [{time, equity, balance, drawdown_pct}]
    metrics: dict  # performance metrics
    indicator_data: dict  # {indicator_name: [values]} for chart overlay
    bar_data: list[dict]  # OHLCV bars for chart display
