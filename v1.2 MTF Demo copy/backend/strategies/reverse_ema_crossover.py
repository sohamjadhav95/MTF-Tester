"""
Reverse EMA Crossover Strategy
================================
Identical to EMA Crossover but with inverted signal logic:
  - BUY  when fast EMA crosses BELOW slow EMA (counter-trend)
  - SELL when fast EMA crosses ABOVE slow EMA (counter-trend)

Useful for mean-reversion testing or comparing with standard EMA.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from app.core.strategy_template import BaseStrategy, StrategyConfig


# ─── Pydantic Config ────────────────────────────────────────────
class ReverseEMAConfig(StrategyConfig):
    """Typed configuration for the Reverse EMA Crossover strategy."""

    fast_period: int = Field(
        9, ge=2, le=500,
        description="Fast EMA Period",
        json_schema_extra={"step": 1},
    )
    slow_period: int = Field(
        21, ge=2, le=500,
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
class ReverseEMACrossover(BaseStrategy):
    """
    Reverse EMA Crossover — counter-trend version of EMA Crossover.

    Signal logic is inverted:
      BUY  when fast EMA crosses BELOW slow EMA (normal SELL signal)
      SELL when fast EMA crosses ABOVE slow EMA (normal BUY signal)

    All SL/TP modes and settings are identical to EMA Crossover.
    """

    name = "Reverse EMA Crossover"
    description = (
        "Counter-trend EMA strategy — opens BUY when fast crosses below slow "
        "and SELL when fast crosses above slow. Inverted EMA Crossover logic. "
        "No SL/TP — pure signal only."
    )
    config_model = ReverseEMAConfig

    # ─── EMA Calculation ────────────────────────────────────────
    def _compute_ema(self, series: pd.Series, period: int) -> np.ndarray:
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

        # ── REVERSED: cross_above triggers SELL, cross_below triggers BUY ──
        cross_above = prev_fast <= prev_slow and curr_fast > curr_slow  # → SELL
        cross_below = prev_fast >= prev_slow and curr_fast < curr_slow  # → BUY

        # cross_below → BUY (reversed)
        if cross_below and cfg.trade_direction in ("both", "long_only"):
            return "BUY"

        # cross_above → SELL (reversed)
        if cross_above and cfg.trade_direction in ("both", "short_only"):
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
