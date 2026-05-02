"""
Pre-Trade Validation Pipeline
==============================
Every order MUST pass ALL checks before reaching the MT5 send call.
If any check fails, raise ValueError with a clear message.
"""

from main.config import MAX_LOT_SIZE
from main.models import OrderRequest


def validate_order(req: OrderRequest, mt5_provider, risk_state: dict):
    """
    Run full validation pipeline.
    Raises ValueError with descriptive message on any failure.
    """
    # 1. MT5 connected
    if not mt5_provider.connected:
        raise ValueError("MT5 is not connected")

    # 2. Confirm flag (manual orders must have confirm=True)
    if not req.confirm:
        raise ValueError("Order must be explicitly confirmed (confirm=true)")

    # 3. Symbol exists
    sym_info = mt5_provider.get_symbol_info(req.symbol)
    if not sym_info:
        raise ValueError(f"Symbol '{req.symbol}' not found or not available in MT5")

    # 4. Volume range
    vol_min = sym_info.get("volume_min", 0.01)
    vol_max = min(sym_info.get("volume_max", 100.0), MAX_LOT_SIZE)
    vol_step = sym_info.get("volume_step", 0.01)

    if req.volume < vol_min:
        raise ValueError(f"Volume {req.volume} is below minimum {vol_min}")
    if req.volume > vol_max:
        raise ValueError(
            f"Volume {req.volume} exceeds maximum {vol_max} "
            f"(symbol max or app safety limit of {MAX_LOT_SIZE})"
        )

    # 5. Price sanity for pending orders
    if req.order_type == "pending" and req.price is not None:
        tick = mt5_provider.get_symbol_tick(req.symbol)
        if tick:
            market_price = tick["ask"] if req.direction == "buy" else tick["bid"]
            if market_price > 0:
                deviation_pct = abs(req.price - market_price) / market_price * 100
                if deviation_pct > 5.0:
                    raise ValueError(
                        f"Pending order price {req.price} is {deviation_pct:.1f}% "
                        f"from market price {market_price}. Max allowed: 5%"
                    )

    # 6. SL/TP sanity
    if req.sl_enabled and req.sl is not None and req.sl <= 0:
        raise ValueError("Stop loss price must be positive")
    if req.tp_enabled and req.tp is not None and req.tp <= 0:
        raise ValueError("Take profit price must be positive")

    # For market orders, validate SL/TP direction against current tick
    if req.order_type == "market":
        tick = mt5_provider.get_symbol_tick(req.symbol)
        if (req.sl_enabled and req.sl) or (req.tp_enabled and req.tp):
            if not tick:
                raise ValueError("Cannot validate SL/TP — MT5 tick unavailable")
            
            entry = tick["ask"] if req.direction == "buy" else tick["bid"]
            if req.sl_enabled and req.sl:
                if req.direction == "buy" and req.sl >= entry:
                    raise ValueError(f"BUY stop loss {req.sl} must be below entry price {entry:.5f}")
                if req.direction == "sell" and req.sl <= entry:
                    raise ValueError(f"SELL stop loss {req.sl} must be above entry price {entry:.5f}")

    # 8. Broker stops_level check (retcode 10016 = "Invalid stops" from MT5)
    if req.order_type == "market" and (req.sl_enabled or req.tp_enabled):
        info = mt5_provider.get_symbol_info(req.symbol)
        stops_level_points = info.get("trade_stops_level", 0) if info else 0
        point = info.get("point", 0.00001) if info else 0.00001
        min_distance = stops_level_points * point
        tick = mt5_provider.get_symbol_tick(req.symbol)
        if tick and stops_level_points > 0:
            entry = tick["ask"] if req.direction == "buy" else tick["bid"]
            if req.sl_enabled and req.sl:
                if abs(entry - req.sl) < min_distance:
                    raise ValueError(
                        f"SL {req.sl} is too close to entry {entry:.5f} "
                        f"(broker requires at least {stops_level_points} points)"
                    )
            if req.tp_enabled and req.tp:
                if abs(entry - req.tp) < min_distance:
                    raise ValueError(
                        f"TP {req.tp} is too close to entry {entry:.5f} "
                        f"(broker requires at least {stops_level_points} points)"
                    )

    # 7. Risk threshold check
    if risk_state.get("breached") and risk_state.get("auto_close"):
        raise ValueError(
            "Risk threshold has been breached and auto-close mode is active. "
            "Disable auto-close or reset the risk threshold to place new orders."
        )
