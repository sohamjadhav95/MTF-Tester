"""
Supertrend Strategy
====================
Classic Supertrend indicator — computes on user-selected timeframe from M1 data.
"""

from __future__ import annotations
from typing import Literal
import numpy as np
import pandas as pd
from pydantic import Field
from ._template import BaseStrategy, StrategyConfig


class SupertrendConfig(StrategyConfig):
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4"] = Field("M15", description="Operating Timeframe")
    atr_period: int = Field(10, ge=2, le=100, description="ATR Period")
    multiplier: float = Field(3.0, ge=0.1, le=20.0, description="ATR Multiplier")
    trade_direction: Literal["both", "long_only", "short_only"] = Field("both", description="Trade Direction")


TF_RULE = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h", "H4": "4h"}


class Supertrend(BaseStrategy):
    name = "Supertrend"
    description = "Supertrend indicator signals on a user-selected timeframe."
    config_model = SupertrendConfig

    @staticmethod
    def _compute_supertrend(high, low, close, atr_period, multiplier):
        n = len(close)
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

        atr = np.full(n, np.nan)
        if n >= atr_period:
            atr[atr_period - 1] = np.mean(tr[:atr_period])
            for i in range(atr_period, n):
                atr[i] = (atr[i - 1] * (atr_period - 1) + tr[i]) / atr_period

        hl2 = (high + low) / 2.0
        upper_band = hl2 + multiplier * atr
        lower_band = hl2 - multiplier * atr

        supertrend = np.full(n, np.nan)
        direction = np.zeros(n, dtype=int)  # 1 = up (bullish), -1 = down (bearish)

        for i in range(1, n):
            if np.isnan(atr[i]):
                continue
            prev_upper = upper_band[i - 1] if not np.isnan(supertrend[i - 1]) else upper_band[i]
            prev_lower = lower_band[i - 1] if not np.isnan(supertrend[i - 1]) else lower_band[i]

            # ✓ CORRECT: bands can only narrow, never widen
            upper_band[i] = min(upper_band[i], prev_upper)
            lower_band[i] = max(lower_band[i], prev_lower)

            prev_dir = direction[i - 1]
            if np.isnan(supertrend[i - 1]):
                direction[i] = 1
                supertrend[i] = lower_band[i]
            elif prev_dir == 1:
                if close[i] < supertrend[i - 1]:
                    direction[i] = -1
                    supertrend[i] = upper_band[i]
                else:
                    direction[i] = 1
                    supertrend[i] = lower_band[i]
            else:
                if close[i] > supertrend[i - 1]:
                    direction[i] = 1
                    supertrend[i] = lower_band[i]
                else:
                    direction[i] = -1
                    supertrend[i] = upper_band[i]

        return supertrend, direction

    def on_start(self, data: pd.DataFrame) -> None:
        cfg = self.config
        rule = TF_RULE.get(cfg.timeframe, "15min")
        htf = self._resample(data, rule)
        h = htf["high"].values.astype(float)
        l = htf["low"].values.astype(float)
        c = htf["close"].values.astype(float)
        st, direction = self._compute_supertrend(h, l, c, cfg.atr_period, cfg.multiplier)
        m1_to_htf = self._m1_to_htf_index(data["time"], htf["time"])
        self._cache = {"st": st, "direction": direction, "m1_to_htf": m1_to_htf}

    def on_bar(self, index: int, data: pd.DataFrame) -> str | tuple:
        cache = self._cache
        if not cache:
            return "HOLD"
        h_idx = cache["m1_to_htf"][index] if index < len(cache["m1_to_htf"]) else -1
        if h_idx < 1:
            return "HOLD"
        d = cache["direction"]
        if d[h_idx] == 1 and d[h_idx - 1] == -1:
            cfg = self.config
            if cfg.trade_direction in ("both", "long_only"):
                return "BUY"
        if d[h_idx] == -1 and d[h_idx - 1] == 1:
            cfg = self.config
            if cfg.trade_direction in ("both", "short_only"):
                return "SELL"
        return "HOLD"

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        cache = self._cache
        if not cache:
            return {}
        n = len(data)
        st_m1 = [None] * n
        for i, h_idx in enumerate(cache["m1_to_htf"]):
            if i < n and 0 <= h_idx < len(cache["st"]):
                v = cache["st"][h_idx]
                st_m1[i] = None if np.isnan(v) else round(float(v), 6)
        return {"Supertrend": st_m1}
