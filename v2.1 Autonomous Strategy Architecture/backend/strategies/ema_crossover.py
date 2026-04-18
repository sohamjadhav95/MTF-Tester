"""
EMA Crossover Strategy
=======================
Signals when fast EMA crosses above/below slow EMA.
Operates on a user-selected timeframe (resampled from M1 data internally).
"""

from __future__ import annotations
from typing import Literal
import numpy as np
import pandas as pd
from pydantic import Field
from ._template import BaseStrategy, StrategyConfig


class EMAConfig(StrategyConfig):
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4"] = Field(
        "M15", description="Operating Timeframe"
    )
    fast_period: int = Field(10, ge=2, le=500, description="Fast EMA Period")
    slow_period: int = Field(50, ge=2, le=500, description="Slow EMA Period")
    source: Literal["open", "high", "low", "close"] = Field("close", description="Price Source")
    trade_direction: Literal["both", "long_only", "short_only"] = Field("both", description="Trade Direction")


TF_RULE = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h"}


class EMACrossover(BaseStrategy):
    name = "EMA Crossover"
    description = "Fast/slow EMA crossover signals on a user-selected timeframe."
    config_model = EMAConfig

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
        prices = htf[cfg.source].values.astype(float)
        fast = self._ema(prices, cfg.fast_period)
        slow = self._ema(prices, cfg.slow_period)
        m1_to_htf = self._m1_to_htf_index(data["time"], htf["time"])
        self._cache = {
            "fast": fast, "slow": slow,
            "m1_to_htf": m1_to_htf,
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
        if cross_up and cfg.trade_direction in ("both", "long_only"):
            return "BUY"
        if cross_dn and cfg.trade_direction in ("both", "short_only"):
            return "SELL"
        return "HOLD"

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        cache = self._cache
        if not cache:
            return {}
        cfg = self.config
        n = len(data)
        fast_m1 = [None] * n
        slow_m1 = [None] * n
        for i, h_idx in enumerate(cache["m1_to_htf"]):
            if i < n and 0 <= h_idx < len(cache["fast"]):
                v = cache["fast"][h_idx]
                fast_m1[i] = None if np.isnan(v) else round(float(v), 6)
                v2 = cache["slow"][h_idx]
                slow_m1[i] = None if np.isnan(v2) else round(float(v2), 6)
        return {f"EMA {cfg.fast_period}": fast_m1, f"EMA {cfg.slow_period}": slow_m1}
