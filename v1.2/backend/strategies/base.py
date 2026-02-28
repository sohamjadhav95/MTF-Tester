"""
Base Strategy Class
All user-authored strategies must extend this class.
"""

from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    
    Users create strategies by:
    1. Creating a new .py file in the strategies/ directory
    2. Defining a class that extends BaseStrategy
    3. Implementing the required properties and on_bar() method
    4. Defining settings_schema for UI-configurable parameters
    
    The app will auto-discover and load the strategy.
    
    Example settings_schema format:
    {
        "fast_period": {
            "type": "int",
            "default": 9,
            "min": 2,
            "max": 500,
            "step": 1,
            "description": "Fast EMA period"
        },
        "source": {
            "type": "select",
            "default": "close",
            "options": ["open", "high", "low", "close"],
            "description": "Price source"
        },
        "use_filter": {
            "type": "bool",
            "default": False,
            "description": "Use trend filter"
        },
        "threshold": {
            "type": "float",
            "default": 0.5,
            "min": 0.0,
            "max": 10.0,
            "step": 0.1,
            "description": "Signal threshold"
        }
    }
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name for the strategy (shown in UI dropdown)."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of what the strategy does."""
        pass

    @property
    @abstractmethod
    def settings_schema(self) -> dict:
        """
        Define configurable settings with types, defaults, and ranges.
        Each key is a parameter name, value is a dict with:
        - type: "int", "float", "select", "bool"
        - default: default value
        - min/max/step: for numeric types
        - options: list of choices for "select" type
        - description: human-readable label
        """
        pass

    def __init__(self, settings: dict = None):
        """
        Initialize strategy with user-provided settings.
        Missing settings fall back to defaults from settings_schema.
        """
        self.settings = {}
        schema = self.settings_schema

        for key, spec in schema.items():
            if settings and key in settings:
                self.settings[key] = self._cast_setting(
                    settings[key], spec["type"]
                )
            else:
                self.settings[key] = spec["default"]

    def _cast_setting(self, value, type_str: str):
        """Cast a setting value to the correct type."""
        if type_str == "int":
            return int(value)
        elif type_str == "float":
            return float(value)
        elif type_str == "bool":
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        return value  # select and others stay as-is

    @abstractmethod
    def on_bar(self, index: int, data: pd.DataFrame) -> str:
        """
        Called on each bar during backtesting.
        
        Args:
            index: Current bar index (0-based)
            data: DataFrame with all bars up to and including current bar.
                  Columns: time, open, high, low, close, volume, spread
                  IMPORTANT: data contains ONLY bars up to current index.
                  There is NO look-ahead — you cannot access future bars.
        
        Returns:
            Signal string: "BUY", "SELL", or "HOLD"
            - "BUY": Open a long position (or flip short to long)
            - "SELL": Open a short position (or flip long to short)
            - "HOLD": Do nothing (maintain current position or stay flat)
        """
        pass

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """
        Optional: Return indicator values for chart overlay.
        
        Called AFTER the backtest completes with the full dataset.
        Return a dict where keys are indicator names and values are
        lists of floats (same length as data, use None for missing values).
        
        Example:
            return {
                "EMA 9": ema_fast.tolist(),
                "EMA 21": ema_slow.tolist(),
            }
        """
        return {}
