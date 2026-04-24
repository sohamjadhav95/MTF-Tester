"""
Heartbeat Test Strategy — Normal Use Case Verifier
===================================================
A deterministic "clock" strategy that emits BUY/SELL on a fixed cadence of
M1 bars. Use this to verify the happy path end-to-end:

    scanner launch → historical backfill → live polling → signal emission
      → panel counters tick → right-pane activity feed → chart markers
      → auto-trade opens real order → SL/TP hit logic → position close
      → right-pane positions/equity refresh → footer stats update
      → backtest over a date range produces EXACTLY the predicted count
      → stop scanner → nav card removed → other scanners unaffected

No look-ahead, no noise, no false signals. Every signal is timestamped by the
bar's close time, so you can check the log and know EXACTLY when each fired.

HOW TO READ SIGNALS
-------------------
The strategy fires BUY every `cadence_bars` M1 bars starting at bar index
`offset_bars`. SELL fires exactly `cadence_bars / 2` bars offset from BUY
(so they alternate evenly). SL and TP are symmetric: ±`sl_pips` / ±`tp_pips`
around the current close. Use a symbol with a known pip size (EURUSD = 0.0001)
for clean arithmetic.

PREDICTION EQUATION
-------------------
Total signals emitted over a window of N M1 bars, with cadence C and offset O:
    N_buys  = floor((N - O - 1) / C) + 1
    N_sells = floor((N - O - 1 - C/2) / C) + 1  (if the first SELL falls within N)

Example: N=1000 M1 bars, C=60, O=0  →  N_buys = 17, N_sells = 17, total = 34.

USAGE
-----
Upload this file via Create Strategy → Upload. Then in MTF Strategy:
    Session Name: "Heartbeat"
    Symbol:       EURUSD (or any active symbol)
    Strategy:     Heartbeat Test
    cadence_bars: 60   (a signal every hour of M1 data)
    offset_bars:  0
    sl_pips:      20
    tp_pips:      40
    pip_size:     0.0001

Launch. Within ~60 M1 bars (60 real minutes on live, or instantly in the
3000-bar backfill scan) you'll see the first BUY; then a SELL 30 bars later.
The signal panel badge increments, the right-pane activity feed prepends a
row, and if auto-trade is enabled a real MT5 order is placed with the stated
SL/TP.

NOTE ON WARMUP
--------------
The engine silently absorbs the first 1440 M1 bars (1 day) as warmup. If
`offset_bars` < 1440 in a backtest, the early signals will be absorbed too.
For a clean backtest over a 2-3 day window, set `offset_bars` to 1440 or
larger, or select a backtest window that starts well after the warmup ends.
"""

from __future__ import annotations

from typing import Literal
import numpy as np
import pandas as pd
from pydantic import Field

from ._template import BaseStrategy, StrategyConfig, Signal, HOLD


class HeartbeatConfig(StrategyConfig):
    cadence_bars: int = Field(
        60, ge=2, le=10_000,
        description="Emit BUY every N M1 bars (SELL fires at N/2 offset)"
    )
    offset_bars: int = Field(
        0, ge=0, le=10_000,
        description="Skip the first N bars before starting the clock"
    )
    sl_pips: float = Field(
        20.0, ge=0, le=10_000,
        description="Stop Loss distance in pips (0 = no SL)"
    )
    tp_pips: float = Field(
        40.0, ge=0, le=10_000,
        description="Take Profit distance in pips (0 = no TP)"
    )
    pip_size: float = Field(
        0.0001, gt=0, le=1.0,
        description="Pip size for this symbol (EURUSD=0.0001, XAUUSD=0.1, BTCUSD=1.0)"
    )
    direction_mode: Literal["alternate", "long_only", "short_only"] = Field(
        "alternate",
        description="alternate=BUY/SELL flip; long_only=BUY only; short_only=SELL only"
    )


class HeartbeatTest(BaseStrategy):
    name = "Heartbeat Test"
    description = "Deterministic clock strategy — BUY/SELL on fixed M1-bar cadence. Use for end-to-end verification."
    config_model = HeartbeatConfig

    def on_start(self, data: pd.DataFrame) -> None:
        """Initialize the cumulative bar count for absolute indexing."""
        self.state.setdefault("cum_bars", len(data))
        self._cache = {
            "closes": data["close"].values.astype(float),
        }

    def on_update(self, new_bars: pd.DataFrame, data: pd.DataFrame) -> None:
        """Increment the cumulative bar count by the number of new bars."""
        self.state["cum_bars"] += len(new_bars)
        self._cache = {
            "closes": data["close"].values.astype(float),
        }

    def on_bar(self, index: int, data: pd.DataFrame) -> Signal:
        cache = self._cache
        if not cache:
            return HOLD

        # Calculate absolute index to account for dataframe truncation in live mode
        cum_bars = self.state.get("cum_bars", len(data))
        abs_index = cum_bars - len(data) + index

        cfg = self.config
        cadence = cfg.cadence_bars
        half = cadence // 2
        offset = cfg.offset_bars

        if abs_index < offset:
            return HOLD

        rel_index = abs_index - offset
        
        direction = ""
        if rel_index % cadence == 0:
            direction = "BUY"
        elif rel_index % cadence == half:
            direction = "SELL"

        if not direction:
            return HOLD

        if cfg.direction_mode == "long_only" and direction == "SELL":
            return HOLD
        if cfg.direction_mode == "short_only" and direction == "BUY":
            return HOLD

        cfg = self.config
        price = float(cache["closes"][index])
        sl = None
        tp = None

        if cfg.sl_pips > 0:
            if direction == "BUY":
                sl = price - cfg.sl_pips * cfg.pip_size
            else:
                sl = price + cfg.sl_pips * cfg.pip_size
            if sl <= 0:
                sl = None  # invalid SL for very cheap symbols

        if cfg.tp_pips > 0:
            if direction == "BUY":
                tp = price + cfg.tp_pips * cfg.pip_size
            else:
                tp = price - cfg.tp_pips * cfg.pip_size
            if tp <= 0:
                tp = None

        return Signal(
            direction=direction,
            sl=sl,
            tp=tp,
            metadata={
                "strategy": "Heartbeat",
                "bar_index": int(index),
                "cadence": cfg.cadence_bars,
                "source_price": round(price, 6),
            },
        )
