"""
Supertrend Strategy — Dead Template Implementation
====================================================
Strategy type: indicator
Exact port of TradingView Pine Script v4 Supertrend logic.

Signal: BUY  when trend flips from -1 to 1  (bearish → bullish)
        SELL when trend flips from  1 to -1 (bullish → bearish)

Layer 1 (Signal):  on_start() pre-computes supertrend → on_bar() reads cache
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

STRATEGY_NAME        = "Supertrend"
STRATEGY_DESCRIPTION = "Classic Supertrend indicator (TV Pine Script logic). BUY when flips green, SELL when flips red."
STRATEGY_VERSION     = "2.0"
STRATEGY_TYPE        = "indicator"


# ════════════════════════════════════════════════════════════════════
# [B] SETTINGS SCHEMA
# ════════════════════════════════════════════════════════════════════

class StrategySettings(StrategyConfig):
    """Supertrend configuration."""

    atr_period: int = Field(
        10, ge=2, le=200,
        description="ATR Period",
        json_schema_extra={"step": 1},
    )
    multiplier: float = Field(
        3.0, ge=0.5, le=20.0,
        description="Supertrend Multiplier",
        json_schema_extra={"step": 0.1},
    )
    trade_direction: Literal["both", "long_only", "short_only"] = Field(
        "both",
        description="Trade Direction",
    )


# ════════════════════════════════════════════════════════════════════
# [C] STRATEGY CLASS
# ════════════════════════════════════════════════════════════════════

class SupertrendStrategy(BaseStrategy):

    name         = STRATEGY_NAME
    description  = STRATEGY_DESCRIPTION
    version      = STRATEGY_VERSION
    strategy_type = STRATEGY_TYPE
    config_model = StrategySettings


    # ════════════════════════════════════════════════════════════════
    # [D] ON_START — Pre-compute supertrend on full dataset
    # ════════════════════════════════════════════════════════════════

    def on_start(self, data: pd.DataFrame):
        cfg = self.config
        self._cache = {}

        # Compute supertrend using the built-in helper
        st_line, st_dir = self._supertrend(data, cfg.atr_period, cfg.multiplier)
        self._cache["st_line"]     = st_line
        self._cache["st_direction"] = st_dir

        # Also compute the raw up/down bands for visualization
        up, dn, trend = self._compute_supertrend_detail(data, cfg.atr_period, cfg.multiplier)
        self._cache["st_up"]    = up
        self._cache["st_dn"]    = dn
        self._cache["st_trend"] = trend

        self._warmup = cfg.atr_period + 1


    def _compute_supertrend_detail(self, data: pd.DataFrame, period: int, multiplier: float):
        """Full Pine Script port returning up/dn/trend arrays for visualization."""
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        n = len(close)

        hl2 = (high + low) / 2.0

        # ATR (Wilder's)
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
        atr = np.full(n, np.nan)
        if n >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

        up    = np.full(n, np.nan)
        dn    = np.full(n, np.nan)
        trend = np.zeros(n, dtype=int)

        for i in range(n):
            if np.isnan(atr[i]):
                up[i] = hl2[i] - multiplier * (high[i] - low[i])
                dn[i] = hl2[i] + multiplier * (high[i] - low[i])
                trend[i] = 1 if i == 0 else trend[i-1]
                continue

            basic_up = hl2[i] - multiplier * atr[i]
            basic_dn = hl2[i] + multiplier * atr[i]

            if i == 0:
                up[i], dn[i], trend[i] = basic_up, basic_dn, 1
            else:
                up[i] = max(basic_up, up[i-1]) if close[i-1] > up[i-1] else basic_up
                dn[i] = min(basic_dn, dn[i-1]) if close[i-1] < dn[i-1] else basic_dn

                if trend[i-1] == -1 and close[i] > dn[i-1]:
                    trend[i] = 1
                elif trend[i-1] == 1 and close[i] < up[i-1]:
                    trend[i] = -1
                else:
                    trend[i] = trend[i-1]

        return up, dn, trend


    # ════════════════════════════════════════════════════════════════
    # [F] ON_BAR — Signal generation (reads from cache only)
    # ════════════════════════════════════════════════════════════════

    def on_bar(self, index: int, data: pd.DataFrame):
        cfg   = self.config
        cache = self._cache

        if index < self._warmup:
            return "HOLD"

        trend = cache.get("st_trend")
        if trend is None:
            return "HOLD"

        curr_trend = trend[index]
        prev_trend = trend[index - 1]

        buy_signal  = curr_trend == 1  and prev_trend == -1
        sell_signal = curr_trend == -1 and prev_trend == 1

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
    # [G] VISUALIZATION
    # ════════════════════════════════════════════════════════════════

    def get_indicator_data(self, data: pd.DataFrame) -> list:
        cfg   = self.config
        cache = self._cache
        plots = []

        up    = cache.get("st_up")
        dn    = cache.get("st_dn")
        trend = cache.get("st_trend")

        if up is not None and trend is not None:
            # Bullish line (green) — shown when trend == 1
            bull_values = []
            for i in range(len(trend)):
                if trend[i] == 1 and not np.isnan(up[i]):
                    t = data.iloc[i]["time"]
                    bull_values.append({
                        "time": t.isoformat() if hasattr(t, "isoformat") else str(t),
                        "value": round(float(up[i]), 6),
                    })
            if bull_values:
                plots.append(IndicatorPlot(
                    id    = "st_bull",
                    label = f"ST↑ ({cfg.atr_period},{cfg.multiplier})",
                    pane  = "price",
                    type  = "line",
                    color = "#22c55e",
                    values = bull_values,
                    line_width = 2,
                ))

        if dn is not None and trend is not None:
            # Bearish line (red) — shown when trend == -1
            bear_values = []
            for i in range(len(trend)):
                if trend[i] == -1 and not np.isnan(dn[i]):
                    t = data.iloc[i]["time"]
                    bear_values.append({
                        "time": t.isoformat() if hasattr(t, "isoformat") else str(t),
                        "value": round(float(dn[i]), 6),
                    })
            if bear_values:
                plots.append(IndicatorPlot(
                    id    = "st_bear",
                    label = f"ST↓ ({cfg.atr_period},{cfg.multiplier})",
                    pane  = "price",
                    type  = "line",
                    color = "#ef4444",
                    values = bear_values,
                    line_width = 2,
                ))

        return plots
