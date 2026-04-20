from strategies._template import BaseStrategy, StrategyConfig, Signal, HOLD, TF_DURATION
from pydantic import Field
from typing import Literal
import numpy as np
import pandas as pd


# ─── Configuration ──────────────────────────────────────────
class SupertrendConfig(StrategyConfig):
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1"] = Field(
        "M15", description="Operating Timeframe"
    )
    atr_period: int = Field(10, ge=2, le=50, description="ATR Lookback Period")
    multiplier: float = Field(3.0, ge=0.1, le=10.0, description="ATR Multiplier")
    direction: Literal["both", "long_only", "short_only"] = Field(
        "both", description="Allowed Trade Direction"
    )


# ─── Strategy ───────────────────────────────────────────────
class Supertrend(BaseStrategy):
    name = "Supertrend (Native Build)"
    description = "Flawless Supertrend indicator deployed with autonomous multi-timeframe precision."
    config_model = SupertrendConfig

    def on_start(self, data: pd.DataFrame):
        cfg = self.config

        # 1. MTF Resampling
        tf_map = {
            "M1": "1min", "M5": "5min", "M15": "15min", 
            "M30": "30min", "H1": "1h", "H4": "4h", "D1": "1D"
        }
        rule = tf_map.get(cfg.timeframe, "15min")
        htf = self._resample(data, rule)

        h = htf["high"].values.astype(float)
        l = htf["low"].values.astype(float)
        c = htf["close"].values.astype(float)
        n = len(c)

        target_dir = np.zeros(n)
        st_line = np.zeros(n)

        # 2. Compute TradingView Parity Supertrend
        if n > cfg.atr_period:
            
            # TR Calculation
            tr = np.zeros(n)
            for i in range(1, n):
                tr[i] = max(
                    h[i] - l[i], 
                    abs(h[i] - c[i-1]), 
                    abs(l[i] - c[i-1])
                )

            # RMA (Wilder's Smoothing)
            atr = np.zeros(n)
            period = cfg.atr_period
            atr[period] = np.mean(tr[1:period+1])
            for i in range(period + 1, n):
                atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period

            hl2 = (h + l) / 2
            upper = hl2 + (cfg.multiplier * atr)
            lower = hl2 - (cfg.multiplier * atr)

            trend_dir = 1  # 1: Bullish, -1: Bearish

            for i in range(1, n):
                if np.isnan(atr[i]) or atr[i] == 0:
                    continue

                # Bands can only narrow
                if c[i-1] > lower[i-1]:
                    lower[i] = max(lower[i], lower[i-1])
                if c[i-1] < upper[i-1]:
                    upper[i] = min(upper[i], upper[i-1])

                # Flip Check
                if trend_dir == 1:
                    if c[i] < lower[i]:
                        trend_dir = -1
                        st_line[i] = upper[i]
                    else:
                        st_line[i] = lower[i]
                else:
                    if c[i] > upper[i]:
                        trend_dir = 1
                        st_line[i] = lower[i]
                    else:
                        st_line[i] = upper[i]

                target_dir[i] = trend_dir

        # 3. Align HTF arrays exactly to the M1 data grid
        # This completely flattens MTF logic allowing O(1) lookups in on_bar
        m_len = len(data)
        m1_st_dir = np.full(m_len, np.nan)
        m1_st_line = np.full(m_len, np.nan)

        htf_duration = TF_DURATION.get(cfg.timeframe, pd.Timedelta(minutes=15))
        m1_to_htf = self._m1_to_completed_htf_index(data["time"], htf["time"], htf_duration)

        for i in range(m_len):
            h_idx = m1_to_htf[i]
            if h_idx != -1:
                m1_st_dir[i] = target_dir[h_idx]
                m1_st_line[i] = st_line[h_idx]

        self._cache = {
            "dir": m1_st_dir,
            "line": m1_st_line,
        }

    def on_bar(self, index: int, data: pd.DataFrame):
        c = self._cache
        
        # Buffer safety
        if index < 1 or np.isnan(c["dir"][index]) or np.isnan(c["dir"][index - 1]):
            return HOLD

        curr_dir = c["dir"][index]
        prev_dir = c["dir"][index - 1]

        cfg = self.config

        # ─── Flip Detection ───
        # By iterating on the M1 array, this inherently blocks spam.
        # It guarantees triggers occur strictly on the 1-minute tick the trend formally flipped.
        if curr_dir == 1 and prev_dir == -1:
            if cfg.direction in ("both", "long_only"):
                return Signal("BUY", sl=c["line"][index])

        elif curr_dir == -1 and prev_dir == 1:
            if cfg.direction in ("both", "short_only"):
                return Signal("SELL", sl=c["line"][index])

        return HOLD
