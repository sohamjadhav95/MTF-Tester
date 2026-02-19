"""
EMA Crossover Strategy
Example strategy template — ships with the app.
Users can reference this to create their own strategies.
"""

import pandas as pd
import numpy as np
from .base import BaseStrategy


class EMACrossover(BaseStrategy):
    """
    EMA Crossover Strategy.
    
    Generates BUY signals when the fast EMA crosses above the slow EMA,
    and SELL signals when the fast EMA crosses below the slow EMA.
    
    EMA Formula: EMA[i] = price * k + EMA[i-1] * (1 - k)
    where k = 2 / (period + 1)
    
    This matches the EMA implementation in TradingView and MetaTrader 5.
    """

    @property
    def name(self) -> str:
        return "EMA Crossover"

    @property
    def description(self) -> str:
        return (
            "Generates signals based on the crossover of two Exponential "
            "Moving Averages (fast and slow). Buy when fast crosses above "
            "slow, sell when fast crosses below slow."
        )

    @property
    def settings_schema(self) -> dict:
        return {
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
        }

    def _compute_ema(self, series: pd.Series, period: int) -> np.ndarray:
        """
        Compute EMA using the standard exponential formula.
        EMA[i] = price * k + EMA[i-1] * (1 - k)
        where k = 2 / (period + 1)
        
        First EMA value is the SMA of the first 'period' values.
        This matches TradingView / MT5 EMA calculation.
        """
        values = series.values.astype(float)
        ema = np.full(len(values), np.nan)
        k = 2.0 / (period + 1)

        if len(values) < period:
            return ema

        # First EMA = SMA of first 'period' values
        ema[period - 1] = np.mean(values[:period])

        # Calculate EMA for remaining values
        for i in range(period, len(values)):
            ema[i] = values[i] * k + ema[i - 1] * (1 - k)

        return ema

    def on_bar(self, index: int, data: pd.DataFrame) -> str:
        """
        Generate signal based on EMA crossover.
        
        A crossover is detected when:
        - Current bar: fast_ema > slow_ema
        - Previous bar: fast_ema <= slow_ema
        (and vice versa for crossunder)
        """
        fast_period = self.settings["fast_period"]
        slow_period = self.settings["slow_period"]
        source = self.settings["source"]
        direction = self.settings["trade_direction"]

        # Need at least slow_period + 1 bars for a valid crossover signal
        min_bars = max(fast_period, slow_period) + 1
        if len(data) < min_bars:
            return "HOLD"

        # Get price source
        prices = data[source]

        # Compute EMAs on the available data
        fast_ema = self._compute_ema(prices, fast_period)
        slow_ema = self._compute_ema(prices, slow_period)

        # Current and previous values
        curr_fast = fast_ema[index]
        curr_slow = slow_ema[index]
        prev_fast = fast_ema[index - 1]
        prev_slow = slow_ema[index - 1]

        # Check for NaN (not enough data yet)
        if np.isnan(curr_fast) or np.isnan(curr_slow):
            return "HOLD"
        if np.isnan(prev_fast) or np.isnan(prev_slow):
            return "HOLD"

        # Detect crossover (fast crosses above slow)
        cross_above = prev_fast <= prev_slow and curr_fast > curr_slow

        # Detect crossunder (fast crosses below slow)
        cross_below = prev_fast >= prev_slow and curr_fast < curr_slow

        if cross_above:
            if direction in ("both", "long_only"):
                return "BUY"
            elif direction == "short_only":
                # Close any short position
                return "HOLD"

        if cross_below:
            if direction in ("both", "short_only"):
                return "SELL"
            elif direction == "long_only":
                # Close any long position
                return "HOLD"

        return "HOLD"

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """Return EMA values for chart overlay."""
        fast_period = self.settings["fast_period"]
        slow_period = self.settings["slow_period"]
        source = self.settings["source"]

        prices = data[source]
        fast_ema = self._compute_ema(prices, fast_period)
        slow_ema = self._compute_ema(prices, slow_period)

        # Convert NaN to None for JSON serialization
        fast_list = [
            None if np.isnan(v) else round(float(v), 6) for v in fast_ema
        ]
        slow_list = [
            None if np.isnan(v) else round(float(v), 6) for v in slow_ema
        ]

        return {
            f"EMA {fast_period}": fast_list,
            f"EMA {slow_period}": slow_list,
        }
