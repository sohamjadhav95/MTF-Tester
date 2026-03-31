"""
Order Manager
==============
Order placement, modification, and cancellation logic.
This module contains the business logic; the router.py handles HTTP concerns.
All actual MT5 order_send calls go through the MT5 provider.
"""

from main.logger import get_logger
from data_collector.router import get_mt5

log = get_logger("order")


def place_order(symbol, order_type, direction, volume, price=None,
                sl=None, tp=None, sl_enabled=False, tp_enabled=False):
    """
    Place an order through MT5 provider.
    Returns result dict from MT5Provider.send_order().
    """
    mt5 = get_mt5()
    return mt5.send_order(
        symbol=symbol,
        order_type=order_type,
        direction=direction,
        volume=volume,
        price=price,
        sl=sl,
        tp=tp,
        sl_enabled=sl_enabled,
        tp_enabled=tp_enabled,
    )


def close_position(ticket: int):
    """Close a specific position by ticket."""
    mt5 = get_mt5()
    return mt5.close_position(ticket)


def close_all_positions(symbol: str = None):
    """Close all open positions."""
    mt5 = get_mt5()
    return mt5.close_all_positions(symbol)
