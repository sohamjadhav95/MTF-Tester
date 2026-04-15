"""
EMA Crossover Strategy
======================
Enhanced with three SL/TP modes:
  - fixed_rr    : SL at fixed pips; TP = SL distance × R/R ratio
  - candle_low  : SL at the entry bar's low (BUY) or high (SELL); TP = SL × R/R
  - atr         : SL = entry ± ATR × multiplier; TP = SL × R/R
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from ._template import BaseStrategy, StrategyConfig


# ─── Pydantic Config (Single Source of Truth) ───────────────────
class EMAConfig(StrategyConfig):
    """Typed, validated configuration for the EMA Crossover strategy."""

    # EMA Settings
    fast_period: int = Field(
        10, ge=2, le=500,
        description="Fast EMA Period",
        json_schema_extra={"step": 1},
    )
    slow_period: int = Field(
        100, ge=2, le=500,
        description="Slow EMA Period",
        json_schema_extra={"step": 1},
    )
    source: Literal["open", "high", "low", "close"] = Field(
        "close",
        description="Price Source",
    )
    trade_direction: Literal["both", "long_only", "short_only"] = Field(
        "both",
        description="Trade Direction",
    )


# ─── Strategy ──────────────────────────────────────────────────
class EMACrossover(BaseStrategy):
    """
    EMA Crossover Strategy.

    Generates BUY signals when the fast EMA crosses above the slow EMA,
    and SELL signals when the fast EMA crosses below the slow EMA.

    SL/TP Modes:
      - fixed_rr   : SL at a fixed pip distance; TP calculated using Risk/Reward ratio
      - candle_low : SL placed at the low (BUY) or high (SELL) of the entry candle
      - atr        : SL placed at entry ± (ATR × multiplier); TP from R/R ratio
    """

    name = "EMA Crossover"
    description = (
        "Generates signals based on the crossover of two Exponential "
        "Moving Averages (fast & slow). No SL/TP — pure signal only."
    )
    config_model = EMAConfig

    # ─── EMA Calculation ────────────────────────────────────────
    def _compute_ema(self, series: pd.Series, period: int) -> np.ndarray:
        """
        Standard EMA: EMA[i] = price * k + EMA[i-1] * (1 - k), k = 2/(p+1)
        First EMA value = SMA of first 'period' bars. Matches MT5 / TradingView.
        """
        values = series.values.astype(float)
        ema = np.full(len(values), np.nan)
        k = 2.0 / (period + 1)

        if len(values) < period:
            return ema

        ema[period - 1] = np.mean(values[:period])
        for i in range(period, len(values)):
            ema[i] = values[i] * k + ema[i - 1] * (1 - k)

        return ema


    # ─── on_bar ─────────────────────────────────────────────────
    def on_bar(self, index: int, data: pd.DataFrame):
        """
        Generate signal based on EMA crossover.
        Returns either 'HOLD', 'BUY', or 'SELL'.
        """
        cfg = self.config
        min_bars = max(cfg.fast_period, cfg.slow_period) + 1

        if len(data) < min_bars:
            return "HOLD"

        prices = data[cfg.source]
        fast_ema = self._compute_ema(prices, cfg.fast_period)
        slow_ema = self._compute_ema(prices, cfg.slow_period)

        curr_fast = fast_ema[index]
        curr_slow = slow_ema[index]
        prev_fast = fast_ema[index - 1]
        prev_slow = slow_ema[index - 1]

        if np.isnan(curr_fast) or np.isnan(curr_slow):
            return "HOLD"
        if np.isnan(prev_fast) or np.isnan(prev_slow):
            return "HOLD"

        cross_above = prev_fast <= prev_slow and curr_fast > curr_slow
        cross_below = prev_fast >= prev_slow and curr_fast < curr_slow

        if cross_above and cfg.trade_direction in ("both", "long_only"):
            return "BUY"

        if cross_below and cfg.trade_direction in ("both", "short_only"):
            return "SELL"

        return "HOLD"

    # ─── Indicator overlay ──────────────────────────────────────
    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """Return EMA values for price chart overlay."""
        cfg = self.config
        prices = data[cfg.source]
        fast_ema = self._compute_ema(prices, cfg.fast_period)
        slow_ema = self._compute_ema(prices, cfg.slow_period)

        def to_list(arr):
            return [None if np.isnan(v) else round(float(v), 6) for v in arr]

        return {
            f"EMA {cfg.fast_period}": to_list(fast_ema),
            f"EMA {cfg.slow_period}": to_list(slow_ema),
        }
