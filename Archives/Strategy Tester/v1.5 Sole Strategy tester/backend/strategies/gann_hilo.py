"""
Gann HiLo Strategy
======================
Implements TradingView Gann High Low Indicator logic:
  - BUY when the first candle closes completely above the Gann HiLo line (low > line).
  - SELL when the first candle closes completely below the Gann HiLo line (high < line).

Enhanced with three SL/TP modes:
  - candle_low  : SL at the entry bar's low (BUY) or high (SELL); TP = SL × R/R
  - fixed_rr    : SL at fixed pips; TP = SL distance × R/R ratio
  - atr         : SL = entry ± ATR × multiplier; TP = SL × R/R
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from app.core.strategy_template import BaseStrategy, StrategyConfig


# ─── Pydantic Config (Single Source of Truth) ───────────────────
class GannHiLoConfig(StrategyConfig):
    """Typed, validated configuration for the Gann HiLo strategy."""

    # Gann Settings
    high_period: int = Field(
        13, ge=2, le=500,
        description="High Period",
        json_schema_extra={"step": 1},
    )
    low_period: int = Field(
        21, ge=2, le=500,
        description="Low Period",
        json_schema_extra={"step": 1},
    )
    trade_direction: Literal["both", "long_only", "short_only"] = Field(
        "both",
        description="Trade Direction",
    )

    # SL / TP Settings
    sl_type: Literal["candle_low", "fixed_rr", "atr"] = Field(
        "candle_low",
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
class GannHiLoStrategy(BaseStrategy):
    """
    Gann HiLo Strategy.

    Generates BUY signals when a candle closes completely above the Gann HiLo line
    (i.e., low > line) and the previous candle was touching or below it.
    Generates SELL signals when a candle closes completely below the Gann HiLo line
    (i.e., high < line) and the previous candle was touching or above it.
    """

    name = "Gann HiLo"
    description = (
        "Signals based on the interaction of price with the Gann High Low indicator. "
        "Enters on the first candle not touching the line. "
        "Configurable SL/TP modes."
    )
    config_model = GannHiLoConfig

    # ─── Indicators Calculation ──────────────────────────────────────
    def _compute_sma(self, series: pd.Series, period: int) -> np.ndarray:
        """Standard SMA."""
        return series.rolling(window=period, min_periods=period).mean().values

    def _compute_gann_hilo(self, data: pd.DataFrame, high_period: int, low_period: int) -> np.ndarray:
        """
        Calculates the Gann HiLo line exactly as TradingView does.
        """
        high = data["high"]
        low = data["low"]
        close = data["close"]

        # Calculate SMAs
        sma_high = self._compute_sma(high, high_period)
        sma_low = self._compute_sma(low, low_period)

        # Shift SMAs to get previous values (nz equivalent with NaNs handled by comparison)
        sma_high_prev = pd.Series(sma_high).shift(1).values
        sma_low_prev = pd.Series(sma_low).shift(1).values

        HLd = np.zeros(len(data))
        
        # iff_1 = close < nz(ta.sma(low, LPeriod))[1] ? -1 : 0
        iff_1 = np.where(close.values < sma_low_prev, -1, 0)
        
        # HLd = close > nz(ta.sma(high, HPeriod))[1] ? 1 : iff_1
        HLd = np.where(close.values > sma_high_prev, 1, iff_1)
        
        # HLv = ta.valuewhen(HLd != 0, HLd, 0)
        # We replace 0 with NaN, forward fill, then fill remaining NaNs with 0
        HLv = pd.Series(HLd).replace(0, np.nan).ffill().fillna(0).values

        # HiLo = HLv == -1 ? sma_1 : sma_2
        HiLo = np.where(HLv == -1, sma_high, sma_low)

        return HiLo

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
        Generate signal based on Gann HiLo.
        Returns either 'HOLD' or a tuple (signal, sl_price, tp_price).
        """
        cfg = self.config
        atr_period = cfg.atr_period if cfg.sl_type == "atr" else 14
        min_bars = max(cfg.high_period, cfg.low_period, atr_period if cfg.sl_type == "atr" else 0) + 1

        if len(data) < min_bars:
            return "HOLD"

        hilo = self._compute_gann_hilo(data, cfg.high_period, cfg.low_period)

        curr_hilo = hilo[index]
        prev_hilo = hilo[index - 1]

        if np.isnan(curr_hilo) or np.isnan(prev_hilo):
            return "HOLD"

        curr_low = float(data["low"].iloc[index])
        curr_high = float(data["high"].iloc[index])
        prev_low = float(data["low"].iloc[index - 1])
        prev_high = float(data["high"].iloc[index - 1])
        entry_price = float(data["close"].iloc[index])

        # Entry logic: "Open position at first closing of candle which is not touching GANN HILO line"
        # Not touching and above means: low > line. First time means previous low was <= previous line.
        buy_signal = (curr_low > curr_hilo) and (prev_low <= prev_hilo)
        
        # Not touching and below means: high < line. First time means previous high was >= previous line.
        sell_signal = (curr_high < curr_hilo) and (prev_high >= prev_hilo)

        # ATR value at current bar (if needed)
        atr_val = 0.0
        if cfg.sl_type == "atr":
            atr_arr = self._compute_atr(data, atr_period)
            atr_val = float(atr_arr[index]) if not np.isnan(atr_arr[index]) else 0.0

        if buy_signal and cfg.trade_direction in ("both", "long_only"):
            sl, tp = self._calc_sl_tp("BUY", entry_price, curr_low, curr_high, atr_val)
            return ("BUY", sl, tp)

        if sell_signal and cfg.trade_direction in ("both", "short_only"):
            sl, tp = self._calc_sl_tp("SELL", entry_price, curr_low, curr_high, atr_val)
            return ("SELL", sl, tp)

        return "HOLD"

    # ─── Indicator overlay ──────────────────────────────────────
    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """Return Gann HiLo values for price chart overlay."""
        cfg = self.config
        hilo = self._compute_gann_hilo(data, cfg.high_period, cfg.low_period)

        def to_list(arr):
            return [None if np.isnan(v) else round(float(v), 6) for v in arr]

        return {
            "Gann HiLo": to_list(hilo),
        }
