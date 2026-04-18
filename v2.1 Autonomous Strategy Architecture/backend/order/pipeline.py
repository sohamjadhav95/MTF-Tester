"""
Order Pipeline — single code path for ALL order placements.

Manual placement (order/router.py) and automated placement (order/auto_executor.py)
BOTH call pipeline.place_order(). There is no other path to the broker.

Every order that reaches MT5 has been:
 1. Validated (validator.validate_order)
 2. Audited on entry (rejected) OR on result (place/failed)
 3. Logged to order.log

This is enforced by layering — routers do NOT call mt5.send_order directly.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional
import asyncio

from main.models import OrderRequest
from main.db import write_order_audit
from main.logger import get_logger
from order.validator import validate_order
from order.risk import RiskGuard
from data_collector.router import get_mt5

log = get_logger("order")


@dataclass
class OrderContext:
    """
    Metadata about where an order originated. Not part of OrderRequest because
    OrderRequest is a public API contract; context is internal plumbing.
    """
    source: str                    # "manual" | "auto"
    scanner_id: Optional[str] = None
    signal_id: Optional[str] = None
    comment: Optional[str] = None  # If provided, overrides the default comment


def _make_comment(ctx: OrderContext) -> str:
    """
    Build an MT5 comment (max 31 chars) encoding origin.
    Format:
      manual         → "MTF-MANUAL"
      auto signal    → "AUTO:{sid}:{id8}"  where id8 = first 8 chars of signal_id
    """
    if ctx.comment:
        return ctx.comment[:31]
    if ctx.source == "auto" and ctx.scanner_id and ctx.signal_id:
        sid = ctx.scanner_id.replace("scan-", "")  # "scan-3" → "3"
        return f"AUTO:{sid}:{ctx.signal_id[:8]}"[:31]
    return "MTF-MANUAL"


async def place_order(
    req: OrderRequest,
    ctx: OrderContext,
    risk_guard: RiskGuard,
) -> dict:
    """
    Run the full order placement pipeline.

    Returns the MT5 result dict (always — success or failure).
    Raises ValueError on validation failure (caller decides how to surface).
    """
    mt5 = get_mt5()

    log.info(
        f"Order requested | source={ctx.source} "
        f"{'scanner=' + ctx.scanner_id + ' ' if ctx.scanner_id else ''}"
        f"{req.direction.upper()} {req.volume} {req.symbol} {req.order_type}"
    )

    # ── Validate ─────────────────────────────────────────────────
    try:
        validate_order(req, mt5, risk_guard.get_state())
    except ValueError as e:
        log.warning(f"Order rejected | source={ctx.source} | reason={e}")
        write_order_audit(
            action="rejected",
            symbol=req.symbol, direction=req.direction, volume=req.volume,
            sl=req.sl, tp=req.tp,
            result={"error": str(e), **asdict(ctx)},
        )
        raise

    # ── Send ─────────────────────────────────────────────────────
    comment = _make_comment(ctx)
    result = await asyncio.to_thread(
        mt5.send_order,
        symbol=req.symbol,
        order_type=req.order_type,
        direction=req.direction,
        volume=req.volume,
        price=req.price,
        sl=req.sl,
        tp=req.tp,
        sl_enabled=req.sl_enabled,
        tp_enabled=req.tp_enabled,
        comment=comment,
    )

    # ── Audit (always) ───────────────────────────────────────────
    write_order_audit(
        action="place" if result.get("success") else "failed",
        symbol=req.symbol, direction=req.direction, volume=req.volume,
        price=result.get("price"),
        sl=req.sl, tp=req.tp,
        result={**result, **asdict(ctx)},
    )

    if result.get("success"):
        log.info(
            f"Order placed | source={ctx.source} "
            f"ticket={result.get('ticket')} | "
            f"{req.direction.upper()} {req.volume} {req.symbol} @ {result.get('price')} "
            f"comment={comment}"
        )
    else:
        log.error(f"Order failed | source={ctx.source} | error={result.get('error')}")

    return result
