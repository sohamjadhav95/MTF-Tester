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


```

## Multi-Timeframe Strategies

If your strategy operates on a higher timeframe (e.g., H4), resample the M1
data and use the `_m1_to_completed_htf_index` helper. This guarantees no
look-ahead: at each M1 bar, the strategy only sees HTF bars that have
*fully closed* by that M1 bar's time.

```python
from strategies._template import BaseStrategy, TF_DURATION

TF_RULE = {"M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}

class MyHTFStrategy(BaseStrategy):
    def on_start(self, data):
        htf = self._resample(data, TF_RULE[self.config.timeframe])
        htf_duration = TF_DURATION[self.config.timeframe]

        # compute indicators on the HTF series
        ema_fast = self._ema(htf['close'].values, 10)

        # completed-HTF mapping — the whole point
        m1_to_htf = self._m1_to_completed_htf_index(
            data['time'], htf['time'], htf_duration
        )

        self._cache = {
            'ema_fast': ema_fast,
            'm1_to_htf': m1_to_htf,
            'htf_times': htf['time'].values,   # enables scanner dedup
        }

    def on_bar(self, i, data):
        h_idx = self._cache['m1_to_htf'][i]
        if h_idx < 1:
            return "HOLD"   # need at least two completed HTF bars
        # compare last two completed HTF bars
        ...
```

**The signal fires on the M1 bar where `h_idx` just incremented** (i.e., a new
HTF bar just became complete). The scanner deduplicates so the signal is
emitted exactly once per HTF bar.

## Persistent state across bar loops

`self._cache`   — derived from input data; safe to rebuild from scratch.
                Populate in `on_start()`. May be touched by `on_update()`.
`self.state`    — persistent across bar loops in LIVE mode.
                The engine NEVER touches this. Use it for counters, flags,
                state machines — anything whose value depends on the history
                of `on_bar()` calls.

In BACKTEST: `on_start` runs once; `self.state` accumulates normally through the loop.
In LIVE: `on_start` runs once at session start; `on_update` runs on each poll;
         `self.state` persists across polls.

If your strategy is purely a function of (index, data), you can ignore `self.state`
entirely. If your strategy has a state machine, a counter, or any "memory", use
`self.state` and ONLY `self.state` for it.

## Return Values from on_bar()

It is preferred to return the structured `Signal` dataclass imported from `_template.py`:

```python
from strategies._template import Signal, HOLD

# ...
return Signal(direction="BUY", sl=sl, tp=tp)
# OR
return HOLD
```

For backward compatibility, strings and tuples are still supported:

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

## What your strategy can do

Strategy files run with full Python access. Common imports that are known to work:
- `numpy`, `pandas`, `math`, `datetime`, `typing`, `pydantic`

Because this is a single-user local application, no sandboxing is applied.
Only upload strategy files that you wrote or reviewed. A malicious file
could do anything your user account can do.
