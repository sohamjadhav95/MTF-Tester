"""
VWAP Crossover Strategy
=======================
Entry logic
-----------
BUY  : Candle OPEN is below VWAP  AND candle CLOSE is above VWAP
        (candle straddles VWAP upward — the cross happens on this bar)
SELL : Candle OPEN is above VWAP  AND candle CLOSE is below VWAP
        (candle straddles VWAP downward)

Stop-Loss options
-----------------
  candle_low  — SL at signal-bar low (BUY) / high (SELL)  ±1 pip
  atr_trail   — SL = entry ± ATR × multiplier

Take-Profit (Grid style)
------------------------
TP levels are spaced at the SAME distance as the initial SL distance.
  TP₁ = entry + 1 × SL_dist   (BUY)
  TP₂ = entry + 2 × SL_dist
  …up to ``tp_grid_levels`` multiples (the engine receives the outermost TP)
  i.e.  TP = entry ± SL_dist × tp_grid_levels

VWAP computation
----------------
Session-anchored VWAP (resets at each daily session boundary, mirroring
TradingView's default "Session" anchor).

    VWAP = Σ(hlc3 × volume) / Σ(volume)   — accumulated within the session

Columns required: time (datetime index or column), open, high, low, close, volume

Pine Script reference (TV built-in):
  ta.vwap(hlc3, new_period, 1)  where new_period = timeframe.change("D")
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from app.core.strategy_template import BaseStrategy, StrategyConfig


# ─── Pydantic Config ────────────────────────────────────────────
class VWAPCrossoverConfig(StrategyConfig):
    """Typed, validated configuration for the VWAP Crossover strategy."""

    # ── Trade direction ──────────────────────────────────────────
    trade_direction: Literal["both", "long_only", "short_only"] = Field(
        "both",
        description="Trade Direction",
    )

    # ── VWAP Settings ───────────────────────────────────────────
    anchor: Literal["Session", "Week", "Month"] = Field(
        "Session",
        description="VWAP Anchor Period — Session resets daily (matches TradingView default)",
    )

    # ── SL / TP ─────────────────────────────────────────────────
    sl_type: Literal["candle_low", "atr_trail"] = Field(
        "candle_low",
        description="Stop Loss Type",
    )
    atr_period: int = Field(
        14, ge=2, le=200,
        description="ATR Period — used by atr_trail",
        json_schema_extra={"step": 1, "x-visible-when": {"sl_type": ["atr_trail"]}},
    )
    atr_sl_multiplier: float = Field(
        1.5, ge=0.1, le=10.0,
        description="ATR SL Multiplier  (SL = ATR × value) — atr_trail only",
        json_schema_extra={"step": 0.1, "x-visible-when": {"sl_type": ["atr_trail"]}},
    )

    # ── Grid TP ─────────────────────────────────────────────────
    tp_grid_levels: int = Field(
        2, ge=1, le=20,
        description=(
            "TP Grid Levels — TP is placed at SL_distance × this value from entry. "
            "Grid step = SL distance (same spacing as initial SL)."
        ),
        json_schema_extra={"step": 1},
    )


# ─── Strategy ──────────────────────────────────────────────────
class VWAPCrossover(BaseStrategy):
    """
    VWAP Crossover Strategy.

    Opens a trade when a candle's open and close straddle the VWAP line:
      BUY  — open below VWAP, close above VWAP
      SELL — open above VWAP, close below VWAP

    SL modes  : candle low/high  or  ATR × multiplier
    TP layout : Grid-style — TP = entry ± (SL_distance × tp_grid_levels)
                Each grid step equals the initial SL distance.
    """

    name = "VWAP Crossover"
    description = (
        "Enters when a candle straddles the session VWAP (open on one side, "
        "close on the other). SL = candle low/high or ATR. "
        "TP uses a grid spacing equal to the SL distance."
    )
    config_model = VWAPCrossoverConfig

    # ─── VWAP computation ────────────────────────────────────────
    def _compute_vwap(self, data: pd.DataFrame) -> np.ndarray:
        """
        Session-anchored VWAP aligned with TradingView 'Session' anchor.

        Resets cumulative sums at each new trading day (date boundary).
        Uses hlc3 = (high + low + close) / 3 as the price source.

        Returns an array of VWAP values, same length as data.
        """
        cfg = self.config
        n = len(data)

        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        vol   = data["volume"].values.astype(float)

        hlc3 = (high + low + close) / 3.0

        # Detect session / anchor boundary
        if "time" in data.columns:
            times = pd.to_datetime(data["time"])
        else:
            times = pd.to_datetime(data.index)

        if cfg.anchor == "Session":
            # New period when the DATE changes
            dates = times.dt.date
            new_period = np.zeros(n, dtype=bool)
            new_period[0] = True
            for i in range(1, n):
                new_period[i] = dates.iloc[i] != dates.iloc[i - 1]

        elif cfg.anchor == "Week":
            weeks = times.dt.isocalendar().week.values
            years = times.dt.year.values
            new_period = np.zeros(n, dtype=bool)
            new_period[0] = True
            for i in range(1, n):
                new_period[i] = (weeks[i] != weeks[i - 1]) or (years[i] != years[i - 1])

        elif cfg.anchor == "Month":
            months = times.dt.month.values
            years  = times.dt.year.values
            new_period = np.zeros(n, dtype=bool)
            new_period[0] = True
            for i in range(1, n):
                new_period[i] = (months[i] != months[i - 1]) or (years[i] != years[i - 1])

        else:
            # Fallback: daily
            dates = times.dt.date
            new_period = np.zeros(n, dtype=bool)
            new_period[0] = True
            for i in range(1, n):
                new_period[i] = dates.iloc[i] != dates.iloc[i - 1]

        # Rolling cumulative sums, reset on new_period
        vwap = np.full(n, np.nan)
        cum_tp_vol = 0.0
        cum_vol    = 0.0

        for i in range(n):
            if new_period[i]:
                cum_tp_vol = 0.0
                cum_vol    = 0.0

            v = vol[i]
            if v <= 0:
                # Zero-volume bar: carry forward previous VWAP
                vwap[i] = vwap[i - 1] if i > 0 else np.nan
                continue

            cum_tp_vol += hlc3[i] * v
            cum_vol    += v
            vwap[i]    = cum_tp_vol / cum_vol

        return vwap

    # ─── ATR (Wilder's, matches MT5 / TradingView) ───────────────
    def _compute_atr(self, data: pd.DataFrame, period: int) -> np.ndarray:
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        n = len(close)

        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(
                high[i]  - low[i],
                abs(high[i]  - close[i - 1]),
                abs(low[i]   - close[i - 1]),
            )

        atr = np.full(n, np.nan)
        if n >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        return atr

    # ─── SL / TP helper ──────────────────────────────────────────
    def _calc_sl_tp(
        self,
        direction: str,
        entry: float,
        bar_low: float,
        bar_high: float,
        atr_val: float,
    ):
        """
        Compute (sl_price, tp_price).

        TP uses grid spacing = SL distance, multiplied by ``tp_grid_levels``.
        This means if SL is 10 pips away, each grid step is 10 pips,
        and TP₂ (tp_grid_levels=2) is 20 pips from entry.
        """
        cfg = self.config
        pip = getattr(self, "_pip_value", 0.0001)

        if cfg.sl_type == "candle_low":
            if direction == "BUY":
                sl      = bar_low - pip
                sl_dist = max(entry - sl, pip)           # guard division by zero
                tp      = entry + sl_dist * cfg.tp_grid_levels
            else:
                sl      = bar_high + pip
                sl_dist = max(sl - entry, pip)
                tp      = entry - sl_dist * cfg.tp_grid_levels

        elif cfg.sl_type == "atr_trail":
            if not np.isnan(atr_val) and atr_val > 0:
                sl_dist = atr_val * cfg.atr_sl_multiplier
            else:
                sl_dist = pip * 20                       # 20-pip fallback

            if direction == "BUY":
                sl = entry - sl_dist
                tp = entry + sl_dist * cfg.tp_grid_levels
            else:
                sl = entry + sl_dist
                tp = entry - sl_dist * cfg.tp_grid_levels

        else:
            return None, None

        return round(sl, 6), round(tp, 6)

    # ─── on_bar ──────────────────────────────────────────────────
    def on_bar(self, index: int, data: pd.DataFrame) -> str | tuple:
        """
        Signal logic — called bar-by-bar (no look-ahead).

        Entry conditions:
          BUY  : open[i] < vwap[i]  AND  close[i] > vwap[i]
          SELL : open[i] > vwap[i]  AND  close[i] < vwap[i]

        Only the COMPLETED candle is evaluated; the open of the NEXT bar
        is the actual trade entry price (handled by the engine with
        ``entry = close`` since tester uses bar-close execution).
        """
        cfg = self.config

        # Need at least 2 bars (for ATR / VWAP to have some history)
        if index < 1:
            return "HOLD"

        # ── Compute VWAP ─────────────────────────────────────────
        vwap_arr = self._compute_vwap(data)
        vwap_val = vwap_arr[index]

        if np.isnan(vwap_val):
            return "HOLD"

        bar_open  = float(data["open"].iloc[index])
        bar_close = float(data["close"].iloc[index])
        bar_low   = float(data["low"].iloc[index])
        bar_high  = float(data["high"].iloc[index])

        # ── Entry conditions ─────────────────────────────────────
        #   BUY  : open below VWAP, close above VWAP  (bullish straddle)
        #   SELL : open above VWAP, close below VWAP  (bearish straddle)
        buy_signal  = bar_open < vwap_val and bar_close > vwap_val
        sell_signal = bar_open > vwap_val and bar_close < vwap_val

        if not buy_signal and not sell_signal:
            return "HOLD"

        # ── ATR for atr_trail SL mode ────────────────────────────
        atr_val = 0.0
        if cfg.sl_type == "atr_trail":
            atr_arr = self._compute_atr(data, cfg.atr_period)
            raw     = atr_arr[index]
            atr_val = float(raw) if not np.isnan(raw) else 0.0

        entry = bar_close   # engine executes at close of signal bar

        if buy_signal and cfg.trade_direction in ("both", "long_only"):
            sl, tp = self._calc_sl_tp("BUY", entry, bar_low, bar_high, atr_val)
            return ("BUY", sl, tp)

        if sell_signal and cfg.trade_direction in ("both", "short_only"):
            sl, tp = self._calc_sl_tp("SELL", entry, bar_low, bar_high, atr_val)
            return ("SELL", sl, tp)

        return "HOLD"

    # ─── Indicator overlay ───────────────────────────────────────
    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """
        Returns chart overlays:
          - VWAP          — the session-anchored VWAP line (price overlay)
        """
        vwap_arr = self._compute_vwap(data)
        vwap_list = [
            None if np.isnan(v) else round(float(v), 6)
            for v in vwap_arr
        ]

        return {
            "VWAP": vwap_list,
        }
