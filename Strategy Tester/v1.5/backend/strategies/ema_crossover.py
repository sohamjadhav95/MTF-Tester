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

from app.core.strategy_template import BaseStrategy, StrategyConfig


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

    # SL / TP Settings
    sl_type: Literal["fixed_rr", "candle_low", "atr"] = Field(
        "fixed_rr",
        description="Stop Loss Type",
    )
    risk_reward_ratio: float = Field(
        2.0, ge=0.1, le=20.0,
        description="Risk / Reward Ratio (TP = SL distance × R/R)",
        json_schema_extra={"step": 0.1},
    )
    sl_pips: int = Field(
        20, ge=1, le=1000,
        description="Stop Loss (pips) — used by fixed_rr",
        json_schema_extra={"step": 1, "x-visible-when": {"sl_type": ["fixed_rr"]}},
    )
    atr_period: int = Field(
        14, ge=2, le=200,
        description="ATR Period — used by atr",
        json_schema_extra={"step": 1, "x-visible-when": {"sl_type": ["atr"]}},
    )
    atr_sl_multiplier: float = Field(
        1.5, ge=0.1, le=10.0,
        description="ATR SL Multiplier — SL = ATR × this value",
        json_schema_extra={"step": 0.1, "x-visible-when": {"sl_type": ["atr"]}},
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
        "Moving Averages (fast & slow). Configurable SL/TP modes: "
        "fixed R/R, entry candle low/high, or ATR-based."
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

    # ─── ATR Calculation ────────────────────────────────────────
    def _compute_atr(self, data: pd.DataFrame, period: int) -> np.ndarray:
        """Wilder's ATR (same as MT5 / TradingView)."""
        high = data["high"].values.astype(float)
        low = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        n = len(close)

        tr = np.full(n, np.nan)
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        tr[0] = high[0] - low[0]

        atr = np.full(n, np.nan)
        if n >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        return atr

    # ─── SL / TP Calculation ────────────────────────────────────
    def _calc_sl_tp(
        self,
        direction: str,
        entry_price: float,
        bar_low: float,
        bar_high: float,
        atr_val: float,
    ):
        """Compute (sl_price, tp_price) based on sl_type setting."""
        cfg = self.config
        pip_value = getattr(self, "_pip_value", 0.0001)

        if cfg.sl_type == "fixed_rr":
            sl_distance = cfg.sl_pips * pip_value
            if direction == "BUY":
                sl = entry_price - sl_distance
                tp = entry_price + sl_distance * cfg.risk_reward_ratio
            else:
                sl = entry_price + sl_distance
                tp = entry_price - sl_distance * cfg.risk_reward_ratio

        elif cfg.sl_type == "candle_low":
            if direction == "BUY":
                sl = bar_low - pip_value
                sl_distance = entry_price - sl
                tp = entry_price + sl_distance * cfg.risk_reward_ratio
            else:
                sl = bar_high + pip_value
                sl_distance = sl - entry_price
                tp = entry_price - sl_distance * cfg.risk_reward_ratio

        elif cfg.sl_type == "atr":
            if not np.isnan(atr_val) and atr_val > 0:
                sl_distance = atr_val * cfg.atr_sl_multiplier
            else:
                sl_distance = pip_value * 20  # fallback: 20 pips
            if direction == "BUY":
                sl = entry_price - sl_distance
                tp = entry_price + sl_distance * cfg.risk_reward_ratio
            else:
                sl = entry_price + sl_distance
                tp = entry_price - sl_distance * cfg.risk_reward_ratio

        else:
            return None, None

        return round(sl, 6), round(tp, 6)

    # ─── on_bar ─────────────────────────────────────────────────
    def on_bar(self, index: int, data: pd.DataFrame):
        """
        Generate signal based on EMA crossover.
        Returns either 'HOLD' or a tuple (signal, sl_price, tp_price).
        """
        cfg = self.config
        atr_period = cfg.atr_period if cfg.sl_type == "atr" else 14
        min_bars = max(cfg.fast_period, cfg.slow_period, atr_period if cfg.sl_type == "atr" else 0) + 1

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

        entry_price = float(data["close"].iloc[index])
        bar_low = float(data["low"].iloc[index])
        bar_high = float(data["high"].iloc[index])

        # ATR value at current bar (if needed)
        atr_val = 0.0
        if cfg.sl_type == "atr":
            atr_arr = self._compute_atr(data, atr_period)
            atr_val = float(atr_arr[index]) if not np.isnan(atr_arr[index]) else 0.0

        if cross_above and cfg.trade_direction in ("both", "long_only"):
            sl, tp = self._calc_sl_tp("BUY", entry_price, bar_low, bar_high, atr_val)
            return ("BUY", sl, tp)

        if cross_below and cfg.trade_direction in ("both", "short_only"):
            sl, tp = self._calc_sl_tp("SELL", entry_price, bar_low, bar_high, atr_val)
            return ("SELL", sl, tp)

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
