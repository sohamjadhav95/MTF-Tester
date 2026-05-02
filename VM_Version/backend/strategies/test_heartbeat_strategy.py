"""
Heartbeat Test Strategy — Normal Use Case Verifier
===================================================
A deterministic "clock" strategy that emits BUY/SELL on a fixed cadence of
M1 bars. Use this to verify the happy path end-to-end.

No look-ahead, no noise, no false signals. Every signal is timestamped by the
bar's close time, so you can check the log and know EXACTLY when each fired.

HOW TO READ SIGNALS
-------------------
The strategy fires BUY every `cadence_bars` M1 bars. SELL fires exactly
`cadence_bars / 2` bars offset from BUY. SL and TP are dynamically sized
using the Average True Range (ATR) so that the stops are valid for ANY
symbol without needing manual pip size configuration. This prevents broker
errors like "Invalid stops (code 10016)".

USAGE
-----
Upload this file via Create Strategy → Upload. Then in MTF Strategy:
    Session Name: "Heartbeat"
    Symbol:       Any active symbol (e.g., EURUSD, XAUUSDm)
    Strategy:     Heartbeat Test
    cadence_bars: 60   (a signal every hour of M1 data)

Launch. Within ~60 M1 bars you'll see the first BUY; then a SELL 30 bars later.
"""

from __future__ import annotations

from typing import Literal
import numpy as np
import pandas as pd
from pydantic import Field

from ._template import BaseStrategy, StrategyConfig, Signal, HOLD


class HeartbeatConfig(StrategyConfig):
    cadence_bars: int = Field(
        60, ge=2, le=10_000,
        description="Emit BUY every N M1 bars (SELL fires at N/2 offset)"
    )
    offset_bars: int = Field(
        0, ge=0, le=10_000,
        description="Skip the first N bars before starting the clock"
    )
    atr_multiplier: float = Field(
        2.0, ge=0.1, le=10.0,
        description="Stop Loss distance as a multiple of ATR (volatility-scaled)"
    )
    rr_ratio: float = Field(
        2.0, ge=0.1, le=20.0,
        description="Take Profit distance as a multiple of SL distance (Risk/Reward)"
    )
    direction_mode: Literal["alternate", "long_only", "short_only"] = Field(
        "alternate",
        description="alternate=BUY/SELL flip; long_only=BUY only; short_only=SELL only"
    )


class HeartbeatTest(BaseStrategy):
    name = "Heartbeat Test"
    description = "Deterministic clock strategy — BUY/SELL on fixed cadence. Auto-scaled stops."
    config_model = HeartbeatConfig

    def on_start(self, data: pd.DataFrame) -> None:
        """Pre-compute indicators. We use ATR for dynamic stop loss sizing."""
        self.state.setdefault("cum_bars", len(data))
        
        high = data["high"].values.astype(float)
        low = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        
        # Calculate True Range
        tr = np.full(len(close), np.nan)
        if len(close) > 0:
            tr[0] = high[0] - low[0]
            for i in range(1, len(close)):
                hl = high[i] - low[i]
                hc = abs(high[i] - close[i - 1])
                lc = abs(low[i] - close[i - 1])
                tr[i] = max(hl, hc, lc)
        
        # Calculate 14-period ATR
        period = 14
        atr = np.full(len(tr), np.nan)
        if len(tr) >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, len(tr)):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        self._cache = {
            "closes": close,
            "atr": atr,
        }

    def on_update(self, new_bars: pd.DataFrame, data: pd.DataFrame) -> None:
        """Increment cumulative bars and re-run on_start to update ATR."""
        self.state["cum_bars"] += len(new_bars)
        self.on_start(data)

    def on_bar(self, index: int, data: pd.DataFrame) -> Signal:
        cache = self._cache
        if not cache:
            return HOLD

        cum_bars = self.state.get("cum_bars", len(data))
        abs_index = cum_bars - len(data) + index

        cfg = self.config
        cadence = cfg.cadence_bars
        half = cadence // 2
        offset = cfg.offset_bars

        if abs_index < offset:
            return HOLD

        rel_index = abs_index - offset
        
        direction = ""
        if rel_index % cadence == 0:
            direction = "BUY"
        elif rel_index % cadence == half:
            direction = "SELL"

        if not direction:
            return HOLD

        if cfg.direction_mode == "long_only" and direction == "SELL":
            return HOLD
        if cfg.direction_mode == "short_only" and direction == "BUY":
            return HOLD

        price = float(cache["closes"][index])
        atr_val = cache["atr"][index]
        
        # Fallback if ATR is not ready or is zero (extremely low volatility)
        if np.isnan(atr_val) or atr_val <= 0:
            atr_val = price * 0.001  # 0.1% of price as fallback

        # Calculate Stop Loss distance based on ATR
        sl_dist = atr_val * cfg.atr_multiplier
        tp_dist = sl_dist * cfg.rr_ratio

        sl = None
        tp = None

        if direction == "BUY":
            sl = price - sl_dist
            tp = price + tp_dist
        else:
            sl = price + sl_dist
            tp = price - tp_dist

        return Signal(
            direction=direction,
            sl=sl,
            tp=tp,
            metadata={
                "strategy": "Heartbeat",
                "abs_index": abs_index,
                "atr": round(atr_val, 5),
            },
        )
