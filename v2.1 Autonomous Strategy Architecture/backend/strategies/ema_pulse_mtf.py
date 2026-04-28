"""
EMA Pulse MTF Strategy
======================
Based on a 3-EMA pulse system (EMA 20 / 50 / 200) combined with
ATR-based entry zones and candle-color confirmation.

LOGIC SUMMARY
─────────────
1. Pulse (from HTF):
   • EMA 20 > EMA 50  →  Positive pulse  (uptrend)
   • EMA 20 < EMA 50  →  Negative pulse  (downtrend)
   • Equal            →  Crossover / no signal

2. Entry confirmation (on M1):
   • Positive pulse + Price > EMA 50 + Green candle  →  BUY zone
   • Negative pulse + Price < EMA 50 + Red  candle   →  SELL zone

3. Zone price (ATR-based):
   • BUY  entry zone = Close − ATR   ("wholesale" / discounted entry)
   • SELL entry zone = Close + ATR   ("premium" / elevated entry)

4. SL / TP:
   • BUY  : SL = entry_zone − 0.5 × ATR  |  TP = entry + RR × risk
   • SELL : SL = entry_zone + 0.5 × ATR  |  TP = entry − RR × risk

5. EMA 200 acts as a macro-trend filter (optional guard).
"""

from __future__ import annotations

from strategies._template import BaseStrategy, StrategyConfig, Signal, HOLD, TF_DURATION
from pydantic import Field
from typing import Literal
import numpy as np
import pandas as pd


# ── Timeframe helpers ────────────────────────────────────────────────────────

TF_RULE: dict[str, str] = {
    "M5":  "5min",
    "M15": "15min",
    "M30": "30min",
    "H1":  "1h",
    "H4":  "4h",
    "D1":  "1D",
}


# ── Config ───────────────────────────────────────────────────────────────────

class EMAPulseConfig(StrategyConfig):
    """All parameters auto-generate UI widgets in the MTF Tester panel."""

    htf: Literal["M5", "M15", "M30", "H1", "H4", "D1"] = Field(
        "H1",
        description="Higher Timeframe — used to determine the EMA pulse direction",
    )

    ema_fast: int = Field(
        20, ge=2, le=500,
        description="Fast EMA period (default 20)",
    )
    ema_slow: int = Field(
        50, ge=2, le=500,
        description="Slow EMA period (default 50)",
    )
    ema_trend: int = Field(
        200, ge=2, le=500,
        description="Trend EMA period (default 200) — macro filter on M1",
    )

    atr_period: int = Field(
        14, ge=1, le=100,
        description="ATR period for zone calculation",
    )
    atr_sl_multiplier: float = Field(
        0.5, ge=0.1, le=5.0,
        description="ATR multiplier beyond zone for Stop Loss",
    )

    rr_ratio: float = Field(
        2.0, ge=0.5, le=20.0,
        description="Risk / Reward ratio (e.g. 2.0 = 1:2)",
    )

    use_trend_filter: bool = Field(
        True,
        description="Enable EMA 200 macro-trend filter on M1",
    )

    direction: Literal["both", "long_only", "short_only"] = Field(
        "both",
        description="Allowed trade directions",
    )


# ── Strategy ─────────────────────────────────────────────────────────────────

class EMAPulseStrategy(BaseStrategy):
    name         = "EMA Pulse MTF"
    description  = (
        "Multi-timeframe pulse strategy: EMA 20/50 pulse on HTF, "
        "ATR-zone entry + candle-colour confirmation on M1."
    )
    config_model = EMAPulseConfig

    # ── on_start ─────────────────────────────────────────────────────────────

    def on_start(self, data: pd.DataFrame) -> None:
        cfg = self.config

        # ── HTF layer ────────────────────────────────────────────────────────
        htf          = self._resample(data, TF_RULE[cfg.htf])
        htf_duration = TF_DURATION[cfg.htf]
        htf_close    = htf["close"].values.astype(float)

        htf_ema_fast = _ema(htf_close, cfg.ema_fast)
        htf_ema_slow = _ema(htf_close, cfg.ema_slow)

        # Pulse array:  1 = positive (uptrend),  -1 = negative (downtrend),  0 = crossover
        htf_pulse = np.zeros(len(htf_close), dtype=np.int8)
        for i in range(len(htf_close)):
            f, s = htf_ema_fast[i], htf_ema_slow[i]
            if np.isnan(f) or np.isnan(s):
                htf_pulse[i] = 0
            elif f > s:
                htf_pulse[i] = 1
            elif f < s:
                htf_pulse[i] = -1
            # else 0 (crossover)

        # Look-ahead-safe M1 → HTF mapping
        m1_to_htf = self._m1_to_completed_htf_index(
            data["time"], htf["time"], htf_duration
        )

        # ── M1 layer ─────────────────────────────────────────────────────────
        m1_open  = data["open"].values.astype(float)
        m1_high  = data["high"].values.astype(float)
        m1_low   = data["low"].values.astype(float)
        m1_close = data["close"].values.astype(float)

        m1_ema_fast  = _ema(m1_close, cfg.ema_fast)
        m1_ema_slow  = _ema(m1_close, cfg.ema_slow)
        m1_ema_trend = _ema(m1_close, cfg.ema_trend)
        m1_atr       = _atr(m1_high, m1_low, m1_close, cfg.atr_period)

        self._cache = {
            # HTF
            "htf_pulse":   htf_pulse,
            "m1_to_htf":   m1_to_htf,
            "htf_times":   htf["time"].values,   # for scanner dedup
            # M1
            "m1_open":      m1_open,
            "m1_high":      m1_high,
            "m1_low":       m1_low,
            "m1_close":     m1_close,
            "m1_ema_fast":  m1_ema_fast,
            "m1_ema_slow":  m1_ema_slow,
            "m1_ema_trend": m1_ema_trend,
            "m1_atr":       m1_atr,
        }

    # ── on_bar ───────────────────────────────────────────────────────────────

    def on_bar(self, index: int, data: pd.DataFrame) -> Signal:
        cfg   = self.config
        cache = getattr(self, "_cache", None)

        if cache is None or index < 2:
            return HOLD

        # ── Resolve HTF pulse ─────────────────────────────────────────────
        h_idx = cache["m1_to_htf"][index]
        if h_idx < 1:
            return HOLD   # need at least one completed HTF bar

        pulse = int(cache["htf_pulse"][h_idx])
        if pulse == 0:
            return HOLD   # crossover — wait

        # ── Read M1 indicators ────────────────────────────────────────────
        ef    = cache["m1_ema_fast"][index]
        es    = cache["m1_ema_slow"][index]
        et    = cache["m1_ema_trend"][index]
        atr   = cache["m1_atr"][index]
        close = cache["m1_close"][index]
        open_ = cache["m1_open"][index]
        high  = cache["m1_high"][index]
        low   = cache["m1_low"][index]

        if any(np.isnan(v) for v in (ef, es, atr)):
            return HOLD
        if cfg.use_trend_filter and np.isnan(et):
            return HOLD

        # ── Candle colour & price position ────────────────────────────────
        is_green         = close > open_
        is_red           = close < open_
        price_above_ema50 = close > es
        price_below_ema50 = close < es

        # ── Macro trend filter (EMA 200) ──────────────────────────────────
        macro_up   = (not cfg.use_trend_filter) or (close > et)
        macro_down = (not cfg.use_trend_filter) or (close < et)

        # ── BUY signal ────────────────────────────────────────────────────
        if (
            pulse == 1
            and price_above_ema50
            and is_green
            and macro_up
            and cfg.direction in ("both", "long_only")
        ):
            entry_zone = close - atr                              # wholesale entry
            sl         = entry_zone - cfg.atr_sl_multiplier * atr
            risk       = entry_zone - sl
            tp         = entry_zone + cfg.rr_ratio * risk

            if sl <= 0 or tp <= 0 or sl >= entry_zone:
                return HOLD

            return Signal(
                direction="BUY",
                sl=round(sl, 6),
                tp=round(tp, 6),
                metadata={
                    "pulse":       "Positive",
                    "entry_zone":  round(entry_zone, 6),
                    "ema_fast_htf": "above slow",
                    "atr":         round(atr, 6),
                },
            )

        # ── SELL signal ───────────────────────────────────────────────────
        if (
            pulse == -1
            and price_below_ema50
            and is_red
            and macro_down
            and cfg.direction in ("both", "short_only")
        ):
            entry_zone = close + atr                              # premium entry
            sl         = entry_zone + cfg.atr_sl_multiplier * atr
            risk       = sl - entry_zone
            tp         = entry_zone - cfg.rr_ratio * risk

            if sl <= 0 or tp <= 0 or sl <= entry_zone:
                return HOLD

            return Signal(
                direction="SELL",
                sl=round(sl, 6),
                tp=round(tp, 6),
                metadata={
                    "pulse":       "Negative",
                    "entry_zone":  round(entry_zone, 6),
                    "ema_fast_htf": "below slow",
                    "atr":         round(atr, 6),
                },
            )

        return HOLD

    # ── Chart overlay ─────────────────────────────────────────────────────────

    def get_indicator_data(self, data: pd.DataFrame) -> dict:
        """Returns EMA lines for chart overlay in the tester UI."""
        cache = getattr(self, "_cache", {})
        return {
            "EMA 20":  _to_list(cache.get("m1_ema_fast")),
            "EMA 50":  _to_list(cache.get("m1_ema_slow")),
            "EMA 200": _to_list(cache.get("m1_ema_trend")),
        }


# ── Pure helpers (module-level, no self) ─────────────────────────────────────

def _ema(series: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average — Wilder-style seed (SMA for first value)."""
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = float(np.mean(series[:period]))
    for i in range(period, len(series)):
        result[i] = series[i] * k + result[i - 1] * (1 - k)
    return result


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Average True Range — RMA (Wilder) smoothing."""
    n  = len(close)
    tr = np.full(n, np.nan)
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr
    atr[period] = float(np.nanmean(tr[1 : period + 1]))
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def _to_list(arr) -> list:
    if arr is None:
        return []
    return [None if np.isnan(v) else float(v) for v in arr]
