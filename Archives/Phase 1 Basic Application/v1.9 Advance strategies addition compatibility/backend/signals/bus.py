"""
Signal Bus
==========
Central in-memory signal store + broadcast mechanism.
Strategies publish signals here; chart WebSockets subscribe by symbol+timeframe.
Global signal WS receives ALL signals for the sidebar signal list.

Thread-safe singleton — one instance shared across the application.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from main.logger import get_logger

log = get_logger("signals")


class SignalBus:
    """
    Singleton signal registry.

    Strategies publish signals here.
    Chart WebSockets subscribe by symbol+timeframe to receive signal markers.
    Global signal WS gets ALL signals (sidebar list, trade updates).
    """

    _instance: Optional["SignalBus"] = None

    def __init__(self):
        self._signals: List[Dict] = []  # all signals (capped at 500 FIFO)
        self._chart_subscribers: Dict[str, List[Callable]] = {}  # "SYMBOL_TF" → [callback, ...]
        self._global_subscribers: List[Callable] = []  # all signals → [callback, ...]
        self._max_signals = 500

    @classmethod
    def get(cls) -> "SignalBus":
        """Get or create the singleton SignalBus instance."""
        if cls._instance is None:
            cls._instance = cls()
            log.info("SignalBus initialized")
        return cls._instance

    # ── Publishing ─────────────────────────────────────────────────

    async def publish(self, signal: dict):
        """
        Called by strategy scanner when a signal fires.
        Broadcasts to:
         1. Chart WS matching signal's symbol+timeframe
         2. All global signal WS subscribers (sidebar signal list)
        """
        self._signals.append(signal)
        if len(self._signals) > self._max_signals:
            self._signals = self._signals[-self._max_signals :]

        # 1. Broadcast to chart WS matching symbol+timeframe
        key = f"{signal.get('symbol', '')}_{signal.get('timeframe', '')}"
        await self._broadcast_to(
            self._chart_subscribers.get(key, []),
            {"type": "signal", "data": signal},
        )

        # 2. Broadcast to ALL global signal subscribers
        await self._broadcast_to(
            self._global_subscribers,
            {"type": "signal", "data": signal},
        )

        log.debug(f"Signal published | {signal.get('direction')} {signal.get('symbol')} [{signal.get('timeframe')}]")

    async def publish_trade_update(self, update: dict):
        """
        Broadcast trade status updates (TP/SL hits).
        Goes to global subscribers only — chart doesn't need TP/SL status updates.
        """
        # Also broadcast to matching chart for potential marker updates
        key = f"{update.get('symbol', '')}_{update.get('timeframe', '')}"
        payload = {"type": "trade_update", "data": update}

        await self._broadcast_to(self._chart_subscribers.get(key, []), payload)
        await self._broadcast_to(self._global_subscribers, payload)

    # ── Subscriptions ──────────────────────────────────────────────

    def subscribe_chart(self, symbol: str, timeframe: str, callback: Callable):
        """Chart WS registers to receive signals for a specific symbol+timeframe."""
        key = f"{symbol}_{timeframe}"
        if key not in self._chart_subscribers:
            self._chart_subscribers[key] = []
        self._chart_subscribers[key].append(callback)
        log.debug(f"Chart subscribed | {key}")

    def unsubscribe_chart(self, symbol: str, timeframe: str, callback: Callable):
        """Remove a chart WS subscription."""
        key = f"{symbol}_{timeframe}"
        if key in self._chart_subscribers:
            try:
                self._chart_subscribers[key].remove(callback)
            except ValueError:
                pass
            # Clean up empty lists
            if not self._chart_subscribers[key]:
                del self._chart_subscribers[key]

    def subscribe_global(self, callback: Callable):
        """Global signal WS registers to receive ALL signals."""
        self._global_subscribers.append(callback)
        log.debug("Global signal subscriber added")

    def unsubscribe_global(self, callback: Callable):
        """Remove a global signal WS subscription."""
        try:
            self._global_subscribers.remove(callback)
        except ValueError:
            pass

    # ── Query ──────────────────────────────────────────────────────

    def get_signals(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Get recent signals, optionally filtered by symbol and/or timeframe.
        Returns newest first.
        """
        sigs = self._signals
        if symbol:
            sigs = [s for s in sigs if s.get("symbol") == symbol]
        if timeframe:
            sigs = [s for s in sigs if s.get("timeframe") == timeframe]
        return list(reversed(sigs[-limit:]))

    # ── Internal ───────────────────────────────────────────────────

    async def _broadcast_to(self, subscribers: List[Callable], payload: dict):
        """Send payload to a list of async callback subscribers."""
        dead = []
        for callback in subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(payload)
                else:
                    callback(payload)
            except Exception:
                dead.append(callback)
        # Remove dead callbacks
        for cb in dead:
            try:
                subscribers.remove(cb)
            except ValueError:
                pass
