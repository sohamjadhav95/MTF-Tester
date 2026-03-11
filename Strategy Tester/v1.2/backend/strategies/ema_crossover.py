"""
EMA Crossover Strategy
Enhanced with three SL/TP modes:
  - fixed_rr    : SL at fixed pips; TP = SL distance × R/R ratio
  - candle_low  : SL at the entry bar's low (BUY) or high (SELL); TP = SL × R/R
  - atr         : SL = entry ± ATR × multiplier; TP = SL × R/R
"""

import pandas as pd
import numpy as np
from .base import BaseStrategy


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

    @property
    def name(self) -> str:
        return "EMA Crossover"

    @property
    def description(self) -> str:
        return (
            "Generates signals based on the crossover of two Exponential "
            "Moving Averages (fast & slow). Configurable SL/TP modes: "
            "fixed R/R, entry candle low/high, or ATR-based."
        )

    @property
    def settings_schema(self) -> dict:
        return {
            # ── EMA Settings ─────────────────────────────
            "fast_period": {
                "type": "int",
                "default": 9,
                "min": 2,
                "max": 500,
                "step": 1,
                "description": "Fast EMA Period",
            },
            "slow_period": {
                "type": "int",
                "default": 21,
                "min": 2,
                "max": 500,
                "step": 1,
                "description": "Slow EMA Period",
            },
            "source": {
                "type": "select",
                "default": "close",
                "options": ["open", "high", "low", "close"],
                "description": "Price Source",
            },
            "trade_direction": {
                "type": "select",
                "default": "both",
                "options": ["both", "long_only", "short_only"],
                "description": "Trade Direction",
            },
            # ── SL / TP Settings ─────────────────────────
            "sl_type": {
                "type": "select",
                "default": "fixed_rr",
                "options": ["fixed_rr", "candle_low", "atr"],
                "description": "Stop Loss Type",
            },
            "risk_reward_ratio": {
                "type": "float",
                "default": 2.0,
                "min": 0.1,
                "max": 20.0,
                "step": 0.1,
                "description": "Risk / Reward Ratio (TP = SL distance × R/R)",
            },
            "sl_pips": {
                "type": "int",
                "default": 20,
                "min": 1,
                "max": 1000,
                "step": 1,
                "description": "Stop Loss (pips) — used by fixed_rr",
                "visible_when": {"sl_type": ["fixed_rr"]},
            },
            "atr_period": {
                "type": "int",
                "default": 14,
                "min": 2,
                "max": 200,
                "step": 1,
                "description": "ATR Period — used by atr",
                "visible_when": {"sl_type": ["atr"]},
            },
            "atr_sl_multiplier": {
                "type": "float",
                "default": 1.5,
                "min": 0.1,
                "max": 10.0,
                "step": 0.1,
                "description": "ATR SL Multiplier — SL = ATR × this value",
                "visible_when": {"sl_type": ["atr"]},
            },
        }

    # ─── EMA Calculation ────────────────────────────────────────────────────

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

    # ─── ATR Calculation ────────────────────────────────────────────────────

    def _compute_atr(self, data: pd.DataFrame, period: int) -> np.ndarray:
        """Wilder's ATR (same as MT5 / TradingView)."""
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        n = len(close)

        tr = np.full(n, np.nan)
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i]  - close[i - 1]),
            )
        tr[0] = high[0] - low[0]

        atr = np.full(n, np.nan)
        if n >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        return atr

    # ─── SL / TP Calculation ────────────────────────────────────────────────

    def _calc_sl_tp(
        self,
        direction: str,
        entry_price: float,
        bar_low: float,
        bar_high: float,
        atr_val: float,
    ):
        """
        Compute (sl_price, tp_price) based on sl_type setting.
        """
        sl_type   = self.settings["sl_type"]
        rr        = self.settings["risk_reward_ratio"]
        pip_value = getattr(self, "_pip_value", 0.0001)

        if sl_type == "fixed_rr":
            sl_pips     = self.settings["sl_pips"]
            sl_distance = sl_pips * pip_value
            if direction == "BUY":
                sl = entry_price - sl_distance
                tp = entry_price + sl_distance * rr
            else:
                sl = entry_price + sl_distance
                tp = entry_price - sl_distance * rr

        elif sl_type == "candle_low":
            if direction == "BUY":
                sl = bar_low - pip_value          # 1 pip below entry candle low
                sl_distance = entry_price - sl
                tp = entry_price + sl_distance * rr
            else:
                sl = bar_high + pip_value         # 1 pip above entry candle high
                sl_distance = sl - entry_price
                tp = entry_price - sl_distance * rr

        elif sl_type == "atr":
            atr_mult = self.settings["atr_sl_multiplier"]
            if not np.isnan(atr_val) and atr_val > 0:
                sl_distance = atr_val * atr_mult
            else:
                sl_distance = pip_value * 20       # fallback: 20 pips
            if direction == "BUY":
                sl = entry_price - sl_distance
                tp = entry_price + sl_distance * rr
            else:
                sl = entry_price + sl_distance
                tp = entry_price - sl_distance * rr

        else:
            return None, None

        return round(sl, 6), round(tp, 6)

    # ─── on_bar ─────────────────────────────────────────────────────────────

    def on_bar(self, index: int, data: pd.DataFrame):
        """
        Generate signal based on EMA crossover.
        Returns either 'HOLD' or a tuple (signal, sl_price, tp_price).
        """
        fast_period = self.settings["fast_period"]
        slow_period = self.settings["slow_period"]
        source      = self.settings["source"]
        direction   = self.settings["trade_direction"]
        sl_type     = self.settings["sl_type"]

        atr_period  = self.settings.get("atr_period", 14) if sl_type == "atr" else 14
        min_bars    = max(fast_period, slow_period, atr_period if sl_type == "atr" else 0) + 1

        if len(data) < min_bars:
            return "HOLD"

        prices   = data[source]
        fast_ema = self._compute_ema(prices, fast_period)
        slow_ema = self._compute_ema(prices, slow_period)

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
        bar_low     = float(data["low"].iloc[index])
        bar_high    = float(data["high"].iloc[index])

        # ATR value at current bar (if needed)
        atr_val = 0.0
        if sl_type == "atr":
            atr_arr = self._compute_atr(data, atr_period)
            atr_val = float(atr_arr[index]) if not np.isnan(atr_arr[index]) else 0.0

        if cross_above and direction in ("both", "long_only"):
            sl, tp = self._calc_sl_tp("BUY", entry_price, bar_low, bar_high, atr_val)
            return ("BUY", sl, tp)

        if cross_below and direction in ("both", "short_only"):
            sl, tp = self._calc_sl_tp("SELL", entry_price, bar_low, bar_high, atr_val)
            return ("SELL", sl, tp)

        return "HOLD"

    # ─── Indicator overlay ──────────────────────────────────────────────────

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """Return EMA values for price chart overlay."""
        fast_period = self.settings["fast_period"]
        slow_period = self.settings["slow_period"]
        source      = self.settings["source"]

        prices   = data[source]
        fast_ema = self._compute_ema(prices, fast_period)
        slow_ema = self._compute_ema(prices, slow_period)

        def to_list(arr):
            return [None if np.isnan(v) else round(float(v), 6) for v in arr]

        return {
            f"EMA {fast_period}": to_list(fast_ema),
            f"EMA {slow_period}": to_list(slow_ema),
        }
