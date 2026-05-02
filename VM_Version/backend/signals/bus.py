"""
Signal Bus
==========
Central in-memory signal store + broadcast mechanism.
Strategies publish signals here; chart WebSockets subscribe by symbol.
All signals for a symbol broadcast to every chart watching that symbol,
regardless of chart timeframe. Global signal WS receives ALL signals.

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
    Chart WebSockets subscribe by symbol+timeframe key, but signals
    broadcast to ALL charts watching the same symbol (cross-timeframe).
    Global signal WS gets ALL signals (sidebar list, trade updates).
    """

    _instance: Optional["SignalBus"] = None

    def __init__(self):
        self._signals: List[Dict] = []  # all signals (capped at 500 FIFO)
        self._chart_subscribers: Dict[str, List[Callable]] = {}  # "SYMBOL_TF" → [callback, ...]
        self._global_subscribers: List[Callable] = []  # all signals → [callback, ...]
        self._service_subscribers: List[Callable] = []  # permanent: NEVER auto-removed
        self._max_signals = 500

    @classmethod
    def get(cls) -> "SignalBus":
        """Get or create the singleton SignalBus instance."""
        if cls._instance is None:
            cls._instance = cls()
            log.info("SignalBus initialized")
        return cls._instance

    # ── Services ───────────────────────────────────────────────────

    def subscribe_service(self, callback: Callable):
        """
        Register a long-lived in-process service (e.g. AutoExecutor).
        Service subscribers are NEVER auto-removed by the bus, regardless of
        what exception their callback raises. Exceptions are logged loudly
        but the subscription stays active.
        """
        self._service_subscribers.append(callback)
        log.info(f"Service subscriber added (total={len(self._service_subscribers)})")
    
    def unsubscribe_service(self, callback: Callable):
        try:
            self._service_subscribers.remove(callback)
        except ValueError:
            pass

    # ── Publishing ─────────────────────────────────────────────────

    async def publish(self, signal: dict):
        """
        Called by strategy scanner when a signal fires.
        Broadcasts to:
         1. Services (AutoExecutor)
         2. Chart WS matching signal's symbol+timeframe
         3. All global signal WS subscribers (sidebar signal list)
        """
        self._signals.append(signal)
        if len(self._signals) > self._max_signals:
            self._signals = self._signals[-self._max_signals :]

        payload = {"type": "signal", "data": signal}
        
        # Services first — never removed on error
        await self._broadcast_to_services(payload)

        # 1. Broadcast to ALL chart WS subscribers watching this symbol
        #    (cross-timeframe: M5 signal → H1 chart, H4 chart, etc.)
        symbol = signal.get('symbol', '')
        for key, subscribers in list(self._chart_subscribers.items()):
            if key.startswith(f"{symbol}_"):
                await self._broadcast_to_transient(
                    subscribers, payload
                )

        # 2. Broadcast to ALL global signal subscribers
        await self._broadcast_to_transient(
            self._global_subscribers, payload
        )

        log.debug(f"Signal published | {signal.get('direction')} {signal.get('symbol')} [{signal.get('timeframe')}]")

    async def publish_trade_update(self, update: dict, global_only: bool = False):
        """
        Broadcast trade status updates (TP/SL hits).
        Goes to global subscribers only if global_only=True.
        """
        payload = {"type": "trade_update", "data": update}
        await self._broadcast_to_services(payload)
        
        if not global_only:
            # Broadcast to ALL charts watching this symbol (cross-timeframe)
            symbol = update.get('symbol', '')
            for key, subscribers in list(self._chart_subscribers.items()):
                if key.startswith(f"{symbol}_"):
                    await self._broadcast_to_transient(subscribers, payload)
        
        await self._broadcast_to_transient(self._global_subscribers, payload)

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

    async def _broadcast_to_services(self, payload: dict):
        """Service callbacks are NEVER removed — only logged on error."""
        for cb in self._service_subscribers:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except Exception as e:
                log.error(
                    f"Service subscriber raised (KEPT, will be called again): "
                    f"{type(e).__name__}: {e}",
                    exc_info=True,
                )

    async def _broadcast_to_transient(self, subs: List[Callable], payload: dict):
        """Transient subscribers (WebSockets) — removed only on explicit disconnect."""
        from fastapi.websockets import WebSocketDisconnect
        dead = []
        for cb in subs:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except WebSocketDisconnect:
                dead.append(cb)
            except (ConnectionResetError, ConnectionAbortedError):
                dead.append(cb)
            except RuntimeError as e:
                # Starlette raises RuntimeError("Cannot call send after close")
                if "after close" in str(e).lower() or "already disconnected" in str(e).lower():
                    dead.append(cb)
                else:
                    log.error(f"Transient subscriber raised (KEPT): {e}", exc_info=True)
            except Exception as e:
                log.error(f"Transient subscriber raised (KEPT): {e}", exc_info=True)
        for cb in dead:
            try:
                subs.remove(cb)
            except ValueError:
                pass
