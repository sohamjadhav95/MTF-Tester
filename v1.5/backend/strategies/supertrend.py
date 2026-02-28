"""
Supertrend Strategy — exact port of the classic TradingView Pine Script v4 logic.

Pine Script reference:
  up  = hl2 - (Multiplier * atr)
  up  = close[1] > up[1] ? max(up, up[1]) : up       # ratchet up
  dn  = hl2 + (Multiplier * atr)
  dn  = close[1] < dn[1] ? min(dn, dn[1]) : dn       # ratchet down
  trend flips: -1→1 when close > dn[1], 1→-1 when close < up[1]

Signal:
  BUY  when trend flips from -1 to 1  (at the close of that bar)
  SELL when trend flips from  1 to -1 (at the close of that bar)

SL Types (all TP = SL distance × R/R):
  fixed_rr   — SL at entry ± fixed pips
  candle_low — SL at signal candle low (BUY) / high (SELL) ±1 pip
  atr        — SL at entry ± ATR × multiplier
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from app.core.strategy_template import BaseStrategy, StrategyConfig


# ─── Pydantic Config (Single Source of Truth) ───────────────────
class SupertrendConfig(StrategyConfig):
    """Typed, validated configuration for the Supertrend strategy."""

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

    # SL / TP
    sl_type: Literal["fixed_rr", "candle_low", "atr"] = Field(
        "candle_low",
        description="Stop Loss Type",
    )
    risk_reward_ratio: float = Field(
        2.0, ge=0.1, le=20.0,
        description="Risk / Reward Ratio  (TP = SL distance × R/R)",
        json_schema_extra={"step": 0.1},
    )
    sl_pips: int = Field(
        20, ge=1, le=1000,
        description="Stop Loss (pips) — fixed_rr only",
        json_schema_extra={"step": 1, "x-visible-when": {"sl_type": ["fixed_rr"]}},
    )
    atr_sl_multiplier: float = Field(
        1.5, ge=0.1, le=10.0,
        description="ATR SL Multiplier  (SL = ATR × value) — atr only",
        json_schema_extra={"step": 0.1, "x-visible-when": {"sl_type": ["atr"]}},
    )


# ─── Strategy ──────────────────────────────────────────────────
class Supertrend(BaseStrategy):
    """
    Classic Supertrend indicator (TV Pine Script logic).
    BUY when Supertrend flips to green, SELL when it flips to red.
    Three SL modes: fixed R/R, entry-candle low/high, or ATR-based.
    """

    name = "Supertrend"
    description = (
        "Classic Supertrend indicator (TV Pine Script logic). "
        "BUY when Supertrend flips to green, SELL when it flips to red. "
        "Three SL modes: fixed R/R, entry-candle low/high, or ATR-based."
    )
    config_model = SupertrendConfig

    # ─── ATR (Wilder's, same as Pine atr()) ─────────────────────
    def _compute_atr(
        self,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        period: int,
    ) -> np.ndarray:
        n = len(close)
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        atr = np.full(n, np.nan)
        if n >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        return atr

    # ─── Supertrend — exact Pine Script port ────────────────────
    def _compute_supertrend(
        self,
        data: pd.DataFrame,
        period: int,
        multiplier: float,
    ):
        """
        Returns (up_arr, dn_arr, trend_arr) all same length as data.

        up_arr  : lower support band (shown when trend == 1, green)
        dn_arr  : upper resistance band (shown when trend == -1, red)
        trend_arr: +1 = uptrend, -1 = downtrend
        """
        high = data["high"].values.astype(float)
        low = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        n = len(close)

        hl2 = (high + low) / 2.0
        atr = self._compute_atr(high, low, close, period)

        up = np.full(n, np.nan)
        dn = np.full(n, np.nan)
        trend = np.zeros(n, dtype=int)

        for i in range(n):
            if np.isnan(atr[i]):
                up[i] = hl2[i] - multiplier * (high[i] - low[i])
                dn[i] = hl2[i] + multiplier * (high[i] - low[i])
                trend[i] = 1 if i == 0 else trend[i - 1]
                continue

            basic_up = hl2[i] - multiplier * atr[i]
            basic_dn = hl2[i] + multiplier * atr[i]

            if i == 0:
                up[i] = basic_up
                dn[i] = basic_dn
                trend[i] = 1
            else:
                prev_up = up[i - 1]
                prev_dn = dn[i - 1]
                prev_close = close[i - 1]
                prev_trend = trend[i - 1]

                up[i] = max(basic_up, prev_up) if prev_close > prev_up else basic_up
                dn[i] = min(basic_dn, prev_dn) if prev_close < prev_dn else basic_dn

                if prev_trend == -1 and close[i] > prev_dn:
                    trend[i] = 1
                elif prev_trend == 1 and close[i] < prev_up:
                    trend[i] = -1
                else:
                    trend[i] = prev_trend

        return up, dn, trend

    # ─── SL / TP ────────────────────────────────────────────────
    def _calc_sl_tp(
        self,
        direction: str,
        entry: float,
        bar_low: float,
        bar_high: float,
        atr_val: float,
    ):
        cfg = self.config
        pip = getattr(self, "_pip_value", 0.0001)

        if cfg.sl_type == "fixed_rr":
            dist = cfg.sl_pips * pip
            sl = entry - dist if direction == "BUY" else entry + dist
            tp = entry + dist * cfg.risk_reward_ratio if direction == "BUY" else entry - dist * cfg.risk_reward_ratio

        elif cfg.sl_type == "candle_low":
            if direction == "BUY":
                sl = bar_low - pip
                dist = entry - sl
                tp = entry + dist * cfg.risk_reward_ratio
            else:
                sl = bar_high + pip
                dist = sl - entry
                tp = entry - dist * cfg.risk_reward_ratio

        elif cfg.sl_type == "atr":
            mult = cfg.atr_sl_multiplier
            dist = atr_val * mult if (not np.isnan(atr_val) and atr_val > 0) else pip * 20
            sl = entry - dist if direction == "BUY" else entry + dist
            tp = entry + dist * cfg.risk_reward_ratio if direction == "BUY" else entry - dist * cfg.risk_reward_ratio

        else:
            return None, None

        return round(sl, 6), round(tp, 6)

    # ─── on_bar ─────────────────────────────────────────────────
    def on_bar(self, index: int, data: pd.DataFrame):
        cfg = self.config

        if index < 1 or len(data) < cfg.atr_period + 1:
            return "HOLD"

        _, dn, trend = self._compute_supertrend(data, cfg.atr_period, cfg.multiplier)

        curr_trend = trend[index]
        prev_trend = trend[index - 1]

        buy_signal = curr_trend == 1 and prev_trend == -1
        sell_signal = curr_trend == -1 and prev_trend == 1

        if not buy_signal and not sell_signal:
            return "HOLD"

        entry = float(data["close"].iloc[index])
        bar_low = float(data["low"].iloc[index])
        bar_high = float(data["high"].iloc[index])

        high_arr = data["high"].values.astype(float)
        low_arr = data["low"].values.astype(float)
        close_arr = data["close"].values.astype(float)
        atr_arr = self._compute_atr(high_arr, low_arr, close_arr, cfg.atr_period)
        atr_val = float(atr_arr[index]) if not np.isnan(atr_arr[index]) else 0.0

        if buy_signal and cfg.trade_direction in ("both", "long_only"):
            sl, tp = self._calc_sl_tp("BUY", entry, bar_low, bar_high, atr_val)
            return ("BUY", sl, tp)

        if sell_signal and cfg.trade_direction in ("both", "short_only"):
            sl, tp = self._calc_sl_tp("SELL", entry, bar_low, bar_high, atr_val)
            return ("SELL", sl, tp)

        return "HOLD"

    # ─── Indicator Overlay ──────────────────────────────────────
    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        cfg = self.config

        if len(data) < cfg.atr_period + 1:
            return {}

        up, dn, trend = self._compute_supertrend(data, cfg.atr_period, cfg.multiplier)

        bull = [
            None if trend[i] != 1 else (None if np.isnan(up[i]) else round(float(up[i]), 6))
            for i in range(len(trend))
        ]
        bear = [
            None if trend[i] != -1 else (None if np.isnan(dn[i]) else round(float(dn[i]), 6))
            for i in range(len(trend))
        ]

        return {
            f"ST↑ ({cfg.atr_period},{cfg.multiplier})": bull,
            f"ST↓ ({cfg.atr_period},{cfg.multiplier})": bear,
        }
