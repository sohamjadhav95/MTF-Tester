"""
Watchlist Engine
================
Minimal live candle streamer for independent chart data feeds.
Fetches historical bars, then polls for updates at adaptive intervals.
No strategy involvement — pure broker data.

One instance per watched symbol+timeframe pair.
"""

import asyncio
from typing import Callable, Dict, List, Optional

import pandas as pd

from main.logger import get_logger

log = get_logger("watchlist")

# Adaptive polling intervals per timeframe (seconds)
# Lower timeframes need faster updates; higher timeframes save resources.
POLL_INTERVALS: Dict[str, int] = {
    "M1": 3,
    "M5": 5,
    "M15": 10,
    "M30": 15,
    "H1": 30,
    "H4": 60,
    "D1": 120,
    "W1": 300,
    "MN1": 600,
}


class WatchlistEngine:
    """
    Live candle streamer for a single symbol+timeframe pair.
    Fetches historical bars, then polls the data provider for updates.
    No strategy, no indicator, no dependency — pure data.
    """

    def __init__(
        self,
        watch_id: str,
        symbol: str,
        timeframe: str,
        provider,
        broadcast_callback: Callable,
    ):
        self.watch_id = watch_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.provider = provider
        self.broadcast_callback = broadcast_callback

        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._last_bar_time = None
        self._history_bars = 500

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Historical Bars ────────────────────────────────────────────

    def get_historical_bars(self, num_bars: Optional[int] = None) -> List[Dict]:
        """
        Fetch initial historical candles for chart rendering.
        Returns list of bar dicts: {time, open, high, low, close, volume}
        """
        count = num_bars or self._history_bars
        try:
            df = self.provider.fetch_latest_bars(self.symbol, self.timeframe, count)
        except Exception as e:
            log.error(f"Historical fetch failed | {self.symbol}/{self.timeframe}: {e}")
            return []

        if df.empty:
            return []

        bars = []
        for _, row in df.iterrows():
            t = row["time"]
            time_str = t.isoformat() if hasattr(t, "isoformat") else str(t)
            # Ensure UTC Z suffix
            if not time_str.endswith("Z") and "+" not in time_str:
                time_str += "Z"
            bars.append(
                {
                    "time": time_str,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"] if pd.notna(row["volume"]) else 0),
                }
            )

        if df.shape[0] > 0:
            self._last_bar_time = df.iloc[-1]["time"]

        log.info(
            f"Watchlist historical | {self.symbol}/{self.timeframe} | "
            f"bars={len(bars)} | first={bars[0]['time'] if bars else '?'} | last={bars[-1]['time'] if bars else '?'}"
        )
        return bars

    # ── Live Polling ───────────────────────────────────────────────

    async def start_polling(self):
        """Poll provider at adaptive intervals for new/updated bars."""
        self._running = True
        interval = POLL_INTERVALS.get(self.timeframe, 5)
        log.info(
            f"Watchlist polling started | {self.symbol}/{self.timeframe} "
            f"| interval={interval}s | watch_id={self.watch_id}"
        )

        while self._running:
            try:
                updates = await asyncio.to_thread(self._fetch_latest)
                if updates:
                    await self.broadcast_callback(
                        {
                            "type": "bar_updates",
                            "data": updates,
                        }
                    )
            except Exception as e:
                log.error(f"Watchlist poll error | {self.symbol}/{self.timeframe}: {e}")
            await asyncio.sleep(interval)

    def _fetch_latest(self) -> List[Dict]:
        """
        Fetch latest bars from the provider and return them as dicts.
        Returns last 2 bars (current updating candle + possible new candle).
        """
        try:
            df = self.provider.fetch_latest_bars(self.symbol, self.timeframe, 5)
        except Exception:
            return []

        if df.empty:
            return []

        updates = []
        for _, row in df.iterrows():
            t = row["time"]
            time_str = t.isoformat() if hasattr(t, "isoformat") else str(t)
            if not time_str.endswith("Z") and "+" not in time_str:
                time_str += "Z"
            updates.append(
                {
                    "time": time_str,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"] if pd.notna(row["volume"]) else 0),
                }
            )

        if df.shape[0] > 0:
            self._last_bar_time = df.iloc[-1]["time"]

        # Only return last 2 bars (current updating + possible new)
        return updates[-2:]

    # ── Stop ───────────────────────────────────────────────────────

    def stop(self):
        """Stop polling loop."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        log.info(f"Watchlist stopped | {self.symbol}/{self.timeframe} | watch_id={self.watch_id}")
