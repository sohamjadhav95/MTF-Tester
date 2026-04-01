"""
Position Tracking
==================
Helper functions for position tracking and unrealized P&L calculations.
Delegates to MT5 provider for actual position data.
"""

from data_collector.router import get_mt5
from main.logger import get_logger

log = get_logger("order")


def get_open_positions(symbol: str = None) -> list:
    """Get all open positions, optionally filtered by symbol."""
    mt5 = get_mt5()
    if not mt5.connected:
        return []
    return mt5.get_positions(symbol)


def get_position_count() -> int:
    """Get total number of open positions."""
    positions = get_open_positions()
    return len(positions)


def get_total_unrealized_pnl() -> float:
    """Calculate total unrealized P&L across all positions."""
    positions = get_open_positions()
    return sum(p.get("profit", 0) for p in positions)
