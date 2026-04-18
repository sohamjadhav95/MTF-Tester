"""
VWAP Cross Strategy
====================
Signals when price crosses above/below VWAP.
Computed on user-selected timeframe from M1 data.
"""

from __future__ import annotations
from typing import Literal
import numpy as np
import pandas as pd
from pydantic import Field
from ._template import BaseStrategy, StrategyConfig


class VWAPConfig(StrategyConfig):
    timeframe: Literal["M1", "M5", "M15", "M30", "H1"] = Field("M5", description="Operating Timeframe")
    rr_ratio: float = Field(2.0, ge=0.1, le=20.0, description="Risk/Reward Ratio")
    atr_period: int = Field(14, ge=2, le=100, description="ATR Period (for SL)")
    trade_direction: Literal["both", "long_only", "short_only"] = Field("both", description="Trade Direction")


TF_RULE = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h"}


class VWAPCrossStrategy(BaseStrategy):
    name = "VWAP Cross"
    description = "VWAP cross signals with ATR-based SL/TP on a user-selected timeframe."
    config_model = VWAPConfig

    def on_start(self, data: pd.DataFrame) -> None:
        cfg = self.config
        rule = TF_RULE.get(cfg.timeframe, "5min")
        htf = self._resample(data, rule)

        # NEW: derive duration from the config timeframe
        from strategies._template import TF_DURATION
        htf_duration = TF_DURATION.get(cfg.timeframe, pd.Timedelta(minutes=5))

        close = htf["close"].values.astype(float)
        high = htf["high"].values.astype(float)
        low = htf["low"].values.astype(float)
        volume = htf["volume"].values.astype(float)
        n = len(close)

        # VWAP: session-aware — resets at midnight UTC each day
        typical = (high + low + close) / 3.0
        tpv = typical * volume

        vwap = np.full(len(close), np.nan)
        cum_pv_session = 0.0
        cum_v_session  = 0.0
        prev_date = None

        htf_times = htf["time"].values  # numpy datetime64 array

        for i in range(len(close)):
            t = pd.Timestamp(htf_times[i])
            current_date = t.date()

            # Reset at session boundary (new trading day)
            if current_date != prev_date:
                cum_pv_session = 0.0
                cum_v_session  = 0.0
                prev_date = current_date

            cum_pv_session += tpv[i]
            cum_v_session  += volume[i]

            if cum_v_session > 0:
                vwap[i] = cum_pv_session / cum_v_session

        # ATR (Wilder)
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        atr = np.full(n, np.nan)
        if n >= cfg.atr_period:
            atr[cfg.atr_period - 1] = np.mean(tr[:cfg.atr_period])
            for i in range(cfg.atr_period, n):
                atr[i] = (atr[i - 1] * (cfg.atr_period - 1) + tr[i]) / cfg.atr_period

        # NEW: use the completed-HTF mapping
        m1_to_htf = self._m1_to_completed_htf_index(
            data["time"], htf["time"], htf_duration
        )

        self._cache = {
            "vwap": vwap, "atr": atr, "close": close, 
            "m1_to_htf": m1_to_htf,
            "htf_times": htf["time"].values,
        }

    def on_bar(self, index: int, data: pd.DataFrame) -> str | tuple:
        cache = self._cache
        if not cache:
            return "HOLD"
        h_idx = cache["m1_to_htf"][index] if index < len(cache["m1_to_htf"]) else -1
        if h_idx < 1:
            return "HOLD"
        vwap = cache["vwap"]
        close = cache["close"]
        atr = cache["atr"]
        if np.isnan(vwap[h_idx]) or np.isnan(atr[h_idx]):
            return "HOLD"
        cross_above = close[h_idx - 1] < vwap[h_idx - 1] and close[h_idx] >= vwap[h_idx]
        cross_below = close[h_idx - 1] > vwap[h_idx - 1] and close[h_idx] <= vwap[h_idx]
        cfg = self.config
        entry = close[h_idx]
        a = atr[h_idx]
        if cross_above and cfg.trade_direction in ("both", "long_only"):
            sl = round(entry - a, 6)
            tp = round(entry + a * cfg.rr_ratio, 6)
            return ("BUY", sl, tp)
        if cross_below and cfg.trade_direction in ("both", "short_only"):
            sl = round(entry + a, 6)
            tp = round(entry - a * cfg.rr_ratio, 6)
            return ("SELL", sl, tp)
        return "HOLD"

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        cache = self._cache
        if not cache:
            return {}
        n = len(data)
        vwap_m1 = [None] * n
        for i, h_idx in enumerate(cache["m1_to_htf"]):
            if i < n and 0 <= h_idx < len(cache["vwap"]):
                v = cache["vwap"][h_idx]
                vwap_m1[i] = None if np.isnan(v) else round(float(v), 6)
        return {"VWAP": vwap_m1}