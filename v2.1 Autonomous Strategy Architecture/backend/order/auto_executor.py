"""
Automated Trade Execution
=========================
Subscribes to SignalBus.
For every LIVE signal from a scanner that is flagged auto-enabled, translates
the signal into an OrderRequest and places it via order.pipeline.place_order().

CONTRACT:
- We NEVER trade on historical signals (live=False). Hard-enforced.
- We NEVER trade on the same signal.id twice. Dedup set.
- We NEVER trade on a signal whose bar_time is older than STALENESS_SECONDS.
- We ALWAYS go through order.pipeline (same validation, same audit as manual).
- We ALWAYS tag the MT5 position with comment="AUTO:{scanner_id}:{sig_id[:8]}".
- On N consecutive failures for a scanner, auto-disable it and notify frontend.

State lives in THIS module — server-side truth. Frontend reflects it via the
/api/order/auto/* endpoints and trade_update broadcasts on the signal bus.
"""

from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Set, Optional

from main.config import DEFAULT_LOT_SIZE
from main.models import OrderRequest
from main.logger import get_logger
from order.pipeline import place_order, OrderContext
from order.risk import RiskGuard
from signals.bus import SignalBus

log = get_logger("auto")

# Reject signals older than this (wall-clock seconds from bar_time to now)
STALENESS_SECONDS = 30

# After this many consecutive failures, auto-disable the scanner
MAX_CONSECUTIVE_FAILURES = 3


@dataclass
class AutoConfig:
    """Per-scanner auto-execution configuration."""
    enabled: bool = False
    volume: float = DEFAULT_LOT_SIZE          # fixed lots per trade
    override_sl: Optional[float] = None       # if set, ignore signal.sl
    override_tp: Optional[float] = None       # if set, ignore signal.tp
    fail_count: int = 0                       # consecutive failures, reset on success
    max_open_positions: int = 1               # default: 1 position per scanner


class AutoExecutor:
    """Singleton. Subscribes once to SignalBus on startup."""

    _instance: Optional["AutoExecutor"] = None

    def __init__(self, risk_guard: RiskGuard):
        self._risk_guard = risk_guard
        self._configs: Dict[str, AutoConfig] = {}     # scanner_id → config
        self._processed_signal_ids: Set[str] = set()  # dedup
        self._processing_lock = asyncio.Lock()        # serialize order placement
        self._max_processed = 5000                    # cap memory

    @classmethod
    def get(cls, risk_guard: Optional[RiskGuard] = None) -> "AutoExecutor":
        if cls._instance is None:
            if risk_guard is None:
                raise RuntimeError("AutoExecutor.get() needs risk_guard on first call")
            cls._instance = cls(risk_guard)
        return cls._instance

    # ── Lifecycle ────────────────────────────────────────────────

    def attach_to_bus(self):
        """Call once on app startup after SignalBus is created."""
        bus = SignalBus.get()
        bus.subscribe_global(self._on_bus_message)
        log.info("AutoExecutor attached to SignalBus")

    # ── Config management ────────────────────────────────────────

    def enable(self, scanner_id: str, volume: float = DEFAULT_LOT_SIZE,
               override_sl: Optional[float] = None,
               override_tp: Optional[float] = None):
        cfg = self._configs.get(scanner_id, AutoConfig())
        cfg.enabled = True
        cfg.volume = volume
        cfg.override_sl = override_sl
        cfg.override_tp = override_tp
        cfg.fail_count = 0
        self._configs[scanner_id] = cfg
        log.info(f"Auto-trade ENABLED | scanner={scanner_id} | volume={volume}")

    def disable(self, scanner_id: str):
        if scanner_id in self._configs:
            self._configs[scanner_id].enabled = False
            log.info(f"Auto-trade DISABLED | scanner={scanner_id}")

    def remove(self, scanner_id: str):
        """Called when a scanner is stopped."""
        self._configs.pop(scanner_id, None)

    def get_config(self, scanner_id: str) -> Optional[AutoConfig]:
        return self._configs.get(scanner_id)

    def get_all_configs(self) -> Dict[str, dict]:
        return {
            sid: {"enabled": c.enabled, "volume": c.volume,
                  "override_sl": c.override_sl, "override_tp": c.override_tp,
                  "fail_count": c.fail_count}
            for sid, c in self._configs.items()
        }

    # ── Signal handler ───────────────────────────────────────────

    async def _on_bus_message(self, payload: dict):
        """Bus calls this with {type, data}. We only care about type=signal."""
        if payload.get("type") != "signal":
            return
        sig = payload.get("data", {})
        await self.on_signal(sig)

    async def on_signal(self, sig: dict):
        """Main entry point. All decisions happen here in order."""
        # Gate 1: must be a live signal
        if not sig.get("live"):
            return

        from main.config import AUTO_EXEC_KILL_SWITCH
        if AUTO_EXEC_KILL_SWITCH:
            return

        # Gate 2: must have a scanner_id
        scanner_id = sig.get("scanner_id")
        if not scanner_id:
            log.warning(f"Live signal without scanner_id | id={sig.get('id')}")
            return

        # Gate 3: auto must be enabled for this scanner
        cfg = self._configs.get(scanner_id)
        if not cfg or not cfg.enabled:
            return

        # Gate 4: direction must be BUY or SELL (not HOLD)
        direction = str(sig.get("direction", "")).upper()
        if direction not in ("BUY", "SELL"):
            return

        # Gate 5: dedup — never trade the same signal twice
        sig_id = sig.get("id")
        if not sig_id:
            log.warning(f"Live signal without id | scanner={scanner_id}")
            return
        if sig_id in self._processed_signal_ids:
            return

        # Gate 6: freshness — reject stale signals
        bar_time_str = sig.get("bar_time") or sig.get("time")
        if bar_time_str and not self._is_fresh(bar_time_str):
            log.warning(
                f"Stale signal rejected | scanner={scanner_id} id={sig_id} "
                f"bar_time={bar_time_str}"
            )
            self._processed_signal_ids.add(sig_id)  # burn the id either way
            return

        # Passed all gates — attempt the trade under a lock so we serialize
        async with self._processing_lock:
            # Re-check dedup inside the lock (defensive against concurrent calls)
            if sig_id in self._processed_signal_ids:
                return
            self._processed_signal_ids.add(sig_id)
            self._trim_processed()
            await self._place_from_signal(sig, cfg)

    # ── Placement ────────────────────────────────────────────────

    async def _place_from_signal(self, sig: dict, cfg: AutoConfig):
        scanner_id = sig["scanner_id"]
        sig_id = sig["id"]

        # Translate signal direction (BUY/SELL) to OrderRequest direction (buy/sell)
        direction = sig["direction"].lower()

        # Build SL/TP: overrides win, else signal's own values
        sl = cfg.override_sl if cfg.override_sl is not None else sig.get("sl")
        tp = cfg.override_tp if cfg.override_tp is not None else sig.get("tp")

        req = OrderRequest(
            symbol=sig["symbol"],
            order_type="market",
            direction=direction,
            volume=cfg.volume,
            price=None,
            sl=sl,
            tp=tp,
            sl_enabled=(sl is not None),
            tp_enabled=(tp is not None),
            confirm=True,
        )
        ctx = OrderContext(
            source="auto",
            scanner_id=scanner_id,
            signal_id=sig_id,
        )

        if self._risk_guard.get_state().get("breached"):
            await self._broadcast_result(
                sig, success=False,
                error="Risk threshold breached — auto-trade paused"
            )
            # Do NOT increment fail_count — this is an external condition, not a pipeline failure
            return

        # Fetch positions & tag prefix
        from data_collector.router import get_mt5
        mt5 = get_mt5()
        positions = await asyncio.to_thread(mt5.get_positions, sig["symbol"]) or []
        tag_prefix = f"AUTO:{scanner_id.replace('scan-', '')}:"
        owned = [p for p in positions if p.get("comment", "").startswith(tag_prefix)]

        # Direction-flip handling: close opposite-side scanner positions first
        new_dir = "buy" if direction == "buy" else "sell"
        for p in owned:
            if p["type"] != new_dir:
                await asyncio.to_thread(mt5.close_position, p["ticket"])
                log.info(f"Auto reversed | scanner={scanner_id} | closed {p['ticket']}")
        
        owned = [p for p in owned if p["type"] == new_dir]  # recount after closes

        if len(owned) >= cfg.max_open_positions:
            await self._broadcast_result(
                sig, success=False,
                error=f"max_open_positions={cfg.max_open_positions} reached for scanner {scanner_id}"
            )
            return

        try:
            result = await place_order(req, ctx, self._risk_guard)
        except ValueError as e:
            # Validation failure
            cfg.fail_count += 1
            await self._broadcast_result(sig, success=False, error=str(e))
            self._maybe_auto_disable(scanner_id, cfg)
            return
        except Exception as e:
            # Unexpected failure — log but don't crash the subscriber
            cfg.fail_count += 1
            log.error(f"Auto-exec unexpected error | scanner={scanner_id} id={sig_id} | {e}")
            await self._broadcast_result(sig, success=False, error=str(e))
            self._maybe_auto_disable(scanner_id, cfg)
            return

        if result.get("success"):
            cfg.fail_count = 0
            await self._broadcast_result(
                sig, success=True,
                ticket=result.get("ticket"), price=result.get("price"),
            )
        else:
            cfg.fail_count += 1
            await self._broadcast_result(sig, success=False, error=result.get("error", "Unknown"))
            self._maybe_auto_disable(scanner_id, cfg)

    # ── Helpers ──────────────────────────────────────────────────

    def _is_fresh(self, bar_time_str: str) -> bool:
        """Reject signals where bar_time is older than STALENESS_SECONDS."""
        try:
            # Strip Z, parse as UTC
            s = bar_time_str.rstrip("Z")
            bar_time = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - bar_time).total_seconds()
            return -5 <= age <= STALENESS_SECONDS
        except Exception:
            return False

    def _maybe_auto_disable(self, scanner_id: str, cfg: AutoConfig):
        if cfg.fail_count >= MAX_CONSECUTIVE_FAILURES:
            cfg.enabled = False
            log.warning(
                f"Auto-trade AUTO-DISABLED | scanner={scanner_id} | "
                f"consecutive failures={cfg.fail_count}"
            )

    def _trim_processed(self):
        if len(self._processed_signal_ids) > self._max_processed:
            # Keep the latest half — we don't know order but we cap memory
            self._processed_signal_ids = set(
                list(self._processed_signal_ids)[-self._max_processed // 2:]
            )

    async def _broadcast_result(self, sig: dict, success: bool,
                                ticket: Optional[int] = None,
                                price: Optional[float] = None,
                                error: Optional[str] = None):
        """Send a trade_update reusing the signal's id so frontend can link them."""
        from signals.bus import SignalBus
        update = {
            "type": "trade_update",
            "id": sig["id"],
            "scanner_id": sig.get("scanner_id"),
            "symbol": sig["symbol"],
            "status": "AUTO_PLACED" if success else "AUTO_FAILED",
            "ticket": ticket,
            "price": price,
            "error": error,
            "time": datetime.now(timezone.utc).isoformat() + "Z",
        }
        await SignalBus.get().publish_trade_update(update)
