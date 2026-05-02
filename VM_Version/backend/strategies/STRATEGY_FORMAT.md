# MTF Tester — Strategy File Format

## Quick Start

Copy this template, fill in your logic, and upload via the "Create Strategy" panel.

```python
from strategies._template import BaseStrategy, StrategyConfig, Signal, HOLD
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
            return HOLD
        
        ef = cache["ema_fast"]
        es = cache["ema_slow"]
        
        if np.isnan(ef[index]) or np.isnan(es[index]):
            return HOLD
        if np.isnan(ef[index-1]) or np.isnan(es[index-1]):
            return HOLD
        
        cross_up   = ef[index-1] <= es[index-1] and ef[index] > es[index]
        cross_down = ef[index-1] >= es[index-1] and ef[index] < es[index]
        
        bar = data.iloc[index]
        entry = float(bar["close"])
        
        if cross_up and cfg.direction in ("both", "long_only"):
            # A simple Market Order entry
            sl = float(bar["low"])
            tp = entry + (entry - sl) * cfg.rr_ratio
            return Signal(direction="BUY", sl=sl, tp=tp)
        
        if cross_down and cfg.direction in ("both", "short_only"):
            sl = float(bar["high"])
            tp = entry - (sl - entry) * cfg.rr_ratio
            return Signal(direction="SELL", sl=sl, tp=tp)
        
        return HOLD

```

## Critical System Behaviors (Avoid These Traps!)

### 1. The Market Order Trap
> [!WARNING]
> MTF-Tester executes **ALL** `Signal` objects as **Market Orders** at the current `Close` price of the bar. It does NOT support Limit or Stop pending orders.

If your strategy identifies a "discount zone" or a "pullback limit price" and calculates SL/TP based on that limit price, **do not emit the signal immediately.** If you do, you will buy at the market `Close`, completely breaking your Risk:Reward math (causing issues like `Take Profit = Open Price`).
**Fix:** You must write a Pullback State Machine (see below) to wait for the price to hit your zone.

### 2. The Live Polling Index Trap
> [!WARNING]
> NEVER store the `index` variable in `self.state` to measure time duration!

During historical backtesting, `index` counts sequentially from `0` to `100,000`. However, during **Live Trading**, the engine bounds the dataframe memory to the most recent 3000 bars. As new live bars arrive, the oldest bars are dropped, meaning `index` gets capped at `2999` and stops growing. 
**Fix:** If you need to count duration (e.g. "wait 15 bars before setup expires"), store the **bar's timestamp** instead, OR create an absolute counter using `self.state.setdefault("cum_bars", 0)` and increment it in `on_update`.

### 3. The 10016 Invalid Stops Error
> [!WARNING]
> NEVER hardcode fixed absolute pip distances (e.g., `0.0020`) for your Stop Losses. 

Fixed pip configurations that work for Forex (e.g., `EURUSD`) will be rejected by MT5 (Error Code 10016) when applied to symbols with different digit scales (like `XAUUSDm` or `BTCUSD`).
**Fix:** Always calculate Stop Loss dynamically using Volatility (e.g., a multiple of Average True Range - ATR) or Structural Swings (e.g., `bar["low"]`). This guarantees your strategy works on any symbol.

---

## The Pullback State Machine Boilerplate

If your strategy waits for a pullback to an "Entry Zone", use this boilerplate to hold the setup in `self.state` and only execute when the price touches the zone:

```python
    def on_bar(self, index: int, data: pd.DataFrame) -> Signal:
        bar = data.iloc[index]
        close = float(bar["close"])
        low = float(bar["low"])
        time_str = str(bar["time"])

        # 1. Check if we are waiting for a pullback
        pending = self.state.get("pending_setup")
        if pending:
            # Check if setup expired (using timestamp to avoid the Live Index Trap)
            current_time = pd.Timestamp(time_str)
            if current_time > pending["expire_time"]:
                self.state["pending_setup"] = None
            else:
                # Setup is still valid. Did price pull back to our zone?
                if pending["direction"] == "BUY" and low <= pending["entry_zone"]:
                    self.state["pending_setup"] = None
                    return Signal(
                        direction="BUY",
                        sl=pending["sl"],
                        tp=pending["tp"],
                        metadata={"type": "Pullback Entry"}
                    )
                # ... same for SELL checking high >= entry_zone

        # 2. Look for new setups
        if my_buy_condition:
            entry_zone = close - atr_value   # We want to buy here
            sl = entry_zone - atr_value      # SL relative to entry
            tp = entry_zone + 2 * atr_value  # TP relative to entry
            
            # Save the setup and HOLD. Wait for price to come to us.
            self.state["pending_setup"] = {
                "direction": "BUY",
                "entry_zone": entry_zone,
                "sl": sl,
                "tp": tp,
                "expire_time": pd.Timestamp(time_str) + pd.Timedelta(minutes=15)
            }
            return HOLD
            
        return HOLD
```

## Persistent State Management

`self._cache`   — Derived from input data. Safe to rebuild from scratch. Populate in `on_start()`.
`self.state`    — Persistent across live polling boundaries. The engine NEVER touches this. Use it for state machines, pending setups, and tracking flags.

In BACKTEST: `on_start` runs once; `self.state` accumulates through the entire loop.
In LIVE: `on_start` runs at session start; `on_update` runs on each poll; `self.state` persists across polls indefinitely.

## Return Values from on_bar()

It is strongly preferred to return the structured `Signal` dataclass:

```python
from strategies._template import Signal, HOLD

return Signal(direction="BUY", sl=sl, tp=tp)
# OR
return HOLD
```

For backward compatibility, strings and tuples are still supported:
`"BUY"`, `"SELL"`, `"HOLD"`
`("BUY", sl, tp)`
`("SELL", sl, tp)`

**SL and TP are absolute price values, not pip distances.**

## Multi-Timeframe Strategies

If your strategy operates on a higher timeframe (e.g., H4), resample the M1 data and use the `_m1_to_completed_htf_index` helper. This guarantees no look-ahead: at each M1 bar, the strategy only sees HTF bars that have *fully closed*.

```python
from strategies._template import BaseStrategy, TF_DURATION

TF_RULE = {"M1": "1min", "M5": "5min", "H1": "1h", "H4": "4h"}

class MyHTFStrategy(BaseStrategy):
    def on_start(self, data):
        htf = self._resample(data, TF_RULE[self.config.timeframe])
        
        # completed-HTF mapping guarantees no look-ahead
        m1_to_htf = self._m1_to_completed_htf_index(
            data['time'], htf['time'], TF_DURATION[self.config.timeframe]
        )

        self._cache = {
            'm1_to_htf': m1_to_htf,
            'htf_pulse': my_htf_pulse_array,
        }

    def on_bar(self, i, data):
        h_idx = self._cache['m1_to_htf'][i]
        if h_idx < 1:
            return HOLD   # wait for completed HTF bars
            
        current_htf_pulse = self._cache['htf_pulse'][h_idx]
```

## Config Field Types → UI Widgets

```python
period: int          = Field(14, ge=1, le=500)        # number input
ratio:  float        = Field(2.0, ge=0.1, le=20.0)    # decimal input  
mode:   Literal[...] = Field("both", ...)             # dropdown select
```

## What your strategy can do

Strategy files run with full Python access. Common imports that are known to work:
- `numpy`, `pandas`, `math`, `datetime`, `typing`, `pydantic`

Only upload strategy files that you wrote or reviewed. A malicious file could do anything your user account can do.
