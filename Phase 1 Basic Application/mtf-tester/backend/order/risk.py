"""
Risk Guard
===========
Monitors account equity against a user-defined drawdown threshold.
Can optionally auto-close all positions on breach.
Runs as a background polling task when enabled.
"""

import asyncio
from main.logger import get_logger

log = get_logger("order")


class RiskGuard:
    def __init__(self):
        self._enabled = False
        self._threshold_pct = 5.0
        self._auto_close = False
        self._initial_balance = None
        self._breached = False
        self._task = None

    def configure(self, enabled: bool, threshold_pct: float, auto_close: bool = False):
        self._enabled = enabled
        self._threshold_pct = threshold_pct
        self._auto_close = auto_close
        if enabled and self._task is None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    self._task = asyncio.create_task(self._monitor_loop())
            except RuntimeError:
                pass  # No event loop available
        elif not enabled and self._task:
            self._task.cancel()
            self._task = None
            self._breached = False
            self._initial_balance = None

    def get_state(self) -> dict:
        return {
            "enabled": self._enabled,
            "threshold_pct": self._threshold_pct,
            "auto_close": self._auto_close,
            "initial_balance": self._initial_balance,
            "breached": self._breached,
        }

    async def _monitor_loop(self):
        """Poll account equity every 5 seconds."""
        from data_collector.router import get_mt5
        mt5 = get_mt5()

        while self._enabled:
            try:
                if mt5.connected:
                    equity_info = mt5.get_account_equity()
                    if equity_info:
                        if self._initial_balance is None:
                            self._initial_balance = equity_info["balance"]

                        if self._initial_balance and self._initial_balance > 0:
                            drawdown_pct = (
                                (self._initial_balance - equity_info["equity"])
                                / self._initial_balance * 100
                            )
                            if drawdown_pct >= self._threshold_pct and not self._breached:
                                self._breached = True
                                log.warning(
                                    f"RISK THRESHOLD BREACHED | "
                                    f"drawdown={drawdown_pct:.2f}% | "
                                    f"threshold={self._threshold_pct}% | "
                                    f"auto_close={self._auto_close}"
                                )
                                if self._auto_close:
                                    await asyncio.to_thread(mt5.close_all_positions)
                                    log.warning("AUTO-CLOSE triggered — all positions closed")
            except Exception as e:
                log.error(f"Risk monitor error: {e}")

            await asyncio.sleep(5)
