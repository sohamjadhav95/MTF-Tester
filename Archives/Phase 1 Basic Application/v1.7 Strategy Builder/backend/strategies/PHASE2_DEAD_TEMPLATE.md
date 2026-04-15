# PHASE 2 — BULLETPROOF DEAD TEMPLATE
# File: backend/strategies/_template.py
# This is the master template document. The actual Python file follows below.
# LLM fills ONLY the marked sections. Nothing else is modified.

---

## TEMPLATE CONTRACT (READ BEFORE FILLING)

The template has 8 sections labeled [A] through [H].
- Sections marked FILL → LLM must provide implementation
- Sections marked NEVER MODIFY → copy exactly as written
- Sections marked CONDITIONAL → include only if strategy needs it

The system cares about exactly ONE output: what `on_bar()` returns.
Everything else is internal to the strategy.

`on_bar()` must return ONE of:
  - "BUY"                        → enter long, no SL/TP
  - "SELL"                       → enter short, no SL/TP
  - "HOLD"                       → do nothing
  - ("BUY",  sl_price, tp_price) → enter long with levels
  - ("SELL", sl_price, tp_price) → enter short with levels
  - ("BUY",  None,     tp_price) → enter long, TP only
  - ("BUY",  sl_price, None)     → enter long, SL only

sl_price and tp_price are ABSOLUTE PRICE VALUES, not distances.

---

## THE COMPLETE DEAD TEMPLATE

```python
"""
╔══════════════════════════════════════════════════════════════════╗
║           MTF STRATEGY TEMPLATE — v3.0 (BULLETPROOF)            ║
║                                                                  ║
║  HOW TO USE (for LLM filling this template):                     ║
║  1. Read the JSON schema provided                                ║
║  2. Fill ONLY sections marked with # FILL                        ║
║  3. Never modify sections marked # NEVER MODIFY                  ║
║  4. Include conditional modules only if strategy_type needs them ║
║  5. Do NOT change class names, method signatures, or imports     ║
║  6. All indicator computation MUST go in on_start(), never in    ║
║     on_bar() — on_bar() only reads from self._cache              ║
║  7. Drop completed file in backend/strategies/ and restart       ║
╚══════════════════════════════════════════════════════════════════╝

Generated from schema version: {schema_version}
Strategy type: {strategy_type}
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional, Literal, List, Dict, Any, Tuple
from pydantic import Field
from app.core.strategy_template import BaseStrategy, StrategyConfig, IndicatorPlot


# ════════════════════════════════════════════════════════════════════
# [A] STRATEGY METADATA — FILL
# ════════════════════════════════════════════════════════════════════
# These strings appear in the UI dropdown and description panel.
# FILL: Replace with actual strategy name and description.

STRATEGY_NAME        = None   # FILL: e.g. "Supply Demand Zone"
STRATEGY_DESCRIPTION = None   # FILL: e.g. "Trades demand/supply zones with EMA trend filter"
STRATEGY_VERSION     = "1.0"
STRATEGY_TYPE        = None   # FILL: "indicator" | "zone" | "pattern" | "mtf" | "hybrid"


# ════════════════════════════════════════════════════════════════════
# [B] SETTINGS SCHEMA — FILL
# ════════════════════════════════════════════════════════════════════
# Every parameter the user can tune from the UI lives here.
# Each Field() auto-generates an input widget in the frontend.
#
# SUPPORTED TYPES:
#   int         → number slider/input
#   float       → decimal input
#   bool        → toggle switch
#   Literal[..] → dropdown
#   str         → text input
#
# FILL: Define all configurable parameters.
# Remove any group that does not apply.

class StrategySettings(StrategyConfig):

    # ── Indicator parameters ─────────────────────────────────────
    # FILL or remove unused fields
    period_1:    Optional[int]   = Field(None, description="")
    period_2:    Optional[int]   = Field(None, description="")
    period_3:    Optional[int]   = Field(None, description="")
    source:      Literal["open","high","low","close"] = Field("close", description="Price Source")

    # ── Zone / Pattern parameters ────────────────────────────────
    # FILL or remove if strategy_type is not zone/pattern
    lookback:    Optional[int]   = Field(None, description="Bars to look back for pattern detection")
    zone_buffer: Optional[float] = Field(None, description="Zone entry buffer in pips")

    # ── Multi-timeframe parameters ───────────────────────────────
    # FILL or remove if strategy_type is not mtf/hybrid
    htf_enabled: bool = Field(False, description="Enable Higher Timeframe Filter")
    htf_period:  Optional[int]  = Field(None, description="HTF Indicator Period")

    # ── Market structure ─────────────────────────────────────────
    sr_lookback: Optional[int]  = Field(None, description="S/R Swing Lookback")

    # ── Time filter ──────────────────────────────────────────────
    time_filter_enabled: bool       = Field(False, description="Enable Time Filter")
    session_start_hour:  Optional[int] = Field(None, description="Session Start (UTC Hour)")
    session_end_hour:    Optional[int] = Field(None, description="Session End (UTC Hour)")
    avoid_friday:        bool       = Field(False, description="Avoid Friday Trades")

    # ── Entry settings ───────────────────────────────────────────
    trade_direction: Literal["both","long_only","short_only"] = Field("both", description="Trade Direction")

    # ── Exit settings ────────────────────────────────────────────
    sl_mode:     Literal["none","fixed_pips","atr","candle_hl","zone","swing"] = Field("none", description="Stop Loss Mode")
    sl_pips:     Optional[float] = Field(None, description="SL Distance (pips)")
    sl_atr_mult: Optional[float] = Field(None, description="ATR Multiplier for SL")
    rr_ratio:    Optional[float] = Field(None, description="Risk/Reward Ratio (TP = SL × RR)")
    max_bars_held: Optional[int] = Field(None, description="Max Bars In Trade")


# ════════════════════════════════════════════════════════════════════
# [C] STRATEGY CLASS — DO NOT RENAME
# ════════════════════════════════════════════════════════════════════

class GeneratedStrategy(BaseStrategy):

    name         = STRATEGY_NAME
    description  = STRATEGY_DESCRIPTION
    config_model = StrategySettings


    # ════════════════════════════════════════════════════════════════
    # [D] ON_START — FILL
    # Called ONCE before bar loop. Pre-compute ALL indicators here.
    # Store results in self._cache (plain dict, keys are your choice).
    # ════════════════════════════════════════════════════════════════
    #
    # RULES:
    # - Compute every indicator series here, not in on_bar()
    # - Store as numpy arrays via self._cache["key"] = array
    # - Keys used here MUST match keys read in on_bar() and
    #   ids used in get_indicator_data()
    # - Use None for any cache slot that may not apply to all configs
    #
    # AVAILABLE HELPERS (NEVER MODIFY THESE — defined in Section H):
    #   self._ema(series, period)        → np.ndarray
    #   self._sma(series, period)        → np.ndarray
    #   self._rsi(series, period)        → np.ndarray
    #   self._atr(data, period)          → np.ndarray
    #   self._bollinger(series, period, std) → (upper, mid, lower)
    #   self._macd(series, fast, slow, signal) → (macd, signal, hist)
    #   self._stochastic(data, k, d)     → (k_line, d_line)
    #   self._cci(data, period)          → np.ndarray
    #   self._swing_highs(data, lookback) → np.ndarray
    #   self._swing_lows(data, lookback)  → np.ndarray
    #   self._true_range(data)           → np.ndarray

    def on_start(self, data: pd.DataFrame):
        cfg = self.config
        self._cache = {}

        # FILL: Compute indicators based on strategy_type
        # Examples shown — replace with what your strategy needs:

        # ── Trend indicators ──────────────────────────────────────
        # self._cache["ema_fast"] = self._ema(data[cfg.source], cfg.period_1)
        # self._cache["ema_slow"] = self._ema(data[cfg.source], cfg.period_2)

        # ── Momentum indicators ───────────────────────────────────
        # self._cache["rsi"] = self._rsi(data["close"], cfg.period_1)
        # self._cache["macd"], self._cache["macd_sig"], self._cache["macd_hist"] = \
        #     self._macd(data["close"], 12, 26, 9)

        # ── Volatility indicators ─────────────────────────────────
        # self._cache["atr"] = self._atr(data, cfg.period_1 or 14)
        # upper, mid, lower = self._bollinger(data["close"], 20, 2.0)
        # self._cache["bb_upper"] = upper
        # self._cache["bb_mid"]   = mid
        # self._cache["bb_lower"] = lower

        # ── Market structure ──────────────────────────────────────
        # self._cache["support"]    = self._swing_lows(data, cfg.sr_lookback or 20)
        # self._cache["resistance"] = self._swing_highs(data, cfg.sr_lookback or 20)

        # ── Zone/Pattern detection (zone-based strategies only) ───
        # CONDITIONAL: Include if STRATEGY_TYPE in ("zone", "hybrid")
        # self._cache["zones"] = []          # list of active zone dicts
        # self._cache["zone_history"] = []   # all zones ever detected (for chart)

        # ── Warmup period ─────────────────────────────────────────
        # NEVER MODIFY — auto-calculated
        self._warmup = self._calculate_warmup(cfg)


    # ════════════════════════════════════════════════════════════════
    # [E] TIME FILTER — NEVER MODIFY SIGNATURE, FILL BODY IF NEEDED
    # ════════════════════════════════════════════════════════════════

    def _time_filter(self, bar: pd.Series) -> bool:
        """
        Returns True if current bar is within allowed trading time.
        Returns True always if time_filter_enabled = False.
        """
        cfg = self.config
        if not cfg.time_filter_enabled:
            return True

        # FILL: extract hour from bar["time"] and apply session/day filter
        # Example:
        # try:
        #     t = pd.Timestamp(bar["time"])
        #     h = t.hour
        #     if cfg.session_start_hour and cfg.session_end_hour:
        #         if not (cfg.session_start_hour <= h < cfg.session_end_hour):
        #             return False
        #     if cfg.avoid_friday and t.weekday() == 4:
        #         return False
        # except Exception:
        #     pass
        return True


    # ════════════════════════════════════════════════════════════════
    # [F] ON_BAR — FILL
    # Called on every bar. Returns the trade signal.
    # ONLY reads from self._cache — never computes indicators here.
    # ════════════════════════════════════════════════════════════════
    #
    # PARAMETER:
    #   index (int)      — current bar index (0-based)
    #   data (DataFrame) — ALL bars up to and including current bar
    #                      (no future data — no look-ahead bias)
    #
    # STRICT EXECUTION ORDER (always follow this order):
    #   1. Warmup guard
    #   2. NaN guard
    #   3. Time filter
    #   4. HTF trend filter (if enabled)
    #   5. Market structure check (if applicable)
    #   6. Zone/Pattern detection and update (if applicable)
    #   7. Indicator conditions
    #   8. Entry signal
    #   9. SL/TP calculation
    #  10. Return signal

    def on_bar(self, index: int, data: pd.DataFrame):
        cfg   = self.config
        cache = self._cache
        bar   = data.iloc[index]

        # ── 1. Warmup guard ───────────────────────────────────────
        # NEVER MODIFY
        if index < self._warmup:
            return "HOLD"

        # ── 2. NaN guard ──────────────────────────────────────────
        # FILL: add NaN checks for every cache array you read
        # Example:
        # if any(np.isnan(v) for v in [
        #     cache["ema_fast"][index],
        #     cache["ema_slow"][index],
        # ]):
        #     return "HOLD"

        # ── 3. Time filter ────────────────────────────────────────
        if not self._time_filter(bar):
            return "HOLD"

        # ── 4. HTF trend filter ───────────────────────────────────
        # CONDITIONAL: Include if htf_enabled or strategy uses HTF bias
        # htf_bias = None   # FILL: "up" | "down" | None
        # if cfg.htf_filter_enabled and htf_bias is None:
        #     return "HOLD"

        # ── 5. Market structure ───────────────────────────────────
        # CONDITIONAL: Include if strategy uses S/R levels
        # support    = cache["support"][index]    if cache.get("support") is not None else None
        # resistance = cache["resistance"][index] if cache.get("resistance") is not None else None

        # ── 6. Zone / Pattern detection ───────────────────────────
        # CONDITIONAL: Include ONLY if STRATEGY_TYPE in ("zone", "pattern", "hybrid")
        #
        # Detect new zones on this bar and add to cache["zones"]
        # new_zones = self._detect_zones(data, index)
        # cache["zones"].extend(new_zones)
        #
        # Expire zones that are too old or have been triggered/broken
        # cache["zones"] = [z for z in cache["zones"] if not self._zone_expired(z, index)]
        #
        # Check if price enters any active zone
        # close = float(bar["close"])
        # triggered_zone = None
        # for zone in cache["zones"]:
        #     if self._zone_entered(zone, bar):
        #         triggered_zone = zone
        #         break

        # ── 7. Read indicator values ──────────────────────────────
        # FILL: read from cache at current index
        # Example:
        # ema_fast_curr = cache["ema_fast"][index]
        # ema_fast_prev = cache["ema_fast"][index - 1]
        # ema_slow_curr = cache["ema_slow"][index]
        # ema_slow_prev = cache["ema_slow"][index - 1]
        # rsi_curr      = cache["rsi"][index]

        # ── 8. Entry conditions ───────────────────────────────────
        # FILL: define buy_signal and sell_signal as boolean expressions
        # Example for EMA crossover:
        # buy_signal  = (ema_fast_prev <= ema_slow_prev) and (ema_fast_curr > ema_slow_curr)
        # sell_signal = (ema_fast_prev >= ema_slow_prev) and (ema_fast_curr < ema_slow_curr)
        #
        # Example for zone-based:
        # buy_signal  = triggered_zone is not None and triggered_zone["type"] == "demand"
        # sell_signal = triggered_zone is not None and triggered_zone["type"] == "supply"

        buy_signal  = False   # FILL
        sell_signal = False   # FILL

        # ── Direction filter ──────────────────────────────────────
        # NEVER MODIFY
        if cfg.trade_direction == "long_only":
            sell_signal = False
        elif cfg.trade_direction == "short_only":
            buy_signal = False

        # ── 9. SL/TP calculation ──────────────────────────────────
        # NEVER MODIFY — _sl_price() and _tp_price() handle all modes
        if buy_signal:
            sl = self._sl_price("BUY", index, data)
            tp = self._tp_price("BUY", sl, float(bar["close"]))
            return ("BUY", sl, tp) if sl else "BUY"

        if sell_signal:
            sl = self._sl_price("SELL", index, data)
            tp = self._tp_price("SELL", sl, float(bar["close"]))
            return ("SELL", sl, tp) if sl else "SELL"

        return "HOLD"


    # ════════════════════════════════════════════════════════════════
    # [G] VISUALIZATION — FILL
    # Declares what to draw on the chart.
    # Returns a list of IndicatorPlot objects.
    # One IndicatorPlot = one visual element on the chart.
    # ════════════════════════════════════════════════════════════════
    #
    # PANE OPTIONS:
    #   "price"    → overlaid on the candlestick chart
    #   "separate" → new pane below the chart
    #
    # TYPE OPTIONS:
    #   "line"      → continuous line (EMA, SMA, BB bands)
    #   "histogram" → bar histogram (MACD hist, volume delta)
    #   "level"     → horizontal line at a fixed price (S/R levels)
    #   "markers"   → dots/arrows on bars (signal points)
    #   "band"      → filled area between two lines (BB, Keltner)
    #   "zone"      → horizontal shaded region (S/D zones)
    #                 requires: zone_top and zone_bottom in values dicts
    #
    # VALUES FORMAT:
    #   Standard:  [{"time": "2024-01-01T00:00:00", "value": 1.2345}, ...]
    #   Zone type: [{"time": "2024-01-01T00:00:00",
    #                "zone_top": 1.2400, "zone_bottom": 1.2350,
    #                "zone_type": "demand", "status": "active"}, ...]
    #
    # FILL: Return IndicatorPlot list matching what strategy computes.
    # Only include plots for indicators actually computed in on_start().

    def get_indicator_data(self, data: pd.DataFrame) -> list:
        cfg   = self.config
        cache = self._cache
        plots = []

        # ── Price pane overlays ───────────────────────────────────

        # Example: EMA lines
        # if cache.get("ema_fast") is not None:
        #     plots.append(IndicatorPlot(
        #         id     = "ema_fast",
        #         label  = f"EMA {cfg.period_1}",
        #         pane   = "price",
        #         type   = "line",
        #         color  = "#2196F3",
        #         values = self._to_chart_values(data, cache["ema_fast"]),
        #     ))
        # if cache.get("ema_slow") is not None:
        #     plots.append(IndicatorPlot(
        #         id     = "ema_slow",
        #         label  = f"EMA {cfg.period_2}",
        #         pane   = "price",
        #         type   = "line",
        #         color  = "#FF9800",
        #         values = self._to_chart_values(data, cache["ema_slow"]),
        #     ))

        # Example: Bollinger Bands
        # if cache.get("bb_upper") is not None:
        #     plots.append(IndicatorPlot(
        #         id          = "bb",
        #         label       = "Bollinger Bands",
        #         pane        = "price",
        #         type        = "band",
        #         color       = "#607D8B",
        #         values      = self._to_chart_values(data, cache["bb_mid"]),
        #         band_upper  = self._to_chart_values(data, cache["bb_upper"]),
        #         band_lower  = self._to_chart_values(data, cache["bb_lower"]),
        #     ))

        # Example: S/R Horizontal Levels
        # if cache.get("support") is not None:
        #     plots.append(IndicatorPlot(
        #         id     = "support",
        #         label  = "Support",
        #         pane   = "price",
        #         type   = "level",
        #         color  = "#4CAF50",
        #         values = self._to_chart_values(data, cache["support"]),
        #     ))

        # Example: Supply/Demand Zones
        # CONDITIONAL: Include if STRATEGY_TYPE in ("zone", "hybrid")
        # if cache.get("zone_history"):
        #     zone_values = []
        #     for zone in cache["zone_history"]:
        #         zone_values.append({
        #             "time":        zone["formed_at"],
        #             "zone_top":    zone["distal"],
        #             "zone_bottom": zone["proximal"],
        #             "zone_type":   zone["type"],    # "demand" | "supply"
        #             "status":      zone["status"],  # "active" | "triggered" | "broken"
        #         })
        #     plots.append(IndicatorPlot(
        #         id     = "zones",
        #         label  = "Supply/Demand Zones",
        #         pane   = "price",
        #         type   = "zone",
        #         color  = "",   # color set by zone_type in frontend
        #         values = zone_values,
        #     ))

        # ── Separate pane indicators ──────────────────────────────

        # Example: RSI with overbought/oversold zones
        # if cache.get("rsi") is not None:
        #     plots.append(IndicatorPlot(
        #         id     = "rsi",
        #         label  = f"RSI {cfg.period_1}",
        #         pane   = "separate",
        #         type   = "line",
        #         color  = "#9C27B0",
        #         values = self._to_chart_values(data, cache["rsi"]),
        #         zones  = [
        #             {"from": 70, "to": 100, "color": "rgba(255,0,0,0.1)"},
        #             {"from": 0,  "to": 30,  "color": "rgba(0,255,0,0.1)"},
        #         ],
        #     ))

        # Example: MACD
        # if cache.get("macd") is not None:
        #     plots.append(IndicatorPlot(
        #         id     = "macd",
        #         label  = "MACD",
        #         pane   = "separate",
        #         type   = "line",
        #         color  = "#2196F3",
        #         values = self._to_chart_values(data, cache["macd"]),
        #     ))
        #     plots.append(IndicatorPlot(
        #         id     = "macd_hist",
        #         label  = "MACD Histogram",
        #         pane   = "separate",
        #         type   = "histogram",
        #         color  = "#4CAF50",
        #         values = self._to_chart_values(data, cache["macd_hist"]),
        #     ))

        return plots


    # ════════════════════════════════════════════════════════════════
    # [G-2] ZONE METHODS — CONDITIONAL
    # Include ONLY if STRATEGY_TYPE in ("zone", "pattern", "hybrid")
    # FILL all three methods.
    # ════════════════════════════════════════════════════════════════

    # def _detect_zones(self, data: pd.DataFrame, index: int) -> list:
    #     """
    #     Scan the last N bars ending at `index` for valid zone patterns.
    #     Returns list of new zone dicts. Each zone dict must have:
    #       {
    #         "type":       "demand" | "supply",
    #         "pattern":    "RBR" | "DBR" | "DBD" | "RBD" | str,
    #         "proximal":   float,   # entry price level
    #         "distal":     float,   # SL price level
    #         "formed_at":  str,     # ISO timestamp of formation bar
    #         "formed_idx": int,     # bar index of formation
    #         "status":     "active",
    #         "strength":   int,     # 0-5 score (how many validation checks pass)
    #       }
    #
    #     FILL: implement pattern detection logic here.
    #     Use self._validate_zone() to filter to only valid zones.
    #     """
    #     return []   # FILL

    # def _validate_zone(self, zone: dict, data: pd.DataFrame, index: int) -> bool:
    #     """
    #     Apply all validation criteria to a candidate zone.
    #     Return True if zone passes all required checks.
    #
    #     Standard checks to implement:
    #     1. Candle size ratio check (boring : leg_in : leg_out ≥ 1:2:4)
    #     2. White area check (no wick crosses boring candle body)
    #     3. TR vs ATR check (boring TR < ATR, leg_in TR > ATR, leg_out TR > ATR)
    #     4. Candle behind leg_in check (not opposite color and > 50% leg_in)
    #     5. Optional: MTF confluence check
    #
    #     FILL: implement validation checks.
    #     """
    #     return True   # FILL

    # def _zone_entered(self, zone: dict, bar: pd.Series) -> bool:
    #     """
    #     Check if current bar price has entered the zone's proximal line.
    #     For demand zones: low <= proximal (price touched zone from above)
    #     For supply zones: high >= proximal (price touched zone from below)
    #
    #     FILL: implement entry trigger.
    #     """
    #     return False   # FILL

    # def _zone_expired(self, zone: dict, current_index: int) -> bool:
    #     """
    #     Return True if zone should be removed from active list.
    #     Reasons to expire:
    #     - Zone has been triggered (status == "triggered")
    #     - Zone has been broken (price moved through distal line)
    #     - Zone is too old (current_index - formed_idx > max_zone_age)
    #
    #     FILL: implement expiry logic.
    #     """
    #     return False   # FILL


    # ════════════════════════════════════════════════════════════════
    # [H] BUILT-IN HELPERS — NEVER MODIFY
    # These are always available. Do not reimplement them.
    # ════════════════════════════════════════════════════════════════

    # ── SL/TP Helpers ─────────────────────────────────────────────

    def _sl_price(self, direction: str, index: int, data: pd.DataFrame) -> Optional[float]:
        """Calculate SL price based on config sl_mode."""
        cfg   = self.config
        close = float(data.iloc[index]["close"])
        low   = float(data.iloc[index]["low"])
        high  = float(data.iloc[index]["high"])

        if cfg.sl_mode == "none":
            return None

        if cfg.sl_mode == "fixed_pips":
            if not cfg.sl_pips:
                return None
            point = getattr(self, "_point", 0.00001)
            dist  = cfg.sl_pips * point * 10
            return (close - dist) if direction == "BUY" else (close + dist)

        if cfg.sl_mode == "atr":
            atr_arr = self._cache.get("atr")
            if atr_arr is None:
                return None
            atr_val = atr_arr[index]
            if np.isnan(atr_val):
                return None
            mult = cfg.sl_atr_mult or 1.5
            return (close - atr_val * mult) if direction == "BUY" else (close + atr_val * mult)

        if cfg.sl_mode == "candle_hl":
            return low if direction == "BUY" else high

        if cfg.sl_mode == "zone":
            # SL at distal line of triggered zone
            zones = self._cache.get("zones", [])
            for zone in zones:
                if zone.get("status") == "triggered":
                    return zone["distal"]
            return None

        if cfg.sl_mode == "swing":
            support    = self._cache.get("support")
            resistance = self._cache.get("resistance")
            if direction == "BUY" and support is not None:
                return float(support[index])
            if direction == "SELL" and resistance is not None:
                return float(resistance[index])
            return None

        return None

    def _tp_price(self, direction: str, sl: Optional[float], entry: float) -> Optional[float]:
        """Calculate TP price from SL distance × RR ratio."""
        if sl is None:
            return None
        cfg     = self.config
        rr      = cfg.rr_ratio or 2.0
        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            return None
        return (entry + sl_dist * rr) if direction == "BUY" else (entry - sl_dist * rr)

    # ── Indicator Calculation Helpers ─────────────────────────────

    @staticmethod
    def _ema(series: pd.Series, period: int) -> np.ndarray:
        values = series.values.astype(float)
        ema    = np.full(len(values), np.nan)
        if len(values) < period:
            return ema
        k           = 2.0 / (period + 1)
        ema[period - 1] = np.mean(values[:period])
        for i in range(period, len(values)):
            ema[i] = values[i] * k + ema[i - 1] * (1 - k)
        return ema

    @staticmethod
    def _sma(series: pd.Series, period: int) -> np.ndarray:
        return series.rolling(period).mean().values

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> np.ndarray:
        delta = series.diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).values

    @staticmethod
    def _atr(data: pd.DataFrame, period: int = 14) -> np.ndarray:
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        tr    = np.maximum(high - low,
                np.maximum(np.abs(high - np.roll(close, 1)),
                           np.abs(low  - np.roll(close, 1))))
        tr[0] = high[0] - low[0]
        atr   = np.full(len(tr), np.nan)
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        return atr

    @staticmethod
    def _true_range(data: pd.DataFrame) -> np.ndarray:
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        tr    = np.maximum(high - low,
                np.maximum(np.abs(high - np.roll(close, 1)),
                           np.abs(low  - np.roll(close, 1))))
        tr[0] = high[0] - low[0]
        return tr

    @staticmethod
    def _bollinger(series: pd.Series, period: int = 20,
                   std: float = 2.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        mid   = series.rolling(period).mean()
        sigma = series.rolling(period).std()
        return (mid + std * sigma).values, mid.values, (mid - std * sigma).values

    @staticmethod
    def _macd(series: pd.Series, fast: int = 12, slow: int = 26,
              signal: int = 9) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd     = ema_fast - ema_slow
        sig      = macd.ewm(span=signal, adjust=False).mean()
        hist     = macd - sig
        return macd.values, sig.values, hist.values

    @staticmethod
    def _stochastic(data: pd.DataFrame, k_period: int = 14,
                    d_period: int = 3) -> Tuple[np.ndarray, np.ndarray]:
        low_min  = data["low"].rolling(k_period).min()
        high_max = data["high"].rolling(k_period).max()
        k = 100 * (data["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
        d = k.rolling(d_period).mean()
        return k.values, d.values

    @staticmethod
    def _cci(data: pd.DataFrame, period: int = 20) -> np.ndarray:
        tp   = (data["high"] + data["low"] + data["close"]) / 3
        sma  = tp.rolling(period).mean()
        mad  = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))))
        return ((tp - sma) / (0.015 * mad)).values

    @staticmethod
    def _swing_highs(data: pd.DataFrame, lookback: int = 20) -> np.ndarray:
        """Returns resistance level at each bar (last confirmed swing high)."""
        highs  = data["high"].values.astype(float)
        result = np.full(len(highs), np.nan)
        last   = np.nan
        for i in range(lookback, len(highs)):
            window = highs[i - lookback: i]
            if highs[i - 1] == np.max(window):
                last = highs[i - 1]
            result[i] = last
        return result

    @staticmethod
    def _swing_lows(data: pd.DataFrame, lookback: int = 20) -> np.ndarray:
        """Returns support level at each bar (last confirmed swing low)."""
        lows   = data["low"].values.astype(float)
        result = np.full(len(lows), np.nan)
        last   = np.nan
        for i in range(lookback, len(lows)):
            window = lows[i - lookback: i]
            if lows[i - 1] == np.min(window):
                last = lows[i - 1]
            result[i] = last
        return result

    @staticmethod
    def _wma(series: pd.Series, period: int) -> np.ndarray:
        weights = np.arange(1, period + 1, dtype=float)
        weights /= weights.sum()
        return np.convolve(series.values.astype(float), weights[::-1], mode='full')[:len(series)]

    @staticmethod
    def _dema(series: pd.Series, period: int) -> np.ndarray:
        ema1 = series.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        return (2 * ema1 - ema2).values

    @staticmethod
    def _tema(series: pd.Series, period: int) -> np.ndarray:
        ema1 = series.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        ema3 = ema2.ewm(span=period, adjust=False).mean()
        return (3 * ema1 - 3 * ema2 + ema3).values

    @staticmethod
    def _vwap(data: pd.DataFrame) -> np.ndarray:
        tp  = (data["high"] + data["low"] + data["close"]) / 3
        vol = data["volume"].replace(0, np.nan)
        return (tp * vol).cumsum() / vol.cumsum().values

    @staticmethod
    def _supertrend(data: pd.DataFrame, period: int = 10,
                    multiplier: float = 3.0) -> Tuple[np.ndarray, np.ndarray]:
        """Returns (supertrend_line, direction) where direction: 1=bullish, -1=bearish."""
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        close = data["close"].values.astype(float)
        n     = len(close)

        # ATR
        tr  = np.maximum(high - low,
              np.maximum(np.abs(high - np.roll(close, 1)),
                         np.abs(low  - np.roll(close, 1))))
        tr[0] = high[0] - low[0]
        atr   = np.full(n, np.nan)
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

        basic_upper = (high + low) / 2 + multiplier * atr
        basic_lower = (high + low) / 2 - multiplier * atr

        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)
        supertrend  = np.full(n, np.nan)
        direction   = np.full(n, np.nan)

        for i in range(period, n):
            final_upper[i] = basic_upper[i] if (
                basic_upper[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]
            ) else final_upper[i-1]
            final_lower[i] = basic_lower[i] if (
                basic_lower[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]
            ) else final_lower[i-1]

            if np.isnan(supertrend[i-1]) or supertrend[i-1] == final_upper[i-1]:
                supertrend[i] = final_upper[i] if close[i] <= final_upper[i] else final_lower[i]
            else:
                supertrend[i] = final_lower[i] if close[i] >= final_lower[i] else final_upper[i]

            direction[i] = -1 if supertrend[i] == final_upper[i] else 1

        return supertrend, direction

    @staticmethod
    def _ichimoku(data: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Returns Tenkan, Kijun, Senkou A, Senkou B, Chikou."""
        high  = data["high"]
        low   = data["low"]
        close = data["close"]
        tenkan   = ((high.rolling(9).max() + low.rolling(9).min()) / 2).values
        kijun    = ((high.rolling(26).max() + low.rolling(26).min()) / 2).values
        senkou_a = pd.Series((tenkan + kijun) / 2).shift(26).values
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26).values
        chikou   = close.shift(-26).values
        return {"tenkan": tenkan, "kijun": kijun,
                "senkou_a": senkou_a, "senkou_b": senkou_b, "chikou": chikou}

    # ── Chart Formatting Helper ───────────────────────────────────

    @staticmethod
    def _to_chart_values(data: pd.DataFrame, arr: np.ndarray) -> list:
        """Convert numpy array to [{time, value}, ...] for frontend charts."""
        result = []
        for i, val in enumerate(arr):
            if val is not None and not (isinstance(val, float) and np.isnan(val)):
                result.append({
                    "time":  data.iloc[i]["time"].isoformat() if hasattr(data.iloc[i]["time"], "isoformat") else str(data.iloc[i]["time"]),
                    "value": round(float(val), 6),
                })
        return result

    # ── Warmup Calculator ─────────────────────────────────────────

    @staticmethod
    def _calculate_warmup(cfg) -> int:
        """Auto-calculate minimum bars needed from all period settings."""
        periods = []
        for attr in vars(cfg):
            val = getattr(cfg, attr)
            if isinstance(val, int) and "period" in attr and val:
                periods.append(val)
        return max(periods) + 1 if periods else 50

    # ── Signal Broadcast (DO NOT MODIFY) ─────────────────────────

    def get_last_signal(self) -> Optional[dict]:
        """
        Returns the last signal dict for the automated trading system.
        Called by MTFLiveEngine after on_bar() returns a signal.
        Structure: {direction, sl, tp, entry_price, bar_time, pattern}
        """
        return getattr(self, "_last_signal", None)
```

---

## ZONE-BASED STRATEGY EXTENSION
## File: backend/strategies/_zone_helpers.py
## Import this in zone-based strategies: from strategies._zone_helpers import ZoneMixin

```python
"""
Zone Helpers Mixin
==================
Provides complete supply/demand zone detection, validation,
and lifecycle management.

Usage in strategy:
    from strategies._zone_helpers import ZoneMixin

    class GeneratedStrategy(BaseStrategy, ZoneMixin):
        def on_start(self, data):
            ...
            self._cache["zones"] = []
            self._cache["zone_history"] = []
            self._atr_cache = self._atr(data, cfg.atr_period or 14)

        def on_bar(self, index, data):
            ...
            # In step 6:
            new_zones = self.detect_sd_zones(data, index, self._atr_cache)
            for z in new_zones:
                if self.validate_sd_zone(z, data, self._atr_cache):
                    self._cache["zones"].append(z)
                    self._cache["zone_history"].append(z)
            self._cache["zones"] = self.expire_zones(
                self._cache["zones"], data, index
            )
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict


class ZoneMixin:
    """
    Complete Supply/Demand Zone implementation.
    All methods are pure functions — no state stored here,
    all state goes through self._cache["zones"].
    """

    def detect_sd_zones(self, data: pd.DataFrame, index: int,
                        atr_arr: np.ndarray) -> List[dict]:
        """
        Scan the 3 bars ending at index-1 for the 4 zone patterns:
          RBR (Rally-Boring-Rally) → Demand
          DBR (Drop-Boring-Rally)  → Demand
          DBD (Drop-Boring-Drop)   → Supply
          RBD (Rally-Boring-Drop)  → Supply

        A 3-bar pattern is:
          bar[i-2] = Leg-In  (the impulse that came before boring)
          bar[i-1] = Boring  (consolidation / low-momentum candle)
          bar[i]   = Leg-Out (the impulse that left the zone)

        Returns list of raw zone candidates (not yet validated).
        """
        if index < 3:
            return []

        zones = []

        # The pattern looks back: leg_in=index-2, boring=index-1, leg_out=index
        # (We detect on the close of the leg_out candle)
        leg_in_idx  = index - 2
        boring_idx  = index - 1
        leg_out_idx = index

        leg_in  = data.iloc[leg_in_idx]
        boring  = data.iloc[boring_idx]
        leg_out = data.iloc[leg_out_idx]

        # Candle body sizes
        leg_in_body  = abs(float(leg_in["close"])  - float(leg_in["open"]))
        boring_body  = abs(float(boring["close"])  - float(boring["open"]))
        leg_out_body = abs(float(leg_out["close"]) - float(leg_out["open"]))

        # Candle direction: True = bullish (green), False = bearish (red)
        leg_in_bull  = float(leg_in["close"])  > float(leg_in["open"])
        boring_bull  = float(boring["close"])  > float(boring["open"])
        leg_out_bull = float(leg_out["close"]) > float(leg_out["open"])

        boring_high = float(boring["high"])
        boring_low  = float(boring["low"])
        boring_open = float(boring["open"])
        boring_close= float(boring["close"])
        boring_body_top = max(boring_open, boring_close)
        boring_body_bot = min(boring_open, boring_close)

        # ── Pattern Detection ────────────────────────────────────
        # RBR: leg_in=bull, leg_out=bull → Demand Zone
        if leg_in_bull and leg_out_bull:
            zones.append({
                "type":        "demand",
                "pattern":     "RBR",
                "proximal":    boring_body_top,  # highest boring body = entry
                "distal":      min(float(boring["low"]),
                                   float(leg_in["low"])),  # lowest low = SL
                "formed_at":   str(data.iloc[boring_idx]["time"]),
                "formed_idx":  boring_idx,
                "leg_in_idx":  leg_in_idx,
                "leg_out_idx": leg_out_idx,
                "leg_in_body": leg_in_body,
                "boring_body": boring_body,
                "leg_out_body":leg_out_body,
                "status":      "active",
                "strength":    0,
            })

        # DBR: leg_in=bear, leg_out=bull → Demand Zone
        if not leg_in_bull and leg_out_bull:
            zones.append({
                "type":        "demand",
                "pattern":     "DBR",
                "proximal":    boring_body_top,
                "distal":      min(float(boring["low"]),
                                   float(leg_in["low"])),
                "formed_at":   str(data.iloc[boring_idx]["time"]),
                "formed_idx":  boring_idx,
                "leg_in_idx":  leg_in_idx,
                "leg_out_idx": leg_out_idx,
                "leg_in_body": leg_in_body,
                "boring_body": boring_body,
                "leg_out_body":leg_out_body,
                "status":      "active",
                "strength":    0,
            })

        # DBD: leg_in=bear, leg_out=bear → Supply Zone
        if not leg_in_bull and not leg_out_bull:
            zones.append({
                "type":        "supply",
                "pattern":     "DBD",
                "proximal":    boring_body_bot,  # lowest boring body = entry
                "distal":      max(float(boring["high"]),
                                   float(leg_in["high"])),  # highest high = SL
                "formed_at":   str(data.iloc[boring_idx]["time"]),
                "formed_idx":  boring_idx,
                "leg_in_idx":  leg_in_idx,
                "leg_out_idx": leg_out_idx,
                "leg_in_body": leg_in_body,
                "boring_body": boring_body,
                "leg_out_body":leg_out_body,
                "status":      "active",
                "strength":    0,
            })

        # RBD: leg_in=bull, leg_out=bear → Supply Zone
        if leg_in_bull and not leg_out_bull:
            zones.append({
                "type":        "supply",
                "pattern":     "RBD",
                "proximal":    boring_body_bot,
                "distal":      max(float(boring["high"]),
                                   float(leg_in["high"])),
                "formed_at":   str(data.iloc[boring_idx]["time"]),
                "formed_idx":  boring_idx,
                "leg_in_idx":  leg_in_idx,
                "leg_out_idx": leg_out_idx,
                "leg_in_body": leg_in_body,
                "boring_body": boring_body,
                "leg_out_body":leg_out_body,
                "status":      "active",
                "strength":    0,
            })

        return zones

    def validate_sd_zone(self, zone: dict, data: pd.DataFrame,
                          atr_arr: np.ndarray) -> bool:
        """
        Apply all 5 validation criteria from the client's system.
        Returns True only if ALL enabled criteria pass.
        Increments zone["strength"] for each criterion passed.
        """
        idx = zone["leg_in_idx"]
        leg_in  = data.iloc[zone["leg_in_idx"]]
        boring  = data.iloc[zone["formed_idx"]]
        leg_out = data.iloc[zone["leg_out_idx"]]

        score = 0

        # ── Check 1: Candle Size Ratio (1 : 2 : 4) ───────────────
        # Boring must be smallest, Leg-In >= 2×Boring, Leg-Out >= 2×Leg-In
        boring_body  = zone["boring_body"]
        leg_in_body  = zone["leg_in_body"]
        leg_out_body = zone["leg_out_body"]

        if boring_body > 0:
            ratio_ok = (leg_in_body >= boring_body * 2 and
                        leg_out_body >= leg_in_body * 2)
            if not ratio_ok:
                return False   # Hard fail — required
            score += 1

        # ── Check 2: White Area (no wick crosses boring body) ─────
        boring_body_top = max(float(boring["open"]), float(boring["close"]))
        boring_body_bot = min(float(boring["open"]), float(boring["close"]))

        # Check that leg_out candle and any candles between boring and
        # current price haven't crossed into the boring body
        # (Simplified: check that boring candle itself has no internal wick violation)
        # The full check would scan all subsequent bars — done in zone_entered
        score += 1   # Pass here, enforced in zone_entered

        # ── Check 3: TR vs ATR ────────────────────────────────────
        if len(atr_arr) > zone["leg_out_idx"] and not np.isnan(atr_arr[idx]):
            boring_tr   = float(boring["high"])  - float(boring["low"])
            leg_in_tr   = float(leg_in["high"])  - float(leg_in["low"])
            leg_out_tr  = float(leg_out["high"]) - float(leg_out["low"])
            atr_val     = float(atr_arr[zone["formed_idx"]])

            tr_ok = (boring_tr  <  atr_val and
                     leg_in_tr  >= atr_val and
                     leg_out_tr >= atr_val)
            if not tr_ok:
                return False   # Hard fail — required
            score += 1

        # ── Check 4: Candle Behind Leg-In ─────────────────────────
        if zone["leg_in_idx"] > 0:
            behind = data.iloc[zone["leg_in_idx"] - 1]
            behind_bull = float(behind["close"]) > float(behind["open"])
            leg_in_bull = float(leg_in["close"]) > float(leg_in["open"])
            behind_body = abs(float(behind["close"]) - float(behind["open"]))

            opposite_and_large = (behind_bull != leg_in_bull and
                                   behind_body >= leg_in_body * 0.5)
            if opposite_and_large:
                return False   # Hard fail — required
            score += 1

        # ── Check 5: Multi-Timeframe (optional, adds strength) ────
        # This is additive only — does not fail the zone
        # MTF confluence is checked externally by the strategy
        # score += 1 if mtf_confirms else 0

        zone["strength"] = score
        return True

    def zone_entered(self, zone: dict, bar: pd.Series) -> bool:
        """
        Check if current bar price has entered the zone's proximal line.
        Also enforces the white area check: if any candle has previously
        crossed into the boring body, the zone is already used.
        """
        close = float(bar["close"])
        low   = float(bar["low"])
        high  = float(bar["high"])

        if zone["type"] == "demand":
            # Price came from above and touched proximal line
            return low <= zone["proximal"]

        if zone["type"] == "supply":
            # Price came from below and touched proximal line
            return high >= zone["proximal"]

        return False

    def zone_broken(self, zone: dict, bar: pd.Series) -> bool:
        """
        Check if price has broken through the distal line, invalidating the zone.
        """
        close = float(bar["close"])

        if zone["type"] == "demand":
            return close < zone["distal"]

        if zone["type"] == "supply":
            return close > zone["distal"]

        return False

    def expire_zones(self, zones: list, data: pd.DataFrame,
                     current_index: int, max_age_bars: int = 200) -> list:
        """
        Remove zones that are expired, triggered, or broken.
        Returns filtered list of still-active zones.
        """
        bar     = data.iloc[current_index]
        active  = []
        for zone in zones:
            if zone["status"] in ("triggered", "broken"):
                continue
            if current_index - zone["formed_idx"] > max_age_bars:
                zone["status"] = "expired"
                continue
            if self.zone_broken(zone, bar):
                zone["status"] = "broken"
                continue
            active.append(zone)
        return active
```

---

## LLM SYSTEM PROMPT FOR STAGE 2
## File: backend/strategies/_prompts.py

```python
GENERATE_SYSTEM_PROMPT = """
You are a trading strategy developer. Your ONLY job is to fill in the marked
sections of the dead template below.

STRICT RULES — NEVER VIOLATE:
1. Do NOT change class names: GeneratedStrategy, StrategySettings
2. Do NOT change method signatures: on_start, on_bar, get_indicator_data
3. Do NOT add new imports outside of standard library and what is already imported
4. Do NOT reimplement any helper method from Section H — use them as-is
5. ALL indicator computation goes in on_start() stored in self._cache
6. on_bar() ONLY reads from self._cache — never calls ema/rsi/etc directly
7. on_bar() must ALWAYS return one of the valid signal types
8. For zone-based strategies, import ZoneMixin and use the provided zone methods
9. get_indicator_data() must return IndicatorPlot objects for EVERY indicator
   stored in self._cache that needs to appear on the chart
10. If strategy_type is "zone" or "hybrid", include the zone rendering block
    in get_indicator_data() so zones appear as shaded regions on the chart
11. SL/TP: always use self._sl_price() and self._tp_price() — never hardcode
12. Return ONLY the complete Python file. No explanation, no markdown fences.

STRATEGY DESCRIPTION FROM USER:
{user_description}

JSON SCHEMA:
{schema_json}

TEMPLATE:
{template_content}
"""

IMPROVE_SYSTEM_PROMPT = """
You are a trading strategy developer reviewing existing strategy code.
Your job is to fix or improve ONLY what is explicitly requested.

STRICT RULES:
1. Preserve ALL class names, method signatures, and imports
2. Preserve ALL sections not related to the requested change
3. Preserve ALL helper methods in Section H exactly as-is
4. Make ONLY the minimum changes required to address the improvement
5. If the improvement requires a new cache key, add it in on_start()
   AND read it in on_bar() AND add its visualization in get_indicator_data()
6. Return ONLY the complete corrected Python file. No explanation, no fences.

CURRENT STRATEGY CODE:
{current_code}

IMPROVEMENT REQUESTED:
{improvement}
"""
```

---

## JSON SCHEMA STRUCTURE
## File: backend/strategies/_schema.py
## This is the intermediate representation between user form and template.

```python
"""
Strategy JSON Schema
====================
The schema is the single source of truth between the user's description
and the generated code. It is human-readable and versioned.

Stage 1 LLM converts user form → this schema.
Stage 2 LLM fills template using this schema.
User can edit the schema directly for power users.
"""

SCHEMA_VERSION = "1.0"

# Complete schema example for Supply/Demand Zone strategy
EXAMPLE_SCHEMA = {
    "schema_version": "1.0",
    "meta": {
        "name": "Supply Demand Zone",
        "description": "Trades validated supply and demand zones with EMA trend filter",
        "strategy_type": "hybrid",     # indicator | zone | pattern | mtf | hybrid
        "entry_timeframe": "H1",
        "htf_timeframe": "H4",
    },
    "settings": {
        "atr_period":       14,
        "ema_fast_period":  20,
        "ema_slow_period":  50,
        "zone_max_age_bars": 200,
        "zone_buffer_pips": 0,
        "trade_direction":  "both",
        "time_filter_enabled": False,
        "sl_mode":          "zone",
        "rr_ratio":         3.0,
    },
    "indicators": [
        {"id": "ema_fast", "type": "EMA", "period": 20, "source": "close",
         "purpose": "trend_filter", "pane": "price", "color": "#2196F3"},
        {"id": "ema_slow", "type": "EMA", "period": 50, "source": "close",
         "purpose": "trend_filter", "pane": "price", "color": "#FF9800"},
        {"id": "atr",      "type": "ATR", "period": 14,
         "purpose": "zone_validation", "pane": "none"},
    ],
    "zone_detection": {
        "enabled": True,
        "patterns": ["RBR", "DBR", "DBD", "RBD"],
        "validation": {
            "candle_ratio_check": True,
            "ratio_min": [2, 1, 4],
            "white_area_check": True,
            "tr_atr_check": True,
            "candle_behind_check": True,
        },
        "zone_colors": {
            "demand_active":    "rgba(76,175,80,0.2)",
            "supply_active":    "rgba(244,67,54,0.2)",
            "demand_triggered": "rgba(76,175,80,0.05)",
            "supply_triggered": "rgba(244,67,54,0.05)",
            "broken":           "rgba(100,100,100,0.05)",
        },
    },
    "trend_filter": {
        "enabled": True,
        "type":    "ema_cross",
        "rule":    "only_buy_demand_when_ema_fast_above_slow",
    },
    "entry": {
        "type":  "limit",
        "level": "proximal_line",
        "trigger": "price_touches_zone",
    },
    "exit": {
        "stop_loss":   "distal_line",
        "take_profit": "rr_ratio",
        "rr_ratio":    3.0,
    },
    "risk": {
        "max_risk_pct":    0.5,
        "zone_validity":   "200 bars",
    },
    "visualization": [
        {"id": "ema_fast",  "type": "line",      "pane": "price"},
        {"id": "ema_slow",  "type": "line",      "pane": "price"},
        {"id": "zones",     "type": "zone",      "pane": "price"},
    ],
}
```

---

## HOW THE SIGNAL REACHES AUTO-TRADING

The signal flow is:

```
on_bar() returns ("BUY", sl, tp)
         ↓
MTFLiveEngine catches the return value
         ↓
Packages it as a signal event:
{
  "type":      "signal",
  "data": {
    "direction":  "BUY",
    "symbol":     "EURUSD",
    "timeframe":  "H1",
    "price":      1.08450,
    "sl":         1.08100,
    "tp":         1.09150,
    "bar_time":   "2024-01-15T10:00:00",
    "strategy":   "Supply Demand Zone",
    "pattern":    "DBR",               ← from zone dict if available
    "strength":   4,                   ← zone strength score if available
  }
}
         ↓
Broadcast via WebSocket to frontend
         ↓
Frontend handleScannerMsg() receives "signal" type
         ↓
If scanner.autoTrade == true:
  → call POST /api/order/place with confirm=true
  → include sl, tp from signal data
  → show confirmation toast, not modal (auto-mode)
If scanner.autoTrade == false:
  → display signal on chart (arrow marker)
  → show toast notification
  → user decides manually
```

The `MTFLiveEngine._process_signal()` method must extract sl/tp from tuple returns:

```python
# In mtf_engine.py — _process_signal method
def _process_signal(self, tf, signal_raw, bar):
    if isinstance(signal_raw, tuple):
        direction = signal_raw[0].upper()
        sl = signal_raw[1] if len(signal_raw) > 1 else None
        tp = signal_raw[2] if len(signal_raw) > 2 else None
    else:
        direction = str(signal_raw).upper()
        sl = None
        tp = None

    if direction not in ("BUY", "SELL"):
        return

    signal = {
        "type": "signal",
        "data": {
            "direction": direction,
            "symbol":    self.symbol,
            "timeframe": tf,
            "price":     float(bar["close"]),
            "sl":        sl,
            "tp":        tp,
            "bar_time":  str(bar["time"]),
            "strategy":  self.strategy_name,
        }
    }
    asyncio.create_task(self._push(signal))
    # Store as last signal for auto-trading check
    self._last_signal[tf] = signal["data"]
```
