# MTF Tester — Strategy File Format

## Quick Start

Copy this template, fill in your logic, upload via the "Create Strategy" panel.

```python
from strategies._template import BaseStrategy, StrategyConfig
from pydantic import Field
from typing import Literal
import numpy as np
import pandas as pd


class MyConfig(StrategyConfig):
    """All parameters here auto-generate UI inputs."""
    
    # int → number input
    fast_period: int = Field(10, ge=2, le=500, description="Fast EMA Period")
    slow_period: int = Field(50, ge=2, le=500, description="Slow EMA Period")
    
    # float → decimal input  
    rr_ratio: float = Field(2.0, ge=0.1, le=20.0, description="Risk/Reward Ratio")
    
    # Literal → dropdown select
    direction: Literal["both", "long_only", "short_only"] = Field(
        "both", description="Trade Direction"
    )


class MyStrategy(BaseStrategy):
    name         = "My Strategy Name"   # shown in dropdown — must be unique
    description  = "Brief description"
    config_model = MyConfig

    def on_start(self, data: pd.DataFrame):
        """
        Called ONCE before the bar loop.
        Pre-compute ALL indicators here and store in self._cache.
        data contains the full dataset (all bars).
        """
        cfg = self.config
        close = data["close"].values.astype(float)
        
        # Example EMA computation
        def ema(series, period):
            result = np.full(len(series), np.nan)
            if len(series) < period:
                return result
            k = 2.0 / (period + 1)
            result[period - 1] = np.mean(series[:period])
            for i in range(period, len(series)):
                result[i] = series[i] * k + result[i - 1] * (1 - k)
            return result
        
        self._cache = {
            "ema_fast": ema(close, cfg.fast_period),
            "ema_slow": ema(close, cfg.slow_period),
        }

    def on_bar(self, index: int, data: pd.DataFrame):
        """
        Called on EVERY bar.
        ONLY reads from self._cache — never computes indicators here.
        data contains bars 0..index (no future data, no look-ahead).
        """
        cfg   = self.config
        cache = getattr(self, "_cache", None)
        if cache is None or index < 2:
            return "HOLD"
        
        ef = cache["ema_fast"]
        es = cache["ema_slow"]
        
        if np.isnan(ef[index]) or np.isnan(es[index]):
            return "HOLD"
        if np.isnan(ef[index-1]) or np.isnan(es[index-1]):
            return "HOLD"
        
        cross_up   = ef[index-1] <= es[index-1] and ef[index] > es[index]
        cross_down = ef[index-1] >= es[index-1] and ef[index] < es[index]
        
        bar = data.iloc[index]
        entry = float(bar["close"])
        
        if cross_up and cfg.direction in ("both", "long_only"):
            sl = float(bar["low"])
            tp = entry + (entry - sl) * cfg.rr_ratio
            return ("BUY", sl, tp)
        
        if cross_down and cfg.direction in ("both", "short_only"):
            sl = float(bar["high"])
            tp = entry - (sl - entry) * cfg.rr_ratio
            return ("SELL", sl, tp)
        
        return "HOLD"

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """
        Return indicators for chart overlay.
        dict keys = line labels in the chart legend.
        dict values = list of float (or None for NaN) — SAME LENGTH as data.
        
        Naming convention:
        - Contains "rsi", "macd", "stoch", "volume", "histogram", "oscillator"
          → renders in a separate pane below the chart
        - Everything else → overlaid on the price chart
        """
        cache = getattr(self, "_cache", None)
        if not cache:
            return {}
        
        def to_list(arr):
            return [None if np.isnan(v) else round(float(v), 6) for v in arr]
        
        return {
            "EMA Fast": to_list(cache["ema_fast"]),
            "EMA Slow": to_list(cache["ema_slow"]),
        }
```

## Return Values from on_bar()

| Return | Meaning |
|--------|---------|
| `"BUY"` | Enter long, no SL/TP |
| `"SELL"` | Enter short, no SL/TP |
| `"HOLD"` | Do nothing |
| `("BUY", 1.0850, 1.0920)` | Enter long, SL=1.0850, TP=1.0920 |
| `("SELL", 1.0920, 1.0850)` | Enter short, SL=1.0920, TP=1.0850 |
| `("BUY", None, 1.0920)` | Enter long with TP only |
| `("BUY", 1.0850, None)` | Enter long with SL only |

**SL and TP are absolute price values, not pip distances.**

## Data Available in on_bar()

```python
data.iloc[index]  # current bar
# Columns: time, open, high, low, close, volume, spread

data.iloc[index]["close"]  # current close price (float)
data.iloc[index]["high"]   # current high
data.iloc[index]["low"]    # current low
data.iloc[index]["time"]   # datetime
```

## Config Field Types → UI Widgets

```python
period: int          = Field(14, ge=1, le=500)        # number input
ratio:  float        = Field(2.0, ge=0.1, le=20.0)    # decimal input  
mode:   Literal[...] = Field("both", ...)              # dropdown select
```

## Allowed Imports

- `numpy`, `pandas`, `math`, `typing`, `datetime`
- `pydantic` (for Field)
- `strategies._template` (for BaseStrategy, StrategyConfig)

**Blocked:** `os`, `subprocess`, `socket`, `requests`, `open()`, `urllib`, `pathlib`
