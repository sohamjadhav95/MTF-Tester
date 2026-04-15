"""
Watchlist Engine
================
Minimal live candle streamer for independent chart data feeds.
Fetches historical bars, then polls for updates at adaptive intervals.
No strategy involvement — pure broker data.

One instance per watched symbol+timeframe pair.

Indicator support (v1.9):
  - Maintains a rolling DataFrame (self._df) used for BOTH candle bars
    and indicator computation, guaranteeing zero data inconsistency.
  - Indicators are added/removed/updated via methods; computation uses
    the same df that produced the candle bars.
"""

import asyncio
from typing import Callable, Dict, List, Optional

import pandas as pd

from main.logger import get_logger
from watchlist.indicators import compute_indicator

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
    No strategy, no dependency — pure data + optional indicators.

    Indicators are computed from self._df — the same DataFrame that
    produces candle bars. This guarantees zero inconsistency between
    historical and live data for both candles and indicators.
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

        # ── Rolling DataFrame: single source of truth ──────────────
        # Both candle bars and indicator values derive from this df.
        self._df: pd.DataFrame = pd.DataFrame()

        # ── Active indicators ──────────────────────────────────────
        # indicator_id → { type, settings, data (last computed) }
        self._indicators: Dict[str, Dict] = {}
        self._indicator_counter = 0

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Bar Formatting ─────────────────────────────────────────────
    # Shared helper so candle bars from get_historical_bars() and
    # _fetch_latest() use the exact same formatting logic.

    @staticmethod
    def _bar_from_row(row) -> Dict:
        """Convert a DataFrame row to a bar dict."""
        t = row["time"]
        time_str = t.isoformat() if hasattr(t, "isoformat") else str(t)
        # Ensure UTC Z suffix
        if not time_str.endswith("Z") and "+" not in time_str:
            time_str += "Z"
        return {
            "time": time_str,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"] if pd.notna(row["volume"]) else 0),
        }

    # ── Historical Bars ────────────────────────────────────────────

    def get_historical_bars(self, num_bars: Optional[int] = None) -> List[Dict]:
        """
        Fetch initial historical candles for chart rendering.
        Returns list of bar dicts: {time, open, high, low, close, volume}

        Also stores the full DataFrame in self._df for indicator computation.
        """
        count = num_bars or self._history_bars
        try:
            df = self.provider.fetch_latest_bars(self.symbol, self.timeframe, count)
        except Exception as e:
            log.error(f"Historical fetch failed | {self.symbol}/{self.timeframe}: {e}")
            return []

        if df.empty:
            return []

        # Store the full df — single source of truth for indicators
        self._df = df.reset_index(drop=True)

        bars = [self._bar_from_row(row) for _, row in df.iterrows()]

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
                result = await asyncio.to_thread(self._fetch_latest)
                if result:
                    bars, indicator_updates = result
                    payload = {
                        "type": "bar_updates",
                        "data": {
                            "bars": bars,
                            "indicators": indicator_updates,
                        },
                    }
                    await self.broadcast_callback(payload)
            except Exception as e:
                log.error(f"Watchlist poll error | {self.symbol}/{self.timeframe}: {e}")
            await asyncio.sleep(interval)

    def _fetch_latest(self) -> Optional[tuple]:
        """
        Fetch latest bars from the provider, merge into self._df,
        and compute indicator updates.

        Returns (bars, indicator_updates) or None if no data.
        """
        try:
            df_latest = self.provider.fetch_latest_bars(self.symbol, self.timeframe, 5)
        except Exception:
            return None

        if df_latest.empty:
            return None

        # ── Merge latest bars into the rolling DataFrame ───────────
        # This ensures self._df is always the continuous, complete
        # dataset — no gap between historical and live.
        if not self._df.empty and "time" in self._df.columns:
            # Find bars in df_latest that are newer or match existing tail
            existing_times = set(self._df["time"].astype(str))
            new_rows = []
            update_rows = []

            for _, row in df_latest.iterrows():
                t_str = str(row["time"])
                if t_str in existing_times:
                    # Update existing bar (current candle keeps changing)
                    update_rows.append(row)
                else:
                    # Brand new bar
                    new_rows.append(row)

            # Update existing bars in-place (for the current live candle)
            for row in update_rows:
                mask = self._df["time"].astype(str) == str(row["time"])
                if mask.any():
                    idx = self._df.index[mask][0]
                    for col in ["open", "high", "low", "close", "volume"]:
                        if col in row.index:
                            self._df.at[idx, col] = row[col]

            # Append genuinely new bars
            if new_rows:
                new_df = pd.DataFrame(new_rows)
                self._df = pd.concat([self._df, new_df], ignore_index=True)

            # Trim to keep memory bounded (keep last 1000 bars max)
            if len(self._df) > 1000:
                self._df = self._df.iloc[-1000:].reset_index(drop=True)
        else:
            self._df = df_latest.reset_index(drop=True)

        # Format bars for broadcast
        updates = [self._bar_from_row(row) for _, row in df_latest.iterrows()]

        if df_latest.shape[0] > 0:
            self._last_bar_time = df_latest.iloc[-1]["time"]

        # Only return last 2 bars (current updating + possible new)
        bars = updates[-2:]

        # ── Compute indicator updates from the SAME self._df ───────
        indicator_updates = self._compute_indicator_updates()

        return bars, indicator_updates

    # ── Indicator Management ───────────────────────────────────────

    def add_indicator(self, indicator_type: str, settings: dict) -> Dict:
        """
        Add an indicator to this chart. Computes from self._df.
        Returns {indicator_id, type, settings, data}.
        """
        self._indicator_counter += 1
        ind_id = f"ind-{self._indicator_counter}"

        # Merge default settings from registry
        from watchlist.indicators import INDICATOR_REGISTRY
        registry_entry = next((r for r in INDICATOR_REGISTRY if r["id"] == indicator_type), None)
        if registry_entry:
            merged = {**registry_entry["defaultSettings"], **settings}
        else:
            merged = settings

        # Compute from the full rolling df
        data = {}
        if not self._df.empty:
            try:
                data = compute_indicator(self._df, indicator_type, merged)
            except Exception as e:
                log.error(f"Indicator compute failed | {indicator_type}: {e}")

        self._indicators[ind_id] = {
            "type": indicator_type,
            "settings": merged,
        }

        log.info(
            f"Indicator added | watch={self.watch_id} | id={ind_id} | "
            f"type={indicator_type} | settings={merged}"
        )

        return {
            "indicator_id": ind_id,
            "type": indicator_type,
            "settings": merged,
            "data": data,
        }

    def remove_indicator(self, indicator_id: str) -> bool:
        """Remove an indicator from this chart."""
        if indicator_id in self._indicators:
            del self._indicators[indicator_id]
            log.info(f"Indicator removed | watch={self.watch_id} | id={indicator_id}")
            return True
        return False

    def update_indicator(self, indicator_id: str, settings: dict) -> Optional[Dict]:
        """
        Update indicator settings and recompute from self._df.
        Returns {indicator_id, type, settings, data} or None if not found.
        """
        ind = self._indicators.get(indicator_id)
        if not ind:
            return None

        # Merge new settings into existing
        merged = {**ind["settings"], **settings}
        ind["settings"] = merged

        # Recompute from the full rolling df
        data = {}
        if not self._df.empty:
            try:
                data = compute_indicator(self._df, ind["type"], merged)
            except Exception as e:
                log.error(f"Indicator recompute failed | {ind['type']}: {e}")

        log.info(
            f"Indicator updated | watch={self.watch_id} | id={indicator_id} | "
            f"settings={merged}"
        )

        return {
            "indicator_id": indicator_id,
            "type": ind["type"],
            "settings": merged,
            "data": data,
        }

    def get_all_indicator_data(self) -> Dict:
        """
        Compute all active indicators from self._df.
        Called when a new WS client connects to get the full state.
        """
        result = {}
        if self._df.empty:
            return result

        for ind_id, ind in self._indicators.items():
            try:
                data = compute_indicator(self._df, ind["type"], ind["settings"])
                result[ind_id] = {
                    "type": ind["type"],
                    "settings": ind["settings"],
                    "data": data,
                }
            except Exception as e:
                log.error(f"Indicator compute failed | {ind['type']}: {e}")

        return result

    def get_active_indicators(self) -> List[Dict]:
        """Return metadata for all active indicators (no heavy data)."""
        return [
            {"indicator_id": ind_id, "type": ind["type"], "settings": ind["settings"]}
            for ind_id, ind in self._indicators.items()
        ]

    def _compute_indicator_updates(self) -> Dict:
        """
        Compute all active indicators from the full self._df for live updates.
        Returns {ind_id: {type, data}, ...}.

        We recompute from the full df (not just the tail) because some
        indicators (EMA, RSI, MACD) have lookback dependencies. This ensures
        perfect continuity between historical and live values.
        """
        result = {}
        if self._df.empty or not self._indicators:
            return result

        for ind_id, ind in self._indicators.items():
            try:
                data = compute_indicator(self._df, ind["type"], ind["settings"])
                result[ind_id] = {
                    "type": ind["type"],
                    "data": data,
                }
            except Exception:
                pass  # skip failed indicators silently on live updates

        return result

    # ── Stop ───────────────────────────────────────────────────────

    def stop(self):
        """Stop polling loop."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None
        log.info(f"Watchlist stopped | {self.symbol}/{self.timeframe} | watch_id={self.watch_id}")
