from strategies._template import BaseStrategy, StrategyConfig, Signal, HOLD
from pydantic import Field
from typing import Literal
import numpy as np
import pandas as pd


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
class LiquidityConfig(StrategyConfig):
    swing_window: int = Field(3, ge=1, le=20)
    rr_ratio: float = Field(2.0, ge=0.5, le=10.0)
    sl_type: Literal["swing", "atr"] = Field("swing")
    atr_period: int = Field(14, ge=2, le=100)
    atr_mult: float = Field(1.5, ge=0.5, le=5.0)
    direction: Literal["both", "long_only", "short_only"] = Field("both")


# ─────────────────────────────────────────────
# STRATEGY
# ─────────────────────────────────────────────
class LiquiditySweepMSS(BaseStrategy):
    name = "Liquidity Sweep + MSS"
    description = "Liquidity grab + structure shift confirmation"
    config_model = LiquidityConfig

    # ─────────────────────────────────────────
    # ON START (FULL PRECOMPUTE)
    # ─────────────────────────────────────────
    def on_start(self, data: pd.DataFrame):
        cfg = self.config

        high = data["high"].values.astype(float)
        low = data["low"].values.astype(float)
        close = data["close"].values.astype(float)

        n = len(data)

        # ─── Swing Detection ───
        swing_high = np.full(n, np.nan)
        swing_low = np.full(n, np.nan)

        w = cfg.swing_window

        for i in range(w, n - w):
            if high[i] == np.max(high[i - w:i + w + 1]):
                swing_high[i + w] = high[i]
            if low[i] == np.min(low[i - w:i + w + 1]):
                swing_low[i + w] = low[i]

        # Forward fill to maintain the last known structure level at any given bar
        last_swing_high = pd.Series(swing_high).ffill().values
        last_swing_low = pd.Series(swing_low).ffill().values

        # ─── ATR ───
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        atr = np.full(n, np.nan)
        p = cfg.atr_period

        if n >= p:
            atr[p - 1] = np.mean(tr[:p])
            for i in range(p, n):
                atr[i] = (atr[i - 1] * (p - 1) + tr[i]) / p

        self._cache = {
            "high": high,
            "low": low,
            "close": close,
            "last_swing_high": last_swing_high,
            "last_swing_low": last_swing_low,
            "atr": atr,
        }

        # ─── Persistent State ───
        if not self.state:
            self.state = {
                "sweep_dir": None,
                "sweep_idx": -1,
            }

    # ─────────────────────────────────────────
    # ON BAR (O(1) LOGIC ONLY)
    # ─────────────────────────────────────────
    def on_bar(self, index: int, data: pd.DataFrame):
        cfg = self.config
        c = self._cache

        if index < 10:
            return HOLD

        high = c["high"]
        low = c["low"]
        close = c["close"]
        last_high_arr = c["last_swing_high"]
        last_low_arr = c["last_swing_low"]
        atr = c["atr"]

        st = self.state

        last_high = last_high_arr[index]
        last_low = last_low_arr[index]

        if np.isnan(last_high) or np.isnan(last_low):
            return HOLD

        # ───────────────────────────────
        # 1. LIQUIDITY SWEEP
        # ───────────────────────────────
        if high[index] > last_high and close[index] < last_high:
            st["sweep_dir"] = "SELL"
            st["sweep_idx"] = index

        elif low[index] < last_low and close[index] > last_low:
            st["sweep_dir"] = "BUY"
            st["sweep_idx"] = index

        direction = st["sweep_dir"]

        if direction is None:
            return HOLD

        # delay to avoid same-candle triggers
        if index - st["sweep_idx"] < 2:
            return HOLD

        entry = close[index]

        # ─── BUY ───
        if direction == "BUY" and cfg.direction != "short_only":

            if close[index] > last_high:

                if cfg.sl_type == "swing":
                    sl = last_low
                else:
                    if np.isnan(atr[index]):
                        return HOLD
                    sl = entry - atr[index] * cfg.atr_mult

                if sl is None or sl <= 0 or sl >= entry:
                    return HOLD

                tp = entry + (entry - sl) * cfg.rr_ratio

                st["sweep_dir"] = None

                return Signal("BUY", sl=sl, tp=tp)

        # ─── SELL ───
        if direction == "SELL" and cfg.direction != "long_only":

            if close[index] < last_low:

                if cfg.sl_type == "swing":
                    sl = last_high
                else:
                    if np.isnan(atr[index]):
                        return HOLD
                    sl = entry + atr[index] * cfg.atr_mult

                if sl is None or sl <= 0 or sl <= entry:
                    return HOLD

                tp = entry - (sl - entry) * cfg.rr_ratio

                st["sweep_dir"] = None

                return Signal("SELL", sl=sl, tp=tp)

        return HOLD