"""
Pulse Zone Strategy
====================
EMA-based Pulse detection with ATR zone entries.

Logic (from client specification):

1. PULSE DETECTION (Image 1):
   - EMA 20 > EMA 50 → Positive Pulse (uptrend)
   - EMA 20 < EMA 50 → Negative Pulse (downtrend)
   - EMA 20 ≈ EMA 50 (crossover region) → No action

2. ZONE CREATION (Images 2 & 5):
   BUY zone created when ALL conditions met:
     - Pulse is Positive (EMA 20 > EMA 50)
     - Price crosses ABOVE EMA 50
     - Candle is Green (close > open)
     → Zone Price = Close - ATR  (wholesale buy level)

   SELL zone created when ALL conditions met:
     - Pulse is Negative (EMA 20 < EMA 50)
     - Price crosses BELOW EMA 50
     - Candle is Red (close < open)
     → Zone Price = Close + ATR  (premium sell level)

3. ZONE FILL / ENTRY (Images 4 & 5):
   - When price retraces to an unfilled zone → entry signal
   - Cross-check: True Range vs ATR filter (reject abnormal bars)
   - Zone expires after configured validity period

4. SL / TP (Images 3 & 4):
   BUY: SL = zone_price - ATR,  TP = zone_price + (risk × R:R)
   SELL: SL = zone_price + ATR,  TP = zone_price - (risk × R:R)
"""

from strategies._template import BaseStrategy, StrategyConfig
from pydantic import Field
from typing import Literal
import numpy as np
import pandas as pd


# ─── Pydantic Config (auto-generates UI inputs) ────────────────
class PulseZoneConfig(StrategyConfig):
    """All parameters here auto-generate UI inputs."""

    fast_period: int = Field(
        20, ge=2, le=500,
        description="Fast EMA Period",
        json_schema_extra={"step": 1},
    )
    slow_period: int = Field(
        50, ge=2, le=500,
        description="Slow EMA Period",
        json_schema_extra={"step": 1},
    )
    atr_period: int = Field(
        14, ge=2, le=100,
        description="ATR Period",
        json_schema_extra={"step": 1},
    )
    rr_ratio: float = Field(
        2.0, ge=0.1, le=20.0,
        description="Risk / Reward Ratio",
        json_schema_extra={"step": 0.1},
    )
    zone_validity_bars: int = Field(
        50, ge=5, le=5000,
        description="Zone Validity (bars before expiry)",
        json_schema_extra={"step": 1},
    )
    tr_atr_filter: float = Field(
        2.5, ge=1.0, le=10.0,
        description="TR/ATR Filter (reject bars where TR exceeds this × ATR)",
        json_schema_extra={"step": 0.1},
    )
    trade_direction: Literal["both", "long_only", "short_only"] = Field(
        "both",
        description="Trade Direction",
    )


# ─── Strategy ──────────────────────────────────────────────────
class PulseZoneStrategy(BaseStrategy):
    """
    Pulse Zone Strategy — EMA pulse + ATR zone entries.

    Detects trend via EMA 20/50 pulse, creates discounted entry zones
    using ATR, waits for price to retrace to zone, then fires signal
    with calculated SL/TP based on risk-reward ratio.
    """

    name = "Pulse Zone"
    description = (
        "EMA Pulse detection (20/50) with ATR-based zone entries. "
        "Creates buy/sell zones on confirmed crossovers, signals when "
        "price retraces to zone. SL/TP via configurable R:R ratio."
    )
    config_model = PulseZoneConfig

    def __init__(self, settings=None):
        super().__init__(settings)
        # ── Persistent state — survives on_start recalibration ──
        # Zones must persist across bar loops and live re-calibrations.
        # on_start only recomputes the indicator cache; it NEVER resets
        # _zones, so active zones are not destroyed when the MTF engine
        # calls on_start again on each new bar close.
        self._zones = []          # list of active unfilled zones
        self._cache = None        # indicator arrays (rebuilt in on_start)
        self._bar_seconds = None  # TF duration in seconds (for time-based expiry)

    # ─── Indicator Pre-computation ──────────────────────────────
    def on_start(self, data: pd.DataFrame, htf_data=None):
        """
        Called ONCE before the bar loop begins, and again by the MTF live
        engine whenever new bars arrive (cache recalibration).

        IMPORTANT: Only the indicator cache is rebuilt here.
        self._zones is intentionally NOT reset — active zones must
        survive cache recalibrations so that zone fills are detected
        correctly across the historical→live boundary.
        """
        cfg = self.config
        close = data["close"].values.astype(float)
        high  = data["high"].values.astype(float)
        low   = data["low"].values.astype(float)
        n = len(close)

        # ── EMA ─────────────────────────────────────────────────
        def ema(series, period):
            result = np.full(len(series), np.nan)
            if len(series) < period:
                return result
            k = 2.0 / (period + 1)
            result[period - 1] = np.mean(series[:period])
            for i in range(period, len(series)):
                result[i] = series[i] * k + result[i - 1] * (1 - k)
            return result

        # ── ATR (Wilder's smoothing, matches MT5/TradingView) ───
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        atr = np.full(n, np.nan)
        if n >= cfg.atr_period:
            atr[cfg.atr_period - 1] = np.mean(tr[:cfg.atr_period])
            for i in range(cfg.atr_period, n):
                atr[i] = (atr[i - 1] * (cfg.atr_period - 1) + tr[i]) / cfg.atr_period

        self._cache = {
            "ema_fast": ema(close, cfg.fast_period),
            "ema_slow": ema(close, cfg.slow_period),
            "atr": atr,
            "tr": tr,
        }

        # ── Bar duration (seconds) — used for time-based zone expiry ──
        # Compute from the first two bars of data. Robust to any TF.
        if n >= 2:
            try:
                t0 = data.iloc[0]["time"]
                t1 = data.iloc[1]["time"]
                delta = (t1 - t0)
                # Works for both pd.Timedelta and datetime.timedelta
                secs = delta.total_seconds() if hasattr(delta, "total_seconds") else float(delta) / 1e9
                self._bar_seconds = secs if secs > 0 else None
            except Exception:
                self._bar_seconds = None

        # NOTE: self._zones deliberately NOT reset here.
        # Any active zones from a prior historical scan or live poll
        # must remain valid after cache recalibration.

    # ─── Bar-by-bar Logic ───────────────────────────────────────
    def on_bar(self, index: int, data: pd.DataFrame):
        """
        Called on EVERY bar. Reads from self._cache only.

        Flow:
          1. Determine pulse (EMA relationship)
          2. Detect EMA 50 crossover + candle color → create zone
          3. Expire old zones (time-based, index-agnostic)
          4. Check existing zones for fills → generate signal
        """
        cfg   = self.config
        cache = getattr(self, "_cache", None)
        if cache is None:
            return "HOLD"

        # Need at least slow_period + 1 bars for crossover detection
        min_bars = cfg.slow_period + 1
        if index < min_bars:
            return "HOLD"

        ef  = cache["ema_fast"]
        es  = cache["ema_slow"]
        atr = cache["atr"]
        tr  = cache["tr"]

        # Guard against NaN indicators
        if np.isnan(ef[index]) or np.isnan(es[index]) or np.isnan(atr[index]):
            return "HOLD"
        if np.isnan(ef[index - 1]) or np.isnan(es[index - 1]):
            return "HOLD"

        bar      = data.iloc[index]
        prev_bar = data.iloc[index - 1]

        close       = float(bar["close"])
        open_price  = float(bar["open"])
        high        = float(bar["high"])
        low         = float(bar["low"])
        prev_close  = float(prev_bar["close"])
        current_time = bar["time"]  # absolute Pandas Timestamp — index-agnostic

        ema_fast_now = ef[index]
        ema_slow_now = es[index]
        ema_slow_prev = es[index - 1]
        atr_now  = atr[index]
        tr_now   = tr[index]

        # ── Step 1: Pulse detection ─────────────────────────────
        if ema_fast_now > ema_slow_now:
            pulse = "positive"
        elif ema_fast_now < ema_slow_now:
            pulse = "negative"
        else:
            pulse = None  # crossover — no action

        # ── Step 2: Candle color ────────────────────────────────
        is_green = close > open_price
        is_red   = close < open_price

        # ── Step 3: Zone creation on EMA 50 crossover ───────────
        # BUY zone: price crosses ABOVE EMA 50 + positive pulse + green candle
        if (pulse == "positive"
                and is_green
                and prev_close <= ema_slow_prev
                and close > ema_slow_now
                and cfg.trade_direction in ("both", "long_only")):

            zone_price = close - atr_now
            self._zones.append({
                "type":             "buy",
                "zone_price":       zone_price,
                "atr_at_creation":  atr_now,
                "created_time":     current_time,   # absolute time — survives reindex
            })

        # SELL zone: price crosses BELOW EMA 50 + negative pulse + red candle
        if (pulse == "negative"
                and is_red
                and prev_close >= ema_slow_prev
                and close < ema_slow_now
                and cfg.trade_direction in ("both", "short_only")):

            zone_price = close + atr_now
            self._zones.append({
                "type":             "sell",
                "zone_price":       zone_price,
                "atr_at_creation":  atr_now,
                "created_time":     current_time,
            })

        # ── Step 4: Expire old zones (time-based, NOT index-based) ──
        # Using absolute timestamps avoids stale indices after DataFrame
        # trim + reset_index in the MTF live engine's process_latest_data.
        bar_secs = self._bar_seconds
        if bar_secs and bar_secs > 0:
            self._zones = [
                z for z in self._zones
                if (current_time - z["created_time"]).total_seconds() / bar_secs
                   <= cfg.zone_validity_bars
            ]
        # If bar_secs not yet computed (very short data), skip expiry for now.

        # ── Step 5: Check zone fills ────────────────────────────
        # TR/ATR filter applies to the whole bar — skip all zones if volatile
        if tr_now > atr_now * cfg.tr_atr_filter:
            return "HOLD"

        # Process oldest zone first (FIFO)
        for zone in list(self._zones):  # iterate copy — safe to mutate original
            # Skip zones created on this exact bar (retrace must be a later bar)
            if zone["created_time"] == current_time:
                continue

            zone_atr = zone["atr_at_creation"]

            if zone["type"] == "buy":
                if low <= zone["zone_price"]:
                    entry = zone["zone_price"]
                    sl    = entry - zone_atr
                    risk  = entry - sl
                    if risk <= 0:
                        continue
                    tp = entry + (risk * cfg.rr_ratio)
                    self._zones.remove(zone)
                    return ("BUY", round(sl, 6), round(tp, 6))

            elif zone["type"] == "sell":
                if high >= zone["zone_price"]:
                    entry = zone["zone_price"]
                    sl    = entry + zone_atr
                    risk  = sl - entry
                    if risk <= 0:
                        continue
                    tp = entry - (risk * cfg.rr_ratio)
                    self._zones.remove(zone)
                    return ("SELL", round(sl, 6), round(tp, 6))

        return "HOLD"

    # ─── Indicator Overlay for Chart ────────────────────────────
    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """
        Return indicators for chart overlay.
        EMA lines on price pane, ATR in separate oscillator pane.
        """
        cache = getattr(self, "_cache", None)
        if not cache:
            return {}

        cfg = self.config

        def to_list(arr):
            return [None if np.isnan(v) else round(float(v), 6) for v in arr]

        return {
            f"EMA {cfg.fast_period}": to_list(cache["ema_fast"]),
            f"EMA {cfg.slow_period}": to_list(cache["ema_slow"]),
            "ATR oscillator": to_list(cache["atr"]),
        }
