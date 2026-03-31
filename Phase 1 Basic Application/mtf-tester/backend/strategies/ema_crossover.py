"""
EMA Crossover Strategy — Dead Template Implementation
======================================================
Strategy type: indicator
Signal: BUY when fast EMA crosses above slow EMA
        SELL when fast EMA crosses below slow EMA

Layer 1 (Signal):  on_start() pre-computes EMAs → on_bar() reads cache
Layer 2 (Visual):  get_indicator_data() returns IndicatorPlot list
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from strategies._template import BaseStrategy, StrategyConfig, IndicatorPlot


# ════════════════════════════════════════════════════════════════════
# [A] STRATEGY METADATA
# ════════════════════════════════════════════════════════════════════

STRATEGY_NAME        = "EMA Crossover"
STRATEGY_DESCRIPTION = "Generates signals based on the crossover of two Exponential Moving Averages (fast & slow)."
STRATEGY_VERSION     = "2.0"
STRATEGY_TYPE        = "indicator"


# ════════════════════════════════════════════════════════════════════
# [B] SETTINGS SCHEMA
# ════════════════════════════════════════════════════════════════════

class StrategySettings(StrategyConfig):
    """EMA Crossover configuration."""

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


# ════════════════════════════════════════════════════════════════════
# [C] STRATEGY CLASS
# ════════════════════════════════════════════════════════════════════

class EMACrossover(BaseStrategy):

    name         = STRATEGY_NAME
    description  = STRATEGY_DESCRIPTION
    version      = STRATEGY_VERSION
    strategy_type = STRATEGY_TYPE
    config_model = StrategySettings


    # ════════════════════════════════════════════════════════════════
    # [D] ON_START — Pre-compute ALL indicators
    # ════════════════════════════════════════════════════════════════

    def on_start(self, data: pd.DataFrame):
        cfg = self.config
        self._cache = {}

        # Compute EMAs once on the full dataset
        self._cache["ema_fast"] = self._ema(data[cfg.source], cfg.fast_period)
        self._cache["ema_slow"] = self._ema(data[cfg.source], cfg.slow_period)

        # Auto-calculate warmup
        self._warmup = self._calculate_warmup(cfg)


    # ════════════════════════════════════════════════════════════════
    # [F] ON_BAR — Signal generation (reads from cache only)
    # ════════════════════════════════════════════════════════════════

    def on_bar(self, index: int, data: pd.DataFrame):
        cfg   = self.config
        cache = self._cache

        # 1. Warmup guard
        if index < self._warmup:
            return "HOLD"

        # 2. NaN guard
        ema_fast = cache.get("ema_fast")
        ema_slow = cache.get("ema_slow")
        if ema_fast is None or ema_slow is None:
            return "HOLD"

        curr_fast = ema_fast[index]
        curr_slow = ema_slow[index]
        prev_fast = ema_fast[index - 1]
        prev_slow = ema_slow[index - 1]

        if any(np.isnan(v) for v in [curr_fast, curr_slow, prev_fast, prev_slow]):
            return "HOLD"

        # 3. Entry conditions
        buy_signal  = prev_fast <= prev_slow and curr_fast > curr_slow
        sell_signal = prev_fast >= prev_slow and curr_fast < curr_slow

        # Direction filter
        if cfg.trade_direction == "long_only":
            sell_signal = False
        elif cfg.trade_direction == "short_only":
            buy_signal = False

        if buy_signal:
            return "BUY"
        if sell_signal:
            return "SELL"

        return "HOLD"


    # ════════════════════════════════════════════════════════════════
    # [G] VISUALIZATION — IndicatorPlot list for chart rendering
    # ════════════════════════════════════════════════════════════════

    def get_indicator_data(self, data: pd.DataFrame) -> list:
        cfg   = self.config
        cache = self._cache
        plots = []

        if cache.get("ema_fast") is not None:
            plots.append(IndicatorPlot(
                id     = "ema_fast",
                label  = f"EMA {cfg.fast_period}",
                pane   = "price",
                type   = "line",
                color  = "#3b82f6",
                values = self._to_chart_values(data, cache["ema_fast"]),
            ))
        if cache.get("ema_slow") is not None:
            plots.append(IndicatorPlot(
                id     = "ema_slow",
                label  = f"EMA {cfg.slow_period}",
                pane   = "price",
                type   = "line",
                color  = "#f59e0b",
                values = self._to_chart_values(data, cache["ema_slow"]),
            ))

        return plots
