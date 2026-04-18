"""
Reverse EMA Crossover Strategy
================================
Counter-trend EMA crossover — down cross = BUY, up cross = SELL.
Operates on a user-selected timeframe (resampled from M1 data internally).
"""

from __future__ import annotations
from typing import Literal
import numpy as np
import pandas as pd
from pydantic import Field
from ._template import BaseStrategy, StrategyConfig


class ReverseEMAConfig(StrategyConfig):
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4"] = Field(
        "M15", description="Operating Timeframe"
    )
    fast_period: int = Field(10, ge=2, le=500, description="Fast EMA Period")
    slow_period: int = Field(50, ge=2, le=500, description="Slow EMA Period")
    source: Literal["open", "high", "low", "close"] = Field("close", description="Price Source")
    trade_direction: Literal["both", "long_only", "short_only"] = Field("both", description="Trade Direction")


TF_RULE = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h"}


class ReverseEMACrossover(BaseStrategy):
    name = "Reverse EMA Crossover"
    description = "Counter-trend EMA crossover — down cross = BUY, up cross = SELL."
    config_model = ReverseEMAConfig

    @staticmethod
    def _ema(series: np.ndarray, period: int) -> np.ndarray:
        result = np.full(len(series), np.nan)
        if len(series) < period:
            return result
        k = 2.0 / (period + 1)
        result[period - 1] = np.mean(series[:period])
        for i in range(period, len(series)):
            result[i] = series[i] * k + result[i - 1] * (1 - k)
        return result

    def on_start(self, data: pd.DataFrame) -> None:
        cfg = self.config
        rule = TF_RULE.get(cfg.timeframe, "15min")
        htf = self._resample(data, rule)

        # NEW: derive duration from the config timeframe
        from strategies._template import TF_DURATION
        htf_duration = TF_DURATION.get(cfg.timeframe, pd.Timedelta(minutes=15))

        prices = htf[cfg.source].values.astype(float)
        fast = self._ema(prices, cfg.fast_period)
        slow = self._ema(prices, cfg.slow_period)

        # NEW: use the completed-HTF mapping (no look-ahead)
        m1_to_htf = self._m1_to_completed_htf_index(
            data["time"], htf["time"], htf_duration
        )

        self._cache = {
            "fast": fast, "slow": slow,
            "m1_to_htf": m1_to_htf,
            "htf_times": htf["time"].values,   # NEW: for scanner dedup
            "htf_close": htf["close"].values.astype(float),
        }

    def on_bar(self, index: int, data: pd.DataFrame) -> str | tuple:
        cache = self._cache
        if not cache:
            return "HOLD"
        h_idx = cache["m1_to_htf"][index] if index < len(cache["m1_to_htf"]) else -1
        if h_idx < 1:
            return "HOLD"
        fast, slow = cache["fast"], cache["slow"]
        if np.isnan(fast[h_idx]) or np.isnan(slow[h_idx]):
            return "HOLD"
        if np.isnan(fast[h_idx - 1]) or np.isnan(slow[h_idx - 1]):
            return "HOLD"
        cross_up = fast[h_idx - 1] <= slow[h_idx - 1] and fast[h_idx] > slow[h_idx]
        cross_dn = fast[h_idx - 1] >= slow[h_idx - 1] and fast[h_idx] < slow[h_idx]
        cfg = self.config
        # REVERSED: cross_up → SELL, cross_dn → BUY
        if cross_dn and cfg.trade_direction in ("both", "long_only"):
            return "BUY"
        if cross_up and cfg.trade_direction in ("both", "short_only"):
            return "SELL"
        return "HOLD"

