"""
EMA Crossover Strategy
Enhanced with SL/TP support: fixed pips, fixed R/R, or EMA-based.
"""

import pandas as pd
import numpy as np
from .base import BaseStrategy


class EMACrossover(BaseStrategy):
    """
    EMA Crossover Strategy.

    Generates BUY signals when the fast EMA crosses above the slow EMA,
    and SELL signals when the fast EMA crosses below the slow EMA.

    Supports optional Stop Loss / Take Profit:
      - none       : No SL/TP, position closed only on opposite signal
      - fixed_pips : SL and TP at fixed pip distances
      - fixed_rr   : SL at fixed pips, TP derived from Risk/Reward ratio
      - based_on_ema: SL behind the slow EMA, TP at R/R multiple of that SL
    """

    @property
    def name(self) -> str:
        return "EMA Crossover"

    @property
    def description(self) -> str:
        return (
            "Generates signals based on the crossover of two Exponential "
            "Moving Averages (fast & slow). Includes configurable SL/TP modes."
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
            "sl_tp_type": {
                "type": "select",
                "default": "none",
                "options": ["none", "fixed_pips", "fixed_rr", "based_on_ema"],
                "description": "SL / TP Type",
            },
            "sl_pips": {
                "type": "int",
                "default": 20,
                "min": 1,
                "max": 1000,
                "step": 1,
                "description": "Stop Loss (pips)",
                "visible_when": {"sl_tp_type": ["fixed_pips", "fixed_rr", "based_on_ema"]},
            },
            "tp_pips": {
                "type": "int",
                "default": 40,
                "min": 1,
                "max": 5000,
                "step": 1,
                "description": "Take Profit (pips)",
                "visible_when": {"sl_tp_type": ["fixed_pips"]},
            },
            "risk_reward_ratio": {
                "type": "float",
                "default": 2.0,
                "min": 0.1,
                "max": 20.0,
                "step": 0.1,
                "description": "Risk / Reward Ratio",
                "visible_when": {"sl_tp_type": ["fixed_rr", "based_on_ema"]},
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

    # ─── SL / TP Calculation ────────────────────────────────────────────────

    def _calc_sl_tp(self, direction: str, entry_price: float, slow_ema_val: float):
        """
        Compute (sl_price, tp_price) based on sl_tp_type setting.
        Returns (None, None) when sl_tp_type is 'none'.
        """
        sl_tp_type = self.settings["sl_tp_type"]
        if sl_tp_type == "none":
            return None, None

        # Pip size: approximate using point.  We don't have config here,
        # so we use a pip = 0.0001 for 4-digit, 0.00001 for 5-digit symbols.
        # Strategy stores config point if available (set by backtester helper).
        pip_value = getattr(self, "_pip_value", 0.0001)

        sl_pips = self.settings["sl_pips"]
        tp_pips = self.settings["tp_pips"]
        rr = self.settings["risk_reward_ratio"]

        sl_distance = sl_pips * pip_value

        if sl_tp_type == "fixed_pips":
            tp_distance = tp_pips * pip_value
            if direction == "BUY":
                return entry_price - sl_distance, entry_price + tp_distance
            else:
                return entry_price + sl_distance, entry_price - tp_distance

        elif sl_tp_type == "fixed_rr":
            tp_distance = sl_distance * rr
            if direction == "BUY":
                return entry_price - sl_distance, entry_price + tp_distance
            else:
                return entry_price + sl_distance, entry_price - tp_distance

        elif sl_tp_type == "based_on_ema":
            # SL just behind the slow EMA; TP = entry ± (entry - slow_ema) * R/R
            if direction == "BUY":
                sl = slow_ema_val - pip_value  # 1 pip below slow EMA
                dist = entry_price - sl
                tp = entry_price + dist * rr
                return sl, tp
            else:
                sl = slow_ema_val + pip_value  # 1 pip above slow EMA
                dist = sl - entry_price
                tp = entry_price - dist * rr
                return sl, tp

        return None, None

    # ─── on_bar ─────────────────────────────────────────────────────────────

    def on_bar(self, index: int, data: pd.DataFrame):
        """
        Generate signal based on EMA crossover.
        Returns either "HOLD" or a tuple (signal, sl_price, tp_price).
        """
        fast_period = self.settings["fast_period"]
        slow_period = self.settings["slow_period"]
        source = self.settings["source"]
        direction = self.settings["trade_direction"]

        min_bars = max(fast_period, slow_period) + 1
        if len(data) < min_bars:
            return "HOLD"

        prices = data[source]
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

        entry = float(data["close"].iloc[index])

        if cross_above and direction in ("both", "long_only"):
            sl, tp = self._calc_sl_tp("BUY", entry, float(curr_slow))
            return ("BUY", sl, tp)

        if cross_below and direction in ("both", "short_only"):
            sl, tp = self._calc_sl_tp("SELL", entry, float(curr_slow))
            return ("SELL", sl, tp)

        return "HOLD"

    # ─── Indicator overlay ──────────────────────────────────────────────────

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """Return EMA values for price chart overlay."""
        fast_period = self.settings["fast_period"]
        slow_period = self.settings["slow_period"]
        source = self.settings["source"]

        prices = data[source]
        fast_ema = self._compute_ema(prices, fast_period)
        slow_ema = self._compute_ema(prices, slow_period)

        def to_list(arr):
            return [None if np.isnan(v) else round(float(v), 6) for v in arr]

        return {
            f"EMA {fast_period}": to_list(fast_ema),
            f"EMA {slow_period}": to_list(slow_ema),
        }
